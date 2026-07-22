from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from domain import Candle, DataSource
from market_data import (
    HistoricalDataIntegrityError,
    HistoricalDataValidationError,
    HistoricalDataset,
    HistoricalDatasetRequest,
    HistoricalProviderQualification,
    build_historical_manifest,
    build_historical_multitimeframe_bundle,
    build_historical_multitimeframe_decision_context,
    build_historical_multitimeframe_decision_context_policy,
    build_historical_multitimeframe_decision_context_series,
    historical_content_hash,
    load_historical_dataset_file,
)
from market_data.historical_store import save_historical_dataset


ONE_MS = timedelta(milliseconds=1)
FIFTEEN_MINUTES = timedelta(minutes=15)
ONE_HOUR = timedelta(hours=1)
FOUR_HOURS = timedelta(hours=4)
BASE_15M_START = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
KUCOIN_ENDPOINT = "https://api.kucoin.com/api/v1/market/candles"
BINANCE_ENDPOINT = "https://api.binance.com/api/v3/klines"


def _qualification(provider: str, interval: str, *, symbol: str = "BTCUSDT") -> HistoricalProviderQualification:
    if provider == "kucoin":
        return HistoricalProviderQualification.kucoin_public_spot(symbol=symbol, interval=interval)
    if provider == "binance":
        return HistoricalProviderQualification.binance_public_spot(symbol=symbol, interval=interval)
    raise AssertionError(f"unsupported provider {provider!r}")


def _interval_delta(interval: str) -> timedelta:
    return {
        "15m": FIFTEEN_MINUTES,
        "1h": ONE_HOUR,
        "4h": FOUR_HOURS,
    }[interval]


def _dataset(
    tmp_path: Path,
    *,
    provider: str,
    interval: str,
    start: datetime,
    count: int,
    symbol: str = "BTCUSDT",
) -> tuple[Path, HistoricalDataset]:
    source = DataSource.KUCOIN if provider == "kucoin" else DataSource.BINANCE
    qualification = _qualification(provider, interval, symbol=symbol)
    step = _interval_delta(interval)
    candles = tuple(
        Candle.from_dict(
            {
                "open_time": start + idx * step,
                "close_time": start + idx * step + step - ONE_MS,
                "open": str(100 + idx),
                "high": str(106 + idx),
                "low": str(96 + idx),
                "close": str(102 + idx),
                "volume": str(1000 + idx),
                "symbol": symbol,
                "interval": interval,
                "source": source,
            }
        )
        for idx in range(count)
    )
    request = HistoricalDatasetRequest(
        provider=qualification.provider_id,
        provider_qualification=qualification,
        endpoint=KUCOIN_ENDPOINT if provider == "kucoin" else BINANCE_ENDPOINT,
        symbol=symbol,
        interval=interval,
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
    start_key = start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = tmp_path / f"{provider}-{interval}-{start_key}-{count}.json"
    save_historical_dataset(path, dataset)
    return path, dataset


def _kucoin_dataset(tmp_path: Path, *, interval: str, start: datetime, count: int, symbol: str = "BTCUSDT") -> tuple[Path, HistoricalDataset]:
    return _dataset(tmp_path, provider="kucoin", interval=interval, start=start, count=count, symbol=symbol)


def _binance_dataset(tmp_path: Path, *, interval: str, start: datetime, count: int, symbol: str = "BTCUSDT") -> tuple[Path, HistoricalDataset]:
    return _dataset(tmp_path, provider="binance", interval=interval, start=start, count=count, symbol=symbol)


def _mutated_dataset(dataset: HistoricalDataset, *, mutate_index: int, open_delta: int = 10, symbol: str | None = None) -> HistoricalDataset:
    candles = list(dataset.candles)
    original = candles[mutate_index]
    candles[mutate_index] = Candle.from_dict(
        {
            "open_time": original.open_time,
            "close_time": original.close_time,
            "open": str(int(original.open) + open_delta),
            "high": str(int(original.high) + open_delta),
            "low": str(int(original.low) + open_delta),
            "close": str(int(original.close) + open_delta),
            "volume": original.volume,
            "symbol": symbol or original.symbol,
            "interval": original.interval,
            "source": original.source,
        }
    )
    mutated_manifest = build_historical_manifest(
        request=HistoricalDatasetRequest(
            provider=dataset.manifest.provider,
            provider_qualification=dataset.manifest.provider_qualification,
            endpoint=dataset.manifest.endpoint,
            symbol=symbol or dataset.manifest.symbol,
            interval=dataset.manifest.interval,
            requested_start_utc=dataset.manifest.requested_start_utc,
            requested_end_utc=dataset.manifest.requested_end_utc,
            page_size=dataset.manifest.page_size,
            closed_candles_only=True,
        ),
        effective_start_utc=dataset.manifest.effective_start_utc,
        effective_end_utc=dataset.manifest.effective_end_utc,
        created_at_utc=dataset.manifest.created_at_utc,
        candle_count=len(candles),
        page_count=dataset.manifest.page_count,
        gap_count=dataset.manifest.gap_count,
        duplicate_count=dataset.manifest.duplicate_count,
        content_hash=historical_content_hash(tuple(candles)),
    )
    return HistoricalDataset(manifest=mutated_manifest, candles=tuple(candles))


def _window_manifest_for_provider(dataset: HistoricalDataset, provider: str, *, tmp_path: Path, count: int | None = None) -> HistoricalDataset:
    count = count or len(dataset.candles)
    _, resolved = _dataset(
        tmp_path,
        provider=provider,
        interval=dataset.manifest.interval,
        start=dataset.manifest.requested_start_utc,
        count=count,
        symbol=dataset.manifest.symbol,
    )
    return resolved


def test_context_policy_hash_is_canonical_and_round_trips():
    policy = build_historical_multitimeframe_decision_context_policy(
        minimum_base_candles=2,
        minimum_one_hour_candles=3,
        minimum_four_hour_candles=4,
    )

    round_tripped = type(policy).from_dict(policy.as_dict())

    assert policy == round_tripped
    assert policy.context_policy_hash == round_tripped.context_policy_hash
    assert policy.as_dict() == round_tripped.as_dict()


@pytest.mark.parametrize(
    "minimum_base_candles",
    [True, 0, -1],
)
def test_context_policy_rejects_invalid_minimums(minimum_base_candles):
    with pytest.raises(HistoricalDataValidationError, match="minimum_base_candles"):
        build_historical_multitimeframe_decision_context_policy(minimum_base_candles=minimum_base_candles)


def test_context_series_is_closed_history_only_and_round_trips(tmp_path):
    _, base = _kucoin_dataset(tmp_path, interval="15m", start=BASE_15M_START, count=8)
    _, one_hour = _kucoin_dataset(tmp_path, interval="1h", start=BASE_15M_START - ONE_HOUR, count=6)
    _, four_hour = _kucoin_dataset(tmp_path, interval="4h", start=BASE_15M_START - FOUR_HOURS, count=4)
    bundle = build_historical_multitimeframe_bundle(base, one_hour, four_hour)
    policy = build_historical_multitimeframe_decision_context_policy()

    series = build_historical_multitimeframe_decision_context_series(bundle, policy=policy)
    round_tripped = type(series).from_dict(series.as_dict(), bundle)

    assert series == round_tripped
    assert series.series_hash == round_tripped.series_hash
    assert series.as_dict() == round_tripped.as_dict()
    assert len(series.contexts) == len(base.candles)

    first = series.contexts[0]
    later = series.contexts[4]

    assert first.base_window.candles[-1].close_time == first.snapshot.base_point.candle.close_time
    assert first.supporting_windows[0].candles[-1].close_time == first.snapshot.supporting_points[0].candle.close_time
    assert first.supporting_windows[1].candles[-1].close_time == first.snapshot.supporting_points[1].candle.close_time
    assert all(candle.close_time <= first.snapshot.decision_time_utc for candle in first.base_window.candles)
    assert all(candle.close_time <= first.snapshot.decision_time_utc for candle in first.supporting_windows[0].candles)
    assert all(candle.close_time <= first.snapshot.decision_time_utc for candle in first.supporting_windows[1].candles)
    assert later.base_window.candles[-1].close_time == later.snapshot.base_point.candle.close_time
    assert later.supporting_windows[0].candles[-1].close_time == later.snapshot.supporting_points[0].candle.close_time
    assert later.supporting_windows[1].candles[-1].close_time == later.snapshot.supporting_points[1].candle.close_time


def test_context_series_rejects_missing_warmup(tmp_path):
    _, base = _kucoin_dataset(tmp_path, interval="15m", start=BASE_15M_START, count=1)
    _, one_hour = _kucoin_dataset(tmp_path, interval="1h", start=BASE_15M_START - ONE_HOUR, count=1)
    _, four_hour = _kucoin_dataset(tmp_path, interval="4h", start=BASE_15M_START - FOUR_HOURS, count=1)
    bundle = build_historical_multitimeframe_bundle(base, one_hour, four_hour)
    policy = build_historical_multitimeframe_decision_context_policy(
        minimum_base_candles=2,
        minimum_one_hour_candles=2,
        minimum_four_hour_candles=2,
    )

    with pytest.raises(HistoricalDataValidationError, match="warm-up"):
        build_historical_multitimeframe_decision_context_series(bundle, policy=policy)


def test_context_series_rejects_tampered_provider_even_with_recomputed_hashes(tmp_path):
    _, base = _kucoin_dataset(tmp_path, interval="15m", start=BASE_15M_START, count=8)
    _, one_hour = _kucoin_dataset(tmp_path, interval="1h", start=BASE_15M_START - ONE_HOUR, count=6)
    _, four_hour = _kucoin_dataset(tmp_path, interval="4h", start=BASE_15M_START - FOUR_HOURS, count=4)
    bundle = build_historical_multitimeframe_bundle(base, one_hour, four_hour)
    policy = build_historical_multitimeframe_decision_context_policy()
    series = build_historical_multitimeframe_decision_context_series(bundle, policy=policy)
    payload = series.as_dict()

    tampered_context = dict(payload["contexts"][0])
    tampered_window = dict(tampered_context["supporting_windows"][0])
    binance_window_dataset = _binance_dataset(
        tmp_path,
        interval=tampered_window["interval"],
        start=one_hour.manifest.requested_start_utc,
        count=len(one_hour.candles),
        symbol=one_hour.manifest.symbol,
    )[1]
    tampered_window["dataset_manifest"] = binance_window_dataset.manifest.as_dict()
    tampered_window["candles"] = [candle.to_dict() for candle in binance_window_dataset.candles]
    tampered_context["supporting_windows"][0] = tampered_window
    payload["contexts"][0] = tampered_context
    payload.pop("series_hash", None)

    with pytest.raises(HistoricalDataValidationError, match="hash mismatch|diverges from trusted alignment"):
        type(series).from_dict(payload, bundle)


def test_context_snapshot_stays_closed_when_future_candles_change(tmp_path):
    _, base = _kucoin_dataset(tmp_path, interval="15m", start=BASE_15M_START, count=12)
    _, one_hour = _kucoin_dataset(tmp_path, interval="1h", start=BASE_15M_START - ONE_HOUR, count=8)
    _, four_hour = _kucoin_dataset(tmp_path, interval="4h", start=BASE_15M_START - FOUR_HOURS, count=4)
    bundle = build_historical_multitimeframe_bundle(base, one_hour, four_hour)
    policy = build_historical_multitimeframe_decision_context_policy()

    base_candle = base.candles[4]
    context = build_historical_multitimeframe_decision_context(bundle, base_candle=base_candle, policy=policy)

    mutated_one_hour = _mutated_dataset(one_hour, mutate_index=len(one_hour.candles) - 1, open_delta=50)
    mutated_bundle = build_historical_multitimeframe_bundle(base, mutated_one_hour, four_hour)
    mutated_context = build_historical_multitimeframe_decision_context(mutated_bundle, base_candle=base_candle, policy=policy)

    assert context.base_window.candles == mutated_context.base_window.candles
    assert tuple(window.candles for window in context.supporting_windows) == tuple(window.candles for window in mutated_context.supporting_windows)
    assert context.snapshot.decision_time_utc == mutated_context.snapshot.decision_time_utc
    assert context.base_window.candles[-1].close_time == base_candle.close_time
    assert context.supporting_windows[0].candles[-1].close_time <= context.snapshot.decision_time_utc
    assert context.supporting_windows[1].candles[-1].close_time <= context.snapshot.decision_time_utc
