from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple

from domain import Candle, MarketSnapshot


@dataclass(frozen=True, slots=True)
class MarketDataCacheEntry:
    symbol: str
    interval: str
    candles: tuple[Candle, ...]
    snapshot: MarketSnapshot
    stored_at: datetime
    ttl_seconds: int

    @property
    def expires_at(self) -> datetime:
        return self.stored_at + timedelta(seconds=self.ttl_seconds)

    @property
    def expired(self) -> bool:
        now = datetime.now(timezone.utc)
        return now >= self.expires_at


class MarketDataCache:
    def __init__(self, ttl_seconds: int = 300, max_entries: int = 64):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: Dict[Tuple[str, str], MarketDataCacheEntry] = {}

    def get(self, symbol: str, interval: str) -> MarketDataCacheEntry | None:
        key = (symbol.upper(), interval)
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expired:
            self._entries.pop(key, None)
            return None
        return entry

    def peek(self, symbol: str, interval: str) -> MarketDataCacheEntry | None:
        return self._entries.get((symbol.upper(), interval))

    def status(self, symbol: str, interval: str) -> str:
        entry = self.peek(symbol, interval)
        if entry is None:
            return "miss"
        return "expired" if entry.expired else "hit"

    def set(self, symbol: str, interval: str, candles: tuple[Candle, ...], snapshot: MarketSnapshot) -> MarketDataCacheEntry:
        key = (symbol.upper(), interval)
        if len(self._entries) >= self.max_entries and key not in self._entries:
            oldest_key = min(self._entries.items(), key=lambda item: item[1].stored_at)[0]
            self._entries.pop(oldest_key, None)
        entry = MarketDataCacheEntry(
            symbol=symbol.upper(),
            interval=interval,
            candles=tuple(candles),
            snapshot=snapshot,
            stored_at=datetime.now(timezone.utc),
            ttl_seconds=self.ttl_seconds,
        )
        self._entries[key] = entry
        return entry

    def clear(self) -> None:
        self._entries.clear()

    def discard(self, symbol: str, interval: str) -> None:
        self._entries.pop((symbol.upper(), interval), None)
