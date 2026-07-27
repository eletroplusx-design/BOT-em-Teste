from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

import market_data.okx_historical as okx
import market_data.research_artifact_registry as registry
import market_data.research_artifact_registry_verification as verification
from datetime import timedelta
from market_data import HistoricalProviderQualification
from market_data.errors import HistoricalDataValidationError


ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)
START_UTC = registry.OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC
END_EXCLUSIVE_UTC = registry.OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC
ACTUAL_REGISTRY_FILE = (
    Path.home()
    / ".codex"
    / "artifacts"
    / "BOT-em-Teste"
    / "phase20a-okx-research-artifact-registry"
    / "okx-research-artifact-registry.json"
)
ACTUAL_REGISTRY_EXTERNAL_ARTIFACT_REF = (
    Path.home()
    / ".codex"
    / "artifacts"
    / "BOT-em-Teste"
    / "phase19c-okx-20260727T000000Z"
    / "okx"
)


def _workspace_tmp_dir(name: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp" / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _fail_network(*args, **kwargs):
    raise AssertionError("network must not be reached")


def _base_entry_payload() -> dict[str, object]:
    entry = registry.ResearchArtifactRegistryEntry(
        registered_at_utc=datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc),
        external_artifact_ref="artifact://okx/phase19c/research-only",
        dataset_sha256=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256,
        manifest_sha256=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256,
        manifest_hash=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH,
    )
    return json.loads(json.dumps(entry.as_dict(), ensure_ascii=False))


def _write_registry_file(root: Path, payload: dict[str, object]) -> Path:
    file_path = root / "okx-research-artifact-registry.json"
    file_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return file_path


def _verify_payload(payload: dict[str, object]) -> verification.ResearchArtifactRegistryVerificationReport:
    root = _workspace_tmp_dir(f"okx-phase20b-{os.getpid()}-{abs(hash(json.dumps(payload, sort_keys=True, default=str)))}")
    registry_file = _write_registry_file(root, payload)
    return verification.verify_okx_research_artifact_registry(registry_file)


def test_okx_research_artifact_registry_verification_accepts_valid_registry_and_stays_read_only(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, "get", _fail_network, raising=True)
    monkeypatch.setattr(okx.OkxPublicSpotHistoryCandlesProvider, "fetch_klines", _fail_network, raising=True)

    payload = _base_entry_payload()
    registry_file = _write_registry_file(_workspace_tmp_dir(f"okx-phase20b-valid-{os.getpid()}"), payload)
    before = registry_file.read_text(encoding="utf-8")

    report = verification.verify_okx_research_artifact_registry(
        registry_file,
        expected_external_artifact_ref="artifact://okx/phase19c/research-only",
    )

    after = registry_file.read_text(encoding="utf-8")
    assert before == after
    assert report.approved is True
    assert report.provider_name == "OKX"
    assert report.market_type == "spot"
    assert report.instrument == "BTC-USDT"
    assert report.symbol == "BTCUSDT"
    assert report.interval == "1H"
    assert report.expected_candle_count == 42816
    assert report.audited_candle_count == 42816
    assert report.dataset_sha256 == registry.OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256
    assert report.manifest_sha256 == registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256
    assert report.manifest_hash == registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH
    assert report.audit_status == "passed"
    assert report.external_artifact_ref == "artifact://okx/phase19c/research-only"
    assert report.external_artifact_ref_is_opaque is True
    assert report.external_artifact_ref_is_local is True
    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.verification_hash


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda payload: payload.__setitem__("provider_name", "KuCoin"), "provider_name must be OKX"),
        (lambda payload: payload.__setitem__("market_type", "futures"), "market_type must be spot"),
        (lambda payload: payload.__setitem__("instrument", "BTCUSDT"), "instrument must be BTC-USDT"),
        (lambda payload: payload.__setitem__("symbol", "BTC-USDT"), "symbol must be BTCUSDT"),
        (lambda payload: payload.__setitem__("requested_start_inclusive_utc", "2021-02-12T01:00:00Z"), "requested_start_inclusive_utc diverges"),
        (lambda payload: payload.__setitem__("requested_end_exclusive_utc", "2026-01-01T01:00:00Z"), "requested_end_exclusive_utc diverges"),
        (lambda payload: payload.__setitem__("expected_candle_count", 42815), "expected_candle_count must be 42816"),
        (lambda payload: payload.__setitem__("audited_candle_count", 42815), "audited_candle_count must match"),
        (lambda payload: payload.__setitem__("dataset_sha256", "0" * 64), "dataset_sha256 must match"),
        (lambda payload: payload.__setitem__("manifest_sha256", "0" * 64), "manifest_sha256 must match"),
        (lambda payload: payload.__setitem__("manifest_hash", "0" * 64), "manifest_hash must match"),
        (lambda payload: payload.__setitem__("audit_status", "failed"), "audit_status must be passed"),
        (lambda payload: payload.__setitem__("historical_research_only", False), "historical_research_only must be true"),
        (lambda payload: payload.__setitem__("operational_evidence", True), "operational_evidence must be false"),
        (lambda payload: payload.__setitem__("paper_promotion_eligible", True), "paper_promotion_eligible must be false"),
        (
            lambda payload: (
                payload.__setitem__("artifact_id", ""),
                payload.__setitem__("registry_hash", ""),
                payload.__setitem__("external_artifact_ref", "{"),
            ),
            "opaque local reference",
        ),
        (
            lambda payload: (
                payload.__setitem__("artifact_id", ""),
                payload.__setitem__("registry_hash", ""),
                payload.__setitem__("external_artifact_ref", "open_time=2021-02-12"),
            ),
            "must not embed dataset content",
        ),
        (
            lambda payload: (
                payload.__setitem__("artifact_id", ""),
                payload.__setitem__("registry_hash", ""),
                payload.__setitem__("external_artifact_ref", "dataset payload"),
            ),
            "opaque local path or URI",
        ),
        (
            lambda payload: (
                payload.__setitem__("artifact_id", ""),
                payload.__setitem__("registry_hash", ""),
                payload.__setitem__("non_operational_declaration", "Replay is allowed."),
            ),
            "diverges from the OKX research artifact contract",
        ),
    ],
)
def test_okx_research_artifact_registry_verification_rejects_critical_divergences(mutator, expected):
    payload = _base_entry_payload()
    mutator(payload)
    registry_file = _write_registry_file(_workspace_tmp_dir(f"okx-phase20b-divergence-{abs(hash(expected))}"), payload)
    with pytest.raises((verification.ResearchArtifactRegistryVerificationValidationError, verification.ResearchArtifactRegistryVerificationIntegrityError), match=expected):
        verification.verify_okx_research_artifact_registry(registry_file)


def test_okx_research_artifact_registry_verification_rejects_operational_use_cases():
    payload = _base_entry_payload()
    registry_file = _write_registry_file(_workspace_tmp_dir(f"okx-phase20b-usecase-{os.getpid()}"), payload)

    entry = registry.ResearchArtifactRegistryEntry.from_dict(payload)
    with pytest.raises(HistoricalDataValidationError, match="not authorized"):
        registry.validate_research_artifact_registry_entry(entry, use_case="replay")


def test_okx_research_artifact_registry_verification_rejects_write_attempts(monkeypatch):
    payload = _base_entry_payload()
    registry_file = _write_registry_file(_workspace_tmp_dir(f"okx-phase20b-nowrite-{os.getpid()}"), payload)

    def _fail_write(*args, **kwargs):
        raise AssertionError("write must not be reached")

    monkeypatch.setattr(Path, "write_text", _fail_write, raising=True)
    monkeypatch.setattr(Path, "unlink", _fail_write, raising=True)
    monkeypatch.setattr(os, "replace", _fail_write, raising=True)
    result = verification.verify_okx_research_artifact_registry(registry_file)

    assert result.approved is True
    assert registry_file.read_text(encoding="utf-8") == json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_okx_research_artifact_registry_verification_keeps_okx_separate_from_kucoin():
    kucoin_qualification = HistoricalProviderQualification.kucoin_public_spot(symbol="BTCUSDT", interval="1h")
    assert kucoin_qualification.exchange == "kucoin"

    payload = _base_entry_payload()
    payload["provider_name"] = "KuCoin"
    registry_file = _write_registry_file(_workspace_tmp_dir(f"okx-phase20b-kucoin-{os.getpid()}"), payload)
    with pytest.raises(verification.ResearchArtifactRegistryVerificationValidationError, match="provider_name must be OKX"):
        verification.verify_okx_research_artifact_registry(registry_file)


def test_okx_research_artifact_registry_verification_rejects_missing_registry():
    missing = _workspace_tmp_dir(f"okx-phase20b-missing-{os.getpid()}") / "missing.json"
    with pytest.raises(verification.ResearchArtifactRegistryVerificationValidationError, match="missing"):
        verification.verify_okx_research_artifact_registry(missing)


@pytest.mark.skipif(not ACTUAL_REGISTRY_FILE.exists(), reason="external registry is not available in this environment")
def test_okx_research_artifact_registry_verification_on_actual_registry_is_read_only(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, "get", _fail_network, raising=True)
    monkeypatch.setattr(okx.OkxPublicSpotHistoryCandlesProvider, "fetch_klines", _fail_network, raising=True)

    before = ACTUAL_REGISTRY_FILE.read_text(encoding="utf-8")
    report = verification.verify_okx_research_artifact_registry(
        ACTUAL_REGISTRY_FILE,
        expected_external_artifact_ref=str(ACTUAL_REGISTRY_EXTERNAL_ARTIFACT_REF),
    )
    after = ACTUAL_REGISTRY_FILE.read_text(encoding="utf-8")

    assert before == after
    assert report.approved is True
    assert report.provider_name == "OKX"
    assert report.expected_candle_count == 42816
    assert report.external_artifact_ref == str(ACTUAL_REGISTRY_EXTERNAL_ARTIFACT_REF)
