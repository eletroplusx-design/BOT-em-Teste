from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping

from domain.serialization import serialize_value

from .errors import HistoricalDataValidationError


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalDataValidationError(f"{field_name} is required.")
    return value.strip()


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalDataValidationError(f"{field_name} must be an integer.")
    if value <= 0:
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
        if self.time_semantics != "utc":
            raise HistoricalDataValidationError("time_semantics must be utc.")
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalProviderQualification":
        if not isinstance(data, Mapping):
            raise HistoricalDataValidationError("provider qualification must be a mapping.")
        mapping = dict(data)
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
                qualification_hash=mapping.get("qualification_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalDataValidationError("provider qualification is incomplete.") from exc

    def canonical_payload(self) -> dict[str, Any]:
        return {
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

    def as_dict(self) -> dict[str, Any]:
        payload = self.canonical_payload()
        payload["qualification_hash"] = self.qualification_hash
        return payload

    def requires_spot(self) -> bool:
        return self.market_type == "spot"

