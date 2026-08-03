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

from . import offline_research_canonical_evidence_fixture as phase44_fixture
from . import offline_research_experiment_execution_plan as phase43_plan
from . import offline_research_experiment_execution_registry as phase42_registry
from . import offline_research_experiment_registry as phase41_registry
from .errors import (
    HistoricalDataConflictError,
    HistoricalDataError,
    HistoricalDataIntegrityError,
    HistoricalDataValidationError,
)
from .research_artifact_registry import OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION
from . import offline_research_experiment_contract as phase40_contract

OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_SCHEMA_VERSION = 1
OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_VERSION = "phase45_offline_execution_authorization_v1"
OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REGISTRY_ID = "offline_research_execution_authorization_registry"
OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REGISTRY_VERSION = "phase45_offline_execution_authorization_registry_v1"
OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_ALLOWED_DECISIONS = (
    "AUTHORIZED_FOR_FUTURE_OFFLINE_EXECUTION",
    "REJECTED",
    "INVALIDATED",
)
OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REQUIRED_PRECONDITIONS = (
    "PHASE_41_EXPERIMENT_REGISTRATION_VALID",
    "PHASE_42_EXECUTION_REGISTRATION_VALID",
    "DATASET_IDENTITY_MATCHES",
    "STRATEGY_IDENTITY_MATCHES",
    "WINDOW_WITHIN_ARTIFACT",
    "NO_OPERATIONAL_PERMISSION",
    "SOURCE_COMMIT_RECORDED",
    "PHASE_43_PLAN_VALID",
    "PHASE_44_EVIDENCE_VALID",
    "ALL_HASHES_MATCH",
    "ALL_SAFETY_FLAGS_VALID",
    "NO_ABORT_CONDITION_TRIGGERED",
)
OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REQUIRED_ABORT_CONDITIONS = (
    "EXPERIMENT_REGISTRATION_INTEGRITY_FAILURE",
    "EXECUTION_REGISTRATION_INTEGRITY_FAILURE",
    "PLAN_INTEGRITY_FAILURE",
    "EVIDENCE_INTEGRITY_FAILURE",
    "DATASET_IDENTITY_MISMATCH",
    "STRATEGY_IDENTITY_MISMATCH",
    "WINDOW_OUTSIDE_ARTIFACT",
    "SCHEMA_MISMATCH",
    "HASH_MISMATCH",
    "OPERATIONAL_PERMISSION_DETECTED",
    "SOURCE_COMMIT_MISMATCH",
    "MISSING_REQUIRED_PRECONDITION",
)
OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_NON_OPERATIONAL_DECLARATION = (
    "This authorization is research-only and does not execute or authorize immediate replay, backtest, "
    "walk-forward, performance evaluation, ranking, paper trading, live trading, exchange connectivity, "
    "strategy execution, position management, or order submission. It only records eligibility for a "
    "separately controlled future offline execution phase."
)
OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_AUTHORIZED = "AUTHORIZED_FOR_FUTURE_OFFLINE_EXECUTION"
OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_REJECTED = "REJECTED"
OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_INVALIDATED = "INVALIDATED"
OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REASON_AUTHORIZED = (
    "all required preconditions and evidence checks passed."
)
OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REASON_REJECTED = "one or more authorization checks failed."
OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REASON_INVALIDATED = "previous authorization invalidated."


class OfflineResearchExecutionAuthorizationError(HistoricalDataError):
    pass


class OfflineResearchExecutionAuthorizationValidationError(
    OfflineResearchExecutionAuthorizationError,
    HistoricalDataValidationError,
):
    pass


class OfflineResearchExecutionAuthorizationIntegrityError(
    OfflineResearchExecutionAuthorizationError,
    HistoricalDataIntegrityError,
):
    pass


class OfflineResearchExecutionAuthorizationConflictError(
    OfflineResearchExecutionAuthorizationError,
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
        raise OfflineResearchExecutionAuthorizationValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineResearchExecutionAuthorizationValidationError(f"{field_name} is required.")
    return value.strip()


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineResearchExecutionAuthorizationValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineResearchExecutionAuthorizationValidationError(f"{field_name} must be a boolean.")
    return value


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchExecutionAuthorizationValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_commit_sha(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 40 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchExecutionAuthorizationValidationError(
            f"{field_name} must be a 40-character hex git commit sha."
        )
    return digest


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineResearchExecutionAuthorizationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise OfflineResearchExecutionAuthorizationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise OfflineResearchExecutionAuthorizationValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineResearchExecutionAuthorizationValidationError(
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
        raise OfflineResearchExecutionAuthorizationValidationError(
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


def _normalize_exact_string_sequence(
    value: Sequence[str] | set[str] | frozenset[str] | None,
    *,
    field_name: str,
    expected_items: tuple[str, ...],
) -> tuple[str, ...]:
    if value is None:
        candidate_items = expected_items
    elif isinstance(value, (str, bytes)) or not isinstance(value, (Sequence, set, frozenset)):
        raise OfflineResearchExecutionAuthorizationValidationError(
            f"{field_name} must be a non-empty sequence of strings."
        )
    else:
        candidate_items = tuple(value)
    if not candidate_items:
        raise OfflineResearchExecutionAuthorizationValidationError(f"{field_name} must not be empty.")

    seen: set[str] = set()
    normalized: list[str] = []
    required_set = set(expected_items)
    for item in candidate_items:
        normalized_item = _require_str(item, field_name[:-1] if field_name.endswith("s") else field_name)
        if normalized_item not in required_set:
            raise OfflineResearchExecutionAuthorizationValidationError(
                f"{field_name} contains an unexpected value."
            )
        if normalized_item in seen:
            raise OfflineResearchExecutionAuthorizationValidationError(f"{field_name} contains duplicates.")
        seen.add(normalized_item)
        normalized.append(normalized_item)
    if seen != required_set:
        missing = [item for item in expected_items if item not in seen]
        raise OfflineResearchExecutionAuthorizationValidationError(
            f"{field_name} is missing required values: {', '.join(missing)}."
        )
    return tuple(item for item in expected_items if item in seen)


def _normalize_subset_string_sequence(
    value: Sequence[str] | set[str] | frozenset[str] | None,
    *,
    field_name: str,
    allowed_items: tuple[str, ...],
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, (Sequence, set, frozenset)):
        raise OfflineResearchExecutionAuthorizationValidationError(
            f"{field_name} must be a non-empty sequence of strings."
        )
    candidate_items = tuple(value)
    if not candidate_items:
        return ()
    seen: set[str] = set()
    normalized: list[str] = []
    allowed_set = set(allowed_items)
    for item in candidate_items:
        normalized_item = _require_str(item, field_name[:-1] if field_name.endswith("s") else field_name)
        if normalized_item not in allowed_set:
            raise OfflineResearchExecutionAuthorizationValidationError(
                f"{field_name} contains an unexpected value."
            )
        if normalized_item in seen:
            raise OfflineResearchExecutionAuthorizationValidationError(f"{field_name} contains duplicates.")
        seen.add(normalized_item)
        normalized.append(normalized_item)
    return tuple(item for item in allowed_items if item in seen)


def _normalize_decision(value: Any) -> str:
    decision = _require_str(value, "decision").upper()
    if decision not in OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_ALLOWED_DECISIONS:
        raise OfflineResearchExecutionAuthorizationValidationError("decision is not allowed.")
    return decision


def _normalize_reason_sequence(value: Sequence[str] | set[str] | frozenset[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, (Sequence, set, frozenset)):
        raise OfflineResearchExecutionAuthorizationValidationError("rejection_reasons must be a sequence of strings.")
    reasons = tuple(_require_str(item, "rejection_reason") for item in value)
    if not reasons:
        raise OfflineResearchExecutionAuthorizationValidationError("rejection_reasons must not be empty.")
    return reasons


def _plan_snapshot(plan: phase43_plan.OfflineResearchExperimentExecutionPlan) -> Mapping[str, Any]:
    return _freeze_read_only_value(dict(plan.as_dict()))


def _artifact_reference_payload_from_verification(
    verification: phase44_fixture.CanonicalOfflineResearchEvidenceVerification,
) -> Mapping[str, Any]:
    return phase40_contract._artifact_reference_payload(verification.artifact_reference)


def _artifact_reference_snapshot_from_verification(
    verification: phase44_fixture.CanonicalOfflineResearchEvidenceVerification,
) -> Mapping[str, Any]:
    return phase41_registry._artifact_reference_snapshot_payload(  # type: ignore[attr-defined]
        _artifact_reference_payload_from_verification(verification),
        registered_at_utc=verification.experiment_registry.records[0].registered_at_utc,
    )


def _expected_hashes_from_verification(
    verification: phase44_fixture.CanonicalOfflineResearchEvidenceVerification,
) -> dict[str, str]:
    verified_plan_registry = phase43_plan.load_offline_research_experiment_execution_plan_registry(
        verification.execution_plan_registry.registry_file
    )
    verified_execution_registry = phase42_registry.load_offline_research_experiment_execution_registry(
        verification.execution_registry.registry_file
    )
    verified_experiment_registry = phase41_registry.load_offline_research_experiment_registry(
        verification.experiment_registry.registry_file
    )
    return {
        "fixture_version": verification.fixture.fixture_version,
        "artifact_registry_hash": verification.fixture.artifact_registry_hash,
        "artifact_registry_verification_hash": verification.fixture.artifact_registry_verification_hash,
        "dataset_hash": verification.dataset.manifest.dataset_hash,
        "manifest_hash": verification.dataset.manifest.manifest_hash,
        "artifact_reference_hash": verification.artifact_reference_hash,
        "experiment_registry_hash": verified_experiment_registry.registry_hash,
        "experiment_contract_hash": verification.experiment_contract.contract_hash,
        "experiment_registration_hash": verified_experiment_registry.records[0].record_hash,
        "execution_registry_hash": verified_execution_registry.registry_hash,
        "execution_hash": verified_execution_registry.records[0].execution_hash,
        "plan_registry_hash": verified_plan_registry.registry_hash,
        "plan_hash": verified_plan_registry.plans[0].plan_hash,
    }


def _evidence_snapshot(
    verification: phase44_fixture.CanonicalOfflineResearchEvidenceVerification,
) -> Mapping[str, Any]:
    return _freeze_read_only_value(
        {
            "fixture_version": verification.fixture.fixture_version,
            "expected_hashes": verification.expected_hashes,
            "dataset_hash": verification.dataset.manifest.dataset_hash,
            "manifest_hash": verification.dataset.manifest.manifest_hash,
            "artifact_registry_hash": verification.fixture.artifact_registry_hash,
            "artifact_registry_verification_hash": verification.fixture.artifact_registry_verification_hash,
            "artifact_reference_hash": verification.artifact_reference_hash,
            "experiment_contract_hash": verification.experiment_contract.contract_hash,
            "experiment_registration_hash": verification.experiment_registry.records[0].record_hash,
            "experiment_registry_hash": verification.experiment_registry.registry_hash,
            "execution_hash": verification.execution_registry.records[0].execution_hash,
            "execution_registry_hash": verification.execution_registry.registry_hash,
            "plan_hash": verification.execution_plan_registry.plans[0].plan_hash,
            "plan_registry_hash": verification.execution_plan_registry.registry_hash,
            "synthetic": verification.fixture.synthetic,
            "test_only": verification.fixture.test_only,
            "offline_only": verification.fixture.offline_only,
            "operational_evidence": verification.fixture.operational_evidence,
            "paper_promotion_eligible": verification.fixture.paper_promotion_eligible,
            "registry_report": verification.registry_report.as_dict(),
            "artifact_reference": _artifact_reference_payload_from_verification(verification),
            "experiment_contract": verification.experiment_contract.as_dict(),
            "experiment_registration": verification.experiment_registry.records[0].as_dict(),
            "execution_registration": verification.execution_registry.records[0].as_dict(),
            "execution_plan": verification.execution_plan_registry.plans[0].as_dict(),
        }
    )


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise OfflineResearchExecutionAuthorizationValidationError("offline research execution authorization registry is missing.")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise OfflineResearchExecutionAuthorizationValidationError("offline research execution authorization registry is empty.")
    try:
        return json.loads(text)
    except Exception as exc:
        raise OfflineResearchExecutionAuthorizationValidationError(
            "offline research execution authorization registry is invalid JSON."
        ) from exc


def _plan_from_source(
    *,
    plan: phase43_plan.OfflineResearchExperimentExecutionPlan | Mapping[str, Any] | None = None,
    plan_registry_file: str | Path | None = None,
    plan_id: str | None = None,
    plan_hash: str | None = None,
) -> phase43_plan.OfflineResearchExperimentExecutionPlan:
    if plan is not None:
        if any(value is not None for value in (plan_registry_file, plan_id, plan_hash)):
            raise OfflineResearchExecutionAuthorizationValidationError(
                "provide either a phase 43 plan or registry lookup parameters, not both."
            )
        if isinstance(plan, phase43_plan.OfflineResearchExperimentExecutionPlan):
            return plan
        if isinstance(plan, Mapping):
            try:
                return phase43_plan.OfflineResearchExperimentExecutionPlan.from_dict(dict(plan))
            except Exception as exc:
                raise OfflineResearchExecutionAuthorizationValidationError("plan snapshot is invalid.") from exc
        raise OfflineResearchExecutionAuthorizationValidationError("a verified phase 43 plan is required.")

    if plan_registry_file is None:
        raise OfflineResearchExecutionAuthorizationValidationError(
            "plan_registry_file is required when plan is not provided."
        )
    registry_path = _ensure_registry_path(plan_registry_file, field_name="plan_registry_file")
    if plan_hash is None and plan_id is None:
        raise OfflineResearchExecutionAuthorizationValidationError(
            "plan_id or plan_hash is required when plan is not provided."
        )
    registry = phase43_plan.load_offline_research_experiment_execution_plan_registry(registry_path)
    try:
        if plan_hash is not None:
            record = registry.plan_by_hash(plan_hash)
            if plan_id is not None and record.plan_id != _require_str(plan_id, "plan_id"):
                raise OfflineResearchExecutionAuthorizationIntegrityError("plan_id mismatch.")
            return record
        return registry.plan_by_id(plan_id or "")
    except phase43_plan.OfflineResearchExperimentExecutionPlanError as exc:
        raise OfflineResearchExecutionAuthorizationValidationError(str(exc)) from exc


def _evidence_from_source(
    *,
    evidence: phase44_fixture.CanonicalOfflineResearchEvidenceVerification | Mapping[str, Any] | None = None,
    fixture_directory: str | Path | None = None,
) -> phase44_fixture.CanonicalOfflineResearchEvidenceVerification:
    if evidence is not None:
        if fixture_directory is not None:
            raise OfflineResearchExecutionAuthorizationValidationError(
                "provide either a verified phase 44 evidence package or a fixture directory, not both."
            )
        if isinstance(evidence, phase44_fixture.CanonicalOfflineResearchEvidenceVerification):
            return evidence
        raise OfflineResearchExecutionAuthorizationValidationError(
            "a verified phase 44 evidence package is required."
        )
    if fixture_directory is None:
        raise OfflineResearchExecutionAuthorizationValidationError(
            "fixture_directory is required when evidence is not provided."
        )
    return phase44_fixture.verify_canonical_offline_research_evidence_fixture(fixture_directory)


def _evaluate_authorization(
    *,
    plan: phase43_plan.OfflineResearchExperimentExecutionPlan,
    evidence: phase44_fixture.CanonicalOfflineResearchEvidenceVerification,
) -> tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[str, ...], str]:
    verified_preconditions: list[str] = []
    abort_conditions: list[str] = []
    reasons: list[str] = []
    verified_plan_registry = phase43_plan.load_offline_research_experiment_execution_plan_registry(
        evidence.execution_plan_registry.registry_file
    )
    verified_execution_registry = phase42_registry.load_offline_research_experiment_execution_registry(
        evidence.execution_registry.registry_file
    )
    verified_experiment_registry = phase41_registry.load_offline_research_experiment_registry(
        evidence.experiment_registry.registry_file
    )
    canonical_expected_hashes = _expected_hashes_from_verification(evidence)

    def _fail(abort: str, reason: str) -> None:
        if abort not in abort_conditions:
            abort_conditions.append(abort)
        if reason not in reasons:
            reasons.append(reason)

    try:
        matched_plan = verified_plan_registry.plan_by_hash(plan.plan_hash)
    except Exception:
        matched_plan = None
        _fail("PLAN_INTEGRITY_FAILURE", "plan hash does not match the verified phase 43 plan registry.")
    try:
        matching_execution = verified_execution_registry.registration_by_execution_hash(plan.execution_hash)
    except Exception:
        matching_execution = None
        _fail(
            "EXECUTION_REGISTRATION_INTEGRITY_FAILURE",
            "execution hash does not match the verified phase 42 registry.",
        )
    try:
        experiment_record = verified_experiment_registry.record_by_experiment_id(plan.experiment_id)
    except Exception:
        experiment_record = None
        _fail(
            "EXPERIMENT_REGISTRATION_INTEGRITY_FAILURE",
            "experiment registration does not match the verified phase 41 registry.",
        )

    plan_valid = matched_plan is not None
    execution_valid = matching_execution is not None and plan_valid
    experiment_valid = experiment_record is not None and plan_valid
    evidence_valid = True
    hash_match = True
    identity_match = True
    safety_flags_valid = True
    operational_permission_detected = False
    source_commit_recorded = True

    if plan_valid:
        if (
            plan.plan_hash != matched_plan.plan_hash
            or plan.execution_id != matched_plan.execution_id
            or plan.execution_hash != matched_plan.execution_hash
            or plan.experiment_registration_hash != matched_plan.experiment_registration_hash
        ):
            hash_match = False
            _fail("PLAN_INTEGRITY_FAILURE", "plan hash does not match the verified phase 43 plan registry.")
        if plan.experiment_id != matched_plan.experiment_id:
            identity_match = False
            _fail("DATASET_IDENTITY_MISMATCH", "plan experiment identity diverges from the verified phase 43 plan.")
        if plan.requested_start_inclusive_utc != matched_plan.requested_start_inclusive_utc:
            _fail("WINDOW_OUTSIDE_ARTIFACT", "requested_start_inclusive_utc diverges from the verified plan.")
        if plan.requested_end_exclusive_utc != matched_plan.requested_end_exclusive_utc:
            _fail("WINDOW_OUTSIDE_ARTIFACT", "requested_end_exclusive_utc diverges from the verified plan.")
        if plan.expected_symbol != matched_plan.expected_symbol or plan.expected_interval != matched_plan.expected_interval:
            identity_match = False
            _fail("STRATEGY_IDENTITY_MISMATCH", "plan symbol or interval diverges from the verified phase 43 plan.")
        if plan.expected_provider_name != matched_plan.expected_provider_name or plan.expected_market_type != matched_plan.expected_market_type:
            identity_match = False
            _fail("STRATEGY_IDENTITY_MISMATCH", "plan provider or market type diverges from the verified phase 43 plan.")
        if plan.source_commit_sha != matched_plan.source_commit_sha or plan.source_branch != matched_plan.source_branch:
            source_commit_recorded = False
            _fail("SOURCE_COMMIT_MISMATCH", "source commit information diverges from the verified phase 43 plan.")
        if (
            plan.allow_replay
            or plan.allow_backtest
            or plan.allow_walk_forward
            or plan.allow_performance_evaluation
            or plan.allow_ranking
            or plan.allow_paper_trading
            or plan.allow_live_trading
            or plan.allow_exchange_connectivity
            or plan.allow_order_submission
        ):
            operational_permission_detected = True
            _fail("OPERATIONAL_PERMISSION_DETECTED", "plan contains an operational allow flag.")
        if (
            plan.offline_only is not True
            or plan.historical_research_only is not True
            or plan.operational_evidence is not False
            or plan.paper_promotion_eligible is not False
        ):
            safety_flags_valid = False
            _fail("SCHEMA_MISMATCH", "plan safety flags diverge from the offline research contract.")
    if execution_valid:
        if matching_execution.execution_id != matched_plan.execution_id:
            hash_match = False
            _fail("EXECUTION_REGISTRATION_INTEGRITY_FAILURE", "execution_id diverges from the verified phase 42 registry.")
        if matching_execution.execution_hash != matched_plan.execution_hash:
            hash_match = False
            _fail("HASH_MISMATCH", "execution_hash diverges from the verified phase 42 registry.")
        if matching_execution.experiment_id != matched_plan.experiment_id:
            identity_match = False
            _fail("EXPERIMENT_REGISTRATION_INTEGRITY_FAILURE", "execution experiment identity diverges from the verified phase 42 registry.")
        if matching_execution.experiment_registration_hash != matched_plan.experiment_registration_hash:
            hash_match = False
            _fail("EXPERIMENT_REGISTRATION_INTEGRITY_FAILURE", "execution experiment registration hash diverges from the verified phase 42 registry.")
    if experiment_valid:
        if experiment_record.record_hash != matched_plan.experiment_registration_hash:
            hash_match = False
            _fail("EXPERIMENT_REGISTRATION_INTEGRITY_FAILURE", "experiment registration hash diverges from the verified phase 41 registry.")
        if experiment_record.contract_snapshot["contract_hash"] != evidence.experiment_contract.contract_hash:
            identity_match = False
            _fail("STRATEGY_IDENTITY_MISMATCH", "experiment contract hash diverges from the verified phase 41 registry.")
        if _hash_payload(experiment_record.artifact_reference_snapshot) != _hash_payload(
            _artifact_reference_snapshot_from_verification(evidence)
        ):
            evidence_valid = False
            _fail("EVIDENCE_INTEGRITY_FAILURE", "artifact reference snapshot diverges from the verified phase 41 registry.")

    evidence_snapshot = _evidence_snapshot(evidence)
    if evidence.fixture.fixture_version != phase44_fixture.FIXTURE_VERSION:
        evidence_valid = False
        _fail("SCHEMA_MISMATCH", "fixture version diverges from the canonical phase 44 fixture.")
    if not evidence.fixture.synthetic or not evidence.fixture.test_only or not evidence.fixture.offline_only:
        evidence_valid = False
        _fail("SCHEMA_MISMATCH", "fixture declarations are not purely offline synthetic evidence.")
    if evidence.fixture.operational_evidence is not False or evidence.fixture.paper_promotion_eligible is not False:
        operational_permission_detected = True
        _fail("OPERATIONAL_PERMISSION_DETECTED", "fixture flags permit operational evidence.")
    if evidence.registry_report.operational_evidence is not False or evidence.registry_report.paper_promotion_eligible is not False:
        operational_permission_detected = True
        _fail("OPERATIONAL_PERMISSION_DETECTED", "registry report flags permit operational evidence.")
    if not evidence.artifact_reference.read_only or not evidence.artifact_reference.historical_research_only:
        evidence_valid = False
        _fail("EVIDENCE_INTEGRITY_FAILURE", "artifact reference is not read-only historical research evidence.")
    if evidence.artifact_reference.operational_evidence is not False or evidence.artifact_reference.paper_promotion_eligible is not False:
        operational_permission_detected = True
        _fail("OPERATIONAL_PERMISSION_DETECTED", "artifact reference permits operational evidence.")
    if dict(evidence.expected_hashes) != canonical_expected_hashes:
        hash_match = False
        _fail("HASH_MISMATCH", "expected hash set diverges from the canonical fixture.")
    if evidence.execution_plan_registry.plans[0].plan_hash != canonical_expected_hashes["plan_hash"]:
        hash_match = False
        _fail("HASH_MISMATCH", "plan hash diverges from the canonical fixture.")
    if evidence.execution_registry.records[0].execution_hash != canonical_expected_hashes["execution_hash"]:
        hash_match = False
        _fail("HASH_MISMATCH", "execution hash diverges from the canonical fixture.")
    if evidence.experiment_registry.records[0].record_hash != canonical_expected_hashes["experiment_registration_hash"]:
        hash_match = False
        _fail("HASH_MISMATCH", "experiment registration hash diverges from the canonical fixture.")
    if evidence.dataset.manifest.dataset_hash != canonical_expected_hashes["dataset_hash"]:
        hash_match = False
        _fail("HASH_MISMATCH", "dataset hash diverges from the canonical fixture.")
    if evidence.dataset.manifest.manifest_hash != canonical_expected_hashes["manifest_hash"]:
        hash_match = False
        _fail("HASH_MISMATCH", "manifest hash diverges from the canonical fixture.")
    if evidence.artifact_reference_hash != canonical_expected_hashes["artifact_reference_hash"]:
        hash_match = False
        _fail("HASH_MISMATCH", "artifact reference hash diverges from the canonical fixture.")
    if evidence.experiment_contract.contract_hash != canonical_expected_hashes["experiment_contract_hash"]:
        hash_match = False
        _fail("HASH_MISMATCH", "experiment contract hash diverges from the canonical fixture.")
    if verified_experiment_registry.records[0].record_hash != canonical_expected_hashes["experiment_registration_hash"]:
        hash_match = False
        _fail("HASH_MISMATCH", "experiment registration hash diverges from the canonical fixture.")
    if verified_execution_registry.records[0].execution_hash != canonical_expected_hashes["execution_hash"]:
        hash_match = False
        _fail("HASH_MISMATCH", "execution hash diverges from the canonical fixture.")
    if verified_plan_registry.plans[0].plan_hash != canonical_expected_hashes["plan_hash"]:
        hash_match = False
        _fail("HASH_MISMATCH", "plan hash diverges from the canonical fixture.")
    if plan.requested_start_inclusive_utc < evidence.experiment_contract.window_start_utc:
        _fail("WINDOW_OUTSIDE_ARTIFACT", "plan starts before the verified artifact window.")
    if plan.requested_end_exclusive_utc > evidence.experiment_contract.window_end_utc:
        _fail("WINDOW_OUTSIDE_ARTIFACT", "plan ends after the verified artifact window.")
    if plan.expected_symbol != evidence.artifact_reference.registry_report.instrument:
        identity_match = False
        _fail("STRATEGY_IDENTITY_MISMATCH", "plan symbol diverges from the verified evidence.")
    if plan.expected_interval != evidence.registry_report.interval:
        identity_match = False
        _fail("STRATEGY_IDENTITY_MISMATCH", "plan interval diverges from the verified evidence.")
    if plan.expected_provider_name != evidence.registry_report.provider_name.upper():
        identity_match = False
        _fail("STRATEGY_IDENTITY_MISMATCH", "plan provider diverges from the verified evidence.")
    if plan.expected_market_type != evidence.registry_report.market_type.lower():
        identity_match = False
        _fail("STRATEGY_IDENTITY_MISMATCH", "plan market type diverges from the verified evidence.")
    if plan.source_commit_sha != verified_execution_registry.records[0].source_commit_sha:
        source_commit_recorded = False
        _fail("SOURCE_COMMIT_MISMATCH", "source commit sha diverges from the verified evidence.")
    if plan.source_branch != verified_execution_registry.records[0].source_branch:
        source_commit_recorded = False
        _fail("SOURCE_COMMIT_MISMATCH", "source branch diverges from the verified evidence.")
    if plan.offline_only is not True or plan.historical_research_only is not True or plan.operational_evidence is not False or plan.paper_promotion_eligible is not False:
        safety_flags_valid = False
        _fail("SCHEMA_MISMATCH", "plan safety flags diverge from the canonical contract.")

    if not abort_conditions:
        verified_preconditions.extend(
            [
                "PHASE_41_EXPERIMENT_REGISTRATION_VALID",
                "PHASE_42_EXECUTION_REGISTRATION_VALID",
                "DATASET_IDENTITY_MATCHES",
                "STRATEGY_IDENTITY_MATCHES",
                "WINDOW_WITHIN_ARTIFACT",
                "NO_OPERATIONAL_PERMISSION",
                "SOURCE_COMMIT_RECORDED",
                "PHASE_43_PLAN_VALID",
                "PHASE_44_EVIDENCE_VALID",
                "ALL_HASHES_MATCH",
                "ALL_SAFETY_FLAGS_VALID",
                "NO_ABORT_CONDITION_TRIGGERED",
            ]
        )
    else:
        if experiment_valid:
            verified_preconditions.append("PHASE_41_EXPERIMENT_REGISTRATION_VALID")
        if execution_valid:
            verified_preconditions.append("PHASE_42_EXECUTION_REGISTRATION_VALID")
        if plan_valid:
            verified_preconditions.append("PHASE_43_PLAN_VALID")
        if evidence_valid:
            verified_preconditions.append("PHASE_44_EVIDENCE_VALID")
        if hash_match:
            verified_preconditions.append("ALL_HASHES_MATCH")
        if safety_flags_valid:
            verified_preconditions.append("ALL_SAFETY_FLAGS_VALID")
        if not operational_permission_detected:
            verified_preconditions.append("NO_OPERATIONAL_PERMISSION")
        if source_commit_recorded:
            verified_preconditions.append("SOURCE_COMMIT_RECORDED")
        if identity_match:
            verified_preconditions.append("STRATEGY_IDENTITY_MATCHES")
        if (
            plan.requested_start_inclusive_utc >= evidence.experiment_contract.window_start_utc
            and plan.requested_end_exclusive_utc <= evidence.experiment_contract.window_end_utc
        ):
            verified_preconditions.append("WINDOW_WITHIN_ARTIFACT")
        if (
            evidence.dataset.manifest.dataset_hash == canonical_expected_hashes["dataset_hash"]
            and evidence.dataset.manifest.manifest_hash == canonical_expected_hashes["manifest_hash"]
        ):
            verified_preconditions.append("DATASET_IDENTITY_MATCHES")
        if not abort_conditions:
            verified_preconditions.append("NO_ABORT_CONDITION_TRIGGERED")

    if abort_conditions:
        decision = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_REJECTED
        decision_reason = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REASON_REJECTED
        allow_future = False
        reasons = reasons or [OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REASON_REJECTED]
    else:
        decision = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_AUTHORIZED
        decision_reason = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REASON_AUTHORIZED
        allow_future = True
        reasons = [OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REASON_AUTHORIZED]
        verified_preconditions = list(OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REQUIRED_PRECONDITIONS)

    return (
        decision,
        decision_reason,
        tuple(reasons),
        tuple(dict.fromkeys(verified_preconditions)),
        tuple(dict.fromkeys(abort_conditions)),
        "phase44 canonical evidence verified" if allow_future else "phase44 canonical evidence rejected",
    )


@dataclass(frozen=True, slots=True)
class OfflineResearchExecutionAuthorization:
    schema_version: int = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_SCHEMA_VERSION
    authorization_id: str = ""
    authorization_version: str = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_VERSION
    authorization_number: int = 1
    previous_authorization_id: str | None = None
    previous_authorization_hash: str | None = None
    plan_id: str = ""
    plan_hash: str = ""
    execution_id: str = ""
    execution_hash: str = ""
    experiment_id: str = ""
    experiment_registration_hash: str = ""
    decision: str = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_REJECTED
    decision_reason: str = ""
    rejection_reasons: tuple[str, ...] = field(default_factory=tuple)
    issued_at_utc: datetime = field(default_factory=lambda: datetime(1970, 1, 1, tzinfo=timezone.utc))
    source_commit_sha: str = ""
    source_branch: str = ""
    verified_fixture_version: str = ""
    verified_fixture_hash: str | None = None
    required_preconditions: tuple[str, ...] = field(default_factory=tuple)
    verified_preconditions: tuple[str, ...] = field(default_factory=tuple)
    triggered_abort_conditions: tuple[str, ...] = field(default_factory=tuple)
    allow_future_offline_execution: bool = False
    allow_replay: bool = False
    allow_backtest: bool = False
    allow_walk_forward: bool = False
    allow_performance_evaluation: bool = False
    allow_ranking: bool = False
    allow_paper_trading: bool = False
    allow_live_trading: bool = False
    allow_exchange_connectivity: bool = False
    allow_strategy_execution: bool = False
    allow_order_submission: bool = False
    offline_only: bool = True
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    plan_snapshot: Mapping[str, Any] = field(default_factory=dict, repr=False)
    evidence_snapshot: Mapping[str, Any] = field(default_factory=dict, repr=False)
    non_operational_declaration: str = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_NON_OPERATIONAL_DECLARATION
    authorization_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "authorization_id", _require_hex_digest(self.authorization_id, "authorization_id") if self.authorization_id else "")
        object.__setattr__(self, "authorization_version", _require_str(self.authorization_version, "authorization_version"))
        object.__setattr__(self, "authorization_number", _require_int(self.authorization_number, "authorization_number"))
        object.__setattr__(self, "plan_id", _require_str(self.plan_id, "plan_id"))
        object.__setattr__(self, "plan_hash", _require_hex_digest(self.plan_hash, "plan_hash"))
        object.__setattr__(self, "execution_id", _require_str(self.execution_id, "execution_id"))
        object.__setattr__(self, "execution_hash", _require_hex_digest(self.execution_hash, "execution_hash"))
        object.__setattr__(self, "experiment_id", _require_str(self.experiment_id, "experiment_id"))
        object.__setattr__(self, "experiment_registration_hash", _require_hex_digest(self.experiment_registration_hash, "experiment_registration_hash"))
        object.__setattr__(self, "decision", _normalize_decision(self.decision))
        object.__setattr__(self, "decision_reason", _require_str(self.decision_reason, "decision_reason"))
        object.__setattr__(self, "rejection_reasons", _normalize_reason_sequence(self.rejection_reasons))
        object.__setattr__(self, "issued_at_utc", _require_utc_datetime(self.issued_at_utc, "issued_at_utc"))
        object.__setattr__(self, "source_commit_sha", _require_commit_sha(self.source_commit_sha, "source_commit_sha"))
        object.__setattr__(self, "source_branch", _require_str(self.source_branch, "source_branch"))
        object.__setattr__(self, "verified_fixture_version", _require_str(self.verified_fixture_version, "verified_fixture_version"))
        object.__setattr__(self, "verified_fixture_hash", _require_hex_digest(self.verified_fixture_hash, "verified_fixture_hash") if self.verified_fixture_hash else None)
        object.__setattr__(self, "required_preconditions", _normalize_exact_string_sequence(self.required_preconditions, field_name="required_preconditions", expected_items=OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REQUIRED_PRECONDITIONS))
        object.__setattr__(self, "verified_preconditions", _normalize_subset_string_sequence(self.verified_preconditions, field_name="verified_preconditions", allowed_items=OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REQUIRED_PRECONDITIONS))
        object.__setattr__(self, "triggered_abort_conditions", _normalize_subset_string_sequence(self.triggered_abort_conditions, field_name="triggered_abort_conditions", allowed_items=OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REQUIRED_ABORT_CONDITIONS))
        object.__setattr__(self, "allow_future_offline_execution", _require_bool(self.allow_future_offline_execution, "allow_future_offline_execution"))
        object.__setattr__(self, "allow_replay", _require_bool(self.allow_replay, "allow_replay"))
        object.__setattr__(self, "allow_backtest", _require_bool(self.allow_backtest, "allow_backtest"))
        object.__setattr__(self, "allow_walk_forward", _require_bool(self.allow_walk_forward, "allow_walk_forward"))
        object.__setattr__(self, "allow_performance_evaluation", _require_bool(self.allow_performance_evaluation, "allow_performance_evaluation"))
        object.__setattr__(self, "allow_ranking", _require_bool(self.allow_ranking, "allow_ranking"))
        object.__setattr__(self, "allow_paper_trading", _require_bool(self.allow_paper_trading, "allow_paper_trading"))
        object.__setattr__(self, "allow_live_trading", _require_bool(self.allow_live_trading, "allow_live_trading"))
        object.__setattr__(self, "allow_exchange_connectivity", _require_bool(self.allow_exchange_connectivity, "allow_exchange_connectivity"))
        object.__setattr__(self, "allow_strategy_execution", _require_bool(self.allow_strategy_execution, "allow_strategy_execution"))
        object.__setattr__(self, "allow_order_submission", _require_bool(self.allow_order_submission, "allow_order_submission"))
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if not isinstance(self.plan_snapshot, Mapping):
            raise OfflineResearchExecutionAuthorizationValidationError("plan_snapshot must be a mapping.")
        if not isinstance(self.evidence_snapshot, Mapping):
            raise OfflineResearchExecutionAuthorizationValidationError("evidence_snapshot must be a mapping.")
        object.__setattr__(self, "plan_snapshot", _freeze_read_only_value(dict(self.plan_snapshot)))
        object.__setattr__(self, "evidence_snapshot", _freeze_read_only_value(dict(self.evidence_snapshot)))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))

        if self.schema_version != OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_SCHEMA_VERSION:
            raise OfflineResearchExecutionAuthorizationValidationError("schema_version must be 1.")
        if self.authorization_version != OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_VERSION:
            raise OfflineResearchExecutionAuthorizationValidationError(
                "authorization_version must remain phase45_offline_execution_authorization_v1."
            )
        if self.authorization_number <= 0:
            raise OfflineResearchExecutionAuthorizationValidationError("authorization_number must be greater than zero.")
        if self.decision not in OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_ALLOWED_DECISIONS:
            raise OfflineResearchExecutionAuthorizationValidationError("decision is not allowed.")
        if self.offline_only is not True:
            raise OfflineResearchExecutionAuthorizationValidationError("offline_only must be true.")
        if self.historical_research_only is not True:
            raise OfflineResearchExecutionAuthorizationValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchExecutionAuthorizationValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchExecutionAuthorizationValidationError("paper_promotion_eligible must be false.")
        if any(
            flag is not False
            for flag in (
                self.allow_replay,
                self.allow_backtest,
                self.allow_walk_forward,
                self.allow_performance_evaluation,
                self.allow_ranking,
                self.allow_paper_trading,
                self.allow_live_trading,
                self.allow_exchange_connectivity,
                self.allow_strategy_execution,
                self.allow_order_submission,
            )
        ):
            raise OfflineResearchExecutionAuthorizationValidationError(
                "all operational allow_* flags except allow_future_offline_execution must be false"
            )
        if self.non_operational_declaration != OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchExecutionAuthorizationValidationError(
                "non_operational_declaration diverges from the research-only contract."
            )
        if self.decision == OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_AUTHORIZED:
            if self.allow_future_offline_execution is not True:
                raise OfflineResearchExecutionAuthorizationValidationError(
                    "allow_future_offline_execution must be true for an authorized record."
                )
            if self.rejection_reasons == ():
                raise OfflineResearchExecutionAuthorizationValidationError(
                    "rejection_reasons must be populated for an authorized record."
                )
            if self.triggered_abort_conditions:
                raise OfflineResearchExecutionAuthorizationValidationError(
                    "authorized records must not record abort conditions."
                )
            if self.previous_authorization_id is not None or self.previous_authorization_hash is not None:
                raise OfflineResearchExecutionAuthorizationValidationError(
                    "authorized records must not reference a previous authorization."
                )
        elif self.decision == OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_REJECTED:
            if self.allow_future_offline_execution is not False:
                raise OfflineResearchExecutionAuthorizationValidationError(
                    "allow_future_offline_execution must be false for a rejected record."
                )
            if self.rejection_reasons == ():
                raise OfflineResearchExecutionAuthorizationValidationError(
                    "rejection_reasons must be populated for a rejected record."
                )
            if self.previous_authorization_id is not None or self.previous_authorization_hash is not None:
                raise OfflineResearchExecutionAuthorizationValidationError(
                    "rejected records must not reference a previous authorization."
                )
        elif self.decision == OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_INVALIDATED:
            if self.allow_future_offline_execution is not False:
                raise OfflineResearchExecutionAuthorizationValidationError(
                    "allow_future_offline_execution must be false for an invalidated record."
                )
            if self.rejection_reasons == ():
                raise OfflineResearchExecutionAuthorizationValidationError(
                    "rejection_reasons must be populated for an invalidated record."
                )
            if self.previous_authorization_id is None or self.previous_authorization_hash is None:
                raise OfflineResearchExecutionAuthorizationValidationError(
                    "invalidated records must reference a previous authorization."
                )
        else:  # pragma: no cover - exhaustive guard
            raise OfflineResearchExecutionAuthorizationValidationError("decision is not allowed.")

        expected_authorization_id = _hash_payload(self._authorization_id_payload())
        if self.authorization_id:
            if self.authorization_id != expected_authorization_id:
                raise OfflineResearchExecutionAuthorizationIntegrityError("authorization_id mismatch.")
        else:
            object.__setattr__(self, "authorization_id", expected_authorization_id)

        expected_authorization_hash = _hash_payload(self.canonical_payload(include_authorization_hash=False))
        if self.authorization_hash:
            if self.authorization_hash != expected_authorization_hash:
                raise OfflineResearchExecutionAuthorizationIntegrityError("authorization_hash mismatch.")
        else:
            object.__setattr__(self, "authorization_hash", expected_authorization_hash)

    def _authorization_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authorization_version": self.authorization_version,
            "authorization_number": self.authorization_number,
            "previous_authorization_id": self.previous_authorization_id,
            "previous_authorization_hash": self.previous_authorization_hash,
            "plan_id": self.plan_id,
            "plan_hash": self.plan_hash,
            "execution_id": self.execution_id,
            "execution_hash": self.execution_hash,
            "experiment_id": self.experiment_id,
            "experiment_registration_hash": self.experiment_registration_hash,
            "decision": self.decision,
            "decision_reason": self.decision_reason,
            "rejection_reasons": self.rejection_reasons,
            "issued_at_utc": _utc_iso(self.issued_at_utc),
            "source_commit_sha": self.source_commit_sha,
            "source_branch": self.source_branch,
            "verified_fixture_version": self.verified_fixture_version,
            "verified_fixture_hash": self.verified_fixture_hash,
            "required_preconditions": self.required_preconditions,
            "verified_preconditions": self.verified_preconditions,
            "triggered_abort_conditions": self.triggered_abort_conditions,
            "allow_future_offline_execution": self.allow_future_offline_execution,
            "allow_replay": self.allow_replay,
            "allow_backtest": self.allow_backtest,
            "allow_walk_forward": self.allow_walk_forward,
            "allow_performance_evaluation": self.allow_performance_evaluation,
            "allow_ranking": self.allow_ranking,
            "allow_paper_trading": self.allow_paper_trading,
            "allow_live_trading": self.allow_live_trading,
            "allow_exchange_connectivity": self.allow_exchange_connectivity,
            "allow_strategy_execution": self.allow_strategy_execution,
            "allow_order_submission": self.allow_order_submission,
            "offline_only": self.offline_only,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "plan_snapshot": _thaw_read_only_value(self.plan_snapshot),
            "evidence_snapshot": _thaw_read_only_value(self.evidence_snapshot),
            "non_operational_declaration": self.non_operational_declaration,
        }

    def canonical_payload(self, *, include_authorization_hash: bool = True) -> dict[str, Any]:
        payload = self._authorization_id_payload()
        payload["authorization_id"] = self.authorization_id
        if include_authorization_hash:
            payload["authorization_hash"] = self.authorization_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_authorization_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfflineResearchExecutionAuthorization":
        if not isinstance(data, Mapping):
            raise OfflineResearchExecutionAuthorizationValidationError(
                "offline research execution authorization must be a mapping."
            )
        mapping = dict(data)
        allowed = {
            "schema_version",
            "authorization_id",
            "authorization_version",
            "authorization_number",
            "previous_authorization_id",
            "previous_authorization_hash",
            "plan_id",
            "plan_hash",
            "execution_id",
            "execution_hash",
            "experiment_id",
            "experiment_registration_hash",
            "decision",
            "decision_reason",
            "rejection_reasons",
            "issued_at_utc",
            "source_commit_sha",
            "source_branch",
            "verified_fixture_version",
            "verified_fixture_hash",
            "required_preconditions",
            "verified_preconditions",
            "triggered_abort_conditions",
            "allow_future_offline_execution",
            "allow_replay",
            "allow_backtest",
            "allow_walk_forward",
            "allow_performance_evaluation",
            "allow_ranking",
            "allow_paper_trading",
            "allow_live_trading",
            "allow_exchange_connectivity",
            "allow_strategy_execution",
            "allow_order_submission",
            "offline_only",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "plan_snapshot",
            "evidence_snapshot",
            "non_operational_declaration",
            "authorization_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise OfflineResearchExecutionAuthorizationValidationError(
                f"unexpected offline research execution authorization fields: {', '.join(extra)}."
            )
        try:
            return cls(
                schema_version=mapping.get("schema_version", OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_SCHEMA_VERSION),
                authorization_id=mapping.get("authorization_id", ""),
                authorization_version=mapping.get(
                    "authorization_version",
                    OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_VERSION,
                ),
                authorization_number=mapping.get("authorization_number", 1),
                previous_authorization_id=mapping.get("previous_authorization_id"),
                previous_authorization_hash=mapping.get("previous_authorization_hash"),
                plan_id=mapping["plan_id"],
                plan_hash=mapping["plan_hash"],
                execution_id=mapping["execution_id"],
                execution_hash=mapping["execution_hash"],
                experiment_id=mapping["experiment_id"],
                experiment_registration_hash=mapping["experiment_registration_hash"],
                decision=mapping["decision"],
                decision_reason=mapping["decision_reason"],
                rejection_reasons=tuple(mapping.get("rejection_reasons", ())),
                issued_at_utc=mapping.get("issued_at_utc", datetime(1970, 1, 1, tzinfo=timezone.utc)),
                source_commit_sha=mapping["source_commit_sha"],
                source_branch=mapping["source_branch"],
                verified_fixture_version=mapping["verified_fixture_version"],
                verified_fixture_hash=mapping.get("verified_fixture_hash"),
                required_preconditions=tuple(mapping.get("required_preconditions", ())),
                verified_preconditions=tuple(mapping.get("verified_preconditions", ())),
                triggered_abort_conditions=tuple(mapping.get("triggered_abort_conditions", ())),
                allow_future_offline_execution=mapping.get("allow_future_offline_execution", False),
                allow_replay=mapping.get("allow_replay", False),
                allow_backtest=mapping.get("allow_backtest", False),
                allow_walk_forward=mapping.get("allow_walk_forward", False),
                allow_performance_evaluation=mapping.get("allow_performance_evaluation", False),
                allow_ranking=mapping.get("allow_ranking", False),
                allow_paper_trading=mapping.get("allow_paper_trading", False),
                allow_live_trading=mapping.get("allow_live_trading", False),
                allow_exchange_connectivity=mapping.get("allow_exchange_connectivity", False),
                allow_strategy_execution=mapping.get("allow_strategy_execution", False),
                allow_order_submission=mapping.get("allow_order_submission", False),
                offline_only=mapping.get("offline_only", True),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                plan_snapshot=mapping.get("plan_snapshot", {}),
                evidence_snapshot=mapping.get("evidence_snapshot", {}),
                non_operational_declaration=mapping.get(
                    "non_operational_declaration",
                    OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_NON_OPERATIONAL_DECLARATION,
                ),
                authorization_hash=mapping.get("authorization_hash", ""),
            )
        except KeyError as exc:
            raise OfflineResearchExecutionAuthorizationValidationError(
                "offline research execution authorization is incomplete."
            ) from exc


def _authorization_from_sources(
    *,
    plan: phase43_plan.OfflineResearchExperimentExecutionPlan | Mapping[str, Any] | None = None,
    plan_registry_file: str | Path | None = None,
    plan_id: str | None = None,
    plan_hash: str | None = None,
    evidence: phase44_fixture.CanonicalOfflineResearchEvidenceVerification | Mapping[str, Any] | None = None,
    fixture_directory: str | Path | None = None,
    issued_at_utc: datetime,
    source_commit_sha: str | None = None,
    source_branch: str | None = None,
    authorization_number: int | None = None,
    previous_authorization: OfflineResearchExecutionAuthorization | Mapping[str, Any] | None = None,
) -> OfflineResearchExecutionAuthorization:
    resolved_plan = _plan_from_source(plan=plan, plan_registry_file=plan_registry_file, plan_id=plan_id, plan_hash=plan_hash)
    resolved_evidence = _evidence_from_source(evidence=evidence, fixture_directory=fixture_directory)
    if not isinstance(resolved_evidence, phase44_fixture.CanonicalOfflineResearchEvidenceVerification):
        raise OfflineResearchExecutionAuthorizationValidationError("a verified phase 44 evidence package is required.")

    decision, decision_reason, rejection_reasons, verified_preconditions, abort_conditions, _ = _evaluate_authorization(
        plan=resolved_plan,
        evidence=resolved_evidence,
    )
    plan_snapshot = _plan_snapshot(resolved_plan)
    evidence_snapshot = _evidence_snapshot(resolved_evidence)

    if source_commit_sha is None:
        source_commit_sha = resolved_plan.source_commit_sha
    if source_branch is None:
        source_branch = resolved_plan.source_branch

    if previous_authorization is not None and not isinstance(previous_authorization, OfflineResearchExecutionAuthorization):
        if isinstance(previous_authorization, Mapping):
            previous_authorization = OfflineResearchExecutionAuthorization.from_dict(dict(previous_authorization))
        else:
            raise OfflineResearchExecutionAuthorizationValidationError(
                "previous_authorization must be a verified authorization."
            )

    previous_authorization_id = None
    previous_authorization_hash = None
    if previous_authorization is not None:
        previous_authorization_id = previous_authorization.authorization_id
        previous_authorization_hash = previous_authorization.authorization_hash
        decision = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_INVALIDATED
        decision_reason = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REASON_INVALIDATED
        rejection_reasons = (OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REASON_INVALIDATED,)
        verified_preconditions = previous_authorization.verified_preconditions
        abort_conditions = ()

    if authorization_number is None:
        authorization_number = (previous_authorization.authorization_number + 1) if previous_authorization is not None else 1

    allow_future = decision == OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_AUTHORIZED
    if decision == OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_INVALIDATED:
        allow_future = False

    verified_fixture_hash = _hash_payload(evidence_snapshot)
    return OfflineResearchExecutionAuthorization(
        authorization_number=authorization_number,
        previous_authorization_id=previous_authorization_id,
        previous_authorization_hash=previous_authorization_hash,
        plan_id=resolved_plan.plan_id,
        plan_hash=resolved_plan.plan_hash,
        execution_id=resolved_plan.execution_id,
        execution_hash=resolved_plan.execution_hash,
        experiment_id=resolved_plan.experiment_id,
        experiment_registration_hash=resolved_plan.experiment_registration_hash,
        decision=decision,
        decision_reason=decision_reason,
        rejection_reasons=rejection_reasons,
        issued_at_utc=issued_at_utc,
        source_commit_sha=source_commit_sha,
        source_branch=source_branch,
        verified_fixture_version=resolved_evidence.fixture.fixture_version,
        verified_fixture_hash=verified_fixture_hash,
        required_preconditions=OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REQUIRED_PRECONDITIONS,
        verified_preconditions=verified_preconditions,
        triggered_abort_conditions=abort_conditions,
        allow_future_offline_execution=allow_future,
        allow_replay=False,
        allow_backtest=False,
        allow_walk_forward=False,
        allow_performance_evaluation=False,
        allow_ranking=False,
        allow_paper_trading=False,
        allow_live_trading=False,
        allow_exchange_connectivity=False,
        allow_strategy_execution=False,
        allow_order_submission=False,
        offline_only=True,
        historical_research_only=True,
        operational_evidence=False,
        paper_promotion_eligible=False,
        plan_snapshot=plan_snapshot,
        evidence_snapshot=evidence_snapshot,
        non_operational_declaration=OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_NON_OPERATIONAL_DECLARATION,
    )


def build_offline_research_execution_authorization(
    *,
    plan: phase43_plan.OfflineResearchExperimentExecutionPlan | Mapping[str, Any] | None = None,
    plan_registry_file: str | Path | None = None,
    plan_id: str | None = None,
    plan_hash: str | None = None,
    evidence: phase44_fixture.CanonicalOfflineResearchEvidenceVerification | Mapping[str, Any] | None = None,
    fixture_directory: str | Path | None = None,
    issued_at_utc: datetime,
    source_commit_sha: str | None = None,
    source_branch: str | None = None,
    authorization_number: int | None = None,
    previous_authorization: OfflineResearchExecutionAuthorization | Mapping[str, Any] | None = None,
) -> OfflineResearchExecutionAuthorization:
    authorization = _authorization_from_sources(
        plan=plan,
        plan_registry_file=plan_registry_file,
        plan_id=plan_id,
        plan_hash=plan_hash,
        evidence=evidence,
        fixture_directory=fixture_directory,
        issued_at_utc=issued_at_utc,
        source_commit_sha=source_commit_sha,
        source_branch=source_branch,
        authorization_number=authorization_number,
        previous_authorization=previous_authorization,
    )
    if authorization.as_dict() != serialize_value(authorization.canonical_payload()):
        raise OfflineResearchExecutionAuthorizationIntegrityError("authorization payload mismatch.")
    return authorization


def invalidate_offline_research_execution_authorization(
    previous_authorization: OfflineResearchExecutionAuthorization | Mapping[str, Any],
    *,
    issued_at_utc: datetime,
    source_commit_sha: str | None = None,
    source_branch: str | None = None,
) -> OfflineResearchExecutionAuthorization:
    if not isinstance(previous_authorization, OfflineResearchExecutionAuthorization):
        if isinstance(previous_authorization, Mapping):
            previous_authorization = OfflineResearchExecutionAuthorization.from_dict(dict(previous_authorization))
        else:
            raise OfflineResearchExecutionAuthorizationValidationError(
                "previous_authorization must be a verified authorization."
            )
    authorization = OfflineResearchExecutionAuthorization(
        authorization_number=previous_authorization.authorization_number + 1,
        previous_authorization_id=previous_authorization.authorization_id,
        previous_authorization_hash=previous_authorization.authorization_hash,
        plan_id=previous_authorization.plan_id,
        plan_hash=previous_authorization.plan_hash,
        execution_id=previous_authorization.execution_id,
        execution_hash=previous_authorization.execution_hash,
        experiment_id=previous_authorization.experiment_id,
        experiment_registration_hash=previous_authorization.experiment_registration_hash,
        decision=OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_INVALIDATED,
        decision_reason=OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REASON_INVALIDATED,
        rejection_reasons=(OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REASON_INVALIDATED,),
        issued_at_utc=issued_at_utc,
        source_commit_sha=source_commit_sha or previous_authorization.source_commit_sha,
        source_branch=source_branch or previous_authorization.source_branch,
        verified_fixture_version=previous_authorization.verified_fixture_version,
        verified_fixture_hash=previous_authorization.verified_fixture_hash,
        required_preconditions=previous_authorization.required_preconditions,
        verified_preconditions=previous_authorization.verified_preconditions,
        triggered_abort_conditions=(),
        allow_future_offline_execution=False,
        allow_replay=False,
        allow_backtest=False,
        allow_walk_forward=False,
        allow_performance_evaluation=False,
        allow_ranking=False,
        allow_paper_trading=False,
        allow_live_trading=False,
        allow_exchange_connectivity=False,
        allow_strategy_execution=False,
        allow_order_submission=False,
        offline_only=previous_authorization.offline_only,
        historical_research_only=previous_authorization.historical_research_only,
        operational_evidence=previous_authorization.operational_evidence,
        paper_promotion_eligible=previous_authorization.paper_promotion_eligible,
        plan_snapshot=previous_authorization.plan_snapshot,
        evidence_snapshot=previous_authorization.evidence_snapshot,
        non_operational_declaration=previous_authorization.non_operational_declaration,
    )
    if authorization.as_dict() != serialize_value(authorization.canonical_payload()):
        raise OfflineResearchExecutionAuthorizationIntegrityError("authorization payload mismatch.")
    return authorization


def _record_sort_key(record: OfflineResearchExecutionAuthorization) -> tuple[int, str, str]:
    return (record.authorization_number, record.authorization_id, record.authorization_hash)


@dataclass(frozen=True, slots=True)
class OfflineResearchExecutionAuthorizationRegistry:
    registry_file: Path = field(default_factory=Path)
    schema_version: int = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_SCHEMA_VERSION
    registry_id: str = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REGISTRY_ID
    registry_version: str = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REGISTRY_VERSION
    created_at_utc: datetime = field(default_factory=lambda: datetime(1970, 1, 1, tzinfo=timezone.utc))
    updated_at_utc: datetime = field(default_factory=lambda: datetime(1970, 1, 1, tzinfo=timezone.utc))
    records: tuple[OfflineResearchExecutionAuthorization, ...] = field(default_factory=tuple)
    offline_only: bool = True
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_NON_OPERATIONAL_DECLARATION
    registry_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_file", Path(self.registry_file))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "registry_id", _require_str(self.registry_id, "registry_id"))
        object.__setattr__(self, "registry_version", _require_str(self.registry_version, "registry_version"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "updated_at_utc", _require_utc_datetime(self.updated_at_utc, "updated_at_utc"))
        object.__setattr__(self, "records", tuple(sorted(tuple(self.records), key=_record_sort_key)))
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.schema_version != OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_SCHEMA_VERSION:
            raise OfflineResearchExecutionAuthorizationValidationError("schema_version must be 1.")
        if self.registry_id != OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REGISTRY_ID:
            raise OfflineResearchExecutionAuthorizationValidationError(
                "registry_id must remain offline_research_execution_authorization_registry."
            )
        if self.registry_version != OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REGISTRY_VERSION:
            raise OfflineResearchExecutionAuthorizationValidationError(
                "registry_version must remain phase45_offline_execution_authorization_registry_v1."
            )
        if self.offline_only is not True:
            raise OfflineResearchExecutionAuthorizationValidationError("offline_only must be true.")
        if self.historical_research_only is not True:
            raise OfflineResearchExecutionAuthorizationValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchExecutionAuthorizationValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchExecutionAuthorizationValidationError("paper_promotion_eligible must be false.")
        if self.non_operational_declaration != OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchExecutionAuthorizationValidationError(
                "non_operational_declaration diverges from the research-only contract."
            )
        expected_hash = _hash_payload(self.canonical_payload(include_registry_hash=False))
        if self.registry_hash:
            if self.registry_hash != expected_hash:
                raise OfflineResearchExecutionAuthorizationIntegrityError("registry_hash mismatch.")
        else:
            object.__setattr__(self, "registry_hash", expected_hash)

    @property
    def authorization_count(self) -> int:
        return len(self.records)

    def canonical_payload(self, *, include_registry_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "registry_file": self.registry_file.as_posix(),
            "registry_id": self.registry_id,
            "registry_version": self.registry_version,
            "created_at_utc": _utc_iso(self.created_at_utc),
            "updated_at_utc": _utc_iso(self.updated_at_utc),
            "authorization_count": self.authorization_count,
            "records": [record.canonical_payload(include_authorization_hash=True) for record in self.records],
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
    ) -> "OfflineResearchExecutionAuthorizationRegistry":
        if not isinstance(data, Mapping):
            raise OfflineResearchExecutionAuthorizationValidationError(
                "offline research execution authorization registry must be a mapping."
            )
        mapping = dict(data)
        allowed = {
            "schema_version",
            "registry_file",
            "registry_id",
            "registry_version",
            "created_at_utc",
            "updated_at_utc",
            "authorization_count",
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
            raise OfflineResearchExecutionAuthorizationValidationError(
                f"unexpected offline research execution authorization registry fields: {', '.join(extra)}."
            )
        if "records" not in mapping:
            raise OfflineResearchExecutionAuthorizationValidationError(
                "offline research execution authorization registry is incomplete."
            )
        try:
            records = tuple(OfflineResearchExecutionAuthorization.from_dict(item) for item in mapping.get("records", ()))
            return cls(
                registry_file=registry_file,
                schema_version=mapping.get("schema_version", OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_SCHEMA_VERSION),
                registry_id=mapping.get("registry_id", OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REGISTRY_ID),
                registry_version=mapping.get("registry_version", OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REGISTRY_VERSION),
                created_at_utc=mapping.get("created_at_utc", datetime(1970, 1, 1, tzinfo=timezone.utc)),
                updated_at_utc=mapping.get("updated_at_utc", datetime(1970, 1, 1, tzinfo=timezone.utc)),
                records=records,
                offline_only=mapping.get("offline_only", True),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                non_operational_declaration=mapping.get(
                    "non_operational_declaration",
                    OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_NON_OPERATIONAL_DECLARATION,
                ),
                registry_hash=mapping.get("registry_hash", ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OfflineResearchExecutionAuthorizationValidationError(
                "offline research execution authorization registry is incomplete."
            ) from exc

    def authorization_by_id(self, authorization_id: str) -> OfflineResearchExecutionAuthorization:
        target = _require_str(authorization_id, "authorization_id")
        for record in self.records:
            if record.authorization_id == target:
                return record
        raise OfflineResearchExecutionAuthorizationValidationError("authorization_id was not found in the registry.")

    def authorization_by_hash(self, authorization_hash: str) -> OfflineResearchExecutionAuthorization:
        target = _require_hex_digest(authorization_hash, "authorization_hash")
        for record in self.records:
            if record.authorization_hash == target:
                return record
        raise OfflineResearchExecutionAuthorizationValidationError("authorization_hash was not found in the registry.")

    def authorizations_for_plan_id(self, plan_id: str) -> tuple[OfflineResearchExecutionAuthorization, ...]:
        target = _require_str(plan_id, "plan_id")
        return tuple(record for record in self.records if record.plan_id == target)

    def with_record(
        self,
        record: OfflineResearchExecutionAuthorization,
        *,
        updated_at_utc: datetime | None = None,
    ) -> "OfflineResearchExecutionAuthorizationRegistry":
        return OfflineResearchExecutionAuthorizationRegistry(
            registry_file=self.registry_file,
            schema_version=self.schema_version,
            registry_id=self.registry_id,
            registry_version=self.registry_version,
            created_at_utc=self.created_at_utc,
            updated_at_utc=updated_at_utc or self.updated_at_utc,
            records=tuple(self.records) + (record,),
            offline_only=self.offline_only,
            historical_research_only=self.historical_research_only,
            operational_evidence=self.operational_evidence,
            paper_promotion_eligible=self.paper_promotion_eligible,
            non_operational_declaration=self.non_operational_declaration,
        )


@dataclass(frozen=True, slots=True)
class OfflineResearchExecutionAuthorizationRegistryVerificationReport:
    schema_version: int = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_SCHEMA_VERSION
    registry_file: Path = field(default_factory=Path)
    verified_at_utc: datetime = field(default_factory=lambda: datetime(1970, 1, 1, tzinfo=timezone.utc))
    approved: bool = True
    registry_id: str = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REGISTRY_ID
    registry_version: str = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REGISTRY_VERSION
    authorization_count: int = 0
    registry_hash: str = ""
    authorization_ids: tuple[str, ...] = ()
    authorization_hashes: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    offline_only: bool = True
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_NON_OPERATIONAL_DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_file", Path(self.registry_file))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "verified_at_utc", _require_utc_datetime(self.verified_at_utc, "verified_at_utc"))
        object.__setattr__(self, "approved", _require_bool(self.approved, "approved"))
        object.__setattr__(self, "registry_id", _require_str(self.registry_id, "registry_id"))
        object.__setattr__(self, "registry_version", _require_str(self.registry_version, "registry_version"))
        object.__setattr__(self, "authorization_count", _require_int(self.authorization_count, "authorization_count"))
        object.__setattr__(self, "registry_hash", _require_hex_digest(self.registry_hash, "registry_hash") if self.registry_hash else "")
        object.__setattr__(self, "authorization_ids", tuple(_require_str(item, "authorization_id") for item in self.authorization_ids))
        object.__setattr__(self, "authorization_hashes", tuple(_require_hex_digest(item, "authorization_hash") for item in self.authorization_hashes))
        object.__setattr__(self, "decisions", tuple(_normalize_decision(item) for item in self.decisions))
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.approved is not True:
            raise OfflineResearchExecutionAuthorizationValidationError("approved must be true.")

    def canonical_payload(self, *, include_registry_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "registry_file": self.registry_file.as_posix(),
            "verified_at_utc": _utc_iso(self.verified_at_utc),
            "approved": self.approved,
            "registry_id": self.registry_id,
            "registry_version": self.registry_version,
            "authorization_count": self.authorization_count,
            "authorization_ids": self.authorization_ids,
            "authorization_hashes": self.authorization_hashes,
            "decisions": self.decisions,
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


def _assert_registry_conflicts(
    registry: OfflineResearchExecutionAuthorizationRegistry,
    record: OfflineResearchExecutionAuthorization,
) -> None:
    try:
        existing_by_id = registry.authorization_by_id(record.authorization_id)
    except OfflineResearchExecutionAuthorizationValidationError:
        existing_by_id = None
    try:
        existing_by_hash = registry.authorization_by_hash(record.authorization_hash)
    except OfflineResearchExecutionAuthorizationValidationError:
        existing_by_hash = None
    if existing_by_hash is not None:
        return
    if existing_by_id is not None and existing_by_id.as_dict() != record.as_dict():
        raise OfflineResearchExecutionAuthorizationConflictError("authorization_id already registered.")


def load_offline_research_execution_authorization_registry(
    registry_file: str | Path,
) -> OfflineResearchExecutionAuthorizationRegistry:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    payload = _load_json(path)
    if not isinstance(payload, Mapping):
        raise OfflineResearchExecutionAuthorizationValidationError(
            "offline research execution authorization registry must be a JSON object."
        )
    registry = OfflineResearchExecutionAuthorizationRegistry.from_dict(payload, registry_file=path)
    if _canonical_json(registry.as_dict()) != _canonical_json(payload):
        raise OfflineResearchExecutionAuthorizationIntegrityError(
            "offline research execution authorization registry payload mismatch."
        )
    return registry


def save_offline_research_execution_authorization_registry(
    registry_file: str | Path,
    registry: OfflineResearchExecutionAuthorizationRegistry,
) -> OfflineResearchExecutionAuthorizationRegistry:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    if not isinstance(registry, OfflineResearchExecutionAuthorizationRegistry):
        raise OfflineResearchExecutionAuthorizationValidationError(
            "offline research execution authorization registry is required."
        )
    payload = registry.as_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{id(registry)}.tmp")
    try:
        tmp_path.write_text(_canonical_json(payload), encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise OfflineResearchExecutionAuthorizationValidationError(
            "failed to write offline research execution authorization registry atomically."
        ) from exc
    return registry


def register_offline_research_execution_authorization(
    *,
    registry_file: str | Path,
    authorization: OfflineResearchExecutionAuthorization,
    updated_at_utc: datetime | None = None,
) -> OfflineResearchExecutionAuthorization:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    if not isinstance(authorization, OfflineResearchExecutionAuthorization):
        raise OfflineResearchExecutionAuthorizationValidationError(
            "offline research execution authorization is required."
        )
    registry = (
        load_offline_research_execution_authorization_registry(path)
        if path.exists()
        else OfflineResearchExecutionAuthorizationRegistry(
            registry_file=path,
            created_at_utc=updated_at_utc or authorization.issued_at_utc,
            updated_at_utc=updated_at_utc or authorization.issued_at_utc,
        )
    )
    _assert_registry_conflicts(registry, authorization)
    if any(existing.as_dict() == authorization.as_dict() for existing in registry.records):
        return next(existing for existing in registry.records if existing.as_dict() == authorization.as_dict())
    updated_registry = registry.with_record(authorization, updated_at_utc=updated_at_utc or authorization.issued_at_utc)
    save_offline_research_execution_authorization_registry(path, updated_registry)
    return authorization


def list_offline_research_execution_authorization_registry_records(
    registry_file: str | Path,
) -> tuple[OfflineResearchExecutionAuthorization, ...]:
    return load_offline_research_execution_authorization_registry(registry_file).records


def get_offline_research_execution_authorization_by_id(
    registry_file: str | Path,
    authorization_id: str,
) -> OfflineResearchExecutionAuthorization:
    return load_offline_research_execution_authorization_registry(registry_file).authorization_by_id(authorization_id)


def get_offline_research_execution_authorization_by_hash(
    registry_file: str | Path,
    authorization_hash: str,
) -> OfflineResearchExecutionAuthorization:
    return load_offline_research_execution_authorization_registry(registry_file).authorization_by_hash(authorization_hash)


def verify_offline_research_execution_authorization_registry(
    registry_file: str | Path,
) -> OfflineResearchExecutionAuthorizationRegistryVerificationReport:
    path = _ensure_registry_path(registry_file, field_name="registry_file")
    registry = load_offline_research_execution_authorization_registry(path)
    report = OfflineResearchExecutionAuthorizationRegistryVerificationReport(
        registry_file=path,
        verified_at_utc=registry.updated_at_utc,
        approved=True,
        registry_id=registry.registry_id,
        registry_version=registry.registry_version,
        authorization_count=registry.authorization_count,
        registry_hash=registry.registry_hash,
        authorization_ids=tuple(record.authorization_id for record in registry.records),
        authorization_hashes=tuple(record.authorization_hash for record in registry.records),
        decisions=tuple(record.decision for record in registry.records),
        offline_only=registry.offline_only,
        historical_research_only=registry.historical_research_only,
        operational_evidence=registry.operational_evidence,
        paper_promotion_eligible=registry.paper_promotion_eligible,
        non_operational_declaration=registry.non_operational_declaration,
    )
    if _canonical_json(report.as_dict()) != _canonical_json(report.canonical_payload(include_registry_hash=True)):
        raise OfflineResearchExecutionAuthorizationIntegrityError(
            "registry verification report payload mismatch."
        )
    return report


__all__ = [
    "OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_ALLOWED_DECISIONS",
    "OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_AUTHORIZED",
    "OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_INVALIDATED",
    "OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_REJECTED",
    "OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_NON_OPERATIONAL_DECLARATION",
    "OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REASON_AUTHORIZED",
    "OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REASON_INVALIDATED",
    "OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REASON_REJECTED",
    "OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REGISTRY_ID",
    "OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REGISTRY_VERSION",
    "OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REQUIRED_ABORT_CONDITIONS",
    "OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REQUIRED_PRECONDITIONS",
    "OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_SCHEMA_VERSION",
    "OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_VERSION",
    "OfflineResearchExecutionAuthorization",
    "OfflineResearchExecutionAuthorizationConflictError",
    "OfflineResearchExecutionAuthorizationError",
    "OfflineResearchExecutionAuthorizationIntegrityError",
    "OfflineResearchExecutionAuthorizationRegistry",
    "OfflineResearchExecutionAuthorizationRegistryVerificationReport",
    "OfflineResearchExecutionAuthorizationValidationError",
    "build_offline_research_execution_authorization",
    "get_offline_research_execution_authorization_by_hash",
    "get_offline_research_execution_authorization_by_id",
    "invalidate_offline_research_execution_authorization",
    "list_offline_research_execution_authorization_registry_records",
    "load_offline_research_execution_authorization_registry",
    "register_offline_research_execution_authorization",
    "save_offline_research_execution_authorization_registry",
    "verify_offline_research_execution_authorization_registry",
]
