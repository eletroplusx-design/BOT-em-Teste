from .adapters import backtest_result_to_dict, dataframe_to_candles, strategy_output_to_order
from .costs import CostModel
from .engine import LeakFreeBacktestEngine
from .errors import (
    BacktestConfigurationError,
    BacktestDataError,
    BacktestError,
    BacktestExecutionError,
    BacktestGapError,
    BacktestLookaheadError,
)
from .metrics import compute_metrics, max_drawdown
from .models import (
    BacktestConfig,
    BacktestResult,
    EquityPoint,
    ExecutedTrade,
    GapPolicy,
    IntrabarPolicy,
    PortfolioSnapshot,
)

BacktestEngine = LeakFreeBacktestEngine

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "BacktestConfigurationError",
    "BacktestDataError",
    "BacktestError",
    "BacktestExecutionError",
    "BacktestGapError",
    "BacktestLookaheadError",
    "BacktestEngine",
    "CostModel",
    "EquityPoint",
    "ExecutedTrade",
    "GapPolicy",
    "IntrabarPolicy",
    "LeakFreeBacktestEngine",
    "PortfolioSnapshot",
    "backtest_result_to_dict",
    "compute_metrics",
    "dataframe_to_candles",
    "max_drawdown",
    "strategy_output_to_order",
]
