from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from domain.serialization import serialize_value

from .errors import (
    HistoricalDataConflictError,
    HistoricalDataError,
    HistoricalDataIntegrityError,
    HistoricalDataValidationError,
)
from . import offline_research_experiment_registry as experiment_registry

OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_SCHEMA_VERSION = 1
OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_ID = "offline_research_experiment_execution_registry"
OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_VERSION = "phase42_offline_experiment_execution_registry_v1"
OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_ALLOWED_STATUSES = (
    "REGISTERED",
    "INVALIDATED",
    "ABORTED_BEFORE_EXECUTION",
)
OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_NON_OPERATIONAL_DECLARATION = (
    "This registry is research-only and does not authorize replay, backtest, walk-forward, performance "
    "evaluation, ranking, paper trading, live trading, execution, exchange connectivity, position "
    "management, or order submission."
)


class OfflineResearchExperimentExecutionRegistryError(HistoricalDataError):
    pass


class OfflineResearchExperimentExecutionRegistryValidationError(
    OfflineResearchExperimentExecutionRegistryError, HistoricalDataValidationError
):
    pass


class OfflineResearchExperimentExecutionRegistryIntegrityError(
    OfflineResearchExperimentExecutionRegistryError, HistoricalDataIntegrityError
):
    pass


class OfflineResearchExperimentExecutionRegistryConflictError(
    OfflineResearchExperimentExecutionRegistryError, HistoricalDataConflictError
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    try:
        canonical = _canonical_json(payload)
    except TypeError as exc:
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "payload is not serializable."
        ) from exc
    return sha256(canonical.encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineResearchExperimentExecutionRegistryValidationError(f"{field_name} is required.")
    return value.strip()


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineResearchExperimentExecutionRegistryValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineResearchExperimentExecutionRegistryValidationError(f"{field_name} must be a boolean.")
    return value


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_commit_sha(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 40 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            f"{field_name} must be a 40-character hex git commit sha."
        )
    return digest


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineResearchExperimentExecutionRegistryValidationError(
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
        raise OfflineResearchExperimentExecutionRegistryValidationError(
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
    if isinstance(value, frozenset):
        return frozenset(_freeze_read_only_value(item) for item in value)
    return value


def _thaw_read_only_value(value: Any) -> Any:
    if isinstance(value, MappingProxyType) or isinstance(value, Mapping):
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
                    (_canonical_json(item), item)
                    for item in thawed_items
                ),
                key=lambda pair: pair[0],
            )
        )
    return value


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "offline research experiment execution registry is missing."
        )
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "offline research experiment execution registry is empty."
        )
    try:
        return json.loads(text)
    except Exception as exc:
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "offline research experiment execution registry is invalid JSON."
        ) from exc


def _normalize_experiment_registration_snapshot(
    experiment_registration: experiment_registry.OfflineResearchExperimentRegistryRecord | Mapping[str, Any],
) -> tuple[str, str, Mapping[str, Any]]:
    if isinstance(experiment_registration, Mapping):
        snapshot = dict(experiment_registration)
    elif hasattr(experiment_registration, "as_dict") and hasattr(experiment_registration, "experiment_id"):
        snapshot = dict(experiment_registration.as_dict())
    else:
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "a verified phase 41 experiment registration is required."
        )

    if "experiment_id" not in snapshot:
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "experiment registration snapshot is incomplete."
        )
    if "record_hash" not in snapshot:
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "experiment registration snapshot is incomplete."
        )

    experiment_id = _require_str(snapshot["experiment_id"], "experiment_id")
    record_hash = _require_hex_digest(snapshot["record_hash"], "record_hash")
    payload = dict(snapshot)
    payload.pop("record_hash", None)
    expected_hash = _hash_payload(payload)
    if record_hash != expected_hash:
        raise OfflineResearchExperimentExecutionRegistryIntegrityError(
            "experiment_registration_hash mismatch."
        )
    if snapshot.get("historical_research_only", True) is not True:
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "historical_research_only must be true."
        )
    if snapshot.get("operational_evidence", False) is not False:
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "operational_evidence must be false."
        )
    if snapshot.get("paper_promotion_eligible", False) is not False:
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "paper_promotion_eligible must be false."
        )
    if snapshot.get(
        "non_operational_declaration",
        experiment_registry.OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_NON_OPERATIONAL_DECLARATION,
    ) != experiment_registry.OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "non_operational_declaration diverges from the experiment registry contract."
        )
    return experiment_id, record_hash, _freeze_read_only_value(snapshot)


def _freeze_experiment_registration_snapshot(
    experiment_registration: experiment_registry.OfflineResearchExperimentRegistryRecord | Mapping[str, Any],
) -> tuple[str, str, Mapping[str, Any]]:
    return _normalize_experiment_registration_snapshot(experiment_registration)


def _build_experiment_registration_from_snapshot(snapshot: Mapping[str, Any]) -> tuple[str, str, Mapping[str, Any]]:
    if not isinstance(snapshot, Mapping):
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "experiment registration snapshot must be a mapping."
        )
    try:
        experiment_id = _require_str(snapshot["experiment_id"], "experiment_id")
        record_hash = _require_hex_digest(snapshot["record_hash"], "record_hash")
        payload = dict(snapshot)
        payload.pop("record_hash", None)
        expected_hash = _hash_payload(_thaw_read_only_value(payload))
        if record_hash != expected_hash:
            raise OfflineResearchExperimentExecutionRegistryIntegrityError(
                "experiment_registration_hash mismatch."
            )
        return experiment_id, record_hash, _freeze_read_only_value(dict(snapshot))
    except KeyError as exc:
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "experiment registration snapshot is incomplete."
        ) from exc
    except OfflineResearchExperimentExecutionRegistryError:
        raise
    except Exception as exc:
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "experiment registration snapshot is invalid."
        ) from exc


def _normalize_execution_status(value: Any) -> str:
    status = _require_str(value, "execution_status").upper()
    if status not in OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_ALLOWED_STATUSES:
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "execution_status is not allowed."
        )
    return status


def _execution_identity_payload(
    *,
    schema_version: int,
    registry_id: str,
    registry_version: str,
    experiment_id: str,
    experiment_registration_hash: str,
    attempt_number: int,
    previous_execution_id: str | None,
    previous_execution_hash: str | None,
    created_at_utc: datetime,
    source_commit_sha: str,
    source_branch: str,
    execution_status: str,
    execution_reason: str,
    execution_context: Any,
    experiment_registration_snapshot: Any,
    offline_only: bool,
    historical_research_only: bool,
    operational_evidence: bool,
    paper_promotion_eligible: bool,
    non_operational_declaration: str,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "registry_id": registry_id,
        "registry_version": registry_version,
        "experiment_id": experiment_id,
        "experiment_registration_hash": experiment_registration_hash,
        "attempt_number": attempt_number,
        "previous_execution_id": previous_execution_id,
        "previous_execution_hash": previous_execution_hash,
        "created_at_utc": _utc_iso(created_at_utc),
        "source_commit_sha": source_commit_sha,
        "source_branch": source_branch,
        "execution_status": execution_status,
        "execution_reason": execution_reason,
        "execution_context": _thaw_read_only_value(execution_context),
        "experiment_registration_snapshot": _thaw_read_only_value(experiment_registration_snapshot),
        "offline_only": offline_only,
        "historical_research_only": historical_research_only,
        "operational_evidence": operational_evidence,
        "paper_promotion_eligible": paper_promotion_eligible,
        "non_operational_declaration": non_operational_declaration,
    }


def _record_sort_key(record: "OfflineResearchExperimentExecutionRegistration") -> tuple[str, int, str, str]:
    return (
        record.experiment_id,
        record.attempt_number,
        record.execution_id,
        record.execution_hash,
    )


@dataclass(frozen=True, slots=True)
class OfflineResearchExperimentExecutionRegistration:
    schema_version: int = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_SCHEMA_VERSION
    registry_id: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_ID
    registry_version: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_VERSION
    execution_id: str = ""
    experiment_id: str = ""
    experiment_registration_hash: str = ""
    attempt_number: int = 0
    previous_execution_id: str | None = None
    previous_execution_hash: str | None = None
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_commit_sha: str = ""
    source_branch: str = ""
    execution_status: str = ""
    execution_reason: str = ""
    execution_context: Mapping[str, Any] = field(default_factory=dict, repr=False)
    experiment_registration_snapshot: Mapping[str, Any] = field(default_factory=dict, repr=False)
    offline_only: bool = True
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_NON_OPERATIONAL_DECLARATION
    execution_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "registry_id", _require_str(self.registry_id, "registry_id"))
        object.__setattr__(self, "registry_version", _require_str(self.registry_version, "registry_version"))
        object.__setattr__(self, "experiment_id", _require_str(self.experiment_id, "experiment_id"))
        object.__setattr__(self, "experiment_registration_hash", _require_hex_digest(self.experiment_registration_hash, "experiment_registration_hash"))
        object.__setattr__(self, "attempt_number", _require_int(self.attempt_number, "attempt_number"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "source_commit_sha", _require_commit_sha(self.source_commit_sha, "source_commit_sha"))
        object.__setattr__(self, "source_branch", _require_str(self.source_branch, "source_branch"))
        object.__setattr__(self, "execution_status", _normalize_execution_status(self.execution_status))
        object.__setattr__(self, "execution_reason", _require_str(self.execution_reason, "execution_reason"))
        object.__setattr__(self, "execution_context", _freeze_read_only_value(dict(self.execution_context)))
        object.__setattr__(self, "experiment_registration_snapshot", _freeze_read_only_value(dict(self.experiment_registration_snapshot)))
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))

        if self.schema_version != OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_SCHEMA_VERSION:
            raise OfflineResearchExperimentExecutionRegistryValidationError("schema_version must be 1.")
        if self.registry_id != OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_ID:
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                "registry_id must remain offline_research_experiment_execution_registry."
            )
        if self.registry_version != OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_VERSION:
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                "registry_version must remain phase42_offline_experiment_execution_registry_v1."
            )
        if self.attempt_number <= 0:
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                "attempt_number must be greater than zero."
            )
        if self.offline_only is not True:
            raise OfflineResearchExperimentExecutionRegistryValidationError("offline_only must be true.")
        if self.historical_research_only is not True:
            raise OfflineResearchExperimentExecutionRegistryValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchExperimentExecutionRegistryValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchExperimentExecutionRegistryValidationError("paper_promotion_eligible must be false.")
        if self.non_operational_declaration != OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                "non_operational_declaration diverges from the execution registry contract."
            )

        registration_experiment_id, registration_hash, normalized_snapshot = _build_experiment_registration_from_snapshot(
            self.experiment_registration_snapshot
        )
        object.__setattr__(self, "experiment_registration_snapshot", normalized_snapshot)
        if registration_experiment_id != self.experiment_id:
            raise OfflineResearchExperimentExecutionRegistryIntegrityError("experiment_id mismatch.")
        if registration_hash != self.experiment_registration_hash:
            raise OfflineResearchExperimentExecutionRegistryIntegrityError(
                "experiment_registration_hash mismatch."
            )

        if self.attempt_number == 1:
            if self.previous_execution_id is not None or self.previous_execution_hash is not None:
                raise OfflineResearchExperimentExecutionRegistryValidationError(
                    "previous execution reference is not allowed for attempt_number 1."
                )
        else:
            if self.previous_execution_id is None or self.previous_execution_hash is None:
                raise OfflineResearchExperimentExecutionRegistryValidationError(
                    "previous execution reference is required for attempt_number greater than 1."
                )
            object.__setattr__(self, "previous_execution_id", _require_str(self.previous_execution_id, "previous_execution_id"))
            object.__setattr__(self, "previous_execution_hash", _require_hex_digest(self.previous_execution_hash, "previous_execution_hash"))

        expected_execution_id = _hash_payload(self._execution_identity_payload(include_execution_id=False))
        if self.execution_id:
            if self.execution_id != expected_execution_id:
                raise OfflineResearchExperimentExecutionRegistryIntegrityError("execution_id mismatch.")
        else:
            object.__setattr__(self, "execution_id", expected_execution_id)

        expected_execution_hash = _hash_payload(self.canonical_payload(include_execution_hash=False))
        if self.execution_hash:
            if self.execution_hash != expected_execution_hash:
                raise OfflineResearchExperimentExecutionRegistryIntegrityError("execution_hash mismatch.")
        else:
            object.__setattr__(self, "execution_hash", expected_execution_hash)

        if self.attempt_number > 1:
            if self.previous_execution_id == self.execution_id:
                raise OfflineResearchExperimentExecutionRegistryIntegrityError(
                    "previous_execution_id cannot equal execution_id."
                )
            if self.previous_execution_hash == self.execution_hash:
                raise OfflineResearchExperimentExecutionRegistryIntegrityError(
                    "previous_execution_hash cannot equal execution_hash."
                )

    def _execution_identity_payload(self, *, include_execution_id: bool = True) -> dict[str, Any]:
        payload = _execution_identity_payload(
            schema_version=self.schema_version,
            registry_id=self.registry_id,
            registry_version=self.registry_version,
            experiment_id=self.experiment_id,
            experiment_registration_hash=self.experiment_registration_hash,
            attempt_number=self.attempt_number,
            previous_execution_id=self.previous_execution_id,
            previous_execution_hash=self.previous_execution_hash,
            created_at_utc=self.created_at_utc,
            source_commit_sha=self.source_commit_sha,
            source_branch=self.source_branch,
            execution_status=self.execution_status,
            execution_reason=self.execution_reason,
            execution_context=self.execution_context,
            experiment_registration_snapshot=self.experiment_registration_snapshot,
            offline_only=self.offline_only,
            historical_research_only=self.historical_research_only,
            operational_evidence=self.operational_evidence,
            paper_promotion_eligible=self.paper_promotion_eligible,
            non_operational_declaration=self.non_operational_declaration,
        )
        if include_execution_id:
            payload["execution_id"] = self.execution_id
        return payload

    def canonical_payload(self, *, include_execution_hash: bool = True) -> dict[str, Any]:
        payload = self._execution_identity_payload(include_execution_id=True)
        if include_execution_hash:
            payload["execution_hash"] = self.execution_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_execution_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfflineResearchExperimentExecutionRegistration":
        if not isinstance(data, Mapping):
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                "offline research experiment execution registration must be a mapping."
            )
        mapping = dict(data)
        allowed = {
            "schema_version",
            "registry_id",
            "registry_version",
            "execution_id",
            "experiment_id",
            "experiment_registration_hash",
            "attempt_number",
            "previous_execution_id",
            "previous_execution_hash",
            "created_at_utc",
            "source_commit_sha",
            "source_branch",
            "execution_status",
            "execution_reason",
            "execution_context",
            "experiment_registration_snapshot",
            "offline_only",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "non_operational_declaration",
            "execution_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                f"unexpected offline research experiment execution registration fields: {', '.join(extra)}."
            )
        try:
            return cls(
                schema_version=mapping.get("schema_version", OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_SCHEMA_VERSION),
                registry_id=mapping.get("registry_id", OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_ID),
                registry_version=mapping.get("registry_version", OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_VERSION),
                execution_id=mapping.get("execution_id", ""),
                experiment_id=mapping["experiment_id"],
                experiment_registration_hash=mapping["experiment_registration_hash"],
                attempt_number=mapping["attempt_number"],
                previous_execution_id=mapping.get("previous_execution_id"),
                previous_execution_hash=mapping.get("previous_execution_hash"),
                created_at_utc=mapping.get("created_at_utc", datetime.now(timezone.utc)),
                source_commit_sha=mapping["source_commit_sha"],
                source_branch=mapping["source_branch"],
                execution_status=mapping["execution_status"],
                execution_reason=mapping["execution_reason"],
                execution_context=mapping.get("execution_context", {}),
                experiment_registration_snapshot=mapping["experiment_registration_snapshot"],
                offline_only=mapping.get("offline_only", True),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                non_operational_declaration=mapping.get(
                    "non_operational_declaration",
                    OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_NON_OPERATIONAL_DECLARATION,
                ),
                execution_hash=mapping.get("execution_hash", ""),
            )
        except KeyError as exc:
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                "offline research experiment execution registration is incomplete."
            ) from exc


@dataclass(frozen=True, slots=True)
class OfflineResearchExperimentExecutionRegistry:
    registry_file: Path = field(default_factory=Path, repr=False)
    schema_version: int = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_SCHEMA_VERSION
    registry_id: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_ID
    registry_version: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_VERSION
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    records: tuple[OfflineResearchExperimentExecutionRegistration, ...] = field(default_factory=tuple)
    offline_only: bool = True
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_NON_OPERATIONAL_DECLARATION
    registry_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_file", Path(self.registry_file))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "registry_id", _require_str(self.registry_id, "registry_id"))
        object.__setattr__(self, "registry_version", _require_str(self.registry_version, "registry_version"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "updated_at_utc", _require_utc_datetime(self.updated_at_utc, "updated_at_utc"))
        records = tuple(
            record
            if isinstance(record, OfflineResearchExperimentExecutionRegistration)
            else OfflineResearchExperimentExecutionRegistration.from_dict(record)
            for record in self.records
        )
        records = tuple(sorted(records, key=_record_sort_key))
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))

        if self.schema_version != OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_SCHEMA_VERSION:
            raise OfflineResearchExperimentExecutionRegistryValidationError("schema_version must be 1.")
        if self.registry_id != OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_ID:
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                "registry_id must remain offline_research_experiment_execution_registry."
            )
        if self.registry_version != OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_VERSION:
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                "registry_version must remain phase42_offline_experiment_execution_registry_v1."
            )
        if self.offline_only is not True:
            raise OfflineResearchExperimentExecutionRegistryValidationError("offline_only must be true.")
        if self.historical_research_only is not True:
            raise OfflineResearchExperimentExecutionRegistryValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchExperimentExecutionRegistryValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchExperimentExecutionRegistryValidationError("paper_promotion_eligible must be false.")
        if self.non_operational_declaration != OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                "non_operational_declaration diverges from the execution registry contract."
            )

        seen_execution_ids: set[str] = set()
        seen_execution_hashes: set[str] = set()
        attempts_by_experiment: dict[str, dict[int, OfflineResearchExperimentExecutionRegistration]] = {}
        for record in records:
            if record.execution_id in seen_execution_ids:
                raise OfflineResearchExperimentExecutionRegistryConflictError("execution_id conflict.")
            if record.execution_hash in seen_execution_hashes:
                raise OfflineResearchExperimentExecutionRegistryConflictError("execution_hash conflict.")
            seen_execution_ids.add(record.execution_id)
            seen_execution_hashes.add(record.execution_hash)
            attempts_by_experiment.setdefault(record.experiment_id, {})
            if record.attempt_number in attempts_by_experiment[record.experiment_id]:
                raise OfflineResearchExperimentExecutionRegistryConflictError("attempt_number conflict.")
            attempts_by_experiment[record.experiment_id][record.attempt_number] = record

        for experiment_id, attempts in attempts_by_experiment.items():
            if not attempts:
                continue
            ordered_attempts = [attempts[number] for number in sorted(attempts)]
            for expected_number, record in enumerate(ordered_attempts, start=1):
                if record.attempt_number != expected_number:
                    raise OfflineResearchExperimentExecutionRegistryIntegrityError(
                        "attempt_number sequence gap."
                    )
                if expected_number == 1:
                    if record.previous_execution_id is not None or record.previous_execution_hash is not None:
                        raise OfflineResearchExperimentExecutionRegistryValidationError(
                            "previous execution reference is not allowed for attempt_number 1."
                        )
                else:
                    previous_record = ordered_attempts[expected_number - 2]
                    if record.previous_execution_id != previous_record.execution_id:
                        raise OfflineResearchExperimentExecutionRegistryIntegrityError(
                            "previous_execution_id mismatch."
                        )
                    if record.previous_execution_hash != previous_record.execution_hash:
                        raise OfflineResearchExperimentExecutionRegistryIntegrityError(
                            "previous_execution_hash mismatch."
                        )
                    if previous_record.experiment_id != experiment_id:
                        raise OfflineResearchExperimentExecutionRegistryIntegrityError(
                            "previous execution belongs to a different experiment."
                        )

        expected_hash = _hash_payload(self.canonical_payload(include_registry_hash=False))
        if self.registry_hash:
            if self.registry_hash != expected_hash:
                raise OfflineResearchExperimentExecutionRegistryIntegrityError("registry_hash mismatch.")
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
            "offline_only": self.offline_only,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
            "records": [record.canonical_payload(include_execution_hash=True) for record in self.records],
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
    ) -> "OfflineResearchExperimentExecutionRegistry":
        if not isinstance(data, Mapping):
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                "offline research experiment execution registry must be a mapping."
            )
        mapping = dict(data)
        allowed = {
            "schema_version",
            "registry_id",
            "registry_version",
            "created_at_utc",
            "updated_at_utc",
            "offline_only",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "non_operational_declaration",
            "records",
            "registry_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                f"unexpected offline research experiment execution registry fields: {', '.join(extra)}."
            )
        try:
            return cls(
                registry_file=registry_file,
                schema_version=mapping.get("schema_version", OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_SCHEMA_VERSION),
                registry_id=mapping.get("registry_id", OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_ID),
                registry_version=mapping.get("registry_version", OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_VERSION),
                created_at_utc=mapping.get("created_at_utc", datetime.now(timezone.utc)),
                updated_at_utc=mapping.get("updated_at_utc", datetime.now(timezone.utc)),
                records=tuple(mapping.get("records", ())),
                offline_only=mapping.get("offline_only", True),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                non_operational_declaration=mapping.get(
                    "non_operational_declaration",
                    OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_NON_OPERATIONAL_DECLARATION,
                ),
                registry_hash=mapping.get("registry_hash", ""),
            )
        except KeyError as exc:
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                "offline research experiment execution registry is incomplete."
            ) from exc

    def registration_by_execution_id(self, execution_id: str) -> OfflineResearchExperimentExecutionRegistration:
        target = _require_str(execution_id, "execution_id")
        for record in self.records:
            if record.execution_id == target:
                return record
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "execution_id was not found in the registry."
        )

    def registration_by_execution_hash(self, execution_hash: str) -> OfflineResearchExperimentExecutionRegistration:
        target = _require_hex_digest(execution_hash, "execution_hash")
        for record in self.records:
            if record.execution_hash == target:
                return record
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "execution_hash was not found in the registry."
        )

    def registrations_for_experiment_id(self, experiment_id: str) -> tuple[OfflineResearchExperimentExecutionRegistration, ...]:
        target = _require_str(experiment_id, "experiment_id")
        return tuple(sorted((record for record in self.records if record.experiment_id == target), key=lambda r: r.attempt_number))

    def registration_by_experiment_id_and_attempt_number(
        self,
        experiment_id: str,
        attempt_number: int,
    ) -> OfflineResearchExperimentExecutionRegistration:
        target_experiment_id = _require_str(experiment_id, "experiment_id")
        target_attempt = _require_int(attempt_number, "attempt_number")
        for record in self.records:
            if record.experiment_id == target_experiment_id and record.attempt_number == target_attempt:
                return record
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "execution attempt was not found in the registry."
        )

    def with_record(
        self,
        record: OfflineResearchExperimentExecutionRegistration,
        *,
        updated_at_utc: datetime | None = None,
    ) -> "OfflineResearchExperimentExecutionRegistry":
        records = tuple(self.records) + (record,)
        return OfflineResearchExperimentExecutionRegistry(
            registry_file=self.registry_file,
            schema_version=self.schema_version,
            registry_id=self.registry_id,
            registry_version=self.registry_version,
            created_at_utc=self.created_at_utc,
            updated_at_utc=updated_at_utc or datetime.now(timezone.utc),
            records=records,
            offline_only=self.offline_only,
            historical_research_only=self.historical_research_only,
            operational_evidence=self.operational_evidence,
            paper_promotion_eligible=self.paper_promotion_eligible,
            non_operational_declaration=self.non_operational_declaration,
        )


@dataclass(frozen=True, slots=True)
class OfflineResearchExperimentExecutionRegistryVerificationReport:
    schema_version: int = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_SCHEMA_VERSION
    registry_file: Path = field(default_factory=Path)
    verified_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved: bool = True
    registry_id: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_ID
    registry_version: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_VERSION
    record_count: int = 0
    registry_hash: str = ""
    execution_ids: tuple[str, ...] = ()
    execution_hashes: tuple[str, ...] = ()
    experiment_ids: tuple[str, ...] = ()
    offline_only: bool = True
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_NON_OPERATIONAL_DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_file", Path(self.registry_file))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "verified_at_utc", _require_utc_datetime(self.verified_at_utc, "verified_at_utc"))
        object.__setattr__(self, "approved", _require_bool(self.approved, "approved"))
        object.__setattr__(self, "registry_id", _require_str(self.registry_id, "registry_id"))
        object.__setattr__(self, "registry_version", _require_str(self.registry_version, "registry_version"))
        object.__setattr__(self, "record_count", _require_int(self.record_count, "record_count"))
        object.__setattr__(self, "registry_hash", _require_hex_digest(self.registry_hash, "registry_hash") if self.registry_hash else "")
        object.__setattr__(self, "execution_ids", tuple(_require_str(item, "execution_id") for item in self.execution_ids))
        object.__setattr__(self, "execution_hashes", tuple(_require_hex_digest(item, "execution_hash") for item in self.execution_hashes))
        object.__setattr__(self, "experiment_ids", tuple(_require_str(item, "experiment_id") for item in self.experiment_ids))
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.approved is not True:
            raise OfflineResearchExperimentExecutionRegistryValidationError("approved must be true.")

    def canonical_payload(self, *, include_report_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "registry_file": self.registry_file.as_posix(),
            "verified_at_utc": _utc_iso(self.verified_at_utc),
            "approved": self.approved,
            "registry_id": self.registry_id,
            "registry_version": self.registry_version,
            "record_count": self.record_count,
            "execution_ids": self.execution_ids,
            "execution_hashes": self.execution_hashes,
            "experiment_ids": self.experiment_ids,
            "offline_only": self.offline_only,
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


def _build_registration_from_registry_snapshot(
    snapshot: Mapping[str, Any],
) -> OfflineResearchExperimentExecutionRegistration:
    if not isinstance(snapshot, Mapping):
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "execution registration snapshot must be a mapping."
        )
    try:
        return OfflineResearchExperimentExecutionRegistration.from_dict(dict(snapshot))
    except Exception as exc:
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "execution registration snapshot is invalid."
        ) from exc


def load_offline_research_experiment_execution_registry(
    registry_file: str | Path,
) -> OfflineResearchExperimentExecutionRegistry:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    payload = _load_json(path)
    if not isinstance(payload, Mapping):
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "offline research experiment execution registry must be a JSON object."
        )
    registry = OfflineResearchExperimentExecutionRegistry.from_dict(payload, registry_file=path)
    if _canonical_json(registry.as_dict()) != _canonical_json(payload):
        raise OfflineResearchExperimentExecutionRegistryIntegrityError(
            "offline research experiment execution registry payload mismatch."
        )
    return registry


def save_offline_research_experiment_execution_registry(
    registry_file: str | Path,
    registry: OfflineResearchExperimentExecutionRegistry,
) -> OfflineResearchExperimentExecutionRegistry:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    if not isinstance(registry, OfflineResearchExperimentExecutionRegistry):
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "offline research experiment execution registry is required."
        )
    payload = registry.as_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{id(registry)}.tmp")
    try:
        tmp_path.write_text(_canonical_json(payload), encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise OfflineResearchExperimentExecutionRegistryValidationError(
            "failed to write offline research experiment execution registry atomically."
        ) from exc
    return registry


def _load_or_create_registry(
    registry_file: str | Path,
    *,
    created_at_utc: datetime | None = None,
    updated_at_utc: datetime | None = None,
) -> OfflineResearchExperimentExecutionRegistry:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    if path.exists():
        return load_offline_research_experiment_execution_registry(path)
    return OfflineResearchExperimentExecutionRegistry(
        registry_file=path,
        created_at_utc=created_at_utc or datetime.now(timezone.utc),
        updated_at_utc=updated_at_utc or datetime.now(timezone.utc),
    )


def build_offline_research_experiment_execution_registration(
    *,
    experiment_registration: experiment_registry.OfflineResearchExperimentRegistryRecord | Mapping[str, Any],
    execution_id: str = "",
    attempt_number: int,
    previous_execution_id: str | None = None,
    previous_execution_hash: str | None = None,
    created_at_utc: datetime,
    source_commit_sha: str,
    source_branch: str,
    execution_status: str,
    execution_reason: str,
    execution_context: Mapping[str, Any] | None = None,
    offline_only: bool = True,
    historical_research_only: bool = True,
    operational_evidence: bool = False,
    paper_promotion_eligible: bool = False,
    non_operational_declaration: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_NON_OPERATIONAL_DECLARATION,
    execution_hash: str = "",
) -> OfflineResearchExperimentExecutionRegistration:
    experiment_id, experiment_registration_hash, snapshot = _freeze_experiment_registration_snapshot(experiment_registration)
    return OfflineResearchExperimentExecutionRegistration(
        execution_id=execution_id,
        experiment_id=experiment_id,
        experiment_registration_hash=experiment_registration_hash,
        attempt_number=attempt_number,
        previous_execution_id=previous_execution_id,
        previous_execution_hash=previous_execution_hash,
        created_at_utc=created_at_utc,
        source_commit_sha=source_commit_sha,
        source_branch=source_branch,
        execution_status=execution_status,
        execution_reason=execution_reason,
        execution_context=execution_context or {},
        experiment_registration_snapshot=snapshot,
        offline_only=offline_only,
        historical_research_only=historical_research_only,
        operational_evidence=operational_evidence,
        paper_promotion_eligible=paper_promotion_eligible,
        non_operational_declaration=non_operational_declaration,
        execution_hash=execution_hash,
    )


def _assert_registration_conflicts(
    registry: OfflineResearchExperimentExecutionRegistry,
    record: OfflineResearchExperimentExecutionRegistration,
) -> None:
    try:
        existing_by_id = registry.registration_by_execution_id(record.execution_id)
    except OfflineResearchExperimentExecutionRegistryValidationError:
        existing_by_id = None
    try:
        existing_by_attempt = registry.registration_by_experiment_id_and_attempt_number(
            record.experiment_id,
            record.attempt_number,
        )
    except OfflineResearchExperimentExecutionRegistryValidationError:
        existing_by_attempt = None

    if existing_by_id is not None:
        if existing_by_id.as_dict() == record.as_dict():
            return
        raise OfflineResearchExperimentExecutionRegistryConflictError("execution_id already registered.")
    if existing_by_attempt is not None:
        if existing_by_attempt.as_dict() == record.as_dict():
            return
        raise OfflineResearchExperimentExecutionRegistryConflictError(
            "attempt_number already registered for this experiment."
        )


def register_offline_research_experiment_execution(
    *,
    registry_file: str | Path,
    experiment_registry_file: str | Path,
    experiment_id: str,
    execution_id: str = "",
    attempt_number: int,
    created_at_utc: datetime,
    source_commit_sha: str,
    source_branch: str,
    execution_status: str,
    execution_reason: str,
    previous_execution_id: str | None = None,
    previous_execution_hash: str | None = None,
    execution_context: Mapping[str, Any] | None = None,
    offline_only: bool = True,
    historical_research_only: bool = True,
    operational_evidence: bool = False,
    paper_promotion_eligible: bool = False,
) -> OfflineResearchExperimentExecutionRegistration:
    registry_path = _ensure_registry_path(registry_file, field_name="registry_file")
    experiment_registry_path = _ensure_registry_path(
        experiment_registry_file,
        field_name="experiment_registry_file",
    )
    experiment_registry_loaded = experiment_registry.load_offline_research_experiment_registry(experiment_registry_path)
    experiment_record = experiment_registry_loaded.record_by_experiment_id(experiment_id)
    registry = _load_or_create_registry(registry_path)

    if attempt_number == 1:
        if previous_execution_id is not None or previous_execution_hash is not None:
            raise OfflineResearchExperimentExecutionRegistryValidationError(
                "previous execution reference is not allowed for attempt_number 1."
            )
        resolved_previous_id = None
        resolved_previous_hash = None
    else:
        previous_record = registry.registration_by_experiment_id_and_attempt_number(
            experiment_id,
            attempt_number - 1,
        )
        if previous_execution_id is not None and previous_execution_id != previous_record.execution_id:
            raise OfflineResearchExperimentExecutionRegistryIntegrityError(
                "previous_execution_id mismatch."
            )
        if previous_execution_hash is not None and previous_execution_hash != previous_record.execution_hash:
            raise OfflineResearchExperimentExecutionRegistryIntegrityError(
                "previous_execution_hash mismatch."
            )
        resolved_previous_id = previous_record.execution_id
        resolved_previous_hash = previous_record.execution_hash

    record = build_offline_research_experiment_execution_registration(
        experiment_registration=experiment_record,
        execution_id=execution_id,
        attempt_number=attempt_number,
        previous_execution_id=resolved_previous_id,
        previous_execution_hash=resolved_previous_hash,
        created_at_utc=created_at_utc,
        source_commit_sha=source_commit_sha,
        source_branch=source_branch,
        execution_status=execution_status,
        execution_reason=execution_reason,
        execution_context=execution_context,
        offline_only=offline_only,
        historical_research_only=historical_research_only,
        operational_evidence=operational_evidence,
        paper_promotion_eligible=paper_promotion_eligible,
    )

    _assert_registration_conflicts(registry, record)
    if any(existing.as_dict() == record.as_dict() for existing in registry.records):
        return next(existing for existing in registry.records if existing.as_dict() == record.as_dict())

    updated_registry = registry.with_record(record, updated_at_utc=created_at_utc)
    save_offline_research_experiment_execution_registry(registry_path, updated_registry)
    return record


def list_offline_research_experiment_execution_registry_records(
    registry_file: str | Path,
) -> tuple[OfflineResearchExperimentExecutionRegistration, ...]:
    return load_offline_research_experiment_execution_registry(registry_file).records


def get_offline_research_experiment_execution_registry_record_by_execution_id(
    registry_file: str | Path,
    execution_id: str,
) -> OfflineResearchExperimentExecutionRegistration:
    return load_offline_research_experiment_execution_registry(registry_file).registration_by_execution_id(
        execution_id
    )


def get_offline_research_experiment_execution_registry_record_by_execution_hash(
    registry_file: str | Path,
    execution_hash: str,
) -> OfflineResearchExperimentExecutionRegistration:
    return load_offline_research_experiment_execution_registry(registry_file).registration_by_execution_hash(
        execution_hash
    )


def get_offline_research_experiment_execution_registry_record_by_experiment_id_and_attempt_number(
    registry_file: str | Path,
    experiment_id: str,
    attempt_number: int,
) -> OfflineResearchExperimentExecutionRegistration:
    return load_offline_research_experiment_execution_registry(registry_file).registration_by_experiment_id_and_attempt_number(
        experiment_id,
        attempt_number,
    )


def verify_offline_research_experiment_execution_registry(
    registry_file: str | Path,
) -> OfflineResearchExperimentExecutionRegistryVerificationReport:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    registry = load_offline_research_experiment_execution_registry(path)
    report = OfflineResearchExperimentExecutionRegistryVerificationReport(
        registry_file=path,
        verified_at_utc=datetime.now(timezone.utc),
        approved=True,
        registry_id=registry.registry_id,
        registry_version=registry.registry_version,
        record_count=registry.record_count,
        registry_hash=registry.registry_hash,
        execution_ids=tuple(record.execution_id for record in registry.records),
        execution_hashes=tuple(record.execution_hash for record in registry.records),
        experiment_ids=tuple(record.experiment_id for record in registry.records),
        offline_only=registry.offline_only,
        historical_research_only=registry.historical_research_only,
        operational_evidence=registry.operational_evidence,
        paper_promotion_eligible=registry.paper_promotion_eligible,
        non_operational_declaration=registry.non_operational_declaration,
    )
    if _canonical_json(report.as_dict()) != _canonical_json(report.canonical_payload(include_report_hash=True)):
        raise OfflineResearchExperimentExecutionRegistryIntegrityError(
            "registry verification report payload mismatch."
        )
    return report


__all__ = [
    "OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_ALLOWED_STATUSES",
    "OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_ID",
    "OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_NON_OPERATIONAL_DECLARATION",
    "OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_SCHEMA_VERSION",
    "OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_VERSION",
    "OfflineResearchExperimentExecutionRegistry",
    "OfflineResearchExperimentExecutionRegistryConflictError",
    "OfflineResearchExperimentExecutionRegistryError",
    "OfflineResearchExperimentExecutionRegistryIntegrityError",
    "OfflineResearchExperimentExecutionRegistryValidationError",
    "OfflineResearchExperimentExecutionRegistryVerificationReport",
    "OfflineResearchExperimentExecutionRegistration",
    "build_offline_research_experiment_execution_registration",
    "get_offline_research_experiment_execution_registry_record_by_execution_hash",
    "get_offline_research_experiment_execution_registry_record_by_execution_id",
    "get_offline_research_experiment_execution_registry_record_by_experiment_id_and_attempt_number",
    "list_offline_research_experiment_execution_registry_records",
    "load_offline_research_experiment_execution_registry",
    "register_offline_research_experiment_execution",
    "save_offline_research_experiment_execution_registry",
    "verify_offline_research_experiment_execution_registry",
]
