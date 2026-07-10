import pandas as pd
import requests


def baixar_dados_btc(simbolo="BTCUSDT", intervalo="1h", limite=500):
    """
    Baixa as ultimas 'limite' velas de 'intervalo' do par 'simbolo'
    da Binance (API publica) e retorna um DataFrame pandas.
    Colunas: datetime, open, high, low, close, volume.
    """
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": simbolo,
        "interval": intervalo,
        "limit": limite,
    }

    try:
        resposta = requests.get(url, params=params, timeout=10)
        resposta.raise_for_status()
        dados = resposta.json()
    except Exception as erro:
        print(f"❌ Erro ao baixar dados da Binance: {erro}")
        return pd.DataFrame()

    colunas = [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "trades",
        "taker_buy_base",
        "taker_buy_quote",
        "ignore",
    ]

    df = pd.DataFrame(dados, columns=colunas)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
    df = df[["datetime", "open", "high", "low", "close", "volume"]]
    df = df.astype(
        {
            "open": float,
            "high": float,
            "low": float,
            "close": float,
            "volume": float,
        }
    )
    df.attrs["fonte_dados"] = "BINANCE"
    return df
