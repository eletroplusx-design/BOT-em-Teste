from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from domain.serialization import serialize_value
from validation import WalkForwardResult
from validation.artifacts import manifest_hash as validation_manifest_hash
from validation.models import CandidateConfig, CandidateEvaluation, FrozenSelection, SegmentMetrics, WalkForwardWindowResult, WindowBounds

from ._operational import load_latest_operational_cohort_contract
from .adapters import evaluate_paper_sessions_from_storage
from .artifacts import paper_evaluation_hash
from .errors import (
    PaperCampaignError,
    PaperCampaignManifestError,
    PaperCampaignPolicyError,
    PaperCampaignReadError,
    PaperEvaluationDecisionError,
    PaperEvaluationManifestError,
    PaperEvaluationPolicyError,
    PaperEvaluationReadError,
)
from .evaluator import _ensure_walk_forward_reference
from .models import PaperEvaluationPolicy, PaperEvaluationReport, PaperEvaluationStatus


_CAMPAIGN_CONSTRUCTION_MODE: ContextVar[str] = ContextVar("campaign_construction_mode", default="public")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_str(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise PaperCampaignManifestError(f"{field_name} must be a string.")
    text = value.strip()
    if not text and not allow_empty:
        raise PaperCampaignManifestError(f"{field_name} must be a non-empty string.")
    return text


def _require_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise PaperCampaignManifestError(f"{field_name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise PaperCampaignManifestError(f"{field_name} must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _require_now_utc(value: datetime | None, field_name: str = "now") -> datetime:
    if value is None:
        return _utcnow()
    return _require_datetime(value, field_name)


def _require_decimal(value: Any, field_name: str, *, allow_negative: bool = False) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    else:
        try:
            result = Decimal(str(value))
        except Exception as exc:
            raise PaperCampaignPolicyError(f"{field_name} must be numeric.") from exc
    if not result.is_finite():
        raise PaperCampaignPolicyError(f"{field_name} must be finite.")
    if not allow_negative and result < 0:
        raise PaperCampaignPolicyError(f"{field_name} cannot be negative.")
    return result


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise PaperCampaignPolicyError(f"{field_name} must be boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise PaperCampaignPolicyError(f"{field_name} must be an integer.")
    if allow_zero and value < 0:
        raise PaperCampaignPolicyError(f"{field_name} cannot be negative.")
    if not allow_zero and value <= 0:
        raise PaperCampaignPolicyError(f"{field_name} must be greater than zero.")
    return int(value)


def _validate_policy_floor(policy: PaperEvaluationPolicy) -> tuple[str, ...]:
    reasons: list[str] = []
    if policy.min_sessions_completed < 10:
        reasons.append("min_sessions_completed below operational floor.")
    if policy.min_distinct_days < 20:
        reasons.append("min_distinct_days below operational floor.")
    if policy.min_trades < 100:
        reasons.append("min_trades below operational floor.")
    if policy.min_duration_hours < Decimal("480"):
        reasons.append("min_duration_hours below operational floor.")
    if policy.max_drawdown_percent > Decimal("15"):
        reasons.append("max_drawdown_percent above operational floor.")
    min_profit_factor = getattr(policy, "min_profit_factor", None)
    if min_profit_factor is None:
        reasons.append("min_profit_factor below operational floor.")
    elif min_profit_factor < Decimal("1.10"):
        reasons.append("min_profit_factor below operational floor.")
    if policy.min_expectancy < Decimal("0"):
        reasons.append("min_expectancy below operational floor.")
    if policy.min_net_return_percent < Decimal("0"):
        reasons.append("min_net_return_percent below operational floor.")
    if policy.max_suspended_sessions != 0:
        reasons.append("max_suspended_sessions must be zero.")
    if policy.require_zero_live_attempts is not True:
        reasons.append("require_zero_live_attempts must be true.")
    if policy.require_audit_chain is not True:
        reasons.append("require_audit_chain must be true.")
    if policy.require_fresh_data is not True:
        reasons.append("require_fresh_data must be true.")
    if policy.min_regime_coverage < 3:
        reasons.append("min_regime_coverage below operational floor.")
    if not {"BULL", "BEAR", "CHOP"}.issubset(set(policy.required_regimes)):
        reasons.append("required_regimes must include BULL, BEAR and CHOP.")
    return tuple(reasons)


def _policy_from_payload(payload: Mapping[str, Any], policy_hash: str) -> PaperEvaluationPolicy:
    data = dict(payload)
    data["policy_hash"] = policy_hash
    return PaperEvaluationPolicy(**data)


def _reference_hashes(reference: WalkForwardResult) -> tuple[dict[str, Any], str, str]:
    payload, ref_hash = _ensure_walk_forward_reference(reference)
    manifest = reference.manifest
    manifest_hash_value = manifest.get("manifest_hash") if isinstance(manifest, Mapping) else None
    if not isinstance(manifest, Mapping) or not manifest_hash_value:
        raise PaperCampaignManifestError("walk-forward manifest is invalid.")
    result_hash = validation_manifest_hash(reference.as_dict())
    if payload.get("manifest", {}).get("manifest_hash") != manifest_hash_value:
        raise PaperCampaignManifestError("walk-forward reference hash mismatch.")
    if reference.summary.get("runner_trusted") is not True or manifest.get("runner_trusted") is not True:
        raise PaperCampaignManifestError("walk-forward reference must be runner_trusted.")
    execution_contract = manifest.get("execution_contract") if isinstance(manifest.get("execution_contract"), Mapping) else {}
    if execution_contract.get("paper_only") is not True:
        raise PaperCampaignManifestError("walk-forward reference must be paper_only.")
    if ref_hash != paper_evaluation_hash(payload):
        raise PaperCampaignManifestError("walk-forward reference payload mismatch.")
    return payload, str(manifest_hash_value), result_hash


def _policy_hash(policy: PaperEvaluationPolicy) -> str:
    return policy.policy_hash


def _reference_scope_is_compatible(
    reference_payload: Mapping[str, Any],
    *,
    strategy_version: str,
    symbol: str,
    interval: str,
) -> None:
    manifest = reference_payload.get("manifest")
    if not isinstance(manifest, Mapping):
        raise PaperCampaignManifestError("walk-forward manifest is invalid.")
    if manifest.get("strategy_version") != strategy_version:
        raise PaperCampaignManifestError("walk-forward strategy_version mismatch.")
    if manifest.get("symbol") != symbol:
        raise PaperCampaignManifestError("walk-forward symbol mismatch.")
    if manifest.get("interval") != interval:
        raise PaperCampaignManifestError("walk-forward interval mismatch.")
    execution_contract = manifest.get("execution_contract")
    if not isinstance(execution_contract, Mapping):
        raise PaperCampaignManifestError("walk-forward execution contract is invalid.")
    if execution_contract.get("paper_only") is not True:
        raise PaperCampaignManifestError("walk-forward reference must be paper_only.")
    if execution_contract.get("strategy_version") != strategy_version:
        raise PaperCampaignManifestError("walk-forward execution contract strategy mismatch.")
    if execution_contract.get("symbol") != symbol:
        raise PaperCampaignManifestError("walk-forward execution contract symbol mismatch.")
    if execution_contract.get("interval") != interval:
        raise PaperCampaignManifestError("walk-forward execution contract interval mismatch.")
    windows = reference_payload.get("windows", [])
    if not isinstance(windows, list) or not windows:
        raise PaperCampaignManifestError("walk-forward windows are required.")
    for window in windows:
        if not isinstance(window, Mapping):
            raise PaperCampaignManifestError("walk-forward window payload is invalid.")
        frozen_selection = window.get("frozen_selection")
        if frozen_selection is None:
            raise PaperCampaignManifestError("walk-forward frozen selection is required.")
        if not isinstance(frozen_selection, Mapping):
            raise PaperCampaignManifestError("walk-forward frozen selection payload is invalid.")
        if frozen_selection.get("strategy_version") != strategy_version:
            raise PaperCampaignManifestError("walk-forward frozen selection strategy mismatch.")
        if frozen_selection.get("symbol") != symbol:
            raise PaperCampaignManifestError("walk-forward frozen selection symbol mismatch.")
        if frozen_selection.get("interval") != interval:
            raise PaperCampaignManifestError("walk-forward frozen selection interval mismatch.")
        frozen_execution_contract = frozen_selection.get("execution_contract")
        if not isinstance(frozen_execution_contract, Mapping):
            raise PaperCampaignManifestError("walk-forward frozen selection execution contract is invalid.")
        if frozen_execution_contract.get("paper_only") is not True:
            raise PaperCampaignManifestError("walk-forward frozen selection must be paper_only.")
        if frozen_execution_contract.get("strategy_version") != strategy_version:
            raise PaperCampaignManifestError("walk-forward frozen selection execution contract strategy mismatch.")
        if frozen_execution_contract.get("symbol") != symbol:
            raise PaperCampaignManifestError("walk-forward frozen selection execution contract symbol mismatch.")
        if frozen_execution_contract.get("interval") != interval:
            raise PaperCampaignManifestError("walk-forward frozen selection execution contract interval mismatch.")


def _reference_from_contract(contract: "OperationalPaperCampaignContract") -> WalkForwardResult:
    reference_payload = dict(contract.reference_payload_json)
    reference = _walk_forward_from_payload(reference_payload)
    payload, manifest_hash_value, result_hash = _reference_hashes(reference)
    if serialize_value(payload) != reference_payload:
        raise PaperCampaignManifestError("walk-forward reference payload mismatch.")
    if manifest_hash_value != contract.walk_forward_manifest_hash:
        raise PaperCampaignManifestError("walk-forward manifest hash mismatch.")
    if result_hash != contract.walk_forward_result_hash:
        raise PaperCampaignManifestError("walk-forward result hash mismatch.")
    _reference_scope_is_compatible(
        reference_payload,
        strategy_version=contract.strategy_version,
        symbol=contract.symbol,
        interval=contract.interval,
    )
    return reference


def _paper_report_payload(value: Any | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if isinstance(value, Mapping):
        return serialize_value(dict(value))
    raise PaperCampaignManifestError("paper_report must be serializable.")


def _campaign_contract_payload(contract: "OperationalPaperCampaignContract") -> dict[str, Any]:
    return contract.as_dict()


def _segment_metrics_from_payload(payload: Mapping[str, Any] | None) -> SegmentMetrics | None:
    if payload is None:
        return None
    return SegmentMetrics.from_summary(payload)


def _candidate_from_payload(payload: Mapping[str, Any]) -> CandidateConfig:
    return CandidateConfig.from_mapping(str(payload.get("name", "")).strip(), dict(payload.get("parameters", {}) or {}))


def _frozen_selection_from_payload(payload: Mapping[str, Any]) -> FrozenSelection:
    return FrozenSelection(
        candidate=_candidate_from_payload(payload.get("candidate", {}) or {}),
        strategy_version=payload.get("strategy_version", ""),
        costs=tuple((payload.get("costs", {}) or {}).items()),
        execution_contract=tuple((payload.get("execution_contract", {}) or {}).items()),
        symbol=payload.get("symbol", ""),
        interval=payload.get("interval", ""),
        frozen_at=datetime.fromisoformat(str(payload.get("frozen_at", "")).replace("Z", "+00:00")),
        manifest_hash=payload.get("manifest_hash", ""),
        window_id=payload.get("window_id", ""),
    )


def _candidate_evaluation_from_payload(payload: Mapping[str, Any]) -> CandidateEvaluation:
    return CandidateEvaluation(
        candidate=_candidate_from_payload(payload.get("candidate", {}) or {}),
        train_metrics=SegmentMetrics.from_summary(payload.get("train_metrics", {})),
        validation_metrics=SegmentMetrics.from_summary(payload.get("validation_metrics", {})),
        stability_score=Decimal(str(payload.get("stability_score", 0))),
        rejection_reason=payload.get("rejection_reason"),
    )


def _window_from_payload(payload: Mapping[str, Any]) -> WalkForwardWindowResult:
    bounds = WindowBounds(**dict(payload.get("bounds", {})))
    candidate_evaluations = tuple(_candidate_evaluation_from_payload(item) for item in payload.get("candidate_evaluations", []) or [])
    selected_candidate = payload.get("selected_candidate")
    frozen_selection = payload.get("frozen_selection")
    test_metrics = payload.get("test_metrics")
    return WalkForwardWindowResult(
        bounds=bounds,
        candidate_evaluations=candidate_evaluations,
        selected_candidate=_candidate_from_payload(selected_candidate) if selected_candidate else None,
        frozen_selection=_frozen_selection_from_payload(frozen_selection) if frozen_selection else None,
        test_metrics=_segment_metrics_from_payload(test_metrics),
        manifest_hash=str(payload.get("manifest_hash", "")),
        approved=bool(payload.get("approved", False)),
        reason=str(payload.get("reason", "")),
    )


def _walk_forward_from_payload(payload: Mapping[str, Any]) -> WalkForwardResult:
    return WalkForwardResult(
        windows=tuple(_window_from_payload(item) for item in payload.get("windows", []) or []),
        summary=dict(payload.get("summary", {}) or {}),
        manifest=dict(payload.get("manifest", {}) or {}),
    )


@contextmanager
def _campaign_load_mode():
    token = _CAMPAIGN_CONSTRUCTION_MODE.set("load")
    try:
        yield
    finally:
        _CAMPAIGN_CONSTRUCTION_MODE.reset(token)


class OperationalPaperCampaignState(str, Enum):
    PREPARED = "PREPARED"
    RUNNING = "RUNNING"
    READY_FOR_EVALUATION = "READY_FOR_EVALUATION"
    EVALUATED = "EVALUATED"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class OperationalPaperCampaignContract:
    campaign_id: str
    cohort_hash: str
    strategy_version: str
    symbol: str
    interval: str
    inclusion_rule: str
    period_start_utc: datetime
    period_end_utc: datetime
    policy_payload: Mapping[str, Any]
    reference_payload_json: Mapping[str, Any]
    policy_hash: str
    walk_forward_manifest_hash: str
    walk_forward_result_hash: str
    evaluator_version: str
    created_at_utc: datetime | None = None
    campaign_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "campaign_id", _require_str(self.campaign_id, "campaign_id"))
        object.__setattr__(self, "cohort_hash", _require_str(self.cohort_hash, "cohort_hash"))
        object.__setattr__(self, "strategy_version", _require_str(self.strategy_version, "strategy_version"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol"))
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "inclusion_rule", _require_str(self.inclusion_rule, "inclusion_rule"))
        object.__setattr__(self, "period_start_utc", _require_datetime(self.period_start_utc, "period_start_utc"))
        object.__setattr__(self, "period_end_utc", _require_datetime(self.period_end_utc, "period_end_utc"))
        if self.period_end_utc <= self.period_start_utc:
            raise PaperCampaignManifestError("period_end_utc must be later than period_start_utc.")
        object.__setattr__(self, "policy_payload", dict(self.policy_payload))
        object.__setattr__(self, "reference_payload_json", MappingProxyType(dict(self.reference_payload_json)))
        object.__setattr__(self, "policy_hash", _require_str(self.policy_hash, "policy_hash"))
        object.__setattr__(self, "walk_forward_manifest_hash", _require_str(self.walk_forward_manifest_hash, "walk_forward_manifest_hash"))
        object.__setattr__(self, "walk_forward_result_hash", _require_str(self.walk_forward_result_hash, "walk_forward_result_hash"))
        object.__setattr__(self, "evaluator_version", _require_str(self.evaluator_version, "evaluator_version"))
        object.__setattr__(self, "policy_payload", MappingProxyType(dict(self.policy_payload)))
        mode = _CAMPAIGN_CONSTRUCTION_MODE.get()
        if self.created_at_utc is None:
            if mode != "public":
                raise PaperCampaignManifestError("created_at_utc must be provided by the storage loader.")
            object.__setattr__(self, "created_at_utc", _utcnow())
        else:
            if mode != "load":
                raise PaperCampaignManifestError("created_at_utc is managed internally.")
            object.__setattr__(self, "created_at_utc", _require_datetime(self.created_at_utc, "created_at_utc"))
        if self.created_at_utc >= self.period_start_utc:
            raise PaperCampaignManifestError("created_at_utc must be earlier than period_start_utc.")
        payload = self.as_hash_payload(include_hash=False)
        campaign_hash = self.campaign_hash or paper_evaluation_hash(payload)
        object.__setattr__(self, "campaign_hash", _require_str(campaign_hash, "campaign_hash"))
        if self.campaign_hash != paper_evaluation_hash(payload):
            raise PaperCampaignManifestError("campaign hash mismatch.")

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "campaign_id": self.campaign_id,
            "cohort_hash": self.cohort_hash,
            "strategy_version": self.strategy_version,
            "symbol": self.symbol,
            "interval": self.interval,
            "inclusion_rule": self.inclusion_rule,
            "period_start_utc": self.period_start_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "period_end_utc": self.period_end_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "policy_payload": serialize_value(dict(self.policy_payload)),
            "reference_payload_json": serialize_value(dict(self.reference_payload_json)),
            "policy_hash": self.policy_hash,
            "walk_forward_manifest_hash": self.walk_forward_manifest_hash,
            "walk_forward_result_hash": self.walk_forward_result_hash,
            "evaluator_version": self.evaluator_version,
            "created_at_utc": self.created_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if include_hash:
            payload["campaign_hash"] = self.campaign_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())


@dataclass(frozen=True, slots=True)
class OperationalPaperCampaignReport:
    contract: OperationalPaperCampaignContract
    campaign_state: OperationalPaperCampaignState
    decision_status: PaperEvaluationStatus
    operational_evidence: bool
    paper_report: Any | None
    reasons: tuple[str, ...]
    evaluated_at_utc: datetime
    report_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.contract, OperationalPaperCampaignContract):
            raise PaperCampaignManifestError("contract must be an OperationalPaperCampaignContract instance.")
        object.__setattr__(self, "campaign_state", OperationalPaperCampaignState(self.campaign_state))
        object.__setattr__(self, "decision_status", PaperEvaluationStatus(self.decision_status))
        if type(self.operational_evidence) is not bool:
            raise PaperCampaignManifestError("operational_evidence must be a boolean.")
        object.__setattr__(self, "reasons", tuple(str(reason).strip() for reason in self.reasons if str(reason).strip()))
        object.__setattr__(self, "evaluated_at_utc", _require_datetime(self.evaluated_at_utc, "evaluated_at_utc"))
        payload = self.as_hash_payload(include_hash=False)
        report_hash = self.report_hash or paper_evaluation_hash(payload)
        object.__setattr__(self, "report_hash", _require_str(report_hash, "report_hash"))
        if self.report_hash != paper_evaluation_hash(payload):
            raise PaperCampaignManifestError("report hash mismatch.")

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "contract": self.contract.as_dict(),
            "campaign_state": self.campaign_state.value,
            "decision_status": self.decision_status.value,
            "operational_evidence": self.operational_evidence,
            "paper_report": _paper_report_payload(self.paper_report),
            "reasons": self.reasons,
            "evaluated_at_utc": self.evaluated_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if include_hash:
            payload["report_hash"] = self.report_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())


def _paper_report_from_payload(payload: Any | None) -> Any | None:
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        return serialize_value(dict(payload))
    return payload


@dataclass(frozen=True, slots=True)
class OperationalPaperCampaignStatusSnapshot:
    campaign_id: str
    campaign_state: OperationalPaperCampaignState
    campaign_hash: str | None
    decision_status: PaperEvaluationStatus | None
    report_hash: str | None
    period_start_utc: datetime | None
    period_end_utc: datetime | None
    created_at_utc: datetime | None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(
            {
                "campaign_id": self.campaign_id,
                "campaign_state": self.campaign_state.value,
                "campaign_hash": self.campaign_hash,
                "decision_status": self.decision_status.value if self.decision_status is not None else None,
                "report_hash": self.report_hash,
                "period_start_utc": self.period_start_utc,
                "period_end_utc": self.period_end_utc,
                "created_at_utc": self.created_at_utc,
                "reason": self.reason,
            }
        )


_CAMPAIGN_REQUIRED_COLUMNS = {
    "campaign_hash",
    "campaign_id",
    "cohort_hash",
    "strategy_version",
    "symbol",
    "interval",
    "inclusion_rule",
    "period_start_utc",
    "period_end_utc",
    "policy_payload_json",
    "reference_payload_json",
    "policy_hash",
    "walk_forward_manifest_hash",
    "walk_forward_result_hash",
    "evaluator_version",
    "created_at_utc",
    "payload_json",
}

_CAMPAIGN_REPORT_REQUIRED_COLUMNS = {
    "campaign_hash",
    "campaign_state",
    "decision_status",
    "operational_evidence",
    "report_json",
    "report_hash",
    "evaluated_at_utc",
}


def _connect_rw(db_path: str | Path):
    return sqlite3.connect(Path(db_path), timeout=30, isolation_level=None)


@contextmanager
def _connect_ro(db_path: str | Path):
    path = Path(db_path)
    if not path.exists():
        raise PaperCampaignReadError("campaign database not found.")
    conn = None
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        yield conn
    except sqlite3.DatabaseError as exc:
        raise PaperCampaignReadError("campaign storage failed.") from exc
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def ensure_operational_paper_campaign_schema(db_path: str | Path) -> None:
    with _connect_rw(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_evaluation_campaign_contracts (
                campaign_hash TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL UNIQUE,
                cohort_hash TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                inclusion_rule TEXT NOT NULL,
                period_start_utc TEXT NOT NULL,
                period_end_utc TEXT NOT NULL,
                policy_payload_json TEXT NOT NULL,
                reference_payload_json TEXT NOT NULL,
                policy_hash TEXT NOT NULL,
                walk_forward_manifest_hash TEXT NOT NULL,
                walk_forward_result_hash TEXT NOT NULL,
                evaluator_version TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_contracts_id ON paper_evaluation_campaign_contracts(campaign_id)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_contracts_window ON paper_evaluation_campaign_contracts(strategy_version, symbol, interval, inclusion_rule, period_start_utc, period_end_utc)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_evaluation_campaign_reports (
                campaign_hash TEXT PRIMARY KEY,
                campaign_state TEXT NOT NULL,
                decision_status TEXT NOT NULL,
                operational_evidence INTEGER NOT NULL,
                report_json TEXT NOT NULL,
                report_hash TEXT NOT NULL,
                evaluated_at_utc TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _campaign_from_row(row: sqlite3.Row) -> OperationalPaperCampaignContract:
    with _campaign_load_mode():
        contract = OperationalPaperCampaignContract(
            campaign_id=row["campaign_id"],
            cohort_hash=row["cohort_hash"],
            strategy_version=row["strategy_version"],
            symbol=row["symbol"],
            interval=row["interval"],
            inclusion_rule=row["inclusion_rule"],
            period_start_utc=datetime.fromisoformat(str(row["period_start_utc"]).replace("Z", "+00:00")),
            period_end_utc=datetime.fromisoformat(str(row["period_end_utc"]).replace("Z", "+00:00")),
            policy_payload=json.loads(row["policy_payload_json"]),
            reference_payload_json=json.loads(row["reference_payload_json"]),
            policy_hash=row["policy_hash"],
            walk_forward_manifest_hash=row["walk_forward_manifest_hash"],
            walk_forward_result_hash=row["walk_forward_result_hash"],
            evaluator_version=row["evaluator_version"],
            created_at_utc=datetime.fromisoformat(str(row["created_at_utc"]).replace("Z", "+00:00")),
            campaign_hash=row["campaign_hash"],
        )
    stored_payload = json.loads(row["payload_json"]) if row["payload_json"] else None
    if stored_payload != contract.as_dict():
        raise PaperCampaignReadError("campaign payload mismatch.")
    return contract


def persist_operational_paper_campaign_contract(db_path: str | Path, contract: OperationalPaperCampaignContract) -> OperationalPaperCampaignContract:
    ensure_operational_paper_campaign_schema(db_path)
    payload = json.dumps(contract.as_dict(), ensure_ascii=False, sort_keys=True)
    with _connect_rw(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                INSERT INTO paper_evaluation_campaign_contracts (
                    campaign_hash, campaign_id, cohort_hash, strategy_version, symbol, interval, inclusion_rule,
                    period_start_utc, period_end_utc, policy_payload_json, reference_payload_json, policy_hash, walk_forward_manifest_hash,
                    walk_forward_result_hash, evaluator_version, created_at_utc, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contract.campaign_hash,
                    contract.campaign_id,
                    contract.cohort_hash,
                    contract.strategy_version,
                    contract.symbol,
                    contract.interval,
                    contract.inclusion_rule,
                    contract.period_start_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    contract.period_end_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    json.dumps(serialize_value(dict(contract.policy_payload)), ensure_ascii=False, sort_keys=True),
                    json.dumps(serialize_value(dict(contract.reference_payload_json)), ensure_ascii=False, sort_keys=True),
                    contract.policy_hash,
                    contract.walk_forward_manifest_hash,
                    contract.walk_forward_result_hash,
                    contract.evaluator_version,
                    contract.created_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    payload,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise PaperCampaignManifestError("campaign contract already exists.") from exc
    return contract


def load_operational_paper_campaign_contract(
    db_path: str | Path,
    *,
    campaign_id: str | None = None,
    campaign_hash: str | None = None,
) -> OperationalPaperCampaignContract:
    with _connect_ro(db_path) as conn:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "paper_evaluation_campaign_contracts" not in tables:
            raise PaperCampaignReadError("campaign contract table is missing.")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(paper_evaluation_campaign_contracts)")}
        missing = sorted(_CAMPAIGN_REQUIRED_COLUMNS - columns)
        if missing:
            raise PaperCampaignReadError("campaign contract schema is incomplete.")
        filters: list[str] = []
        params: list[Any] = []
        if campaign_id is not None:
            filters.append("campaign_id = ?")
            params.append(_require_str(campaign_id, "campaign_id"))
        if campaign_hash is not None:
            filters.append("campaign_hash = ?")
            params.append(_require_str(campaign_hash, "campaign_hash"))
        query = "SELECT * FROM paper_evaluation_campaign_contracts"
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY created_at_utc DESC, campaign_hash DESC LIMIT 1"
        row = conn.execute(query, params).fetchone()
        if row is None:
            raise PaperCampaignReadError("campaign contract not found.")
        return _campaign_from_row(row)


def persist_operational_paper_campaign_report(db_path: str | Path, report: OperationalPaperCampaignReport) -> OperationalPaperCampaignReport:
    ensure_operational_paper_campaign_schema(db_path)
    payload = json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True)
    existing = load_operational_paper_campaign_report(db_path, campaign_hash=report.contract.campaign_hash)
    if existing is not None:
        if existing.as_dict() == report.as_dict():
            return existing
        raise PaperCampaignManifestError("campaign report already exists.")
    with _connect_rw(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                INSERT INTO paper_evaluation_campaign_reports (
                    campaign_hash, campaign_state, decision_status, operational_evidence, report_json, report_hash, evaluated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.contract.campaign_hash,
                    report.campaign_state.value,
                    report.decision_status.value,
                    1 if report.operational_evidence else 0,
                    payload,
                    report.report_hash,
                    report.evaluated_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise PaperCampaignManifestError("campaign report already exists.") from exc
    return report


def load_operational_paper_campaign_report(db_path: str | Path, *, campaign_hash: str | None = None) -> OperationalPaperCampaignReport | None:
    with _connect_ro(db_path) as conn:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "paper_evaluation_campaign_reports" not in tables:
            return None
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(paper_evaluation_campaign_reports)")}
        missing = sorted(_CAMPAIGN_REPORT_REQUIRED_COLUMNS - columns)
        if missing:
            raise PaperCampaignReadError("campaign report schema is incomplete.")
        query = "SELECT * FROM paper_evaluation_campaign_reports"
        params: list[Any] = []
        if campaign_hash is not None:
            query += " WHERE campaign_hash = ?"
            params.append(_require_str(campaign_hash, "campaign_hash"))
        query += " ORDER BY evaluated_at_utc DESC, campaign_hash DESC LIMIT 1"
        row = conn.execute(query, params).fetchone()
        if row is None:
            return None
        contract = load_operational_paper_campaign_contract(db_path, campaign_hash=row["campaign_hash"])
        report_payload = json.loads(row["report_json"])
        paper_report_payload = report_payload.get("paper_report")
        paper_report = _paper_report_from_payload(paper_report_payload)
        decision_status = PaperEvaluationStatus(row["decision_status"])
        report = OperationalPaperCampaignReport(
            contract=contract,
            campaign_state=OperationalPaperCampaignState(row["campaign_state"]),
            decision_status=decision_status,
            operational_evidence=bool(row["operational_evidence"]),
            paper_report=paper_report,
            reasons=tuple(report_payload.get("reasons", ())),
            evaluated_at_utc=datetime.fromisoformat(str(row["evaluated_at_utc"]).replace("Z", "+00:00")),
            report_hash=row["report_hash"],
        )
        if report_payload != report.as_dict():
            raise PaperCampaignReadError("campaign report payload mismatch.")
        return report


def create_operational_paper_campaign(
    *,
    campaign_id: str,
    cohort_hash: str | None,
    strategy_version: str,
    symbol: str,
    interval: str,
    inclusion_rule: str,
    period_start_utc: datetime,
    period_end_utc: datetime,
    policy: PaperEvaluationPolicy,
    reference_walk_forward: WalkForwardResult,
    evaluator_version: str = "v8_paper_evaluation",
    runtime_db_path: str | Path = "paper_runtime.db",
    campaign_db_path: str | Path = "paper_evaluation_campaign.db",
) -> OperationalPaperCampaignContract:
    policy_floor_reasons = _validate_policy_floor(policy)
    period_start = _require_datetime(period_start_utc, "period_start_utc")
    period_end = _require_datetime(period_end_utc, "period_end_utc")
    if period_end <= period_start:
        raise PaperCampaignManifestError("period_end_utc must be later than period_start_utc.")
    if _utcnow() >= period_start:
        raise PaperCampaignManifestError("campaign must be created before the operational window starts.")
    cohort_contract = load_latest_operational_cohort_contract(
        runtime_db_path,
        cohort_hash=cohort_hash,
        strategy_version=strategy_version,
        symbol=symbol,
        interval=interval,
        inclusion_rule=inclusion_rule,
    )
    if cohort_hash is not None and cohort_contract.cohort_hash != _require_str(cohort_hash, "cohort_hash"):
        raise PaperCampaignManifestError("cohort hash mismatch.")
    if cohort_contract.strategy_version != strategy_version or cohort_contract.symbol != symbol or cohort_contract.interval != interval or cohort_contract.inclusion_rule != inclusion_rule:
        raise PaperCampaignManifestError("cohort contract diverges from the campaign scope.")
    if cohort_contract.period_start_utc != period_start:
        raise PaperCampaignManifestError("cohort period_start_utc diverges from the campaign scope.")
    if cohort_contract.period_end_utc != period_end:
        raise PaperCampaignManifestError("cohort period_end_utc diverges from the campaign scope.")
    reference_payload, manifest_hash_value, result_hash = _reference_hashes(reference_walk_forward)
    _reference_scope_is_compatible(
        reference_payload,
        strategy_version=strategy_version,
        symbol=symbol,
        interval=interval,
    )
    contract = OperationalPaperCampaignContract(
        campaign_id=campaign_id,
        cohort_hash=cohort_contract.cohort_hash,
        strategy_version=strategy_version,
        symbol=symbol,
        interval=interval,
        inclusion_rule=inclusion_rule,
        period_start_utc=period_start,
        period_end_utc=period_end,
        policy_payload=policy.as_dict(),
        reference_payload_json=reference_payload,
        policy_hash=_policy_hash(policy),
        walk_forward_manifest_hash=manifest_hash_value,
        walk_forward_result_hash=result_hash,
        evaluator_version=evaluator_version,
    )
    persist_operational_paper_campaign_contract(campaign_db_path, contract)
    if policy_floor_reasons:
        # The contract may be prepared for exploratory use, but it is never eligible for operational approval.
        return contract
    return contract


def _current_campaign_state(contract: OperationalPaperCampaignContract, *, now: datetime, report: OperationalPaperCampaignReport | None) -> OperationalPaperCampaignState:
    if report is not None:
        return OperationalPaperCampaignState.EVALUATED
    if now < contract.period_start_utc:
        return OperationalPaperCampaignState.PREPARED
    if now < contract.period_end_utc:
        return OperationalPaperCampaignState.RUNNING
    return OperationalPaperCampaignState.READY_FOR_EVALUATION


def get_operational_paper_campaign_status(
    *,
    campaign_id: str,
    campaign_db_path: str | Path = "paper_evaluation_campaign.db",
) -> OperationalPaperCampaignStatusSnapshot:
    current = _utcnow()
    try:
        contract = load_operational_paper_campaign_contract(campaign_db_path, campaign_id=campaign_id)
    except PaperCampaignError as exc:
        return OperationalPaperCampaignStatusSnapshot(
            campaign_id=_require_str(campaign_id, "campaign_id", allow_empty=False),
            campaign_state=OperationalPaperCampaignState.INVALID,
            campaign_hash=None,
            decision_status=None,
            report_hash=None,
            period_start_utc=None,
            period_end_utc=None,
            created_at_utc=None,
            reason=str(exc),
        )
    report = load_operational_paper_campaign_report(campaign_db_path, campaign_hash=contract.campaign_hash)
    state = _current_campaign_state(contract, now=current, report=report)
    return OperationalPaperCampaignStatusSnapshot(
        campaign_id=contract.campaign_id,
        campaign_state=state,
        campaign_hash=contract.campaign_hash,
        decision_status=report.decision_status if report is not None else None,
        report_hash=report.report_hash if report is not None else None,
        period_start_utc=contract.period_start_utc,
        period_end_utc=contract.period_end_utc,
        created_at_utc=contract.created_at_utc,
        reason="",
    )


def _campaign_result_from_report(
    contract: OperationalPaperCampaignContract,
    report: PaperEvaluationReport | None,
    *,
    campaign_db_path: str | Path,
    now: datetime,
    reasons: tuple[str, ...],
) -> OperationalPaperCampaignReport:
    if report is not None:
        decision_status = report.decision.status
        operational_evidence = bool(report.operational_evidence)
    else:
        decision_status = PaperEvaluationStatus.INSUFFICIENT_EVIDENCE
        operational_evidence = False
    state = OperationalPaperCampaignState.EVALUATED if report is not None else _current_campaign_state(contract, now=now, report=None)
    campaign_report = OperationalPaperCampaignReport(
        contract=contract,
        campaign_state=state,
        decision_status=decision_status,
        operational_evidence=operational_evidence,
        paper_report=report,
        reasons=reasons,
        evaluated_at_utc=now,
    )
    if report is None and now < contract.period_end_utc:
        return campaign_report
    return persist_operational_paper_campaign_report(campaign_db_path, campaign_report)


def evaluate_operational_paper_campaign(
    *,
    campaign_id: str,
    campaign_db_path: str | Path = "paper_evaluation_campaign.db",
    runtime_db_path: str | Path = "paper_runtime.db",
    trades_db_path: str | Path = "trades.db",
) -> OperationalPaperCampaignReport:
    current = _utcnow()
    contract = load_operational_paper_campaign_contract(campaign_db_path, campaign_id=campaign_id)
    existing_report = load_operational_paper_campaign_report(campaign_db_path, campaign_hash=contract.campaign_hash)
    if existing_report is not None:
        return existing_report
    if current < contract.period_start_utc:
        return _campaign_result_from_report(contract, None, campaign_db_path=campaign_db_path, now=current, reasons=("campaign window has not started.",))
    if current < contract.period_end_utc:
        return _campaign_result_from_report(contract, None, campaign_db_path=campaign_db_path, now=current, reasons=("campaign window is still running.",))

    frozen_policy = _policy_from_payload(contract.policy_payload, contract.policy_hash)
    policy_floor_reasons = _validate_policy_floor(frozen_policy)
    if policy_floor_reasons:
        raise PaperCampaignPolicyError("; ".join(policy_floor_reasons))
    reference_walk_forward = _reference_from_contract(contract)

    cohort_contract = load_latest_operational_cohort_contract(
        runtime_db_path,
        cohort_hash=contract.cohort_hash,
        strategy_version=contract.strategy_version,
        symbol=contract.symbol,
        interval=contract.interval,
        inclusion_rule=contract.inclusion_rule,
    )
    if cohort_contract.cohort_hash != contract.cohort_hash:
        raise PaperCampaignManifestError("cohort hash mismatch.")
    if cohort_contract.period_start_utc != contract.period_start_utc or cohort_contract.period_end_utc != contract.period_end_utc:
        raise PaperCampaignManifestError("campaign period diverges from the frozen cohort.")

    report = evaluate_paper_sessions_from_storage(
        runtime_db_path=runtime_db_path,
        trades_db_path=trades_db_path,
        policy=frozen_policy,
        reference_walk_forward=reference_walk_forward,
        evaluation_id=contract.campaign_id,
        inclusion_rule=contract.inclusion_rule,
        synthetic_test_data=False,
        operational_evidence=True,
    )
    reasons = tuple(report.decision.reasons)
    if report.decision.status is PaperEvaluationStatus.APPROVED_FOR_EXTENDED_PAPER:
        if report.manifest.cohort_hash != contract.cohort_hash:
            raise PaperCampaignManifestError("operational evidence cohort mismatch.")
    campaign_report = _campaign_result_from_report(contract, report, campaign_db_path=campaign_db_path, now=current, reasons=reasons)
    return campaign_report


def _format_status(snapshot: OperationalPaperCampaignStatusSnapshot) -> str:
    lines = [
        f"campaign_id: {snapshot.campaign_id}",
        f"campaign_state: {snapshot.campaign_state.value}",
        f"campaign_hash: {snapshot.campaign_hash or 'N/A'}",
        f"decision_status: {snapshot.decision_status.value if snapshot.decision_status else 'N/A'}",
        f"report_hash: {snapshot.report_hash or 'N/A'}",
        f"period_start_utc: {snapshot.period_start_utc or 'N/A'}",
        f"period_end_utc: {snapshot.period_end_utc or 'N/A'}",
        f"created_at_utc: {snapshot.created_at_utc or 'N/A'}",
    ]
    if snapshot.reason:
        lines.append(f"reason: {snapshot.reason}")
    return "\n".join(lines)


def _parse_utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PaperCampaignManifestError("timestamp must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m paper_evaluation.campaign", description="Paper campaign administration commands.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Prepare a new operational paper campaign.")
    prepare.add_argument("--campaign-id", required=True)
    prepare.add_argument("--campaign-db", default="paper_evaluation_campaign.db")
    prepare.add_argument("--runtime-db", default="paper_runtime.db")
    prepare.add_argument("--cohort-hash", required=False)
    prepare.add_argument("--strategy-version", required=True)
    prepare.add_argument("--symbol", required=True)
    prepare.add_argument("--interval", required=True)
    prepare.add_argument("--inclusion-rule", required=True)
    prepare.add_argument("--period-start-utc", required=True)
    prepare.add_argument("--period-end-utc", required=True)
    prepare.add_argument("--policy-json", required=True, help="JSON representation of PaperEvaluationPolicy.as_dict().")
    prepare.add_argument("--reference-json", required=True, help="JSON representation of WalkForwardResult.as_dict().")
    prepare.add_argument("--evaluator-version", default="v8_paper_evaluation")

    status = subparsers.add_parser("status", help="Show a sanitized campaign status snapshot.")
    status.add_argument("--campaign-id", required=True)
    status.add_argument("--campaign-db", default="paper_evaluation_campaign.db")

    evaluate = subparsers.add_parser("evaluate", help="Evaluate a finished operational paper campaign.")
    evaluate.add_argument("--campaign-id", required=True)
    evaluate.add_argument("--campaign-db", default="paper_evaluation_campaign.db")
    evaluate.add_argument("--runtime-db", default="paper_runtime.db")
    evaluate.add_argument("--trades-db", default="trades.db")

    return parser


def _load_json_argument(value: str) -> Any:
    return json.loads(value)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            policy_payload = _load_json_argument(args.policy_json)
            reference_payload = _load_json_argument(args.reference_json)
            with _campaign_load_mode():
                policy = PaperEvaluationPolicy(**policy_payload)
            reference = _walk_forward_from_payload(reference_payload)
            contract = create_operational_paper_campaign(
                campaign_id=args.campaign_id,
                cohort_hash=args.cohort_hash,
                strategy_version=args.strategy_version,
                symbol=args.symbol,
                interval=args.interval,
                inclusion_rule=args.inclusion_rule,
                period_start_utc=_parse_utc_datetime(args.period_start_utc),
                period_end_utc=_parse_utc_datetime(args.period_end_utc),
                policy=policy,
                reference_walk_forward=reference,
                evaluator_version=args.evaluator_version,
                runtime_db_path=args.runtime_db,
                campaign_db_path=args.campaign_db,
            )
            print(contract.campaign_hash)
            return 0

        if args.command == "status":
            snapshot = get_operational_paper_campaign_status(campaign_id=args.campaign_id, campaign_db_path=args.campaign_db)
            print(_format_status(snapshot))
            return 0

        if args.command == "evaluate":
            report = evaluate_operational_paper_campaign(
                campaign_id=args.campaign_id,
                campaign_db_path=args.campaign_db,
                runtime_db_path=args.runtime_db,
                trades_db_path=args.trades_db,
            )
            print(report.report_hash)
            return 0

        raise PaperCampaignError("unknown command.")
    except PaperCampaignError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("error: campaign command failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
