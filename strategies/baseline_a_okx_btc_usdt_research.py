from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import inspect
import json
from typing import Any, Mapping, Sequence

from domain import Candle, DataSource, MarketSnapshot
from domain.serialization import serialize_value

from market_data.offline_research_experiment_authorization import (
    OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_NON_OPERATIONAL_DECLARATION,
    OfflineResearchExperimentAuthorization,
)
from market_data.offline_research_strategy_compatibility import (
    OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION,
    OfflineResearchStrategyCompatibilityDecision,
)
from market_data.research_artifact_registry import (
    OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT,
    OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256,
    OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH,
    OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256,
    OKX_RESEARCH_ARTIFACT_INSTRUMENT,
    OKX_RESEARCH_ARTIFACT_MARKET_TYPE,
    OKX_RESEARCH_ARTIFACT_PROVIDER_NAME,
    OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC,
    OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC,
    OKX_RESEARCH_ARTIFACT_SYMBOL,
)

BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_SCHEMA_VERSION = 1
BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_ID = "baseline_a_okx_btc_usdt_1h_research"
BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_VERSION = "baseline_a_okx_btc_usdt_1h_research_v1"
BASELINE_A_OKX_BTC_USDT_RESEARCH_PURPOSE = "offline_historical_research"
BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_ALLOWED_USE_CASES: tuple[str, ...] = (
    BASELINE_A_OKX_BTC_USDT_RESEARCH_PURPOSE,
)
BASELINE_A_OKX_BTC_USDT_RESEARCH_PROHIBITED_USE_CASES: tuple[str, ...] = (
    "replay",
    "backtest",
    "walk_forward",
    "performance",
    "ranking",
    "paper",
    "live",
    "execution",
    "order_submission",
)
BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_LONG_SETUP_DETECTED = "long_setup_detected"
BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_NO_SETUP = "no_setup"
BASELINE_A_OKX_BTC_USDT_RESEARCH_ALLOWED_DECISIONS: tuple[str, ...] = (
    BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_LONG_SETUP_DETECTED,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_NO_SETUP,
)
BASELINE_A_OKX_BTC_USDT_RESEARCH_NON_OPERATIONAL_DECLARATION = (
    "This strategy is research-only and does not authorize replay, backtest, walk-forward, performance, "
    "ranking, paper trading, live trading, execution, or order submission."
)
BASELINE_A_OKX_BTC_USDT_RESEARCH_FAST_EMA = 20
BASELINE_A_OKX_BTC_USDT_RESEARCH_MID_EMA = 50
BASELINE_A_OKX_BTC_USDT_RESEARCH_SLOW_EMA = 200
BASELINE_A_OKX_BTC_USDT_RESEARCH_ATR_PERIOD = 14
BASELINE_A_OKX_BTC_USDT_RESEARCH_PULLBACK_LOOKBACK = 3
BASELINE_A_OKX_BTC_USDT_RESEARCH_STOP_ATR_MULTIPLIER = Decimal("1.5")
BASELINE_A_OKX_BTC_USDT_RESEARCH_REWARD_MULTIPLIER = Decimal("2")
BASELINE_A_OKX_BTC_USDT_RESEARCH_MIN_HISTORY = BASELINE_A_OKX_BTC_USDT_RESEARCH_SLOW_EMA + 1
BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_SOURCE = DataSource.PAPER
BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_INTERVAL = "1H"
BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_SYMBOL = OKX_RESEARCH_ARTIFACT_INSTRUMENT
BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_CANONICAL_SYMBOL = OKX_RESEARCH_ARTIFACT_SYMBOL
BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_PROVIDER = OKX_RESEARCH_ARTIFACT_PROVIDER_NAME
BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_MARKET_TYPE = OKX_RESEARCH_ARTIFACT_MARKET_TYPE


class BaselineAOkxBtcUsdtResearchError(Exception):
    pass


class BaselineAOkxBtcUsdtResearchValidationError(BaselineAOkxBtcUsdtResearchError):
    pass


class BaselineAOkxBtcUsdtResearchIntegrityError(BaselineAOkxBtcUsdtResearchError):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BaselineAOkxBtcUsdtResearchValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise BaselineAOkxBtcUsdtResearchValidationError(f"{field_name} must be a 64-character hex digest.")
    return digest


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise BaselineAOkxBtcUsdtResearchValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise BaselineAOkxBtcUsdtResearchValidationError(f"{field_name} must be a boolean.")
    return value


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise BaselineAOkxBtcUsdtResearchValidationError(f"{field_name} must be timezone-aware UTC datetime.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise BaselineAOkxBtcUsdtResearchValidationError(f"{field_name} must be timezone-aware UTC datetime.") from exc
    if not isinstance(value, datetime):
        raise BaselineAOkxBtcUsdtResearchValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise BaselineAOkxBtcUsdtResearchValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _require_candle_history(candles: Sequence[Candle]) -> tuple[Candle, ...]:
    if not isinstance(candles, Sequence):
        raise BaselineAOkxBtcUsdtResearchValidationError("candles are required.")
    items = tuple(candles)
    if len(items) < BASELINE_A_OKX_BTC_USDT_RESEARCH_MIN_HISTORY:
        raise BaselineAOkxBtcUsdtResearchValidationError("candles are insufficient for the 1H trend contract.")
    previous_open_time: datetime | None = None
    for index, candle in enumerate(items):
        if not isinstance(candle, Candle):
            raise BaselineAOkxBtcUsdtResearchValidationError("candles must contain Candle instances.")
        if candle.provider if hasattr(candle, "provider") else None:  # pragma: no cover - defensive guard
            pass
        if candle.symbol != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_SYMBOL:
            raise BaselineAOkxBtcUsdtResearchValidationError("candles must use BTC-USDT.")
        if candle.interval != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_INTERVAL:
            raise BaselineAOkxBtcUsdtResearchValidationError("candles must use 1H.")
        if candle.source != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_SOURCE:
            raise BaselineAOkxBtcUsdtResearchValidationError("candles must be synthetic PAPER candles.")
        if previous_open_time is not None:
            delta = candle.open_time - previous_open_time
            if delta != timedelta(hours=1):
                raise BaselineAOkxBtcUsdtResearchValidationError("candles must be contiguous 1H bars without gaps or duplicates.")
        previous_open_time = candle.open_time
    return items


def _closes(history: Sequence[Candle]) -> list[Decimal]:
    return [candle.close for candle in history]


def _true_ranges(history: Sequence[Candle]) -> list[Decimal]:
    ranges: list[Decimal] = []
    previous_close: Decimal | None = None
    for candle in history:
        high_low = candle.high - candle.low
        if previous_close is None:
            ranges.append(high_low)
        else:
            ranges.append(max(high_low, abs(candle.high - previous_close), abs(candle.low - previous_close)))
        previous_close = candle.close
    return ranges


def _ema_series(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    if period <= 0:
        raise BaselineAOkxBtcUsdtResearchValidationError("period must be greater than zero.")
    series: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return series
    alpha = Decimal("2") / Decimal(period + 1)
    complement = Decimal("1") - alpha
    seed = sum(values[:period], Decimal("0")) / Decimal(period)
    series[period - 1] = seed
    previous = seed
    for idx in range(period, len(values)):
        previous = (values[idx] * alpha) + (previous * complement)
        series[idx] = previous
    return series


def _atr_series(history: Sequence[Candle], period: int) -> list[Decimal | None]:
    series: list[Decimal | None] = [None] * len(history)
    if period <= 0:
        raise BaselineAOkxBtcUsdtResearchValidationError("period must be greater than zero.")
    if len(history) < period:
        return series
    true_ranges = _true_ranges(history)
    seed = sum(true_ranges[:period], Decimal("0")) / Decimal(period)
    series[period - 1] = seed
    previous = seed
    divisor = Decimal(period)
    multiplier = Decimal(period - 1)
    for idx in range(period, len(history)):
        previous = ((previous * multiplier) + true_ranges[idx]) / divisor
        series[idx] = previous
    return series


def _last_pullback_touch(history: Sequence[Candle], ema20: Sequence[Decimal | None], current_index: int) -> bool:
    start = max(0, current_index - (BASELINE_A_OKX_BTC_USDT_RESEARCH_PULLBACK_LOOKBACK - 1))
    for idx in range(start, current_index + 1):
        ema_value = ema20[idx]
        if ema_value is not None and history[idx].low <= ema_value:
            return True
    return False


@dataclass(frozen=True, slots=True)
class BaselineAOkxBtcUsdtResearchContract:
    schema_version: int = BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_SCHEMA_VERSION
    strategy_id: str = BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_ID
    strategy_version: str = BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_VERSION
    provider_name: str = BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_PROVIDER
    market_type: str = BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_MARKET_TYPE
    symbol: str = BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_SYMBOL
    canonical_symbol: str = BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_CANONICAL_SYMBOL
    interval: str = BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_INTERVAL
    requested_start_inclusive_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC
    requested_end_exclusive_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC
    expected_candle_count: int = OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT
    minimum_candles_required: int = BASELINE_A_OKX_BTC_USDT_RESEARCH_MIN_HISTORY
    trend_fast_ema_period: int = BASELINE_A_OKX_BTC_USDT_RESEARCH_FAST_EMA
    trend_mid_ema_period: int = BASELINE_A_OKX_BTC_USDT_RESEARCH_MID_EMA
    trend_slow_ema_period: int = BASELINE_A_OKX_BTC_USDT_RESEARCH_SLOW_EMA
    atr_period: int = BASELINE_A_OKX_BTC_USDT_RESEARCH_ATR_PERIOD
    pullback_lookback: int = BASELINE_A_OKX_BTC_USDT_RESEARCH_PULLBACK_LOOKBACK
    stop_atr_multiplier: Decimal = BASELINE_A_OKX_BTC_USDT_RESEARCH_STOP_ATR_MULTIPLIER
    reward_multiplier: Decimal = BASELINE_A_OKX_BTC_USDT_RESEARCH_REWARD_MULTIPLIER
    allowed_decisions: tuple[str, ...] = BASELINE_A_OKX_BTC_USDT_RESEARCH_ALLOWED_DECISIONS
    purpose: str = BASELINE_A_OKX_BTC_USDT_RESEARCH_PURPOSE
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    allowed_use_cases: tuple[str, ...] = BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_ALLOWED_USE_CASES
    prohibited_use_cases: tuple[str, ...] = BASELINE_A_OKX_BTC_USDT_RESEARCH_PROHIBITED_USE_CASES
    non_operational_declaration: str = BASELINE_A_OKX_BTC_USDT_RESEARCH_NON_OPERATIONAL_DECLARATION
    required_authorization_hash: str = ""
    required_compatibility_hash: str = ""
    no_entry_rule: str = "trend_pullback_confirmation_required"
    contract_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "strategy_id", _require_str(self.strategy_id, "strategy_id"))
        object.__setattr__(self, "strategy_version", _require_str(self.strategy_version, "strategy_version"))
        object.__setattr__(self, "provider_name", _require_str(self.provider_name, "provider_name").upper())
        object.__setattr__(self, "market_type", _require_str(self.market_type, "market_type").lower())
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "canonical_symbol", _require_str(self.canonical_symbol, "canonical_symbol").upper())
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "requested_start_inclusive_utc", _require_utc_datetime(self.requested_start_inclusive_utc, "requested_start_inclusive_utc"))
        object.__setattr__(self, "requested_end_exclusive_utc", _require_utc_datetime(self.requested_end_exclusive_utc, "requested_end_exclusive_utc"))
        object.__setattr__(self, "expected_candle_count", _require_int(self.expected_candle_count, "expected_candle_count"))
        object.__setattr__(self, "minimum_candles_required", _require_int(self.minimum_candles_required, "minimum_candles_required"))
        object.__setattr__(self, "trend_fast_ema_period", _require_int(self.trend_fast_ema_period, "trend_fast_ema_period"))
        object.__setattr__(self, "trend_mid_ema_period", _require_int(self.trend_mid_ema_period, "trend_mid_ema_period"))
        object.__setattr__(self, "trend_slow_ema_period", _require_int(self.trend_slow_ema_period, "trend_slow_ema_period"))
        object.__setattr__(self, "atr_period", _require_int(self.atr_period, "atr_period"))
        object.__setattr__(self, "pullback_lookback", _require_int(self.pullback_lookback, "pullback_lookback"))
        object.__setattr__(self, "stop_atr_multiplier", Decimal(str(self.stop_atr_multiplier)))
        object.__setattr__(self, "reward_multiplier", Decimal(str(self.reward_multiplier)))
        object.__setattr__(self, "allowed_decisions", tuple(_require_str(item, "allowed_decision") for item in self.allowed_decisions))
        object.__setattr__(self, "purpose", _require_str(self.purpose, "purpose"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "allowed_use_cases", tuple(dict.fromkeys(_require_str(item, "allowed_use_case").lower() for item in self.allowed_use_cases)))
        object.__setattr__(self, "prohibited_use_cases", tuple(dict.fromkeys(_require_str(item, "prohibited_use_case").lower() for item in self.prohibited_use_cases)))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        object.__setattr__(self, "required_authorization_hash", _require_hex_digest(self.required_authorization_hash, "required_authorization_hash"))
        object.__setattr__(self, "required_compatibility_hash", _require_hex_digest(self.required_compatibility_hash, "required_compatibility_hash"))
        object.__setattr__(self, "no_entry_rule", _require_str(self.no_entry_rule, "no_entry_rule"))
        if self.purpose != BASELINE_A_OKX_BTC_USDT_RESEARCH_PURPOSE:
            raise BaselineAOkxBtcUsdtResearchValidationError("purpose must be offline_historical_research.")
        if self.provider_name != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_PROVIDER:
            raise BaselineAOkxBtcUsdtResearchValidationError("provider_name must be OKX.")
        if self.market_type != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_MARKET_TYPE:
            raise BaselineAOkxBtcUsdtResearchValidationError("market_type must be spot.")
        if self.symbol != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_SYMBOL:
            raise BaselineAOkxBtcUsdtResearchValidationError("symbol must be BTC-USDT.")
        if self.canonical_symbol != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_CANONICAL_SYMBOL:
            raise BaselineAOkxBtcUsdtResearchValidationError("canonical_symbol must be BTCUSDT.")
        if self.interval != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_INTERVAL:
            raise BaselineAOkxBtcUsdtResearchValidationError("interval must be 1H.")
        if self.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
            raise BaselineAOkxBtcUsdtResearchIntegrityError("expected_candle_count must be 42816.")
        if self.minimum_candles_required < BASELINE_A_OKX_BTC_USDT_RESEARCH_MIN_HISTORY:
            raise BaselineAOkxBtcUsdtResearchValidationError("minimum_candles_required must be at least 201.")
        if self.trend_fast_ema_period != BASELINE_A_OKX_BTC_USDT_RESEARCH_FAST_EMA:
            raise BaselineAOkxBtcUsdtResearchIntegrityError("trend_fast_ema_period must be 20.")
        if self.trend_mid_ema_period != BASELINE_A_OKX_BTC_USDT_RESEARCH_MID_EMA:
            raise BaselineAOkxBtcUsdtResearchIntegrityError("trend_mid_ema_period must be 50.")
        if self.trend_slow_ema_period != BASELINE_A_OKX_BTC_USDT_RESEARCH_SLOW_EMA:
            raise BaselineAOkxBtcUsdtResearchIntegrityError("trend_slow_ema_period must be 200.")
        if self.atr_period != BASELINE_A_OKX_BTC_USDT_RESEARCH_ATR_PERIOD:
            raise BaselineAOkxBtcUsdtResearchIntegrityError("atr_period must be 14.")
        if self.pullback_lookback != BASELINE_A_OKX_BTC_USDT_RESEARCH_PULLBACK_LOOKBACK:
            raise BaselineAOkxBtcUsdtResearchIntegrityError("pullback_lookback must be 3.")
        if self.stop_atr_multiplier != BASELINE_A_OKX_BTC_USDT_RESEARCH_STOP_ATR_MULTIPLIER:
            raise BaselineAOkxBtcUsdtResearchIntegrityError("stop_atr_multiplier must be 1.5.")
        if self.reward_multiplier != BASELINE_A_OKX_BTC_USDT_RESEARCH_REWARD_MULTIPLIER:
            raise BaselineAOkxBtcUsdtResearchIntegrityError("reward_multiplier must be 2.")
        if self.historical_research_only is not True:
            raise BaselineAOkxBtcUsdtResearchValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise BaselineAOkxBtcUsdtResearchValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise BaselineAOkxBtcUsdtResearchValidationError("paper_promotion_eligible must be false.")
        if self.allowed_use_cases != BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_ALLOWED_USE_CASES:
            raise BaselineAOkxBtcUsdtResearchValidationError("allowed_use_cases must remain offline_historical_research.")
        if self.prohibited_use_cases != BASELINE_A_OKX_BTC_USDT_RESEARCH_PROHIBITED_USE_CASES:
            raise BaselineAOkxBtcUsdtResearchValidationError("prohibited_use_cases must block operational use cases.")
        if self.allowed_decisions != BASELINE_A_OKX_BTC_USDT_RESEARCH_ALLOWED_DECISIONS:
            raise BaselineAOkxBtcUsdtResearchValidationError("allowed_decisions must remain long_setup_detected or no_setup.")
        if self.non_operational_declaration != BASELINE_A_OKX_BTC_USDT_RESEARCH_NON_OPERATIONAL_DECLARATION:
            raise BaselineAOkxBtcUsdtResearchValidationError("non_operational_declaration diverges from the research-only contract.")
        expected_hash = _hash_payload(self.canonical_payload(include_contract_hash=False))
        if self.contract_hash:
            if self.contract_hash != expected_hash:
                raise BaselineAOkxBtcUsdtResearchIntegrityError("contract_hash mismatch.")
        else:
            object.__setattr__(self, "contract_hash", expected_hash)

    def canonical_payload(self, *, include_contract_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "provider_name": self.provider_name,
            "market_type": self.market_type,
            "symbol": self.symbol,
            "canonical_symbol": self.canonical_symbol,
            "interval": self.interval,
            "requested_start_inclusive_utc": _utc_iso(self.requested_start_inclusive_utc),
            "requested_end_exclusive_utc": _utc_iso(self.requested_end_exclusive_utc),
            "expected_candle_count": self.expected_candle_count,
            "minimum_candles_required": self.minimum_candles_required,
            "trend_fast_ema_period": self.trend_fast_ema_period,
            "trend_mid_ema_period": self.trend_mid_ema_period,
            "trend_slow_ema_period": self.trend_slow_ema_period,
            "atr_period": self.atr_period,
            "pullback_lookback": self.pullback_lookback,
            "stop_atr_multiplier": str(self.stop_atr_multiplier),
            "reward_multiplier": str(self.reward_multiplier),
            "allowed_decisions": self.allowed_decisions,
            "purpose": self.purpose,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "allowed_use_cases": self.allowed_use_cases,
            "prohibited_use_cases": self.prohibited_use_cases,
            "non_operational_declaration": self.non_operational_declaration,
            "required_authorization_hash": self.required_authorization_hash,
            "required_compatibility_hash": self.required_compatibility_hash,
            "no_entry_rule": self.no_entry_rule,
        }
        if include_contract_hash:
            payload["contract_hash"] = self.contract_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_contract_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BaselineAOkxBtcUsdtResearchContract":
        if not isinstance(data, Mapping):
            raise BaselineAOkxBtcUsdtResearchValidationError("strategy contract must be a mapping.")
        mapping = dict(data)
        allowed = {
            "schema_version",
            "strategy_id",
            "strategy_version",
            "provider_name",
            "market_type",
            "symbol",
            "canonical_symbol",
            "interval",
            "requested_start_inclusive_utc",
            "requested_end_exclusive_utc",
            "expected_candle_count",
            "minimum_candles_required",
            "trend_fast_ema_period",
            "trend_mid_ema_period",
            "trend_slow_ema_period",
            "atr_period",
            "pullback_lookback",
            "stop_atr_multiplier",
            "reward_multiplier",
            "allowed_decisions",
            "purpose",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "allowed_use_cases",
            "prohibited_use_cases",
            "non_operational_declaration",
            "required_authorization_hash",
            "required_compatibility_hash",
            "no_entry_rule",
            "contract_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise BaselineAOkxBtcUsdtResearchValidationError(f"unexpected strategy contract fields: {', '.join(extra)}.")
        try:
            return cls(
                schema_version=mapping.get("schema_version", BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_SCHEMA_VERSION),
                strategy_id=mapping["strategy_id"],
                strategy_version=mapping["strategy_version"],
                provider_name=mapping.get("provider_name", BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_PROVIDER),
                market_type=mapping.get("market_type", BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_MARKET_TYPE),
                symbol=mapping.get("symbol", BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_SYMBOL),
                canonical_symbol=mapping.get("canonical_symbol", BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_CANONICAL_SYMBOL),
                interval=mapping.get("interval", BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_INTERVAL),
                requested_start_inclusive_utc=mapping.get(
                    "requested_start_inclusive_utc", OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC
                ),
                requested_end_exclusive_utc=mapping.get(
                    "requested_end_exclusive_utc", OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC
                ),
                expected_candle_count=mapping.get("expected_candle_count", OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT),
                minimum_candles_required=mapping.get(
                    "minimum_candles_required", BASELINE_A_OKX_BTC_USDT_RESEARCH_MIN_HISTORY
                ),
                trend_fast_ema_period=mapping.get("trend_fast_ema_period", BASELINE_A_OKX_BTC_USDT_RESEARCH_FAST_EMA),
                trend_mid_ema_period=mapping.get("trend_mid_ema_period", BASELINE_A_OKX_BTC_USDT_RESEARCH_MID_EMA),
                trend_slow_ema_period=mapping.get("trend_slow_ema_period", BASELINE_A_OKX_BTC_USDT_RESEARCH_SLOW_EMA),
                atr_period=mapping.get("atr_period", BASELINE_A_OKX_BTC_USDT_RESEARCH_ATR_PERIOD),
                pullback_lookback=mapping.get("pullback_lookback", BASELINE_A_OKX_BTC_USDT_RESEARCH_PULLBACK_LOOKBACK),
                stop_atr_multiplier=mapping.get("stop_atr_multiplier", BASELINE_A_OKX_BTC_USDT_RESEARCH_STOP_ATR_MULTIPLIER),
                reward_multiplier=mapping.get("reward_multiplier", BASELINE_A_OKX_BTC_USDT_RESEARCH_REWARD_MULTIPLIER),
                allowed_decisions=tuple(
                    mapping.get("allowed_decisions", BASELINE_A_OKX_BTC_USDT_RESEARCH_ALLOWED_DECISIONS)
                ),
                purpose=mapping.get("purpose", BASELINE_A_OKX_BTC_USDT_RESEARCH_PURPOSE),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                allowed_use_cases=tuple(
                    mapping.get("allowed_use_cases", BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_ALLOWED_USE_CASES)
                ),
                prohibited_use_cases=tuple(
                    mapping.get("prohibited_use_cases", BASELINE_A_OKX_BTC_USDT_RESEARCH_PROHIBITED_USE_CASES)
                ),
                non_operational_declaration=mapping.get(
                    "non_operational_declaration", BASELINE_A_OKX_BTC_USDT_RESEARCH_NON_OPERATIONAL_DECLARATION
                ),
                required_authorization_hash=mapping["required_authorization_hash"],
                required_compatibility_hash=mapping["required_compatibility_hash"],
                no_entry_rule=mapping.get("no_entry_rule", "trend_pullback_confirmation_required"),
                contract_hash=mapping.get("contract_hash", ""),
            )
        except KeyError as exc:
            raise BaselineAOkxBtcUsdtResearchValidationError("strategy contract is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class BaselineAOkxBtcUsdtResearchDecision:
    schema_version: int = BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_SCHEMA_VERSION
    strategy_id: str = BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_ID
    strategy_version: str = BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_VERSION
    decided_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    decision: str = BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_NO_SETUP
    authorization_hash: str = ""
    compatibility_hash: str = ""
    contract_hash: str = ""
    candle_count: int = 0
    signal_side: str | None = None
    trend_state: str | None = None
    pullback_state: str | None = None
    confirmation_state: str | None = None
    theoretical_entry: Decimal | None = None
    theoretical_stop_loss: Decimal | None = None
    theoretical_take_profit: Decimal | None = None
    theoretical_rr: Decimal | None = None
    rejection_reason: str | None = None
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    decision_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "strategy_id", _require_str(self.strategy_id, "strategy_id"))
        object.__setattr__(self, "strategy_version", _require_str(self.strategy_version, "strategy_version"))
        object.__setattr__(self, "decided_at_utc", _require_utc_datetime(self.decided_at_utc, "decided_at_utc"))
        object.__setattr__(self, "decision", _require_str(self.decision, "decision"))
        object.__setattr__(self, "authorization_hash", _require_hex_digest(self.authorization_hash, "authorization_hash"))
        object.__setattr__(self, "compatibility_hash", _require_hex_digest(self.compatibility_hash, "compatibility_hash"))
        object.__setattr__(self, "contract_hash", _require_hex_digest(self.contract_hash, "contract_hash"))
        object.__setattr__(self, "candle_count", _require_int(self.candle_count, "candle_count"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.decision not in BASELINE_A_OKX_BTC_USDT_RESEARCH_ALLOWED_DECISIONS:
            raise BaselineAOkxBtcUsdtResearchValidationError("decision must be long_setup_detected or no_setup.")
        if self.historical_research_only is not True:
            raise BaselineAOkxBtcUsdtResearchValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise BaselineAOkxBtcUsdtResearchValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise BaselineAOkxBtcUsdtResearchValidationError("paper_promotion_eligible must be false.")
        if self.signal_side is not None:
            object.__setattr__(self, "signal_side", _require_str(self.signal_side, "signal_side").upper())
        if self.trend_state is not None:
            object.__setattr__(self, "trend_state", _require_str(self.trend_state, "trend_state").upper())
        if self.pullback_state is not None:
            object.__setattr__(self, "pullback_state", _require_str(self.pullback_state, "pullback_state").upper())
        if self.confirmation_state is not None:
            object.__setattr__(self, "confirmation_state", _require_str(self.confirmation_state, "confirmation_state").upper())
        if self.theoretical_entry is not None:
            object.__setattr__(self, "theoretical_entry", Decimal(str(self.theoretical_entry)))
        if self.theoretical_stop_loss is not None:
            object.__setattr__(self, "theoretical_stop_loss", Decimal(str(self.theoretical_stop_loss)))
        if self.theoretical_take_profit is not None:
            object.__setattr__(self, "theoretical_take_profit", Decimal(str(self.theoretical_take_profit)))
        if self.theoretical_rr is not None:
            object.__setattr__(self, "theoretical_rr", Decimal(str(self.theoretical_rr)))
        expected_hash = _hash_payload(self.canonical_payload(include_decision_hash=False))
        if self.decision_hash:
            if self.decision_hash != expected_hash:
                raise BaselineAOkxBtcUsdtResearchIntegrityError("decision_hash mismatch.")
        else:
            object.__setattr__(self, "decision_hash", expected_hash)

    def canonical_payload(self, *, include_decision_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "decided_at_utc": _utc_iso(self.decided_at_utc),
            "decision": self.decision,
            "authorization_hash": self.authorization_hash,
            "compatibility_hash": self.compatibility_hash,
            "contract_hash": self.contract_hash,
            "candle_count": self.candle_count,
            "signal_side": self.signal_side,
            "trend_state": self.trend_state,
            "pullback_state": self.pullback_state,
            "confirmation_state": self.confirmation_state,
            "theoretical_entry": str(self.theoretical_entry) if self.theoretical_entry is not None else None,
            "theoretical_stop_loss": str(self.theoretical_stop_loss) if self.theoretical_stop_loss is not None else None,
            "theoretical_take_profit": str(self.theoretical_take_profit) if self.theoretical_take_profit is not None else None,
            "theoretical_rr": str(self.theoretical_rr) if self.theoretical_rr is not None else None,
            "rejection_reason": self.rejection_reason,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }
        if include_decision_hash:
            payload["decision_hash"] = self.decision_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_decision_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BaselineAOkxBtcUsdtResearchDecision":
        if not isinstance(data, Mapping):
            raise BaselineAOkxBtcUsdtResearchValidationError("strategy decision must be a mapping.")
        mapping = dict(data)
        allowed = {
            "schema_version",
            "strategy_id",
            "strategy_version",
            "decided_at_utc",
            "decision",
            "authorization_hash",
            "compatibility_hash",
            "contract_hash",
            "candle_count",
            "signal_side",
            "trend_state",
            "pullback_state",
            "confirmation_state",
            "theoretical_entry",
            "theoretical_stop_loss",
            "theoretical_take_profit",
            "theoretical_rr",
            "rejection_reason",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "decision_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise BaselineAOkxBtcUsdtResearchValidationError(f"unexpected strategy decision fields: {', '.join(extra)}.")
        try:
            return cls(
                schema_version=mapping.get("schema_version", BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_SCHEMA_VERSION),
                strategy_id=mapping["strategy_id"],
                strategy_version=mapping["strategy_version"],
                decided_at_utc=mapping["decided_at_utc"],
                decision=mapping["decision"],
                authorization_hash=mapping["authorization_hash"],
                compatibility_hash=mapping["compatibility_hash"],
                contract_hash=mapping["contract_hash"],
                candle_count=mapping["candle_count"],
                signal_side=mapping.get("signal_side"),
                trend_state=mapping.get("trend_state"),
                pullback_state=mapping.get("pullback_state"),
                confirmation_state=mapping.get("confirmation_state"),
                theoretical_entry=mapping.get("theoretical_entry"),
                theoretical_stop_loss=mapping.get("theoretical_stop_loss"),
                theoretical_take_profit=mapping.get("theoretical_take_profit"),
                theoretical_rr=mapping.get("theoretical_rr"),
                rejection_reason=mapping.get("rejection_reason"),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                decision_hash=mapping.get("decision_hash", ""),
            )
        except KeyError as exc:
            raise BaselineAOkxBtcUsdtResearchValidationError("strategy decision is incomplete.") from exc


def build_baseline_a_okx_btc_usdt_research_contract(
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    *,
    strategy_version: str = BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_VERSION,
    contract_hash: str = "",
) -> BaselineAOkxBtcUsdtResearchContract:
    if not isinstance(authorization, OfflineResearchExperimentAuthorization):
        raise BaselineAOkxBtcUsdtResearchValidationError("authorization must be a verified offline research experiment authorization.")
    if not isinstance(compatibility_decision, OfflineResearchStrategyCompatibilityDecision):
        raise BaselineAOkxBtcUsdtResearchValidationError("compatibility_decision must be a verified offline compatibility decision.")
    return BaselineAOkxBtcUsdtResearchContract(
        strategy_version=strategy_version,
        requested_start_inclusive_utc=authorization.requested_start_inclusive_utc,
        requested_end_exclusive_utc=authorization.requested_end_exclusive_utc,
        expected_candle_count=authorization.candle_count,
        required_authorization_hash=authorization.authorization_hash,
        required_compatibility_hash=compatibility_decision.compatibility_hash,
        contract_hash=contract_hash,
    )


def _require_authorization(authorization: Any) -> OfflineResearchExperimentAuthorization:
    if not isinstance(authorization, OfflineResearchExperimentAuthorization):
        raise BaselineAOkxBtcUsdtResearchValidationError("authorization must be a verified offline research experiment authorization.")
    if authorization.provider_name != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_PROVIDER:
        raise BaselineAOkxBtcUsdtResearchValidationError("authorization provider_name must be OKX.")
    if authorization.market_type != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_MARKET_TYPE:
        raise BaselineAOkxBtcUsdtResearchValidationError("authorization market_type must be spot.")
    if authorization.instrument != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_SYMBOL:
        raise BaselineAOkxBtcUsdtResearchValidationError("authorization instrument must be BTC-USDT.")
    if authorization.symbol != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_CANONICAL_SYMBOL:
        raise BaselineAOkxBtcUsdtResearchValidationError("authorization symbol must be BTCUSDT.")
    if authorization.interval != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_INTERVAL:
        raise BaselineAOkxBtcUsdtResearchValidationError("authorization interval must be 1H.")
    if authorization.historical_research_only is not True:
        raise BaselineAOkxBtcUsdtResearchValidationError("historical_research_only must be true.")
    if authorization.operational_evidence is not False:
        raise BaselineAOkxBtcUsdtResearchValidationError("operational_evidence must be false.")
    if authorization.paper_promotion_eligible is not False:
        raise BaselineAOkxBtcUsdtResearchValidationError("paper_promotion_eligible must be false.")
    if authorization.non_operational_declaration != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_NON_OPERATIONAL_DECLARATION:
        raise BaselineAOkxBtcUsdtResearchValidationError("authorization non_operational_declaration diverges from the research-only contract.")
    return authorization


def _require_compatibility_decision(
    compatibility_decision: Any,
) -> OfflineResearchStrategyCompatibilityDecision:
    if not isinstance(compatibility_decision, OfflineResearchStrategyCompatibilityDecision):
        raise BaselineAOkxBtcUsdtResearchValidationError("compatibility_decision must be a verified offline compatibility decision.")
    if compatibility_decision.provider_name != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_PROVIDER:
        raise BaselineAOkxBtcUsdtResearchValidationError("compatibility decision provider_name must be OKX.")
    if compatibility_decision.market_type != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_MARKET_TYPE:
        raise BaselineAOkxBtcUsdtResearchValidationError("compatibility decision market_type must be spot.")
    if compatibility_decision.symbol != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_SYMBOL:
        raise BaselineAOkxBtcUsdtResearchValidationError("compatibility decision symbol must be BTC-USDT.")
    if compatibility_decision.canonical_symbol != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_CANONICAL_SYMBOL:
        raise BaselineAOkxBtcUsdtResearchValidationError("compatibility decision canonical_symbol must be BTCUSDT.")
    if compatibility_decision.interval != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_INTERVAL:
        raise BaselineAOkxBtcUsdtResearchValidationError("compatibility decision interval must be 1H.")
    if compatibility_decision.historical_research_only is not True:
        raise BaselineAOkxBtcUsdtResearchValidationError("compatibility decision historical_research_only must be true.")
    if compatibility_decision.operational_evidence is not False:
        raise BaselineAOkxBtcUsdtResearchValidationError("compatibility decision operational_evidence must be false.")
    if compatibility_decision.paper_promotion_eligible is not False:
        raise BaselineAOkxBtcUsdtResearchValidationError("compatibility decision paper_promotion_eligible must be false.")
    if compatibility_decision.non_operational_declaration != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION:
        raise BaselineAOkxBtcUsdtResearchValidationError("compatibility decision non_operational_declaration diverges from the research-only contract.")
    return compatibility_decision


def _build_setup_decision(
    *,
    contract: BaselineAOkxBtcUsdtResearchContract,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    decided_at_utc: datetime,
    candles: Sequence[Candle],
    entry: Decimal,
    stop_loss: Decimal,
    take_profit: Decimal,
    trend_state: str,
    pullback_state: str,
    confirmation_state: str,
    signal_side: str,
    regime: str | None,
) -> BaselineAOkxBtcUsdtResearchDecision:
    return BaselineAOkxBtcUsdtResearchDecision(
        strategy_id=contract.strategy_id,
        strategy_version=contract.strategy_version,
        decided_at_utc=decided_at_utc,
        decision=BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_LONG_SETUP_DETECTED,
        authorization_hash=authorization.authorization_hash,
        compatibility_hash=compatibility_decision.compatibility_hash,
        contract_hash=contract.contract_hash,
        candle_count=len(candles),
        signal_side=signal_side,
        trend_state=trend_state,
        pullback_state=pullback_state,
        confirmation_state=confirmation_state,
        theoretical_entry=entry,
        theoretical_stop_loss=stop_loss,
        theoretical_take_profit=take_profit,
        theoretical_rr=contract.reward_multiplier,
        rejection_reason=None,
        historical_research_only=authorization.historical_research_only and compatibility_decision.historical_research_only,
        operational_evidence=authorization.operational_evidence or compatibility_decision.operational_evidence,
        paper_promotion_eligible=authorization.paper_promotion_eligible or compatibility_decision.paper_promotion_eligible,
    )


def evaluate_baseline_a_okx_btc_usdt_research(
    candles: Sequence[Candle],
    *,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    contract: BaselineAOkxBtcUsdtResearchContract | None = None,
    snapshot: MarketSnapshot | None = None,
    decided_at_utc: datetime | None = None,
) -> BaselineAOkxBtcUsdtResearchDecision:
    authorization = _require_authorization(authorization)
    compatibility_decision = _require_compatibility_decision(compatibility_decision)
    if contract is None:
        contract = build_baseline_a_okx_btc_usdt_research_contract(authorization, compatibility_decision)
    if not isinstance(contract, BaselineAOkxBtcUsdtResearchContract):
        raise BaselineAOkxBtcUsdtResearchValidationError("strategy contract is required.")
    if contract.required_authorization_hash != authorization.authorization_hash:
        raise BaselineAOkxBtcUsdtResearchValidationError("required_authorization_hash diverges from the verified authorization.")
    if contract.required_compatibility_hash != compatibility_decision.compatibility_hash:
        raise BaselineAOkxBtcUsdtResearchValidationError("required_compatibility_hash diverges from the verified compatibility decision.")
    if contract.provider_name != authorization.provider_name or contract.provider_name != compatibility_decision.provider_name:
        raise BaselineAOkxBtcUsdtResearchValidationError("provider_name diverges from the OKX research artifact.")
    if contract.market_type != authorization.market_type or contract.market_type != compatibility_decision.market_type:
        raise BaselineAOkxBtcUsdtResearchValidationError("market_type diverges from the OKX research artifact.")
    if contract.symbol != authorization.instrument or contract.symbol != compatibility_decision.symbol:
        raise BaselineAOkxBtcUsdtResearchValidationError("symbol diverges from the OKX research artifact.")
    if contract.canonical_symbol != authorization.symbol or contract.canonical_symbol != compatibility_decision.canonical_symbol:
        raise BaselineAOkxBtcUsdtResearchValidationError("canonical_symbol diverges from the OKX research artifact.")
    if contract.interval != authorization.interval or contract.interval != compatibility_decision.interval:
        raise BaselineAOkxBtcUsdtResearchValidationError("interval diverges from the OKX research artifact.")
    if contract.requested_start_inclusive_utc != authorization.requested_start_inclusive_utc:
        raise BaselineAOkxBtcUsdtResearchValidationError("requested_start_inclusive_utc diverges from the OKX research artifact.")
    if contract.requested_end_exclusive_utc != authorization.requested_end_exclusive_utc:
        raise BaselineAOkxBtcUsdtResearchValidationError("requested_end_exclusive_utc diverges from the OKX research artifact.")
    if contract.expected_candle_count != authorization.candle_count:
        raise BaselineAOkxBtcUsdtResearchValidationError("expected_candle_count diverges from the OKX research artifact.")
    if contract.historical_research_only is not True or authorization.historical_research_only is not True:
        raise BaselineAOkxBtcUsdtResearchValidationError("historical_research_only must remain true.")
    if contract.operational_evidence is not False or authorization.operational_evidence is not False:
        raise BaselineAOkxBtcUsdtResearchValidationError("operational_evidence must remain false.")
    if contract.paper_promotion_eligible is not False or authorization.paper_promotion_eligible is not False:
        raise BaselineAOkxBtcUsdtResearchValidationError("paper_promotion_eligible must remain false.")
    if contract.non_operational_declaration != BASELINE_A_OKX_BTC_USDT_RESEARCH_NON_OPERATIONAL_DECLARATION:
        raise BaselineAOkxBtcUsdtResearchValidationError("strategy contract non_operational_declaration diverges from the research-only contract.")
    if contract.allowed_use_cases != BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_ALLOWED_USE_CASES:
        raise BaselineAOkxBtcUsdtResearchValidationError("allowed_use_cases must remain offline_historical_research.")
    if contract.prohibited_use_cases != BASELINE_A_OKX_BTC_USDT_RESEARCH_PROHIBITED_USE_CASES:
        raise BaselineAOkxBtcUsdtResearchValidationError("prohibited_use_cases must remain blocked for operational use.")
    if contract.allowed_decisions != BASELINE_A_OKX_BTC_USDT_RESEARCH_ALLOWED_DECISIONS:
        raise BaselineAOkxBtcUsdtResearchValidationError("allowed_decisions must remain long_setup_detected or no_setup.")
    if contract.no_entry_rule != "trend_pullback_confirmation_required":
        raise BaselineAOkxBtcUsdtResearchValidationError("no_entry_rule diverges from the research contract.")

    history = _require_candle_history(candles)
    if any(candle.symbol != contract.symbol for candle in history):
        raise BaselineAOkxBtcUsdtResearchValidationError("candles must use BTC-USDT.")
    if any(candle.interval != contract.interval for candle in history):
        raise BaselineAOkxBtcUsdtResearchValidationError("candles must use 1H.")
    if any(candle.source != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_SOURCE for candle in history):
        raise BaselineAOkxBtcUsdtResearchValidationError("candles must remain synthetic PAPER candles.")
    if snapshot is not None:
        if not isinstance(snapshot, MarketSnapshot):
            raise BaselineAOkxBtcUsdtResearchValidationError("snapshot must be a MarketSnapshot instance.")
        if snapshot.symbol != contract.symbol:
            raise BaselineAOkxBtcUsdtResearchValidationError("snapshot symbol diverges from the research contract.")
        if snapshot.source != BASELINE_A_OKX_BTC_USDT_RESEARCH_EXPECTED_SOURCE:
            raise BaselineAOkxBtcUsdtResearchValidationError("snapshot source must remain PAPER.")

    decided_at = _require_utc_datetime(decided_at_utc or authorization.issued_at_utc, "decided_at_utc")
    closes = _closes(history)
    ema20 = _ema_series(closes, contract.trend_fast_ema_period)
    ema50 = _ema_series(closes, contract.trend_mid_ema_period)
    ema200 = _ema_series(closes, contract.trend_slow_ema_period)
    atr14 = _atr_series(history, contract.atr_period)
    index = len(history) - 1
    previous_index = index - 1

    current_ema20 = ema20[index]
    current_ema50 = ema50[index]
    previous_ema50 = ema50[previous_index]
    current_ema200 = ema200[index]
    current_atr = atr14[index]
    if any(value is None for value in (current_ema20, current_ema50, previous_ema50, current_ema200, current_atr)):
        raise BaselineAOkxBtcUsdtResearchValidationError("candles are insufficient for the trend contract.")
    current_candle = history[index]
    previous_candle = history[previous_index]

    if current_ema50 <= current_ema200:
        return BaselineAOkxBtcUsdtResearchDecision(
            strategy_id=contract.strategy_id,
            strategy_version=contract.strategy_version,
            decided_at_utc=decided_at,
            decision=BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_NO_SETUP,
            authorization_hash=authorization.authorization_hash,
            compatibility_hash=compatibility_decision.compatibility_hash,
            contract_hash=contract.contract_hash,
            candle_count=len(history),
            trend_state="BEAR_OR_UNCLEAR",
            pullback_state="NO_TREND",
            confirmation_state="NO_TREND",
            rejection_reason="ema50 must be above ema200.",
            historical_research_only=True,
            operational_evidence=False,
            paper_promotion_eligible=False,
        )
    if current_candle.close <= current_ema200:
        return BaselineAOkxBtcUsdtResearchDecision(
            strategy_id=contract.strategy_id,
            strategy_version=contract.strategy_version,
            decided_at_utc=decided_at,
            decision=BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_NO_SETUP,
            authorization_hash=authorization.authorization_hash,
            compatibility_hash=compatibility_decision.compatibility_hash,
            contract_hash=contract.contract_hash,
            candle_count=len(history),
            trend_state="BEAR_OR_UNCLEAR",
            pullback_state="NO_TREND",
            confirmation_state="NO_TREND",
            rejection_reason="close must be above ema200.",
            historical_research_only=True,
            operational_evidence=False,
            paper_promotion_eligible=False,
        )
    if current_ema50 <= previous_ema50:
        return BaselineAOkxBtcUsdtResearchDecision(
            strategy_id=contract.strategy_id,
            strategy_version=contract.strategy_version,
            decided_at_utc=decided_at,
            decision=BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_NO_SETUP,
            authorization_hash=authorization.authorization_hash,
            compatibility_hash=compatibility_decision.compatibility_hash,
            contract_hash=contract.contract_hash,
            candle_count=len(history),
            trend_state="FLAT_OR_UNCLEAR",
            pullback_state="NO_TREND",
            confirmation_state="NO_TREND",
            rejection_reason="ema50 must be rising.",
            historical_research_only=True,
            operational_evidence=False,
            paper_promotion_eligible=False,
        )
    if current_candle.close <= current_ema20:
        return BaselineAOkxBtcUsdtResearchDecision(
            strategy_id=contract.strategy_id,
            strategy_version=contract.strategy_version,
            decided_at_utc=decided_at,
            decision=BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_NO_SETUP,
            authorization_hash=authorization.authorization_hash,
            compatibility_hash=compatibility_decision.compatibility_hash,
            contract_hash=contract.contract_hash,
            candle_count=len(history),
            trend_state="TRENDING",
            pullback_state="NOT_RECLAIMED",
            confirmation_state="NO_RECLAIM",
            rejection_reason="close must reclaim ema20.",
            historical_research_only=True,
            operational_evidence=False,
            paper_promotion_eligible=False,
        )
    if current_candle.close <= previous_candle.high:
        return BaselineAOkxBtcUsdtResearchDecision(
            strategy_id=contract.strategy_id,
            strategy_version=contract.strategy_version,
            decided_at_utc=decided_at,
            decision=BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_NO_SETUP,
            authorization_hash=authorization.authorization_hash,
            compatibility_hash=compatibility_decision.compatibility_hash,
            contract_hash=contract.contract_hash,
            candle_count=len(history),
            trend_state="TRENDING",
            pullback_state="PULLBACK_ONLY",
            confirmation_state="NO_BREAKOUT",
            rejection_reason="close must break the prior high to confirm resumption.",
            historical_research_only=True,
            operational_evidence=False,
            paper_promotion_eligible=False,
        )
    if not _last_pullback_touch(history, ema20, index):
        return BaselineAOkxBtcUsdtResearchDecision(
            strategy_id=contract.strategy_id,
            strategy_version=contract.strategy_version,
            decided_at_utc=decided_at,
            decision=BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_NO_SETUP,
            authorization_hash=authorization.authorization_hash,
            compatibility_hash=compatibility_decision.compatibility_hash,
            contract_hash=contract.contract_hash,
            candle_count=len(history),
            trend_state="TRENDING",
            pullback_state="NO_TOUCH",
            confirmation_state="NO_CONFIRMATION",
            rejection_reason="no pullback touch to ema20 in the lookback window.",
            historical_research_only=True,
            operational_evidence=False,
            paper_promotion_eligible=False,
        )
    if current_atr <= 0:
        raise BaselineAOkxBtcUsdtResearchValidationError("atr must be positive.")

    entry = current_candle.close
    stop_loss = entry - (contract.stop_atr_multiplier * current_atr)
    take_profit = entry + ((entry - stop_loss) * contract.reward_multiplier)
    if stop_loss >= entry or take_profit <= entry:
        raise BaselineAOkxBtcUsdtResearchValidationError("risk targets are invalid.")

    regime = None
    if snapshot is not None:
        regime_value = getattr(snapshot, "regime", None)
        if isinstance(regime_value, str) and regime_value.strip():
            regime = regime_value.strip().upper()

    return _build_setup_decision(
        contract=contract,
        authorization=authorization,
        compatibility_decision=compatibility_decision,
        decided_at_utc=decided_at,
        candles=history,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        trend_state="BULLISH",
        pullback_state="TOUCHED_EMA20",
        confirmation_state="BREAKOUT_CONFIRMED",
        signal_side="LONG",
        regime=regime,
    )


__all__ = [
    "BASELINE_A_OKX_BTC_USDT_RESEARCH_ALLOWED_DECISIONS",
    "BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_SCHEMA_VERSION",
    "BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_LONG_SETUP_DETECTED",
    "BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_NO_SETUP",
    "BASELINE_A_OKX_BTC_USDT_RESEARCH_PROHIBITED_USE_CASES",
    "BASELINE_A_OKX_BTC_USDT_RESEARCH_PURPOSE",
    "BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_ID",
    "BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_VERSION",
    "BaselineAOkxBtcUsdtResearchContract",
    "BaselineAOkxBtcUsdtResearchDecision",
    "BaselineAOkxBtcUsdtResearchError",
    "BaselineAOkxBtcUsdtResearchIntegrityError",
    "BaselineAOkxBtcUsdtResearchValidationError",
    "build_baseline_a_okx_btc_usdt_research_contract",
    "evaluate_baseline_a_okx_btc_usdt_research",
]
