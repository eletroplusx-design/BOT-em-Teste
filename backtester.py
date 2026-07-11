import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from backtesting import BacktestConfig, LeakFreeBacktestEngine, dataframe_to_candles

from decisor import (
    extrair_fvg_bearish_acima,
    extrair_fvg_bullish_abaixo,
    extrair_swing_high_low,
)
from regime_classifier import classificar_regime
from risk_manager import calcular_tamanho_posicao


ROOT_DIR = Path(__file__).resolve().parent
REPORT_PATH = ROOT_DIR / "backtest_report.json"
VARIANTES_REPORT_PATH = ROOT_DIR / "backtest_variantes.json"
TRADES_CSV_PATH = ROOT_DIR / "trades_backtest.csv"
FILTROS_ENTRADA_REPORT_PATH = ROOT_DIR / "backtest_filters_entrada.json"
MULTI_ATIVOS_REPORT_PATH = ROOT_DIR / "backtest_multi_ativos.json"
OTIMIZACAO_SOL_PATH = ROOT_DIR / "otimizacao_sol.json"
OOS_SOL_PATH = ROOT_DIR / "oos_sol.json"
WALKFORWARD_SOL_PATH = ROOT_DIR / "walkforward_sol.json"


def executar_backtest_leak_free(df, strategy_callback, *, symbol="BTCUSDT", interval="1h", config=None):
    candles = dataframe_to_candles(df, symbol=symbol, interval=interval)
    engine = LeakFreeBacktestEngine(config or BacktestConfig(symbol=symbol, interval=interval))
    return engine.run(candles, strategy_callback).to_dict()


def baixar_dados_historicos(symbol="BTCUSDT", intervalo="1h", limite=2000):
    """
    Baixa candles históricos da Binance e retorna um DataFrame com OHLCV.
    """
    url = "https://api.binance.com/api/v3/klines"
    limite_api = min(limite, 1000)
    inicio = datetime.now(timezone.utc) - timedelta(days=180)
    start_time = int(inicio.timestamp() * 1000)
    dados = []

    while True:
        params = {
            "symbol": symbol,
            "interval": intervalo,
            "limit": limite_api,
            "startTime": start_time,
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break

        dados.extend(batch)
        if len(batch) < limite_api:
            break

        start_time = batch[-1][0] + 1

    if not dados:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    colunas = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_asset_volume",
        "number_of_trades",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
        "ignore",
    ]
    df = pd.DataFrame(dados, columns=colunas)
    for coluna in ("open", "high", "low", "close", "volume"):
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    resultado = df[["open_time", "close_time", "open", "high", "low", "close", "volume"]].copy()
    resultado.attrs["fonte_dados"] = "BINANCE"
    return resultado


def _calcular_atr(df, periodo=14):
    max_min = df["high"] - df["low"]
    max_fech_ant = (df["high"] - df["close"].shift(1)).abs()
    min_fech_ant = (df["low"] - df["close"].shift(1)).abs()
    true_range = pd.concat([max_min, max_fech_ant, min_fech_ant], axis=1).max(axis=1)
    return true_range.rolling(window=periodo).mean().iloc[-1]


def _calcular_volume_medio(df, periodo=20):
    volume_medio = df["volume"].rolling(window=periodo).mean().iloc[-1]
    return volume_medio


def _fvg_foi_tocado(df, zona_inferior, zona_superior, candles=10):
    janela = df.tail(candles)
    for _, candle in janela.iterrows():
        if float(candle["high"]) >= zona_inferior and float(candle["low"]) <= zona_superior:
            return True
    return False


def _simular_decisao(
    df,
    volume_alto_multiplicador=1.8,
    volume_minimo_multiplicador=None,
    exigir_rr_minimo=True,
    somente_bear=False,
    regime_modo=None,
    exigir_fvg_nao_tocado=False,
    lookback_fvg=10,
):
    """
    Replica a lógica principal do decisor.py sem dependências externas de rede.
    """
    if len(df) < 200:
        return {
            "decisao": "AGUARDAR",
            "entrada": df["close"].iloc[-1],
            "stop_loss": None,
            "take_profit": None,
            "rr": None,
            "direcao": None,
            "motivo": "Dados insuficientes para regime.",
            "volume_status": "INDETERMINADO",
        }

    df = df.copy()
    preco_atual = float(df["close"].iloc[-1])
    volume_atual = float(df["volume"].iloc[-1])
    atr = _calcular_atr(df, 14)
    volume_medio = _calcular_volume_medio(df, 20)
    regime_info = classificar_regime(df)
    regime = regime_info["regime"]

    if volume_medio is not None and not pd.isna(volume_medio) and volume_medio > 0:
        razao_volume = volume_atual / volume_medio
        if volume_minimo_multiplicador is not None:
            if razao_volume < volume_minimo_multiplicador:
                resultado = {
                    "decisao": "AGUARDAR",
                    "score": 0,
                    "entrada": preco_atual,
                    "stop_loss": None,
                    "take_profit": None,
                    "risco": None,
                    "recompensa": None,
                    "rr": None,
                    "motivo": "Volume abaixo do filtro minimo.",
                    "zona_entrada_ideal": None,
                    "volume_status": "BAIXO",
                    "volume_atual": volume_atual,
                    "volume_medio": volume_medio,
                    "regime": regime,
                    "direcao": None,
                }
                return resultado
            status_volume = "ALTO"
            ajuste_score_volume = 2 if razao_volume >= volume_alto_multiplicador else 0
        else:
            if razao_volume > volume_alto_multiplicador:
                status_volume = "ALTO"
                ajuste_score_volume = 2
            elif razao_volume < 0.6:
                status_volume = "BAIXO"
                ajuste_score_volume = -2
            else:
                status_volume = "NEUTRO"
                ajuste_score_volume = 0
    else:
        status_volume = "INDETERMINADO"
        ajuste_score_volume = 0

    resultado = {
        "decisao": "AGUARDAR",
        "score": 0,
        "entrada": preco_atual,
        "stop_loss": None,
        "take_profit": None,
        "risco": None,
        "recompensa": None,
        "rr": None,
        "motivo": "",
        "zona_entrada_ideal": None,
        "volume_status": status_volume,
        "volume_atual": volume_atual,
        "volume_medio": volume_medio,
        "regime": regime,
        "direcao": None,
    }

    if regime_modo is None:
        regime_modo = "bear_only" if somente_bear else "bull_bear"

    if pd.isna(atr) or regime == "INDEFINIDO":
        resultado["motivo"] = "Regime lateral/indefinido."
        return resultado

    if regime_modo == "bear_only" and regime != "BEAR":
        resultado["motivo"] = "Filtro de regime ativo: apenas BEAR."
        return resultado
    if regime_modo == "bull_only" and regime != "BULL":
        resultado["motivo"] = "Filtro de regime ativo: apenas BULL."
        return resultado
    if regime_modo == "bull_bear" and regime not in ("BULL", "BEAR"):
        resultado["motivo"] = "Filtro de regime ativo: BULL e BEAR apenas."
        return resultado

    topo, fundo = extrair_swing_high_low(df, 50)
    amplitude = topo - fundo

    if regime == "BULL":
        fvg = extrair_fvg_bearish_acima(df, preco_atual)
        if fvg is None:
            resultado["motivo"] = "Nenhum FVG Bearish acima do preço."
            return resultado

        fvg_low, fvg_high = fvg
        if exigir_fvg_nao_tocado and _fvg_foi_tocado(df, min(fvg_low, fvg_high), max(fvg_low, fvg_high), lookback_fvg):
            resultado["motivo"] = "FVG ja tocado nos ultimos candles."
            return resultado
        entrada = preco_atual
        stop_loss = min(fundo, entrada - 1.5 * atr) if not pd.isna(fundo) else entrada - 1.5 * atr
        take_profit = fvg_high
        risco = entrada - stop_loss
        recompensa = take_profit - entrada
        rr = recompensa / risco if risco > 0 else 0
        score = min(10, 5 + ajuste_score_volume)

        if status_volume == "BAIXO":
            resultado["decisao"] = "AGUARDAR (Volume Baixo)"
            resultado["motivo"] = "Volume baixo."
            return resultado

        if exigir_rr_minimo and rr < 1.5:
            resultado["motivo"] = "R/R abaixo de 1.5."
            return resultado

        resultado.update(
            {
                "decisao": "COMPRA",
                "score": score,
                "entrada": entrada,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "risco": risco,
                "recompensa": recompensa,
                "rr": rr,
                "motivo": "Tendência de alta com FVG Bearish acima.",
                "direcao": "COMPRA",
                "zona_entrada_ideal": topo - amplitude * 0.618,
                "fvg_target": fvg_high,
            }
        )
        return resultado

    if regime == "BEAR":
        fvg = extrair_fvg_bullish_abaixo(df, preco_atual)
        if fvg is None:
            resultado["motivo"] = "Nenhum FVG Bullish abaixo do preço."
            return resultado

        fvg_low, fvg_high = fvg
        if exigir_fvg_nao_tocado and _fvg_foi_tocado(df, min(fvg_low, fvg_high), max(fvg_low, fvg_high), lookback_fvg):
            resultado["motivo"] = "FVG ja tocado nos ultimos candles."
            return resultado
        entrada = preco_atual
        stop_loss = min(topo, entrada + 1.5 * atr) if not pd.isna(topo) and topo > entrada else entrada + 1.5 * atr
        take_profit = fvg_high
        risco = stop_loss - entrada
        recompensa = entrada - take_profit
        rr = recompensa / risco if risco > 0 else 0
        score = min(10, 5 + ajuste_score_volume)

        if status_volume == "BAIXO":
            resultado["decisao"] = "AGUARDAR (Volume Baixo)"
            resultado["motivo"] = "Volume baixo."
            return resultado

        if exigir_rr_minimo and rr < 1.5:
            resultado["motivo"] = "R/R abaixo de 1.5."
            return resultado

        resultado.update(
            {
                "decisao": "VENDA",
                "score": score,
                "entrada": entrada,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "risco": risco,
                "recompensa": recompensa,
                "rr": rr,
                "motivo": "Tendência de baixa com FVG Bullish abaixo.",
                "direcao": "VENDA",
                "zona_entrada_ideal": fundo + amplitude * 0.618,
                "fvg_target": fvg_high,
            }
        )
        return resultado

    resultado["motivo"] = "Regime não identificado."
    return resultado


def configurar_estrategia(variante):
    variantes = {
        "A": {"stop_multiplier": 1.0, "tp_multiplier": 1.5, "tp_parcial": False, "trailing": False},
        "B": {"stop_multiplier": 1.5, "tp_multiplier": 2.0, "tp_parcial": False, "trailing": False},
        "C": {"stop_multiplier": 1.0, "tp_multiplier": 1.5, "tp_parcial": True, "trailing": True},
        "D": {"stop_multiplier": 1.5, "tp_multiplier": 1.5, "tp_parcial": False, "trailing": False},
    }
    return variantes.get(str(variante).upper(), variantes["A"]).copy()


def _calcular_preco_trailing_ativacao(entrada, tp_level):
    return entrada + ((tp_level - entrada) * 0.5)


def _atualizar_stop_trailing(direcao, extremo, stop_dist):
    if direcao == "COMPRA":
        return extremo - stop_dist
    return extremo + stop_dist


def _resultado_saida(qty, entrada_preco, exit_price, direcao, taxa):
    if direcao == "COMPRA":
        gross_pnl = qty * (exit_price - entrada_preco)
    else:
        gross_pnl = qty * (entrada_preco - exit_price)
    exit_fee = qty * exit_price * taxa
    return gross_pnl - exit_fee


def _aplicar_slippage(preco, slippage, direcao, tipo):
    if direcao == "COMPRA":
        if tipo == "entrada":
            return preco * (1 + slippage)
        return preco * (1 - slippage)
    if tipo == "entrada":
        return preco * (1 - slippage)
    return preco * (1 + slippage)


def _simular_trade_variante(
    df,
    start_idx,
    sinal,
    capital_atual,
    risco_percentual,
    estrategia,
    slippage,
    taxa,
):
    janela = df.iloc[: start_idx + 1].copy()
    atr = _calcular_atr(janela, 14)
    if pd.isna(atr):
        return None

    direcao = sinal.get("direcao")
    if direcao not in ("COMPRA", "VENDA"):
        return None

    sign = 1 if direcao == "COMPRA" else -1
    candle_entrada = df.iloc[start_idx + 1]
    entrada_preco = _aplicar_slippage(float(candle_entrada["open"]), slippage, direcao, "entrada")
    stop_dist = float(estrategia["stop_multiplier"]) * float(atr)
    stop_loss = entrada_preco - sign * stop_dist
    tp_dist = float(estrategia["tp_multiplier"]) * stop_dist
    tp_level = entrada_preco + sign * tp_dist
    quantidade, valor_arriscado = calcular_tamanho_posicao(
        capital_atual, risco_percentual, entrada_preco, stop_loss
    )

    if quantidade <= 0:
        return None

    entry_fee = quantidade * entrada_preco * taxa
    realized_pnl = -entry_fee
    remaining_qty = quantidade
    partial_qty = quantidade * 0.5 if estrategia["tp_parcial"] else 0.0
    partial_done = False
    trail_active = False
    trail_extreme = entrada_preco
    trailing_stop = None
    trailing_activation = _calcular_preco_trailing_ativacao(entrada_preco, tp_level)
    fvg_target = sinal.get("fvg_target") or sinal.get("take_profit") or tp_level
    exit_index = len(df) - 1
    exit_reason = "FINAL_CLOSE"
    partial_exit_reais = 0.0
    remaining_exit_reais = 0.0
    partial_exit_price = None
    final_exit_price = None

    for j in range(start_idx + 1, len(df)):
        candle = df.iloc[j]
        high = float(candle["high"])
        low = float(candle["low"])

        if estrategia["tp_parcial"] and not partial_done:
            if direcao == "COMPRA":
                if low <= stop_loss:
                    final_exit_price = _aplicar_slippage(stop_loss, slippage, direcao, "saida")
                    remaining_exit_reais = _resultado_saida(quantidade, entrada_preco, final_exit_price, direcao, taxa)
                    realized_pnl += remaining_exit_reais
                    exit_index = j
                    exit_reason = "STOP"
                    break
                if high >= fvg_target:
                    partial_exit_price = _aplicar_slippage(float(fvg_target), slippage, direcao, "saida")
                    partial_exit_reais = _resultado_saida(partial_qty, entrada_preco, partial_exit_price, direcao, taxa)
                    realized_pnl += partial_exit_reais
                    remaining_qty = quantidade - partial_qty
                    partial_done = True
                    continue
            else:
                if high >= stop_loss:
                    final_exit_price = _aplicar_slippage(stop_loss, slippage, direcao, "saida")
                    remaining_exit_reais = _resultado_saida(quantidade, entrada_preco, final_exit_price, direcao, taxa)
                    realized_pnl += remaining_exit_reais
                    exit_index = j
                    exit_reason = "STOP"
                    break
                if low <= fvg_target:
                    partial_exit_price = _aplicar_slippage(float(fvg_target), slippage, direcao, "saida")
                    partial_exit_reais = _resultado_saida(partial_qty, entrada_preco, partial_exit_price, direcao, taxa)
                    realized_pnl += partial_exit_reais
                    remaining_qty = quantidade - partial_qty
                    partial_done = True
                    continue

        if estrategia["tp_parcial"] and partial_done:
            if direcao == "COMPRA":
                if low <= stop_loss:
                    final_exit_price = _aplicar_slippage(stop_loss, slippage, direcao, "saida")
                    remaining_exit_reais = _resultado_saida(remaining_qty, entrada_preco, final_exit_price, direcao, taxa)
                    realized_pnl += remaining_exit_reais
                    exit_index = j
                    exit_reason = "STOP_AFTER_PARTIAL"
                    break
                if not trail_active and high >= trailing_activation:
                    trail_active = True
                    trail_extreme = high
                    trailing_stop = _atualizar_stop_trailing(direcao, trail_extreme, stop_dist)
                elif trail_active:
                    trail_extreme = max(trail_extreme, high)
                    trailing_stop = _atualizar_stop_trailing(direcao, trail_extreme, stop_dist)
                if trail_active:
                    effective_stop = max(stop_loss, trailing_stop)
                    if low <= effective_stop:
                        final_exit_price = _aplicar_slippage(effective_stop, slippage, direcao, "saida")
                        remaining_exit_reais = _resultado_saida(remaining_qty, entrada_preco, final_exit_price, direcao, taxa)
                        realized_pnl += remaining_exit_reais
                        exit_index = j
                        exit_reason = "TRAILING_STOP"
                        break
            else:
                if high >= stop_loss:
                    final_exit_price = _aplicar_slippage(stop_loss, slippage, direcao, "saida")
                    remaining_exit_reais = _resultado_saida(remaining_qty, entrada_preco, final_exit_price, direcao, taxa)
                    realized_pnl += remaining_exit_reais
                    exit_index = j
                    exit_reason = "STOP_AFTER_PARTIAL"
                    break
                if not trail_active and low <= trailing_activation:
                    trail_active = True
                    trail_extreme = low
                    trailing_stop = _atualizar_stop_trailing(direcao, trail_extreme, stop_dist)
                elif trail_active:
                    trail_extreme = min(trail_extreme, low)
                    trailing_stop = _atualizar_stop_trailing(direcao, trail_extreme, stop_dist)
                if trail_active:
                    effective_stop = min(stop_loss, trailing_stop)
                    if high >= effective_stop:
                        final_exit_price = _aplicar_slippage(effective_stop, slippage, direcao, "saida")
                        remaining_exit_reais = _resultado_saida(remaining_qty, entrada_preco, final_exit_price, direcao, taxa)
                        realized_pnl += remaining_exit_reais
                        exit_index = j
                        exit_reason = "TRAILING_STOP"
                        break
            continue

        if not estrategia["tp_parcial"]:
            if direcao == "COMPRA":
                if low <= stop_loss:
                    final_exit_price = _aplicar_slippage(stop_loss, slippage, direcao, "saida")
                    remaining_exit_reais = _resultado_saida(quantidade, entrada_preco, final_exit_price, direcao, taxa)
                    realized_pnl += remaining_exit_reais
                    exit_index = j
                    exit_reason = "STOP"
                    break
                if estrategia["trailing"]:
                    if not trail_active and high >= trailing_activation:
                        trail_active = True
                        trail_extreme = high
                        trailing_stop = _atualizar_stop_trailing(direcao, trail_extreme, stop_dist)
                    elif trail_active:
                        trail_extreme = max(trail_extreme, high)
                        trailing_stop = _atualizar_stop_trailing(direcao, trail_extreme, stop_dist)
                    if trail_active:
                        effective_stop = max(stop_loss, trailing_stop)
                        if low <= effective_stop:
                            final_exit_price = _aplicar_slippage(effective_stop, slippage, direcao, "saida")
                            remaining_exit_reais = _resultado_saida(quantidade, entrada_preco, final_exit_price, direcao, taxa)
                            realized_pnl += remaining_exit_reais
                            exit_index = j
                            exit_reason = "TRAILING_STOP"
                            break
                else:
                    if high >= tp_level:
                        final_exit_price = _aplicar_slippage(tp_level, slippage, direcao, "saida")
                        remaining_exit_reais = _resultado_saida(quantidade, entrada_preco, final_exit_price, direcao, taxa)
                        realized_pnl += remaining_exit_reais
                        exit_index = j
                        exit_reason = "TAKE_PROFIT"
                        break
            else:
                if high >= stop_loss:
                    final_exit_price = _aplicar_slippage(stop_loss, slippage, direcao, "saida")
                    remaining_exit_reais = _resultado_saida(quantidade, entrada_preco, final_exit_price, direcao, taxa)
                    realized_pnl += remaining_exit_reais
                    exit_index = j
                    exit_reason = "STOP"
                    break
                if estrategia["trailing"]:
                    if not trail_active and low <= trailing_activation:
                        trail_active = True
                        trail_extreme = low
                        trailing_stop = _atualizar_stop_trailing(direcao, trail_extreme, stop_dist)
                    elif trail_active:
                        trail_extreme = min(trail_extreme, low)
                        trailing_stop = _atualizar_stop_trailing(direcao, trail_extreme, stop_dist)
                    if trail_active:
                        effective_stop = min(stop_loss, trailing_stop)
                        if high >= effective_stop:
                            final_exit_price = _aplicar_slippage(effective_stop, slippage, direcao, "saida")
                            remaining_exit_reais = _resultado_saida(quantidade, entrada_preco, final_exit_price, direcao, taxa)
                            realized_pnl += remaining_exit_reais
                            exit_index = j
                            exit_reason = "TRAILING_STOP"
                            break
                else:
                    if low <= tp_level:
                        final_exit_price = _aplicar_slippage(tp_level, slippage, direcao, "saida")
                        remaining_exit_reais = _resultado_saida(quantidade, entrada_preco, final_exit_price, direcao, taxa)
                        realized_pnl += remaining_exit_reais
                        exit_index = j
                        exit_reason = "TAKE_PROFIT"
                        break

    if final_exit_price is None:
        close_price = float(df.iloc[-1]["close"])
        final_exit_price = _aplicar_slippage(close_price, slippage, direcao, "saida")
        qty_final = remaining_qty if estrategia["tp_parcial"] else quantidade
        remaining_exit_reais = _resultado_saida(qty_final, entrada_preco, final_exit_price, direcao, taxa)
        realized_pnl += remaining_exit_reais
        exit_reason = "FINAL_CLOSE"

    net_pnl = realized_pnl
    resultado_percentual = (net_pnl / capital_atual) * 100 if capital_atual > 0 else 0.0
    resultado_trade = "GANHO" if net_pnl > 0 else "PERDA" if net_pnl < 0 else "BREAKEVEN"
    realized_rr = net_pnl / valor_arriscado if valor_arriscado > 0 else 0.0

    trade = {
        "data_entrada": str(df.iloc[start_idx + 1]["open_time"]),
        "entrada_time": str(df.iloc[start_idx + 1]["open_time"]),
        "saida_time": str(df.iloc[exit_index]["close_time"]),
        "direcao": direcao,
        "regime": sinal.get("regime", "INDEFINIDO"),
        "entrada_preco": entrada_preco,
        "stop_loss": stop_loss,
        "take_profit": tp_level,
        "fvg_target": fvg_target,
        "entrada": entrada_preco,
        "stop": stop_loss,
        "take": tp_level,
        "quantidade": quantidade,
        "valor_arriscado": valor_arriscado,
        "gross_pnl": net_pnl + entry_fee,
        "entry_fee": entry_fee,
        "exit_fee": 0.0,
        "net_pnl": net_pnl,
        "resultado_percentual": resultado_percentual,
        "resultado_reais": net_pnl,
        "resultado": resultado_trade,
        "exit_reason": exit_reason,
        "realized_rr": realized_rr,
        "equity_after": None,
        "drawdown_percent": None,
        "score": sinal.get("score", 0),
        "planned_rr": sinal.get("rr"),
        "volume_status": sinal.get("volume_status"),
        "stop_multiplier": estrategia["stop_multiplier"],
        "tp_multiplier": estrategia["tp_multiplier"],
        "tp_parcial": estrategia["tp_parcial"],
        "trailing": estrategia["trailing"],
        "partial_exit_reais": partial_exit_reais,
        "remaining_exit_reais": remaining_exit_reais,
        "partial_exit_price": partial_exit_price,
        "final_exit_price": final_exit_price,
    }
    return trade, exit_index


def executar_backtest(
    df,
    capital_inicial=10000,
    risco_percentual=1.0,
    slippage=0.0005,
    taxa=0.0004,
    variante="A",
):
    """
    Executa o backtest para uma variante específica de saída.
    """
    estrategia = configurar_estrategia(variante)

    if df is None or df.empty:
        return {
            "variante": str(variante).upper(),
            "estrategia": estrategia,
            "trades": [],
            "capital_inicial": capital_inicial,
            "capital_final": capital_inicial,
            "equity_curve": [capital_inicial],
            "summary": {
                "total_trades": 0,
                "win_rate": 0.0,
                "lucro_total_percent": 0.0,
                "lucro_total_valor": 0.0,
                "profit_factor": 0.0,
                "drawdown_max_percent": 0.0,
                "media_rr": 0.0,
                "sequencia_maxima_perdas": 0,
                "expectativa_matematica_percentual": 0.0,
                "regimes": {},
            },
        }

    trades = []
    capital = float(capital_inicial)
    equity_curve = [capital]
    peak = capital
    max_drawdown = 0.0
    historico_resultados = []
    trades_por_regime = {"BULL": [], "BEAR": [], "CHOP": [], "INDEFINIDO": []}

    i = 200
    while i < len(df) - 1:
        janela = df.iloc[: i + 1].copy()
        sinal = _simular_decisao(janela)
        direcao = sinal.get("direcao")
        if direcao not in ("COMPRA", "VENDA"):
            i += 1
            continue

        trade_result = _simular_trade_variante(
            df,
            i,
            sinal,
            capital,
            risco_percentual,
            estrategia,
            slippage,
            taxa,
        )
        if trade_result is None:
            i += 1
            continue

        trade, exit_index = trade_result
        capital += trade["net_pnl"]
        equity_curve.append(capital)
        peak = max(peak, capital)
        trade["equity_after"] = capital
        trade["drawdown_percent"] = ((peak - capital) / peak) * 100 if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, trade["drawdown_percent"])
        historico_resultados.append(trade["resultado"])
        trades.append(trade)
        trades_por_regime.setdefault(trade["regime"], []).append(trade)
        i = exit_index + 1

    gross_profit = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
    gross_loss = abs(sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0))
    total_net = sum(t["net_pnl"] for t in trades)
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
    total_trades = len(trades)
    wins = sum(1 for t in trades if t["resultado"] == "GANHO")
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    media_rr = sum((t["realized_rr"] for t in trades), 0.0) / total_trades if total_trades > 0 else 0.0
    ganho_medio = (
        sum(t["resultado_percentual"] for t in trades if t["resultado_percentual"] > 0) / wins
        if wins > 0
        else 0.0
    )
    perdas = total_trades - wins
    perda_media = (
        abs(sum(t["resultado_percentual"] for t in trades if t["resultado_percentual"] < 0)) / perdas
        if perdas > 0
        else 0.0
    )
    expectativa_matematica = (win_rate / 100.0) * ganho_medio - (1 - (win_rate / 100.0)) * perda_media

    regimes_summary = {}
    for regime_nome, trades_regime in trades_por_regime.items():
        total_regime = len(trades_regime)
        wins_regime = sum(1 for t in trades_regime if t["resultado"] == "GANHO")
        gross_profit_regime = sum(t["net_pnl"] for t in trades_regime if t["net_pnl"] > 0)
        gross_loss_regime = abs(sum(t["net_pnl"] for t in trades_regime if t["net_pnl"] < 0))
        profit_factor_regime = (
            gross_profit_regime / gross_loss_regime
            if gross_loss_regime > 0
            else float("inf") if gross_profit_regime > 0
            else 0.0
        )
        media_rr_regime = (
            sum(t["realized_rr"] for t in trades_regime) / total_regime if total_regime > 0 else 0.0
        )
        regimes_summary[regime_nome] = {
            "total_trades": total_regime,
            "win_rate": round((wins_regime / total_regime * 100), 2) if total_regime > 0 else 0.0,
            "profit_factor": round(profit_factor_regime, 4) if profit_factor_regime != float("inf") else "inf",
            "media_rr": round(media_rr_regime, 3),
        }

    summary = {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 2),
        "lucro_total_percent": round((total_net / capital_inicial) * 100, 2) if capital_inicial else 0.0,
        "lucro_total_valor": round(total_net, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
        "drawdown_max_percent": round(max_drawdown, 2),
        "media_rr": round(media_rr, 3),
        "sequencia_maxima_perdas": _sequencia_maxima_perdas(historico_resultados),
        "expectativa_matematica_percentual": round(expectativa_matematica, 3),
        "regimes": regimes_summary,
    }

    return {
        "variante": str(variante).upper(),
        "estrategia": estrategia,
        "trades": trades,
        "capital_inicial": capital_inicial,
        "capital_final": round(capital, 2),
        "equity_curve": equity_curve,
        "trades_por_regime": trades_por_regime,
        "summary": summary,
    }


def executar_backtests_variantes(df, capital_inicial=10000, risco_percentual=1.0, slippage=0.0005, taxa=0.0004):
    resultados = {}
    for variante in ("A", "B", "C", "D"):
        resultados[variante] = executar_backtest(
            df,
            capital_inicial=capital_inicial,
            risco_percentual=risco_percentual,
            slippage=slippage,
            taxa=taxa,
            variante=variante,
        )
    return resultados


def construir_relatorio_variantes(resultados_variantes):
    variantes_relatorio = {}
    comparativo = {
        "melhor_profit_factor": None,
        "melhor_media_rr": None,
        "melhor_expectativa_matematica": None,
    }

    for variante, resultado in resultados_variantes.items():
        summary = resultado["summary"]
        variantes_relatorio[variante] = {
            "configuracao": resultado["estrategia"],
            "profit_factor": summary["profit_factor"],
            "win_rate": summary["win_rate"],
            "media_rr": summary["media_rr"],
            "lucro_total_percent": summary["lucro_total_percent"],
            "drawdown_max_percent": summary["drawdown_max_percent"],
            "expectativa_matematica_percentual": summary["expectativa_matematica_percentual"],
            "total_trades": summary["total_trades"],
            "capital_final": resultado["capital_final"],
            "regimes": summary["regimes"],
        }

    def _valor_metric(metric_name, variante_nome):
        valor = variantes_relatorio[variante_nome][metric_name]
        return float("-inf") if valor == "inf" else float(valor)

    if variantes_relatorio:
        comparativo["melhor_profit_factor"] = max(
            variantes_relatorio,
            key=lambda v: _valor_metric("profit_factor", v),
        )
        comparativo["melhor_media_rr"] = max(
            variantes_relatorio,
            key=lambda v: _valor_metric("media_rr", v),
        )
        comparativo["melhor_expectativa_matematica"] = max(
            variantes_relatorio,
            key=lambda v: _valor_metric("expectativa_matematica_percentual", v),
        )

    return {
        "variantes": variantes_relatorio,
        "comparativo": comparativo,
    }


def _nome_configuracao_entrada(config):
    return (
        f"bear_only={config['somente_bear']}"
        f"|fvg_nao_tocado={config['exigir_fvg_nao_tocado']}"
        f"|volume>={config['volume_alto_multiplicador']}x"
        f"|rr_minimo={config['exigir_rr_minimo']}"
    )


def executar_backtest_filtros_entrada(
    df,
    symbol="BTCUSDT",
    capital_inicial=10000,
    risco_percentual=1.0,
    slippage=0.0005,
    taxa=0.0004,
    volume_alto_multiplicador=1.8,
    volume_minimo_multiplicador=None,
    exigir_fvg_nao_tocado=False,
    somente_bear=True,
    regime_modo=None,
    exigir_rr_minimo=False,
    lookback_fvg=10,
):
    estrategia = configurar_estrategia("D")

    if df is None or df.empty:
        return {
            "symbol": symbol,
            "estrategia": estrategia,
            "filtros_entrada": {
                "somente_bear": somente_bear,
                "regime_modo": regime_modo,
                "exigir_fvg_nao_tocado": exigir_fvg_nao_tocado,
                "volume_alto_multiplicador": volume_alto_multiplicador,
                "volume_minimo_multiplicador": volume_minimo_multiplicador,
                "exigir_rr_minimo": exigir_rr_minimo,
                "lookback_fvg": lookback_fvg,
            },
            "trades": [],
            "capital_inicial": capital_inicial,
            "capital_final": capital_inicial,
            "equity_curve": [capital_inicial],
            "summary": {
                "total_trades": 0,
                "win_rate": 0.0,
                "lucro_total_percent": 0.0,
                "lucro_total_valor": 0.0,
                "profit_factor": 0.0,
                "drawdown_max_percent": 0.0,
                "media_rr": 0.0,
                "sequencia_maxima_perdas": 0,
                "expectativa_matematica_percentual": 0.0,
                "regimes": {},
            },
        }

    trades = []
    capital = float(capital_inicial)
    equity_curve = [capital]
    peak = capital
    max_drawdown = 0.0
    historico_resultados = []
    trades_por_regime = {"BULL": [], "BEAR": [], "CHOP": [], "INDEFINIDO": []}

    i = 200
    while i < len(df) - 1:
        janela = df.iloc[: i + 1].copy()
        sinal = _simular_decisao(
            janela,
            volume_alto_multiplicador=volume_alto_multiplicador,
            volume_minimo_multiplicador=volume_minimo_multiplicador,
            exigir_rr_minimo=exigir_rr_minimo,
            somente_bear=somente_bear,
            regime_modo=regime_modo,
            exigir_fvg_nao_tocado=exigir_fvg_nao_tocado,
            lookback_fvg=lookback_fvg,
        )
        direcao = sinal.get("direcao")
        if direcao not in ("COMPRA", "VENDA"):
            i += 1
            continue

        trade_result = _simular_trade_variante(
            df,
            i,
            sinal,
            capital,
            risco_percentual,
            estrategia,
            slippage,
            taxa,
        )
        if trade_result is None:
            i += 1
            continue

        trade, exit_index = trade_result
        capital += trade["net_pnl"]
        equity_curve.append(capital)
        peak = max(peak, capital)
        trade["equity_after"] = capital
        trade["drawdown_percent"] = ((peak - capital) / peak) * 100 if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, trade["drawdown_percent"])
        historico_resultados.append(trade["resultado"])
        trades.append(trade)
        trades_por_regime.setdefault(trade["regime"], []).append(trade)
        i = exit_index + 1

    gross_profit = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
    gross_loss = abs(sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0))
    total_net = sum(t["net_pnl"] for t in trades)
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
    total_trades = len(trades)
    wins = sum(1 for t in trades if t["resultado"] == "GANHO")
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    media_rr = sum((t["realized_rr"] for t in trades), 0.0) / total_trades if total_trades > 0 else 0.0
    ganho_medio = (
        sum(t["resultado_percentual"] for t in trades if t["resultado_percentual"] > 0) / wins
        if wins > 0
        else 0.0
    )
    perdas = total_trades - wins
    perda_media = (
        abs(sum(t["resultado_percentual"] for t in trades if t["resultado_percentual"] < 0)) / perdas
        if perdas > 0
        else 0.0
    )
    expectativa_matematica = (win_rate / 100.0) * ganho_medio - (1 - (win_rate / 100.0)) * perda_media

    regimes_summary = {}
    for regime_nome, trades_regime in trades_por_regime.items():
        total_regime = len(trades_regime)
        wins_regime = sum(1 for t in trades_regime if t["resultado"] == "GANHO")
        gross_profit_regime = sum(t["net_pnl"] for t in trades_regime if t["net_pnl"] > 0)
        gross_loss_regime = abs(sum(t["net_pnl"] for t in trades_regime if t["net_pnl"] < 0))
        profit_factor_regime = (
            gross_profit_regime / gross_loss_regime
            if gross_loss_regime > 0
            else float("inf") if gross_profit_regime > 0
            else 0.0
        )
        media_rr_regime = (
            sum(t["realized_rr"] for t in trades_regime) / total_regime if total_regime > 0 else 0.0
        )
        regimes_summary[regime_nome] = {
            "total_trades": total_regime,
            "win_rate": round((wins_regime / total_regime * 100), 2) if total_regime > 0 else 0.0,
            "profit_factor": round(profit_factor_regime, 4) if profit_factor_regime != float("inf") else "inf",
            "media_rr": round(media_rr_regime, 3),
        }

    summary = {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 2),
        "lucro_total_percent": round((total_net / capital_inicial) * 100, 2) if capital_inicial else 0.0,
        "lucro_total_valor": round(total_net, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
        "drawdown_max_percent": round(max_drawdown, 2),
        "media_rr": round(media_rr, 3),
        "sequencia_maxima_perdas": _sequencia_maxima_perdas(historico_resultados),
        "expectativa_matematica_percentual": round(expectativa_matematica, 3),
        "regimes": regimes_summary,
    }

    return {
        "symbol": symbol,
        "estrategia": estrategia,
        "filtros_entrada": {
            "somente_bear": somente_bear,
            "regime_modo": regime_modo,
            "exigir_fvg_nao_tocado": exigir_fvg_nao_tocado,
            "volume_alto_multiplicador": volume_alto_multiplicador,
            "volume_minimo_multiplicador": volume_minimo_multiplicador,
            "exigir_rr_minimo": exigir_rr_minimo,
            "lookback_fvg": lookback_fvg,
        },
        "trades": trades,
        "capital_inicial": capital_inicial,
        "capital_final": round(capital, 2),
        "equity_curve": equity_curve,
        "trades_por_regime": trades_por_regime,
        "summary": summary,
    }


def executar_backtests_filtros_entrada(
    df,
    symbol="BTCUSDT",
    capital_inicial=10000,
    risco_percentual=1.0,
    slippage=0.0005,
    taxa=0.0004,
):
    resultados = {}
    for exigir_fvg_nao_tocado in (False, True):
        for volume_alto_multiplicador in (1.5, 1.2, 0.8):
            config = {
                "somente_bear": True,
                "exigir_fvg_nao_tocado": exigir_fvg_nao_tocado,
                "volume_alto_multiplicador": volume_alto_multiplicador,
                "exigir_rr_minimo": False,
            }
            chave = _nome_configuracao_entrada(config)
            resultados[chave] = executar_backtest_filtros_entrada(
                df,
                symbol=symbol,
                capital_inicial=capital_inicial,
                risco_percentual=risco_percentual,
                slippage=slippage,
                taxa=taxa,
                volume_alto_multiplicador=volume_alto_multiplicador,
                exigir_fvg_nao_tocado=exigir_fvg_nao_tocado,
                somente_bear=True,
                exigir_rr_minimo=False,
            )
    return resultados


def executar_backtest_multi_ativos(
    symbols,
    capital_inicial=10000,
    risco_percentual=1.0,
    slippage=0.0005,
    taxa=0.0004,
):
    resultados = {}
    for symbol in symbols:
        df = baixar_dados_historicos(symbol=symbol)
        resultados[symbol] = executar_backtests_filtros_entrada(
            df,
            symbol=symbol,
            capital_inicial=capital_inicial,
            risco_percentual=risco_percentual,
            slippage=slippage,
            taxa=taxa,
        )
    return resultados


def construir_relatorio_filtros_entrada(resultados_filtros):
    variacoes = {}
    comparativo = {
        "melhor_profit_factor": None,
        "melhor_expectativa_matematica": None,
    }

    for chave, resultado in resultados_filtros.items():
        summary = resultado["summary"]
        filtros = resultado["filtros_entrada"]
        variacoes[chave] = {
            "configuracao": filtros,
            "profit_factor": summary["profit_factor"],
            "win_rate": summary["win_rate"],
            "media_rr": summary["media_rr"],
            "lucro_total_percent": summary["lucro_total_percent"],
            "drawdown_max_percent": summary["drawdown_max_percent"],
            "expectativa_matematica_percentual": summary["expectativa_matematica_percentual"],
            "total_trades": summary["total_trades"],
            "capital_final": resultado["capital_final"],
            "regimes": summary["regimes"],
        }

    def _valor_metric(metric_name, chave_nome):
        valor = variacoes[chave_nome][metric_name]
        return float("-inf") if valor == "inf" else float(valor)

    if variacoes:
        comparativo["melhor_profit_factor"] = max(
            variacoes,
            key=lambda k: _valor_metric("profit_factor", k),
        )
        comparativo["melhor_expectativa_matematica"] = max(
            variacoes,
            key=lambda k: _valor_metric("expectativa_matematica_percentual", k),
        )

    melhor_chave = comparativo.get("melhor_profit_factor")
    melhor_resultado = resultados_filtros.get(melhor_chave, {}) if melhor_chave else {}
    return {
        "variacoes": variacoes,
        "comparativo": comparativo,
        "melhor_configuracao": {
            "chave": melhor_chave,
            "configuracao": variacoes.get(melhor_chave, {}).get("configuracao") if melhor_chave else None,
            "summary": melhor_resultado.get("summary"),
        },
    }


def construir_relatorio_multi_ativos(resultados_por_ativo):
    ativos_relatorio = {}
    comparativo = {
        "melhor_profit_factor": None,
        "melhor_win_rate": None,
        "melhor_lucro_total": None,
        "melhor_total_trades": None,
        "melhor_drawdown": None,
        "melhor_media_rr": None,
    }

    for symbol, resultados_filtros in resultados_por_ativo.items():
        melhor_chave = None
        melhor_pf = float("-inf")
        melhor_summary = None
        melhor_config = None
        for chave, resultado in resultados_filtros.items():
            summary = resultado["summary"]
            pf = summary["profit_factor"]
            pf_num = float("-inf") if pf == "inf" else float(pf)
            if pf_num > melhor_pf:
                melhor_pf = pf_num
                melhor_chave = chave
                melhor_summary = summary
                melhor_config = resultado["filtros_entrada"]

        ativos_relatorio[symbol] = {
            "melhor_configuracao": {
                "chave": melhor_chave,
                "configuracao": melhor_config,
            },
            "profit_factor": melhor_summary["profit_factor"] if melhor_summary else 0.0,
            "win_rate": melhor_summary["win_rate"] if melhor_summary else 0.0,
            "lucro_total_percent": melhor_summary["lucro_total_percent"] if melhor_summary else 0.0,
            "lucro_total_valor": melhor_summary["lucro_total_valor"] if melhor_summary else 0.0,
            "total_trades": melhor_summary["total_trades"] if melhor_summary else 0,
            "drawdown_max_percent": melhor_summary["drawdown_max_percent"] if melhor_summary else 0.0,
            "media_rr": melhor_summary["media_rr"] if melhor_summary else 0.0,
            "expectativa_matematica_percentual": melhor_summary["expectativa_matematica_percentual"] if melhor_summary else 0.0,
        }

    def _valor_metric(symbol_nome, metric_name):
        valor = ativos_relatorio[symbol_nome][metric_name]
        return float("-inf") if valor == "inf" else float(valor)

    if ativos_relatorio:
        comparativo["melhor_profit_factor"] = max(ativos_relatorio, key=lambda s: _valor_metric(s, "profit_factor"))
        comparativo["melhor_win_rate"] = max(ativos_relatorio, key=lambda s: _valor_metric(s, "win_rate"))
        comparativo["melhor_lucro_total"] = max(ativos_relatorio, key=lambda s: _valor_metric(s, "lucro_total_percent"))
        comparativo["melhor_total_trades"] = max(ativos_relatorio, key=lambda s: _valor_metric(s, "total_trades"))
        comparativo["melhor_drawdown"] = min(ativos_relatorio, key=lambda s: _valor_metric(s, "drawdown_max_percent"))
        comparativo["melhor_media_rr"] = max(ativos_relatorio, key=lambda s: _valor_metric(s, "media_rr"))

    return {
        "ativos": ativos_relatorio,
        "comparativo": comparativo,
    }


def _chave_otimizacao_sol(config):
    return (
        f"regime={config['regime_modo']}"
        f"|volume={config['volume_minimo_multiplicador'] if config['volume_minimo_multiplicador'] is not None else 'sem_filtro'}"
        f"|fvg={config['exigir_fvg_nao_tocado']}"
        f"|janela={config['lookback_fvg'] if config['lookback_fvg'] is not None else 'sem_filtro'}"
        f"|rr_min={config['exigir_rr_minimo']}"
    )


def _precomputar_contextos_otimizacao(df):
    if df is None or df.empty:
        return {}
    if len(df) < 20:
        return {}

    contextos = []
    try:
        coluna_tempo = "open_time" if "open_time" in df.columns else "timestamp" if "timestamp" in df.columns else None
        if coluna_tempo is None:
            return {}

        for i in range(200, len(df) - 1):
            janela = df.iloc[: i + 1].copy()
            regime_info = classificar_regime(janela)
            atr = _calcular_atr(janela, 14)
            volume_medio = _calcular_volume_medio(janela, 20)
            preco_atual = float(janela["close"].iloc[-1])
            volume_atual = float(janela["volume"].iloc[-1])
            topo, fundo = extrair_swing_high_low(janela, 50)
            fvg_bearish = extrair_fvg_bearish_acima(janela, preco_atual)
            fvg_bullish = extrair_fvg_bullish_abaixo(janela, preco_atual)
            tail = janela.tail(20)

            ultimo_tempo = janela.iloc[-1][coluna_tempo]
            if pd.isna(ultimo_tempo):
                return {}

            contextos.append(
                {
                    "idx": i,
                    "preco_atual": preco_atual,
                    "volume_atual": volume_atual,
                    "volume_medio": volume_medio,
                    "atr": atr,
                    "regime": regime_info["regime"],
                    "topo": topo,
                    "fundo": fundo,
                    "amplitude": topo - fundo,
                    "fvg_bearish": fvg_bearish,
                    "fvg_bullish": fvg_bullish,
                    "tail_highs": [float(v) for v in tail["high"].tolist()],
                    "tail_lows": [float(v) for v in tail["low"].tolist()],
                    "open_time": str(ultimo_tempo),
                    "close_time": str(janela.iloc[-1]["close_time"]) if "close_time" in janela.columns else str(ultimo_tempo),
                }
            )
    except Exception:
        return {}

    return contextos


def _fvg_foi_tocado_em_contexto(contexto, zona_inferior, zona_superior, candles=10):
    highs = contexto["tail_highs"][-candles:]
    lows = contexto["tail_lows"][-candles:]
    for high, low in zip(highs, lows):
        if float(high) >= zona_inferior and float(low) <= zona_superior:
            return True
    return False


def _simular_decisao_contexto(
    contexto,
    volume_minimo_multiplicador=None,
    volume_alto_multiplicador=1.8,
    exigir_rr_minimo=True,
    regime_modo="bear_only",
    exigir_fvg_nao_tocado=False,
    lookback_fvg=10,
):
    regime = contexto["regime"]
    atr = contexto["atr"]
    preco_atual = contexto["preco_atual"]
    volume_atual = contexto["volume_atual"]
    volume_medio = contexto["volume_medio"]
    topo = contexto["topo"]
    fundo = contexto["fundo"]
    amplitude = contexto["amplitude"]

    if pd.isna(atr) or regime == "INDEFINIDO":
        return None

    if regime_modo == "bear_only" and regime != "BEAR":
        return None
    if regime_modo == "bull_only" and regime != "BULL":
        return None
    if regime_modo == "bull_bear" and regime not in ("BULL", "BEAR"):
        return None

    if volume_medio is not None and not pd.isna(volume_medio) and volume_medio > 0:
        razao_volume = volume_atual / volume_medio
        if volume_minimo_multiplicador is not None and razao_volume < volume_minimo_multiplicador:
            return None
        status_volume = "ALTO" if volume_minimo_multiplicador is not None else ("ALTO" if razao_volume > volume_alto_multiplicador else "NEUTRO")
        ajuste_score_volume = 2 if (volume_minimo_multiplicador is not None or razao_volume > volume_alto_multiplicador) else 0
    else:
        status_volume = "INDETERMINADO"
        ajuste_score_volume = 0

    def _montar_candidato(direcao, fvg, motivo_base, score_base=5):
        if fvg is None:
            return None
        fvg_low, fvg_high = fvg
        if exigir_fvg_nao_tocado and _fvg_foi_tocado_em_contexto(
            contexto, min(fvg_low, fvg_high), max(fvg_low, fvg_high), lookback_fvg
        ):
            return None

        if direcao == "COMPRA":
            entrada = preco_atual
            stop_loss = min(fundo, entrada - 1.5 * atr) if not pd.isna(fundo) else entrada - 1.5 * atr
            take_profit = fvg_high
            risco = entrada - stop_loss
            recompensa = take_profit - entrada
        else:
            entrada = preco_atual
            stop_loss = min(topo, entrada + 1.5 * atr) if not pd.isna(topo) and topo > entrada else entrada + 1.5 * atr
            take_profit = fvg_high
            risco = stop_loss - entrada
            recompensa = entrada - take_profit

        rr = recompensa / risco if risco > 0 else 0
        if exigir_rr_minimo and rr < 1.5:
            return None

        return {
            "decisao": direcao,
            "score": min(10, score_base + ajuste_score_volume),
            "entrada": entrada,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "rr": rr,
            "regime": regime,
            "direcao": direcao,
            "volume_status": status_volume,
            "fvg_target": fvg_high,
            "zona_entrada_ideal": topo - amplitude * 0.618 if direcao == "COMPRA" else fundo + amplitude * 0.618,
        }

    if regime == "CHOP" and regime_modo == "qualquer":
        candidato_compra = _montar_candidato("COMPRA", contexto["fvg_bearish"], "CHOP COMPRA")
        candidato_venda = _montar_candidato("VENDA", contexto["fvg_bullish"], "CHOP VENDA")
        candidatos = [c for c in (candidato_compra, candidato_venda) if c is not None]
        if not candidatos:
            return None
        candidatos.sort(key=lambda item: item["rr"], reverse=True)
        return candidatos[0]

    if regime == "BULL":
        return _montar_candidato("COMPRA", contexto["fvg_bearish"], "Tendencia de alta com FVG Bearish acima.")

    if regime == "BEAR":
        return _montar_candidato("VENDA", contexto["fvg_bullish"], "Tendencia de baixa com FVG Bullish abaixo.")

    return None


def executar_otimizacao_sol(
    df,
    capital_inicial=10000,
    risco_percentual=1.0,
    slippage=0.0005,
    taxa=0.0004,
):
    contextos = _precomputar_contextos_otimizacao(df)
    if not isinstance(contextos, list):
        contextos = []
    volume_opcoes = [None, 1.2, 1.5, 2.0]
    regime_opcoes = ["bear_only", "bull_only", "bull_bear"]
    rr_opcoes = [True, False]
    fvg_opcoes = [False, True]
    janelas_fvg = [5, 10, 15, 20]

    resultados = {}
    estrategia = configurar_estrategia("D")
    idx_map = {ctx["idx"]: ctx for ctx in contextos}

    for regime_modo in regime_opcoes:
        for volume_minimo_multiplicador in volume_opcoes:
            for exigir_rr_minimo in rr_opcoes:
                for exigir_fvg_nao_tocado in fvg_opcoes:
                    if exigir_fvg_nao_tocado:
                        lookbacks = janelas_fvg
                    else:
                        lookbacks = [None]

                    for lookback_fvg in lookbacks:
                        config = {
                            "regime_modo": regime_modo,
                            "volume_minimo_multiplicador": volume_minimo_multiplicador,
                            "exigir_fvg_nao_tocado": exigir_fvg_nao_tocado,
                            "lookback_fvg": lookback_fvg,
                            "exigir_rr_minimo": exigir_rr_minimo,
                        }
                        chave = _chave_otimizacao_sol(config)
                        trades = []
                        capital = float(capital_inicial)
                        equity_curve = [capital]
                        peak = capital
                        max_drawdown = 0.0
                        historico_resultados = []
                        trades_por_regime = {"BULL": [], "BEAR": [], "CHOP": [], "INDEFINIDO": []}

                        i = 200
                        while i < len(df) - 1:
                            contexto = idx_map.get(i)
                            if contexto is None:
                                i += 1
                                continue

                            sinal = _simular_decisao_contexto(
                                contexto,
                                volume_minimo_multiplicador=volume_minimo_multiplicador,
                                volume_alto_multiplicador=volume_minimo_multiplicador or 1.0,
                                exigir_rr_minimo=exigir_rr_minimo,
                                regime_modo=regime_modo,
                                exigir_fvg_nao_tocado=exigir_fvg_nao_tocado,
                                lookback_fvg=lookback_fvg or 10,
                            )
                            if sinal is None or sinal.get("direcao") not in ("COMPRA", "VENDA"):
                                i += 1
                                continue

                            trade_result = _simular_trade_variante(
                                df,
                                i,
                                sinal,
                                capital,
                                risco_percentual,
                                estrategia,
                                slippage,
                                taxa,
                            )
                            if trade_result is None:
                                i += 1
                                continue

                            trade, exit_index = trade_result
                            capital += trade["net_pnl"]
                            equity_curve.append(capital)
                            peak = max(peak, capital)
                            trade["equity_after"] = capital
                            trade["drawdown_percent"] = ((peak - capital) / peak) * 100 if peak > 0 else 0.0
                            max_drawdown = max(max_drawdown, trade["drawdown_percent"])
                            historico_resultados.append(trade["resultado"])
                            trades.append(trade)
                            trades_por_regime.setdefault(trade["regime"], []).append(trade)
                            i = exit_index + 1

                        gross_profit = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
                        gross_loss = abs(sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0))
                        total_net = sum(t["net_pnl"] for t in trades)
                        profit_factor = (
                            gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
                        )
                        total_trades = len(trades)
                        wins = sum(1 for t in trades if t["resultado"] == "GANHO")
                        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
                        media_rr = sum((t["realized_rr"] for t in trades), 0.0) / total_trades if total_trades > 0 else 0.0
                        ganho_medio = (
                            sum(t["resultado_percentual"] for t in trades if t["resultado_percentual"] > 0) / wins
                            if wins > 0
                            else 0.0
                        )
                        perdas = total_trades - wins
                        perda_media = (
                            abs(sum(t["resultado_percentual"] for t in trades if t["resultado_percentual"] < 0)) / perdas
                            if perdas > 0
                            else 0.0
                        )
                        expectativa_matematica = (win_rate / 100.0) * ganho_medio - (1 - (win_rate / 100.0)) * perda_media

                        regimes_summary = {}
                        for regime_nome, trades_regime in trades_por_regime.items():
                            total_regime = len(trades_regime)
                            wins_regime = sum(1 for t in trades_regime if t["resultado"] == "GANHO")
                            gross_profit_regime = sum(t["net_pnl"] for t in trades_regime if t["net_pnl"] > 0)
                            gross_loss_regime = abs(sum(t["net_pnl"] for t in trades_regime if t["net_pnl"] < 0))
                            profit_factor_regime = (
                                gross_profit_regime / gross_loss_regime
                                if gross_loss_regime > 0
                                else float("inf") if gross_profit_regime > 0
                                else 0.0
                            )
                            media_rr_regime = (
                                sum(t["realized_rr"] for t in trades_regime) / total_regime if total_regime > 0 else 0.0
                            )
                            regimes_summary[regime_nome] = {
                                "total_trades": total_regime,
                                "win_rate": round((wins_regime / total_regime * 100), 2) if total_regime > 0 else 0.0,
                                "profit_factor": round(profit_factor_regime, 4)
                                if profit_factor_regime != float("inf")
                                else "inf",
                                "media_rr": round(media_rr_regime, 3),
                            }

                        summary = {
                            "total_trades": total_trades,
                            "win_rate": round(win_rate, 2),
                            "lucro_total_percent": round((total_net / capital_inicial) * 100, 2) if capital_inicial else 0.0,
                            "lucro_total_valor": round(total_net, 2),
                            "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
                            "drawdown_max_percent": round(max_drawdown, 2),
                            "media_rr": round(media_rr, 3),
                            "sequencia_maxima_perdas": _sequencia_maxima_perdas(historico_resultados),
                            "expectativa_matematica_percentual": round(expectativa_matematica, 3),
                            "regimes": regimes_summary,
                        }

                        resultados[chave] = {
                            "symbol": "SOLUSDT",
                            "estrategia": estrategia,
                            "filtros_entrada": config,
                            "trades": trades,
                            "capital_inicial": capital_inicial,
                            "capital_final": round(capital, 2),
                            "equity_curve": equity_curve,
                            "trades_por_regime": trades_por_regime,
                            "summary": summary,
                        }

    resultados_ordenados = []
    for chave, resultado in resultados.items():
        summary = resultado["summary"]
        resultados_ordenados.append(
            {
                "chave": chave,
                "configuracao": resultado["filtros_entrada"],
                "summary": summary,
                "capital_final": resultado["capital_final"],
                "symbol": resultado["symbol"],
            }
        )

    candidatos_validos = [
        item for item in resultados_ordenados if item["summary"]["total_trades"] >= 30
    ]
    universo = candidatos_validos if candidatos_validos else resultados_ordenados

    def _score(item):
        pf = item["summary"]["profit_factor"]
        pf_num = float("-inf") if pf == "inf" else float(pf)
        expectativa = float(item["summary"]["expectativa_matematica_percentual"])
        return (pf_num, expectativa)

    melhor = max(universo, key=_score) if universo else None

    return {
        "symbol": "SOLUSDT",
        "criterios": {
            "min_trades": 30,
            "prioridade": ["profit_factor", "expectativa_matematica"],
            "regimes": regime_opcoes,
            "volume_thresholds": volume_opcoes,
            "fvg_windows": janelas_fvg,
            "rr_minimo": rr_opcoes,
            "fvg_nao_tocado": fvg_opcoes,
        },
        "total_cenarios": len(resultados_ordenados),
        "candidatos_validos": len(candidatos_validos),
        "melhor_configuracao": melhor,
        "resultados": resultados_ordenados,
    }


def _dividir_em_periodos_walkforward(df, periodos=3):
    if df is None or df.empty:
        return []

    df = df.sort_values("open_time").reset_index(drop=True)
    tamanho = len(df)
    if tamanho < periodos * 10:
        return [df]

    bloco = tamanho // periodos
    segmentos = []
    for i in range(periodos):
        inicio = i * bloco
        fim = (i + 1) * bloco if i < periodos - 1 else tamanho
        segmento = df.iloc[inicio:fim].copy()
        if not segmento.empty:
            segmentos.append(segmento)
    return segmentos


def _executar_backtest_config_rapido(
    df,
    capital_inicial=10000,
    risco_percentual=1.0,
    slippage=0.0005,
    taxa=0.0004,
    volume_minimo_multiplicador=None,
    volume_alto_multiplicador=1.8,
    exigir_fvg_nao_tocado=False,
    regime_modo="bear_only",
    exigir_rr_minimo=True,
    lookback_fvg=10,
):
    contextos = _precomputar_contextos_otimizacao(df)
    if not isinstance(contextos, list):
        contextos = []
    return _executar_backtest_com_contextos(
        contextos,
        df,
        capital_inicial=capital_inicial,
        risco_percentual=risco_percentual,
        slippage=slippage,
        taxa=taxa,
        volume_minimo_multiplicador=volume_minimo_multiplicador,
        volume_alto_multiplicador=volume_alto_multiplicador,
        exigir_fvg_nao_tocado=exigir_fvg_nao_tocado,
        regime_modo=regime_modo,
        exigir_rr_minimo=exigir_rr_minimo,
        lookback_fvg=lookback_fvg,
    )


def _executar_backtest_com_contextos(
    contextos,
    df,
    capital_inicial=10000,
    risco_percentual=1.0,
    slippage=0.0005,
    taxa=0.0004,
    volume_minimo_multiplicador=None,
    volume_alto_multiplicador=1.8,
    exigir_fvg_nao_tocado=False,
    regime_modo="bear_only",
    exigir_rr_minimo=True,
    lookback_fvg=10,
):
    if not contextos:
        return {
            "trades": [],
            "capital_inicial": capital_inicial,
            "capital_final": capital_inicial,
            "equity_curve": [capital_inicial],
            "summary": {
                "total_trades": 0,
                "win_rate": 0.0,
                "lucro_total_percent": 0.0,
                "lucro_total_valor": 0.0,
                "profit_factor": 0.0,
                "drawdown_max_percent": 0.0,
                "media_rr": 0.0,
                "sequencia_maxima_perdas": 0,
                "expectativa_matematica_percentual": 0.0,
                "regimes": {},
            },
        }

    estrategia = configurar_estrategia("D")
    trades = []
    capital = float(capital_inicial)
    equity_curve = [capital]
    peak = capital
    max_drawdown = 0.0
    historico_resultados = []
    trades_por_regime = {"BULL": [], "BEAR": [], "CHOP": [], "INDEFINIDO": []}
    idx_map = {ctx["idx"]: ctx for ctx in contextos}

    i = 200
    while i < len(df) - 1:
        contexto = idx_map.get(i)
        if contexto is None:
            i += 1
            continue

        sinal = _simular_decisao_contexto(
            contexto,
            volume_minimo_multiplicador=volume_minimo_multiplicador,
            volume_alto_multiplicador=volume_alto_multiplicador,
            exigir_rr_minimo=exigir_rr_minimo,
            regime_modo=regime_modo,
            exigir_fvg_nao_tocado=exigir_fvg_nao_tocado,
            lookback_fvg=lookback_fvg,
        )
        if sinal is None or sinal.get("direcao") not in ("COMPRA", "VENDA"):
            i += 1
            continue

        trade_result = _simular_trade_variante(
            df,
            i,
            sinal,
            capital,
            risco_percentual,
            estrategia,
            slippage,
            taxa,
        )
        if trade_result is None:
            i += 1
            continue

        trade, exit_index = trade_result
        capital += trade["net_pnl"]
        equity_curve.append(capital)
        peak = max(peak, capital)
        trade["equity_after"] = capital
        trade["drawdown_percent"] = ((peak - capital) / peak) * 100 if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, trade["drawdown_percent"])
        historico_resultados.append(trade["resultado"])
        trades.append(trade)
        trades_por_regime.setdefault(trade["regime"], []).append(trade)
        i = exit_index + 1

    gross_profit = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
    gross_loss = abs(sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0))
    total_net = sum(t["net_pnl"] for t in trades)
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
    total_trades = len(trades)
    wins = sum(1 for t in trades if t["resultado"] == "GANHO")
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    media_rr = sum((t["realized_rr"] for t in trades), 0.0) / total_trades if total_trades > 0 else 0.0
    ganho_medio = (
        sum(t["resultado_percentual"] for t in trades if t["resultado_percentual"] > 0) / wins
        if wins > 0
        else 0.0
    )
    perdas = total_trades - wins
    perda_media = (
        abs(sum(t["resultado_percentual"] for t in trades if t["resultado_percentual"] < 0)) / perdas
        if perdas > 0
        else 0.0
    )
    expectativa_matematica = (win_rate / 100.0) * ganho_medio - (1 - (win_rate / 100.0)) * perda_media

    regimes_summary = {}
    for regime_nome, trades_regime in trades_por_regime.items():
        total_regime = len(trades_regime)
        wins_regime = sum(1 for t in trades_regime if t["resultado"] == "GANHO")
        gross_profit_regime = sum(t["net_pnl"] for t in trades_regime if t["net_pnl"] > 0)
        gross_loss_regime = abs(sum(t["net_pnl"] for t in trades_regime if t["net_pnl"] < 0))
        profit_factor_regime = (
            gross_profit_regime / gross_loss_regime
            if gross_loss_regime > 0
            else float("inf") if gross_profit_regime > 0
            else 0.0
        )
        media_rr_regime = (
            sum(t["realized_rr"] for t in trades_regime) / total_regime if total_regime > 0 else 0.0
        )
        regimes_summary[regime_nome] = {
            "total_trades": total_regime,
            "win_rate": round((wins_regime / total_regime * 100), 2) if total_regime > 0 else 0.0,
            "profit_factor": round(profit_factor_regime, 4) if profit_factor_regime != float("inf") else "inf",
            "media_rr": round(media_rr_regime, 3),
        }

    summary = {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 2),
        "lucro_total_percent": round((total_net / capital_inicial) * 100, 2) if capital_inicial else 0.0,
        "lucro_total_valor": round(total_net, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
        "drawdown_max_percent": round(max_drawdown, 2),
        "media_rr": round(media_rr, 3),
        "sequencia_maxima_perdas": _sequencia_maxima_perdas(historico_resultados),
        "expectativa_matematica_percentual": round(expectativa_matematica, 3),
        "regimes": regimes_summary,
    }

    return {
        "estrategia": estrategia,
        "trades": trades,
        "capital_inicial": capital_inicial,
        "capital_final": round(capital, 2),
        "equity_curve": equity_curve,
        "trades_por_regime": trades_por_regime,
        "summary": summary,
    }


def executar_otimizacao_sol_walkforward(
    df,
    capital_inicial=10000,
    risco_percentual=1.0,
    slippage=0.0005,
    taxa=0.0004,
):
    periodos = _dividir_em_periodos_walkforward(df, periodos=3)
    periodos_contextos = []
    for segmento in periodos:
        split_idx = max(1, int(len(segmento) * 0.7))
        train_df = segmento.iloc[:split_idx].copy()
        test_df = segmento.iloc[split_idx:].copy()
        train_contextos = _precomputar_contextos_otimizacao(train_df)
        test_contextos = _precomputar_contextos_otimizacao(test_df)
        if not isinstance(train_contextos, list):
            train_contextos = []
        if not isinstance(test_contextos, list):
            test_contextos = []
        periodos_contextos.append(
            {
                "train_df": train_df,
                "test_df": test_df,
                "train_contextos": train_contextos,
                "test_contextos": test_contextos,
            }
        )
    volume_opcoes = [None, 1.2, 1.5, 2.0]
    regime_opcoes = ["bear_only", "bull_only", "bull_bear"]
    rr_opcoes = [True, False]
    fvg_opcoes = [False, True]
    janelas_fvg = [5, 10, 15, 20]

    resultados = {}

    for regime_modo in regime_opcoes:
        for volume_minimo_multiplicador in volume_opcoes:
            for exigir_rr_minimo in rr_opcoes:
                for exigir_fvg_nao_tocado in fvg_opcoes:
                    lookbacks = janelas_fvg if exigir_fvg_nao_tocado else [None]
                    for lookback_fvg in lookbacks:
                        config = {
                            "regime_modo": regime_modo,
                            "volume_minimo_multiplicador": volume_minimo_multiplicador,
                            "exigir_fvg_nao_tocado": exigir_fvg_nao_tocado,
                            "lookback_fvg": lookback_fvg,
                            "exigir_rr_minimo": exigir_rr_minimo,
                        }
                        chave = _chave_otimizacao_sol(config)
                        testes = []
                        treinos = []

                        for periodo_ctx in periodos_contextos:
                            treino = _executar_backtest_com_contextos(
                                periodo_ctx["train_contextos"],
                                periodo_ctx["train_df"],
                                capital_inicial=capital_inicial,
                                risco_percentual=risco_percentual,
                                slippage=slippage,
                                taxa=taxa,
                                volume_minimo_multiplicador=volume_minimo_multiplicador,
                                volume_alto_multiplicador=volume_minimo_multiplicador or 1.0,
                                exigir_fvg_nao_tocado=exigir_fvg_nao_tocado,
                                regime_modo=regime_modo,
                                exigir_rr_minimo=exigir_rr_minimo,
                                lookback_fvg=lookback_fvg or 10,
                            )

                            teste = _executar_backtest_com_contextos(
                                periodo_ctx["test_contextos"],
                                periodo_ctx["test_df"],
                                capital_inicial=capital_inicial,
                                risco_percentual=risco_percentual,
                                slippage=slippage,
                                taxa=taxa,
                                volume_minimo_multiplicador=volume_minimo_multiplicador,
                                volume_alto_multiplicador=volume_minimo_multiplicador or 1.0,
                                exigir_fvg_nao_tocado=exigir_fvg_nao_tocado,
                                regime_modo=regime_modo,
                                exigir_rr_minimo=exigir_rr_minimo,
                                lookback_fvg=lookback_fvg or 10,
                            )

                            treinos.append(treino["summary"])
                            testes.append(teste["summary"])

                        total_trades_teste = sum(t["total_trades"] for t in testes)

                        def _media(metric):
                            valores = [float(t[metric]) if t[metric] != "inf" else 0.0 for t in testes]
                            return sum(valores) / len(valores) if valores else 0.0

                        def _media_treino(metric):
                            valores = [float(t[metric]) if t[metric] != "inf" else 0.0 for t in treinos]
                            return sum(valores) / len(valores) if valores else 0.0

                        resultados[chave] = {
                            "symbol": "SOLUSDT",
                            "configuracao": config,
                            "treinos": treinos,
                            "testes": testes,
                            "resumo": {
                                "media_profit_factor_teste": round(_media("profit_factor"), 4),
                                "media_win_rate_teste": round(_media("win_rate"), 2),
                                "media_lucro_total_teste": round(_media("lucro_total_percent"), 2),
                                "media_total_trades_teste": round(_media("total_trades"), 2),
                                "media_drawdown_teste": round(_media("drawdown_max_percent"), 2),
                                "media_rr_teste": round(_media("media_rr"), 3),
                                "media_profit_factor_treino": round(_media_treino("profit_factor"), 4),
                                "media_win_rate_treino": round(_media_treino("win_rate"), 2),
                                "total_trades_teste": total_trades_teste,
                                "total_periodos": len(periodos),
                            },
                        }

    candidatos = list(resultados.items())
    melhor = None
    if candidatos:
        def _score(item):
            resumo = item[1]["resumo"]
            return (float(resumo["media_profit_factor_teste"]), float(resumo["media_win_rate_teste"]))

        melhor = max(candidatos, key=_score)

    return {
        "symbol": "SOLUSDT",
        "criterios": {
            "periodos": 3,
            "split": "70/30",
            "regimes": regime_opcoes,
            "volume_thresholds": volume_opcoes,
            "fvg_windows": janelas_fvg,
            "rr_minimo": rr_opcoes,
            "fvg_nao_tocado": fvg_opcoes,
            "min_total_trades_teste": 0,
        },
        "total_cenarios": len(resultados),
        "melhor_configuracao": {
            "chave": melhor[0] if melhor else None,
            "configuracao": melhor[1]["configuracao"] if melhor else None,
            "resumo": melhor[1]["resumo"] if melhor else None,
        } if melhor else None,
        "resultados": [
            {
                "chave": chave,
                "configuracao": valor["configuracao"],
                "resumo": valor["resumo"],
            }
            for chave, valor in resultados.items()
        ],
    }


def avaliar_out_of_sample_sol(
    df,
    split_ratio=0.7,
    capital_inicial=10000,
    risco_percentual=1.0,
    slippage=0.0005,
    taxa=0.0004,
):
    """
    Avalia a combinacao vencedora da SOL em treino/teste cronologico.
    """
    if df is None or df.empty:
        return {
            "symbol": "SOLUSDT",
            "split_ratio": split_ratio,
            "configuracao": None,
            "treino": None,
            "teste": None,
            "comparacao": {
                "veredito": "SEM_DADOS",
                "observacao": "DataFrame vazio.",
            },
        }

    split_idx = max(1, int(len(df) * split_ratio))
    train_df = df.iloc[:split_idx].copy()
    test_df = df.iloc[split_idx:].copy()

    configuracao_vencedora = {
        "symbol": "SOLUSDT",
        "regime_modo": "qualquer",
        "volume_minimo_multiplicador": 1.5,
        "exigir_fvg_nao_tocado": True,
        "lookback_fvg": 5,
        "exigir_rr_minimo": False,
    }

    treino = executar_backtest_filtros_entrada(
        train_df,
        symbol="SOLUSDT",
        capital_inicial=capital_inicial,
        risco_percentual=risco_percentual,
        slippage=slippage,
        taxa=taxa,
        volume_alto_multiplicador=1.5,
        volume_minimo_multiplicador=1.5,
        exigir_fvg_nao_tocado=True,
        somente_bear=False,
        regime_modo="qualquer",
        exigir_rr_minimo=False,
        lookback_fvg=5,
    )

    teste = executar_backtest_filtros_entrada(
        test_df,
        symbol="SOLUSDT",
        capital_inicial=capital_inicial,
        risco_percentual=risco_percentual,
        slippage=slippage,
        taxa=taxa,
        volume_alto_multiplicador=1.5,
        volume_minimo_multiplicador=1.5,
        exigir_fvg_nao_tocado=True,
        somente_bear=False,
        regime_modo="qualquer",
        exigir_rr_minimo=False,
        lookback_fvg=5,
    )

    train_pf = treino["summary"]["profit_factor"]
    test_pf = teste["summary"]["profit_factor"]
    train_pf_num = float("-inf") if train_pf == "inf" else float(train_pf)
    test_pf_num = float("-inf") if test_pf == "inf" else float(test_pf)
    degradacao_pf = train_pf_num - test_pf_num

    if test_pf_num > 1.0:
        veredito = "VALIDADA"
        observacao = "PF de teste acima de 1.0."
    elif test_pf_num < 0.9:
        veredito = "OVERFITTING_PROVAVEL"
        observacao = "PF de teste abaixo de 0.9."
    else:
        veredito = "MISTA"
        observacao = "PF de teste entre 0.9 e 1.0."

    comparacao = {
        "veredito": veredito,
        "observacao": observacao,
        "treino_referencia": {
            "profit_factor": 1.13,
            "total_trades": 57,
        },
        "treino_obtido": {
            "profit_factor": treino["summary"]["profit_factor"],
            "total_trades": treino["summary"]["total_trades"],
        },
        "teste": {
            "profit_factor": teste["summary"]["profit_factor"],
            "total_trades": teste["summary"]["total_trades"],
        },
        "degradacao_pf": round(degradacao_pf, 4),
        "degradacao_percentual": round(
            ((train_pf_num - test_pf_num) / train_pf_num) * 100, 2
        ) if train_pf_num not in (0.0, float("-inf")) and train_pf_num != 0 else None,
    }

    return {
        "symbol": "SOLUSDT",
        "split_ratio": split_ratio,
        "split_index": split_idx,
        "total_candles": len(df),
        "configuracao": configuracao_vencedora,
        "treino": treino,
        "teste": teste,
        "comparacao": comparacao,
    }


def _yahoo_para_backtester(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["open_time", "close_time", "open", "high", "low", "close", "volume"])

    resultado = df.copy()
    if "Date" in resultado.columns:
        resultado["open_time"] = pd.to_datetime(resultado["Date"], utc=True)
    elif "Datetime" in resultado.columns:
        resultado["open_time"] = pd.to_datetime(resultado["Datetime"], utc=True)
    else:
        resultado["open_time"] = pd.to_datetime(resultado.index, utc=True)

    resultado["close_time"] = resultado["open_time"]
    rename_map = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    resultado = resultado.rename(columns=rename_map)
    colunas = ["open_time", "close_time", "open", "high", "low", "close", "volume"]
    for coluna in ("open", "high", "low", "close", "volume"):
        if coluna in resultado.columns:
            resultado[coluna] = pd.to_numeric(resultado[coluna], errors="coerce")
    for coluna in colunas:
        if coluna not in resultado.columns:
            resultado[coluna] = pd.NA
    resultado = resultado[colunas].copy()
    resultado.attrs["fonte_dados"] = "YAHOO"
    return resultado


def _calcular_metricas(trades, capital_inicial=10000):
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "lucro_total_percent": 0.0,
            "lucro_total_valor": 0.0,
            "profit_factor": 0.0,
            "drawdown_max_percent": 0.0,
            "media_rr": 0.0,
            "sequencia_maxima_perdas": 0,
            "expectativa_matematica_percentual": 0.0,
            "regimes": {},
        }

    trades_ordenados = sorted(trades, key=lambda item: item.get("data_entrada") or "")
    gross_profit = sum(t["net_pnl"] for t in trades_ordenados if t["net_pnl"] > 0)
    gross_loss = abs(sum(t["net_pnl"] for t in trades_ordenados if t["net_pnl"] < 0))
    total_net = sum(t["net_pnl"] for t in trades_ordenados)
    total_trades = len(trades_ordenados)
    wins = sum(1 for t in trades_ordenados if t["resultado"] == "GANHO")
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
    media_rr = sum((t.get("realized_rr") or 0.0 for t in trades_ordenados), 0.0) / total_trades if total_trades > 0 else 0.0
    ganho_medio = (
        sum(t.get("resultado_percentual") or 0.0 for t in trades_ordenados if (t.get("resultado_percentual") or 0.0) > 0) / wins
        if wins > 0
        else 0.0
    )
    perdas = total_trades - wins
    perda_media = (
        abs(sum(t.get("resultado_percentual") or 0.0 for t in trades_ordenados if (t.get("resultado_percentual") or 0.0) < 0)) / perdas
        if perdas > 0
        else 0.0
    )
    expectativa_matematica = (win_rate / 100.0) * ganho_medio - (1 - (win_rate / 100.0)) * perda_media

    regimes_summary = {}
    for regime_nome in ("BULL", "BEAR", "CHOP", "INDEFINIDO"):
        trades_regime = [t for t in trades_ordenados if t.get("regime") == regime_nome]
        total_regime = len(trades_regime)
        wins_regime = sum(1 for t in trades_regime if t["resultado"] == "GANHO")
        gross_profit_regime = sum(t["net_pnl"] for t in trades_regime if t["net_pnl"] > 0)
        gross_loss_regime = abs(sum(t["net_pnl"] for t in trades_regime if t["net_pnl"] < 0))
        profit_factor_regime = (
            gross_profit_regime / gross_loss_regime
            if gross_loss_regime > 0
            else float("inf") if gross_profit_regime > 0
            else 0.0
        )
        media_rr_regime = sum((t.get("realized_rr") or 0.0 for t in trades_regime), 0.0) / total_regime if total_regime > 0 else 0.0
        regimes_summary[regime_nome] = {
            "total_trades": total_regime,
            "win_rate": round((wins_regime / total_regime * 100), 2) if total_regime > 0 else 0.0,
            "profit_factor": round(profit_factor_regime, 4) if profit_factor_regime != float("inf") else "inf",
            "media_rr": round(media_rr_regime, 3),
        }

    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 2),
        "lucro_total_percent": round((total_net / capital_inicial) * 100, 2) if capital_inicial else 0.0,
        "lucro_total_valor": round(total_net, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
        "drawdown_max_percent": 0.0,
        "media_rr": round(media_rr, 3),
        "sequencia_maxima_perdas": _sequencia_maxima_perdas([t["resultado"] for t in trades_ordenados]),
        "expectativa_matematica_percentual": round(expectativa_matematica, 3),
        "regimes": regimes_summary,
    }


def _sequencia_maxima_perdas(historico):
    max_seq = 0
    atual = 0
    for item in historico:
        if item == "PERDA":
            atual += 1
            max_seq = max(max_seq, atual)
        else:
            atual = 0
    return max_seq


def gerar_relatorio_backtest(resultado):
    summary = resultado["summary"]
    return {
        "summary": summary,
        "capital_inicial": resultado["capital_inicial"],
        "capital_final": resultado["capital_final"],
        "trades": resultado["trades"],
        "regimes": summary.get("regimes", {}),
    }


def salvar_relatorio(resultado, caminho=REPORT_PATH):
    caminho.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")


def salvar_trades_csv(trades, caminho=TRADES_CSV_PATH):
    colunas = [
        "data_entrada",
        "direcao",
        "entrada",
        "stop",
        "take",
        "resultado_percentual",
        "resultado_reais",
        "regime",
    ]
    if not trades:
        pd.DataFrame(columns=colunas).to_csv(caminho, index=False, encoding="utf-8")
        return

    df = pd.DataFrame(trades)
    df = df.reindex(columns=colunas)
    df.to_csv(caminho, index=False, encoding="utf-8")


def main():
    try:
        df = baixar_dados_historicos()
        resultados_variantes = executar_backtests_variantes(df)
        relatorio = construir_relatorio_variantes(resultados_variantes)
        salvar_relatorio(relatorio, VARIANTES_REPORT_PATH)
        salvar_relatorio(relatorio, REPORT_PATH)

        print(json.dumps(relatorio, indent=2, ensure_ascii=False))
        print(f"Relatório comparativo salvo em: {VARIANTES_REPORT_PATH}")
    except Exception as e:
        print(f"Erro no backtest: {e}")


def main():
    try:
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
        resultados_multi = executar_backtest_multi_ativos(symbols)
        relatorio = construir_relatorio_multi_ativos(resultados_multi)
        salvar_relatorio(relatorio, MULTI_ATIVOS_REPORT_PATH)
        salvar_relatorio(relatorio, REPORT_PATH)

        print(json.dumps(relatorio, indent=2, ensure_ascii=False))
        print(f"Relatorio comparativo salvo em: {MULTI_ATIVOS_REPORT_PATH}")
    except Exception as e:
        print(f"Erro no backtest: {e}")


def main():
    try:
        df = baixar_dados_historicos(symbol="SOLUSDT")
        relatorio = executar_otimizacao_sol_walkforward(df)
        salvar_relatorio(relatorio, WALKFORWARD_SOL_PATH)
        salvar_relatorio(relatorio, REPORT_PATH)

        print(json.dumps(relatorio, indent=2, ensure_ascii=False))
        print(f"Relatorio walk-forward salvo em: {WALKFORWARD_SOL_PATH}")
    except Exception as e:
        print(f"Erro no backtest: {e}")


if __name__ == "__main__":
    main()
