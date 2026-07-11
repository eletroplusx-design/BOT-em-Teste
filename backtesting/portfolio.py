from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict

from domain import DataSource, Direction, Fill, OrderStatus, PaperOrder, Position, PositionStatus, TradeResult, TradeResultStatus, TradingMode

from .costs import CostModel
from .errors import BacktestConfigurationError
from .models import EquityPoint, ExecutedTrade, PortfolioSnapshot


@dataclass(frozen=True, slots=True)
class OpenPositionState:
    position: Position
    entry_fill: Fill
    entry_index: int


@dataclass
class Portfolio:
    starting_capital: Decimal
    cost_model: CostModel
    cash: Decimal = field(init=False)
    realized_pnl: Decimal = field(default=Decimal("0"))
    open_positions: Dict[str, OpenPositionState] = field(default_factory=dict)
    equity_curve: list[EquityPoint] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cash = self.starting_capital

    def _calculate_equity(self, prices: Dict[str, Decimal] | None = None) -> Decimal:
        unrealized = Decimal("0")
        for symbol, state in self.open_positions.items():
            if not prices or symbol not in prices:
                continue
            current = prices[symbol]
            if state.position.direction == Direction.COMPRA:
                unrealized += (current - state.position.entry) * state.position.quantity
            else:
                unrealized += (state.position.entry - current) * state.position.quantity
        return self.cash + unrealized

    def snapshot(self, timestamp: datetime, prices: Dict[str, Decimal] | None = None) -> PortfolioSnapshot:
        equity = self._calculate_equity(prices)
        return PortfolioSnapshot(
            cash=self.cash,
            equity=equity,
            open_positions=len(self.open_positions),
            realized_pnl=self.realized_pnl,
            timestamp=timestamp.astimezone(timezone.utc),
        )

    def equity_at_price(self, prices: Dict[str, Decimal], timestamp: datetime) -> Decimal:
        unrealized = self._calculate_equity(prices) - self.cash
        equity = self.cash + unrealized
        self.equity_curve.append(EquityPoint(timestamp=timestamp, equity=equity, cash=self.cash, unrealized_pnl=unrealized))
        return equity

    def open_position(self, order: PaperOrder, fill: Fill, *, entry_index: int) -> Position:
        if order.symbol in self.open_positions:
            raise BacktestConfigurationError(f"Position for {order.symbol} already open.")
        position = Position(
            symbol=order.symbol,
            direction=order.direction,
            entry=fill.price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            quantity=order.quantity,
            opened_at=fill.filled_at,
            status=PositionStatus.OPEN,
            source=DataSource.PAPER,
            paper=True,
            trading_mode=TradingMode.PAPER,
            unrealized_pnl=Decimal("0"),
        )
        self.cash -= fill.fee
        self.open_positions[order.symbol] = OpenPositionState(position=position, entry_fill=fill, entry_index=entry_index)
        return position

    def close_position(self, symbol: str, fill: Fill, *, exit_reason: str, exit_index: int, gap_handled: bool = False) -> ExecutedTrade:
        state = self.open_positions.pop(symbol, None)
        if state is None:
            raise BacktestConfigurationError(f"Position for {symbol} is not open.")

        position = state.position
        entry_fill = state.entry_fill
        if position.direction == Direction.COMPRA:
            gross_pnl = (fill.price - position.entry) * position.quantity
        else:
            gross_pnl = (position.entry - fill.price) * position.quantity

        net_pnl = gross_pnl - entry_fill.fee - fill.fee
        self.cash += gross_pnl - fill.fee
        self.realized_pnl += net_pnl

        opened_at = position.opened_at
        closed_at = fill.filled_at
        entry_notional = position.entry * position.quantity
        pnl_percent = (net_pnl / entry_notional * Decimal("100")) if entry_notional != 0 else Decimal("0")
        risk_amount = abs(position.entry - position.stop_loss) * position.quantity
        realized_rr = (net_pnl / risk_amount) if risk_amount != 0 else Decimal("0")

        trade = TradeResult(
            symbol=position.symbol,
            direction=position.direction,
            entry=position.entry,
            exit_price=fill.price,
            quantity=position.quantity,
            pnl_percent=pnl_percent,
            pnl_reais=net_pnl,
            status=TradeResultStatus.CLOSED,
            reason=exit_reason,
            opened_at=opened_at,
            closed_at=closed_at,
            source=DataSource.PAPER,
            paper=True,
            trading_mode=TradingMode.PAPER,
            strategy_version="v3_leak_free",
        )

        return ExecutedTrade(
            order=PaperOrder(
                symbol=position.symbol,
                direction=position.direction,
                entry=position.entry,
                quantity=position.quantity,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                opened_at=opened_at,
                status=OrderStatus.CLOSED,
                source=DataSource.PAPER,
                paper=True,
                trading_mode=TradingMode.PAPER,
                order_id=state.entry_fill.order_id,
            ),
            entry_fill=entry_fill,
            exit_fill=fill,
            trade=trade,
            realized_rr=realized_rr,
            entry_index=state.entry_index,
            exit_index=exit_index,
            gap_handled=gap_handled,
        )
