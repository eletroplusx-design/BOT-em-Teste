from __future__ import annotations

import copy
import json
from functools import lru_cache
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

import market_data.offline_research_experiment_authorization as authorization
import market_data.offline_research_backtest as backtest
import market_data.offline_research_experiment_contract as experiment_contract
import market_data.offline_research_experiment_execution_plan as execution_plan
import market_data.offline_research_experiment_execution_registry as execution_registry
import market_data.offline_research_experiment_registry as experiment_registry
import market_data.offline_research_strategy_compatibility as compatibility
import market_data.okx_historical as okx
import market_data.research_artifact_registry as registry
from market_data.research_artifact_registry_verification import verify_okx_research_artifact_registry
import market_data.research_artifact_registry_verification as verification
from domain.serialization import serialize_value
from strategies.baseline_a_okx_btc_usdt_research import build_baseline_a_okx_btc_usdt_research_contract

EXPERIMENT_CREATED_AT_UTC = datetime(2026, 7, 31, 12, 0, 0, 123456, tzinfo=timezone.utc)
EXPERIMENT_REGISTERED_AT_UTC = datetime(2026, 7, 31, 12, 0, 1, 654321, tzinfo=timezone.utc)
EXECUTION_CREATED_AT_UTC = datetime(2026, 7, 31, 12, 5, 0, 111111, tzinfo=timezone.utc)
PLAN_CREATED_AT_UTC = datetime(2026, 7, 31, 12, 10, 0, 222222, tzinfo=timezone.utc)
SOURCE_COMMIT_SHA = "c5843ac613973cc55052fadeb17d524a0dd30d30"
SOURCE_BRANCH = "phase-43-offline-experiment-execution-plan"
ACTUAL_REGISTRY_FILE = (
    Path.home()
    / ".codex"
    / "artifacts"
    / "BOT-em-Teste"
    / "phase20a-okx-research-artifact-registry"
    / "okx-research-artifact-registry.json"
)
ACTUAL_ARTIFACT_DIR = (
    Path.home()
    / ".codex"
    / "artifacts"
    / "BOT-em-Teste"
    / "phase19c-okx-20260727T000000Z"
    / "okx"
)
VIRTUAL_RESEARCH_ARTIFACT_REF = "artifact://okx/phase43/research-only"


@dataclass(frozen=True, slots=True)
class _SyntheticPhase41Registration:
    experiment_id: str
    payload: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return json.loads(
            json.dumps(
                serialize_value(execution_registry._thaw_read_only_value(self.payload)),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )


def _real_phase41_record():
    with tempfile.TemporaryDirectory(prefix="phase43-phase41-") as tmp:
        root = Path(tmp)
        artifact_dir = root / "phase19c-okx-20260727T000000Z" / "okx"
        registry_dir = root / "phase20a-okx-research-artifact-registry"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        registry_dir.mkdir(parents=True, exist_ok=True)

        if not ACTUAL_REGISTRY_FILE.exists() or not ACTUAL_ARTIFACT_DIR.exists():
            pytest.skip("persistent artifact is not available in this environment")

        shutil.copytree(ACTUAL_ARTIFACT_DIR, artifact_dir, dirs_exist_ok=True)
        copied_dataset_file = artifact_dir / okx.OKX_HISTORICAL_DATASET_CANDLES_FILENAME
        copied_manifest_file = artifact_dir / okx.OKX_HISTORICAL_MANIFEST_FILENAME
        loaded = okx.load_okx_historical_dataset(
            dataset_file=copied_dataset_file,
            manifest_file=copied_manifest_file,
        )

        registry_file = registry_dir / "okx-research-artifact-registry.json"
        registry_entry = registry.ResearchArtifactRegistryEntry(
            registered_at_utc=datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc),
            external_artifact_ref=artifact_dir.as_posix(),
            dataset_sha256=loaded.manifest.dataset_hash,
            manifest_sha256=sha256(copied_manifest_file.read_bytes()).hexdigest(),
            manifest_hash=loaded.manifest.manifest_hash,
        )
        registry.save_research_artifact_registry(registry_file, registry_entry)

        registry_loaded = experiment_registry.load_offline_research_experiment_registry(registry_file)
        return registry_loaded.record_by_experiment_id(
            experiment_contract.OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_ID
        )


@lru_cache(maxsize=1)
def _phase41_base_payload() -> dict[str, object]:
    if not ACTUAL_REGISTRY_FILE.exists() or not ACTUAL_ARTIFACT_DIR.exists():
        pytest.skip("persistent artifact is not available in this environment")
    dataset_file = ACTUAL_ARTIFACT_DIR / okx.OKX_HISTORICAL_DATASET_CANDLES_FILENAME
    manifest_file = ACTUAL_ARTIFACT_DIR / okx.OKX_HISTORICAL_MANIFEST_FILENAME
    registry_report_raw = verify_okx_research_artifact_registry(ACTUAL_REGISTRY_FILE)
    registry_report = verification.ResearchArtifactRegistryVerificationReport(
        registry_file=registry_report_raw.registry_file,
        verified_at_utc=EXPERIMENT_REGISTERED_AT_UTC,
        approved=registry_report_raw.approved,
        artifact_id=registry_report_raw.artifact_id,
        provider_name=registry_report_raw.provider_name,
        market_type=registry_report_raw.market_type,
        instrument=registry_report_raw.instrument,
        symbol=registry_report_raw.symbol,
        interval=registry_report_raw.interval,
        requested_start_inclusive_utc=registry_report_raw.requested_start_inclusive_utc,
        requested_end_exclusive_utc=registry_report_raw.requested_end_exclusive_utc,
        expected_candle_count=registry_report_raw.expected_candle_count,
        audited_candle_count=registry_report_raw.audited_candle_count,
        dataset_sha256=registry_report_raw.dataset_sha256,
        manifest_sha256=registry_report_raw.manifest_sha256,
        manifest_hash=registry_report_raw.manifest_hash,
        audit_status=registry_report_raw.audit_status,
        external_artifact_ref=registry_report_raw.external_artifact_ref,
        external_artifact_ref_is_opaque=registry_report_raw.external_artifact_ref_is_opaque,
        external_artifact_ref_is_local=registry_report_raw.external_artifact_ref_is_local,
        historical_research_only=registry_report_raw.historical_research_only,
        operational_evidence=registry_report_raw.operational_evidence,
        paper_promotion_eligible=registry_report_raw.paper_promotion_eligible,
        non_operational_declaration=registry_report_raw.non_operational_declaration,
        verification_hash="",
    )
    dataset_report = okx.verify_okx_historical_dataset(
        dataset_file=dataset_file,
        manifest_file=manifest_file,
    )
    resolution = backtest.OkxPersistentResearchArtifactResolution(
        registry_file=ACTUAL_REGISTRY_FILE,
        dataset_file=dataset_file,
        manifest_file=manifest_file,
        registry_report=registry_report,
        dataset_report=dict(dataset_report),
    )
    artifact_reference = backtest.resolve_okx_offline_research_artifact_reference(resolution=resolution)
    strategy_contract = _baseline_strategy_contract()
    contract = experiment_contract.build_offline_research_experiment_contract(
        artifact_reference=artifact_reference,
        strategy_contract=strategy_contract,
        created_at_utc=EXPERIMENT_CREATED_AT_UTC,
    )
    payload = {
        "schema_version": execution_registry.OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_SCHEMA_VERSION,
        "experiment_id": contract.experiment_id,
        "experiment_version": contract.experiment_version,
        "experiment_fingerprint": contract.contract_hash,
        "registered_at_utc": EXPERIMENT_REGISTERED_AT_UTC,
        "contract_snapshot": contract.as_dict(),
        "artifact_reference_snapshot": {
            "registry_file": ACTUAL_REGISTRY_FILE.as_posix(),
            "dataset_file": dataset_file.as_posix(),
            "manifest_file": manifest_file.as_posix(),
            "registry_report": serialize_value(artifact_reference.registry_report.as_dict()),
            "dataset_report": serialize_value(dict(artifact_reference.dataset_report)),
            "read_only": True,
            "historical_research_only": True,
            "operational_evidence": False,
            "paper_promotion_eligible": False,
            "purpose": "offline_historical_research",
        },
        "historical_research_only": True,
        "operational_evidence": False,
        "paper_promotion_eligible": False,
        "non_operational_declaration": experiment_registry.OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_NON_OPERATIONAL_DECLARATION,
    }
    payload["record_hash"] = sha256(
        json.dumps(
            serialize_value(
                execution_registry._thaw_read_only_value(
                    {key: value for key, value in payload.items() if key != "record_hash"}
                )
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return payload


def _verified_authorization() -> authorization.OfflineResearchExperimentAuthorization:
    registry_entry = registry.ResearchArtifactRegistryEntry(
        registered_at_utc=datetime(2026, 7, 27, 16, 31, 31, tzinfo=timezone.utc),
        external_artifact_ref=VIRTUAL_RESEARCH_ARTIFACT_REF,
        dataset_sha256=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256,
        manifest_sha256=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256,
        manifest_hash=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH,
    )
    report = verification.ResearchArtifactRegistryVerificationReport(
        registry_file=Path("synthetic/okx-research-artifact-registry.json"),
        verified_at_utc=datetime(2026, 7, 27, 16, 31, 32, tzinfo=timezone.utc),
        approved=True,
        artifact_id=registry_entry.artifact_id,
        provider_name=registry.OKX_RESEARCH_ARTIFACT_PROVIDER_NAME,
        market_type=registry.OKX_RESEARCH_ARTIFACT_MARKET_TYPE,
        instrument=registry.OKX_RESEARCH_ARTIFACT_INSTRUMENT,
        symbol=registry.OKX_RESEARCH_ARTIFACT_SYMBOL,
        interval=registry.OKX_RESEARCH_ARTIFACT_INTERVAL,
        requested_start_inclusive_utc=registry.OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC,
        requested_end_exclusive_utc=registry.OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC,
        expected_candle_count=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT,
        audited_candle_count=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT,
        dataset_sha256=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256,
        manifest_sha256=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256,
        manifest_hash=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH,
        audit_status=registry.OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED,
        external_artifact_ref=VIRTUAL_RESEARCH_ARTIFACT_REF,
        external_artifact_ref_is_opaque=True,
        external_artifact_ref_is_local=True,
        historical_research_only=True,
        operational_evidence=False,
        paper_promotion_eligible=False,
        non_operational_declaration=registry.OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION,
        verification_hash="",
    )
    return authorization.authorize_offline_research_experiment(
        report,
        issued_at_utc=datetime(2026, 7, 27, 16, 31, 33, tzinfo=timezone.utc),
    )


def _compatibility_contract(
    auth: authorization.OfflineResearchExperimentAuthorization,
) -> compatibility.OfflineResearchStrategyCompatibilityContract:
    return compatibility.OfflineResearchStrategyCompatibilityContract(
        strategy_id="synthetic_okx_compatibility",
        strategy_version="phase43_compatibility_v1",
        provider_name=auth.provider_name,
        market_type=auth.market_type,
        symbol=auth.instrument,
        canonical_symbol=auth.symbol,
        interval=auth.interval,
        requested_start_inclusive_utc=auth.requested_start_inclusive_utc,
        requested_end_exclusive_utc=auth.requested_end_exclusive_utc,
        expected_candle_count=auth.candle_count,
        required_dataset_sha256=auth.dataset_sha256,
        required_manifest_sha256=auth.manifest_sha256,
        required_manifest_hash=auth.manifest_hash,
        required_verification_hash=auth.verification_result_hash,
        purpose=auth.purpose,
        historical_research_only=auth.historical_research_only,
        operational_evidence=auth.operational_evidence,
        paper_promotion_eligible=auth.paper_promotion_eligible,
        allowed_use_cases=auth.allowed_use_cases,
        prohibited_use_cases=auth.prohibited_use_cases,
    )


def _baseline_strategy_contract():
    auth = _verified_authorization()
    compat = _compatibility_contract(auth)
    decision = compatibility.evaluate_offline_research_strategy_compatibility(
        auth,
        compat,
        decided_at_utc=datetime(2026, 7, 27, 16, 31, 34, tzinfo=timezone.utc),
    )
    return build_baseline_a_okx_btc_usdt_research_contract(auth, decision)


def _synthetic_phase41_registration(
    *,
    experiment_id: str,
    experiment_version: str,
    label: str,
    registered_at_utc: datetime,
) -> _SyntheticPhase41Registration:
    payload = copy.deepcopy(_phase41_base_payload())
    payload["experiment_id"] = experiment_id
    payload["experiment_version"] = experiment_version
    payload["experiment_fingerprint"] = sha256(f"{experiment_id}:{label}".encode("utf-8")).hexdigest()
    payload["registered_at_utc"] = registered_at_utc
    payload["contract_snapshot"]["extra_parameters"] = {
        "labels": frozenset({label, "offline"}),
        "nested": {"gate": frozenset({"a", "b"})},
    }
    payload["record_hash"] = sha256(
        json.dumps(
            serialize_value(
                execution_registry._thaw_read_only_value(
                    {key: value for key, value in payload.items() if key != "record_hash"}
                )
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return _SyntheticPhase41Registration(experiment_id=experiment_id, payload=payload)


def _build_execution(
    *,
    experiment_registration,
    attempt_number: int,
    execution_id: str = "",
    previous_execution_id: str | None = None,
    previous_execution_hash: str | None = None,
    source_commit_sha: str = SOURCE_COMMIT_SHA,
    source_branch: str = SOURCE_BRANCH,
    execution_status: str = "REGISTERED",
    execution_reason: str = "offline preparation",
    created_at_utc: datetime = EXECUTION_CREATED_AT_UTC,
    execution_context: dict[str, object] | None = None,
    offline_only: bool = True,
    historical_research_only: bool = True,
    operational_evidence: bool = False,
    paper_promotion_eligible: bool = False,
):
    return execution_registry.build_offline_research_experiment_execution_registration(
        experiment_registration=experiment_registration,
        execution_id=execution_id,
        attempt_number=attempt_number,
        previous_execution_id=previous_execution_id,
        previous_execution_hash=previous_execution_hash,
        created_at_utc=created_at_utc,
        source_commit_sha=source_commit_sha,
        source_branch=source_branch,
        execution_status=execution_status,
        execution_reason=execution_reason,
        execution_context=execution_context
        or {
            "channels": {"primary", "secondary"},
            "nested": {"flags": {"offline", "research"}},
            "notes": ["offline", "audit"],
        },
        offline_only=offline_only,
        historical_research_only=historical_research_only,
        operational_evidence=operational_evidence,
        paper_promotion_eligible=paper_promotion_eligible,
    )


def _build_execution_chain(
    *,
    experiment_id: str = "synthetic_experiment",
    experiment_version: str = "phase41_synthetic_v1",
    label: str = "alpha",
):
    phase41_registration = _synthetic_phase41_registration(
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        label=label,
        registered_at_utc=EXPERIMENT_REGISTERED_AT_UTC,
    )
    execution_1 = _build_execution(experiment_registration=phase41_registration, attempt_number=1)
    execution_2 = _build_execution(
        experiment_registration=phase41_registration,
        attempt_number=2,
        previous_execution_id=execution_1.execution_id,
        previous_execution_hash=execution_1.execution_hash,
    )
    execution_3 = _build_execution(
        experiment_registration=phase41_registration,
        attempt_number=3,
        previous_execution_id=execution_2.execution_id,
        previous_execution_hash=execution_2.execution_hash,
    )
    return phase41_registration, execution_1, execution_2, execution_3


def _build_plan(
    execution_record,
    *,
    plan_id: str,
    plan_number: int,
    previous_plan=None,
    plan_context=None,
    execution_registry_file: Path | None = None,
    execution_id: str | None = None,
    execution_hash: str | None = None,
    research_mode: str = execution_plan.OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_RESEARCH_MODE,
    created_at_utc: datetime = PLAN_CREATED_AT_UTC,
    source_commit_sha: str = SOURCE_COMMIT_SHA,
    source_branch: str = SOURCE_BRANCH,
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
    preconditions=None,
    abort_conditions=None,
    non_operational_declaration: str = execution_plan.OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_NON_OPERATIONAL_DECLARATION,
):
    kwargs = {
        "plan_id": plan_id,
        "plan_number": plan_number,
        "previous_plan": previous_plan,
        "plan_context": plan_context,
        "research_mode": research_mode,
        "created_at_utc": created_at_utc,
        "source_commit_sha": source_commit_sha,
        "source_branch": source_branch,
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
        "non_operational_declaration": non_operational_declaration,
    }
    if execution_registry_file is not None:
        kwargs["execution_registry_file"] = execution_registry_file
        kwargs["execution_id"] = execution_id
        kwargs["execution_hash"] = execution_hash
    else:
        kwargs["execution_registration"] = execution_record
    return execution_plan.build_offline_research_experiment_execution_plan(**kwargs)


def _build_plan_registry(*plans: execution_plan.OfflineResearchExperimentExecutionPlan, registry_file: Path | None = None):
    return execution_plan.OfflineResearchExperimentExecutionPlanRegistry(
        registry_file=registry_file or Path(),
        created_at_utc=PLAN_CREATED_AT_UTC,
        updated_at_utc=PLAN_CREATED_AT_UTC + timedelta(minutes=1),
        plans=plans,
    )


def _persist_plan_registry(registry_file: Path, plans: tuple[execution_plan.OfflineResearchExperimentExecutionPlan, ...]):
    registry_obj = _build_plan_registry(*plans, registry_file=registry_file)
    execution_plan.save_offline_research_experiment_execution_plan_registry(registry_file, registry_obj)
    return registry_obj


def _persist_execution_registry(registry_file: Path, records: tuple):
    registry_obj = execution_registry.OfflineResearchExperimentExecutionRegistry(
        registry_file=registry_file,
        created_at_utc=EXECUTION_CREATED_AT_UTC,
        updated_at_utc=EXECUTION_CREATED_AT_UTC + timedelta(minutes=1),
        records=records,
    )
    execution_registry.save_offline_research_experiment_execution_registry(registry_file, registry_obj)
    return registry_obj


def _forbidden(*args, **kwargs):
    raise AssertionError("unexpected operational or legacy call")


def test_phase43_builds_first_second_third_plans_and_preserves_chain_and_immutability():
    _, execution_1, execution_2, execution_3 = _build_execution_chain()
    source_context = {
        "metadata": {
            "labels": {"offline", "research"},
            "nested": {"flags": {"alpha", "beta"}},
        },
        "notes": ["offline", "prepared"],
    }
    plan_1 = _build_plan(
        execution_1,
        plan_id="phase43-plan-1",
        plan_number=1,
        plan_context=source_context,
    )
    plan_2 = _build_plan(
        execution_1,
        plan_id="phase43-plan-2",
        plan_number=2,
        previous_plan=plan_1,
    )
    plan_3 = _build_plan(
        execution_1,
        plan_id="phase43-plan-3",
        plan_number=3,
        previous_plan=plan_2,
    )

    assert plan_1.plan_number == 1
    assert plan_2.plan_number == 2
    assert plan_3.plan_number == 3
    assert plan_2.execution_id == plan_1.execution_id
    assert plan_3.execution_id == plan_1.execution_id
    assert plan_2.execution_hash == plan_1.execution_hash
    assert plan_3.execution_hash == plan_1.execution_hash
    assert plan_2.previous_plan_id == plan_1.plan_id
    assert plan_2.previous_plan_hash == plan_1.plan_hash
    assert plan_3.previous_plan_id == plan_2.plan_id
    assert plan_3.previous_plan_hash == plan_2.plan_hash
    assert plan_1.research_mode == execution_plan.OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_RESEARCH_MODE
    assert plan_1.expected_symbol == registry.OKX_RESEARCH_ARTIFACT_INSTRUMENT
    assert plan_1.expected_interval == registry.OKX_RESEARCH_ARTIFACT_INTERVAL
    assert plan_1.expected_provider_name == registry.OKX_RESEARCH_ARTIFACT_PROVIDER_NAME
    assert plan_1.expected_market_type == registry.OKX_RESEARCH_ARTIFACT_MARKET_TYPE
    assert plan_1.warmup_candle_count == 201
    assert plan_1.maximum_candle_count == registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT
    assert plan_1.offline_only is True
    assert plan_1.historical_research_only is True
    assert plan_1.operational_evidence is False
    assert plan_1.paper_promotion_eligible is False
    assert plan_1.plan_context["metadata"]["labels"] == frozenset({"offline", "research"})
    assert plan_1.plan_context["metadata"]["nested"]["flags"] == frozenset({"alpha", "beta"})

    with pytest.raises(AttributeError):
        plan_1.plan_context["metadata"]["labels"].add("mutated")

    source_context["metadata"]["labels"].add("mutated")
    source_context["metadata"]["nested"]["flags"].add("mutated")
    source_context["notes"][0] = "mutated"

    assert plan_1.plan_context["metadata"]["labels"] == frozenset({"offline", "research"})
    assert plan_1.plan_context["metadata"]["nested"]["flags"] == frozenset({"alpha", "beta"})
    assert plan_1.plan_context["notes"][0] == "offline"


def test_phase43_plans_are_independent_for_distinct_attempts():
    _, execution_a_1, execution_a_2, _ = _build_execution_chain(experiment_id="synthetic_experiment_a", label="alpha")
    _, execution_b_1, _, _ = _build_execution_chain(experiment_id="synthetic_experiment_b", label="beta")
    plan_a = _build_plan(execution_a_1, plan_id="phase43-plan-a", plan_number=1)
    plan_b = _build_plan(execution_b_1, plan_id="phase43-plan-b", plan_number=1)
    plan_a_attempt_2 = _build_plan(execution_a_2, plan_id="phase43-plan-a-2", plan_number=1)

    assert plan_a.plan_hash != plan_b.plan_hash
    assert plan_a.plan_hash != plan_a_attempt_2.plan_hash
    assert plan_a.execution_id != plan_b.execution_id


def test_phase43_register_is_idempotent_for_identical_plan(tmp_path):
    _, execution_1, _, _ = _build_execution_chain()
    registry_file = tmp_path / "execution-plan-registry.json"
    plan = execution_plan.register_offline_research_experiment_execution_plan(
        registry_file=registry_file,
        plan_id="phase43-plan-idempotent",
        execution_registration=execution_1,
        plan_number=1,
        created_at_utc=PLAN_CREATED_AT_UTC,
        source_commit_sha=SOURCE_COMMIT_SHA,
        source_branch=SOURCE_BRANCH,
    )
    original_text = registry_file.read_text(encoding="utf-8")
    same_plan = execution_plan.register_offline_research_experiment_execution_plan(
        registry_file=registry_file,
        plan_id="phase43-plan-idempotent",
        execution_registration=execution_1,
        plan_number=1,
        created_at_utc=PLAN_CREATED_AT_UTC,
        source_commit_sha=SOURCE_COMMIT_SHA,
        source_branch=SOURCE_BRANCH,
    )

    assert plan.plan_hash == same_plan.plan_hash
    assert registry_file.read_text(encoding="utf-8") == original_text
    loaded = execution_plan.load_offline_research_experiment_execution_plan_registry(registry_file)
    assert loaded.plan_count == 1
    assert loaded.plans[0].plan_hash == plan.plan_hash


def test_phase43_register_rejects_duplicate_plan_id_with_different_content(tmp_path):
    _, execution_1, execution_2, _ = _build_execution_chain()
    registry_file = tmp_path / "execution-plan-registry.json"
    execution_plan.register_offline_research_experiment_execution_plan(
        registry_file=registry_file,
        plan_id="phase43-plan-duplicate",
        execution_registration=execution_1,
        plan_number=1,
        created_at_utc=PLAN_CREATED_AT_UTC,
        source_commit_sha=SOURCE_COMMIT_SHA,
        source_branch=SOURCE_BRANCH,
    )

    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanConflictError, match="plan_id already registered"):
        execution_plan.register_offline_research_experiment_execution_plan(
            registry_file=registry_file,
            plan_id="phase43-plan-duplicate",
            execution_registration=execution_2,
            plan_number=1,
            created_at_utc=PLAN_CREATED_AT_UTC,
            source_commit_sha=SOURCE_COMMIT_SHA,
            source_branch=SOURCE_BRANCH,
        )


@pytest.mark.parametrize("plan_number", [0, -1, True])
def test_phase43_rejects_invalid_plan_number(plan_number):
    _, execution_1, _, _ = _build_execution_chain()
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match="plan_number"):
        _build_plan(
            execution_1,
            plan_id="phase43-invalid-plan-number",
            plan_number=plan_number,
        )


def test_phase43_rejects_previous_plan_chain_errors():
    _, execution_1, execution_2, execution_3 = _build_execution_chain()
    first_plan = _build_plan(execution_1, plan_id="phase43-chain-1", plan_number=1)
    second_plan = _build_plan(execution_1, plan_id="phase43-chain-2", plan_number=2, previous_plan=first_plan)

    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match="previous plan reference is not allowed for plan_number 1"):
        _build_plan(execution_1, plan_id="phase43-chain-1-bad", plan_number=1, previous_plan=first_plan)

    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match="previous plan reference is required for plan_number greater than 1"):
        _build_plan(execution_1, plan_id="phase43-chain-2-bad", plan_number=2)

    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanIntegrityError, match="previous plan_number mismatch"):
        _build_plan(execution_1, plan_id="phase43-chain-3-bad", plan_number=3, previous_plan=first_plan)

    _, foreign_execution_1, _, _ = _build_execution_chain(experiment_id="synthetic_experiment_b", label="beta")
    foreign_first_plan = _build_plan(foreign_execution_1, plan_id="phase43-chain-foreign", plan_number=1)
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanIntegrityError, match="previous plan execution_id mismatch"):
        _build_plan(execution_1, plan_id="phase43-chain-2-foreign", plan_number=2, previous_plan=foreign_first_plan)

    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match="previous plan reference is not allowed for plan_number 1"):
        _build_plan(execution_1, plan_id="phase43-chain-1-cycle", plan_number=1, previous_plan=second_plan)


def test_phase43_rejects_nonexistent_execution_id_and_hash_lookup(tmp_path):
    _, execution_1, _, _ = _build_execution_chain()
    registry_file = tmp_path / "execution-registry.json"
    _persist_execution_registry(registry_file, (execution_1,))

    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match="execution_id was not found"):
        _build_plan(
            execution_1,
            plan_id="phase43-missing-execution",
            plan_number=1,
            execution_registry_file=registry_file,
            execution_id="not-an-existing-id",
        )

    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanIntegrityError, match="execution_hash mismatch"):
        _build_plan(
            execution_1,
            plan_id="phase43-hash-mismatch",
            plan_number=1,
            execution_registry_file=registry_file,
            execution_id=execution_1.execution_id,
            execution_hash="0" * 64,
        )


def test_phase43_rejects_tampered_execution_registration_snapshot():
    _, execution_1, _, _ = _build_execution_chain()
    snapshot = json.loads(json.dumps(serialize_value(execution_1.as_dict()), ensure_ascii=False, sort_keys=True))
    snapshot["non_operational_declaration"] = "tampered"
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match="execution_registration snapshot is invalid"):
        _build_plan(snapshot, plan_id="phase43-snapshot-tampered", plan_number=1)


def test_phase43_rejects_incomplete_snapshot_and_unsafe_flags():
    _, execution_1, _, _ = _build_execution_chain()
    snapshot = json.loads(json.dumps(serialize_value(execution_1.as_dict()), ensure_ascii=False, sort_keys=True))
    snapshot.pop("experiment_registration_hash")
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match="execution_registration snapshot is invalid"):
        _build_plan(snapshot, plan_id="phase43-snapshot-missing", plan_number=1)

    unsafe_flags = json.loads(json.dumps(serialize_value(execution_1.as_dict()), ensure_ascii=False, sort_keys=True))
    unsafe_flags["operational_evidence"] = True
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match="execution_registration snapshot is invalid"):
        _build_plan(unsafe_flags, plan_id="phase43-snapshot-unsafe", plan_number=1)


@pytest.mark.parametrize(
    "mode",
    [
        "OFFLINE_EXECUTION_PREPARATION",
        "offline_execution_preparation",
    ],
)
def test_phase43_accepts_valid_research_mode(mode):
    _, execution_1, _, _ = _build_execution_chain()
    plan = _build_plan(execution_1, plan_id="phase43-mode-valid", plan_number=1, research_mode=mode)
    assert plan.research_mode == execution_plan.OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_PLAN_RESEARCH_MODE


@pytest.mark.parametrize("mode", ["BACKTEST", "REPLAY", "RUNNING", "PAPER", "LIVE", "QUEUED", "SCHEDULED"])
def test_phase43_rejects_disallowed_research_modes(mode):
    _, execution_1, _, _ = _build_execution_chain()
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match="research_mode is not allowed"):
        _build_plan(execution_1, plan_id="phase43-mode-invalid", plan_number=1, research_mode=mode)


def test_phase43_normalizes_timezone_and_preserves_microseconds():
    _, execution_1, _, _ = _build_execution_chain()
    plan = _build_plan(
        execution_1,
        plan_id="phase43-timezone",
        plan_number=1,
        created_at_utc=datetime(2026, 7, 31, 14, 10, 0, 333444, tzinfo=timezone(timedelta(hours=2))),
    )
    assert plan.created_at_utc == datetime(2026, 7, 31, 12, 10, 0, 333444, tzinfo=timezone.utc)
    assert plan.requested_start_inclusive_utc == registry.OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC
    assert plan.requested_end_exclusive_utc == registry.OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC


@pytest.mark.parametrize(
    ("field_name", "replacement", "expected"),
    [
        ("requested_start_inclusive_utc", datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc) - timedelta(seconds=1), "requested_start_inclusive_utc mismatch"),
        ("requested_end_exclusive_utc", datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc) + timedelta(days=1), "requested_end_exclusive_utc mismatch"),
        ("expected_symbol", "BTCUSDT", "expected_symbol mismatch"),
        ("expected_interval", "4H", "expected_interval mismatch"),
        ("expected_provider_name", "KuCoin", "expected_provider_name mismatch"),
        ("expected_market_type", "futures", "expected_market_type mismatch"),
    ],
)
def test_phase43_rejects_window_and_market_identity_divergence(field_name, replacement, expected):
    _, execution_1, _, _ = _build_execution_chain()
    payload = json.loads(json.dumps(serialize_value(_build_plan(execution_1, plan_id="phase43-valid", plan_number=1).as_dict()), ensure_ascii=False, sort_keys=True))
    payload[field_name] = replacement.isoformat().replace("+00:00", "Z") if isinstance(replacement, datetime) else replacement
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanIntegrityError, match=expected):
        execution_plan.OfflineResearchExperimentExecutionPlan.from_dict(payload)


@pytest.mark.parametrize(
    ("field_name", "replacement", "expected"),
    [
        ("warmup_candle_count", True, "warmup_candle_count"),
        ("warmup_candle_count", -1, "warmup_candle_count cannot be negative"),
        ("maximum_candle_count", 0, "maximum_candle_count must be greater than zero"),
        ("maximum_candle_count", -1, "maximum_candle_count must be greater than zero"),
        ("warmup_candle_count", 999999, "warmup_candle_count must not exceed maximum_candle_count"),
    ],
)
def test_phase43_rejects_warmup_and_candle_limits(field_name, replacement, expected):
    _, execution_1, _, _ = _build_execution_chain()
    payload = json.loads(json.dumps(serialize_value(_build_plan(execution_1, plan_id="phase43-valid", plan_number=1).as_dict()), ensure_ascii=False, sort_keys=True))
    payload[field_name] = replacement
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match=expected):
        execution_plan.OfflineResearchExperimentExecutionPlan.from_dict(payload)


@pytest.mark.parametrize(
    ("field_name", "replacement", "expected"),
    [
        ("allow_replay", True, "allow_replay must be false"),
        ("allow_backtest", True, "allow_backtest must be false"),
        ("allow_walk_forward", True, "allow_walk_forward must be false"),
        ("allow_performance_evaluation", True, "allow_performance_evaluation must be false"),
        ("allow_ranking", True, "allow_ranking must be false"),
        ("allow_paper_trading", True, "allow_paper_trading must be false"),
        ("allow_live_trading", True, "allow_live_trading must be false"),
        ("allow_exchange_connectivity", True, "allow_exchange_connectivity must be false"),
        ("allow_order_submission", True, "allow_order_submission must be false"),
        ("offline_only", False, "offline_only must be true"),
        ("historical_research_only", False, "historical_research_only must be true"),
        ("operational_evidence", True, "operational_evidence must be false"),
        ("paper_promotion_eligible", True, "paper_promotion_eligible must be false"),
    ],
)
def test_phase43_rejects_operational_permissions_and_security_flags(field_name, replacement, expected):
    _, execution_1, _, _ = _build_execution_chain()
    payload = json.loads(json.dumps(serialize_value(_build_plan(execution_1, plan_id="phase43-valid", plan_number=1).as_dict()), ensure_ascii=False, sort_keys=True))
    payload[field_name] = replacement
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match=expected):
        execution_plan.OfflineResearchExperimentExecutionPlan.from_dict(payload)


@pytest.mark.parametrize(
    ("field_name", "replacement", "expected"),
    [
        ("preconditions", ["PHASE_41_EXPERIMENT_REGISTRATION_VALID"], "missing required values"),
        ("preconditions", ["PHASE_41_EXPERIMENT_REGISTRATION_VALID", "PHASE_41_EXPERIMENT_REGISTRATION_VALID"], "duplicates"),
        ("preconditions", ["PHASE_41_EXPERIMENT_REGISTRATION_VALID", "UNEXPECTED"], "unexpected value"),
        ("abort_conditions", ["EXPERIMENT_REGISTRATION_INTEGRITY_FAILURE"], "missing required values"),
        ("abort_conditions", ["EXPERIMENT_REGISTRATION_INTEGRITY_FAILURE", "EXPERIMENT_REGISTRATION_INTEGRITY_FAILURE"], "duplicates"),
        ("abort_conditions", ["EXPERIMENT_REGISTRATION_INTEGRITY_FAILURE", "UNEXPECTED"], "unexpected value"),
    ],
)
def test_phase43_rejects_invalid_preconditions_and_abort_conditions(field_name, replacement, expected):
    _, execution_1, _, _ = _build_execution_chain()
    payload = json.loads(json.dumps(serialize_value(_build_plan(execution_1, plan_id="phase43-valid", plan_number=1).as_dict()), ensure_ascii=False, sort_keys=True))
    payload[field_name] = replacement
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match=expected):
        execution_plan.OfflineResearchExperimentExecutionPlan.from_dict(payload)


def test_phase43_plan_context_is_deeply_immutable_and_source_independent():
    _, execution_1, _, _ = _build_execution_chain()
    source_context = {
        "metadata": {
            "labels": {"offline", "research"},
            "nested": {"flags": {"alpha", "beta"}},
        },
        "notes": ["offline", "prepared"],
    }
    plan = _build_plan(execution_1, plan_id="phase43-context", plan_number=1, plan_context=source_context)

    with pytest.raises(TypeError):
        plan.plan_context["metadata"] = {}
    with pytest.raises(TypeError):
        plan.plan_context["metadata"]["labels"] = frozenset({"mutated"})
    with pytest.raises(TypeError):
        plan.plan_context["notes"][0] = "mutated"

    source_context["metadata"]["labels"].add("mutated")
    source_context["metadata"]["nested"]["flags"].add("mutated")
    source_context["notes"][0] = "mutated"

    assert plan.plan_context["metadata"]["labels"] == frozenset({"offline", "research"})
    assert plan.plan_context["metadata"]["nested"]["flags"] == frozenset({"alpha", "beta"})
    assert plan.plan_context["notes"][0] == "offline"


@pytest.mark.parametrize(
    ("plan_context", "expected"),
    [
        ({"callable": lambda: None}, "callables"),
        ({"bad": object()}, "unsupported value"),
        ({"credentials": {"api_key": "sk-test"}}, "secrets or credentials"),
        ({"token": "secret"}, "secrets or credentials"),
    ],
)
def test_phase43_rejects_bad_plan_context_values(plan_context, expected):
    _, execution_1, _, _ = _build_execution_chain()
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match=expected):
        _build_plan(execution_1, plan_id="phase43-bad-context", plan_number=1, plan_context=plan_context)


def test_phase43_persistence_round_trip_and_reload_stability(tmp_path):
    _, execution_1, _, _ = _build_execution_chain()
    plan_1 = _build_plan(execution_1, plan_id="phase43-persist-1", plan_number=1)
    plan_2 = _build_plan(execution_1, plan_id="phase43-persist-2", plan_number=2, previous_plan=plan_1)
    plan_3 = _build_plan(execution_1, plan_id="phase43-persist-3", plan_number=3, previous_plan=plan_2)
    registry_file = tmp_path / "execution-plan-registry.json"
    _persist_plan_registry(registry_file, (plan_1, plan_2, plan_3))

    loaded_a = execution_plan.load_offline_research_experiment_execution_plan_registry(registry_file)
    loaded_b = execution_plan.load_offline_research_experiment_execution_plan_registry(registry_file)
    verified = execution_plan.verify_offline_research_experiment_execution_plan_registry(registry_file)

    assert loaded_a.as_dict() == loaded_b.as_dict()
    assert loaded_a.registry_hash == loaded_b.registry_hash
    assert loaded_a.plan_count == 3
    assert verified.approved is True
    assert verified.plan_count == 3
    assert verified.plan_ids == (plan_1.plan_id, plan_2.plan_id, plan_3.plan_id)
    assert verified.plan_hashes == (plan_1.plan_hash, plan_2.plan_hash, plan_3.plan_hash)


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda payload: payload.__setitem__("registry_hash", "0" * 64), "registry_hash mismatch"),
        (lambda payload: payload["plans"][0].__setitem__("plan_hash", "1" * 64), "plan_hash mismatch"),
        (lambda payload: payload.__setitem__("non_operational_declaration", "tampered"), "non_operational_declaration diverges"),
        (lambda payload: payload["plans"][0].pop("plan_id"), "incomplete"),
        (lambda payload: payload.__setitem__("unexpected", True), "unexpected"),
    ],
)
def test_phase43_rejects_tampered_registry_file_variants(tmp_path, mutator, expected):
    _, execution_1, _, _ = _build_execution_chain()
    plan_1 = _build_plan(execution_1, plan_id="phase43-registry-1", plan_number=1)
    plan_2 = _build_plan(execution_1, plan_id="phase43-registry-2", plan_number=2, previous_plan=plan_1)
    plan_3 = _build_plan(execution_1, plan_id="phase43-registry-3", plan_number=3, previous_plan=plan_2)
    registry_file = tmp_path / "execution-plan-registry.json"
    _persist_plan_registry(registry_file, (plan_1, plan_2, plan_3))

    payload = json.loads(registry_file.read_text(encoding="utf-8"))
    mutator(payload)
    registry_file.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanError, match=expected):
        execution_plan.load_offline_research_experiment_execution_plan_registry(registry_file)


def test_phase43_rejects_empty_invalid_root_and_non_mapping_items(tmp_path):
    registry_file = tmp_path / "execution-plan-registry.json"
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match="missing"):
        execution_plan.load_offline_research_experiment_execution_plan_registry(registry_file)

    registry_file.write_text("", encoding="utf-8")
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match="empty"):
        execution_plan.load_offline_research_experiment_execution_plan_registry(registry_file)

    registry_file.write_text("{not-json", encoding="utf-8")
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match="invalid JSON"):
        execution_plan.load_offline_research_experiment_execution_plan_registry(registry_file)

    registry_file.write_text("[]", encoding="utf-8")
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match="must be a JSON object"):
        execution_plan.load_offline_research_experiment_execution_plan_registry(registry_file)

    _, execution_1, _, _ = _build_execution_chain()
    plan = _build_plan(execution_1, plan_id="phase43-root", plan_number=1)
    payload = plan.as_dict()
    payload["plans"] = [1]
    registry_file.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError):
        execution_plan.load_offline_research_experiment_execution_plan_registry(registry_file)


def test_phase43_atomic_write_preserves_previous_registry_and_cleans_temp_file(tmp_path, monkeypatch):
    _, execution_1, _, _ = _build_execution_chain()
    plan_1 = _build_plan(execution_1, plan_id="phase43-atomic-1", plan_number=1)
    registry_file = tmp_path / "execution-plan-registry.json"
    _persist_plan_registry(registry_file, (plan_1,))
    original_text = registry_file.read_text(encoding="utf-8")

    def _fail(*args, **kwargs):
        raise OSError("simulated write failure")

    real_exists = execution_plan.Path.exists

    def _exists(path_self):
        if Path(path_self) == registry_file:
            return False
        return real_exists(path_self)

    monkeypatch.setattr(execution_plan.Path, "exists", _exists, raising=True)
    monkeypatch.setattr(execution_plan.os, "replace", _fail, raising=True)
    plan_2 = _build_plan(execution_1, plan_id="phase43-atomic-2", plan_number=2, previous_plan=plan_1)
    with pytest.raises(execution_plan.OfflineResearchExperimentExecutionPlanValidationError, match="failed to write"):
        execution_plan.save_offline_research_experiment_execution_plan_registry(
            registry_file,
            execution_plan.OfflineResearchExperimentExecutionPlanRegistry(
                registry_file=registry_file,
                created_at_utc=PLAN_CREATED_AT_UTC,
                updated_at_utc=PLAN_CREATED_AT_UTC + timedelta(minutes=1),
                plans=(plan_1, plan_2),
            ),
        )
    assert registry_file.read_text(encoding="utf-8") == original_text
    assert not any(path.name.endswith(".tmp") for path in registry_file.parent.iterdir())


def test_phase43_allows_same_plan_number_for_distinct_executions_and_orders_by_execution_then_number(tmp_path):
    _, execution_a_1, _, _ = _build_execution_chain(experiment_id="synthetic_experiment_a", label="alpha")
    _, execution_b_1, _, _ = _build_execution_chain(experiment_id="synthetic_experiment_b", label="beta")
    plan_a_1 = _build_plan(execution_a_1, plan_id="phase43-order-a-1", plan_number=1)
    plan_a_2 = _build_plan(execution_a_1, plan_id="phase43-order-a-2", plan_number=2, previous_plan=plan_a_1)
    plan_b_1 = _build_plan(execution_b_1, plan_id="phase43-order-b-1", plan_number=1)

    registry_file = tmp_path / "execution-plan-registry.json"
    _persist_plan_registry(registry_file, (plan_b_1, plan_a_2, plan_a_1))
    loaded = execution_plan.load_offline_research_experiment_execution_plan_registry(registry_file)

    expected_order = tuple(
        sorted(
            (plan_a_1, plan_a_2, plan_b_1),
            key=lambda plan: (plan.execution_id, plan.plan_number, plan.plan_id, plan.plan_hash),
        )
    )

    assert loaded.plan_count == 3
    assert loaded.plans == expected_order
    assert loaded.plans[0].execution_id == plan_a_1.execution_id
    assert loaded.plans[0].plan_number == 1
    assert loaded.plans[1].execution_id == plan_a_1.execution_id
    assert loaded.plans[1].plan_number == 2
    assert loaded.plans[2].execution_id == plan_b_1.execution_id
    assert loaded.plans[2].plan_number == 1

def test_phase43_registry_lookup_by_id_and_hash_and_no_operational_calls(monkeypatch, tmp_path):
    _, execution_1, _, _ = _build_execution_chain()
    monkeypatch.setattr(backtest, "run_first_offline_okx_backtest_experiment", _forbidden, raising=True)
    monkeypatch.setattr(backtest.LeakFreeBacktestEngine, "run", _forbidden, raising=True)
    plan = _build_plan(execution_1, plan_id="phase43-no-op", plan_number=1)
    registry_file = tmp_path / "phase43-no-op-registry.json"
    _persist_plan_registry(registry_file, (plan,))

    assert execution_plan.get_offline_research_experiment_execution_plan_by_id(registry_file, plan.plan_id).plan_hash == plan.plan_hash
    assert execution_plan.get_offline_research_experiment_execution_plan_by_hash(registry_file, plan.plan_hash).plan_id == plan.plan_id


def test_phase43_hash_is_deterministic_across_processes(tmp_path):
    _, execution_1, _, _ = _build_execution_chain()
    plan = _build_plan(
        execution_1,
        plan_id="phase43-hash-deterministic",
        plan_number=1,
        plan_context={"metadata": {"labels": {"alpha", "beta"}, "nested": {"flags": {"x", "y"}}}},
    )
    script = f"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
sys.path.insert(0, r"{Path.cwd()}")
from tests.test_offline_research_experiment_execution_plan_phase43 import _build_execution_chain, _build_plan
_, execution_1, _, _ = _build_execution_chain()
plan = _build_plan(
    execution_1,
    plan_id="phase43-hash-deterministic",
    plan_number=1,
    plan_context={{"metadata": {{"labels": {{"alpha", "beta"}}, "nested": {{"flags": {{"x", "y"}}}}}}}},
)
print(plan.plan_hash)
print(json.dumps(plan.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
"""
    first = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    second = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    assert first.stdout == second.stdout
    stdout_lines = first.stdout.splitlines()
    assert stdout_lines[0] == plan.plan_hash
    assert json.loads(stdout_lines[1]) == plan.as_dict()
