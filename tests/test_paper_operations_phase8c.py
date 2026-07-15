from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from domain.serialization import serialize_value
from paper_operations import (
    backup_create,
    backup_list,
    backup_verify,
    campaign_prepare,
    doctor,
    initialize,
    main as paper_operations_main,
    phase5_reference,
    promotion_decision,
    report,
    restore_verify,
    runtime_resume,
    session_complete,
    session_start,
    session_status,
    cohort_prepare,
)
from paper_evaluation import PaperEvaluationPolicy
from promotion import PromotionPolicy, PromotionStatus

from tests.test_promotion_phase6 import _promotion_result


def _write_json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(serialize_value(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _trusted_reference_result():
    return _promotion_result(
        total_trades=30,
        net_return_percent="8",
        expectancy="2",
        profit_factor="1.40",
        drawdown_max_percent="4",
    )


def test_phase8c_local_operations_flow_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr("paper_operations.live_trading_permitted", lambda: False)
    monkeypatch.setattr("paper_operations.validate_component_config", lambda component: (True, []))
    monkeypatch.setattr("config.PAPER_DATA_DIR", str(tmp_path / "paper_data"))

    data_dir = tmp_path / "paper_data"
    initialize_result = initialize(data_dir=data_dir)
    assert Path(initialize_result["data_dir"]).exists()
    assert (data_dir / "trades.db").exists()
    assert (data_dir / "paper_runtime.db").exists()
    assert (data_dir / "paper_evaluation_campaign.db").exists()

    reference_source = tmp_path / "reference_source.json"
    reference_file = data_dir / "reference.json"
    promotion_policy_file = tmp_path / "promotion_policy.json"
    campaign_policy_file = tmp_path / "campaign_policy.json"
    decision_file = tmp_path / "promotion_decision.json"
    campaign_id = "campaign-phase8c"

    _write_json(reference_source, _trusted_reference_result().as_dict())
    _write_json(promotion_policy_file, PromotionPolicy().as_dict())
    _write_json(campaign_policy_file, PaperEvaluationPolicy().as_dict())

    phase5_result = phase5_reference(input_file=reference_source, output_file=reference_file)
    assert Path(phase5_result["output"]).exists()
    assert phase5_result["runner_trusted"] is True

    decision_result = promotion_decision(reference_file=reference_file, policy_file=promotion_policy_file, output_file=decision_file)
    assert decision_result["status"] == PromotionStatus.APPROVED_FOR_MONITORED_PAPER.value

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
    assert cohort["cohort_hash"]

    campaign = campaign_prepare(
        campaign_id=campaign_id,
        policy_file=campaign_policy_file,
        reference_file=reference_file,
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
    assert campaign["campaign_id"] == campaign_id
    assert campaign["campaign_hash"]

    session = session_start(
        campaign_id=campaign_id,
        decision_file=decision_file,
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
    assert "trades.db" in backup["files"]
    assert backup_list(data_dir=data_dir)["backups"] == ["test-backup"]
    assert backup_verify(backup_dir=backup["backup_dir"])["verified"] is True
    assert restore_verify(backup_dir=backup["backup_dir"])["verified"] is True

    doctor_report = doctor(data_dir=data_dir)
    assert doctor_report["status"] == "READY"

    report_result = report(data_dir=data_dir, campaign_id=campaign_id, session_id=session["session_id"])
    assert report_result["doctor"]["status"] == "READY"
    assert report_result["campaign"]["campaign_id"] == campaign_id
    assert report_result["session"]["session_id"] == session["session_id"]


def test_paper_operations_main_rejects_invalid_files(tmp_path, capsys):
    bad_reference = tmp_path / "bad_reference.json"
    bad_reference.write_text("{not json}", encoding="utf-8")
    policy_file = tmp_path / "policy.json"
    _write_json(policy_file, PromotionPolicy().as_dict())

    exit_code = paper_operations_main([
        "phase5-reference",
        "--input",
        str(bad_reference),
        "--output",
        str(tmp_path / "reference.json"),
    ])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "invalid JSON" in captured.err

    exit_code = paper_operations_main([
        "promotion-decision",
        "--reference-file",
        str(tmp_path / "missing_reference.json"),
        "--policy-file",
        str(policy_file),
    ])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "not found" in captured.err


def test_doctor_reports_not_ready_without_initialize(tmp_path, monkeypatch):
    monkeypatch.setattr("paper_operations.live_trading_permitted", lambda: False)
    monkeypatch.setattr("paper_operations.validate_component_config", lambda component: (True, []))
    report_result = doctor(data_dir=tmp_path / "missing")
    assert report_result["status"] == "NOT_READY"
    assert any("PAPER_DATA_DIR" in issue or "operational" in issue for issue in report_result["issues"])
