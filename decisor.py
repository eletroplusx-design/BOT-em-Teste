import pandas as pd
import requests
from regime_classifier import classificar_regime
from storage import log_decisao

def obter_funding_rate(symbol="BTCUSDT"):
    """
    Busca a última funding rate do contrato futuro perpétuo da Binance.
    Retorna o valor decimal (ex.: 0.0001 representa 0.01%) ou None em caso de erro.
    """
    try:
        url = "https://fapi.binance.com/fapi/v1/premiumIndex"
        resp = requests.get(url, params={"symbol": symbol}, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("lastFundingRate", 0))
    except Exception as e:
        print(f"⚠️ Erro ao obter funding rate: {e}")
        return None

def calcular_volume_medio(df, periodo=20):
    return df['volume'].rolling(window=periodo).mean().iloc[-1]

def extrair_tendencia_direcao(df):
    if len(df) < 200:
        return 'INDEFINIDO'
    df['SMA200'] = df['close'].rolling(window=200).mean()
    preco_atual = df['close'].iloc[-1]
    sma200 = df['SMA200'].iloc[-1]
    if pd.isna(sma200):
        return 'INDEFINIDO'
    return 'ALTA' if preco_atual > sma200 else 'BAIXA'

def extrair_swing_high_low(df, periodo=50):
    janela = df.tail(periodo)
    topo = janela['high'].max()
    fundo = janela['low'].min()
    return topo, fundo

def calcular_atr(df, periodo=14):
    max_min = df["high"] - df["low"]
    max_fech_ant = abs(df["high"] - df["close"].shift(1))
    min_fech_ant = abs(df["low"] - df["close"].shift(1))
    true_range = pd.concat([max_min, max_fech_ant, min_fech_ant], axis=1).max(axis=1)
    atr = true_range.rolling(window=periodo).mean()
    return atr.iloc[-1]

def calcular_rsi(df, periodo=14):
    """Calcula o RSI do último candle fechado."""
    fechamento = df["close"]
    delta = fechamento.diff()
    ganho = delta.clip(lower=0)
    perda = -delta.clip(upper=0)

    media_ganho = ganho.ewm(alpha=1 / periodo, min_periods=periodo, adjust=False).mean()
    media_perda = perda.ewm(alpha=1 / periodo, min_periods=periodo, adjust=False).mean()

    rs = media_ganho / media_perda.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    if rsi.empty:
        return None
    ultimo = rsi.iloc[-1]
    return None if pd.isna(ultimo) else float(ultimo)

def extrair_fvg_bearish_acima(df, preco_atual):
    janela = df.tail(50).reset_index(drop=True)
    melhor = None
    melhor_dist = float('inf')
    for i in range(2, len(janela)):
        high_i = janela.loc[i, "high"]
        low_i_2 = janela.loc[i-2, "low"]
        if high_i < low_i_2:  # Bearish FVG
            fvg_low = high_i
            fvg_high = low_i_2
            if fvg_low > preco_atual:
                dist = fvg_low - preco_atual
                if dist < melhor_dist:
                    melhor = (fvg_low, fvg_high)
                    melhor_dist = dist
    return melhor

def extrair_fvg_bullish_abaixo(df, preco_atual):
    janela = df.tail(50).reset_index(drop=True)
    melhor = None
    melhor_dist = float('inf')
    for i in range(2, len(janela)):
        low_i = janela.loc[i, "low"]
        high_i_2 = janela.loc[i-2, "high"]
        if low_i > high_i_2:  # Bullish FVG
            fvg_low = high_i_2
            fvg_high = low_i
            if fvg_high < preco_atual:
                dist = preco_atual - fvg_high
                if dist < melhor_dist:
                    melhor = (fvg_low, fvg_high)
                    melhor_dist = dist
    return melhor

def tomar_decisao(df, symbol="BTCUSDT", modo="DECISOR", fonte_dados=None, strategy_version="v2_risk_safe"):
    preco_atual = df['close'].iloc[-1]
    volume_atual = df['volume'].iloc[-1]
    atr = calcular_atr(df, 14)
    rsi_atual = calcular_rsi(df, 14)
    volume_medio = calcular_volume_medio(df, 20)

    # Prova do volume
    if volume_medio is not None and not pd.isna(volume_medio) and volume_medio > 0:
        razao_volume = volume_atual / volume_medio
        if razao_volume > 1.8:
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

    # Prova da Funding Rate
    funding_rate = obter_funding_rate()
    if funding_rate is not None:
        funding_pct = funding_rate * 100  # converter para percentual (0.01% → 0.01)
        if funding_pct > 0.01:
            funding_status = "ALTO (Longs pagando)"
            ajuste_score_funding = -1
        elif funding_pct < -0.01:
            funding_status = "NEGATIVO (Shorts pagando)"
            ajuste_score_funding = +1
        else:
            funding_status = "NEUTRO"
            ajuste_score_funding = 0
    else:
        funding_rate = None
        funding_pct = None
        funding_status = "INDISPONÍVEL"
        ajuste_score_funding = 0

    regime_info = classificar_regime(df)
    regime = regime_info['regime']

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
        "funding_rate": f"{funding_pct:.3f}%" if funding_pct is not None else None,
        "funding_status": funding_status,
        "rsi": round(rsi_atual, 1) if rsi_atual is not None else None,
        "rsi_status": "Neutro",
        "regime": regime,
        "direcao": None
    }

    if rsi_atual is not None:
        if rsi_atual > 55:
            resultado["rsi_status"] = "Sobrecomprado"
        elif rsi_atual < 45:
            resultado["rsi_status"] = "Sobrevendido"
        else:
            resultado["rsi_status"] = "Neutro"

    if regime == 'CHOP':
        resultado["decisao"] = "AGUARDAR (MERCADO LATERAL)"
        resultado["motivo"] = "Regime lateral/CHOP. Nenhuma operação recomendada."
        return resultado

    if regime == 'INDEFINIDO':
        resultado["motivo"] = "Regime lateral/indefinido. Nenhuma operação recomendada."
        return resultado

    topo, fundo = extrair_swing_high_low(df, 50)
    amplitude = topo - fundo

    if regime == 'BULL':
        fvg = extrair_fvg_bearish_acima(df, preco_atual)
        if fvg is None:
            resultado["motivo"] = "Nenhum FVG Bearish acima do preço."
            return resultado
        fvg_low, fvg_high = fvg
        alvo = fvg_high
        zona_entrada = topo - amplitude * 0.618
        resultado["zona_entrada_ideal"] = zona_entrada

        if preco_atual > zona_entrada * 1.01:
            resultado["decisao"] = "AGUARDAR RETRAÇÃO"
            resultado["motivo"] = f"Preço acima da zona de entrada ideal ({zona_entrada:,.2f}). Aguarde correção."
            return resultado

        entrada = preco_atual
        stop_loss = min(fundo, entrada - 1.5 * atr) if not pd.isna(fundo) else entrada - 1.5 * atr
        take_profit = alvo
        risco = entrada - stop_loss
        recompensa = take_profit - entrada
        rr = recompensa / risco if risco > 0 else 0

        score = 5
        score += ajuste_score_volume
        score += ajuste_score_funding
        if rsi_atual is not None and rsi_atual > 55:
            score -= 2
        score = min(score, 10)

        if status_volume == "BAIXO":
            resultado["decisao"] = "AGUARDAR (Volume Baixo)"
            resultado["motivo"] = "Volume atual muito baixo. Aguardar aumento de volume para confirmar."
            return resultado

        if score < 5:
            resultado.update({
                "decisao": "AGUARDAR (TIMING RUIM)",
                "score": score,
                "motivo": "RSI indica movimento esticado para COMPRA. Aguardar timing melhor.",
            })
            return resultado

        if rr < 1.5:
            resultado["decisao"] = "AGUARDAR"
            resultado["motivo"] = "R/R abaixo de 1.5. Risco muito alto para o alvo."
            return resultado

        resultado.update({
            "decisao": "COMPRA (Mercado BULL)",
            "score": score,
            "entrada": entrada,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risco": risco,
            "recompensa": recompensa,
            "rr": rr,
            "motivo": "Tendência de alta, comprando na correção até o FVG Bearish.",
            "direcao": "COMPRA"
        })
        try:
            log_decisao(
                symbol=symbol,
                modo=modo,
                decisao="SINAL_GERADO",
                direcao="COMPRA",
                preco=entrada,
                regime=regime,
                adx=regime_info.get("adx"),
                volume_status=status_volume,
                motivo=resultado["motivo"],
                bloqueado_por="N/A",
                fonte_dados=fonte_dados or getattr(df, "attrs", {}).get("fonte_dados") or "BINANCE",
                erro="N/A",
                strategy_version=strategy_version,
            )
        except Exception as exc:
            print(f"⚠️ Falha ao registrar SINAL_GERADO: {exc}")
        return resultado

    elif regime == 'BEAR':
        fvg = extrair_fvg_bullish_abaixo(df, preco_atual)
        if fvg is None:
            resultado["motivo"] = "Nenhum FVG Bullish abaixo do preço."
            return resultado
        fvg_low, fvg_high = fvg
        alvo = fvg_high
        zona_entrada = fundo + amplitude * 0.618
        resultado["zona_entrada_ideal"] = zona_entrada

        if preco_atual < zona_entrada * 0.99:
            resultado["decisao"] = "AGUARDAR RETRAÇÃO"
            resultado["motivo"] = f"Preço abaixo da zona de entrada ideal ({zona_entrada:,.2f}). Aguarde repique."
            return resultado

        entrada = preco_atual
        stop_loss = min(topo, entrada + 1.5 * atr) if not pd.isna(topo) and topo > entrada else entrada + 1.5 * atr
        take_profit = alvo
        risco = stop_loss - entrada
        recompensa = entrada - take_profit
        rr = recompensa / risco if risco > 0 else 0

        score = 5
        score += ajuste_score_volume
        score += ajuste_score_funding
        if rsi_atual is not None and rsi_atual < 45:
            score -= 2
        score = min(score, 10)

        if status_volume == "BAIXO":
            resultado["decisao"] = "AGUARDAR (Volume Baixo)"
            resultado["motivo"] = "Volume atual muito baixo. Aguardar aumento de volume para confirmar."
            return resultado

        if score < 5:
            resultado.update({
                "decisao": "AGUARDAR (TIMING RUIM)",
                "score": score,
                "motivo": "RSI indica movimento esticado para VENDA. Aguardar timing melhor.",
            })
            return resultado

        if rr < 1.5:
            resultado["decisao"] = "AGUARDAR"
            resultado["motivo"] = "R/R abaixo de 1.5. Risco muito alto para o alvo."
            return resultado

        resultado.update({
            "decisao": "VENDA (Mercado BEAR)",
            "score": score,
            "entrada": entrada,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risco": risco,
            "recompensa": recompensa,
            "rr": rr,
            "motivo": "Tendência de baixa, vendendo na correção até o FVG Bullish.",
            "direcao": "VENDA"
        })
        try:
            log_decisao(
                symbol=symbol,
                modo=modo,
                decisao="SINAL_GERADO",
                direcao="VENDA",
                preco=entrada,
                regime=regime,
                adx=regime_info.get("adx"),
                volume_status=status_volume,
                motivo=resultado["motivo"],
                bloqueado_por="N/A",
                fonte_dados=fonte_dados or getattr(df, "attrs", {}).get("fonte_dados") or "BINANCE",
                erro="N/A",
                strategy_version=strategy_version,
            )
        except Exception as exc:
            print(f"⚠️ Falha ao registrar SINAL_GERADO: {exc}")
        return resultado

    resultado["motivo"] = "Regime não identificado."
    return resultado
