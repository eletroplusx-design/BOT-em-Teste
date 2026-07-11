from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from .errors import ValidationSelectionError
from .models import CandidateEvaluation, CandidateConfig, SelectionCriteria


@dataclass(frozen=True, slots=True)
class SelectionOutcome:
    approved: bool
    candidate: CandidateConfig | None
    reason: str
    ranking: tuple[str, ...] = ()
    evaluated_candidates: tuple[CandidateEvaluation, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "approved": self.approved,
            "candidate": self.candidate.as_dict() if self.candidate else None,
            "reason": self.reason,
            "ranking": self.ranking,
            "evaluated_candidates": [item.as_dict() for item in self.evaluated_candidates],
        }


def _metric(metric, default: Decimal = Decimal("-Infinity")) -> Decimal:
    if metric is None:
        return default
    if isinstance(metric, Decimal):
        return metric
    return Decimal(str(metric))


def _passes(metrics, criteria: SelectionCriteria) -> bool:
    if metrics.total_trades < criteria.min_total_trades:
        return False
    if criteria.require_defined_profit_factor and metrics.profit_factor is None:
        return False
    if metrics.net_return_percent < criteria.min_net_return:
        return False
    if metrics.drawdown_max_percent > criteria.max_drawdown_percent:
        return False
    if metrics.expectancy < criteria.min_expectancy:
        return False
    if metrics.profit_factor is not None and metrics.profit_factor < criteria.min_profit_factor:
        return False
    return True


def select_configuration(
    candidate_evaluations: Sequence[CandidateEvaluation],
    criteria: SelectionCriteria | None = None,
) -> SelectionOutcome:
    criteria = criteria or SelectionCriteria()
    if not candidate_evaluations:
        return SelectionOutcome(approved=False, candidate=None, reason="nenhuma configuração aprovada")

    eligible: list[CandidateEvaluation] = []
    rejected: list[CandidateEvaluation] = []
    for evaluation in candidate_evaluations:
        if _passes(evaluation.validation_metrics, criteria) and _passes(evaluation.train_metrics, criteria):
            eligible.append(evaluation)
        else:
            rejected.append(evaluation)

    if not eligible:
        return SelectionOutcome(approved=False, candidate=None, reason="nenhuma configuração aprovada", evaluated_candidates=tuple(candidate_evaluations))

    def rank_key(evaluation: CandidateEvaluation):
        validation = evaluation.validation_metrics
        return (
            _metric(validation.profit_factor),
            _metric(validation.expectancy),
            _metric(validation.net_return_percent),
            -_metric(validation.drawdown_max_percent, Decimal("0")),
            -evaluation.stability_score,
            evaluation.candidate.name,
            evaluation.candidate.as_dict()["parameters"],
        )

    ordered = sorted(eligible, key=rank_key, reverse=True)
    best = ordered[0]
    ranking = tuple(item.candidate.name for item in ordered)
    if len(ordered) > 1:
        first, second = ordered[0], ordered[1]
        if rank_key(first) == rank_key(second):
            ordered = sorted(ordered, key=lambda item: (item.candidate.name, item.candidate.as_dict()["parameters"]))
            best = ordered[0]
            ranking = tuple(item.candidate.name for item in ordered)
    return SelectionOutcome(approved=True, candidate=best.candidate, reason="approved", ranking=ranking, evaluated_candidates=tuple(candidate_evaluations))
