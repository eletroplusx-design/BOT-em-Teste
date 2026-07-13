import logging
from datetime import datetime, timezone
from decimal import Decimal

from config import (
    CAPITAL_PAPER,
    FVG_JANELA,
    PAPER_TRADING_ATIVO,
    RR_MINIMO,
    STRATEGY_VERSION,
    VOLUME_MINIMO,
    KILLZONE_SOL,
    can_execute_sensitive_telegram_action,
)
from decisor import (
    tomar_decisao,
    extrair_fvg_bearish_acima,
    extrair_fvg_bullish_abaixo,
)
from regime_classifier import classificar_regime
from domain import (
    DomainValidationError,
    legacy_signal_payload,
    signal_from_legacy_mapping,
    trade_intent_from_legacy_mapping,
    trade_result_from_legacy_mapping,
)
from storage import (
    buscar_ultimo_decision_log,
    finalizar_trade_paper,
    log_decisao,
    obter_trades_paper_abertos,
    registrar_trade_paper,
)

try:
    from risk_manager import calcular_tamanho_posicao
except Exception:  # pragma: no cover - fallback defensivo
    calcular_tamanho_posicao = None

try:
    import backtester
except Exception:  # pragma: no cover - fallback defensivo
    backtester = None

try:
    from paper_runtime import (
        PaperRuntimeSessionError,
        build_snapshot_from_observed_state,
        evaluate_monitored_session,
        get_monitored_session,
    )
except Exception:  # pragma: no cover - fallback defensivo
    PaperRuntimeSessionError = Exception
    get_monitored_session = None
    build_snapshot_from_observed_state = None
    evaluate_monitored_session = None


PAPER_SYMBOL = "SOLUSDT"
PAPER_JOB_NAME = "paper_sol"
PAPER_CONFIG = {
    "regime_modo": "bull_bear",
    "volume_minimo_multiplicador": VOLUME_MINIMO,
    "exigir_fvg_nao_tocado": False,
    "lookback_fvg": FVG_JANELA,
    "exigir_rr_minimo": False,
}

ULTIMO_PRECO_CACHE = {}
ULTIMO_LOG_CACHE = {}


def _construir_trade_intent_paper(sinal, quantidade, valor_arriscado, fonte_dados):
    return trade_intent_from_legacy_mapping(
        {
            "symbol": PAPER_SYMBOL,
            "direction": sinal.get("direcao"),
            "entry": sinal.get("entrada"),
            "stop_loss": sinal.get("stop_loss"),
            "take_profit": sinal.get("take_profit"),
            "quantity": quantidade,
            "risk_amount": valor_arriscado,
            "paper": True,
            "created_at": datetime.now(timezone.utc),
            "source": fonte_dados,
            "strategy_version": STRATEGY_VERSION,
        }
    )


def _construir_trade_result_paper(trade, saida, lucro_percent, lucro_reais, fonte_dados, motivo_saida):
    return trade_result_from_legacy_mapping(
        {
            "symbol": PAPER_SYMBOL,
            "direction": trade["direcao"],
            "entry": trade["entrada"],
            "exit_price": saida,
            "quantity": trade["quantidade"],
            "pnl_percent": lucro_percent,
            "pnl_reais": lucro_reais,
            "status": "closed",
            "reason": motivo_saida,
            "opened_at": trade.get("aberto_em") or trade.get("timestamp") or datetime.now(timezone.utc),
            "closed_at": datetime.now(timezone.utc),
            "source": fonte_dados,
            "paper": True,
            "strategy_version": STRATEGY_VERSION,
        }
    )


def fmt_num(val, formato=".2f"):
    if val is None:
        return "N/A"
    try:
        return f"{val:{formato}}"
    except (TypeError, ValueError):
        return "N/A"


def atualizar_cache_preco(symbol, preco, fonte_dados, modo):
    if preco is None:
        return
    ULTIMO_PRECO_CACHE[symbol] = {
        "preco": float(preco),
        "fonte_dados": fonte_dados or "N/D",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "modo": modo,
    }


def atualizar_cache_log(log):
    if not log:
        return
    modo = log.get("modo") or "N/D"
    symbol = log.get("symbol") or "N/D"
    ULTIMO_LOG_CACHE[modo] = log
    ULTIMO_LOG_CACHE[symbol] = log


def obter_fonte_dados_df(df):
    if df is None or getattr(df, "empty", True):
        return "N/D"
    return getattr(df, "attrs", {}).get("fonte_dados") or "BINANCE"


def registrar_decisao_observabilidade(**kwargs):
    payload = dict(kwargs)
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    payload.setdefault("strategy_version", STRATEGY_VERSION)
    try:
        log_decisao(**payload)
        atualizar_cache_log(payload)
    except Exception as exc:
        logging.warning(f"Falha ao registrar decisao observabilidade: {exc}")


def esta_em_killzone():
    agora = datetime.now(timezone.utc)
    minutos_utc = agora.hour * 60 + agora.minute
    return (7 * 60 <= minutos_utc < 10 * 60) or (13 * 60 <= minutos_utc < 16 * 60)


def _obter_sinal_paper_sol():
    if backtester is None:
        return None
    try:
        df = backtester.baixar_dados_historicos(symbol=PAPER_SYMBOL)
        if df is None or df.empty:
            return None
        try:
            contextos = backtester._precomputar_contextos_otimizacao(df)
        except Exception as exc:
            logging.warning(f"Falha ao precomputar contextos do paper SOL: {exc}")
            return None
        if not contextos:
            return None
        contexto = contextos[-1]
        sinal = backtester._simular_decisao_contexto(
            contexto,
            volume_minimo_multiplicador=PAPER_CONFIG["volume_minimo_multiplicador"],
            volume_alto_multiplicador=1.5,
            exigir_rr_minimo=PAPER_CONFIG["exigir_rr_minimo"],
            regime_modo=PAPER_CONFIG["regime_modo"],
            exigir_fvg_nao_tocado=PAPER_CONFIG["exigir_fvg_nao_tocado"],
            lookback_fvg=PAPER_CONFIG["lookback_fvg"] or 10,
        )
        if not sinal:
            return None
        try:
            sinal_model = signal_from_legacy_mapping(sinal, default_symbol=PAPER_SYMBOL)
            payload = legacy_signal_payload(sinal_model)
            payload.setdefault("motivo", payload.get("reason"))
            return payload
        except DomainValidationError as exc:
            logging.warning(f"Falha ao validar sinal paper SOL: {exc}")
            return None
        except Exception as exc:
            logging.warning(f"Falha ao validar sinal paper SOL: {exc}")
            return None
    except Exception as exc:
        logging.warning(f"Falha ao gerar sinal paper SOL: {exc}")
        return None


def _avaliar_filtros_paper(sinal, decisao_info, regime_info):
    killzone_ok = (not KILLZONE_SOL) or esta_em_killzone()
    adx = regime_info.get("adx")
    rsi = decisao_info.get("rsi")
    direcao = sinal.get("direcao")
    adx_ok = adx is not None and adx >= 20
    if direcao == "COMPRA":
        rsi_ok = rsi is not None and rsi <= 55
    else:
        rsi_ok = rsi is not None and rsi >= 45
    filtros_aplicados = killzone_ok and adx_ok and rsi_ok
    return filtros_aplicados, {"killzone_ok": killzone_ok, "adx_ok": adx_ok, "rsi_ok": rsi_ok}


def _obter_runtime_session_do_job(job_data):
    if get_monitored_session is None:
        return None
    if not job_data:
        return None
    session_id = job_data.get("session_id")
    if not session_id:
        return None
    try:
        return get_monitored_session(session_id=session_id)
    except Exception as exc:
        logging.warning(f"Sessao paper monitorada indisponivel: {exc}")
        return None


async def monitorar_paper_sol(context):
    if not PAPER_TRADING_ATIVO:
        return

    try:
        job_data = getattr(context.job, "data", {}) or {}
        chat_id = job_data.get("chat_id")
        user_id = job_data.get("user_id")
        chat_type = job_data.get("chat_type")
        if not can_execute_sensitive_telegram_action(user_id, chat_id, chat_type):
            logging.warning("Monitoramento paper SOL bloqueado por autorizacao.")
            return
        runtime_session = _obter_runtime_session_do_job(job_data)
        if job_data.get("session_id") and runtime_session is None:
            registrar_decisao_observabilidade(
                symbol=PAPER_SYMBOL,
                modo="PAPER_SOL",
                decisao="ERRO",
                direcao="N/A",
                preco=None,
                regime="N/D",
                adx=None,
                volume_status="N/D",
                motivo="Sessao paper monitorada indisponivel.",
                bloqueado_por="SESSION",
                fonte_dados="N/D",
                erro="sessao monitora ausente",
            )
            return
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
                motivo="Backtester indisponivel para o paper trading.",
                bloqueado_por="N/A",
                fonte_dados="N/D",
                erro="backtester indisponivel",
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
        atualizar_cache_preco(PAPER_SYMBOL, preco_atual, fonte_dados, "PAPER_SOL")
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

                if direcao == "COMPRA":
                    stop_atingido = float(candle["low"]) <= stop_loss
                    take_atingido = float(candle["high"]) >= take_profit
                    if stop_atingido:
                        saida = stop_loss
                        lucro_reais = quantidade * (saida - entrada)
                        lucro_percent = (lucro_reais / CAPITAL_PAPER) * 100
                        resultado_trade = _construir_trade_result_paper(
                            trade,
                            saida,
                            lucro_percent,
                            lucro_reais,
                            fonte_dados,
                            "STOP",
                        )
                        finalizar_trade_paper(
                            trade["id"],
                            float(resultado_trade.exit_price),
                            float(resultado_trade.pnl_percent),
                            float(resultado_trade.pnl_reais),
                            resultado_trade.resultado,
                            resultado_trade.reason,
                        )
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
                            text=f"Paper SOL fechado por STOP. Resultado: {fmt_num(lucro_percent, '+.2f')}%",
                        )
                        continue
                    if take_atingido:
                        saida = take_profit
                        lucro_reais = quantidade * (saida - entrada)
                        lucro_percent = (lucro_reais / CAPITAL_PAPER) * 100
                        resultado_trade = _construir_trade_result_paper(
                            trade,
                            saida,
                            lucro_percent,
                            lucro_reais,
                            fonte_dados,
                            "TAKE_PROFIT",
                        )
                        finalizar_trade_paper(
                            trade["id"],
                            float(resultado_trade.exit_price),
                            float(resultado_trade.pnl_percent),
                            float(resultado_trade.pnl_reais),
                            resultado_trade.resultado,
                            resultado_trade.reason,
                        )
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
                            text=f"Paper SOL fechado por TAKE PROFIT. Resultado: {fmt_num(lucro_percent, '+.2f')}%",
                        )
                        continue
                else:
                    stop_atingido = float(candle["high"]) >= stop_loss
                    take_atingido = float(candle["low"]) <= take_profit
                    if stop_atingido:
                        saida = stop_loss
                        lucro_reais = quantidade * (entrada - saida)
                        lucro_percent = (lucro_reais / CAPITAL_PAPER) * 100
                        resultado_trade = _construir_trade_result_paper(
                            trade,
                            saida,
                            lucro_percent,
                            lucro_reais,
                            fonte_dados,
                            "STOP",
                        )
                        finalizar_trade_paper(
                            trade["id"],
                            float(resultado_trade.exit_price),
                            float(resultado_trade.pnl_percent),
                            float(resultado_trade.pnl_reais),
                            resultado_trade.resultado,
                            resultado_trade.reason,
                        )
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
                            text=f"Paper SOL fechado por STOP. Resultado: {fmt_num(lucro_percent, '+.2f')}%",
                        )
                        continue
                    if take_atingido:
                        saida = take_profit
                        lucro_reais = quantidade * (entrada - saida)
                        lucro_percent = (lucro_reais / CAPITAL_PAPER) * 100
                        resultado_trade = _construir_trade_result_paper(
                            trade,
                            saida,
                            lucro_percent,
                            lucro_reais,
                            fonte_dados,
                            "TAKE_PROFIT",
                        )
                        finalizar_trade_paper(
                            trade["id"],
                            float(resultado_trade.exit_price),
                            float(resultado_trade.pnl_percent),
                            float(resultado_trade.pnl_reais),
                            resultado_trade.resultado,
                            resultado_trade.reason,
                        )
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
                            text=f"Paper SOL fechado por TAKE PROFIT. Resultado: {fmt_num(lucro_percent, '+.2f')}%",
                        )
                        continue
            return

        if runtime_session is not None and build_snapshot_from_observed_state is not None and evaluate_monitored_session is not None:
            runtime_decision = runtime_session.decision
            if runtime_decision is None:
                registrar_decisao_observabilidade(
                    symbol=PAPER_SYMBOL,
                    modo="PAPER_SOL",
                    decisao="ERRO",
                    direcao="N/A",
                    preco=preco_atual,
                    regime=regime_info.get("regime"),
                    adx=regime_info.get("adx"),
                    volume_status=regime_info.get("volatilidade"),
                    motivo="Sessao runtime sem decisao monitoravel.",
                    bloqueado_por="SESSION",
                    fonte_dados=fonte_dados,
                    erro="runtime decision ausente",
                )
                return
            runtime_observed = {
                "data_fresh": True,
                "session_drawdown_percent": Decimal("0"),
                "current_loss_streak": 0,
                "open_positions": len(aberto),
                "executed_trades": len(aberto),
                "observed_costs": {
                    "entry_fee_rate": "0.0004",
                    "exit_fee_rate": "0.0004",
                    "spread_bps": "5",
                    "slippage_bps": "5",
                },
                "session_state": runtime_session.record.state.value,
                "paper_capital_used": Decimal(str(CAPITAL_PAPER)),
                "risk_per_trade_percent": Decimal("1.0"),
                "internal_error": None,
                "attempted_live": False,
            }
            try:
                runtime_snapshot = build_snapshot_from_observed_state(
                    session=runtime_session.record,
                    decision=runtime_decision,
                    observed=runtime_observed,
                    timestamp_utc=datetime.now(timezone.utc),
                )
                runtime_result = runtime_session.evaluate_snapshot(
                    runtime_snapshot,
                    decision=runtime_decision,
                )
                if not runtime_result.approved:
                    registrar_decisao_observabilidade(
                        symbol=PAPER_SYMBOL,
                        modo="PAPER_SOL",
                        decisao="PAPER_SUSPENDED",
                        direcao="N/A",
                        preco=preco_atual,
                        regime=regime_info.get("regime"),
                        adx=regime_info.get("adx"),
                        volume_status=regime_info.get("volatilidade"),
                        motivo="Sessao paper monitorada suspensa.",
                        bloqueado_por="SESSION",
                        fonte_dados=fonte_dados,
                        erro="N/A",
                    )
                    logging.warning("Sessao paper monitorada suspensa; novas ordens bloqueadas.")
                    return
            except Exception as exc:
                registrar_decisao_observabilidade(
                    symbol=PAPER_SYMBOL,
                    modo="PAPER_SOL",
                    decisao="ERRO",
                    direcao="N/A",
                    preco=preco_atual,
                    regime=regime_info.get("regime"),
                    adx=regime_info.get("adx"),
                    volume_status=regime_info.get("volatilidade"),
                    motivo="Falha ao revalidar a sessao paper monitorada.",
                    bloqueado_por="SESSION",
                    fonte_dados=fonte_dados,
                    erro=str(exc),
                )
                logging.warning(f"Falha ao revalidar sessao paper monitorada: {exc}")
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
                motivo="Sem sinal valido no momento.",
                bloqueado_por="N/A",
                fonte_dados=fonte_dados,
                erro="N/A",
            )
            return

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
            logging.info("Alerta bloqueado: fora da Killzone.")
            return

        decisao_info = tomar_decisao(df, symbol=PAPER_SYMBOL, modo="PAPER_SOL", fonte_dados=fonte_dados)
        filtros_aplicados, detalhes_filtros = _avaliar_filtros_paper(sinal, decisao_info, regime_info)

        entrada = float(sinal["entrada"])
        stop_loss = float(sinal["stop_loss"])
        take_profit = float(sinal["take_profit"])
        rr_planejado = float(sinal.get("rr") or 0.0)
        rr_real = abs(take_profit - entrada) / abs(entrada - stop_loss) if abs(entrada - stop_loss) > 0 else 0.0
        if rr_real < 1.5:
            logging.info(f"Trade bloqueado pelo risk manager: R/R muito baixo ({rr_real:.2f})")
            registrar_decisao_observabilidade(
                symbol=PAPER_SYMBOL,
                modo="PAPER_SOL",
                decisao="BLOQUEADO_FILTRO",
                direcao=sinal.get("direcao"),
                preco=entrada,
                regime=regime_info.get("regime"),
                adx=regime_info.get("adx"),
                volume_status=decisao_info.get("volume_status"),
                motivo=f"Trade bloqueado pelo risk manager: R/R muito baixo ({rr_real:.2f})",
                bloqueado_por="RISK",
                fonte_dados=fonte_dados,
                erro="N/A",
            )
            return

        capital_teste = CAPITAL_PAPER
        if calcular_tamanho_posicao is None:
            registrar_decisao_observabilidade(
                symbol=PAPER_SYMBOL,
                modo="PAPER_SOL",
                decisao="ERRO",
                direcao=sinal.get("direcao"),
                preco=entrada,
                regime=regime_info.get("regime"),
                adx=regime_info.get("adx"),
                volume_status=decisao_info.get("volume_status"),
                motivo="Risk manager indisponivel.",
                bloqueado_por="RISK",
                fonte_dados=fonte_dados,
                erro="calcular_tamanho_posicao indisponivel",
            )
            return

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
                motivo="Tamanho de posicao invalido.",
                bloqueado_por="RISK",
                fonte_dados=fonte_dados,
                erro="N/A",
            )
            return

        trade_intent = _construir_trade_intent_paper(sinal, quantidade, valor_arriscado, fonte_dados)
        trade_id = registrar_trade_paper(
            trade_intent.symbol,
            trade_intent.direction.value,
            float(trade_intent.entry),
            float(trade_intent.stop_loss),
            float(trade_intent.take_profit),
            float(trade_intent.quantity),
            float(trade_intent.risk_amount),
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
                    f"Paper SOL aberto\n"
                    f"Direcao: {sinal['direcao']}\n"
                    f"Entrada: {fmt_num(entrada, ',.4f')}\n"
                    f"Stop: {fmt_num(stop_loss, ',.4f')}\n"
                    f"Take: {fmt_num(take_profit, ',.4f')}\n"
                    f"R/R: {fmt_num(rr_planejado)}\n"
                    f"Trade ID: {trade_id}"
                ),
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
    except Exception as exc:
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
            erro=str(exc),
        )
        logging.warning(f"Erro no monitoramento paper SOL: {exc}")
