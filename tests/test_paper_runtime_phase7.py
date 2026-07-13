from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_runtime import (
    PaperRuntimeAuditError,
    PaperRuntimeMonitorError,
    PaperRuntimeSession,
    PaperRuntimeSessionError,
    PaperRuntimeState,
    PaperRuntimeStore,
    PaperRuntimeStoreError,
    build_snapshot_from_observed_state,
    get_monitored_session,
)
from paper_runtime.errors import PaperRuntimePolicyError
from promotion import MonitoredPaperLimits, PromotionStatus, adapt_walk_forward_result, evaluate_promotion, evaluate_paper_monitoring
from promotion.errors import PromotionDecisionError, PromotionPolicyError
from promotion import PaperMonitoringSnapshot

from tests.test_promotion_phase6 import _promotion_result

import paper_engine


def _approved_decision():
    return evaluate_promotion(adapt_walk_forward_result(_promotion_result()))


def _rejected_decision():
    return evaluate_promotion(adapt_walk_forward_result(_promotion_result(window_count=1)))


def _session_id(suffix: str = "alpha") -> str:
    return f"runtime-session-{suffix}"


def _store(tmp_path: Path) -> PaperRuntimeStore:
    return PaperRuntimeStore(tmp_path / "runtime.db")


def _session(store: PaperRuntimeStore, *, session_id: str = "alpha"):
    return PaperRuntimeSession.create_from_decision(
        _approved_decision(),
        session_id=_session_id(session_id),
        session_started_utc=datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc),
        store=store,
    )


def _observed(**overrides):
    payload = {
        "data_fresh": True,
        "session_drawdown_percent": "4",
        "current_loss_streak": 0,
        "open_positions": 0,
        "executed_trades": 4,
        "observed_costs": {
            "entry_fee_rate": "0.0004",
            "exit_fee_rate": "0.0004",
            "spread_bps": "5",
            "slippage_bps": "5",
        },
        "session_state": "RUNNING",
        "paper_capital_used": "1000",
        "risk_per_trade_percent": "0.5",
        "internal_error": None,
        "attempted_live": False,
    }
    payload.update(overrides)
    return payload


def _paper_df():
    import pandas as pd

    df = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "volume": [1000, 1010, 1020],
            "open_time": pd.date_range("2026-07-11", periods=3, freq="h", tz="UTC"),
            "close_time": pd.date_range("2026-07-11 00:59:59.999", periods=3, freq="h", tz="UTC"),
        }
    )
    df.attrs["fonte_dados"] = "BINANCE"
    return df


def _snapshot(session: PaperRuntimeSession, decision=None, **observed_overrides):
    decision = decision or session.decision
    return build_snapshot_from_observed_state(
        session=session.record,
        decision=decision,
        observed=_observed(**observed_overrides),
        timestamp_utc=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
    )


def _runtime_job(job_data=None):
    return SimpleNamespace(data=job_data or {})


class _DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):  # pragma: no cover - async helper
        self.sent.append((chat_id, text))


class _DummyJobQueue:
    def __init__(self):
        self.calls = []

    def get_jobs_by_name(self, name):
        return []


class _DummyContext:
    def __init__(self, job_data=None):
        self.job = _runtime_job(job_data)
        self.bot = _DummyBot()
        self.job_queue = _DummyJobQueue()


def test_decisao_aprovada_inicia_sessao(tmp_path):
    store = _store(tmp_path)
    session = _session(store)
    assert session.is_running()
    assert session.record.state is PaperRuntimeState.RUNNING
    assert session.contract.session_id == session.record.session_id
    assert session.decision is not None
    assert session.decision.status is PromotionStatus.APPROVED_FOR_MONITORED_PAPER
    assert store.load_session(session.record.session_id).session_id == session.record.session_id


def test_decisao_rejeitada_nao_inicia(tmp_path):
    store = _store(tmp_path)
    rejected = _rejected_decision()
    assert rejected.status is not PromotionStatus.APPROVED_FOR_MONITORED_PAPER
    with pytest.raises(PaperRuntimeSessionError):
        PaperRuntimeSession.create_from_decision(
            rejected,
            session_id=_session_id("rejected"),
            session_started_utc=datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc),
            store=store,
        )


def test_decisao_adulterada_nao_inicia(tmp_path):
    store = _store(tmp_path)
    decision = _approved_decision()
    object.__setattr__(decision, "paper_limits_hash", "bad-hash")
    with pytest.raises((PromotionDecisionError, PaperRuntimeSessionError)):
        PaperRuntimeSession.create_from_decision(
            decision,
            session_id=_session_id("tampered"),
            session_started_utc=datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc),
            store=store,
        )


def test_configuracao_divergente_nao_inicia(tmp_path):
    store = _store(tmp_path)
    session = _session(store)
    snapshot = _snapshot(session)
    tampered = replace(
        snapshot,
        configuration={**snapshot.configuration, "strategy_version": "tampered"},
    )
    with pytest.raises(PromotionDecisionError):
        session.evaluate_snapshot(tampered, decision=session.decision)


def test_somente_modo_paper_aceito(tmp_path):
    store = _store(tmp_path)
    session = _session(store)
    snapshot = PaperMonitoringSnapshot(
        timestamp_utc=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
        decision_hash=session.decision.decision_hash,
        evidence_hash=session.decision.evidence_hash,
        strategy_version=session.decision.strategy_version,
        configuration=session.decision.frozen_selection.as_dict(),
        trading_mode="LIVE",
        session_id=session.record.session_id,
        session_started_utc=session.record.session_started_utc,
        data_fresh=True,
        session_drawdown_percent=Decimal("0"),
        current_loss_streak=0,
        open_positions=0,
        executed_trades=0,
        observed_costs={},
        session_state="RUNNING",
        paper_capital_used=Decimal("0"),
        risk_per_trade_percent=Decimal("0"),
        internal_error=None,
        attempted_live=False,
    )
    with pytest.raises(PromotionDecisionError):
        evaluate_paper_monitoring(session.decision, snapshot, session_contract=session.contract_as_monitoring())


def test_duplicidade_sessao_ativa_bloqueada(tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="dup-a")
    with pytest.raises(PaperRuntimeSessionError):
        PaperRuntimeSession.create_from_decision(
            session.decision,
            session_id=_session_id("dup-b"),
            session_started_utc=datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc),
            store=store,
        )
    assert session.record.active is True


def test_reinicio_preserva_inicio_e_limites(tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="restart")
    reloaded = PaperRuntimeSession.from_store(session.record.session_id, store=store)
    assert reloaded.record.session_started_utc == session.record.session_started_utc
    assert reloaded.contract.paper_limits == session.contract.paper_limits
    assert reloaded.contract.execution_contract == session.contract.execution_contract
    assert reloaded.decision is not None
    assert reloaded.decision.decision_hash == session.decision.decision_hash


def test_banco_ausente_nao_recria_recuperacao(tmp_path):
    db_path = tmp_path / "missing.db"
    store = PaperRuntimeStore(db_path)
    with pytest.raises(PaperRuntimeStoreError):
        store.load_session("any-session")
    assert not db_path.exists()


def test_schema_invalido_bloqueia(tmp_path):
    db_path = tmp_path / "invalid.db"
    db_path.write_text("not sqlite", encoding="utf-8")
    store = PaperRuntimeStore(db_path)
    with pytest.raises(PaperRuntimeStoreError):
        store.load_session("any-session")


def test_snapshot_duplicado_e_idempotente(tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="dup-snapshot")
    snapshot = _snapshot(session)
    first = session.evaluate_snapshot(snapshot, decision=session.decision)
    second = session.evaluate_snapshot(snapshot, decision=session.decision)
    assert first.monitoring_decision.snapshot_hash == second.monitoring_decision.snapshot_hash
    with sqlite3.connect(store.db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM paper_runtime_snapshots WHERE session_id = ?", (session.record.session_id,)).fetchone()[0]
    assert count == 1


def test_duas_atualizacoes_mesma_versao_nao_sao_ambas_aceitas(tmp_path):
    store = _store(tmp_path)
    session_a = _session(store, session_id="version-a")
    session_b = PaperRuntimeSession.from_store(session_a.record.session_id, store=store)
    session_a.suspend("pause for version check")
    with pytest.raises(PaperRuntimeSessionError):
        session_b.suspend("stale transition")


def test_sessao_suspensa_nao_reinicia(tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="suspend")
    session.suspend("manual")
    with pytest.raises(PaperRuntimeSessionError):
        session._store.transition_session(
            session.record.session_id,
            expected_version=session.record.version,
            next_state=PaperRuntimeState.RUNNING,
        )


def test_sessao_concluida_nao_reinicia(tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="complete")
    session.complete("done")
    with pytest.raises(PaperRuntimeSessionError):
        session._store.transition_session(
            session.record.session_id,
            expected_version=session.record.version,
            next_state=PaperRuntimeState.RUNNING,
        )


@pytest.mark.parametrize(
    "field_name, expected_reason",
    [
        ("session_drawdown_percent", "session drawdown exceeded"),
        ("paper_capital_used", "paper capital limit exceeded"),
        ("risk_per_trade_percent", "risk per trade limit exceeded"),
        ("executed_trades", "trade count above maximum"),
        ("current_loss_streak", "loss streak exceeded"),
    ],
)
def test_limites_suspendem_sessao(tmp_path, field_name, expected_reason):
    store = _store(tmp_path)
    session = _session(store, session_id=f"limit-{field_name}")
    overrides = {
        "session_drawdown_percent": "999",
        "paper_capital_used": "999999",
        "risk_per_trade_percent": "99",
        "executed_trades": 500,
        "current_loss_streak": 99,
    }
    snapshot = _snapshot(session, **{field_name: overrides[field_name]})
    result = session.evaluate_snapshot(snapshot, decision=session.decision)
    assert result.monitoring_decision.status is PromotionStatus.PAPER_SUSPENDED
    assert expected_reason in result.monitoring_decision.reasons[0].lower()
    assert result.session.state is PaperRuntimeState.SUSPENDED


def test_duracao_excedida_suspende(tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="duration")
    snapshot = build_snapshot_from_observed_state(
        session=session.record,
        decision=session.decision,
        observed=_observed(),
        timestamp_utc=datetime(2026, 7, 12, 0, 0, tzinfo=timezone.utc),
    )
    result = session.evaluate_snapshot(snapshot, decision=session.decision)
    assert result.monitoring_decision.status is PromotionStatus.PAPER_SUSPENDED
    assert "duration" in result.monitoring_decision.reasons[0].lower()


def test_dados_expirados_suspende(tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="stale")
    snapshot = _snapshot(session, data_fresh=False)
    result = session.evaluate_snapshot(snapshot, decision=session.decision)
    assert result.monitoring_decision.status is PromotionStatus.PAPER_SUSPENDED
    assert "stale" in result.monitoring_decision.reasons[0].lower()


def test_tentativa_live_suspende(tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="live")
    snapshot = _snapshot(session, attempted_live=True)
    result = session.evaluate_snapshot(snapshot, decision=session.decision)
    assert result.monitoring_decision.status is PromotionStatus.PAPER_SUSPENDED
    assert "live trading attempt" in result.monitoring_decision.reasons[0].lower()


@pytest.mark.parametrize(
    "observed_costs, expected_reason",
    [
        ({}, "missing observed cost keys"),
        ({"entry_fee_rate": "0.0004", "exit_fee_rate": "0.0004", "spread_bps": "5"}, "missing observed cost keys"),
        ({"entry_fee_rate": "0.0004", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5", "other": "1"}, "unknown observed cost keys"),
        ({"entry_fee_rate": "-0.1", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5"}, "cannot be negative"),
        ({"entry_fee_rate": "NaN", "exit_fee_rate": "0.0004", "spread_bps": "5", "slippage_bps": "5"}, "must be finite"),
    ],
)
def test_custos_invalidos_suspendem(tmp_path, observed_costs, expected_reason):
    store = _store(tmp_path)
    session = _session(store, session_id=f"cost-{expected_reason}")
    snapshot = _snapshot(session, observed_costs=observed_costs)
    result = session.evaluate_snapshot(snapshot, decision=session.decision)
    assert result.monitoring_decision.status is PromotionStatus.PAPER_SUSPENDED
    assert expected_reason in result.monitoring_decision.reasons[0].lower()


def test_falha_interna_suspende(tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="internal-error")
    snapshot = _snapshot(session, internal_error="timeout")
    result = session.evaluate_snapshot(snapshot, decision=session.decision)
    assert result.monitoring_decision.status is PromotionStatus.PAPER_SUSPENDED
    assert "internal error" in result.monitoring_decision.reasons[0].lower()


def test_auditoria_detecta_adulteracao(tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="audit")
    session.evaluate_snapshot(_snapshot(session), decision=session.decision)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE paper_runtime_events SET previous_hash = ? WHERE session_id = ? AND sequence = 2",
            ("tampered", session.record.session_id),
        )
        conn.commit()
    with pytest.raises(PaperRuntimeAuditError):
        store.assert_audit_chain(session.record.session_id)


def test_sequencia_hash_incorreta_detectada(tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="hash-chain")
    session.evaluate_snapshot(_snapshot(session), decision=session.decision)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE paper_runtime_events SET event_hash = ? WHERE session_id = ? AND sequence = 2",
            ("bad-hash", session.record.session_id),
        )
        conn.commit()
    with pytest.raises(PaperRuntimeAuditError):
        store.load_events(session.record.session_id)


def test_job_suspensa_nao_busca_rede(monkeypatch, tmp_path):
    called = {"data": False}

    class _BacktesterStub:
        def baixar_dados_historicos(self, *args, **kwargs):
            called["data"] = True
            raise AssertionError("nao deveria buscar dados")

    monkeypatch.setattr(paper_engine, "backtester", _BacktesterStub())
    monkeypatch.setattr(paper_engine, "can_execute_sensitive_telegram_action", lambda *args, **kwargs: True)
    monkeypatch.setattr(paper_engine, "get_monitored_session", lambda session_id=None, decision_hash=None: None)
    ctx = _DummyContext({"chat_id": 1, "user_id": 2, "chat_type": "private", "session_id": "missing"})

    import asyncio

    asyncio.run(paper_engine.monitorar_paper_sol(ctx))
    assert called["data"] is False
    assert ctx.bot.sent == []


def test_ordem_nao_ocorre_antes_da_validacao(monkeypatch, tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="gate-order")
    monkeypatch.setattr(paper_engine, "can_execute_sensitive_telegram_action", lambda *args, **kwargs: True)
    monkeypatch.setattr(paper_engine, "get_monitored_session", lambda session_id=None, decision_hash=None: session if session_id == session.record.session_id else None)
    monkeypatch.setattr(paper_engine, "backtester", SimpleNamespace(baixar_dados_historicos=lambda symbol=None: _paper_df()))
    monkeypatch.setattr(paper_engine, "obter_trades_paper_abertos", lambda symbol=None: [])
    monkeypatch.setattr(paper_engine, "classificar_regime", lambda df: {"regime": "BULL", "adx": 30, "volatilidade": "ALTA"})
    monkeypatch.setattr(paper_engine, "esta_em_killzone", lambda: True)
    monkeypatch.setattr(
        paper_engine,
        "_obter_sinal_paper_sol",
        lambda: {"direcao": "COMPRA", "entrada": 100, "stop_loss": 95, "take_profit": 110, "rr": 2, "motivo": "ok"},
    )
    monkeypatch.setattr(paper_engine, "tomar_decisao", lambda *args, **kwargs: {"volume_status": "ALTO", "motivo": "ok", "rsi": 50})
    monkeypatch.setattr(paper_engine, "calcular_tamanho_posicao", lambda capital, risco, entrada, stop: (1, 10))
    monkeypatch.setattr(paper_engine, "registrar_trade_paper", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("nao deveria registrar trade")))
    monkeypatch.setattr(
        paper_engine,
        "build_snapshot_from_observed_state",
        lambda **kwargs: _snapshot(session, attempted_live=True),
    )
    ctx = _DummyContext({"chat_id": 1, "user_id": 2, "chat_type": "private", "session_id": session.record.session_id})

    import asyncio

    asyncio.run(paper_engine.monitorar_paper_sol(ctx))


def test_falha_de_persistencia_impede_ordem(monkeypatch, tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="persist-fail")
    monkeypatch.setattr(paper_engine, "can_execute_sensitive_telegram_action", lambda *args, **kwargs: True)
    monkeypatch.setattr(paper_engine, "get_monitored_session", lambda session_id=None, decision_hash=None: session if session_id == session.record.session_id else None)
    monkeypatch.setattr(paper_engine, "backtester", SimpleNamespace(baixar_dados_historicos=lambda symbol=None: _paper_df()))
    monkeypatch.setattr(paper_engine, "obter_trades_paper_abertos", lambda symbol=None: [])
    monkeypatch.setattr(paper_engine, "classificar_regime", lambda df: {"regime": "BULL", "adx": 30, "volatilidade": "ALTA"})
    monkeypatch.setattr(
        paper_engine,
        "build_snapshot_from_observed_state",
        lambda **kwargs: (_ for _ in ()).throw(PaperRuntimeSessionError("persistencia")),
    )
    monkeypatch.setattr(
        paper_engine,
        "_obter_sinal_paper_sol",
        lambda: (_ for _ in ()).throw(AssertionError("nao deveria calcular sinal")),
    )
    ctx = _DummyContext({"chat_id": 1, "user_id": 2, "chat_type": "private", "session_id": session.record.session_id})

    import asyncio

    asyncio.run(paper_engine.monitorar_paper_sol(ctx))


def test_chamada_repetida_nao_duplica_trade_fill(tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="idempotent")
    snapshot = _snapshot(session)
    session.evaluate_snapshot(snapshot, decision=session.decision)
    session.evaluate_snapshot(snapshot, decision=session.decision)
    with sqlite3.connect(store.db_path) as conn:
        snapshot_count = conn.execute("SELECT COUNT(*) FROM paper_runtime_snapshots WHERE session_id = ?", (session.record.session_id,)).fetchone()[0]
        event_count = conn.execute("SELECT COUNT(*) FROM paper_runtime_events WHERE session_id = ?", (session.record.session_id,)).fetchone()[0]
    assert snapshot_count == 1
    assert event_count >= 1


@pytest.mark.parametrize("timestamp_utc, session_started_utc", [
    (datetime(2026, 7, 11, 12, 0), datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc)),
    (datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc), datetime(2026, 7, 11, 9, 0)),
])
def test_timestamps_ingeuos_falham(tmp_path, timestamp_utc, session_started_utc):
    store = _store(tmp_path)
    session = _session(store, session_id="naive")
    with pytest.raises(PromotionPolicyError):
        PaperMonitoringSnapshot(
            timestamp_utc=timestamp_utc,
            decision_hash=session.decision.decision_hash,
            evidence_hash=session.decision.evidence_hash,
            strategy_version=session.decision.strategy_version,
            configuration=session.decision.frozen_selection.as_dict(),
            trading_mode="PAPER",
            session_id=session.record.session_id,
            session_started_utc=session_started_utc,
            data_fresh=True,
            session_drawdown_percent=Decimal("0"),
            current_loss_streak=0,
            open_positions=0,
            executed_trades=0,
            observed_costs={},
            session_state="RUNNING",
            paper_capital_used=Decimal("0"),
            risk_per_trade_percent=Decimal("0"),
            internal_error=None,
            attempted_live=False,
        )


@pytest.mark.parametrize("value", ["false", 0, 1, None])
def test_bools_estritos_falham(tmp_path, value):
    store = _store(tmp_path)
    session = _session(store, session_id=f"bool-{value}")
    with pytest.raises(PromotionPolicyError):
        build_snapshot_from_observed_state(
            session=session.record,
            decision=session.decision,
            observed=_observed(data_fresh=value, attempted_live=value),
            timestamp_utc=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize("session_id", [None, 1, True, "", "   "])
def test_session_id_estrito_falha(tmp_path, session_id):
    store = _store(tmp_path)
    session = _session(store, session_id="strict-session")
    with pytest.raises(PromotionPolicyError):
        PaperMonitoringSnapshot(
            timestamp_utc=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
            decision_hash=session.decision.decision_hash,
            evidence_hash=session.decision.evidence_hash,
            strategy_version=session.decision.strategy_version,
            configuration=session.decision.frozen_selection.as_dict(),
            trading_mode="PAPER",
            session_id=session_id,
            session_started_utc=session.record.session_started_utc,
            data_fresh=True,
            session_drawdown_percent=Decimal("0"),
            current_loss_streak=0,
            open_positions=0,
            executed_trades=0,
            observed_costs={},
            session_state="RUNNING",
            paper_capital_used=Decimal("0"),
            risk_per_trade_percent=Decimal("0"),
            internal_error=None,
            attempted_live=False,
        )


def test_monitoracao_com_sessao_valida_revalida_e_permite_ordem(monkeypatch, tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="valid-gate")
    calls = {"trade": 0}
    monkeypatch.setattr(paper_engine, "can_execute_sensitive_telegram_action", lambda *args, **kwargs: True)
    monkeypatch.setattr(paper_engine, "get_monitored_session", lambda session_id=None, decision_hash=None: session if session_id == session.record.session_id else None)
    monkeypatch.setattr(paper_engine, "backtester", SimpleNamespace(baixar_dados_historicos=lambda symbol=None: _paper_df()))
    monkeypatch.setattr(paper_engine, "obter_trades_paper_abertos", lambda symbol=None: [])
    monkeypatch.setattr(paper_engine, "classificar_regime", lambda df: {"regime": "BULL", "adx": 30, "volatilidade": "ALTA"})
    monkeypatch.setattr(paper_engine, "esta_em_killzone", lambda: True)
    monkeypatch.setattr(
        paper_engine,
        "_obter_sinal_paper_sol",
        lambda: {"direcao": "COMPRA", "entrada": 100, "stop_loss": 95, "take_profit": 110, "rr": 2, "motivo": "ok"},
    )
    monkeypatch.setattr(paper_engine, "tomar_decisao", lambda *args, **kwargs: {"volume_status": "ALTO", "motivo": "ok", "rsi": 50})
    monkeypatch.setattr(paper_engine, "calcular_tamanho_posicao", lambda capital, risco, entrada, stop: (1, 10))
    monkeypatch.setattr(
        paper_engine,
        "_obter_sinal_paper_sol",
        lambda: {"direcao": "COMPRA", "entrada": 100, "stop_loss": 95, "take_profit": 110, "rr": 2, "motivo": "ok"},
    )
    monkeypatch.setattr(
        paper_engine,
        "build_snapshot_from_observed_state",
        lambda **kwargs: _snapshot(
            session,
            paper_capital_used=Decimal("10"),
            session_drawdown_percent=Decimal("0"),
            risk_per_trade_percent=Decimal("0.5"),
        ),
    )
    monkeypatch.setattr(
        paper_engine,
        "registrar_trade_paper",
        lambda *args, **kwargs: calls.__setitem__("trade", calls["trade"] + 1) or 99,
    )
    monkeypatch.setattr(
        paper_engine,
        "finalizar_trade_paper",
        lambda *args, **kwargs: True,
    )
    ctx = _DummyContext({"chat_id": 1, "user_id": 2, "chat_type": "private", "session_id": session.record.session_id})

    import asyncio

    asyncio.run(paper_engine.monitorar_paper_sol(ctx))
    assert calls["trade"] == 1
    assert ctx.bot.sent
