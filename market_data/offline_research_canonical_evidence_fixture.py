from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any, Iterator

from domain import Candle, DataSource
from domain.serialization import serialize_value

from . import okx_historical as okx
from . import offline_research_backtest as backtest
from . import offline_research_experiment_contract as phase40_contract
from . import offline_research_experiment_execution_plan as phase43_plan
from . import offline_research_experiment_execution_registry as phase42_registry
from . import offline_research_experiment_registry as phase41_registry
from . import research_artifact_registry as artifact_registry
from . import research_artifact_registry_verification as artifact_verification
from .offline_research_experiment_authorization import authorize_offline_research_experiment
from .offline_research_strategy_compatibility import (
    OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION,
    OfflineResearchStrategyCompatibilityContract,
    evaluate_offline_research_strategy_compatibility,
)
from strategies.baseline_a_okx_btc_usdt_research import build_baseline_a_okx_btc_usdt_research_contract

FIXTURE_VERSION = "phase44_canonical_offline_evidence_v1"
FIXTURE_SPEC_FILENAME = "canonical_fixture_spec.json"
EXPECTED_HASHES_FILENAME = "expected_hashes.json"
CANONICAL_ARTIFACT_ROOT_REL = Path("phase19c-okx-20260727T000000Z") / okx.OKX_HISTORICAL_ARTIFACT_DIRNAME
CANONICAL_REGISTRY_ROOT_REL = Path("phase20a-okx-research-artifact-registry")
CANONICAL_CONTRACT_FILE_REL = Path("phase40") / "offline_research_experiment_contract.json"
CANONICAL_EXPERIMENT_REGISTRY_FILE_REL = Path("phase41") / "offline_research_experiment_registry.json"
CANONICAL_EXECUTION_REGISTRY_FILE_REL = Path("phase42") / "offline_research_experiment_execution_registry.json"
CANONICAL_EXECUTION_PLAN_REGISTRY_FILE_REL = Path("phase43") / "offline_research_experiment_execution_plan_registry.json"
CANONICAL_ARTIFACT_REGISTRY_FILENAME = "okx-research-artifact-registry.json"
CANONICAL_DATASET_START_UTC = okx.OKX_HISTORICAL_REQUESTED_START_INCLUSIVE_UTC
CANONICAL_DATASET_END_EXCLUSIVE_UTC = okx.OKX_HISTORICAL_REQUESTED_END_EXCLUSIVE_UTC
CANONICAL_DATASET_CANDLE_COUNT = okx.OKX_HISTORICAL_EXPECTED_CANDLE_COUNT
CANONICAL_PRICE_BASE = Decimal("50000")
CANONICAL_PRICE_STEP = Decimal("1")
CANONICAL_CLOSE_DELTA = Decimal("0.5")
CANONICAL_HIGH_DELTA = Decimal("1.0")
CANONICAL_LOW_DELTA = Decimal("1.0")
CANONICAL_VOLUME_BASE = Decimal("1000")
CANONICAL_VOLUME_STEP = Decimal("1")
CANONICAL_REGISTERED_AT_UTC = datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc)
CANONICAL_EXPERIMENT_CREATED_AT_UTC = datetime(2026, 7, 31, 12, 0, 0, 123456, tzinfo=timezone.utc)
CANONICAL_EXPERIMENT_REGISTERED_AT_UTC = datetime(2026, 7, 31, 12, 0, 1, 654321, tzinfo=timezone.utc)
CANONICAL_EXECUTION_CREATED_AT_UTC = datetime(2026, 7, 31, 12, 5, 0, 111111, tzinfo=timezone.utc)
CANONICAL_PLAN_CREATED_AT_UTC = datetime(2026, 7, 31, 12, 10, 0, 222222, tzinfo=timezone.utc)
CANONICAL_REGISTRY_VERIFIED_AT_UTC = datetime(2026, 7, 27, 16, 31, 32, tzinfo=timezone.utc)
CANONICAL_SOURCE_COMMIT_SHA = "c5843ac613973cc55052fadeb17d524a0dd30d30"
CANONICAL_SOURCE_BRANCH = "phase-44-canonical-offline-evidence-fixtures"
CANONICAL_STRATEGY_EXPERIMENT_ID = "synthetic_offline_canonical_experiment"
CANONICAL_STRATEGY_EXPERIMENT_VERSION = "phase44_canonical_experiment_v1"
CANONICAL_EXECUTION_REASON = "offline preparation"
CANONICAL_PLAN_CONTEXT = {
    "metadata": {
        "labels": {"offline", "research"},
        "nested": {"flags": {"alpha", "beta"}},
    },
    "notes": ["offline", "prepared"],
}
CANONICAL_EXECUTION_CONTEXT = {
    "channels": {"primary", "secondary"},
    "nested": {"flags": {"offline", "research"}},
    "notes": ["offline", "audit"],
}
FIXTURE_SOURCE_ARTIFACT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "offline_research_phase44"
    / CANONICAL_ARTIFACT_ROOT_REL
)


@contextmanager
def _pushd(path: Path) -> Iterator[None]:
    import os

    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: Any) -> None:
    canonical = _canonical_json(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") == canonical:
            return
        raise FileExistsError(f"{path.name} already exists and differs.")
    tmp_path = path.with_name(f".{path.name}.{Path.cwd().name}.{id(payload)}.tmp")
    try:
        tmp_path.write_text(canonical, encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _registry_report_payload() -> dict[str, Any]:
    return {
        "schema_version": artifact_registry.RESEARCH_ARTIFACT_REGISTRY_SCHEMA_VERSION,
        "provider_name": artifact_registry.OKX_RESEARCH_ARTIFACT_PROVIDER_NAME,
        "market_type": artifact_registry.OKX_RESEARCH_ARTIFACT_MARKET_TYPE,
        "instrument": artifact_registry.OKX_RESEARCH_ARTIFACT_INSTRUMENT,
        "symbol": artifact_registry.OKX_RESEARCH_ARTIFACT_SYMBOL,
        "interval": artifact_registry.OKX_RESEARCH_ARTIFACT_INTERVAL,
        "requested_start_inclusive_utc": artifact_registry.OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC.isoformat().replace("+00:00", "Z"),
        "requested_end_exclusive_utc": artifact_registry.OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC.isoformat().replace("+00:00", "Z"),
        "expected_candle_count": artifact_registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT,
        "audited_candle_count": artifact_registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT,
        "audited_first_candle_open_utc": artifact_registry.OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC.isoformat().replace("+00:00", "Z"),
        "audited_first_candle_close_utc": (
            artifact_registry.OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC + timedelta(hours=1) - timedelta(milliseconds=1)
        ).isoformat().replace("+00:00", "Z"),
        "audited_last_candle_open_utc": (
            artifact_registry.OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC - timedelta(hours=1)
        ).isoformat().replace("+00:00", "Z"),
        "audited_last_candle_close_utc": (
            artifact_registry.OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC - timedelta(milliseconds=1)
        ).isoformat().replace("+00:00", "Z"),
        "audited_gap_count": artifact_registry.OKX_RESEARCH_ARTIFACT_AUDITED_GAP_COUNT,
        "audited_duplicate_count": artifact_registry.OKX_RESEARCH_ARTIFACT_AUDITED_DUPLICATE_COUNT,
        "audited_confirm_required_value": artifact_registry.OKX_RESEARCH_ARTIFACT_AUDITED_CONFIRM_REQUIRED_VALUE,
        "dataset_sha256": artifact_registry.OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256,
        "manifest_sha256": artifact_registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256,
        "manifest_hash": artifact_registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH,
        "audit_status": artifact_registry.OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED,
        "external_artifact_ref": CANONICAL_ARTIFACT_ROOT_REL.as_posix(),
        "historical_research_only": True,
        "operational_evidence": False,
        "paper_promotion_eligible": False,
        "non_operational_declaration": artifact_registry.OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION,
    }


def _build_strategy_contract():
    verification_report = artifact_verification.ResearchArtifactRegistryVerificationReport(
        registry_file=Path("synthetic/okx-research-artifact-registry.json"),
        verified_at_utc=datetime(2026, 7, 27, 16, 31, 32, tzinfo=timezone.utc),
        approved=True,
        artifact_id=_hash_payload(_registry_report_payload()),
        provider_name=artifact_registry.OKX_RESEARCH_ARTIFACT_PROVIDER_NAME,
        market_type=artifact_registry.OKX_RESEARCH_ARTIFACT_MARKET_TYPE,
        instrument=artifact_registry.OKX_RESEARCH_ARTIFACT_INSTRUMENT,
        symbol=artifact_registry.OKX_RESEARCH_ARTIFACT_SYMBOL,
        interval=artifact_registry.OKX_RESEARCH_ARTIFACT_INTERVAL,
        requested_start_inclusive_utc=artifact_registry.OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC,
        requested_end_exclusive_utc=artifact_registry.OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC,
        expected_candle_count=artifact_registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT,
        audited_candle_count=artifact_registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT,
        dataset_sha256=artifact_registry.OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256,
        manifest_sha256=artifact_registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256,
        manifest_hash=artifact_registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH,
        audit_status=artifact_registry.OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED,
        external_artifact_ref=CANONICAL_ARTIFACT_ROOT_REL.as_posix(),
        external_artifact_ref_is_opaque=True,
        external_artifact_ref_is_local=True,
        historical_research_only=True,
        operational_evidence=False,
        paper_promotion_eligible=False,
        non_operational_declaration=artifact_registry.OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION,
        verification_hash="",
    )
    authorization = authorize_offline_research_experiment(
        verification_report,
        issued_at_utc=datetime(2026, 7, 27, 16, 31, 33, tzinfo=timezone.utc),
    )
    compatibility_contract = OfflineResearchStrategyCompatibilityContract(
        strategy_id="synthetic_okx_compatibility",
        strategy_version="phase44_compatibility_v1",
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
        historical_research_only=True,
        operational_evidence=False,
        paper_promotion_eligible=False,
        allowed_use_cases=authorization.allowed_use_cases,
        prohibited_use_cases=authorization.prohibited_use_cases,
        non_operational_declaration=OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION,
    )
    decision = evaluate_offline_research_strategy_compatibility(
        authorization,
        compatibility_contract,
        decided_at_utc=datetime(2026, 7, 27, 16, 31, 34, tzinfo=timezone.utc),
    )
    return build_baseline_a_okx_btc_usdt_research_contract(authorization, decision)

def _canonical_registry_report(
    *,
    registry_file: Path,
    registry_entry: artifact_registry.ResearchArtifactRegistryEntry,
) -> artifact_verification.ResearchArtifactRegistryVerificationReport:
    return artifact_verification.ResearchArtifactRegistryVerificationReport(
        registry_file=registry_file,
        verified_at_utc=CANONICAL_REGISTRY_VERIFIED_AT_UTC,
        approved=True,
        artifact_id=registry_entry.artifact_id,
        provider_name=registry_entry.provider_name,
        market_type=registry_entry.market_type,
        instrument=registry_entry.instrument,
        symbol=registry_entry.symbol,
        interval=registry_entry.interval,
        requested_start_inclusive_utc=registry_entry.requested_start_inclusive_utc,
        requested_end_exclusive_utc=registry_entry.requested_end_exclusive_utc,
        expected_candle_count=registry_entry.expected_candle_count,
        audited_candle_count=registry_entry.audited_candle_count,
        dataset_sha256=registry_entry.dataset_sha256,
        manifest_sha256=registry_entry.manifest_sha256,
        manifest_hash=registry_entry.manifest_hash,
        audit_status=registry_entry.audit_status,
        external_artifact_ref=registry_entry.external_artifact_ref,
        external_artifact_ref_is_opaque=True,
        external_artifact_ref_is_local=True,
        historical_research_only=registry_entry.historical_research_only,
        operational_evidence=registry_entry.operational_evidence,
        paper_promotion_eligible=registry_entry.paper_promotion_eligible,
        non_operational_declaration=registry_entry.non_operational_declaration,
        verification_hash="",
    )


def _fixture_root(target_directory: str | Path) -> Path:
    root = Path(target_directory)
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _fixture_paths(root: Path) -> dict[str, Path]:
    artifact_root = root / CANONICAL_ARTIFACT_ROOT_REL
    registry_root = root / CANONICAL_REGISTRY_ROOT_REL
    return {
        "dataset_file": artifact_root / okx.OKX_HISTORICAL_DATASET_CANDLES_FILENAME,
        "manifest_file": artifact_root / okx.OKX_HISTORICAL_MANIFEST_FILENAME,
        "artifact_registry_file": registry_root / CANONICAL_ARTIFACT_REGISTRY_FILENAME,
        "experiment_contract_file": root / CANONICAL_CONTRACT_FILE_REL,
        "experiment_registry_file": root / CANONICAL_EXPERIMENT_REGISTRY_FILE_REL,
        "execution_registry_file": root / CANONICAL_EXECUTION_REGISTRY_FILE_REL,
        "execution_plan_registry_file": root / CANONICAL_EXECUTION_PLAN_REGISTRY_FILE_REL,
        "expected_hashes_file": root / EXPECTED_HASHES_FILENAME,
        "spec_file": root / FIXTURE_SPEC_FILENAME,
    }


def _build_execution_registration(
    *,
    experiment_registration: phase41_registry.OfflineResearchExperimentRegistryRecord,
    attempt_number: int,
    previous_execution_id: str | None = None,
    previous_execution_hash: str | None = None,
) -> phase42_registry.OfflineResearchExperimentExecutionRegistration:
    return phase42_registry.build_offline_research_experiment_execution_registration(
        experiment_registration=experiment_registration,
        attempt_number=attempt_number,
        previous_execution_id=previous_execution_id,
        previous_execution_hash=previous_execution_hash,
        created_at_utc=CANONICAL_EXECUTION_CREATED_AT_UTC,
        source_commit_sha=CANONICAL_SOURCE_COMMIT_SHA,
        source_branch=CANONICAL_SOURCE_BRANCH,
        execution_status="REGISTERED",
        execution_reason=CANONICAL_EXECUTION_REASON,
        execution_context=CANONICAL_EXECUTION_CONTEXT,
        offline_only=True,
        historical_research_only=True,
        operational_evidence=False,
        paper_promotion_eligible=False,
    )


def _build_plan(
    execution_record: phase42_registry.OfflineResearchExperimentExecutionRegistration,
    *,
    plan_id: str,
    plan_number: int,
    previous_plan: phase43_plan.OfflineResearchExperimentExecutionPlan | None = None,
) -> phase43_plan.OfflineResearchExperimentExecutionPlan:
    return phase43_plan.build_offline_research_experiment_execution_plan(
        execution_registration=execution_record,
        plan_id=plan_id,
        plan_number=plan_number,
        previous_plan=previous_plan,
        plan_context=CANONICAL_PLAN_CONTEXT,
        created_at_utc=CANONICAL_PLAN_CREATED_AT_UTC,
        source_commit_sha=CANONICAL_SOURCE_COMMIT_SHA,
        source_branch=CANONICAL_SOURCE_BRANCH,
        allow_replay=False,
        allow_backtest=False,
        allow_walk_forward=False,
        allow_performance_evaluation=False,
        allow_ranking=False,
        allow_paper_trading=False,
        allow_live_trading=False,
        allow_exchange_connectivity=False,
        allow_order_submission=False,
        offline_only=True,
        historical_research_only=True,
        operational_evidence=False,
        paper_promotion_eligible=False,
    )


@dataclass(frozen=True, slots=True)
class CanonicalOfflineResearchEvidenceFixture:
    fixture_version: str
    fixture_directory: Path
    dataset_file: Path
    manifest_file: Path
    artifact_registry_file: Path
    experiment_contract_file: Path
    experiment_registry_file: Path
    execution_registry_file: Path
    execution_plan_registry_file: Path
    expected_hashes_file: Path
    dataset_hash: str
    manifest_hash: str
    artifact_registry_hash: str
    artifact_registry_verification_hash: str
    artifact_reference_hash: str
    experiment_contract_hash: str
    experiment_registration_hash: str
    experiment_registry_hash: str
    execution_hash: str
    execution_registry_hash: str
    plan_hash: str
    plan_registry_hash: str
    synthetic: bool = True
    test_only: bool = True
    offline_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False


@dataclass(frozen=True, slots=True)
class CanonicalOfflineResearchEvidenceVerification:
    fixture: CanonicalOfflineResearchEvidenceFixture
    dataset: okx.OkxHistoricalDataset
    registry_report: artifact_verification.ResearchArtifactRegistryVerificationReport
    artifact_reference: backtest.OkxOfflineResearchArtifactReference
    artifact_reference_hash: str
    experiment_contract: phase40_contract.OfflineResearchExperimentContract
    experiment_registry: phase41_registry.OfflineResearchExperimentRegistry
    execution_registry: phase42_registry.OfflineResearchExperimentExecutionRegistry
    execution_plan_registry: phase43_plan.OfflineResearchExperimentExecutionPlanRegistry
    expected_hashes: dict[str, Any]


def build_canonical_offline_research_evidence_fixture(
    target_directory: str | Path,
) -> CanonicalOfflineResearchEvidenceFixture:
    root = _fixture_root(target_directory)
    paths = _fixture_paths(root)

    if not FIXTURE_SOURCE_ARTIFACT_ROOT.exists():
        raise FileNotFoundError("canonical offline evidence source fixture is missing.")
    source_dataset_file = FIXTURE_SOURCE_ARTIFACT_ROOT / okx.OKX_HISTORICAL_DATASET_CANDLES_FILENAME
    source_manifest_file = FIXTURE_SOURCE_ARTIFACT_ROOT / okx.OKX_HISTORICAL_MANIFEST_FILENAME
    paths["dataset_file"].parent.mkdir(parents=True, exist_ok=True)
    paths["manifest_file"].parent.mkdir(parents=True, exist_ok=True)
    paths["artifact_registry_file"].parent.mkdir(parents=True, exist_ok=True)
    paths["experiment_contract_file"].parent.mkdir(parents=True, exist_ok=True)
    paths["experiment_registry_file"].parent.mkdir(parents=True, exist_ok=True)
    paths["execution_registry_file"].parent.mkdir(parents=True, exist_ok=True)
    paths["execution_plan_registry_file"].parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_dataset_file, paths["dataset_file"])
    shutil.copy2(source_manifest_file, paths["manifest_file"])
    dataset = okx.load_okx_historical_dataset(dataset_file=paths["dataset_file"], manifest_file=paths["manifest_file"])

    registry_entry = artifact_registry.ResearchArtifactRegistryEntry(
        registered_at_utc=CANONICAL_REGISTERED_AT_UTC,
        external_artifact_ref=CANONICAL_ARTIFACT_ROOT_REL.as_posix(),
        dataset_sha256=dataset.manifest.dataset_hash,
        manifest_sha256=sha256(paths["manifest_file"].read_bytes()).hexdigest(),
        manifest_hash=dataset.manifest.manifest_hash,
    )
    artifact_registry.save_research_artifact_registry(paths["artifact_registry_file"], registry_entry)

    with _pushd(root):
        artifact_verification.verify_okx_research_artifact_registry(
            paths["artifact_registry_file"].relative_to(root)
        )
        dataset_report = okx.verify_okx_historical_dataset(
            dataset_file=paths["dataset_file"].relative_to(root),
            manifest_file=paths["manifest_file"].relative_to(root),
        )
    registry_report = _canonical_registry_report(
        registry_file=paths["artifact_registry_file"].relative_to(root),
        registry_entry=registry_entry,
    )

    resolution = backtest.OkxPersistentResearchArtifactResolution(
        registry_file=paths["artifact_registry_file"],
        dataset_file=paths["dataset_file"],
        manifest_file=paths["manifest_file"],
        registry_report=registry_report,
        dataset_report=dict(dataset_report),
    )
    artifact_reference = backtest.resolve_okx_offline_research_artifact_reference(resolution=resolution)

    strategy_contract = _build_strategy_contract()
    experiment_contract = phase40_contract.build_offline_research_experiment_contract(
        artifact_reference=artifact_reference,
        strategy_contract=strategy_contract,
        experiment_id=phase40_contract.OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_ID,
        experiment_version=phase40_contract.OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_VERSION,
        created_at_utc=CANONICAL_EXPERIMENT_CREATED_AT_UTC,
    )
    _write_json_atomic(paths["experiment_contract_file"], experiment_contract.as_dict())

    expected_experiment_registration = phase41_registry._build_registry_record(
        experiment_contract,
        registered_at_utc=CANONICAL_EXPERIMENT_REGISTERED_AT_UTC,
    )
    if paths["experiment_registry_file"].exists():
        experiment_registry_obj = phase41_registry.load_offline_research_experiment_registry(
            paths["experiment_registry_file"]
        )
        experiment_registration = experiment_registry_obj.record_by_experiment_id(
            expected_experiment_registration.experiment_id
        )
        if experiment_registration.as_dict() != expected_experiment_registration.as_dict():
            raise FileExistsError("canonical experiment registry already exists and differs.")
    else:
        experiment_registration = phase41_registry.register_offline_research_experiment(
            registry_file=paths["experiment_registry_file"],
            contract=experiment_contract,
            registered_at_utc=CANONICAL_EXPERIMENT_REGISTERED_AT_UTC,
        )
    experiment_registry_obj = phase41_registry.load_offline_research_experiment_registry(paths["experiment_registry_file"])

    execution_1 = _build_execution_registration(experiment_registration=experiment_registration, attempt_number=1)
    execution_2 = _build_execution_registration(
        experiment_registration=experiment_registration,
        attempt_number=2,
        previous_execution_id=execution_1.execution_id,
        previous_execution_hash=execution_1.execution_hash,
    )
    execution_3 = _build_execution_registration(
        experiment_registration=experiment_registration,
        attempt_number=3,
        previous_execution_id=execution_2.execution_id,
        previous_execution_hash=execution_2.execution_hash,
    )
    execution_registry_obj = phase42_registry.OfflineResearchExperimentExecutionRegistry(
        registry_file=paths["execution_registry_file"],
        created_at_utc=CANONICAL_EXECUTION_CREATED_AT_UTC,
        updated_at_utc=CANONICAL_EXECUTION_CREATED_AT_UTC + timedelta(minutes=1),
        records=(execution_1, execution_2, execution_3),
    )
    phase42_registry.save_offline_research_experiment_execution_registry(
        paths["execution_registry_file"],
        execution_registry_obj,
    )

    plan_1 = _build_plan(execution_1, plan_id="phase44-plan-1", plan_number=1)
    plan_2 = _build_plan(execution_1, plan_id="phase44-plan-2", plan_number=2, previous_plan=plan_1)
    plan_3 = _build_plan(execution_1, plan_id="phase44-plan-3", plan_number=3, previous_plan=plan_2)
    execution_plan_obj = phase43_plan.OfflineResearchExperimentExecutionPlanRegistry(
        registry_file=paths["execution_plan_registry_file"],
        created_at_utc=CANONICAL_PLAN_CREATED_AT_UTC,
        updated_at_utc=CANONICAL_PLAN_CREATED_AT_UTC + timedelta(minutes=1),
        plans=(plan_1, plan_2, plan_3),
    )
    phase43_plan.save_offline_research_experiment_execution_plan_registry(
        paths["execution_plan_registry_file"],
        execution_plan_obj,
    )

    fixture = CanonicalOfflineResearchEvidenceFixture(
        fixture_version=FIXTURE_VERSION,
        fixture_directory=root,
        dataset_file=paths["dataset_file"],
        manifest_file=paths["manifest_file"],
        artifact_registry_file=paths["artifact_registry_file"],
        experiment_contract_file=paths["experiment_contract_file"],
        experiment_registry_file=paths["experiment_registry_file"],
        execution_registry_file=paths["execution_registry_file"],
        execution_plan_registry_file=paths["execution_plan_registry_file"],
        expected_hashes_file=paths["expected_hashes_file"],
        dataset_hash=dataset.manifest.dataset_hash,
        manifest_hash=dataset.manifest.manifest_hash,
        artifact_registry_hash=registry_entry.registry_hash,
        artifact_registry_verification_hash=registry_report.verification_hash,
        artifact_reference_hash=_hash_payload(phase40_contract._artifact_reference_payload(artifact_reference)),
        experiment_contract_hash=experiment_contract.contract_hash,
        experiment_registration_hash=experiment_registration.record_hash,
        experiment_registry_hash=experiment_registry_obj.registry_hash,
        execution_hash=execution_1.execution_hash,
        execution_registry_hash=execution_registry_obj.registry_hash,
        plan_hash=plan_1.plan_hash,
        plan_registry_hash=execution_plan_obj.registry_hash,
    )
    expected_hashes = {
        "fixture_version": fixture.fixture_version,
        "dataset_hash": fixture.dataset_hash,
        "manifest_hash": fixture.manifest_hash,
        "artifact_registry_hash": fixture.artifact_registry_hash,
        "artifact_registry_verification_hash": fixture.artifact_registry_verification_hash,
        "artifact_reference_hash": fixture.artifact_reference_hash,
        "experiment_contract_hash": fixture.experiment_contract_hash,
        "experiment_registration_hash": fixture.experiment_registration_hash,
        "experiment_registry_hash": fixture.experiment_registry_hash,
        "execution_hash": fixture.execution_hash,
        "execution_registry_hash": fixture.execution_registry_hash,
        "plan_hash": fixture.plan_hash,
        "plan_registry_hash": fixture.plan_registry_hash,
    }
    _write_json_atomic(paths["expected_hashes_file"], expected_hashes)
    _write_json_atomic(
        paths["spec_file"],
        {
            "fixture_version": FIXTURE_VERSION,
            "synthetic": True,
            "test_only": True,
            "offline_only": True,
            "operational_evidence": False,
            "paper_promotion_eligible": False,
            "dataset_candle_count": CANONICAL_DATASET_CANDLE_COUNT,
            "dataset_start_utc": CANONICAL_DATASET_START_UTC.isoformat().replace("+00:00", "Z"),
            "dataset_end_exclusive_utc": CANONICAL_DATASET_END_EXCLUSIVE_UTC.isoformat().replace("+00:00", "Z"),
            "artifact_root": CANONICAL_ARTIFACT_ROOT_REL.as_posix(),
            "registry_root": CANONICAL_REGISTRY_ROOT_REL.as_posix(),
        },
    )
    return fixture


def verify_canonical_offline_research_evidence_fixture(
    fixture_directory: str | Path,
) -> CanonicalOfflineResearchEvidenceVerification:
    root = _fixture_root(fixture_directory)
    paths = _fixture_paths(root)
    expected_hashes = json.loads(paths["expected_hashes_file"].read_text(encoding="utf-8"))
    if expected_hashes.get("fixture_version") != FIXTURE_VERSION:
        raise ValueError("fixture version mismatch.")

    dataset = okx.load_okx_historical_dataset(dataset_file=paths["dataset_file"], manifest_file=paths["manifest_file"])
    dataset_report = okx.verify_okx_historical_dataset(dataset_file=paths["dataset_file"], manifest_file=paths["manifest_file"])
    artifact_registry_entry = artifact_registry.load_research_artifact_registry(paths["artifact_registry_file"])
    with _pushd(root):
        artifact_verification.verify_okx_research_artifact_registry(
            paths["artifact_registry_file"].relative_to(root)
        )
    registry_report = _canonical_registry_report(
        registry_file=paths["artifact_registry_file"].relative_to(root),
        registry_entry=artifact_registry_entry,
    )
    resolution = backtest.OkxPersistentResearchArtifactResolution(
        registry_file=paths["artifact_registry_file"],
        dataset_file=paths["dataset_file"],
        manifest_file=paths["manifest_file"],
        registry_report=registry_report,
        dataset_report=dict(dataset_report),
    )
    artifact_reference = backtest.resolve_okx_offline_research_artifact_reference(resolution=resolution)

    strategy_contract = _build_strategy_contract()
    rebuilt_contract = phase40_contract.build_offline_research_experiment_contract(
        artifact_reference=artifact_reference,
        strategy_contract=strategy_contract,
        experiment_id=phase40_contract.OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_ID,
        experiment_version=phase40_contract.OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_VERSION,
        created_at_utc=CANONICAL_EXPERIMENT_CREATED_AT_UTC,
    )
    persisted_contract_payload = json.loads(paths["experiment_contract_file"].read_text(encoding="utf-8"))
    if rebuilt_contract.as_dict() != persisted_contract_payload:
        raise ValueError("canonical experiment contract mismatch.")

    experiment_registry_obj = phase41_registry.load_offline_research_experiment_registry(paths["experiment_registry_file"])
    execution_registry_obj = phase42_registry.load_offline_research_experiment_execution_registry(paths["execution_registry_file"])
    execution_plan_obj = phase43_plan.load_offline_research_experiment_execution_plan_registry(
        paths["execution_plan_registry_file"]
    )

    computed_hashes = {
        "fixture_version": FIXTURE_VERSION,
        "dataset_hash": dataset.manifest.dataset_hash,
        "manifest_hash": dataset.manifest.manifest_hash,
        "artifact_registry_hash": artifact_registry_entry.registry_hash,
        "artifact_registry_verification_hash": registry_report.verification_hash,
        "artifact_reference_hash": _hash_payload(phase40_contract._artifact_reference_payload(artifact_reference)),
        "experiment_contract_hash": rebuilt_contract.contract_hash,
        "experiment_registration_hash": experiment_registry_obj.records[0].record_hash,
        "experiment_registry_hash": experiment_registry_obj.registry_hash,
        "execution_hash": execution_registry_obj.records[0].execution_hash,
        "execution_registry_hash": execution_registry_obj.registry_hash,
        "plan_hash": execution_plan_obj.plans[0].plan_hash,
        "plan_registry_hash": execution_plan_obj.registry_hash,
    }
    if computed_hashes != expected_hashes:
        raise ValueError("canonical fixture hashes mismatch.")

    fixture = CanonicalOfflineResearchEvidenceFixture(
        fixture_version=FIXTURE_VERSION,
        fixture_directory=root,
        dataset_file=paths["dataset_file"],
        manifest_file=paths["manifest_file"],
        artifact_registry_file=paths["artifact_registry_file"],
        experiment_contract_file=paths["experiment_contract_file"],
        experiment_registry_file=paths["experiment_registry_file"],
        execution_registry_file=paths["execution_registry_file"],
        execution_plan_registry_file=paths["execution_plan_registry_file"],
        expected_hashes_file=paths["expected_hashes_file"],
        dataset_hash=dataset.manifest.dataset_hash,
        manifest_hash=dataset.manifest.manifest_hash,
        artifact_registry_hash=artifact_registry_entry.registry_hash,
        artifact_registry_verification_hash=registry_report.verification_hash,
        artifact_reference_hash=_hash_payload(phase40_contract._artifact_reference_payload(artifact_reference)),
        experiment_contract_hash=rebuilt_contract.contract_hash,
        experiment_registration_hash=experiment_registry_obj.records[0].record_hash,
        experiment_registry_hash=experiment_registry_obj.registry_hash,
        execution_hash=execution_registry_obj.records[0].execution_hash,
        execution_registry_hash=execution_registry_obj.registry_hash,
        plan_hash=execution_plan_obj.plans[0].plan_hash,
        plan_registry_hash=execution_plan_obj.registry_hash,
    )
    return CanonicalOfflineResearchEvidenceVerification(
        fixture=fixture,
        dataset=dataset,
        registry_report=registry_report,
        artifact_reference=artifact_reference,
        artifact_reference_hash=_hash_payload(phase40_contract._artifact_reference_payload(artifact_reference)),
        experiment_contract=rebuilt_contract,
        experiment_registry=experiment_registry_obj,
        execution_registry=execution_registry_obj,
        execution_plan_registry=execution_plan_obj,
        expected_hashes=expected_hashes,
    )


__all__ = [
    "CANONICAL_ARTIFACT_ROOT_REL",
    "CANONICAL_CONTRACT_FILE_REL",
    "CANONICAL_DATASET_CANDLE_COUNT",
    "CANONICAL_DATASET_END_EXCLUSIVE_UTC",
    "CANONICAL_DATASET_START_UTC",
    "CANONICAL_EXPERIMENT_REGISTRY_FILE_REL",
    "CANONICAL_EXECUTION_PLAN_REGISTRY_FILE_REL",
    "CANONICAL_EXECUTION_REGISTRY_FILE_REL",
    "CANONICAL_REGISTRY_ROOT_REL",
    "EXPECTED_HASHES_FILENAME",
    "FIXTURE_SPEC_FILENAME",
    "FIXTURE_VERSION",
    "CanonicalOfflineResearchEvidenceFixture",
    "CanonicalOfflineResearchEvidenceVerification",
    "build_canonical_offline_research_evidence_fixture",
    "verify_canonical_offline_research_evidence_fixture",
]
