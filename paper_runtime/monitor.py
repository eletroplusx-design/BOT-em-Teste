from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from promotion import MonitoredPaperLimits, PaperMonitoringDecision, PaperMonitoringSnapshot, PromotionDecision, PromotionStatus, evaluate_paper_monitoring

from .errors import PaperRuntimeMonitorError
from .models import PaperRuntimeSessionRecord
from .session import PaperRuntimeSession, RuntimeEvaluationResult


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PaperRuntimeMonitorError(f"{field_name} must be a mapping.")
    return value


def _require_observed_field(observed: Mapping[str, Any], field_name: str) -> Any:
    if field_name not in observed:
        raise PaperRuntimeMonitorError(f"{field_name} is required.")
    value = observed[field_name]
    if value is None:
        raise PaperRuntimeMonitorError(f"{field_name} is required.")
    return value


def _require_observed_key(observed: Mapping[str, Any], field_name: str) -> Any:
    if field_name not in observed:
        raise PaperRuntimeMonitorError(f"{field_name} is required.")
    return observed[field_name]


def build_snapshot_from_observed_state(
    *,
    session: PaperRuntimeSessionRecord,
    decision: PromotionDecision,
    observed: Mapping[str, Any],
    timestamp_utc: datetime | None = None,
) -> PaperMonitoringSnapshot:
    observed = _require_mapping(observed, "observed")
    timestamp = timestamp_utc or datetime.now(timezone.utc)
    observed_costs = _require_mapping(_require_observed_key(observed, "observed_costs"), "observed_costs")
    return PaperMonitoringSnapshot(
        timestamp_utc=timestamp,
        decision_hash=decision.decision_hash,
        evidence_hash=decision.evidence_hash,
        strategy_version=decision.strategy_version,
        configuration=decision.frozen_selection.as_dict(),
        trading_mode="PAPER",
        session_id=session.session_id,
        session_started_utc=session.session_started_utc,
        data_fresh=_require_observed_key(observed, "data_fresh"),
        session_drawdown_percent=Decimal(str(_require_observed_key(observed, "session_drawdown_percent"))),
        current_loss_streak=int(_require_observed_key(observed, "current_loss_streak")),
        open_positions=int(_require_observed_key(observed, "open_positions")),
        executed_trades=int(_require_observed_key(observed, "executed_trades")),
        observed_costs=dict(observed_costs),
        session_state=str(_require_observed_key(observed, "session_state")),
        paper_capital_used=Decimal(str(_require_observed_key(observed, "paper_capital_used"))),
        risk_per_trade_percent=Decimal(str(_require_observed_key(observed, "risk_per_trade_percent"))),
        internal_error=_require_observed_key(observed, "internal_error"),
        attempted_live=_require_observed_key(observed, "attempted_live"),
    )


def evaluate_monitored_session(
    session: PaperRuntimeSession,
    decision: PromotionDecision,
    observed: Mapping[str, Any],
    *,
    limits: MonitoredPaperLimits | None = None,
    timestamp_utc: datetime | None = None,
    idempotency_key: str | None = None,
) -> RuntimeEvaluationResult:
    snapshot = build_snapshot_from_observed_state(
        session=session.record,
        decision=decision,
        observed=observed,
        timestamp_utc=timestamp_utc,
    )
    return session.evaluate_snapshot(
        snapshot,
        decision=decision,
        limits=limits,
        idempotency_key=idempotency_key,
    )


def evaluate_paper_contract(
    decision: PromotionDecision,
    session: PaperRuntimeSession,
    observed: Mapping[str, Any],
    *,
    limits: MonitoredPaperLimits | None = None,
) -> PaperMonitoringDecision:
    result = evaluate_monitored_session(session, decision, observed, limits=limits)
    return result.monitoring_decision
