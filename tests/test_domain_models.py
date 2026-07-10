from datetime import datetime, timezone

import pytest

from domain_models import (
    Candle,
    DomainValidationError,
    Fill,
    MarketSnapshot,
    PaperOrder,
    Position,
    RiskDecision,
    Signal,
    TradeIntent,
    TradeResult,
    coerce_candle,
    coerce_fill,
    coerce_market_snapshot,
    coerce_paper_order,
    coerce_position,
    coerce_risk_decision,
    coerce_signal,
    coerce_trade_intent,
    coerce_trade_result,
    validate_direction,
    validate_symbol,
)


def test_candle_roundtrip_and_aliases():
    candle = Candle.from_mapping(
        {
            "symbol": "solusdt",
            "open_time": "2026-07-10T12:00:00+00:00",
            "open": 100,
            "high": 110,
            "low": 95,
            "close": 105,
            "volume": 1234,
            "timeframe": "1h",
            "source": "binance",
        }
    )
    assert candle.symbol == "SOLUSDT"
    assert candle.to_dict()["timestamp"] == "2026-07-10T12:00:00+00:00"
    assert coerce_candle(candle) is candle
    assert coerce_candle(candle.to_dict()).symbol == "SOLUSDT"


def test_candle_rejeita_valores_impossiveis():
    with pytest.raises(DomainValidationError):
        Candle.from_mapping(
            {
                "symbol": "BTCUSDT",
                "timestamp": "2026-07-10T12:00:00+00:00",
                "open": 100,
                "high": 90,
                "low": 95,
                "close": 97,
                "volume": 10,
            }
        )


def test_market_snapshot_nested_serialization():
    snapshot = MarketSnapshot.from_mapping(
        {
            "symbol": "BTCUSDT",
            "candle": {
                "symbol": "BTCUSDT",
                "timestamp": "2026-07-10T12:00:00+00:00",
                "open": 100,
                "high": 110,
                "low": 95,
                "close": 105,
                "volume": 1234,
            },
            "regime": "bull",
            "adx": 27,
            "rsi": 51,
            "volume_status": "normal",
            "source": "binance",
        }
    )
    payload = snapshot.to_dict()
    assert payload["symbol"] == "BTCUSDT"
    assert payload["candle"]["close"] == 105.0
    assert payload["regime"] == "BULL"
    assert coerce_market_snapshot(payload).symbol == "BTCUSDT"


def test_signal_validation_and_roundtrip():
    signal = Signal.from_mapping(
        {
            "symbol": "BTCUSDT",
            "direcao": "buy",
            "entrada": 100.5,
            "stop": 95.0,
            "take": 115.0,
            "rr": 2.5,
            "score": 8,
            "regime": "bear",
            "timestamp": "2026-07-10T12:00:00+00:00",
            "fonte_dados": "binance",
            "strategy_version": "v2_risk_safe",
            "motivo": "ok",
            "volume_status": "alto",
            "paper": True,
        }
    )
    payload = signal.to_dict()
    assert signal.direction == "COMPRA"
    assert payload["paper"] is True
    assert payload["regime"] == "BEAR"
    assert coerce_signal(payload).symbol == "BTCUSDT"


def test_trade_intent_and_risk_decision_validation():
    signal = Signal.from_mapping(
        {
            "symbol": "SOLUSDT",
            "direction": "COMPRA",
            "entry": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "rr": 2,
            "score": 7,
            "regime": "BULL",
            "timestamp": "2026-07-10T12:00:00+00:00",
        }
    )
    intent = TradeIntent.from_signal(signal, quantity=1.25, risk_amount=3.75, source="paper")
    assert intent.paper is True
    assert intent.quantity == 1.25
    assert coerce_trade_intent(intent.to_dict()).symbol == "SOLUSDT"

    decision = RiskDecision.from_mapping(
        {
            "allowed": False,
            "reason": "blocked",
            "bloqueado_por": "risk",
            "capital": 27,
            "risk_percent": 0.5,
            "exposure": 5,
            "timestamp": "2026-07-10T12:00:00+00:00",
        }
    )
    assert decision.blocked_by == "RISK"
    assert coerce_risk_decision(decision.to_dict()).allowed is False


def test_paper_order_fill_and_position_roundtrip():
    order = PaperOrder.from_mapping(
        {
            "symbol": "BTCUSDT",
            "direcao": "VENDA",
            "entrada": 100,
            "quantidade": 2,
            "stop": 105,
            "take": 90,
            "status": "open",
            "opened_at": "2026-07-10T12:00:00+00:00",
            "fonte_dados": "paper",
            "paper": True,
            "order_id": 42,
        }
    )
    assert order.paper is True
    assert order.direction == "VENDA"
    assert coerce_paper_order(order.to_dict()).order_id == 42

    fill = Fill.from_mapping(
        {
            "order_id": 42,
            "preco": 101,
            "quantidade": 2,
            "timestamp": "2026-07-10T12:05:00+00:00",
            "fee": 0.1,
            "fonte_dados": "paper",
            "is_real": False,
        }
    )
    assert fill.is_real is False
    assert coerce_fill(fill.to_dict()).price == 101.0

    position = Position.from_mapping(
        {
            "symbol": "BTCUSDT",
            "direction": "SHORT",
            "entry": 100,
            "stop_loss": 105,
            "take_profit": 90,
            "quantity": 2,
            "opened_at": "2026-07-10T12:00:00+00:00",
            "status": "open",
            "source": "paper",
            "paper": True,
            "unrealized_pnl": -1.5,
        }
    )
    assert position.direction == "VENDA"
    assert coerce_position(position.to_dict()).symbol == "BTCUSDT"


def test_trade_result_resultado_and_mapping():
    result = TradeResult.from_mapping(
        {
            "symbol": "BTCUSDT",
            "direcao": "COMPRA",
            "entrada": 100,
            "saida": 110,
            "quantidade": 1.5,
            "lucro_percent": 10,
            "lucro_reais": 15,
            "resultado": "closed",
            "motivo_saida": "TAKE_PROFIT",
            "aberto_em": "2026-07-10T12:00:00+00:00",
            "fechado_em": "2026-07-10T13:00:00+00:00",
            "fonte_dados": "paper",
            "paper": True,
            "strategy_version": "v2_risk_safe",
        }
    )
    assert result.resultado == "GANHO"
    assert coerce_trade_result(result.to_dict()).pnl_reais == 15.0


def test_helpers_rejeitam_dados_invalidos():
    with pytest.raises(DomainValidationError):
        validate_symbol(" ")
    with pytest.raises(DomainValidationError):
        validate_direction("foo")
    with pytest.raises(DomainValidationError):
        coerce_signal(
            {
                "symbol": "BTCUSDT",
                "direction": "COMPRA",
                "entry": -1,
                "stop_loss": 95,
                "take_profit": 115,
                "rr": 2,
            }
        )
