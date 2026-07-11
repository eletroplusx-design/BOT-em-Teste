from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Sequence

from domain import Candle, DataSource, Direction, Fill, OrderStatus, PaperOrder, Position, PositionStatus, RiskDecision, TradeResult, TradeResultStatus, TradingMode
from domain.serialization import serialize_value
from domain.validation import DomainValidationError, parse_bool_false_only, parse_decimal, parse_symbol, parse_strict_bool

from .errors import BacktestConfigurationError


class IntrabarPolicy(str, Enum):
    STOP_FIRST = "STOP_FIRST"
    TAKE_FIRST = "TAKE_FIRST"


class GapPolicy(str, Enum):
    STRICT = "STRICT"
    OPEN_PRICE = "OPEN_PRICE"


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    initial_capital: Decimal = Decimal("10000")
    risk_percent: Decimal = Decimal("1")
    commission_rate: Decimal | None = None
    slippage_rate: Decimal | None = None
    entry_fee_rate: Decimal = Decimal("0.0004")
    exit_fee_rate: Decimal = Decimal("0.0004")
    spread_bps: Decimal = Decimal("5")
    slippage_bps: Decimal = Decimal("5")
    leverage: Decimal = Decimal("1")
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    paper_only: bool = True
    allow_short: bool = True
    intrabar_policy: IntrabarPolicy = IntrabarPolicy.STOP_FIRST
    gap_policy: GapPolicy = GapPolicy.OPEN_PRICE
    strategy_version: str = "v3_leak_free"
    close_open_positions_at_end: bool = True

    def __post_init__(self) -> None:
        initial_capital = parse_decimal(self.initial_capital, "initial_capital")
        risk_percent = parse_decimal(self.risk_percent, "risk_percent")
        entry_fee_rate = parse_decimal(self.entry_fee_rate, "entry_fee_rate", allow_zero=True)
        exit_fee_rate = parse_decimal(self.exit_fee_rate, "exit_fee_rate", allow_zero=True)
        spread_bps = parse_decimal(self.spread_bps, "spread_bps", allow_zero=True)
        slippage_bps = parse_decimal(self.slippage_bps, "slippage_bps", allow_zero=True)
        leverage = parse_decimal(self.leverage, "leverage")
        symbol = parse_symbol(self.symbol)
        interval = str(self.interval).strip()
        if not interval:
            raise BacktestConfigurationError("interval is required.")
        if type(self.paper_only) is not bool or self.paper_only is not True:
            raise BacktestConfigurationError("paper_only must be True.")
        if type(self.allow_short) is not bool:
            raise BacktestConfigurationError("allow_short must be a boolean.")
        if not isinstance(self.intrabar_policy, IntrabarPolicy):
            raise BacktestConfigurationError("intrabar_policy is invalid.")
        if not isinstance(self.gap_policy, GapPolicy):
            raise BacktestConfigurationError("gap_policy is invalid.")
        if risk_percent <= 0 or risk_percent > 100:
            raise BacktestConfigurationError("risk_percent must be between 0 and 100.")
        if leverage <= 0:
            raise BacktestConfigurationError("leverage must be greater than zero.")
        if self.commission_rate is not None:
            entry_fee_rate = exit_fee_rate = parse_decimal(self.commission_rate, "commission_rate", allow_zero=True)
        if self.slippage_rate is not None:
            slippage_bps = parse_decimal(self.slippage_rate, "slippage_rate", allow_zero=True) * Decimal("10000")
        object.__setattr__(self, "initial_capital", initial_capital)
        object.__setattr__(self, "risk_percent", risk_percent)
        object.__setattr__(self, "entry_fee_rate", entry_fee_rate)
        object.__setattr__(self, "exit_fee_rate", exit_fee_rate)
        object.__setattr__(self, "spread_bps", spread_bps)
        object.__setattr__(self, "slippage_bps", slippage_bps)
        object.__setattr__(self, "leverage", leverage)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "interval", interval)
        object.__setattr__(self, "strategy_version", self.strategy_version.strip() or "v3_leak_free")

    @property
    def commission_rate_effective(self) -> Decimal:
        return self.entry_fee_rate

    @property
    def slippage_rate_effective(self) -> Decimal:
        return self.slippage_bps / Decimal("10000")


@dataclass(frozen=True, slots=True)
class EquityPoint:
    timestamp: datetime
    equity: Decimal
    cash: Decimal
    unrealized_pnl: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise BacktestConfigurationError("Equity timestamps must be timezone-aware.")
        object.__setattr__(self, "timestamp", self.timestamp.astimezone(timezone.utc))
        object.__setattr__(self, "equity", parse_decimal(self.equity, "equity", allow_zero=True, allow_negative=True))
        object.__setattr__(self, "cash", parse_decimal(self.cash, "cash", allow_zero=True, allow_negative=True))
        object.__setattr__(self, "unrealized_pnl", parse_decimal(self.unrealized_pnl, "unrealized_pnl", allow_zero=True, allow_negative=True))


@dataclass(frozen=True, slots=True)
class ExecutedTrade:
    order: PaperOrder
    entry_fill: Fill
    exit_fill: Fill
    trade: TradeResult
    realized_rr: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    entry_fee: Decimal
    exit_fee: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    entry_index: int
    exit_index: int
    capital_before: Decimal
    capital_after: Decimal
    gap_handled: bool = False
    intrabar_policy: IntrabarPolicy = IntrabarPolicy.STOP_FIRST
    risk_decision: RiskDecision | None = None

    @property
    def resultado(self) -> str:
        return self.trade.resultado

    @property
    def pnl_reais(self) -> Decimal:
        return self.trade.pnl_reais

    @property
    def pnl_percent(self) -> Decimal:
        return self.trade.pnl_percent

    @property
    def symbol(self) -> str:
        return self.trade.symbol

    @property
    def direction(self) -> Direction:
        return self.trade.direction

    @property
    def total_costs(self) -> Decimal:
        return self.entry_fee + self.exit_fee + self.spread_cost + self.slippage_cost


@dataclass(frozen=True, slots=True)
class BacktestResult:
    trades: tuple[ExecutedTrade, ...]
    equity_curve: tuple[EquityPoint, ...]
    config: BacktestConfig
    starting_capital: Decimal
    final_capital: Decimal
    symbol: str
    interval: str
    summary: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return serialize_value(
            {
                "trades": self.trades,
                "equity_curve": self.equity_curve,
                "config": self.config,
                "starting_capital": self.starting_capital,
                "final_capital": self.final_capital,
                "symbol": self.symbol,
                "interval": self.interval,
                "summary": self.summary,
                "metadata": self.metadata,
            }
        )


StrategyCallback = Callable[[Sequence[Candle], "PortfolioSnapshot"], object | None]


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    cash: Decimal
    equity: Decimal
    open_positions: int
    realized_pnl: Decimal
    timestamp: datetime

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise BacktestConfigurationError("PortfolioSnapshot timestamp must be timezone-aware.")
        object.__setattr__(self, "timestamp", self.timestamp.astimezone(timezone.utc))
