from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

import market_data.offline_research_backtest as backtest
import market_data.offline_research_experiment_authorization as authorization
import market_data.offline_research_experiment_contract as experiment_contract
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
        "artifact_dir": artifact_dir,
        "registry_file": registry_file,
        "dataset_file": copied_dataset_file,
        "manifest_file": copied_manifest_file,
    }


@pytest.fixture(scope="module")
def persistent_artifact(tmp_path_factory):
    root = tmp_path_factory.mktemp("phase40-okx-persistent-artifact")
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
        strategy_version="phase40_compatibility_v1",
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


def _extra_parameters_with_nested_set(*, labels: tuple[str, ...]) -> dict[str, object]:
    return {
        "safety": {
            "labels": set(labels),
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


def _forbidden(*args, **kwargs):
    raise AssertionError("unexpected operational or legacy call")


def test_offline_research_experiment_contract_builds_from_qualified_reference_and_is_stable(
    persistent_artifact, monkeypatch
):
    _, reference = _qualified_reference(persistent_artifact)
    _, _, strategy_contract = _baseline_strategy_contract()

    monkeypatch.setattr(backtest, "run_first_offline_okx_backtest_experiment", _forbidden, raising=True)
    monkeypatch.setattr(backtest.OfflineResearchBacktestRunner, "run", _forbidden, raising=True)
    monkeypatch.setattr(backtest.LeakFreeBacktestEngine, "run", _forbidden, raising=True)

    contract_one = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
    )
    contract_two = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
    )

    assert contract_one.contract_hash == contract_two.contract_hash
    assert contract_one.as_dict()["contract_hash"] == contract_one.contract_hash
    assert contract_one.experiment_id == experiment_contract.OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_ID
    assert contract_one.schema_version == experiment_contract.OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_SCHEMA_VERSION
    assert contract_one.historical_research_only is True
    assert contract_one.operational_evidence is False
    assert contract_one.paper_promotion_eligible is False
    assert contract_one.strategy_contract["strategy_id"] == "baseline_a_okx_btc_usdt_1h_research"
    assert contract_one.artifact_reference["artifact_id"] == reference.registry_report.artifact_id
    assert contract_one.artifact_reference["historical_research_only"] is True
    assert contract_one.artifact_reference["operational_evidence"] is False
    assert contract_one.artifact_reference["paper_promotion_eligible"] is False


def test_offline_research_experiment_contract_is_deeply_immutable_and_source_independent(
    persistent_artifact,
):
    _, reference = _qualified_reference(persistent_artifact)
    _, _, strategy_contract = _baseline_strategy_contract()
    extra_parameters = _default_extra_parameters()
    contract = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
        extra_parameters=extra_parameters,
    )

    with pytest.raises(TypeError):
        contract.extra_parameters["safety"] = {}
    with pytest.raises(TypeError):
        contract.extra_parameters["safety"]["paper_promotion_eligible"] = True
    with pytest.raises(TypeError):
        contract.extra_parameters["notes"][0] = "changed"

    original_strategy_hash = contract.strategy_contract["contract_hash"]
    original_strategy_version = contract.strategy_contract["strategy_version"]
    original_reference_artifact_id = contract.artifact_reference["artifact_id"]

    extra_parameters["safety"]["historical_research_only"] = False
    extra_parameters["safety"]["paper_promotion_eligible"] = True
    extra_parameters["notes"][0] = "mutated"
    object.__setattr__(strategy_contract, "contract_hash", "f" * 64)
    object.__setattr__(strategy_contract, "strategy_version", "tampered_strategy_version")
    object.__setattr__(
        reference.resolution,
        "dataset_report",
        {"historical_research_only": False, "nested": {"gate": "tampered"}},
    )
    object.__setattr__(
        reference.resolution,
        "registry_report",
        reference.registry_report,
    )

    assert contract.extra_parameters["safety"]["historical_research_only"] is True
    assert contract.extra_parameters["safety"]["paper_promotion_eligible"] is False
    assert contract.extra_parameters["notes"][0] == "offline"
    assert contract.strategy_contract["contract_hash"] == original_strategy_hash
    assert contract.strategy_contract["strategy_version"] == original_strategy_version
    assert contract.artifact_reference["artifact_id"] == original_reference_artifact_id
    assert contract.artifact_reference["historical_research_only"] is True
    assert contract.artifact_reference["operational_evidence"] is False
    assert contract.artifact_reference["paper_promotion_eligible"] is False


def test_offline_research_experiment_contract_supports_nested_sets_deterministically(
    persistent_artifact,
):
    _, reference = _qualified_reference(persistent_artifact)
    _, _, strategy_contract = _baseline_strategy_contract()
    extra_parameters_a = _extra_parameters_with_nested_set(labels=("beta", "alpha", "gamma"))
    extra_parameters_b = _extra_parameters_with_nested_set(labels=("gamma", "alpha", "beta"))

    contract_a = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
        extra_parameters=extra_parameters_a,
    )
    contract_b = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
        extra_parameters=extra_parameters_b,
    )

    assert contract_a.contract_hash == contract_b.contract_hash
    assert contract_a.as_dict() == contract_b.as_dict()
    assert isinstance(contract_a.extra_parameters["safety"]["labels"], frozenset)
    assert contract_a.extra_parameters["safety"]["labels"] == frozenset({"alpha", "beta", "gamma"})

    with pytest.raises(AttributeError):
        contract_a.extra_parameters["safety"]["labels"].add("delta")

    extra_parameters_a["safety"]["labels"].add("delta")
    extra_parameters_a["notes"].append("mutated")
    assert contract_a.extra_parameters["safety"]["labels"] == frozenset({"alpha", "beta", "gamma"})
    assert contract_a.extra_parameters["notes"] == ("offline", "read-only")

    extra_parameters_c = _extra_parameters_with_nested_set(labels=("alpha", "beta", "delta"))
    contract_c = _build_contract(
        persistent_artifact,
        reference=reference,
        strategy_contract=strategy_contract,
        extra_parameters=extra_parameters_c,
    )
    assert contract_c.contract_hash != contract_a.contract_hash


@pytest.mark.parametrize(
    ("mutator", "expected_fragment"),
    [
        (lambda payload: payload["strategy_contract"].__setitem__("contract_hash", "1" * 64), "strategy_contract"),
        (
            lambda payload: payload.__setitem__(
                "window_start_utc",
                (datetime(2026, 1, 1, tzinfo=timezone.utc) + ONE_HOUR).isoformat().replace("+00:00", "Z"),
            ),
            "window_start_utc",
        ),
        (
            lambda payload: payload.__setitem__(
                "window_end_utc",
                (datetime(2026, 1, 1, tzinfo=timezone.utc) - ONE_HOUR).isoformat().replace("+00:00", "Z"),
            ),
            "window_end_utc",
        ),
        (lambda payload: payload.__setitem__("symbol", "BTCUSDT"), "symbol"),
        (lambda payload: payload.__setitem__("interval", "4H"), "interval"),
        (lambda payload: payload.__setitem__("entry_fee_rate", "0.0005"), "entry_fee_rate"),
        (lambda payload: payload.__setitem__("spread_bps", "7"), "spread_bps"),
    ],
)
def test_offline_research_experiment_contract_fingerprint_is_sensitive_to_relevant_fields(
    persistent_artifact,
    mutator,
    expected_fragment,
):
    contract = _build_contract(persistent_artifact)
    baseline_payload = copy.deepcopy(serialize_value(contract.canonical_payload(include_contract_hash=False)))
    mutated_payload = copy.deepcopy(baseline_payload)
    mutator(mutated_payload)

    assert experiment_contract._hash_payload(mutated_payload) != contract.contract_hash
    assert expected_fragment in mutated_payload


def test_offline_research_experiment_contract_reuses_explicit_reference_entrypoint(
    persistent_artifact, monkeypatch
):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    real_resolver = backtest.resolve_okx_offline_research_artifact_reference

    def _tracking_resolver(*args, **kwargs):
        calls.append((args, kwargs))
        return real_resolver(*args, **kwargs)

    monkeypatch.setattr(
        experiment_contract,
        "resolve_okx_offline_research_artifact_reference",
        _tracking_resolver,
        raising=True,
    )
    monkeypatch.setattr(backtest, "run_first_offline_okx_backtest_experiment", _forbidden, raising=True)
    monkeypatch.setattr(backtest.OfflineResearchBacktestRunner, "run", _forbidden, raising=True)
    monkeypatch.setattr(backtest.LeakFreeBacktestEngine, "run", _forbidden, raising=True)

    strategy_contract = _baseline_strategy_contract()[2]
    contract = experiment_contract.build_offline_research_experiment_contract(
        registry_file=persistent_artifact["registry_file"],
        dataset_file=persistent_artifact["dataset_file"],
        manifest_file=persistent_artifact["manifest_file"],
        strategy_contract=strategy_contract,
        created_at_utc=EXPERIMENT_CREATED_AT_UTC,
    )

    assert len(calls) == 1
    assert contract.artifact_reference["artifact_id"]
    assert contract.strategy_contract["strategy_id"] == "baseline_a_okx_btc_usdt_1h_research"


@pytest.mark.parametrize(
    ("artifact_reference", "registry_file", "dataset_file", "manifest_file", "expected"),
    [
        ("not-a-reference", None, None, None, "a verified offline research artifact reference is required"),
        (None, None, None, None, "registry_file, dataset_file and manifest_file are required"),
    ],
)
def test_offline_research_experiment_contract_rejects_unqualified_reference_and_missing_paths(
    persistent_artifact,
    artifact_reference,
    registry_file,
    dataset_file,
    manifest_file,
    expected,
):
    _, _, strategy_contract = _baseline_strategy_contract()

    with pytest.raises(experiment_contract.OfflineResearchExperimentContractValidationError, match=expected):
        experiment_contract.build_offline_research_experiment_contract(
            artifact_reference=artifact_reference,
            registry_file=registry_file,
            dataset_file=dataset_file,
            manifest_file=manifest_file,
            strategy_contract=strategy_contract,
            created_at_utc=EXPERIMENT_CREATED_AT_UTC,
        )


def test_offline_research_experiment_contract_rejects_pytest_tmp_paths(persistent_artifact, tmp_path):
    _, _, strategy_contract = _baseline_strategy_contract()
    repo_root = Path(__file__).resolve().parents[1]
    root = repo_root / ".pytest_tmp" / "phase40-reject"
    artifact_dir = root / "okx"
    registry_dir = root / "phase20a-okx-research-artifact-registry"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    registry_dir.mkdir(parents=True, exist_ok=True)
    dataset_file = artifact_dir / okx.OKX_HISTORICAL_DATASET_CANDLES_FILENAME
    manifest_file = artifact_dir / okx.OKX_HISTORICAL_MANIFEST_FILENAME
    registry_file = registry_dir / "okx-research-artifact-registry.json"
    dataset_file.write_text("[]", encoding="utf-8")
    manifest_file.write_text("{}", encoding="utf-8")
    registry_file.write_text("{}", encoding="utf-8")

    with pytest.raises(backtest.OfflineResearchBacktestValidationError, match=".pytest_tmp"):
        experiment_contract.build_offline_research_experiment_contract(
            registry_file=registry_file,
            dataset_file=dataset_file,
            manifest_file=manifest_file,
            strategy_contract=strategy_contract,
            created_at_utc=EXPERIMENT_CREATED_AT_UTC,
        )


@pytest.mark.parametrize(
    ("flag_name", "value", "expected"),
    [
        ("historical_research_only", False, "historical_research_only must be true"),
        ("operational_evidence", True, "operational_evidence must be false"),
        ("paper_promotion_eligible", True, "paper_promotion_eligible must be false"),
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
def test_offline_research_experiment_contract_rejects_prohibited_operational_toggles(
    persistent_artifact,
    flag_name,
    value,
    expected,
):
    _, reference = _qualified_reference(persistent_artifact)
    _, _, strategy_contract = _baseline_strategy_contract()
    kwargs = {
        "artifact_reference": reference,
        "strategy_contract": strategy_contract,
        "created_at_utc": EXPERIMENT_CREATED_AT_UTC,
        flag_name: value,
    }
    with pytest.raises(experiment_contract.OfflineResearchExperimentContractValidationError, match=expected):
        experiment_contract.build_offline_research_experiment_contract(**kwargs)


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("window_start_utc", datetime(2021, 2, 12, 1, 0, tzinfo=timezone.utc)),
        ("window_end_utc", datetime(2025, 12, 31, 23, 0, tzinfo=timezone.utc)),
        ("symbol", "BTCUSDT"),
        ("interval", "4H"),
        ("entry_fee_rate", Decimal("0.0005")),
        ("exit_fee_rate", Decimal("0.0005")),
        ("spread_bps", Decimal("7")),
        ("slippage_bps", Decimal("9")),
        ("leverage", Decimal("2")),
        ("initial_capital", Decimal("12000")),
        ("risk_percent", Decimal("2")),
    ],
)
def test_offline_research_experiment_contract_hash_changes_for_configuration_fields(
    persistent_artifact,
    field_name,
    replacement,
):
    contract = _build_contract(persistent_artifact)
    payload = copy.deepcopy(serialize_value(contract.canonical_payload(include_contract_hash=False)))
    payload[field_name] = (
        replacement.isoformat().replace("+00:00", "Z")
        if isinstance(replacement, datetime)
        else str(replacement)
    )
    assert experiment_contract._hash_payload(payload) != contract.contract_hash


def test_offline_research_experiment_contract_rejects_manifest_and_registry_path_divergence(
    persistent_artifact, tmp_path
):
    _, _, strategy_contract = _baseline_strategy_contract()

    artifact_root = tmp_path / "phase40-divergence"
    artifact_dir = artifact_root / "okx"
    registry_dir = artifact_root / "phase20a-okx-research-artifact-registry"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    registry_dir.mkdir(parents=True, exist_ok=True)
    dataset_file = artifact_dir / okx.OKX_HISTORICAL_DATASET_CANDLES_FILENAME
    manifest_file = artifact_dir / okx.OKX_HISTORICAL_MANIFEST_FILENAME
    shutil.copyfile(persistent_artifact["dataset_file"], dataset_file)
    shutil.copyfile(persistent_artifact["manifest_file"], manifest_file)
    registry_file = registry_dir / "okx-research-artifact-registry.json"
    payload = json.loads(persistent_artifact["registry_file"].read_text(encoding="utf-8"))
    registry_entry = registry.ResearchArtifactRegistryEntry.from_dict(payload)
    object.__setattr__(registry_entry, "external_artifact_ref", artifact_dir.as_posix())
    object.__setattr__(registry_entry, "manifest_hash", "0" * 64)
    object.__setattr__(
        registry_entry,
        "artifact_id",
        sha256(
            json.dumps(
                serialize_value(registry_entry._artifact_id_payload()),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    )
    object.__setattr__(
        registry_entry,
        "registry_hash",
        sha256(
            json.dumps(
                serialize_value(registry_entry.canonical_payload(include_registry_hash=False)),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    )
    registry_file.write_text(
        json.dumps(registry_entry.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(backtest.OfflineResearchBacktestError, match="manifest_hash must match"):
        experiment_contract.build_offline_research_experiment_contract(
            registry_file=registry_file,
            dataset_file=dataset_file,
            manifest_file=manifest_file,
            strategy_contract=strategy_contract,
            created_at_utc=EXPERIMENT_CREATED_AT_UTC,
        )


def test_offline_research_experiment_contract_rejects_artifact_id_mismatch_without_registry_hash_escape(
    persistent_artifact, tmp_path
):
    _, _, strategy_contract = _baseline_strategy_contract()
    artifact_root = tmp_path / "phase40-artifact-id"
    artifact_dir = artifact_root / "okx"
    registry_dir = artifact_root / "phase20a-okx-research-artifact-registry"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    registry_dir.mkdir(parents=True, exist_ok=True)
    dataset_file = artifact_dir / okx.OKX_HISTORICAL_DATASET_CANDLES_FILENAME
    manifest_file = artifact_dir / okx.OKX_HISTORICAL_MANIFEST_FILENAME
    shutil.copyfile(persistent_artifact["dataset_file"], dataset_file)
    shutil.copyfile(persistent_artifact["manifest_file"], manifest_file)

    registry_payload = json.loads(persistent_artifact["registry_file"].read_text(encoding="utf-8"))
    registry_entry = registry.ResearchArtifactRegistryEntry.from_dict(registry_payload)
    object.__setattr__(registry_entry, "external_artifact_ref", artifact_dir.as_posix())
    registry_payload["external_artifact_ref"] = artifact_dir.as_posix()
    registry_payload["registry_hash"] = sha256(
        json.dumps(
            serialize_value(registry_entry.canonical_payload(include_registry_hash=False)),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    registry_file = registry_dir / "okx-research-artifact-registry.json"
    registry_file.write_text(
        json.dumps(registry_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(backtest.OfflineResearchBacktestError, match="artifact_id mismatch"):
        experiment_contract.build_offline_research_experiment_contract(
            registry_file=registry_file,
            dataset_file=dataset_file,
            manifest_file=manifest_file,
            strategy_contract=strategy_contract,
            created_at_utc=EXPERIMENT_CREATED_AT_UTC,
        )
