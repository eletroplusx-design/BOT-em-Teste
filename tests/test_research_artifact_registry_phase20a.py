from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

import market_data.okx_historical as okx
import market_data.research_artifact_registry as registry
from market_data.errors import HistoricalDataConflictError, HistoricalDataIntegrityError, HistoricalDataValidationError

ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)
START_UTC = registry.OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC
END_EXCLUSIVE_UTC = registry.OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC
EXPECTED_DATASET_SHA256 = registry.OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256
EXPECTED_MANIFEST_SHA256 = registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256
EXPECTED_MANIFEST_HASH = registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH


def _workspace_tmp_dir(name: str):
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp" / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _fail_network(*args, **kwargs):
    raise AssertionError("network must not be reached")


def _entry_payload() -> dict[str, object]:
    return {
        "schema_version": registry.RESEARCH_ARTIFACT_REGISTRY_SCHEMA_VERSION,
        "artifact_id": "",
        "provider_name": registry.OKX_RESEARCH_ARTIFACT_PROVIDER_NAME,
        "market_type": registry.OKX_RESEARCH_ARTIFACT_MARKET_TYPE,
        "instrument": registry.OKX_RESEARCH_ARTIFACT_INSTRUMENT,
        "symbol": registry.OKX_RESEARCH_ARTIFACT_SYMBOL,
        "interval": registry.OKX_RESEARCH_ARTIFACT_INTERVAL,
        "requested_start_inclusive_utc": START_UTC,
        "requested_end_exclusive_utc": END_EXCLUSIVE_UTC,
        "expected_candle_count": registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT,
        "audited_candle_count": registry.OKX_RESEARCH_ARTIFACT_AUDITED_CANDLE_COUNT,
        "audited_first_candle_open_utc": START_UTC,
        "audited_first_candle_close_utc": START_UTC + ONE_HOUR - ONE_MS,
        "audited_last_candle_open_utc": END_EXCLUSIVE_UTC - ONE_HOUR,
        "audited_last_candle_close_utc": END_EXCLUSIVE_UTC - ONE_MS,
        "audited_gap_count": registry.OKX_RESEARCH_ARTIFACT_AUDITED_GAP_COUNT,
        "audited_duplicate_count": registry.OKX_RESEARCH_ARTIFACT_AUDITED_DUPLICATE_COUNT,
        "audited_confirm_required_value": registry.OKX_RESEARCH_ARTIFACT_AUDITED_CONFIRM_REQUIRED_VALUE,
        "dataset_sha256": EXPECTED_DATASET_SHA256,
        "manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "manifest_hash": EXPECTED_MANIFEST_HASH,
        "audit_status": registry.OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED,
        "registered_at_utc": datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc),
        "external_artifact_ref": "artifact://okx/phase19c/research-only",
        "historical_research_only": True,
        "operational_evidence": False,
        "paper_promotion_eligible": False,
        "non_operational_declaration": registry.OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION,
        "registry_hash": "",
    }


def _entry() -> registry.ResearchArtifactRegistryEntry:
    return registry.ResearchArtifactRegistryEntry(**_entry_payload())


def test_okx_research_artifact_registry_round_trip_is_offline_and_write_once(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, "get", _fail_network, raising=True)
    monkeypatch.setattr(okx.OkxPublicSpotHistoryCandlesProvider, "fetch_klines", _fail_network, raising=True)

    entry = _entry()
    validated = registry.validate_research_artifact_registry_entry(entry, use_case="research")
    registry_path = _workspace_tmp_dir(f"okx-phase20a-registry-{os.getpid()}") / "okx-research-artifact-registry.json"

    saved = registry.save_research_artifact_registry(registry_path, validated)
    loaded = registry.load_research_artifact_registry(registry_path)
    reused = registry.save_research_artifact_registry(registry_path, entry)

    assert validated == entry
    assert saved == entry
    assert loaded == entry
    assert reused == entry
    assert loaded.artifact_id == entry.artifact_id
    assert loaded.registry_hash == entry.registry_hash
    assert loaded.historical_research_only is True
    assert loaded.operational_evidence is False
    assert loaded.paper_promotion_eligible is False
    assert loaded.provider_name == "OKX"
    assert loaded.instrument == "BTC-USDT"
    assert loaded.symbol == "BTCUSDT"
    assert loaded.interval == "1H"
    assert loaded.external_artifact_ref == "artifact://okx/phase19c/research-only"

    conflict_entry = registry.ResearchArtifactRegistryEntry(
        **{
            **_entry_payload(),
            "external_artifact_ref": "artifact://okx/phase19c/different-reference",
        }
    )
    with pytest.raises(HistoricalDataConflictError):
        registry.save_research_artifact_registry(registry_path, conflict_entry)


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda payload: payload.__setitem__("provider_name", "KuCoin"), "provider_name must be OKX"),
        (lambda payload: payload.__setitem__("market_type", "futures"), "market_type must be spot"),
        (lambda payload: payload.__setitem__("instrument", "BTCUSDT"), "instrument must be BTC-USDT"),
        (lambda payload: payload.__setitem__("symbol", "BTC-USDT"), "symbol must be BTCUSDT"),
        (
            lambda payload: payload.__setitem__(
                "requested_start_inclusive_utc", (START_UTC + ONE_HOUR).isoformat().replace("+00:00", "Z")
            ),
            "requested_start_inclusive_utc diverges",
        ),
        (
            lambda payload: payload.__setitem__(
                "requested_end_exclusive_utc", (END_EXCLUSIVE_UTC + ONE_HOUR).isoformat().replace("+00:00", "Z")
            ),
            "requested_end_exclusive_utc diverges",
        ),
        (lambda payload: payload.__setitem__("dataset_sha256", "0" * 64), "dataset_sha256 must match"),
        (lambda payload: payload.__setitem__("manifest_sha256", "0" * 64), "manifest_sha256 must match"),
        (lambda payload: payload.__setitem__("manifest_hash", "0" * 64), "manifest_hash must match"),
        (
            lambda payload: payload.__setitem__("audited_candle_count", registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT + 1),
            "audited_candle_count must match",
        ),
        (
            lambda payload: payload.__setitem__(
                "audited_first_candle_open_utc", (START_UTC + ONE_HOUR).isoformat().replace("+00:00", "Z")
            ),
            "audited_first_candle_open_utc does not match",
        ),
        (lambda payload: payload.__setitem__("audit_status", "failed"), "audit_status must be passed"),
        (lambda payload: payload.__setitem__("historical_research_only", False), "historical_research_only must be true"),
        (lambda payload: payload.__setitem__("operational_evidence", True), "operational_evidence must be false"),
        (lambda payload: payload.__setitem__("paper_promotion_eligible", True), "paper_promotion_eligible must be false"),
    ],
)
def test_okx_research_artifact_registry_rejects_divergent_contracts(mutator, expected):
    payload = _entry_payload()
    mutator(payload)
    with pytest.raises((HistoricalDataValidationError, HistoricalDataIntegrityError), match=expected):
        registry.ResearchArtifactRegistryEntry(**payload)


@pytest.mark.parametrize(
    "use_case",
    ["replay", "backtest", "performance", "ranking", "paper", "live"],
)
def test_okx_research_artifact_registry_rejects_operational_use_cases(use_case):
    entry = _entry()
    with pytest.raises(HistoricalDataValidationError, match="not authorized"):
        registry.validate_research_artifact_registry_entry(entry, use_case=use_case)


def test_okx_research_artifact_registry_rejects_promotion_or_operational_evidence():
    entry = _entry()

    with pytest.raises(HistoricalDataValidationError, match="operational_evidence must be false"):
        registry.validate_research_artifact_registry_entry(entry, use_case="registry", operational_evidence=True)

    with pytest.raises(HistoricalDataValidationError, match="paper_promotion_eligible must be false"):
        registry.validate_research_artifact_registry_entry(entry, use_case="registry", paper_promotion_eligible=True)


def test_okx_research_artifact_registry_rejects_missing_audit_status():
    payload = _entry_payload()
    payload.pop("audit_status")
    with pytest.raises(HistoricalDataValidationError, match="incomplete"):
        registry.ResearchArtifactRegistryEntry.from_dict(payload)


def test_okx_research_artifact_registry_keeps_okx_separate_from_kucoin():
    kucoin_qualification = okx.HistoricalProviderQualification.kucoin_public_spot(symbol="BTCUSDT", interval="1h")
    assert kucoin_qualification.exchange == "kucoin"

    payload = _entry_payload()
    payload["provider_name"] = "KuCoin"
    with pytest.raises(HistoricalDataValidationError, match="provider_name must be OKX"):
        registry.ResearchArtifactRegistryEntry(**payload)

    payload = _entry_payload()
    payload["instrument"] = "BTCUSDT"
    with pytest.raises(HistoricalDataValidationError, match="instrument must be BTC-USDT"):
        registry.ResearchArtifactRegistryEntry(**payload)
