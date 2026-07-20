from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import sqlite3
from pathlib import Path

import pytest

from backtesting import BacktestConfig, LeakFreeBacktestEngine
from domain import Candle, DataSource, Direction, Signal
from historical_experiments import (
    HistoricalExperimentConflictError,
    HistoricalExperimentIntegrityError,
    HistoricalExperimentValidationError,
    HistoricalStrategyFingerprint,
    build_historical_experiment_plan,
    fingerprint_strategy_callable,
    load_historical_experiment_report,
    run_historical_backtest_experiment,
    run_historical_walk_forward_experiment,
    save_historical_experiment_report,
    status_historical_experiment_report,
    verify_historical_experiment_report,
)
from historical_replay import historical_dataset_to_dataframe
from market_data import HistoricalDataset, HistoricalDatasetRequest, HistoricalProviderQualification, historical_content_hash
from market_data.historical_manifest import build_historical_manifest
from market_data.historical_store import save_historical_dataset
from promotion.adapters import adapt_historical_experiment_report, adapt_walk_forward_result
from promotion.errors import PromotionEvidenceError
from validation import CandidateConfig, SelectionCriteria, TrustedLeakFreeBacktestRunner, ValidationSplitConfig


ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)


def _historical_candle(open_time: datetime, *, base: int, symbol: str = "BTCUSDT", interval: str = "1h") -> Candle:
    return Candle.from_dict(
        {
            "open_time": open_time,
            "close_time": open_time + ONE_HOUR - ONE_MS,
            "open": str(base),
            "high": str(base + 5),
            "low": str(base - 5),
            "close": str(base + 2),
            "volume": str(1000 + base),
            "symbol": symbol,
            "interval": interval,
            "source": DataSource.BINANCE,
        }
    )


def _historical_dataset(tmp_path: Path, *, rows: int = 260, symbol: str = "BTCUSDT", interval: str = "1h") -> tuple[Path, HistoricalDataset]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles = tuple(_historical_candle(start + idx * ONE_HOUR, base=100 + idx, symbol=symbol, interval=interval) for idx in range(rows))
    request = HistoricalDatasetRequest(
        provider="binance.public.klines",
        provider_qualification=HistoricalProviderQualification.binance_public_spot(symbol=symbol, interval=interval),
        endpoint="https://api.binance.com/api/v3/klines",
        symbol=symbol,
        interval=interval,
        requested_start_utc=candles[0].open_time,
        requested_end_utc=candles[-1].close_time,
        page_size=1000,
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
    dataset = HistoricalDataset(manifest=manifest, candles=candles)
    path = tmp_path / "historical-dataset.json"
    save_historical_dataset(path, dataset)
    return path, dataset


def _backtest_strategy_v1(history, snapshot):
    candle = history[-1]
    entry = Decimal(str(candle.close))
    return Signal(
        symbol=candle.symbol,
        direction=Direction.COMPRA,
        entry=entry,
        stop_loss=entry - Decimal("5"),
        take_profit=entry + Decimal("10"),
        rr=Decimal("2"),
        timestamp=candle.close_time,
        source=DataSource.PAPER,
        score=Decimal("1"),
        regime="BULL",
        volume_status="ALTO",
        reason="historical experiment",
        strategy_version="v4_walk_forward",
    )


def _backtest_strategy_v2(history, snapshot):
    candle = history[-1]
    entry = Decimal(str(candle.close))
    return Signal(
        symbol=candle.symbol,
        direction=Direction.COMPRA,
        entry=entry,
        stop_loss=entry - Decimal("8"),
        take_profit=entry + Decimal("12"),
        rr=Decimal("1.5"),
        timestamp=candle.close_time,
        source=DataSource.PAPER,
        score=Decimal("1"),
        regime="BULL",
        volume_status="ALTO",
        reason="historical experiment v2",
        strategy_version="v4_walk_forward",
    )


def _walk_forward_strategy_factory_v1(candidate):
    return _backtest_strategy_v1


def _walk_forward_strategy_factory_v2(candidate):
    return _backtest_strategy_v2


def _engine(symbol: str = "BTCUSDT", interval: str = "1h") -> LeakFreeBacktestEngine:
    return LeakFreeBacktestEngine(
        BacktestConfig(
            initial_capital=Decimal("10000"),
            risk_percent=Decimal("1"),
            entry_fee_rate=Decimal("0"),
            exit_fee_rate=Decimal("0"),
            spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            leverage=Decimal("1"),
            symbol=symbol,
            interval=interval,
            strategy_version="v4_walk_forward",
        )
    )


def _runner(symbol: str = "BTCUSDT", interval: str = "1h", strategy_factory=_walk_forward_strategy_factory_v1) -> TrustedLeakFreeBacktestRunner:
    return TrustedLeakFreeBacktestRunner(
        engine_factory=lambda: _engine(symbol=symbol, interval=interval),
        strategy_factory=strategy_factory,
        symbol=symbol,
        interval=interval,
    )


def _selection_criteria() -> SelectionCriteria:
    return SelectionCriteria(
        min_total_trades=0,
        min_net_return=Decimal("-100000"),
        max_drawdown_percent=Decimal("100000"),
        min_expectancy=Decimal("-100000"),
        require_defined_profit_factor=False,
        min_profit_factor=Decimal("0"),
    )


def _split_config() -> ValidationSplitConfig:
    return ValidationSplitConfig(
        mode="rolling",
        train_bars=120,
        validation_bars=40,
        test_bars=40,
        warmup_bars=20,
        purge_bars=5,
        embargo_bars=5,
        step_bars=40,
    )


def _candidate(name: str = "alpha", risk: str = "low") -> CandidateConfig:
    return CandidateConfig.from_mapping(name, {"risk": risk})


def test_historical_experiment_plan_is_deterministic_and_hash_changes_with_inputs(tmp_path):
    path, dataset = _historical_dataset(tmp_path, rows=260)
    runner = _runner()
    contract = runner.execution_contract()
    base_plan = build_historical_experiment_plan(
        path,
        mode="walk_forward",
        strategy_callable=_walk_forward_strategy_factory_v1,
        strategy_version=contract["strategy_version"],
        execution_contract=contract,
        costs={
            "entry_fee_rate": contract["entry_fee_rate"],
            "exit_fee_rate": contract["exit_fee_rate"],
            "spread_bps": contract["spread_bps"],
            "slippage_bps": contract["slippage_bps"],
            "leverage": contract["leverage"],
            "intrabar_policy": contract["intrabar_policy"],
            "gap_policy": contract["gap_policy"],
        },
        candidate_grid=[_candidate()],
        selection_criteria=_selection_criteria(),
        split_config=_split_config(),
        seed=7,
        intrabar_policy=contract["intrabar_policy"],
        gap_policy=contract["gap_policy"],
    )
    same_plan = build_historical_experiment_plan(
        dataset,
        mode="walk_forward",
        strategy_callable=_walk_forward_strategy_factory_v1,
        strategy_version=contract["strategy_version"],
        execution_contract=contract,
        costs={
            "entry_fee_rate": contract["entry_fee_rate"],
            "exit_fee_rate": contract["exit_fee_rate"],
            "spread_bps": contract["spread_bps"],
            "slippage_bps": contract["slippage_bps"],
            "leverage": contract["leverage"],
            "intrabar_policy": contract["intrabar_policy"],
            "gap_policy": contract["gap_policy"],
        },
        candidate_grid=[_candidate()],
        selection_criteria=_selection_criteria(),
        split_config=_split_config(),
        seed=7,
        intrabar_policy=contract["intrabar_policy"],
        gap_policy=contract["gap_policy"],
    )

    assert base_plan.plan_hash == same_plan.plan_hash
    assert base_plan.historical_provenance == same_plan.historical_provenance
    assert base_plan.classification == "historical_research_only"
    assert base_plan.operational_evidence is False
    assert base_plan.paper_promotion_eligible is False
    assert base_plan.historical_provenance.classification == "historical_research_only"

    altered_dataset = list(dataset.candles)
    first = altered_dataset[0]
    altered_dataset[0] = Candle.from_dict(
        {
            "open_time": first.open_time,
            "close_time": first.close_time,
            "open": "201",
            "high": "205",
            "low": "195",
            "close": "202",
            "volume": first.volume,
            "symbol": first.symbol,
            "interval": first.interval,
            "source": first.source,
        }
    )
    altered_manifest = build_historical_manifest(
        request=HistoricalDatasetRequest(
            provider=dataset.manifest.provider,
            provider_qualification=dataset.manifest.provider_qualification,
            endpoint=dataset.manifest.endpoint,
            symbol=dataset.manifest.symbol,
            interval=dataset.manifest.interval,
            requested_start_utc=dataset.manifest.requested_start_utc,
            requested_end_utc=dataset.manifest.requested_end_utc,
            page_size=dataset.manifest.page_size,
            closed_candles_only=True,
        ),
        effective_start_utc=dataset.manifest.effective_start_utc,
        effective_end_utc=dataset.manifest.effective_end_utc,
        created_at_utc=dataset.manifest.created_at_utc,
        candle_count=len(altered_dataset),
        page_count=dataset.manifest.page_count,
        gap_count=dataset.manifest.gap_count,
        duplicate_count=dataset.manifest.duplicate_count,
        content_hash=historical_content_hash(tuple(altered_dataset)),
    )
    altered_path = tmp_path / "historical-altered.json"
    save_historical_dataset(altered_path, HistoricalDataset(manifest=altered_manifest, candles=tuple(altered_dataset)))

    dataset_plan = build_historical_experiment_plan(
        altered_path,
        mode="walk_forward",
        strategy_callable=_walk_forward_strategy_factory_v1,
        strategy_version=contract["strategy_version"],
        execution_contract=contract,
        costs={
            "entry_fee_rate": contract["entry_fee_rate"],
            "exit_fee_rate": contract["exit_fee_rate"],
            "spread_bps": contract["spread_bps"],
            "slippage_bps": contract["slippage_bps"],
            "leverage": contract["leverage"],
            "intrabar_policy": contract["intrabar_policy"],
            "gap_policy": contract["gap_policy"],
        },
        candidate_grid=[_candidate()],
        selection_criteria=_selection_criteria(),
        split_config=_split_config(),
        seed=7,
        intrabar_policy=contract["intrabar_policy"],
        gap_policy=contract["gap_policy"],
    )
    strategy_plan = build_historical_experiment_plan(
        path,
        mode="walk_forward",
        strategy_callable=_walk_forward_strategy_factory_v2,
        strategy_version=contract["strategy_version"],
        execution_contract=contract,
        costs={
            "entry_fee_rate": contract["entry_fee_rate"],
            "exit_fee_rate": contract["exit_fee_rate"],
            "spread_bps": contract["spread_bps"],
            "slippage_bps": contract["slippage_bps"],
            "leverage": contract["leverage"],
            "intrabar_policy": contract["intrabar_policy"],
            "gap_policy": contract["gap_policy"],
        },
        candidate_grid=[_candidate()],
        selection_criteria=_selection_criteria(),
        split_config=_split_config(),
        seed=7,
        intrabar_policy=contract["intrabar_policy"],
        gap_policy=contract["gap_policy"],
    )
    costs_plan = build_historical_experiment_plan(
        path,
        mode="walk_forward",
        strategy_callable=_walk_forward_strategy_factory_v1,
        strategy_version=contract["strategy_version"],
        execution_contract=contract,
        costs={
            "entry_fee_rate": contract["entry_fee_rate"],
            "exit_fee_rate": contract["exit_fee_rate"],
            "spread_bps": "6",
            "slippage_bps": contract["slippage_bps"],
            "leverage": contract["leverage"],
            "intrabar_policy": contract["intrabar_policy"],
            "gap_policy": contract["gap_policy"],
        },
        candidate_grid=[_candidate()],
        selection_criteria=_selection_criteria(),
        split_config=_split_config(),
        seed=7,
        intrabar_policy=contract["intrabar_policy"],
        gap_policy=contract["gap_policy"],
    )
    seed_plan = build_historical_experiment_plan(
        path,
        mode="walk_forward",
        strategy_callable=_walk_forward_strategy_factory_v1,
        strategy_version=contract["strategy_version"],
        execution_contract=contract,
        costs={
            "entry_fee_rate": contract["entry_fee_rate"],
            "exit_fee_rate": contract["exit_fee_rate"],
            "spread_bps": contract["spread_bps"],
            "slippage_bps": contract["slippage_bps"],
            "leverage": contract["leverage"],
            "intrabar_policy": contract["intrabar_policy"],
            "gap_policy": contract["gap_policy"],
        },
        candidate_grid=[_candidate()],
        selection_criteria=_selection_criteria(),
        split_config=_split_config(),
        seed=8,
        intrabar_policy=contract["intrabar_policy"],
        gap_policy=contract["gap_policy"],
    )
    candidate_plan = build_historical_experiment_plan(
        path,
        mode="walk_forward",
        strategy_callable=_walk_forward_strategy_factory_v1,
        strategy_version=contract["strategy_version"],
        execution_contract=contract,
        costs={
            "entry_fee_rate": contract["entry_fee_rate"],
            "exit_fee_rate": contract["exit_fee_rate"],
            "spread_bps": contract["spread_bps"],
            "slippage_bps": contract["slippage_bps"],
            "leverage": contract["leverage"],
            "intrabar_policy": contract["intrabar_policy"],
            "gap_policy": contract["gap_policy"],
        },
        candidate_grid=[_candidate("beta", "medium")],
        selection_criteria=_selection_criteria(),
        split_config=_split_config(),
        seed=7,
        intrabar_policy=contract["intrabar_policy"],
        gap_policy=contract["gap_policy"],
    )
    split_plan = build_historical_experiment_plan(
        path,
        mode="walk_forward",
        strategy_callable=_walk_forward_strategy_factory_v1,
        strategy_version=contract["strategy_version"],
        execution_contract=contract,
        costs={
            "entry_fee_rate": contract["entry_fee_rate"],
            "exit_fee_rate": contract["exit_fee_rate"],
            "spread_bps": contract["spread_bps"],
            "slippage_bps": contract["slippage_bps"],
            "leverage": contract["leverage"],
            "intrabar_policy": contract["intrabar_policy"],
            "gap_policy": contract["gap_policy"],
        },
        candidate_grid=[_candidate()],
        selection_criteria=_selection_criteria(),
        split_config=replace(_split_config(), warmup_bars=25),
        seed=7,
        intrabar_policy=contract["intrabar_policy"],
        gap_policy=contract["gap_policy"],
    )
    criteria_plan = build_historical_experiment_plan(
        path,
        mode="walk_forward",
        strategy_callable=_walk_forward_strategy_factory_v1,
        strategy_version=contract["strategy_version"],
        execution_contract=contract,
        costs={
            "entry_fee_rate": contract["entry_fee_rate"],
            "exit_fee_rate": contract["exit_fee_rate"],
            "spread_bps": contract["spread_bps"],
            "slippage_bps": contract["slippage_bps"],
            "leverage": contract["leverage"],
            "intrabar_policy": contract["intrabar_policy"],
            "gap_policy": contract["gap_policy"],
        },
        candidate_grid=[_candidate()],
        selection_criteria=replace(_selection_criteria(), min_profit_factor=Decimal("1.2")),
        split_config=_split_config(),
        seed=7,
        intrabar_policy=contract["intrabar_policy"],
        gap_policy=contract["gap_policy"],
    )

    assert base_plan.plan_hash != dataset_plan.plan_hash
    assert base_plan.plan_hash != strategy_plan.plan_hash
    assert base_plan.plan_hash != costs_plan.plan_hash
    assert base_plan.plan_hash != seed_plan.plan_hash
    assert base_plan.plan_hash != candidate_plan.plan_hash
    assert base_plan.plan_hash != split_plan.plan_hash
    assert base_plan.plan_hash != criteria_plan.plan_hash


def test_historical_strategy_fingerprint_rejects_lambda_and_closure():
    with pytest.raises(HistoricalExperimentValidationError, match="lambda strategies are not allowed"):
        fingerprint_strategy_callable(lambda history, snapshot: None)

    def outer():
        token = "secret"

        def inner(history, snapshot):
            return token

        return inner

    with pytest.raises(HistoricalExperimentValidationError, match="nested or ambiguous strategy callables are not allowed|strategy closures are not allowed"):
        fingerprint_strategy_callable(outer())

    fingerprint = fingerprint_strategy_callable(_backtest_strategy_v1)
    assert isinstance(fingerprint, HistoricalStrategyFingerprint)
    assert fingerprint.source_hash


def test_historical_experiment_reports_are_not_promotion_evidence(tmp_path):
    path, _ = _historical_dataset(tmp_path, rows=260)
    runner = _runner(strategy_factory=_walk_forward_strategy_factory_v1)
    walk_forward_report = run_historical_walk_forward_experiment(
        path,
        runner=runner,
        candidate_grid=[_candidate()],
        split_config=_split_config(),
        selection_criteria=_selection_criteria(),
        strategy_version="v4_walk_forward",
        costs={"entry_fee_rate": "0", "exit_fee_rate": "0", "spread_bps": "0", "slippage_bps": "0", "leverage": "1"},
        seed=11,
    )
    backtest_report = run_historical_backtest_experiment(
        path,
        engine=_engine(),
        strategy_callable=_backtest_strategy_v1,
    )

    with pytest.raises(PromotionEvidenceError):
        adapt_historical_experiment_report(walk_forward_report)
    with pytest.raises(PromotionEvidenceError):
        adapt_historical_experiment_report(backtest_report)
    with pytest.raises(PromotionEvidenceError):
        adapt_walk_forward_result(walk_forward_report.replay.result)


def test_historical_experiment_report_persistence_is_atomic_write_once_and_idempotent(tmp_path):
    path, _ = _historical_dataset(tmp_path, rows=260)
    runner = _runner(strategy_factory=_walk_forward_strategy_factory_v1)
    report = run_historical_walk_forward_experiment(
        path,
        runner=runner,
        candidate_grid=[_candidate()],
        split_config=_split_config(),
        selection_criteria=_selection_criteria(),
        strategy_version="v4_walk_forward",
        costs={"entry_fee_rate": "0", "exit_fee_rate": "0", "spread_bps": "0", "slippage_bps": "0", "leverage": "1"},
        seed=13,
    )

    output = tmp_path / "experiment-report.json"
    saved = save_historical_experiment_report(output, report)
    assert output.exists()
    assert saved.report_hash == report.report_hash
    assert saved.plan.plan_hash == report.plan.plan_hash
    assert not any(output.parent.glob(f".{output.name}.*.tmp"))
    mtime_before = output.stat().st_mtime_ns
    loaded = load_historical_experiment_report(output)
    assert loaded.report_hash == report.report_hash
    assert loaded.plan.plan_hash == report.plan.plan_hash
    verify = verify_historical_experiment_report(output)
    assert verify["verified"] is True
    assert verify["report_hash"] == report.report_hash
    status = status_historical_experiment_report(output)
    assert status["exists"] is True
    assert status["classification"] == "historical_research_only"

    saved_again = save_historical_experiment_report(output, report)
    assert saved_again.report_hash == report.report_hash
    assert output.stat().st_mtime_ns == mtime_before

    divergent = run_historical_walk_forward_experiment(
        path,
        runner=_runner(strategy_factory=_walk_forward_strategy_factory_v2),
        candidate_grid=[_candidate()],
        split_config=_split_config(),
        selection_criteria=_selection_criteria(),
        strategy_version="v4_walk_forward",
        costs={"entry_fee_rate": "0", "exit_fee_rate": "0", "spread_bps": "0", "slippage_bps": "0", "leverage": "1"},
        seed=13,
    )
    with pytest.raises(HistoricalExperimentConflictError):
        save_historical_experiment_report(output, divergent)

    tampered = json.loads(output.read_text(encoding="utf-8"))
    tampered["plan"]["strategy_version"] = "tampered"
    output.write_text(json.dumps(tampered, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    with pytest.raises(HistoricalExperimentIntegrityError):
        load_historical_experiment_report(output)


def test_historical_experiment_rejects_dataframe_and_isolated_from_network_and_sqlite(tmp_path, monkeypatch):
    path, dataset = _historical_dataset(tmp_path, rows=260)
    frame = historical_dataset_to_dataframe(dataset)
    runner = _runner(strategy_factory=_walk_forward_strategy_factory_v1)

    with pytest.raises(HistoricalExperimentValidationError):
        build_historical_experiment_plan(
            frame,
            mode="walk_forward",
            strategy_callable=_walk_forward_strategy_factory_v1,
            strategy_version="v4_walk_forward",
            execution_contract=runner.execution_contract(),
            costs={"entry_fee_rate": "0", "exit_fee_rate": "0", "spread_bps": "0", "slippage_bps": "0", "leverage": "1"},
            candidate_grid=[_candidate()],
            selection_criteria=_selection_criteria(),
            split_config=_split_config(),
            seed=1,
            intrabar_policy="STOP_FIRST",
            gap_policy="OPEN_PRICE",
        )

    def _boom(*args, **kwargs):
        raise AssertionError("unexpected external or sqlite access")

    monkeypatch.setattr(sqlite3, "connect", _boom)
    try:
        import requests  # type: ignore
    except Exception:  # pragma: no cover - dependency guard
        requests = None
    if requests is not None:
        monkeypatch.setattr(requests, "get", _boom, raising=False)
    try:
        import httpx  # type: ignore
    except Exception:  # pragma: no cover - dependency guard
        httpx = None
    if httpx is not None:
        monkeypatch.setattr(httpx, "Client", _boom, raising=False)

    backtest_report = run_historical_backtest_experiment(
        path,
        engine=_engine(),
        strategy_callable=_backtest_strategy_v1,
    )
    assert backtest_report.classification == "historical_research_only"
    assert backtest_report.operational_evidence is False
    assert backtest_report.paper_promotion_eligible is False


def test_historical_experiment_walk_forward_result_remains_not_promotion_evidence_and_plan_not_influenced_by_result(tmp_path):
    path, _ = _historical_dataset(tmp_path, rows=260)
    runner = _runner(strategy_factory=_walk_forward_strategy_factory_v1)
    report = run_historical_walk_forward_experiment(
        path,
        runner=runner,
        candidate_grid=[_candidate()],
        split_config=_split_config(),
        selection_criteria=_selection_criteria(),
        strategy_version="v4_walk_forward",
        costs={"entry_fee_rate": "0", "exit_fee_rate": "0", "spread_bps": "0", "slippage_bps": "0", "leverage": "1"},
        seed=15,
    )
    direct_plan = build_historical_experiment_plan(
        path,
        mode="walk_forward",
        strategy_callable=_walk_forward_strategy_factory_v1,
        strategy_version="v4_walk_forward",
        execution_contract=runner.execution_contract(),
        costs={"entry_fee_rate": "0", "exit_fee_rate": "0", "spread_bps": "0", "slippage_bps": "0", "leverage": "1"},
        candidate_grid=[_candidate()],
        selection_criteria=_selection_criteria(),
        split_config=_split_config(),
        seed=15,
        intrabar_policy=runner.execution_contract()["intrabar_policy"],
        gap_policy=runner.execution_contract()["gap_policy"],
    )

    assert report.plan.plan_hash == direct_plan.plan_hash
    assert report.plan.classification == "historical_research_only"
    assert report.plan.operational_evidence is False
    assert report.plan.paper_promotion_eligible is False
    assert report.replay.result.manifest["historical_provenance"]["classification"] == "historical_research_only"
    assert report.replay.result.manifest["historical_provenance"]["operational_evidence"] is False
    assert report.replay.result.manifest["historical_provenance"]["paper_promotion_eligible"] is False
    with pytest.raises(PromotionEvidenceError):
        adapt_walk_forward_result(report.replay.result)
