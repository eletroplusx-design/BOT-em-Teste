from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import os

import pytest
import requests

from domain import Candle, DataSource, MarketSnapshot
from domain.serialization import serialize_value
from market_data import HistoricalProviderQualification
import market_data.offline_research_experiment_authorization as authorization
import market_data.offline_research_strategy_compatibility as compatibility
import market_data.research_artifact_registry as registry
import market_data.research_artifact_registry_verification as verification
from strategies.baseline_a import BASELINE_A_CANDIDATE, baseline_a_candidate_config, baseline_a_strategy
import strategies.baseline_a_okx_btc_usdt_research as research

ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)


def _fail_network(*args, **kwargs):
    raise AssertionError("network must not be reached")


def _verified_authorization() -> authorization.OfflineResearchExperimentAuthorization:
    registry_entry = registry.ResearchArtifactRegistryEntry(
        registered_at_utc=datetime(2026, 7, 27, 16, 31, 31, tzinfo=timezone.utc),
        external_artifact_ref="artifact://okx/phase22a/research-only",
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
        external_artifact_ref="artifact://okx/phase22a/research-only",
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


def _compatible_contract(
    auth: authorization.OfflineResearchExperimentAuthorization,
) -> compatibility.OfflineResearchStrategyCompatibilityContract:
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


def _verified_bundle():
    auth = _verified_authorization()
    contract = _compatible_contract(auth)
    compatibility_decision = compatibility.evaluate_offline_research_strategy_compatibility(
        auth,
        contract,
        decided_at_utc=datetime(2026, 7, 27, 16, 31, 34, tzinfo=timezone.utc),
    )
    strategy_contract = research.build_baseline_a_okx_btc_usdt_research_contract(auth, compatibility_decision)
    return auth, compatibility_decision, strategy_contract


def _candle(
    open_time: datetime,
    *,
    base: int,
    symbol: str = registry.OKX_RESEARCH_ARTIFACT_INSTRUMENT,
    interval: str = registry.OKX_RESEARCH_ARTIFACT_INTERVAL,
) -> Candle:
    return Candle.from_dict(
        {
            "open_time": open_time,
            "close_time": open_time + ONE_HOUR - ONE_MS,
            "open": str(base),
            "high": str(base + 6),
            "low": str(base - 6),
            "close": str(base + 2),
            "volume": str(1000 + base),
            "symbol": symbol,
            "interval": interval,
            "source": DataSource.PAPER,
        }
    )


def _flat_history(*, count: int = 202, symbol: str = registry.OKX_RESEARCH_ARTIFACT_INSTRUMENT, interval: str = registry.OKX_RESEARCH_ARTIFACT_INTERVAL) -> tuple[Candle, ...]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = [_candle(start + idx * ONE_HOUR, base=100 + idx, symbol=symbol, interval=interval) for idx in range(count)]
    for idx in range(20, count):
        candle = candles[idx]
        base = 100 + idx * 2
        candles[idx] = Candle.from_dict(
            {
                "open_time": candle.open_time,
                "close_time": candle.close_time,
                "open": str(base - 2),
                "high": str(base + 6),
                "low": str(base - 7),
                "close": str(base + 2),
                "volume": str(2000 + idx),
                "symbol": candle.symbol,
                "interval": candle.interval,
                "source": candle.source,
            }
        )

    candles[-4] = Candle.from_dict(
        {
            "open_time": candles[-4].open_time,
            "close_time": candles[-4].close_time,
            "open": "500",
            "high": "512",
            "low": "494",
            "close": "508",
            "volume": "3000",
            "symbol": candles[-4].symbol,
            "interval": candles[-4].interval,
            "source": DataSource.PAPER,
        }
    )
    candles[-3] = Candle.from_dict(
        {
            "open_time": candles[-3].open_time,
            "close_time": candles[-3].close_time,
            "open": "508",
            "high": "516",
            "low": "450",
            "close": "514",
            "volume": "3100",
            "symbol": candles[-3].symbol,
            "interval": candles[-3].interval,
            "source": DataSource.PAPER,
        }
    )
    candles[-2] = Candle.from_dict(
        {
            "open_time": candles[-2].open_time,
            "close_time": candles[-2].close_time,
            "open": "514",
            "high": "526",
            "low": "499",
            "close": "522",
            "volume": "3200",
            "symbol": candles[-2].symbol,
            "interval": candles[-2].interval,
            "source": DataSource.PAPER,
        }
    )
    candles[-1] = Candle.from_dict(
        {
            "open_time": candles[-1].open_time,
            "close_time": candles[-1].close_time,
            "open": "530",
            "high": "540",
            "low": "528",
            "close": "538",
            "volume": "3300",
            "symbol": candles[-1].symbol,
            "interval": candles[-1].interval,
            "source": DataSource.PAPER,
        }
    )
    return tuple(candles)


def _snapshot(candles: tuple[Candle, ...], *, regime: str | None = None) -> MarketSnapshot:
    last = candles[-1]
    return MarketSnapshot(
        symbol=last.symbol,
        timestamp=last.close_time,
        current_price=last.close,
        source=DataSource.PAPER,
        regime=regime,
    )


def _history_with_symbol(candles: tuple[Candle, ...], *, symbol: str, interval: str) -> tuple[Candle, ...]:
    return tuple(
        Candle.from_dict(
            {
                "open_time": candle.open_time,
                "close_time": candle.close_time,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "symbol": symbol,
                "interval": interval,
                "source": candle.source,
            }
        )
        for candle in candles
    )


def test_strategy_identity_and_fingerprint_are_deterministic(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, "get", _fail_network, raising=True)
    monkeypatch.setattr(Path, "write_text", _fail_network, raising=True)
    monkeypatch.setattr(Path, "unlink", _fail_network, raising=True)
    monkeypatch.setattr(os, "replace", _fail_network, raising=True)

    auth, compatibility_decision, contract = _verified_bundle()
    contract_again = research.build_baseline_a_okx_btc_usdt_research_contract(auth, compatibility_decision)

    assert contract.strategy_id == "baseline_a_okx_btc_usdt_1h_research"
    assert contract.strategy_version == "baseline_a_okx_btc_usdt_1h_research_v1"
    assert contract.provider_name == "OKX"
    assert contract.market_type == "spot"
    assert contract.symbol == "BTC-USDT"
    assert contract.canonical_symbol == "BTCUSDT"
    assert contract.interval == "1H"
    assert contract.purpose == "offline_historical_research"
    assert contract.historical_research_only is True
    assert contract.operational_evidence is False
    assert contract.paper_promotion_eligible is False
    assert contract.contract_hash == contract_again.contract_hash
    assert contract.as_dict() == serialize_value(contract.canonical_payload())


def test_strategy_accepts_exact_okx_contract_and_emits_long_setup(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, "get", _fail_network, raising=True)
    monkeypatch.setattr(Path, "write_text", _fail_network, raising=True)
    monkeypatch.setattr(Path, "unlink", _fail_network, raising=True)
    monkeypatch.setattr(os, "replace", _fail_network, raising=True)

    auth, compatibility_decision, contract = _verified_bundle()
    candles = _flat_history()
    decision = research.evaluate_baseline_a_okx_btc_usdt_research(
        candles,
        authorization=auth,
        compatibility_decision=compatibility_decision,
        contract=contract,
        snapshot=_snapshot(candles, regime="bull"),
        decided_at_utc=datetime(2026, 7, 27, 16, 31, 35, tzinfo=timezone.utc),
    )

    assert decision.decision == research.BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_LONG_SETUP_DETECTED
    assert decision.strategy_id == contract.strategy_id
    assert decision.strategy_version == contract.strategy_version
    assert decision.signal_side == "LONG"
    assert decision.trend_state == "BULLISH"
    assert decision.pullback_state == "TOUCHED_EMA20"
    assert decision.confirmation_state == "BREAKOUT_CONFIRMED"
    assert decision.historical_research_only is True
    assert decision.operational_evidence is False
    assert decision.paper_promotion_eligible is False
    assert decision.theoretical_rr == Decimal("2")
    assert decision.rejection_reason is None
    assert decision.as_dict() == serialize_value(decision.canonical_payload())


def test_strategy_rejects_baseline_a_and_btcusdt_divergence():
    auth, compatibility_decision, contract = _verified_bundle()
    okx_candles = _flat_history()
    btcusdt_candles = _history_with_symbol(okx_candles, symbol="BTCUSDT", interval="1H")

    assert baseline_a_candidate_config() == BASELINE_A_CANDIDATE
    assert baseline_a_strategy(okx_candles, _snapshot(okx_candles)) is None

    with pytest.raises(research.BaselineAOkxBtcUsdtResearchValidationError, match="candles must use BTC-USDT"):
        research.evaluate_baseline_a_okx_btc_usdt_research(
            btcusdt_candles,
            authorization=auth,
            compatibility_decision=compatibility_decision,
            contract=contract,
            snapshot=_snapshot(btcusdt_candles),
        )


def test_strategy_rejects_kucoin_and_operational_uses():
    auth = _verified_authorization()
    kucoin_qualification = HistoricalProviderQualification.kucoin_public_spot(symbol="BTCUSDT", interval="1h")
    assert kucoin_qualification.exchange == "kucoin"
    assert kucoin_qualification.symbol == "BTCUSDT"
    assert kucoin_qualification.external_symbol == "BTC-USDT"

    contract = _compatible_contract(auth)
    compatibility_decision = compatibility.evaluate_offline_research_strategy_compatibility(
        auth,
        contract,
        decided_at_utc=datetime(2026, 7, 27, 16, 31, 34, tzinfo=timezone.utc),
    )
    tampered_decision = compatibility_decision
    object.__setattr__(tampered_decision, "provider_name", "KuCoin")
    object.__setattr__(tampered_decision, "symbol", "BTCUSDT")
    object.__setattr__(tampered_decision, "canonical_symbol", "BTCUSDT")

    with pytest.raises(research.BaselineAOkxBtcUsdtResearchValidationError, match="provider_name must be OKX"):
        research.evaluate_baseline_a_okx_btc_usdt_research(
            _flat_history(),
            authorization=auth,
            compatibility_decision=tampered_decision,
        )

    assert research.BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_ALLOWED_USE_CASES == ("offline_historical_research",)
    assert research.BASELINE_A_OKX_BTC_USDT_RESEARCH_PROHIBITED_USE_CASES == (
        "replay",
        "backtest",
        "walk_forward",
        "performance",
        "ranking",
        "paper",
        "live",
        "execution",
        "order_submission",
    )


def test_strategy_rejects_missing_or_invalid_data_and_preserves_flags():
    auth, compatibility_decision, contract = _verified_bundle()
    candles = list(_flat_history())
    candles[-1] = Candle.from_dict(
        {
            "open_time": candles[-1].open_time,
            "close_time": candles[-1].close_time,
            "open": "530",
            "high": "530",
            "low": "520",
            "close": "525",
            "volume": candles[-1].volume,
            "symbol": candles[-1].symbol,
            "interval": candles[-1].interval,
            "source": candles[-1].source,
        }
    )

    assert (
        research.evaluate_baseline_a_okx_btc_usdt_research(
            tuple(candles),
            authorization=auth,
            compatibility_decision=compatibility_decision,
            contract=contract,
            snapshot=_snapshot(tuple(candles)),
        ).decision
        == research.BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_NO_SETUP
    )

    short_history = _flat_history(count=200)
    with pytest.raises(research.BaselineAOkxBtcUsdtResearchValidationError, match="candles are insufficient"):
        research.evaluate_baseline_a_okx_btc_usdt_research(
            short_history,
            authorization=auth,
            compatibility_decision=compatibility_decision,
            contract=contract,
            snapshot=_snapshot(short_history),
        )

    assert contract.historical_research_only is True
    assert contract.operational_evidence is False
    assert contract.paper_promotion_eligible is False
    assert auth.historical_research_only is True
    assert auth.operational_evidence is False
    assert auth.paper_promotion_eligible is False
