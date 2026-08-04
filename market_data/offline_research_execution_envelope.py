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

from . import offline_research_canonical_evidence_fixture as phase44_fixture
from . import offline_research_execution_authorization as phase45
from . import offline_research_experiment_execution_plan as phase43_plan
from .errors import (
    HistoricalDataConflictError,
    HistoricalDataError,
    HistoricalDataIntegrityError,
    HistoricalDataValidationError,
)

OFFLINE_RESEARCH_EXECUTION_ENVELOPE_SCHEMA_VERSION = 1
OFFLINE_RESEARCH_EXECUTION_ENVELOPE_VERSION = "phase46_offline_execution_envelope_v1"
OFFLINE_RESEARCH_EXECUTION_ENVELOPE_REGISTRY_ID = "offline_research_execution_envelope_registry"
OFFLINE_RESEARCH_EXECUTION_ENVELOPE_REGISTRY_VERSION = "phase46_offline_execution_envelope_registry_v1"
OFFLINE_RESEARCH_EXECUTION_ENVELOPE_NON_OPERATIONAL_DECLARATION = (
    "This envelope only packages inputs for a future isolated offline execution. It does not perform or "
    "authorize replay, backtest, walk-forward, performance evaluation, ranking, paper trading, live trading, "
    "exchange connectivity, position management, order submission, or operational strategy execution."
)
OFFLINE_RESEARCH_EXECUTION_ENVELOPE_EXECUTION_ENVIRONMENT_TYPE = "OFFLINE_ISOLATED"
OFFLINE_RESEARCH_EXECUTION_ENVELOPE_NETWORK_POLICY_DENY_ALL = "DENY_ALL"
OFFLINE_RESEARCH_EXECUTION_ENVELOPE_EXCHANGE_POLICY_DENY_ALL = "DENY_ALL"
OFFLINE_RESEARCH_EXECUTION_ENVELOPE_FILESYSTEM_POLICY_ISOLATED_OUTPUT_ONLY = "ISOLATED_OUTPUT_ONLY"
OFFLINE_RESEARCH_EXECUTION_ENVELOPE_PROCESS_POLICY_NO_CHILD_PROCESSES = "NO_CHILD_PROCESSES"
OFFLINE_RESEARCH_EXECUTION_ENVELOPE_OUTPUT_DIRECTORY_MODE_ISOLATED = "ISOLATED"
OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_RESOURCE_LIMITS = {
    "max_runtime_seconds": 86400,
    "max_memory_mb": 8192,
    "max_output_bytes": 10485760,
    "max_event_count": 1000000,
}
OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_EXECUTION_ENVIRONMENT = {
    "environment_type": OFFLINE_RESEARCH_EXECUTION_ENVELOPE_EXECUTION_ENVIRONMENT_TYPE,
    "network_policy": OFFLINE_RESEARCH_EXECUTION_ENVELOPE_NETWORK_POLICY_DENY_ALL,
    "exchange_policy": OFFLINE_RESEARCH_EXECUTION_ENVELOPE_EXCHANGE_POLICY_DENY_ALL,
    "filesystem_policy": OFFLINE_RESEARCH_EXECUTION_ENVELOPE_FILESYSTEM_POLICY_ISOLATED_OUTPUT_ONLY,
    "process_policy": OFFLINE_RESEARCH_EXECUTION_ENVELOPE_PROCESS_POLICY_NO_CHILD_PROCESSES,
}
OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_OUTPUT_POLICY = {
    "output_directory_mode": OFFLINE_RESEARCH_EXECUTION_ENVELOPE_OUTPUT_DIRECTORY_MODE_ISOLATED,
    "overwrite_existing": False,
    "append_only_results": True,
    "temporary_output_allowed": True,
    "external_path_allowed": False,
}


class OfflineResearchExecutionEnvelopeError(HistoricalDataError):
    pass


class OfflineResearchExecutionEnvelopeValidationError(
    OfflineResearchExecutionEnvelopeError,
    HistoricalDataValidationError,
):
    pass


class OfflineResearchExecutionEnvelopeIntegrityError(
    OfflineResearchExecutionEnvelopeError,
    HistoricalDataIntegrityError,
):
    pass


class OfflineResearchExecutionEnvelopePersistenceError(OfflineResearchExecutionEnvelopeError):
    pass


class OfflineResearchExecutionEnvelopeConflictError(
    OfflineResearchExecutionEnvelopeError,
    HistoricalDataConflictError,
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        serialize_value(_thaw_read_only_value(payload)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash_payload(payload: Any) -> str:
    try:
        return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    except TypeError as exc:
        raise OfflineResearchExecutionEnvelopeValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineResearchExecutionEnvelopeValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchExecutionEnvelopeValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_commit_sha(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 40 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchExecutionEnvelopeValidationError(
            f"{field_name} must be a 40-character hex git commit sha."
        )
    return digest


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineResearchExecutionEnvelopeValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_positive_int(value: Any, field_name: str) -> int:
    normalized = _require_int(value, field_name)
    if normalized <= 0:
        raise OfflineResearchExecutionEnvelopeValidationError(f"{field_name} must be greater than zero.")
    return normalized


def _require_non_negative_int(value: Any, field_name: str) -> int:
    normalized = _require_int(value, field_name)
    if normalized < 0:
        raise OfflineResearchExecutionEnvelopeValidationError(f"{field_name} must not be negative.")
    return normalized


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineResearchExecutionEnvelopeValidationError(f"{field_name} must be a boolean.")
    return value


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineResearchExecutionEnvelopeValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise OfflineResearchExecutionEnvelopeValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise OfflineResearchExecutionEnvelopeValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineResearchExecutionEnvelopeValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _is_temporary_pytest_path(path: Path) -> bool:
    return any(part == ".pytest_tmp" for part in path.parts)


def _ensure_registry_path(path: str | Path, *, field_name: str) -> Path:
    registry_path = Path(path)
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
    if isinstance(value, set) or isinstance(value, frozenset):
        thawed_items = [_thaw_read_only_value(item) for item in value]
        return tuple(sorted(thawed_items, key=_canonical_json))
    return value


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise OfflineResearchExecutionEnvelopeValidationError(
            "offline research execution envelope registry is missing."
        )
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise OfflineResearchExecutionEnvelopeValidationError(
            "offline research execution envelope registry is empty."
        )
    try:
        return json.loads(text)
    except Exception as exc:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "offline research execution envelope registry is invalid JSON."
        ) from exc


def _write_json_atomic(path: Path, payload: Any) -> None:
    canonical = _canonical_json(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") == canonical:
            return
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{id(payload)}.tmp")
    try:
        tmp_path.write_text(canonical, encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise OfflineResearchExecutionEnvelopePersistenceError(
            "failed to write offline research execution envelope registry atomically."
        ) from exc


def _normalize_resource_limits(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    payload = dict(OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_RESOURCE_LIMITS if value is None else value)
    allowed = set(OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_RESOURCE_LIMITS)
    extra = sorted(set(payload) - allowed)
    if extra:
        raise OfflineResearchExecutionEnvelopeValidationError(
            f"unexpected resource_limits fields: {', '.join(extra)}."
        )
    try:
        normalized = {
            "max_runtime_seconds": _require_positive_int(payload["max_runtime_seconds"], "max_runtime_seconds"),
            "max_memory_mb": _require_positive_int(payload["max_memory_mb"], "max_memory_mb"),
            "max_output_bytes": _require_positive_int(payload["max_output_bytes"], "max_output_bytes"),
            "max_event_count": _require_positive_int(payload["max_event_count"], "max_event_count"),
        }
    except KeyError as exc:
        raise OfflineResearchExecutionEnvelopeValidationError(
            f"{exc.args[0]} is required in resource_limits."
        ) from exc
    return _freeze_read_only_value(normalized)


def _normalize_execution_environment(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    payload = dict(OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_EXECUTION_ENVIRONMENT if value is None else value)
    allowed = set(OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_EXECUTION_ENVIRONMENT)
    extra = sorted(set(payload) - allowed)
    if extra:
        raise OfflineResearchExecutionEnvelopeValidationError(
            f"unexpected execution_environment fields: {', '.join(extra)}."
        )
    try:
        normalized = {
            "environment_type": _require_str(payload["environment_type"], "environment_type").upper(),
            "network_policy": _require_str(payload["network_policy"], "network_policy").upper(),
            "exchange_policy": _require_str(payload["exchange_policy"], "exchange_policy").upper(),
            "filesystem_policy": _require_str(payload["filesystem_policy"], "filesystem_policy").upper(),
            "process_policy": _require_str(payload["process_policy"], "process_policy").upper(),
        }
    except KeyError as exc:
        raise OfflineResearchExecutionEnvelopeValidationError(
            f"{exc.args[0]} is required in execution_environment."
        ) from exc
    if normalized["environment_type"] != OFFLINE_RESEARCH_EXECUTION_ENVELOPE_EXECUTION_ENVIRONMENT_TYPE:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "environment_type must remain OFFLINE_ISOLATED."
        )
    if normalized["network_policy"] != OFFLINE_RESEARCH_EXECUTION_ENVELOPE_NETWORK_POLICY_DENY_ALL:
        raise OfflineResearchExecutionEnvelopeValidationError("network_policy must remain DENY_ALL.")
    if normalized["exchange_policy"] != OFFLINE_RESEARCH_EXECUTION_ENVELOPE_EXCHANGE_POLICY_DENY_ALL:
        raise OfflineResearchExecutionEnvelopeValidationError("exchange_policy must remain DENY_ALL.")
    if normalized["filesystem_policy"] != OFFLINE_RESEARCH_EXECUTION_ENVELOPE_FILESYSTEM_POLICY_ISOLATED_OUTPUT_ONLY:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "filesystem_policy must remain ISOLATED_OUTPUT_ONLY."
        )
    if normalized["process_policy"] != OFFLINE_RESEARCH_EXECUTION_ENVELOPE_PROCESS_POLICY_NO_CHILD_PROCESSES:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "process_policy must remain NO_CHILD_PROCESSES."
        )
    return _freeze_read_only_value(normalized)


def _normalize_output_policy(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    payload = dict(OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_OUTPUT_POLICY if value is None else value)
    allowed = set(OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_OUTPUT_POLICY)
    extra = sorted(set(payload) - allowed)
    if extra:
        raise OfflineResearchExecutionEnvelopeValidationError(
            f"unexpected output_policy fields: {', '.join(extra)}."
        )
    try:
        normalized = {
            "output_directory_mode": _require_str(payload["output_directory_mode"], "output_directory_mode").upper(),
            "overwrite_existing": _require_bool(payload["overwrite_existing"], "overwrite_existing"),
            "append_only_results": _require_bool(payload["append_only_results"], "append_only_results"),
            "temporary_output_allowed": _require_bool(payload["temporary_output_allowed"], "temporary_output_allowed"),
            "external_path_allowed": _require_bool(payload["external_path_allowed"], "external_path_allowed"),
        }
    except KeyError as exc:
        raise OfflineResearchExecutionEnvelopeValidationError(
            f"{exc.args[0]} is required in output_policy."
        ) from exc
    if normalized["output_directory_mode"] != OFFLINE_RESEARCH_EXECUTION_ENVELOPE_OUTPUT_DIRECTORY_MODE_ISOLATED:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "output_directory_mode must remain ISOLATED."
        )
    if normalized["overwrite_existing"] is not False:
        raise OfflineResearchExecutionEnvelopeValidationError("overwrite_existing must be false.")
    if normalized["append_only_results"] is not True:
        raise OfflineResearchExecutionEnvelopeValidationError("append_only_results must be true.")
    if normalized["temporary_output_allowed"] is not True:
        raise OfflineResearchExecutionEnvelopeValidationError("temporary_output_allowed must be true.")
    if normalized["external_path_allowed"] is not False:
        raise OfflineResearchExecutionEnvelopeValidationError("external_path_allowed must be false.")
    return _freeze_read_only_value(normalized)


def _normalize_strategy_contract_snapshot(strategy_contract: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(strategy_contract, Mapping):
        raise OfflineResearchExecutionEnvelopeValidationError("strategy_contract snapshot must be a mapping.")
    payload = dict(strategy_contract)
    payload.pop("contract_hash", None)
    return _freeze_read_only_value(payload)


def _normalize_parameter_set(experiment_contract_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(experiment_contract_payload, Mapping):
        raise OfflineResearchExecutionEnvelopeValidationError("parameter_set must be a mapping.")
    return _freeze_read_only_value(dict(experiment_contract_payload))


def _experiment_contract_parameter_set(
    experiment_contract: phase45.phase40_contract.OfflineResearchExperimentContract if hasattr(phase45, "phase40_contract") else Any,
) -> Mapping[str, Any]:
    payload = dict(experiment_contract.as_dict())
    payload.pop("contract_hash", None)
    return _freeze_read_only_value(payload)


def _authorization_from_source(
    *,
    authorization: phase45.OfflineResearchExecutionAuthorization | Mapping[str, Any] | None,
    authorization_registry_file: str | Path,
    plan_id: str,
) -> phase45.OfflineResearchExecutionAuthorization:
    registry = phase45.load_offline_research_execution_authorization_registry(authorization_registry_file)
    current_candidates = [record for record in registry.records if record.plan_id == plan_id]
    if not current_candidates:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "authorization for the plan was not found in the registry."
        )
    current = max(current_candidates, key=lambda record: record.authorization_number)
    if current.decision != phase45.OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_AUTHORIZED:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "authorization registry is not in the authorized state."
        )
    if current.allow_future_offline_execution is not True:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "authorization registry is not in the authorized state."
        )
    if authorization is None:
        return current
    if isinstance(authorization, Mapping):
        authorization = phase45.OfflineResearchExecutionAuthorization.from_dict(dict(authorization))
    if not isinstance(authorization, phase45.OfflineResearchExecutionAuthorization):
        raise OfflineResearchExecutionEnvelopeValidationError(
            "a verified phase 45 authorization is required."
        )
    if authorization.authorization_id != current.authorization_id or authorization.authorization_hash != current.authorization_hash:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "authorization is not the current effective state for the plan."
        )
    if authorization.decision != phase45.OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_AUTHORIZED:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "authorization must be authorized for future offline execution."
        )
    if authorization.allow_future_offline_execution is not True:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "authorization must allow future offline execution."
        )
    return authorization


def _plan_from_source(
    *,
    plan: phase43_plan.OfflineResearchExperimentExecutionPlan | Mapping[str, Any] | None,
    plan_registry_file: str | Path | None = None,
) -> phase43_plan.OfflineResearchExperimentExecutionPlan:
    if plan is None:
        raise OfflineResearchExecutionEnvelopeValidationError("a verified phase 43 plan is required.")
    if isinstance(plan, Mapping):
        plan = phase43_plan.OfflineResearchExperimentExecutionPlan.from_dict(dict(plan))
    if not isinstance(plan, phase43_plan.OfflineResearchExperimentExecutionPlan):
        raise OfflineResearchExecutionEnvelopeValidationError("a verified phase 43 plan is required.")
    if plan_registry_file is None:
        return plan
    registry = phase43_plan.load_offline_research_experiment_execution_plan_registry(plan_registry_file)
    current = registry.plan_by_id(plan.plan_id)
    if current.as_dict() != plan.as_dict():
        raise OfflineResearchExecutionEnvelopeValidationError(
            "plan is not the current effective state for the plan registry."
        )
    return plan


def _evidence_snapshot(
    evidence: phase44_fixture.CanonicalOfflineResearchEvidenceVerification,
) -> Mapping[str, Any]:
    if not isinstance(evidence, phase44_fixture.CanonicalOfflineResearchEvidenceVerification):
        raise OfflineResearchExecutionEnvelopeValidationError(
            "a verified phase 44 evidence package is required."
        )
    return _freeze_read_only_value(dict(phase45._evidence_snapshot(evidence)))  # type: ignore[attr-defined]


def _current_material_signature(envelope: "OfflineResearchExecutionEnvelope") -> str:
    payload = envelope.canonical_payload(include_envelope_hash=False)
    payload = dict(payload)
    payload.pop("created_at_utc", None)
    payload.pop("envelope_number", None)
    payload.pop("previous_envelope_id", None)
    payload.pop("previous_envelope_hash", None)
    payload.pop("envelope_id", None)
    payload.pop("envelope_hash", None)
    return _canonical_json(payload)


@dataclass(frozen=True, slots=True)
class OfflineResearchExecutionEnvelope:
    schema_version: int = OFFLINE_RESEARCH_EXECUTION_ENVELOPE_SCHEMA_VERSION
    envelope_id: str = ""
    envelope_number: int = 0
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    experiment_id: str = ""
    experiment_registration_hash: str = ""
    execution_id: str = ""
    execution_registration_hash: str = ""
    plan_id: str = ""
    plan_hash: str = ""
    evidence_id: str = ""
    evidence_hash: str = ""
    authorization_id: str = ""
    authorization_hash: str = ""
    artifact_reference_id: str = ""
    artifact_reference_hash: str = ""
    strategy_id: str = ""
    strategy_version: str = ""
    strategy_fingerprint: str = ""
    provider_name: str = ""
    market_type: str = ""
    instrument: str = ""
    canonical_symbol: str = ""
    interval: str = ""
    requested_start_inclusive_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    requested_end_exclusive_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expected_candle_count: int = 0
    dataset_sha256: str = ""
    manifest_sha256: str = ""
    manifest_hash: str = ""
    source_commit: str = ""
    source_branch: str = ""
    random_seed: int = 0
    parameter_set: Mapping[str, Any] = field(default_factory=dict, repr=False)
    resource_limits: Mapping[str, Any] = field(default_factory=dict, repr=False)
    execution_environment: Mapping[str, Any] = field(default_factory=dict, repr=False)
    output_policy: Mapping[str, Any] = field(default_factory=dict, repr=False)
    authorization_snapshot: Mapping[str, Any] = field(default_factory=dict, repr=False)
    plan_snapshot: Mapping[str, Any] = field(default_factory=dict, repr=False)
    evidence_snapshot: Mapping[str, Any] = field(default_factory=dict, repr=False)
    offline_only: bool = True
    network_access_allowed: bool = False
    exchange_connectivity_allowed: bool = False
    paper_trading_allowed: bool = False
    live_trading_allowed: bool = False
    order_submission_allowed: bool = False
    strategy_execution_allowed: bool = False
    future_offline_execution_authorized: bool = True
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_RESEARCH_EXECUTION_ENVELOPE_NON_OPERATIONAL_DECLARATION
    previous_envelope_id: str | None = None
    previous_envelope_hash: str | None = None
    envelope_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "envelope_id", _require_hex_digest(self.envelope_id, "envelope_id") if self.envelope_id else "")
        object.__setattr__(self, "envelope_number", _require_positive_int(self.envelope_number, "envelope_number"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "experiment_id", _require_str(self.experiment_id, "experiment_id"))
        object.__setattr__(self, "experiment_registration_hash", _require_hex_digest(self.experiment_registration_hash, "experiment_registration_hash"))
        object.__setattr__(self, "execution_id", _require_str(self.execution_id, "execution_id"))
        object.__setattr__(self, "execution_registration_hash", _require_hex_digest(self.execution_registration_hash, "execution_registration_hash"))
        object.__setattr__(self, "plan_id", _require_str(self.plan_id, "plan_id"))
        object.__setattr__(self, "plan_hash", _require_hex_digest(self.plan_hash, "plan_hash"))
        object.__setattr__(self, "evidence_id", _require_str(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "evidence_hash", _require_hex_digest(self.evidence_hash, "evidence_hash"))
        object.__setattr__(self, "authorization_id", _require_hex_digest(self.authorization_id, "authorization_id"))
        object.__setattr__(self, "authorization_hash", _require_hex_digest(self.authorization_hash, "authorization_hash"))
        object.__setattr__(self, "artifact_reference_id", _require_hex_digest(self.artifact_reference_id, "artifact_reference_id"))
        object.__setattr__(self, "artifact_reference_hash", _require_hex_digest(self.artifact_reference_hash, "artifact_reference_hash"))
        object.__setattr__(self, "strategy_id", _require_str(self.strategy_id, "strategy_id"))
        object.__setattr__(self, "strategy_version", _require_str(self.strategy_version, "strategy_version"))
        object.__setattr__(self, "strategy_fingerprint", _require_hex_digest(self.strategy_fingerprint, "strategy_fingerprint"))
        object.__setattr__(self, "provider_name", _require_str(self.provider_name, "provider_name").upper())
        object.__setattr__(self, "market_type", _require_str(self.market_type, "market_type").lower())
        object.__setattr__(self, "instrument", _require_str(self.instrument, "instrument").upper())
        object.__setattr__(self, "canonical_symbol", _require_str(self.canonical_symbol, "canonical_symbol").upper())
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "requested_start_inclusive_utc", _require_utc_datetime(self.requested_start_inclusive_utc, "requested_start_inclusive_utc"))
        object.__setattr__(self, "requested_end_exclusive_utc", _require_utc_datetime(self.requested_end_exclusive_utc, "requested_end_exclusive_utc"))
        object.__setattr__(self, "expected_candle_count", _require_positive_int(self.expected_candle_count, "expected_candle_count"))
        object.__setattr__(self, "dataset_sha256", _require_hex_digest(self.dataset_sha256, "dataset_sha256"))
        object.__setattr__(self, "manifest_sha256", _require_hex_digest(self.manifest_sha256, "manifest_sha256"))
        object.__setattr__(self, "manifest_hash", _require_hex_digest(self.manifest_hash, "manifest_hash"))
        object.__setattr__(self, "source_commit", _require_commit_sha(self.source_commit, "source_commit"))
        object.__setattr__(self, "source_branch", _require_str(self.source_branch, "source_branch"))
        object.__setattr__(self, "random_seed", _require_non_negative_int(self.random_seed, "random_seed"))
        if not isinstance(self.parameter_set, Mapping):
            raise OfflineResearchExecutionEnvelopeValidationError("parameter_set must be a mapping.")
        if not isinstance(self.resource_limits, Mapping):
            raise OfflineResearchExecutionEnvelopeValidationError("resource_limits must be a mapping.")
        if not isinstance(self.execution_environment, Mapping):
            raise OfflineResearchExecutionEnvelopeValidationError("execution_environment must be a mapping.")
        if not isinstance(self.output_policy, Mapping):
            raise OfflineResearchExecutionEnvelopeValidationError("output_policy must be a mapping.")
        if not isinstance(self.authorization_snapshot, Mapping):
            raise OfflineResearchExecutionEnvelopeValidationError("authorization_snapshot must be a mapping.")
        if not isinstance(self.plan_snapshot, Mapping):
            raise OfflineResearchExecutionEnvelopeValidationError("plan_snapshot must be a mapping.")
        if not isinstance(self.evidence_snapshot, Mapping):
            raise OfflineResearchExecutionEnvelopeValidationError("evidence_snapshot must be a mapping.")
        object.__setattr__(self, "parameter_set", _freeze_read_only_value(dict(self.parameter_set)))
        object.__setattr__(self, "resource_limits", _normalize_resource_limits(self.resource_limits))
        object.__setattr__(self, "execution_environment", _normalize_execution_environment(self.execution_environment))
        object.__setattr__(self, "output_policy", _normalize_output_policy(self.output_policy))
        object.__setattr__(self, "authorization_snapshot", _freeze_read_only_value(dict(self.authorization_snapshot)))
        object.__setattr__(self, "plan_snapshot", _freeze_read_only_value(dict(self.plan_snapshot)))
        object.__setattr__(self, "evidence_snapshot", _freeze_read_only_value(dict(self.evidence_snapshot)))
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "network_access_allowed", _require_bool(self.network_access_allowed, "network_access_allowed"))
        object.__setattr__(self, "exchange_connectivity_allowed", _require_bool(self.exchange_connectivity_allowed, "exchange_connectivity_allowed"))
        object.__setattr__(self, "paper_trading_allowed", _require_bool(self.paper_trading_allowed, "paper_trading_allowed"))
        object.__setattr__(self, "live_trading_allowed", _require_bool(self.live_trading_allowed, "live_trading_allowed"))
        object.__setattr__(self, "order_submission_allowed", _require_bool(self.order_submission_allowed, "order_submission_allowed"))
        object.__setattr__(self, "strategy_execution_allowed", _require_bool(self.strategy_execution_allowed, "strategy_execution_allowed"))
        object.__setattr__(self, "future_offline_execution_authorized", _require_bool(self.future_offline_execution_authorized, "future_offline_execution_authorized"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        object.__setattr__(self, "previous_envelope_id", _require_hex_digest(self.previous_envelope_id, "previous_envelope_id") if self.previous_envelope_id else None)
        object.__setattr__(self, "previous_envelope_hash", _require_hex_digest(self.previous_envelope_hash, "previous_envelope_hash") if self.previous_envelope_hash else None)

        if self.schema_version != OFFLINE_RESEARCH_EXECUTION_ENVELOPE_SCHEMA_VERSION:
            raise OfflineResearchExecutionEnvelopeValidationError("schema_version must be 1.")
        if self.offline_only is not True:
            raise OfflineResearchExecutionEnvelopeValidationError("offline_only must be true.")
        if self.future_offline_execution_authorized is not True:
            raise OfflineResearchExecutionEnvelopeValidationError(
                "future_offline_execution_authorized must be true."
            )
        if self.historical_research_only is not True:
            raise OfflineResearchExecutionEnvelopeValidationError("historical_research_only must be true.")
        if self.network_access_allowed is not False:
            raise OfflineResearchExecutionEnvelopeValidationError("network_access_allowed must be false.")
        if self.exchange_connectivity_allowed is not False:
            raise OfflineResearchExecutionEnvelopeValidationError(
                "exchange_connectivity_allowed must be false."
            )
        if self.paper_trading_allowed is not False:
            raise OfflineResearchExecutionEnvelopeValidationError("paper_trading_allowed must be false.")
        if self.live_trading_allowed is not False:
            raise OfflineResearchExecutionEnvelopeValidationError("live_trading_allowed must be false.")
        if self.order_submission_allowed is not False:
            raise OfflineResearchExecutionEnvelopeValidationError("order_submission_allowed must be false.")
        if self.strategy_execution_allowed is not False:
            raise OfflineResearchExecutionEnvelopeValidationError("strategy_execution_allowed must be false.")
        if self.operational_evidence is not False:
            raise OfflineResearchExecutionEnvelopeValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchExecutionEnvelopeValidationError("paper_promotion_eligible must be false.")
        if self.non_operational_declaration != OFFLINE_RESEARCH_EXECUTION_ENVELOPE_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchExecutionEnvelopeValidationError(
                "non_operational_declaration diverges from the envelope contract."
            )

        strategy_contract_snapshot = self.parameter_set.get("strategy_contract")
        if not isinstance(strategy_contract_snapshot, Mapping):
            raise OfflineResearchExecutionEnvelopeValidationError(
                "parameter_set.strategy_contract is required."
            )
        if self.strategy_id != _require_str(strategy_contract_snapshot["strategy_id"], "strategy_id"):
            raise OfflineResearchExecutionEnvelopeIntegrityError("strategy_id mismatch.")
        if self.strategy_version != _require_str(strategy_contract_snapshot["strategy_version"], "strategy_version"):
            raise OfflineResearchExecutionEnvelopeIntegrityError("strategy_version mismatch.")
        if self.strategy_fingerprint != _require_hex_digest(strategy_contract_snapshot["contract_hash"], "strategy_fingerprint"):
            raise OfflineResearchExecutionEnvelopeIntegrityError("strategy_fingerprint mismatch.")
        if self.provider_name != _require_str(strategy_contract_snapshot["provider_name"], "provider_name").upper():
            raise OfflineResearchExecutionEnvelopeIntegrityError("provider_name mismatch.")
        if self.market_type != _require_str(strategy_contract_snapshot["market_type"], "market_type").lower():
            raise OfflineResearchExecutionEnvelopeIntegrityError("market_type mismatch.")
        if self.instrument != _require_str(strategy_contract_snapshot["symbol"], "instrument").upper():
            raise OfflineResearchExecutionEnvelopeIntegrityError("instrument mismatch.")
        if self.canonical_symbol != _require_str(strategy_contract_snapshot["canonical_symbol"], "canonical_symbol").upper():
            raise OfflineResearchExecutionEnvelopeIntegrityError("canonical_symbol mismatch.")
        if self.interval != _require_str(strategy_contract_snapshot["interval"], "interval"):
            raise OfflineResearchExecutionEnvelopeIntegrityError("interval mismatch.")
        if self.requested_start_inclusive_utc != _require_utc_datetime(
            strategy_contract_snapshot["requested_start_inclusive_utc"],
            "requested_start_inclusive_utc",
        ):
            raise OfflineResearchExecutionEnvelopeIntegrityError(
                "requested_start_inclusive_utc mismatch."
            )
        if self.requested_end_exclusive_utc != _require_utc_datetime(
            strategy_contract_snapshot["requested_end_exclusive_utc"],
            "requested_end_exclusive_utc",
        ):
            raise OfflineResearchExecutionEnvelopeIntegrityError("requested_end_exclusive_utc mismatch.")
        if self.expected_candle_count != _require_positive_int(
            strategy_contract_snapshot["expected_candle_count"],
            "expected_candle_count",
        ):
            raise OfflineResearchExecutionEnvelopeIntegrityError("expected_candle_count mismatch.")

        expected_envelope_id = _hash_payload(self._envelope_id_payload())
        if self.envelope_id:
            if self.envelope_id != expected_envelope_id:
                raise OfflineResearchExecutionEnvelopeIntegrityError("envelope_id mismatch.")
        else:
            object.__setattr__(self, "envelope_id", expected_envelope_id)

        expected_envelope_hash = _hash_payload(self.canonical_payload(include_envelope_hash=False))
        if self.envelope_hash:
            if self.envelope_hash != expected_envelope_hash:
                raise OfflineResearchExecutionEnvelopeIntegrityError("envelope_hash mismatch.")
        else:
            object.__setattr__(self, "envelope_hash", expected_envelope_hash)

    def _envelope_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "envelope_number": self.envelope_number,
            "created_at_utc": _utc_iso(self.created_at_utc),
            "experiment_id": self.experiment_id,
            "experiment_registration_hash": self.experiment_registration_hash,
            "execution_id": self.execution_id,
            "execution_registration_hash": self.execution_registration_hash,
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "evidence_id": self.evidence_id,
            "evidence_hash": self.evidence_hash,
            "authorization_id": self.authorization_id,
            "authorization_hash": self.authorization_hash,
            "artifact_reference_id": self.artifact_reference_id,
            "artifact_reference_hash": self.artifact_reference_hash,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_fingerprint": self.strategy_fingerprint,
            "provider_name": self.provider_name,
            "market_type": self.market_type,
            "instrument": self.instrument,
            "canonical_symbol": self.canonical_symbol,
            "interval": self.interval,
            "requested_start_inclusive_utc": _utc_iso(self.requested_start_inclusive_utc),
            "requested_end_exclusive_utc": _utc_iso(self.requested_end_exclusive_utc),
            "expected_candle_count": self.expected_candle_count,
            "dataset_sha256": self.dataset_sha256,
            "manifest_sha256": self.manifest_sha256,
            "manifest_hash": self.manifest_hash,
            "source_commit": self.source_commit,
            "source_branch": self.source_branch,
            "random_seed": self.random_seed,
            "parameter_set": _thaw_read_only_value(self.parameter_set),
            "resource_limits": _thaw_read_only_value(self.resource_limits),
            "execution_environment": _thaw_read_only_value(self.execution_environment),
            "output_policy": _thaw_read_only_value(self.output_policy),
            "authorization_snapshot": _thaw_read_only_value(self.authorization_snapshot),
            "plan_snapshot": _thaw_read_only_value(self.plan_snapshot),
            "evidence_snapshot": _thaw_read_only_value(self.evidence_snapshot),
            "offline_only": self.offline_only,
            "network_access_allowed": self.network_access_allowed,
            "exchange_connectivity_allowed": self.exchange_connectivity_allowed,
            "paper_trading_allowed": self.paper_trading_allowed,
            "live_trading_allowed": self.live_trading_allowed,
            "order_submission_allowed": self.order_submission_allowed,
            "strategy_execution_allowed": self.strategy_execution_allowed,
            "future_offline_execution_authorized": self.future_offline_execution_authorized,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
            "previous_envelope_id": self.previous_envelope_id,
            "previous_envelope_hash": self.previous_envelope_hash,
        }

    def canonical_payload(self, *, include_envelope_hash: bool = True) -> dict[str, Any]:
        payload = self._envelope_id_payload()
        payload["envelope_id"] = self.envelope_id
        if include_envelope_hash:
            payload["envelope_hash"] = self.envelope_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_envelope_hash=True))

    @property
    def material_signature(self) -> str:
        payload = self.canonical_payload(include_envelope_hash=False)
        payload = dict(payload)
        payload.pop("created_at_utc", None)
        payload.pop("envelope_number", None)
        payload.pop("previous_envelope_id", None)
        payload.pop("previous_envelope_hash", None)
        payload.pop("envelope_id", None)
        return _canonical_json(payload)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfflineResearchExecutionEnvelope":
        if not isinstance(data, Mapping):
            raise OfflineResearchExecutionEnvelopeValidationError(
                "offline research execution envelope must be a mapping."
            )
        mapping = dict(data)
        allowed = {
            "schema_version",
            "envelope_id",
            "envelope_number",
            "created_at_utc",
            "experiment_id",
            "experiment_registration_hash",
            "execution_id",
            "execution_registration_hash",
            "plan_id",
            "plan_hash",
            "evidence_id",
            "evidence_hash",
            "authorization_id",
            "authorization_hash",
            "artifact_reference_id",
            "artifact_reference_hash",
            "strategy_id",
            "strategy_version",
            "strategy_fingerprint",
            "provider_name",
            "market_type",
            "instrument",
            "canonical_symbol",
            "interval",
            "requested_start_inclusive_utc",
            "requested_end_exclusive_utc",
            "expected_candle_count",
            "dataset_sha256",
            "manifest_sha256",
            "manifest_hash",
            "source_commit",
            "source_branch",
            "random_seed",
            "parameter_set",
            "resource_limits",
            "execution_environment",
            "output_policy",
            "authorization_snapshot",
            "plan_snapshot",
            "evidence_snapshot",
            "offline_only",
            "network_access_allowed",
            "exchange_connectivity_allowed",
            "paper_trading_allowed",
            "live_trading_allowed",
            "order_submission_allowed",
            "strategy_execution_allowed",
            "future_offline_execution_authorized",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "non_operational_declaration",
            "previous_envelope_id",
            "previous_envelope_hash",
            "envelope_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise OfflineResearchExecutionEnvelopeValidationError(
                f"unexpected offline research execution envelope fields: {', '.join(extra)}."
            )
        try:
            return cls(
                schema_version=mapping.get("schema_version", OFFLINE_RESEARCH_EXECUTION_ENVELOPE_SCHEMA_VERSION),
                envelope_id=mapping.get("envelope_id", ""),
                envelope_number=mapping["envelope_number"],
                created_at_utc=mapping.get("created_at_utc", datetime.now(timezone.utc)),
                experiment_id=mapping["experiment_id"],
                experiment_registration_hash=mapping["experiment_registration_hash"],
                execution_id=mapping["execution_id"],
                execution_registration_hash=mapping["execution_registration_hash"],
                plan_id=mapping["plan_id"],
                plan_hash=mapping["plan_hash"],
                evidence_id=mapping["evidence_id"],
                evidence_hash=mapping["evidence_hash"],
                authorization_id=mapping["authorization_id"],
                authorization_hash=mapping["authorization_hash"],
                artifact_reference_id=mapping["artifact_reference_id"],
                artifact_reference_hash=mapping["artifact_reference_hash"],
                strategy_id=mapping["strategy_id"],
                strategy_version=mapping["strategy_version"],
                strategy_fingerprint=mapping["strategy_fingerprint"],
                provider_name=mapping["provider_name"],
                market_type=mapping["market_type"],
                instrument=mapping["instrument"],
                canonical_symbol=mapping["canonical_symbol"],
                interval=mapping["interval"],
                requested_start_inclusive_utc=mapping["requested_start_inclusive_utc"],
                requested_end_exclusive_utc=mapping["requested_end_exclusive_utc"],
                expected_candle_count=mapping["expected_candle_count"],
                dataset_sha256=mapping["dataset_sha256"],
                manifest_sha256=mapping["manifest_sha256"],
                manifest_hash=mapping["manifest_hash"],
                source_commit=mapping["source_commit"],
                source_branch=mapping["source_branch"],
                random_seed=mapping["random_seed"],
                parameter_set=mapping["parameter_set"],
                resource_limits=mapping["resource_limits"],
                execution_environment=mapping["execution_environment"],
                output_policy=mapping["output_policy"],
                authorization_snapshot=mapping["authorization_snapshot"],
                plan_snapshot=mapping["plan_snapshot"],
                evidence_snapshot=mapping["evidence_snapshot"],
                offline_only=mapping.get("offline_only", True),
                network_access_allowed=mapping.get("network_access_allowed", False),
                exchange_connectivity_allowed=mapping.get("exchange_connectivity_allowed", False),
                paper_trading_allowed=mapping.get("paper_trading_allowed", False),
                live_trading_allowed=mapping.get("live_trading_allowed", False),
                order_submission_allowed=mapping.get("order_submission_allowed", False),
                strategy_execution_allowed=mapping.get("strategy_execution_allowed", False),
                future_offline_execution_authorized=mapping.get("future_offline_execution_authorized", True),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                non_operational_declaration=mapping.get(
                    "non_operational_declaration",
                    OFFLINE_RESEARCH_EXECUTION_ENVELOPE_NON_OPERATIONAL_DECLARATION,
                ),
                previous_envelope_id=mapping.get("previous_envelope_id"),
                previous_envelope_hash=mapping.get("previous_envelope_hash"),
                envelope_hash=mapping.get("envelope_hash", ""),
            )
        except KeyError as exc:
            raise OfflineResearchExecutionEnvelopeValidationError(
                "offline research execution envelope is incomplete."
            ) from exc


def build_offline_research_execution_envelope(
    *,
    plan: phase43_plan.OfflineResearchExperimentExecutionPlan | Mapping[str, Any],
    evidence: phase44_fixture.CanonicalOfflineResearchEvidenceVerification,
    authorization: phase45.OfflineResearchExecutionAuthorization | Mapping[str, Any] | None = None,
    authorization_registry_file: str | Path | None = None,
    plan_registry_file: str | Path | None = None,
    random_seed: int,
    created_at_utc: datetime,
    source_commit_sha: str | None = None,
    source_branch: str | None = None,
    resource_limits: Mapping[str, Any] | None = None,
    execution_environment: Mapping[str, Any] | None = None,
    output_policy: Mapping[str, Any] | None = None,
    previous_envelope: OfflineResearchExecutionEnvelope | Mapping[str, Any] | None = None,
    envelope_number: int | None = None,
) -> OfflineResearchExecutionEnvelope:
    resolved_plan = _plan_from_source(plan=plan, plan_registry_file=plan_registry_file)
    if authorization_registry_file is None:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "authorization_registry_file is required."
        )
    resolved_authorization = _authorization_from_source(
        authorization=authorization,
        authorization_registry_file=authorization_registry_file,
        plan_id=resolved_plan.plan_id,
    )
    if resolved_authorization.plan_id != resolved_plan.plan_id:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "authorization and plan must refer to the same plan."
        )
    if resolved_authorization.execution_id != resolved_plan.execution_id:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "authorization and plan must refer to the same execution."
        )
    if resolved_authorization.experiment_id != resolved_plan.experiment_id:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "authorization and plan must refer to the same experiment."
        )
    if not isinstance(evidence, phase44_fixture.CanonicalOfflineResearchEvidenceVerification):
        raise OfflineResearchExecutionEnvelopeValidationError(
            "a verified phase 44 evidence package is required."
        )
    if resolved_plan.experiment_id != evidence.experiment_contract.experiment_id:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "plan and evidence must refer to the same experiment contract."
        )
    if resolved_plan.execution_hash != evidence.execution_registry.records[0].execution_hash:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "plan and evidence must refer to the same execution registry record."
        )
    artifact_reference = evidence.artifact_reference
    artifact_report = artifact_reference.registry_report
    authorization_artifact_snapshot = resolved_authorization.evidence_snapshot.get("artifact_reference")
    if not isinstance(authorization_artifact_snapshot, Mapping):
        raise OfflineResearchExecutionEnvelopeValidationError(
            "authorization evidence snapshot is incomplete."
        )
    if _require_str(authorization_artifact_snapshot["artifact_id"], "artifact_id") != artifact_report.artifact_id:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "authorization and evidence must refer to the same artifact reference."
        )
    if _require_hex_digest(authorization_artifact_snapshot["dataset_hash"], "dataset_hash") != artifact_report.dataset_sha256:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "authorization and evidence must refer to the same dataset hash."
        )
    if _require_hex_digest(authorization_artifact_snapshot["manifest_sha256"], "manifest_sha256") != artifact_report.manifest_sha256:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "authorization and evidence must refer to the same manifest file hash."
        )
    if _require_hex_digest(authorization_artifact_snapshot["manifest_hash"], "manifest_hash") != artifact_report.manifest_hash:
        raise OfflineResearchExecutionEnvelopeValidationError(
            "authorization and evidence must refer to the same manifest hash."
        )
    if source_commit_sha is None:
        source_commit_sha = resolved_plan.source_commit_sha
    if source_branch is None:
        source_branch = resolved_plan.source_branch

    authorization_snapshot = _freeze_read_only_value(dict(resolved_authorization.as_dict()))
    plan_snapshot = _freeze_read_only_value(dict(resolved_plan.as_dict()))
    evidence_snapshot = _evidence_snapshot(evidence)
    parameter_set = _normalize_parameter_set({
        key: value for key, value in evidence.experiment_contract.as_dict().items() if key != "contract_hash"
    })
    strategy_contract_snapshot = parameter_set["strategy_contract"]
    if not isinstance(strategy_contract_snapshot, Mapping):
        raise OfflineResearchExecutionEnvelopeValidationError("parameter_set.strategy_contract must be a mapping.")

    derived_previous = None
    if previous_envelope is not None:
        if isinstance(previous_envelope, Mapping):
            previous_envelope = OfflineResearchExecutionEnvelope.from_dict(dict(previous_envelope))
        if not isinstance(previous_envelope, OfflineResearchExecutionEnvelope):
            raise OfflineResearchExecutionEnvelopeValidationError(
                "previous_envelope must be a verified envelope."
            )
        if previous_envelope.plan_id != resolved_plan.plan_id:
            raise OfflineResearchExecutionEnvelopeValidationError(
                "previous_envelope must belong to the same plan."
            )
        if envelope_number is None:
            envelope_number = previous_envelope.envelope_number + 1
        derived_previous = previous_envelope
    if envelope_number is None:
        envelope_number = 1

    if envelope_number == 1:
        if derived_previous is not None:
            raise OfflineResearchExecutionEnvelopeValidationError(
                "previous_envelope is not allowed for envelope_number 1."
            )
        previous_envelope_id = None
        previous_envelope_hash = None
    else:
        if derived_previous is None:
            raise OfflineResearchExecutionEnvelopeValidationError(
                "previous_envelope is required for envelope_number greater than 1."
            )
        previous_envelope_id = derived_previous.envelope_id
        previous_envelope_hash = derived_previous.envelope_hash
        if envelope_number != derived_previous.envelope_number + 1:
            raise OfflineResearchExecutionEnvelopeValidationError(
                "envelope_number must follow the previous envelope sequentially."
            )

    envelope = OfflineResearchExecutionEnvelope(
        envelope_number=envelope_number,
        created_at_utc=created_at_utc,
        experiment_id=resolved_plan.experiment_id,
        experiment_registration_hash=resolved_plan.experiment_registration_hash,
        execution_id=resolved_plan.execution_id,
        execution_registration_hash=resolved_plan.execution_hash,
        plan_id=resolved_plan.plan_id,
        plan_hash=resolved_plan.plan_hash,
        evidence_id=evidence.fixture.fixture_version,
        evidence_hash=_hash_payload(evidence_snapshot),
        authorization_id=resolved_authorization.authorization_id,
        authorization_hash=resolved_authorization.authorization_hash,
        artifact_reference_id=artifact_report.artifact_id,
        artifact_reference_hash=evidence.artifact_reference_hash,
        strategy_id=_require_str(strategy_contract_snapshot["strategy_id"], "strategy_id"),
        strategy_version=_require_str(strategy_contract_snapshot["strategy_version"], "strategy_version"),
        strategy_fingerprint=_require_hex_digest(strategy_contract_snapshot["contract_hash"], "strategy_fingerprint"),
        provider_name=_require_str(strategy_contract_snapshot["provider_name"], "provider_name"),
        market_type=_require_str(strategy_contract_snapshot["market_type"], "market_type"),
        instrument=_require_str(strategy_contract_snapshot["symbol"], "instrument"),
        canonical_symbol=_require_str(strategy_contract_snapshot["canonical_symbol"], "canonical_symbol"),
        interval=_require_str(strategy_contract_snapshot["interval"], "interval"),
        requested_start_inclusive_utc=_require_utc_datetime(
            strategy_contract_snapshot["requested_start_inclusive_utc"],
            "requested_start_inclusive_utc",
        ),
        requested_end_exclusive_utc=_require_utc_datetime(
            strategy_contract_snapshot["requested_end_exclusive_utc"],
            "requested_end_exclusive_utc",
        ),
        expected_candle_count=_require_positive_int(
            strategy_contract_snapshot["expected_candle_count"],
            "expected_candle_count",
        ),
        dataset_sha256=artifact_report.dataset_sha256,
        manifest_sha256=artifact_report.manifest_sha256,
        manifest_hash=artifact_report.manifest_hash,
        source_commit=source_commit_sha,
        source_branch=source_branch,
        random_seed=random_seed,
        parameter_set=parameter_set,
        resource_limits=OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_RESOURCE_LIMITS
        if resource_limits is None
        else resource_limits,
        execution_environment=OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_EXECUTION_ENVIRONMENT
        if execution_environment is None
        else execution_environment,
        output_policy=OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_OUTPUT_POLICY
        if output_policy is None
        else output_policy,
        authorization_snapshot=authorization_snapshot,
        plan_snapshot=plan_snapshot,
        evidence_snapshot=evidence_snapshot,
        future_offline_execution_authorized=resolved_authorization.allow_future_offline_execution,
        previous_envelope_id=previous_envelope_id,
        previous_envelope_hash=previous_envelope_hash,
    )
    if envelope.as_dict() != serialize_value(envelope.canonical_payload()):
        raise OfflineResearchExecutionEnvelopeIntegrityError("envelope payload mismatch.")
    return envelope


def verify_offline_research_execution_envelope(envelope: OfflineResearchExecutionEnvelope) -> OfflineResearchExecutionEnvelope:
    if not isinstance(envelope, OfflineResearchExecutionEnvelope):
        raise OfflineResearchExecutionEnvelopeValidationError(
            "offline research execution envelope is required."
        )
    if envelope.as_dict() != serialize_value(envelope.canonical_payload()):
        raise OfflineResearchExecutionEnvelopeIntegrityError("envelope payload mismatch.")
    return envelope


def _record_sort_key(record: OfflineResearchExecutionEnvelope) -> tuple[str, int, str]:
    return (record.plan_id, record.envelope_number, record.envelope_id)


def _validate_chain(records: tuple[OfflineResearchExecutionEnvelope, ...]) -> None:
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    chains: dict[str, list[OfflineResearchExecutionEnvelope]] = {}
    for record in records:
        if record.envelope_id in seen_ids:
            raise OfflineResearchExecutionEnvelopeConflictError("envelope_id conflict.")
        if record.envelope_hash in seen_hashes:
            raise OfflineResearchExecutionEnvelopeConflictError("envelope_hash conflict.")
        seen_ids.add(record.envelope_id)
        seen_hashes.add(record.envelope_hash)
        chains.setdefault(record.plan_id, []).append(record)

    for plan_id, chain in chains.items():
        ordered = sorted(chain, key=_record_sort_key)
        for expected_number, record in enumerate(ordered, start=1):
            if record.envelope_number != expected_number:
                raise OfflineResearchExecutionEnvelopeIntegrityError("envelope_number sequence gap.")
            if expected_number == 1:
                if record.previous_envelope_id is not None or record.previous_envelope_hash is not None:
                    raise OfflineResearchExecutionEnvelopeValidationError(
                        "previous envelope reference is not allowed for envelope_number 1."
                    )
            else:
                previous_record = ordered[expected_number - 2]
                if record.previous_envelope_id != previous_record.envelope_id:
                    raise OfflineResearchExecutionEnvelopeIntegrityError("previous_envelope_id mismatch.")
                if record.previous_envelope_hash != previous_record.envelope_hash:
                    raise OfflineResearchExecutionEnvelopeIntegrityError("previous_envelope_hash mismatch.")
                if previous_record.plan_id != plan_id:
                    raise OfflineResearchExecutionEnvelopeIntegrityError(
                        "previous envelope belongs to a different plan."
                    )
                if record.material_signature != previous_record.material_signature:
                    raise OfflineResearchExecutionEnvelopeIntegrityError(
                        "envelope material diverges within the same plan chain."
                    )


@dataclass(frozen=True, slots=True)
class OfflineResearchExecutionEnvelopeRegistry:
    registry_file: Path = field(default_factory=Path, repr=False)
    schema_version: int = OFFLINE_RESEARCH_EXECUTION_ENVELOPE_SCHEMA_VERSION
    registry_id: str = OFFLINE_RESEARCH_EXECUTION_ENVELOPE_REGISTRY_ID
    registry_version: str = OFFLINE_RESEARCH_EXECUTION_ENVELOPE_REGISTRY_VERSION
    created_at_utc: datetime = field(default_factory=lambda: datetime(1970, 1, 1, tzinfo=timezone.utc))
    updated_at_utc: datetime = field(default_factory=lambda: datetime(1970, 1, 1, tzinfo=timezone.utc))
    records: tuple[OfflineResearchExecutionEnvelope, ...] = field(default_factory=tuple)
    offline_only: bool = True
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_RESEARCH_EXECUTION_ENVELOPE_NON_OPERATIONAL_DECLARATION
    registry_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_file", Path(self.registry_file))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "registry_id", _require_str(self.registry_id, "registry_id"))
        object.__setattr__(self, "registry_version", _require_str(self.registry_version, "registry_version"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "updated_at_utc", _require_utc_datetime(self.updated_at_utc, "updated_at_utc"))
        records = tuple(
            record if isinstance(record, OfflineResearchExecutionEnvelope) else OfflineResearchExecutionEnvelope.from_dict(record)
            for record in self.records
        )
        records = tuple(sorted(records, key=_record_sort_key))
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.schema_version != OFFLINE_RESEARCH_EXECUTION_ENVELOPE_SCHEMA_VERSION:
            raise OfflineResearchExecutionEnvelopeValidationError("schema_version must be 1.")
        if self.registry_id != OFFLINE_RESEARCH_EXECUTION_ENVELOPE_REGISTRY_ID:
            raise OfflineResearchExecutionEnvelopeValidationError(
                "registry_id must remain offline_research_execution_envelope_registry."
            )
        if self.registry_version != OFFLINE_RESEARCH_EXECUTION_ENVELOPE_REGISTRY_VERSION:
            raise OfflineResearchExecutionEnvelopeValidationError(
                "registry_version must remain phase46_offline_execution_envelope_registry_v1."
            )
        if self.offline_only is not True:
            raise OfflineResearchExecutionEnvelopeValidationError("offline_only must be true.")
        if self.historical_research_only is not True:
            raise OfflineResearchExecutionEnvelopeValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchExecutionEnvelopeValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchExecutionEnvelopeValidationError("paper_promotion_eligible must be false.")
        if self.non_operational_declaration != OFFLINE_RESEARCH_EXECUTION_ENVELOPE_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchExecutionEnvelopeValidationError(
                "non_operational_declaration diverges from the envelope contract."
            )
        _validate_chain(records)
        expected_hash = _hash_payload(self.canonical_payload(include_registry_hash=False))
        if self.registry_hash:
            if self.registry_hash != expected_hash:
                raise OfflineResearchExecutionEnvelopeIntegrityError("registry_hash mismatch.")
        else:
            object.__setattr__(self, "registry_hash", expected_hash)

    @property
    def record_count(self) -> int:
        return len(self.records)

    def canonical_payload(self, *, include_registry_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "registry_file": self.registry_file.as_posix(),
            "registry_id": self.registry_id,
            "registry_version": self.registry_version,
            "created_at_utc": _utc_iso(self.created_at_utc),
            "updated_at_utc": _utc_iso(self.updated_at_utc),
            "record_count": self.record_count,
            "records": [record.canonical_payload(include_envelope_hash=True) for record in self.records],
            "offline_only": self.offline_only,
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
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        registry_file: str | Path = Path(),
    ) -> "OfflineResearchExecutionEnvelopeRegistry":
        if not isinstance(data, Mapping):
            raise OfflineResearchExecutionEnvelopeValidationError(
                "offline research execution envelope registry must be a mapping."
            )
        mapping = dict(data)
        allowed = {
            "schema_version",
            "registry_file",
            "registry_id",
            "registry_version",
            "created_at_utc",
            "updated_at_utc",
            "record_count",
            "records",
            "offline_only",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "non_operational_declaration",
            "registry_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise OfflineResearchExecutionEnvelopeValidationError(
                f"unexpected offline research execution envelope registry fields: {', '.join(extra)}."
            )
        if "records" not in mapping:
            raise OfflineResearchExecutionEnvelopeValidationError(
                "offline research execution envelope registry is incomplete."
            )
        try:
            records = tuple(OfflineResearchExecutionEnvelope.from_dict(item) for item in mapping.get("records", ()))
            return cls(
                registry_file=registry_file,
                schema_version=mapping.get("schema_version", OFFLINE_RESEARCH_EXECUTION_ENVELOPE_SCHEMA_VERSION),
                registry_id=mapping.get("registry_id", OFFLINE_RESEARCH_EXECUTION_ENVELOPE_REGISTRY_ID),
                registry_version=mapping.get(
                    "registry_version",
                    OFFLINE_RESEARCH_EXECUTION_ENVELOPE_REGISTRY_VERSION,
                ),
                created_at_utc=mapping.get("created_at_utc", datetime(1970, 1, 1, tzinfo=timezone.utc)),
                updated_at_utc=mapping.get("updated_at_utc", datetime(1970, 1, 1, tzinfo=timezone.utc)),
                records=records,
                offline_only=mapping.get("offline_only", True),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                non_operational_declaration=mapping.get(
                    "non_operational_declaration",
                    OFFLINE_RESEARCH_EXECUTION_ENVELOPE_NON_OPERATIONAL_DECLARATION,
                ),
                registry_hash=mapping.get("registry_hash", ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OfflineResearchExecutionEnvelopeValidationError(
                "offline research execution envelope registry is incomplete."
            ) from exc

    def envelope_by_id(self, envelope_id: str) -> OfflineResearchExecutionEnvelope:
        target = _require_str(envelope_id, "envelope_id").lower()
        for record in self.records:
            if record.envelope_id == target:
                return record
        raise OfflineResearchExecutionEnvelopeValidationError("envelope_id was not found in the registry.")

    def envelope_by_hash(self, envelope_hash: str) -> OfflineResearchExecutionEnvelope:
        target = _require_hex_digest(envelope_hash, "envelope_hash")
        for record in self.records:
            if record.envelope_hash == target:
                return record
        raise OfflineResearchExecutionEnvelopeValidationError("envelope_hash was not found in the registry.")

    def latest_envelope_for_plan(self, plan_id: str) -> OfflineResearchExecutionEnvelope:
        target = _require_str(plan_id, "plan_id")
        candidates = [record for record in self.records if record.plan_id == target]
        if not candidates:
            raise OfflineResearchExecutionEnvelopeValidationError("plan_id was not found in the registry.")
        return max(candidates, key=lambda record: record.envelope_number)

    def with_envelope(
        self,
        envelope: OfflineResearchExecutionEnvelope,
        *,
        updated_at_utc: datetime | None = None,
    ) -> "OfflineResearchExecutionEnvelopeRegistry":
        records = tuple(self.records) + (envelope,)
        return OfflineResearchExecutionEnvelopeRegistry(
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
class OfflineResearchExecutionEnvelopeRegistryVerificationReport:
    schema_version: int = OFFLINE_RESEARCH_EXECUTION_ENVELOPE_SCHEMA_VERSION
    registry_file: Path = field(default_factory=Path)
    verified_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved: bool = True
    registry_id: str = OFFLINE_RESEARCH_EXECUTION_ENVELOPE_REGISTRY_ID
    registry_version: str = OFFLINE_RESEARCH_EXECUTION_ENVELOPE_REGISTRY_VERSION
    record_count: int = 0
    registry_hash: str = ""
    envelope_ids: tuple[str, ...] = ()
    envelope_hashes: tuple[str, ...] = ()
    plan_ids: tuple[str, ...] = ()
    experiment_ids: tuple[str, ...] = ()
    authorization_ids: tuple[str, ...] = ()
    offline_only: bool = True
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_RESEARCH_EXECUTION_ENVELOPE_NON_OPERATIONAL_DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_file", Path(self.registry_file))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "verified_at_utc", _require_utc_datetime(self.verified_at_utc, "verified_at_utc"))
        object.__setattr__(self, "approved", _require_bool(self.approved, "approved"))
        object.__setattr__(self, "registry_id", _require_str(self.registry_id, "registry_id"))
        object.__setattr__(self, "registry_version", _require_str(self.registry_version, "registry_version"))
        object.__setattr__(self, "record_count", _require_positive_int(self.record_count, "record_count") if self.record_count else 0)
        object.__setattr__(self, "registry_hash", _require_hex_digest(self.registry_hash, "registry_hash") if self.registry_hash else "")
        object.__setattr__(self, "envelope_ids", tuple(_require_hex_digest(item, "envelope_id") for item in self.envelope_ids))
        object.__setattr__(self, "envelope_hashes", tuple(_require_hex_digest(item, "envelope_hash") for item in self.envelope_hashes))
        object.__setattr__(self, "plan_ids", tuple(_require_str(item, "plan_id") for item in self.plan_ids))
        object.__setattr__(self, "experiment_ids", tuple(_require_str(item, "experiment_id") for item in self.experiment_ids))
        object.__setattr__(self, "authorization_ids", tuple(_require_hex_digest(item, "authorization_id") for item in self.authorization_ids))
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.approved is not True:
            raise OfflineResearchExecutionEnvelopeValidationError("approved must be true.")

    def canonical_payload(self, *, include_registry_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "registry_file": self.registry_file.as_posix(),
            "verified_at_utc": _utc_iso(self.verified_at_utc),
            "approved": self.approved,
            "registry_id": self.registry_id,
            "registry_version": self.registry_version,
            "record_count": self.record_count,
            "envelope_ids": self.envelope_ids,
            "envelope_hashes": self.envelope_hashes,
            "plan_ids": self.plan_ids,
            "experiment_ids": self.experiment_ids,
            "authorization_ids": self.authorization_ids,
            "offline_only": self.offline_only,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
            "registry_hash": self.registry_hash,
        }
        if not include_registry_hash:
            payload.pop("registry_hash", None)
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_registry_hash=True))


def load_offline_research_execution_envelope_registry(
    registry_file: str | Path,
) -> OfflineResearchExecutionEnvelopeRegistry:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    payload = _load_json(path)
    if not isinstance(payload, Mapping):
        raise OfflineResearchExecutionEnvelopeValidationError(
            "offline research execution envelope registry must be a JSON object."
        )
    registry = OfflineResearchExecutionEnvelopeRegistry.from_dict(payload, registry_file=path)
    if _canonical_json(registry.as_dict()) != _canonical_json(payload):
        raise OfflineResearchExecutionEnvelopeIntegrityError(
            "offline research execution envelope registry payload mismatch."
        )
    return registry


def save_offline_research_execution_envelope_registry(
    registry_file: str | Path,
    registry: OfflineResearchExecutionEnvelopeRegistry,
) -> OfflineResearchExecutionEnvelopeRegistry:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    if not isinstance(registry, OfflineResearchExecutionEnvelopeRegistry):
        raise OfflineResearchExecutionEnvelopeValidationError(
            "offline research execution envelope registry is required."
        )
    payload = registry.as_dict()
    _write_json_atomic(path, payload)
    return registry


def register_offline_research_execution_envelope(
    *,
    registry_file: str | Path,
    envelope: OfflineResearchExecutionEnvelope,
    updated_at_utc: datetime | None = None,
) -> OfflineResearchExecutionEnvelope:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    if not isinstance(envelope, OfflineResearchExecutionEnvelope):
        raise OfflineResearchExecutionEnvelopeValidationError(
            "offline research execution envelope is required."
        )
    registry = (
        load_offline_research_execution_envelope_registry(path)
        if path.exists()
        else OfflineResearchExecutionEnvelopeRegistry(
            registry_file=path,
            created_at_utc=updated_at_utc or envelope.created_at_utc,
            updated_at_utc=updated_at_utc or envelope.created_at_utc,
        )
    )
    if any(existing.as_dict() == envelope.as_dict() for existing in registry.records):
        return next(existing for existing in registry.records if existing.as_dict() == envelope.as_dict())
    if any(existing.envelope_id == envelope.envelope_id for existing in registry.records):
        raise OfflineResearchExecutionEnvelopeConflictError("envelope_id already registered and differs.")
    if registry.records:
        latest = registry.latest_envelope_for_plan(envelope.plan_id)
        if envelope.envelope_number != latest.envelope_number + 1:
            raise OfflineResearchExecutionEnvelopeConflictError(
                "envelope_number must follow the existing chain."
            )
        if envelope.previous_envelope_id != latest.envelope_id or envelope.previous_envelope_hash != latest.envelope_hash:
            raise OfflineResearchExecutionEnvelopeConflictError(
                "previous envelope reference must match the latest registered envelope."
            )
    elif envelope.envelope_number != 1:
        raise OfflineResearchExecutionEnvelopeConflictError("the first envelope in a chain must have envelope_number 1.")
    updated_registry = registry.with_envelope(envelope, updated_at_utc=updated_at_utc or envelope.created_at_utc)
    save_offline_research_execution_envelope_registry(path, updated_registry)
    return envelope


def verify_offline_research_execution_envelope_registry(
    registry_file: str | Path,
) -> OfflineResearchExecutionEnvelopeRegistryVerificationReport:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    registry = load_offline_research_execution_envelope_registry(path)
    report = OfflineResearchExecutionEnvelopeRegistryVerificationReport(
        registry_file=path,
        verified_at_utc=registry.updated_at_utc,
        approved=True,
        registry_id=registry.registry_id,
        registry_version=registry.registry_version,
        record_count=registry.record_count,
        registry_hash=registry.registry_hash,
        envelope_ids=tuple(record.envelope_id for record in registry.records),
        envelope_hashes=tuple(record.envelope_hash for record in registry.records),
        plan_ids=tuple(record.plan_id for record in registry.records),
        experiment_ids=tuple(record.experiment_id for record in registry.records),
        authorization_ids=tuple(record.authorization_id for record in registry.records),
        offline_only=registry.offline_only,
        historical_research_only=registry.historical_research_only,
        operational_evidence=registry.operational_evidence,
        paper_promotion_eligible=registry.paper_promotion_eligible,
        non_operational_declaration=registry.non_operational_declaration,
    )
    if _canonical_json(report.as_dict()) != _canonical_json(report.canonical_payload(include_registry_hash=True)):
        raise OfflineResearchExecutionEnvelopeIntegrityError(
            "registry verification report payload mismatch."
        )
    return report


__all__ = [
    "OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_EXECUTION_ENVIRONMENT",
    "OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_OUTPUT_POLICY",
    "OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_RESOURCE_LIMITS",
    "OFFLINE_RESEARCH_EXECUTION_ENVELOPE_EXECUTION_ENVIRONMENT_TYPE",
    "OFFLINE_RESEARCH_EXECUTION_ENVELOPE_EXCHANGE_POLICY_DENY_ALL",
    "OFFLINE_RESEARCH_EXECUTION_ENVELOPE_FILESYSTEM_POLICY_ISOLATED_OUTPUT_ONLY",
    "OFFLINE_RESEARCH_EXECUTION_ENVELOPE_NETWORK_POLICY_DENY_ALL",
    "OFFLINE_RESEARCH_EXECUTION_ENVELOPE_NON_OPERATIONAL_DECLARATION",
    "OFFLINE_RESEARCH_EXECUTION_ENVELOPE_OUTPUT_DIRECTORY_MODE_ISOLATED",
    "OFFLINE_RESEARCH_EXECUTION_ENVELOPE_PROCESS_POLICY_NO_CHILD_PROCESSES",
    "OFFLINE_RESEARCH_EXECUTION_ENVELOPE_REGISTRY_ID",
    "OFFLINE_RESEARCH_EXECUTION_ENVELOPE_REGISTRY_VERSION",
    "OFFLINE_RESEARCH_EXECUTION_ENVELOPE_SCHEMA_VERSION",
    "OFFLINE_RESEARCH_EXECUTION_ENVELOPE_VERSION",
    "OfflineResearchExecutionEnvelope",
    "OfflineResearchExecutionEnvelopeConflictError",
    "OfflineResearchExecutionEnvelopeError",
    "OfflineResearchExecutionEnvelopeIntegrityError",
    "OfflineResearchExecutionEnvelopePersistenceError",
    "OfflineResearchExecutionEnvelopeRegistry",
    "OfflineResearchExecutionEnvelopeRegistryVerificationReport",
    "OfflineResearchExecutionEnvelopeValidationError",
    "build_offline_research_execution_envelope",
    "load_offline_research_execution_envelope_registry",
    "register_offline_research_execution_envelope",
    "save_offline_research_execution_envelope_registry",
    "verify_offline_research_execution_envelope",
    "verify_offline_research_execution_envelope_registry",
]
