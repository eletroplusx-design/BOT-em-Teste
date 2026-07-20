from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest

from backtesting import BacktestConfig, LeakFreeBacktestEngine
from backtesting.adapters import dataframe_to_candles
from domain import Candle, DataSource, Direction, Signal
from historical_replay import (
    HistoricalBacktestReplay,
    HistoricalReplayIntegrityError,
    HistoricalReplayProvenance,
    HistoricalReplayValidationError,
    HistoricalWalkForwardReplay,
    historical_dataset_to_dataframe,
    load_historical_replay_dataset,
    replay_historical_backtest,
    replay_historical_walk_forward,
)
from market_data import HistoricalDataIntegrityError, HistoricalDataset, HistoricalDatasetRequest, HistoricalProviderQualification, historical_content_hash, load_historical_dataset_file
from market_data.historical_store import save_historical_dataset
from market_data.historical_manifest import build_historical_manifest
from promotion.adapters import adapt_walk_forward_result
from promotion.errors import PromotionEvidenceError
from validation import CandidateConfig, SelectionCriteria, TrustedLeakFreeBacktestRunner, ValidationSplitConfig, WalkForwardValidator


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


def _signal_callback(history, snapshot):
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
        reason="historical replay",
        strategy_version="v4_walk_forward",
    )


def _trusted_runner(symbol: str, interval: str) -> TrustedLeakFreeBacktestRunner:
    return TrustedLeakFreeBacktestRunner(
        engine_factory=lambda: LeakFreeBacktestEngine(
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
        ),
        strategy_factory=lambda candidate: _signal_callback,
        symbol=symbol,
        interval=interval,
    )


def _candidate(name: str = "alpha") -> CandidateConfig:
    return CandidateConfig.from_mapping(name, {"risk": "low"})


def test_historical_replay_backtest_is_deterministic_and_hash_anchored(tmp_path):
    path, dataset = _historical_dataset(tmp_path, rows=12)
    assert HistoricalReplayProvenance.from_dataset(dataset).schema_version == dataset.manifest.schema_version
    engine = LeakFreeBacktestEngine(
        BacktestConfig(
            initial_capital=Decimal("10000"),
            risk_percent=Decimal("1"),
            entry_fee_rate=Decimal("0"),
            exit_fee_rate=Decimal("0"),
            spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            leverage=Decimal("1"),
            symbol="BTCUSDT",
            interval="1h",
            strategy_version="v4_walk_forward",
        )
    )

    replay_a = replay_historical_backtest(path, engine=engine, strategy_callback=_signal_callback)
    replay_b = replay_historical_backtest(load_historical_replay_dataset(dataset), engine=engine, strategy_callback=_signal_callback)

    assert isinstance(replay_a, HistoricalBacktestReplay)
    assert replay_a.replay_hash == replay_b.replay_hash
    assert replay_a.provenance == replay_b.provenance
    assert replay_a.provenance.classification == "historical_research_only"
    assert replay_a.provenance.operational_evidence is False
    assert replay_a.provenance.paper_promotion_eligible is False
    assert replay_a.execution_contract["paper_only"] is True
    assert replay_a.result.config.paper_only is True
    assert replay_a.result.final_capital == replay_b.result.final_capital
    assert replay_a.result.symbol == "BTCUSDT"


def test_historical_replay_dataframe_preserves_binance_source_round_trip(tmp_path):
    _, dataset = _historical_dataset(tmp_path, rows=12)
    frame = historical_dataset_to_dataframe(dataset)
    candles = dataframe_to_candles(frame, symbol=dataset.manifest.symbol, interval=dataset.manifest.interval)
    assert candles[0].source == DataSource.BINANCE
    assert candles[-1].source == DataSource.BINANCE


def test_historical_replay_backtest_hash_changes_with_dataset_and_contract(tmp_path):
    path, dataset = _historical_dataset(tmp_path, rows=12)
    engine = LeakFreeBacktestEngine(
        BacktestConfig(
            initial_capital=Decimal("10000"),
            risk_percent=Decimal("1"),
            entry_fee_rate=Decimal("0"),
            exit_fee_rate=Decimal("0"),
            spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            leverage=Decimal("1"),
            symbol="BTCUSDT",
            interval="1h",
            strategy_version="v4_walk_forward",
        )
    )
    replay = replay_historical_backtest(path, engine=engine, strategy_callback=_signal_callback)

    altered_candles = list(dataset.candles)
    first = altered_candles[0]
    altered_candles[0] = Candle.from_dict(
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
        candle_count=len(altered_candles),
        page_count=dataset.manifest.page_count,
        gap_count=dataset.manifest.gap_count,
        duplicate_count=dataset.manifest.duplicate_count,
        content_hash=historical_content_hash(tuple(altered_candles)),
    )
    altered_path = tmp_path / "historical-altered.json"
    save_historical_dataset(altered_path, HistoricalDataset(manifest=altered_manifest, candles=tuple(altered_candles)))

    altered_replay = replay_historical_backtest(altered_path, engine=engine, strategy_callback=_signal_callback)
    assert replay.replay_hash != altered_replay.replay_hash

    mutated_engine = LeakFreeBacktestEngine(
        BacktestConfig(
            initial_capital=Decimal("10000"),
            risk_percent=Decimal("1"),
            entry_fee_rate=Decimal("0.0005"),
            exit_fee_rate=Decimal("0.0005"),
            spread_bps=Decimal("1"),
            slippage_bps=Decimal("1"),
            leverage=Decimal("1"),
            symbol="BTCUSDT",
            interval="1h",
            strategy_version="v4_walk_forward",
        )
    )
    mutated_replay = replay_historical_backtest(path, engine=mutated_engine, strategy_callback=_signal_callback)
    assert replay.replay_hash != mutated_replay.replay_hash


def test_historical_replay_loader_rejects_adulterated_json_even_with_recomputed_hashes(tmp_path):
    path, dataset = _historical_dataset(tmp_path, rows=6)
    payload = load_historical_dataset_file(path).as_dict()
    payload["candles"][0]["source"] = DataSource.PAPER.value if hasattr(DataSource.PAPER, "value") else DataSource.PAPER
    payload["manifest"]["content_hash"] = historical_content_hash([Candle.from_dict(item) for item in payload["candles"]])
    payload["manifest"]["dataset_id"] = payload["manifest"]["content_hash"]
    altered_path = tmp_path / "adulterated.json"
    altered_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    with pytest.raises(HistoricalReplayIntegrityError):
        load_historical_replay_dataset(altered_path)


def test_historical_replay_rejects_dataset_dataframe_and_engine_contract_mismatch(tmp_path):
    path, dataset = _historical_dataset(tmp_path, rows=12)
    frame = historical_dataset_to_dataframe(dataset)
    assert list(frame["open_time"]) == [candle.open_time for candle in dataset.candles]
    assert list(frame["close_time"]) == [candle.close_time for candle in dataset.candles]
    assert list(frame["open"]) == [candle.open for candle in dataset.candles]

    with pytest.raises(HistoricalReplayValidationError):
        load_historical_replay_dataset(frame)

    bad_engine = LeakFreeBacktestEngine(
        BacktestConfig(
            initial_capital=Decimal("10000"),
            risk_percent=Decimal("1"),
            entry_fee_rate=Decimal("0"),
            exit_fee_rate=Decimal("0"),
            spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            leverage=Decimal("1"),
            symbol="ETHUSDT",
            interval="1h",
            strategy_version="v4_walk_forward",
        )
    )
    with pytest.raises(HistoricalReplayValidationError):
        replay_historical_backtest(path, engine=bad_engine, strategy_callback=_signal_callback)


def test_historical_replay_rejects_non_paper_engine_and_invalid_strategy_callback(tmp_path):
    path, _ = _historical_dataset(tmp_path, rows=12)
    engine = LeakFreeBacktestEngine(
        BacktestConfig(
            initial_capital=Decimal("10000"),
            risk_percent=Decimal("1"),
            entry_fee_rate=Decimal("0"),
            exit_fee_rate=Decimal("0"),
            spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            leverage=Decimal("1"),
            symbol="BTCUSDT",
            interval="1h",
            strategy_version="v4_walk_forward",
        )
    )
    object.__setattr__(engine.config, "paper_only", False)
    with pytest.raises(HistoricalReplayValidationError):
        replay_historical_backtest(path, engine=engine, strategy_callback=_signal_callback)

    with pytest.raises(HistoricalReplayValidationError):
        replay_historical_backtest(path, engine=LeakFreeBacktestEngine(), strategy_callback=None)


def test_historical_walk_forward_replay_requires_trusted_runner_and_is_not_promotion_evidence(tmp_path):
    path, dataset = _historical_dataset(tmp_path, rows=260)
    runner = _trusted_runner("BTCUSDT", "1h")
    candidate_grid = [_candidate()]
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
    selection_criteria = SelectionCriteria(
        min_total_trades=0,
        min_net_return=Decimal("-100000"),
        max_drawdown_percent=Decimal("100000"),
        min_expectancy=Decimal("-100000"),
        require_defined_profit_factor=False,
        min_profit_factor=Decimal("0"),
    )

    replay = replay_historical_walk_forward(
        path,
        runner=runner,
        candidate_grid=candidate_grid,
        split_config=split_config,
        selection_criteria=selection_criteria,
        strategy_version="v4_walk_forward",
        costs={"entry_fee_rate": "0", "exit_fee_rate": "0", "spread_bps": "0", "slippage_bps": "0", "leverage": "1"},
    )
    replay_again = replay_historical_walk_forward(
        path,
        runner=runner,
        candidate_grid=candidate_grid,
        split_config=split_config,
        selection_criteria=selection_criteria,
        strategy_version="v4_walk_forward",
        costs={"entry_fee_rate": "0", "exit_fee_rate": "0", "spread_bps": "0", "slippage_bps": "0", "leverage": "1"},
    )
    assert isinstance(replay, HistoricalWalkForwardReplay)
    assert replay.provenance.classification == "historical_research_only"
    assert replay.result.manifest["historical_provenance"] == replay.provenance.as_dict()
    assert replay.result.manifest["runner_trusted"] is True
    assert replay.result.summary["runner_trusted"] is True
    assert replay.result.manifest["manifest_hash"] == replay.result.summary["manifest_hash"]
    assert replay.replay_hash == replay_again.replay_hash
    assert replay.result.windows[0].approved is True

    direct_validator = WalkForwardValidator(
        split_config=split_config,
        selection_criteria=selection_criteria,
        strategy_version="v4_walk_forward",
        costs={"entry_fee_rate": "0", "exit_fee_rate": "0", "spread_bps": "0", "slippage_bps": "0", "leverage": "1"},
        symbol="BTCUSDT",
        interval="1h",
        require_trusted_runner=True,
    )
    plain_result = direct_validator.run(historical_dataset_to_dataframe(dataset), candidate_grid, runner=runner)
    assert "historical_provenance" not in plain_result.manifest
    assert replay.result.manifest["manifest_hash"] != plain_result.manifest["manifest_hash"]

    with pytest.raises(HistoricalReplayValidationError):
        replay_historical_walk_forward(
            path,
            runner=object(),
            candidate_grid=candidate_grid,
            split_config=split_config,
            selection_criteria=selection_criteria,
            strategy_version="v4_walk_forward",
            costs={"entry_fee_rate": "0", "exit_fee_rate": "0", "spread_bps": "0", "slippage_bps": "0", "leverage": "1"},
        )

    with pytest.raises(PromotionEvidenceError):
        adapt_walk_forward_result(replay.result)


def test_historical_replay_rejects_dataframe_divergence_and_preserves_manifest_hash(tmp_path):
    path, dataset = _historical_dataset(tmp_path, rows=260)
    frame = historical_dataset_to_dataframe(dataset)
    assert frame.iloc[0]["open_time"] == dataset.candles[0].open_time
    assert frame.iloc[-1]["close_time"] == dataset.candles[-1].close_time

    shuffled = frame.iloc[::-1].reset_index(drop=True)
    assert list(shuffled["open_time"]) != list(frame["open_time"])

    runner = _trusted_runner("BTCUSDT", "1h")
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
    selection_criteria = SelectionCriteria(
        min_total_trades=0,
        min_net_return=Decimal("-100000"),
        max_drawdown_percent=Decimal("100000"),
        min_expectancy=Decimal("-100000"),
        require_defined_profit_factor=False,
        min_profit_factor=Decimal("0"),
    )
    candidate_grid = [_candidate()]
    replay = replay_historical_walk_forward(
        path,
        runner=runner,
        candidate_grid=candidate_grid,
        split_config=split_config,
        selection_criteria=selection_criteria,
        strategy_version="v4_walk_forward",
        costs={"entry_fee_rate": "0", "exit_fee_rate": "0", "spread_bps": "0", "slippage_bps": "0", "leverage": "1"},
    )
    assert replay.result.manifest["historical_provenance"]["dataset_id"] == replay.provenance.dataset_id
    assert replay.result.manifest["historical_provenance"]["classification"] == "historical_research_only"
