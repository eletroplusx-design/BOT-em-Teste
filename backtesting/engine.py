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
from .execution import resolve_entry_execution, resolve_exit_execution, resolve_final_close_execution
from .metrics import compute_metrics
from .models import BacktestConfig, BacktestResult, EquityPoint, PortfolioSnapshot
from .portfolio import Portfolio


RiskDecisionProvider = Callable[[PortfolioSnapshot, object], RiskDecision]


class LeakFreeBacktestEngine:
    def __init__(self, config: BacktestConfig | None = None, *, cost_model: CostModel | None = None):
        self.config = config or BacktestConfig()
        self.cost_model = cost_model or CostModel(
            entry_fee_rate=self.config.entry_fee_rate,
            exit_fee_rate=self.config.exit_fee_rate,
            spread_bps=self.config.spread_bps,
            slippage_bps=self.config.slippage_bps,
        )

    def _default_risk_decision_provider(self, snapshot: PortfolioSnapshot, order: object) -> RiskDecision:
        capital = snapshot.equity
        quantity = getattr(order, "quantity", Decimal("0"))
        entry = getattr(order, "entry", Decimal("0"))
        leverage = self.config.leverage
        exposure = Decimal("0")
        try:
            exposure = (Decimal(str(entry)) * Decimal(str(quantity))) / leverage if leverage > 0 else Decimal("0")
        except Exception:
            exposure = Decimal("0")

        allowed = capital > 0 and quantity > 0 and exposure <= capital
        reason = "Approved by default risk policy." if allowed else "Insufficient capital for default risk policy."
        blocked_by = "N/A" if allowed else "RISK"
        return RiskDecision(
            allowed=allowed,
            reason=reason,
            blocked_by=blocked_by,
            capital=capital,
            risk_percent=self.config.risk_percent,
            exposure=exposure,
            timestamp=snapshot.timestamp,
            exchange_info_ok=True,
            strategy_version=self.config.strategy_version,
            notes="",
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
        provider = risk_decision_provider or self._default_risk_decision_provider
        portfolio = Portfolio(self.config.initial_capital, self.config, self.cost_model)
        trades = []
        pending_order = None
        pending_risk_decision = None

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
            if pending_order is not None:
                entry_execution = resolve_entry_execution(pending_order, candle, self.cost_model)
                try:
                    portfolio.open_position(
                        pending_order,
                        entry_execution,
                        entry_index=idx,
                        risk_decision=pending_risk_decision,
                    )
                except (BacktestConfigurationError, DomainValidationError):
                    pending_order = None
                    pending_risk_decision = None
                else:
                    pending_order = None
                    pending_risk_decision = None

            open_symbols = list(portfolio.open_positions.keys())
            for symbol in open_symbols:
                exit_decision = resolve_exit_execution(
                    portfolio.open_positions[symbol].position,
                    candle,
                    costs=self.cost_model,
                    intrabar_policy=self.config.intrabar_policy,
                )
                if exit_decision is None:
                    continue
                executed_trade = portfolio.close_position(
                    symbol,
                    exit_decision,
                    exit_reason=exit_decision.reason,
                    exit_index=idx,
                    gap_handled=exit_decision.gap_handled,
                )
                trades.append(executed_trade)

            current_prices = {symbol: state.position.entry for symbol, state in portfolio.open_positions.items()}
            current_prices[candle.symbol] = candle.close
            portfolio.mark_equity(current_prices, candle.close_time)

            snapshot = portfolio.snapshot(candle.close_time, current_prices)
            if idx >= len(candles) - 1:
                continue

            strategy_output = strategy(candles[: idx + 1], snapshot)
            order = strategy_output_to_order(
                strategy_output,
                capital=snapshot.equity,
                risk_percent=self.config.risk_percent,
            )
            if order is None:
                continue
            if portfolio.open_positions or pending_order is not None:
                continue
            if order.direction.value == "VENDA" and not self.config.allow_short:
                continue

            risk_decision = provider(snapshot, order)
            if not isinstance(risk_decision, RiskDecision):
                raise BacktestConfigurationError("risk_decision_provider must return RiskDecision.")
            if not risk_decision.allowed or not risk_decision.exchange_info_ok:
                continue

            if order.symbol != self.config.symbol or self.config.interval != candle.interval:
                continue

            pending_order = order
            pending_risk_decision = risk_decision

        if portfolio.open_positions and self.config.close_open_positions_at_end:
            final_candle = candles[-1]
            for symbol, state in list(portfolio.open_positions.items()):
                exit_execution = resolve_final_close_execution(state.position, final_candle, costs=self.cost_model)
                executed_trade = portfolio.close_position(
                    symbol,
                    exit_execution,
                    exit_reason=exit_execution.reason,
                    exit_index=len(candles) - 1,
                    gap_handled=False,
                )
                trades.append(executed_trade)
            if portfolio.equity_curve:
                portfolio.equity_curve[-1] = EquityPoint(
                    timestamp=final_candle.close_time,
                    equity=portfolio.cash,
                    cash=portfolio.cash,
                    unrealized_pnl=Decimal("0"),
                )

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
