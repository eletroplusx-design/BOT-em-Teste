class ValidationError(Exception):
    """Base error for validation workflows."""


class ValidationSplitError(ValidationError):
    """Raised when a chronological split is invalid."""


class ValidationSelectionError(ValidationError):
    """Raised when a candidate cannot be selected."""


class ValidationFreezeError(ValidationError):
    """Raised when a frozen configuration is mutated or reselection is attempted."""


class ValidationEvaluationError(ValidationError):
    """Raised when a segment evaluation fails or returns malformed metrics."""
