from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value
from historical_multitimeframe_experiments import HistoricalMultiTimeframeReplay
from market_data import (
    HistoricalDataValidationError,
    HistoricalMultiTimeframeDecisionContext,
    HistoricalMultiTimeframeDecisionContextPolicy,
    HistoricalMultiTimeframeDecisionContextSeries,
    build_historical_multitimeframe_decision_context_policy,
    build_historical_multitimeframe_decision_context_series,
)


HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_SCHEMA_VERSION = 1
HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_VERSION = "phase_13b_historical_15m_1h_4h_breakout_v1"
HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_SYMBOL = "BTCUSDT"
HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_BASE_INTERVAL = "15m"
HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_ONE_HOUR_INTERVAL = "1h"
HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_FOUR_HOUR_INTERVAL = "4h"
HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_DIRECTION = "COMPRA"
HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_CONTEXT_POLICY_HASH = build_historical_multitimeframe_decision_context_policy().context_policy_hash


class HistoricalMultiTimeframeFirstStrategyError(Exception):
    pass


class HistoricalMultiTimeframeFirstStrategyValidationError(HistoricalMultiTimeframeFirstStrategyError):
    pass


class HistoricalMultiTimeframeFirstStrategyIntegrityError(HistoricalMultiTimeframeFirstStrategyValidationError):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _deserialize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _deserialize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deserialize_value(item) for item in value]
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
        try:
            return Decimal(value)
        except Exception:
            return value
    return value


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalMultiTimeframeFirstStrategyValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalMultiTimeframeFirstStrategyValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalMultiTimeframeFirstStrategyValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalMultiTimeframeFirstStrategyValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalMultiTimeframeFirstStrategyValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if type(value) is bool:
        raise HistoricalMultiTimeframeFirstStrategyValidationError(f"{field_name} must be numeric.")
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise HistoricalMultiTimeframeFirstStrategyValidationError(f"{field_name} must be numeric.") from exc


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalMultiTimeframeFirstStrategyValidationError(f"{field_name} must be timezone-aware UTC datetime.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalMultiTimeframeFirstStrategyValidationError(f"{field_name} must be timezone-aware UTC datetime.") from exc
    if not isinstance(value, datetime):
        raise HistoricalMultiTimeframeFirstStrategyValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoricalMultiTimeframeFirstStrategyValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _default_context_policy() -> HistoricalMultiTimeframeDecisionContextPolicy:
    return build_historical_multitimeframe_decision_context_policy()


def _default_context_policy_hash() -> str:
    return _default_context_policy().context_policy_hash


def _policy_from_config(
    *,
    minimum_base_candles: int,
    minimum_one_hour_candles: int,
    minimum_four_hour_candles: int,
) -> HistoricalMultiTimeframeDecisionContextPolicy:
    return build_historical_multitimeframe_decision_context_policy(
        minimum_base_candles=minimum_base_candles,
        minimum_one_hour_candles=minimum_one_hour_candles,
        minimum_four_hour_candles=minimum_four_hour_candles,
    )


def _validate_exact_keys(mapping: Mapping[str, Any], *, allowed: set[str], name: str) -> None:
    extra = set(mapping) - allowed
    if extra:
        raise HistoricalMultiTimeframeFirstStrategyValidationError(f"{name} contains unknown fields: {sorted(extra)!r}.")


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeFirstStrategyHypothesisConfig:
    schema_version: int = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_SCHEMA_VERSION
    hypothesis_version: str = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_VERSION
    symbol: str = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_SYMBOL
    base_interval: str = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_BASE_INTERVAL
    one_hour_interval: str = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_ONE_HOUR_INTERVAL
    four_hour_interval: str = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_FOUR_HOUR_INTERVAL
    one_hour_sma_period: int = 20
    four_hour_sma_period: int = 20
    donchian_lookback: int = 20
    minimum_base_candles: int = 21
    minimum_one_hour_candles: int = 20
    minimum_four_hour_candles: int = 20
    context_policy_hash: str = ""
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    config_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "hypothesis_version", _require_str(self.hypothesis_version, "hypothesis_version"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "base_interval", _require_str(self.base_interval, "base_interval"))
        object.__setattr__(self, "one_hour_interval", _require_str(self.one_hour_interval, "one_hour_interval"))
        object.__setattr__(self, "four_hour_interval", _require_str(self.four_hour_interval, "four_hour_interval"))
        object.__setattr__(self, "one_hour_sma_period", _require_int(self.one_hour_sma_period, "one_hour_sma_period"))
        object.__setattr__(self, "four_hour_sma_period", _require_int(self.four_hour_sma_period, "four_hour_sma_period"))
        object.__setattr__(self, "donchian_lookback", _require_int(self.donchian_lookback, "donchian_lookback"))
        object.__setattr__(self, "minimum_base_candles", _require_int(self.minimum_base_candles, "minimum_base_candles"))
        object.__setattr__(self, "minimum_one_hour_candles", _require_int(self.minimum_one_hour_candles, "minimum_one_hour_candles"))
        object.__setattr__(self, "minimum_four_hour_candles", _require_int(self.minimum_four_hour_candles, "minimum_four_hour_candles"))
        object.__setattr__(self, "context_policy_hash", _require_str(self.context_policy_hash, "context_policy_hash") if self.context_policy_hash else _default_context_policy_hash())
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_SCHEMA_VERSION:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("strategy schema_version must be 1.")
        if self.symbol != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_SYMBOL:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("strategy must remain bound to BTCUSDT.")
        if self.base_interval != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_BASE_INTERVAL:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("strategy base interval must remain 15m.")
        if self.one_hour_interval != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_ONE_HOUR_INTERVAL:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("strategy 1h interval mismatch.")
        if self.four_hour_interval != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_FOUR_HOUR_INTERVAL:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("strategy 4h interval mismatch.")
        if self.minimum_base_candles < self.donchian_lookback + 1:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("minimum_base_candles must cover the Donchian lookback plus trigger candle.")
        if self.minimum_one_hour_candles < self.one_hour_sma_period:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("minimum_one_hour_candles must cover the 1h SMA warm-up.")
        if self.minimum_four_hour_candles < self.four_hour_sma_period:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("minimum_four_hour_candles must cover the 4h SMA warm-up.")
        if self.context_policy_hash != _default_context_policy_hash():
            raise HistoricalMultiTimeframeFirstStrategyValidationError("context policy hash mismatch.")
        if self.historical_research_only is not True:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("paper_promotion_eligible must be false.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.config_hash:
            if self.config_hash != expected:
                raise HistoricalMultiTimeframeFirstStrategyValidationError("strategy config hash mismatch.")
        else:
            object.__setattr__(self, "config_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "hypothesis_version": self.hypothesis_version,
            "symbol": self.symbol,
            "base_interval": self.base_interval,
            "one_hour_interval": self.one_hour_interval,
            "four_hour_interval": self.four_hour_interval,
            "one_hour_sma_period": self.one_hour_sma_period,
            "four_hour_sma_period": self.four_hour_sma_period,
            "donchian_lookback": self.donchian_lookback,
            "minimum_base_candles": self.minimum_base_candles,
            "minimum_one_hour_candles": self.minimum_one_hour_candles,
            "minimum_four_hour_candles": self.minimum_four_hour_candles,
            "context_policy_hash": self.context_policy_hash,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }
        if include_hash:
            payload["config_hash"] = self.config_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeFirstStrategyHypothesisConfig":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeFirstStrategyValidationError("strategy config must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "hypothesis_version",
                "symbol",
                "base_interval",
                "one_hour_interval",
                "four_hour_interval",
                "one_hour_sma_period",
                "four_hour_sma_period",
                "donchian_lookback",
                "minimum_base_candles",
                "minimum_one_hour_candles",
                "minimum_four_hour_candles",
                "context_policy_hash",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "config_hash",
            },
            name="strategy config",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                hypothesis_version=mapping["hypothesis_version"],
                symbol=mapping["symbol"],
                base_interval=mapping["base_interval"],
                one_hour_interval=mapping["one_hour_interval"],
                four_hour_interval=mapping["four_hour_interval"],
                one_hour_sma_period=mapping["one_hour_sma_period"],
                four_hour_sma_period=mapping["four_hour_sma_period"],
                donchian_lookback=mapping["donchian_lookback"],
                minimum_base_candles=mapping["minimum_base_candles"],
                minimum_one_hour_candles=mapping["minimum_one_hour_candles"],
                minimum_four_hour_candles=mapping["minimum_four_hour_candles"],
                context_policy_hash=mapping.get("context_policy_hash", ""),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                config_hash=mapping.get("config_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("strategy config is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeFirstStrategyFactory:
    config: HistoricalMultiTimeframeFirstStrategyHypothesisConfig
    factory_identity: str = "historical_multitimeframe_first_strategy_factory"
    factory_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.config, HistoricalMultiTimeframeFirstStrategyHypothesisConfig):
            raise HistoricalMultiTimeframeFirstStrategyValidationError("config must be a HistoricalMultiTimeframeFirstStrategyHypothesisConfig instance.")
        object.__setattr__(self, "factory_identity", _require_str(self.factory_identity, "factory_identity"))
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.factory_hash:
            if self.factory_hash != expected:
                raise HistoricalMultiTimeframeFirstStrategyValidationError("strategy factory hash mismatch.")
        else:
            object.__setattr__(self, "factory_hash", expected)

    def __call__(self, context: HistoricalMultiTimeframeDecisionContext) -> "HistoricalMultiTimeframeFirstStrategyDecision":
        return evaluate_historical_multitimeframe_first_strategy(context, factory=self)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "factory_identity": self.factory_identity,
            "config": self.config.as_dict(),
        }
        if include_hash:
            payload["factory_hash"] = self.factory_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeFirstStrategyFactory":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeFirstStrategyValidationError("strategy factory must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(mapping, allowed={"factory_identity", "config", "factory_hash"}, name="strategy factory")
        try:
            return cls(
                config=HistoricalMultiTimeframeFirstStrategyHypothesisConfig.from_dict(mapping["config"]),
                factory_identity=mapping["factory_identity"],
                factory_hash=mapping.get("factory_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("strategy factory is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeFirstStrategyRuleResult:
    name: str
    passed: bool
    reason: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_str(self.name, "name"))
        object.__setattr__(self, "reason", _require_str(self.reason, "reason"))
        object.__setattr__(self, "passed", _require_bool(self.passed, "passed"))
        if not isinstance(self.details, Mapping):
            raise HistoricalMultiTimeframeFirstStrategyValidationError("details must be a mapping.")
        object.__setattr__(self, "details", dict(self.details))

    def as_hash_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "reason": self.reason,
            "details": serialize_value(self.details),
        }

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeFirstStrategyRuleResult":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeFirstStrategyValidationError("rule result must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(mapping, allowed={"name", "passed", "reason", "details"}, name="rule result")
        try:
            return cls(
                name=mapping["name"],
                passed=mapping["passed"],
                reason=mapping["reason"],
                details=_deserialize_value(mapping.get("details", {})),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("rule result is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeFirstStrategySignal:
    direction: str
    decision_time_utc: datetime
    trigger_open_time_utc: datetime
    trigger_close_time_utc: datetime
    trigger_close: Decimal
    breakout_level: Decimal
    one_hour_close: Decimal
    one_hour_sma: Decimal
    four_hour_close: Decimal
    four_hour_sma: Decimal
    donchian_lookback: int
    signal_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "direction", _require_str(self.direction, "direction").upper())
        object.__setattr__(self, "decision_time_utc", _require_utc_datetime(self.decision_time_utc, "decision_time_utc"))
        object.__setattr__(self, "trigger_open_time_utc", _require_utc_datetime(self.trigger_open_time_utc, "trigger_open_time_utc"))
        object.__setattr__(self, "trigger_close_time_utc", _require_utc_datetime(self.trigger_close_time_utc, "trigger_close_time_utc"))
        object.__setattr__(self, "trigger_close", _require_decimal(self.trigger_close, "trigger_close"))
        object.__setattr__(self, "breakout_level", _require_decimal(self.breakout_level, "breakout_level"))
        object.__setattr__(self, "one_hour_close", _require_decimal(self.one_hour_close, "one_hour_close"))
        object.__setattr__(self, "one_hour_sma", _require_decimal(self.one_hour_sma, "one_hour_sma"))
        object.__setattr__(self, "four_hour_close", _require_decimal(self.four_hour_close, "four_hour_close"))
        object.__setattr__(self, "four_hour_sma", _require_decimal(self.four_hour_sma, "four_hour_sma"))
        object.__setattr__(self, "donchian_lookback", _require_int(self.donchian_lookback, "donchian_lookback"))
        if self.direction != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_DIRECTION:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("direction must remain buy-only.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.signal_hash:
            if self.signal_hash != expected:
                raise HistoricalMultiTimeframeFirstStrategyValidationError("signal hash mismatch.")
        else:
            object.__setattr__(self, "signal_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "direction": self.direction,
            "decision_time_utc": _utc_iso(self.decision_time_utc),
            "trigger_open_time_utc": _utc_iso(self.trigger_open_time_utc),
            "trigger_close_time_utc": _utc_iso(self.trigger_close_time_utc),
            "trigger_close": self.trigger_close,
            "breakout_level": self.breakout_level,
            "one_hour_close": self.one_hour_close,
            "one_hour_sma": self.one_hour_sma,
            "four_hour_close": self.four_hour_close,
            "four_hour_sma": self.four_hour_sma,
            "donchian_lookback": self.donchian_lookback,
        }
        if include_hash:
            payload["signal_hash"] = self.signal_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeFirstStrategySignal":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeFirstStrategyValidationError("signal must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "direction",
                "decision_time_utc",
                "trigger_open_time_utc",
                "trigger_close_time_utc",
                "trigger_close",
                "breakout_level",
                "one_hour_close",
                "one_hour_sma",
                "four_hour_close",
                "four_hour_sma",
                "donchian_lookback",
                "signal_hash",
            },
            name="signal",
        )
        try:
            return cls(
                direction=mapping["direction"],
                decision_time_utc=mapping["decision_time_utc"],
                trigger_open_time_utc=mapping["trigger_open_time_utc"],
                trigger_close_time_utc=mapping["trigger_close_time_utc"],
                trigger_close=mapping["trigger_close"],
                breakout_level=mapping["breakout_level"],
                one_hour_close=mapping["one_hour_close"],
                one_hour_sma=mapping["one_hour_sma"],
                four_hour_close=mapping["four_hour_close"],
                four_hour_sma=mapping["four_hour_sma"],
                donchian_lookback=mapping["donchian_lookback"],
                signal_hash=mapping.get("signal_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("signal is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeFirstStrategyDecision:
    context_hash: str
    decision_time_utc: datetime
    config_hash: str
    rule_results: tuple[HistoricalMultiTimeframeFirstStrategyRuleResult, ...]
    signal: HistoricalMultiTimeframeFirstStrategySignal | None = None
    schema_version: int = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    decision_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "context_hash", _require_str(self.context_hash, "context_hash"))
        object.__setattr__(self, "decision_time_utc", _require_utc_datetime(self.decision_time_utc, "decision_time_utc"))
        object.__setattr__(self, "config_hash", _require_str(self.config_hash, "config_hash"))
        if not isinstance(self.rule_results, tuple):
            object.__setattr__(self, "rule_results", tuple(self.rule_results))
        if not self.rule_results:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("rule_results are required.")
        if self.signal is not None and not isinstance(self.signal, HistoricalMultiTimeframeFirstStrategySignal):
            raise HistoricalMultiTimeframeFirstStrategyValidationError("signal must be a HistoricalMultiTimeframeFirstStrategySignal instance.")
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.historical_research_only is not True:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("paper_promotion_eligible must be false.")
        passed_all = all(rule.passed for rule in self.rule_results)
        if passed_all and self.signal is None:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("signal is required when all rules pass.")
        if not passed_all and self.signal is not None:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("signal must be absent when any rule fails.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.decision_hash:
            if self.decision_hash != expected:
                raise HistoricalMultiTimeframeFirstStrategyValidationError("decision hash mismatch.")
        else:
            object.__setattr__(self, "decision_hash", expected)

    @property
    def signal_generated(self) -> bool:
        return self.signal is not None

    @property
    def rejection_reasons(self) -> tuple[str, ...]:
        return tuple(rule.reason for rule in self.rule_results if not rule.passed)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "context_hash": self.context_hash,
            "decision_time_utc": _utc_iso(self.decision_time_utc),
            "config_hash": self.config_hash,
            "rule_results": [rule.as_dict() for rule in self.rule_results],
            "signal": self.signal.as_dict() if self.signal is not None else None,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }
        if include_hash:
            payload["decision_hash"] = self.decision_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeFirstStrategyDecision":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeFirstStrategyValidationError("decision must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "context_hash",
                "decision_time_utc",
                "config_hash",
                "rule_results",
                "signal",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "decision_hash",
            },
            name="decision",
        )
        try:
            return cls(
                context_hash=mapping["context_hash"],
                decision_time_utc=mapping["decision_time_utc"],
                config_hash=mapping["config_hash"],
                rule_results=tuple(HistoricalMultiTimeframeFirstStrategyRuleResult.from_dict(item) for item in mapping["rule_results"]),
                signal=HistoricalMultiTimeframeFirstStrategySignal.from_dict(mapping["signal"]) if mapping.get("signal") is not None else None,
                schema_version=mapping["schema_version"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                decision_hash=mapping.get("decision_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("decision is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeFirstStrategyReport:
    replay: HistoricalMultiTimeframeReplay
    context_series: HistoricalMultiTimeframeDecisionContextSeries
    factory: HistoricalMultiTimeframeFirstStrategyFactory
    decisions: tuple[HistoricalMultiTimeframeFirstStrategyDecision, ...]
    schema_version: int = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    report_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.replay, HistoricalMultiTimeframeReplay):
            raise HistoricalMultiTimeframeFirstStrategyValidationError("replay must be a HistoricalMultiTimeframeReplay instance.")
        if not isinstance(self.context_series, HistoricalMultiTimeframeDecisionContextSeries):
            raise HistoricalMultiTimeframeFirstStrategyValidationError("context_series must be a HistoricalMultiTimeframeDecisionContextSeries instance.")
        if not isinstance(self.factory, HistoricalMultiTimeframeFirstStrategyFactory):
            raise HistoricalMultiTimeframeFirstStrategyValidationError("factory must be a HistoricalMultiTimeframeFirstStrategyFactory instance.")
        if not isinstance(self.decisions, tuple):
            object.__setattr__(self, "decisions", tuple(self.decisions))
        if len(self.decisions) != len(self.context_series.contexts):
            raise HistoricalMultiTimeframeFirstStrategyValidationError("decision count must match context count.")
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.replay.bundle.bundle_hash != self.context_series.bundle.bundle_hash:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("context series bundle diverges from replay bundle.")
        if self.context_series.policy.context_policy_hash != self.factory.config.context_policy_hash:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("context policy diverges from strategy config.")
        if self.historical_research_only is not True:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("paper_promotion_eligible must be false.")
        expected = tuple(self.factory(context) for context in self.context_series.contexts)
        if self.decisions != expected:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("strategy decisions diverge from the deterministic factory.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.report_hash:
            if self.report_hash != expected:
                raise HistoricalMultiTimeframeFirstStrategyValidationError("report hash mismatch.")
        else:
            object.__setattr__(self, "report_hash", expected)

    @property
    def signal_count(self) -> int:
        return sum(1 for decision in self.decisions if decision.signal_generated)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "replay": self.replay.as_dict(),
            "context_series": self.context_series.as_dict(),
            "factory": self.factory.as_dict(),
            "decisions": [decision.as_dict() for decision in self.decisions],
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeFirstStrategyReport":
        if not isinstance(data, Mapping):
            raise HistoricalMultiTimeframeFirstStrategyValidationError("strategy report must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "replay",
                "context_series",
                "factory",
                "decisions",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "report_hash",
            },
            name="strategy report",
        )
        try:
            replay = HistoricalMultiTimeframeReplay.from_dict(mapping["replay"])
            context_series = HistoricalMultiTimeframeDecisionContextSeries.from_dict(mapping["context_series"], bundle=replay.bundle)
        except HistoricalDataValidationError as exc:
            raise HistoricalMultiTimeframeFirstStrategyIntegrityError("strategy report provenance diverges from validated historical data.") from exc
        try:
            return cls(
                replay=replay,
                context_series=context_series,
                factory=HistoricalMultiTimeframeFirstStrategyFactory.from_dict(mapping["factory"]),
                decisions=tuple(HistoricalMultiTimeframeFirstStrategyDecision.from_dict(item) for item in mapping["decisions"]),
                schema_version=mapping["schema_version"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                report_hash=mapping.get("report_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalMultiTimeframeFirstStrategyValidationError("strategy report is incomplete.") from exc


def build_historical_multitimeframe_first_strategy_config(
    *,
    hypothesis_version: str = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_VERSION,
    symbol: str = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_SYMBOL,
    base_interval: str = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_BASE_INTERVAL,
    one_hour_interval: str = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_ONE_HOUR_INTERVAL,
    four_hour_interval: str = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_FOUR_HOUR_INTERVAL,
    one_hour_sma_period: int = 20,
    four_hour_sma_period: int = 20,
    donchian_lookback: int = 20,
) -> HistoricalMultiTimeframeFirstStrategyHypothesisConfig:
    return HistoricalMultiTimeframeFirstStrategyHypothesisConfig(
        hypothesis_version=hypothesis_version,
        symbol=symbol,
        base_interval=base_interval,
        one_hour_interval=one_hour_interval,
        four_hour_interval=four_hour_interval,
        one_hour_sma_period=one_hour_sma_period,
        four_hour_sma_period=four_hour_sma_period,
        donchian_lookback=donchian_lookback,
        minimum_base_candles=donchian_lookback + 1,
        minimum_one_hour_candles=one_hour_sma_period,
        minimum_four_hour_candles=four_hour_sma_period,
        context_policy_hash=_default_context_policy_hash(),
    )


def build_historical_multitimeframe_first_strategy_factory(
    config: HistoricalMultiTimeframeFirstStrategyHypothesisConfig | None = None,
) -> HistoricalMultiTimeframeFirstStrategyFactory:
    return HistoricalMultiTimeframeFirstStrategyFactory(config=config or build_historical_multitimeframe_first_strategy_config())


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise HistoricalMultiTimeframeFirstStrategyValidationError("moving average requires values.")
    total = sum(values, Decimal("0"))
    return total / Decimal(len(values))


def _latest_sma(candles: Sequence[Any], period: int) -> Decimal:
    closes = [candle.close for candle in candles]
    if len(closes) < period:
        raise HistoricalMultiTimeframeFirstStrategyValidationError("warm-up is insufficient for the moving average.")
    return _mean(closes[-period:])


def _donchian_high(previous_candles: Sequence[Any], lookback: int) -> Decimal:
    if len(previous_candles) < lookback:
        raise HistoricalMultiTimeframeFirstStrategyValidationError("warm-up is insufficient for the Donchian breakout.")
    highs = [candle.high for candle in previous_candles[-lookback:]]
    return max(highs)


def _check_rule(name: str, passed: bool, reason: str, **details: Any) -> HistoricalMultiTimeframeFirstStrategyRuleResult:
    return HistoricalMultiTimeframeFirstStrategyRuleResult(name=name, passed=passed, reason=reason, details=details)


def evaluate_historical_multitimeframe_first_strategy(
    context: HistoricalMultiTimeframeDecisionContext,
    *,
    factory: HistoricalMultiTimeframeFirstStrategyFactory | None = None,
    config: HistoricalMultiTimeframeFirstStrategyHypothesisConfig | None = None,
) -> HistoricalMultiTimeframeFirstStrategyDecision:
    if factory is None:
        factory = build_historical_multitimeframe_first_strategy_factory(config)
    if config is None:
        config = factory.config
    if not isinstance(context, HistoricalMultiTimeframeDecisionContext):
        raise HistoricalMultiTimeframeFirstStrategyValidationError("context must be a HistoricalMultiTimeframeDecisionContext instance.")
    if context.snapshot.base_point.candle.symbol != config.symbol:
        raise HistoricalMultiTimeframeFirstStrategyValidationError("context symbol diverges from strategy symbol.")
    if context.snapshot.base_point.candle.interval != config.base_interval:
        raise HistoricalMultiTimeframeFirstStrategyValidationError("context interval diverges from strategy base interval.")
    if len(context.base_window.candles) < config.minimum_base_candles:
        return HistoricalMultiTimeframeFirstStrategyDecision(
            context_hash=context.context_hash,
            decision_time_utc=context.snapshot.decision_time_utc,
            config_hash=config.config_hash,
            rule_results=(
                _check_rule(
                    "warmup_base",
                    False,
                    "warm-up insufficient for the 15m Donchian window.",
                    required=config.minimum_base_candles,
                    available=len(context.base_window.candles),
                ),
                _check_rule(
                    "warmup_one_hour",
                    len(context.supporting_windows[0].candles) >= config.minimum_one_hour_candles,
                    "warm-up insufficient for the 1h confirmation window." if len(context.supporting_windows[0].candles) < config.minimum_one_hour_candles else "1h warm-up satisfied.",
                    required=config.minimum_one_hour_candles,
                    available=len(context.supporting_windows[0].candles),
                ),
                _check_rule(
                    "warmup_four_hour",
                    len(context.supporting_windows[1].candles) >= config.minimum_four_hour_candles,
                    "warm-up insufficient for the 4h trend window." if len(context.supporting_windows[1].candles) < config.minimum_four_hour_candles else "4h warm-up satisfied.",
                    required=config.minimum_four_hour_candles,
                    available=len(context.supporting_windows[1].candles),
                ),
                _check_rule(
                    "trend_4h_above_sma",
                    False,
                    "warm-up insufficient before evaluating the 4h trend filter.",
                    required=config.four_hour_sma_period,
                    available=len(context.supporting_windows[1].candles),
                ),
                _check_rule(
                    "confirmation_1h_above_sma",
                    False,
                    "warm-up insufficient before evaluating the 1h confirmation filter.",
                    required=config.one_hour_sma_period,
                    available=len(context.supporting_windows[0].candles),
                ),
                _check_rule(
                    "donchian_breakout_15m",
                    False,
                    "warm-up insufficient before evaluating the 15m breakout.",
                    required=config.donchian_lookback + 1,
                    available=len(context.base_window.candles),
                ),
            ),
            signal=None,
        )

    four_hour_window = context.supporting_windows[1].candles
    one_hour_window = context.supporting_windows[0].candles
    base_window = context.base_window.candles
    trigger = base_window[-1]
    prior_base = base_window[:-1]

    four_hour_close = four_hour_window[-1].close
    one_hour_close = one_hour_window[-1].close
    four_hour_sma = _latest_sma(four_hour_window, config.four_hour_sma_period)
    one_hour_sma = _latest_sma(one_hour_window, config.one_hour_sma_period)
    breakout_level = _donchian_high(prior_base, config.donchian_lookback)

    trend_4h_passed = four_hour_close > four_hour_sma
    confirmation_1h_passed = one_hour_close > one_hour_sma
    breakout_passed = trigger.close > breakout_level

    rule_results = (
        _check_rule(
            "warmup_base",
            len(base_window) >= config.minimum_base_candles,
            "15m warm-up satisfied." if len(base_window) >= config.minimum_base_candles else "warm-up insufficient for the 15m Donchian window.",
            required=config.minimum_base_candles,
            available=len(base_window),
        ),
        _check_rule(
            "warmup_one_hour",
            len(one_hour_window) >= config.minimum_one_hour_candles,
            "1h warm-up satisfied." if len(one_hour_window) >= config.minimum_one_hour_candles else "warm-up insufficient for the 1h confirmation window.",
            required=config.minimum_one_hour_candles,
            available=len(one_hour_window),
        ),
        _check_rule(
            "warmup_four_hour",
            len(four_hour_window) >= config.minimum_four_hour_candles,
            "4h warm-up satisfied." if len(four_hour_window) >= config.minimum_four_hour_candles else "warm-up insufficient for the 4h trend window.",
            required=config.minimum_four_hour_candles,
            available=len(four_hour_window),
        ),
        _check_rule(
            "trend_4h_above_sma",
            trend_4h_passed,
            "4h close is above the configured 4h SMA." if trend_4h_passed else "4h close is not above the configured 4h SMA.",
            close=four_hour_close,
            sma=four_hour_sma,
            period=config.four_hour_sma_period,
        ),
        _check_rule(
            "confirmation_1h_above_sma",
            confirmation_1h_passed,
            "1h close is above the configured 1h SMA." if confirmation_1h_passed else "1h close is not above the configured 1h SMA.",
            close=one_hour_close,
            sma=one_hour_sma,
            period=config.one_hour_sma_period,
        ),
        _check_rule(
            "donchian_breakout_15m",
            breakout_passed,
            "15m close broke above the prior Donchian high." if breakout_passed else "15m close did not break above the prior Donchian high.",
            trigger_close=trigger.close,
            trigger_high=trigger.high,
            donchian_high=breakout_level,
            lookback=config.donchian_lookback,
        ),
    )

    signal = None
    if all(rule.passed for rule in rule_results):
        signal = HistoricalMultiTimeframeFirstStrategySignal(
            direction=HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_DIRECTION,
            decision_time_utc=context.snapshot.decision_time_utc,
            trigger_open_time_utc=trigger.open_time,
            trigger_close_time_utc=trigger.close_time,
            trigger_close=trigger.close,
            breakout_level=breakout_level,
            one_hour_close=one_hour_close,
            one_hour_sma=one_hour_sma,
            four_hour_close=four_hour_close,
            four_hour_sma=four_hour_sma,
            donchian_lookback=config.donchian_lookback,
        )

    return HistoricalMultiTimeframeFirstStrategyDecision(
        context_hash=context.context_hash,
        decision_time_utc=context.snapshot.decision_time_utc,
        config_hash=config.config_hash,
        rule_results=rule_results,
        signal=signal,
    )


def run_historical_multitimeframe_first_strategy(
    replay: HistoricalMultiTimeframeReplay,
    *,
    config: HistoricalMultiTimeframeFirstStrategyHypothesisConfig | None = None,
    factory: HistoricalMultiTimeframeFirstStrategyFactory | None = None,
) -> HistoricalMultiTimeframeFirstStrategyReport:
    if not isinstance(replay, HistoricalMultiTimeframeReplay):
        raise HistoricalMultiTimeframeFirstStrategyValidationError("replay must be a HistoricalMultiTimeframeReplay instance.")
    if factory is None:
        factory = build_historical_multitimeframe_first_strategy_factory(config)
    elif config is not None and config != factory.config:
        raise HistoricalMultiTimeframeFirstStrategyValidationError("strategy config diverges from the supplied factory.")
    context_series = build_historical_multitimeframe_decision_context_series(replay.bundle)
    decisions = tuple(factory(context) for context in context_series.contexts)
    return HistoricalMultiTimeframeFirstStrategyReport(
        replay=replay,
        context_series=context_series,
        factory=factory,
        decisions=decisions,
    )


__all__ = [
    "HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_BASE_INTERVAL",
    "HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_CONTEXT_POLICY_HASH",
    "HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_DIRECTION",
    "HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_FOUR_HOUR_INTERVAL",
    "HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_ONE_HOUR_INTERVAL",
    "HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_SCHEMA_VERSION",
    "HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_SYMBOL",
    "HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_VERSION",
    "HistoricalMultiTimeframeFirstStrategyError",
    "HistoricalMultiTimeframeFirstStrategyFactory",
    "HistoricalMultiTimeframeFirstStrategyHypothesisConfig",
    "HistoricalMultiTimeframeFirstStrategyIntegrityError",
    "HistoricalMultiTimeframeFirstStrategyDecision",
    "HistoricalMultiTimeframeFirstStrategyRuleResult",
    "HistoricalMultiTimeframeFirstStrategySignal",
    "HistoricalMultiTimeframeFirstStrategyValidationError",
    "build_historical_multitimeframe_first_strategy_config",
    "build_historical_multitimeframe_first_strategy_factory",
    "evaluate_historical_multitimeframe_first_strategy",
    "run_historical_multitimeframe_first_strategy",
]
