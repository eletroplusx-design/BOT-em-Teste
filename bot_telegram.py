import asyncio
import math
import time
import logging
import os
import sqlite3
from datetime import datetime, timezone
import httpx
import telegram.error
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    JobQueue
)
from telegram.request import HTTPXRequest
from dotenv import load_dotenv
import pandas as pd
import warnings

warnings.filterwarnings("ignore", message=".*per_message=False.*")
load_dotenv()

# --------------------- IMPORTAÇÕES DOS MÓDULOS PRÓPRIOS ---------------------
from data_fetcher import baixar_dados_btc
from analisador_fvg import identificar_fvg
from analisador_contexto import tendencia_geral, ultimos_swings
from regime_classifier import classificar_regime, contexto_tempo
from decisor import (
    tomar_decisao,
    extrair_swing_high_low,
    extrair_fvg_bearish_acima,
    extrair_fvg_bullish_abaixo,
    obter_funding_rate   # <-- NOVA IMPORTAÇÃO
)
from ai_analista import gerar_comentario_ia
from storage import (
    buscar_ultimo_decision_log,
    buscar_ultimos_decision_logs,
    buscar_trades_paper,
    contar_trades_abertos_paper,
    contar_trades_fechados_hoje,
    criar_tabelas as criar_tabelas_observabilidade,
    log_decisao,
)
try:
    from risk_manager import (
        calcular_tamanho_posicao,
        verificar_limite_diario,
        verificar_sequencia_perdas,
    )
except Exception:
    calcular_tamanho_posicao = None
    verificar_limite_diario = None
    verificar_sequencia_perdas = None

try:
    import backtester
except Exception:
    backtester = None

# ---------- CHAVE SELETORA ----------
MODO_OPERACAO = "FUTUROS"   # "FUTUROS" ou "SPOT"
PAPER_TRADING_ATIVO = True
KILLZONE_BTC = True
KILLZONE_SOL = True
PAPER_SYMBOL = "SOLUSDT"
PAPER_JOB_NAME = "paper_sol"
PAPER_CONFIG = {
    "regime_modo": "bull_bear",
    "volume_minimo_multiplicador": None,
    "exigir_fvg_nao_tocado": False,
    "lookback_fvg": None,
    "exigir_rr_minimo": False,
}

def esta_em_killzone():
    agora = datetime.now(timezone.utc)
    minutos_utc = agora.hour * 60 + agora.minute
    londres_inicio = 7 * 60
    londres_fim = 10 * 60
    ny_inicio = 13 * 60
    ny_fim = 16 * 60
    return (londres_inicio <= minutos_utc < londres_fim) or (ny_inicio <= minutos_utc < ny_fim)

# ---------- Estados do ConversationHandler ----------
DIRECAO, RESULTADO, SCORE, LUCRO, RR = range(5)

# ---------- Banco de Dados ----------
DB_NAME = "trades.db"

def garantir_schema_trades():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            direcao TEXT NOT NULL,
            resultado TEXT NOT NULL,
            score INTEGER NOT NULL,
            lucro_percent REAL NOT NULL,
            rr_planejado REAL NOT NULL
        )
    ''')
    colunas = {
        row[1] for row in c.execute("PRAGMA table_info(trades)").fetchall()
    }
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
    }
    for coluna, tipo in alteracoes.items():
        if coluna not in colunas:
            try:
                c.execute(f"ALTER TABLE trades ADD COLUMN {coluna} {tipo}")
            except sqlite3.OperationalError:
                pass
    c.execute(
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
    conn.commit()
    conn.close()

def init_db():
    criar_tabelas_observabilidade()
    garantir_schema_trades()

def salvar_trade(direcao, resultado, score, lucro_percent, rr_planejado):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    timestamp = datetime.now().isoformat()
    c.execute('''
        INSERT INTO trades (timestamp, direcao, resultado, score, lucro_percent, rr_planejado)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (timestamp, direcao, resultado, score, lucro_percent, rr_planejado))
    conn.commit()
    conn.close()

def obter_estatisticas():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    total = c.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    if total == 0:
        conn.close()
        return None

    vitorias = c.execute("SELECT COUNT(*) FROM trades WHERE resultado = 'GANHO'").fetchone()[0]
    derrotas = total - vitorias
    win_rate = (vitorias / total) * 100
    lucro_total = c.execute("SELECT SUM(lucro_percent) FROM trades").fetchone()[0] or 0.0
    score_vencedores = c.execute("SELECT AVG(score) FROM trades WHERE resultado = 'GANHO'").fetchone()[0]
    score_perdedores = c.execute("SELECT AVG(score) FROM trades WHERE resultado = 'PERDA'").fetchone()[0]
    trades_score_alto = c.execute("SELECT COUNT(*) FROM trades WHERE score > 8").fetchone()[0]
    vitorias_score_alto = c.execute("SELECT COUNT(*) FROM trades WHERE score > 8 AND resultado = 'GANHO'").fetchone()[0]
    chance_alto = (vitorias_score_alto / trades_score_alto * 100) if trades_score_alto > 0 else 0.0
    conn.close()

    return {
        "total": total,
        "vitorias": vitorias,
        "derrotas": derrotas,
        "win_rate": win_rate,
        "lucro_total": lucro_total,
        "score_vencedores": score_vencedores,
        "score_perdedores": score_perdedores,
        "chance_alto": chance_alto
    }

def reset_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM trades")
    conn.commit()
    conn.close()


def obter_trades_paper_abertos(symbol=PAPER_SYMBOL):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    linhas = c.execute(
        "SELECT id, timestamp, simbolo, direcao, entrada, stop_loss, take_profit, quantidade, valor_arriscado, aberto_em "
        "FROM trades WHERE tipo = 'paper' AND simbolo = ? AND status = 'open' ORDER BY timestamp ASC",
        (symbol,),
    ).fetchall()
    conn.close()
    trades = []
    for linha in linhas:
        trades.append(
            {
                "id": linha[0],
                "timestamp": linha[1],
                "symbol": linha[2],
                "direcao": linha[3],
                "entrada": float(linha[4]),
                "stop_loss": float(linha[5]),
                "take_profit": float(linha[6]),
                "quantidade": float(linha[7] or 0.0),
                "valor_arriscado": float(linha[8] or 0.0),
                "aberto_em": linha[9],
            }
        )
    return trades


def registrar_trade_paper(symbol, direcao, entrada, stop_loss, take_profit, quantidade, valor_arriscado, rr_planejado, filtros_aplicados=True):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    timestamp = datetime.now(timezone.utc).isoformat()
    c.execute(
        """
        INSERT INTO trades (
            timestamp, tipo, simbolo, status, direcao, resultado, score,
            lucro_percent, rr_planejado, entrada, stop_loss, take_profit,
            quantidade, valor_arriscado, aberto_em, filtros_aplicados
        )
        VALUES (?, 'paper', ?, 'open', ?, 'PENDENTE', 0, 0.0, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            timestamp,
            symbol,
            direcao,
            rr_planejado,
            entrada,
            stop_loss,
            take_profit,
            quantidade,
            valor_arriscado,
            timestamp,
            1 if filtros_aplicados else 0,
        ),
    )
    trade_id = c.lastrowid
    conn.commit()
    conn.close()
    return trade_id


def finalizar_trade_paper(trade_id, saida, lucro_percent, lucro_reais, resultado, motivo_saida):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    timestamp = datetime.now(timezone.utc).isoformat()
    c.execute(
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
    conn.close()


def obter_paper_stats(symbol=PAPER_SYMBOL):
    def _consultar_metricas(where_sql, parametros):
        total_local = c.execute(
            f"SELECT COUNT(*) FROM trades WHERE {where_sql}",
            parametros,
        ).fetchone()[0]
        if total_local == 0:
            return None

        vitorias_local = c.execute(
            f"SELECT COUNT(*) FROM trades WHERE {where_sql} AND resultado = 'GANHO'",
            parametros,
        ).fetchone()[0]
        win_rate_local = (vitorias_local / total_local) * 100 if total_local > 0 else 0.0
        lucro_total_percent_local = c.execute(
            f"SELECT SUM(lucro_percent) FROM trades WHERE {where_sql}",
            parametros,
        ).fetchone()[0] or 0.0
        lucro_total_reais_local = c.execute(
            f"SELECT SUM(lucro_reais) FROM trades WHERE {where_sql}",
            parametros,
        ).fetchone()[0] or 0.0
        lucro_bruto_local = c.execute(
            f"SELECT SUM(lucro_reais) FROM trades WHERE {where_sql} AND lucro_reais > 0",
            parametros,
        ).fetchone()[0] or 0.0
        perda_bruta_local = abs(c.execute(
            f"SELECT SUM(lucro_reais) FROM trades WHERE {where_sql} AND lucro_reais < 0",
            parametros,
        ).fetchone()[0] or 0.0)
        profit_factor_local = (lucro_bruto_local / perda_bruta_local) if perda_bruta_local > 0 else (float("inf") if lucro_bruto_local > 0 else 0.0)
        rr_medio_local = c.execute(
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

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    metricas_todas = _consultar_metricas(
        "tipo = 'paper' AND simbolo = ? AND status = 'closed'",
        (symbol,),
    )
    metricas_filtradas = _consultar_metricas(
        "tipo = 'paper' AND simbolo = ? AND status = 'closed' AND filtros_aplicados = 1",
        (symbol,),
    )
    conn.close()

    if metricas_todas is None:
        return None

    return {
        "symbol": symbol,
        "todas": metricas_todas,
        "filtradas": metricas_filtradas,
    }


def obter_ultimos_trades_paper(symbol=PAPER_SYMBOL, limite=30):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    linhas = c.execute(
        """
        SELECT timestamp, resultado, lucro_percent, lucro_reais, filtros_aplicados
        FROM trades
        WHERE tipo = 'paper' AND simbolo = ? AND status = 'closed'
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (symbol, limite),
    ).fetchall()
    conn.close()

    trades = []
    for linha in linhas:
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


def registrar_validacao_sol(total_trades, profit_factor, win_rate, drawdown_max, resultado, comparacao_walkforward):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    timestamp = datetime.now(timezone.utc).isoformat()
    c.execute(
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
    conn.close()


async def validar_sol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trades = obter_ultimos_trades_paper(PAPER_SYMBOL, limite=30)
    if not trades:
        await update.message.reply_text("ℹ️ Ainda não há trades paper fechados suficientes para validar a SOL.")
        return

    metricas = calcular_metricas_trade_history(trades)
    if metricas is None:
        await update.message.reply_text("❌ Não foi possível calcular a validação da SOL.")
        return

    pf = metricas["profit_factor"]
    win_rate = metricas["win_rate"]
    drawdown_max = metricas["drawdown_max"]
    total = metricas["total"]

    walkforward_pf = 1.34
    walkforward_win = 45.56
    walkforward_dd = 2.86
    comparacao = (
        f"Walk-forward: PF {fmt_num(walkforward_pf)}, Win {fmt_num(walkforward_win)}%, DD {fmt_num(walkforward_dd)}% | "
        f"Paper: PF {fmt_num(pf)}, Win {fmt_num(win_rate)}%, DD {fmt_num(drawdown_max)}%"
    )

    if pf > 1.0 and drawdown_max < 5.0:
        resultado = f"✅ SOL validada para operação real (PF: {fmt_num(pf)}, Win: {fmt_num(win_rate)}%)"
    elif pf < 1.0:
        resultado = "❌ SOL ainda não validada. Aguarde mais trades ou ajuste os filtros."
    else:
        resultado = f"⚠️ SOL em observação (PF: {fmt_num(pf)}, DD: {fmt_num(drawdown_max)}%)"

    registrar_validacao_sol(
        total_trades=total,
        profit_factor=pf,
        win_rate=win_rate,
        drawdown_max=drawdown_max,
        resultado=resultado,
        comparacao_walkforward=comparacao,
    )

    await update.message.reply_text(
        "🧪 Validação da SOL\n\n"
        f"{resultado}\n\n"
        f"Trades analisados: {total}\n"
        f"Profit Factor: {fmt_num(pf)}\n"
        f"Win Rate: {fmt_num(win_rate)}%\n"
        f"Drawdown Máx.: {fmt_num(drawdown_max)}%\n\n"
        f"{comparacao}"
    )


def _obter_sinal_paper_sol():
    if backtester is None:
        return None
    try:
        df = backtester.baixar_dados_historicos(symbol=PAPER_SYMBOL)
        if df is None or df.empty:
            return None
        try:
            contextos = backtester._precomputar_contextos_otimizacao(df)
        except Exception as e:
            logging.warning(f"Falha ao precomputar contextos do paper SOL: {e}")
            return None
        if not contextos:
            return None
        contexto = contextos[-1]
        return backtester._simular_decisao_contexto(
            contexto,
            volume_minimo_multiplicador=PAPER_CONFIG["volume_minimo_multiplicador"],
            volume_alto_multiplicador=1.5,
            exigir_rr_minimo=PAPER_CONFIG["exigir_rr_minimo"],
            regime_modo=PAPER_CONFIG["regime_modo"],
            exigir_fvg_nao_tocado=PAPER_CONFIG["exigir_fvg_nao_tocado"],
            lookback_fvg=PAPER_CONFIG["lookback_fvg"] or 10,
        )
    except Exception as e:
        logging.warning(f"Falha ao gerar sinal paper SOL: {e}")
        return None


def _avaliar_filtros_paper(df, sinal, decisao_info, regime_info):
    if not KILLZONE_SOL or esta_em_killzone():
        killzone_ok = True
    else:
        killzone_ok = False

    adx = regime_info.get("adx")
    rsi = decisao_info.get("rsi")
    direcao = sinal.get("direcao")

    adx_ok = adx is not None and adx >= 20
    if direcao == "COMPRA":
        rsi_ok = rsi is not None and rsi <= 55
    else:
        rsi_ok = rsi is not None and rsi >= 45

    filtros_aplicados = killzone_ok and adx_ok and rsi_ok
    detalhes = {
        "killzone_ok": killzone_ok,
        "adx_ok": adx_ok,
        "rsi_ok": rsi_ok,
    }
    return filtros_aplicados, detalhes


async def monitorar_paper_sol(context: ContextTypes.DEFAULT_TYPE):
    if not PAPER_TRADING_ATIVO:
        return

    try:
        chat_id = context.job.data["chat_id"]
        if backtester is None:
            registrar_decisao_observabilidade(
                symbol=PAPER_SYMBOL,
                modo="PAPER_SOL",
                decisao="ERRO",
                direcao="N/A",
                preco=None,
                regime="N/D",
                adx=None,
                volume_status="N/D",
                motivo="Backtester indisponível para o paper trading.",
                bloqueado_por="N/A",
                fonte_dados="N/D",
                erro="backtester indisponível",
            )
            return

        df = backtester.baixar_dados_historicos(symbol=PAPER_SYMBOL)
        if df is None or df.empty:
            registrar_decisao_observabilidade(
                symbol=PAPER_SYMBOL,
                modo="PAPER_SOL",
                decisao="AGUARDAR",
                direcao="N/A",
                preco=None,
                regime="N/D",
                adx=None,
                volume_status="N/D",
                motivo="Sem dados suficientes para monitorar o paper trading.",
                bloqueado_por="N/D",
                fonte_dados="N/D",
                erro="N/D",
            )
            return

        fonte_dados = obter_fonte_dados_df(df)
        preco_atual = float(df["close"].iloc[-1])
        candle = df.iloc[-1]
        regime_info = classificar_regime(df)
        aberto = obter_trades_paper_abertos(PAPER_SYMBOL)

        if aberto:
            for trade in aberto:
                direcao = trade["direcao"]
                stop_loss = trade["stop_loss"]
                take_profit = trade["take_profit"]
                quantidade = trade["quantidade"]
                entrada = trade["entrada"]

                stop_atingido = False
                take_atingido = False
                if direcao == "COMPRA":
                    stop_atingido = float(candle["low"]) <= stop_loss
                    take_atingido = float(candle["high"]) >= take_profit
                    if stop_atingido:
                        saida = stop_loss
                        lucro_reais = quantidade * (saida - entrada)
                        lucro_percent = (lucro_reais / 10000) * 100
                        finalizar_trade_paper(trade["id"], saida, lucro_percent, lucro_reais, "PERDA", "STOP")
                        registrar_decisao_observabilidade(
                            symbol=PAPER_SYMBOL,
                            modo="PAPER_SOL",
                            decisao="TRADE_FECHADO",
                            direcao=direcao,
                            preco=saida,
                            regime=regime_info.get("regime"),
                            adx=regime_info.get("adx"),
                            volume_status=regime_info.get("volatilidade"),
                            motivo="Fechado no STOP",
                            bloqueado_por="N/A",
                            fonte_dados=fonte_dados,
                            erro="N/A",
                        )
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"🧪 Paper SOL fechado por STOP. Resultado: {fmt_num(lucro_percent, '+.2f')}%",
                        )
                        continue
                    if take_atingido:
                        saida = take_profit
                        lucro_reais = quantidade * (saida - entrada)
                        lucro_percent = (lucro_reais / 10000) * 100
                        finalizar_trade_paper(trade["id"], saida, lucro_percent, lucro_reais, "GANHO", "TAKE_PROFIT")
                        registrar_decisao_observabilidade(
                            symbol=PAPER_SYMBOL,
                            modo="PAPER_SOL",
                            decisao="TRADE_FECHADO",
                            direcao=direcao,
                            preco=saida,
                            regime=regime_info.get("regime"),
                            adx=regime_info.get("adx"),
                            volume_status=regime_info.get("volatilidade"),
                            motivo="Fechado no TAKE PROFIT",
                            bloqueado_por="N/A",
                            fonte_dados=fonte_dados,
                            erro="N/A",
                        )
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"🧪 Paper SOL fechado por TAKE PROFIT. Resultado: {fmt_num(lucro_percent, '+.2f')}%",
                        )
                        continue
                else:
                    stop_atingido = float(candle["high"]) >= stop_loss
                    take_atingido = float(candle["low"]) <= take_profit
                    if stop_atingido:
                        saida = stop_loss
                        lucro_reais = quantidade * (entrada - saida)
                        lucro_percent = (lucro_reais / 10000) * 100
                        finalizar_trade_paper(trade["id"], saida, lucro_percent, lucro_reais, "PERDA", "STOP")
                        registrar_decisao_observabilidade(
                            symbol=PAPER_SYMBOL,
                            modo="PAPER_SOL",
                            decisao="TRADE_FECHADO",
                            direcao=direcao,
                            preco=saida,
                            regime=regime_info.get("regime"),
                            adx=regime_info.get("adx"),
                            volume_status=regime_info.get("volatilidade"),
                            motivo="Fechado no STOP",
                            bloqueado_por="N/A",
                            fonte_dados=fonte_dados,
                            erro="N/A",
                        )
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"🧪 Paper SOL fechado por STOP. Resultado: {fmt_num(lucro_percent, '+.2f')}%",
                        )
                        continue
                    if take_atingido:
                        saida = take_profit
                        lucro_reais = quantidade * (entrada - saida)
                        lucro_percent = (lucro_reais / 10000) * 100
                        finalizar_trade_paper(trade["id"], saida, lucro_percent, lucro_reais, "GANHO", "TAKE_PROFIT")
                        registrar_decisao_observabilidade(
                            symbol=PAPER_SYMBOL,
                            modo="PAPER_SOL",
                            decisao="TRADE_FECHADO",
                            direcao=direcao,
                            preco=saida,
                            regime=regime_info.get("regime"),
                            adx=regime_info.get("adx"),
                            volume_status=regime_info.get("volatilidade"),
                            motivo="Fechado no TAKE PROFIT",
                            bloqueado_por="N/A",
                            fonte_dados=fonte_dados,
                            erro="N/A",
                        )
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"🧪 Paper SOL fechado por TAKE PROFIT. Resultado: {fmt_num(lucro_percent, '+.2f')}%",
                        )
                        continue
            return

        sinal = _obter_sinal_paper_sol()
        if not sinal or sinal.get("direcao") not in ("COMPRA", "VENDA"):
            registrar_decisao_observabilidade(
                symbol=PAPER_SYMBOL,
                modo="PAPER_SOL",
                decisao="AGUARDAR",
                direcao="N/A",
                preco=preco_atual,
                regime=regime_info.get("regime"),
                adx=regime_info.get("adx"),
                volume_status=regime_info.get("volatilidade"),
                motivo="Sem sinal válido no momento.",
                bloqueado_por="N/A",
                fonte_dados=fonte_dados,
                erro="N/A",
            )
            return

        agora_utc = datetime.now(timezone.utc)
        horario_utc = agora_utc.strftime("%H:%M")
        if KILLZONE_SOL and not esta_em_killzone():
            registrar_decisao_observabilidade(
                symbol=PAPER_SYMBOL,
                modo="PAPER_SOL",
                decisao="BLOQUEADO_KILLZONE",
                direcao=sinal.get("direcao"),
                preco=preco_atual,
                regime=regime_info.get("regime"),
                adx=regime_info.get("adx"),
                volume_status=regime_info.get("volatilidade"),
                motivo="Fora da Killzone.",
                bloqueado_por="KILLZONE",
                fonte_dados=fonte_dados,
                erro="N/A",
            )
            logging.info(f"Alerta bloqueado: fora da Killzone (Horário atual: {horario_utc} UTC)")
            return

        decisao_info = tomar_decisao(df, symbol=PAPER_SYMBOL, modo="PAPER_SOL", fonte_dados=fonte_dados)
        filtros_aplicados, detalhes_filtros = _avaliar_filtros_paper(df, sinal, decisao_info, regime_info)

        entrada = float(sinal["entrada"])
        stop_loss = float(sinal["stop_loss"])
        take_profit = float(sinal["take_profit"])
        rr_planejado = float(sinal.get("rr") or 0.0)
        capital_teste = 10000
        quantidade, valor_arriscado = calcular_tamanho_posicao(capital_teste, 1.0, entrada, stop_loss)
        if quantidade <= 0:
            registrar_decisao_observabilidade(
                symbol=PAPER_SYMBOL,
                modo="PAPER_SOL",
                decisao="BLOQUEADO_FILTRO",
                direcao=sinal.get("direcao"),
                preco=entrada,
                regime=regime_info.get("regime"),
                adx=regime_info.get("adx"),
                volume_status=decisao_info.get("volume_status"),
                motivo="Tamanho de posição inválido.",
                bloqueado_por="RISK",
                fonte_dados=fonte_dados,
                erro="N/A",
            )
            return

        trade_id = registrar_trade_paper(
            PAPER_SYMBOL,
            sinal["direcao"],
            entrada,
            stop_loss,
            take_profit,
            quantidade,
            valor_arriscado,
            rr_planejado,
            filtros_aplicados=filtros_aplicados,
        )

        if filtros_aplicados:
            registrar_decisao_observabilidade(
                symbol=PAPER_SYMBOL,
                modo="PAPER_SOL",
                decisao="TRADE_ABERTO",
                direcao=sinal["direcao"],
                preco=entrada,
                regime=regime_info.get("regime"),
                adx=regime_info.get("adx"),
                volume_status=decisao_info.get("volume_status"),
                motivo=sinal.get("motivo") or decisao_info.get("motivo") or "Trade paper aberto.",
                bloqueado_por="N/A",
                fonte_dados=fonte_dados,
                erro="N/A",
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🧪 *Paper SOL aberto*\n"
                    f"Direção: {sinal['direcao']}\n"
                    f"Entrada: {fmt_num(entrada, ',.4f')}\n"
                    f"Stop: {fmt_num(stop_loss, ',.4f')}\n"
                    f"Take: {fmt_num(take_profit, ',.4f')}\n"
                    f"R/R: {fmt_num(rr_planejado)}\n"
                    f"Trade ID: {trade_id}"
                ),
                parse_mode="Markdown",
            )
        else:
            bloqueado_por = "FILTRO"
            if not detalhes_filtros.get("killzone_ok"):
                bloqueado_por = "KILLZONE"
            elif not detalhes_filtros.get("adx_ok"):
                bloqueado_por = "ADX"
            elif not detalhes_filtros.get("rsi_ok"):
                bloqueado_por = "RSI"
            elif regime_info.get("regime") == "CHOP":
                bloqueado_por = "CHOP"
            registrar_decisao_observabilidade(
                symbol=PAPER_SYMBOL,
                modo="PAPER_SOL",
                decisao="BLOQUEADO_FILTRO",
                direcao=sinal.get("direcao"),
                preco=entrada,
                regime=regime_info.get("regime"),
                adx=regime_info.get("adx"),
                volume_status=decisao_info.get("volume_status"),
                motivo=(
                    f"Filtros bloquearam o sinal: ADX_ok={detalhes_filtros['adx_ok']}, "
                    f"RSI_ok={detalhes_filtros['rsi_ok']}, Killzone_ok={detalhes_filtros['killzone_ok']}."
                ),
                bloqueado_por=bloqueado_por,
                fonte_dados=fonte_dados,
                erro="N/A",
            )
            logging.info(
                "Paper SOL registrado sem alerta: filtros bloquearam o sinal "
                f"(ADX_ok={detalhes_filtros['adx_ok']}, RSI_ok={detalhes_filtros['rsi_ok']}, Killzone_ok={detalhes_filtros['killzone_ok']})."
            )
    except Exception as e:
        registrar_decisao_observabilidade(
            symbol=PAPER_SYMBOL,
            modo="PAPER_SOL",
            decisao="ERRO",
            direcao="N/A",
            preco=None,
            regime="N/D",
            adx=None,
            volume_status="N/D",
            motivo="Falha no monitoramento do paper SOL.",
            bloqueado_por="N/A",
            fonte_dados="N/D",
            erro=str(e),
        )
        logging.warning(f"Erro no monitoramento paper SOL: {e}")

def obter_dados_risco_historico(capital):
    """
    Retorna perdas do dia em valor absoluto e histórico simples de resultados.
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    linhas = c.execute(
        "SELECT resultado, lucro_percent, timestamp FROM trades ORDER BY timestamp ASC"
    ).fetchall()
    conn.close()

    perdas_hoje = 0.0
    historico = []
    hoje = datetime.now().date()

    for resultado, lucro_percent, timestamp in linhas:
        historico.append(resultado)
        if resultado != "PERDA":
            continue

        try:
            data_trade = datetime.fromisoformat(timestamp).date()
        except ValueError:
            continue

        if data_trade == hoje:
            try:
                perdas_hoje += abs(float(lucro_percent or 0.0)) * capital / 100
            except (TypeError, ValueError):
                continue

    return perdas_hoje, historico


def obter_contexto_risco(decisao_info, capital=10000, risco_percentual=1.0):
    """
    Calcula o contexto de risco para relatório e bloqueio operacional.
    Retorna None quando a gestão de risco não estiver disponível.
    """
    if not all(
        callable(func)
        for func in (
            calcular_tamanho_posicao,
            verificar_limite_diario,
            verificar_sequencia_perdas,
        )
    ):
        return None

    try:
        entrada = decisao_info.get("entrada")
        stop_loss = decisao_info.get("stop_loss")
        if entrada is None or stop_loss is None:
            return None

        quantidade, valor_arriscado = calcular_tamanho_posicao(
            capital, risco_percentual, entrada, stop_loss
        )
        perdas_hoje, historico = obter_dados_risco_historico(capital)
        limite_diario_atingido = verificar_limite_diario(capital, perdas_hoje)
        sequencia_perdas_atingida = verificar_sequencia_perdas(historico)

        return {
            "capital": capital,
            "risco_percentual": risco_percentual,
            "entrada": entrada,
            "stop_loss": stop_loss,
            "quantidade": quantidade,
            "valor_arriscado": valor_arriscado,
            "perdas_hoje": perdas_hoje,
            "limite_diario_atingido": limite_diario_atingido,
            "sequencia_perdas_atingida": sequencia_perdas_atingida,
        }
    except Exception:
        return None


def aplicar_bloqueio_risco(decisao_info, capital=10000, risco_percentual=1.0):
    """
    Atualiza o veredito quando limites de risco forem atingidos.
    Retorna o contexto de risco para uso no relatório.
    """
    risco_contexto = obter_contexto_risco(decisao_info, capital, risco_percentual)
    if not risco_contexto:
        return None

    if risco_contexto["limite_diario_atingido"]:
        decisao_info["decisao"] = "BLOQUEADO POR RISCO (Limite Diário)"
        decisao_info["motivo"] = "Limite diário de perda atingido."
    elif risco_contexto["sequencia_perdas_atingida"]:
        decisao_info["decisao"] = "BLOQUEADO POR RISCO (Sequência de Perdas)"
        decisao_info["motivo"] = "Sequência máxima de perdas consecutivas atingida."

    return risco_contexto


def formatar_linha_risco(risco_contexto):
    if not risco_contexto:
        return None

    return (
        f"📊 *Risco:* {fmt_num(risco_contexto.get('risco_percentual'), '.1f')}% da conta "
        f"(R$ {fmt_num(risco_contexto.get('valor_arriscado'))}) | "
        f"Posição: {fmt_num(risco_contexto.get('quantidade'), '.6f')} BTC"
    )


def fmt_num(val, formato=".2f"):
    if val is None:
        return "N/A"
    if isinstance(val, float) and math.isinf(val):
        return "inf"
    try:
        return f"{val:{formato}}"
    except (TypeError, ValueError):
        return "N/A"


def obter_fonte_dados_df(df):
    if df is None or getattr(df, "empty", True):
        return "N/D"
    fonte = getattr(df, "attrs", {}).get("fonte_dados")
    return fonte or "BINANCE"


def registrar_decisao_segura(**kwargs):
    try:
        payload = dict(kwargs)
        payload.setdefault("strategy_version", "v2_risk_safe")
        log_decisao(**payload)
    except Exception as exc:
        logging.warning(f"Falha ao registrar decisão operacional: {exc}")


def registrar_decisao_observabilidade(**kwargs):
    registrar_decisao_segura(**kwargs)

# ---------- Variáveis globais do vigia ----------
vigia_ativo = False
ultimo_regime_vigia = None
ultimo_alerta_timestamp = None

# ---------- Funções auxiliares ----------
def calcular_atr(df, periodo=14):
    max_min = df["high"] - df["low"]
    max_fech_ant = abs(df["high"] - df["close"].shift(1))
    min_fech_ant = abs(df["low"] - df["close"].shift(1))
    true_range = pd.concat([max_min, max_fech_ant, min_fech_ant], axis=1).max(axis=1)
    atr = true_range.rolling(window=periodo).mean()
    return atr

def obter_funding_info():
    """Retorna string formatada com funding rate + status, ou 'Indisponível'."""
    funding = obter_funding_rate()
    if funding is not None:
        funding_pct = funding * 100
        if funding_pct > 0.01:
            f_status = "ALTO (Longs pagando)"
        elif funding_pct < -0.01:
            f_status = "NEGATIVO (Shorts pagando)"
        else:
            f_status = "NEUTRO"
        return f"{fmt_num(funding_pct, '.3f')}% ({f_status})"
    return "Indisponível"


def formatar_adx_linha(regime_info):
    adx = regime_info.get("adx")
    if adx is None:
        return None
    regime = regime_info.get("regime")
    if regime == "CHOP":
        return f"📊 *ADX:* {adx} (Lateral/CHOP)\n"
    return f"📊 *ADX:* {adx} (Tendencial)\n"

def formatar_rsi_linha(rsi, rsi_status=None):
    if rsi is None:
        return None
    status = rsi_status or "Neutro"
    return f"📊 *RSI(14):* {fmt_num(rsi, '.0f')} ({status})\n"

def obter_dados_resumidos():
    """Retorna um dicionário com os principais indicadores para a IA."""
    df = baixar_dados_btc()
    if df.empty:
        return None

    decisao_info = tomar_decisao(df)
    if decisao_info.get("regime") == "CHOP":
        decisao_info.update({
            "decisao": "AGUARDAR (MERCADO LATERAL)",
            "score": 0,
            "stop_loss": None,
            "take_profit": None,
            "risco": None,
            "recompensa": None,
            "rr": None,
            "direcao": None,
            "motivo": "Regime lateral/CHOP. Nenhuma operação recomendada.",
        })
    regime_info = classificar_regime(df)
    tendencia = tendencia_geral(df)
    fvg = identificar_fvg(df)

    preco_atual = df['close'].iloc[-1]
    atr = calcular_atr(df, 14).iloc[-1]

    dados = {
        "preco_atual": round(preco_atual, 2),
        "atr": round(atr, 2),
        "tendencia": tendencia,
        "regime": regime_info['regime'],
        "adx": regime_info['adx'],
        "volatilidade": regime_info['volatilidade'],
        "fvg": fvg,
        "veredito": decisao_info['decisao'],
        "score": decisao_info['score'],
        "rr": decisao_info.get('rr'),
        "volume_status": decisao_info.get('volume_status', 'NEUTRO'),
        "motivo": decisao_info.get('motivo', ''),
        "zona_entrada_ideal": decisao_info.get('zona_entrada_ideal'),
        "funding_rate": obter_funding_info()  # NOVO
    }

    return dados

# ---------- Relatório completo (/analisa) ----------
def obter_analise():
    df = baixar_dados_btc()
    if df.empty:
        return "❌ Não foi possível obter os dados da Binance."

    decisao_info = tomar_decisao(df)

    # Aplica bloqueio de venda no modo SPOT
    if MODO_OPERACAO == "SPOT" and decisao_info.get("direcao") == "VENDA":
        decisao_info.update({
            "decisao": "AGUARDAR (Spot: Sem Short)",
            "score": 0,
            "stop_loss": None,
            "take_profit": None,
            "risco": None,
            "recompensa": None,
            "rr": None,
            "motivo": "Modo Spot ativo: apenas compras são permitidas. Operação de venda bloqueada.",
            "direcao": None
        })

    risco_contexto = aplicar_bloqueio_risco(decisao_info, capital=10000, risco_percentual=1.0)

    preco_atual = df['close'].iloc[-1]
    volume = df['volume'].iloc[-1]
    atr_atual = calcular_atr(df, 14).iloc[-1] if not df.empty else 0

    tendencia = tendencia_geral(df)
    swings = ultimos_swings(df)
    fvg = identificar_fvg(df)

    regime_info = classificar_regime(df)
    regime = regime_info['regime']
    adx = regime_info['adx']
    volatilidade = regime_info['volatilidade']
    rsi = decisao_info.get('rsi')
    rsi_status = decisao_info.get('rsi_status')

    contexto = None
    if decisao_info.get('take_profit') and decisao_info['decisao'] not in ('AGUARDAR', 'AGUARDAR RETRAÇÃO', 'AGUARDAR (Volume Baixo)', 'AGUARDAR (Spot: Sem Short)'):
        take_profit = decisao_info['take_profit']
        if decisao_info.get('direcao') == 'COMPRA':
            dist_percent = (take_profit - preco_atual) / preco_atual * 100
        else:
            dist_percent = (preco_atual - take_profit) / preco_atual * 100
            if dist_percent > 0:
                contexto = contexto_tempo(dist_percent, df)

    mensagem = (
        f"📊 *Análise BTC/USDT*\n\n"
        f"💰 *Preço Atual:* {preco_atual:,.2f} USD\n"
        f"📏 *ATR(14):* {atr_atual:,.2f}\n"
        f"📦 *Volume:* {volume:,.2f}\n\n"
        f"{tendencia}\n"
        f"{swings}\n"
        f"🕯️ {fvg}\n\n"
        f"📌 *Modo:* {MODO_OPERACAO}\n"
        f"📌 *Regime:* {regime}"
    )
    if adx is not None:
        mensagem += f" (ADX: {adx})"
    mensagem += f" | Vol: {volatilidade}\n"
    adx_linha = formatar_adx_linha(regime_info)
    if adx_linha:
        mensagem += adx_linha
    rsi_linha = formatar_rsi_linha(rsi, rsi_status)
    if rsi_linha:
        mensagem += rsi_linha

    if contexto:
        mensagem += f"⏳ *Horizonte Estimado:* {contexto}\n"

        mensagem += f"\n🚦 *Veredito:* {decisao_info['decisao']}\n"
        mensagem += f"⭐ *Score de Confiança:* {decisao_info['score']}/10\n"

    if decisao_info['zona_entrada_ideal'] is not None:
        mensagem += f"📍 *Zona de Entrada Ideal (61.8%):* {fmt_num(decisao_info.get('zona_entrada_ideal'), ',.2f')}\n"

    vol_status = decisao_info.get('volume_status', 'NEUTRO')
    vol_at = decisao_info.get('volume_atual', 0)
    vol_med = decisao_info.get('volume_medio', 0)
    mensagem += f"📊 *Volume:* {fmt_num(vol_at, ',.0f')} | Média 20: {fmt_num(vol_med, ',.0f')} | Status: {vol_status}\n"

    # NOVA LINHA: Funding Rate
    mensagem += f"📊 *Funding Rate:* {obter_funding_info()}\n"

    linha_risco = formatar_linha_risco(risco_contexto)
    if linha_risco:
        mensagem += f"{linha_risco}\n"

    if decisao_info['decisao'] not in ('AGUARDAR', 'AGUARDAR RETRAÇÃO', 'AGUARDAR (Volume Baixo)', 'AGUARDAR (Spot: Sem Short)'):
        mensagem += f"📌 *Direção:* {decisao_info['direcao']} (Regime {regime})\n"
        mensagem += f"🎯 *Entrada Sugerida:* {fmt_num(decisao_info.get('entrada'), ',.2f')}\n"
        mensagem += f"🛑 *Stop Loss:* {fmt_num(decisao_info.get('stop_loss'), ',.2f')}\n"
        mensagem += f"🏆 *Take Profit (Alvo):* {fmt_num(decisao_info.get('take_profit'), ',.2f')}\n"
        if decisao_info['rr'] is not None:
            mensagem += f"📊 *R/R:* {fmt_num(decisao_info.get('rr'), '.1f')}\n"
    else:
        mensagem += f"🎯 *Entrada Sugerida:* N/A\n"
        mensagem += f"🛑 *Stop Loss:* N/A\n"
        mensagem += f"🏆 *Take Profit (Alvo):* N/A\n"
        mensagem += f"📊 *R/R:* N/A\n"

    mensagem += f"💡 *Motivo:* {decisao_info['motivo']}"

    return mensagem

# ---------- Comandos básicos ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Bem-vindo ao Bot de Análise BTC!\n\n"
        f"Modo atual: {MODO_OPERACAO}\n\n"
        "**📊 Análise**\n"
        "/analisa – Relatório completo com veredito\n"
        "/ia – Relatório + comentário inteligente da IA\n\n"
        "**👀 Monitoramento**\n"
        "/vigia – Ativar monitoramento automático da zona de entrada\n"
        "/status – Ver se o vigia está ativo e a zona alvo\n"
        "/parar – Parar o monitoramento\n\n"
        "**📘 Diário**\n"
        "/trade – Registrar resultado de trade\n"
        "/stats – Estatísticas do histórico\n"
        "/reset_stats – Limpar histórico\n\n"
        "**🧪 Paper Trading**\n"
        "/paper_stats – Ver desempenho do paper trading da SOL\n"
        "/validar_sol – Validar a SOL com base no paper trading\n\n"
        "**⚙️ Configuração**\n"
        "Use /status para checar o estado atual do bot e dos filtros"
    )

async def analisa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Buscando dados e calculando análise...")
    try:
        resultado = obter_analise()
    except Exception as e:
        resultado = f"❌ Erro durante a análise: {e}"
    await update.message.reply_text(resultado)

async def comando_ia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 Consultando a IA, aguarde...")

    try:
        dados = obter_dados_resumidos()
        if dados is None:
            await update.message.reply_text("❌ Não foi possível obter os dados de mercado.")
            return

        relatorio = obter_analise()
        comentario = gerar_comentario_ia(dados)

        mensagem_final = f"{relatorio}\n\n{comentario}"
        await update.message.reply_text(mensagem_final)

    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao gerar análise com IA: {e}")

async def comando_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Iniciando backtest histórico. Isso pode levar alguns segundos...")
    try:
        import backtester

        resultado = await asyncio.to_thread(backtester.baixar_dados_historicos)
        relatorio = await asyncio.to_thread(backtester.executar_backtest, resultado)
        relatorio_final = backtester.gerar_relatorio_backtest(relatorio)
        await asyncio.to_thread(backtester.salvar_relatorio, relatorio_final)

        summary = relatorio_final["summary"]
        mensagem = (
            "📈 Backtest concluído\n\n"
            f"Trades: {summary['total_trades']}\n"
            f"Win rate: {fmt_num(summary.get('win_rate'), '.2f')}%\n"
            f"Lucro/Prejuízo: {fmt_num(summary.get('lucro_total_percent'), '.2f')}% "
            f"(R$ {fmt_num(summary.get('lucro_total_valor'), '.2f')})\n"
            f"Profit Factor: {fmt_num(summary.get('profit_factor'))}\n"
            f"Drawdown Máx.: {fmt_num(summary.get('drawdown_max_percent'), '.2f')}%\n"
            f"Média R/R: {fmt_num(summary.get('media_rr'), '.3f')}\n"
            f"Sequência Máx. de Perdas: {summary['sequencia_maxima_perdas']}"
        )
        await update.message.reply_text(mensagem)
    except Exception as e:
        logging.warning(f"Erro no backtest: {e}")
        await update.message.reply_text(f"❌ Falha ao executar o backtest: {e}")

# ---------- Vigia (dual-mode adaptativo + bloqueio SPOT + funding rate) ----------
async def monitorar_preco(context: ContextTypes.DEFAULT_TYPE):
    global vigia_ativo, ultimo_regime_vigia, ultimo_alerta_timestamp
    try:
        chat_id = context.job.data['chat_id']
        df = baixar_dados_btc()
        if df.empty:
            return

        horario_utc = datetime.now(timezone.utc).strftime("%H:%M")
        preco_atual = df['close'].iloc[-1]
        regime_info = classificar_regime(df)
        regime_atual = regime_info['regime']

        if ultimo_regime_vigia is not None and regime_atual != ultimo_regime_vigia:
            jobs = context.job_queue.get_jobs_by_name("vigia_btc")
            for job in jobs:
                job.schedule_removal()
            context.job_queue.run_repeating(
                monitorar_preco, interval=60, first=10,
                name="vigia_btc", data={'chat_id': chat_id}
            )
            ultimo_regime_vigia = regime_atual
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔄 Regime alterado para {regime_atual}. Vigia reconfigurado."
            )
            return

        ultimo_regime_vigia = regime_atual

        if regime_atual in ('CHOP', 'INDEFINIDO'):
            registrar_decisao_observabilidade(
                symbol="BTCUSDT",
                modo="VIGIA_BTC",
                decisao="BLOQUEADO_FILTRO",
                direcao="N/A",
                preco=preco_atual,
                regime=regime_atual,
                adx=regime_info.get("adx"),
                volume_status=regime_info.get("volatilidade"),
                motivo="Mercado lateral/indefinido.",
                bloqueado_por="CHOP",
                fonte_dados=obter_fonte_dados_df(df),
                erro="N/A",
            )
            return

        topo, fundo = extrair_swing_high_low(df, 50)
        candle_anterior = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]

        if regime_atual == 'BULL':
            if fundo and candle_anterior['low'] < fundo:
                registrar_decisao_observabilidade(
                    symbol="BTCUSDT",
                    modo="VIGIA_BTC",
                    decisao="BLOQUEADO_FILTRO",
                    direcao="COMPRA",
                    preco=preco_atual,
                    regime=regime_atual,
                    adx=regime_info.get("adx"),
                    volume_status=regime_info.get("volatilidade"),
                    motivo="Estrutura de baixa quebrada no candle anterior.",
                    bloqueado_por="ESTRUTURA",
                    fonte_dados=obter_fonte_dados_df(df),
                    erro="N/A",
                )
                await context.bot.send_message(chat_id=chat_id, text="🚨 Estrutura de baixa quebrada. Vigia cancelado.")
                vigia_ativo = False
                jobs = context.job_queue.get_jobs_by_name("vigia_btc")
                for job in jobs:
                    job.schedule_removal()
                return
        elif regime_atual == 'BEAR':
            if topo and candle_anterior['high'] > topo:
                registrar_decisao_observabilidade(
                    symbol="BTCUSDT",
                    modo="VIGIA_BTC",
                    decisao="BLOQUEADO_FILTRO",
                    direcao="VENDA",
                    preco=preco_atual,
                    regime=regime_atual,
                    adx=regime_info.get("adx"),
                    volume_status=regime_info.get("volatilidade"),
                    motivo="Estrutura de alta quebrada no candle anterior.",
                    bloqueado_por="ESTRUTURA",
                    fonte_dados=obter_fonte_dados_df(df),
                    erro="N/A",
                )
                await context.bot.send_message(chat_id=chat_id, text="🚨 Estrutura de alta quebrada. Vigia cancelado.")
                vigia_ativo = False
                jobs = context.job_queue.get_jobs_by_name("vigia_btc")
                for job in jobs:
                    job.schedule_removal()
                return

        if MODO_OPERACAO == "SPOT" and regime_atual == 'BEAR':
            logging.info("Alerta de venda bloqueado pelo modo SPOT.")
            return

        if regime_atual == 'BULL':
            zona = topo - (topo - fundo) * 0.618 if (topo and fundo) else None
            direcao = 'COMPRA'
        else:
            zona = fundo + (topo - fundo) * 0.618 if (topo and fundo) else None
            direcao = 'VENDA'

        if zona is None:
            return

        dist_percent = abs(preco_atual - zona) / zona * 100

        if dist_percent <= 0.5:
            decisao_info = tomar_decisao(df)
            if direcao == 'COMPRA':
                fvg = extrair_fvg_bearish_acima(df, preco_atual)
                acao = "compra"
            else:
                fvg = extrair_fvg_bullish_abaixo(df, preco_atual)
                acao = "venda"

            if fvg is None:
                return

            fvg_low, fvg_high = fvg
            take_profit = fvg_high

            if direcao == 'COMPRA':
                dist_alvo = (take_profit - preco_atual) / preco_atual * 100
            else:
                dist_alvo = (preco_atual - take_profit) / preco_atual * 100
            contexto = contexto_tempo(dist_alvo, df) if dist_alvo > 0 else None

            agora = datetime.now(timezone.utc)
            dia_semana = agora.weekday()
            horario = agora.hour + agora.minute / 60.0
            alerta_extra = ""
            if dia_semana in (1, 2, 3):
                if 13 + 20/60 <= horario <= 14.0:
                    alerta_extra = "⚠️ ATENÇÃO: Horário de risco (próximo a dados econômicos dos EUA). Aguarde 5 minutos após o release.\n\n"

            # Funding rate info
            funding_str = obter_funding_info()

            mensagem = (
                f"{alerta_extra}"
                f"🚨 ALERTA DE OPORTUNIDADE!\n"
                f"BTC está a {fmt_num(dist_percent, '.2f')}% da zona de entrada ideal!\n"
                f"💰 Preço Atual: {fmt_num(preco_atual, ',.2f')}\n"
                f"📍 Zona Alvo: {fmt_num(zona, ',.2f')}\n"
                f"📝 Sugestão: Prepare a ordem de {acao}.\n"
                f"📌 *Modo:* {MODO_OPERACAO}\n"
                f"📌 *Regime:* {regime_atual}"
            )
            if regime_info['adx'] is not None:
                mensagem += f" (ADX: {regime_info['adx']})"
            mensagem += f" | Vol: {regime_info['volatilidade']}\n"
            adx_linha = formatar_adx_linha(regime_info)
            if adx_linha:
                mensagem += adx_linha
            rsi_linha = formatar_rsi_linha(decisao_info.get('rsi'), decisao_info.get('rsi_status'))
            if rsi_linha:
                mensagem += rsi_linha
            if contexto:
                mensagem += f"⏳ *Horizonte Estimado:* {contexto}\n"
            mensagem += f"📊 *Funding Rate:* {funding_str}\n"

            risco_contexto = aplicar_bloqueio_risco(decisao_info, capital=10000, risco_percentual=1.0)
            linha_risco = None
            if risco_contexto:
                if risco_contexto["limite_diario_atingido"]:
                    registrar_decisao_observabilidade(
                        symbol="BTCUSDT",
                        modo="VIGIA_BTC",
                        decisao="BLOQUEADO_FILTRO",
                        direcao=direcao,
                        preco=preco_atual,
                        regime=regime_atual,
                        adx=regime_info.get("adx"),
                        volume_status=regime_info.get("volatilidade"),
                        motivo="Limite diário de risco atingido.",
                        bloqueado_por="RISK",
                        fonte_dados=obter_fonte_dados_df(df),
                        erro="N/A",
                    )
                    logging.info("Alerta bloqueado por risco: limite diário atingido.")
                    return
                if risco_contexto["sequencia_perdas_atingida"]:
                    registrar_decisao_observabilidade(
                        symbol="BTCUSDT",
                        modo="VIGIA_BTC",
                        decisao="BLOQUEADO_FILTRO",
                        direcao=direcao,
                        preco=preco_atual,
                        regime=regime_atual,
                        adx=regime_info.get("adx"),
                        volume_status=regime_info.get("volatilidade"),
                        motivo="Sequência máxima de perdas atingida.",
                        bloqueado_por="RISK",
                        fonte_dados=obter_fonte_dados_df(df),
                        erro="N/A",
                    )
                    logging.info("Alerta bloqueado por risco: sequência de perdas atingida.")
                    return

                linha_risco = formatar_linha_risco(risco_contexto)
            if linha_risco:
                mensagem += f"{linha_risco}\n"

            if KILLZONE_BTC and not esta_em_killzone():
                registrar_decisao_observabilidade(
                    symbol="BTCUSDT",
                    modo="VIGIA_BTC",
                    decisao="BLOQUEADO_KILLZONE",
                    direcao=direcao,
                    preco=preco_atual,
                    regime=regime_atual,
                    adx=regime_info.get("adx"),
                    volume_status=regime_info.get("volatilidade"),
                    motivo="Fora da Killzone.",
                    bloqueado_por="KILLZONE",
                    fonte_dados=obter_fonte_dados_df(df),
                    erro="N/A",
                )
                logging.info(f"Alerta bloqueado: fora da Killzone (Horário atual: {horario_utc} UTC)")
                return

            agora_ts = datetime.now(timezone.utc).timestamp()
            if ultimo_alerta_timestamp is not None and (agora_ts - ultimo_alerta_timestamp) < 1800:
                logging.info("Alerta bloqueado: cooldown de 30 minutos ativo.")
                return

            registrar_decisao_observabilidade(
                symbol="BTCUSDT",
                modo="VIGIA_BTC",
                decisao="TRADE_ABERTO",
                direcao=direcao,
                preco=preco_atual,
                regime=regime_atual,
                adx=regime_info.get("adx"),
                volume_status=regime_info.get("volatilidade"),
                motivo="Alerta de entrada enviado.",
                bloqueado_por="N/A",
                fonte_dados=obter_fonte_dados_df(df),
                erro="N/A",
            )
            await context.bot.send_message(chat_id=chat_id, text=mensagem)
            ultimo_alerta_timestamp = agora_ts
            logging.info("ALERTA! Preço na zona de entrada! Verifique o Telegram.")

    except Exception as e:
        registrar_decisao_observabilidade(
            symbol="BTCUSDT",
            modo="VIGIA_BTC",
            decisao="ERRO",
            direcao="N/A",
            preco=None,
            regime="N/D",
            adx=None,
            volume_status="N/D",
            motivo="Falha no monitoramento do BTC.",
            bloqueado_por="N/A",
            fonte_dados="N/D",
            erro=str(e),
        )
        logging.warning(f"Erro no monitoramento: {e}")

async def ativar_vigia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global vigia_ativo, ultimo_regime_vigia
    if vigia_ativo:
        await update.message.reply_text("⚠️ Vigia já está ativo! Use /parar para desligar antes de ativar novamente.")
        return
    jobs = context.job_queue.get_jobs_by_name("vigia_btc")
    if jobs:
        vigia_ativo = True
        await update.message.reply_text("⚠️ Vigia já está ativo! Use /parar para desligar antes de ativar novamente.")
        return

    df = baixar_dados_btc()
    if not df.empty:
        regime_info = classificar_regime(df)
        ultimo_regime_vigia = regime_info['regime']
    else:
        ultimo_regime_vigia = None

    context.job_queue.run_repeating(
        monitorar_preco, interval=60, first=10,
        name="vigia_btc", data={'chat_id': update.effective_chat.id}
    )
    if PAPER_TRADING_ATIVO and not context.job_queue.get_jobs_by_name(PAPER_JOB_NAME):
        context.job_queue.run_repeating(
            monitorar_paper_sol, interval=60, first=15,
            name=PAPER_JOB_NAME, data={'chat_id': update.effective_chat.id}
        )
    vigia_ativo = True
    await update.message.reply_text(f"🔍 Vigia ativado! Monitorando a cada 1 minuto. Adapta-se ao regime automaticamente.\nModo: {MODO_OPERACAO}\nPara parar, use /parar.")

async def parar_vigia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global vigia_ativo, ultimo_regime_vigia
    jobs = context.job_queue.get_jobs_by_name("vigia_btc")
    paper_jobs = context.job_queue.get_jobs_by_name(PAPER_JOB_NAME)
    if not jobs:
        vigia_ativo = False
        await update.message.reply_text("ℹ️ Nenhum monitoramento ativo no momento.")
        return
    for job in jobs:
        job.schedule_removal()
    for job in paper_jobs:
        job.schedule_removal()
    vigia_ativo = False
    ultimo_regime_vigia = None
    await update.message.reply_text("🛑 Monitoramento parado com sucesso.")

async def status_vigia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global vigia_ativo
    jobs = context.job_queue.get_jobs_by_name("vigia_btc")
    paper_jobs = context.job_queue.get_jobs_by_name(PAPER_JOB_NAME)
    if jobs or vigia_ativo:
        status_msg = f"🟢 Vigia está ATIVO, verificando a cada 60 segundos.\nModo: {MODO_OPERACAO}\n"
    else:
        status_msg = f"🔴 Vigia está DESATIVADO.\nModo: {MODO_OPERACAO}\n"
    if PAPER_TRADING_ATIVO:
        status_msg += f"🧪 Paper SOLUSDT: {'ATIVO' if paper_jobs else 'DESATIVADO'}\n"
    status_msg += f"📌 Killzone BTC: {'ATIVA' if KILLZONE_BTC else 'DESATIVADA'} | Killzone SOL: {'ATIVA' if KILLZONE_SOL else 'DESATIVADA'}\n"
    try:
        df = baixar_dados_btc()
        if not df.empty:
            regime_info = classificar_regime(df)
            zona = None
            topo, fundo = extrair_swing_high_low(df, 50)
            if regime_info['regime'] == 'BULL' and topo and fundo:
                zona = topo - (topo - fundo) * 0.618
            elif regime_info['regime'] == 'BEAR' and topo and fundo:
                zona = fundo + (topo - fundo) * 0.618
            if zona:
                status_msg += f"📍 Zona Alvo atual: {fmt_num(zona, ',.2f')}\n"
            else:
                status_msg += "📍 Zona Alvo: Indisponível\n"
            status_msg += f"📌 Regime atual: {regime_info['regime']}"
            if regime_info['adx'] is not None:
                status_msg += f" (ADX: {regime_info['adx']})"
            status_msg += f" | Vol: {regime_info['volatilidade']}\n"
            adx_linha = formatar_adx_linha(regime_info)
            if adx_linha:
                status_msg += adx_linha
            status_msg += f"📊 Funding Rate: {obter_funding_info()}\n"
        else:
            status_msg += "📍 Zona Alvo: Indisponível\n"
    except Exception:
        status_msg += "📍 Zona Alvo: Indisponível\n"
    await update.message.reply_text(status_msg)

# ---------- Registro de Trade (/trade) ----------
async def trade_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📈 Compra", callback_data='COMPRA')],
        [InlineKeyboardButton("📉 Venda", callback_data='VENDA')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Qual foi a direção do trade?", reply_markup=reply_markup)
    return DIRECAO

async def trade_direcao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['direcao'] = query.data
    keyboard = [
        [InlineKeyboardButton("✅ Ganhei", callback_data='GANHO')],
        [InlineKeyboardButton("❌ Perdi", callback_data='PERDA')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Qual foi o resultado?", reply_markup=reply_markup)
    return RESULTADO

async def trade_resultado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['resultado'] = query.data
    await query.edit_message_text("Qual era o Score de Confiança na hora? (digite um número de 0 a 10)")
    return SCORE

async def trade_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        score = int(update.message.text)
        if score < 0 or score > 10:
            await update.message.reply_text("Por favor, um número entre 0 e 10.")
            return SCORE
        context.user_data['score'] = score
        await update.message.reply_text("Qual foi o Lucro/Perda em %? (ex: 1.5 ou -0.8)")
        return LUCRO
    except ValueError:
        await update.message.reply_text("Valor inválido. Digite um número inteiro.")
        return SCORE

async def trade_lucro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        lucro = float(update.message.text.replace(',', '.'))
        context.user_data['lucro_percent'] = lucro
        await update.message.reply_text("Qual era o R/R planejado? (ex: 1.5)")
        return RR
    except ValueError:
        await update.message.reply_text("Valor inválido. Digite um número decimal.")
        return LUCRO

async def trade_rr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rr = float(update.message.text.replace(',', '.'))
        direcao = context.user_data['direcao']
        resultado = context.user_data['resultado']
        score = context.user_data['score']
        lucro = context.user_data['lucro_percent']

        salvar_trade(direcao, resultado, score, lucro, rr)

        await update.message.reply_text(
            f"✅ Trade registrado com sucesso!\n"
            f"Direção: {direcao}\n"
            f"Resultado: {resultado}\n"
            f"Score: {score}/10\n"
            f"Lucro: {fmt_num(lucro, '+.2f')}%\n"
            f"R/R: {fmt_num(rr, '.1f')}"
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Valor inválido. Digite um número decimal.")
        return RR

async def trade_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Registro cancelado.")
    return ConversationHandler.END

# ---------- Estatísticas (/stats) ----------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats_data = obter_estatisticas()
    if stats_data is None:
        await update.message.reply_text("ℹ️ Nenhum trade registrado ainda. Use /trade para começar.")
        return

    mensagem = (
        f"📊 Estatísticas do Trader\n\n"
        f"Total de Trades: {stats_data['total']}\n"
        f"Win Rate: {fmt_num(stats_data.get('win_rate'), '.1f')}%\n"
        f"Lucro Total: {fmt_num(stats_data.get('lucro_total'), '+.2f')}%\n"
        f"Score Médio (Vencedores): {fmt_num(stats_data.get('score_vencedores'), '.1f')}\n"
        f"Score Médio (Perdedores): {fmt_num(stats_data.get('score_perdedores'), '.1f')}\n\n"
        f"💡 Conclusão: "
    )
    if stats_data['chance_alto'] > 0:
        mensagem += f"Seus trades com Score > 8 têm {fmt_num(stats_data.get('chance_alto'), '.0f')}% de chance de ganhar."
    else:
        mensagem += "Ainda sem dados suficientes para análise por Score."

    await update.message.reply_text(mensagem)


async def paper_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats_data = obter_paper_stats(PAPER_SYMBOL)
    if stats_data is None:
        await update.message.reply_text("ℹ️ Nenhum trade paper encerrado ainda para SOLUSDT.")
        return

    todas = stats_data["todas"]
    filtradas = stats_data["filtradas"]

    def _formatar_bloco(nome, dados):
        if not dados:
            return f"{nome}\nSem trades suficientes.\n"
        pf = dados["profit_factor"]
        return (
            f"{nome}\n"
            f"PF: {fmt_num(pf)}\n"
            f"Win Rate: {fmt_num(dados.get('win_rate'), '.1f')}%\n"
            f"Lucro Total: {fmt_num(dados.get('lucro_total_percent'), '+.2f')}% "
            f"(R$ {fmt_num(dados.get('lucro_total_reais'), '+.2f')})\n"
            f"Trades: {fmt_num(dados.get('total'), '.0f')}\n"
            f"R/R Médio: {fmt_num(dados.get('rr_medio'))}\n"
        )

    mensagem = (
        f"🧪 Estatísticas do Paper Trading SOLUSDT\n\n"
        f"=== Performance sem Filtros ===\n"
        f"{_formatar_bloco('Todos os trades', todas)}\n"
        f"=== Performance com Filtros ===\n"
        f"{_formatar_bloco('Apenas trades filtrados', filtradas)}"
    )
    await update.message.reply_text(mensagem)

# ---------- Resetar Estatísticas (/reset_stats) ----------
def _parse_dt_segura(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        try:
            return datetime.strptime(valor, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


def _obter_preco_atual_referencia(symbol):
    try:
        if symbol == PAPER_SYMBOL and backtester is not None:
            df = backtester.baixar_dados_historicos(symbol=symbol)
        else:
            df = baixar_dados_btc(simbolo=symbol)
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1]), obter_fonte_dados_df(df)
    except Exception as exc:
        logging.warning(f"Falha ao obter preço atual de referência para {symbol}: {exc}")

    ultimo_log = buscar_ultimo_decision_log(modos=["PAPER_SOL", "VIGIA_BTC"])
    if ultimo_log and ultimo_log.get("preco") is not None:
        return float(ultimo_log["preco"]), ultimo_log.get("fonte_dados") or "N/D"

    return None, "N/D"


async def paper_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ultimo_log = buscar_ultimo_decision_log(modos=["PAPER_SOL", "VIGIA_BTC"])
    preco_atual, fonte_dados = _obter_preco_atual_referencia(PAPER_SYMBOL)
    status_paper = "SIM" if PAPER_TRADING_ATIVO else "NÃO"
    jobs_vigia = context.job_queue.get_jobs_by_name("vigia_btc")
    status_vigia = "SIM" if jobs_vigia or vigia_ativo else "NÃO"
    ultimo_horario = ultimo_log["timestamp"] if ultimo_log else "N/D"
    ultima_decisao = ultimo_log["decisao"] if ultimo_log else "N/D"
    ultimo_motivo = ultimo_log["motivo"] if ultimo_log else "N/D"
    trades_abertos = contar_trades_abertos_paper(PAPER_SYMBOL)
    trades_fechados_hoje = contar_trades_fechados_hoje(PAPER_SYMBOL)
    preco_texto = fmt_num(preco_atual, ',.4f') if preco_atual is not None else "N/D"

    mensagem = (
        "📡 *Paper Status*\n\n"
        f"Paper ativo: {status_paper}\n"
        f"Vigia ativo: {status_vigia}\n"
        f"Última checagem: {ultimo_horario}\n"
        f"Último preço: {preco_texto}\n"
        f"Fonte de dados: {fonte_dados}\n"
        f"Última decisão: {ultima_decisao}\n"
        f"Último motivo: {ultimo_motivo}\n"
        f"Trades abertos: {trades_abertos}\n"
        f"Trades fechados hoje: {trades_fechados_hoje}"
    )
    await update.message.reply_text(mensagem, parse_mode="Markdown")


async def paper_abertos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trades = obter_trades_paper_abertos(PAPER_SYMBOL)
    if not trades:
        await update.message.reply_text("ℹ️ Não há trades paper abertos no momento.")
        return

    preco_atual, _ = _obter_preco_atual_referencia(PAPER_SYMBOL)
    agora = datetime.now(timezone.utc)
    linhas = ["📂 *Trades Paper Abertos*"]
    for trade in trades:
        aberto_em = _parse_dt_segura(trade.get("aberto_em") or trade.get("timestamp"))
        horas_aberto = ((agora - aberto_em).total_seconds() / 3600) if aberto_em else None
        entrada = trade.get("entrada")
        preco_ref = preco_atual
        if entrada is None or preco_ref is None:
            pnl_parcial = "N/D"
        else:
            if trade["direcao"] == "COMPRA":
                pnl_parcial = ((preco_ref - entrada) / entrada) * 100
            else:
                pnl_parcial = ((entrada - preco_ref) / entrada) * 100
            pnl_parcial = f"{pnl_parcial:+.2f}%"

        linhas.append(
            (
                f"\nID: {trade['id']}\n"
                f"Símbolo: {trade['symbol']}\n"
                f"Direção: {trade['direcao']}\n"
                f"Entrada: {fmt_num(entrada, ',.4f')}\n"
                f"Stop: {fmt_num(trade.get('stop_loss'), ',.4f')}\n"
                f"Take: {fmt_num(trade.get('take_profit'), ',.4f')}\n"
                f"Preço atual: {fmt_num(preco_ref, ',.4f') if preco_ref is not None else 'N/D'}\n"
                f"PnL parcial: {pnl_parcial}\n"
                f"Tempo aberto: {fmt_num(horas_aberto, '.2f') if horas_aberto is not None else 'N/D'} h"
            )
        )

    await update.message.reply_text("\n".join(linhas), parse_mode="Markdown")


async def paper_trades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trades = buscar_trades_paper(limite=10, symbol=PAPER_SYMBOL)
    if not trades:
        await update.message.reply_text("ℹ️ Nenhum trade paper encontrado.")
        return

    linhas = ["📜 *Últimos 10 Trades Paper*"]
    for trade in trades:
        linhas.append(
            (
                f"\nID: {trade['id']}\n"
                f"Símbolo: {trade['symbol']}\n"
                f"Direção: {trade['direcao']}\n"
                f"Entrada: {fmt_num(trade.get('entrada'), ',.4f')}\n"
                f"Saída: {fmt_num(trade.get('saida'), ',.4f')}\n"
                f"Resultado: {fmt_num(trade.get('lucro_percent'), '+.2f')}%\n"
                f"Status: {trade['status']}"
            )
        )
    await update.message.reply_text("\n".join(linhas), parse_mode="Markdown")


async def paper_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logs = buscar_ultimos_decision_logs(limite=10)
    if not logs:
        await update.message.reply_text("ℹ️ Nenhum registro de decisão encontrado.")
        return

    linhas = ["🧾 *Últimos 10 Decision Logs*"]
    for log in logs:
        linhas.append(
            (
                f"\nTimestamp: {log['timestamp']}\n"
                f"Símbolo: {log['symbol']}\n"
                f"Decisão: {log['decisao']}\n"
                f"Motivo: {log['motivo']}\n"
                f"Bloqueado por: {log['bloqueado_por']}\n"
                f"Fonte dados: {log['fonte_dados']}"
            )
        )
    await update.message.reply_text("\n".join(linhas), parse_mode="Markdown")


async def reset_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Sim, resetar tudo", callback_data='confirm_reset')],
        [InlineKeyboardButton("Cancelar", callback_data='cancel_reset')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("⚠️ Tem certeza que deseja apagar todo o histórico de trades?", reply_markup=reply_markup)

async def reset_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'confirm_reset':
        reset_db()
        await query.edit_message_text("✅ Histórico limpo com sucesso.")
    else:
        await query.edit_message_text("❌ Reset cancelado.")

# ---------- Ponto de entrada ----------
def main():
    init_db()
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

    job_queue = JobQueue()
    request = HTTPXRequest(
        read_timeout=45,
        write_timeout=45,
        connect_timeout=15,
    )
    app = Application.builder().token(TOKEN).request(request).job_queue(job_queue).build()

    # Handlers básicos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analisa", analisa))
    app.add_handler(CommandHandler("ia", comando_ia))
    app.add_handler(CommandHandler("backtest", comando_backtest))
    app.add_handler(CommandHandler("validar_sol", validar_sol))
    app.add_handler(CommandHandler("vigia", ativar_vigia))
    app.add_handler(CommandHandler("parar", parar_vigia))
    app.add_handler(CommandHandler("status", status_vigia))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("paper_stats", paper_stats))
    app.add_handler(CommandHandler("paper_status", paper_status))
    app.add_handler(CommandHandler("paper_abertos", paper_abertos))
    app.add_handler(CommandHandler("paper_trades", paper_trades))
    app.add_handler(CommandHandler("paper_log", paper_log))

    # ConversationHandler para /trade
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('trade', trade_start)],
        states={
            DIRECAO: [CallbackQueryHandler(trade_direcao)],
            RESULTADO: [CallbackQueryHandler(trade_resultado)],
            SCORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_score)],
            LUCRO: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_lucro)],
            RR: [MessageHandler(filters.TEXT & ~filters.COMMAND, trade_rr)],
        },
        fallbacks=[CommandHandler('cancel', trade_cancel)],
    )
    app.add_handler(conv_handler)

    # Handler para /reset_stats e callback
    app.add_handler(CommandHandler("reset_stats", reset_stats))
    app.add_handler(CallbackQueryHandler(reset_stats_callback, pattern='^(confirm_reset|cancel_reset)$'))

    print("🤖 Bot rodando... Pressione Ctrl+C para parar.")
    falha_anterior = False

    while True:
        try:
            if falha_anterior:
                logging.info("✅ Conexão com o Telegram restabelecida. Bot rodando.")

            app.run_polling()
            break
        except (httpx.ConnectError, httpx.TimeoutException, telegram.error.NetworkError):
            logging.warning(
                "\033[91m❌ ERRO DE REDE: Não foi possível conectar ao Telegram. "
                "Verifique sua internet ou configuração de proxy. Tentando novamente em 10 segundos...\033[0m"
            )
            falha_anterior = True
            time.sleep(10)
        except Exception as e:
            logging.warning(f"❌ Erro inesperado no bot: {e}")
            falha_anterior = True
            time.sleep(10)

if __name__ == "__main__":
    main()
