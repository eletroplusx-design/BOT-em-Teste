from __future__ import annotations


class PaperRuntimeError(Exception):
    """Base error for the monitored paper runtime."""


class PaperRuntimePolicyError(PaperRuntimeError):
    """Raised when a runtime policy or contract is invalid."""


class PaperRuntimeSessionError(PaperRuntimeError):
    """Raised when a session transition or identity check fails."""


class PaperRuntimeStoreError(PaperRuntimeError):
    """Raised when persistence cannot be read or written safely."""


class PaperRuntimeAuditError(PaperRuntimeError):
    """Raised when the audit hash chain or sanitization fails."""


class PaperRuntimeMonitorError(PaperRuntimeError):
    """Raised when a runtime snapshot cannot be evaluated safely."""
