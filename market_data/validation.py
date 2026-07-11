from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import isfinite
import re
from typing import Any, Iterable, Sequence

from domain import Candle, MarketSnapshot, DataSource, DomainValidationError

from .errors import MarketDataExpiredError, MarketDataValidationError


ALLOWED_INTERVALS = {
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "6h",
    "8h",
    "12h",
    "1d",
    "3d",
    "1w",
    "1M",
}

_INTERVAL_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
    "3d": 259200,
    "1w": 604800,
    "1M": 2592000,
}

MAX_BINANCE_LIMIT = 1000


def _is_month_start(dt: datetime) -> bool:
    return dt.day == 1 and dt.hour == 0 and dt.minute == 0 and dt.second == 0 and dt.microsecond == 0


def _next_month_start(dt: datetime) -> datetime:
    year = dt.year + (1 if dt.month == 12 else 0)
    month = 1 if dt.month == 12 else dt.month + 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def _expected_close_time(open_time: datetime, interval: str) -> datetime:
    if interval == "1M":
        return _next_month_start(open_time) - timedelta(milliseconds=1)
    return open_time + timedelta(seconds=_INTERVAL_SECONDS[interval]) - timedelta(milliseconds=1)


def _finite_decimal(value: Any, field_name: str, *, allow_zero: bool = True) -> Decimal:
    try:
        dec = Decimal(str(value))
    except Exception as exc:
        raise MarketDataValidationError(f"Invalid numeric value for {field_name}.") from exc
    if not dec.is_finite():
        raise MarketDataValidationError(f"{field_name} must be finite.")
    if allow_zero:
        if dec < 0:
            raise MarketDataValidationError(f"{field_name} must be >= 0.")
    elif dec <= 0:
        raise MarketDataValidationError(f"{field_name} must be > 0.")
    return dec


def validate_symbol_interval(symbol: str, interval: str) -> tuple[str, str]:
    if not isinstance(symbol, str) or not symbol.strip():
        raise MarketDataValidationError("symbol is required.")
    if not re.fullmatch(r"[A-Z0-9]{3,20}", symbol.strip().upper()):
        raise MarketDataValidationError(f"Invalid symbol: {symbol!r}")
    if interval not in ALLOWED_INTERVALS:
        raise MarketDataValidationError(f"Invalid interval: {interval!r}")
    return symbol.strip().upper(), interval


def validate_limit(limit: Any) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise MarketDataValidationError("limit must be an integer.")
    if limit <= 0:
        raise MarketDataValidationError("limit must be greater than zero.")
    if limit > MAX_BINANCE_LIMIT:
        raise MarketDataValidationError(f"limit must be <= {MAX_BINANCE_LIMIT}.")
    return limit


def _row_to_candle(row: Sequence[Any], symbol: str, interval: str) -> Candle:
    if len(row) < 7:
        raise MarketDataValidationError("Kline payload is partial.")
    open_time_ms, open_, high, low, close, volume, close_time_ms = row[:7]
    open_time = datetime.fromtimestamp(int(open_time_ms) / 1000, tz=timezone.utc)
    close_time = datetime.fromtimestamp(int(close_time_ms) / 1000, tz=timezone.utc)
    try:
        candle = Candle.from_dict(
            {
                "open_time": open_time,
                "close_time": close_time,
                "open": _finite_decimal(open_, "open"),
                "high": _finite_decimal(high, "high"),
                "low": _finite_decimal(low, "low"),
                "close": _finite_decimal(close, "close"),
                "volume": _finite_decimal(volume, "volume"),
                "symbol": symbol,
                "interval": interval,
                "source": DataSource.BINANCE,
            }
        )
    except DomainValidationError as exc:
        raise MarketDataValidationError(str(exc)) from exc
    return candle


def validate_klines_payload(
    payload: Any,
    *,
    symbol: str,
    interval: str,
    now: datetime | None = None,
) -> list[Candle]:
    symbol, interval = validate_symbol_interval(symbol, interval)
    if not isinstance(payload, list) or not payload:
        raise MarketDataValidationError("Empty or malformed response payload.")

    candles: list[Candle] = []
    seen_open_times: set[datetime] = set()
    last_open_time: datetime | None = None
    expected_gap = _INTERVAL_SECONDS[interval]
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise MarketDataValidationError("Reference time must include timezone information.")

    for idx, row in enumerate(payload):
        if not isinstance(row, (list, tuple)):
            raise MarketDataValidationError("Malformed kline row.")
        candle = _row_to_candle(row, symbol, interval)
        if candle.open_time >= candle.close_time:
            raise MarketDataValidationError("Candle timestamps are incoherent.")
        if candle.open_time in seen_open_times:
            raise MarketDataValidationError("Duplicate candle detected.")
        if candle.open_time > current_time:
            raise MarketDataValidationError("Future candle detected.")
        if interval == "1M":
            if not _is_month_start(candle.open_time):
                raise MarketDataValidationError("Monthly candles must start at month boundaries.")
            expected_open_time = _next_month_start(last_open_time) if last_open_time is not None else candle.open_time
            if last_open_time is not None:
                if candle.open_time < expected_open_time:
                    raise MarketDataValidationError("Klines are out of order.")
                if candle.open_time > expected_open_time:
                    raise MarketDataValidationError("Missing candle detected.")
        else:
            if last_open_time is not None:
                delta = int((candle.open_time - last_open_time).total_seconds())
                if delta < expected_gap:
                    raise MarketDataValidationError("Klines are out of order.")
                if delta > expected_gap:
                    raise MarketDataValidationError("Missing candle detected.")

        if candle.close_time > current_time:
            if idx != len(payload) - 1:
                raise MarketDataValidationError("Open candle detected before the end of the series.")
            if not candles:
                raise MarketDataValidationError("No closed candles available.")
            break

        expected_close_time = _expected_close_time(candle.open_time, interval)
        if candle.close_time != expected_close_time:
            raise MarketDataValidationError("Candle duration does not match the declared interval.")

        if candle.high < candle.low:
            raise MarketDataValidationError("high must be >= low.")
        if not (candle.low <= candle.open <= candle.high):
            raise MarketDataValidationError("open must be within candle range.")
        if not (candle.low <= candle.close <= candle.high):
            raise MarketDataValidationError("close must be within candle range.")
        seen_open_times.add(candle.open_time)
        last_open_time = candle.open_time
        candles.append(candle)

    return candles


def validate_market_data_consistency(
    candles: Sequence[Candle],
    *,
    max_age_seconds: int,
    now: datetime | None = None,
) -> None:
    if not candles:
        raise MarketDataValidationError("No candles available.")
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise MarketDataValidationError("Reference time must include timezone information.")
    latest = candles[-1]
    if latest.close_time > current_time:
        raise MarketDataValidationError("Latest candle is in the future.")
    age_seconds = (current_time - latest.close_time).total_seconds()
    if age_seconds > max_age_seconds:
        raise MarketDataExpiredError("Market data expired.")


def candles_to_snapshot(candles: Sequence[Candle]) -> MarketSnapshot:
    if not candles:
        raise MarketDataValidationError("No candles to build snapshot.")
    latest = candles[-1]
    return MarketSnapshot.from_dict(
        {
            "symbol": latest.symbol,
            "timestamp": latest.close_time,
            "current_price": latest.close,
            "source": latest.source,
            "candle": latest.to_dict(),
            "regime": None,
        }
    )
