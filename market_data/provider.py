from __future__ import annotations

import json
from typing import Any

import requests

from .errors import (
    MarketDataHTTPError,
    MarketDataJSONError,
    MarketDataNetworkError,
    MarketDataRateLimitError,
)


class BinancePublicKlinesProvider:
    base_url = "https://api.binance.com/api/v3/klines"

    def __init__(self, *, timeout: tuple[float, float] = (5.0, 10.0), session: requests.sessions.Session | None = None):
        self.timeout = timeout
        self.session = session or requests.Session()

    def fetch_klines(self, symbol: str, interval: str, limit: int = 500) -> list[Any]:
        try:
            response = self.session.get(
                self.base_url,
                params={"symbol": symbol, "interval": interval, "limit": limit},
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
