from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

import market_data.okx_historical as okx
from domain import Candle
from market_data import HistoricalDataConflictError, HistoricalDataIntegrityError, HistoricalDataValidationError, HistoricalProviderQualification

ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)
START_UTC = okx.OKX_HISTORICAL_REQUESTED_START_INCLUSIVE_UTC
END_EXCLUSIVE_UTC = okx.OKX_HISTORICAL_REQUESTED_END_EXCLUSIVE_UTC
TOTAL_CANDLES = okx.OKX_HISTORICAL_EXPECTED_CANDLE_COUNT
PAGE_SIZE = okx.OKX_HISTORICAL_REQUEST_LIMIT
PAGE_COUNT = TOTAL_CANDLES // PAGE_SIZE + (1 if TOTAL_CANDLES % PAGE_SIZE else 0)

def _workspace_tmp_dir(name: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp" / name
    root.mkdir(parents=True, exist_ok=True)
    return root

def _okx_row(open_time: datetime, *, base: int) -> list[str | int]:
    return [
        int(open_time.timestamp() * 1000),
        str(base),
        str(base + 5),
        str(base - 2),
        str(base + 1),
        str(1000 + base),
        str(2000 + base),
        str(3000 + base),
        1,
    ]

def _okx_page(start: datetime, count: int, *, base: int) -> list[list[str | int]]:
    rows = [_okx_row(start + idx * ONE_HOUR, base=base + idx) for idx in range(count)]
    return list(reversed(rows))

def _okx_page_specs() -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    for page_index in range(PAGE_COUNT):
        page_start = START_UTC + timedelta(hours=TOTAL_CANDLES - (page_index + 1) * PAGE_SIZE)
        if page_index == 0:
            after = int(END_EXCLUSIVE_UTC.timestamp() * 1000)
        else:
            prev_page_start = START_UTC + timedelta(hours=TOTAL_CANDLES - page_index * PAGE_SIZE)
            after = int(prev_page_start.timestamp() * 1000)
        specs.append(
            {
                "after": after,
                "symbol": okx.OKX_HISTORICAL_SYMBOL,
                "interval": okx.OKX_HISTORICAL_CANDLE_INTERVAL,
                "limit": PAGE_SIZE,
                "payload": _okx_page(page_start, PAGE_SIZE, base=10_000 + page_index * PAGE_SIZE),
            }
        )
    return specs

class FakeOkxProvider:
    base_url = okx.OKX_HISTORICAL_ENDPOINT_URL
    trusted_market_data_provider = True
    historical_source = okx.DataSource.OKX
    provider_identity = okx.OKX_HISTORICAL_PROVIDER_ID
    provider_version = okx.OKX_HISTORICAL_PROVIDER_VERSION
    historical_market_type = okx.OKX_HISTORICAL_MARKET_TYPE
    historical_exchange = okx.OKX_HISTORICAL_PROVIDER_EXCHANGE
    historical_access_type = "public_no_auth"
    historical_symbol = okx.OKX_HISTORICAL_SYMBOL
    historical_external_symbol = okx.OKX_HISTORICAL_INSTRUMENT
    historical_interval = okx.OKX_HISTORICAL_CANDLE_INTERVAL
    historical_pagination_limit = PAGE_SIZE
    instantiations = 0
    qualification_calls = 0
    fetch_calls = 0
    calls: list[dict[str, int | str]] = []
    pages: list[dict[str, object]] = []

    def __init__(self) -> None:
        type(self).instantiations += 1
        self._pages = [dict(page) for page in type(self).pages]

    @classmethod
    def reset(cls, pages: list[dict[str, object]]) -> None:
        cls.instantiations = 0
        cls.qualification_calls = 0
        cls.fetch_calls = 0
        cls.calls = []
        cls.pages = [dict(page) for page in pages]

    def historical_qualification(self, symbol: str = okx.OKX_HISTORICAL_SYMBOL, interval: str = okx.OKX_HISTORICAL_CANDLE_INTERVAL):
        type(self).qualification_calls += 1
        return HistoricalProviderQualification.okx_public_spot(symbol=symbol, interval=interval)

    def fetch_klines(self, symbol: str, interval: str, limit: int = PAGE_SIZE, *, after: int | None = None):
        type(self).fetch_calls += 1
        type(self).calls.append({"symbol": symbol, "interval": interval, "limit": limit, "after": after or 0})
        if not self._pages:
            raise AssertionError("unexpected extra historical fetch")
        expected = self._pages.pop(0)
        if symbol != expected["symbol"] or interval != expected["interval"] or limit != expected["limit"] or after != expected["after"]:
            raise AssertionError(f"unexpected OKX request contract: {symbol!r} {interval!r} {limit!r} {after!r}")
        return expected["payload"]

def _canonical_contract_kwargs() -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_name": "OKX",
        "provider_id": "okx.public.klines",
        "provider_version": "v1",
        "market_type": "spot",
        "instrument": "BTC-USDT",
        "symbol": "BTCUSDT",
        "interval": "1H",
        "endpoint_method": "GET",
        "endpoint_url": "https://www.okx.com/api/v5/market/history-candles",
        "endpoint_path": "/api/v5/market/history-candles",
        "documentation_url": "https://www.okx.com/docs-v5/en/",
        "cursor_name": "after",
        "cursor_exclusive": True,
        "collection_direction": "reverse_chronological",
        "request_limit": 100,
        "confirm_required_value": 1,
        "requested_start_inclusive_utc": START_UTC,
        "requested_end_exclusive_utc": END_EXCLUSIVE_UTC,
        "cursor_semantics": "after returns candles earlier than the cursor timestamp and the next cursor is the oldest retained open time.",
        "request_params": {"instId": "BTC-USDT", "bar": "1H", "limit": 100},
        "historical_research_only": True,
        "operational_evidence": False,
        "paper_promotion_eligible": False,
    }

@pytest.fixture(scope="module")
def okx_base_artifacts():
    artifact_root = _workspace_tmp_dir(f"okx-phase19a-base-{os.getpid()}")
    dataset_file, manifest_file = okx.resolve_okx_historical_artifact_paths(artifact_root)
    FakeOkxProvider.reset(_okx_page_specs())

    def _fail_network(*args, **kwargs):
        raise AssertionError("network must not be reached")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(requests.sessions.Session, "get", _fail_network, raising=True)
    try:
        result = okx.prepare_okx_historical_dataset(
            dataset_file=dataset_file,
            manifest_file=manifest_file,
            provider=FakeOkxProvider(),
        )
    finally:
        monkeypatch.undo()

    dataset = okx.load_okx_historical_dataset(dataset_file=dataset_file, manifest_file=manifest_file)
    return {
        "root": artifact_root,
        "dataset_file": dataset_file,
        "manifest_file": manifest_file,
        "result": result,
        "dataset": dataset,
    }

@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("instrument", "BTCUSDT", "instrument must be BTC-USDT"),
        ("interval", "1h", "interval must be 1H"),
        ("market_type", "futures", "market_type must be spot"),
        ("endpoint_url", "https://example.invalid", "endpoint_url must be the official OKX history-candles endpoint"),
        ("requested_end_exclusive_utc", END_EXCLUSIVE_UTC + ONE_HOUR, "requested_end_exclusive_utc diverges from the Fase 19A contract"),
    ],
)
def test_okx_contract_rejects_invalid_values(field, value, match):
    kwargs = _canonical_contract_kwargs()
    kwargs[field] = value
    with pytest.raises(HistoricalDataValidationError, match=match):
        okx.OkxHistoricalIngestionContract(**kwargs)

def test_okx_provider_qualification_is_strict_and_separate_from_kucoin():
    okx_qual = HistoricalProviderQualification.okx_public_spot()
    round_trip = HistoricalProviderQualification.from_dict(okx_qual.as_dict())
    kucoin_qual = HistoricalProviderQualification.kucoin_public_spot(symbol="BTCUSDT", interval="1h")

    assert okx_qual == round_trip
    assert okx_qual.qualification_hash == round_trip.qualification_hash
    assert okx_qual.interval == "1H"
    assert okx_qual.external_symbol == "BTC-USDT"
    assert okx_qual.pagination_limit == 100
    assert okx_qual.close_time_rule == "confirm=0 means incomplete; confirm=1 means completed"
    assert okx_qual != kucoin_qual
    assert okx_qual.qualification_hash != kucoin_qual.qualification_hash
    assert okx_qual.exchange == "okx"
    assert kucoin_qual.exchange == "kucoin"

def test_okx_artifact_paths_are_explicitly_separate_from_kucoin():
    dataset_file, manifest_file = okx.resolve_okx_historical_artifact_paths(_workspace_tmp_dir(f"okx-phase19a-paths-{os.getpid()}"))

    assert "okx" in {part.lower() for part in dataset_file.parts}
    assert "okx" in {part.lower() for part in manifest_file.parts}
    assert "kucoin" not in {part.lower() for part in dataset_file.parts}
    assert "kucoin" not in {part.lower() for part in manifest_file.parts}
    assert dataset_file.name.endswith(".candles.json")
    assert manifest_file.name.endswith(".manifest.json")

def test_okx_full_ingestion_is_deterministic_write_once_and_offline_verified(okx_base_artifacts):
    dataset = okx_base_artifacts["dataset"]
    result = okx_base_artifacts["result"]
    loaded = dataset
    verified = okx.verify_okx_historical_dataset(
        dataset_file=okx_base_artifacts["dataset_file"],
        manifest_file=okx_base_artifacts["manifest_file"],
    )

    assert result["reused"] is False
    assert result["candle_count"] == TOTAL_CANDLES
    assert result["page_count"] == PAGE_COUNT
    assert result["first_candle_open_utc"] == "2021-02-12T00:00:00Z"
    assert result["last_candle_open_utc"] == "2025-12-31T23:00:00Z"
    assert loaded.manifest.contract.request_params == {"instId": "BTC-USDT", "bar": "1H", "limit": 100}
    assert loaded.manifest.contract.historical_research_only is True
    assert loaded.manifest.contract.operational_evidence is False
    assert loaded.manifest.contract.paper_promotion_eligible is False
    assert loaded.manifest.non_ingestion_scope_statement == okx.OKX_HISTORICAL_NON_INGESTION_SCOPE_STATEMENT
    assert loaded.manifest.trimmed_before_start_count == 84
    assert loaded.manifest.dataset_hash == result["dataset_hash"]
    assert loaded.manifest.manifest_hash == result["manifest_hash"]
    assert loaded.candles[0].open_time == START_UTC
    assert loaded.candles[-1].open_time == END_EXCLUSIVE_UTC - ONE_HOUR
    assert all(candle.source.name == "OKX" for candle in loaded.candles)
    assert verified["verified"] is True
    assert verified["dataset_hash"] == loaded.manifest.dataset_hash
    assert verified["manifest_hash"] == loaded.manifest.manifest_hash
    assert verified["candle_count"] == TOTAL_CANDLES
    assert verified["page_count"] == PAGE_COUNT
    assert verified["historical_research_only"] is True
    assert verified["operational_evidence"] is False
    assert verified["paper_promotion_eligible"] is False
    assert FakeOkxProvider.fetch_calls == PAGE_COUNT
    assert len(FakeOkxProvider.calls) == PAGE_COUNT

def test_okx_prepare_is_idempotent_when_artifacts_already_exist(okx_base_artifacts):
    class NoFetchProvider(FakeOkxProvider):
        def fetch_klines(self, *args, **kwargs):
            raise AssertionError("network must not be reached")

    NoFetchProvider.reset([])
    result = okx.prepare_okx_historical_dataset(
        dataset_file=okx_base_artifacts["dataset_file"],
        manifest_file=okx_base_artifacts["manifest_file"],
        provider=NoFetchProvider(),
    )

    assert result["reused"] is True
    assert result["candle_count"] == TOTAL_CANDLES

def test_okx_save_rejects_overwrite_conflict(okx_base_artifacts):
    loaded = okx_base_artifacts["dataset"]
    altered_candles = list(loaded.candles)
    altered_first = Candle.from_dict(
        {
            **altered_candles[0].to_dict(),
            "open": "99999",
            "high": "100010",
            "low": "99990",
            "close": "100001",
        }
    )
    altered_candles[0] = altered_first
    altered_dataset_hash = okx.historical_content_hash(tuple(altered_candles))
    altered_manifest = okx.OkxHistoricalIngestionManifest(
        schema_version=loaded.manifest.schema_version,
        contract=loaded.manifest.contract,
        expected_candle_count=len(altered_candles),
        found_candle_count=len(altered_candles),
        page_count=loaded.manifest.page_count,
        first_candle_open_utc=altered_candles[0].open_time,
        first_candle_close_utc=altered_candles[0].close_time,
        last_candle_open_utc=altered_candles[-1].open_time,
        last_candle_close_utc=altered_candles[-1].close_time,
        trimmed_before_start_count=loaded.manifest.trimmed_before_start_count,
        gap_count=0,
        duplicate_count=0,
        overlap_count=0,
        cursor_no_progress_count=0,
        http_error_count=0,
        timeout_count=0,
        malformed_response_count=0,
        dataset_hash=altered_dataset_hash,
    )
    altered_dataset = okx.OkxHistoricalDataset(manifest=altered_manifest, candles=tuple(altered_candles))

    with pytest.raises(HistoricalDataConflictError):
        okx.save_okx_historical_dataset(
            dataset_file=okx_base_artifacts["dataset_file"],
            manifest_file=okx_base_artifacts["manifest_file"],
            dataset=altered_dataset,
        )

def test_okx_load_detects_dataset_and_manifest_tampering(okx_base_artifacts):
    temp_dir = _workspace_tmp_dir(f"okx-phase19a-tamper-{os.getpid()}")
    dataset_copy = temp_dir / "dataset.json"
    manifest_copy = temp_dir / "manifest.json"
    dataset_copy.write_text(okx_base_artifacts["dataset_file"].read_text(encoding="utf-8"), encoding="utf-8")
    manifest_copy.write_text(okx_base_artifacts["manifest_file"].read_text(encoding="utf-8"), encoding="utf-8")

    dataset_payload = json.loads(dataset_copy.read_text(encoding="utf-8"))
    dataset_payload[0]["close"] = "123456"
    dataset_copy.write_text(json.dumps(dataset_payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    with pytest.raises((HistoricalDataIntegrityError, HistoricalDataValidationError)):
        okx.load_okx_historical_dataset(dataset_file=dataset_copy, manifest_file=manifest_copy)

    dataset_copy.write_text(okx_base_artifacts["dataset_file"].read_text(encoding="utf-8"), encoding="utf-8")
    manifest_payload = json.loads(manifest_copy.read_text(encoding="utf-8"))
    manifest_payload["page_count"] = 1
    manifest_copy.write_text(json.dumps(manifest_payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    with pytest.raises((HistoricalDataIntegrityError, HistoricalDataValidationError)):
        okx.load_okx_historical_dataset(dataset_file=dataset_copy, manifest_file=manifest_copy)
