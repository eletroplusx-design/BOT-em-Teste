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


def test_get_monitored_session_valida_auditoria_integral(tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="audit-get")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE paper_runtime_sessions SET contract_hash = ? WHERE session_id = ?",
            ("tampered", session.record.session_id),
        )
        conn.commit()
    with pytest.raises(PaperRuntimeSessionError):
        get_monitored_session(session_id=session.record.session_id, store=store)


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
    monkeypatch.setattr(paper_engine, "obter_trades_paper_abertos", lambda symbol=None, session_id=None: [])
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


def test_fechamento_nao_ocorre_antes_da_validacao(monkeypatch, tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="close-gate-order")
    monkeypatch.setattr(paper_engine, "can_execute_sensitive_telegram_action", lambda *args, **kwargs: True)
    monkeypatch.setattr(paper_engine, "get_monitored_session", lambda session_id=None, decision_hash=None: session if session_id == session.record.session_id else None)
    monkeypatch.setattr(paper_engine, "backtester", SimpleNamespace(baixar_dados_historicos=lambda symbol=None: _paper_df()))
    monkeypatch.setattr(
        paper_engine,
        "obter_trades_paper_abertos",
        lambda symbol=None, session_id=None: [
            {
                "id": 10,
                "timestamp": "2026-01-01T00:00:00+00:00",
                "symbol": "SOLUSDT",
                "direcao": "COMPRA",
                "entrada": 100.0,
                "stop_loss": 95.0,
                "take_profit": 110.0,
                "quantidade": 1.0,
                "valor_arriscado": 100.0,
                "aberto_em": "2026-01-01T00:00:00+00:00",
                "session_id": session.record.session_id,
                "tipo": "paper",
                "status": "open",
            }
        ],
    )
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
    monkeypatch.setattr(paper_engine, "finalizar_trade_paper", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("nao deveria finalizar trade")))
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
    monkeypatch.setattr(paper_engine, "obter_trades_paper_abertos", lambda symbol=None, session_id=None: [])
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
    monkeypatch.setattr(paper_engine, "obter_trades_paper_abertos", lambda symbol=None, session_id=None: [])
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
    reconcile_calls = {"count": 0}

    async def _fake_reconcile(*args, **kwargs):
        reconcile_calls["count"] += 1
        if reconcile_calls["count"] == 1:
            return False
        await ctx.bot.send_message(chat_id=1, text="Paper SOL reconciliado")
        return True

    monkeypatch.setattr(paper_engine, "_reconciliar_paper_runtime_outbox", _fake_reconcile)

    import asyncio

    asyncio.run(paper_engine.monitorar_paper_sol(ctx))
    assert calls["trade"] == 1
    assert ctx.bot.sent


def test_outbox_real_transita_abertura_fechamento_e_notificacao(monkeypatch, tmp_path):
    import storage

    trades_db = tmp_path / "paper_trades.db"
    monkeypatch.setattr(storage, "DB_NAME", str(trades_db))
    storage.inicializar_banco(str(trades_db))
    monkeypatch.setattr(
        paper_engine,
        "obter_outbox_paper_pendentes",
        lambda session_id=None: storage.obter_outbox_paper_pendentes(session_id=session_id, db_name=str(trades_db)),
    )
    monkeypatch.setattr(
        paper_engine,
        "atualizar_outbox_paper_trade",
        lambda event_id, **kwargs: storage.atualizar_outbox_paper_trade(event_id, db_name=str(trades_db), **kwargs),
    )
    monkeypatch.setattr(
        paper_engine,
        "obter_trades_paper_abertos",
        lambda symbol=None, session_id=None: storage.obter_trades_paper_abertos(symbol=symbol, session_id=session_id),
    )

    store = _store(tmp_path)
    session = _session(store, session_id="real-outbox")
    import sqlite3

    contexto = _DummyContext({"chat_id": 123, "user_id": 123, "chat_type": "private", "session_id": session.record.session_id})
    def _fake_evaluate_snapshot(self, snapshot, decision=None, idempotency_key=None, limits=None):
        self._store.append_snapshot(
            self.record.session_id,
            snapshot=getattr(snapshot, "as_dict", lambda: snapshot)(),
            decision_hash=self.decision.decision_hash,
            evidence_hash=self.decision.evidence_hash,
            result_status="APPROVED",
            idempotency_key=idempotency_key,
        )
        return SimpleNamespace(monitoring_decision=SimpleNamespace(status="APPROVED"), session=self.record, approved=True)

    monkeypatch.setattr(type(session), "evaluate_snapshot", _fake_evaluate_snapshot, raising=False)

    agora = datetime.now(timezone.utc)
    open_time = agora - timedelta(minutes=30)
    close_time = agora - timedelta(minutes=5)

    def _open_outbox_factory(trade_id, timestamp):
        return paper_engine._paper_runtime_outbox_record(
            paper_engine._paper_runtime_outbox_payload(
                operation_type="OPEN",
                trade_id=trade_id,
                session_id=session.record.session_id,
                candle_close_time=open_time,
                idempotency_key=f"open:{trade_id}",
                runtime_events=[
                    {
                        "event_type": paper_engine.PaperRuntimeEventType.TRADE_RECORDED.value,
                        "result": "OPENED",
                        "idempotency_key": f"open-event:{trade_id}",
                        "payload": {"action": "OPEN", "trade_id": trade_id, "session_id": session.record.session_id},
                    }
                ],
                snapshot_context={
                    "preco_atual": 100.0,
                    "regime_info": {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"},
                    "data_fresh": True,
                },
                telegram_text="Paper SOL aberto",
                telegram_chat_id=123,
            )
        )

    trade_id = storage.registrar_trade_paper(
        "SOLUSDT",
        "COMPRA",
        100.0,
        95.0,
        110.0,
        1.0,
        100.0,
        2.0,
        session_id=session.record.session_id,
        idempotency_key="idem-open",
        candle_close_time=open_time,
        signal_identity="signal-open",
        preco_base=100.0,
        fill_price=100.0,
        entry_fee=0.0,
        entry_spread_cost=0.25,
        entry_slippage_cost=0.15,
        spread_cost=0.25,
        slippage_cost=0.15,
        outbox_event_factory=_open_outbox_factory,
        db_name=str(trades_db),
    )
    assert trade_id is not None

    with sqlite3.connect(trades_db) as conn:
        row = conn.execute(
            """
            SELECT entry_spread_cost, entry_slippage_cost, exit_spread_cost, exit_slippage_cost, spread_cost, slippage_cost
            FROM trades
            WHERE id = ?
            """,
            (trade_id,),
        ).fetchone()
    assert row == (0.25, 0.15, None, None, 0.25, 0.15)

    import asyncio

    asyncio.run(paper_engine._reconciliar_paper_runtime_outbox(contexto, session, session_scope_id=session.record.session_id, chat_id=123))
    assert len(contexto.bot.sent) == 1

    with sqlite3.connect(trades_db) as conn:
        row = conn.execute(
            """
            SELECT status, runtime_delivered_at_utc, snapshot_applied_at_utc, telegram_sent_at_utc
            FROM paper_trade_outbox
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        assert row is not None
        assert row[0] == "NOTIFIED"
        assert row[1] is not None
        assert row[2] is not None
        assert row[3] is not None

    def _close_outbox_factory(trade_id, timestamp):
        return paper_engine._paper_runtime_outbox_record(
            paper_engine._paper_runtime_outbox_payload(
                operation_type="CLOSE",
                trade_id=trade_id,
                session_id=session.record.session_id,
                candle_close_time=close_time,
                idempotency_key=f"close:{trade_id}",
                runtime_events=[
                    {
                        "event_type": paper_engine.PaperRuntimeEventType.TRADE_RECORDED.value,
                        "result": "CLOSED",
                        "idempotency_key": f"close-event:{trade_id}",
                        "payload": {
                            "action": "CLOSE",
                            "trade_id": trade_id,
                            "session_id": session.record.session_id,
                            "direcao": "COMPRA",
                            "saida": 110.0,
                        },
                    }
                ],
                snapshot_context={
                    "preco_atual": 110.0,
                    "regime_info": {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"},
                    "data_fresh": True,
                },
                telegram_text="Paper SOL fechado",
                telegram_chat_id=123,
            )
        )

    fechamento_ok = storage.finalizar_trade_paper(
        trade_id,
        110.0,
        10.0,
        10.0,
        "GANHO",
        "TAKE_PROFIT",
        idempotency_key="idem-close",
        session_id=session.record.session_id,
        candle_close_time=close_time,
        fill_price=110.0,
        pnl_bruto=10.0,
        custos_totais=0.0,
        pnl_liquido=10.0,
        exit_fee=0.0,
        spread_cost=0.0,
        slippage_cost=0.0,
        close_idempotency_key="idem-close",
        outbox_event_factory=_close_outbox_factory,
        db_name=str(trades_db),
    )
    assert fechamento_ok is True

    asyncio.run(paper_engine._reconciliar_paper_runtime_outbox(contexto, session, session_scope_id=session.record.session_id, chat_id=123))
    assert len(contexto.bot.sent) == 2

    with sqlite3.connect(trades_db) as conn:
        outbox_rows = conn.execute(
            """
            SELECT status, runtime_delivered_at_utc, snapshot_applied_at_utc, telegram_sent_at_utc
            FROM paper_trade_outbox
            ORDER BY id
            """
        ).fetchall()
        assert outbox_rows
        assert all(row[0] == "NOTIFIED" for row in outbox_rows)
        assert all(row[1] is not None and row[2] is not None and row[3] is not None for row in outbox_rows)

    with sqlite3.connect(store.db_path) as conn:
        snapshot_count = conn.execute(
            "SELECT COUNT(*) FROM paper_runtime_snapshots WHERE session_id = ?",
            (session.record.session_id,),
        ).fetchone()[0]
        event_count = conn.execute(
            "SELECT COUNT(*) FROM paper_runtime_events WHERE session_id = ?",
            (session.record.session_id,),
        ).fetchone()[0]
    assert snapshot_count >= 1
    assert event_count >= 1


def test_monitorar_paper_sol_costs_abertura_e_fechamento_5bps(monkeypatch, tmp_path):
    import storage

    trades_db = tmp_path / "paper_trades_costs.db"
    monkeypatch.setattr(storage, "DB_NAME", str(trades_db))
    storage.inicializar_banco(str(trades_db))

    store = _store(tmp_path)
    session = _session(store, session_id="costs-5bps")
    ctx = _DummyContext({"chat_id": 123, "user_id": 123, "chat_type": "private", "session_id": session.record.session_id})
    monkeypatch.setattr(paper_engine, "get_monitored_session", lambda session_id=None, decision_hash=None, store=None: session if session_id == session.record.session_id else None)
    monkeypatch.setattr(paper_engine, "_runtime_monitoring_enabled", lambda: False)
    monkeypatch.setattr(paper_engine, "can_execute_sensitive_telegram_action", lambda *args, **kwargs: True)
    monkeypatch.setattr(paper_engine, "backtester", SimpleNamespace(baixar_dados_historicos=lambda symbol=None: _paper_df()))
    monkeypatch.setattr(storage, "DB_NAME", str(trades_db))
    monkeypatch.setattr(paper_engine, "obter_trades_paper_abertos", lambda symbol=None, session_id=None: storage.obter_trades_paper_abertos(symbol=symbol, session_id=session_id))
    monkeypatch.setattr(paper_engine, "classificar_regime", lambda df: {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"})
    monkeypatch.setattr(paper_engine, "esta_em_killzone", lambda: True)
    monkeypatch.setattr(
        paper_engine,
        "_obter_sinal_paper_sol",
        lambda: {"direcao": "COMPRA", "entrada": 100.0, "stop_loss": 95.0, "take_profit": 110.0, "rr": 2.0, "motivo": "ok"},
    )
    monkeypatch.setattr(paper_engine, "tomar_decisao", lambda *args, **kwargs: {"volume_status": "ALTO", "motivo": "ok", "rsi": 50})
    monkeypatch.setattr(paper_engine, "calcular_tamanho_posicao", lambda capital, risco, entrada, stop: (1.0, 5.0))

    original_registrar = paper_engine.registrar_trade_paper
    captured = {}
    call_count = {"n": 0}

    open_df = _paper_df()
    close_df = _paper_df().copy()
    close_df.loc[:, "high"] = [120.0, 121.0, 122.0]

    def _captura_trade_paper(*args, **kwargs):
        captured.update(kwargs)
        return original_registrar(*args, **kwargs)

    monkeypatch.setattr(paper_engine, "registrar_trade_paper", _captura_trade_paper)
    monkeypatch.setattr(
        paper_engine,
        "backtester",
        SimpleNamespace(
            baixar_dados_historicos=lambda symbol=None: (open_df if call_count["n"] == 0 else close_df)
        ),
    )

    import asyncio

    asyncio.run(paper_engine.monitorar_paper_sol(ctx))
    call_count["n"] += 1
    assert captured["entry_spread_cost"] == pytest.approx(0.05, rel=1e-9)
    assert captured["entry_slippage_cost"] == pytest.approx(0.05, rel=1e-9)

    with sqlite3.connect(trades_db) as conn:
        row = conn.execute(
            "SELECT entry_spread_cost, entry_slippage_cost FROM trades WHERE tipo = 'paper' AND simbolo = 'SOLUSDT' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row == pytest.approx((0.05, 0.05), rel=1e-9)

    observed_open = paper_engine._coletar_runtime_observed_state(
        session=session,
        decision=session.decision,
        df=open_df,
        trades_abertos=storage.obter_trades_paper_abertos(symbol="SOLUSDT", session_id=session.record.session_id),
        preco_atual=100.0,
        regime_info={"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"},
    )
    assert observed_open["open_positions"] == 1
    assert observed_open["paper_capital_used"] == Decimal("5")
    assert observed_open["risk_per_trade_percent"] == Decimal("0.05")
    assert len(observed_open["observed_costs"]) == 4
    assert Decimal(str(observed_open["observed_costs"]["spread_bps"])) == Decimal("5")
    assert Decimal(str(observed_open["observed_costs"]["slippage_bps"])) == Decimal("5")

    asyncio.run(paper_engine.monitorar_paper_sol(ctx))
    call_count["n"] += 1

    with sqlite3.connect(trades_db) as conn:
        row = conn.execute(
            """
            SELECT entry_spread_cost, entry_slippage_cost, exit_spread_cost, exit_slippage_cost, spread_cost, slippage_cost
            FROM trades
            WHERE tipo = 'paper' AND simbolo = 'SOLUSDT'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    assert row is not None
    assert row[0] == pytest.approx(0.05, rel=1e-9)
    assert row[1] == pytest.approx(0.05, rel=1e-9)
    assert row[2] == pytest.approx(0.055, rel=1e-9)
    assert row[3] == pytest.approx(0.055, rel=1e-9)
    assert ((row[4]) / (100.0 + 110.0)) * 10000 == pytest.approx(5.0, rel=1e-9)
    assert ((row[5]) / (100.0 + 110.0)) * 10000 == pytest.approx(5.0, rel=1e-9)


def test_reconciliacao_retoma_apos_falha_entre_runtime_e_snapshot(monkeypatch, tmp_path):
    import storage

    trades_db = tmp_path / "paper_trades_resume.db"
    monkeypatch.setattr(storage, "DB_NAME", str(trades_db))
    storage.inicializar_banco(str(trades_db))

    store = _store(tmp_path)
    session = _session(store, session_id="resume-snapshot")
    contexto = _DummyContext({"chat_id": 123, "user_id": 123, "chat_type": "private", "session_id": session.record.session_id})
    monkeypatch.setattr(paper_engine, "obter_outbox_paper_pendentes", lambda session_id=None: storage.obter_outbox_paper_pendentes(session_id=session_id, db_name=str(trades_db)))
    monkeypatch.setattr(paper_engine, "atualizar_outbox_paper_trade", lambda event_id, **kwargs: storage.atualizar_outbox_paper_trade(event_id, db_name=str(trades_db), **kwargs))
    monkeypatch.setattr(storage, "DB_NAME", str(trades_db))
    monkeypatch.setattr(paper_engine, "obter_trades_paper_abertos", lambda symbol=None, session_id=None: storage.obter_trades_paper_abertos(symbol=symbol, session_id=session_id))

    def _fake_evaluate_snapshot(self, snapshot, decision=None, idempotency_key=None, limits=None):
        self._store.append_snapshot(
            self.record.session_id,
            snapshot=getattr(snapshot, "as_dict", lambda: snapshot)(),
            decision_hash=self.decision.decision_hash,
            evidence_hash=self.decision.evidence_hash,
            result_status="APPROVED",
            idempotency_key=idempotency_key,
        )
        return SimpleNamespace(monitoring_decision=SimpleNamespace(status="APPROVED"), session=self.record, approved=True)

    monkeypatch.setattr(type(session), "evaluate_snapshot", _fake_evaluate_snapshot, raising=False)

    agora = datetime.now(timezone.utc)
    candle_time = agora - timedelta(minutes=5)
    trade_id = storage.registrar_trade_paper(
        "SOLUSDT",
        "COMPRA",
        100.0,
        95.0,
        110.0,
        1.0,
        100.0,
        2.0,
        session_id=session.record.session_id,
        idempotency_key="idem-resume-open",
        candle_close_time=candle_time,
        signal_identity="signal-resume-open",
        preco_base=100.0,
        fill_price=100.0,
        entry_fee=0.0,
        entry_spread_cost=0.05,
        entry_slippage_cost=0.05,
        spread_cost=0.05,
        slippage_cost=0.05,
        outbox_event_factory=lambda trade_id, timestamp: paper_engine._paper_runtime_outbox_record(
            paper_engine._paper_runtime_outbox_payload(
                operation_type="OPEN",
                trade_id=trade_id,
                session_id=session.record.session_id,
                candle_close_time=candle_time,
                idempotency_key=f"open:{trade_id}",
                runtime_events=[{"event_type": paper_engine.PaperRuntimeEventType.TRADE_RECORDED.value, "result": "OPENED", "idempotency_key": f"open-event:{trade_id}", "payload": {"action": "OPEN", "trade_id": trade_id}}],
                snapshot_context={"preco_atual": 100.0, "regime_info": {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"}, "data_fresh": True},
                telegram_text="Paper SOL aberto",
                telegram_chat_id=123,
            )
        ),
        db_name=str(trades_db),
    )
    assert trade_id is not None

    state = {"fail_snapshot": True}

    def _update_fail_snapshot(event_id, **kwargs):
        if kwargs.get("snapshot_applied_at_utc") is not None and state["fail_snapshot"]:
            state["fail_snapshot"] = False
            return False
        return storage.atualizar_outbox_paper_trade(event_id, db_name=str(trades_db), **kwargs)

    monkeypatch.setattr(paper_engine, "atualizar_outbox_paper_trade", _update_fail_snapshot)

    import asyncio

    with pytest.raises(PaperRuntimeSessionError):
        asyncio.run(paper_engine._reconciliar_paper_runtime_outbox(contexto, session, session_scope_id=session.record.session_id, chat_id=123))

    with sqlite3.connect(trades_db) as conn:
        row = conn.execute("SELECT status, runtime_delivered_at_utc, snapshot_applied_at_utc, telegram_sent_at_utc FROM paper_trade_outbox WHERE event_id = (SELECT event_id FROM paper_trade_outbox ORDER BY id DESC LIMIT 1)").fetchone()
    assert row[0] == "DELIVERED"
    assert row[1] is not None
    assert row[2] is None
    assert row[3] is None

    monkeypatch.setattr(paper_engine, "atualizar_outbox_paper_trade", lambda event_id, **kwargs: storage.atualizar_outbox_paper_trade(event_id, db_name=str(trades_db), **kwargs))
    asyncio.run(paper_engine._reconciliar_paper_runtime_outbox(contexto, session, session_scope_id=session.record.session_id, chat_id=123))
    with sqlite3.connect(trades_db) as conn:
        row = conn.execute("SELECT status, snapshot_applied_at_utc, telegram_sent_at_utc FROM paper_trade_outbox WHERE event_id = (SELECT event_id FROM paper_trade_outbox ORDER BY id DESC LIMIT 1)").fetchone()
    assert row[0] == "NOTIFIED"
    assert row[1] is not None
    assert row[2] is not None


def test_reconciliacao_retoma_apos_falha_entre_snapshot_e_telegram(monkeypatch, tmp_path):
    import storage

    trades_db = tmp_path / "paper_trades_resume2.db"
    monkeypatch.setattr(storage, "DB_NAME", str(trades_db))
    storage.inicializar_banco(str(trades_db))

    store = _store(tmp_path)
    session = _session(store, session_id="resume-telegram")
    contexto = _DummyContext({"chat_id": 123, "user_id": 123, "chat_type": "private", "session_id": session.record.session_id})
    monkeypatch.setattr(paper_engine, "obter_outbox_paper_pendentes", lambda session_id=None: storage.obter_outbox_paper_pendentes(session_id=session_id, db_name=str(trades_db)))
    monkeypatch.setattr(paper_engine, "atualizar_outbox_paper_trade", lambda event_id, **kwargs: storage.atualizar_outbox_paper_trade(event_id, db_name=str(trades_db), **kwargs))
    monkeypatch.setattr(storage, "DB_NAME", str(trades_db))
    monkeypatch.setattr(paper_engine, "obter_trades_paper_abertos", lambda symbol=None, session_id=None: storage.obter_trades_paper_abertos(symbol=symbol, session_id=session_id))
    monkeypatch.setattr(type(session), "evaluate_snapshot", lambda self, snapshot, decision=None, idempotency_key=None, limits=None: SimpleNamespace(monitoring_decision=SimpleNamespace(status="APPROVED"), session=self.record, approved=True), raising=False)

    agora = datetime.now(timezone.utc)
    candle_time = agora - timedelta(minutes=5)
    storage.registrar_trade_paper(
        "SOLUSDT",
        "COMPRA",
        100.0,
        95.0,
        110.0,
        1.0,
        100.0,
        2.0,
        session_id=session.record.session_id,
        idempotency_key="idem-resume2-open",
        candle_close_time=candle_time,
        signal_identity="signal-resume2-open",
        preco_base=100.0,
        fill_price=100.0,
        entry_fee=0.0,
        entry_spread_cost=0.05,
        entry_slippage_cost=0.05,
        spread_cost=0.05,
        slippage_cost=0.05,
        outbox_event_factory=lambda trade_id, timestamp: paper_engine._paper_runtime_outbox_record(
            paper_engine._paper_runtime_outbox_payload(
                operation_type="OPEN",
                trade_id=trade_id,
                session_id=session.record.session_id,
                candle_close_time=candle_time,
                idempotency_key=f"open2:{trade_id}",
                runtime_events=[{"event_type": paper_engine.PaperRuntimeEventType.TRADE_RECORDED.value, "result": "OPENED", "idempotency_key": f"open2-event:{trade_id}", "payload": {"action": "OPEN", "trade_id": trade_id}}],
                snapshot_context={"preco_atual": 100.0, "regime_info": {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"}, "data_fresh": True},
                telegram_text="Paper SOL aberto",
                telegram_chat_id=123,
            )
        ),
        db_name=str(trades_db),
    )

    state = {"fail_telegram": True}

    def _update_fail_telegram(event_id, **kwargs):
        if kwargs.get("telegram_sent_at_utc") is not None and state["fail_telegram"]:
            state["fail_telegram"] = False
            return False
        return storage.atualizar_outbox_paper_trade(event_id, db_name=str(trades_db), **kwargs)

    monkeypatch.setattr(paper_engine, "atualizar_outbox_paper_trade", _update_fail_telegram)
    import asyncio

    with pytest.raises(PaperRuntimeSessionError):
        asyncio.run(paper_engine._reconciliar_paper_runtime_outbox(contexto, session, session_scope_id=session.record.session_id, chat_id=123))
    with sqlite3.connect(trades_db) as conn:
        row = conn.execute("SELECT status, snapshot_applied_at_utc, telegram_sent_at_utc FROM paper_trade_outbox ORDER BY id DESC LIMIT 1").fetchone()
    assert row[0] == "DELIVERED"
    assert row[1] is not None
    assert row[2] is None

    monkeypatch.setattr(paper_engine, "atualizar_outbox_paper_trade", lambda event_id, **kwargs: storage.atualizar_outbox_paper_trade(event_id, db_name=str(trades_db), **kwargs))
    asyncio.run(paper_engine._reconciliar_paper_runtime_outbox(contexto, session, session_scope_id=session.record.session_id, chat_id=123))
    with sqlite3.connect(trades_db) as conn:
        row = conn.execute("SELECT status, snapshot_applied_at_utc, telegram_sent_at_utc FROM paper_trade_outbox ORDER BY id DESC LIMIT 1").fetchone()
    assert row[0] == "NOTIFIED"
    assert row[1] is not None
    assert row[2] is not None


@pytest.mark.parametrize(
    "blocked_field",
    [
        "runtime_delivered_at_utc",
        "snapshot_applied_at_utc",
        "telegram_sent_at_utc",
    ],
)
def test_reconciliacao_bloqueia_outbox_sem_evento_existente(monkeypatch, tmp_path, blocked_field):
    import storage

    trades_db = tmp_path / f"paper_trades_missing_{blocked_field}.db"
    monkeypatch.setattr(storage, "DB_NAME", str(trades_db))
    storage.inicializar_banco(str(trades_db))

    store = _store(tmp_path)
    session = _session(store, session_id=f"missing-{blocked_field}")
    contexto = _DummyContext({"chat_id": 123, "user_id": 123, "chat_type": "private", "session_id": session.record.session_id})
    monkeypatch.setattr(paper_engine, "obter_outbox_paper_pendentes", lambda session_id=None: [
        paper_engine._paper_runtime_outbox_record(
            paper_engine._paper_runtime_outbox_payload(
                operation_type="OPEN",
                trade_id=1,
                session_id=session.record.session_id,
                candle_close_time=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
                idempotency_key=f"idem-{blocked_field}",
                runtime_events=[],
                snapshot_context={
                    "preco_atual": 100.0,
                    "regime_info": {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"},
                    "data_fresh": True,
                },
                telegram_text="Paper SOL aberto",
                telegram_chat_id=123,
            )
        )
    ])

    def _fake_update(event_id, **kwargs):
        if "runtime_delivered_at_utc" in kwargs:
            return blocked_field != "runtime_delivered_at_utc"
        if "snapshot_applied_at_utc" in kwargs:
            return blocked_field != "snapshot_applied_at_utc"
        if "telegram_sent_at_utc" in kwargs:
            return blocked_field != "telegram_sent_at_utc"
        return True

    monkeypatch.setattr(paper_engine, "atualizar_outbox_paper_trade", _fake_update)
    monkeypatch.setattr(
        paper_engine,
        "build_snapshot_from_observed_state",
        lambda **kwargs: _snapshot(session),
    )
    monkeypatch.setattr(
        type(session),
        "evaluate_snapshot",
        lambda self, snapshot, decision=None, idempotency_key=None, limits=None: SimpleNamespace(
            monitoring_decision=SimpleNamespace(status="APPROVED"),
            session=self.record,
            approved=True,
        ),
        raising=False,
    )

    async def _telegram_nao_deveria_ser_enviado(*args, **kwargs):  # pragma: no cover - guard rail
        raise AssertionError("telegram nao deveria ser enviado")

    if blocked_field in {"runtime_delivered_at_utc", "snapshot_applied_at_utc"}:
        monkeypatch.setattr(contexto.bot, "send_message", _telegram_nao_deveria_ser_enviado)

    import asyncio

    with pytest.raises(PaperRuntimeSessionError):
        asyncio.run(
            paper_engine._reconciliar_paper_runtime_outbox(
                contexto,
                session,
                session_scope_id=session.record.session_id,
                chat_id=123,
            )
        )
    if blocked_field != "telegram_sent_at_utc":
        assert contexto.bot.sent == []


def test_estado_desconhecido_bloqueia_runtime(monkeypatch, tmp_path):
    import storage

    store = _store(tmp_path)
    session = _session(store, session_id="unknown-state")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE paper_runtime_sessions SET state = ? WHERE session_id = ?", ("CORRUPTED", session.record.session_id))
        conn.commit()
    with pytest.raises((PaperRuntimeSessionError, ValueError)):
        paper_engine.get_monitored_session(session_id=session.record.session_id, store=store)


def test_timestamp_futuro_bloqueia_freshness(monkeypatch, tmp_path):
    import storage

    trades_db = tmp_path / "paper_trades_future.db"
    monkeypatch.setattr(storage, "DB_NAME", str(trades_db))
    storage.inicializar_banco(str(trades_db))

    store = _store(tmp_path)
    session = _session(store, session_id="future-candle")
    contexto = _DummyContext({"chat_id": 123, "user_id": 123, "chat_type": "private", "session_id": session.record.session_id})
    monkeypatch.setattr(paper_engine, "get_monitored_session", lambda session_id=None, decision_hash=None, store=None: session if session_id == session.record.session_id else None)
    monkeypatch.setattr(paper_engine, "_runtime_monitoring_enabled", lambda: False)
    monkeypatch.setattr(paper_engine, "can_execute_sensitive_telegram_action", lambda *args, **kwargs: True)
    monkeypatch.setattr(paper_engine, "backtester", SimpleNamespace(baixar_dados_historicos=lambda symbol=None: _paper_df()))
    monkeypatch.setattr(paper_engine, "obter_trades_paper_abertos", lambda symbol=None, session_id=None: storage.obter_trades_paper_abertos(symbol=symbol, session_id=session_id))
    monkeypatch.setattr(paper_engine, "classificar_regime", lambda df: {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"})
    monkeypatch.setattr(paper_engine, "esta_em_killzone", lambda: True)
    monkeypatch.setattr(paper_engine, "_obter_sinal_paper_sol", lambda: {"direcao": "COMPRA", "entrada": 100.0, "stop_loss": 95.0, "take_profit": 110.0, "rr": 2.0, "motivo": "ok"})
    monkeypatch.setattr(paper_engine, "tomar_decisao", lambda *args, **kwargs: {"volume_status": "ALTO", "motivo": "ok", "rsi": 50})
    monkeypatch.setattr(paper_engine, "calcular_tamanho_posicao", lambda capital, risco, entrada, stop: (1.0, 5.0))
    monkeypatch.setattr(
        paper_engine,
        "registrar_trade_paper",
        lambda *args, **kwargs: storage.registrar_trade_paper(
            *args,
            **kwargs,
            db_name=str(trades_db),
        ),
    )
    monkeypatch.setattr(
        paper_engine,
        "finalizar_trade_paper",
        lambda *args, **kwargs: storage.finalizar_trade_paper(*args, **kwargs, db_name=str(trades_db)),
    )
    captured = {}

    def _fake_build_snapshot_from_observed_state(**kwargs):
        captured["data_fresh"] = kwargs["observed"]["data_fresh"]
        return _snapshot(
            session,
            data_fresh=kwargs["observed"]["data_fresh"],
            paper_capital_used=Decimal("10"),
            session_drawdown_percent=Decimal("0"),
            risk_per_trade_percent=Decimal("0.5"),
        )

    monkeypatch.setattr(paper_engine, "build_snapshot_from_observed_state", _fake_build_snapshot_from_observed_state)
    monkeypatch.setattr(type(session), "evaluate_snapshot", lambda self, snapshot, decision=None, idempotency_key=None, limits=None: SimpleNamespace(monitoring_decision=SimpleNamespace(status="APPROVED"), session=self.record, approved=True), raising=False)
    import asyncio

    snapshot_observed = paper_engine._coletar_runtime_observed_state(
        session=session,
        decision=session.decision,
        df=_paper_df().assign(close_time=datetime.now(timezone.utc) + timedelta(minutes=10)),
        trades_abertos=[],
        preco_atual=100.0,
        regime_info={"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"},
    )
    assert snapshot_observed["data_fresh"] is False


def test_trade_aberto_persistido_expoe_tipo_status_e_limites_reais(monkeypatch, tmp_path):
    import storage

    trades_db = tmp_path / "paper_trades_open_contract.db"
    monkeypatch.setattr(storage, "DB_NAME", str(trades_db))
    storage.inicializar_banco(str(trades_db))

    store = _store(tmp_path)
    session = _session(store, session_id="open-contract")

    storage.registrar_trade_paper(
        "SOLUSDT",
        "COMPRA",
        100.0,
        95.0,
        110.0,
        1.0,
        6000.0,
        2.0,
        session_id=session.record.session_id,
        idempotency_key="open-contract-1",
        candle_close_time="2026-07-11T12:00:00+00:00",
        signal_identity="open-contract-1",
        preco_base=100.0,
        fill_price=100.0,
        entry_fee=0.4,
        entry_spread_cost=0.05,
        entry_slippage_cost=0.05,
        spread_cost=0.05,
        slippage_cost=0.05,
        db_name=str(trades_db),
    )
    storage.registrar_trade_paper(
        "SOLUSDT",
        "COMPRA",
        100.0,
        95.0,
        110.0,
        1.0,
        5000.0,
        2.0,
        session_id=session.record.session_id,
        idempotency_key="open-contract-2",
        candle_close_time="2026-07-11T12:05:00+00:00",
        signal_identity="open-contract-2",
        preco_base=100.0,
        fill_price=100.0,
        entry_fee=0.4,
        entry_spread_cost=0.05,
        entry_slippage_cost=0.05,
        spread_cost=0.05,
        slippage_cost=0.05,
        db_name=str(trades_db),
    )

    trades_abertos = storage.obter_trades_paper_abertos("SOLUSDT")
    assert all(trade["tipo"] == "paper" for trade in trades_abertos)
    assert all(trade["status"] == "open" for trade in trades_abertos)

    observed = paper_engine._coletar_runtime_observed_state(
        session=session,
        decision=session.decision,
        df=_paper_df(),
        trades_abertos=trades_abertos,
        preco_atual=102.0,
        regime_info={"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"},
    )

    assert observed["open_positions"] == 2
    assert observed["paper_capital_used"] == Decimal("11000")
    assert observed["risk_per_trade_percent"] == Decimal("60")

    snapshot = build_snapshot_from_observed_state(
        session=session.record,
        decision=session.decision,
        observed=observed,
        timestamp_utc=datetime(2026, 7, 11, 12, 30, tzinfo=timezone.utc),
    )
    result = session.evaluate_snapshot(snapshot, decision=session.decision)
    assert result.monitoring_decision.status is PromotionStatus.PAPER_SUSPENDED


def test_outbox_json_tampered_bloqueia_reconciliacao(monkeypatch, tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="outbox-json")
    contexto = _DummyContext({"chat_id": 123, "user_id": 123, "chat_type": "private", "session_id": session.record.session_id})
    outbox = paper_engine._paper_runtime_outbox_record(
        paper_engine._paper_runtime_outbox_payload(
            operation_type="OPEN",
            trade_id=1,
            session_id=session.record.session_id,
            candle_close_time=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
            idempotency_key="idem-json",
            runtime_events=[],
            snapshot_context={
                "preco_atual": 100.0,
                "regime_info": {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"},
                "data_fresh": True,
            },
            telegram_text="Paper SOL aberto",
            telegram_chat_id=123,
        )
    )
    outbox["payload_json"] = "{"
    monkeypatch.setattr(paper_engine, "obter_outbox_paper_pendentes", lambda session_id=None: [outbox])
    monkeypatch.setattr(paper_engine, "atualizar_outbox_paper_trade", lambda *args, **kwargs: True)

    import asyncio

    with pytest.raises(PaperRuntimeSessionError):
        asyncio.run(
            paper_engine._reconciliar_paper_runtime_outbox(
                contexto,
                session,
                session_scope_id=session.record.session_id,
                chat_id=123,
            )
        )
    assert contexto.bot.sent == []


def test_outbox_hash_tampered_bloqueia_reconciliacao(monkeypatch, tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="outbox-hash")
    contexto = _DummyContext({"chat_id": 123, "user_id": 123, "chat_type": "private", "session_id": session.record.session_id})
    outbox = paper_engine._paper_runtime_outbox_record(
        paper_engine._paper_runtime_outbox_payload(
            operation_type="OPEN",
            trade_id=1,
            session_id=session.record.session_id,
            candle_close_time=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
            idempotency_key="idem-hash",
            runtime_events=[],
            snapshot_context={
                "preco_atual": 100.0,
                "regime_info": {"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"},
                "data_fresh": True,
            },
            telegram_text="Paper SOL aberto",
            telegram_chat_id=123,
        )
    )
    outbox["request_hash"] = "bad-hash"
    monkeypatch.setattr(paper_engine, "obter_outbox_paper_pendentes", lambda session_id=None: [outbox])
    monkeypatch.setattr(paper_engine, "atualizar_outbox_paper_trade", lambda *args, **kwargs: True)

    import asyncio

    with pytest.raises(PaperRuntimeSessionError):
        asyncio.run(
            paper_engine._reconciliar_paper_runtime_outbox(
                contexto,
                session,
                session_scope_id=session.record.session_id,
                chat_id=123,
            )
        )
    assert contexto.bot.sent == []


@pytest.mark.parametrize(
    "missing_field",
    [
        "data_fresh",
        "session_drawdown_percent",
        "current_loss_streak",
        "open_positions",
        "executed_trades",
        "observed_costs",
        "session_state",
        "paper_capital_used",
        "risk_per_trade_percent",
        "attempted_live",
        "internal_error",
    ],
)
def test_snapshot_requer_campos_observados_explicitos(tmp_path, missing_field):
    store = _store(tmp_path)
    session = _session(store, session_id=f"required-{missing_field}")
    observed = _observed()
    observed.pop(missing_field, None)
    with pytest.raises(PaperRuntimeMonitorError):
        build_snapshot_from_observed_state(
            session=session.record,
            decision=session.decision,
            observed=observed,
            timestamp_utc=datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc),
        )


def test_coleta_runtime_close_time_ausente_desativa_freshness(tmp_path):
    store = _store(tmp_path)
    session = _session(store, session_id="close-missing")
    import pandas as pd

    df = pd.DataFrame(
        {
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000.0, 1000.0],
        }
    )
    observed = paper_engine._coletar_runtime_observed_state(
        session=session,
        decision=session.decision,
        df=df,
        trades_abertos=[],
        preco_atual=102.0,
        regime_info={"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"},
    )
    assert observed["data_fresh"] is False
    assert observed["paper_capital_used"] == Decimal("0")
    assert observed["risk_per_trade_percent"] == Decimal("0")


def test_coleta_runtime_falha_ao_buscar_trades(tmp_path, monkeypatch):
    store = _store(tmp_path)
    session = _session(store, session_id="trades-fail")
    import storage

    monkeypatch.setattr(storage, "obter_ultimos_trades_paper", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(PaperRuntimeSessionError):
        paper_engine._coletar_runtime_observed_state(
            session=session,
            decision=session.decision,
            df=_paper_df(),
            trades_abertos=[],
            preco_atual=102.0,
            regime_info={"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"},
        )


def test_coleta_runtime_prefere_trade_fechado_para_custos(tmp_path, monkeypatch):
    store = _store(tmp_path)
    session = _session(store, session_id="cost-source")
    import storage

    monkeypatch.setattr(
        storage,
        "obter_ultimos_trades_paper",
        lambda *args, **kwargs: [
            {
                "timestamp": "2026-07-11T12:00:00+00:00",
                "status": "open",
                "session_id": session.record.session_id,
                "entry_fee": 0.4,
                "entry_spread_cost": 0.25,
                "entry_slippage_cost": 0.15,
                "spread_cost": 0.25,
                "slippage_cost": 0.15,
            },
            {
                "timestamp": "2026-07-11T11:00:00+00:00",
                "status": "closed",
                "session_id": session.record.session_id,
                "resultado": "GANHO",
                "saida": 110.0,
                "entry_fee": 0.4,
                "exit_fee": 0.4,
                "entry_spread_cost": 0.25,
                "entry_slippage_cost": 0.15,
                "exit_spread_cost": 0.22,
                "exit_slippage_cost": 0.12,
                "spread_cost": 0.47,
                "slippage_cost": 0.27,
                "pnl_bruto": 10.0,
                "custos_totais": 1.0,
                "pnl_liquido": 9.0,
            },
        ],
    )
    observed = paper_engine._coletar_runtime_observed_state(
        session=session,
        decision=session.decision,
        df=_paper_df(),
        trades_abertos=[],
        preco_atual=102.0,
        regime_info={"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"},
    )
    assert observed["observed_costs"]["exit_fee_rate"] > 0


def test_primeira_perda_gera_drawdown_positivo(tmp_path, monkeypatch):
    store = _store(tmp_path)
    session = _session(store, session_id="drawdown-positive")
    import storage

    monkeypatch.setattr(
        storage,
        "obter_ultimos_trades_paper",
        lambda *args, **kwargs: [
            {"lucro_reais": -100.0, "lucro_percent": -1.0, "session_id": session.record.session_id},
        ],
    )
    observed = paper_engine._coletar_runtime_observed_state(
        session=session,
        decision=session.decision,
        df=_paper_df(),
        trades_abertos=[],
        preco_atual=102.0,
        regime_info={"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"},
    )
    assert observed["session_drawdown_percent"] > 0


def test_trades_de_outra_sessao_nao_contaminam_metricas(tmp_path, monkeypatch):
    store = _store(tmp_path)
    session = _session(store, session_id="same-session")
    import storage

    called = {"session_id": None}

    def fake_obter_ultimos_trades_paper(*args, **kwargs):
        called["session_id"] = kwargs.get("session_id")
        return [{"lucro_reais": 50.0, "lucro_percent": 0.5, "session_id": session.record.session_id}]

    monkeypatch.setattr(storage, "obter_ultimos_trades_paper", fake_obter_ultimos_trades_paper)
    observed = paper_engine._coletar_runtime_observed_state(
        session=session,
        decision=session.decision,
        df=_paper_df(),
        trades_abertos=[
            {"id": 1, "session_id": "outra-sessao", "tipo": "paper", "status": "open", "valor_arriscado": 500.0},
            {"id": 2, "session_id": session.record.session_id, "tipo": "paper", "status": "open", "valor_arriscado": 100.0},
        ],
        preco_atual=102.0,
        regime_info={"regime": "BULL", "adx": 30, "volatilidade": "NORMAL"},
    )
    assert called["session_id"] == session.record.session_id
    assert observed["open_positions"] == 1
    assert observed["paper_capital_used"] == Decimal("100")


def test_monitor_snapshot_rollback_total_em_falha_idempotencia(tmp_path, monkeypatch):
    store = _store(tmp_path)
    session = _session(store, session_id="rollback")
    snapshot = _snapshot(session)
    monkeypatch.setattr(store, "_store_idempotent_response", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        session.evaluate_snapshot(snapshot, decision=session.decision, idempotency_key="idem-rollback")
    with sqlite3.connect(store.db_path) as conn:
        snapshot_count = conn.execute("SELECT COUNT(*) FROM paper_runtime_snapshots WHERE session_id = ?", (session.record.session_id,)).fetchone()[0]
        event_count = conn.execute("SELECT COUNT(*) FROM paper_runtime_events WHERE session_id = ?", (session.record.session_id,)).fetchone()[0]
    assert snapshot_count == 0
    assert event_count == 1
    assert store.load_session(session.record.session_id).state is PaperRuntimeState.RUNNING


def test_idempotencia_mesma_chave_papel_divergente_falha(tmp_path, monkeypatch):
    import storage

    monkeypatched_db = str(tmp_path / "trades.db")
    storage.inicializar_banco(monkeypatched_db)
    trade_id = storage.registrar_trade_paper("SOLUSDT", "COMPRA", 100.0, 95.0, 110.0, 1.0, 10.0, 2.0, session_id="sess-1", idempotency_key="idem-trade", db_name=monkeypatched_db)
    assert trade_id is not None
    mesmo_id = storage.registrar_trade_paper("SOLUSDT", "COMPRA", 100.0, 95.0, 110.0, 1.0, 10.0, 2.0, session_id="sess-1", idempotency_key="idem-trade", db_name=monkeypatched_db)
    assert mesmo_id == trade_id
    divergente = storage.registrar_trade_paper("SOLUSDT", "COMPRA", 101.0, 95.0, 110.0, 1.0, 10.0, 2.0, session_id="sess-1", idempotency_key="idem-trade", db_name=monkeypatched_db)
    assert divergente is None


@pytest.mark.parametrize("sequence_to_delete", [2, 3, 4])
def test_truncamento_evento_primeiro_intermediario_ultimo_detectado(tmp_path, sequence_to_delete):
    store = _store(tmp_path)
    session = _session(store, session_id=f"truncate-{sequence_to_delete}")
    session.evaluate_snapshot(_snapshot(session), decision=session.decision)
    session.evaluate_snapshot(_snapshot(session, executed_trades=1), decision=session.decision)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("DELETE FROM paper_runtime_events WHERE session_id = ? AND sequence = ?", (session.record.session_id, sequence_to_delete))
        conn.commit()
    with pytest.raises(PaperRuntimeAuditError):
        store.load_events(session.record.session_id)
