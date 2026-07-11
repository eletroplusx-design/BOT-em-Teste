from __future__ import annotations

from datetime import timedelta
from typing import Sequence

from domain import Candle

from .adapters import strategy_output_to_order
from .costs import CostModel
from .errors import BacktestConfigurationError, BacktestGapError
from .execution import ExecutionDecision, build_exit_fill, resolve_entry_fill, resolve_exit
from .metrics import compute_metrics
from .models import BacktestConfig, BacktestResult
from .portfolio import Portfolio


class LeakFreeBacktestEngine:
    def __init__(self, config: BacktestConfig | None = None, *, cost_model: CostModel | None = None):
        self.config = config or BacktestConfig()
        self.cost_model = cost_model or CostModel(
            commission_rate=self.config.commission_rate,
            slippage_rate=self.config.slippage_rate,
        )

    def _validate_series(self, candles: Sequence[Candle]) -> None:
        if not candles:
            raise BacktestConfigurationError("At least one candle is required.")
        for idx, candle in enumerate(candles):
            if candle.open_time.tzinfo is None or candle.open_time.utcoffset() is None:
                raise BacktestConfigurationError("Candle open_time must include timezone information.")
            if candle.close_time.tzinfo is None or candle.close_time.utcoffset() is None:
                raise BacktestConfigurationError("Candle close_time must include timezone information.")
            if idx > 0:
                prev = candles[idx - 1]
                if candle.open_time <= prev.open_time:
                    raise BacktestGapError("Candles must be strictly increasing.")
                if self.config.gap_policy.value == "STRICT":
                    if candle.open_time != prev.close_time + timedelta(milliseconds=1):
                        raise BacktestGapError("Gap detected in candle series.")

    def run(self, candles: Sequence[Candle], strategy) -> BacktestResult:
        self._validate_series(candles)
        portfolio = Portfolio(self.config.initial_capital, self.cost_model)
        trades = []
        pending_order = None
        pending_entry_index = None

        for idx, candle in enumerate(candles):
            if pending_order is not None and pending_entry_index == idx:
                entry_fill = resolve_entry_fill(pending_order, candle, self.cost_model)
                portfolio.open_position(pending_order, entry_fill, entry_index=idx)
                opened_symbol = pending_order.symbol
                pending_order = None
                pending_entry_index = None

                open_state = portfolio.open_positions.get(opened_symbol)
                if open_state is not None:
                    exit_decision = resolve_exit(
                        open_state.position,
                        candle,
                        costs=self.cost_model,
                        intrabar_policy=self.config.intrabar_policy,
                    )
                    if exit_decision is not None:
                        exit_fill = build_exit_fill(open_state.position, exit_decision, self.cost_model)
                        executed_trade = portfolio.close_position(
                            opened_symbol,
                            exit_fill,
                            exit_reason=exit_decision.reason,
                            exit_index=idx,
                            gap_handled=exit_decision.gap_handled,
                        )
                        trades.append(executed_trade)

            open_state = portfolio.open_positions.get(candle.symbol)
            if open_state is not None:
                exit_decision = resolve_exit(
                    open_state.position,
                    candle,
                    costs=self.cost_model,
                    intrabar_policy=self.config.intrabar_policy,
                )
                if exit_decision is not None:
                    exit_fill = build_exit_fill(open_state.position, exit_decision, self.cost_model)
                    executed_trade = portfolio.close_position(
                        open_state.position.symbol,
                        exit_fill,
                        exit_reason=exit_decision.reason,
                        exit_index=idx,
                        gap_handled=exit_decision.gap_handled,
                    )
                    trades.append(executed_trade)

            prices = {symbol: state.position.entry for symbol, state in portfolio.open_positions.items()}
            if candle.symbol in prices:
                prices[candle.symbol] = candle.close
            else:
                prices[candle.symbol] = candle.close
            portfolio.equity_at_price(prices, candle.close_time)

            if idx < len(candles) - 1 and not portfolio.open_positions and pending_order is None:
                snapshot_prices = {symbol: state.position.entry for symbol, state in portfolio.open_positions.items()}
                snapshot_prices[candle.symbol] = candle.close
                snapshot = portfolio.snapshot(candle.close_time, snapshot_prices)
                strategy_output = strategy(candles[: idx + 1], snapshot)
                pending_order = strategy_output_to_order(
                    strategy_output,
                    capital=self.config.initial_capital,
                    risk_percent=self.config.risk_percent,
                )
                pending_entry_index = idx + 1 if pending_order is not None else None

        if portfolio.open_positions and self.config.close_open_positions_at_end:
            final_candle = candles[-1]
            for symbol, state in list(portfolio.open_positions.items()):
                decision = resolve_exit(
                    state.position,
                    final_candle,
                    costs=self.cost_model,
                    intrabar_policy=self.config.intrabar_policy,
                )
                if decision is None:
                    decision = ExecutionDecision(
                        price=final_candle.close,
                        reason="FINAL_CLOSE",
                        timestamp=final_candle.close_time,
                        gap_handled=False,
                    )
                exit_fill = build_exit_fill(state.position, decision, self.cost_model)
                executed_trade = portfolio.close_position(
                    symbol,
                    exit_fill,
                    exit_reason=decision.reason,
                    exit_index=len(candles) - 1,
                    gap_handled=decision.gap_handled,
                )
                trades.append(executed_trade)
            portfolio.equity_at_price({}, final_candle.close_time)

        summary = compute_metrics(trades, portfolio.equity_curve, self.config.initial_capital)
        return BacktestResult(
            trades=tuple(trades),
            equity_curve=tuple(portfolio.equity_curve),
            config=self.config,
            starting_capital=self.config.initial_capital,
            final_capital=portfolio.cash,
            symbol=self.config.symbol,
            interval=self.config.interval,
            summary=summary,
            metadata={"lookahead_free": True},
        )
