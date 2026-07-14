import sqlite3

import pytest

import storage


def _setup_db(monkeypatch, temp_db_path):
    monkeypatch.setattr(storage, "DB_NAME", temp_db_path, raising=False)
    storage.inicializar_banco(temp_db_path)
    return temp_db_path


def _criar_trade_manual(conn, **kwargs):
    payload = {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "tipo": "paper",
        "simbolo": "SOLUSDT",
        "status": "open",
        "direcao": "COMPRA",
        "resultado": "PENDENTE",
        "score": 0,
        "lucro_percent": 0.0,
        "rr_planejado": 2.0,
        "entrada": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "quantidade": 1.0,
        "valor_arriscado": 100.0,
        "aberto_em": "2026-01-01T00:00:00+00:00",
        "filtros_aplicados": 1,
    }
    payload.update(kwargs)
    cols = ", ".join(payload.keys())
    placeholders = ", ".join("?" for _ in payload)
    conn.execute(f"INSERT INTO trades ({cols}) VALUES ({placeholders})", tuple(payload.values()))


def test_criar_tabelas_e_log_decisao(monkeypatch, temp_db_path):
    _setup_db(monkeypatch, temp_db_path)
    ok = storage.log_decisao(
        symbol="BTCUSDT",
        modo="TESTE",
        decisao="AGUARDAR",
        direcao="N/A",
        preco=100.0,
        regime="BULL",
        adx=25.0,
        volume_status="NEUTRO",
        motivo="teste",
        bloqueado_por="N/A",
        fonte_dados="BINANCE",
        erro="N/A",
    )
    assert ok is True

    with sqlite3.connect(temp_db_path) as conn:
        cursor = conn.cursor()
        tables = {row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "trades" in tables
        assert "decision_logs" in tables
        row = cursor.execute("SELECT symbol, modo, decisao FROM decision_logs ORDER BY id DESC LIMIT 1").fetchone()
        assert row == ("BTCUSDT", "TESTE", "AGUARDAR")


def test_log_decisao_falha(monkeypatch, temp_db_path):
    _setup_db(monkeypatch, temp_db_path)

    class FakeConn:
        def __enter__(self):
            raise sqlite3.OperationalError("boom")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(storage.sqlite3, "connect", lambda *args, **kwargs: FakeConn())
    assert storage.log_decisao(symbol="BTCUSDT", modo="TESTE", decisao="AGUARDAR") is False


def test_buscar_ultimos_e_ultimo_decision_logs(monkeypatch, temp_db_path):
    _setup_db(monkeypatch, temp_db_path)
    for idx in range(4):
        storage.log_decisao(
            timestamp=f"2026-01-01T00:00:0{idx}+00:00",
            symbol=f"BTC{idx}",
            modo="TESTE" if idx < 3 else "OUTRO",
            decisao="AGUARDAR",
            motivo=f"log-{idx}",
            bloqueado_por="N/A",
        )

    logs = storage.buscar_ultimos_decision_logs(limite=2)
    assert len(logs) == 2
    assert logs[0]["symbol"] == "BTC3"
    assert logs[1]["symbol"] == "BTC2"

    filtrados = storage.buscar_ultimos_decision_logs(limite=5, modos=["TESTE"])
    assert all(log["modo"] == "TESTE" for log in filtrados)
    assert storage.buscar_ultimo_decision_log(modos=["TESTE"])["symbol"] == "BTC2"


def test_buscar_logs_vazios_e_falha(monkeypatch, temp_db_path):
    _setup_db(monkeypatch, temp_db_path)
    assert storage.buscar_ultimos_decision_logs(limite=5) == []
    assert storage.buscar_ultimo_decision_log() is None

    class FakeConn:
        def __enter__(self):
            raise sqlite3.OperationalError("boom")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(storage.sqlite3, "connect", lambda *args, **kwargs: FakeConn())
    assert storage.buscar_ultimos_decision_logs(limite=5) == []


def test_trade_paper_workflow(monkeypatch, temp_db_path):
    _setup_db(monkeypatch, temp_db_path)
    trade_id = storage.registrar_trade_paper(
        symbol="SOLUSDT",
        direcao="COMPRA",
        entrada=100,
        stop_loss=95,
        take_profit=110,
        quantidade=1.5,
        valor_arriscado=100,
        rr_planejado=2.0,
        filtros_aplicados=True,
        entry_spread_cost=0.25,
        entry_slippage_cost=0.15,
        spread_cost=0.25,
        slippage_cost=0.15,
    )
    assert trade_id is not None

    with sqlite3.connect(temp_db_path) as conn:
        row = conn.execute(
            """
            SELECT entry_spread_cost, entry_slippage_cost, exit_spread_cost, exit_slippage_cost, spread_cost, slippage_cost
            FROM trades
            WHERE id = ?
            """,
            (trade_id,),
        ).fetchone()
    assert row == (0.25, 0.15, None, None, 0.25, 0.15)

    abertos = storage.obter_trades_paper_abertos("SOLUSDT")
    assert len(abertos) == 1
    assert abertos[0]["id"] == trade_id

    count_abertos = storage.contar_trades_abertos_paper("SOLUSDT")
    assert count_abertos == 1

    close_ok = storage.finalizar_trade_paper(
        trade_id,
        110,
        10.0,
        15.0,
        "GANHO",
        "TAKE_PROFIT",
        idempotency_key="idem-close",
    )
    assert close_ok is True
    assert storage.contar_trades_abertos_paper("SOLUSDT") == 0
    assert storage.finalizar_trade_paper(
        trade_id,
        110,
        10.0,
        15.0,
        "GANHO",
        "TAKE_PROFIT",
        idempotency_key="idem-close",
    ) is True
    with pytest.raises(storage.PaperTradeFinalizationError):
        storage.finalizar_trade_paper(trade_id, 111, 11.0, 16.0, "GANHO", "TAKE_PROFIT", idempotency_key="idem-close")

    stats = storage.obter_paper_stats("SOLUSDT")
    assert stats is not None
    assert stats["todas"]["total"] == 1
    assert stats["filtradas"]["total"] == 1

    trade_list = storage.buscar_trades_paper(limite=10, symbol="SOLUSDT")
    assert len(trade_list) == 1
    assert trade_list[0]["status"] == "closed"
    with sqlite3.connect(temp_db_path) as conn:
        row = conn.execute(
            "SELECT preco_base, fill_price, entry_fee, entry_spread_cost, entry_slippage_cost, exit_spread_cost, exit_slippage_cost, close_idempotency_key, close_idempotency_hash, pnl_liquido FROM trades WHERE id = ?",
            (trade_id,),
        ).fetchone()
    assert row[0] == 100.0
    assert row[1] is not None
    assert row[2] is not None
    assert row[3] is not None
    assert row[4] is not None
    assert row[5] is not None
    assert row[6] is not None
    assert row[7] == "idem-close"
    assert row[8] is not None
    assert row[9] is not None


def test_contar_fechados_hoje_e_paper_stats_sem_filtrado(monkeypatch, temp_db_path):
    _setup_db(monkeypatch, temp_db_path)
    hoje_iso = storage._agora_iso()
    with sqlite3.connect(temp_db_path) as conn:
        _criar_trade_manual(
            conn,
            status="closed",
            resultado="GANHO",
            lucro_percent=5.0,
            lucro_reais=50.0,
            fechado_em=hoje_iso,
            filtros_aplicados=0,
        )
        conn.commit()

    assert storage.contar_trades_fechados_hoje("SOLUSDT") == 1

    stats = storage.obter_paper_stats("SOLUSDT")
    assert stats is not None
    assert stats["filtradas"] is None
    assert stats["todas"]["profit_factor"] == float("inf")


def test_obter_paper_stats_vazio(monkeypatch, temp_db_path):
    _setup_db(monkeypatch, temp_db_path)
    assert storage.obter_paper_stats("SOLUSDT") is None


def test_buscar_trades_paper_vazio_e_erro(monkeypatch, temp_db_path):
    _setup_db(monkeypatch, temp_db_path)
    assert storage.buscar_trades_paper(limite=10, symbol="SOLUSDT") == []
    assert storage.obter_trades_paper_abertos("SOLUSDT") == []
    assert storage.contar_trades_abertos_paper("SOLUSDT") == 0
    assert storage.contar_trades_fechados_hoje("SOLUSDT") == 0

    class FakeConn:
        def __enter__(self):
            raise sqlite3.OperationalError("boom")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(storage.sqlite3, "connect", lambda *args, **kwargs: FakeConn())
    assert storage.buscar_trades_paper(limite=10, symbol="SOLUSDT") == []
    assert storage.obter_trades_paper_abertos("SOLUSDT") == []


def test_registrar_e_finalizar_trade_paper_falhas(monkeypatch, temp_db_path):
    _setup_db(monkeypatch, temp_db_path)

    class FakeConn:
        def __enter__(self):
            raise sqlite3.OperationalError("boom")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(storage.sqlite3, "connect", lambda *args, **kwargs: FakeConn())
    assert storage.registrar_trade_paper("SOLUSDT", "COMPRA", 1, 1, 2, 1, 1, 2.0) is None
    assert storage.finalizar_trade_paper(1, 2, 1.0, 1.0, "GANHO", "TAKE") is False


def test_metricas_trade_history_and_validacao(monkeypatch, temp_db_path):
    _setup_db(monkeypatch, temp_db_path)
    storage.registrar_trade_paper(
        symbol="SOLUSDT",
        direcao="COMPRA",
        entrada=100,
        stop_loss=95,
        take_profit=110,
        quantidade=1,
        valor_arriscado=100,
        rr_planejado=2.0,
        filtros_aplicados=True,
    )
    storage.finalizar_trade_paper(1, 110, 10.0, 10.0, "GANHO", "TAKE_PROFIT")

    trades = storage.obter_ultimos_trades_paper("SOLUSDT", limite=30, db_name=temp_db_path)
    metricas = storage.calcular_metricas_trade_history(trades)
    assert metricas["total"] == 1
    assert metricas["profit_factor"] == float("inf")
    assert storage.calcular_metricas_trade_history([]) is None

    ok = storage.registrar_validacao_sol(
        total_trades=1,
        profit_factor=metricas["profit_factor"],
        win_rate=100.0,
        drawdown_max=0.0,
        resultado="OK",
        comparacao_walkforward="walkforward",
        db_name=temp_db_path,
    )
    assert ok is True

    with sqlite3.connect(temp_db_path) as conn:
        cursor = conn.cursor()
        row = cursor.execute("SELECT total_trades, resultado FROM validacoes_sol ORDER BY id DESC LIMIT 1").fetchone()
        assert row == (1, "OK")


def test_metricas_trade_history_e_validacao_falha(monkeypatch, temp_db_path):
    _setup_db(monkeypatch, temp_db_path)

    class FakeConn:
        def __enter__(self):
            raise sqlite3.OperationalError("boom")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(storage.sqlite3, "connect", lambda *args, **kwargs: FakeConn())
    assert storage.registrar_validacao_sol(1, 1.0, 100.0, 0.0, "OK", "wf", db_name=temp_db_path) is False


def test_salvar_trade_and_estatisticas(monkeypatch, temp_db_path):
    _setup_db(monkeypatch, temp_db_path)
    ok1 = storage.salvar_trade("COMPRA", "GANHO", 8, 2.5, 1.5, db_name=temp_db_path)
    ok2 = storage.salvar_trade("VENDA", "PERDA", 4, -1.0, 1.0, db_name=temp_db_path)
    assert ok1 is True
    assert ok2 is True

    stats = storage.obter_estatisticas(db_name=temp_db_path)
    assert stats is not None
    assert stats["total"] == 2
    assert stats["vitorias"] == 1
    assert stats["derrotas"] == 1
    assert stats["win_rate"] == 50.0


def test_obter_estatisticas_vazio_e_erro(monkeypatch, temp_db_path):
    _setup_db(monkeypatch, temp_db_path)
    assert storage.obter_estatisticas(db_name=temp_db_path) is None

    class FakeConn:
        def __enter__(self):
            raise sqlite3.OperationalError("boom")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(storage.sqlite3, "connect", lambda *args, **kwargs: FakeConn())
    assert storage.obter_estatisticas(db_name=temp_db_path) is None


def test_reset_db(monkeypatch, temp_db_path):
    _setup_db(monkeypatch, temp_db_path)
    storage.salvar_trade("COMPRA", "GANHO", 8, 2.5, 1.5, db_name=temp_db_path)
    assert storage.obter_estatisticas(db_name=temp_db_path)["total"] == 1
    ok = storage.reset_db(db_name=temp_db_path)
    assert ok is True
    assert storage.obter_estatisticas(db_name=temp_db_path) is None


def test_reset_db_falha(monkeypatch, temp_db_path):
    _setup_db(monkeypatch, temp_db_path)

    class FakeConn:
        def __enter__(self):
            raise sqlite3.OperationalError("boom")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(storage.sqlite3, "connect", lambda *args, **kwargs: FakeConn())
    assert storage.reset_db(db_name=temp_db_path) is False


def test_migracao_adiciona_colunas_sem_perder_dados(temp_db_path):
    with sqlite3.connect(temp_db_path) as conn:
        conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, direcao TEXT)")
        conn.execute("INSERT INTO trades (timestamp, direcao) VALUES (?, ?)", ("2026-01-01T00:00:00+00:00", "COMPRA"))
        conn.commit()

    assert storage.inicializar_banco(temp_db_path) is True

    with sqlite3.connect(temp_db_path) as conn:
        cursor = conn.cursor()
        colunas = {row[1] for row in cursor.execute("PRAGMA table_info(trades)").fetchall()}
        assert {"tipo", "simbolo", "status", "entrada", "stop_loss", "take_profit", "filtros_aplicados"} <= colunas
        assert cursor.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1


def test_inicializar_banco_falha(monkeypatch, temp_db_path):
    class FakeConn:
        def __enter__(self):
            raise sqlite3.OperationalError("boom")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(storage.sqlite3, "connect", lambda *args, **kwargs: FakeConn())
    assert storage.inicializar_banco(temp_db_path) is False
