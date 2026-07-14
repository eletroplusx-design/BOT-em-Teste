from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from paper_evaluation import (
    OperationalEvidenceBatch,
    PaperEvaluationCohort,
    PaperEvaluationAdapter,
    PaperEvaluationDecisionError,
    PaperEvaluationEvidenceError,
    PaperEvaluationManifestError,
    PaperEvaluationPolicy,
    PaperEvaluationPolicyError,
    PaperEvaluationReadError,
    PaperEvaluationStatus,
    PaperFillEvidence,
    PaperSessionEvidence,
    PaperSessionSnapshotEvidence,
    PaperSessionTradeEvidence,
    compute_paper_session_metrics,
    evaluate_paper_sessions,
    evaluate_paper_sessions_from_storage,
)
from promotion import PaperMonitoringSnapshot, adapt_walk_forward_result, evaluate_promotion
from promotion.errors import PromotionPolicyError
from paper_runtime import PaperRuntimeSession, PaperRuntimeStore
from paper_evaluation.evidence import load_operational_evidence_batch

from storage import finalizar_trade_paper, registrar_trade_paper
from tests.test_promotion_phase6 import _promotion_result


BASE_COSTS = {
    "entry_fee_rate": Decimal("0.0004"),
    "exit_fee_rate": Decimal("0.0004"),
    "spread_bps": Decimal("5"),
    "slippage_bps": Decimal("5"),
}

BASE_LIMITS = {
    "paper_capital_max": Decimal("10000"),
    "risk_per_trade_max_percent": Decimal("1"),
    "max_positions": 1,
    "session_drawdown_max_percent": Decimal("25"),
    "max_loss_streak": 3,
    "max_duration_hours": 8,
    "min_trades": 1,
    "max_trades": 100,
    "expired_data_policy": "BLOCK_AND_SUSPEND",
    "suspension_policy": "AUTO_SUSPEND",
    "kill_switch_required": True,
    "live_trading_permanently_disabled": True,
}


def _decision():
    return evaluate_promotion(adapt_walk_forward_result(_promotion_result()))


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lenient_policy() -> PaperEvaluationPolicy:
    return PaperEvaluationPolicy(
        min_sessions_completed=1,
        min_distinct_days=1,
        min_trades=0,
        min_duration_hours=Decimal("0"),
        max_drawdown_percent=Decimal("100"),
        min_profit_factor=Decimal("0"),
        min_expectancy=Decimal("-100"),
        min_net_return_percent=Decimal("-100"),
        max_total_costs_percent=Decimal("100"),
        max_suspended_sessions=0,
        require_zero_live_attempts=True,
        require_audit_chain=True,
        require_fresh_data=True,
        required_regimes=(),
        min_regime_coverage=0,
        evaluator_version="v8_paper_evaluation",
    )


def _snapshot(
    session_id: str,
    started_at: datetime,
    timestamp_utc: datetime,
    *,
    sequence: int = 1,
    session_state: str = "COMPLETED",
    data_fresh: bool = True,
    paper_capital_used: Decimal = Decimal("1000"),
    risk_per_trade_percent: Decimal = Decimal("0.5"),
    drawdown: Decimal = Decimal("1"),
    current_loss_streak: int = 0,
    open_positions: int = 0,
    executed_trades: int = 1,
    attempted_live: bool = False,
    internal_error: str | None = None,
    observed_costs: dict[str, Decimal] | None = None,
    decision_hash: str | None = None,
    evidence_hash: str | None = None,
    strategy_version: str = "v8_paper_evaluation",
    configuration: dict[str, str] | None = None,
) -> PaperMonitoringSnapshot:
    return PaperMonitoringSnapshot(
        timestamp_utc=timestamp_utc,
        decision_hash=decision_hash or _hash(f"decision-{session_id}"),
        evidence_hash=evidence_hash or _hash(f"evidence-{session_id}"),
        strategy_version=strategy_version,
        configuration=configuration or {"strategy": "monitoring", "regime": "BULL"},
        trading_mode="PAPER",
        session_id=session_id,
        session_started_utc=started_at,
        data_fresh=data_fresh,
        session_drawdown_percent=drawdown,
        current_loss_streak=current_loss_streak,
        open_positions=open_positions,
        executed_trades=executed_trades,
        observed_costs=observed_costs or dict(BASE_COSTS),
        session_state=session_state,
        paper_capital_used=paper_capital_used,
        risk_per_trade_percent=risk_per_trade_percent,
        internal_error=internal_error,
        attempted_live=attempted_live,
    )


def _trade(
    trade_id: int,
    session_id: str,
    opened_at: datetime,
    closed_at: datetime | None,
    *,
    lucro_reais: Decimal,
    entry_price: Decimal,
    exit_price: Decimal | None,
    direction: str = "COMPRA",
    quantity: Decimal = Decimal("1"),
    entry_fee: Decimal = Decimal("0.4"),
    exit_fee: Decimal | None = Decimal("0.4"),
    entry_spread_cost: Decimal = Decimal("0.5"),
    entry_slippage_cost: Decimal = Decimal("0.5"),
    exit_spread_cost: Decimal | None = Decimal("0.5"),
    exit_slippage_cost: Decimal | None = Decimal("0.5"),
    spread_cost: Decimal = Decimal("1.0"),
    slippage_cost: Decimal = Decimal("1.0"),
) -> PaperSessionTradeEvidence:
    custos_totais = entry_fee + (exit_fee or Decimal("0")) + spread_cost + slippage_cost
    lucro_percent = (lucro_reais / Decimal("1000")) * Decimal("100")
    return PaperSessionTradeEvidence(
        trade_id=trade_id,
        session_id=session_id,
        symbol="BTCUSDT",
        tipo="paper",
        status="closed" if closed_at is not None else "open",
        direcao=direction,
        entrada=entry_price,
        stop_loss=entry_price - Decimal("5"),
        take_profit=entry_price + Decimal("10"),
        quantidade=quantity,
        valor_arriscado=Decimal("100"),
        preco_base=entry_price,
        fill_price=entry_price,
        entry_fee=entry_fee,
        exit_fee=exit_fee if closed_at is not None else None,
        entry_spread_cost=entry_spread_cost,
        entry_slippage_cost=entry_slippage_cost,
        exit_spread_cost=exit_spread_cost if closed_at is not None else None,
        exit_slippage_cost=exit_slippage_cost if closed_at is not None else None,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        pnl_bruto=abs(lucro_reais) + custos_totais,
        custos_totais=custos_totais if closed_at is not None else entry_fee + spread_cost + slippage_cost,
        pnl_liquido=lucro_reais,
        aberto_em=opened_at,
        fechado_em=closed_at,
        saida=exit_price if closed_at is not None else None,
        lucro_reais=lucro_reais,
        lucro_percent=lucro_percent,
        filtros_aplicados=True,
        close_idempotency_key=f"{session_id}:close:{trade_id}" if closed_at is not None else None,
        close_idempotency_hash=_hash(f"{session_id}:close:{trade_id}") if closed_at is not None else None,
        is_real=False,
    )


def _fill(trade: PaperSessionTradeEvidence, side: str, ts: datetime, price: Decimal, fee: Decimal) -> PaperFillEvidence:
    return PaperFillEvidence(
        trade_id=trade.trade_id,
        session_id=trade.session_id,
        fill_side=side,
        timestamp_utc=ts,
        price=price,
        quantity=trade.quantidade,
        fee=fee,
        spread_cost=trade.entry_spread_cost if side == "ENTRY" else (trade.exit_spread_cost or Decimal("0")),
        slippage_cost=trade.entry_slippage_cost if side == "ENTRY" else (trade.exit_slippage_cost or Decimal("0")),
        is_real=False,
    )


def _session_evidence(
    session_id: str,
    trades: tuple[PaperSessionTradeEvidence, ...],
    snapshots: tuple[PaperMonitoringSnapshot, ...],
    *,
    session_state: str = "COMPLETED",
    regime_coverage: tuple[str, ...] = ("BULL",),
    attempted_live_count: int = 0,
    internal_error_count: int = 0,
    expired_data_cycles: int = 0,
    suspension_reasons: tuple[str, ...] = (),
    paper_limits: dict[str, Decimal | int | bool | str] | None = None,
    observed_costs: dict[str, Decimal] | None = None,
    configuration: dict[str, str] | None = None,
) -> PaperSessionEvidence:
    started = snapshots[0].session_started_utc if snapshots else datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    updated = snapshots[-1].timestamp_utc if snapshots else started + timedelta(hours=1)
    fills: list[PaperFillEvidence] = []
    for trade in trades:
        fills.append(_fill(trade, "ENTRY", trade.aberto_em, trade.fill_price or trade.preco_base or trade.entrada, trade.entry_fee or Decimal("0")))
        if trade.fechado_em is not None:
            fills.append(_fill(trade, "EXIT", trade.fechado_em, trade.saida or trade.fill_price or trade.entrada, trade.exit_fee or Decimal("0")))
    return PaperSessionEvidence(
        session_id=session_id,
        session_state=session_state,
        session_started_utc=started,
        session_updated_utc=updated,
        session_finished_utc=updated if session_state in {"COMPLETED", "FAILED", "SUSPENDED"} else None,
        decision_hash=_hash(f"decision-{session_id}"),
        evidence_hash=_hash(f"evidence-{session_id}"),
        paper_limits_hash=_hash(f"paper-limits-{session_id}"),
        strategy_version="v8_paper_evaluation",
        symbol="BTCUSDT",
        interval="1h",
        paper_only=True,
        contract_hash=_hash(f"contract-{session_id}"),
        paper_limits=paper_limits or dict(BASE_LIMITS),
        configuration=configuration or {"regime": "BULL"},
        execution_contract={
            "engine_class": "LeakFreeBacktestEngine",
            "entry_fee_rate": "0.0004",
            "exit_fee_rate": "0.0004",
            "spread_bps": "5",
            "slippage_bps": "5",
            "leverage": "1",
            "intrabar_policy": "STOP_FIRST",
            "gap_policy": "OPEN_PRICE",
            "paper_only": True,
            "symbol": "BTCUSDT",
            "interval": "1h",
            "strategy_version": "v8_paper_evaluation",
        },
        snapshots=snapshots,
        events=tuple(),
        trades=trades,
        fills=tuple(fills),
        audit_chain_valid=True,
        attempted_live_count=attempted_live_count,
        internal_error_count=internal_error_count,
        expired_data_cycles=expired_data_cycles,
        suspension_reasons=suspension_reasons,
        regime_coverage=regime_coverage,
        observed_costs=observed_costs or dict(BASE_COSTS),
    )


def _make_trade_session(session_id: str, *, trade_results: tuple[Decimal, ...], started_at: datetime, current_loss_streaks: tuple[int, ...] = (0, 1)) -> PaperSessionEvidence:
    snapshots = tuple(
        _snapshot(
            session_id,
            started_at,
            started_at + timedelta(hours=idx + 1),
            sequence=idx + 1,
            current_loss_streak=current_loss_streaks[min(idx, len(current_loss_streaks) - 1)],
            executed_trades=idx + 1,
            paper_capital_used=Decimal("1000") + Decimal(str(idx)),
        )
        for idx in range(max(1, len(current_loss_streaks)))
    )
    trades: list[PaperSessionTradeEvidence] = []
    for idx, lucro in enumerate(trade_results, start=1):
        opened = started_at + timedelta(minutes=idx * 5)
        closed = opened + timedelta(minutes=30)
        price = Decimal("100") + Decimal(idx)
        trades.append(
            _trade(
                idx,
                session_id,
                opened,
                closed,
                lucro_reais=lucro,
                entry_price=price,
                exit_price=price + lucro,
                direction="COMPRA" if lucro >= 0 else "VENDA",
            )
        )
    return _session_evidence(session_id, tuple(trades), snapshots)


def _seed_runtime_and_trades(tmp_path: Path, *, session_id: str, trade_result: Decimal) -> tuple[Path, Path]:
    runtime_db = tmp_path / "runtime.db"
    trades_db = tmp_path / "trades.db"
    decision = _decision()
    runtime_store = PaperRuntimeStore(runtime_db)
    session_started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    runtime_session = PaperRuntimeSession.create_from_decision(
        decision,
        session_id=session_id,
        session_started_utc=session_started,
        store=runtime_store,
    )
    snapshot = _snapshot(
        session_id,
        session_started,
        session_started + timedelta(hours=1),
        current_loss_streak=1 if trade_result < 0 else 0,
        executed_trades=1,
        open_positions=0,
        paper_capital_used=Decimal("1000"),
        risk_per_trade_percent=Decimal("0.5"),
        session_state="RUNNING",
        decision_hash=decision.decision_hash,
        evidence_hash=decision.evidence_hash,
        strategy_version=decision.strategy_version,
        configuration=decision.frozen_selection.as_dict(),
    )
    runtime_session.evaluate_snapshot(snapshot, decision=decision, idempotency_key=f"{session_id}:snapshot:1")
    runtime_session.complete("session complete")
    trade_id = registrar_trade_paper(
        symbol="BTCUSDT",
        direcao="COMPRA" if trade_result >= 0 else "VENDA",
        entrada=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        quantidade=1.0,
        valor_arriscado=100.0,
        rr_planejado=2.0,
        session_id=session_id,
        idempotency_key=f"{session_id}:open:1",
        db_name=str(trades_db),
    )
    finalizar_trade_paper(
        trade_id,
        saida=110.0 if trade_result >= 0 else 90.0,
        lucro_percent=float(trade_result),
        lucro_reais=float(trade_result),
        resultado="WIN" if trade_result >= 0 else "LOSS",
        motivo_saida="TP" if trade_result >= 0 else "SL",
        session_id=session_id,
        db_name=str(trades_db),
        pnl_bruto=float(trade_result + Decimal("1")),
        custos_totais=1.0,
        pnl_liquido=float(trade_result),
        exit_fee=0.4,
        entry_spread_cost=0.25,
        entry_slippage_cost=0.25,
        exit_spread_cost=0.25,
        exit_slippage_cost=0.25,
        spread_cost=0.5,
        slippage_cost=0.5,
        close_idempotency_key=f"{session_id}:close:1",
    )
    return runtime_db, trades_db


def test_paper_evaluation_empty_set_insufficient_evidence():
    report = evaluate_paper_sessions(
        [],
        policy=_lenient_policy(),
        evaluation_id="eval-empty",
        synthetic_test_data=True,
    )
    assert report.decision.status is PaperEvaluationStatus.INSUFFICIENT_EVIDENCE
    assert report.manifest.session_count == 0
    assert report.synthetic_test_data is True
    assert report.operational_evidence is False
    assert report.manifest.synthetic_test_data is True
    assert report.manifest.operational_evidence is False


def test_paper_evaluation_synthetic_fixture_not_operational_evidence():
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    session = _make_trade_session("synthetic-session", trade_results=(Decimal("25"),), started_at=started)
    report = evaluate_paper_sessions(
        [session],
        policy=_lenient_policy(),
        evaluation_id="eval-synthetic",
        synthetic_test_data=True,
    )
    assert report.decision.status is PaperEvaluationStatus.INSUFFICIENT_EVIDENCE
    assert report.synthetic_test_data is True
    assert report.operational_evidence is False
    assert report.manifest.synthetic_test_data is True
    assert report.manifest.operational_evidence is False
    assert report.aggregate_metrics.total_trades == 1
    assert any("operational evidence required" in reason for reason in report.decision.reasons)


def test_paper_evaluation_memory_only_cannot_approve_operational():
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    session = _make_trade_session("memory-only", trade_results=(Decimal("40"),), started_at=started)
    report = evaluate_paper_sessions(
        [session],
        policy=_lenient_policy(),
        evaluation_id="eval-memory-only",
    )
    assert report.decision.status is PaperEvaluationStatus.INSUFFICIENT_EVIDENCE
    assert report.operational_evidence is False
    assert report.manifest.operational_evidence is False
    assert any("operational evidence required" in reason for reason in report.decision.reasons)


def test_paper_evaluation_order_does_not_change_hash():
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    early = _make_trade_session("session-early", trade_results=(Decimal("25"),), started_at=started)
    late = _make_trade_session("session-late", trade_results=(Decimal("-10"),), started_at=started + timedelta(days=1))
    report_a = evaluate_paper_sessions([early, late], policy=_lenient_policy(), evaluation_id="eval-order")
    report_b = evaluate_paper_sessions([late, early], policy=_lenient_policy(), evaluation_id="eval-order")
    assert report_a.manifest.manifest_hash == report_b.manifest.manifest_hash
    assert report_a.decision.decision_hash == report_b.decision.decision_hash
    assert report_a.aggregate_metrics.total_trades == report_b.aggregate_metrics.total_trades


def test_paper_evaluation_policy_period_and_evaluation_id_change_hash():
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    base = _make_trade_session("base-session", trade_results=(Decimal("30"),), started_at=started)
    shifted = _make_trade_session("shifted-session", trade_results=(Decimal("30"),), started_at=started + timedelta(days=2))
    base_report = evaluate_paper_sessions([base], policy=_lenient_policy(), evaluation_id="same-eval")
    shifted_report = evaluate_paper_sessions([shifted], policy=_lenient_policy(), evaluation_id="same-eval")
    policy_report = evaluate_paper_sessions(
        [base],
        policy=PaperEvaluationPolicy(
            min_sessions_completed=1,
            min_distinct_days=1,
            min_trades=0,
            min_duration_hours=Decimal("0"),
            max_drawdown_percent=Decimal("50"),
            min_profit_factor=Decimal("0"),
            min_expectancy=Decimal("-100"),
            min_net_return_percent=Decimal("-100"),
            max_total_costs_percent=Decimal("100"),
            max_suspended_sessions=0,
            require_zero_live_attempts=True,
            require_audit_chain=True,
            require_fresh_data=True,
            required_regimes=("BULL",),
            min_regime_coverage=1,
            evaluator_version="v8_paper_evaluation",
        ),
        evaluation_id="same-eval",
    )
    renamed_report = evaluate_paper_sessions([base], policy=_lenient_policy(), evaluation_id="other-eval")
    assert base_report.manifest.manifest_hash != shifted_report.manifest.manifest_hash
    assert base_report.manifest.manifest_hash != policy_report.manifest.manifest_hash
    assert base_report.manifest.manifest_hash != renamed_report.manifest.manifest_hash
    assert base_report.manifest.period_start_utc != shifted_report.manifest.period_start_utc


def test_paper_evaluation_duplicate_session_id_rejected():
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    session = _make_trade_session("duplicated-session", trade_results=(Decimal("10"),), started_at=started)
    with pytest.raises(PaperEvaluationDecisionError):
        evaluate_paper_sessions([session, session], policy=_lenient_policy(), evaluation_id="dup-eval")


def test_paper_evaluation_missing_losing_session_is_detected():
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    winning = _make_trade_session("win-session", trade_results=(Decimal("20"),), started_at=started)
    losing = _make_trade_session("loss-session", trade_results=(Decimal("-12"),), started_at=started + timedelta(days=1))
    with pytest.raises(PaperEvaluationDecisionError):
        evaluate_paper_sessions(
            [winning],
            policy=_lenient_policy(),
            evaluation_id="expected-both",
            expected_session_ids=("win-session", "loss-session"),
        )
    report = evaluate_paper_sessions([winning, losing], policy=_lenient_policy(), evaluation_id="expected-both")
    assert report.manifest.session_ids == ("win-session", "loss-session")


def test_paper_session_metrics_drawdown_and_loss_streak_are_chronological():
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    trade_a = _trade(1, "chrono-session", started + timedelta(minutes=10), started + timedelta(minutes=30), lucro_reais=Decimal("20"), entry_price=Decimal("100"), exit_price=Decimal("120"))
    trade_b = _trade(2, "chrono-session", started + timedelta(minutes=20), started + timedelta(minutes=50), lucro_reais=Decimal("-30"), entry_price=Decimal("110"), exit_price=Decimal("80"), direction="VENDA")
    trade_c = _trade(3, "chrono-session", started + timedelta(minutes=5), started + timedelta(minutes=40), lucro_reais=Decimal("-15"), entry_price=Decimal("105"), exit_price=Decimal("90"), direction="VENDA")
    snapshots = (
        _snapshot("chrono-session", started, started + timedelta(hours=1), sequence=1, current_loss_streak=0, executed_trades=1),
        _snapshot("chrono-session", started, started + timedelta(hours=2), sequence=2, current_loss_streak=1, executed_trades=2),
        _snapshot("chrono-session", started, started + timedelta(hours=3), sequence=3, current_loss_streak=2, executed_trades=3),
    )
    session_a = _session_evidence("chrono-session", (trade_b, trade_c, trade_a), snapshots)
    session_b = _session_evidence(
        "chrono-session-b",
        tuple(replace(trade, session_id="chrono-session-b") for trade in (trade_a, trade_b, trade_c)),
        snapshots=tuple(replace(s, session_id="chrono-session-b") for s in snapshots),
    )
    metrics_a = compute_paper_session_metrics(session_a)
    metrics_b = compute_paper_session_metrics(session_b)
    assert metrics_a.drawdown_max_percent == metrics_b.drawdown_max_percent
    assert metrics_a.max_loss_streak == 2
    assert metrics_a.total_trades == 3
    assert metrics_a.capital_final == metrics_a.capital_initial + metrics_a.net_pnl
    assert metrics_a.total_costs > 0


def test_paper_session_metrics_profit_factor_and_zero_trades():
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    profit_session = _make_trade_session("profit-session", trade_results=(Decimal("30"),), started_at=started)
    loss_session = _make_trade_session("loss-session", trade_results=(Decimal("-10"),), started_at=started + timedelta(days=1))
    zero_trade_session = _session_evidence(
        "zero-session",
        tuple(),
        (
            _snapshot("zero-session", started, started + timedelta(hours=1), sequence=1, executed_trades=0, current_loss_streak=0),
        ),
    )
    profit_metrics = compute_paper_session_metrics(profit_session)
    loss_metrics = compute_paper_session_metrics(loss_session)
    zero_metrics = compute_paper_session_metrics(zero_trade_session)
    assert profit_metrics.profit_factor is None
    assert loss_metrics.winning_trades == 0
    assert loss_metrics.losing_trades == 1
    assert loss_metrics.profit_factor == Decimal("0")
    assert zero_metrics.total_trades == 0
    assert zero_metrics.profit_factor is None
    assert zero_metrics.capital_final == zero_metrics.capital_initial


def test_paper_evaluation_live_attempt_expired_data_and_suspended_sessions_reject():
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    live_attempt = _session_evidence(
        "live-attempt",
        (_trade(1, "live-attempt", started + timedelta(minutes=1), started + timedelta(minutes=5), lucro_reais=Decimal("10"), entry_price=Decimal("100"), exit_price=Decimal("110")),),
        (_snapshot("live-attempt", started, started + timedelta(hours=1), attempted_live=True, executed_trades=1),),
        attempted_live_count=1,
    )
    expired = _session_evidence(
        "expired-data",
        (_trade(1, "expired-data", started + timedelta(minutes=1), started + timedelta(minutes=5), lucro_reais=Decimal("10"), entry_price=Decimal("100"), exit_price=Decimal("110")),),
        (_snapshot("expired-data", started, started + timedelta(hours=1), data_fresh=False, executed_trades=1),),
        expired_data_cycles=1,
    )
    suspended = _session_evidence(
        "suspended",
        (_trade(1, "suspended", started + timedelta(minutes=1), started + timedelta(minutes=5), lucro_reais=Decimal("10"), entry_price=Decimal("100"), exit_price=Decimal("110")),),
        (_snapshot("suspended", started, started + timedelta(hours=1), session_state="COMPLETED", executed_trades=1),),
        session_state="SUSPENDED",
        suspension_reasons=("max_drawdown",),
    )
    report = evaluate_paper_sessions([live_attempt, expired, suspended], policy=_lenient_policy(), evaluation_id="risk-fail")
    assert report.decision.status is PaperEvaluationStatus.REJECTED
    assert any("live attempts are not allowed" in reason for reason in report.decision.reasons)
    assert any("stale data detected" in reason for reason in report.decision.reasons)
    assert any("session state SUSPENDED not eligible" in rejection.reason for rejection in report.rejected_sessions if rejection.session_id == "suspended")


def test_aggregate_metrics_use_whole_cohort_for_profit_factor_and_cost_percent():
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    low_limits = dict(BASE_LIMITS)
    low_limits["paper_capital_max"] = Decimal("100")
    good_session = _session_evidence(
        "cohort-good",
        (
            _trade(
                1,
                "cohort-good",
                started + timedelta(minutes=5),
                started + timedelta(minutes=35),
                lucro_reais=Decimal("40"),
                entry_price=Decimal("100"),
                exit_price=Decimal("140"),
            ),
        ),
        (_snapshot("cohort-good", started, started + timedelta(hours=1), executed_trades=1, paper_capital_used=Decimal("40")),),
        paper_limits=low_limits,
    )
    bad_session = _session_evidence(
        "cohort-bad",
        (
            _trade(
                1,
                "cohort-bad",
                started + timedelta(days=1, minutes=5),
                started + timedelta(days=1, minutes=35),
                lucro_reais=Decimal("-30"),
                entry_price=Decimal("100"),
                exit_price=Decimal("70"),
                direction="VENDA",
            ),
        ),
        (_snapshot("cohort-bad", started + timedelta(days=1), started + timedelta(days=1, hours=1), executed_trades=1, paper_capital_used=Decimal("40")),),
        paper_limits=low_limits,
    )
    policy = PaperEvaluationPolicy(
        min_sessions_completed=2,
        min_distinct_days=1,
        min_trades=2,
        min_duration_hours=Decimal("0"),
        max_drawdown_percent=Decimal("100"),
        min_profit_factor=Decimal("2"),
        min_expectancy=Decimal("-100"),
        min_net_return_percent=Decimal("-100"),
        max_total_costs_percent=Decimal("1"),
        max_suspended_sessions=0,
        require_zero_live_attempts=True,
        require_audit_chain=True,
        require_fresh_data=True,
        required_regimes=(),
        min_regime_coverage=0,
        evaluator_version="v8_paper_evaluation",
    )
    cohort = PaperEvaluationCohort(
        strategy_version="v8_paper_evaluation",
        period_start_utc=started,
        period_end_utc=started + timedelta(days=1, hours=1),
        inclusion_rule="cohort_aggregate",
        created_at_utc=started + timedelta(days=1, hours=1),
        session_ids=("cohort-good", "cohort-bad"),
    )
    batch = OperationalEvidenceBatch(cohort=cohort, evidences=(good_session, bad_session), rejections=tuple())
    report = evaluate_paper_sessions(
        [good_session, bad_session],
        policy=policy,
        reference_walk_forward=_promotion_result(),
        evaluation_id="cohort-aggregate",
        synthetic_test_data=False,
        operational_batch=batch,
    )
    assert report.decision.status is PaperEvaluationStatus.REJECTED
    assert any("profit factor below minimum" in reason for reason in report.decision.reasons)
    assert any("costs above maximum" in reason for reason in report.decision.reasons)


def test_operational_evaluation_requires_walk_forward_reference(tmp_path):
    runtime_db, trades_db = _seed_runtime_and_trades(tmp_path, session_id="operational-no-reference", trade_result=Decimal("25"))
    batch = load_operational_evidence_batch(runtime_db_path=runtime_db, trades_db_path=trades_db)
    report = evaluate_paper_sessions(
        list(batch.evidences),
        policy=_lenient_policy(),
        evaluation_id="operational-no-reference",
        operational_batch=batch,
    )
    assert report.decision.status is PaperEvaluationStatus.INSUFFICIENT_EVIDENCE
    assert any("walk-forward reference required" in reason for reason in report.decision.reasons)


def test_operational_period_filters_are_rejected(tmp_path):
    runtime_db, trades_db = _seed_runtime_and_trades(tmp_path, session_id="operational-period", trade_result=Decimal("25"))
    with pytest.raises(PaperEvaluationDecisionError):
        evaluate_paper_sessions_from_storage(
            runtime_db_path=runtime_db,
            trades_db_path=trades_db,
            policy=_lenient_policy(),
            reference_walk_forward=_decision(),
            evaluation_id="operational-period",
            synthetic_test_data=False,
            operational_evidence=True,
            period_start_utc=datetime(2026, 7, 11, 0, 0, tzinfo=timezone.utc),
            period_end_utc=datetime(2026, 7, 12, 0, 0, tzinfo=timezone.utc),
        )


def test_operational_cohort_hash_mutation_is_blocked():
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    cohort = PaperEvaluationCohort(
        strategy_version="v8_paper_evaluation",
        period_start_utc=started,
        period_end_utc=started + timedelta(hours=2),
        inclusion_rule="sqlite_all_sessions",
        created_at_utc=started + timedelta(hours=2),
        session_ids=("a", "b"),
    )
    with pytest.raises(PaperEvaluationManifestError):
        replace(cohort, inclusion_rule="manual")


def test_costs_are_read_from_execution_contract_not_defaults():
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    session = _make_trade_session("contract-costs", trade_results=(Decimal("15"),), started_at=started)
    updated_contract = dict(session.execution_contract)
    updated_contract.update({"entry_fee_rate": "0.0012", "exit_fee_rate": "0.0015", "spread_bps": "12", "slippage_bps": "18"})
    session = replace(session, session_hash="", execution_contract=updated_contract, observed_costs={"entry_fee_rate": Decimal("0.0012"), "exit_fee_rate": Decimal("0.0015"), "spread_bps": Decimal("12"), "slippage_bps": Decimal("18")})
    metrics = compute_paper_session_metrics(session)
    assert metrics.fee_deviation_percent == Decimal("0")
    assert metrics.spread_deviation_bps == Decimal("0")
    assert metrics.slippage_deviation_bps == Decimal("0")


@pytest.mark.parametrize(
    "field_name, factory, kwargs",
    [
        ("data_fresh", PaperSessionSnapshotEvidence, {"field": "data_fresh", "value": "false"}),
        ("data_fresh_zero", PaperSessionSnapshotEvidence, {"field": "data_fresh", "value": 0}),
        ("data_fresh_one", PaperSessionSnapshotEvidence, {"field": "data_fresh", "value": 1}),
        ("attempted_live", PaperSessionSnapshotEvidence, {"field": "attempted_live", "value": "false"}),
        ("session_id_none", PaperSessionEvidence, {"field": "session_id", "value": None}),
        ("session_id_int", PaperSessionEvidence, {"field": "session_id", "value": 1}),
        ("session_id_bool", PaperSessionEvidence, {"field": "session_id", "value": True}),
        ("session_id_empty", PaperSessionEvidence, {"field": "session_id", "value": ""}),
        ("session_id_spaces", PaperSessionEvidence, {"field": "session_id", "value": "   "}),
    ],
)
def test_paper_evaluation_rejects_invalid_booleans_and_session_ids(field_name, factory, kwargs):
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    snapshot = _snapshot("invalid-case", started, started + timedelta(hours=1))
    trade = _trade(1, "invalid-case", started + timedelta(minutes=1), started + timedelta(minutes=10), lucro_reais=Decimal("5"), entry_price=Decimal("100"), exit_price=Decimal("105"))
    fill = _fill(trade, "ENTRY", trade.aberto_em, trade.fill_price or trade.entrada, trade.entry_fee or Decimal("0"))
    if factory is PaperSessionSnapshotEvidence:
        value = kwargs["value"]
        with pytest.raises(PromotionPolicyError):
            replace(snapshot, **{kwargs["field"]: value})
    else:
        value = kwargs["value"]
        bad_kwargs = {
            "session_id": value,
            "session_state": "COMPLETED",
            "session_started_utc": started,
            "session_updated_utc": started + timedelta(hours=1),
            "session_finished_utc": started + timedelta(hours=1),
            "decision_hash": _hash("decision"),
            "evidence_hash": _hash("evidence"),
            "paper_limits_hash": _hash("paper-limits"),
            "strategy_version": "v8_paper_evaluation",
            "symbol": "BTCUSDT",
            "interval": "1h",
            "paper_only": True,
            "contract_hash": _hash("contract"),
            "paper_limits": dict(BASE_LIMITS),
            "configuration": {"regime": "BULL"},
            "execution_contract": {
                "engine_class": "LeakFreeBacktestEngine",
                "entry_fee_rate": "0.0004",
                "exit_fee_rate": "0.0004",
                "spread_bps": "5",
                "slippage_bps": "5",
                "leverage": "1",
                "intrabar_policy": "STOP_FIRST",
                "gap_policy": "OPEN_PRICE",
                "paper_only": True,
                "symbol": "BTCUSDT",
                "interval": "1h",
                "strategy_version": "v8_paper_evaluation",
            },
            "snapshots": (snapshot,),
            "events": tuple(),
            "trades": (trade,),
            "fills": (fill, _fill(trade, "EXIT", trade.fechado_em or trade.aberto_em, trade.saida or trade.entrada, trade.exit_fee or Decimal("0"))),
            "audit_chain_valid": True,
            "attempted_live_count": 0,
            "internal_error_count": 0,
            "expired_data_cycles": 0,
            "suspension_reasons": (),
            "regime_coverage": ("BULL",),
            "observed_costs": dict(BASE_COSTS),
        }
        with pytest.raises(PaperEvaluationEvidenceError):
            PaperSessionEvidence(**bad_kwargs)


@pytest.mark.parametrize(
    "value, field",
    [
        ("false", "data_fresh"),
        (0, "data_fresh"),
        (1, "attempted_live"),
        (None, "attempted_live"),
    ],
)
def test_snapshot_validation_rejects_non_strict_booleans(value, field):
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    kwargs = dict(
        timestamp_utc=started + timedelta(hours=1),
        decision_hash=_hash("decision"),
        evidence_hash=_hash("evidence"),
        strategy_version="v8_paper_evaluation",
        configuration={"regime": "BULL"},
        trading_mode="PAPER",
        session_id="snapshot-boolean",
        session_started_utc=started,
        data_fresh=True,
        session_drawdown_percent=Decimal("0"),
        current_loss_streak=0,
        open_positions=0,
        executed_trades=0,
        observed_costs=dict(BASE_COSTS),
        session_state="RUNNING",
        paper_capital_used=Decimal("0"),
        risk_per_trade_percent=Decimal("0"),
        internal_error=None,
        attempted_live=False,
    )
    kwargs[field] = value
    with pytest.raises(PromotionPolicyError):
        PaperMonitoringSnapshot(**kwargs)


@pytest.mark.parametrize(
    "costs",
    [
        {"entry_fee_rate": Decimal("-1"), "exit_fee_rate": Decimal("0.0004"), "spread_bps": Decimal("5"), "slippage_bps": Decimal("5")},
        {"entry_fee_rate": Decimal("NaN"), "exit_fee_rate": Decimal("0.0004"), "spread_bps": Decimal("5"), "slippage_bps": Decimal("5")},
        {"entry_fee_rate": Decimal("0.0004"), "exit_fee_rate": Decimal("Infinity"), "spread_bps": Decimal("5"), "slippage_bps": Decimal("5")},
    ],
)
def test_snapshot_validation_rejects_invalid_costs(costs):
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    kwargs = dict(
        timestamp_utc=started + timedelta(hours=1),
        decision_hash=_hash("decision"),
        evidence_hash=_hash("evidence"),
        strategy_version="v8_paper_evaluation",
        configuration={"regime": "BULL"},
        trading_mode="PAPER",
        session_id="snapshot-costs",
        session_started_utc=started,
        data_fresh=True,
        session_drawdown_percent=Decimal("0"),
        current_loss_streak=0,
        open_positions=0,
        executed_trades=0,
        observed_costs=costs,
        session_state="RUNNING",
        paper_capital_used=Decimal("0"),
        risk_per_trade_percent=Decimal("0"),
        internal_error=None,
        attempted_live=False,
    )
    with pytest.raises(PromotionPolicyError):
        PaperMonitoringSnapshot(**kwargs)


def test_typed_fill_and_trade_reject_real_and_invalid_values():
    started = datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)
    trade = _trade(1, "validation-session", started, started + timedelta(minutes=5), lucro_reais=Decimal("10"), entry_price=Decimal("100"), exit_price=Decimal("110"))
    with pytest.raises(PaperEvaluationEvidenceError):
        PaperFillEvidence(
            trade_id=1,
            session_id="validation-session",
            fill_side="ENTRY",
            timestamp_utc=started,
            price=Decimal("NaN"),
            quantity=Decimal("1"),
            fee=Decimal("0"),
            spread_cost=Decimal("0"),
            slippage_cost=Decimal("0"),
            is_real=False,
        )
    with pytest.raises(PaperEvaluationEvidenceError):
        replace(trade, is_real=True)


def test_policy_and_report_reject_invalid_boolean_fields():
    with pytest.raises(PaperEvaluationPolicyError):
        PaperEvaluationPolicy(require_zero_live_attempts="false")  # type: ignore[arg-type]


def test_operational_evidence_from_sqlite_and_phase5_reference(tmp_path):
    runtime_db, trades_db = _seed_runtime_and_trades(tmp_path, session_id="operational-1", trade_result=Decimal("35"))
    reference = _promotion_result()
    batch = load_operational_evidence_batch(runtime_db_path=runtime_db, trades_db_path=trades_db)
    report = evaluate_paper_sessions_from_storage(
        runtime_db_path=runtime_db,
        trades_db_path=trades_db,
        policy=_lenient_policy(),
        reference_walk_forward=reference,
        evaluation_id="operational-eval",
        synthetic_test_data=False,
        operational_evidence=True,
    )
    assert report.manifest.session_count == 1
    assert report.manifest.operational_evidence is True
    assert report.manifest.cohort_hash == batch.cohort.cohort_hash
    assert report.synthetic_test_data is False
    assert report.decision.status is PaperEvaluationStatus.APPROVED_FOR_EXTENDED_PAPER
    assert report.walk_forward_comparison["reference_manifest_hash"] == reference.manifest["manifest_hash"]
    assert report.walk_forward_comparison["reference_profit_factor"] is not None


def test_explicit_operational_session_selection_and_mapping_reference_are_rejected(tmp_path):
    runtime_db, trades_db = _seed_runtime_and_trades(tmp_path, session_id="operational-explicit", trade_result=Decimal("20"))
    reference = _promotion_result()
    with pytest.raises(PaperEvaluationReadError):
        evaluate_paper_sessions_from_storage(
            runtime_db_path=runtime_db,
            trades_db_path=trades_db,
            policy=_lenient_policy(),
            reference_walk_forward=reference,
            evaluation_id="operational-empty",
            synthetic_test_data=False,
            operational_evidence=True,
            session_ids=(),
        )
    with pytest.raises(PaperEvaluationReadError):
        evaluate_paper_sessions_from_storage(
            runtime_db_path=runtime_db,
            trades_db_path=trades_db,
            policy=_lenient_policy(),
            reference_walk_forward=reference,
            evaluation_id="operational-duplicate",
            synthetic_test_data=False,
            operational_evidence=False,
            session_ids=("operational-explicit", "operational-explicit"),
        )
    with pytest.raises(PaperEvaluationReadError):
        evaluate_paper_sessions_from_storage(
            runtime_db_path=runtime_db,
            trades_db_path=trades_db,
            policy=_lenient_policy(),
            reference_walk_forward=reference,
            evaluation_id="operational-unknown",
            synthetic_test_data=False,
            operational_evidence=False,
            session_ids=("missing-session",),
        )
    with pytest.raises(PaperEvaluationReadError):
        evaluate_paper_sessions_from_storage(
            runtime_db_path=runtime_db,
            trades_db_path=trades_db,
            policy=_lenient_policy(),
            reference_walk_forward=reference,
            evaluation_id="operational-blank",
            synthetic_test_data=False,
            operational_evidence=False,
            session_ids=("   ",),
        )
    with pytest.raises(PaperEvaluationDecisionError):
        evaluate_paper_sessions_from_storage(
            runtime_db_path=runtime_db,
            trades_db_path=trades_db,
            policy=_lenient_policy(),
            reference_walk_forward=reference,
            evaluation_id="operational-explicit",
            synthetic_test_data=False,
            operational_evidence=True,
            session_ids=("operational-explicit",),
        )
    with pytest.raises(PaperEvaluationDecisionError):
        evaluate_paper_sessions(
            [ _make_trade_session("mapping-session", trade_results=(Decimal("25"),), started_at=datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)) ],
            policy=_lenient_policy(),
            evaluation_id="mapping-ref",
            reference_walk_forward=reference.as_dict(),
            synthetic_test_data=False,
        )


def test_tampered_audit_chain_blocks(tmp_path):
    runtime_db, trades_db = _seed_runtime_and_trades(tmp_path, session_id="tampered-1", trade_result=Decimal("10"))
    with sqlite3.connect(runtime_db) as conn:
        conn.execute("UPDATE paper_runtime_events SET previous_hash = 'broken-chain' WHERE session_id = ?", ("tampered-1",))
        conn.commit()
    report = evaluate_paper_sessions_from_storage(
        runtime_db_path=runtime_db,
        trades_db_path=trades_db,
        policy=_lenient_policy(),
        evaluation_id="tampered-eval",
    )
    assert report.decision.status is PaperEvaluationStatus.REJECTED
    assert any("audit chain diverged" in rejection.reason for rejection in report.rejected_sessions)


def test_runtime_snapshot_and_session_hash_mismatches_block(tmp_path):
    runtime_db, trades_db = _seed_runtime_and_trades(tmp_path, session_id="tampered-snapshot", trade_result=Decimal("10"))
    with sqlite3.connect(runtime_db) as conn:
        conn.execute("UPDATE paper_runtime_sessions SET last_snapshot_hash = 'broken-snapshot' WHERE session_id = ?", ("tampered-snapshot",))
        conn.commit()
    report = evaluate_paper_sessions_from_storage(
        runtime_db_path=runtime_db,
        trades_db_path=trades_db,
        policy=_lenient_policy(),
        evaluation_id="tampered-snapshot",
    )
    assert report.decision.status is PaperEvaluationStatus.REJECTED
    assert any("runtime last snapshot hash mismatch" in rejection.reason for rejection in report.rejected_sessions)


def test_runtime_snapshot_hash_column_mismatch_blocks(tmp_path):
    runtime_db, trades_db = _seed_runtime_and_trades(tmp_path, session_id="tampered-snapshot-hash", trade_result=Decimal("10"))
    with sqlite3.connect(runtime_db) as conn:
        conn.execute("UPDATE paper_runtime_snapshots SET snapshot_hash = 'broken-snapshot' WHERE session_id = ?", ("tampered-snapshot-hash",))
        conn.commit()
    report = evaluate_paper_sessions_from_storage(
        runtime_db_path=runtime_db,
        trades_db_path=trades_db,
        policy=_lenient_policy(),
        evaluation_id="tampered-snapshot-hash",
    )
    assert report.decision.status is PaperEvaluationStatus.REJECTED
    assert any("runtime snapshot hash mismatch" in rejection.reason for rejection in report.rejected_sessions)


def test_runtime_event_gap_and_last_hash_mismatches_block(tmp_path):
    runtime_db, trades_db = _seed_runtime_and_trades(tmp_path, session_id="tampered-event", trade_result=Decimal("10"))
    with sqlite3.connect(runtime_db) as conn:
        conn.execute(
            "UPDATE paper_runtime_events SET sequence = 99 WHERE session_id = ? AND sequence = (SELECT MIN(sequence) FROM paper_runtime_events WHERE session_id = ? AND sequence > 1)",
            ("tampered-event", "tampered-event"),
        )
        conn.execute("UPDATE paper_runtime_sessions SET last_event_hash = 'broken-event-hash' WHERE session_id = ?", ("tampered-event",))
        conn.commit()
    report = evaluate_paper_sessions_from_storage(
        runtime_db_path=runtime_db,
        trades_db_path=trades_db,
        policy=_lenient_policy(),
        evaluation_id="tampered-event",
    )
    assert report.decision.status is PaperEvaluationStatus.REJECTED
    assert any("runtime event sequence is not continuous" in rejection.reason or "runtime last event hash mismatch" in rejection.reason for rejection in report.rejected_sessions)


def test_missing_database_blocks(tmp_path):
    with pytest.raises(PaperEvaluationReadError):
        evaluate_paper_sessions_from_storage(
            runtime_db_path=tmp_path / "missing-runtime.db",
            trades_db_path=tmp_path / "missing-trades.db",
            policy=_lenient_policy(),
            evaluation_id="missing-db",
            operational_evidence=False,
            session_ids=("missing",),
        )


def test_invalid_schema_blocks(tmp_path):
    runtime_db = tmp_path / "runtime.db"
    trades_db = tmp_path / "trades.db"
    sqlite3.connect(runtime_db).close()
    sqlite3.connect(trades_db).close()
    with pytest.raises(PaperEvaluationReadError):
        evaluate_paper_sessions_from_storage(
            runtime_db_path=runtime_db,
            trades_db_path=trades_db,
            policy=_lenient_policy(),
            evaluation_id="invalid-schema",
            operational_evidence=False,
            session_ids=("missing",),
        )


def test_no_network_or_executor_real_imports_in_package():
    forbidden = ("requests", "httpx", "create_order", "send_order", "api_key", "secret", "telegram", "websocket", "subprocess", "APPROVED_FOR_LIVE")
    files = list(Path("paper_evaluation").glob("*.py"))
    payload = "\n".join(path.read_text(encoding="utf-8").lower() for path in files)
    for token in forbidden:
        assert token.lower() not in payload
