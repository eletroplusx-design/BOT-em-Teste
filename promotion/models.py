from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from domain.serialization import serialize_value
from domain.validation import DomainValidationError
from validation.models import FrozenSelection, SegmentMetrics, WalkForwardResult, WalkForwardWindowResult

from .artifacts import promotion_hash
from .errors import PromotionDecisionError, PromotionPolicyError, PromotionValidationError


class PromotionStatus(str, Enum):
    REJECTED = "REJECTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    APPROVED_FOR_MONITORED_PAPER = "APPROVED_FOR_MONITORED_PAPER"
    PAPER_SUSPENDED = "PAPER_SUSPENDED"


def _require_timezone_aware(dt: datetime, field_name: str) -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise PromotionValidationError(f"{field_name} must be timezone-aware.")
    return dt.astimezone(timezone.utc)


def _to_decimal(value: Any, field_name: str, *, allow_none: bool = False) -> Decimal | None:
    if value is None:
        if allow_none:
            return None
        raise PromotionPolicyError(f"{field_name} is required.")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise PromotionPolicyError(f"{field_name} must be numeric.") from exc


def _strict_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise PromotionPolicyError(f"{field_name} must be an integer.")
    if allow_zero and value < 0:
        raise PromotionPolicyError(f"{field_name} cannot be negative.")
    if not allow_zero and value <= 0:
        raise PromotionPolicyError(f"{field_name} must be greater than zero.")
    return int(value)


@dataclass(frozen=True, slots=True)
class PromotionCriterionResult:
    name: str
    passed: bool
    expected: Any
    actual: Any
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name).strip())
        object.__setattr__(self, "reason", str(self.reason).strip())
        if not self.name:
            raise PromotionValidationError("criterion name is required.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "expected": self.expected,
            "actual": self.actual,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    status: PromotionStatus
    frozen_selection: FrozenSelection
    strategy_version: str
    symbol: str
    interval: str
    phase5_manifest: dict[str, Any]
    evidence_hash: str
    policy_hash: str
    decision_hash: str
    criteria_evaluated: tuple[PromotionCriterionResult, ...]
    reasons: tuple[str, ...]
    recalculated_metrics: dict[str, Any]
    paper_limits: dict[str, Any]
    timestamp_utc: datetime
    paper_limits_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.frozen_selection, FrozenSelection):
            raise PromotionDecisionError("frozen_selection must be a FrozenSelection instance.")
        object.__setattr__(self, "status", PromotionStatus(self.status))
        object.__setattr__(self, "strategy_version", str(self.strategy_version).strip())
        object.__setattr__(self, "symbol", str(self.symbol).strip().upper())
        object.__setattr__(self, "interval", str(self.interval).strip())
        object.__setattr__(self, "phase5_manifest", dict(self.phase5_manifest))
        object.__setattr__(self, "evidence_hash", str(self.evidence_hash))
        object.__setattr__(self, "policy_hash", str(self.policy_hash))
        object.__setattr__(self, "decision_hash", str(self.decision_hash))
        object.__setattr__(self, "criteria_evaluated", tuple(self.criteria_evaluated))
        object.__setattr__(self, "reasons", tuple(str(reason) for reason in self.reasons))
        object.__setattr__(self, "recalculated_metrics", dict(self.recalculated_metrics))
        object.__setattr__(self, "paper_limits", dict(self.paper_limits))
        object.__setattr__(self, "paper_limits_hash", str(self.paper_limits_hash).strip() or promotion_hash(self.paper_limits))
        object.__setattr__(self, "timestamp_utc", _require_timezone_aware(self.timestamp_utc, "timestamp_utc"))
        if not self.evidence_hash:
            raise PromotionDecisionError("evidence_hash is required.")
        if not self.policy_hash:
            raise PromotionDecisionError("policy_hash is required.")
        if not self.decision_hash:
            raise PromotionDecisionError("decision_hash is required.")
        if self.paper_limits_hash != promotion_hash(self.paper_limits):
            raise PromotionDecisionError("paper_limits hash mismatch.")
        if self.status == PromotionStatus.APPROVED_FOR_MONITORED_PAPER:
            if not self.criteria_evaluated:
                raise PromotionDecisionError("approved decisions require evaluated criteria.")
            if any(not criterion.passed for criterion in self.criteria_evaluated):
                raise PromotionDecisionError("approved decisions cannot include failed criteria.")
            required_flags = {
                "kill_switch_required": True,
                "live_trading_permanently_disabled": True,
            }
            for key, expected in required_flags.items():
                if self.paper_limits.get(key) is not expected:
                    raise PromotionDecisionError(f"{key} must be {expected}.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "frozen_selection": self.frozen_selection.as_dict(),
            "strategy_version": self.strategy_version,
            "symbol": self.symbol,
            "interval": self.interval,
            "phase5_manifest": serialize_value(self.phase5_manifest),
            "evidence_hash": self.evidence_hash,
            "policy_hash": self.policy_hash,
            "decision_hash": self.decision_hash,
            "criteria_evaluated": [criterion.as_dict() for criterion in self.criteria_evaluated],
            "reasons": list(self.reasons),
            "recalculated_metrics": serialize_value(self.recalculated_metrics),
            "paper_limits": serialize_value(self.paper_limits),
            "paper_limits_hash": self.paper_limits_hash,
            "timestamp_utc": self.timestamp_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
