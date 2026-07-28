from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os

import pytest
import requests

import market_data.okx_historical as okx
import market_data.offline_research_experiment_authorization as authorization
import market_data.offline_research_strategy_compatibility as compatibility
import market_data.research_artifact_registry as registry
import market_data.research_artifact_registry_verification as verification
from market_data import HistoricalProviderQualification
from strategies.baseline_a import BASELINE_A_CANDIDATE, BASELINE_A_INTERVAL, BASELINE_A_SYMBOL, baseline_a_backtest_config, baseline_a_candidate_config
from domain.serialization import serialize_value


def _fail_network(*args, **kwargs):
    raise AssertionError("network must not be reached")


def _verified_authorization() -> authorization.OfflineResearchExperimentAuthorization:
    registry_entry = registry.ResearchArtifactRegistryEntry(
        registered_at_utc=datetime(2026, 7, 27, 16, 31, 31, tzinfo=timezone.utc),
        external_artifact_ref="artifact://okx/phase19c/research-only",
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
        external_artifact_ref="artifact://okx/phase19c/research-only",
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
        issued_at_utc=datetime(2026, 7, 27, 16, 31, 33, tzinfo=timezone.utc),
    )


def _compatible_contract(auth: authorization.OfflineResearchExperimentAuthorization) -> compatibility.OfflineResearchStrategyCompatibilityContract:
    return compatibility.OfflineResearchStrategyCompatibilityContract(
        strategy_id="synthetic_okx_compatibility",
        strategy_version="phase21b_compatibility_v1",
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


def _tamper_contract(contract: compatibility.OfflineResearchStrategyCompatibilityContract, **changes):
    for field_name, value in changes.items():
        object.__setattr__(contract, field_name, value)
    return contract


def test_offline_research_strategy_compatibility_accepts_exact_match_and_stays_read_only(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, "get", _fail_network, raising=True)
    monkeypatch.setattr(okx.OkxPublicSpotHistoryCandlesProvider, "fetch_klines", _fail_network, raising=True)
    monkeypatch.setattr(Path, "write_text", _fail_network, raising=True)
    monkeypatch.setattr(Path, "unlink", _fail_network, raising=True)
    monkeypatch.setattr(os, "replace", _fail_network, raising=True)

    auth = _verified_authorization()
    contract = _compatible_contract(auth)
    decision = compatibility.evaluate_offline_research_strategy_compatibility(
        auth,
        contract,
        decided_at_utc=datetime(2026, 7, 27, 16, 31, 34, tzinfo=timezone.utc),
    )

    assert decision.status == compatibility.OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_STATUS_COMPATIBLE_FOR_FUTURE_OFFLINE_RESEARCH
    assert decision.strategy_id == "synthetic_okx_compatibility"
    assert decision.strategy_version == "phase21b_compatibility_v1"
    assert decision.authorization_id == auth.authorization_id
    assert decision.authorization_hash == auth.authorization_hash
    assert decision.strategy_contract_hash == contract.compatibility_hash
    assert decision.provider_name == "OKX"
    assert decision.market_type == "spot"
    assert decision.symbol == "BTC-USDT"
    assert decision.canonical_symbol == "BTCUSDT"
    assert decision.interval == "1H"
    assert decision.expected_candle_count == 42816
    assert decision.historical_research_only is True
    assert decision.operational_evidence is False
    assert decision.paper_promotion_eligible is False
    assert decision.allowed_use_cases == ("experiment_contract_validation",)
    assert decision.prohibited_use_cases == compatibility.OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES
    assert decision.as_dict() == serialize_value(decision.canonical_payload())


def test_offline_research_strategy_compatibility_rejects_baseline_a_current_contract():
    auth = _verified_authorization()
    contract = compatibility.OfflineResearchStrategyCompatibilityContract(
        strategy_id="baseline_a",
        strategy_version=baseline_a_candidate_config().name,
        provider_name=auth.provider_name,
        market_type=auth.market_type,
        symbol=baseline_a_backtest_config().symbol,
        canonical_symbol=baseline_a_backtest_config().symbol,
        interval="1H",
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

    with pytest.raises(
        compatibility.OfflineResearchStrategyCompatibilityValidationError,
        match="symbol diverges from the authorized artifact instrument",
    ):
        compatibility.evaluate_offline_research_strategy_compatibility(auth, contract)

    assert baseline_a_candidate_config() == BASELINE_A_CANDIDATE


def test_offline_research_strategy_compatibility_rejects_kucoin_and_btcusdt():
    auth = _verified_authorization()
    kucoin_qualification = HistoricalProviderQualification.kucoin_public_spot(symbol="BTCUSDT", interval="1h")
    assert kucoin_qualification.exchange == "kucoin"
    assert kucoin_qualification.symbol == "BTCUSDT"
    assert kucoin_qualification.external_symbol == "BTC-USDT"

    contract = _compatible_contract(auth)
    _tamper_contract(contract, provider_name="KuCoin", symbol="BTCUSDT", canonical_symbol="BTCUSDT")
    with pytest.raises(
        compatibility.OfflineResearchStrategyCompatibilityValidationError,
        match="provider_name diverges from the authorized artifact",
    ):
        compatibility.evaluate_offline_research_strategy_compatibility(auth, contract)


@pytest.mark.parametrize(
    ("field_name", "value", "expected"),
    [
        ("allowed_use_cases", ("replay",), "allowed_use_cases diverge from the authorization"),
        ("allowed_use_cases", ("backtest",), "allowed_use_cases diverge from the authorization"),
        ("allowed_use_cases", ("walk_forward",), "allowed_use_cases diverge from the authorization"),
        ("allowed_use_cases", ("performance",), "allowed_use_cases diverge from the authorization"),
        ("allowed_use_cases", ("ranking",), "allowed_use_cases diverge from the authorization"),
        ("allowed_use_cases", ("paper",), "allowed_use_cases diverge from the authorization"),
        ("allowed_use_cases", ("live",), "allowed_use_cases diverge from the authorization"),
        ("allowed_use_cases", ("execution",), "allowed_use_cases diverge from the authorization"),
        ("allowed_use_cases", ("order_submission",), "allowed_use_cases diverge from the authorization"),
        ("historical_research_only", False, "historical_research_only must remain true"),
        ("operational_evidence", True, "operational_evidence must remain false"),
        ("paper_promotion_eligible", True, "paper_promotion_eligible must remain false"),
    ],
)
def test_offline_research_strategy_compatibility_rejects_operational_uses_and_flag_divergence(field_name, value, expected):
    auth = _verified_authorization()
    contract = _compatible_contract(auth)
    _tamper_contract(contract, **{field_name: value})
    with pytest.raises(compatibility.OfflineResearchStrategyCompatibilityValidationError, match=expected):
        compatibility.evaluate_offline_research_strategy_compatibility(auth, contract)


def test_offline_research_strategy_compatibility_rejects_unverified_or_incomplete_authorization():
    auth = _verified_authorization()
    tampered_auth = _tamper_contract(auth, verification_audit_status="failed")
    contract = _compatible_contract(auth)
    with pytest.raises(
        compatibility.OfflineResearchStrategyCompatibilityValidationError,
        match="authorization verification_audit_status must be passed",
    ):
        compatibility.evaluate_offline_research_strategy_compatibility(tampered_auth, contract)


def test_offline_research_strategy_compatibility_preserves_baseline_a_contract():
    assert baseline_a_candidate_config() == BASELINE_A_CANDIDATE
