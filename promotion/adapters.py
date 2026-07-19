from __future__ import annotations

from typing import Any

from validation.models import WalkForwardResult

from .evidence import PromotionEvidence, build_promotion_evidence
from .errors import PromotionEvidenceError


def adapt_walk_forward_result(result: WalkForwardResult) -> PromotionEvidence:
    return build_promotion_evidence(result)


def adapt_historical_experiment_report(report: Any) -> PromotionEvidence:
    if isinstance(report, dict):
        classification = report.get("classification")
        operational_evidence = report.get("operational_evidence")
        paper_promotion_eligible = report.get("paper_promotion_eligible")
    else:
        classification = getattr(report, "classification", None)
        operational_evidence = getattr(report, "operational_evidence", None)
        paper_promotion_eligible = getattr(report, "paper_promotion_eligible", None)
    if classification == "historical_research_only" or operational_evidence is False or paper_promotion_eligible is False:
        raise PromotionEvidenceError("historical experiment reports cannot be used as promotion evidence.")
    raise PromotionEvidenceError("historical experiment reports cannot be used as promotion evidence.")
