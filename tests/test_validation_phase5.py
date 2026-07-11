from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd
import pytest

from validation import (
    CandidateConfig,
    CandidateEvaluation,
    FrozenSelection,
    SelectionCriteria,
    SelectionOutcome,
    ValidationEvaluationError,
    ValidationFreezeError,
    ValidationSelectionError,
    ValidationSplitConfig,
    WalkForwardValidator,
    aggregate_run_statistics,
    aggregate_segment_metrics,
    build_manifest,
    build_expanding_windows,
    build_rolling_windows,
    compute_candidate_stability,
    freeze_selection,
    manifest_hash,
    select_configuration,
)
from validation.evaluation import evaluate_frozen_selection
from validation.models import SegmentMetrics
from validation.splits import slice_window_frames


def _metrics(
    *,
    capital_initial: str = "1000",
    capital_final: str = "1000",
    net_pnl: str = "0",
    net_return_percent: str = "0",
    gross_pnl: str = "0",
    total_costs: str = "0",
    total_fees: str = "0",
    spread_cost: str = "0",
    slippage_cost: str = "0",
    drawdown_max_percent: str = "0",
    expectancy: str = "0",
    profit_factor: str | None = "1",
    win_rate: str = "0",
    total_trades: int = 10,
    average_gain: str | None = None,
    average_loss: str | None = None,
    sequencia_maxima_perdas: int = 0,
) -> SegmentMetrics:
    summary = {
        "capital_initial": capital_initial,
        "capital_final": capital_final,
        "net_pnl": net_pnl,
        "return_net_percent": net_return_percent,
        "gross_pnl": gross_pnl,
        "total_costs": total_costs,
        "total_fees": total_fees,
        "spread_cost": spread_cost,
        "slippage_cost": slippage_cost,
        "drawdown_max_percent": drawdown_max_percent,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "win_rate": win_rate,
        "total_trades": total_trades,
        "average_gain": average_gain,
        "average_loss": average_loss,
        "sequencia_maxima_perdas": sequencia_maxima_perdas,
    }
    return SegmentMetrics.from_summary(summary)


def _candidate(name: str, **parameters) -> CandidateConfig:
    return CandidateConfig.from_mapping(name, parameters)


def _window_runner_factory(train_validation_scores, test_scores):
    def runner(df, candidate, segment, context=None, frozen_selection=None):
        mapping = train_validation_scores if segment in {"train", "validation"} else test_scores
        metrics = mapping[candidate.name]
        return {"summary": metrics.as_dict()}

    return runner


def _build_sample_frame(rows: int = 220) -> pd.DataFrame:
    open_time = pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC")
    base = pd.DataFrame(
        {
            "open_time": open_time,
            "open": [100 + i for i in range(rows)],
            "high": [101 + i for i in range(rows)],
            "low": [99 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
            "volume": [1000 + i for i in range(rows)],
        }
    )
    return base


def test_split_windows_respeitam_ordem_purge_embargo(sample_btc_data):
    config = ValidationSplitConfig(
        mode="rolling",
        train_bars=80,
        validation_bars=20,
        test_bars=20,
        warmup_bars=10,
        purge_bars=5,
        embargo_bars=5,
        step_bars=20,
    )
    windows = build_rolling_windows(sample_btc_data.iloc[:220].copy(), config)
    assert windows
    for window in windows:
        assert window.warmup_start <= window.train_start <= window.train_end <= window.validation_start <= window.validation_end <= window.test_start <= window.test_end
        slices = slice_window_frames(sample_btc_data.iloc[:220], window)
        assert len(slices["train"]) == 80
        assert len(slices["validation"]) == 20
        assert len(slices["test"]) == 20
        assert len(slices["warmup"]) <= 10


def test_expanding_windows_grows_train_window(sample_btc_data):
    config = ValidationSplitConfig(
        mode="expanding",
        train_bars=60,
        validation_bars=20,
        test_bars=20,
        warmup_bars=10,
        purge_bars=5,
        embargo_bars=5,
        step_bars=20,
    )
    windows = build_expanding_windows(sample_btc_data.iloc[:220].copy(), config)
    assert len(windows) >= 2
    assert windows[0].train_end < windows[-1].train_end
    assert all(window.mode == "expanding" for window in windows)


def test_selection_uses_only_train_and_validation_and_breaks_ties_deterministically():
    alpha = _candidate("alpha", risk="low")
    beta = _candidate("beta", risk="low")
    same_train = _metrics(net_return_percent="10", expectancy="2", profit_factor="2.0", drawdown_max_percent="1", win_rate="60")
    same_validation = _metrics(net_return_percent="11", expectancy="2", profit_factor="2.0", drawdown_max_percent="1", win_rate="61")
    candidate_evaluations = (
        CandidateEvaluation(candidate=alpha, train_metrics=same_train, validation_metrics=same_validation, stability_score=Decimal("0.2")),
        CandidateEvaluation(candidate=beta, train_metrics=same_train, validation_metrics=same_validation, stability_score=Decimal("0.2")),
    )
    outcome = select_configuration(candidate_evaluations, SelectionCriteria(min_total_trades=1))
    assert outcome.approved is True
    assert outcome.candidate == beta
    assert outcome.ranking == ("beta", "alpha")


def test_selection_rejects_when_thresholds_are_not_met():
    alpha = _candidate("alpha", risk="low")
    candidate_evaluations = (
        CandidateEvaluation(
            candidate=alpha,
            train_metrics=_metrics(total_trades=1, net_return_percent="-1", expectancy="-1", profit_factor=None, drawdown_max_percent="50"),
            validation_metrics=_metrics(total_trades=1, net_return_percent="-1", expectancy="-1", profit_factor=None, drawdown_max_percent="50"),
            stability_score=Decimal("0.5"),
        ),
    )
    outcome = select_configuration(
        candidate_evaluations,
        SelectionCriteria(min_total_trades=5, min_net_return=Decimal("0"), min_expectancy=Decimal("0"), min_profit_factor=Decimal("1")),
    )
    assert outcome.approved is False
    assert outcome.candidate is None
    assert "aprovada" in outcome.reason


def test_manifest_and_freeze_are_deterministic_and_utc(sample_btc_data):
    config = ValidationSplitConfig()
    windows = build_rolling_windows(sample_btc_data.iloc[:220].copy(), config)
    candidate = _candidate("alpha", risk="low")
    manifest_a = build_manifest(
        symbol="BTCUSDT",
        interval="1h",
        strategy_version="v4_walk_forward",
        costs={"fee": "0.1"},
        split_config=config,
        candidate_grid=[candidate],
        windows=windows[:1],
        data_signature={"rows": 220},
        seed=7,
    )
    manifest_b = build_manifest(
        symbol="BTCUSDT",
        interval="1h",
        strategy_version="v4_walk_forward",
        costs={"fee": "0.1"},
        split_config=config,
        candidate_grid=[candidate],
        windows=windows[:1],
        data_signature={"rows": 220},
        seed=7,
    )
    assert manifest_hash(manifest_a) == manifest_hash(manifest_b)
    frozen = freeze_selection(
        candidate,
        strategy_version="v4_walk_forward",
        costs={"fee": "0.1"},
        symbol="BTCUSDT",
        interval="1h",
        frozen_at=datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
        manifest_hash_value=manifest_hash(manifest_a),
        window_id="0:1:2",
    )
    assert frozen.as_dict()["frozen_at"] == "2026-07-10T12:00:00Z"


def test_walk_forward_selection_ignores_test_metrics_and_freezes_once(sample_btc_data):
    alpha = _candidate("alpha", risk="low")
    beta = _candidate("beta", risk="medium")
    split_config = ValidationSplitConfig(
        mode="rolling",
        train_bars=120,
        validation_bars=40,
        test_bars=40,
        warmup_bars=20,
        purge_bars=5,
        embargo_bars=5,
        step_bars=40,
    )
    validator = WalkForwardValidator(
        split_config=split_config,
        selection_criteria=SelectionCriteria(min_total_trades=1, min_profit_factor=Decimal("1")),
        strategy_version="v4_walk_forward",
        costs={"fee": "0.1"},
        symbol="BTCUSDT",
        interval="1h",
        seed=11,
    )
    train_validation_scores = {
        "alpha": _metrics(net_return_percent="12", expectancy="3", profit_factor="2.5", drawdown_max_percent="2", win_rate="70"),
        "beta": _metrics(net_return_percent="8", expectancy="1", profit_factor="1.2", drawdown_max_percent="5", win_rate="55"),
    }
    test_scores_better_beta = {
        "alpha": _metrics(net_return_percent="-5", expectancy="-1", profit_factor="0.7", drawdown_max_percent="8", win_rate="40"),
        "beta": _metrics(net_return_percent="20", expectancy="5", profit_factor="4.0", drawdown_max_percent="1", win_rate="80"),
    }
    runner_a = _window_runner_factory(train_validation_scores, test_scores_better_beta)
    result_a = validator.run(sample_btc_data.iloc[:260].copy(), [alpha, beta], runner=runner_a)
    assert result_a.windows
    assert result_a.windows[0].selected_candidate == alpha
    assert result_a.windows[0].test_metrics is not None
    assert result_a.summary["manifest_hash"] == result_a.manifest["manifest_hash"]
    assert result_a.summary["strategy_version"] == "v4_walk_forward"
    assert result_a.summary["symbol"] == "BTCUSDT"

    different_test_scores = {
        "alpha": _metrics(net_return_percent="30", expectancy="7", profit_factor="5.0", drawdown_max_percent="1", win_rate="85"),
        "beta": _metrics(net_return_percent="-1", expectancy="0", profit_factor="0.9", drawdown_max_percent="9", win_rate="45"),
    }
    runner_b = _window_runner_factory(train_validation_scores, different_test_scores)
    validator_b = WalkForwardValidator(
        split_config=split_config,
        selection_criteria=SelectionCriteria(min_total_trades=1, min_profit_factor=Decimal("1")),
        strategy_version="v4_walk_forward",
        costs={"fee": "0.1"},
        symbol="BTCUSDT",
        interval="1h",
        seed=11,
    )
    result_b = validator_b.run(sample_btc_data.iloc[:260].copy(), [alpha, beta], runner=runner_b)
    assert result_b.windows[0].selected_candidate == alpha
    assert result_b.windows[0].test_metrics is not None
    assert result_a.windows[0].test_metrics != result_b.windows[0].test_metrics


def test_validate_frozen_selection_blocks_mismatch_and_reselection(sample_btc_data):
    alpha = _candidate("alpha", risk="low")
    beta = _candidate("beta", risk="medium")
    split_config = ValidationSplitConfig(
        mode="rolling",
        train_bars=120,
        validation_bars=40,
        test_bars=40,
        warmup_bars=20,
        purge_bars=5,
        embargo_bars=5,
        step_bars=40,
    )
    validator = WalkForwardValidator(split_config=split_config, selection_criteria=SelectionCriteria(min_total_trades=1))
    runner = _window_runner_factory(
        {
            "alpha": _metrics(net_return_percent="5", expectancy="1", profit_factor="1.5", drawdown_max_percent="2", win_rate="60"),
            "beta": _metrics(net_return_percent="4", expectancy="0.5", profit_factor="1.2", drawdown_max_percent="3", win_rate="55"),
        },
        {
            "alpha": _metrics(net_return_percent="5", expectancy="1", profit_factor="1.5", drawdown_max_percent="2", win_rate="60"),
            "beta": _metrics(net_return_percent="4", expectancy="0.5", profit_factor="1.2", drawdown_max_percent="3", win_rate="55"),
        },
    )
    result = validator.run(sample_btc_data.iloc[:260].copy(), [alpha, beta], runner=runner)
    frozen = result.windows[0].frozen_selection
    assert frozen is not None
    with pytest.raises(ValidationFreezeError):
        validator.select_window(result.windows[0].candidate_evaluations)
    with pytest.raises(ValidationEvaluationError):
        evaluate_frozen_selection(
            sample_btc_data.iloc[:40].copy(),
            beta,
            frozen,
            segment="test",
            runner=runner,
        )


def test_statistics_and_validation_errors_cover_edge_cases():
    metrics = [
        _metrics(net_return_percent="10", net_pnl="10", gross_pnl="12", profit_factor="2.0", win_rate="66.6", total_trades=6, drawdown_max_percent="3"),
        _metrics(net_return_percent="-5", net_pnl="-5", gross_pnl="-5", profit_factor="0.5", win_rate="33.3", total_trades=4, drawdown_max_percent="8"),
    ]
    aggregated = aggregate_segment_metrics(metrics)
    assert aggregated["total_trades"] == 10
    assert aggregated["profit_factor"] is not None
    assert aggregated["win_rate"] > 0

    stability = compute_candidate_stability(
        _metrics(net_return_percent="10", drawdown_max_percent="3", expectancy="1"),
        _metrics(net_return_percent="5", drawdown_max_percent="6", expectancy="0.5"),
    )
    assert stability > 0

    stats = aggregate_run_statistics([])
    assert stats["total_windows"] == 0
    assert stats["profit_factor"] == 0.0


def test_validation_package_has_no_network_or_executor_tokens():
    import inspect
    import validation

    source = inspect.getsource(validation)
    for token in ("requests", "httpx", "telegram", "OpenAI", "create_order", "send_order", "subprocess", "websocket"):
        assert token not in source
