from __future__ import annotations

from datetime import timezone
from decimal import Decimal
from typing import Sequence

import pandas as pd

from domain import Candle, MarketSnapshot


def candles_to_dataframe(candles: Sequence[Candle]) -> pd.DataFrame:
    if not candles:
        return pd.DataFrame(columns=["open_time", "close_time", "datetime", "open", "high", "low", "close", "volume", "symbol", "interval", "source"])
    rows = []
    for candle in candles:
        rows.append(
            {
                "open_time": candle.open_time,
                "close_time": candle.close_time,
                "datetime": candle.close_time,
                "open": float(candle.open),
                "high": float(candle.high),
                "low": float(candle.low),
                "close": float(candle.close),
                "volume": float(candle.volume),
                "symbol": candle.symbol,
                "interval": candle.interval,
                "source": candle.source.value if hasattr(candle.source, "value") else str(candle.source),
            }
        )
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], utc=True)
    df.attrs["fonte_dados"] = "BINANCE"
    df.attrs["market_data_model"] = "trusted"
    return df


def candles_to_market_snapshot(candles: Sequence[Candle]) -> MarketSnapshot:
    if not candles:
        raise ValueError("No candles available.")
    latest = candles[-1]
    return MarketSnapshot.from_dict(
        {
            "symbol": latest.symbol,
            "timestamp": latest.close_time,
            "current_price": latest.close,
            "source": latest.source,
            "candle": latest.to_dict(),
            "regime": None,
        }
    )


def candles_to_legacy_dataframe(candles: Sequence[Candle]) -> pd.DataFrame:
    return candles_to_dataframe(candles)
