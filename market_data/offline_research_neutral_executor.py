from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from domain.serialization import serialize_value

from . import offline_research_canonical_evidence_fixture as phase44_fixture
from . import offline_research_execution_authorization as phase45
from . import offline_research_execution_envelope as phase46
from .errors import (
    HistoricalDataConflictError,
    HistoricalDataError,
    HistoricalDataIntegrityError,
    HistoricalDataValidationError,
)

OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_SCHEMA_VERSION = 1
OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_VERSION = "phase47_neutral_offline_executor_v1"
OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_NAME = "deterministic_neutral_offline_executor"
OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REQUEST_VERSION = "phase47_neutral_offline_execution_request_v1"
OFFLINE_RESEARCH_NEUTRAL_EXECUTION_RESULT_VERSION = "phase47_neutral_offline_execution_result_v1"
OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_ID = "offline_research_neutral_execution_registry"
OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_VERSION = "phase47_neutral_offline_execution_registry_v1"
OFFLINE_RESEARCH_NEUTRAL_OPERATION_NAME = "neutral_fixture_summary"
OFFLINE_RESEARCH_NEUTRAL_OPERATION_VERSION = "v1"
OFFLINE_RESEARCH_NEUTRAL_EXECUTION_NON_OPERATIONAL_DECLARATION = (
    "This result was produced by a deterministic neutral offline executor. It did not execute a trading strategy, "
    "generate signals, simulate trades, calculate performance, access a network, connect to an exchange, create "
    "positions, submit orders, perform paper trading, or perform live trading."
)
OFFLINE_RESEARCH_NEUTRAL_EXECUTION_DEFAULT_RESOURCE_LIMITS = {
    "max_runtime_seconds": 86400,
    "max_memory_mb": 8192,
    "max_output_bytes": 10485760,
    "max_event_count": 1000000,
}
OFFLINE_RESEARCH_NEUTRAL_EXECUTION_DEFAULT_EXECUTION_ENVIRONMENT = {
    "environment_type": "OFFLINE_ISOLATED",
    "network_policy": "DENY_ALL",
    "exchange_policy": "DENY_ALL",
    "filesystem_policy": "ISOLATED_OUTPUT_ONLY",
    "process_policy": "NO_CHILD_PROCESSES",
}
OFFLINE_RESEARCH_NEUTRAL_EXECUTION_DEFAULT_OUTPUT_POLICY = {
    "output_directory_mode": "ISOLATED",
    "overwrite_existing": False,
    "append_only_results": True,
    "temporary_output_allowed": True,
    "external_path_allowed": False,
}
OFFLINE_RESEARCH_NEUTRAL_EXECUTION_ALLOWED_STATUSES = (
    "SUCCEEDED",
    "FAILED_VALIDATION",
    "FAILED_RESOURCE_LIMIT",
    "FAILED_PERSISTENCE",
)
OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_FILENAME = "offline_research_neutral_execution_registry.json"


class OfflineResearchNeutralExecutorError(HistoricalDataError):
    pass


class OfflineResearchNeutralExecutionValidationError(
    OfflineResearchNeutralExecutorError,
    HistoricalDataValidationError,
):
    pass


class OfflineResearchNeutralExecutionIntegrityError(
    OfflineResearchNeutralExecutorError,
    HistoricalDataIntegrityError,
):
    pass


class OfflineResearchNeutralExecutionResourceLimitError(
    OfflineResearchNeutralExecutorError,
):
    pass


class OfflineResearchNeutralExecutionPersistenceError(OfflineResearchNeutralExecutorError):
    pass


class OfflineResearchNeutralExecutionConflictError(
    OfflineResearchNeutralExecutorError,
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
        raise OfflineResearchNeutralExecutionValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineResearchNeutralExecutionValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchNeutralExecutionValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineResearchNeutralExecutionValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_positive_int(value: Any, field_name: str) -> int:
    normalized = _require_int(value, field_name)
    if normalized <= 0:
        raise OfflineResearchNeutralExecutionValidationError(f"{field_name} must be greater than zero.")
    return normalized


def _require_non_negative_int(value: Any, field_name: str) -> int:
    normalized = _require_int(value, field_name)
    if normalized < 0:
        raise OfflineResearchNeutralExecutionValidationError(f"{field_name} must not be negative.")
    return normalized


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineResearchNeutralExecutionValidationError(f"{field_name} must be a boolean.")
    return value


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineResearchNeutralExecutionValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise OfflineResearchNeutralExecutionValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise OfflineResearchNeutralExecutionValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineResearchNeutralExecutionValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _is_temporary_pytest_path(path: Path) -> bool:
    return any(part == ".pytest_tmp" for part in path.parts)


def _ensure_path(path: str | Path, *, field_name: str) -> Path:
    resolved = Path(path)
    if _is_temporary_pytest_path(resolved):
        raise OfflineResearchNeutralExecutionValidationError(f"{field_name} must not point to .pytest_tmp.")
    return resolved


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


def _normalize_resource_limits(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    payload = dict(OFFLINE_RESEARCH_NEUTRAL_EXECUTION_DEFAULT_RESOURCE_LIMITS if value is None else value)
    allowed = set(OFFLINE_RESEARCH_NEUTRAL_EXECUTION_DEFAULT_RESOURCE_LIMITS)
    extra = sorted(set(payload) - allowed)
    if extra:
        raise OfflineResearchNeutralExecutionValidationError(
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
        raise OfflineResearchNeutralExecutionValidationError(
            f"{exc.args[0]} is required in resource_limits."
        ) from exc
    return _freeze_read_only_value(normalized)


def _normalize_execution_environment(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    payload = dict(OFFLINE_RESEARCH_NEUTRAL_EXECUTION_DEFAULT_EXECUTION_ENVIRONMENT if value is None else value)
    allowed = set(OFFLINE_RESEARCH_NEUTRAL_EXECUTION_DEFAULT_EXECUTION_ENVIRONMENT)
    extra = sorted(set(payload) - allowed)
    if extra:
        raise OfflineResearchNeutralExecutionValidationError(
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
        raise OfflineResearchNeutralExecutionValidationError(
            f"{exc.args[0]} is required in execution_environment."
        ) from exc
    if normalized != OFFLINE_RESEARCH_NEUTRAL_EXECUTION_DEFAULT_EXECUTION_ENVIRONMENT:
        raise OfflineResearchNeutralExecutionValidationError("execution_environment diverges from the neutral contract.")
    return _freeze_read_only_value(normalized)


def _normalize_output_policy(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    payload = dict(OFFLINE_RESEARCH_NEUTRAL_EXECUTION_DEFAULT_OUTPUT_POLICY if value is None else value)
    allowed = set(OFFLINE_RESEARCH_NEUTRAL_EXECUTION_DEFAULT_OUTPUT_POLICY)
    extra = sorted(set(payload) - allowed)
    if extra:
        raise OfflineResearchNeutralExecutionValidationError(
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
        raise OfflineResearchNeutralExecutionValidationError(
            f"{exc.args[0]} is required in output_policy."
        ) from exc
    if normalized != OFFLINE_RESEARCH_NEUTRAL_EXECUTION_DEFAULT_OUTPUT_POLICY:
        raise OfflineResearchNeutralExecutionValidationError("output_policy diverges from the neutral contract.")
    return _freeze_read_only_value(normalized)


def _ensure_allowed_neutral_policies(
    *,
    offline_only: bool,
    historical_research_only: bool,
    neutral_execution_only: bool,
    network_access_allowed: bool,
    exchange_connectivity_allowed: bool,
    paper_trading_allowed: bool,
    live_trading_allowed: bool,
    order_submission_allowed: bool,
    strategy_execution_allowed: bool,
    operational_evidence: bool,
    paper_promotion_eligible: bool,
    non_operational_declaration: str,
) -> None:
    if offline_only is not True:
        raise OfflineResearchNeutralExecutionValidationError("offline_only must be true.")
    if historical_research_only is not True:
        raise OfflineResearchNeutralExecutionValidationError("historical_research_only must be true.")
    if neutral_execution_only is not True:
        raise OfflineResearchNeutralExecutionValidationError("neutral_execution_only must be true.")
    if network_access_allowed is not False:
        raise OfflineResearchNeutralExecutionValidationError("network_access_allowed must be false.")
    if exchange_connectivity_allowed is not False:
        raise OfflineResearchNeutralExecutionValidationError("exchange_connectivity_allowed must be false.")
    if paper_trading_allowed is not False:
        raise OfflineResearchNeutralExecutionValidationError("paper_trading_allowed must be false.")
    if live_trading_allowed is not False:
        raise OfflineResearchNeutralExecutionValidationError("live_trading_allowed must be false.")
    if order_submission_allowed is not False:
        raise OfflineResearchNeutralExecutionValidationError("order_submission_allowed must be false.")
    if strategy_execution_allowed is not False:
        raise OfflineResearchNeutralExecutionValidationError("strategy_execution_allowed must be false.")
    if operational_evidence is not False:
        raise OfflineResearchNeutralExecutionValidationError("operational_evidence must be false.")
    if paper_promotion_eligible is not False:
        raise OfflineResearchNeutralExecutionValidationError("paper_promotion_eligible must be false.")
    if non_operational_declaration != phase46.OFFLINE_RESEARCH_EXECUTION_ENVELOPE_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchNeutralExecutionValidationError(
            "non_operational_declaration diverges from the envelope contract."
        )


@dataclass(frozen=True, slots=True)
class OfflineResearchNeutralExecutionRequest:
    envelope: phase46.OfflineResearchExecutionEnvelope = field(repr=False)
    schema_version: int = OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_SCHEMA_VERSION
    fixture_directory: Path = field(default_factory=Path)
    registry_file: Path = field(default_factory=Path)
    output_directory: Path = field(default_factory=Path)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    random_seed: int = 0
    resource_limits: Mapping[str, Any] = field(default_factory=dict, repr=False)
    execution_environment: Mapping[str, Any] = field(default_factory=dict, repr=False)
    output_policy: Mapping[str, Any] = field(default_factory=dict, repr=False)
    offline_only: bool = True
    historical_research_only: bool = True
    neutral_execution_only: bool = True
    network_access_allowed: bool = False
    exchange_connectivity_allowed: bool = False
    paper_trading_allowed: bool = False
    live_trading_allowed: bool = False
    order_submission_allowed: bool = False
    strategy_execution_allowed: bool = False
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = phase46.OFFLINE_RESEARCH_EXECUTION_ENVELOPE_NON_OPERATIONAL_DECLARATION
    request_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        if not isinstance(self.envelope, phase46.OfflineResearchExecutionEnvelope):
            raise OfflineResearchNeutralExecutionValidationError(
                "envelope must be a verified offline research execution envelope."
            )
        object.__setattr__(self, "fixture_directory", _ensure_path(self.fixture_directory, field_name="fixture_directory"))
        object.__setattr__(self, "registry_file", _ensure_path(self.registry_file, field_name="registry_file"))
        object.__setattr__(self, "output_directory", _ensure_path(self.output_directory, field_name="output_directory"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "random_seed", _require_non_negative_int(self.random_seed, "random_seed"))
        if not isinstance(self.resource_limits, Mapping):
            raise OfflineResearchNeutralExecutionValidationError("resource_limits must be a mapping.")
        if not isinstance(self.execution_environment, Mapping):
            raise OfflineResearchNeutralExecutionValidationError("execution_environment must be a mapping.")
        if not isinstance(self.output_policy, Mapping):
            raise OfflineResearchNeutralExecutionValidationError("output_policy must be a mapping.")
        object.__setattr__(self, "resource_limits", _normalize_resource_limits(self.resource_limits))
        object.__setattr__(self, "execution_environment", _normalize_execution_environment(self.execution_environment))
        object.__setattr__(self, "output_policy", _normalize_output_policy(self.output_policy))
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "neutral_execution_only", _require_bool(self.neutral_execution_only, "neutral_execution_only"))
        object.__setattr__(self, "network_access_allowed", _require_bool(self.network_access_allowed, "network_access_allowed"))
        object.__setattr__(self, "exchange_connectivity_allowed", _require_bool(self.exchange_connectivity_allowed, "exchange_connectivity_allowed"))
        object.__setattr__(self, "paper_trading_allowed", _require_bool(self.paper_trading_allowed, "paper_trading_allowed"))
        object.__setattr__(self, "live_trading_allowed", _require_bool(self.live_trading_allowed, "live_trading_allowed"))
        object.__setattr__(self, "order_submission_allowed", _require_bool(self.order_submission_allowed, "order_submission_allowed"))
        object.__setattr__(self, "strategy_execution_allowed", _require_bool(self.strategy_execution_allowed, "strategy_execution_allowed"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        _ensure_allowed_neutral_policies(
            offline_only=self.offline_only,
            historical_research_only=self.historical_research_only,
            neutral_execution_only=self.neutral_execution_only,
            network_access_allowed=self.network_access_allowed,
            exchange_connectivity_allowed=self.exchange_connectivity_allowed,
            paper_trading_allowed=self.paper_trading_allowed,
            live_trading_allowed=self.live_trading_allowed,
            order_submission_allowed=self.order_submission_allowed,
            strategy_execution_allowed=self.strategy_execution_allowed,
            operational_evidence=self.operational_evidence,
            paper_promotion_eligible=self.paper_promotion_eligible,
            non_operational_declaration=self.non_operational_declaration,
        )
        expected_hash = _hash_payload(self._request_identity_payload())
        if self.request_hash:
            if self.request_hash != expected_hash:
                raise OfflineResearchNeutralExecutionIntegrityError("request_hash mismatch.")
        else:
            object.__setattr__(self, "request_hash", expected_hash)

    def _request_identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "envelope_hash": self.envelope.envelope_hash,
            "envelope_id": self.envelope.envelope_id,
            "fixture_directory": self.fixture_directory.resolve().as_posix(),
            "registry_file": self.registry_file.resolve().as_posix(),
            "output_directory": self.output_directory.resolve().as_posix(),
            "random_seed": self.random_seed,
            "resource_limits": _thaw_read_only_value(self.resource_limits),
            "execution_environment": _thaw_read_only_value(self.execution_environment),
            "output_policy": _thaw_read_only_value(self.output_policy),
            "offline_only": self.offline_only,
            "historical_research_only": self.historical_research_only,
            "neutral_execution_only": self.neutral_execution_only,
            "network_access_allowed": self.network_access_allowed,
            "exchange_connectivity_allowed": self.exchange_connectivity_allowed,
            "paper_trading_allowed": self.paper_trading_allowed,
            "live_trading_allowed": self.live_trading_allowed,
            "order_submission_allowed": self.order_submission_allowed,
            "strategy_execution_allowed": self.strategy_execution_allowed,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
        }

    def canonical_payload(self, *, include_request_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "envelope": self.envelope.as_dict(),
            "fixture_directory": self.fixture_directory.resolve().as_posix(),
            "registry_file": self.registry_file.resolve().as_posix(),
            "output_directory": self.output_directory.resolve().as_posix(),
            "created_at_utc": _utc_iso(self.created_at_utc),
            "random_seed": self.random_seed,
            "resource_limits": _thaw_read_only_value(self.resource_limits),
            "execution_environment": _thaw_read_only_value(self.execution_environment),
            "output_policy": _thaw_read_only_value(self.output_policy),
            "offline_only": self.offline_only,
            "historical_research_only": self.historical_research_only,
            "neutral_execution_only": self.neutral_execution_only,
            "network_access_allowed": self.network_access_allowed,
            "exchange_connectivity_allowed": self.exchange_connectivity_allowed,
            "paper_trading_allowed": self.paper_trading_allowed,
            "live_trading_allowed": self.live_trading_allowed,
            "order_submission_allowed": self.order_submission_allowed,
            "strategy_execution_allowed": self.strategy_execution_allowed,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
        }
        if include_request_hash:
            payload["request_hash"] = self.request_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_request_hash=True))


@dataclass(frozen=True, slots=True)
class OfflineResearchNeutralExecutionResult:
    schema_version: int = OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_SCHEMA_VERSION
    neutral_execution_id: str = ""
    execution_number: int = 0
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    executor_name: str = OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_NAME
    executor_version: str = OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_VERSION
    neutral_operation_name: str = OFFLINE_RESEARCH_NEUTRAL_OPERATION_NAME
    neutral_operation_version: str = OFFLINE_RESEARCH_NEUTRAL_OPERATION_VERSION
    request_hash: str = ""
    envelope_id: str = ""
    envelope_hash: str = ""
    experiment_id: str = ""
    execution_id: str = ""
    plan_id: str = ""
    evidence_id: str = ""
    authorization_id: str = ""
    strategy_id: str = ""
    strategy_version: str = ""
    strategy_fingerprint: str = ""
    input_record_count: int = 0
    expected_record_count: int = 0
    first_record_timestamp: str = ""
    last_record_timestamp: str = ""
    min_timestamp: str = ""
    max_timestamp: str = ""
    ordered_records: tuple[str, ...] = ()
    duplicate_record_count: int = 0
    missing_record_count: int = 0
    input_sequence_hash: str = ""
    neutral_transform_hash: str = ""
    canonical_field_set_hash: str = ""
    random_seed: int = 0
    resource_limits_snapshot: Mapping[str, Any] = field(default_factory=dict, repr=False)
    execution_environment_snapshot: Mapping[str, Any] = field(default_factory=dict, repr=False)
    output_policy_snapshot: Mapping[str, Any] = field(default_factory=dict, repr=False)
    started_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    elapsed_monotonic_ns: int = 0
    status: str = "SUCCEEDED"
    failure_code: str = ""
    failure_message: str = ""
    offline_only: bool = True
    historical_research_only: bool = True
    neutral_execution_only: bool = True
    network_access_used: bool = False
    exchange_connectivity_used: bool = False
    paper_trading_used: bool = False
    live_trading_used: bool = False
    order_submission_used: bool = False
    strategy_execution_used: bool = False
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_RESEARCH_NEUTRAL_EXECUTION_NON_OPERATIONAL_DECLARATION
    previous_execution_id: str | None = None
    previous_execution_hash: str | None = None
    result_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "neutral_execution_id", _require_hex_digest(self.neutral_execution_id, "neutral_execution_id"))
        object.__setattr__(self, "execution_number", _require_positive_int(self.execution_number, "execution_number"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "executor_name", _require_str(self.executor_name, "executor_name"))
        object.__setattr__(self, "executor_version", _require_str(self.executor_version, "executor_version"))
        object.__setattr__(self, "neutral_operation_name", _require_str(self.neutral_operation_name, "neutral_operation_name"))
        object.__setattr__(self, "neutral_operation_version", _require_str(self.neutral_operation_version, "neutral_operation_version"))
        object.__setattr__(self, "request_hash", _require_hex_digest(self.request_hash, "request_hash"))
        object.__setattr__(self, "envelope_id", _require_hex_digest(self.envelope_id, "envelope_id"))
        object.__setattr__(self, "envelope_hash", _require_hex_digest(self.envelope_hash, "envelope_hash"))
        object.__setattr__(self, "experiment_id", _require_str(self.experiment_id, "experiment_id"))
        object.__setattr__(self, "execution_id", _require_str(self.execution_id, "execution_id"))
        object.__setattr__(self, "plan_id", _require_str(self.plan_id, "plan_id"))
        object.__setattr__(self, "evidence_id", _require_str(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "authorization_id", _require_hex_digest(self.authorization_id, "authorization_id"))
        object.__setattr__(self, "strategy_id", _require_str(self.strategy_id, "strategy_id"))
        object.__setattr__(self, "strategy_version", _require_str(self.strategy_version, "strategy_version"))
        object.__setattr__(self, "strategy_fingerprint", _require_hex_digest(self.strategy_fingerprint, "strategy_fingerprint"))
        object.__setattr__(self, "input_record_count", _require_non_negative_int(self.input_record_count, "input_record_count"))
        object.__setattr__(self, "expected_record_count", _require_positive_int(self.expected_record_count, "expected_record_count"))
        object.__setattr__(self, "first_record_timestamp", _require_str(self.first_record_timestamp, "first_record_timestamp"))
        object.__setattr__(self, "last_record_timestamp", _require_str(self.last_record_timestamp, "last_record_timestamp"))
        object.__setattr__(self, "min_timestamp", _require_str(self.min_timestamp, "min_timestamp"))
        object.__setattr__(self, "max_timestamp", _require_str(self.max_timestamp, "max_timestamp"))
        object.__setattr__(self, "ordered_records", tuple(_require_str(item, "ordered_record") for item in self.ordered_records))
        object.__setattr__(self, "duplicate_record_count", _require_non_negative_int(self.duplicate_record_count, "duplicate_record_count"))
        object.__setattr__(self, "missing_record_count", _require_non_negative_int(self.missing_record_count, "missing_record_count"))
        object.__setattr__(self, "input_sequence_hash", _require_hex_digest(self.input_sequence_hash, "input_sequence_hash"))
        object.__setattr__(self, "neutral_transform_hash", _require_hex_digest(self.neutral_transform_hash, "neutral_transform_hash"))
        object.__setattr__(self, "canonical_field_set_hash", _require_hex_digest(self.canonical_field_set_hash, "canonical_field_set_hash"))
        object.__setattr__(self, "random_seed", _require_non_negative_int(self.random_seed, "random_seed"))
        if not isinstance(self.resource_limits_snapshot, Mapping):
            raise OfflineResearchNeutralExecutionValidationError("resource_limits_snapshot must be a mapping.")
        if not isinstance(self.execution_environment_snapshot, Mapping):
            raise OfflineResearchNeutralExecutionValidationError("execution_environment_snapshot must be a mapping.")
        if not isinstance(self.output_policy_snapshot, Mapping):
            raise OfflineResearchNeutralExecutionValidationError("output_policy_snapshot must be a mapping.")
        object.__setattr__(self, "resource_limits_snapshot", _freeze_read_only_value(dict(self.resource_limits_snapshot)))
        object.__setattr__(self, "execution_environment_snapshot", _freeze_read_only_value(dict(self.execution_environment_snapshot)))
        object.__setattr__(self, "output_policy_snapshot", _freeze_read_only_value(dict(self.output_policy_snapshot)))
        object.__setattr__(self, "started_at_utc", _require_utc_datetime(self.started_at_utc, "started_at_utc"))
        object.__setattr__(self, "finished_at_utc", _require_utc_datetime(self.finished_at_utc, "finished_at_utc"))
        object.__setattr__(self, "elapsed_monotonic_ns", _require_non_negative_int(self.elapsed_monotonic_ns, "elapsed_monotonic_ns"))
        object.__setattr__(self, "status", _require_str(self.status, "status").upper())
        if self.status not in OFFLINE_RESEARCH_NEUTRAL_EXECUTION_ALLOWED_STATUSES:
            raise OfflineResearchNeutralExecutionValidationError("status is not allowed.")
        object.__setattr__(self, "failure_code", _require_str(self.failure_code, "failure_code") if self.failure_code else "")
        object.__setattr__(self, "failure_message", _require_str(self.failure_message, "failure_message") if self.failure_message else "")
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "neutral_execution_only", _require_bool(self.neutral_execution_only, "neutral_execution_only"))
        object.__setattr__(self, "network_access_used", _require_bool(self.network_access_used, "network_access_used"))
        object.__setattr__(self, "exchange_connectivity_used", _require_bool(self.exchange_connectivity_used, "exchange_connectivity_used"))
        object.__setattr__(self, "paper_trading_used", _require_bool(self.paper_trading_used, "paper_trading_used"))
        object.__setattr__(self, "live_trading_used", _require_bool(self.live_trading_used, "live_trading_used"))
        object.__setattr__(self, "order_submission_used", _require_bool(self.order_submission_used, "order_submission_used"))
        object.__setattr__(self, "strategy_execution_used", _require_bool(self.strategy_execution_used, "strategy_execution_used"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        object.__setattr__(self, "previous_execution_id", _require_hex_digest(self.previous_execution_id, "previous_execution_id") if self.previous_execution_id else None)
        object.__setattr__(self, "previous_execution_hash", _require_hex_digest(self.previous_execution_hash, "previous_execution_hash") if self.previous_execution_hash else None)
        if self.offline_only is not True:
            raise OfflineResearchNeutralExecutionValidationError("offline_only must be true.")
        if self.historical_research_only is not True:
            raise OfflineResearchNeutralExecutionValidationError("historical_research_only must be true.")
        if self.neutral_execution_only is not True:
            raise OfflineResearchNeutralExecutionValidationError("neutral_execution_only must be true.")
        if self.network_access_used is not False:
            raise OfflineResearchNeutralExecutionValidationError("network_access_used must be false.")
        if self.exchange_connectivity_used is not False:
            raise OfflineResearchNeutralExecutionValidationError("exchange_connectivity_used must be false.")
        if self.paper_trading_used is not False:
            raise OfflineResearchNeutralExecutionValidationError("paper_trading_used must be false.")
        if self.live_trading_used is not False:
            raise OfflineResearchNeutralExecutionValidationError("live_trading_used must be false.")
        if self.order_submission_used is not False:
            raise OfflineResearchNeutralExecutionValidationError("order_submission_used must be false.")
        if self.strategy_execution_used is not False:
            raise OfflineResearchNeutralExecutionValidationError("strategy_execution_used must be false.")
        if self.operational_evidence is not False:
            raise OfflineResearchNeutralExecutionValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchNeutralExecutionValidationError("paper_promotion_eligible must be false.")
        if self.non_operational_declaration != OFFLINE_RESEARCH_NEUTRAL_EXECUTION_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchNeutralExecutionValidationError(
                "non_operational_declaration diverges from the neutral executor contract."
            )
        expected_neutral_execution_id = _hash_payload(self._neutral_execution_identity_payload())
        if self.neutral_execution_id != expected_neutral_execution_id:
            raise OfflineResearchNeutralExecutionIntegrityError("neutral_execution_id mismatch.")
        expected_result_hash = _hash_payload(self._result_identity_payload())
        if self.result_hash:
            if self.result_hash != expected_result_hash:
                raise OfflineResearchNeutralExecutionIntegrityError("result_hash mismatch.")
        else:
            object.__setattr__(self, "result_hash", expected_result_hash)

    def _neutral_execution_identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "executor_name": self.executor_name,
            "executor_version": self.executor_version,
            "neutral_operation_name": self.neutral_operation_name,
            "neutral_operation_version": self.neutral_operation_version,
            "request_hash": self.request_hash,
            "envelope_id": self.envelope_id,
            "envelope_hash": self.envelope_hash,
            "input_sequence_hash": self.input_sequence_hash,
            "random_seed": self.random_seed,
            "status": self.status,
            "execution_number": self.execution_number,
        }

    def _result_identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "neutral_execution_id": self.neutral_execution_id,
            "execution_number": self.execution_number,
            "executor_name": self.executor_name,
            "executor_version": self.executor_version,
            "neutral_operation_name": self.neutral_operation_name,
            "neutral_operation_version": self.neutral_operation_version,
            "request_hash": self.request_hash,
            "envelope_id": self.envelope_id,
            "envelope_hash": self.envelope_hash,
            "experiment_id": self.experiment_id,
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "evidence_id": self.evidence_id,
            "authorization_id": self.authorization_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_fingerprint": self.strategy_fingerprint,
            "input_record_count": self.input_record_count,
            "expected_record_count": self.expected_record_count,
            "first_record_timestamp": self.first_record_timestamp,
            "last_record_timestamp": self.last_record_timestamp,
            "min_timestamp": self.min_timestamp,
            "max_timestamp": self.max_timestamp,
            "ordered_records": self.ordered_records,
            "duplicate_record_count": self.duplicate_record_count,
            "missing_record_count": self.missing_record_count,
            "input_sequence_hash": self.input_sequence_hash,
            "neutral_transform_hash": self.neutral_transform_hash,
            "canonical_field_set_hash": self.canonical_field_set_hash,
            "random_seed": self.random_seed,
            "resource_limits_snapshot": _thaw_read_only_value(self.resource_limits_snapshot),
            "execution_environment_snapshot": _thaw_read_only_value(self.execution_environment_snapshot),
            "output_policy_snapshot": _thaw_read_only_value(self.output_policy_snapshot),
            "status": self.status,
            "failure_code": self.failure_code,
            "failure_message": self.failure_message,
            "offline_only": self.offline_only,
            "historical_research_only": self.historical_research_only,
            "neutral_execution_only": self.neutral_execution_only,
            "network_access_used": self.network_access_used,
            "exchange_connectivity_used": self.exchange_connectivity_used,
            "paper_trading_used": self.paper_trading_used,
            "live_trading_used": self.live_trading_used,
            "order_submission_used": self.order_submission_used,
            "strategy_execution_used": self.strategy_execution_used,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
            "previous_execution_id": self.previous_execution_id,
            "previous_execution_hash": self.previous_execution_hash,
        }

    def canonical_payload(self, *, include_result_hash: bool = True) -> dict[str, Any]:
        payload = self._result_identity_payload()
        payload["created_at_utc"] = _utc_iso(self.created_at_utc)
        payload["started_at_utc"] = _utc_iso(self.started_at_utc)
        payload["finished_at_utc"] = _utc_iso(self.finished_at_utc)
        payload["elapsed_monotonic_ns"] = self.elapsed_monotonic_ns
        if include_result_hash:
            payload["result_hash"] = self.result_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_result_hash=True))


@dataclass(frozen=True, slots=True)
class OfflineResearchNeutralExecutionRegistry:
    schema_version: int = OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_SCHEMA_VERSION
    registry_file: Path = field(default_factory=Path)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    records: tuple[OfflineResearchNeutralExecutionResult, ...] = ()
    registry_id: str = OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_ID
    registry_version: str = OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_VERSION
    offline_only: bool = True
    historical_research_only: bool = True
    neutral_execution_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_RESEARCH_NEUTRAL_EXECUTION_NON_OPERATIONAL_DECLARATION
    registry_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "registry_file", _ensure_path(self.registry_file, field_name="registry_file"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "updated_at_utc", _require_utc_datetime(self.updated_at_utc, "updated_at_utc"))
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "registry_id", _require_str(self.registry_id, "registry_id"))
        object.__setattr__(self, "registry_version", _require_str(self.registry_version, "registry_version"))
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "neutral_execution_only", _require_bool(self.neutral_execution_only, "neutral_execution_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.registry_id != OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_ID:
            raise OfflineResearchNeutralExecutionValidationError(
                "registry_id must remain offline_research_neutral_execution_registry."
            )
        if self.registry_version != OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_VERSION:
            raise OfflineResearchNeutralExecutionValidationError(
                "registry_version must remain phase47_neutral_offline_execution_registry_v1."
            )
        if self.offline_only is not True:
            raise OfflineResearchNeutralExecutionValidationError("offline_only must be true.")
        if self.historical_research_only is not True:
            raise OfflineResearchNeutralExecutionValidationError("historical_research_only must be true.")
        if self.neutral_execution_only is not True:
            raise OfflineResearchNeutralExecutionValidationError("neutral_execution_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchNeutralExecutionValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchNeutralExecutionValidationError("paper_promotion_eligible must be false.")
        if self.non_operational_declaration != OFFLINE_RESEARCH_NEUTRAL_EXECUTION_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchNeutralExecutionValidationError(
                "non_operational_declaration diverges from the neutral registry contract."
            )
        _validate_chain(self.records)
        expected_hash = _hash_payload(self.canonical_payload(include_registry_hash=False))
        if self.registry_hash:
            if self.registry_hash != expected_hash:
                raise OfflineResearchNeutralExecutionIntegrityError("registry_hash mismatch.")
        else:
            object.__setattr__(self, "registry_hash", expected_hash)

    @property
    def record_count(self) -> int:
        return len(self.records)

    def canonical_payload(self, *, include_registry_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "registry_file": self.registry_file.resolve().as_posix(),
            "created_at_utc": _utc_iso(self.created_at_utc),
            "updated_at_utc": _utc_iso(self.updated_at_utc),
            "registry_id": self.registry_id,
            "registry_version": self.registry_version,
            "record_count": self.record_count,
            "records": [record.canonical_payload(include_result_hash=True) for record in self.records],
            "offline_only": self.offline_only,
            "historical_research_only": self.historical_research_only,
            "neutral_execution_only": self.neutral_execution_only,
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
    ) -> "OfflineResearchNeutralExecutionRegistry":
        if not isinstance(data, Mapping):
            raise OfflineResearchNeutralExecutionValidationError(
                "offline research neutral execution registry must be a mapping."
            )
        mapping = dict(data)
        allowed = {
            "schema_version",
            "registry_file",
            "created_at_utc",
            "updated_at_utc",
            "records",
            "registry_id",
            "registry_version",
            "record_count",
            "offline_only",
            "historical_research_only",
            "neutral_execution_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "non_operational_declaration",
            "registry_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise OfflineResearchNeutralExecutionValidationError(
                f"unexpected offline research neutral execution registry fields: {', '.join(extra)}."
            )
        if "records" not in mapping:
            raise OfflineResearchNeutralExecutionValidationError(
                "offline research neutral execution registry is incomplete."
            )
        try:
            return cls(
                registry_file=registry_file,
                schema_version=mapping.get("schema_version", OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_SCHEMA_VERSION),
                created_at_utc=mapping.get("created_at_utc", datetime.now(timezone.utc)),
                updated_at_utc=mapping.get("updated_at_utc", datetime.now(timezone.utc)),
                records=tuple(OfflineResearchNeutralExecutionResult.from_dict(item) for item in mapping.get("records", ())),
                registry_id=mapping.get("registry_id", OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_ID),
                registry_version=mapping.get("registry_version", OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_VERSION),
                offline_only=mapping.get("offline_only", True),
                historical_research_only=mapping.get("historical_research_only", True),
                neutral_execution_only=mapping.get("neutral_execution_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                non_operational_declaration=mapping.get(
                    "non_operational_declaration",
                    OFFLINE_RESEARCH_NEUTRAL_EXECUTION_NON_OPERATIONAL_DECLARATION,
                ),
                registry_hash=mapping.get("registry_hash", ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OfflineResearchNeutralExecutionValidationError(
                "offline research neutral execution registry is incomplete."
            ) from exc

    def result_by_neutral_execution_id(self, neutral_execution_id: str) -> OfflineResearchNeutralExecutionResult:
        target = _require_hex_digest(neutral_execution_id, "neutral_execution_id")
        for record in self.records:
            if record.neutral_execution_id == target:
                return record
        raise OfflineResearchNeutralExecutionValidationError(
            "neutral_execution_id was not found in the registry."
        )

    def with_result(
        self,
        result: OfflineResearchNeutralExecutionResult,
        *,
        updated_at_utc: datetime | None = None,
    ) -> "OfflineResearchNeutralExecutionRegistry":
        return OfflineResearchNeutralExecutionRegistry(
            registry_file=self.registry_file,
            schema_version=self.schema_version,
            created_at_utc=self.created_at_utc,
            updated_at_utc=updated_at_utc or datetime.now(timezone.utc),
            records=tuple(self.records) + (result,),
            registry_id=self.registry_id,
            registry_version=self.registry_version,
            offline_only=self.offline_only,
            historical_research_only=self.historical_research_only,
            neutral_execution_only=self.neutral_execution_only,
            operational_evidence=self.operational_evidence,
            paper_promotion_eligible=self.paper_promotion_eligible,
            non_operational_declaration=self.non_operational_declaration,
        )


def _validate_chain(records: tuple[OfflineResearchNeutralExecutionResult, ...]) -> None:
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    previous: OfflineResearchNeutralExecutionResult | None = None
    for index, record in enumerate(records, start=1):
        if record.execution_number != index:
            raise OfflineResearchNeutralExecutionIntegrityError("execution_number mismatch.")
        if record.neutral_execution_id in seen_ids:
            raise OfflineResearchNeutralExecutionConflictError("neutral_execution_id conflict.")
        if record.result_hash in seen_hashes:
            raise OfflineResearchNeutralExecutionConflictError("result_hash conflict.")
        seen_ids.add(record.neutral_execution_id)
        seen_hashes.add(record.result_hash)
        if index == 1:
            if record.previous_execution_id is not None or record.previous_execution_hash is not None:
                raise OfflineResearchNeutralExecutionIntegrityError(
                    "first execution must not reference a previous execution."
                )
        else:
            assert previous is not None
            if record.previous_execution_id != previous.neutral_execution_id:
                raise OfflineResearchNeutralExecutionIntegrityError("previous_execution_id mismatch.")
            if record.previous_execution_hash != previous.result_hash:
                raise OfflineResearchNeutralExecutionIntegrityError("previous_execution_hash mismatch.")
        previous = record


@dataclass(frozen=True, slots=True)
class OfflineResearchNeutralExecutionRegistryVerificationReport:
    schema_version: int = OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_SCHEMA_VERSION
    registry_file: Path = field(default_factory=Path)
    verified_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved: bool = True
    registry_id: str = OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_ID
    registry_version: str = OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_VERSION
    record_count: int = 0
    registry_hash: str = ""
    neutral_execution_ids: tuple[str, ...] = ()
    result_hashes: tuple[str, ...] = ()
    offline_only: bool = True
    historical_research_only: bool = True
    neutral_execution_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_RESEARCH_NEUTRAL_EXECUTION_NON_OPERATIONAL_DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_file", _ensure_path(self.registry_file, field_name="registry_file"))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "verified_at_utc", _require_utc_datetime(self.verified_at_utc, "verified_at_utc"))
        object.__setattr__(self, "approved", _require_bool(self.approved, "approved"))
        object.__setattr__(self, "registry_id", _require_str(self.registry_id, "registry_id"))
        object.__setattr__(self, "registry_version", _require_str(self.registry_version, "registry_version"))
        object.__setattr__(self, "record_count", _require_non_negative_int(self.record_count, "record_count"))
        object.__setattr__(self, "registry_hash", _require_hex_digest(self.registry_hash, "registry_hash") if self.registry_hash else "")
        object.__setattr__(self, "neutral_execution_ids", tuple(_require_hex_digest(item, "neutral_execution_id") for item in self.neutral_execution_ids))
        object.__setattr__(self, "result_hashes", tuple(_require_hex_digest(item, "result_hash") for item in self.result_hashes))
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "neutral_execution_only", _require_bool(self.neutral_execution_only, "neutral_execution_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.approved is not True:
            raise OfflineResearchNeutralExecutionValidationError("approved must be true.")

    def canonical_payload(self, *, include_registry_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "registry_file": self.registry_file.resolve().as_posix(),
            "verified_at_utc": _utc_iso(self.verified_at_utc),
            "approved": self.approved,
            "registry_id": self.registry_id,
            "registry_version": self.registry_version,
            "record_count": self.record_count,
            "neutral_execution_ids": self.neutral_execution_ids,
            "result_hashes": self.result_hashes,
            "offline_only": self.offline_only,
            "historical_research_only": self.historical_research_only,
            "neutral_execution_only": self.neutral_execution_only,
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


def _build_request_snapshot(request: OfflineResearchNeutralExecutionRequest) -> dict[str, Any]:
    return {
        "schema_version": request.schema_version,
        "request_hash": request.request_hash,
        "envelope_hash": request.envelope.envelope_hash,
        "envelope_id": request.envelope.envelope_id,
        "fixture_directory": request.fixture_directory.resolve().as_posix(),
        "registry_file": request.registry_file.resolve().as_posix(),
        "output_directory": request.output_directory.resolve().as_posix(),
        "random_seed": request.random_seed,
        "resource_limits": _thaw_read_only_value(request.resource_limits),
        "execution_environment": _thaw_read_only_value(request.execution_environment),
        "output_policy": _thaw_read_only_value(request.output_policy),
        "offline_only": request.offline_only,
        "historical_research_only": request.historical_research_only,
        "neutral_execution_only": request.neutral_execution_only,
        "network_access_allowed": request.network_access_allowed,
        "exchange_connectivity_allowed": request.exchange_connectivity_allowed,
        "paper_trading_allowed": request.paper_trading_allowed,
        "live_trading_allowed": request.live_trading_allowed,
        "order_submission_allowed": request.order_submission_allowed,
        "strategy_execution_allowed": request.strategy_execution_allowed,
        "operational_evidence": request.operational_evidence,
        "paper_promotion_eligible": request.paper_promotion_eligible,
        "non_operational_declaration": request.non_operational_declaration,
    }


def _ensure_output_capacity(output_directory: Path, result: OfflineResearchNeutralExecutionResult) -> None:
    canonical = _canonical_json(result.as_dict())
    if len(canonical.encode("utf-8")) > result.resource_limits_snapshot.get("max_output_bytes", 0):
        raise OfflineResearchNeutralExecutionResourceLimitError("max_output_bytes exceeded.")
    output_directory.mkdir(parents=True, exist_ok=True)


def build_neutral_execution_request(
    *,
    envelope: phase46.OfflineResearchExecutionEnvelope,
    fixture_directory: str | Path,
    output_directory: str | Path,
    registry_file: str | Path | None = None,
    created_at_utc: datetime | None = None,
    random_seed: int = 0,
) -> OfflineResearchNeutralExecutionRequest:
    if registry_file is None:
        registry_file = Path(output_directory) / OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_FILENAME
    request = OfflineResearchNeutralExecutionRequest(
        envelope=envelope,
        fixture_directory=fixture_directory,
        registry_file=registry_file,
        output_directory=output_directory,
        created_at_utc=created_at_utc or datetime.now(timezone.utc),
        random_seed=random_seed,
        resource_limits=envelope.resource_limits,
        execution_environment=envelope.execution_environment,
        output_policy=envelope.output_policy,
        offline_only=envelope.offline_only,
        historical_research_only=envelope.historical_research_only,
        neutral_execution_only=True,
        network_access_allowed=envelope.network_access_allowed,
        exchange_connectivity_allowed=envelope.exchange_connectivity_allowed,
        paper_trading_allowed=envelope.paper_trading_allowed,
        live_trading_allowed=envelope.live_trading_allowed,
        order_submission_allowed=envelope.order_submission_allowed,
        strategy_execution_allowed=envelope.strategy_execution_allowed,
        operational_evidence=envelope.operational_evidence,
        paper_promotion_eligible=envelope.paper_promotion_eligible,
        non_operational_declaration=envelope.non_operational_declaration,
    )
    return verify_neutral_execution_request(request)


def verify_neutral_execution_request(
    request: OfflineResearchNeutralExecutionRequest,
) -> OfflineResearchNeutralExecutionRequest:
    if not isinstance(request, OfflineResearchNeutralExecutionRequest):
        raise OfflineResearchNeutralExecutionValidationError(
            "offline research neutral execution request is required."
        )
    verified_envelope = phase46.verify_offline_research_execution_envelope(request.envelope)
    if verified_envelope is not request.envelope:
        object.__setattr__(request, "envelope", verified_envelope)
    try:
        authorization = phase45.OfflineResearchExecutionAuthorization.from_dict(dict(request.envelope.authorization_snapshot))
    except (HistoricalDataError, ValueError) as exc:
        raise OfflineResearchNeutralExecutionValidationError(
            f"authorization must allow future offline execution: {exc}"
        ) from exc
    if authorization.authorization_id != request.envelope.authorization_id:
        raise OfflineResearchNeutralExecutionIntegrityError("authorization_id mismatch.")
    if authorization.authorization_hash != request.envelope.authorization_hash:
        raise OfflineResearchNeutralExecutionIntegrityError("authorization_hash mismatch.")
    if authorization.allow_future_offline_execution is not True:
        raise OfflineResearchNeutralExecutionValidationError(
            "authorization must allow future offline execution."
        )
    if authorization.offline_only is not True:
        raise OfflineResearchNeutralExecutionValidationError("authorization offline_only must be true.")
    if authorization.historical_research_only is not True:
        raise OfflineResearchNeutralExecutionValidationError("authorization historical_research_only must be true.")
    if authorization.operational_evidence is not False:
        raise OfflineResearchNeutralExecutionValidationError("authorization operational_evidence must be false.")
    if authorization.paper_promotion_eligible is not False:
        raise OfflineResearchNeutralExecutionValidationError("authorization paper_promotion_eligible must be false.")
    if request.resource_limits != request.envelope.resource_limits:
        raise OfflineResearchNeutralExecutionValidationError("resource_limits diverge from the envelope.")
    if request.execution_environment != request.envelope.execution_environment:
        raise OfflineResearchNeutralExecutionValidationError("execution_environment diverge from the envelope.")
    if request.output_policy != request.envelope.output_policy:
        raise OfflineResearchNeutralExecutionValidationError("output_policy diverge from the envelope.")
    expected_hash = _hash_payload(request._request_identity_payload())
    if request.request_hash != expected_hash:
        raise OfflineResearchNeutralExecutionIntegrityError("request_hash mismatch.")
    _ensure_allowed_neutral_policies(
        offline_only=request.offline_only,
        historical_research_only=request.historical_research_only,
        neutral_execution_only=request.neutral_execution_only,
        network_access_allowed=request.network_access_allowed,
        exchange_connectivity_allowed=request.exchange_connectivity_allowed,
        paper_trading_allowed=request.paper_trading_allowed,
        live_trading_allowed=request.live_trading_allowed,
        order_submission_allowed=request.order_submission_allowed,
        strategy_execution_allowed=request.strategy_execution_allowed,
        operational_evidence=request.operational_evidence,
        paper_promotion_eligible=request.paper_promotion_eligible,
        non_operational_declaration=request.non_operational_declaration,
    )
    return request


def _build_result(
    request: OfflineResearchNeutralExecutionRequest,
    *,
    fixture_verification: phase44_fixture.CanonicalOfflineResearchEvidenceVerification,
    input_record_count: int,
    first_record_timestamp: str,
    last_record_timestamp: str,
    ordered_records: tuple[str, ...],
    duplicate_record_count: int,
    missing_record_count: int,
    input_sequence_hash: str,
    neutral_transform_hash: str,
    canonical_field_set_hash: str,
    started_at_utc: datetime,
    finished_at_utc: datetime,
    elapsed_monotonic_ns: int,
    status: str,
    failure_code: str = "",
    failure_message: str = "",
    previous_execution_id: str | None = None,
    previous_execution_hash: str | None = None,
    execution_number: int = 1,
) -> OfflineResearchNeutralExecutionResult:
    envelope = request.envelope
    payload = {
        "schema_version": OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_SCHEMA_VERSION,
        "executor_name": OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_NAME,
        "executor_version": OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_VERSION,
        "neutral_operation_name": OFFLINE_RESEARCH_NEUTRAL_OPERATION_NAME,
        "neutral_operation_version": OFFLINE_RESEARCH_NEUTRAL_OPERATION_VERSION,
        "request_hash": request.request_hash,
        "envelope_id": envelope.envelope_id,
        "envelope_hash": envelope.envelope_hash,
        "input_sequence_hash": input_sequence_hash,
        "random_seed": request.random_seed,
        "status": status,
        "execution_number": execution_number,
    }
    neutral_execution_id = _hash_payload(payload)
    result = OfflineResearchNeutralExecutionResult(
        neutral_execution_id=neutral_execution_id,
        execution_number=execution_number,
        created_at_utc=request.created_at_utc,
        executor_name=OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_NAME,
        executor_version=OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_VERSION,
        neutral_operation_name=OFFLINE_RESEARCH_NEUTRAL_OPERATION_NAME,
        neutral_operation_version=OFFLINE_RESEARCH_NEUTRAL_OPERATION_VERSION,
        request_hash=request.request_hash,
        envelope_id=envelope.envelope_id,
        envelope_hash=envelope.envelope_hash,
        experiment_id=envelope.experiment_id,
        execution_id=envelope.execution_id,
        plan_id=envelope.plan_id,
        evidence_id=envelope.evidence_id,
        authorization_id=envelope.authorization_id,
        strategy_id=envelope.strategy_id,
        strategy_version=envelope.strategy_version,
        strategy_fingerprint=envelope.strategy_fingerprint,
        input_record_count=input_record_count,
        expected_record_count=request.envelope.expected_candle_count,
        first_record_timestamp=first_record_timestamp,
        last_record_timestamp=last_record_timestamp,
        min_timestamp=first_record_timestamp,
        max_timestamp=last_record_timestamp,
        ordered_records=ordered_records,
        duplicate_record_count=duplicate_record_count,
        missing_record_count=missing_record_count,
        input_sequence_hash=input_sequence_hash,
        neutral_transform_hash=neutral_transform_hash,
        canonical_field_set_hash=canonical_field_set_hash,
        random_seed=request.random_seed,
        resource_limits_snapshot=request.resource_limits,
        execution_environment_snapshot=request.execution_environment,
        output_policy_snapshot=request.output_policy,
        started_at_utc=started_at_utc,
        finished_at_utc=finished_at_utc,
        elapsed_monotonic_ns=elapsed_monotonic_ns,
        status=status,
        failure_code=failure_code,
        failure_message=failure_message,
        offline_only=request.offline_only,
        historical_research_only=request.historical_research_only,
        neutral_execution_only=request.neutral_execution_only,
        network_access_used=request.network_access_allowed,
        exchange_connectivity_used=request.exchange_connectivity_allowed,
        paper_trading_used=request.paper_trading_allowed,
        live_trading_used=request.live_trading_allowed,
        order_submission_used=request.order_submission_allowed,
        strategy_execution_used=request.strategy_execution_allowed,
        operational_evidence=request.operational_evidence,
        paper_promotion_eligible=request.paper_promotion_eligible,
        non_operational_declaration=OFFLINE_RESEARCH_NEUTRAL_EXECUTION_NON_OPERATIONAL_DECLARATION,
        previous_execution_id=previous_execution_id,
        previous_execution_hash=previous_execution_hash,
    )
    _ensure_output_capacity(request.output_directory, result)
    return result


def execute_neutral_offline(
    request: OfflineResearchNeutralExecutionRequest,
    *,
    started_at_utc: datetime | None = None,
    finished_at_utc: datetime | None = None,
    elapsed_monotonic_ns: int | None = None,
) -> OfflineResearchNeutralExecutionResult:
    verified_request = verify_neutral_execution_request(request)
    registry_path = verified_request.registry_file
    if registry_path.exists():
        registry = load_neutral_execution_registry(registry_path)
        for existing in registry.records:
            if existing.request_hash == verified_request.request_hash:
                return existing

    fixture_verification = phase44_fixture.verify_canonical_offline_research_evidence_fixture(
        verified_request.fixture_directory
    )
    dataset = fixture_verification.dataset
    candles = tuple(dataset.candles)
    if len(candles) > verified_request.resource_limits["max_event_count"]:
        raise OfflineResearchNeutralExecutionResourceLimitError("max_event_count exceeded.")

    if not candles:
        raise OfflineResearchNeutralExecutionValidationError("fixture candles are missing.")

    duplicate_record_count = 0
    missing_record_count = 0
    ordered_records = tuple(_utc_iso(candle.open_time) for candle in candles)
    for previous, current in zip(candles, candles[1:]):
        if current.open_time == previous.open_time:
            duplicate_record_count += 1
        if current.open_time < previous.open_time:
            raise OfflineResearchNeutralExecutionValidationError("fixture records are not ordered.")
    if duplicate_record_count:
        raise OfflineResearchNeutralExecutionValidationError("duplicate record detected in fixture.")
    if missing_record_count:
        raise OfflineResearchNeutralExecutionValidationError("missing record detected in fixture.")

    input_sequence_hash = _hash_payload([candle.to_dict() for candle in candles])
    neutral_transform_payload = {
        "input_record_count": len(candles),
        "first_record_timestamp": _utc_iso(candles[0].open_time),
        "last_record_timestamp": _utc_iso(candles[-1].open_time),
        "ordered_records": ordered_records,
        "duplicate_record_count": duplicate_record_count,
        "missing_record_count": missing_record_count,
        "input_sequence_hash": input_sequence_hash,
        "neutral_operation_name": OFFLINE_RESEARCH_NEUTRAL_OPERATION_NAME,
        "neutral_operation_version": OFFLINE_RESEARCH_NEUTRAL_OPERATION_VERSION,
    }
    neutral_transform_hash = _hash_payload(neutral_transform_payload)
    canonical_field_set_hash = _hash_payload(tuple(sorted(candles[0].to_dict().keys())))
    started = started_at_utc or verified_request.created_at_utc
    finished = finished_at_utc or started
    elapsed = _require_non_negative_int(elapsed_monotonic_ns if elapsed_monotonic_ns is not None else 0, "elapsed_monotonic_ns")
    result = _build_result(
        verified_request,
        fixture_verification=fixture_verification,
        input_record_count=len(candles),
        first_record_timestamp=_utc_iso(candles[0].open_time),
        last_record_timestamp=_utc_iso(candles[-1].open_time),
        ordered_records=ordered_records,
        duplicate_record_count=duplicate_record_count,
        missing_record_count=missing_record_count,
        input_sequence_hash=input_sequence_hash,
        neutral_transform_hash=neutral_transform_hash,
        canonical_field_set_hash=canonical_field_set_hash,
        started_at_utc=started,
        finished_at_utc=finished,
        elapsed_monotonic_ns=elapsed,
        status="SUCCEEDED",
    )
    return register_neutral_execution_result(registry_file=registry_path, result=result)


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise OfflineResearchNeutralExecutionValidationError("offline research neutral execution registry is missing.")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise OfflineResearchNeutralExecutionValidationError("offline research neutral execution registry is empty.")
    try:
        return json.loads(text)
    except Exception as exc:
        raise OfflineResearchNeutralExecutionValidationError(
            "offline research neutral execution registry is invalid JSON."
        ) from exc


def load_neutral_execution_registry(
    registry_file: str | Path,
) -> OfflineResearchNeutralExecutionRegistry:
    path = _ensure_path(registry_file, field_name="registry_file")
    payload = _load_json(path)
    if not isinstance(payload, Mapping):
        raise OfflineResearchNeutralExecutionValidationError(
            "offline research neutral execution registry must be a JSON object."
        )
    registry = OfflineResearchNeutralExecutionRegistry.from_dict(payload, registry_file=path)
    if _canonical_json(registry.as_dict()) != _canonical_json(payload):
        raise OfflineResearchNeutralExecutionIntegrityError(
            "offline research neutral execution registry payload mismatch."
        )
    return registry


def _write_json_atomic(path: Path, payload: Any) -> None:
    canonical = _canonical_json(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == canonical:
        return
    tmp_path = path.with_name(f".{path.name}.{Path.cwd().name}.{id(payload)}.tmp")
    try:
        tmp_path.write_text(canonical, encoding="utf-8")
        tmp_path.replace(path)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise OfflineResearchNeutralExecutionPersistenceError(
            "failed to write offline research neutral execution registry atomically."
        ) from exc


def save_neutral_execution_registry(
    registry_file: str | Path,
    registry: OfflineResearchNeutralExecutionRegistry,
) -> OfflineResearchNeutralExecutionRegistry:
    path = _ensure_path(registry_file, field_name="registry_file")
    if not isinstance(registry, OfflineResearchNeutralExecutionRegistry):
        raise OfflineResearchNeutralExecutionValidationError(
            "offline research neutral execution registry is required."
        )
    _write_json_atomic(path, registry.as_dict())
    return registry


def verify_neutral_execution_result(
    result: OfflineResearchNeutralExecutionResult,
) -> OfflineResearchNeutralExecutionResult:
    if not isinstance(result, OfflineResearchNeutralExecutionResult):
        raise OfflineResearchNeutralExecutionValidationError(
            "offline research neutral execution result is required."
        )
    expected_hash = _hash_payload(result._result_identity_payload())
    if result.result_hash != expected_hash:
        raise OfflineResearchNeutralExecutionIntegrityError("result_hash mismatch.")
    expected_neutral_execution_id = _hash_payload(result._neutral_execution_identity_payload())
    if result.neutral_execution_id != expected_neutral_execution_id:
        raise OfflineResearchNeutralExecutionIntegrityError("neutral_execution_id mismatch.")
    return result


def register_neutral_execution_result(
    *,
    registry_file: str | Path,
    result: OfflineResearchNeutralExecutionResult,
    updated_at_utc: datetime | None = None,
) -> OfflineResearchNeutralExecutionResult:
    path = _ensure_path(registry_file, field_name="registry_file")
    result = verify_neutral_execution_result(result)
    registry = (
        load_neutral_execution_registry(path)
        if path.exists()
        else OfflineResearchNeutralExecutionRegistry(
            registry_file=path,
            created_at_utc=updated_at_utc or result.created_at_utc,
            updated_at_utc=updated_at_utc or result.created_at_utc,
        )
    )
    for existing in registry.records:
        if existing.neutral_execution_id == result.neutral_execution_id:
            if existing.as_dict() == result.as_dict():
                return existing
            raise OfflineResearchNeutralExecutionConflictError("neutral_execution_id already registered and differs.")
    if registry.records:
        latest = registry.records[-1]
        if result.execution_number != latest.execution_number + 1:
            raise OfflineResearchNeutralExecutionConflictError("execution_number must follow the existing chain.")
        if result.previous_execution_id != latest.neutral_execution_id or result.previous_execution_hash != latest.result_hash:
            raise OfflineResearchNeutralExecutionConflictError(
                "previous execution reference must match the latest registered result."
            )
    elif result.execution_number != 1 or result.previous_execution_id is not None or result.previous_execution_hash is not None:
        raise OfflineResearchNeutralExecutionConflictError(
            "the first execution in a chain must have execution_number 1."
        )
    updated_registry = registry.with_result(result, updated_at_utc=updated_at_utc or result.created_at_utc)
    save_neutral_execution_registry(path, updated_registry)
    return result


def verify_neutral_execution_registry(
    registry_file: str | Path,
) -> OfflineResearchNeutralExecutionRegistryVerificationReport:
    path = _ensure_path(registry_file, field_name="registry_file")
    registry = load_neutral_execution_registry(path)
    report = OfflineResearchNeutralExecutionRegistryVerificationReport(
        registry_file=path,
        verified_at_utc=registry.updated_at_utc,
        approved=True,
        registry_id=registry.registry_id,
        registry_version=registry.registry_version,
        record_count=registry.record_count,
        registry_hash=registry.registry_hash,
        neutral_execution_ids=tuple(record.neutral_execution_id for record in registry.records),
        result_hashes=tuple(record.result_hash for record in registry.records),
        offline_only=registry.offline_only,
        historical_research_only=registry.historical_research_only,
        neutral_execution_only=registry.neutral_execution_only,
        operational_evidence=registry.operational_evidence,
        paper_promotion_eligible=registry.paper_promotion_eligible,
        non_operational_declaration=registry.non_operational_declaration,
    )
    if _canonical_json(report.as_dict()) != _canonical_json(report.canonical_payload(include_registry_hash=True)):
        raise OfflineResearchNeutralExecutionIntegrityError(
            "registry verification report payload mismatch."
        )
    return report


def _result_from_dict(data: Mapping[str, Any]) -> OfflineResearchNeutralExecutionResult:
    if not isinstance(data, Mapping):
        raise OfflineResearchNeutralExecutionValidationError(
            "offline research neutral execution result must be a mapping."
        )
    mapping = dict(data)
    allowed = {
        "schema_version",
        "neutral_execution_id",
        "execution_number",
        "created_at_utc",
        "executor_name",
        "executor_version",
        "neutral_operation_name",
        "neutral_operation_version",
        "request_hash",
        "envelope_id",
        "envelope_hash",
        "experiment_id",
        "execution_id",
        "plan_id",
        "evidence_id",
        "authorization_id",
        "strategy_id",
        "strategy_version",
        "strategy_fingerprint",
        "input_record_count",
        "expected_record_count",
        "first_record_timestamp",
        "last_record_timestamp",
        "min_timestamp",
        "max_timestamp",
        "ordered_records",
        "duplicate_record_count",
        "missing_record_count",
        "input_sequence_hash",
        "neutral_transform_hash",
        "canonical_field_set_hash",
        "random_seed",
        "resource_limits_snapshot",
        "execution_environment_snapshot",
        "output_policy_snapshot",
        "started_at_utc",
        "finished_at_utc",
        "elapsed_monotonic_ns",
        "status",
        "failure_code",
        "failure_message",
        "offline_only",
        "historical_research_only",
        "neutral_execution_only",
        "network_access_used",
        "exchange_connectivity_used",
        "paper_trading_used",
        "live_trading_used",
        "order_submission_used",
        "strategy_execution_used",
        "operational_evidence",
        "paper_promotion_eligible",
        "non_operational_declaration",
        "previous_execution_id",
        "previous_execution_hash",
        "result_hash",
    }
    extra = sorted(set(mapping) - allowed)
    if extra:
        raise OfflineResearchNeutralExecutionValidationError(
            f"unexpected offline research neutral execution result fields: {', '.join(extra)}."
        )
    try:
        return OfflineResearchNeutralExecutionResult(
            schema_version=mapping.get("schema_version", OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_SCHEMA_VERSION),
            neutral_execution_id=mapping.get("neutral_execution_id", ""),
            execution_number=mapping.get("execution_number", 0),
            created_at_utc=mapping.get("created_at_utc", datetime.now(timezone.utc)),
            executor_name=mapping.get("executor_name", OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_NAME),
            executor_version=mapping.get("executor_version", OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_VERSION),
            neutral_operation_name=mapping.get(
                "neutral_operation_name",
                OFFLINE_RESEARCH_NEUTRAL_OPERATION_NAME,
            ),
            neutral_operation_version=mapping.get(
                "neutral_operation_version",
                OFFLINE_RESEARCH_NEUTRAL_OPERATION_VERSION,
            ),
            request_hash=mapping.get("request_hash", ""),
            envelope_id=mapping.get("envelope_id", ""),
            envelope_hash=mapping.get("envelope_hash", ""),
            experiment_id=mapping.get("experiment_id", ""),
            execution_id=mapping.get("execution_id", ""),
            plan_id=mapping.get("plan_id", ""),
            evidence_id=mapping.get("evidence_id", ""),
            authorization_id=mapping.get("authorization_id", ""),
            strategy_id=mapping.get("strategy_id", ""),
            strategy_version=mapping.get("strategy_version", ""),
            strategy_fingerprint=mapping.get("strategy_fingerprint", ""),
            input_record_count=mapping.get("input_record_count", 0),
            expected_record_count=mapping.get("expected_record_count", 0),
            first_record_timestamp=mapping.get("first_record_timestamp", ""),
            last_record_timestamp=mapping.get("last_record_timestamp", ""),
            min_timestamp=mapping.get("min_timestamp", ""),
            max_timestamp=mapping.get("max_timestamp", ""),
            ordered_records=tuple(mapping.get("ordered_records", ())),
            duplicate_record_count=mapping.get("duplicate_record_count", 0),
            missing_record_count=mapping.get("missing_record_count", 0),
            input_sequence_hash=mapping.get("input_sequence_hash", ""),
            neutral_transform_hash=mapping.get("neutral_transform_hash", ""),
            canonical_field_set_hash=mapping.get("canonical_field_set_hash", ""),
            random_seed=mapping.get("random_seed", 0),
            resource_limits_snapshot=mapping.get("resource_limits_snapshot", {}),
            execution_environment_snapshot=mapping.get("execution_environment_snapshot", {}),
            output_policy_snapshot=mapping.get("output_policy_snapshot", {}),
            started_at_utc=mapping.get("started_at_utc", datetime.now(timezone.utc)),
            finished_at_utc=mapping.get("finished_at_utc", datetime.now(timezone.utc)),
            elapsed_monotonic_ns=mapping.get("elapsed_monotonic_ns", 0),
            status=mapping.get("status", "SUCCEEDED"),
            failure_code=mapping.get("failure_code", ""),
            failure_message=mapping.get("failure_message", ""),
            offline_only=mapping.get("offline_only", True),
            historical_research_only=mapping.get("historical_research_only", True),
            neutral_execution_only=mapping.get("neutral_execution_only", True),
            network_access_used=mapping.get("network_access_used", False),
            exchange_connectivity_used=mapping.get("exchange_connectivity_used", False),
            paper_trading_used=mapping.get("paper_trading_used", False),
            live_trading_used=mapping.get("live_trading_used", False),
            order_submission_used=mapping.get("order_submission_used", False),
            strategy_execution_used=mapping.get("strategy_execution_used", False),
            operational_evidence=mapping.get("operational_evidence", False),
            paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
            non_operational_declaration=mapping.get(
                "non_operational_declaration",
                OFFLINE_RESEARCH_NEUTRAL_EXECUTION_NON_OPERATIONAL_DECLARATION,
            ),
            previous_execution_id=mapping.get("previous_execution_id"),
            previous_execution_hash=mapping.get("previous_execution_hash"),
            result_hash=mapping.get("result_hash", ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OfflineResearchNeutralExecutionValidationError(
            "offline research neutral execution result is incomplete."
        ) from exc


OfflineResearchNeutralExecutionResult.from_dict = staticmethod(_result_from_dict)  # type: ignore[attr-defined]


def _build_result_summary_for_fixture(
    request: OfflineResearchNeutralExecutionRequest,
    fixture_verification: phase44_fixture.CanonicalOfflineResearchEvidenceVerification,
    *,
    started_at_utc: datetime,
    finished_at_utc: datetime,
    elapsed_monotonic_ns: int,
    execution_number: int,
    previous_execution_id: str | None,
    previous_execution_hash: str | None,
) -> OfflineResearchNeutralExecutionResult:
    dataset = fixture_verification.dataset
    candles = tuple(dataset.candles)
    expected_count = request.envelope.expected_candle_count
    if len(candles) > request.resource_limits["max_event_count"]:
        raise OfflineResearchNeutralExecutionResourceLimitError("max_event_count exceeded.")
    if not candles:
        raise OfflineResearchNeutralExecutionValidationError("fixture candles are missing.")

    ordered_records = tuple(_utc_iso(candle.open_time) for candle in candles)
    duplicate_record_count = 0
    missing_record_count = 0
    for previous, current in zip(candles, candles[1:]):
        if current.open_time == previous.open_time:
            duplicate_record_count += 1
        if current.open_time < previous.open_time:
            raise OfflineResearchNeutralExecutionValidationError("fixture records are not ordered.")
        if current.open_time != previous.open_time + phase44_fixture.ONE_HOUR if hasattr(phase44_fixture, "ONE_HOUR") else previous.open_time + datetime.resolution:
            pass
    # We compute gaps explicitly to keep the procedure fail-closed and deterministic.
    for previous, current in zip(candles, candles[1:]):
        gap_hours = int((current.open_time - previous.open_time).total_seconds() // 3600) - 1
        if gap_hours > 0:
            missing_record_count += gap_hours
    if duplicate_record_count:
        raise OfflineResearchNeutralExecutionValidationError("duplicate record detected in fixture.")
    if missing_record_count:
        raise OfflineResearchNeutralExecutionValidationError("missing record detected in fixture.")

    input_sequence_hash = _hash_payload([candle.to_dict() for candle in candles])
    neutral_transform_hash = _hash_payload(
        {
            "input_record_count": len(candles),
            "first_record_timestamp": _utc_iso(candles[0].open_time),
            "last_record_timestamp": _utc_iso(candles[-1].open_time),
            "ordered_records": ordered_records,
            "duplicate_record_count": duplicate_record_count,
            "missing_record_count": missing_record_count,
            "input_sequence_hash": input_sequence_hash,
            "neutral_operation_name": OFFLINE_RESEARCH_NEUTRAL_OPERATION_NAME,
            "neutral_operation_version": OFFLINE_RESEARCH_NEUTRAL_OPERATION_VERSION,
        }
    )
    canonical_field_set_hash = _hash_payload(tuple(sorted(candles[0].to_dict().keys())))
    result = _build_result(
        request,
        fixture_verification=fixture_verification,
        input_record_count=len(candles),
        first_record_timestamp=_utc_iso(candles[0].open_time),
        last_record_timestamp=_utc_iso(candles[-1].open_time),
        ordered_records=ordered_records,
        duplicate_record_count=duplicate_record_count,
        missing_record_count=missing_record_count,
        input_sequence_hash=input_sequence_hash,
        neutral_transform_hash=neutral_transform_hash,
        canonical_field_set_hash=canonical_field_set_hash,
        started_at_utc=started_at_utc,
        finished_at_utc=finished_at_utc,
        elapsed_monotonic_ns=elapsed_monotonic_ns,
        status="SUCCEEDED",
        execution_number=execution_number,
        previous_execution_id=previous_execution_id,
        previous_execution_hash=previous_execution_hash,
    )
    _ensure_output_capacity(request.output_directory, result)
    return result


def _materialize_result(
    request: OfflineResearchNeutralExecutionRequest,
    *,
    started_at_utc: datetime | None = None,
    finished_at_utc: datetime | None = None,
    elapsed_monotonic_ns: int | None = None,
    execution_number: int = 1,
    previous_execution_id: str | None = None,
    previous_execution_hash: str | None = None,
) -> OfflineResearchNeutralExecutionResult:
    try:
        fixture_verification = phase44_fixture.verify_canonical_offline_research_evidence_fixture(
            request.fixture_directory
        )
    except (ValueError, HistoricalDataError) as exc:
        raise OfflineResearchNeutralExecutionValidationError(
            f"canonical fixture verification failed: {exc}"
        ) from exc
    started = started_at_utc or request.created_at_utc
    finished = finished_at_utc or started
    elapsed = _require_non_negative_int(elapsed_monotonic_ns if elapsed_monotonic_ns is not None else 0, "elapsed_monotonic_ns")
    return _build_result_summary_for_fixture(
        request,
        fixture_verification,
        started_at_utc=started,
        finished_at_utc=finished,
        elapsed_monotonic_ns=elapsed,
        execution_number=execution_number,
        previous_execution_id=previous_execution_id,
        previous_execution_hash=previous_execution_hash,
    )


def execute_neutral_offline(
    request: OfflineResearchNeutralExecutionRequest,
    *,
    started_at_utc: datetime | None = None,
    finished_at_utc: datetime | None = None,
    elapsed_monotonic_ns: int | None = None,
) -> OfflineResearchNeutralExecutionResult:
    verified_request = verify_neutral_execution_request(request)
    registry_path = verified_request.registry_file
    execution_number = 1
    previous_execution_id: str | None = None
    previous_execution_hash: str | None = None
    if registry_path.exists():
        registry = load_neutral_execution_registry(registry_path)
        for existing in registry.records:
            if existing.request_hash == verified_request.request_hash:
                return existing
        if registry.records:
            latest = registry.records[-1]
            execution_number = latest.execution_number + 1
            previous_execution_id = latest.neutral_execution_id
            previous_execution_hash = latest.result_hash
    try:
        result = _materialize_result(
            verified_request,
            started_at_utc=started_at_utc,
            finished_at_utc=finished_at_utc,
            elapsed_monotonic_ns=elapsed_monotonic_ns,
            execution_number=execution_number,
            previous_execution_id=previous_execution_id,
            previous_execution_hash=previous_execution_hash,
        )
    except OfflineResearchNeutralExecutionResourceLimitError:
        raise
    except OfflineResearchNeutralExecutionValidationError:
        raise
    return register_neutral_execution_result(registry_file=registry_path, result=result)


__all__ = [
    "OFFLINE_RESEARCH_NEUTRAL_EXECUTION_ALLOWED_STATUSES",
    "OFFLINE_RESEARCH_NEUTRAL_EXECUTION_DEFAULT_EXECUTION_ENVIRONMENT",
    "OFFLINE_RESEARCH_NEUTRAL_EXECUTION_DEFAULT_OUTPUT_POLICY",
    "OFFLINE_RESEARCH_NEUTRAL_EXECUTION_DEFAULT_RESOURCE_LIMITS",
    "OFFLINE_RESEARCH_NEUTRAL_EXECUTION_NON_OPERATIONAL_DECLARATION",
    "OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_FILENAME",
    "OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_ID",
    "OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REGISTRY_VERSION",
    "OFFLINE_RESEARCH_NEUTRAL_EXECUTION_RESULT_VERSION",
    "OFFLINE_RESEARCH_NEUTRAL_EXECUTION_REQUEST_VERSION",
    "OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_NAME",
    "OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_SCHEMA_VERSION",
    "OFFLINE_RESEARCH_NEUTRAL_EXECUTOR_VERSION",
    "OFFLINE_RESEARCH_NEUTRAL_OPERATION_NAME",
    "OFFLINE_RESEARCH_NEUTRAL_OPERATION_VERSION",
    "OfflineResearchNeutralExecutionConflictError",
    "OfflineResearchNeutralExecutionError",
    "OfflineResearchNeutralExecutionIntegrityError",
    "OfflineResearchNeutralExecutionPersistenceError",
    "OfflineResearchNeutralExecutionRegistry",
    "OfflineResearchNeutralExecutionRegistryVerificationReport",
    "OfflineResearchNeutralExecutionRequest",
    "OfflineResearchNeutralExecutionResult",
    "OfflineResearchNeutralExecutionResourceLimitError",
    "OfflineResearchNeutralExecutionValidationError",
    "build_neutral_execution_request",
    "execute_neutral_offline",
    "load_neutral_execution_registry",
    "register_neutral_execution_result",
    "save_neutral_execution_registry",
    "verify_neutral_execution_registry",
    "verify_neutral_execution_request",
    "verify_neutral_execution_result",
]
