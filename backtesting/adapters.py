from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Sequence

import pandas as pd

from domain import Candle, DataSource, Direction, PaperOrder, Signal, TradingMode, OrderStatus
from domain.serialization import serialize_value
from domain.validation import DomainValidationError

from .errors import BacktestDataError, BacktestExecutionError
from .models import BacktestConfig, BacktestResult, EquityPoint, ExecutedTrade, IntrabarPolicy, PortfolioSnapshot


def dataframe_to_candles(df: pd.DataFrame, *, symbol: str, interval: str, source: DataSource = DataSource.PAPER) -> tuple[Candle, ...]:
    if df is None or df.empty:
        return tuple()
    required = {"open_time", "close_time", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise BacktestDataError(f"Missing candle columns: {sorted(missing)!r}")
    candles = []
    for row in df.to_dict("records"):
        try:
            candles.append(
                Candle.from_dict(
                    {
                        "open_time": row["open_time"],
                        "close_time": row["close_time"],
                        "open": row["open"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": row["close"],
                        "volume": row["volume"],
                        "symbol": symbol,
                        "interval": interval,
                        "source": source,
                    }
                )
            )
        except Exception as exc:
            raise BacktestDataError("Invalid candle frame.") from exc
    return tuple(candles)


def _signal_to_order(signal: Signal, *, capital: Decimal, risk_percent: Decimal) -> PaperOrder:
    distance = abs(signal.entry - signal.stop_loss)
    if distance <= 0:
        raise BacktestExecutionError("Signal stop distance must be positive.")
    risk_amount = capital * (risk_percent / Decimal("100"))
    quantity = risk_amount / distance
    return PaperOrder.from_dict(
        {
            "symbol": signal.symbol,
            "direction": signal.direction,
            "entry": signal.entry,
            "quantity": quantity,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "opened_at": signal.timestamp,
            "status": OrderStatus.OPEN,
            "source": DataSource.PAPER,
            "paper": True,
            "trading_mode": TradingMode.PAPER,
        }
    )


def strategy_output_to_order(output, *, capital: Decimal, risk_percent: Decimal) -> PaperOrder | None:
    if output is None:
        return None
    if isinstance(output, PaperOrder):
        return output
    if isinstance(output, Signal):
        return _signal_to_order(output, capital=capital, risk_percent=risk_percent)
    if isinstance(output, dict):
        if {"symbol", "direction", "entry", "stop_loss", "take_profit", "timestamp"}.issubset(output):
            signal = Signal.from_dict(output)
            return _signal_to_order(signal, capital=capital, risk_percent=risk_percent)
        return PaperOrder.from_dict(output)
    raise BacktestExecutionError(f"Unsupported strategy output: {type(output)!r}")


def backtest_result_to_dict(result: BacktestResult) -> dict:
    return serialize_value(result.to_dict())
