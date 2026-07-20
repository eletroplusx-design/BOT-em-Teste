from __future__ import annotations

import json
from typing import Any

import requests

from .provider_qualification import HistoricalProviderQualification
from .errors import (
    HistoricalDataValidationError,
    MarketDataHTTPError,
    MarketDataJSONError,
    MarketDataNetworkError,
    MarketDataRateLimitError,
)


class BinancePublicKlinesProvider:
    base_url = "https://api.binance.com/api/v3/klines"
    trusted_market_data_provider = True
    provider_identity = "binance.public.klines"
    provider_version = "v1"
    historical_market_type = "spot"
    historical_exchange = "binance"
    historical_access_type = "public_no_auth"
    historical_data_contract_version = 1
    historical_symbol = "BTCUSDT"
    historical_interval = "1h"

    def __init__(self, *, timeout: tuple[float, float] = (5.0, 10.0), session: requests.sessions.Session | None = None):
        self.timeout = timeout
        self.session = session or requests.Session()

    def historical_qualification(self, symbol: str = "BTCUSDT", interval: str = "1h") -> HistoricalProviderQualification:
        if not isinstance(symbol, str) or not isinstance(interval, str):
            raise HistoricalDataValidationError("historical provider requires valid symbol and interval.")
        normalized_symbol = symbol.strip().upper()
        normalized_interval = interval.strip()
        if normalized_symbol != self.historical_symbol or normalized_interval != self.historical_interval:
            raise HistoricalDataValidationError("historical provider only supports BTCUSDT 1h.")
        return HistoricalProviderQualification.binance_public_spot(
            symbol=normalized_symbol,
            interval=normalized_interval,
            provider_version=self.provider_version,
            data_contract_version=self.historical_data_contract_version,
        )

    def fetch_klines(self, symbol: str, interval: str, limit: int = 500, *, start_time: int | None = None, end_time: int | None = None) -> list[Any]:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        try:
            response = self.session.get(
                self.base_url,
                params=params,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise MarketDataNetworkError("Timeout while fetching market data.") from exc
        except requests.RequestException as exc:
            raise MarketDataNetworkError("Network error while fetching market data.") from exc

        if response.status_code == 429:
            raise MarketDataRateLimitError("Rate limit reached.")
        if not response.ok:
            raise MarketDataHTTPError(f"HTTP error {response.status_code}.")

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise MarketDataJSONError("Invalid JSON payload.") from exc

        if not isinstance(payload, list):
            raise MarketDataJSONError("Malformed payload.")

        return payload
