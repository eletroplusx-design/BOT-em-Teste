from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
from typing import Any, Sequence

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
)
from .research_artifact_registry_verification import ResearchArtifactRegistryVerificationReport

OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_SCHEMA_VERSION = 1
OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PURPOSE = "offline_historical_research"
OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_ALLOWED_USE_CASES: tuple[str, ...] = (
    "experiment_contract_validation",
)
OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PROHIBITED_USE_CASES: tuple[str, ...] = (
    "replay",
    "backtest",
    "walk_forward",
    "performance",
    "ranking",
    "paper",
    "live",
    "execution",
    "order_submission",
)
OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_NON_OPERATIONAL_DECLARATION = (
    "This authorization is research-only and does not authorize replay, backtest, walk-forward, "
    "performance, ranking, paper trading, live trading, execution, or order submission."
)


class OfflineResearchExperimentAuthorizationError(HistoricalDataError):
    pass


class OfflineResearchExperimentAuthorizationValidationError(
    OfflineResearchExperimentAuthorizationError, HistoricalDataValidationError
):
    pass


class OfflineResearchExperimentAuthorizationIntegrityError(
    OfflineResearchExperimentAuthorizationError, HistoricalDataIntegrityError
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineResearchExperimentAuthorizationValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchExperimentAuthorizationValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineResearchExperimentAuthorizationValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineResearchExperimentAuthorizationValidationError(f"{field_name} must be a boolean.")
    return value


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineResearchExperimentAuthorizationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise OfflineResearchExperimentAuthorizationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise OfflineResearchExperimentAuthorizationValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineResearchExperimentAuthorizationValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _normalize_use_cases(value: Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_ALLOWED_USE_CASES
    normalized = []
    for item in value:
        use_case = _require_str(item, "allowed_use_case").lower()
        normalized.append(use_case)
    unique = tuple(dict.fromkeys(normalized))
    if any(use_case in OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PROHIBITED_USE_CASES for use_case in unique):
        raise OfflineResearchExperimentAuthorizationValidationError(
            "authorization cannot include prohibited operational use cases."
        )
    invalid = sorted(
        use_case
        for use_case in unique
        if use_case not in OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_ALLOWED_USE_CASES
    )
    if invalid:
        raise OfflineResearchExperimentAuthorizationValidationError(
            "authorization may only contain experiment_contract_validation or remain empty."
        )
    return unique


def _assert_verified_report(report: ResearchArtifactRegistryVerificationReport) -> None:
    if not isinstance(report, ResearchArtifactRegistryVerificationReport):
        raise OfflineResearchExperimentAuthorizationValidationError(
            "a verified research artifact registry report is required."
        )
    if report.approved is not True:
        raise OfflineResearchExperimentAuthorizationValidationError("verification report must be approved.")
    if report.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchExperimentAuthorizationValidationError("provider_name must be OKX.")
    if report.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchExperimentAuthorizationValidationError("market_type must be spot.")
    if report.instrument != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchExperimentAuthorizationValidationError("instrument must be BTC-USDT.")
    if report.symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchExperimentAuthorizationValidationError("symbol must be BTCUSDT.")
    if report.interval != OKX_RESEARCH_ARTIFACT_INTERVAL:
        raise OfflineResearchExperimentAuthorizationValidationError("interval must be 1H.")
    if report.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchExperimentAuthorizationIntegrityError(
            "requested_start_inclusive_utc diverges from the OKX research artifact contract."
        )
    if report.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise OfflineResearchExperimentAuthorizationIntegrityError(
            "requested_end_exclusive_utc diverges from the OKX research artifact contract."
        )
    if report.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchExperimentAuthorizationIntegrityError("expected_candle_count must be 42816.")
    if report.audited_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchExperimentAuthorizationIntegrityError("audited_candle_count must be 42816.")
    if report.audit_status != OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED:
        raise OfflineResearchExperimentAuthorizationValidationError("audit_status must be passed.")
    if report.historical_research_only is not True:
        raise OfflineResearchExperimentAuthorizationValidationError("historical_research_only must be true.")
    if report.operational_evidence is not False:
        raise OfflineResearchExperimentAuthorizationValidationError("operational_evidence must be false.")
    if report.paper_promotion_eligible is not False:
        raise OfflineResearchExperimentAuthorizationValidationError("paper_promotion_eligible must be false.")
    if report.external_artifact_ref_is_opaque is not True:
        raise OfflineResearchExperimentAuthorizationValidationError("external_artifact_ref must be opaque.")
    if report.external_artifact_ref_is_local is not True:
        raise OfflineResearchExperimentAuthorizationValidationError("external_artifact_ref must be local.")
    if report.non_operational_declaration != OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchExperimentAuthorizationValidationError(
            "non_operational_declaration diverges from the OKX research artifact contract."
        )
    if _require_hex_digest(report.dataset_sha256, "dataset_sha256") != OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256:
        raise OfflineResearchExperimentAuthorizationIntegrityError("dataset_sha256 must match the OKX research artifact.")
    if _require_hex_digest(report.manifest_sha256, "manifest_sha256") != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256:
        raise OfflineResearchExperimentAuthorizationIntegrityError("manifest_sha256 must match the OKX research artifact.")
    if _require_hex_digest(report.manifest_hash, "manifest_hash") != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH:
        raise OfflineResearchExperimentAuthorizationIntegrityError("manifest_hash must match the OKX research artifact.")
    if not _require_hex_digest(report.verification_hash, "verification_hash"):
        raise OfflineResearchExperimentAuthorizationIntegrityError("verification_hash must be present.")
    if not report.external_artifact_ref:
        raise OfflineResearchExperimentAuthorizationValidationError("external_artifact_ref is required.")


@dataclass(frozen=True, slots=True)
class OfflineResearchExperimentAuthorization:
    schema_version: int = OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_SCHEMA_VERSION
    authorization_id: str = ""
    issued_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    purpose: str = OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PURPOSE
    artifact_id: str = ""
    provider_name: str = OKX_RESEARCH_ARTIFACT_PROVIDER_NAME
    market_type: str = OKX_RESEARCH_ARTIFACT_MARKET_TYPE
    instrument: str = OKX_RESEARCH_ARTIFACT_INSTRUMENT
    symbol: str = OKX_RESEARCH_ARTIFACT_SYMBOL
    interval: str = OKX_RESEARCH_ARTIFACT_INTERVAL
    requested_start_inclusive_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC
    requested_end_exclusive_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC
    candle_count: int = OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT
    dataset_sha256: str = OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256
    manifest_sha256: str = OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256
    manifest_hash: str = OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH
    verification_registry_file: Path = field(default_factory=Path)
    verification_result_hash: str = ""
    verification_audit_status: str = OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    allowed_use_cases: tuple[str, ...] = field(default_factory=lambda: OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_ALLOWED_USE_CASES)
    prohibited_use_cases: tuple[str, ...] = field(default_factory=lambda: OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PROHIBITED_USE_CASES)
    non_operational_declaration: str = OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_NON_OPERATIONAL_DECLARATION
    authorization_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(
            self,
            "authorization_id",
            _require_hex_digest(self.authorization_id, "authorization_id") if self.authorization_id else "",
        )
        object.__setattr__(self, "issued_at_utc", _require_utc_datetime(self.issued_at_utc, "issued_at_utc"))
        object.__setattr__(self, "purpose", _require_str(self.purpose, "purpose"))
        object.__setattr__(self, "artifact_id", _require_hex_digest(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "provider_name", _require_str(self.provider_name, "provider_name").upper())
        object.__setattr__(self, "market_type", _require_str(self.market_type, "market_type").lower())
        object.__setattr__(self, "instrument", _require_str(self.instrument, "instrument").upper())
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "requested_start_inclusive_utc", _require_utc_datetime(self.requested_start_inclusive_utc, "requested_start_inclusive_utc"))
        object.__setattr__(self, "requested_end_exclusive_utc", _require_utc_datetime(self.requested_end_exclusive_utc, "requested_end_exclusive_utc"))
        object.__setattr__(self, "candle_count", _require_int(self.candle_count, "candle_count"))
        object.__setattr__(self, "dataset_sha256", _require_hex_digest(self.dataset_sha256, "dataset_sha256"))
        object.__setattr__(self, "manifest_sha256", _require_hex_digest(self.manifest_sha256, "manifest_sha256"))
        object.__setattr__(self, "manifest_hash", _require_hex_digest(self.manifest_hash, "manifest_hash"))
        object.__setattr__(self, "verification_registry_file", Path(self.verification_registry_file))
        object.__setattr__(self, "verification_result_hash", _require_hex_digest(self.verification_result_hash, "verification_result_hash"))
        object.__setattr__(self, "verification_audit_status", _require_str(self.verification_audit_status, "verification_audit_status").lower())
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "allowed_use_cases", _normalize_use_cases(self.allowed_use_cases))
        object.__setattr__(
            self,
            "prohibited_use_cases",
            tuple(dict.fromkeys(_require_str(item, "prohibited_use_case").lower() for item in self.prohibited_use_cases)),
        )
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.purpose != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PURPOSE:
            raise OfflineResearchExperimentAuthorizationValidationError(
                "purpose must be offline_historical_research."
            )
        if self.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
            raise OfflineResearchExperimentAuthorizationValidationError("provider_name must be OKX.")
        if self.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
            raise OfflineResearchExperimentAuthorizationValidationError("market_type must be spot.")
        if self.instrument != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
            raise OfflineResearchExperimentAuthorizationValidationError("instrument must be BTC-USDT.")
        if self.symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
            raise OfflineResearchExperimentAuthorizationValidationError("symbol must be BTCUSDT.")
        if self.interval != OKX_RESEARCH_ARTIFACT_INTERVAL:
            raise OfflineResearchExperimentAuthorizationValidationError("interval must be 1H.")
        if self.requested_end_exclusive_utc <= self.requested_start_inclusive_utc:
            raise OfflineResearchExperimentAuthorizationValidationError(
                "requested_end_exclusive_utc must be after requested_start_inclusive_utc."
            )
        if self.candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
            raise OfflineResearchExperimentAuthorizationIntegrityError("candle_count must be 42816.")
        if self.verification_audit_status != OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED:
            raise OfflineResearchExperimentAuthorizationValidationError("verification_audit_status must be passed.")
        if self.historical_research_only is not True:
            raise OfflineResearchExperimentAuthorizationValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchExperimentAuthorizationValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchExperimentAuthorizationValidationError("paper_promotion_eligible must be false.")
        if self.allowed_use_cases and any(
            use_case not in OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_ALLOWED_USE_CASES
            for use_case in self.allowed_use_cases
        ):
            raise OfflineResearchExperimentAuthorizationValidationError(
                "allowed_use_cases may only contain experiment_contract_validation."
            )
        if any(use_case in OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PROHIBITED_USE_CASES for use_case in self.allowed_use_cases):
            raise OfflineResearchExperimentAuthorizationValidationError(
                "allowed_use_cases cannot contain prohibited operational use cases."
            )
        if any(use_case in self.allowed_use_cases for use_case in self.prohibited_use_cases):
            raise OfflineResearchExperimentAuthorizationValidationError(
                "allowed_use_cases and prohibited_use_cases must not overlap."
            )
        if self.prohibited_use_cases != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PROHIBITED_USE_CASES:
            raise OfflineResearchExperimentAuthorizationValidationError(
                "prohibited_use_cases must match the offline research experiment contract."
            )

        authorization_id_payload = self._authorization_id_payload()
        expected_authorization_id = _hash_payload(authorization_id_payload)
        if self.authorization_id:
            if self.authorization_id != expected_authorization_id:
                raise OfflineResearchExperimentAuthorizationIntegrityError("authorization_id mismatch.")
        else:
            object.__setattr__(self, "authorization_id", expected_authorization_id)

        expected_authorization_hash = _hash_payload(self.canonical_payload(include_authorization_hash=False))
        if self.authorization_hash:
            if self.authorization_hash != expected_authorization_hash:
                raise OfflineResearchExperimentAuthorizationIntegrityError("authorization_hash mismatch.")
        else:
            object.__setattr__(self, "authorization_hash", expected_authorization_hash)

    def _authorization_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "issued_at_utc": _utc_iso(self.issued_at_utc),
            "purpose": self.purpose,
            "artifact_id": self.artifact_id,
            "provider_name": self.provider_name,
            "market_type": self.market_type,
            "instrument": self.instrument,
            "symbol": self.symbol,
            "interval": self.interval,
            "requested_start_inclusive_utc": _utc_iso(self.requested_start_inclusive_utc),
            "requested_end_exclusive_utc": _utc_iso(self.requested_end_exclusive_utc),
            "candle_count": self.candle_count,
            "dataset_sha256": self.dataset_sha256,
            "manifest_sha256": self.manifest_sha256,
            "manifest_hash": self.manifest_hash,
            "verification_registry_file": str(self.verification_registry_file),
            "verification_result_hash": self.verification_result_hash,
            "verification_audit_status": self.verification_audit_status,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "allowed_use_cases": self.allowed_use_cases,
            "prohibited_use_cases": self.prohibited_use_cases,
            "non_operational_declaration": self.non_operational_declaration,
        }

    def canonical_payload(self, *, include_authorization_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "authorization_id": self.authorization_id,
            "issued_at_utc": _utc_iso(self.issued_at_utc),
            "purpose": self.purpose,
            "artifact_id": self.artifact_id,
            "provider_name": self.provider_name,
            "market_type": self.market_type,
            "instrument": self.instrument,
            "symbol": self.symbol,
            "interval": self.interval,
            "requested_start_inclusive_utc": _utc_iso(self.requested_start_inclusive_utc),
            "requested_end_exclusive_utc": _utc_iso(self.requested_end_exclusive_utc),
            "candle_count": self.candle_count,
            "dataset_sha256": self.dataset_sha256,
            "manifest_sha256": self.manifest_sha256,
            "manifest_hash": self.manifest_hash,
            "verification_registry_file": str(self.verification_registry_file),
            "verification_result_hash": self.verification_result_hash,
            "verification_audit_status": self.verification_audit_status,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "allowed_use_cases": self.allowed_use_cases,
            "prohibited_use_cases": self.prohibited_use_cases,
            "non_operational_declaration": self.non_operational_declaration,
        }
        if include_authorization_hash:
            payload["authorization_hash"] = self.authorization_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_authorization_hash=True))


def authorize_offline_research_experiment(
    verification_report: ResearchArtifactRegistryVerificationReport,
    *,
    issued_at_utc: datetime | None = None,
    allowed_use_cases: Sequence[str] | None = None,
) -> OfflineResearchExperimentAuthorization:
    _assert_verified_report(verification_report)
    authorization = OfflineResearchExperimentAuthorization(
        issued_at_utc=issued_at_utc or verification_report.verified_at_utc,
        artifact_id=verification_report.artifact_id,
        provider_name=verification_report.provider_name,
        market_type=verification_report.market_type,
        instrument=verification_report.instrument,
        symbol=verification_report.symbol,
        interval=verification_report.interval,
        requested_start_inclusive_utc=verification_report.requested_start_inclusive_utc,
        requested_end_exclusive_utc=verification_report.requested_end_exclusive_utc,
        candle_count=verification_report.expected_candle_count,
        dataset_sha256=verification_report.dataset_sha256,
        manifest_sha256=verification_report.manifest_sha256,
        manifest_hash=verification_report.manifest_hash,
        verification_registry_file=verification_report.registry_file,
        verification_result_hash=verification_report.verification_hash,
        verification_audit_status=verification_report.audit_status,
        historical_research_only=verification_report.historical_research_only,
        operational_evidence=verification_report.operational_evidence,
        paper_promotion_eligible=verification_report.paper_promotion_eligible,
        allowed_use_cases=tuple(allowed_use_cases) if allowed_use_cases is not None else OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_ALLOWED_USE_CASES,
        prohibited_use_cases=OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PROHIBITED_USE_CASES,
        non_operational_declaration=OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_NON_OPERATIONAL_DECLARATION,
    )
    if authorization.as_dict() != serialize_value(authorization.canonical_payload()):
        raise OfflineResearchExperimentAuthorizationIntegrityError("authorization payload mismatch.")
    return authorization
