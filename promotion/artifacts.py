from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from domain.serialization import serialize_value


def _normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, set):
        return [_normalize(item) for item in sorted(value, key=str)]
    if hasattr(value, "as_dict"):
        return _normalize(value.as_dict())
    return value


def promotion_hash(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(_normalize(dict(payload)), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_promotion_report(decision) -> dict[str, Any]:
    payload = decision.as_dict()
    payload["report_hash"] = promotion_hash(payload)
    return serialize_value(payload)
