import logging
import sqlite3
from datetime import datetime, timezone


DB_NAME = "trades.db"
STRATEGY_VERSION_DEFAULT = "v2_risk_safe"


def _agora_iso():
    return datetime.now(timezone.utc).isoformat()


def _normalizar(valor, padrao="N/A"):
    if valor is None:
        return padrao
    if isinstance(valor, str) and not valor.strip():
        return padrao
    return valor


def criar_tabelas(db_name=DB_NAME):
    try:
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    symbol TEXT,
                    modo TEXT,
                    decisao TEXT,
                    direcao TEXT,
                    preco REAL,
                    regime TEXT,
                    adx REAL,
                    volume_status TEXT,
                    motivo TEXT,
                    bloqueado_por TEXT,
                    fonte_dados TEXT,
                    erro TEXT,
                    strategy_version TEXT DEFAULT 'v2_risk_safe'
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_decision_logs_timestamp ON decision_logs(timestamp DESC)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_decision_logs_modo_timestamp ON decision_logs(modo, timestamp DESC)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_decision_logs_decisao_timestamp ON decision_logs(decisao, timestamp DESC)"
            )
            conn.commit()
    except Exception as exc:
        logging.warning(f"Falha ao criar tabelas de observabilidade: {exc}")


def inicializar_banco(db_name=DB_NAME):
    """
    Cria as tabelas do bot e executa migrações leves automaticamente.
    """
    try:
        criar_tabelas(db_name=db_name)
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    session_id TEXT,
                    idempotency_key TEXT,
                    idempotency_hash TEXT,
                    direcao TEXT NOT NULL,
                    resultado TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    lucro_percent REAL NOT NULL,
                    rr_planejado REAL NOT NULL
                )
                """
            )
            colunas = {row[1] for row in cursor.execute("PRAGMA table_info(trades)").fetchall()}
            alteracoes = {
                "tipo": "TEXT DEFAULT 'manual'",
                "simbolo": "TEXT DEFAULT 'BTCUSDT'",
                "status": "TEXT DEFAULT 'closed'",
                "entrada": "REAL",
                "stop_loss": "REAL",
                "take_profit": "REAL",
                "quantidade": "REAL",
                "valor_arriscado": "REAL",
                "aberto_em": "TEXT",
                "fechado_em": "TEXT",
                "saida": "REAL",
                "lucro_reais": "REAL",
                "motivo_saida": "TEXT",
                "filtros_aplicados": "INTEGER DEFAULT 1",
                "session_id": "TEXT",
                "idempotency_key": "TEXT",
                "idempotency_hash": "TEXT",
            }
            for coluna, tipo in alteracoes.items():
                if coluna not in colunas:
                    try:
                        cursor.execute(f"ALTER TABLE trades ADD COLUMN {coluna} {tipo}")
                    except sqlite3.OperationalError:
                        pass
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS validacoes_sol (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    total_trades INTEGER NOT NULL,
                    profit_factor REAL NOT NULL,
                    win_rate REAL NOT NULL,
                    drawdown_max REAL NOT NULL,
                    resultado TEXT NOT NULL,
                    comparacao_walkforward TEXT NOT NULL
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_tipo_simbolo_status ON trades(tipo, simbolo, status)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_trades_tipo_simbolo_status_fechado_em ON trades(tipo, simbolo, status, fechado_em)"
            )
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_idempotency_key ON trades(idempotency_key) WHERE idempotency_key IS NOT NULL"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_trades_session_id_tipo_status ON trades(session_id, tipo, status)"
            )
            conn.commit()
        return True
    except Exception as exc:
        logging.warning(f"Falha ao inicializar banco: {exc}")
        return False


def log_decisao(**kwargs):
    """
    Registra um evento de decisão sem interromper o bot se a escrita falhar.
    """
    try:
        criar_tabelas()
        payload = {
            "timestamp": kwargs.get("timestamp") or _agora_iso(),
            "symbol": _normalizar(kwargs.get("symbol")),
            "modo": _normalizar(kwargs.get("modo")),
            "decisao": _normalizar(kwargs.get("decisao")),
            "direcao": _normalizar(kwargs.get("direcao")),
            "preco": kwargs.get("preco"),
            "regime": _normalizar(kwargs.get("regime")),
            "adx": kwargs.get("adx"),
            "volume_status": _normalizar(kwargs.get("volume_status")),
            "motivo": _normalizar(kwargs.get("motivo")),
            "bloqueado_por": _normalizar(kwargs.get("bloqueado_por")),
            "fonte_dados": _normalizar(kwargs.get("fonte_dados")),
            "erro": _normalizar(kwargs.get("erro")),
            "strategy_version": _normalizar(
                kwargs.get("strategy_version"), STRATEGY_VERSION_DEFAULT
            ),
        }

        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO decision_logs (
                    timestamp, symbol, modo, decisao, direcao, preco, regime, adx,
                    volume_status, motivo, bloqueado_por, fonte_dados, erro, strategy_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["timestamp"],
                    payload["symbol"],
                    payload["modo"],
                    payload["decisao"],
                    payload["direcao"],
                    payload["preco"],
                    payload["regime"],
                    payload["adx"],
                    payload["volume_status"],
                    payload["motivo"],
                    payload["bloqueado_por"],
                    payload["fonte_dados"],
                    payload["erro"],
                    payload["strategy_version"],
                ),
            )
            conn.commit()
        return True
    except Exception as exc:
        logging.warning(f"Falha ao registrar decision_log: {exc}")
        return False


def buscar_ultimos_decision_logs(limite=10, modos=None):
    try:
        criar_tabelas()
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            query = (
                "SELECT id, timestamp, symbol, modo, decisao, direcao, preco, regime, adx, "
                "volume_status, motivo, bloqueado_por, fonte_dados, erro, strategy_version "
                "FROM decision_logs"
            )
            parametros = []
            if modos:
                modos = list(modos)
                placeholders = ",".join("?" for _ in modos)
                query += f" WHERE modo IN ({placeholders})"
                parametros.extend(modos)
            query += " ORDER BY timestamp DESC LIMIT ?"
            parametros.append(limite)
            rows = cursor.execute(query, parametros).fetchall()
        return [
            {
                "id": row[0],
                "timestamp": row[1],
                "symbol": row[2],
                "modo": row[3],
                "decisao": row[4],
                "direcao": row[5],
                "preco": row[6],
                "regime": row[7],
                "adx": row[8],
                "volume_status": row[9],
                "motivo": row[10],
                "bloqueado_por": row[11],
                "fonte_dados": row[12],
                "erro": row[13],
                "strategy_version": row[14],
            }
            for row in rows
        ]
    except Exception as exc:
        logging.warning(f"Falha ao buscar decision_logs: {exc}")
        return []


def buscar_ultimo_decision_log(modos=None):
    logs = buscar_ultimos_decision_logs(limite=1, modos=modos)
    return logs[0] if logs else None


def contar_trades_abertos_paper(symbol="SOLUSDT"):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            return cursor.execute(
                "SELECT COUNT(*) FROM trades WHERE tipo = 'paper' AND simbolo = ? AND status = 'open'",
                (symbol,),
            ).fetchone()[0]
    except Exception as exc:
        logging.warning(f"Falha ao contar trades paper abertos: {exc}")
        return 0


def contar_trades_fechados_hoje(symbol="SOLUSDT"):
    try:
        hoje = datetime.now(timezone.utc).date().isoformat()
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            return cursor.execute(
                """
                SELECT COUNT(*) FROM trades
                WHERE tipo = 'paper' AND simbolo = ? AND status = 'closed'
                AND date(fechado_em) = ?
                """,
                (symbol, hoje),
            ).fetchone()[0]
    except Exception as exc:
        logging.warning(f"Falha ao contar trades paper fechados hoje: {exc}")
        return 0


def buscar_trades_paper(limite=10, symbol="SOLUSDT"):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                """
                SELECT id, timestamp, simbolo, direcao, entrada, saida, lucro_percent, status, tipo, aberto_em, fechado_em
                FROM trades
                WHERE tipo = 'paper' AND simbolo = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (symbol, limite),
            ).fetchall()
        return [
            {
                "id": row[0],
                "timestamp": row[1],
                "symbol": row[2],
                "direcao": row[3],
                "entrada": row[4],
                "saida": row[5],
                "lucro_percent": row[6],
                "status": row[7],
                "tipo": row[8],
                "aberto_em": row[9],
                "fechado_em": row[10],
            }
            for row in rows
        ]
    except Exception as exc:
        logging.warning(f"Falha ao buscar trades paper: {exc}")
        return []


def obter_trades_paper_abertos(symbol="SOLUSDT", session_id=None):
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            query = """
                SELECT id, timestamp, simbolo, session_id, direcao, entrada, stop_loss, take_profit, quantidade, valor_arriscado, aberto_em
                FROM trades
                WHERE tipo = 'paper' AND simbolo = ? AND status = 'open'
            """
            parametros = [symbol]
            if session_id is not None:
                query += " AND session_id = ?"
                parametros.append(session_id)
            query += " ORDER BY timestamp ASC"
            rows = cursor.execute(query, parametros).fetchall()
        trades = []
        for linha in rows:
            trades.append(
                {
                    "id": linha[0],
                    "timestamp": linha[1],
                    "symbol": linha[2],
                    "session_id": linha[3],
                    "direcao": linha[4],
                    "entrada": float(linha[5]) if linha[5] is not None else None,
                    "stop_loss": float(linha[6]) if linha[6] is not None else None,
                    "take_profit": float(linha[7]) if linha[7] is not None else None,
                    "quantidade": float(linha[8] or 0.0),
                    "valor_arriscado": float(linha[9] or 0.0),
                    "aberto_em": linha[10],
                }
            )
        return trades
    except Exception as exc:
        logging.warning(f"Falha ao buscar trades paper abertos: {exc}")
        return []


def registrar_trade_paper(
    symbol,
    direcao,
    entrada,
    stop_loss,
    take_profit,
    quantidade,
    valor_arriscado,
    rr_planejado,
    filtros_aplicados=True,
    session_id=None,
    idempotency_key=None,
    db_name=None,
):
    try:
        if db_name is None:
            db_name = DB_NAME
        inicializar_banco(db_name)
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            timestamp = datetime.now(timezone.utc).isoformat()
            request_hash = None
            if idempotency_key is not None:
                request_hash = f"{symbol}|{direcao}|{entrada}|{stop_loss}|{take_profit}|{quantidade}|{valor_arriscado}|{rr_planejado}|{1 if filtros_aplicados else 0}|{session_id}"
                row = cursor.execute(
                    "SELECT id, idempotency_hash FROM trades WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if row is not None:
                    if row[1] != request_hash:
                        raise ValueError("idempotency key reuse with different payload")
                    return row[0]
            cursor.execute(
                """
                INSERT INTO trades (
                    timestamp, tipo, simbolo, session_id, status, direcao, resultado, score,
                    lucro_percent, rr_planejado, entrada, stop_loss, take_profit,
                    quantidade, valor_arriscado, aberto_em, filtros_aplicados, idempotency_key, idempotency_hash
                )
                VALUES (:timestamp, 'paper', :symbol, :session_id, 'open', :direcao, 'PENDENTE', 0, 0.0,
                        :rr_planejado, :entrada, :stop_loss, :take_profit, :quantidade, :valor_arriscado,
                        :aberto_em, :filtros_aplicados, :idempotency_key, :idempotency_hash)
                """,
                {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "session_id": session_id,
                    "direcao": direcao,
                    "rr_planejado": rr_planejado,
                    "entrada": entrada,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "quantidade": quantidade,
                    "valor_arriscado": valor_arriscado,
                    "aberto_em": timestamp,
                    "filtros_aplicados": 1 if filtros_aplicados else 0,
                    "idempotency_key": idempotency_key,
                    "idempotency_hash": request_hash,
                },
            )
            conn.commit()
            return cursor.lastrowid
    except Exception as exc:
        logging.warning(f"Falha ao registrar trade paper: {exc}")
        return None


def finalizar_trade_paper(trade_id, saida, lucro_percent, lucro_reais, resultado, motivo_saida, idempotency_key=None, db_name=None):
    try:
        if db_name is None:
            db_name = DB_NAME
        inicializar_banco(db_name)
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            timestamp = datetime.now(timezone.utc).isoformat()
            if idempotency_key is not None:
                row = cursor.execute(
                    "SELECT saida, lucro_percent, lucro_reais, resultado, motivo_saida FROM trades WHERE id = ?",
                    (trade_id,),
                ).fetchone()
                if row is not None:
                    return True
            cursor.execute(
                """
                UPDATE trades
                SET status = 'closed',
                    resultado = ?,
                    lucro_percent = ?,
                    lucro_reais = ?,
                    saida = ?,
                    fechado_em = ?,
                    motivo_saida = ?
                WHERE id = ?
                """,
                (resultado, lucro_percent, lucro_reais, saida, timestamp, motivo_saida, trade_id),
            )
            conn.commit()
            return True
    except Exception as exc:
        logging.warning(f"Falha ao finalizar trade paper: {exc}")
        return False


def obter_paper_stats(symbol="SOLUSDT"):
    def _consultar_metricas(cursor, where_sql, parametros):
        total_local = cursor.execute(
            f"SELECT COUNT(*) FROM trades WHERE {where_sql}",
            parametros,
        ).fetchone()[0]
        if total_local == 0:
            return None

        vitorias_local = cursor.execute(
            f"SELECT COUNT(*) FROM trades WHERE {where_sql} AND resultado = 'GANHO'",
            parametros,
        ).fetchone()[0]
        win_rate_local = (vitorias_local / total_local) * 100 if total_local > 0 else 0.0
        lucro_total_percent_local = cursor.execute(
            f"SELECT SUM(lucro_percent) FROM trades WHERE {where_sql}",
            parametros,
        ).fetchone()[0] or 0.0
        lucro_total_reais_local = cursor.execute(
            f"SELECT SUM(lucro_reais) FROM trades WHERE {where_sql}",
            parametros,
        ).fetchone()[0] or 0.0
        lucro_bruto_local = cursor.execute(
            f"SELECT SUM(lucro_reais) FROM trades WHERE {where_sql} AND lucro_reais > 0",
            parametros,
        ).fetchone()[0] or 0.0
        perda_bruta_local = abs(
            cursor.execute(
                f"SELECT SUM(lucro_reais) FROM trades WHERE {where_sql} AND lucro_reais < 0",
                parametros,
            ).fetchone()[0]
            or 0.0
        )
        profit_factor_local = (
            lucro_bruto_local / perda_bruta_local
            if perda_bruta_local > 0
            else (float("inf") if lucro_bruto_local > 0 else 0.0)
        )
        rr_medio_local = cursor.execute(
            f"SELECT AVG(rr_planejado) FROM trades WHERE {where_sql}",
            parametros,
        ).fetchone()[0] or 0.0
        return {
            "total": total_local,
            "vitorias": vitorias_local,
            "win_rate": win_rate_local,
            "lucro_total_percent": lucro_total_percent_local,
            "lucro_total_reais": lucro_total_reais_local,
            "profit_factor": profit_factor_local,
            "rr_medio": rr_medio_local,
        }

    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            metricas_todas = _consultar_metricas(
                cursor,
                "tipo = 'paper' AND simbolo = ? AND status = 'closed'",
                (symbol,),
            )
            metricas_filtradas = _consultar_metricas(
                cursor,
                "tipo = 'paper' AND simbolo = ? AND status = 'closed' AND filtros_aplicados = 1",
                (symbol,),
            )
        if metricas_todas is None:
            return None
        return {
            "symbol": symbol,
            "todas": metricas_todas,
            "filtradas": metricas_filtradas,
        }
    except Exception as exc:
        logging.warning(f"Falha ao obter paper stats: {exc}")
        return None


def salvar_trade(direcao, resultado, score, lucro_percent, rr_planejado, db_name=DB_NAME):
    try:
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            timestamp = datetime.now().isoformat()
            cursor.execute(
                """
                INSERT INTO trades (timestamp, direcao, resultado, score, lucro_percent, rr_planejado)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (timestamp, direcao, resultado, score, lucro_percent, rr_planejado),
            )
            conn.commit()
        return True
    except Exception as exc:
        logging.warning(f"Falha ao salvar trade: {exc}")
        return False


def obter_estatisticas(db_name=DB_NAME):
    try:
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            total = cursor.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
            if total == 0:
                return None
            vitorias = cursor.execute("SELECT COUNT(*) FROM trades WHERE resultado = 'GANHO'").fetchone()[0]
            derrotas = total - vitorias
            win_rate = (vitorias / total) * 100
            lucro_total = cursor.execute("SELECT SUM(lucro_percent) FROM trades").fetchone()[0] or 0.0
            score_vencedores = cursor.execute("SELECT AVG(score) FROM trades WHERE resultado = 'GANHO'").fetchone()[0]
            score_perdedores = cursor.execute("SELECT AVG(score) FROM trades WHERE resultado = 'PERDA'").fetchone()[0]
            trades_score_alto = cursor.execute("SELECT COUNT(*) FROM trades WHERE score > 8").fetchone()[0]
            vitorias_score_alto = cursor.execute(
                "SELECT COUNT(*) FROM trades WHERE score > 8 AND resultado = 'GANHO'"
            ).fetchone()[0]
            chance_alto = (vitorias_score_alto / trades_score_alto * 100) if trades_score_alto > 0 else 0.0
            return {
                "total": total,
                "vitorias": vitorias,
                "derrotas": derrotas,
                "win_rate": win_rate,
                "lucro_total": lucro_total,
                "score_vencedores": score_vencedores,
                "score_perdedores": score_perdedores,
                "chance_alto": chance_alto,
            }
    except Exception as exc:
        logging.warning(f"Falha ao obter estatísticas: {exc}")
        return None


def reset_db(db_name=DB_NAME):
    try:
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM trades")
            conn.commit()
        return True
    except Exception as exc:
        logging.warning(f"Falha ao resetar banco: {exc}")
        return False


def obter_ultimos_trades_paper(symbol="SOLUSDT", limite=30, db_name=DB_NAME, session_id=None):
    try:
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            query = """
                SELECT timestamp, resultado, lucro_percent, lucro_reais, filtros_aplicados
                FROM trades
                WHERE tipo = 'paper' AND simbolo = ? AND status = 'closed'
            """
            parametros = [symbol]
            if session_id is not None:
                query += " AND session_id = ?"
                parametros.append(session_id)
            query += " ORDER BY timestamp DESC LIMIT ?"
            parametros.append(limite)
            rows = cursor.execute(
                query,
                parametros,
            ).fetchall()
        trades = []
        for linha in rows:
            trades.append(
                {
                    "timestamp": linha[0],
                    "resultado": linha[1],
                    "lucro_percent": float(linha[2] or 0.0),
                    "lucro_reais": float(linha[3] or 0.0),
                    "filtros_aplicados": bool(linha[4]),
                }
            )
        return list(reversed(trades))
    except Exception as exc:
        logging.warning(f"Falha ao buscar ultimos trades paper: {exc}")
        return []


def calcular_metricas_trade_history(trades):
    if not trades:
        return None

    trades_ordenados = sorted(trades, key=lambda item: item["timestamp"])
    ganhos = [t for t in trades_ordenados if (t.get("lucro_reais") or 0.0) > 0]
    perdas = [t for t in trades_ordenados if (t.get("lucro_reais") or 0.0) < 0]
    lucro_bruto = sum(float(t.get("lucro_reais") or 0.0) for t in ganhos)
    perda_bruta = abs(sum(float(t.get("lucro_reais") or 0.0) for t in perdas))
    profit_factor = (lucro_bruto / perda_bruta) if perda_bruta > 0 else (float("inf") if lucro_bruto > 0 else 0.0)
    win_rate = (len(ganhos) / len(trades_ordenados)) * 100 if trades_ordenados else 0.0

    saldo = 100.0
    pico = 100.0
    drawdown_max = 0.0
    for trade in trades_ordenados:
        saldo += float(trade.get("lucro_percent") or 0.0)
        if saldo > pico:
            pico = saldo
        if pico > 0:
            drawdown_atual = ((pico - saldo) / pico) * 100
            if drawdown_atual > drawdown_max:
                drawdown_max = drawdown_atual

    return {
        "total": len(trades_ordenados),
        "profit_factor": profit_factor,
        "win_rate": win_rate,
        "drawdown_max": drawdown_max,
    }


def registrar_validacao_sol(total_trades, profit_factor, win_rate, drawdown_max, resultado, comparacao_walkforward, db_name=DB_NAME):
    try:
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            timestamp = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT INTO validacoes_sol (
                    timestamp, total_trades, profit_factor, win_rate, drawdown_max, resultado, comparacao_walkforward
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    total_trades,
                    profit_factor,
                    win_rate,
                    drawdown_max,
                    resultado,
                    comparacao_walkforward,
                ),
            )
            conn.commit()
        return True
    except Exception as exc:
        logging.warning(f"Falha ao registrar validacao SOL: {exc}")
        return False
