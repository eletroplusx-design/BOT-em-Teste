class PaperEvaluationError(Exception):
    """Base error for the monitored paper evaluation workflow."""


class PaperEvaluationPolicyError(PaperEvaluationError):
    """Raised when an evaluation policy is malformed or contradictory."""


class PaperEvaluationEvidenceError(PaperEvaluationError):
    """Raised when paper-session evidence is incomplete, inconsistent, or tampered."""


class PaperEvaluationMetricsError(PaperEvaluationError):
    """Raised when metrics cannot be computed safely."""


class PaperEvaluationDecisionError(PaperEvaluationError):
    """Raised when an evaluation decision cannot be produced safely."""


class PaperEvaluationManifestError(PaperEvaluationError):
    """Raised when the evaluation manifest is invalid or unstable."""


class PaperEvaluationReadError(PaperEvaluationError):
    """Raised when strict SQLite reads fail closed."""
