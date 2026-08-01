from __future__ import annotations

import json
from pathlib import Path

import pytest

import market_data.offline_research_canonical_evidence_fixture as canonical_fixture


def _build_fixture(root: Path):
    fixture = canonical_fixture.build_canonical_offline_research_evidence_fixture(root)
    verification = canonical_fixture.verify_canonical_offline_research_evidence_fixture(root)
    return fixture, verification


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_phase44_builds_and_verifies_full_offline_chain(tmp_path):
    fixture, verification = _build_fixture(tmp_path / "phase44-fixture")

    assert fixture.fixture_version == canonical_fixture.FIXTURE_VERSION
    assert fixture.synthetic is True
    assert fixture.test_only is True
    assert fixture.offline_only is True
    assert fixture.operational_evidence is False
    assert fixture.paper_promotion_eligible is False
    assert fixture.dataset_file.exists()
    assert fixture.manifest_file.exists()
    assert fixture.artifact_registry_file.exists()
    assert fixture.experiment_contract_file.exists()
    assert fixture.experiment_registry_file.exists()
    assert fixture.execution_registry_file.exists()
    assert fixture.execution_plan_registry_file.exists()
    assert fixture.expected_hashes_file.exists()

    assert verification.fixture == fixture
    assert verification.dataset.manifest.found_candle_count == canonical_fixture.CANONICAL_DATASET_CANDLE_COUNT
    assert verification.dataset.manifest.dataset_hash == fixture.dataset_hash
    assert verification.registry_report.external_artifact_ref == canonical_fixture.CANONICAL_ARTIFACT_ROOT_REL.as_posix()
    assert verification.registry_report.historical_research_only is True
    assert verification.registry_report.operational_evidence is False
    assert verification.registry_report.paper_promotion_eligible is False
    assert verification.artifact_reference.read_only is True
    assert verification.artifact_reference.historical_research_only is True
    assert verification.artifact_reference.operational_evidence is False
    assert verification.artifact_reference.paper_promotion_eligible is False
    assert verification.experiment_contract.historical_research_only is True
    assert verification.experiment_contract.operational_evidence is False
    assert verification.experiment_contract.paper_promotion_eligible is False
    assert verification.experiment_registry.record_count == 1
    assert verification.execution_registry.record_count == 3
    assert verification.execution_plan_registry.plan_count == 3
    assert verification.experiment_registry.records[0].contract_snapshot["extra_parameters"] == {}
    assert verification.execution_registry.records[1].previous_execution_id == verification.execution_registry.records[0].execution_id
    assert verification.execution_plan_registry.plans[1].previous_plan_id == verification.execution_plan_registry.plans[0].plan_id

    expected = _read_json(fixture.expected_hashes_file)
    assert verification.expected_hashes == expected


def test_phase44_is_idempotent_and_stable_across_directories(tmp_path):
    fixture_1, verification_1 = _build_fixture(tmp_path / "phase44-a")
    fixture_2, verification_2 = _build_fixture(tmp_path / "phase44-b")
    fixture_1_repeat, verification_1_repeat = _build_fixture(tmp_path / "phase44-a")

    assert fixture_1 == fixture_1_repeat
    assert verification_1.fixture == verification_1_repeat.fixture
    assert verification_1.expected_hashes == verification_1_repeat.expected_hashes
    assert verification_1.expected_hashes == verification_2.expected_hashes
    assert verification_1.dataset.manifest.dataset_hash == verification_2.dataset.manifest.dataset_hash
    assert verification_1.registry_report.verification_hash == verification_2.registry_report.verification_hash
    assert verification_1.artifact_reference_hash == verification_2.artifact_reference_hash
    assert verification_1.experiment_contract.contract_hash == verification_2.experiment_contract.contract_hash
    assert verification_1.experiment_registry.registry_hash == verification_2.experiment_registry.registry_hash
    assert verification_1.execution_registry.registry_hash == verification_2.execution_registry.registry_hash
    assert verification_1.execution_plan_registry.registry_hash == verification_2.execution_plan_registry.registry_hash


def test_phase44_expected_hashes_file_matches_fixture(tmp_path):
    fixture, verification = _build_fixture(tmp_path / "phase44-hashes")
    expected = _read_json(fixture.expected_hashes_file)

    assert expected["fixture_version"] == canonical_fixture.FIXTURE_VERSION
    assert expected["dataset_hash"] == verification.dataset.manifest.dataset_hash
    assert expected["manifest_hash"] == verification.dataset.manifest.manifest_hash
    assert expected["artifact_registry_hash"] == verification.fixture.artifact_registry_hash
    assert expected["artifact_registry_verification_hash"] == verification.fixture.artifact_registry_verification_hash
    assert expected["artifact_reference_hash"] == verification.fixture.artifact_reference_hash
    assert expected["experiment_contract_hash"] == verification.fixture.experiment_contract_hash
    assert expected["experiment_registration_hash"] == verification.fixture.experiment_registration_hash
    assert expected["experiment_registry_hash"] == verification.fixture.experiment_registry_hash
    assert expected["execution_hash"] == verification.fixture.execution_hash
    assert expected["execution_registry_hash"] == verification.fixture.execution_registry_hash
    assert expected["plan_hash"] == verification.fixture.plan_hash
    assert expected["plan_registry_hash"] == verification.fixture.plan_registry_hash


@pytest.mark.parametrize(
    ("mutator", "expected_message"),
    [
        (lambda payload: payload.pop(), "manifest expected_candle_count does not match candles"),
        (lambda payload: payload.insert(1, payload[0].copy()), "manifest expected_candle_count does not match candles"),
        (lambda payload: payload.__setitem__(0, {**payload[0], "close": "999999"}), "OKX dataset candles are invalid"),
        (lambda payload: payload, "mismatch"),
    ],
)
def test_phase44_rejects_tampering_in_dataset_manifest_and_registry(tmp_path, mutator, expected_message):
    fixture, _ = _build_fixture(tmp_path / "phase44-tamper")

    if expected_message == "mismatch":
        registry_payload = _read_json(fixture.artifact_registry_file)
        registry_payload["external_artifact_ref"] = "changed/relative/path"
        fixture.artifact_registry_file.write_text(json.dumps(registry_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        with pytest.raises(Exception, match="artifact_id|registry_hash|mismatch"):
            canonical_fixture.verify_canonical_offline_research_evidence_fixture(fixture.fixture_directory)
        return

    dataset_payload = _read_json(fixture.dataset_file)
    mutator(dataset_payload)
    fixture.dataset_file.write_text(json.dumps(dataset_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(Exception, match=expected_message):
        canonical_fixture.verify_canonical_offline_research_evidence_fixture(fixture.fixture_directory)


def test_phase44_rejects_tampering_in_contract_execution_and_plan(tmp_path):
    fixture, _ = _build_fixture(tmp_path / "phase44-tamper-chain")

    contract_payload = _read_json(fixture.experiment_contract_file)
    contract_payload["paper_trading_enabled"] = True
    fixture.experiment_contract_file.write_text(json.dumps(contract_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(Exception, match="paper_trading_enabled|must be false|mismatch"):
        canonical_fixture.verify_canonical_offline_research_evidence_fixture(fixture.fixture_directory)

    fixture, _ = _build_fixture(tmp_path / "phase44-tamper-chain-2")
    execution_payload = _read_json(fixture.execution_registry_file)
    execution_payload["records"][0]["operational_evidence"] = True
    fixture.execution_registry_file.write_text(json.dumps(execution_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(Exception, match="operational_evidence|must be false|mismatch"):
        canonical_fixture.verify_canonical_offline_research_evidence_fixture(fixture.fixture_directory)

    fixture, _ = _build_fixture(tmp_path / "phase44-tamper-chain-3")
    plan_payload = _read_json(fixture.execution_plan_registry_file)
    plan_payload["plans"][0]["allow_live_trading"] = True
    fixture.execution_plan_registry_file.write_text(json.dumps(plan_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(Exception, match="allow_live_trading|must be false|mismatch"):
        canonical_fixture.verify_canonical_offline_research_evidence_fixture(fixture.fixture_directory)
