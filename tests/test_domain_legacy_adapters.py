from datetime import datetime, timezone
from decimal import Decimal

from domain import (
    DataSource,
    Direction,
    OrderStatus,
    PositionStatus,
    TradeResultStatus,
    legacy_candle_payload,
    legacy_fill_payload,
    legacy_market_snapshot_payload,
    legacy_paper_order_payload,
    legacy_position_payload,
    legacy_risk_decision_payload,
    legacy_signal_payload,
    legacy_trade_intent_payload,
    legacy_trade_result_payload,
    candle_from_legacy_mapping,
    fill_from_legacy_mapping,
    market_snapshot_from_legacy_mapping,
    paper_order_from_legacy_mapping,
    position_from_legacy_mapping,
    risk_decision_from_legacy_mapping,
    signal_from_legacy_mapping,
    trade_intent_from_legacy_mapping,
    trade_result_from_legacy_mapping,
)


def test_legacy_signal_and_roundtrip():
    signal = signal_from_legacy_mapping(
        {
            "direcao": "COMPRA",
            "entrada": 100,
            "stop": 95,
            "take": 110,
            "rr": 2,
            "timestamp": datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
            "fonte_dados": "BINANCE",
            "motivo": "ok",
        },
        default_symbol="SOLUSDT",
    )
    assert signal.symbol == "SOLUSDT"
    assert signal.direction == Direction.COMPRA
    payload = legacy_signal_payload(signal)
    assert payload["direcao"] == "COMPRA"
    assert payload["entrada"] == 100.0


def test_legacy_models_roundtrip_and_payloads():
    intent = trade_intent_from_legacy_mapping(
        {
            "symbol": "BTCUSDT",
            "direcao": "VENDA",
            "entrada": 100,
            "stop_loss": 105,
            "take_profit": 90,
            "quantidade": 1.5,
            "valor_arriscado": 2.5,
            "timestamp": datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
            "fonte_dados": "PAPER",
        }
    )
    assert intent.paper is True
    assert legacy_trade_intent_payload(intent)["quantity"] == 1.5

    order = paper_order_from_legacy_mapping(
        {
            "symbol": "BTCUSDT",
            "direcao": "COMPRA",
            "entrada": 100,
            "quantidade": 1,
            "stop": 95,
            "take": 110,
            "status": "open",
            "opened_at": datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
            "fonte_dados": "PAPER",
            "order_id": 7,
        }
    )
    assert order.status == OrderStatus.OPEN
    assert legacy_paper_order_payload(order)["order_id"] == 7

    position = position_from_legacy_mapping(
        {
            "symbol": "BTCUSDT",
            "direction": "SHORT",
            "entry": 100,
            "stop_loss": 105,
            "take_profit": 90,
            "quantidade": 2,
            "status": "open",
            "opened_at": datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
            "fonte_dados": "PAPER",
            "unrealized_pnl": -1.5,
        }
    )
    assert position.status == PositionStatus.OPEN
    assert legacy_position_payload(position)["unrealized_pnl"] == -1.5

    fill = fill_from_legacy_mapping(
        {
            "preco": 101,
            "quantidade": 2,
            "timestamp": datetime(2026, 7, 10, 12, 5, tzinfo=timezone.utc),
            "fee": 0.1,
            "fonte_dados": "PAPER",
            "is_real": False,
            "id": 22,
        }
    )
    assert legacy_fill_payload(fill)["is_real"] is False

    result = trade_result_from_legacy_mapping(
        {
            "symbol": "BTCUSDT",
            "direcao": "COMPRA",
            "entrada": 100,
            "saida": 110,
            "quantidade": 1.5,
            "lucro_percent": 10,
            "lucro_reais": 15,
            "resultado": "GANHO",
            "motivo_saida": "TAKE_PROFIT",
            "aberto_em": datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
            "fechado_em": datetime(2026, 7, 10, 13, tzinfo=timezone.utc),
            "fonte_dados": "PAPER",
        }
    )
    assert result.status == TradeResultStatus.CLOSED
    assert legacy_trade_result_payload(result)["pnl_reais"] == 15.0

    candle = candle_from_legacy_mapping(
        {
            "open_time": datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
            "close_time": datetime(2026, 7, 10, 13, tzinfo=timezone.utc),
            "open": 100,
            "high": 110,
            "low": 95,
            "close": 105,
            "volume": 1234,
            "symbol": "BTCUSDT",
            "interval": "1h",
            "fonte_dados": "BINANCE",
        }
    )
    assert legacy_candle_payload(candle)["close"] == 105.0

    snapshot = market_snapshot_from_legacy_mapping(
        {
            "symbol": "BTCUSDT",
            "timestamp": datetime(2026, 7, 10, 13, tzinfo=timezone.utc),
            "current_price": 105,
            "source": "BINANCE",
            "candle": legacy_candle_payload(candle),
            "regime": "BULL",
        }
    )
    assert snapshot.source == DataSource.BINANCE
    assert legacy_market_snapshot_payload(snapshot)["current_price"] == 105.0
