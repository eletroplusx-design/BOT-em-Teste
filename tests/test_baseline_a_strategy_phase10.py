from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backtesting import BacktestConfig, LeakFreeBacktestEngine
from domain import Candle, DataSource, MarketSnapshot, Direction
from historical_experiments import HistoricalExperimentValidationError, build_historical_experiment_plan
from historical_replay import HistoricalDataset
from market_data import HistoricalDatasetRequest, historical_content_hash
from market_data.historical_manifest import build_historical_manifest
from market_data.historical_store import save_historical_dataset
from strategies.baseline_a import (
    BASELINE_A_CANDIDATE,
    BASELINE_A_INTERVAL,
    BASELINE_A_STRATEGY_VERSION,
    BASELINE_A_SYMBOL,
    baseline_a_backtest_config,
    baseline_a_candidate_config,
    baseline_a_historical_experiment_plan,
    baseline_a_strategy,
    baseline_a_strategy_factory,
    baseline_a_trusted_runner,
)
from validation import CandidateConfig


ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)


def _candle(open_time: datetime, *, base: int, symbol: str = BASELINE_A_SYMBOL, interval: str = BASELINE_A_INTERVAL) -> Candle:
    return Candle.from_dict(
        {
            "open_time": open_time,
            "close_time": open_time + ONE_HOUR - ONE_MS,
            "open": str(base),
            "high": str(base + 6),
            "low": str(base - 6),
            "close": str(base + 2),
            "volume": str(1000 + base),
            "symbol": symbol,
            "interval": interval,
            "source": DataSource.BINANCE,
        }
    )


def _downward_candle(open_time: datetime, *, base: int, symbol: str = BASELINE_A_SYMBOL, interval: str = BASELINE_A_INTERVAL) -> Candle:
    return Candle.from_dict(
        {
            "open_time": open_time,
            "close_time": open_time + ONE_HOUR - ONE_MS,
            "open": str(base),
            "high": str(base + 3),
            "low": str(base - 9),
            "close": str(base - 4),
            "volume": str(1000 + base),
            "symbol": symbol,
            "interval": interval,
            "source": DataSource.BINANCE,
        }
    )


def _flat_candle(open_time: datetime, *, base: int, symbol: str = BASELINE_A_SYMBOL, interval: str = BASELINE_A_INTERVAL) -> Candle:
    return Candle.from_dict(
        {
            "open_time": open_time,
            "close_time": open_time + ONE_HOUR - ONE_MS,
            "open": str(base),
            "high": str(base + 1),
            "low": str(base - 1),
            "close": str(base),
            "volume": str(1000 + base),
            "symbol": symbol,
            "interval": interval,
            "source": DataSource.BINANCE,
        }
    )


def _bullish_pullback_history(*, count: int = 202) -> tuple[Candle, ...]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = [_flat_candle(start + idx * ONE_HOUR, base=100 + idx) for idx in range(count)]
    for idx in range(20, count):
        candle = candles[idx]
        base = 100 + idx * 2
        candles[idx] = Candle.from_dict(
            {
                "open_time": candle.open_time,
                "close_time": candle.close_time,
                "open": str(base - 2),
                "high": str(base + 6),
                "low": str(base - 7),
                "close": str(base + 2),
                "volume": str(2000 + idx),
                "symbol": candle.symbol,
                "interval": candle.interval,
                "source": candle.source,
            }
        )

    candles[-4] = Candle.from_dict(
        {
            "open_time": candles[-4].open_time,
            "close_time": candles[-4].close_time,
            "open": "500",
            "high": "512",
            "low": "494",
            "close": "508",
            "volume": "3000",
            "symbol": BASELINE_A_SYMBOL,
            "interval": BASELINE_A_INTERVAL,
            "source": DataSource.BINANCE,
        }
    )
    candles[-3] = Candle.from_dict(
        {
            "open_time": candles[-3].open_time,
            "close_time": candles[-3].close_time,
            "open": "508",
            "high": "516",
            "low": "450",
            "close": "514",
            "volume": "3100",
            "symbol": BASELINE_A_SYMBOL,
            "interval": BASELINE_A_INTERVAL,
            "source": DataSource.BINANCE,
        }
    )
    candles[-2] = Candle.from_dict(
        {
            "open_time": candles[-2].open_time,
            "close_time": candles[-2].close_time,
            "open": "514",
            "high": "526",
            "low": "499",
            "close": "522",
            "volume": "3200",
            "symbol": BASELINE_A_SYMBOL,
            "interval": BASELINE_A_INTERVAL,
            "source": DataSource.BINANCE,
        }
    )
    candles[-1] = Candle.from_dict(
        {
            "open_time": candles[-1].open_time,
            "close_time": candles[-1].close_time,
            "open": "530",
            "high": "540",
            "low": "528",
            "close": "538",
            "volume": "3300",
            "symbol": BASELINE_A_SYMBOL,
            "interval": BASELINE_A_INTERVAL,
            "source": DataSource.BINANCE,
        }
    )
    return tuple(candles)


def _snapshot(candles: tuple[Candle, ...], *, regime: str | None = None) -> MarketSnapshot:
    last = candles[-1]
    return MarketSnapshot(
        symbol=last.symbol,
        timestamp=last.close_time,
        current_price=last.close,
        source=DataSource.BINANCE,
        regime=regime,
    )


def test_strategy_requires_enough_history():
    candles = _bullish_pullback_history(count=200)
    assert baseline_a_strategy(candles, _snapshot(candles)) is None


def test_strategy_rejects_when_ema50_is_not_above_ema200():
    candles = list(_bullish_pullback_history())
    mutated = list(candles)
    for idx in range(180, len(mutated)):
        mutated[idx] = _downward_candle(mutated[idx].open_time, base=80 + idx)
    assert baseline_a_strategy(tuple(mutated), _snapshot(tuple(mutated))) is None


def test_strategy_rejects_when_close_below_ema200():
    candles = list(_bullish_pullback_history())
    mutated = list(candles)
    last = mutated[-1]
    mutated[-1] = Candle.from_dict(
        {
            "open_time": last.open_time,
            "close_time": last.close_time,
            "open": "350",
            "high": "352",
            "low": "330",
            "close": "340",
            "volume": last.volume,
            "symbol": last.symbol,
            "interval": last.interval,
            "source": last.source,
        }
    )
    assert baseline_a_strategy(tuple(mutated), _snapshot(tuple(mutated))) is None


def test_strategy_rejects_without_pullback_to_ema20():
    candles = list(_bullish_pullback_history())
    mutated = list(candles)
    for idx in range(len(mutated) - 3, len(mutated)):
        candle = mutated[idx]
        mutated[idx] = Candle.from_dict(
            {
                "open_time": candle.open_time,
                "close_time": candle.close_time,
                "open": candle.close,
                "high": str(candle.close + Decimal("1")),
                "low": str(candle.close - Decimal("1")),
                "close": candle.close,
                "volume": candle.volume,
                "symbol": candle.symbol,
                "interval": candle.interval,
                "source": candle.source,
            }
        )
    assert baseline_a_strategy(tuple(mutated), _snapshot(tuple(mutated))) is None


def test_strategy_rejects_when_close_is_not_above_previous_high():
    candles = list(_bullish_pullback_history())
    mutated = list(candles)
    previous = mutated[-2]
    current = mutated[-1]
    mutated[-1] = Candle.from_dict(
        {
            "open_time": current.open_time,
            "close_time": current.close_time,
            "open": str(previous.high - Decimal("1")),
            "high": str(previous.high),
            "low": str(previous.high - Decimal("4")),
            "close": str(previous.high - Decimal("1")),
            "volume": current.volume,
            "symbol": current.symbol,
            "interval": current.interval,
            "source": current.source,
        }
    )
    assert baseline_a_strategy(tuple(mutated), _snapshot(tuple(mutated))) is None


def test_strategy_emits_buy_signal_with_expected_risk_and_targets():
    candles = _bullish_pullback_history()
    signal = baseline_a_strategy(candles, _snapshot(candles, regime="bull"))
    assert signal is not None
    assert signal.direction is Direction.COMPRA
    assert signal.source is DataSource.PAPER
    assert signal.strategy_version == BASELINE_A_STRATEGY_VERSION
    assert signal.entry == candles[-1].close
    assert signal.stop_loss < signal.entry < signal.take_profit
    assert signal.take_profit - signal.entry == (signal.entry - signal.stop_loss) * Decimal("2")
    assert signal.rr == Decimal("2")
    assert signal.regime == "BULL"


def test_strategy_rejects_zero_or_invalid_atr():
    candles = list(_bullish_pullback_history())
    mutated = list(candles)
    for idx in range(len(mutated)):
        candle = mutated[idx]
        mutated[idx] = Candle.from_dict(
            {
                "open_time": candle.open_time,
                "close_time": candle.close_time,
                "open": "100",
                "high": "100",
                "low": "100",
                "close": "100",
                "volume": candle.volume,
                "symbol": candle.symbol,
                "interval": candle.interval,
                "source": candle.source,
            }
        )
    assert baseline_a_strategy(tuple(mutated), _snapshot(tuple(mutated))) is None


def test_strategy_never_emits_sell():
    candles = _bullish_pullback_history()
    signal = baseline_a_strategy(candles, _snapshot(candles))
    assert signal is None or signal.direction is not Direction.VENDA


def test_strategy_factory_is_stable_and_fingerprintable():
    candidate = baseline_a_candidate_config()
    factory = baseline_a_strategy_factory(candidate)
    assert factory is baseline_a_strategy
    assert baseline_a_strategy.__closure__ is None
    assert baseline_a_strategy_factory.__closure__ is None
    assert baseline_a_candidate_config() == BASELINE_A_CANDIDATE


def test_engine_executes_signal_on_next_candle():
    candles = list(_bullish_pullback_history())
    engine = LeakFreeBacktestEngine(
        BacktestConfig(
            initial_capital=Decimal("10000"),
            risk_percent=Decimal("0.5"),
            entry_fee_rate=Decimal("0"),
            exit_fee_rate=Decimal("0"),
            spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            leverage=Decimal("1"),
            symbol=BASELINE_A_SYMBOL,
            interval=BASELINE_A_INTERVAL,
            paper_only=True,
            allow_short=False,
            strategy_version=BASELINE_A_STRATEGY_VERSION,
        )
    )
    result = engine.run(candles, baseline_a_strategy)
    assert result.trades
    trade = result.trades[0]
    assert trade.entry_index == len(candles) - 1
    assert trade.entry_fill.filled_at == candles[-1].open_time


def test_backtest_config_helper_matches_required_contract():
    config = baseline_a_backtest_config()
    assert config.symbol == BASELINE_A_SYMBOL
    assert config.interval == BASELINE_A_INTERVAL
    assert config.paper_only is True
    assert config.allow_short is False
    assert config.risk_percent == Decimal("0.5")
    assert config.entry_fee_rate == Decimal("0.0004")
    assert config.exit_fee_rate == Decimal("0.0004")
    assert config.spread_bps == Decimal("5")
    assert config.slippage_bps == Decimal("5")
    assert config.strategy_version == BASELINE_A_STRATEGY_VERSION


def test_trusted_runner_execution_contract_matches_helper_config():
    runner = baseline_a_trusted_runner()
    contract = runner.execution_contract()
    config = baseline_a_backtest_config()
    assert contract["symbol"] == BASELINE_A_SYMBOL
    assert contract["interval"] == BASELINE_A_INTERVAL
    assert contract["paper_only"] is True
    assert contract["entry_fee_rate"] == str(config.entry_fee_rate)
    assert contract["exit_fee_rate"] == str(config.exit_fee_rate)
    assert contract["spread_bps"] == str(config.spread_bps)
    assert contract["slippage_bps"] == str(config.slippage_bps)
    assert contract["strategy_version"] == BASELINE_A_STRATEGY_VERSION


def test_historical_experiment_plan_is_compatible_and_not_promotional(tmp_path):
    candles = _bullish_pullback_history(count=260)
    request = HistoricalDatasetRequest(
        provider="binance.public.klines",
        endpoint="https://api.binance.com/api/v3/klines",
        symbol=BASELINE_A_SYMBOL,
        interval=BASELINE_A_INTERVAL,
        requested_start_utc=candles[0].open_time,
        requested_end_utc=candles[-1].close_time,
        page_size=1000,
        closed_candles_only=True,
    )
    manifest = build_historical_manifest(
        request=request,
        effective_start_utc=candles[0].open_time,
        effective_end_utc=candles[-1].close_time,
        created_at_utc=candles[-1].close_time + timedelta(days=1),
        candle_count=len(candles),
        page_count=1,
        gap_count=0,
        duplicate_count=0,
        content_hash=historical_content_hash(candles),
    )
    dataset = HistoricalDataset(manifest=manifest, candles=candles)
    path = tmp_path / "baseline-a-historical.json"
    save_historical_dataset(path, dataset)

    plan = baseline_a_historical_experiment_plan(path)
    assert plan.mode == "walk_forward"
    assert plan.classification == "historical_research_only"
    assert plan.operational_evidence is False
    assert plan.paper_promotion_eligible is False
    assert plan.strategy_version == BASELINE_A_STRATEGY_VERSION
    assert plan.execution_contract["paper_only"] is True
    assert plan.candidate_grid == (BASELINE_A_CANDIDATE,)


def test_strategy_does_not_require_operational_artifacts_or_network():
    candles = _bullish_pullback_history()
    signal = baseline_a_strategy(candles, _snapshot(candles))
    assert signal is None or signal.source is DataSource.PAPER
