from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Mapping

from domain.serialization import serialize_value

from .errors import HistoricalDataConflictError, HistoricalDataIntegrityError, HistoricalDataValidationError

RESEARCH_ARTIFACT_REGISTRY_SCHEMA_VERSION = 1
RESEARCH_ARTIFACT_REGISTRY_ALLOWED_USE_CASES = {"research", "registry", "offline-audit"}
RESEARCH_ARTIFACT_REGISTRY_DISALLOWED_USE_CASES = {"replay", "backtest", "performance", "ranking", "paper", "live"}

OKX_RESEARCH_ARTIFACT_PROVIDER_NAME = "OKX"
OKX_RESEARCH_ARTIFACT_MARKET_TYPE = "spot"
OKX_RESEARCH_ARTIFACT_INSTRUMENT = "BTC-USDT"
OKX_RESEARCH_ARTIFACT_SYMBOL = "BTCUSDT"
OKX_RESEARCH_ARTIFACT_INTERVAL = "1H"
OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC = datetime(2021, 2, 12, 0, 0, tzinfo=timezone.utc)
OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT = 42816
OKX_RESEARCH_ARTIFACT_AUDITED_CANDLE_COUNT = 42816
OKX_RESEARCH_ARTIFACT_AUDITED_GAP_COUNT = 0
OKX_RESEARCH_ARTIFACT_AUDITED_DUPLICATE_COUNT = 0
OKX_RESEARCH_ARTIFACT_AUDITED_CONFIRM_REQUIRED_VALUE = 1
OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256 = "b6b86ad0d80ef714ce15e21c141ce59190f1b63ec6b6cce671569475eba6d4d8"
OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256 = "57bae08a8a0a21fd662034d874eeb719d0ffd88c88c5836e66c64fcc02086515"
OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH = "8c9bcc3b0e86032c0e1c5cb671f5ac3cd704ee43b2768d49335a051169cec7ab"
OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED = "passed"
OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION = (
    "This artifact is research-only and does not authorize replay, backtest, performance, ranking, paper trading, or live trading."
)


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _hour_delta() -> timedelta:
    return timedelta(hours=1)


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalDataValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalDataValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalDataValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalDataValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalDataValidationError(f"{field_name} must be greater than zero.")
    return int(value)


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


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise HistoricalDataValidationError(f"{field_name} must be a 64-character hex digest.")
    return digest


def _ensure_disallowed_use_case(use_case: str) -> None:
    normalized = _require_str(use_case, "use_case").lower()
    if normalized in RESEARCH_ARTIFACT_REGISTRY_DISALLOWED_USE_CASES:
        raise HistoricalDataValidationError(f"use_case {normalized!r} is not authorized for a research-only registry entry.")
    if normalized not in RESEARCH_ARTIFACT_REGISTRY_ALLOWED_USE_CASES:
        raise HistoricalDataValidationError(f"use_case {normalized!r} is not supported by the research-only registry gate.")


def _ensure_okx_research_contract(entry: "ResearchArtifactRegistryEntry") -> None:
    if entry.schema_version != RESEARCH_ARTIFACT_REGISTRY_SCHEMA_VERSION:
        raise HistoricalDataValidationError("schema_version must be 1.")
    if entry.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise HistoricalDataValidationError("provider_name must be OKX.")
    if entry.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise HistoricalDataValidationError("market_type must be spot.")
    if entry.instrument != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise HistoricalDataValidationError("instrument must be BTC-USDT.")
    if entry.symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise HistoricalDataValidationError("symbol must be BTCUSDT.")
    if entry.interval != OKX_RESEARCH_ARTIFACT_INTERVAL:
        raise HistoricalDataValidationError("interval must be 1H.")
    if entry.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise HistoricalDataValidationError("requested_start_inclusive_utc diverges from the OKX research artifact contract.")
    if entry.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise HistoricalDataValidationError("requested_end_exclusive_utc diverges from the OKX research artifact contract.")
    if entry.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise HistoricalDataValidationError("expected_candle_count must be 42816.")
    if entry.audited_candle_count != OKX_RESEARCH_ARTIFACT_AUDITED_CANDLE_COUNT:
        raise HistoricalDataIntegrityError("audited_candle_count must match the OKX research artifact.")
    if entry.audited_first_candle_open_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise HistoricalDataIntegrityError("audited_first_candle_open_utc does not match the OKX research artifact.")
    if entry.audited_first_candle_close_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC + _hour_delta() - timedelta(milliseconds=1):
        raise HistoricalDataIntegrityError("audited_first_candle_close_utc does not match the OKX research artifact.")
    if entry.audited_last_candle_open_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC - _hour_delta():
        raise HistoricalDataIntegrityError("audited_last_candle_open_utc does not match the OKX research artifact.")
    if entry.audited_last_candle_close_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC - timedelta(milliseconds=1):
        raise HistoricalDataIntegrityError("audited_last_candle_close_utc does not match the OKX research artifact.")
    if entry.audited_gap_count != OKX_RESEARCH_ARTIFACT_AUDITED_GAP_COUNT:
        raise HistoricalDataIntegrityError("audited_gap_count must be zero.")
    if entry.audited_duplicate_count != OKX_RESEARCH_ARTIFACT_AUDITED_DUPLICATE_COUNT:
        raise HistoricalDataIntegrityError("audited_duplicate_count must be zero.")
    if entry.audited_confirm_required_value != OKX_RESEARCH_ARTIFACT_AUDITED_CONFIRM_REQUIRED_VALUE:
        raise HistoricalDataIntegrityError("audited_confirm_required_value must be 1.")
    if entry.audit_status != OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED:
        raise HistoricalDataValidationError("audit_status must be passed.")
    if entry.historical_research_only is not True:
        raise HistoricalDataValidationError("historical_research_only must be true.")
    if entry.operational_evidence is not False:
        raise HistoricalDataValidationError("operational_evidence must be false.")
    if entry.paper_promotion_eligible is not False:
        raise HistoricalDataValidationError("paper_promotion_eligible must be false.")
    if entry.external_artifact_ref != _require_str(entry.external_artifact_ref, "external_artifact_ref"):
        raise HistoricalDataValidationError("external_artifact_ref is required.")
    if entry.non_operational_declaration != OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION:
        raise HistoricalDataValidationError("non_operational_declaration diverges from the OKX research artifact contract.")
    if _require_hex_digest(entry.dataset_sha256, "dataset_sha256") != OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256:
        raise HistoricalDataIntegrityError("dataset_sha256 must match the OKX research artifact.")
    if _require_hex_digest(entry.manifest_sha256, "manifest_sha256") != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256:
        raise HistoricalDataIntegrityError("manifest_sha256 must match the OKX research artifact.")
    if _require_hex_digest(entry.manifest_hash, "manifest_hash") != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH:
        raise HistoricalDataIntegrityError("manifest_hash must match the OKX research artifact.")


@dataclass(frozen=True, slots=True)
class ResearchArtifactRegistryEntry:
    schema_version: int = RESEARCH_ARTIFACT_REGISTRY_SCHEMA_VERSION
    artifact_id: str = ""
    provider_name: str = OKX_RESEARCH_ARTIFACT_PROVIDER_NAME
    market_type: str = OKX_RESEARCH_ARTIFACT_MARKET_TYPE
    instrument: str = OKX_RESEARCH_ARTIFACT_INSTRUMENT
    symbol: str = OKX_RESEARCH_ARTIFACT_SYMBOL
    interval: str = OKX_RESEARCH_ARTIFACT_INTERVAL
    requested_start_inclusive_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC
    requested_end_exclusive_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC
    expected_candle_count: int = OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT
    audited_candle_count: int = OKX_RESEARCH_ARTIFACT_AUDITED_CANDLE_COUNT
    audited_first_candle_open_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC
    audited_first_candle_close_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC + _hour_delta() - timedelta(milliseconds=1)
    audited_last_candle_open_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC - _hour_delta()
    audited_last_candle_close_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC - timedelta(milliseconds=1)
    audited_gap_count: int = OKX_RESEARCH_ARTIFACT_AUDITED_GAP_COUNT
    audited_duplicate_count: int = OKX_RESEARCH_ARTIFACT_AUDITED_DUPLICATE_COUNT
    audited_confirm_required_value: int = OKX_RESEARCH_ARTIFACT_AUDITED_CONFIRM_REQUIRED_VALUE
    dataset_sha256: str = ""
    manifest_sha256: str = ""
    manifest_hash: str = ""
    audit_status: str = OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED
    registered_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    external_artifact_ref: str = ""
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION
    registry_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "artifact_id", _require_str(self.artifact_id, "artifact_id") if self.artifact_id else "")
        object.__setattr__(self, "provider_name", _require_str(self.provider_name, "provider_name").upper())
        object.__setattr__(self, "market_type", _require_str(self.market_type, "market_type").lower())
        object.__setattr__(self, "instrument", _require_str(self.instrument, "instrument").upper())
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "requested_start_inclusive_utc", _require_utc_datetime(self.requested_start_inclusive_utc, "requested_start_inclusive_utc"))
        object.__setattr__(self, "requested_end_exclusive_utc", _require_utc_datetime(self.requested_end_exclusive_utc, "requested_end_exclusive_utc"))
        object.__setattr__(self, "expected_candle_count", _require_int(self.expected_candle_count, "expected_candle_count"))
        object.__setattr__(self, "audited_candle_count", _require_int(self.audited_candle_count, "audited_candle_count"))
        object.__setattr__(self, "audited_first_candle_open_utc", _require_utc_datetime(self.audited_first_candle_open_utc, "audited_first_candle_open_utc"))
        object.__setattr__(self, "audited_first_candle_close_utc", _require_utc_datetime(self.audited_first_candle_close_utc, "audited_first_candle_close_utc"))
        object.__setattr__(self, "audited_last_candle_open_utc", _require_utc_datetime(self.audited_last_candle_open_utc, "audited_last_candle_open_utc"))
        object.__setattr__(self, "audited_last_candle_close_utc", _require_utc_datetime(self.audited_last_candle_close_utc, "audited_last_candle_close_utc"))
        object.__setattr__(self, "audited_gap_count", _require_int(self.audited_gap_count, "audited_gap_count", allow_zero=True))
        object.__setattr__(self, "audited_duplicate_count", _require_int(self.audited_duplicate_count, "audited_duplicate_count", allow_zero=True))
        object.__setattr__(self, "audited_confirm_required_value", _require_int(self.audited_confirm_required_value, "audited_confirm_required_value"))
        object.__setattr__(self, "dataset_sha256", _require_hex_digest(self.dataset_sha256, "dataset_sha256"))
        object.__setattr__(self, "manifest_sha256", _require_hex_digest(self.manifest_sha256, "manifest_sha256"))
        object.__setattr__(self, "manifest_hash", _require_hex_digest(self.manifest_hash, "manifest_hash"))
        object.__setattr__(self, "audit_status", _require_str(self.audit_status, "audit_status").lower())
        object.__setattr__(self, "registered_at_utc", _require_utc_datetime(self.registered_at_utc, "registered_at_utc"))
        object.__setattr__(self, "external_artifact_ref", _require_str(self.external_artifact_ref, "external_artifact_ref"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.requested_end_exclusive_utc <= self.requested_start_inclusive_utc:
            raise HistoricalDataValidationError("requested_end_exclusive_utc must be after requested_start_inclusive_utc.")
        if self.audit_status != OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED:
            raise HistoricalDataValidationError("audit_status must be passed.")
        _ensure_okx_research_contract(self)
        artifact_id_payload = self._artifact_id_payload()
        expected_artifact_id = _hash_payload(artifact_id_payload)
        if self.artifact_id:
            if self.artifact_id != expected_artifact_id:
                raise HistoricalDataValidationError("artifact_id mismatch.")
        else:
            object.__setattr__(self, "artifact_id", expected_artifact_id)
        registry_hash_payload = self.canonical_payload(include_registry_hash=False)
        expected_registry_hash = _hash_payload(registry_hash_payload)
        if self.registry_hash:
            if self.registry_hash != expected_registry_hash:
                raise HistoricalDataValidationError("registry_hash mismatch.")
        else:
            object.__setattr__(self, "registry_hash", expected_registry_hash)

    def _artifact_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider_name": self.provider_name,
            "market_type": self.market_type,
            "instrument": self.instrument,
            "symbol": self.symbol,
            "interval": self.interval,
            "requested_start_inclusive_utc": _utc_iso(self.requested_start_inclusive_utc),
            "requested_end_exclusive_utc": _utc_iso(self.requested_end_exclusive_utc),
            "expected_candle_count": self.expected_candle_count,
            "audited_candle_count": self.audited_candle_count,
            "audited_first_candle_open_utc": _utc_iso(self.audited_first_candle_open_utc),
            "audited_first_candle_close_utc": _utc_iso(self.audited_first_candle_close_utc),
            "audited_last_candle_open_utc": _utc_iso(self.audited_last_candle_open_utc),
            "audited_last_candle_close_utc": _utc_iso(self.audited_last_candle_close_utc),
            "audited_gap_count": self.audited_gap_count,
            "audited_duplicate_count": self.audited_duplicate_count,
            "audited_confirm_required_value": self.audited_confirm_required_value,
            "dataset_sha256": self.dataset_sha256,
            "manifest_sha256": self.manifest_sha256,
            "manifest_hash": self.manifest_hash,
            "audit_status": self.audit_status,
            "external_artifact_ref": self.external_artifact_ref,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
        }

    def canonical_payload(self, *, include_registry_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "provider_name": self.provider_name,
            "market_type": self.market_type,
            "instrument": self.instrument,
            "symbol": self.symbol,
            "interval": self.interval,
            "requested_start_inclusive_utc": _utc_iso(self.requested_start_inclusive_utc),
            "requested_end_exclusive_utc": _utc_iso(self.requested_end_exclusive_utc),
            "expected_candle_count": self.expected_candle_count,
            "audited_candle_count": self.audited_candle_count,
            "audited_first_candle_open_utc": _utc_iso(self.audited_first_candle_open_utc),
            "audited_first_candle_close_utc": _utc_iso(self.audited_first_candle_close_utc),
            "audited_last_candle_open_utc": _utc_iso(self.audited_last_candle_open_utc),
            "audited_last_candle_close_utc": _utc_iso(self.audited_last_candle_close_utc),
            "audited_gap_count": self.audited_gap_count,
            "audited_duplicate_count": self.audited_duplicate_count,
            "audited_confirm_required_value": self.audited_confirm_required_value,
            "dataset_sha256": self.dataset_sha256,
            "manifest_sha256": self.manifest_sha256,
            "manifest_hash": self.manifest_hash,
            "audit_status": self.audit_status,
            "registered_at_utc": _utc_iso(self.registered_at_utc),
            "external_artifact_ref": self.external_artifact_ref,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
        }
        if include_registry_hash:
            payload["registry_hash"] = self.registry_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_registry_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResearchArtifactRegistryEntry":
        if not isinstance(data, Mapping):
            raise HistoricalDataValidationError("research artifact registry entry must be a mapping.")
        mapping = dict(data)
        allowed = {
            "schema_version",
            "artifact_id",
            "provider_name",
            "market_type",
            "instrument",
            "symbol",
            "interval",
            "requested_start_inclusive_utc",
            "requested_end_exclusive_utc",
            "expected_candle_count",
            "audited_candle_count",
            "audited_first_candle_open_utc",
            "audited_first_candle_close_utc",
            "audited_last_candle_open_utc",
            "audited_last_candle_close_utc",
            "audited_gap_count",
            "audited_duplicate_count",
            "audited_confirm_required_value",
            "dataset_sha256",
            "manifest_sha256",
            "manifest_hash",
            "audit_status",
            "registered_at_utc",
            "external_artifact_ref",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "non_operational_declaration",
            "registry_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise HistoricalDataValidationError(f"unexpected research artifact registry fields: {', '.join(extra)}.")
        try:
            return cls(
                schema_version=mapping["schema_version"],
                artifact_id=mapping.get("artifact_id", ""),
                provider_name=mapping["provider_name"],
                market_type=mapping["market_type"],
                instrument=mapping["instrument"],
                symbol=mapping["symbol"],
                interval=mapping["interval"],
                requested_start_inclusive_utc=mapping["requested_start_inclusive_utc"],
                requested_end_exclusive_utc=mapping["requested_end_exclusive_utc"],
                expected_candle_count=mapping["expected_candle_count"],
                audited_candle_count=mapping["audited_candle_count"],
                audited_first_candle_open_utc=mapping["audited_first_candle_open_utc"],
                audited_first_candle_close_utc=mapping["audited_first_candle_close_utc"],
                audited_last_candle_open_utc=mapping["audited_last_candle_open_utc"],
                audited_last_candle_close_utc=mapping["audited_last_candle_close_utc"],
                audited_gap_count=mapping["audited_gap_count"],
                audited_duplicate_count=mapping["audited_duplicate_count"],
                audited_confirm_required_value=mapping["audited_confirm_required_value"],
                dataset_sha256=mapping["dataset_sha256"],
                manifest_sha256=mapping["manifest_sha256"],
                manifest_hash=mapping["manifest_hash"],
                audit_status=mapping["audit_status"],
                registered_at_utc=mapping.get("registered_at_utc", datetime.now(timezone.utc)),
                external_artifact_ref=mapping["external_artifact_ref"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                non_operational_declaration=mapping.get(
                    "non_operational_declaration", OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION
                ),
                registry_hash=mapping.get("registry_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalDataValidationError("research artifact registry entry is incomplete.") from exc


def build_okx_research_artifact_registry_entry(
    *,
    external_artifact_ref: str,
    dataset_sha256: str,
    manifest_sha256: str,
    manifest_hash: str,
    registered_at_utc: datetime | None = None,
    audited_candle_count: int = OKX_RESEARCH_ARTIFACT_AUDITED_CANDLE_COUNT,
    audited_first_candle_open_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC,
    audited_first_candle_close_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC + _hour_delta() - timedelta(milliseconds=1),
    audited_last_candle_open_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC - _hour_delta(),
    audited_last_candle_close_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC - timedelta(milliseconds=1),
    audited_gap_count: int = OKX_RESEARCH_ARTIFACT_AUDITED_GAP_COUNT,
    audited_duplicate_count: int = OKX_RESEARCH_ARTIFACT_AUDITED_DUPLICATE_COUNT,
    audited_confirm_required_value: int = OKX_RESEARCH_ARTIFACT_AUDITED_CONFIRM_REQUIRED_VALUE,
    audit_status: str = OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED,
    historical_research_only: bool = True,
    operational_evidence: bool = False,
    paper_promotion_eligible: bool = False,
    non_operational_declaration: str = OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION,
) -> ResearchArtifactRegistryEntry:
    return ResearchArtifactRegistryEntry(
        registered_at_utc=registered_at_utc or datetime.now(timezone.utc),
        external_artifact_ref=external_artifact_ref,
        dataset_sha256=dataset_sha256,
        manifest_sha256=manifest_sha256,
        manifest_hash=manifest_hash,
        audited_candle_count=audited_candle_count,
        audited_first_candle_open_utc=audited_first_candle_open_utc,
        audited_first_candle_close_utc=audited_first_candle_close_utc,
        audited_last_candle_open_utc=audited_last_candle_open_utc,
        audited_last_candle_close_utc=audited_last_candle_close_utc,
        audited_gap_count=audited_gap_count,
        audited_duplicate_count=audited_duplicate_count,
        audited_confirm_required_value=audited_confirm_required_value,
        audit_status=audit_status,
        historical_research_only=historical_research_only,
        operational_evidence=operational_evidence,
        paper_promotion_eligible=paper_promotion_eligible,
        non_operational_declaration=non_operational_declaration,
    )


def validate_research_artifact_registry_entry(
    entry: ResearchArtifactRegistryEntry,
    *,
    use_case: str = "research",
    operational_evidence: bool = False,
    paper_promotion_eligible: bool = False,
) -> ResearchArtifactRegistryEntry:
    _ensure_disallowed_use_case(use_case)
    if operational_evidence is not False:
        raise HistoricalDataValidationError("operational_evidence must be false.")
    if paper_promotion_eligible is not False:
        raise HistoricalDataValidationError("paper_promotion_eligible must be false.")
    if not isinstance(entry, ResearchArtifactRegistryEntry):
        raise HistoricalDataValidationError("research artifact registry entry is required.")
    _ensure_okx_research_contract(entry)
    return entry


def _load_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise HistoricalDataValidationError("Research artifact registry not found.")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise HistoricalDataValidationError("Research artifact registry is empty.")
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise HistoricalDataValidationError("Research artifact registry is invalid JSON.") from exc
    if not isinstance(payload, Mapping):
        raise HistoricalDataValidationError("Research artifact registry must be a JSON object.")
    return payload


def load_research_artifact_registry(path: str | Path) -> ResearchArtifactRegistryEntry:
    file_path = Path(path)
    payload = _load_json(file_path)
    entry = ResearchArtifactRegistryEntry.from_dict(payload)
    if entry.as_dict() != payload:
        raise HistoricalDataIntegrityError("research artifact registry payload mismatch.")
    return entry


def save_research_artifact_registry(path: str | Path, entry: ResearchArtifactRegistryEntry) -> ResearchArtifactRegistryEntry:
    file_path = Path(path)
    payload = entry.as_dict()
    if file_path.exists():
        existing = load_research_artifact_registry(file_path)
        if existing.as_dict() != payload:
            raise HistoricalDataConflictError("research artifact registry already exists and differs.")
        return existing
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f".{file_path.name}.{os.getpid()}.{id(entry)}.tmp")
    try:
        tmp_path.write_text(_canonical_json(payload), encoding="utf-8")
        os.replace(tmp_path, file_path)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HistoricalDataValidationError("Failed to write research artifact registry atomically.") from exc
    return entry


def register_okx_historical_research_artifact(
    *,
    path: str | Path,
    external_artifact_ref: str,
    dataset_sha256: str,
    manifest_sha256: str,
    manifest_hash: str,
    registered_at_utc: datetime | None = None,
) -> ResearchArtifactRegistryEntry:
    entry = build_okx_research_artifact_registry_entry(
        external_artifact_ref=external_artifact_ref,
        dataset_sha256=dataset_sha256,
        manifest_sha256=manifest_sha256,
        manifest_hash=manifest_hash,
        registered_at_utc=registered_at_utc,
    )
    return save_research_artifact_registry(path, entry)
