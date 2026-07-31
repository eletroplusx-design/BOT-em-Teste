from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

import market_data.offline_research_backtest as backtest
import market_data.offline_research_experiment_authorization as authorization
import market_data.offline_research_experiment_contract as experiment_contract
import market_data.offline_research_experiment_registry as experiment_registry
import market_data.offline_research_strategy_compatibility as compatibility
import market_data.okx_historical as okx
import market_data.research_artifact_registry as registry
import market_data.research_artifact_registry_verification as verification
from domain.serialization import serialize_value
from strategies.baseline_a_okx_btc_usdt_research import build_baseline_a_okx_btc_usdt_research_contract

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

EXPERIMENT_CREATED_AT_UTC = datetime(2026, 7, 27, 16, 31, 35, tzinfo=timezone.utc)
EXPERIMENT_REGISTERED_AT_UTC = datetime(2026, 7, 27, 16, 31, 36, tzinfo=timezone.utc)
REFERENCE_DECIDED_AT_UTC = datetime(2026, 7, 27, 16, 31, 34, tzinfo=timezone.utc)
AUTHORIZATION_ISSUED_AT_UTC = datetime(2026, 7, 27, 16, 31, 33, tzinfo=timezone.utc)
VIRTUAL_RESEARCH_ARTIFACT_REF = "artifact://okx/phase40/research-only"
ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)


def _build_persistent_artifact(root: Path) -> dict[str, Path]:
    artifact_dir = root / "phase19c-okx-20260727T000000Z" / "okx"
    registry_dir = root / "phase20a-okx-research-artifact-registry"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    registry_dir.mkdir(parents=True, exist_ok=True)
    if not ACTUAL_REGISTRY_FILE.exists() or not ACTUAL_ARTIFACT_DIR.exists():
        pytest.skip("persistent artifact is not available in this environment")

    shutil.copytree(ACTUAL_ARTIFACT_DIR, artifact_dir, dirs_exist_ok=True)
    copied_dataset_file = artifact_dir / okx.OKX_HISTORICAL_DATASET_CANDLES_FILENAME
    copied_manifest_file = artifact_dir / okx.OKX_HISTORICAL_MANIFEST_FILENAME
    loaded = okx.load_okx_historical_dataset(dataset_file=copied_dataset_file, manifest_file=copied_manifest_file)

    registry_file = registry_dir / "okx-research-artifact-registry.json"
    registry_entry = registry.ResearchArtifactRegistryEntry(
        registered_at_utc=datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc),
        external_artifact_ref=artifact_dir.as_posix(),
        dataset_sha256=loaded.manifest.dataset_hash,
        manifest_sha256=sha256(copied_manifest_file.read_bytes()).hexdigest(),
        manifest_hash=loaded.manifest.manifest_hash,
    )
    registry.save_research_artifact_registry(registry_file, registry_entry)

    return {
        "root": root,
        "artifact_dir": artifact_dir,
        "registry_file": registry_file,
        "dataset_file": copied_dataset_file,
        "manifest_file": copied_manifest_file,
    }


@pytest.fixture(scope="module")
def persistent_artifact(tmp_path_factory):
    root = tmp_path_factory.mktemp("phase41-okx-persistent-artifact")
    return _build_persistent_artifact(root)


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
        issued_at_utc=AUTHORIZATION_ISSUED_AT_UTC,
    )


def _compatibility_contract(
    auth: authorization.OfflineResearchExperimentAuthorization,
) -> compatibility.OfflineResearchStrategyCompatibilityContract:
    return compatibility.OfflineResearchStrategyCompatibilityContract(
        strategy_id="synthetic_okx_compatibility",
        strategy_version="phase41_compatibility_v1",
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


def _baseline_strategy_contract() -> tuple[
    authorization.OfflineResearchExperimentAuthorization,
    compatibility.OfflineResearchStrategyCompatibilityDecision,
    object,
]:
    auth = _verified_authorization()
    compat = _compatibility_contract(auth)
    decision = compatibility.evaluate_offline_research_strategy_compatibility(
        auth,
        compat,
        decided_at_utc=REFERENCE_DECIDED_AT_UTC,
    )
    strategy_contract = build_baseline_a_okx_btc_usdt_research_contract(auth, decision)
    return auth, decision, strategy_contract


def _qualified_reference(persistent_artifact):
    resolution = backtest.resolve_okx_persistent_artifact(
        registry_file=persistent_artifact["registry_file"],
        dataset_file=persistent_artifact["dataset_file"],
        manifest_file=persistent_artifact["manifest_file"],
    )
    reference = backtest.resolve_okx_offline_research_artifact_reference(resolution=resolution)
    return resolution, reference


def _default_extra_parameters() -> dict[str, object]:
    return {
        "safety": {
            "labels": {"offline", "research"},
            "historical_research_only": True,
            "operational_evidence": False,
            "paper_promotion_eligible": False,
        },
        "costs": {
            "entry_fee_rate": "0.0004",
            "exit_fee_rate": "0.0004",
            "spread_bps": "5",
            "slippage_bps": "5",
        },
        "notes": ["offline", "read-only"],
    }


def _build_contract(
    persistent_artifact,
    *,
    reference=None,
    strategy_contract=None,
    extra_parameters=None,
    **overrides,
):
    if reference is None:
        _, reference = _qualified_reference(persistent_artifact)
    if strategy_contract is None:
        _, _, strategy_contract = _baseline_strategy_contract()
    if extra_parameters is None:
        extra_parameters = _default_extra_parameters()
    return experiment_contract.build_offline_research_experiment_contract(
        artifact_reference=reference,
        strategy_contract=strategy_contract,
        created_at_utc=EXPERIMENT_CREATED_AT_UTC,
        extra_parameters=extra_parameters,
        **overrides,
    )


def _build_contract_with_nested_dataset_report(persistent_artifact):
    resolution, _ = _qualified_reference(persistent_artifact)
    nested_report = {
        "dataset_hash": resolution.dataset_report["dataset_hash"],
        "contract_hash": resolution.dataset_report["contract_hash"],
        "historical_research_only": True,
        "operational_evidence": False,
        "paper_promotion_eligible": False,
        "nested": {"gate": "tight"},
    }
    object.__setattr__(resolution, "dataset_report", nested_report)
    _, reference = _qualified_reference(persistent_artifact)
    object.__setattr__(reference.resolution, "dataset_report", nested_report)
    return reference


def _forbidden(*args, **kwargs):
    raise AssertionError("unexpected operational or legacy call")


def _registry_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_offline_research_experiment_registry_registers_valid_contract_and_is_read_only(
    persistent_artifact, tmp_path, monkeypatch
):
    _, reference = _qualified_reference(persistent_artifact)
    _, _, strategy_contract = _baseline_strategy_contract()
    contract = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
    )

    monkeypatch.setattr(backtest, "run_first_offline_okx_backtest_experiment", _forbidden, raising=True)
    monkeypatch.setattr(backtest.LeakFreeBacktestEngine, "run", _forbidden, raising=True)

    registry_file = tmp_path / "offline-research-experiment-registry.json"
    record = experiment_registry.register_offline_research_experiment(
        registry_file=registry_file,
        contract=contract,
        registered_at_utc=EXPERIMENT_REGISTERED_AT_UTC,
    )
    loaded = experiment_registry.load_offline_research_experiment_registry(registry_file)
    verified = experiment_registry.verify_offline_research_experiment_registry(registry_file)

    assert record.experiment_id == experiment_contract.OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_ID
    assert record.experiment_version == experiment_contract.OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_VERSION
    assert record.experiment_fingerprint == contract.contract_hash
    assert record.record_hash == loaded.records[0].record_hash
    assert loaded.record_count == 1
    assert loaded.records == experiment_registry.list_offline_research_experiment_registry_records(registry_file)
    assert loaded.records[0].contract.contract_hash == contract.contract_hash
    assert loaded.records[0].contract.artifact_reference["artifact_id"] == reference.registry_report.artifact_id
    assert loaded.records[0].artifact_reference.dataset_report["historical_research_only"] is True
    assert verified.approved is True
    assert verified.record_count == 1
    assert verified.experiment_ids == (contract.experiment_id,)
    assert verified.experiment_fingerprints == (contract.contract_hash,)
    assert loaded.contract_by_experiment_id(contract.experiment_id).contract_hash == contract.contract_hash
    assert loaded.contract_by_fingerprint(contract.contract_hash).contract_hash == contract.contract_hash

    with pytest.raises(TypeError):
        loaded.records[0].contract_snapshot["extra_parameters"]["safety"]["historical_research_only"] = False
    with pytest.raises(TypeError):
        loaded.records[0].contract_snapshot["extra_parameters"]["safety"]["labels"][0] = "changed"
    with pytest.raises(TypeError):
        loaded.records[0].artifact_reference_snapshot["dataset_report"]["historical_research_only"] = False
    with pytest.raises(TypeError):
        loaded.records[0].artifact_reference_snapshot["registry_report"]["approved"] = False


def test_offline_research_experiment_registry_persists_deterministically_for_same_input(
    persistent_artifact, tmp_path
):
    _, reference = _qualified_reference(persistent_artifact)
    _, _, strategy_contract = _baseline_strategy_contract()
    contract = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
    )

    first_registry_file = tmp_path / "registry-a.json"
    second_registry_file = tmp_path / "registry-b.json"
    first_record = experiment_registry.register_offline_research_experiment(
        registry_file=first_registry_file,
        contract=contract,
        registered_at_utc=EXPERIMENT_REGISTERED_AT_UTC,
    )
    second_record = experiment_registry.register_offline_research_experiment(
        registry_file=second_registry_file,
        contract=contract,
        registered_at_utc=EXPERIMENT_REGISTERED_AT_UTC,
    )

    assert first_record.record_hash == second_record.record_hash
    assert _registry_text(first_registry_file) == _registry_text(second_registry_file)


def test_offline_research_experiment_registry_rejects_duplicate_fingerprint_and_experiment_id_conflict(
    persistent_artifact, tmp_path
):
    _, reference = _qualified_reference(persistent_artifact)
    _, _, strategy_contract = _baseline_strategy_contract()
    contract = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
    )
    registry_file = tmp_path / "offline-research-experiment-registry.json"

    experiment_registry.register_offline_research_experiment(
        registry_file=registry_file,
        contract=contract,
        registered_at_utc=EXPERIMENT_REGISTERED_AT_UTC,
    )

    with pytest.raises(
        experiment_registry.OfflineResearchExperimentRegistryConflictError,
        match="experiment_fingerprint already registered",
    ):
        experiment_registry.register_offline_research_experiment(
            registry_file=registry_file,
            contract=contract,
            registered_at_utc=EXPERIMENT_REGISTERED_AT_UTC,
        )

    divergent_contract = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
        extra_parameters={
            "safety": {
                "labels": {"offline", "research", "variant"},
                "historical_research_only": True,
                "operational_evidence": False,
                "paper_promotion_eligible": False,
            },
            "costs": {
                "entry_fee_rate": "0.0004",
                "exit_fee_rate": "0.0004",
                "spread_bps": "5",
                "slippage_bps": "5",
            },
            "notes": ["offline", "variant"],
        },
    )
    with pytest.raises(
        experiment_registry.OfflineResearchExperimentRegistryConflictError,
        match="experiment_id already registered",
    ):
        experiment_registry.register_offline_research_experiment(
            registry_file=registry_file,
            contract=divergent_contract,
            registered_at_utc=EXPERIMENT_REGISTERED_AT_UTC,
        )


def test_offline_research_experiment_registry_rejects_tampered_registry_file(
    persistent_artifact, tmp_path
):
    _, reference = _qualified_reference(persistent_artifact)
    _, _, strategy_contract = _baseline_strategy_contract()
    contract = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
    )
    registry_file = tmp_path / "offline-research-experiment-registry.json"
    experiment_registry.register_offline_research_experiment(
        registry_file=registry_file,
        contract=contract,
        registered_at_utc=EXPERIMENT_REGISTERED_AT_UTC,
    )

    payload = json.loads(registry_file.read_text(encoding="utf-8"))
    payload["registry_hash"] = "0" * 64
    registry_file.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    with pytest.raises(experiment_registry.OfflineResearchExperimentRegistryIntegrityError, match="registry_hash mismatch"):
        experiment_registry.load_offline_research_experiment_registry(registry_file)

    payload = json.loads(registry_file.read_text(encoding="utf-8"))
    payload["registry_hash"] = ""
    payload["records"][0]["record_hash"] = ""
    payload["records"][0]["contract_snapshot"]["paper_trading_enabled"] = True
    payload["records"][0]["record_hash"] = sha256(
        json.dumps(
            serialize_value(
                {
                    key: value
                    for key, value in payload["records"][0].items()
                    if key != "record_hash"
                }
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    payload["registry_hash"] = sha256(
        json.dumps(
            serialize_value(
                {
                    key: value
                    for key, value in payload.items()
                    if key != "registry_hash"
                }
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    registry_file.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    with pytest.raises(
        experiment_registry.OfflineResearchExperimentRegistryValidationError,
        match="offline research experiment contract snapshot is invalid",
    ):
        experiment_registry.load_offline_research_experiment_registry(registry_file)


@pytest.mark.parametrize(
    ("field_name", "value", "expected"),
    [
        ("paper_trading_enabled", True, "paper_trading_enabled must be false"),
        ("live_trading_enabled", True, "live_trading_enabled must be false"),
        ("execution_enabled", True, "execution_enabled must be false"),
        ("order_submission_enabled", True, "order_submission_enabled must be false"),
        ("credentials_required", True, "credentials_required must be false"),
        ("exchange_api_enabled", True, "exchange_api_enabled must be false"),
        ("download_enabled", True, "download_enabled must be false"),
        ("ingestion_enabled", True, "ingestion_enabled must be false"),
    ],
)
def test_offline_research_experiment_registry_rejects_prohibited_operational_fields(
    persistent_artifact,
    tmp_path,
    field_name,
    value,
    expected,
):
    _, reference = _qualified_reference(persistent_artifact)
    _, _, strategy_contract = _baseline_strategy_contract()
    contract = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
    )
    object.__setattr__(contract, field_name, value)
    registry_file = tmp_path / "offline-research-experiment-registry.json"

    with pytest.raises(experiment_registry.OfflineResearchExperimentRegistryValidationError, match=expected):
        experiment_registry.register_offline_research_experiment(
            registry_file=registry_file,
            contract=contract,
            registered_at_utc=EXPERIMENT_REGISTERED_AT_UTC,
        )


def test_offline_research_experiment_registry_preserves_source_independence_and_nested_snapshot_immutability(
    persistent_artifact, tmp_path
):
    _, _, strategy_contract = _baseline_strategy_contract()
    resolution, reference = _qualified_reference(persistent_artifact)
    resolution.dataset_report["historical_research_only"] = True
    reference = backtest.resolve_okx_offline_research_artifact_reference(resolution=resolution)
    extra_parameters = _default_extra_parameters()
    contract = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
        extra_parameters=extra_parameters,
    )
    registry_file = tmp_path / "offline-research-experiment-registry.json"
    record = experiment_registry.register_offline_research_experiment(
        registry_file=registry_file,
        contract=contract,
        registered_at_utc=EXPERIMENT_REGISTERED_AT_UTC,
    )

    extra_parameters["safety"]["historical_research_only"] = False
    extra_parameters["safety"]["labels"].add("mutated")
    extra_parameters["notes"][0] = "mutated"
    resolution.dataset_report["historical_research_only"] = False

    loaded = experiment_registry.load_offline_research_experiment_registry(registry_file)
    loaded_record = loaded.records[0]

    assert loaded_record.experiment_fingerprint == contract.contract_hash
    assert loaded_record.contract_snapshot["extra_parameters"]["safety"]["historical_research_only"] is True
    assert loaded_record.contract_snapshot["extra_parameters"]["safety"]["labels"] == ("offline", "research")
    assert loaded_record.contract_snapshot["extra_parameters"]["notes"][0] == "offline"
    assert loaded_record.artifact_reference_snapshot["dataset_report"]["historical_research_only"] is True
    assert record.record_hash == loaded_record.record_hash


def test_offline_research_experiment_registry_accepts_set_in_extra_parameters_deterministically(
    persistent_artifact, tmp_path
):
    _, reference = _qualified_reference(persistent_artifact)
    _, _, strategy_contract = _baseline_strategy_contract()

    first_contract = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
        extra_parameters={
            "safety": {
                "labels": {"alpha", "beta", "gamma"},
                "historical_research_only": True,
                "operational_evidence": False,
                "paper_promotion_eligible": False,
            },
            "costs": {
                "entry_fee_rate": "0.0004",
                "exit_fee_rate": "0.0004",
                "spread_bps": "5",
                "slippage_bps": "5",
            },
        },
    )
    second_contract = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
        extra_parameters={
            "safety": {
                "labels": {"gamma", "beta", "alpha"},
                "historical_research_only": True,
                "operational_evidence": False,
                "paper_promotion_eligible": False,
            },
            "costs": {
                "entry_fee_rate": "0.0004",
                "exit_fee_rate": "0.0004",
                "spread_bps": "5",
                "slippage_bps": "5",
            },
        },
    )
    third_contract = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
        extra_parameters={
            "safety": {
                "labels": {"alpha", "beta", "delta"},
                "historical_research_only": True,
                "operational_evidence": False,
                "paper_promotion_eligible": False,
            },
            "costs": {
                "entry_fee_rate": "0.0004",
                "exit_fee_rate": "0.0004",
                "spread_bps": "5",
                "slippage_bps": "5",
            },
        },
    )

    first_registry_file = tmp_path / "registry-sets-a.json"
    second_registry_file = tmp_path / "registry-sets-b.json"
    third_registry_file = tmp_path / "registry-sets-c.json"

    first_record = experiment_registry.register_offline_research_experiment(
        registry_file=first_registry_file,
        contract=first_contract,
        registered_at_utc=EXPERIMENT_REGISTERED_AT_UTC,
    )
    second_record = experiment_registry.register_offline_research_experiment(
        registry_file=second_registry_file,
        contract=second_contract,
        registered_at_utc=EXPERIMENT_REGISTERED_AT_UTC,
    )
    third_record = experiment_registry.register_offline_research_experiment(
        registry_file=third_registry_file,
        contract=third_contract,
        registered_at_utc=EXPERIMENT_REGISTERED_AT_UTC,
    )

    assert first_contract.contract_hash == second_contract.contract_hash
    assert first_record.record_hash == second_record.record_hash
    assert first_registry_file.read_text(encoding="utf-8") == second_registry_file.read_text(encoding="utf-8")
    assert first_contract.contract_hash != third_contract.contract_hash
    assert first_record.record_hash != third_record.record_hash
    assert first_registry_file.read_text(encoding="utf-8") != third_registry_file.read_text(encoding="utf-8")
