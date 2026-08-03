from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import pytest

import market_data.offline_research_canonical_evidence_fixture as canonical_fixture
import market_data.offline_research_execution_authorization as phase45
from domain.serialization import serialize_value


SOURCE_COMMIT_SHA = "c5843ac613973cc55052fadeb17d524a0dd30d30"
SOURCE_BRANCH = "phase-44-canonical-offline-evidence-fixtures"
ISSUED_AT_UTC = datetime(2026, 8, 1, 12, 0, 0, 123456, tzinfo=timezone.utc)
INVALIDATION_UTC = datetime(2026, 8, 1, 12, 0, 1, 654321, tzinfo=timezone.utc)


@lru_cache(maxsize=1)
def _canonical_fixture_root():
    root = Path(tempfile.mkdtemp(prefix="phase45-canonical-fixture-"))
    canonical_fixture.build_canonical_offline_research_evidence_fixture(root)
    return root


def _canonical_verification():
    return canonical_fixture.verify_canonical_offline_research_evidence_fixture(_canonical_fixture_root())


def _canonical_plan():
    return _canonical_verification().execution_plan_registry.plans[0]


def _canonical_authorization():
    verification = _canonical_verification()
    return phase45.build_offline_research_execution_authorization(
        plan=verification.execution_plan_registry.plans[0],
        evidence=verification,
        issued_at_utc=ISSUED_AT_UTC,
        source_commit_sha=SOURCE_COMMIT_SHA,
        source_branch=SOURCE_BRANCH,
    )


def _fresh_verification(root: Path):
    canonical_fixture.build_canonical_offline_research_evidence_fixture(root)
    return canonical_fixture.verify_canonical_offline_research_evidence_fixture(root)


def test_phase45_authorizes_canonical_chain_and_is_deeply_immutable():
    verification = _canonical_verification()
    authorization = _canonical_authorization()

    assert authorization.decision == phase45.OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_AUTHORIZED
    assert authorization.allow_future_offline_execution is True
    assert authorization.allow_replay is False
    assert authorization.allow_backtest is False
    assert authorization.allow_walk_forward is False
    assert authorization.allow_performance_evaluation is False
    assert authorization.allow_ranking is False
    assert authorization.allow_paper_trading is False
    assert authorization.allow_live_trading is False
    assert authorization.allow_exchange_connectivity is False
    assert authorization.allow_strategy_execution is False
    assert authorization.allow_order_submission is False
    assert authorization.offline_only is True
    assert authorization.historical_research_only is True
    assert authorization.operational_evidence is False
    assert authorization.paper_promotion_eligible is False
    assert authorization.required_preconditions == phase45.OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REQUIRED_PRECONDITIONS
    assert authorization.verified_preconditions == phase45.OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_REQUIRED_PRECONDITIONS
    assert authorization.triggered_abort_conditions == ()
    assert authorization.rejection_reasons
    assert authorization.decision_reason
    assert authorization.verified_fixture_version == canonical_fixture.FIXTURE_VERSION
    assert authorization.verified_fixture_hash
    assert authorization.plan_id == _canonical_plan().plan_id
    assert authorization.plan_hash == _canonical_plan().plan_hash
    assert authorization.execution_id == _canonical_plan().execution_id
    assert authorization.execution_hash == _canonical_plan().execution_hash
    assert authorization.experiment_id == _canonical_plan().experiment_id
    assert authorization.experiment_registration_hash == _canonical_plan().experiment_registration_hash
    assert authorization.source_commit_sha == SOURCE_COMMIT_SHA
    assert authorization.source_branch == SOURCE_BRANCH
    assert authorization.as_dict() == serialize_value(authorization.canonical_payload())

    with pytest.raises(TypeError):
        authorization.plan_snapshot["plan_context"] = {}
    with pytest.raises(TypeError):
        authorization.evidence_snapshot["expected_hashes"]["plan_hash"] = "0" * 64

    original_expected_hashes = copy.deepcopy(verification.expected_hashes)
    verification.expected_hashes["plan_hash"] = "0" * 64
    assert authorization.evidence_snapshot["expected_hashes"]["plan_hash"] == original_expected_hashes["plan_hash"]
    assert authorization.evidence_snapshot["expected_hashes"] == original_expected_hashes


@pytest.mark.parametrize(
    ("mutator", "expected_abort"),
    [
        (lambda plan, evidence: object.__setattr__(plan, "plan_hash", "0" * 64), "PLAN_INTEGRITY_FAILURE"),
        (lambda plan, evidence: object.__setattr__(plan, "execution_hash", "1" * 64), "PLAN_INTEGRITY_FAILURE"),
        (lambda plan, evidence: object.__setattr__(plan, "experiment_registration_hash", "2" * 64), "PLAN_INTEGRITY_FAILURE"),
        (lambda plan, evidence: object.__setattr__(evidence.registry_report, "operational_evidence", True), "OPERATIONAL_PERMISSION_DETECTED"),
        (lambda plan, evidence: object.__setattr__(evidence.registry_report, "paper_promotion_eligible", True), "OPERATIONAL_PERMISSION_DETECTED"),
        (lambda plan, evidence: evidence.expected_hashes.__setitem__("dataset_hash", "3" * 64), "HASH_MISMATCH"),
        (lambda plan, evidence: evidence.expected_hashes.__setitem__("manifest_hash", "4" * 64), "HASH_MISMATCH"),
        (lambda plan, evidence: object.__setattr__(evidence.execution_registry.records[0], "execution_hash", "5" * 64), "HASH_MISMATCH"),
        (lambda plan, evidence: object.__setattr__(evidence.experiment_registry.records[0], "record_hash", "6" * 64), "HASH_MISMATCH"),
    ],
)
def test_phase45_rejects_tampered_plan_or_evidence_chain(tmp_path, mutator, expected_abort):
    verification = _fresh_verification(tmp_path / "phase45-tamper")
    plan = verification.execution_plan_registry.plans[0]
    mutator(plan, verification)

    authorization = phase45.build_offline_research_execution_authorization(
        plan=plan,
        evidence=verification,
        issued_at_utc=ISSUED_AT_UTC,
        source_commit_sha=SOURCE_COMMIT_SHA,
        source_branch=SOURCE_BRANCH,
    )

    assert authorization.decision == phase45.OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_REJECTED
    assert expected_abort in authorization.triggered_abort_conditions
    assert authorization.allow_future_offline_execution is False
    assert authorization.rejection_reasons
    assert authorization.verified_preconditions


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("decision", "RUNNING", "decision is not allowed"),
        ("decision", "EXECUTED", "decision is not allowed"),
        ("allow_future_offline_execution", False, "allow_future_offline_execution must be true for an authorized record"),
        ("allow_replay", True, "all operational allow_* flags except allow_future_offline_execution must be false"),
        ("allow_backtest", True, "all operational allow_* flags except allow_future_offline_execution must be false"),
        ("allow_walk_forward", True, "all operational allow_* flags except allow_future_offline_execution must be false"),
        ("allow_performance_evaluation", True, "all operational allow_* flags except allow_future_offline_execution must be false"),
        ("allow_ranking", True, "all operational allow_* flags except allow_future_offline_execution must be false"),
        ("allow_paper_trading", True, "all operational allow_* flags except allow_future_offline_execution must be false"),
        ("allow_live_trading", True, "all operational allow_* flags except allow_future_offline_execution must be false"),
        ("allow_exchange_connectivity", True, "all operational allow_* flags except allow_future_offline_execution must be false"),
        ("allow_strategy_execution", True, "all operational allow_* flags except allow_future_offline_execution must be false"),
        ("allow_order_submission", True, "all operational allow_* flags except allow_future_offline_execution must be false"),
        ("offline_only", False, "offline_only must be true"),
        ("historical_research_only", False, "historical_research_only must be true"),
        ("operational_evidence", True, "operational_evidence must be false"),
        ("paper_promotion_eligible", True, "paper_promotion_eligible must be false"),
        ("source_commit_sha", "", "source_commit_sha is required"),
        ("source_branch", "", "source_branch is required"),
        ("decision_reason", "", "decision_reason is required"),
        ("rejection_reasons", (), "rejection_reasons must not be empty"),
        ("issued_at_utc", datetime(2026, 8, 1, 12, 0, 0), "timezone-aware UTC datetime"),
    ],
)
def test_phase45_from_dict_rejects_invalid_decisions_flags_and_timestamps(field_name, value, message):
    authorization = _canonical_authorization()
    payload = authorization.as_dict()
    payload[field_name] = value

    with pytest.raises(phase45.OfflineResearchExecutionAuthorizationValidationError, match=re.escape(message)):
        phase45.OfflineResearchExecutionAuthorization.from_dict(payload)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("required_preconditions", ["PHASE_41_EXPERIMENT_REGISTRATION_VALID"], "missing required values"),
        ("required_preconditions", ["PHASE_41_EXPERIMENT_REGISTRATION_VALID", "PHASE_41_EXPERIMENT_REGISTRATION_VALID"], "duplicates"),
        ("required_preconditions", ["UNEXPECTED"], "unexpected value"),
        ("triggered_abort_conditions", ["PLAN_INTEGRITY_FAILURE"], "authorized records must not record abort conditions"),
        ("triggered_abort_conditions", ["PLAN_INTEGRITY_FAILURE", "PLAN_INTEGRITY_FAILURE"], "duplicates"),
        ("triggered_abort_conditions", ["UNEXPECTED"], "unexpected value"),
    ],
)
def test_phase45_precondition_and_abort_allowlists_are_fail_closed(field_name, value, message):
    authorization = _canonical_authorization()
    payload = authorization.as_dict()
    payload[field_name] = value

    with pytest.raises(phase45.OfflineResearchExecutionAuthorizationValidationError, match=message):
        phase45.OfflineResearchExecutionAuthorization.from_dict(payload)


def test_phase45_registry_round_trip_is_idempotent_and_invalidation_is_append_only(tmp_path):
    registry_file = tmp_path / "offline-research-execution-authorization-registry.json"
    authorization = _canonical_authorization()

    stored = phase45.register_offline_research_execution_authorization(
        registry_file=registry_file,
        authorization=authorization,
        updated_at_utc=INVALIDATION_UTC,
    )
    original_text = registry_file.read_text(encoding="utf-8")
    stored_again = phase45.register_offline_research_execution_authorization(
        registry_file=registry_file,
        authorization=authorization,
        updated_at_utc=INVALIDATION_UTC,
    )

    assert stored == stored_again
    assert registry_file.read_text(encoding="utf-8") == original_text

    invalidated = phase45.invalidate_offline_research_execution_authorization(
        authorization,
        issued_at_utc=INVALIDATION_UTC,
        source_commit_sha=SOURCE_COMMIT_SHA,
        source_branch=SOURCE_BRANCH,
    )
    phase45.register_offline_research_execution_authorization(
        registry_file=registry_file,
        authorization=invalidated,
        updated_at_utc=INVALIDATION_UTC,
    )

    registry = phase45.load_offline_research_execution_authorization_registry(registry_file)
    verified = phase45.verify_offline_research_execution_authorization_registry(registry_file)
    assert registry.authorization_count == 2
    assert registry.records[0].authorization_id == authorization.authorization_id
    assert registry.records[1].decision == phase45.OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_INVALIDATED
    assert registry.records[1].previous_authorization_id == authorization.authorization_id
    assert registry.records[1].previous_authorization_hash == authorization.authorization_hash
    assert registry.records[0].authorization_hash == authorization.authorization_hash
    assert verified.approved is True
    assert verified.authorization_count == 2
    assert verified.authorization_ids == (authorization.authorization_id, invalidated.authorization_id)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda payload: payload.pop("records"), "incomplete"),
        (lambda payload: payload.__setitem__("unexpected", True), "unexpected"),
        (lambda payload: payload.__setitem__("registry_hash", "0" * 64), "registry_hash mismatch"),
        (lambda payload: payload["records"][0].__setitem__("authorization_hash", "1" * 64), "authorization_hash mismatch"),
    ],
)
def test_phase45_registry_rejects_invalid_json_empty_schema_and_tampering(tmp_path, mutator, message):
    registry_file = tmp_path / "offline-research-execution-authorization-registry.json"
    authorization = _canonical_authorization()
    phase45.register_offline_research_execution_authorization(
        registry_file=registry_file,
        authorization=authorization,
        updated_at_utc=INVALIDATION_UTC,
    )
    payload = json.loads(registry_file.read_text(encoding="utf-8"))
    mutator(payload)
    registry_file.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    with pytest.raises(phase45.OfflineResearchExecutionAuthorizationError, match=message):
        phase45.load_offline_research_execution_authorization_registry(registry_file)


def test_phase45_registry_rejects_empty_invalid_json_and_missing_file(tmp_path):
    registry_file = tmp_path / "offline-research-execution-authorization-registry.json"
    with pytest.raises(phase45.OfflineResearchExecutionAuthorizationValidationError, match="missing"):
        phase45.load_offline_research_execution_authorization_registry(registry_file)

    registry_file.write_text("", encoding="utf-8")
    with pytest.raises(phase45.OfflineResearchExecutionAuthorizationValidationError, match="empty"):
        phase45.load_offline_research_execution_authorization_registry(registry_file)

    registry_file.write_text("{not-json", encoding="utf-8")
    with pytest.raises(phase45.OfflineResearchExecutionAuthorizationValidationError, match="invalid JSON"):
        phase45.load_offline_research_execution_authorization_registry(registry_file)

    registry_file.write_text("[]", encoding="utf-8")
    with pytest.raises(phase45.OfflineResearchExecutionAuthorizationValidationError, match="must be a JSON object"):
        phase45.load_offline_research_execution_authorization_registry(registry_file)


def test_phase45_hash_is_deterministic_across_processes_and_pythonhashseed(tmp_path):
    script = f"""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import json
import sys
sys.path.insert(0, r"{Path.cwd()}")
import market_data.offline_research_canonical_evidence_fixture as canonical_fixture
import market_data.offline_research_execution_authorization as phase45
root = Path(tempfile.mkdtemp(prefix="phase45-subprocess-"))
canonical_fixture.build_canonical_offline_research_evidence_fixture(root)
verification = canonical_fixture.verify_canonical_offline_research_evidence_fixture(root)
auth = phase45.build_offline_research_execution_authorization(
    plan=verification.execution_plan_registry.plans[0],
    evidence=verification,
    issued_at_utc=datetime(2026, 8, 1, 12, 0, 0, 123456, tzinfo=timezone.utc),
    source_commit_sha="c5843ac613973cc55052fadeb17d524a0dd30d30",
    source_branch="phase-44-canonical-offline-evidence-fixtures",
)
print(auth.authorization_hash)
print(json.dumps(auth.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
"""

    env_a = dict(os.environ, PYTHONHASHSEED="1")
    env_b = dict(os.environ, PYTHONHASHSEED="2")
    first = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True, env=env_a)
    second = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True, env=env_b)
    assert first.stdout == second.stdout
    stdout_lines = first.stdout.splitlines()
    assert stdout_lines[0] == _canonical_authorization().authorization_hash
    assert json.loads(stdout_lines[1]) == _canonical_authorization().as_dict()


def test_phase45_end_to_end_in_clean_directory_and_preserves_offline_only(tmp_path):
    clean_root = tmp_path / "clean-phase45"
    canonical_fixture.build_canonical_offline_research_evidence_fixture(clean_root)
    verification = canonical_fixture.verify_canonical_offline_research_evidence_fixture(clean_root)

    authorization = phase45.build_offline_research_execution_authorization(
        plan_registry_file=verification.fixture.execution_plan_registry_file,
        plan_id=verification.execution_plan_registry.plans[0].plan_id,
        fixture_directory=clean_root,
        issued_at_utc=ISSUED_AT_UTC,
        source_commit_sha=SOURCE_COMMIT_SHA,
        source_branch=SOURCE_BRANCH,
    )
    registry_file = clean_root / "offline-research-execution-authorization-registry.json"
    phase45.register_offline_research_execution_authorization(
        registry_file=registry_file,
        authorization=authorization,
        updated_at_utc=ISSUED_AT_UTC,
    )
    loaded = phase45.load_offline_research_execution_authorization_registry(registry_file)
    verified = phase45.verify_offline_research_execution_authorization_registry(registry_file)

    assert authorization.decision == phase45.OFFLINE_RESEARCH_EXECUTION_AUTHORIZATION_DECISION_AUTHORIZED
    assert authorization.allow_future_offline_execution is True
    assert authorization.allow_replay is False
    assert authorization.allow_backtest is False
    assert authorization.allow_walk_forward is False
    assert authorization.allow_performance_evaluation is False
    assert authorization.allow_ranking is False
    assert authorization.allow_paper_trading is False
    assert authorization.allow_live_trading is False
    assert authorization.allow_exchange_connectivity is False
    assert authorization.allow_strategy_execution is False
    assert authorization.allow_order_submission is False
    assert loaded.authorization_count == 1
    assert loaded.records[0].authorization_hash == authorization.authorization_hash
    assert verified.approved is True
    assert verified.authorization_count == 1
    assert verified.registry_hash == loaded.registry_hash
    assert verified.authorization_ids == (authorization.authorization_id,)
