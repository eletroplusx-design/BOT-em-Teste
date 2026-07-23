from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from domain import Candle, DataSource
from market_data.historical_alignment import build_historical_multitimeframe_bundle
from historical_multitimeframe_analysis import (
    HistoricalMultiTimeframeStrategyAnalysisConflictError,
    HistoricalMultiTimeframeStrategyAnalysisPromotionError,
    HistoricalMultiTimeframeStrategyAnalysisReport,
    HistoricalMultiTimeframeStrategyAnalysisValidationError,
    build_historical_multitimeframe_strategy_analysis_protocol,
    load_historical_multitimeframe_strategy_analysis_report,
    reject_historical_multitimeframe_strategy_analysis_promotion,
    run_historical_multitimeframe_strategy_analysis,
    save_historical_multitimeframe_strategy_analysis_report,
    status_historical_multitimeframe_strategy_analysis_report,
    verify_historical_multitimeframe_strategy_analysis_report,
)
from historical_multitimeframe_evaluation import run_historical_multitimeframe_first_strategy_evaluation
from historical_multitimeframe_experiments import build_historical_multitimeframe_replay
from historical_multitimeframe_strategy import (
    build_historical_multitimeframe_first_strategy_factory,
    build_historical_multitimeframe_first_strategy_config,
    run_historical_multitimeframe_first_strategy,
)
from market_data import (
    HistoricalDataset,
    HistoricalDatasetManifest,
    HistoricalProviderQualification,
)
from market_data.errors import HistoricalDataIntegrityError
from market_data.historical_models import candles_content_hash


START = datetime(2024, 1, 1, tzinfo=timezone.utc)
SYMBOL = "BTCUSDT"
ENDPOINT = "https://api.kucoin.com/api/v1/market/candles"


def _minute_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _make_series(*, future_variant: bool = False) -> tuple[list[Candle], list[Candle], list[Candle]]:
    base_candles: list[Candle] = []
    price = Decimal("100")
    open_time = START
    for index in range(400):
        if index < 320:
            delta = Decimal("0.05")
            spread = Decimal("0.80")
        elif index < 360:
            delta = Decimal("0.20")
            spread = Decimal("1.50")
        else:
            delta = Decimal("-0.18") if not future_variant else Decimal("0.27")
            spread = Decimal("3.00") if not future_variant else Decimal("4.00")
        candle_open = price
        candle_close = price + delta
        high = max(candle_open, candle_close) + spread
        low = min(candle_open, candle_close) - spread
        base_candles.append(
            Candle(
                open_time=open_time,
                close_time=open_time + timedelta(minutes=15) - timedelta(milliseconds=1),
                open=candle_open,
                high=high,
                low=low,
                close=candle_close,
                volume=Decimal("100") + Decimal(index % 11),
                symbol=SYMBOL,
                interval="15m",
                source=DataSource.KUCOIN,
            )
        )
        price = candle_close
        open_time += timedelta(minutes=15)

    def aggregate(interval: str, chunk_size: int, candles: list[Candle]) -> list[Candle]:
        series: list[Candle] = []
        for start in range(0, len(candles), chunk_size):
            chunk = candles[start : start + chunk_size]
            if len(chunk) != chunk_size:
                break
            series.append(
                Candle(
                    open_time=chunk[0].open_time,
                    close_time=chunk[-1].close_time,
                    open=chunk[0].open,
                    high=max(c.high for c in chunk),
                    low=min(c.low for c in chunk),
                    close=chunk[-1].close,
                    volume=sum((c.volume for c in chunk), Decimal("0")),
                    symbol=SYMBOL,
                    interval=interval,
                    source=DataSource.KUCOIN,
                )
            )
        return series

    one_hour_candles = aggregate("1h", 4, base_candles)
    four_hour_candles = aggregate("4h", 16, base_candles)
    return base_candles, one_hour_candles, four_hour_candles


def _build_dataset(candles: list[Candle], interval: str) -> HistoricalDataset:
    qualification = HistoricalProviderQualification.kucoin_public_spot(symbol=SYMBOL, interval=interval)
    content_hash = candles_content_hash(candles)
    manifest = HistoricalDatasetManifest(
        schema_version=2,
        dataset_id=content_hash,
        provider=qualification.provider_id,
        provider_qualification=qualification,
        endpoint=ENDPOINT,
        symbol=SYMBOL,
        interval=interval,
        requested_start_utc=candles[0].open_time,
        requested_end_utc=candles[-1].close_time,
        effective_start_utc=candles[0].open_time,
        effective_end_utc=candles[-1].close_time,
        created_at_utc=candles[-1].close_time + timedelta(days=1),
        candle_count=len(candles),
        page_count=1,
        page_size=1500,
        closed_candles_only=True,
        gap_count=0,
        duplicate_count=0,
        content_hash=content_hash,
    )
    manifest = HistoricalDatasetManifest.from_dict(manifest.as_dict())
    return HistoricalDataset(manifest=manifest, candles=tuple(candles))


def _build_analysis_report(*, future_variant: bool = False, period_windows=None):
    full_base_candles, one_hour_candles, four_hour_candles = _make_series(future_variant=future_variant)
    base_candles = full_base_candles[320:]
    base_dataset = _build_dataset(base_candles, "15m")
    one_hour_dataset = _build_dataset(one_hour_candles, "1h")
    four_hour_dataset = _build_dataset(four_hour_candles, "4h")
    bundle = build_historical_multitimeframe_bundle(base_dataset, one_hour_dataset, four_hour_dataset)
    replay = build_historical_multitimeframe_replay(bundle)
    factory = build_historical_multitimeframe_first_strategy_factory(build_historical_multitimeframe_first_strategy_config())
    strategy_report = run_historical_multitimeframe_first_strategy(replay, factory=factory)
    evaluation_report = run_historical_multitimeframe_first_strategy_evaluation(strategy_report, exit_horizon_15m_candles=4)
    protocol = build_historical_multitimeframe_strategy_analysis_protocol(evaluation_report, period_windows=period_windows)
    analysis_report = run_historical_multitimeframe_strategy_analysis(evaluation_report, protocol=protocol)
    return analysis_report, evaluation_report, strategy_report, bundle, protocol


@pytest.fixture(scope="module")
def analysis_artifacts():
    return _build_analysis_report()


@pytest.fixture(scope="module")
def future_analysis_artifacts(analysis_artifacts):
    _, _, _, _, original_protocol = analysis_artifacts
    return _build_analysis_report(future_variant=True, period_windows=original_protocol.period_windows)


def _manual_group_metrics(observations):
    returns = [item.gross_return_percent_without_costs for item in observations if item.status == "evaluated" and item.gross_return_percent_without_costs is not None]
    evaluated = len(returns)
    if evaluated:
        wins = sum(1 for value in returns if value > 0)
        win_rate = (Decimal(wins) / Decimal(evaluated)) * Decimal("100")
        mean_return = sum(returns, Decimal("0")) / Decimal(evaluated)
        median_return = sorted(returns)[evaluated // 2] if evaluated % 2 == 1 else (sorted(returns)[evaluated // 2 - 1] + sorted(returns)[evaluated // 2]) / Decimal("2")
        cumulative = sum(returns, Decimal("0"))
    else:
        win_rate = Decimal("0")
        mean_return = Decimal("0")
        median_return = Decimal("0")
        cumulative = Decimal("0")
    return evaluated, win_rate, mean_return, median_return, cumulative


def test_analysis_round_trip_and_hash_stability(analysis_artifacts):
    report, evaluation_report, *_ = analysis_artifacts
    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.protocol.source.evaluation_hash == evaluation_report.evaluation_hash

    with TemporaryDirectory(dir=Path.cwd()) as temp_dir:
        output_path = Path(temp_dir) / "analysis.json"
        saved = save_historical_multitimeframe_strategy_analysis_report(output_path, report)
        assert saved.report_hash == report.report_hash

        loaded = load_historical_multitimeframe_strategy_analysis_report(output_path)
        assert loaded == report
        assert loaded.report_hash == report.report_hash
        verify_historical_multitimeframe_strategy_analysis_report(output_path)
        status = status_historical_multitimeframe_strategy_analysis_report(output_path)
        assert status["classification"] == "historical_research_only"
        assert status["report_hash"] == report.report_hash

    rebuilt = HistoricalMultiTimeframeStrategyAnalysisReport.from_dict(report.as_dict())
    assert rebuilt.report_hash == report.report_hash
    assert rebuilt.as_dict() == report.as_dict()
    assert saved.report_hash == report.report_hash



def test_analysis_summary_matches_observations(analysis_artifacts):
    report, *_ = analysis_artifacts
    observations = report.observations
    summary = report.summary

    assert summary.decision_count == len(observations)
    assert summary.signal_count == sum(1 for item in observations if item.signal_generated)
    assert summary.evaluated_operations == sum(1 for item in observations if item.status == "evaluated")
    assert summary.no_signal_decisions == sum(1 for item in observations if item.status == "no_signal")
    assert summary.not_evaluable_entries == sum(1 for item in observations if item.status == "not_evaluable")

    evaluated_returns = [item.gross_return_percent_without_costs for item in observations if item.status == "evaluated" and item.gross_return_percent_without_costs is not None]
    if evaluated_returns:
        sorted_returns = sorted(evaluated_returns)
        median_return = sorted_returns[len(sorted_returns) // 2] if len(sorted_returns) % 2 == 1 else (sorted_returns[len(sorted_returns) // 2 - 1] + sorted_returns[len(sorted_returns) // 2]) / Decimal("2")
        assert summary.win_rate_percent == (Decimal(sum(1 for value in evaluated_returns if value > 0)) / Decimal(len(evaluated_returns))) * Decimal("100")
        assert summary.mean_gross_return_percent_without_costs == sum(evaluated_returns, Decimal("0")) / Decimal(len(evaluated_returns))
        assert summary.median_gross_return_percent_without_costs == median_return
        assert summary.cumulative_simple_return_percent_without_costs == sum(evaluated_returns, Decimal("0"))
        assert summary.max_loss_streak >= 0
        assert summary.max_win_streak >= 0
    else:
        assert summary.win_rate_percent == Decimal("0")

    assert summary.excluded_reason_counts
    assert summary.warning_group_count >= 0
    assert summary.empty_group_count > 0


def test_group_metrics_are_deterministic_and_auditable(analysis_artifacts):
    report, *_ = analysis_artifacts
    target_group = next(group for group in report.groups if group.decision_count > 0)
    selected = [
        item for item in report.observations
        if (
            item.period_label,
            item.trend_4h_label,
            item.price_1h_label,
            item.volatility_label,
        ) == (
            target_group.period_label,
            target_group.trend_4h_label,
            target_group.price_1h_label,
            target_group.volatility_label,
        )
    ]
    assert target_group.decision_count == len(selected)
    assert target_group.signal_count == sum(1 for item in selected if item.signal_generated)
    assert target_group.no_signal_decisions == sum(1 for item in selected if item.status == "no_signal")
    assert target_group.not_evaluable_entries == sum(1 for item in selected if item.status == "not_evaluable")

    evaluated_returns = [item.gross_return_percent_without_costs for item in selected if item.status == "evaluated" and item.gross_return_percent_without_costs is not None]
    if evaluated_returns:
        sorted_returns = sorted(evaluated_returns)
        median_return = sorted_returns[len(sorted_returns) // 2] if len(sorted_returns) % 2 == 1 else (sorted_returns[len(sorted_returns) // 2 - 1] + sorted_returns[len(sorted_returns) // 2]) / Decimal("2")
        assert target_group.evaluated_operations == len(evaluated_returns)
        assert target_group.win_rate_percent == (Decimal(sum(1 for value in evaluated_returns if value > 0)) / Decimal(len(evaluated_returns))) * Decimal("100")
        assert target_group.mean_gross_return_percent_without_costs == sum(evaluated_returns, Decimal("0")) / Decimal(len(evaluated_returns))
        assert target_group.median_gross_return_percent_without_costs == median_return
        assert target_group.cumulative_simple_return_percent_without_costs == sum(evaluated_returns, Decimal("0"))
    else:
        assert target_group.evaluated_operations == 0
        assert target_group.win_rate_percent == Decimal("0")

    assert target_group.sample_warning is not None


def test_analysis_uses_only_past_data_for_classification(future_analysis_artifacts, analysis_artifacts):
    future_report, _, _, _, _ = future_analysis_artifacts
    original_report, _, _, _, _ = analysis_artifacts

    cutoff = original_report.observations[39].decision_time_utc
    semantic_fields = (
        "decision_time_utc",
        "period_label",
        "trend_4h_label",
        "price_1h_label",
        "volatility_label",
        "trend_4h_close",
        "trend_4h_sma",
        "trend_4h_distance_percent",
        "price_1h_close",
        "price_1h_sma",
        "price_1h_distance_percent",
        "volatility_percent",
        "volatility_lookback_15m_candles",
        "signal_generated",
        "status",
        "reasons",
        "gross_return_percent_without_costs",
    )
    original_prefix = [tuple(item.as_dict()[field] for field in semantic_fields) for item in original_report.observations if item.decision_time_utc <= cutoff]
    future_prefix = [tuple(item.as_dict()[field] for field in semantic_fields) for item in future_report.observations if item.decision_time_utc <= cutoff]
    assert original_prefix == future_prefix
    assert future_report.report_hash != original_report.report_hash


def test_analysis_rejects_tampering_and_incompatible_source(analysis_artifacts):
    report, *_ = analysis_artifacts
    payload = report.as_dict()

    payload["summary"]["decision_count"] += 1
    with pytest.raises(HistoricalMultiTimeframeStrategyAnalysisValidationError):
        HistoricalMultiTimeframeStrategyAnalysisReport.from_dict(payload)

    payload = report.as_dict()
    payload["protocol"]["source"]["strategy_hypothesis_version"] = "tampered"
    with pytest.raises(HistoricalMultiTimeframeStrategyAnalysisValidationError):
        HistoricalMultiTimeframeStrategyAnalysisReport.from_dict(payload)

    payload = report.as_dict()
    payload["protocol"]["source"]["evaluation_hash"] = "0" * 64
    with pytest.raises(HistoricalMultiTimeframeStrategyAnalysisValidationError):
        HistoricalMultiTimeframeStrategyAnalysisReport.from_dict(payload)

    payload = report.as_dict()
    payload["source_evaluation_report"]["strategy_report"]["replay"]["bundle"]["base_dataset"]["dataset"]["candles"][0]["close_time"] = "2024-01-04T08:30:00Z"
    with pytest.raises((HistoricalMultiTimeframeStrategyAnalysisValidationError, HistoricalDataIntegrityError)):
        HistoricalMultiTimeframeStrategyAnalysisReport.from_dict(payload)


def test_analysis_preserves_research_only_flags_and_rejects_promotion(analysis_artifacts):
    report, *_ = analysis_artifacts
    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    with pytest.raises(HistoricalMultiTimeframeStrategyAnalysisPromotionError):
        reject_historical_multitimeframe_strategy_analysis_promotion(report)


def test_analysis_protocol_and_group_cuts_are_versioned(analysis_artifacts):
    report, evaluation_report, *_ = analysis_artifacts
    assert report.protocol.source.evaluation_name == evaluation_report.protocol.evaluation_name
    assert report.protocol.source.evaluation_version == evaluation_report.protocol.evaluation_version
    assert report.protocol.period_cut_version == "period_window_equal_duration_v1"
    assert report.protocol.trend_cut_version == "trend_4h_close_vs_sma_v1"
    assert report.protocol.price_cut_version == "price_1h_close_vs_sma_v1"
    assert report.protocol.volatility_cut_version == "volatility_15m_trailing_mean_range_ratio_v1"
    assert report.protocol.source.bundle_hash == evaluation_report.strategy_report.replay.bundle.bundle_hash
    assert report.protocol.source.replay_hash == evaluation_report.strategy_report.replay.replay_hash


def test_analysis_load_save_conflict_detection(analysis_artifacts, future_analysis_artifacts):
    report, *_ = analysis_artifacts
    future_report, *_ = future_analysis_artifacts
    with TemporaryDirectory(dir=Path.cwd()) as temp_dir:
        path = Path(temp_dir) / "analysis.json"
        save_historical_multitimeframe_strategy_analysis_report(path, report)
        loaded = load_historical_multitimeframe_strategy_analysis_report(path)
        assert loaded.report_hash == report.report_hash
        with pytest.raises(HistoricalMultiTimeframeStrategyAnalysisConflictError):
            save_historical_multitimeframe_strategy_analysis_report(path, future_report)
