from __future__ import annotations

import json
import hashlib
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from contextlib import contextmanager
from types import SimpleNamespace
from pathlib import Path

import pandas as pd
import pytest

import decisor
import paper_operations as paper_ops
from domain import Candle
from domain.serialization import serialize_value
from market_data import candles_to_market_snapshot
from paper_evaluation import PaperEvaluationPolicy
from paper_evaluation._operational import OperationalCohortContract
from paper_evaluation.errors import PaperCampaignManifestError, PaperCampaignReadError
from paper_evaluation.artifacts import paper_evaluation_hash
from paper_evaluation import OperationalPaperCampaignContract
from paper_evaluation.campaign import _campaign_load_mode
from paper_runtime import PaperRuntimeContract, PaperRuntimeState, PaperRuntimeStore
from promotion import (
    PromotionCriterionResult,
    PromotionDecision,
    PromotionPolicy,
    PromotionStatus,
    promotion_hash,
)
from promotion.errors import PromotionEvidenceError
from promotion.monitoring import MonitoredPaperLimits
from validation import CandidateConfig, FrozenSelection
from paper_operations import (
    _ALLOW_TEMPORARY_DATA_DIRS_FOR_TESTS,
    _data_dir,
    _lock_file_path,
    backup_create,
    backup_list,
    backup_verify,
    campaign_prepare,
    campaign_bind,
    cohort_prepare,
    doctor,
    initialize,
    main as paper_operations_main,
    phase5_reference,
    report,
    restore_apply,
    restore_recover,
    restore_verify,
    runtime_resume,
    session_complete,
    session_start,
    session_status,
    promotion_decision,
    PaperOperationsError,
)
from paper_runtime.errors import PaperRuntimeSessionError, PaperRuntimeStoreError
import storage
from market_data import MarketDataPackage, MarketDataProvenance
from validation.artifacts import build_data_signature, build_manifest, freeze_selection
from validation.models import CandidateEvaluation, SegmentMetrics, ValidationSplitConfig, WalkForwardResult, WalkForwardWindowResult, WindowBounds
from validation.splits import build_rolling_windows


def _write_json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(serialize_value(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _enable_operational_tmp_dirs(monkeypatch) -> None:
    monkeypatch.setattr("paper_operations._ALLOW_TEMPORARY_DATA_DIRS_FOR_TESTS", True)


def _operational_reference_payload(
    frame: pd.DataFrame,
    *,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
) -> list[list[int | str]]:
    candles = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for idx, row in frame.reset_index(drop=True).iterrows():
        open_time = start + timedelta(hours=idx)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        candles.append(
            [
                int(open_time.timestamp() * 1000),
                str(row["open"]),
                str(row["high"]),
                str(row["low"]),
                str(row["close"]),
                str(row["volume"]),
                int(close_time.timestamp() * 1000),
                0,
                0,
                0,
                0,
                0,
            ]
        )
    return candles


def _trusted_operational_reference_package(
    monkeypatch,
    frame: pd.DataFrame,
    *,
    symbol: str = "BTCUSDT",
    interval: str = "1h",
):
    payload = _operational_reference_payload(frame, symbol=symbol, interval=interval)
    provider = paper_ops.trusted_market_data_service.provider
    monkeypatch.setattr(paper_ops.trusted_market_data_service, "max_age_seconds", 10**9)

    def fetch_klines(symbol="BTCUSDT", interval="1h", limit=500, *, end_time=None):
        rows = payload
        if end_time is not None:
            rows = [row for row in rows if row[6] <= end_time]
        return rows[:limit]

    monkeypatch.setattr(provider, "fetch_klines", fetch_klines)
    return paper_ops.trusted_market_data_service.fetch(symbol=symbol, interval=interval, limit=min(len(payload), 500))


def _operational_reference_frame(rows: int = 1200) -> pd.DataFrame:
    prices = []
    price = 100.0
    cycle = 0
    while len(prices) < rows:
        for _ in range(30):
            if len(prices) >= rows:
                break
            price += 4
            prices.append(price)
        for _ in range(3):
            if len(prices) >= rows:
                break
            price -= 30
            prices.append(price)
        post_step = 1 if cycle % 2 == 0 else -4
        for _ in range(10):
            if len(prices) >= rows:
                break
            price += post_step
            prices.append(price)
        cycle += 1
    prices = prices[:rows]
    times = pd.date_range("2025-01-01", periods=rows, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": times,
            "close_time": times + pd.Timedelta(hours=1) - pd.Timedelta(milliseconds=1),
            "open": [valor - 1 for valor in prices],
            "high": [valor + 2 for valor in prices],
            "low": [valor - 2 for valor in prices],
            "close": prices,
            "volume": [1000 + (idx % 10) * 50 for idx in range(rows)],
        }
    )


def _mock_operational_market_data(monkeypatch, frame: pd.DataFrame):
    return _trusted_operational_reference_package(monkeypatch, frame)


def _seed_decision_log(db_path: Path, *, modo: str, decisao: str, symbol: str) -> None:
    storage.criar_tabelas(db_name=str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO decision_logs (
                timestamp, symbol, modo, decisao, direcao, preco, regime, adx,
                volume_status, motivo, bloqueado_por, fonte_dados, erro, strategy_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                symbol,
                modo,
                decisao,
                "N/A",
                1.0,
                "BULL",
                20.0,
                "ALTO",
                "test",
                "N/A",
                "BINANCE",
                None,
                "v2_risk_safe",
            ),
        )
        conn.commit()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _sqlite_logical_fingerprint(path: Path) -> str:
    if not path.exists():
        return "missing"
    with sqlite3.connect(path) as conn:
        table_names = [
            row[0]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        ]
        payload: list[dict[str, object]] = []
        for table_name in table_names:
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
            rows = conn.execute(f'SELECT * FROM "{table_name}" ORDER BY rowid').fetchall()
            payload.append({"table": table_name, "columns": columns, "rows": rows})
    digest = hashlib.sha256()
    digest.update(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
    return digest.hexdigest()


def _sqlite_table_rows(path: Path, table: str):
    with sqlite3.connect(path) as conn:
        return conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()


def _sqlite_table_count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as conn:
        return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]


def _seed_reference_registry(reference_db: Path, reference_payload: dict[str, object]) -> dict[str, str]:
    paper_ops._ensure_reference_schema(reference_db)
    provenance = reference_payload["operational_provenance"]
    reference_hash = paper_ops.validation_manifest_hash(reference_payload)
    scope_hash = paper_ops.validation_manifest_hash(
        {
            "symbol": provenance["symbol"],
            "interval": provenance["interval"],
            "strategy_version": provenance["strategy_version"],
            "provider": provenance["provider"],
            "limit_value": provenance["limit_value"],
            "data_period_start_utc": provenance["data_period_start_utc"],
            "data_period_end_utc": provenance["data_period_end_utc"],
        }
    )
    provenance["reference_hash"] = reference_hash
    provenance["scope_hash"] = scope_hash
    reference_payload["operational_provenance"] = provenance
    payload_json = json.dumps(serialize_value(reference_payload), ensure_ascii=False, sort_keys=True)
    with sqlite3.connect(reference_db) as conn:
        conn.execute(
            """
            INSERT INTO operational_reference_contracts (
                reference_hash, scope_hash, symbol, interval, strategy_version, provider, limit_value,
                data_period_start_utc, data_period_end_utc, data_content_hash, manifest_hash, result_hash,
                created_at_utc, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference_hash,
                scope_hash,
                provenance["symbol"],
                provenance["interval"],
                provenance["strategy_version"],
                provenance["provider"],
                provenance["limit_value"],
                provenance["data_period_start_utc"],
                provenance["data_period_end_utc"],
                provenance["data_content_hash"],
                provenance["manifest_hash"],
                provenance["result_hash"],
                provenance["created_at_utc"],
                payload_json,
            ),
        )
        conn.commit()
    return {"reference_hash": reference_hash, "scope_hash": scope_hash, "payload_json": payload_json}


def _approved_walk_forward_result(frame: pd.DataFrame) -> WalkForwardResult:
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
    candidate = CandidateConfig.from_mapping("alpha", {"risk": "low"})
    windows = build_rolling_windows(frame, split_config)
    if not windows:
        raise AssertionError("expected at least one walk-forward window for the approval fixture.")
    bounds = windows[0]

    def _metrics(*, net_return_percent: str, expectancy: str, profit_factor: str, drawdown_max_percent: str, total_trades: int, winning_trades: int, losing_trades: int, breakeven_trades: int, gross_profit: str, gross_loss: str) -> SegmentMetrics:
        capital_initial = Decimal("10000")
        net_pnl = (capital_initial * Decimal(str(net_return_percent)) / Decimal("100")).quantize(Decimal("0.0001"))
        return SegmentMetrics.from_summary(
            {
                "capital_initial": "10000",
                "capital_final": str((capital_initial + net_pnl).quantize(Decimal("0.0001"))),
                "net_pnl": str(net_pnl),
                "net_return_percent": net_return_percent,
                "gross_pnl": str(Decimal(gross_profit) - Decimal(gross_loss)),
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

    train_metrics = _metrics(
        net_return_percent="6",
        expectancy="1.2",
        profit_factor="1.4",
        drawdown_max_percent="4",
        total_trades=12,
        winning_trades=7,
        losing_trades=4,
        breakeven_trades=1,
        gross_profit="120",
        gross_loss="80",
    )
    validation_metrics = _metrics(
        net_return_percent="5",
        expectancy="1.1",
        profit_factor="1.35",
        drawdown_max_percent="5",
        total_trades=11,
        winning_trades=6,
        losing_trades=4,
        breakeven_trades=1,
        gross_profit="110",
        gross_loss="80",
    )
    test_metrics = _metrics(
        net_return_percent="4",
        expectancy="1.0",
        profit_factor="1.25",
        drawdown_max_percent="6",
        total_trades=10,
        winning_trades=6,
        losing_trades=3,
        breakeven_trades=1,
        gross_profit="100",
        gross_loss="80",
    )
    evaluation = CandidateEvaluation(candidate=candidate, train_metrics=train_metrics, validation_metrics=validation_metrics, stability_score=Decimal("0.2"))
    window_signature = {
        "warmup_train": build_data_signature(frame.iloc[bounds.warmup_start : bounds.train_start], symbol="BTCUSDT", interval="1h"),
        "train": build_data_signature(frame.iloc[bounds.train_start : bounds.train_end], symbol="BTCUSDT", interval="1h"),
        "warmup_validation": build_data_signature(frame.iloc[bounds.train_end : bounds.validation_start], symbol="BTCUSDT", interval="1h"),
        "validation": build_data_signature(frame.iloc[bounds.validation_start : bounds.validation_end], symbol="BTCUSDT", interval="1h"),
        "warmup_test": build_data_signature(frame.iloc[bounds.validation_end : bounds.test_start], symbol="BTCUSDT", interval="1h"),
        "test": build_data_signature(frame.iloc[bounds.test_start : bounds.test_end], symbol="BTCUSDT", interval="1h"),
    }
    window_manifest = build_manifest(
        symbol="BTCUSDT",
        interval="1h",
        strategy_version="v4_walk_forward",
        costs={"entry_fee_rate": "0.0004", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5", "leverage": "1"},
        split_config=split_config,
        candidate_grid=[candidate],
        windows=[bounds],
        data_signature=window_signature["test"],
        selection_criteria={"min_total_trades": 1},
        execution_contract={"engine_class": "LeakFreeBacktestEngine", "entry_fee_rate": "0.0004", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5", "leverage": "1", "intrabar_policy": "STOP_FIRST", "gap_policy": "OPEN_PRICE", "paper_only": True, "symbol": "BTCUSDT", "interval": "1h", "strategy_version": "v4_walk_forward"},
        window_signatures=window_signature,
        runner_trusted=True,
        seed=7,
    )
    manifest = build_manifest(
        symbol="BTCUSDT",
        interval="1h",
        strategy_version="v4_walk_forward",
        costs={"entry_fee_rate": "0.0004", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5", "leverage": "1"},
        split_config=split_config,
        candidate_grid=[candidate],
        windows=[bounds],
        data_signature=window_signature["test"],
        selection_criteria={"min_total_trades": 1},
        execution_contract={"engine_class": "LeakFreeBacktestEngine", "entry_fee_rate": "0.0004", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5", "leverage": "1", "intrabar_policy": "STOP_FIRST", "gap_policy": "OPEN_PRICE", "paper_only": True, "symbol": "BTCUSDT", "interval": "1h", "strategy_version": "v4_walk_forward"},
        window_signatures={"windows": [window_signature]},
        runner_trusted=True,
        seed=7,
    )
    frozen = freeze_selection(
        candidate,
        strategy_version="v4_walk_forward",
        costs={"entry_fee_rate": "0.0004", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5", "leverage": "1"},
        execution_contract={"engine_class": "LeakFreeBacktestEngine", "entry_fee_rate": "0.0004", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5", "leverage": "1", "intrabar_policy": "STOP_FIRST", "gap_policy": "OPEN_PRICE", "paper_only": True, "symbol": "BTCUSDT", "interval": "1h", "strategy_version": "v4_walk_forward"},
        symbol="BTCUSDT",
        interval="1h",
        frozen_at=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
        manifest_hash_value=window_manifest["manifest_hash"],
        window_id="0:1:2",
    )
    window_result = WalkForwardWindowResult(
        bounds=bounds,
        candidate_evaluations=(evaluation,),
        selected_candidate=candidate,
        frozen_selection=frozen,
        test_metrics=test_metrics,
        manifest_hash=window_manifest["manifest_hash"],
        approved=True,
        reason="approved",
    )
    summary = {
        "total_windows": 1,
        "selected_windows": 1,
        "total_trades": 10,
        "net_return_percent": "4",
        "net_pnl": "400",
        "drawdown_max_percent": "6",
        "expectancy": "1",
        "profit_factor": "1.25",
        "degradation_validation_test": "1",
        "winning_trades": 6,
        "losing_trades": 3,
        "breakeven_trades": 1,
        "manifest_hash": manifest["manifest_hash"],
        "runner_trusted": True,
    }
    return WalkForwardResult(windows=(window_result,), summary=summary, manifest=manifest)


def _seed_campaign_registry(campaign_db: Path, contract: OperationalPaperCampaignContract) -> str:
    paper_ops.ensure_operational_paper_campaign_schema(campaign_db)
    contract_hash = contract.campaign_hash
    payload_json = json.dumps(contract.as_dict(), ensure_ascii=False, sort_keys=True)
    with sqlite3.connect(campaign_db) as conn:
        conn.execute(
            """
            INSERT INTO paper_evaluation_campaign_contracts (
                campaign_hash, campaign_id, cohort_hash, strategy_version, symbol, interval, inclusion_rule,
                period_start_utc, period_end_utc, policy_payload_json, reference_payload_json, policy_hash, walk_forward_manifest_hash,
                walk_forward_result_hash, evaluator_version, created_at_utc, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contract_hash,
                contract.campaign_id,
                contract.cohort_hash,
                contract.strategy_version,
                contract.symbol,
                contract.interval,
                contract.inclusion_rule,
                contract.period_start_utc.isoformat().replace("+00:00", "Z"),
                contract.period_end_utc.isoformat().replace("+00:00", "Z"),
                json.dumps(serialize_value(dict(contract.policy_payload)), ensure_ascii=False, sort_keys=True),
                json.dumps(serialize_value(dict(contract.reference_payload_json)), ensure_ascii=False, sort_keys=True),
                contract.policy_hash,
                contract.walk_forward_manifest_hash,
                contract.walk_forward_result_hash,
                contract.evaluator_version,
                contract.created_at_utc.isoformat().replace("+00:00", "Z"),
                payload_json,
            ),
        )
        conn.commit()
    return contract_hash


def _seed_promotion_decision_registry(reference_db: Path, decision: PromotionDecision) -> None:
    paper_ops._ensure_promotion_decision_schema(reference_db)
    payload_json = json.dumps(
        serialize_value({"reference_hash": decision.evidence_hash, "decision": decision.as_dict()}),
        ensure_ascii=False,
        sort_keys=True,
    )
    with sqlite3.connect(reference_db) as conn:
        conn.execute(
            """
            INSERT INTO operational_promotion_decision_contracts (
                decision_hash, reference_hash, policy_hash, paper_limits_hash, status,
                strategy_version, symbol, interval, created_at_utc, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.decision_hash,
                decision.evidence_hash,
                decision.policy_hash,
                decision.paper_limits_hash,
                decision.status.value,
                decision.strategy_version,
                decision.symbol,
                decision.interval,
                decision.timestamp_utc.isoformat().replace("+00:00", "Z"),
                payload_json,
            ),
        )
        conn.commit()


def _seed_runtime_session(runtime_db: Path, *, session_id: str, decision_hash: str, strategy_version: str, symbol: str, interval: str, started_at: datetime) -> None:
    store = PaperRuntimeStore(runtime_db)
    store.initialize()
    contract = PaperRuntimeContract(
        session_id=session_id,
        session_started_utc=started_at,
        decision_hash=decision_hash,
        evidence_hash="test-evidence-hash",
        paper_limits_hash="test-paper-limits-hash",
        paper_limits={"paper_capital_max": "10000", "risk_per_trade_max_percent": "1"},
        configuration={"test_only": True},
        strategy_version=strategy_version,
        symbol=symbol,
        interval=interval,
        execution_contract={"paper_only": True},
        paper_only=True,
    )
    store.create_session(contract, session_state=PaperRuntimeState.RUNNING)


def _seed_second_active_runtime_session(runtime_db: Path, *, session_id: str = "secondary-session") -> None:
    store = PaperRuntimeStore(runtime_db)
    started_at = datetime.now(timezone.utc).replace(microsecond=0)
    contract = PaperRuntimeContract(
        session_id=session_id,
        session_started_utc=started_at,
        decision_hash=f"decision-{session_id}",
        evidence_hash=f"evidence-{session_id}",
        paper_limits_hash=f"paper-limits-{session_id}",
        paper_limits={"paper_capital_max": "10000", "risk_per_trade_max_percent": "1"},
        configuration={"test_only": True, "session_tag": session_id},
        strategy_version="v4_walk_forward",
        symbol="BTCUSDT",
        interval="1h",
        execution_contract={"paper_only": True},
        paper_only=True,
    )
    store.create_session(contract, session_state=PaperRuntimeState.RUNNING)


def _prepare_test_only_local_operations_fixture(tmp_path: Path, monkeypatch, sample_btc_data):
    _enable_operational_tmp_dirs(monkeypatch)
    monkeypatch.setattr("paper_operations.live_trading_permitted", lambda: False)
    monkeypatch.setattr(decisor, "obter_funding_rate", lambda symbol="BTCUSDT": None)
    monkeypatch.setattr(decisor, "log_decisao", lambda *args, **kwargs: None)
    data_dir = tmp_path / "paper_data"
    initialize(data_dir=data_dir)
    operational_frame = _operational_reference_frame(len(sample_btc_data))
    package = _trusted_operational_reference_package(monkeypatch, operational_frame)

    reference_result = _approved_walk_forward_result(sample_btc_data.iloc[:260].copy())
    reference_output = data_dir / "reference.json"
    reference_payload = {
        "operational_provenance": {
            "version": 1,
            "synthetic_test_data": False,
            "symbol": "BTCUSDT",
            "interval": "1h",
            "strategy_version": "v4_walk_forward",
            "provider": "trusted_market_data_service",
            "limit_value": len(sample_btc_data),
            "data_period_start_utc": sample_btc_data.iloc[0]["open_time"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "data_period_end_utc": sample_btc_data.iloc[-1]["close_time"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "evidence_class": "OPERATIONAL_TRUSTED",
            "data_content_hash": paper_ops.validation_manifest_hash(
                {
                    "symbol": "BTCUSDT",
                    "interval": "1h",
                    "provider": "trusted_market_data_service",
                    "candles": [
                        {
                            "open_time": candle.open_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "close_time": candle.close_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "open": str(candle.open),
                            "high": str(candle.high),
                            "low": str(candle.low),
                            "close": str(candle.close),
                            "volume": str(candle.volume),
                        }
                        for candle in package.candles
                    ],
                }
            ),
            "data_signature_hash": reference_result.manifest["data_signature"]["content_hash"],
            "manifest_hash": reference_result.manifest["manifest_hash"],
            "result_hash": paper_ops.validation_manifest_hash(reference_result.as_dict()),
            "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reference_hash": "",
            "scope_hash": "",
        },
        "walk_forward": reference_result.as_dict(),
    }
    _seed_reference_registry(reference_output.parent / "paper_evaluation_reference.db", reference_payload)
    _write_json(reference_output, reference_payload)
    assert reference_result.manifest["runner_trusted"] is True

    policy_file = tmp_path / "promotion_policy.json"
    _write_json(
        policy_file,
        PromotionPolicy(
            min_oos_windows=1,
            min_oos_trades=1,
            min_oos_net_return_percent=0,
            min_oos_expectancy=0,
            min_oos_profit_factor=0.1,
            max_oos_drawdown_percent=100,
            min_profitable_window_ratio_percent=0,
            max_validation_degradation_percent=100,
            require_nonzero_costs=True,
        ).as_dict(),
    )
    decision_file = data_dir / "promotion_decision.json"
    promotion_result = promotion_decision(
        reference_file=reference_output,
        policy_file=policy_file,
        output_file=decision_file,
    )
    assert promotion_result["status"] == PromotionStatus.APPROVED_FOR_MONITORED_PAPER.value

    campaign_policy_file = tmp_path / "campaign_policy.json"
    _write_json(campaign_policy_file, PaperEvaluationPolicy().as_dict())
    now = datetime.now(timezone.utc).replace(microsecond=0)
    period_start = now + timedelta(days=1)
    period_end = period_start + timedelta(days=1)
    cohort = cohort_prepare(
        strategy_version="v4_walk_forward",
        symbol="BTCUSDT",
        interval="1h",
        inclusion_rule="sessions-with-valid-paper-evidence",
        period_start_utc=period_start.isoformat().replace("+00:00", "Z"),
        period_end_utc=period_end.isoformat().replace("+00:00", "Z"),
        runtime_db=data_dir / "paper_runtime.db",
    )
    campaign = campaign_prepare(
        campaign_id="campaign-phase8c",
        policy_file=campaign_policy_file,
        reference_file=reference_output,
        strategy_version="v4_walk_forward",
        symbol="BTCUSDT",
        interval="1h",
        inclusion_rule="sessions-with-valid-paper-evidence",
        period_start_utc=period_start.isoformat().replace("+00:00", "Z"),
        period_end_utc=period_end.isoformat().replace("+00:00", "Z"),
        cohort_hash=cohort["cohort_hash"],
        runtime_db=data_dir / "paper_runtime.db",
        campaign_db=data_dir / "paper_evaluation_campaign.db",
    )
    binding = campaign_bind(
        campaign_id="campaign-phase8c",
        decision_file=decision_file,
        campaign_db=data_dir / "paper_evaluation_campaign.db",
        data_dir=data_dir,
    )
    reference_payload = json.loads(reference_output.read_text(encoding="utf-8"))
    return {
        "data_dir": data_dir,
        "reference_output": reference_output,
        "decision_file": decision_file,
        "campaign_id": campaign["campaign_id"],
        "binding_hash": binding["binding_hash"],
        "cohort_hash": cohort["cohort_hash"],
        "reference_hash": reference_payload["operational_provenance"]["reference_hash"],
        "synthetic_test_data": False,
    }


def _create_legacy_campaign_binding_db(path: Path, binding, *, payload_mutator=None) -> None:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE operational_campaign_decision_bindings (
                binding_hash TEXT PRIMARY KEY,
                campaign_hash TEXT NOT NULL UNIQUE,
                campaign_id TEXT NOT NULL UNIQUE,
                decision_hash TEXT NOT NULL UNIQUE,
                reference_hash TEXT NOT NULL UNIQUE,
                evidence_hash TEXT NOT NULL,
                manifest_hash TEXT NOT NULL,
                result_hash TEXT NOT NULL,
                promotion_policy_hash TEXT NOT NULL,
                campaign_policy_hash TEXT NOT NULL,
                paper_limits_hash TEXT NOT NULL,
                frozen_selection_hash TEXT NOT NULL,
                cohort_hash TEXT NOT NULL,
                strategy_version TEXT NOT NULL,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                evidence_class TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        payload = dict(binding.as_hash_payload(include_hash=False))
        payload.pop("payload_hash", None)
        if payload_mutator is not None:
            payload = payload_mutator(payload)
        legacy_hash_payload = dict(payload)
        legacy_hash_payload.pop("payload_json", None)
        old_binding_hash = paper_evaluation_hash(serialize_value(legacy_hash_payload))
        conn.execute(
            """
            INSERT INTO operational_campaign_decision_bindings (
                binding_hash, campaign_hash, campaign_id, decision_hash, reference_hash, evidence_hash,
                manifest_hash, result_hash, promotion_policy_hash, campaign_policy_hash, paper_limits_hash,
                frozen_selection_hash, cohort_hash, strategy_version, symbol, interval, evidence_class,
                created_at_utc, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                old_binding_hash,
                binding.campaign_hash,
                binding.campaign_id,
                binding.decision_hash,
                binding.reference_hash,
                binding.evidence_hash,
                binding.manifest_hash,
                binding.result_hash,
                binding.promotion_policy_hash,
                binding.campaign_policy_hash,
                binding.paper_limits_hash,
                binding.frozen_selection_hash,
                binding.cohort_hash,
                binding.strategy_version,
                binding.symbol,
                binding.interval,
                binding.evidence_class,
                binding.created_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True),
            ),
        )
        conn.commit()


def test_operational_data_dir_rejects_temporary_paths_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr("paper_operations._ALLOW_TEMPORARY_DATA_DIRS_FOR_TESTS", False)
    with pytest.raises(ValueError, match="temporary directory"):
        _data_dir(tmp_path / "paper_data")


def test_phase5_reference_rejects_synthetic_fixture(tmp_path, monkeypatch):
    _enable_operational_tmp_dirs(monkeypatch)
    synthetic_reference = tmp_path / "synthetic_reference.json"
    _write_json(
        synthetic_reference,
        {
            "operational_provenance": {
                "version": 1,
                "synthetic_test_data": True,
                "manifest_hash": "synthetic",
                "result_hash": "synthetic",
                "data_signature_hash": "synthetic",
            },
            "walk_forward": {"windows": [], "summary": {}, "manifest": {}},
        },
    )
    with pytest.raises(PaperOperationsError):
        phase5_reference(input_file=synthetic_reference, output_file=tmp_path / "output.json")


def test_phase5_reference_rejects_unknown_market_data_provenance(tmp_path, monkeypatch, sample_btc_data):
    _enable_operational_tmp_dirs(monkeypatch)
    monkeypatch.setattr("paper_operations.live_trading_permitted", lambda: False)
    monkeypatch.setattr(decisor, "obter_funding_rate", lambda symbol="BTCUSDT": None)
    monkeypatch.setattr(decisor, "log_decisao", lambda *args, **kwargs: None)
    data_dir = tmp_path / "paper_data"
    initialize(data_dir=data_dir)

    trusted_package = _trusted_operational_reference_package(monkeypatch, sample_btc_data)
    unknown_package = MarketDataPackage(
        symbol=trusted_package.symbol,
        interval=trusted_package.interval,
        candles=trusted_package.candles,
        snapshot=trusted_package.snapshot,
        source=trusted_package.source,
        provenance_class=MarketDataProvenance.UNKNOWN,
        fetched_at=trusted_package.fetched_at,
        expires_at=trusted_package.expires_at,
        cache_status="miss",
    )
    monkeypatch.setattr(paper_ops.trusted_market_data_service, "fetch", lambda **kwargs: unknown_package)

    reference_input = tmp_path / "reference_config.json"
    _write_json(
        reference_input,
        {
            "symbol": "BTCUSDT",
            "interval": "1h",
            "limit": 1000,
            "strategy_version": "v4_walk_forward",
            "provider": "trusted_market_data_service",
        },
    )
    with pytest.raises(PaperOperationsError, match="trusted operational market data"):
        phase5_reference(input_file=reference_input, output_file=data_dir / "reference.json")


def test_phase8c_honest_operational_flow_rejects_unsatisfied_strategy_without_adulteration(tmp_path, monkeypatch, sample_btc_data):
    _enable_operational_tmp_dirs(monkeypatch)
    monkeypatch.setattr("paper_operations.live_trading_permitted", lambda: False)
    monkeypatch.setattr(decisor, "obter_funding_rate", lambda symbol="BTCUSDT": None)
    monkeypatch.setattr(decisor, "log_decisao", lambda *args, **kwargs: None)
    data_dir = tmp_path / "paper_data"
    initialize(data_dir=data_dir)

    _trusted_operational_reference_package(monkeypatch, sample_btc_data)

    reference_input = tmp_path / "reference_config.json"
    _write_json(
        reference_input,
        {
            "symbol": "BTCUSDT",
            "interval": "1h",
            "limit": 1000,
            "strategy_version": "v4_walk_forward",
            "provider": "trusted_market_data_service",
        },
    )
    reference_output = data_dir / "reference.json"
    reference_result = phase5_reference(input_file=reference_input, output_file=reference_output)
    assert reference_result["runner_trusted"] is True
    assert reference_result["synthetic_test_data"] is False

    reference_payload = json.loads(reference_output.read_text(encoding="utf-8"))
    assert all(window.get("approved") is not True for window in reference_payload["walk_forward"]["windows"])

    policy_file = tmp_path / "promotion_policy.json"
    _write_json(
        policy_file,
        PromotionPolicy(
            min_oos_windows=1,
            min_oos_trades=1,
            min_oos_net_return_percent=0,
            min_oos_expectancy=0,
            min_oos_profit_factor=0.1,
            max_oos_drawdown_percent=100,
            min_profitable_window_ratio_percent=0,
            max_validation_degradation_percent=100,
            require_nonzero_costs=True,
        ).as_dict(),
    )
    campaign_policy_file = tmp_path / "campaign_policy.json"
    _write_json(campaign_policy_file, PaperEvaluationPolicy().as_dict())
    now = datetime.now(timezone.utc).replace(microsecond=0)
    period_start = now + timedelta(days=1)
    period_end = period_start + timedelta(days=1)
    cohort = cohort_prepare(
        strategy_version="v4_walk_forward",
        symbol="BTCUSDT",
        interval="1h",
        inclusion_rule="sessions-with-valid-paper-evidence",
        period_start_utc=period_start.isoformat().replace("+00:00", "Z"),
        period_end_utc=period_end.isoformat().replace("+00:00", "Z"),
        runtime_db=data_dir / "paper_runtime.db",
    )
    with pytest.raises(PromotionEvidenceError):
        promotion_decision(
            reference_file=reference_output,
            policy_file=policy_file,
            output_file=tmp_path / "rejected_decision.json",
        )

    with pytest.raises(PaperCampaignManifestError):
        campaign_prepare(
            campaign_id="campaign-phase8c-honest",
            policy_file=campaign_policy_file,
            reference_file=reference_output,
            strategy_version="v4_walk_forward",
            symbol="BTCUSDT",
            interval="1h",
            inclusion_rule="sessions-with-valid-paper-evidence",
            period_start_utc=period_start.isoformat().replace("+00:00", "Z"),
            period_end_utc=period_end.isoformat().replace("+00:00", "Z"),
            cohort_hash=cohort["cohort_hash"],
            runtime_db=data_dir / "paper_runtime.db",
            campaign_db=data_dir / "paper_evaluation_campaign.db",
        )


def test_phase8c_full_local_operations_flow_uses_real_reference_and_sanitized_reports(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]

    session = session_start(
        campaign_id=flow["campaign_id"],
        decision_file=flow["decision_file"],
        campaign_db=data_dir / "paper_evaluation_campaign.db",
        data_dir=data_dir,
    )
    assert session["session_id"]
    assert session["state"] == "RUNNING"
    binding = paper_ops.load_operational_campaign_decision_binding(
        data_dir / "paper_evaluation_campaign.db",
        campaign_id=flow["campaign_id"],
    )
    assert binding is not None
    assert binding.payload_hash == paper_evaluation_hash(binding.payload_json)

    with sqlite3.connect(data_dir / "paper_runtime.db") as conn:
        row = conn.execute(
            "SELECT session_id, state FROM paper_runtime_sessions WHERE session_id = ?",
            (session["session_id"],),
        ).fetchone()
    assert row is not None
    assert row[0] == session["session_id"]
    assert row[1] == "RUNNING"

    resumed = runtime_resume(session_id=session["session_id"], data_dir=data_dir)
    assert resumed["state"] == "RUNNING"

    completed = session_complete(session_id=session["session_id"], reason="test completion", data_dir=data_dir)
    assert completed["state"] == "COMPLETED"

    backup = backup_create(data_dir=data_dir, backup_name="test-backup")
    assert Path(backup["backup_dir"]).exists()
    assert backup["files"] == ["paper_evaluation_campaign.db", "paper_evaluation_reference.db", "paper_runtime.db", "trades.db"]
    assert backup_list(data_dir=data_dir)["backups"] == ["test-backup"]

    restore = restore_verify(backup_dir=backup["backup_dir"])
    assert restore["verified"] is True
    assert restore["backup_dir"] == "test-backup"
    assert restore["files"] == ["paper_evaluation_campaign.db", "paper_evaluation_reference.db", "paper_runtime.db", "trades.db"]
    assert "paper_restore_verify_" not in json.dumps(restore)

    applied = restore_apply(backup_dir=backup["backup_dir"], data_dir=data_dir, confirm=True)
    assert applied["restored_from"] == "test-backup"

    doctor_report = doctor(data_dir=data_dir)
    assert doctor_report["status"] == "READY"
    assert doctor_report["local_operations_ready"] is True

    report_result = report(data_dir=data_dir, campaign_id=flow["campaign_id"], session_id=session["session_id"])
    assert report_result["doctor"]["status"] == "READY"
    assert report_result["doctor"]["local_operations_ready"] is True
    assert report_result["doctor"]["bot_runtime_ready"] in {True, False}
    assert report_result["campaign"]["campaign_id"] == flow["campaign_id"]
    assert report_result["session"]["session_id"] == session["session_id"]
    assert report_result["operational_summary"]["local_operations_ready"] is True
    assert report_result["operational_summary"]["sessions_observed"] >= 1
    assert report_result["operational_summary"]["hours_observed"] >= 0
    assert report_result["activity"]["open_positions"] >= 0
    assert report_result["activity"]["closed_trades"] >= 0
    assert report_result["activity"]["distinct_days"] >= 0
    assert report_result["activity"]["outbox_pending"] >= 0
    assert report_result["last_restore_verify"]["verified"] is True


def test_campaign_bind_is_idempotent_and_preserves_created_at(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    campaign_db = data_dir / "paper_evaluation_campaign.db"
    first_binding = paper_ops.load_operational_campaign_decision_binding(campaign_db, campaign_id=flow["campaign_id"])
    assert first_binding is not None

    repeated = campaign_bind(
        campaign_id=flow["campaign_id"],
        decision_file=flow["decision_file"],
        campaign_db=campaign_db,
        data_dir=data_dir,
    )
    assert repeated["binding_hash"] == first_binding.binding_hash
    assert repeated["created_at_utc"] == first_binding.created_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    second_binding = paper_ops.load_operational_campaign_decision_binding(campaign_db, campaign_id=flow["campaign_id"])
    assert second_binding is not None
    assert second_binding.as_dict() == first_binding.as_dict()


def test_session_start_holds_lock_during_loading_and_creation(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    campaign_db = data_dir / "paper_evaluation_campaign.db"
    contract = paper_ops.load_operational_paper_campaign_contract(campaign_db, campaign_id=flow["campaign_id"])
    decision_payload = paper_ops._load_promotion_decision(flow["decision_file"])
    reference_envelope = paper_ops._load_walk_forward_reference_envelope(flow["reference_output"])
    binding = paper_ops.load_operational_campaign_decision_binding(campaign_db, campaign_id=flow["campaign_id"])
    assert binding is not None
    decision_registry = paper_ops._load_promotion_decision_registry(
        data_dir / "paper_evaluation_reference.db",
        decision_payload.decision_hash,
    )

    lock_state = {"active": False}

    @contextmanager
    def fake_lock(*args, **kwargs):
        lock_state["active"] = True
        try:
            yield
        finally:
            lock_state["active"] = False

    def _assert_locked(*args, **kwargs):
        assert lock_state["active"] is True

    monkeypatch.setattr(paper_ops, "_acquire_operational_lock", fake_lock)
    monkeypatch.setattr(paper_ops, "load_operational_paper_campaign_contract", lambda *args, **kwargs: (_assert_locked(), contract)[1])
    monkeypatch.setattr(paper_ops, "_load_promotion_decision", lambda *args, **kwargs: (_assert_locked(), decision_payload)[1])
    monkeypatch.setattr(paper_ops, "_load_promotion_decision_registry", lambda *args, **kwargs: (_assert_locked(), decision_registry)[1])
    monkeypatch.setattr(paper_ops, "_load_walk_forward_reference_envelope", lambda *args, **kwargs: (_assert_locked(), reference_envelope)[1])
    monkeypatch.setattr(paper_ops, "load_operational_campaign_decision_binding", lambda *args, **kwargs: (_assert_locked(), binding)[1])
    monkeypatch.setattr(
        paper_ops,
        "create_monitored_session",
        lambda *args, **kwargs: (_assert_locked(), SimpleNamespace(record=SimpleNamespace(session_id="session-lock", state=PaperRuntimeState.RUNNING)))[1],
    )

    session = session_start(
        campaign_id=flow["campaign_id"],
        decision_file=flow["decision_file"],
        campaign_db=campaign_db,
        data_dir=data_dir,
    )
    assert session["session_id"] == "session-lock"
    assert session["state"] == "RUNNING"


def test_promotion_decision_requires_status_and_session_start_fails_closed(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    bad_decision = tmp_path / "bad_decision.json"
    payload = json.loads(flow["decision_file"].read_text(encoding="utf-8"))
    payload.pop("status", None)
    _write_json(bad_decision, payload)

    with pytest.raises(PaperOperationsError):
        session_start(
            campaign_id=flow["campaign_id"],
            decision_file=bad_decision,
            campaign_db=data_dir / "paper_evaluation_campaign.db",
            data_dir=data_dir,
        )


def test_session_start_does_not_fallback_to_other_active_session(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    session = session_start(
        campaign_id=flow["campaign_id"],
        decision_file=flow["decision_file"],
        campaign_db=data_dir / "paper_evaluation_campaign.db",
        data_dir=data_dir,
    )
    assert session["state"] == "RUNNING"

    monkeypatch.setattr("paper_operations.create_monitored_session", lambda *args, **kwargs: (_ for _ in ()).throw(PaperRuntimeSessionError("forced failure")))
    with pytest.raises(PaperRuntimeSessionError):
        session_start(
            campaign_id=flow["campaign_id"],
            decision_file=flow["decision_file"],
            campaign_db=data_dir / "paper_evaluation_campaign.db",
            data_dir=data_dir,
        )


def test_session_active_reports_none_when_no_active_session(tmp_path, monkeypatch, sample_btc_data):
    _enable_operational_tmp_dirs(monkeypatch)
    data_dir = tmp_path / "paper_data"
    initialize(data_dir=data_dir)

    active = paper_ops.session_active(data_dir=data_dir)
    assert active == {"status": "NONE", "active_sessions": 0}


def test_session_active_reports_found_and_includes_session_started_utc(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    session_start(
        campaign_id=flow["campaign_id"],
        decision_file=flow["decision_file"],
        campaign_db=data_dir / "paper_evaluation_campaign.db",
        data_dir=data_dir,
    )

    active = paper_ops.session_active(data_dir=data_dir)
    assert active["status"] == "FOUND"
    assert active["active_sessions"] == 1
    assert active["session_id"]
    assert active["state"] == "RUNNING"
    assert active["session_started_utc"].endswith("Z")
    assert active["created_at_utc"].endswith("Z")


def test_session_active_blocks_multiple_active_sessions(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    session_start(
        campaign_id=flow["campaign_id"],
        decision_file=flow["decision_file"],
        campaign_db=data_dir / "paper_evaluation_campaign.db",
        data_dir=data_dir,
    )
    _seed_second_active_runtime_session(data_dir / "paper_runtime.db")

    with pytest.raises(PaperOperationsError, match="more than one active runtime session found"):
        paper_ops.session_active(data_dir=data_dir)


def test_session_active_blocks_on_store_error(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]

    def _boom(*args, **kwargs):
        raise PaperRuntimeStoreError("boom")

    monkeypatch.setattr(PaperRuntimeStore, "list_active_sessions", _boom)

    with pytest.raises(PaperRuntimeStoreError, match="boom"):
        paper_ops.session_active(data_dir=data_dir)


def test_session_active_cli_reports_active_session(tmp_path, monkeypatch, sample_btc_data, capsys):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    session_start(
        campaign_id=flow["campaign_id"],
        decision_file=flow["decision_file"],
        campaign_db=data_dir / "paper_evaluation_campaign.db",
        data_dir=data_dir,
    )

    exit_code = paper_operations_main(["--data-dir", str(data_dir), "session", "active"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "FOUND"
    assert payload["active_sessions"] == 1


def test_start_campaign_script_contains_session_active_recovery_and_atomic_write():
    script = Path("start-paper-campaign.ps1").read_text(encoding="utf-8")
    assert "session active" in script
    assert "SESSION_STARTING" in script
    assert "SESSION_STARTED" in script
    assert "Assert-PlanConsistency" in script
    assert "Convert-ToUtcIso" in script
    assert "File]::Replace" in script
    assert "File]::Move" in script
    assert '$env:PAPER_DATA_DIR = "C:\\Users\\Vitor\\BotTraderPaperData"' in script
    assert "cohort status" in script
    assert "campaign status" in script
    assert "campaign bind" in script
    assert "backup verify" in script
    assert "restore verify" in script
    assert "doctor is not ready." in script
    assert "backup.verified" in script
    assert "restore.verified" in script
    assert "campaign window has not started yet." in script
    assert "campaign window has already ended." in script
    assert "session_starting state requires an active runtime session for recovery." in script
    assert "session start did not result in a running session." in script
    assert "session start revalidation failed." in script
    assert "cohort hash mismatch." in script
    assert "campaign hash mismatch." in script
    assert "binding_hash mismatch." in script
    assert "Recovered active session" in script


def test_session_start_requires_registry_entry(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    reference_db = data_dir / "paper_evaluation_reference.db"
    with sqlite3.connect(reference_db) as conn:
        conn.execute("DELETE FROM operational_promotion_decision_contracts")
        conn.commit()

    with pytest.raises(PaperOperationsError, match="promotion decision registry entry not found"):
        session_start(
            campaign_id=flow["campaign_id"],
            decision_file=flow["decision_file"],
            campaign_db=data_dir / "paper_evaluation_campaign.db",
            data_dir=data_dir,
        )


def test_session_start_requires_binding_entry(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    campaign_db = data_dir / "paper_evaluation_campaign.db"
    with sqlite3.connect(campaign_db) as conn:
        conn.execute("DELETE FROM operational_campaign_decision_bindings")
        conn.commit()

    with pytest.raises(PaperOperationsError, match="campaign decision binding not found"):
        session_start(
            campaign_id=flow["campaign_id"],
            decision_file=flow["decision_file"],
            campaign_db=campaign_db,
            data_dir=data_dir,
        )


def test_session_start_blocks_tampered_binding_payload_json(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    campaign_db = data_dir / "paper_evaluation_campaign.db"
    with sqlite3.connect(campaign_db) as conn:
        row = conn.execute(
            "SELECT payload_json FROM operational_campaign_decision_bindings WHERE campaign_id = ?",
            (flow["campaign_id"],),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["payload_json"]["contract"]["symbol"] = "ETHUSDT"
        conn.execute(
            "UPDATE operational_campaign_decision_bindings SET payload_json = ? WHERE campaign_id = ?",
            (json.dumps(payload, ensure_ascii=False, sort_keys=True), flow["campaign_id"]),
        )
        conn.commit()

    with pytest.raises(PaperCampaignManifestError, match="payload hash mismatch"):
        session_start(
            campaign_id=flow["campaign_id"],
            decision_file=flow["decision_file"],
            campaign_db=campaign_db,
            data_dir=data_dir,
        )


def test_operational_campaign_binding_payload_hash_migrates_legacy_rows(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    campaign_db = flow["data_dir"] / "legacy_campaign_bindings.db"
    binding = paper_ops.load_operational_campaign_decision_binding(
        flow["data_dir"] / "paper_evaluation_campaign.db",
        campaign_id=flow["campaign_id"],
    )
    assert binding is not None
    _create_legacy_campaign_binding_db(campaign_db, binding)

    paper_ops.ensure_operational_paper_campaign_schema(campaign_db)
    migrated = paper_ops.load_operational_campaign_decision_binding(campaign_db, campaign_id=binding.campaign_id)
    assert migrated is not None
    assert migrated.binding_hash == binding.binding_hash
    assert migrated.payload_hash == paper_evaluation_hash(migrated.payload_json)
    with sqlite3.connect(campaign_db) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM operational_campaign_decision_bindings WHERE payload_hash IS NOT NULL AND payload_hash != ''",
        ).fetchone()
    assert row is not None
    assert row[0] == 1


def test_operational_campaign_binding_payload_mismatch_blocks_migration(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    campaign_db = flow["data_dir"] / "legacy_campaign_bindings_invalid.db"
    binding = paper_ops.load_operational_campaign_decision_binding(
        flow["data_dir"] / "paper_evaluation_campaign.db",
        campaign_id=flow["campaign_id"],
    )
    assert binding is not None
    _create_legacy_campaign_binding_db(
        campaign_db,
        binding,
        payload_mutator=lambda payload: {
            **payload,
            "payload_json": {
                **payload["payload_json"],
                "contract": {**payload["payload_json"]["contract"], "symbol": "ETHUSDT"},
            },
        },
    )

    with pytest.raises(PaperCampaignReadError, match="campaign decision binding payload mismatch"):
        paper_ops.ensure_operational_paper_campaign_schema(campaign_db)


def test_operational_campaign_binding_payload_hash_null_blocks_reading(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    campaign_db = flow["data_dir"] / "legacy_campaign_bindings_null.db"
    binding = paper_ops.load_operational_campaign_decision_binding(
        flow["data_dir"] / "paper_evaluation_campaign.db",
        campaign_id=flow["campaign_id"],
    )
    assert binding is not None
    _create_legacy_campaign_binding_db(campaign_db, binding)
    paper_ops.ensure_operational_paper_campaign_schema(campaign_db)
    with sqlite3.connect(campaign_db) as conn:
        conn.execute("UPDATE operational_campaign_decision_bindings SET payload_hash = NULL")
        conn.commit()

    with pytest.raises(PaperCampaignManifestError):
        paper_ops.load_operational_campaign_decision_binding(campaign_db, campaign_id=binding.campaign_id)


def test_operational_campaign_binding_migration_is_idempotent(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    campaign_db = flow["data_dir"] / "legacy_campaign_bindings_idempotent.db"
    binding = paper_ops.load_operational_campaign_decision_binding(
        flow["data_dir"] / "paper_evaluation_campaign.db",
        campaign_id=flow["campaign_id"],
    )
    assert binding is not None
    _create_legacy_campaign_binding_db(campaign_db, binding)

    paper_ops.ensure_operational_paper_campaign_schema(campaign_db)
    first = paper_ops.load_operational_campaign_decision_binding(campaign_db, campaign_id=binding.campaign_id)
    assert first is not None
    paper_ops.ensure_operational_paper_campaign_schema(campaign_db)
    second = paper_ops.load_operational_campaign_decision_binding(campaign_db, campaign_id=binding.campaign_id)
    assert second is not None
    assert first.as_dict() == second.as_dict()


def test_lock_malformed_blocks_and_requires_admin_recovery(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    lock_path = _lock_file_path(data_dir, scope=f"session_start:{flow['campaign_id']}")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(lock_path, {"pid": 999999, "scope": "session_start"})
    with pytest.raises(PaperOperationsError):
        session_start(
            campaign_id=flow["campaign_id"],
            decision_file=flow["decision_file"],
            campaign_db=data_dir / "paper_evaluation_campaign.db",
            data_dir=data_dir,
        )
    assert paper_operations_main(["lock", "recover", "--data-dir", str(data_dir), "--confirm"]) == 0
    assert not lock_path.exists()
    recovered = session_start(
        campaign_id=flow["campaign_id"],
        decision_file=flow["decision_file"],
        campaign_db=data_dir / "paper_evaluation_campaign.db",
        data_dir=data_dir,
    )
    assert recovered["session_id"]


def test_lock_blocks_live_process_and_recovers_stale_lock(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    lock_path = _lock_file_path(data_dir, scope=f"session_start:{flow['campaign_id']}")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    live_payload = {
        "operation": f"session_start:{flow['campaign_id']}",
        "scope": f"session_start:{flow['campaign_id']}",
        "pid": os.getpid(),
        "instance_id": "live-instance",
        "nonce": "live-nonce",
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    _write_json(lock_path, live_payload)
    with pytest.raises(PaperOperationsError):
        session_start(
            campaign_id=flow["campaign_id"],
            decision_file=flow["decision_file"],
            campaign_db=data_dir / "paper_evaluation_campaign.db",
            data_dir=data_dir,
        )
    stale_payload = dict(live_payload)
    stale_payload["pid"] = 999999
    stale_payload["instance_id"] = "stale-instance"
    _write_json(lock_path, stale_payload)
    assert paper_operations_main(["lock", "recover", "--data-dir", str(data_dir), "--confirm"]) == 0
    recovered = session_start(
        campaign_id=flow["campaign_id"],
        decision_file=flow["decision_file"],
        campaign_db=data_dir / "paper_evaluation_campaign.db",
        data_dir=data_dir,
    )
    assert recovered["session_id"]


def test_backup_manifest_and_restore_apply_hardened(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    backup = backup_create(data_dir=data_dir, backup_name="valid-backup")
    manifest_path = Path(backup["backup_dir"]) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["data_dir"] == data_dir.name
    assert set(manifest["files"]) == {"trades.db", "paper_runtime.db", "paper_evaluation_campaign.db", "paper_evaluation_reference.db"}

    empty_manifest_backup = Path(backup["backup_dir"]) / "empty"
    empty_manifest_backup.mkdir()
    _write_json(empty_manifest_backup / "manifest.json", {})
    with pytest.raises(PaperOperationsError):
        backup_verify(backup_dir=empty_manifest_backup)

    traversal_name = "../escape"
    with pytest.raises(PaperOperationsError):
        backup_create(data_dir=data_dir, backup_name=traversal_name)
    with pytest.raises(PaperOperationsError):
        backup_create(data_dir=data_dir, backup_name=str(Path.cwd()))

    restored = restore_apply(backup_dir=backup["backup_dir"], data_dir=data_dir, confirm=True)
    assert restored["restored_from"] == "valid-backup"


def test_backup_retention_keeps_latest_valid_backups(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    names = []
    for index in range(8):
        name = f"backup-{index:02d}"
        names.append(backup_create(data_dir=data_dir, backup_name=name)["backup_dir"])
    backups = backup_list(data_dir=data_dir)["backups"]
    assert len(backups) <= 7
    assert "backup-00" not in backups


def test_doctor_requires_backup_and_restore_verify_and_report_includes_activity(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    backup = backup_create(data_dir=data_dir, backup_name="doctor-backup")
    restore_verify(backup_dir=backup["backup_dir"])
    doctor_report = doctor(data_dir=data_dir)
    assert doctor_report["status"] == "READY"
    assert doctor_report["local_operations_ready"] is True

    report_result = report(data_dir=data_dir, campaign_id=flow["campaign_id"], session_id=None)
    assert report_result["doctor"]["local_operations_ready"] is True
    assert report_result["operational_summary"]["sessions_observed"] == 0
    assert report_result["activity"]["open_positions"] >= 0
    assert report_result["activity"]["closed_trades"] >= 0
    assert report_result["activity"]["distinct_days"] >= 0
    assert report_result["activity"]["outbox_pending"] >= 0
    assert report_result["last_restore_verify"]["verified"] is True


def test_cli_rejects_temporary_paths_and_missing_status(tmp_path, monkeypatch, sample_btc_data, capsys):
    monkeypatch.setattr("paper_operations._ALLOW_TEMPORARY_DATA_DIRS_FOR_TESTS", False)
    exit_code = paper_operations_main(["--data-dir", str(tmp_path / "paper_data"), "doctor"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "temporary directory" in captured.err or "error:" in captured.err

    monkeypatch.setattr("paper_operations.PAPER_DATA_DIR", str(tmp_path / "paper_data_env"))
    exit_code = paper_operations_main(["doctor"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "temporary directory" in captured.err or "error:" in captured.err

    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    bad_decision = tmp_path / "bad_decision_cli.json"
    payload = json.loads(flow["decision_file"].read_text(encoding="utf-8"))
    payload.pop("status", None)
    _write_json(bad_decision, payload)
    exit_code = paper_operations_main([
        "session",
        "start",
        "--campaign-id",
        flow["campaign_id"],
        "--decision-file",
        str(bad_decision),
        "--campaign-db",
        str(flow["data_dir"] / "paper_evaluation_campaign.db"),
        "--data-dir",
        str(flow["data_dir"]),
    ])
    assert exit_code == 1


def test_report_uses_selected_database_for_decision_logs(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    db_a = data_dir / "trades.db"
    db_b = tmp_path / "other" / "trades.db"
    db_b.parent.mkdir(parents=True, exist_ok=True)
    _seed_decision_log(db_a, modo="PAPER_SOL", decisao="AGUARDAR", symbol="BTCUSDT")
    _seed_decision_log(db_b, modo="PAPER_SOL", decisao="BLOQUEADO", symbol="ETHUSDT")

    captured: dict[str, object] = {}
    original = storage.buscar_ultimos_decision_logs

    def wrapped(*args, **kwargs):
        captured["db_name"] = kwargs.get("db_name")
        captured["strict"] = kwargs.get("strict")
        return original(*args, **kwargs)

    monkeypatch.setattr(storage, "buscar_ultimos_decision_logs", wrapped)
    report_result = report(data_dir=data_dir, campaign_id=flow["campaign_id"], session_id=None)
    assert captured["db_name"] == str(db_a)
    assert captured["strict"] is True
    assert "operational_summary" in report_result


def test_backup_verify_is_read_only(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    backup = backup_create(data_dir=data_dir, backup_name="readonly-backup")
    backup_dir = Path(backup["backup_dir"])
    before = {path.name: _sha256_file(path) for path in backup_dir.iterdir() if path.is_file()}

    verified = backup_verify(backup_dir=backup["backup_dir"])
    assert verified["verified"] is True
    after = {path.name: _sha256_file(path) for path in backup_dir.iterdir() if path.is_file()}
    assert after == before


def test_backup_retention_ignores_corrupted_backups(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    for index in range(6):
        backup_create(data_dir=data_dir, backup_name=f"backup-{index:02d}")
    corrupted = Path(backup_create(data_dir=data_dir, backup_name="backup-corrupted")["backup_dir"])
    (corrupted / "manifest.json").write_text("{", encoding="utf-8")
    backup_create(data_dir=data_dir, backup_name="backup-06")
    backups = backup_list(data_dir=data_dir)["backups"]
    assert "backup-00" in backups
    assert "backup-corrupted" in backups


def test_restore_apply_rolls_back_on_intermediate_failure(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    backup = backup_create(data_dir=data_dir, backup_name="rollback-backup")
    _seed_decision_log(data_dir / "trades.db", modo="PAPER_SOL", decisao="ERRO", symbol="BTCUSDT")
    before_trade_rows = _sqlite_table_rows(data_dir / "trades.db", "decision_logs")
    before_runtime_meta = _sqlite_table_rows(data_dir / "paper_runtime.db", "paper_runtime_meta")
    before_runtime_contracts = _sqlite_table_rows(data_dir / "paper_runtime.db", "paper_evaluation_cohort_contracts")
    before_runtime_counts = {
        table: _sqlite_table_count(data_dir / "paper_runtime.db", table)
        for table in ("paper_runtime_events", "paper_runtime_idempotency", "paper_runtime_sessions", "paper_runtime_snapshots")
    }
    before_campaign_contracts = _sqlite_table_rows(data_dir / "paper_evaluation_campaign.db", "paper_evaluation_campaign_contracts")
    before_campaign_reports = _sqlite_table_rows(data_dir / "paper_evaluation_campaign.db", "paper_evaluation_campaign_reports")
    calls = {"count": 0}
    original_restore = paper_ops._restore_sqlite_file

    def failing_restore(source, target):
        calls["count"] += 1
        if calls["count"] == 2:
            raise PaperOperationsError("forced restore failure")
        return original_restore(source, target)

    monkeypatch.setattr(paper_ops, "_restore_sqlite_file", failing_restore)
    with pytest.raises(PaperOperationsError):
        restore_apply(backup_dir=backup["backup_dir"], data_dir=data_dir, confirm=True)
    assert _sqlite_table_rows(data_dir / "trades.db", "decision_logs") == before_trade_rows
    assert _sqlite_table_rows(data_dir / "paper_runtime.db", "paper_runtime_meta") == before_runtime_meta
    assert _sqlite_table_rows(data_dir / "paper_runtime.db", "paper_evaluation_cohort_contracts") == before_runtime_contracts
    assert {
        table: _sqlite_table_count(data_dir / "paper_runtime.db", table)
        for table in ("paper_runtime_events", "paper_runtime_idempotency", "paper_runtime_sessions", "paper_runtime_snapshots")
    } == before_runtime_counts
    assert _sqlite_table_rows(data_dir / "paper_evaluation_campaign.db", "paper_evaluation_campaign_contracts") == before_campaign_contracts
    assert _sqlite_table_rows(data_dir / "paper_evaluation_campaign.db", "paper_evaluation_campaign_reports") == before_campaign_reports


def test_restore_apply_recovery_required_and_restore_recover_restores_snapshot(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    backup = backup_create(data_dir=data_dir, backup_name="recovery-backup")
    before_trade_rows = _sqlite_table_rows(data_dir / "trades.db", "decision_logs")
    before_runtime_rows = _sqlite_table_rows(data_dir / "paper_runtime.db", "paper_runtime_sessions")
    before_campaign_rows = _sqlite_table_rows(data_dir / "paper_evaluation_campaign.db", "paper_evaluation_campaign_contracts")
    calls = {"count": 0}
    original_restore = paper_ops._restore_sqlite_file

    def fail_during_rollback(source, target):
        calls["count"] += 1
        if calls["count"] >= 2:
            raise PaperOperationsError("forced rollback failure")
        return original_restore(source, target)

    monkeypatch.setattr(paper_ops, "_restore_sqlite_file", fail_during_rollback)
    with pytest.raises(PaperOperationsError, match="restore rollback failed"):
        restore_apply(backup_dir=backup["backup_dir"], data_dir=data_dir, confirm=True)

    marker_state = paper_ops._load_restore_recovery_state(paper_ops._paths(data_dir))
    assert marker_state is not None
    assert marker_state["status"] == "RECOVERY_REQUIRED"
    assert _sqlite_table_rows(data_dir / "trades.db", "decision_logs") == before_trade_rows
    assert _sqlite_table_rows(data_dir / "paper_runtime.db", "paper_runtime_sessions") == before_runtime_rows
    assert _sqlite_table_rows(data_dir / "paper_evaluation_campaign.db", "paper_evaluation_campaign_contracts") == before_campaign_rows

    with pytest.raises(PaperOperationsError, match="restore recovery required"):
        session_start(
            campaign_id=flow["campaign_id"],
            decision_file=flow["decision_file"],
            campaign_db=data_dir / "paper_evaluation_campaign.db",
            data_dir=data_dir,
        )

    monkeypatch.setattr(paper_ops, "_restore_sqlite_file", original_restore)
    recovered = restore_recover(data_dir=data_dir, confirm=True)
    assert recovered["status"] == "RECOVERED"
    assert paper_ops._load_restore_recovery_state(paper_ops._paths(data_dir)) is None


def test_restore_verify_receipt_expires_and_blocks_doctor(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_test_only_local_operations_fixture(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    backup = backup_create(data_dir=data_dir, backup_name="expiry-backup")
    receipt = restore_verify(backup_dir=backup["backup_dir"])
    assert receipt["verified"] is True
    expires_at = datetime.fromisoformat(receipt["expires_at_utc"].replace("Z", "+00:00"))
    monkeypatch.setattr(paper_ops, "_utcnow", lambda: expires_at + timedelta(minutes=1))
    doctor_report = doctor(data_dir=data_dir)
    assert doctor_report["status"] == "NOT_READY"
    assert doctor_report["local_operations_ready"] is False
    assert "recent restore verification unavailable." in doctor_report["local_issues"]


def test_storage_decision_logs_use_explicit_db_name_and_strict(tmp_path):
    db_a = tmp_path / "paper_data_a" / "trades.db"
    db_b = tmp_path / "paper_data_b" / "trades.db"
    db_a.parent.mkdir(parents=True, exist_ok=True)
    db_b.parent.mkdir(parents=True, exist_ok=True)
    _seed_decision_log(db_a, modo="PAPER_SOL", decisao="AGUARDAR", symbol="BTCUSDT")
    _seed_decision_log(db_b, modo="VIGIA_BTC", decisao="BLOQUEADO", symbol="ETHUSDT")

    logs_a = storage.buscar_ultimos_decision_logs(limite=5, db_name=str(db_a), strict=True)
    logs_b = storage.buscar_ultimos_decision_logs(limite=5, db_name=str(db_b), strict=True)

    assert logs_a[0]["symbol"] == "BTCUSDT"
    assert logs_b[0]["symbol"] == "ETHUSDT"
    assert logs_a[0]["modo"] == "PAPER_SOL"
    assert logs_b[0]["modo"] == "VIGIA_BTC"
