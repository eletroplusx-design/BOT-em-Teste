from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from math import isfinite
import re
from typing import Any, TypeVar

from .enums import Direction


class DomainValidationError(ValueError):
    pass


_EnumT = TypeVar("_EnumT", bound=Enum)


def _require_not_blank(value: Any, field_name: str) -> str:
    if value is None:
        raise DomainValidationError(f"{field_name} is required.")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise DomainValidationError(f"{field_name} is required.")
        return text
    text = str(value).strip()
    if not text:
        raise DomainValidationError(f"{field_name} is required.")
    return text


def parse_symbol(value: Any) -> str:
    text = _require_not_blank(value, "symbol").upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,19}", text):
        raise DomainValidationError(f"Invalid symbol: {value!r}")
    return text


def parse_direction(value: Any) -> Direction:
    if isinstance(value, Direction):
        return value
    text = _require_not_blank(value, "direction").upper()
    aliases = {
        "BUY": Direction.COMPRA,
        "LONG": Direction.COMPRA,
        "COMPRA": Direction.COMPRA,
        "SELL": Direction.VENDA,
        "SHORT": Direction.VENDA,
        "VENDA": Direction.VENDA,
    }
    try:
        return aliases[text]
    except KeyError as exc:
        raise DomainValidationError(f"Invalid direction: {value!r}") from exc


def parse_enum(value: Any, enum_cls: type[_EnumT], field_name: str) -> _EnumT:
    if isinstance(value, enum_cls):
        return value
    text = _require_not_blank(value, field_name)
    for member in enum_cls:
        if text == member.value or text.upper() == member.value.upper():
            return member
    raise DomainValidationError(f"Invalid {field_name}: {value!r}")


def parse_decimal(value: Any, field_name: str, *, allow_zero: bool = False, allow_negative: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise DomainValidationError(f"{field_name} must be numeric.")
    if value is None:
        raise DomainValidationError(f"{field_name} is required.")
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise DomainValidationError(f"{field_name} must be numeric.") from exc
    if not decimal_value.is_finite():
        raise DomainValidationError(f"{field_name} must be finite.")
    if not allow_negative:
        if allow_zero:
            if decimal_value < 0:
                raise DomainValidationError(f"{field_name} must be >= 0.")
        elif decimal_value <= 0:
            raise DomainValidationError(f"{field_name} must be > 0.")
    return decimal_value


def parse_strict_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise DomainValidationError(f"{field_name} must be a boolean.")
    return value


def parse_bool_true_only(value: Any, field_name: str) -> bool:
    if type(value) is not bool or value is not True:
        raise DomainValidationError(f"{field_name} must be True.")
    return True


def parse_bool_false_only(value: Any, field_name: str) -> bool:
    if type(value) is not bool or value is not False:
        raise DomainValidationError(f"{field_name} must be False.")
    return False


def parse_timezone_aware_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
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

    if dt.tzinfo is None or dt.utcoffset() is None:
        raise DomainValidationError(f"{field_name} must include timezone information.")
    return dt.astimezone(timezone.utc)


def ensure_price_coherence(direction: Direction, entry: Decimal, stop_loss: Decimal, take_profit: Decimal) -> None:
    if direction == Direction.COMPRA:
        if not (stop_loss < entry < take_profit):
            raise DomainValidationError("For COMPRA, stop_loss < entry < take_profit is required.")
    elif direction == Direction.VENDA:
        if not (take_profit < entry < stop_loss):
            raise DomainValidationError("For VENDA, take_profit < entry < stop_loss is required.")
    else:  # pragma: no cover - defensive, Direction is closed
        raise DomainValidationError(f"Unsupported direction: {direction!r}")
