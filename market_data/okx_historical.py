from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

from domain import Candle, DataSource
from domain.serialization import serialize_value

from .errors import (
    HistoricalDataConflictError,
    HistoricalDataIntegrityError,
    HistoricalDataValidationError,
    MarketDataHTTPError,
    MarketDataJSONError,
    MarketDataNetworkError,
    MarketDataRateLimitError,
)
from .historical_manifest import historical_content_hash
from .provider_qualification import (
    HistoricalProviderQualification,
    OKX_PUBLIC_SPOT_CLOSE_TIME_RULE,
    OKX_PUBLIC_SPOT_DOCUMENTATION_URL,
    OKX_PUBLIC_SPOT_ENDPOINT_URL,
    OKX_PUBLIC_SPOT_PAGINATION_LIMIT,
)

OKX_HISTORICAL_ARTIFACT_DIRNAME = "okx"
OKX_HISTORICAL_ARTIFACT_BASENAME = "btc-usdt-1H-2021-02-12-to-2026-01-01"
OKX_HISTORICAL_DATASET_CANDLES_FILENAME = f"{OKX_HISTORICAL_ARTIFACT_BASENAME}.candles.json"
OKX_HISTORICAL_MANIFEST_FILENAME = f"{OKX_HISTORICAL_ARTIFACT_BASENAME}.manifest.json"
OKX_HISTORICAL_REQUESTED_START_INCLUSIVE_UTC = datetime(2021, 2, 12, 0, 0, tzinfo=timezone.utc)
OKX_HISTORICAL_REQUESTED_END_EXCLUSIVE_UTC = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
OKX_HISTORICAL_EXPECTED_FIRST_CANDLE_OPEN_UTC = OKX_HISTORICAL_REQUESTED_START_INCLUSIVE_UTC
OKX_HISTORICAL_EXPECTED_LAST_CANDLE_OPEN_UTC = datetime(2025, 12, 31, 23, 0, tzinfo=timezone.utc)
OKX_HISTORICAL_EXPECTED_CANDLE_COUNT = 42816
OKX_HISTORICAL_REQUEST_LIMIT = OKX_PUBLIC_SPOT_PAGINATION_LIMIT
OKX_HISTORICAL_CONFIRM_REQUIRED_VALUE = 1
OKX_HISTORICAL_CANDLE_INTERVAL = "1H"
OKX_HISTORICAL_SOURCE_NAME = "OKX"
OKX_HISTORICAL_MARKET_TYPE = "spot"
OKX_HISTORICAL_INSTRUMENT = "BTC-USDT"
OKX_HISTORICAL_SYMBOL = "BTCUSDT"
OKX_HISTORICAL_PROVIDER_ID = "okx.public.klines"
OKX_HISTORICAL_PROVIDER_VERSION = "v1"
OKX_HISTORICAL_PROVIDER_EXCHANGE = "okx"
OKX_HISTORICAL_ENDPOINT_PATH = "/api/v5/market/history-candles"
OKX_HISTORICAL_ENDPOINT_METHOD = "GET"
OKX_HISTORICAL_CURSOR_NAME = "after"
OKX_HISTORICAL_CURSOR_EXCLUSIVE = True
OKX_HISTORICAL_COLLECTION_DIRECTION = "reverse_chronological"
OKX_HISTORICAL_NON_INGESTION_SCOPE_STATEMENT = (
    "No replay, backtest, performance comparison, paper trading, or live trading is authorized."
)
OKX_HISTORICAL_CURSOR_SEMANTICS = (
    "after returns candles earlier than the cursor timestamp and the next cursor is the oldest retained open time."
)
OKX_HISTORICAL_ENDPOINT_URL = OKX_PUBLIC_SPOT_ENDPOINT_URL

def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalDataValidationError(f"{field_name} is required.")
    return value.strip()

def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalDataValidationError(f"{field_name} must be a boolean.")
    return value

def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalDataValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalDataValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalDataValidationError(f"{field_name} must be greater than zero.")
    return int(value)

def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.") from exc
    if not isinstance(value, datetime):
        raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)

def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")

def _hour_delta() -> timedelta:
    return timedelta(hours=1)

def _expected_candle_count(start: datetime, end_exclusive: datetime) -> int:
    span = end_exclusive - start
    if span.total_seconds() <= 0:
        raise HistoricalDataValidationError("requested_end_exclusive_utc must be after requested_start_inclusive_utc.")
    if span.total_seconds() % 3600 != 0:
        raise HistoricalDataValidationError("requested window must align to whole UTC hours.")
    return int(span.total_seconds() // 3600)

def _request_params(*, limit: int, after: int) -> dict[str, Any]:
    return {"instId": OKX_HISTORICAL_INSTRUMENT, "bar": OKX_HISTORICAL_CANDLE_INTERVAL, "after": int(after), "limit": int(limit)}

@dataclass(frozen=True, slots=True)
class OkxPublicSpotHistoryCandlesProvider:
    timeout: tuple[float, float] = (5.0, 10.0)
    session: requests.sessions.Session | None = None
    base_url: str = OKX_HISTORICAL_ENDPOINT_URL
    trusted_market_data_provider: bool = True
    historical_source: DataSource = DataSource.OKX
    provider_identity: str = OKX_HISTORICAL_PROVIDER_ID
    provider_version: str = OKX_HISTORICAL_PROVIDER_VERSION
    historical_market_type: str = OKX_HISTORICAL_MARKET_TYPE
    historical_exchange: str = OKX_HISTORICAL_PROVIDER_EXCHANGE
    historical_access_type: str = "public_no_auth"
    historical_symbol: str = OKX_HISTORICAL_SYMBOL
    historical_external_symbol: str = OKX_HISTORICAL_INSTRUMENT
    historical_interval: str = OKX_HISTORICAL_CANDLE_INTERVAL
    historical_pagination_limit: int = OKX_HISTORICAL_REQUEST_LIMIT

    def __post_init__(self) -> None:
        if self.session is None:
            object.__setattr__(self, "session", requests.Session())

    def historical_qualification(self, symbol: str = OKX_HISTORICAL_SYMBOL, interval: str = OKX_HISTORICAL_CANDLE_INTERVAL) -> HistoricalProviderQualification:
        normalized_symbol = _require_str(symbol, "symbol").upper()
        normalized_interval = _require_str(interval, "interval")
        if normalized_symbol != OKX_HISTORICAL_SYMBOL or normalized_interval != OKX_HISTORICAL_CANDLE_INTERVAL:
            raise HistoricalDataValidationError("okx public spot provider only supports BTCUSDT 1H.")
        return HistoricalProviderQualification.okx_public_spot(
            symbol=normalized_symbol,
            interval=normalized_interval,
            provider_version=self.provider_version,
            data_contract_version=2,
        )

    def fetch_klines(self, symbol: str, interval: str, limit: int = OKX_HISTORICAL_REQUEST_LIMIT, *, after: int | None = None) -> list[Any]:
        normalized_symbol = _require_str(symbol, "symbol").upper()
        normalized_interval = _require_str(interval, "interval")
        if normalized_symbol != OKX_HISTORICAL_SYMBOL or normalized_interval != OKX_HISTORICAL_CANDLE_INTERVAL:
            raise HistoricalDataValidationError("okx public spot provider only supports BTCUSDT 1H.")
        if type(limit) is not int or isinstance(limit, bool):
            raise HistoricalDataValidationError("limit must be an integer.")
        if limit <= 0:
            raise HistoricalDataValidationError("limit must be greater than zero.")
        if limit > self.historical_pagination_limit:
            raise HistoricalDataValidationError(f"limit must be <= {self.historical_pagination_limit}.")
        if after is None:
            raise HistoricalDataValidationError("after is required.")
        params = _request_params(limit=limit, after=after)
        try:
            response = self.session.get(self.base_url, params=params, timeout=self.timeout)  # type: ignore[union-attr]
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
        if not isinstance(payload, Mapping):
            raise MarketDataJSONError("Malformed payload.")
        if str(payload.get("code")) != "0":
            raise MarketDataHTTPError(f"OKX error {payload.get('code')!r}.")
        data = payload.get("data")
        if not isinstance(data, list):
            raise MarketDataJSONError("Malformed payload.")
        return data

@dataclass(frozen=True, slots=True)
class OkxHistoricalIngestionContract:
    schema_version: int = 1
    source_name: str = OKX_HISTORICAL_SOURCE_NAME
    provider_id: str = OKX_HISTORICAL_PROVIDER_ID
    provider_version: str = OKX_HISTORICAL_PROVIDER_VERSION
    market_type: str = OKX_HISTORICAL_MARKET_TYPE
    instrument: str = OKX_HISTORICAL_INSTRUMENT
    symbol: str = OKX_HISTORICAL_SYMBOL
    interval: str = OKX_HISTORICAL_CANDLE_INTERVAL
    endpoint_method: str = OKX_HISTORICAL_ENDPOINT_METHOD
    endpoint_url: str = OKX_HISTORICAL_ENDPOINT_URL
    endpoint_path: str = OKX_HISTORICAL_ENDPOINT_PATH
    documentation_url: str = OKX_PUBLIC_SPOT_DOCUMENTATION_URL
    cursor_name: str = OKX_HISTORICAL_CURSOR_NAME
    cursor_exclusive: bool = OKX_HISTORICAL_CURSOR_EXCLUSIVE
    collection_direction: str = OKX_HISTORICAL_COLLECTION_DIRECTION
    request_limit: int = OKX_HISTORICAL_REQUEST_LIMIT
    confirm_required_value: int = OKX_HISTORICAL_CONFIRM_REQUIRED_VALUE
    requested_start_inclusive_utc: datetime = OKX_HISTORICAL_REQUESTED_START_INCLUSIVE_UTC
    requested_end_exclusive_utc: datetime = OKX_HISTORICAL_REQUESTED_END_EXCLUSIVE_UTC
    cursor_semantics: str = OKX_HISTORICAL_CURSOR_SEMANTICS
    request_params: Mapping[str, Any] | None = None
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    contract_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "source_name", _require_str(self.source_name, "source_name"))
        object.__setattr__(self, "provider_id", _require_str(self.provider_id, "provider_id"))
        object.__setattr__(self, "provider_version", _require_str(self.provider_version, "provider_version"))
        object.__setattr__(self, "market_type", _require_str(self.market_type, "market_type").lower())
        object.__setattr__(self, "instrument", _require_str(self.instrument, "instrument").upper())
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "endpoint_method", _require_str(self.endpoint_method, "endpoint_method").upper())
        object.__setattr__(self, "endpoint_url", _require_str(self.endpoint_url, "endpoint_url"))
        object.__setattr__(self, "endpoint_path", _require_str(self.endpoint_path, "endpoint_path"))
        object.__setattr__(self, "documentation_url", _require_str(self.documentation_url, "documentation_url"))
        object.__setattr__(self, "cursor_name", _require_str(self.cursor_name, "cursor_name"))
        object.__setattr__(self, "cursor_exclusive", _require_bool(self.cursor_exclusive, "cursor_exclusive"))
        object.__setattr__(self, "collection_direction", _require_str(self.collection_direction, "collection_direction"))
        object.__setattr__(self, "request_limit", _require_int(self.request_limit, "request_limit"))
        object.__setattr__(self, "confirm_required_value", _require_int(self.confirm_required_value, "confirm_required_value"))
        object.__setattr__(self, "requested_start_inclusive_utc", _require_utc_datetime(self.requested_start_inclusive_utc, "requested_start_inclusive_utc"))
        object.__setattr__(self, "requested_end_exclusive_utc", _require_utc_datetime(self.requested_end_exclusive_utc, "requested_end_exclusive_utc"))
        object.__setattr__(self, "cursor_semantics", _require_str(self.cursor_semantics, "cursor_semantics"))
        if self.request_params is None:
            object.__setattr__(self, "request_params", {"instId": OKX_HISTORICAL_INSTRUMENT, "bar": OKX_HISTORICAL_CANDLE_INTERVAL, "limit": self.request_limit})
        elif not isinstance(self.request_params, Mapping):
            raise HistoricalDataValidationError("request_params must be a mapping.")
        else:
            object.__setattr__(self, "request_params", dict(self.request_params))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != 1:
            raise HistoricalDataValidationError("schema_version must be 1.")
        if self.source_name != OKX_HISTORICAL_SOURCE_NAME:
            raise HistoricalDataValidationError("source_name must be OKX.")
        if self.provider_id != OKX_HISTORICAL_PROVIDER_ID:
            raise HistoricalDataValidationError("provider_id must be okx.public.klines.")
        if self.provider_version != OKX_HISTORICAL_PROVIDER_VERSION:
            raise HistoricalDataValidationError("provider_version must be v1.")
        if self.market_type != OKX_HISTORICAL_MARKET_TYPE:
            raise HistoricalDataValidationError("market_type must be spot.")
        if self.instrument != OKX_HISTORICAL_INSTRUMENT:
            raise HistoricalDataValidationError("instrument must be BTC-USDT.")
        if self.symbol != OKX_HISTORICAL_SYMBOL:
            raise HistoricalDataValidationError("symbol must be BTCUSDT.")
        if self.interval != OKX_HISTORICAL_CANDLE_INTERVAL:
            raise HistoricalDataValidationError("interval must be 1H.")
        if self.endpoint_method != OKX_HISTORICAL_ENDPOINT_METHOD:
            raise HistoricalDataValidationError("endpoint_method must be GET.")
        if self.endpoint_url != OKX_HISTORICAL_ENDPOINT_URL:
            raise HistoricalDataValidationError("endpoint_url must be the official OKX history-candles endpoint.")
        if self.endpoint_path != OKX_HISTORICAL_ENDPOINT_PATH:
            raise HistoricalDataValidationError("endpoint_path must be /api/v5/market/history-candles.")
        if self.documentation_url != OKX_PUBLIC_SPOT_DOCUMENTATION_URL:
            raise HistoricalDataValidationError("documentation_url must be the official OKX docs URL.")
        if self.cursor_name != OKX_HISTORICAL_CURSOR_NAME:
            raise HistoricalDataValidationError("cursor_name must be after.")
        if self.cursor_exclusive is not True:
            raise HistoricalDataValidationError("cursor_exclusive must be true.")
        if self.collection_direction != OKX_HISTORICAL_COLLECTION_DIRECTION:
            raise HistoricalDataValidationError("collection_direction must be reverse_chronological.")
        if self.request_limit != OKX_HISTORICAL_REQUEST_LIMIT:
            raise HistoricalDataValidationError("request_limit must be 100.")
        if self.confirm_required_value != OKX_HISTORICAL_CONFIRM_REQUIRED_VALUE:
            raise HistoricalDataValidationError("confirm_required_value must be 1.")
        if self.requested_start_inclusive_utc != OKX_HISTORICAL_REQUESTED_START_INCLUSIVE_UTC:
            raise HistoricalDataValidationError("requested_start_inclusive_utc diverges from the Fase 19A contract.")
        if self.requested_end_exclusive_utc != OKX_HISTORICAL_REQUESTED_END_EXCLUSIVE_UTC:
            raise HistoricalDataValidationError("requested_end_exclusive_utc diverges from the Fase 19A contract.")
        if self.historical_research_only is not True:
            raise HistoricalDataValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise HistoricalDataValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise HistoricalDataValidationError("paper_promotion_eligible must be false.")
        if self.request_params != {"instId": OKX_HISTORICAL_INSTRUMENT, "bar": OKX_HISTORICAL_CANDLE_INTERVAL, "limit": OKX_HISTORICAL_REQUEST_LIMIT}:
            raise HistoricalDataValidationError("request_params diverge from the Fase 19A contract.")
        expected = _hash_payload(self.canonical_payload())
        if self.contract_hash:
            if self.contract_hash != _require_str(self.contract_hash, "contract_hash"):
                raise HistoricalDataValidationError("contract_hash mismatch.")
            if self.contract_hash != expected:
                raise HistoricalDataValidationError("contract_hash mismatch.")
        else:
            object.__setattr__(self, "contract_hash", expected)

    @property
    def expected_candle_count(self) -> int:
        return _expected_candle_count(self.requested_start_inclusive_utc, self.requested_end_exclusive_utc)

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_name": self.source_name,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "market_type": self.market_type,
            "instrument": self.instrument,
            "symbol": self.symbol,
            "interval": self.interval,
            "endpoint_method": self.endpoint_method,
            "endpoint_url": self.endpoint_url,
            "endpoint_path": self.endpoint_path,
            "documentation_url": self.documentation_url,
            "cursor_name": self.cursor_name,
            "cursor_exclusive": self.cursor_exclusive,
            "collection_direction": self.collection_direction,
            "request_limit": self.request_limit,
            "confirm_required_value": self.confirm_required_value,
            "requested_start_inclusive_utc": _utc_iso(self.requested_start_inclusive_utc),
            "requested_end_exclusive_utc": _utc_iso(self.requested_end_exclusive_utc),
            "cursor_semantics": self.cursor_semantics,
            "request_params": dict(self.request_params or {}),
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }

    def as_dict(self) -> dict[str, Any]:
        payload = self.canonical_payload()
        payload["contract_hash"] = self.contract_hash
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OkxHistoricalIngestionContract":
        if not isinstance(data, Mapping):
            raise HistoricalDataValidationError("OKX ingestion contract must be a mapping.")
        mapping = dict(data)
        allowed = {
            "schema_version",
            "source_name",
            "provider_id",
            "provider_version",
            "market_type",
            "instrument",
            "symbol",
            "interval",
            "endpoint_method",
            "endpoint_url",
            "endpoint_path",
            "documentation_url",
            "cursor_name",
            "cursor_exclusive",
            "collection_direction",
            "request_limit",
            "confirm_required_value",
            "requested_start_inclusive_utc",
            "requested_end_exclusive_utc",
            "cursor_semantics",
            "request_params",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "contract_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise HistoricalDataValidationError(f"unexpected OKX ingestion contract fields: {', '.join(extra)}.")
        try:
            return cls(
                schema_version=mapping["schema_version"],
                source_name=mapping["source_name"],
                provider_id=mapping["provider_id"],
                provider_version=mapping["provider_version"],
                market_type=mapping["market_type"],
                instrument=mapping["instrument"],
                symbol=mapping["symbol"],
                interval=mapping["interval"],
                endpoint_method=mapping["endpoint_method"],
                endpoint_url=mapping["endpoint_url"],
                endpoint_path=mapping["endpoint_path"],
                documentation_url=mapping["documentation_url"],
                cursor_name=mapping["cursor_name"],
                cursor_exclusive=mapping["cursor_exclusive"],
                collection_direction=mapping["collection_direction"],
                request_limit=mapping["request_limit"],
                confirm_required_value=mapping["confirm_required_value"],
                requested_start_inclusive_utc=mapping["requested_start_inclusive_utc"],
                requested_end_exclusive_utc=mapping["requested_end_exclusive_utc"],
                cursor_semantics=mapping["cursor_semantics"],
                request_params=mapping.get("request_params"),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                contract_hash=mapping.get("contract_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalDataValidationError("OKX ingestion contract is incomplete.") from exc

@dataclass(frozen=True, slots=True)
class OkxHistoricalIngestionManifest:
    schema_version: int
    contract: OkxHistoricalIngestionContract
    expected_candle_count: int
    found_candle_count: int
    page_count: int
    first_candle_open_utc: datetime
    first_candle_close_utc: datetime
    last_candle_open_utc: datetime
    last_candle_close_utc: datetime
    trimmed_before_start_count: int
    gap_count: int
    duplicate_count: int
    overlap_count: int
    cursor_no_progress_count: int
    http_error_count: int
    timeout_count: int
    malformed_response_count: int
    dataset_hash: str
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_ingestion_scope_statement: str = OKX_HISTORICAL_NON_INGESTION_SCOPE_STATEMENT
    manifest_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        if not isinstance(self.contract, OkxHistoricalIngestionContract):
            raise HistoricalDataValidationError("contract must be an OkxHistoricalIngestionContract instance.")
        object.__setattr__(self, "expected_candle_count", _require_int(self.expected_candle_count, "expected_candle_count"))
        object.__setattr__(self, "found_candle_count", _require_int(self.found_candle_count, "found_candle_count"))
        object.__setattr__(self, "page_count", _require_int(self.page_count, "page_count"))
        object.__setattr__(self, "first_candle_open_utc", _require_utc_datetime(self.first_candle_open_utc, "first_candle_open_utc"))
        object.__setattr__(self, "first_candle_close_utc", _require_utc_datetime(self.first_candle_close_utc, "first_candle_close_utc"))
        object.__setattr__(self, "last_candle_open_utc", _require_utc_datetime(self.last_candle_open_utc, "last_candle_open_utc"))
        object.__setattr__(self, "last_candle_close_utc", _require_utc_datetime(self.last_candle_close_utc, "last_candle_close_utc"))
        object.__setattr__(self, "trimmed_before_start_count", _require_int(self.trimmed_before_start_count, "trimmed_before_start_count", allow_zero=True))
        object.__setattr__(self, "gap_count", _require_int(self.gap_count, "gap_count", allow_zero=True))
        object.__setattr__(self, "duplicate_count", _require_int(self.duplicate_count, "duplicate_count", allow_zero=True))
        object.__setattr__(self, "overlap_count", _require_int(self.overlap_count, "overlap_count", allow_zero=True))
        object.__setattr__(self, "cursor_no_progress_count", _require_int(self.cursor_no_progress_count, "cursor_no_progress_count", allow_zero=True))
        object.__setattr__(self, "http_error_count", _require_int(self.http_error_count, "http_error_count", allow_zero=True))
        object.__setattr__(self, "timeout_count", _require_int(self.timeout_count, "timeout_count", allow_zero=True))
        object.__setattr__(self, "malformed_response_count", _require_int(self.malformed_response_count, "malformed_response_count", allow_zero=True))
        object.__setattr__(self, "dataset_hash", _require_str(self.dataset_hash, "dataset_hash"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_ingestion_scope_statement", _require_str(self.non_ingestion_scope_statement, "non_ingestion_scope_statement"))
        if self.schema_version != 1:
            raise HistoricalDataValidationError("manifest schema_version must be 1.")
        if self.expected_candle_count != self.contract.expected_candle_count:
            raise HistoricalDataValidationError("expected_candle_count diverges from the OKX contract.")
        if self.historical_research_only is not True:
            raise HistoricalDataValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise HistoricalDataValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise HistoricalDataValidationError("paper_promotion_eligible must be false.")
        expected = _hash_payload(self.canonical_payload())
        if self.manifest_hash:
            if self.manifest_hash != _require_str(self.manifest_hash, "manifest_hash"):
                raise HistoricalDataValidationError("manifest_hash mismatch.")
            if self.manifest_hash != expected:
                raise HistoricalDataValidationError("manifest_hash mismatch.")
        else:
            object.__setattr__(self, "manifest_hash", expected)

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract": self.contract.as_dict(),
            "expected_candle_count": self.expected_candle_count,
            "found_candle_count": self.found_candle_count,
            "page_count": self.page_count,
            "first_candle_open_utc": _utc_iso(self.first_candle_open_utc),
            "first_candle_close_utc": _utc_iso(self.first_candle_close_utc),
            "last_candle_open_utc": _utc_iso(self.last_candle_open_utc),
            "last_candle_close_utc": _utc_iso(self.last_candle_close_utc),
            "trimmed_before_start_count": self.trimmed_before_start_count,
            "gap_count": self.gap_count,
            "duplicate_count": self.duplicate_count,
            "overlap_count": self.overlap_count,
            "cursor_no_progress_count": self.cursor_no_progress_count,
            "http_error_count": self.http_error_count,
            "timeout_count": self.timeout_count,
            "malformed_response_count": self.malformed_response_count,
            "dataset_hash": self.dataset_hash,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_ingestion_scope_statement": self.non_ingestion_scope_statement,
        }

    def as_dict(self) -> dict[str, Any]:
        payload = self.canonical_payload()
        payload["manifest_hash"] = self.manifest_hash
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OkxHistoricalIngestionManifest":
        if not isinstance(data, Mapping):
            raise HistoricalDataValidationError("OKX ingestion manifest must be a mapping.")
        mapping = dict(data)
        allowed = {
            "schema_version",
            "contract",
            "expected_candle_count",
            "found_candle_count",
            "page_count",
            "first_candle_open_utc",
            "first_candle_close_utc",
            "last_candle_open_utc",
            "last_candle_close_utc",
            "trimmed_before_start_count",
            "gap_count",
            "duplicate_count",
            "overlap_count",
            "cursor_no_progress_count",
            "http_error_count",
            "timeout_count",
            "malformed_response_count",
            "dataset_hash",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "non_ingestion_scope_statement",
            "manifest_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise HistoricalDataValidationError(f"unexpected OKX ingestion manifest fields: {', '.join(extra)}.")
        try:
            return cls(
                schema_version=mapping["schema_version"],
                contract=OkxHistoricalIngestionContract.from_dict(mapping["contract"]),
                expected_candle_count=mapping["expected_candle_count"],
                found_candle_count=mapping["found_candle_count"],
                page_count=mapping["page_count"],
                first_candle_open_utc=mapping["first_candle_open_utc"],
                first_candle_close_utc=mapping["first_candle_close_utc"],
                last_candle_open_utc=mapping["last_candle_open_utc"],
                last_candle_close_utc=mapping["last_candle_close_utc"],
                trimmed_before_start_count=mapping["trimmed_before_start_count"],
                gap_count=mapping["gap_count"],
                duplicate_count=mapping["duplicate_count"],
                overlap_count=mapping["overlap_count"],
                cursor_no_progress_count=mapping["cursor_no_progress_count"],
                http_error_count=mapping["http_error_count"],
                timeout_count=mapping["timeout_count"],
                malformed_response_count=mapping["malformed_response_count"],
                dataset_hash=mapping["dataset_hash"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                non_ingestion_scope_statement=mapping.get("non_ingestion_scope_statement", OKX_HISTORICAL_NON_INGESTION_SCOPE_STATEMENT),
                manifest_hash=mapping.get("manifest_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalDataValidationError("OKX ingestion manifest is incomplete.") from exc

@dataclass(frozen=True, slots=True)
class OkxHistoricalDataset:
    manifest: OkxHistoricalIngestionManifest
    candles: tuple[Candle, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, OkxHistoricalIngestionManifest):
            raise HistoricalDataValidationError("manifest must be an OkxHistoricalIngestionManifest instance.")
        if not isinstance(self.candles, tuple):
            object.__setattr__(self, "candles", tuple(self.candles))
        if not self.candles:
            raise HistoricalDataValidationError("OKX dataset must contain candles.")
        if self.manifest.expected_candle_count != len(self.candles):
            raise HistoricalDataValidationError("manifest expected_candle_count does not match candles.")
        if self.manifest.found_candle_count != len(self.candles):
            raise HistoricalDataValidationError("manifest found_candle_count does not match candles.")
        if self.candles[0].open_time != self.manifest.first_candle_open_utc:
            raise HistoricalDataValidationError("first candle diverges from manifest.")
        if self.candles[-1].open_time != self.manifest.last_candle_open_utc:
            raise HistoricalDataValidationError("last candle diverges from manifest.")
        if self.manifest.first_candle_close_utc != self.candles[0].close_time:
            raise HistoricalDataValidationError("first candle close_time diverges from manifest.")
        if self.manifest.last_candle_close_utc != self.candles[-1].close_time:
            raise HistoricalDataValidationError("last candle close_time diverges from manifest.")
        if any(candle.symbol != OKX_HISTORICAL_SYMBOL for candle in self.candles):
            raise HistoricalDataValidationError("OKX dataset candle symbol mismatch.")
        if any(candle.interval != OKX_HISTORICAL_CANDLE_INTERVAL for candle in self.candles):
            raise HistoricalDataValidationError("OKX dataset candle interval mismatch.")
        if any(candle.source != DataSource.OKX for candle in self.candles):
            raise HistoricalDataValidationError("OKX dataset candle source mismatch.")
        for previous, current in zip(self.candles, self.candles[1:]):
            if current.open_time != previous.open_time + _hour_delta():
                raise HistoricalDataValidationError("OKX dataset candles are not contiguous.")
            if current.close_time != current.open_time + _hour_delta() - timedelta(milliseconds=1):
                raise HistoricalDataValidationError("OKX dataset candle close_time diverges.")
        if self.manifest.dataset_hash != historical_content_hash(self.candles):
            raise HistoricalDataValidationError("dataset_hash mismatch.")
        if self.manifest.contract.expected_candle_count != len(self.candles):
            raise HistoricalDataValidationError("contract expected candle count mismatch.")
        if self.manifest.contract.requested_start_inclusive_utc != self.candles[0].open_time:
            raise HistoricalDataValidationError("contract requested_start_inclusive_utc mismatch.")
        if self.manifest.contract.requested_end_exclusive_utc != self.candles[-1].close_time + timedelta(milliseconds=1):
            raise HistoricalDataValidationError("contract requested_end_exclusive_utc mismatch.")
        if self.manifest.contract.contract_hash != _hash_payload(self.manifest.contract.canonical_payload()):
            raise HistoricalDataValidationError("contract_hash mismatch.")
        if self.manifest.manifest_hash != _hash_payload(self.manifest.canonical_payload()):
            raise HistoricalDataValidationError("manifest_hash mismatch.")

    def dataset_payload(self) -> list[dict[str, Any]]:
        return [candle.to_dict() for candle in self.candles]

    def manifest_payload(self) -> dict[str, Any]:
        return self.manifest.as_dict()

    def as_dict(self) -> dict[str, Any]:
        return {"manifest": self.manifest_payload(), "candles": self.dataset_payload()}

def resolve_okx_historical_artifact_paths(
    base_dir: str | Path,
    *,
    dataset_filename: str = OKX_HISTORICAL_DATASET_CANDLES_FILENAME,
    manifest_filename: str = OKX_HISTORICAL_MANIFEST_FILENAME,
) -> tuple[Path, Path]:
    root = Path(base_dir)
    artifact_dir = root / OKX_HISTORICAL_ARTIFACT_DIRNAME
    return artifact_dir / dataset_filename, artifact_dir / manifest_filename

def _write_atomic_json(path: Path, payload: Any, *, owner_tag: str) -> None:
    canonical = _canonical_json(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == canonical:
            return
        raise HistoricalDataConflictError(f"{owner_tag} already exists and differs.")
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{id(payload)}.tmp")
    try:
        tmp_path.write_text(canonical, encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HistoricalDataValidationError(f"Failed to write {owner_tag} atomically.") from exc

def _okx_row_to_candle(row: Any) -> Candle:
    if not isinstance(row, (list, tuple)) or len(row) < 8:
        raise HistoricalDataValidationError("Malformed OKX candle row.")
    try:
        open_time_ms = int(row[0])
        confirm = int(row[-1])
    except (TypeError, ValueError, OverflowError) as exc:
        raise HistoricalDataValidationError("Invalid timestamp in OKX candle row.") from exc
    if confirm != OKX_HISTORICAL_CONFIRM_REQUIRED_VALUE:
        raise HistoricalDataValidationError("confirm=1 is required for OKX historical candles.")
    open_time = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)
    if open_time.minute != 0 or open_time.second != 0 or open_time.microsecond != 0:
        raise HistoricalDataValidationError("OKX candle timestamp must be aligned to the UTC hour.")
    close_time = open_time + _hour_delta() - timedelta(milliseconds=1)
    try:
        return Candle.from_dict(
            {
                "open_time": open_time,
                "close_time": close_time,
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
                "symbol": OKX_HISTORICAL_SYMBOL,
                "interval": OKX_HISTORICAL_CANDLE_INTERVAL,
                "source": DataSource.OKX,
            }
        )
    except Exception as exc:
        raise HistoricalDataValidationError(str(exc)) from exc

def _normalize_page(payload: Any, *, start_utc: datetime, end_exclusive_utc: datetime) -> list[Candle]:
    if not isinstance(payload, list) or not payload:
        raise HistoricalDataValidationError("Empty or malformed response payload.")
    candles = sorted((_okx_row_to_candle(row) for row in payload), key=lambda candle: candle.open_time)
    for previous, current in zip(candles, candles[1:]):
        if current.open_time == previous.open_time:
            raise HistoricalDataValidationError("Duplicate candle detected.")
        if current.open_time != previous.open_time + _hour_delta():
            raise HistoricalDataValidationError("Gap detected between candles.")
    if candles[-1].open_time >= end_exclusive_utc:
        raise HistoricalDataValidationError("Historical page exceeds requested_end_exclusive_utc.")
    return candles

def _build_contract() -> OkxHistoricalIngestionContract:
    return OkxHistoricalIngestionContract()

def _load_json(path: Path) -> Any:
    if not path.exists():
        raise HistoricalDataValidationError(f"{path.name} is missing.")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise HistoricalDataValidationError(f"{path.name} is empty.")
    try:
        return json.loads(text)
    except Exception as exc:
        raise HistoricalDataValidationError(f"{path.name} is invalid JSON.") from exc

def load_okx_historical_dataset(*, dataset_file: str | Path, manifest_file: str | Path) -> OkxHistoricalDataset:
    dataset_path = Path(dataset_file)
    manifest_path = Path(manifest_file)
    dataset_payload = _load_json(dataset_path)
    manifest_payload = _load_json(manifest_path)
    if not isinstance(dataset_payload, list):
        raise HistoricalDataIntegrityError("OKX dataset payload must be a JSON array.")
    if not isinstance(manifest_payload, Mapping):
        raise HistoricalDataIntegrityError("OKX manifest payload must be a JSON object.")
    manifest = OkxHistoricalIngestionManifest.from_dict(manifest_payload)
    try:
        candles = tuple(Candle.from_dict(item) for item in dataset_payload)
    except Exception as exc:
        raise HistoricalDataIntegrityError("OKX dataset candles are invalid.") from exc
    dataset = OkxHistoricalDataset(manifest=manifest, candles=candles)
    if dataset.dataset_payload() != dataset_payload:
        raise HistoricalDataIntegrityError("OKX dataset payload mismatch.")
    if dataset.manifest_payload() != manifest_payload:
        raise HistoricalDataIntegrityError("OKX manifest payload mismatch.")
    return dataset

def save_okx_historical_dataset(
    *,
    dataset_file: str | Path,
    manifest_file: str | Path,
    dataset: OkxHistoricalDataset,
) -> OkxHistoricalDataset:
    dataset_path = Path(dataset_file)
    manifest_path = Path(manifest_file)
    dataset_payload = dataset.dataset_payload()
    manifest_payload = dataset.manifest_payload()
    if dataset_path.exists() or manifest_path.exists():
        existing = load_okx_historical_dataset(dataset_file=dataset_path, manifest_file=manifest_path)
        if existing.as_dict() != dataset.as_dict():
            raise HistoricalDataConflictError("OKX dataset already exists and differs.")
        return existing
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_tmp = dataset_path.with_name(f".{dataset_path.name}.{os.getpid()}.{id(dataset)}.tmp")
    manifest_tmp = manifest_path.with_name(f".{manifest_path.name}.{os.getpid()}.{id(dataset)}.tmp")
    wrote_dataset = False
    try:
        dataset_tmp.write_text(_canonical_json(dataset_payload), encoding="utf-8")
        manifest_tmp.write_text(_canonical_json(manifest_payload), encoding="utf-8")
        os.replace(dataset_tmp, dataset_path)
        wrote_dataset = True
        os.replace(manifest_tmp, manifest_path)
    except Exception as exc:
        dataset_tmp.unlink(missing_ok=True)
        manifest_tmp.unlink(missing_ok=True)
        if wrote_dataset:
            dataset_path.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
        raise HistoricalDataValidationError("Failed to write OKX dataset atomically.") from exc
    return dataset

def _fetch_okx_candles(provider: OkxPublicSpotHistoryCandlesProvider, contract: OkxHistoricalIngestionContract) -> tuple[list[Candle], int, int]:
    expected_count = contract.expected_candle_count
    start_utc = contract.requested_start_inclusive_utc
    end_exclusive_utc = contract.requested_end_exclusive_utc
    cursor_ms = int(end_exclusive_utc.timestamp() * 1000)
    candles: list[Candle] = []
    page_count = 0
    trimmed_before_start_count = 0
    previous_cursor_ms: int | None = None
    while len(candles) < expected_count:
        if page_count >= expected_count + 1:
            raise HistoricalDataValidationError("Maximum historical page count exceeded.")
        page_payload = provider.fetch_klines(
            contract.symbol,
            contract.interval,
            contract.request_limit,
            after=cursor_ms,
        )
        page_count += 1
        page_candles = _normalize_page(page_payload, start_utc=start_utc, end_exclusive_utc=end_exclusive_utc)
        if not page_candles:
            raise HistoricalDataValidationError("Historical page did not return candles within the requested range.")
        page_newest_open_ms = int(page_candles[-1].open_time.timestamp() * 1000)
        page_oldest_open_ms = int(page_candles[0].open_time.timestamp() * 1000)
        if previous_cursor_ms is not None and page_newest_open_ms >= previous_cursor_ms:
            raise HistoricalDataValidationError("Historical page made no progress.")
        if page_newest_open_ms >= cursor_ms:
            raise HistoricalDataValidationError("Historical page overlaps a previous page.")
        in_window = [candle for candle in page_candles if start_utc <= candle.open_time < end_exclusive_utc]
        trimmed_before_start_count += len(page_candles) - len(in_window)
        if not in_window:
            raise HistoricalDataValidationError("Historical page did not cover the requested start boundary.")
        candles = in_window + candles
        previous_cursor_ms = cursor_ms
        cursor_ms = page_oldest_open_ms
        if len(candles) > expected_count:
            raise HistoricalDataValidationError("Historical candle count diverged.")
    return candles, page_count, trimmed_before_start_count

def prepare_okx_historical_dataset(*, dataset_file: str | Path, manifest_file: str | Path, provider: OkxPublicSpotHistoryCandlesProvider | None = None) -> dict[str, Any]:
    contract = _build_contract()
    dataset_path = Path(dataset_file)
    manifest_path = Path(manifest_file)
    if dataset_path.exists() or manifest_path.exists():
        if not dataset_path.exists() or not manifest_path.exists():
            raise HistoricalDataConflictError("OKX dataset already exists and is incomplete.")
        existing = load_okx_historical_dataset(dataset_file=dataset_path, manifest_file=manifest_path)
        if existing.manifest.contract != contract:
            raise HistoricalDataConflictError("OKX dataset already exists and differs.")
        return {
            "dataset_file": str(dataset_path),
            "manifest_file": str(manifest_path),
            "dataset_hash": existing.manifest.dataset_hash,
            "manifest_hash": existing.manifest.manifest_hash,
            "candle_count": existing.manifest.found_candle_count,
            "page_count": existing.manifest.page_count,
            "first_candle_open_utc": _utc_iso(existing.manifest.first_candle_open_utc),
            "last_candle_open_utc": _utc_iso(existing.manifest.last_candle_open_utc),
            "reused": True,
        }
    resolved_provider = provider or OkxPublicSpotHistoryCandlesProvider()
    qualification = resolved_provider.historical_qualification(symbol=contract.symbol, interval=contract.interval)
    expected_qualification = HistoricalProviderQualification.okx_public_spot(symbol=contract.symbol, interval=contract.interval)
    if qualification != expected_qualification:
        raise HistoricalDataValidationError("OKX provider qualification mismatch.")
    candles, page_count, trimmed_before_start_count = _fetch_okx_candles(resolved_provider, contract)
    dataset_hash = historical_content_hash(candles)
    manifest = OkxHistoricalIngestionManifest(
        schema_version=1,
        contract=contract,
        expected_candle_count=len(candles),
        found_candle_count=len(candles),
        page_count=page_count,
        first_candle_open_utc=candles[0].open_time,
        first_candle_close_utc=candles[0].close_time,
        last_candle_open_utc=candles[-1].open_time,
        last_candle_close_utc=candles[-1].close_time,
        trimmed_before_start_count=trimmed_before_start_count,
        gap_count=0,
        duplicate_count=0,
        overlap_count=0,
        cursor_no_progress_count=0,
        http_error_count=0,
        timeout_count=0,
        malformed_response_count=0,
        dataset_hash=dataset_hash,
    )
    dataset = OkxHistoricalDataset(manifest=manifest, candles=tuple(candles))
    saved = save_okx_historical_dataset(dataset_file=dataset_path, manifest_file=manifest_path, dataset=dataset)
    return {
        "dataset_file": str(dataset_path),
        "manifest_file": str(manifest_path),
        "dataset_hash": saved.manifest.dataset_hash,
        "manifest_hash": saved.manifest.manifest_hash,
        "candle_count": saved.manifest.found_candle_count,
        "page_count": saved.manifest.page_count,
        "first_candle_open_utc": _utc_iso(saved.manifest.first_candle_open_utc),
        "last_candle_open_utc": _utc_iso(saved.manifest.last_candle_open_utc),
        "reused": False,
    }

def verify_okx_historical_dataset(*, dataset_file: str | Path, manifest_file: str | Path) -> dict[str, Any]:
    dataset = load_okx_historical_dataset(dataset_file=dataset_file, manifest_file=manifest_file)
    return {
        "verified": True,
        "dataset_hash": dataset.manifest.dataset_hash,
        "manifest_hash": dataset.manifest.manifest_hash,
        "contract_hash": dataset.manifest.contract.contract_hash,
        "candle_count": dataset.manifest.found_candle_count,
        "expected_candle_count": dataset.manifest.expected_candle_count,
        "page_count": dataset.manifest.page_count,
        "first_candle_open_utc": _utc_iso(dataset.manifest.first_candle_open_utc),
        "last_candle_open_utc": _utc_iso(dataset.manifest.last_candle_open_utc),
        "source_name": dataset.manifest.contract.source_name,
        "market_type": dataset.manifest.contract.market_type,
        "instrument": dataset.manifest.contract.instrument,
        "symbol": dataset.manifest.contract.symbol,
        "interval": dataset.manifest.contract.interval,
        "cursor_name": dataset.manifest.contract.cursor_name,
        "cursor_exclusive": dataset.manifest.contract.cursor_exclusive,
        "collection_direction": dataset.manifest.contract.collection_direction,
        "request_limit": dataset.manifest.contract.request_limit,
        "confirm_required_value": dataset.manifest.contract.confirm_required_value,
        "historical_research_only": dataset.manifest.contract.historical_research_only,
        "operational_evidence": dataset.manifest.contract.operational_evidence,
        "paper_promotion_eligible": dataset.manifest.contract.paper_promotion_eligible,
    }
