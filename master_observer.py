import os
import sqlite3
from collections import Counter
from datetime import datetime, timezone, timedelta
from config import (
    CAPITAL_REAL,
    MAX_PERDA_DIARIA_PERCENTUAL,
    MAX_PERDAS_CONSECUTIVAS,
    MAX_TRADES_POR_DIA,
)

from storage import DB_NAME


ARQUIVO_DB = DB_NAME


def _db_existe():
    return os.path.exists(ARQUIVO_DB)


def _conectar():
    return sqlite3.connect(ARQUIVO_DB)


def _parse_iso(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        try:
            return datetime.strptime(valor, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None


def _colunas_tabela(conn, tabela):
    cursor = conn.cursor()
    return {row[1] for row in cursor.execute(f"PRAGMA table_info({tabela})").fetchall()}


def _ultima_acao_trades(cursor, colunas_trades):
    if "timestamp" not in colunas_trades:
        return None

    if "motivo_saida" in colunas_trades:
        query = (
            "SELECT timestamp, status, motivo_saida, tipo, simbolo, entrada, saida, lucro_percent "
            "FROM trades ORDER BY timestamp DESC LIMIT 1"
        )
    else:
        query = (
            "SELECT timestamp, status, NULL as motivo_saida, tipo, simbolo, entrada, saida, lucro_percent "
            "FROM trades ORDER BY timestamp DESC LIMIT 1"
        )
    row = cursor.execute(query).fetchone()
    if not row:
        return None

    timestamp_trade, status_trade, motivo_saida, tipo_trade, simbolo_trade, entrada_trade, saida_trade, lucro_percent_trade = row
    decisao_trade = "TRADE_ABERTO" if str(status_trade).lower() in ("open", "aberto") else "TRADE_FECHADO"
    return (
        timestamp_trade,
        decisao_trade,
        motivo_saida or f"Última ação registrada na tabela trades ({tipo_trade or 'N/D'}).",
        "N/A",
        "N/D",
        "N/D",
        None,
        "N/D",
        None,
        simbolo_trade,
        tipo_trade,
    )


def obter_status_geral():
    if not _db_existe():
        return {
            "db_existe": False,
            "bot_vivo": False,
            "ultima_checagem": None,
            "ultima_decisao": None,
            "ultimo_motivo": None,
            "bloqueado_por": None,
            "trades_abertos": 0,
            "trades_fechados_hoje": 0,
            "erros_recentes": [],
            "fonte_dados": None,
            "regime_atual": None,
            "adx_atual": None,
            "volume_status": None,
            "resumo_alerta": "Banco de dados não encontrado. O bot pode não ter iniciado corretamente.",
        }

    try:
        with _conectar() as conn:
            cursor = conn.cursor()
            colunas_logs = _colunas_tabela(conn, "decision_logs")
            colunas_trades = _colunas_tabela(conn, "trades")

            total_logs = cursor.execute("SELECT COUNT(*) FROM decision_logs").fetchone()[0]
            ultimo_log = None
            if total_logs > 0:
                query_ultimo = (
                    "SELECT timestamp, decisao, motivo, bloqueado_por, fonte_dados, regime, adx, volume_status, erro, symbol, modo "
                    "FROM decision_logs ORDER BY timestamp DESC LIMIT 1"
                )
                if "erro" not in colunas_logs:
                    query_ultimo = (
                        "SELECT timestamp, decisao, motivo, bloqueado_por, fonte_dados, regime, adx, volume_status, NULL as erro, symbol, modo "
                        "FROM decision_logs ORDER BY timestamp DESC LIMIT 1"
                    )
                ultimo_log = cursor.execute(query_ultimo).fetchone()
            else:
                ultimo_log = _ultima_acao_trades(cursor, colunas_trades)

            erros_recentes = []
            if total_logs > 0:
                query_erros = (
                    "SELECT timestamp, simbolo, modo, erro, motivo FROM decision_logs "
                    "WHERE decisao = 'ERRO' ORDER BY timestamp DESC LIMIT 3"
                )
                if "erro" not in colunas_logs:
                    query_erros = (
                        "SELECT timestamp, simbolo, modo, motivo FROM decision_logs "
                        "WHERE decisao = 'ERRO' ORDER BY timestamp DESC LIMIT 3"
                    )
                rows_erros = cursor.execute(query_erros).fetchall()
                for row in rows_erros:
                    if len(row) == 5:
                        erros_recentes.append(
                            {
                                "timestamp": row[0],
                                "symbol": row[1],
                                "modo": row[2],
                                "erro": row[3],
                                "motivo": row[4],
                            }
                        )
                    else:
                        erros_recentes.append(
                            {
                                "timestamp": row[0],
                                "symbol": row[1],
                                "modo": row[2],
                                "erro": None,
                                "motivo": row[3],
                            }
                        )

            bot_vivo = False
            if ultimo_log and ultimo_log[0]:
                dt_ultima = _parse_iso(ultimo_log[0])
                if dt_ultima:
                    bot_vivo = (datetime.now(timezone.utc) - dt_ultima) <= timedelta(minutes=5)
            elif total_logs > 0:
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
                log_24h = cursor.execute(
                    "SELECT timestamp FROM decision_logs WHERE timestamp >= ? ORDER BY timestamp DESC LIMIT 1",
                    (cutoff,),
                ).fetchone()
                bot_vivo = bool(log_24h)

            trades_abertos = 0
            trades_fechados_hoje = 0
            if "tipo" in colunas_trades and "status" in colunas_trades:
                trades_abertos = cursor.execute(
                    "SELECT COUNT(*) FROM trades WHERE tipo = 'paper' AND status IN ('open', 'aberto')"
                ).fetchone()[0]
                if "fechado_em" in colunas_trades:
                    hoje = datetime.now(timezone.utc).date().isoformat()
                    trades_fechados_hoje = cursor.execute(
                        "SELECT COUNT(*) FROM trades WHERE tipo = 'paper' AND status IN ('closed', 'fechado') AND date(fechado_em) = ?",
                        (hoje,),
                    ).fetchone()[0]
                else:
                    hoje = datetime.now(timezone.utc).date().isoformat()
                    trades_fechados_hoje = cursor.execute(
                        "SELECT COUNT(*) FROM trades WHERE tipo = 'paper' AND status IN ('closed', 'fechado') AND date(timestamp) = ?",
                        (hoje,),
                    ).fetchone()[0]

            bloqueios = []
            if total_logs > 0:
                rows_bloqueios = cursor.execute(
                    "SELECT bloqueado_por FROM decision_logs WHERE decisao IN ('BLOQUEADO_KILLZONE', 'BLOQUEADO_FILTRO', 'BLOQUEADO_POR_RISCO') "
                    "AND bloqueado_por IS NOT NULL AND bloqueado_por != '' ORDER BY timestamp DESC LIMIT 50"
                ).fetchall()
                bloqueios = [row[0] for row in rows_bloqueios]

        bloqueado_por = Counter(bloqueios).most_common(1)[0][0] if bloqueios else None

        ultima_checagem = ultimo_log[0] if ultimo_log else None
        ultima_decisao = ultimo_log[1] if ultimo_log else None
        ultimo_motivo = ultimo_log[2] if ultimo_log else None
        fonte_dados = ultimo_log[4] if ultimo_log else None
        regime_atual = ultimo_log[5] if ultimo_log else None
        adx_atual = ultimo_log[6] if ultimo_log else None
        volume_status = ultimo_log[7] if ultimo_log else None
        erro_ultimo = ultimo_log[8] if ultimo_log else None

        return {
            "db_existe": True,
            "bot_vivo": bot_vivo,
            "ultima_checagem": ultima_checagem,
            "ultima_decisao": ultima_decisao,
            "ultimo_motivo": ultimo_motivo,
            "bloqueado_por": bloqueado_por,
            "trades_abertos": trades_abertos,
            "trades_fechados_hoje": trades_fechados_hoje,
            "erros_recentes": erros_recentes,
            "fonte_dados": fonte_dados,
            "regime_atual": regime_atual,
            "adx_atual": adx_atual,
            "volume_status": volume_status,
            "erro_ultimo": erro_ultimo,
        }
    except Exception as exc:
        return {
            "db_existe": True,
            "bot_vivo": False,
            "ultima_checagem": None,
            "ultima_decisao": None,
            "ultimo_motivo": None,
            "bloqueado_por": None,
            "trades_abertos": 0,
            "trades_fechados_hoje": 0,
            "erros_recentes": [],
            "fonte_dados": None,
            "regime_atual": None,
            "adx_atual": None,
            "volume_status": None,
            "erro_ultimo": str(exc),
        }


def obter_resumo_risco():
    if not _db_existe():
        return {
            "db_existe": False,
            "capital_atual": None,
            "perdas_hoje": None,
            "trades_hoje": None,
            "perdas_consecutivas": None,
            "exposicao_atual": None,
            "ultimo_bloqueio": None,
            "limite_diario_perda": None,
            "limite_sequencia_perdas": None,
            "limite_trades_dia": None,
        }

    try:
        with _conectar() as conn:
            cursor = conn.cursor()
            colunas_trades = _colunas_tabela(conn, "trades")

            capital_atual = CAPITAL_REAL
            trades_hoje = 0
            perdas_hoje = 0.0
            perdas_consecutivas = 0
            exposicao_atual = 0.0
            ultimo_bloqueio = None

            if "timestamp" in colunas_trades:
                hoje = datetime.now(timezone.utc).date().isoformat()
                trades_hoje = cursor.execute(
                    "SELECT COUNT(*) FROM trades WHERE tipo = 'paper' AND date(timestamp) = ?",
                    (hoje,),
                ).fetchone()[0]

            if "fechado_em" in colunas_trades:
                hoje = datetime.now(timezone.utc).date().isoformat()
                col_saida = "lucro_reais" if "lucro_reais" in colunas_trades else "lucro_percent"
                rows_fechados = cursor.execute(
                    f"SELECT {col_saida}, fechado_em FROM trades WHERE tipo = 'paper' AND status IN ('closed', 'fechado') AND date(fechado_em) = ?",
                    (hoje,),
                ).fetchall()
                for valor, _ in rows_fechados:
                    try:
                        valor_f = float(valor or 0.0)
                    except (TypeError, ValueError):
                        continue
                    if valor_f < 0:
                        perdas_hoje += abs(valor_f)

            order_col = "fechado_em" if "fechado_em" in colunas_trades else "timestamp"
            rows_trades = cursor.execute(
                f"SELECT resultado FROM trades WHERE tipo = 'paper' ORDER BY {order_col} DESC LIMIT 20"
            ).fetchall()
            for (resultado,) in rows_trades:
                if resultado in ("PERDA", "LOSS"):
                    perdas_consecutivas += 1
                else:
                    break

            if {"quantidade", "entrada", "valor_nocional"}.intersection(colunas_trades):
                rows_abertos = cursor.execute(
                    "SELECT * FROM trades WHERE tipo = 'paper' AND status IN ('open', 'aberto')"
                ).fetchall()
                if rows_abertos:
                    idx = {desc[0]: i for i, desc in enumerate(cursor.description or [])}
                    for row in rows_abertos:
                        try:
                            if "valor_nocional" in idx:
                                exposicao_atual += float(row[idx["valor_nocional"]] or 0.0)
                            elif "quantidade" in idx and "entrada" in idx:
                                exposicao_atual += float(row[idx["quantidade"]] or 0.0) * float(row[idx["entrada"]] or 0.0)
                        except (TypeError, ValueError, ZeroDivisionError):
                            continue

            rows_bloqueio = cursor.execute(
                "SELECT timestamp, motivo, bloqueado_por, symbol, modo "
                "FROM decision_logs "
                "WHERE decisao = 'BLOQUEADO_POR_RISCO' OR bloqueado_por IN ('RISK', 'RISK_MANAGER') "
                "ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            if rows_bloqueio:
                dt = _parse_iso(rows_bloqueio[0])
                minutos = int((datetime.now(timezone.utc) - dt).total_seconds() // 60) if dt else None
                ultimo_bloqueio = {
                    "timestamp": rows_bloqueio[0],
                    "motivo": rows_bloqueio[1],
                    "bloqueado_por": rows_bloqueio[2],
                    "symbol": rows_bloqueio[3],
                    "modo": rows_bloqueio[4],
                    "minutos_ago": minutos,
                }

            return {
                "db_existe": True,
                "capital_atual": capital_atual,
                "perdas_hoje": perdas_hoje,
                "trades_hoje": trades_hoje,
                "perdas_consecutivas": perdas_consecutivas,
                "exposicao_atual": exposicao_atual,
                "ultimo_bloqueio": ultimo_bloqueio,
                "limite_diario_perda": capital_atual * 0.02,
                "limite_sequencia_perdas": 3,
                "limite_trades_dia": 5,
            }
    except Exception as exc:
        return {
            "db_existe": True,
                "capital_atual": CAPITAL_REAL,
            "perdas_hoje": None,
            "trades_hoje": None,
            "perdas_consecutivas": None,
            "exposicao_atual": None,
            "ultimo_bloqueio": None,
                "limite_diario_perda": CAPITAL_REAL * (MAX_PERDA_DIARIA_PERCENTUAL / 100),
                "limite_sequencia_perdas": MAX_PERDAS_CONSECUTIVAS,
                "limite_trades_dia": MAX_TRADES_POR_DIA,
            "erro": str(exc),
        }


def _analise_em_linguagem_natural(status):
    if not status.get("db_existe"):
        return "Banco de dados não encontrado. O bot pode não ter iniciado corretamente."

    if status.get("ultima_checagem") is None:
        return "Ainda não há dados suficientes. O bot está rodando, mas aguardando a primeira decisão."

    partes = []
    if status.get("bloqueado_por") in {"KILLZONE", "ADX", "RSI", "RISK", "CHOP", "ESTRUTURA"}:
        if status["bloqueado_por"] == "KILLZONE":
            partes.append("O bot está vivo, mas bloqueando sinais fora da Killzone.")
        elif status["bloqueado_por"] == "CHOP":
            partes.append("O mercado está lateral e o bot está corretamente se protegendo.")
        elif status["bloqueado_por"] == "ADX":
            partes.append("O ADX está fraco, então o bot evita operar em mercado sem força.")
        elif status["bloqueado_por"] == "RSI":
            partes.append("O RSI está avisando timing ruim e o bot está aguardando melhor momento.")
        elif status["bloqueado_por"] == "RISK":
            partes.append("A gestão de risco bloqueou novas entradas para proteger o capital.")
        else:
            partes.append("A estrutura de preço não confirmou a entrada e o bot permaneceu cauteloso.")
    elif status.get("ultima_decisao") in {"AGUARDAR", "AGUARDAR (MERCADO LATERAL)", "AGUARDAR (TIMING RUIM)"}:
        partes.append("O bot está vivo e aguardando um cenário mais claro antes de operar.")
    elif status.get("ultima_decisao") == "TRADE_ABERTO":
        partes.append("Há trade aberto e o bot está acompanhando a posição normalmente.")
    elif status.get("ultima_decisao") == "TRADE_FECHADO":
        partes.append("O bot operou recentemente e já registrou o fechamento do trade.")
    else:
        partes.append("O bot está ativo e seguindo seus filtros normais de decisão.")

    if status.get("erros_recentes"):
        partes.append("Houve erros recentes, mas o sistema ainda segue respondendo.")

    if status.get("trades_abertos", 0) > 0:
        partes.append(f"Existem {status['trades_abertos']} trades abertos sob monitoramento.")

    return " ".join(partes)


def _resumo_paper(status):
    if status.get("trades_abertos", 0) > 0:
        return "O paper trading está ativo com posições em acompanhamento."

    if status.get("erros_recentes"):
        return "O paper trading parece estável, mas com alguns erros recentes que merecem atenção."

    return "O paper trading parece saudável, sem posições abertas no momento e com comportamento consistente."


def gerar_resumo_mestre():
    status = obter_status_geral()
    risco = obter_resumo_risco()

    if not status.get("db_existe"):
        return "Banco de dados não encontrado. O bot pode não ter iniciado corretamente."

    if status.get("ultima_checagem") is None:
        return "Ainda não há dados suficientes. O bot está rodando, mas aguardando a primeira decisão."

    erros = status.get("erros_recentes") or []
    erros_texto = "Nenhum" if not erros else "; ".join(
        f"{item.get('timestamp', 'N/D')} - {item.get('modo', 'N/D')} - {item.get('erro') or item.get('motivo') or 'N/D'}"
        for item in erros
    )

    status_geral = "✅ Bot está VIVO" if status.get("bot_vivo") else "⚠️ Bot sem atividade recente"
    ultima_checagem = status.get("ultima_checagem") or "N/D"
    ultima_decisao = status.get("ultima_decisao") or "N/D"
    ultimo_motivo = status.get("ultimo_motivo") or "N/D"
    bloqueado_por = status.get("bloqueado_por") or "N/D"
    trades_abertos = status.get("trades_abertos", 0)
    trades_fechados_hoje = status.get("trades_fechados_hoje", 0)
    fonte_dados = status.get("fonte_dados") or "N/D"
    regime_atual = status.get("regime_atual") or "N/D"
    volume_status = status.get("volume_status") or "N/D"
    adx_atual = status.get("adx_atual")
    adx_texto = f"{adx_atual}" if adx_atual is not None else "N/D"

    capital_atual = risco.get("capital_atual")
    perdas_hoje = risco.get("perdas_hoje")
    trades_hoje = risco.get("trades_hoje")
    perdas_consecutivas = risco.get("perdas_consecutivas")
    exposicao_atual = risco.get("exposicao_atual")
    limite_diario_perda = risco.get("limite_diario_perda")
    limite_sequencia_perdas = risco.get("limite_sequencia_perdas")
    limite_trades_dia = risco.get("limite_trades_dia")
    ultimo_bloqueio = risco.get("ultimo_bloqueio")

    if capital_atual is not None:
        exposicao_pct = (exposicao_atual / capital_atual) * 100 if exposicao_atual is not None else None
        capital_texto = f"R$ {capital_atual:,.2f}"
        exposicao_texto = f"R$ {exposicao_atual:,.2f}" if exposicao_atual is not None else "N/D"
        exposicao_pct_texto = f"{exposicao_pct:.2f}%" if exposicao_pct is not None else "N/D"
    else:
        capital_texto = "N/D"
        exposicao_texto = "N/D"
        exposicao_pct_texto = "N/D"

    perdas_hoje_texto = f"R$ {perdas_hoje:,.2f}" if perdas_hoje is not None else "N/D"
    trades_hoje_texto = str(trades_hoje) if trades_hoje is not None else "N/D"
    perdas_consecutivas_texto = str(perdas_consecutivas) if perdas_consecutivas is not None else "N/D"
    limite_diario_texto = f"R$ {limite_diario_perda:,.2f}" if limite_diario_perda is not None else "N/D"
    limite_seq_texto = str(limite_sequencia_perdas) if limite_sequencia_perdas is not None else "N/D"
    limite_trades_texto = str(limite_trades_dia) if limite_trades_dia is not None else "N/D"

    if ultimo_bloqueio:
        motivo_bloqueio = ultimo_bloqueio.get("motivo") or "N/D"
        minutos_ago = ultimo_bloqueio.get("minutos_ago")
        tempo_bloqueio = f"há {minutos_ago} min" if minutos_ago is not None else "horário indisponível"
        ultimo_bloqueio_texto = f"\"{motivo_bloqueio}\" ({tempo_bloqueio})"
    else:
        ultimo_bloqueio_texto = "Nenhum"

    analise = _analise_em_linguagem_natural(status)
    paper = _resumo_paper(status)

    return (
        "📡 **Status Geral do Bot**\n"
        f"{status_geral} (última checagem: {ultima_checagem})\n"
        f"📊 Última decisão: {ultima_decisao}\n"
        f"📌 Motivo: {ultimo_motivo}\n"
        f"🔍 Filtro mais ativo: {bloqueado_por}\n"
        f"📂 Trades abertos: {trades_abertos}\n"
        f"📉 Trades fechados hoje: {trades_fechados_hoje}\n"
        f"⚠️ Erros recentes: {erros_texto}\n"
        f"📈 Fonte de dados: {fonte_dados}\n"
        f"🧭 Regime atual: {regime_atual}\n"
        f"📊 ADX atual: {adx_texto}\n"
        f"📦 Volume: {volume_status}\n"
        "🛡️ **Resumo de Risco**\n"
        f"- Capital: {capital_texto}\n"
        f"- Exposição atual: {exposicao_texto} ({exposicao_pct_texto})\n"
        f"- Perdas hoje: {perdas_hoje_texto}\n"
        f"- Trades hoje: {trades_hoje_texto}\n"
        f"- Sequência de perdas: {perdas_consecutivas_texto}\n"
        f"- Limite diário de perda: {limite_diario_texto}\n"
        f"- Limite de sequência de perdas: {limite_seq_texto}\n"
        f"- Limite de trades/dia: {limite_trades_texto}\n"
        f"- Último bloqueio: {ultimo_bloqueio_texto}\n"
        f"🧠 Análise da IA Mestre:\n{analise}\n"
        f"🪙 Paper trading: {paper}"
    )
