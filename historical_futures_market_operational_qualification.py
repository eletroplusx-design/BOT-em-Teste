"""Research-only operational qualification for the observed OKX spot candidate.

This module freezes the evidence collected in Phase 18A into an immutable,
deterministic, fail-closed report. It records only the observed operational
coverage for the verified frozen windows and does not authorize ingestion,
dataset preparation, replay, backtest, paper trading, or live trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value
from historical_futures_market_contract import (
    HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE,
    HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST,
    HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION,
)
from market_data import HistoricalDataValidationError
from market_data.provider_qualification import HistoricalProviderQualification

HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION = 1
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_PROTOCOL_NAME = (
    "historical_futures_market_operational_qualification"
)
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_PROTOCOL_VERSION = "v1"
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS = (
    "operational_evidence_observed_not_authorized_for_ingestion"
)
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_NAME = "KuCoin spot"
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID = "kucoin.public.klines"
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SOURCE_NAME = "OKX spot"
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_ID = "okx.public.klines"
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_MARKET_TYPE = "spot"
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SYMBOL = "BTCUSDT"
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL = "BTC-USDT"
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_TIME_SEMANTICS = "utc"
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ACCESS_TYPE = "public_no_auth"
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_VERSION = "v1"
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE = "okx"
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL = "https://www.okx.com/docs-v5/en/"
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_URL = (
    "https://www.okx.com/api/v5/market/history-candles"
)
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_PATH = (
    "/api/v5/market/history-candles"
)
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE = (
    "confirm=0 means incomplete; confirm=1 means completed"
)
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PAGINATION_LIMIT = 100
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_INTERVALS: tuple[str, ...] = (
    "15m",
    "1h",
    "4h",
)
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT = (
    "Coverage is limited to the frozen reference, validation, and test windows; "
    "coverage beyond those windows remains unverified."
)
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT = (
    "No dataset OKX was prepared; no manifest_hash, content_hash, or candle hash exists; "
    "no replay, backtest, performance comparison, paper, or live trading is authorized."
)
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_ENDPOINT_BEHAVIOR_STATEMENT = (
    "The OKX history-candles endpoint returned confirm=1 for closed historical candles and "
    "confirm=0 for an incomplete sample."
)
HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_OPERATIONAL_STATUS = (
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS
)

_WINDOW_REFERENCE_START_UTC = datetime(2025, 1, 4, 8, 14, 59, 999000, tzinfo=timezone.utc)
_WINDOW_REFERENCE_END_UTC = datetime(2025, 1, 4, 14, 49, 59, 998999, tzinfo=timezone.utc)
_WINDOW_VALIDATION_START_UTC = datetime(2025, 1, 4, 14, 49, 59, 999000, tzinfo=timezone.utc)
_WINDOW_VALIDATION_END_UTC = datetime(2025, 1, 4, 21, 24, 59, 998999, tzinfo=timezone.utc)
_WINDOW_TEST_START_UTC = datetime(2025, 1, 4, 21, 24, 59, 999000, tzinfo=timezone.utc)
_WINDOW_TEST_END_UTC = datetime(2025, 1, 5, 3, 59, 59, 999000, tzinfo=timezone.utc)

_WINDOW_SPECS: dict[str, tuple[datetime, datetime]] = {
    HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE: (
        _WINDOW_REFERENCE_START_UTC,
        _WINDOW_REFERENCE_END_UTC,
    ),
    HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION: (
        _WINDOW_VALIDATION_START_UTC,
        _WINDOW_VALIDATION_END_UTC,
    ),
    HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST: (
        _WINDOW_TEST_START_UTC,
        _WINDOW_TEST_END_UTC,
    ),
}

_INTERVAL_SPECS: dict[str, dict[str, Any]] = {
    "15m": {
        "candle_count": 80,
        "first_candle_open_utc": datetime(2025, 1, 4, 8, 0, 0, tzinfo=timezone.utc),
        "last_candle_open_utc": datetime(2025, 1, 5, 3, 45, 0, tzinfo=timezone.utc),
        "duplicate_count": 0,
        "gap_count": 0,
        "page_count": 1,
    },
    "1h": {
        "candle_count": 20,
        "first_candle_open_utc": datetime(2025, 1, 4, 8, 0, 0, tzinfo=timezone.utc),
        "last_candle_open_utc": datetime(2025, 1, 5, 3, 0, 0, tzinfo=timezone.utc),
        "duplicate_count": 0,
        "gap_count": 0,
        "page_count": 1,
    },
    "4h": {
        "candle_count": 5,
        "first_candle_open_utc": datetime(2025, 1, 4, 8, 0, 0, tzinfo=timezone.utc),
        "last_candle_open_utc": datetime(2025, 1, 5, 0, 0, 0, tzinfo=timezone.utc),
        "duplicate_count": 0,
        "gap_count": 0,
        "page_count": 1,
    },
}


class HistoricalFuturesMarketOperationalQualificationError(Exception):
    pass


class HistoricalFuturesMarketOperationalQualificationValidationError(
    HistoricalFuturesMarketOperationalQualificationError
):
    pass


class HistoricalFuturesMarketOperationalQualificationIntegrityError(
    HistoricalFuturesMarketOperationalQualificationValidationError
):
    pass


class HistoricalFuturesMarketOperationalQualificationConflictError(
    HistoricalFuturesMarketOperationalQualificationIntegrityError
):
    pass


class HistoricalFuturesMarketOperationalQualificationPromotionError(
    HistoricalFuturesMarketOperationalQualificationValidationError
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalFuturesMarketOperationalQualificationValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalFuturesMarketOperationalQualificationValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalFuturesMarketOperationalQualificationValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalFuturesMarketOperationalQualificationValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise HistoricalFuturesMarketOperationalQualificationValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise HistoricalFuturesMarketOperationalQualificationValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _validate_exact_keys(mapping: Mapping[str, Any], *, allowed: set[str], name: str) -> None:
    extra = set(mapping) - allowed
    if extra:
        raise HistoricalFuturesMarketOperationalQualificationIntegrityError(
            f"{name} contains unknown fields: {sorted(extra)!r}."
        )


def _research_only(historical_research_only: bool, operational_evidence: bool, paper_promotion_eligible: bool) -> None:
    if historical_research_only is not True:
        raise HistoricalFuturesMarketOperationalQualificationValidationError(
            "historical_research_only must be true."
        )
    if operational_evidence is not False:
        raise HistoricalFuturesMarketOperationalQualificationValidationError("operational_evidence must be false.")
    if paper_promotion_eligible is not False:
        raise HistoricalFuturesMarketOperationalQualificationValidationError(
            "paper_promotion_eligible must be false."
        )


def _expected_window_name_order() -> tuple[str, ...]:
    return (
        HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE,
        HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION,
        HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST,
    )


def _expected_interval_order() -> tuple[str, ...]:
    return HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_INTERVALS


def _expected_provider_qualification(interval: str) -> HistoricalProviderQualification:
    if interval not in _INTERVAL_SPECS:
        raise HistoricalFuturesMarketOperationalQualificationValidationError(
            "interval must be 15m, 1h, or 4h."
        )
    return HistoricalProviderQualification(
        provider_id=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_ID,
        provider_version=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_VERSION,
        market_type=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_MARKET_TYPE,
        exchange=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE,
        symbol=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SYMBOL,
        interval=interval,
        time_semantics=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_TIME_SEMANTICS,
        access_type=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ACCESS_TYPE,
        data_contract_version=2,
        external_symbol=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL,
        endpoint_url=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_URL,
        documentation_url=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL,
        pagination_limit=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PAGINATION_LIMIT,
        close_time_rule=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE,
    )


def _expected_frozen_window(window_name: str) -> tuple[datetime, datetime]:
    try:
        return _WINDOW_SPECS[window_name]
    except KeyError as exc:
        raise HistoricalFuturesMarketOperationalQualificationValidationError(
            "window_name must be reference, validation, or test."
        ) from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketOperationalQualificationWindow:
    window_name: str
    start_utc: datetime
    end_utc: datetime
    schema_version: int = HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION
    window_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_name", _require_str(self.window_name, "window_name").lower())
        object.__setattr__(self, "start_utc", _require_utc_datetime(self.start_utc, "start_utc"))
        object.__setattr__(self, "end_utc", _require_utc_datetime(self.end_utc, "end_utc"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "window schema_version must be 1."
            )
        expected_start, expected_end = _expected_frozen_window(self.window_name)
        if self.start_utc != expected_start or self.end_utc != expected_end:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "frozen window bounds diverge from the declared Phase 18A evidence."
            )
        if self.end_utc <= self.start_utc:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "window end must be after window start."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.window_hash:
            if self.window_hash != expected:
                raise HistoricalFuturesMarketOperationalQualificationValidationError("window hash mismatch.")
        else:
            object.__setattr__(self, "window_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "window_name": self.window_name,
            "start_utc": _utc_iso(self.start_utc),
            "end_utc": _utc_iso(self.end_utc),
        }
        if include_hash:
            payload["window_hash"] = self.window_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketOperationalQualificationWindow":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketOperationalQualificationValidationError("window must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={"schema_version", "window_name", "start_utc", "end_utc", "window_hash"},
            name="window",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                window_name=mapping["window_name"],
                start_utc=mapping["start_utc"],
                end_utc=mapping["end_utc"],
                window_hash=mapping.get("window_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("window is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketOperationalQualificationObservation:
    provider_qualification: HistoricalProviderQualification
    candle_count: int
    first_candle_open_utc: datetime
    last_candle_open_utc: datetime
    duplicate_count: int
    gap_count: int
    page_count: int
    pagination_limit: int
    all_confirm_closed: bool
    incomplete_candle_confirm_observed: bool
    schema_version: int = HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION
    observation_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.provider_qualification, HistoricalProviderQualification):
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "provider_qualification must be a HistoricalProviderQualification instance."
            )
        interval = self.provider_qualification.interval
        expected_provider_qualification = _expected_provider_qualification(interval)
        if self.provider_qualification != expected_provider_qualification:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "provider_qualification diverges from the declared OKX evidence."
            )
        object.__setattr__(self, "candle_count", _require_int(self.candle_count, "candle_count"))
        object.__setattr__(self, "first_candle_open_utc", _require_utc_datetime(self.first_candle_open_utc, "first_candle_open_utc"))
        object.__setattr__(self, "last_candle_open_utc", _require_utc_datetime(self.last_candle_open_utc, "last_candle_open_utc"))
        object.__setattr__(self, "duplicate_count", _require_int(self.duplicate_count, "duplicate_count", allow_zero=True))
        object.__setattr__(self, "gap_count", _require_int(self.gap_count, "gap_count", allow_zero=True))
        object.__setattr__(self, "page_count", _require_int(self.page_count, "page_count"))
        object.__setattr__(self, "pagination_limit", _require_int(self.pagination_limit, "pagination_limit"))
        object.__setattr__(self, "all_confirm_closed", _require_bool(self.all_confirm_closed, "all_confirm_closed"))
        object.__setattr__(
            self,
            "incomplete_candle_confirm_observed",
            _require_bool(self.incomplete_candle_confirm_observed, "incomplete_candle_confirm_observed"),
        )
        if self.schema_version != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "observation schema_version must be 1."
            )
        expected = _INTERVAL_SPECS[interval]
        if self.candle_count != expected["candle_count"]:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("candle_count diverges from the declared evidence.")
        if self.first_candle_open_utc != expected["first_candle_open_utc"]:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "first_candle_open_utc diverges from the declared evidence."
            )
        if self.last_candle_open_utc != expected["last_candle_open_utc"]:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "last_candle_open_utc diverges from the declared evidence."
            )
        if self.duplicate_count != expected["duplicate_count"]:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("duplicate_count diverges from the declared evidence.")
        if self.gap_count != expected["gap_count"]:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("gap_count diverges from the declared evidence.")
        if self.page_count != expected["page_count"]:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("page_count diverges from the declared evidence.")
        if self.pagination_limit != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PAGINATION_LIMIT:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "pagination_limit diverges from the declared evidence."
            )
        if self.all_confirm_closed is not True:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "all_confirm_closed must remain true for the observed historical windows."
            )
        if self.incomplete_candle_confirm_observed is not True:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "incomplete_candle_confirm_observed must remain true."
            )
        if self.last_candle_open_utc < self.first_candle_open_utc:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "last_candle_open_utc must not precede first_candle_open_utc."
            )
        expected_hash = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.observation_hash:
            if self.observation_hash != expected_hash:
                raise HistoricalFuturesMarketOperationalQualificationValidationError("observation hash mismatch.")
        else:
            object.__setattr__(self, "observation_hash", expected_hash)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "provider_qualification": self.provider_qualification.as_dict(),
            "candle_count": self.candle_count,
            "first_candle_open_utc": _utc_iso(self.first_candle_open_utc),
            "last_candle_open_utc": _utc_iso(self.last_candle_open_utc),
            "duplicate_count": self.duplicate_count,
            "gap_count": self.gap_count,
            "page_count": self.page_count,
            "pagination_limit": self.pagination_limit,
            "all_confirm_closed": self.all_confirm_closed,
            "incomplete_candle_confirm_observed": self.incomplete_candle_confirm_observed,
        }
        if include_hash:
            payload["observation_hash"] = self.observation_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketOperationalQualificationObservation":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketOperationalQualificationValidationError("observation must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "provider_qualification",
                "candle_count",
                "first_candle_open_utc",
                "last_candle_open_utc",
                "duplicate_count",
                "gap_count",
                "page_count",
                "pagination_limit",
                "all_confirm_closed",
                "incomplete_candle_confirm_observed",
                "observation_hash",
            },
            name="observation",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                provider_qualification=HistoricalProviderQualification.from_dict(mapping["provider_qualification"]),
                candle_count=mapping["candle_count"],
                first_candle_open_utc=mapping["first_candle_open_utc"],
                last_candle_open_utc=mapping["last_candle_open_utc"],
                duplicate_count=mapping["duplicate_count"],
                gap_count=mapping["gap_count"],
                page_count=mapping["page_count"],
                pagination_limit=mapping["pagination_limit"],
                all_confirm_closed=mapping["all_confirm_closed"],
                incomplete_candle_confirm_observed=mapping["incomplete_candle_confirm_observed"],
                observation_hash=mapping.get("observation_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("observation is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketOperationalQualificationProtocol:
    coverage_start_utc: datetime
    coverage_end_utc: datetime
    frozen_window_names: tuple[str, ...]
    frozen_window_hashes: tuple[str, ...]
    interval_names: tuple[str, ...]
    interval_observation_hashes: tuple[str, ...]
    canonical_source_name: str
    canonical_source_provider_id: str
    candidate_source_name: str
    candidate_provider_id: str
    candidate_market_type: str
    candidate_symbol: str
    candidate_external_symbol: str
    candidate_time_semantics: str
    candidate_access_type: str
    candidate_provider_version: str
    candidate_provider_exchange: str
    candidate_endpoint_url: str
    candidate_documentation_url: str
    candidate_endpoint_path: str
    operational_qualification_status: str
    coverage_scope_statement: str
    non_ingestion_scope_statement: str
    endpoint_behavior_statement: str
    window_count: int
    interval_count: int
    schema_version: int = HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION
    protocol_name: str = HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_PROTOCOL_NAME
    protocol_version: str = HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_PROTOCOL_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    protocol_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "coverage_start_utc", _require_utc_datetime(self.coverage_start_utc, "coverage_start_utc"))
        object.__setattr__(self, "coverage_end_utc", _require_utc_datetime(self.coverage_end_utc, "coverage_end_utc"))
        if not isinstance(self.frozen_window_names, tuple):
            object.__setattr__(self, "frozen_window_names", tuple(self.frozen_window_names))
        if not isinstance(self.frozen_window_hashes, tuple):
            object.__setattr__(self, "frozen_window_hashes", tuple(self.frozen_window_hashes))
        if not isinstance(self.interval_names, tuple):
            object.__setattr__(self, "interval_names", tuple(self.interval_names))
        if not isinstance(self.interval_observation_hashes, tuple):
            object.__setattr__(self, "interval_observation_hashes", tuple(self.interval_observation_hashes))
        object.__setattr__(self, "frozen_window_names", tuple(_require_str(item, "frozen_window_name").lower() for item in self.frozen_window_names))
        object.__setattr__(self, "frozen_window_hashes", tuple(_require_str(item, "frozen_window_hash") for item in self.frozen_window_hashes))
        object.__setattr__(self, "interval_names", tuple(_require_str(item, "interval_name") for item in self.interval_names))
        object.__setattr__(self, "interval_observation_hashes", tuple(_require_str(item, "interval_observation_hash") for item in self.interval_observation_hashes))
        object.__setattr__(self, "canonical_source_name", _require_str(self.canonical_source_name, "canonical_source_name"))
        object.__setattr__(self, "canonical_source_provider_id", _require_str(self.canonical_source_provider_id, "canonical_source_provider_id"))
        object.__setattr__(self, "candidate_source_name", _require_str(self.candidate_source_name, "candidate_source_name"))
        object.__setattr__(self, "candidate_provider_id", _require_str(self.candidate_provider_id, "candidate_provider_id"))
        object.__setattr__(self, "candidate_market_type", _require_str(self.candidate_market_type, "candidate_market_type"))
        object.__setattr__(self, "candidate_symbol", _require_str(self.candidate_symbol, "candidate_symbol"))
        object.__setattr__(self, "candidate_external_symbol", _require_str(self.candidate_external_symbol, "candidate_external_symbol"))
        object.__setattr__(self, "candidate_time_semantics", _require_str(self.candidate_time_semantics, "candidate_time_semantics"))
        object.__setattr__(self, "candidate_access_type", _require_str(self.candidate_access_type, "candidate_access_type"))
        object.__setattr__(self, "candidate_provider_version", _require_str(self.candidate_provider_version, "candidate_provider_version"))
        object.__setattr__(self, "candidate_provider_exchange", _require_str(self.candidate_provider_exchange, "candidate_provider_exchange"))
        object.__setattr__(self, "candidate_endpoint_url", _require_str(self.candidate_endpoint_url, "candidate_endpoint_url"))
        object.__setattr__(self, "candidate_documentation_url", _require_str(self.candidate_documentation_url, "candidate_documentation_url"))
        object.__setattr__(self, "candidate_endpoint_path", _require_str(self.candidate_endpoint_path, "candidate_endpoint_path"))
        object.__setattr__(self, "operational_qualification_status", _require_str(self.operational_qualification_status, "operational_qualification_status"))
        object.__setattr__(self, "coverage_scope_statement", _require_str(self.coverage_scope_statement, "coverage_scope_statement"))
        object.__setattr__(self, "non_ingestion_scope_statement", _require_str(self.non_ingestion_scope_statement, "non_ingestion_scope_statement"))
        object.__setattr__(self, "endpoint_behavior_statement", _require_str(self.endpoint_behavior_statement, "endpoint_behavior_statement"))
        object.__setattr__(self, "window_count", _require_int(self.window_count, "window_count"))
        object.__setattr__(self, "interval_count", _require_int(self.interval_count, "interval_count"))
        object.__setattr__(self, "protocol_name", _require_str(self.protocol_name, "protocol_name"))
        object.__setattr__(self, "protocol_version", _require_str(self.protocol_version, "protocol_version"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "operational qualification schema_version must be 1."
            )
        if self.protocol_name != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_PROTOCOL_NAME:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "protocol_name diverges from the declared operational qualification contract."
            )
        if self.protocol_version != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_PROTOCOL_VERSION:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "protocol_version diverges from the declared operational qualification contract."
            )
        if self.candidate_source_name != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SOURCE_NAME:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("candidate_source_name must remain OKX spot.")
        if self.candidate_provider_id != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_ID:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("candidate_provider_id must remain okx.public.klines.")
        if self.canonical_source_name != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_NAME:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("canonical_source_name must remain KuCoin spot.")
        if self.canonical_source_provider_id != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "canonical_source_provider_id must remain the KuCoin provider id."
            )
        if self.candidate_market_type != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_MARKET_TYPE:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("candidate_market_type must remain spot.")
        if self.candidate_symbol != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SYMBOL:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("candidate_symbol must remain BTCUSDT.")
        if self.candidate_external_symbol != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("candidate_external_symbol must remain BTC-USDT.")
        if self.candidate_time_semantics != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_TIME_SEMANTICS:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("candidate_time_semantics must remain utc.")
        if self.candidate_access_type != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ACCESS_TYPE:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("candidate_access_type must remain public_no_auth.")
        if self.candidate_provider_version != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_VERSION:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("candidate_provider_version must remain v1.")
        if self.candidate_provider_exchange != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("candidate_provider_exchange must remain okx.")
        if self.candidate_endpoint_url != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_URL:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("candidate_endpoint_url diverges from the declared evidence.")
        if self.candidate_documentation_url != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "candidate_documentation_url diverges from the declared evidence."
            )
        if self.candidate_endpoint_path != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_PATH:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "candidate_endpoint_path diverges from the declared evidence."
            )
        if self.operational_qualification_status != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "operational_qualification_status diverges from the declared evidence."
            )
        if self.coverage_scope_statement != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "coverage_scope_statement diverges from the declared evidence."
            )
        if self.non_ingestion_scope_statement != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "non_ingestion_scope_statement diverges from the declared evidence."
            )
        if self.endpoint_behavior_statement != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_ENDPOINT_BEHAVIOR_STATEMENT:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "endpoint_behavior_statement diverges from the declared evidence."
            )
        if self.window_count != 3:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("window_count must be exactly three.")
        if self.interval_count != 3:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("interval_count must be exactly three.")
        if self.frozen_window_names != _expected_window_name_order():
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "frozen_window_names must remain reference, validation, test."
            )
        if self.interval_names != _expected_interval_order():
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "interval_names must remain 15m, 1h, 4h."
            )
        if len(self.frozen_window_hashes) != 3:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "frozen_window_hashes must contain three window hashes."
            )
        if len(self.interval_observation_hashes) != 3:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "interval_observation_hashes must contain three observation hashes."
            )
        if self.coverage_end_utc <= self.coverage_start_utc:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "coverage_end_utc must be after coverage_start_utc."
            )
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.protocol_hash:
            if self.protocol_hash != expected:
                raise HistoricalFuturesMarketOperationalQualificationValidationError("protocol hash mismatch.")
        else:
            object.__setattr__(self, "protocol_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "protocol_name": self.protocol_name,
            "protocol_version": self.protocol_version,
            "coverage_start_utc": _utc_iso(self.coverage_start_utc),
            "coverage_end_utc": _utc_iso(self.coverage_end_utc),
            "frozen_window_names": list(self.frozen_window_names),
            "frozen_window_hashes": list(self.frozen_window_hashes),
            "interval_names": list(self.interval_names),
            "interval_observation_hashes": list(self.interval_observation_hashes),
            "canonical_source_name": self.canonical_source_name,
            "canonical_source_provider_id": self.canonical_source_provider_id,
            "candidate_source_name": self.candidate_source_name,
            "candidate_provider_id": self.candidate_provider_id,
            "candidate_market_type": self.candidate_market_type,
            "candidate_symbol": self.candidate_symbol,
            "candidate_external_symbol": self.candidate_external_symbol,
            "candidate_time_semantics": self.candidate_time_semantics,
            "candidate_access_type": self.candidate_access_type,
            "candidate_provider_version": self.candidate_provider_version,
            "candidate_provider_exchange": self.candidate_provider_exchange,
            "candidate_endpoint_url": self.candidate_endpoint_url,
            "candidate_documentation_url": self.candidate_documentation_url,
            "candidate_endpoint_path": self.candidate_endpoint_path,
            "operational_qualification_status": self.operational_qualification_status,
            "coverage_scope_statement": self.coverage_scope_statement,
            "non_ingestion_scope_statement": self.non_ingestion_scope_statement,
            "endpoint_behavior_statement": self.endpoint_behavior_statement,
            "window_count": self.window_count,
            "interval_count": self.interval_count,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }
        if include_hash:
            payload["protocol_hash"] = self.protocol_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketOperationalQualificationProtocol":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "operational qualification protocol must be a mapping."
            )
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "protocol_name",
                "protocol_version",
                "coverage_start_utc",
                "coverage_end_utc",
                "frozen_window_names",
                "frozen_window_hashes",
                "interval_names",
                "interval_observation_hashes",
                "canonical_source_name",
                "canonical_source_provider_id",
                "candidate_source_name",
                "candidate_provider_id",
                "candidate_market_type",
                "candidate_symbol",
                "candidate_external_symbol",
                "candidate_time_semantics",
                "candidate_access_type",
                "candidate_provider_version",
                "candidate_provider_exchange",
                "candidate_endpoint_url",
                "candidate_documentation_url",
                "candidate_endpoint_path",
                "operational_qualification_status",
                "coverage_scope_statement",
                "non_ingestion_scope_statement",
                "endpoint_behavior_statement",
                "window_count",
                "interval_count",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "protocol_hash",
            },
            name="operational qualification protocol",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                protocol_name=mapping["protocol_name"],
                protocol_version=mapping["protocol_version"],
                coverage_start_utc=mapping["coverage_start_utc"],
                coverage_end_utc=mapping["coverage_end_utc"],
                frozen_window_names=tuple(mapping["frozen_window_names"]),
                frozen_window_hashes=tuple(mapping["frozen_window_hashes"]),
                interval_names=tuple(mapping["interval_names"]),
                interval_observation_hashes=tuple(mapping["interval_observation_hashes"]),
                canonical_source_name=mapping["canonical_source_name"],
                canonical_source_provider_id=mapping["canonical_source_provider_id"],
                candidate_source_name=mapping["candidate_source_name"],
                candidate_provider_id=mapping["candidate_provider_id"],
                candidate_market_type=mapping["candidate_market_type"],
                candidate_symbol=mapping["candidate_symbol"],
                candidate_external_symbol=mapping["candidate_external_symbol"],
                candidate_time_semantics=mapping["candidate_time_semantics"],
                candidate_access_type=mapping["candidate_access_type"],
                candidate_provider_version=mapping["candidate_provider_version"],
                candidate_provider_exchange=mapping["candidate_provider_exchange"],
                candidate_endpoint_url=mapping["candidate_endpoint_url"],
                candidate_documentation_url=mapping["candidate_documentation_url"],
                candidate_endpoint_path=mapping["candidate_endpoint_path"],
                operational_qualification_status=mapping["operational_qualification_status"],
                coverage_scope_statement=mapping["coverage_scope_statement"],
                non_ingestion_scope_statement=mapping["non_ingestion_scope_statement"],
                endpoint_behavior_statement=mapping["endpoint_behavior_statement"],
                window_count=mapping["window_count"],
                interval_count=mapping["interval_count"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                protocol_hash=mapping.get("protocol_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "operational qualification protocol is incomplete."
            ) from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketOperationalQualificationSummary:
    window_count: int
    interval_count: int
    candle_count: int
    duplicate_count: int
    gap_count: int
    page_count: int
    all_confirm_closed: bool
    incomplete_candle_confirm_observed: bool
    operational_qualification_status: str
    coverage_scope_statement: str
    non_ingestion_scope_statement: str
    schema_version: int = HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION
    summary_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_count", _require_int(self.window_count, "window_count"))
        object.__setattr__(self, "interval_count", _require_int(self.interval_count, "interval_count"))
        object.__setattr__(self, "candle_count", _require_int(self.candle_count, "candle_count"))
        object.__setattr__(self, "duplicate_count", _require_int(self.duplicate_count, "duplicate_count", allow_zero=True))
        object.__setattr__(self, "gap_count", _require_int(self.gap_count, "gap_count", allow_zero=True))
        object.__setattr__(self, "page_count", _require_int(self.page_count, "page_count"))
        object.__setattr__(self, "all_confirm_closed", _require_bool(self.all_confirm_closed, "all_confirm_closed"))
        object.__setattr__(
            self,
            "incomplete_candle_confirm_observed",
            _require_bool(self.incomplete_candle_confirm_observed, "incomplete_candle_confirm_observed"),
        )
        object.__setattr__(self, "operational_qualification_status", _require_str(self.operational_qualification_status, "operational_qualification_status"))
        object.__setattr__(self, "coverage_scope_statement", _require_str(self.coverage_scope_statement, "coverage_scope_statement"))
        object.__setattr__(self, "non_ingestion_scope_statement", _require_str(self.non_ingestion_scope_statement, "non_ingestion_scope_statement"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "summary schema_version must be 1."
            )
        if self.window_count != 3:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("window_count must be exactly three.")
        if self.interval_count != 3:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("interval_count must be exactly three.")
        if self.candle_count != 105:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("candle_count must be exactly 105.")
        if self.duplicate_count != 0:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("duplicate_count must remain zero.")
        if self.gap_count != 0:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("gap_count must remain zero.")
        if self.page_count != 3:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("page_count must be exactly three.")
        if self.all_confirm_closed is not True:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "all_confirm_closed must remain true."
            )
        if self.incomplete_candle_confirm_observed is not True:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "incomplete_candle_confirm_observed must remain true."
            )
        if self.operational_qualification_status != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "operational_qualification_status diverges from the declared evidence."
            )
        if self.coverage_scope_statement != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "coverage_scope_statement diverges from the declared evidence."
            )
        if self.non_ingestion_scope_statement != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "non_ingestion_scope_statement diverges from the declared evidence."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.summary_hash:
            if self.summary_hash != expected:
                raise HistoricalFuturesMarketOperationalQualificationValidationError("summary hash mismatch.")
        else:
            object.__setattr__(self, "summary_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "window_count": self.window_count,
            "interval_count": self.interval_count,
            "candle_count": self.candle_count,
            "duplicate_count": self.duplicate_count,
            "gap_count": self.gap_count,
            "page_count": self.page_count,
            "all_confirm_closed": self.all_confirm_closed,
            "incomplete_candle_confirm_observed": self.incomplete_candle_confirm_observed,
            "operational_qualification_status": self.operational_qualification_status,
            "coverage_scope_statement": self.coverage_scope_statement,
            "non_ingestion_scope_statement": self.non_ingestion_scope_statement,
        }
        if include_hash:
            payload["summary_hash"] = self.summary_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketOperationalQualificationSummary":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketOperationalQualificationValidationError("summary must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "window_count",
                "interval_count",
                "candle_count",
                "duplicate_count",
                "gap_count",
                "page_count",
                "all_confirm_closed",
                "incomplete_candle_confirm_observed",
                "operational_qualification_status",
                "coverage_scope_statement",
                "non_ingestion_scope_statement",
                "summary_hash",
            },
            name="summary",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                window_count=mapping["window_count"],
                interval_count=mapping["interval_count"],
                candle_count=mapping["candle_count"],
                duplicate_count=mapping["duplicate_count"],
                gap_count=mapping["gap_count"],
                page_count=mapping["page_count"],
                all_confirm_closed=mapping["all_confirm_closed"],
                incomplete_candle_confirm_observed=mapping["incomplete_candle_confirm_observed"],
                operational_qualification_status=mapping["operational_qualification_status"],
                coverage_scope_statement=mapping["coverage_scope_statement"],
                non_ingestion_scope_statement=mapping["non_ingestion_scope_statement"],
                summary_hash=mapping.get("summary_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketOperationalQualificationValidationError("summary is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketOperationalQualificationReport:
    protocol: HistoricalFuturesMarketOperationalQualificationProtocol
    frozen_windows: tuple[HistoricalFuturesMarketOperationalQualificationWindow, ...]
    interval_observations: tuple[HistoricalFuturesMarketOperationalQualificationObservation, ...]
    summary: HistoricalFuturesMarketOperationalQualificationSummary
    schema_version: int = HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    report_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.protocol, HistoricalFuturesMarketOperationalQualificationProtocol):
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "protocol must be an operational qualification protocol instance."
            )
        if not isinstance(self.summary, HistoricalFuturesMarketOperationalQualificationSummary):
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "summary must be an operational qualification summary instance."
            )
        if not isinstance(self.frozen_windows, tuple):
            object.__setattr__(self, "frozen_windows", tuple(self.frozen_windows))
        if not isinstance(self.interval_observations, tuple):
            object.__setattr__(self, "interval_observations", tuple(self.interval_observations))
        if len(self.frozen_windows) != 3:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "frozen_windows must contain exactly three windows."
            )
        if len(self.interval_observations) != 3:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "interval_observations must contain exactly three interval observations."
            )
        window_names = tuple(window.window_name for window in self.frozen_windows)
        if window_names != _expected_window_name_order():
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "frozen_windows must preserve reference, validation, test order."
            )
        interval_names = tuple(observation.provider_qualification.interval for observation in self.interval_observations)
        if interval_names != _expected_interval_order():
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "interval_observations must preserve 15m, 1h, 4h order."
            )
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        if self.schema_version != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "operational qualification report schema_version must be 1."
            )
        expected_protocol = _build_protocol(self.frozen_windows, self.interval_observations, self.summary, self)
        if self.protocol != expected_protocol:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "operational qualification protocol diverges from the declared evidence."
            )
        expected_summary = _build_summary(self.frozen_windows, self.interval_observations, self)
        if self.summary != expected_summary:
            raise HistoricalFuturesMarketOperationalQualificationIntegrityError(
                "operational qualification summary diverges from the declared evidence."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.report_hash:
            if self.report_hash != expected:
                raise HistoricalFuturesMarketOperationalQualificationValidationError("report hash mismatch.")
        else:
            object.__setattr__(self, "report_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "protocol": self.protocol.as_hash_payload(include_hash=False),
            "frozen_windows": [window.as_dict() for window in self.frozen_windows],
            "interval_observations": [observation.as_dict() for observation in self.interval_observations],
            "summary": self.summary.as_dict(),
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }
        if include_hash:
            payload["report_hash"] = self.report_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketOperationalQualificationReport":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "operational qualification report must be a mapping."
            )
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "protocol",
                "frozen_windows",
                "interval_observations",
                "summary",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "report_hash",
            },
            name="operational qualification report",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                protocol=HistoricalFuturesMarketOperationalQualificationProtocol.from_dict(mapping["protocol"]),
                frozen_windows=tuple(
                    HistoricalFuturesMarketOperationalQualificationWindow.from_dict(item)
                    for item in mapping["frozen_windows"]
                ),
                interval_observations=tuple(
                    HistoricalFuturesMarketOperationalQualificationObservation.from_dict(item)
                    for item in mapping["interval_observations"]
                ),
                summary=HistoricalFuturesMarketOperationalQualificationSummary.from_dict(mapping["summary"]),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                report_hash=mapping.get("report_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketOperationalQualificationValidationError(
                "operational qualification report is incomplete."
            ) from exc
        except (
            HistoricalFuturesMarketOperationalQualificationValidationError,
            HistoricalFuturesMarketOperationalQualificationIntegrityError,
            HistoricalFuturesMarketOperationalQualificationError,
            HistoricalDataValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise HistoricalFuturesMarketOperationalQualificationIntegrityError(str(exc)) from exc


def _build_frozen_windows() -> tuple[HistoricalFuturesMarketOperationalQualificationWindow, ...]:
    return tuple(
        HistoricalFuturesMarketOperationalQualificationWindow(window_name=name, start_utc=start, end_utc=end)
        for name, (start, end) in _WINDOW_SPECS.items()
    )


def _build_interval_observations() -> tuple[HistoricalFuturesMarketOperationalQualificationObservation, ...]:
    observations = []
    for interval in _expected_interval_order():
        spec = _INTERVAL_SPECS[interval]
        observations.append(
            HistoricalFuturesMarketOperationalQualificationObservation(
                provider_qualification=_expected_provider_qualification(interval),
                candle_count=spec["candle_count"],
                first_candle_open_utc=spec["first_candle_open_utc"],
                last_candle_open_utc=spec["last_candle_open_utc"],
                duplicate_count=spec["duplicate_count"],
                gap_count=spec["gap_count"],
                page_count=spec["page_count"],
                pagination_limit=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PAGINATION_LIMIT,
                all_confirm_closed=True,
                incomplete_candle_confirm_observed=True,
            )
        )
    return tuple(observations)


def _build_protocol(
    frozen_windows: Sequence[HistoricalFuturesMarketOperationalQualificationWindow],
    interval_observations: Sequence[HistoricalFuturesMarketOperationalQualificationObservation],
    summary: HistoricalFuturesMarketOperationalQualificationSummary | None = None,
    report: HistoricalFuturesMarketOperationalQualificationReport | None = None,
) -> HistoricalFuturesMarketOperationalQualificationProtocol:
    _ = summary
    _ = report
    return HistoricalFuturesMarketOperationalQualificationProtocol(
        coverage_start_utc=frozen_windows[0].start_utc,
        coverage_end_utc=frozen_windows[-1].end_utc,
        frozen_window_names=tuple(window.window_name for window in frozen_windows),
        frozen_window_hashes=tuple(window.window_hash for window in frozen_windows),
        interval_names=tuple(observation.provider_qualification.interval for observation in interval_observations),
        interval_observation_hashes=tuple(observation.observation_hash for observation in interval_observations),
        canonical_source_name=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_NAME,
        canonical_source_provider_id=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID,
        candidate_source_name=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SOURCE_NAME,
        candidate_provider_id=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_ID,
        candidate_market_type=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_MARKET_TYPE,
        candidate_symbol=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SYMBOL,
        candidate_external_symbol=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL,
        candidate_time_semantics=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_TIME_SEMANTICS,
        candidate_access_type=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ACCESS_TYPE,
        candidate_provider_version=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_VERSION,
        candidate_provider_exchange=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE,
        candidate_endpoint_url=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_URL,
        candidate_documentation_url=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL,
        candidate_endpoint_path=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_PATH,
        operational_qualification_status=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS,
        coverage_scope_statement=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT,
        non_ingestion_scope_statement=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT,
        endpoint_behavior_statement=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_ENDPOINT_BEHAVIOR_STATEMENT,
        window_count=len(frozen_windows),
        interval_count=len(interval_observations),
    )


def _build_summary(
    frozen_windows: Sequence[HistoricalFuturesMarketOperationalQualificationWindow],
    interval_observations: Sequence[HistoricalFuturesMarketOperationalQualificationObservation],
    report: HistoricalFuturesMarketOperationalQualificationReport | None = None,
) -> HistoricalFuturesMarketOperationalQualificationSummary:
    _ = report
    return HistoricalFuturesMarketOperationalQualificationSummary(
        window_count=len(frozen_windows),
        interval_count=len(interval_observations),
        candle_count=sum(item.candle_count for item in interval_observations),
        duplicate_count=sum(item.duplicate_count for item in interval_observations),
        gap_count=sum(item.gap_count for item in interval_observations),
        page_count=sum(item.page_count for item in interval_observations),
        all_confirm_closed=all(item.all_confirm_closed for item in interval_observations),
        incomplete_candle_confirm_observed=all(
            item.incomplete_candle_confirm_observed for item in interval_observations
        ),
        operational_qualification_status=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS,
        coverage_scope_statement=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT,
        non_ingestion_scope_statement=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT,
    )


def build_historical_futures_market_operational_qualification_report(
    _: Any | None = None,
) -> HistoricalFuturesMarketOperationalQualificationReport:
    frozen_windows = _build_frozen_windows()
    interval_observations = _build_interval_observations()
    summary = _build_summary(frozen_windows, interval_observations)
    protocol = _build_protocol(frozen_windows, interval_observations, summary)
    return HistoricalFuturesMarketOperationalQualificationReport(
        protocol=protocol,
        frozen_windows=frozen_windows,
        interval_observations=interval_observations,
        summary=summary,
    )


def run_historical_futures_market_operational_qualification(
    _: Any | None = None,
    *,
    output_file: str | Path | None = None,
) -> HistoricalFuturesMarketOperationalQualificationReport:
    report = build_historical_futures_market_operational_qualification_report()
    if output_file is not None:
        save_historical_futures_market_operational_qualification_report(output_file, report)
    return report


def _read(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HistoricalFuturesMarketOperationalQualificationValidationError(
            "operational qualification report not found."
        ) from exc
    except Exception as exc:
        raise HistoricalFuturesMarketOperationalQualificationIntegrityError(
            "operational qualification report is invalid JSON."
        ) from exc
    if not isinstance(value, Mapping):
        raise HistoricalFuturesMarketOperationalQualificationIntegrityError(
            "operational qualification report must be a JSON object."
        )
    return value


def load_historical_futures_market_operational_qualification_report(
    path: str | Path,
) -> HistoricalFuturesMarketOperationalQualificationReport:
    payload = _read(Path(path))
    try:
        report = HistoricalFuturesMarketOperationalQualificationReport.from_dict(payload)
    except (
        KeyError,
        TypeError,
        ValueError,
        HistoricalFuturesMarketOperationalQualificationValidationError,
        HistoricalFuturesMarketOperationalQualificationIntegrityError,
        HistoricalDataValidationError,
    ) as exc:
        raise HistoricalFuturesMarketOperationalQualificationIntegrityError(str(exc)) from exc
    if report.as_dict() != payload:
        raise HistoricalFuturesMarketOperationalQualificationIntegrityError(
            "operational qualification report payload mismatch."
        )
    return report


def save_historical_futures_market_operational_qualification_report(
    path: str | Path,
    report: HistoricalFuturesMarketOperationalQualificationReport,
) -> HistoricalFuturesMarketOperationalQualificationReport:
    file_path = Path(path)
    payload = report.as_dict()
    if file_path.exists():
        existing = load_historical_futures_market_operational_qualification_report(file_path)
        if existing.as_dict() != payload:
            raise HistoricalFuturesMarketOperationalQualificationConflictError(
                "operational qualification report already exists and differs."
            )
        return existing
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_name(f".{file_path.name}.{os.getpid()}.{id(report)}.tmp")
    try:
        tmp.write_text(_canonical_json(payload), encoding="utf-8")
        try:
            os.link(tmp, file_path)
        except FileExistsError:
            existing = load_historical_futures_market_operational_qualification_report(file_path)
            if existing.as_dict() != payload:
                raise HistoricalFuturesMarketOperationalQualificationConflictError(
                    "operational qualification report already exists and differs."
                )
            return existing
    except Exception as exc:
        if isinstance(exc, HistoricalFuturesMarketOperationalQualificationConflictError):
            raise
        raise HistoricalFuturesMarketOperationalQualificationValidationError(
            "failed to write operational qualification report atomically."
        ) from exc
    finally:
        tmp.unlink(missing_ok=True)
    return report


def verify_historical_futures_market_operational_qualification_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_operational_qualification_report(path)
    return {
        "verified": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "summary_hash": report.summary.summary_hash,
        "classification": HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS,
        "operational_qualification_status": report.protocol.operational_qualification_status,
        "window_count": report.protocol.window_count,
        "interval_count": report.protocol.interval_count,
        "candle_count": report.summary.candle_count,
        "all_confirm_closed": report.summary.all_confirm_closed,
    }


def status_historical_futures_market_operational_qualification_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_operational_qualification_report(path)
    summary = report.summary
    return {
        "exists": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "summary_hash": summary.summary_hash,
        "window_count": summary.window_count,
        "interval_count": summary.interval_count,
        "candle_count": summary.candle_count,
        "duplicate_count": summary.duplicate_count,
        "gap_count": summary.gap_count,
        "page_count": summary.page_count,
        "all_confirm_closed": summary.all_confirm_closed,
        "incomplete_candle_confirm_observed": summary.incomplete_candle_confirm_observed,
        "operational_qualification_status": summary.operational_qualification_status,
        "candidate_source_name": report.protocol.candidate_source_name,
        "candidate_provider_id": report.protocol.candidate_provider_id,
        "candidate_symbol": report.protocol.candidate_symbol,
        "classification": HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS,
    }


def reject_historical_futures_market_operational_qualification_promotion(
    _: HistoricalFuturesMarketOperationalQualificationReport,
) -> None:
    raise HistoricalFuturesMarketOperationalQualificationPromotionError(
        "operational qualification is not promotion evidence."
    )


__all__ = [
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_NAME",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ACCESS_TYPE",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_PATH",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_URL",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_INTERVALS",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_MARKET_TYPE",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_ID",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_VERSION",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PAGINATION_LIMIT",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SOURCE_NAME",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SYMBOL",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_TIME_SEMANTICS",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_ENDPOINT_BEHAVIOR_STATEMENT",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_OPERATIONAL_STATUS",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_PROTOCOL_NAME",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_PROTOCOL_VERSION",
    "HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION",
    "HistoricalFuturesMarketOperationalQualificationConflictError",
    "HistoricalFuturesMarketOperationalQualificationError",
    "HistoricalFuturesMarketOperationalQualificationIntegrityError",
    "HistoricalFuturesMarketOperationalQualificationObservation",
    "HistoricalFuturesMarketOperationalQualificationProtocol",
    "HistoricalFuturesMarketOperationalQualificationPromotionError",
    "HistoricalFuturesMarketOperationalQualificationReport",
    "HistoricalFuturesMarketOperationalQualificationSummary",
    "HistoricalFuturesMarketOperationalQualificationValidationError",
    "HistoricalFuturesMarketOperationalQualificationWindow",
    "build_historical_futures_market_operational_qualification_report",
    "load_historical_futures_market_operational_qualification_report",
    "reject_historical_futures_market_operational_qualification_promotion",
    "run_historical_futures_market_operational_qualification",
    "save_historical_futures_market_operational_qualification_report",
    "status_historical_futures_market_operational_qualification_report",
    "verify_historical_futures_market_operational_qualification_report",
]
