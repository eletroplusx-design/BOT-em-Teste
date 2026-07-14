from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from promotion import (
    MonitoredPaperLimits,
    PaperMonitoringSessionContract,
    PaperMonitoringSnapshot,
    PromotionEvidence,
    PromotionEvidenceError,
    PromotionPolicy,
    PromotionStatus,
    adapt_walk_forward_result,
    build_promotion_report,
    evaluate_promotion,
    evaluate_paper_monitoring,
    promotion_hash,
)
from promotion.errors import PromotionDecisionError, PromotionPolicyError
from validation.artifacts import build_data_signature, build_manifest, freeze_selection
from validation.models import CandidateConfig, CandidateEvaluation, FrozenSelection, SegmentMetrics, ValidationSplitConfig, WindowBounds, WalkForwardResult, WalkForwardWindowResult
from validation.splits import build_rolling_windows


def _candidate(name: str = "alpha") -> CandidateConfig:
    return CandidateConfig.from_mapping(name, {"risk": "low"})


def _metrics(*, net_return_percent: str = "5", expectancy: str = "1", profit_factor: str | None = "1.5", drawdown_max_percent: str = "5", total_trades: int = 12, winning_trades: int = 7, losing_trades: int = 4, breakeven_trades: int = 1, gross_profit: str = "140", gross_loss: str = "80") -> SegmentMetrics:
    capital_initial = Decimal("10000")
    net_return_decimal = Decimal(str(net_return_percent))
    net_pnl = (capital_initial * net_return_decimal / Decimal("100")).quantize(Decimal("0.0001"))
    return SegmentMetrics.from_summary(
        {
            "capital_initial": "10000",
            "capital_final": str((capital_initial + net_pnl).quantize(Decimal("0.0001"))),
            "net_pnl": str(net_pnl),
            "net_return_percent": net_return_percent,
            "gross_pnl": "0",
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "total_costs": "5",
            "total_fees": "2",
            "spread_cost": "1",
            "slippage_cost": "2",
            "drawdown_max_percent": drawdown_max_percent,
            "expectancy": expectancy,
            "profit_factor": profit_factor,
            "win_rate": "58.3333",
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "breakeven_trades": breakeven_trades,
        }
    )


def _sample_frame(rows: int = 260) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=rows, freq="h", tz="UTC")
    base = pd.DataFrame(
        {
            "open_time": index,
            "close_time": index + pd.Timedelta(hours=1) - pd.Timedelta(milliseconds=1),
            "open": [100 + i for i in range(rows)],
            "high": [101 + i for i in range(rows)],
            "low": [99 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
            "volume": [1000 + i for i in range(rows)],
        }
    )
    return base


def _window_result(
    *,
    window: WindowBounds,
    candidate: CandidateConfig,
    manifest_hash_value: str,
    trade_base: int,
) -> WalkForwardWindowResult:
    train_metrics = _metrics(net_return_percent="6", expectancy="1.2", profit_factor="1.4", drawdown_max_percent="4", total_trades=12, winning_trades=7, losing_trades=4, breakeven_trades=1, gross_profit="120", gross_loss="80")
    validation_metrics = _metrics(net_return_percent="5", expectancy="1.1", profit_factor="1.35", drawdown_max_percent="5", total_trades=11, winning_trades=6, losing_trades=4, breakeven_trades=1, gross_profit="110", gross_loss="80")
    test_metrics = _metrics(net_return_percent="4", expectancy="1.0", profit_factor="1.25", drawdown_max_percent="6", total_trades=10, winning_trades=6, losing_trades=3, breakeven_trades=1, gross_profit="100", gross_loss="80")
    evaluation = CandidateEvaluation(candidate=candidate, train_metrics=train_metrics, validation_metrics=validation_metrics, stability_score=Decimal("0.2"))
    frozen = freeze_selection(
        candidate,
        strategy_version="v4_walk_forward",
        costs={"entry_fee_rate": "0.0004", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5", "leverage": "1"},
        execution_contract={"engine_class": "LeakFreeBacktestEngine", "entry_fee_rate": "0.0004", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5", "leverage": "1", "intrabar_policy": "STOP_FIRST", "gap_policy": "OPEN_PRICE", "paper_only": True, "symbol": "BTCUSDT", "interval": "1h", "strategy_version": "v4_walk_forward"},
        symbol="BTCUSDT",
        interval="1h",
        frozen_at=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
        manifest_hash_value=manifest_hash_value,
        window_id=f"{trade_base}:{trade_base + 1}:{trade_base + 2}",
    )
    return WalkForwardWindowResult(
        bounds=window,
        candidate_evaluations=(evaluation,),
        selected_candidate=candidate,
        frozen_selection=frozen,
        test_metrics=test_metrics,
        manifest_hash=manifest_hash_value,
        approved=True,
        reason="approved",
    )


def _promotion_result(
    *,
    window_count: int = 3,
    runner_trusted: bool = True,
    paper_only: bool = True,
    engine_class: str = "LeakFreeBacktestEngine",
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    strategy_version: str = "v4_walk_forward",
    entry_fee_rate: str = "0.0004",
    exit_fee_rate: str = "0.0004",
    spread_bps: str = "5",
    slippage_bps: str = "5",
    total_trades: int = 10,
    net_return_percent: str = "4",
    expectancy: str = "1",
    profit_factor: str | None = "1.25",
    drawdown_max_percent: str = "6",
    validation_degradation: str = "1",
    profitable_windows: int | None = None,
    manifest_override: dict[str, object] | None = None,
    tamper_window_hash: bool = False,
    trade_counts: list[int] | None = None,
) -> WalkForwardResult:
    frame = _sample_frame(340)
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
    costs = {
        "entry_fee_rate": entry_fee_rate,
        "exit_fee_rate": exit_fee_rate,
        "spread_bps": spread_bps,
        "slippage_bps": slippage_bps,
        "leverage": "1",
    }
    execution_contract = {
        "engine_class": engine_class,
        "entry_fee_rate": entry_fee_rate,
        "exit_fee_rate": exit_fee_rate,
        "spread_bps": spread_bps,
        "slippage_bps": slippage_bps,
        "leverage": "1",
        "intrabar_policy": "STOP_FIRST",
        "gap_policy": "OPEN_PRICE",
        "paper_only": paper_only,
        "symbol": symbol,
        "interval": interval,
        "strategy_version": strategy_version,
    }
    windows_bounds = build_rolling_windows(frame, split_config)[:window_count]
    candidate = _candidate("alpha")
    window_results: list[WalkForwardWindowResult] = []
    window_signatures: list[dict[str, object]] = []
    for idx, bounds in enumerate(windows_bounds):
        window_signature = {
            "warmup_train": build_data_signature(frame.iloc[bounds.warmup_start : bounds.train_start], symbol=symbol, interval=interval),
            "train": build_data_signature(frame.iloc[bounds.train_start : bounds.train_end], symbol=symbol, interval=interval),
            "warmup_validation": build_data_signature(frame.iloc[bounds.train_end : bounds.validation_start], symbol=symbol, interval=interval),
            "validation": build_data_signature(frame.iloc[bounds.validation_start : bounds.validation_end], symbol=symbol, interval=interval),
            "warmup_test": build_data_signature(frame.iloc[bounds.validation_end : bounds.test_start], symbol=symbol, interval=interval),
            "test": build_data_signature(frame.iloc[bounds.test_start : bounds.test_end], symbol=symbol, interval=interval),
        }
        window_manifest = build_manifest(
            symbol=symbol,
            interval=interval,
            strategy_version=strategy_version,
            costs=costs,
            selection_criteria={"min_total_trades": 30},
            execution_contract=execution_contract,
            window_signatures=window_signature,
            runner_trusted=runner_trusted,
            split_config=split_config,
            candidate_grid=[candidate],
            windows=[bounds],
            data_signature=window_signature["test"],
            seed=7,
        )
        manifest_hash_value = window_manifest["manifest_hash"]
        if tamper_window_hash and idx == 0:
            manifest_hash_value = "tampered-window-hash"
        result = _window_result(window=bounds, candidate=candidate, manifest_hash_value=manifest_hash_value, trade_base=idx * 10)
        if trade_counts is not None:
            adjusted_test = _metrics(
                net_return_percent=net_return_percent,
                expectancy=expectancy,
                profit_factor=profit_factor,
                drawdown_max_percent=drawdown_max_percent,
                total_trades=trade_counts[idx],
                winning_trades=max(1, trade_counts[idx] - 3),
                losing_trades=2,
                breakeven_trades=max(0, trade_counts[idx] - max(1, trade_counts[idx] - 3) - 2),
            )
            result = replace(result, test_metrics=adjusted_test)
        window_results.append(result)
        window_signatures.append(window_signature)
    manifest = build_manifest(
        symbol=symbol,
        interval=interval,
        strategy_version=strategy_version,
        costs=costs,
        selection_criteria={"min_total_trades": 30},
        execution_contract=execution_contract,
        window_signatures={"windows": window_signatures},
        runner_trusted=runner_trusted,
        split_config=split_config,
        candidate_grid=[candidate],
        windows=windows_bounds,
        data_signature=build_data_signature(frame.iloc[:260], symbol=symbol, interval=interval),
        seed=7,
    )
    if manifest_override:
        manifest.update(manifest_override)

    summary = {
        "total_windows": len(window_results),
        "selected_windows": len(window_results),
        "total_trades": total_trades,
        "net_return_percent": net_return_percent,
        "net_pnl": "50",
        "drawdown_max_percent": drawdown_max_percent,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "payoff": "1.5",
        "win_rate": "66.6667",
        "trade_win_rate": "66.6667",
        "window_dispersion": 0.2,
        "worst_window": windows_bounds[0].as_dict() if windows_bounds else None,
        "proportion_lucrative_windows": float(100 if profitable_windows is None else profitable_windows / max(1, len(window_results)) * 100),
        "degradation_validation_test": validation_degradation,
        "validation_net_return_percent": "5",
        "selected_test_net_return_percent": net_return_percent,
        "selected_test_winning_trades": total_trades - 3,
        "selected_test_losing_trades": 2,
        "selected_test_gross_profit": "120",
        "selected_test_gross_loss": "80",
        "validation_winning_trades": total_trades - 3,
        "validation_losing_trades": 2,
        "validation_gross_profit": "130",
        "validation_gross_loss": "80",
        "manifest_hash": manifest["manifest_hash"],
        "runner_trusted": runner_trusted,
        "strategy_version": strategy_version,
        "symbol": symbol,
        "interval": interval,
        "mode": split_config.mode,
    }
    return WalkForwardResult(windows=tuple(window_results), summary=summary, manifest=manifest)


def _paper_snapshot(
    decision,
    *,
    session_id: str = "paper-session-1",
    trading_mode: str = "PAPER",
    data_fresh: bool = True,
    session_state: str = "RUNNING",
    session_started_utc: datetime | None = None,
    paper_capital_used: str = "1000",
    risk_per_trade_percent: str = "0.5",
    session_drawdown_percent: str = "4",
    current_loss_streak: int = 0,
    open_positions: int = 0,
    executed_trades: int = 4,
    observed_costs: dict[str, object] | None = None,
    internal_error: str | None = None,
    attempted_live: bool = False,
) -> PaperMonitoringSnapshot:
    return PaperMonitoringSnapshot(
        timestamp_utc=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
        decision_hash=decision.decision_hash,
        evidence_hash=decision.evidence_hash,
        strategy_version=decision.strategy_version,
        configuration=decision.frozen_selection.as_dict(),
        trading_mode=trading_mode,
        session_id=session_id,
        data_fresh=data_fresh,
        session_state=session_state,
        session_started_utc=session_started_utc or datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc),
        paper_capital_used=Decimal(paper_capital_used),
        risk_per_trade_percent=Decimal(risk_per_trade_percent),
        session_drawdown_percent=Decimal(session_drawdown_percent),
        current_loss_streak=current_loss_streak,
        open_positions=open_positions,
        executed_trades=executed_trades,
        observed_costs={
            "entry_fee_rate": "0.0004",
            "exit_fee_rate": "0.0004",
            "spread_bps": "5",
            "slippage_bps": "5",
        } if observed_costs is None else observed_costs,
        internal_error=internal_error,
        attempted_live=attempted_live,
    )


def _paper_session_contract(
    *,
    session_id: str = "paper-session-1",
    session_started_utc: datetime | None = None,
) -> PaperMonitoringSessionContract:
    return PaperMonitoringSessionContract(
        session_id=session_id,
        session_started_utc=session_started_utc or datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc),
    )


def _mutate_result_windows(
    result: WalkForwardResult,
    *,
    validation_metrics: list[SegmentMetrics] | None = None,
    test_metrics: list[SegmentMetrics] | None = None,
) -> WalkForwardResult:
    windows: list[WalkForwardWindowResult] = []
    for idx, window in enumerate(result.windows):
        evaluation = window.candidate_evaluations[0]
        mutated_validation = validation_metrics[idx] if validation_metrics is not None else evaluation.validation_metrics
        mutated_test = test_metrics[idx] if test_metrics is not None else window.test_metrics
        windows.append(
            replace(
                window,
                candidate_evaluations=(replace(evaluation, validation_metrics=mutated_validation),),
                test_metrics=mutated_test,
            )
        )
    return replace(result, windows=tuple(windows))


def _mutate_result_windows(
    result: WalkForwardResult,
    *,
    validation_metrics: list[SegmentMetrics] | None = None,
    test_metrics: list[SegmentMetrics] | None = None,
) -> WalkForwardResult:
    windows: list[WalkForwardWindowResult] = []
    for idx, window in enumerate(result.windows):
        evaluation = window.candidate_evaluations[0]
        mutated_validation = validation_metrics[idx] if validation_metrics is not None else evaluation.validation_metrics
        mutated_test = test_metrics[idx] if test_metrics is not None else window.test_metrics
        windows.append(
            replace(
                window,
                candidate_evaluations=(replace(evaluation, validation_metrics=mutated_validation),),
                test_metrics=mutated_test,
            )
        )
    return replace(result, windows=tuple(windows))


def test_evidence_vigente_aprova_apenas_paper_e_report_has_hash():
    result = _promotion_result()
    evidence = adapt_walk_forward_result(result)
    assert isinstance(evidence, PromotionEvidence)
    assert evidence.runner_trusted is True
    assert evidence.paper_only is True
    assert evidence.engine_class == "LeakFreeBacktestEngine"
    assert len(evidence.windows) == 3
    decision = evaluate_promotion(evidence)
    assert decision.status == PromotionStatus.APPROVED_FOR_MONITORED_PAPER
    assert decision.decision_hash
    report = build_promotion_report(decision)
    assert report["status"] == PromotionStatus.APPROVED_FOR_MONITORED_PAPER.value
    assert report["report_hash"]
    evidence.recalculated_metrics["profit_factor"] = 999
    assert evaluate_promotion(evidence).status == PromotionStatus.REJECTED
    forged = PromotionEvidence(
        manifest=dict(result.manifest),
        manifest_hash=result.manifest["manifest_hash"],
        summary=dict(result.summary),
        windows=evidence.windows,
        recalculated_metrics=dict(result.summary),
        symbol="BTCUSDT",
        interval="1h",
        strategy_version="v4_walk_forward",
        runner_trusted=True,
        paper_only=True,
        engine_class="LeakFreeBacktestEngine",
        execution_contract=dict(result.manifest["execution_contract"]),
        window_count_expected=len(result.manifest["windows"]),
        window_count_received=len(result.windows),
    )
    assert evaluate_promotion(forged).status == PromotionStatus.REJECTED


def test_runner_nao_confiavel_e_manifesto_adulterado_rejeitam():
    base_result = _promotion_result(runner_trusted=False)
    with pytest.raises(PromotionEvidenceError):
        adapt_walk_forward_result(base_result)

    tampered_manifest = _promotion_result(manifest_override={"runner_trusted": True})
    tampered_manifest.manifest["manifest_hash"] = "broken"
    with pytest.raises(PromotionEvidenceError):
        adapt_walk_forward_result(tampered_manifest)


def test_hash_divergente_config_diferente_e_mistura_de_manifestos_falham():
    base_result = _promotion_result()
    evidence = adapt_walk_forward_result(base_result)

    altered_policy = PromotionPolicy(min_oos_profit_factor=Decimal("1.20"))
    altered_decision = evaluate_promotion(evidence, altered_policy)
    assert altered_decision.policy_hash != evaluate_promotion(evidence).policy_hash
    assert altered_decision.decision_hash != evaluate_promotion(evidence).decision_hash

    different_contract = _promotion_result(entry_fee_rate="0.001")
    different_evidence = adapt_walk_forward_result(different_contract)
    assert different_evidence.evidence_hash != evidence.evidence_hash

    mixed = _promotion_result(tamper_window_hash=True)
    with pytest.raises(PromotionEvidenceError):
        adapt_walk_forward_result(mixed)


def test_limites_e_risco_rejeicao_in_sufficient_or_suspended():
    evidence = adapt_walk_forward_result(_promotion_result(window_count=2))
    decision = evaluate_promotion(evidence)
    assert decision.status == PromotionStatus.INSUFFICIENT_EVIDENCE

    too_few_trades = adapt_walk_forward_result(
        _mutate_result_windows(
            _promotion_result(),
            test_metrics=[
                _metrics(net_return_percent="4", expectancy="1", profit_factor="1.25", drawdown_max_percent="6", total_trades=8, winning_trades=5, losing_trades=2, breakeven_trades=1),
                _metrics(net_return_percent="4", expectancy="1", profit_factor="1.25", drawdown_max_percent="6", total_trades=8, winning_trades=5, losing_trades=2, breakeven_trades=1),
                _metrics(net_return_percent="4", expectancy="1", profit_factor="1.25", drawdown_max_percent="6", total_trades=8, winning_trades=5, losing_trades=2, breakeven_trades=1),
            ],
        )
    )
    decision = evaluate_promotion(too_few_trades)
    assert decision.status == PromotionStatus.INSUFFICIENT_EVIDENCE

    negative_return_result = _mutate_result_windows(
        _promotion_result(),
        test_metrics=[
            _metrics(net_return_percent="-1", expectancy="-0.5", profit_factor="0.8", drawdown_max_percent="6", total_trades=30, winning_trades=10, losing_trades=18, breakeven_trades=2),
            _metrics(net_return_percent="-1", expectancy="-0.5", profit_factor="0.8", drawdown_max_percent="6", total_trades=30, winning_trades=10, losing_trades=18, breakeven_trades=2),
            _metrics(net_return_percent="-1", expectancy="-0.5", profit_factor="0.8", drawdown_max_percent="6", total_trades=30, winning_trades=10, losing_trades=18, breakeven_trades=2),
        ],
    )
    negative_return = adapt_walk_forward_result(negative_return_result)
    assert evaluate_promotion(negative_return).status == PromotionStatus.REJECTED

    negative_expectancy = adapt_walk_forward_result(
        _mutate_result_windows(
                _promotion_result(),
                validation_metrics=[
                    _metrics(net_return_percent="5", expectancy="-0.5", profit_factor="1.25", drawdown_max_percent="5", total_trades=30, winning_trades=18, losing_trades=10, breakeven_trades=2),
                    _metrics(net_return_percent="5", expectancy="-0.5", profit_factor="1.25", drawdown_max_percent="5", total_trades=30, winning_trades=18, losing_trades=10, breakeven_trades=2),
                    _metrics(net_return_percent="5", expectancy="-0.5", profit_factor="1.25", drawdown_max_percent="5", total_trades=30, winning_trades=18, losing_trades=10, breakeven_trades=2),
                ],
                test_metrics=[
                    _metrics(net_return_percent="-1", expectancy="-0.5", profit_factor="1.25", drawdown_max_percent="6", total_trades=30, winning_trades=10, losing_trades=18, breakeven_trades=2),
                    _metrics(net_return_percent="-1", expectancy="-0.5", profit_factor="1.25", drawdown_max_percent="6", total_trades=30, winning_trades=10, losing_trades=18, breakeven_trades=2),
                    _metrics(net_return_percent="-1", expectancy="-0.5", profit_factor="1.25", drawdown_max_percent="6", total_trades=30, winning_trades=10, losing_trades=18, breakeven_trades=2),
                ],
            )
        )
    assert evaluate_promotion(negative_expectancy).status == PromotionStatus.REJECTED

    pf_none = adapt_walk_forward_result(
        _mutate_result_windows(
            _promotion_result(),
            test_metrics=[
                _metrics(net_return_percent="4", expectancy="1", profit_factor=None, drawdown_max_percent="6", total_trades=30, winning_trades=18, losing_trades=0, breakeven_trades=12, gross_loss="0"),
                _metrics(net_return_percent="4", expectancy="1", profit_factor=None, drawdown_max_percent="6", total_trades=30, winning_trades=18, losing_trades=0, breakeven_trades=12, gross_loss="0"),
                _metrics(net_return_percent="4", expectancy="1", profit_factor=None, drawdown_max_percent="6", total_trades=30, winning_trades=18, losing_trades=0, breakeven_trades=12, gross_loss="0"),
            ],
        )
    )
    assert evaluate_promotion(pf_none).status == PromotionStatus.REJECTED

    pf_low = adapt_walk_forward_result(
        _mutate_result_windows(
            _promotion_result(),
            test_metrics=[
                _metrics(net_return_percent="2", expectancy="0.5", profit_factor="1.00", drawdown_max_percent="6", total_trades=30, winning_trades=15, losing_trades=15, gross_profit="80", gross_loss="100"),
                _metrics(net_return_percent="2", expectancy="0.5", profit_factor="1.00", drawdown_max_percent="6", total_trades=30, winning_trades=15, losing_trades=15, gross_profit="80", gross_loss="100"),
                _metrics(net_return_percent="2", expectancy="0.5", profit_factor="1.00", drawdown_max_percent="6", total_trades=30, winning_trades=15, losing_trades=15, gross_profit="80", gross_loss="100"),
            ],
        )
    )
    assert evaluate_promotion(pf_low).status == PromotionStatus.REJECTED

    drawdown = adapt_walk_forward_result(
        _mutate_result_windows(
            _promotion_result(),
            test_metrics=[
                _metrics(net_return_percent="4", expectancy="1", profit_factor="1.25", drawdown_max_percent="20", total_trades=30, winning_trades=18, losing_trades=10, breakeven_trades=2),
                _metrics(net_return_percent="4", expectancy="1", profit_factor="1.25", drawdown_max_percent="20", total_trades=30, winning_trades=18, losing_trades=10, breakeven_trades=2),
                _metrics(net_return_percent="4", expectancy="1", profit_factor="1.25", drawdown_max_percent="20", total_trades=30, winning_trades=18, losing_trades=10, breakeven_trades=2),
            ],
        )
    )
    assert evaluate_promotion(drawdown).status == PromotionStatus.REJECTED


def test_pocas_janelas_lucrativas_degradacao_e_filtros_de_custos():
    few_profitable = adapt_walk_forward_result(
        _mutate_result_windows(
            _promotion_result(),
            test_metrics=[
                _metrics(net_return_percent="4", expectancy="1", profit_factor="1.25", drawdown_max_percent="6", total_trades=30, winning_trades=18, losing_trades=10, breakeven_trades=2),
                _metrics(net_return_percent="-2", expectancy="-0.5", profit_factor="0.9", drawdown_max_percent="8", total_trades=30, winning_trades=10, losing_trades=18, breakeven_trades=2),
                _metrics(net_return_percent="-3", expectancy="-0.7", profit_factor="0.8", drawdown_max_percent="9", total_trades=30, winning_trades=8, losing_trades=20, breakeven_trades=2),
            ],
        )
    )
    assert evaluate_promotion(few_profitable).status == PromotionStatus.REJECTED

    degraded = adapt_walk_forward_result(
        _mutate_result_windows(
            _promotion_result(),
            validation_metrics=[
                _metrics(net_return_percent="18", expectancy="4", profit_factor="2.0", drawdown_max_percent="4", total_trades=30, winning_trades=20, losing_trades=8, breakeven_trades=2),
                _metrics(net_return_percent="18", expectancy="4", profit_factor="2.0", drawdown_max_percent="4", total_trades=30, winning_trades=20, losing_trades=8, breakeven_trades=2),
                _metrics(net_return_percent="18", expectancy="4", profit_factor="2.0", drawdown_max_percent="4", total_trades=30, winning_trades=20, losing_trades=8, breakeven_trades=2),
            ],
            test_metrics=[
                _metrics(net_return_percent="1", expectancy="0.2", profit_factor="1.1", drawdown_max_percent="6", total_trades=30, winning_trades=15, losing_trades=14, breakeven_trades=1),
                _metrics(net_return_percent="1", expectancy="0.2", profit_factor="1.1", drawdown_max_percent="6", total_trades=30, winning_trades=15, losing_trades=14, breakeven_trades=1),
                _metrics(net_return_percent="1", expectancy="0.2", profit_factor="1.1", drawdown_max_percent="6", total_trades=30, winning_trades=15, losing_trades=14, breakeven_trades=1),
            ],
        )
    )
    assert evaluate_promotion(degraded).status == PromotionStatus.REJECTED

    missing_costs = adapt_walk_forward_result(_promotion_result(entry_fee_rate="0", exit_fee_rate="0", spread_bps="0", slippage_bps="0"))
    assert evaluate_promotion(missing_costs).status == PromotionStatus.REJECTED

    negative_costs = adapt_walk_forward_result(_promotion_result(entry_fee_rate="-0.1", exit_fee_rate="-0.1"))
    assert evaluate_promotion(negative_costs).status == PromotionStatus.REJECTED


def test_nan_infinity_missing_window_and_only_best_window_are_rejected():
    nan_result = _promotion_result()
    nan_result.summary["net_return_percent"] = float("nan")
    with pytest.raises(PromotionEvidenceError):
        adapt_walk_forward_result(nan_result)

    inf_result = _promotion_result()
    inf_result.summary["profit_factor"] = float("inf")
    with pytest.raises(PromotionEvidenceError):
        adapt_walk_forward_result(inf_result)

    removed_window_result = _promotion_result(window_count=3)
    removed_window_result.manifest["windows"] = removed_window_result.manifest["windows"][:2]
    with pytest.raises(PromotionEvidenceError):
        adapt_walk_forward_result(removed_window_result)

    only_best_window = adapt_walk_forward_result(_promotion_result(window_count=1))
    assert evaluate_promotion(only_best_window).status == PromotionStatus.INSUFFICIENT_EVIDENCE


def test_candidate_freeze_identity_and_duplicate_evaluations_block():
    base = _promotion_result()
    first_window = base.windows[0]
    different_candidate = CandidateConfig.from_mapping("alpha", {"risk": "high"})
    mutated_window = replace(
        first_window,
        selected_candidate=different_candidate,
        frozen_selection=replace(first_window.frozen_selection, candidate=different_candidate),
    )
    with pytest.raises(PromotionEvidenceError):
        adapt_walk_forward_result(replace(base, windows=(mutated_window,) + base.windows[1:]))

    duplicate_eval = replace(
        first_window,
        candidate_evaluations=(
            first_window.candidate_evaluations[0],
            replace(first_window.candidate_evaluations[0]),
        ),
    )
    with pytest.raises(PromotionEvidenceError):
        adapt_walk_forward_result(replace(base, windows=(duplicate_eval,) + base.windows[1:]))

    not_approved = replace(first_window, approved=False)
    with pytest.raises(PromotionEvidenceError):
        adapt_walk_forward_result(replace(base, windows=(not_approved,) + base.windows[1:]))


def test_decisao_deterministica_polity_hash_timestamp_and_live_attempt_fail():
    evidence = adapt_walk_forward_result(_promotion_result())
    policy = PromotionPolicy()
    decision_a = evaluate_promotion(evidence, policy)
    decision_b = evaluate_promotion(evidence, policy)
    assert decision_a.decision_hash == decision_b.decision_hash

    changed_policy = PromotionPolicy(min_oos_windows=4)
    assert decision_a.policy_hash != evaluate_promotion(evidence, changed_policy).policy_hash
    assert decision_a.decision_hash != evaluate_promotion(evidence, changed_policy).decision_hash

    frozen = decision_a.as_dict()
    assert frozen["timestamp_utc"].endswith("Z")
    with pytest.raises(PromotionPolicyError):
        MonitoredPaperLimits(live_trading_permanently_disabled=False)

    session_contract = _paper_session_contract()
    snapshot = _paper_snapshot(decision_a)
    with pytest.raises(PromotionDecisionError):
        evaluate_paper_monitoring(decision_a, snapshot)
    approved_monitoring = evaluate_paper_monitoring(decision_a, snapshot, session_contract=session_contract)
    assert approved_monitoring.status == PromotionStatus.APPROVED_FOR_MONITORED_PAPER
    assert approved_monitoring.decision_hash == decision_a.decision_hash
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, session_id="paper-session-1"), session_contract=session_contract).status == PromotionStatus.APPROVED_FOR_MONITORED_PAPER
    with pytest.raises(PromotionPolicyError):
        _paper_snapshot(decision_a, data_fresh="false")  # type: ignore[arg-type]
    with pytest.raises(PromotionPolicyError):
        _paper_snapshot(decision_a, data_fresh=0)  # type: ignore[arg-type]
    with pytest.raises(PromotionPolicyError):
        _paper_snapshot(decision_a, data_fresh=1)  # type: ignore[arg-type]
    with pytest.raises(PromotionPolicyError):
        _paper_snapshot(decision_a, attempted_live="false")  # type: ignore[arg-type]
    with pytest.raises(PromotionPolicyError):
        _paper_snapshot(decision_a, session_id=None)  # type: ignore[arg-type]
    with pytest.raises(PromotionPolicyError):
        _paper_snapshot(decision_a, session_id=1)  # type: ignore[arg-type]
    with pytest.raises(PromotionPolicyError):
        _paper_snapshot(decision_a, session_id=True)  # type: ignore[arg-type]
    with pytest.raises(PromotionPolicyError):
        _paper_snapshot(decision_a, session_id="")
    with pytest.raises(PromotionPolicyError):
        _paper_snapshot(decision_a, session_id="   ")
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, executed_trades=0, session_state="RUNNING"), session_contract=session_contract).status == PromotionStatus.APPROVED_FOR_MONITORED_PAPER
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, session_state="COMPLETED", executed_trades=30), session_contract=session_contract).status == PromotionStatus.APPROVED_FOR_MONITORED_PAPER
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, session_state="COMPLETED", executed_trades=2), session_contract=session_contract).status == PromotionStatus.PAPER_SUSPENDED
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, session_drawdown_percent="20"), session_contract=session_contract).status == PromotionStatus.PAPER_SUSPENDED
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, current_loss_streak=5), session_contract=session_contract).status == PromotionStatus.PAPER_SUSPENDED
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, open_positions=2), session_contract=session_contract).status == PromotionStatus.PAPER_SUSPENDED
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, data_fresh=False), session_contract=session_contract).status == PromotionStatus.PAPER_SUSPENDED
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, internal_error="boom"), session_contract=session_contract).status == PromotionStatus.PAPER_SUSPENDED
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, attempted_live=True), session_contract=session_contract).status == PromotionStatus.PAPER_SUSPENDED
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, observed_costs={"entry_fee_rate": "0.0004", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5"}), session_contract=session_contract).status == PromotionStatus.APPROVED_FOR_MONITORED_PAPER
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, observed_costs={"entry_fee_rate": "0.1", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5"}), session_contract=session_contract).status == PromotionStatus.PAPER_SUSPENDED
    with pytest.raises(PromotionPolicyError):
        _paper_snapshot(decision_a, observed_costs={"entry_fee_rate": "-0.1", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5"})
    with pytest.raises(PromotionPolicyError):
        _paper_snapshot(decision_a, observed_costs={"entry_fee_rate": "NaN", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5"})
    with pytest.raises(PromotionPolicyError):
        _paper_snapshot(decision_a, observed_costs={"entry_fee_rate": "Infinity", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5"})
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, observed_costs={}), session_contract=session_contract).status == PromotionStatus.PAPER_SUSPENDED
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, observed_costs={"entry_fee_rate": "0.0004", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5", "extra": "1"}), session_contract=session_contract).status == PromotionStatus.PAPER_SUSPENDED
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, paper_capital_used="20000"), session_contract=session_contract).status == PromotionStatus.PAPER_SUSPENDED
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, risk_per_trade_percent="2"), session_contract=session_contract).status == PromotionStatus.PAPER_SUSPENDED
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, session_started_utc=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc), executed_trades=4), session_contract=_paper_session_contract(session_started_utc=datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc))).status == PromotionStatus.APPROVED_FOR_MONITORED_PAPER
    with pytest.raises(PromotionPolicyError):
        PaperMonitoringSnapshot(
            timestamp_utc=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
            decision_hash=decision_a.decision_hash,
            evidence_hash=decision_a.evidence_hash,
            strategy_version=decision_a.strategy_version,
            configuration=decision_a.frozen_selection.as_dict(),
            trading_mode="PAPER",
            session_id="paper-session-1",
            session_started_utc=None,
            data_fresh=True,
            session_drawdown_percent=Decimal("4"),
            current_loss_streak=0,
            open_positions=0,
            executed_trades=0,
            observed_costs={"entry_fee_rate": "0.0004", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5"},
        )
    with pytest.raises(PromotionPolicyError):
        PaperMonitoringSnapshot(
            timestamp_utc=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
            decision_hash=decision_a.decision_hash,
            evidence_hash=decision_a.evidence_hash,
            strategy_version=decision_a.strategy_version,
            configuration=decision_a.frozen_selection.as_dict(),
            trading_mode="PAPER",
            session_id="paper-session-1",
            session_started_utc=datetime(2026, 7, 11, 12, 0),
            data_fresh=True,
            session_drawdown_percent=Decimal("4"),
            current_loss_streak=0,
            open_positions=0,
            executed_trades=0,
            observed_costs={"entry_fee_rate": "0.0004", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5"},
        )
    with pytest.raises(PromotionPolicyError):
        _paper_snapshot(decision_a, session_started_utc=datetime(2026, 7, 11, 13, 0, tzinfo=timezone.utc))
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, session_started_utc=datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc), data_fresh=True, executed_trades=4), session_contract=_paper_session_contract(session_started_utc=datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc))).status == PromotionStatus.APPROVED_FOR_MONITORED_PAPER
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, session_started_utc=datetime(2026, 7, 11, 0, 0, tzinfo=timezone.utc), data_fresh=True, executed_trades=4), session_contract=_paper_session_contract(session_started_utc=datetime(2026, 7, 11, 0, 0, tzinfo=timezone.utc))).status == PromotionStatus.PAPER_SUSPENDED
    with pytest.raises(PromotionDecisionError):
        evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, session_started_utc=datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)), session_contract=session_contract)
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, session_state="RUNNING", executed_trades=0), session_contract=session_contract).status == PromotionStatus.APPROVED_FOR_MONITORED_PAPER
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, session_state="COMPLETED", executed_trades=2), session_contract=session_contract).status == PromotionStatus.PAPER_SUSPENDED
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, executed_trades=200), session_contract=session_contract).status == PromotionStatus.PAPER_SUSPENDED
    assert evaluate_paper_monitoring(decision_a, _paper_snapshot(decision_a, session_started_utc=datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc), data_fresh=True, executed_trades=4), session_contract=_paper_session_contract(session_started_utc=datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc))).status == PromotionStatus.APPROVED_FOR_MONITORED_PAPER
    mutated_session = replace(snapshot, session_started_utc=datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc))
    assert mutated_session.snapshot_hash != snapshot.snapshot_hash
    with pytest.raises(PromotionDecisionError):
        evaluate_paper_monitoring(decision_a, mutated_session, session_contract=session_contract)
    changed_session_id = replace(snapshot, session_id="paper-session-2")
    with pytest.raises(PromotionDecisionError):
        evaluate_paper_monitoring(decision_a, changed_session_id, session_contract=session_contract)
    with pytest.raises(PromotionDecisionError):
        evaluate_paper_monitoring(decision_b.__class__(
            status=PromotionStatus.REJECTED,
            frozen_selection=decision_b.frozen_selection,
            strategy_version=decision_b.strategy_version,
            symbol=decision_b.symbol,
            interval=decision_b.interval,
            phase5_manifest=decision_b.phase5_manifest,
            evidence_hash=decision_b.evidence_hash,
            policy_hash=decision_b.policy_hash,
            decision_hash=decision_b.decision_hash,
            criteria_evaluated=decision_b.criteria_evaluated,
            reasons=decision_b.reasons,
            recalculated_metrics=decision_b.recalculated_metrics,
            paper_limits=decision_b.paper_limits,
            timestamp_utc=decision_b.timestamp_utc,
        ), snapshot, session_contract=session_contract)
    with pytest.raises(PromotionDecisionError):
        evaluate_paper_monitoring(decision_a, snapshot, MonitoredPaperLimits(paper_capital_max=Decimal("20000")), session_contract=session_contract)
    mutated_snapshot = _paper_snapshot(decision_a)
    mutated_snapshot.configuration["strategy_version"] = "tampered"
    with pytest.raises(PromotionDecisionError):
        evaluate_paper_monitoring(decision_a, mutated_snapshot, session_contract=session_contract)
    mutated_decision = evaluate_promotion(evidence)
    mutated_decision.paper_limits["max_positions"] = 99
    with pytest.raises(PromotionDecisionError):
        evaluate_paper_monitoring(mutated_decision, snapshot, session_contract=session_contract)


def test_paper_monitoring_limits_and_source_safety():
    limits = MonitoredPaperLimits()
    assert limits.live_trading_allowed is False
    assert limits.kill_switch_required is True
    assert limits.live_trading_permanently_disabled is True
    assert limits.as_dict()["paper_capital_max"] == Decimal("10000")

    promotion_source = Path("promotion")
    for path in promotion_source.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in ("requests", "create_order", "send_order", "subprocess", "telegram", "websocket", "APPROVED_FOR_LIVE"):
            assert token not in text
