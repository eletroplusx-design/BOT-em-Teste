from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from domain.serialization import serialize_value
from .artifacts import promotion_hash
from .errors import PromotionDecisionError, PromotionPolicyError
from .models import PromotionDecision, PromotionStatus


def _strict_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise PromotionPolicyError(f"{field_name} must be an integer.")
    if allow_zero and value < 0:
        raise PromotionPolicyError(f"{field_name} cannot be negative.")
    if not allow_zero and value <= 0:
        raise PromotionPolicyError(f"{field_name} must be greater than zero.")
    return int(value)


def _to_decimal(value: Any, field_name: str, *, allow_zero: bool = True) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    else:
        try:
            result = Decimal(str(value))
        except Exception as exc:
            raise PromotionPolicyError(f"{field_name} must be numeric.") from exc
    if not result.is_finite():
        raise PromotionPolicyError(f"{field_name} must be finite.")
    if allow_zero:
        if result < 0:
            raise PromotionPolicyError(f"{field_name} cannot be negative.")
    elif result <= 0:
        raise PromotionPolicyError(f"{field_name} must be greater than zero.")
    return result


@dataclass(frozen=True, slots=True)
class MonitoredPaperLimits:
    paper_capital_max: Decimal = Decimal("10000")
    risk_per_trade_max_percent: Decimal = Decimal("1")
    max_positions: int = 1
    session_drawdown_max_percent: Decimal = Decimal("10")
    max_loss_streak: int = 3
    max_duration_hours: int = 8
    min_trades: int = 1
    max_trades: int = 100
    expired_data_policy: str = "BLOCK_AND_SUSPEND"
    suspension_policy: str = "AUTO_SUSPEND"
    kill_switch_required: bool = True
    live_trading_permanently_disabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "paper_capital_max", _to_decimal(self.paper_capital_max, "paper_capital_max"))
        object.__setattr__(self, "risk_per_trade_max_percent", _to_decimal(self.risk_per_trade_max_percent, "risk_per_trade_max_percent"))
        object.__setattr__(self, "max_positions", _strict_int(self.max_positions, "max_positions"))
        object.__setattr__(self, "session_drawdown_max_percent", _to_decimal(self.session_drawdown_max_percent, "session_drawdown_max_percent"))
        object.__setattr__(self, "max_loss_streak", _strict_int(self.max_loss_streak, "max_loss_streak"))
        object.__setattr__(self, "max_duration_hours", _strict_int(self.max_duration_hours, "max_duration_hours"))
        object.__setattr__(self, "min_trades", _strict_int(self.min_trades, "min_trades"))
        object.__setattr__(self, "max_trades", _strict_int(self.max_trades, "max_trades"))
        object.__setattr__(self, "expired_data_policy", str(self.expired_data_policy).strip().upper())
        object.__setattr__(self, "suspension_policy", str(self.suspension_policy).strip().upper())
        if self.kill_switch_required is not True:
            raise PromotionPolicyError("kill_switch_required must be True.")
        if self.live_trading_permanently_disabled is not True:
            raise PromotionPolicyError("live_trading_permanently_disabled must be True.")
        if self.max_trades < self.min_trades:
            raise PromotionPolicyError("max_trades must be greater than or equal to min_trades.")
        if self.expired_data_policy not in {"BLOCK", "SUSPEND", "BLOCK_AND_SUSPEND"}:
            raise PromotionPolicyError("expired_data_policy is invalid.")
        if self.suspension_policy not in {"AUTO_SUSPEND", "BLOCK_ONLY", "SUSPEND"}:
            raise PromotionPolicyError("suspension_policy is invalid.")

    @property
    def live_trading_allowed(self) -> bool:
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "paper_capital_max": self.paper_capital_max,
            "risk_per_trade_max_percent": self.risk_per_trade_max_percent,
            "max_positions": self.max_positions,
            "session_drawdown_max_percent": self.session_drawdown_max_percent,
            "max_loss_streak": self.max_loss_streak,
            "max_duration_hours": self.max_duration_hours,
            "min_trades": self.min_trades,
            "max_trades": self.max_trades,
            "expired_data_policy": self.expired_data_policy,
            "suspension_policy": self.suspension_policy,
            "kill_switch_required": self.kill_switch_required,
            "live_trading_permanently_disabled": self.live_trading_permanently_disabled,
        }


@dataclass(frozen=True, slots=True)
class PaperMonitoringSnapshot:
    timestamp_utc: datetime
    decision_hash: str
    evidence_hash: str
    strategy_version: str
    configuration: dict[str, Any]
    trading_mode: str
    data_fresh: bool
    session_drawdown_percent: Decimal
    current_loss_streak: int
    open_positions: int
    executed_trades: int
    observed_costs: dict[str, Any]
    internal_error: str | None = None
    attempted_live: bool = False
    snapshot_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp_utc", self.timestamp_utc.astimezone(timezone.utc))
        object.__setattr__(self, "session_drawdown_percent", _to_decimal(self.session_drawdown_percent, "session_drawdown_percent"))
        object.__setattr__(self, "decision_hash", str(self.decision_hash).strip())
        object.__setattr__(self, "evidence_hash", str(self.evidence_hash).strip())
        object.__setattr__(self, "strategy_version", str(self.strategy_version).strip())
        object.__setattr__(self, "trading_mode", str(self.trading_mode).strip().upper())
        object.__setattr__(self, "configuration", dict(self.configuration))
        object.__setattr__(self, "observed_costs", dict(self.observed_costs))
        object.__setattr__(self, "current_loss_streak", _strict_int(self.current_loss_streak, "current_loss_streak", allow_zero=True))
        object.__setattr__(self, "open_positions", _strict_int(self.open_positions, "open_positions", allow_zero=True))
        object.__setattr__(self, "executed_trades", _strict_int(self.executed_trades, "executed_trades", allow_zero=True))
        if not self.snapshot_hash:
            object.__setattr__(self, "snapshot_hash", promotion_hash(self.as_hash_payload()))

    def as_hash_payload(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "decision_hash": self.decision_hash,
            "evidence_hash": self.evidence_hash,
            "strategy_version": self.strategy_version,
            "configuration": self.configuration,
            "trading_mode": self.trading_mode,
            "data_fresh": self.data_fresh,
            "session_drawdown_percent": self.session_drawdown_percent,
            "current_loss_streak": self.current_loss_streak,
            "open_positions": self.open_positions,
            "executed_trades": self.executed_trades,
            "observed_costs": self.observed_costs,
            "internal_error": self.internal_error,
            "attempted_live": self.attempted_live,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "decision_hash": self.decision_hash,
            "evidence_hash": self.evidence_hash,
            "strategy_version": self.strategy_version,
            "configuration": serialize_value(self.configuration),
            "trading_mode": self.trading_mode,
            "data_fresh": self.data_fresh,
            "session_drawdown_percent": self.session_drawdown_percent,
            "current_loss_streak": self.current_loss_streak,
            "open_positions": self.open_positions,
            "executed_trades": self.executed_trades,
            "observed_costs": serialize_value(self.observed_costs),
            "internal_error": self.internal_error,
            "attempted_live": self.attempted_live,
            "snapshot_hash": self.snapshot_hash,
        }


@dataclass(frozen=True, slots=True)
class PaperMonitoringDecision:
    status: PromotionStatus
    decision_hash: str
    evidence_hash: str
    snapshot_hash: str
    paper_limits: dict[str, Any]
    reasons: tuple[str, ...]
    timestamp_utc: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", PromotionStatus(self.status))
        object.__setattr__(self, "decision_hash", str(self.decision_hash).strip())
        object.__setattr__(self, "evidence_hash", str(self.evidence_hash).strip())
        object.__setattr__(self, "snapshot_hash", str(self.snapshot_hash).strip())
        object.__setattr__(self, "paper_limits", dict(self.paper_limits))
        object.__setattr__(self, "reasons", tuple(str(reason) for reason in self.reasons))
        object.__setattr__(self, "timestamp_utc", self.timestamp_utc.astimezone(timezone.utc))
        if not self.decision_hash or not self.evidence_hash or not self.snapshot_hash:
            raise PromotionDecisionError("monitoring hashes are required.")
        if self.status == PromotionStatus.APPROVED_FOR_MONITORED_PAPER:
            if self.paper_limits.get("kill_switch_required") is not True:
                raise PromotionDecisionError("monitoring approval requires kill_switch_required.")
            if self.paper_limits.get("live_trading_permanently_disabled") is not True:
                raise PromotionDecisionError("monitoring approval requires live trading permanently disabled.")


def _monitoring_snapshot_hash(snapshot: PaperMonitoringSnapshot) -> str:
    return promotion_hash(snapshot.as_hash_payload())


def _suspend(reason: str, decision: PromotionDecision, snapshot: PaperMonitoringSnapshot, limits: MonitoredPaperLimits) -> PaperMonitoringDecision:
    return PaperMonitoringDecision(
        status=PromotionStatus.PAPER_SUSPENDED,
        decision_hash=decision.decision_hash,
        evidence_hash=decision.evidence_hash,
        snapshot_hash=_monitoring_snapshot_hash(snapshot),
        paper_limits=limits.as_dict(),
        reasons=(reason,),
        timestamp_utc=datetime.now(timezone.utc),
    )


def evaluate_paper_monitoring(
    decision: PromotionDecision,
    snapshot: PaperMonitoringSnapshot,
    limits: MonitoredPaperLimits | None = None,
) -> PaperMonitoringDecision:
    limits = limits or MonitoredPaperLimits()
    if not isinstance(decision, PromotionDecision):
        raise PromotionDecisionError("promotion decision is required.")
    if decision.status is not PromotionStatus.APPROVED_FOR_MONITORED_PAPER:
        raise PromotionDecisionError("only approved monitored paper decisions can be monitored.")
    if not isinstance(snapshot, PaperMonitoringSnapshot):
        raise PromotionDecisionError("paper monitoring snapshot is required.")
    if snapshot.snapshot_hash != _monitoring_snapshot_hash(snapshot):
        return _suspend("snapshot hash mismatch", decision, snapshot, limits)
    if snapshot.decision_hash != decision.decision_hash or snapshot.evidence_hash != decision.evidence_hash:
        return _suspend("hash divergence", decision, snapshot, limits)
    expected_configuration = decision.frozen_selection.as_dict()
    if serialize_value(snapshot.configuration) != serialize_value(expected_configuration):
        return _suspend("configuration divergence", decision, snapshot, limits)
    if snapshot.strategy_version != decision.strategy_version or snapshot.trading_mode != "PAPER":
        return _suspend("strategy or mode divergence", decision, snapshot, limits)
    if snapshot.internal_error:
        return _suspend("internal error", decision, snapshot, limits)
    if snapshot.attempted_live:
        return _suspend("live trading attempt", decision, snapshot, limits)
    if not snapshot.data_fresh:
        return _suspend("stale or invalid data", decision, snapshot, limits)
    if snapshot.session_drawdown_percent > limits.session_drawdown_max_percent:
        return _suspend("session drawdown exceeded", decision, snapshot, limits)
    if snapshot.current_loss_streak > limits.max_loss_streak:
        return _suspend("loss streak exceeded", decision, snapshot, limits)
    if snapshot.open_positions > limits.max_positions:
        return _suspend("open positions exceeded", decision, snapshot, limits)
    if snapshot.executed_trades < limits.min_trades or snapshot.executed_trades > limits.max_trades:
        return _suspend("trade count outside limits", decision, snapshot, limits)
    expected_costs = decision.phase5_manifest.get("execution_contract", {})
    for key, observed in snapshot.observed_costs.items():
        expected = expected_costs.get(key)
        if expected is None:
            continue
        try:
            if Decimal(str(observed)) > Decimal(str(expected)):
                return _suspend(f"observed cost too high: {key}", decision, snapshot, limits)
        except Exception:
            return _suspend(f"invalid observed cost: {key}", decision, snapshot, limits)
    return PaperMonitoringDecision(
        status=PromotionStatus.APPROVED_FOR_MONITORED_PAPER,
        decision_hash=decision.decision_hash,
        evidence_hash=decision.evidence_hash,
        snapshot_hash=snapshot.snapshot_hash,
        paper_limits=limits.as_dict(),
        reasons=(),
        timestamp_utc=datetime.now(timezone.utc),
    )
