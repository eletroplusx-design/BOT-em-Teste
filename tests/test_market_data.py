from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from math import inf, nan
from unittest.mock import MagicMock

import pandas as pd
import pytest
import requests

from domain import Candle, DataSource
from market_data import (
    BinancePublicKlinesProvider,
    MarketDataCache,
    MarketDataExpiredError,
    MarketDataHTTPError,
    MarketDataJSONError,
    MarketDataNetworkError,
    MarketDataRateLimitError,
    MarketDataValidationError,
    TrustedMarketDataService,
    candles_to_dataframe,
    validate_klines_payload,
)


def _payload_candles(start_ms: int, step_ms: int = 3600000, count: int = 2, close_delta: int = 60000):
    payload = []
    for idx in range(count):
        open_time = start_ms + idx * step_ms
        close_time = open_time + close_delta
        base = 100 + idx
        payload.append(
            [
                open_time,
                str(base),
                str(base + 5),
                str(base - 2),
                str(base + 1),
                str(1000 + idx),
                close_time,
                0,
                0,
                0,
                0,
                0,
            ]
        )
    return payload


class FakeResponse:
    def __init__(self, *, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


def test_provider_fetch_success_and_no_auth_headers(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeResponse(payload=_payload_candles(1704067200000))

    session = MagicMock()
    session.get.side_effect = fake_get
    provider = BinancePublicKlinesProvider(session=session)
    payload = provider.fetch_klines("BTCUSDT", "1h", 2)

    assert len(payload) == 2
    assert captured["url"].startswith("https://api.binance.com/api/v3/klines")
    assert "headers" not in captured["kwargs"]
    assert "auth" not in captured["kwargs"]
    assert captured["kwargs"]["timeout"] == (5.0, 10.0)
    assert captured["kwargs"]["params"]["symbol"] == "BTCUSDT"


@pytest.mark.parametrize(
    "side_effect,expected",
    [
        (requests.Timeout("timeout"), MarketDataNetworkError),
        (requests.ConnectionError("conn"), MarketDataNetworkError),
    ],
)
def test_provider_network_failures(side_effect, expected):
    session = MagicMock()
    session.get.side_effect = side_effect
    provider = BinancePublicKlinesProvider(session=session)
    with pytest.raises(expected):
        provider.fetch_klines("BTCUSDT", "1h", 2)


def test_provider_http_and_rate_limit_errors():
    session = MagicMock()
    session.get.return_value = FakeResponse(status_code=429, payload=[])
    provider = BinancePublicKlinesProvider(session=session)
    with pytest.raises(MarketDataRateLimitError):
        provider.fetch_klines("BTCUSDT", "1h", 2)

    session.get.return_value = FakeResponse(status_code=500, payload=[])
    with pytest.raises(MarketDataHTTPError):
        provider.fetch_klines("BTCUSDT", "1h", 2)


def test_provider_json_and_payload_errors():
    session = MagicMock()
    session.get.return_value = FakeResponse(payload=None, json_error=ValueError("bad json"))
    provider = BinancePublicKlinesProvider(session=session)
    with pytest.raises(MarketDataJSONError):
        provider.fetch_klines("BTCUSDT", "1h", 2)

    session.get.return_value = FakeResponse(payload={"foo": "bar"})
    with pytest.raises(MarketDataJSONError):
        provider.fetch_klines("BTCUSDT", "1h", 2)


def test_validate_klines_payload_and_dataframe_conversion():
    candles = validate_klines_payload(
        _payload_candles(1704067200000, count=3),
        symbol="BTCUSDT",
        interval="1h",
        now=datetime(2024, 1, 1, 3, 30, tzinfo=timezone.utc),
    )
    assert len(candles) == 3
    assert candles[0].symbol == "BTCUSDT"
    df = candles_to_dataframe(candles)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns[:3]) == ["open_time", "close_time", "datetime"]
    assert df.attrs["fonte_dados"] == "BINANCE"


@pytest.mark.parametrize(
    "payload,exc",
    [
        ([], MarketDataValidationError),
        ([["bad"]], MarketDataValidationError),
    ],
)
def test_validate_klines_payload_rejeita_payload_vazio_malformado_e_duplicado(payload, exc):
    with pytest.raises(exc):
        validate_klines_payload(payload, symbol="BTCUSDT", interval="1h", now=datetime(2024, 1, 1, 3, 30, tzinfo=timezone.utc))


def test_validate_klines_payload_rejeita_ohlc_incoerente_nan_inf_timezone_e_futuro():
    base = _payload_candles(1704067200000)
    bad_high = [row[:] for row in base]
    bad_high[0][2] = "90"
    with pytest.raises(MarketDataValidationError):
        validate_klines_payload(bad_high, symbol="BTCUSDT", interval="1h", now=datetime(2024, 1, 1, 3, 30, tzinfo=timezone.utc))

    bad_nan = [row[:] for row in base]
    bad_nan[0][1] = "NaN"
    with pytest.raises(MarketDataValidationError):
        validate_klines_payload(bad_nan, symbol="BTCUSDT", interval="1h", now=datetime(2024, 1, 1, 3, 30, tzinfo=timezone.utc))

    bad_inf = [row[:] for row in base]
    bad_inf[0][1] = str(inf)
    with pytest.raises(MarketDataValidationError):
        validate_klines_payload(bad_inf, symbol="BTCUSDT", interval="1h", now=datetime(2024, 1, 1, 3, 30, tzinfo=timezone.utc))

    future_payload = _payload_candles(4102444800000)
    with pytest.raises(MarketDataValidationError):
        validate_klines_payload(future_payload, symbol="BTCUSDT", interval="1h", now=datetime(2024, 1, 1, 3, 30, tzinfo=timezone.utc))

    gap_payload = _payload_candles(1704067200000, count=2)
    gap_payload[1][0] += 7200000
    with pytest.raises(MarketDataValidationError):
        validate_klines_payload(gap_payload, symbol="BTCUSDT", interval="1h", now=datetime(2024, 1, 1, 3, 30, tzinfo=timezone.utc))

    out_of_order = _payload_candles(1704067200000, count=2)
    out_of_order[1][0] = out_of_order[0][0] - 3600000
    with pytest.raises(MarketDataValidationError):
        validate_klines_payload(out_of_order, symbol="BTCUSDT", interval="1h", now=datetime(2024, 1, 1, 3, 30, tzinfo=timezone.utc))


def test_validate_klines_payload_rejeita_timestamp_naive():
    candles = _payload_candles(1704067200000)
    parsed = validate_klines_payload(candles, symbol="BTCUSDT", interval="1h", now=datetime(2024, 1, 1, 3, 30, tzinfo=timezone.utc))
    assert parsed[0].open_time.tzinfo == timezone.utc


def test_validate_klines_payload_rejeita_duplicado():
    payload = _payload_candles(1704067200000)
    payload.append(payload[0][:])
    with pytest.raises(MarketDataValidationError):
        validate_klines_payload(payload, symbol="BTCUSDT", interval="1h", now=datetime(2024, 1, 1, 5, 30, tzinfo=timezone.utc))


def test_service_cache_valid_expired_and_isolation(monkeypatch):
    cache = MarketDataCache(ttl_seconds=1)
    session = MagicMock()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    session.get.return_value = FakeResponse(payload=_payload_candles(now_ms - 2 * 3600000))
    provider = BinancePublicKlinesProvider(session=session)
    service = TrustedMarketDataService(provider=provider, cache=cache, ttl_seconds=1, max_age_seconds=999999)

    first = service.fetch("BTCUSDT", "1h", 2)
    assert first.cache_status == "miss"
    assert service.cache.status("BTCUSDT", "1h") == "hit"

    second = service.fetch("BTCUSDT", "1h", 2)
    assert second.cache_status == "hit"
    assert session.get.call_count == 1

    other = service.fetch("ETHUSDT", "1h", 2)
    assert other.symbol == "ETHUSDT"
    assert service.cache.status("ETHUSDT", "1h") == "hit"

    cached = service.cache.peek("BTCUSDT", "1h")
    assert cached is not None
    expired = replace(cached, stored_at=datetime.now(timezone.utc) - timedelta(seconds=5))
    service.cache._entries[("BTCUSDT", "1h")] = expired
    assert service.cache.status("BTCUSDT", "1h") == "expired"
    assert service.cache.get("BTCUSDT", "1h") is None


def test_service_expired_data_and_no_silent_reuse(monkeypatch):
    cache = MarketDataCache(ttl_seconds=1)
    session = MagicMock()
    old_ms = int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp() * 1000)
    session.get.return_value = FakeResponse(payload=_payload_candles(old_ms))
    provider = BinancePublicKlinesProvider(session=session)
    service = TrustedMarketDataService(provider=provider, cache=cache, ttl_seconds=1, max_age_seconds=1)
    with pytest.raises(MarketDataExpiredError):
        service.fetch("BTCUSDT", "1h", 2)


def test_service_rejeita_resposta_vazia(monkeypatch):
    session = MagicMock()
    session.get.return_value = FakeResponse(payload=[])
    provider = BinancePublicKlinesProvider(session=session)
    service = TrustedMarketDataService(provider=provider, cache=MarketDataCache(), ttl_seconds=1, max_age_seconds=999999)
    with pytest.raises(MarketDataValidationError):
        service.fetch("BTCUSDT", "1h", 2)


def test_no_authenticated_calls_or_private_endpoints():
    import inspect
    from market_data import provider as provider_module
    from market_data import service as service_module

    source = inspect.getsource(provider_module) + inspect.getsource(service_module)
    for token in ("create_order", "websocket", "private", "apikey", "api_key", "secret", "order"):
        assert token not in source.lower()
