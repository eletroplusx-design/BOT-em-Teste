from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from itertools import product
import json
import os
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value
from historical_multitimeframe_evaluation import (
    HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_NAME,
    HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_VERSION,
    HistoricalMultiTimeframeFirstStrategyEvaluationError,
    HistoricalMultiTimeframeFirstStrategyEvaluationReport,
    HistoricalMultiTimeframeFirstStrategyEvaluationValidationError,
)
from historical_multitimeframe_strategy import (
    HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_VERSION,
    HistoricalMultiTimeframeFirstStrategyReport,
)
from market_data import HistoricalDataValidationError


HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION = 1
HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_NAME = "historical_multitimeframe_first_strategy_analysis"
HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_VERSION = "v1"
HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_PERIOD_CUT_VERSION = "period_window_equal_duration_v1"
HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_TREND_CUT_VERSION = "trend_4h_close_vs_sma_v1"
HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_PRICE_CUT_VERSION = "price_1h_close_vs_sma_v1"
HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_VOLATILITY_CUT_VERSION = "volatility_15m_trailing_mean_range_ratio_v1"
HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_TREND_LABELS: tuple[str, ...] = ("above_sma", "at_or_below_sma")
HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_PRICE_LABELS: tuple[str, ...] = ("above_sma", "at_or_below_sma")
HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_VOLATILITY_LABELS: tuple[str, ...] = ("low", "medium", "high", "insufficient_history")


class HistoricalMultiTimeframeStrategyAnalysisError(Exception):
    pass


class HistoricalMultiTimeframeStrategyAnalysisValidationError(HistoricalMultiTimeframeStrategyAnalysisError):
    pass


class HistoricalMultiTimeframeStrategyAnalysisIntegrityError(HistoricalMultiTimeframeStrategyAnalysisValidationError):
    pass


class HistoricalMultiTimeframeStrategyAnalysisConflictError(HistoricalMultiTimeframeStrategyAnalysisIntegrityError):
    pass


class HistoricalMultiTimeframeStrategyAnalysisPromotionError(HistoricalMultiTimeframeStrategyAnalysisValidationError):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if type(value) is bool:
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError(f"{field_name} must be numeric.")
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError(f"{field_name} must be numeric.") from exc


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError(f"{field_name} must be timezone-aware UTC datetime.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError(f"{field_name} must be timezone-aware UTC datetime.") from exc
    if not isinstance(value, datetime):
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _validate_exact_keys(mapping: Mapping[str, Any], *, allowed: set[str], name: str) -> None:
    extra = set(mapping) - allowed
    if extra:
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError(f"{name} contains unknown fields: {sorted(extra)!r}.")


def _research_only_flags(historical_research_only: bool, operational_evidence: bool, paper_promotion_eligible: bool) -> None:
    if historical_research_only is not True:
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError("historical_research_only must be true.")
    if operational_evidence is not False:
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError("operational_evidence must be false.")
    if paper_promotion_eligible is not False:
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError("paper_promotion_eligible must be false.")


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeStrategyAnalysisReasonCount:
    reason: str
    count: int
    reason_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", _require_str(self.reason, "reason"))
        object.__setattr__(self, "count", _require_int(self.count, "count", allow_zero=True))
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.reason_hash:
            if self.reason_hash != expected:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("reason count hash mismatch.")
        else:
            object.__setattr__(self, "reason_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {"reason": self.reason, "count": self.count}
        if include_hash:
            payload["reason_hash"] = self.reason_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeStrategyAnalysisReasonCount":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("reason count must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(mapping, allowed={"reason", "count", "reason_hash"}, name="reason count")
        try:
            return cls(reason=mapping["reason"], count=mapping["count"], reason_hash=mapping.get("reason_hash", ""))
        except KeyError as exc:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("reason count is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeStrategyAnalysisPeriodWindow:
    label: str
    start_utc: datetime
    end_utc: datetime
    inclusive_end: bool = False
    schema_version: int = HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION
    window_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _require_str(self.label, "label"))
        object.__setattr__(self, "start_utc", _require_utc_datetime(self.start_utc, "start_utc"))
        object.__setattr__(self, "end_utc", _require_utc_datetime(self.end_utc, "end_utc"))
        object.__setattr__(self, "inclusive_end", _require_bool(self.inclusive_end, "inclusive_end"))
        if self.start_utc >= self.end_utc:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("period window start must be before end.")
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("period window schema_version must be 1.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.window_hash:
            if self.window_hash != expected:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("period window hash mismatch.")
        else:
            object.__setattr__(self, "window_hash", expected)

    def contains(self, value: datetime) -> bool:
        decision_time = _require_utc_datetime(value, "decision_time_utc")
        if self.inclusive_end:
            return self.start_utc <= decision_time <= self.end_utc
        return self.start_utc <= decision_time < self.end_utc

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "label": self.label,
            "start_utc": _utc_iso(self.start_utc),
            "end_utc": _utc_iso(self.end_utc),
            "inclusive_end": self.inclusive_end,
        }
        if include_hash:
            payload["window_hash"] = self.window_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeStrategyAnalysisPeriodWindow":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("period window must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(mapping, allowed={"schema_version", "label", "start_utc", "end_utc", "inclusive_end", "window_hash"}, name="period window")
        try:
            return cls(
                label=mapping["label"],
                start_utc=mapping["start_utc"],
                end_utc=mapping["end_utc"],
                inclusive_end=mapping.get("inclusive_end", False),
                schema_version=mapping["schema_version"],
                window_hash=mapping.get("window_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("period window is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeStrategyAnalysisSource:
    evaluation_name: str
    evaluation_version: str
    strategy_hypothesis_version: str
    strategy_config_hash: str
    strategy_factory_hash: str
    strategy_report_hash: str
    evaluation_protocol_hash: str
    evaluation_hash: str
    replay_hash: str
    bundle_hash: str
    alignment_policy_hash: str
    context_policy_hash: str
    symbol: str
    base_interval: str
    one_hour_interval: str
    four_hour_interval: str
    period_start_utc: datetime
    period_end_utc: datetime
    snapshot_count: int
    schema_version: int = HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    source_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluation_name", _require_str(self.evaluation_name, "evaluation_name"))
        object.__setattr__(self, "evaluation_version", _require_str(self.evaluation_version, "evaluation_version"))
        object.__setattr__(self, "strategy_hypothesis_version", _require_str(self.strategy_hypothesis_version, "strategy_hypothesis_version"))
        object.__setattr__(self, "strategy_config_hash", _require_str(self.strategy_config_hash, "strategy_config_hash"))
        object.__setattr__(self, "strategy_factory_hash", _require_str(self.strategy_factory_hash, "strategy_factory_hash"))
        object.__setattr__(self, "strategy_report_hash", _require_str(self.strategy_report_hash, "strategy_report_hash"))
        object.__setattr__(self, "evaluation_protocol_hash", _require_str(self.evaluation_protocol_hash, "evaluation_protocol_hash"))
        object.__setattr__(self, "evaluation_hash", _require_str(self.evaluation_hash, "evaluation_hash"))
        object.__setattr__(self, "replay_hash", _require_str(self.replay_hash, "replay_hash"))
        object.__setattr__(self, "bundle_hash", _require_str(self.bundle_hash, "bundle_hash"))
        object.__setattr__(self, "alignment_policy_hash", _require_str(self.alignment_policy_hash, "alignment_policy_hash"))
        object.__setattr__(self, "context_policy_hash", _require_str(self.context_policy_hash, "context_policy_hash"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "base_interval", _require_str(self.base_interval, "base_interval"))
        object.__setattr__(self, "one_hour_interval", _require_str(self.one_hour_interval, "one_hour_interval"))
        object.__setattr__(self, "four_hour_interval", _require_str(self.four_hour_interval, "four_hour_interval"))
        object.__setattr__(self, "period_start_utc", _require_utc_datetime(self.period_start_utc, "period_start_utc"))
        object.__setattr__(self, "period_end_utc", _require_utc_datetime(self.period_end_utc, "period_end_utc"))
        object.__setattr__(self, "snapshot_count", _require_int(self.snapshot_count, "snapshot_count"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis source schema_version must be 1.")
        if self.evaluation_name != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_NAME:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis source evaluation_name diverges from the trusted protocol.")
        if self.evaluation_version != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_VERSION:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis source evaluation_version diverges from the trusted protocol.")
        if self.base_interval != "15m" or self.one_hour_interval != "1h" or self.four_hour_interval != "4h":
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis source intervals diverge from the trusted multi-timeframe contract.")
        if self.period_end_utc <= self.period_start_utc:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis source period_end_utc must not precede period_start_utc.")
        if self.snapshot_count <= 0:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis source snapshot_count must be greater than zero.")
        if self.historical_research_only is not True:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("paper_promotion_eligible must be false.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.source_hash:
            if self.source_hash != expected:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis source hash mismatch.")
        else:
            object.__setattr__(self, "source_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "evaluation_name": self.evaluation_name,
            "evaluation_version": self.evaluation_version,
            "strategy_hypothesis_version": self.strategy_hypothesis_version,
            "strategy_config_hash": self.strategy_config_hash,
            "strategy_factory_hash": self.strategy_factory_hash,
            "strategy_report_hash": self.strategy_report_hash,
            "evaluation_protocol_hash": self.evaluation_protocol_hash,
            "evaluation_hash": self.evaluation_hash,
            "replay_hash": self.replay_hash,
            "bundle_hash": self.bundle_hash,
            "alignment_policy_hash": self.alignment_policy_hash,
            "context_policy_hash": self.context_policy_hash,
            "symbol": self.symbol,
            "base_interval": self.base_interval,
            "one_hour_interval": self.one_hour_interval,
            "four_hour_interval": self.four_hour_interval,
            "period_start_utc": _utc_iso(self.period_start_utc),
            "period_end_utc": _utc_iso(self.period_end_utc),
            "snapshot_count": self.snapshot_count,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }
        if include_hash:
            payload["source_hash"] = self.source_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeStrategyAnalysisSource":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis source must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "evaluation_name",
                "evaluation_version",
                "strategy_hypothesis_version",
                "strategy_config_hash",
                "strategy_factory_hash",
                "strategy_report_hash",
                "evaluation_protocol_hash",
                "evaluation_hash",
                "replay_hash",
                "bundle_hash",
                "alignment_policy_hash",
                "context_policy_hash",
                "symbol",
                "base_interval",
                "one_hour_interval",
                "four_hour_interval",
                "period_start_utc",
                "period_end_utc",
                "snapshot_count",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "source_hash",
            },
            name="analysis source",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                evaluation_name=mapping["evaluation_name"],
                evaluation_version=mapping["evaluation_version"],
                strategy_hypothesis_version=mapping["strategy_hypothesis_version"],
                strategy_config_hash=mapping["strategy_config_hash"],
                strategy_factory_hash=mapping["strategy_factory_hash"],
                strategy_report_hash=mapping["strategy_report_hash"],
                evaluation_protocol_hash=mapping["evaluation_protocol_hash"],
                evaluation_hash=mapping["evaluation_hash"],
                replay_hash=mapping["replay_hash"],
                bundle_hash=mapping["bundle_hash"],
                alignment_policy_hash=mapping["alignment_policy_hash"],
                context_policy_hash=mapping["context_policy_hash"],
                symbol=mapping["symbol"],
                base_interval=mapping["base_interval"],
                one_hour_interval=mapping["one_hour_interval"],
                four_hour_interval=mapping["four_hour_interval"],
                period_start_utc=mapping["period_start_utc"],
                period_end_utc=mapping["period_end_utc"],
                snapshot_count=mapping["snapshot_count"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                source_hash=mapping.get("source_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis source is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeStrategyAnalysisProtocol:
    source: HistoricalMultiTimeframeStrategyAnalysisSource
    period_windows: tuple[HistoricalMultiTimeframeStrategyAnalysisPeriodWindow, ...]
    period_cut_version: str = HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_PERIOD_CUT_VERSION
    trend_cut_version: str = HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_TREND_CUT_VERSION
    price_cut_version: str = HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_PRICE_CUT_VERSION
    volatility_cut_version: str = HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_VOLATILITY_CUT_VERSION
    trend_labels: tuple[str, ...] = HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_TREND_LABELS
    price_labels: tuple[str, ...] = HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_PRICE_LABELS
    volatility_labels: tuple[str, ...] = HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_VOLATILITY_LABELS
    volatility_lookback_15m_candles: int = 32
    volatility_low_threshold_percent: Decimal = Decimal("1")
    volatility_medium_threshold_percent: Decimal = Decimal("2")
    minimum_group_sample_size: int = 5
    schema_version: int = HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    protocol_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.source, HistoricalMultiTimeframeStrategyAnalysisSource):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("source must be an analysis source instance.")
        if not isinstance(self.period_windows, tuple):
            object.__setattr__(self, "period_windows", tuple(self.period_windows))
        if not self.period_windows:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis requires period windows.")
        if not all(isinstance(window, HistoricalMultiTimeframeStrategyAnalysisPeriodWindow) for window in self.period_windows):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("period_windows must contain analysis period window entries.")
        object.__setattr__(self, "period_cut_version", _require_str(self.period_cut_version, "period_cut_version"))
        object.__setattr__(self, "trend_cut_version", _require_str(self.trend_cut_version, "trend_cut_version"))
        object.__setattr__(self, "price_cut_version", _require_str(self.price_cut_version, "price_cut_version"))
        object.__setattr__(self, "volatility_cut_version", _require_str(self.volatility_cut_version, "volatility_cut_version"))
        object.__setattr__(self, "trend_labels", tuple(_require_str(label, "trend label") for label in self.trend_labels))
        object.__setattr__(self, "price_labels", tuple(_require_str(label, "price label") for label in self.price_labels))
        object.__setattr__(self, "volatility_labels", tuple(_require_str(label, "volatility label") for label in self.volatility_labels))
        object.__setattr__(self, "volatility_lookback_15m_candles", _require_int(self.volatility_lookback_15m_candles, "volatility_lookback_15m_candles"))
        object.__setattr__(self, "volatility_low_threshold_percent", _require_decimal(self.volatility_low_threshold_percent, "volatility_low_threshold_percent"))
        object.__setattr__(self, "volatility_medium_threshold_percent", _require_decimal(self.volatility_medium_threshold_percent, "volatility_medium_threshold_percent"))
        object.__setattr__(self, "minimum_group_sample_size", _require_int(self.minimum_group_sample_size, "minimum_group_sample_size"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis protocol schema_version must be 1.")
        if self.period_windows[0].start_utc != self.source.period_start_utc:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis periods must start at the source period start.")
        if self.period_windows[-1].end_utc != self.source.period_end_utc:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis periods must end at the source period end.")
        for index, window in enumerate(self.period_windows):
            if window.label != f"period_{index + 1}":
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis period labels must follow the frozen order.")
            if index < len(self.period_windows) - 1 and window.inclusive_end:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("only the final analysis period may include its end time.")
            if index == len(self.period_windows) - 1 and not window.inclusive_end:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("the final analysis period must include its end time.")
            if index > 0 and window.start_utc != self.period_windows[index - 1].end_utc:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis periods must be contiguous.")
        if self.volatility_low_threshold_percent <= 0 or self.volatility_medium_threshold_percent <= 0:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("volatility thresholds must be greater than zero.")
        if self.volatility_low_threshold_percent >= self.volatility_medium_threshold_percent:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("volatility low threshold must be below the medium threshold.")
        if self.minimum_group_sample_size <= 0:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("minimum_group_sample_size must be greater than zero.")
        if self.trend_labels != HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_TREND_LABELS:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("trend labels diverge from the frozen analysis cut.")
        if self.price_labels != HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_PRICE_LABELS:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("price labels diverge from the frozen analysis cut.")
        if self.volatility_labels != HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_VOLATILITY_LABELS:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("volatility labels diverge from the frozen analysis cut.")
        _research_only_flags(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.protocol_hash:
            if self.protocol_hash != expected:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis protocol hash mismatch.")
        else:
            object.__setattr__(self, "protocol_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "source": self.source.as_dict(),
            "period_windows": [window.as_dict() for window in self.period_windows],
            "period_cut_version": self.period_cut_version,
            "trend_cut_version": self.trend_cut_version,
            "price_cut_version": self.price_cut_version,
            "volatility_cut_version": self.volatility_cut_version,
            "trend_labels": list(self.trend_labels),
            "price_labels": list(self.price_labels),
            "volatility_labels": list(self.volatility_labels),
            "volatility_lookback_15m_candles": self.volatility_lookback_15m_candles,
            "volatility_low_threshold_percent": self.volatility_low_threshold_percent,
            "volatility_medium_threshold_percent": self.volatility_medium_threshold_percent,
            "minimum_group_sample_size": self.minimum_group_sample_size,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeStrategyAnalysisProtocol":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis protocol must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "source",
                "period_windows",
                "period_cut_version",
                "trend_cut_version",
                "price_cut_version",
                "volatility_cut_version",
                "trend_labels",
                "price_labels",
                "volatility_labels",
                "volatility_lookback_15m_candles",
                "volatility_low_threshold_percent",
                "volatility_medium_threshold_percent",
                "minimum_group_sample_size",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "protocol_hash",
            },
            name="analysis protocol",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                source=HistoricalMultiTimeframeStrategyAnalysisSource.from_dict(mapping["source"]),
                period_windows=tuple(HistoricalMultiTimeframeStrategyAnalysisPeriodWindow.from_dict(item) for item in mapping["period_windows"]),
                period_cut_version=mapping["period_cut_version"],
                trend_cut_version=mapping["trend_cut_version"],
                price_cut_version=mapping["price_cut_version"],
                volatility_cut_version=mapping["volatility_cut_version"],
                trend_labels=tuple(mapping.get("trend_labels", ())),
                price_labels=tuple(mapping.get("price_labels", ())),
                volatility_labels=tuple(mapping.get("volatility_labels", ())),
                volatility_lookback_15m_candles=mapping["volatility_lookback_15m_candles"],
                volatility_low_threshold_percent=mapping["volatility_low_threshold_percent"],
                volatility_medium_threshold_percent=mapping["volatility_medium_threshold_percent"],
                minimum_group_sample_size=mapping["minimum_group_sample_size"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                protocol_hash=mapping.get("protocol_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis protocol is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeStrategyAnalysisObservation:
    decision_hash: str
    context_hash: str
    result_hash: str
    decision_time_utc: datetime
    period_label: str
    trend_4h_label: str
    price_1h_label: str
    volatility_label: str
    trend_4h_close: Decimal
    trend_4h_sma: Decimal
    trend_4h_distance_percent: Decimal
    price_1h_close: Decimal
    price_1h_sma: Decimal
    price_1h_distance_percent: Decimal
    volatility_percent: Decimal | None
    volatility_lookback_15m_candles: int
    signal_generated: bool
    status: str
    reasons: tuple[str, ...]
    gross_return_percent_without_costs: Decimal | None = None
    schema_version: int = HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION
    observation_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_hash", _require_str(self.decision_hash, "decision_hash"))
        object.__setattr__(self, "context_hash", _require_str(self.context_hash, "context_hash"))
        object.__setattr__(self, "result_hash", _require_str(self.result_hash, "result_hash"))
        object.__setattr__(self, "decision_time_utc", _require_utc_datetime(self.decision_time_utc, "decision_time_utc"))
        object.__setattr__(self, "period_label", _require_str(self.period_label, "period_label"))
        object.__setattr__(self, "trend_4h_label", _require_str(self.trend_4h_label, "trend_4h_label"))
        object.__setattr__(self, "price_1h_label", _require_str(self.price_1h_label, "price_1h_label"))
        object.__setattr__(self, "volatility_label", _require_str(self.volatility_label, "volatility_label"))
        object.__setattr__(self, "trend_4h_close", _require_decimal(self.trend_4h_close, "trend_4h_close"))
        object.__setattr__(self, "trend_4h_sma", _require_decimal(self.trend_4h_sma, "trend_4h_sma"))
        object.__setattr__(self, "trend_4h_distance_percent", _require_decimal(self.trend_4h_distance_percent, "trend_4h_distance_percent"))
        object.__setattr__(self, "price_1h_close", _require_decimal(self.price_1h_close, "price_1h_close"))
        object.__setattr__(self, "price_1h_sma", _require_decimal(self.price_1h_sma, "price_1h_sma"))
        object.__setattr__(self, "price_1h_distance_percent", _require_decimal(self.price_1h_distance_percent, "price_1h_distance_percent"))
        object.__setattr__(self, "volatility_lookback_15m_candles", _require_int(self.volatility_lookback_15m_candles, "volatility_lookback_15m_candles"))
        object.__setattr__(self, "signal_generated", _require_bool(self.signal_generated, "signal_generated"))
        object.__setattr__(self, "status", _require_str(self.status, "status"))
        if self.volatility_percent is not None:
            object.__setattr__(self, "volatility_percent", _require_decimal(self.volatility_percent, "volatility_percent"))
        object.__setattr__(self, "gross_return_percent_without_costs", _require_decimal(self.gross_return_percent_without_costs, "gross_return_percent_without_costs") if self.gross_return_percent_without_costs is not None else None)
        if not isinstance(self.reasons, tuple):
            object.__setattr__(self, "reasons", tuple(self.reasons))
        if not self.reasons:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis reasons are required.")
        if any(not isinstance(reason, str) or not reason.strip() for reason in self.reasons):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis reasons must be non-empty strings.")
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis observation schema_version must be 1.")
        if self.status not in {
            "no_signal",
            "not_evaluable",
            "evaluated",
        }:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("unknown analysis status.")
        if self.volatility_label not in HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_VOLATILITY_LABELS:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("volatility label diverges from the frozen analysis cut.")
        if self.trend_4h_label not in HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_TREND_LABELS:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("4h trend label diverges from the frozen analysis cut.")
        if self.price_1h_label not in HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_PRICE_LABELS:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("1h price label diverges from the frozen analysis cut.")
        if self.status == "no_signal":
            if self.signal_generated is not False:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("no-signal observations must not claim a generated signal.")
            if self.gross_return_percent_without_costs is not None:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("no-signal observations must not carry a return.")
        elif self.status == "not_evaluable":
            if self.signal_generated is not True:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("not-evaluable observations must originate from a generated signal.")
            if self.gross_return_percent_without_costs is not None:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("not-evaluable observations must not carry a return.")
        else:
            if self.signal_generated is not True:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("evaluated observations must originate from a generated signal.")
            if self.gross_return_percent_without_costs is None:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("evaluated observations require a return.")
        if self.volatility_label == "insufficient_history":
            if self.volatility_percent is not None:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("insufficient history observations must not carry a volatility value.")
        else:
            if self.volatility_percent is None:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("volatility observations require a value.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.observation_hash:
            if self.observation_hash != expected:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis observation hash mismatch.")
        else:
            object.__setattr__(self, "observation_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "decision_hash": self.decision_hash,
            "context_hash": self.context_hash,
            "result_hash": self.result_hash,
            "decision_time_utc": _utc_iso(self.decision_time_utc),
            "period_label": self.period_label,
            "trend_4h_label": self.trend_4h_label,
            "price_1h_label": self.price_1h_label,
            "volatility_label": self.volatility_label,
            "trend_4h_close": self.trend_4h_close,
            "trend_4h_sma": self.trend_4h_sma,
            "trend_4h_distance_percent": self.trend_4h_distance_percent,
            "price_1h_close": self.price_1h_close,
            "price_1h_sma": self.price_1h_sma,
            "price_1h_distance_percent": self.price_1h_distance_percent,
            "volatility_percent": self.volatility_percent,
            "volatility_lookback_15m_candles": self.volatility_lookback_15m_candles,
            "signal_generated": self.signal_generated,
            "status": self.status,
            "reasons": list(self.reasons),
            "gross_return_percent_without_costs": self.gross_return_percent_without_costs,
        }
        if include_hash:
            payload["observation_hash"] = self.observation_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeStrategyAnalysisObservation":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis observation must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "decision_hash",
                "context_hash",
                "result_hash",
                "decision_time_utc",
                "period_label",
                "trend_4h_label",
                "price_1h_label",
                "volatility_label",
                "trend_4h_close",
                "trend_4h_sma",
                "trend_4h_distance_percent",
                "price_1h_close",
                "price_1h_sma",
                "price_1h_distance_percent",
                "volatility_percent",
                "volatility_lookback_15m_candles",
                "signal_generated",
                "status",
                "reasons",
                "gross_return_percent_without_costs",
                "observation_hash",
            },
            name="analysis observation",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                decision_hash=mapping["decision_hash"],
                context_hash=mapping["context_hash"],
                result_hash=mapping["result_hash"],
                decision_time_utc=mapping["decision_time_utc"],
                period_label=mapping["period_label"],
                trend_4h_label=mapping["trend_4h_label"],
                price_1h_label=mapping["price_1h_label"],
                volatility_label=mapping["volatility_label"],
                trend_4h_close=mapping["trend_4h_close"],
                trend_4h_sma=mapping["trend_4h_sma"],
                trend_4h_distance_percent=mapping["trend_4h_distance_percent"],
                price_1h_close=mapping["price_1h_close"],
                price_1h_sma=mapping["price_1h_sma"],
                price_1h_distance_percent=mapping["price_1h_distance_percent"],
                volatility_percent=mapping.get("volatility_percent"),
                volatility_lookback_15m_candles=mapping["volatility_lookback_15m_candles"],
                signal_generated=mapping["signal_generated"],
                status=mapping["status"],
                reasons=tuple(mapping.get("reasons", ())),
                gross_return_percent_without_costs=mapping.get("gross_return_percent_without_costs"),
                observation_hash=mapping.get("observation_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis observation is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeStrategyAnalysisGroup:
    period_label: str
    trend_4h_label: str
    price_1h_label: str
    volatility_label: str
    decision_count: int
    signal_count: int
    evaluated_operations: int
    no_signal_decisions: int
    not_evaluable_entries: int
    no_signal_reason_counts: tuple[HistoricalMultiTimeframeStrategyAnalysisReasonCount, ...]
    not_evaluable_reason_counts: tuple[HistoricalMultiTimeframeStrategyAnalysisReasonCount, ...]
    win_rate_percent: Decimal
    mean_gross_return_percent_without_costs: Decimal
    median_gross_return_percent_without_costs: Decimal
    cumulative_simple_return_percent_without_costs: Decimal
    max_loss_streak: int
    max_win_streak: int
    sample_warning: str | None = None
    schema_version: int = HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION
    group_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "period_label", _require_str(self.period_label, "period_label"))
        object.__setattr__(self, "trend_4h_label", _require_str(self.trend_4h_label, "trend_4h_label"))
        object.__setattr__(self, "price_1h_label", _require_str(self.price_1h_label, "price_1h_label"))
        object.__setattr__(self, "volatility_label", _require_str(self.volatility_label, "volatility_label"))
        object.__setattr__(self, "decision_count", _require_int(self.decision_count, "decision_count", allow_zero=True))
        object.__setattr__(self, "signal_count", _require_int(self.signal_count, "signal_count", allow_zero=True))
        object.__setattr__(self, "evaluated_operations", _require_int(self.evaluated_operations, "evaluated_operations", allow_zero=True))
        object.__setattr__(self, "no_signal_decisions", _require_int(self.no_signal_decisions, "no_signal_decisions", allow_zero=True))
        object.__setattr__(self, "not_evaluable_entries", _require_int(self.not_evaluable_entries, "not_evaluable_entries", allow_zero=True))
        if not isinstance(self.no_signal_reason_counts, tuple):
            object.__setattr__(self, "no_signal_reason_counts", tuple(self.no_signal_reason_counts))
        if not isinstance(self.not_evaluable_reason_counts, tuple):
            object.__setattr__(self, "not_evaluable_reason_counts", tuple(self.not_evaluable_reason_counts))
        if any(not isinstance(item, HistoricalMultiTimeframeStrategyAnalysisReasonCount) for item in self.no_signal_reason_counts):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("no_signal_reason_counts must contain reason counts.")
        if any(not isinstance(item, HistoricalMultiTimeframeStrategyAnalysisReasonCount) for item in self.not_evaluable_reason_counts):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("not_evaluable_reason_counts must contain reason counts.")
        object.__setattr__(self, "win_rate_percent", _require_decimal(self.win_rate_percent, "win_rate_percent"))
        object.__setattr__(self, "mean_gross_return_percent_without_costs", _require_decimal(self.mean_gross_return_percent_without_costs, "mean_gross_return_percent_without_costs"))
        object.__setattr__(self, "median_gross_return_percent_without_costs", _require_decimal(self.median_gross_return_percent_without_costs, "median_gross_return_percent_without_costs"))
        object.__setattr__(self, "cumulative_simple_return_percent_without_costs", _require_decimal(self.cumulative_simple_return_percent_without_costs, "cumulative_simple_return_percent_without_costs"))
        object.__setattr__(self, "max_loss_streak", _require_int(self.max_loss_streak, "max_loss_streak", allow_zero=True))
        object.__setattr__(self, "max_win_streak", _require_int(self.max_win_streak, "max_win_streak", allow_zero=True))
        if self.sample_warning is not None:
            object.__setattr__(self, "sample_warning", _require_str(self.sample_warning, "sample_warning"))
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis group schema_version must be 1.")
        if self.signal_count != self.evaluated_operations + self.not_evaluable_entries:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("group signal counts must reconcile with evaluated and not-evaluable entries.")
        if self.decision_count != self.signal_count + self.no_signal_decisions:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("group counts must reconcile with the decision count.")
        if self.evaluated_operations < 0:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("evaluated_operations must not be negative.")
        if self.evaluated_operations > self.signal_count:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("evaluated_operations cannot exceed the signal count.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.group_hash:
            if self.group_hash != expected:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis group hash mismatch.")
        else:
            object.__setattr__(self, "group_hash", expected)

    @property
    def excluded_records(self) -> int:
        return self.no_signal_decisions + self.not_evaluable_entries

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "period_label": self.period_label,
            "trend_4h_label": self.trend_4h_label,
            "price_1h_label": self.price_1h_label,
            "volatility_label": self.volatility_label,
            "decision_count": self.decision_count,
            "signal_count": self.signal_count,
            "evaluated_operations": self.evaluated_operations,
            "no_signal_decisions": self.no_signal_decisions,
            "not_evaluable_entries": self.not_evaluable_entries,
            "no_signal_reason_counts": [item.as_dict() for item in self.no_signal_reason_counts],
            "not_evaluable_reason_counts": [item.as_dict() for item in self.not_evaluable_reason_counts],
            "win_rate_percent": self.win_rate_percent,
            "mean_gross_return_percent_without_costs": self.mean_gross_return_percent_without_costs,
            "median_gross_return_percent_without_costs": self.median_gross_return_percent_without_costs,
            "cumulative_simple_return_percent_without_costs": self.cumulative_simple_return_percent_without_costs,
            "max_loss_streak": self.max_loss_streak,
            "max_win_streak": self.max_win_streak,
            "sample_warning": self.sample_warning,
        }
        if include_hash:
            payload["group_hash"] = self.group_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeStrategyAnalysisGroup":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis group must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "period_label",
                "trend_4h_label",
                "price_1h_label",
                "volatility_label",
                "decision_count",
                "signal_count",
                "evaluated_operations",
                "no_signal_decisions",
                "not_evaluable_entries",
                "no_signal_reason_counts",
                "not_evaluable_reason_counts",
                "win_rate_percent",
                "mean_gross_return_percent_without_costs",
                "median_gross_return_percent_without_costs",
                "cumulative_simple_return_percent_without_costs",
                "max_loss_streak",
                "max_win_streak",
                "sample_warning",
                "group_hash",
            },
            name="analysis group",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                period_label=mapping["period_label"],
                trend_4h_label=mapping["trend_4h_label"],
                price_1h_label=mapping["price_1h_label"],
                volatility_label=mapping["volatility_label"],
                decision_count=mapping["decision_count"],
                signal_count=mapping["signal_count"],
                evaluated_operations=mapping["evaluated_operations"],
                no_signal_decisions=mapping["no_signal_decisions"],
                not_evaluable_entries=mapping["not_evaluable_entries"],
                no_signal_reason_counts=tuple(HistoricalMultiTimeframeStrategyAnalysisReasonCount.from_dict(item) for item in mapping.get("no_signal_reason_counts", ())),
                not_evaluable_reason_counts=tuple(HistoricalMultiTimeframeStrategyAnalysisReasonCount.from_dict(item) for item in mapping.get("not_evaluable_reason_counts", ())),
                win_rate_percent=mapping["win_rate_percent"],
                mean_gross_return_percent_without_costs=mapping["mean_gross_return_percent_without_costs"],
                median_gross_return_percent_without_costs=mapping["median_gross_return_percent_without_costs"],
                cumulative_simple_return_percent_without_costs=mapping["cumulative_simple_return_percent_without_costs"],
                max_loss_streak=mapping["max_loss_streak"],
                max_win_streak=mapping["max_win_streak"],
                sample_warning=mapping.get("sample_warning"),
                group_hash=mapping.get("group_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis group is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeStrategyAnalysisSummary:
    decision_count: int
    signal_count: int
    evaluated_operations: int
    no_signal_decisions: int
    not_evaluable_entries: int
    excluded_records: int
    excluded_reason_counts: tuple[HistoricalMultiTimeframeStrategyAnalysisReasonCount, ...]
    group_count: int
    empty_group_count: int
    warning_group_count: int
    win_rate_percent: Decimal
    mean_gross_return_percent_without_costs: Decimal
    median_gross_return_percent_without_costs: Decimal
    cumulative_simple_return_percent_without_costs: Decimal
    max_loss_streak: int
    max_win_streak: int
    schema_version: int = HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION
    summary_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_count", _require_int(self.decision_count, "decision_count", allow_zero=True))
        object.__setattr__(self, "signal_count", _require_int(self.signal_count, "signal_count", allow_zero=True))
        object.__setattr__(self, "evaluated_operations", _require_int(self.evaluated_operations, "evaluated_operations", allow_zero=True))
        object.__setattr__(self, "no_signal_decisions", _require_int(self.no_signal_decisions, "no_signal_decisions", allow_zero=True))
        object.__setattr__(self, "not_evaluable_entries", _require_int(self.not_evaluable_entries, "not_evaluable_entries", allow_zero=True))
        object.__setattr__(self, "excluded_records", _require_int(self.excluded_records, "excluded_records", allow_zero=True))
        if not isinstance(self.excluded_reason_counts, tuple):
            object.__setattr__(self, "excluded_reason_counts", tuple(self.excluded_reason_counts))
        if any(not isinstance(item, HistoricalMultiTimeframeStrategyAnalysisReasonCount) for item in self.excluded_reason_counts):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("excluded_reason_counts must contain reason counts.")
        object.__setattr__(self, "group_count", _require_int(self.group_count, "group_count", allow_zero=True))
        object.__setattr__(self, "empty_group_count", _require_int(self.empty_group_count, "empty_group_count", allow_zero=True))
        object.__setattr__(self, "warning_group_count", _require_int(self.warning_group_count, "warning_group_count", allow_zero=True))
        object.__setattr__(self, "win_rate_percent", _require_decimal(self.win_rate_percent, "win_rate_percent"))
        object.__setattr__(self, "mean_gross_return_percent_without_costs", _require_decimal(self.mean_gross_return_percent_without_costs, "mean_gross_return_percent_without_costs"))
        object.__setattr__(self, "median_gross_return_percent_without_costs", _require_decimal(self.median_gross_return_percent_without_costs, "median_gross_return_percent_without_costs"))
        object.__setattr__(self, "cumulative_simple_return_percent_without_costs", _require_decimal(self.cumulative_simple_return_percent_without_costs, "cumulative_simple_return_percent_without_costs"))
        object.__setattr__(self, "max_loss_streak", _require_int(self.max_loss_streak, "max_loss_streak", allow_zero=True))
        object.__setattr__(self, "max_win_streak", _require_int(self.max_win_streak, "max_win_streak", allow_zero=True))
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis summary schema_version must be 1.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.summary_hash:
            if self.summary_hash != expected:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis summary hash mismatch.")
        else:
            object.__setattr__(self, "summary_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "decision_count": self.decision_count,
            "signal_count": self.signal_count,
            "evaluated_operations": self.evaluated_operations,
            "no_signal_decisions": self.no_signal_decisions,
            "not_evaluable_entries": self.not_evaluable_entries,
            "excluded_records": self.excluded_records,
            "excluded_reason_counts": [item.as_dict() for item in self.excluded_reason_counts],
            "group_count": self.group_count,
            "empty_group_count": self.empty_group_count,
            "warning_group_count": self.warning_group_count,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeStrategyAnalysisSummary":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis summary must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "decision_count",
                "signal_count",
                "evaluated_operations",
                "no_signal_decisions",
                "not_evaluable_entries",
                "excluded_records",
                "excluded_reason_counts",
                "group_count",
                "empty_group_count",
                "warning_group_count",
                "win_rate_percent",
                "mean_gross_return_percent_without_costs",
                "median_gross_return_percent_without_costs",
                "cumulative_simple_return_percent_without_costs",
                "max_loss_streak",
                "max_win_streak",
                "summary_hash",
            },
            name="analysis summary",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                decision_count=mapping["decision_count"],
                signal_count=mapping["signal_count"],
                evaluated_operations=mapping["evaluated_operations"],
                no_signal_decisions=mapping["no_signal_decisions"],
                not_evaluable_entries=mapping["not_evaluable_entries"],
                excluded_records=mapping["excluded_records"],
                excluded_reason_counts=tuple(HistoricalMultiTimeframeStrategyAnalysisReasonCount.from_dict(item) for item in mapping.get("excluded_reason_counts", ())),
                group_count=mapping["group_count"],
                empty_group_count=mapping["empty_group_count"],
                warning_group_count=mapping["warning_group_count"],
                win_rate_percent=mapping["win_rate_percent"],
                mean_gross_return_percent_without_costs=mapping["mean_gross_return_percent_without_costs"],
                median_gross_return_percent_without_costs=mapping["median_gross_return_percent_without_costs"],
                cumulative_simple_return_percent_without_costs=mapping["cumulative_simple_return_percent_without_costs"],
                max_loss_streak=mapping["max_loss_streak"],
                max_win_streak=mapping["max_win_streak"],
                summary_hash=mapping.get("summary_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis summary is incomplete.") from exc


def _default_period_windows(source: HistoricalMultiTimeframeStrategyAnalysisSource, *, period_count: int = 4) -> tuple[HistoricalMultiTimeframeStrategyAnalysisPeriodWindow, ...]:
    if period_count <= 0:
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError("period_count must be greater than zero.")
    start = source.period_start_utc
    end = source.period_end_utc
    span = end - start
    if span <= timedelta(0):
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis source period must have positive duration.")
    step = span / period_count
    windows: list[HistoricalMultiTimeframeStrategyAnalysisPeriodWindow] = []
    current_start = start
    for index in range(period_count):
        window_end = end if index == period_count - 1 else start + (step * (index + 1))
        windows.append(
            HistoricalMultiTimeframeStrategyAnalysisPeriodWindow(
                label=f"period_{index + 1}",
                start_utc=current_start,
                end_utc=window_end,
                inclusive_end=index == period_count - 1,
            )
        )
        current_start = window_end
    return tuple(windows)


def _period_label_for_time(period_windows: Sequence[HistoricalMultiTimeframeStrategyAnalysisPeriodWindow], decision_time_utc: datetime) -> str:
    decision_time = _require_utc_datetime(decision_time_utc, "decision_time_utc")
    for window in period_windows:
        if window.contains(decision_time):
            return window.label
    raise HistoricalMultiTimeframeStrategyAnalysisValidationError("decision time falls outside the frozen analysis periods.")



def _latest_sma(candles: Sequence[Any], period: int) -> Decimal:
    if len(candles) < period:
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError("warm-up is insufficient for the fixed analytical moving average.")
    closes = [candle.close for candle in candles[-period:]]
    return sum(closes, Decimal("0")) / Decimal(period)
def _mean_range_ratio_percent(candles: Sequence[Any], lookback: int) -> Decimal | None:
    if len(candles) < lookback:
        return None
    window = candles[-lookback:]
    ratios: list[Decimal] = []
    for candle in window:
        close = _require_decimal(candle.close, "volatility close")
        if close == 0:
            raise HistoricalMultiTimeframeStrategyIntegrityError("volatility close cannot be zero.")
        range_value = _require_decimal(candle.high, "volatility high") - _require_decimal(candle.low, "volatility low")
        ratios.append((range_value / close) * Decimal("100"))
    return sum(ratios, Decimal("0")) / Decimal(len(ratios))


def _bucket_volatility(value_percent: Decimal | None, protocol: HistoricalMultiTimeframeStrategyAnalysisProtocol) -> str:
    if value_percent is None:
        return "insufficient_history"
    if value_percent < protocol.volatility_low_threshold_percent:
        return "low"
    if value_percent < protocol.volatility_medium_threshold_percent:
        return "medium"
    return "high"


def _label_from_threshold(close: Decimal, sma: Decimal) -> tuple[str, Decimal]:
    if sma == 0:
        raise HistoricalMultiTimeframeStrategyAnalysisIntegrityError("moving average cannot be zero.")
    distance_percent = ((close - sma) / sma) * Decimal("100")
    if close > sma:
        return "above_sma", distance_percent
    return "at_or_below_sma", distance_percent


def _build_default_protocol_from_report(
    evaluation_report: HistoricalMultiTimeframeFirstStrategyEvaluationReport,
    *,
    period_windows: Sequence[HistoricalMultiTimeframeStrategyAnalysisPeriodWindow] | None = None,
    volatility_lookback_15m_candles: int = 32,
    volatility_low_threshold_percent: Decimal = Decimal("1"),
    volatility_medium_threshold_percent: Decimal = Decimal("2"),
    minimum_group_sample_size: int = 5,
) -> HistoricalMultiTimeframeStrategyAnalysisProtocol:
    strategy_report = evaluation_report.strategy_report
    source = HistoricalMultiTimeframeStrategyAnalysisSource(
        evaluation_name=evaluation_report.protocol.evaluation_name,
        evaluation_version=evaluation_report.protocol.evaluation_version,
        strategy_hypothesis_version=evaluation_report.protocol.strategy_hypothesis_version,
        strategy_config_hash=evaluation_report.protocol.strategy_config_hash,
        strategy_factory_hash=evaluation_report.protocol.strategy_factory_hash,
        strategy_report_hash=evaluation_report.strategy_report.report_hash,
        evaluation_protocol_hash=evaluation_report.protocol.protocol_hash,
        evaluation_hash=evaluation_report.evaluation_hash,
        replay_hash=strategy_report.replay.replay_hash,
        bundle_hash=strategy_report.replay.bundle.bundle_hash,
        alignment_policy_hash=strategy_report.context_series.policy.alignment_policy_hash,
        context_policy_hash=strategy_report.context_series.policy.context_policy_hash,
        symbol=strategy_report.factory.config.symbol,
        base_interval=strategy_report.factory.config.base_interval,
        one_hour_interval=strategy_report.factory.config.one_hour_interval,
        four_hour_interval=strategy_report.factory.config.four_hour_interval,
        period_start_utc=evaluation_report.period_start_utc,
        period_end_utc=evaluation_report.period_end_utc,
        snapshot_count=evaluation_report.snapshot_count,
    )
    if period_windows is None:
        period_windows = _default_period_windows(source)
    return HistoricalMultiTimeframeStrategyAnalysisProtocol(
        source=source,
        period_windows=tuple(period_windows),
        volatility_lookback_15m_candles=volatility_lookback_15m_candles,
        volatility_low_threshold_percent=volatility_low_threshold_percent,
        volatility_medium_threshold_percent=volatility_medium_threshold_percent,
        minimum_group_sample_size=minimum_group_sample_size,
    )


def build_historical_multitimeframe_strategy_analysis_protocol(
    evaluation_report: HistoricalMultiTimeframeFirstStrategyEvaluationReport,
    *,
    period_windows: Sequence[HistoricalMultiTimeframeStrategyAnalysisPeriodWindow] | None = None,
    volatility_lookback_15m_candles: int = 32,
    volatility_low_threshold_percent: Decimal = Decimal("1"),
    volatility_medium_threshold_percent: Decimal = Decimal("2"),
    minimum_group_sample_size: int = 5,
) -> HistoricalMultiTimeframeStrategyAnalysisProtocol:
    if not isinstance(evaluation_report, HistoricalMultiTimeframeFirstStrategyEvaluationReport):
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError("evaluation_report must be a HistoricalMultiTimeframeFirstStrategyEvaluationReport instance.")
    return _build_default_protocol_from_report(
        evaluation_report,
        period_windows=period_windows,
        volatility_lookback_15m_candles=volatility_lookback_15m_candles,
        volatility_low_threshold_percent=volatility_low_threshold_percent,
        volatility_medium_threshold_percent=volatility_medium_threshold_percent,
        minimum_group_sample_size=minimum_group_sample_size,
    )


def _build_observations(
    evaluation_report: HistoricalMultiTimeframeFirstStrategyEvaluationReport,
    protocol: HistoricalMultiTimeframeStrategyAnalysisProtocol,
) -> tuple[HistoricalMultiTimeframeStrategyAnalysisObservation, ...]:
    strategy_report = evaluation_report.strategy_report
    contexts = strategy_report.context_series.contexts
    if len(evaluation_report.results) != len(contexts):
        raise HistoricalMultiTimeframeStrategyAnalysisIntegrityError("evaluation results diverge from the frozen strategy contexts.")
    observations: list[HistoricalMultiTimeframeStrategyAnalysisObservation] = []
    for decision, result, context in zip(strategy_report.decisions, evaluation_report.results, contexts):
        if result.decision_hash != decision.decision_hash:
            raise HistoricalMultiTimeframeStrategyAnalysisIntegrityError("analysis result decision hash diverges from the frozen strategy report.")
        if result.decision_time_utc != decision.decision_time_utc:
            raise HistoricalMultiTimeframeStrategyAnalysisIntegrityError("analysis result decision time diverges from the frozen strategy report.")
        if decision.decision_time_utc != context.snapshot.decision_time_utc:
            raise HistoricalMultiTimeframeStrategyAnalysisIntegrityError("decision time diverges from the frozen historical context.")
        period_label = _period_label_for_time(protocol.period_windows, decision.decision_time_utc)
        one_hour_window = context.supporting_windows[0].candles
        four_hour_window = context.supporting_windows[1].candles
        config = strategy_report.factory.config
        four_hour_sma = _latest_sma(four_hour_window, config.four_hour_sma_period)
        one_hour_sma = _latest_sma(one_hour_window, config.one_hour_sma_period)
        trend_label, trend_distance_percent = _label_from_threshold(four_hour_window[-1].close, four_hour_sma)
        price_label, price_distance_percent = _label_from_threshold(one_hour_window[-1].close, one_hour_sma)
        volatility_percent = _mean_range_ratio_percent(context.base_window.candles[:-1], protocol.volatility_lookback_15m_candles)
        volatility_label = _bucket_volatility(volatility_percent, protocol)
        observation = HistoricalMultiTimeframeStrategyAnalysisObservation(
            decision_hash=decision.decision_hash,
            context_hash=context.context_hash,
            result_hash=result.result_hash,
            decision_time_utc=decision.decision_time_utc,
            period_label=period_label,
            trend_4h_label=trend_label,
            price_1h_label=price_label,
            volatility_label=volatility_label,
            trend_4h_close=four_hour_window[-1].close,
            trend_4h_sma=four_hour_sma,
            trend_4h_distance_percent=trend_distance_percent,
            price_1h_close=one_hour_window[-1].close,
            price_1h_sma=one_hour_sma,
            price_1h_distance_percent=price_distance_percent,
            volatility_percent=volatility_percent,
            volatility_lookback_15m_candles=protocol.volatility_lookback_15m_candles,
            signal_generated=result.signal_generated,
            status=result.status,
            reasons=result.reasons,
            gross_return_percent_without_costs=result.gross_return_percent_without_costs,
        )
        observations.append(observation)
    return tuple(observations)


def _group_key(observation: HistoricalMultiTimeframeStrategyAnalysisObservation) -> tuple[str, str, str, str]:
    return (observation.period_label, observation.trend_4h_label, observation.price_1h_label, observation.volatility_label)


def _build_group(
    protocol: HistoricalMultiTimeframeStrategyAnalysisProtocol,
    observations: Sequence[HistoricalMultiTimeframeStrategyAnalysisObservation],
    *,
    period_label: str,
    trend_4h_label: str,
    price_1h_label: str,
    volatility_label: str,
) -> HistoricalMultiTimeframeStrategyAnalysisGroup:
    selected = [observation for observation in observations if _group_key(observation) == (period_label, trend_4h_label, price_1h_label, volatility_label)]
    decision_count = len(selected)
    signal_count = sum(1 for item in selected if item.signal_generated)
    evaluated_returns = [item.gross_return_percent_without_costs for item in selected if item.status == "evaluated" and item.gross_return_percent_without_costs is not None]
    evaluated_operations = len(evaluated_returns)
    no_signal_decisions = sum(1 for item in selected if item.status == "no_signal")
    not_evaluable_entries = sum(1 for item in selected if item.status == "not_evaluable")
    no_signal_reason_counts = tuple(
        HistoricalMultiTimeframeStrategyAnalysisReasonCount(reason=reason, count=count)
        for reason, count in sorted(Counter(reason for item in selected if item.status == "no_signal" for reason in item.reasons).items())
    )
    not_evaluable_reason_counts = tuple(
        HistoricalMultiTimeframeStrategyAnalysisReasonCount(reason=reason, count=count)
        for reason, count in sorted(Counter(reason for item in selected if item.status == "not_evaluable" for reason in item.reasons).items())
    )
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
    warning = None
    if decision_count == 0:
        warning = "no observations matched this fixed analytical cut."
    elif decision_count < protocol.minimum_group_sample_size:
        warning = f"sample size is small (decision_count={decision_count}, minimum_group_sample_size={protocol.minimum_group_sample_size})."
    if evaluated_operations == 0 and warning is None:
        warning = "no evaluated operations were available for this fixed analytical cut."
    return HistoricalMultiTimeframeStrategyAnalysisGroup(
        period_label=period_label,
        trend_4h_label=trend_4h_label,
        price_1h_label=price_1h_label,
        volatility_label=volatility_label,
        decision_count=decision_count,
        signal_count=signal_count,
        evaluated_operations=evaluated_operations,
        no_signal_decisions=no_signal_decisions,
        not_evaluable_entries=not_evaluable_entries,
        no_signal_reason_counts=no_signal_reason_counts,
        not_evaluable_reason_counts=not_evaluable_reason_counts,
        win_rate_percent=win_rate_percent,
        mean_gross_return_percent_without_costs=mean_return,
        median_gross_return_percent_without_costs=median_return,
        cumulative_simple_return_percent_without_costs=cumulative_return,
        max_loss_streak=_max_loss_streak(evaluated_returns),
        max_win_streak=_max_win_streak(evaluated_returns),
        sample_warning=warning,
    )


def _max_loss_streak(returns: Sequence[Decimal]) -> int:
    streak = 0
    best = 0
    for value in returns:
        if value < 0:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best


def _max_win_streak(returns: Sequence[Decimal]) -> int:
    streak = 0
    best = 0
    for value in returns:
        if value > 0:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best


def _build_groups(
    protocol: HistoricalMultiTimeframeStrategyAnalysisProtocol,
    observations: Sequence[HistoricalMultiTimeframeStrategyAnalysisObservation],
) -> tuple[HistoricalMultiTimeframeStrategyAnalysisGroup, ...]:
    groups = [
        _build_group(
            protocol,
            observations,
            period_label=period_window.label,
            trend_4h_label=trend_4h_label,
            price_1h_label=price_1h_label,
            volatility_label=volatility_label,
        )
        for period_window, trend_4h_label, price_1h_label, volatility_label in product(
            protocol.period_windows,
            protocol.trend_labels,
            protocol.price_labels,
            protocol.volatility_labels,
        )
    ]
    return tuple(groups)


def _build_summary(
    protocol: HistoricalMultiTimeframeStrategyAnalysisProtocol,
    observations: Sequence[HistoricalMultiTimeframeStrategyAnalysisObservation],
    groups: Sequence[HistoricalMultiTimeframeStrategyAnalysisGroup],
) -> HistoricalMultiTimeframeStrategyAnalysisSummary:
    decision_count = len(observations)
    signal_count = sum(1 for item in observations if item.signal_generated)
    evaluated_returns = [item.gross_return_percent_without_costs for item in observations if item.status == "evaluated" and item.gross_return_percent_without_costs is not None]
    evaluated_operations = len(evaluated_returns)
    no_signal_decisions = sum(1 for item in observations if item.status == "no_signal")
    not_evaluable_entries = sum(1 for item in observations if item.status == "not_evaluable")
    excluded_reason_counts = tuple(
        HistoricalMultiTimeframeStrategyAnalysisReasonCount(reason=reason, count=count)
        for reason, count in sorted(
            Counter(reason for item in observations if item.status != "evaluated" for reason in item.reasons).items()
        )
    )
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
    empty_group_count = sum(1 for group in groups if group.decision_count == 0)
    warning_group_count = sum(1 for group in groups if group.sample_warning)
    return HistoricalMultiTimeframeStrategyAnalysisSummary(
        decision_count=decision_count,
        signal_count=signal_count,
        evaluated_operations=evaluated_operations,
        no_signal_decisions=no_signal_decisions,
        not_evaluable_entries=not_evaluable_entries,
        excluded_records=no_signal_decisions + not_evaluable_entries,
        excluded_reason_counts=excluded_reason_counts,
        group_count=len(groups),
        empty_group_count=empty_group_count,
        warning_group_count=warning_group_count,
        win_rate_percent=win_rate_percent,
        mean_gross_return_percent_without_costs=mean_return,
        median_gross_return_percent_without_costs=median_return,
        cumulative_simple_return_percent_without_costs=cumulative_return,
        max_loss_streak=_max_loss_streak(evaluated_returns),
        max_win_streak=_max_win_streak(evaluated_returns),
    )


def _build_analysis_report(
    evaluation_report: HistoricalMultiTimeframeFirstStrategyEvaluationReport,
    *,
    protocol: HistoricalMultiTimeframeStrategyAnalysisProtocol | None = None,
) -> "HistoricalMultiTimeframeStrategyAnalysisReport":
    if not isinstance(evaluation_report, HistoricalMultiTimeframeFirstStrategyEvaluationReport):
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError("evaluation_report must be a HistoricalMultiTimeframeFirstStrategyEvaluationReport instance.")
    if protocol is None:
        protocol = build_historical_multitimeframe_strategy_analysis_protocol(evaluation_report)
    elif protocol.source.evaluation_hash != evaluation_report.evaluation_hash:
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis protocol diverges from the frozen evaluation report.")
    observations = _build_observations(evaluation_report, protocol)
    groups = _build_groups(protocol, observations)
    summary = _build_summary(protocol, observations, groups)
    return HistoricalMultiTimeframeStrategyAnalysisReport(
        source_evaluation_report=evaluation_report,
        protocol=protocol,
        observations=observations,
        groups=groups,
        summary=summary,
    )


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeStrategyAnalysisReport:
    source_evaluation_report: HistoricalMultiTimeframeFirstStrategyEvaluationReport
    protocol: HistoricalMultiTimeframeStrategyAnalysisProtocol
    observations: tuple[HistoricalMultiTimeframeStrategyAnalysisObservation, ...]
    groups: tuple[HistoricalMultiTimeframeStrategyAnalysisGroup, ...]
    summary: HistoricalMultiTimeframeStrategyAnalysisSummary
    schema_version: int = HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    report_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.source_evaluation_report, HistoricalMultiTimeframeFirstStrategyEvaluationReport):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("source_evaluation_report must be a historical multi-timeframe evaluation report instance.")
        if not isinstance(self.protocol, HistoricalMultiTimeframeStrategyAnalysisProtocol):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("protocol must be an analysis protocol instance.")
        if not isinstance(self.observations, tuple):
            object.__setattr__(self, "observations", tuple(self.observations))
        if not isinstance(self.groups, tuple):
            object.__setattr__(self, "groups", tuple(self.groups))
        if not isinstance(self.summary, HistoricalMultiTimeframeStrategyAnalysisSummary):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("summary must be an analysis summary instance.")
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis report schema_version must be 1.")
        if self.historical_research_only is not True:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("paper_promotion_eligible must be false.")
        if self.source_evaluation_report.historical_research_only is not True:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("source evaluation report must be research-only.")
        if self.source_evaluation_report.operational_evidence is not False:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("source evaluation report must not be operational evidence.")
        if self.source_evaluation_report.paper_promotion_eligible is not False:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("source evaluation report must not be promotion eligible.")
        if self.protocol.source.evaluation_hash != self.source_evaluation_report.evaluation_hash:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis protocol source diverges from the frozen evaluation report.")
        _research_only_flags(self.protocol.source.historical_research_only, self.protocol.source.operational_evidence, self.protocol.source.paper_promotion_eligible)
        if self.protocol.source.snapshot_count != len(self.observations):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis observations must match the frozen snapshot count.")
        if self.summary.decision_count != len(self.observations):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis summary decision_count diverges from observations.")
        expected_groups = _build_groups(self.protocol, self.observations)
        if self.groups != expected_groups:
            raise HistoricalMultiTimeframeStrategyAnalysisIntegrityError("analysis groups diverge from the frozen observations.")
        expected_summary = _build_summary(self.protocol, self.observations, self.groups)
        if self.summary != expected_summary:
            raise HistoricalMultiTimeframeStrategyAnalysisIntegrityError("analysis summary diverges from the frozen observations.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.report_hash:
            if self.report_hash != expected:
                raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis report hash mismatch.")
        else:
            object.__setattr__(self, "report_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "source_evaluation_report": self.source_evaluation_report.as_dict(),
            "protocol": self.protocol.as_dict(),
            "observations": [observation.as_dict() for observation in self.observations],
            "groups": [group.as_dict() for group in self.groups],
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeStrategyAnalysisReport":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis report must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "source_evaluation_report",
                "protocol",
                "observations",
                "groups",
                "summary",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "report_hash",
            },
            name="analysis report",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                source_evaluation_report=HistoricalMultiTimeframeFirstStrategyEvaluationReport.from_dict(mapping["source_evaluation_report"]),
                protocol=HistoricalMultiTimeframeStrategyAnalysisProtocol.from_dict(mapping["protocol"]),
                observations=tuple(HistoricalMultiTimeframeStrategyAnalysisObservation.from_dict(item) for item in mapping["observations"]),
                groups=tuple(HistoricalMultiTimeframeStrategyAnalysisGroup.from_dict(item) for item in mapping["groups"]),
                summary=HistoricalMultiTimeframeStrategyAnalysisSummary.from_dict(mapping["summary"]),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                report_hash=mapping.get("report_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis report is incomplete.") from exc


def run_historical_multitimeframe_strategy_analysis(
    evaluation_report: HistoricalMultiTimeframeFirstStrategyEvaluationReport,
    *,
    protocol: HistoricalMultiTimeframeStrategyAnalysisProtocol | None = None,
    output_file: str | Path | None = None,
) -> HistoricalMultiTimeframeStrategyAnalysisReport:
    if not isinstance(evaluation_report, HistoricalMultiTimeframeFirstStrategyEvaluationReport):
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError("evaluation_report must be a HistoricalMultiTimeframeFirstStrategyEvaluationReport instance.")
    report = _build_analysis_report(evaluation_report, protocol=protocol)
    if output_file is not None:
        save_historical_multitimeframe_strategy_analysis_report(output_file, report)
    return report


def _read(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError("analysis report not found.") from exc
    except Exception as exc:
        raise HistoricalMultiTimeframeStrategyAnalysisIntegrityError("analysis report is invalid JSON.") from exc
    if not isinstance(value, Mapping):
        raise HistoricalMultiTimeframeStrategyAnalysisIntegrityError("analysis report must be a JSON object.")
    return value


def load_historical_multitimeframe_strategy_analysis_report(path: str | Path) -> HistoricalMultiTimeframeStrategyAnalysisReport:
    payload = _read(Path(path))
    try:
        report = HistoricalMultiTimeframeStrategyAnalysisReport.from_dict(payload)
    except (KeyError, TypeError, HistoricalMultiTimeframeStrategyAnalysisValidationError, HistoricalMultiTimeframeStrategyAnalysisIntegrityError, HistoricalMultiTimeframeFirstStrategyEvaluationValidationError, HistoricalMultiTimeframeFirstStrategyEvaluationError, HistoricalDataValidationError) as exc:
        raise HistoricalMultiTimeframeStrategyAnalysisIntegrityError(str(exc)) from exc
    if report.as_dict() != payload:
        raise HistoricalMultiTimeframeStrategyAnalysisIntegrityError("analysis report payload mismatch.")
    return report


def save_historical_multitimeframe_strategy_analysis_report(
    path: str | Path,
    report: HistoricalMultiTimeframeStrategyAnalysisReport,
) -> HistoricalMultiTimeframeStrategyAnalysisReport:
    file_path = Path(path)
    payload = report.as_dict()
    if file_path.exists():
        existing = load_historical_multitimeframe_strategy_analysis_report(file_path)
        if existing.as_dict() != payload:
            raise HistoricalMultiTimeframeStrategyAnalysisConflictError("analysis report already exists and differs.")
        return existing
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_name(f".{file_path.name}.{os.getpid()}.{id(report)}.tmp")
    try:
        tmp.write_text(_canonical_json(payload), encoding="utf-8")
        try:
            os.link(tmp, file_path)
        except FileExistsError:
            existing = load_historical_multitimeframe_strategy_analysis_report(file_path)
            if existing.as_dict() != payload:
                raise HistoricalMultiTimeframeStrategyAnalysisConflictError("analysis report already exists and differs.")
            return existing
    except Exception as exc:
        if isinstance(exc, HistoricalMultiTimeframeStrategyAnalysisConflictError):
            raise
        raise HistoricalMultiTimeframeStrategyAnalysisValidationError("failed to write analysis report atomically.") from exc
    finally:
        tmp.unlink(missing_ok=True)
    return report


def verify_historical_multitimeframe_strategy_analysis_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_multitimeframe_strategy_analysis_report(path)
    return {
        "verified": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "source_hash": report.protocol.source.source_hash,
        "classification": "historical_research_only",
    }


def status_historical_multitimeframe_strategy_analysis_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_multitimeframe_strategy_analysis_report(path)
    return {
        "exists": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "source_hash": report.protocol.source.source_hash,
        "evaluation_hash": report.protocol.source.evaluation_hash,
        "strategy_report_hash": report.protocol.source.strategy_report_hash,
        "period_start_utc": _utc_iso(report.protocol.source.period_start_utc),
        "period_end_utc": _utc_iso(report.protocol.source.period_end_utc),
        "snapshot_count": report.protocol.source.snapshot_count,
        "decision_count": report.summary.decision_count,
        "evaluated_operations": report.summary.evaluated_operations,
        "excluded_records": report.summary.excluded_records,
        "empty_group_count": report.summary.empty_group_count,
        "warning_group_count": report.summary.warning_group_count,
        "classification": "historical_research_only",
    }


def reject_historical_multitimeframe_strategy_analysis_promotion(
    _: HistoricalMultiTimeframeStrategyAnalysisReport,
) -> None:
    raise HistoricalMultiTimeframeStrategyAnalysisPromotionError("multi-timeframe historical analysis is not promotion evidence.")


__all__ = [
    "HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_NAME",
    "HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_PERIOD_CUT_VERSION",
    "HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_PRICE_CUT_VERSION",
    "HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_SCHEMA_VERSION",
    "HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_TREND_CUT_VERSION",
    "HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_TREND_LABELS",
    "HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_VERSION",
    "HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_VOLATILITY_CUT_VERSION",
    "HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_VOLATILITY_LABELS",
    "HistoricalMultiTimeframeStrategyAnalysisConflictError",
    "HistoricalMultiTimeframeStrategyAnalysisError",
    "HistoricalMultiTimeframeStrategyAnalysisGroup",
    "HistoricalMultiTimeframeStrategyAnalysisIntegrityError",
    "HistoricalMultiTimeframeStrategyAnalysisObservation",
    "HistoricalMultiTimeframeStrategyAnalysisPeriodWindow",

    "HistoricalMultiTimeframeStrategyAnalysisProtocol",
    "HistoricalMultiTimeframeStrategyAnalysisPromotionError",
    "HistoricalMultiTimeframeStrategyAnalysisReasonCount",
    "HistoricalMultiTimeframeStrategyAnalysisReport",
    "HistoricalMultiTimeframeStrategyAnalysisSource",
    "HistoricalMultiTimeframeStrategyAnalysisSummary",
    "HistoricalMultiTimeframeStrategyAnalysisValidationError",
    "build_historical_multitimeframe_strategy_analysis_protocol",
    "load_historical_multitimeframe_strategy_analysis_report",
    "reject_historical_multitimeframe_strategy_analysis_promotion",
    "run_historical_multitimeframe_strategy_analysis",
    "save_historical_multitimeframe_strategy_analysis_report",
    "status_historical_multitimeframe_strategy_analysis_report",
    "verify_historical_multitimeframe_strategy_analysis_report",
]
