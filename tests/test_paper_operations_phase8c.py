from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from domain.serialization import serialize_value
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
    restore_verify,
    runtime_resume,
    session_complete,
    session_start,
    session_status,
    PaperOperationsError,
)
from paper_runtime.errors import PaperRuntimeSessionError
from promotion import PromotionPolicy, PromotionStatus
from domain import DataSource, Direction, Signal
from backtesting import BacktestConfig, LeakFreeBacktestEngine
from validation import CandidateConfig, SelectionCriteria, ValidationSplitConfig, WalkForwardValidator
from validation import TrustedLeakFreeBacktestRunner
from validation.artifacts import manifest_hash as validation_manifest_hash

from tests.test_promotion_phase6 import _promotion_result


def _write_json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(serialize_value(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _enable_operational_tmp_dirs(monkeypatch) -> None:
    monkeypatch.setattr("paper_operations._ALLOW_TEMPORARY_DATA_DIRS_FOR_TESTS", True)


def _trusted_walk_forward_envelope(tmp_path: Path, sample_btc_data):
    result = _promotion_result()
    envelope = {
        "operational_provenance": {
            "version": 1,
            "synthetic_test_data": False,
            "manifest_hash": result.manifest["manifest_hash"],
            "result_hash": validation_manifest_hash(result.as_dict()),
            "data_signature_hash": result.manifest["data_signature"]["content_hash"],
        },
        "walk_forward": result.as_dict(),
    }
    input_path = tmp_path / "trusted_walk_forward_input.json"
    _write_json(input_path, envelope)
    return input_path, result


def _prepare_full_operational_flow(tmp_path: Path, monkeypatch, sample_btc_data):
    _enable_operational_tmp_dirs(monkeypatch)
    monkeypatch.setattr("paper_operations.live_trading_permitted", lambda: False)
    monkeypatch.setattr("paper_operations.validate_component_config", lambda component: (True, []))
    data_dir = tmp_path / "paper_data"
    initialize(data_dir=data_dir)

    reference_input, real_result = _trusted_walk_forward_envelope(tmp_path, sample_btc_data)
    reference_output = data_dir / "reference.json"
    phase5_reference(input_file=reference_input, output_file=reference_output)

    policy_file = tmp_path / "promotion_policy.json"
    _write_json(policy_file, PromotionPolicy().as_dict())
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
        "real_result": real_result,
    }


def test_operational_data_dir_rejects_temporary_paths_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr("paper_operations._ALLOW_TEMPORARY_DATA_DIRS_FOR_TESTS", False)
    with pytest.raises(ValueError, match="temporary directory"):
        _data_dir(tmp_path / "paper_data")


def test_phase5_reference_rejects_synthetic_fixture(tmp_path):
    synthetic_reference = tmp_path / "synthetic_reference.json"
    _write_json(synthetic_reference, _promotion_result().as_dict())
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
    assert backup["files"] == ["paper_evaluation_campaign.db", "paper_runtime.db", "trades.db"]
    assert backup_list(data_dir=data_dir)["backups"] == ["test-backup"]

    restore = restore_verify(backup_dir=backup["backup_dir"])
    assert restore["verified"] is True
    assert restore["backup_dir"] == "test-backup"
    assert restore["files"] == ["paper_evaluation_campaign.db", "paper_runtime.db", "trades.db"]
    assert "paper_restore_verify_" not in json.dumps(restore)

    applied = restore_apply(backup_dir=backup["backup_dir"], data_dir=data_dir, confirm=True)
    assert applied["restored_from"] == "test-backup"

    doctor_report = doctor(data_dir=data_dir)
    assert doctor_report["status"] == "READY"

    report_result = report(data_dir=data_dir, campaign_id=flow["campaign_id"], session_id=session["session_id"])
    assert report_result["doctor"]["status"] == "READY"
    assert report_result["campaign"]["campaign_id"] == flow["campaign_id"]
    assert report_result["session"]["session_id"] == session["session_id"]
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


def test_lock_blocks_live_process_and_recovers_stale_lock(tmp_path, monkeypatch, sample_btc_data):
    flow = _prepare_full_operational_flow(tmp_path, monkeypatch, sample_btc_data)
    data_dir = flow["data_dir"]
    lock_path = _lock_file_path(data_dir, scope=f"session_start:{flow['campaign_id']}")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(lock_path, {"pid": os.getpid(), "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "scope": f"session_start:{flow['campaign_id']}"})
    with pytest.raises(PaperOperationsError):
        session_start(
            campaign_id=flow["campaign_id"],
            decision_file=flow["decision_file"],
            campaign_db=data_dir / "paper_evaluation_campaign.db",
            data_dir=data_dir,
        )
    _write_json(lock_path, {"pid": 999999, "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "scope": f"session_start:{flow['campaign_id']}"})
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
    assert set(manifest["files"]) == {"trades.db", "paper_runtime.db", "paper_evaluation_campaign.db"}

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

    report_result = report(data_dir=data_dir, campaign_id=flow["campaign_id"], session_id=None)
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
