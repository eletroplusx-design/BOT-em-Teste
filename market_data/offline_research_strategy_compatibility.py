from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value

from .errors import HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError
from .offline_research_experiment_authorization import (
    OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_ALLOWED_USE_CASES,
    OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_NON_OPERATIONAL_DECLARATION,
    OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PROHIBITED_USE_CASES,
    OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PURPOSE,
    OfflineResearchExperimentAuthorization,
)
from .research_artifact_registry import (
    OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED,
    OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT,
    OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256,
    OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH,
    OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256,
    OKX_RESEARCH_ARTIFACT_INSTRUMENT,
    OKX_RESEARCH_ARTIFACT_MARKET_TYPE,
    OKX_RESEARCH_ARTIFACT_PROVIDER_NAME,
    OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC,
    OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC,
    OKX_RESEARCH_ARTIFACT_SYMBOL,
)
from .research_artifact_registry_verification import ResearchArtifactRegistryVerificationReport

OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_SCHEMA_VERSION = 1
OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_STATUS_COMPATIBLE_FOR_FUTURE_OFFLINE_RESEARCH = (
    "compatible_for_future_offline_research"
)
OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PURPOSE = OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PURPOSE
OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES: tuple[str, ...] = (
    "experiment_contract_validation",
)
OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES: tuple[str, ...] = (
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
OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION = (
    "This compatibility decision is research-only and does not authorize replay, backtest, walk-forward, "
    "performance, ranking, paper trading, live trading, execution, or order submission."
)


class OfflineResearchStrategyCompatibilityError(HistoricalDataError):
    pass


class OfflineResearchStrategyCompatibilityValidationError(
    OfflineResearchStrategyCompatibilityError, HistoricalDataValidationError
):
    pass


class OfflineResearchStrategyCompatibilityIntegrityError(
    OfflineResearchStrategyCompatibilityError, HistoricalDataIntegrityError
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineResearchStrategyCompatibilityValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchStrategyCompatibilityValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineResearchStrategyCompatibilityValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineResearchStrategyCompatibilityValidationError(f"{field_name} must be a boolean.")
    return value


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineResearchStrategyCompatibilityValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise OfflineResearchStrategyCompatibilityValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise OfflineResearchStrategyCompatibilityValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineResearchStrategyCompatibilityValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _normalize_use_cases(value: Sequence[str] | None) -> tuple[str, ...]:
    if value is None:
        return OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES
    normalized = tuple(dict.fromkeys(_require_str(item, "allowed_use_case").lower() for item in value))
    if any(use_case in OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES for use_case in normalized):
        raise OfflineResearchStrategyCompatibilityValidationError(
            "strategy contract cannot include prohibited operational use cases."
        )
    invalid = sorted(
        use_case
        for use_case in normalized
        if use_case not in OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES
    )
    if invalid:
        raise OfflineResearchStrategyCompatibilityValidationError(
            "strategy contract may only contain experiment_contract_validation or remain empty."
        )
    return normalized


def _require_authorization(
    authorization: OfflineResearchExperimentAuthorization,
) -> OfflineResearchExperimentAuthorization:
    if not isinstance(authorization, OfflineResearchExperimentAuthorization):
        raise OfflineResearchStrategyCompatibilityValidationError(
            "a verified offline research experiment authorization is required."
        )
    if authorization.purpose != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PURPOSE:
        raise OfflineResearchStrategyCompatibilityValidationError(
            "authorization purpose must be offline_historical_research."
        )
    if authorization.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchStrategyCompatibilityValidationError("authorization provider_name must be OKX.")
    if authorization.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchStrategyCompatibilityValidationError("authorization market_type must be spot.")
    if authorization.instrument != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchStrategyCompatibilityValidationError("authorization instrument must be BTC-USDT.")
    if authorization.symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchStrategyCompatibilityValidationError("authorization symbol must be BTCUSDT.")
    if authorization.interval != "1H":
        raise OfflineResearchStrategyCompatibilityValidationError("authorization interval must be 1H.")
    if authorization.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchStrategyCompatibilityIntegrityError(
            "authorization requested_start_inclusive_utc diverges from the OKX research artifact contract."
        )
    if authorization.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise OfflineResearchStrategyCompatibilityIntegrityError(
            "authorization requested_end_exclusive_utc diverges from the OKX research artifact contract."
        )
    if authorization.candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchStrategyCompatibilityIntegrityError("authorization candle_count must be 42816.")
    if authorization.dataset_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256:
        raise OfflineResearchStrategyCompatibilityIntegrityError("authorization dataset_sha256 mismatch.")
    if authorization.manifest_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256:
        raise OfflineResearchStrategyCompatibilityIntegrityError("authorization manifest_sha256 mismatch.")
    if authorization.manifest_hash != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH:
        raise OfflineResearchStrategyCompatibilityIntegrityError("authorization manifest_hash mismatch.")
    if authorization.verification_audit_status != OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED:
        raise OfflineResearchStrategyCompatibilityValidationError("authorization verification_audit_status must be passed.")
    if authorization.historical_research_only is not True:
        raise OfflineResearchStrategyCompatibilityValidationError("historical_research_only must be true.")
    if authorization.operational_evidence is not False:
        raise OfflineResearchStrategyCompatibilityValidationError("operational_evidence must be false.")
    if authorization.paper_promotion_eligible is not False:
        raise OfflineResearchStrategyCompatibilityValidationError("paper_promotion_eligible must be false.")
    if authorization.allowed_use_cases != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES:
        raise OfflineResearchStrategyCompatibilityValidationError(
            "authorization allowed_use_cases must remain limited to experiment_contract_validation."
        )
    if authorization.prohibited_use_cases != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES:
        raise OfflineResearchStrategyCompatibilityValidationError(
            "authorization prohibited_use_cases must remain fixed for research-only compatibility."
        )
    if authorization.non_operational_declaration != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchStrategyCompatibilityValidationError(
            "authorization non_operational_declaration diverges from the OKX research artifact contract."
        )
    if not authorization.verification_result_hash:
        raise OfflineResearchStrategyCompatibilityIntegrityError("authorization verification_result_hash is required.")
    return authorization


def _require_verification_report(
    verification_report: ResearchArtifactRegistryVerificationReport,
) -> ResearchArtifactRegistryVerificationReport:
    if not isinstance(verification_report, ResearchArtifactRegistryVerificationReport):
        raise OfflineResearchStrategyCompatibilityValidationError(
            "a verified research artifact registry report is required."
        )
    if verification_report.approved is not True:
        raise OfflineResearchStrategyCompatibilityValidationError("verification report must be approved.")
    if verification_report.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchStrategyCompatibilityValidationError("verification report provider_name must be OKX.")
    if verification_report.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchStrategyCompatibilityValidationError("verification report market_type must be spot.")
    if verification_report.instrument != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchStrategyCompatibilityValidationError("verification report instrument must be BTC-USDT.")
    if verification_report.symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchStrategyCompatibilityValidationError("verification report symbol must be BTCUSDT.")
    if verification_report.interval != "1H":
        raise OfflineResearchStrategyCompatibilityValidationError("verification report interval must be 1H.")
    if verification_report.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchStrategyCompatibilityIntegrityError(
            "verification report requested_start_inclusive_utc diverges from the OKX research artifact contract."
        )
    if verification_report.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise OfflineResearchStrategyCompatibilityIntegrityError(
            "verification report requested_end_exclusive_utc diverges from the OKX research artifact contract."
        )
    if verification_report.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchStrategyCompatibilityIntegrityError("verification report expected_candle_count must be 42816.")
    if verification_report.audited_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchStrategyCompatibilityIntegrityError("verification report audited_candle_count must be 42816.")
    if verification_report.audit_status != OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED:
        raise OfflineResearchStrategyCompatibilityValidationError("verification report audit_status must be passed.")
    if verification_report.historical_research_only is not True:
        raise OfflineResearchStrategyCompatibilityValidationError("historical_research_only must be true.")
    if verification_report.operational_evidence is not False:
        raise OfflineResearchStrategyCompatibilityValidationError("operational_evidence must be false.")
    if verification_report.paper_promotion_eligible is not False:
        raise OfflineResearchStrategyCompatibilityValidationError("paper_promotion_eligible must be false.")
    if verification_report.non_operational_declaration != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchStrategyCompatibilityValidationError(
            "verification report non_operational_declaration diverges from the OKX research artifact contract."
        )
    if not verification_report.verification_hash:
        raise OfflineResearchStrategyCompatibilityIntegrityError("verification report verification_hash is required.")
    return verification_report


@dataclass(frozen=True, slots=True)
class OfflineResearchStrategyCompatibilityContract:
    strategy_id: str
    strategy_version: str
    provider_name: str = OKX_RESEARCH_ARTIFACT_PROVIDER_NAME
    market_type: str = OKX_RESEARCH_ARTIFACT_MARKET_TYPE
    symbol: str = OKX_RESEARCH_ARTIFACT_INSTRUMENT
    canonical_symbol: str = OKX_RESEARCH_ARTIFACT_SYMBOL
    interval: str = "1H"
    requested_start_inclusive_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC
    requested_end_exclusive_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC
    expected_candle_count: int = OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT
    required_dataset_sha256: str = OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256
    required_manifest_sha256: str = OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256
    required_manifest_hash: str = OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH
    required_verification_hash: str = ""
    purpose: str = OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PURPOSE
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    allowed_use_cases: tuple[str, ...] = field(
        default_factory=lambda: OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES
    )
    prohibited_use_cases: tuple[str, ...] = field(
        default_factory=lambda: OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES
    )
    non_operational_declaration: str = OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION
    compatibility_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_id", _require_str(self.strategy_id, "strategy_id"))
        object.__setattr__(self, "strategy_version", _require_str(self.strategy_version, "strategy_version"))
        object.__setattr__(self, "provider_name", _require_str(self.provider_name, "provider_name").upper())
        object.__setattr__(self, "market_type", _require_str(self.market_type, "market_type").lower())
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "canonical_symbol", _require_str(self.canonical_symbol, "canonical_symbol").upper())
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "requested_start_inclusive_utc", _require_utc_datetime(self.requested_start_inclusive_utc, "requested_start_inclusive_utc"))
        object.__setattr__(self, "requested_end_exclusive_utc", _require_utc_datetime(self.requested_end_exclusive_utc, "requested_end_exclusive_utc"))
        object.__setattr__(self, "expected_candle_count", _require_int(self.expected_candle_count, "expected_candle_count"))
        object.__setattr__(self, "required_dataset_sha256", _require_hex_digest(self.required_dataset_sha256, "required_dataset_sha256"))
        object.__setattr__(self, "required_manifest_sha256", _require_hex_digest(self.required_manifest_sha256, "required_manifest_sha256"))
        object.__setattr__(self, "required_manifest_hash", _require_hex_digest(self.required_manifest_hash, "required_manifest_hash"))
        object.__setattr__(self, "required_verification_hash", _require_hex_digest(self.required_verification_hash, "required_verification_hash"))
        object.__setattr__(self, "purpose", _require_str(self.purpose, "purpose"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "allowed_use_cases", _normalize_use_cases(self.allowed_use_cases))
        object.__setattr__(
            self,
            "prohibited_use_cases",
            tuple(dict.fromkeys(_require_str(item, "prohibited_use_case").lower() for item in self.prohibited_use_cases)),
        )
        object.__setattr__(
            self,
            "non_operational_declaration",
            _require_str(self.non_operational_declaration, "non_operational_declaration"),
        )
        if self.purpose != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PURPOSE:
            raise OfflineResearchStrategyCompatibilityValidationError(
                "purpose must be offline_historical_research."
            )
        if self.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
            raise OfflineResearchStrategyCompatibilityValidationError("provider_name must be OKX.")
        if self.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
            raise OfflineResearchStrategyCompatibilityValidationError("market_type must be spot.")
        if self.interval != "1H":
            raise OfflineResearchStrategyCompatibilityValidationError("interval must be 1H.")
        if self.requested_end_exclusive_utc <= self.requested_start_inclusive_utc:
            raise OfflineResearchStrategyCompatibilityValidationError(
                "requested_end_exclusive_utc must be after requested_start_inclusive_utc."
            )
        if self.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
            raise OfflineResearchStrategyCompatibilityIntegrityError("expected_candle_count must be 42816.")
        if self.historical_research_only is not True:
            raise OfflineResearchStrategyCompatibilityValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchStrategyCompatibilityValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchStrategyCompatibilityValidationError("paper_promotion_eligible must be false.")
        if self.allowed_use_cases and any(
            use_case not in OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES
            for use_case in self.allowed_use_cases
        ):
            raise OfflineResearchStrategyCompatibilityValidationError(
                "allowed_use_cases may only contain experiment_contract_validation."
            )
        if any(use_case in OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES for use_case in self.allowed_use_cases):
            raise OfflineResearchStrategyCompatibilityValidationError(
                "allowed_use_cases cannot contain prohibited operational use cases."
            )
        if any(use_case in self.allowed_use_cases for use_case in self.prohibited_use_cases):
            raise OfflineResearchStrategyCompatibilityValidationError(
                "allowed_use_cases and prohibited_use_cases must not overlap."
            )
        if self.prohibited_use_cases != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES:
            raise OfflineResearchStrategyCompatibilityValidationError(
                "prohibited_use_cases must match the offline research strategy compatibility contract."
            )
        if self.non_operational_declaration != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchStrategyCompatibilityValidationError(
                "non_operational_declaration diverges from the offline compatibility contract."
            )
        expected_compatibility_hash = _hash_payload(self.canonical_payload(include_compatibility_hash=False))
        if self.compatibility_hash:
            if self.compatibility_hash != expected_compatibility_hash:
                raise OfflineResearchStrategyCompatibilityIntegrityError("compatibility_hash mismatch.")
        else:
            object.__setattr__(self, "compatibility_hash", expected_compatibility_hash)

    def canonical_payload(self, *, include_compatibility_hash: bool = True) -> dict[str, Any]:
        payload = {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "provider_name": self.provider_name,
            "market_type": self.market_type,
            "symbol": self.symbol,
            "canonical_symbol": self.canonical_symbol,
            "interval": self.interval,
            "requested_start_inclusive_utc": _utc_iso(self.requested_start_inclusive_utc),
            "requested_end_exclusive_utc": _utc_iso(self.requested_end_exclusive_utc),
            "expected_candle_count": self.expected_candle_count,
            "required_dataset_sha256": self.required_dataset_sha256,
            "required_manifest_sha256": self.required_manifest_sha256,
            "required_manifest_hash": self.required_manifest_hash,
            "required_verification_hash": self.required_verification_hash,
            "purpose": self.purpose,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "allowed_use_cases": self.allowed_use_cases,
            "prohibited_use_cases": self.prohibited_use_cases,
            "non_operational_declaration": self.non_operational_declaration,
        }
        if include_compatibility_hash:
            payload["compatibility_hash"] = self.compatibility_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_compatibility_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfflineResearchStrategyCompatibilityContract":
        if not isinstance(data, Mapping):
            raise OfflineResearchStrategyCompatibilityValidationError(
                "offline research strategy compatibility contract must be a mapping."
            )
        mapping = dict(data)
        allowed = {
            "strategy_id",
            "strategy_version",
            "provider_name",
            "market_type",
            "symbol",
            "canonical_symbol",
            "interval",
            "requested_start_inclusive_utc",
            "requested_end_exclusive_utc",
            "expected_candle_count",
            "required_dataset_sha256",
            "required_manifest_sha256",
            "required_manifest_hash",
            "required_verification_hash",
            "purpose",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "allowed_use_cases",
            "prohibited_use_cases",
            "non_operational_declaration",
            "compatibility_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise OfflineResearchStrategyCompatibilityValidationError(
                f"unexpected compatibility contract fields: {', '.join(extra)}."
            )
        try:
            return cls(
                strategy_id=mapping["strategy_id"],
                strategy_version=mapping["strategy_version"],
                provider_name=mapping.get("provider_name", OKX_RESEARCH_ARTIFACT_PROVIDER_NAME),
                market_type=mapping.get("market_type", OKX_RESEARCH_ARTIFACT_MARKET_TYPE),
                symbol=mapping.get("symbol", OKX_RESEARCH_ARTIFACT_INSTRUMENT),
                canonical_symbol=mapping.get("canonical_symbol", OKX_RESEARCH_ARTIFACT_SYMBOL),
                interval=mapping.get("interval", "1H"),
                requested_start_inclusive_utc=mapping.get(
                    "requested_start_inclusive_utc", OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC
                ),
                requested_end_exclusive_utc=mapping.get(
                    "requested_end_exclusive_utc", OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC
                ),
                expected_candle_count=mapping.get(
                    "expected_candle_count", OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT
                ),
                required_dataset_sha256=mapping.get(
                    "required_dataset_sha256", OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256
                ),
                required_manifest_sha256=mapping.get(
                    "required_manifest_sha256", OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256
                ),
                required_manifest_hash=mapping.get(
                    "required_manifest_hash", OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH
                ),
                required_verification_hash=mapping["required_verification_hash"],
                purpose=mapping.get("purpose", OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PURPOSE),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                allowed_use_cases=mapping.get("allowed_use_cases", OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES),
                prohibited_use_cases=mapping.get(
                    "prohibited_use_cases", OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES
                ),
                non_operational_declaration=mapping.get(
                    "non_operational_declaration",
                    OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION,
                ),
                compatibility_hash=mapping.get("compatibility_hash", ""),
            )
        except KeyError as exc:
            raise OfflineResearchStrategyCompatibilityValidationError(
                "offline research strategy compatibility contract is incomplete."
            ) from exc


@dataclass(frozen=True, slots=True)
class OfflineResearchStrategyCompatibilityDecision:
    schema_version: int = OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_SCHEMA_VERSION
    strategy_id: str = ""
    strategy_version: str = ""
    decision_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_STATUS_COMPATIBLE_FOR_FUTURE_OFFLINE_RESEARCH
    authorization_id: str = ""
    authorization_hash: str = ""
    strategy_contract_hash: str = ""
    compatibility_hash: str = ""
    provider_name: str = OKX_RESEARCH_ARTIFACT_PROVIDER_NAME
    market_type: str = OKX_RESEARCH_ARTIFACT_MARKET_TYPE
    symbol: str = OKX_RESEARCH_ARTIFACT_INSTRUMENT
    canonical_symbol: str = OKX_RESEARCH_ARTIFACT_SYMBOL
    interval: str = "1H"
    requested_start_inclusive_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC
    requested_end_exclusive_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC
    expected_candle_count: int = OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT
    required_dataset_sha256: str = OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256
    required_manifest_sha256: str = OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256
    required_manifest_hash: str = OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH
    required_verification_hash: str = ""
    purpose: str = OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PURPOSE
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    allowed_use_cases: tuple[str, ...] = field(default_factory=lambda: OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES)
    prohibited_use_cases: tuple[str, ...] = field(default_factory=lambda: OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES)
    non_operational_declaration: str = OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "strategy_id", _require_str(self.strategy_id, "strategy_id"))
        object.__setattr__(self, "strategy_version", _require_str(self.strategy_version, "strategy_version"))
        object.__setattr__(self, "decision_at_utc", _require_utc_datetime(self.decision_at_utc, "decision_at_utc"))
        object.__setattr__(self, "status", _require_str(self.status, "status"))
        object.__setattr__(self, "authorization_id", _require_hex_digest(self.authorization_id, "authorization_id"))
        object.__setattr__(self, "authorization_hash", _require_hex_digest(self.authorization_hash, "authorization_hash"))
        object.__setattr__(self, "strategy_contract_hash", _require_hex_digest(self.strategy_contract_hash, "strategy_contract_hash"))
        object.__setattr__(self, "provider_name", _require_str(self.provider_name, "provider_name").upper())
        object.__setattr__(self, "market_type", _require_str(self.market_type, "market_type").lower())
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "canonical_symbol", _require_str(self.canonical_symbol, "canonical_symbol").upper())
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "requested_start_inclusive_utc", _require_utc_datetime(self.requested_start_inclusive_utc, "requested_start_inclusive_utc"))
        object.__setattr__(self, "requested_end_exclusive_utc", _require_utc_datetime(self.requested_end_exclusive_utc, "requested_end_exclusive_utc"))
        object.__setattr__(self, "expected_candle_count", _require_int(self.expected_candle_count, "expected_candle_count"))
        object.__setattr__(self, "required_dataset_sha256", _require_hex_digest(self.required_dataset_sha256, "required_dataset_sha256"))
        object.__setattr__(self, "required_manifest_sha256", _require_hex_digest(self.required_manifest_sha256, "required_manifest_sha256"))
        object.__setattr__(self, "required_manifest_hash", _require_hex_digest(self.required_manifest_hash, "required_manifest_hash"))
        object.__setattr__(self, "required_verification_hash", _require_hex_digest(self.required_verification_hash, "required_verification_hash"))
        object.__setattr__(self, "purpose", _require_str(self.purpose, "purpose"))
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
        if self.status != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_STATUS_COMPATIBLE_FOR_FUTURE_OFFLINE_RESEARCH:
            raise OfflineResearchStrategyCompatibilityValidationError(
                "status must be compatible_for_future_offline_research."
            )
        if self.purpose != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PURPOSE:
            raise OfflineResearchStrategyCompatibilityValidationError(
                "purpose must be offline_historical_research."
            )
        if self.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
            raise OfflineResearchStrategyCompatibilityValidationError("provider_name must be OKX.")
        if self.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
            raise OfflineResearchStrategyCompatibilityValidationError("market_type must be spot.")
        if self.symbol != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
            raise OfflineResearchStrategyCompatibilityValidationError("symbol must be BTC-USDT.")
        if self.canonical_symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
            raise OfflineResearchStrategyCompatibilityValidationError("canonical_symbol must be BTCUSDT.")
        if self.interval != "1H":
            raise OfflineResearchStrategyCompatibilityValidationError("interval must be 1H.")
        if self.requested_end_exclusive_utc <= self.requested_start_inclusive_utc:
            raise OfflineResearchStrategyCompatibilityValidationError(
                "requested_end_exclusive_utc must be after requested_start_inclusive_utc."
            )
        if self.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
            raise OfflineResearchStrategyCompatibilityIntegrityError("expected_candle_count must be 42816.")
        if self.historical_research_only is not True:
            raise OfflineResearchStrategyCompatibilityValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchStrategyCompatibilityValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchStrategyCompatibilityValidationError("paper_promotion_eligible must be false.")
        if self.allowed_use_cases != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES:
            raise OfflineResearchStrategyCompatibilityValidationError(
                "allowed_use_cases must remain limited to experiment_contract_validation."
            )
        if self.prohibited_use_cases != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES:
            raise OfflineResearchStrategyCompatibilityValidationError(
                "prohibited_use_cases must match the offline research strategy compatibility contract."
            )
        expected_hash = _hash_payload(self.canonical_payload(include_compatibility_hash=False))
        if self.compatibility_hash:
            if self.compatibility_hash != expected_hash:
                raise OfflineResearchStrategyCompatibilityIntegrityError("compatibility_hash mismatch.")
        else:
            object.__setattr__(self, "compatibility_hash", expected_hash)

    def canonical_payload(self, *, include_compatibility_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "decision_at_utc": _utc_iso(self.decision_at_utc),
            "status": self.status,
            "authorization_id": self.authorization_id,
            "authorization_hash": self.authorization_hash,
            "strategy_contract_hash": self.strategy_contract_hash,
            "provider_name": self.provider_name,
            "market_type": self.market_type,
            "symbol": self.symbol,
            "canonical_symbol": self.canonical_symbol,
            "interval": self.interval,
            "requested_start_inclusive_utc": _utc_iso(self.requested_start_inclusive_utc),
            "requested_end_exclusive_utc": _utc_iso(self.requested_end_exclusive_utc),
            "expected_candle_count": self.expected_candle_count,
            "required_dataset_sha256": self.required_dataset_sha256,
            "required_manifest_sha256": self.required_manifest_sha256,
            "required_manifest_hash": self.required_manifest_hash,
            "required_verification_hash": self.required_verification_hash,
            "purpose": self.purpose,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "allowed_use_cases": self.allowed_use_cases,
            "prohibited_use_cases": self.prohibited_use_cases,
            "non_operational_declaration": self.non_operational_declaration,
            "rejection_reason": self.rejection_reason,
        }
        if include_compatibility_hash:
            payload["compatibility_hash"] = self.compatibility_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_compatibility_hash=True))


def evaluate_offline_research_strategy_compatibility(
    authorization: OfflineResearchExperimentAuthorization,
    strategy_contract: OfflineResearchStrategyCompatibilityContract,
    *,
    decided_at_utc: datetime | None = None,
) -> OfflineResearchStrategyCompatibilityDecision:
    authorization = _require_authorization(authorization)
    if not isinstance(strategy_contract, OfflineResearchStrategyCompatibilityContract):
        raise OfflineResearchStrategyCompatibilityValidationError(
            "offline research strategy compatibility contract is required."
        )
    decided_at = _require_utc_datetime(decided_at_utc or authorization.issued_at_utc, "decided_at_utc")
    contract = strategy_contract
    if contract.provider_name != authorization.provider_name:
        raise OfflineResearchStrategyCompatibilityValidationError("provider_name diverges from the authorized artifact.")
    if contract.market_type != authorization.market_type:
        raise OfflineResearchStrategyCompatibilityValidationError("market_type diverges from the authorized artifact.")
    if contract.symbol != authorization.instrument:
        raise OfflineResearchStrategyCompatibilityValidationError("symbol diverges from the authorized artifact instrument.")
    if contract.canonical_symbol != authorization.symbol:
        raise OfflineResearchStrategyCompatibilityValidationError(
            "canonical_symbol diverges from the authorized artifact symbol."
        )
    if contract.interval != authorization.interval:
        raise OfflineResearchStrategyCompatibilityValidationError("interval diverges from the authorized artifact.")
    if contract.requested_start_inclusive_utc != authorization.requested_start_inclusive_utc:
        raise OfflineResearchStrategyCompatibilityIntegrityError(
            "requested_start_inclusive_utc diverges from the authorized artifact."
        )
    if contract.requested_end_exclusive_utc != authorization.requested_end_exclusive_utc:
        raise OfflineResearchStrategyCompatibilityIntegrityError(
            "requested_end_exclusive_utc diverges from the authorized artifact."
        )
    if contract.expected_candle_count != authorization.candle_count:
        raise OfflineResearchStrategyCompatibilityIntegrityError("expected_candle_count diverges from the authorized artifact.")
    if contract.required_dataset_sha256 != authorization.dataset_sha256:
        raise OfflineResearchStrategyCompatibilityIntegrityError("required_dataset_sha256 diverges from the authorized artifact.")
    if contract.required_manifest_sha256 != authorization.manifest_sha256:
        raise OfflineResearchStrategyCompatibilityIntegrityError("required_manifest_sha256 diverges from the authorized artifact.")
    if contract.required_manifest_hash != authorization.manifest_hash:
        raise OfflineResearchStrategyCompatibilityIntegrityError("required_manifest_hash diverges from the authorized artifact.")
    if contract.required_verification_hash != authorization.verification_result_hash:
        raise OfflineResearchStrategyCompatibilityIntegrityError("required_verification_hash diverges from the authorized artifact.")
    if contract.purpose != authorization.purpose:
        raise OfflineResearchStrategyCompatibilityValidationError("purpose must remain offline_historical_research.")
    if contract.historical_research_only is not True or authorization.historical_research_only is not True:
        raise OfflineResearchStrategyCompatibilityValidationError("historical_research_only must remain true.")
    if contract.operational_evidence is not False or authorization.operational_evidence is not False:
        raise OfflineResearchStrategyCompatibilityValidationError("operational_evidence must remain false.")
    if contract.paper_promotion_eligible is not False or authorization.paper_promotion_eligible is not False:
        raise OfflineResearchStrategyCompatibilityValidationError("paper_promotion_eligible must remain false.")
    if contract.allowed_use_cases != authorization.allowed_use_cases:
        raise OfflineResearchStrategyCompatibilityValidationError("allowed_use_cases diverge from the authorization.")
    if contract.prohibited_use_cases != authorization.prohibited_use_cases:
        raise OfflineResearchStrategyCompatibilityValidationError("prohibited_use_cases diverge from the authorization.")
    if contract.allowed_use_cases and any(
        use_case in OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES for use_case in contract.allowed_use_cases
    ):
        raise OfflineResearchStrategyCompatibilityValidationError(
            "strategy contract cannot authorize prohibited operational use cases."
        )
    if any(use_case in contract.allowed_use_cases for use_case in contract.prohibited_use_cases):
        raise OfflineResearchStrategyCompatibilityValidationError(
            "strategy contract allowed_use_cases and prohibited_use_cases must not overlap."
        )
    if contract.non_operational_declaration != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchStrategyCompatibilityValidationError(
            "strategy contract non_operational_declaration diverges from the offline compatibility contract."
        )
    decision = OfflineResearchStrategyCompatibilityDecision(
        strategy_id=contract.strategy_id,
        strategy_version=contract.strategy_version,
        decision_at_utc=decided_at,
        authorization_id=authorization.authorization_id,
        authorization_hash=authorization.authorization_hash,
        strategy_contract_hash=contract.compatibility_hash,
        provider_name=authorization.provider_name,
        market_type=authorization.market_type,
        symbol=authorization.instrument,
        canonical_symbol=authorization.symbol,
        interval=authorization.interval,
        requested_start_inclusive_utc=authorization.requested_start_inclusive_utc,
        requested_end_exclusive_utc=authorization.requested_end_exclusive_utc,
        expected_candle_count=authorization.candle_count,
        required_dataset_sha256=authorization.dataset_sha256,
        required_manifest_sha256=authorization.manifest_sha256,
        required_manifest_hash=authorization.manifest_hash,
        required_verification_hash=authorization.verification_result_hash,
        purpose=authorization.purpose,
        historical_research_only=authorization.historical_research_only,
        operational_evidence=authorization.operational_evidence,
        paper_promotion_eligible=authorization.paper_promotion_eligible,
        allowed_use_cases=authorization.allowed_use_cases,
        prohibited_use_cases=authorization.prohibited_use_cases,
        non_operational_declaration=OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION,
    )
    if decision.as_dict() != serialize_value(decision.canonical_payload()):
        raise OfflineResearchStrategyCompatibilityIntegrityError("compatibility decision payload mismatch.")
    return decision


__all__ = [
    "OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES",
    "OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION",
    "OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES",
    "OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PURPOSE",
    "OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_SCHEMA_VERSION",
    "OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_STATUS_COMPATIBLE_FOR_FUTURE_OFFLINE_RESEARCH",
    "OfflineResearchStrategyCompatibilityContract",
    "OfflineResearchStrategyCompatibilityDecision",
    "OfflineResearchStrategyCompatibilityError",
    "OfflineResearchStrategyCompatibilityIntegrityError",
    "OfflineResearchStrategyCompatibilityValidationError",
    "evaluate_offline_research_strategy_compatibility",
]
