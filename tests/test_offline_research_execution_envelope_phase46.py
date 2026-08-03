from __future__ import annotations

import copy
import json
import tempfile
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import pytest

import market_data.offline_research_canonical_evidence_fixture as phase44
import market_data.offline_research_execution_authorization as phase45
import market_data.offline_research_execution_envelope as phase46
import market_data.offline_research_experiment_execution_plan as phase43

CANONICAL_ISSUED_AT_UTC = datetime(2026, 8, 1, 12, 0, 0, 123456, tzinfo=timezone.utc)
CANONICAL_INVALIDATION_AT_UTC = datetime(2026, 8, 1, 12, 0, 1, 654321, tzinfo=timezone.utc)
CANONICAL_ENVELOPE_CREATED_AT_UTC = datetime(2026, 8, 1, 12, 0, 2, 0, tzinfo=timezone.utc)


@lru_cache(maxsize=1)
def _canonical_verification() -> phase44.CanonicalOfflineResearchEvidenceVerification:
    root = Path(tempfile.mkdtemp(prefix="phase46-canonical-fixture-"))
    phase44.build_canonical_offline_research_evidence_fixture(root)
    return phase44.verify_canonical_offline_research_evidence_fixture(root)


def _fresh_verification(root: Path) -> phase44.CanonicalOfflineResearchEvidenceVerification:
    phase44.build_canonical_offline_research_evidence_fixture(root)
    return phase44.verify_canonical_offline_research_evidence_fixture(root)


def _canonical_authorization(
    verification: phase44.CanonicalOfflineResearchEvidenceVerification | None = None,
) -> phase45.OfflineResearchExecutionAuthorization:
    verification = verification or _canonical_verification()
    plan = verification.execution_plan_registry.plans[0]
    return phase45.build_offline_research_execution_authorization(
        plan=plan,
        evidence=verification,
        issued_at_utc=CANONICAL_ISSUED_AT_UTC,
        source_commit_sha=plan.source_commit_sha,
        source_branch=plan.source_branch,
    )


def _authorization_registry_file(
    root: Path,
    authorization: phase45.OfflineResearchExecutionAuthorization,
) -> Path:
    registry_file = root / "offline-research-execution-authorization-registry.json"
    phase45.register_offline_research_execution_authorization(
        registry_file=registry_file,
        authorization=authorization,
        updated_at_utc=CANONICAL_ISSUED_AT_UTC,
    )
    return registry_file


def _build_envelope(
    root: Path,
    *,
    verification: phase44.CanonicalOfflineResearchEvidenceVerification | None = None,
    authorization: phase45.OfflineResearchExecutionAuthorization | None = None,
    plan: phase43.OfflineResearchExperimentExecutionPlan | None = None,
    previous_envelope: phase46.OfflineResearchExecutionEnvelope | None = None,
    envelope_number: int | None = None,
    random_seed: int = 123,
    resource_limits: dict[str, object] | None = None,
    execution_environment: dict[str, object] | None = None,
    output_policy: dict[str, object] | None = None,
) -> phase46.OfflineResearchExecutionEnvelope:
    verification = verification or _canonical_verification()
    plan = plan or verification.execution_plan_registry.plans[0]
    authorization = authorization or _canonical_authorization(verification)
    auth_registry_file = _authorization_registry_file(root, authorization)
    return phase46.build_offline_research_execution_envelope(
        plan=plan,
        evidence=verification,
        authorization=authorization,
        authorization_registry_file=auth_registry_file,
        plan_registry_file=verification.execution_plan_registry.registry_file,
        random_seed=random_seed,
        created_at_utc=CANONICAL_ENVELOPE_CREATED_AT_UTC,
        resource_limits=resource_limits,
        execution_environment=execution_environment,
        output_policy=output_policy,
        previous_envelope=previous_envelope,
        envelope_number=envelope_number,
    )


def _envelope_registry_file(root: Path) -> Path:
    return root / "offline-research-execution-envelope-registry.json"


def test_phase46_builds_canonical_envelope_and_is_hash_stable(tmp_path):
    verification = _fresh_verification(tmp_path / "fixture")
    envelope_a = _build_envelope(tmp_path / "first", verification=verification)
    envelope_b = _build_envelope(tmp_path / "second", verification=verification)

    assert envelope_a.envelope_id == envelope_b.envelope_id
    assert envelope_a.envelope_hash == envelope_b.envelope_hash
    assert envelope_a.as_dict()["envelope_hash"] == envelope_a.envelope_hash
    assert phase46.verify_offline_research_execution_envelope(envelope_a) is envelope_a
    assert envelope_a.future_offline_execution_authorized is True
    assert envelope_a.offline_only is True
    assert envelope_a.network_access_allowed is False
    assert envelope_a.exchange_connectivity_allowed is False
    assert envelope_a.paper_trading_allowed is False
    assert envelope_a.live_trading_allowed is False
    assert envelope_a.order_submission_allowed is False
    assert envelope_a.strategy_execution_allowed is False
    assert envelope_a.historical_research_only is True
    assert envelope_a.operational_evidence is False
    assert envelope_a.paper_promotion_eligible is False
    assert envelope_a.strategy_id == "baseline_a_okx_btc_usdt_1h_research"
    assert envelope_a.strategy_version == verification.experiment_contract.strategy_contract["strategy_version"]
    assert envelope_a.strategy_fingerprint == envelope_a.parameter_set["strategy_contract"]["contract_hash"]
    assert envelope_a.resource_limits == phase46.OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_RESOURCE_LIMITS
    assert envelope_a.execution_environment == phase46.OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_EXECUTION_ENVIRONMENT
    assert envelope_a.output_policy == phase46.OFFLINE_RESEARCH_EXECUTION_ENVELOPE_DEFAULT_OUTPUT_POLICY
    assert envelope_a.parameter_set["strategy_contract"]["strategy_id"] == "baseline_a_okx_btc_usdt_1h_research"

    rebuilt = phase46.OfflineResearchExecutionEnvelope.from_dict(envelope_a.as_dict())
    assert rebuilt.as_dict() == envelope_a.as_dict()
    assert rebuilt.envelope_hash == envelope_a.envelope_hash


def test_phase46_envelope_is_deeply_immutable_and_source_independent(tmp_path):
    verification = _fresh_verification(tmp_path / "fixture")
    authorization = _canonical_authorization(verification)
    envelope = _build_envelope(tmp_path / "envelope", verification=verification, authorization=authorization)
    baseline_payload = envelope.as_dict()

    with pytest.raises(TypeError):
        envelope.parameter_set["new_field"] = {}
    with pytest.raises(TypeError):
        envelope.parameter_set["strategy_contract"]["allowed_use_cases"][0] = "mutated"
    with pytest.raises(TypeError):
        envelope.resource_limits["max_runtime_seconds"] = 1
    with pytest.raises(TypeError):
        envelope.execution_environment["network_policy"] = "ALLOW_ALL"
    with pytest.raises(TypeError):
        envelope.output_policy["overwrite_existing"] = True
    with pytest.raises(TypeError):
        envelope.authorization_snapshot["evidence_snapshot"]["expected_hashes"]["plan_hash"] = "0" * 64
    with pytest.raises(TypeError):
        envelope.plan_snapshot["plan_context"] = {}

    object.__setattr__(authorization, "decision", phase45.OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_REJECTED)
    object.__setattr__(verification.execution_plan_registry.plans[0], "source_branch", "tampered-branch")
    object.__setattr__(
        verification.artifact_reference.resolution.registry_report,
        "manifest_hash",
        "1" * 64,
    )
    verification.expected_hashes["plan_hash"] = "2" * 64

    assert envelope.as_dict() == baseline_payload
    assert envelope.envelope_hash == baseline_payload["envelope_hash"]


def test_phase46_supports_registry_round_trip_and_idempotent_register(tmp_path):
    verification = _fresh_verification(tmp_path / "fixture")
    envelope = _build_envelope(tmp_path / "build", verification=verification)
    registry_file = _envelope_registry_file(tmp_path)

    registry = phase46.OfflineResearchExecutionEnvelopeRegistry(
        registry_file=registry_file,
        created_at_utc=CANONICAL_ENVELOPE_CREATED_AT_UTC,
        updated_at_utc=CANONICAL_ENVELOPE_CREATED_AT_UTC + timedelta(minutes=1),
        records=(envelope,),
    )
    phase46.save_offline_research_execution_envelope_registry(registry_file, registry)
    original_text = registry_file.read_text(encoding="utf-8")
    stored_again = phase46.save_offline_research_execution_envelope_registry(registry_file, registry)
    loaded = phase46.load_offline_research_execution_envelope_registry(registry_file)
    verified = phase46.verify_offline_research_execution_envelope_registry(registry_file)

    assert stored_again.registry_hash == registry.registry_hash
    assert registry_file.read_text(encoding="utf-8") == original_text
    assert loaded.record_count == 1
    assert loaded.records[0].envelope_hash == envelope.envelope_hash
    assert verified.approved is True
    assert verified.record_count == 1
    assert verified.envelope_ids == (envelope.envelope_id,)
    assert verified.envelope_hashes == (envelope.envelope_hash,)
    assert verified.registry_hash == loaded.registry_hash


def test_phase46_chains_previous_envelope_and_registers_append_only(tmp_path):
    verification = _fresh_verification(tmp_path / "fixture")
    envelope_1 = _build_envelope(tmp_path / "build-1", verification=verification, envelope_number=1)
    envelope_2 = _build_envelope(
        tmp_path / "build-2",
        verification=verification,
        previous_envelope=envelope_1,
        envelope_number=2,
    )
    registry_file = _envelope_registry_file(tmp_path)

    stored_1 = phase46.register_offline_research_execution_envelope(
        registry_file=registry_file,
        envelope=envelope_1,
    )
    stored_2 = phase46.register_offline_research_execution_envelope(
        registry_file=registry_file,
        envelope=envelope_2,
    )
    same_text = registry_file.read_text(encoding="utf-8")
    stored_2_again = phase46.register_offline_research_execution_envelope(
        registry_file=registry_file,
        envelope=envelope_2,
    )
    loaded = phase46.load_offline_research_execution_envelope_registry(registry_file)

    assert stored_1.envelope_hash == envelope_1.envelope_hash
    assert stored_2.envelope_hash == envelope_2.envelope_hash
    assert stored_2_again.envelope_hash == envelope_2.envelope_hash
    assert registry_file.read_text(encoding="utf-8") == same_text
    assert loaded.records == (envelope_1, envelope_2)
    assert loaded.latest_envelope_for_plan(envelope_1.plan_id).envelope_hash == envelope_2.envelope_hash
    assert envelope_2.previous_envelope_id == envelope_1.envelope_id
    assert envelope_2.previous_envelope_hash == envelope_1.envelope_hash
    assert envelope_2.envelope_number == 2


def test_phase46_rejects_invalidated_or_tampered_authorization_state(tmp_path):
    verification = _fresh_verification(tmp_path / "fixture")
    authorization = _canonical_authorization(verification)
    auth_registry_file = _authorization_registry_file(tmp_path / "auth", authorization)

    invalidated = phase45.invalidate_offline_research_execution_authorization(
        authorization,
        issued_at_utc=CANONICAL_INVALIDATION_AT_UTC,
        source_commit_sha=authorization.source_commit_sha,
        source_branch=authorization.source_branch,
    )
    phase45.register_offline_research_execution_authorization(
        registry_file=auth_registry_file,
        authorization=invalidated,
        updated_at_utc=CANONICAL_INVALIDATION_AT_UTC,
    )

    with pytest.raises(phase46.OfflineResearchExecutionEnvelopeValidationError, match="authorization registry is not in the authorized state"):
        phase46.build_offline_research_execution_envelope(
            plan=verification.execution_plan_registry.plans[0],
            evidence=verification,
            authorization=authorization,
            authorization_registry_file=auth_registry_file,
            plan_registry_file=verification.execution_plan_registry.registry_file,
            random_seed=123,
            created_at_utc=CANONICAL_ENVELOPE_CREATED_AT_UTC,
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda auth: object.__setattr__(auth, "decision", phase45.OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_REJECTED),
            "authorization must be authorized for future offline execution",
        ),
        (
            lambda auth: object.__setattr__(auth, "allow_future_offline_execution", False),
            "authorization must allow future offline execution",
        ),
    ],
)
def test_phase46_rejects_tampered_authorization_object(tmp_path, mutator, message):
    verification = _fresh_verification(tmp_path / "fixture")
    authorization = _canonical_authorization(verification)
    auth_registry_file = _authorization_registry_file(tmp_path / "auth", authorization)
    mutator(authorization)

    with pytest.raises(phase46.OfflineResearchExecutionEnvelopeValidationError, match=message):
        phase46.build_offline_research_execution_envelope(
            plan=verification.execution_plan_registry.plans[0],
            evidence=verification,
            authorization=authorization,
            authorization_registry_file=auth_registry_file,
            plan_registry_file=verification.execution_plan_registry.registry_file,
            random_seed=123,
            created_at_utc=CANONICAL_ENVELOPE_CREATED_AT_UTC,
        )


def test_phase46_rejects_plan_and_evidence_divergence(tmp_path):
    verification = _fresh_verification(tmp_path / "fixture")
    authorization = _canonical_authorization(verification)
    auth_registry_file = _authorization_registry_file(tmp_path / "auth", authorization)
    plan = verification.execution_plan_registry.plans[0]
    tampered_plan = phase43.OfflineResearchExperimentExecutionPlan.from_dict(plan.as_dict())
    object.__setattr__(tampered_plan, "source_branch", "tampered-branch")

    with pytest.raises(phase46.OfflineResearchExecutionEnvelopeValidationError, match="plan is not the current effective state for the plan registry"):
        phase46.build_offline_research_execution_envelope(
            plan=tampered_plan,
            evidence=verification,
            authorization=authorization,
            authorization_registry_file=auth_registry_file,
            plan_registry_file=verification.execution_plan_registry.registry_file,
            random_seed=123,
            created_at_utc=CANONICAL_ENVELOPE_CREATED_AT_UTC,
        )

    object.__setattr__(
        verification.artifact_reference.resolution.registry_report,
        "manifest_hash",
        "0" * 64,
    )
    with pytest.raises(phase46.OfflineResearchExecutionEnvelopeValidationError, match="authorization and evidence must refer to the same manifest hash"):
        phase46.build_offline_research_execution_envelope(
            plan=plan,
            evidence=verification,
            authorization=authorization,
            authorization_registry_file=auth_registry_file,
            plan_registry_file=verification.execution_plan_registry.registry_file,
            random_seed=123,
            created_at_utc=CANONICAL_ENVELOPE_CREATED_AT_UTC,
        )


@pytest.mark.parametrize("random_seed", [True, -1])
def test_phase46_rejects_invalid_random_seed(tmp_path, random_seed):
    verification = _fresh_verification(tmp_path / "fixture")
    authorization = _canonical_authorization(verification)
    with pytest.raises(phase46.OfflineResearchExecutionEnvelopeValidationError, match="random_seed"):
        _build_envelope(
            tmp_path / "envelope",
            verification=verification,
            authorization=authorization,
            random_seed=random_seed,
        )


@pytest.mark.parametrize(
    ("field_name", "replacement", "expected"),
    [
        ("future_offline_execution_authorized", False, "future_offline_execution_authorized must be true"),
        ("offline_only", False, "offline_only must be true"),
        ("historical_research_only", False, "historical_research_only must be true"),
        ("operational_evidence", True, "operational_evidence must be false"),
        ("paper_promotion_eligible", True, "paper_promotion_eligible must be false"),
        ("network_access_allowed", True, "network_access_allowed must be false"),
        ("exchange_connectivity_allowed", True, "exchange_connectivity_allowed must be false"),
        ("paper_trading_allowed", True, "paper_trading_allowed must be false"),
        ("live_trading_allowed", True, "live_trading_allowed must be false"),
        ("order_submission_allowed", True, "order_submission_allowed must be false"),
        ("strategy_execution_allowed", True, "strategy_execution_allowed must be false"),
        ("non_operational_declaration", "tampered", "non_operational_declaration diverges"),
    ],
)
def test_phase46_rejects_tampered_payload_flags(
    tmp_path,
    field_name,
    replacement,
    expected,
):
    verification = _fresh_verification(tmp_path / "fixture")
    envelope = _build_envelope(tmp_path / "envelope", verification=verification)
    payload = envelope.as_dict()
    payload[field_name] = replacement

    with pytest.raises(phase46.OfflineResearchExecutionEnvelopeValidationError, match=expected):
        phase46.OfflineResearchExecutionEnvelope.from_dict(payload)


@pytest.mark.parametrize(
    ("resource_limits", "execution_environment", "output_policy", "expected"),
    [
        ({"max_runtime_seconds": 0, "max_memory_mb": 1, "max_output_bytes": 1, "max_event_count": 1}, None, None, "greater than zero"),
        ({"max_runtime_seconds": True, "max_memory_mb": 1, "max_output_bytes": 1, "max_event_count": 1}, None, None, "must be an integer"),
        ({"max_runtime_seconds": 1, "max_memory_mb": 1, "max_output_bytes": 1}, None, None, "required in resource_limits"),
        (None, {"environment_type": "ONLINE", "network_policy": "DENY_ALL", "exchange_policy": "DENY_ALL", "filesystem_policy": "ISOLATED_OUTPUT_ONLY", "process_policy": "NO_CHILD_PROCESSES"}, None, "OFFLINE_ISOLATED"),
        (None, {"environment_type": "OFFLINE_ISOLATED", "network_policy": "ALLOW", "exchange_policy": "DENY_ALL", "filesystem_policy": "ISOLATED_OUTPUT_ONLY", "process_policy": "NO_CHILD_PROCESSES"}, None, "DENY_ALL"),
        (None, None, {"output_directory_mode": "SHARED", "overwrite_existing": False, "append_only_results": True, "temporary_output_allowed": True, "external_path_allowed": False}, "ISOLATED"),
        (None, None, {"output_directory_mode": "ISOLATED", "overwrite_existing": True, "append_only_results": True, "temporary_output_allowed": True, "external_path_allowed": False}, "overwrite_existing must be false"),
        (None, None, {"output_directory_mode": "ISOLATED", "overwrite_existing": False, "append_only_results": True, "temporary_output_allowed": True}, "required in output_policy"),
    ],
)
def test_phase46_rejects_invalid_resource_environment_and_output_policies(
    tmp_path,
    resource_limits,
    execution_environment,
    output_policy,
    expected,
):
    verification = _fresh_verification(tmp_path / "fixture")
    authorization = _canonical_authorization(verification)

    with pytest.raises(phase46.OfflineResearchExecutionEnvelopeValidationError, match=expected):
        _build_envelope(
            tmp_path / "envelope",
            verification=verification,
            authorization=authorization,
            resource_limits=resource_limits,
            execution_environment=execution_environment,
            output_policy=output_policy,
        )


def test_phase46_registry_rejects_tampered_chain_and_invalid_json(tmp_path):
    verification = _fresh_verification(tmp_path / "fixture")
    envelope_1 = _build_envelope(tmp_path / "build-1", verification=verification, envelope_number=1)
    envelope_2 = _build_envelope(
        tmp_path / "build-2",
        verification=verification,
        previous_envelope=envelope_1,
        envelope_number=2,
    )
    registry_file = _envelope_registry_file(tmp_path)
    registry = phase46.OfflineResearchExecutionEnvelopeRegistry(
        registry_file=registry_file,
        created_at_utc=CANONICAL_ENVELOPE_CREATED_AT_UTC,
        updated_at_utc=CANONICAL_ENVELOPE_CREATED_AT_UTC + timedelta(minutes=1),
        records=(envelope_1, envelope_2),
    )
    phase46.save_offline_research_execution_envelope_registry(registry_file, registry)

    payload = json.loads(registry_file.read_text(encoding="utf-8"))
    payload["registry_hash"] = "0" * 64
    registry_file.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(phase46.OfflineResearchExecutionEnvelopeIntegrityError, match="registry_hash mismatch"):
        phase46.load_offline_research_execution_envelope_registry(registry_file)

    payload = json.loads(json.dumps(registry.as_dict(), ensure_ascii=False, sort_keys=True))
    payload["records"][1]["previous_envelope_hash"] = "1" * 64
    registry_file.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(phase46.OfflineResearchExecutionEnvelopeIntegrityError, match="envelope_id mismatch"):
        phase46.load_offline_research_execution_envelope_registry(registry_file)

    registry_file.write_text("", encoding="utf-8")
    with pytest.raises(phase46.OfflineResearchExecutionEnvelopeValidationError, match="empty"):
        phase46.load_offline_research_execution_envelope_registry(registry_file)

    registry_file.write_text("{not-json", encoding="utf-8")
    with pytest.raises(phase46.OfflineResearchExecutionEnvelopeValidationError, match="invalid JSON"):
        phase46.load_offline_research_execution_envelope_registry(registry_file)

    registry_file.write_text("[]", encoding="utf-8")
    with pytest.raises(phase46.OfflineResearchExecutionEnvelopeValidationError, match="must be a JSON object"):
        phase46.load_offline_research_execution_envelope_registry(registry_file)
