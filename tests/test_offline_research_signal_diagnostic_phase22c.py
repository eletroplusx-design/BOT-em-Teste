from __future__ import annotations

import copy
import inspect
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from domain import Candle, DataSource
import market_data.offline_research_backtest as backtest
import market_data.okx_historical as okx

import market_data.offline_research_experiment_authorization as authorization
import market_data.offline_research_signal_diagnostic as diagnostic
import market_data.offline_research_strategy_compatibility as compatibility
import market_data.research_artifact_registry as registry
import market_data.research_artifact_registry_verification as verification
from strategies.baseline_a_okx_btc_usdt_research import build_baseline_a_okx_btc_usdt_research_contract

ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)


def _verified_authorization() -> authorization.OfflineResearchExperimentAuthorization:
    registry_entry = registry.ResearchArtifactRegistryEntry(
        registered_at_utc=datetime(2026, 7, 27, 16, 31, 31, tzinfo=timezone.utc),
        external_artifact_ref="artifact://okx/phase22c/research-only",
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
        external_artifact_ref="artifact://okx/phase22c/research-only",
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
    compat = _compatible_contract(auth)
    compatibility_decision = compatibility.evaluate_offline_research_strategy_compatibility(
        auth,
        compat,
        decided_at_utc=datetime(2026, 7, 27, 16, 31, 34, tzinfo=timezone.utc),
    )
    strategy_contract = build_baseline_a_okx_btc_usdt_research_contract(auth, compatibility_decision)
    return auth, compatibility_decision, strategy_contract


def _candle(
    open_time: datetime,
    *,
    base: int,
    close_offset: int = 1,
    high_offset: int = 2,
    low_offset: int = 1,
    symbol: str = registry.OKX_RESEARCH_ARTIFACT_INSTRUMENT,
    interval: str = registry.OKX_RESEARCH_ARTIFACT_INTERVAL,
) -> Candle:
    return Candle.from_dict(
        {
            "open_time": open_time,
            "close_time": open_time + ONE_HOUR - ONE_MS,
            "open": str(base),
            "high": str(base + high_offset),
            "low": str(base - low_offset),
            "close": str(base + close_offset),
            "volume": str(1000 + base),
            "symbol": symbol,
            "interval": interval,
            "source": DataSource.PAPER,
        }
    )


def _bullish_history() -> tuple[Candle, ...]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = [
        _candle(start + idx * ONE_HOUR, base=100 + idx, close_offset=1, high_offset=2, low_offset=1)
        for idx in range(200)
    ]
    candles.append(
        Candle.from_dict(
            {
                "open_time": start + 200 * ONE_HOUR,
                "close_time": start + 201 * ONE_HOUR - ONE_MS,
                "open": "300",
                "high": "301",
                "low": "280",
                "close": "285",
                "volume": "5000",
                "symbol": registry.OKX_RESEARCH_ARTIFACT_INSTRUMENT,
                "interval": registry.OKX_RESEARCH_ARTIFACT_INTERVAL,
                "source": DataSource.PAPER,
            }
        )
    )
    candles.append(
        Candle.from_dict(
            {
                "open_time": start + 201 * ONE_HOUR,
                "close_time": start + 202 * ONE_HOUR - ONE_MS,
                "open": "286",
                "high": "320",
                "low": "284",
                "close": "319",
                "volume": "6000",
                "symbol": registry.OKX_RESEARCH_ARTIFACT_INSTRUMENT,
                "interval": registry.OKX_RESEARCH_ARTIFACT_INTERVAL,
                "source": DataSource.PAPER,
            }
        )
    )
    return tuple(candles)


def _bearish_history() -> tuple[Candle, ...]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = [
        _candle(start + idx * ONE_HOUR, base=400 - idx, close_offset=-1, high_offset=1, low_offset=2)
        for idx in range(200)
    ]
    candles.append(
        Candle.from_dict(
            {
                "open_time": start + 200 * ONE_HOUR,
                "close_time": start + 201 * ONE_HOUR - ONE_MS,
                "open": "200",
                "high": "240",
                "low": "195",
                "close": "210",
                "volume": "5000",
                "symbol": registry.OKX_RESEARCH_ARTIFACT_INSTRUMENT,
                "interval": registry.OKX_RESEARCH_ARTIFACT_INTERVAL,
                "source": DataSource.PAPER,
            }
        )
    )
    candles.append(
        Candle.from_dict(
            {
                "open_time": start + 201 * ONE_HOUR,
                "close_time": start + 202 * ONE_HOUR - ONE_MS,
                "open": "209",
                "high": "211",
                "low": "150",
                "close": "151",
                "volume": "6000",
                "symbol": registry.OKX_RESEARCH_ARTIFACT_INSTRUMENT,
                "interval": registry.OKX_RESEARCH_ARTIFACT_INTERVAL,
                "source": DataSource.PAPER,
            }
        )
    )
    return tuple(candles)

def _real_phase19a_artifact_paths() -> tuple[Path, Path]:
    return backtest.discover_okx_phase19a_artifact_paths()


def test_diagnostic_counts_bullish_funnel_and_is_deterministic():
    auth, compat, strategy_contract = _verified_bundle()
    before = strategy_contract.as_dict()
    report = diagnostic.analyze_zero_trade_signal_funnel(
        _bullish_history(),
        authorization=auth,
        compatibility_decision=compat,
        strategy_contract=strategy_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 35, tzinfo=timezone.utc),
    )
    second = diagnostic.analyze_zero_trade_signal_funnel(
        _bullish_history(),
        authorization=auth,
        compatibility_decision=compat,
        strategy_contract=strategy_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 35, tzinfo=timezone.utc),
    )

    assert strategy_contract.as_dict() == before
    assert report.as_dict() == second.as_dict()
    assert report.candles_total == 202
    assert report.candles_insufficient == 200
    assert report.candles_structurally_invalid == 0
    assert report.bullish_trend_candles > 0
    assert report.bullish_pullback_candles > 0
    assert report.bullish_confirmation_candles > 0
    assert report.long_setups == 1
    assert report.short_setups == 0
    assert report.first_occurrences["first_long_setup"]["open_time"] == "2025-01-09T09:00:00Z"
    assert report.conclusion == "at least one long setup is present."

    output_file = _workspace_tmp_dir("phase22c-diagnostic") / "diagnostic.json"
    written = diagnostic.run_zero_trade_signal_diagnostic(
        _bullish_history(),
        authorization=auth,
        compatibility_decision=compat,
        strategy_contract=strategy_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 35, tzinfo=timezone.utc),
        output_file=output_file,
    )
    assert output_file.exists()
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["diagnostic_hash"] == written.diagnostic_hash
    assert payload["report_notice"] == diagnostic.OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_NON_OPERATIONAL_DECLARATION


def test_diagnostic_counts_bearish_funnel_and_no_lookahead():
    auth, compat, strategy_contract = _verified_bundle()
    report = diagnostic.analyze_zero_trade_signal_funnel(
        _bearish_history(),
        authorization=auth,
        compatibility_decision=compat,
        strategy_contract=strategy_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 36, tzinfo=timezone.utc),
    )

    assert report.candles_total == 202
    assert report.candles_insufficient == 200
    assert report.bullish_trend_candles == 0
    assert report.long_setups == 0
    assert report.bearish_trend_candles > 0
    assert report.bearish_pullback_candles > 0
    assert report.bearish_confirmation_candles > 0
    assert report.short_setups == 1
    assert report.first_occurrences["first_short_setup"]["open_time"] == "2025-01-09T09:00:00Z"
    assert report.first_occurrences["first_bearish_trend"]["open_time"] <= report.first_occurrences["first_short_setup"]["open_time"]
    assert report.conclusion == (
        "candles are accepted, but every eligible candle is rejected at the bullish trend gate "
        "(ema50 must be above ema200)."
    )

def test_diagnostic_projects_real_okx_artifact_to_research_surface_and_keeps_zero_trade_result():
    auth, decision, strategy_contract = _verified_bundle()
    dataset_file, manifest_file = _real_phase19a_artifact_paths()
    dataset = okx.load_okx_historical_dataset(dataset_file=dataset_file, manifest_file=manifest_file)
    projected = diagnostic.project_okx_research_candles(
        dataset,
        symbol=strategy_contract.symbol,
    )
    report = diagnostic.run_zero_trade_signal_diagnostic_for_okx_artifact(
        dataset=dataset,
        authorization=auth,
        compatibility_decision=decision,
        strategy_contract=strategy_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 38, tzinfo=timezone.utc),
    )
    second = diagnostic.run_zero_trade_signal_diagnostic_for_okx_artifact(
        dataset=dataset,
        authorization=auth,
        compatibility_decision=decision,
        strategy_contract=strategy_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 38, tzinfo=timezone.utc),
    )

    assert len(projected) == registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT
    assert projected[0].symbol == "BTC-USDT"
    assert projected[0].source == DataSource.PAPER
    assert projected[-1].symbol == "BTC-USDT"
    assert report.as_dict() == second.as_dict()
    assert report.candles_total == registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT
    assert report.candles_insufficient == 200
    assert report.candles_structurally_invalid == 0
    assert report.primary_rejection_reason == diagnostic.OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_BULLISH_TREND_REJECTION


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda auth, compat, contract, candles: object.__setattr__(auth, "provider_name", "KuCoin"), "authorization provider_name must be OKX."),
        (lambda auth, compat, contract, candles: object.__setattr__(compat, "symbol", "BTCUSDT"), "compatibility symbol must be BTC-USDT."),
        (lambda auth, compat, contract, candles: object.__setattr__(contract, "symbol", "BTCUSDT"), "strategy symbol must be BTC-USDT."),
        (lambda auth, compat, contract, candles: object.__setattr__(auth, "paper_promotion_eligible", True), "paper_promotion_eligible must be false."),
        (lambda auth, compat, contract, candles: tuple(candles).__setitem__ if False else None, "candles must use BTC-USDT."),
    ],
)
def test_diagnostic_rejects_invalid_authorization_compatibility_and_dataset(mutator, expected):
    auth, compat, strategy_contract = _verified_bundle()
    candles = list(_bullish_history())
    if expected == "candles must use BTC-USDT.":
        candles[0] = Candle.from_dict(
            {
                "open_time": candles[0].open_time,
                "close_time": candles[0].close_time,
                "open": str(candles[0].open),
                "high": str(candles[0].high),
                "low": str(candles[0].low),
                "close": str(candles[0].close),
                "volume": str(candles[0].volume),
                "symbol": "BTCUSDT",
                "interval": candles[0].interval,
                "source": DataSource.PAPER,
            }
        )
    else:
        mutator(auth, compat, strategy_contract, candles)

    with pytest.raises(diagnostic.OfflineResearchSignalDiagnosticValidationError, match=expected):
        diagnostic.analyze_zero_trade_signal_funnel(
            tuple(candles),
            authorization=auth,
            compatibility_decision=compat,
            strategy_contract=strategy_contract,
            analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 37, tzinfo=timezone.utc),
        )


def test_diagnostic_module_is_pure_and_does_not_import_execution_or_network():
    assert not hasattr(diagnostic, "requests")
    assert not hasattr(diagnostic, "BacktestConfig")
    assert not hasattr(diagnostic, "LeakFreeBacktestEngine")
    assert not hasattr(diagnostic, "OkxPublicSpotHistoryCandlesProvider")
    assert not hasattr(diagnostic, "KuCoinPublicSpotKlinesProvider")
    source = inspect.getsource(diagnostic)
    assert "import requests" not in source
    assert "BacktestConfig" not in source
    assert "LeakFreeBacktestEngine" not in source
    assert "OkxPublicSpotHistoryCandlesProvider" not in source


def _workspace_tmp_dir(name: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp" / name
    root.mkdir(parents=True, exist_ok=True)
    return root
