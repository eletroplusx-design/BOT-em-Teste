from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Any, Mapping

from domain.serialization import serialize_value

from . import (
    offline_research_backtest as phase38_backtest,
    offline_research_canonical_evidence_fixture as phase44_fixture,
    offline_research_execution_authorization as phase45_auth,
    offline_research_execution_envelope as phase46_envelope,
    offline_research_experiment_contract as phase40_contract,
    offline_research_experiment_execution_plan as phase43_plan,
    offline_research_experiment_execution_registry as phase42_registry,
    offline_research_experiment_registry as phase41_registry,
    offline_research_neutral_executor as phase47_executor,
)
from .errors import HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError

OFFLINE_EXECUTION_AUDIT_RECORD_SCHEMA_VERSION = 1
OFFLINE_EXECUTION_AUDIT_RECORD_VERSION = "phase48_offline_execution_audit_record_v1"
OFFLINE_EXECUTION_AUDIT_RECORD_NON_OPERATIONAL_DECLARATION = (
    "This audit record is research-only and does not authorize replay, backtest, walk-forward, performance "
    "evaluation, ranking, paper trading, live trading, strategy execution, order submission, exchange "
    "connectivity, or any other operational activity."
)


class OfflineExecutionAuditRecordError(HistoricalDataError):
    pass


class OfflineExecutionAuditRecordValidationError(
    OfflineExecutionAuditRecordError,
    HistoricalDataValidationError,
):
    pass


class OfflineExecutionAuditRecordIntegrityError(
    OfflineExecutionAuditRecordError,
    HistoricalDataIntegrityError,
):
    pass


class OfflineExecutionAuditRecordPersistenceError(OfflineExecutionAuditRecordError):
    pass


class OfflineExecutionAuditRecordConflictError(
    OfflineExecutionAuditRecordError,
    HistoricalDataValidationError,
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        serialize_value(_thaw_read_only_value(payload)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash_payload(payload: Any) -> str:
    try:
        return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    except (TypeError, ValueError) as exc:
        raise OfflineExecutionAuditRecordValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineExecutionAuditRecordValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineExecutionAuditRecordValidationError(f"{field_name} must be a 64-character hex digest.")
    return digest


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineExecutionAuditRecordValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineExecutionAuditRecordValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineExecutionAuditRecordValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise OfflineExecutionAuditRecordValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise OfflineExecutionAuditRecordValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineExecutionAuditRecordValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _is_temporary_pytest_path(path: Path) -> bool:
    normalized = str(path).replace("\\", "/")
    return any(part == ".pytest_tmp" for part in normalized.split("/") if part)


def _is_windows_rooted_path(path_text: str) -> bool:
    windows_path = PureWindowsPath(path_text)
    return bool(windows_path.drive or windows_path.anchor)


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


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OfflineExecutionAuditRecordValidationError(f"{field_name} must be a mapping.")
    return value


def _metadata_snapshot(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    snapshot = _freeze_read_only_value(dict(metadata))
    if not isinstance(snapshot, Mapping):
        raise OfflineExecutionAuditRecordValidationError("metadata must be a mapping.")
    provenance = snapshot.get("provenance")
    if not isinstance(provenance, Mapping):
        raise OfflineExecutionAuditRecordValidationError("metadata.provenance is required.")
    return snapshot


def _artifact_reference_snapshot(
    artifact_reference: phase38_backtest.OkxOfflineResearchArtifactReference,
) -> dict[str, Any]:
    registry_report = artifact_reference.registry_report
    return {
        "registry_report": registry_report.as_dict(),
        "dataset_report": _thaw_read_only_value(artifact_reference.dataset_report),
        "artifact_root": artifact_reference.artifact_root.resolve().as_posix(),
    }


def _experiment_contract_snapshot(
    experiment_contract: phase40_contract.OfflineResearchExperimentContract,
) -> dict[str, Any]:
    return experiment_contract.as_dict()


def _experiment_registry_snapshot(
    experiment_registry: phase41_registry.OfflineResearchExperimentRegistry,
) -> dict[str, Any]:
    return experiment_registry.as_dict()


def _execution_registry_snapshot(
    execution_registry: phase42_registry.OfflineResearchExperimentExecutionRegistry,
) -> dict[str, Any]:
    return execution_registry.as_dict()


def _execution_plan_snapshot(
    execution_plan: phase43_plan.OfflineResearchExperimentExecutionPlan,
) -> dict[str, Any]:
    return execution_plan.as_dict()


def _evidence_snapshot(
    evidence: phase44_fixture.CanonicalOfflineResearchEvidenceVerification,
) -> dict[str, Any]:
    return phase45_auth._evidence_snapshot(evidence)  # type: ignore[attr-defined]


def _authorization_snapshot(authorization: phase45_auth.OfflineResearchExecutionAuthorization) -> dict[str, Any]:
    return authorization.as_dict()


def _envelope_snapshot(envelope: phase46_envelope.OfflineResearchExecutionEnvelope) -> dict[str, Any]:
    return envelope.as_dict()


def _result_snapshot(result: phase47_executor.OfflineResearchNeutralExecutionResult) -> dict[str, Any]:
    return result.as_dict()


def _provenance_snapshot(
    *,
    artifact_reference: phase38_backtest.OkxOfflineResearchArtifactReference,
    experiment_contract: phase40_contract.OfflineResearchExperimentContract,
    experiment_registry: phase41_registry.OfflineResearchExperimentRegistry,
    execution_registry: phase42_registry.OfflineResearchExperimentExecutionRegistry,
    execution_plan: phase43_plan.OfflineResearchExperimentExecutionPlan,
    evidence: phase44_fixture.CanonicalOfflineResearchEvidenceVerification,
    authorization: phase45_auth.OfflineResearchExecutionAuthorization,
    envelope: phase46_envelope.OfflineResearchExecutionEnvelope,
    result: phase47_executor.OfflineResearchNeutralExecutionResult,
) -> dict[str, Any]:
    return {
        "artifact_reference": _artifact_reference_snapshot(artifact_reference),
        "experiment_contract": _experiment_contract_snapshot(experiment_contract),
        "experiment_registry": _experiment_registry_snapshot(experiment_registry),
        "execution_registry": _execution_registry_snapshot(execution_registry),
        "execution_plan": _execution_plan_snapshot(execution_plan),
        "evidence": _evidence_snapshot(evidence),
        "authorization": _authorization_snapshot(authorization),
        "envelope": _envelope_snapshot(envelope),
        "result": _result_snapshot(result),
    }


def _rooted_record_path(
    record_file: str | Path,
    *,
    root_directory: str | Path | None,
    field_name: str,
) -> tuple[Path, Path]:
    root = Path(root_directory) if root_directory is not None else Path.cwd()
    if _is_temporary_pytest_path(root):
        raise OfflineExecutionAuditRecordValidationError(f"{field_name} root must not point to .pytest_tmp.")
    if not isinstance(record_file, (str, Path)):
        raise OfflineExecutionAuditRecordValidationError(f"{field_name} must be a path.")
    candidate = Path(record_file)
    candidate_text = str(candidate)
    if candidate_text.startswith("~"):
        raise OfflineExecutionAuditRecordValidationError(f"{field_name} must not use home expansion.")
    if candidate.is_absolute() or _is_windows_rooted_path(candidate_text):
        raise OfflineExecutionAuditRecordValidationError(f"{field_name} must be relative to the authorized root.")
    if any(part == ".." for part in candidate.parts):
        raise OfflineExecutionAuditRecordValidationError(f"{field_name} must not traverse outside the authorized root.")
    if _is_temporary_pytest_path(candidate):
        raise OfflineExecutionAuditRecordValidationError(f"{field_name} must not point to .pytest_tmp.")

    root_resolved = root.resolve(strict=False)
    target = (root_resolved / candidate).resolve(strict=False)
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise OfflineExecutionAuditRecordValidationError(
            f"{field_name} must remain within the authorized root."
        ) from exc
    return root_resolved, target


def _write_json_atomic(path: Path, payload: Any) -> None:
    canonical = _canonical_json(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == canonical:
        return
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{id(payload)}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        try:
            dir_handle = os.open(path.parent, os.O_RDONLY)
        except Exception:
            return
        try:
            os.fsync(dir_handle)
        finally:
            os.close(dir_handle)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise OfflineExecutionAuditRecordPersistenceError(
            "failed to write offline execution audit record atomically."
        ) from exc


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise OfflineExecutionAuditRecordValidationError("offline execution audit record is missing.")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise OfflineExecutionAuditRecordValidationError("offline execution audit record is empty.")
    try:
        return json.loads(text)
    except Exception as exc:
        raise OfflineExecutionAuditRecordValidationError(
            "offline execution audit record is invalid JSON."
        ) from exc


def _validate_chain(
    *,
    artifact_reference: phase38_backtest.OkxOfflineResearchArtifactReference,
    experiment_contract: phase40_contract.OfflineResearchExperimentContract,
    experiment_registry: phase41_registry.OfflineResearchExperimentRegistry,
    execution_registry: phase42_registry.OfflineResearchExperimentExecutionRegistry,
    execution_plan: phase43_plan.OfflineResearchExperimentExecutionPlan,
    evidence: phase44_fixture.CanonicalOfflineResearchEvidenceVerification,
    authorization: phase45_auth.OfflineResearchExecutionAuthorization,
    envelope: phase46_envelope.OfflineResearchExecutionEnvelope,
    result: phase47_executor.OfflineResearchNeutralExecutionResult,
) -> dict[str, Any]:
    if not isinstance(artifact_reference, phase38_backtest.OkxOfflineResearchArtifactReference):
        raise OfflineExecutionAuditRecordValidationError("artifact_reference must be a verified offline reference.")
    if not isinstance(experiment_contract, phase40_contract.OfflineResearchExperimentContract):
        raise OfflineExecutionAuditRecordValidationError("experiment_contract must be a verified phase 40 contract.")
    if not isinstance(experiment_registry, phase41_registry.OfflineResearchExperimentRegistry):
        raise OfflineExecutionAuditRecordValidationError("experiment_registry must be a verified phase 41 registry.")
    if not isinstance(execution_registry, phase42_registry.OfflineResearchExperimentExecutionRegistry):
        raise OfflineExecutionAuditRecordValidationError("execution_registry must be a verified phase 42 registry.")
    if not isinstance(execution_plan, phase43_plan.OfflineResearchExperimentExecutionPlan):
        raise OfflineExecutionAuditRecordValidationError("execution_plan must be a verified phase 43 plan.")
    if not isinstance(evidence, phase44_fixture.CanonicalOfflineResearchEvidenceVerification):
        raise OfflineExecutionAuditRecordValidationError("evidence must be a verified phase 44 bundle.")
    if not isinstance(authorization, phase45_auth.OfflineResearchExecutionAuthorization):
        raise OfflineExecutionAuditRecordValidationError("authorization must be a verified phase 45 authorization.")
    if not isinstance(envelope, phase46_envelope.OfflineResearchExecutionEnvelope):
        raise OfflineExecutionAuditRecordValidationError("envelope must be a verified phase 46 envelope.")
    if not isinstance(result, phase47_executor.OfflineResearchNeutralExecutionResult):
        raise OfflineExecutionAuditRecordValidationError("result must be a verified phase 47 result.")

    artifact_payload = _artifact_reference_snapshot(artifact_reference)
    contract_payload = _experiment_contract_snapshot(experiment_contract)
    registry_payload = _experiment_registry_snapshot(experiment_registry)
    execution_registry_payload = _execution_registry_snapshot(execution_registry)
    plan_payload = _execution_plan_snapshot(execution_plan)
    evidence_payload = _evidence_snapshot(evidence)
    authorization_payload = _authorization_snapshot(authorization)
    envelope_payload = _envelope_snapshot(envelope)
    result_payload = _result_snapshot(result)

    if contract_payload["artifact_reference"]["artifact_id"] != artifact_reference.registry_report.artifact_id:
        raise OfflineExecutionAuditRecordIntegrityError("artifact reference id mismatch.")
    if contract_payload["artifact_reference"]["manifest_hash"] != artifact_reference.registry_report.manifest_hash:
        raise OfflineExecutionAuditRecordIntegrityError("artifact reference manifest_hash mismatch.")
    if contract_payload["artifact_reference"]["dataset_hash"] != artifact_reference.dataset_report["dataset_hash"]:
        raise OfflineExecutionAuditRecordIntegrityError("artifact reference dataset_hash mismatch.")
    if contract_payload["strategy_contract"]["strategy_id"] != "baseline_a_okx_btc_usdt_1h_research":
        raise OfflineExecutionAuditRecordValidationError("strategy_id must remain baseline_a_okx_btc_usdt_1h_research.")
    if contract_payload["strategy_contract"]["contract_hash"] != experiment_contract.strategy_contract["contract_hash"]:
        raise OfflineExecutionAuditRecordIntegrityError("strategy contract_hash mismatch.")

    registry_record = experiment_registry.record_by_experiment_id(experiment_contract.experiment_id)
    if registry_record.experiment_fingerprint != experiment_contract.contract_hash:
        raise OfflineExecutionAuditRecordIntegrityError("experiment_fingerprint mismatch.")
    if _canonical_json(registry_record.contract.as_dict()) != _canonical_json(experiment_contract.as_dict()):
        raise OfflineExecutionAuditRecordIntegrityError("experiment contract snapshot mismatch.")
    if registry_record.artifact_reference_snapshot["registry_report"]["artifact_id"] != artifact_reference.registry_report.artifact_id:
        raise OfflineExecutionAuditRecordIntegrityError("registry artifact reference mismatch.")

    expected_registry_hash = _hash_payload(experiment_registry.canonical_payload(include_registry_hash=False))
    if registry_payload["registry_hash"] != expected_registry_hash:
        raise OfflineExecutionAuditRecordIntegrityError("experiment_registry_hash mismatch.")

    execution_record = execution_registry.registration_by_execution_hash(execution_plan.execution_hash)
    if execution_record.execution_id != execution_plan.execution_id:
        raise OfflineExecutionAuditRecordIntegrityError("execution_id mismatch.")
    if execution_record.experiment_id != execution_plan.experiment_id:
        raise OfflineExecutionAuditRecordIntegrityError("execution registry experiment mismatch.")
    if execution_record.execution_hash != execution_plan.execution_hash:
        raise OfflineExecutionAuditRecordIntegrityError("execution_hash mismatch.")
    if execution_record.attempt_number <= 0:
        raise OfflineExecutionAuditRecordValidationError("attempt_number must be greater than zero.")
    if _canonical_json(execution_record.as_dict()) != _canonical_json(execution_plan.execution_registration_snapshot):
        raise OfflineExecutionAuditRecordIntegrityError("execution registration snapshot mismatch.")

    plan_from_registry = execution_plan
    if execution_plan.plan_hash != evidence.execution_plan_registry.plan_by_id(execution_plan.plan_id).plan_hash:
        raise OfflineExecutionAuditRecordIntegrityError("execution_plan_hash mismatch.")
    if plan_from_registry.experiment_id != experiment_contract.experiment_id:
        raise OfflineExecutionAuditRecordIntegrityError("execution plan experiment mismatch.")
    if plan_from_registry.execution_hash != execution_record.execution_hash:
        raise OfflineExecutionAuditRecordIntegrityError("execution hash mismatch.")
    if plan_from_registry.execution_id != execution_record.execution_id:
        raise OfflineExecutionAuditRecordIntegrityError("execution id mismatch.")
    if plan_from_registry.plan_hash != evidence.execution_plan_registry.plan_by_execution_id_and_number(
        execution_plan.execution_id,
        execution_plan.plan_number,
    ).plan_hash:
        raise OfflineExecutionAuditRecordIntegrityError("execution plan registry mismatch.")

    if authorization.plan_hash != execution_plan.plan_hash:
        raise OfflineExecutionAuditRecordIntegrityError("authorization plan_hash mismatch.")
    if authorization.experiment_id != experiment_contract.experiment_id:
        raise OfflineExecutionAuditRecordIntegrityError("authorization experiment_id mismatch.")
    if envelope.authorization_hash != authorization.authorization_hash:
        raise OfflineExecutionAuditRecordIntegrityError("envelope authorization_hash mismatch.")
    if envelope.plan_hash != execution_plan.plan_hash:
        raise OfflineExecutionAuditRecordIntegrityError("envelope plan_hash mismatch.")
    if envelope.strategy_fingerprint != experiment_contract.strategy_contract["contract_hash"]:
        raise OfflineExecutionAuditRecordIntegrityError("envelope strategy_fingerprint mismatch.")
    if envelope.artifact_reference_hash != evidence.artifact_reference_hash:
        raise OfflineExecutionAuditRecordIntegrityError("envelope artifact_reference_hash mismatch.")
    if envelope.evidence_hash != _hash_payload(evidence_payload):
        raise OfflineExecutionAuditRecordIntegrityError("envelope evidence_hash mismatch.")
    if result.envelope_id != envelope.envelope_id:
        raise OfflineExecutionAuditRecordIntegrityError("result envelope_id mismatch.")
    if result.envelope_hash != envelope.envelope_hash:
        raise OfflineExecutionAuditRecordIntegrityError("result envelope_hash mismatch.")
    if result.authorization_id != authorization.authorization_id:
        raise OfflineExecutionAuditRecordIntegrityError("result authorization_id mismatch.")
    if result.plan_id != execution_plan.plan_id:
        raise OfflineExecutionAuditRecordIntegrityError("result plan_id mismatch.")
    if result.experiment_id != experiment_contract.experiment_id:
        raise OfflineExecutionAuditRecordIntegrityError("result experiment_id mismatch.")
    if result.execution_id != execution_record.execution_id:
        raise OfflineExecutionAuditRecordIntegrityError("result execution_id mismatch.")
    if result.execution_number != execution_record.attempt_number:
        raise OfflineExecutionAuditRecordIntegrityError("result execution_number mismatch.")
    if result.strategy_id != experiment_contract.strategy_contract["strategy_id"]:
        raise OfflineExecutionAuditRecordIntegrityError("result strategy_id mismatch.")
    if result.strategy_version != experiment_contract.strategy_contract["strategy_version"]:
        raise OfflineExecutionAuditRecordIntegrityError("result strategy_version mismatch.")
    if result.strategy_fingerprint != experiment_contract.strategy_contract["contract_hash"]:
        raise OfflineExecutionAuditRecordIntegrityError("result strategy_fingerprint mismatch.")
    if result.neutral_execution_id != phase47_executor._hash_payload(result._neutral_execution_identity_payload()):
        raise OfflineExecutionAuditRecordIntegrityError("neutral_execution_id mismatch.")
    if result.result_hash != phase47_executor._hash_payload(result._result_identity_payload()):
        raise OfflineExecutionAuditRecordIntegrityError("result_hash mismatch.")

    provenance = {
        "artifact_reference": artifact_payload,
        "experiment_contract": contract_payload,
        "experiment_registry": registry_payload,
        "execution_registry": execution_registry_payload,
        "execution_plan": plan_payload,
        "evidence": evidence_payload,
        "authorization": authorization_payload,
        "envelope": envelope_payload,
        "result": result_payload,
    }
    return provenance


@dataclass(frozen=True, slots=True)
class OfflineExecutionAuditRecord:
    schema_version: int = OFFLINE_EXECUTION_AUDIT_RECORD_SCHEMA_VERSION
    audit_record_id: str = ""
    audit_record_hash: str = ""
    lineage_hash: str = ""
    artifact_reference_id: str = ""
    experiment_id: str = ""
    experiment_contract_hash: str = ""
    execution_id: str = ""
    execution_attempt_number: int = 0
    execution_attempt_id: str = ""
    execution_plan_hash: str = ""
    evidence_hash: str = ""
    authorization_hash: str = ""
    envelope_hash: str = ""
    neutral_execution_id: str = ""
    result_hash: str = ""
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    offline_only: bool = True
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = OFFLINE_EXECUTION_AUDIT_RECORD_NON_OPERATIONAL_DECLARATION

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "audit_record_id", _require_hex_digest(self.audit_record_id, "audit_record_id") if self.audit_record_id else "")
        object.__setattr__(self, "audit_record_hash", _require_hex_digest(self.audit_record_hash, "audit_record_hash") if self.audit_record_hash else "")
        object.__setattr__(self, "lineage_hash", _require_hex_digest(self.lineage_hash, "lineage_hash"))
        object.__setattr__(self, "artifact_reference_id", _require_hex_digest(self.artifact_reference_id, "artifact_reference_id"))
        object.__setattr__(self, "experiment_id", _require_str(self.experiment_id, "experiment_id"))
        object.__setattr__(self, "experiment_contract_hash", _require_hex_digest(self.experiment_contract_hash, "experiment_contract_hash"))
        object.__setattr__(self, "execution_id", _require_str(self.execution_id, "execution_id"))
        object.__setattr__(self, "execution_attempt_number", _require_int(self.execution_attempt_number, "execution_attempt_number"))
        object.__setattr__(self, "execution_attempt_id", _require_str(self.execution_attempt_id, "execution_attempt_id"))
        object.__setattr__(self, "execution_plan_hash", _require_hex_digest(self.execution_plan_hash, "execution_plan_hash"))
        object.__setattr__(self, "evidence_hash", _require_hex_digest(self.evidence_hash, "evidence_hash"))
        object.__setattr__(self, "authorization_hash", _require_hex_digest(self.authorization_hash, "authorization_hash"))
        object.__setattr__(self, "envelope_hash", _require_hex_digest(self.envelope_hash, "envelope_hash"))
        object.__setattr__(self, "neutral_execution_id", _require_hex_digest(self.neutral_execution_id, "neutral_execution_id"))
        object.__setattr__(self, "result_hash", _require_hex_digest(self.result_hash, "result_hash"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        if not isinstance(self.metadata, Mapping):
            raise OfflineExecutionAuditRecordValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _metadata_snapshot(self.metadata))
        object.__setattr__(self, "offline_only", _require_bool(self.offline_only, "offline_only"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))

        if self.schema_version != OFFLINE_EXECUTION_AUDIT_RECORD_SCHEMA_VERSION:
            raise OfflineExecutionAuditRecordValidationError("schema_version must be 1.")
        if self.offline_only is not True:
            raise OfflineExecutionAuditRecordValidationError("offline_only must be true.")
        if self.historical_research_only is not True:
            raise OfflineExecutionAuditRecordValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineExecutionAuditRecordValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineExecutionAuditRecordValidationError("paper_promotion_eligible must be false.")
        if self.non_operational_declaration != OFFLINE_EXECUTION_AUDIT_RECORD_NON_OPERATIONAL_DECLARATION:
            raise OfflineExecutionAuditRecordValidationError(
                "non_operational_declaration diverges from the audit record contract."
            )
        if self.execution_attempt_number <= 0:
            raise OfflineExecutionAuditRecordValidationError("execution_attempt_number must be greater than zero.")
        expected_execution_attempt_id = f"{self.execution_id}:{self.execution_attempt_number}"
        if self.execution_attempt_id:
            if self.execution_attempt_id != expected_execution_attempt_id:
                raise OfflineExecutionAuditRecordIntegrityError("execution_attempt_id mismatch.")
        else:
            object.__setattr__(self, "execution_attempt_id", expected_execution_attempt_id)
        provenance = self.metadata.get("provenance")
        if not isinstance(provenance, Mapping):
            raise OfflineExecutionAuditRecordValidationError("metadata.provenance is required.")

        expected_lineage_hash = _hash_payload(provenance)
        if self.lineage_hash != expected_lineage_hash:
            raise OfflineExecutionAuditRecordIntegrityError("lineage_hash mismatch.")

        expected_audit_record_id = _hash_payload(self._audit_record_id_payload())
        if self.audit_record_id:
            if self.audit_record_id != expected_audit_record_id:
                raise OfflineExecutionAuditRecordIntegrityError("audit_record_id mismatch.")
        else:
            object.__setattr__(self, "audit_record_id", expected_audit_record_id)

        expected_audit_record_hash = _hash_payload(self._audit_record_hash_payload())
        if self.audit_record_hash:
            if self.audit_record_hash != expected_audit_record_hash:
                raise OfflineExecutionAuditRecordIntegrityError("audit_record_hash mismatch.")
        else:
            object.__setattr__(self, "audit_record_hash", expected_audit_record_hash)

    def _audit_record_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "lineage_hash": self.lineage_hash,
            "artifact_reference_id": self.artifact_reference_id,
            "experiment_id": self.experiment_id,
            "experiment_contract_hash": self.experiment_contract_hash,
            "execution_id": self.execution_id,
            "execution_attempt_number": self.execution_attempt_number,
            "execution_attempt_id": self.execution_attempt_id,
            "execution_plan_hash": self.execution_plan_hash,
            "evidence_hash": self.evidence_hash,
            "authorization_hash": self.authorization_hash,
            "envelope_hash": self.envelope_hash,
            "neutral_execution_id": self.neutral_execution_id,
            "result_hash": self.result_hash,
            "offline_only": self.offline_only,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
        }

    def _audit_record_hash_payload(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "audit_record_id": self.audit_record_id,
            "lineage_hash": self.lineage_hash,
            "artifact_reference_id": self.artifact_reference_id,
            "experiment_id": self.experiment_id,
            "experiment_contract_hash": self.experiment_contract_hash,
            "execution_id": self.execution_id,
            "execution_attempt_number": self.execution_attempt_number,
            "execution_attempt_id": self.execution_attempt_id,
            "execution_plan_hash": self.execution_plan_hash,
            "evidence_hash": self.evidence_hash,
            "authorization_hash": self.authorization_hash,
            "envelope_hash": self.envelope_hash,
            "neutral_execution_id": self.neutral_execution_id,
            "result_hash": self.result_hash,
            "metadata": _thaw_read_only_value(self.metadata),
            "offline_only": self.offline_only,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
        }
        return payload

    def canonical_payload(self, *, include_audit_record_hash: bool = True) -> dict[str, Any]:
        payload = self._audit_record_hash_payload()
        payload["created_at_utc"] = _utc_iso(self.created_at_utc)
        if include_audit_record_hash:
            payload["audit_record_hash"] = self.audit_record_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(_thaw_read_only_value(self.canonical_payload(include_audit_record_hash=True)))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfflineExecutionAuditRecord":
        if not isinstance(data, Mapping):
            raise OfflineExecutionAuditRecordValidationError("offline execution audit record must be a mapping.")
        mapping = dict(data)
        allowed = {
            "schema_version",
            "audit_record_id",
            "audit_record_hash",
            "lineage_hash",
            "artifact_reference_id",
            "experiment_id",
            "experiment_contract_hash",
            "execution_id",
            "execution_attempt_number",
            "execution_attempt_id",
            "execution_plan_hash",
            "evidence_hash",
            "authorization_hash",
            "envelope_hash",
            "neutral_execution_id",
            "result_hash",
            "created_at_utc",
            "metadata",
            "offline_only",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "non_operational_declaration",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise OfflineExecutionAuditRecordValidationError(
                f"unexpected offline execution audit record fields: {', '.join(extra)}."
            )
        try:
            return cls(
                schema_version=mapping.get("schema_version", OFFLINE_EXECUTION_AUDIT_RECORD_SCHEMA_VERSION),
                audit_record_id=mapping.get("audit_record_id", ""),
                audit_record_hash=mapping.get("audit_record_hash", ""),
                lineage_hash=mapping["lineage_hash"],
                artifact_reference_id=mapping["artifact_reference_id"],
                experiment_id=mapping["experiment_id"],
                experiment_contract_hash=mapping["experiment_contract_hash"],
                execution_id=mapping["execution_id"],
                execution_attempt_number=mapping["execution_attempt_number"],
                execution_attempt_id=mapping["execution_attempt_id"],
                execution_plan_hash=mapping["execution_plan_hash"],
                evidence_hash=mapping["evidence_hash"],
                authorization_hash=mapping["authorization_hash"],
                envelope_hash=mapping["envelope_hash"],
                neutral_execution_id=mapping["neutral_execution_id"],
                result_hash=mapping["result_hash"],
                created_at_utc=mapping.get("created_at_utc", datetime.now(timezone.utc)),
                metadata=mapping.get("metadata", {}),
                offline_only=mapping.get("offline_only", True),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                non_operational_declaration=mapping.get(
                    "non_operational_declaration",
                    OFFLINE_EXECUTION_AUDIT_RECORD_NON_OPERATIONAL_DECLARATION,
                ),
            )
        except KeyError as exc:
            raise OfflineExecutionAuditRecordValidationError("offline execution audit record is incomplete.") from exc


def build_offline_execution_audit_record(
    *,
    artifact_reference: phase38_backtest.OkxOfflineResearchArtifactReference,
    experiment_contract: phase40_contract.OfflineResearchExperimentContract,
    experiment_registry: phase41_registry.OfflineResearchExperimentRegistry,
    execution_registry: phase42_registry.OfflineResearchExperimentExecutionRegistry,
    execution_plan: phase43_plan.OfflineResearchExperimentExecutionPlan,
    evidence: phase44_fixture.CanonicalOfflineResearchEvidenceVerification,
    authorization: phase45_auth.OfflineResearchExecutionAuthorization,
    envelope: phase46_envelope.OfflineResearchExecutionEnvelope,
    result: phase47_executor.OfflineResearchNeutralExecutionResult,
    created_at_utc: datetime | str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> OfflineExecutionAuditRecord:
    provenance = _validate_chain(
        artifact_reference=artifact_reference,
        experiment_contract=experiment_contract,
        experiment_registry=experiment_registry,
        execution_registry=execution_registry,
        execution_plan=execution_plan,
        evidence=evidence,
        authorization=authorization,
        envelope=envelope,
        result=result,
    )
    user_metadata = _freeze_read_only_value(dict(metadata or {}))
    combined_metadata = {
        "provenance": provenance,
        "user_metadata": user_metadata,
    }
    execution_record = execution_registry.registration_by_execution_hash(execution_plan.execution_hash)
    execution_attempt_id = f"{execution_record.execution_id}:{execution_record.attempt_number}"
    if created_at_utc is None:
        created_at = datetime.now(timezone.utc)
    else:
        created_at = _require_utc_datetime(created_at_utc, "created_at_utc")

    return OfflineExecutionAuditRecord(
        artifact_reference_id=artifact_reference.registry_report.artifact_id,
        experiment_id=experiment_contract.experiment_id,
        experiment_contract_hash=experiment_contract.contract_hash,
        execution_id=execution_record.execution_id,
        execution_attempt_number=execution_record.attempt_number,
        execution_attempt_id=execution_attempt_id,
        execution_plan_hash=execution_plan.plan_hash,
        evidence_hash=_hash_payload(_evidence_snapshot(evidence)),
        authorization_hash=authorization.authorization_hash,
        envelope_hash=envelope.envelope_hash,
        neutral_execution_id=result.neutral_execution_id,
        result_hash=result.result_hash,
        created_at_utc=created_at,
        metadata=combined_metadata,
        lineage_hash=_hash_payload(provenance),
    )


def verify_offline_execution_audit_record(
    record: OfflineExecutionAuditRecord,
) -> OfflineExecutionAuditRecord:
    if not isinstance(record, OfflineExecutionAuditRecord):
        raise OfflineExecutionAuditRecordValidationError("offline execution audit record is required.")
    provenance = record.metadata.get("provenance")
    if not isinstance(provenance, Mapping):
        raise OfflineExecutionAuditRecordValidationError("metadata.provenance is required.")

    expected_lineage_hash = _hash_payload(provenance)
    if record.lineage_hash != expected_lineage_hash:
        raise OfflineExecutionAuditRecordIntegrityError("lineage_hash mismatch.")
    expected_audit_record_id = _hash_payload(record._audit_record_id_payload())
    if record.audit_record_id != expected_audit_record_id:
        raise OfflineExecutionAuditRecordIntegrityError("audit_record_id mismatch.")
    expected_audit_record_hash = _hash_payload(record._audit_record_hash_payload())
    if record.audit_record_hash != expected_audit_record_hash:
        raise OfflineExecutionAuditRecordIntegrityError("audit_record_hash mismatch.")
    return record


def load_offline_execution_audit_record(
    *,
    record_file: str | Path,
    root_directory: str | Path | None = None,
) -> OfflineExecutionAuditRecord:
    _, path = _rooted_record_path(record_file, root_directory=root_directory, field_name="record_file")
    payload = _load_json(path)
    if not isinstance(payload, Mapping):
        raise OfflineExecutionAuditRecordValidationError("offline execution audit record must be a JSON object.")
    record = OfflineExecutionAuditRecord.from_dict(payload)
    if _canonical_json(record.as_dict()) != _canonical_json(payload):
        raise OfflineExecutionAuditRecordIntegrityError("offline execution audit record payload mismatch.")
    return verify_offline_execution_audit_record(record)


def save_offline_execution_audit_record(
    *,
    record_file: str | Path,
    record: OfflineExecutionAuditRecord,
    root_directory: str | Path | None = None,
) -> OfflineExecutionAuditRecord:
    _, path = _rooted_record_path(record_file, root_directory=root_directory, field_name="record_file")
    verified = verify_offline_execution_audit_record(record)
    if path.exists():
        existing = load_offline_execution_audit_record(record_file=record_file, root_directory=root_directory)
        if existing.as_dict() == verified.as_dict():
            return existing
        if existing.audit_record_id == verified.audit_record_id:
            raise OfflineExecutionAuditRecordConflictError("audit_record_id already exists and differs.")
        raise OfflineExecutionAuditRecordConflictError("offline execution audit record already exists and differs.")
    _write_json_atomic(path, verified.as_dict())
    return verified


__all__ = [
    "OFFLINE_EXECUTION_AUDIT_RECORD_NON_OPERATIONAL_DECLARATION",
    "OFFLINE_EXECUTION_AUDIT_RECORD_SCHEMA_VERSION",
    "OFFLINE_EXECUTION_AUDIT_RECORD_VERSION",
    "OfflineExecutionAuditRecord",
    "OfflineExecutionAuditRecordConflictError",
    "OfflineExecutionAuditRecordError",
    "OfflineExecutionAuditRecordIntegrityError",
    "OfflineExecutionAuditRecordPersistenceError",
    "OfflineExecutionAuditRecordValidationError",
    "build_offline_execution_audit_record",
    "load_offline_execution_audit_record",
    "save_offline_execution_audit_record",
    "verify_offline_execution_audit_record",
]
