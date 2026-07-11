from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict

from domain import DataSource, Direction, Fill, OrderStatus, PaperOrder, Position, PositionStatus, RiskDecision, TradeResult, TradeResultStatus, TradingMode

from .costs import CostModel
from .errors import BacktestConfigurationError
from .execution import ExecutionDecision
from .models import BacktestConfig, EquityPoint, ExecutedTrade, PortfolioSnapshot


@dataclass(frozen=True, slots=True)
class OpenPositionState:
    position: Position
    entry_fill: Fill
    entry_execution: ExecutionDecision
    entry_index: int
    risk_decision: RiskDecision


@dataclass
class Portfolio:
    starting_capital: Decimal
    config: BacktestConfig
    cost_model: CostModel
    cash: Decimal = field(init=False)
    realized_pnl: Decimal = field(default=Decimal("0"))
    open_positions: Dict[str, OpenPositionState] = field(default_factory=dict)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    exposure_bars: int = 0
    total_bars: int = 0

    def __post_init__(self) -> None:
        self.cash = self.starting_capital

    def _calculate_equity(self, prices: Dict[str, Decimal] | None = None) -> Decimal:
        unrealized = Decimal("0")
        for symbol, state in self.open_positions.items():
            if not prices or symbol not in prices:
                continue
            current = prices[symbol]
            if state.position.direction == Direction.COMPRA:
                unrealized += (current - state.entry_execution.base_price) * state.position.quantity
            else:
                unrealized += (state.entry_execution.base_price - current) * state.position.quantity
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

    def mark_equity(self, prices: Dict[str, Decimal], timestamp: datetime, *, exposed: bool | None = None) -> Decimal:
        equity = self._calculate_equity(prices)
        unrealized = equity - self.cash
        self.equity_curve.append(EquityPoint(timestamp=timestamp.astimezone(timezone.utc), equity=equity, cash=self.cash, unrealized_pnl=unrealized))
        self.total_bars += 1
        if exposed if exposed is not None else bool(self.open_positions):
            self.exposure_bars += 1
        return equity

    def open_position(self, order: PaperOrder, entry_execution: ExecutionDecision, *, entry_index: int, risk_decision: RiskDecision) -> Position:
        if order.symbol in self.open_positions:
            raise BacktestConfigurationError(f"Position for {order.symbol} already open.")
        if not risk_decision.allowed or not risk_decision.exchange_info_ok:
            raise BacktestConfigurationError("Risk decision blocks the position.")

        required_margin = (entry_execution.fill_price * order.quantity) / self.config.leverage
        entry_costs = entry_execution.fee + entry_execution.spread_cost + entry_execution.slippage_cost
        required_cash = required_margin + entry_costs
        if required_cash > self.cash:
            raise BacktestConfigurationError("Insufficient capital for position.")
        position = Position(
            symbol=order.symbol,
            direction=order.direction,
            entry=entry_execution.fill_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            quantity=order.quantity,
            opened_at=entry_execution.timestamp,
            status=PositionStatus.OPEN,
            source=DataSource.PAPER,
            paper=True,
            trading_mode=TradingMode.PAPER,
            unrealized_pnl=Decimal("0"),
        )
        self.cash -= entry_costs
        self.open_positions[order.symbol] = OpenPositionState(
            position=position,
            entry_fill=Fill(
                price=entry_execution.fill_price,
                quantity=order.quantity,
                filled_at=entry_execution.timestamp,
                fee=entry_execution.fee,
                source=DataSource.PAPER,
                is_real=False,
                order_id=order.order_id,
            ),
            entry_execution=entry_execution,
            entry_index=entry_index,
            risk_decision=risk_decision,
        )
        return position

    def close_position(self, symbol: str, exit_execution: ExecutionDecision, *, exit_reason: str, exit_index: int, gap_handled: bool = False) -> ExecutedTrade:
        state = self.open_positions.pop(symbol, None)
        if state is None:
            raise BacktestConfigurationError(f"Position for {symbol} is not open.")

        position = state.position
        entry_exec = state.entry_execution
        cash_before_close = self.cash
        exit_fill = Fill(
            price=exit_execution.fill_price,
            quantity=position.quantity,
            filled_at=exit_execution.timestamp,
            fee=exit_execution.fee,
            source=DataSource.PAPER,
            is_real=False,
            order_id=None,
        )

        if position.direction == Direction.COMPRA:
            gross_pnl = (exit_execution.base_price - entry_exec.base_price) * position.quantity
        else:
            gross_pnl = (entry_exec.base_price - exit_execution.base_price) * position.quantity

        net_pnl = gross_pnl - entry_exec.fee - exit_execution.fee - entry_exec.spread_cost - exit_execution.spread_cost - entry_exec.slippage_cost - exit_execution.slippage_cost
        cash_delta = gross_pnl - exit_execution.fee - exit_execution.spread_cost - exit_execution.slippage_cost
        self.cash += cash_delta
        self.realized_pnl += net_pnl

        entry_notional = entry_exec.base_price * position.quantity
        risk_amount = abs(position.entry - position.stop_loss) * position.quantity
        realized_rr = (net_pnl / risk_amount) if risk_amount != 0 else Decimal("0")
        pnl_percent = (net_pnl / entry_notional * Decimal("100")) if entry_notional != 0 else Decimal("0")

        trade = TradeResult(
            symbol=position.symbol,
            direction=position.direction,
            entry=position.entry,
            exit_price=exit_execution.fill_price,
            quantity=position.quantity,
            pnl_percent=pnl_percent,
            pnl_reais=net_pnl,
            status=TradeResultStatus.CLOSED,
            reason=exit_reason,
            opened_at=position.opened_at,
            closed_at=exit_execution.timestamp,
            source=DataSource.PAPER,
            paper=True,
            trading_mode=TradingMode.PAPER,
            strategy_version=self.config.strategy_version,
        )

        return ExecutedTrade(
            order=PaperOrder(
                symbol=position.symbol,
                direction=position.direction,
                entry=position.entry,
                quantity=position.quantity,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                opened_at=position.opened_at,
                status=OrderStatus.CLOSED,
                source=DataSource.PAPER,
                paper=True,
                trading_mode=TradingMode.PAPER,
                order_id=state.entry_fill.order_id,
            ),
            entry_fill=state.entry_fill,
            exit_fill=exit_fill,
            trade=trade,
            realized_rr=realized_rr,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            entry_fee=entry_exec.fee,
            exit_fee=exit_execution.fee,
            spread_cost=entry_exec.spread_cost + exit_execution.spread_cost,
            slippage_cost=entry_exec.slippage_cost + exit_execution.slippage_cost,
            entry_index=state.entry_index,
            exit_index=exit_index,
            capital_before=cash_before_close,
            capital_after=self.cash,
            gap_handled=gap_handled,
            intrabar_policy=self.config.intrabar_policy,
            risk_decision=state.risk_decision,
        )
