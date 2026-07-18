from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from domain import Candle, MarketSnapshot

from .cache import MarketDataCache
from .errors import MarketDataExpiredError, MarketDataError, MarketDataValidationError
from .normalization import candles_to_dataframe, candles_to_market_snapshot
from .provider import BinancePublicKlinesProvider
from .validation import MAX_BINANCE_LIMIT, validate_klines_payload, validate_limit, validate_market_data_consistency, validate_symbol_interval


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
    synthetic_test_data: bool = False

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
            synthetic_test_data=False,
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
            synthetic_test_data=package.synthetic_test_data,
        )

    def _candles_to_payload(self, candles: tuple[Candle, ...]) -> list[list[Any]]:
        payload: list[list[Any]] = []
        for candle in candles:
            payload.append(
                [
                    int(candle.open_time.timestamp() * 1000),
                    str(candle.open),
                    str(candle.high),
                    str(candle.low),
                    str(candle.close),
                    str(candle.volume),
                    int(candle.close_time.timestamp() * 1000),
                    0,
                    0,
                    0,
                    0,
                    0,
                ]
            )
        return payload

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
                        synthetic_test_data=False,
                    )
                    return self._package_for_limit(cached_package, limit, "hit")

        request_limit = min(limit + 1, MAX_BINANCE_LIMIT) if limit < MAX_BINANCE_LIMIT else limit
        payload = self.provider.fetch_klines(symbol, interval, request_limit)
        candles = validate_klines_payload(payload, symbol=symbol, interval=interval, now=now)
        validate_market_data_consistency(candles, max_age_seconds=self.max_age_seconds, now=now)
        if len(candles) < limit:
            if limit != MAX_BINANCE_LIMIT or len(candles) < limit - 1 or not candles:
                raise MarketDataValidationError("Not enough closed candles available.")
            previous_end_time = int((candles[0].open_time - timedelta(milliseconds=1)).timestamp() * 1000)
            fallback_payload = self.provider.fetch_klines(symbol, interval, 1, end_time=previous_end_time)
            fallback_candles = validate_klines_payload(fallback_payload, symbol=symbol, interval=interval, now=now)
            if len(fallback_candles) != 1:
                raise MarketDataValidationError("Not enough closed candles available.")
            merged = fallback_candles + candles
            merged = validate_klines_payload(self._candles_to_payload(tuple(merged)), symbol=symbol, interval=interval, now=now)
            validate_market_data_consistency(merged, max_age_seconds=self.max_age_seconds, now=now)
            candles = merged
            if len(candles) < limit:
                raise MarketDataValidationError("Not enough closed candles available.")
        snapshot = candles_to_market_snapshot(candles)
        entry = self.cache.set(symbol, interval, tuple(candles), snapshot)
        full_package = MarketDataPackage(
            symbol=symbol,
            interval=interval,
            candles=entry.candles,
            snapshot=entry.snapshot,
            source=entry.snapshot.source.value if hasattr(entry.snapshot.source, "value") else str(entry.snapshot.source),
            fetched_at=entry.stored_at,
            expires_at=entry.expires_at,
            cache_status="miss",
            synthetic_test_data=False,
        )
        return self._package_for_limit(full_package, limit, "miss")


trusted_market_data_service = TrustedMarketDataService()


def package_to_dataframe(package: MarketDataPackage):
    return candles_to_dataframe(package.candles)
