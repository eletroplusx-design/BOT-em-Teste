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


def build_snapshot_from_observed_state(
    *,
    session: PaperRuntimeSessionRecord,
    decision: PromotionDecision,
    observed: Mapping[str, Any],
    timestamp_utc: datetime | None = None,
) -> PaperMonitoringSnapshot:
    observed = _require_mapping(observed, "observed")
    timestamp = timestamp_utc or datetime.now(timezone.utc)
    return PaperMonitoringSnapshot(
        timestamp_utc=timestamp,
        decision_hash=decision.decision_hash,
        evidence_hash=decision.evidence_hash,
        strategy_version=decision.strategy_version,
        configuration=decision.frozen_selection.as_dict(),
        trading_mode="PAPER",
        session_id=session.session_id,
        session_started_utc=session.session_started_utc,
        data_fresh=observed.get("data_fresh", True),
        session_drawdown_percent=Decimal(str(observed.get("session_drawdown_percent", "0"))),
        current_loss_streak=int(observed.get("current_loss_streak", 0)),
        open_positions=int(observed.get("open_positions", 0)),
        executed_trades=int(observed.get("executed_trades", 0)),
        observed_costs=dict(_require_mapping(observed.get("observed_costs", {}), "observed_costs")),
        session_state=str(observed.get("session_state", session.state.value)),
        paper_capital_used=Decimal(str(observed.get("paper_capital_used", "0"))),
        risk_per_trade_percent=Decimal(str(observed.get("risk_per_trade_percent", "0"))),
        internal_error=observed.get("internal_error"),
        attempted_live=observed.get("attempted_live", False),
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
