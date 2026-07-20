from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import pytest

from backtesting import BacktestConfig, LeakFreeBacktestEngine
from domain import Candle, DataSource, Direction, Signal
from domain.serialization import serialize_value
import market_data.historical as historical
from historical_experiments import load_historical_experiment_report, run_historical_backtest_experiment
from historical_replay import HistoricalReplayProvenance, HistoricalDataIntegrityError, replay_historical_backtest
from market_data import (
    HistoricalDataValidationError,
    HistoricalDataset,
    HistoricalDatasetRequest,
    HistoricalProviderQualification,
    historical_content_hash,
    load_historical_dataset_file,
    prepare_historical_dataset,
    status_historical_dataset,
    verify_historical_dataset_file,
)
from market_data.historical_manifest import build_historical_manifest
from market_data.historical_store import save_historical_dataset


ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)
BASE_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _kline_row(open_time: datetime, *, base: int = 100):
    return [
        int(open_time.timestamp() * 1000),
        str(base),
        str(base + 5),
        str(base - 2),
        str(base + 1),
        str(1000 + base),
        int((open_time + ONE_HOUR - ONE_MS).timestamp() * 1000),
        0,
        0,
        0,
        0,
        0,
    ]


def _candles(count: int = 12, *, symbol: str = "BTCUSDT", interval: str = "1h"):
    return tuple(
        Candle.from_dict(
            {
                "open_time": BASE_START + idx * ONE_HOUR,
                "close_time": BASE_START + idx * ONE_HOUR + ONE_HOUR - ONE_MS,
                "open": str(100 + idx),
                "high": str(106 + idx),
                "low": str(96 + idx),
                "close": str(102 + idx),
                "volume": str(1000 + idx),
                "symbol": symbol,
                "interval": interval,
                "source": DataSource.BINANCE,
            }
        )
        for idx in range(count)
    )


def _qualification() -> HistoricalProviderQualification:
    return HistoricalProviderQualification.binance_public_spot(symbol="BTCUSDT", interval="1h")


def _dataset(tmp_path: Path, *, count: int = 12) -> tuple[Path, HistoricalDataset]:
    candles = _candles(count=count)
    request = HistoricalDatasetRequest(
        provider="binance.public.klines",
        provider_qualification=_qualification(),
        endpoint="https://api.binance.com/api/v3/klines",
        symbol="BTCUSDT",
        interval="1h",
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
    path = tmp_path / "historical-dataset.json"
    save_historical_dataset(path, dataset)
    return path, dataset


def _signal_callback(history, snapshot):
    candle = history[-1]
    entry = Decimal(str(candle.close))
    return Signal(
        symbol=candle.symbol,
        direction=Direction.COMPRA,
        entry=entry,
        stop_loss=entry - Decimal("5"),
        take_profit=entry + Decimal("10"),
        rr=Decimal("2"),
        timestamp=candle.close_time,
        source=DataSource.PAPER,
        score=Decimal("1"),
        regime="BULL",
        volume_status="ALTO",
        reason="phase 11 replay",
        strategy_version="v4_walk_forward",
    )


def _canonical_hash(payload):
    return sha256(json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _recompute_dataset_payload_hashes(payload: dict) -> None:
    payload["manifest"]["provider_qualification"]["qualification_hash"] = _canonical_hash(
        {k: v for k, v in payload["manifest"]["provider_qualification"].items() if k != "qualification_hash"}
    )
    payload["manifest"]["content_hash"] = historical_content_hash(tuple(Candle.from_dict(item) for item in payload["candles"]))
    payload["manifest"]["dataset_id"] = payload["manifest"]["content_hash"]
    payload["manifest"]["manifest_hash"] = _canonical_hash({k: v for k, v in payload["manifest"].items() if k != "manifest_hash"})


def test_provider_qualification_hash_is_canonical_and_deterministic():
    first = _qualification()
    second = HistoricalProviderQualification.from_dict(first.as_dict())
    assert first == second
    assert first.qualification_hash == second.qualification_hash
    assert first.as_dict() == second.as_dict()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"provider_version": "v1", "market_type": "spot", "exchange": "binance", "symbol": "BTCUSDT", "interval": "1h", "time_semantics": "utc", "access_type": "public_no_auth", "data_contract_version": 1}, "provider qualification is incomplete."),
        ({"provider_id": True, "provider_version": "v1", "market_type": "spot", "exchange": "binance", "symbol": "BTCUSDT", "interval": "1h", "time_semantics": "utc", "access_type": "public_no_auth", "data_contract_version": 1}, "provider_id is required."),
        ({"provider_id": "binance.public.klines", "provider_version": "v1", "market_type": "invalid", "exchange": "binance", "symbol": "BTCUSDT", "interval": "1h", "time_semantics": "utc", "access_type": "public_no_auth", "data_contract_version": 1}, "market_type must be spot or futures."),
        ({"provider_id": "binance.public.klines", "provider_version": "v1", "market_type": "spot", "exchange": "binance", "symbol": "BTCUSDT", "interval": "1h", "time_semantics": "utc", "access_type": "public_no_auth", "data_contract_version": True}, "data_contract_version must be an integer."),
    ],
)
def test_provider_qualification_rejects_missing_and_invalid_fields(payload, message):
    with pytest.raises(HistoricalDataValidationError, match=message):
        HistoricalProviderQualification.from_dict(payload)


def test_provider_qualification_rejects_futures_in_spot_contract():
    futures = HistoricalProviderQualification(
        provider_id="binance.public.klines",
        provider_version="v1",
        market_type="futures",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1h",
        time_semantics="utc",
        access_type="public_no_auth",
        data_contract_version=1,
    )
    with pytest.raises(HistoricalDataValidationError, match="provider qualification mismatch"):
        HistoricalDatasetRequest(
            provider="binance.public.klines",
            provider_qualification=futures,
            endpoint="https://api.binance.com/api/v3/klines",
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=BASE_START + ONE_HOUR - ONE_MS,
            page_size=1000,
            closed_candles_only=True,
        )


def test_dataset_round_trip_save_load_verify_preserves_provider_qualification(tmp_path):
    path, dataset = _dataset(tmp_path)
    loaded = load_historical_dataset_file(path)
    assert loaded.manifest.provider_qualification == dataset.manifest.provider_qualification
    assert loaded.manifest.provider_qualification.as_dict() == dataset.manifest.provider_qualification.as_dict()

    status = status_historical_dataset(input_file=path)
    verify = verify_historical_dataset_file(input_file=path)
    assert status["provider_qualification"] == dataset.manifest.provider_qualification.as_dict()
    assert verify["provider_qualification"] == dataset.manifest.provider_qualification.as_dict()


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("provider_id", "alt.provider", "provider qualification mismatch"),
        ("provider_version", "v2", "provider qualification mismatch"),
        ("market_type", "futures", "provider qualification mismatch"),
        ("exchange", "other", "provider qualification mismatch"),
        ("symbol", "ETHUSDT", "binance public spot provider only supports BTCUSDT 1h."),
        ("interval", "15m", "binance public spot provider only supports BTCUSDT 1h."),
    ],
)
def test_dataset_tampering_with_provider_qualification_or_contract_is_rejected(tmp_path, field, value, expected):
    path, _ = _dataset(tmp_path)
    payload = load_historical_dataset_file(path).as_dict()
    payload["manifest"]["provider_qualification"][field] = value
    if field == "provider_id":
        payload["manifest"]["provider"] = value
    if field == "symbol":
        payload["manifest"]["symbol"] = value
        payload["candles"][0]["symbol"] = value
    if field == "interval":
        payload["manifest"]["interval"] = value
        payload["candles"][0]["interval"] = value
    _recompute_dataset_payload_hashes(payload)
    rewritten = path.parent / f"tampered-{field}.json"
    rewritten.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    with pytest.raises((HistoricalDataValidationError, HistoricalDataIntegrityError), match=expected):
        load_historical_dataset_file(rewritten)


def test_replay_and_report_preserve_provider_qualification(tmp_path):
    path, dataset = _dataset(tmp_path)
    engine = LeakFreeBacktestEngine(
        BacktestConfig(
            initial_capital=Decimal("10000"),
            risk_percent=Decimal("1"),
            entry_fee_rate=Decimal("0"),
            exit_fee_rate=Decimal("0"),
            spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            leverage=Decimal("1"),
            symbol="BTCUSDT",
            interval="1h",
            strategy_version="v4_walk_forward",
        )
    )
    replay = replay_historical_backtest(path, engine=engine, strategy_callback=_signal_callback)
    assert replay.provenance.provider_qualification == dataset.manifest.provider_qualification
    assert replay.provenance.as_dict()["provider_qualification"] == dataset.manifest.provider_qualification.as_dict()

    report = run_historical_backtest_experiment(path, engine=engine, strategy_callable=_signal_callback)
    assert report.replay.provenance.provider_qualification == dataset.manifest.provider_qualification
    assert report.replay.provenance.as_dict()["provider_qualification"] == dataset.manifest.provider_qualification.as_dict()

    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_path = report_dir / "report.json"
    from historical_experiments import save_historical_experiment_report
    save_historical_experiment_report(report_path, report)
    reloaded_report = load_historical_experiment_report(report_path)
    assert reloaded_report.replay["provenance"]["provider_qualification"] == dataset.manifest.provider_qualification.as_dict()


def test_provider_resolution_occurs_once_and_has_no_fallback(tmp_path, monkeypatch):
    output = tmp_path / "resolved-once.json"

    class CountingProvider:
        provider_identity = "binance.public.klines"
        base_url = "https://api.binance.com/api/v3/klines"
        trusted_market_data_provider = True
        instances = 0
        qualification_calls = 0
        fetch_calls = 0

        def __init__(self):
            type(self).instances += 1

        def historical_qualification(self, symbol="BTCUSDT", interval="1h"):
            type(self).qualification_calls += 1
            return HistoricalProviderQualification.binance_public_spot(symbol=symbol, interval=interval)

        def fetch_klines(self, symbol, interval, limit=500, *, start_time=None, end_time=None):
            type(self).fetch_calls += 1
            return [_kline_row(BASE_START, base=100)]

    monkeypatch.setattr(historical, "BinancePublicKlinesProvider", CountingProvider)

    result = prepare_historical_dataset(
        output_file=output,
        provider=None,
        symbol="BTCUSDT",
        interval="1h",
        requested_start_utc=BASE_START,
        requested_end_utc=BASE_START + ONE_HOUR - ONE_MS,
        page_size=1,
        max_pages=2,
    )

    assert result["candle_count"] == 1
    assert CountingProvider.instances == 1
    assert CountingProvider.qualification_calls == 1
    assert CountingProvider.fetch_calls == 1


def test_qualification_divergence_changes_semantic_hashes():
    spot = _qualification()
    futures = HistoricalProviderQualification(
        provider_id="binance.public.klines",
        provider_version="v1",
        market_type="futures",
        exchange="binance",
        symbol="BTCUSDT",
        interval="1h",
        time_semantics="utc",
        access_type="public_no_auth",
        data_contract_version=1,
    )
    assert spot.qualification_hash != futures.qualification_hash
    assert spot.as_dict() != futures.as_dict()

