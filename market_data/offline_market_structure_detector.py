from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import math
import re
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value

from .errors import HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError
from .market_structure_research_contract import (
    MarketStructureResearchContract,
    verify_market_structure_research_contract,
)

OFFLINE_MARKET_STRUCTURE_DETECTOR_SCHEMA_VERSION = 1
OFFLINE_MARKET_STRUCTURE_DETECTOR_ID = "offline_market_structure_detector"
OFFLINE_MARKET_STRUCTURE_DETECTOR_VERSION = "phase51_offline_market_structure_detector_v1"
OFFLINE_MARKET_STRUCTURE_DETECTOR_PURPOSE = "offline_historical_research"
OFFLINE_MARKET_STRUCTURE_DETECTOR_ALLOWED_STRUCTURE_STATES = (
    "bullish",
    "bearish",
    "lateral",
    "ambiguous",
    "indeterminate",
)


class OfflineMarketStructureDetectorError(HistoricalDataError):
    pass


class OfflineMarketStructureDetectorValidationError(
    OfflineMarketStructureDetectorError,
    HistoricalDataValidationError,
):
    pass


class OfflineMarketStructureDetectorIntegrityError(
    OfflineMarketStructureDetectorError,
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
        raise OfflineMarketStructureDetectorValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineMarketStructureDetectorValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineMarketStructureDetectorValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineMarketStructureDetectorValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise OfflineMarketStructureDetectorValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise OfflineMarketStructureDetectorValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineMarketStructureDetectorValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_decimal(
    value: Any,
    field_name: str,
    *,
    allow_zero: bool = True,
    allow_negative: bool = False,
) -> Decimal:
    if type(value) is bool:
        raise OfflineMarketStructureDetectorValidationError(f"{field_name} must be numeric.")
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise OfflineMarketStructureDetectorValidationError(f"{field_name} must be numeric.") from exc
    if not decimal_value.is_finite():
        raise OfflineMarketStructureDetectorValidationError(f"{field_name} must be finite.")
    if not allow_negative and decimal_value < 0:
        raise OfflineMarketStructureDetectorValidationError(f"{field_name} must be non-negative.")
    if not allow_zero and decimal_value == 0:
        raise OfflineMarketStructureDetectorValidationError(f"{field_name} must be greater than zero.")
    return decimal_value


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineMarketStructureDetectorValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise OfflineMarketStructureDetectorValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise OfflineMarketStructureDetectorValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineMarketStructureDetectorValidationError(f"{field_name} must be timezone-aware UTC datetime.")
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
    if isinstance(value, Mapping):
        return {key: _thaw_read_only_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_thaw_read_only_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_thaw_read_only_value(item) for item in value)
    if isinstance(value, set) or isinstance(value, frozenset):
        thawed_items = [_thaw_read_only_value(item) for item in value]
        return tuple(sorted(thawed_items, key=_canonical_json))
    return value


def _parse_timeframe_delta(timeframe: str) -> timedelta:
    normalized = _require_str(timeframe, "timeframe").upper()
    match = re.fullmatch(r"(?P<count>\d+)(?P<unit>[MHDW])", normalized)
    if not match:
        raise OfflineMarketStructureDetectorValidationError("timeframe must use a supported interval like 1H or 1D.")
    count = int(match.group("count"))
    unit = match.group("unit")
    if unit == "M":
        return timedelta(minutes=count)
    if unit == "H":
        return timedelta(hours=count)
    if unit == "D":
        return timedelta(days=count)
    return timedelta(weeks=count)


def _timeframe_rank(timeframe: str) -> int:
    return int(_parse_timeframe_delta(timeframe).total_seconds() // 60)


def _coerce_records(records: Any) -> list[Mapping[str, Any]]:
    if hasattr(records, "to_dict") and callable(getattr(records, "to_dict")):
        try:
            coerced = records.to_dict(orient="records")
        except TypeError:
            coerced = records.to_dict("records")
        if not isinstance(coerced, list):
            raise OfflineMarketStructureDetectorValidationError("candles must be a sequence of mappings.")
        return coerced
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise OfflineMarketStructureDetectorValidationError("candles must be a sequence of mappings.")
    return list(records)


def _normalize_candle_record(
    record: Mapping[str, Any],
    *,
    field_name: str,
    incomplete_candle_policy: str,
) -> "_MarketCandle":
    if not isinstance(record, Mapping):
        raise OfflineMarketStructureDetectorValidationError(f"{field_name} must be a mapping.")

    required = {"timestamp", "open", "high", "low", "close"}
    missing = sorted(required - set(record))
    if missing:
        raise OfflineMarketStructureDetectorValidationError(
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
    complete = record.get("complete", True)
    complete = _require_bool(complete, f"{field_name}.complete")

    if incomplete_candle_policy != "reject":
        raise OfflineMarketStructureDetectorValidationError(
            "incomplete_candle_policy must remain reject."
        )
    if complete is not True:
        raise OfflineMarketStructureDetectorValidationError("incomplete candle is not allowed.")

    if high_ < low_:
        raise OfflineMarketStructureDetectorValidationError(f"{field_name}.high must be greater than or equal to low.")
    if high_ < open_ or high_ < close_:
        raise OfflineMarketStructureDetectorValidationError(f"{field_name}.high must cover open and close.")
    if low_ > open_ or low_ > close_:
        raise OfflineMarketStructureDetectorValidationError(f"{field_name}.low must cover open and close.")
    if volume is not None and volume < 0:
        raise OfflineMarketStructureDetectorValidationError(f"{field_name}.volume must be non-negative.")

    return _MarketCandle(
        timestamp=timestamp,
        open=open_,
        high=high_,
        low=low_,
        close=close_,
        volume=volume,
        complete=complete,
    )


def _normalize_candle_series(
    records: Any,
    *,
    field_name: str,
    timeframe: str,
    duplicate_timestamp_policy: str,
    missing_candle_policy: str,
    incomplete_candle_policy: str,
) -> tuple["_MarketCandle", ...]:
    if duplicate_timestamp_policy != "reject":
        raise OfflineMarketStructureDetectorValidationError("duplicate_timestamp_policy must remain reject.")
    if missing_candle_policy != "reject":
        raise OfflineMarketStructureDetectorValidationError("missing_candle_policy must remain reject.")

    delta = _parse_timeframe_delta(timeframe)
    normalized: list[_MarketCandle] = []
    previous_timestamp: datetime | None = None

    for index, record in enumerate(_coerce_records(records)):
        candle = _normalize_candle_record(
            record,
            field_name=f"{field_name}[{index}]",
            incomplete_candle_policy=incomplete_candle_policy,
        )
        if previous_timestamp is not None:
            if candle.timestamp <= previous_timestamp:
                raise OfflineMarketStructureDetectorValidationError(
                    f"{field_name} must be strictly ascending without duplicate timestamps."
                )
            gap = candle.timestamp - previous_timestamp
            if gap != delta:
                raise OfflineMarketStructureDetectorValidationError(
                    f"{field_name} contains missing or misaligned candles for {timeframe}."
                )
        normalized.append(candle)
        previous_timestamp = candle.timestamp

    if not normalized:
        raise OfflineMarketStructureDetectorValidationError(f"{field_name} must not be empty.")
    return tuple(normalized)


def _normalize_candles_by_timeframe(
    candles_by_timeframe: Mapping[str, Any] | None,
    *,
    primary_timeframe: str,
    primary_candles: tuple["_MarketCandle", ...],
    duplicate_timestamp_policy: str,
    missing_candle_policy: str,
    incomplete_candle_policy: str,
) -> Mapping[str, tuple["_MarketCandle", ...]]:
    normalized: dict[str, tuple[_MarketCandle, ...]] = {}
    if candles_by_timeframe is None:
        normalized[primary_timeframe] = primary_candles
        return _freeze_read_only_value(normalized)

    if not isinstance(candles_by_timeframe, Mapping):
        raise OfflineMarketStructureDetectorValidationError("candles_by_timeframe must be a mapping.")

    for key, value in candles_by_timeframe.items():
        timeframe = _require_str(key, "candles_by_timeframe key").upper()
        normalized[timeframe] = _normalize_candle_series(
            value,
            field_name=f"candles_by_timeframe[{timeframe}]",
            timeframe=timeframe,
            duplicate_timestamp_policy=duplicate_timestamp_policy,
            missing_candle_policy=missing_candle_policy,
            incomplete_candle_policy=incomplete_candle_policy,
        )

    if primary_timeframe in normalized:
        if normalized[primary_timeframe] != primary_candles:
            raise OfflineMarketStructureDetectorValidationError(
                "primary candles must match the primary timeframe series."
            )
    else:
        normalized[primary_timeframe] = primary_candles

    return _freeze_read_only_value(normalized)


def _format_decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _candle_midpoint(candle: "_MarketCandle") -> Decimal:
    return (candle.high + candle.low) / Decimal("2")


def _candle_range(candle: "_MarketCandle") -> Decimal:
    return candle.high - candle.low


def _candle_body(candle: "_MarketCandle") -> Decimal:
    return abs(candle.close - candle.open)


def _is_bullish_displacement(candle: "_MarketCandle", avg_range: Decimal, minimum_amplitude: Decimal, atr_multiplier: int) -> bool:
    range_value = _candle_range(candle)
    if range_value < minimum_amplitude:
        return False
    threshold = max(minimum_amplitude, avg_range * Decimal(atr_multiplier))
    return range_value >= threshold and candle.close >= _candle_midpoint(candle)


def _is_bearish_displacement(candle: "_MarketCandle", avg_range: Decimal, minimum_amplitude: Decimal, atr_multiplier: int) -> bool:
    range_value = _candle_range(candle)
    if range_value < minimum_amplitude:
        return False
    threshold = max(minimum_amplitude, avg_range * Decimal(atr_multiplier))
    return range_value >= threshold and candle.close <= _candle_midpoint(candle)


def _event_priority(kind: str) -> int:
    priorities = {
        "candidate_swing_high": 0,
        "candidate_swing_low": 0,
        "confirmed_swing_high": 1,
        "confirmed_swing_low": 1,
        "ambiguous_swing_high": 1,
        "ambiguous_swing_low": 1,
        "bullish_structure": 2,
        "bearish_structure": 2,
        "lateral_structure": 2,
        "ambiguous_structure": 2,
        "indeterminate_structure": 2,
        "equal_highs": 3,
        "equal_lows": 3,
        "internal_liquidity": 3,
        "external_liquidity": 3,
        "protected_high": 3,
        "protected_low": 3,
        "valid_displacement": 4,
        "insufficient_displacement": 4,
        "valid_bos": 5,
        "failed_bos": 5,
        "valid_choch": 5,
        "failed_choch": 5,
        "liquidity_sweep": 6,
        "failed_sweep": 6,
        "false_break": 6,
        "breakout": 6,
        "valid_retest": 7,
        "failed_retest": 7,
        "random_return": 7,
        "valid_trading_range": 8,
        "unclassified_range": 8,
        "candidate_accumulation": 8,
        "candidate_distribution": 8,
        "candidate_reaccumulation": 8,
        "candidate_redistribution": 8,
    }
    return priorities.get(kind, 99)


def _structure_state_event_kind(state: str) -> str:
    return {
        "bullish": "bullish_structure",
        "bearish": "bearish_structure",
        "lateral": "lateral_structure",
        "ambiguous": "ambiguous_structure",
        "indeterminate": "indeterminate_structure",
    }[state]


@dataclass(frozen=True, slots=True)
class _MarketCandle:
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
            raise OfflineMarketStructureDetectorValidationError("high must be greater than or equal to low.")
        if self.high < self.open or self.high < self.close:
            raise OfflineMarketStructureDetectorValidationError("high must cover open and close.")
        if self.low > self.open or self.low > self.close:
            raise OfflineMarketStructureDetectorValidationError("low must cover open and close.")
        if self.volume is not None and self.volume < 0:
            raise OfflineMarketStructureDetectorValidationError("volume must be non-negative.")
        if self.complete is not True:
            raise OfflineMarketStructureDetectorValidationError("incomplete candle is not allowed.")

    def canonical_payload(self) -> dict[str, Any]:
        payload = {
            "timestamp": _utc_iso(self.timestamp),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "complete": self.complete,
        }
        return payload


@dataclass(frozen=True, slots=True)
class _MarketStructureEvent:
    kind: str
    status: str
    timestamp: datetime
    candle_index: int
    timeframe: str
    level: Decimal | None = None
    direction: str = ""
    related_candle_index: int | None = None
    related_timestamp: datetime | None = None
    details: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _require_str(self.kind, "kind"))
        object.__setattr__(self, "status", _require_str(self.status, "status"))
        object.__setattr__(self, "timestamp", _require_utc_datetime(self.timestamp, "timestamp"))
        object.__setattr__(self, "candle_index", _require_int(self.candle_index, "candle_index", allow_zero=True))
        object.__setattr__(self, "timeframe", _require_str(self.timeframe, "timeframe").upper())
        if self.level is not None:
            object.__setattr__(self, "level", _require_decimal(self.level, "level", allow_negative=False))
        if self.direction:
            object.__setattr__(self, "direction", _require_str(self.direction, "direction").lower())
        if self.related_candle_index is not None:
            object.__setattr__(
                self,
                "related_candle_index",
                _require_int(self.related_candle_index, "related_candle_index", allow_zero=True),
            )
        if self.related_timestamp is not None:
            object.__setattr__(self, "related_timestamp", _require_utc_datetime(self.related_timestamp, "related_timestamp"))
        if not isinstance(self.details, Mapping):
            raise OfflineMarketStructureDetectorValidationError("details must be a mapping.")
        object.__setattr__(self, "details", _freeze_read_only_value(dict(self.details)))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status": self.status,
            "timestamp": _utc_iso(self.timestamp),
            "candle_index": self.candle_index,
            "timeframe": self.timeframe,
            "level": self.level,
            "direction": self.direction,
            "related_candle_index": self.related_candle_index,
            "related_timestamp": _utc_iso(self.related_timestamp) if self.related_timestamp else None,
            "details": _thaw_read_only_value(self.details),
        }

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "_MarketStructureEvent":
        if not isinstance(data, Mapping):
            raise OfflineMarketStructureDetectorValidationError("event must be a mapping.")
        return cls(
            kind=data["kind"],
            status=data["status"],
            timestamp=data["timestamp"],
            candle_index=data["candle_index"],
            timeframe=data["timeframe"],
            level=data.get("level"),
            direction=data.get("direction", ""),
            related_candle_index=data.get("related_candle_index"),
            related_timestamp=data.get("related_timestamp"),
            details=data.get("details", {}),
        )


@dataclass(frozen=True, slots=True)
class _SeriesSummary:
    timeframe: str
    state: str
    confirmed_swings: tuple[_MarketStructureEvent, ...]
    confirmed_highs: tuple[_MarketStructureEvent, ...]
    confirmed_lows: tuple[_MarketStructureEvent, ...]
    highest_level: Decimal | None
    lowest_level: Decimal | None
    average_range: Decimal
    first_timestamp: datetime
    last_timestamp: datetime


def _detect_swings(
    candles: tuple[_MarketCandle, ...],
    *,
    timeframe: str,
    swing_definition: Mapping[str, Any],
) -> tuple[_MarketStructureEvent, tuple[_MarketStructureEvent, ...], tuple[_MarketStructureEvent, ...]]:
    left_window = _require_int(swing_definition["left_window"], "left_window")
    right_window = _require_int(swing_definition["right_window"], "right_window")
    tolerance = _require_decimal(swing_definition["equality_tolerance_value"], "equality_tolerance_value")
    tie_break_policy = _require_str(swing_definition["tie_break_policy"], "tie_break_policy")

    events: list[_MarketStructureEvent] = []
    confirmed_highs: list[_MarketStructureEvent] = []
    confirmed_lows: list[_MarketStructureEvent] = []

    for index, candle in enumerate(candles):
        left_slice = candles[max(0, index - left_window) : index]
        right_slice = candles[index + 1 : index + right_window + 1]

        if len(left_slice) < left_window or len(right_slice) < right_window:
            if index >= left_window and not right_slice:
                left_high = max(item.high for item in left_slice) if left_slice else candle.high
                left_low = min(item.low for item in left_slice) if left_slice else candle.low
                if candle.high >= left_high:
                    events.append(
                        _MarketStructureEvent(
                            kind="candidate_swing_high",
                            status="candidate",
                            timestamp=candle.timestamp,
                            candle_index=index,
                            timeframe=timeframe,
                            level=candle.high,
                            details={
                                "window": {"left": left_window, "right": right_window},
                                "reason": "right_window_incomplete",
                            },
                        )
                    )
                if candle.low <= left_low:
                    events.append(
                        _MarketStructureEvent(
                            kind="candidate_swing_low",
                            status="candidate",
                            timestamp=candle.timestamp,
                            candle_index=index,
                            timeframe=timeframe,
                            level=candle.low,
                            details={
                                "window": {"left": left_window, "right": right_window},
                                "reason": "right_window_incomplete",
                            },
                        )
                    )
            continue

        window = left_slice + (candle,) + right_slice
        high_values = [item.high for item in window]
        low_values = [item.low for item in window]
        max_high = max(high_values)
        min_low = min(low_values)

        if candle.high == max_high:
            tied_highs = [i for i, value in enumerate(high_values) if abs(value - max_high) <= tolerance]
            if len(tied_highs) == 1 or tie_break_policy != "reject_tied_extrema":
                swing_high = _MarketStructureEvent(
                    kind="confirmed_swing_high",
                    status="confirmed",
                    timestamp=candle.timestamp,
                    candle_index=index,
                    timeframe=timeframe,
                    level=candle.high,
                    details={"window": {"left": left_window, "right": right_window}},
                )
                events.append(swing_high)
                confirmed_highs.append(swing_high)
            else:
                events.append(
                    _MarketStructureEvent(
                        kind="ambiguous_swing_high",
                        status="ambiguous",
                        timestamp=candle.timestamp,
                        candle_index=index,
                        timeframe=timeframe,
                        level=candle.high,
                        details={"reason": "tied_highs_rejected"},
                    )
                )

        if candle.low == min_low:
            tied_lows = [i for i, value in enumerate(low_values) if abs(value - min_low) <= tolerance]
            if len(tied_lows) == 1 or tie_break_policy != "reject_tied_extrema":
                swing_low = _MarketStructureEvent(
                    kind="confirmed_swing_low",
                    status="confirmed",
                    timestamp=candle.timestamp,
                    candle_index=index,
                    timeframe=timeframe,
                    level=candle.low,
                    details={"window": {"left": left_window, "right": right_window}},
                )
                events.append(swing_low)
                confirmed_lows.append(swing_low)
            else:
                events.append(
                    _MarketStructureEvent(
                        kind="ambiguous_swing_low",
                        status="ambiguous",
                        timestamp=candle.timestamp,
                        candle_index=index,
                        timeframe=timeframe,
                        level=candle.low,
                        details={"reason": "tied_lows_rejected"},
                    )
                )

    return tuple(events), tuple(confirmed_highs), tuple(confirmed_lows)


def _classify_structure(
    confirmed_highs: tuple[_MarketStructureEvent, ...],
    confirmed_lows: tuple[_MarketStructureEvent, ...],
    *,
    minimum_swing_count: int,
    lateral_range_tolerance: int,
) -> str:
    swing_points = sorted((*confirmed_highs, *confirmed_lows), key=lambda event: (event.timestamp, event.candle_index, event.kind))
    if len(swing_points) < minimum_swing_count:
        return "indeterminate"

    highs = [event.level for event in confirmed_highs if event.level is not None]
    lows = [event.level for event in confirmed_lows if event.level is not None]
    if len(highs) < 2 or len(lows) < 2:
        return "indeterminate"

    bullish_highs = all(later > earlier for earlier, later in zip(highs, highs[1:]))
    bullish_lows = all(later > earlier for earlier, later in zip(lows, lows[1:]))
    bearish_highs = all(later < earlier for earlier, later in zip(highs, highs[1:]))
    bearish_lows = all(later < earlier for earlier, later in zip(lows, lows[1:]))

    overall_high = max(highs)
    overall_low = min(lows)
    if overall_high - overall_low <= Decimal(lateral_range_tolerance):
        return "lateral"
    if bullish_highs and bullish_lows:
        return "bullish"
    if bearish_highs and bearish_lows:
        return "bearish"
    if bullish_highs or bullish_lows or bearish_highs or bearish_lows:
        return "ambiguous"
    return "indeterminate"


def _average_range(candles: tuple[_MarketCandle, ...], lookback: int) -> Decimal:
    if lookback <= 0:
        return Decimal("0")
    window = candles[max(0, len(candles) - lookback) :]
    if not window:
        return Decimal("0")
    total = sum((_candle_range(candle) for candle in window), Decimal("0"))
    return total / Decimal(len(window))


def _first_break_candidate(
    candles: tuple[_MarketCandle, ...],
    *,
    timeframe: str,
    state: str,
    confirmed_highs: tuple[_MarketStructureEvent, ...],
    confirmed_lows: tuple[_MarketStructureEvent, ...],
    minimum_break_distance: Decimal,
    minimum_displacement: Decimal,
    atr_multiplier: int,
    range_average_lookback: int,
) -> tuple[_MarketStructureEvent | None, _MarketStructureEvent | None, _MarketStructureEvent | None]:
    if state not in {"bullish", "bearish", "lateral"}:
        return None, None, None

    break_event: _MarketStructureEvent | None = None
    displacement_event: _MarketStructureEvent | None = None
    retest_event: _MarketStructureEvent | None = None

    highest_level = confirmed_highs[-1].level if confirmed_highs else None
    lowest_level = confirmed_lows[-1].level if confirmed_lows else None
    avg_range = _average_range(candles, range_average_lookback)

    for index, candle in enumerate(candles):
        bullish_break = False
        bearish_break = False
        break_level: Decimal | None = None
        break_kind = ""

        if state == "bullish" and highest_level is not None and candle.close > highest_level + minimum_break_distance:
            bullish_break = True
            break_level = highest_level
            break_kind = "valid_bos"
            if _is_bullish_displacement(candle, avg_range, minimum_displacement, atr_multiplier):
                break_kind = "valid_bos"
            else:
                break_kind = "failed_bos"
        elif state == "bearish" and lowest_level is not None and candle.close < lowest_level - minimum_break_distance:
            bearish_break = True
            break_level = lowest_level
            break_kind = "valid_bos"
            if _is_bearish_displacement(candle, avg_range, minimum_displacement, atr_multiplier):
                break_kind = "valid_bos"
            else:
                break_kind = "failed_bos"
        elif state == "bullish" and lowest_level is not None and candle.close < lowest_level - minimum_break_distance:
            bearish_break = True
            break_level = lowest_level
            break_kind = "valid_choch" if _is_bearish_displacement(candle, avg_range, minimum_displacement, atr_multiplier) else "failed_choch"
        elif state == "bearish" and highest_level is not None and candle.close > highest_level + minimum_break_distance:
            bullish_break = True
            break_level = highest_level
            break_kind = "valid_choch" if _is_bullish_displacement(candle, avg_range, minimum_displacement, atr_multiplier) else "failed_choch"
        elif state == "lateral":
            if highest_level is not None and candle.close > highest_level + minimum_break_distance:
                bullish_break = True
                break_level = highest_level
                break_kind = "breakout" if _is_bullish_displacement(candle, avg_range, minimum_displacement, atr_multiplier) else "failed_bos"
            elif lowest_level is not None and candle.close < lowest_level - minimum_break_distance:
                bearish_break = True
                break_level = lowest_level
                break_kind = "breakout" if _is_bearish_displacement(candle, avg_range, minimum_displacement, atr_multiplier) else "failed_bos"

        if break_level is None:
            continue
        if break_kind.startswith("failed_"):
            continue

        break_event = _MarketStructureEvent(
            kind=break_kind,
            status="confirmed" if break_kind in {"valid_bos", "valid_choch", "breakout"} else "failed",
            timestamp=candle.timestamp,
            candle_index=index,
            timeframe=timeframe,
            level=break_level,
            direction="bullish" if bullish_break else "bearish",
            details={
                "state": state,
                "minimum_break_distance": str(minimum_break_distance),
                "minimum_displacement": str(minimum_displacement),
                "atr_multiplier": atr_multiplier,
            },
        )

        window_end = min(len(candles), index + 1 + max(1, int(math.ceil(float(max(Decimal("1"), minimum_break_distance)))) + 2))
        for later_index in range(index + 1, window_end):
            later_candle = candles[later_index]
            if bullish_break and later_candle.low <= break_level <= later_candle.high and later_candle.close >= break_level:
                retest_event = _MarketStructureEvent(
                    kind="valid_retest",
                    status="confirmed",
                    timestamp=later_candle.timestamp,
                    candle_index=later_index,
                    timeframe=timeframe,
                    level=break_level,
                    direction="bullish",
                    details={"break_index": index},
                )
                break
            if bearish_break and later_candle.low <= break_level <= later_candle.high and later_candle.close <= break_level:
                retest_event = _MarketStructureEvent(
                    kind="valid_retest",
                    status="confirmed",
                    timestamp=later_candle.timestamp,
                    candle_index=later_index,
                    timeframe=timeframe,
                    level=break_level,
                    direction="bearish",
                    details={"break_index": index},
                )
                break

        strongest_index = max(range(len(candles)), key=lambda idx: _candle_range(candles[idx]))
        strongest_candle = candles[strongest_index]
        displacement_event = _MarketStructureEvent(
            kind="valid_displacement"
            if (
                _is_bullish_displacement(strongest_candle, avg_range, minimum_displacement, atr_multiplier)
                or _is_bearish_displacement(strongest_candle, avg_range, minimum_displacement, atr_multiplier)
            )
            else "insufficient_displacement",
            status="confirmed"
            if (
                _is_bullish_displacement(strongest_candle, avg_range, minimum_displacement, atr_multiplier)
                or _is_bearish_displacement(strongest_candle, avg_range, minimum_displacement, atr_multiplier)
            )
            else "insufficient",
            timestamp=strongest_candle.timestamp,
            candle_index=strongest_index,
            timeframe=timeframe,
            level=strongest_candle.close,
            details={
                "range": str(_candle_range(strongest_candle)),
                "average_range": str(avg_range),
                "minimum_displacement": str(minimum_displacement),
            },
        )

        break

    return break_event, displacement_event, retest_event


def _sweep_events(
    candles: tuple[_MarketCandle, ...],
    *,
    timeframe: str,
    confirmed_highs: tuple[_MarketStructureEvent, ...],
    confirmed_lows: tuple[_MarketStructureEvent, ...],
    tolerance: Decimal,
    sweep_definition: Mapping[str, Any],
    liquidity_definition: Mapping[str, Any],
) -> list[_MarketStructureEvent]:
    events: list[_MarketStructureEvent] = []
    minimum_test_count = _require_int(liquidity_definition["minimum_test_count"], "minimum_test_count")
    return_window = _require_int(sweep_definition["return_window"], "return_window")
    minimum_penetration = _require_decimal(sweep_definition["minimum_penetration"], "minimum_penetration")
    breakout_threshold = _require_decimal(
        sweep_definition["breakout_confirmation_threshold"], "breakout_confirmation_threshold"
    )
    close_back_inside_required = _require_bool(
        sweep_definition["close_back_inside_required"], "close_back_inside_required"
    )

    def _scan_groups(
        groups: list[tuple[Decimal, list[_MarketStructureEvent]]],
        *,
        direction: str,
    ) -> None:
        for level, items in groups:
            if len(items) < minimum_test_count:
                continue
            breach_index: int | None = None
            breach_candle: _MarketCandle | None = None
            for index, candle in enumerate(candles):
                if direction == "up" and candle.high > level + minimum_penetration:
                    breach_index = index
                    breach_candle = candle
                    break
                if direction == "down" and candle.low < level - minimum_penetration:
                    breach_index = index
                    breach_candle = candle
                    break
            if breach_index is None or breach_candle is None:
                continue

            if direction == "up" and breach_candle.close <= level and (not close_back_inside_required or breach_candle.close <= level):
                events.append(
                    _MarketStructureEvent(
                        kind="liquidity_sweep",
                        status="confirmed",
                        timestamp=breach_candle.timestamp,
                        candle_index=breach_index,
                        timeframe=timeframe,
                        level=level,
                        direction="bullish",
                        details={"count": len(items), "direction": "up"},
                    )
                )
                if breach_index + return_window < len(candles):
                    later_window = candles[breach_index + 1 : breach_index + return_window + 1]
                    if any(candle.close <= level for candle in later_window):
                        events.append(
                            _MarketStructureEvent(
                                kind="false_break",
                                status="confirmed",
                                timestamp=later_window[-1].timestamp,
                                candle_index=breach_index + len(later_window),
                                timeframe=timeframe,
                                level=level,
                                direction="bullish",
                                details={"reason": "reclaimed_after_liquidity_breach"},
                            )
                        )
                continue
            if direction == "down" and breach_candle.close >= level and (not close_back_inside_required or breach_candle.close >= level):
                events.append(
                    _MarketStructureEvent(
                        kind="liquidity_sweep",
                        status="confirmed",
                        timestamp=breach_candle.timestamp,
                        candle_index=breach_index,
                        timeframe=timeframe,
                        level=level,
                        direction="bearish",
                        details={"count": len(items), "direction": "down"},
                    )
                )
                if breach_index + return_window < len(candles):
                    later_window = candles[breach_index + 1 : breach_index + return_window + 1]
                    if any(candle.close >= level for candle in later_window):
                        events.append(
                            _MarketStructureEvent(
                                kind="false_break",
                                status="confirmed",
                                timestamp=later_window[-1].timestamp,
                                candle_index=breach_index + len(later_window),
                                timeframe=timeframe,
                                level=level,
                                direction="bearish",
                                details={"reason": "reclaimed_after_liquidity_breach"},
                            )
                        )
                continue

            if direction == "up" and breach_candle.close > level + breakout_threshold:
                events.append(
                    _MarketStructureEvent(
                        kind="breakout",
                        status="confirmed",
                        timestamp=breach_candle.timestamp,
                        candle_index=breach_index,
                        timeframe=timeframe,
                        level=level,
                        direction="bullish",
                        details={"count": len(items), "direction": "up"},
                    )
                )
            elif direction == "down" and breach_candle.close < level - breakout_threshold:
                events.append(
                    _MarketStructureEvent(
                        kind="breakout",
                        status="confirmed",
                        timestamp=breach_candle.timestamp,
                        candle_index=breach_index,
                        timeframe=timeframe,
                        level=level,
                        direction="bearish",
                        details={"count": len(items), "direction": "down"},
                    )
                )
            else:
                events.append(
                    _MarketStructureEvent(
                        kind="failed_sweep",
                        status="failed",
                        timestamp=breach_candle.timestamp,
                        candle_index=breach_index,
                        timeframe=timeframe,
                        level=level,
                        direction="bullish" if direction == "up" else "bearish",
                        details={"count": len(items), "direction": direction},
                    )
                )
            if breach_index + return_window < len(candles):
                later_window = candles[breach_index + 1 : breach_index + return_window + 1]
                if direction == "up" and any(candle.close <= level for candle in later_window):
                    events.append(
                        _MarketStructureEvent(
                            kind="false_break",
                            status="confirmed",
                            timestamp=later_window[-1].timestamp,
                            candle_index=breach_index + len(later_window),
                            timeframe=timeframe,
                            level=level,
                            direction="bullish",
                            details={"reason": "reclaimed_after_liquidity_breach"},
                        )
                    )
                if direction == "down" and any(candle.close >= level for candle in later_window):
                    events.append(
                        _MarketStructureEvent(
                            kind="false_break",
                            status="confirmed",
                            timestamp=later_window[-1].timestamp,
                            candle_index=breach_index + len(later_window),
                            timeframe=timeframe,
                            level=level,
                            direction="bearish",
                            details={"reason": "reclaimed_after_liquidity_breach"},
                        )
                    )

    high_groups = _group_equal_levels(confirmed_highs, tolerance)
    low_groups = _group_equal_levels(confirmed_lows, tolerance)
    _scan_groups(high_groups, direction="up")
    _scan_groups(low_groups, direction="down")
    return events


def _group_equal_levels(values: tuple[_MarketStructureEvent, ...], tolerance: Decimal) -> list[tuple[Decimal, list[_MarketStructureEvent]]]:
    groups: list[tuple[Decimal, list[_MarketStructureEvent]]] = []
    for event in values:
        if event.level is None:
            continue
        placed = False
        for level, items in groups:
            if abs(level - event.level) <= tolerance:
                items.append(event)
                placed = True
                break
        if not placed:
            groups.append((event.level, [event]))
    return groups


def _liquidity_events(
    confirmed_highs: tuple[_MarketStructureEvent, ...],
    confirmed_lows: tuple[_MarketStructureEvent, ...],
    *,
    timeframe: str,
    minimum_test_count: int,
    tolerance: Decimal,
) -> list[_MarketStructureEvent]:
    events: list[_MarketStructureEvent] = []
    high_groups = _group_equal_levels(confirmed_highs, tolerance)
    low_groups = _group_equal_levels(confirmed_lows, tolerance)

    for level, items in high_groups:
        if len(items) >= minimum_test_count:
            events.append(
                _MarketStructureEvent(
                    kind="equal_highs",
                    status="confirmed",
                    timestamp=items[-1].timestamp,
                    candle_index=items[-1].candle_index,
                    timeframe=timeframe,
                    level=level,
                    details={"count": len(items)},
                )
            )
            events.append(
                _MarketStructureEvent(
                    kind="external_liquidity" if level == max(item.level for item in confirmed_highs if item.level is not None) else "internal_liquidity",
                    status="confirmed",
                    timestamp=items[-1].timestamp,
                    candle_index=items[-1].candle_index,
                    timeframe=timeframe,
                    level=level,
                    details={"kind": "high"},
                )
            )
            events.append(
                _MarketStructureEvent(
                    kind="protected_high",
                    status="confirmed",
                    timestamp=items[-1].timestamp,
                    candle_index=items[-1].candle_index,
                    timeframe=timeframe,
                    level=level,
                    details={"count": len(items)},
                )
            )

    for level, items in low_groups:
        if len(items) >= minimum_test_count:
            events.append(
                _MarketStructureEvent(
                    kind="equal_lows",
                    status="confirmed",
                    timestamp=items[-1].timestamp,
                    candle_index=items[-1].candle_index,
                    timeframe=timeframe,
                    level=level,
                    details={"count": len(items)},
                )
            )
            events.append(
                _MarketStructureEvent(
                    kind="external_liquidity" if level == min(item.level for item in confirmed_lows if item.level is not None) else "internal_liquidity",
                    status="confirmed",
                    timestamp=items[-1].timestamp,
                    candle_index=items[-1].candle_index,
                    timeframe=timeframe,
                    level=level,
                    details={"kind": "low"},
                )
            )
            events.append(
                _MarketStructureEvent(
                    kind="protected_low",
                    status="confirmed",
                    timestamp=items[-1].timestamp,
                    candle_index=items[-1].candle_index,
                    timeframe=timeframe,
                    level=level,
                    details={"count": len(items)},
                )
            )
    return events


def _range_events(
    candles: tuple[_MarketCandle, ...],
    *,
    timeframe: str,
    state: str,
    minimum_duration: int,
    minimum_width: Decimal,
    maximum_width: Decimal,
    minimum_support_tests: int,
    minimum_resistance_tests: int,
) -> list[_MarketStructureEvent]:
    events: list[_MarketStructureEvent] = []
    if len(candles) < minimum_duration:
        return [
            _MarketStructureEvent(
                kind="unclassified_range",
                status="indeterminate",
                timestamp=candles[-1].timestamp,
                candle_index=len(candles) - 1,
                timeframe=timeframe,
                details={"reason": "insufficient_duration"},
            )
        ]

    window = candles[-minimum_duration:]
    high = max(candle.high for candle in window)
    low = min(candle.low for candle in window)
    width = high - low
    support_tests = sum(1 for candle in window if abs(candle.low - low) <= minimum_width)
    resistance_tests = sum(1 for candle in window if abs(candle.high - high) <= minimum_width)

    if width <= maximum_width and support_tests >= minimum_support_tests and resistance_tests >= minimum_resistance_tests:
        events.append(
            _MarketStructureEvent(
                kind="valid_trading_range",
                status="confirmed",
                timestamp=window[-1].timestamp,
                candle_index=len(candles) - 1,
                timeframe=timeframe,
                level=high,
                details={
                    "low": str(low),
                    "width": str(width),
                    "support_tests": support_tests,
                    "resistance_tests": resistance_tests,
                },
            )
        )
        if state == "bullish":
            events.append(
                _MarketStructureEvent(
                    kind="candidate_distribution",
                    status="candidate",
                    timestamp=window[-1].timestamp,
                    candle_index=len(candles) - 1,
                    timeframe=timeframe,
                    level=high,
                    details={"reason": "bullish_into_range"},
                )
            )
        elif state == "bearish":
            events.append(
                _MarketStructureEvent(
                    kind="candidate_accumulation",
                    status="candidate",
                    timestamp=window[-1].timestamp,
                    candle_index=len(candles) - 1,
                    timeframe=timeframe,
                    level=low,
                    details={"reason": "bearish_into_range"},
                )
            )
        else:
            events.append(
                _MarketStructureEvent(
                    kind="candidate_reaccumulation",
                    status="candidate",
                    timestamp=window[-1].timestamp,
                    candle_index=len(candles) - 1,
                    timeframe=timeframe,
                    level=low,
                    details={"reason": "lateral_range"},
                )
            )
    else:
        events.append(
            _MarketStructureEvent(
                kind="unclassified_range",
                status="indeterminate",
                timestamp=window[-1].timestamp,
                candle_index=len(candles) - 1,
                timeframe=timeframe,
                details={
                    "width": str(width),
                    "support_tests": support_tests,
                    "resistance_tests": resistance_tests,
                },
            )
        )
    return events


def _analyze_timeframe(
    candles: tuple[_MarketCandle, ...],
    *,
    timeframe: str,
    contract: MarketStructureResearchContract,
) -> _SeriesSummary:
    swing_definition = contract.swing_definition.parameters
    trend_definition = contract.trend_structure_definition.parameters
    displacement_definition = contract.displacement_definition.parameters
    liquidity_definition = contract.liquidity_definition.parameters

    swing_events, confirmed_highs, confirmed_lows = _detect_swings(
        candles,
        timeframe=timeframe,
        swing_definition=swing_definition,
    )
    minimum_swing_count = _require_int(trend_definition["minimum_swing_count"], "minimum_swing_count")
    lateral_range_tolerance = _require_int(trend_definition["lateral_range_tolerance"], "lateral_range_tolerance", allow_zero=True)
    state = _classify_structure(
        confirmed_highs,
        confirmed_lows,
        minimum_swing_count=minimum_swing_count,
        lateral_range_tolerance=lateral_range_tolerance,
    )
    highest_level = max((event.level for event in confirmed_highs if event.level is not None), default=None)
    lowest_level = min((event.level for event in confirmed_lows if event.level is not None), default=None)
    average_range = _average_range(
        candles,
        _require_int(displacement_definition["range_average_lookback"], "range_average_lookback"),
    )
    return _SeriesSummary(
        timeframe=timeframe,
        state=state,
        confirmed_swings=swing_events,
        confirmed_highs=confirmed_highs,
        confirmed_lows=confirmed_lows,
        highest_level=highest_level,
        lowest_level=lowest_level,
        average_range=average_range,
        first_timestamp=candles[0].timestamp,
        last_timestamp=candles[-1].timestamp,
    )


def _analysis_contexts(
    candles_by_timeframe: Mapping[str, tuple[_MarketCandle, ...]],
    *,
    contract: MarketStructureResearchContract,
) -> tuple[str, str, str]:
    ordered = sorted(candles_by_timeframe.items(), key=lambda item: (_timeframe_rank(item[0]), item[0]))
    analyses = [
        _analyze_timeframe(candles, timeframe=timeframe, contract=contract)
        for timeframe, candles in ordered
    ]
    states = [analysis.state for analysis in analyses]
    if len(states) == 1:
        return states[0], states[0], states[0]
    macro = states[-1]
    micro = states[0]
    intermediate = states[len(states) // 2]
    return macro, intermediate, micro


@dataclass(frozen=True, slots=True)
class MarketStructureDetectionInput:
    schema_version: int
    contract: MarketStructureResearchContract = field(repr=False)
    dataset_hash: str = ""
    symbol: str = ""
    market: str = ""
    timeframe: str = ""
    provider_name: str = ""
    candles: tuple[_MarketCandle, ...] = field(default_factory=tuple, repr=False)
    candles_by_timeframe: Mapping[str, tuple[_MarketCandle, ...]] = field(default_factory=dict, repr=False)
    ordering_policy: str = "strict_ascending_timestamp"
    duplicate_timestamp_policy: str = "reject"
    missing_candle_policy: str = "reject"
    incomplete_candle_policy: str = "reject"
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        if not isinstance(self.contract, MarketStructureResearchContract):
            raise OfflineMarketStructureDetectorValidationError("contract must be a verified market structure research contract.")
        verify_market_structure_research_contract(self.contract)
        object.__setattr__(self, "dataset_hash", _require_str(self.dataset_hash, "dataset_hash").lower())
        if len(self.dataset_hash) != 64 or any(ch not in "0123456789abcdef" for ch in self.dataset_hash):
            raise OfflineMarketStructureDetectorValidationError("dataset_hash must be a 64-character hex digest.")
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "market", _require_str(self.market, "market").lower())
        object.__setattr__(self, "timeframe", _require_str(self.timeframe, "timeframe").upper())
        object.__setattr__(self, "provider_name", _require_str(self.provider_name, "provider_name"))
        object.__setattr__(self, "ordering_policy", _require_str(self.ordering_policy, "ordering_policy"))
        object.__setattr__(self, "duplicate_timestamp_policy", _require_str(self.duplicate_timestamp_policy, "duplicate_timestamp_policy"))
        object.__setattr__(self, "missing_candle_policy", _require_str(self.missing_candle_policy, "missing_candle_policy"))
        object.__setattr__(self, "incomplete_candle_policy", _require_str(self.incomplete_candle_policy, "incomplete_candle_policy"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        if not isinstance(self.metadata, Mapping):
            raise OfflineMarketStructureDetectorValidationError("metadata must be a mapping.")

        normalized_candles = self.candles
        if not normalized_candles or not isinstance(normalized_candles, tuple) or not isinstance(normalized_candles[0], _MarketCandle):
            normalized_candles = _normalize_candle_series(
                self.candles,
                field_name="candles",
                timeframe=self.timeframe,
                duplicate_timestamp_policy=self.duplicate_timestamp_policy,
                missing_candle_policy=self.missing_candle_policy,
                incomplete_candle_policy=self.incomplete_candle_policy,
            )
        object.__setattr__(self, "candles", normalized_candles)

        normalized_by_timeframe = self.candles_by_timeframe
        if not isinstance(normalized_by_timeframe, Mapping) or not normalized_by_timeframe:
            normalized_by_timeframe = _normalize_candles_by_timeframe(
                None,
                primary_timeframe=self.timeframe,
                primary_candles=normalized_candles,
                duplicate_timestamp_policy=self.duplicate_timestamp_policy,
                missing_candle_policy=self.missing_candle_policy,
                incomplete_candle_policy=self.incomplete_candle_policy,
            )
        else:
            needs_normalization = True
            first_value = next(iter(normalized_by_timeframe.values()))
            if isinstance(first_value, tuple) and first_value and isinstance(first_value[0], _MarketCandle):
                needs_normalization = False
            if needs_normalization:
                normalized_by_timeframe = _normalize_candles_by_timeframe(
                    normalized_by_timeframe,
                    primary_timeframe=self.timeframe,
                    primary_candles=normalized_candles,
                    duplicate_timestamp_policy=self.duplicate_timestamp_policy,
                    missing_candle_policy=self.missing_candle_policy,
                    incomplete_candle_policy=self.incomplete_candle_policy,
                )
            elif self.timeframe not in normalized_by_timeframe:
                normalized_by_timeframe = _freeze_read_only_value(
                    {**dict(normalized_by_timeframe), self.timeframe: normalized_candles}
                )
            else:
                if normalized_by_timeframe[self.timeframe] != normalized_candles:
                    raise OfflineMarketStructureDetectorValidationError(
                        "primary candles must match the primary timeframe series."
                    )
        object.__setattr__(self, "candles_by_timeframe", normalized_by_timeframe)
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))
        if self.ordering_policy != "strict_ascending_timestamp":
            raise OfflineMarketStructureDetectorValidationError("ordering_policy must remain strict_ascending_timestamp.")
        if self.duplicate_timestamp_policy != "reject":
            raise OfflineMarketStructureDetectorValidationError("duplicate_timestamp_policy must remain reject.")
        if self.missing_candle_policy != "reject":
            raise OfflineMarketStructureDetectorValidationError("missing_candle_policy must remain reject.")
        if self.incomplete_candle_policy != "reject":
            raise OfflineMarketStructureDetectorValidationError("incomplete_candle_policy must remain reject.")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_id": self.contract.contract_id,
            "contract_hash": self.contract.contract_hash,
            "dataset_hash": self.dataset_hash,
            "symbol": self.symbol,
            "market": self.market,
            "timeframe": self.timeframe,
            "provider_name": self.provider_name,
            "candles": [candle.canonical_payload() for candle in self.candles],
            "candles_by_timeframe": {
                key: [candle.canonical_payload() for candle in value]
                for key, value in self.candles_by_timeframe.items()
            },
            "ordering_policy": self.ordering_policy,
            "duplicate_timestamp_policy": self.duplicate_timestamp_policy,
            "missing_candle_policy": self.missing_candle_policy,
            "incomplete_candle_policy": self.incomplete_candle_policy,
            "created_at_utc": _utc_iso(self.created_at_utc),
            "metadata": _thaw_read_only_value(self.metadata),
        }

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class MarketStructureDetectionResult:
    schema_version: int
    detection_result_id: str = ""
    detection_result_hash: str = ""
    contract_id: str = ""
    contract_hash: str = ""
    dataset_hash: str = ""
    symbol: str = ""
    market: str = ""
    timeframe: str = ""
    first_timestamp: datetime | str = field(default_factory=lambda: datetime.now(timezone.utc))
    last_timestamp: datetime | str = field(default_factory=lambda: datetime.now(timezone.utc))
    candle_count: int = 0
    events: tuple[_MarketStructureEvent, ...] = field(default_factory=tuple, repr=False)
    final_structure_state: str = "indeterminate"
    macro_context: str = "indeterminate"
    intermediate_context: str = "indeterminate"
    micro_context: str = "indeterminate"
    ambiguity_state: str = "indeterminate"
    invalidation_state: str = "indeterminate"
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "detection_result_id", _require_str(self.detection_result_id, "detection_result_id") if self.detection_result_id else "")
        object.__setattr__(self, "detection_result_hash", _require_str(self.detection_result_hash, "detection_result_hash") if self.detection_result_hash else "")
        object.__setattr__(self, "contract_id", _require_hex_digest(self.contract_id, "contract_id"))
        object.__setattr__(self, "contract_hash", _require_hex_digest(self.contract_hash, "contract_hash"))
        object.__setattr__(self, "dataset_hash", _require_hex_digest(self.dataset_hash, "dataset_hash"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "market", _require_str(self.market, "market").lower())
        object.__setattr__(self, "timeframe", _require_str(self.timeframe, "timeframe").upper())
        object.__setattr__(self, "first_timestamp", _require_utc_datetime(self.first_timestamp, "first_timestamp"))
        object.__setattr__(self, "last_timestamp", _require_utc_datetime(self.last_timestamp, "last_timestamp"))
        object.__setattr__(self, "candle_count", _require_int(self.candle_count, "candle_count", allow_zero=True))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        if not isinstance(self.metadata, Mapping):
            raise OfflineMarketStructureDetectorValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))

        normalized_events: list[_MarketStructureEvent] = []
        for event in self.events:
            if isinstance(event, _MarketStructureEvent):
                normalized_events.append(event)
            elif isinstance(event, Mapping):
                normalized_events.append(_MarketStructureEvent.from_dict(event))
            else:
                raise OfflineMarketStructureDetectorValidationError("events must contain event mappings.")
        object.__setattr__(self, "events", tuple(sorted(normalized_events, key=_event_sort_key)))

        if self.final_structure_state not in OFFLINE_MARKET_STRUCTURE_DETECTOR_ALLOWED_STRUCTURE_STATES:
            raise OfflineMarketStructureDetectorValidationError("final_structure_state is invalid.")
        if self.macro_context not in OFFLINE_MARKET_STRUCTURE_DETECTOR_ALLOWED_STRUCTURE_STATES:
            raise OfflineMarketStructureDetectorValidationError("macro_context is invalid.")
        if self.intermediate_context not in OFFLINE_MARKET_STRUCTURE_DETECTOR_ALLOWED_STRUCTURE_STATES:
            raise OfflineMarketStructureDetectorValidationError("intermediate_context is invalid.")
        if self.micro_context not in OFFLINE_MARKET_STRUCTURE_DETECTOR_ALLOWED_STRUCTURE_STATES:
            raise OfflineMarketStructureDetectorValidationError("micro_context is invalid.")
        if self.ambiguity_state not in {"none", "ambiguous", "indeterminate"}:
            raise OfflineMarketStructureDetectorValidationError("ambiguity_state is invalid.")
        if self.invalidation_state not in {"none", "invalidated", "indeterminate"}:
            raise OfflineMarketStructureDetectorValidationError("invalidation_state is invalid.")

        expected_id = _hash_payload(self._detection_result_id_payload())
        if self.detection_result_id:
            if self.detection_result_id != expected_id:
                raise OfflineMarketStructureDetectorIntegrityError("detection_result_id mismatch.")
        else:
            object.__setattr__(self, "detection_result_id", expected_id)

        expected_hash = _hash_payload(self._detection_result_hash_payload())
        if self.detection_result_hash:
            if self.detection_result_hash != expected_hash:
                raise OfflineMarketStructureDetectorIntegrityError("detection_result_hash mismatch.")
        else:
            object.__setattr__(self, "detection_result_hash", expected_hash)

    def _detection_result_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_id": self.contract_id,
            "contract_hash": self.contract_hash,
            "dataset_hash": self.dataset_hash,
            "symbol": self.symbol,
            "market": self.market,
            "timeframe": self.timeframe,
            "first_timestamp": _utc_iso(self.first_timestamp),
            "last_timestamp": _utc_iso(self.last_timestamp),
            "candle_count": self.candle_count,
            "events": [event.canonical_payload() for event in self.events],
            "final_structure_state": self.final_structure_state,
            "macro_context": self.macro_context,
            "intermediate_context": self.intermediate_context,
            "micro_context": self.micro_context,
            "ambiguity_state": self.ambiguity_state,
            "invalidation_state": self.invalidation_state,
            "metadata": _thaw_read_only_value(self.metadata),
        }

    def _detection_result_hash_payload(self) -> dict[str, Any]:
        payload = self._detection_result_id_payload()
        payload["detection_result_id"] = self.detection_result_id
        return payload

    def canonical_payload(
        self,
        *,
        include_detection_result_id: bool = True,
        include_detection_result_hash: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "contract_id": self.contract_id,
            "contract_hash": self.contract_hash,
            "dataset_hash": self.dataset_hash,
            "symbol": self.symbol,
            "market": self.market,
            "timeframe": self.timeframe,
            "first_timestamp": _utc_iso(self.first_timestamp),
            "last_timestamp": _utc_iso(self.last_timestamp),
            "candle_count": self.candle_count,
            "events": [event.canonical_payload() for event in self.events],
            "final_structure_state": self.final_structure_state,
            "macro_context": self.macro_context,
            "intermediate_context": self.intermediate_context,
            "micro_context": self.micro_context,
            "ambiguity_state": self.ambiguity_state,
            "invalidation_state": self.invalidation_state,
            "created_at_utc": _utc_iso(self.created_at_utc),
            "metadata": _thaw_read_only_value(self.metadata),
        }
        if include_detection_result_id:
            payload["detection_result_id"] = self.detection_result_id
        if include_detection_result_hash:
            payload["detection_result_hash"] = self.detection_result_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_detection_result_id=True, include_detection_result_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureDetectionResult":
        if not isinstance(data, Mapping):
            raise OfflineMarketStructureDetectorValidationError("market structure detection result must be a mapping.")
        try:
            return cls(
                schema_version=data["schema_version"],
                detection_result_id=data.get("detection_result_id", ""),
                detection_result_hash=data.get("detection_result_hash", ""),
                contract_id=data["contract_id"],
                contract_hash=data["contract_hash"],
                dataset_hash=data["dataset_hash"],
                symbol=data["symbol"],
                market=data["market"],
                timeframe=data["timeframe"],
                first_timestamp=data["first_timestamp"],
                last_timestamp=data["last_timestamp"],
                candle_count=data["candle_count"],
                events=data["events"],
                final_structure_state=data["final_structure_state"],
                macro_context=data["macro_context"],
                intermediate_context=data["intermediate_context"],
                micro_context=data["micro_context"],
                ambiguity_state=data["ambiguity_state"],
                invalidation_state=data["invalidation_state"],
                created_at_utc=data["created_at_utc"],
                metadata=data.get("metadata", {}),
            )
        except KeyError as exc:
            raise OfflineMarketStructureDetectorValidationError(
                "market structure detection result is incomplete."
            ) from exc


def _event_sort_key(event: _MarketStructureEvent) -> tuple[int, str, int, str]:
    return (
        _event_priority(event.kind),
        _utc_iso(event.timestamp),
        event.candle_index,
        event.kind,
    )


def build_market_structure_detection_input(
    *,
    contract: MarketStructureResearchContract,
    candles: Sequence[Mapping[str, Any]] | Any,
    dataset_hash: str,
    symbol: str,
    market: str,
    timeframe: str,
    provider_name: str,
    candles_by_timeframe: Mapping[str, Any] | None = None,
    ordering_policy: str = "strict_ascending_timestamp",
    duplicate_timestamp_policy: str = "reject",
    missing_candle_policy: str = "reject",
    incomplete_candle_policy: str = "reject",
    created_at_utc: datetime | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> MarketStructureDetectionInput:
    detection_input = MarketStructureDetectionInput(
        schema_version=OFFLINE_MARKET_STRUCTURE_DETECTOR_SCHEMA_VERSION,
        contract=contract,
        dataset_hash=dataset_hash,
        symbol=symbol,
        market=market,
        timeframe=timeframe,
        provider_name=provider_name,
        candles=candles,
        candles_by_timeframe=candles_by_timeframe or {},
        ordering_policy=ordering_policy,
        duplicate_timestamp_policy=duplicate_timestamp_policy,
        missing_candle_policy=missing_candle_policy,
        incomplete_candle_policy=incomplete_candle_policy,
        created_at_utc=created_at_utc or datetime.now(timezone.utc),
        metadata=metadata or {},
    )
    return verify_market_structure_detection_input(detection_input)


def verify_market_structure_detection_input(
    detection_input: MarketStructureDetectionInput,
) -> MarketStructureDetectionInput:
    if not isinstance(detection_input, MarketStructureDetectionInput):
        raise OfflineMarketStructureDetectorValidationError("market structure detection input is required.")
    verify_market_structure_research_contract(detection_input.contract)
    if detection_input.timeframe not in detection_input.candles_by_timeframe:
        raise OfflineMarketStructureDetectorValidationError("primary timeframe candles are required.")
    if detection_input.candles_by_timeframe[detection_input.timeframe] != detection_input.candles:
        raise OfflineMarketStructureDetectorValidationError("primary candles must match the primary timeframe series.")
    return detection_input


def _primary_timeframe_analysis(
    detection_input: MarketStructureDetectionInput,
) -> tuple[_SeriesSummary, list[_MarketStructureEvent]]:
    primary_summary = _analyze_timeframe(
        detection_input.candles,
        timeframe=detection_input.timeframe,
        contract=detection_input.contract,
    )
    primary_events = list(primary_summary.confirmed_swings)
    primary_events.append(
        _MarketStructureEvent(
            kind=_structure_state_event_kind(primary_summary.state),
            status="final",
            timestamp=primary_summary.last_timestamp,
            candle_index=len(detection_input.candles) - 1,
            timeframe=detection_input.timeframe,
            details={
                "swings": len(primary_summary.confirmed_swings),
                "highest_level": _format_decimal(primary_summary.highest_level),
                "lowest_level": _format_decimal(primary_summary.lowest_level),
            },
        )
    )

    liquidity_definition = detection_input.contract.liquidity_definition.parameters
    displacement_definition = detection_input.contract.displacement_definition.parameters
    trading_range_definition = detection_input.contract.trading_range_definition.parameters
    choch_definition = detection_input.contract.choch_definition.parameters
    bos_definition = detection_input.contract.bos_definition.parameters
    sweep_definition = detection_input.contract.liquidity_sweep_definition.parameters
    retest_definition = detection_input.contract.retest_definition.parameters

    primary_events.extend(
        _liquidity_events(
            primary_summary.confirmed_highs,
            primary_summary.confirmed_lows,
            timeframe=detection_input.timeframe,
            minimum_test_count=_require_int(liquidity_definition["minimum_test_count"], "minimum_test_count"),
            tolerance=_require_decimal(liquidity_definition["level_tolerance_value"], "level_tolerance_value"),
        )
    )
    primary_events.extend(
        _sweep_events(
            detection_input.candles,
            timeframe=detection_input.timeframe,
            confirmed_highs=primary_summary.confirmed_highs,
            confirmed_lows=primary_summary.confirmed_lows,
            tolerance=_require_decimal(liquidity_definition["level_tolerance_value"], "level_tolerance_value"),
            sweep_definition=sweep_definition,
            liquidity_definition=liquidity_definition,
        )
    )

    if primary_summary.state == "bullish" and primary_summary.confirmed_highs:
        primary_events.append(
            _MarketStructureEvent(
                kind="protected_high",
                status="confirmed",
                timestamp=primary_summary.confirmed_highs[-1].timestamp,
                candle_index=primary_summary.confirmed_highs[-1].candle_index,
                timeframe=detection_input.timeframe,
                level=primary_summary.confirmed_highs[-1].level,
                details={"reason": "bullish_structure"},
            )
        )
    elif primary_summary.state == "bearish" and primary_summary.confirmed_lows:
        primary_events.append(
            _MarketStructureEvent(
                kind="protected_low",
                status="confirmed",
                timestamp=primary_summary.confirmed_lows[-1].timestamp,
                candle_index=primary_summary.confirmed_lows[-1].candle_index,
                timeframe=detection_input.timeframe,
                level=primary_summary.confirmed_lows[-1].level,
                details={"reason": "bearish_structure"},
            )
        )

    minimum_displacement = _require_decimal(displacement_definition["minimum_amplitude"], "minimum_amplitude")
    break_event, displacement_event, retest_event = _first_break_candidate(
        detection_input.candles,
        timeframe=detection_input.timeframe,
        state=primary_summary.state,
        confirmed_highs=primary_summary.confirmed_highs,
        confirmed_lows=primary_summary.confirmed_lows,
        minimum_break_distance=_require_decimal(bos_definition["minimum_break_distance"], "minimum_break_distance"),
        minimum_displacement=minimum_displacement,
        atr_multiplier=_require_int(displacement_definition["atr_multiplier"], "atr_multiplier"),
        range_average_lookback=_require_int(displacement_definition["range_average_lookback"], "range_average_lookback"),
    )
    if break_event is not None:
        break_event = _MarketStructureEvent(
            kind=break_event.kind,
            status=break_event.status,
            timestamp=break_event.timestamp,
            candle_index=break_event.candle_index,
            timeframe=detection_input.timeframe,
            level=break_event.level,
            direction=break_event.direction,
            details=break_event.details,
        )
        primary_events.append(break_event)
    if displacement_event is not None:
        displacement_event = _MarketStructureEvent(
            kind=displacement_event.kind,
            status=displacement_event.status,
            timestamp=displacement_event.timestamp,
            candle_index=displacement_event.candle_index,
            timeframe=detection_input.timeframe,
            level=displacement_event.level,
            direction=displacement_event.direction,
            details=displacement_event.details,
        )
        primary_events.append(displacement_event)
    if retest_event is not None:
        retest_event = _MarketStructureEvent(
            kind=retest_event.kind,
            status=retest_event.status,
            timestamp=retest_event.timestamp,
            candle_index=retest_event.candle_index,
            timeframe=detection_input.timeframe,
            level=retest_event.level,
            direction=retest_event.direction,
            details=retest_event.details,
        )
        primary_events.append(retest_event)

    primary_events.extend(
        _range_events(
            detection_input.candles,
            timeframe=detection_input.timeframe,
            state=primary_summary.state,
            minimum_duration=_require_int(trading_range_definition["minimum_duration"], "minimum_duration"),
            minimum_width=_require_decimal(trading_range_definition["minimum_width"], "minimum_width"),
            maximum_width=_require_decimal(trading_range_definition["maximum_width"], "maximum_width"),
            minimum_support_tests=_require_int(trading_range_definition["minimum_support_tests"], "minimum_support_tests"),
            minimum_resistance_tests=_require_int(trading_range_definition["minimum_resistance_tests"], "minimum_resistance_tests"),
        )
    )

    if primary_summary.state == "bullish" and break_event and break_event.kind == "valid_choch":
        primary_events.append(
            _MarketStructureEvent(
                kind="false_break",
                status="confirmed",
                timestamp=break_event.timestamp,
                candle_index=break_event.candle_index,
                timeframe=detection_input.timeframe,
                level=break_event.level,
                direction=break_event.direction,
                details={"reason": "bullish_to_bearish_reversal"},
            )
        )
    elif primary_summary.state == "bearish" and break_event and break_event.kind == "valid_choch":
        primary_events.append(
            _MarketStructureEvent(
                kind="false_break",
                status="confirmed",
                timestamp=break_event.timestamp,
                candle_index=break_event.candle_index,
                timeframe=detection_input.timeframe,
                level=break_event.level,
                direction=break_event.direction,
                details={"reason": "bearish_to_bullish_reversal"},
            )
        )

    primary_events = sorted(primary_events, key=_event_sort_key)
    return primary_summary, primary_events


def detect_market_structure(
    detection_input: MarketStructureDetectionInput,
) -> MarketStructureDetectionResult:
    verified_input = verify_market_structure_detection_input(detection_input)
    macro_context, intermediate_context, micro_context = _analysis_contexts(
        verified_input.candles_by_timeframe,
        contract=verified_input.contract,
    )
    primary_summary, events = _primary_timeframe_analysis(verified_input)

    if primary_summary.state in {"ambiguous", "indeterminate"}:
        ambiguity_state = primary_summary.state
    elif len({macro_context, intermediate_context, micro_context}) > 1:
        ambiguity_state = "ambiguous"
    else:
        ambiguity_state = "none"

    invalidation_state = "none"
    if any(event.kind in {"failed_bos", "failed_choch", "failed_sweep", "failed_retest"} for event in events):
        invalidation_state = "invalidated"
    elif primary_summary.state == "indeterminate":
        invalidation_state = "indeterminate"

    result = MarketStructureDetectionResult(
        schema_version=OFFLINE_MARKET_STRUCTURE_DETECTOR_SCHEMA_VERSION,
        contract_id=verified_input.contract.contract_id,
        contract_hash=verified_input.contract.contract_hash,
        dataset_hash=verified_input.dataset_hash,
        symbol=verified_input.symbol,
        market=verified_input.market,
        timeframe=verified_input.timeframe,
        first_timestamp=primary_summary.first_timestamp,
        last_timestamp=primary_summary.last_timestamp,
        candle_count=len(verified_input.candles),
        events=tuple(events),
        final_structure_state=primary_summary.state,
        macro_context=macro_context,
        intermediate_context=intermediate_context,
        micro_context=micro_context,
        ambiguity_state=ambiguity_state,
        invalidation_state=invalidation_state,
        created_at_utc=verified_input.created_at_utc,
        metadata=verified_input.metadata,
    )
    return verify_market_structure_detection_result(result)


def verify_market_structure_detection_result(
    detection_result: MarketStructureDetectionResult,
) -> MarketStructureDetectionResult:
    if not isinstance(detection_result, MarketStructureDetectionResult):
        raise OfflineMarketStructureDetectorValidationError("market structure detection result is required.")
    expected_id = _hash_payload(detection_result._detection_result_id_payload())
    if detection_result.detection_result_id != expected_id:
        raise OfflineMarketStructureDetectorIntegrityError("detection_result_id mismatch.")
    expected_hash = _hash_payload(detection_result._detection_result_hash_payload())
    if detection_result.detection_result_hash != expected_hash:
        raise OfflineMarketStructureDetectorIntegrityError("detection_result_hash mismatch.")
    return detection_result


def market_structure_detection_result_to_dict(
    detection_result: MarketStructureDetectionResult,
) -> dict[str, Any]:
    if not isinstance(detection_result, MarketStructureDetectionResult):
        raise OfflineMarketStructureDetectorValidationError("market structure detection result is required.")
    return detection_result.as_dict()


def market_structure_detection_result_from_dict(
    data: Mapping[str, Any],
) -> MarketStructureDetectionResult:
    return MarketStructureDetectionResult.from_dict(data)


__all__ = [
    "OFFLINE_MARKET_STRUCTURE_DETECTOR_ALLOWED_STRUCTURE_STATES",
    "OFFLINE_MARKET_STRUCTURE_DETECTOR_ID",
    "OFFLINE_MARKET_STRUCTURE_DETECTOR_SCHEMA_VERSION",
    "OFFLINE_MARKET_STRUCTURE_DETECTOR_VERSION",
    "OFFLINE_MARKET_STRUCTURE_DETECTOR_PURPOSE",
    "MarketStructureDetectionInput",
    "MarketStructureDetectionResult",
    "OfflineMarketStructureDetectorError",
    "OfflineMarketStructureDetectorIntegrityError",
    "OfflineMarketStructureDetectorValidationError",
    "build_market_structure_detection_input",
    "detect_market_structure",
    "market_structure_detection_result_from_dict",
    "market_structure_detection_result_to_dict",
    "verify_market_structure_detection_input",
    "verify_market_structure_detection_result",
]
