from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

import market_data.historical as historical
from domain import Candle, DataSource
from market_data import (
    HistoricalDataConflictError,
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
from market_data.historical_manifest import build_historical_manifest
from paper_operations import build_parser
from domain.serialization import serialize_value


ONE_HOUR = timedelta(hours=1)
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
            normalized_rows.append([
                open_time * 1000,
                row[1],
                row[3],
                row[4],
                row[2],
                row[5],
                (open_time + 3600) * 1000 - 1,
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
    calls: list[dict[str, int | None]] = []
    responses: list[dict[str, Any]] = []

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
        type(self).calls.append({"start_time": start_time, "end_time": end_time, "limit": limit})
        if not self._responses:
            raise AssertionError("unexpected extra historical fetch")
        expected = self._responses.pop(0)
        if start_time != expected["start_time"] or end_time != expected["end_time"]:
            raise AssertionError(f"unexpected KuCoin page bounds: {start_time!r}..{end_time!r}")
        return expected["payload"]



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


def _kucoin_raw_page(start: datetime, count: int, *, base: int = 100):
    rows = [_kucoin_raw_row(start + idx * ONE_HOUR, base=base + idx) for idx in range(count)]
    return list(reversed(rows))


def _kucoin_normalized_page(start: datetime, count: int, *, base: int = 100):
    return [
        [
            int((start + idx * ONE_HOUR).timestamp() * 1000),
            str(base + idx),
            str(base + idx + 3),
            str(base + idx - 2),
            str(base + idx + 1),
            str(1000 + base + idx),
            int((start + idx * ONE_HOUR + ONE_HOUR - ONE_MS).timestamp() * 1000),
            0,
            0,
            0,
            0,
            0,
        ]
        for idx in range(count)
    ]


def _dataset_rows(count: int = 12, *, symbol: str = "BTCUSDT"):
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
                "interval": "1h",
                "source": DataSource.KUCOIN,
            }
        )
        for idx in range(count)
    )


def _kucoin_qualification(symbol: str = "BTCUSDT"):
    return HistoricalProviderQualification.kucoin_public_spot(symbol=symbol, interval="1h")


def _kucoin_dataset(tmp_path: Path, *, count: int = 12, symbol: str = "BTCUSDT") -> tuple[Path, HistoricalDataset]:
    candles = _dataset_rows(count=count, symbol=symbol)
    request = HistoricalDatasetRequest(
        provider="kucoin.public.klines",
        provider_qualification=_kucoin_qualification(symbol=symbol),
        endpoint=KUCOIN_ENDPOINT,
        symbol=symbol,
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
    path = tmp_path / "kucoin-historical-dataset.json"
    historical.save_historical_dataset(path, dataset)
    return path, dataset


def _canonical_hash(payload: dict) -> str:
    canonical = json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _recompute_dataset_payload_hashes(payload: dict) -> None:
    provider_qualification_payload = dict(payload["manifest"]["provider_qualification"])
    provider_qualification_payload.pop("qualification_hash", None)
    provider_qualification = HistoricalProviderQualification.from_dict(provider_qualification_payload)
    payload["manifest"]["provider_qualification"]["qualification_hash"] = provider_qualification.qualification_hash
    candles = tuple(Candle.from_dict(item) for item in payload["candles"])
    payload["manifest"]["content_hash"] = historical_content_hash(candles)
    payload["manifest"]["dataset_id"] = payload["manifest"]["content_hash"]
    payload["manifest"]["manifest_hash"] = _canonical_hash(payload["manifest"])


def test_kucoin_qualification_hash_is_canonical_and_deterministic():
    first = _kucoin_qualification()
    second = HistoricalProviderQualification.from_dict(first.as_dict())
    assert first == second
    assert first.qualification_hash == second.qualification_hash
    assert first.as_dict() == second.as_dict()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"provider_version": "v1", "market_type": "spot", "exchange": "kucoin", "symbol": "BTCUSDT", "interval": "1h", "time_semantics": "utc", "access_type": "public_no_auth", "data_contract_version": 2, "external_symbol": "BTC-USDT", "endpoint_url": "https://api.kucoin.com/api/v1/market/candles", "documentation_url": KUCOIN_DOCS, "pagination_limit": 1500, "close_time_rule": "open_time + 1h - 1ms"}, "provider qualification is incomplete."),
        ({"provider_id": True, "provider_version": "v1", "market_type": "spot", "exchange": "kucoin", "symbol": "BTCUSDT", "interval": "1h", "time_semantics": "utc", "access_type": "public_no_auth", "data_contract_version": 2, "external_symbol": "BTC-USDT", "endpoint_url": "https://api.kucoin.com/api/v1/market/candles", "documentation_url": KUCOIN_DOCS, "pagination_limit": 1500, "close_time_rule": "open_time + 1h - 1ms"}, "provider_id is required."),
        ({"provider_id": "kucoin.public.klines", "provider_version": "v1", "market_type": "invalid", "exchange": "kucoin", "symbol": "BTCUSDT", "interval": "1h", "time_semantics": "utc", "access_type": "public_no_auth", "data_contract_version": 2, "external_symbol": "BTC-USDT", "endpoint_url": "https://api.kucoin.com/api/v1/market/candles", "documentation_url": KUCOIN_DOCS, "pagination_limit": 1500, "close_time_rule": "open_time + 1h - 1ms"}, "market_type must be spot or futures."),
        ({"provider_id": "kucoin.public.klines", "provider_version": "v1", "market_type": "spot", "exchange": "kucoin", "symbol": "BTCUSDT", "interval": "1h", "time_semantics": "utc", "access_type": "public_no_auth", "data_contract_version": True, "external_symbol": "BTC-USDT", "endpoint_url": "https://api.kucoin.com/api/v1/market/candles", "documentation_url": KUCOIN_DOCS, "pagination_limit": 1500, "close_time_rule": "open_time + 1h - 1ms"}, "data_contract_version must be an integer."),
    ],
)
def test_kucoin_qualification_rejects_missing_and_invalid_fields(payload, message):
    with pytest.raises(HistoricalDataValidationError, match=message):
        HistoricalProviderQualification.from_dict(payload)

@pytest.mark.parametrize(
    ("symbol", "external_symbol"),
    [
        ("BTCUSDT", "BTC-USDT"),
        ("ethusdt", "ETH-USDT"),
        ("SolUsdt", "SOL-USDT"),
        ("UNIUSDT", "UNI-USDT"),
    ],
)
def test_kucoin_qualification_accepts_supported_symbols_and_derives_external_symbol(symbol, external_symbol):
    qualification = HistoricalProviderQualification.kucoin_public_spot(symbol=symbol, interval="1h")
    assert qualification.symbol == symbol.strip().upper()
    assert qualification.external_symbol == external_symbol
    assert qualification.qualification_hash == HistoricalProviderQualification.from_dict(qualification.as_dict()).qualification_hash

def test_kucoin_qualification_hash_differs_across_supported_symbols():
    btc = HistoricalProviderQualification.kucoin_public_spot(symbol="BTCUSDT", interval="1h")
    eth = HistoricalProviderQualification.kucoin_public_spot(symbol="ETHUSDT", interval="1h")
    sol = HistoricalProviderQualification.kucoin_public_spot(symbol="SOLUSDT", interval="1h")
    uni = HistoricalProviderQualification.kucoin_public_spot(symbol="UNIUSDT", interval="1h")
    assert len({btc.qualification_hash, eth.qualification_hash, sol.qualification_hash, uni.qualification_hash}) == 4

@pytest.mark.parametrize("symbol", ["DOGEUSDT", "BTCUSD", "BTC-USDT"])
def test_kucoin_qualification_rejects_unsupported_symbols(symbol):
    with pytest.raises(HistoricalDataValidationError, match="only supports BTCUSDT, ETHUSDT, SOLUSDT, or UNIUSDT"):
        HistoricalProviderQualification.kucoin_public_spot(symbol=symbol, interval="1h")


def test_kucoin_qualification_rejects_futures_in_spot_contract():
    futures = HistoricalProviderQualification(
        provider_id="kucoin.public.klines",
        provider_version="v1",
        market_type="futures",
        exchange="kucoin",
        symbol="BTCUSDT",
        interval="1h",
        time_semantics="utc",
        access_type="public_no_auth",
        data_contract_version=2,
        external_symbol="BTC-USDT",
        endpoint_url="https://api.kucoin.com/api/v1/market/candles",
        documentation_url=KUCOIN_DOCS,
        pagination_limit=1500,
        close_time_rule="open_time + 1h - 1ms",
    )
    with pytest.raises(HistoricalDataValidationError, match="provider qualification mismatch"):
        HistoricalDatasetRequest(
            provider="kucoin.public.klines",
            provider_qualification=futures,
            endpoint=KUCOIN_ENDPOINT,
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=BASE_START + ONE_HOUR - ONE_MS,
            page_size=1,
            closed_candles_only=True,
        )

@pytest.mark.parametrize(
    ("symbol", "external_symbol"),
    [
        ("ETHUSDT", "ETH-USDT"),
        ("SolUsdt", "SOL-USDT"),
        ("uniusdt", "UNI-USDT"),
    ],
)
def test_kucoin_provider_fetch_uses_symbol_specific_request_symbol(symbol, external_symbol):
    start = BASE_START
    rows = _kucoin_raw_page(start, 1)
    session = FakeSession([FakeResponse({"code": "200000", "data": rows})])
    provider = KuCoinPublicSpotKlinesProvider(session=session)

    payload = provider.fetch_klines(symbol, "1h", limit=1500, start_time=int(start.timestamp() * 1000), end_time=int((start + ONE_HOUR - ONE_MS).timestamp() * 1000))

    assert session.calls[0]["params"]["symbol"] == external_symbol
    assert session.calls[0]["params"]["type"] == "1hour"
    assert payload[0][0] == int(start.timestamp() * 1000)


def test_kucoin_provider_fetch_normalizes_reverse_order_and_derives_close_time():
    start = BASE_START
    rows = _kucoin_raw_page(start, 3)
    session = FakeSession([FakeResponse({"code": "200000", "data": rows})])
    provider = KuCoinPublicSpotKlinesProvider(session=session)

    payload = provider.fetch_klines("BTCUSDT", "1h", limit=1500, start_time=int(start.timestamp() * 1000), end_time=int((start + 2 * ONE_HOUR + ONE_MS).timestamp() * 1000))

    assert session.calls[0]["url"] == KUCOIN_ENDPOINT
    assert session.calls[0]["params"]["symbol"] == "BTC-USDT"
    assert session.calls[0]["params"]["type"] == "1hour"
    assert payload[0][0] < payload[1][0] < payload[2][0]
    assert payload[0][6] == payload[0][0] + int(ONE_HOUR.total_seconds() * 1000) - 1
    assert payload[0][1:6] == [rows[-1][1], rows[-1][3], rows[-1][4], rows[-1][2], rows[-1][5]]
    assert payload[0][6] == payload[0][0] + int(ONE_HOUR.total_seconds() * 1000) - 1


def test_prepare_historical_dataset_kucoin_round_trip_preserves_provider_qualification(tmp_path, monkeypatch):
    pages = [_kucoin_raw_page(BASE_START, 12)]
    CountingKuCoinProvider.reset(pages)
    monkeypatch.setattr(historical, "KuCoinPublicSpotKlinesProvider", CountingKuCoinProvider)
    output = tmp_path / "kucoin-historical-dataset.json"

    result = prepare_historical_dataset_kucoin(
        output_file=output,
        symbol="BTCUSDT",
        interval="1h",
        requested_start_utc=BASE_START,
        requested_end_utc=BASE_START + 11 * ONE_HOUR + ONE_HOUR - ONE_MS,
        page_size=1500,
        max_pages=4,
    )

    assert result["reused"] is False
    assert CountingKuCoinProvider.instantiations == 1
    assert CountingKuCoinProvider.qualification_calls == 1
    assert CountingKuCoinProvider.fetch_calls == 1
    assert output.exists()

    dataset = load_historical_dataset_file(output)
    assert dataset.manifest.provider_qualification == _kucoin_qualification()
    assert dataset.manifest.provider_qualification.as_dict()["external_symbol"] == "BTC-USDT"
    assert dataset.manifest.provider_qualification.as_dict()["close_time_rule"] == "open_time + 1h - 1ms"

    status = status_historical_dataset(input_file=output)
    verify = verify_historical_dataset_file(input_file=output)
    assert status["provider_qualification"] == _kucoin_qualification().as_dict()
    assert verify["provider_qualification"] == _kucoin_qualification().as_dict()

@pytest.mark.parametrize(
    ("symbol", "external_symbol"),
    [
        ("ETHUSDT", "ETH-USDT"),
        ("SOLUSDT", "SOL-USDT"),
        ("UNIUSDT", "UNI-USDT"),
    ],
)
def test_kucoin_prepare_historical_dataset_supports_all_whitelisted_symbols(tmp_path, monkeypatch, symbol, external_symbol):
    pages = [_kucoin_raw_page(BASE_START, 12)]
    CountingKuCoinProvider.reset(pages)
    monkeypatch.setattr(historical, "KuCoinPublicSpotKlinesProvider", CountingKuCoinProvider)
    output = tmp_path / f"kucoin-{symbol.lower()}.json"

    result = prepare_historical_dataset_kucoin(
        output_file=output,
        symbol=symbol,
        interval="1h",
        requested_start_utc=BASE_START,
        requested_end_utc=BASE_START + 11 * ONE_HOUR + ONE_HOUR - ONE_MS,
        page_size=1500,
        max_pages=4,
    )

    assert result["reused"] is False
    assert CountingKuCoinProvider.instantiations == 1
    assert CountingKuCoinProvider.qualification_calls == 1
    assert CountingKuCoinProvider.fetch_calls == 1
    dataset = load_historical_dataset_file(output)
    assert dataset.manifest.provider_qualification == _kucoin_qualification(symbol=symbol)
    assert dataset.manifest.provider_qualification.external_symbol == external_symbol


class BoundaryBinanceProvider(historical.BinancePublicKlinesProvider):
    instantiations = 0
    qualification_calls = 0
    fetch_calls = 0
    calls: list[dict[str, int | None]] = []
    responses: list[dict[str, Any]] = []

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

    def fetch_klines(self, symbol: str, interval: str, limit: int = 1000, *, start_time=None, end_time=None):
        type(self).fetch_calls += 1
        type(self).calls.append({"start_time": start_time, "end_time": end_time, "limit": limit})
        if not self._responses:
            raise AssertionError("unexpected extra historical fetch")
        expected = self._responses.pop(0)
        if start_time != expected["start_time"] or end_time != expected["end_time"]:
            raise AssertionError(f"unexpected Binance page bounds: {start_time!r}..{end_time!r}")
        return expected["payload"]



def test_prepare_historical_dataset_kucoin_pages_with_exact_1600_candle_boundaries(tmp_path, monkeypatch):
    requested_start = BASE_START
    requested_end = requested_start + 1600 * ONE_HOUR - ONE_MS
    first_page_end = requested_start + 1500 * ONE_HOUR - ONE_MS
    second_start = requested_start + 1500 * ONE_HOUR
    responses = [
        {
            "start_time": int(requested_start.timestamp() * 1000),
            "end_time": int(first_page_end.timestamp() * 1000),
            "payload": _kucoin_normalized_page(requested_start, 1500),
        },
        {
            "start_time": int(second_start.timestamp() * 1000),
            "end_time": int(requested_end.timestamp() * 1000),
            "payload": _kucoin_normalized_page(second_start, 100, base=5000),
        },
    ]
    BoundaryKuCoinProvider.reset(responses)
    monkeypatch.setattr(historical, "KuCoinPublicSpotKlinesProvider", BoundaryKuCoinProvider)
    output = tmp_path / "kucoin-1600.json"

    result = prepare_historical_dataset_kucoin(
        output_file=output,
        symbol="BTCUSDT",
        interval="1h",
        requested_start_utc=requested_start,
        requested_end_utc=requested_end,
        page_size=1500,
        max_pages=2,
    )

    assert result["reused"] is False
    assert result["page_count"] == 2
    assert result["candle_count"] == 1600
    assert BoundaryKuCoinProvider.instantiations == 1
    assert BoundaryKuCoinProvider.qualification_calls == 1
    assert BoundaryKuCoinProvider.fetch_calls == 2
    assert len(BoundaryKuCoinProvider.calls) == 2
    assert BoundaryKuCoinProvider.calls[0]["start_time"] == int(requested_start.timestamp() * 1000)
    assert BoundaryKuCoinProvider.calls[0]["end_time"] == int(first_page_end.timestamp() * 1000)
    assert BoundaryKuCoinProvider.calls[1]["start_time"] == int(second_start.timestamp() * 1000)
    assert BoundaryKuCoinProvider.calls[1]["end_time"] == int(requested_end.timestamp() * 1000)

    dataset = load_historical_dataset_file(output)
    assert len(dataset.candles) == 1600
    assert dataset.manifest.page_count == 2
    assert dataset.manifest.candle_count == 1600
    assert dataset.manifest.provider_qualification == _kucoin_qualification()
    assert dataset.candles[0].open_time == requested_start
    assert dataset.candles[-1].close_time == requested_end

    status = status_historical_dataset(input_file=output)
    verify = verify_historical_dataset_file(input_file=output)
    assert status["provider_qualification"] == _kucoin_qualification().as_dict()
    assert verify["provider_qualification"] == _kucoin_qualification().as_dict()


def test_prepare_historical_dataset_binance_pages_with_exact_1600_candle_boundaries(tmp_path):
    requested_start = BASE_START
    requested_end = requested_start + 1600 * ONE_HOUR - ONE_MS
    first_page_end = requested_start + 1000 * ONE_HOUR - ONE_MS
    second_start = requested_start + 1000 * ONE_HOUR
    responses = [
        {
            "start_time": int(requested_start.timestamp() * 1000),
            "end_time": int(first_page_end.timestamp() * 1000),
            "payload": [
                [
                    int((requested_start + idx * ONE_HOUR).timestamp() * 1000),
                    str(100 + idx),
                    str(106 + idx),
                    str(96 + idx),
                    str(102 + idx),
                    str(1000 + idx),
                    int((requested_start + idx * ONE_HOUR + ONE_HOUR - ONE_MS).timestamp() * 1000),
                ]
                for idx in range(1000)
            ],
        },
        {
            "start_time": int(second_start.timestamp() * 1000),
            "end_time": int(requested_end.timestamp() * 1000),
            "payload": [
                [
                    int((second_start + idx * ONE_HOUR).timestamp() * 1000),
                    str(200 + idx),
                    str(206 + idx),
                    str(196 + idx),
                    str(202 + idx),
                    str(2000 + idx),
                    int((second_start + idx * ONE_HOUR + ONE_HOUR - ONE_MS).timestamp() * 1000),
                ]
                for idx in range(600)
            ],
        },
    ]
    BoundaryBinanceProvider.reset(responses)
    output = tmp_path / "binance-1600.json"

    result = historical.prepare_historical_dataset(
        output_file=output,
        provider=BoundaryBinanceProvider(),
        symbol="BTCUSDT",
        interval="1h",
        requested_start_utc=requested_start,
        requested_end_utc=requested_end,
        page_size=1000,
        max_pages=2,
    )

    assert result["reused"] is False
    assert result["page_count"] == 2
    assert result["candle_count"] == 1600
    assert BoundaryBinanceProvider.instantiations == 1
    assert BoundaryBinanceProvider.qualification_calls == 1
    assert BoundaryBinanceProvider.fetch_calls == 2
    assert len(BoundaryBinanceProvider.calls) == 2
    assert BoundaryBinanceProvider.calls[0]["start_time"] == int(requested_start.timestamp() * 1000)
    assert BoundaryBinanceProvider.calls[0]["end_time"] == int(first_page_end.timestamp() * 1000)
    assert BoundaryBinanceProvider.calls[1]["start_time"] == int(second_start.timestamp() * 1000)
    assert BoundaryBinanceProvider.calls[1]["end_time"] == int(requested_end.timestamp() * 1000)

    dataset = load_historical_dataset_file(output)
    assert len(dataset.candles) == 1600
    assert dataset.manifest.page_count == 2
    assert dataset.candles[0].open_time == requested_start
    assert dataset.candles[-1].close_time == requested_end


def test_prepare_historical_dataset_kucoin_rejects_future_end_before_network(tmp_path, monkeypatch):
    class NoFetchProvider(CountingKuCoinProvider):
        def fetch_klines(self, *args, **kwargs):
            raise AssertionError("network must not be reached")

    NoFetchProvider.reset([_kucoin_raw_page(BASE_START, 2)])
    monkeypatch.setattr(historical, "KuCoinPublicSpotKlinesProvider", NoFetchProvider)
    future_end = datetime.now(timezone.utc) + timedelta(days=1)

    with pytest.raises(HistoricalDataValidationError, match="must not be in the future"):
        prepare_historical_dataset_kucoin(
            output_file=tmp_path / "future.json",
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=future_end,
            page_size=1500,
            max_pages=4,
        )
    assert NoFetchProvider.fetch_calls == 0


@pytest.mark.parametrize(
    ("pages", "match"),
    [
        ([_kucoin_raw_page(BASE_START, 1), _kucoin_raw_page(BASE_START, 1)], "Duplicate candle detected between pages|no progress"),
        ([_kucoin_raw_page(BASE_START, 1), _kucoin_raw_page(BASE_START + 2 * ONE_HOUR, 1, base=500)], "Gap detected between pages"),
        ([{"code": "200000", "data": None}], "Empty or malformed response payload|Malformed payload"),
    ],
)
def test_prepare_historical_dataset_kucoin_rejects_gap_duplicate_and_malformed(tmp_path, monkeypatch, pages, match):
    class StaticProvider(CountingKuCoinProvider):
        pass

    StaticProvider.reset(pages)
    monkeypatch.setattr(historical, "KuCoinPublicSpotKlinesProvider", StaticProvider)
    requested_end = BASE_START + (ONE_HOUR - ONE_MS if "malformed" in match.lower() else 3 * ONE_HOUR - ONE_MS)
    with pytest.raises(HistoricalDataValidationError, match=match):
        prepare_historical_dataset_kucoin(
            output_file=tmp_path / "invalid.json",
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=requested_end,
            page_size=1500,
            max_pages=4,
        )


def test_prepare_historical_dataset_kucoin_rejects_bounds_mismatch(tmp_path, monkeypatch):
    class StaticProvider(CountingKuCoinProvider):
        pass

    StaticProvider.reset([_kucoin_raw_page(BASE_START, 2)])
    monkeypatch.setattr(historical, "KuCoinPublicSpotKlinesProvider", StaticProvider)
    with pytest.raises(HistoricalDataValidationError, match="Historical page exceeds requested_end_utc"):
        prepare_historical_dataset_kucoin(
            output_file=tmp_path / "bounds.json",
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=BASE_START + ONE_HOUR - ONE_MS,
            page_size=1500,
            max_pages=4,
        )


def test_kucoin_and_binance_manifest_hashes_differ_for_same_candles():
    candles_binance = tuple(
        Candle.from_dict(
            {
                "open_time": BASE_START + idx * ONE_HOUR,
                "close_time": BASE_START + idx * ONE_HOUR + ONE_HOUR - ONE_MS,
                "open": str(100 + idx),
                "high": str(106 + idx),
                "low": str(96 + idx),
                "close": str(102 + idx),
                "volume": str(1000 + idx),
                "symbol": "BTCUSDT",
                "interval": "1h",
                "source": DataSource.BINANCE,
            }
        )
        for idx in range(3)
    )
    candles_kucoin = tuple(
        Candle.from_dict({**candle.to_dict(), "source": DataSource.KUCOIN}) for candle in candles_binance
    )
    binance_request = HistoricalDatasetRequest(
        provider="binance.public.klines",
        provider_qualification=HistoricalProviderQualification.binance_public_spot(symbol="BTCUSDT", interval="1h"),
        endpoint="https://api.binance.com/api/v3/klines",
        symbol="BTCUSDT",
        interval="1h",
        requested_start_utc=candles_binance[0].open_time,
        requested_end_utc=candles_binance[-1].close_time,
        page_size=1000,
        closed_candles_only=True,
    )
    kucoin_request = HistoricalDatasetRequest(
        provider="kucoin.public.klines",
        provider_qualification=_kucoin_qualification(),
        endpoint=KUCOIN_ENDPOINT,
        symbol="BTCUSDT",
        interval="1h",
        requested_start_utc=candles_kucoin[0].open_time,
        requested_end_utc=candles_kucoin[-1].close_time,
        page_size=1500,
        closed_candles_only=True,
    )
    binance_manifest = build_historical_manifest(
        request=binance_request,
        effective_start_utc=candles_binance[0].open_time,
        effective_end_utc=candles_binance[-1].close_time,
        created_at_utc=candles_binance[-1].close_time + timedelta(days=1),
        candle_count=len(candles_binance),
        page_count=1,
        gap_count=0,
        duplicate_count=0,
        content_hash=historical_content_hash(candles_binance),
    )
    kucoin_manifest = build_historical_manifest(
        request=kucoin_request,
        effective_start_utc=candles_kucoin[0].open_time,
        effective_end_utc=candles_kucoin[-1].close_time,
        created_at_utc=candles_kucoin[-1].close_time + timedelta(days=1),
        candle_count=len(candles_kucoin),
        page_count=1,
        gap_count=0,
        duplicate_count=0,
        content_hash=historical_content_hash(candles_kucoin),
    )
    assert historical_content_hash(candles_binance) != historical_content_hash(candles_kucoin)
    assert binance_manifest.content_hash != kucoin_manifest.content_hash
    assert binance_manifest.manifest_hash != kucoin_manifest.manifest_hash
    assert binance_manifest.provider_qualification.qualification_hash != kucoin_manifest.provider_qualification.qualification_hash


def test_kucoin_dataset_tampering_with_provider_qualification_and_close_time_rule_is_rejected(tmp_path):
    path, _ = _kucoin_dataset(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["manifest"]["provider_qualification"]["exchange"] = "binance"
    payload["manifest"]["provider_qualification"]["close_time_rule"] = "open_time + 1h"
    payload["manifest"]["provider_qualification"]["external_symbol"] = "BTC-USDT-ALT"
    payload["manifest"]["provider_qualification"]["symbol"] = "BTCUSDT"
    payload["manifest"]["provider_qualification"]["interval"] = "1h"
    _recompute_dataset_payload_hashes(payload)
    tampered = tmp_path / "tampered-kucoin.json"
    tampered.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    with pytest.raises((HistoricalDataValidationError, HistoricalDataIntegrityError), match="provider qualification mismatch|provider qualification provider_id must match provider|Historical dataset payload mismatch"):
        load_historical_dataset_file(tampered)


def test_kucoin_history_help_exposes_explicit_subcommand_and_no_provider_flag():
    parser = build_parser()
    history_action = next(action for action in parser._actions if getattr(action, "dest", None) == "command")
    history_parser = history_action.choices["history"]
    help_text = history_parser.format_help()
    assert "prepare-kucoin" in help_text
    assert "--provider" not in help_text
    args = parser.parse_args(["history", "prepare-kucoin", "--symbol", "BTCUSDT", "--interval", "1h", "--start-utc", "2024-01-01T00:00:00Z", "--end-utc", "2024-01-01T01:00:00Z", "--output", "out.json"])
    assert args.history_command == "prepare-kucoin"
