from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value

from .errors import (
    HistoricalDataConflictError,
    HistoricalDataError,
    HistoricalDataIntegrityError,
    HistoricalDataValidationError,
)
from .offline_research_backtest import (
    OkxOfflineResearchArtifactReference,
    OkxPersistentResearchArtifactResolution,
    OfflineResearchBacktestIntegrityError,
    OfflineResearchBacktestValidationError,
    resolve_okx_offline_research_artifact_reference,
)
from .offline_research_experiment_contract import (
    OfflineResearchExperimentContract,
    OfflineResearchExperimentContractIntegrityError,
    OfflineResearchExperimentContractValidationError,
    build_offline_research_experiment_contract,
)
from .research_artifact_registry_verification import ResearchArtifactRegistryVerificationReport
from .research_artifact_registry import OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION
from strategies.baseline_a_okx_btc_usdt_research import BaselineAOkxBtcUsdtResearchContract

OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_SCHEMA_VERSION = 1
OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_ID = "offline_research_experiment_registry"
OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_VERSION = "phase41_offline_experiment_registry_v1"
OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_NON_OPERATIONAL_DECLARATION = (
    "This registry is research-only and does not authorize replay, backtest, walk-forward, performance, "
    "ranking, paper trading, live trading, execution, or order submission."
)
OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_PLACEHOLDER_REGISTRY_FILE = "offline_research_experiment_registry.json"
OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_PLACEHOLDER_DATASET_FILE = "offline_research_experiment_dataset.json"
OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_PLACEHOLDER_MANIFEST_FILE = "offline_research_experiment_manifest.json"


class OfflineResearchExperimentRegistryError(HistoricalDataError):
    pass


class OfflineResearchExperimentRegistryValidationError(
    OfflineResearchExperimentRegistryError, HistoricalDataValidationError
):
    pass


class OfflineResearchExperimentRegistryIntegrityError(
    OfflineResearchExperimentRegistryError, HistoricalDataIntegrityError
):
    pass


class OfflineResearchExperimentRegistryConflictError(
    OfflineResearchExperimentRegistryError, HistoricalDataConflictError
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineResearchExperimentRegistryValidationError(f"{field_name} is required.")
    return value.strip()


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineResearchExperimentRegistryValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineResearchExperimentRegistryValidationError(f"{field_name} must be a boolean.")
    return value


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchExperimentRegistryValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineResearchExperimentRegistryValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise OfflineResearchExperimentRegistryValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise OfflineResearchExperimentRegistryValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineResearchExperimentRegistryValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _is_temporary_pytest_path(path: Path) -> bool:
    return any(part == ".pytest_tmp" for part in path.parts)


def _ensure_registry_path(path: str | Path, *, field_name: str) -> Path:
    registry_path = Path(path)
    if _is_temporary_pytest_path(registry_path):
        raise OfflineResearchExperimentRegistryValidationError(
            f"{field_name} must not point to .pytest_tmp."
        )
    return registry_path


def _freeze_read_only_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_read_only_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_read_only_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_read_only_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_read_only_value(item) for item in value)
    return value


def _thaw_read_only_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_read_only_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_thaw_read_only_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_thaw_read_only_value(item) for item in value)
    if isinstance(value, frozenset):
        thawed_items = [_thaw_read_only_value(item) for item in value]
        return tuple(
            item
            for _, item in sorted(
                (
                    (
                        _canonical_json(_thaw_read_only_value(item)),
                        _thaw_read_only_value(item),
                    )
                    for item in thawed_items
                ),
                key=lambda pair: pair[0],
            )
        )
    return value


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise OfflineResearchExperimentRegistryValidationError("offline research experiment registry is missing.")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise OfflineResearchExperimentRegistryValidationError("offline research experiment registry is empty.")
    try:
        return json.loads(text)
    except Exception as exc:
        raise OfflineResearchExperimentRegistryValidationError(
            "offline research experiment registry is invalid JSON."
        ) from exc


def _contract_snapshot_payload(contract: OfflineResearchExperimentContract) -> dict[str, Any]:
    return _freeze_read_only_value(dict(contract.as_dict()))


def _artifact_reference_snapshot_payload(
    reference_payload: Mapping[str, Any],
    *,
    registered_at_utc: datetime,
) -> dict[str, Any]:
    if not isinstance(reference_payload, Mapping):
        raise OfflineResearchExperimentRegistryValidationError(
            "artifact reference payload must be a mapping."
        )
    registry_report_snapshot = {
        "schema_version": 1,
        "registry_file": OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_PLACEHOLDER_REGISTRY_FILE,
        "verified_at_utc": _utc_iso(registered_at_utc),
        "approved": True,
        "artifact_id": reference_payload["artifact_id"],
        "provider_name": reference_payload["provider_name"],
        "market_type": reference_payload["market_type"],
        "instrument": reference_payload["instrument"],
        "symbol": reference_payload["symbol"],
        "interval": reference_payload["interval"],
        "requested_start_inclusive_utc": reference_payload["requested_start_inclusive_utc"],
        "requested_end_exclusive_utc": reference_payload["requested_end_exclusive_utc"],
        "expected_candle_count": reference_payload["expected_candle_count"],
        "audited_candle_count": reference_payload["expected_candle_count"],
        "dataset_sha256": reference_payload["dataset_sha256"],
        "manifest_sha256": reference_payload["manifest_sha256"],
        "manifest_hash": reference_payload["manifest_hash"],
        "audit_status": reference_payload["audit_status"],
        "external_artifact_ref": "artifact://offline-research-experiment-registry",
        "external_artifact_ref_is_opaque": True,
        "external_artifact_ref_is_local": True,
        "historical_research_only": reference_payload["historical_research_only"],
        "operational_evidence": reference_payload["operational_evidence"],
        "paper_promotion_eligible": reference_payload["paper_promotion_eligible"],
        "non_operational_declaration": OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION,
        "verification_hash": reference_payload["registry_verification_hash"],
    }
    return _freeze_read_only_value(
        {
            "registry_file": OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_PLACEHOLDER_REGISTRY_FILE,
            "dataset_file": OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_PLACEHOLDER_DATASET_FILE,
            "manifest_file": OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_PLACEHOLDER_MANIFEST_FILE,
            "registry_report": registry_report_snapshot,
            "dataset_report": {
                "dataset_hash": reference_payload["dataset_hash"],
                "contract_hash": reference_payload["dataset_contract_hash"],
                "historical_research_only": reference_payload["dataset_historical_research_only"],
                "operational_evidence": reference_payload["dataset_operational_evidence"],
                "paper_promotion_eligible": reference_payload["dataset_paper_promotion_eligible"],
            },
            "read_only": True,
            "historical_research_only": reference_payload["historical_research_only"],
            "operational_evidence": reference_payload["operational_evidence"],
            "paper_promotion_eligible": reference_payload["paper_promotion_eligible"],
            "purpose": "offline_historical_research",
        }
    )


def _build_registry_report(snapshot: Mapping[str, Any]) -> ResearchArtifactRegistryVerificationReport:
    if not isinstance(snapshot, Mapping):
        raise OfflineResearchExperimentRegistryValidationError(
            "artifact reference registry_report snapshot must be a mapping."
        )
    try:
        mapping = dict(snapshot)
        verification_hash = mapping.pop("verification_hash", "")
        report = ResearchArtifactRegistryVerificationReport(**mapping, verification_hash="")
        if verification_hash:
            object.__setattr__(report, "verification_hash", _require_hex_digest(verification_hash, "verification_hash"))
        return report
    except Exception as exc:
        raise OfflineResearchExperimentRegistryValidationError(
            "artifact reference registry_report snapshot is invalid."
        ) from exc


def _build_artifact_reference_from_snapshot(
    snapshot: Mapping[str, Any],
) -> OkxOfflineResearchArtifactReference:
    if not isinstance(snapshot, Mapping):
        raise OfflineResearchExperimentRegistryValidationError(
            "artifact reference snapshot must be a mapping."
        )
    registry_report = _build_registry_report(snapshot["registry_report"])
    resolution = OkxPersistentResearchArtifactResolution(
        registry_file=Path(snapshot["registry_file"]),
        dataset_file=Path(snapshot["dataset_file"]),
        manifest_file=Path(snapshot["manifest_file"]),
        registry_report=registry_report,
        dataset_report=dict(_thaw_read_only_value(snapshot["dataset_report"])),
    )
    return resolve_okx_offline_research_artifact_reference(resolution=resolution)


def _build_strategy_contract_from_snapshot(
    snapshot: Mapping[str, Any],
) -> BaselineAOkxBtcUsdtResearchContract:
    if not isinstance(snapshot, Mapping):
        raise OfflineResearchExperimentRegistryValidationError(
            "strategy contract snapshot must be a mapping."
        )
    try:
        return BaselineAOkxBtcUsdtResearchContract.from_dict(dict(snapshot))
    except Exception as exc:
        raise OfflineResearchExperimentRegistryValidationError(
            "strategy contract snapshot is invalid."
        ) from exc


def _build_contract_from_snapshot(
    contract_snapshot: Mapping[str, Any],
    artifact_reference_snapshot: Mapping[str, Any],
) -> OfflineResearchExperimentContract:
    if not isinstance(contract_snapshot, Mapping):
        raise OfflineResearchExperimentRegistryValidationError("contract snapshot must be a mapping.")
    try:
        artifact_reference = _build_artifact_reference_from_snapshot(artifact_reference_snapshot)
        strategy_contract = _build_strategy_contract_from_snapshot(contract_snapshot["strategy_contract"])
        contract = build_offline_research_experiment_contract(
            artifact_reference=artifact_reference,
            strategy_contract=strategy_contract,
            experiment_id=contract_snapshot["experiment_id"],
            experiment_version=contract_snapshot["experiment_version"],
            created_at_utc=contract_snapshot.get("created_at_utc", datetime.now(timezone.utc)),
            purpose=contract_snapshot.get("purpose", "offline_historical_research"),
            window_start_utc=contract_snapshot["window_start_utc"],
            window_end_utc=contract_snapshot["window_end_utc"],
            symbol=contract_snapshot["symbol"],
            interval=contract_snapshot["interval"],
            entry_fee_rate=contract_snapshot["entry_fee_rate"],
            exit_fee_rate=contract_snapshot["exit_fee_rate"],
            spread_bps=contract_snapshot["spread_bps"],
            slippage_bps=contract_snapshot["slippage_bps"],
            leverage=contract_snapshot["leverage"],
            initial_capital=contract_snapshot["initial_capital"],
            risk_percent=contract_snapshot["risk_percent"],
            extra_parameters=contract_snapshot.get("extra_parameters", {}),
            historical_research_only=contract_snapshot.get("historical_research_only", True),
            operational_evidence=contract_snapshot.get("operational_evidence", False),
            paper_promotion_eligible=contract_snapshot.get("paper_promotion_eligible", False),
            paper_trading_enabled=contract_snapshot.get("paper_trading_enabled", False),
            live_trading_enabled=contract_snapshot.get("live_trading_enabled", False),
            execution_enabled=contract_snapshot.get("execution_enabled", False),
            order_submission_enabled=contract_snapshot.get("order_submission_enabled", False),
            credentials_required=contract_snapshot.get("credentials_required", False),
            exchange_api_enabled=contract_snapshot.get("exchange_api_enabled", False),
            download_enabled=contract_snapshot.get("download_enabled", False),
            ingestion_enabled=contract_snapshot.get("ingestion_enabled", False),
            allowed_use_cases=tuple(contract_snapshot.get("allowed_use_cases", ())),
            prohibited_use_cases=tuple(contract_snapshot.get("prohibited_use_cases", ())),
            non_operational_declaration=contract_snapshot.get("non_operational_declaration", ""),
        )
    except (
        OfflineResearchExperimentContractValidationError,
        OfflineResearchExperimentContractIntegrityError,
        OfflineResearchBacktestValidationError,
        OfflineResearchBacktestIntegrityError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise OfflineResearchExperimentRegistryValidationError(
            "offline research experiment contract snapshot is invalid."
        ) from exc

    if _canonical_json(contract.as_dict()) != _canonical_json(_thaw_read_only_value(contract_snapshot)):
        raise OfflineResearchExperimentRegistryIntegrityError(
            "offline research experiment contract snapshot mismatch."
        )
    return contract


def _record_sort_key(record: "OfflineResearchExperimentRegistryRecord") -> tuple[str, str, str, str]:
    return (
        record.experiment_id,
        record.experiment_fingerprint,
        _utc_iso(record.registered_at_utc),
        record.record_hash,
    )


@dataclass(frozen=True, slots=True)
class OfflineResearchExperimentRegistryRecord:
    schema_version: int = OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_SCHEMA_VERSION
    experiment_id: str = ""
    experiment_version: str = ""
    experiment_fingerprint: str = ""
    registered_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    contract_snapshot: Mapping[str, Any] = field(repr=False, default_factory=dict)
    artifact_reference_snapshot: Mapping[str, Any] = field(repr=False, default_factory=dict)
    record_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "experiment_id", _require_str(self.experiment_id, "experiment_id"))
        object.__setattr__(self, "experiment_version", _require_str(self.experiment_version, "experiment_version"))
        object.__setattr__(self, "experiment_fingerprint", _require_hex_digest(self.experiment_fingerprint, "experiment_fingerprint"))
        object.__setattr__(self, "registered_at_utc", _require_utc_datetime(self.registered_at_utc, "registered_at_utc"))
        object.__setattr__(self, "contract_snapshot", _freeze_read_only_value(dict(self.contract_snapshot)))
        object.__setattr__(self, "artifact_reference_snapshot", _freeze_read_only_value(dict(self.artifact_reference_snapshot)))

        contract = _build_contract_from_snapshot(self.contract_snapshot, self.artifact_reference_snapshot)
        if contract.experiment_id != self.experiment_id:
            raise OfflineResearchExperimentRegistryIntegrityError("experiment_id mismatch.")
        if contract.experiment_version != self.experiment_version:
            raise OfflineResearchExperimentRegistryIntegrityError("experiment_version mismatch.")
        if contract.contract_hash != self.experiment_fingerprint:
            raise OfflineResearchExperimentRegistryIntegrityError("experiment_fingerprint mismatch.")

        expected_hash = _hash_payload(self.canonical_payload(include_record_hash=False))
        if self.record_hash:
            if self.record_hash != expected_hash:
                raise OfflineResearchExperimentRegistryIntegrityError("record_hash mismatch.")
        else:
            object.__setattr__(self, "record_hash", expected_hash)

    @property
    def contract(self) -> OfflineResearchExperimentContract:
        return _build_contract_from_snapshot(self.contract_snapshot, self.artifact_reference_snapshot)

    @property
    def artifact_reference(self) -> OkxOfflineResearchArtifactReference:
        return _build_artifact_reference_from_snapshot(self.artifact_reference_snapshot)

    def canonical_payload(self, *, include_record_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "experiment_version": self.experiment_version,
            "experiment_fingerprint": self.experiment_fingerprint,
            "registered_at_utc": _utc_iso(self.registered_at_utc),
            "contract_snapshot": _thaw_read_only_value(self.contract_snapshot),
            "artifact_reference_snapshot": _thaw_read_only_value(self.artifact_reference_snapshot),
        }
        if include_record_hash:
            payload["record_hash"] = self.record_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_record_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfflineResearchExperimentRegistryRecord":
        if not isinstance(data, Mapping):
            raise OfflineResearchExperimentRegistryValidationError("registry record must be a mapping.")
        mapping = dict(data)
        allowed = {
            "schema_version",
            "experiment_id",
            "experiment_version",
            "experiment_fingerprint",
            "registered_at_utc",
            "contract_snapshot",
            "artifact_reference_snapshot",
            "record_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise OfflineResearchExperimentRegistryValidationError(
                f"unexpected registry record fields: {', '.join(extra)}."
            )
        try:
            return cls(
                schema_version=mapping.get("schema_version", OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_SCHEMA_VERSION),
                experiment_id=mapping["experiment_id"],
                experiment_version=mapping["experiment_version"],
                experiment_fingerprint=mapping["experiment_fingerprint"],
                registered_at_utc=mapping.get("registered_at_utc", datetime.now(timezone.utc)),
                contract_snapshot=mapping["contract_snapshot"],
                artifact_reference_snapshot=mapping["artifact_reference_snapshot"],
                record_hash=mapping.get("record_hash", ""),
            )
        except KeyError as exc:
            raise OfflineResearchExperimentRegistryValidationError("registry record is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class OfflineResearchExperimentRegistry:
    registry_file: Path = field(default_factory=Path, repr=False)
    schema_version: int = OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_SCHEMA_VERSION
    registry_id: str = OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_ID
    registry_version: str = OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_VERSION
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    records: tuple[OfflineResearchExperimentRegistryRecord, ...] = field(default_factory=tuple)
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_NON_OPERATIONAL_DECLARATION
    registry_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_file", Path(self.registry_file))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "registry_id", _require_str(self.registry_id, "registry_id"))
        object.__setattr__(self, "registry_version", _require_str(self.registry_version, "registry_version"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "updated_at_utc", _require_utc_datetime(self.updated_at_utc, "updated_at_utc"))
        records = tuple(
            record if isinstance(record, OfflineResearchExperimentRegistryRecord) else OfflineResearchExperimentRegistryRecord.from_dict(record)
            for record in self.records
        )
        records = tuple(sorted(records, key=_record_sort_key))
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.schema_version != OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_SCHEMA_VERSION:
            raise OfflineResearchExperimentRegistryValidationError("schema_version must be 1.")
        if self.registry_id != OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_ID:
            raise OfflineResearchExperimentRegistryValidationError(
                "registry_id must remain offline_research_experiment_registry."
            )
        if self.registry_version != OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_VERSION:
            raise OfflineResearchExperimentRegistryValidationError(
                "registry_version must remain phase41_offline_experiment_registry_v1."
            )
        if self.historical_research_only is not True:
            raise OfflineResearchExperimentRegistryValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchExperimentRegistryValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchExperimentRegistryValidationError("paper_promotion_eligible must be false.")
        if self.non_operational_declaration != OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchExperimentRegistryValidationError(
                "non_operational_declaration diverges from the registry contract."
            )

        seen_ids: set[str] = set()
        seen_fingerprints: set[str] = set()
        for record in records:
            if record.experiment_id in seen_ids:
                raise OfflineResearchExperimentRegistryConflictError("experiment_id conflict.")
            if record.experiment_fingerprint in seen_fingerprints:
                raise OfflineResearchExperimentRegistryConflictError("experiment_fingerprint conflict.")
            seen_ids.add(record.experiment_id)
            seen_fingerprints.add(record.experiment_fingerprint)

        expected_hash = _hash_payload(self.canonical_payload(include_registry_hash=False))
        if self.registry_hash:
            if self.registry_hash != expected_hash:
                raise OfflineResearchExperimentRegistryIntegrityError("registry_hash mismatch.")
        else:
            object.__setattr__(self, "registry_hash", expected_hash)

    @property
    def record_count(self) -> int:
        return len(self.records)

    def canonical_payload(self, *, include_registry_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "registry_id": self.registry_id,
            "registry_version": self.registry_version,
            "created_at_utc": _utc_iso(self.created_at_utc),
            "updated_at_utc": _utc_iso(self.updated_at_utc),
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
            "records": [record.canonical_payload(include_record_hash=True) for record in self.records],
        }
        if include_registry_hash:
            payload["registry_hash"] = self.registry_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_registry_hash=True))

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        registry_file: str | Path = Path(),
    ) -> "OfflineResearchExperimentRegistry":
        if not isinstance(data, Mapping):
            raise OfflineResearchExperimentRegistryValidationError("offline research experiment registry must be a mapping.")
        mapping = dict(data)
        allowed = {
            "schema_version",
            "registry_id",
            "registry_version",
            "created_at_utc",
            "updated_at_utc",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "non_operational_declaration",
            "records",
            "registry_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise OfflineResearchExperimentRegistryValidationError(
                f"unexpected offline research experiment registry fields: {', '.join(extra)}."
            )
        try:
            return cls(
                registry_file=registry_file,
                schema_version=mapping.get("schema_version", OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_SCHEMA_VERSION),
                registry_id=mapping.get("registry_id", OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_ID),
                registry_version=mapping.get("registry_version", OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_VERSION),
                created_at_utc=mapping.get("created_at_utc", datetime.now(timezone.utc)),
                updated_at_utc=mapping.get("updated_at_utc", datetime.now(timezone.utc)),
                records=tuple(mapping.get("records", ())),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                non_operational_declaration=mapping.get(
                    "non_operational_declaration",
                    OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_NON_OPERATIONAL_DECLARATION,
                ),
                registry_hash=mapping.get("registry_hash", ""),
            )
        except KeyError as exc:
            raise OfflineResearchExperimentRegistryValidationError("offline research experiment registry is incomplete.") from exc

    def record_by_experiment_id(self, experiment_id: str) -> OfflineResearchExperimentRegistryRecord:
        target = _require_str(experiment_id, "experiment_id")
        for record in self.records:
            if record.experiment_id == target:
                return record
        raise OfflineResearchExperimentRegistryValidationError("experiment_id was not found in the registry.")

    def record_by_fingerprint(self, experiment_fingerprint: str) -> OfflineResearchExperimentRegistryRecord:
        target = _require_hex_digest(experiment_fingerprint, "experiment_fingerprint")
        for record in self.records:
            if record.experiment_fingerprint == target:
                return record
        raise OfflineResearchExperimentRegistryValidationError("experiment_fingerprint was not found in the registry.")

    def contract_by_experiment_id(self, experiment_id: str) -> OfflineResearchExperimentContract:
        return self.record_by_experiment_id(experiment_id).contract

    def contract_by_fingerprint(self, experiment_fingerprint: str) -> OfflineResearchExperimentContract:
        return self.record_by_fingerprint(experiment_fingerprint).contract

    def with_record(
        self,
        record: OfflineResearchExperimentRegistryRecord,
        *,
        updated_at_utc: datetime | None = None,
    ) -> "OfflineResearchExperimentRegistry":
        records = tuple(self.records) + (record,)
        return OfflineResearchExperimentRegistry(
            registry_file=self.registry_file,
            schema_version=self.schema_version,
            registry_id=self.registry_id,
            registry_version=self.registry_version,
            created_at_utc=self.created_at_utc,
            updated_at_utc=updated_at_utc or datetime.now(timezone.utc),
            records=records,
            historical_research_only=self.historical_research_only,
            operational_evidence=self.operational_evidence,
            paper_promotion_eligible=self.paper_promotion_eligible,
            non_operational_declaration=self.non_operational_declaration,
        )


@dataclass(frozen=True, slots=True)
class OfflineResearchExperimentRegistryVerificationReport:
    schema_version: int = OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_SCHEMA_VERSION
    registry_file: Path = field(default_factory=Path)
    verified_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved: bool = True
    registry_id: str = OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_ID
    registry_version: str = OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_VERSION
    record_count: int = 0
    registry_hash: str = ""
    experiment_ids: tuple[str, ...] = ()
    experiment_fingerprints: tuple[str, ...] = ()
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_NON_OPERATIONAL_DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_file", Path(self.registry_file))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "verified_at_utc", _require_utc_datetime(self.verified_at_utc, "verified_at_utc"))
        object.__setattr__(self, "approved", _require_bool(self.approved, "approved"))
        object.__setattr__(self, "registry_id", _require_str(self.registry_id, "registry_id"))
        object.__setattr__(self, "registry_version", _require_str(self.registry_version, "registry_version"))
        object.__setattr__(self, "record_count", _require_int(self.record_count, "record_count"))
        object.__setattr__(self, "registry_hash", _require_hex_digest(self.registry_hash, "registry_hash") if self.registry_hash else "")
        object.__setattr__(self, "experiment_ids", tuple(_require_str(item, "experiment_id") for item in self.experiment_ids))
        object.__setattr__(self, "experiment_fingerprints", tuple(_require_hex_digest(item, "experiment_fingerprint") for item in self.experiment_fingerprints))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.approved is not True:
            raise OfflineResearchExperimentRegistryValidationError("approved must be true.")

    def canonical_payload(self, *, include_report_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "registry_file": self.registry_file.as_posix(),
            "verified_at_utc": _utc_iso(self.verified_at_utc),
            "approved": self.approved,
            "registry_id": self.registry_id,
            "registry_version": self.registry_version,
            "record_count": self.record_count,
            "experiment_ids": self.experiment_ids,
            "experiment_fingerprints": self.experiment_fingerprints,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
            "registry_hash": self.registry_hash,
        }
        if not include_report_hash:
            payload.pop("registry_hash", None)
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_report_hash=True))


def load_offline_research_experiment_registry(
    registry_file: str | Path,
) -> OfflineResearchExperimentRegistry:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    payload = _load_json(path)
    if not isinstance(payload, Mapping):
        raise OfflineResearchExperimentRegistryValidationError(
            "offline research experiment registry must be a JSON object."
        )
    registry = OfflineResearchExperimentRegistry.from_dict(payload, registry_file=path)
    if _canonical_json(registry.as_dict()) != _canonical_json(payload):
        raise OfflineResearchExperimentRegistryIntegrityError("offline research experiment registry payload mismatch.")
    return registry


def save_offline_research_experiment_registry(
    registry_file: str | Path,
    registry: OfflineResearchExperimentRegistry,
) -> OfflineResearchExperimentRegistry:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    if not isinstance(registry, OfflineResearchExperimentRegistry):
        raise OfflineResearchExperimentRegistryValidationError(
            "offline research experiment registry is required."
        )
    payload = registry.as_dict()
    if path.exists():
        existing = load_offline_research_experiment_registry(path)
        if _canonical_json(existing.as_dict()) != _canonical_json(payload):
            raise OfflineResearchExperimentRegistryConflictError(
                "offline research experiment registry already exists and differs."
            )
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{id(registry)}.tmp")
    try:
        tmp_path.write_text(_canonical_json(payload), encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise OfflineResearchExperimentRegistryValidationError(
            "failed to write offline research experiment registry atomically."
        ) from exc
    return registry


def _load_or_create_registry(
    registry_file: str | Path,
    *,
    created_at_utc: datetime | None = None,
    updated_at_utc: datetime | None = None,
) -> OfflineResearchExperimentRegistry:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    if path.exists():
        return load_offline_research_experiment_registry(path)
    return OfflineResearchExperimentRegistry(
        registry_file=path,
        created_at_utc=created_at_utc or datetime.now(timezone.utc),
        updated_at_utc=updated_at_utc or datetime.now(timezone.utc),
    )


def _build_registry_record(
    contract: OfflineResearchExperimentContract,
    *,
    registered_at_utc: datetime | None = None,
) -> OfflineResearchExperimentRegistryRecord:
    if not isinstance(contract, OfflineResearchExperimentContract):
        raise OfflineResearchExperimentRegistryValidationError(
            "a verified offline research experiment contract is required."
        )
    if contract.historical_research_only is not True:
        raise OfflineResearchExperimentRegistryValidationError("historical_research_only must be true.")
    if contract.operational_evidence is not False:
        raise OfflineResearchExperimentRegistryValidationError("operational_evidence must be false.")
    if contract.paper_promotion_eligible is not False:
        raise OfflineResearchExperimentRegistryValidationError("paper_promotion_eligible must be false.")
    if contract.paper_trading_enabled is not False:
        raise OfflineResearchExperimentRegistryValidationError("paper_trading_enabled must be false.")
    if contract.live_trading_enabled is not False:
        raise OfflineResearchExperimentRegistryValidationError("live_trading_enabled must be false.")
    if contract.execution_enabled is not False:
        raise OfflineResearchExperimentRegistryValidationError("execution_enabled must be false.")
    if contract.order_submission_enabled is not False:
        raise OfflineResearchExperimentRegistryValidationError("order_submission_enabled must be false.")
    if contract.credentials_required is not False:
        raise OfflineResearchExperimentRegistryValidationError("credentials_required must be false.")
    if contract.exchange_api_enabled is not False:
        raise OfflineResearchExperimentRegistryValidationError("exchange_api_enabled must be false.")
    if contract.download_enabled is not False:
        raise OfflineResearchExperimentRegistryValidationError("download_enabled must be false.")
    if contract.ingestion_enabled is not False:
        raise OfflineResearchExperimentRegistryValidationError("ingestion_enabled must be false.")
    registered_at = registered_at_utc or datetime.now(timezone.utc)

    return OfflineResearchExperimentRegistryRecord(
        experiment_id=contract.experiment_id,
        experiment_version=contract.experiment_version,
        experiment_fingerprint=contract.contract_hash,
        registered_at_utc=registered_at,
        contract_snapshot=_contract_snapshot_payload(contract),
        artifact_reference_snapshot=_artifact_reference_snapshot_payload(
            contract.artifact_reference,
            registered_at_utc=registered_at,
        ),
    )


def _assert_registration_conflicts(
    registry: OfflineResearchExperimentRegistry,
    record: OfflineResearchExperimentRegistryRecord,
) -> None:
    try:
        existing_by_id = registry.record_by_experiment_id(record.experiment_id)
    except OfflineResearchExperimentRegistryValidationError:
        existing_by_id = None
    try:
        existing_by_fingerprint = registry.record_by_fingerprint(record.experiment_fingerprint)
    except OfflineResearchExperimentRegistryValidationError:
        existing_by_fingerprint = None

    if existing_by_fingerprint is not None:
        raise OfflineResearchExperimentRegistryConflictError("experiment_fingerprint already registered.")
    if existing_by_id is not None:
        raise OfflineResearchExperimentRegistryConflictError("experiment_id already registered with a different fingerprint.")


def register_offline_research_experiment(
    *,
    registry_file: str | Path,
    contract: OfflineResearchExperimentContract,
    registered_at_utc: datetime | None = None,
) -> OfflineResearchExperimentRegistryRecord:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    registry = _load_or_create_registry(path, created_at_utc=registered_at_utc, updated_at_utc=registered_at_utc)
    record = _build_registry_record(contract, registered_at_utc=registered_at_utc)
    _assert_registration_conflicts(registry, record)
    updated_registry = registry.with_record(record, updated_at_utc=registered_at_utc or datetime.now(timezone.utc))
    save_offline_research_experiment_registry(path, updated_registry)
    return record


def list_offline_research_experiment_registry_records(
    registry_file: str | Path,
) -> tuple[OfflineResearchExperimentRegistryRecord, ...]:
    return load_offline_research_experiment_registry(registry_file).records


def get_offline_research_experiment_registry_record_by_experiment_id(
    registry_file: str | Path,
    experiment_id: str,
) -> OfflineResearchExperimentRegistryRecord:
    return load_offline_research_experiment_registry(registry_file).record_by_experiment_id(experiment_id)


def get_offline_research_experiment_registry_record_by_fingerprint(
    registry_file: str | Path,
    experiment_fingerprint: str,
) -> OfflineResearchExperimentRegistryRecord:
    return load_offline_research_experiment_registry(registry_file).record_by_fingerprint(experiment_fingerprint)


def get_offline_research_experiment_contract_by_experiment_id(
    registry_file: str | Path,
    experiment_id: str,
) -> OfflineResearchExperimentContract:
    return load_offline_research_experiment_registry(registry_file).contract_by_experiment_id(experiment_id)


def get_offline_research_experiment_contract_by_fingerprint(
    registry_file: str | Path,
    experiment_fingerprint: str,
) -> OfflineResearchExperimentContract:
    return load_offline_research_experiment_registry(registry_file).contract_by_fingerprint(experiment_fingerprint)


def verify_offline_research_experiment_registry(
    registry_file: str | Path,
) -> OfflineResearchExperimentRegistryVerificationReport:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    registry = load_offline_research_experiment_registry(path)
    report = OfflineResearchExperimentRegistryVerificationReport(
        registry_file=path,
        verified_at_utc=datetime.now(timezone.utc),
        approved=True,
        registry_id=registry.registry_id,
        registry_version=registry.registry_version,
        record_count=registry.record_count,
        registry_hash=registry.registry_hash,
        experiment_ids=tuple(record.experiment_id for record in registry.records),
        experiment_fingerprints=tuple(record.experiment_fingerprint for record in registry.records),
        historical_research_only=registry.historical_research_only,
        operational_evidence=registry.operational_evidence,
        paper_promotion_eligible=registry.paper_promotion_eligible,
        non_operational_declaration=registry.non_operational_declaration,
    )
    if _canonical_json(report.as_dict()) != _canonical_json(report.canonical_payload(include_report_hash=True)):
        raise OfflineResearchExperimentRegistryIntegrityError("registry verification report payload mismatch.")
    return report


__all__ = [
    "OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_ID",
    "OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_NON_OPERATIONAL_DECLARATION",
    "OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_SCHEMA_VERSION",
    "OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_VERSION",
    "OfflineResearchExperimentRegistry",
    "OfflineResearchExperimentRegistryConflictError",
    "OfflineResearchExperimentRegistryError",
    "OfflineResearchExperimentRegistryIntegrityError",
    "OfflineResearchExperimentRegistryRecord",
    "OfflineResearchExperimentRegistryValidationError",
    "OfflineResearchExperimentRegistryVerificationReport",
    "get_offline_research_experiment_contract_by_experiment_id",
    "get_offline_research_experiment_contract_by_fingerprint",
    "get_offline_research_experiment_registry_record_by_experiment_id",
    "get_offline_research_experiment_registry_record_by_fingerprint",
    "list_offline_research_experiment_registry_records",
    "load_offline_research_experiment_registry",
    "register_offline_research_experiment",
    "save_offline_research_experiment_registry",
    "verify_offline_research_experiment_registry",
]
