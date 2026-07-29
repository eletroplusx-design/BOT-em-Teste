from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os

import pytest
import requests

import market_data.okx_historical as okx
import market_data.offline_research_experiment_authorization as authorization
import market_data.research_artifact_registry as registry
import market_data.research_artifact_registry_verification as verification
from market_data import HistoricalProviderQualification
from strategies.baseline_a import BASELINE_A_CANDIDATE, baseline_a_candidate_config
from domain.serialization import serialize_value


def _fail_network(*args, **kwargs):
    raise AssertionError("network must not be reached")


def _verified_report() -> verification.ResearchArtifactRegistryVerificationReport:
    registry_entry = registry.ResearchArtifactRegistryEntry(
        registered_at_utc=datetime(2026, 7, 27, 16, 31, 31, tzinfo=timezone.utc),
        external_artifact_ref="artifact://okx/phase19c/research-only",
        dataset_sha256=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256,
        manifest_sha256=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256,
        manifest_hash=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH,
    )
    return verification.ResearchArtifactRegistryVerificationReport(
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
        external_artifact_ref="artifact://okx/phase19c/research-only",
        external_artifact_ref_is_opaque=True,
        external_artifact_ref_is_local=True,
        historical_research_only=True,
        operational_evidence=False,
        paper_promotion_eligible=False,
        non_operational_declaration=registry.OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION,
        verification_hash="",
    )


def _tamper_report(report: verification.ResearchArtifactRegistryVerificationReport, **changes):
    for field_name, value in changes.items():
        object.__setattr__(report, field_name, value)
    return report


def test_offline_research_experiment_authorization_accepts_verified_report_and_stays_read_only(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, "get", _fail_network, raising=True)
    monkeypatch.setattr(okx.OkxPublicSpotHistoryCandlesProvider, "fetch_klines", _fail_network, raising=True)
    monkeypatch.setattr(Path, "write_text", _fail_network, raising=True)
    monkeypatch.setattr(Path, "unlink", _fail_network, raising=True)
    monkeypatch.setattr(os, "replace", _fail_network, raising=True)

    report = _verified_report()
    authorization_record = authorization.authorize_offline_research_experiment(
        report,
        issued_at_utc=datetime(2026, 7, 27, 16, 31, 33, tzinfo=timezone.utc),
    )

    assert authorization_record.purpose == authorization.OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PURPOSE
    assert authorization_record.allowed_use_cases == ("experiment_contract_validation",)
    assert authorization_record.prohibited_use_cases == authorization.OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PROHIBITED_USE_CASES
    assert authorization_record.provider_name == "OKX"
    assert authorization_record.market_type == "spot"
    assert authorization_record.instrument == "BTC-USDT"
    assert authorization_record.symbol == "BTCUSDT"
    assert authorization_record.interval == "1H"
    assert authorization_record.requested_start_inclusive_utc == registry.OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC
    assert authorization_record.requested_end_exclusive_utc == registry.OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC
    assert authorization_record.candle_count == 42816
    assert authorization_record.dataset_sha256 == registry.OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256
    assert authorization_record.manifest_sha256 == registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256
    assert authorization_record.manifest_hash == registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH
    assert authorization_record.verification_registry_file == report.registry_file
    assert authorization_record.canonical_payload()["verification_registry_file"] == report.registry_file.as_posix()
    assert authorization_record.verification_result_hash == report.verification_hash
    assert authorization_record.verification_audit_status == "passed"
    assert authorization_record.historical_research_only is True
    assert authorization_record.operational_evidence is False
    assert authorization_record.paper_promotion_eligible is False
    assert authorization_record.authorization_id
    assert authorization_record.authorization_hash
    assert authorization_record.as_dict() == serialize_value(authorization_record.canonical_payload())


def test_offline_research_experiment_authorization_accepts_empty_allowed_use_cases():
    report = _verified_report()
    authorization_record = authorization.authorize_offline_research_experiment(
        report,
        allowed_use_cases=(),
    )

    assert authorization_record.allowed_use_cases == ()
    assert authorization_record.purpose == "offline_historical_research"


@pytest.mark.parametrize(
    "allowed_use_cases",
    [
        ("replay",),
        ("backtest",),
        ("walk_forward",),
        ("performance",),
        ("ranking",),
        ("paper",),
        ("live",),
        ("execution",),
        ("order_submission",),
    ],
)
def test_offline_research_experiment_authorization_rejects_operational_uses(allowed_use_cases):
    report = _verified_report()
    with pytest.raises(
        authorization.OfflineResearchExperimentAuthorizationValidationError,
        match="prohibited operational use cases",
    ):
        authorization.authorize_offline_research_experiment(report, allowed_use_cases=allowed_use_cases)


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda report: _tamper_report(report, provider_name="KuCoin"), "provider_name must be OKX"),
        (lambda report: _tamper_report(report, market_type="futures"), "market_type must be spot"),
        (lambda report: _tamper_report(report, instrument="BTCUSDT"), "instrument must be BTC-USDT"),
        (lambda report: _tamper_report(report, symbol="BTC-USDT"), "symbol must be BTCUSDT"),
        (
            lambda report: _tamper_report(
                report,
                requested_start_inclusive_utc=datetime(2026, 7, 27, 17, 31, 32, tzinfo=timezone.utc),
            ),
            "requested_start_inclusive_utc diverges",
        ),
        (
            lambda report: _tamper_report(
                report,
                requested_end_exclusive_utc=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
            ),
            "requested_end_exclusive_utc diverges",
        ),
        (lambda report: _tamper_report(report, expected_candle_count=42815), "expected_candle_count must be 42816"),
        (lambda report: _tamper_report(report, audited_candle_count=42815), "audited_candle_count must be 42816"),
        (lambda report: _tamper_report(report, audit_status="failed"), "audit_status must be passed"),
        (lambda report: _tamper_report(report, historical_research_only=False), "historical_research_only must be true"),
        (lambda report: _tamper_report(report, operational_evidence=True), "operational_evidence must be false"),
        (lambda report: _tamper_report(report, paper_promotion_eligible=True), "paper_promotion_eligible must be false"),
    ],
)
def test_offline_research_experiment_authorization_rejects_contract_divergences(mutator, expected):
    report = _verified_report()
    divergent_report = mutator(report)
    with pytest.raises(
        (
            authorization.OfflineResearchExperimentAuthorizationValidationError,
            authorization.OfflineResearchExperimentAuthorizationIntegrityError,
        ),
        match=expected,
    ):
        authorization.authorize_offline_research_experiment(divergent_report)


def test_offline_research_experiment_authorization_keeps_okx_separate_from_kucoin():
    kucoin_qualification = HistoricalProviderQualification.kucoin_public_spot(symbol="BTCUSDT", interval="1h")
    assert kucoin_qualification.exchange == "kucoin"
    assert kucoin_qualification.symbol == "BTCUSDT"
    assert kucoin_qualification.external_symbol == "BTC-USDT"

    report = _tamper_report(_verified_report(), provider_name="KuCoin")
    with pytest.raises(
        authorization.OfflineResearchExperimentAuthorizationValidationError,
        match="provider_name must be OKX",
    ):
        authorization.authorize_offline_research_experiment(report)


def test_offline_research_experiment_authorization_rejects_unverified_report():
    report = _verified_report()
    unverified = _tamper_report(report, approved=False)
    with pytest.raises(
        authorization.OfflineResearchExperimentAuthorizationValidationError,
        match="verification report must be approved",
    ):
        authorization.authorize_offline_research_experiment(unverified)


def test_offline_research_experiment_authorization_does_not_change_baseline_a_contract():
    assert baseline_a_candidate_config() == BASELINE_A_CANDIDATE
