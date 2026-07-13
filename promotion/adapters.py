from __future__ import annotations

from validation.models import WalkForwardResult

from .evidence import PromotionEvidence, build_promotion_evidence


def adapt_walk_forward_result(result: WalkForwardResult) -> PromotionEvidence:
    return build_promotion_evidence(result)
