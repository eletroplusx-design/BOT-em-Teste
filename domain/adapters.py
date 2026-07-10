from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from .enums import DataSource, Direction, OrderStatus, PositionStatus, TradeResultStatus, TradingMode
from .models import Candle, Fill, MarketSnapshot, PaperOrder, Position, RiskDecision, Signal, TradeIntent, TradeResult
from .validation import DomainValidationError, parse_enum


def _mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    return dict(data)


def _legacy_symbol(mapping: Mapping[str, Any], default_symbol: str | None) -> Any:
    if "symbol" in mapping:
        return mapping["symbol"]
    if "simbolo" in mapping:
        return mapping["simbolo"]
    if default_symbol is not None:
        return default_symbol
    raise DomainValidationError("symbol is required.")


def _legacy_direction(mapping: Mapping[str, Any]) -> Any:
    for key in ("direction", "direcao", "side"):
        if key in mapping:
            return mapping[key]
    raise DomainValidationError("direction is required.")


def _legacy_source(mapping: Mapping[str, Any], default: DataSource = DataSource.LEGACY) -> Any:
    for key in ("source", "fonte_dados"):
        if key in mapping:
            return mapping[key]
    return default


def _legacy_decimal(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def signal_from_legacy_mapping(mapping: Mapping[str, Any], *, default_symbol: str | None = None) -> Signal:
    data = _mapping(mapping)
    return Signal.from_dict(
        {
            "symbol": _legacy_symbol(data, default_symbol),
            "direction": _legacy_direction(data),
            "entry": _legacy_decimal(data, "entry", "entrada"),
            "stop_loss": _legacy_decimal(data, "stop_loss", "stop", "stopLoss"),
            "take_profit": _legacy_decimal(data, "take_profit", "take", "takeProfit"),
            "rr": _legacy_decimal(data, "rr", default=Decimal("0")),
            "timestamp": _legacy_decimal(data, "timestamp", default=datetime.now(timezone.utc)),
            "source": _legacy_source(data),
            "score": _legacy_decimal(data, "score", default=Decimal("0")),
            "regime": _legacy_decimal(data, "regime"),
            "volume_status": _legacy_decimal(data, "volume_status"),
            "reason": _legacy_decimal(data, "reason", "motivo", default=""),
            "strategy_version": _legacy_decimal(data, "strategy_version", default="v2_risk_safe"),
        }
    )


def trade_intent_from_legacy_mapping(mapping: Mapping[str, Any], *, default_symbol: str | None = None) -> TradeIntent:
    data = _mapping(mapping)
    return TradeIntent.from_dict(
        {
            "symbol": _legacy_symbol(data, default_symbol),
            "direction": _legacy_direction(data),
            "entry": _legacy_decimal(data, "entry", "entrada"),
            "stop_loss": _legacy_decimal(data, "stop_loss", "stop", "stopLoss"),
            "take_profit": _legacy_decimal(data, "take_profit", "take", "takeProfit"),
            "quantity": _legacy_decimal(data, "quantity", "quantidade"),
            "risk_amount": _legacy_decimal(data, "risk_amount", "valor_arriscado"),
            "created_at": _legacy_decimal(data, "created_at", "timestamp", default=datetime.now(timezone.utc)),
            "source": _legacy_source(data, DataSource.PAPER),
            "strategy_version": _legacy_decimal(data, "strategy_version", default="v2_risk_safe"),
            "paper": True,
            "trading_mode": TradingMode.PAPER,
        }
    )


def paper_order_from_legacy_mapping(mapping: Mapping[str, Any], *, default_symbol: str | None = None) -> PaperOrder:
    data = _mapping(mapping)
    return PaperOrder.from_dict(
        {
            "symbol": _legacy_symbol(data, default_symbol),
            "direction": _legacy_direction(data),
            "entry": _legacy_decimal(data, "entry", "entrada"),
            "quantity": _legacy_decimal(data, "quantity", "quantidade"),
            "stop_loss": _legacy_decimal(data, "stop_loss", "stop", "stopLoss"),
            "take_profit": _legacy_decimal(data, "take_profit", "take", "takeProfit"),
            "opened_at": _legacy_decimal(data, "opened_at", "timestamp", default=datetime.now(timezone.utc)),
            "status": _legacy_decimal(data, "status", default=OrderStatus.OPEN),
            "source": _legacy_source(data, DataSource.PAPER),
            "paper": True,
            "trading_mode": TradingMode.PAPER,
            "order_id": _legacy_decimal(data, "order_id", "id"),
        }
    )


def position_from_legacy_mapping(mapping: Mapping[str, Any], *, default_symbol: str | None = None) -> Position:
    data = _mapping(mapping)
    return Position.from_dict(
        {
            "symbol": _legacy_symbol(data, default_symbol),
            "direction": _legacy_direction(data),
            "entry": _legacy_decimal(data, "entry", "entrada"),
            "stop_loss": _legacy_decimal(data, "stop_loss", "stop", "stopLoss"),
            "take_profit": _legacy_decimal(data, "take_profit", "take", "takeProfit"),
            "quantity": _legacy_decimal(data, "quantity", "quantidade"),
            "opened_at": _legacy_decimal(data, "opened_at", "timestamp", default=datetime.now(timezone.utc)),
            "status": _legacy_decimal(data, "status", default=PositionStatus.OPEN),
            "source": _legacy_source(data, DataSource.PAPER),
            "paper": True,
            "trading_mode": TradingMode.PAPER,
            "unrealized_pnl": _legacy_decimal(data, "unrealized_pnl", default=Decimal("0")),
        }
    )


def trade_result_from_legacy_mapping(mapping: Mapping[str, Any], *, default_symbol: str | None = None) -> TradeResult:
    data = _mapping(mapping)
    resultado = _legacy_decimal(data, "status", "resultado", default=TradeResultStatus.CLOSED)
    if isinstance(resultado, str) and resultado.upper() in {"GANHO", "PERDA", "EMPATE"}:
        resultado = TradeResultStatus.CLOSED
    return TradeResult.from_dict(
        {
            "symbol": _legacy_symbol(data, default_symbol),
            "direction": _legacy_direction(data),
            "entry": _legacy_decimal(data, "entry", "entrada"),
            "exit_price": _legacy_decimal(data, "exit_price", "saida", "exit"),
            "quantity": _legacy_decimal(data, "quantity", "quantidade"),
            "pnl_percent": _legacy_decimal(data, "pnl_percent", "lucro_percent", default=Decimal("0")),
            "pnl_reais": _legacy_decimal(data, "pnl_reais", "lucro_reais", default=Decimal("0")),
            "status": resultado,
            "reason": _legacy_decimal(data, "reason", "motivo", "motivo_saida", default=""),
            "opened_at": _legacy_decimal(data, "opened_at", "aberto_em", default=datetime.now(timezone.utc)),
            "closed_at": _legacy_decimal(data, "closed_at", "fechado_em", default=datetime.now(timezone.utc)),
            "source": _legacy_source(data, DataSource.PAPER),
            "paper": True,
            "trading_mode": TradingMode.PAPER,
            "strategy_version": _legacy_decimal(data, "strategy_version", default="v2_risk_safe"),
        }
    )


def risk_decision_from_legacy_mapping(mapping: Mapping[str, Any]) -> RiskDecision:
    data = _mapping(mapping)
    return RiskDecision.from_dict(
        {
            "allowed": data.get("allowed"),
            "reason": data.get("reason", ""),
            "blocked_by": data.get("blocked_by", data.get("bloqueado_por", "N/A")),
            "capital": data.get("capital", 0),
            "risk_percent": data.get("risk_percent", 0),
            "exposure": data.get("exposure", 0),
            "timestamp": data.get("timestamp", datetime.now(timezone.utc)),
            "strategy_version": data.get("strategy_version", "v2_risk_safe"),
            "exchange_info_ok": data.get("exchange_info_ok", True),
            "notes": data.get("notes", ""),
        }
    )


def fill_from_legacy_mapping(mapping: Mapping[str, Any]) -> Fill:
    data = _mapping(mapping)
    return Fill.from_dict(
        {
            "price": data.get("price", data.get("preco")),
            "quantity": data.get("quantity", data.get("quantidade")),
            "filled_at": data.get("filled_at", data.get("timestamp", datetime.now(timezone.utc))),
            "fee": data.get("fee", 0),
            "source": data.get("source", data.get("fonte_dados", DataSource.PAPER)),
            "is_real": data.get("is_real", False),
            "order_id": data.get("order_id", data.get("id")),
        }
    )


def candle_from_legacy_mapping(mapping: Mapping[str, Any]) -> Candle:
    data = _mapping(mapping)
    return Candle.from_dict(
        {
            "open_time": data.get("open_time", data.get("timestamp")),
            "close_time": data.get("close_time", data.get("timestamp")),
            "open": data.get("open"),
            "high": data.get("high"),
            "low": data.get("low"),
            "close": data.get("close"),
            "volume": data.get("volume"),
            "symbol": data.get("symbol", data.get("simbolo")),
            "interval": data.get("interval", data.get("timeframe")),
            "source": data.get("source", data.get("fonte_dados", DataSource.BINANCE)),
        }
    )


def market_snapshot_from_legacy_mapping(mapping: Mapping[str, Any]) -> MarketSnapshot:
    data = _mapping(mapping)
    candle = data.get("candle")
    return MarketSnapshot.from_dict(
        {
            "symbol": data.get("symbol", data.get("simbolo")),
            "timestamp": data.get("timestamp", data.get("open_time", datetime.now(timezone.utc))),
            "current_price": data.get("current_price", data.get("close")),
            "source": data.get("source", data.get("fonte_dados", DataSource.BINANCE)),
            "candle": candle_from_legacy_mapping(candle).to_dict() if isinstance(candle, Mapping) else candle,
            "regime": data.get("regime"),
        }
    )


def legacy_signal_payload(signal: Signal) -> dict[str, Any]:
    return {
        "symbol": signal.symbol,
        "direction": signal.direction.value,
        "direcao": signal.direction.value,
        "entry": float(signal.entry),
        "entrada": float(signal.entry),
        "stop_loss": float(signal.stop_loss),
        "take_profit": float(signal.take_profit),
        "rr": float(signal.rr),
        "score": float(signal.score),
        "regime": signal.regime,
        "timestamp": signal.timestamp.isoformat(),
        "source": signal.source.value,
        "reason": signal.reason,
        "motivo": signal.reason,
        "volume_status": signal.volume_status,
        "strategy_version": signal.strategy_version,
    }


def legacy_trade_intent_payload(intent: TradeIntent) -> dict[str, Any]:
    return {
        "symbol": intent.symbol,
        "direction": intent.direction.value,
        "entry": float(intent.entry),
        "stop_loss": float(intent.stop_loss),
        "take_profit": float(intent.take_profit),
        "quantity": float(intent.quantity),
        "risk_amount": float(intent.risk_amount),
        "created_at": intent.created_at.isoformat(),
        "source": intent.source.value,
        "strategy_version": intent.strategy_version,
        "paper": intent.paper,
        "trading_mode": intent.trading_mode.value,
    }


def legacy_paper_order_payload(order: PaperOrder) -> dict[str, Any]:
    return {
        "symbol": order.symbol,
        "direction": order.direction.value,
        "entry": float(order.entry),
        "quantity": float(order.quantity),
        "stop_loss": float(order.stop_loss),
        "take_profit": float(order.take_profit),
        "opened_at": order.opened_at.isoformat(),
        "status": order.status.value,
        "source": order.source.value,
        "paper": order.paper,
        "trading_mode": order.trading_mode.value,
        "order_id": order.order_id,
    }


def legacy_position_payload(position: Position) -> dict[str, Any]:
    return {
        "symbol": position.symbol,
        "direction": position.direction.value,
        "entry": float(position.entry),
        "stop_loss": float(position.stop_loss),
        "take_profit": float(position.take_profit),
        "quantity": float(position.quantity),
        "opened_at": position.opened_at.isoformat(),
        "status": position.status.value,
        "source": position.source.value,
        "paper": position.paper,
        "trading_mode": position.trading_mode.value,
        "unrealized_pnl": float(position.unrealized_pnl),
    }


def legacy_trade_result_payload(result: TradeResult) -> dict[str, Any]:
    return {
        "symbol": result.symbol,
        "direction": result.direction.value,
        "entry": float(result.entry),
        "exit_price": float(result.exit_price),
        "quantity": float(result.quantity),
        "pnl_percent": float(result.pnl_percent),
        "pnl_reais": float(result.pnl_reais),
        "status": result.status.value,
        "reason": result.reason,
        "opened_at": result.opened_at.isoformat(),
        "closed_at": result.closed_at.isoformat(),
        "source": result.source.value,
        "paper": result.paper,
        "trading_mode": result.trading_mode.value,
        "strategy_version": result.strategy_version,
    }


def legacy_risk_decision_payload(decision: RiskDecision) -> dict[str, Any]:
    return {
        "allowed": decision.allowed,
        "reason": decision.reason,
        "blocked_by": decision.blocked_by,
        "capital": float(decision.capital),
        "risk_percent": float(decision.risk_percent),
        "exposure": float(decision.exposure),
        "timestamp": decision.timestamp.isoformat(),
        "strategy_version": decision.strategy_version,
        "exchange_info_ok": decision.exchange_info_ok,
        "notes": decision.notes,
    }


def legacy_fill_payload(fill: Fill) -> dict[str, Any]:
    return {
        "price": float(fill.price),
        "quantity": float(fill.quantity),
        "filled_at": fill.filled_at.isoformat(),
        "fee": float(fill.fee),
        "source": fill.source.value,
        "is_real": fill.is_real,
        "order_id": fill.order_id,
    }


def legacy_candle_payload(candle: Candle) -> dict[str, Any]:
    return {
        "open_time": candle.open_time.isoformat(),
        "close_time": candle.close_time.isoformat(),
        "open": float(candle.open),
        "high": float(candle.high),
        "low": float(candle.low),
        "close": float(candle.close),
        "volume": float(candle.volume),
        "symbol": candle.symbol,
        "interval": candle.interval,
        "source": candle.source.value,
    }


def legacy_market_snapshot_payload(snapshot: MarketSnapshot) -> dict[str, Any]:
    payload = {
        "symbol": snapshot.symbol,
        "timestamp": snapshot.timestamp.isoformat(),
        "current_price": float(snapshot.current_price),
        "source": snapshot.source.value,
        "regime": snapshot.regime,
    }
    if snapshot.candle is not None:
        payload["candle"] = legacy_candle_payload(snapshot.candle)
    return payload
