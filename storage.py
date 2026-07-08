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
            conn.commit()
    except Exception as exc:
        logging.warning(f"Falha ao criar tabelas de observabilidade: {exc}")


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
