from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

import paper_evaluation.campaign as campaign_module
from paper_evaluation import (
    PaperCampaignManifestError,
    PaperCampaignPolicyError,
    PaperCampaignReadError,
    PaperEvaluationDecisionError,
    PaperEvaluationPolicy,
    PaperEvaluationStatus,
)
from paper_evaluation.campaign import (
    OperationalPaperCampaignContract,
    OperationalPaperCampaignState,
    build_parser,
    create_operational_paper_campaign,
    evaluate_operational_paper_campaign,
    get_operational_paper_campaign_status,
    load_operational_paper_campaign_contract,
    load_operational_paper_campaign_report,
)
from tests.test_paper_evaluation_phase8 import _decision, _lenient_policy, _seed_runtime_and_trades
from tests.test_promotion_phase6 import _promotion_result


def _campaign_policy() -> PaperEvaluationPolicy:
    return PaperEvaluationPolicy(
        min_sessions_completed=1,
        min_distinct_days=1,
        min_trades=1,
        min_duration_hours=Decimal("1"),
        max_drawdown_percent=Decimal("25"),
        min_profit_factor=Decimal("1"),
        min_expectancy=Decimal("0"),
        min_net_return_percent=Decimal("0"),
        max_total_costs_percent=Decimal("10"),
        max_suspended_sessions=0,
        require_zero_live_attempts=True,
        require_audit_chain=True,
        require_fresh_data=True,
        required_regimes=("BULL", "BEAR", "CHOP"),
        min_regime_coverage=3,
        evaluator_version="v8_paper_evaluation",
    )


def _campaign_kwargs(period_start: datetime, period_end: datetime) -> dict[str, object]:
    decision = _decision()
    return {
        "campaign_id": "campaign-8b",
        "cohort_hash": None,
        "strategy_version": decision.strategy_version,
        "symbol": decision.symbol,
        "interval": decision.interval,
        "inclusion_rule": "sqlite_all_sessions",
        "period_start_utc": period_start,
        "period_end_utc": period_end,
        "policy": _lenient_policy(),
        "reference_walk_forward": _promotion_result(),
        "evaluator_version": "v8_paper_evaluation",
    }


def test_campaign_prepare_status_and_reference_round_trip(tmp_path):
    runtime_db, _ = _seed_runtime_and_trades(tmp_path, session_id="campaign-prepare", trade_result=Decimal("25"))
    campaign_db = tmp_path / "campaign.db"
    period_start = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    period_end = period_start + timedelta(days=1)
    with pytest.raises(PaperCampaignManifestError):
        OperationalPaperCampaignContract(
            campaign_id="manual-contract",
            cohort_hash="cohort",
            strategy_version="v8_paper_evaluation",
            symbol="BTCUSDT",
            interval="1h",
            inclusion_rule="sqlite_all_sessions",
            period_start_utc=period_start,
            period_end_utc=period_end,
            policy_payload=_lenient_policy().as_dict(),
            policy_hash=_lenient_policy().policy_hash,
            walk_forward_manifest_hash=_promotion_result().manifest["manifest_hash"],
            walk_forward_result_hash=campaign_module.validation_manifest_hash(_promotion_result().as_dict()),
            evaluator_version="v8_paper_evaluation",
            created_at_utc=period_start - timedelta(minutes=1),
        )
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=1)):
        contract = create_operational_paper_campaign(
            **_campaign_kwargs(period_start, period_end),
            runtime_db_path=runtime_db,
            campaign_db_path=campaign_db,
        )
    assert contract.campaign_hash
    snapshot = get_operational_paper_campaign_status(
        campaign_id=contract.campaign_id,
        campaign_db_path=campaign_db,
        now=period_start - timedelta(minutes=1),
    )
    assert snapshot.campaign_state is OperationalPaperCampaignState.PREPARED
    round_tripped = campaign_module._walk_forward_from_payload(_promotion_result().as_dict())
    assert round_tripped.as_dict() == _promotion_result().as_dict()


def test_campaign_creation_requires_timezone_aware_window_and_before_start(tmp_path):
    runtime_db, _ = _seed_runtime_and_trades(tmp_path, session_id="campaign-window", trade_result=Decimal("25"))
    campaign_db = tmp_path / "campaign.db"
    period_start = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    period_end = period_start + timedelta(days=1)
    with pytest.raises(PaperCampaignManifestError):
        create_operational_paper_campaign(
            **_campaign_kwargs(period_start.replace(tzinfo=None), period_end),
            runtime_db_path=runtime_db,
            campaign_db_path=campaign_db,
        )
    with pytest.raises(PaperCampaignManifestError):
        create_operational_paper_campaign(
            **_campaign_kwargs(period_start, period_end),
            runtime_db_path=runtime_db,
            campaign_db_path=campaign_db,
        )
    with pytest.raises(PaperCampaignManifestError):
        create_operational_paper_campaign(
            **_campaign_kwargs(period_start, period_end),
            runtime_db_path=runtime_db,
            campaign_db_path=campaign_db,
        )


def test_campaign_duplicate_and_tampered_persistence_block(tmp_path):
    runtime_db, _ = _seed_runtime_and_trades(tmp_path, session_id="campaign-tamper", trade_result=Decimal("25"))
    campaign_db = tmp_path / "campaign.db"
    period_start = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    period_end = period_start + timedelta(days=1)
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=1)):
        contract = create_operational_paper_campaign(
            **_campaign_kwargs(period_start, period_end),
            runtime_db_path=runtime_db,
            campaign_db_path=campaign_db,
        )
    with pytest.raises(PaperCampaignManifestError):
        with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=1)):
            create_operational_paper_campaign(
                **_campaign_kwargs(period_start, period_end),
                runtime_db_path=runtime_db,
                campaign_db_path=campaign_db,
            )
    loaded = load_operational_paper_campaign_contract(campaign_db, campaign_id=contract.campaign_id)
    assert loaded.campaign_hash == contract.campaign_hash
    with sqlite3.connect(campaign_db) as conn:
        conn.execute(
            "UPDATE paper_evaluation_campaign_contracts SET payload_json = json_set(payload_json, '$.symbol', 'ETHUSDT') WHERE campaign_hash = ?",
            (contract.campaign_hash,),
        )
        conn.commit()
    with pytest.raises(PaperCampaignReadError):
        load_operational_paper_campaign_contract(campaign_db, campaign_hash=contract.campaign_hash)


def test_campaign_reference_validation_and_policy_mismatch_block(tmp_path):
    runtime_db, _ = _seed_runtime_and_trades(tmp_path, session_id="campaign-ref", trade_result=Decimal("25"))
    campaign_db = tmp_path / "campaign.db"
    period_start = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    period_end = period_start + timedelta(days=1)
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=1)):
        contract = create_operational_paper_campaign(
            **_campaign_kwargs(period_start, period_end),
            runtime_db_path=runtime_db,
            campaign_db_path=campaign_db,
        )
    with pytest.raises(PaperEvaluationDecisionError):
        evaluate_operational_paper_campaign(
            campaign_id=contract.campaign_id,
            campaign_db_path=campaign_db,
            runtime_db_path=runtime_db,
            trades_db_path=tmp_path / "trades.db",
            reference_walk_forward=_promotion_result().as_dict(),
            policy=_lenient_policy(),
            now=period_end + timedelta(hours=1),
        )
    bad_reference = replace(
        _promotion_result(),
        summary={**_promotion_result().summary, "runner_trusted": False},
        manifest={**_promotion_result().manifest, "runner_trusted": False},
    )
    with pytest.raises(PaperEvaluationDecisionError):
        evaluate_operational_paper_campaign(
            campaign_id=contract.campaign_id,
            campaign_db_path=campaign_db,
            runtime_db_path=runtime_db,
            trades_db_path=tmp_path / "trades.db",
            reference_walk_forward=bad_reference,
            policy=_lenient_policy(),
            now=period_end + timedelta(hours=1),
        )
    with pytest.raises(PaperCampaignPolicyError):
        evaluate_operational_paper_campaign(
            campaign_id=contract.campaign_id,
            campaign_db_path=campaign_db,
            runtime_db_path=runtime_db,
            trades_db_path=tmp_path / "trades.db",
            reference_walk_forward=_promotion_result(),
            policy=PaperEvaluationPolicy(
                min_sessions_completed=1,
                min_distinct_days=1,
                min_trades=1,
                min_duration_hours=Decimal("1"),
                max_drawdown_percent=Decimal("25"),
                min_profit_factor=Decimal("1"),
                min_expectancy=Decimal("0"),
                min_net_return_percent=Decimal("0"),
                max_total_costs_percent=Decimal("10"),
                max_suspended_sessions=0,
                require_zero_live_attempts=True,
                require_audit_chain=True,
                require_fresh_data=True,
                required_regimes=("BULL", "BEAR", "CHOP"),
                min_regime_coverage=3,
                evaluator_version="changed",
            ),
            now=period_end + timedelta(hours=1),
        )


def test_campaign_evaluation_before_end_is_not_final_and_after_end_is_idempotent(tmp_path):
    runtime_db, _ = _seed_runtime_and_trades(tmp_path, session_id="campaign-idempotent", trade_result=Decimal("25"))
    campaign_db = tmp_path / "campaign.db"
    period_start = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    period_end = period_start + timedelta(days=1)
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=1)):
        contract = create_operational_paper_campaign(
            **_campaign_kwargs(period_start, period_end),
            runtime_db_path=runtime_db,
            campaign_db_path=campaign_db,
        )
    pre = evaluate_operational_paper_campaign(
        campaign_id=contract.campaign_id,
        campaign_db_path=campaign_db,
        runtime_db_path=runtime_db,
        trades_db_path=tmp_path / "trades.db",
        policy=_lenient_policy(),
        reference_walk_forward=_promotion_result(),
        now=period_start + timedelta(hours=12),
    )
    assert pre.campaign_state is OperationalPaperCampaignState.RUNNING
    assert pre.decision_status is PaperEvaluationStatus.INSUFFICIENT_EVIDENCE
    post = evaluate_operational_paper_campaign(
        campaign_id=contract.campaign_id,
        campaign_db_path=campaign_db,
        runtime_db_path=runtime_db,
        trades_db_path=tmp_path / "trades.db",
        policy=_lenient_policy(),
        reference_walk_forward=_promotion_result(),
        now=period_end + timedelta(hours=2),
    )
    again = evaluate_operational_paper_campaign(
        campaign_id=contract.campaign_id,
        campaign_db_path=campaign_db,
        runtime_db_path=runtime_db,
        trades_db_path=tmp_path / "trades.db",
        policy=_lenient_policy(),
        reference_walk_forward=_promotion_result(),
        now=period_end + timedelta(hours=3),
    )
    assert again.report_hash == post.report_hash
    assert again.as_dict() == post.as_dict()
    persisted = load_operational_paper_campaign_report(campaign_db, campaign_hash=contract.campaign_hash)
    assert persisted is not None
    assert persisted.report_hash == post.report_hash


def test_campaign_cli_help_and_sanitized_source():
    help_text = build_parser().format_help()
    assert "prepare" in help_text
    assert "status" in help_text
    assert "evaluate" in help_text
    assert "--live" not in help_text
    source = Path("paper_evaluation/campaign.py").read_text(encoding="utf-8").lower()
    forbidden = ("requests", "httpx", "create_order", "send_order", "api_key", "secret", "telegram", "websocket", "subprocess", "approved_for_live")
    for token in forbidden:
        assert token not in source
