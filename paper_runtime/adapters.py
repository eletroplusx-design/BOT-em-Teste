from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from promotion import MonitoredPaperLimits, PaperMonitoringSessionContract, PromotionDecision
from promotion.models import PromotionStatus

from .errors import PaperRuntimeSessionError
from .models import PaperRuntimeContract
from .session import PaperRuntimeSession, load_active_runtime_session
from .store import PaperRuntimeStore, get_default_store


def build_runtime_contract_from_decision(
    decision: PromotionDecision,
    *,
    session_id: str,
    session_started_utc: datetime,
) -> PaperRuntimeContract:
    return PaperRuntimeContract(
        session_id=session_id,
        session_started_utc=session_started_utc,
        decision_hash=decision.decision_hash,
        evidence_hash=decision.evidence_hash,
        paper_limits_hash=decision.paper_limits_hash,
        paper_limits=decision.paper_limits,
        configuration=decision.frozen_selection.as_dict(),
        strategy_version=decision.strategy_version,
        symbol=decision.symbol,
        interval=decision.interval,
        execution_contract=decision.phase5_manifest.get("execution_contract", {}),
        paper_only=True,
    )


def create_monitored_session(
    decision: PromotionDecision,
    *,
    session_id: str,
    session_started_utc: datetime,
    store: PaperRuntimeStore | None = None,
) -> PaperRuntimeSession:
    if decision.status is not PromotionStatus.APPROVED_FOR_MONITORED_PAPER:
        raise PaperRuntimeSessionError("decision must be approved for monitored paper.")
    runtime_store = store or get_default_store()
    contract = build_runtime_contract_from_decision(
        decision,
        session_id=session_id,
        session_started_utc=session_started_utc,
    )
    record = runtime_store.create_session(contract)
    return PaperRuntimeSession(record, contract, runtime_store, decision=decision)


def get_monitored_session(
    *,
    session_id: str | None = None,
    decision_hash: str | None = None,
    store: PaperRuntimeStore | None = None,
) -> PaperRuntimeSession | None:
    return load_active_runtime_session(decision_hash, session_id=session_id, store=store)


def build_session_contract(session: PaperRuntimeSession) -> PaperMonitoringSessionContract:
    return session.contract_as_monitoring()


def require_session_runtime(
    *,
    session_id: str | None,
    decision_hash: str | None = None,
    store: PaperRuntimeStore | None = None,
) -> PaperRuntimeSession:
    session = get_monitored_session(session_id=session_id, decision_hash=decision_hash, store=store)
    if session is None:
        raise PaperRuntimeSessionError("paper runtime session is required.")
    return session
