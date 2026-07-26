"""Research-only integral source qualification for the observed OKX spot candidate.

This module freezes the read-only Phase 18G audit result into an immutable,
deterministic, fail-closed contract. It records only the observed operational
evidence for BTC-USDT spot on 1H across the audited historical period and does
not authorize ingestion, dataset preparation, replay, backtest, paper trading,
or live trading.
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
from market_data.provider_qualification import HistoricalProviderQualification

HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCHEMA_VERSION = 1
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PROTOCOL_NAME = (
    "historical_futures_market_integral_source_qualification"
)
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PROTOCOL_VERSION = "v1"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS = (
    "integral_historical_operational_evidence_observed_not_authorized_for_ingestion"
)
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCOPE = (
    "single_candidate_single_market_single_instrument_single_interval_single_audited_period"
)
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_SOURCE_NAME = "KuCoin spot"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID = "kucoin.public.klines"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_MARKET_TYPE = "spot"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_SYMBOL = "BTCUSDT"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_NAME = "OKX spot"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_ID = "okx.public.klines"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_MARKET_TYPE = "spot"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_SYMBOL = "BTCUSDT"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL = "BTC-USDT"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE = "okx"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_VERSION = "v1"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_ACCESS_TYPE = "public_no_auth"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_TIME_SEMANTICS = "utc"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL = (
    "https://www.okx.com/docs-v5/en/"
)
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_ENDPOINT_URL = (
    "https://www.okx.com/api/v5/market/history-candles"
)
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_ENDPOINT_PATH = (
    "/api/v5/market/history-candles"
)
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE = (
    "confirm=0 means incomplete; confirm=1 means completed"
)
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_AUDITED_INTERVAL_NAME = "1H"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_AUDIT_START_UTC = datetime(
    2021, 2, 12, 0, 0, 0, tzinfo=timezone.utc
)
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_AUDIT_END_EXCLUSIVE_UTC = datetime(
    2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc
)
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_FIRST_CANDLE_OPEN_UTC = datetime(
    2021, 2, 12, 0, 0, 0, tzinfo=timezone.utc
)
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_LAST_CANDLE_OPEN_UTC = datetime(
    2025, 12, 31, 23, 0, 0, tzinfo=timezone.utc
)
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_EXPECTED_CANDLE_COUNT = 42816
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PAGES_OBSERVED = 429
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_LIMIT_USED = 100
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CURSOR_NAME = "after"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CURSOR_EXCLUSIVE = True
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_COLLECTION_DIRECTION = "reverse_chronological"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CONFIRM_VALUE = 1
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_UTC_TIME_SEMANTICS = "utc"
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_DUPLICATE_COUNT = 0
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_GAP_COUNT = 0
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_OVERLAP_COUNT = 0
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CURSOR_NO_PROGRESS_COUNT = 0
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_HTTP_ERROR_COUNT = 0
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_TIMEOUT_COUNT = 0
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_INCOMPLETE_CANDLE_COUNT = 0
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_YEAR_COUNT = 5
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_INTERVAL_COUNT = 1
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PROVIDER_QUALIFICATION_COUNT = 1
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_ANNUAL_RESULT_COUNT = 5
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_COVERAGE_SCOPE_STATEMENT = (
    "Coverage is limited to the audited BTC-USDT spot 1H period from 2021-02-12T00:00:00Z to "
    "2026-01-01T00:00:00Z; coverage beyond that period remains unverified."
)
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT = (
    "No API polling, download, dataset, manifest, candle hash, replay, backtest, performance comparison, "
    "paper trading, or live trading is authorized."
)
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT = (
    "The OKX history-candles endpoint was observed with after as the exclusive cursor and limit=100, "
    "and pages can include candles before the requested start that must be filtered in memory."
)
HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_RISK_NOTES: tuple[str, ...] = (
    "1H is mandatory; 1h is not a valid alias for this contract.",
    "The documented limit should be reconfirmed in any future implementation before API calls.",
    "Pagination can return candles before the requested window and requires explicit in-memory filtering.",
    "The qualification is limited to the audited period and does not imply retention beyond it.",
    "OKX remains separate from KuCoin and is not authorized for ingestion.",
)

_ANNUAL_SPECS: dict[int, dict[str, Any]] = {
    2021: {
        "first_timestamp_utc": datetime(2021, 2, 12, 0, 0, 0, tzinfo=timezone.utc),
        "last_timestamp_utc": datetime(2021, 12, 31, 23, 0, 0, tzinfo=timezone.utc),
        "expected_candle_count": 7752,
        "found_candle_count": 7752,
        "duplicate_count": 0,
        "gap_count": 0,
        "result": "pass",
    },
    2022: {
        "first_timestamp_utc": datetime(2022, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        "last_timestamp_utc": datetime(2022, 12, 31, 23, 0, 0, tzinfo=timezone.utc),
        "expected_candle_count": 8760,
        "found_candle_count": 8760,
        "duplicate_count": 0,
        "gap_count": 0,
        "result": "pass",
    },
    2023: {
        "first_timestamp_utc": datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        "last_timestamp_utc": datetime(2023, 12, 31, 23, 0, 0, tzinfo=timezone.utc),
        "expected_candle_count": 8760,
        "found_candle_count": 8760,
        "duplicate_count": 0,
        "gap_count": 0,
        "result": "pass",
    },
    2024: {
        "first_timestamp_utc": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        "last_timestamp_utc": datetime(2024, 12, 31, 23, 0, 0, tzinfo=timezone.utc),
        "expected_candle_count": 8784,
        "found_candle_count": 8784,
        "duplicate_count": 0,
        "gap_count": 0,
        "result": "pass",
    },
    2025: {
        "first_timestamp_utc": datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        "last_timestamp_utc": datetime(2025, 12, 31, 23, 0, 0, tzinfo=timezone.utc),
        "expected_candle_count": 8760,
        "found_candle_count": 8760,
        "duplicate_count": 0,
        "gap_count": 0,
        "result": "pass",
    },
}
_ANNUAL_YEARS: tuple[int, ...] = tuple(_ANNUAL_SPECS)


class HistoricalFuturesMarketIntegralSourceQualificationError(Exception):
    pass


class HistoricalFuturesMarketIntegralSourceQualificationValidationError(
    HistoricalFuturesMarketIntegralSourceQualificationError
):
    pass


class HistoricalFuturesMarketIntegralSourceQualificationIntegrityError(
    HistoricalFuturesMarketIntegralSourceQualificationValidationError
):
    pass


class HistoricalFuturesMarketIntegralSourceQualificationConflictError(
    HistoricalFuturesMarketIntegralSourceQualificationIntegrityError
):
    pass


class HistoricalFuturesMarketIntegralSourceQualificationPromotionError(
    HistoricalFuturesMarketIntegralSourceQualificationValidationError
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _validate_exact_keys(mapping: Mapping[str, Any], *, allowed: set[str], name: str) -> None:
    extra = set(mapping) - allowed
    if extra:
        raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
            f"{name} contains unknown fields: {sorted(extra)!r}."
        )


def _require_hash(value: Any, field_name: str) -> str:
    normalized = _require_str(value, field_name).lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
            f"{field_name} must be a 64-character hexadecimal hash."
        )
    return normalized


def _research_only(historical_research_only: bool, operational_evidence: bool, paper_promotion_eligible: bool) -> None:
    if historical_research_only is not True:
        raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
            "historical_research_only must be true."
        )
    if operational_evidence is not False:
        raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
            "operational_evidence must be false."
        )
    if paper_promotion_eligible is not False:
        raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
            "paper_promotion_eligible must be false."
        )


def _expected_annual_spec(year: int) -> dict[str, Any]:
    normalized_year = _require_int(year, "year")
    try:
        return {"year": normalized_year, **_ANNUAL_SPECS[normalized_year]}
    except KeyError as exc:
        raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
            "year must be 2021, 2022, 2023, 2024, or 2025."
        ) from exc


def _expected_provider_qualification() -> HistoricalProviderQualification:
    return HistoricalProviderQualification(
        provider_id=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_ID,
        provider_version=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_VERSION,
        market_type=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_MARKET_TYPE,
        exchange=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE,
        symbol=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_SYMBOL,
        interval=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_AUDITED_INTERVAL_NAME,
        time_semantics=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_TIME_SEMANTICS,
        access_type=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_ACCESS_TYPE,
        data_contract_version=2,
        external_symbol=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL,
        endpoint_url=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_ENDPOINT_URL,
        documentation_url=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL,
        pagination_limit=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_LIMIT_USED,
        close_time_rule=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE,
    )


def _expected_annual_results() -> tuple["HistoricalFuturesMarketIntegralSourceQualificationAnnualResult", ...]:
    return tuple(
        HistoricalFuturesMarketIntegralSourceQualificationAnnualResult(
            year=year,
            first_timestamp_utc=spec["first_timestamp_utc"],
            last_timestamp_utc=spec["last_timestamp_utc"],
            expected_candle_count=spec["expected_candle_count"],
            found_candle_count=spec["found_candle_count"],
            duplicate_count=spec["duplicate_count"],
            gap_count=spec["gap_count"],
            result=spec["result"],
        )
        for year, spec in _ANNUAL_SPECS.items()
    )


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketIntegralSourceQualificationAnnualResult:
    year: int
    first_timestamp_utc: datetime
    last_timestamp_utc: datetime
    expected_candle_count: int
    found_candle_count: int
    duplicate_count: int
    gap_count: int
    result: str
    schema_version: int = HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCHEMA_VERSION
    annual_result_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "year", _require_int(self.year, "year"))
        object.__setattr__(self, "first_timestamp_utc", _require_utc_datetime(self.first_timestamp_utc, "first_timestamp_utc"))
        object.__setattr__(self, "last_timestamp_utc", _require_utc_datetime(self.last_timestamp_utc, "last_timestamp_utc"))
        object.__setattr__(self, "expected_candle_count", _require_int(self.expected_candle_count, "expected_candle_count"))
        object.__setattr__(self, "found_candle_count", _require_int(self.found_candle_count, "found_candle_count"))
        object.__setattr__(self, "duplicate_count", _require_int(self.duplicate_count, "duplicate_count", allow_zero=True))
        object.__setattr__(self, "gap_count", _require_int(self.gap_count, "gap_count", allow_zero=True))
        object.__setattr__(self, "result", _require_str(self.result, "result").lower())
        if self.schema_version != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "annual result schema_version must be 1."
            )
        expected = _expected_annual_spec(self.year)
        if self.first_timestamp_utc != expected["first_timestamp_utc"]:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "first_timestamp_utc diverges from the audited annual evidence."
            )
        if self.last_timestamp_utc != expected["last_timestamp_utc"]:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "last_timestamp_utc diverges from the audited annual evidence."
            )
        if self.expected_candle_count != expected["expected_candle_count"]:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "expected_candle_count diverges from the audited annual evidence."
            )
        if self.found_candle_count != expected["found_candle_count"]:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "found_candle_count diverges from the audited annual evidence."
            )
        if self.duplicate_count != expected["duplicate_count"]:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "duplicate_count diverges from the audited annual evidence."
            )
        if self.gap_count != expected["gap_count"]:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "gap_count diverges from the audited annual evidence."
            )
        if self.result != expected["result"]:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "result diverges from the audited annual evidence."
            )
        expected_hash = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.annual_result_hash:
            if self.annual_result_hash != _require_hash(self.annual_result_hash, "annual_result_hash"):
                raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                    "annual result hash mismatch."
                )
            if self.annual_result_hash != expected_hash:
                raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                    "annual result hash mismatch."
                )
        else:
            object.__setattr__(self, "annual_result_hash", expected_hash)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "year": self.year,
            "first_timestamp_utc": _utc_iso(self.first_timestamp_utc),
            "last_timestamp_utc": _utc_iso(self.last_timestamp_utc),
            "expected_candle_count": self.expected_candle_count,
            "found_candle_count": self.found_candle_count,
            "duplicate_count": self.duplicate_count,
            "gap_count": self.gap_count,
            "result": self.result,
        }
        if include_hash:
            payload["annual_result_hash"] = self.annual_result_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketIntegralSourceQualificationAnnualResult":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "annual result must be a mapping."
            )
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "year",
                "first_timestamp_utc",
                "last_timestamp_utc",
                "expected_candle_count",
                "found_candle_count",
                "duplicate_count",
                "gap_count",
                "result",
                "annual_result_hash",
            },
            name="annual result",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                year=mapping["year"],
                first_timestamp_utc=mapping["first_timestamp_utc"],
                last_timestamp_utc=mapping["last_timestamp_utc"],
                expected_candle_count=mapping["expected_candle_count"],
                found_candle_count=mapping["found_candle_count"],
                duplicate_count=mapping["duplicate_count"],
                gap_count=mapping["gap_count"],
                result=mapping["result"],
                annual_result_hash=mapping.get("annual_result_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "annual result is incomplete."
            ) from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketIntegralSourceQualificationProtocol:
    provider_qualification_hash: str
    annual_result_hashes: tuple[str, ...]
    canonical_source_name: str
    canonical_source_provider_id: str
    canonical_market_type: str
    canonical_symbol: str
    candidate_source_name: str
    candidate_provider_id: str
    candidate_market_type: str
    candidate_symbol: str
    candidate_external_symbol: str
    candidate_provider_exchange: str
    candidate_provider_version: str
    candidate_access_type: str
    candidate_time_semantics: str
    candidate_endpoint_url: str
    candidate_endpoint_path: str
    candidate_documentation_url: str
    candidate_close_time_rule: str
    audited_interval_name: str
    audited_period_start_utc: datetime
    audited_period_end_exclusive_utc: datetime
    first_candle_open_utc: datetime
    last_candle_open_utc: datetime
    expected_candle_count: int
    found_candle_count: int
    pages_observed: int
    limit_used: int
    cursor_name: str
    cursor_exclusive: bool
    collect_direction: str
    confirm_value: int
    all_confirm_closed: bool
    utc_time_semantics: str
    utc_alignment_valid: bool
    duplicate_count: int
    gap_count: int
    overlap_count: int
    cursor_no_progress_count: int
    http_error_count: int
    timeout_count: int
    incomplete_candle_count: int
    year_count: int
    annual_result_count: int
    interval_count: int
    provider_qualification_count: int
    schema_version: int = HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCHEMA_VERSION
    protocol_name: str = HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PROTOCOL_NAME
    protocol_version: str = HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PROTOCOL_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    integral_source_qualification_status: str = HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS
    scope: str = HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCOPE
    coverage_scope_statement: str = HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_COVERAGE_SCOPE_STATEMENT
    non_ingestion_scope_statement: str = HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT
    pagination_behavior_statement: str = HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT
    risk_notes: tuple[str, ...] = HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_RISK_NOTES
    protocol_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_qualification_hash", _require_hash(self.provider_qualification_hash, "provider_qualification_hash"))
        if not isinstance(self.annual_result_hashes, tuple):
            object.__setattr__(self, "annual_result_hashes", tuple(self.annual_result_hashes))
        object.__setattr__(self, "annual_result_hashes", tuple(_require_hash(item, "annual_result_hash") for item in self.annual_result_hashes))
        object.__setattr__(self, "canonical_source_name", _require_str(self.canonical_source_name, "canonical_source_name"))
        object.__setattr__(self, "canonical_source_provider_id", _require_str(self.canonical_source_provider_id, "canonical_source_provider_id"))
        object.__setattr__(self, "canonical_market_type", _require_str(self.canonical_market_type, "canonical_market_type").lower())
        object.__setattr__(self, "canonical_symbol", _require_str(self.canonical_symbol, "canonical_symbol").upper())
        object.__setattr__(self, "candidate_source_name", _require_str(self.candidate_source_name, "candidate_source_name"))
        object.__setattr__(self, "candidate_provider_id", _require_str(self.candidate_provider_id, "candidate_provider_id"))
        object.__setattr__(self, "candidate_market_type", _require_str(self.candidate_market_type, "candidate_market_type").lower())
        object.__setattr__(self, "candidate_symbol", _require_str(self.candidate_symbol, "candidate_symbol").upper())
        object.__setattr__(self, "candidate_external_symbol", _require_str(self.candidate_external_symbol, "candidate_external_symbol").upper())
        object.__setattr__(self, "candidate_provider_exchange", _require_str(self.candidate_provider_exchange, "candidate_provider_exchange").lower())
        object.__setattr__(self, "candidate_provider_version", _require_str(self.candidate_provider_version, "candidate_provider_version"))
        object.__setattr__(self, "candidate_access_type", _require_str(self.candidate_access_type, "candidate_access_type"))
        object.__setattr__(self, "candidate_time_semantics", _require_str(self.candidate_time_semantics, "candidate_time_semantics").lower())
        object.__setattr__(self, "candidate_endpoint_url", _require_str(self.candidate_endpoint_url, "candidate_endpoint_url"))
        object.__setattr__(self, "candidate_endpoint_path", _require_str(self.candidate_endpoint_path, "candidate_endpoint_path"))
        object.__setattr__(self, "candidate_documentation_url", _require_str(self.candidate_documentation_url, "candidate_documentation_url"))
        object.__setattr__(self, "candidate_close_time_rule", _require_str(self.candidate_close_time_rule, "candidate_close_time_rule"))
        object.__setattr__(self, "audited_interval_name", _require_str(self.audited_interval_name, "audited_interval_name"))
        object.__setattr__(self, "audited_period_start_utc", _require_utc_datetime(self.audited_period_start_utc, "audited_period_start_utc"))
        object.__setattr__(self, "audited_period_end_exclusive_utc", _require_utc_datetime(self.audited_period_end_exclusive_utc, "audited_period_end_exclusive_utc"))
        object.__setattr__(self, "first_candle_open_utc", _require_utc_datetime(self.first_candle_open_utc, "first_candle_open_utc"))
        object.__setattr__(self, "last_candle_open_utc", _require_utc_datetime(self.last_candle_open_utc, "last_candle_open_utc"))
        object.__setattr__(self, "expected_candle_count", _require_int(self.expected_candle_count, "expected_candle_count"))
        object.__setattr__(self, "found_candle_count", _require_int(self.found_candle_count, "found_candle_count"))
        object.__setattr__(self, "pages_observed", _require_int(self.pages_observed, "pages_observed"))
        object.__setattr__(self, "limit_used", _require_int(self.limit_used, "limit_used"))
        object.__setattr__(self, "cursor_name", _require_str(self.cursor_name, "cursor_name"))
        object.__setattr__(self, "cursor_exclusive", _require_bool(self.cursor_exclusive, "cursor_exclusive"))
        object.__setattr__(self, "collect_direction", _require_str(self.collect_direction, "collect_direction"))
        object.__setattr__(self, "confirm_value", _require_int(self.confirm_value, "confirm_value"))
        object.__setattr__(self, "all_confirm_closed", _require_bool(self.all_confirm_closed, "all_confirm_closed"))
        object.__setattr__(self, "utc_time_semantics", _require_str(self.utc_time_semantics, "utc_time_semantics").lower())
        object.__setattr__(self, "utc_alignment_valid", _require_bool(self.utc_alignment_valid, "utc_alignment_valid"))
        object.__setattr__(self, "duplicate_count", _require_int(self.duplicate_count, "duplicate_count", allow_zero=True))
        object.__setattr__(self, "gap_count", _require_int(self.gap_count, "gap_count", allow_zero=True))
        object.__setattr__(self, "overlap_count", _require_int(self.overlap_count, "overlap_count", allow_zero=True))
        object.__setattr__(self, "cursor_no_progress_count", _require_int(self.cursor_no_progress_count, "cursor_no_progress_count", allow_zero=True))
        object.__setattr__(self, "http_error_count", _require_int(self.http_error_count, "http_error_count", allow_zero=True))
        object.__setattr__(self, "timeout_count", _require_int(self.timeout_count, "timeout_count", allow_zero=True))
        object.__setattr__(self, "incomplete_candle_count", _require_int(self.incomplete_candle_count, "incomplete_candle_count", allow_zero=True))
        object.__setattr__(self, "year_count", _require_int(self.year_count, "year_count"))
        object.__setattr__(self, "annual_result_count", _require_int(self.annual_result_count, "annual_result_count"))
        object.__setattr__(self, "interval_count", _require_int(self.interval_count, "interval_count"))
        object.__setattr__(self, "provider_qualification_count", _require_int(self.provider_qualification_count, "provider_qualification_count"))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "protocol_name", _require_str(self.protocol_name, "protocol_name"))
        object.__setattr__(self, "protocol_version", _require_str(self.protocol_version, "protocol_version"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "integral_source_qualification_status", _require_str(self.integral_source_qualification_status, "integral_source_qualification_status"))
        object.__setattr__(self, "scope", _require_str(self.scope, "scope"))
        object.__setattr__(self, "coverage_scope_statement", _require_str(self.coverage_scope_statement, "coverage_scope_statement"))
        object.__setattr__(self, "non_ingestion_scope_statement", _require_str(self.non_ingestion_scope_statement, "non_ingestion_scope_statement"))
        object.__setattr__(self, "pagination_behavior_statement", _require_str(self.pagination_behavior_statement, "pagination_behavior_statement"))
        if not isinstance(self.risk_notes, tuple):
            object.__setattr__(self, "risk_notes", tuple(self.risk_notes))
        object.__setattr__(self, "risk_notes", tuple(_require_str(item, "risk_note") for item in self.risk_notes))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "integral source qualification schema_version must be 1."
            )
        if self.protocol_name != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PROTOCOL_NAME:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "protocol_name diverges from the trusted integral source qualification contract."
            )
        if self.protocol_version != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PROTOCOL_VERSION:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "protocol_version diverges from the trusted integral source qualification contract."
            )
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        if self.canonical_source_name != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_SOURCE_NAME:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "canonical_source_name diverges from the trusted source chain."
            )
        if self.canonical_source_provider_id != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "canonical_source_provider_id diverges from the trusted source chain."
            )
        if self.canonical_market_type != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_MARKET_TYPE:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "canonical_market_type must remain spot."
            )
        if self.canonical_symbol != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_SYMBOL:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "canonical_symbol must remain BTCUSDT."
            )
        if self.candidate_source_name != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_NAME:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "candidate_source_name diverges from the audited candidate."
            )
        if self.candidate_provider_id != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_ID:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "candidate_provider_id diverges from the audited candidate."
            )
        if self.candidate_market_type != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_MARKET_TYPE:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "candidate_market_type must remain spot."
            )
        if self.candidate_symbol != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_SYMBOL:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "candidate_symbol must remain BTCUSDT."
            )
        if self.candidate_external_symbol != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "candidate_external_symbol must remain BTC-USDT."
            )
        if self.candidate_provider_exchange != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "candidate_provider_exchange must remain OKX."
            )
        if self.candidate_provider_version != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_VERSION:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "candidate_provider_version must remain v1."
            )
        if self.candidate_access_type != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_ACCESS_TYPE:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "candidate_access_type must remain public_no_auth."
            )
        if self.candidate_time_semantics != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_TIME_SEMANTICS:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "candidate_time_semantics must remain utc."
            )
        if self.candidate_endpoint_url != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_ENDPOINT_URL:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "candidate_endpoint_url diverges from the audited candidate."
            )
        if self.candidate_endpoint_path != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_ENDPOINT_PATH:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "candidate_endpoint_path diverges from the audited candidate."
            )
        if self.candidate_documentation_url != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "candidate_documentation_url diverges from the audited candidate."
            )
        if self.candidate_close_time_rule != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "candidate_close_time_rule diverges from the audited candidate."
            )
        if self.audited_interval_name != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_AUDITED_INTERVAL_NAME:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "audited_interval_name must remain 1H."
            )
        if self.audited_period_start_utc != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_AUDIT_START_UTC:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "audited_period_start_utc diverges from the audited period."
            )
        if self.audited_period_end_exclusive_utc != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_AUDIT_END_EXCLUSIVE_UTC:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "audited_period_end_exclusive_utc diverges from the audited period."
            )
        if self.first_candle_open_utc != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_FIRST_CANDLE_OPEN_UTC:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "first_candle_open_utc diverges from the audited period."
            )
        if self.last_candle_open_utc != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_LAST_CANDLE_OPEN_UTC:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "last_candle_open_utc diverges from the audited period."
            )
        if self.expected_candle_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_EXPECTED_CANDLE_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "expected_candle_count diverges from the audited period."
            )
        if self.found_candle_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_EXPECTED_CANDLE_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "found_candle_count diverges from the audited period."
            )
        if self.pages_observed != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PAGES_OBSERVED:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "pages_observed diverges from the audited period."
            )
        if self.limit_used != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_LIMIT_USED:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "limit_used diverges from the audited period."
            )
        if self.cursor_name != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CURSOR_NAME:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "cursor_name must remain after."
            )
        if self.cursor_exclusive is not HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CURSOR_EXCLUSIVE:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "cursor_exclusive diverges from the audited period."
            )
        if self.collect_direction != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_COLLECTION_DIRECTION:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "collect_direction must remain reverse_chronological."
            )
        if self.confirm_value != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CONFIRM_VALUE:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "confirm_value diverges from the audited period."
            )
        if self.all_confirm_closed is not True:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "all_confirm_closed must remain true."
            )
        if self.utc_time_semantics != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_UTC_TIME_SEMANTICS:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "utc_time_semantics must remain utc."
            )
        if self.utc_alignment_valid is not True:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "utc_alignment_valid must remain true."
            )
        if self.duplicate_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_DUPLICATE_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "duplicate_count diverges from the audited period."
            )
        if self.gap_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_GAP_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "gap_count diverges from the audited period."
            )
        if self.overlap_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_OVERLAP_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "overlap_count diverges from the audited period."
            )
        if self.cursor_no_progress_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CURSOR_NO_PROGRESS_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "cursor_no_progress_count diverges from the audited period."
            )
        if self.http_error_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_HTTP_ERROR_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "http_error_count diverges from the audited period."
            )
        if self.timeout_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_TIMEOUT_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "timeout_count diverges from the audited period."
            )
        if self.incomplete_candle_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_INCOMPLETE_CANDLE_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "incomplete_candle_count diverges from the audited period."
            )
        if self.year_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_YEAR_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "year_count must remain five."
            )
        if self.annual_result_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_ANNUAL_RESULT_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "annual_result_count must remain five."
            )
        if self.interval_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_INTERVAL_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "interval_count must remain one."
            )
        if self.provider_qualification_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PROVIDER_QUALIFICATION_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "provider_qualification_count must remain one."
            )
        if self.integral_source_qualification_status != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "integral_source_qualification_status diverges from the audited conclusion."
            )
        if self.scope != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCOPE:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("scope diverges from the audited conclusion.")
        if self.coverage_scope_statement != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_COVERAGE_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "coverage_scope_statement diverges from the audited conclusion."
            )
        if self.non_ingestion_scope_statement != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "non_ingestion_scope_statement diverges from the audited conclusion."
            )
        if self.pagination_behavior_statement != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "pagination_behavior_statement diverges from the audited conclusion."
            )
        if self.risk_notes != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_RISK_NOTES:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "risk_notes diverge from the audited conclusion."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.protocol_hash:
            if self.protocol_hash != _require_hash(self.protocol_hash, "protocol_hash"):
                raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("protocol hash mismatch.")
            if self.protocol_hash != expected:
                raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("protocol hash mismatch.")
        else:
            object.__setattr__(self, "protocol_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "protocol_name": self.protocol_name,
            "protocol_version": self.protocol_version,
            "provider_qualification_hash": self.provider_qualification_hash,
            "annual_result_hashes": list(self.annual_result_hashes),
            "canonical_source_name": self.canonical_source_name,
            "canonical_source_provider_id": self.canonical_source_provider_id,
            "canonical_market_type": self.canonical_market_type,
            "canonical_symbol": self.canonical_symbol,
            "candidate_source_name": self.candidate_source_name,
            "candidate_provider_id": self.candidate_provider_id,
            "candidate_market_type": self.candidate_market_type,
            "candidate_symbol": self.candidate_symbol,
            "candidate_external_symbol": self.candidate_external_symbol,
            "candidate_provider_exchange": self.candidate_provider_exchange,
            "candidate_provider_version": self.candidate_provider_version,
            "candidate_access_type": self.candidate_access_type,
            "candidate_time_semantics": self.candidate_time_semantics,
            "candidate_endpoint_url": self.candidate_endpoint_url,
            "candidate_endpoint_path": self.candidate_endpoint_path,
            "candidate_documentation_url": self.candidate_documentation_url,
            "candidate_close_time_rule": self.candidate_close_time_rule,
            "audited_interval_name": self.audited_interval_name,
            "audited_period_start_utc": _utc_iso(self.audited_period_start_utc),
            "audited_period_end_exclusive_utc": _utc_iso(self.audited_period_end_exclusive_utc),
            "first_candle_open_utc": _utc_iso(self.first_candle_open_utc),
            "last_candle_open_utc": _utc_iso(self.last_candle_open_utc),
            "expected_candle_count": self.expected_candle_count,
            "found_candle_count": self.found_candle_count,
            "pages_observed": self.pages_observed,
            "limit_used": self.limit_used,
            "cursor_name": self.cursor_name,
            "cursor_exclusive": self.cursor_exclusive,
            "collect_direction": self.collect_direction,
            "confirm_value": self.confirm_value,
            "all_confirm_closed": self.all_confirm_closed,
            "utc_time_semantics": self.utc_time_semantics,
            "utc_alignment_valid": self.utc_alignment_valid,
            "duplicate_count": self.duplicate_count,
            "gap_count": self.gap_count,
            "overlap_count": self.overlap_count,
            "cursor_no_progress_count": self.cursor_no_progress_count,
            "http_error_count": self.http_error_count,
            "timeout_count": self.timeout_count,
            "incomplete_candle_count": self.incomplete_candle_count,
            "year_count": self.year_count,
            "annual_result_count": self.annual_result_count,
            "interval_count": self.interval_count,
            "provider_qualification_count": self.provider_qualification_count,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "integral_source_qualification_status": self.integral_source_qualification_status,
            "scope": self.scope,
            "coverage_scope_statement": self.coverage_scope_statement,
            "non_ingestion_scope_statement": self.non_ingestion_scope_statement,
            "pagination_behavior_statement": self.pagination_behavior_statement,
            "risk_notes": list(self.risk_notes),
        }
        if include_hash:
            payload["protocol_hash"] = self.protocol_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketIntegralSourceQualificationProtocol":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "integral source qualification protocol must be a mapping."
            )
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "protocol_name",
                "protocol_version",
                "provider_qualification_hash",
                "annual_result_hashes",
                "canonical_source_name",
                "canonical_source_provider_id",
                "canonical_market_type",
                "canonical_symbol",
                "candidate_source_name",
                "candidate_provider_id",
                "candidate_market_type",
                "candidate_symbol",
                "candidate_external_symbol",
                "candidate_provider_exchange",
                "candidate_provider_version",
                "candidate_access_type",
                "candidate_time_semantics",
                "candidate_endpoint_url",
                "candidate_endpoint_path",
                "candidate_documentation_url",
                "candidate_close_time_rule",
                "audited_interval_name",
                "audited_period_start_utc",
                "audited_period_end_exclusive_utc",
                "first_candle_open_utc",
                "last_candle_open_utc",
                "expected_candle_count",
                "found_candle_count",
                "pages_observed",
                "limit_used",
                "cursor_name",
                "cursor_exclusive",
                "collect_direction",
                "confirm_value",
                "all_confirm_closed",
                "utc_time_semantics",
                "utc_alignment_valid",
                "duplicate_count",
                "gap_count",
                "overlap_count",
                "cursor_no_progress_count",
                "http_error_count",
                "timeout_count",
                "incomplete_candle_count",
                "year_count",
                "annual_result_count",
                "interval_count",
                "provider_qualification_count",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "integral_source_qualification_status",
                "scope",
                "coverage_scope_statement",
                "non_ingestion_scope_statement",
                "pagination_behavior_statement",
                "risk_notes",
                "protocol_hash",
            },
            name="integral source qualification protocol",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                protocol_name=mapping["protocol_name"],
                protocol_version=mapping["protocol_version"],
                provider_qualification_hash=mapping["provider_qualification_hash"],
                annual_result_hashes=tuple(mapping["annual_result_hashes"]),
                canonical_source_name=mapping["canonical_source_name"],
                canonical_source_provider_id=mapping["canonical_source_provider_id"],
                canonical_market_type=mapping["canonical_market_type"],
                canonical_symbol=mapping["canonical_symbol"],
                candidate_source_name=mapping["candidate_source_name"],
                candidate_provider_id=mapping["candidate_provider_id"],
                candidate_market_type=mapping["candidate_market_type"],
                candidate_symbol=mapping["candidate_symbol"],
                candidate_external_symbol=mapping["candidate_external_symbol"],
                candidate_provider_exchange=mapping["candidate_provider_exchange"],
                candidate_provider_version=mapping["candidate_provider_version"],
                candidate_access_type=mapping["candidate_access_type"],
                candidate_time_semantics=mapping["candidate_time_semantics"],
                candidate_endpoint_url=mapping["candidate_endpoint_url"],
                candidate_endpoint_path=mapping["candidate_endpoint_path"],
                candidate_documentation_url=mapping["candidate_documentation_url"],
                candidate_close_time_rule=mapping["candidate_close_time_rule"],
                audited_interval_name=mapping["audited_interval_name"],
                audited_period_start_utc=mapping["audited_period_start_utc"],
                audited_period_end_exclusive_utc=mapping["audited_period_end_exclusive_utc"],
                first_candle_open_utc=mapping["first_candle_open_utc"],
                last_candle_open_utc=mapping["last_candle_open_utc"],
                expected_candle_count=mapping["expected_candle_count"],
                found_candle_count=mapping["found_candle_count"],
                pages_observed=mapping["pages_observed"],
                limit_used=mapping["limit_used"],
                cursor_name=mapping["cursor_name"],
                cursor_exclusive=mapping["cursor_exclusive"],
                collect_direction=mapping["collect_direction"],
                confirm_value=mapping["confirm_value"],
                all_confirm_closed=mapping["all_confirm_closed"],
                utc_time_semantics=mapping["utc_time_semantics"],
                utc_alignment_valid=mapping["utc_alignment_valid"],
                duplicate_count=mapping["duplicate_count"],
                gap_count=mapping["gap_count"],
                overlap_count=mapping["overlap_count"],
                cursor_no_progress_count=mapping["cursor_no_progress_count"],
                http_error_count=mapping["http_error_count"],
                timeout_count=mapping["timeout_count"],
                incomplete_candle_count=mapping["incomplete_candle_count"],
                year_count=mapping["year_count"],
                annual_result_count=mapping["annual_result_count"],
                interval_count=mapping["interval_count"],
                provider_qualification_count=mapping["provider_qualification_count"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                integral_source_qualification_status=mapping.get(
                    "integral_source_qualification_status",
                    HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS,
                ),
                scope=mapping.get("scope", HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCOPE),
                coverage_scope_statement=mapping.get(
                    "coverage_scope_statement",
                    HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_COVERAGE_SCOPE_STATEMENT,
                ),
                non_ingestion_scope_statement=mapping.get(
                    "non_ingestion_scope_statement",
                    HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT,
                ),
                pagination_behavior_statement=mapping.get(
                    "pagination_behavior_statement",
                    HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT,
                ),
                risk_notes=tuple(
                    mapping.get("risk_notes", HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_RISK_NOTES)
                ),
                protocol_hash=mapping.get("protocol_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "integral source qualification protocol is incomplete."
            ) from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketIntegralSourceQualificationSummary:
    year_count: int
    annual_result_count: int
    pass_year_count: int
    interval_count: int
    provider_qualification_count: int
    pages_observed: int
    expected_candle_count: int
    found_candle_count: int
    duplicate_count: int
    gap_count: int
    overlap_count: int
    cursor_no_progress_count: int
    http_error_count: int
    timeout_count: int
    incomplete_candle_count: int
    all_confirm_closed: bool
    utc_alignment_valid: bool
    integral_source_qualification_status: str
    coverage_scope_statement: str
    non_ingestion_scope_statement: str
    pagination_behavior_statement: str
    risk_notes: tuple[str, ...]
    schema_version: int = HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCHEMA_VERSION
    summary_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "year_count", _require_int(self.year_count, "year_count"))
        object.__setattr__(self, "annual_result_count", _require_int(self.annual_result_count, "annual_result_count"))
        object.__setattr__(self, "pass_year_count", _require_int(self.pass_year_count, "pass_year_count"))
        object.__setattr__(self, "interval_count", _require_int(self.interval_count, "interval_count"))
        object.__setattr__(self, "provider_qualification_count", _require_int(self.provider_qualification_count, "provider_qualification_count"))
        object.__setattr__(self, "pages_observed", _require_int(self.pages_observed, "pages_observed"))
        object.__setattr__(self, "expected_candle_count", _require_int(self.expected_candle_count, "expected_candle_count"))
        object.__setattr__(self, "found_candle_count", _require_int(self.found_candle_count, "found_candle_count"))
        object.__setattr__(self, "duplicate_count", _require_int(self.duplicate_count, "duplicate_count", allow_zero=True))
        object.__setattr__(self, "gap_count", _require_int(self.gap_count, "gap_count", allow_zero=True))
        object.__setattr__(self, "overlap_count", _require_int(self.overlap_count, "overlap_count", allow_zero=True))
        object.__setattr__(self, "cursor_no_progress_count", _require_int(self.cursor_no_progress_count, "cursor_no_progress_count", allow_zero=True))
        object.__setattr__(self, "http_error_count", _require_int(self.http_error_count, "http_error_count", allow_zero=True))
        object.__setattr__(self, "timeout_count", _require_int(self.timeout_count, "timeout_count", allow_zero=True))
        object.__setattr__(self, "incomplete_candle_count", _require_int(self.incomplete_candle_count, "incomplete_candle_count", allow_zero=True))
        object.__setattr__(self, "all_confirm_closed", _require_bool(self.all_confirm_closed, "all_confirm_closed"))
        object.__setattr__(self, "utc_alignment_valid", _require_bool(self.utc_alignment_valid, "utc_alignment_valid"))
        object.__setattr__(self, "integral_source_qualification_status", _require_str(
            self.integral_source_qualification_status,
            "integral_source_qualification_status",
        ))
        object.__setattr__(self, "coverage_scope_statement", _require_str(self.coverage_scope_statement, "coverage_scope_statement"))
        object.__setattr__(self, "non_ingestion_scope_statement", _require_str(self.non_ingestion_scope_statement, "non_ingestion_scope_statement"))
        object.__setattr__(self, "pagination_behavior_statement", _require_str(self.pagination_behavior_statement, "pagination_behavior_statement"))
        if not isinstance(self.risk_notes, tuple):
            object.__setattr__(self, "risk_notes", tuple(self.risk_notes))
        object.__setattr__(self, "risk_notes", tuple(_require_str(item, "risk_note") for item in self.risk_notes))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "integral source qualification summary schema_version must be 1."
            )
        if self.year_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_YEAR_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("year_count must remain five.")
        if self.annual_result_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_ANNUAL_RESULT_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("annual_result_count must remain five.")
        if self.pass_year_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_YEAR_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("pass_year_count must remain five.")
        if self.interval_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_INTERVAL_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("interval_count must remain one.")
        if self.provider_qualification_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PROVIDER_QUALIFICATION_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "provider_qualification_count must remain one."
            )
        if self.pages_observed != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PAGES_OBSERVED:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("pages_observed diverges from the audited period.")
        if self.expected_candle_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_EXPECTED_CANDLE_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "expected_candle_count diverges from the audited period."
            )
        if self.found_candle_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_EXPECTED_CANDLE_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "found_candle_count diverges from the audited period."
            )
        if self.duplicate_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_DUPLICATE_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("duplicate_count diverges from the audited period.")
        if self.gap_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_GAP_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("gap_count diverges from the audited period.")
        if self.overlap_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_OVERLAP_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("overlap_count diverges from the audited period.")
        if self.cursor_no_progress_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CURSOR_NO_PROGRESS_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "cursor_no_progress_count diverges from the audited period."
            )
        if self.http_error_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_HTTP_ERROR_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("http_error_count diverges from the audited period.")
        if self.timeout_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_TIMEOUT_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("timeout_count diverges from the audited period.")
        if self.incomplete_candle_count != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_INCOMPLETE_CANDLE_COUNT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "incomplete_candle_count diverges from the audited period."
            )
        if self.all_confirm_closed is not True:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("all_confirm_closed must remain true.")
        if self.utc_alignment_valid is not True:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("utc_alignment_valid must remain true.")
        if self.integral_source_qualification_status != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "integral_source_qualification_status diverges from the audited conclusion."
            )
        if self.coverage_scope_statement != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_COVERAGE_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "coverage_scope_statement diverges from the audited conclusion."
            )
        if self.non_ingestion_scope_statement != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "non_ingestion_scope_statement diverges from the audited conclusion."
            )
        if self.pagination_behavior_statement != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "pagination_behavior_statement diverges from the audited conclusion."
            )
        if self.risk_notes != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_RISK_NOTES:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "risk_notes diverge from the audited conclusion."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.summary_hash:
            if self.summary_hash != _require_hash(self.summary_hash, "summary_hash"):
                raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("summary hash mismatch.")
            if self.summary_hash != expected:
                raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("summary hash mismatch.")
        else:
            object.__setattr__(self, "summary_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "year_count": self.year_count,
            "annual_result_count": self.annual_result_count,
            "pass_year_count": self.pass_year_count,
            "interval_count": self.interval_count,
            "provider_qualification_count": self.provider_qualification_count,
            "pages_observed": self.pages_observed,
            "expected_candle_count": self.expected_candle_count,
            "found_candle_count": self.found_candle_count,
            "duplicate_count": self.duplicate_count,
            "gap_count": self.gap_count,
            "overlap_count": self.overlap_count,
            "cursor_no_progress_count": self.cursor_no_progress_count,
            "http_error_count": self.http_error_count,
            "timeout_count": self.timeout_count,
            "incomplete_candle_count": self.incomplete_candle_count,
            "all_confirm_closed": self.all_confirm_closed,
            "utc_alignment_valid": self.utc_alignment_valid,
            "integral_source_qualification_status": self.integral_source_qualification_status,
            "coverage_scope_statement": self.coverage_scope_statement,
            "non_ingestion_scope_statement": self.non_ingestion_scope_statement,
            "pagination_behavior_statement": self.pagination_behavior_statement,
            "risk_notes": list(self.risk_notes),
        }
        if include_hash:
            payload["summary_hash"] = self.summary_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketIntegralSourceQualificationSummary":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "integral source qualification summary must be a mapping."
            )
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "year_count",
                "annual_result_count",
                "pass_year_count",
                "interval_count",
                "provider_qualification_count",
                "pages_observed",
                "expected_candle_count",
                "found_candle_count",
                "duplicate_count",
                "gap_count",
                "overlap_count",
                "cursor_no_progress_count",
                "http_error_count",
                "timeout_count",
                "incomplete_candle_count",
                "all_confirm_closed",
                "utc_alignment_valid",
                "integral_source_qualification_status",
                "coverage_scope_statement",
                "non_ingestion_scope_statement",
                "pagination_behavior_statement",
                "risk_notes",
                "summary_hash",
            },
            name="integral source qualification summary",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                year_count=mapping["year_count"],
                annual_result_count=mapping["annual_result_count"],
                pass_year_count=mapping["pass_year_count"],
                interval_count=mapping["interval_count"],
                provider_qualification_count=mapping["provider_qualification_count"],
                pages_observed=mapping["pages_observed"],
                expected_candle_count=mapping["expected_candle_count"],
                found_candle_count=mapping["found_candle_count"],
                duplicate_count=mapping["duplicate_count"],
                gap_count=mapping["gap_count"],
                overlap_count=mapping["overlap_count"],
                cursor_no_progress_count=mapping["cursor_no_progress_count"],
                http_error_count=mapping["http_error_count"],
                timeout_count=mapping["timeout_count"],
                incomplete_candle_count=mapping["incomplete_candle_count"],
                all_confirm_closed=mapping["all_confirm_closed"],
                utc_alignment_valid=mapping["utc_alignment_valid"],
                integral_source_qualification_status=mapping.get(
                    "integral_source_qualification_status",
                    HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS,
                ),
                coverage_scope_statement=mapping.get(
                    "coverage_scope_statement",
                    HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_COVERAGE_SCOPE_STATEMENT,
                ),
                non_ingestion_scope_statement=mapping.get(
                    "non_ingestion_scope_statement",
                    HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT,
                ),
                pagination_behavior_statement=mapping.get(
                    "pagination_behavior_statement",
                    HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT,
                ),
                risk_notes=tuple(
                    mapping.get("risk_notes", HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_RISK_NOTES)
                ),
                summary_hash=mapping.get("summary_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "integral source qualification summary is incomplete."
            ) from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketIntegralSourceQualificationReport:
    provider_qualification: HistoricalProviderQualification
    annual_results: tuple[HistoricalFuturesMarketIntegralSourceQualificationAnnualResult, ...]
    protocol: HistoricalFuturesMarketIntegralSourceQualificationProtocol
    summary: HistoricalFuturesMarketIntegralSourceQualificationSummary
    schema_version: int = HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    report_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.provider_qualification, HistoricalProviderQualification):
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "provider_qualification must be a HistoricalProviderQualification instance."
            )
        if not isinstance(self.annual_results, tuple):
            object.__setattr__(self, "annual_results", tuple(self.annual_results))
        if not isinstance(self.protocol, HistoricalFuturesMarketIntegralSourceQualificationProtocol):
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "protocol must be an integral source qualification protocol instance."
            )
        if not isinstance(self.summary, HistoricalFuturesMarketIntegralSourceQualificationSummary):
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "summary must be an integral source qualification summary instance."
            )
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "integral source qualification report schema_version must be 1."
            )
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        expected_provider = _expected_provider_qualification()
        if self.provider_qualification != expected_provider:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "provider_qualification diverges from the audited candidate."
            )
        if self.provider_qualification.interval != HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_AUDITED_INTERVAL_NAME:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "provider_qualification interval must remain 1H."
            )
        expected_annual_results = _expected_annual_results()
        if self.annual_results != expected_annual_results:
            raise HistoricalFuturesMarketIntegralSourceQualificationIntegrityError(
                "annual_results diverge from the audited evidence."
            )
        expected_protocol = _build_protocol(self.provider_qualification, self.annual_results)
        if self.protocol != expected_protocol:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "protocol diverges from the audited evidence."
            )
        expected_summary = _build_summary(self.provider_qualification, self.annual_results)
        if self.summary != expected_summary:
            raise HistoricalFuturesMarketIntegralSourceQualificationIntegrityError(
                "summary diverges from the audited evidence."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.report_hash:
            if self.report_hash != _require_hash(self.report_hash, "report_hash"):
                raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("report hash mismatch.")
            if self.report_hash != expected:
                raise HistoricalFuturesMarketIntegralSourceQualificationValidationError("report hash mismatch.")
        else:
            object.__setattr__(self, "report_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "provider_qualification": self.provider_qualification.as_dict(),
            "annual_results": [item.as_dict() for item in self.annual_results],
            "protocol": self.protocol.as_hash_payload(include_hash=False),
            "summary": self.summary.as_hash_payload(include_hash=False),
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketIntegralSourceQualificationReport":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "integral source qualification report must be a mapping."
            )
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "provider_qualification",
                "annual_results",
                "protocol",
                "summary",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "report_hash",
            },
            name="integral source qualification report",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                provider_qualification=HistoricalProviderQualification.from_dict(mapping["provider_qualification"]),
                annual_results=tuple(
                    HistoricalFuturesMarketIntegralSourceQualificationAnnualResult.from_dict(item)
                    for item in mapping["annual_results"]
                ),
                protocol=HistoricalFuturesMarketIntegralSourceQualificationProtocol.from_dict(mapping["protocol"]),
                summary=HistoricalFuturesMarketIntegralSourceQualificationSummary.from_dict(mapping["summary"]),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                report_hash=mapping.get("report_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
                "integral source qualification report is incomplete."
            ) from exc
        except (
            HistoricalFuturesMarketIntegralSourceQualificationValidationError,
            HistoricalFuturesMarketIntegralSourceQualificationIntegrityError,
            HistoricalFuturesMarketIntegralSourceQualificationError,
            TypeError,
            ValueError,
        ) as exc:
            raise HistoricalFuturesMarketIntegralSourceQualificationIntegrityError(str(exc)) from exc


def _build_annual_results() -> tuple[HistoricalFuturesMarketIntegralSourceQualificationAnnualResult, ...]:
    return tuple(
        HistoricalFuturesMarketIntegralSourceQualificationAnnualResult(
            year=year,
            first_timestamp_utc=spec["first_timestamp_utc"],
            last_timestamp_utc=spec["last_timestamp_utc"],
            expected_candle_count=spec["expected_candle_count"],
            found_candle_count=spec["found_candle_count"],
            duplicate_count=spec["duplicate_count"],
            gap_count=spec["gap_count"],
            result=spec["result"],
        )
        for year, spec in _ANNUAL_SPECS.items()
    )


def _build_protocol(
    provider_qualification: HistoricalProviderQualification,
    annual_results: Sequence[HistoricalFuturesMarketIntegralSourceQualificationAnnualResult],
) -> HistoricalFuturesMarketIntegralSourceQualificationProtocol:
    annual_result_hashes = tuple(item.annual_result_hash for item in annual_results)
    return HistoricalFuturesMarketIntegralSourceQualificationProtocol(
        provider_qualification_hash=provider_qualification.qualification_hash,
        annual_result_hashes=annual_result_hashes,
        canonical_source_name=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_SOURCE_NAME,
        canonical_source_provider_id=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID,
        canonical_market_type=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_MARKET_TYPE,
        canonical_symbol=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_SYMBOL,
        candidate_source_name=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_NAME,
        candidate_provider_id=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_ID,
        candidate_market_type=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_MARKET_TYPE,
        candidate_symbol=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_SYMBOL,
        candidate_external_symbol=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL,
        candidate_provider_exchange=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE,
        candidate_provider_version=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_VERSION,
        candidate_access_type=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_ACCESS_TYPE,
        candidate_time_semantics=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_TIME_SEMANTICS,
        candidate_endpoint_url=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_ENDPOINT_URL,
        candidate_endpoint_path=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_ENDPOINT_PATH,
        candidate_documentation_url=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL,
        candidate_close_time_rule=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE,
        audited_interval_name=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_AUDITED_INTERVAL_NAME,
        audited_period_start_utc=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_AUDIT_START_UTC,
        audited_period_end_exclusive_utc=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_AUDIT_END_EXCLUSIVE_UTC,
        first_candle_open_utc=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_FIRST_CANDLE_OPEN_UTC,
        last_candle_open_utc=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_LAST_CANDLE_OPEN_UTC,
        expected_candle_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_EXPECTED_CANDLE_COUNT,
        found_candle_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_EXPECTED_CANDLE_COUNT,
        pages_observed=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PAGES_OBSERVED,
        limit_used=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_LIMIT_USED,
        cursor_name=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CURSOR_NAME,
        cursor_exclusive=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CURSOR_EXCLUSIVE,
        collect_direction=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_COLLECTION_DIRECTION,
        confirm_value=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CONFIRM_VALUE,
        all_confirm_closed=True,
        utc_time_semantics=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_UTC_TIME_SEMANTICS,
        utc_alignment_valid=True,
        duplicate_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_DUPLICATE_COUNT,
        gap_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_GAP_COUNT,
        overlap_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_OVERLAP_COUNT,
        cursor_no_progress_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CURSOR_NO_PROGRESS_COUNT,
        http_error_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_HTTP_ERROR_COUNT,
        timeout_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_TIMEOUT_COUNT,
        incomplete_candle_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_INCOMPLETE_CANDLE_COUNT,
        year_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_YEAR_COUNT,
        annual_result_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_ANNUAL_RESULT_COUNT,
        interval_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_INTERVAL_COUNT,
        provider_qualification_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PROVIDER_QUALIFICATION_COUNT,
    )


def _build_summary(
    provider_qualification: HistoricalProviderQualification,
    annual_results: Sequence[HistoricalFuturesMarketIntegralSourceQualificationAnnualResult],
) -> HistoricalFuturesMarketIntegralSourceQualificationSummary:
    _ = provider_qualification
    return HistoricalFuturesMarketIntegralSourceQualificationSummary(
        year_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_YEAR_COUNT,
        annual_result_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_ANNUAL_RESULT_COUNT,
        pass_year_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_YEAR_COUNT,
        interval_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_INTERVAL_COUNT,
        provider_qualification_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PROVIDER_QUALIFICATION_COUNT,
        pages_observed=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PAGES_OBSERVED,
        expected_candle_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_EXPECTED_CANDLE_COUNT,
        found_candle_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_EXPECTED_CANDLE_COUNT,
        duplicate_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_DUPLICATE_COUNT,
        gap_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_GAP_COUNT,
        overlap_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_OVERLAP_COUNT,
        cursor_no_progress_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CURSOR_NO_PROGRESS_COUNT,
        http_error_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_HTTP_ERROR_COUNT,
        timeout_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_TIMEOUT_COUNT,
        incomplete_candle_count=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_INCOMPLETE_CANDLE_COUNT,
        all_confirm_closed=True,
        utc_alignment_valid=True,
        integral_source_qualification_status=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS,
        coverage_scope_statement=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_COVERAGE_SCOPE_STATEMENT,
        non_ingestion_scope_statement=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT,
        pagination_behavior_statement=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT,
        risk_notes=HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_RISK_NOTES,
    )


def build_historical_futures_market_integral_source_qualification_protocol() -> HistoricalFuturesMarketIntegralSourceQualificationProtocol:
    provider_qualification = _expected_provider_qualification()
    annual_results = _expected_annual_results()
    return _build_protocol(provider_qualification, annual_results)


def build_historical_futures_market_integral_source_qualification_report(
    _: Any | None = None,
) -> HistoricalFuturesMarketIntegralSourceQualificationReport:
    provider_qualification = _expected_provider_qualification()
    annual_results = _expected_annual_results()
    protocol = _build_protocol(provider_qualification, annual_results)
    summary = _build_summary(provider_qualification, annual_results)
    return HistoricalFuturesMarketIntegralSourceQualificationReport(
        provider_qualification=provider_qualification,
        annual_results=annual_results,
        protocol=protocol,
        summary=summary,
    )


def run_historical_futures_market_integral_source_qualification(
    _: Any | None = None,
    *,
    output_file: str | Path | None = None,
) -> HistoricalFuturesMarketIntegralSourceQualificationReport:
    report = build_historical_futures_market_integral_source_qualification_report()
    if output_file is not None:
        save_historical_futures_market_integral_source_qualification_report(output_file, report)
    return report


def _read(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
            "integral source qualification report not found."
        ) from exc
    except Exception as exc:
        raise HistoricalFuturesMarketIntegralSourceQualificationIntegrityError(
            "integral source qualification report is invalid JSON."
        ) from exc
    if not isinstance(value, Mapping):
        raise HistoricalFuturesMarketIntegralSourceQualificationIntegrityError(
            "integral source qualification report must be a JSON object."
        )
    return value


def load_historical_futures_market_integral_source_qualification_report(
    path: str | Path,
) -> HistoricalFuturesMarketIntegralSourceQualificationReport:
    payload = _read(Path(path))
    try:
        report = HistoricalFuturesMarketIntegralSourceQualificationReport.from_dict(payload)
    except (
        KeyError,
        TypeError,
        ValueError,
        HistoricalFuturesMarketIntegralSourceQualificationValidationError,
        HistoricalFuturesMarketIntegralSourceQualificationIntegrityError,
    ) as exc:
        raise HistoricalFuturesMarketIntegralSourceQualificationIntegrityError(str(exc)) from exc
    if report.as_dict() != payload:
        raise HistoricalFuturesMarketIntegralSourceQualificationIntegrityError(
            "integral source qualification report payload mismatch."
        )
    return report


def save_historical_futures_market_integral_source_qualification_report(
    path: str | Path,
    report: HistoricalFuturesMarketIntegralSourceQualificationReport,
) -> HistoricalFuturesMarketIntegralSourceQualificationReport:
    file_path = Path(path)
    payload = report.as_dict()
    if file_path.exists():
        existing = load_historical_futures_market_integral_source_qualification_report(file_path)
        if existing.as_dict() != payload:
            raise HistoricalFuturesMarketIntegralSourceQualificationConflictError(
                "integral source qualification report already exists and differs."
            )
        return existing
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_name(f".{file_path.name}.{os.getpid()}.{id(report)}.tmp")
    try:
        tmp.write_text(_canonical_json(payload), encoding="utf-8")
        try:
            os.link(tmp, file_path)
        except FileExistsError:
            existing = load_historical_futures_market_integral_source_qualification_report(file_path)
            if existing.as_dict() != payload:
                raise HistoricalFuturesMarketIntegralSourceQualificationConflictError(
                    "integral source qualification report already exists and differs."
                )
            return existing
    except Exception as exc:
        if isinstance(exc, HistoricalFuturesMarketIntegralSourceQualificationConflictError):
            raise
        raise HistoricalFuturesMarketIntegralSourceQualificationValidationError(
            "failed to write integral source qualification report atomically."
        ) from exc
    finally:
        tmp.unlink(missing_ok=True)
    return report


def verify_historical_futures_market_integral_source_qualification_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_integral_source_qualification_report(path)
    return {
        "verified": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "summary_hash": report.summary.summary_hash,
        "provider_qualification_hash": report.provider_qualification.qualification_hash,
        "classification": HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS,
        "integral_source_qualification_status": report.summary.integral_source_qualification_status,
        "year_count": report.summary.year_count,
        "annual_result_count": report.summary.annual_result_count,
        "pages_observed": report.summary.pages_observed,
        "expected_candle_count": report.summary.expected_candle_count,
        "found_candle_count": report.summary.found_candle_count,
        "all_confirm_closed": report.summary.all_confirm_closed,
        "utc_alignment_valid": report.summary.utc_alignment_valid,
    }


def status_historical_futures_market_integral_source_qualification_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_integral_source_qualification_report(path)
    summary = report.summary
    return {
        "exists": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "summary_hash": summary.summary_hash,
        "provider_qualification_hash": report.provider_qualification.qualification_hash,
        "classification": HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS,
        "integral_source_qualification_status": summary.integral_source_qualification_status,
        "canonical_source_name": report.protocol.canonical_source_name,
        "canonical_source_provider_id": report.protocol.canonical_source_provider_id,
        "canonical_market_type": report.protocol.canonical_market_type,
        "canonical_symbol": report.protocol.canonical_symbol,
        "candidate_source_name": report.protocol.candidate_source_name,
        "candidate_provider_id": report.protocol.candidate_provider_id,
        "candidate_market_type": report.protocol.candidate_market_type,
        "candidate_symbol": report.protocol.candidate_symbol,
        "candidate_external_symbol": report.protocol.candidate_external_symbol,
        "audited_interval_name": report.protocol.audited_interval_name,
        "audited_period_start_utc": _utc_iso(report.protocol.audited_period_start_utc),
        "audited_period_end_exclusive_utc": _utc_iso(report.protocol.audited_period_end_exclusive_utc),
        "first_candle_open_utc": _utc_iso(report.protocol.first_candle_open_utc),
        "last_candle_open_utc": _utc_iso(report.protocol.last_candle_open_utc),
        "expected_candle_count": summary.expected_candle_count,
        "found_candle_count": summary.found_candle_count,
        "pages_observed": summary.pages_observed,
        "limit_used": report.protocol.limit_used,
        "duplicate_count": summary.duplicate_count,
        "gap_count": summary.gap_count,
        "overlap_count": summary.overlap_count,
        "cursor_no_progress_count": summary.cursor_no_progress_count,
        "http_error_count": summary.http_error_count,
        "timeout_count": summary.timeout_count,
        "incomplete_candle_count": summary.incomplete_candle_count,
        "year_count": summary.year_count,
        "annual_result_count": summary.annual_result_count,
        "provider_qualification_count": summary.provider_qualification_count,
        "all_confirm_closed": summary.all_confirm_closed,
        "utc_alignment_valid": summary.utc_alignment_valid,
    }


def reject_historical_futures_market_integral_source_qualification_promotion(
    _: HistoricalFuturesMarketIntegralSourceQualificationReport,
) -> None:
    raise HistoricalFuturesMarketIntegralSourceQualificationPromotionError(
        "historical futures integral source qualification is not promotion evidence."
    )


__all__ = [
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_AUDITED_INTERVAL_NAME",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_AUDIT_END_EXCLUSIVE_UTC",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_AUDIT_START_UTC",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_MARKET_TYPE",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_SOURCE_NAME",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANONICAL_SYMBOL",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_ACCESS_TYPE",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_ENDPOINT_PATH",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_ENDPOINT_URL",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_MARKET_TYPE",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_ID",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_VERSION",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_NAME",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_SYMBOL",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CANDIDATE_TIME_SEMANTICS",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_COLLECTION_DIRECTION",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CONFIRM_VALUE",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_COVERAGE_SCOPE_STATEMENT",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CURSOR_EXCLUSIVE",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CURSOR_NAME",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_CURSOR_NO_PROGRESS_COUNT",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_DUPLICATE_COUNT",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_EXPECTED_CANDLE_COUNT",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_FIRST_CANDLE_OPEN_UTC",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_FOUND_CANDLE_COUNT",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_GAP_COUNT",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_HTTP_ERROR_COUNT",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_INCOMPLETE_CANDLE_COUNT",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_INTERVAL_COUNT",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_LIMIT_USED",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_LAST_CANDLE_OPEN_UTC",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_OVERLAP_COUNT",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PAGES_OBSERVED",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PROTOCOL_NAME",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PROTOCOL_VERSION",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_PROVIDER_QUALIFICATION_COUNT",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_RISK_NOTES",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCOPE",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCHEMA_VERSION",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_SCOPE",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_TIMEOUT_COUNT",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_UTC_ALIGNMENT_VALID",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_UTC_TIME_SEMANTICS",
    "HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_YEAR_COUNT",
    "HistoricalFuturesMarketIntegralSourceQualificationAnnualResult",
    "HistoricalFuturesMarketIntegralSourceQualificationConflictError",
    "HistoricalFuturesMarketIntegralSourceQualificationError",
    "HistoricalFuturesMarketIntegralSourceQualificationIntegrityError",
    "HistoricalFuturesMarketIntegralSourceQualificationProtocol",
    "HistoricalFuturesMarketIntegralSourceQualificationPromotionError",
    "HistoricalFuturesMarketIntegralSourceQualificationReport",
    "HistoricalFuturesMarketIntegralSourceQualificationSummary",
    "HistoricalFuturesMarketIntegralSourceQualificationValidationError",
    "build_historical_futures_market_integral_source_qualification_protocol",
    "build_historical_futures_market_integral_source_qualification_report",
    "load_historical_futures_market_integral_source_qualification_report",
    "reject_historical_futures_market_integral_source_qualification_promotion",
    "run_historical_futures_market_integral_source_qualification",
    "save_historical_futures_market_integral_source_qualification_report",
    "status_historical_futures_market_integral_source_qualification_report",
    "verify_historical_futures_market_integral_source_qualification_report",
]
