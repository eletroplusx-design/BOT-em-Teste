from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median

import pytest

from domain import Candle, DataSource
from historical_multitimeframe_evaluation import (
    HistoricalMultiTimeframeFirstStrategyEvaluationConflictError,
    HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError,
    HistoricalMultiTimeframeFirstStrategyEvaluationPromotionError,
    HistoricalMultiTimeframeFirstStrategyEvaluationProtocol,
    HistoricalMultiTimeframeFirstStrategyEvaluationReport,
    HistoricalMultiTimeframeFirstStrategyEvaluationResult,
    HistoricalMultiTimeframeFirstStrategyEvaluationValidationError,
    build_historical_multitimeframe_first_strategy_evaluation_protocol,
    load_historical_multitimeframe_first_strategy_evaluation_report,
    reject_historical_multitimeframe_first_strategy_evaluation_promotion,
    run_historical_multitimeframe_first_strategy_evaluation,
    save_historical_multitimeframe_first_strategy_evaluation_report,
    status_historical_multitimeframe_first_strategy_evaluation_report,
    verify_historical_multitimeframe_first_strategy_evaluation_report,
)
from historical_multitimeframe_experiments import build_historical_multitimeframe_replay
from historical_multitimeframe_strategy import (
    build_historical_multitimeframe_first_strategy_config,
    build_historical_multitimeframe_first_strategy_factory,
    run_historical_multitimeframe_first_strategy,
)
from market_data import (
    HistoricalDataset,
    HistoricalDatasetRequest,
    HistoricalProviderQualification,
    build_historical_manifest,
    build_historical_multitimeframe_bundle,
    historical_content_hash,
)
from market_data.historical_store import save_historical_dataset


ONE_MS = timedelta(milliseconds=1)
FIFTEEN_MINUTES = timedelta(minutes=15)
ONE_HOUR = timedelta(hours=1)
FOUR_HOURS = timedelta(hours=4)
BASE_15M_START = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
KUCOIN_ENDPOINT = "https://api.kucoin.com/api/v1/market/candles"


def _qualification(interval: str, *, symbol: str = "BTCUSDT") -> HistoricalProviderQualification:
    return HistoricalProviderQualification.kucoin_public_spot(symbol=symbol, interval=interval)


def _interval_delta(interval: str) -> timedelta:
    return {
        "15m": FIFTEEN_MINUTES,
        "1h": ONE_HOUR,
        "4h": FOUR_HOURS,
    }[interval]


def _dataset(
    tmp_path: Path,
    *,
    interval: str,
    start: datetime,
    count: int,
    symbol: str = "BTCUSDT",
    direction: str = "up",
    trigger_index: int | None = None,
    tail_shift: int = 0,
    tail_shift_start: int | None = None,
) -> tuple[Path, HistoricalDataset]:
    qualification = _qualification(interval, symbol=symbol)
    step = _interval_delta(interval)
    candles: list[Candle] = []
    trigger_index = count - 1 if trigger_index is None else trigger_index
    for idx in range(count):
        if interval == "15m":
            if idx < trigger_index:
                open_value = Decimal("100") + Decimal(idx)
                close_value = Decimal("101") + Decimal(idx)
            elif idx == trigger_index:
                open_value = Decimal("200") + Decimal(idx)
                close_value = Decimal("1000") + Decimal(idx)
            else:
                shift_applies = tail_shift_start is None or idx >= tail_shift_start
                if direction == "down":
                    open_value = Decimal("50") + (Decimal(tail_shift) if shift_applies else Decimal("0")) + Decimal(idx)
                    close_value = open_value - Decimal("1")
                else:
                    open_value = Decimal("200") + (Decimal(tail_shift) if shift_applies else Decimal("0")) + Decimal(idx)
                    close_value = open_value + Decimal("1")
            high_value = max(open_value, close_value) + Decimal("1")
            low_value = min(open_value, close_value) - Decimal("1")
            if idx == trigger_index:
                high_value = close_value + Decimal("100")
                low_value = min(low_value, close_value - Decimal("2"))
        else:
            if direction == "down":
                open_value = Decimal("500") - (Decimal(idx) * Decimal("2"))
                close_value = Decimal("499") - (Decimal(idx) * Decimal("2"))
            else:
                open_value = Decimal("100") + (Decimal(idx) * Decimal("2"))
                close_value = Decimal("101") + (Decimal(idx) * Decimal("2"))
            high_value = max(open_value, close_value) + Decimal("1")
            low_value = min(open_value, close_value) - Decimal("1")
        candles.append(
            Candle.from_dict(
                {
                    "open_time": start + (idx * step),
                    "close_time": start + (idx * step) + step - ONE_MS,
                    "open": str(open_value),
                    "high": str(high_value),
                    "low": str(low_value),
                    "close": str(close_value),
                    "volume": str(1000 + idx),
                    "symbol": symbol,
                    "interval": interval,
                    "source": DataSource.KUCOIN,
                }
            )
        )
    request = HistoricalDatasetRequest(
        provider=qualification.provider_id,
        provider_qualification=qualification,
        endpoint=KUCOIN_ENDPOINT,
        symbol=symbol,
        interval=interval,
        requested_start_utc=candles[0].open_time,
        requested_end_utc=candles[-1].close_time,
        page_size=1500,
        closed_candles_only=True,
    )
    manifest = build_historical_manifest(
        request=request,
        effective_start_utc=candles[0].open_time,
        effective_end_utc=candles[-1].close_time,
        created_at_utc=candles[-1].close_time + timedelta(days=1),
        candle_count=len(candles),
        page_count=1,
        gap_count=0,
        duplicate_count=0,
        content_hash=historical_content_hash(candles),
    )
    dataset = HistoricalDataset(manifest=manifest, candles=tuple(candles))
    start_key = start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = tmp_path / f"kucoin-{interval}-{direction}-{tail_shift}-{start_key}-{count}.json"
    save_historical_dataset(path, dataset)
    return path, dataset


def _bundle(
    tmp_path: Path,
    *,
    base_count: int = 30,
    one_hour_count: int = 30,
    four_hour_count: int = 30,
    trigger_index: int | None = None,
    tail_shift: int = 0,
    tail_shift_start: int | None = None,
    base_direction: str = "down",
    one_hour_direction: str = "up",
    four_hour_direction: str = "up",
) -> tuple[HistoricalDataset, HistoricalDataset, HistoricalDataset, object]:
    _, base = _dataset(
        tmp_path,
        interval="15m",
        start=BASE_15M_START,
        count=base_count,
        direction=base_direction,
        trigger_index=base_count - 1 if trigger_index is None else trigger_index,
        tail_shift=tail_shift,
        tail_shift_start=tail_shift_start,
    )
    _, one_hour = _dataset(
        tmp_path,
        interval="1h",
        start=BASE_15M_START - timedelta(hours=24),
        count=one_hour_count,
        direction=one_hour_direction,
    )
    _, four_hour = _dataset(
        tmp_path,
        interval="4h",
        start=BASE_15M_START - timedelta(days=4),
        count=four_hour_count,
        direction=four_hour_direction,
    )
    bundle = build_historical_multitimeframe_bundle(base, one_hour, four_hour)
    return base, one_hour, four_hour, build_historical_multitimeframe_replay(bundle)


def _strategy_report(tmp_path: Path, *, trigger_index: int | None = None, tail_shift: int = 0, tail_shift_start: int | None = None, base_count: int = 30, exit_horizon: int = 4):
    _, _, _, replay = _bundle(
        tmp_path,
        base_count=base_count,
        trigger_index=trigger_index,
        tail_shift=tail_shift,
        tail_shift_start=tail_shift_start,
    )
    config = build_historical_multitimeframe_first_strategy_config()
    report = run_historical_multitimeframe_first_strategy(replay, config=config)
    evaluation = run_historical_multitimeframe_first_strategy_evaluation(report, exit_horizon_15m_candles=exit_horizon)
    return report, evaluation


def _find_decision(report, *, decision_time: datetime):
    return next(decision for decision in report.decisions if decision.decision_time_utc == decision_time)


def test_protocol_hash_is_canonical_and_round_trips(tmp_path):
    report, _ = _strategy_report(tmp_path)
    protocol = build_historical_multitimeframe_first_strategy_evaluation_protocol(report)
    round_tripped = type(protocol).from_dict(protocol.as_dict())

    assert protocol == round_tripped
    assert protocol.protocol_hash == round_tripped.protocol_hash
    assert protocol.as_dict() == round_tripped.as_dict()
    assert protocol.historical_research_only is True
    assert protocol.operational_evidence is False
    assert protocol.paper_promotion_eligible is False


def test_entry_uses_next_candle_open_and_exit_uses_fixed_horizon(tmp_path):
    report, evaluation = _strategy_report(tmp_path, trigger_index=20, base_count=32, exit_horizon=4)
    decision = _find_decision(report, decision_time=report.decisions[20].decision_time_utc)
    result = next(item for item in evaluation.results if item.decision_hash == decision.decision_hash)
    base_candles = report.replay.bundle.base_dataset.candles

    assert result.status == "evaluated"
    assert result.signal_generated is True
    assert result.entry_open_time_utc == base_candles[21].open_time
    assert result.entry_open == base_candles[21].open
    assert result.exit_open_time_utc == base_candles[25].open_time
    assert result.exit_open == base_candles[25].open
    assert result.holding_period_15m_candles == 4
    assert result.gross_return_percent_without_costs == ((base_candles[25].open - base_candles[21].open) / base_candles[21].open) * Decimal("100")


def test_future_data_does_not_change_earlier_signal_or_evaluation(tmp_path):
    _, evaluation_a = _strategy_report(tmp_path, trigger_index=20, base_count=32, tail_shift=0, exit_horizon=4)
    report_b, evaluation_b = _strategy_report(
        tmp_path,
        trigger_index=20,
        base_count=32,
        tail_shift=25,
        tail_shift_start=26,
        exit_horizon=4,
    )

    decision_a = _find_decision(evaluation_a.strategy_report, decision_time=evaluation_a.strategy_report.decisions[20].decision_time_utc)
    decision_b = _find_decision(report_b, decision_time=report_b.decisions[20].decision_time_utc)
    result_a = next(item for item in evaluation_a.results if item.decision_hash == decision_a.decision_hash)
    result_b = next(item for item in evaluation_b.results if item.decision_hash == decision_b.decision_hash)

    assert decision_a.signal.signal_hash == decision_b.signal.signal_hash
    assert result_a.signal_hash == result_b.signal_hash
    assert result_a.gross_return_percent_without_costs == result_b.gross_return_percent_without_costs


def test_missing_entry_or_exit_is_not_evaluable(tmp_path):
    _, missing_entry = _strategy_report(tmp_path, trigger_index=20, base_count=21, exit_horizon=4)
    _, missing_exit = _strategy_report(tmp_path, trigger_index=20, base_count=23, exit_horizon=4)

    entry_result = missing_entry.results[20]
    exit_result = missing_exit.results[20]

    assert entry_result.status == "not_evaluable"
    assert "entry" in " ".join(entry_result.reasons).lower()
    assert entry_result.entry_open_time_utc is None
    assert entry_result.exit_open_time_utc is None
    assert entry_result.gross_return_percent_without_costs is None

    assert exit_result.status == "not_evaluable"
    assert "exit" in " ".join(exit_result.reasons).lower()
    assert exit_result.entry_open_time_utc is not None
    assert exit_result.entry_open is not None
    assert exit_result.exit_open_time_utc is None
    assert exit_result.gross_return_percent_without_costs is None


def test_metrics_are_deterministic_and_match_the_results(tmp_path):
    _, evaluation_a = _strategy_report(tmp_path, trigger_index=20, base_count=32, exit_horizon=4)
    _, evaluation_b = _strategy_report(tmp_path, trigger_index=20, base_count=32, exit_horizon=4)
    returns = [
        result.gross_return_percent_without_costs
        for result in evaluation_a.results
        if result.status == "evaluated" and result.gross_return_percent_without_costs is not None
    ]
    evaluated_operations = len(returns)
    signal_count = sum(1 for result in evaluation_a.results if result.signal_generated)
    no_signal_decisions = sum(1 for result in evaluation_a.results if result.status == "no_signal")
    not_evaluable_entries = sum(1 for result in evaluation_a.results if result.status == "not_evaluable")
    if evaluated_operations:
        expected_win_rate = (Decimal(sum(1 for value in returns if value > 0)) / Decimal(evaluated_operations)) * Decimal("100")
        expected_mean = sum(returns, Decimal("0")) / Decimal(evaluated_operations)
        expected_median = median(returns)
        expected_cumulative = sum(returns, Decimal("0"))
    else:
        expected_win_rate = Decimal("0")
        expected_mean = Decimal("0")
        expected_median = Decimal("0")
        expected_cumulative = Decimal("0")

    assert evaluation_a.evaluation_hash == evaluation_b.evaluation_hash
    assert evaluation_a.as_hash_payload() == evaluation_b.as_hash_payload()
    assert evaluation_a.metrics == evaluation_b.metrics
    assert evaluation_a.metrics.signal_count == signal_count
    assert evaluation_a.metrics.evaluated_operations == evaluated_operations
    assert evaluation_a.metrics.no_signal_decisions == no_signal_decisions
    assert evaluation_a.metrics.not_evaluable_entries == not_evaluable_entries
    assert evaluation_a.metrics.win_rate_percent == expected_win_rate
    assert evaluation_a.metrics.mean_gross_return_percent_without_costs == expected_mean
    assert evaluation_a.metrics.median_gross_return_percent_without_costs == expected_median
    assert evaluation_a.metrics.cumulative_simple_return_percent_without_costs == expected_cumulative


def test_save_load_verify_status_and_hash_round_trip(tmp_path):
    _, evaluation = _strategy_report(tmp_path, trigger_index=20, base_count=32, exit_horizon=4)
    path = tmp_path / "evaluation.json"
    saved = save_historical_multitimeframe_first_strategy_evaluation_report(path, evaluation)
    loaded = load_historical_multitimeframe_first_strategy_evaluation_report(path)
    verified = verify_historical_multitimeframe_first_strategy_evaluation_report(path)
    status = status_historical_multitimeframe_first_strategy_evaluation_report(path)

    assert saved == evaluation
    assert loaded == evaluation
    assert verified["verified"] is True
    assert verified["evaluation_hash"] == evaluation.evaluation_hash
    assert status["exists"] is True
    assert status["evaluation_hash"] == evaluation.evaluation_hash
    assert path.exists()


def test_tampering_of_protocol_report_or_provenance_is_rejected(tmp_path):
    _, evaluation = _strategy_report(tmp_path, trigger_index=20, base_count=32, exit_horizon=4)
    payload = evaluation.as_dict()

    payload["protocol"]["exit_horizon_15m_candles"] = 5
    with pytest.raises(HistoricalMultiTimeframeFirstStrategyEvaluationValidationError):
        type(evaluation).from_dict(payload)

    payload = evaluation.as_dict()
    payload["strategy_report"]["factory"]["config"]["donchian_lookback"] = 99
    with pytest.raises(HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError):
        type(evaluation).from_dict(payload)

    payload = evaluation.as_dict()
    payload["strategy_report"]["replay"]["bundle"]["base_dataset"]["dataset"]["manifest"]["provider_qualification"]["market_type"] = "futures"
    with pytest.raises(HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError):
        type(evaluation).from_dict(payload)


def test_future_candle_in_decision_context_is_rejected(tmp_path):
    _, evaluation = _strategy_report(tmp_path, trigger_index=20, base_count=32, exit_horizon=4)
    payload = evaluation.as_dict()
    payload["strategy_report"]["context_series"]["contexts"][0]["supporting_windows"][0]["candles"][-1]["close_time"] = "2030-01-01T00:00:00Z"

    with pytest.raises(HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError):
        type(evaluation).from_dict(payload)


def test_research_only_and_promotion_ineligible(tmp_path):
    _, evaluation = _strategy_report(tmp_path, trigger_index=20, base_count=32, exit_horizon=4)

    assert evaluation.historical_research_only is True
    assert evaluation.operational_evidence is False
    assert evaluation.paper_promotion_eligible is False
    with pytest.raises(HistoricalMultiTimeframeFirstStrategyEvaluationPromotionError):
        reject_historical_multitimeframe_first_strategy_evaluation_promotion(evaluation)


def test_compatibility_with_existing_multitimeframe_contracts(tmp_path):
    _, base = _dataset(tmp_path, interval="15m", start=BASE_15M_START, count=20, trigger_index=19)
    _, one_hour = _dataset(tmp_path, interval="1h", start=BASE_15M_START - ONE_HOUR, count=30, direction="up")
    _, four_hour = _dataset(tmp_path, interval="4h", start=BASE_15M_START - FOUR_HOURS, count=30, direction="up")
    bundle = build_historical_multitimeframe_bundle(base, one_hour, four_hour)
    replay = build_historical_multitimeframe_replay(bundle)
    config = build_historical_multitimeframe_first_strategy_config()
    factory = build_historical_multitimeframe_first_strategy_factory(config)
    strategy_report = run_historical_multitimeframe_first_strategy(replay, factory=factory)
    evaluation = run_historical_multitimeframe_first_strategy_evaluation(strategy_report, exit_horizon_15m_candles=4)

    assert strategy_report.replay.bundle.bundle_hash == replay.bundle.bundle_hash
    assert strategy_report.historical_research_only is True
    assert evaluation.strategy_report.report_hash == strategy_report.report_hash
    assert evaluation.protocol.strategy_config_hash == config.config_hash
    assert evaluation.protocol.strategy_factory_hash == factory.factory_hash

