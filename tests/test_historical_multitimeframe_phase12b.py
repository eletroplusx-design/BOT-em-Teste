from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import json

import pytest

from domain import Candle, DataSource
from market_data import (
    HistoricalDataIntegrityError,
    HistoricalDataValidationError,
    HistoricalDataset,
    HistoricalDatasetRequest,
    HistoricalProviderQualification,
    align_historical_multitimeframe_series,
    align_historical_multitimeframe_snapshot,
    build_historical_manifest,
    build_historical_multitimeframe_bundle,
    HistoricalMultiTimeframeBundle,
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


def test_multitimeframe_bundle_hash_is_canonical_and_round_trips(tmp_path):
    _, base = _kucoin_dataset(tmp_path, interval="15m", start=BASE_15M_START, count=20)
    _, one_hour = _kucoin_dataset(tmp_path, interval="1h", start=BASE_15M_START - ONE_HOUR, count=7)
    _, four_hour = _kucoin_dataset(tmp_path, interval="4h", start=BASE_15M_START - FOUR_HOURS, count=4)

    bundle = build_historical_multitimeframe_bundle(base, one_hour, four_hour)
    round_tripped = type(bundle).from_dict(bundle.as_dict())

    assert bundle == round_tripped
    assert bundle.bundle_hash == round_tripped.bundle_hash
    assert bundle.as_dict() == round_tripped.as_dict()
    assert bundle.base_dataset.manifest.interval == "15m"
    assert tuple(dataset.manifest.interval for dataset in bundle.supporting_datasets) == ("1h", "4h")


def test_multitimeframe_alignment_uses_last_closed_supporting_candles_without_lookahead(tmp_path):
    _, base = _kucoin_dataset(tmp_path, interval="15m", start=BASE_15M_START, count=20)
    _, one_hour = _kucoin_dataset(tmp_path, interval="1h", start=BASE_15M_START - ONE_HOUR, count=7)
    _, four_hour = _kucoin_dataset(tmp_path, interval="4h", start=BASE_15M_START - FOUR_HOURS, count=4)

    bundle = build_historical_multitimeframe_bundle(base, one_hour, four_hour)
    snapshots = align_historical_multitimeframe_series(bundle)

    first = snapshots[0]
    exact_1h_close = snapshots[3]
    exact_4h_close = snapshots[15]
    still_forming = snapshots[16]

    assert first.decision_time_utc == base.candles[0].close_time
    assert [point.interval for point in first.supporting_points] == ["1h", "4h"]
    assert first.supporting_points[0].candle.close_time == one_hour.candles[0].close_time
    assert first.supporting_points[1].candle.close_time == four_hour.candles[0].close_time

    assert exact_1h_close.base_point.candle.close_time == base.candles[3].close_time
    assert exact_1h_close.supporting_points[0].candle.close_time == one_hour.candles[1].close_time
    assert exact_1h_close.supporting_points[1].candle.close_time == four_hour.candles[0].close_time

    assert exact_4h_close.supporting_points[0].candle.close_time == one_hour.candles[4].close_time
    assert exact_4h_close.supporting_points[1].candle.close_time == four_hour.candles[1].close_time

    assert still_forming.supporting_points[0].candle.close_time == one_hour.candles[4].close_time
    assert still_forming.supporting_points[1].candle.close_time == four_hour.candles[1].close_time
    assert still_forming.supporting_points[0].candle.close_time <= still_forming.decision_time_utc
    assert still_forming.supporting_points[1].candle.close_time <= still_forming.decision_time_utc


def test_multitimeframe_alignment_rejects_missing_supporting_warmup(tmp_path):
    _, base = _kucoin_dataset(tmp_path, interval="15m", start=BASE_15M_START, count=2)
    _, one_hour = _kucoin_dataset(tmp_path, interval="1h", start=BASE_15M_START, count=2)
    _, four_hour = _kucoin_dataset(tmp_path, interval="4h", start=BASE_15M_START, count=2)

    bundle = build_historical_multitimeframe_bundle(base, one_hour, four_hour)

    with pytest.raises(HistoricalDataValidationError, match="not yet closed"):
        align_historical_multitimeframe_snapshot(bundle, base_candle=base.candles[0])


@pytest.mark.parametrize(
    ("base_provider", "base_interval", "one_hour_provider", "one_hour_interval", "four_hour_provider", "four_hour_interval", "expected_message"),
    [
        ("kucoin", "1h", "kucoin", "1h", "kucoin", "4h", "base_dataset must use 15m interval."),
        ("kucoin", "15m", "kucoin", "15m", "kucoin", "4h", "supporting_datasets must contain 1h and 4h intervals."),
        ("kucoin", "15m", "kucoin", "1h", "kucoin", "15m", "supporting_datasets must contain 1h and 4h intervals."),
        ("kucoin", "15m", "binance", "1h", "kucoin", "4h", "multi-timeframe datasets must share the same provider."),
    ],
)
def test_multitimeframe_bundle_rejects_divergent_provider_symbol_or_interval(
    tmp_path,
    base_provider,
    base_interval,
    one_hour_provider,
    one_hour_interval,
    four_hour_provider,
    four_hour_interval,
    expected_message,
):
    _, base = _dataset(tmp_path, provider=base_provider, interval=base_interval, start=BASE_15M_START, count=4)
    _, one_hour = _dataset(tmp_path, provider=one_hour_provider, interval=one_hour_interval, start=BASE_15M_START - ONE_HOUR, count=4)
    _, four_hour = _dataset(tmp_path, provider=four_hour_provider, interval=four_hour_interval, start=BASE_15M_START - FOUR_HOURS, count=4)

    with pytest.raises(HistoricalDataValidationError, match=expected_message):
        build_historical_multitimeframe_bundle(base, one_hour, four_hour)


def test_multitimeframe_bundle_rejects_valid_but_heterogeneous_provider_families(tmp_path):
    _, base = _kucoin_dataset(tmp_path, interval="15m", start=BASE_15M_START, count=8)
    _, one_hour = _kucoin_dataset(tmp_path, interval="1h", start=BASE_15M_START - ONE_HOUR, count=8)
    _, four_hour = _kucoin_dataset(tmp_path, interval="4h", start=BASE_15M_START - FOUR_HOURS, count=8)
    payload = build_historical_multitimeframe_bundle(base, one_hour, four_hour).as_dict()
    payload["supporting_datasets"][0]["dataset"]["manifest"]["provider"] = "binance"
    payload["supporting_datasets"][0]["dataset"]["manifest"]["provider_qualification"]["provider_id"] = "binance.public.klines"
    provider_qualification_payload = dict(payload["supporting_datasets"][0]["dataset"]["manifest"]["provider_qualification"])
    provider_qualification_payload.pop("qualification_hash", None)
    payload["supporting_datasets"][0]["dataset"]["manifest"]["provider_qualification"]["qualification_hash"] = sha256(
        json.dumps(
            provider_qualification_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(HistoricalDataValidationError, match="provider qualification mismatch|provider_id must match provider|same provider family provenance"):
        HistoricalMultiTimeframeBundle.from_dict(payload)


def test_multitimeframe_bundle_rejects_symbol_adulteration_even_with_recomputed_hashes(tmp_path):
    _, base = _kucoin_dataset(tmp_path, interval="15m", start=BASE_15M_START, count=8)
    _, one_hour = _kucoin_dataset(tmp_path, interval="1h", start=BASE_15M_START - ONE_HOUR, count=8)
    _, four_hour = _kucoin_dataset(tmp_path, interval="4h", start=BASE_15M_START - FOUR_HOURS, count=4)
    payload = build_historical_multitimeframe_bundle(base, one_hour, four_hour).as_dict()
    supporting_payload = payload["supporting_datasets"][0]["dataset"]
    supporting_payload["manifest"]["symbol"] = "ETHUSDT"
    supporting_payload["manifest"]["provider_qualification"]["symbol"] = "ETHUSDT"
    supporting_payload["manifest"]["provider_qualification"]["external_symbol"] = "ETH-USDT"
    for candle in supporting_payload["candles"]:
        candle["symbol"] = "ETHUSDT"
    provider_qualification_payload = dict(supporting_payload["manifest"]["provider_qualification"])
    provider_qualification_payload.pop("qualification_hash", None)
    supporting_payload["manifest"]["provider_qualification"]["qualification_hash"] = sha256(
        json.dumps(
            provider_qualification_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    supporting_payload["manifest"]["content_hash"] = historical_content_hash(
        [Candle.from_dict(item) for item in supporting_payload["candles"]]
    )
    supporting_payload["manifest"]["dataset_id"] = supporting_payload["manifest"]["content_hash"]
    manifest_payload = dict(supporting_payload["manifest"])
    manifest_payload.pop("manifest_hash", None)
    supporting_payload["manifest"]["manifest_hash"] = sha256(
        json.dumps(manifest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    supporting_payload["content_hash"] = historical_content_hash([Candle.from_dict(item) for item in supporting_payload["candles"]])
    supporting_payload["dataset_id"] = supporting_payload["content_hash"]

    with pytest.raises(HistoricalDataValidationError, match="kucoin public spot provider only supports BTCUSDT|provider qualification mismatch|same provider family provenance|symbol"):
        HistoricalMultiTimeframeBundle.from_dict(payload)


def test_multitimeframe_alignment_snapshot_is_stable_when_future_candles_change(tmp_path):
    _, base = _kucoin_dataset(tmp_path, interval="15m", start=BASE_15M_START, count=20)
    _, one_hour = _kucoin_dataset(tmp_path, interval="1h", start=BASE_15M_START - ONE_HOUR, count=8)
    _, four_hour = _kucoin_dataset(tmp_path, interval="4h", start=BASE_15M_START - FOUR_HOURS, count=4)
    bundle = build_historical_multitimeframe_bundle(base, one_hour, four_hour)

    historical_point = base.candles[4]
    snapshot = align_historical_multitimeframe_snapshot(bundle, base_candle=historical_point)

    mutated_one_hour = _mutated_dataset(one_hour, mutate_index=len(one_hour.candles) - 1, open_delta=50)
    mutated_bundle = build_historical_multitimeframe_bundle(base, mutated_one_hour, four_hour)
    mutated_snapshot = align_historical_multitimeframe_snapshot(mutated_bundle, base_candle=historical_point)

    assert snapshot.base_point == mutated_snapshot.base_point
    assert tuple(point.candle for point in snapshot.supporting_points) == tuple(point.candle for point in mutated_snapshot.supporting_points)
    assert snapshot.decision_time_utc == mutated_snapshot.decision_time_utc
    assert bundle.bundle_hash != mutated_bundle.bundle_hash


def test_multitimeframe_dataset_gap_duplicate_payload_and_bounds_fail_closed(tmp_path):
    path, dataset = _kucoin_dataset(tmp_path, interval="1h", start=BASE_15M_START - ONE_HOUR, count=4)
    payload = load_historical_dataset_file(path).as_dict()
    payload["candles"][1]["open_time"] = payload["candles"][0]["open_time"]
    payload["candles"][1]["close_time"] = payload["candles"][0]["close_time"]
    payload["manifest"]["content_hash"] = historical_content_hash([Candle.from_dict(item) for item in payload["candles"]])
    payload["manifest"]["dataset_id"] = payload["manifest"]["content_hash"]
    tampered = tmp_path / "kucoin-1h-duplicate.json"
    tampered.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    with pytest.raises((HistoricalDataValidationError, HistoricalDataIntegrityError)):
        load_historical_dataset_file(tampered)

