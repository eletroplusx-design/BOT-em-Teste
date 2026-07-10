import logging
import math
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import requests
from config import (
    ALAVANCAGEM_MAXIMA,
    CAPITAL_REAL,
    DISTANCIA_MAX_PCT,
    DISTANCIA_MIN_PCT,
    MAX_EXPOSICAO_PERCENTUAL,
    MAX_PERDA_DIARIA_PERCENTUAL,
    MAX_PERDAS_CONSECUTIVAS,
    MAX_TRADES_POR_DIA,
    STRATEGY_VERSION,
)

logger = logging.getLogger(__name__)

DEFAULT_CAPITAL = CAPITAL_REAL
DEFAULT_RISK_PCT = 1.0
DEFAULT_MAX_LEVERAGE = ALAVANCAGEM_MAXIMA
DEFAULT_MAX_DAILY_LOSS_PCT = MAX_PERDA_DIARIA_PERCENTUAL
DEFAULT_MAX_CONSECUTIVE_LOSSES = MAX_PERDAS_CONSECUTIVAS
DEFAULT_MAX_TRADES_PER_DAY = MAX_TRADES_POR_DIA
DEFAULT_MAX_EXPOSURE_PCT = MAX_EXPOSICAO_PERCENTUAL
DEFAULT_MIN_DISTANCE_PCT = DISTANCIA_MIN_PCT
DEFAULT_MAX_DISTANCE_PCT = DISTANCIA_MAX_PCT

_exchange_info_cache: Dict[str, Dict[str, Any]] = {}
_cache_timestamp: Dict[str, datetime] = {}


def _buscar_exchange_info(symbol: str, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Busca informações do contrato na Binance e mantém cache por 1 hora.
    Em caso de falha, retorna fallback seguro.
    """
    if not symbol:
        return _fallback_exchange_info()

    if not force_refresh and symbol in _exchange_info_cache:
        cached_at = _cache_timestamp.get(symbol)
        if cached_at and (datetime.now() - cached_at).seconds < 3600:
            info = dict(_exchange_info_cache[symbol])
            info["exchange_info_ok"] = True
            return info

    try:
        url = "https://api.binance.com/api/v3/exchangeInfo"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        for s in data.get("symbols", []):
            if s.get("symbol") != symbol:
                continue

            filters = {f.get("filterType"): f for f in s.get("filters", []) if f.get("filterType")}
            lot_size = filters.get("LOT_SIZE", {})
            price_filter = filters.get("PRICE_FILTER", {})
            min_notional = filters.get("MIN_NOTIONAL", {})

            tick_size = float(price_filter.get("tickSize", 0.01) or 0.01)
            step_size = float(lot_size.get("stepSize", 0.001) or 0.001)

            info = {
                "step_size": step_size,
                "min_qty": float(lot_size.get("minQty", 0.001) or 0.001),
                "max_qty": float(lot_size.get("maxQty", 1000000) or 1000000),
                "tick_size": tick_size,
                "min_price": float(price_filter.get("minPrice", 0.0) or 0.0),
                "max_price": float(price_filter.get("maxPrice", 1000000) or 1000000),
                "min_notional": float(min_notional.get("minNotional", 10.0) or 10.0),
                "price_precision": _precision_from_step(tick_size, default=2),
                "quantity_precision": _precision_from_step(step_size, default=3),
                "exchange_info_ok": True,
            }
            _exchange_info_cache[symbol] = dict(info)
            _cache_timestamp[symbol] = datetime.now()
            return info

        logger.warning("ExchangeInfo: símbolo %s não encontrado. Usando fallback seguro.", symbol)
        return _fallback_exchange_info()

    except Exception as exc:
        logger.error("Erro ao buscar exchangeInfo: %s. Usando fallback seguro.", exc)
        return _fallback_exchange_info()


def _fallback_exchange_info() -> Dict[str, Any]:
    return {
        "step_size": 0.001,
        "min_qty": 0.001,
        "max_qty": 1000000,
        "tick_size": 0.01,
        "min_price": 0.0,
        "max_price": 1000000,
        "min_notional": 10.0,
        "price_precision": 2,
        "quantity_precision": 3,
        "exchange_info_ok": False,
    }


def _precision_from_step(value: float, default: int = 2) -> int:
    if value <= 0:
        return default
    try:
        return int(round(-math.log10(value)))
    except (ValueError, OverflowError):
        return default


def _arredondar_quantidade(quantidade: float, step_size: float) -> float:
    if step_size <= 0:
        return quantidade
    return math.floor(quantidade / step_size) * step_size


def _arredondar_preco(preco: float, tick_size: float) -> float:
    if tick_size <= 0:
        return preco
    return round(preco / tick_size) * tick_size


def calcular_posicao(
    capital: float,
    risco_pct: float,
    entrada: float,
    stop: float,
    symbol: str = "BTCUSDT",
    alavancagem: float = DEFAULT_MAX_LEVERAGE,
    trades_abertos: Optional[list] = None,
    perdas_hoje: float = 0.0,
    trades_hoje: int = 0,
    perdas_consecutivas: int = 0,
    exposure_limit_pct: float = DEFAULT_MAX_EXPOSURE_PCT,
    max_daily_loss_pct: float = DEFAULT_MAX_DAILY_LOSS_PCT,
    max_consecutive_losses: int = DEFAULT_MAX_CONSECUTIVE_LOSSES,
    max_trades_per_day: int = DEFAULT_MAX_TRADES_PER_DAY,
    min_distance_pct: float = DEFAULT_MIN_DISTANCE_PCT,
    max_distance_pct: float = DEFAULT_MAX_DISTANCE_PCT,
) -> Dict[str, Any]:
    if capital <= 0:
        return {"aprovado": False, "motivo": "Capital inválido (<= 0)"}
    if risco_pct <= 0 or risco_pct > 5:
        return {"aprovado": False, "motivo": f"Risco {risco_pct}% fora do limite (0-5%)"}
    if entrada <= 0 or stop <= 0:
        return {"aprovado": False, "motivo": "Entrada ou stop inválido (<= 0)"}

    distancia = abs(entrada - stop)
    if distancia <= 0:
        return {"aprovado": False, "motivo": "Distância entre entrada e stop é zero"}

    distancia_pct = (distancia / entrada) * 100
    if distancia_pct < min_distance_pct:
        return {"aprovado": False, "motivo": f"Stop muito apertado ({distancia_pct:.2f}% < {min_distance_pct}%)"}
    if distancia_pct > max_distance_pct:
        return {"aprovado": False, "motivo": f"Stop muito largo ({distancia_pct:.2f}% > {max_distance_pct}%)"}

    max_daily_loss = capital * (max_daily_loss_pct / 100)
    if perdas_hoje > max_daily_loss:
        return {"aprovado": False, "motivo": f"Limite diário de perda atingido ({max_daily_loss_pct}%)"}

    if perdas_consecutivas >= max_consecutive_losses:
        return {"aprovado": False, "motivo": f"Sequência máxima de perdas ({max_consecutive_losses}) atingida"}

    if trades_hoje >= max_trades_per_day:
        return {"aprovado": False, "motivo": f"Número máximo de trades por dia ({max_trades_per_day}) atingido"}

    valor_arriscado = capital * (risco_pct / 100)
    quantidade_bruta = valor_arriscado / distancia

    info = _buscar_exchange_info(symbol)
    step_size = info.get("step_size", 0.001)
    min_qty = info.get("min_qty", 0.001)
    max_qty = info.get("max_qty", 1000000)
    tick_size = info.get("tick_size", 0.01)
    min_notional = info.get("min_notional", 10.0)
    price_precision = info.get("price_precision", 2)
    quantity_precision = info.get("quantity_precision", 3)

    quantidade = _arredondar_quantidade(quantidade_bruta, step_size)

    if quantidade < min_qty:
        return {"aprovado": False, "motivo": f"Quantidade ({quantidade}) abaixo do mínimo ({min_qty})"}
    if quantidade > max_qty:
        return {"aprovado": False, "motivo": f"Quantidade ({quantidade}) acima do máximo ({max_qty})"}

    entrada_ajustada = _arredondar_preco(entrada, tick_size)
    stop_ajustado = _arredondar_preco(stop, tick_size)
    valor_nocional = quantidade * entrada_ajustada

    if valor_nocional < min_notional:
        return {"aprovado": False, "motivo": f"Valor nocional ({valor_nocional:.2f}) abaixo do mínimo ({min_notional})"}

    margem_necessaria = valor_nocional / alavancagem if alavancagem > 0 else valor_nocional
    exposure_limit = capital * (exposure_limit_pct / 100)
    if margem_necessaria > exposure_limit:
        return {
            "aprovado": False,
            "motivo": f"Margem necessária ({margem_necessaria:.2f}) excede limite de exposição ({exposure_limit:.2f})",
        }

    if trades_abertos:
        exposure_atual = sum(t.get("valor_nocional", 0) for t in trades_abertos)
        if exposure_atual + valor_nocional > exposure_limit:
            return {"aprovado": False, "motivo": f"Exposição total com trades abertos excederia {exposure_limit_pct}%"}

    return {
        "aprovado": True,
        "motivo": "Posição aprovada",
        "quantidade": quantidade,
        "valor_arriscado": valor_arriscado,
        "valor_nocional": valor_nocional,
        "margem_necessaria": margem_necessaria,
        "alavancagem": alavancagem,
        "risco_pct": risco_pct,
        "entrada_ajustada": entrada_ajustada,
        "stop_ajustado": stop_ajustado,
        "distancia_pct": distancia_pct,
        "preco_precision": price_precision,
        "quantidade_precision": quantity_precision,
        "exchange_info_ok": bool(info.get("exchange_info_ok")),
    }


def registrar_bloqueio(
    symbol: str,
    motivo: str,
    capital: float,
    risco_pct: float,
    entrada: float,
    stop: float,
    **kwargs,
) -> None:
    try:
        from storage import log_decisao

        log_decisao(
            symbol=symbol,
            modo="RISK_MANAGER",
            decisao="BLOQUEADO_POR_RISCO",
            motivo=motivo,
            preco=entrada,
            regime=kwargs.get("regime", "N/A"),
            adx=kwargs.get("adx", 0.0),
            volume_status=kwargs.get("volume_status", "N/A"),
            bloqueado_por="RISK_MANAGER",
            fonte_dados=kwargs.get("fonte_dados", "N/A"),
            strategy_version=STRATEGY_VERSION,
        )
    except Exception as exc:
        logger.warning("Não foi possível registrar bloqueio no log: %s", exc)


def validar_e_calcular(
    capital: float,
    risco_pct: float,
    entrada: float,
    stop: float,
    symbol: str = "BTCUSDT",
    alavancagem: float = DEFAULT_MAX_LEVERAGE,
    trades_abertos: Optional[list] = None,
    perdas_hoje: float = 0.0,
    trades_hoje: int = 0,
    perdas_consecutivas: int = 0,
    registrar_bloqueio_flag: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    info = _buscar_exchange_info(symbol)
    if not info.get("exchange_info_ok"):
        resultado_bloqueado = {
            "aprovado": False,
            "motivo": "Falha ao validar regras da exchange. Trade bloqueado por segurança.",
            "quantidade": 0.0,
            "valor_arriscado": capital * (risco_pct / 100),
            "valor_nocional": 0.0,
            "margem_necessaria": 0.0,
            "alavancagem": alavancagem,
            "risco_pct": risco_pct,
            "entrada_ajustada": entrada,
            "stop_ajustado": stop,
            "distancia_pct": None,
            "preco_precision": info.get("price_precision", 2),
            "quantidade_precision": info.get("quantity_precision", 3),
            "exchange_info_ok": False,
        }
        if registrar_bloqueio_flag:
            registrar_bloqueio(
                symbol=symbol,
                motivo=resultado_bloqueado["motivo"],
                capital=capital,
                risco_pct=risco_pct,
                entrada=entrada,
                stop=stop,
                regime=kwargs.get("regime"),
                adx=kwargs.get("adx"),
                volume_status=kwargs.get("volume_status"),
                fonte_dados=kwargs.get("fonte_dados"),
            )
        return resultado_bloqueado

    resultado = calcular_posicao(
        capital=capital,
        risco_pct=risco_pct,
        entrada=entrada,
        stop=stop,
        symbol=symbol,
        alavancagem=alavancagem,
        trades_abertos=trades_abertos,
        perdas_hoje=perdas_hoje,
        trades_hoje=trades_hoje,
        perdas_consecutivas=perdas_consecutivas,
        exposure_limit_pct=kwargs.get("exposure_limit_pct", DEFAULT_MAX_EXPOSURE_PCT),
        max_daily_loss_pct=kwargs.get("max_daily_loss_pct", DEFAULT_MAX_DAILY_LOSS_PCT),
        max_consecutive_losses=kwargs.get("max_consecutive_losses", DEFAULT_MAX_CONSECUTIVE_LOSSES),
        max_trades_per_day=kwargs.get("max_trades_per_day", DEFAULT_MAX_TRADES_PER_DAY),
        min_distance_pct=kwargs.get("min_distance_pct", DEFAULT_MIN_DISTANCE_PCT),
        max_distance_pct=kwargs.get("max_distance_pct", DEFAULT_MAX_DISTANCE_PCT),
    )

    if not resultado.get("aprovado") and registrar_bloqueio_flag:
        registrar_bloqueio(
            symbol=symbol,
            motivo=resultado.get("motivo", "Bloqueado por risco"),
            capital=capital,
            risco_pct=risco_pct,
            entrada=entrada,
            stop=stop,
            regime=kwargs.get("regime"),
            adx=kwargs.get("adx"),
            volume_status=kwargs.get("volume_status"),
            fonte_dados=kwargs.get("fonte_dados"),
        )

    return resultado


def calcular_tamanho_posicao(capital, risco_percentual, entrada, stop):
    """
    Compatibilidade com o bot atual.
    Retorna (quantidade, valor_arriscado).
    """
    valor_arriscado = capital * (risco_percentual / 100)
    distancia_stop = abs(entrada - stop)
    if distancia_stop <= 0:
        return 0.0, valor_arriscado
    quantidade = valor_arriscado / distancia_stop
    return quantidade, valor_arriscado


def verificar_limite_diario(capital, perdas_hoje, max_perda_diaria_percentual=2):
    limite_diario = capital * (max_perda_diaria_percentual / 100)
    return perdas_hoje > limite_diario


def verificar_sequencia_perdas(historico, max_perdas_consecutivas=3):
    perdas_consecutivas = 0
    for item in reversed(list(historico)):
        is_perda = item in ("PERDA", "LOSS", False, 0)
        if is_perda:
            perdas_consecutivas += 1
            if perdas_consecutivas >= max_perdas_consecutivas:
                return True
        else:
            break
    return False
