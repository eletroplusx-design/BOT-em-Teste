import os
import sqlite3
import tempfile

import pandas as pd
import pytest


@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {
            "open": [60000, 60100, 60200, 60300, 60400],
            "high": [60100, 60200, 60300, 60400, 60500],
            "low": [59900, 60000, 60100, 60200, 60300],
            "close": [60050, 60150, 60250, 60350, 60450],
            "volume": [100, 110, 120, 130, 140],
            "timestamp": pd.date_range("2026-01-01", periods=5, freq="h"),
        }
    )


@pytest.fixture
def sample_btc_data():
    rows = 1200
    closes = []
    for idx in range(rows):
        bloco = idx % 40
        if bloco < 20:
            closes.append(50000 + bloco * 15)
        else:
            closes.append(50300 - (bloco - 20) * 15)
    base = pd.DataFrame(
        {
            "open_time": pd.date_range("2025-01-01", periods=rows, freq="h", tz="UTC"),
            "close_time": pd.date_range("2025-01-01", periods=rows, freq="h", tz="UTC"),
            "open": [valor - 5 for valor in closes],
            "high": [valor + 15 for valor in closes],
            "low": [valor - 20 for valor in closes],
            "close": closes,
            "volume": [1000 + (idx % 50) * 10 for idx in range(rows)],
        }
    )
    base.attrs["fonte_dados"] = "BINANCE"
    return base


@pytest.fixture
def trend_df():
    rows = 220
    closes = []
    for idx in range(rows):
        bloco = idx % 20
        if bloco < 10:
            closes.append(100 + bloco * 2)
        else:
            closes.append(120 - (bloco - 10) * 2)
    base = pd.DataFrame(
        {
            "open": [valor - 1 for valor in closes],
            "high": [valor + 1 for valor in closes],
            "low": [valor - 2 for valor in closes],
            "close": closes,
            "volume": [1000 + i for i in range(rows)],
            "timestamp": pd.date_range("2026-01-01", periods=rows, freq="h"),
        }
    )
    return base


@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path


@pytest.fixture
def mock_binance_exchange_info():
    return {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "1000"},
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01", "minPrice": "0.01", "maxPrice": "1000000"},
                    {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                ],
            }
        ]
    }
