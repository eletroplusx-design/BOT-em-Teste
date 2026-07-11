from __future__ import annotations

import logging

import pandas as pd

from market_data import (
    MarketDataError,
    MarketDataExpiredError,
    trusted_market_data_service,
)
from market_data.service import package_to_dataframe


def baixar_candles_confiaveis(simbolo: str = "BTCUSDT", intervalo: str = "1h", limite: int = 500):
    return trusted_market_data_service.fetch(simbolo, intervalo, limite)


def baixar_dados_btc(simbolo="BTCUSDT", intervalo="1h", limite=500):
    """
    Adaptador legado: baixa candles confiáveis e devolve DataFrame pandas.
    Quando a camada de mercado falha, retorna DataFrame vazio sem inventar preço.
    """
    try:
        pacote = baixar_candles_confiaveis(simbolo, intervalo, limite)
        df = package_to_dataframe(pacote)
        df.attrs["fonte_dados"] = "BINANCE"
        df.attrs["cache_status"] = pacote.cache_status
        df.attrs["expired"] = pacote.expired
        return df
    except MarketDataExpiredError as erro:
        logging.warning(f"Dados de mercado expirados: {erro}")
        print(f"âŒ Erro ao baixar dados da Binance: {erro}")
        return pd.DataFrame()
    except MarketDataError as erro:
        logging.warning(f"Erro ao baixar dados confiáveis: {erro}")
        print(f"âŒ Erro ao baixar dados da Binance: {erro}")
        return pd.DataFrame()
    except Exception as erro:
        logging.warning(f"Erro inesperado ao baixar dados: {erro}")
        print(f"âŒ Erro ao baixar dados da Binance: {erro}")
        return pd.DataFrame()
