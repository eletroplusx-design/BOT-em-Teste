from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from domain.serialization import serialize_value
from promotion import (
    MonitoredPaperLimits,
    PaperMonitoringDecision,
    PaperMonitoringSessionContract,
    PaperMonitoringSnapshot,
    PromotionCriterionResult,
    PromotionDecision,
    PromotionStatus,
    evaluate_paper_monitoring,
    promotion_hash,
)
from promotion.errors import PromotionDecisionError
from validation.models import CandidateConfig, FrozenSelection

from .errors import PaperRuntimeMonitorError, PaperRuntimeSessionError
from .models import PaperRuntimeContract, PaperRuntimeSessionRecord, PaperRuntimeState
from .store import PaperRuntimeStore, get_default_store


def _dt_from_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise PaperRuntimeSessionError("session timestamps must be timezone-aware.")
    return dt.astimezone(timezone.utc)


def _decision_from_record(record: PaperRuntimeSessionRecord) -> PromotionDecision:
    try:
        decision_data = json.loads(record.decision_json)
    except Exception as exc:  # pragma: no cover - defensive guard
        raise PaperRuntimeSessionError("stored decision payload is invalid.") from exc

    frozen_selection_data = decision_data.get("frozen_selection") or {}
    candidate_data = frozen_selection_data.get("candidate") or {}
    candidate = CandidateConfig.from_mapping(
        candidate_data.get("name", "runtime"),
        candidate_data.get("parameters", {}),
    )
    frozen_selection = FrozenSelection(
        candidate=candidate,
        strategy_version=frozen_selection_data.get("strategy_version", record.strategy_version),
        costs=tuple(sorted((frozen_selection_data.get("costs", {}) or {}).items())),
        execution_contract=tuple(sorted((frozen_selection_data.get("execution_contract", {}) or {}).items())),
        symbol=frozen_selection_data.get("symbol", record.symbol),
        interval=frozen_selection_data.get("interval", record.interval),
        frozen_at=_dt_from_iso(frozen_selection_data.get("frozen_at", record.created_at_utc.isoformat())),
        manifest_hash=frozen_selection_data.get("manifest_hash", record.contract_hash),
        window_id=frozen_selection_data.get("window_id", record.session_id),
    )

    criteria = tuple(
        PromotionCriterionResult(
            name=item.get("name", "criterion"),
            passed=(item["passed"] if type(item.get("passed")) is bool else _raise_stored_bool_error("stored decision criterion passed flag must be boolean.")),
            expected=item.get("expected"),
            actual=item.get("actual"),
            reason=item.get("reason", ""),
        )
        for item in decision_data.get("criteria_evaluated", [])
    )

    decision = PromotionDecision(
        status=PromotionStatus(decision_data.get("status", PromotionStatus.APPROVED_FOR_MONITORED_PAPER.value)),
        frozen_selection=frozen_selection,
        strategy_version=decision_data.get("strategy_version", record.strategy_version),
        symbol=decision_data.get("symbol", record.symbol),
        interval=decision_data.get("interval", record.interval),
        phase5_manifest=decision_data.get("phase5_manifest", {}),
        evidence_hash=decision_data.get("evidence_hash", record.evidence_hash),
        policy_hash=decision_data.get("policy_hash", record.contract_hash),
        decision_hash=decision_data.get("decision_hash", record.decision_hash),
        criteria_evaluated=criteria,
        reasons=tuple(decision_data.get("reasons", ())),
        recalculated_metrics=decision_data.get("recalculated_metrics", {}),
        paper_limits=decision_data.get("paper_limits", {}),
        timestamp_utc=_dt_from_iso(decision_data.get("timestamp_utc", record.updated_at_utc.isoformat())),
        paper_limits_hash=decision_data.get("paper_limits_hash", record.paper_limits_hash),
    )
    try:
        normalized_limits = MonitoredPaperLimits(**decision.paper_limits).as_dict()
        object.__setattr__(decision, "paper_limits", normalized_limits)
    except Exception:
        pass
    return decision


def _validate_recovered_session(record: PaperRuntimeSessionRecord, decision: PromotionDecision, contract: PaperRuntimeContract) -> None:
    if record.decision_hash != decision.decision_hash:
        raise PaperRuntimeSessionError("stored decision hash mismatch.")
    if record.evidence_hash != decision.evidence_hash:
        raise PaperRuntimeSessionError("stored evidence hash mismatch.")
    if record.paper_limits_hash != decision.paper_limits_hash:
        raise PaperRuntimeSessionError("stored paper limits hash mismatch.")
    if record.contract_hash != contract.contract_hash:
        raise PaperRuntimeSessionError("stored contract hash mismatch.")
    if record.configuration_hash != promotion_hash({"configuration": decision.frozen_selection.as_dict()}):
        raise PaperRuntimeSessionError("stored configuration hash mismatch.")
    if record.execution_contract_hash != promotion_hash({"execution_contract": decision.phase5_manifest.get("execution_contract", {})}):
        raise PaperRuntimeSessionError("stored execution contract hash mismatch.")
    if record.paper_only is not True or not contract.paper_only:
        raise PaperRuntimeSessionError("paper-only runtime contract mismatch.")
    if record.session_id != contract.session_id or record.session_started_utc != contract.session_started_utc:
        raise PaperRuntimeSessionError("session identity mismatch.")


def _raise_stored_bool_error(message: str) -> bool:
    raise PaperRuntimeSessionError(message)


def _contract_from_record(record: PaperRuntimeSessionRecord, decision: PromotionDecision | None = None) -> PaperRuntimeContract:
    if decision is not None:
        paper_limits = MonitoredPaperLimits(**decision.paper_limits).as_dict()
        configuration = decision.frozen_selection.as_dict()
        execution_contract = decision.phase5_manifest.get("execution_contract", {})
    else:
        paper_limits = json.loads(record.paper_limits_json)
        configuration = json.loads(record.configuration_json)
        execution_contract = json.loads(record.execution_contract_json)
    return PaperRuntimeContract(
        session_id=record.session_id,
        session_started_utc=record.session_started_utc,
        decision_hash=record.decision_hash,
        evidence_hash=record.evidence_hash,
        paper_limits_hash=record.paper_limits_hash,
        paper_limits=paper_limits,
        configuration=configuration,
        strategy_version=record.strategy_version,
        symbol=record.symbol,
        interval=record.interval,
        execution_contract=execution_contract,
        paper_only=record.paper_only,
    )


@dataclass(frozen=True, slots=True)
class RuntimeEvaluationResult:
    monitoring_decision: PaperMonitoringDecision
    session: PaperRuntimeSessionRecord
    approved: bool


class PaperRuntimeSession:
    def __init__(
        self,
        record: PaperRuntimeSessionRecord,
        contract: PaperRuntimeContract,
        store: PaperRuntimeStore | None = None,
        decision: PromotionDecision | None = None,
    ) -> None:
        self._record = record
        self._contract = contract
        self._store = store or get_default_store()
        self._decision = decision

    @property
    def record(self) -> PaperRuntimeSessionRecord:
        return self._record

    @property
    def contract(self) -> PaperRuntimeContract:
        return self._contract

    @property
    def decision(self) -> PromotionDecision | None:
        return self._decision

    @classmethod
    def create_from_decision(
        cls,
        decision: PromotionDecision,
        *,
        session_id: str,
        session_started_utc: datetime,
        store: PaperRuntimeStore | None = None,
    ) -> "PaperRuntimeSession":
        if type(decision) is not PromotionDecision:
            raise PaperRuntimeSessionError("promotion decision must be an exact PromotionDecision instance.")
        if decision.status is not PromotionStatus.APPROVED_FOR_MONITORED_PAPER:
            raise PaperRuntimeSessionError("only approved monitored paper decisions can start a runtime session.")
        if decision.paper_limits_hash != promotion_hash(decision.paper_limits):
            raise PaperRuntimeSessionError("decision paper limits hash mismatch.")
        contract = PaperRuntimeContract(
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
        runtime_store = store or get_default_store()
        record = runtime_store.create_session(
            contract,
            session_state=PaperRuntimeState.RUNNING,
            decision_json=json.dumps(serialize_value(decision.as_dict()), ensure_ascii=False, sort_keys=True),
        )
        return cls(record, contract, runtime_store, decision=decision)

    @classmethod
    def from_store(cls, session_id: str, store: PaperRuntimeStore | None = None) -> "PaperRuntimeSession":
        runtime_store = store or get_default_store()
        record = runtime_store.load_session(session_id)
        if record is None:
            raise PaperRuntimeSessionError("runtime session not found.")
        decision = _decision_from_record(record)
        contract = _contract_from_record(record, decision)
        _validate_recovered_session(record, decision, contract)
        runtime_store.assert_audit_chain(session_id)
        return cls(record, contract, runtime_store, decision=decision)

    def reload(self) -> PaperRuntimeSessionRecord:
        self._record = self._store.load_session(self._record.session_id)
        return self._record

    def is_running(self) -> bool:
        return self._record.state is PaperRuntimeState.RUNNING

    def require_running(self) -> PaperRuntimeSessionRecord:
        if self._record.state is not PaperRuntimeState.RUNNING:
            raise PaperRuntimeSessionError("runtime session is not running.")
        return self._record

    def contract_as_monitoring(self) -> PaperMonitoringSessionContract:
        return self._contract.to_promotion_contract()

    def evaluate_snapshot(
        self,
        snapshot: PaperMonitoringSnapshot,
        *,
        decision: PromotionDecision | None = None,
        limits: MonitoredPaperLimits | None = None,
        idempotency_key: str | None = None,
    ) -> RuntimeEvaluationResult:
        self.require_running()
        decision_obj = decision or self._decision
        if decision_obj is None:
            raise PaperRuntimeMonitorError("a promotion decision is required to evaluate runtime monitoring.")
        monitoring_decision = evaluate_paper_monitoring(
            decision_obj,
            snapshot,
            limits=limits,
            session_contract=self.contract_as_monitoring(),
        )
        self._store.append_snapshot(
            self._record.session_id,
            snapshot=snapshot.as_dict(),
            decision_hash=monitoring_decision.decision_hash,
            evidence_hash=monitoring_decision.evidence_hash,
            result_status=monitoring_decision.status.value,
            idempotency_key=idempotency_key,
        )
        self._record = self._store.load_session(self._record.session_id)
        if monitoring_decision.status is PromotionStatus.PAPER_SUSPENDED:
            self._record = self._store.transition_session(
                self._record.session_id,
                expected_version=self._record.version,
                next_state=PaperRuntimeState.SUSPENDED,
                reason=monitoring_decision.reasons[0] if monitoring_decision.reasons else "monitoring suspended",
            )
        return RuntimeEvaluationResult(
            monitoring_decision=monitoring_decision,
            session=self._record,
            approved=monitoring_decision.status is PromotionStatus.APPROVED_FOR_MONITORED_PAPER,
        )

    def suspend(self, reason: str, *, idempotency_key: str | None = None) -> PaperRuntimeSessionRecord:
        self._record = self._store.transition_session(
            self._record.session_id,
            expected_version=self._record.version,
            next_state=PaperRuntimeState.SUSPENDED,
            reason=reason,
        )
        return self._record

    def complete(self, reason: str, *, idempotency_key: str | None = None) -> PaperRuntimeSessionRecord:
        self._record = self._store.transition_session(
            self._record.session_id,
            expected_version=self._record.version,
            next_state=PaperRuntimeState.COMPLETED,
            reason=reason,
        )
        return self._record

    def fail(self, reason: str, *, idempotency_key: str | None = None) -> PaperRuntimeSessionRecord:
        self._record = self._store.transition_session(
            self._record.session_id,
            expected_version=self._record.version,
            next_state=PaperRuntimeState.FAILED,
            reason=reason,
        )
        return self._record


def load_active_runtime_session(decision_hash: str | None = None, *, session_id: str | None = None, store: PaperRuntimeStore | None = None) -> PaperRuntimeSession | None:
    runtime_store = store or get_default_store()
    record = runtime_store.load_active_session(decision_hash, session_id=session_id)
    if record is None:
        return None
    decision = _decision_from_record(record)
    contract = _contract_from_record(record, decision)
    return PaperRuntimeSession(record, contract, runtime_store, decision=decision)
