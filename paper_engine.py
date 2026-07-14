import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

from config import (
    CAPITAL_PAPER,
    FVG_JANELA,
    PAPER_MONITORED_RUNTIME_REQUIRED,
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
    obter_outbox_paper_pendentes,
    log_decisao,
    obter_trades_paper_abertos,
    registrar_paper_trade_outbox,
    registrar_trade_paper,
    atualizar_outbox_paper_trade,
)
from paper_runtime.audit import sha256_hex

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
        PaperRuntimeEventType,
        build_snapshot_from_observed_state,
        evaluate_monitored_session,
        get_monitored_session,
    )
except Exception:  # pragma: no cover - fallback defensivo
    PaperRuntimeSessionError = Exception
    get_monitored_session = None
    build_snapshot_from_observed_state = None
    evaluate_monitored_session = None
    PAPER_RUNTIME_AVAILABLE = False
else:
    PAPER_RUNTIME_AVAILABLE = True


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


def _paper_runtime_close_timestamp(df):
    if df is None or getattr(df, "empty", True):
        return datetime.now(timezone.utc)
    for coluna in ("close_time", "timestamp", "open_time"):
        if coluna not in getattr(df, "columns", ()):
            continue
        valor = df[coluna].iloc[-1]
        if hasattr(valor, "to_pydatetime"):
            valor = valor.to_pydatetime()
        if isinstance(valor, datetime):
            if valor.tzinfo is None:
                return valor.replace(tzinfo=timezone.utc)
            return valor.astimezone(timezone.utc)
        try:
            texto = str(valor)
            if texto.endswith("Z"):
                texto = texto.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(texto)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            continue
    return datetime.now(timezone.utc)


def _paper_runtime_idempotency_key(session_id: str | None, close_time: datetime, operation: str, identity: str) -> str:
    session_part = session_id or "global"
    return f"paper-runtime:{session_part}:{close_time.astimezone(timezone.utc).isoformat()}:{operation}:{identity}"


def _paper_costs_from_contract(runtime_session) -> dict[str, Decimal]:
    contract = getattr(runtime_session, "contract", None)
    execution_contract = getattr(contract, "execution_contract", {}) if contract is not None else {}
    return {
        "entry_fee_rate": Decimal(str(execution_contract.get("entry_fee_rate", "0.0004"))),
        "exit_fee_rate": Decimal(str(execution_contract.get("exit_fee_rate", "0.0004"))),
        "spread_bps": Decimal(str(execution_contract.get("spread_bps", "5"))),
        "slippage_bps": Decimal(str(execution_contract.get("slippage_bps", "5"))),
    }


def _paper_trade_costs(
    direcao: str,
    entrada: float,
    saida: float,
    quantidade: float,
    costs: dict[str, Decimal],
    *,
    include_exit_costs: bool = True,
) -> dict[str, Decimal]:
    entrada_dec = Decimal(str(entrada))
    saida_dec = Decimal(str(saida))
    quantidade_dec = Decimal(str(quantidade))
    spread_rate = costs["spread_bps"] / Decimal("10000")
    slippage_rate = costs["slippage_bps"] / Decimal("10000")
    entry_spread = entrada_dec * spread_rate
    entry_slippage = entrada_dec * slippage_rate
    exit_spread = saida_dec * spread_rate if include_exit_costs else Decimal("0")
    exit_slippage = saida_dec * slippage_rate if include_exit_costs else Decimal("0")
    if direcao == "COMPRA":
        entry_fill = entrada_dec + entry_spread + entry_slippage
        exit_fill = saida_dec - exit_spread - exit_slippage
        pnl_bruto = quantidade_dec * (saida_dec - entrada_dec)
    else:
        entry_fill = entrada_dec - entry_spread - entry_slippage
        exit_fill = saida_dec + exit_spread + exit_slippage
        pnl_bruto = quantidade_dec * (entrada_dec - saida_dec)
    entry_fee = abs(quantidade_dec * entry_fill * costs["entry_fee_rate"])
    exit_fee = abs(quantidade_dec * exit_fill * costs["exit_fee_rate"]) if include_exit_costs else Decimal("0")
    entry_spread_cost = abs(quantidade_dec * entry_spread)
    exit_spread_cost = abs(quantidade_dec * exit_spread)
    entry_slippage_cost = abs(quantidade_dec * entry_slippage)
    exit_slippage_cost = abs(quantidade_dec * exit_slippage)
    spread_cost = entry_spread_cost + exit_spread_cost
    slippage_cost = entry_slippage_cost + exit_slippage_cost
    custos_totais = entry_fee + exit_fee + spread_cost + slippage_cost
    pnl_liquido = pnl_bruto - custos_totais
    return {
        "preco_base": entrada_dec,
        "fill_price": entry_fill,
        "exit_fill_price": exit_fill,
        "entry_fee": entry_fee,
        "exit_fee": exit_fee,
        "entry_spread_cost": entry_spread_cost,
        "exit_spread_cost": exit_spread_cost,
        "entry_slippage_cost": entry_slippage_cost,
        "exit_slippage_cost": exit_slippage_cost,
        "spread_cost": spread_cost,
        "slippage_cost": slippage_cost,
        "pnl_bruto": pnl_bruto,
        "custos_totais": custos_totais,
        "pnl_liquido": pnl_liquido,
    }


def _trade_order_timestamp_key(trade: dict) -> datetime:
    for chave in ("fechado_em", "saida_em", "timestamp", "aberto_em"):
        valor = trade.get(chave)
        if valor is None:
            continue
        if isinstance(valor, datetime):
            return valor if valor.tzinfo is not None else valor.replace(tzinfo=timezone.utc)
        try:
            texto = str(valor)
            if texto.endswith("Z"):
                texto = texto.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(texto)
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return datetime.min.replace(tzinfo=timezone.utc)


def _registrar_trade_runtime_event(runtime_session, *, payload, result: str, idempotency_key: str, event_type=PaperRuntimeEventType.TRADE_RECORDED) -> None:
    if runtime_session is None:
        return
    try:
        runtime_session.record_trade_event(
            payload=payload,
            result=result,
            event_type=event_type,
            idempotency_key=idempotency_key,
        )
        runtime_session.reload()
    except Exception as exc:
        logging.warning(f"Falha ao registrar evento {event_type.value}: {exc.__class__.__name__}")
        raise PaperRuntimeSessionError("audit event registration failed.") from exc


def _paper_runtime_outbox_request_hash(payload: dict) -> str:
    return sha256_hex({"kind": "paper_runtime_outbox", "payload": payload})


def _paper_runtime_operation_identity(
    *,
    session_id: str | None,
    candle_close_time: datetime,
    symbol: str,
    operation: str,
    direcao: str,
    signal_identity: str,
) -> str:
    return _paper_runtime_idempotency_key(
        session_id,
        candle_close_time,
        operation,
        f"{symbol}:{direcao}:{signal_identity}",
    )


def _paper_runtime_signal_identity(sinal: dict, *, regime_info: dict, decisao_info: dict, candle_close_time: datetime) -> str:
    payload = {
        "candle_close_time": candle_close_time.astimezone(timezone.utc).isoformat(),
        "direcao": sinal.get("direcao"),
        "entrada": sinal.get("entrada"),
        "stop_loss": sinal.get("stop_loss"),
        "take_profit": sinal.get("take_profit"),
        "rr": sinal.get("rr"),
        "motivo": sinal.get("motivo"),
        "regime": regime_info.get("regime"),
        "adx": regime_info.get("adx"),
        "volatilidade": regime_info.get("volatilidade"),
        "volume_status": decisao_info.get("volume_status"),
    }
    return sha256_hex({"kind": "paper_signal_identity", "payload": payload})


def _paper_runtime_outbox_payload(
    *,
    operation_type: str,
    trade_id: int,
    session_id: str | None,
    candle_close_time: datetime,
    idempotency_key: str,
    runtime_events: list[dict],
    snapshot_context: dict,
    telegram_text: str,
    telegram_chat_id: int | None,
) -> dict:
    payload = {
        "operation_type": operation_type,
        "trade_id": trade_id,
        "session_id": session_id,
        "candle_close_time": candle_close_time.astimezone(timezone.utc).isoformat(),
        "idempotency_key": idempotency_key,
        "snapshot_idempotency_key": f"{idempotency_key}:snapshot",
        "runtime_events": runtime_events,
        "snapshot_context": snapshot_context,
        "telegram": {
            "chat_id": telegram_chat_id,
            "text": telegram_text,
        },
    }
    return payload


def _paper_runtime_outbox_record(payload: dict) -> dict:
    payload_json = json.loads(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    request_hash = _paper_runtime_outbox_request_hash(payload_json)
    event_id = sha256_hex({"kind": "paper_runtime_outbox_event_id", "payload": payload_json})
    return {
        "event_id": event_id,
        "session_id": payload_json["session_id"],
        "trade_id": payload_json["trade_id"],
        "operation_type": payload_json["operation_type"],
        "candle_close_time": payload_json["candle_close_time"],
        "idempotency_key": payload_json["idempotency_key"],
        "request_hash": request_hash,
        "payload_json": json.dumps(payload_json, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        "status": "PENDING",
    }


def _paper_runtime_outbox_validate_record(outbox: dict) -> dict:
    required = {
        "event_id",
        "session_id",
        "trade_id",
        "operation_type",
        "candle_close_time",
        "idempotency_key",
        "request_hash",
        "payload_json",
        "status",
        "attempts",
    }
    missing = sorted(required - set(outbox))
    if missing:
        raise PaperRuntimeSessionError(f"paper outbox missing fields: {', '.join(missing)}")
    if not isinstance(outbox["event_id"], str) or not outbox["event_id"].strip():
        raise PaperRuntimeSessionError("paper outbox event_id is invalid.")
    if not isinstance(outbox["session_id"], str) or not outbox["session_id"].strip():
        raise PaperRuntimeSessionError("paper outbox session_id is invalid.")
    if type(outbox["trade_id"]) is not int or outbox["trade_id"] <= 0:
        raise PaperRuntimeSessionError("paper outbox trade_id is invalid.")
    if not isinstance(outbox["operation_type"], str) or not outbox["operation_type"].strip():
        raise PaperRuntimeSessionError("paper outbox operation_type is invalid.")
    if not isinstance(outbox["candle_close_time"], str) or not outbox["candle_close_time"].strip():
        raise PaperRuntimeSessionError("paper outbox candle_close_time is invalid.")
    if not isinstance(outbox["idempotency_key"], str) or not outbox["idempotency_key"].strip():
        raise PaperRuntimeSessionError("paper outbox idempotency_key is invalid.")
    if not isinstance(outbox["request_hash"], str) or not outbox["request_hash"].strip():
        raise PaperRuntimeSessionError("paper outbox request_hash is invalid.")
    if type(outbox["status"]) is not str or not outbox["status"].strip():
        raise PaperRuntimeSessionError("paper outbox status is invalid.")
    if type(outbox["attempts"]) is not int or outbox["attempts"] < 0:
        raise PaperRuntimeSessionError("paper outbox attempts is invalid.")
    try:
        payload = json.loads(outbox["payload_json"])
    except Exception as exc:
        raise PaperRuntimeSessionError("paper outbox payload_json is invalid.") from exc
    if not isinstance(payload, dict):
        raise PaperRuntimeSessionError("paper outbox payload must be a mapping.")
    allowed_payload = {
        "operation_type",
        "trade_id",
        "session_id",
        "candle_close_time",
        "idempotency_key",
        "snapshot_idempotency_key",
        "runtime_events",
        "snapshot_context",
        "telegram",
    }
    if set(payload) != allowed_payload:
        raise PaperRuntimeSessionError("paper outbox payload schema mismatch.")
    if payload["operation_type"] != outbox["operation_type"] or payload["trade_id"] != outbox["trade_id"]:
        raise PaperRuntimeSessionError("paper outbox payload divergence.")
    if payload["session_id"] != outbox["session_id"]:
        raise PaperRuntimeSessionError("paper outbox session mismatch.")
    if payload["idempotency_key"] != outbox["idempotency_key"]:
        raise PaperRuntimeSessionError("paper outbox idempotency mismatch.")
    if payload["candle_close_time"] != outbox["candle_close_time"]:
        raise PaperRuntimeSessionError("paper outbox candle time mismatch.")
    recalculated_request_hash = _paper_runtime_outbox_request_hash(payload)
    recalculated_event_id = sha256_hex({"kind": "paper_runtime_outbox_event_id", "payload": payload})
    if recalculated_request_hash != outbox["request_hash"] or recalculated_event_id != outbox["event_id"]:
        raise PaperRuntimeSessionError("paper outbox hash mismatch.")
    runtime_events = payload.get("runtime_events")
    if not isinstance(runtime_events, list):
        raise PaperRuntimeSessionError("paper outbox runtime events are invalid.")
    snapshot_context = payload.get("snapshot_context")
    if not isinstance(snapshot_context, dict):
        raise PaperRuntimeSessionError("paper outbox snapshot context is invalid.")
    if set(snapshot_context) != {"preco_atual", "regime_info", "data_fresh"}:
        raise PaperRuntimeSessionError("paper outbox snapshot context schema mismatch.")
    if type(snapshot_context.get("data_fresh")) is not bool:
        raise PaperRuntimeSessionError("paper outbox data_fresh must be boolean.")
    telegram = payload.get("telegram")
    if not isinstance(telegram, dict):
        raise PaperRuntimeSessionError("paper outbox telegram payload is invalid.")
    if set(telegram) != {"chat_id", "text"}:
        raise PaperRuntimeSessionError("paper outbox telegram schema mismatch.")
    if "chat_id" in telegram and telegram["chat_id"] is not None and type(telegram["chat_id"]) is not int:
        raise PaperRuntimeSessionError("paper outbox telegram chat_id is invalid.")
    if "text" in telegram and not isinstance(telegram["text"], str):
        raise PaperRuntimeSessionError("paper outbox telegram text is invalid.")
    return payload


def _paper_runtime_outbox_state_allows_update(current_status: str, updates: dict) -> bool:
    status = str(current_status or "").strip().upper()
    if status not in {"PENDING", "DELIVERED", "NOTIFIED"}:
        return False
    desired = updates.get("status")
    if desired is not None:
        desired = str(desired).strip().upper()
        if desired not in {"PENDING", "DELIVERED", "NOTIFIED"}:
            return False
    if desired == "DELIVERED":
        return status in {"PENDING", "DELIVERED"}
    if desired == "NOTIFIED":
        return status in {"PENDING", "DELIVERED", "NOTIFIED"}
    return True


async def _reconciliar_paper_runtime_outbox(context, runtime_session, *, session_scope_id, chat_id):
    pendentes = obter_outbox_paper_pendentes(session_id=session_scope_id)
    if not pendentes:
        return False
    if runtime_session is None:
        raise PaperRuntimeSessionError("runtime session required to reconcile paper outbox.")
    for outbox in pendentes:
        try:
            payload = _paper_runtime_outbox_validate_record(outbox)
            if outbox["status"] == "PENDING":
                for event in payload.get("runtime_events", []):
                    if not isinstance(event, dict):
                        raise PaperRuntimeSessionError("paper outbox runtime event is invalid.")
                    event_type = PaperRuntimeEventType(event.get("event_type", PaperRuntimeEventType.TRADE_RECORDED.value))
                    _registrar_trade_runtime_event(
                        runtime_session,
                        payload=event.get("payload", {}),
                        result=event.get("result", "RECORDED"),
                        event_type=event_type,
                        idempotency_key=event.get("idempotency_key"),
                    )
                if not atualizar_outbox_paper_trade(
                    outbox["event_id"],
                    status="DELIVERED",
                    runtime_delivered_at_utc=datetime.now(timezone.utc).isoformat(),
                ):
                    raise PaperRuntimeSessionError("paper outbox delivery update failed.")

            snapshot_context = payload.get("snapshot_context") or {}
            if outbox["snapshot_applied_at_utc"] is None and snapshot_context is not None:
                current_trades = obter_trades_paper_abertos(PAPER_SYMBOL, session_id=session_scope_id)
                candle_close_time = datetime.fromisoformat(payload["candle_close_time"].replace("Z", "+00:00"))
                delta_seconds = (datetime.now(timezone.utc) - candle_close_time.astimezone(timezone.utc)).total_seconds()
                data_fresh = 0 <= delta_seconds <= 2 * 3600
                snapshot_observed = _coletar_runtime_observed_state(
                    session=runtime_session,
                    decision=runtime_session.decision,
                    df=None,
                    trades_abertos=current_trades,
                    preco_atual=snapshot_context.get("preco_atual"),
                    regime_info=snapshot_context.get("regime_info") or {},
                    data_fresh_hint=data_fresh,
                )
                snapshot = build_snapshot_from_observed_state(
                    session=runtime_session.record,
                    decision=runtime_session.decision,
                    observed=snapshot_observed,
                    timestamp_utc=candle_close_time,
                )
                runtime_session.evaluate_snapshot(
                    snapshot,
                    decision=runtime_session.decision,
                    idempotency_key=payload.get("snapshot_idempotency_key") or f"{payload['idempotency_key']}:snapshot",
                )
                if not atualizar_outbox_paper_trade(
                    outbox["event_id"],
                    snapshot_applied_at_utc=datetime.now(timezone.utc).isoformat(),
                    status="DELIVERED",
                ):
                    raise PaperRuntimeSessionError("paper outbox snapshot update failed.")

            if outbox["telegram_sent_at_utc"] is None:
                telegram = payload.get("telegram", {})
                await context.bot.send_message(
                    chat_id=telegram.get("chat_id") or chat_id,
                    text=telegram.get("text") or "Operacao paper reconciliada.",
                )
                if not atualizar_outbox_paper_trade(
                    outbox["event_id"],
                    status="NOTIFIED",
                    telegram_sent_at_utc=datetime.now(timezone.utc).isoformat(),
                ):
                    raise PaperRuntimeSessionError("paper outbox notification update failed.")
        except Exception as exc:
            atualizar_outbox_paper_trade(
                outbox["event_id"],
                attempts_increment=1,
                last_error_class=exc.__class__.__name__,
                last_error_code="OUTBOX_RECONCILE_FAILED",
            )
            logging.warning(
                f"Falha ao reconciliar outbox paper trade: {exc.__class__.__name__}"
            )
            raise PaperRuntimeSessionError("paper outbox reconciliation failed.") from exc
    return True


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
        logging.warning(f"Falha ao registrar decisao observabilidade: {exc.__class__.__name__}")


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
            logging.warning(f"Falha ao precomputar contextos do paper SOL: {exc.__class__.__name__}")
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
            logging.warning(f"Falha ao validar sinal paper SOL: {exc.__class__.__name__}")
            return None
        except Exception as exc:
            logging.warning(f"Falha ao validar sinal paper SOL: {exc.__class__.__name__}")
            return None
    except Exception as exc:
        logging.warning(f"Falha ao gerar sinal paper SOL: {exc.__class__.__name__}")
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
    if not PAPER_RUNTIME_AVAILABLE:
        return None
    if not job_data:
        return None
    session_id = job_data.get("session_id")
    if not session_id:
        return None
    try:
        return get_monitored_session(session_id=session_id)
    except Exception as exc:
        logging.warning(f"Sessao paper monitorada indisponivel: {exc.__class__.__name__}")
        return None


def _runtime_monitoring_enabled() -> bool:
    return PAPER_MONITORED_RUNTIME_REQUIRED


def _bloquear_runtime_monitorado(motivo: str, *, chat_id=None, regime_info=None, fonte_dados="N/D", erro="N/D", direcao="N/A", preco=None, adx=None, volume_status="N/D"):
    registrar_decisao_observabilidade(
        symbol=PAPER_SYMBOL,
        modo="PAPER_SOL",
        decisao="PAPER_SUSPENDED" if "sessao" in motivo.lower() or "runtime" in motivo.lower() else "ERRO",
        direcao=direcao,
        preco=preco,
        regime=(regime_info or {}).get("regime", "N/D") if regime_info else "N/D",
        adx=(regime_info or {}).get("adx") if regime_info else adx,
        volume_status=(regime_info or {}).get("volatilidade", volume_status) if regime_info else volume_status,
        motivo=motivo,
        bloqueado_por="SESSION",
        fonte_dados=fonte_dados,
        erro=erro,
    )


def _remover_jobs_runtime_monitorado(context, session_id: str | None) -> None:
    if not session_id:
        return
    try:
        jobs = context.job_queue.get_jobs_by_name(PAPER_JOB_NAME)
    except Exception:
        return
    for job in jobs:
        job_data = getattr(job, "data", {}) or {}
        if job_data.get("session_id") == session_id:
            job.schedule_removal()


def _coletar_runtime_observed_state(*, session, decision, df, trades_abertos, preco_atual, regime_info, data_fresh_hint=None):
    if df is None or getattr(df, "empty", True):
        data_fresh = bool(data_fresh_hint) if data_fresh_hint is not None else False
    elif "close_time" not in df.columns:
        data_fresh = bool(data_fresh_hint) if data_fresh_hint is not None else False
    else:
        ultimo_close_time = df["close_time"].iloc[-1]
        try:
            close_dt = ultimo_close_time.to_pydatetime() if hasattr(ultimo_close_time, "to_pydatetime") else ultimo_close_time
            if close_dt.tzinfo is None:
                data_fresh = False
            else:
                delta_seconds = (datetime.now(timezone.utc) - close_dt.astimezone(timezone.utc)).total_seconds()
                data_fresh = 0 <= delta_seconds <= 2 * 3600
        except Exception:
            data_fresh = bool(data_fresh_hint) if data_fresh_hint is not None else False

    session_id = session.record.session_id
    paper_trades = [
        trade
        for trade in trades_abertos
        if (trade.get("tipo") == "paper" or trade.get("status") == "open") and trade.get("session_id") == session_id
    ]
    try:
        from storage import obter_ultimos_trades_paper

        closed_trades = obter_ultimos_trades_paper(symbol=PAPER_SYMBOL, limite=500, session_id=session_id)
    except Exception as exc:
        raise PaperRuntimeSessionError("failed to load closed paper trades.") from exc

    def _trade_timestamp_key(trade: dict):
        timestamp_value = trade.get("fechado_em") or trade.get("saida_em") or trade.get("timestamp") or trade.get("aberto_em")
        if isinstance(timestamp_value, datetime):
            return timestamp_value if timestamp_value.tzinfo is not None else timestamp_value.replace(tzinfo=timezone.utc)
        try:
            texto = str(timestamp_value)
            if texto.endswith("Z"):
                texto = texto.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(texto)
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

    current_loss_streak = 0
    for trade in sorted(closed_trades, key=_trade_timestamp_key, reverse=True):
        lucro_reais = Decimal(str(trade.get("lucro_reais") or 0))
        if lucro_reais < 0:
            current_loss_streak += 1
        elif lucro_reais > 0:
            break

    session_drawdown_percent = Decimal("0")
    saldo = Decimal(str(CAPITAL_PAPER))
    pico = saldo
    for trade in sorted(closed_trades, key=_trade_timestamp_key):
        saldo += Decimal(str(trade.get("lucro_reais") or 0))
        if saldo > pico:
            pico = saldo
        if pico > 0:
            drawdown = ((pico - saldo) / pico) * Decimal("100")
            if drawdown > session_drawdown_percent:
                session_drawdown_percent = drawdown

    open_positions = len(paper_trades)
    executed_trades = len(closed_trades) + open_positions
    if paper_trades:
        paper_capital_used = sum(Decimal(str(t.get("valor_arriscado") or 0)) for t in paper_trades)
        risk_per_trade_percent = max(
            (Decimal(str(t.get("valor_arriscado") or 0)) / Decimal(str(CAPITAL_PAPER))) * Decimal("100")
            for t in paper_trades
        )
    else:
        paper_capital_used = Decimal("0")
        risk_per_trade_percent = Decimal("0")
    costs = {}
    try:
        costs = dict(session.contract.execution_contract or {})
    except Exception:
        if isinstance(decision.phase5_manifest, dict):
            costs = dict(decision.phase5_manifest.get("execution_contract", {}) or {})
    candidatos_custo = sorted(paper_trades + closed_trades, key=_trade_order_timestamp_key, reverse=True)

    def _tem_custos_completos(trade: dict) -> bool:
        return trade.get("resultado") is not None or trade.get("saida") is not None or trade.get("fechado_em") is not None or (
            trade.get("exit_fee") is not None
            or trade.get("exit_spread_cost") is not None
            or trade.get("exit_slippage_cost") is not None
            or trade.get("custos_totais") is not None
            or trade.get("pnl_liquido") is not None
        )

    persisted_cost_source = next((trade for trade in candidatos_custo if _tem_custos_completos(trade)), None)
    if persisted_cost_source is None:
        persisted_cost_source = next(
            (
                trade
                for trade in candidatos_custo
                if any(
                    trade.get(chave) is not None
                    for chave in (
                        "entry_fee",
                        "entry_spread_cost",
                        "entry_slippage_cost",
                        "spread_cost",
                        "slippage_cost",
                        "pnl_bruto",
                    )
                )
            ),
            None,
        )
    if persisted_cost_source is not None:
        try:
            quantidade_persistida = Decimal(str(persisted_cost_source.get("quantidade") or 0))
            preco_base_persistido = Decimal(
                str(
                    persisted_cost_source.get("preco_base")
                    or persisted_cost_source.get("entrada")
                    or persisted_cost_source.get("fill_price")
                    or 0
                )
            )
            fill_price_persistido = Decimal(
                str(
                    persisted_cost_source.get("fill_price")
                    or persisted_cost_source.get("preco_base")
                    or persisted_cost_source.get("entrada")
                    or 0
                )
            )
            saida_persistida = Decimal(str(persisted_cost_source.get("saida") or fill_price_persistido))
            entry_fee = Decimal(str(persisted_cost_source.get("entry_fee") or 0))
            exit_fee = Decimal(str(persisted_cost_source.get("exit_fee") or 0))
            entry_spread_cost = Decimal(str(persisted_cost_source.get("entry_spread_cost") or 0))
            entry_slippage_cost = Decimal(str(persisted_cost_source.get("entry_slippage_cost") or 0))
            exit_spread_cost = Decimal(str(persisted_cost_source.get("exit_spread_cost") or 0))
            exit_slippage_cost = Decimal(str(persisted_cost_source.get("exit_slippage_cost") or 0))
            entry_notional = abs(quantidade_persistida * (fill_price_persistido or preco_base_persistido or Decimal("0")))
            trade_closed = any(
                persisted_cost_source.get(chave) is not None
                for chave in ("fechado_em", "saida", "pnl_liquido", "resultado")
            ) or str(persisted_cost_source.get("status") or "").lower() == "closed"
            exit_notional = abs(quantidade_persistida * (saida_persistida or preco_base_persistido or Decimal("0"))) if trade_closed else Decimal("0")
            total_notional = entry_notional + exit_notional if trade_closed and exit_notional > 0 else entry_notional
            spread_cost = Decimal(str(persisted_cost_source.get("spread_cost") or (entry_spread_cost + (exit_spread_cost if trade_closed else Decimal("0")))))
            slippage_cost = Decimal(str(persisted_cost_source.get("slippage_cost") or (entry_slippage_cost + (exit_slippage_cost if trade_closed else Decimal("0")))))
            spread_component = entry_spread_cost + (exit_spread_cost if trade_closed else Decimal("0"))
            slippage_component = entry_slippage_cost + (exit_slippage_cost if trade_closed else Decimal("0"))
            observed_costs = {
                "entry_fee_rate": (entry_fee / entry_notional) if entry_notional > 0 else Decimal(str(costs.get("entry_fee_rate", "0.0004"))),
                "exit_fee_rate": (exit_fee / exit_notional) if trade_closed and exit_notional > 0 else Decimal(str(costs.get("exit_fee_rate", "0.0004"))),
                "spread_bps": ((spread_component / total_notional) * Decimal("10000"))
                if quantidade_persistida > 0 and total_notional > 0 and spread_component >= 0
                else Decimal(str(costs.get("spread_bps", "5"))),
                "slippage_bps": ((slippage_component / total_notional) * Decimal("10000"))
                if quantidade_persistida > 0 and total_notional > 0 and slippage_component >= 0
                else Decimal(str(costs.get("slippage_bps", "5"))),
            }
        except Exception:
            observed_costs = {
                "entry_fee_rate": costs.get("entry_fee_rate", "0.0004"),
                "exit_fee_rate": costs.get("exit_fee_rate", "0.0004"),
                "spread_bps": costs.get("spread_bps", "5"),
                "slippage_bps": costs.get("slippage_bps", "5"),
            }
    else:
        observed_costs = {
            "entry_fee_rate": costs.get("entry_fee_rate", "0.0004"),
            "exit_fee_rate": costs.get("exit_fee_rate", "0.0004"),
            "spread_bps": costs.get("spread_bps", "5"),
            "slippage_bps": costs.get("slippage_bps", "5"),
        }
    if not isinstance(regime_info, dict):
        regime_info = {}
    session_state_raw = getattr(session.record.state, "value", session.record.state)
    session_state = str(session_state_raw).strip().upper()
    if session_state not in {"RUNNING", "COMPLETED"}:
        raise PaperRuntimeSessionError("session state is invalid.")
    return {
        "data_fresh": data_fresh,
        "session_drawdown_percent": session_drawdown_percent,
        "current_loss_streak": current_loss_streak,
        "open_positions": open_positions,
        "executed_trades": executed_trades,
        "observed_costs": observed_costs,
        "session_state": session_state,
        "paper_capital_used": paper_capital_used,
        "risk_per_trade_percent": risk_per_trade_percent,
        "internal_error": None,
        "attempted_live": False,
    }


async def _processar_trades_paper_abertos(context, chat_id, trades, candle, df, regime_info, fonte_dados, *, runtime_session=None, close_time=None):
    if not trades:
        return False
    costs = _paper_costs_from_contract(runtime_session) if runtime_session is not None else {
        "entry_fee_rate": Decimal("0.0004"),
        "exit_fee_rate": Decimal("0.0004"),
        "spread_bps": Decimal("5"),
        "slippage_bps": Decimal("5"),
    }
    trade_moved = False
    for trade in trades:
        direcao = trade["direcao"]
        stop_loss = trade["stop_loss"]
        take_profit = trade["take_profit"]
        quantidade = trade["quantidade"]
        entrada = trade["entrada"]

        if direcao == "COMPRA":
            stop_atingido = float(candle["low"]) <= stop_loss
            take_atingido = float(candle["high"]) >= take_profit
            if stop_atingido or take_atingido:
                saida = stop_loss if stop_atingido else take_profit
                trade_costs = _paper_trade_costs(direcao, entrada, saida, quantidade, costs)
                lucro_reais = float(trade_costs["pnl_liquido"])
                lucro_percent = (Decimal(str(lucro_reais)) / Decimal(str(CAPITAL_PAPER))) * Decimal("100")
                resultado_trade = _construir_trade_result_paper(
                    trade,
                    saida,
                    float(lucro_percent),
                    lucro_reais,
                    fonte_dados,
                    "STOP" if stop_atingido else "TAKE_PROFIT",
                )
                close_candle_time = close_time or datetime.now(timezone.utc)
                close_idempotency_key = _paper_runtime_idempotency_key(
                    runtime_session.record.session_id if runtime_session else None,
                    close_candle_time,
                    "close",
                    f"{trade['id']}:{saida}",
                )
                mensagem_fechamento = f"Paper SOL fechado por {'STOP' if stop_atingido else 'TAKE PROFIT'}. Resultado: {fmt_num(lucro_percent, '+.2f')}%"

                delta_seconds = (datetime.now(timezone.utc) - close_candle_time).total_seconds()
                data_fresh_snapshot = 0 <= delta_seconds <= 2 * 3600

                def _outbox_factory_close(trade_id, _timestamp):
                    runtime_events = [
                        {
                            "event_type": PaperRuntimeEventType.TRADE_RECORDED.value,
                            "result": "CLOSED",
                            "idempotency_key": _paper_runtime_idempotency_key(
                                runtime_session.record.session_id if runtime_session else None,
                                close_candle_time,
                                "close",
                                f"{trade_id}:{saida}",
                            ),
                            "payload": {
                                "action": "CLOSE",
                                "trade_id": trade_id,
                                "session_id": runtime_session.record.session_id if runtime_session else None,
                                "direcao": direcao,
                                "motivo": "STOP" if stop_atingido else "TAKE_PROFIT",
                                "saida": saida,
                                "entry_base": entrada,
                                "pnl_bruto": float(trade_costs["pnl_bruto"]),
                                "custos_totais": float(trade_costs["custos_totais"]),
                                "pnl_liquido": float(trade_costs["pnl_liquido"]),
                            },
                        },
                        {
                            "event_type": PaperRuntimeEventType.FILL.value,
                            "result": "FILLED",
                            "idempotency_key": _paper_runtime_idempotency_key(
                                runtime_session.record.session_id if runtime_session else None,
                                close_candle_time,
                                "fill-exit",
                                f"{trade_id}:{saida}",
                            ),
                            "payload": {
                                "action": "FILL",
                                "side": "EXIT",
                                "trade_id": trade_id,
                                "session_id": runtime_session.record.session_id if runtime_session else None,
                                "direcao": direcao,
                                "fill_price": saida,
                            },
                        },
                    ]
                    outbox_payload = _paper_runtime_outbox_payload(
                        operation_type="CLOSE",
                        trade_id=trade_id,
                        session_id=runtime_session.record.session_id if runtime_session else None,
                        candle_close_time=close_candle_time,
                        idempotency_key=close_idempotency_key,
                        runtime_events=runtime_events,
                        snapshot_context={
                            "preco_atual": saida,
                            "regime_info": regime_info,
                            "data_fresh": data_fresh_snapshot,
                        },
                        telegram_text=mensagem_fechamento,
                        telegram_chat_id=chat_id,
                    )
                    return _paper_runtime_outbox_record(outbox_payload)

                fechamento_ok = finalizar_trade_paper(
                    trade["id"],
                    float(resultado_trade.exit_price),
                    float(resultado_trade.pnl_percent),
                    float(resultado_trade.pnl_reais),
                    resultado_trade.resultado,
                    resultado_trade.reason,
                    idempotency_key=close_idempotency_key,
                    session_id=runtime_session.record.session_id if runtime_session else None,
                    candle_close_time=close_candle_time,
                    fill_price=saida,
                    pnl_bruto=float(trade_costs["pnl_bruto"]),
                    custos_totais=float(trade_costs["custos_totais"]),
                    pnl_liquido=float(trade_costs["pnl_liquido"]),
                    exit_fee=float(trade_costs["exit_fee"]),
                    entry_spread_cost=float(trade_costs["entry_spread_cost"]),
                    entry_slippage_cost=float(trade_costs["entry_slippage_cost"]),
                    exit_spread_cost=float(trade_costs["exit_spread_cost"]),
                    exit_slippage_cost=float(trade_costs["exit_slippage_cost"]),
                    spread_cost=float(trade_costs["spread_cost"]),
                    slippage_cost=float(trade_costs["slippage_cost"]),
                    close_idempotency_key=close_idempotency_key,
                    outbox_event_factory=_outbox_factory_close if runtime_session is not None else None,
                )
                if not fechamento_ok:
                    raise PaperRuntimeSessionError("paper trade close failed.")
                if runtime_session is not None:
                    await _reconciliar_paper_runtime_outbox(
                        context,
                        runtime_session,
                        session_scope_id=runtime_session.record.session_id,
                        chat_id=chat_id,
                    )
                else:
                    await context.bot.send_message(chat_id=chat_id, text=mensagem_fechamento)
                registrar_decisao_observabilidade(
                    symbol=PAPER_SYMBOL,
                    modo="PAPER_SOL",
                    decisao="TRADE_FECHADO",
                    direcao=direcao,
                    preco=saida,
                    regime=regime_info.get("regime"),
                    adx=regime_info.get("adx"),
                    volume_status=regime_info.get("volatilidade"),
                    motivo="Fechado no STOP" if stop_atingido else "Fechado no TAKE PROFIT",
                    bloqueado_por="N/A",
                    fonte_dados=fonte_dados,
                    erro="N/A",
                )
                trade_moved = True
        else:
            stop_atingido = float(candle["high"]) >= stop_loss
            take_atingido = float(candle["low"]) <= take_profit
            if stop_atingido or take_atingido:
                saida = stop_loss if stop_atingido else take_profit
                trade_costs = _paper_trade_costs(direcao, entrada, saida, quantidade, costs)
                lucro_reais = float(trade_costs["pnl_liquido"])
                lucro_percent = (Decimal(str(lucro_reais)) / Decimal(str(CAPITAL_PAPER))) * Decimal("100")
                resultado_trade = _construir_trade_result_paper(
                    trade,
                    saida,
                    float(lucro_percent),
                    lucro_reais,
                    fonte_dados,
                    "STOP" if stop_atingido else "TAKE_PROFIT",
                )
                close_candle_time = close_time or datetime.now(timezone.utc)
                close_idempotency_key = _paper_runtime_idempotency_key(
                    runtime_session.record.session_id if runtime_session else None,
                    close_candle_time,
                    "close",
                    f"{trade['id']}:{saida}",
                )
                mensagem_fechamento = f"Paper SOL fechado por {'STOP' if stop_atingido else 'TAKE PROFIT'}. Resultado: {fmt_num(lucro_percent, '+.2f')}%"

                delta_seconds = (datetime.now(timezone.utc) - close_candle_time).total_seconds()
                data_fresh_snapshot = 0 <= delta_seconds <= 2 * 3600

                def _outbox_factory_close(trade_id, _timestamp):
                    runtime_events = [
                        {
                            "event_type": PaperRuntimeEventType.TRADE_RECORDED.value,
                            "result": "CLOSED",
                            "idempotency_key": _paper_runtime_idempotency_key(
                                runtime_session.record.session_id if runtime_session else None,
                                close_candle_time,
                                "close",
                                f"{trade_id}:{saida}",
                            ),
                            "payload": {
                                "action": "CLOSE",
                                "trade_id": trade_id,
                                "session_id": runtime_session.record.session_id if runtime_session else None,
                                "direcao": direcao,
                                "motivo": "STOP" if stop_atingido else "TAKE_PROFIT",
                                "saida": saida,
                                "entry_base": entrada,
                                "pnl_bruto": float(trade_costs["pnl_bruto"]),
                                "custos_totais": float(trade_costs["custos_totais"]),
                                "pnl_liquido": float(trade_costs["pnl_liquido"]),
                            },
                        },
                        {
                            "event_type": PaperRuntimeEventType.FILL.value,
                            "result": "FILLED",
                            "idempotency_key": _paper_runtime_idempotency_key(
                                runtime_session.record.session_id if runtime_session else None,
                                close_candle_time,
                                "fill-exit",
                                f"{trade_id}:{saida}",
                            ),
                            "payload": {
                                "action": "FILL",
                                "side": "EXIT",
                                "trade_id": trade_id,
                                "session_id": runtime_session.record.session_id if runtime_session else None,
                                "direcao": direcao,
                                "fill_price": saida,
                            },
                        },
                    ]
                    return _paper_runtime_outbox_record(
                        _paper_runtime_outbox_payload(
                            operation_type="CLOSE",
                            trade_id=trade_id,
                            session_id=runtime_session.record.session_id if runtime_session else None,
                            candle_close_time=close_candle_time,
                            idempotency_key=close_idempotency_key,
                            runtime_events=runtime_events,
                            snapshot_context={
                                "preco_atual": saida,
                                "regime_info": regime_info,
                                "data_fresh": data_fresh_snapshot,
                            },
                            telegram_text=mensagem_fechamento,
                            telegram_chat_id=chat_id,
                        )
                    )

                fechamento_ok = finalizar_trade_paper(
                    trade["id"],
                    float(resultado_trade.exit_price),
                    float(resultado_trade.pnl_percent),
                    float(resultado_trade.pnl_reais),
                    resultado_trade.resultado,
                    resultado_trade.reason,
                    idempotency_key=close_idempotency_key,
                    session_id=runtime_session.record.session_id if runtime_session else None,
                    candle_close_time=close_candle_time,
                    fill_price=saida,
                    pnl_bruto=float(trade_costs["pnl_bruto"]),
                    custos_totais=float(trade_costs["custos_totais"]),
                    pnl_liquido=float(trade_costs["pnl_liquido"]),
                    exit_fee=float(trade_costs["exit_fee"]),
                    entry_spread_cost=float(trade_costs["entry_spread_cost"]),
                    entry_slippage_cost=float(trade_costs["entry_slippage_cost"]),
                    exit_spread_cost=float(trade_costs["exit_spread_cost"]),
                    exit_slippage_cost=float(trade_costs["exit_slippage_cost"]),
                    spread_cost=float(trade_costs["spread_cost"]),
                    slippage_cost=float(trade_costs["slippage_cost"]),
                    close_idempotency_key=close_idempotency_key,
                    outbox_event_factory=_outbox_factory_close if runtime_session is not None else None,
                )
                if not fechamento_ok:
                    raise PaperRuntimeSessionError("paper trade close failed.")
                if runtime_session is not None:
                    await _reconciliar_paper_runtime_outbox(
                        context,
                        runtime_session,
                        session_scope_id=runtime_session.record.session_id,
                        chat_id=chat_id,
                    )
                else:
                    await context.bot.send_message(chat_id=chat_id, text=mensagem_fechamento)
                registrar_decisao_observabilidade(
                    symbol=PAPER_SYMBOL,
                    modo="PAPER_SOL",
                    decisao="TRADE_FECHADO",
                    direcao=direcao,
                    preco=saida,
                    regime=regime_info.get("regime"),
                    adx=regime_info.get("adx"),
                    volume_status=regime_info.get("volatilidade"),
                    motivo="Fechado no STOP" if stop_atingido else "Fechado no TAKE PROFIT",
                    bloqueado_por="N/A",
                    fonte_dados=fonte_dados,
                    erro="N/A",
                )
                trade_moved = True
    return trade_moved


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
        session_scope_id = runtime_session.record.session_id if runtime_session is not None else job_data.get("session_id")
        if _runtime_monitoring_enabled():
            session_id = job_data.get("session_id")
            if not session_id or runtime_session is None or not runtime_session.is_running():
                _bloquear_runtime_monitorado(
                    "Sessao paper monitorada indisponivel.",
                    chat_id=chat_id,
                    fonte_dados="N/D",
                    erro="runtime indisponivel",
                )
                return
            if build_snapshot_from_observed_state is None or evaluate_monitored_session is None:
                _bloquear_runtime_monitorado(
                    "Runtime paper monitorado indisponivel.",
                    chat_id=chat_id,
                    fonte_dados="N/D",
                    erro="runtime import indisponivel",
                )
                return
            if await _reconciliar_paper_runtime_outbox(
                context,
                runtime_session,
                session_scope_id=session_scope_id,
                chat_id=chat_id,
            ):
                logging.info("Outbox paper reconciliada antes de nova decisao.")
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
        candle_close_time = _paper_runtime_close_timestamp(df)
        regime_info = classificar_regime(df)
        aberto = obter_trades_paper_abertos(PAPER_SYMBOL, session_id=session_scope_id)

        runtime_costs = None
        if _runtime_monitoring_enabled():
            runtime_decision = runtime_session.decision
            if runtime_decision is None:
                _bloquear_runtime_monitorado(
                    "Sessao runtime sem decisao monitoravel.",
                    chat_id=chat_id,
                    regime_info=regime_info,
                    fonte_dados=fonte_dados,
                    preco=preco_atual,
                    erro="runtime decision ausente",
                )
                return
            runtime_costs = _paper_costs_from_contract(runtime_session)
            runtime_observed_pre = _coletar_runtime_observed_state(
                session=runtime_session,
                decision=runtime_decision,
                df=df,
                trades_abertos=aberto,
                preco_atual=preco_atual,
                regime_info=regime_info,
            )
            try:
                runtime_snapshot_pre = build_snapshot_from_observed_state(
                    session=runtime_session.record,
                    decision=runtime_decision,
                    observed=runtime_observed_pre,
                    timestamp_utc=candle_close_time,
                )
                runtime_result_pre = runtime_session.evaluate_snapshot(
                    runtime_snapshot_pre,
                    decision=runtime_decision,
                    idempotency_key=_paper_runtime_idempotency_key(
                        runtime_session.record.session_id,
                        candle_close_time,
                        "monitor-pre",
                        f"{PAPER_SYMBOL}:{preco_atual}",
                    ),
                )
                if not runtime_result_pre.approved:
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
                    _remover_jobs_runtime_monitorado(context, runtime_session.record.session_id)
                    logging.warning("Sessao paper monitorada suspensa; novas ordens bloqueadas.")
                    return
            except Exception as exc:
                _bloquear_runtime_monitorado(
                    "Falha ao revalidar a sessao paper monitorada.",
                    chat_id=chat_id,
                    regime_info=regime_info,
                    fonte_dados=fonte_dados,
                    preco=preco_atual,
                    erro="revalidacao runtime falhou",
                )
                _remover_jobs_runtime_monitorado(context, runtime_session.record.session_id)
                logging.warning("Falha ao revalidar sessao paper monitorada.")
                return

        if await _processar_trades_paper_abertos(
            context,
            chat_id,
            aberto,
            candle,
            df,
            regime_info,
            fonte_dados,
            runtime_session=runtime_session if _runtime_monitoring_enabled() else None,
            close_time=candle_close_time,
        ):
            if _runtime_monitoring_enabled() and runtime_session is not None and runtime_costs is not None:
                aberto_pos = obter_trades_paper_abertos(PAPER_SYMBOL, session_id=session_scope_id)
                runtime_observed_post = _coletar_runtime_observed_state(
                    session=runtime_session,
                    decision=runtime_session.decision,
                    df=df,
                    trades_abertos=aberto_pos,
                    preco_atual=preco_atual,
                    regime_info=regime_info,
                )
                runtime_snapshot_post = build_snapshot_from_observed_state(
                    session=runtime_session.record,
                    decision=runtime_session.decision,
                    observed=runtime_observed_post,
                    timestamp_utc=candle_close_time,
                )
                runtime_session.evaluate_snapshot(
                    runtime_snapshot_post,
                    decision=runtime_session.decision,
                    idempotency_key=_paper_runtime_idempotency_key(
                        runtime_session.record.session_id,
                        candle_close_time,
                        "monitor-post-close",
                        f"{PAPER_SYMBOL}:{preco_atual}:{len(aberto_pos)}",
                    ),
                )
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
        trade_costs_entry = _paper_trade_costs(
            sinal["direcao"],
            entrada,
            entrada,
            float(trade_intent.quantity),
            runtime_costs or (
                _paper_costs_from_contract(runtime_session)
                if runtime_session is not None
                else {
                    "entry_fee_rate": Decimal("0.0004"),
                    "exit_fee_rate": Decimal("0.0004"),
                    "spread_bps": Decimal("5"),
                    "slippage_bps": Decimal("5"),
                }
            ),
            include_exit_costs=False,
        )
        signal_identity = _paper_runtime_signal_identity(
            sinal,
            regime_info=regime_info,
            decisao_info=decisao_info,
            candle_close_time=candle_close_time,
        )
        open_idempotency_key = _paper_runtime_operation_identity(
            session_id=session_scope_id,
            candle_close_time=candle_close_time,
            symbol=PAPER_SYMBOL,
            operation="open",
            direcao=sinal["direcao"],
            signal_identity=signal_identity,
        )
        observed_trade_aberto = {
            "session_id": session_scope_id,
            "tipo": "paper",
            "status": "open",
            "valor_arriscado": float(trade_intent.risk_amount),
        }
        delta_seconds = (datetime.now(timezone.utc) - candle_close_time).total_seconds()
        data_fresh_snapshot = 0 <= delta_seconds <= 2 * 3600

        def _mensagem_abertura_paper(trade_id):
            return (
                f"Paper SOL aberto\n"
                f"Direcao: {sinal['direcao']}\n"
                f"Entrada: {fmt_num(entrada, ',.4f')}\n"
                f"Stop: {fmt_num(stop_loss, ',.4f')}\n"
                f"Take: {fmt_num(take_profit, ',.4f')}\n"
                f"R/R: {fmt_num(rr_planejado)}\n"
                f"Trade ID: {trade_id}"
            )

        def _outbox_factory_open(trade_id, _timestamp):
            runtime_events = [
                {
                    "event_type": PaperRuntimeEventType.TRADE_RECORDED.value,
                    "result": "OPENED",
                    "idempotency_key": _paper_runtime_idempotency_key(
                        runtime_session.record.session_id if runtime_session else None,
                        candle_close_time,
                        "open",
                        f"{trade_id}:{sinal['direcao']}:{entrada}:{stop_loss}:{take_profit}",
                    ),
                    "payload": {
                        "action": "OPEN",
                        "trade_id": trade_id,
                        "session_id": runtime_session.record.session_id if runtime_session else None,
                        "direcao": sinal["direcao"],
                        "entrada_base": entrada,
                        "fill_price": float(trade_costs_entry["fill_price"]),
                        "entry_fee": float(trade_costs_entry["entry_fee"]),
                        "spread_cost": float(trade_costs_entry["spread_cost"]),
                        "slippage_cost": float(trade_costs_entry["slippage_cost"]),
                    },
                },
                {
                    "event_type": PaperRuntimeEventType.FILL.value,
                    "result": "FILLED",
                    "idempotency_key": _paper_runtime_idempotency_key(
                        runtime_session.record.session_id if runtime_session else None,
                        candle_close_time,
                        "fill-entry",
                        f"{trade_id}:{sinal['direcao']}:{entrada}:{stop_loss}:{take_profit}",
                    ),
                    "payload": {
                        "action": "FILL",
                        "side": "ENTRY",
                        "trade_id": trade_id,
                        "session_id": runtime_session.record.session_id if runtime_session else None,
                        "direcao": sinal["direcao"],
                        "fill_price": float(trade_costs_entry["fill_price"]),
                    },
                },
            ]
            outbox_payload = _paper_runtime_outbox_payload(
                operation_type="OPEN",
                trade_id=trade_id,
                session_id=runtime_session.record.session_id if runtime_session else session_scope_id,
                candle_close_time=candle_close_time,
                idempotency_key=open_idempotency_key,
                runtime_events=runtime_events,
                snapshot_context={
                    "preco_atual": preco_atual,
                    "regime_info": regime_info,
                    "data_fresh": data_fresh_snapshot,
                },
                telegram_text=_mensagem_abertura_paper(trade_id),
                telegram_chat_id=chat_id,
            )
            return _paper_runtime_outbox_record(outbox_payload)

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
            session_id=session_scope_id,
            idempotency_key=open_idempotency_key,
            candle_close_time=candle_close_time,
            signal_identity=signal_identity,
            preco_base=entrada,
            fill_price=float(trade_costs_entry["fill_price"]),
            entry_fee=float(trade_costs_entry["entry_fee"]),
            entry_spread_cost=float(trade_costs_entry["entry_spread_cost"]),
            entry_slippage_cost=float(trade_costs_entry["entry_slippage_cost"]),
            spread_cost=float(trade_costs_entry["entry_spread_cost"]),
            slippage_cost=float(trade_costs_entry["entry_slippage_cost"]),
            outbox_event_factory=_outbox_factory_open if runtime_session is not None else None,
        )
        mensagem_abertura = _mensagem_abertura_paper(trade_id)
        if trade_id is None:
            registrar_decisao_observabilidade(
                symbol=PAPER_SYMBOL,
                modo="PAPER_SOL",
                decisao="ERRO",
                direcao=sinal.get("direcao"),
                preco=entrada,
                regime=regime_info.get("regime"),
                adx=regime_info.get("adx"),
                volume_status=decisao_info.get("volume_status"),
                motivo="Falha ao registrar trade paper.",
                bloqueado_por="RISK",
                fonte_dados=fonte_dados,
                erro="trade paper indisponivel",
            )
            return

        if runtime_session is not None:
            await _reconciliar_paper_runtime_outbox(
                context,
                runtime_session,
                session_scope_id=session_scope_id,
                chat_id=chat_id,
            )
        else:
            await context.bot.send_message(chat_id=chat_id, text=mensagem_abertura)

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
            return
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
            erro=exc.__class__.__name__,
        )
        logging.warning(f"Erro no monitoramento paper SOL: {exc.__class__.__name__}")
