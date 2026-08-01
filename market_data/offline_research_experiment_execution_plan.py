from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from types import MappingProxyType
from decimal import Decimal
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value

from . import offline_research_experiment_execution_registry as execution_registry
from .errors import (
    HistoricalDataConflictError,
    HistoricalDataError,
    HistoricalDataIntegrityError,
    HistoricalDataValidationError,
)

OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_SCHEMA_VERSION = 1
OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REGISTRY_ID = "offline_research_experiment_execution_plan_registry"
OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REGISTRY_VERSION = "phase43_offline_experiment_execution_plan_registry_v1"
OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_RESEARCH_MODE = "OFFLINE_EXECUTION_PREPARATION"
OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_ALLOWED_RESEARCH_MODES = (
    OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_RESEARCH_MODE,
)
OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REQUIRED_PRECONDITIONS = (
    "PHASE_41_EXPERIMENT_REGISTRATION_VALID",
    "PHASE_42_EXECUTION_REGISTRATION_VALID",
    "DATASET_IDENTITY_MATCHES",
    "STRATEGY_IDENTITY_MATCHES",
    "WINDOW_WITHIN_ARTIFACT",
    "NO_OPERATIONAL_PERMISSION",
    "SOURCE_COMMIT_RECORDED",
)
OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REQUIRED_ABORT_CONDITIONS = (
    "EXPERIMENT_REGISTRATION_INTEGRITY_FAILURE",
    "EXECUTION_REGISTRATION_INTEGRITY_FAILURE",
    "DATASET_IDENTITY_MISMATCH",
    "STRATEGY_IDENTITY_MISMATCH",
    "WINDOW_OUTSIDE_ARTIFACT",
    "SCHEMA_MISMATCH",
    "HASH_MISMATCH",
    "OPERATIONAL_PERMISSION_DETECTED",
    "SOURCE_COMMIT_MISMATCH",
)
OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_NON_OPERATIONAL_DECLARATION = (
    "This plan is research-only and does not authorize or perform replay, backtest, walk-forward, "
    "performance evaluation, ranking, paper trading, live trading, exchange connectivity, strategy "
    "execution, position management, or order submission."
)


class OfflineResearchExperimentExecutionPlanError(HistoricalDataError):
    pass


class OfflineResearchExperimentExecutionPlanValidationError(
    OfflineResearchExperimentExecutionPlanError, HistoricalDataValidationError
):
    pass


class OfflineResearchExperimentExecutionPlanIntegrityError(
    OfflineResearchExperimentExecutionPlanError, HistoricalDataIntegrityError
):
    pass


class OfflineResearchExperimentExecutionPlanConflictError(
    OfflineResearchExperimentExecutionPlanError, HistoricalDataConflictError
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    try:
        return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    except TypeError as exc:
        raise OfflineResearchExperimentExecutionPlanValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineResearchExperimentExecutionPlanValidationError(f"{field_name} is required.")
    return value.strip()


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineResearchExperimentExecutionPlanValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineResearchExperimentExecutionPlanValidationError(f"{field_name} must be a boolean.")
    return value


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchExperimentExecutionPlanValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_commit_sha(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 40 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchExperimentExecutionPlanValidationError(
            f"{field_name} must be a 40-character hex git commit sha."
        )
    return digest


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise OfflineResearchExperimentExecutionPlanValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise OfflineResearchExperimentExecutionPlanValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineResearchExperimentExecutionPlanValidationError(
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
        raise OfflineResearchExperimentExecutionPlanValidationError(
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
    if isinstance(value, set) or isinstance(value, frozenset):
        thawed_items = [_thaw_read_only_value(item) for item in value]
        return tuple(sorted(thawed_items, key=_canonical_json))
    return value


def _normalize_string_sequence(
    value: Sequence[str] | set[str] | frozenset[str] | None,
    *,
    field_name: str,
    required_items: tuple[str, ...],
) -> tuple[str, ...]:
    if value is None:
        candidate_items = required_items
    elif isinstance(value, (str, bytes)) or not isinstance(value, (Sequence, set, frozenset)):
        raise OfflineResearchExperimentExecutionPlanValidationError(
            f"{field_name} must be a non-empty sequence of strings."
        )
    else:
        candidate_items = tuple(value)

    if not candidate_items:
        raise OfflineResearchExperimentExecutionPlanValidationError(f"{field_name} must not be empty.")

    seen: set[str] = set()
    normalized: list[str] = []
    required_set = set(required_items)
    for item in candidate_items:
        normalized_item = _require_str(item, field_name[:-1] if field_name.endswith("s") else field_name)
        if normalized_item not in required_set:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                f"{field_name} contains an unexpected value."
            )
        if normalized_item in seen:
            raise OfflineResearchExperimentExecutionPlanValidationError(f"{field_name} contains duplicates.")
        seen.add(normalized_item)
        normalized.append(normalized_item)

    if seen != required_set:
        missing = [item for item in required_items if item not in seen]
        raise OfflineResearchExperimentExecutionPlanValidationError(
            f"{field_name} is missing required values: {', '.join(missing)}."
        )
    return tuple(item for item in required_items if item in seen)


def _normalize_research_mode(value: Any) -> str:
    mode = _require_str(value, "research_mode").upper()
    if mode not in OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_ALLOWED_RESEARCH_MODES:
        raise OfflineResearchExperimentExecutionPlanValidationError("research_mode is not allowed.")
    return mode


def _normalize_execution_registration_source(
    *,
    execution_registration: execution_registry.OfflineResearchExperimentExecutionRegistration | Mapping[str, Any] | None = None,
    execution_registry_file: str | Path | None = None,
    execution_id: str | None = None,
    execution_hash: str | None = None,
) -> execution_registry.OfflineResearchExperimentExecutionRegistration:
    if execution_registration is not None:
        if any(value is not None for value in (execution_registry_file, execution_id, execution_hash)):
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "provide either a phase 42 execution registration or registry lookup parameters, not both."
            )
        if isinstance(execution_registration, execution_registry.OfflineResearchExperimentExecutionRegistration):
            return execution_registration
        if isinstance(execution_registration, Mapping):
            try:
                return execution_registry.OfflineResearchExperimentExecutionRegistration.from_dict(
                    dict(execution_registration)
                )
            except Exception as exc:
                raise OfflineResearchExperimentExecutionPlanValidationError(
                    "execution_registration snapshot is invalid."
                ) from exc
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "a verified phase 42 execution registration is required."
        )

    if execution_registry_file is None:
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "execution_registry_file is required when execution_registration is not provided."
        )

    registry_path = _ensure_registry_path(execution_registry_file, field_name="execution_registry_file")
    if execution_hash is None and execution_id is None:
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "execution_id or execution_hash is required when execution_registration is not provided."
        )

    registry = execution_registry.load_offline_research_experiment_execution_registry(registry_path)
    try:
        if execution_id is not None:
            record = registry.registration_by_execution_id(execution_id)
            if execution_hash is not None and record.execution_hash != _require_hex_digest(
                execution_hash,
                "execution_hash",
            ):
                raise OfflineResearchExperimentExecutionPlanIntegrityError("execution_hash mismatch.")
            return record
        record = registry.registration_by_execution_hash(execution_hash or "")
        return record
    except execution_registry.OfflineResearchExperimentExecutionRegistryError as exc:
        raise OfflineResearchExperimentExecutionPlanValidationError(str(exc)) from exc


def _execution_snapshot_payload(
    execution_record: execution_registry.OfflineResearchExperimentExecutionRegistration,
) -> Mapping[str, Any]:
    return _freeze_read_only_value(dict(execution_record.as_dict()))


def _extract_contract_snapshot(
    execution_record: execution_registry.OfflineResearchExperimentExecutionRegistration,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    snapshot = execution_record.experiment_registration_snapshot
    if not isinstance(snapshot, Mapping):
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "execution registration snapshot is incomplete."
        )
    try:
        contract_snapshot = snapshot["contract_snapshot"]
        artifact_reference_snapshot = snapshot["artifact_reference_snapshot"]
        strategy_contract_snapshot = contract_snapshot["strategy_contract"]
    except Exception as exc:
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "execution registration snapshot is incomplete."
        ) from exc
    if not isinstance(contract_snapshot, Mapping):
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "execution registration snapshot is incomplete."
        )
    if not isinstance(artifact_reference_snapshot, Mapping):
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "execution registration snapshot is incomplete."
        )
    if not isinstance(strategy_contract_snapshot, Mapping):
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "execution registration snapshot is incomplete."
        )
    return contract_snapshot, artifact_reference_snapshot, strategy_contract_snapshot


def _required_window_and_identity(
    execution_record: execution_registry.OfflineResearchExperimentExecutionRegistration,
) -> dict[str, Any]:
    contract_snapshot, artifact_reference_snapshot, strategy_contract_snapshot = _extract_contract_snapshot(
        execution_record
    )
    registry_report = artifact_reference_snapshot.get("registry_report")
    if not isinstance(registry_report, Mapping):
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "execution registration snapshot is incomplete."
        )
    required = {
        "requested_start_inclusive_utc": _require_utc_datetime(
            contract_snapshot["window_start_utc"],
            "requested_start_inclusive_utc",
        ),
        "requested_end_exclusive_utc": _require_utc_datetime(
            contract_snapshot["window_end_utc"],
            "requested_end_exclusive_utc",
        ),
        "expected_symbol": _require_str(contract_snapshot["symbol"], "expected_symbol").upper(),
        "expected_interval": _require_str(contract_snapshot["interval"], "expected_interval"),
        "expected_provider_name": _require_str(registry_report["provider_name"], "expected_provider_name").upper(),
        "expected_market_type": _require_str(registry_report["market_type"], "expected_market_type").lower(),
        "warmup_candle_count": _require_int(
            strategy_contract_snapshot["minimum_candles_required"],
            "warmup_candle_count",
        ),
        "maximum_candle_count": _require_int(
            strategy_contract_snapshot["expected_candle_count"],
            "maximum_candle_count",
        ),
    }
    if required["requested_end_exclusive_utc"] <= required["requested_start_inclusive_utc"]:
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "requested_end_exclusive_utc must be after requested_start_inclusive_utc."
        )
    if required["warmup_candle_count"] > required["maximum_candle_count"]:
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "warmup_candle_count must not exceed maximum_candle_count."
        )
    return required


def _derive_plan_context(
    execution_record: execution_registry.OfflineResearchExperimentExecutionRegistration,
    *,
    plan_context: Mapping[str, Any] | None,
    source_commit_sha: str,
    source_branch: str,
) -> Mapping[str, Any]:
    base_context: dict[str, Any] = {
        "attempt_number": execution_record.attempt_number,
        "execution_status": execution_record.execution_status,
        "execution_reason": execution_record.execution_reason,
        "source_commit_sha": source_commit_sha,
        "source_branch": source_branch,
    }
    _validate_plan_context_value(base_context)
    if plan_context is None:
        return _freeze_read_only_value(base_context)
    if not isinstance(plan_context, Mapping):
        raise OfflineResearchExperimentExecutionPlanValidationError("plan_context must be a mapping.")
    for key in plan_context:
        if key in base_context:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "plan_context cannot override reserved fields."
            )
    merged = dict(base_context)
    merged.update(plan_context)
    _validate_plan_context_value(merged)
    return _freeze_read_only_value(merged)


def _validate_plan_context_value(value: Any, *, path: str = "plan_context") -> None:
    sensitive_tokens = (
        "secret",
        "password",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "credential",
        "private_key",
        "client_secret",
        "access_token",
        "refresh_token",
    )
    if callable(value):
        raise OfflineResearchExperimentExecutionPlanValidationError(
            f"{path} must not contain callables."
        )
    if isinstance(value, MappingProxyType) or isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise OfflineResearchExperimentExecutionPlanValidationError(
                    "plan_context keys must be non-empty strings."
                )
            lowered = key.lower()
            if any(token in lowered for token in sensitive_tokens):
                raise OfflineResearchExperimentExecutionPlanValidationError(
                    "plan_context must not contain secrets or credentials."
                )
            _validate_plan_context_value(item, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _validate_plan_context_value(item, path=path)
        return
    if isinstance(value, (str, int, float, bool, Decimal, datetime)) or value is None:
        return
    raise OfflineResearchExperimentExecutionPlanValidationError(
        f"{path} contains an unsupported value."
    )


def _plan_identity_payload(
    *,
    schema_version: int,
    plan_id: str,
    plan_version: str,
    execution_id: str,
    execution_hash: str,
    experiment_id: str,
    experiment_registration_hash: str,
    plan_number: int,
    previous_plan_id: str | None,
    previous_plan_hash: str | None,
    created_at_utc: datetime,
    source_commit_sha: str,
    source_branch: str,
    research_mode: str,
    requested_start_inclusive_utc: datetime,
    requested_end_exclusive_utc: datetime,
    expected_symbol: str,
    expected_interval: str,
    expected_provider_name: str,
    expected_market_type: str,
    warmup_candle_count: int,
    maximum_candle_count: int,
    allow_replay: bool,
    allow_backtest: bool,
    allow_walk_forward: bool,
    allow_performance_evaluation: bool,
    allow_ranking: bool,
    allow_paper_trading: bool,
    allow_live_trading: bool,
    allow_exchange_connectivity: bool,
    allow_order_submission: bool,
    offline_only: bool,
    historical_research_only: bool,
    operational_evidence: bool,
    paper_promotion_eligible: bool,
    preconditions: tuple[str, ...],
    abort_conditions: tuple[str, ...],
    execution_registration_snapshot: Any,
    plan_context: Any,
    non_operational_declaration: str,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "plan_id": plan_id,
        "plan_version": plan_version,
        "execution_id": execution_id,
        "execution_hash": execution_hash,
        "experiment_id": experiment_id,
        "experiment_registration_hash": experiment_registration_hash,
        "plan_number": plan_number,
        "previous_plan_id": previous_plan_id,
        "previous_plan_hash": previous_plan_hash,
        "created_at_utc": _utc_iso(created_at_utc),
        "source_commit_sha": source_commit_sha,
        "source_branch": source_branch,
        "research_mode": research_mode,
        "requested_start_inclusive_utc": _utc_iso(requested_start_inclusive_utc),
        "requested_end_exclusive_utc": _utc_iso(requested_end_exclusive_utc),
        "expected_symbol": expected_symbol,
        "expected_interval": expected_interval,
        "expected_provider_name": expected_provider_name,
        "expected_market_type": expected_market_type,
        "warmup_candle_count": warmup_candle_count,
        "maximum_candle_count": maximum_candle_count,
        "allow_replay": allow_replay,
        "allow_backtest": allow_backtest,
        "allow_walk_forward": allow_walk_forward,
        "allow_performance_evaluation": allow_performance_evaluation,
        "allow_ranking": allow_ranking,
        "allow_paper_trading": allow_paper_trading,
        "allow_live_trading": allow_live_trading,
        "allow_exchange_connectivity": allow_exchange_connectivity,
        "allow_order_submission": allow_order_submission,
        "offline_only": offline_only,
        "historical_research_only": historical_research_only,
        "operational_evidence": operational_evidence,
        "paper_promotion_eligible": paper_promotion_eligible,
        "preconditions": preconditions,
        "abort_conditions": abort_conditions,
        "execution_registration_snapshot": _thaw_read_only_value(execution_registration_snapshot),
        "plan_context": _thaw_read_only_value(plan_context),
        "non_operational_declaration": non_operational_declaration,
    }


def _plan_sort_key(plan: "OfflineResearchExperimentExecutionPlan") -> tuple[str, int, str, str]:
    return (
        plan.execution_id,
        plan.plan_number,
        plan.plan_id,
        plan.plan_hash,
    )


@dataclass(frozen=True, slots=True)
class OfflineResearchExperimentExecutionPlan:
    schema_version: int = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_SCHEMA_VERSION
    plan_id: str = ""
    plan_version: str = "phase43_offline_experiment_execution_plan_v1"
    execution_id: str = ""
    execution_hash: str = ""
    experiment_id: str = ""
    experiment_registration_hash: str = ""
    plan_number: int = 0
    previous_plan_id: str | None = None
    previous_plan_hash: str | None = None
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_commit_sha: str = ""
    source_branch: str = ""
    research_mode: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_RESEARCH_MODE
    requested_start_inclusive_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    requested_end_exclusive_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expected_symbol: str = ""
    expected_interval: str = ""
    expected_provider_name: str = ""
    expected_market_type: str = ""
    warmup_candle_count: int = 0
    maximum_candle_count: int = 0
    allow_replay: bool = False
    allow_backtest: bool = False
    allow_walk_forward: bool = False
    allow_performance_evaluation: bool = False
    allow_ranking: bool = False
    allow_paper_trading: bool = False
    allow_live_trading: bool = False
    allow_exchange_connectivity: bool = False
    allow_order_submission: bool = False
    offline_only: bool = True
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    preconditions: tuple[str, ...] = field(default_factory=tuple)
    abort_conditions: tuple[str, ...] = field(default_factory=tuple)
    execution_registration_snapshot: Mapping[str, Any] = field(default_factory=dict, repr=False)
    plan_context: Mapping[str, Any] = field(default_factory=dict, repr=False)
    non_operational_declaration: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_NON_OPERATIONAL_DECLARATION
    plan_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "plan_id", _require_str(self.plan_id, "plan_id"))
        object.__setattr__(self, "plan_version", _require_str(self.plan_version, "plan_version"))
        object.__setattr__(self, "execution_id", _require_str(self.execution_id, "execution_id"))
        object.__setattr__(self, "execution_hash", _require_hex_digest(self.execution_hash, "execution_hash"))
        object.__setattr__(self, "experiment_id", _require_str(self.experiment_id, "experiment_id"))
        object.__setattr__(
            self,
            "experiment_registration_hash",
            _require_hex_digest(self.experiment_registration_hash, "experiment_registration_hash"),
        )
        object.__setattr__(self, "plan_number", _require_int(self.plan_number, "plan_number"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "source_commit_sha", _require_commit_sha(self.source_commit_sha, "source_commit_sha"))
        object.__setattr__(self, "source_branch", _require_str(self.source_branch, "source_branch"))
        object.__setattr__(self, "research_mode", _normalize_research_mode(self.research_mode))
        object.__setattr__(
            self,
            "requested_start_inclusive_utc",
            _require_utc_datetime(self.requested_start_inclusive_utc, "requested_start_inclusive_utc"),
        )
        object.__setattr__(
            self,
            "requested_end_exclusive_utc",
            _require_utc_datetime(self.requested_end_exclusive_utc, "requested_end_exclusive_utc"),
        )
        object.__setattr__(self, "expected_symbol", _require_str(self.expected_symbol, "expected_symbol").upper())
        object.__setattr__(self, "expected_interval", _require_str(self.expected_interval, "expected_interval"))
        object.__setattr__(
            self,
            "expected_provider_name",
            _require_str(self.expected_provider_name, "expected_provider_name").upper(),
        )
        object.__setattr__(
            self,
            "expected_market_type",
            _require_str(self.expected_market_type, "expected_market_type").lower(),
        )
        object.__setattr__(self, "warmup_candle_count", _require_int(self.warmup_candle_count, "warmup_candle_count"))
        object.__setattr__(self, "maximum_candle_count", _require_int(self.maximum_candle_count, "maximum_candle_count"))
        object.__setattr__(self, "allow_replay", _require_bool(self.allow_replay, "allow_replay"))
        object.__setattr__(self, "allow_backtest", _require_bool(self.allow_backtest, "allow_backtest"))
        object.__setattr__(self, "allow_walk_forward", _require_bool(self.allow_walk_forward, "allow_walk_forward"))
        object.__setattr__(
            self,
            "allow_performance_evaluation",
            _require_bool(self.allow_performance_evaluation, "allow_performance_evaluation"),
        )
        object.__setattr__(self, "allow_ranking", _require_bool(self.allow_ranking, "allow_ranking"))
        object.__setattr__(self, "allow_paper_trading", _require_bool(self.allow_paper_trading, "allow_paper_trading"))
        object.__setattr__(self, "allow_live_trading", _require_bool(self.allow_live_trading, "allow_live_trading"))
        object.__setattr__(
            self,
            "allow_exchange_connectivity",
            _require_bool(self.allow_exchange_connectivity, "allow_exchange_connectivity"),
        )
        object.__setattr__(self, "allow_order_submission", _require_bool(self.allow_order_submission, "allow_order_submission"))
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(
            self,
            "preconditions",
            _normalize_string_sequence(
                self.preconditions,
                field_name="preconditions",
                required_items=OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REQUIRED_PRECONDITIONS,
            ),
        )
        object.__setattr__(
            self,
            "abort_conditions",
            _normalize_string_sequence(
                self.abort_conditions,
                field_name="abort_conditions",
                required_items=OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REQUIRED_ABORT_CONDITIONS,
            ),
        )
        if not isinstance(self.execution_registration_snapshot, Mapping):
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "execution_registration_snapshot must be a mapping."
            )
        if not isinstance(self.plan_context, Mapping):
            raise OfflineResearchExperimentExecutionPlanValidationError("plan_context must be a mapping.")
        object.__setattr__(self, "execution_registration_snapshot", _freeze_read_only_value(dict(self.execution_registration_snapshot)))
        object.__setattr__(self, "plan_context", _freeze_read_only_value(dict(self.plan_context)))
        _validate_plan_context_value(self.plan_context)
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))

        if self.schema_version != OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_SCHEMA_VERSION:
            raise OfflineResearchExperimentExecutionPlanValidationError("schema_version must be 1.")
        if self.plan_version != "phase43_offline_experiment_execution_plan_v1":
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "plan_version must remain phase43_offline_experiment_execution_plan_v1."
            )
        if self.plan_number <= 0:
            raise OfflineResearchExperimentExecutionPlanValidationError("plan_number must be greater than zero.")
        if self.requested_end_exclusive_utc <= self.requested_start_inclusive_utc:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "requested_end_exclusive_utc must be after requested_start_inclusive_utc."
            )
        if self.maximum_candle_count <= 0:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "maximum_candle_count must be greater than zero."
            )
        if self.warmup_candle_count < 0:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "warmup_candle_count cannot be negative."
            )
        if self.warmup_candle_count > self.maximum_candle_count:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "warmup_candle_count must not exceed maximum_candle_count."
            )
        if self.offline_only is not True:
            raise OfflineResearchExperimentExecutionPlanValidationError("offline_only must be true.")
        if self.historical_research_only is not True:
            raise OfflineResearchExperimentExecutionPlanValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchExperimentExecutionPlanValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchExperimentExecutionPlanValidationError("paper_promotion_eligible must be false.")
        if self.allow_replay is not False:
            raise OfflineResearchExperimentExecutionPlanValidationError("allow_replay must be false.")
        if self.allow_backtest is not False:
            raise OfflineResearchExperimentExecutionPlanValidationError("allow_backtest must be false.")
        if self.allow_walk_forward is not False:
            raise OfflineResearchExperimentExecutionPlanValidationError("allow_walk_forward must be false.")
        if self.allow_performance_evaluation is not False:
            raise OfflineResearchExperimentExecutionPlanValidationError("allow_performance_evaluation must be false.")
        if self.allow_ranking is not False:
            raise OfflineResearchExperimentExecutionPlanValidationError("allow_ranking must be false.")
        if self.allow_paper_trading is not False:
            raise OfflineResearchExperimentExecutionPlanValidationError("allow_paper_trading must be false.")
        if self.allow_live_trading is not False:
            raise OfflineResearchExperimentExecutionPlanValidationError("allow_live_trading must be false.")
        if self.allow_exchange_connectivity is not False:
            raise OfflineResearchExperimentExecutionPlanValidationError("allow_exchange_connectivity must be false.")
        if self.allow_order_submission is not False:
            raise OfflineResearchExperimentExecutionPlanValidationError("allow_order_submission must be false.")
        if self.non_operational_declaration != OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "non_operational_declaration diverges from the plan contract."
            )

        execution_record = execution_registry.OfflineResearchExperimentExecutionRegistration.from_dict(
            dict(_thaw_read_only_value(self.execution_registration_snapshot))
        )
        normalized_snapshot = _execution_snapshot_payload(execution_record)
        object.__setattr__(self, "execution_registration_snapshot", normalized_snapshot)
        if execution_record.execution_id != self.execution_id:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("execution_id mismatch.")
        if execution_record.execution_hash != self.execution_hash:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("execution_hash mismatch.")
        if execution_record.experiment_id != self.experiment_id:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("experiment_id mismatch.")
        if execution_record.experiment_registration_hash != self.experiment_registration_hash:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("experiment_registration_hash mismatch.")

        contract_data = _required_window_and_identity(execution_record)
        if self.requested_start_inclusive_utc != contract_data["requested_start_inclusive_utc"]:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("requested_start_inclusive_utc mismatch.")
        if self.requested_end_exclusive_utc != contract_data["requested_end_exclusive_utc"]:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("requested_end_exclusive_utc mismatch.")
        if self.expected_symbol != contract_data["expected_symbol"]:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("expected_symbol mismatch.")
        if self.expected_interval != contract_data["expected_interval"]:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("expected_interval mismatch.")
        if self.expected_provider_name != contract_data["expected_provider_name"]:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("expected_provider_name mismatch.")
        if self.expected_market_type != contract_data["expected_market_type"]:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("expected_market_type mismatch.")
        if self.warmup_candle_count != contract_data["warmup_candle_count"]:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("warmup_candle_count mismatch.")
        if self.maximum_candle_count != contract_data["maximum_candle_count"]:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("maximum_candle_count mismatch.")

        if self.plan_number == 1:
            if self.previous_plan_id is not None or self.previous_plan_hash is not None:
                raise OfflineResearchExperimentExecutionPlanValidationError(
                    "previous plan reference is not allowed for plan_number 1."
                )
        else:
            if self.previous_plan_id is None or self.previous_plan_hash is None:
                raise OfflineResearchExperimentExecutionPlanValidationError(
                    "previous plan reference is required for plan_number greater than 1."
                )
            object.__setattr__(self, "previous_plan_id", _require_str(self.previous_plan_id, "previous_plan_id"))
            object.__setattr__(self, "previous_plan_hash", _require_hex_digest(self.previous_plan_hash, "previous_plan_hash"))

        try:
            expected_plan_hash = _hash_payload(self.canonical_payload(include_plan_hash=False))
        except TypeError as exc:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "plan payload is not serializable."
            ) from exc

        if self.plan_hash:
            if self.plan_hash != expected_plan_hash:
                raise OfflineResearchExperimentExecutionPlanIntegrityError("plan_hash mismatch.")
        else:
            object.__setattr__(self, "plan_hash", expected_plan_hash)

    def canonical_payload(self, *, include_plan_hash: bool = True) -> dict[str, Any]:
        payload = _plan_identity_payload(
            schema_version=self.schema_version,
            plan_id=self.plan_id,
            plan_version=self.plan_version,
            execution_id=self.execution_id,
            execution_hash=self.execution_hash,
            experiment_id=self.experiment_id,
            experiment_registration_hash=self.experiment_registration_hash,
            plan_number=self.plan_number,
            previous_plan_id=self.previous_plan_id,
            previous_plan_hash=self.previous_plan_hash,
            created_at_utc=self.created_at_utc,
            source_commit_sha=self.source_commit_sha,
            source_branch=self.source_branch,
            research_mode=self.research_mode,
            requested_start_inclusive_utc=self.requested_start_inclusive_utc,
            requested_end_exclusive_utc=self.requested_end_exclusive_utc,
            expected_symbol=self.expected_symbol,
            expected_interval=self.expected_interval,
            expected_provider_name=self.expected_provider_name,
            expected_market_type=self.expected_market_type,
            warmup_candle_count=self.warmup_candle_count,
            maximum_candle_count=self.maximum_candle_count,
            allow_replay=self.allow_replay,
            allow_backtest=self.allow_backtest,
            allow_walk_forward=self.allow_walk_forward,
            allow_performance_evaluation=self.allow_performance_evaluation,
            allow_ranking=self.allow_ranking,
            allow_paper_trading=self.allow_paper_trading,
            allow_live_trading=self.allow_live_trading,
            allow_exchange_connectivity=self.allow_exchange_connectivity,
            allow_order_submission=self.allow_order_submission,
            offline_only=self.offline_only,
            historical_research_only=self.historical_research_only,
            operational_evidence=self.operational_evidence,
            paper_promotion_eligible=self.paper_promotion_eligible,
            preconditions=self.preconditions,
            abort_conditions=self.abort_conditions,
            execution_registration_snapshot=self.execution_registration_snapshot,
            plan_context=self.plan_context,
            non_operational_declaration=self.non_operational_declaration,
        )
        if include_plan_hash:
            payload["plan_hash"] = self.plan_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_plan_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfflineResearchExperimentExecutionPlan":
        if not isinstance(data, Mapping):
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "offline research experiment execution plan must be a mapping."
            )
        mapping = dict(data)
        allowed = {
            "schema_version",
            "plan_id",
            "plan_version",
            "execution_id",
            "execution_hash",
            "experiment_id",
            "experiment_registration_hash",
            "plan_number",
            "previous_plan_id",
            "previous_plan_hash",
            "created_at_utc",
            "source_commit_sha",
            "source_branch",
            "research_mode",
            "requested_start_inclusive_utc",
            "requested_end_exclusive_utc",
            "expected_symbol",
            "expected_interval",
            "expected_provider_name",
            "expected_market_type",
            "warmup_candle_count",
            "maximum_candle_count",
            "allow_replay",
            "allow_backtest",
            "allow_walk_forward",
            "allow_performance_evaluation",
            "allow_ranking",
            "allow_paper_trading",
            "allow_live_trading",
            "allow_exchange_connectivity",
            "allow_order_submission",
            "offline_only",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "preconditions",
            "abort_conditions",
            "execution_registration_snapshot",
            "plan_context",
            "non_operational_declaration",
            "plan_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                f"unexpected offline research experiment execution plan fields: {', '.join(extra)}."
            )
        try:
            return cls(
                schema_version=mapping.get("schema_version", OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_SCHEMA_VERSION),
                plan_id=mapping["plan_id"],
                plan_version=mapping.get(
                    "plan_version",
                    "phase43_offline_experiment_execution_plan_v1",
                ),
                execution_id=mapping["execution_id"],
                execution_hash=mapping["execution_hash"],
                experiment_id=mapping["experiment_id"],
                experiment_registration_hash=mapping["experiment_registration_hash"],
                plan_number=mapping["plan_number"],
                previous_plan_id=mapping.get("previous_plan_id"),
                previous_plan_hash=mapping.get("previous_plan_hash"),
                created_at_utc=mapping.get("created_at_utc", datetime.now(timezone.utc)),
                source_commit_sha=mapping["source_commit_sha"],
                source_branch=mapping["source_branch"],
                research_mode=mapping.get(
                    "research_mode",
                    OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_RESEARCH_MODE,
                ),
                requested_start_inclusive_utc=mapping["requested_start_inclusive_utc"],
                requested_end_exclusive_utc=mapping["requested_end_exclusive_utc"],
                expected_symbol=mapping["expected_symbol"],
                expected_interval=mapping["expected_interval"],
                expected_provider_name=mapping["expected_provider_name"],
                expected_market_type=mapping["expected_market_type"],
                warmup_candle_count=mapping["warmup_candle_count"],
                maximum_candle_count=mapping["maximum_candle_count"],
                allow_replay=mapping.get("allow_replay", False),
                allow_backtest=mapping.get("allow_backtest", False),
                allow_walk_forward=mapping.get("allow_walk_forward", False),
                allow_performance_evaluation=mapping.get("allow_performance_evaluation", False),
                allow_ranking=mapping.get("allow_ranking", False),
                allow_paper_trading=mapping.get("allow_paper_trading", False),
                allow_live_trading=mapping.get("allow_live_trading", False),
                allow_exchange_connectivity=mapping.get("allow_exchange_connectivity", False),
                allow_order_submission=mapping.get("allow_order_submission", False),
                offline_only=mapping.get("offline_only", True),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                preconditions=tuple(mapping.get("preconditions", ())),
                abort_conditions=tuple(mapping.get("abort_conditions", ())),
                execution_registration_snapshot=mapping["execution_registration_snapshot"],
                plan_context=mapping.get("plan_context", {}),
                non_operational_declaration=mapping.get(
                    "non_operational_declaration",
                    OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_NON_OPERATIONAL_DECLARATION,
                ),
                plan_hash=mapping.get("plan_hash", ""),
            )
        except KeyError as exc:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "offline research experiment execution plan is incomplete."
            ) from exc


def _build_execution_registration_snapshot(
    execution_record: execution_registry.OfflineResearchExperimentExecutionRegistration,
) -> Mapping[str, Any]:
    if not isinstance(execution_record, execution_registry.OfflineResearchExperimentExecutionRegistration):
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "a verified phase 42 execution registration is required."
        )
    return _execution_snapshot_payload(execution_record)


def build_offline_research_experiment_execution_plan(
    *,
    plan_id: str,
    execution_registration: execution_registry.OfflineResearchExperimentExecutionRegistration | Mapping[str, Any] | None = None,
    execution_registry_file: str | Path | None = None,
    execution_id: str | None = None,
    execution_hash: str | None = None,
    previous_plan: "OfflineResearchExperimentExecutionPlan | Mapping[str, Any] | None" = None,
    plan_version: str = "phase43_offline_experiment_execution_plan_v1",
    plan_number: int,
    created_at_utc: datetime | None = None,
    source_commit_sha: str = "",
    source_branch: str = "",
    research_mode: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_RESEARCH_MODE,
    plan_context: Mapping[str, Any] | None = None,
    allow_replay: bool = False,
    allow_backtest: bool = False,
    allow_walk_forward: bool = False,
    allow_performance_evaluation: bool = False,
    allow_ranking: bool = False,
    allow_paper_trading: bool = False,
    allow_live_trading: bool = False,
    allow_exchange_connectivity: bool = False,
    allow_order_submission: bool = False,
    offline_only: bool = True,
    historical_research_only: bool = True,
    operational_evidence: bool = False,
    paper_promotion_eligible: bool = False,
    preconditions: Sequence[str] | set[str] | frozenset[str] | None = None,
    abort_conditions: Sequence[str] | set[str] | frozenset[str] | None = None,
    non_operational_declaration: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_NON_OPERATIONAL_DECLARATION,
) -> OfflineResearchExperimentExecutionPlan:
    execution_record = _normalize_execution_registration_source(
        execution_registration=execution_registration,
        execution_registry_file=execution_registry_file,
        execution_id=execution_id,
        execution_hash=execution_hash,
    )
    if plan_number == 1 and previous_plan is not None:
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "previous plan reference is not allowed for plan_number 1."
        )
    if plan_number > 1 and previous_plan is None:
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "previous plan reference is required for plan_number greater than 1."
        )

    previous_plan_obj: OfflineResearchExperimentExecutionPlan | None
    if previous_plan is None:
        previous_plan_obj = None
    elif isinstance(previous_plan, OfflineResearchExperimentExecutionPlan):
        previous_plan_obj = previous_plan
    elif isinstance(previous_plan, Mapping):
        try:
            previous_plan_obj = OfflineResearchExperimentExecutionPlan.from_dict(dict(previous_plan))
        except Exception as exc:
            raise OfflineResearchExperimentExecutionPlanValidationError("previous plan snapshot is invalid.") from exc
    else:
        raise OfflineResearchExperimentExecutionPlanValidationError("previous plan snapshot is invalid.")

    required = _required_window_and_identity(execution_record)
    if previous_plan_obj is not None:
        if previous_plan_obj.plan_number != plan_number - 1:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("previous plan_number mismatch.")
        if previous_plan_obj.execution_id != execution_record.execution_id:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("previous plan execution_id mismatch.")
        if previous_plan_obj.execution_hash != execution_record.execution_hash:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("previous plan execution_hash mismatch.")
        if previous_plan_obj.experiment_id != execution_record.experiment_id:
            raise OfflineResearchExperimentExecutionPlanIntegrityError("previous plan experiment_id mismatch.")
        previous_plan_id = previous_plan_obj.plan_id
        previous_plan_hash = previous_plan_obj.plan_hash
    else:
        previous_plan_id = None
        previous_plan_hash = None

    if not source_commit_sha:
        raise OfflineResearchExperimentExecutionPlanValidationError("source_commit_sha is required.")
    if not source_branch:
        raise OfflineResearchExperimentExecutionPlanValidationError("source_branch is required.")

    if plan_context is None:
        derived_context: dict[str, Any] = {
            "attempt_number": execution_record.attempt_number,
            "execution_status": execution_record.execution_status,
            "execution_reason": execution_record.execution_reason,
            "source_commit_sha": _require_commit_sha(source_commit_sha, "source_commit_sha"),
            "source_branch": _require_str(source_branch, "source_branch"),
        }
        _validate_plan_context_value(derived_context)
        normalized_context = _freeze_read_only_value(derived_context)
    else:
        normalized_context = _derive_plan_context(
            execution_record,
            plan_context=plan_context,
            source_commit_sha=_require_commit_sha(source_commit_sha, "source_commit_sha"),
            source_branch=_require_str(source_branch, "source_branch"),
        )

    plan = OfflineResearchExperimentExecutionPlan(
        schema_version=OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_SCHEMA_VERSION,
        plan_id=plan_id,
        plan_version=plan_version,
        execution_id=execution_record.execution_id,
        execution_hash=execution_record.execution_hash,
        experiment_id=execution_record.experiment_id,
        experiment_registration_hash=execution_record.experiment_registration_hash,
        plan_number=plan_number,
        previous_plan_id=previous_plan_id,
        previous_plan_hash=previous_plan_hash,
        created_at_utc=created_at_utc or datetime.now(timezone.utc),
        source_commit_sha=source_commit_sha,
        source_branch=source_branch,
        research_mode=research_mode,
        requested_start_inclusive_utc=required["requested_start_inclusive_utc"],
        requested_end_exclusive_utc=required["requested_end_exclusive_utc"],
        expected_symbol=required["expected_symbol"],
        expected_interval=required["expected_interval"],
        expected_provider_name=required["expected_provider_name"],
        expected_market_type=required["expected_market_type"],
        warmup_candle_count=required["warmup_candle_count"],
        maximum_candle_count=required["maximum_candle_count"],
        allow_replay=allow_replay,
        allow_backtest=allow_backtest,
        allow_walk_forward=allow_walk_forward,
        allow_performance_evaluation=allow_performance_evaluation,
        allow_ranking=allow_ranking,
        allow_paper_trading=allow_paper_trading,
        allow_live_trading=allow_live_trading,
        allow_exchange_connectivity=allow_exchange_connectivity,
        allow_order_submission=allow_order_submission,
        offline_only=offline_only,
        historical_research_only=historical_research_only,
        operational_evidence=operational_evidence,
        paper_promotion_eligible=paper_promotion_eligible,
        preconditions=preconditions,
        abort_conditions=abort_conditions,
        execution_registration_snapshot=_build_execution_registration_snapshot(execution_record),
        plan_context=normalized_context,
        non_operational_declaration=non_operational_declaration,
    )
    if plan.as_dict() != serialize_value(plan.canonical_payload(include_plan_hash=True)):
        raise OfflineResearchExperimentExecutionPlanIntegrityError("plan payload mismatch.")
    return plan


@dataclass(frozen=True, slots=True)
class OfflineResearchExperimentExecutionPlanRegistry:
    registry_file: Path = field(default_factory=Path, repr=False)
    schema_version: int = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_SCHEMA_VERSION
    registry_id: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REGISTRY_ID
    registry_version: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REGISTRY_VERSION
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    plans: tuple[OfflineResearchExperimentExecutionPlan, ...] = field(default_factory=tuple)
    offline_only: bool = True
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_NON_OPERATIONAL_DECLARATION
    registry_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_file", Path(self.registry_file))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "registry_id", _require_str(self.registry_id, "registry_id"))
        object.__setattr__(self, "registry_version", _require_str(self.registry_version, "registry_version"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "updated_at_utc", _require_utc_datetime(self.updated_at_utc, "updated_at_utc"))
        plans = tuple(
            plan if isinstance(plan, OfflineResearchExperimentExecutionPlan) else OfflineResearchExperimentExecutionPlan.from_dict(plan)
            for plan in self.plans
        )
        plans = tuple(sorted(plans, key=_plan_sort_key))
        object.__setattr__(self, "plans", plans)
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.schema_version != OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_SCHEMA_VERSION:
            raise OfflineResearchExperimentExecutionPlanValidationError("schema_version must be 1.")
        if self.registry_id != OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REGISTRY_ID:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "registry_id must remain offline_research_experiment_execution_plan_registry."
            )
        if self.registry_version != OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REGISTRY_VERSION:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "registry_version must remain phase43_offline_experiment_execution_plan_registry_v1."
            )
        if self.offline_only is not True:
            raise OfflineResearchExperimentExecutionPlanValidationError("offline_only must be true.")
        if self.historical_research_only is not True:
            raise OfflineResearchExperimentExecutionPlanValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchExperimentExecutionPlanValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchExperimentExecutionPlanValidationError("paper_promotion_eligible must be false.")
        if self.non_operational_declaration != OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "non_operational_declaration diverges from the plan registry contract."
            )

        seen_plan_ids: set[str] = set()
        seen_plan_hashes: set[str] = set()
        for plan in plans:
            if plan.plan_id in seen_plan_ids:
                raise OfflineResearchExperimentExecutionPlanConflictError("plan_id conflict.")
            if plan.plan_hash in seen_plan_hashes:
                raise OfflineResearchExperimentExecutionPlanConflictError("plan_hash conflict.")
            seen_plan_ids.add(plan.plan_id)
            seen_plan_hashes.add(plan.plan_hash)
        seen_plan_numbers_by_execution: dict[str, set[int]] = {}
        for plan in plans:
            seen_plan_numbers = seen_plan_numbers_by_execution.setdefault(plan.execution_id, set())
            if plan.plan_number in seen_plan_numbers:
                raise OfflineResearchExperimentExecutionPlanConflictError("plan_number conflict.")
            seen_plan_numbers.add(plan.plan_number)

        try:
            expected_hash = _hash_payload(self.canonical_payload(include_registry_hash=False))
        except TypeError as exc:
            raise OfflineResearchExperimentExecutionPlanValidationError("plan registry payload is not serializable.") from exc
        if self.registry_hash:
            if self.registry_hash != expected_hash:
                raise OfflineResearchExperimentExecutionPlanIntegrityError("registry_hash mismatch.")
        else:
            object.__setattr__(self, "registry_hash", expected_hash)

    @property
    def plan_count(self) -> int:
        return len(self.plans)

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
            "plans": [plan.canonical_payload(include_plan_hash=True) for plan in self.plans],
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
    ) -> "OfflineResearchExperimentExecutionPlanRegistry":
        if not isinstance(data, Mapping):
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "offline research experiment execution plan registry must be a mapping."
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
            "plans",
            "registry_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                f"unexpected offline research experiment execution plan registry fields: {', '.join(extra)}."
            )
        try:
            return cls(
                registry_file=registry_file,
                schema_version=mapping.get("schema_version", OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_SCHEMA_VERSION),
                registry_id=mapping.get("registry_id", OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REGISTRY_ID),
                registry_version=mapping.get(
                    "registry_version",
                    OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REGISTRY_VERSION,
                ),
                created_at_utc=mapping.get("created_at_utc", datetime.now(timezone.utc)),
                updated_at_utc=mapping.get("updated_at_utc", datetime.now(timezone.utc)),
                plans=tuple(mapping.get("plans", ())),
                offline_only=mapping.get("offline_only", True),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                non_operational_declaration=mapping.get(
                    "non_operational_declaration",
                    OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_NON_OPERATIONAL_DECLARATION,
                ),
                registry_hash=mapping.get("registry_hash", ""),
            )
        except KeyError as exc:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "offline research experiment execution plan registry is incomplete."
            ) from exc

    def plan_by_id(self, plan_id: str) -> OfflineResearchExperimentExecutionPlan:
        target = _require_str(plan_id, "plan_id")
        for plan in self.plans:
            if plan.plan_id == target:
                return plan
        raise OfflineResearchExperimentExecutionPlanValidationError("plan_id was not found in the registry.")

    def plan_by_hash(self, plan_hash: str) -> OfflineResearchExperimentExecutionPlan:
        target = _require_hex_digest(plan_hash, "plan_hash")
        for plan in self.plans:
            if plan.plan_hash == target:
                return plan
        raise OfflineResearchExperimentExecutionPlanValidationError("plan_hash was not found in the registry.")

    def plan_by_execution_id_and_number(
        self,
        execution_id: str,
        plan_number: int,
    ) -> OfflineResearchExperimentExecutionPlan:
        target_execution_id = _require_str(execution_id, "execution_id")
        target_plan_number = _require_int(plan_number, "plan_number")
        for plan in self.plans:
            if plan.execution_id == target_execution_id and plan.plan_number == target_plan_number:
                return plan
        raise OfflineResearchExperimentExecutionPlanValidationError("plan was not found in the registry.")

    def plans_for_execution_id(self, execution_id: str) -> tuple[OfflineResearchExperimentExecutionPlan, ...]:
        target = _require_str(execution_id, "execution_id")
        return tuple(sorted((plan for plan in self.plans if plan.execution_id == target), key=lambda plan: plan.plan_number))

    def with_plan(
        self,
        plan: OfflineResearchExperimentExecutionPlan,
        *,
        updated_at_utc: datetime | None = None,
    ) -> "OfflineResearchExperimentExecutionPlanRegistry":
        plans = tuple(self.plans) + (plan,)
        return OfflineResearchExperimentExecutionPlanRegistry(
            registry_file=self.registry_file,
            schema_version=self.schema_version,
            registry_id=self.registry_id,
            registry_version=self.registry_version,
            created_at_utc=self.created_at_utc,
            updated_at_utc=updated_at_utc or datetime.now(timezone.utc),
            plans=plans,
            offline_only=self.offline_only,
            historical_research_only=self.historical_research_only,
            operational_evidence=self.operational_evidence,
            paper_promotion_eligible=self.paper_promotion_eligible,
            non_operational_declaration=self.non_operational_declaration,
        )


@dataclass(frozen=True, slots=True)
class OfflineResearchExperimentExecutionPlanVerificationReport:
    schema_version: int = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_SCHEMA_VERSION
    registry_file: Path = field(default_factory=Path)
    verified_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved: bool = True
    registry_id: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REGISTRY_ID
    registry_version: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REGISTRY_VERSION
    plan_count: int = 0
    registry_hash: str = ""
    plan_ids: tuple[str, ...] = ()
    plan_hashes: tuple[str, ...] = ()
    execution_ids: tuple[str, ...] = ()
    offline_only: bool = True
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_NON_OPERATIONAL_DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_file", Path(self.registry_file))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "verified_at_utc", _require_utc_datetime(self.verified_at_utc, "verified_at_utc"))
        object.__setattr__(self, "approved", _require_bool(self.approved, "approved"))
        object.__setattr__(self, "registry_id", _require_str(self.registry_id, "registry_id"))
        object.__setattr__(self, "registry_version", _require_str(self.registry_version, "registry_version"))
        object.__setattr__(self, "plan_count", _require_int(self.plan_count, "plan_count"))
        object.__setattr__(self, "registry_hash", _require_hex_digest(self.registry_hash, "registry_hash") if self.registry_hash else "")
        object.__setattr__(self, "plan_ids", tuple(_require_str(item, "plan_id") for item in self.plan_ids))
        object.__setattr__(self, "plan_hashes", tuple(_require_hex_digest(item, "plan_hash") for item in self.plan_hashes))
        object.__setattr__(self, "execution_ids", tuple(_require_str(item, "execution_id") for item in self.execution_ids))
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.approved is not True:
            raise OfflineResearchExperimentExecutionPlanValidationError("approved must be true.")

    def canonical_payload(self, *, include_report_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "registry_file": self.registry_file.as_posix(),
            "verified_at_utc": _utc_iso(self.verified_at_utc),
            "approved": self.approved,
            "registry_id": self.registry_id,
            "registry_version": self.registry_version,
            "plan_count": self.plan_count,
            "plan_ids": self.plan_ids,
            "plan_hashes": self.plan_hashes,
            "execution_ids": self.execution_ids,
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


def _build_plan_from_snapshot(snapshot: Mapping[str, Any]) -> OfflineResearchExperimentExecutionPlan:
    if not isinstance(snapshot, Mapping):
        raise OfflineResearchExperimentExecutionPlanValidationError("plan snapshot must be a mapping.")
    try:
        return OfflineResearchExperimentExecutionPlan.from_dict(dict(snapshot))
    except Exception as exc:
        raise OfflineResearchExperimentExecutionPlanValidationError("plan snapshot is invalid.") from exc


def load_offline_research_experiment_execution_plan_registry(
    registry_file: str | Path,
) -> OfflineResearchExperimentExecutionPlanRegistry:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    if not path.exists():
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "offline research experiment execution plan registry is missing."
        )
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "offline research experiment execution plan registry is empty."
        )
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "offline research experiment execution plan registry is invalid JSON."
        ) from exc
    if not isinstance(payload, Mapping):
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "offline research experiment execution plan registry must be a JSON object."
        )
    registry = OfflineResearchExperimentExecutionPlanRegistry.from_dict(payload, registry_file=path)
    if _canonical_json(registry.as_dict()) != _canonical_json(payload):
        raise OfflineResearchExperimentExecutionPlanIntegrityError(
            "offline research experiment execution plan registry payload mismatch."
        )
    return registry


def save_offline_research_experiment_execution_plan_registry(
    registry_file: str | Path,
    registry: OfflineResearchExperimentExecutionPlanRegistry,
) -> OfflineResearchExperimentExecutionPlanRegistry:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    if not isinstance(registry, OfflineResearchExperimentExecutionPlanRegistry):
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "offline research experiment execution plan registry is required."
        )
    payload = registry.as_dict()
    if path.exists():
        existing = load_offline_research_experiment_execution_plan_registry(path)
        if _canonical_json(existing.as_dict()) != _canonical_json(payload):
            raise OfflineResearchExperimentExecutionPlanConflictError(
                "offline research experiment execution plan registry already exists and differs."
            )
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{id(registry)}.tmp")
    try:
        tmp_path.write_text(_canonical_json(payload), encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "failed to write offline research experiment execution plan registry atomically."
        ) from exc
    return registry


def _load_or_create_registry(
    registry_file: str | Path,
    *,
    created_at_utc: datetime | None = None,
    updated_at_utc: datetime | None = None,
) -> OfflineResearchExperimentExecutionPlanRegistry:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    if path.exists():
        return load_offline_research_experiment_execution_plan_registry(path)
    return OfflineResearchExperimentExecutionPlanRegistry(
        registry_file=path,
        created_at_utc=created_at_utc or datetime.now(timezone.utc),
        updated_at_utc=updated_at_utc or datetime.now(timezone.utc),
    )


def _assert_plan_conflicts(
    registry: OfflineResearchExperimentExecutionPlanRegistry,
    plan: OfflineResearchExperimentExecutionPlan,
) -> None:
    try:
        existing_by_id = registry.plan_by_id(plan.plan_id)
    except OfflineResearchExperimentExecutionPlanValidationError:
        existing_by_id = None
    try:
        existing_by_number = registry.plan_by_execution_id_and_number(plan.execution_id, plan.plan_number)
    except OfflineResearchExperimentExecutionPlanValidationError:
        existing_by_number = None

    if existing_by_id is not None:
        if existing_by_id.as_dict() == plan.as_dict():
            return
        raise OfflineResearchExperimentExecutionPlanConflictError("plan_id already registered.")
    if existing_by_number is not None:
        if existing_by_number.as_dict() == plan.as_dict():
            return
        raise OfflineResearchExperimentExecutionPlanConflictError(
            "plan_number already registered for this execution."
        )


def register_offline_research_experiment_execution_plan(
    *,
    registry_file: str | Path,
    plan_id: str,
    execution_registration: execution_registry.OfflineResearchExperimentExecutionRegistration | Mapping[str, Any] | None = None,
    execution_registry_file: str | Path | None = None,
    execution_id: str | None = None,
    execution_hash: str | None = None,
    previous_plan: OfflineResearchExperimentExecutionPlan | Mapping[str, Any] | None = None,
    plan_version: str = "phase43_offline_experiment_execution_plan_v1",
    plan_number: int,
    created_at_utc: datetime | None = None,
    source_commit_sha: str = "",
    source_branch: str = "",
    research_mode: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_RESEARCH_MODE,
    plan_context: Mapping[str, Any] | None = None,
    allow_replay: bool = False,
    allow_backtest: bool = False,
    allow_walk_forward: bool = False,
    allow_performance_evaluation: bool = False,
    allow_ranking: bool = False,
    allow_paper_trading: bool = False,
    allow_live_trading: bool = False,
    allow_exchange_connectivity: bool = False,
    allow_order_submission: bool = False,
    offline_only: bool = True,
    historical_research_only: bool = True,
    operational_evidence: bool = False,
    paper_promotion_eligible: bool = False,
    preconditions: Sequence[str] | set[str] | frozenset[str] | None = None,
    abort_conditions: Sequence[str] | set[str] | frozenset[str] | None = None,
    non_operational_declaration: str = OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_NON_OPERATIONAL_DECLARATION,
) -> OfflineResearchExperimentExecutionPlan:
    registry_path = _ensure_registry_path(registry_file, field_name="registry_file")
    registry = _load_or_create_registry(registry_path, created_at_utc=created_at_utc, updated_at_utc=created_at_utc)

    if execution_registration is None and execution_registry_file is None:
        raise OfflineResearchExperimentExecutionPlanValidationError(
            "execution_registration or execution_registry_file is required."
        )

    execution_record = _normalize_execution_registration_source(
        execution_registration=execution_registration,
        execution_registry_file=execution_registry_file,
        execution_id=execution_id,
        execution_hash=execution_hash,
    )
    resolved_previous_plan = previous_plan
    if resolved_previous_plan is None and plan_number > 1:
        try:
            resolved_previous_plan = registry.plan_by_execution_id_and_number(
                execution_record.execution_id,
                plan_number - 1,
            )
        except OfflineResearchExperimentExecutionPlanValidationError as exc:
            raise OfflineResearchExperimentExecutionPlanValidationError(
                "previous plan reference is required for plan_number greater than 1."
            ) from exc

    plan = build_offline_research_experiment_execution_plan(
        plan_id=plan_id,
        execution_registration=execution_record,
        previous_plan=resolved_previous_plan,
        plan_version=plan_version,
        plan_number=plan_number,
        created_at_utc=created_at_utc,
        source_commit_sha=source_commit_sha,
        source_branch=source_branch,
        research_mode=research_mode,
        plan_context=plan_context,
        allow_replay=allow_replay,
        allow_backtest=allow_backtest,
        allow_walk_forward=allow_walk_forward,
        allow_performance_evaluation=allow_performance_evaluation,
        allow_ranking=allow_ranking,
        allow_paper_trading=allow_paper_trading,
        allow_live_trading=allow_live_trading,
        allow_exchange_connectivity=allow_exchange_connectivity,
        allow_order_submission=allow_order_submission,
        offline_only=offline_only,
        historical_research_only=historical_research_only,
        operational_evidence=operational_evidence,
        paper_promotion_eligible=paper_promotion_eligible,
        preconditions=preconditions,
        abort_conditions=abort_conditions,
        non_operational_declaration=non_operational_declaration,
    )
    _assert_plan_conflicts(registry, plan)
    if any(existing.as_dict() == plan.as_dict() for existing in registry.plans):
        return next(existing for existing in registry.plans if existing.as_dict() == plan.as_dict())
    updated_registry = registry.with_plan(plan, updated_at_utc=created_at_utc or datetime.now(timezone.utc))
    save_offline_research_experiment_execution_plan_registry(registry_path, updated_registry)
    return plan


def list_offline_research_experiment_execution_plan_registry_plans(
    registry_file: str | Path,
) -> tuple[OfflineResearchExperimentExecutionPlan, ...]:
    return load_offline_research_experiment_execution_plan_registry(registry_file).plans


def get_offline_research_experiment_execution_plan_by_id(
    registry_file: str | Path,
    plan_id: str,
) -> OfflineResearchExperimentExecutionPlan:
    return load_offline_research_experiment_execution_plan_registry(registry_file).plan_by_id(plan_id)


def get_offline_research_experiment_execution_plan_by_hash(
    registry_file: str | Path,
    plan_hash: str,
) -> OfflineResearchExperimentExecutionPlan:
    return load_offline_research_experiment_execution_plan_registry(registry_file).plan_by_hash(plan_hash)


def get_offline_research_experiment_execution_plan_by_execution_id_and_number(
    registry_file: str | Path,
    execution_id: str,
    plan_number: int,
) -> OfflineResearchExperimentExecutionPlan:
    return load_offline_research_experiment_execution_plan_registry(registry_file).plan_by_execution_id_and_number(
        execution_id,
        plan_number,
    )


def verify_offline_research_experiment_execution_plan_registry(
    registry_file: str | Path,
) -> OfflineResearchExperimentExecutionPlanVerificationReport:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    registry = load_offline_research_experiment_execution_plan_registry(path)
    report = OfflineResearchExperimentExecutionPlanVerificationReport(
        registry_file=path,
        verified_at_utc=datetime.now(timezone.utc),
        approved=True,
        registry_id=registry.registry_id,
        registry_version=registry.registry_version,
        plan_count=registry.plan_count,
        registry_hash=registry.registry_hash,
        plan_ids=tuple(plan.plan_id for plan in registry.plans),
        plan_hashes=tuple(plan.plan_hash for plan in registry.plans),
        execution_ids=tuple(plan.execution_id for plan in registry.plans),
        offline_only=registry.offline_only,
        historical_research_only=registry.historical_research_only,
        operational_evidence=registry.operational_evidence,
        paper_promotion_eligible=registry.paper_promotion_eligible,
        non_operational_declaration=registry.non_operational_declaration,
    )
    if _canonical_json(report.as_dict()) != _canonical_json(report.canonical_payload(include_report_hash=True)):
        raise OfflineResearchExperimentExecutionPlanIntegrityError(
            "registry verification report payload mismatch."
        )
    return report


__all__ = [
    "OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_ALLOWED_RESEARCH_MODES",
    "OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_NON_OPERATIONAL_DECLARATION",
    "OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_RESEARCH_MODE",
    "OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REGISTRY_ID",
    "OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REGISTRY_VERSION",
    "OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REQUIRED_ABORT_CONDITIONS",
    "OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_REQUIRED_PRECONDITIONS",
    "OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_SCHEMA_VERSION",
    "OfflineResearchExperimentExecutionPlan",
    "OfflineResearchExperimentExecutionPlanConflictError",
    "OfflineResearchExperimentExecutionPlanError",
    "OfflineResearchExperimentExecutionPlanIntegrityError",
    "OfflineResearchExperimentExecutionPlanRegistry",
    "OfflineResearchExperimentExecutionPlanValidationError",
    "OfflineResearchExperimentExecutionPlanVerificationReport",
    "build_offline_research_experiment_execution_plan",
    "get_offline_research_experiment_execution_plan_by_execution_id_and_number",
    "get_offline_research_experiment_execution_plan_by_hash",
    "get_offline_research_experiment_execution_plan_by_id",
    "list_offline_research_experiment_execution_plan_registry_plans",
    "load_offline_research_experiment_execution_plan_registry",
    "register_offline_research_experiment_execution_plan",
    "save_offline_research_experiment_execution_plan_registry",
    "verify_offline_research_experiment_execution_plan_registry",
]
