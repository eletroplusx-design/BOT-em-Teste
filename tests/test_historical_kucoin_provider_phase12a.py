from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest

from domain.serialization import serialize_value

import market_data.historical as historical
from domain import Candle, DataSource
from market_data import (
    HistoricalDataIntegrityError,
    HistoricalDataValidationError,
    HistoricalDataset,
    HistoricalDatasetRequest,
    HistoricalProviderQualification,
    KuCoinPublicSpotKlinesProvider,
    historical_content_hash,
    load_historical_dataset_file,
    prepare_historical_dataset_kucoin,
    status_historical_dataset,
    verify_historical_dataset_file,
)
from market_data.provider_qualification import KUCOIN_PUBLIC_SPOT_INTERVAL_SECONDS
from market_data.historical_manifest import build_historical_manifest
from paper_operations import build_parser


ONE_MS = timedelta(milliseconds=1)
BASE_START = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
KUCOIN_ENDPOINT = "https://api.kucoin.com/api/v1/market/candles"
KUCOIN_DOCS = "https://www.kucoin.com/docs-new/3470071w0"


class FakeResponse:
    def __init__(self, payload, *, status_code: int = 200, ok: bool = True):
        self._payload = payload
        self.status_code = status_code
        self.ok = ok

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        if not self.responses:
            raise AssertionError("unexpected extra request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class CountingKuCoinProvider(KuCoinPublicSpotKlinesProvider):
    instantiations = 0
    qualification_calls = 0
    fetch_calls = 0
    pages: list[list[list[int | str]] | dict[str, object]] = []

    def __init__(self):
        type(self).instantiations += 1
        super().__init__()
        self._pages = [page for page in type(self).pages]

    @classmethod
    def reset(cls, pages):
        cls.instantiations = 0
        cls.qualification_calls = 0
        cls.fetch_calls = 0
        cls.pages = [page for page in pages]

    def historical_qualification(self, symbol: str = "BTCUSDT", interval: str = "1h"):
        type(self).qualification_calls += 1
        return super().historical_qualification(symbol=symbol, interval=interval)

    def fetch_klines(self, symbol: str, interval: str, limit: int = 1500, *, start_time=None, end_time=None):
        type(self).fetch_calls += 1
        if not self._pages:
            raise AssertionError("unexpected extra historical fetch")
        page = self._pages.pop(0)
        if isinstance(page, dict):
            raise HistoricalDataValidationError("Malformed payload.")
        normalized_rows = []
        for row in page:
            open_time = int(row[0])
            interval_duration_seconds = KUCOIN_PUBLIC_SPOT_INTERVAL_SECONDS[interval]
            normalized_rows.append([
                open_time * 1000,
                row[1],
                row[3],
                row[4],
                row[2],
                row[5],
                (open_time + interval_duration_seconds) * 1000 - 1,
                0,
                0,
                0,
                0,
                0,
            ])
        normalized_rows.sort(key=lambda item: item[0])
        return normalized_rows


class BoundaryKuCoinProvider(KuCoinPublicSpotKlinesProvider):
    instantiations = 0
    qualification_calls = 0
    fetch_calls = 0
    calls: list[dict[str, int | None | str]] = []
    responses: list[dict[str, object]] = []

    def __init__(self):
        type(self).instantiations += 1
        super().__init__()
        self._responses = [dict(response) for response in type(self).responses]

    @classmethod
    def reset(cls, responses):
        cls.instantiations = 0
        cls.qualification_calls = 0
        cls.fetch_calls = 0
        cls.calls = []
        cls.responses = [dict(response) for response in responses]

    def historical_qualification(self, symbol: str = "BTCUSDT", interval: str = "1h"):
        type(self).qualification_calls += 1
        return super().historical_qualification(symbol=symbol, interval=interval)

    def fetch_klines(self, symbol: str, interval: str, limit: int = 1500, *, start_time=None, end_time=None):
        type(self).fetch_calls += 1
        type(self).calls.append({"symbol": symbol, "interval": interval, "start_time": start_time, "end_time": end_time, "limit": limit})
        if not self._responses:
            raise AssertionError("unexpected extra historical fetch")
        expected = self._responses.pop(0)
        if symbol != expected["symbol"] or interval != expected["interval"]:
            raise AssertionError(f"unexpected KuCoin request contract: {symbol!r} {interval!r}")
        if start_time != expected["start_time"] or end_time != expected["end_time"]:
            raise AssertionError(f"unexpected KuCoin page bounds: {start_time!r}..{end_time!r}")
        return expected["payload"]


class NoFetchProvider(CountingKuCoinProvider):
    def fetch_klines(self, *args, **kwargs):
        raise AssertionError("network must not be reached")


class StaticProvider(CountingKuCoinProvider):
    pass


class _TempDataset:
    pass



def _kucoin_raw_row(open_time: datetime, *, base: int = 100):
    return [
        str(int(open_time.timestamp())),
        str(base),
        str(base + 1),
        str(base + 5),
        str(base - 2),
        str(1000 + base),
        str(2000 + base),
    ]



def _kucoin_raw_page(start: datetime, count: int, *, base: int = 100, duration_seconds: int = 3600):
    rows = [_kucoin_raw_row(start + idx * timedelta(seconds=duration_seconds), base=base + idx) for idx in range(count)]
    return list(reversed(rows))



def _kucoin_normalized_page(start: datetime, count: int, *, base: int = 100, duration_seconds: int = 3600):
    return [
        [
            int((start + idx * timedelta(seconds=duration_seconds)).timestamp() * 1000),
            str(base + idx),
            str(base + idx + 3),
            str(base + idx - 2),
            str(base + idx + 1),
            str(1000 + base + idx),
            int((start + idx * timedelta(seconds=duration_seconds) + timedelta(seconds=duration_seconds) - ONE_MS).timestamp() * 1000),
            0,
            0,
            0,
            0,
            0,
        ]
        for idx in range(count)
    ]



def _kucoin_qualification(interval: str):
    return HistoricalProviderQualification.kucoin_public_spot(symbol="BTCUSDT", interval=interval)


def _canonical_hash(payload):
    return sha256(json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()



def _kucoin_dataset(tmp_path: Path, *, interval: str = "1h", count: int = 12) -> tuple[Path, HistoricalDataset]:
    seconds = HistoricalProviderQualification.kucoin_public_spot(symbol="BTCUSDT", interval=interval).interval_duration_seconds or 3600
    candles = tuple(
        Candle.from_dict(
            {
                "open_time": BASE_START + idx * timedelta(seconds=seconds),
                "close_time": BASE_START + idx * timedelta(seconds=seconds) + timedelta(seconds=seconds) - ONE_MS,
                "open": str(100 + idx),
                "high": str(106 + idx),
                "low": str(96 + idx),
                "close": str(102 + idx),
                "volume": str(1000 + idx),
                "symbol": "BTCUSDT",
                "interval": interval,
                "source": DataSource.KUCOIN,
            }
        )
        for idx in range(count)
    )
    request = HistoricalDatasetRequest(
        provider="kucoin.public.klines",
        provider_qualification=_kucoin_qualification(interval),
        endpoint=KUCOIN_ENDPOINT,
        symbol="BTCUSDT",
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
    path = tmp_path / f"kucoin-historical-dataset-{interval}.json"
    historical.save_historical_dataset(path, dataset)
    return path, dataset


@pytest.mark.parametrize(
    ("interval", "expected_version", "expected_code", "expected_duration", "expected_close_rule"),
    [
        ("15m", 3, "15min", 900, "open_time + interval_duration_seconds - 1ms"),
        ("1h", 2, "1hour", 3600, "open_time + 1h - 1ms"),
        ("4h", 3, "4hour", 14400, "open_time + interval_duration_seconds - 1ms"),
    ],
)
def test_kucoin_qualification_is_canonical_for_allowed_intervals(interval, expected_version, expected_code, expected_duration, expected_close_rule):
    first = _kucoin_qualification(interval)
    second = HistoricalProviderQualification.from_dict(first.as_dict())
    assert first == second
    assert first.qualification_hash == second.qualification_hash
    assert first.as_dict() == second.as_dict()
    assert first.data_contract_version == expected_version
    assert first.interval_code == (expected_code if expected_version == 3 else "")
    assert first.interval_duration_seconds == (expected_duration if expected_version == 3 else 0)
    assert first.close_time_rule == expected_close_rule


@pytest.mark.parametrize("interval", ["5m", "3m", "1d", "4hour", "15min", "2h", "1hour", "abc"])
def test_kucoin_qualification_rejects_non_whitelisted_intervals(interval):
    with pytest.raises(HistoricalDataValidationError, match="only supports BTCUSDT 15m, 1h, or 4h"):
        HistoricalProviderQualification.kucoin_public_spot(symbol="BTCUSDT", interval=interval)


@pytest.mark.parametrize(
    ("interval", "duration_seconds", "code"),
    [("15m", 900, "15min"), ("1h", 3600, "1hour"), ("4h", 14400, "4hour")],
)
def test_kucoin_provider_fetch_uses_official_codes_and_derives_close_time(interval, duration_seconds, code):
    start = BASE_START
    rows = _kucoin_raw_page(start, 2, duration_seconds=duration_seconds)
    session = FakeSession([FakeResponse({"code": "200000", "data": rows})])
    provider = KuCoinPublicSpotKlinesProvider(session=session)

    payload = provider.fetch_klines(
        "BTCUSDT",
        interval,
        limit=1500,
        start_time=int(start.timestamp() * 1000),
        end_time=int((start + 2 * timedelta(seconds=duration_seconds) - ONE_MS).timestamp() * 1000),
    )

    assert session.calls[0]["url"] == KUCOIN_ENDPOINT
    assert session.calls[0]["params"]["symbol"] == "BTC-USDT"
    assert session.calls[0]["params"]["type"] == code
    assert payload[0][0] < payload[1][0]
    assert payload[0][6] == payload[0][0] + duration_seconds * 1000 - 1
    assert payload[1][6] == payload[1][0] + duration_seconds * 1000 - 1


@pytest.mark.parametrize(
    ("interval", "duration_seconds", "page_size", "total_candles", "first_page_count", "second_page_count"),
    [
        ("15m", 900, 3, 4, 3, 1),
        ("4h", 14400, 3, 4, 3, 1),
    ],
)
def test_prepare_historical_dataset_kucoin_pages_with_exact_boundaries_for_allowed_intervals(tmp_path, monkeypatch, interval, duration_seconds, page_size, total_candles, first_page_count, second_page_count):
    requested_start = BASE_START
    requested_end = requested_start + total_candles * timedelta(seconds=duration_seconds) - ONE_MS
    first_page_end = requested_start + first_page_count * timedelta(seconds=duration_seconds) - ONE_MS
    second_start = requested_start + first_page_count * timedelta(seconds=duration_seconds)
    responses = [
        {
            "symbol": "BTCUSDT",
            "interval": interval,
            "start_time": int(requested_start.timestamp() * 1000),
            "end_time": int(first_page_end.timestamp() * 1000),
            "payload": _kucoin_normalized_page(requested_start, first_page_count, base=100, duration_seconds=duration_seconds),
        },
        {
            "symbol": "BTCUSDT",
            "interval": interval,
            "start_time": int(second_start.timestamp() * 1000),
            "end_time": int(requested_end.timestamp() * 1000),
            "payload": _kucoin_normalized_page(second_start, second_page_count, base=5000, duration_seconds=duration_seconds),
        },
    ]
    BoundaryKuCoinProvider.reset(responses)
    monkeypatch.setattr(historical, "KuCoinPublicSpotKlinesProvider", BoundaryKuCoinProvider)
    output = tmp_path / f"kucoin-{interval}-boundary.json"

    result = prepare_historical_dataset_kucoin(
        output_file=output,
        symbol="BTCUSDT",
        interval=interval,
        requested_start_utc=requested_start,
        requested_end_utc=requested_end,
        page_size=page_size,
        max_pages=2,
    )

    assert result["reused"] is False
    assert result["page_count"] == 2
    assert result["candle_count"] == total_candles
    assert BoundaryKuCoinProvider.instantiations == 1
    assert BoundaryKuCoinProvider.qualification_calls == 1
    assert BoundaryKuCoinProvider.fetch_calls == 2
    assert len(BoundaryKuCoinProvider.calls) == 2
    assert BoundaryKuCoinProvider.calls[0]["symbol"] == "BTCUSDT"
    assert BoundaryKuCoinProvider.calls[0]["interval"] == interval
    assert BoundaryKuCoinProvider.calls[0]["start_time"] == int(requested_start.timestamp() * 1000)
    assert BoundaryKuCoinProvider.calls[0]["end_time"] == int(first_page_end.timestamp() * 1000)
    assert BoundaryKuCoinProvider.calls[1]["interval"] == interval
    assert BoundaryKuCoinProvider.calls[1]["start_time"] == int(second_start.timestamp() * 1000)
    assert BoundaryKuCoinProvider.calls[1]["end_time"] == int(requested_end.timestamp() * 1000)

    dataset = load_historical_dataset_file(output)
    assert len(dataset.candles) == total_candles
    assert dataset.manifest.page_count == 2
    assert dataset.manifest.candle_count == total_candles
    assert dataset.manifest.provider_qualification == _kucoin_qualification(interval)
    assert dataset.candles[0].open_time == requested_start
    assert dataset.candles[-1].close_time == requested_end
    assert dataset.manifest.provider_qualification.interval == interval
    if interval == "15m":
        assert dataset.manifest.provider_qualification.interval_code == "15min"
        assert dataset.manifest.provider_qualification.interval_duration_seconds == 900
    if interval == "4h":
        assert dataset.manifest.provider_qualification.interval_code == "4hour"
        assert dataset.manifest.provider_qualification.interval_duration_seconds == 14400

    status = status_historical_dataset(input_file=output)
    verify = verify_historical_dataset_file(input_file=output)
    assert status["provider_qualification"] == _kucoin_qualification(interval).as_dict()
    assert verify["provider_qualification"] == _kucoin_qualification(interval).as_dict()


@pytest.mark.parametrize("interval", ["15m", "1h", "4h"])
def test_kucoin_legacy_and_new_dataset_round_trip_preserve_provenance(tmp_path, interval):
    path, dataset = _kucoin_dataset(tmp_path, interval=interval, count=8)
    loaded = load_historical_dataset_file(path)
    assert loaded.manifest.provider_qualification == dataset.manifest.provider_qualification
    assert loaded.manifest.provider_qualification.as_dict() == dataset.manifest.provider_qualification.as_dict()
    assert loaded.manifest.interval == interval
    assert loaded.manifest.symbol == "BTCUSDT"


@pytest.mark.parametrize("interval", ["15m", "4h"])
def test_kucoin_tampering_with_interval_metadata_is_rejected_even_with_recomputed_hashes(tmp_path, interval):
    path, _ = _kucoin_dataset(tmp_path, interval=interval, count=8)
    payload = load_historical_dataset_file(path).as_dict()
    payload["manifest"]["provider_qualification"]["interval_code"] = "1hour" if interval == "15m" else "15min"
    payload["manifest"]["provider_qualification"]["interval_duration_seconds"] = 3600 if interval == "15m" else 900
    payload["manifest"]["provider_qualification"]["close_time_rule"] = "open_time + 1h - 1ms"
    candles = [Candle.from_dict(item) for item in payload["candles"]]
    payload["manifest"]["content_hash"] = historical_content_hash(candles)
    payload["manifest"]["dataset_id"] = payload["manifest"]["content_hash"]
    payload["manifest"]["provider_qualification"]["qualification_hash"] = _canonical_hash(
        {k: v for k, v in payload["manifest"]["provider_qualification"].items() if k != "qualification_hash"}
    )
    payload["manifest"]["manifest_hash"] = _canonical_hash({k: v for k, v in payload["manifest"].items() if k != "manifest_hash"})
    tampered = path.parent / f"tampered-{interval}.json"
    tampered.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    with pytest.raises((HistoricalDataValidationError, HistoricalDataIntegrityError), match="provider qualification mismatch|Historical dataset payload mismatch|interval_code mismatch|interval_duration_seconds mismatch|close_time_rule is required"):
        load_historical_dataset_file(tampered)


@pytest.mark.parametrize("interval", ["15m", "1h", "4h"])
def test_kucoin_prepare_cli_accepts_only_whitelisted_intervals(interval):
    parser = build_parser()
    args = parser.parse_args(["history", "prepare-kucoin", "--symbol", "BTCUSDT", "--interval", interval, "--start-utc", "2024-01-01T00:00:00Z", "--end-utc", "2024-01-01T01:00:00Z", "--output", "out.json"])
    assert args.history_command == "prepare-kucoin"
    assert args.interval == interval


@pytest.mark.parametrize("interval", ["5m", "3m", "1d", "4hour", "15min"])
def test_kucoin_prepare_cli_rejects_non_whitelisted_intervals(interval):
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["history", "prepare-kucoin", "--symbol", "BTCUSDT", "--interval", interval, "--start-utc", "2024-01-01T00:00:00Z", "--end-utc", "2024-01-01T01:00:00Z", "--output", "out.json"])


@pytest.mark.parametrize("interval", ["15m", "1h", "4h"])
def test_kucoin_provider_resolution_occurs_once_and_has_no_fallback_for_allowed_intervals(tmp_path, monkeypatch, interval):
    output = tmp_path / f"resolved-{interval}.json"

    class CountingProvider(CountingKuCoinProvider):
        pass

    CountingProvider.reset([
        _kucoin_raw_page(BASE_START, 1, duration_seconds=HistoricalProviderQualification.kucoin_public_spot(symbol="BTCUSDT", interval=interval).interval_duration_seconds or 3600),
    ])
    monkeypatch.setattr(historical, "KuCoinPublicSpotKlinesProvider", CountingProvider)

    result = prepare_historical_dataset_kucoin(
        output_file=output,
        symbol="BTCUSDT",
        interval=interval,
        requested_start_utc=BASE_START,
        requested_end_utc=BASE_START + timedelta(seconds=HistoricalProviderQualification.kucoin_public_spot(symbol="BTCUSDT", interval=interval).interval_duration_seconds or 3600) - ONE_MS,
        page_size=1,
        max_pages=2,
    )

    assert result["candle_count"] == 1
    assert CountingProvider.instantiations == 1
    assert CountingProvider.qualification_calls == 1
    assert CountingProvider.fetch_calls == 1
