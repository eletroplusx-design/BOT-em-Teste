"""Research-only evaluation for the Phase 13B multi-timeframe hypothesis.

This module turns a frozen, validated Phase 13B strategy report into a
deterministic historical evaluation report. It does not expose any paper/live
path and it never changes the underlying hypothesis or replay contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import json
import os
from statistics import median
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value
from historical_multitimeframe_strategy import (
    HistoricalMultiTimeframeFirstStrategyDecision,
    HistoricalMultiTimeframeFirstStrategyIntegrityError,
    HistoricalMultiTimeframeFirstStrategyReport,
    HistoricalMultiTimeframeFirstStrategyValidationError,
)
from historical_multitimeframe_experiments import HistoricalMultiTimeframeExperimentIntegrityError
from market_data import HistoricalDataValidationError


HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_SCHEMA_VERSION = 1
HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_NAME = "historical_multitimeframe_first_strategy_evaluation"
HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_VERSION = "v1"
HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_ENTRY_DELAY_CANDLES = 1
HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_NO_SIGNAL = "no_signal"
HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_NOT_EVALUABLE = "not_evaluable"
HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_EVALUATED = "evaluated"


class HistoricalMultiTimeframeFirstStrategyEvaluationError(Exception):
    pass


class HistoricalMultiTimeframeFirstStrategyEvaluationValidationError(HistoricalMultiTimeframeFirstStrategyEvaluationError):
    pass


class HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError(HistoricalMultiTimeframeFirstStrategyEvaluationValidationError):
    pass


class HistoricalMultiTimeframeFirstStrategyEvaluationConflictError(HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError):
    pass


class HistoricalMultiTimeframeFirstStrategyEvaluationPromotionError(HistoricalMultiTimeframeFirstStrategyEvaluationValidationError):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _utc(value: Any, name: str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError(f"{name} must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _required_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError(f"{name} is required.")
    return value.strip()


def _required_int(value: Any, name: str) -> int:
    if type(value) is not int:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError(f"{name} must be an integer.")
    return value


def _required_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError(f"{name} must be a boolean.")
    return value


def _validate_exact_keys(mapping: Mapping[str, Any], *, allowed: set[str], name: str) -> None:
    extra = set(mapping) - allowed
    if extra:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError(f"{name} contains unknown fields: {sorted(extra)!r}.")


def _research_only(classification: str, operational_evidence: bool, paper_promotion_eligible: bool) -> None:
    if classification != "historical_research_only":
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("classification must be historical_research_only.")
    if operational_evidence is not False:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("operational_evidence must be false.")
    if paper_promotion_eligible is not False:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("paper_promotion_eligible must be false.")


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


def _build_decision_index(strategy_report: HistoricalMultiTimeframeFirstStrategyReport) -> dict[datetime, int]:
    base_candles = strategy_report.replay.bundle.base_dataset.candles
    return {candle.close_time.astimezone(timezone.utc): index for index, candle in enumerate(base_candles)}


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeFirstStrategyEvaluationProtocol:
    schema_version: int = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_SCHEMA_VERSION
    evaluation_name: str = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_NAME
    evaluation_version: str = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_VERSION
    strategy_hypothesis_version: str = ""
    strategy_config_hash: str = ""
    strategy_factory_hash: str = ""
    strategy_report_hash: str = ""
    entry_delay_15m_candles: int = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_ENTRY_DELAY_CANDLES
    exit_horizon_15m_candles: int = 4
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    protocol_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluation_name", _required_str(self.evaluation_name, "evaluation_name"))
        object.__setattr__(self, "evaluation_version", _required_str(self.evaluation_version, "evaluation_version"))
        object.__setattr__(self, "strategy_hypothesis_version", _required_str(self.strategy_hypothesis_version, "strategy_hypothesis_version"))
        object.__setattr__(self, "strategy_config_hash", _required_str(self.strategy_config_hash, "strategy_config_hash"))
        object.__setattr__(self, "strategy_factory_hash", _required_str(self.strategy_factory_hash, "strategy_factory_hash"))
        object.__setattr__(self, "strategy_report_hash", _required_str(self.strategy_report_hash, "strategy_report_hash"))
        object.__setattr__(self, "entry_delay_15m_candles", _required_int(self.entry_delay_15m_candles, "entry_delay_15m_candles"))
        object.__setattr__(self, "exit_horizon_15m_candles", _required_int(self.exit_horizon_15m_candles, "exit_horizon_15m_candles"))
        object.__setattr__(self, "historical_research_only", _required_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _required_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _required_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_SCHEMA_VERSION:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation schema_version must be 1.")
        if self.evaluation_name != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_NAME:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation_name diverges from the trusted protocol.")
        if self.evaluation_version != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_VERSION:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation_version diverges from the trusted protocol.")
        if self.entry_delay_15m_candles != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_ENTRY_DELAY_CANDLES:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("entry delay must remain a single 15m candle.")
        if self.exit_horizon_15m_candles <= 0:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("exit horizon must be greater than zero.")
        if self.historical_research_only is not True:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("paper_promotion_eligible must be false.")
        expected = _hash(self.as_hash_payload(include_hash=False))
        if self.protocol_hash:
            if self.protocol_hash != expected:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("protocol hash mismatch.")
        else:
            object.__setattr__(self, "protocol_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "evaluation_name": self.evaluation_name,
            "evaluation_version": self.evaluation_version,
            "strategy_hypothesis_version": self.strategy_hypothesis_version,
            "strategy_config_hash": self.strategy_config_hash,
            "strategy_factory_hash": self.strategy_factory_hash,
            "strategy_report_hash": self.strategy_report_hash,
            "entry_delay_15m_candles": self.entry_delay_15m_candles,
            "exit_horizon_15m_candles": self.exit_horizon_15m_candles,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeFirstStrategyEvaluationProtocol":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation protocol must be a mapping.")
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
                "entry_delay_15m_candles",
                "exit_horizon_15m_candles",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "protocol_hash",
            },
            name="evaluation protocol",
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
                entry_delay_15m_candles=mapping["entry_delay_15m_candles"],
                exit_horizon_15m_candles=mapping["exit_horizon_15m_candles"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                protocol_hash=mapping.get("protocol_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation protocol is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeFirstStrategyEvaluationResult:
    decision_hash: str
    decision_time_utc: datetime
    signal_generated: bool
    status: str
    reasons: tuple[str, ...]
    signal_hash: str | None = None
    entry_open_time_utc: datetime | None = None
    entry_open: Decimal | None = None
    exit_open_time_utc: datetime | None = None
    exit_open: Decimal | None = None
    holding_period_15m_candles: int | None = None
    gross_return_percent_without_costs: Decimal | None = None
    result_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_hash", _required_str(self.decision_hash, "decision_hash"))
        object.__setattr__(self, "decision_time_utc", _utc(self.decision_time_utc, "decision_time_utc"))
        object.__setattr__(self, "signal_generated", _required_bool(self.signal_generated, "signal_generated"))
        object.__setattr__(self, "status", _required_str(self.status, "status"))
        object.__setattr__(self, "entry_open_time_utc", _utc(self.entry_open_time_utc, "entry_open_time_utc") if self.entry_open_time_utc is not None else None)
        object.__setattr__(self, "exit_open_time_utc", _utc(self.exit_open_time_utc, "exit_open_time_utc") if self.exit_open_time_utc is not None else None)
        object.__setattr__(self, "entry_open", Decimal(str(self.entry_open)) if self.entry_open is not None else None)
        object.__setattr__(self, "exit_open", Decimal(str(self.exit_open)) if self.exit_open is not None else None)
        object.__setattr__(self, "gross_return_percent_without_costs", Decimal(str(self.gross_return_percent_without_costs)) if self.gross_return_percent_without_costs is not None else None)
        if not isinstance(self.reasons, tuple):
            object.__setattr__(self, "reasons", tuple(self.reasons))
        if not self.reasons:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation reasons are required.")
        if any(not isinstance(reason, str) or not reason.strip() for reason in self.reasons):
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation reasons must be non-empty strings.")
        if self.status not in {
            HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_NO_SIGNAL,
            HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_NOT_EVALUABLE,
            HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_EVALUATED,
        }:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("unknown evaluation status.")
        if self.status == HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_NO_SIGNAL:
            if self.signal_generated is not False:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("no-signal results must not claim a generated signal.")
            if self.signal_hash is not None:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("no-signal results must not carry a signal hash.")
            if any(
                value is not None
                for value in (
                    self.entry_open_time_utc,
                    self.entry_open,
                    self.exit_open_time_utc,
                    self.exit_open,
                    self.holding_period_15m_candles,
                    self.gross_return_percent_without_costs,
                )
            ):
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("no-signal results must not carry entry or exit details.")
        elif self.status == HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_NOT_EVALUABLE:
            if self.signal_generated is not True:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("not-evaluable results must come from a generated signal.")
            object.__setattr__(self, "signal_hash", _required_str(self.signal_hash, "signal_hash"))
            if self.exit_open_time_utc is not None or self.exit_open is not None or self.holding_period_15m_candles is not None or self.gross_return_percent_without_costs is not None:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("not-evaluable results must not include exit details.")
            if self.entry_open_time_utc is None and self.entry_open is not None:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("entry_open_time_utc is required when entry_open is provided.")
            if self.entry_open_time_utc is not None and self.entry_open is None:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("entry_open is required when entry_open_time_utc is provided.")
        else:
            object.__setattr__(self, "signal_hash", _required_str(self.signal_hash, "signal_hash"))
            if self.signal_generated is not True:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluated results must come from a generated signal.")
            if self.entry_open_time_utc is None or self.entry_open is None:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluated results require entry details.")
            if self.exit_open_time_utc is None or self.exit_open is None:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluated results require exit details.")
            if self.holding_period_15m_candles is None or self.holding_period_15m_candles <= 0:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluated results require a positive holding period.")
            if self.gross_return_percent_without_costs is None:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluated results require a gross return.")
        expected = _hash(self.as_hash_payload(include_hash=False))
        if self.result_hash:
            if self.result_hash != expected:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation result hash mismatch.")
        else:
            object.__setattr__(self, "result_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "decision_hash": self.decision_hash,
            "decision_time_utc": _iso(self.decision_time_utc),
            "signal_generated": self.signal_generated,
            "status": self.status,
            "reasons": list(self.reasons),
            "signal_hash": self.signal_hash,
            "entry_open_time_utc": _iso(self.entry_open_time_utc) if self.entry_open_time_utc is not None else None,
            "entry_open": self.entry_open,
            "exit_open_time_utc": _iso(self.exit_open_time_utc) if self.exit_open_time_utc is not None else None,
            "exit_open": self.exit_open,
            "holding_period_15m_candles": self.holding_period_15m_candles,
            "gross_return_percent_without_costs": self.gross_return_percent_without_costs,
        }
        if include_hash:
            payload["result_hash"] = self.result_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeFirstStrategyEvaluationResult":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation result must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "decision_hash",
                "decision_time_utc",
                "signal_generated",
                "status",
                "reasons",
                "signal_hash",
                "entry_open_time_utc",
                "entry_open",
                "exit_open_time_utc",
                "exit_open",
                "holding_period_15m_candles",
                "gross_return_percent_without_costs",
                "result_hash",
            },
            name="evaluation result",
        )
        try:
            return cls(
                decision_hash=mapping["decision_hash"],
                decision_time_utc=mapping["decision_time_utc"],
                signal_generated=mapping["signal_generated"],
                status=mapping["status"],
                reasons=tuple(mapping.get("reasons", ())),
                signal_hash=mapping.get("signal_hash"),
                entry_open_time_utc=mapping.get("entry_open_time_utc"),
                entry_open=mapping.get("entry_open"),
                exit_open_time_utc=mapping.get("exit_open_time_utc"),
                exit_open=mapping.get("exit_open"),
                holding_period_15m_candles=mapping.get("holding_period_15m_candles"),
                gross_return_percent_without_costs=mapping.get("gross_return_percent_without_costs"),
                result_hash=mapping.get("result_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation result is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeFirstStrategyEvaluationMetrics:
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
    schema_version: int = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_SCHEMA_VERSION
    metrics_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "signal_count", _required_int(self.signal_count, "signal_count"))
        object.__setattr__(self, "evaluated_operations", _required_int(self.evaluated_operations, "evaluated_operations"))
        object.__setattr__(self, "no_signal_decisions", _required_int(self.no_signal_decisions, "no_signal_decisions"))
        object.__setattr__(self, "not_evaluable_entries", _required_int(self.not_evaluable_entries, "not_evaluable_entries"))
        object.__setattr__(self, "win_rate_percent", Decimal(str(self.win_rate_percent)))
        object.__setattr__(self, "mean_gross_return_percent_without_costs", Decimal(str(self.mean_gross_return_percent_without_costs)))
        object.__setattr__(self, "median_gross_return_percent_without_costs", Decimal(str(self.median_gross_return_percent_without_costs)))
        object.__setattr__(self, "cumulative_simple_return_percent_without_costs", Decimal(str(self.cumulative_simple_return_percent_without_costs)))
        object.__setattr__(self, "max_loss_streak", _required_int(self.max_loss_streak, "max_loss_streak"))
        object.__setattr__(self, "max_win_streak", _required_int(self.max_win_streak, "max_win_streak"))
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_SCHEMA_VERSION:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("metrics schema_version must be 1.")
        for name, value in (
            ("signal_count", self.signal_count),
            ("evaluated_operations", self.evaluated_operations),
            ("no_signal_decisions", self.no_signal_decisions),
            ("not_evaluable_entries", self.not_evaluable_entries),
            ("max_loss_streak", self.max_loss_streak),
            ("max_win_streak", self.max_win_streak),
        ):
            if value < 0:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError(f"{name} must not be negative.")
        if self.signal_count != self.evaluated_operations + self.not_evaluable_entries:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("signal_count must equal evaluable plus not-evaluable entries.")
        expected = _hash(self.as_hash_payload(include_hash=False))
        if self.metrics_hash:
            if self.metrics_hash != expected:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("metrics hash mismatch.")
        else:
            object.__setattr__(self, "metrics_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
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
            payload["metrics_hash"] = self.metrics_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeFirstStrategyEvaluationMetrics":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation metrics must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
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
                "metrics_hash",
            },
            name="evaluation metrics",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
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
                metrics_hash=mapping.get("metrics_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation metrics are incomplete.") from exc


def _build_expected_result(
    strategy_report: HistoricalMultiTimeframeFirstStrategyReport,
    decision: HistoricalMultiTimeframeFirstStrategyDecision,
    protocol: HistoricalMultiTimeframeFirstStrategyEvaluationProtocol,
    *,
    decision_index: int,
) -> HistoricalMultiTimeframeFirstStrategyEvaluationResult:
    if not decision.signal_generated:
        return HistoricalMultiTimeframeFirstStrategyEvaluationResult(
            decision_hash=decision.decision_hash,
            decision_time_utc=decision.decision_time_utc,
            signal_generated=False,
            status=HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_NO_SIGNAL,
            reasons=decision.rejection_reasons,
        )

    signal = decision.signal
    if signal is None:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError("signal is required when the strategy decision generated one.")
    if signal.decision_time_utc != decision.decision_time_utc:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError("signal decision time diverges from the frozen decision.")
    if signal.trigger_close_time_utc != decision.decision_time_utc:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError("signal trigger close time diverges from the frozen decision.")

    base_candles = strategy_report.replay.bundle.base_dataset.candles
    expected_entry_index = decision_index + protocol.entry_delay_15m_candles
    if expected_entry_index >= len(base_candles):
        return HistoricalMultiTimeframeFirstStrategyEvaluationResult(
            decision_hash=decision.decision_hash,
            decision_time_utc=decision.decision_time_utc,
            signal_generated=True,
            status=HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_NOT_EVALUABLE,
            reasons=("next 15m candle is unavailable for the frozen entry rule.",),
            signal_hash=signal.signal_hash,
        )

    entry_candle = base_candles[expected_entry_index]
    expected_entry_open_time = decision.decision_time_utc + timedelta(milliseconds=1)
    if entry_candle.open_time.astimezone(timezone.utc) != expected_entry_open_time:
        return HistoricalMultiTimeframeFirstStrategyEvaluationResult(
            decision_hash=decision.decision_hash,
            decision_time_utc=decision.decision_time_utc,
            signal_generated=True,
            status=HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_NOT_EVALUABLE,
            reasons=("next 15m candle is missing or misaligned for the frozen entry rule.",),
            signal_hash=signal.signal_hash,
        )

    exit_index = expected_entry_index + protocol.exit_horizon_15m_candles
    if exit_index >= len(base_candles):
        return HistoricalMultiTimeframeFirstStrategyEvaluationResult(
            decision_hash=decision.decision_hash,
            decision_time_utc=decision.decision_time_utc,
            signal_generated=True,
            status=HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_NOT_EVALUABLE,
            reasons=("fixed-horizon exit candle is unavailable.",),
            signal_hash=signal.signal_hash,
            entry_open_time_utc=entry_candle.open_time,
            entry_open=entry_candle.open,
        )

    exit_candle = base_candles[exit_index]
    expected_exit_open_time = entry_candle.open_time + timedelta(minutes=15 * protocol.exit_horizon_15m_candles)
    if exit_candle.open_time.astimezone(timezone.utc) != expected_exit_open_time:
        return HistoricalMultiTimeframeFirstStrategyEvaluationResult(
            decision_hash=decision.decision_hash,
            decision_time_utc=decision.decision_time_utc,
            signal_generated=True,
            status=HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_NOT_EVALUABLE,
            reasons=("fixed-horizon exit candle is missing or misaligned.",),
            signal_hash=signal.signal_hash,
            entry_open_time_utc=entry_candle.open_time,
            entry_open=entry_candle.open,
        )

    if entry_candle.open == 0:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError("entry open price cannot be zero.")
    gross_return_percent = ((exit_candle.open - entry_candle.open) / entry_candle.open) * Decimal("100")
    return HistoricalMultiTimeframeFirstStrategyEvaluationResult(
        decision_hash=decision.decision_hash,
        decision_time_utc=decision.decision_time_utc,
        signal_generated=True,
        status=HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_EVALUATED,
        reasons=("fixed-horizon exit evaluated without costs.",),
        signal_hash=signal.signal_hash,
        entry_open_time_utc=entry_candle.open_time,
        entry_open=entry_candle.open,
        exit_open_time_utc=exit_candle.open_time,
        exit_open=exit_candle.open,
        holding_period_15m_candles=protocol.exit_horizon_15m_candles,
        gross_return_percent_without_costs=gross_return_percent,
    )


def _compute_metrics(results: Sequence[HistoricalMultiTimeframeFirstStrategyEvaluationResult]) -> HistoricalMultiTimeframeFirstStrategyEvaluationMetrics:
    returns = [result.gross_return_percent_without_costs for result in results if result.status == HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_EVALUATED]
    evaluated_operations = len(returns)
    signal_count = sum(1 for result in results if result.signal_generated)
    no_signal_decisions = sum(1 for result in results if result.status == HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_NO_SIGNAL)
    not_evaluable_entries = sum(1 for result in results if result.status == HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_NOT_EVALUABLE)
    if evaluated_operations:
        winning_operations = sum(1 for value in returns if value > 0)
        win_rate_percent = (Decimal(winning_operations) / Decimal(evaluated_operations)) * Decimal("100")
        mean_return = sum(returns, Decimal("0")) / Decimal(evaluated_operations)
        median_return = median(returns)
        cumulative = sum(returns, Decimal("0"))
    else:
        win_rate_percent = Decimal("0")
        mean_return = Decimal("0")
        median_return = Decimal("0")
        cumulative = Decimal("0")
    return HistoricalMultiTimeframeFirstStrategyEvaluationMetrics(
        signal_count=signal_count,
        evaluated_operations=evaluated_operations,
        no_signal_decisions=no_signal_decisions,
        not_evaluable_entries=not_evaluable_entries,
        win_rate_percent=win_rate_percent,
        mean_gross_return_percent_without_costs=mean_return,
        median_gross_return_percent_without_costs=median_return,
        cumulative_simple_return_percent_without_costs=cumulative,
        max_loss_streak=_max_loss_streak(returns),
        max_win_streak=_max_win_streak(returns),
    )


def build_historical_multitimeframe_first_strategy_evaluation_protocol(
    strategy_report: HistoricalMultiTimeframeFirstStrategyReport,
    *,
    exit_horizon_15m_candles: int = 4,
) -> HistoricalMultiTimeframeFirstStrategyEvaluationProtocol:
    if not isinstance(strategy_report, HistoricalMultiTimeframeFirstStrategyReport):
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("strategy_report must be a HistoricalMultiTimeframeFirstStrategyReport instance.")
    return HistoricalMultiTimeframeFirstStrategyEvaluationProtocol(
        strategy_hypothesis_version=strategy_report.factory.config.hypothesis_version,
        strategy_config_hash=strategy_report.factory.config.config_hash,
        strategy_factory_hash=strategy_report.factory.factory_hash,
        strategy_report_hash=strategy_report.report_hash,
        exit_horizon_15m_candles=exit_horizon_15m_candles,
    )


def build_historical_multitimeframe_first_strategy_evaluation_report(
    strategy_report: HistoricalMultiTimeframeFirstStrategyReport,
    *,
    protocol: HistoricalMultiTimeframeFirstStrategyEvaluationProtocol | None = None,
    exit_horizon_15m_candles: int = 4,
) -> HistoricalMultiTimeframeFirstStrategyEvaluationReport:
    if not isinstance(strategy_report, HistoricalMultiTimeframeFirstStrategyReport):
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("strategy_report must be a HistoricalMultiTimeframeFirstStrategyReport instance.")
    built_protocol = build_historical_multitimeframe_first_strategy_evaluation_protocol(
        strategy_report,
        exit_horizon_15m_candles=exit_horizon_15m_candles,
    )
    if protocol is None:
        protocol = built_protocol
    elif protocol != built_protocol:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation protocol diverges from the frozen strategy report.")
    results = _build_results(strategy_report, protocol)
    metrics = _compute_metrics(results)
    snapshots = strategy_report.replay.snapshots
    return HistoricalMultiTimeframeFirstStrategyEvaluationReport(
        strategy_report=strategy_report,
        protocol=protocol,
        results=results,
        metrics=metrics,
        period_start_utc=snapshots[0].decision_time_utc,
        period_end_utc=snapshots[-1].decision_time_utc,
        snapshot_count=len(snapshots),
        created_at_utc=datetime.now(timezone.utc),
    )


def _build_results(
    strategy_report: HistoricalMultiTimeframeFirstStrategyReport,
    protocol: HistoricalMultiTimeframeFirstStrategyEvaluationProtocol,
) -> tuple[HistoricalMultiTimeframeFirstStrategyEvaluationResult, ...]:
    if protocol.entry_delay_15m_candles != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_ENTRY_DELAY_CANDLES:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("entry delay must remain a single 15m candle.")
    decision_index = _build_decision_index(strategy_report)
    results: list[HistoricalMultiTimeframeFirstStrategyEvaluationResult] = []
    for decision in strategy_report.decisions:
        if decision.decision_time_utc not in decision_index:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError("decision time diverges from the frozen 15m replay.")
        index = decision_index[decision.decision_time_utc]
        result = _build_expected_result(strategy_report, decision, protocol, decision_index=index)
        results.append(result)
    return tuple(results)


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeFirstStrategyEvaluationReport:
    strategy_report: HistoricalMultiTimeframeFirstStrategyReport
    protocol: HistoricalMultiTimeframeFirstStrategyEvaluationProtocol
    results: tuple[HistoricalMultiTimeframeFirstStrategyEvaluationResult, ...]
    metrics: HistoricalMultiTimeframeFirstStrategyEvaluationMetrics
    period_start_utc: datetime
    period_end_utc: datetime
    snapshot_count: int
    created_at_utc: datetime
    schema_version: int = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    evaluation_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.strategy_report, HistoricalMultiTimeframeFirstStrategyReport):
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("strategy_report must be a HistoricalMultiTimeframeFirstStrategyReport instance.")
        if not isinstance(self.protocol, HistoricalMultiTimeframeFirstStrategyEvaluationProtocol):
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("protocol must be a HistoricalMultiTimeframeFirstStrategyEvaluationProtocol instance.")
        if not isinstance(self.results, tuple):
            object.__setattr__(self, "results", tuple(self.results))
        if not isinstance(self.metrics, HistoricalMultiTimeframeFirstStrategyEvaluationMetrics):
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("metrics must be a HistoricalMultiTimeframeFirstStrategyEvaluationMetrics instance.")
        object.__setattr__(self, "period_start_utc", _utc(self.period_start_utc, "period_start_utc"))
        object.__setattr__(self, "period_end_utc", _utc(self.period_end_utc, "period_end_utc"))
        object.__setattr__(self, "created_at_utc", _utc(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "snapshot_count", _required_int(self.snapshot_count, "snapshot_count"))
        object.__setattr__(self, "historical_research_only", _required_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _required_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _required_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_SCHEMA_VERSION:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation report schema_version must be 1.")
        if self.historical_research_only is not True:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("paper_promotion_eligible must be false.")
        if self.period_start_utc != self.strategy_report.replay.snapshots[0].decision_time_utc:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("period_start_utc diverges from the frozen replay.")
        if self.period_end_utc != self.strategy_report.replay.snapshots[-1].decision_time_utc:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("period_end_utc diverges from the frozen replay.")
        if self.snapshot_count != len(self.strategy_report.replay.snapshots):
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("snapshot_count diverges from the frozen replay.")
        if self.protocol.strategy_report_hash != self.strategy_report.report_hash:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("protocol strategy_report_hash diverges from the frozen strategy report.")
        if self.protocol.strategy_config_hash != self.strategy_report.factory.config.config_hash:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("protocol strategy_config_hash diverges from the frozen strategy report.")
        if self.protocol.strategy_factory_hash != self.strategy_report.factory.factory_hash:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("protocol strategy_factory_hash diverges from the frozen strategy report.")
        if self.protocol.strategy_hypothesis_version != self.strategy_report.factory.config.hypothesis_version:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("protocol strategy_hypothesis_version diverges from the frozen strategy report.")
        if len(self.results) != len(self.strategy_report.decisions):
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation result count must match the strategy decision count.")
        expected_results = _build_results(self.strategy_report, self.protocol)
        if self.results != expected_results:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError("evaluation results diverge from the frozen strategy report.")
        expected_metrics = _compute_metrics(self.results)
        if self.metrics != expected_metrics:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError("evaluation metrics diverge from the frozen evaluation results.")
        expected = _hash(self.as_hash_payload(include_hash=False))
        if self.evaluation_hash:
            if self.evaluation_hash != expected:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation hash mismatch.")
        else:
            object.__setattr__(self, "evaluation_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "strategy_report_hash": self.strategy_report.report_hash,
            "protocol": self.protocol.as_dict(),
            "results": [result.as_dict() for result in self.results],
            "metrics": self.metrics.as_dict(),
            "period_start_utc": _iso(self.period_start_utc),
            "period_end_utc": _iso(self.period_end_utc),
            "snapshot_count": self.snapshot_count,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }
        if include_hash:
            payload["evaluation_hash"] = self.evaluation_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(
            {
                "schema_version": self.schema_version,
                "strategy_report": self.strategy_report.as_dict(),
                "protocol": self.protocol.as_dict(),
                "results": [result.as_dict() for result in self.results],
                "metrics": self.metrics.as_dict(),
                "period_start_utc": _iso(self.period_start_utc),
                "period_end_utc": _iso(self.period_end_utc),
                "snapshot_count": self.snapshot_count,
                "created_at_utc": _iso(self.created_at_utc),
                "evaluation_hash": self.evaluation_hash,
                "historical_research_only": self.historical_research_only,
                "operational_evidence": self.operational_evidence,
                "paper_promotion_eligible": self.paper_promotion_eligible,
            }
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeFirstStrategyEvaluationReport":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation report must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "strategy_report",
                "protocol",
                "results",
                "metrics",
                "period_start_utc",
                "period_end_utc",
                "snapshot_count",
                "created_at_utc",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "evaluation_hash",
            },
            name="evaluation report",
        )
        try:
            strategy_report = HistoricalMultiTimeframeFirstStrategyReport.from_dict(mapping["strategy_report"])
            protocol = HistoricalMultiTimeframeFirstStrategyEvaluationProtocol.from_dict(mapping["protocol"])
            results = tuple(HistoricalMultiTimeframeFirstStrategyEvaluationResult.from_dict(item) for item in mapping["results"])
            metrics = HistoricalMultiTimeframeFirstStrategyEvaluationMetrics.from_dict(mapping["metrics"])
            return cls(
                strategy_report=strategy_report,
                protocol=protocol,
                results=results,
                metrics=metrics,
                period_start_utc=mapping["period_start_utc"],
                period_end_utc=mapping["period_end_utc"],
                snapshot_count=mapping["snapshot_count"],
                created_at_utc=mapping["created_at_utc"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                evaluation_hash=mapping.get("evaluation_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation report is incomplete.") from exc
        except (HistoricalDataValidationError, HistoricalMultiTimeframeFirstStrategyValidationError, HistoricalMultiTimeframeFirstStrategyIntegrityError, HistoricalMultiTimeframeFirstStrategyEvaluationValidationError, HistoricalMultiTimeframeExperimentIntegrityError) as exc:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError(str(exc)) from exc


def run_historical_multitimeframe_first_strategy_evaluation(
    strategy_report: HistoricalMultiTimeframeFirstStrategyReport,
    *,
    protocol: HistoricalMultiTimeframeFirstStrategyEvaluationProtocol | None = None,
    exit_horizon_15m_candles: int = 4,
    output_file: str | Path | None = None,
) -> HistoricalMultiTimeframeFirstStrategyEvaluationReport:
    if not isinstance(strategy_report, HistoricalMultiTimeframeFirstStrategyReport):
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("strategy_report must be a HistoricalMultiTimeframeFirstStrategyReport instance.")
    built_protocol = build_historical_multitimeframe_first_strategy_evaluation_protocol(
        strategy_report,
        exit_horizon_15m_candles=exit_horizon_15m_candles,
    )
    if protocol is None:
        protocol = built_protocol
    elif protocol != built_protocol:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation protocol diverges from the frozen strategy report.")
    report = build_historical_multitimeframe_first_strategy_evaluation_report(strategy_report, protocol=protocol)
    if output_file is not None:
        save_historical_multitimeframe_first_strategy_evaluation_report(output_file, report)
    return report


def _read(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("evaluation report not found.") from exc
    except Exception as exc:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError("evaluation report is invalid JSON.") from exc
    if not isinstance(value, Mapping):
        raise HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError("evaluation report must be a JSON object.")
    return value


def load_historical_multitimeframe_first_strategy_evaluation_report(path: str | Path) -> HistoricalMultiTimeframeFirstStrategyEvaluationReport:
    payload = _read(Path(path))
    try:
        report = HistoricalMultiTimeframeFirstStrategyEvaluationReport.from_dict(payload)
    except (KeyError, TypeError, HistoricalDataValidationError, HistoricalMultiTimeframeFirstStrategyValidationError, HistoricalMultiTimeframeFirstStrategyIntegrityError, HistoricalMultiTimeframeFirstStrategyEvaluationValidationError) as exc:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError(str(exc)) from exc
    if report.as_dict() != payload:
        raise HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError("evaluation report payload mismatch.")
    return report


def save_historical_multitimeframe_first_strategy_evaluation_report(
    path: str | Path,
    report: HistoricalMultiTimeframeFirstStrategyEvaluationReport,
) -> HistoricalMultiTimeframeFirstStrategyEvaluationReport:
    file_path = Path(path)
    payload = report.as_dict()
    if file_path.exists():
        existing = load_historical_multitimeframe_first_strategy_evaluation_report(file_path)
        if existing.as_dict() != payload:
            raise HistoricalMultiTimeframeFirstStrategyEvaluationConflictError("evaluation report already exists and differs.")
        return existing
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_name(f".{file_path.name}.{os.getpid()}.{id(report)}.tmp")
    try:
        tmp.write_text(_canonical_json(payload), encoding="utf-8")
        try:
            os.link(tmp, file_path)
        except FileExistsError:
            existing = load_historical_multitimeframe_first_strategy_evaluation_report(file_path)
            if existing.as_dict() != payload:
                raise HistoricalMultiTimeframeFirstStrategyEvaluationConflictError("evaluation report already exists and differs.")
            return existing
    except Exception as exc:
        if isinstance(exc, HistoricalMultiTimeframeFirstStrategyEvaluationConflictError):
            raise
        raise HistoricalMultiTimeframeFirstStrategyEvaluationValidationError("failed to write evaluation report atomically.") from exc
    finally:
        tmp.unlink(missing_ok=True)
    return report


def verify_historical_multitimeframe_first_strategy_evaluation_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_multitimeframe_first_strategy_evaluation_report(path)
    return {
        "verified": True,
        "evaluation_hash": report.evaluation_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "strategy_report_hash": report.strategy_report.report_hash,
        "classification": "historical_research_only",
    }


def status_historical_multitimeframe_first_strategy_evaluation_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_multitimeframe_first_strategy_evaluation_report(path)
    return {
        "exists": True,
        "evaluation_hash": report.evaluation_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "strategy_report_hash": report.strategy_report.report_hash,
        "period_start_utc": _iso(report.period_start_utc),
        "period_end_utc": _iso(report.period_end_utc),
        "snapshot_count": report.snapshot_count,
        "signal_count": report.metrics.signal_count,
        "evaluated_operations": report.metrics.evaluated_operations,
        "no_signal_decisions": report.metrics.no_signal_decisions,
        "not_evaluable_entries": report.metrics.not_evaluable_entries,
        "classification": "historical_research_only",
    }


def reject_historical_multitimeframe_first_strategy_evaluation_promotion(
    _: HistoricalMultiTimeframeFirstStrategyEvaluationReport,
) -> None:
    raise HistoricalMultiTimeframeFirstStrategyEvaluationPromotionError("multi-timeframe historical evaluation is not promotion evidence.")


__all__ = [
    "HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_ENTRY_DELAY_CANDLES",
    "HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_NAME",
    "HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_SCHEMA_VERSION",
    "HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_EVALUATED",
    "HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_NO_SIGNAL",
    "HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_STATUS_NOT_EVALUABLE",
    "HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_EVALUATION_VERSION",
    "HistoricalMultiTimeframeFirstStrategyEvaluationConflictError",
    "HistoricalMultiTimeframeFirstStrategyEvaluationError",
    "HistoricalMultiTimeframeFirstStrategyEvaluationIntegrityError",
    "HistoricalMultiTimeframeFirstStrategyEvaluationMetrics",
    "HistoricalMultiTimeframeFirstStrategyEvaluationProtocol",
    "HistoricalMultiTimeframeFirstStrategyEvaluationPromotionError",
    "HistoricalMultiTimeframeFirstStrategyEvaluationReport",
    "HistoricalMultiTimeframeFirstStrategyEvaluationResult",
    "HistoricalMultiTimeframeFirstStrategyEvaluationValidationError",
    "build_historical_multitimeframe_first_strategy_evaluation_protocol",
    "build_historical_multitimeframe_first_strategy_evaluation_report",
    "load_historical_multitimeframe_first_strategy_evaluation_report",
    "reject_historical_multitimeframe_first_strategy_evaluation_promotion",
    "run_historical_multitimeframe_first_strategy_evaluation",
    "save_historical_multitimeframe_first_strategy_evaluation_report",
    "status_historical_multitimeframe_first_strategy_evaluation_report",
    "verify_historical_multitimeframe_first_strategy_evaluation_report",
]
