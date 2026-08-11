from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value

from .errors import HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError
from .market_structure_research_contract import (
    MarketStructureResearchContract,
    verify_market_structure_research_contract,
)
from . import offline_market_structure_detector as phase51

MARKET_STRUCTURE_LOCAL_TRANSITION_SCHEMA_VERSION = 1
MARKET_STRUCTURE_LOCAL_TRANSITION_ID = "market_structure_local_transition"
MARKET_STRUCTURE_LOCAL_TRANSITION_VERSION = "phase60_local_structural_transition_v1"
MARKET_STRUCTURE_LOCAL_TRANSITION_PURPOSE = "offline_historical_research"
MARKET_STRUCTURE_LOCAL_TRANSITION_ALLOWED_TYPES = ("bos", "choch", "none", "indeterminate")
MARKET_STRUCTURE_LOCAL_TRANSITION_ALLOWED_DIRECTIONS = ("bullish", "bearish", "none")
MARKET_STRUCTURE_LOCAL_TRANSITION_ALLOWED_LOCAL_STRUCTURES = ("bullish", "bearish", "indeterminate")
MARKET_STRUCTURE_LOCAL_TRANSITION_ALLOWED_CONFIRMATION_STATES = (
    "confirmed",
    "none",
    "indeterminate",
)
MARKET_STRUCTURE_LOCAL_TRANSITION_NON_OPERATIONAL_DECLARATION = (
    "This local structural transition detector is research-only and does not authorize replay, backtest, "
    "walk-forward, performance evaluation, ranking, scoring, paper trading, live trading, exchange connectivity, "
    "execution, or order submission."
)


class MarketStructureLocalTransitionError(HistoricalDataError):
    pass


class MarketStructureLocalTransitionValidationError(
    MarketStructureLocalTransitionError,
    HistoricalDataValidationError,
):
    pass


class MarketStructureLocalTransitionIntegrityError(
    MarketStructureLocalTransitionError,
    HistoricalDataIntegrityError,
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        serialize_value(_thaw_read_only_value(payload)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash_payload(payload: Any) -> str:
    try:
        return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    except (TypeError, ValueError) as exc:
        raise MarketStructureLocalTransitionValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketStructureLocalTransitionValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise MarketStructureLocalTransitionValidationError(f"{field_name} must be a 64-character hex digest.")
    return digest


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise MarketStructureLocalTransitionValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise MarketStructureLocalTransitionValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise MarketStructureLocalTransitionValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise MarketStructureLocalTransitionValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_decimal(
    value: Any,
    field_name: str,
    *,
    allow_zero: bool = True,
    allow_negative: bool = False,
) -> Decimal:
    if type(value) is bool:
        raise MarketStructureLocalTransitionValidationError(f"{field_name} must be numeric.")
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MarketStructureLocalTransitionValidationError(f"{field_name} must be numeric.") from exc
    if not decimal_value.is_finite():
        raise MarketStructureLocalTransitionValidationError(f"{field_name} must be finite.")
    if not allow_negative and decimal_value < 0:
        raise MarketStructureLocalTransitionValidationError(f"{field_name} must be non-negative.")
    if not allow_zero and decimal_value == 0:
        raise MarketStructureLocalTransitionValidationError(f"{field_name} must be greater than zero.")
    return decimal_value


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise MarketStructureLocalTransitionValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise MarketStructureLocalTransitionValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise MarketStructureLocalTransitionValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketStructureLocalTransitionValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _freeze_read_only_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_read_only_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_read_only_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_read_only_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_read_only_value(item) for item in value)
    if isinstance(value, frozenset):
        return frozenset(_freeze_read_only_value(item) for item in value)
    return value


def _thaw_read_only_value(value: Any) -> Any:
    if isinstance(value, MappingProxyType) or isinstance(value, Mapping):
        return {key: _thaw_read_only_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_thaw_read_only_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_thaw_read_only_value(item) for item in value)
    if isinstance(value, set) or isinstance(value, frozenset):
        thawed_items = [_thaw_read_only_value(item) for item in value]
        return tuple(sorted(thawed_items, key=_canonical_json))
    return value


def _require_exact_keys(mapping: Mapping[str, Any], field_name: str, expected_keys: set[str]) -> None:
    extra = sorted(set(mapping) - expected_keys)
    missing = sorted(expected_keys - set(mapping))
    if extra or missing:
        parts: list[str] = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected {', '.join(extra)}")
        raise MarketStructureLocalTransitionValidationError(
            f"{field_name} has invalid fields: {'; '.join(parts)}."
        )


def _parse_timeframe_delta(timeframe: str) -> timedelta:
    normalized = _require_str(timeframe, "timeframe").upper()
    match = re.fullmatch(r"(?P<count>\d+)(?P<unit>[MHDW])", normalized)
    if not match:
        raise MarketStructureLocalTransitionValidationError("timeframe must use a supported interval like 1H or 1D.")
    count = int(match.group("count"))
    unit = match.group("unit")
    if unit == "M":
        return timedelta(minutes=count)
    if unit == "H":
        return timedelta(hours=count)
    if unit == "D":
        return timedelta(days=count)
    return timedelta(weeks=count)


def _coerce_candles(candles: Any) -> list[Mapping[str, Any]]:
    if hasattr(candles, "to_dict") and callable(getattr(candles, "to_dict")):
        try:
            coerced = candles.to_dict(orient="records")
        except TypeError:
            coerced = candles.to_dict("records")
        if not isinstance(coerced, list):
            raise MarketStructureLocalTransitionValidationError("candles must be a sequence of mappings.")
        return coerced
    if isinstance(candles, (str, bytes)) or not isinstance(candles, Sequence):
        raise MarketStructureLocalTransitionValidationError("candles must be a sequence of mappings.")
    return list(candles)


@dataclass(frozen=True, slots=True)
class _LocalCandle:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None
    complete: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", _require_utc_datetime(self.timestamp, "timestamp"))
        object.__setattr__(self, "open", _require_decimal(self.open, "open", allow_zero=False))
        object.__setattr__(self, "high", _require_decimal(self.high, "high", allow_zero=False))
        object.__setattr__(self, "low", _require_decimal(self.low, "low", allow_zero=False))
        object.__setattr__(self, "close", _require_decimal(self.close, "close", allow_zero=False))
        if self.volume is not None:
            object.__setattr__(self, "volume", _require_decimal(self.volume, "volume"))
        object.__setattr__(self, "complete", _require_bool(self.complete, "complete"))
        if self.high < self.low:
            raise MarketStructureLocalTransitionValidationError("high must be greater than or equal to low.")
        if self.high < self.open or self.high < self.close:
            raise MarketStructureLocalTransitionValidationError("high must cover open and close.")
        if self.low > self.open or self.low > self.close:
            raise MarketStructureLocalTransitionValidationError("low must cover open and close.")
        if self.volume is not None and self.volume < 0:
            raise MarketStructureLocalTransitionValidationError("volume must be non-negative.")
        if self.complete is not True:
            raise MarketStructureLocalTransitionValidationError("incomplete candle is not allowed.")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "timestamp": _utc_iso(self.timestamp),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "complete": self.complete,
        }


@dataclass(frozen=True, slots=True)
class _LocalSwing:
    kind: str
    timestamp: datetime
    candle_index: int
    confirmation_timestamp: datetime
    level: Decimal
    timeframe: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _require_str(self.kind, "kind"))
        object.__setattr__(self, "timestamp", _require_utc_datetime(self.timestamp, "timestamp"))
        object.__setattr__(self, "candle_index", _require_int(self.candle_index, "candle_index", allow_zero=True))
        object.__setattr__(self, "confirmation_timestamp", _require_utc_datetime(self.confirmation_timestamp, "confirmation_timestamp"))
        object.__setattr__(self, "level", _require_decimal(self.level, "level", allow_negative=False))
        object.__setattr__(self, "timeframe", _require_str(self.timeframe, "timeframe").upper())

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "timestamp": _utc_iso(self.timestamp),
            "candle_index": self.candle_index,
            "confirmation_timestamp": _utc_iso(self.confirmation_timestamp),
            "level": self.level,
            "timeframe": self.timeframe,
        }


@dataclass(frozen=True, slots=True)
class MarketStructureLocalTransition:
    schema_version: int = MARKET_STRUCTURE_LOCAL_TRANSITION_SCHEMA_VERSION
    result_id: str = ""
    result_hash: str = ""
    contract_hash: str = ""
    dataset_hash: str = ""
    symbol: str = ""
    market: str = ""
    timeframe: str = ""
    effective_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    local_structure_before: str = "indeterminate"
    transition_type: str = "indeterminate"
    direction: str = "none"
    protected_pivot_id: str = ""
    protected_pivot_kind: str = ""
    protected_pivot_timestamp: datetime | None = None
    protected_pivot_confirmation_timestamp: datetime | None = None
    protected_pivot_price: Decimal | None = None
    broken_level: Decimal | None = None
    break_confirmation_timestamp: datetime | None = None
    break_event_ids: tuple[str, ...] = field(default_factory=tuple, repr=False)
    displacement_event_ids: tuple[str, ...] = field(default_factory=tuple, repr=False)
    confirmation_state: str = "indeterminate"
    reasons: tuple[str, ...] = field(default_factory=tuple, repr=False)
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "result_id", _require_hex_digest(self.result_id, "result_id") if self.result_id else "")
        object.__setattr__(self, "result_hash", _require_hex_digest(self.result_hash, "result_hash") if self.result_hash else "")
        object.__setattr__(self, "contract_hash", _require_hex_digest(self.contract_hash, "contract_hash"))
        object.__setattr__(self, "dataset_hash", _require_hex_digest(self.dataset_hash, "dataset_hash"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol"))
        object.__setattr__(self, "market", _require_str(self.market, "market"))
        object.__setattr__(self, "timeframe", _require_str(self.timeframe, "timeframe").upper())
        object.__setattr__(self, "effective_at", _require_utc_datetime(self.effective_at, "effective_at"))
        object.__setattr__(self, "local_structure_before", _require_str(self.local_structure_before, "local_structure_before").lower())
        object.__setattr__(self, "transition_type", _require_str(self.transition_type, "transition_type").lower())
        object.__setattr__(self, "direction", _require_str(self.direction, "direction").lower())
        object.__setattr__(self, "protected_pivot_id", _require_str(self.protected_pivot_id, "protected_pivot_id") if self.protected_pivot_id else "")
        object.__setattr__(self, "protected_pivot_kind", _require_str(self.protected_pivot_kind, "protected_pivot_kind") if self.protected_pivot_kind else "")
        if self.protected_pivot_timestamp is not None:
            object.__setattr__(self, "protected_pivot_timestamp", _require_utc_datetime(self.protected_pivot_timestamp, "protected_pivot_timestamp"))
        if self.protected_pivot_confirmation_timestamp is not None:
            object.__setattr__(self, "protected_pivot_confirmation_timestamp", _require_utc_datetime(self.protected_pivot_confirmation_timestamp, "protected_pivot_confirmation_timestamp"))
        if self.protected_pivot_price is not None:
            object.__setattr__(self, "protected_pivot_price", _require_decimal(self.protected_pivot_price, "protected_pivot_price"))
        if self.broken_level is not None:
            object.__setattr__(self, "broken_level", _require_decimal(self.broken_level, "broken_level"))
        if self.break_confirmation_timestamp is not None:
            object.__setattr__(self, "break_confirmation_timestamp", _require_utc_datetime(self.break_confirmation_timestamp, "break_confirmation_timestamp"))
        if not isinstance(self.break_event_ids, tuple):
            object.__setattr__(self, "break_event_ids", tuple(self.break_event_ids))
        if not isinstance(self.displacement_event_ids, tuple):
            object.__setattr__(self, "displacement_event_ids", tuple(self.displacement_event_ids))
        object.__setattr__(self, "confirmation_state", _require_str(self.confirmation_state, "confirmation_state").lower())
        object.__setattr__(self, "reasons", tuple(_require_str(item, "reasons") for item in self.reasons))
        if not isinstance(self.metadata, Mapping):
            raise MarketStructureLocalTransitionValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))

        if self.schema_version != MARKET_STRUCTURE_LOCAL_TRANSITION_SCHEMA_VERSION:
            raise MarketStructureLocalTransitionValidationError("schema_version must be 1.")
        if self.local_structure_before not in MARKET_STRUCTURE_LOCAL_TRANSITION_ALLOWED_LOCAL_STRUCTURES:
            raise MarketStructureLocalTransitionValidationError("local_structure_before must be bullish, bearish, or indeterminate.")
        if self.transition_type not in MARKET_STRUCTURE_LOCAL_TRANSITION_ALLOWED_TYPES:
            raise MarketStructureLocalTransitionValidationError("transition_type must be bos, choch, none, or indeterminate.")
        if self.direction not in MARKET_STRUCTURE_LOCAL_TRANSITION_ALLOWED_DIRECTIONS:
            raise MarketStructureLocalTransitionValidationError("direction must be bullish, bearish, or none.")
        if self.confirmation_state not in MARKET_STRUCTURE_LOCAL_TRANSITION_ALLOWED_CONFIRMATION_STATES:
            raise MarketStructureLocalTransitionValidationError("confirmation_state is invalid.")

        self._validate_semantics()

        expected_result_id = _hash_payload(self._result_id_payload())
        if self.result_id:
            if self.result_id != expected_result_id:
                raise MarketStructureLocalTransitionIntegrityError("result_id mismatch.")
        else:
            object.__setattr__(self, "result_id", expected_result_id)

        expected_result_hash = _hash_payload(self._result_hash_payload())
        if self.result_hash:
            if self.result_hash != expected_result_hash:
                raise MarketStructureLocalTransitionIntegrityError("result_hash mismatch.")
        else:
            object.__setattr__(self, "result_hash", expected_result_hash)

    def _validate_semantics(self) -> None:
        if self.transition_type == "none":
            if self.direction != "none":
                raise MarketStructureLocalTransitionValidationError("none transition must use direction none.")
            if self.confirmation_state == "confirmed":
                raise MarketStructureLocalTransitionValidationError("none transition cannot be confirmed.")
            if self.broken_level is not None or self.break_confirmation_timestamp is not None:
                raise MarketStructureLocalTransitionValidationError("none transition must not define a break.")
            return

        if self.transition_type == "indeterminate":
            if self.direction != "none":
                raise MarketStructureLocalTransitionValidationError("indeterminate transition must use direction none.")
            if self.confirmation_state == "confirmed":
                raise MarketStructureLocalTransitionValidationError("indeterminate transition cannot be confirmed.")
            return

        if self.direction == "none":
            raise MarketStructureLocalTransitionValidationError("confirmed local transitions require a direction.")

        if self.transition_type == "bos":
            if self.local_structure_before != self.direction:
                raise MarketStructureLocalTransitionValidationError("bos must continue the current local structure.")
        elif self.transition_type == "choch":
            if self.local_structure_before == self.direction:
                raise MarketStructureLocalTransitionValidationError("choch must oppose the current local structure.")
        else:
            raise MarketStructureLocalTransitionValidationError("transition_type is invalid.")

        if self.confirmation_state != "confirmed":
            raise MarketStructureLocalTransitionValidationError("confirmed local transitions must be confirmed.")
        if self.protected_pivot_id == "" or self.protected_pivot_kind == "":
            raise MarketStructureLocalTransitionValidationError("confirmed local transitions require a protected pivot.")
        if self.protected_pivot_price is None or self.broken_level is None or self.break_confirmation_timestamp is None:
            raise MarketStructureLocalTransitionValidationError("confirmed local transitions require break details.")
        if self.break_confirmation_timestamp > self.effective_at:
            raise MarketStructureLocalTransitionValidationError("break confirmation timestamp is inconsistent.")
        if self.protected_pivot_confirmation_timestamp is not None and (
            self.break_confirmation_timestamp < self.protected_pivot_confirmation_timestamp
        ):
            raise MarketStructureLocalTransitionValidationError("break confirmation timestamp is inconsistent.")

    def _result_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_hash": self.contract_hash,
            "dataset_hash": self.dataset_hash,
            "symbol": self.symbol,
            "market": self.market,
            "timeframe": self.timeframe,
            "effective_at": _utc_iso(self.effective_at),
            "local_structure_before": self.local_structure_before,
            "transition_type": self.transition_type,
            "direction": self.direction,
            "protected_pivot_id": self.protected_pivot_id,
            "protected_pivot_kind": self.protected_pivot_kind,
            "protected_pivot_timestamp": _utc_iso(self.protected_pivot_timestamp) if self.protected_pivot_timestamp else None,
            "protected_pivot_confirmation_timestamp": _utc_iso(self.protected_pivot_confirmation_timestamp)
            if self.protected_pivot_confirmation_timestamp
            else None,
            "protected_pivot_price": self.protected_pivot_price,
            "broken_level": self.broken_level,
            "break_confirmation_timestamp": _utc_iso(self.break_confirmation_timestamp) if self.break_confirmation_timestamp else None,
            "break_event_ids": self.break_event_ids,
            "displacement_event_ids": self.displacement_event_ids,
            "confirmation_state": self.confirmation_state,
            "reasons": self.reasons,
            "metadata": _thaw_read_only_value(self.metadata),
        }

    def _result_hash_payload(self) -> dict[str, Any]:
        payload = self._result_id_payload()
        payload["result_id"] = self.result_id
        return payload

    def canonical_payload(self, *, include_result_id: bool = True, include_result_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "contract_hash": self.contract_hash,
            "dataset_hash": self.dataset_hash,
            "symbol": self.symbol,
            "market": self.market,
            "timeframe": self.timeframe,
            "effective_at": _utc_iso(self.effective_at),
            "local_structure_before": self.local_structure_before,
            "transition_type": self.transition_type,
            "direction": self.direction,
            "protected_pivot_id": self.protected_pivot_id,
            "protected_pivot_kind": self.protected_pivot_kind,
            "protected_pivot_timestamp": _utc_iso(self.protected_pivot_timestamp) if self.protected_pivot_timestamp else None,
            "protected_pivot_confirmation_timestamp": _utc_iso(self.protected_pivot_confirmation_timestamp)
            if self.protected_pivot_confirmation_timestamp
            else None,
            "protected_pivot_price": self.protected_pivot_price,
            "broken_level": self.broken_level,
            "break_confirmation_timestamp": _utc_iso(self.break_confirmation_timestamp) if self.break_confirmation_timestamp else None,
            "break_event_ids": self.break_event_ids,
            "displacement_event_ids": self.displacement_event_ids,
            "confirmation_state": self.confirmation_state,
            "reasons": self.reasons,
            "metadata": _thaw_read_only_value(self.metadata),
            "created_at_utc": _utc_iso(self.created_at_utc),
        }
        if include_result_id:
            payload["result_id"] = self.result_id
        if include_result_hash:
            payload["result_hash"] = self.result_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_result_id=True, include_result_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureLocalTransition":
        if not isinstance(data, Mapping):
            raise MarketStructureLocalTransitionValidationError("market structure local transition must be a mapping.")
        _require_exact_keys(
            data,
            "market structure local transition",
            {
                "schema_version",
                "result_id",
                "result_hash",
                "contract_hash",
                "dataset_hash",
                "symbol",
                "market",
                "timeframe",
                "effective_at",
                "local_structure_before",
                "transition_type",
                "direction",
                "protected_pivot_id",
                "protected_pivot_kind",
                "protected_pivot_timestamp",
                "protected_pivot_confirmation_timestamp",
                "protected_pivot_price",
                "broken_level",
                "break_confirmation_timestamp",
                "break_event_ids",
                "displacement_event_ids",
                "confirmation_state",
                "reasons",
                "metadata",
                "created_at_utc",
            },
        )
        try:
            return cls(
                schema_version=data["schema_version"],
                result_id=data.get("result_id", ""),
                result_hash=data.get("result_hash", ""),
                contract_hash=data["contract_hash"],
                dataset_hash=data["dataset_hash"],
                symbol=data["symbol"],
                market=data["market"],
                timeframe=data["timeframe"],
                effective_at=data["effective_at"],
                local_structure_before=data["local_structure_before"],
                transition_type=data["transition_type"],
                direction=data["direction"],
                protected_pivot_id=data.get("protected_pivot_id", ""),
                protected_pivot_kind=data.get("protected_pivot_kind", ""),
                protected_pivot_timestamp=data.get("protected_pivot_timestamp"),
                protected_pivot_confirmation_timestamp=data.get("protected_pivot_confirmation_timestamp"),
                protected_pivot_price=data.get("protected_pivot_price"),
                broken_level=data.get("broken_level"),
                break_confirmation_timestamp=data.get("break_confirmation_timestamp"),
                break_event_ids=tuple(data.get("break_event_ids", ())),
                displacement_event_ids=tuple(data.get("displacement_event_ids", ())),
                confirmation_state=data.get("confirmation_state", "indeterminate"),
                reasons=tuple(data.get("reasons", ())),
                metadata=data.get("metadata", {}),
                created_at_utc=data["created_at_utc"],
            )
        except KeyError as exc:
            raise MarketStructureLocalTransitionValidationError(
                "market structure local transition is incomplete."
            ) from exc


def _event_id(kind: str, candle_index: int, timestamp: datetime) -> str:
    return f"{kind}:{candle_index}:{_utc_iso(timestamp)}"


def _normalize_candle_record(record: Mapping[str, Any], *, field_name: str) -> _LocalCandle:
    if not isinstance(record, Mapping):
        raise MarketStructureLocalTransitionValidationError(f"{field_name} must be a mapping.")
    required = {"timestamp", "open", "high", "low", "close"}
    missing = sorted(required - set(record))
    if missing:
        raise MarketStructureLocalTransitionValidationError(
            f"{field_name} is missing required fields: {', '.join(missing)}."
        )
    timestamp = _require_utc_datetime(record["timestamp"], f"{field_name}.timestamp")
    open_ = _require_decimal(record["open"], f"{field_name}.open", allow_zero=False)
    high_ = _require_decimal(record["high"], f"{field_name}.high", allow_zero=False)
    low_ = _require_decimal(record["low"], f"{field_name}.low", allow_zero=False)
    close_ = _require_decimal(record["close"], f"{field_name}.close", allow_zero=False)
    volume = None
    if "volume" in record and record["volume"] is not None:
        volume = _require_decimal(record["volume"], f"{field_name}.volume")
    complete = _require_bool(record.get("complete", True), f"{field_name}.complete")
    if high_ < low_:
        raise MarketStructureLocalTransitionValidationError(f"{field_name}.high must be greater than or equal to low.")
    if high_ < open_ or high_ < close_:
        raise MarketStructureLocalTransitionValidationError(f"{field_name}.high must cover open and close.")
    if low_ > open_ or low_ > close_:
        raise MarketStructureLocalTransitionValidationError(f"{field_name}.low must cover open and close.")
    if volume is not None and volume < 0:
        raise MarketStructureLocalTransitionValidationError(f"{field_name}.volume must be non-negative.")
    if complete is not True:
        raise MarketStructureLocalTransitionValidationError("incomplete candle is not allowed.")
    return _LocalCandle(
        timestamp=timestamp,
        open=open_,
        high=high_,
        low=low_,
        close=close_,
        volume=volume,
        complete=complete,
    )


def _normalize_candles(candles: Any, *, timeframe: str) -> tuple[_LocalCandle, ...]:
    delta = _parse_timeframe_delta(timeframe)
    normalized: list[_LocalCandle] = []
    previous_timestamp: datetime | None = None
    for index, record in enumerate(_coerce_candles(candles)):
        candle = _normalize_candle_record(record, field_name=f"candles[{index}]")
        if previous_timestamp is not None:
            if candle.timestamp <= previous_timestamp:
                raise MarketStructureLocalTransitionValidationError("candles must be strictly ascending without duplicate timestamps.")
            if candle.timestamp - previous_timestamp != delta:
                raise MarketStructureLocalTransitionValidationError(
                    f"candles contains missing or misaligned candles for {timeframe}."
                )
        normalized.append(candle)
        previous_timestamp = candle.timestamp
    if not normalized:
        raise MarketStructureLocalTransitionValidationError("candles must not be empty.")
    return tuple(normalized)


def _format_decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _candle_midpoint(candle: _LocalCandle) -> Decimal:
    return (candle.high + candle.low) / Decimal("2")


def _candle_range(candle: _LocalCandle) -> Decimal:
    return candle.high - candle.low


def _is_bullish_displacement(candle: _LocalCandle, avg_range: Decimal, minimum_amplitude: Decimal, atr_multiplier: int) -> bool:
    range_value = _candle_range(candle)
    if range_value < minimum_amplitude:
        return False
    threshold = max(minimum_amplitude, avg_range * Decimal(atr_multiplier))
    return range_value >= threshold and candle.close >= _candle_midpoint(candle)


def _is_bearish_displacement(candle: _LocalCandle, avg_range: Decimal, minimum_amplitude: Decimal, atr_multiplier: int) -> bool:
    range_value = _candle_range(candle)
    if range_value < minimum_amplitude:
        return False
    threshold = max(minimum_amplitude, avg_range * Decimal(atr_multiplier))
    return range_value >= threshold and candle.close <= _candle_midpoint(candle)


def _average_range(candles: tuple[_LocalCandle, ...], lookback: int) -> Decimal:
    if lookback <= 0:
        return Decimal("0")
    window = candles[max(0, len(candles) - lookback) :]
    if not window:
        return Decimal("0")
    total = sum((_candle_range(candle) for candle in window), Decimal("0"))
    return total / Decimal(len(window))


def _confirm_swing(
    swing: Any,
    *,
    candles: tuple[_LocalCandle, ...],
    effective_at: datetime,
    right_window: int,
    timeframe: str,
) -> _LocalSwing | None:
    if isinstance(swing, Mapping):
        kind_value = swing.get("kind")
        candle_index_value = swing.get("candle_index")
        timestamp_value = swing.get("timestamp")
        level_value = swing.get("level")
    else:
        kind_value = getattr(swing, "kind", None)
        candle_index_value = getattr(swing, "candle_index", None)
        timestamp_value = getattr(swing, "timestamp", None)
        level_value = getattr(swing, "level", None)

    kind = _require_str(kind_value, "swing.kind")
    if kind not in {"confirmed_swing_high", "confirmed_swing_low"}:
        return None
    candle_index = _require_int(candle_index_value, "swing.candle_index", allow_zero=True)
    if candle_index + right_window >= len(candles):
        return None
    confirmation_timestamp = candles[candle_index + right_window].timestamp
    if confirmation_timestamp > effective_at:
        return None
    timestamp = _require_utc_datetime(timestamp_value, "swing.timestamp")
    level = _require_decimal(level_value, "swing.level", allow_negative=False)
    return _LocalSwing(
        kind=kind,
        timestamp=timestamp,
        candle_index=candle_index,
        confirmation_timestamp=confirmation_timestamp,
        level=level,
        timeframe=timeframe,
    )


def _extract_confirmed_swings(
    *,
    candles: tuple[_LocalCandle, ...],
    timeframe: str,
    effective_at: datetime,
    contract: MarketStructureResearchContract,
    detection_result: phase51.MarketStructureDetectionResult | None,
    confirmed_swings: Sequence[Any] | None,
) -> tuple[_LocalSwing, ...]:
    right_window = _require_int(contract.swing_definition.parameters["right_window"], "right_window")
    swings: list[_LocalSwing] = []
    if confirmed_swings is None:
        if detection_result is None:
            raise MarketStructureLocalTransitionValidationError(
                "detection_result or confirmed_swings is required."
            )
        source = detection_result.events
    else:
        source = confirmed_swings
    for swing in source:
        normalized = _confirm_swing(
            swing,
            candles=candles,
            effective_at=effective_at,
            right_window=right_window,
            timeframe=timeframe,
        )
        if normalized is not None:
            swings.append(normalized)
    swings.sort(key=lambda item: (item.confirmation_timestamp, item.candle_index, item.kind))
    return tuple(swings)


def _pairwise_latest_context(
    confirmed_swings: tuple[_LocalSwing, ...],
) -> tuple[str, _LocalSwing | None, _LocalSwing | None, _LocalSwing | None, _LocalSwing | None]:
    highs = [swing for swing in confirmed_swings if swing.kind == "confirmed_swing_high"]
    lows = [swing for swing in confirmed_swings if swing.kind == "confirmed_swing_low"]
    if len(highs) < 2 or len(lows) < 2:
        return "indeterminate", highs[-1] if highs else None, lows[-1] if lows else None, None, None

    prev_high, last_high = highs[-2], highs[-1]
    prev_low, last_low = lows[-2], lows[-1]
    bullish = last_high.level > prev_high.level and last_low.level > prev_low.level
    bearish = last_high.level < prev_high.level and last_low.level < prev_low.level
    if bullish:
        return "bullish", last_high, last_low, prev_high, prev_low
    if bearish:
        return "bearish", last_high, last_low, prev_high, prev_low
    return "indeterminate", last_high, last_low, prev_high, prev_low


def _build_no_transition(
    *,
    contract_hash: str,
    dataset_hash: str,
    symbol: str,
    market: str,
    timeframe: str,
    effective_at: datetime,
    local_structure_before: str,
    confirmation_state: str,
    reasons: tuple[str, ...],
    metadata: Mapping[str, Any],
    created_at_utc: datetime,
) -> MarketStructureLocalTransition:
    return MarketStructureLocalTransition(
        contract_hash=contract_hash,
        dataset_hash=dataset_hash,
        symbol=symbol,
        market=market,
        timeframe=timeframe,
        effective_at=effective_at,
        local_structure_before=local_structure_before,
        transition_type="none" if local_structure_before != "indeterminate" else "indeterminate",
        direction="none",
        protected_pivot_id="",
        protected_pivot_kind="",
        protected_pivot_timestamp=None,
        protected_pivot_confirmation_timestamp=None,
        protected_pivot_price=None,
        broken_level=None,
        break_confirmation_timestamp=None,
        break_event_ids=(),
        displacement_event_ids=(),
        confirmation_state=confirmation_state,
        reasons=reasons,
        metadata=metadata,
        created_at_utc=created_at_utc,
    )


def _detect_local_transition(
    *,
    candles: tuple[_LocalCandle, ...],
    contract: MarketStructureResearchContract,
    dataset_hash: str,
    symbol: str,
    market: str,
    timeframe: str,
    effective_at: datetime,
    confirmed_swings: tuple[_LocalSwing, ...],
    metadata: Mapping[str, Any],
    created_at_utc: datetime,
) -> MarketStructureLocalTransition:
    local_structure_before, last_high, last_low, prev_high, prev_low = _pairwise_latest_context(confirmed_swings)
    if local_structure_before == "indeterminate":
        if len([swing for swing in confirmed_swings if swing.kind == "confirmed_swing_high"]) < 2 or len(
            [swing for swing in confirmed_swings if swing.kind == "confirmed_swing_low"]
        ) < 2:
            return _build_no_transition(
                contract_hash=contract.contract_hash,
                dataset_hash=dataset_hash,
                symbol=symbol,
                market=market,
                timeframe=timeframe,
                effective_at=effective_at,
                local_structure_before="indeterminate",
                confirmation_state="indeterminate",
                reasons=("insufficient_confirmed_swings",),
                metadata=metadata,
                created_at_utc=created_at_utc,
            )

    assert last_high is not None or last_low is not None
    if local_structure_before == "bullish":
        assert last_high is not None and last_low is not None and prev_high is not None and prev_low is not None
        protected_continuation = last_high
        protected_opposite = last_low
        start_timestamp = max(protected_continuation.confirmation_timestamp, protected_opposite.confirmation_timestamp)
        candidate_candles = [candle for candle in candles if start_timestamp <= candle.timestamp <= effective_at]
        minimum_break_distance = _require_decimal(
            contract.bos_definition.parameters["minimum_break_distance"],
            "minimum_break_distance",
        )
        minimum_displacement = _require_decimal(
            contract.displacement_definition.parameters["minimum_amplitude"],
            "minimum_amplitude",
        )
        atr_multiplier = _require_int(contract.displacement_definition.parameters["atr_multiplier"], "atr_multiplier")
        range_average_lookback = _require_int(
            contract.displacement_definition.parameters["range_average_lookback"],
            "range_average_lookback",
        )
        avg_range = _average_range(candles, range_average_lookback)
        for index, candle in enumerate(candidate_candles, start=next(i for i, item in enumerate(candles) if item.timestamp == candidate_candles[0].timestamp) if candidate_candles else len(candles)):
            bullish_break = candle.close > protected_continuation.level + minimum_break_distance
            bearish_break = candle.close < protected_opposite.level - minimum_break_distance
            if bullish_break and _is_bullish_displacement(candle, avg_range, minimum_displacement, atr_multiplier):
                break_event_id = _event_id("break", index, candle.timestamp)
                displacement_event_id = _event_id("displacement", index, candle.timestamp)
                return MarketStructureLocalTransition(
                    contract_hash=contract.contract_hash,
                    dataset_hash=dataset_hash,
                    symbol=symbol,
                    market=market,
                    timeframe=timeframe,
                    effective_at=effective_at,
                    local_structure_before="bullish",
                    transition_type="bos",
                    direction="bullish",
                    protected_pivot_id=_event_id(protected_continuation.kind, protected_continuation.candle_index, protected_continuation.timestamp),
                    protected_pivot_kind=protected_continuation.kind,
                    protected_pivot_timestamp=protected_continuation.timestamp,
                    protected_pivot_confirmation_timestamp=protected_continuation.confirmation_timestamp,
                    protected_pivot_price=protected_continuation.level,
                    broken_level=protected_continuation.level,
                    break_confirmation_timestamp=candle.timestamp,
                    break_event_ids=(break_event_id,),
                    displacement_event_ids=(displacement_event_id,),
                    confirmation_state="confirmed",
                    reasons=(
                        "local_bullish_structure",
                        "continuation_break_confirmed",
                        "displacement_valid",
                    ),
                    metadata=metadata,
                    created_at_utc=created_at_utc,
                )
            if bearish_break and _is_bearish_displacement(candle, avg_range, minimum_displacement, atr_multiplier):
                break_event_id = _event_id("break", index, candle.timestamp)
                displacement_event_id = _event_id("displacement", index, candle.timestamp)
                return MarketStructureLocalTransition(
                    contract_hash=contract.contract_hash,
                    dataset_hash=dataset_hash,
                    symbol=symbol,
                    market=market,
                    timeframe=timeframe,
                    effective_at=effective_at,
                    local_structure_before="bullish",
                    transition_type="choch",
                    direction="bearish",
                    protected_pivot_id=_event_id(protected_opposite.kind, protected_opposite.candle_index, protected_opposite.timestamp),
                    protected_pivot_kind=protected_opposite.kind,
                    protected_pivot_timestamp=protected_opposite.timestamp,
                    protected_pivot_confirmation_timestamp=protected_opposite.confirmation_timestamp,
                    protected_pivot_price=protected_opposite.level,
                    broken_level=protected_opposite.level,
                    break_confirmation_timestamp=candle.timestamp,
                    break_event_ids=(break_event_id,),
                    displacement_event_ids=(displacement_event_id,),
                    confirmation_state="confirmed",
                    reasons=(
                        "local_bullish_structure",
                        "character_change_confirmed",
                        "displacement_valid",
                    ),
                    metadata=metadata,
                    created_at_utc=created_at_utc,
                )
        return _build_no_transition(
            contract_hash=contract.contract_hash,
            dataset_hash=dataset_hash,
            symbol=symbol,
            market=market,
            timeframe=timeframe,
            effective_at=effective_at,
            local_structure_before="bullish",
            confirmation_state="none",
            reasons=("no_confirmed_transition_found",),
            metadata=metadata,
            created_at_utc=created_at_utc,
        )

    if local_structure_before == "bearish":
        assert last_high is not None and last_low is not None and prev_high is not None and prev_low is not None
        protected_continuation = last_low
        protected_opposite = last_high
        start_timestamp = max(protected_continuation.confirmation_timestamp, protected_opposite.confirmation_timestamp)
        candidate_candles = [candle for candle in candles if start_timestamp <= candle.timestamp <= effective_at]
        minimum_break_distance = _require_decimal(
            contract.bos_definition.parameters["minimum_break_distance"],
            "minimum_break_distance",
        )
        minimum_displacement = _require_decimal(
            contract.displacement_definition.parameters["minimum_amplitude"],
            "minimum_amplitude",
        )
        atr_multiplier = _require_int(contract.displacement_definition.parameters["atr_multiplier"], "atr_multiplier")
        range_average_lookback = _require_int(
            contract.displacement_definition.parameters["range_average_lookback"],
            "range_average_lookback",
        )
        avg_range = _average_range(candles, range_average_lookback)
        for index, candle in enumerate(candidate_candles, start=next(i for i, item in enumerate(candles) if item.timestamp == candidate_candles[0].timestamp) if candidate_candles else len(candles)):
            bearish_break = candle.close < protected_continuation.level - minimum_break_distance
            bullish_break = candle.close > protected_opposite.level + minimum_break_distance
            if bearish_break and _is_bearish_displacement(candle, avg_range, minimum_displacement, atr_multiplier):
                break_event_id = _event_id("break", index, candle.timestamp)
                displacement_event_id = _event_id("displacement", index, candle.timestamp)
                return MarketStructureLocalTransition(
                    contract_hash=contract.contract_hash,
                    dataset_hash=dataset_hash,
                    symbol=symbol,
                    market=market,
                    timeframe=timeframe,
                    effective_at=effective_at,
                    local_structure_before="bearish",
                    transition_type="bos",
                    direction="bearish",
                    protected_pivot_id=_event_id(protected_continuation.kind, protected_continuation.candle_index, protected_continuation.timestamp),
                    protected_pivot_kind=protected_continuation.kind,
                    protected_pivot_timestamp=protected_continuation.timestamp,
                    protected_pivot_confirmation_timestamp=protected_continuation.confirmation_timestamp,
                    protected_pivot_price=protected_continuation.level,
                    broken_level=protected_continuation.level,
                    break_confirmation_timestamp=candle.timestamp,
                    break_event_ids=(break_event_id,),
                    displacement_event_ids=(displacement_event_id,),
                    confirmation_state="confirmed",
                    reasons=(
                        "local_bearish_structure",
                        "continuation_break_confirmed",
                        "displacement_valid",
                    ),
                    metadata=metadata,
                    created_at_utc=created_at_utc,
                )
            if bullish_break and _is_bullish_displacement(candle, avg_range, minimum_displacement, atr_multiplier):
                break_event_id = _event_id("break", index, candle.timestamp)
                displacement_event_id = _event_id("displacement", index, candle.timestamp)
                return MarketStructureLocalTransition(
                    contract_hash=contract.contract_hash,
                    dataset_hash=dataset_hash,
                    symbol=symbol,
                    market=market,
                    timeframe=timeframe,
                    effective_at=effective_at,
                    local_structure_before="bearish",
                    transition_type="choch",
                    direction="bullish",
                    protected_pivot_id=_event_id(protected_opposite.kind, protected_opposite.candle_index, protected_opposite.timestamp),
                    protected_pivot_kind=protected_opposite.kind,
                    protected_pivot_timestamp=protected_opposite.timestamp,
                    protected_pivot_confirmation_timestamp=protected_opposite.confirmation_timestamp,
                    protected_pivot_price=protected_opposite.level,
                    broken_level=protected_opposite.level,
                    break_confirmation_timestamp=candle.timestamp,
                    break_event_ids=(break_event_id,),
                    displacement_event_ids=(displacement_event_id,),
                    confirmation_state="confirmed",
                    reasons=(
                        "local_bearish_structure",
                        "character_change_confirmed",
                        "displacement_valid",
                    ),
                    metadata=metadata,
                    created_at_utc=created_at_utc,
                )
        return _build_no_transition(
            contract_hash=contract.contract_hash,
            dataset_hash=dataset_hash,
            symbol=symbol,
            market=market,
            timeframe=timeframe,
            effective_at=effective_at,
            local_structure_before="bearish",
            confirmation_state="none",
            reasons=("no_confirmed_transition_found",),
            metadata=metadata,
            created_at_utc=created_at_utc,
        )

    return _build_no_transition(
        contract_hash=contract.contract_hash,
        dataset_hash=dataset_hash,
        symbol=symbol,
        market=market,
        timeframe=timeframe,
        effective_at=effective_at,
        local_structure_before="indeterminate",
        confirmation_state="indeterminate",
        reasons=("insufficient_local_structure",),
        metadata=metadata,
        created_at_utc=created_at_utc,
    )


def build_market_structure_local_transition(
    *,
    contract: MarketStructureResearchContract,
    candles: Sequence[Mapping[str, Any]] | Any,
    dataset_hash: str,
    symbol: str,
    market: str,
    timeframe: str,
    effective_at: datetime | None = None,
    detection_result: phase51.MarketStructureDetectionResult | None = None,
    confirmed_swings: Sequence[Any] | None = None,
    created_at_utc: datetime | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> MarketStructureLocalTransition:
    verified_contract = verify_market_structure_research_contract(contract)
    normalized_candles = _normalize_candles(candles, timeframe=timeframe)
    effective_at_utc = _require_utc_datetime(effective_at or normalized_candles[-1].timestamp, "effective_at")
    if effective_at_utc > normalized_candles[-1].timestamp:
        effective_at_utc = normalized_candles[-1].timestamp
    if detection_result is not None:
        if detection_result.contract_hash != verified_contract.contract_hash:
            raise MarketStructureLocalTransitionValidationError("detection_result contract_hash mismatch.")
        if detection_result.dataset_hash != dataset_hash:
            raise MarketStructureLocalTransitionValidationError("detection_result dataset_hash mismatch.")
        if detection_result.symbol != symbol:
            raise MarketStructureLocalTransitionValidationError("detection_result symbol mismatch.")
        if detection_result.market != market:
            raise MarketStructureLocalTransitionValidationError("detection_result market mismatch.")
        if detection_result.timeframe.upper() != timeframe.upper():
            raise MarketStructureLocalTransitionValidationError("detection_result timeframe mismatch.")
        if effective_at_utc < detection_result.first_timestamp:
            raise MarketStructureLocalTransitionValidationError("effective_at precedes detection_result coverage.")
    normalized_swings = _extract_confirmed_swings(
        candles=normalized_candles,
        timeframe=timeframe,
        effective_at=effective_at_utc,
        contract=verified_contract,
        detection_result=detection_result,
        confirmed_swings=confirmed_swings,
    )
    normalized_metadata = _freeze_read_only_value(dict(metadata or {}))
    transition = _detect_local_transition(
        candles=normalized_candles,
        contract=verified_contract,
        dataset_hash=dataset_hash,
        symbol=symbol,
        market=market,
        timeframe=timeframe,
        effective_at=effective_at_utc,
        confirmed_swings=normalized_swings,
        metadata=normalized_metadata,
        created_at_utc=created_at_utc or datetime.now(timezone.utc),
    )
    return verify_market_structure_local_transition(transition)


def detect_market_structure_local_transition(
    *,
    contract: MarketStructureResearchContract,
    candles: Sequence[Mapping[str, Any]] | Any,
    dataset_hash: str,
    symbol: str,
    market: str,
    timeframe: str,
    effective_at: datetime | None = None,
    detection_result: phase51.MarketStructureDetectionResult | None = None,
    confirmed_swings: Sequence[Any] | None = None,
    created_at_utc: datetime | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> MarketStructureLocalTransition:
    return build_market_structure_local_transition(
        contract=contract,
        candles=candles,
        dataset_hash=dataset_hash,
        symbol=symbol,
        market=market,
        timeframe=timeframe,
        effective_at=effective_at,
        detection_result=detection_result,
        confirmed_swings=confirmed_swings,
        created_at_utc=created_at_utc,
        metadata=metadata,
    )


def verify_market_structure_local_transition(
    transition: MarketStructureLocalTransition,
) -> MarketStructureLocalTransition:
    if not isinstance(transition, MarketStructureLocalTransition):
        raise MarketStructureLocalTransitionValidationError("market structure local transition is required.")
    expected_result_id = _hash_payload(transition._result_id_payload())
    if transition.result_id != expected_result_id:
        raise MarketStructureLocalTransitionIntegrityError("result_id mismatch.")
    expected_result_hash = _hash_payload(transition._result_hash_payload())
    if transition.result_hash != expected_result_hash:
        raise MarketStructureLocalTransitionIntegrityError("result_hash mismatch.")
    return transition


def market_structure_local_transition_to_dict(
    transition: MarketStructureLocalTransition,
) -> dict[str, Any]:
    if not isinstance(transition, MarketStructureLocalTransition):
        raise MarketStructureLocalTransitionValidationError("market structure local transition is required.")
    return transition.as_dict()


def market_structure_local_transition_from_dict(
    data: Mapping[str, Any],
) -> MarketStructureLocalTransition:
    return MarketStructureLocalTransition.from_dict(data)


__all__ = [
    "MARKET_STRUCTURE_LOCAL_TRANSITION_ALLOWED_CONFIRMATION_STATES",
    "MARKET_STRUCTURE_LOCAL_TRANSITION_ALLOWED_DIRECTIONS",
    "MARKET_STRUCTURE_LOCAL_TRANSITION_ALLOWED_LOCAL_STRUCTURES",
    "MARKET_STRUCTURE_LOCAL_TRANSITION_ALLOWED_TYPES",
    "MARKET_STRUCTURE_LOCAL_TRANSITION_ID",
    "MARKET_STRUCTURE_LOCAL_TRANSITION_NON_OPERATIONAL_DECLARATION",
    "MARKET_STRUCTURE_LOCAL_TRANSITION_PURPOSE",
    "MARKET_STRUCTURE_LOCAL_TRANSITION_SCHEMA_VERSION",
    "MARKET_STRUCTURE_LOCAL_TRANSITION_VERSION",
    "MarketStructureLocalTransition",
    "MarketStructureLocalTransitionError",
    "MarketStructureLocalTransitionIntegrityError",
    "MarketStructureLocalTransitionValidationError",
    "build_market_structure_local_transition",
    "detect_market_structure_local_transition",
    "market_structure_local_transition_from_dict",
    "market_structure_local_transition_to_dict",
    "verify_market_structure_local_transition",
]
