from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import market_data.offline_execution_audit_record as phase48
import market_data.offline_research_backtest as phase38
import market_data.offline_research_canonical_evidence_fixture as phase44
import market_data.offline_research_execution_authorization as phase45
import market_data.offline_research_execution_envelope as phase46
import market_data.offline_research_experiment_contract as phase40
import market_data.offline_research_experiment_execution_plan as phase43
import market_data.offline_research_experiment_execution_registry as phase42
import market_data.offline_research_experiment_registry as phase41
import market_data.offline_research_neutral_executor as phase47

CANONICAL_AUTHORIZATION_ISSUED_AT_UTC = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
CANONICAL_ENVELOPE_CREATED_AT_UTC = datetime(2026, 8, 1, 12, 0, 1, tzinfo=timezone.utc)
CANONICAL_REQUEST_CREATED_AT_UTC = datetime(2026, 8, 1, 12, 0, 2, tzinfo=timezone.utc)
CANONICAL_RESULT_STARTED_AT_UTC = datetime(2026, 8, 1, 12, 0, 3, tzinfo=timezone.utc)
CANONICAL_RESULT_FINISHED_AT_UTC = datetime(2026, 8, 1, 12, 0, 4, tzinfo=timezone.utc)
SYNTHETIC_CREATED_AT_UTC = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)
SYNTHETIC_CREATED_AT_UTC_OFFSET = datetime(2026, 8, 4, 9, 0, 0, tzinfo=timezone(timedelta(hours=-3)))




def _fresh_artifact_reference(
    verification: phase44.CanonicalOfflineResearchEvidenceVerification,
) -> phase38.OkxOfflineResearchArtifactReference:
    resolution = phase38.OkxPersistentResearchArtifactResolution(
        registry_file=verification.artifact_reference.resolution.registry_file,
        dataset_file=verification.artifact_reference.resolution.dataset_file,
        manifest_file=verification.artifact_reference.resolution.manifest_file,
        registry_report=verification.registry_report,
        dataset_report=dict(verification.artifact_reference.resolution.dataset_report),
    )
    return phase38.resolve_okx_offline_research_artifact_reference(resolution=resolution)


def _fresh_bundle(canonical_runtime_bundle: dict[str, object]) -> SimpleNamespace:
    verification = canonical_runtime_bundle["verification"]
    assert isinstance(verification, phase44.CanonicalOfflineResearchEvidenceVerification)
    fresh_verification = phase44.verify_canonical_offline_research_evidence_fixture(
        verification.fixture.fixture_directory
    )
    return SimpleNamespace(
        verification=fresh_verification,
        artifact_reference=_fresh_artifact_reference(fresh_verification),
        experiment_contract=phase40.build_offline_research_experiment_contract(
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
        experiment_registry=phase41.OfflineResearchExperimentRegistry.from_dict(
            fresh_verification.experiment_registry.as_dict()
        ),
        execution_registry=phase42.OfflineResearchExperimentExecutionRegistry.from_dict(
            fresh_verification.execution_registry.as_dict()
        ),
        execution_plan=phase43.OfflineResearchExperimentExecutionPlan.from_dict(
            fresh_verification.execution_plan_registry.plans[0].as_dict()
        ),
        execution_plan_registry=phase43.OfflineResearchExperimentExecutionPlanRegistry.from_dict(
            fresh_verification.execution_plan_registry.as_dict()
        ),
        authorization=phase45.OfflineResearchExecutionAuthorization.from_dict(
            canonical_runtime_bundle["authorization"].as_dict()
        ),
        envelope=phase46.OfflineResearchExecutionEnvelope.from_dict(
            canonical_runtime_bundle["envelope"].as_dict()
        ),
        result=phase47.OfflineResearchNeutralExecutionResult.from_dict(
            canonical_runtime_bundle["result"].as_dict()
        ),
    )


def _synthetic_provenance(*, label_order: tuple[str, ...], group_order: tuple[tuple[str, ...], ...]) -> dict[str, object]:
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
            "experiment_id": "synthetic_experiment_48",
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
    note: str = "",
) -> phase48.OfflineExecutionAuditRecord:
    provenance = _synthetic_provenance(label_order=label_order, group_order=group_order)
    user_metadata = _synthetic_user_metadata(label_order=label_order, group_order=group_order)
    if note:
        user_metadata["note"] = note
    return phase48.OfflineExecutionAuditRecord(
        schema_version=phase48.OFFLINE_EXECUTION_AUDIT_RECORD_SCHEMA_VERSION,
        lineage_hash=phase48._hash_payload(provenance),
        artifact_reference_id="c" * 64,
        experiment_id="synthetic_experiment_48",
        experiment_contract_hash="d" * 64,
        execution_id="synthetic-execution",
        execution_attempt_number=1,
        execution_attempt_id="synthetic-execution:1",
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


def _build_audit_record(
    canonical_runtime_bundle: dict[str, object],
    *,
    created_at_utc: datetime,
    metadata: dict[str, object],
) -> phase48.OfflineExecutionAuditRecord:
    fresh = _fresh_bundle(canonical_runtime_bundle)
    return phase48.build_offline_execution_audit_record(
        artifact_reference=fresh.artifact_reference,
        experiment_contract=fresh.experiment_contract,
        experiment_registry=fresh.experiment_registry,
        execution_registry=fresh.execution_registry,
        execution_plan=fresh.execution_plan,
        evidence=fresh.verification,
        authorization=fresh.authorization,
        envelope=fresh.envelope,
        result=fresh.result,
        created_at_utc=created_at_utc,
        metadata=metadata,
    )


def _forbidden(*args, **kwargs):
    raise AssertionError("unexpected operational or legacy call")


def test_phase48_builds_stable_record_from_real_chain_and_preserves_immutability(
    canonical_runtime_bundle: dict[str, object],
    canonical_verification: phase44.CanonicalOfflineResearchEvidenceVerification,
):
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

    record_a = _build_audit_record(
        canonical_runtime_bundle,
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        metadata=metadata_source,
    )
    record_b = _build_audit_record(
        canonical_runtime_bundle,
        created_at_utc=SYNTHETIC_CREATED_AT_UTC_OFFSET,
        metadata=metadata_equivalent,
    )

    execution_record = canonical_verification.execution_registry.registration_by_execution_hash(
        canonical_verification.execution_plan_registry.plans[0].execution_hash
    )

    assert record_a.audit_record_id == record_b.audit_record_id
    assert record_a.audit_record_hash == record_b.audit_record_hash
    assert record_a.lineage_hash == record_b.lineage_hash
    assert record_a.artifact_reference_id == canonical_verification.artifact_reference.registry_report.artifact_id
    assert record_a.experiment_id == canonical_verification.experiment_contract.experiment_id
    assert record_a.execution_id == execution_record.execution_id
    assert record_a.execution_attempt_number == execution_record.attempt_number
    assert record_a.execution_attempt_id == f"{execution_record.execution_id}:{execution_record.attempt_number}"
    assert record_a.metadata["user_metadata"]["labels"] == frozenset({"alpha", "beta"})
    assert record_a.metadata["user_metadata"]["nested"]["inner_labels"] == frozenset({"one", "two"})
    assert record_a.metadata["user_metadata"]["nested"]["groups"] == frozenset(
        {frozenset({"alpha"}), frozenset({"delta", "gamma"})}
    )
    assert record_a.as_dict()["created_at_utc"] == "2026-08-04T12:00:00Z"
    assert record_b.as_dict()["created_at_utc"] == "2026-08-04T12:00:00Z"
    assert json.dumps(record_a.as_dict(), sort_keys=True, separators=(",", ":"))

    with pytest.raises(TypeError):
        record_a.metadata["user_metadata"]["labels"] = frozenset({"gamma"})  # type: ignore[index]
    with pytest.raises(AttributeError):
        record_a.metadata["user_metadata"]["labels"].add("gamma")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        record_a.metadata["user_metadata"]["nested"]["inner_labels"].add("gamma")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        record_a.metadata["user_metadata"]["nested"]["groups"].add(frozenset({"gamma"}))  # type: ignore[attr-defined]

    metadata_source["labels"].add("late")  # type: ignore[attr-defined]
    metadata_source["nested"]["inner_labels"].add("late")  # type: ignore[attr-defined]
    metadata_source["nested"]["groups"].add(frozenset({"late"}))  # type: ignore[attr-defined]
    canonical_verification.artifact_reference.resolution.dataset_report["dataset_hash"] = "0" * 64

    assert record_a.metadata["user_metadata"]["labels"] == frozenset({"alpha", "beta"})
    assert record_a.metadata["user_metadata"]["nested"]["inner_labels"] == frozenset({"one", "two"})
    assert record_a.metadata["provenance"]["artifact_reference"]["dataset_report"]["dataset_hash"] != "0" * 64

    snapshot = record_a.as_dict()
    snapshot["metadata"]["user_metadata"]["labels"] = ("changed",)
    assert record_a.as_dict()["metadata"]["user_metadata"]["labels"] == ["alpha", "beta"]

    root_directory = canonical_runtime_bundle["verification"].fixture.fixture_directory
    record_file = Path("phase48") / "offline-execution-audit-record.json"
    saved = phase48.save_offline_execution_audit_record(
        record_file=record_file,
        record=record_a,
        root_directory=root_directory,
    )
    loaded = phase48.load_offline_execution_audit_record(
        record_file=record_file,
        root_directory=root_directory,
    )
    saved_again = phase48.save_offline_execution_audit_record(
        record_file=record_file,
        record=record_a,
        root_directory=root_directory,
    )

    assert saved.as_dict() == record_a.as_dict()
    assert loaded.as_dict() == record_a.as_dict()
    assert saved_again.as_dict() == record_a.as_dict()
    assert (root_directory / record_file).read_text(encoding="utf-8") == json.dumps(
        record_a.as_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def test_phase48_serializes_sets_and_frozensets_deterministically_across_order_and_timezone():
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

    assert record_a.audit_record_id == record_b.audit_record_id
    assert record_a.audit_record_hash == record_b.audit_record_hash
    assert record_a.lineage_hash == record_b.lineage_hash
    assert record_a.as_dict()["created_at_utc"] == "2026-08-04T12:00:00Z"
    assert record_b.as_dict()["created_at_utc"] == "2026-08-04T12:00:00Z"
    assert json.dumps(record_a.as_dict(), sort_keys=True, separators=(",", ":"))


def test_phase48_serialization_is_stable_across_pythonhashseed(tmp_path):
    script = r"""
import json
from datetime import datetime, timezone
import market_data.offline_execution_audit_record as phase48

provenance = {
    "artifact_reference": {
        "artifact_id": "a" * 64,
        "provider_name": "OKX",
        "market_type": "spot",
        "instrument": "BTC-USDT",
        "symbol": "BTCUSDT",
        "interval": "1H",
        "labels": {"beta", "alpha"},
        "nested": {"groups": {frozenset({"delta", "gamma"}), frozenset({"epsilon"})}},
    },
    "experiment_contract": {
        "experiment_id": "synthetic_experiment_48",
        "strategy_contract": {"strategy_id": "baseline_a_okx_btc_usdt_1h_research", "contract_hash": "b" * 64},
        "window": {"start": "2026-08-04T00:00:00Z", "end": "2026-08-05T00:00:00Z"},
    },
    "execution_registry": {
        "execution_id": "synthetic-execution",
        "attempts": {frozenset({"attempt-2", "attempt-3"}), frozenset({"attempt-1"})},
    },
    "result": {"status": "SUCCEEDED", "notes": ["offline", "audit"]},
}
record = phase48.OfflineExecutionAuditRecord(
    schema_version=phase48.OFFLINE_EXECUTION_AUDIT_RECORD_SCHEMA_VERSION,
    lineage_hash=phase48._hash_payload(provenance),
    artifact_reference_id="c" * 64,
    experiment_id="synthetic_experiment_48",
    experiment_contract_hash="d" * 64,
    execution_id="synthetic-execution",
    execution_attempt_number=1,
    execution_attempt_id="synthetic-execution:1",
    execution_plan_hash="e" * 64,
    evidence_hash="f" * 64,
    authorization_hash="1" * 64,
    envelope_hash="2" * 64,
    neutral_execution_id="3" * 64,
    result_hash="4" * 64,
    created_at_utc=datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc),
    metadata={
        "provenance": provenance,
        "user_metadata": {
            "labels": {"beta", "alpha"},
            "nested": {"inner_labels": {"two", "one"}, "groups": {frozenset({"gamma", "delta"}), frozenset({"epsilon"})}},
        },
    },
)
print(json.dumps({
    "audit_record_id": record.audit_record_id,
    "audit_record_hash": record.audit_record_hash,
    "as_dict": record.as_dict(),
}, sort_keys=True, separators=(",", ":")))
"""
    outputs: list[str] = []
    for seed in ("1", "2"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(completed.stdout.strip())
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize(
    ("field", "value_factory", "expected_message"),
    [
        ("schema_version", lambda payload: 2, "schema_version must be 1"),
        ("lineage_hash", lambda payload: payload.pop("lineage_hash"), "offline execution audit record is incomplete"),
        ("unexpected", lambda payload: payload.__setitem__("unexpected", True), "unexpected offline execution audit record fields"),
        ("execution_id", lambda payload: payload.__setitem__("execution_id", 123), "execution_id is required"),
        ("execution_attempt_number", lambda payload: payload.__setitem__("execution_attempt_number", True), "execution_attempt_number must be an integer"),
        ("created_at_utc", lambda payload: payload.__setitem__("created_at_utc", "2026-08-04T12:00:00"), "timezone-aware UTC datetime"),
        ("nan", lambda payload: payload["metadata"]["user_metadata"].__setitem__("nan", float("nan")), "payload is not serializable"),
        ("inf", lambda payload: payload["metadata"]["user_metadata"].__setitem__("inf", float("inf")), "payload is not serializable"),
    ],
)
def test_phase48_rejects_invalid_record_payloads(field, value_factory, expected_message):
    record = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )
    payload = copy.deepcopy(record.as_dict())
    if field == "schema_version":
        payload["schema_version"] = value_factory(payload)
    elif field == "unexpected":
        value_factory(payload)
    elif field == "lineage_hash":
        value_factory(payload)
    elif field == "execution_id":
        value_factory(payload)
    elif field == "execution_attempt_number":
        value_factory(payload)
    elif field == "created_at_utc":
        value_factory(payload)
    elif field in {"nan", "inf"}:
        value_factory(payload)

    with pytest.raises(phase48.OfflineExecutionAuditRecordError, match=expected_message):
        phase48.OfflineExecutionAuditRecord.from_dict(payload)


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
def test_phase48_rejects_pytest_tmp_roots_and_loads(root_directory):
    record = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )
    with pytest.raises(phase48.OfflineExecutionAuditRecordValidationError, match=r"\.pytest_tmp"):
        phase48.save_offline_execution_audit_record(
            record_file=Path("audit.json"),
            record=record,
            root_directory=root_directory,
        )
    with pytest.raises(phase48.OfflineExecutionAuditRecordValidationError, match=r"\.pytest_tmp"):
        phase48.load_offline_execution_audit_record(
            record_file=Path("audit.json"),
            root_directory=root_directory,
        )


@pytest.mark.parametrize(
    "root_directory",
    [
        Path("safe/my.pytest_tmp_backup/root"),
        Path("safe/pytest_tmp/root"),
        Path("safe/.pytest_tmp_backup/root"),
        Path("safe/folder.pytest_tmp/root"),
    ],
)
def test_phase48_allows_similar_names_without_exact_segment(root_directory, tmp_path):
    record = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )
    record_file = Path("records") / "audit.json"
    root = tmp_path / root_directory

    saved = phase48.save_offline_execution_audit_record(
        record_file=record_file,
        record=record,
        root_directory=root,
    )
    loaded = phase48.load_offline_execution_audit_record(
        record_file=record_file,
        root_directory=root,
    )

    assert saved.as_dict() == record.as_dict()
    assert loaded.as_dict() == record.as_dict()


def test_phase48_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable in this environment: {exc}")

    record = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )
    with pytest.raises(phase48.OfflineExecutionAuditRecordValidationError, match="must remain within the authorized root"):
        phase48.save_offline_execution_audit_record(
            record_file=Path("linked") / "audit.json",
            record=record,
            root_directory=root,
        )


def test_phase48_save_is_idempotent_and_conflict_closed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    record_file = Path("records") / "audit.json"
    record_one = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )
    record_two = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
        note="conflict",
    )

    saved = phase48.save_offline_execution_audit_record(
        record_file=record_file,
        record=record_one,
        root_directory=root,
    )
    original_text = (root / record_file).read_text(encoding="utf-8")
    saved_again = phase48.save_offline_execution_audit_record(
        record_file=record_file,
        record=record_one,
        root_directory=root,
    )

    assert saved.as_dict() == record_one.as_dict()
    assert saved_again.as_dict() == record_one.as_dict()
    assert (root / record_file).read_text(encoding="utf-8") == original_text

    with pytest.raises(phase48.OfflineExecutionAuditRecordConflictError, match="audit_record_id already exists and differs"):
        phase48.save_offline_execution_audit_record(
            record_file=record_file,
            record=record_two,
            root_directory=root,
        )


def test_phase48_atomic_write_failure_cleans_temp_and_preserves_existing_file(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    record_file = Path("records") / "audit.json"
    existing = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("alpha", "beta"),
        group_order=(("gamma", "delta"), ("epsilon",)),
    )
    replacement = _synthetic_record(
        created_at_utc=SYNTHETIC_CREATED_AT_UTC,
        label_order=("beta", "alpha"),
        group_order=(("epsilon",), ("delta", "gamma")),
    )
    path = root / record_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("original-content", encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(phase48.os, "replace", _boom, raising=True)

    with pytest.raises(phase48.OfflineExecutionAuditRecordPersistenceError, match="failed to write offline execution audit record atomically"):
        phase48._write_json_atomic(path, replacement.as_dict())

    assert path.read_text(encoding="utf-8") == "original-content"
    assert not any(candidate.suffix == ".tmp" for candidate in path.parent.iterdir())


@pytest.mark.parametrize(
    ("mutator", "expected_message"),
    [
        (lambda bundle: object.__setattr__(bundle.artifact_reference, "dataset_report", dict(bundle.artifact_reference.dataset_report, dataset_hash="0" * 64)), "artifact reference dataset_hash mismatch"),
            (lambda bundle: object.__setattr__(bundle.experiment_contract, "experiment_version", "phase40_offline_experiment_contract_v1_alt"), "experiment contract snapshot mismatch"),
            (lambda bundle: object.__setattr__(bundle.experiment_registry.records[0], "experiment_version", "phase41_offline_experiment_registry_v1_alt"), "experiment_registry_hash mismatch"),
        (lambda bundle: object.__setattr__(bundle.execution_plan, "plan_hash", "0" * 64), "execution_plan_hash mismatch"),
        (lambda bundle: object.__setattr__(bundle.authorization, "plan_hash", "0" * 64), "authorization plan_hash mismatch"),
        (lambda bundle: object.__setattr__(bundle.envelope, "authorization_hash", "0" * 64), "envelope authorization_hash mismatch"),
        (lambda bundle: object.__setattr__(bundle.result, "envelope_id", "0" * 64), "result envelope_id mismatch"),
        (lambda bundle: object.__setattr__(bundle.result, "execution_id", "synthetic-execution-alt"), "result execution_id mismatch"),
        (lambda bundle: object.__setattr__(bundle.result, "execution_number", 2), "result execution_number mismatch"),
        (lambda bundle: object.__setattr__(bundle.result, "strategy_id", "different-strategy"), "result strategy_id mismatch"),
        (lambda bundle: object.__setattr__(bundle.result, "strategy_version", "different-version"), "result strategy_version mismatch"),
        (lambda bundle: object.__setattr__(bundle.result, "strategy_fingerprint", "0" * 64), "result strategy_fingerprint mismatch"),
        (lambda bundle: object.__setattr__(bundle.result, "result_hash", "0" * 64), "result_hash mismatch"),
        (lambda bundle: object.__setattr__(bundle.execution_registry.registration_by_execution_hash(bundle.execution_plan.execution_hash), "attempt_number", 2), "result execution_number mismatch"),
    ],
)
def test_phase48_rejects_divergent_chain_links(canonical_runtime_bundle, mutator, expected_message):
    bundle = _fresh_bundle(canonical_runtime_bundle)
    if expected_message == "result execution_number mismatch":
        execution_record = bundle.execution_registry.registration_by_execution_hash(bundle.execution_plan.execution_hash)
        object.__setattr__(execution_record, "attempt_number", 2)
        object.__setattr__(bundle.execution_plan, "execution_registration_snapshot", dict(execution_record.as_dict()))
    else:
        mutator(bundle)

    with pytest.raises(phase48.OfflineExecutionAuditRecordError, match=expected_message):
        phase48.build_offline_execution_audit_record(
            artifact_reference=bundle.artifact_reference,
            experiment_contract=bundle.experiment_contract,
            experiment_registry=bundle.experiment_registry,
            execution_registry=bundle.execution_registry,
            execution_plan=bundle.execution_plan,
            evidence=bundle.verification,
            authorization=bundle.authorization,
            envelope=bundle.envelope,
            result=bundle.result,
            created_at_utc=SYNTHETIC_CREATED_AT_UTC,
            metadata={
                "labels": {"alpha", "beta"},
                "nested": {"groups": {frozenset({"gamma", "delta"})}},
            },
        )
