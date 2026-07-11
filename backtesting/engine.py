from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Sequence

from domain import Candle, RiskDecision
from domain.validation import DomainValidationError

from .adapters import strategy_output_to_order
from .costs import CostModel
from .errors import BacktestConfigurationError, BacktestDataError, BacktestGapError
from .execution import resolve_entry_execution, resolve_exit_execution, resolve_gap_exit_execution
from .metrics import compute_metrics
from .models import BacktestConfig, BacktestResult, EquityPoint, PortfolioSnapshot
from .portfolio import Portfolio


RiskDecisionProvider = Callable[[PortfolioSnapshot, object], RiskDecision]


def _approved_risk_decision(snapshot: PortfolioSnapshot, order: object) -> RiskDecision:
    capital = snapshot.equity
    risk_percent = Decimal("1")
    return RiskDecision(
        allowed=True,
        reason="Approved for leak-free backtest.",
        blocked_by="N/A",
        capital=capital,
        risk_percent=risk_percent,
        exposure=Decimal("0"),
        timestamp=snapshot.timestamp,
        exchange_info_ok=True,
        strategy_version="v3_leak_free",
        notes="",
    )


class LeakFreeBacktestEngine:
    def __init__(self, config: BacktestConfig | None = None, *, cost_model: CostModel | None = None):
        self.config = config or BacktestConfig()
        self.cost_model = cost_model or CostModel(
            entry_fee_rate=self.config.entry_fee_rate,
            exit_fee_rate=self.config.exit_fee_rate,
            spread_bps=self.config.spread_bps,
            slippage_bps=self.config.slippage_bps,
        )

    def _validate_series(self, candles: Sequence[Candle]) -> None:
        if not candles:
            raise BacktestConfigurationError("At least one candle is required.")
        for idx, candle in enumerate(candles):
            if candle.symbol != self.config.symbol:
                raise BacktestDataError("Candle symbol does not match backtest configuration.")
            if candle.interval != self.config.interval:
                raise BacktestDataError("Candle interval does not match backtest configuration.")
            if candle.open_time.tzinfo is None or candle.open_time.utcoffset() is None:
                raise BacktestDataError("Candle open_time must include timezone information.")
            if candle.close_time.tzinfo is None or candle.close_time.utcoffset() is None:
                raise BacktestDataError("Candle close_time must include timezone information.")
            if candle.close_time < candle.open_time:
                raise BacktestDataError("Candle close_time cannot be earlier than open_time.")
            if idx > 0:
                prev = candles[idx - 1]
                if candle.open_time <= prev.open_time:
                    raise BacktestDataError("Candles must be strictly increasing.")
                if candle.open_time == prev.open_time:
                    raise BacktestDataError("Duplicate candle detected.")
                if self.config.gap_policy.value == "STRICT" and candle.open_time != prev.close_time + timedelta(milliseconds=1):
                    raise BacktestGapError("Gap detected in candle series.")

    def run(self, candles: Sequence[Candle], strategy, *, risk_decision_provider: RiskDecisionProvider | None = None) -> BacktestResult:
        self._validate_series(candles)
        provider = risk_decision_provider or _approved_risk_decision
        portfolio = Portfolio(self.config.initial_capital, self.config, self.cost_model)
        trades = []

        initial_timestamp = candles[0].open_time
        portfolio.equity_curve.append(
            EquityPoint(
                timestamp=initial_timestamp,
                equity=self.config.initial_capital,
                cash=self.config.initial_capital,
                unrealized_pnl=Decimal("0"),
            )
        )

        for idx, candle in enumerate(candles):
            current_prices = {symbol: state.position.entry for symbol, state in portfolio.open_positions.items()}
            current_prices[candle.symbol] = candle.close
            portfolio.mark_equity(current_prices, candle.close_time)

            if idx >= len(candles) - 1:
                continue

            if portfolio.open_positions:
                continue

            snapshot = portfolio.snapshot(candle.close_time, current_prices)
            strategy_output = strategy(candles[: idx + 1], snapshot)
            order = strategy_output_to_order(
                strategy_output,
                capital=snapshot.equity,
                risk_percent=self.config.risk_percent,
            )
            if order is None:
                continue
            if order.direction.value == "VENDA" and not self.config.allow_short:
                continue

            risk_decision = provider(snapshot, order)
            if not risk_decision.allowed or not risk_decision.exchange_info_ok:
                continue

            if order.symbol != self.config.symbol or self.config.interval != candle.interval:
                continue

            entry_idx = idx + 1
            if entry_idx >= len(candles):
                continue

            entry_candle = candles[entry_idx]
            entry_execution = resolve_entry_execution(order, entry_candle, self.cost_model)
            try:
                portfolio.open_position(order, entry_execution, entry_index=entry_idx, risk_decision=risk_decision)
            except (BacktestConfigurationError, DomainValidationError):
                continue

            if entry_idx == len(candles) - 1:
                continue

            exit_idx = entry_idx
            while exit_idx < len(candles):
                active_candle = candles[exit_idx]
                exit_decision = resolve_exit_execution(
                    portfolio.open_positions[order.symbol].position,
                    active_candle,
                    costs=self.cost_model,
                    intrabar_policy=self.config.intrabar_policy,
                )
                if exit_decision is not None:
                    executed_trade = portfolio.close_position(
                        order.symbol,
                        exit_decision,
                        exit_reason=exit_decision.reason,
                        exit_index=exit_idx,
                        gap_handled=exit_decision.gap_handled,
                    )
                    trades.append(executed_trade)
                    break
                exit_idx += 1

        if portfolio.open_positions and self.config.close_open_positions_at_end:
            final_candle = candles[-1]
            for symbol, state in list(portfolio.open_positions.items()):
                exit_execution = resolve_gap_exit_execution(state.position, final_candle, costs=self.cost_model)
                executed_trade = portfolio.close_position(
                    symbol,
                    exit_execution,
                    exit_reason=exit_execution.reason,
                    exit_index=len(candles) - 1,
                    gap_handled=True,
                )
                trades.append(executed_trade)

        summary = compute_metrics(
            trades,
            portfolio.equity_curve,
            self.config.initial_capital,
            total_bars=portfolio.total_bars,
            exposure_bars=portfolio.exposure_bars,
        )
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
