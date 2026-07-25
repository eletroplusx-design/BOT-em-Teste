"""Research-only temporal consistency audit for the Phase 14C historical futures pipeline.

This module consumes the immutable Phase 14B validation report as the canonical
source of the three temporal windows and reuses the Phase 13D analysis groups
and observations to build a deterministic window x sub-regime matrix.

The audit is descriptive only. It does not approve, reject, optimize, or
promote anything operational.
"""

from __future__ import annotations

from collections import Counter
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
from historical_futures_market_validation import (
    HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES,
    HistoricalFuturesMarketValidationError,
    HistoricalFuturesMarketValidationReport,
    HistoricalFuturesMarketValidationValidationError,
)
from historical_multitimeframe_analysis import (
    HistoricalMultiTimeframeStrategyAnalysisGroup,
    HistoricalMultiTimeframeStrategyAnalysisObservation,
    HistoricalMultiTimeframeStrategyAnalysisReasonCount,
    HistoricalMultiTimeframeStrategyAnalysisReport,
    HistoricalMultiTimeframeStrategyAnalysisValidationError,
)
from market_data import HistoricalDataValidationError

HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_SCHEMA_VERSION = 1
HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_PROTOCOL_NAME = (
    "historical_futures_market_temporal_regime_consistency_audit"
)
HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_PROTOCOL_VERSION = "v1"
HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT = "absent"
HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE = "insufficient_sample"
HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED = "observed"
HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUSES: tuple[str, ...] = (
    HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT,
    HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE,
    HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED,
)


class HistoricalFuturesMarketTemporalConsistencyError(Exception):
    pass


class HistoricalFuturesMarketTemporalConsistencyValidationError(HistoricalFuturesMarketTemporalConsistencyError):
    pass


class HistoricalFuturesMarketTemporalConsistencyIntegrityError(
    HistoricalFuturesMarketTemporalConsistencyValidationError
):
    pass


class HistoricalFuturesMarketTemporalConsistencyConflictError(
    HistoricalFuturesMarketTemporalConsistencyIntegrityError
):
    pass


class HistoricalFuturesMarketTemporalConsistencyPromotionError(
    HistoricalFuturesMarketTemporalConsistencyValidationError
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalFuturesMarketTemporalConsistencyValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalFuturesMarketTemporalConsistencyValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalFuturesMarketTemporalConsistencyValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalFuturesMarketTemporalConsistencyValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if type(value) is bool:
        raise HistoricalFuturesMarketTemporalConsistencyValidationError(f"{field_name} must be numeric.")
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise HistoricalFuturesMarketTemporalConsistencyValidationError(f"{field_name} must be numeric.") from exc


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise HistoricalFuturesMarketTemporalConsistencyValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise HistoricalFuturesMarketTemporalConsistencyValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _validate_exact_keys(mapping: Mapping[str, Any], *, allowed: set[str], name: str) -> None:
    extra = set(mapping) - allowed
    if extra:
        raise HistoricalFuturesMarketTemporalConsistencyValidationError(f"{name} contains unknown fields: {sorted(extra)!r}.")


def _research_only(historical_research_only: bool, operational_evidence: bool, paper_promotion_eligible: bool) -> None:
    if historical_research_only is not True:
        raise HistoricalFuturesMarketTemporalConsistencyValidationError("historical_research_only must be true.")
    if operational_evidence is not False:
        raise HistoricalFuturesMarketTemporalConsistencyValidationError("operational_evidence must be false.")
    if paper_promotion_eligible is not False:
        raise HistoricalFuturesMarketTemporalConsistencyValidationError("paper_promotion_eligible must be false.")


def _window_contains(window: Any, decision_time_utc: datetime) -> bool:
    decision_time = _require_utc_datetime(decision_time_utc, "decision_time_utc")
    return window.start_utc <= decision_time <= window.end_utc


def _observations_for_group_and_window(
    observations: Sequence[HistoricalMultiTimeframeStrategyAnalysisObservation],
    *,
    window: Any,
    group: HistoricalMultiTimeframeStrategyAnalysisGroup,
) -> tuple[HistoricalMultiTimeframeStrategyAnalysisObservation, ...]:
    selected = [
        observation
        for observation in observations
        if _window_contains(window, observation.decision_time_utc)
        and (
            observation.period_label,
            observation.trend_4h_label,
            observation.price_1h_label,
            observation.volatility_label,
        )
        == (
            group.period_label,
            group.trend_4h_label,
            group.price_1h_label,
            group.volatility_label,
        )
    ]
    return tuple(selected)


def _returns_for_observations(
    observations: Sequence[HistoricalMultiTimeframeStrategyAnalysisObservation],
) -> list[Decimal]:
    return [
        item.gross_return_percent_without_costs
        for item in observations
        if item.status == "evaluated" and item.gross_return_percent_without_costs is not None
    ]


def _build_metrics(
    observations: Sequence[HistoricalMultiTimeframeStrategyAnalysisObservation],
) -> tuple[
    int,
    int,
    int,
    int,
    int,
    tuple[HistoricalMultiTimeframeStrategyAnalysisReasonCount, ...],
    tuple[HistoricalMultiTimeframeStrategyAnalysisReasonCount, ...],
    Decimal,
    Decimal,
    Decimal,
    Decimal,
    int,
    int,
]:
    decision_count = len(observations)
    signal_count = sum(1 for item in observations if item.signal_generated)
    evaluated_returns = _returns_for_observations(observations)
    evaluated_operations = len(evaluated_returns)
    no_signal_decisions = sum(1 for item in observations if item.status == "no_signal")
    not_evaluable_entries = sum(1 for item in observations if item.status == "not_evaluable")
    no_signal_reason_counts = tuple(
        HistoricalMultiTimeframeStrategyAnalysisReasonCount(reason=reason, count=count)
        for reason, count in sorted(
            Counter(reason for item in observations if item.status == "no_signal" for reason in item.reasons).items()
        )
    )
    not_evaluable_reason_counts = tuple(
        HistoricalMultiTimeframeStrategyAnalysisReasonCount(reason=reason, count=count)
        for reason, count in sorted(
            Counter(reason for item in observations if item.status == "not_evaluable" for reason in item.reasons).items()
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
        no_signal_reason_counts,
        not_evaluable_reason_counts,
        win_rate_percent,
        mean_return,
        median_return,
        cumulative_return,
        max_loss_streak,
        max_win_streak,
    )


def _cell_status(
    decision_count: int,
    evaluated_operations: int,
    minimum_group_sample_size: int,
) -> str:
    if decision_count == 0:
        return HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT
    if decision_count < minimum_group_sample_size or evaluated_operations == 0:
        return HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE
    return HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED


def _cell_warning(
    status: str,
    *,
    decision_count: int,
    evaluated_operations: int,
    minimum_group_sample_size: int,
) -> str | None:
    if status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT:
        return "no observations matched this fixed analytical cut."
    if status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE:
        if evaluated_operations == 0:
            return "no evaluated operations were available for this fixed analytical cut."
        return (
            "sample size is small "
            f"(decision_count={decision_count}, minimum_group_sample_size={minimum_group_sample_size})."
        )
    return None


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketTemporalConsistencyProtocol:
    schema_version: int
    protocol_name: str = HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_PROTOCOL_NAME
    protocol_version: str = HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_PROTOCOL_VERSION
    validation_report_hash: str = ""
    contract_hash: str = ""
    contract_temporal_split_hash: str = ""
    analysis_report_hash: str = ""
    analysis_protocol_hash: str = ""
    evaluation_hash: str = ""
    strategy_report_hash: str = ""
    replay_hash: str = ""
    bundle_hash: str = ""
    source_hash: str = ""
    reference_window_hash: str = ""
    validation_window_hash: str = ""
    test_window_hash: str = ""
    source_group_hashes: tuple[str, ...] = ()
    window_count: int = 3
    regime_count: int = 0
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    protocol_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol_name", _require_str(self.protocol_name, "protocol_name"))
        object.__setattr__(self, "protocol_version", _require_str(self.protocol_version, "protocol_version"))
        object.__setattr__(self, "validation_report_hash", _require_str(self.validation_report_hash, "validation_report_hash"))
        object.__setattr__(self, "contract_hash", _require_str(self.contract_hash, "contract_hash"))
        object.__setattr__(self, "contract_temporal_split_hash", _require_str(self.contract_temporal_split_hash, "contract_temporal_split_hash"))
        object.__setattr__(self, "analysis_report_hash", _require_str(self.analysis_report_hash, "analysis_report_hash"))
        object.__setattr__(self, "analysis_protocol_hash", _require_str(self.analysis_protocol_hash, "analysis_protocol_hash"))
        object.__setattr__(self, "evaluation_hash", _require_str(self.evaluation_hash, "evaluation_hash"))
        object.__setattr__(self, "strategy_report_hash", _require_str(self.strategy_report_hash, "strategy_report_hash"))
        object.__setattr__(self, "replay_hash", _require_str(self.replay_hash, "replay_hash"))
        object.__setattr__(self, "bundle_hash", _require_str(self.bundle_hash, "bundle_hash"))
        object.__setattr__(self, "source_hash", _require_str(self.source_hash, "source_hash"))
        object.__setattr__(self, "reference_window_hash", _require_str(self.reference_window_hash, "reference_window_hash"))
        object.__setattr__(self, "validation_window_hash", _require_str(self.validation_window_hash, "validation_window_hash"))
        object.__setattr__(self, "test_window_hash", _require_str(self.test_window_hash, "test_window_hash"))
        if not isinstance(self.source_group_hashes, tuple):
            object.__setattr__(self, "source_group_hashes", tuple(self.source_group_hashes))
        object.__setattr__(self, "source_group_hashes", tuple(_require_str(item, "source_group_hash") for item in self.source_group_hashes))
        object.__setattr__(self, "window_count", _require_int(self.window_count, "window_count"))
        object.__setattr__(self, "regime_count", _require_int(self.regime_count, "regime_count"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_SCHEMA_VERSION:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency schema_version must be 1.")
        if self.protocol_name != HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_PROTOCOL_NAME:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("protocol_name diverges from the trusted audit.")
        if self.protocol_version != HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_PROTOCOL_VERSION:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("protocol_version diverges from the trusted audit.")
        if self.window_count != len(HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES):
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency must cover three windows.")
        if self.regime_count != len(self.source_group_hashes):
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("regime_count must equal the number of source groups.")
        if len({self.reference_window_hash, self.validation_window_hash, self.test_window_hash}) != 3:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("window hashes must remain distinct.")
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.protocol_hash:
            if self.protocol_hash != expected:
                raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency protocol hash mismatch.")
        else:
            object.__setattr__(self, "protocol_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "protocol_name": self.protocol_name,
            "protocol_version": self.protocol_version,
            "validation_report_hash": self.validation_report_hash,
            "reference_window_hash": self.reference_window_hash,
            "validation_window_hash": self.validation_window_hash,
            "test_window_hash": self.test_window_hash,
            "source_group_hashes": list(self.source_group_hashes),
            "window_count": self.window_count,
            "regime_count": self.regime_count,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }
        if include_hash:
            payload.update(
                {
                    "contract_hash": self.contract_hash,
                    "contract_temporal_split_hash": self.contract_temporal_split_hash,
                    "analysis_report_hash": self.analysis_report_hash,
                    "analysis_protocol_hash": self.analysis_protocol_hash,
                    "evaluation_hash": self.evaluation_hash,
                    "strategy_report_hash": self.strategy_report_hash,
                    "replay_hash": self.replay_hash,
                    "bundle_hash": self.bundle_hash,
                    "source_hash": self.source_hash,
                }
            )
        if include_hash:
            payload["protocol_hash"] = self.protocol_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketTemporalConsistencyProtocol":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency protocol must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "protocol_name",
                "protocol_version",
                "validation_report_hash",
                "contract_hash",
                "contract_temporal_split_hash",
                "analysis_report_hash",
                "analysis_protocol_hash",
                "evaluation_hash",
                "strategy_report_hash",
                "replay_hash",
                "bundle_hash",
                "source_hash",
                "reference_window_hash",
                "validation_window_hash",
                "test_window_hash",
                "source_group_hashes",
                "window_count",
                "regime_count",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "protocol_hash",
            },
            name="temporal consistency protocol",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                protocol_name=mapping["protocol_name"],
                protocol_version=mapping["protocol_version"],
                validation_report_hash=mapping["validation_report_hash"],
                contract_hash=mapping["contract_hash"],
                contract_temporal_split_hash=mapping["contract_temporal_split_hash"],
                analysis_report_hash=mapping["analysis_report_hash"],
                analysis_protocol_hash=mapping["analysis_protocol_hash"],
                evaluation_hash=mapping["evaluation_hash"],
                strategy_report_hash=mapping["strategy_report_hash"],
                replay_hash=mapping["replay_hash"],
                bundle_hash=mapping["bundle_hash"],
                source_hash=mapping["source_hash"],
                reference_window_hash=mapping["reference_window_hash"],
                validation_window_hash=mapping["validation_window_hash"],
                test_window_hash=mapping["test_window_hash"],
                source_group_hashes=tuple(mapping.get("source_group_hashes", ())),
                window_count=mapping["window_count"],
                regime_count=mapping["regime_count"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                protocol_hash=mapping.get("protocol_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency protocol is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketTemporalConsistencyCell:
    window_name: str
    window_start_utc: datetime
    window_end_utc: datetime
    window_hash: str
    source_group: HistoricalMultiTimeframeStrategyAnalysisGroup
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
    status: str
    sample_warning: str | None = None
    schema_version: int = HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_SCHEMA_VERSION
    cell_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_name", _require_str(self.window_name, "window_name").lower())
        object.__setattr__(self, "window_start_utc", _require_utc_datetime(self.window_start_utc, "window_start_utc"))
        object.__setattr__(self, "window_end_utc", _require_utc_datetime(self.window_end_utc, "window_end_utc"))
        object.__setattr__(self, "window_hash", _require_str(self.window_hash, "window_hash"))
        if not isinstance(self.source_group, HistoricalMultiTimeframeStrategyAnalysisGroup):
            raise HistoricalFuturesMarketTemporalConsistencyValidationError(
                "source_group must be a HistoricalMultiTimeframeStrategyAnalysisGroup instance."
            )
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
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("no_signal_reason_counts must contain reason counts.")
        if any(not isinstance(item, HistoricalMultiTimeframeStrategyAnalysisReasonCount) for item in self.not_evaluable_reason_counts):
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("not_evaluable_reason_counts must contain reason counts.")
        object.__setattr__(self, "win_rate_percent", _require_decimal(self.win_rate_percent, "win_rate_percent"))
        object.__setattr__(self, "mean_gross_return_percent_without_costs", _require_decimal(self.mean_gross_return_percent_without_costs, "mean_gross_return_percent_without_costs"))
        object.__setattr__(self, "median_gross_return_percent_without_costs", _require_decimal(self.median_gross_return_percent_without_costs, "median_gross_return_percent_without_costs"))
        object.__setattr__(self, "cumulative_simple_return_percent_without_costs", _require_decimal(self.cumulative_simple_return_percent_without_costs, "cumulative_simple_return_percent_without_costs"))
        object.__setattr__(self, "max_loss_streak", _require_int(self.max_loss_streak, "max_loss_streak", allow_zero=True))
        object.__setattr__(self, "max_win_streak", _require_int(self.max_win_streak, "max_win_streak", allow_zero=True))
        object.__setattr__(self, "status", _require_str(self.status, "status").lower())
        if self.sample_warning is not None:
            object.__setattr__(self, "sample_warning", _require_str(self.sample_warning, "sample_warning"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_SCHEMA_VERSION:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency cell schema_version must be 1.")
        if self.window_name not in HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("window_name must be reference, validation, or test.")
        if self.window_end_utc < self.window_start_utc:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("window end must be after or equal to window start.")
        if self.decision_count != self.signal_count + self.no_signal_decisions:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError(
                "decision_count must equal signal_count plus no-signal decisions."
            )
        if self.signal_count != self.evaluated_operations + self.not_evaluable_entries:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError(
                "signal_count must equal evaluated plus not-evaluable entries."
            )
        if self.status not in HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUSES:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("unknown cell status.")
        if self.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT:
            if self.decision_count != 0:
                raise HistoricalFuturesMarketTemporalConsistencyValidationError("absent cells must have no observations.")
            if self.sample_warning is None:
                raise HistoricalFuturesMarketTemporalConsistencyValidationError("absent cells must carry a sample warning.")
        elif self.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE:
            if self.decision_count <= 0:
                raise HistoricalFuturesMarketTemporalConsistencyValidationError("insufficient-sample cells must have observations.")
            if self.sample_warning is None:
                raise HistoricalFuturesMarketTemporalConsistencyValidationError("insufficient-sample cells must carry a sample warning.")
        else:
            if self.decision_count <= 0:
                raise HistoricalFuturesMarketTemporalConsistencyValidationError("observed cells must have observations.")
            if self.sample_warning is not None:
                raise HistoricalFuturesMarketTemporalConsistencyValidationError("observed cells must not carry a sample warning.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.cell_hash:
            if self.cell_hash != expected:
                raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency cell hash mismatch.")
        else:
            object.__setattr__(self, "cell_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "window_name": self.window_name,
            "window_start_utc": _utc_iso(self.window_start_utc),
            "window_end_utc": _utc_iso(self.window_end_utc),
            "window_hash": self.window_hash,
            "source_group": self.source_group.as_dict(),
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
            "status": self.status,
            "sample_warning": self.sample_warning,
        }
        if include_hash:
            payload["cell_hash"] = self.cell_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketTemporalConsistencyCell":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency cell must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "window_name",
                "window_start_utc",
                "window_end_utc",
                "window_hash",
                "source_group",
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
                "status",
                "sample_warning",
                "cell_hash",
            },
            name="temporal consistency cell",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                window_name=mapping["window_name"],
                window_start_utc=mapping["window_start_utc"],
                window_end_utc=mapping["window_end_utc"],
                window_hash=mapping["window_hash"],
                source_group=HistoricalMultiTimeframeStrategyAnalysisGroup.from_dict(mapping["source_group"]),
                decision_count=mapping["decision_count"],
                signal_count=mapping["signal_count"],
                evaluated_operations=mapping["evaluated_operations"],
                no_signal_decisions=mapping["no_signal_decisions"],
                not_evaluable_entries=mapping["not_evaluable_entries"],
                no_signal_reason_counts=tuple(
                    HistoricalMultiTimeframeStrategyAnalysisReasonCount.from_dict(item)
                    for item in mapping.get("no_signal_reason_counts", ())
                ),
                not_evaluable_reason_counts=tuple(
                    HistoricalMultiTimeframeStrategyAnalysisReasonCount.from_dict(item)
                    for item in mapping.get("not_evaluable_reason_counts", ())
                ),
                win_rate_percent=mapping["win_rate_percent"],
                mean_gross_return_percent_without_costs=mapping["mean_gross_return_percent_without_costs"],
                median_gross_return_percent_without_costs=mapping["median_gross_return_percent_without_costs"],
                cumulative_simple_return_percent_without_costs=mapping["cumulative_simple_return_percent_without_costs"],
                max_loss_streak=mapping["max_loss_streak"],
                max_win_streak=mapping["max_win_streak"],
                status=mapping["status"],
                sample_warning=mapping.get("sample_warning"),
                cell_hash=mapping.get("cell_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency cell is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketTemporalConsistencyWindowSummary:
    window_name: str
    window_start_utc: datetime
    window_end_utc: datetime
    window_hash: str
    regime_count: int
    cell_count: int
    observed_cell_count: int
    insufficient_sample_cell_count: int
    absent_cell_count: int
    decision_count: int
    signal_count: int
    evaluated_operations: int
    no_signal_decisions: int
    not_evaluable_entries: int
    schema_version: int = HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_SCHEMA_VERSION
    summary_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_name", _require_str(self.window_name, "window_name").lower())
        object.__setattr__(self, "window_start_utc", _require_utc_datetime(self.window_start_utc, "window_start_utc"))
        object.__setattr__(self, "window_end_utc", _require_utc_datetime(self.window_end_utc, "window_end_utc"))
        object.__setattr__(self, "window_hash", _require_str(self.window_hash, "window_hash"))
        object.__setattr__(self, "regime_count", _require_int(self.regime_count, "regime_count"))
        object.__setattr__(self, "cell_count", _require_int(self.cell_count, "cell_count"))
        object.__setattr__(self, "observed_cell_count", _require_int(self.observed_cell_count, "observed_cell_count", allow_zero=True))
        object.__setattr__(self, "insufficient_sample_cell_count", _require_int(self.insufficient_sample_cell_count, "insufficient_sample_cell_count", allow_zero=True))
        object.__setattr__(self, "absent_cell_count", _require_int(self.absent_cell_count, "absent_cell_count", allow_zero=True))
        object.__setattr__(self, "decision_count", _require_int(self.decision_count, "decision_count", allow_zero=True))
        object.__setattr__(self, "signal_count", _require_int(self.signal_count, "signal_count", allow_zero=True))
        object.__setattr__(self, "evaluated_operations", _require_int(self.evaluated_operations, "evaluated_operations", allow_zero=True))
        object.__setattr__(self, "no_signal_decisions", _require_int(self.no_signal_decisions, "no_signal_decisions", allow_zero=True))
        object.__setattr__(self, "not_evaluable_entries", _require_int(self.not_evaluable_entries, "not_evaluable_entries", allow_zero=True))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_SCHEMA_VERSION:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("window summary schema_version must be 1.")
        if self.window_name not in HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("window_name must be reference, validation, or test.")
        if self.window_end_utc < self.window_start_utc:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("window end must be after or equal to window start.")
        if self.cell_count != self.regime_count:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("window summary cell_count must equal regime_count.")
        if self.cell_count != self.observed_cell_count + self.insufficient_sample_cell_count + self.absent_cell_count:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("window summary cell counts do not reconcile.")
        if self.decision_count != self.signal_count + self.no_signal_decisions:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("window summary decision_count does not reconcile.")
        if self.signal_count != self.evaluated_operations + self.not_evaluable_entries:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("window summary signal_count does not reconcile.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.summary_hash:
            if self.summary_hash != expected:
                raise HistoricalFuturesMarketTemporalConsistencyValidationError("window summary hash mismatch.")
        else:
            object.__setattr__(self, "summary_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "window_name": self.window_name,
            "window_start_utc": _utc_iso(self.window_start_utc),
            "window_end_utc": _utc_iso(self.window_end_utc),
            "window_hash": self.window_hash,
            "regime_count": self.regime_count,
            "cell_count": self.cell_count,
            "observed_cell_count": self.observed_cell_count,
            "insufficient_sample_cell_count": self.insufficient_sample_cell_count,
            "absent_cell_count": self.absent_cell_count,
            "decision_count": self.decision_count,
            "signal_count": self.signal_count,
            "evaluated_operations": self.evaluated_operations,
            "no_signal_decisions": self.no_signal_decisions,
            "not_evaluable_entries": self.not_evaluable_entries,
        }
        if include_hash:
            payload["summary_hash"] = self.summary_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketTemporalConsistencyWindowSummary":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("window summary must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "window_name",
                "window_start_utc",
                "window_end_utc",
                "window_hash",
                "regime_count",
                "cell_count",
                "observed_cell_count",
                "insufficient_sample_cell_count",
                "absent_cell_count",
                "decision_count",
                "signal_count",
                "evaluated_operations",
                "no_signal_decisions",
                "not_evaluable_entries",
                "summary_hash",
            },
            name="window summary",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                window_name=mapping["window_name"],
                window_start_utc=mapping["window_start_utc"],
                window_end_utc=mapping["window_end_utc"],
                window_hash=mapping["window_hash"],
                regime_count=mapping["regime_count"],
                cell_count=mapping["cell_count"],
                observed_cell_count=mapping["observed_cell_count"],
                insufficient_sample_cell_count=mapping["insufficient_sample_cell_count"],
                absent_cell_count=mapping["absent_cell_count"],
                decision_count=mapping["decision_count"],
                signal_count=mapping["signal_count"],
                evaluated_operations=mapping["evaluated_operations"],
                no_signal_decisions=mapping["no_signal_decisions"],
                not_evaluable_entries=mapping["not_evaluable_entries"],
                summary_hash=mapping.get("summary_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("window summary is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketTemporalConsistencySummary:
    window_count: int
    regime_count: int
    cell_count: int
    observed_cell_count: int
    insufficient_sample_cell_count: int
    absent_cell_count: int
    fully_observed_regime_count: int
    partially_observed_regime_count: int
    absent_regime_count: int
    comparable_regime_count: int
    decision_count: int
    signal_count: int
    evaluated_operations: int
    no_signal_decisions: int
    not_evaluable_entries: int
    max_regime_mean_return_spread_percent: Decimal
    median_regime_mean_return_spread_percent: Decimal
    max_regime_win_rate_spread_percent: Decimal
    median_regime_win_rate_spread_percent: Decimal
    schema_version: int = HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_SCHEMA_VERSION
    summary_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_count", _require_int(self.window_count, "window_count"))
        object.__setattr__(self, "regime_count", _require_int(self.regime_count, "regime_count"))
        object.__setattr__(self, "cell_count", _require_int(self.cell_count, "cell_count"))
        object.__setattr__(self, "observed_cell_count", _require_int(self.observed_cell_count, "observed_cell_count", allow_zero=True))
        object.__setattr__(self, "insufficient_sample_cell_count", _require_int(self.insufficient_sample_cell_count, "insufficient_sample_cell_count", allow_zero=True))
        object.__setattr__(self, "absent_cell_count", _require_int(self.absent_cell_count, "absent_cell_count", allow_zero=True))
        object.__setattr__(self, "fully_observed_regime_count", _require_int(self.fully_observed_regime_count, "fully_observed_regime_count", allow_zero=True))
        object.__setattr__(self, "partially_observed_regime_count", _require_int(self.partially_observed_regime_count, "partially_observed_regime_count", allow_zero=True))
        object.__setattr__(self, "absent_regime_count", _require_int(self.absent_regime_count, "absent_regime_count", allow_zero=True))
        object.__setattr__(self, "comparable_regime_count", _require_int(self.comparable_regime_count, "comparable_regime_count", allow_zero=True))
        object.__setattr__(self, "decision_count", _require_int(self.decision_count, "decision_count", allow_zero=True))
        object.__setattr__(self, "signal_count", _require_int(self.signal_count, "signal_count", allow_zero=True))
        object.__setattr__(self, "evaluated_operations", _require_int(self.evaluated_operations, "evaluated_operations", allow_zero=True))
        object.__setattr__(self, "no_signal_decisions", _require_int(self.no_signal_decisions, "no_signal_decisions", allow_zero=True))
        object.__setattr__(self, "not_evaluable_entries", _require_int(self.not_evaluable_entries, "not_evaluable_entries", allow_zero=True))
        object.__setattr__(self, "max_regime_mean_return_spread_percent", _require_decimal(self.max_regime_mean_return_spread_percent, "max_regime_mean_return_spread_percent"))
        object.__setattr__(self, "median_regime_mean_return_spread_percent", _require_decimal(self.median_regime_mean_return_spread_percent, "median_regime_mean_return_spread_percent"))
        object.__setattr__(self, "max_regime_win_rate_spread_percent", _require_decimal(self.max_regime_win_rate_spread_percent, "max_regime_win_rate_spread_percent"))
        object.__setattr__(self, "median_regime_win_rate_spread_percent", _require_decimal(self.median_regime_win_rate_spread_percent, "median_regime_win_rate_spread_percent"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_SCHEMA_VERSION:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency summary schema_version must be 1.")
        if self.cell_count != self.observed_cell_count + self.insufficient_sample_cell_count + self.absent_cell_count:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("summary cell counts do not reconcile.")
        if self.regime_count != self.fully_observed_regime_count + self.partially_observed_regime_count + self.absent_regime_count:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("summary regime counts do not reconcile.")
        if self.decision_count != self.signal_count + self.no_signal_decisions:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("summary decision_count does not reconcile.")
        if self.signal_count != self.evaluated_operations + self.not_evaluable_entries:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("summary signal_count does not reconcile.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.summary_hash:
            if self.summary_hash != expected:
                raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency summary hash mismatch.")
        else:
            object.__setattr__(self, "summary_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "window_count": self.window_count,
            "regime_count": self.regime_count,
            "cell_count": self.cell_count,
            "observed_cell_count": self.observed_cell_count,
            "insufficient_sample_cell_count": self.insufficient_sample_cell_count,
            "absent_cell_count": self.absent_cell_count,
            "fully_observed_regime_count": self.fully_observed_regime_count,
            "partially_observed_regime_count": self.partially_observed_regime_count,
            "absent_regime_count": self.absent_regime_count,
            "comparable_regime_count": self.comparable_regime_count,
            "decision_count": self.decision_count,
            "signal_count": self.signal_count,
            "evaluated_operations": self.evaluated_operations,
            "no_signal_decisions": self.no_signal_decisions,
            "not_evaluable_entries": self.not_evaluable_entries,
            "max_regime_mean_return_spread_percent": self.max_regime_mean_return_spread_percent,
            "median_regime_mean_return_spread_percent": self.median_regime_mean_return_spread_percent,
            "max_regime_win_rate_spread_percent": self.max_regime_win_rate_spread_percent,
            "median_regime_win_rate_spread_percent": self.median_regime_win_rate_spread_percent,
        }
        if include_hash:
            payload["summary_hash"] = self.summary_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketTemporalConsistencySummary":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency summary must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "window_count",
                "regime_count",
                "cell_count",
                "observed_cell_count",
                "insufficient_sample_cell_count",
                "absent_cell_count",
                "fully_observed_regime_count",
                "partially_observed_regime_count",
                "absent_regime_count",
                "comparable_regime_count",
                "decision_count",
                "signal_count",
                "evaluated_operations",
                "no_signal_decisions",
                "not_evaluable_entries",
                "max_regime_mean_return_spread_percent",
                "median_regime_mean_return_spread_percent",
                "max_regime_win_rate_spread_percent",
                "median_regime_win_rate_spread_percent",
                "summary_hash",
            },
            name="temporal consistency summary",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                window_count=mapping["window_count"],
                regime_count=mapping["regime_count"],
                cell_count=mapping["cell_count"],
                observed_cell_count=mapping["observed_cell_count"],
                insufficient_sample_cell_count=mapping["insufficient_sample_cell_count"],
                absent_cell_count=mapping["absent_cell_count"],
                fully_observed_regime_count=mapping["fully_observed_regime_count"],
                partially_observed_regime_count=mapping["partially_observed_regime_count"],
                absent_regime_count=mapping["absent_regime_count"],
                comparable_regime_count=mapping["comparable_regime_count"],
                decision_count=mapping["decision_count"],
                signal_count=mapping["signal_count"],
                evaluated_operations=mapping["evaluated_operations"],
                no_signal_decisions=mapping["no_signal_decisions"],
                not_evaluable_entries=mapping["not_evaluable_entries"],
                max_regime_mean_return_spread_percent=mapping["max_regime_mean_return_spread_percent"],
                median_regime_mean_return_spread_percent=mapping["median_regime_mean_return_spread_percent"],
                max_regime_win_rate_spread_percent=mapping["max_regime_win_rate_spread_percent"],
                median_regime_win_rate_spread_percent=mapping["median_regime_win_rate_spread_percent"],
                summary_hash=mapping.get("summary_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency summary is incomplete.") from exc


def _contract_windows(contract: HistoricalFuturesMarketContract) -> tuple[Any, Any, Any]:
    temporal_split = contract.temporal_split_protocol
    return temporal_split.reference_window, temporal_split.validation_window, temporal_split.test_window


def _build_protocol(
    validation_report: HistoricalFuturesMarketValidationReport,
) -> HistoricalFuturesMarketTemporalConsistencyProtocol:
    contract = validation_report.contract
    analysis_report = validation_report.analysis_report
    temporal_split = contract.temporal_split_protocol
    source_group_hashes = tuple(group.group_hash for group in analysis_report.groups)
    return HistoricalFuturesMarketTemporalConsistencyProtocol(
        schema_version=HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_SCHEMA_VERSION,
        validation_report_hash=validation_report.report_hash,
        contract_hash=contract.contract_hash,
        contract_temporal_split_hash=temporal_split.protocol_hash,
        analysis_report_hash=analysis_report.report_hash,
        analysis_protocol_hash=analysis_report.protocol.protocol_hash,
        evaluation_hash=analysis_report.protocol.source.evaluation_hash,
        strategy_report_hash=analysis_report.protocol.source.strategy_report_hash,
        replay_hash=analysis_report.protocol.source.replay_hash,
        bundle_hash=analysis_report.protocol.source.bundle_hash,
        source_hash=analysis_report.protocol.source.source_hash,
        reference_window_hash=temporal_split.reference_window.window_hash,
        validation_window_hash=temporal_split.validation_window.window_hash,
        test_window_hash=temporal_split.test_window.window_hash,
        source_group_hashes=source_group_hashes,
        window_count=len(HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES),
        regime_count=len(source_group_hashes),
    )


def _build_cells(
    validation_report: HistoricalFuturesMarketValidationReport,
) -> tuple[HistoricalFuturesMarketTemporalConsistencyCell, ...]:
    analysis_report = validation_report.analysis_report
    contract = validation_report.contract
    temporal_split = contract.temporal_split_protocol
    windows = _contract_windows(contract)
    minimum_group_sample_size = analysis_report.protocol.minimum_group_sample_size
    cells: list[HistoricalFuturesMarketTemporalConsistencyCell] = []
    for window in windows:
        for source_group in analysis_report.groups:
            observations = _observations_for_group_and_window(
                analysis_report.observations,
                window=window,
                group=source_group,
            )
            (
                decision_count,
                signal_count,
                evaluated_operations,
                no_signal_decisions,
                not_evaluable_entries,
                no_signal_reason_counts,
                not_evaluable_reason_counts,
                win_rate_percent,
                mean_return,
                median_return,
                cumulative_return,
                max_loss_streak,
                max_win_streak,
            ) = _build_metrics(observations)
            status = _cell_status(
                decision_count,
                evaluated_operations,
                minimum_group_sample_size,
            )
            sample_warning = _cell_warning(
                status,
                decision_count=decision_count,
                evaluated_operations=evaluated_operations,
                minimum_group_sample_size=minimum_group_sample_size,
            )
            cells.append(
                HistoricalFuturesMarketTemporalConsistencyCell(
                    window_name=window.window_name,
                    window_start_utc=window.start_utc,
                    window_end_utc=window.end_utc,
                    window_hash=window.window_hash,
                    source_group=source_group,
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
                    max_loss_streak=max_loss_streak,
                    max_win_streak=max_win_streak,
                    status=status,
                    sample_warning=sample_warning,
                )
            )
    return tuple(cells)


def _build_window_summaries(
    validation_report: HistoricalFuturesMarketValidationReport,
    cells: Sequence[HistoricalFuturesMarketTemporalConsistencyCell],
) -> tuple[HistoricalFuturesMarketTemporalConsistencyWindowSummary, ...]:
    windows = _contract_windows(validation_report.contract)
    summaries: list[HistoricalFuturesMarketTemporalConsistencyWindowSummary] = []
    cell_by_window: dict[str, list[HistoricalFuturesMarketTemporalConsistencyCell]] = {
        window.window_name: [] for window in windows
    }
    for cell in cells:
        cell_by_window[cell.window_name].append(cell)
    for window in windows:
        window_cells = tuple(cell_by_window[window.window_name])
        summaries.append(
            HistoricalFuturesMarketTemporalConsistencyWindowSummary(
                window_name=window.window_name,
                window_start_utc=window.start_utc,
                window_end_utc=window.end_utc,
                window_hash=window.window_hash,
                regime_count=len(validation_report.analysis_report.groups),
                cell_count=len(window_cells),
                observed_cell_count=sum(1 for cell in window_cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED),
                insufficient_sample_cell_count=sum(
                    1 for cell in window_cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE
                ),
                absent_cell_count=sum(1 for cell in window_cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT),
                decision_count=sum(cell.decision_count for cell in window_cells),
                signal_count=sum(cell.signal_count for cell in window_cells),
                evaluated_operations=sum(cell.evaluated_operations for cell in window_cells),
                no_signal_decisions=sum(cell.no_signal_decisions for cell in window_cells),
                not_evaluable_entries=sum(cell.not_evaluable_entries for cell in window_cells),
            )
        )
    return tuple(summaries)


def _build_summary(
    validation_report: HistoricalFuturesMarketValidationReport,
    cells: Sequence[HistoricalFuturesMarketTemporalConsistencyCell],
    window_summaries: Sequence[HistoricalFuturesMarketTemporalConsistencyWindowSummary],
) -> HistoricalFuturesMarketTemporalConsistencySummary:
    analysis_report = validation_report.analysis_report
    regime_to_cells: dict[str, list[HistoricalFuturesMarketTemporalConsistencyCell]] = {
        group.group_hash: [] for group in analysis_report.groups
    }
    for cell in cells:
        regime_to_cells[cell.source_group.group_hash].append(cell)
    comparable_mean_spreads: list[Decimal] = []
    comparable_win_rate_spreads: list[Decimal] = []
    fully_observed_regime_count = 0
    partially_observed_regime_count = 0
    absent_regime_count = 0
    for source_group in analysis_report.groups:
        group_cells = regime_to_cells[source_group.group_hash]
        observed_cells = [cell for cell in group_cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED]
        if len(observed_cells) == len(HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES):
            fully_observed_regime_count += 1
        elif observed_cells:
            partially_observed_regime_count += 1
        else:
            absent_regime_count += 1
        if len(observed_cells) >= 2:
            mean_values = [cell.mean_gross_return_percent_without_costs for cell in observed_cells]
            win_rate_values = [cell.win_rate_percent for cell in observed_cells]
            comparable_mean_spreads.append(max(mean_values) - min(mean_values))
            comparable_win_rate_spreads.append(max(win_rate_values) - min(win_rate_values))
    if comparable_mean_spreads:
        max_mean_spread = max(comparable_mean_spreads)
        median_mean_spread = median(comparable_mean_spreads)
        max_win_spread = max(comparable_win_rate_spreads)
        median_win_spread = median(comparable_win_rate_spreads)
    else:
        max_mean_spread = Decimal("0")
        median_mean_spread = Decimal("0")
        max_win_spread = Decimal("0")
        median_win_spread = Decimal("0")
    decision_count = sum(cell.decision_count for cell in cells)
    signal_count = sum(cell.signal_count for cell in cells)
    evaluated_operations = sum(cell.evaluated_operations for cell in cells)
    no_signal_decisions = sum(cell.no_signal_decisions for cell in cells)
    not_evaluable_entries = sum(cell.not_evaluable_entries for cell in cells)
    return HistoricalFuturesMarketTemporalConsistencySummary(
        window_count=len(window_summaries),
        regime_count=len(analysis_report.groups),
        cell_count=len(cells),
        observed_cell_count=sum(1 for cell in cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED),
        insufficient_sample_cell_count=sum(
            1 for cell in cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE
        ),
        absent_cell_count=sum(1 for cell in cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT),
        fully_observed_regime_count=fully_observed_regime_count,
        partially_observed_regime_count=partially_observed_regime_count,
        absent_regime_count=absent_regime_count,
        comparable_regime_count=len(comparable_mean_spreads),
        decision_count=decision_count,
        signal_count=signal_count,
        evaluated_operations=evaluated_operations,
        no_signal_decisions=no_signal_decisions,
        not_evaluable_entries=not_evaluable_entries,
        max_regime_mean_return_spread_percent=max_mean_spread,
        median_regime_mean_return_spread_percent=median_mean_spread,
        max_regime_win_rate_spread_percent=max_win_spread,
        median_regime_win_rate_spread_percent=median_win_spread,
    )


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketTemporalConsistencyReport:
    validation_report: HistoricalFuturesMarketValidationReport
    protocol: HistoricalFuturesMarketTemporalConsistencyProtocol
    cells: tuple[HistoricalFuturesMarketTemporalConsistencyCell, ...]
    window_summaries: tuple[HistoricalFuturesMarketTemporalConsistencyWindowSummary, ...]
    summary: HistoricalFuturesMarketTemporalConsistencySummary
    schema_version: int = HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    report_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.validation_report, HistoricalFuturesMarketValidationReport):
            raise HistoricalFuturesMarketTemporalConsistencyValidationError(
                "validation_report must be a HistoricalFuturesMarketValidationReport instance."
            )
        if not isinstance(self.protocol, HistoricalFuturesMarketTemporalConsistencyProtocol):
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("protocol must be a temporal consistency protocol instance.")
        if not isinstance(self.cells, tuple):
            object.__setattr__(self, "cells", tuple(self.cells))
        if not isinstance(self.window_summaries, tuple):
            object.__setattr__(self, "window_summaries", tuple(self.window_summaries))
        if not isinstance(self.summary, HistoricalFuturesMarketTemporalConsistencySummary):
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("summary must be a temporal consistency summary instance.")
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_SCHEMA_VERSION:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency report schema_version must be 1.")
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        if (
            self.validation_report.historical_research_only is not True
            or self.validation_report.operational_evidence is not False
            or self.validation_report.paper_promotion_eligible is not False
        ):
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("validation report must remain research-only.")
        if self.protocol != _build_protocol(self.validation_report):
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency protocol diverges from the trusted validation chain.")
        expected_cells = _build_cells(self.validation_report)
        if self.cells != expected_cells:
            raise HistoricalFuturesMarketTemporalConsistencyIntegrityError("temporal consistency cells diverge from the frozen evidence.")
        expected_window_summaries = _build_window_summaries(self.validation_report, self.cells)
        if self.window_summaries != expected_window_summaries:
            raise HistoricalFuturesMarketTemporalConsistencyIntegrityError("temporal consistency window summaries diverge from the frozen evidence.")
        expected_summary = _build_summary(self.validation_report, self.cells, self.window_summaries)
        if self.summary != expected_summary:
            raise HistoricalFuturesMarketTemporalConsistencyIntegrityError("temporal consistency summary diverges from the frozen evidence.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.report_hash:
            if self.report_hash != expected:
                raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency report hash mismatch.")
        else:
            object.__setattr__(self, "report_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "protocol": self.protocol.as_hash_payload(include_hash=False),
            "cells": [cell.as_dict() for cell in self.cells],
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
            "validation_report": self.validation_report.as_dict(),
            "protocol": self.protocol.as_dict(),
            "cells": [cell.as_dict() for cell in self.cells],
            "window_summaries": [item.as_dict() for item in self.window_summaries],
            "summary": self.summary.as_dict(),
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "report_hash": self.report_hash,
        }
        return serialize_value(payload)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketTemporalConsistencyReport":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency report must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "validation_report",
                "protocol",
                "cells",
                "window_summaries",
                "summary",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "report_hash",
            },
            name="temporal consistency report",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                validation_report=HistoricalFuturesMarketValidationReport.from_dict(mapping["validation_report"]),
                protocol=HistoricalFuturesMarketTemporalConsistencyProtocol.from_dict(mapping["protocol"]),
                cells=tuple(HistoricalFuturesMarketTemporalConsistencyCell.from_dict(item) for item in mapping["cells"]),
                window_summaries=tuple(
                    HistoricalFuturesMarketTemporalConsistencyWindowSummary.from_dict(item)
                    for item in mapping["window_summaries"]
                ),
                summary=HistoricalFuturesMarketTemporalConsistencySummary.from_dict(mapping["summary"]),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                report_hash=mapping.get("report_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency report is incomplete.") from exc
        except (
            HistoricalFuturesMarketValidationValidationError,
            HistoricalFuturesMarketTemporalConsistencyValidationError,
            HistoricalFuturesMarketContractValidationError,
            HistoricalMultiTimeframeStrategyAnalysisValidationError,
            HistoricalDataValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise HistoricalFuturesMarketTemporalConsistencyIntegrityError(str(exc)) from exc


def build_historical_futures_market_temporal_consistency_protocol(
    validation_report: HistoricalFuturesMarketValidationReport,
) -> HistoricalFuturesMarketTemporalConsistencyProtocol:
    if not isinstance(validation_report, HistoricalFuturesMarketValidationReport):
        raise HistoricalFuturesMarketTemporalConsistencyValidationError(
            "validation_report must be a HistoricalFuturesMarketValidationReport instance."
        )
    return _build_protocol(validation_report)


def build_historical_futures_market_temporal_consistency_report(
    validation_report: HistoricalFuturesMarketValidationReport,
) -> HistoricalFuturesMarketTemporalConsistencyReport:
    if not isinstance(validation_report, HistoricalFuturesMarketValidationReport):
        raise HistoricalFuturesMarketTemporalConsistencyValidationError(
            "validation_report must be a HistoricalFuturesMarketValidationReport instance."
        )
    protocol = _build_protocol(validation_report)
    cells = _build_cells(validation_report)
    window_summaries = _build_window_summaries(validation_report, cells)
    summary = _build_summary(validation_report, cells, window_summaries)
    return HistoricalFuturesMarketTemporalConsistencyReport(
        validation_report=validation_report,
        protocol=protocol,
        cells=cells,
        window_summaries=window_summaries,
        summary=summary,
    )


def run_historical_futures_market_temporal_consistency(
    validation_report: HistoricalFuturesMarketValidationReport,
    *,
    output_file: str | Path | None = None,
) -> HistoricalFuturesMarketTemporalConsistencyReport:
    report = build_historical_futures_market_temporal_consistency_report(validation_report)
    if output_file is not None:
        save_historical_futures_market_temporal_consistency_report(output_file, report)
    return report


def _read(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HistoricalFuturesMarketTemporalConsistencyValidationError("temporal consistency report not found.") from exc
    except Exception as exc:
        raise HistoricalFuturesMarketTemporalConsistencyIntegrityError("temporal consistency report is invalid JSON.") from exc
    if not isinstance(value, Mapping):
        raise HistoricalFuturesMarketTemporalConsistencyIntegrityError("temporal consistency report must be a JSON object.")
    return value


def load_historical_futures_market_temporal_consistency_report(
    path: str | Path,
) -> HistoricalFuturesMarketTemporalConsistencyReport:
    payload = _read(Path(path))
    try:
        report = HistoricalFuturesMarketTemporalConsistencyReport.from_dict(payload)
    except (
        KeyError,
        TypeError,
        ValueError,
        HistoricalFuturesMarketTemporalConsistencyValidationError,
        HistoricalFuturesMarketTemporalConsistencyIntegrityError,
        HistoricalFuturesMarketValidationValidationError,
        HistoricalFuturesMarketValidationError,
        HistoricalFuturesMarketContractValidationError,
        HistoricalMultiTimeframeStrategyAnalysisValidationError,
        HistoricalDataValidationError,
    ) as exc:
        raise HistoricalFuturesMarketTemporalConsistencyIntegrityError(str(exc)) from exc
    if report.as_dict() != payload:
        raise HistoricalFuturesMarketTemporalConsistencyIntegrityError("temporal consistency report payload mismatch.")
    return report


def save_historical_futures_market_temporal_consistency_report(
    path: str | Path,
    report: HistoricalFuturesMarketTemporalConsistencyReport,
) -> HistoricalFuturesMarketTemporalConsistencyReport:
    file_path = Path(path)
    payload = report.as_dict()
    if file_path.exists():
        existing = load_historical_futures_market_temporal_consistency_report(file_path)
        if existing.as_dict() != payload:
            raise HistoricalFuturesMarketTemporalConsistencyConflictError("temporal consistency report already exists and differs.")
        return existing
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_name(f".{file_path.name}.{os.getpid()}.{id(report)}.tmp")
    try:
        tmp.write_text(_canonical_json(payload), encoding="utf-8")
        try:
            os.link(tmp, file_path)
        except FileExistsError:
            existing = load_historical_futures_market_temporal_consistency_report(file_path)
            if existing.as_dict() != payload:
                raise HistoricalFuturesMarketTemporalConsistencyConflictError(
                    "temporal consistency report already exists and differs."
                )
            return existing
    except Exception as exc:
        if isinstance(exc, HistoricalFuturesMarketTemporalConsistencyConflictError):
            raise
        raise HistoricalFuturesMarketTemporalConsistencyValidationError("failed to write temporal consistency report atomically.") from exc
    finally:
        tmp.unlink(missing_ok=True)
    return report


def verify_historical_futures_market_temporal_consistency_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_temporal_consistency_report(path)
    return {
        "verified": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "validation_report_hash": report.validation_report.report_hash,
        "contract_hash": report.validation_report.contract.contract_hash,
        "analysis_report_hash": report.validation_report.analysis_report.report_hash,
        "classification": "historical_research_only",
    }


def status_historical_futures_market_temporal_consistency_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_temporal_consistency_report(path)
    summary = report.summary
    window_map = {item.window_name: item for item in report.window_summaries}
    return {
        "exists": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "validation_report_hash": report.validation_report.report_hash,
        "contract_hash": report.validation_report.contract.contract_hash,
        "analysis_report_hash": report.validation_report.analysis_report.report_hash,
        "reference_window_hash": report.protocol.reference_window_hash,
        "validation_window_hash": report.protocol.validation_window_hash,
        "test_window_hash": report.protocol.test_window_hash,
        "reference_window_cell_count": window_map[HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE].cell_count,
        "validation_window_cell_count": window_map[HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION].cell_count,
        "test_window_cell_count": window_map[HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST].cell_count,
        "cell_count": summary.cell_count,
        "observed_cell_count": summary.observed_cell_count,
        "insufficient_sample_cell_count": summary.insufficient_sample_cell_count,
        "absent_cell_count": summary.absent_cell_count,
        "fully_observed_regime_count": summary.fully_observed_regime_count,
        "partially_observed_regime_count": summary.partially_observed_regime_count,
        "comparable_regime_count": summary.comparable_regime_count,
        "max_regime_mean_return_spread_percent": summary.max_regime_mean_return_spread_percent,
        "max_regime_win_rate_spread_percent": summary.max_regime_win_rate_spread_percent,
        "classification": "historical_research_only",
    }


def reject_historical_futures_market_temporal_consistency_promotion(
    _: HistoricalFuturesMarketTemporalConsistencyReport,
) -> None:
    raise HistoricalFuturesMarketTemporalConsistencyPromotionError(
        "historical futures temporal consistency is not promotion evidence."
    )


__all__ = [
    "HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT",
    "HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE",
    "HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED",
    "HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUSES",
    "HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_PROTOCOL_NAME",
    "HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_PROTOCOL_VERSION",
    "HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_SCHEMA_VERSION",
    "HistoricalFuturesMarketTemporalConsistencyCell",
    "HistoricalFuturesMarketTemporalConsistencyConflictError",
    "HistoricalFuturesMarketTemporalConsistencyError",
    "HistoricalFuturesMarketTemporalConsistencyIntegrityError",
    "HistoricalFuturesMarketTemporalConsistencyPromotionError",
    "HistoricalFuturesMarketTemporalConsistencyProtocol",
    "HistoricalFuturesMarketTemporalConsistencyReport",
    "HistoricalFuturesMarketTemporalConsistencySummary",
    "HistoricalFuturesMarketTemporalConsistencyValidationError",
    "HistoricalFuturesMarketTemporalConsistencyWindowSummary",
    "build_historical_futures_market_temporal_consistency_protocol",
    "build_historical_futures_market_temporal_consistency_report",
    "load_historical_futures_market_temporal_consistency_report",
    "reject_historical_futures_market_temporal_consistency_promotion",
    "run_historical_futures_market_temporal_consistency",
    "save_historical_futures_market_temporal_consistency_report",
    "status_historical_futures_market_temporal_consistency_report",
    "verify_historical_futures_market_temporal_consistency_report",
]
