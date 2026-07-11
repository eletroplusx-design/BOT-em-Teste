from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import inspect
import time

import pytest

from domain import (
    Candle,
    DataSource,
    Direction,
    DomainValidationError,
    Fill,
    MarketSnapshot,
    OrderStatus,
    PaperOrder,
    Position,
    PositionStatus,
    RiskDecision,
    Signal,
    TradeIntent,
    TradeResult,
    TradeResultStatus,
    TradingMode,
    serialize_value,
)


UTC = timezone.utc


def dt(hour: int, minute: int = 0):
    return datetime(2026, 7, 10, hour, minute, tzinfo=UTC)


def test_candle_and_snapshot_roundtrip():
    candle = Candle.from_dict(
        {
            "open_time": "2026-07-10T12:00:00Z",
            "close_time": "2026-07-10T13:00:00Z",
            "open": "100.50",
            "high": "110.25",
            "low": "95.10",
            "close": "105.75",
            "volume": "1234.5",
            "symbol": "SOLUSDT",
            "interval": "1h",
            "source": "BINANCE",
        }
    )
    assert candle.open == Decimal("100.50")
    payload = candle.to_dict()
    rebuilt = Candle.from_dict(payload)
    assert rebuilt == candle

    snapshot = MarketSnapshot.from_dict(
        {
            "symbol": "SOLUSDT",
            "timestamp": "2026-07-10T13:00:00Z",
            "current_price": "105.75",
            "source": "BINANCE",
            "candle": payload,
            "regime": "BULL",
        }
    )
    assert snapshot.candle.symbol == snapshot.symbol
    assert snapshot.to_dict()["current_price"] == "105.75"
    assert MarketSnapshot.from_dict(snapshot.to_dict()) == snapshot


def test_signal_roundtrip_and_price_coherence():
    signal = Signal.from_dict(
        {
            "symbol": "BTCUSDT",
            "direction": "COMPRA",
            "entry": "100",
            "stop_loss": "95",
            "take_profit": "110",
            "rr": "2.0",
            "timestamp": "2026-07-10T12:00:00Z",
            "source": "BINANCE",
            "score": "8.5",
            "regime": "BULL",
            "reason": "ok",
            "strategy_version": "v2_risk_safe",
        }
    )
    assert signal.direction == Direction.COMPRA
    assert signal.to_dict()["direction"] == "COMPRA"
    assert Signal.from_dict(signal.to_dict()) == signal


@pytest.mark.parametrize(
    "payload",
    [
        {"symbol": "BTCUSDT", "direction": "COMPRA", "entry": "100", "stop_loss": "105", "take_profit": "90", "rr": "2", "timestamp": "2026-07-10T12:00:00Z", "source": "BINANCE"},
        {"symbol": "BTCUSDT", "direction": "VENDA", "entry": "100", "stop_loss": "95", "take_profit": "110", "rr": "2", "timestamp": "2026-07-10T12:00:00Z", "source": "BINANCE"},
    ],
)
def test_signal_rejeita_stop_take_invertidos(payload):
    with pytest.raises(DomainValidationError):
        Signal.from_dict(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", None),
        ("symbol", ""),
        ("direction", None),
        ("direction", ""),
    ],
)
def test_signal_rejeita_campos_obrigatorios(field, value):
    payload = {
        "symbol": "BTCUSDT",
        "direction": "COMPRA",
        "entry": "100",
        "stop_loss": "95",
        "take_profit": "110",
        "rr": "2",
        "timestamp": "2026-07-10T12:00:00Z",
        "source": "BINANCE",
    }
    payload[field] = value
    with pytest.raises(DomainValidationError):
        Signal.from_dict(payload)


@pytest.mark.parametrize(
    "value",
    [False, "false", 0, 1],
)
def test_trade_models_rejeitam_modo_nao_paper(value):
    base = {
        "symbol": "BTCUSDT",
        "direction": "COMPRA",
        "entry": "100",
        "stop_loss": "95",
        "take_profit": "110",
        "quantity": "1",
        "risk_amount": "10",
        "created_at": "2026-07-10T12:00:00Z",
        "source": "PAPER",
        "paper": True,
        "trading_mode": TradingMode.PAPER,
    }
    for model in (TradeIntent, PaperOrder, Position, TradeResult):
        payload = dict(base)
        if model is PaperOrder:
            payload.update({"status": "open", "opened_at": "2026-07-10T12:00:00Z", "order_id": 1})
        elif model is Position:
            payload.update({"status": "open", "opened_at": "2026-07-10T12:00:00Z", "unrealized_pnl": "0"})
        elif model is TradeResult:
            payload.update(
                {
                    "pnl_percent": "1",
                    "pnl_reais": "1",
                    "status": TradeResultStatus.CLOSED,
                    "reason": "ok",
                    "opened_at": "2026-07-10T12:00:00Z",
                    "closed_at": "2026-07-10T12:30:00Z",
                }
            )
        payload["paper"] = value
        with pytest.raises(DomainValidationError):
            model.from_dict(payload)


def test_fill_rejeita_is_real_true():
    with pytest.raises(DomainValidationError):
        Fill.from_dict(
            {
                "price": "100",
                "quantity": "1",
                "filled_at": "2026-07-10T12:00:00Z",
                "fee": "0.1",
                "source": "PAPER",
                "is_real": True,
            }
        )


@pytest.mark.parametrize("value", ["false", "true", 0, 1, "0", "1"])
def test_risk_decision_bool_parser_rejeita_textos_e_numeros(value):
    payload = {
        "allowed": value,
        "reason": "blocked",
        "blocked_by": "RISK",
        "capital": "27",
        "risk_percent": "0.5",
        "exposure": "5",
        "timestamp": "2026-07-10T12:00:00Z",
        "exchange_info_ok": True,
    }
    with pytest.raises(DomainValidationError):
        RiskDecision.from_dict(payload)


def test_risk_decision_accepta_bool_real():
    decision = RiskDecision.from_dict(
        {
            "allowed": False,
            "reason": "blocked",
            "blocked_by": "RISK",
            "capital": "27",
            "risk_percent": "0.5",
            "exposure": "5",
            "timestamp": "2026-07-10T12:00:00Z",
            "exchange_info_ok": False,
        }
    )
    assert decision.allowed is False
    assert decision.exchange_info_ok is False
    assert RiskDecision.from_dict(decision.to_dict()) == decision


def test_risk_decision_nao_pode_aprovar_sem_exchange_info():
    with pytest.raises(DomainValidationError):
        RiskDecision.from_dict(
            {
                "allowed": True,
                "reason": "blocked",
                "blocked_by": "RISK",
                "capital": "27",
                "risk_percent": "0.5",
                "exposure": "5",
                "timestamp": "2026-07-10T12:00:00Z",
                "exchange_info_ok": False,
            }
        )


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2026, 7, 10, 12, 0),
        "2026-07-10T12:00:00",
        "2026-07-10",
    ],
)
def test_datetime_sem_timezone_rejeitado(timestamp):
    payload = {
        "symbol": "BTCUSDT",
        "direction": "COMPRA",
        "entry": "100",
        "stop_loss": "95",
        "take_profit": "110",
        "rr": "2",
        "timestamp": timestamp,
        "source": "BINANCE",
    }
    with pytest.raises(DomainValidationError):
        Signal.from_dict(payload)


@pytest.mark.parametrize("bad_value", ["NaN", "Infinity", "-Infinity"])
def test_numeric_values_invalidas_rejeitadas(bad_value):
    payload = {
        "symbol": "BTCUSDT",
        "direction": "COMPRA",
        "entry": bad_value,
        "stop_loss": "95",
        "take_profit": "110",
        "rr": "2",
        "timestamp": "2026-07-10T12:00:00Z",
        "source": "BINANCE",
    }
    with pytest.raises(DomainValidationError):
        Signal.from_dict(payload)


def test_decimals_roundtrip_and_imutabilidade():
    intent = TradeIntent.from_dict(
        {
            "symbol": "SOLUSDT",
            "direction": "COMPRA",
            "entry": "100.10",
            "stop_loss": "99.00",
            "take_profit": "105.00",
            "quantity": "1.25",
            "risk_amount": "2.50",
            "created_at": "2026-07-10T12:00:00Z",
            "source": "PAPER",
            "paper": True,
        }
    )
    payload = intent.to_dict()
    rebuilt = TradeIntent.from_dict(payload)
    assert rebuilt == intent
    assert payload["entry"] == "100.10"
    with pytest.raises(FrozenInstanceError):
        intent.entry = Decimal("101")


def test_serializacao_datetime_canonica_em_utc():
    original_tz = os.environ.get("TZ")
    had_tzset = hasattr(time, "tzset")
    try:
        os.environ["TZ"] = "America/Sao_Paulo"
        if had_tzset:
            time.tzset()
        dt_utc = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        assert serialize_value(dt_utc) == "2026-01-01T00:00:00Z"
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        if had_tzset:
            time.tzset()


def test_trade_result_closed_at_validation():
    with pytest.raises(DomainValidationError):
        TradeResult.from_dict(
            {
                "symbol": "BTCUSDT",
                "direction": "VENDA",
                "entry": "100",
                "exit_price": "95",
                "quantity": "1",
                "pnl_percent": "-5",
                "pnl_reais": "-5",
                "status": "closed",
                "reason": "ok",
                "opened_at": "2026-07-10T12:00:00Z",
                "closed_at": "2026-07-10T11:59:00Z",
                "source": "PAPER",
                "paper": True,
            }
        )


def test_import_sem_dependencias_externas():
    import domain

    source = inspect.getsource(domain)
    for token in ("requests", "httpx", "telegram", "OpenAI", "create_order", "subprocess"):
        assert token not in source
