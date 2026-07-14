import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any


DB_NAME = "trades.db"
STRATEGY_VERSION_DEFAULT = "v2_risk_safe"


class PaperTradeOutboxError(Exception):
    pass


class PaperTradeFinalizationError(Exception):
    pass


class PaperTradeStorageReadError(Exception):
    pass


def _agora_iso():
    return datetime.now(timezone.utc).isoformat()


def _canonizar_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonizar_payload(payload).encode("utf-8")).hexdigest()


def _iso_utc_hash(value):
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return value


def _normalizar(valor, padrao="N/A"):
    if valor is None:
        return padrao
    if isinstance(valor, str) and not valor.strip():
        return padrao
    return valor


def _tratar_falha_leitura_storage(contexto: str, exc: Exception, *, strict: bool):
    logging.warning(f"{contexto} indisponivel: {exc.__class__.__name__}")
    if strict:
        raise PaperTradeStorageReadError(contexto) from exc
    return []


def _trade_cost_helpers(direcao, entrada, quantidade, trade_costs):
    entrada_val = float(entrada)
    quantidade_val = float(quantidade)
    spread_rate = float(trade_costs["spread_bps"]) / 10000.0
    slippage_rate = float(trade_costs["slippage_bps"]) / 10000.0
    entry_spread = entrada_val * spread_rate
    entry_slippage = entrada_val * slippage_rate
    if direcao == "COMPRA":
        fill_price = entrada_val + entry_spread + entry_slippage
    else:
        fill_price = entrada_val - entry_spread - entry_slippage
    entry_fee = abs(quantidade_val * fill_price * float(trade_costs["entry_fee_rate"]))
    entry_spread_cost = abs(quantidade_val * entry_spread)
    entry_slippage_cost = abs(quantidade_val * entry_slippage)
    return fill_price, entry_fee, entry_spread_cost, entry_slippage_cost


def _calcular_fill_price_paper(direcao, entrada, quantidade, trade_costs):
    return _trade_cost_helpers(direcao, entrada, quantidade, trade_costs)[0]


def _calcular_entry_fee_paper(direcao, entrada, quantidade, trade_costs):
    return _trade_cost_helpers(direcao, entrada, quantidade, trade_costs)[1]


def _calcular_spread_cost_paper(direcao, entrada, quantidade, trade_costs):
    return _trade_cost_helpers(direcao, entrada, quantidade, trade_costs)[2]


def _calcular_slippage_cost_paper(direcao, entrada, quantidade, trade_costs):
    return _trade_cost_helpers(direcao, entrada, quantidade, trade_costs)[3]


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
                "preco_base": "REAL",
                "fill_price": "REAL",
                "entry_fee": "REAL",
                "exit_fee": "REAL",
                "entry_spread_cost": "REAL",
                "exit_spread_cost": "REAL",
                "entry_slippage_cost": "REAL",
                "exit_slippage_cost": "REAL",
                "spread_cost": "REAL",
                "slippage_cost": "REAL",
                "pnl_bruto": "REAL",
                "custos_totais": "REAL",
                "pnl_liquido": "REAL",
                "aberto_em": "TEXT",
                "fechado_em": "TEXT",
                "saida": "REAL",
                "lucro_reais": "REAL",
                "motivo_saida": "TEXT",
                "filtros_aplicados": "INTEGER DEFAULT 1",
                "session_id": "TEXT",
                "idempotency_key": "TEXT",
                "idempotency_hash": "TEXT",
                "close_idempotency_key": "TEXT",
                "close_idempotency_hash": "TEXT",
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
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trade_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    trade_id INTEGER NOT NULL,
                    operation_type TEXT NOT NULL,
                    candle_close_time TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    runtime_delivered_at_utc TEXT,
                    snapshot_applied_at_utc TEXT,
                    telegram_sent_at_utc TEXT,
                    last_error_class TEXT,
                    last_error_code TEXT
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
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_paper_trade_outbox_session_status_created ON paper_trade_outbox(session_id, status, created_at_utc)"
            )
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_trade_outbox_idempotency_key ON paper_trade_outbox(idempotency_key)"
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


def _normalizar_outbox_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(_canonizar_payload(payload))


def _inserir_paper_trade_outbox(
    cursor,
    *,
    event_id,
    session_id,
    trade_id,
    operation_type,
    candle_close_time,
    idempotency_key,
    request_hash,
    payload_json,
    status="PENDING",
    attempts=0,
    runtime_delivered_at_utc=None,
    snapshot_applied_at_utc=None,
    telegram_sent_at_utc=None,
    last_error_class=None,
    last_error_code=None,
):
    cursor.execute(
        """
        INSERT INTO paper_trade_outbox (
            event_id, session_id, trade_id, operation_type, candle_close_time, idempotency_key,
            request_hash, payload_json, status, attempts, created_at_utc, updated_at_utc,
            runtime_delivered_at_utc, snapshot_applied_at_utc, telegram_sent_at_utc,
            last_error_class, last_error_code
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            session_id,
            trade_id,
            operation_type,
            candle_close_time,
            idempotency_key,
            request_hash,
            payload_json,
            status,
            attempts,
            _agora_iso(),
            _agora_iso(),
            runtime_delivered_at_utc,
            snapshot_applied_at_utc,
            telegram_sent_at_utc,
            last_error_class,
            last_error_code,
        ),
    )


def _atualizar_paper_trade_outbox(cursor, event_id, **updates):
    if not updates:
        return 0
    campos = ", ".join(f"{campo} = ?" for campo in updates)
    valores = list(updates.values())
    valores.extend([_agora_iso(), event_id])
    cursor.execute(
        f"UPDATE paper_trade_outbox SET {campos}, updated_at_utc = ? WHERE event_id = ?",
        valores,
    )
    return cursor.rowcount


def _paper_outbox_transition_is_valid(current_status, updates) -> bool:
    status = str(current_status or "").strip().upper()
    if status not in {"PENDING", "DELIVERED", "NOTIFIED"}:
        return False
    desired = updates.get("status")
    if desired is None:
        return True
    desired = str(desired).strip().upper()
    if desired not in {"PENDING", "DELIVERED", "NOTIFIED"}:
        return False
    allowed = {
        "PENDING": {"PENDING", "DELIVERED", "NOTIFIED"},
        "DELIVERED": {"DELIVERED", "NOTIFIED"},
        "NOTIFIED": {"NOTIFIED"},
    }
    return desired in allowed[status]


def registrar_paper_trade_outbox(
    *,
    event_id,
    session_id,
    trade_id,
    operation_type,
    candle_close_time,
    idempotency_key,
    payload,
    status="PENDING",
    attempts=0,
    runtime_delivered_at_utc=None,
    snapshot_applied_at_utc=None,
    telegram_sent_at_utc=None,
    last_error_class=None,
    last_error_code=None,
    db_name=DB_NAME,
):
    try:
        inicializar_banco(db_name)
        payload_json = _canonizar_payload(_normalizar_outbox_payload(payload))
        request_hash = _sha256_payload(
            {
                "event_id": event_id,
                "session_id": session_id,
                "trade_id": trade_id,
                "operation_type": operation_type,
                "candle_close_time": candle_close_time,
                "idempotency_key": idempotency_key,
                "payload": json.loads(payload_json),
            }
        )
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT event_id, request_hash FROM paper_trade_outbox WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is not None:
                if row[1] != request_hash:
                    raise PaperTradeOutboxError("idempotency key reuse with different payload")
                return row[0]
            _inserir_paper_trade_outbox(
                cursor,
                event_id=event_id,
                session_id=session_id,
                trade_id=trade_id,
                operation_type=operation_type,
                candle_close_time=candle_close_time,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                payload_json=payload_json,
                status=status,
                attempts=attempts,
                runtime_delivered_at_utc=runtime_delivered_at_utc,
                snapshot_applied_at_utc=snapshot_applied_at_utc,
                telegram_sent_at_utc=telegram_sent_at_utc,
                last_error_class=last_error_class,
                last_error_code=last_error_code,
            )
            conn.commit()
            return event_id
    except PaperTradeOutboxError:
        raise
    except Exception as exc:
        logging.warning(f"Falha ao registrar outbox paper trade: {exc}")
        return None


def obter_outbox_paper_pendentes(session_id=None, db_name=DB_NAME, strict=False):
    try:
        inicializar_banco(db_name)
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            query = """
                SELECT id, event_id, session_id, trade_id, operation_type, candle_close_time, idempotency_key,
                       request_hash, payload_json, status, attempts, runtime_delivered_at_utc,
                       snapshot_applied_at_utc, telegram_sent_at_utc, last_error_class, last_error_code,
                       created_at_utc, updated_at_utc
                FROM paper_trade_outbox
                WHERE telegram_sent_at_utc IS NULL
            """
            parametros = []
            if session_id is not None:
                query += " AND session_id = ?"
                parametros.append(session_id)
            query += " ORDER BY created_at_utc ASC, id ASC"
            rows = cursor.execute(query, parametros).fetchall()
        return [
            {
                "id": row[0],
                "event_id": row[1],
                "session_id": row[2],
                "trade_id": row[3],
                "operation_type": row[4],
                "candle_close_time": row[5],
                "idempotency_key": row[6],
                "request_hash": row[7],
                "payload_json": row[8],
                "status": row[9],
                "attempts": row[10],
                "runtime_delivered_at_utc": row[11],
                "snapshot_applied_at_utc": row[12],
                "telegram_sent_at_utc": row[13],
                "last_error_class": row[14],
                "last_error_code": row[15],
                "created_at_utc": row[16],
                "updated_at_utc": row[17],
            }
            for row in rows
        ]
    except Exception as exc:
        return _tratar_falha_leitura_storage("Falha ao buscar outbox paper trade", exc, strict=strict)


def atualizar_outbox_paper_trade(
    event_id,
    *,
    status=None,
    runtime_delivered_at_utc=None,
    snapshot_applied_at_utc=None,
    telegram_sent_at_utc=None,
    attempts_increment=0,
    last_error_class=None,
    last_error_code=None,
    db_name=DB_NAME,
):
    try:
        inicializar_banco(db_name)
        updates = {}
        if status is not None:
            updates["status"] = status
        if runtime_delivered_at_utc is not None:
            updates["runtime_delivered_at_utc"] = runtime_delivered_at_utc
        if snapshot_applied_at_utc is not None:
            updates["snapshot_applied_at_utc"] = snapshot_applied_at_utc
        if telegram_sent_at_utc is not None:
            updates["telegram_sent_at_utc"] = telegram_sent_at_utc
        if last_error_class is not None:
            updates["last_error_class"] = last_error_class
        if last_error_code is not None:
            updates["last_error_code"] = last_error_code
        if not updates:
            return False
        if attempts_increment:
            with sqlite3.connect(db_name) as conn:
                cursor = conn.cursor()
                row = cursor.execute(
                    "SELECT attempts FROM paper_trade_outbox WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if row is None:
                    return False
                current_status = cursor.execute(
                    "SELECT status FROM paper_trade_outbox WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if current_status is None:
                    return False
                if not _paper_outbox_transition_is_valid(current_status[0], updates):
                    return False
                updates["attempts"] = int(row[0] or 0) + int(attempts_increment)
                if _atualizar_paper_trade_outbox(cursor, event_id, **updates) != 1:
                    return False
                conn.commit()
                return True
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            current_status = cursor.execute(
                "SELECT status FROM paper_trade_outbox WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if current_status is None:
                return False
            if not _paper_outbox_transition_is_valid(current_status[0], updates):
                return False
            if _atualizar_paper_trade_outbox(cursor, event_id, **updates) != 1:
                return False
            conn.commit()
        return True
    except Exception as exc:
        logging.warning(f"Falha ao atualizar outbox paper trade: {exc}")
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


def obter_trades_paper_abertos(symbol="SOLUSDT", session_id=None, db_name=DB_NAME, strict=False):
    try:
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            query = """
                SELECT id, timestamp, simbolo, session_id, direcao, entrada, stop_loss, take_profit, quantidade, valor_arriscado,
                       preco_base, fill_price, entry_fee, exit_fee, entry_spread_cost, entry_slippage_cost, exit_spread_cost, exit_slippage_cost,
                       spread_cost, slippage_cost, pnl_bruto, custos_totais, pnl_liquido,
                       aberto_em
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
                "tipo": "paper",
                "status": "open",
                "direcao": linha[4],
                "entrada": float(linha[5]) if linha[5] is not None else None,
                "stop_loss": float(linha[6]) if linha[6] is not None else None,
                "take_profit": float(linha[7]) if linha[7] is not None else None,
                    "quantidade": float(linha[8] or 0.0),
                    "valor_arriscado": float(linha[9] or 0.0),
                    "preco_base": float(linha[10]) if linha[10] is not None else None,
                    "fill_price": float(linha[11]) if linha[11] is not None else None,
                    "entry_fee": float(linha[12]) if linha[12] is not None else None,
                    "exit_fee": float(linha[13]) if linha[13] is not None else None,
                    "entry_spread_cost": float(linha[14]) if linha[14] is not None else None,
                    "entry_slippage_cost": float(linha[15]) if linha[15] is not None else None,
                    "exit_spread_cost": float(linha[16]) if linha[16] is not None else None,
                    "exit_slippage_cost": float(linha[17]) if linha[17] is not None else None,
                    "spread_cost": float(linha[18]) if linha[18] is not None else None,
                    "slippage_cost": float(linha[19]) if linha[19] is not None else None,
                    "pnl_bruto": float(linha[20]) if linha[20] is not None else None,
                    "custos_totais": float(linha[21]) if linha[21] is not None else None,
                    "pnl_liquido": float(linha[22]) if linha[22] is not None else None,
                    "aberto_em": linha[23],
                }
            )
        return trades
    except Exception as exc:
        return _tratar_falha_leitura_storage("Falha ao buscar trades paper abertos", exc, strict=strict)


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
    candle_close_time=None,
    signal_identity=None,
    preco_base=None,
    fill_price=None,
    entry_fee=None,
    entry_spread_cost=None,
    entry_slippage_cost=None,
    spread_cost=None,
    slippage_cost=None,
    outbox_event_factory=None,
    db_name=None,
):
    try:
        if db_name is None:
            db_name = DB_NAME
        inicializar_banco(db_name)
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            timestamp = datetime.now(timezone.utc).isoformat()
            costs = {
                "entry_fee_rate": 0.0004,
                "exit_fee_rate": 0.0004,
                "spread_bps": 5.0,
                "slippage_bps": 5.0,
            }
            if (
                fill_price is None
                or entry_fee is None
                or entry_spread_cost is None
                or entry_slippage_cost is None
                or spread_cost is None
                or slippage_cost is None
            ):
                try:
                    from decimal import Decimal

                    trade_costs = {
                        "entry_fee_rate": Decimal(str(costs["entry_fee_rate"])),
                        "exit_fee_rate": Decimal(str(costs["exit_fee_rate"])),
                        "spread_bps": Decimal(str(costs["spread_bps"])),
                        "slippage_bps": Decimal(str(costs["slippage_bps"])),
                    }
                    calculado = {
                        "fill_price": float(_calcular_fill_price_paper(direcao, entrada, quantidade, trade_costs)),
                        "entry_fee": float(_calcular_entry_fee_paper(direcao, entrada, quantidade, trade_costs)),
                        "entry_spread_cost": float(_calcular_spread_cost_paper(direcao, entrada, quantidade, trade_costs)),
                        "entry_slippage_cost": float(_calcular_slippage_cost_paper(direcao, entrada, quantidade, trade_costs)),
                    }
                    fill_price = calculado["fill_price"] if fill_price is None else fill_price
                    entry_fee = calculado["entry_fee"] if entry_fee is None else entry_fee
                    entry_spread_cost = calculado["entry_spread_cost"] if entry_spread_cost is None else entry_spread_cost
                    entry_slippage_cost = calculado["entry_slippage_cost"] if entry_slippage_cost is None else entry_slippage_cost
                    spread_cost = entry_spread_cost if spread_cost is None else spread_cost
                    slippage_cost = entry_slippage_cost if slippage_cost is None else slippage_cost
                except Exception:
                    fill_price = fill_price if fill_price is not None else entrada
                    entry_fee = entry_fee if entry_fee is not None else 0.0
                    entry_spread_cost = entry_spread_cost if entry_spread_cost is not None else 0.0
                    entry_slippage_cost = entry_slippage_cost if entry_slippage_cost is not None else 0.0
                    spread_cost = spread_cost if spread_cost is not None else 0.0
                    slippage_cost = slippage_cost if slippage_cost is not None else 0.0
            request_hash = None
            if idempotency_key is not None:
                request_hash = _sha256_payload(
                    {
                        "kind": "paper_trade_open",
                        "symbol": symbol,
                        "direcao": direcao,
                        "entrada": entrada,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "quantidade": quantidade,
                        "valor_arriscado": valor_arriscado,
                        "rr_planejado": rr_planejado,
                        "filtros_aplicados": bool(filtros_aplicados),
                        "session_id": session_id,
                        "candle_close_time": _iso_utc_hash(candle_close_time),
                        "signal_identity": signal_identity,
                        "preco_base": preco_base if preco_base is not None else entrada,
                        "fill_price": fill_price if fill_price is not None else entrada,
                        "entry_fee": entry_fee,
                        "entry_spread_cost": entry_spread_cost,
                        "entry_slippage_cost": entry_slippage_cost,
                        "spread_cost": spread_cost,
                        "slippage_cost": slippage_cost,
                    }
                )
                row = cursor.execute(
                    "SELECT id, idempotency_hash FROM trades WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if row is not None:
                    if row[1] != request_hash:
                        raise PaperTradeOutboxError("idempotency key reuse with different payload")
                    return row[0]
            cursor.execute(
                """
                INSERT INTO trades (
                    timestamp, tipo, simbolo, session_id, status, direcao, resultado, score,
                    lucro_percent, rr_planejado, entrada, stop_loss, take_profit,
                    quantidade, valor_arriscado, preco_base, fill_price, entry_fee, entry_spread_cost, entry_slippage_cost, spread_cost, slippage_cost,
                    aberto_em, filtros_aplicados, idempotency_key, idempotency_hash
                )
                VALUES (:timestamp, 'paper', :symbol, :session_id, 'open', :direcao, 'PENDENTE', 0, 0.0,
                        :rr_planejado, :entrada, :stop_loss, :take_profit, :quantidade, :valor_arriscado,
                        :preco_base, :fill_price, :entry_fee, :entry_spread_cost, :entry_slippage_cost, :spread_cost, :slippage_cost,
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
                    "preco_base": preco_base if preco_base is not None else entrada,
                    "fill_price": fill_price if fill_price is not None else entrada,
                    "entry_fee": entry_fee,
                    "entry_spread_cost": entry_spread_cost,
                    "entry_slippage_cost": entry_slippage_cost,
                    "spread_cost": spread_cost,
                    "slippage_cost": slippage_cost,
                    "aberto_em": timestamp,
                    "filtros_aplicados": 1 if filtros_aplicados else 0,
                    "idempotency_key": idempotency_key,
                    "idempotency_hash": request_hash,
                },
            )
            trade_id = cursor.lastrowid
            if outbox_event_factory is not None:
                outbox_event = outbox_event_factory(trade_id, timestamp)
                if outbox_event is None:
                    raise PaperTradeOutboxError("outbox event factory returned no payload")
                _inserir_paper_trade_outbox(
                    cursor,
                    event_id=outbox_event["event_id"],
                    session_id=outbox_event["session_id"],
                    trade_id=outbox_event["trade_id"],
                    operation_type=outbox_event["operation_type"],
                    candle_close_time=outbox_event["candle_close_time"],
                    idempotency_key=outbox_event["idempotency_key"],
                    request_hash=outbox_event["request_hash"],
                    payload_json=outbox_event["payload_json"],
                    status=outbox_event.get("status", "PENDING"),
                    attempts=outbox_event.get("attempts", 0),
                    runtime_delivered_at_utc=outbox_event.get("runtime_delivered_at_utc"),
                    snapshot_applied_at_utc=outbox_event.get("snapshot_applied_at_utc"),
                    telegram_sent_at_utc=outbox_event.get("telegram_sent_at_utc"),
                    last_error_class=outbox_event.get("last_error_class"),
                    last_error_code=outbox_event.get("last_error_code"),
                )
            conn.commit()
            return trade_id
    except Exception as exc:
        logging.warning(f"Falha ao registrar trade paper: {exc}")
        return None


def finalizar_trade_paper(
    trade_id,
    saida,
    lucro_percent,
    lucro_reais,
    resultado,
    motivo_saida,
    idempotency_key=None,
    db_name=None,
    pnl_bruto=None,
    custos_totais=None,
    pnl_liquido=None,
    exit_fee=None,
    entry_spread_cost=None,
    entry_slippage_cost=None,
    exit_spread_cost=None,
    exit_slippage_cost=None,
    spread_cost=None,
    slippage_cost=None,
    close_idempotency_key=None,
    session_id=None,
    candle_close_time=None,
    fill_price=None,
    outbox_event_factory=None,
):
    try:
        if db_name is None:
            db_name = DB_NAME
        inicializar_banco(db_name)
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            timestamp = datetime.now(timezone.utc).isoformat()
            if pnl_bruto is None:
                pnl_bruto = lucro_reais
            if custos_totais is None:
                custos_totais = 0.0
            if pnl_liquido is None:
                pnl_liquido = lucro_reais
            if exit_fee is None:
                exit_fee = 0.0
            if entry_spread_cost is None:
                entry_spread_cost = 0.0
            if entry_slippage_cost is None:
                entry_slippage_cost = 0.0
            if exit_spread_cost is None:
                exit_spread_cost = 0.0
            if exit_slippage_cost is None:
                exit_slippage_cost = 0.0
            if spread_cost is None:
                spread_cost = 0.0
            if slippage_cost is None:
                slippage_cost = 0.0
            row = cursor.execute(
                """
                SELECT id, status, saida, lucro_percent, lucro_reais, resultado, motivo_saida,
                       close_idempotency_key, close_idempotency_hash
                FROM trades
                WHERE id = ?
                """,
                (trade_id,),
            ).fetchone()
            if row is None:
                raise PaperTradeFinalizationError("trade not found")

            request_hash = _sha256_payload(
                {
                    "kind": "paper_trade_close",
                    "trade_id": trade_id,
                    "session_id": session_id,
                    "candle_close_time": _iso_utc_hash(candle_close_time),
                    "saida": saida,
                    "fill_price": fill_price if fill_price is not None else saida,
                    "lucro_percent": lucro_percent,
                    "lucro_reais": lucro_reais,
                    "resultado": resultado,
                    "motivo_saida": motivo_saida,
                    "pnl_bruto": pnl_bruto,
                    "custos_totais": custos_totais,
                    "pnl_liquido": pnl_liquido,
                    "exit_fee": exit_fee,
                    "entry_spread_cost": entry_spread_cost,
                    "entry_slippage_cost": entry_slippage_cost,
                    "exit_spread_cost": exit_spread_cost,
                    "exit_slippage_cost": exit_slippage_cost,
                    "spread_cost": spread_cost,
                    "slippage_cost": slippage_cost,
                    "close_idempotency_key": close_idempotency_key or idempotency_key,
                }
            )
            stored_close_key = row[7]
            stored_close_hash = row[8]
            if row[1] == "closed":
                if stored_close_key == (close_idempotency_key or idempotency_key) and stored_close_hash == request_hash:
                    return True
                raise PaperTradeFinalizationError("closed trade cannot be altered")
            if idempotency_key is not None and stored_close_key is not None:
                if stored_close_key != (close_idempotency_key or idempotency_key) or stored_close_hash != request_hash:
                    raise PaperTradeFinalizationError("idempotency key reuse with different payload")

            cursor.execute(
                """
                UPDATE trades
                SET status = 'closed',
                    resultado = ?,
                    lucro_percent = ?,
                    lucro_reais = ?,
                    saida = ?,
                    fechado_em = ?,
                    motivo_saida = ?,
                    pnl_bruto = COALESCE(?, pnl_bruto),
                    custos_totais = COALESCE(?, custos_totais),
                    pnl_liquido = COALESCE(?, pnl_liquido),
                    exit_fee = COALESCE(?, exit_fee),
                    entry_spread_cost = COALESCE(?, entry_spread_cost),
                    entry_slippage_cost = COALESCE(?, entry_slippage_cost),
                    exit_spread_cost = COALESCE(?, exit_spread_cost),
                    exit_slippage_cost = COALESCE(?, exit_slippage_cost),
                    spread_cost = COALESCE(?, spread_cost),
                    slippage_cost = COALESCE(?, slippage_cost),
                    close_idempotency_key = COALESCE(?, close_idempotency_key),
                    close_idempotency_hash = COALESCE(?, close_idempotency_hash)
                WHERE id = ? AND status = 'open'
                """,
                (
                    resultado,
                    lucro_percent,
                    lucro_reais,
                    saida,
                    timestamp,
                    motivo_saida,
                    pnl_bruto,
                    custos_totais,
                    pnl_liquido,
                    exit_fee,
                    entry_spread_cost,
                    entry_slippage_cost,
                    exit_spread_cost,
                    exit_slippage_cost,
                    spread_cost,
                    slippage_cost,
                    close_idempotency_key or idempotency_key,
                    request_hash,
                    trade_id,
                ),
            )
            if cursor.rowcount != 1:
                raise PaperTradeFinalizationError("trade close update failed")
            if outbox_event_factory is not None:
                outbox_event = outbox_event_factory(trade_id, timestamp)
                if outbox_event is None:
                    raise PaperTradeOutboxError("outbox event factory returned no payload")
                _inserir_paper_trade_outbox(
                    cursor,
                    event_id=outbox_event["event_id"],
                    session_id=outbox_event["session_id"],
                    trade_id=outbox_event["trade_id"],
                    operation_type=outbox_event["operation_type"],
                    candle_close_time=outbox_event["candle_close_time"],
                    idempotency_key=outbox_event["idempotency_key"],
                    request_hash=outbox_event["request_hash"],
                    payload_json=outbox_event["payload_json"],
                    status=outbox_event.get("status", "PENDING"),
                    attempts=outbox_event.get("attempts", 0),
                    runtime_delivered_at_utc=outbox_event.get("runtime_delivered_at_utc"),
                    snapshot_applied_at_utc=outbox_event.get("snapshot_applied_at_utc"),
                    telegram_sent_at_utc=outbox_event.get("telegram_sent_at_utc"),
                    last_error_class=outbox_event.get("last_error_class"),
                    last_error_code=outbox_event.get("last_error_code"),
                )
            conn.commit()
            return True
    except PaperTradeFinalizationError:
        raise
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
            cursor.execute("DELETE FROM paper_trade_outbox")
            conn.commit()
        return True
    except Exception as exc:
        logging.warning(f"Falha ao resetar banco: {exc}")
        return False


def obter_ultimos_trades_paper(symbol="SOLUSDT", limite=30, db_name=DB_NAME, session_id=None, strict=False):
    try:
        with sqlite3.connect(db_name) as conn:
            cursor = conn.cursor()
            query = """
                SELECT timestamp, resultado, lucro_percent, lucro_reais, filtros_aplicados,
                       direcao, entrada, saida, quantidade, preco_base, fill_price, entry_fee,
                       exit_fee, entry_spread_cost, entry_slippage_cost, exit_spread_cost, exit_slippage_cost,
                       spread_cost, slippage_cost, pnl_bruto, custos_totais, pnl_liquido, session_id, fechado_em
                FROM trades
                WHERE tipo = 'paper' AND simbolo = ? AND status = 'closed'
            """
            parametros = [symbol]
            if session_id is not None:
                query += " AND session_id = ?"
                parametros.append(session_id)
            query += " ORDER BY COALESCE(fechado_em, timestamp) DESC LIMIT ?"
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
                    "direcao": linha[5],
                    "entrada": float(linha[6]) if linha[6] is not None else None,
                    "saida": float(linha[7]) if linha[7] is not None else None,
                    "quantidade": float(linha[8]) if linha[8] is not None else None,
                    "preco_base": float(linha[9]) if linha[9] is not None else None,
                    "fill_price": float(linha[10]) if linha[10] is not None else None,
                    "entry_fee": float(linha[11]) if linha[11] is not None else None,
                    "exit_fee": float(linha[12]) if linha[12] is not None else None,
                    "entry_spread_cost": float(linha[13]) if linha[13] is not None else None,
                    "entry_slippage_cost": float(linha[14]) if linha[14] is not None else None,
                    "exit_spread_cost": float(linha[15]) if linha[15] is not None else None,
                    "exit_slippage_cost": float(linha[16]) if linha[16] is not None else None,
                    "spread_cost": float(linha[17]) if linha[17] is not None else None,
                    "slippage_cost": float(linha[18]) if linha[18] is not None else None,
                    "pnl_bruto": float(linha[19]) if linha[19] is not None else None,
                    "custos_totais": float(linha[20]) if linha[20] is not None else None,
                    "pnl_liquido": float(linha[21]) if linha[21] is not None else None,
                    "session_id": linha[22],
                    "fechado_em": linha[23] if len(linha) > 23 else None,
                }
            )
        return list(reversed(trades))
    except Exception as exc:
        return _tratar_falha_leitura_storage("Falha ao buscar ultimos trades paper", exc, strict=strict)


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
