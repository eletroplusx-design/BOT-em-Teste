from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from domain import Candle, MarketSnapshot

from .cache import MarketDataCache
from .errors import MarketDataExpiredError, MarketDataError, MarketDataValidationError
from .normalization import candles_to_dataframe, candles_to_market_snapshot
from .provider import BinancePublicKlinesProvider
from .validation import validate_klines_payload, validate_limit, validate_market_data_consistency, validate_symbol_interval


@dataclass(frozen=True, slots=True)
class MarketDataPackage:
    symbol: str
    interval: str
    candles: tuple[Candle, ...]
    snapshot: MarketSnapshot
    source: str
    fetched_at: datetime
    expires_at: datetime
    cache_status: str = "miss"

    @property
    def expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at


class TrustedMarketDataService:
    def __init__(
        self,
        *,
        provider: BinancePublicKlinesProvider | None = None,
        cache: MarketDataCache | None = None,
        ttl_seconds: int = 300,
        max_age_seconds: int = 7200,
    ):
        self.provider = provider or BinancePublicKlinesProvider()
        self.cache = cache or MarketDataCache(ttl_seconds=ttl_seconds)
        self.ttl_seconds = ttl_seconds
        self.max_age_seconds = max_age_seconds

    def _build_package(self, candles: list[Candle], symbol: str, interval: str, cache_status: str = "miss") -> MarketDataPackage:
        snapshot = candles_to_market_snapshot(candles)
        now = datetime.now(timezone.utc)
        return MarketDataPackage(
            symbol=symbol,
            interval=interval,
            candles=tuple(candles),
            snapshot=snapshot,
            source=snapshot.source.value if hasattr(snapshot.source, "value") else str(snapshot.source),
            fetched_at=now,
            expires_at=now + timedelta(seconds=self.ttl_seconds),
            cache_status=cache_status,
        )

    def _package_for_limit(self, package: MarketDataPackage, limit: int, cache_status: str) -> MarketDataPackage:
        candles = package.candles[-limit:] if limit < len(package.candles) else package.candles
        snapshot = candles_to_market_snapshot(candles)
        return MarketDataPackage(
            symbol=package.symbol,
            interval=package.interval,
            candles=candles,
            snapshot=snapshot,
            source=snapshot.source.value if hasattr(snapshot.source, "value") else str(snapshot.source),
            fetched_at=package.fetched_at,
            expires_at=package.expires_at,
            cache_status=cache_status,
        )

    def fetch(self, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 500) -> MarketDataPackage:
        symbol, interval = validate_symbol_interval(symbol, interval)
        limit = validate_limit(limit)
        now = datetime.now(timezone.utc)
        cached = self.cache.get(symbol, interval)
        if cached is not None:
            try:
                validate_market_data_consistency(cached.candles, max_age_seconds=self.max_age_seconds, now=now)
            except (MarketDataExpiredError, MarketDataValidationError):
                self.cache.discard(symbol, interval)
            else:
                if len(cached.candles) >= limit:
                    cached_package = MarketDataPackage(
                        symbol=symbol,
                        interval=interval,
                        candles=cached.candles,
                        snapshot=cached.snapshot,
                        source=cached.snapshot.source.value if hasattr(cached.snapshot.source, "value") else str(cached.snapshot.source),
                        fetched_at=cached.stored_at,
                        expires_at=cached.expires_at,
                        cache_status="hit",
                    )
                    return self._package_for_limit(cached_package, limit, "hit")

        payload = self.provider.fetch_klines(symbol, interval, limit)
        candles = validate_klines_payload(payload, symbol=symbol, interval=interval, now=now)
        validate_market_data_consistency(candles, max_age_seconds=self.max_age_seconds, now=now)
        snapshot = candles_to_market_snapshot(candles)
        entry = self.cache.set(symbol, interval, tuple(candles), snapshot)
        return MarketDataPackage(
            symbol=symbol,
            interval=interval,
            candles=entry.candles,
            snapshot=entry.snapshot,
            source=entry.snapshot.source.value if hasattr(entry.snapshot.source, "value") else str(entry.snapshot.source),
            fetched_at=entry.stored_at,
            expires_at=entry.expires_at,
            cache_status="miss",
        )


trusted_market_data_service = TrustedMarketDataService()


def package_to_dataframe(package: MarketDataPackage):
    return candles_to_dataframe(package.candles)
