from __future__ import annotations

import json
import hashlib
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

import decisor
import paper_operations as paper_ops
from domain import Candle
from domain.serialization import serialize_value
from market_data import MarketDataPackage, candles_to_market_snapshot
from paper_evaluation import PaperEvaluationPolicy
from paper_operations import (
    _ALLOW_TEMPORARY_DATA_DIRS_FOR_TESTS,
    _data_dir,
    _lock_file_path,
    backup_create,
    backup_list,
    backup_verify,
    campaign_prepare,
    cohort_prepare,
    doctor,
    initialize,
    main as paper_operations_main,
    phase5_reference,
    promotion_decision,
    report,
    restore_apply,
    restore_recover,
    restore_verify,
    runtime_resume,
    session_complete,
    session_start,
    session_status,
    PaperOperationsError,
)
from paper_runtime.errors import PaperRuntimeSessionError
from promotion import PromotionPolicy, PromotionStatus
import storage


def _write_json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(serialize_value(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _enable_operational_tmp_dirs(monkeypatch) -> None:
    monkeypatch.setattr("paper_operations._ALLOW_TEMPORARY_DATA_DIRS_FOR_TESTS", True)


def _operational_reference_package(frame: pd.DataFrame, *, symbol: str = "BTCUSDT", interval: str = "1h") -> MarketDataPackage:
    candles = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for idx, row in frame.reset_index(drop=True).iterrows():
        open_time = start + timedelta(hours=idx)
        close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
        candle = Candle.from_dict(
            {
                "open_time": open_time.isoformat().replace("+00:00", "Z"),
                "close_time": close_time.isoformat().replace("+00:00", "Z"),
                "open": str(row["open"]),
                "high": str(row["high"]),
                "low": str(row["low"]),
                "close": str(row["close"]),
                "volume": str(row["volume"]),
                "symbol": symbol,
                "interval": interval,
                "source": "BINANCE",
            }
        )
        candles.append(candle)
    candles_tuple = tuple(candles)
    snapshot = candles_to_market_snapshot(candles_tuple)
    now = datetime.now(timezone.utc)
    return MarketDataPackage(
        symbol=symbol,
        interval=interval,
        candles=candles_tuple,
        snapshot=snapshot,
        source=snapshot.source.value if hasattr(snapshot.source, "value") else str(snapshot.source),
        fetched_at=now,
        expires_at=now + timedelta(minutes=5),
        cache_status="miss",
    )


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


def _mock_operational_market_data(monkeypatch, frame: pd.DataFrame) -> MarketDataPackage:
    package = _operational_reference_package(_operational_reference_frame())
    monkeypatch.setattr(
        paper_ops.trusted_market_data_service,
        "fetch",
        lambda symbol="BTCUSDT", interval="1h", limit=500: package,
    )
    return package


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


def _prepare_full_operational_flow(tmp_path: Path, monkeypatch, sample_btc_data):
    _enable_operational_tmp_dirs(monkeypatch)
    monkeypatch.setattr("paper_operations.live_trading_permitted", lambda: False)
    monkeypatch.setattr(decisor, "obter_funding_rate", lambda symbol="BTCUSDT": None)
    monkeypatch.setattr(decisor, "log_decisao", lambda *args, **kwargs: None)
    data_dir = tmp_path / "paper_data"
    initialize(data_dir=data_dir)

    _mock_operational_market_data(monkeypatch, sample_btc_data)
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
    phase5_reference(input_file=reference_input, output_file=reference_output)

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
    decision_file = tmp_path / "promotion_decision.json"
    decision = promotion_decision(reference_file=reference_output, policy_file=policy_file, output_file=decision_file)
    assert decision["status"] == PromotionStatus.APPROVED_FOR_MONITORED_PAPER.value

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
    return {
        "data_dir": data_dir,
        "reference_output": reference_output,
        "decision_file": decision_file,
        "campaign_id": campaign["campaign_id"],
    }


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


def test_phase8c_full_local_operations_flow_uses_real_reference_and_sanitized_reports(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]

    session = session_start(
        campaign_id=flow["campaign_id"],
        decision_file=flow["decision_file"],
        campaign_db=data_dir / "paper_evaluation_campaign.db",
        data_dir=data_dir,
    )
    assert session["session_id"]
    assert session["state"] == "RUNNING"

    session_info = session_status(session_id=session["session_id"], data_dir=data_dir)
    assert session_info["session_id"] == session["session_id"]
    assert session_info["state"] == "RUNNING"

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


def test_promotion_decision_requires_status_and_session_start_fails_closed(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
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
    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
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


def test_lock_malformed_blocks_and_requires_admin_recovery(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
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
    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
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
    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
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
    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    names = []
    for index in range(8):
        name = f"backup-{index:02d}"
        names.append(backup_create(data_dir=data_dir, backup_name=name)["backup_dir"])
    backups = backup_list(data_dir=data_dir)["backups"]
    assert len(backups) <= 7
    assert "backup-00" not in backups


def test_doctor_requires_backup_and_restore_verify_and_report_includes_activity(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    backup = backup_create(data_dir=data_dir, backup_name="doctor-backup")
    restore_verify(backup_dir=backup["backup_dir"])
    doctor_report = doctor(data_dir=data_dir)
    assert doctor_report["status"] == "READY"
    assert doctor_report["local_operations_ready"] is True

    report_result = report(data_dir=data_dir, campaign_id=flow["campaign_id"], session_id=None)
    assert report_result["doctor"]["local_operations_ready"] is True
    assert report_result["operational_summary"]["sessions_observed"] >= 1
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

    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
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
    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
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
    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    backup = backup_create(data_dir=data_dir, backup_name="readonly-backup")
    backup_dir = Path(backup["backup_dir"])
    before = {path.name: _sha256_file(path) for path in backup_dir.iterdir() if path.is_file()}

    verified = backup_verify(backup_dir=backup["backup_dir"])
    assert verified["verified"] is True
    after = {path.name: _sha256_file(path) for path in backup_dir.iterdir() if path.is_file()}
    assert after == before


def test_backup_retention_ignores_corrupted_backups(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
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
    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
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
    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
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
    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
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
