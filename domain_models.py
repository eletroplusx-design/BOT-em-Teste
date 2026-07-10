from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime, timezone
import json
import re
from typing import Any, Mapping


class DomainValidationError(ValueError):
    """Raised when a domain object receives an invalid value."""

def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _normalize_text(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if _is_blank(value):
        if allow_empty:
            return ""
        raise DomainValidationError(f"{field_name} is required.")
    return str(value).strip()


def validate_symbol(symbol: Any) -> str:
    value = _normalize_text(symbol, "symbol").upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,19}", value):
        raise DomainValidationError(f"Invalid symbol: {symbol!r}")
    return value


def validate_direction(direction: Any) -> str:
    value = _normalize_text(direction, "direction").upper()
    aliases = {
        "BUY": "COMPRA",
        "LONG": "COMPRA",
        "COMPRA": "COMPRA",
        "SELL": "VENDA",
        "SHORT": "VENDA",
        "VENDA": "VENDA",
    }
    if value not in aliases:
        raise DomainValidationError(f"Invalid direction: {direction!r}")
    return aliases[value]


def validate_positive_number(value: Any, field_name: str, *, allow_zero: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(f"{field_name} must be numeric.") from exc
    if allow_zero:
        if number < 0:
            raise DomainValidationError(f"{field_name} must be >= 0.")
    else:
        if number <= 0:
            raise DomainValidationError(f"{field_name} must be > 0.")
    return number


def validate_non_negative_number(value: Any, field_name: str) -> float:
    return validate_positive_number(value, field_name, allow_zero=True)


def validate_percentage(value: Any, field_name: str) -> float:
    number = validate_non_negative_number(value, field_name)
    if number > 1000:
        raise DomainValidationError(f"{field_name} is unrealistically high.")
    return number


def _parse_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise DomainValidationError(f"{field_name} is required.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise DomainValidationError(f"Invalid datetime for {field_name}: {value!r}") from exc
    else:
        raise DomainValidationError(f"Invalid datetime for {field_name}: {value!r}")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _serialize_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]
    return value


def _mapping_from(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    raise DomainValidationError("A mapping value is required.")


def _get_first(mapping: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return default


@dataclass(slots=True)
class SerializableModel:
    def to_dict(self) -> dict[str, Any]:
        return {field.name: _serialize_value(getattr(self, field.name)) for field in fields(self)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True)


@dataclass(slots=True)
class Candle(SerializableModel):
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str = "1h"
    source: str = "BINANCE"

    def __post_init__(self) -> None:
        self.symbol = validate_symbol(self.symbol)
        self.timestamp = _parse_datetime(self.timestamp, "timestamp")
        self.open = validate_positive_number(self.open, "open")
        self.high = validate_positive_number(self.high, "high")
        self.low = validate_non_negative_number(self.low, "low")
        self.close = validate_positive_number(self.close, "close")
        self.volume = validate_non_negative_number(self.volume, "volume")
        self.timeframe = _normalize_text(self.timeframe, "timeframe")
        self.source = _normalize_text(self.source, "source").upper()
        if self.high < self.low:
            raise DomainValidationError("high must be >= low.")
        if not (self.low <= self.open <= self.high):
            raise DomainValidationError("open must be within candle range.")
        if not (self.low <= self.close <= self.high):
            raise DomainValidationError("close must be within candle range.")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Candle":
        mapping = _mapping_from(data)
        return cls(
            symbol=_get_first(mapping, "symbol", "simbolo", default="BTCUSDT"),
            timestamp=_get_first(mapping, "timestamp", "open_time", "openTime"),
            open=_get_first(mapping, "open"),
            high=_get_first(mapping, "high"),
            low=_get_first(mapping, "low"),
            close=_get_first(mapping, "close"),
            volume=_get_first(mapping, "volume"),
            timeframe=_get_first(mapping, "timeframe", default="1h"),
            source=_get_first(mapping, "source", "fonte_dados", default="BINANCE"),
        )


@dataclass(slots=True)
class MarketSnapshot(SerializableModel):
    symbol: str
    candle: Candle
    timeframe: str = "1h"
    source: str = "BINANCE"
    regime: str | None = None
    adx: float | None = None
    rsi: float | None = None
    volume_status: str | None = None

    def __post_init__(self) -> None:
        self.symbol = validate_symbol(self.symbol)
        if not isinstance(self.candle, Candle):
            self.candle = Candle.from_mapping(_mapping_from(self.candle))
        self.timeframe = _normalize_text(self.timeframe, "timeframe")
        self.source = _normalize_text(self.source, "source").upper()
        if self.regime is not None:
            self.regime = _normalize_text(self.regime, "regime").upper()
            if self.regime not in {"BULL", "BEAR", "CHOP", "INDEFINIDO"}:
                raise DomainValidationError(f"Invalid regime: {self.regime!r}")
        if self.adx is not None:
            self.adx = validate_non_negative_number(self.adx, "adx")
        if self.rsi is not None:
            self.rsi = validate_percentage(self.rsi, "rsi")
        if self.volume_status is not None:
            self.volume_status = _normalize_text(self.volume_status, "volume_status").upper()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "MarketSnapshot":
        mapping = _mapping_from(data)
        candle_data = _get_first(mapping, "candle", default=None)
        if candle_data is None:
            candle_data = mapping
        return cls(
            symbol=_get_first(mapping, "symbol", "simbolo", default="BTCUSDT"),
            candle=Candle.from_mapping(candle_data),
            timeframe=_get_first(mapping, "timeframe", default="1h"),
            source=_get_first(mapping, "source", "fonte_dados", default="BINANCE"),
            regime=_get_first(mapping, "regime"),
            adx=_get_first(mapping, "adx"),
            rsi=_get_first(mapping, "rsi"),
            volume_status=_get_first(mapping, "volume_status"),
        )


@dataclass(slots=True)
class Signal(SerializableModel):
    symbol: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    rr: float
    score: float = 0.0
    regime: str = "INDEFINIDO"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "BINANCE"
    strategy_version: str = "v2_risk_safe"
    reason: str = ""
    volume_status: str | None = None
    paper: bool = False

    def __post_init__(self) -> None:
        self.symbol = validate_symbol(self.symbol)
        self.direction = validate_direction(self.direction)
        self.entry = validate_positive_number(self.entry, "entry")
        self.stop_loss = validate_positive_number(self.stop_loss, "stop_loss")
        self.take_profit = validate_positive_number(self.take_profit, "take_profit")
        self.rr = validate_non_negative_number(self.rr, "rr")
        self.score = float(self.score)
        self.regime = _normalize_text(self.regime, "regime").upper()
        if self.regime not in {"BULL", "BEAR", "CHOP", "INDEFINIDO"}:
            raise DomainValidationError(f"Invalid regime: {self.regime!r}")
        self.timestamp = _parse_datetime(self.timestamp, "timestamp")
        self.source = _normalize_text(self.source, "source").upper()
        self.strategy_version = _normalize_text(self.strategy_version, "strategy_version")
        self.reason = _normalize_text(self.reason, "reason", allow_empty=True)
        if self.volume_status is not None:
            self.volume_status = _normalize_text(self.volume_status, "volume_status").upper()
        self.paper = bool(self.paper)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Signal":
        mapping = _mapping_from(data)
        return cls(
            symbol=_get_first(mapping, "symbol", "simbolo", default="BTCUSDT"),
            direction=_get_first(mapping, "direction", "direcao", default="COMPRA"),
            entry=_get_first(mapping, "entry", "entrada"),
            stop_loss=_get_first(mapping, "stop_loss", "stop", "stopLoss"),
            take_profit=_get_first(mapping, "take_profit", "take", "takeProfit"),
            rr=_get_first(mapping, "rr", "risk_reward", default=0.0),
            score=_get_first(mapping, "score", default=0.0),
            regime=_get_first(mapping, "regime", default="INDEFINIDO"),
            timestamp=_get_first(mapping, "timestamp", default=datetime.now(timezone.utc)),
            source=_get_first(mapping, "source", "fonte_dados", default="BINANCE"),
            strategy_version=_get_first(mapping, "strategy_version", default="v2_risk_safe"),
            reason=_get_first(mapping, "reason", "motivo", default=""),
            volume_status=_get_first(mapping, "volume_status"),
            paper=bool(_get_first(mapping, "paper", default=False)),
        )


@dataclass(slots=True)
class TradeIntent(SerializableModel):
    symbol: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    quantity: float
    risk_amount: float
    paper: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "PAPER"
    strategy_version: str = "v2_risk_safe"
    exchange_info_ok: bool = True

    def __post_init__(self) -> None:
        self.symbol = validate_symbol(self.symbol)
        self.direction = validate_direction(self.direction)
        self.entry = validate_positive_number(self.entry, "entry")
        self.stop_loss = validate_positive_number(self.stop_loss, "stop_loss")
        self.take_profit = validate_positive_number(self.take_profit, "take_profit")
        self.quantity = validate_positive_number(self.quantity, "quantity")
        self.risk_amount = validate_non_negative_number(self.risk_amount, "risk_amount")
        self.paper = bool(self.paper)
        self.created_at = _parse_datetime(self.created_at, "created_at")
        self.source = _normalize_text(self.source, "source").upper()
        self.strategy_version = _normalize_text(self.strategy_version, "strategy_version")
        self.exchange_info_ok = bool(self.exchange_info_ok)

    @classmethod
    def from_signal(
        cls,
        signal: Signal | Mapping[str, Any],
        *,
        quantity: Any,
        risk_amount: Any,
        paper: bool = True,
        source: str | None = None,
        created_at: Any = None,
        exchange_info_ok: bool = True,
    ) -> "TradeIntent":
        signal_model = coerce_signal(signal)
        return cls(
            symbol=signal_model.symbol,
            direction=signal_model.direction,
            entry=signal_model.entry,
            stop_loss=signal_model.stop_loss,
            take_profit=signal_model.take_profit,
            quantity=quantity,
            risk_amount=risk_amount,
            paper=paper,
            created_at=created_at or signal_model.timestamp,
            source=source or signal_model.source,
            strategy_version=signal_model.strategy_version,
            exchange_info_ok=exchange_info_ok,
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TradeIntent":
        mapping = _mapping_from(data)
        return cls(
            symbol=_get_first(mapping, "symbol", "simbolo", default="BTCUSDT"),
            direction=_get_first(mapping, "direction", "direcao", default="COMPRA"),
            entry=_get_first(mapping, "entry", "entrada"),
            stop_loss=_get_first(mapping, "stop_loss", "stop", "stopLoss"),
            take_profit=_get_first(mapping, "take_profit", "take", "takeProfit"),
            quantity=_get_first(mapping, "quantity", "quantidade"),
            risk_amount=_get_first(mapping, "risk_amount", "valor_arriscado", default=0.0),
            paper=bool(_get_first(mapping, "paper", "is_paper", default=True)),
            created_at=_get_first(mapping, "created_at", "timestamp", default=datetime.now(timezone.utc)),
            source=_get_first(mapping, "source", "fonte_dados", default="PAPER"),
            strategy_version=_get_first(mapping, "strategy_version", default="v2_risk_safe"),
            exchange_info_ok=bool(_get_first(mapping, "exchange_info_ok", default=True)),
        )


@dataclass(slots=True)
class RiskDecision(SerializableModel):
    allowed: bool
    reason: str
    blocked_by: str = "N/A"
    capital: float = 0.0
    risk_percent: float = 0.0
    exposure: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    strategy_version: str = "v2_risk_safe"
    notes: str = ""

    def __post_init__(self) -> None:
        self.allowed = bool(self.allowed)
        self.reason = _normalize_text(self.reason, "reason", allow_empty=True)
        self.blocked_by = _normalize_text(self.blocked_by, "blocked_by").upper()
        self.capital = validate_non_negative_number(self.capital, "capital")
        self.risk_percent = validate_non_negative_number(self.risk_percent, "risk_percent")
        self.exposure = validate_non_negative_number(self.exposure, "exposure")
        self.timestamp = _parse_datetime(self.timestamp, "timestamp")
        self.strategy_version = _normalize_text(self.strategy_version, "strategy_version")
        self.notes = _normalize_text(self.notes, "notes", allow_empty=True)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RiskDecision":
        mapping = _mapping_from(data)
        return cls(
            allowed=bool(_get_first(mapping, "allowed", default=False)),
            reason=_get_first(mapping, "reason", "motivo", default=""),
            blocked_by=_get_first(mapping, "blocked_by", "bloqueado_por", default="N/A"),
            capital=_get_first(mapping, "capital", default=0.0),
            risk_percent=_get_first(mapping, "risk_percent", default=0.0),
            exposure=_get_first(mapping, "exposure", default=0.0),
            timestamp=_get_first(mapping, "timestamp", default=datetime.now(timezone.utc)),
            strategy_version=_get_first(mapping, "strategy_version", default="v2_risk_safe"),
            notes=_get_first(mapping, "notes", default=""),
        )


@dataclass(slots=True)
class PaperOrder(SerializableModel):
    symbol: str
    direction: str
    entry: float
    quantity: float
    stop_loss: float
    take_profit: float
    status: str = "open"
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "PAPER"
    paper: bool = True
    order_id: int | None = None

    def __post_init__(self) -> None:
        self.symbol = validate_symbol(self.symbol)
        self.direction = validate_direction(self.direction)
        self.entry = validate_positive_number(self.entry, "entry")
        self.quantity = validate_positive_number(self.quantity, "quantity")
        self.stop_loss = validate_positive_number(self.stop_loss, "stop_loss")
        self.take_profit = validate_positive_number(self.take_profit, "take_profit")
        self.status = _normalize_text(self.status, "status").lower()
        if self.status not in {"open", "closed", "cancelled"}:
            raise DomainValidationError(f"Invalid order status: {self.status!r}")
        self.opened_at = _parse_datetime(self.opened_at, "opened_at")
        self.source = _normalize_text(self.source, "source").upper()
        self.paper = bool(self.paper)
        if self.order_id is not None:
            self.order_id = int(self.order_id)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PaperOrder":
        mapping = _mapping_from(data)
        return cls(
            symbol=_get_first(mapping, "symbol", "simbolo", default="BTCUSDT"),
            direction=_get_first(mapping, "direction", "direcao", default="COMPRA"),
            entry=_get_first(mapping, "entry", "entrada"),
            quantity=_get_first(mapping, "quantity", "quantidade"),
            stop_loss=_get_first(mapping, "stop_loss", "stop", "stopLoss"),
            take_profit=_get_first(mapping, "take_profit", "take", "takeProfit"),
            status=_get_first(mapping, "status", default="open"),
            opened_at=_get_first(mapping, "opened_at", "timestamp", default=datetime.now(timezone.utc)),
            source=_get_first(mapping, "source", "fonte_dados", default="PAPER"),
            paper=bool(_get_first(mapping, "paper", "is_paper", default=True)),
            order_id=_get_first(mapping, "order_id", "id"),
        )


@dataclass(slots=True)
class Fill(SerializableModel):
    price: float
    quantity: float
    filled_at: datetime
    fee: float = 0.0
    source: str = "PAPER"
    is_real: bool = False
    order_id: int | None = None

    def __post_init__(self) -> None:
        self.price = validate_positive_number(self.price, "price")
        self.quantity = validate_positive_number(self.quantity, "quantity")
        self.fee = validate_non_negative_number(self.fee, "fee")
        self.filled_at = _parse_datetime(self.filled_at, "filled_at")
        self.source = _normalize_text(self.source, "source").upper()
        self.is_real = bool(self.is_real)
        if self.order_id is not None:
            self.order_id = int(self.order_id)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Fill":
        mapping = _mapping_from(data)
        return cls(
            price=_get_first(mapping, "price", "preco"),
            quantity=_get_first(mapping, "quantity", "quantidade"),
            filled_at=_get_first(mapping, "filled_at", "timestamp", default=datetime.now(timezone.utc)),
            fee=_get_first(mapping, "fee", default=0.0),
            source=_get_first(mapping, "source", "fonte_dados", default="PAPER"),
            is_real=bool(_get_first(mapping, "is_real", default=False)),
            order_id=_get_first(mapping, "order_id", "id"),
        )


@dataclass(slots=True)
class Position(SerializableModel):
    symbol: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    quantity: float
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "open"
    source: str = "PAPER"
    paper: bool = True
    unrealized_pnl: float = 0.0

    def __post_init__(self) -> None:
        self.symbol = validate_symbol(self.symbol)
        self.direction = validate_direction(self.direction)
        self.entry = validate_positive_number(self.entry, "entry")
        self.stop_loss = validate_positive_number(self.stop_loss, "stop_loss")
        self.take_profit = validate_positive_number(self.take_profit, "take_profit")
        self.quantity = validate_positive_number(self.quantity, "quantity")
        self.opened_at = _parse_datetime(self.opened_at, "opened_at")
        self.status = _normalize_text(self.status, "status").lower()
        if self.status not in {"open", "closed"}:
            raise DomainValidationError(f"Invalid position status: {self.status!r}")
        self.source = _normalize_text(self.source, "source").upper()
        self.paper = bool(self.paper)
        self.unrealized_pnl = float(self.unrealized_pnl)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Position":
        mapping = _mapping_from(data)
        return cls(
            symbol=_get_first(mapping, "symbol", "simbolo", default="BTCUSDT"),
            direction=_get_first(mapping, "direction", "direcao", default="COMPRA"),
            entry=_get_first(mapping, "entry", "entrada"),
            stop_loss=_get_first(mapping, "stop_loss", "stop", "stopLoss"),
            take_profit=_get_first(mapping, "take_profit", "take", "takeProfit"),
            quantity=_get_first(mapping, "quantity", "quantidade"),
            opened_at=_get_first(mapping, "opened_at", "timestamp", default=datetime.now(timezone.utc)),
            status=_get_first(mapping, "status", default="open"),
            source=_get_first(mapping, "source", "fonte_dados", default="PAPER"),
            paper=bool(_get_first(mapping, "paper", "is_paper", default=True)),
            unrealized_pnl=_get_first(mapping, "unrealized_pnl", default=0.0),
        )


@dataclass(slots=True)
class TradeResult(SerializableModel):
    symbol: str
    direction: str
    entry: float
    exit_price: float
    quantity: float
    pnl_percent: float
    pnl_reais: float
    status: str
    reason: str
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "PAPER"
    paper: bool = True
    strategy_version: str = "v2_risk_safe"

    def __post_init__(self) -> None:
        self.symbol = validate_symbol(self.symbol)
        self.direction = validate_direction(self.direction)
        self.entry = validate_positive_number(self.entry, "entry")
        self.exit_price = validate_positive_number(self.exit_price, "exit_price")
        self.quantity = validate_positive_number(self.quantity, "quantity")
        self.pnl_percent = float(self.pnl_percent)
        self.pnl_reais = float(self.pnl_reais)
        self.status = _normalize_text(self.status, "status").lower()
        if self.status not in {"open", "closed", "partial"}:
            raise DomainValidationError(f"Invalid trade result status: {self.status!r}")
        self.reason = _normalize_text(self.reason, "reason", allow_empty=True)
        self.opened_at = _parse_datetime(self.opened_at, "opened_at")
        self.closed_at = _parse_datetime(self.closed_at, "closed_at")
        self.source = _normalize_text(self.source, "source").upper()
        self.paper = bool(self.paper)
        self.strategy_version = _normalize_text(self.strategy_version, "strategy_version")

    @property
    def resultado(self) -> str:
        if self.pnl_reais > 0:
            return "GANHO"
        if self.pnl_reais < 0:
            return "PERDA"
        return "EMPATE"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TradeResult":
        mapping = _mapping_from(data)
        status_value = _get_first(mapping, "status", default=None)
        if status_value is None:
            status_value = _get_first(mapping, "resultado", default="closed")
        if isinstance(status_value, str) and status_value.strip().upper() in {"GANHO", "PERDA", "EMPATE"}:
            status_value = "closed"
        return cls(
            symbol=_get_first(mapping, "symbol", "simbolo", default="BTCUSDT"),
            direction=_get_first(mapping, "direction", "direcao", default="COMPRA"),
            entry=_get_first(mapping, "entry", "entrada"),
            exit_price=_get_first(mapping, "exit_price", "saida", "exit"),
            quantity=_get_first(mapping, "quantity", "quantidade"),
            pnl_percent=_get_first(mapping, "pnl_percent", "lucro_percent", default=0.0),
            pnl_reais=_get_first(mapping, "pnl_reais", "lucro_reais", default=0.0),
            status=status_value,
            reason=_get_first(mapping, "reason", "motivo", "motivo_saida", default=""),
            opened_at=_get_first(mapping, "opened_at", "aberto_em", default=datetime.now(timezone.utc)),
            closed_at=_get_first(mapping, "closed_at", "fechado_em", default=datetime.now(timezone.utc)),
            source=_get_first(mapping, "source", "fonte_dados", default="PAPER"),
            paper=bool(_get_first(mapping, "paper", "is_paper", default=True)),
            strategy_version=_get_first(mapping, "strategy_version", default="v2_risk_safe"),
        )


def coerce_candle(value: Candle | Mapping[str, Any]) -> Candle:
    if isinstance(value, Candle):
        return value
    return Candle.from_mapping(value)


def coerce_market_snapshot(value: MarketSnapshot | Mapping[str, Any]) -> MarketSnapshot:
    if isinstance(value, MarketSnapshot):
        return value
    return MarketSnapshot.from_mapping(value)


def coerce_signal(value: Signal | Mapping[str, Any]) -> Signal:
    if isinstance(value, Signal):
        return value
    return Signal.from_mapping(value)


def coerce_trade_intent(value: TradeIntent | Mapping[str, Any]) -> TradeIntent:
    if isinstance(value, TradeIntent):
        return value
    return TradeIntent.from_mapping(value)


def coerce_risk_decision(value: RiskDecision | Mapping[str, Any]) -> RiskDecision:
    if isinstance(value, RiskDecision):
        return value
    return RiskDecision.from_mapping(value)


def coerce_paper_order(value: PaperOrder | Mapping[str, Any]) -> PaperOrder:
    if isinstance(value, PaperOrder):
        return value
    return PaperOrder.from_mapping(value)


def coerce_fill(value: Fill | Mapping[str, Any]) -> Fill:
    if isinstance(value, Fill):
        return value
    return Fill.from_mapping(value)


def coerce_position(value: Position | Mapping[str, Any]) -> Position:
    if isinstance(value, Position):
        return value
    return Position.from_mapping(value)


def coerce_trade_result(value: TradeResult | Mapping[str, Any]) -> TradeResult:
    if isinstance(value, TradeResult):
        return value
    return TradeResult.from_mapping(value)
