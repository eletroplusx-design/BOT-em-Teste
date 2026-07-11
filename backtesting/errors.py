from __future__ import annotations


class BacktestError(Exception):
    """Base error for leak-free backtesting failures."""


class BacktestConfigurationError(BacktestError):
    """Raised when a configuration value is invalid."""


class BacktestDataError(BacktestError):
    """Raised when input market data is malformed or unsafe."""


class BacktestExecutionError(BacktestError):
    """Raised when execution cannot continue safely."""


class BacktestGapError(BacktestDataError):
    """Raised when gap handling policy blocks a series."""


class BacktestLookaheadError(BacktestError):
    """Raised when a strategy tries to use future data."""
