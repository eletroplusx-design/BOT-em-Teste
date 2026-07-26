from __future__ import annotations

from enum import Enum


class Direction(str, Enum):
    COMPRA = "COMPRA"
    VENDA = "VENDA"


class TradingMode(str, Enum):
    PAPER = "PAPER"


class OrderStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class TradeResultStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    PARTIAL = "partial"


class DataSource(str, Enum):
    BINANCE = "BINANCE"
    KUCOIN = "KUCOIN"
    OKX = "OKX"
    YAHOO = "YAHOO"
    PAPER = "PAPER"
    LEGACY = "LEGACY"
