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


def _payload_candles(start_ms: int, step_ms: int = 3600000, count: int = 2, close_delta: int = 3599999):
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


def _monthly_payload(starts: list[datetime]):
    payload = []
    for idx, open_time in enumerate(starts):
        if open_time.tzinfo is None:
            raise ValueError("open_time must be timezone-aware")
        year = open_time.year + (1 if open_time.month == 12 else 0)
        month = 1 if open_time.month == 12 else open_time.month + 1
        next_month = datetime(year, month, 1, tzinfo=timezone.utc)
        close_time = next_month - timedelta(milliseconds=1)
        base = 200 + idx
        payload.append(
            [
                int(open_time.timestamp() * 1000),
                str(base),
                str(base + 5),
                str(base - 2),
                str(base + 1),
                str(1000 + idx),
                int(close_time.timestamp() * 1000),
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
    session.get.return_value = FakeResponse(status_code=400, payload=[])
    provider = BinancePublicKlinesProvider(session=session)
    with pytest.raises(MarketDataHTTPError):
        provider.fetch_klines("BTCUSDT", "1h", 2)

    session.get.return_value = FakeResponse(status_code=429, payload=[])
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


def test_validate_klines_payload_interval_horario_fechamento_correto():
    candles = validate_klines_payload(
        _payload_candles(1704067200000, count=2),
        symbol="BTCUSDT",
        interval="1h",
        now=datetime(2024, 1, 1, 4, 30, tzinfo=timezone.utc),
    )
    assert candles[-1].close_time == datetime(2024, 1, 1, 1, 59, 59, 999000, tzinfo=timezone.utc)


def test_validate_klines_payload_interval_horario_rejeita_duracao_de_um_minuto():
    payload = _payload_candles(1704067200000, count=2, close_delta=60000)
    with pytest.raises(MarketDataValidationError, match="Candle duration does not match"):
        validate_klines_payload(payload, symbol="BTCUSDT", interval="1h", now=datetime(2024, 1, 1, 4, 30, tzinfo=timezone.utc))


def test_validate_klines_payload_interval_horario_rejeita_fechamento_alem_do_intervalo():
    payload = _payload_candles(1704067200000, count=1)
    payload[0][6] = payload[0][6] + 1000
    with pytest.raises(MarketDataValidationError, match="Candle duration does not match"):
        validate_klines_payload(payload, symbol="BTCUSDT", interval="1h", now=datetime(2024, 1, 1, 3, 30, tzinfo=timezone.utc))


def test_validate_klines_payload_interval_horario_rejeita_sobreposicao():
    payload = _payload_candles(1704067200000, count=2)
    payload[0][6] = payload[0][6] + 1000
    with pytest.raises(MarketDataValidationError, match="Candle duration does not match"):
        validate_klines_payload(payload, symbol="BTCUSDT", interval="1h", now=datetime(2024, 1, 1, 4, 30, tzinfo=timezone.utc))


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
    with pytest.raises(MarketDataValidationError):
        validate_klines_payload(candles, symbol="BTCUSDT", interval="1h", now=datetime(2024, 1, 1, 3, 30))


@pytest.mark.parametrize("bad_value", ["invalid", None, 10**30])
def test_row_to_candle_rejeita_timestamps_invalidos(bad_value):
    from market_data import validation as validation_module

    row = [bad_value, "100", "105", "98", "101", "1000", bad_value, 0, 0, 0, 0, 0]
    with pytest.raises(MarketDataValidationError, match="Invalid timestamp in kline payload"):
        validation_module._row_to_candle(row, "BTCUSDT", "1h")


def test_service_ignora_candle_em_formacao_e_snapshot_usa_ultimo_fechado(monkeypatch):
    from market_data import service as service_module
    from market_data import validation as validation_module

    class FrozenDateTime(datetime):
        current = datetime(2024, 1, 1, 3, 30, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is not None else cls.current.replace(tzinfo=None)

    monkeypatch.setattr(service_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(validation_module, "datetime", FrozenDateTime)

    payload = _payload_candles(int(datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc).timestamp() * 1000), count=3)
    payload[2][6] = int((FrozenDateTime.current + timedelta(minutes=30)).timestamp() * 1000)
    session = MagicMock()
    session.get.return_value = FakeResponse(payload=payload)
    provider = BinancePublicKlinesProvider(session=session)
    service = TrustedMarketDataService(provider=provider, cache=MarketDataCache(ttl_seconds=60), ttl_seconds=60, max_age_seconds=999999)

    package = service.fetch("BTCUSDT", "1h", 2)

    assert len(package.candles) == 2
    assert package.snapshot.timestamp == package.candles[-1].close_time
    assert package.candles[-1].close_time <= FrozenDateTime.current


def test_service_bloqueia_quando_todos_os_candles_estao_abertos(monkeypatch):
    from market_data import service as service_module
    from market_data import validation as validation_module

    class FrozenDateTime(datetime):
        current = datetime(2024, 1, 1, 3, 30, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is not None else cls.current.replace(tzinfo=None)

    monkeypatch.setattr(service_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(validation_module, "datetime", FrozenDateTime)

    payload = _payload_candles(int(datetime(2024, 1, 1, 3, 0, tzinfo=timezone.utc).timestamp() * 1000), count=1, close_delta=3600000)
    session = MagicMock()
    session.get.return_value = FakeResponse(payload=payload)
    provider = BinancePublicKlinesProvider(session=session)
    service = TrustedMarketDataService(provider=provider, cache=MarketDataCache(ttl_seconds=60), ttl_seconds=60, max_age_seconds=999999)

    with pytest.raises(MarketDataValidationError, match="No closed candles available"):
        service.fetch("BTCUSDT", "1h", 1)


def test_validate_klines_payload_rejeita_duplicado():
    payload = _payload_candles(1704067200000)
    payload.append(payload[0][:])
    with pytest.raises(MarketDataValidationError):
        validate_klines_payload(payload, symbol="BTCUSDT", interval="1h", now=datetime(2024, 1, 1, 5, 30, tzinfo=timezone.utc))


def test_service_cache_valid_expired_and_isolation(monkeypatch):
    from market_data import service as service_module
    from market_data import validation as validation_module

    class FrozenDateTime(datetime):
        current = datetime(2024, 1, 1, 3, 30, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is not None else cls.current.replace(tzinfo=None)

    monkeypatch.setattr(service_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(validation_module, "datetime", FrozenDateTime)

    cache = MarketDataCache(ttl_seconds=1)
    session = MagicMock()
    first_payload = _payload_candles(int(datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc).timestamp() * 1000), count=3)
    second_payload = _payload_candles(int(datetime(2024, 1, 1, 3, 0, tzinfo=timezone.utc).timestamp() * 1000), count=3)
    third_payload = _payload_candles(int(datetime(2024, 1, 1, 3, 0, tzinfo=timezone.utc).timestamp() * 1000), count=3)
    session.get.side_effect = [FakeResponse(payload=first_payload), FakeResponse(payload=second_payload), FakeResponse(payload=third_payload)]
    provider = BinancePublicKlinesProvider(session=session)
    service = TrustedMarketDataService(provider=provider, cache=cache, ttl_seconds=1, max_age_seconds=3600)

    first = service.fetch("BTCUSDT", "1h", 2)
    assert first.cache_status == "miss"
    assert service.cache.status("BTCUSDT", "1h") == "hit"

    FrozenDateTime.current = FrozenDateTime.current + timedelta(hours=2)
    second = service.fetch("BTCUSDT", "1h", 2)
    assert second.cache_status == "miss"
    assert session.get.call_count == 2

    assert service.cache.status("BTCUSDT", "15m") == "miss"
    assert service.cache.peek("BTCUSDT", "15m") is None

    other = service.fetch("ETHUSDT", "1h", 2)
    assert other.symbol == "ETHUSDT"
    assert service.cache.status("ETHUSDT", "1h") == "hit"
    assert session.get.call_count == 3

    cached = service.cache.peek("BTCUSDT", "1h")
    assert cached is not None
    expired = replace(cached, stored_at=datetime.now(timezone.utc) - timedelta(seconds=5))
    service.cache._entries[("BTCUSDT", "1h")] = expired
    assert service.cache.status("BTCUSDT", "1h") == "expired"
    assert service.cache.get("BTCUSDT", "1h") is None


def test_service_cache_respeita_limit_e_devolve_mais_recente():
    cache = MarketDataCache(ttl_seconds=60)
    provider = MagicMock()
    payload_500 = _payload_candles(1704067200000, count=500)
    provider.fetch_klines.return_value = payload_500
    service = TrustedMarketDataService(provider=provider, cache=cache, ttl_seconds=60, max_age_seconds=999999999)

    seeded = validate_klines_payload(payload_500[:2], symbol="BTCUSDT", interval="1h", now=datetime(2024, 1, 1, 3, 30, tzinfo=timezone.utc))
    cache.set("BTCUSDT", "1h", tuple(seeded), service._build_package(seeded, "BTCUSDT", "1h").snapshot)

    first = service.fetch("BTCUSDT", "1h", 500)
    assert provider.fetch_klines.call_count == 1
    assert len(first.candles) == 500

    second = service.fetch("BTCUSDT", "1h", 2)
    assert provider.fetch_klines.call_count == 1
    assert len(second.candles) == 2
    assert second.candles[-1] == first.candles[-1]


def test_service_pede_um_candle_extra_e_ignora_candle_em_formacao(monkeypatch):
    from market_data import service as service_module
    from market_data import validation as validation_module

    class FrozenDateTime(datetime):
        current = datetime(2024, 2, 1, 12, 30, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is not None else cls.current.replace(tzinfo=None)

    monkeypatch.setattr(service_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(validation_module, "datetime", FrozenDateTime)

    start_ms = int((FrozenDateTime.current - timedelta(hours=501)).timestamp() * 1000)
    payload = _payload_candles(start_ms, count=501)
    payload[-1][6] = int((FrozenDateTime.current + timedelta(minutes=30)).timestamp() * 1000)

    provider = MagicMock()
    provider.fetch_klines.return_value = payload
    service = TrustedMarketDataService(provider=provider, cache=MarketDataCache(), ttl_seconds=60, max_age_seconds=999999999)

    package = service.fetch("BTCUSDT", "1h", 500)

    assert provider.fetch_klines.call_args.args[2] == 501
    assert len(package.candles) == 500
    assert package.candles[-1].close_time <= FrozenDateTime.current


def test_service_respeita_limit_maximo_da_binance():
    provider = MagicMock()
    payload = _payload_candles(1704067200000, count=1000)
    provider.fetch_klines.return_value = payload
    service = TrustedMarketDataService(provider=provider, cache=MarketDataCache(), ttl_seconds=60, max_age_seconds=999999999)

    package = service.fetch("BTCUSDT", "1h", 1000)

    assert provider.fetch_klines.call_args.args[2] == 1000
    assert len(package.candles) == 1000


@pytest.mark.parametrize(
    "limit",
    [0, -1, 1001, True, False, 1.5, "500"],
)
def test_service_rejeita_limit_invalido_sem_chamar_rede(limit):
    provider = MagicMock()
    service = TrustedMarketDataService(provider=provider, cache=MarketDataCache(), ttl_seconds=60, max_age_seconds=999999)
    with pytest.raises(MarketDataValidationError):
        service.fetch("BTCUSDT", "1h", limit)
    provider.fetch_klines.assert_not_called()


def test_service_expired_data_and_no_silent_reuse(monkeypatch):
    cache = MarketDataCache(ttl_seconds=1)
    session = MagicMock()
    old_ms = int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp() * 1000)
    session.get.return_value = FakeResponse(payload=_payload_candles(old_ms))
    provider = BinancePublicKlinesProvider(session=session)
    service = TrustedMarketDataService(provider=provider, cache=cache, ttl_seconds=1, max_age_seconds=1)
    with pytest.raises(MarketDataExpiredError):
        service.fetch("BTCUSDT", "1h", 2)


def test_validate_klines_payload_interval_mensal_calendar_aware():
    jan = datetime(2024, 1, 1, tzinfo=timezone.utc)
    feb = datetime(2024, 2, 1, tzinfo=timezone.utc)
    mar = datetime(2024, 3, 1, tzinfo=timezone.utc)
    parsed = validate_klines_payload(
        _monthly_payload([jan, feb, mar]),
        symbol="BTCUSDT",
        interval="1M",
        now=datetime(2024, 4, 1, tzinfo=timezone.utc),
    )
    assert [c.open_time for c in parsed] == [jan, feb, mar]


def test_validate_klines_payload_interval_mensal_febrero_marco_ano_comum():
    feb = datetime(2025, 2, 1, tzinfo=timezone.utc)
    mar = datetime(2025, 3, 1, tzinfo=timezone.utc)
    apr = datetime(2025, 4, 1, tzinfo=timezone.utc)
    parsed = validate_klines_payload(
        _monthly_payload([feb, mar, apr]),
        symbol="BTCUSDT",
        interval="1M",
        now=datetime(2025, 5, 1, tzinfo=timezone.utc),
    )
    assert parsed[-1].open_time == apr


def test_validate_klines_payload_interval_mensal_febrero_marco_ano_bissexto():
    feb = datetime(2024, 2, 1, tzinfo=timezone.utc)
    mar = datetime(2024, 3, 1, tzinfo=timezone.utc)
    apr = datetime(2024, 4, 1, tzinfo=timezone.utc)
    parsed = validate_klines_payload(
        _monthly_payload([feb, mar, apr]),
        symbol="BTCUSDT",
        interval="1M",
        now=datetime(2024, 5, 1, tzinfo=timezone.utc),
    )
    assert parsed[0].open_time == feb


def test_validate_klines_payload_interval_mensal_rejeita_lacuna_real():
    jan = datetime(2024, 1, 1, tzinfo=timezone.utc)
    mar = datetime(2024, 3, 1, tzinfo=timezone.utc)
    with pytest.raises(MarketDataValidationError, match="Missing candle detected"):
        validate_klines_payload(
            _monthly_payload([jan, mar]),
            symbol="BTCUSDT",
            interval="1M",
            now=datetime(2024, 4, 1, tzinfo=timezone.utc),
        )


def test_validate_klines_payload_interval_mensal_rejeita_fechamento_antecipado():
    jan = datetime(2024, 1, 1, tzinfo=timezone.utc)
    feb = datetime(2024, 2, 1, tzinfo=timezone.utc)
    payload = _monthly_payload([jan, feb])
    payload[0][6] = int((feb - timedelta(minutes=1)).timestamp() * 1000)
    with pytest.raises(MarketDataValidationError, match="Candle duration does not match"):
        validate_klines_payload(
            payload,
            symbol="BTCUSDT",
            interval="1M",
            now=datetime(2024, 3, 1, tzinfo=timezone.utc),
        )


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
