from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

import market_data.offline_research_experiment_authorization as authorization
import market_data.offline_research_backtest as backtest
import market_data.offline_research_experiment_contract as experiment_contract
import market_data.offline_research_experiment_execution_registry as execution_registry
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
EXECUTION_CREATED_AT_UTC = datetime(2026, 7, 27, 17, 0, 0, tzinfo=timezone.utc)
REFERENCE_DECIDED_AT_UTC = datetime(2026, 7, 27, 16, 31, 34, tzinfo=timezone.utc)
AUTHORIZATION_ISSUED_AT_UTC = datetime(2026, 7, 27, 16, 31, 33, tzinfo=timezone.utc)
SOURCE_COMMIT_SHA = "9a0764a8a772ac4904195497cec39e638a2ec1cd"
SOURCE_BRANCH = "phase-42-offline-experiment-execution-registry"
ONE_HOUR = timedelta(hours=1)


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
    root = tmp_path_factory.mktemp("phase42-okx-persistent-artifact")
    return _build_persistent_artifact(root)


def _real_phase41_record():
    with tempfile.TemporaryDirectory(prefix="phase42-phase41-") as tmp:
        root = Path(tmp)
        artifact_dir = root / "phase19c-okx-20260727T000000Z" / "okx"
        registry_dir = root / "phase20a-okx-research-artifact-registry"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        registry_dir.mkdir(parents=True, exist_ok=True)

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


def _synthetic_phase41_registration(
    *,
    experiment_id: str,
    experiment_version: str,
    label: str,
    registered_at_utc: datetime,
) -> experiment_registry.OfflineResearchExperimentRegistryRecord:
    record = object.__new__(experiment_registry.OfflineResearchExperimentRegistryRecord)
    object.__setattr__(record, "schema_version", experiment_registry.OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_SCHEMA_VERSION)
    object.__setattr__(record, "experiment_id", experiment_id)
    object.__setattr__(record, "experiment_version", experiment_version)
    object.__setattr__(record, "experiment_fingerprint", sha256(f"{experiment_id}:{label}".encode("utf-8")).hexdigest())
    object.__setattr__(record, "registered_at_utc", registered_at_utc)
    object.__setattr__(
        record,
        "contract_snapshot",
        {
            "label": label,
            "extra_parameters": {
                "labels": frozenset({label, "offline"}),
                "nested": {"gate": frozenset({"a", "b"})},
            },
        },
    )
    object.__setattr__(
        record,
        "artifact_reference_snapshot",
        {
            "registry_report": {
                "artifact_id": sha256(f"artifact:{label}".encode("utf-8")).hexdigest(),
                "provider_name": "OKX",
                "market_type": "spot",
                "instrument": "BTC-USDT",
                "symbol": "BTCUSDT",
                "interval": "1H",
                "requested_start_inclusive_utc": "2026-01-01T00:00:00Z",
                "requested_end_exclusive_utc": "2026-01-01T01:00:00Z",
                "expected_candle_count": 1,
                "audited_candle_count": 1,
                "dataset_sha256": sha256(f"dataset:{label}".encode("utf-8")).hexdigest(),
                "manifest_sha256": sha256(f"manifest:{label}".encode("utf-8")).hexdigest(),
                "manifest_hash": sha256(f"manifest-hash:{label}".encode("utf-8")).hexdigest(),
                "audit_status": "passed",
                "external_artifact_ref": f"artifact://synthetic/{label}",
                "external_artifact_ref_is_opaque": True,
                "external_artifact_ref_is_local": True,
                "historical_research_only": True,
                "operational_evidence": False,
                "paper_promotion_eligible": False,
                "non_operational_declaration": registry.OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION,
                "verification_hash": sha256(f"verification:{label}".encode("utf-8")).hexdigest(),
            },
            "dataset_report": {
                "dataset_hash": sha256(f"dataset-hash:{label}".encode("utf-8")).hexdigest(),
                "contract_hash": sha256(f"contract-hash:{label}".encode("utf-8")).hexdigest(),
                "historical_research_only": True,
                "operational_evidence": False,
                "paper_promotion_eligible": False,
                "nested": {"labels": frozenset({label, "research"})},
            },
        },
    )
    object.__setattr__(record, "historical_research_only", True)
    object.__setattr__(record, "operational_evidence", False)
    object.__setattr__(record, "paper_promotion_eligible", False)
    object.__setattr__(
        record,
        "non_operational_declaration",
        experiment_registry.OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_NON_OPERATIONAL_DECLARATION,
    )
    object.__setattr__(
        record,
        "record_hash",
        sha256(
            json.dumps(
                serialize_value(record.canonical_payload(include_record_hash=False)),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    )
    return record


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
            )
        )


def _verified_authorization() -> authorization.OfflineResearchExperimentAuthorization:
    registry_entry = registry.ResearchArtifactRegistryEntry(
        registered_at_utc=datetime(2026, 7, 27, 16, 31, 31, tzinfo=timezone.utc),
        external_artifact_ref="artifact://okx/phase42/research-only",
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
        external_artifact_ref="artifact://okx/phase42/research-only",
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


def _baseline_strategy_contract() -> object:
    auth = _verified_authorization()
    compat = _compatibility_contract(auth)
    decision = compatibility.evaluate_offline_research_strategy_compatibility(
        auth,
        compat,
        decided_at_utc=REFERENCE_DECIDED_AT_UTC,
    )
    return build_baseline_a_okx_btc_usdt_research_contract(auth, decision)


@dataclass(frozen=True, slots=True)
class _SyntheticPhase41Registry:
    record: _SyntheticPhase41Registration

    def record_by_experiment_id(self, experiment_id: str) -> _SyntheticPhase41Registration:
        if experiment_id != self.record.experiment_id:
            raise execution_registry.OfflineResearchExperimentExecutionRegistryValidationError(
                "experiment_id was not found in the registry."
            )
        return self.record


def _phase41_registry_bundle(
    tmp_path: Path,
    *,
    experiment_id: str,
    experiment_version: str,
) -> tuple[Path, _SyntheticPhase41Registry, _SyntheticPhase41Registration]:
    record = _synthetic_phase41_registration(
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        label=experiment_id,
        registered_at_utc=EXPERIMENT_REGISTERED_AT_UTC,
    )
    registry_file = tmp_path / "phase41.json"
    registry_file.write_text(
        json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return registry_file, _SyntheticPhase41Registry(record=record), record


def _synthetic_phase41_registration(
    *,
    experiment_id: str,
    experiment_version: str,
    label: str,
    registered_at_utc: datetime,
) -> _SyntheticPhase41Registration:
    payload = {
        "schema_version": experiment_registry.OFFLINE_RESEARCH_EXPERIMENT_REGISTRY_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "experiment_version": experiment_version,
        "experiment_fingerprint": sha256(f"{experiment_id}:{label}".encode("utf-8")).hexdigest(),
        "registered_at_utc": registered_at_utc,
        "contract_snapshot": {
            "label": label,
            "extra_parameters": {
                "labels": frozenset({label, "offline"}),
                "nested": {"gate": frozenset({"a", "b"})},
            },
        },
        "artifact_reference_snapshot": {
            "registry_report": {
                "artifact_id": sha256(f"artifact:{label}".encode("utf-8")).hexdigest(),
                "provider_name": "OKX",
                "market_type": "spot",
                "instrument": "BTC-USDT",
                "symbol": "BTCUSDT",
                "interval": "1H",
                "requested_start_inclusive_utc": "2026-01-01T00:00:00Z",
                "requested_end_exclusive_utc": "2026-01-01T01:00:00Z",
                "expected_candle_count": 1,
                "audited_candle_count": 1,
                "dataset_sha256": sha256(f"dataset:{label}".encode("utf-8")).hexdigest(),
                "manifest_sha256": sha256(f"manifest:{label}".encode("utf-8")).hexdigest(),
                "manifest_hash": sha256(f"manifest-hash:{label}".encode("utf-8")).hexdigest(),
                "audit_status": "passed",
                "external_artifact_ref": f"artifact://synthetic/{label}",
                "external_artifact_ref_is_opaque": True,
                "external_artifact_ref_is_local": True,
                "historical_research_only": True,
                "operational_evidence": False,
                "paper_promotion_eligible": False,
                "non_operational_declaration": registry.OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION,
                "verification_hash": sha256(f"verification:{label}".encode("utf-8")).hexdigest(),
            },
            "dataset_report": {
                "dataset_hash": sha256(f"dataset-hash:{label}".encode("utf-8")).hexdigest(),
                "contract_hash": sha256(f"contract-hash:{label}".encode("utf-8")).hexdigest(),
                "historical_research_only": True,
                "operational_evidence": False,
                "paper_promotion_eligible": False,
                "nested": {"labels": frozenset({label, "research"})},
            },
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
    return _SyntheticPhase41Registration(experiment_id=experiment_id, payload=payload)


def _execution_context(*, labels: set[str] | frozenset[str] | None = None) -> dict[str, object]:
    return {
        "channels": {"primary", "secondary"} if labels is None else set(labels),
        "nested": {
            "flags": {"offline", "research"},
            "window": {"start", "end"},
        },
        "notes": ["offline", "audit"],
    }


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
        execution_context=execution_context or _execution_context(),
        offline_only=offline_only,
        historical_research_only=historical_research_only,
        operational_evidence=operational_evidence,
        paper_promotion_eligible=paper_promotion_eligible,
    )


def _persist_registry(path: Path, records: tuple[execution_registry.OfflineResearchExperimentExecutionRegistration, ...]):
    registry_obj = execution_registry.OfflineResearchExperimentExecutionRegistry(
        registry_file=path,
        created_at_utc=EXECUTION_CREATED_AT_UTC,
        updated_at_utc=EXECUTION_CREATED_AT_UTC,
        records=records,
    )
    execution_registry.save_offline_research_experiment_execution_registry(path, registry_obj)
    return registry_obj


def _forbidden(*args, **kwargs):
    raise AssertionError("unexpected operational or legacy call")


def test_phase42_valid_chain_idempotency_and_round_trip(persistent_artifact, tmp_path, monkeypatch):
    phase41_registry_file, phase41_registry, phase41_record = _phase41_registry_bundle(
        tmp_path,
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
    )
    monkeypatch.setattr(
        experiment_registry,
        "load_offline_research_experiment_registry",
        lambda path: phase41_registry,
        raising=True,
    )
    monkeypatch.setattr(backtest, "run_first_offline_okx_backtest_experiment", _forbidden, raising=True)
    monkeypatch.setattr(backtest.LeakFreeBacktestEngine, "run", _forbidden, raising=True)

    registry_file = tmp_path / "offline-research-experiment-execution-registry.json"
    first = execution_registry.register_offline_research_experiment_execution(
        registry_file=registry_file,
        experiment_registry_file=phase41_registry_file,
        experiment_id=phase41_record.experiment_id,
        attempt_number=1,
        created_at_utc=EXECUTION_CREATED_AT_UTC,
        source_commit_sha=SOURCE_COMMIT_SHA,
        source_branch=SOURCE_BRANCH,
        execution_status="REGISTERED",
        execution_reason="offline preparation",
        execution_context=_execution_context(),
    )
    second = execution_registry.register_offline_research_experiment_execution(
        registry_file=registry_file,
        experiment_registry_file=phase41_registry_file,
        experiment_id=phase41_record.experiment_id,
        attempt_number=2,
        created_at_utc=EXECUTION_CREATED_AT_UTC + ONE_HOUR,
        source_commit_sha=SOURCE_COMMIT_SHA,
        source_branch=SOURCE_BRANCH,
        execution_status="ABORTED_BEFORE_EXECUTION",
        execution_reason="offline guard failed",
        execution_context=_execution_context(labels={"primary", "secondary"}),
    )
    third = execution_registry.register_offline_research_experiment_execution(
        registry_file=registry_file,
        experiment_registry_file=phase41_registry_file,
        experiment_id=phase41_record.experiment_id,
        attempt_number=3,
        created_at_utc=EXECUTION_CREATED_AT_UTC + 2 * ONE_HOUR,
        source_commit_sha=SOURCE_COMMIT_SHA,
        source_branch=SOURCE_BRANCH,
        execution_status="INVALIDATED",
        execution_reason="offline guard already invalidated",
        execution_context=_execution_context(labels={"audit", "offline"}),
    )
    duplicated = execution_registry.register_offline_research_experiment_execution(
        registry_file=registry_file,
        experiment_registry_file=phase41_registry_file,
        experiment_id=phase41_record.experiment_id,
        attempt_number=3,
        created_at_utc=EXECUTION_CREATED_AT_UTC + 2 * ONE_HOUR,
        source_commit_sha=SOURCE_COMMIT_SHA,
        source_branch=SOURCE_BRANCH,
        execution_status="INVALIDATED",
        execution_reason="offline guard already invalidated",
        execution_context=_execution_context(labels={"audit", "offline"}),
    )

    loaded = execution_registry.load_offline_research_experiment_execution_registry(registry_file)
    verified = execution_registry.verify_offline_research_experiment_execution_registry(registry_file)

    assert first.execution_id == loaded.records[0].execution_id
    assert second.previous_execution_id == first.execution_id
    assert second.previous_execution_hash == first.execution_hash
    assert third.previous_execution_id == second.execution_id
    assert third.previous_execution_hash == second.execution_hash
    assert duplicated.execution_hash == third.execution_hash
    assert duplicated.as_dict() == third.as_dict()
    assert loaded.record_count == 3
    assert [record.attempt_number for record in loaded.records] == [1, 2, 3]
    assert verified.approved is True
    assert verified.record_count == 3
    assert verified.execution_ids == tuple(record.execution_id for record in loaded.records)
    assert verified.execution_hashes == tuple(record.execution_hash for record in loaded.records)
    assert verified.experiment_ids == (phase41_record.experiment_id,) * 3
    assert loaded.registration_by_execution_hash(third.execution_hash).execution_id == third.execution_id

    with pytest.raises(TypeError):
        loaded.records[0].execution_context["channels"][0] = "changed"
    with pytest.raises(TypeError):
        loaded.records[0].experiment_registration_snapshot["contract_snapshot"]["extra_parameters"]["labels"][0] = "changed"


def test_phase42_independent_experiments_allow_independent_chains(tmp_path):
    experiment_a = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    experiment_b = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_b",
        experiment_version="phase41_synthetic_v1",
        label="beta",
        registered_at_utc=datetime(2026, 7, 27, 8, 5, tzinfo=timezone.utc),
    )

    reg_a1 = _build_execution(experiment_registration=experiment_a, attempt_number=1, execution_context={"nested": {"labels": {"a", "b"}}})
    reg_b1 = _build_execution(experiment_registration=experiment_b, attempt_number=1, execution_context={"nested": {"labels": {"c", "d"}}})
    reg_a2 = _build_execution(
        experiment_registration=experiment_a,
        attempt_number=2,
        previous_execution_id=reg_a1.execution_id,
        previous_execution_hash=reg_a1.execution_hash,
        execution_context={"nested": {"labels": {"e", "f"}}},
    )

    registry_file = tmp_path / "offline-research-experiment-execution-registry.json"
    _persist_registry(registry_file, (reg_a1, reg_b1, reg_a2))
    loaded = execution_registry.load_offline_research_experiment_execution_registry(registry_file)

    assert loaded.registration_by_experiment_id_and_attempt_number("synthetic_experiment_a", 1).execution_id == reg_a1.execution_id
    assert loaded.registration_by_experiment_id_and_attempt_number("synthetic_experiment_b", 1).execution_id == reg_b1.execution_id
    assert loaded.registration_by_experiment_id_and_attempt_number("synthetic_experiment_a", 2).previous_execution_id == reg_a1.execution_id


@pytest.mark.parametrize(
    ("attempt_number", "previous_id", "previous_hash", "expected"),
    [
        (0, None, None, "attempt_number must be greater than zero"),
        (-1, None, None, "attempt_number must be greater than zero"),
        (True, None, None, "attempt_number must be an integer"),
        (1, "x", None, "previous execution reference is not allowed for attempt_number 1"),
        (1, None, "a" * 64, "previous execution reference is not allowed for attempt_number 1"),
        (2, None, None, "previous execution reference is required for attempt_number greater than 1"),
    ],
)
def test_phase42_attempt_number_and_first_attempt_rules(
    attempt_number,
    previous_id,
    previous_hash,
    expected,
):
    experiment_a = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError, match=expected):
        _build_execution(
            experiment_registration=experiment_a,
            attempt_number=attempt_number,
            previous_execution_id=previous_id,
            previous_execution_hash=previous_hash,
        )


def test_phase42_chain_mismatch_and_cross_experiment_previous_reference(tmp_path, monkeypatch):
    experiment_a = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    experiment_b = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_b",
        experiment_version="phase41_synthetic_v1",
        label="beta",
        registered_at_utc=datetime(2026, 7, 27, 8, 5, tzinfo=timezone.utc),
    )
    reg_a1 = _build_execution(experiment_registration=experiment_a, attempt_number=1)
    reg_a2 = _build_execution(
        experiment_registration=experiment_a,
        attempt_number=2,
        previous_execution_id=reg_a1.execution_id,
        previous_execution_hash=reg_a1.execution_hash,
    )
    reg_b1 = _build_execution(experiment_registration=experiment_b, attempt_number=1)
    reg_a2_cross = _build_execution(
        experiment_registration=experiment_a,
        attempt_number=2,
        previous_execution_id=reg_b1.execution_id,
        previous_execution_hash=reg_b1.execution_hash,
    )
    phase41_registry_file, phase41_registry, _ = _phase41_registry_bundle(
        tmp_path,
        experiment_id=experiment_a.experiment_id,
        experiment_version="phase41_synthetic_v1",
    )
    monkeypatch.setattr(
        experiment_registry,
        "load_offline_research_experiment_registry",
        lambda path: phase41_registry,
        raising=True,
    )
    registry_file = tmp_path / "offline-research-experiment-execution-registry.json"
    _persist_registry(registry_file, (reg_a1,))

    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryIntegrityError, match="previous_execution_id mismatch"):
        execution_registry.register_offline_research_experiment_execution(
            registry_file=registry_file,
            experiment_registry_file=phase41_registry_file,
            experiment_id=experiment_a.experiment_id,
            attempt_number=2,
            created_at_utc=EXECUTION_CREATED_AT_UTC + ONE_HOUR,
            source_commit_sha=SOURCE_COMMIT_SHA,
            source_branch=SOURCE_BRANCH,
            execution_status="REGISTERED",
            execution_reason="offline preparation",
            previous_execution_id=reg_b1.execution_id,
            previous_execution_hash=reg_b1.execution_hash,
        )

    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryIntegrityError, match="previous_execution_hash mismatch"):
        execution_registry.register_offline_research_experiment_execution(
            registry_file=registry_file,
            experiment_registry_file=phase41_registry_file,
            experiment_id=experiment_a.experiment_id,
            attempt_number=2,
            created_at_utc=EXECUTION_CREATED_AT_UTC + ONE_HOUR,
            source_commit_sha=SOURCE_COMMIT_SHA,
            source_branch=SOURCE_BRANCH,
            execution_status="REGISTERED",
            execution_reason="offline preparation",
            previous_execution_id=reg_a1.execution_id,
            previous_execution_hash=reg_b1.execution_hash,
        )

    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryIntegrityError, match="previous_execution_id mismatch"):
        execution_registry.OfflineResearchExperimentExecutionRegistry(
            registry_file=tmp_path / "cross.json",
            created_at_utc=EXECUTION_CREATED_AT_UTC,
            updated_at_utc=EXECUTION_CREATED_AT_UTC,
            records=(reg_a1, reg_b1, reg_a2_cross),
        )


def test_phase42_rejects_nonexistent_experiment_id(tmp_path, monkeypatch):
    phase41_registry_file, phase41_registry, _ = _phase41_registry_bundle(
        tmp_path,
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
    )
    monkeypatch.setattr(
        experiment_registry,
        "load_offline_research_experiment_registry",
        lambda path: phase41_registry,
        raising=True,
    )
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError, match="experiment_id was not found in the registry"):
        execution_registry.register_offline_research_experiment_execution(
            registry_file=Path("unused-registry.json"),
            experiment_registry_file=phase41_registry_file,
            experiment_id="missing-experiment-id",
            attempt_number=1,
            created_at_utc=EXECUTION_CREATED_AT_UTC,
            source_commit_sha=SOURCE_COMMIT_SHA,
            source_branch=SOURCE_BRANCH,
            execution_status="REGISTERED",
            execution_reason="offline preparation",
        )


def test_phase42_same_execution_id_requires_identical_content():
    experiment_a = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    first = _build_execution(experiment_registration=experiment_a, attempt_number=1)
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryIntegrityError, match="execution_id mismatch"):
        _build_execution(
            experiment_registration=experiment_a,
            attempt_number=1,
            execution_id=first.execution_id,
            execution_reason="different content",
        )


def test_phase42_repeated_attempt_number_with_different_content_conflicts(tmp_path, monkeypatch):
    experiment_a = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    phase41_registry_file, phase41_registry, _ = _phase41_registry_bundle(
        tmp_path,
        experiment_id=experiment_a.experiment_id,
        experiment_version="phase41_synthetic_v1",
    )
    monkeypatch.setattr(
        experiment_registry,
        "load_offline_research_experiment_registry",
        lambda path: phase41_registry,
        raising=True,
    )
    registry_file = tmp_path / "offline-research-experiment-execution-registry.json"
    execution_registry.register_offline_research_experiment_execution(
        registry_file=registry_file,
        experiment_registry_file=phase41_registry_file,
        experiment_id=experiment_a.experiment_id,
        attempt_number=1,
        created_at_utc=EXECUTION_CREATED_AT_UTC,
        source_commit_sha=SOURCE_COMMIT_SHA,
        source_branch=SOURCE_BRANCH,
        execution_status="REGISTERED",
        execution_reason="offline preparation",
    )
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryConflictError, match="attempt_number already registered for this experiment"):
        execution_registry.register_offline_research_experiment_execution(
            registry_file=registry_file,
            experiment_registry_file=phase41_registry_file,
            experiment_id=experiment_a.experiment_id,
            attempt_number=1,
            created_at_utc=EXECUTION_CREATED_AT_UTC,
            source_commit_sha=SOURCE_COMMIT_SHA,
            source_branch=SOURCE_BRANCH,
            execution_status="REGISTERED",
            execution_reason="different content",
        )


def test_phase42_skips_attempt_numbers_and_rejects_previous_missing(tmp_path, monkeypatch):
    experiment_a = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    reg1 = _build_execution(experiment_registration=experiment_a, attempt_number=1)
    phase41_registry_file, phase41_registry, _ = _phase41_registry_bundle(
        tmp_path,
        experiment_id=experiment_a.experiment_id,
        experiment_version="phase41_synthetic_v1",
    )
    monkeypatch.setattr(
        experiment_registry,
        "load_offline_research_experiment_registry",
        lambda path: phase41_registry,
        raising=True,
    )
    registry_file = tmp_path / "offline-research-experiment-execution-registry.json"
    _persist_registry(registry_file, (reg1,))
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError, match="execution attempt was not found in the registry"):
        execution_registry.register_offline_research_experiment_execution(
            registry_file=registry_file,
            experiment_registry_file=phase41_registry_file,
            experiment_id=experiment_a.experiment_id,
            attempt_number=3,
            created_at_utc=EXECUTION_CREATED_AT_UTC + 2 * ONE_HOUR,
            source_commit_sha=SOURCE_COMMIT_SHA,
            source_branch=SOURCE_BRANCH,
            execution_status="REGISTERED",
            execution_reason="offline preparation",
        )


def test_phase42_rejects_tampered_non_operational_declaration(tmp_path):
    _, _, phase41_record = _phase41_registry_bundle(
        tmp_path,
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
    )
    tampered = json.loads(json.dumps(serialize_value(phase41_record.as_dict()), ensure_ascii=False, sort_keys=True))
    tampered["non_operational_declaration"] = "tampered declaration"
    tampered["record_hash"] = sha256(
        json.dumps(
            serialize_value({key: value for key, value in tampered.items() if key != "record_hash"}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError, match="non_operational_declaration diverges from the experiment registry contract"):
        _build_execution(experiment_registration=tampered, attempt_number=1)


@pytest.mark.parametrize(
    "status",
    [
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "EXECUTED",
        "BACKTESTED",
        "WALK_FORWARD_COMPLETED",
        "PAPER",
        "LIVE",
        "PROMOTED",
    ],
)
def test_phase42_rejects_disallowed_statuses(status):
    experiment_a = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError, match="execution_status is not allowed"):
        _build_execution(experiment_registration=experiment_a, attempt_number=1, execution_status=status)


@pytest.mark.parametrize(
    ("field_name", "value", "expected"),
    [
        ("offline_only", False, "offline_only must be true"),
        ("historical_research_only", False, "historical_research_only must be true"),
        ("operational_evidence", True, "operational_evidence must be false"),
        ("paper_promotion_eligible", True, "paper_promotion_eligible must be false"),
    ],
)
def test_phase42_rejects_security_flags(field_name, value, expected):
    experiment_a = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    kwargs = {
        "offline_only": True,
        "historical_research_only": True,
        "operational_evidence": False,
        "paper_promotion_eligible": False,
    }
    kwargs[field_name] = value
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError, match=expected):
        _build_execution(experiment_registration=experiment_a, attempt_number=1, **kwargs)


def test_phase42_datetime_commit_branch_reason_validation_and_normalization():
    experiment_a = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError, match="created_at_utc must be timezone-aware UTC datetime"):
        _build_execution(experiment_registration=experiment_a, attempt_number=1, created_at_utc=datetime(2026, 7, 27, 17, 0))
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError, match="source_commit_sha must be a 40-character hex git commit sha"):
        _build_execution(experiment_registration=experiment_a, attempt_number=1, source_commit_sha="bad")
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError, match="source_branch is required"):
        _build_execution(experiment_registration=experiment_a, attempt_number=1, source_branch="   ")
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError, match="execution_reason is required"):
        _build_execution(experiment_registration=experiment_a, attempt_number=1, execution_reason=" ")

    record = _build_execution(
        experiment_registration=experiment_a,
        attempt_number=1,
        created_at_utc=datetime(2026, 7, 27, 19, 0, tzinfo=timezone(timedelta(hours=2))),
    )
    assert record.created_at_utc == datetime(2026, 7, 27, 17, 0, tzinfo=timezone.utc)


def test_phase42_hashes_are_deterministic_and_order_insensitive():
    experiment_a = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    context_a = {
        "metadata": {"b": 2, "a": 1},
        "labels": {"beta", "alpha"},
        "nested": {"set": {"y", "x"}},
    }
    context_b = {
        "labels": {"alpha", "beta"},
        "nested": {"set": {"x", "y"}},
        "metadata": {"a": 1, "b": 2},
    }
    record_a = _build_execution(experiment_registration=experiment_a, attempt_number=1, execution_context=context_a)
    record_b = _build_execution(experiment_registration=experiment_a, attempt_number=1, execution_context=context_b)
    record_c = _build_execution(
        experiment_registration=experiment_a,
        attempt_number=1,
        execution_context={
            "metadata": {"a": 1, "b": 2},
            "labels": {"alpha", "gamma"},
            "nested": {"set": {"x", "y"}},
        },
    )

    assert record_a.execution_id == record_b.execution_id
    assert record_a.execution_hash == record_b.execution_hash
    assert record_a.execution_id != record_c.execution_id
    assert record_a.execution_hash != record_c.execution_hash


def test_phase42_hash_is_stable_across_processes():
    record = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    script = f"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
sys.path.insert(0, r"{Path.cwd()}")
from tests.test_offline_research_experiment_execution_registry_phase42 import _synthetic_phase41_registration
record = _synthetic_phase41_registration(
    experiment_id="synthetic_experiment_a",
    experiment_version="phase41_synthetic_v1",
    label="alpha",
    registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
)
print(json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
"""
    first = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    second = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    assert first.stdout == second.stdout
    assert json.loads(first.stdout) == record.as_dict()


def test_phase42_deep_immutability_and_source_independence(tmp_path):
    experiment_a = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    execution_context = {
        "metadata": {"labels": {"alpha", "beta"}, "nested": {"left": [1, 2], "right": {"x", "y"}}},
        "notes": ["offline", "research"],
    }
    record = _build_execution(experiment_registration=experiment_a, attempt_number=1, execution_context=execution_context)
    execution_context["metadata"]["labels"].add("gamma")
    execution_context["metadata"]["nested"]["right"].add("z")
    execution_context["notes"][0] = "mutated"

    registry_file = tmp_path / "registry.json"
    _persist_registry(registry_file, (record,))
    loaded = execution_registry.load_offline_research_experiment_execution_registry(registry_file)

    assert loaded.records[0].execution_context["metadata"]["labels"] == ("alpha", "beta")
    assert loaded.records[0].execution_context["metadata"]["nested"]["right"] == ("x", "y")
    assert loaded.records[0].execution_context["notes"][0] == "offline"
    with pytest.raises(TypeError):
        loaded.records[0].execution_context["metadata"]["labels"][0] = "changed"
    with pytest.raises(TypeError):
        loaded.records[0].experiment_registration_snapshot["contract_snapshot"]["extra_parameters"]["labels"][0] = "changed"


def test_phase42_persistence_round_trip_and_reload_stability(tmp_path):
    experiment_a = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    reg1 = _build_execution(experiment_registration=experiment_a, attempt_number=1)
    reg2 = _build_execution(
        experiment_registration=experiment_a,
        attempt_number=2,
        previous_execution_id=reg1.execution_id,
        previous_execution_hash=reg1.execution_hash,
    )
    registry_file = tmp_path / "registry.json"
    _persist_registry(registry_file, (reg1, reg2))
    loaded_a = execution_registry.load_offline_research_experiment_execution_registry(registry_file)
    loaded_b = execution_registry.load_offline_research_experiment_execution_registry(registry_file)

    assert loaded_a.as_dict() == loaded_b.as_dict()
    assert loaded_a.registry_hash == loaded_b.registry_hash
    assert registry_file.read_text(encoding="utf-8") == registry_file.read_text(encoding="utf-8")


def test_phase42_rejects_phase41_tampering_and_hash_mismatch(tmp_path):
    _, _, phase41_record = _phase41_registry_bundle(
        tmp_path,
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
    )
    tampered = json.loads(json.dumps(serialize_value(phase41_record.as_dict()), ensure_ascii=False, sort_keys=True))
    tampered["record_hash"] = "0" * 64
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryIntegrityError, match="experiment_registration_hash mismatch"):
        _build_execution(experiment_registration=tampered, attempt_number=1)


def test_phase42_rejects_missing_unexpected_empty_invalid_schema(tmp_path):
    registry_file = tmp_path / "registry.json"
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError, match="missing"):
        execution_registry.load_offline_research_experiment_execution_registry(registry_file)
    registry_file.write_text("", encoding="utf-8")
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError, match="empty"):
        execution_registry.load_offline_research_experiment_execution_registry(registry_file)
    registry_file.write_text("{not-json", encoding="utf-8")
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError, match="invalid JSON"):
        execution_registry.load_offline_research_experiment_execution_registry(registry_file)

    experiment_a = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    record = _build_execution(experiment_registration=experiment_a, attempt_number=1)
    _persist_registry(registry_file, (record,))
    payload = json.loads(registry_file.read_text(encoding="utf-8"))
    payload["schema_version"] = 99
    registry_file.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError, match="schema_version must be 1"):
        execution_registry.load_offline_research_experiment_execution_registry(registry_file)

    payload = json.loads(json.dumps(serialize_value(record.as_dict()), ensure_ascii=False, sort_keys=True))
    payload.pop("execution_reason")
    registry_file.write_text(json.dumps({"schema_version": 1, "registry_id": execution_registry.OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_ID, "registry_version": execution_registry.OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_VERSION, "created_at_utc": "2026-07-27T17:00:00Z", "updated_at_utc": "2026-07-27T17:00:00Z", "offline_only": True, "historical_research_only": True, "operational_evidence": False, "paper_promotion_eligible": False, "non_operational_declaration": execution_registry.OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_NON_OPERATIONAL_DECLARATION, "records": [payload], "registry_hash": "0" * 64}, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError):
        execution_registry.load_offline_research_experiment_execution_registry(registry_file)

    payload = json.loads(json.dumps(serialize_value(record.as_dict()), ensure_ascii=False, sort_keys=True))
    payload["execution_hash"] = "1" * 64
    registry_file.write_text(json.dumps({"schema_version": 1, "registry_id": execution_registry.OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_ID, "registry_version": execution_registry.OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_VERSION, "created_at_utc": "2026-07-27T17:00:00Z", "updated_at_utc": "2026-07-27T17:00:00Z", "offline_only": True, "historical_research_only": True, "operational_evidence": False, "paper_promotion_eligible": False, "non_operational_declaration": execution_registry.OFFLINE_RESEARCH_EXPERIMENT_EXECUTION_REGISTRY_NON_OPERATIONAL_DECLARATION, "records": [payload], "registry_hash": "0" * 64}, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryIntegrityError):
        execution_registry.load_offline_research_experiment_execution_registry(registry_file)


def test_phase42_partial_write_preserves_previous_registry(tmp_path, monkeypatch):
    experiment_a = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    record = _build_execution(experiment_registration=experiment_a, attempt_number=1)
    registry_file = tmp_path / "registry.json"
    _persist_registry(registry_file, (record,))
    original_text = registry_file.read_text(encoding="utf-8")

    def _fail(*args, **kwargs):
        raise OSError("simulated write failure")

    monkeypatch.setattr(execution_registry.os, "replace", _fail, raising=True)
    second = _build_execution(
        experiment_registration=experiment_a,
        attempt_number=2,
        previous_execution_id=record.execution_id,
        previous_execution_hash=record.execution_hash,
    )
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError, match="failed to write"):
        execution_registry.save_offline_research_experiment_execution_registry(
            registry_file,
            execution_registry.OfflineResearchExperimentExecutionRegistry(
                registry_file=registry_file,
                created_at_utc=EXECUTION_CREATED_AT_UTC,
                updated_at_utc=EXECUTION_CREATED_AT_UTC + ONE_HOUR,
                records=(record, second),
            ),
        )
    assert registry_file.read_text(encoding="utf-8") == original_text


def test_phase42_rejects_non_serializable_and_operational_payload(monkeypatch):
    experiment_a = _synthetic_phase41_registration(
        experiment_id="synthetic_experiment_a",
        experiment_version="phase41_synthetic_v1",
        label="alpha",
        registered_at_utc=datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(execution_registry.OfflineResearchExperimentExecutionRegistryValidationError):
        _build_execution(experiment_registration=experiment_a, attempt_number=1, execution_context={"bad": object()})

    monkeypatch.setattr(backtest, "run_first_offline_okx_backtest_experiment", _forbidden, raising=True)
    monkeypatch.setattr(backtest.LeakFreeBacktestEngine, "run", _forbidden, raising=True)
    record = _build_execution(experiment_registration=experiment_a, attempt_number=1)
    assert record.offline_only is True
    assert record.historical_research_only is True
    assert record.operational_evidence is False
    assert record.paper_promotion_eligible is False
    assert record.execution_status == "REGISTERED"
