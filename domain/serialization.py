from __future__ import annotations

from dataclasses import asdict, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
import json
from enum import Enum
from typing import Any


def serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone().isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: serialize_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {key: serialize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_value(item) for item in value]
    return value


def to_jsonable(mapping: dict[str, Any]) -> dict[str, Any]:
    return {key: serialize_value(value) for key, value in mapping.items()}


def dumps_json(value: Any) -> str:
    return json.dumps(serialize_value(value), ensure_ascii=True, sort_keys=True)
