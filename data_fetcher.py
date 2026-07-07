import requests
import pandas as pd

def baixar_dados_btc(simbolo="BTCUSDT", intervalo="1h", limite=500):
    """
    Baixa as últimas 'limite' velas de 'intervalo' do par 'simbolo'
    da Binance (API pública) e retorna um DataFrame pandas.
    Colunas: datetime, open, high, low, close, volume.
    """
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": simbolo,
        "interval": intervalo,
        "limit": limite
    }

    try:
        resposta = requests.get(url, params=params)
        resposta.raise_for_status()
        dados = resposta.json()
    except requests.exceptions.RequestException as erro:
        print(f"❌ Erro ao baixar dados da Binance: {erro}")
        return pd.DataFrame()

    # Cada vela é uma lista com:
    # [abertura_tempo, open, high, low, close, volume, ...]
    colunas = [
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ]

    df = pd.DataFrame(dados, columns=colunas)

    # Converter timestamp (ms) para datetime
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")

    # Selecionar e converter tipos
    df = df[["datetime", "open", "high", "low", "close", "volume"]]
    df = df.astype({
        "open": float,
        "high": float,
        "low": float,
        "close": float,
        "volume": float
    })

    return df