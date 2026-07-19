from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import timedelta
from decimal import Decimal
from typing import Any

from backtesting import BacktestConfig, LeakFreeBacktestEngine
from domain import Candle, DataSource, Direction, Signal
from historical_experiments import build_historical_experiment_plan
from historical_replay import HistoricalDataset
from validation import CandidateConfig, SelectionCriteria, TrustedLeakFreeBacktestRunner, ValidationSplitConfig
from validation.errors import ValidationSelectionError


BASELINE_A_STRATEGY_VERSION = "baseline_a_ema_trend_pullback_v1"
BASELINE_A_SYMBOL = "BTCUSDT"
BASELINE_A_INTERVAL = "1h"
BASELINE_A_FAST_EMA = 20
BASELINE_A_MID_EMA = 50
BASELINE_A_SLOW_EMA = 200
BASELINE_A_ATR_PERIOD = 14
BASELINE_A_PULLBACK_LOOKBACK = 3
BASELINE_A_STOP_ATR_MULTIPLIER = Decimal("1.5")
BASELINE_A_REWARD_MULTIPLIER = Decimal("2")
BASELINE_A_MIN_HISTORY = BASELINE_A_SLOW_EMA + 1


BASELINE_A_CANDIDATE = CandidateConfig.from_mapping(
    BASELINE_A_STRATEGY_VERSION,
    {
        "fast_ema": BASELINE_A_FAST_EMA,
        "mid_ema": BASELINE_A_MID_EMA,
        "slow_ema": BASELINE_A_SLOW_EMA,
        "atr_period": BASELINE_A_ATR_PERIOD,
        "pullback_lookback": BASELINE_A_PULLBACK_LOOKBACK,
        "stop_atr_multiplier": BASELINE_A_STOP_ATR_MULTIPLIER,
        "reward_multiplier": BASELINE_A_REWARD_MULTIPLIER,
        "direction": "COMPRA",
        "timeframe": BASELINE_A_INTERVAL,
    },
)


def baseline_a_candidate_config() -> CandidateConfig:
    return BASELINE_A_CANDIDATE


def baseline_a_backtest_config(*, symbol: str = BASELINE_A_SYMBOL, interval: str = BASELINE_A_INTERVAL) -> BacktestConfig:
    return BacktestConfig(
        initial_capital=Decimal("10000"),
        risk_percent=Decimal("0.5"),
        entry_fee_rate=Decimal("0.0004"),
        exit_fee_rate=Decimal("0.0004"),
        spread_bps=Decimal("5"),
        slippage_bps=Decimal("5"),
        leverage=Decimal("1"),
        symbol=symbol,
        interval=interval,
        paper_only=True,
        allow_short=False,
        strategy_version=BASELINE_A_STRATEGY_VERSION,
    )

def _closes(history: Sequence[Candle]) -> list[Decimal]:
    return [candle.close for candle in history]


def _true_ranges(history: Sequence[Candle]) -> list[Decimal]:
    ranges: list[Decimal] = []
    previous_close: Decimal | None = None
    for candle in history:
        high_low = candle.high - candle.low
        if previous_close is None:
            ranges.append(high_low)
        else:
            ranges.append(max(high_low, abs(candle.high - previous_close), abs(candle.low - previous_close)))
        previous_close = candle.close
    return ranges


def _ema_series(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    if period <= 0:
        raise ValidationSelectionError("period must be greater than zero.")
    series: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return series
    alpha = Decimal("2") / Decimal(period + 1)
    complement = Decimal("1") - alpha
    seed = sum(values[:period], Decimal("0")) / Decimal(period)
    series[period - 1] = seed
    previous = seed
    for idx in range(period, len(values)):
        previous = (values[idx] * alpha) + (previous * complement)
        series[idx] = previous
    return series


def _atr_series(history: Sequence[Candle], period: int) -> list[Decimal | None]:
    series: list[Decimal | None] = [None] * len(history)
    if period <= 0:
        raise ValidationSelectionError("period must be greater than zero.")
    if len(history) < period:
        return series
    true_ranges = _true_ranges(history)
    seed = sum(true_ranges[:period], Decimal("0")) / Decimal(period)
    series[period - 1] = seed
    previous = seed
    divisor = Decimal(period)
    multiplier = Decimal(period - 1)
    for idx in range(period, len(history)):
        previous = ((previous * multiplier) + true_ranges[idx]) / divisor
        series[idx] = previous
    return series


def _last_pullback_touch(history: Sequence[Candle], ema20: Sequence[Decimal | None], current_index: int) -> bool:
    start = max(0, current_index - (BASELINE_A_PULLBACK_LOOKBACK - 1))
    for idx in range(start, current_index + 1):
        ema_value = ema20[idx]
        if ema_value is not None and history[idx].low <= ema_value:
            return True
    return False


def baseline_a_strategy(history: Sequence[Candle], snapshot) -> Signal | None:
    candles = tuple(history)
    if len(candles) < BASELINE_A_MIN_HISTORY:
        return None

    closes = _closes(candles)
    ema20 = _ema_series(closes, BASELINE_A_FAST_EMA)
    ema50 = _ema_series(closes, BASELINE_A_MID_EMA)
    ema200 = _ema_series(closes, BASELINE_A_SLOW_EMA)
    atr14 = _atr_series(candles, BASELINE_A_ATR_PERIOD)

    index = len(candles) - 1
    previous_index = index - 1

    current_ema20 = ema20[index]
    current_ema50 = ema50[index]
    previous_ema50 = ema50[previous_index]
    current_ema200 = ema200[index]
    current_atr = atr14[index]
    if any(value is None for value in (current_ema20, current_ema50, previous_ema50, current_ema200, current_atr)):
        return None
    if index <= 0:
        return None
    current_candle = candles[index]
    previous_candle = candles[previous_index]

    if current_ema50 <= current_ema200:
        return None
    if current_candle.close <= current_ema200:
        return None
    if current_ema50 <= previous_ema50:
        return None
    if current_candle.close <= current_ema20:
        return None
    if current_candle.close <= previous_candle.high:
        return None
    if not _last_pullback_touch(candles, ema20, index):
        return None
    if current_atr <= 0:
        return None

    entry = current_candle.close
    stop_loss = entry - (BASELINE_A_STOP_ATR_MULTIPLIER * current_atr)
    take_profit = entry + ((entry - stop_loss) * BASELINE_A_REWARD_MULTIPLIER)
    if stop_loss >= entry or take_profit <= entry:
        return None

    regime = None
    if snapshot is not None:
        regime_value = getattr(snapshot, "regime", None)
        if isinstance(regime_value, str) and regime_value.strip():
            regime = regime_value.strip().upper()

    return Signal(
        symbol=current_candle.symbol,
        direction=Direction.COMPRA,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        rr=BASELINE_A_REWARD_MULTIPLIER,
        timestamp=current_candle.close_time,
        source=DataSource.PAPER,
        score=Decimal("1"),
        regime=regime,
        volume_status="NAO_FILTRADO",
        reason="baseline_a_ema_trend_pullback_v1",
        strategy_version=BASELINE_A_STRATEGY_VERSION,
    )


def baseline_a_strategy_factory(candidate: CandidateConfig) -> Callable[[Sequence[Candle], Any], Signal | None]:
    if candidate != BASELINE_A_CANDIDATE:
        raise ValidationSelectionError("baseline A candidate diverges from the frozen contract.")
    return baseline_a_strategy


def baseline_a_trusted_runner(*, symbol: str = BASELINE_A_SYMBOL, interval: str = BASELINE_A_INTERVAL) -> TrustedLeakFreeBacktestRunner:
    def _engine_factory() -> LeakFreeBacktestEngine:
        return LeakFreeBacktestEngine(baseline_a_backtest_config(symbol=symbol, interval=interval))

    return TrustedLeakFreeBacktestRunner(
        engine_factory=_engine_factory,
        strategy_factory=baseline_a_strategy_factory,
        symbol=symbol,
        interval=interval,
    )


def baseline_a_historical_experiment_plan(
    source: str | HistoricalDataset,
    *,
    symbol: str = BASELINE_A_SYMBOL,
    interval: str = BASELINE_A_INTERVAL,
    seed: int | None = None,
) -> Any:
    runner = baseline_a_trusted_runner(symbol=symbol, interval=interval)
    contract = runner.execution_contract()
    config = baseline_a_backtest_config(symbol=symbol, interval=interval)
    return build_historical_experiment_plan(
        source,
        mode="walk_forward",
        strategy_callable=baseline_a_strategy_factory,
        strategy_version=contract["strategy_version"],
        execution_contract=contract,
        costs={
            "entry_fee_rate": config.entry_fee_rate,
            "exit_fee_rate": config.exit_fee_rate,
            "spread_bps": config.spread_bps,
            "slippage_bps": config.slippage_bps,
            "leverage": config.leverage,
            "intrabar_policy": config.intrabar_policy,
            "gap_policy": config.gap_policy,
        },
        candidate_grid=(BASELINE_A_CANDIDATE,),
        selection_criteria=SelectionCriteria(
            min_total_trades=1,
            min_net_return=Decimal("0"),
            max_drawdown_percent=Decimal("25"),
            min_expectancy=Decimal("0"),
            require_defined_profit_factor=False,
            min_profit_factor=Decimal("0"),
        ),
        split_config=ValidationSplitConfig(
            mode="rolling",
            train_bars=160,
            validation_bars=80,
            test_bars=80,
            warmup_bars=BASELINE_A_SLOW_EMA + 1,
            purge_bars=5,
            embargo_bars=5,
            step_bars=80,
            min_total_trades=1,
            min_net_return=Decimal("0"),
            max_drawdown_percent=Decimal("25"),
            min_expectancy=Decimal("0"),
            require_defined_profit_factor=False,
            min_profit_factor=Decimal("0"),
        ),
        seed=seed,
        intrabar_policy=contract["intrabar_policy"],
        gap_policy=contract["gap_policy"],
    )
