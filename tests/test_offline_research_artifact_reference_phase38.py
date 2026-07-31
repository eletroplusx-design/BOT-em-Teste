from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

import market_data.offline_research_backtest as backtest
import market_data.offline_research_execution_gate_diagnostic as execution_gate_diagnostic
import market_data.offline_research_signal_gap_diagnostic as signal_gap_diagnostic
import market_data.okx_historical as okx
import market_data.research_artifact_registry as registry
from domain.serialization import serialize_value


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


def _copy_registry(
    src_registry: Path,
    dst_root: Path,
    *,
    external_artifact_ref: str,
    mutate: dict[str, object] | None = None,
    refresh_hashes: bool = False,
) -> Path:
    dst_root.mkdir(parents=True, exist_ok=True)
    payload = json.loads(src_registry.read_text(encoding="utf-8"))
    if mutate:
        payload.update(mutate)
    payload["external_artifact_ref"] = external_artifact_ref
    if refresh_hashes:
        payload["artifact_id"] = ""
        payload["registry_hash"] = ""
        payload = registry.ResearchArtifactRegistryEntry.from_dict(payload).as_dict()
    dst_registry = dst_root / src_registry.name
    dst_registry.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return dst_registry


@pytest.fixture(scope="module")
def persistent_artifact(tmp_path_factory):
    root = tmp_path_factory.mktemp("phase38-okx-persistent-artifact")
    return _build_persistent_artifact(root)


def _forbidden(*args, **kwargs):
    raise AssertionError("unexpected operational or legacy discovery call")


def test_offline_research_artifact_reference_accepts_prevalidated_resolution_without_legacy_diagnostics(
    persistent_artifact, monkeypatch
):
    resolution = backtest.resolve_okx_persistent_artifact(
        registry_file=persistent_artifact["registry_file"],
        dataset_file=persistent_artifact["dataset_file"],
        manifest_file=persistent_artifact["manifest_file"],
    )

    monkeypatch.setattr(backtest, "resolve_okx_persistent_artifact", _forbidden, raising=True)
    monkeypatch.setattr(backtest, "discover_okx_phase19a_artifact_paths", _forbidden, raising=True)
    monkeypatch.setattr(backtest, "run_first_offline_okx_backtest_experiment", _forbidden, raising=True)
    monkeypatch.setattr(backtest.LeakFreeBacktestEngine, "run", _forbidden, raising=True)
    monkeypatch.setattr(execution_gate_diagnostic, "discover_okx_phase24_artifact_paths", _forbidden, raising=True)
    monkeypatch.setattr(signal_gap_diagnostic, "discover_okx_phase26_artifact_paths", _forbidden, raising=True)

    reference = backtest.resolve_okx_offline_research_artifact_reference(resolution=resolution)

    assert reference.resolution is resolution
    assert reference.read_only is True
    assert reference.historical_research_only is True
    assert reference.operational_evidence is False
    assert reference.paper_promotion_eligible is False
    assert reference.purpose == "offline_historical_research"
    assert reference.registry_file == persistent_artifact["registry_file"]
    assert reference.dataset_file == persistent_artifact["dataset_file"]
    assert reference.manifest_file == persistent_artifact["manifest_file"]
    assert reference.artifact_root == persistent_artifact["artifact_dir"]
    assert reference.registry_report.approved is True
    assert reference.registry_report.historical_research_only is True
    assert reference.registry_report.operational_evidence is False
    assert reference.registry_report.paper_promotion_eligible is False
    assert reference.dataset_report["historical_research_only"] is True
    assert reference.dataset_report["operational_evidence"] is False
    assert reference.dataset_report["paper_promotion_eligible"] is False


def test_offline_research_artifact_reference_resolves_explicit_paths_and_uses_persistent_resolver(
    persistent_artifact, monkeypatch
):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    real_resolver = backtest.resolve_okx_persistent_artifact

    def _tracking_resolver(*args, **kwargs):
        calls.append((args, kwargs))
        return real_resolver(*args, **kwargs)

    monkeypatch.setattr(backtest, "resolve_okx_persistent_artifact", _tracking_resolver, raising=True)
    monkeypatch.setattr(backtest, "discover_okx_phase19a_artifact_paths", _forbidden, raising=True)

    reference = backtest.resolve_okx_offline_research_artifact_reference(
        registry_file=persistent_artifact["registry_file"],
        dataset_file=persistent_artifact["dataset_file"],
        manifest_file=persistent_artifact["manifest_file"],
    )

    assert len(calls) == 1
    assert reference.registry_file == persistent_artifact["registry_file"]
    assert reference.dataset_file == persistent_artifact["dataset_file"]
    assert reference.manifest_file == persistent_artifact["manifest_file"]
    assert reference.registry_report.approved is True
    assert reference.historical_research_only is True
    assert reference.operational_evidence is False
    assert reference.paper_promotion_eligible is False


def test_offline_research_artifact_reference_freezes_dataset_report_deeply(persistent_artifact):
    resolution = backtest.resolve_okx_persistent_artifact(
        registry_file=persistent_artifact["registry_file"],
        dataset_file=persistent_artifact["dataset_file"],
        manifest_file=persistent_artifact["manifest_file"],
    )
    nested_report = {
        "outer": {
            "items": [1, {"leaf": "x"}],
            "flags": {"enabled": True},
        }
    }
    object.__setattr__(resolution, "dataset_report", nested_report)
    reference = backtest.resolve_okx_offline_research_artifact_reference(resolution=resolution)

    with pytest.raises(TypeError):
        reference.dataset_report["outer"] = {}
    with pytest.raises(TypeError):
        reference.dataset_report["outer"]["items"][1]["leaf"] = "y"

    object.__setattr__(resolution, "dataset_report", {"outer": {"items": [9, {"leaf": "z"}]}})
    assert reference.dataset_report["outer"]["items"][0] == 1
    assert reference.dataset_report["outer"]["items"][1]["leaf"] == "x"


@pytest.mark.parametrize(
    ("resolution", "registry_file", "dataset_file", "manifest_file", "expected"),
    [
        (None, None, None, None, "registry_file, dataset_file and manifest_file are required"),
        ("not-a-resolution", None, None, None, "resolution must be a verified persistent OKX artifact resolution."),
    ],
)
def test_offline_research_artifact_reference_rejects_invalid_entrypoint_inputs(
    resolution,
    registry_file,
    dataset_file,
    manifest_file,
    expected,
):
    with pytest.raises(backtest.OfflineResearchBacktestValidationError, match=expected):
        backtest.resolve_okx_offline_research_artifact_reference(
            resolution=resolution,
            registry_file=registry_file,
            dataset_file=dataset_file,
            manifest_file=manifest_file,
        )


def test_offline_research_artifact_reference_rejects_pytest_tmp_fixture_paths(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    root = repo_root / ".pytest_tmp" / "phase38-reject"
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
        backtest.resolve_okx_offline_research_artifact_reference(
            registry_file=registry_file,
            dataset_file=dataset_file,
            manifest_file=manifest_file,
        )


@pytest.mark.parametrize(
    ("mutate_registry", "mutate_manifest", "expected"),
    [
        ({"provider_name": "KuCoin"}, None, "provider_name must be OKX"),
        ({"market_type": "futures"}, None, "market_type must be spot"),
        (None, {"manifest_hash": "0" * 64}, "manifest_hash mismatch"),
    ],
)
def test_offline_research_artifact_reference_rejects_divergent_contract_and_hashes_via_explicit_paths(
    persistent_artifact,
    tmp_path,
    mutate_registry,
    mutate_manifest,
    expected,
):
    artifact_root = tmp_path / "persistent-copy"
    artifact_dir = artifact_root / "okx"
    registry_dir = artifact_root / "phase20a-okx-research-artifact-registry"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    registry_dir.mkdir(parents=True, exist_ok=True)
    dataset_file = artifact_dir / okx.OKX_HISTORICAL_DATASET_CANDLES_FILENAME
    manifest_file = artifact_dir / okx.OKX_HISTORICAL_MANIFEST_FILENAME
    shutil.copyfile(persistent_artifact["dataset_file"], dataset_file)
    shutil.copyfile(persistent_artifact["manifest_file"], manifest_file)
    if mutate_manifest:
        manifest_payload = json.loads(manifest_file.read_text(encoding="utf-8"))
        manifest_payload.update(mutate_manifest)
        manifest_file.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
    registry_file = _copy_registry(
        persistent_artifact["registry_file"],
        registry_dir,
        external_artifact_ref=artifact_dir.as_posix(),
        mutate=mutate_registry,
        refresh_hashes=mutate_manifest is not None and mutate_registry is None,
    )

    with pytest.raises(backtest.OfflineResearchBacktestError, match=expected):
        backtest.resolve_okx_offline_research_artifact_reference(
            registry_file=registry_file,
            dataset_file=dataset_file,
            manifest_file=manifest_file,
        )


def test_offline_research_artifact_reference_rejects_artifact_id_mismatch_with_separate_case(persistent_artifact, tmp_path):
    artifact_root = tmp_path / "persistent-copy-artifact-id"
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
            serialize_value(
                registry_entry.canonical_payload(include_registry_hash=False)
            ),
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
        backtest.resolve_okx_offline_research_artifact_reference(
            registry_file=registry_file,
            dataset_file=dataset_file,
            manifest_file=manifest_file,
        )
