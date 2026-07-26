"""Research-only distributed operational qualification for the observed OKX spot candidate.

This module freezes the fifteen distributed samples observed in Phase 18E into an
immutable, deterministic, fail-closed report. It records only derived evidence
for the sampled windows and does not authorize ingestion, dataset preparation,
replay, backtest, paper trading, or live trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
from historical_futures_market_operational_qualification import (
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_NAME,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ACCESS_TYPE,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_PATH,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_URL,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_MARKET_TYPE,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PAGINATION_LIMIT,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_ID,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_VERSION,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SOURCE_NAME,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SYMBOL,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_TIME_SEMANTICS,
)
from market_data import HistoricalDataValidationError
from market_data.provider_qualification import HistoricalProviderQualification

HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION = 1
HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_PROTOCOL_NAME = (
    "historical_futures_market_distributed_operational_qualification"
)
HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_PROTOCOL_VERSION = "v1"
HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_STATUS = (
    "distributed_operational_evidence_observed_not_authorized_for_ingestion"
)
HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES: tuple[str, ...] = (
    "15m",
    "1h",
    "4h",
)
HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_BAR_ALIASES: tuple[str, ...] = (
    "15m",
    "1H",
    "4H",
)
HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_YEARS: tuple[int, ...] = (
    2021,
    2022,
    2023,
    2024,
    2025,
)
HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT = (
    "Coverage is limited to fifteen distributed samples across 2021, 2022, 2023, 2024, and 2025; "
    "it does not establish continuous history coverage."
)
HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT = (
    "No API polling, dataset, manifest, content hash, candle hash, replay, backtest, "
    "performance comparison, paper trading, or live trading is authorized."
)
HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT = (
    "The OKX history-candles endpoint was observed with limit=100, confirm=1 on closed candles, "
    "and after as the pagination mechanism for older candles; before returned newer candles; "
    "the second page can include candles before the requested window start and must be filtered in memory."
)
HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_RISK_NOTES: tuple[str, ...] = (
    "Lowercase 1h and 4h are not valid aliases in this contract; 1H and 4H are required.",
    "The second page can contain candles before the requested window start and must be filtered in memory in any future authorized implementation.",
    "The samples are distributed across 2021, 2022, 2023, 2024, and 2025 and do not prove continuous history coverage.",
    "OKX remains separate from KuCoin and is not authorized for ingestion.",
)

_INTERVAL_SPECS: dict[str, dict[str, Any]] = {
    "15m": {"bar_alias": "15m", "span": timedelta(days=2), "window_candle_count": 192},
    "1h": {"bar_alias": "1H", "span": timedelta(days=5), "window_candle_count": 120},
    "4h": {"bar_alias": "4H", "span": timedelta(days=18), "window_candle_count": 108},
}
_INTERVAL_DURATION: dict[str, timedelta] = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
}
_WINDOW_START_BY_YEAR_INTERVAL: dict[tuple[int, str], datetime] = {}
_EXPECTED_SAMPLE_ORDER: tuple[tuple[str, int], ...] = tuple(
    (interval_name, year)
    for interval_name in HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES
    for year in HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_YEARS
)


class HistoricalFuturesMarketDistributedOperationalQualificationError(Exception):
    pass


class HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
    HistoricalFuturesMarketDistributedOperationalQualificationError
):
    pass


class HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError(
    HistoricalFuturesMarketDistributedOperationalQualificationValidationError
):
    pass


class HistoricalFuturesMarketDistributedOperationalQualificationConflictError(
    HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError
):
    pass


class HistoricalFuturesMarketDistributedOperationalQualificationPromotionError(
    HistoricalFuturesMarketDistributedOperationalQualificationValidationError
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hash(value: Any, field_name: str) -> str:
    normalized = _require_str(value, field_name).lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            f"{field_name} must be a 64-character hexadecimal hash."
        )
    return normalized


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            f"{field_name} must be a boolean."
        )
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            f"{field_name} must be an integer."
        )
    if allow_zero:
        if value < 0:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                f"{field_name} cannot be negative."
            )
    elif value <= 0:
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            f"{field_name} must be greater than zero."
        )
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _validate_exact_keys(mapping: Mapping[str, Any], *, allowed: set[str], name: str) -> None:
    extra = set(mapping) - allowed
    if extra:
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            f"{name} contains unknown fields: {sorted(extra)!r}."
        )


def _research_only(historical_research_only: bool, operational_evidence: bool, paper_promotion_eligible: bool) -> None:
    if historical_research_only is not True:
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            "historical_research_only must be true."
        )
    if operational_evidence is not False:
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            "operational_evidence must be false."
        )
    if paper_promotion_eligible is not False:
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            "paper_promotion_eligible must be false."
        )


def _expected_sample_order() -> tuple[tuple[str, int], ...]:
    return _EXPECTED_SAMPLE_ORDER


def _expected_provider_qualification(bar_alias: str) -> HistoricalProviderQualification:
    bar_alias = _require_str(bar_alias, "bar_alias")
    if bar_alias not in HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_BAR_ALIASES:
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            "bar_alias must be 15m, 1H, or 4H."
        )
    return HistoricalProviderQualification(
        provider_id=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_ID,
        provider_version=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_VERSION,
        market_type=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_MARKET_TYPE,
        exchange=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE,
        symbol=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SYMBOL,
        interval=bar_alias,
        time_semantics=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_TIME_SEMANTICS,
        access_type=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ACCESS_TYPE,
        data_contract_version=2,
        external_symbol=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL,
        endpoint_url=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_URL,
        documentation_url=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL,
        pagination_limit=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PAGINATION_LIMIT,
        close_time_rule=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE,
    )


def _expected_sample_spec(year: int, interval_name: str) -> dict[str, Any]:
    normalized_year = _require_int(year, "year")
    if normalized_year not in HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_YEARS:
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            "year must be 2021, 2022, 2023, 2024, or 2025."
        )
    normalized_interval = _require_str(interval_name, "interval_name").lower()
    if normalized_interval not in _INTERVAL_SPECS:
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            "interval must be 15m, 1h, or 4h."
        )
    start_utc = datetime(normalized_year, 1, 1, tzinfo=timezone.utc)
    span = _INTERVAL_SPECS[normalized_interval]["span"]
    duration = _INTERVAL_DURATION[normalized_interval]
    end_utc = start_utc + span
    last_candle_open_utc = end_utc - duration
    return {
        "year": normalized_year,
        "interval_name": normalized_interval,
        "bar_alias": _INTERVAL_SPECS[normalized_interval]["bar_alias"],
        "window_start_utc": start_utc,
        "window_end_utc": end_utc,
        "page_count": 2,
        "fetched_count": 200,
        "window_candle_count": int(span / duration),
        "first_candle_open_utc": start_utc,
        "last_candle_open_utc": last_candle_open_utc,
        "confirm_value": 1,
        "all_confirm_closed": True,
        "incomplete_candle_confirm_observed": False,
        "duplicate_count": 0,
        "gap_count": 0,
        "second_page_contains_pre_window_candles": True,
        "second_page_filtered_in_memory": True,
        "before_returns_newer_candles": True,
        "after_observed_as_pagination_mechanism": True,
        "utc_time_semantics": HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_TIME_SEMANTICS,
        "pagination_limit": HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PAGINATION_LIMIT,
    }


def _expected_totals(samples: Sequence["HistoricalFuturesMarketDistributedOperationalQualificationSample"]) -> dict[str, Any]:
    return {
        "sample_count": len(samples),
        "year_count": len(HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_YEARS),
        "interval_count": len(HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES),
        "page_count": sum(sample.page_count for sample in samples),
        "fetched_count": sum(sample.fetched_count for sample in samples),
        "window_candle_count": sum(sample.window_candle_count for sample in samples),
        "duplicate_count": sum(sample.duplicate_count for sample in samples),
        "gap_count": sum(sample.gap_count for sample in samples),
    }


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketDistributedOperationalQualificationSample:
    provider_qualification: HistoricalProviderQualification
    year: int
    interval_name: str
    bar_alias: str
    window_start_utc: datetime
    window_end_utc: datetime
    page_count: int
    fetched_count: int
    window_candle_count: int
    first_candle_open_utc: datetime
    last_candle_open_utc: datetime
    confirm_value: int
    all_confirm_closed: bool
    incomplete_candle_confirm_observed: bool
    duplicate_count: int
    gap_count: int
    second_page_contains_pre_window_candles: bool
    second_page_filtered_in_memory: bool
    before_returns_newer_candles: bool
    after_observed_as_pagination_mechanism: bool
    utc_time_semantics: str
    pagination_limit: int
    schema_version: int = HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION
    sample_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.provider_qualification, HistoricalProviderQualification):
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "provider_qualification must be a HistoricalProviderQualification instance."
            )
        object.__setattr__(self, "year", _require_int(self.year, "year"))
        object.__setattr__(self, "interval_name", _require_str(self.interval_name, "interval_name").lower())
        object.__setattr__(self, "bar_alias", _require_str(self.bar_alias, "bar_alias"))
        object.__setattr__(self, "window_start_utc", _require_utc_datetime(self.window_start_utc, "window_start_utc"))
        object.__setattr__(self, "window_end_utc", _require_utc_datetime(self.window_end_utc, "window_end_utc"))
        object.__setattr__(self, "page_count", _require_int(self.page_count, "page_count"))
        object.__setattr__(self, "fetched_count", _require_int(self.fetched_count, "fetched_count"))
        object.__setattr__(self, "window_candle_count", _require_int(self.window_candle_count, "window_candle_count"))
        object.__setattr__(self, "first_candle_open_utc", _require_utc_datetime(self.first_candle_open_utc, "first_candle_open_utc"))
        object.__setattr__(self, "last_candle_open_utc", _require_utc_datetime(self.last_candle_open_utc, "last_candle_open_utc"))
        object.__setattr__(self, "confirm_value", _require_int(self.confirm_value, "confirm_value"))
        object.__setattr__(self, "all_confirm_closed", _require_bool(self.all_confirm_closed, "all_confirm_closed"))
        object.__setattr__(
            self,
            "incomplete_candle_confirm_observed",
            _require_bool(self.incomplete_candle_confirm_observed, "incomplete_candle_confirm_observed"),
        )
        object.__setattr__(self, "duplicate_count", _require_int(self.duplicate_count, "duplicate_count", allow_zero=True))
        object.__setattr__(self, "gap_count", _require_int(self.gap_count, "gap_count", allow_zero=True))
        object.__setattr__(
            self,
            "second_page_contains_pre_window_candles",
            _require_bool(self.second_page_contains_pre_window_candles, "second_page_contains_pre_window_candles"),
        )
        object.__setattr__(
            self,
            "second_page_filtered_in_memory",
            _require_bool(self.second_page_filtered_in_memory, "second_page_filtered_in_memory"),
        )
        object.__setattr__(
            self,
            "before_returns_newer_candles",
            _require_bool(self.before_returns_newer_candles, "before_returns_newer_candles"),
        )
        object.__setattr__(
            self,
            "after_observed_as_pagination_mechanism",
            _require_bool(self.after_observed_as_pagination_mechanism, "after_observed_as_pagination_mechanism"),
        )
        object.__setattr__(self, "utc_time_semantics", _require_str(self.utc_time_semantics, "utc_time_semantics").lower())
        object.__setattr__(self, "pagination_limit", _require_int(self.pagination_limit, "pagination_limit"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "sample schema_version must be 1."
            )
        expected = _expected_sample_spec(self.year, self.interval_name)
        if self.bar_alias != expected["bar_alias"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "bar_alias diverges from the declared distributed evidence."
            )
        if self.provider_qualification != _expected_provider_qualification(self.bar_alias):
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "provider_qualification diverges from the declared distributed evidence."
            )
        if self.window_start_utc != expected["window_start_utc"] or self.window_end_utc != expected["window_end_utc"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "window bounds diverge from the declared distributed evidence."
            )
        if self.page_count != expected["page_count"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "page_count diverges from the declared distributed evidence."
            )
        if self.fetched_count != expected["fetched_count"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "fetched_count diverges from the declared distributed evidence."
            )
        if self.window_candle_count != expected["window_candle_count"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "window_candle_count diverges from the declared distributed evidence."
            )
        if self.first_candle_open_utc != expected["first_candle_open_utc"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "first_candle_open_utc diverges from the declared distributed evidence."
            )
        if self.last_candle_open_utc != expected["last_candle_open_utc"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "last_candle_open_utc diverges from the declared distributed evidence."
            )
        if self.confirm_value != expected["confirm_value"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "confirm_value diverges from the declared distributed evidence."
            )
        if self.all_confirm_closed is not expected["all_confirm_closed"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "all_confirm_closed must remain true."
            )
        if self.incomplete_candle_confirm_observed is not expected["incomplete_candle_confirm_observed"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "incomplete_candle_confirm_observed must remain false."
            )
        if self.duplicate_count != expected["duplicate_count"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "duplicate_count diverges from the declared distributed evidence."
            )
        if self.gap_count != expected["gap_count"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "gap_count diverges from the declared distributed evidence."
            )
        if self.second_page_contains_pre_window_candles is not expected["second_page_contains_pre_window_candles"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "second_page_contains_pre_window_candles must remain true."
            )
        if self.second_page_filtered_in_memory is not expected["second_page_filtered_in_memory"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "second_page_filtered_in_memory must remain true."
            )
        if self.before_returns_newer_candles is not expected["before_returns_newer_candles"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "before_returns_newer_candles must remain true."
            )
        if self.after_observed_as_pagination_mechanism is not expected["after_observed_as_pagination_mechanism"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "after_observed_as_pagination_mechanism must remain true."
            )
        if self.utc_time_semantics != expected["utc_time_semantics"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "utc_time_semantics must remain utc."
            )
        if self.pagination_limit != expected["pagination_limit"]:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "pagination_limit diverges from the declared distributed evidence."
            )
        if self.last_candle_open_utc < self.first_candle_open_utc:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "last_candle_open_utc must not precede first_candle_open_utc."
            )
        expected_hash = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.sample_hash:
            if self.sample_hash != _require_hash(self.sample_hash, "sample_hash"):
                raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("sample hash mismatch.")
            if self.sample_hash != expected_hash:
                raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("sample hash mismatch.")
        else:
            object.__setattr__(self, "sample_hash", expected_hash)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "provider_qualification": self.provider_qualification.as_dict(),
            "year": self.year,
            "interval_name": self.interval_name,
            "bar_alias": self.bar_alias,
            "window_start_utc": _utc_iso(self.window_start_utc),
            "window_end_utc": _utc_iso(self.window_end_utc),
            "page_count": self.page_count,
            "fetched_count": self.fetched_count,
            "window_candle_count": self.window_candle_count,
            "first_candle_open_utc": _utc_iso(self.first_candle_open_utc),
            "last_candle_open_utc": _utc_iso(self.last_candle_open_utc),
            "confirm_value": self.confirm_value,
            "all_confirm_closed": self.all_confirm_closed,
            "incomplete_candle_confirm_observed": self.incomplete_candle_confirm_observed,
            "duplicate_count": self.duplicate_count,
            "gap_count": self.gap_count,
            "second_page_contains_pre_window_candles": self.second_page_contains_pre_window_candles,
            "second_page_filtered_in_memory": self.second_page_filtered_in_memory,
            "before_returns_newer_candles": self.before_returns_newer_candles,
            "after_observed_as_pagination_mechanism": self.after_observed_as_pagination_mechanism,
            "utc_time_semantics": self.utc_time_semantics,
            "pagination_limit": self.pagination_limit,
        }
        if include_hash:
            payload["sample_hash"] = self.sample_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
    ) -> "HistoricalFuturesMarketDistributedOperationalQualificationSample":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("sample must be a mapping.")
        mapping = dict(data)
        try:
            _validate_exact_keys(
                mapping,
                allowed={
                    "schema_version",
                    "provider_qualification",
                    "year",
                    "interval_name",
                    "bar_alias",
                    "window_start_utc",
                    "window_end_utc",
                    "page_count",
                    "fetched_count",
                    "window_candle_count",
                    "first_candle_open_utc",
                    "last_candle_open_utc",
                    "confirm_value",
                    "all_confirm_closed",
                    "incomplete_candle_confirm_observed",
                    "duplicate_count",
                    "gap_count",
                    "second_page_contains_pre_window_candles",
                    "second_page_filtered_in_memory",
                    "before_returns_newer_candles",
                    "after_observed_as_pagination_mechanism",
                    "utc_time_semantics",
                    "pagination_limit",
                    "sample_hash",
                },
                name="sample",
            )
            return cls(
                schema_version=mapping["schema_version"],
                provider_qualification=HistoricalProviderQualification.from_dict(mapping["provider_qualification"]),
                year=mapping["year"],
                interval_name=mapping["interval_name"],
                bar_alias=mapping["bar_alias"],
                window_start_utc=mapping["window_start_utc"],
                window_end_utc=mapping["window_end_utc"],
                page_count=mapping["page_count"],
                fetched_count=mapping["fetched_count"],
                window_candle_count=mapping["window_candle_count"],
                first_candle_open_utc=mapping["first_candle_open_utc"],
                last_candle_open_utc=mapping["last_candle_open_utc"],
                confirm_value=mapping["confirm_value"],
                all_confirm_closed=mapping["all_confirm_closed"],
                incomplete_candle_confirm_observed=mapping["incomplete_candle_confirm_observed"],
                duplicate_count=mapping["duplicate_count"],
                gap_count=mapping["gap_count"],
                second_page_contains_pre_window_candles=mapping["second_page_contains_pre_window_candles"],
                second_page_filtered_in_memory=mapping["second_page_filtered_in_memory"],
                before_returns_newer_candles=mapping["before_returns_newer_candles"],
                after_observed_as_pagination_mechanism=mapping["after_observed_as_pagination_mechanism"],
                utc_time_semantics=mapping["utc_time_semantics"],
                pagination_limit=mapping["pagination_limit"],
                sample_hash=mapping.get("sample_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("sample is incomplete.") from exc
        except (
            HistoricalFuturesMarketDistributedOperationalQualificationValidationError,
            HistoricalDataValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketDistributedOperationalQualificationProtocol:
    coverage_start_utc: datetime
    coverage_end_utc: datetime
    years: tuple[int, ...]
    interval_names: tuple[str, ...]
    bar_aliases: tuple[str, ...]
    sample_hashes: tuple[str, ...]
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
    distributed_operational_evidence_status: str
    coverage_scope_statement: str
    non_ingestion_scope_statement: str
    pagination_behavior_statement: str
    risk_notes: tuple[str, ...]
    sample_count: int
    year_count: int
    interval_count: int
    page_count: int
    fetched_count: int
    window_candle_count: int
    duplicate_count: int
    gap_count: int
    distributed_samples_only: bool
    continuous_history_coverage_claimed: bool
    schema_version: int = HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION
    protocol_name: str = HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_PROTOCOL_NAME
    protocol_version: str = HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_PROTOCOL_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    protocol_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "coverage_start_utc", _require_utc_datetime(self.coverage_start_utc, "coverage_start_utc"))
        object.__setattr__(self, "coverage_end_utc", _require_utc_datetime(self.coverage_end_utc, "coverage_end_utc"))
        object.__setattr__(self, "years", tuple(_require_int(item, "year") for item in self.years))
        object.__setattr__(self, "interval_names", tuple(_require_str(item, "interval_name").lower() for item in self.interval_names))
        object.__setattr__(self, "bar_aliases", tuple(_require_str(item, "bar_alias") for item in self.bar_aliases))
        object.__setattr__(self, "sample_hashes", tuple(_require_hash(item, "sample_hash") for item in self.sample_hashes))
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
        object.__setattr__(self, "distributed_operational_evidence_status", _require_str(self.distributed_operational_evidence_status, "distributed_operational_evidence_status"))
        object.__setattr__(self, "coverage_scope_statement", _require_str(self.coverage_scope_statement, "coverage_scope_statement"))
        object.__setattr__(self, "non_ingestion_scope_statement", _require_str(self.non_ingestion_scope_statement, "non_ingestion_scope_statement"))
        object.__setattr__(self, "pagination_behavior_statement", _require_str(self.pagination_behavior_statement, "pagination_behavior_statement"))
        object.__setattr__(self, "risk_notes", tuple(_require_str(item, "risk_note") for item in self.risk_notes))
        object.__setattr__(self, "sample_count", _require_int(self.sample_count, "sample_count"))
        object.__setattr__(self, "year_count", _require_int(self.year_count, "year_count"))
        object.__setattr__(self, "interval_count", _require_int(self.interval_count, "interval_count"))
        object.__setattr__(self, "page_count", _require_int(self.page_count, "page_count"))
        object.__setattr__(self, "fetched_count", _require_int(self.fetched_count, "fetched_count"))
        object.__setattr__(self, "window_candle_count", _require_int(self.window_candle_count, "window_candle_count"))
        object.__setattr__(self, "duplicate_count", _require_int(self.duplicate_count, "duplicate_count", allow_zero=True))
        object.__setattr__(self, "gap_count", _require_int(self.gap_count, "gap_count", allow_zero=True))
        object.__setattr__(self, "distributed_samples_only", _require_bool(self.distributed_samples_only, "distributed_samples_only"))
        object.__setattr__(
            self,
            "continuous_history_coverage_claimed",
            _require_bool(self.continuous_history_coverage_claimed, "continuous_history_coverage_claimed"),
        )
        object.__setattr__(self, "protocol_name", _require_str(self.protocol_name, "protocol_name"))
        object.__setattr__(self, "protocol_version", _require_str(self.protocol_version, "protocol_version"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "distributed operational qualification schema_version must be 1."
            )
        if self.protocol_name != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_PROTOCOL_NAME:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "protocol_name diverges from the trusted distributed operational qualification contract."
            )
        if self.protocol_version != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_PROTOCOL_VERSION:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "protocol_version diverges from the trusted distributed operational qualification contract."
            )
        if self.years != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_YEARS:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "years must remain 2021, 2022, 2023, 2024, 2025."
            )
        if self.interval_names != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "interval_names must remain 15m, 1h, 4h."
            )
        if self.bar_aliases != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_BAR_ALIASES:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "bar_aliases must remain 15m, 1H, 4H."
            )
        if len(self.sample_hashes) != 15:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "sample_hashes must contain exactly fifteen hashes."
            )
        if self.canonical_source_name != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_NAME:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "canonical_source_name must remain KuCoin spot."
            )
        if self.canonical_source_provider_id != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "canonical_source_provider_id must remain the KuCoin provider id."
            )
        if self.candidate_source_name != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SOURCE_NAME:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "candidate_source_name must remain OKX spot."
            )
        if self.candidate_provider_id != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_ID:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "candidate_provider_id must remain the OKX provider id."
            )
        if self.candidate_market_type != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_MARKET_TYPE:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "candidate_market_type must remain spot."
            )
        if self.candidate_symbol != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SYMBOL:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "candidate_symbol must remain BTCUSDT."
            )
        if self.candidate_external_symbol != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "candidate_external_symbol must remain BTC-USDT."
            )
        if self.candidate_time_semantics != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_TIME_SEMANTICS:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "candidate_time_semantics must remain utc."
            )
        if self.candidate_access_type != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ACCESS_TYPE:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "candidate_access_type must remain public_no_auth."
            )
        if self.candidate_provider_version != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_VERSION:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "candidate_provider_version must remain v1."
            )
        if self.candidate_provider_exchange != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "candidate_provider_exchange must remain okx."
            )
        if self.candidate_endpoint_url != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_URL:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "candidate_endpoint_url diverges from the declared evidence."
            )
        if self.candidate_documentation_url != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "candidate_documentation_url diverges from the declared evidence."
            )
        if self.candidate_endpoint_path != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_PATH:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "candidate_endpoint_path diverges from the declared evidence."
            )
        if self.distributed_operational_evidence_status != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_STATUS:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "distributed_operational_evidence_status diverges from the declared evidence."
            )
        if self.coverage_scope_statement != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "coverage_scope_statement diverges from the declared evidence."
            )
        if self.non_ingestion_scope_statement != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "non_ingestion_scope_statement diverges from the declared evidence."
            )
        if self.pagination_behavior_statement != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "pagination_behavior_statement diverges from the declared evidence."
            )
        if self.risk_notes != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_RISK_NOTES:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "risk_notes diverge from the declared evidence."
            )
        if self.sample_count != 15:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "sample_count must be exactly fifteen."
            )
        if self.year_count != 5:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "year_count must be exactly five."
            )
        if self.interval_count != 3:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "interval_count must be exactly three."
            )
        if self.page_count != 30:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "page_count must be exactly thirty."
            )
        if self.fetched_count != 3000:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "fetched_count must be exactly three thousand."
            )
        if self.window_candle_count != 2100:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "window_candle_count must be exactly two thousand one hundred."
            )
        if self.duplicate_count != 0:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "duplicate_count must remain zero."
            )
        if self.gap_count != 0:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("gap_count must remain zero.")
        if self.distributed_samples_only is not True:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "distributed_samples_only must remain true."
            )
        if self.continuous_history_coverage_claimed is not False:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "continuous_history_coverage_claimed must remain false."
            )
        if self.coverage_start_utc != datetime(2021, 1, 1, tzinfo=timezone.utc):
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "coverage_start_utc must remain 2021-01-01T00:00:00Z."
            )
        if self.coverage_end_utc != datetime(2025, 1, 18, 20, 0, tzinfo=timezone.utc):
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "coverage_end_utc must remain 2025-01-18T20:00:00Z."
            )
        if self.coverage_start_utc > self.coverage_end_utc:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "coverage_end_utc must be after coverage_start_utc."
            )
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.protocol_hash:
            if self.protocol_hash != _require_hash(self.protocol_hash, "protocol_hash"):
                raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("protocol hash mismatch.")
            if self.protocol_hash != expected:
                raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("protocol hash mismatch.")
        else:
            object.__setattr__(self, "protocol_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "protocol_name": self.protocol_name,
            "protocol_version": self.protocol_version,
            "coverage_start_utc": _utc_iso(self.coverage_start_utc),
            "coverage_end_utc": _utc_iso(self.coverage_end_utc),
            "years": list(self.years),
            "interval_names": list(self.interval_names),
            "bar_aliases": list(self.bar_aliases),
            "sample_hashes": list(self.sample_hashes),
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
            "distributed_operational_evidence_status": self.distributed_operational_evidence_status,
            "coverage_scope_statement": self.coverage_scope_statement,
            "non_ingestion_scope_statement": self.non_ingestion_scope_statement,
            "pagination_behavior_statement": self.pagination_behavior_statement,
            "risk_notes": list(self.risk_notes),
            "sample_count": self.sample_count,
            "year_count": self.year_count,
            "interval_count": self.interval_count,
            "page_count": self.page_count,
            "fetched_count": self.fetched_count,
            "window_candle_count": self.window_candle_count,
            "duplicate_count": self.duplicate_count,
            "gap_count": self.gap_count,
            "distributed_samples_only": self.distributed_samples_only,
            "continuous_history_coverage_claimed": self.continuous_history_coverage_claimed,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketDistributedOperationalQualificationProtocol":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("protocol must be a mapping.")
        mapping = dict(data)
        try:
            _validate_exact_keys(
                mapping,
                allowed={
                    "schema_version",
                    "protocol_name",
                    "protocol_version",
                    "coverage_start_utc",
                    "coverage_end_utc",
                    "years",
                    "interval_names",
                    "bar_aliases",
                    "sample_hashes",
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
                    "distributed_operational_evidence_status",
                    "coverage_scope_statement",
                    "non_ingestion_scope_statement",
                    "pagination_behavior_statement",
                    "risk_notes",
                    "sample_count",
                    "year_count",
                    "interval_count",
                    "page_count",
                    "fetched_count",
                    "window_candle_count",
                    "duplicate_count",
                    "gap_count",
                    "distributed_samples_only",
                    "continuous_history_coverage_claimed",
                    "historical_research_only",
                    "operational_evidence",
                    "paper_promotion_eligible",
                    "protocol_hash",
                },
                name="protocol",
            )
            return cls(
                schema_version=mapping["schema_version"],
                protocol_name=mapping["protocol_name"],
                protocol_version=mapping["protocol_version"],
                coverage_start_utc=mapping["coverage_start_utc"],
                coverage_end_utc=mapping["coverage_end_utc"],
                years=tuple(mapping["years"]),
                interval_names=tuple(mapping["interval_names"]),
                bar_aliases=tuple(mapping["bar_aliases"]),
                sample_hashes=tuple(mapping["sample_hashes"]),
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
                distributed_operational_evidence_status=mapping["distributed_operational_evidence_status"],
                coverage_scope_statement=mapping["coverage_scope_statement"],
                non_ingestion_scope_statement=mapping["non_ingestion_scope_statement"],
                pagination_behavior_statement=mapping["pagination_behavior_statement"],
                risk_notes=tuple(mapping["risk_notes"]),
                sample_count=mapping["sample_count"],
                year_count=mapping["year_count"],
                interval_count=mapping["interval_count"],
                page_count=mapping["page_count"],
                fetched_count=mapping["fetched_count"],
                window_candle_count=mapping["window_candle_count"],
                duplicate_count=mapping["duplicate_count"],
                gap_count=mapping["gap_count"],
                distributed_samples_only=mapping["distributed_samples_only"],
                continuous_history_coverage_claimed=mapping["continuous_history_coverage_claimed"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                protocol_hash=mapping.get("protocol_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("protocol is incomplete.") from exc
        except (
            HistoricalFuturesMarketDistributedOperationalQualificationValidationError,
            HistoricalDataValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketDistributedOperationalQualificationSummary:
    sample_count: int
    year_count: int
    interval_count: int
    page_count: int
    fetched_count: int
    window_candle_count: int
    duplicate_count: int
    gap_count: int
    all_confirm_closed: bool
    incomplete_candle_confirm_observed: bool
    distributed_samples_only: bool
    continuous_history_coverage_claimed: bool
    distributed_operational_evidence_status: str
    coverage_scope_statement: str
    non_ingestion_scope_statement: str
    pagination_behavior_statement: str
    risk_notes: tuple[str, ...]
    schema_version: int = HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION
    summary_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_count", _require_int(self.sample_count, "sample_count"))
        object.__setattr__(self, "year_count", _require_int(self.year_count, "year_count"))
        object.__setattr__(self, "interval_count", _require_int(self.interval_count, "interval_count"))
        object.__setattr__(self, "page_count", _require_int(self.page_count, "page_count"))
        object.__setattr__(self, "fetched_count", _require_int(self.fetched_count, "fetched_count"))
        object.__setattr__(self, "window_candle_count", _require_int(self.window_candle_count, "window_candle_count"))
        object.__setattr__(self, "duplicate_count", _require_int(self.duplicate_count, "duplicate_count", allow_zero=True))
        object.__setattr__(self, "gap_count", _require_int(self.gap_count, "gap_count", allow_zero=True))
        object.__setattr__(self, "all_confirm_closed", _require_bool(self.all_confirm_closed, "all_confirm_closed"))
        object.__setattr__(
            self,
            "incomplete_candle_confirm_observed",
            _require_bool(self.incomplete_candle_confirm_observed, "incomplete_candle_confirm_observed"),
        )
        object.__setattr__(self, "distributed_samples_only", _require_bool(self.distributed_samples_only, "distributed_samples_only"))
        object.__setattr__(
            self,
            "continuous_history_coverage_claimed",
            _require_bool(self.continuous_history_coverage_claimed, "continuous_history_coverage_claimed"),
        )
        object.__setattr__(self, "distributed_operational_evidence_status", _require_str(self.distributed_operational_evidence_status, "distributed_operational_evidence_status"))
        object.__setattr__(self, "coverage_scope_statement", _require_str(self.coverage_scope_statement, "coverage_scope_statement"))
        object.__setattr__(self, "non_ingestion_scope_statement", _require_str(self.non_ingestion_scope_statement, "non_ingestion_scope_statement"))
        object.__setattr__(self, "pagination_behavior_statement", _require_str(self.pagination_behavior_statement, "pagination_behavior_statement"))
        object.__setattr__(self, "risk_notes", tuple(_require_str(item, "risk_note") for item in self.risk_notes))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "summary schema_version must be 1."
            )
        if self.sample_count != 15:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "sample_count must be exactly fifteen."
            )
        if self.year_count != 5:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "year_count must be exactly five."
            )
        if self.interval_count != 3:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "interval_count must be exactly three."
            )
        if self.page_count != 30:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("page_count must be exactly thirty.")
        if self.fetched_count != 3000:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "fetched_count must be exactly three thousand."
            )
        if self.window_candle_count != 2100:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "window_candle_count must be exactly two thousand one hundred."
            )
        if self.duplicate_count != 0:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("duplicate_count must remain zero.")
        if self.gap_count != 0:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("gap_count must remain zero.")
        if self.all_confirm_closed is not True:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("all_confirm_closed must remain true.")
        if self.incomplete_candle_confirm_observed is not False:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "incomplete_candle_confirm_observed must remain false."
            )
        if self.distributed_samples_only is not True:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "distributed_samples_only must remain true."
            )
        if self.continuous_history_coverage_claimed is not False:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "continuous_history_coverage_claimed must remain false."
            )
        if self.distributed_operational_evidence_status != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_STATUS:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "distributed_operational_evidence_status diverges from the declared evidence."
            )
        if self.coverage_scope_statement != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "coverage_scope_statement diverges from the declared evidence."
            )
        if self.non_ingestion_scope_statement != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "non_ingestion_scope_statement diverges from the declared evidence."
            )
        if self.pagination_behavior_statement != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "pagination_behavior_statement diverges from the declared evidence."
            )
        if self.risk_notes != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_RISK_NOTES:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "risk_notes diverge from the declared evidence."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.summary_hash:
            if self.summary_hash != _require_hash(self.summary_hash, "summary_hash"):
                raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("summary hash mismatch.")
            if self.summary_hash != expected:
                raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("summary hash mismatch.")
        else:
            object.__setattr__(self, "summary_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "sample_count": self.sample_count,
            "year_count": self.year_count,
            "interval_count": self.interval_count,
            "page_count": self.page_count,
            "fetched_count": self.fetched_count,
            "window_candle_count": self.window_candle_count,
            "duplicate_count": self.duplicate_count,
            "gap_count": self.gap_count,
            "all_confirm_closed": self.all_confirm_closed,
            "incomplete_candle_confirm_observed": self.incomplete_candle_confirm_observed,
            "distributed_samples_only": self.distributed_samples_only,
            "continuous_history_coverage_claimed": self.continuous_history_coverage_claimed,
            "distributed_operational_evidence_status": self.distributed_operational_evidence_status,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketDistributedOperationalQualificationSummary":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("summary must be a mapping.")
        mapping = dict(data)
        try:
            _validate_exact_keys(
                mapping,
                allowed={
                    "schema_version",
                    "sample_count",
                    "year_count",
                    "interval_count",
                    "page_count",
                    "fetched_count",
                    "window_candle_count",
                    "duplicate_count",
                    "gap_count",
                    "all_confirm_closed",
                    "incomplete_candle_confirm_observed",
                    "distributed_samples_only",
                    "continuous_history_coverage_claimed",
                    "distributed_operational_evidence_status",
                    "coverage_scope_statement",
                    "non_ingestion_scope_statement",
                    "pagination_behavior_statement",
                    "risk_notes",
                    "summary_hash",
                },
                name="summary",
            )
            return cls(
                schema_version=mapping["schema_version"],
                sample_count=mapping["sample_count"],
                year_count=mapping["year_count"],
                interval_count=mapping["interval_count"],
                page_count=mapping["page_count"],
                fetched_count=mapping["fetched_count"],
                window_candle_count=mapping["window_candle_count"],
                duplicate_count=mapping["duplicate_count"],
                gap_count=mapping["gap_count"],
                all_confirm_closed=mapping["all_confirm_closed"],
                incomplete_candle_confirm_observed=mapping["incomplete_candle_confirm_observed"],
                distributed_samples_only=mapping["distributed_samples_only"],
                continuous_history_coverage_claimed=mapping["continuous_history_coverage_claimed"],
                distributed_operational_evidence_status=mapping["distributed_operational_evidence_status"],
                coverage_scope_statement=mapping["coverage_scope_statement"],
                non_ingestion_scope_statement=mapping["non_ingestion_scope_statement"],
                pagination_behavior_statement=mapping["pagination_behavior_statement"],
                risk_notes=tuple(mapping["risk_notes"]),
                summary_hash=mapping.get("summary_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("summary is incomplete.") from exc
        except (
            HistoricalFuturesMarketDistributedOperationalQualificationValidationError,
            HistoricalDataValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketDistributedOperationalQualificationReport:
    protocol: HistoricalFuturesMarketDistributedOperationalQualificationProtocol
    distributed_samples: tuple[HistoricalFuturesMarketDistributedOperationalQualificationSample, ...]
    summary: HistoricalFuturesMarketDistributedOperationalQualificationSummary
    schema_version: int = HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    report_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.protocol, HistoricalFuturesMarketDistributedOperationalQualificationProtocol):
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "protocol must be a distributed operational qualification protocol instance."
            )
        if not isinstance(self.summary, HistoricalFuturesMarketDistributedOperationalQualificationSummary):
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "summary must be a distributed operational qualification summary instance."
            )
        if not isinstance(self.distributed_samples, tuple):
            object.__setattr__(self, "distributed_samples", tuple(self.distributed_samples))
        if len(self.distributed_samples) != 15:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "distributed_samples must contain exactly fifteen samples."
            )
        sample_order = tuple((sample.interval_name, sample.year) for sample in self.distributed_samples)
        if sample_order != _expected_sample_order():
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "distributed_samples must preserve 15m 2021-2025, 1h 2021-2025, 4h 2021-2025 order."
            )
        if self.schema_version != HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "distributed operational qualification report schema_version must be 1."
            )
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        expected_protocol = _build_protocol(self.distributed_samples)
        if self.protocol != expected_protocol:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "protocol diverges from the declared distributed evidence."
            )
        expected_summary = _build_summary(self.distributed_samples)
        if self.summary != expected_summary:
            raise HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError(
                "summary diverges from the declared distributed evidence."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.report_hash:
            if self.report_hash != _require_hash(self.report_hash, "report_hash"):
                raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("report hash mismatch.")
            if self.report_hash != expected:
                raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError("report hash mismatch.")
        else:
            object.__setattr__(self, "report_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "protocol": self.protocol.as_hash_payload(include_hash=False),
            "distributed_samples": [sample.as_dict() for sample in self.distributed_samples],
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketDistributedOperationalQualificationReport":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "distributed operational qualification report must be a mapping."
            )
        mapping = dict(data)
        try:
            _validate_exact_keys(
                mapping,
                allowed={
                    "schema_version",
                    "protocol",
                    "distributed_samples",
                    "summary",
                    "historical_research_only",
                    "operational_evidence",
                    "paper_promotion_eligible",
                    "report_hash",
                },
                name="distributed operational qualification report",
            )
            return cls(
                schema_version=mapping["schema_version"],
                protocol=HistoricalFuturesMarketDistributedOperationalQualificationProtocol.from_dict(mapping["protocol"]),
                distributed_samples=tuple(
                    HistoricalFuturesMarketDistributedOperationalQualificationSample.from_dict(item)
                    for item in mapping["distributed_samples"]
                ),
                summary=HistoricalFuturesMarketDistributedOperationalQualificationSummary.from_dict(mapping["summary"]),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                report_hash=mapping.get("report_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
                "distributed operational qualification report is incomplete."
            ) from exc
        except (
            HistoricalFuturesMarketDistributedOperationalQualificationValidationError,
            HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError,
            HistoricalFuturesMarketDistributedOperationalQualificationError,
            HistoricalDataValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError(str(exc)) from exc


def _build_samples() -> tuple[HistoricalFuturesMarketDistributedOperationalQualificationSample, ...]:
    samples: list[HistoricalFuturesMarketDistributedOperationalQualificationSample] = []
    for interval_name in HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES:
        for year in HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_YEARS:
            spec = _expected_sample_spec(year, interval_name)
            samples.append(
                HistoricalFuturesMarketDistributedOperationalQualificationSample(
                    provider_qualification=_expected_provider_qualification(spec["bar_alias"]),
                    year=spec["year"],
                    interval_name=spec["interval_name"],
                    bar_alias=spec["bar_alias"],
                    window_start_utc=spec["window_start_utc"],
                    window_end_utc=spec["window_end_utc"],
                    page_count=spec["page_count"],
                    fetched_count=spec["fetched_count"],
                    window_candle_count=spec["window_candle_count"],
                    first_candle_open_utc=spec["first_candle_open_utc"],
                    last_candle_open_utc=spec["last_candle_open_utc"],
                    confirm_value=spec["confirm_value"],
                    all_confirm_closed=spec["all_confirm_closed"],
                    incomplete_candle_confirm_observed=spec["incomplete_candle_confirm_observed"],
                    duplicate_count=spec["duplicate_count"],
                    gap_count=spec["gap_count"],
                    second_page_contains_pre_window_candles=spec["second_page_contains_pre_window_candles"],
                    second_page_filtered_in_memory=spec["second_page_filtered_in_memory"],
                    before_returns_newer_candles=spec["before_returns_newer_candles"],
                    after_observed_as_pagination_mechanism=spec["after_observed_as_pagination_mechanism"],
                    utc_time_semantics=spec["utc_time_semantics"],
                    pagination_limit=spec["pagination_limit"],
                )
            )
    return tuple(samples)


def _build_protocol(
    samples: Sequence[HistoricalFuturesMarketDistributedOperationalQualificationSample],
) -> HistoricalFuturesMarketDistributedOperationalQualificationProtocol:
    if not samples:
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            "distributed samples are required."
        )
    first = samples[0]
    last = samples[-1]
    return HistoricalFuturesMarketDistributedOperationalQualificationProtocol(
        coverage_start_utc=first.window_start_utc,
        coverage_end_utc=last.last_candle_open_utc,
        years=HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_YEARS,
        interval_names=HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES,
        bar_aliases=HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_BAR_ALIASES,
        sample_hashes=tuple(sample.sample_hash for sample in samples),
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
        distributed_operational_evidence_status=HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_STATUS,
        coverage_scope_statement=HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT,
        non_ingestion_scope_statement=HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT,
        pagination_behavior_statement=HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT,
        risk_notes=HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_RISK_NOTES,
        sample_count=len(samples),
        year_count=len(HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_YEARS),
        interval_count=len(HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES),
        page_count=sum(sample.page_count for sample in samples),
        fetched_count=sum(sample.fetched_count for sample in samples),
        window_candle_count=sum(sample.window_candle_count for sample in samples),
        duplicate_count=sum(sample.duplicate_count for sample in samples),
        gap_count=sum(sample.gap_count for sample in samples),
        distributed_samples_only=True,
        continuous_history_coverage_claimed=False,
    )


def _build_summary(
    samples: Sequence[HistoricalFuturesMarketDistributedOperationalQualificationSample],
) -> HistoricalFuturesMarketDistributedOperationalQualificationSummary:
    return HistoricalFuturesMarketDistributedOperationalQualificationSummary(
        sample_count=len(samples),
        year_count=len(HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_YEARS),
        interval_count=len(HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES),
        page_count=sum(sample.page_count for sample in samples),
        fetched_count=sum(sample.fetched_count for sample in samples),
        window_candle_count=sum(sample.window_candle_count for sample in samples),
        duplicate_count=sum(sample.duplicate_count for sample in samples),
        gap_count=sum(sample.gap_count for sample in samples),
        all_confirm_closed=all(sample.all_confirm_closed for sample in samples),
        incomplete_candle_confirm_observed=any(sample.incomplete_candle_confirm_observed for sample in samples),
        distributed_samples_only=True,
        continuous_history_coverage_claimed=False,
        distributed_operational_evidence_status=HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_STATUS,
        coverage_scope_statement=HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT,
        non_ingestion_scope_statement=HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT,
        pagination_behavior_statement=HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT,
        risk_notes=HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_RISK_NOTES,
    )


def build_historical_futures_market_distributed_operational_qualification_report(
    _: Any | None = None,
) -> HistoricalFuturesMarketDistributedOperationalQualificationReport:
    distributed_samples = _build_samples()
    summary = _build_summary(distributed_samples)
    protocol = _build_protocol(distributed_samples)
    return HistoricalFuturesMarketDistributedOperationalQualificationReport(
        protocol=protocol,
        distributed_samples=distributed_samples,
        summary=summary,
    )


def run_historical_futures_market_distributed_operational_qualification(
    _: Any | None = None,
    *,
    output_file: str | Path | None = None,
) -> HistoricalFuturesMarketDistributedOperationalQualificationReport:
    report = build_historical_futures_market_distributed_operational_qualification_report()
    if output_file is not None:
        save_historical_futures_market_distributed_operational_qualification_report(output_file, report)
    return report


def _read(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            "distributed operational qualification report not found."
        ) from exc
    except Exception as exc:
        raise HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError(
            "distributed operational qualification report is invalid JSON."
        ) from exc
    if not isinstance(value, Mapping):
        raise HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError(
            "distributed operational qualification report must be a JSON object."
        )
    return value


def load_historical_futures_market_distributed_operational_qualification_report(
    path: str | Path,
) -> HistoricalFuturesMarketDistributedOperationalQualificationReport:
    payload = _read(Path(path))
    try:
        report = HistoricalFuturesMarketDistributedOperationalQualificationReport.from_dict(payload)
    except (
        KeyError,
        TypeError,
        ValueError,
        HistoricalFuturesMarketDistributedOperationalQualificationValidationError,
        HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError,
        HistoricalDataValidationError,
    ) as exc:
        raise HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError(str(exc)) from exc
    if report.as_dict() != payload:
        raise HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError(
            "distributed operational qualification report payload mismatch."
        )
    return report


def save_historical_futures_market_distributed_operational_qualification_report(
    path: str | Path,
    report: HistoricalFuturesMarketDistributedOperationalQualificationReport,
) -> HistoricalFuturesMarketDistributedOperationalQualificationReport:
    file_path = Path(path)
    payload = report.as_dict()
    if file_path.exists():
        existing = load_historical_futures_market_distributed_operational_qualification_report(file_path)
        if existing.as_dict() != payload:
            raise HistoricalFuturesMarketDistributedOperationalQualificationConflictError(
                "distributed operational qualification report already exists and differs."
            )
        return existing
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_name(f".{file_path.name}.{os.getpid()}.{id(report)}.tmp")
    try:
        tmp.write_text(_canonical_json(payload), encoding="utf-8")
        try:
            os.link(tmp, file_path)
        except FileExistsError:
            existing = load_historical_futures_market_distributed_operational_qualification_report(file_path)
            if existing.as_dict() != payload:
                raise HistoricalFuturesMarketDistributedOperationalQualificationConflictError(
                    "distributed operational qualification report already exists and differs."
                )
            return existing
    except Exception as exc:
        if isinstance(exc, HistoricalFuturesMarketDistributedOperationalQualificationConflictError):
            raise
        raise HistoricalFuturesMarketDistributedOperationalQualificationValidationError(
            "failed to write distributed operational qualification report atomically."
        ) from exc
    finally:
        tmp.unlink(missing_ok=True)
    return report


def verify_historical_futures_market_distributed_operational_qualification_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_distributed_operational_qualification_report(path)
    return {
        "verified": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "summary_hash": report.summary.summary_hash,
        "classification": HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_STATUS,
        "distributed_operational_evidence_status": report.protocol.distributed_operational_evidence_status,
        "sample_count": report.protocol.sample_count,
        "year_count": report.protocol.year_count,
        "interval_count": report.protocol.interval_count,
        "page_count": report.protocol.page_count,
        "fetched_count": report.protocol.fetched_count,
        "window_candle_count": report.protocol.window_candle_count,
        "all_confirm_closed": report.summary.all_confirm_closed,
        "incomplete_candle_confirm_observed": report.summary.incomplete_candle_confirm_observed,
        "distributed_samples_only": report.summary.distributed_samples_only,
        "continuous_history_coverage_claimed": report.summary.continuous_history_coverage_claimed,
    }


def status_historical_futures_market_distributed_operational_qualification_report(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {"exists": False}
    report = load_historical_futures_market_distributed_operational_qualification_report(file_path)
    summary = report.summary
    return {
        "exists": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "summary_hash": summary.summary_hash,
        "sample_count": summary.sample_count,
        "year_count": summary.year_count,
        "interval_count": summary.interval_count,
        "page_count": summary.page_count,
        "fetched_count": summary.fetched_count,
        "window_candle_count": summary.window_candle_count,
        "duplicate_count": summary.duplicate_count,
        "gap_count": summary.gap_count,
        "all_confirm_closed": summary.all_confirm_closed,
        "incomplete_candle_confirm_observed": summary.incomplete_candle_confirm_observed,
        "distributed_samples_only": summary.distributed_samples_only,
        "continuous_history_coverage_claimed": summary.continuous_history_coverage_claimed,
        "distributed_operational_evidence_status": summary.distributed_operational_evidence_status,
    }


def reject_historical_futures_market_distributed_operational_qualification_promotion(
    _: HistoricalFuturesMarketDistributedOperationalQualificationReport,
) -> None:
    raise HistoricalFuturesMarketDistributedOperationalQualificationPromotionError(
        "distributed operational qualification remains research-only and cannot be promoted."
    )
