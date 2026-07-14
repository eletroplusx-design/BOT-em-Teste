from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from domain.serialization import serialize_value

from .errors import PaperRuntimeAuditError

_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "headers",
    "message",
    "mensagem",
    "password",
    "secret",
    "token",
}

_SECRET_PATTERN = re.compile(r"(?i)(api[_-]?key|secret|token|bearer\s+[a-z0-9._-]+)")


def _iso_utc(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise PaperRuntimeAuditError("timestamp must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise PaperRuntimeAuditError("timestamp must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _redact_string(value: str) -> str:
    text = value.strip()
    if not text:
        return text
    if _SECRET_PATTERN.search(text):
        return "[REDACTED]"
    if len(text) > 128 and any(ch.isalnum() for ch in text):
        return "[REDACTED]"
    return text


def sanitize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _iso_utc(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).strip()
            if key_text.lower() in _SENSITIVE_KEYS:
                sanitized[key_text] = "[REDACTED]"
            else:
                sanitized[key_text] = sanitize_value(item)
        return sanitized
    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, bool) or value is None or isinstance(value, int) or isinstance(value, float):
        return value
    return _redact_string(str(value))


def sanitize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): sanitize_value(value) for key, value in payload.items()}


def canonical_json(payload: Mapping[str, Any]) -> str:
    try:
        sanitized = sanitize_payload(payload)
        return json.dumps(sanitized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except Exception as exc:
        raise PaperRuntimeAuditError("unable to serialize audit payload.") from exc


def sha256_hex(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def chain_hash(previous_hash: str, content_hash: str, *, session_id: str, sequence: int, event_type: str) -> str:
    payload = {
        "previous_hash": previous_hash,
        "content_hash": content_hash,
        "session_id": session_id,
        "sequence": sequence,
        "event_type": event_type,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def event_content_hash(event_payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(event_payload).encode("utf-8")).hexdigest()
