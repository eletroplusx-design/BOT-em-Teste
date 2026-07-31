from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from domain import Candle, DataSource

import market_data.offline_research_backtest as backtest
import market_data.okx_historical as okx
import market_data.research_artifact_registry as registry

ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)
START_UTC = registry.OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC
END_EXCLUSIVE_UTC = registry.OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC
TOTAL_CANDLES = registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT
PAGE_COUNT = (TOTAL_CANDLES + okx.OKX_HISTORICAL_REQUEST_LIMIT - 1) // okx.OKX_HISTORICAL_REQUEST_LIMIT
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


def _candle(open_time: datetime, *, base: int) -> Candle:
    return Candle.from_dict(
        {
            "open_time": open_time,
            "close_time": open_time + ONE_HOUR - ONE_MS,
            "open": str(base),
            "high": str(base + 5),
            "low": str(base - 2),
            "close": str(base + 1),
            "volume": str(1000 + base),
            "symbol": okx.OKX_HISTORICAL_SYMBOL,
            "interval": okx.OKX_HISTORICAL_CANDLE_INTERVAL,
            "source": DataSource.OKX,
        }
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


@pytest.fixture(scope="module")
def persistent_artifact(tmp_path_factory):
    root = tmp_path_factory.mktemp("phase34-okx-persistent-artifact")
    return _build_persistent_artifact(root)


def _copy_artifact_files(src_dataset: Path, src_manifest: Path, dst_root: Path) -> tuple[Path, Path]:
    dst_root.mkdir(parents=True, exist_ok=True)
    dst_dataset = dst_root / src_dataset.name
    dst_manifest = dst_root / src_manifest.name
    shutil.copyfile(src_dataset, dst_dataset)
    shutil.copyfile(src_manifest, dst_manifest)
    return dst_dataset, dst_manifest


def _copy_registry(
    src_registry: Path,
    dst_root: Path,
    *,
    mutate: dict[str, object] | None = None,
    refresh_hashes: bool = False,
) -> Path:
    dst_root.mkdir(parents=True, exist_ok=True)
    payload = json.loads(src_registry.read_text(encoding="utf-8"))
    if mutate:
        payload.update(mutate)
    if refresh_hashes:
        payload["artifact_id"] = ""
        payload["registry_hash"] = ""
        payload = registry.ResearchArtifactRegistryEntry.from_dict(payload).as_dict()
    dst_registry = dst_root / src_registry.name
    dst_registry.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return dst_registry


def test_resolve_okx_persistent_artifact_accepts_qualified_fixture_without_running_strategy_or_backtest(
    persistent_artifact, monkeypatch
):
    forbidden_calls = []

    def _forbidden(*args, **kwargs):
        forbidden_calls.append((args, kwargs))
        raise AssertionError("operational code must not be reached")

    monkeypatch.setattr(backtest, "run_first_offline_okx_backtest_experiment", _forbidden, raising=True)
    monkeypatch.setattr(backtest, "_build_strategy_callable", _forbidden, raising=True)
    monkeypatch.setattr(backtest.LeakFreeBacktestEngine, "run", _forbidden, raising=True)

    resolution = backtest.resolve_okx_persistent_artifact(
        registry_file=persistent_artifact["registry_file"],
        dataset_file=persistent_artifact["dataset_file"],
        manifest_file=persistent_artifact["manifest_file"],
    )

    assert resolution.registry_file == persistent_artifact["registry_file"]
    assert resolution.dataset_file == persistent_artifact["dataset_file"]
    assert resolution.manifest_file == persistent_artifact["manifest_file"]
    assert resolution.artifact_root == persistent_artifact["artifact_dir"]
    assert resolution.registry_report.approved is True
    assert resolution.registry_report.historical_research_only is True
    assert resolution.registry_report.operational_evidence is False
    assert resolution.registry_report.paper_promotion_eligible is False
    assert resolution.dataset_report["historical_research_only"] is True
    assert resolution.dataset_report["operational_evidence"] is False
    assert resolution.dataset_report["paper_promotion_eligible"] is False
    assert resolution.dataset_report["dataset_hash"] == resolution.registry_report.dataset_sha256
    assert resolution.dataset_report["manifest_hash"] == resolution.registry_report.manifest_hash
    assert resolution.dataset_report["contract_hash"]
    assert not forbidden_calls


def test_discover_okx_persistent_artifact_paths_prefers_persistent_root(persistent_artifact):
    dataset_file, manifest_file = backtest.discover_okx_persistent_artifact_paths(root=persistent_artifact["root"])

    assert dataset_file == persistent_artifact["dataset_file"]
    assert manifest_file == persistent_artifact["manifest_file"]


def test_resolve_okx_persistent_artifact_rejects_pytest_tmp_fixture():
    repo_root = Path(__file__).resolve().parents[1]
    root = repo_root / ".pytest_tmp" / "phase34-reject"
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
        backtest.resolve_okx_persistent_artifact(
            registry_file=registry_file,
            dataset_file=dataset_file,
            manifest_file=manifest_file,
        )


@pytest.mark.parametrize(
    ("mutate_registry", "mutate_manifest", "expected"),
    [
        ({"provider_name": "KuCoin"}, None, "provider_name must be OKX"),
        ({"market_type": "futures"}, None, "market_type must be spot"),
        ({"instrument": "BTCUSDT"}, None, "instrument must be BTC-USDT"),
        ({"symbol": "BTC-USDT"}, None, "symbol must be BTCUSDT"),
        ({"interval": "15m"}, None, "interval must be 1H"),
        ({"dataset_sha256": "0" * 64}, None, "dataset_sha256 must match"),
        ({"manifest_sha256": "0" * 64}, None, "manifest_sha256 must match"),
        (None, {"dataset_hash": "0" * 64}, "manifest_hash mismatch"),
    ],
)
def test_resolve_okx_persistent_artifact_rejects_hash_manifest_and_contract_divergence(
    persistent_artifact,
    tmp_path,
    mutate_registry,
    mutate_manifest,
    expected,
):
    artifact_root = tmp_path / "persistent-copy"
    artifact_dir = artifact_root / "okx"
    registry_dir = artifact_root / "phase20a-okx-research-artifact-registry"
    dataset_file, manifest_file = _copy_artifact_files(
        persistent_artifact["dataset_file"], persistent_artifact["manifest_file"], artifact_dir
    )
    registry_file = _copy_registry(
        persistent_artifact["registry_file"],
        registry_dir,
        mutate={**(mutate_registry or {}), "external_artifact_ref": artifact_dir.as_posix()},
        refresh_hashes=(mutate_registry is None and mutate_manifest is not None),
    )
    if mutate_manifest is not None:
        payload = json.loads(manifest_file.read_text(encoding="utf-8"))
        payload.update(mutate_manifest)
        manifest_file.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")

    with pytest.raises(backtest.OfflineResearchBacktestError, match=expected):
        backtest.resolve_okx_persistent_artifact(
            registry_file=registry_file,
            dataset_file=dataset_file,
            manifest_file=manifest_file,
        )


def test_resolve_okx_persistent_artifact_rejects_missing_dataset_or_manifest(persistent_artifact, tmp_path):
    artifact_root = tmp_path / "missing-files"
    artifact_dir = artifact_root / "okx"
    registry_dir = artifact_root / "phase20a-okx-research-artifact-registry"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    registry_dir.mkdir(parents=True, exist_ok=True)
    registry_file = _copy_registry(
        persistent_artifact["registry_file"],
        registry_dir,
        mutate={"external_artifact_ref": artifact_dir.as_posix()},
    )
    dataset_file = artifact_dir / okx.OKX_HISTORICAL_DATASET_CANDLES_FILENAME
    manifest_file = artifact_dir / okx.OKX_HISTORICAL_MANIFEST_FILENAME

    with pytest.raises(backtest.OfflineResearchBacktestValidationError, match="dataset file is missing"):
        backtest.resolve_okx_persistent_artifact(
            registry_file=registry_file,
            dataset_file=dataset_file,
            manifest_file=manifest_file,
        )

    dataset_file.write_text("[]", encoding="utf-8")
    with pytest.raises(backtest.OfflineResearchBacktestValidationError, match="manifest file is missing"):
        backtest.resolve_okx_persistent_artifact(
            registry_file=registry_file,
            dataset_file=dataset_file,
            manifest_file=manifest_file,
        )
