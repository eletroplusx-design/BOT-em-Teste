from __future__ import annotations

from dataclasses import dataclass, field, fields, FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional

from .enums import (
    DataSource,
    Direction,
    OrderStatus,
    PositionStatus,
    TradeResultStatus,
    TradingMode,
)
from .serialization import dumps_json, to_jsonable
from .validation import (
    DomainValidationError,
    ensure_price_coherence,
    parse_bool_false_only,
    parse_bool_true_only,
    parse_decimal,
    parse_direction,
    parse_enum,
    parse_symbol,
    parse_strict_bool,
    parse_timezone_aware_datetime,
)


def _require_keys(data: Mapping[str, Any], keys: tuple[str, ...], field_name: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    raise DomainValidationError(f"{field_name} is required.")


def _first_present(data: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return default


@dataclass(frozen=True, slots=True)
class DomainModel:
    def to_dict(self) -> dict[str, Any]:
        return to_jsonable({field.name: getattr(self, field.name) for field in fields(self)})

    def to_json(self) -> str:
        return dumps_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class Candle(DomainModel):
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    symbol: str
    interval: str
    source: DataSource

    def __post_init__(self) -> None:
        open_time = parse_timezone_aware_datetime(self.open_time, "open_time")
        close_time = parse_timezone_aware_datetime(self.close_time, "close_time")
        if close_time < open_time:
            raise DomainValidationError("close_time cannot be earlier than open_time.")
        symbol = parse_symbol(self.symbol)
        open_value = parse_decimal(self.open, "open")
        high_value = parse_decimal(self.high, "high")
        low_value = parse_decimal(self.low, "low")
        close_value = parse_decimal(self.close, "close")
        volume = parse_decimal(self.volume, "volume", allow_zero=True)
        interval = str(self.interval).strip()
        if not interval:
            raise DomainValidationError("interval is required.")
        source = parse_enum(self.source, DataSource, "source")
        if high_value < low_value:
            raise DomainValidationError("high must be greater than or equal to low.")
        if not (low_value <= open_value <= high_value):
            raise DomainValidationError("open must be within candle range.")
        if not (low_value <= close_value <= high_value):
            raise DomainValidationError("close must be within candle range.")

        object.__setattr__(self, "open_time", open_time)
        object.__setattr__(self, "close_time", close_time)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "open", open_value)
        object.__setattr__(self, "high", high_value)
        object.__setattr__(self, "low", low_value)
        object.__setattr__(self, "close", close_value)
        object.__setattr__(self, "volume", volume)
        object.__setattr__(self, "interval", interval)
        object.__setattr__(self, "source", source)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Candle":
        mapping = dict(data)
        return cls(
            open_time=_require_keys(mapping, ("open_time",), "open_time"),
            close_time=_require_keys(mapping, ("close_time",), "close_time"),
            open=_require_keys(mapping, ("open",), "open"),
            high=_require_keys(mapping, ("high",), "high"),
            low=_require_keys(mapping, ("low",), "low"),
            close=_require_keys(mapping, ("close",), "close"),
            volume=_require_keys(mapping, ("volume",), "volume"),
            symbol=_require_keys(mapping, ("symbol",), "symbol"),
            interval=_require_keys(mapping, ("interval",), "interval"),
            source=_require_keys(mapping, ("source",), "source"),
        )


@dataclass(frozen=True, slots=True)
class MarketSnapshot(DomainModel):
    symbol: str
    timestamp: datetime
    current_price: Decimal
    source: DataSource
    candle: Optional[Candle] = None
    regime: Optional[str] = None

    def __post_init__(self) -> None:
        symbol = parse_symbol(self.symbol)
        timestamp = parse_timezone_aware_datetime(self.timestamp, "timestamp")
        current_price = parse_decimal(self.current_price, "current_price")
        source = parse_enum(self.source, DataSource, "source")
        candle = self.candle
        regime = self.regime.strip().upper() if isinstance(self.regime, str) and self.regime.strip() else None
        if regime is not None and regime not in {"BULL", "BEAR", "CHOP", "INDEFINIDO"}:
            raise DomainValidationError(f"Invalid regime: {self.regime!r}")
        if candle is not None:
            if not isinstance(candle, Candle):
                candle = Candle.from_dict(candle)
            if candle.symbol != symbol:
                raise DomainValidationError("Snapshot and candle symbols must match.")
            if candle.source != source:
                raise DomainValidationError("Snapshot and candle sources must match.")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "current_price", current_price)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "candle", candle)
        object.__setattr__(self, "regime", regime)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketSnapshot":
        mapping = dict(data)
        candle = mapping.get("candle")
        return cls(
            symbol=_require_keys(mapping, ("symbol",), "symbol"),
            timestamp=_require_keys(mapping, ("timestamp",), "timestamp"),
            current_price=_require_keys(mapping, ("current_price",), "current_price"),
            source=_require_keys(mapping, ("source",), "source"),
            candle=candle,
            regime=mapping.get("regime"),
        )


@dataclass(frozen=True, slots=True)
class Signal(DomainModel):
    symbol: str
    direction: Direction
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    rr: Decimal
    timestamp: datetime
    source: DataSource
    score: Decimal = Decimal("0")
    regime: Optional[str] = None
    volume_status: Optional[str] = None
    reason: str = ""
    strategy_version: str = "v2_risk_safe"

    def __post_init__(self) -> None:
        symbol = parse_symbol(self.symbol)
        direction = parse_direction(self.direction)
        entry = parse_decimal(self.entry, "entry")
        stop_loss = parse_decimal(self.stop_loss, "stop_loss")
        take_profit = parse_decimal(self.take_profit, "take_profit")
        rr = parse_decimal(self.rr, "rr", allow_zero=True)
        timestamp = parse_timezone_aware_datetime(self.timestamp, "timestamp")
        source = parse_enum(self.source, DataSource, "source")
        score = parse_decimal(self.score, "score", allow_zero=True, allow_negative=True)
        regime = self.regime.strip().upper() if isinstance(self.regime, str) and self.regime.strip() else None
        if regime is not None and regime not in {"BULL", "BEAR", "CHOP", "INDEFINIDO"}:
            raise DomainValidationError(f"Invalid regime: {self.regime!r}")
        if self.volume_status is not None:
            volume_status = self.volume_status.strip().upper()
            if not volume_status:
                raise DomainValidationError("volume_status is required when provided.")
        else:
            volume_status = None
        reason = self.reason.strip() if isinstance(self.reason, str) else str(self.reason).strip()
        ensure_price_coherence(direction, entry, stop_loss, take_profit)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "entry", entry)
        object.__setattr__(self, "stop_loss", stop_loss)
        object.__setattr__(self, "take_profit", take_profit)
        object.__setattr__(self, "rr", rr)
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "regime", regime)
        object.__setattr__(self, "volume_status", volume_status)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "strategy_version", self.strategy_version.strip() or "v2_risk_safe")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Signal":
        mapping = dict(data)
        return cls(
            symbol=_require_keys(mapping, ("symbol",), "symbol"),
            direction=_require_keys(mapping, ("direction",), "direction"),
            entry=_require_keys(mapping, ("entry",), "entry"),
            stop_loss=_require_keys(mapping, ("stop_loss",), "stop_loss"),
            take_profit=_require_keys(mapping, ("take_profit",), "take_profit"),
            rr=_require_keys(mapping, ("rr",), "rr"),
            timestamp=_require_keys(mapping, ("timestamp",), "timestamp"),
            source=_require_keys(mapping, ("source",), "source"),
            score=mapping.get("score", Decimal("0")),
            regime=mapping.get("regime"),
            volume_status=mapping.get("volume_status"),
            reason=mapping.get("reason", ""),
            strategy_version=mapping.get("strategy_version", "v2_risk_safe"),
        )


@dataclass(frozen=True, slots=True)
class TradeIntent(DomainModel):
    symbol: str
    direction: Direction
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    quantity: Decimal
    risk_amount: Decimal
    created_at: datetime
    source: DataSource
    strategy_version: str = "v2_risk_safe"
    paper: bool = True
    trading_mode: TradingMode = TradingMode.PAPER

    def __post_init__(self) -> None:
        if parse_bool_true_only(self.paper, "paper") is not True:
            raise DomainValidationError("paper must be True.")
        if parse_enum(self.trading_mode, TradingMode, "trading_mode") is not TradingMode.PAPER:
            raise DomainValidationError("trading_mode must be PAPER.")
        symbol = parse_symbol(self.symbol)
        direction = parse_direction(self.direction)
        entry = parse_decimal(self.entry, "entry")
        stop_loss = parse_decimal(self.stop_loss, "stop_loss")
        take_profit = parse_decimal(self.take_profit, "take_profit")
        quantity = parse_decimal(self.quantity, "quantity")
        risk_amount = parse_decimal(self.risk_amount, "risk_amount", allow_zero=True)
        created_at = parse_timezone_aware_datetime(self.created_at, "created_at")
        source = parse_enum(self.source, DataSource, "source")
        ensure_price_coherence(direction, entry, stop_loss, take_profit)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "entry", entry)
        object.__setattr__(self, "stop_loss", stop_loss)
        object.__setattr__(self, "take_profit", take_profit)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "risk_amount", risk_amount)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "strategy_version", self.strategy_version.strip() or "v2_risk_safe")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TradeIntent":
        mapping = dict(data)
        return cls(
            symbol=_require_keys(mapping, ("symbol",), "symbol"),
            direction=_require_keys(mapping, ("direction",), "direction"),
            entry=_require_keys(mapping, ("entry",), "entry"),
            stop_loss=_require_keys(mapping, ("stop_loss",), "stop_loss"),
            take_profit=_require_keys(mapping, ("take_profit",), "take_profit"),
            quantity=_require_keys(mapping, ("quantity",), "quantity"),
            risk_amount=_require_keys(mapping, ("risk_amount",), "risk_amount"),
            created_at=_require_keys(mapping, ("created_at",), "created_at"),
            source=_require_keys(mapping, ("source",), "source"),
            strategy_version=mapping.get("strategy_version", "v2_risk_safe"),
            paper=mapping.get("paper", True),
            trading_mode=mapping.get("trading_mode", TradingMode.PAPER),
        )


@dataclass(frozen=True, slots=True)
class RiskDecision(DomainModel):
    allowed: bool
    reason: str
    blocked_by: str
    capital: Decimal
    risk_percent: Decimal
    exposure: Decimal
    timestamp: datetime
    strategy_version: str = "v2_risk_safe"
    exchange_info_ok: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        allowed = parse_strict_bool(self.allowed, "allowed")
        exchange_info_ok = parse_strict_bool(self.exchange_info_ok, "exchange_info_ok")
        reason = self.reason.strip() if isinstance(self.reason, str) else str(self.reason).strip()
        blocked_by = self.blocked_by.strip().upper() if isinstance(self.blocked_by, str) and self.blocked_by.strip() else "N/A"
        capital = parse_decimal(self.capital, "capital", allow_zero=True)
        risk_percent = parse_decimal(self.risk_percent, "risk_percent", allow_zero=True)
        exposure = parse_decimal(self.exposure, "exposure", allow_zero=True)
        timestamp = parse_timezone_aware_datetime(self.timestamp, "timestamp")
        object.__setattr__(self, "allowed", allowed)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "blocked_by", blocked_by)
        object.__setattr__(self, "capital", capital)
        object.__setattr__(self, "risk_percent", risk_percent)
        object.__setattr__(self, "exposure", exposure)
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "exchange_info_ok", exchange_info_ok)
        object.__setattr__(self, "strategy_version", self.strategy_version.strip() or "v2_risk_safe")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RiskDecision":
        mapping = dict(data)
        return cls(
            allowed=_require_keys(mapping, ("allowed",), "allowed"),
            reason=_require_keys(mapping, ("reason",), "reason"),
            blocked_by=_require_keys(mapping, ("blocked_by",), "blocked_by"),
            capital=_require_keys(mapping, ("capital",), "capital"),
            risk_percent=_require_keys(mapping, ("risk_percent",), "risk_percent"),
            exposure=_require_keys(mapping, ("exposure",), "exposure"),
            timestamp=_require_keys(mapping, ("timestamp",), "timestamp"),
            strategy_version=mapping.get("strategy_version", "v2_risk_safe"),
            exchange_info_ok=mapping.get("exchange_info_ok", True),
            notes=mapping.get("notes", ""),
        )


@dataclass(frozen=True, slots=True)
class PaperOrder(DomainModel):
    symbol: str
    direction: Direction
    entry: Decimal
    quantity: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    opened_at: datetime
    status: OrderStatus
    source: DataSource
    paper: bool = True
    trading_mode: TradingMode = TradingMode.PAPER
    order_id: Optional[int] = None

    def __post_init__(self) -> None:
        parse_bool_true_only(self.paper, "paper")
        if parse_enum(self.trading_mode, TradingMode, "trading_mode") is not TradingMode.PAPER:
            raise DomainValidationError("trading_mode must be PAPER.")
        symbol = parse_symbol(self.symbol)
        direction = parse_direction(self.direction)
        entry = parse_decimal(self.entry, "entry")
        quantity = parse_decimal(self.quantity, "quantity")
        stop_loss = parse_decimal(self.stop_loss, "stop_loss")
        take_profit = parse_decimal(self.take_profit, "take_profit")
        opened_at = parse_timezone_aware_datetime(self.opened_at, "opened_at")
        status = parse_enum(self.status, OrderStatus, "status")
        source = parse_enum(self.source, DataSource, "source")
        ensure_price_coherence(direction, entry, stop_loss, take_profit)
        order_id = int(self.order_id) if self.order_id is not None else None
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "entry", entry)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "stop_loss", stop_loss)
        object.__setattr__(self, "take_profit", take_profit)
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "order_id", order_id)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PaperOrder":
        mapping = dict(data)
        return cls(
            symbol=_require_keys(mapping, ("symbol",), "symbol"),
            direction=_require_keys(mapping, ("direction",), "direction"),
            entry=_require_keys(mapping, ("entry",), "entry"),
            quantity=_require_keys(mapping, ("quantity",), "quantity"),
            stop_loss=_require_keys(mapping, ("stop_loss",), "stop_loss"),
            take_profit=_require_keys(mapping, ("take_profit",), "take_profit"),
            opened_at=_require_keys(mapping, ("opened_at",), "opened_at"),
            status=_require_keys(mapping, ("status",), "status"),
            source=_require_keys(mapping, ("source",), "source"),
            paper=mapping.get("paper", True),
            trading_mode=mapping.get("trading_mode", TradingMode.PAPER),
            order_id=mapping.get("order_id"),
        )


@dataclass(frozen=True, slots=True)
class Fill(DomainModel):
    price: Decimal
    quantity: Decimal
    filled_at: datetime
    fee: Decimal = Decimal("0")
    source: DataSource = DataSource.PAPER
    is_real: bool = False
    order_id: Optional[int] = None

    def __post_init__(self) -> None:
        parse_bool_false_only(self.is_real, "is_real")
        price = parse_decimal(self.price, "price")
        quantity = parse_decimal(self.quantity, "quantity")
        fee = parse_decimal(self.fee, "fee", allow_zero=True)
        filled_at = parse_timezone_aware_datetime(self.filled_at, "filled_at")
        source = parse_enum(self.source, DataSource, "source")
        order_id = int(self.order_id) if self.order_id is not None else None
        object.__setattr__(self, "price", price)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "fee", fee)
        object.__setattr__(self, "filled_at", filled_at)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "order_id", order_id)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Fill":
        mapping = dict(data)
        return cls(
            price=_require_keys(mapping, ("price",), "price"),
            quantity=_require_keys(mapping, ("quantity",), "quantity"),
            filled_at=_require_keys(mapping, ("filled_at",), "filled_at"),
            fee=mapping.get("fee", Decimal("0")),
            source=mapping.get("source", DataSource.PAPER),
            is_real=mapping.get("is_real", False),
            order_id=mapping.get("order_id"),
        )


@dataclass(frozen=True, slots=True)
class Position(DomainModel):
    symbol: str
    direction: Direction
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    quantity: Decimal
    opened_at: datetime
    status: PositionStatus
    source: DataSource
    paper: bool = True
    trading_mode: TradingMode = TradingMode.PAPER
    unrealized_pnl: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        parse_bool_true_only(self.paper, "paper")
        if parse_enum(self.trading_mode, TradingMode, "trading_mode") is not TradingMode.PAPER:
            raise DomainValidationError("trading_mode must be PAPER.")
        symbol = parse_symbol(self.symbol)
        direction = parse_direction(self.direction)
        entry = parse_decimal(self.entry, "entry")
        stop_loss = parse_decimal(self.stop_loss, "stop_loss")
        take_profit = parse_decimal(self.take_profit, "take_profit")
        quantity = parse_decimal(self.quantity, "quantity")
        opened_at = parse_timezone_aware_datetime(self.opened_at, "opened_at")
        status = parse_enum(self.status, PositionStatus, "status")
        source = parse_enum(self.source, DataSource, "source")
        unrealized_pnl = parse_decimal(self.unrealized_pnl, "unrealized_pnl", allow_zero=True, allow_negative=True)
        ensure_price_coherence(direction, entry, stop_loss, take_profit)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "entry", entry)
        object.__setattr__(self, "stop_loss", stop_loss)
        object.__setattr__(self, "take_profit", take_profit)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "unrealized_pnl", unrealized_pnl)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Position":
        mapping = dict(data)
        return cls(
            symbol=_require_keys(mapping, ("symbol",), "symbol"),
            direction=_require_keys(mapping, ("direction",), "direction"),
            entry=_require_keys(mapping, ("entry",), "entry"),
            stop_loss=_require_keys(mapping, ("stop_loss",), "stop_loss"),
            take_profit=_require_keys(mapping, ("take_profit",), "take_profit"),
            quantity=_require_keys(mapping, ("quantity",), "quantity"),
            opened_at=_require_keys(mapping, ("opened_at",), "opened_at"),
            status=_require_keys(mapping, ("status",), "status"),
            source=_require_keys(mapping, ("source",), "source"),
            paper=mapping.get("paper", True),
            trading_mode=mapping.get("trading_mode", TradingMode.PAPER),
            unrealized_pnl=mapping.get("unrealized_pnl", Decimal("0")),
        )


@dataclass(frozen=True, slots=True)
class TradeResult(DomainModel):
    symbol: str
    direction: Direction
    entry: Decimal
    exit_price: Decimal
    quantity: Decimal
    pnl_percent: Decimal
    pnl_reais: Decimal
    status: TradeResultStatus
    reason: str
    opened_at: datetime
    closed_at: datetime
    source: DataSource
    paper: bool = True
    trading_mode: TradingMode = TradingMode.PAPER
    strategy_version: str = "v2_risk_safe"

    def __post_init__(self) -> None:
        parse_bool_true_only(self.paper, "paper")
        if parse_enum(self.trading_mode, TradingMode, "trading_mode") is not TradingMode.PAPER:
            raise DomainValidationError("trading_mode must be PAPER.")
        symbol = parse_symbol(self.symbol)
        direction = parse_direction(self.direction)
        entry = parse_decimal(self.entry, "entry")
        exit_price = parse_decimal(self.exit_price, "exit_price")
        quantity = parse_decimal(self.quantity, "quantity")
        pnl_percent = parse_decimal(self.pnl_percent, "pnl_percent", allow_zero=True, allow_negative=True)
        pnl_reais = parse_decimal(self.pnl_reais, "pnl_reais", allow_zero=True, allow_negative=True)
        status = parse_enum(self.status, TradeResultStatus, "status")
        opened_at = parse_timezone_aware_datetime(self.opened_at, "opened_at")
        closed_at = parse_timezone_aware_datetime(self.closed_at, "closed_at")
        source = parse_enum(self.source, DataSource, "source")
        if closed_at < opened_at:
            raise DomainValidationError("closed_at cannot be earlier than opened_at.")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "entry", entry)
        object.__setattr__(self, "exit_price", exit_price)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "pnl_percent", pnl_percent)
        object.__setattr__(self, "pnl_reais", pnl_reais)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "closed_at", closed_at)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "strategy_version", self.strategy_version.strip() or "v2_risk_safe")

    @property
    def resultado(self) -> str:
        if self.pnl_reais > 0:
            return "GANHO"
        if self.pnl_reais < 0:
            return "PERDA"
        return "EMPATE"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TradeResult":
        mapping = dict(data)
        return cls(
            symbol=_require_keys(mapping, ("symbol",), "symbol"),
            direction=_require_keys(mapping, ("direction",), "direction"),
            entry=_require_keys(mapping, ("entry",), "entry"),
            exit_price=_require_keys(mapping, ("exit_price",), "exit_price"),
            quantity=_require_keys(mapping, ("quantity",), "quantity"),
            pnl_percent=_require_keys(mapping, ("pnl_percent",), "pnl_percent"),
            pnl_reais=_require_keys(mapping, ("pnl_reais",), "pnl_reais"),
            status=_require_keys(mapping, ("status",), "status"),
            reason=_require_keys(mapping, ("reason",), "reason"),
            opened_at=_require_keys(mapping, ("opened_at",), "opened_at"),
            closed_at=_require_keys(mapping, ("closed_at",), "closed_at"),
            source=_require_keys(mapping, ("source",), "source"),
            paper=mapping.get("paper", True),
            trading_mode=mapping.get("trading_mode", TradingMode.PAPER),
            strategy_version=mapping.get("strategy_version", "v2_risk_safe"),
        )
