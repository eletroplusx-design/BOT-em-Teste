from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from domain import Candle, DataSource

import market_data.offline_research_backtest as backtest
import market_data.offline_research_experiment_authorization as authorization
import market_data.offline_research_signal_gap_diagnostic as diagnostic
import market_data.offline_research_strategy_compatibility as compatibility
import market_data.okx_historical as okx
import market_data.research_artifact_registry as registry
import market_data.research_artifact_registry_verification as verification
from strategies.baseline_a_okx_btc_usdt_research import build_baseline_a_okx_btc_usdt_research_contract

ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)


def _verified_authorization() -> authorization.OfflineResearchExperimentAuthorization:
    registry_entry = registry.ResearchArtifactRegistryEntry(
        registered_at_utc=datetime(2026, 7, 27, 16, 31, 31, tzinfo=timezone.utc),
        external_artifact_ref="artifact://okx/phase26/research-only",
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
        external_artifact_ref="artifact://okx/phase26/research-only",
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
        strategy_version="phase26_compatibility_v1",
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


def _bundle():
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


def _short_history() -> tuple[Candle, ...]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return (
        _candle(start, base=100, close_offset=1, high_offset=2, low_offset=1),
        _candle(start + ONE_HOUR, base=101, close_offset=1, high_offset=2, low_offset=1),
    )


def _real_phase19a_artifact_paths() -> tuple[Path, Path]:
    return backtest.discover_okx_phase19a_artifact_paths()


def test_gap_real_okx_artifact_is_deterministic_and_blocks_at_trend_alignment():
    auth, compat, strategy_contract = _bundle()
    dataset_file, manifest_file = _real_phase19a_artifact_paths()
    dataset = okx.load_okx_historical_dataset(dataset_file=dataset_file, manifest_file=manifest_file)

    report = diagnostic.analyze_baseline_a_okx_btc_usdt_1h_signal_gap_research_for_okx_artifact(
        dataset=dataset,
        authorization=auth,
        compatibility_decision=compat,
        strategy_contract=strategy_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 38, tzinfo=timezone.utc),
    )
    second = diagnostic.analyze_baseline_a_okx_btc_usdt_1h_signal_gap_research_for_okx_artifact(
        dataset=dataset,
        authorization=auth,
        compatibility_decision=compat,
        strategy_contract=strategy_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 38, tzinfo=timezone.utc),
    )

    assert report.as_dict() == second.as_dict()
    assert report.report_hash == second.report_hash
    assert report.contract.historical_research_only is True
    assert report.contract.operational_evidence is False
    assert report.contract.paper_promotion_eligible is False
    assert report.contract.allowed_use_cases == ("offline_historical_research",)
    assert report.contract.prohibited_use_cases == (
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
    assert ".pytest_tmp" in report.report_notice
    assert report.setup_candles == 0
    assert report.signal_emitted_candles == 0
    assert report.not_reached == 200
    assert report.primary_rejection_reason == "trend_alignment"
    assert report.primary_rejection_reason_count == 42616
    assert "trend_alignment" in report.conclusion
    assert report.first_occurrences["first_real_failure_trend_alignment"]["open_time"] == "2021-02-20T08:00:00Z"
    assert report.signal_gap_records[0].candle_index == 200
    assert report.signal_gap_records[0].first_real_failed_gate == "trend_alignment"
    assert report.signal_gap_records[0].normalized_rejection_reason == "trend_alignment"
    assert report.signal_gap_records[0].real_gate_terminal == "trend_alignment"
    assert report.real_gate_pass_counts.get("trend_alignment", 0) == 0
    assert report.real_gate_fail_counts["trend_alignment"] == 42616
    assert report.real_gate_not_reached_counts["close_above_ema200"] == 42816
    assert report.signal_gap_records[-1].signal_emitted is False


def test_gap_bullish_fixture_emits_signal_and_is_deterministic():
    auth, compat, strategy_contract = _bundle()
    candles = _bullish_history()

    report = diagnostic.analyze_baseline_a_okx_btc_usdt_1h_signal_gap_research(
        candles,
        authorization=auth,
        compatibility_decision=compat,
        strategy_contract=strategy_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 38, tzinfo=timezone.utc),
    )
    second = diagnostic.analyze_baseline_a_okx_btc_usdt_1h_signal_gap_research(
        candles,
        authorization=auth,
        compatibility_decision=compat,
        strategy_contract=strategy_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 38, tzinfo=timezone.utc),
    )

    assert report.as_dict() == second.as_dict()
    assert report.report_hash == second.report_hash
    assert report.setup_candles == 1
    assert report.signal_emitted_candles == 1
    assert report.not_reached == 200
    assert report.first_occurrences["first_setup_detected"]["open_time"] == "2025-01-09T09:00:00Z"
    assert report.first_occurrences["first_signal_emitted"]["open_time"] == "2025-01-09T09:00:00Z"
    assert report.signal_gap_records[-1].signal_emitted is True
    assert report.signal_gap_records[-1].signal_side == "LONG"
    assert report.signal_gap_records[-1].signal_reason == "long_setup_detected"
    assert report.real_gate_pass_counts.get("trend_alignment", 0) == 2
    assert report.real_gate_not_reached_counts["close_above_ema200"] == 200
    assert report.contract.allowed_use_cases == ("offline_historical_research",)


def test_gap_bearish_fixture_reaches_warmup_then_blocks_at_trend_alignment():
    auth, compat, strategy_contract = _bundle()
    candles = _bearish_history()

    report = diagnostic.analyze_baseline_a_okx_btc_usdt_1h_signal_gap_research(
        candles,
        authorization=auth,
        compatibility_decision=compat,
        strategy_contract=strategy_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 38, tzinfo=timezone.utc),
    )

    assert report.setup_candles == 0
    assert report.signal_emitted_candles == 0
    assert report.not_reached == 200
    assert report.primary_rejection_reason == "trend_alignment"
    assert report.first_occurrences["first_real_failure_trend_alignment"]["open_time"] == "2025-01-09T08:00:00Z"
    assert report.signal_gap_records[0].first_real_failed_gate == "trend_alignment"
    assert report.signal_gap_records[0].normalized_rejection_reason == "trend_alignment"
    assert report.real_gate_pass_counts.get("trend_alignment", 0) == 0
    assert report.real_gate_not_reached_counts["close_above_ema200"] == 202


def test_gap_short_fixture_stays_in_warmup_and_emits_no_records():
    auth, compat, strategy_contract = _bundle()
    candles = _short_history()

    report = diagnostic.analyze_baseline_a_okx_btc_usdt_1h_signal_gap_research(
        candles,
        authorization=auth,
        compatibility_decision=compat,
        strategy_contract=strategy_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 38, tzinfo=timezone.utc),
    )

    assert report.setup_candles == 0
    assert report.signal_emitted_candles == 0
    assert report.not_reached == 2
    assert report.signal_gap_records == ()
    assert report.first_occurrences["first_not_reached"]["reason"] == "signal_not_emitted"


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda auth, compat, contract, candles: object.__setattr__(auth, "provider_name", "KuCoin"), "authorization provider_name must be OKX."),
        (lambda auth, compat, contract, candles: object.__setattr__(compat, "symbol", "BTCUSDT"), "compatibility symbol must be BTC-USDT."),
        (lambda auth, compat, contract, candles: object.__setattr__(auth, "paper_promotion_eligible", True), "paper_promotion_eligible must be false."),
        (lambda auth, compat, contract, candles: object.__setattr__(contract, "symbol", "BTCUSDT"), "strategy symbol must be BTC-USDT."),
        (lambda auth, compat, contract, candles: None, "candles must not be empty."),
    ],
)
def test_gap_rejects_invalid_authorization_compatibility_and_dataset(mutator, expected):
    auth, compat, strategy_contract = _bundle()
    candles = list(_bullish_history())
    if expected == "candles must not be empty.":
        candles = []
    else:
        mutator(auth, compat, strategy_contract, candles)

    with pytest.raises(diagnostic.OfflineResearchSignalGapDiagnosticValidationError, match=expected):
        diagnostic.analyze_baseline_a_okx_btc_usdt_1h_signal_gap_research(
            tuple(candles),
            authorization=auth,
            compatibility_decision=compat,
            strategy_contract=strategy_contract,
            analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 38, tzinfo=timezone.utc),
        )


def test_gap_module_is_pure_and_does_not_import_execution_or_network():
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
