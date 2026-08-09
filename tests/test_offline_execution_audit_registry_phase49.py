from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import market_data.offline_execution_audit_record as phase48
import market_data.offline_execution_audit_registry as phase49
import market_data.offline_research_canonical_evidence_fixture as phase44
import market_data.offline_research_execution_authorization as phase45
import market_data.offline_research_execution_envelope as phase46
import market_data.offline_research_experiment_contract as phase40
import market_data.offline_research_experiment_execution_plan as phase43
import market_data.offline_research_experiment_execution_registry as phase42
import market_data.offline_research_experiment_registry as phase41
import market_data.offline_research_neutral_executor as phase47
import market_data.offline_research_backtest as backtest

CANONICAL_AUTHORIZATION_ISSUED_AT_UTC = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
CANONICAL_ENVELOPE_CREATED_AT_UTC = datetime(2026, 8, 1, 12, 0, 1, tzinfo=timezone.utc)
CANONICAL_REQUEST_CREATED_AT_UTC = datetime(2026, 8, 1, 12, 0, 2, tzinfo=timezone.utc)
CANONICAL_RESULT_STARTED_AT_UTC = datetime(2026, 8, 1, 12, 0, 3, tzinfo=timezone.utc)
CANONICAL_RESULT_FINISHED_AT_UTC = datetime(2026, 8, 1, 12, 0, 4, tzinfo=timezone.utc)
SYNTHETIC_CREATED_AT_UTC = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)
SYNTHETIC_CREATED_AT_UTC_OFFSET = datetime(2026, 8, 4, 9, 0, 0, tzinfo=timezone(timedelta(hours=-3)))




def _fresh_artifact_reference(
    verification: phase44.CanonicalOfflineResearchEvidenceVerification,
) -> phase48.OkxOfflineResearchArtifactReference:
    resolution = backtest.OkxPersistentResearchArtifactResolution(
        registry_file=verification.artifact_reference.resolution.registry_file,
        dataset_file=verification.artifact_reference.resolution.dataset_file,
        manifest_file=verification.artifact_reference.resolution.manifest_file,
        registry_report=verification.registry_report,
        dataset_report=dict(verification.artifact_reference.resolution.dataset_report),
    )
    return backtest.resolve_okx_offline_research_artifact_reference(resolution=resolution)


def _fresh_bundle(canonical_runtime_bundle: dict[str, object]) -> dict[str, object]:
    verification = canonical_runtime_bundle["verification"]
    assert isinstance(verification, phase44.CanonicalOfflineResearchEvidenceVerification)
    fresh_verification = phase44.verify_canonical_offline_research_evidence_fixture(
        verification.fixture.fixture_directory
    )
    return {
        "verification": fresh_verification,
        "artifact_reference": _fresh_artifact_reference(fresh_verification),
        "experiment_contract": phase40.build_offline_research_experiment_contract(
            artifact_reference=fresh_verification.artifact_reference,
            strategy_contract=phase40.BaselineAOkxBtcUsdtResearchContract.from_dict(
                dict(fresh_verification.experiment_contract.strategy_contract)
            ),
            experiment_id=fresh_verification.experiment_contract.experiment_id,
            experiment_version=fresh_verification.experiment_contract.experiment_version,
            created_at_utc=fresh_verification.experiment_contract.created_at_utc,
            purpose=fresh_verification.experiment_contract.purpose,
            window_start_utc=fresh_verification.experiment_contract.window_start_utc,
            window_end_utc=fresh_verification.experiment_contract.window_end_utc,
            symbol=fresh_verification.experiment_contract.symbol,
            interval=fresh_verification.experiment_contract.interval,
            entry_fee_rate=fresh_verification.experiment_contract.entry_fee_rate,
            exit_fee_rate=fresh_verification.experiment_contract.exit_fee_rate,
            spread_bps=fresh_verification.experiment_contract.spread_bps,
            slippage_bps=fresh_verification.experiment_contract.slippage_bps,
            leverage=fresh_verification.experiment_contract.leverage,
            initial_capital=fresh_verification.experiment_contract.initial_capital,
            risk_percent=fresh_verification.experiment_contract.risk_percent,
            extra_parameters=dict(fresh_verification.experiment_contract.extra_parameters),
            historical_research_only=fresh_verification.experiment_contract.historical_research_only,
            operational_evidence=fresh_verification.experiment_contract.operational_evidence,
            paper_promotion_eligible=fresh_verification.experiment_contract.paper_promotion_eligible,
            paper_trading_enabled=fresh_verification.experiment_contract.paper_trading_enabled,
            live_trading_enabled=fresh_verification.experiment_contract.live_trading_enabled,
            execution_enabled=fresh_verification.experiment_contract.execution_enabled,
            order_submission_enabled=fresh_verification.experiment_contract.order_submission_enabled,
            credentials_required=fresh_verification.experiment_contract.credentials_required,
            exchange_api_enabled=fresh_verification.experiment_contract.exchange_api_enabled,
            download_enabled=fresh_verification.experiment_contract.download_enabled,
            ingestion_enabled=fresh_verification.experiment_contract.ingestion_enabled,
            allowed_use_cases=tuple(fresh_verification.experiment_contract.allowed_use_cases),
            prohibited_use_cases=tuple(fresh_verification.experiment_contract.prohibited_use_cases),
            non_operational_declaration=fresh_verification.experiment_contract.non_operational_declaration,
        ),
        "experiment_registry": phase41.OfflineResearchExperimentRegistry.from_dict(
            fresh_verification.experiment_registry.as_dict()
        ),
        "execution_registry": phase42.OfflineResearchExperimentExecutionRegistry.from_dict(
            fresh_verification.execution_registry.as_dict()
        ),
        "execution_plan": phase43.OfflineResearchExperimentExecutionPlan.from_dict(
            fresh_verification.execution_plan_registry.plans[0].as_dict()
        ),
        "authorization": phase45.OfflineResearchExecutionAuthorization.from_dict(
            canonical_runtime_bundle["authorization"].as_dict()
        ),
        "envelope": phase46.OfflineResearchExecutionEnvelope.from_dict(
            canonical_runtime_bundle["envelope"].as_dict()
        ),
        "result": phase47.OfflineResearchNeutralExecutionResult.from_dict(
            canonical_runtime_bundle["result"].as_dict()
        ),
    }


def _synthetic_provenance(
    *,
    label_order: tuple[str, ...],
    group_order: tuple[tuple[str, ...], ...],
    execution_attempt_number: int,
) -> dict[str, object]:
    return {
        "artifact_reference": {
            "artifact_id": "a" * 64,
            "provider_name": "OKX",
            "market_type": "spot",
            "instrument": "BTC-USDT",
            "symbol": "BTCUSDT",
            "interval": "1H",
            "labels": set(label_order),
            "nested": {
                "groups": {frozenset(group) for group in group_order},
            },
        },
        "experiment_contract": {
            "experiment_id": "synthetic_experiment_49",
            "strategy_contract": {
                "strategy_id": "baseline_a_okx_btc_usdt_1h_research",
                "contract_hash": "b" * 64,
            },
            "window": {
                "start": "2026-08-04T00:00:00Z",
                "end": "2026-08-05T00:00:00Z",
            },
        },
        "execution_registry": {
            "execution_id": "synthetic-execution",
            "attempts": {frozenset({"attempt-1"}), frozenset({"attempt-2", "attempt-3"})},
        },
        "execution_attempt_number": execution_attempt_number,
        "result": {
            "status": "SUCCEEDED",
            "notes": ["offline", "audit"],
        },
    }


def _synthetic_user_metadata(*, label_order: tuple[str, ...], group_order: tuple[tuple[str, ...], ...]) -> dict[str, object]:
    return {
        "labels": set(label_order),
        "nested": {
            "inner_labels": set(reversed(label_order)),
            "groups": {frozenset(group) for group in group_order},
        },
        "notes": ["offline", "read-only"],
    }


def _synthetic_record(
    *,
    created_at_utc: datetime,
    label_order: tuple[str, ...],
    group_order: tuple[tuple[str, ...], ...],
    execution_id: str = "synthetic-execution",
    execution_attempt_number: int = 1,
    note: str = "",
) -> phase48.OfflineExecutionAuditRecord:
    provenance = _synthetic_provenance(
        label_order=label_order,
        group_order=group_order,
        execution_attempt_number=execution_attempt_number,
    )
    user_metadata = _synthetic_user_metadata(label_order=label_order, group_order=group_order)
    if note:
        user_metadata["note"] = note
    return phase48.OfflineExecutionAuditRecord(
        schema_version=phase48.OFFLINE_EXECUTION_AUDIT_RECORD_SCHEMA_VERSION,
        lineage_hash=phase48._hash_payload(provenance),
        artifact_reference_id="c" * 64,
        experiment_id="synthetic_experiment_49",
        experiment_contract_hash="d" * 64,
        execution_id=execution_id,
        execution_attempt_number=execution_attempt_number,
        execution_attempt_id=f"{execution_id}:{execution_attempt_number}",
        execution_plan_hash="e" * 64,
        evidence_hash="f" * 64,
        authorization_hash="1" * 64,
        envelope_hash="2" * 64,
        neutral_execution_id="3" * 64,
        result_hash="4" * 64,
        created_at_utc=created_at_utc,
        metadata={
            "provenance": provenance,
            "user_metadata": user_metadata,
        },
    )


def _build_real_audit_record(canonical_runtime_bundle: dict[str, object]) -> phase48.OfflineExecutionAuditRecord:
    bundle = _fresh_bundle(canonical_runtime_bundle)
    return phase48.build_offline_execution_audit_record(
        artifact_reference=bundle["artifact_reference"],
        experiment_contract=bundle["experiment_contract"],
        experiment_registry=bundle["experiment_registry"],
        execution_registry=bundle["execution_registry"],
        execution_plan=bundle["execution_plan"],
        evidence=bundle["verification"],
        authorization=bundle["authorization"],
        envelope=bundle["envelope"],
        result=bundle["result"],
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        metadata={
            "labels": {"beta", "alpha"},
            "nested": {"groups": {frozenset({"gamma", "delta"})}},
        },
    )


def _registry_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _forbidden(*args, **kwargs):
    raise AssertionError("unexpected operational or legacy call")


def test_phase49_builds_entry_from_real_phase48_audit_record_and_preserves_immutability(
    canonical_runtime_bundle: dict[str, object],
    canonical_verification: phase44.CanonicalOfflineResearchEvidenceVerification,
):
    record = _build_real_audit_record(canonical_runtime_bundle)
    metadata_source = {
        "labels": {"beta", "alpha"},
        "nested": {
            "inner_labels": {"two", "one"},
            "groups": {frozenset({"gamma", "delta"}), frozenset({"alpha"})},
        },
        "notes": ["offline", "read-only"],
    }
    metadata_equivalent = {
        "notes": ["offline", "read-only"],
        "nested": {
            "groups": {frozenset({"alpha"}), frozenset({"delta", "gamma"})},
            "inner_labels": {"one", "two"},
        },
        "labels": {"alpha", "beta"},
    }

    entry_a = phase49.build_offline_execution_audit_registry_entry(
        audit_record=record,
        entry_number=1,
        metadata=metadata_source,
        registered_at_utc=SYNTHETIC_CREATED_AT_UTC,
    )
    entry_b = phase49.build_offline_execution_audit_registry_entry(
        audit_record=record,
        entry_number=1,
        metadata=metadata_equivalent,
        registered_at_utc=SYNTHETIC_CREATED_AT_UTC_OFFSET,
    )

    assert entry_a.registry_entry_id == entry_b.registry_entry_id
    assert entry_a.registry_entry_hash == entry_b.registry_entry_hash
    assert entry_a.audit_record_id == record.audit_record_id
    assert entry_a.audit_record_hash == record.audit_record_hash
    assert entry_a.execution_attempt_id == record.execution_attempt_id
    assert entry_a.metadata["labels"] == frozenset({"alpha", "beta"})
    assert entry_a.metadata["nested"]["inner_labels"] == frozenset({"one", "two"})
    assert entry_a.metadata["nested"]["groups"] == frozenset(
        {frozenset({"alpha"}), frozenset({"delta", "gamma"})}
    )
    assert entry_a.as_dict()["registered_at_utc"] == "2026-08-04T12:00:00Z"
    assert entry_b.as_dict()["registered_at_utc"] == "2026-08-04T12:00:00Z"
    assert json.dumps(entry_a.as_dict(), sort_keys=True, separators=(",", ":"))

    with pytest.raises(TypeError):
        entry_a.metadata["labels"] = frozenset({"gamma"})  # type: ignore[index]
    with pytest.raises(AttributeError):
        entry_a.metadata["labels"].add("gamma")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        entry_a.metadata["nested"]["inner_labels"].add("gamma")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        entry_a.metadata["nested"]["groups"].add(frozenset({"gamma"}))  # type: ignore[attr-defined]

    metadata_source["labels"].add("late")  # type: ignore[attr-defined]
    metadata_source["nested"]["inner_labels"].add("late")  # type: ignore[attr-defined]
    metadata_source["nested"]["groups"].add(frozenset({"late"}))  # type: ignore[attr-defined]

    assert entry_a.metadata["labels"] == frozenset({"alpha", "beta"})
    assert entry_a.metadata["nested"]["inner_labels"] == frozenset({"one", "two"})
    assert entry_a.metadata["nested"]["groups"] == frozenset({frozenset({"alpha"}), frozenset({"delta", "gamma"})})

    snapshot = entry_a.as_dict()
    snapshot["metadata"]["labels"] = ("changed",)
    assert entry_a.as_dict()["metadata"]["labels"] == ["alpha", "beta"]


def test_phase49_registry_entry_serializes_sets_and_frozensets_deterministically_across_order_and_timezone():
    record_a = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )
    record_b = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC_OFFSET,
        label_order=("beta", "alpha"),
        group_order=(("epsilon",), ("delta", "gamma")),
    )
    entry_a = phase49.build_offline_execution_audit_registry_entry(
        audit_record=record_a,
        entry_number=1,
        metadata={
            "labels": {"alpha", "beta"},
            "nested": {"groups": {frozenset({"gamma", "delta"}), frozenset({"epsilon"})}},
        },
        registered_at_utc=SYNTHETIC_CREATED_AT_UTC,
    )
    entry_b = phase49.build_offline_execution_audit_registry_entry(
        audit_record=record_b,
        entry_number=1,
        metadata={
            "labels": {"beta", "alpha"},
            "nested": {"groups": {frozenset({"epsilon"}), frozenset({"delta", "gamma"})}},
        },
        registered_at_utc=SYNTHETIC_CREATED_AT_UTC_OFFSET,
    )

    assert entry_a.registry_entry_id == entry_b.registry_entry_id
    assert entry_a.registry_entry_hash == entry_b.registry_entry_hash
    assert entry_a.as_dict()["registered_at_utc"] == "2026-08-04T12:00:00Z"
    assert entry_b.as_dict()["registered_at_utc"] == "2026-08-04T12:00:00Z"
    assert json.dumps(entry_a.as_dict(), sort_keys=True, separators=(",", ":"))


def test_phase49_registry_empty_is_canonical_and_hash_stable():
    registry_a = phase49.create_offline_execution_audit_registry(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        updated_at_utc=SYNTHETIC_CREATED_AT_UTC,
        metadata={"labels": {"alpha", "beta"}},
    )
    registry_b = phase49.create_offline_execution_audit_registry(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC_OFFSET,
        updated_at_utc=SYNTHETIC_CREATED_AT_UTC_OFFSET,
        metadata={"labels": {"beta", "alpha"}},
    )

    assert registry_a.entry_count == 0
    assert registry_a.first_entry_id is None
    assert registry_a.last_entry_id is None
    assert registry_a.registry_hash == registry_b.registry_hash
    assert registry_a.as_dict()["created_at_utc"] == "2026-08-04T12:00:00Z"
    assert registry_b.as_dict()["created_at_utc"] == "2026-08-04T12:00:00Z"


def test_phase49_registry_registers_chain_and_preserves_immutability(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    registry_file = Path("records") / "audit-registry.json"
    record_1 = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )
    record_2 = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("beta", "alpha"),
        group_order=(("epsilon",), ("delta", "gamma")),
        execution_attempt_number=2,
    )

    entry_1 = phase49.register_offline_execution_audit_record(
        registry_file=registry_file,
        audit_record=record_1,
        root_directory=root,
        registered_at_utc=SYNTHETIC_CREATED_AT_UTC,
        metadata={
            "labels": {"alpha", "beta"},
            "nested": {"groups": {frozenset({"gamma", "delta"}), frozenset({"epsilon"})}},
        },
    )
    entry_1_again = phase49.register_offline_execution_audit_record(
        registry_file=registry_file,
        audit_record=record_1,
        root_directory=root,
        registered_at_utc=SYNTHETIC_CREATED_AT_UTC_OFFSET,
        metadata={
            "nested": {"groups": {frozenset({"epsilon"}), frozenset({"delta", "gamma"})}},
            "labels": {"beta", "alpha"},
        },
    )
    entry_2 = phase49.register_offline_execution_audit_record(
        registry_file=registry_file,
        audit_record=record_2,
        root_directory=root,
        registered_at_utc=SYNTHETIC_CREATED_AT_UTC_OFFSET,
        metadata={
            "labels": {"beta", "alpha"},
            "nested": {"groups": {frozenset({"epsilon"}), frozenset({"delta", "gamma"})}},
        },
    )

    loaded = phase49.load_offline_execution_audit_registry(registry_file=registry_file, root_directory=root)
    saved = phase49.save_offline_execution_audit_registry(
        registry_file=registry_file,
        registry=loaded,
        root_directory=root,
    )
    saved_again = phase49.save_offline_execution_audit_registry(
        registry_file=registry_file,
        registry=loaded,
        root_directory=root,
    )

    assert entry_1.registry_entry_id == entry_1_again.registry_entry_id
    assert entry_1.registry_entry_hash == entry_1_again.registry_entry_hash
    assert entry_2.entry_number == 2
    assert entry_2.previous_entry_id == entry_1.registry_entry_id
    assert entry_2.previous_entry_hash == entry_1.registry_entry_hash
    assert loaded.entry_count == 2
    assert loaded.entries[0].registry_entry_id == entry_1.registry_entry_id
    assert loaded.entries[1].registry_entry_id == entry_2.registry_entry_id
    assert loaded.first_entry_id == entry_1.registry_entry_id
    assert loaded.last_entry_id == entry_2.registry_entry_id
    assert saved.as_dict() == loaded.as_dict()
    assert saved_again.as_dict() == loaded.as_dict()
    assert _registry_text(root / registry_file) == json.dumps(
        loaded.as_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    with pytest.raises(TypeError):
        loaded.entries[0].metadata["labels"][0] = "changed"
    with pytest.raises(TypeError):
        loaded.metadata["labels"][0] = "changed"


def test_phase49_registry_rejects_conflicts_and_chain_breaks(tmp_path):
    record_1 = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )
    record_2 = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("beta", "alpha"),
        group_order=(("epsilon",), ("delta", "gamma")),
        execution_attempt_number=2,
    )
    record_3 = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta", "gamma"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )

    entry_1 = phase49.build_offline_execution_audit_registry_entry(
        audit_record=record_1,
        entry_number=1,
        metadata={"labels": {"alpha", "beta"}},
    )
    entry_2 = phase49.build_offline_execution_audit_registry_entry(
        audit_record=record_2,
        entry_number=2,
        previous_entry_id=entry_1.registry_entry_id,
        previous_entry_hash=entry_1.registry_entry_hash,
        metadata={"labels": {"beta", "alpha"}},
    )
    registry = phase49.create_offline_execution_audit_registry(entries=(entry_1, entry_2))
    root = tmp_path / "root"
    root.mkdir()
    registry_file = Path("records") / "audit-registry.json"
    phase49.save_offline_execution_audit_registry(
        registry_file=registry_file,
        registry=registry,
        root_directory=root,
    )

    with pytest.raises(phase49.OfflineExecutionAuditRegistryValidationError, match="entry_number sequence"):
        phase49.create_offline_execution_audit_registry(entries=(entry_2, entry_1))

    tampered_previous_id = phase49.build_offline_execution_audit_registry_entry(
        audit_record=record_2,
        entry_number=2,
        previous_entry_id="f" * 64,
        previous_entry_hash=entry_1.registry_entry_hash,
        metadata={"labels": {"beta", "alpha"}},
    )
    with pytest.raises(phase49.OfflineExecutionAuditRegistryIntegrityError, match="previous_entry_id mismatch"):
        phase49.create_offline_execution_audit_registry(entries=(entry_1, tampered_previous_id))

    with pytest.raises(phase49.OfflineExecutionAuditRegistryConflictError, match="audit_record_id already registered"):
        phase49.register_offline_execution_audit_record(
            registry_file=registry_file,
            audit_record=record_1,
            root_directory=root,
            metadata={"labels": {"alpha", "beta", "late"}},
        )

    with pytest.raises(phase49.OfflineExecutionAuditRegistryConflictError, match="execution_attempt_id already registered"):
        phase49.register_offline_execution_audit_record(
            registry_file=registry_file,
            audit_record=record_3,
            root_directory=root,
            metadata={"labels": {"alpha", "beta"}},
        )

    assert phase49.find_entry_by_audit_record_id(registry, entry_1.audit_record_id) == entry_1
    assert phase49.find_entry_by_execution_attempt_id(registry, entry_2.execution_attempt_id) == entry_2


def test_phase49_registry_validates_persistence_round_trip_and_failure_cases(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    registry_file = Path("records") / "audit-registry.json"
    record_1 = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )
    entry_1 = phase49.register_offline_execution_audit_record(
        registry_file=registry_file,
        audit_record=record_1,
        root_directory=root,
        registered_at_utc=SYNTHETIC_CREATED_AT_UTC,
        metadata={"labels": {"alpha", "beta"}},
    )
    registry_path = root / registry_file
    original_text = registry_path.read_text(encoding="utf-8")

    loaded = phase49.load_offline_execution_audit_registry(registry_file=registry_file, root_directory=root)
    verified = phase49.verify_offline_execution_audit_registry(loaded)
    assert verified.registry_hash == loaded.registry_hash
    assert verified.entries[0].registry_entry_id == entry_1.registry_entry_id
    assert phase49.list_registry_entries(loaded)[0].as_dict() == entry_1.as_dict()
    assert phase49.find_entry_by_audit_record_id(loaded, entry_1.audit_record_id).as_dict() == entry_1.as_dict()
    assert phase49.find_entry_by_execution_attempt_id(loaded, entry_1.execution_attempt_id).as_dict() == entry_1.as_dict()

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["registry_hash"] = "0" * 64
    registry_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(phase49.OfflineExecutionAuditRegistryIntegrityError, match="registry_hash mismatch"):
        phase49.load_offline_execution_audit_registry(registry_file=registry_file, root_directory=root)

    payload = json.loads(original_text)
    payload["entries"][0]["registry_entry_hash"] = "1" * 64
    registry_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(phase49.OfflineExecutionAuditRegistryIntegrityError, match="registry_entry_hash mismatch"):
        phase49.load_offline_execution_audit_registry(registry_file=registry_file, root_directory=root)

    registry_path.write_text("", encoding="utf-8")
    with pytest.raises(phase49.OfflineExecutionAuditRegistryValidationError, match="empty"):
        phase49.load_offline_execution_audit_registry(registry_file=registry_file, root_directory=root)

    registry_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(phase49.OfflineExecutionAuditRegistryValidationError, match="invalid JSON"):
        phase49.load_offline_execution_audit_registry(registry_file=registry_file, root_directory=root)

    registry_path.write_text(original_text, encoding="utf-8")

    def _fail(*args, **kwargs):
        raise OSError("simulated write failure")

    monkeypatch.setattr(phase49.os, "replace", _fail, raising=True)
    registry = phase49.create_offline_execution_audit_registry(
        entries=(entry_1,),
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        updated_at_utc=SYNTHETIC_CREATED_AT_UTC_OFFSET,
        metadata={"labels": {"alpha", "beta", "late"}},
    )
    with pytest.raises(phase49.OfflineExecutionAuditRegistryPersistenceError, match="failed to write"):
        phase49.save_offline_execution_audit_registry(
            registry_file=registry_file,
            registry=registry,
            root_directory=root,
        )


@pytest.mark.parametrize(
    "root_directory",
    [
        Path(r"C:\temp\.pytest_tmp\root"),
        Path("C:/temp/.pytest_tmp/root"),
        Path("/tmp/.pytest_tmp/root"),
        Path("relative/.pytest_tmp/root"),
        Path(".pytest_tmp/root"),
        Path(r"nested\folder\.pytest_tmp\root"),
        Path("nested/folder/.pytest_tmp/root"),
    ],
)
def test_phase49_rejects_pytest_tmp_roots_and_loads(root_directory):
    record = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )
    with pytest.raises(phase49.OfflineExecutionAuditRegistryValidationError, match=r"\.pytest_tmp"):
        phase49.register_offline_execution_audit_record(
            registry_file=Path("records") / "audit.json",
            audit_record=record,
            root_directory=root_directory,
        )
    with pytest.raises(phase49.OfflineExecutionAuditRegistryValidationError, match=r"\.pytest_tmp"):
        phase49.load_offline_execution_audit_registry(
            registry_file=Path("records") / "audit.json",
            root_directory=root_directory,
        )


@pytest.mark.parametrize(
    "registry_file",
    [
        Path(r"C:\escape.json"),
        Path(r"C:\escape.json"),
        Path(r"D:\folder\file.json"),
        Path("//server/share/file.json"),
        Path(r"\\server\share\file.json"),
        Path("/tmp/file.json"),
        Path("../file.json"),
        Path("folder/../../file.json"),
        Path("~/file.json"),
    ],
)
def test_phase49_rejects_escape_paths(registry_file):
    record = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )
    with pytest.raises(phase49.OfflineExecutionAuditRegistryValidationError):
        phase49.register_offline_execution_audit_record(
            registry_file=registry_file,
            audit_record=record,
            root_directory=Path.cwd(),
        )


def test_phase49_rejects_divergent_entry_and_registry_payloads():
    record = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )
    entry = phase49.build_offline_execution_audit_registry_entry(
        audit_record=record,
        entry_number=1,
        metadata={"labels": {"alpha", "beta"}},
    )
    payload = entry.as_dict()
    payload["registry_entry_id"] = "0" * 64
    with pytest.raises(phase49.OfflineExecutionAuditRegistryIntegrityError, match="registry_entry_id mismatch"):
        phase49.OfflineExecutionAuditRegistryEntry.from_dict(payload)

    registry = phase49.create_offline_execution_audit_registry(
        entries=(entry,),
        metadata={"labels": {"alpha", "beta"}},
    )
    payload = registry.as_dict()
    payload["registry_hash"] = "0" * 64
    with pytest.raises(phase49.OfflineExecutionAuditRegistryIntegrityError, match="registry_hash mismatch"):
        phase49.OfflineExecutionAuditRegistry.from_dict(payload)

    payload = registry.as_dict()
    payload["entries"][0]["previous_entry_id"] = "0" * 64
    with pytest.raises(phase49.OfflineExecutionAuditRegistryIntegrityError, match="previous_entry_id mismatch"):
        phase49.OfflineExecutionAuditRegistry.from_dict(payload)


def test_phase49_registry_rejects_invalid_schema_and_unexpected_fields():
    record = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )
    entry_payload = phase49.build_offline_execution_audit_registry_entry(
        audit_record=record,
        entry_number=1,
        metadata={"labels": {"alpha", "beta"}},
    ).as_dict()
    entry_payload["schema_version"] = 2
    with pytest.raises(phase49.OfflineExecutionAuditRegistryValidationError, match="schema_version must be 1"):
        phase49.OfflineExecutionAuditRegistryEntry.from_dict(entry_payload)

    entry_payload = phase49.build_offline_execution_audit_registry_entry(
        audit_record=record,
        entry_number=1,
        metadata={"labels": {"alpha", "beta"}},
    ).as_dict()
    entry_payload["unexpected"] = True
    with pytest.raises(phase49.OfflineExecutionAuditRegistryValidationError, match="unexpected offline execution audit registry entry fields"):
        phase49.OfflineExecutionAuditRegistryEntry.from_dict(entry_payload)

    registry_payload = phase49.create_offline_execution_audit_registry(
        entries=(),
        metadata={"labels": {"alpha", "beta"}},
    ).as_dict()
    registry_payload["schema_version"] = 2
    with pytest.raises(phase49.OfflineExecutionAuditRegistryValidationError, match="schema_version must be 1"):
        phase49.OfflineExecutionAuditRegistry.from_dict(registry_payload)

    registry_payload = phase49.create_offline_execution_audit_registry(
        entries=(),
        metadata={"labels": {"alpha", "beta"}},
    ).as_dict()
    registry_payload["unexpected"] = True
    with pytest.raises(phase49.OfflineExecutionAuditRegistryValidationError, match="unexpected offline execution audit registry fields"):
        phase49.OfflineExecutionAuditRegistry.from_dict(registry_payload)


def test_phase49_registry_is_not_operational(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest, "run_first_offline_okx_backtest_experiment", _forbidden, raising=True)
    monkeypatch.setattr(backtest.LeakFreeBacktestEngine, "run", _forbidden, raising=True)
    record = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )
    registry_file = Path("records") / "audit-registry.json"
    entry = phase49.register_offline_execution_audit_record(
        registry_file=registry_file,
        audit_record=record,
        root_directory=tmp_path,
        metadata={"labels": {"alpha", "beta"}},
    )
    registry = phase49.load_offline_execution_audit_registry(registry_file=registry_file, root_directory=tmp_path)
    assert registry.entries[0].as_dict() == entry.as_dict()
    assert registry.entry_count == 1
    assert registry.metadata["labels"] == ("alpha", "beta")
