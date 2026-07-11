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
    ValidationSplitError,
    ValidationSplitConfig,
    WalkForwardValidator,
    aggregate_run_statistics,
    aggregate_segment_metrics,
    build_data_signature,
    build_manifest,
    build_expanding_windows,
    build_segment_view,
    build_window_segment_views,
    build_rolling_windows,
    compute_candidate_stability,
    freeze_selection,
    manifest_hash,
    select_configuration,
    TrustedLeakFreeBacktestRunner,
)
from validation.evaluation import evaluate_frozen_selection
from validation.models import SegmentMetrics
from validation.splits import slice_window_frames
from backtesting import BacktestConfig, LeakFreeBacktestEngine, dataframe_to_candles
from domain import DataSource, Direction, Signal


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
    winning_trades: int | None = None,
    losing_trades: int | None = None,
    gross_profit: str | None = None,
    gross_loss: str | None = None,
    average_gain: str | None = None,
    average_loss: str | None = None,
    sequencia_maxima_perdas: int = 0,
) -> SegmentMetrics:
    net_pnl_decimal = Decimal(net_pnl)
    if winning_trades is None:
        winning_trades = int(round(total_trades * (float(win_rate) / 100.0)))
    if losing_trades is None:
        losing_trades = max(0, total_trades - winning_trades)
    if gross_profit is None:
        gross_profit = net_pnl if net_pnl_decimal > 0 else "0"
    if gross_loss is None:
        gross_loss = str(abs(net_pnl_decimal)) if net_pnl_decimal < 0 else "0"
    summary = {
        "capital_initial": capital_initial,
        "capital_final": capital_final,
        "net_pnl": net_pnl,
        "return_net_percent": net_return_percent,
        "gross_pnl": gross_pnl,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "total_costs": total_costs,
        "total_fees": total_fees,
        "spread_cost": spread_cost,
        "slippage_cost": slippage_cost,
        "drawdown_max_percent": drawdown_max_percent,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "win_rate": win_rate,
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "average_gain": average_gain,
        "average_loss": average_loss,
        "sequencia_maxima_perdas": sequencia_maxima_perdas,
    }
    return SegmentMetrics.from_summary(summary)


def _candidate(name: str, **parameters) -> CandidateConfig:
    return CandidateConfig.from_mapping(name, parameters)


def _signal(timestamp, *, entry, stop, take):
    return Signal(
        symbol="BTCUSDT",
        direction=Direction.COMPRA,
        entry=entry,
        stop_loss=stop,
        take_profit=take,
        rr=Decimal("2"),
        timestamp=timestamp,
        source=DataSource.PAPER,
        score=Decimal("7"),
        regime="BULL",
        volume_status="ALTO",
        reason="warmup gated",
        strategy_version="v3_leak_free",
    )


def _window_runner_factory(train_validation_scores, test_scores):
    seen_test = {"value": False}

    def runner(df, candidate, segment, context=None, frozen_selection=None):
        context = context or {}
        assert "slices" not in context
        assert "test_metrics" not in context
        assert "candidate_evaluations" not in context
        assert "window" not in context
        assert "segment" in context
        assert "segment_view" in context
        assert "segment_signature" in context
        assert "data_signature" not in context
        segment_meta = context["segment"]
        assert segment_meta["segment_end"] >= segment_meta["segment_start"]
        assert len(df) == segment_meta["warmup_rows"] + segment_meta["segment_rows"]
        assert context["trade_start_index"] == segment_meta["trade_start_index"]
        if segment == "test":
            seen_test["value"] = True
        else:
            assert seen_test["value"] is False
        if segment == "test":
            assert "frozen_selection" in context
        else:
            assert "frozen_selection" not in context
        mapping = train_validation_scores if segment in {"train", "validation"} else test_scores
        metrics = mapping[candidate.name]
        return {"summary": metrics.as_dict()}

    return runner


def _engine_runner_factory():
    def strategy_factory(candidate):
        def strategy(history, snapshot):
            candle = history[-1]
            entry = Decimal(str(candle.close))
            return _signal(
                candle.close_time,
                entry=entry,
                stop=entry - Decimal("5"),
                take=entry + Decimal("10"),
            )

        return strategy

    trusted_runner = TrustedLeakFreeBacktestRunner(
        engine_factory=lambda: LeakFreeBacktestEngine(
            BacktestConfig(
                initial_capital=Decimal("10000"),
                risk_percent=Decimal("1"),
                slippage_rate=Decimal("0"),
                commission_rate=Decimal("0.0004"),
                leverage=Decimal("1"),
                symbol="BTCUSDT",
                interval="1h",
            )
        ),
        strategy_factory=strategy_factory,
        symbol="BTCUSDT",
        interval="1h",
    )

    def runner(df, candidate, segment, context=None, frozen_selection=None):
        context = context or {}
        segment_meta = context["segment"]
        trade_start_index = segment_meta["trade_start_index"]
        result = trusted_runner(
            df,
            candidate,
            segment=segment,
            context=context,
            frozen_selection=frozen_selection,
        )
        assert result["summary"]["total_trades"] >= 0
        assert trade_start_index >= 0
        return result

    return runner


def _ordering_runner_factory(events):
    def runner(df, candidate, segment, context=None, frozen_selection=None):
        context = context or {}
        segment_meta = context["segment"]
        if segment == "test":
            events.append(("test", candidate.name, segment_meta["name"]))
        else:
            if any(event[0] == "test" for event in events):
                raise AssertionError("train/validation executed after test phase.")
            events.append((segment, candidate.name, segment_meta["name"]))
        metrics = _metrics(net_return_percent="5", expectancy="1", profit_factor="1.5", drawdown_max_percent="2", win_rate="60", total_trades=10)
        return {"summary": metrics.as_dict()}

    return runner


def _build_sample_frame(rows: int = 220) -> pd.DataFrame:
    open_time = pd.date_range("2026-01-01", periods=rows, freq="h", tz="UTC")
    base = pd.DataFrame(
        {
            "open_time": open_time,
            "close_time": open_time + pd.Timedelta(hours=1) - pd.Timedelta(milliseconds=1),
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
    signature = build_data_signature(sample_btc_data.iloc[:220].copy(), symbol="BTCUSDT", interval="1h")
    manifest_a = build_manifest(
        symbol="BTCUSDT",
        interval="1h",
        strategy_version="v4_walk_forward",
        costs={"fee": "0.1"},
        split_config=config,
        candidate_grid=[candidate],
        windows=windows[:1],
        data_signature=signature,
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
        data_signature=signature,
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


def test_split_config_rejeita_step_bars_invalidos():
    with pytest.raises(ValidationSplitError):
        ValidationSplitConfig(step_bars=0)
    with pytest.raises(ValidationSplitError):
        ValidationSplitConfig(step_bars=-1)
    with pytest.raises(ValidationSplitError):
        ValidationSplitConfig(step_bars=False)
    with pytest.raises(ValidationSplitError):
        ValidationSplitConfig(step_bars=0.5)
    with pytest.raises(ValidationSplitError):
        ValidationSplitConfig(step_bars="5")


def test_manifest_hash_muda_com_ohlcv_e_ordem(sample_btc_data):
    signature_a = build_data_signature(sample_btc_data.iloc[:220].copy(), symbol="BTCUSDT", interval="1h")
    altered = sample_btc_data.iloc[:220].copy()
    altered.loc[10, "close"] = altered.loc[10, "close"] + 1
    signature_b = build_data_signature(altered, symbol="BTCUSDT", interval="1h")
    reordered = sample_btc_data.iloc[:220].copy().iloc[::-1].reset_index(drop=True)
    signature_c = build_data_signature(reordered, symbol="BTCUSDT", interval="1h")
    assert signature_a["content_hash"] != signature_b["content_hash"]
    assert signature_a["content_hash"] != signature_c["content_hash"]


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
    with pytest.raises(ValidationFreezeError):
        validator.run(sample_btc_data.iloc[:260].copy(), [alpha, beta], runner=runner_a)


def test_walk_forward_two_phase_selection_and_segment_signatures_are_isolated(sample_btc_data):
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

    def make_runner(recorded_events, recorded_contexts):
        seen_test = {"value": False}

        def runner(df, candidate, segment, context=None, frozen_selection=None):
            context = context or {}
            snapshot = {
                "phase": segment,
                "candidate": candidate.name,
                "segment_signature": context["segment_signature"],
                "segment_meta": context["segment"],
                "trade_start_index": context["trade_start_index"],
                "frozen": "frozen_selection" in context,
            }
            if segment == "test":
                seen_test["value"] = True
            else:
                assert seen_test["value"] is False
            recorded_events.append((segment, candidate.name))
            recorded_contexts.append(snapshot)
            metrics = _metrics(net_return_percent="5", expectancy="1", profit_factor="1.5", drawdown_max_percent="2", win_rate="60", total_trades=10)
            return {"summary": metrics.as_dict()}

        return runner

    base_df = sample_btc_data.iloc[:260].copy()
    altered_df = base_df.copy()
    altered_df.loc[220:, "close"] = altered_df.loc[220:, "close"] + 999

    events_a: list[tuple[str, str]] = []
    contexts_a: list[dict[str, object]] = []
    validator_a = WalkForwardValidator(split_config=split_config, selection_criteria=SelectionCriteria(min_total_trades=1))
    result_a = validator_a.run(base_df, [alpha, beta], runner=make_runner(events_a, contexts_a))

    events_b: list[tuple[str, str]] = []
    contexts_b: list[dict[str, object]] = []
    validator_b = WalkForwardValidator(split_config=split_config, selection_criteria=SelectionCriteria(min_total_trades=1))
    result_b = validator_b.run(altered_df, [alpha, beta], runner=make_runner(events_b, contexts_b))

    assert result_a.windows[0].selected_candidate == result_b.windows[0].selected_candidate
    assert any(item[0] == "test" for item in events_a)
    first_test_index = next(index for index, item in enumerate(events_a) if item[0] == "test")
    assert all(event[0] != "test" for event in events_a[:first_test_index])
    train_validation_a = [item for item in contexts_a if item["phase"] != "test"]
    train_validation_b = [item for item in contexts_b if item["phase"] != "test"]
    assert train_validation_a == train_validation_b
    test_contexts_a = [item for item in contexts_a if item["phase"] == "test"]
    test_contexts_b = [item for item in contexts_b if item["phase"] == "test"]
    assert test_contexts_a != test_contexts_b
    assert all("data_signature" not in context for context in contexts_a)
    assert all("data_signature" not in context for context in contexts_b)


def test_runner_context_isolation_and_warmup_engine_integration(sample_btc_data):
    alpha = _candidate("alpha", risk="low")
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
    runner = _engine_runner_factory()
    result = validator.run(_build_sample_frame(260), [alpha], runner=runner)
    assert result.windows
    assert result.summary["total_windows"] >= 1
    assert "manifest_hash" in result.summary


def test_leak_free_engine_smoke_uses_costs_and_paper_only():
    df = _build_sample_frame(5)
    candles = dataframe_to_candles(df, symbol="BTCUSDT", interval="1h")
    engine = LeakFreeBacktestEngine(
        BacktestConfig(
            initial_capital=Decimal("10000"),
            risk_percent=Decimal("1"),
            slippage_rate=Decimal("0"),
            commission_rate=Decimal("0.0004"),
            leverage=Decimal("1"),
            symbol="BTCUSDT",
            interval="1h",
        )
    )

    def strategy(history, snapshot):
        if len(history) == 1:
            candle = history[-1]
            entry = Decimal(str(candle.close))
            return _signal(candle.close_time, entry=entry, stop=entry - Decimal("5"), take=entry + Decimal("10"))
        return None

    result = engine.run(candles, strategy)
    assert result.trades
    assert result.config.paper_only is True
    assert result.summary["entry_fees"] > 0
    assert all(trade.trade.paper is True for trade in result.trades)


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
        _metrics(net_return_percent="10", net_pnl="10", gross_pnl="12", gross_profit="12", gross_loss="0", profit_factor="2.0", win_rate="66.6", total_trades=6, winning_trades=4, losing_trades=2, drawdown_max_percent="3"),
        _metrics(net_return_percent="-5", net_pnl="-5", gross_pnl="-5", gross_profit="0", gross_loss="5", profit_factor="0.5", win_rate="33.3", total_trades=4, winning_trades=1, losing_trades=3, drawdown_max_percent="8"),
    ]
    aggregated = aggregate_segment_metrics(metrics)
    assert aggregated["total_trades"] == 10
    assert aggregated["profit_factor"] is not None
    assert aggregated["win_rate"] > 0
    assert aggregated["trade_win_rate"] == pytest.approx(50.0, rel=1e-4)

    weighted_metrics = [
        _metrics(net_return_percent="6", net_pnl="6", gross_pnl="12", gross_profit="12", gross_loss="8", profit_factor="1.5", win_rate="60", total_trades=100, winning_trades=60, losing_trades=40),
        _metrics(net_return_percent="-1", net_pnl="-1", gross_pnl="-1", gross_profit="0", gross_loss="1", profit_factor="0.0", win_rate="0", total_trades=1, winning_trades=0, losing_trades=1),
    ]
    weighted = aggregate_segment_metrics(weighted_metrics)
    assert weighted["trade_win_rate"] == pytest.approx(59.4059, rel=1e-4)

    stability = compute_candidate_stability(
        _metrics(net_return_percent="10", drawdown_max_percent="3", expectancy="1"),
        _metrics(net_return_percent="5", drawdown_max_percent="6", expectancy="0.5"),
    )
    assert stability > 0

    stats = aggregate_run_statistics([])
    assert stats["total_windows"] == 0
    assert stats["profit_factor"] is None
    assert stats["trade_win_rate"] is None
    assert stats["window_dispersion"] is None
    assert stats["degradation_validation_test"] is None


def test_validation_package_has_no_network_or_executor_tokens():
    import inspect
    import validation

    source = inspect.getsource(validation)
    for token in ("requests", "httpx", "telegram", "OpenAI", "create_order", "send_order", "subprocess", "websocket"):
        assert token not in source
