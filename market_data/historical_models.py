from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from domain import Candle, MarketSnapshot
from domain.serialization import serialize_value

from .errors import HistoricalDataIntegrityError, HistoricalDataValidationError


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalDataValidationError(f"{field_name} is required.")
    return value.strip()


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalDataValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalDataValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalDataValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalDataValidationError(f"{field_name} must be a boolean.")
    return value


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.") from exc
    if not isinstance(value, datetime):
        raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def candles_content_hash(candles: Sequence[Candle]) -> str:
    payload = [candle.to_dict() for candle in candles]
    return _hash_payload(payload)


@dataclass(frozen=True, slots=True)
class HistoricalDatasetRequest:
    provider: str
    endpoint: str
    symbol: str
    interval: str
    requested_start_utc: datetime
    requested_end_utc: datetime
    page_size: int
    closed_candles_only: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _require_str(self.provider, "provider"))
        object.__setattr__(self, "endpoint", _require_str(self.endpoint, "endpoint"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "requested_start_utc", _require_utc_datetime(self.requested_start_utc, "requested_start_utc"))
        object.__setattr__(self, "requested_end_utc", _require_utc_datetime(self.requested_end_utc, "requested_end_utc"))
        object.__setattr__(self, "page_size", _require_int(self.page_size, "page_size"))
        object.__setattr__(self, "closed_candles_only", _require_bool(self.closed_candles_only, "closed_candles_only"))
        if self.requested_end_utc <= self.requested_start_utc:
            raise HistoricalDataValidationError("requested_end_utc must be after requested_start_utc.")
        if self.page_size > 1000:
            raise HistoricalDataValidationError("page_size must be <= 1000.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "endpoint": self.endpoint,
            "symbol": self.symbol,
            "interval": self.interval,
            "requested_start_utc": _utc_iso(self.requested_start_utc),
            "requested_end_utc": _utc_iso(self.requested_end_utc),
            "page_size": self.page_size,
            "closed_candles_only": self.closed_candles_only,
        }


@dataclass(frozen=True, slots=True)
class HistoricalDatasetManifest:
    schema_version: int
    dataset_id: str
    provider: str
    endpoint: str
    symbol: str
    interval: str
    requested_start_utc: datetime
    requested_end_utc: datetime
    effective_start_utc: datetime
    effective_end_utc: datetime
    created_at_utc: datetime
    candle_count: int
    page_count: int
    page_size: int
    closed_candles_only: bool
    gap_count: int
    duplicate_count: int
    content_hash: str
    manifest_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "dataset_id", _require_str(self.dataset_id, "dataset_id"))
        object.__setattr__(self, "provider", _require_str(self.provider, "provider"))
        object.__setattr__(self, "endpoint", _require_str(self.endpoint, "endpoint"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "requested_start_utc", _require_utc_datetime(self.requested_start_utc, "requested_start_utc"))
        object.__setattr__(self, "requested_end_utc", _require_utc_datetime(self.requested_end_utc, "requested_end_utc"))
        object.__setattr__(self, "effective_start_utc", _require_utc_datetime(self.effective_start_utc, "effective_start_utc"))
        object.__setattr__(self, "effective_end_utc", _require_utc_datetime(self.effective_end_utc, "effective_end_utc"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "candle_count", _require_int(self.candle_count, "candle_count", allow_zero=True))
        object.__setattr__(self, "page_count", _require_int(self.page_count, "page_count", allow_zero=True))
        object.__setattr__(self, "page_size", _require_int(self.page_size, "page_size"))
        object.__setattr__(self, "closed_candles_only", _require_bool(self.closed_candles_only, "closed_candles_only"))
        object.__setattr__(self, "gap_count", _require_int(self.gap_count, "gap_count", allow_zero=True))
        object.__setattr__(self, "duplicate_count", _require_int(self.duplicate_count, "duplicate_count", allow_zero=True))
        object.__setattr__(self, "content_hash", _require_str(self.content_hash, "content_hash"))
        if self.page_size > 1000:
            raise HistoricalDataValidationError("page_size must be <= 1000.")
        if self.requested_end_utc <= self.requested_start_utc:
            raise HistoricalDataValidationError("requested_end_utc must be after requested_start_utc.")
        if self.effective_end_utc < self.effective_start_utc:
            raise HistoricalDataValidationError("effective_end_utc must not be before effective_start_utc.")
        if self.manifest_hash:
            object.__setattr__(self, "manifest_hash", _require_str(self.manifest_hash, "manifest_hash"))

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "symbol": self.symbol,
            "interval": self.interval,
            "requested_start_utc": _utc_iso(self.requested_start_utc),
            "requested_end_utc": _utc_iso(self.requested_end_utc),
            "effective_start_utc": _utc_iso(self.effective_start_utc),
            "effective_end_utc": _utc_iso(self.effective_end_utc),
            "created_at_utc": _utc_iso(self.created_at_utc),
            "candle_count": self.candle_count,
            "page_count": self.page_count,
            "page_size": self.page_size,
            "closed_candles_only": self.closed_candles_only,
            "gap_count": self.gap_count,
            "duplicate_count": self.duplicate_count,
            "content_hash": self.content_hash,
        }
        payload["manifest_hash"] = self.manifest_hash or _hash_payload(payload)
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalDatasetManifest":
        mapping = dict(data)
        return cls(
            schema_version=mapping.get("schema_version", 1),
            dataset_id=mapping["dataset_id"],
            provider=mapping["provider"],
            endpoint=mapping["endpoint"],
            symbol=mapping["symbol"],
            interval=mapping["interval"],
            requested_start_utc=mapping["requested_start_utc"],
            requested_end_utc=mapping["requested_end_utc"],
            effective_start_utc=mapping["effective_start_utc"],
            effective_end_utc=mapping["effective_end_utc"],
            created_at_utc=mapping["created_at_utc"],
            candle_count=mapping["candle_count"],
            page_count=mapping["page_count"],
            page_size=mapping["page_size"],
            closed_candles_only=mapping["closed_candles_only"],
            gap_count=mapping["gap_count"],
            duplicate_count=mapping["duplicate_count"],
            content_hash=mapping["content_hash"],
            manifest_hash=mapping.get("manifest_hash", ""),
        )

    def canonical_payload(self) -> dict[str, Any]:
        payload = self.as_dict()
        payload.pop("manifest_hash", None)
        return payload

    def matches_request(self, request: HistoricalDatasetRequest) -> bool:
        return (
            self.provider == request.provider
            and self.endpoint == request.endpoint
            and self.symbol == request.symbol
            and self.interval == request.interval
            and self.requested_start_utc == request.requested_start_utc
            and self.requested_end_utc == request.requested_end_utc
            and self.page_size == request.page_size
            and self.closed_candles_only is request.closed_candles_only
        )


@dataclass(frozen=True, slots=True)
class HistoricalDataset:
    manifest: HistoricalDatasetManifest
    candles: tuple[Candle, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.candles, tuple):
            object.__setattr__(self, "candles", tuple(self.candles))
        if self.manifest.candle_count != len(self.candles):
            raise HistoricalDataIntegrityError("manifest candle_count does not match candles.")
        if self.candles and self.manifest.content_hash != candles_content_hash(self.candles):
            raise HistoricalDataIntegrityError("content_hash mismatch.")
        if self.manifest.dataset_id != self.manifest.content_hash:
            raise HistoricalDataIntegrityError("dataset_id must match content_hash.")
        if self.manifest.manifest_hash and self.manifest.manifest_hash != _hash_payload(self.manifest.canonical_payload()):
            raise HistoricalDataIntegrityError("manifest_hash mismatch.")
        if self.candles:
            first = self.candles[0].open_time
            last = self.candles[-1].close_time
            if first != self.manifest.effective_start_utc or last != self.manifest.effective_end_utc:
                raise HistoricalDataIntegrityError("manifest candle bounds do not match candles.")

    def as_dict(self) -> dict[str, Any]:
        manifest_payload = self.manifest.as_dict()
        return {
            "manifest": manifest_payload,
            "candles": [candle.to_dict() for candle in self.candles],
        }

    def replay_snapshots(self) -> tuple[MarketSnapshot, ...]:
        snapshots = []
        for candle in self.candles:
            snapshots.append(
                MarketSnapshot.from_dict(
                    {
                        "symbol": candle.symbol,
                        "timestamp": candle.close_time,
                        "current_price": candle.close,
                        "source": candle.source,
                        "candle": candle.to_dict(),
                        "regime": None,
                    }
                )
            )
        return tuple(snapshots)
