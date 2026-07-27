from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from domain.serialization import serialize_value

from .errors import HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError
from .research_artifact_registry import (
    OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED,
    OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT,
    OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256,
    OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH,
    OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256,
    OKX_RESEARCH_ARTIFACT_INTERVAL,
    OKX_RESEARCH_ARTIFACT_INSTRUMENT,
    OKX_RESEARCH_ARTIFACT_MARKET_TYPE,
    OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION,
    OKX_RESEARCH_ARTIFACT_PROVIDER_NAME,
    OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC,
    OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC,
    OKX_RESEARCH_ARTIFACT_SYMBOL,
    RESEARCH_ARTIFACT_REGISTRY_SCHEMA_VERSION,
    ResearchArtifactRegistryEntry,
)
from .research_artifact_registry import (
    HistoricalDataIntegrityError as ResearchArtifactRegistryIntegrityError,
    HistoricalDataValidationError as ResearchArtifactRegistryValidationError,
)


class ResearchArtifactRegistryVerificationError(HistoricalDataError):
    pass


class ResearchArtifactRegistryVerificationValidationError(
    ResearchArtifactRegistryVerificationError, HistoricalDataValidationError
):
    pass


class ResearchArtifactRegistryVerificationIntegrityError(
    ResearchArtifactRegistryVerificationError, HistoricalDataIntegrityError
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchArtifactRegistryVerificationValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ResearchArtifactRegistryVerificationValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise ResearchArtifactRegistryVerificationValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise ResearchArtifactRegistryVerificationValidationError(f"{field_name} must be a boolean.")
    return value


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ResearchArtifactRegistryVerificationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise ResearchArtifactRegistryVerificationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise ResearchArtifactRegistryVerificationValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise ResearchArtifactRegistryVerificationValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise ResearchArtifactRegistryVerificationValidationError("research artifact registry is missing.")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ResearchArtifactRegistryVerificationValidationError("research artifact registry is empty.")
    try:
        return json.loads(text)
    except Exception as exc:
        raise ResearchArtifactRegistryVerificationValidationError(
            "research artifact registry is invalid JSON."
        ) from exc


def _require_opaque_local_reference(value: Any) -> tuple[str, bool, bool]:
    ref = _require_str(value, "external_artifact_ref")
    lowered = ref.lower()
    if ref[0] in "{[":
        raise ResearchArtifactRegistryVerificationValidationError(
            "external_artifact_ref must be an opaque local reference, not artifact content."
        )
    if any(token in lowered for token in ("open_time", "close_time", "candle", "dataset_sha256", "manifest_sha256")):
        raise ResearchArtifactRegistryVerificationValidationError(
            "external_artifact_ref must not embed dataset content."
        )
    is_uri = "://" in ref
    is_local_path = Path(ref).is_absolute() or "/" in ref or "\\" in ref
    if not (is_uri or is_local_path):
        raise ResearchArtifactRegistryVerificationValidationError(
            "external_artifact_ref must be an opaque local path or URI."
        )
    return ref, True, is_local_path


def _assert_entry(entry: ResearchArtifactRegistryEntry) -> None:
    if entry.schema_version != RESEARCH_ARTIFACT_REGISTRY_SCHEMA_VERSION:
        raise ResearchArtifactRegistryVerificationValidationError("schema_version must be 1.")
    if entry.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise ResearchArtifactRegistryVerificationValidationError("provider_name must be OKX.")
    if entry.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise ResearchArtifactRegistryVerificationValidationError("market_type must be spot.")
    if entry.instrument != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise ResearchArtifactRegistryVerificationValidationError("instrument must be BTC-USDT.")
    if entry.symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise ResearchArtifactRegistryVerificationValidationError("symbol must be BTCUSDT.")
    if entry.interval != OKX_RESEARCH_ARTIFACT_INTERVAL:
        raise ResearchArtifactRegistryVerificationValidationError("interval must be 1H.")
    if entry.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise ResearchArtifactRegistryVerificationIntegrityError(
            "requested_start_inclusive_utc diverges from the OKX research artifact contract."
        )
    if entry.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise ResearchArtifactRegistryVerificationIntegrityError(
            "requested_end_exclusive_utc diverges from the OKX research artifact contract."
        )
    if entry.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise ResearchArtifactRegistryVerificationIntegrityError("expected_candle_count must be 42816.")
    if entry.audited_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise ResearchArtifactRegistryVerificationIntegrityError("audited_candle_count must be 42816.")
    if entry.audit_status != OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED:
        raise ResearchArtifactRegistryVerificationValidationError("audit_status must be passed.")
    if entry.historical_research_only is not True:
        raise ResearchArtifactRegistryVerificationValidationError("historical_research_only must be true.")
    if entry.operational_evidence is not False:
        raise ResearchArtifactRegistryVerificationValidationError("operational_evidence must be false.")
    if entry.paper_promotion_eligible is not False:
        raise ResearchArtifactRegistryVerificationValidationError("paper_promotion_eligible must be false.")
    if entry.non_operational_declaration != OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION:
        raise ResearchArtifactRegistryVerificationValidationError(
            "non_operational_declaration diverges from the OKX research artifact contract."
        )
    if _require_hex_digest(entry.dataset_sha256, "dataset_sha256") != OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256:
        raise ResearchArtifactRegistryVerificationIntegrityError("dataset_sha256 must match the OKX research artifact.")
    if _require_hex_digest(entry.manifest_sha256, "manifest_sha256") != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256:
        raise ResearchArtifactRegistryVerificationIntegrityError("manifest_sha256 must match the OKX research artifact.")
    if _require_hex_digest(entry.manifest_hash, "manifest_hash") != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH:
        raise ResearchArtifactRegistryVerificationIntegrityError("manifest_hash must match the OKX research artifact.")
    if entry.registry_hash != _hash_payload(entry.canonical_payload(include_registry_hash=False)):
        raise ResearchArtifactRegistryVerificationIntegrityError("registry_hash mismatch.")
    if entry.artifact_id != _hash_payload(entry._artifact_id_payload()):
        raise ResearchArtifactRegistryVerificationIntegrityError("artifact_id mismatch.")


@dataclass(frozen=True, slots=True)
class ResearchArtifactRegistryVerificationReport:
    schema_version: int = 1
    registry_file: Path = field(default_factory=Path)
    verified_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved: bool = True
    artifact_id: str = ""
    provider_name: str = OKX_RESEARCH_ARTIFACT_PROVIDER_NAME
    market_type: str = OKX_RESEARCH_ARTIFACT_MARKET_TYPE
    instrument: str = OKX_RESEARCH_ARTIFACT_INSTRUMENT
    symbol: str = OKX_RESEARCH_ARTIFACT_SYMBOL
    interval: str = OKX_RESEARCH_ARTIFACT_INTERVAL
    requested_start_inclusive_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC
    requested_end_exclusive_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC
    expected_candle_count: int = OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT
    audited_candle_count: int = OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT
    dataset_sha256: str = OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256
    manifest_sha256: str = OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256
    manifest_hash: str = OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH
    audit_status: str = OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED
    external_artifact_ref: str = ""
    external_artifact_ref_is_opaque: bool = True
    external_artifact_ref_is_local: bool = True
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION
    verification_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_file", Path(self.registry_file))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "verified_at_utc", _require_utc_datetime(self.verified_at_utc, "verified_at_utc"))
        object.__setattr__(self, "artifact_id", _require_str(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "provider_name", _require_str(self.provider_name, "provider_name").upper())
        object.__setattr__(self, "market_type", _require_str(self.market_type, "market_type").lower())
        object.__setattr__(self, "instrument", _require_str(self.instrument, "instrument").upper())
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "requested_start_inclusive_utc", _require_utc_datetime(self.requested_start_inclusive_utc, "requested_start_inclusive_utc"))
        object.__setattr__(self, "requested_end_exclusive_utc", _require_utc_datetime(self.requested_end_exclusive_utc, "requested_end_exclusive_utc"))
        object.__setattr__(self, "expected_candle_count", _require_int(self.expected_candle_count, "expected_candle_count"))
        object.__setattr__(self, "audited_candle_count", _require_int(self.audited_candle_count, "audited_candle_count"))
        object.__setattr__(self, "dataset_sha256", _require_hex_digest(self.dataset_sha256, "dataset_sha256"))
        object.__setattr__(self, "manifest_sha256", _require_hex_digest(self.manifest_sha256, "manifest_sha256"))
        object.__setattr__(self, "manifest_hash", _require_hex_digest(self.manifest_hash, "manifest_hash"))
        object.__setattr__(self, "audit_status", _require_str(self.audit_status, "audit_status").lower())
        object.__setattr__(self, "external_artifact_ref", _require_str(self.external_artifact_ref, "external_artifact_ref"))
        object.__setattr__(self, "external_artifact_ref_is_opaque", _require_bool(self.external_artifact_ref_is_opaque, "external_artifact_ref_is_opaque"))
        object.__setattr__(self, "external_artifact_ref_is_local", _require_bool(self.external_artifact_ref_is_local, "external_artifact_ref_is_local"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.approved is not True:
            raise ResearchArtifactRegistryVerificationValidationError("approved must be true.")
        if self.external_artifact_ref_is_opaque is not True:
            raise ResearchArtifactRegistryVerificationValidationError("external_artifact_ref must be opaque.")
        if self.external_artifact_ref_is_local is not True:
            raise ResearchArtifactRegistryVerificationValidationError("external_artifact_ref must be local.")
        if self.verification_hash:
            object.__setattr__(self, "verification_hash", _require_hex_digest(self.verification_hash, "verification_hash"))
            if self.verification_hash != _hash_payload(self.canonical_payload(include_verification_hash=False)):
                raise ResearchArtifactRegistryVerificationIntegrityError("verification_hash mismatch.")
        else:
            object.__setattr__(self, "verification_hash", _hash_payload(self.canonical_payload(include_verification_hash=False)))

    def canonical_payload(self, *, include_verification_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "registry_file": str(self.registry_file),
            "verified_at_utc": _utc_iso(self.verified_at_utc),
            "approved": self.approved,
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
            "dataset_sha256": self.dataset_sha256,
            "manifest_sha256": self.manifest_sha256,
            "manifest_hash": self.manifest_hash,
            "audit_status": self.audit_status,
            "external_artifact_ref": self.external_artifact_ref,
            "external_artifact_ref_is_opaque": self.external_artifact_ref_is_opaque,
            "external_artifact_ref_is_local": self.external_artifact_ref_is_local,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
        }
        if include_verification_hash:
            payload["verification_hash"] = self.verification_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_verification_hash=True))


def verify_okx_research_artifact_registry(
    registry_file: str | Path,
    *,
    expected_external_artifact_ref: str | None = None,
) -> ResearchArtifactRegistryVerificationReport:
    path = Path(registry_file)
    payload = _load_json(path)
    if not isinstance(payload, Mapping):
        raise ResearchArtifactRegistryVerificationValidationError("research artifact registry must be a JSON object.")
    try:
        entry = ResearchArtifactRegistryEntry.from_dict(payload)
    except ResearchArtifactRegistryValidationError as exc:
        raise ResearchArtifactRegistryVerificationValidationError(str(exc)) from exc
    except ResearchArtifactRegistryIntegrityError as exc:
        raise ResearchArtifactRegistryVerificationIntegrityError(str(exc)) from exc
    _assert_entry(entry)
    external_artifact_ref, is_opaque, is_local = _require_opaque_local_reference(entry.external_artifact_ref)
    if expected_external_artifact_ref is not None and external_artifact_ref != expected_external_artifact_ref:
        raise ResearchArtifactRegistryVerificationIntegrityError("external_artifact_ref mismatch.")
    report = ResearchArtifactRegistryVerificationReport(
        registry_file=path,
        artifact_id=entry.artifact_id,
        provider_name=entry.provider_name,
        market_type=entry.market_type,
        instrument=entry.instrument,
        symbol=entry.symbol,
        interval=entry.interval,
        requested_start_inclusive_utc=entry.requested_start_inclusive_utc,
        requested_end_exclusive_utc=entry.requested_end_exclusive_utc,
        expected_candle_count=entry.expected_candle_count,
        audited_candle_count=entry.audited_candle_count,
        dataset_sha256=entry.dataset_sha256,
        manifest_sha256=entry.manifest_sha256,
        manifest_hash=entry.manifest_hash,
        audit_status=entry.audit_status,
        external_artifact_ref=external_artifact_ref,
        external_artifact_ref_is_opaque=is_opaque,
        external_artifact_ref_is_local=is_local,
        historical_research_only=entry.historical_research_only,
        operational_evidence=entry.operational_evidence,
        paper_promotion_eligible=entry.paper_promotion_eligible,
        non_operational_declaration=entry.non_operational_declaration,
    )
    if report.as_dict() != serialize_value(report.canonical_payload()):
        raise ResearchArtifactRegistryVerificationIntegrityError("verification report payload mismatch.")
    return report
