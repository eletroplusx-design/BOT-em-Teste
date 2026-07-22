from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import json

import pytest

from domain import Candle, DataSource
from historical_multitimeframe_experiments import build_historical_multitimeframe_replay
from historical_multitimeframe_strategy import (
    HistoricalMultiTimeframeFirstStrategyDecision,
    HistoricalMultiTimeframeFirstStrategyFactory,
    HistoricalMultiTimeframeFirstStrategyHypothesisConfig,
    HistoricalMultiTimeframeFirstStrategyIntegrityError,
    HistoricalMultiTimeframeFirstStrategyValidationError,
    build_historical_multitimeframe_first_strategy_config,
    build_historical_multitimeframe_first_strategy_factory,
    evaluate_historical_multitimeframe_first_strategy,
    run_historical_multitimeframe_first_strategy,
)
from market_data import (
    HistoricalDataset,
    HistoricalDatasetRequest,
    HistoricalProviderQualification,
    build_historical_manifest,
    build_historical_multitimeframe_bundle,
    historical_content_hash,
)
from market_data.historical_store import save_historical_dataset


ONE_MS = timedelta(milliseconds=1)
FIFTEEN_MINUTES = timedelta(minutes=15)
ONE_HOUR = timedelta(hours=1)
FOUR_HOURS = timedelta(hours=4)
BASE_15M_START = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
KUCOIN_ENDPOINT = "https://api.kucoin.com/api/v1/market/candles"


def _qualification(interval: str, *, symbol: str = "BTCUSDT") -> HistoricalProviderQualification:
    return HistoricalProviderQualification.kucoin_public_spot(symbol=symbol, interval=interval)


def _interval_delta(interval: str) -> timedelta:
    return {
        "15m": FIFTEEN_MINUTES,
        "1h": ONE_HOUR,
        "4h": FOUR_HOURS,
    }[interval]


def _trend_dataset(
    tmp_path: Path,
    *,
    interval: str,
    start: datetime,
    count: int,
    direction: str = "up",
    symbol: str = "BTCUSDT",
    trigger_spike: bool = False,
) -> tuple[Path, HistoricalDataset]:
    qualification = _qualification(interval, symbol=symbol)
    step = _interval_delta(interval)
    candles: list[Candle] = []
    for idx in range(count):
        if direction == "down":
            open_value = 500 - (idx * 2)
            close_value = 499 - (idx * 2)
        else:
            open_value = 100 + (idx * 2)
            close_value = 101 + (idx * 2)
        high_value = max(open_value, close_value) + 1
        low_value = min(open_value, close_value) - 1
        if idx == count - 1:
            if trigger_spike:
                close_value = 1000
                high_value = 1100
                low_value = min(low_value, close_value - 2)
            else:
                close_value = open_value
                high_value = max(open_value, close_value) + 1
                low_value = min(low_value, close_value - 1)
        candles.append(
            Candle.from_dict(
                {
                    "open_time": start + (idx * step),
                    "close_time": start + (idx * step) + step - ONE_MS,
                    "open": str(open_value),
                    "high": str(high_value),
                    "low": str(low_value),
                    "close": str(close_value),
                    "volume": str(1000 + idx),
                    "symbol": symbol,
                    "interval": interval,
                    "source": DataSource.KUCOIN,
                }
            )
        )
    request = HistoricalDatasetRequest(
        provider=qualification.provider_id,
        provider_qualification=qualification,
        endpoint=KUCOIN_ENDPOINT,
        symbol=symbol,
        interval=interval,
        requested_start_utc=candles[0].open_time,
        requested_end_utc=candles[-1].close_time,
        page_size=1500,
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
    dataset = HistoricalDataset(manifest=manifest, candles=tuple(candles))
    start_key = start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = tmp_path / f"kucoin-{interval}-{direction}-{start_key}-{count}.json"
    save_historical_dataset(path, dataset)
    return path, dataset


def _bundle(
    tmp_path: Path,
    *,
    base_count: int = 30,
    one_hour_count: int = 30,
    four_hour_count: int = 30,
    one_hour_direction: str = "up",
    four_hour_direction: str = "up",
    breakout: bool = True,
) -> tuple[HistoricalDataset, HistoricalDataset, HistoricalDataset, object]:
    _, base = _trend_dataset(
        tmp_path,
        interval="15m",
        start=BASE_15M_START,
        count=base_count,
        direction="up",
        trigger_spike=breakout,
    )
    _, one_hour = _trend_dataset(
        tmp_path,
        interval="1h",
        start=BASE_15M_START - timedelta(hours=24),
        count=one_hour_count,
        direction=one_hour_direction,
    )
    _, four_hour = _trend_dataset(
        tmp_path,
        interval="4h",
        start=BASE_15M_START - timedelta(days=4),
        count=four_hour_count,
        direction=four_hour_direction,
    )
    bundle = build_historical_multitimeframe_bundle(base, one_hour, four_hour)
    return base, one_hour, four_hour, build_historical_multitimeframe_replay(bundle)


def _report(tmp_path: Path, *, config: HistoricalMultiTimeframeFirstStrategyHypothesisConfig | None = None):
    _, _, _, replay = _bundle(tmp_path)
    return run_historical_multitimeframe_first_strategy(replay, config=config)


def test_strategy_config_hash_is_canonical_and_round_trips():
    config = build_historical_multitimeframe_first_strategy_config()
    round_tripped = type(config).from_dict(config.as_dict())

    assert config == round_tripped
    assert config.config_hash == round_tripped.config_hash
    assert config.as_dict() == round_tripped.as_dict()
    assert config.historical_research_only is True
    assert config.operational_evidence is False
    assert config.paper_promotion_eligible is False


def test_strategy_factory_hash_is_deterministic_and_round_trips():
    config = build_historical_multitimeframe_first_strategy_config()
    factory = build_historical_multitimeframe_first_strategy_factory(config)
    round_tripped = type(factory).from_dict(factory.as_dict())

    assert factory == round_tripped
    assert factory.factory_hash == round_tripped.factory_hash
    assert factory.as_dict() == round_tripped.as_dict()


def test_signal_valid_when_all_conditions_are_true(tmp_path):
    _, _, _, replay = _bundle(tmp_path, breakout=True, one_hour_direction="up", four_hour_direction="up")
    config = build_historical_multitimeframe_first_strategy_config()
    report = run_historical_multitimeframe_first_strategy(replay, config=config)

    decision = report.decisions[-1]

    assert decision.signal_generated is True
    assert decision.signal is not None
    assert decision.signal.direction == "COMPRA"
    assert decision.signal.trigger_close_time_utc == decision.decision_time_utc
    assert decision.signal.trigger_close > decision.signal.breakout_level
    assert all(rule.passed for rule in decision.rule_results)
    assert report.signal_count > 0
    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False


def test_blocked_by_four_hour_trend(tmp_path):
    _, _, _, replay = _bundle(tmp_path, breakout=True, one_hour_direction="up", four_hour_direction="down")
    config = build_historical_multitimeframe_first_strategy_config()
    report = run_historical_multitimeframe_first_strategy(replay, config=config)

    decision = report.decisions[-1]
    trend_rule = next(rule for rule in decision.rule_results if rule.name == "trend_4h_above_sma")

    assert decision.signal is None
    assert trend_rule.passed is False
    assert "4h" in trend_rule.reason


def test_blocked_by_one_hour_confirmation(tmp_path):
    _, _, _, replay = _bundle(tmp_path, breakout=True, one_hour_direction="down", four_hour_direction="up")
    config = build_historical_multitimeframe_first_strategy_config()
    report = run_historical_multitimeframe_first_strategy(replay, config=config)

    decision = report.decisions[-1]
    confirmation_rule = next(rule for rule in decision.rule_results if rule.name == "confirmation_1h_above_sma")

    assert decision.signal is None
    assert confirmation_rule.passed is False
    assert "1h" in confirmation_rule.reason


def test_blocked_by_missing_15m_breakout(tmp_path):
    _, _, _, replay = _bundle(tmp_path, breakout=False, one_hour_direction="up", four_hour_direction="up")
    config = build_historical_multitimeframe_first_strategy_config()
    report = run_historical_multitimeframe_first_strategy(replay, config=config)

    decision = report.decisions[-1]
    breakout_rule = next(rule for rule in decision.rule_results if rule.name == "donchian_breakout_15m")

    assert decision.signal is None
    assert breakout_rule.passed is False
    assert "Donchian" in breakout_rule.reason or "donchian" in breakout_rule.reason.lower()
    assert breakout_rule.details["trigger_close"] <= breakout_rule.details["donchian_high"]
    assert breakout_rule.details["lookback"] == config.donchian_lookback


def test_warmup_insufficient_blocks_closed_history(tmp_path):
    _, _, _, replay = _bundle(tmp_path, base_count=10, one_hour_count=10, four_hour_count=10, breakout=True)
    config = build_historical_multitimeframe_first_strategy_config()
    report = run_historical_multitimeframe_first_strategy(replay, config=config)

    assert all(decision.signal is None for decision in report.decisions)
    assert any(
        not rule.passed and rule.name.startswith("warmup_")
        for decision in report.decisions
        for rule in decision.rule_results
    )


def test_future_candle_adulteration_fails_closed(tmp_path):
    report = _report(tmp_path)
    payload = report.as_dict()
    payload["context_series"]["contexts"][0]["supporting_windows"][0]["candles"][-1]["close_time"] = "2030-01-01T00:00:00Z"

    with pytest.raises((HistoricalMultiTimeframeFirstStrategyIntegrityError, HistoricalMultiTimeframeFirstStrategyValidationError)):
        type(report).from_dict(payload)


def test_trigger_candle_is_not_part_of_donchian_maximum(tmp_path):
    _, _, _, replay = _bundle(tmp_path, breakout=True, one_hour_direction="up", four_hour_direction="up")
    config = build_historical_multitimeframe_first_strategy_config(donchian_lookback=20)
    report = run_historical_multitimeframe_first_strategy(replay, config=config)

    decision = report.decisions[-1]
    breakout_rule = next(rule for rule in decision.rule_results if rule.name == "donchian_breakout_15m")
    trigger_close = decision.signal.trigger_close if decision.signal is not None else Decimal("0")

    assert decision.signal is not None
    assert breakout_rule.details["donchian_high"] < trigger_close
    assert breakout_rule.details["trigger_close"] == trigger_close


def test_determinism_hash_and_configuration_tampering(tmp_path):
    _, _, _, replay = _bundle(tmp_path, breakout=True, one_hour_direction="up", four_hour_direction="up")
    config = build_historical_multitimeframe_first_strategy_config()

    report_a = run_historical_multitimeframe_first_strategy(replay, config=config)
    report_b = run_historical_multitimeframe_first_strategy(replay, config=config)
    mutated_config = build_historical_multitimeframe_first_strategy_config(
        donchian_lookback=config.donchian_lookback - 1,
        one_hour_sma_period=config.one_hour_sma_period,
        four_hour_sma_period=config.four_hour_sma_period,
    )
    report_c = run_historical_multitimeframe_first_strategy(replay, config=mutated_config)

    assert report_a == report_b
    assert report_a.report_hash == report_b.report_hash
    assert report_a.report_hash != report_c.report_hash

    tampered_payload = report_a.as_dict()
    tampered_payload["factory"]["config"]["donchian_lookback"] = config.donchian_lookback - 1
    with pytest.raises(HistoricalMultiTimeframeFirstStrategyValidationError, match="config hash mismatch|factory hash mismatch|strategy decisions diverge"):
        type(report_a).from_dict(tampered_payload)


def test_research_only_invariants_and_replay_compatibility(tmp_path):
    _, _, _, replay = _bundle(tmp_path, breakout=True, one_hour_direction="up", four_hour_direction="up")
    config = build_historical_multitimeframe_first_strategy_config()
    factory = build_historical_multitimeframe_first_strategy_factory(config)
    report = run_historical_multitimeframe_first_strategy(replay, factory=factory)

    assert report.replay.bundle.bundle_hash == replay.bundle.bundle_hash
    assert report.context_series.bundle.bundle_hash == replay.bundle.bundle_hash
    assert report.context_series.policy.context_policy_hash == config.context_policy_hash
    assert report.factory.config == config
    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert all(decision.historical_research_only for decision in report.decisions)
    assert all(decision.operational_evidence is False for decision in report.decisions)
    assert all(decision.paper_promotion_eligible is False for decision in report.decisions)

