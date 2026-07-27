from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping

from domain.serialization import serialize_value

from .errors import HistoricalDataValidationError


KUCOIN_PUBLIC_SPOT_INTERVALS: tuple[str, ...] = ("15m", "1h", "4h")
KUCOIN_PUBLIC_SPOT_INTERVAL_CODES: dict[str, str] = {
    "15m": "15min",
    "1h": "1hour",
    "4h": "4hour",
}
KUCOIN_PUBLIC_SPOT_INTERVAL_SECONDS: dict[str, int] = {
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
}
_KUCOIN_PUBLIC_SPOT_INTERVAL_CLOSE_TIME_RULE = "open_time + interval_duration_seconds - 1ms"
OKX_PUBLIC_SPOT_ENDPOINT_URL = "https://www.okx.com/api/v5/market/history-candles"
OKX_PUBLIC_SPOT_DOCUMENTATION_URL = "https://www.okx.com/docs-v5/en/"
OKX_PUBLIC_SPOT_PAGINATION_LIMIT = 100
OKX_PUBLIC_SPOT_CLOSE_TIME_RULE = "confirm=0 means incomplete; confirm=1 means completed"


def kucoin_public_spot_interval_contract(interval: str) -> tuple[str, int]:
    normalized_interval = _require_str(interval, "interval")
    if normalized_interval not in KUCOIN_PUBLIC_SPOT_INTERVALS:
        raise HistoricalDataValidationError("kucoin public spot provider only supports BTCUSDT 15m, 1h, or 4h.")
    return (
        KUCOIN_PUBLIC_SPOT_INTERVAL_CODES[normalized_interval],
        KUCOIN_PUBLIC_SPOT_INTERVAL_SECONDS[normalized_interval],
    )


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalDataValidationError(f"{field_name} is required.")
    return value.strip()


def _require_optional_str(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_str(value, field_name)


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalDataValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalDataValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalDataValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_market_type(value: Any) -> str:
    market_type = _require_str(value, "market_type").lower()
    if market_type not in {"spot", "futures"}:
        raise HistoricalDataValidationError("market_type must be spot or futures.")
    return market_type


def _require_access_type(value: Any) -> str:
    access_type = _require_str(value, "access_type").lower()
    if access_type != "public_no_auth":
        raise HistoricalDataValidationError("access_type must be public_no_auth.")
    return access_type


def _require_http_url(value: Any, field_name: str) -> str:
    url = _require_str(value, field_name)
    if not url.lower().startswith(("https://", "http://")):
        raise HistoricalDataValidationError(f"{field_name} must be a URL.")
    return url


@dataclass(frozen=True, slots=True)
class HistoricalProviderQualification:
    provider_id: str
    provider_version: str
    market_type: str
    exchange: str
    symbol: str
    interval: str
    time_semantics: str
    access_type: str
    data_contract_version: int
    external_symbol: str = ""
    interval_code: str = ""
    interval_duration_seconds: int = 0
    endpoint_url: str = ""
    documentation_url: str = ""
    pagination_limit: int = 0
    close_time_rule: str = ""
    qualification_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _require_str(self.provider_id, "provider_id"))
        object.__setattr__(self, "provider_version", _require_str(self.provider_version, "provider_version"))
        object.__setattr__(self, "market_type", _require_market_type(self.market_type))
        object.__setattr__(self, "exchange", _require_str(self.exchange, "exchange").lower())
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "time_semantics", _require_str(self.time_semantics, "time_semantics").lower())
        object.__setattr__(self, "access_type", _require_access_type(self.access_type))
        object.__setattr__(self, "data_contract_version", _require_int(self.data_contract_version, "data_contract_version"))
        object.__setattr__(self, "external_symbol", _require_optional_str(self.external_symbol, "external_symbol").upper())
        object.__setattr__(self, "interval_code", _require_optional_str(self.interval_code, "interval_code").lower())
        object.__setattr__(self, "interval_duration_seconds", _require_int(self.interval_duration_seconds, "interval_duration_seconds", allow_zero=True))
        object.__setattr__(self, "endpoint_url", _require_optional_str(self.endpoint_url, "endpoint_url"))
        object.__setattr__(self, "documentation_url", _require_optional_str(self.documentation_url, "documentation_url"))
        object.__setattr__(self, "pagination_limit", _require_int(self.pagination_limit, "pagination_limit", allow_zero=True))
        object.__setattr__(self, "close_time_rule", _require_optional_str(self.close_time_rule, "close_time_rule"))
        if self.time_semantics != "utc":
            raise HistoricalDataValidationError("time_semantics must be utc.")
        if self.data_contract_version == 1:
            if any((self.external_symbol, self.interval_code, self.interval_duration_seconds, self.endpoint_url, self.documentation_url, self.pagination_limit, self.close_time_rule)):
                raise HistoricalDataValidationError("data_contract_version 1 does not allow extended provider metadata.")
        elif self.data_contract_version == 2:
            if not self.external_symbol:
                raise HistoricalDataValidationError("external_symbol is required for provider contract version 2.")
            if self.external_symbol == self.symbol:
                raise HistoricalDataValidationError("external_symbol must differ from canonical symbol for version 2.")
            if self.interval_code or self.interval_duration_seconds:
                raise HistoricalDataValidationError("data_contract_version 2 does not allow interval_code or interval_duration_seconds.")
            if not self.endpoint_url:
                raise HistoricalDataValidationError("endpoint_url is required for provider contract version 2.")
            if not self.documentation_url:
                raise HistoricalDataValidationError("documentation_url is required for provider contract version 2.")
            if self.pagination_limit <= 0:
                raise HistoricalDataValidationError("pagination_limit is required for provider contract version 2.")
            if not self.close_time_rule:
                raise HistoricalDataValidationError("close_time_rule is required for provider contract version 2.")
        elif self.data_contract_version == 3:
            expected_interval_code, expected_duration_seconds = kucoin_public_spot_interval_contract(self.interval)
            if self.external_symbol != "BTC-USDT":
                raise HistoricalDataValidationError("external_symbol is required for provider contract version 3.")
            if self.external_symbol == self.symbol:
                raise HistoricalDataValidationError("external_symbol must differ from canonical symbol for version 3.")
            if self.interval_code != expected_interval_code:
                raise HistoricalDataValidationError("interval_code mismatch for provider contract version 3.")
            if self.interval_duration_seconds != expected_duration_seconds:
                raise HistoricalDataValidationError("interval_duration_seconds mismatch for provider contract version 3.")
            if not self.endpoint_url:
                raise HistoricalDataValidationError("endpoint_url is required for provider contract version 3.")
            if not self.documentation_url:
                raise HistoricalDataValidationError("documentation_url is required for provider contract version 3.")
            if self.pagination_limit <= 0:
                raise HistoricalDataValidationError("pagination_limit is required for provider contract version 3.")
            if self.close_time_rule != _KUCOIN_PUBLIC_SPOT_INTERVAL_CLOSE_TIME_RULE:
                raise HistoricalDataValidationError("close_time_rule is required for provider contract version 3.")
        else:
            raise HistoricalDataValidationError("data_contract_version must be greater than zero.")
        if self.qualification_hash:
            object.__setattr__(self, "qualification_hash", _require_str(self.qualification_hash, "qualification_hash"))
            if self.qualification_hash != _hash_payload(self.canonical_payload()):
                raise HistoricalDataValidationError("qualification_hash mismatch.")
        else:
            object.__setattr__(self, "qualification_hash", _hash_payload(self.canonical_payload()))

    @classmethod
    def binance_public_spot(
        cls,
        *,
        symbol: str = "BTCUSDT",
        interval: str = "1h",
        provider_version: str = "v1",
        data_contract_version: int = 1,
    ) -> "HistoricalProviderQualification":
        normalized_symbol = _require_str(symbol, "symbol").upper()
        normalized_interval = _require_str(interval, "interval")
        if normalized_symbol != "BTCUSDT" or normalized_interval != "1h":
            raise HistoricalDataValidationError("binance public spot provider only supports BTCUSDT 1h.")
        return cls(
            provider_id="binance.public.klines",
            provider_version=provider_version,
            market_type="spot",
            exchange="binance",
            symbol=normalized_symbol,
            interval=normalized_interval,
            time_semantics="utc",
            access_type="public_no_auth",
            data_contract_version=data_contract_version,
        )

    @classmethod
    def kucoin_public_spot(
        cls,
        *,
        symbol: str = "BTCUSDT",
        interval: str = "1h",
        provider_version: str = "v1",
        data_contract_version: int | None = None,
    ) -> "HistoricalProviderQualification":
        normalized_symbol = _require_str(symbol, "symbol").upper()
        normalized_interval = _require_str(interval, "interval")
        if normalized_symbol != "BTCUSDT":
            raise HistoricalDataValidationError("kucoin public spot provider only supports BTCUSDT.")
        interval_code, interval_duration_seconds = kucoin_public_spot_interval_contract(normalized_interval)
        if normalized_interval == "1h":
            expected_version = 2
            expected_close_time_rule = "open_time + 1h - 1ms"
        else:
            expected_version = 3
            expected_close_time_rule = _KUCOIN_PUBLIC_SPOT_INTERVAL_CLOSE_TIME_RULE
        if data_contract_version is None:
            data_contract_version = expected_version
        if data_contract_version != expected_version:
            raise HistoricalDataValidationError("kucoin public spot provider interval is incompatible with the requested contract version.")
        return cls(
            provider_id="kucoin.public.klines",
            provider_version=provider_version,
            market_type="spot",
            exchange="kucoin",
            symbol=normalized_symbol,
            interval=normalized_interval,
            time_semantics="utc",
            access_type="public_no_auth",
            data_contract_version=data_contract_version,
            external_symbol="BTC-USDT",
            interval_code=interval_code if data_contract_version >= 3 else "",
            interval_duration_seconds=interval_duration_seconds if data_contract_version >= 3 else 0,
            endpoint_url="https://api.kucoin.com/api/v1/market/candles",
            documentation_url="https://www.kucoin.com/docs-new/3470071w0",
            pagination_limit=1500,
            close_time_rule=expected_close_time_rule,
        )

    @classmethod
    def okx_public_spot(
        cls,
        *,
        symbol: str = "BTCUSDT",
        interval: str = "1H",
        provider_version: str = "v1",
        data_contract_version: int = 2,
    ) -> "HistoricalProviderQualification":
        normalized_symbol = _require_str(symbol, "symbol").upper()
        normalized_interval = _require_str(interval, "interval")
        if normalized_symbol != "BTCUSDT" or normalized_interval != "1H":
            raise HistoricalDataValidationError("okx public spot provider only supports BTCUSDT 1H.")
        if data_contract_version != 2:
            raise HistoricalDataValidationError("okx public spot provider only supports contract version 2.")
        return cls(
            provider_id="okx.public.klines",
            provider_version=provider_version,
            market_type="spot",
            exchange="okx",
            symbol=normalized_symbol,
            interval=normalized_interval,
            time_semantics="utc",
            access_type="public_no_auth",
            data_contract_version=data_contract_version,
            external_symbol="BTC-USDT",
            endpoint_url=OKX_PUBLIC_SPOT_ENDPOINT_URL,
            documentation_url=OKX_PUBLIC_SPOT_DOCUMENTATION_URL,
            pagination_limit=OKX_PUBLIC_SPOT_PAGINATION_LIMIT,
            close_time_rule=OKX_PUBLIC_SPOT_CLOSE_TIME_RULE,
        )

    @classmethod
    def expected_for_provider(cls, provider_id: str, *, symbol: str, interval: str) -> "HistoricalProviderQualification":
        provider_id = _require_str(provider_id, "provider_id")
        if provider_id == "binance.public.klines":
            return cls.binance_public_spot(symbol=symbol, interval=interval)
        if provider_id == "kucoin.public.klines":
            return cls.kucoin_public_spot(symbol=symbol, interval=interval)
        if provider_id == "okx.public.klines":
            return cls.okx_public_spot(symbol=symbol, interval=interval)
        raise HistoricalDataValidationError("unsupported historical provider.")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalProviderQualification":
        if not isinstance(data, Mapping):
            raise HistoricalDataValidationError("provider qualification must be a mapping.")
        mapping = dict(data)
        version = mapping.get("data_contract_version")
        allowed = {
            "provider_id",
            "provider_version",
            "market_type",
            "exchange",
            "symbol",
            "interval",
            "time_semantics",
            "access_type",
            "data_contract_version",
            "external_symbol",
            "endpoint_url",
            "documentation_url",
            "pagination_limit",
            "close_time_rule",
            "qualification_hash",
        }
        if version == 3:
            allowed.update({"interval_code", "interval_duration_seconds"})
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise HistoricalDataValidationError(f"unexpected provider qualification fields: {', '.join(extra)}.")
        try:
            return cls(
                provider_id=mapping["provider_id"],
                provider_version=mapping["provider_version"],
                market_type=mapping["market_type"],
                exchange=mapping["exchange"],
                symbol=mapping["symbol"],
                interval=mapping["interval"],
                time_semantics=mapping["time_semantics"],
                access_type=mapping["access_type"],
                data_contract_version=mapping["data_contract_version"],
                external_symbol=mapping.get("external_symbol", ""),
                interval_code=mapping.get("interval_code", ""),
                interval_duration_seconds=mapping.get("interval_duration_seconds", 0),
                endpoint_url=mapping.get("endpoint_url", ""),
                documentation_url=mapping.get("documentation_url", ""),
                pagination_limit=mapping.get("pagination_limit", 0),
                close_time_rule=mapping.get("close_time_rule", ""),
                qualification_hash=mapping.get("qualification_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalDataValidationError("provider qualification is incomplete.") from exc

    def canonical_payload(self) -> dict[str, Any]:
        payload = {
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "market_type": self.market_type,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "interval": self.interval,
            "time_semantics": self.time_semantics,
            "access_type": self.access_type,
            "data_contract_version": self.data_contract_version,
        }
        if self.data_contract_version >= 2:
            payload["external_symbol"] = self.external_symbol
        if self.data_contract_version == 2:
            payload.update(
                {
                    "endpoint_url": self.endpoint_url,
                    "documentation_url": self.documentation_url,
                    "pagination_limit": self.pagination_limit,
                    "close_time_rule": self.close_time_rule,
                }
            )
        if self.data_contract_version >= 3:
            payload.update(
                {
                    "interval_code": self.interval_code,
                    "interval_duration_seconds": self.interval_duration_seconds,
                    "endpoint_url": self.endpoint_url,
                    "documentation_url": self.documentation_url,
                    "pagination_limit": self.pagination_limit,
                    "close_time_rule": self.close_time_rule,
                }
            )
        return payload

    def as_dict(self) -> dict[str, Any]:
        payload = self.canonical_payload()
        payload["qualification_hash"] = self.qualification_hash
        return payload

    def requires_spot(self) -> bool:
        return self.market_type == "spot"

    def matches_symbol_interval(self, *, symbol: str, interval: str) -> bool:
        return self.symbol == _require_str(symbol, "symbol").upper() and self.interval == _require_str(interval, "interval")

    def matches_provider(self, provider_id: str) -> bool:
        return self.provider_id == _require_str(provider_id, "provider_id")
