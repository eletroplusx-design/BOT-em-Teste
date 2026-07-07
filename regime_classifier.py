import pandas as pd
import numpy as np

def calcular_atr(df, periodo=14):
    """Calcula o Average True Range (ATR) e retorna a série."""
    high = df['high']
    low = df['low']
    close = df['close']
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = true_range.ewm(alpha=1/periodo, min_periods=periodo, adjust=False).mean()
    return atr

def calcular_adx(df, periodo=14):
    """
    Calcula o ADX (Average Directional Index) usando suavização de Wilder.
    Retorna o valor do último candle.
    """
    high = df['high']
    low = df['low']
    close = df['close']

    # True Range
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Movimento direcional (+DM e -DM)
    up_move = high.diff()
    down_move = low.diff(-1) * -1  # low anterior - low atual (positivo se caiu)
    # Corrigindo: down_move = low.shift(1) - low
    prev_low = low.shift(1)
    prev_high = high.shift(1)
    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

    # Suavização Wilder (EWM com alpha = 1/periodo)
    atr_smooth = tr.ewm(alpha=1/periodo, min_periods=periodo, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/periodo, min_periods=periodo, adjust=False).mean() / atr_smooth)
    minus_di = 100 * (minus_dm.ewm(alpha=1/periodo, min_periods=periodo, adjust=False).mean() / atr_smooth)

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.ewm(alpha=1/periodo, min_periods=periodo, adjust=False).mean()

    if adx.empty:
        return None
    ultimo = adx.iloc[-1]
    return None if pd.isna(ultimo) else float(ultimo)

def classificar_regime(df):
    """
    Classifica o regime de mercado com base no ADX e SMA 200.
    Retorna um dicionário com 'regime', 'adx', 'volatilidade'.
    """
    # Calcular ATR (14) e ADX (14)
    df = df.copy()
    df['ATR'] = calcular_atr(df, 14)
    adx_atual = calcular_adx(df, 14)

    # Últimos valores
    atr_atual = df['ATR'].iloc[-1]

    # Média do ATR dos últimos 30 períodos
    atr_media_30 = df['ATR'].tail(30).mean()
    if pd.isna(atr_media_30) or atr_media_30 == 0:
        volatilidade = 'NORMAL'
    elif atr_atual > 1.8 * atr_media_30:
        volatilidade = 'ALTA'
    else:
        volatilidade = 'NORMAL'

    # SMA 200
    if len(df) < 200:
        regime = 'INDEFINIDO'
    else:
        sma200 = df['close'].rolling(200).mean().iloc[-1]
        preco = df['close'].iloc[-1]
        if pd.isna(adx_atual):
            regime = 'INDEFINIDO'
        elif adx_atual < 20:
            regime = 'CHOP'
        elif preco > sma200:
            regime = 'BULL'
        else:
            regime = 'BEAR'

    return {
        'regime': regime,
        'adx': round(adx_atual, 1) if not pd.isna(adx_atual) else None,
        'volatilidade': volatilidade
    }

def contexto_tempo(distancia_alvo, df):
    """
    Calcula o horizonte de tempo estimado com base na distância percentual até o alvo e na ADR.
    distancia_alvo: float (percentual, ex: 1.5)
    df: DataFrame com dados de preço.
    Retorna string descritiva.
    """
    # ADR: amplitude média dos ranges das últimas 24 velas (1 dia em 1h)
    high = df['high']
    low = df['low']
    range_diario = high - low
    adr = range_diario.tail(24).mean()
    preco_atual = df['close'].iloc[-1]
    adr_percent = (adr / preco_atual) * 100

    if pd.isna(adr_percent) or adr_percent == 0:
        return 'Indisponível'

    if distancia_alvo < adr_percent / 3:
        return 'Rápido (Day/Scalping)'
    elif distancia_alvo < 2 * adr_percent / 3:
        return 'Médio (Swing)'
    else:
        return 'Longo (Position)'
