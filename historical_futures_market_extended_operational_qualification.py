"""Research-only extended operational qualification for the observed OKX spot candidate.

This module freezes the extended evidence observed in Phase 18C into an
immutable, deterministic, fail-closed report. It records only the observed
operational coverage for the verified frozen windows and does not authorize
ingestion, dataset preparation, replay, backtest, paper trading, or live
trading.
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
from historical_futures_market_operational_qualification import (
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ACCESS_TYPE,
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
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_NAME,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID,
)
from market_data import HistoricalDataValidationError
from market_data.provider_qualification import HistoricalProviderQualification

HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION = 1
HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_PROTOCOL_NAME = (
    "historical_futures_market_extended_operational_qualification"
)
HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_PROTOCOL_VERSION = "v1"
HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_STATUS = (
    "extended_operational_evidence_observed_not_authorized_for_ingestion"
)
HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES: tuple[str, ...] = (
    "15m",
    "1h",
    "4h",
)
HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_BAR_ALIASES: tuple[str, ...] = (
    "15m",
    "1H",
    "4H",
)
HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT = (
    "Coverage is limited to the frozen reference, validation, and test windows; "
    "coverage outside those windows remains unverified."
)
HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT = (
    "No dataset OKX was prepared; no manifest_hash, content_hash, or candle hash exists; "
    "no replay, backtest, performance comparison, paper, or live trading is authorized."
)
HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT = (
    "The OKX history-candles endpoint returned confirm=1 for closed historical candles and "
    "confirm=0 for an incomplete sample; before returned newer candles than the supplied timestamp, "
    "and after was observed as the pagination mechanism."
)
HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_RISK_NOTES: tuple[str, ...] = (
    "OKX requires 1H and 4H; lowercase 1h and 4h returned empty in the documented check.",
    "The last page can contain a candle before the authorized start and requires explicit timestamp filtering in a future authorized implementation.",
    "There is no evidence of coverage, retention, or integrity outside the frozen windows.",
    "OKX remains separate from KuCoin and is not authorized for ingestion.",
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

_OBSERVATION_SPECS: dict[str, dict[str, Any]] = {
    "15m": {
        "bar_alias": "15m",
        "candle_count": 80,
        "first_candle_open_utc": datetime(2025, 1, 4, 8, 0, 0, tzinfo=timezone.utc),
        "last_candle_open_utc": datetime(2025, 1, 5, 3, 45, 0, tzinfo=timezone.utc),
        "duplicate_count": 0,
        "gap_count": 0,
        "page_count": 4,
    },
    "1h": {
        "bar_alias": "1H",
        "candle_count": 20,
        "first_candle_open_utc": datetime(2025, 1, 4, 8, 0, 0, tzinfo=timezone.utc),
        "last_candle_open_utc": datetime(2025, 1, 5, 3, 0, 0, tzinfo=timezone.utc),
        "duplicate_count": 0,
        "gap_count": 0,
        "page_count": 3,
    },
    "4h": {
        "bar_alias": "4H",
        "candle_count": 5,
        "first_candle_open_utc": datetime(2025, 1, 4, 8, 0, 0, tzinfo=timezone.utc),
        "last_candle_open_utc": datetime(2025, 1, 5, 0, 0, 0, tzinfo=timezone.utc),
        "duplicate_count": 0,
        "gap_count": 0,
        "page_count": 3,
    },
}


class HistoricalFuturesMarketExtendedOperationalQualificationError(Exception):
    pass


class HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
    HistoricalFuturesMarketExtendedOperationalQualificationError
):
    pass


class HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError(
    HistoricalFuturesMarketExtendedOperationalQualificationValidationError
):
    pass


class HistoricalFuturesMarketExtendedOperationalQualificationConflictError(
    HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError
):
    pass


class HistoricalFuturesMarketExtendedOperationalQualificationPromotionError(
    HistoricalFuturesMarketExtendedOperationalQualificationValidationError
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _validate_exact_keys(mapping: Mapping[str, Any], *, allowed: set[str], name: str) -> None:
    extra = set(mapping) - allowed
    if extra:
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
            f"{name} contains unknown fields: {sorted(extra)!r}."
        )


def _research_only(historical_research_only: bool, operational_evidence: bool, paper_promotion_eligible: bool) -> None:
    if historical_research_only is not True:
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
            "historical_research_only must be true."
        )
    if operational_evidence is not False:
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
            "operational_evidence must be false."
        )
    if paper_promotion_eligible is not False:
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
            "paper_promotion_eligible must be false."
        )


def _expected_window_name_order() -> tuple[str, ...]:
    return (
        HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE,
        HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION,
        HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST,
    )


def _expected_interval_name_order() -> tuple[str, ...]:
    return HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES


def _expected_bar_alias_order() -> tuple[str, ...]:
    return HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_BAR_ALIASES


def _expected_window(window_name: str) -> tuple[datetime, datetime]:
    try:
        return _WINDOW_SPECS[window_name]
    except KeyError as exc:
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
            "window_name must be reference, validation, or test."
        ) from exc


def _expected_provider_qualification(logical_interval: str) -> HistoricalProviderQualification:
    try:
        bar_alias = _OBSERVATION_SPECS[logical_interval]["bar_alias"]
    except KeyError as exc:
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
            "interval must be 15m, 1h, or 4h."
        ) from exc
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


def _require_provider_qualifications(
    qualifications: Sequence[HistoricalProviderQualification],
) -> tuple[HistoricalProviderQualification, ...]:
    if not isinstance(qualifications, Sequence):
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
            "provider_qualifications must be a sequence."
        )
    items = tuple(qualifications)
    if len(items) != len(HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES):
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
            "provider_qualifications must contain three interval qualifications."
        )
    normalized: list[HistoricalProviderQualification] = []
    for index, expected_interval in enumerate(HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES):
        expected_bar_alias = _OBSERVATION_SPECS[expected_interval]["bar_alias"]
        item = items[index]
        if not isinstance(item, HistoricalProviderQualification):
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider_qualifications must contain HistoricalProviderQualification instances."
            )
        if item.provider_id != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_ID:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider qualification provider_id diverges from the OKX candidate."
            )
        if item.provider_version != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_VERSION:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider qualification provider_version diverges from the OKX candidate."
            )
        if item.market_type != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_MARKET_TYPE:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider qualification market_type must remain spot."
            )
        if item.exchange != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider qualification exchange must remain OKX."
            )
        if item.symbol != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SYMBOL:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider qualification symbol must remain BTCUSDT."
            )
        if item.interval != expected_bar_alias:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider qualification intervals must remain 15m, 1H, and 4H."
            )
        if item.time_semantics != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_TIME_SEMANTICS:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider qualification time_semantics must remain utc."
            )
        if item.access_type != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ACCESS_TYPE:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider qualification access_type must remain public_no_auth."
            )
        if item.data_contract_version != 2:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider qualification data_contract_version must remain 2."
            )
        if item.external_symbol != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider qualification external_symbol must remain BTC-USDT."
            )
        if item.endpoint_url != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_URL:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider qualification endpoint_url diverges from the OKX candidate."
            )
        if item.documentation_url != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider qualification documentation_url diverges from the OKX candidate."
            )
        if item.pagination_limit != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PAGINATION_LIMIT:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider qualification pagination_limit diverges from the OKX candidate."
            )
        if item.close_time_rule != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider qualification close_time_rule diverges from the OKX candidate."
            )
        normalized.append(item)
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketExtendedOperationalQualificationWindow:
    window_name: str
    start_utc: datetime
    end_utc: datetime
    schema_version: int = HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION
    window_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_name", _require_str(self.window_name, "window_name").lower())
        object.__setattr__(self, "start_utc", _require_utc_datetime(self.start_utc, "start_utc"))
        object.__setattr__(self, "end_utc", _require_utc_datetime(self.end_utc, "end_utc"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "window schema_version must be 1."
            )
        expected_start, expected_end = _expected_window(self.window_name)
        if self.start_utc != expected_start or self.end_utc != expected_end:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "frozen window bounds diverge from the declared Phase 18C evidence."
            )
        if self.end_utc <= self.start_utc:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "window end must be after window start."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.window_hash:
            if self.window_hash != expected:
                raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("window hash mismatch.")
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketExtendedOperationalQualificationWindow":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("window must be a mapping.")
        mapping = dict(data)
        try:
            _validate_exact_keys(
                mapping,
                allowed={"schema_version", "window_name", "start_utc", "end_utc", "window_hash"},
                name="window",
            )
            return cls(
                schema_version=mapping["schema_version"],
                window_name=mapping["window_name"],
                start_utc=mapping["start_utc"],
                end_utc=mapping["end_utc"],
                window_hash=mapping.get("window_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("window is incomplete.") from exc
        except HistoricalFuturesMarketExtendedOperationalQualificationValidationError as exc:
            raise HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketExtendedOperationalQualificationObservation:
    provider_qualification: HistoricalProviderQualification
    interval_name: str
    bar_alias: str
    candle_count: int
    first_candle_open_utc: datetime
    last_candle_open_utc: datetime
    duplicate_count: int
    gap_count: int
    page_count: int
    pagination_limit: int
    all_confirm_closed: bool
    incomplete_candle_confirm_observed: bool
    before_returns_newer_candles: bool
    after_observed_as_pagination_mechanism: bool
    utc_time_semantics: str
    schema_version: int = HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION
    observation_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.provider_qualification, HistoricalProviderQualification):
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider_qualification must be a HistoricalProviderQualification instance."
            )
        object.__setattr__(self, "interval_name", _require_str(self.interval_name, "interval_name").lower())
        object.__setattr__(self, "bar_alias", _require_str(self.bar_alias, "bar_alias"))
        expected_provider_qualification = _expected_provider_qualification(self.interval_name)
        if self.provider_qualification != expected_provider_qualification:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
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
        if self.schema_version != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "observation schema_version must be 1."
            )
        if self.bar_alias != _OBSERVATION_SPECS[self.interval_name]["bar_alias"]:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "bar_alias diverges from the declared Phase 18C evidence."
            )
        expected = _OBSERVATION_SPECS[self.interval_name]
        if self.candle_count != expected["candle_count"]:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "candle_count diverges from the declared evidence."
            )
        if self.first_candle_open_utc != expected["first_candle_open_utc"]:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "first_candle_open_utc diverges from the declared evidence."
            )
        if self.last_candle_open_utc != expected["last_candle_open_utc"]:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "last_candle_open_utc diverges from the declared evidence."
            )
        if self.duplicate_count != expected["duplicate_count"]:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "duplicate_count diverges from the declared evidence."
            )
        if self.gap_count != expected["gap_count"]:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "gap_count diverges from the declared evidence."
            )
        if self.page_count != expected["page_count"]:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "page_count diverges from the declared evidence."
            )
        if self.pagination_limit != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PAGINATION_LIMIT:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "pagination_limit diverges from the declared evidence."
            )
        if self.all_confirm_closed is not True:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "all_confirm_closed must remain true for the observed historical windows."
            )
        if self.incomplete_candle_confirm_observed is not True:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "incomplete_candle_confirm_observed must remain true."
            )
        if self.before_returns_newer_candles is not True:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "before_returns_newer_candles must remain true."
            )
        if self.after_observed_as_pagination_mechanism is not True:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "after_observed_as_pagination_mechanism must remain true."
            )
        if self.utc_time_semantics != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_TIME_SEMANTICS:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "utc_time_semantics must remain utc."
            )
        if self.last_candle_open_utc < self.first_candle_open_utc:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "last_candle_open_utc must not precede first_candle_open_utc."
            )
        expected_hash = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.observation_hash:
            if self.observation_hash != expected_hash:
                raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                    "observation hash mismatch."
                )
        else:
            object.__setattr__(self, "observation_hash", expected_hash)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "provider_qualification": self.provider_qualification.as_dict(),
            "interval_name": self.interval_name,
            "bar_alias": self.bar_alias,
            "candle_count": self.candle_count,
            "first_candle_open_utc": _utc_iso(self.first_candle_open_utc),
            "last_candle_open_utc": _utc_iso(self.last_candle_open_utc),
            "duplicate_count": self.duplicate_count,
            "gap_count": self.gap_count,
            "page_count": self.page_count,
            "pagination_limit": self.pagination_limit,
            "all_confirm_closed": self.all_confirm_closed,
            "incomplete_candle_confirm_observed": self.incomplete_candle_confirm_observed,
            "before_returns_newer_candles": self.before_returns_newer_candles,
            "after_observed_as_pagination_mechanism": self.after_observed_as_pagination_mechanism,
            "utc_time_semantics": self.utc_time_semantics,
        }
        if include_hash:
            payload["observation_hash"] = self.observation_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketExtendedOperationalQualificationObservation":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("observation must be a mapping.")
        mapping = dict(data)
        try:
            _validate_exact_keys(
                mapping,
                allowed={
                    "schema_version",
                    "provider_qualification",
                    "interval_name",
                    "bar_alias",
                    "candle_count",
                    "first_candle_open_utc",
                    "last_candle_open_utc",
                    "duplicate_count",
                    "gap_count",
                    "page_count",
                    "pagination_limit",
                    "all_confirm_closed",
                    "incomplete_candle_confirm_observed",
                    "before_returns_newer_candles",
                    "after_observed_as_pagination_mechanism",
                    "utc_time_semantics",
                    "observation_hash",
                },
                name="observation",
            )
            return cls(
                schema_version=mapping["schema_version"],
                provider_qualification=HistoricalProviderQualification.from_dict(mapping["provider_qualification"]),
                interval_name=mapping["interval_name"],
                bar_alias=mapping["bar_alias"],
                candle_count=mapping["candle_count"],
                first_candle_open_utc=mapping["first_candle_open_utc"],
                last_candle_open_utc=mapping["last_candle_open_utc"],
                duplicate_count=mapping["duplicate_count"],
                gap_count=mapping["gap_count"],
                page_count=mapping["page_count"],
                pagination_limit=mapping["pagination_limit"],
                all_confirm_closed=mapping["all_confirm_closed"],
                incomplete_candle_confirm_observed=mapping["incomplete_candle_confirm_observed"],
                before_returns_newer_candles=mapping["before_returns_newer_candles"],
                after_observed_as_pagination_mechanism=mapping["after_observed_as_pagination_mechanism"],
                utc_time_semantics=mapping["utc_time_semantics"],
                observation_hash=mapping.get("observation_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "observation is incomplete."
            ) from exc
        except HistoricalFuturesMarketExtendedOperationalQualificationValidationError as exc:
            raise HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketExtendedOperationalQualificationProtocol:
    coverage_start_utc: datetime
    coverage_end_utc: datetime
    frozen_window_names: tuple[str, ...]
    frozen_window_hashes: tuple[str, ...]
    interval_names: tuple[str, ...]
    bar_aliases: tuple[str, ...]
    interval_observation_hashes: tuple[str, ...]
    provider_qualification_hashes: tuple[str, ...]
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
    operational_evidence_status: str
    coverage_scope_statement: str
    non_ingestion_scope_statement: str
    pagination_behavior_statement: str
    risk_notes: tuple[str, ...]
    window_count: int
    interval_count: int
    provider_qualification_count: int
    page_count: int
    candle_count: int
    duplicate_count: int
    gap_count: int
    schema_version: int = HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION
    protocol_name: str = HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_PROTOCOL_NAME
    protocol_version: str = HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_PROTOCOL_VERSION
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
        if not isinstance(self.bar_aliases, tuple):
            object.__setattr__(self, "bar_aliases", tuple(self.bar_aliases))
        if not isinstance(self.interval_observation_hashes, tuple):
            object.__setattr__(self, "interval_observation_hashes", tuple(self.interval_observation_hashes))
        if not isinstance(self.provider_qualification_hashes, tuple):
            object.__setattr__(self, "provider_qualification_hashes", tuple(self.provider_qualification_hashes))
        if not isinstance(self.risk_notes, tuple):
            object.__setattr__(self, "risk_notes", tuple(self.risk_notes))
        object.__setattr__(self, "frozen_window_names", tuple(_require_str(item, "frozen_window_name").lower() for item in self.frozen_window_names))
        object.__setattr__(self, "frozen_window_hashes", tuple(_require_str(item, "frozen_window_hash") for item in self.frozen_window_hashes))
        object.__setattr__(self, "interval_names", tuple(_require_str(item, "interval_name").lower() for item in self.interval_names))
        object.__setattr__(self, "bar_aliases", tuple(_require_str(item, "bar_alias") for item in self.bar_aliases))
        object.__setattr__(self, "interval_observation_hashes", tuple(_require_str(item, "interval_observation_hash") for item in self.interval_observation_hashes))
        object.__setattr__(self, "provider_qualification_hashes", tuple(_require_str(item, "provider_qualification_hash") for item in self.provider_qualification_hashes))
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
        object.__setattr__(self, "operational_evidence_status", _require_str(self.operational_evidence_status, "operational_evidence_status"))
        object.__setattr__(self, "coverage_scope_statement", _require_str(self.coverage_scope_statement, "coverage_scope_statement"))
        object.__setattr__(self, "non_ingestion_scope_statement", _require_str(self.non_ingestion_scope_statement, "non_ingestion_scope_statement"))
        object.__setattr__(self, "pagination_behavior_statement", _require_str(self.pagination_behavior_statement, "pagination_behavior_statement"))
        object.__setattr__(self, "window_count", _require_int(self.window_count, "window_count"))
        object.__setattr__(self, "interval_count", _require_int(self.interval_count, "interval_count"))
        object.__setattr__(self, "provider_qualification_count", _require_int(self.provider_qualification_count, "provider_qualification_count"))
        object.__setattr__(self, "page_count", _require_int(self.page_count, "page_count"))
        object.__setattr__(self, "candle_count", _require_int(self.candle_count, "candle_count"))
        object.__setattr__(self, "duplicate_count", _require_int(self.duplicate_count, "duplicate_count", allow_zero=True))
        object.__setattr__(self, "gap_count", _require_int(self.gap_count, "gap_count", allow_zero=True))
        object.__setattr__(self, "protocol_name", _require_str(self.protocol_name, "protocol_name"))
        object.__setattr__(self, "protocol_version", _require_str(self.protocol_version, "protocol_version"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "extended operational qualification schema_version must be 1."
            )
        if self.protocol_name != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_PROTOCOL_NAME:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "protocol_name diverges from the trusted extended operational qualification contract."
            )
        if self.protocol_version != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_PROTOCOL_VERSION:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "protocol_version diverges from the trusted extended operational qualification contract."
            )
        if self.canonical_source_name != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_NAME:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "canonical_source_name must remain KuCoin spot."
            )
        if self.canonical_source_provider_id != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "canonical_source_provider_id must remain the KuCoin provider id."
            )
        if self.candidate_source_name != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SOURCE_NAME:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "candidate_source_name must remain OKX spot."
            )
        if self.candidate_provider_id != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_ID:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "candidate_provider_id must remain the OKX provider id."
            )
        if self.candidate_market_type != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_MARKET_TYPE:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "candidate_market_type must remain spot."
            )
        if self.candidate_symbol != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SYMBOL:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "candidate_symbol must remain BTCUSDT."
            )
        if self.candidate_external_symbol != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "candidate_external_symbol must remain BTC-USDT."
            )
        if self.candidate_time_semantics != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_TIME_SEMANTICS:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "candidate_time_semantics must remain utc."
            )
        if self.candidate_access_type != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ACCESS_TYPE:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "candidate_access_type must remain public_no_auth."
            )
        if self.candidate_provider_version != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_VERSION:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "candidate_provider_version must remain v1."
            )
        if self.candidate_provider_exchange != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "candidate_provider_exchange must remain okx."
            )
        if self.candidate_endpoint_url != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_URL:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "candidate_endpoint_url diverges from the declared evidence."
            )
        if self.candidate_documentation_url != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "candidate_documentation_url diverges from the declared evidence."
            )
        if self.candidate_endpoint_path != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_PATH:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "candidate_endpoint_path diverges from the declared evidence."
            )
        if self.operational_evidence_status != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_STATUS:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "operational_evidence_status diverges from the declared evidence."
            )
        if self.coverage_scope_statement != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "coverage_scope_statement diverges from the declared evidence."
            )
        if self.non_ingestion_scope_statement != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "non_ingestion_scope_statement diverges from the declared evidence."
            )
        if self.pagination_behavior_statement != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "pagination_behavior_statement diverges from the declared evidence."
            )
        if self.risk_notes != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_RISK_NOTES:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "risk_notes diverge from the declared evidence."
            )
        if self.window_count != 3:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("window_count must be exactly three.")
        if self.interval_count != 3:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("interval_count must be exactly three.")
        if self.provider_qualification_count != 3:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider_qualification_count must be exactly three."
            )
        if self.page_count != 10:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("page_count must be exactly ten.")
        if self.candle_count != 105:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("candle_count must be exactly 105.")
        if self.duplicate_count != 0:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("duplicate_count must remain zero.")
        if self.gap_count != 0:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("gap_count must remain zero.")
        if self.frozen_window_names != _expected_window_name_order():
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "frozen_window_names must remain reference, validation, test."
            )
        if self.interval_names != _expected_interval_name_order():
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "interval_names must remain 15m, 1h, 4h."
            )
        if self.bar_aliases != _expected_bar_alias_order():
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "bar_aliases must remain 15m, 1H, 4H."
            )
        if len(self.frozen_window_hashes) != 3:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "frozen_window_hashes must contain three window hashes."
            )
        if len(self.interval_observation_hashes) != 3:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "interval_observation_hashes must contain three observation hashes."
            )
        if len(self.provider_qualification_hashes) != 3:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider_qualification_hashes must contain three qualification hashes."
            )
        if self.coverage_start_utc > self.coverage_end_utc:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "coverage_end_utc must be after coverage_start_utc."
            )
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.protocol_hash:
            if self.protocol_hash != expected:
                raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("protocol hash mismatch.")
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
            "bar_aliases": list(self.bar_aliases),
            "interval_observation_hashes": list(self.interval_observation_hashes),
            "provider_qualification_hashes": list(self.provider_qualification_hashes),
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
            "operational_evidence_status": self.operational_evidence_status,
            "coverage_scope_statement": self.coverage_scope_statement,
            "non_ingestion_scope_statement": self.non_ingestion_scope_statement,
            "pagination_behavior_statement": self.pagination_behavior_statement,
            "risk_notes": list(self.risk_notes),
            "window_count": self.window_count,
            "interval_count": self.interval_count,
            "provider_qualification_count": self.provider_qualification_count,
            "page_count": self.page_count,
            "candle_count": self.candle_count,
            "duplicate_count": self.duplicate_count,
            "gap_count": self.gap_count,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketExtendedOperationalQualificationProtocol":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "extended operational qualification protocol must be a mapping."
            )
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
                    "frozen_window_names",
                    "frozen_window_hashes",
                    "interval_names",
                    "bar_aliases",
                    "interval_observation_hashes",
                    "provider_qualification_hashes",
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
                    "operational_evidence_status",
                    "coverage_scope_statement",
                    "non_ingestion_scope_statement",
                    "pagination_behavior_statement",
                    "risk_notes",
                    "window_count",
                    "interval_count",
                    "provider_qualification_count",
                    "page_count",
                    "candle_count",
                    "duplicate_count",
                    "gap_count",
                    "historical_research_only",
                    "operational_evidence",
                    "paper_promotion_eligible",
                    "protocol_hash",
                },
                name="extended operational qualification protocol",
            )
            return cls(
                schema_version=mapping["schema_version"],
                protocol_name=mapping["protocol_name"],
                protocol_version=mapping["protocol_version"],
                coverage_start_utc=mapping["coverage_start_utc"],
                coverage_end_utc=mapping["coverage_end_utc"],
                frozen_window_names=tuple(mapping["frozen_window_names"]),
                frozen_window_hashes=tuple(mapping["frozen_window_hashes"]),
                interval_names=tuple(mapping["interval_names"]),
                bar_aliases=tuple(mapping["bar_aliases"]),
                interval_observation_hashes=tuple(mapping["interval_observation_hashes"]),
                provider_qualification_hashes=tuple(mapping["provider_qualification_hashes"]),
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
                operational_evidence_status=mapping["operational_evidence_status"],
                coverage_scope_statement=mapping["coverage_scope_statement"],
                non_ingestion_scope_statement=mapping["non_ingestion_scope_statement"],
                pagination_behavior_statement=mapping["pagination_behavior_statement"],
                risk_notes=tuple(mapping["risk_notes"]),
                window_count=mapping["window_count"],
                interval_count=mapping["interval_count"],
                provider_qualification_count=mapping["provider_qualification_count"],
                page_count=mapping["page_count"],
                candle_count=mapping["candle_count"],
                duplicate_count=mapping["duplicate_count"],
                gap_count=mapping["gap_count"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                protocol_hash=mapping.get("protocol_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "extended operational qualification protocol is incomplete."
            ) from exc
        except HistoricalFuturesMarketExtendedOperationalQualificationValidationError as exc:
            raise HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketExtendedOperationalQualificationSummary:
    window_count: int
    interval_count: int
    provider_qualification_count: int
    candle_count: int
    duplicate_count: int
    gap_count: int
    page_count: int
    all_confirm_closed: bool
    incomplete_candle_confirm_observed: bool
    operational_evidence_status: str
    coverage_scope_statement: str
    non_ingestion_scope_statement: str
    pagination_behavior_statement: str
    risk_notes: tuple[str, ...]
    schema_version: int = HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION
    summary_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_count", _require_int(self.window_count, "window_count"))
        object.__setattr__(self, "interval_count", _require_int(self.interval_count, "interval_count"))
        object.__setattr__(self, "provider_qualification_count", _require_int(self.provider_qualification_count, "provider_qualification_count"))
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
        object.__setattr__(self, "operational_evidence_status", _require_str(self.operational_evidence_status, "operational_evidence_status"))
        object.__setattr__(self, "coverage_scope_statement", _require_str(self.coverage_scope_statement, "coverage_scope_statement"))
        object.__setattr__(self, "non_ingestion_scope_statement", _require_str(self.non_ingestion_scope_statement, "non_ingestion_scope_statement"))
        object.__setattr__(self, "pagination_behavior_statement", _require_str(self.pagination_behavior_statement, "pagination_behavior_statement"))
        if not isinstance(self.risk_notes, tuple):
            object.__setattr__(self, "risk_notes", tuple(self.risk_notes))
        object.__setattr__(self, "risk_notes", tuple(_require_str(item, "risk_note") for item in self.risk_notes))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "summary schema_version must be 1."
            )
        if self.window_count != 3:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("window_count must be exactly three.")
        if self.interval_count != 3:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("interval_count must be exactly three.")
        if self.provider_qualification_count != 3:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "provider_qualification_count must be exactly three."
            )
        if self.candle_count != 105:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("candle_count must be exactly 105.")
        if self.duplicate_count != 0:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("duplicate_count must remain zero.")
        if self.gap_count != 0:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("gap_count must remain zero.")
        if self.page_count != 10:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("page_count must be exactly ten.")
        if self.all_confirm_closed is not True:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "all_confirm_closed must remain true."
            )
        if self.incomplete_candle_confirm_observed is not True:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "incomplete_candle_confirm_observed must remain true."
            )
        if self.operational_evidence_status != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_STATUS:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "operational_evidence_status diverges from the declared evidence."
            )
        if self.coverage_scope_statement != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "coverage_scope_statement diverges from the declared evidence."
            )
        if self.non_ingestion_scope_statement != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "non_ingestion_scope_statement diverges from the declared evidence."
            )
        if self.pagination_behavior_statement != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "pagination_behavior_statement diverges from the declared evidence."
            )
        if self.risk_notes != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_RISK_NOTES:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "risk_notes diverge from the declared evidence."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.summary_hash:
            if self.summary_hash != expected:
                raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("summary hash mismatch.")
        else:
            object.__setattr__(self, "summary_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "window_count": self.window_count,
            "interval_count": self.interval_count,
            "provider_qualification_count": self.provider_qualification_count,
            "candle_count": self.candle_count,
            "duplicate_count": self.duplicate_count,
            "gap_count": self.gap_count,
            "page_count": self.page_count,
            "all_confirm_closed": self.all_confirm_closed,
            "incomplete_candle_confirm_observed": self.incomplete_candle_confirm_observed,
            "operational_evidence_status": self.operational_evidence_status,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketExtendedOperationalQualificationSummary":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("summary must be a mapping.")
        mapping = dict(data)
        try:
            _validate_exact_keys(
                mapping,
                allowed={
                    "schema_version",
                    "window_count",
                    "interval_count",
                    "provider_qualification_count",
                    "candle_count",
                    "duplicate_count",
                    "gap_count",
                    "page_count",
                    "all_confirm_closed",
                    "incomplete_candle_confirm_observed",
                    "operational_evidence_status",
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
                window_count=mapping["window_count"],
                interval_count=mapping["interval_count"],
                provider_qualification_count=mapping["provider_qualification_count"],
                candle_count=mapping["candle_count"],
                duplicate_count=mapping["duplicate_count"],
                gap_count=mapping["gap_count"],
                page_count=mapping["page_count"],
                all_confirm_closed=mapping["all_confirm_closed"],
                incomplete_candle_confirm_observed=mapping["incomplete_candle_confirm_observed"],
                operational_evidence_status=mapping["operational_evidence_status"],
                coverage_scope_statement=mapping["coverage_scope_statement"],
                non_ingestion_scope_statement=mapping["non_ingestion_scope_statement"],
                pagination_behavior_statement=mapping["pagination_behavior_statement"],
                risk_notes=tuple(mapping["risk_notes"]),
                summary_hash=mapping.get("summary_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("summary is incomplete.") from exc
        except HistoricalFuturesMarketExtendedOperationalQualificationValidationError as exc:
            raise HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketExtendedOperationalQualificationReport:
    protocol: HistoricalFuturesMarketExtendedOperationalQualificationProtocol
    frozen_windows: tuple[HistoricalFuturesMarketExtendedOperationalQualificationWindow, ...]
    interval_observations: tuple[HistoricalFuturesMarketExtendedOperationalQualificationObservation, ...]
    summary: HistoricalFuturesMarketExtendedOperationalQualificationSummary
    schema_version: int = HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    report_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.protocol, HistoricalFuturesMarketExtendedOperationalQualificationProtocol):
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "protocol must be an extended operational qualification protocol instance."
            )
        if not isinstance(self.summary, HistoricalFuturesMarketExtendedOperationalQualificationSummary):
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "summary must be an extended operational qualification summary instance."
            )
        if not isinstance(self.frozen_windows, tuple):
            object.__setattr__(self, "frozen_windows", tuple(self.frozen_windows))
        if not isinstance(self.interval_observations, tuple):
            object.__setattr__(self, "interval_observations", tuple(self.interval_observations))
        if len(self.frozen_windows) != 3:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "frozen_windows must contain exactly three windows."
            )
        if len(self.interval_observations) != 3:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "interval_observations must contain exactly three observations."
            )
        window_names = tuple(window.window_name for window in self.frozen_windows)
        if window_names != _expected_window_name_order():
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "frozen_windows must preserve reference, validation, test order."
            )
        interval_names = tuple(observation.interval_name for observation in self.interval_observations)
        if interval_names != _expected_interval_name_order():
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "interval_observations must preserve 15m, 1h, 4h order."
            )
        bar_aliases = tuple(observation.bar_alias for observation in self.interval_observations)
        if bar_aliases != _expected_bar_alias_order():
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "interval_observations must preserve 15m, 1H, 4H bar aliases."
            )
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        if self.schema_version != HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "extended operational qualification report schema_version must be 1."
            )
        expected_protocol = _build_protocol(self.frozen_windows, self.interval_observations, self.summary, self)
        if self.protocol != expected_protocol:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "extended operational qualification protocol diverges from the declared evidence."
            )
        expected_summary = _build_summary(self.frozen_windows, self.interval_observations, self)
        if self.summary != expected_summary:
            raise HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError(
                "extended operational qualification summary diverges from the declared evidence."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.report_hash:
            if self.report_hash != expected:
                raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError("report hash mismatch.")
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketExtendedOperationalQualificationReport":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "extended operational qualification report must be a mapping."
            )
        mapping = dict(data)
        try:
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
                name="extended operational qualification report",
            )
            return cls(
                schema_version=mapping["schema_version"],
                protocol=HistoricalFuturesMarketExtendedOperationalQualificationProtocol.from_dict(mapping["protocol"]),
                frozen_windows=tuple(
                    HistoricalFuturesMarketExtendedOperationalQualificationWindow.from_dict(item)
                    for item in mapping["frozen_windows"]
                ),
                interval_observations=tuple(
                    HistoricalFuturesMarketExtendedOperationalQualificationObservation.from_dict(item)
                    for item in mapping["interval_observations"]
                ),
                summary=HistoricalFuturesMarketExtendedOperationalQualificationSummary.from_dict(mapping["summary"]),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                report_hash=mapping.get("report_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
                "extended operational qualification report is incomplete."
            ) from exc
        except (
            HistoricalFuturesMarketExtendedOperationalQualificationValidationError,
            HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError,
            HistoricalFuturesMarketExtendedOperationalQualificationError,
            HistoricalDataValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError(str(exc)) from exc


def _build_frozen_windows() -> tuple[HistoricalFuturesMarketExtendedOperationalQualificationWindow, ...]:
    return tuple(
        HistoricalFuturesMarketExtendedOperationalQualificationWindow(window_name=name, start_utc=start, end_utc=end)
        for name, (start, end) in _WINDOW_SPECS.items()
    )


def _build_provider_qualifications() -> tuple[HistoricalProviderQualification, ...]:
    return tuple(_expected_provider_qualification(interval) for interval in _expected_interval_name_order())


def _build_interval_observations() -> tuple[HistoricalFuturesMarketExtendedOperationalQualificationObservation, ...]:
    observations = []
    for interval_name in _expected_interval_name_order():
        spec = _OBSERVATION_SPECS[interval_name]
        observations.append(
            HistoricalFuturesMarketExtendedOperationalQualificationObservation(
                provider_qualification=_expected_provider_qualification(interval_name),
                interval_name=interval_name,
                bar_alias=spec["bar_alias"],
                candle_count=spec["candle_count"],
                first_candle_open_utc=spec["first_candle_open_utc"],
                last_candle_open_utc=spec["last_candle_open_utc"],
                duplicate_count=spec["duplicate_count"],
                gap_count=spec["gap_count"],
                page_count=spec["page_count"],
                pagination_limit=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PAGINATION_LIMIT,
                all_confirm_closed=True,
                incomplete_candle_confirm_observed=True,
                before_returns_newer_candles=True,
                after_observed_as_pagination_mechanism=True,
                utc_time_semantics=HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_TIME_SEMANTICS,
            )
        )
    return tuple(observations)


def _build_protocol(
    frozen_windows: Sequence[HistoricalFuturesMarketExtendedOperationalQualificationWindow],
    interval_observations: Sequence[HistoricalFuturesMarketExtendedOperationalQualificationObservation],
    summary: HistoricalFuturesMarketExtendedOperationalQualificationSummary | None = None,
    report: HistoricalFuturesMarketExtendedOperationalQualificationReport | None = None,
) -> HistoricalFuturesMarketExtendedOperationalQualificationProtocol:
    _ = summary
    _ = report
    provider_qualifications = tuple(observation.provider_qualification for observation in interval_observations)
    return HistoricalFuturesMarketExtendedOperationalQualificationProtocol(
        coverage_start_utc=frozen_windows[0].start_utc,
        coverage_end_utc=interval_observations[0].last_candle_open_utc,
        frozen_window_names=tuple(window.window_name for window in frozen_windows),
        frozen_window_hashes=tuple(window.window_hash for window in frozen_windows),
        interval_names=tuple(observation.interval_name for observation in interval_observations),
        bar_aliases=tuple(observation.bar_alias for observation in interval_observations),
        interval_observation_hashes=tuple(observation.observation_hash for observation in interval_observations),
        provider_qualification_hashes=tuple(qualification.qualification_hash for qualification in provider_qualifications),
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
        operational_evidence_status=HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_STATUS,
        coverage_scope_statement=HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT,
        non_ingestion_scope_statement=HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT,
        pagination_behavior_statement=HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT,
        risk_notes=HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_RISK_NOTES,
        window_count=len(frozen_windows),
        interval_count=len(interval_observations),
        provider_qualification_count=len(provider_qualifications),
        page_count=sum(observation.page_count for observation in interval_observations),
        candle_count=sum(observation.candle_count for observation in interval_observations),
        duplicate_count=sum(observation.duplicate_count for observation in interval_observations),
        gap_count=sum(observation.gap_count for observation in interval_observations),
    )


def _build_summary(
    frozen_windows: Sequence[HistoricalFuturesMarketExtendedOperationalQualificationWindow],
    interval_observations: Sequence[HistoricalFuturesMarketExtendedOperationalQualificationObservation],
    report: HistoricalFuturesMarketExtendedOperationalQualificationReport | None = None,
) -> HistoricalFuturesMarketExtendedOperationalQualificationSummary:
    _ = report
    return HistoricalFuturesMarketExtendedOperationalQualificationSummary(
        window_count=len(frozen_windows),
        interval_count=len(interval_observations),
        provider_qualification_count=len(interval_observations),
        candle_count=sum(item.candle_count for item in interval_observations),
        duplicate_count=sum(item.duplicate_count for item in interval_observations),
        gap_count=sum(item.gap_count for item in interval_observations),
        page_count=sum(item.page_count for item in interval_observations),
        all_confirm_closed=all(item.all_confirm_closed for item in interval_observations),
        incomplete_candle_confirm_observed=all(
            item.incomplete_candle_confirm_observed for item in interval_observations
        ),
        operational_evidence_status=HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_STATUS,
        coverage_scope_statement=HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT,
        non_ingestion_scope_statement=HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT,
        pagination_behavior_statement=HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT,
        risk_notes=HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_RISK_NOTES,
    )


def build_historical_futures_market_extended_operational_qualification_report(
    _: Any | None = None,
) -> HistoricalFuturesMarketExtendedOperationalQualificationReport:
    frozen_windows = _build_frozen_windows()
    interval_observations = _build_interval_observations()
    summary = _build_summary(frozen_windows, interval_observations)
    protocol = _build_protocol(frozen_windows, interval_observations, summary)
    report = HistoricalFuturesMarketExtendedOperationalQualificationReport(
        protocol=protocol,
        frozen_windows=frozen_windows,
        interval_observations=interval_observations,
        summary=summary,
    )
    protocol = _build_protocol(frozen_windows, interval_observations, summary, report)
    return HistoricalFuturesMarketExtendedOperationalQualificationReport(
        protocol=protocol,
        frozen_windows=frozen_windows,
        interval_observations=interval_observations,
        summary=summary,
    )


def run_historical_futures_market_extended_operational_qualification(
    _: Any | None = None,
    *,
    output_file: str | Path | None = None,
) -> HistoricalFuturesMarketExtendedOperationalQualificationReport:
    report = build_historical_futures_market_extended_operational_qualification_report()
    if output_file is not None:
        save_historical_futures_market_extended_operational_qualification_report(output_file, report)
    return report


def _read(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
            "extended operational qualification report not found."
        ) from exc
    except Exception as exc:
        raise HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError(
            "extended operational qualification report is invalid JSON."
        ) from exc
    if not isinstance(value, Mapping):
        raise HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError(
            "extended operational qualification report must be a JSON object."
        )
    return value


def load_historical_futures_market_extended_operational_qualification_report(
    path: str | Path,
) -> HistoricalFuturesMarketExtendedOperationalQualificationReport:
    payload = _read(Path(path))
    try:
        report = HistoricalFuturesMarketExtendedOperationalQualificationReport.from_dict(payload)
    except (
        KeyError,
        TypeError,
        ValueError,
        HistoricalFuturesMarketExtendedOperationalQualificationValidationError,
        HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError,
        HistoricalDataValidationError,
    ) as exc:
        raise HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError(str(exc)) from exc
    if report.as_dict() != payload:
        raise HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError(
            "extended operational qualification report payload mismatch."
        )
    return report


def save_historical_futures_market_extended_operational_qualification_report(
    path: str | Path,
    report: HistoricalFuturesMarketExtendedOperationalQualificationReport,
) -> HistoricalFuturesMarketExtendedOperationalQualificationReport:
    file_path = Path(path)
    payload = report.as_dict()
    if file_path.exists():
        existing = load_historical_futures_market_extended_operational_qualification_report(file_path)
        if existing.as_dict() != payload:
            raise HistoricalFuturesMarketExtendedOperationalQualificationConflictError(
                "extended operational qualification report already exists and differs."
            )
        return existing
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_name(f".{file_path.name}.{os.getpid()}.{id(report)}.tmp")
    try:
        tmp.write_text(_canonical_json(payload), encoding="utf-8")
        try:
            os.link(tmp, file_path)
        except FileExistsError:
            existing = load_historical_futures_market_extended_operational_qualification_report(file_path)
            if existing.as_dict() != payload:
                raise HistoricalFuturesMarketExtendedOperationalQualificationConflictError(
                    "extended operational qualification report already exists and differs."
                )
            return existing
    except Exception as exc:
        if isinstance(exc, HistoricalFuturesMarketExtendedOperationalQualificationConflictError):
            raise
        raise HistoricalFuturesMarketExtendedOperationalQualificationValidationError(
            "failed to write extended operational qualification report atomically."
        ) from exc
    finally:
        tmp.unlink(missing_ok=True)
    return report


def verify_historical_futures_market_extended_operational_qualification_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_extended_operational_qualification_report(path)
    return {
        "verified": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "summary_hash": report.summary.summary_hash,
        "classification": HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_STATUS,
        "operational_evidence_status": report.protocol.operational_evidence_status,
        "window_count": report.protocol.window_count,
        "interval_count": report.protocol.interval_count,
        "provider_qualification_count": report.protocol.provider_qualification_count,
        "page_count": report.summary.page_count,
        "candle_count": report.summary.candle_count,
        "all_confirm_closed": report.summary.all_confirm_closed,
    }


def status_historical_futures_market_extended_operational_qualification_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_extended_operational_qualification_report(path)
    summary = report.summary
    return {
        "exists": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "summary_hash": summary.summary_hash,
        "window_count": summary.window_count,
        "interval_count": summary.interval_count,
        "provider_qualification_count": summary.provider_qualification_count,
        "candle_count": summary.candle_count,
        "duplicate_count": summary.duplicate_count,
        "gap_count": summary.gap_count,
        "page_count": summary.page_count,
        "all_confirm_closed": summary.all_confirm_closed,
        "incomplete_candle_confirm_observed": summary.incomplete_candle_confirm_observed,
        "operational_evidence_status": summary.operational_evidence_status,
        "coverage_scope_statement": summary.coverage_scope_statement,
        "non_ingestion_scope_statement": summary.non_ingestion_scope_statement,
        "pagination_behavior_statement": summary.pagination_behavior_statement,
    }


def reject_historical_futures_market_extended_operational_qualification_promotion(
    _: HistoricalFuturesMarketExtendedOperationalQualificationReport,
) -> None:
    raise HistoricalFuturesMarketExtendedOperationalQualificationPromotionError(
        "historical futures extended operational qualification is not promotion evidence."
    )
