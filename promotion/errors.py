from __future__ import annotations


class PromotionValidationError(Exception):
    """Base error for promotion workflows."""


class PromotionEvidenceError(PromotionValidationError):
    """Raised when phase 5 evidence is incomplete or inconsistent."""


class PromotionPolicyError(PromotionValidationError):
    """Raised when a promotion policy is invalid."""


class PromotionDecisionError(PromotionValidationError):
    """Raised when a promotion decision cannot be produced."""
