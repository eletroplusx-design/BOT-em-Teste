from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from validation import WalkForwardResult

from .evaluator import _evaluate_paper_sessions_from_operational_batch, evaluate_paper_sessions
from .evidence import load_operational_evidence_batch, load_paper_session_evidence_batch
from .errors import PaperEvaluationDecisionError, PaperEvaluationReadError
from .models import _OperationalEvidenceBatch, PaperEvaluationPolicy, PaperEvaluationReport, PaperSessionEvidence, PaperSessionRejection


def _normalize_session_ids(session_ids: Sequence[str] | None) -> tuple[str, ...] | None:
    if session_ids is None:
        return None
    normalized = tuple(str(session_id).strip() for session_id in session_ids if str(session_id).strip())
    return normalized


@dataclass(frozen=True, slots=True)
class PaperEvaluationAdapter:
    runtime_db_path: str | Path = "paper_runtime.db"
    trades_db_path: str | Path = "trades.db"
    policy: PaperEvaluationPolicy | None = None
    reference_walk_forward: WalkForwardResult | None = None
    evaluation_id: str | None = None
    inclusion_rule: str = "explicit_session_ids"
    synthetic_test_data: bool = False
    operational_evidence: bool = True
    period_start_utc: datetime | None = None
    period_end_utc: datetime | None = None
    session_ids: Sequence[str] | None = None

    def load(self) -> tuple[list[PaperSessionEvidence], list[PaperSessionRejection], _OperationalEvidenceBatch | None]:
        normalized_session_ids = _normalize_session_ids(self.session_ids)
        if normalized_session_ids is not None and not normalized_session_ids:
            raise PaperEvaluationReadError("explicit session selection is empty.")
        if self.operational_evidence:
            if normalized_session_ids is not None:
                raise PaperEvaluationDecisionError("operational evidence must enumerate sessions directly from storage.")
            if self.period_start_utc is not None or self.period_end_utc is not None:
                raise PaperEvaluationDecisionError("operational evidence must use the frozen cohort period.")
            batch = load_operational_evidence_batch(
                runtime_db_path=self.runtime_db_path,
                trades_db_path=self.trades_db_path,
            )
            return list(batch.evidences), list(batch.rejections), batch
        return load_paper_session_evidence_batch(
            runtime_db_path=self.runtime_db_path,
            trades_db_path=self.trades_db_path,
            period_start_utc=self.period_start_utc,
            period_end_utc=self.period_end_utc,
            session_ids=normalized_session_ids,
        ) + (None,)

    def evaluate(self) -> PaperEvaluationReport:
        evidences, rejections, operational_batch = self.load()
        normalized_session_ids = _normalize_session_ids(self.session_ids)
        if normalized_session_ids is not None:
            expected_ids = set(normalized_session_ids)
            loaded_ids = {e.session_id for e in evidences}
            seen_ids = loaded_ids | {rejection.session_id for rejection in rejections}
            if seen_ids != expected_ids:
                raise PaperEvaluationDecisionError("loaded evidence does not match the expected session set.")
            if self.operational_evidence:
                raise PaperEvaluationDecisionError("operational evidence must enumerate sessions directly from storage.")
        if self.operational_evidence:
            if operational_batch is None:
                raise PaperEvaluationDecisionError("operational evidence batch is required.")
            return _evaluate_paper_sessions_from_operational_batch(
                evidences,
                policy=self.policy,
                reference_walk_forward=self.reference_walk_forward,
                evaluation_id=self.evaluation_id,
                inclusion_rule=self.inclusion_rule,
                synthetic_test_data=self.synthetic_test_data,
                operational_batch=operational_batch,
                expected_session_ids=None,
                load_rejections=tuple(rejections),
            )
        return evaluate_paper_sessions(
            evidences,
            policy=self.policy,
            reference_walk_forward=self.reference_walk_forward,
            evaluation_id=self.evaluation_id,
            inclusion_rule=self.inclusion_rule,
            synthetic_test_data=self.synthetic_test_data,
            expected_session_ids=normalized_session_ids,
            load_rejections=tuple(rejections),
        )


def evaluate_paper_sessions_from_storage(
    *,
    runtime_db_path: str | Path = "paper_runtime.db",
    trades_db_path: str | Path = "trades.db",
    policy: PaperEvaluationPolicy | None = None,
    reference_walk_forward: WalkForwardResult | None = None,
    evaluation_id: str | None = None,
    inclusion_rule: str = "explicit_session_ids",
    synthetic_test_data: bool = False,
    operational_evidence: bool = True,
    period_start_utc: datetime | None = None,
    period_end_utc: datetime | None = None,
    session_ids: Sequence[str] | None = None,
) -> PaperEvaluationReport:
    adapter = PaperEvaluationAdapter(
        runtime_db_path=runtime_db_path,
        trades_db_path=trades_db_path,
        policy=policy,
        reference_walk_forward=reference_walk_forward,
        evaluation_id=evaluation_id,
        inclusion_rule=inclusion_rule,
        synthetic_test_data=synthetic_test_data,
        operational_evidence=operational_evidence,
        period_start_utc=period_start_utc,
        period_end_utc=period_end_utc,
        session_ids=session_ids,
    )
    return adapter.evaluate()


def load_paper_session_evidence(
    session_id: str,
    *,
    runtime_db_path: str | Path = "paper_runtime.db",
    trades_db_path: str | Path = "trades.db",
):
    evidences, rejections = load_paper_session_evidence_batch(
        runtime_db_path=runtime_db_path,
        trades_db_path=trades_db_path,
        session_ids=(session_id,),
    )
    if rejections:
        raise PaperEvaluationReadError(rejections[0].reason)
    if not evidences:
        raise PaperEvaluationReadError("paper session evidence not found.")
    return evidences[0]
