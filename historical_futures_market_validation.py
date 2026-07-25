"""Research-only temporal validation for the Phase 14A historical futures contract.

This module consumes the immutable Phase 14A market contract together with the
Phase 13B/13C/13D historical artifact chain embedded in the multi-timeframe
analysis report. It produces a canonical windowed validation report without
touching paper, live, order execution, or operational storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value
from historical_futures_market_contract import (
    HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE,
    HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST,
    HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION,
    HistoricalFuturesMarketContract,
    HistoricalFuturesMarketContractValidationError,
)
from historical_multitimeframe_analysis import (
    HistoricalMultiTimeframeStrategyAnalysisObservation,
    HistoricalMultiTimeframeStrategyAnalysisReport,
    HistoricalMultiTimeframeStrategyAnalysisValidationError,
)
from market_data import HistoricalDataValidationError

HISTORICAL_FUTURES_MARKET_VALIDATION_SCHEMA_VERSION = 1
HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES: tuple[str, ...] = (
    HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE,
    HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION,
    HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST,
)


class HistoricalFuturesMarketValidationError(Exception):
    pass


class HistoricalFuturesMarketValidationValidationError(HistoricalFuturesMarketValidationError):
    pass


class HistoricalFuturesMarketValidationIntegrityError(HistoricalFuturesMarketValidationValidationError):
    pass


class HistoricalFuturesMarketValidationConflictError(HistoricalFuturesMarketValidationIntegrityError):
    pass


class HistoricalFuturesMarketValidationPromotionError(HistoricalFuturesMarketValidationValidationError):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalFuturesMarketValidationValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalFuturesMarketValidationValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalFuturesMarketValidationValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalFuturesMarketValidationValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalFuturesMarketValidationValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalFuturesMarketValidationValidationError(f"{field_name} must be timezone-aware UTC datetime.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalFuturesMarketValidationValidationError(f"{field_name} must be timezone-aware UTC datetime.") from exc
    if not isinstance(value, datetime):
        raise HistoricalFuturesMarketValidationValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoricalFuturesMarketValidationValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise HistoricalFuturesMarketValidationValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _validate_exact_keys(mapping: Mapping[str, Any], *, allowed: set[str], name: str) -> None:
    extra = set(mapping) - allowed
    if extra:
        raise HistoricalFuturesMarketValidationValidationError(f"{name} contains unknown fields: {sorted(extra)!r}.")


def _research_only(historical_research_only: bool, operational_evidence: bool, paper_promotion_eligible: bool) -> None:
    if historical_research_only is not True:
        raise HistoricalFuturesMarketValidationValidationError("historical_research_only must be true.")
    if operational_evidence is not False:
        raise HistoricalFuturesMarketValidationValidationError("operational_evidence must be false.")
    if paper_promotion_eligible is not False:
        raise HistoricalFuturesMarketValidationValidationError("paper_promotion_eligible must be false.")


def _window_contains(window, decision_time_utc: datetime) -> bool:
    decision_time = _require_utc_datetime(decision_time_utc, "decision_time_utc")
    return window.start_utc <= decision_time <= window.end_utc


def _returns_for_observations(observations: Sequence[HistoricalMultiTimeframeStrategyAnalysisObservation]) -> list[Decimal]:
    return [
        item.gross_return_percent_without_costs
        for item in observations
        if item.status == "evaluated" and item.gross_return_percent_without_costs is not None
    ]


def _build_window_returns(
    observations: Sequence[HistoricalMultiTimeframeStrategyAnalysisObservation],
) -> tuple[int, int, int, int, int, Decimal, Decimal, Decimal, Decimal, int, int]:
    decision_count = len(observations)
    signal_count = sum(1 for item in observations if item.signal_generated)
    evaluated_returns = _returns_for_observations(observations)
    evaluated_operations = len(evaluated_returns)
    no_signal_decisions = sum(1 for item in observations if item.status == "no_signal")
    not_evaluable_entries = sum(1 for item in observations if item.status == "not_evaluable")
    if evaluated_operations:
        winning_operations = sum(1 for value in evaluated_returns if value > 0)
        win_rate_percent = (Decimal(winning_operations) / Decimal(evaluated_operations)) * Decimal("100")
        mean_return = sum(evaluated_returns, Decimal("0")) / Decimal(evaluated_operations)
        median_return = median(evaluated_returns)
        cumulative = sum(evaluated_returns, Decimal("0"))
    else:
        win_rate_percent = Decimal("0")
        mean_return = Decimal("0")
        median_return = Decimal("0")
        cumulative = Decimal("0")
    max_loss_streak = 0
    max_win_streak = 0
    loss_streak = 0
    win_streak = 0
    for value in evaluated_returns:
        if value < 0:
            loss_streak += 1
            win_streak = 0
            max_loss_streak = max(max_loss_streak, loss_streak)
        elif value > 0:
            win_streak += 1
            loss_streak = 0
            max_win_streak = max(max_win_streak, win_streak)
        else:
            loss_streak = 0
            win_streak = 0
    return (
        decision_count,
        signal_count,
        evaluated_operations,
        no_signal_decisions,
        not_evaluable_entries,
        win_rate_percent,
        mean_return,
        median_return,
        cumulative,
        max_loss_streak,
        max_win_streak,
    )


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketValidationWindowSummary:
    window_name: str
    start_utc: datetime
    end_utc: datetime
    window_hash: str
    decision_count: int
    signal_count: int
    evaluated_operations: int
    no_signal_decisions: int
    not_evaluable_entries: int
    win_rate_percent: Decimal
    mean_gross_return_percent_without_costs: Decimal
    median_gross_return_percent_without_costs: Decimal
    cumulative_simple_return_percent_without_costs: Decimal
    max_loss_streak: int
    max_win_streak: int
    schema_version: int = HISTORICAL_FUTURES_MARKET_VALIDATION_SCHEMA_VERSION
    summary_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_name", _require_str(self.window_name, "window_name").lower())
        object.__setattr__(self, "start_utc", _require_utc_datetime(self.start_utc, "start_utc"))
        object.__setattr__(self, "end_utc", _require_utc_datetime(self.end_utc, "end_utc"))
        object.__setattr__(self, "window_hash", _require_str(self.window_hash, "window_hash"))
        object.__setattr__(self, "decision_count", _require_int(self.decision_count, "decision_count", allow_zero=True))
        object.__setattr__(self, "signal_count", _require_int(self.signal_count, "signal_count", allow_zero=True))
        object.__setattr__(self, "evaluated_operations", _require_int(self.evaluated_operations, "evaluated_operations", allow_zero=True))
        object.__setattr__(self, "no_signal_decisions", _require_int(self.no_signal_decisions, "no_signal_decisions", allow_zero=True))
        object.__setattr__(self, "not_evaluable_entries", _require_int(self.not_evaluable_entries, "not_evaluable_entries", allow_zero=True))
        object.__setattr__(self, "win_rate_percent", Decimal(str(self.win_rate_percent)))
        object.__setattr__(self, "mean_gross_return_percent_without_costs", Decimal(str(self.mean_gross_return_percent_without_costs)))
        object.__setattr__(self, "median_gross_return_percent_without_costs", Decimal(str(self.median_gross_return_percent_without_costs)))
        object.__setattr__(self, "cumulative_simple_return_percent_without_costs", Decimal(str(self.cumulative_simple_return_percent_without_costs)))
        object.__setattr__(self, "max_loss_streak", _require_int(self.max_loss_streak, "max_loss_streak", allow_zero=True))
        object.__setattr__(self, "max_win_streak", _require_int(self.max_win_streak, "max_win_streak", allow_zero=True))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_VALIDATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketValidationValidationError("validation window summary schema_version must be 1.")
        if self.window_name not in HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES:
            raise HistoricalFuturesMarketValidationValidationError("window_name must be reference, validation, or test.")
        if self.end_utc < self.start_utc:
            raise HistoricalFuturesMarketValidationValidationError("window end must be after or equal to window start.")
        if self.decision_count != self.signal_count + self.no_signal_decisions:
            raise HistoricalFuturesMarketValidationValidationError("decision_count must equal signal_count plus no-signal decisions.")
        if self.signal_count != self.evaluated_operations + self.not_evaluable_entries:
            raise HistoricalFuturesMarketValidationValidationError("signal_count must equal evaluated plus not-evaluable entries.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.summary_hash:
            if self.summary_hash != expected:
                raise HistoricalFuturesMarketValidationValidationError("window summary hash mismatch.")
        else:
            object.__setattr__(self, "summary_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "window_name": self.window_name,
            "start_utc": _utc_iso(self.start_utc),
            "end_utc": _utc_iso(self.end_utc),
            "window_hash": self.window_hash,
            "decision_count": self.decision_count,
            "signal_count": self.signal_count,
            "evaluated_operations": self.evaluated_operations,
            "no_signal_decisions": self.no_signal_decisions,
            "not_evaluable_entries": self.not_evaluable_entries,
            "win_rate_percent": self.win_rate_percent,
            "mean_gross_return_percent_without_costs": self.mean_gross_return_percent_without_costs,
            "median_gross_return_percent_without_costs": self.median_gross_return_percent_without_costs,
            "cumulative_simple_return_percent_without_costs": self.cumulative_simple_return_percent_without_costs,
            "max_loss_streak": self.max_loss_streak,
            "max_win_streak": self.max_win_streak,
        }
        if include_hash:
            payload["summary_hash"] = self.summary_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketValidationWindowSummary":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketValidationValidationError("validation window summary must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "window_name",
                "start_utc",
                "end_utc",
                "window_hash",
                "decision_count",
                "signal_count",
                "evaluated_operations",
                "no_signal_decisions",
                "not_evaluable_entries",
                "win_rate_percent",
                "mean_gross_return_percent_without_costs",
                "median_gross_return_percent_without_costs",
                "cumulative_simple_return_percent_without_costs",
                "max_loss_streak",
                "max_win_streak",
                "summary_hash",
            },
            name="validation window summary",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                window_name=mapping["window_name"],
                start_utc=mapping["start_utc"],
                end_utc=mapping["end_utc"],
                window_hash=mapping["window_hash"],
                decision_count=mapping["decision_count"],
                signal_count=mapping["signal_count"],
                evaluated_operations=mapping["evaluated_operations"],
                no_signal_decisions=mapping["no_signal_decisions"],
                not_evaluable_entries=mapping["not_evaluable_entries"],
                win_rate_percent=mapping["win_rate_percent"],
                mean_gross_return_percent_without_costs=mapping["mean_gross_return_percent_without_costs"],
                median_gross_return_percent_without_costs=mapping["median_gross_return_percent_without_costs"],
                cumulative_simple_return_percent_without_costs=mapping["cumulative_simple_return_percent_without_costs"],
                max_loss_streak=mapping["max_loss_streak"],
                max_win_streak=mapping["max_win_streak"],
                summary_hash=mapping.get("summary_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketValidationValidationError("validation window summary is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketValidationSummary:
    window_count: int
    empty_window_count: int
    decision_count: int
    signal_count: int
    evaluated_operations: int
    no_signal_decisions: int
    not_evaluable_entries: int
    win_rate_percent: Decimal
    mean_gross_return_percent_without_costs: Decimal
    median_gross_return_percent_without_costs: Decimal
    cumulative_simple_return_percent_without_costs: Decimal
    max_loss_streak: int
    max_win_streak: int
    window_mean_return_spread_percent: Decimal
    window_win_rate_spread_percent: Decimal
    schema_version: int = HISTORICAL_FUTURES_MARKET_VALIDATION_SCHEMA_VERSION
    summary_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_count", _require_int(self.window_count, "window_count"))
        object.__setattr__(self, "empty_window_count", _require_int(self.empty_window_count, "empty_window_count", allow_zero=True))
        object.__setattr__(self, "decision_count", _require_int(self.decision_count, "decision_count", allow_zero=True))
        object.__setattr__(self, "signal_count", _require_int(self.signal_count, "signal_count", allow_zero=True))
        object.__setattr__(self, "evaluated_operations", _require_int(self.evaluated_operations, "evaluated_operations", allow_zero=True))
        object.__setattr__(self, "no_signal_decisions", _require_int(self.no_signal_decisions, "no_signal_decisions", allow_zero=True))
        object.__setattr__(self, "not_evaluable_entries", _require_int(self.not_evaluable_entries, "not_evaluable_entries", allow_zero=True))
        object.__setattr__(self, "win_rate_percent", Decimal(str(self.win_rate_percent)))
        object.__setattr__(self, "mean_gross_return_percent_without_costs", Decimal(str(self.mean_gross_return_percent_without_costs)))
        object.__setattr__(self, "median_gross_return_percent_without_costs", Decimal(str(self.median_gross_return_percent_without_costs)))
        object.__setattr__(self, "cumulative_simple_return_percent_without_costs", Decimal(str(self.cumulative_simple_return_percent_without_costs)))
        object.__setattr__(self, "max_loss_streak", _require_int(self.max_loss_streak, "max_loss_streak", allow_zero=True))
        object.__setattr__(self, "max_win_streak", _require_int(self.max_win_streak, "max_win_streak", allow_zero=True))
        object.__setattr__(self, "window_mean_return_spread_percent", Decimal(str(self.window_mean_return_spread_percent)))
        object.__setattr__(self, "window_win_rate_spread_percent", Decimal(str(self.window_win_rate_spread_percent)))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_VALIDATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketValidationValidationError("validation summary schema_version must be 1.")
        if self.window_count != 3:
            raise HistoricalFuturesMarketValidationValidationError("validation summary must cover three contract windows.")
        if self.decision_count != self.signal_count + self.no_signal_decisions:
            raise HistoricalFuturesMarketValidationValidationError("decision_count must equal signal_count plus no-signal decisions.")
        if self.signal_count != self.evaluated_operations + self.not_evaluable_entries:
            raise HistoricalFuturesMarketValidationValidationError("signal_count must equal evaluated plus not-evaluable entries.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.summary_hash:
            if self.summary_hash != expected:
                raise HistoricalFuturesMarketValidationValidationError("validation summary hash mismatch.")
        else:
            object.__setattr__(self, "summary_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "window_count": self.window_count,
            "empty_window_count": self.empty_window_count,
            "decision_count": self.decision_count,
            "signal_count": self.signal_count,
            "evaluated_operations": self.evaluated_operations,
            "no_signal_decisions": self.no_signal_decisions,
            "not_evaluable_entries": self.not_evaluable_entries,
            "win_rate_percent": self.win_rate_percent,
            "mean_gross_return_percent_without_costs": self.mean_gross_return_percent_without_costs,
            "median_gross_return_percent_without_costs": self.median_gross_return_percent_without_costs,
            "cumulative_simple_return_percent_without_costs": self.cumulative_simple_return_percent_without_costs,
            "max_loss_streak": self.max_loss_streak,
            "max_win_streak": self.max_win_streak,
            "window_mean_return_spread_percent": self.window_mean_return_spread_percent,
            "window_win_rate_spread_percent": self.window_win_rate_spread_percent,
        }
        if include_hash:
            payload["summary_hash"] = self.summary_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketValidationSummary":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketValidationValidationError("validation summary must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "window_count",
                "empty_window_count",
                "decision_count",
                "signal_count",
                "evaluated_operations",
                "no_signal_decisions",
                "not_evaluable_entries",
                "win_rate_percent",
                "mean_gross_return_percent_without_costs",
                "median_gross_return_percent_without_costs",
                "cumulative_simple_return_percent_without_costs",
                "max_loss_streak",
                "max_win_streak",
                "window_mean_return_spread_percent",
                "window_win_rate_spread_percent",
                "summary_hash",
            },
            name="validation summary",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                window_count=mapping["window_count"],
                empty_window_count=mapping["empty_window_count"],
                decision_count=mapping["decision_count"],
                signal_count=mapping["signal_count"],
                evaluated_operations=mapping["evaluated_operations"],
                no_signal_decisions=mapping["no_signal_decisions"],
                not_evaluable_entries=mapping["not_evaluable_entries"],
                win_rate_percent=mapping["win_rate_percent"],
                mean_gross_return_percent_without_costs=mapping["mean_gross_return_percent_without_costs"],
                median_gross_return_percent_without_costs=mapping["median_gross_return_percent_without_costs"],
                cumulative_simple_return_percent_without_costs=mapping["cumulative_simple_return_percent_without_costs"],
                max_loss_streak=mapping["max_loss_streak"],
                max_win_streak=mapping["max_win_streak"],
                window_mean_return_spread_percent=mapping["window_mean_return_spread_percent"],
                window_win_rate_spread_percent=mapping["window_win_rate_spread_percent"],
                summary_hash=mapping.get("summary_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketValidationValidationError("validation summary is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketValidationProtocol:
    contract_hash: str
    contract_temporal_split_hash: str
    analysis_report_hash: str
    evaluation_hash: str
    strategy_report_hash: str
    replay_hash: str
    bundle_hash: str
    source_hash: str
    coverage_start_utc: datetime
    coverage_end_utc: datetime
    reference_window_hash: str
    validation_window_hash: str
    test_window_hash: str
    window_count: int = 3
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    schema_version: int = HISTORICAL_FUTURES_MARKET_VALIDATION_SCHEMA_VERSION
    protocol_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_hash", _require_str(self.contract_hash, "contract_hash"))
        object.__setattr__(self, "contract_temporal_split_hash", _require_str(self.contract_temporal_split_hash, "contract_temporal_split_hash"))
        object.__setattr__(self, "analysis_report_hash", _require_str(self.analysis_report_hash, "analysis_report_hash"))
        object.__setattr__(self, "evaluation_hash", _require_str(self.evaluation_hash, "evaluation_hash"))
        object.__setattr__(self, "strategy_report_hash", _require_str(self.strategy_report_hash, "strategy_report_hash"))
        object.__setattr__(self, "replay_hash", _require_str(self.replay_hash, "replay_hash"))
        object.__setattr__(self, "bundle_hash", _require_str(self.bundle_hash, "bundle_hash"))
        object.__setattr__(self, "source_hash", _require_str(self.source_hash, "source_hash"))
        object.__setattr__(self, "coverage_start_utc", _require_utc_datetime(self.coverage_start_utc, "coverage_start_utc"))
        object.__setattr__(self, "coverage_end_utc", _require_utc_datetime(self.coverage_end_utc, "coverage_end_utc"))
        object.__setattr__(self, "reference_window_hash", _require_str(self.reference_window_hash, "reference_window_hash"))
        object.__setattr__(self, "validation_window_hash", _require_str(self.validation_window_hash, "validation_window_hash"))
        object.__setattr__(self, "test_window_hash", _require_str(self.test_window_hash, "test_window_hash"))
        object.__setattr__(self, "window_count", _require_int(self.window_count, "window_count"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_VALIDATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketValidationValidationError("validation protocol schema_version must be 1.")
        if self.window_count != len(HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES):
            raise HistoricalFuturesMarketValidationValidationError("validation protocol must cover three windows.")
        if self.coverage_end_utc <= self.coverage_start_utc:
            raise HistoricalFuturesMarketValidationValidationError("coverage_end_utc must be after coverage_start_utc.")
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.protocol_hash:
            if self.protocol_hash != expected:
                raise HistoricalFuturesMarketValidationValidationError("validation protocol hash mismatch.")
        else:
            object.__setattr__(self, "protocol_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "contract_hash": self.contract_hash,
            "contract_temporal_split_hash": self.contract_temporal_split_hash,
            "analysis_report_hash": self.analysis_report_hash,
            "evaluation_hash": self.evaluation_hash,
            "strategy_report_hash": self.strategy_report_hash,
            "replay_hash": self.replay_hash,
            "bundle_hash": self.bundle_hash,
            "source_hash": self.source_hash,
            "coverage_start_utc": _utc_iso(self.coverage_start_utc),
            "coverage_end_utc": _utc_iso(self.coverage_end_utc),
            "reference_window_hash": self.reference_window_hash,
            "validation_window_hash": self.validation_window_hash,
            "test_window_hash": self.test_window_hash,
            "window_count": self.window_count,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketValidationProtocol":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketValidationValidationError("validation protocol must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "contract_hash",
                "contract_temporal_split_hash",
                "analysis_report_hash",
                "evaluation_hash",
                "strategy_report_hash",
                "replay_hash",
                "bundle_hash",
                "source_hash",
                "coverage_start_utc",
                "coverage_end_utc",
                "reference_window_hash",
                "validation_window_hash",
                "test_window_hash",
                "window_count",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "protocol_hash",
            },
            name="validation protocol",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                contract_hash=mapping["contract_hash"],
                contract_temporal_split_hash=mapping["contract_temporal_split_hash"],
                analysis_report_hash=mapping["analysis_report_hash"],
                evaluation_hash=mapping["evaluation_hash"],
                strategy_report_hash=mapping["strategy_report_hash"],
                replay_hash=mapping["replay_hash"],
                bundle_hash=mapping["bundle_hash"],
                source_hash=mapping["source_hash"],
                coverage_start_utc=mapping["coverage_start_utc"],
                coverage_end_utc=mapping["coverage_end_utc"],
                reference_window_hash=mapping["reference_window_hash"],
                validation_window_hash=mapping["validation_window_hash"],
                test_window_hash=mapping["test_window_hash"],
                window_count=mapping["window_count"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                protocol_hash=mapping.get("protocol_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketValidationValidationError("validation protocol is incomplete.") from exc


def _contract_windows(contract: HistoricalFuturesMarketContract) -> tuple[Any, Any, Any]:
    temporal_split = contract.temporal_split_protocol
    return temporal_split.reference_window, temporal_split.validation_window, temporal_split.test_window


def _build_window_summaries(
    contract: HistoricalFuturesMarketContract,
    analysis_report: HistoricalMultiTimeframeStrategyAnalysisReport,
) -> tuple[HistoricalFuturesMarketValidationWindowSummary, ...]:
    windows = _contract_windows(contract)
    observations = analysis_report.observations
    grouped: dict[str, list[HistoricalMultiTimeframeStrategyAnalysisObservation]] = {
        window.window_name: [] for window in windows
    }
    for observation in observations:
        matches = [window for window in windows if _window_contains(window, observation.decision_time_utc)]
        if len(matches) != 1:
            raise HistoricalFuturesMarketValidationValidationError(
                "analysis observations diverge from the trusted temporal contract."
            )
        grouped[matches[0].window_name].append(observation)

    summaries: list[HistoricalFuturesMarketValidationWindowSummary] = []
    for window in windows:
        observations_in_window = grouped[window.window_name]
        (
            decision_count,
            signal_count,
            evaluated_operations,
            no_signal_decisions,
            not_evaluable_entries,
            win_rate_percent,
            mean_return,
            median_return,
            cumulative_return,
            max_loss_streak,
            max_win_streak,
        ) = _build_window_returns(observations_in_window)
        summaries.append(
            HistoricalFuturesMarketValidationWindowSummary(
                window_name=window.window_name,
                start_utc=window.start_utc,
                end_utc=window.end_utc,
                window_hash=window.window_hash,
                decision_count=decision_count,
                signal_count=signal_count,
                evaluated_operations=evaluated_operations,
                no_signal_decisions=no_signal_decisions,
                not_evaluable_entries=not_evaluable_entries,
                win_rate_percent=win_rate_percent,
                mean_gross_return_percent_without_costs=mean_return,
                median_gross_return_percent_without_costs=median_return,
                cumulative_simple_return_percent_without_costs=cumulative_return,
                max_loss_streak=max_loss_streak,
                max_win_streak=max_win_streak,
            )
        )
    return tuple(summaries)


def _build_summary(
    observations: Sequence[HistoricalMultiTimeframeStrategyAnalysisObservation],
    window_summaries: Sequence[HistoricalFuturesMarketValidationWindowSummary],
) -> HistoricalFuturesMarketValidationSummary:
    decision_count = len(observations)
    signal_count = sum(1 for item in observations if item.signal_generated)
    evaluated_returns = _returns_for_observations(observations)
    evaluated_operations = len(evaluated_returns)
    no_signal_decisions = sum(1 for item in observations if item.status == "no_signal")
    not_evaluable_entries = sum(1 for item in observations if item.status == "not_evaluable")
    empty_window_count = sum(1 for item in window_summaries if item.decision_count == 0)
    if evaluated_operations:
        winning_operations = sum(1 for value in evaluated_returns if value > 0)
        win_rate_percent = (Decimal(winning_operations) / Decimal(evaluated_operations)) * Decimal("100")
        mean_return = sum(evaluated_returns, Decimal("0")) / Decimal(evaluated_operations)
        median_return = median(evaluated_returns)
        cumulative_return = sum(evaluated_returns, Decimal("0"))
    else:
        win_rate_percent = Decimal("0")
        mean_return = Decimal("0")
        median_return = Decimal("0")
        cumulative_return = Decimal("0")
    mean_values = [item.mean_gross_return_percent_without_costs for item in window_summaries]
    win_rate_values = [item.win_rate_percent for item in window_summaries]
    window_mean_return_spread = (max(mean_values) - min(mean_values)) if mean_values else Decimal("0")
    window_win_rate_spread = (max(win_rate_values) - min(win_rate_values)) if win_rate_values else Decimal("0")
    max_loss_streak = max((item.max_loss_streak for item in window_summaries), default=0)
    max_win_streak = max((item.max_win_streak for item in window_summaries), default=0)
    return HistoricalFuturesMarketValidationSummary(
        window_count=len(window_summaries),
        empty_window_count=empty_window_count,
        decision_count=decision_count,
        signal_count=signal_count,
        evaluated_operations=evaluated_operations,
        no_signal_decisions=no_signal_decisions,
        not_evaluable_entries=not_evaluable_entries,
        win_rate_percent=win_rate_percent,
        mean_gross_return_percent_without_costs=mean_return,
        median_gross_return_percent_without_costs=median_return,
        cumulative_simple_return_percent_without_costs=cumulative_return,
        max_loss_streak=max_loss_streak,
        max_win_streak=max_win_streak,
        window_mean_return_spread_percent=window_mean_return_spread,
        window_win_rate_spread_percent=window_win_rate_spread,
    )


def _build_protocol(
    contract: HistoricalFuturesMarketContract,
    analysis_report: HistoricalMultiTimeframeStrategyAnalysisReport,
) -> HistoricalFuturesMarketValidationProtocol:
    temporal_split = contract.temporal_split_protocol
    strategy_report = analysis_report.source_evaluation_report.strategy_report
    evaluation_report = analysis_report.source_evaluation_report
    return HistoricalFuturesMarketValidationProtocol(
        contract_hash=contract.contract_hash,
        contract_temporal_split_hash=temporal_split.protocol_hash,
        analysis_report_hash=analysis_report.report_hash,
        evaluation_hash=evaluation_report.evaluation_hash,
        strategy_report_hash=strategy_report.report_hash,
        replay_hash=strategy_report.replay.replay_hash,
        bundle_hash=strategy_report.replay.bundle.bundle_hash,
        source_hash=analysis_report.protocol.source.source_hash,
        coverage_start_utc=temporal_split.coverage_start_utc,
        coverage_end_utc=temporal_split.coverage_end_utc,
        reference_window_hash=temporal_split.reference_window.window_hash,
        validation_window_hash=temporal_split.validation_window.window_hash,
        test_window_hash=temporal_split.test_window.window_hash,
    )


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketValidationReport:
    contract: HistoricalFuturesMarketContract
    analysis_report: HistoricalMultiTimeframeStrategyAnalysisReport
    protocol: HistoricalFuturesMarketValidationProtocol
    window_summaries: tuple[HistoricalFuturesMarketValidationWindowSummary, ...]
    summary: HistoricalFuturesMarketValidationSummary
    schema_version: int = HISTORICAL_FUTURES_MARKET_VALIDATION_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    report_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.contract, HistoricalFuturesMarketContract):
            raise HistoricalFuturesMarketValidationValidationError("contract must be a HistoricalFuturesMarketContract instance.")
        if not isinstance(self.analysis_report, HistoricalMultiTimeframeStrategyAnalysisReport):
            raise HistoricalFuturesMarketValidationValidationError("analysis_report must be a historical multi-timeframe analysis report instance.")
        if not isinstance(self.protocol, HistoricalFuturesMarketValidationProtocol):
            raise HistoricalFuturesMarketValidationValidationError("protocol must be a validation protocol instance.")
        if not isinstance(self.window_summaries, tuple):
            object.__setattr__(self, "window_summaries", tuple(self.window_summaries))
        if len(self.window_summaries) != len(HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES):
            raise HistoricalFuturesMarketValidationValidationError("validation report must contain three window summaries.")
        if not isinstance(self.summary, HistoricalFuturesMarketValidationSummary):
            raise HistoricalFuturesMarketValidationValidationError("summary must be a validation summary instance.")
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_VALIDATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketValidationValidationError("validation report schema_version must be 1.")
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        if self.contract.historical_research_only is not True or self.contract.operational_evidence is not False or self.contract.paper_promotion_eligible is not False:
            raise HistoricalFuturesMarketValidationValidationError("contract must remain research-only.")
        if self.analysis_report.historical_research_only is not True or self.analysis_report.operational_evidence is not False or self.analysis_report.paper_promotion_eligible is not False:
            raise HistoricalFuturesMarketValidationValidationError("analysis report must remain research-only.")
        built_protocol = _build_protocol(self.contract, self.analysis_report)
        if self.protocol != built_protocol:
            raise HistoricalFuturesMarketValidationValidationError("validation protocol diverges from the trusted contract and analysis chain.")
        built_window_summaries = _build_window_summaries(self.contract, self.analysis_report)
        if self.window_summaries != built_window_summaries:
            raise HistoricalFuturesMarketValidationIntegrityError("window summaries diverge from the trusted analysis chain.")
        built_summary = _build_summary(self.analysis_report.observations, self.window_summaries)
        if self.summary != built_summary:
            raise HistoricalFuturesMarketValidationIntegrityError("validation summary diverges from the trusted window summaries.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.report_hash:
            if self.report_hash != expected:
                raise HistoricalFuturesMarketValidationValidationError("validation report hash mismatch.")
        else:
            object.__setattr__(self, "report_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            # Keep the report fingerprint stable even when upstream artifact
            # hashes vary due to unrelated provenance details. The full nested
            # artifacts remain serialized in as_dict() for round-trip and
            # tamper checks, but the report hash is derived from the stable
            # temporal contract and the derived validation evidence.
            "protocol": {
                "schema_version": self.protocol.schema_version,
                "coverage_start_utc": _utc_iso(self.protocol.coverage_start_utc),
                "coverage_end_utc": _utc_iso(self.protocol.coverage_end_utc),
                "provenance_hash": self.contract.temporal_split_protocol.provenance_hash,
                "reference_window_hash": self.protocol.reference_window_hash,
                "validation_window_hash": self.protocol.validation_window_hash,
                "test_window_hash": self.protocol.test_window_hash,
                "evaluation_hash": self.protocol.evaluation_hash,
                "strategy_report_hash": self.protocol.strategy_report_hash,
                "replay_hash": self.protocol.replay_hash,
                "bundle_hash": self.protocol.bundle_hash,
                "source_hash": self.protocol.source_hash,
                "historical_research_only": self.protocol.historical_research_only,
                "operational_evidence": self.protocol.operational_evidence,
                "paper_promotion_eligible": self.protocol.paper_promotion_eligible,
            },
            "window_summaries": [item.as_dict() for item in self.window_summaries],
            "summary": self.summary.as_dict(),
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }
        if include_hash:
            payload["report_hash"] = self.report_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "contract": self.contract.as_dict(),
            "analysis_report": self.analysis_report.as_dict(),
            "protocol": self.protocol.as_dict(),
            "window_summaries": [item.as_dict() for item in self.window_summaries],
            "summary": self.summary.as_dict(),
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "report_hash": self.report_hash,
        }
        return serialize_value(payload)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketValidationReport":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketValidationValidationError("validation report must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "contract",
                "analysis_report",
                "protocol",
                "window_summaries",
                "summary",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "report_hash",
            },
            name="validation report",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                contract=HistoricalFuturesMarketContract.from_dict(mapping["contract"]),
                analysis_report=HistoricalMultiTimeframeStrategyAnalysisReport.from_dict(mapping["analysis_report"]),
                protocol=HistoricalFuturesMarketValidationProtocol.from_dict(mapping["protocol"]),
                window_summaries=tuple(
                    HistoricalFuturesMarketValidationWindowSummary.from_dict(item)
                    for item in mapping["window_summaries"]
                ),
                summary=HistoricalFuturesMarketValidationSummary.from_dict(mapping["summary"]),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                report_hash=mapping.get("report_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketValidationValidationError("validation report is incomplete.") from exc
        except (
            HistoricalFuturesMarketContractValidationError,
            HistoricalMultiTimeframeStrategyAnalysisValidationError,
            HistoricalDataValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise HistoricalFuturesMarketValidationIntegrityError(str(exc)) from exc


def build_historical_futures_market_validation_protocol(
    contract: HistoricalFuturesMarketContract,
    analysis_report: HistoricalMultiTimeframeStrategyAnalysisReport,
) -> HistoricalFuturesMarketValidationProtocol:
    if not isinstance(contract, HistoricalFuturesMarketContract):
        raise HistoricalFuturesMarketValidationValidationError("contract must be a HistoricalFuturesMarketContract instance.")
    if not isinstance(analysis_report, HistoricalMultiTimeframeStrategyAnalysisReport):
        raise HistoricalFuturesMarketValidationValidationError("analysis_report must be a HistoricalMultiTimeframeStrategyAnalysisReport instance.")
    return _build_protocol(contract, analysis_report)


def build_historical_futures_market_validation_report(
    contract: HistoricalFuturesMarketContract,
    analysis_report: HistoricalMultiTimeframeStrategyAnalysisReport,
    *,
    protocol: HistoricalFuturesMarketValidationProtocol | None = None,
) -> HistoricalFuturesMarketValidationReport:
    if not isinstance(contract, HistoricalFuturesMarketContract):
        raise HistoricalFuturesMarketValidationValidationError("contract must be a HistoricalFuturesMarketContract instance.")
    if not isinstance(analysis_report, HistoricalMultiTimeframeStrategyAnalysisReport):
        raise HistoricalFuturesMarketValidationValidationError("analysis_report must be a HistoricalMultiTimeframeStrategyAnalysisReport instance.")
    built_protocol = _build_protocol(contract, analysis_report)
    if protocol is None:
        protocol = built_protocol
    elif protocol != built_protocol:
        raise HistoricalFuturesMarketValidationValidationError("validation protocol diverges from the frozen contract and analysis chain.")
    window_summaries = _build_window_summaries(contract, analysis_report)
    summary = _build_summary(analysis_report.observations, window_summaries)
    return HistoricalFuturesMarketValidationReport(
        contract=contract,
        analysis_report=analysis_report,
        protocol=protocol,
        window_summaries=window_summaries,
        summary=summary,
    )


def run_historical_futures_market_validation(
    contract: HistoricalFuturesMarketContract,
    analysis_report: HistoricalMultiTimeframeStrategyAnalysisReport,
    *,
    protocol: HistoricalFuturesMarketValidationProtocol | None = None,
    output_file: str | Path | None = None,
) -> HistoricalFuturesMarketValidationReport:
    report = build_historical_futures_market_validation_report(contract, analysis_report, protocol=protocol)
    if output_file is not None:
        save_historical_futures_market_validation_report(output_file, report)
    return report


def _read(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HistoricalFuturesMarketValidationValidationError("validation report not found.") from exc
    except Exception as exc:
        raise HistoricalFuturesMarketValidationIntegrityError("validation report is invalid JSON.") from exc
    if not isinstance(value, Mapping):
        raise HistoricalFuturesMarketValidationIntegrityError("validation report must be a JSON object.")
    return value


def load_historical_futures_market_validation_report(path: str | Path) -> HistoricalFuturesMarketValidationReport:
    payload = _read(Path(path))
    try:
        report = HistoricalFuturesMarketValidationReport.from_dict(payload)
    except (
        KeyError,
        TypeError,
        ValueError,
        HistoricalFuturesMarketValidationValidationError,
        HistoricalFuturesMarketValidationIntegrityError,
        HistoricalFuturesMarketContractValidationError,
        HistoricalMultiTimeframeStrategyAnalysisValidationError,
        HistoricalDataValidationError,
    ) as exc:
        raise HistoricalFuturesMarketValidationIntegrityError(str(exc)) from exc
    if report.as_dict() != payload:
        raise HistoricalFuturesMarketValidationIntegrityError("validation report payload mismatch.")
    return report


def save_historical_futures_market_validation_report(
    path: str | Path,
    report: HistoricalFuturesMarketValidationReport,
) -> HistoricalFuturesMarketValidationReport:
    file_path = Path(path)
    payload = report.as_dict()
    if file_path.exists():
        existing = load_historical_futures_market_validation_report(file_path)
        if existing.as_dict() != payload:
            raise HistoricalFuturesMarketValidationConflictError("validation report already exists and differs.")
        return existing
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_name(f".{file_path.name}.{os.getpid()}.{id(report)}.tmp")
    try:
        tmp.write_text(_canonical_json(payload), encoding="utf-8")
        try:
            os.link(tmp, file_path)
        except FileExistsError:
            existing = load_historical_futures_market_validation_report(file_path)
            if existing.as_dict() != payload:
                raise HistoricalFuturesMarketValidationConflictError("validation report already exists and differs.")
            return existing
    except Exception as exc:
        if isinstance(exc, HistoricalFuturesMarketValidationConflictError):
            raise
        raise HistoricalFuturesMarketValidationValidationError("failed to write validation report atomically.") from exc
    finally:
        tmp.unlink(missing_ok=True)
    return report


def verify_historical_futures_market_validation_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_validation_report(path)
    return {
        "verified": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "contract_hash": report.contract.contract_hash,
        "analysis_report_hash": report.analysis_report.report_hash,
        "classification": "historical_research_only",
    }


def status_historical_futures_market_validation_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_validation_report(path)
    summary_map = {item.window_name: item for item in report.window_summaries}
    return {
        "exists": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "contract_hash": report.contract.contract_hash,
        "analysis_report_hash": report.analysis_report.report_hash,
        "strategy_report_hash": report.protocol.strategy_report_hash,
        "evaluation_hash": report.protocol.evaluation_hash,
        "reference_window_hash": report.protocol.reference_window_hash,
        "validation_window_hash": report.protocol.validation_window_hash,
        "test_window_hash": report.protocol.test_window_hash,
        "reference_window_decision_count": summary_map[HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE].decision_count,
        "validation_window_decision_count": summary_map[HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION].decision_count,
        "test_window_decision_count": summary_map[HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST].decision_count,
        "decision_count": report.summary.decision_count,
        "signal_count": report.summary.signal_count,
        "evaluated_operations": report.summary.evaluated_operations,
        "no_signal_decisions": report.summary.no_signal_decisions,
        "not_evaluable_entries": report.summary.not_evaluable_entries,
        "window_mean_return_spread_percent": report.summary.window_mean_return_spread_percent,
        "window_win_rate_spread_percent": report.summary.window_win_rate_spread_percent,
        "classification": "historical_research_only",
    }


def reject_historical_futures_market_validation_promotion(
    _: HistoricalFuturesMarketValidationReport,
) -> None:
    raise HistoricalFuturesMarketValidationPromotionError("historical futures market validation is not promotion evidence.")


__all__ = [
    "HISTORICAL_FUTURES_MARKET_VALIDATION_SCHEMA_VERSION",
    "HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES",
    "HistoricalFuturesMarketValidationConflictError",
    "HistoricalFuturesMarketValidationError",
    "HistoricalFuturesMarketValidationIntegrityError",
    "HistoricalFuturesMarketValidationProtocol",
    "HistoricalFuturesMarketValidationPromotionError",
    "HistoricalFuturesMarketValidationReport",
    "HistoricalFuturesMarketValidationSummary",
    "HistoricalFuturesMarketValidationValidationError",
    "HistoricalFuturesMarketValidationWindowSummary",
    "build_historical_futures_market_validation_protocol",
    "build_historical_futures_market_validation_report",
    "load_historical_futures_market_validation_report",
    "reject_historical_futures_market_validation_promotion",
    "run_historical_futures_market_validation",
    "save_historical_futures_market_validation_report",
    "status_historical_futures_market_validation_report",
    "verify_historical_futures_market_validation_report",
]
