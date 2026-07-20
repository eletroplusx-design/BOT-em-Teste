from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from domain import DataSource

from .errors import (
    HistoricalDataValidationError,
    MarketDataHTTPError,
    MarketDataJSONError,
    MarketDataNetworkError,
    MarketDataRateLimitError,
)
from .provider_qualification import HistoricalProviderQualification


class KuCoinPublicSpotKlinesProvider:
    base_url = "https://api.kucoin.com/api/v1/market/candles"
    trusted_market_data_provider = True
    historical_source = DataSource.KUCOIN
    provider_identity = "kucoin.public.klines"
    provider_version = "v1"
    historical_market_type = "spot"
    historical_exchange = "kucoin"
    historical_access_type = "public_no_auth"
    historical_data_contract_version = 2
    historical_symbol = "BTCUSDT"
    historical_external_symbol = "BTC-USDT"
    historical_interval = "1h"
    historical_endpoint_documentation = "https://www.kucoin.com/docs-new/3470071w0"
    historical_close_time_rule = "open_time + 1h - 1ms"
    historical_pagination_limit = 1500

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
        return HistoricalProviderQualification.kucoin_public_spot(
            symbol=normalized_symbol,
            interval=normalized_interval,
            provider_version=self.provider_version,
            data_contract_version=self.historical_data_contract_version,
        )

    def _request_params(self, symbol: str, interval: str, limit: int, start_time: int | None, end_time: int | None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "symbol": self.historical_external_symbol,
            "type": "1hour",
            "limit": limit,
        }
        if start_time is not None:
            params["startAt"] = int(start_time // 1000)
        if end_time is not None:
            params["endAt"] = int(end_time // 1000)
        return params

    def fetch_klines(self, symbol: str, interval: str, limit: int = 1500, *, start_time: int | None = None, end_time: int | None = None) -> list[Any]:
        if not isinstance(symbol, str) or not isinstance(interval, str):
            raise HistoricalDataValidationError("historical provider requires valid symbol and interval.")
        normalized_symbol = symbol.strip().upper()
        normalized_interval = interval.strip()
        if normalized_symbol != self.historical_symbol or normalized_interval != self.historical_interval:
            raise HistoricalDataValidationError("historical provider only supports BTCUSDT 1h.")
        if type(limit) is not int or isinstance(limit, bool):
            raise HistoricalDataValidationError("limit must be an integer.")
        if limit <= 0:
            raise HistoricalDataValidationError("limit must be greater than zero.")
        if limit > self.historical_pagination_limit:
            raise HistoricalDataValidationError(f"limit must be <= {self.historical_pagination_limit}.")
        params = self._request_params(normalized_symbol, normalized_interval, limit, start_time, end_time)
        try:
            response = self.session.get(self.base_url, params=params, timeout=self.timeout)
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
        if not isinstance(payload, dict):
            raise MarketDataJSONError("Malformed payload.")
        if str(payload.get("code")) != "200000":
            raise MarketDataHTTPError(f"KuCoin error {payload.get('code')!r}.")
        data = payload.get("data")
        if data is None:
            raise MarketDataJSONError("Malformed payload.")
        if not isinstance(data, list):
            raise MarketDataJSONError("Malformed payload.")
        normalized_rows: list[list[Any]] = []
        for row in data:
            if not isinstance(row, (list, tuple)) or len(row) < 7:
                raise MarketDataJSONError("Malformed payload.")
            try:
                open_time_seconds = int(row[0])
                open_time = datetime.fromtimestamp(open_time_seconds, tz=timezone.utc)
            except (TypeError, ValueError, OverflowError, OSError) as exc:
                raise MarketDataJSONError("Invalid timestamp in kline payload.") from exc
            close_time = open_time + timedelta(hours=1) - timedelta(milliseconds=1)
            normalized_rows.append(
                [
                    int(open_time.timestamp() * 1000),
                    row[1],
                    row[3],
                    row[4],
                    row[2],
                    row[5],
                    int(close_time.timestamp() * 1000),
                    0,
                    0,
                    0,
                    0,
                    0,
                ]
            )
        normalized_rows.sort(key=lambda item: item[0])
        return normalized_rows
