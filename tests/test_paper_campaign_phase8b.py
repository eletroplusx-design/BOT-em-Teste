from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import paper_evaluation.campaign as campaign_module
import paper_evaluation.evidence as evidence_module
import paper_evaluation._operational as operational_module
from paper_evaluation import (
    PaperCampaignManifestError,
    PaperCampaignPolicyError,
    PaperEvaluationEvidenceError,
    PaperEvaluationPolicy,
    PaperEvaluationStatus,
)
from paper_evaluation.campaign import (
    build_parser,
    create_operational_paper_campaign,
    evaluate_operational_paper_campaign,
    get_operational_paper_campaign_status,
    load_operational_paper_campaign_contract,
    load_operational_paper_campaign_report,
    main,
)
from paper_runtime import PaperRuntimeSession, PaperRuntimeStore
from paper_evaluation._operational import persist_operational_cohort_contract
from storage import finalizar_trade_paper, registrar_trade_paper
from tests.test_paper_evaluation_phase8 import _decision, _seed_runtime_and_trades
from tests.test_paper_evaluation_phase8 import _snapshot
from tests.test_promotion_phase6 import _promotion_result


def _operational_policy() -> PaperEvaluationPolicy:
    return PaperEvaluationPolicy(
        min_sessions_completed=10,
        min_distinct_days=20,
        min_trades=100,
        min_duration_hours=Decimal("480"),
        max_drawdown_percent=Decimal("15"),
        min_profit_factor=Decimal("1.10"),
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


def _session_trade_result(session_index: int, trade_index: int) -> Decimal:
    if trade_index % 5 == 4:
        return Decimal("-2")
    return Decimal("12") + Decimal(session_index % 3)


def _seed_operational_campaign_runtime(
    tmp_path: Path,
    *,
    session_count: int = 20,
    trades_per_session: int = 5,
) -> tuple[Path, Path, datetime, datetime, dict[str, object]]:
    runtime_db = tmp_path / "runtime.db"
    trades_db = tmp_path / "trades.db"
    decision = _decision()
    runtime_store = PaperRuntimeStore(runtime_db)
    base_start = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=session_count + 5)
    period_end = base_start + timedelta(days=session_count)
    with patch.object(operational_module, "_utcnow", return_value=base_start - timedelta(hours=1)):
        persist_operational_cohort_contract(
            runtime_db,
            strategy_version=decision.strategy_version,
            symbol=decision.symbol,
            interval=decision.interval,
            inclusion_rule="sqlite_all_sessions",
            period_start_utc=base_start,
            period_end_utc=period_end,
        )

    for idx in range(session_count):
        session_id = f"campaign-session-{idx:02d}"
        started = base_start + timedelta(days=idx)
        regime = ("BULL", "BEAR", "CHOP")[idx % 3]
        session_decision = replace(
            decision,
            frozen_selection=replace(
                decision.frozen_selection,
                execution_contract=tuple({**dict(decision.phase5_manifest["execution_contract"]), "regime": regime}.items()),
            ),
        )
        runtime_session = PaperRuntimeSession.create_from_decision(
            session_decision,
            session_id=session_id,
            session_started_utc=started,
            store=runtime_store,
        )
        snapshot = _snapshot(
            session_id,
            started,
            started + timedelta(hours=1),
            current_loss_streak=0,
            executed_trades=trades_per_session,
            open_positions=0,
            paper_capital_used=Decimal("1000") + Decimal(idx),
            risk_per_trade_percent=Decimal("0.5"),
            session_state="RUNNING",
            decision_hash=session_decision.decision_hash,
            evidence_hash=session_decision.evidence_hash,
            strategy_version=session_decision.strategy_version,
            configuration=session_decision.frozen_selection.as_dict(),
        )
        runtime_session.evaluate_snapshot(snapshot, decision=session_decision, idempotency_key=f"{session_id}:snapshot")
        for trade_index in range(trades_per_session):
            lucro_reais = _session_trade_result(idx, trade_index)
            opened = started + timedelta(minutes=5 + trade_index * 10)
            closed = opened + timedelta(minutes=15)
            entry_price = Decimal("100") + Decimal(idx) + Decimal(trade_index)
            exit_price = entry_price + lucro_reais
            trade_id = registrar_trade_paper(
                symbol=session_decision.symbol,
                direcao="COMPRA" if lucro_reais >= 0 else "VENDA",
                entrada=float(entry_price),
                stop_loss=float(entry_price - Decimal("5")),
                take_profit=float(entry_price + Decimal("10")),
                quantidade=1.0,
                valor_arriscado=100.0,
                rr_planejado=2.0,
                session_id=session_id,
                idempotency_key=f"{session_id}:open:{trade_index}",
                db_name=str(trades_db),
            )
            finalizar_trade_paper(
                trade_id,
                saida=float(exit_price),
                lucro_percent=float(lucro_reais),
                lucro_reais=float(lucro_reais),
                resultado="WIN" if lucro_reais >= 0 else "LOSS",
                motivo_saida="TP" if lucro_reais >= 0 else "SL",
                session_id=session_id,
                db_name=str(trades_db),
                pnl_bruto=float(lucro_reais + Decimal("1")),
                custos_totais=1.0,
                pnl_liquido=float(lucro_reais),
                exit_fee=0.4,
                entry_spread_cost=0.25,
                entry_slippage_cost=0.25,
                exit_spread_cost=0.25,
                exit_slippage_cost=0.25,
                spread_cost=0.5,
                slippage_cost=0.5,
                close_idempotency_key=f"{session_id}:close:{trade_index}",
            )
        runtime_session.complete("session complete", idempotency_key=f"{session_id}:complete")
    return runtime_db, trades_db, base_start, period_end, _promotion_result().as_dict()


def _write_json_file(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(campaign_module.serialize_value(payload), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def _campaign_kwargs(period_start: datetime, period_end: datetime, *, reference=None) -> dict[str, object]:
    reference = reference or _promotion_result()
    return {
        "campaign_id": "campaign-8b",
        "cohort_hash": None,
        "strategy_version": reference.summary["strategy_version"],
        "symbol": reference.summary["symbol"],
        "interval": reference.summary["interval"],
        "inclusion_rule": "sqlite_all_sessions",
        "period_start_utc": period_start,
        "period_end_utc": period_end,
        "policy": _operational_policy(),
        "reference_walk_forward": reference,
        "evaluator_version": "v8_paper_evaluation",
    }


def test_campaign_prepare_status_and_reference_round_trip(tmp_path):
    runtime_db, _, period_start, period_end, reference = _seed_operational_campaign_runtime(tmp_path, session_count=20, trades_per_session=5)
    campaign_db = tmp_path / "campaign.db"
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=2)):
        contract = create_operational_paper_campaign(
            **_campaign_kwargs(period_start, period_end),
            runtime_db_path=runtime_db,
            campaign_db_path=campaign_db,
        )
    assert contract.reference_payload_json["manifest"]["manifest_hash"] == reference["manifest"]["manifest_hash"]
    assert contract.reference_payload_json["manifest"]["runner_trusted"] is True
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(minutes=1)):
        snapshot = get_operational_paper_campaign_status(campaign_id=contract.campaign_id, campaign_db_path=campaign_db)
    assert snapshot.campaign_state.value == "PREPARED"
    round_tripped = campaign_module._walk_forward_from_payload(reference)
    assert round_tripped.as_dict() == reference


def test_campaign_public_clock_and_cli_flags_are_blocked(tmp_path):
    runtime_db, _, period_start, period_end, _ = _seed_operational_campaign_runtime(tmp_path, session_count=20, trades_per_session=5)
    campaign_db = tmp_path / "campaign.db"
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=2)):
        contract = create_operational_paper_campaign(
            **_campaign_kwargs(period_start, period_end),
            runtime_db_path=runtime_db,
            campaign_db_path=campaign_db,
        )
    with pytest.raises(TypeError):
        evaluate_operational_paper_campaign(
            campaign_id=contract.campaign_id,
            campaign_db_path=campaign_db,
            runtime_db_path=runtime_db,
            trades_db_path=tmp_path / "trades.db",
            now=period_end + timedelta(hours=1),  # type: ignore[call-arg]
        )
    with pytest.raises(TypeError):
        get_operational_paper_campaign_status(
            campaign_id=contract.campaign_id,
            campaign_db_path=campaign_db,
            now=period_end + timedelta(hours=1),  # type: ignore[call-arg]
        )
    with pytest.raises(SystemExit):
        build_parser().parse_args(["prepare", "--campaign-id", "x", "--policy-json", "{}"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["prepare", "--campaign-id", "x", "--reference-json", "{}"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["evaluate", "--campaign-id", "x", "--policy-json", "{}"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["evaluate", "--campaign-id", "x", "--reference-json", "{}"])


def test_campaign_prepare_cli_reads_json_files_and_keeps_frozen_hash_stable(tmp_path, capsys):
    runtime_db, _, period_start, period_end, reference = _seed_operational_campaign_runtime(tmp_path, session_count=20, trades_per_session=5)
    campaign_db = tmp_path / "campaign.db"
    policy_path = _write_json_file(tmp_path / "policy.json", _operational_policy().as_dict())
    reference_path = _write_json_file(tmp_path / "reference.json", reference)
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=2)):
        exit_code = main([
            "prepare",
            "--campaign-id",
            "campaign-cli-files",
            "--campaign-db",
            str(campaign_db),
            "--runtime-db",
            str(runtime_db),
            "--strategy-version",
            reference["summary"]["strategy_version"],
            "--symbol",
            reference["summary"]["symbol"],
            "--interval",
            reference["summary"]["interval"],
            "--inclusion-rule",
            "sqlite_all_sessions",
            "--period-start-utc",
            period_start.isoformat().replace("+00:00", "Z"),
            "--period-end-utc",
            period_end.isoformat().replace("+00:00", "Z"),
            "--policy-file",
            str(policy_path),
            "--reference-file",
            str(reference_path),
        ])
    assert exit_code == 0
    stdout = capsys.readouterr().out.strip()
    assert stdout
    contract = load_operational_paper_campaign_contract(campaign_db, campaign_id="campaign-cli-files")
    assert contract.campaign_hash == stdout
    assert contract.reference_payload_json["manifest"]["manifest_hash"] == reference["manifest"]["manifest_hash"]
    assert campaign_module.paper_evaluation_hash(contract.reference_payload_json) == campaign_module.paper_evaluation_hash(reference)
    assert contract.reference_payload_json["manifest"]["strategy_version"] == reference["manifest"]["strategy_version"]


@pytest.mark.parametrize(
    ("file_name", "content", "message"),
    [
        ("missing-policy.json", None, "policy file not found"),
        ("policy.json", "", "policy file is empty"),
        ("policy.json", "{bad json", "policy file is invalid json"),
        ("missing-reference.json", None, "reference file not found"),
        ("reference.json", "", "reference file is empty"),
        ("reference.json", "{bad json", "reference file is invalid json"),
    ],
)
def test_campaign_prepare_cli_rejects_invalid_files(tmp_path, capsys, file_name, content, message):
    runtime_db, _, period_start, period_end, reference = _seed_operational_campaign_runtime(tmp_path, session_count=20, trades_per_session=5)
    campaign_db = tmp_path / "campaign.db"
    policy_path = tmp_path / "policy.json"
    reference_path = tmp_path / "reference.json"
    policy_path.write_text(json.dumps(_operational_policy().as_dict(), ensure_ascii=False), encoding="utf-8")
    reference_path.write_text(json.dumps(campaign_module.serialize_value(reference), ensure_ascii=False), encoding="utf-8")
    target_path = policy_path if "policy" in file_name else reference_path
    if content is None:
        target_path.unlink()
    else:
        target_path.write_text(content, encoding="utf-8")
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=2)):
        exit_code = main([
            "prepare",
            "--campaign-id",
            "campaign-cli-invalid",
            "--campaign-db",
            str(campaign_db),
            "--runtime-db",
            str(runtime_db),
            "--strategy-version",
            reference["summary"]["strategy_version"],
            "--symbol",
            reference["summary"]["symbol"],
            "--interval",
            reference["summary"]["interval"],
            "--inclusion-rule",
            "sqlite_all_sessions",
            "--period-start-utc",
            period_start.isoformat().replace("+00:00", "Z"),
            "--period-end-utc",
            period_end.isoformat().replace("+00:00", "Z"),
            "--policy-file",
            str(policy_path),
            "--reference-file",
            str(reference_path),
        ])
    assert exit_code == 1
    stderr = capsys.readouterr().err.lower()
    assert message in stderr
    assert str(tmp_path).lower() not in stderr


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("strategy_version", "other-strategy", "strategy_version mismatch"),
        ("symbol", "ETHUSDT", "symbol mismatch"),
        ("interval", "15m", "interval mismatch"),
    ],
)
def test_campaign_reference_scope_mismatch_blocks_at_prepare(tmp_path, field, value, message):
    runtime_db, _, period_start, period_end, reference = _seed_operational_campaign_runtime(tmp_path, session_count=20, trades_per_session=5)
    campaign_db = tmp_path / "campaign.db"
    tampered = dict(reference)
    tampered["manifest"] = {**reference["manifest"], field: value}
    tampered["manifest"]["manifest_hash"] = campaign_module.paper_evaluation_hash({k: v for k, v in tampered["manifest"].items() if k != "manifest_hash"})
    tampered["summary"] = {**reference["summary"], "manifest_hash": tampered["manifest"]["manifest_hash"]}
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=2)):
        with pytest.raises(PaperCampaignManifestError, match=message):
            create_operational_paper_campaign(
                **_campaign_kwargs(period_start, period_end, reference=campaign_module._walk_forward_from_payload(tampered)),
                runtime_db_path=runtime_db,
                campaign_db_path=campaign_db,
            )


def test_campaign_reference_execution_contract_mismatch_blocks_at_prepare(tmp_path):
    runtime_db, _, period_start, period_end, reference = _seed_operational_campaign_runtime(tmp_path, session_count=20, trades_per_session=5)
    campaign_db = tmp_path / "campaign.db"
    tampered = dict(reference)
    tampered["manifest"] = {**reference["manifest"], "execution_contract": {**reference["manifest"]["execution_contract"], "paper_only": False}}
    tampered["manifest"]["manifest_hash"] = campaign_module.paper_evaluation_hash({k: v for k, v in tampered["manifest"].items() if k != "manifest_hash"})
    tampered["summary"] = {**reference["summary"], "manifest_hash": tampered["manifest"]["manifest_hash"]}
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=2)):
        with pytest.raises(PaperCampaignManifestError, match="paper_only"):
            create_operational_paper_campaign(
                **_campaign_kwargs(period_start, period_end, reference=campaign_module._walk_forward_from_payload(tampered)),
                runtime_db_path=runtime_db,
                campaign_db_path=campaign_db,
            )


def test_campaign_policy_mismatch_and_policy_floor_none_block(tmp_path):
    runtime_db, _, period_start, period_end, _ = _seed_operational_campaign_runtime(tmp_path, session_count=20, trades_per_session=5)
    campaign_db = tmp_path / "campaign.db"
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=2)):
        contract = create_operational_paper_campaign(
            **_campaign_kwargs(period_start, period_end),
            runtime_db_path=runtime_db,
            campaign_db_path=campaign_db,
        )
    with sqlite3.connect(campaign_db) as conn:
        conn.execute("UPDATE paper_evaluation_campaign_contracts SET policy_payload_json = json_set(policy_payload_json, '$.min_profit_factor', '0.5') WHERE campaign_hash = ?", (contract.campaign_hash,))
        conn.commit()
    with pytest.raises(PaperCampaignManifestError):
        evaluate_operational_paper_campaign(
            campaign_id=contract.campaign_id,
            campaign_db_path=campaign_db,
            runtime_db_path=runtime_db,
            trades_db_path=tmp_path / "trades.db",
        )
    policy_like = SimpleNamespace(
        min_sessions_completed=10,
        min_distinct_days=20,
        min_trades=100,
        min_duration_hours=Decimal("480"),
        max_drawdown_percent=Decimal("25"),
        min_profit_factor=None,
        min_expectancy=Decimal("0"),
        min_net_return_percent=Decimal("0"),
        max_suspended_sessions=0,
        require_zero_live_attempts=True,
        require_audit_chain=True,
        require_fresh_data=True,
        min_regime_coverage=3,
        required_regimes=("BULL", "BEAR", "CHOP"),
    )
    reasons = campaign_module._validate_policy_floor(policy_like)
    assert any("min_profit_factor" in reason for reason in reasons)


def test_campaign_evaluation_before_end_is_transient_and_after_end_approves(tmp_path):
    runtime_db, trades_db, period_start, period_end, _ = _seed_operational_campaign_runtime(tmp_path, session_count=20, trades_per_session=5)
    campaign_db = tmp_path / "campaign.db"
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=2)):
        contract = create_operational_paper_campaign(
            **_campaign_kwargs(period_start, period_end),
            runtime_db_path=runtime_db,
            campaign_db_path=campaign_db,
        )
    with patch.object(campaign_module, "_utcnow", return_value=period_start + timedelta(hours=12)):
        pre = evaluate_operational_paper_campaign(
            campaign_id=contract.campaign_id,
            campaign_db_path=campaign_db,
            runtime_db_path=runtime_db,
            trades_db_path=trades_db,
        )
    assert pre.campaign_state.value == "RUNNING"
    assert pre.decision_status is PaperEvaluationStatus.INSUFFICIENT_EVIDENCE
    assert load_operational_paper_campaign_report(campaign_db, campaign_hash=contract.campaign_hash) is None
    with patch.object(campaign_module, "_utcnow", return_value=period_end + timedelta(hours=2)):
        post = evaluate_operational_paper_campaign(
            campaign_id=contract.campaign_id,
            campaign_db_path=campaign_db,
            runtime_db_path=runtime_db,
            trades_db_path=trades_db,
        )
    assert post.decision_status is PaperEvaluationStatus.APPROVED_FOR_EXTENDED_PAPER
    assert post.operational_evidence is True
    assert post.paper_report is not None
    assert post.paper_report.decision.status is PaperEvaluationStatus.APPROVED_FOR_EXTENDED_PAPER
    assert post.paper_report.aggregate_metrics.total_trades == 100
    assert post.paper_report.aggregate_metrics.snapshot_count == 20
    assert post.paper_report.aggregate_metrics.duration_hours >= Decimal("480")
    assert set(post.paper_report.aggregate_metrics.regime_coverage) == {"BULL", "BEAR", "CHOP"}
    assert post.paper_report.aggregate_metrics.winning_trades > 0
    assert post.paper_report.aggregate_metrics.losing_trades > 0
    assert post.paper_report.aggregate_metrics.breakeven_trades >= 0
    assert post.paper_report.manifest.operational_evidence is True
    again = evaluate_operational_paper_campaign(
        campaign_id=contract.campaign_id,
        campaign_db_path=campaign_db,
        runtime_db_path=runtime_db,
        trades_db_path=trades_db,
    )
    assert again.report_hash == post.report_hash
    persisted = load_operational_paper_campaign_report(campaign_db, campaign_hash=contract.campaign_hash)
    assert persisted is not None
    assert persisted.report_hash == post.report_hash


def test_campaign_frozen_selection_hash_and_json_remain_stable(tmp_path):
    runtime_db, _, period_start, period_end, reference = _seed_operational_campaign_runtime(tmp_path, session_count=20, trades_per_session=5)
    selection = campaign_module._walk_forward_from_payload(reference).windows[0].frozen_selection
    payload = selection.as_dict()
    assert "regime" not in payload
    assert set(payload) == {
        "candidate",
        "strategy_version",
        "costs",
        "execution_contract",
        "symbol",
        "interval",
        "frozen_at",
        "manifest_hash",
        "window_id",
    }
    campaign_db = tmp_path / "campaign.db"
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=2)):
        contract = create_operational_paper_campaign(
            **_campaign_kwargs(period_start, period_end),
            runtime_db_path=runtime_db,
            campaign_db_path=campaign_db,
        )
    assert contract.walk_forward_manifest_hash == reference["manifest"]["manifest_hash"]
    assert contract.walk_forward_result_hash == campaign_module.paper_evaluation_hash(reference)


@pytest.mark.parametrize(
    ("configuration", "expected"),
    [
        ({"regime": "bull"}, "BULL"),
        ({"execution_contract": {"regime": "BEAR"}}, "BEAR"),
        ({"regime": "CHOP", "execution_contract": {"regime": "CHOP"}}, "CHOP"),
        ({}, None),
    ],
)
def test_campaign_normalize_regime_accepts_valid_sources(configuration, expected):
    assert evidence_module._normalize_regime(configuration) == expected


@pytest.mark.parametrize(
    ("configuration", "message"),
    [
        ({"regime": "INVALID", "execution_contract": {"regime": "BULL"}}, "configuration.regime"),
        ({"regime": "BULL", "execution_contract": {"regime": "BEAR"}}, "regime divergence"),
        ({"execution_contract": {"regime": "INVALID"}}, "configuration.execution_contract.regime"),
        ({"regime": ""}, "configuration.regime"),
    ],
)
def test_campaign_normalize_regime_blocks_invalid_or_divergent_values(configuration, message):
    with pytest.raises(PaperEvaluationEvidenceError, match=message):
        evidence_module._normalize_regime(configuration)


def test_campaign_reference_and_policy_tamper_in_sqlite_block(tmp_path):
    runtime_db, trades_db, period_start, period_end, _ = _seed_operational_campaign_runtime(tmp_path, session_count=20, trades_per_session=5)
    campaign_db = tmp_path / "campaign.db"
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=2)):
        contract = create_operational_paper_campaign(
            **_campaign_kwargs(period_start, period_end),
            runtime_db_path=runtime_db,
            campaign_db_path=campaign_db,
        )
    with sqlite3.connect(campaign_db) as conn:
        conn.execute("UPDATE paper_evaluation_campaign_contracts SET reference_payload_json = json_set(reference_payload_json, '$.manifest.symbol', 'ETHUSDT') WHERE campaign_hash = ?", (contract.campaign_hash,))
        conn.commit()
    with pytest.raises(PaperCampaignManifestError):
        evaluate_operational_paper_campaign(
            campaign_id=contract.campaign_id,
            campaign_db_path=campaign_db,
            runtime_db_path=runtime_db,
            trades_db_path=trades_db,
        )


def test_campaign_policy_payload_tamper_blocks_by_hash(tmp_path):
    runtime_db, _, period_start, period_end, _ = _seed_operational_campaign_runtime(tmp_path, session_count=20, trades_per_session=5)
    campaign_db = tmp_path / "campaign.db"
    with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=2)):
        contract = create_operational_paper_campaign(
            **_campaign_kwargs(period_start, period_end),
            runtime_db_path=runtime_db,
            campaign_db_path=campaign_db,
        )
    with sqlite3.connect(campaign_db) as conn:
        conn.execute(
            "UPDATE paper_evaluation_campaign_contracts SET policy_payload_json = json_set(policy_payload_json, '$.min_profit_factor', '9.9') WHERE campaign_hash = ?",
            (contract.campaign_hash,),
        )
        conn.commit()
    with pytest.raises(PaperCampaignManifestError, match="campaign hash mismatch"):
        evaluate_operational_paper_campaign(
            campaign_id=contract.campaign_id,
            campaign_db_path=campaign_db,
            runtime_db_path=runtime_db,
            trades_db_path=tmp_path / "trades.db",
        )


def test_campaign_concurrent_prepare_and_evaluate_are_deduplicated(tmp_path):
    runtime_db, trades_db, period_start, period_end, reference = _seed_operational_campaign_runtime(tmp_path, session_count=20, trades_per_session=5)
    campaign_db = tmp_path / "campaign.db"
    policy_path = _write_json_file(tmp_path / "policy.json", _operational_policy().as_dict())
    reference_path = _write_json_file(tmp_path / "reference.json", reference)
    prepare_args = [
        "prepare",
        "--campaign-id",
        "campaign-concurrent",
        "--campaign-db",
        str(campaign_db),
        "--runtime-db",
        str(runtime_db),
        "--strategy-version",
        reference["summary"]["strategy_version"],
        "--symbol",
        reference["summary"]["symbol"],
        "--interval",
        reference["summary"]["interval"],
        "--inclusion-rule",
        "sqlite_all_sessions",
        "--period-start-utc",
        period_start.isoformat().replace("+00:00", "Z"),
        "--period-end-utc",
        period_end.isoformat().replace("+00:00", "Z"),
        "--policy-file",
        str(policy_path),
        "--reference-file",
        str(reference_path),
    ]

    def _prepare_once() -> int:
        with patch.object(campaign_module, "_utcnow", return_value=period_start - timedelta(hours=2)):
            return main(prepare_args)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [future.result() for future in (executor.submit(_prepare_once), executor.submit(_prepare_once))]
    assert set(results).issubset({0, 1})
    contract = load_operational_paper_campaign_contract(campaign_db, campaign_id="campaign-concurrent")
    with sqlite3.connect(campaign_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM paper_evaluation_campaign_contracts WHERE campaign_id = ?", ("campaign-concurrent",)).fetchone()[0]
    assert count == 1
    with patch.object(campaign_module, "_utcnow", return_value=period_end + timedelta(hours=2)):
        def _evaluate_once() -> str:
            return evaluate_operational_paper_campaign(
                campaign_id=contract.campaign_id,
                campaign_db_path=campaign_db,
                runtime_db_path=runtime_db,
                trades_db_path=trades_db,
            ).report_hash

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(_evaluate_once), executor.submit(_evaluate_once)]
            report_hashes: list[str] = []
            errors: list[Exception] = []
            for future in futures:
                try:
                    report_hashes.append(future.result())
                except Exception as exc:
                    errors.append(exc)
    assert report_hashes
    assert len(set(report_hashes)) == 1
    assert all(isinstance(error, PaperCampaignManifestError) for error in errors)
    persisted = load_operational_paper_campaign_report(campaign_db, campaign_hash=contract.campaign_hash)
    assert persisted is not None
    assert persisted.report_hash == report_hashes[0]


def test_campaign_cli_evaluate_returns_sanitized_error_on_missing_campaign_db(tmp_path, capsys):
    exit_code = main(["evaluate", "--campaign-id", "missing-campaign", "--campaign-db", str(tmp_path / "missing-campaign.db")])
    assert exit_code == 1
    stderr = capsys.readouterr().err.lower()
    assert "campaign database not found" in stderr
    assert str(tmp_path).lower() not in stderr


def test_campaign_cli_help_and_sanitized_source(capsys):
    parser = build_parser()
    help_text = parser.format_help()
    assert "prepare" in help_text
    assert "status" in help_text
    assert "evaluate" in help_text
    assert "--live" not in help_text
    assert "--policy-json" not in help_text
    assert "--reference-json" not in help_text
    with pytest.raises(SystemExit):
        parser.parse_args(["prepare", "-h"])
    prepare_help = capsys.readouterr().out
    assert "--policy-file" in prepare_help
    assert "--reference-file" in prepare_help
    source = Path("paper_evaluation/campaign.py").read_text(encoding="utf-8").lower()
    forbidden = ("requests", "httpx", "create_order", "send_order", "api_key", "secret", "telegram", "websocket", "subprocess", "approved_for_live")
    for token in forbidden:
        assert token not in source
