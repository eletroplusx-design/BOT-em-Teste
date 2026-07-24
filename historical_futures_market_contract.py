from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from decimal import Decimal
from typing import Any, Mapping

from domain.serialization import serialize_value
from domain.validation import DomainValidationError, parse_decimal
from historical_multitimeframe_analysis import (
    HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_NAME,
    HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_VERSION,
    HistoricalMultiTimeframeStrategyAnalysisProtocol,
    HistoricalMultiTimeframeStrategyAnalysisReport,
    HistoricalMultiTimeframeStrategyAnalysisValidationError,
)
from historical_multitimeframe_evaluation import (
    HistoricalMultiTimeframeFirstStrategyEvaluationProtocol,
    HistoricalMultiTimeframeFirstStrategyEvaluationReport,
    HistoricalMultiTimeframeFirstStrategyEvaluationValidationError,
)
from historical_multitimeframe_strategy import (
    HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_BASE_INTERVAL,
    HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_FOUR_HOUR_INTERVAL,
    HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_ONE_HOUR_INTERVAL,
    HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_SYMBOL,
    HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_VERSION,
    HistoricalMultiTimeframeFirstStrategyReport,
    HistoricalMultiTimeframeFirstStrategyValidationError,
)


HISTORICAL_FUTURES_MARKET_CONTRACT_SCHEMA_VERSION = 1
HISTORICAL_FUTURES_MARKET_EXCHANGE = "Binance"
HISTORICAL_FUTURES_MARKET_TYPE = "USD\u24c8-M Futures"
HISTORICAL_FUTURES_MARKET_CONTRACT_TYPE = "perpetual"
HISTORICAL_FUTURES_MARKET_SETTLEMENT_CURRENCY = "USDT"
HISTORICAL_FUTURES_MARKET_TIMEFRAMES: tuple[str, ...] = (
    HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_BASE_INTERVAL,
    HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_ONE_HOUR_INTERVAL,
    HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_FOUR_HOUR_INTERVAL,
)
HISTORICAL_FUTURES_MARKET_COST_PROTOCOL_SCHEMA_VERSION = 1
HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_SCHEMA_VERSION = 1
HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_NAME = "historical_futures_market_historical_execution_policy"
HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_VERSION = "v1"
HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_EVENT_PRECEDENCE: tuple[str, ...] = (
    "missing_data",
    "future_data",
    "invalid_candle",
    "duplicate_candle",
    "out_of_order_candle",
    "same_candle_conflict",
    "reject_non_evaluable",
)
HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_SCHEMA_VERSION = 1
HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_NAME = "historical_futures_market_ambiguous_candle_policy"
HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_VERSION = "v1"
HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_RESOLUTION = "reject_non_evaluable"
HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_EVENT_PRECEDENCE: tuple[str, ...] = (
    "missing_data",
    "future_data",
    "invalid_candle",
    "duplicate_candle",
    "out_of_order_candle",
    "same_candle_conflict",
    "reject_non_evaluable",
)
HISTORICAL_FUTURES_MARKET_TEMPORAL_SPLIT_SCHEMA_VERSION = 1
HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE = "reference"
HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION = "validation"
HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST = "test"
HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_METHOD = "historical_coverage_only_v1"
HISTORICAL_FUTURES_MARKET_TEMPORAL_SPLIT_METHOD = "historical_reference_validation_test_split_v1"
HISTORICAL_FUTURES_MARKET_TEMPORAL_SPLIT_PROHIBITED_CRITERIA: tuple[str, ...] = (
    "pnl",
    "return",
    "expectancy",
    "profit_factor",
    "drawdown",
    "sizing",
    "walk_forward",
    "optimization",
    "grid_search",
    "parameter_search",
    "performance",
)
HISTORICAL_FUTURES_MARKET_COST_SCENARIO_BASE = "base"
HISTORICAL_FUTURES_MARKET_COST_SCENARIO_PESSIMISTIC = "pessimistic"
HISTORICAL_FUTURES_MARKET_COST_ENTRY_EXIT_UNIT = "fraction_of_notional"
HISTORICAL_FUTURES_MARKET_COST_SPREAD_SLIPPAGE_UNIT = "bps_of_notional"
HISTORICAL_FUTURES_MARKET_COST_FUNDING_UNIT = "fraction_per_8h_of_notional"
HISTORICAL_FUTURES_MARKET_COST_ROUNDING_RULE = "ROUND_HALF_EVEN"
HISTORICAL_FUTURES_MARKET_COST_PREMISE_METHOD = "binance_usdm_futures_public_cost_premise"
HISTORICAL_FUTURES_MARKET_COST_PREMISE_VERSION = "v1"
HISTORICAL_FUTURES_MARKET_FUNDING_METHOD_NAME = "binance_usdm_public_funding_rate_history"
HISTORICAL_FUTURES_MARKET_FUNDING_METHOD_VERSION = "v1"
HISTORICAL_FUTURES_MARKET_FUNDING_METHOD_REFERENCE = (
    "https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History"
)


class HistoricalFuturesMarketContractError(Exception):
    pass


class HistoricalFuturesMarketContractValidationError(HistoricalFuturesMarketContractError):
    pass


class HistoricalFuturesMarketContractIntegrityError(HistoricalFuturesMarketContractValidationError):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalFuturesMarketContractValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hash(value: Any, field_name: str) -> str:
    normalized = _require_str(value, field_name).lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise HistoricalFuturesMarketContractValidationError(f"{field_name} must be a 64-character hexadecimal hash.")
    return normalized


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalFuturesMarketContractValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalFuturesMarketContractValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalFuturesMarketContractValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalFuturesMarketContractValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalFuturesMarketContractValidationError(f"{field_name} must be timezone-aware UTC datetime.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalFuturesMarketContractValidationError(f"{field_name} must be timezone-aware UTC datetime.") from exc
    if not isinstance(value, datetime):
        raise HistoricalFuturesMarketContractValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoricalFuturesMarketContractValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.utcoffset() != timedelta(0):
        raise HistoricalFuturesMarketContractValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _validate_exact_keys(mapping: Mapping[str, Any], *, allowed: set[str], name: str) -> None:
    extra = set(mapping) - allowed
    if extra:
        raise HistoricalFuturesMarketContractValidationError(f"{name} contains unknown fields: {sorted(extra)!r}.")


def _research_only_flags(historical_research_only: bool, operational_evidence: bool, paper_promotion_eligible: bool) -> None:
    if historical_research_only is not True:
        raise HistoricalFuturesMarketContractValidationError("historical_research_only must be true.")
    if operational_evidence is not False:
        raise HistoricalFuturesMarketContractValidationError("operational_evidence must be false.")
    if paper_promotion_eligible is not False:
        raise HistoricalFuturesMarketContractValidationError("paper_promotion_eligible must be false.")


def _require_decimal(value: Any, field_name: str, *, allow_zero: bool = True) -> Decimal:
    try:
        decimal_value = parse_decimal(value, field_name, allow_zero=allow_zero)
    except DomainValidationError as exc:
        raise HistoricalFuturesMarketContractValidationError(str(exc)) from exc
    if decimal_value < 0:
        raise HistoricalFuturesMarketContractValidationError(f"{field_name} cannot be negative.")
    return decimal_value


def _require_unit(value: Any, field_name: str, *, expected: str) -> str:
    unit = _require_str(value, field_name)
    if unit != expected:
        raise HistoricalFuturesMarketContractValidationError(f"{field_name} must be {expected}.")
    return unit


def _require_https_reference(value: Any, field_name: str) -> str:
    reference = _require_str(value, field_name)
    if not reference.startswith("https://"):
        raise HistoricalFuturesMarketContractValidationError(f"{field_name} must be a public HTTPS reference.")
    return reference


def _require_future_bound_utc(value: Any, field_name: str) -> datetime:
    dt = _require_utc_datetime(value, field_name)
    if dt > datetime.now(timezone.utc):
        raise HistoricalFuturesMarketContractValidationError(f"{field_name} cannot be in the future.")
    return dt


def _require_temporal_selection_basis(value: Any, field_name: str) -> str:
    basis = _require_str(value, field_name)
    normalized = basis.lower()
    if normalized in HISTORICAL_FUTURES_MARKET_TEMPORAL_SPLIT_PROHIBITED_CRITERIA:
        raise HistoricalFuturesMarketContractValidationError(f"{field_name} cannot use performance-based criteria.")
    if normalized != HISTORICAL_FUTURES_MARKET_TEMPORAL_SPLIT_METHOD:
        raise HistoricalFuturesMarketContractValidationError(f"{field_name} diverges from the trusted temporal split methodology.")
    return normalized


def _require_supported_symbol_and_timeframes(symbol: str, timeframes: tuple[str, ...]) -> None:
    if symbol != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_SYMBOL:
        raise HistoricalFuturesMarketContractValidationError("symbol diverges from the trusted Phase 13B artifact.")
    if timeframes != HISTORICAL_FUTURES_MARKET_TIMEFRAMES:
        raise HistoricalFuturesMarketContractValidationError("timeframes diverge from the trusted Phase 13B artifact.")


def _split_btcusdt_symbol(symbol: str) -> tuple[str, str, str]:
    normalized = _require_str(symbol, "symbol").upper()
    if normalized != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_SYMBOL:
        raise HistoricalFuturesMarketContractValidationError("only the BTCUSDT research contract is supported in this phase.")
    return "BTC", "USDT", "USDT"


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketIdentity:
    exchange: str = HISTORICAL_FUTURES_MARKET_EXCHANGE
    market_type: str = HISTORICAL_FUTURES_MARKET_TYPE
    contract_type: str = HISTORICAL_FUTURES_MARKET_CONTRACT_TYPE
    symbol: str = HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_SYMBOL
    base_asset: str = "BTC"
    margin_asset: str = "USDT"
    settlement_asset: str = "USDT"
    timeframes: tuple[str, ...] = HISTORICAL_FUTURES_MARKET_TIMEFRAMES
    identity_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "exchange", _require_str(self.exchange, "exchange"))
        object.__setattr__(self, "market_type", _require_str(self.market_type, "market_type"))
        object.__setattr__(self, "contract_type", _require_str(self.contract_type, "contract_type"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "base_asset", _require_str(self.base_asset, "base_asset").upper())
        object.__setattr__(self, "margin_asset", _require_str(self.margin_asset, "margin_asset").upper())
        object.__setattr__(self, "settlement_asset", _require_str(self.settlement_asset, "settlement_asset").upper())
        if not isinstance(self.timeframes, tuple):
            object.__setattr__(self, "timeframes", tuple(self.timeframes))
        object.__setattr__(self, "timeframes", tuple(_require_str(item, "timeframe") for item in self.timeframes))
        if self.exchange != HISTORICAL_FUTURES_MARKET_EXCHANGE:
            raise HistoricalFuturesMarketContractValidationError("exchange must remain Binance.")
        if self.market_type != HISTORICAL_FUTURES_MARKET_TYPE:
            raise HistoricalFuturesMarketContractValidationError("market_type must remain USDⓈ-M Futures.")
        if self.contract_type != HISTORICAL_FUTURES_MARKET_CONTRACT_TYPE:
            raise HistoricalFuturesMarketContractValidationError("contract_type must remain perpetual.")
        if len(self.timeframes) != len(HISTORICAL_FUTURES_MARKET_TIMEFRAMES) or self.timeframes != HISTORICAL_FUTURES_MARKET_TIMEFRAMES:
            raise HistoricalFuturesMarketContractValidationError("timeframes must remain the trusted 15m/1h/4h contract.")
        expected_base, expected_margin, expected_settlement = _split_btcusdt_symbol(self.symbol)
        if self.base_asset != expected_base:
            raise HistoricalFuturesMarketContractValidationError("base_asset diverges from the trusted BTCUSDT contract.")
        if self.margin_asset != expected_margin:
            raise HistoricalFuturesMarketContractValidationError("margin_asset diverges from the trusted BTCUSDT contract.")
        if self.settlement_asset != expected_settlement:
            raise HistoricalFuturesMarketContractValidationError("settlement_asset diverges from the trusted BTCUSDT contract.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.identity_hash:
            if self.identity_hash != expected:
                raise HistoricalFuturesMarketContractValidationError("identity hash mismatch.")
        else:
            object.__setattr__(self, "identity_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "exchange": self.exchange,
            "market_type": self.market_type,
            "contract_type": self.contract_type,
            "symbol": self.symbol,
            "base_asset": self.base_asset,
            "margin_asset": self.margin_asset,
            "settlement_asset": self.settlement_asset,
            "timeframes": list(self.timeframes),
        }
        if include_hash:
            payload["identity_hash"] = self.identity_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketIdentity":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketContractValidationError("market identity must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={"exchange", "market_type", "contract_type", "symbol", "base_asset", "margin_asset", "settlement_asset", "timeframes", "identity_hash"},
            name="market identity",
        )
        try:
            return cls(
                exchange=mapping["exchange"],
                market_type=mapping["market_type"],
                contract_type=mapping["contract_type"],
                symbol=mapping["symbol"],
                base_asset=mapping["base_asset"],
                margin_asset=mapping["margin_asset"],
                settlement_asset=mapping["settlement_asset"],
                timeframes=tuple(mapping["timeframes"]),
                identity_hash=mapping.get("identity_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketContractValidationError("market identity is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketHypothesisReference13B:
    hypothesis_version: str
    strategy_config_hash: str
    strategy_factory_hash: str
    strategy_report_hash: str
    replay_hash: str
    bundle_hash: str
    context_policy_hash: str
    symbol: str
    base_interval: str
    one_hour_interval: str
    four_hour_interval: str
    reference_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "hypothesis_version", _require_str(self.hypothesis_version, "hypothesis_version"))
        object.__setattr__(self, "strategy_config_hash", _require_hash(self.strategy_config_hash, "strategy_config_hash"))
        object.__setattr__(self, "strategy_factory_hash", _require_hash(self.strategy_factory_hash, "strategy_factory_hash"))
        object.__setattr__(self, "strategy_report_hash", _require_hash(self.strategy_report_hash, "strategy_report_hash"))
        object.__setattr__(self, "replay_hash", _require_hash(self.replay_hash, "replay_hash"))
        object.__setattr__(self, "bundle_hash", _require_hash(self.bundle_hash, "bundle_hash"))
        object.__setattr__(self, "context_policy_hash", _require_hash(self.context_policy_hash, "context_policy_hash"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "base_interval", _require_str(self.base_interval, "base_interval"))
        object.__setattr__(self, "one_hour_interval", _require_str(self.one_hour_interval, "one_hour_interval"))
        object.__setattr__(self, "four_hour_interval", _require_str(self.four_hour_interval, "four_hour_interval"))
        _require_supported_symbol_and_timeframes(self.symbol, (self.base_interval, self.one_hour_interval, self.four_hour_interval))
        if self.hypothesis_version != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_VERSION:
            raise HistoricalFuturesMarketContractValidationError("hypothesis_version diverges from the trusted Phase 13B artifact.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.reference_hash:
            if self.reference_hash != expected:
                raise HistoricalFuturesMarketContractValidationError("13B reference hash mismatch.")
        else:
            object.__setattr__(self, "reference_hash", expected)

    @classmethod
    def from_strategy_report(cls, strategy_report: HistoricalMultiTimeframeFirstStrategyReport) -> "HistoricalFuturesMarketHypothesisReference13B":
        if not isinstance(strategy_report, HistoricalMultiTimeframeFirstStrategyReport):
            raise HistoricalFuturesMarketContractValidationError("strategy_report must be a HistoricalMultiTimeframeFirstStrategyReport instance.")
        config = strategy_report.factory.config
        return cls(
            hypothesis_version=config.hypothesis_version,
            strategy_config_hash=config.config_hash,
            strategy_factory_hash=strategy_report.factory.factory_hash,
            strategy_report_hash=strategy_report.report_hash,
            replay_hash=strategy_report.replay.replay_hash,
            bundle_hash=strategy_report.replay.bundle.bundle_hash,
            context_policy_hash=config.context_policy_hash,
            symbol=config.symbol,
            base_interval=config.base_interval,
            one_hour_interval=config.one_hour_interval,
            four_hour_interval=config.four_hour_interval,
        )

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "hypothesis_version": self.hypothesis_version,
            "strategy_config_hash": self.strategy_config_hash,
            "strategy_factory_hash": self.strategy_factory_hash,
            "strategy_report_hash": self.strategy_report_hash,
            "replay_hash": self.replay_hash,
            "bundle_hash": self.bundle_hash,
            "context_policy_hash": self.context_policy_hash,
            "symbol": self.symbol,
            "base_interval": self.base_interval,
            "one_hour_interval": self.one_hour_interval,
            "four_hour_interval": self.four_hour_interval,
        }
        if include_hash:
            payload["reference_hash"] = self.reference_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketHypothesisReference13B":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketContractValidationError("13B reference must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "hypothesis_version",
                "strategy_config_hash",
                "strategy_factory_hash",
                "strategy_report_hash",
                "replay_hash",
                "bundle_hash",
                "context_policy_hash",
                "symbol",
                "base_interval",
                "one_hour_interval",
                "four_hour_interval",
                "reference_hash",
            },
            name="13B reference",
        )
        try:
            return cls(
                hypothesis_version=mapping["hypothesis_version"],
                strategy_config_hash=mapping["strategy_config_hash"],
                strategy_factory_hash=mapping["strategy_factory_hash"],
                strategy_report_hash=mapping["strategy_report_hash"],
                replay_hash=mapping["replay_hash"],
                bundle_hash=mapping["bundle_hash"],
                context_policy_hash=mapping["context_policy_hash"],
                symbol=mapping["symbol"],
                base_interval=mapping["base_interval"],
                one_hour_interval=mapping["one_hour_interval"],
                four_hour_interval=mapping["four_hour_interval"],
                reference_hash=mapping.get("reference_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketContractValidationError("13B reference is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketEvaluationReference13C:
    evaluation_name: str
    evaluation_version: str
    strategy_hypothesis_version: str
    strategy_config_hash: str
    strategy_factory_hash: str
    strategy_report_hash: str
    replay_hash: str
    bundle_hash: str
    evaluation_protocol_hash: str
    evaluation_hash: str
    reference_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluation_name", _require_str(self.evaluation_name, "evaluation_name"))
        object.__setattr__(self, "evaluation_version", _require_str(self.evaluation_version, "evaluation_version"))
        object.__setattr__(self, "strategy_hypothesis_version", _require_str(self.strategy_hypothesis_version, "strategy_hypothesis_version"))
        object.__setattr__(self, "strategy_config_hash", _require_hash(self.strategy_config_hash, "strategy_config_hash"))
        object.__setattr__(self, "strategy_factory_hash", _require_hash(self.strategy_factory_hash, "strategy_factory_hash"))
        object.__setattr__(self, "strategy_report_hash", _require_hash(self.strategy_report_hash, "strategy_report_hash"))
        object.__setattr__(self, "replay_hash", _require_hash(self.replay_hash, "replay_hash"))
        object.__setattr__(self, "bundle_hash", _require_hash(self.bundle_hash, "bundle_hash"))
        object.__setattr__(self, "evaluation_protocol_hash", _require_hash(self.evaluation_protocol_hash, "evaluation_protocol_hash"))
        object.__setattr__(self, "evaluation_hash", _require_hash(self.evaluation_hash, "evaluation_hash"))
        if self.evaluation_name != "historical_multitimeframe_first_strategy_evaluation":
            raise HistoricalFuturesMarketContractValidationError("evaluation_name diverges from the trusted Phase 13C artifact.")
        if self.evaluation_version != "v1":
            raise HistoricalFuturesMarketContractValidationError("evaluation_version diverges from the trusted Phase 13C artifact.")
        if self.strategy_hypothesis_version != HISTORICAL_MULTITIMEFRAME_FIRST_STRATEGY_VERSION:
            raise HistoricalFuturesMarketContractValidationError("strategy_hypothesis_version diverges from the trusted Phase 13B artifact.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.reference_hash:
            if self.reference_hash != expected:
                raise HistoricalFuturesMarketContractValidationError("13C reference hash mismatch.")
        else:
            object.__setattr__(self, "reference_hash", expected)

    @classmethod
    def from_evaluation_report(cls, evaluation_report: HistoricalMultiTimeframeFirstStrategyEvaluationReport) -> "HistoricalFuturesMarketEvaluationReference13C":
        if not isinstance(evaluation_report, HistoricalMultiTimeframeFirstStrategyEvaluationReport):
            raise HistoricalFuturesMarketContractValidationError("evaluation_report must be a HistoricalMultiTimeframeFirstStrategyEvaluationReport instance.")
        protocol = evaluation_report.protocol
        strategy_report = evaluation_report.strategy_report
        return cls(
            evaluation_name=protocol.evaluation_name,
            evaluation_version=protocol.evaluation_version,
            strategy_hypothesis_version=protocol.strategy_hypothesis_version,
            strategy_config_hash=protocol.strategy_config_hash,
            strategy_factory_hash=protocol.strategy_factory_hash,
            strategy_report_hash=protocol.strategy_report_hash,
            replay_hash=strategy_report.replay.replay_hash,
            bundle_hash=strategy_report.replay.bundle.bundle_hash,
            evaluation_protocol_hash=protocol.protocol_hash,
            evaluation_hash=evaluation_report.evaluation_hash,
        )

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "evaluation_name": self.evaluation_name,
            "evaluation_version": self.evaluation_version,
            "strategy_hypothesis_version": self.strategy_hypothesis_version,
            "strategy_config_hash": self.strategy_config_hash,
            "strategy_factory_hash": self.strategy_factory_hash,
            "strategy_report_hash": self.strategy_report_hash,
            "replay_hash": self.replay_hash,
            "bundle_hash": self.bundle_hash,
            "evaluation_protocol_hash": self.evaluation_protocol_hash,
            "evaluation_hash": self.evaluation_hash,
        }
        if include_hash:
            payload["reference_hash"] = self.reference_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketEvaluationReference13C":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketContractValidationError("13C reference must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "evaluation_name",
                "evaluation_version",
                "strategy_hypothesis_version",
                "strategy_config_hash",
                "strategy_factory_hash",
                "strategy_report_hash",
                "replay_hash",
                "bundle_hash",
                "evaluation_protocol_hash",
                "evaluation_hash",
                "reference_hash",
            },
            name="13C reference",
        )
        try:
            return cls(
                evaluation_name=mapping["evaluation_name"],
                evaluation_version=mapping["evaluation_version"],
                strategy_hypothesis_version=mapping["strategy_hypothesis_version"],
                strategy_config_hash=mapping["strategy_config_hash"],
                strategy_factory_hash=mapping["strategy_factory_hash"],
                strategy_report_hash=mapping["strategy_report_hash"],
                replay_hash=mapping["replay_hash"],
                bundle_hash=mapping["bundle_hash"],
                evaluation_protocol_hash=mapping["evaluation_protocol_hash"],
                evaluation_hash=mapping["evaluation_hash"],
                reference_hash=mapping.get("reference_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketContractValidationError("13C reference is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketAnalysisReference13D:
    analysis_name: str
    analysis_version: str
    strategy_hypothesis_version: str
    strategy_config_hash: str
    strategy_factory_hash: str
    strategy_report_hash: str
    evaluation_protocol_hash: str
    evaluation_hash: str
    replay_hash: str
    bundle_hash: str
    source_hash: str
    analysis_protocol_hash: str
    analysis_hash: str
    symbol: str
    base_interval: str
    one_hour_interval: str
    four_hour_interval: str
    period_start_utc: datetime
    period_end_utc: datetime
    snapshot_count: int
    reference_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "analysis_name", _require_str(self.analysis_name, "analysis_name"))
        object.__setattr__(self, "analysis_version", _require_str(self.analysis_version, "analysis_version"))
        object.__setattr__(self, "strategy_hypothesis_version", _require_str(self.strategy_hypothesis_version, "strategy_hypothesis_version"))
        object.__setattr__(self, "strategy_config_hash", _require_hash(self.strategy_config_hash, "strategy_config_hash"))
        object.__setattr__(self, "strategy_factory_hash", _require_hash(self.strategy_factory_hash, "strategy_factory_hash"))
        object.__setattr__(self, "strategy_report_hash", _require_hash(self.strategy_report_hash, "strategy_report_hash"))
        object.__setattr__(self, "evaluation_protocol_hash", _require_hash(self.evaluation_protocol_hash, "evaluation_protocol_hash"))
        object.__setattr__(self, "evaluation_hash", _require_hash(self.evaluation_hash, "evaluation_hash"))
        object.__setattr__(self, "replay_hash", _require_hash(self.replay_hash, "replay_hash"))
        object.__setattr__(self, "bundle_hash", _require_hash(self.bundle_hash, "bundle_hash"))
        object.__setattr__(self, "source_hash", _require_hash(self.source_hash, "source_hash"))
        object.__setattr__(self, "analysis_protocol_hash", _require_hash(self.analysis_protocol_hash, "analysis_protocol_hash"))
        object.__setattr__(self, "analysis_hash", _require_hash(self.analysis_hash, "analysis_hash"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "base_interval", _require_str(self.base_interval, "base_interval"))
        object.__setattr__(self, "one_hour_interval", _require_str(self.one_hour_interval, "one_hour_interval"))
        object.__setattr__(self, "four_hour_interval", _require_str(self.four_hour_interval, "four_hour_interval"))
        object.__setattr__(self, "period_start_utc", _require_utc_datetime(self.period_start_utc, "period_start_utc"))
        object.__setattr__(self, "period_end_utc", _require_utc_datetime(self.period_end_utc, "period_end_utc"))
        object.__setattr__(self, "snapshot_count", _require_int(self.snapshot_count, "snapshot_count"))
        if self.analysis_name != HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_NAME:
            raise HistoricalFuturesMarketContractValidationError("analysis_name diverges from the trusted Phase 13D artifact.")
        if self.analysis_version != HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_VERSION:
            raise HistoricalFuturesMarketContractValidationError("analysis_version diverges from the trusted Phase 13D artifact.")
        _require_supported_symbol_and_timeframes(self.symbol, (self.base_interval, self.one_hour_interval, self.four_hour_interval))
        if self.period_end_utc <= self.period_start_utc:
            raise HistoricalFuturesMarketContractValidationError("period_end_utc must be after period_start_utc.")
        if self.snapshot_count <= 0:
            raise HistoricalFuturesMarketContractValidationError("snapshot_count must be greater than zero.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.reference_hash:
            if self.reference_hash != expected:
                raise HistoricalFuturesMarketContractValidationError("13D reference hash mismatch.")
        else:
            object.__setattr__(self, "reference_hash", expected)

    @classmethod
    def from_analysis_report(cls, analysis_report: HistoricalMultiTimeframeStrategyAnalysisReport) -> "HistoricalFuturesMarketAnalysisReference13D":
        if not isinstance(analysis_report, HistoricalMultiTimeframeStrategyAnalysisReport):
            raise HistoricalFuturesMarketContractValidationError("analysis_report must be a HistoricalMultiTimeframeStrategyAnalysisReport instance.")
        protocol = analysis_report.protocol
        source = protocol.source
        return cls(
            analysis_name=HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_NAME,
            analysis_version=HISTORICAL_MULTITIMEFRAME_STRATEGY_ANALYSIS_VERSION,
            strategy_hypothesis_version=source.strategy_hypothesis_version,
            strategy_config_hash=source.strategy_config_hash,
            strategy_factory_hash=source.strategy_factory_hash,
            strategy_report_hash=source.strategy_report_hash,
            evaluation_protocol_hash=source.evaluation_protocol_hash,
            evaluation_hash=source.evaluation_hash,
            replay_hash=source.replay_hash,
            bundle_hash=source.bundle_hash,
            source_hash=source.source_hash,
            analysis_protocol_hash=protocol.protocol_hash,
            analysis_hash=analysis_report.report_hash,
            symbol=source.symbol,
            base_interval=source.base_interval,
            one_hour_interval=source.one_hour_interval,
            four_hour_interval=source.four_hour_interval,
            period_start_utc=source.period_start_utc,
            period_end_utc=source.period_end_utc,
            snapshot_count=source.snapshot_count,
        )

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "analysis_name": self.analysis_name,
            "analysis_version": self.analysis_version,
            "strategy_hypothesis_version": self.strategy_hypothesis_version,
            "strategy_config_hash": self.strategy_config_hash,
            "strategy_factory_hash": self.strategy_factory_hash,
            "strategy_report_hash": self.strategy_report_hash,
            "evaluation_protocol_hash": self.evaluation_protocol_hash,
            "evaluation_hash": self.evaluation_hash,
            "replay_hash": self.replay_hash,
            "bundle_hash": self.bundle_hash,
            "source_hash": self.source_hash,
            "analysis_protocol_hash": self.analysis_protocol_hash,
            "analysis_hash": self.analysis_hash,
            "symbol": self.symbol,
            "base_interval": self.base_interval,
            "one_hour_interval": self.one_hour_interval,
            "four_hour_interval": self.four_hour_interval,
            "period_start_utc": _utc_iso(self.period_start_utc),
            "period_end_utc": _utc_iso(self.period_end_utc),
            "snapshot_count": self.snapshot_count,
        }
        if include_hash:
            payload["reference_hash"] = self.reference_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketAnalysisReference13D":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketContractValidationError("13D reference must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "analysis_name",
                "analysis_version",
                "strategy_hypothesis_version",
                "strategy_config_hash",
                "strategy_factory_hash",
                "strategy_report_hash",
                "evaluation_protocol_hash",
                "evaluation_hash",
                "replay_hash",
                "bundle_hash",
                "source_hash",
                "analysis_protocol_hash",
                "analysis_hash",
                "symbol",
                "base_interval",
                "one_hour_interval",
                "four_hour_interval",
                "period_start_utc",
                "period_end_utc",
                "snapshot_count",
                "reference_hash",
            },
            name="13D reference",
        )
        try:
            return cls(
                analysis_name=mapping["analysis_name"],
                analysis_version=mapping["analysis_version"],
                strategy_hypothesis_version=mapping["strategy_hypothesis_version"],
                strategy_config_hash=mapping["strategy_config_hash"],
                strategy_factory_hash=mapping["strategy_factory_hash"],
                strategy_report_hash=mapping["strategy_report_hash"],
                evaluation_protocol_hash=mapping["evaluation_protocol_hash"],
                evaluation_hash=mapping["evaluation_hash"],
                replay_hash=mapping["replay_hash"],
                bundle_hash=mapping["bundle_hash"],
                source_hash=mapping["source_hash"],
                analysis_protocol_hash=mapping["analysis_protocol_hash"],
                analysis_hash=mapping["analysis_hash"],
                symbol=mapping["symbol"],
                base_interval=mapping["base_interval"],
                one_hour_interval=mapping["one_hour_interval"],
                four_hour_interval=mapping["four_hour_interval"],
                period_start_utc=mapping["period_start_utc"],
                period_end_utc=mapping["period_end_utc"],
                snapshot_count=mapping["snapshot_count"],
                reference_hash=mapping.get("reference_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketContractValidationError("13D reference is incomplete.") from exc




@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketFundingMethod:
    funding_method_name: str = HISTORICAL_FUTURES_MARKET_FUNDING_METHOD_NAME
    funding_method_version: str = HISTORICAL_FUTURES_MARKET_FUNDING_METHOD_VERSION
    funding_method_reference: str = HISTORICAL_FUTURES_MARKET_FUNDING_METHOD_REFERENCE
    funding_method_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "funding_method_name", _require_str(self.funding_method_name, "funding_method_name"))
        object.__setattr__(self, "funding_method_version", _require_str(self.funding_method_version, "funding_method_version"))
        object.__setattr__(self, "funding_method_reference", _require_https_reference(self.funding_method_reference, "funding_method_reference"))
        if self.funding_method_name != HISTORICAL_FUTURES_MARKET_FUNDING_METHOD_NAME:
            raise HistoricalFuturesMarketContractValidationError("funding_method_name diverges from the trusted Binance USD?-M funding reference.")
        if self.funding_method_version != HISTORICAL_FUTURES_MARKET_FUNDING_METHOD_VERSION:
            raise HistoricalFuturesMarketContractValidationError("funding_method_version diverges from the trusted Binance USD?-M funding reference.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.funding_method_hash:
            if self.funding_method_hash != expected:
                raise HistoricalFuturesMarketContractValidationError("funding method hash mismatch.")
        else:
            object.__setattr__(self, "funding_method_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "funding_method_name": self.funding_method_name,
            "funding_method_version": self.funding_method_version,
            "funding_method_reference": self.funding_method_reference,
        }
        if include_hash:
            payload["funding_method_hash"] = self.funding_method_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketFundingMethod":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketContractValidationError("funding method must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={"funding_method_name", "funding_method_version", "funding_method_reference", "funding_method_hash"},
            name="funding method",
        )
        try:
            return cls(
                funding_method_name=mapping["funding_method_name"],
                funding_method_version=mapping["funding_method_version"],
                funding_method_reference=mapping["funding_method_reference"],
                funding_method_hash=mapping.get("funding_method_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketContractValidationError("funding method is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketCostScenario:
    scenario_name: str = HISTORICAL_FUTURES_MARKET_COST_SCENARIO_BASE
    entry_fee_rate: Decimal = Decimal("0")
    entry_fee_unit: str = HISTORICAL_FUTURES_MARKET_COST_ENTRY_EXIT_UNIT
    exit_fee_rate: Decimal = Decimal("0")
    exit_fee_unit: str = HISTORICAL_FUTURES_MARKET_COST_ENTRY_EXIT_UNIT
    spread: Decimal = Decimal("0")
    spread_unit: str = HISTORICAL_FUTURES_MARKET_COST_SPREAD_SLIPPAGE_UNIT
    slippage: Decimal = Decimal("0")
    slippage_unit: str = HISTORICAL_FUTURES_MARKET_COST_SPREAD_SLIPPAGE_UNIT
    funding: Decimal = Decimal("0")
    funding_unit: str = HISTORICAL_FUTURES_MARKET_COST_FUNDING_UNIT
    settlement_currency: str = HISTORICAL_FUTURES_MARKET_SETTLEMENT_CURRENCY
    rounding_rule: str = HISTORICAL_FUTURES_MARKET_COST_ROUNDING_RULE
    premise_methodology: str = HISTORICAL_FUTURES_MARKET_COST_PREMISE_METHOD
    premise_methodology_version: str = HISTORICAL_FUTURES_MARKET_COST_PREMISE_VERSION
    funding_required: bool = False
    scenario_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario_name", _require_str(self.scenario_name, "scenario_name"))
        object.__setattr__(self, "entry_fee_rate", _require_decimal(self.entry_fee_rate, "entry_fee_rate"))
        object.__setattr__(self, "entry_fee_unit", _require_unit(self.entry_fee_unit, "entry_fee_unit", expected=HISTORICAL_FUTURES_MARKET_COST_ENTRY_EXIT_UNIT))
        object.__setattr__(self, "exit_fee_rate", _require_decimal(self.exit_fee_rate, "exit_fee_rate"))
        object.__setattr__(self, "exit_fee_unit", _require_unit(self.exit_fee_unit, "exit_fee_unit", expected=HISTORICAL_FUTURES_MARKET_COST_ENTRY_EXIT_UNIT))
        object.__setattr__(self, "spread", _require_decimal(self.spread, "spread"))
        object.__setattr__(self, "spread_unit", _require_unit(self.spread_unit, "spread_unit", expected=HISTORICAL_FUTURES_MARKET_COST_SPREAD_SLIPPAGE_UNIT))
        object.__setattr__(self, "slippage", _require_decimal(self.slippage, "slippage"))
        object.__setattr__(self, "slippage_unit", _require_unit(self.slippage_unit, "slippage_unit", expected=HISTORICAL_FUTURES_MARKET_COST_SPREAD_SLIPPAGE_UNIT))
        object.__setattr__(self, "funding", _require_decimal(self.funding, "funding"))
        object.__setattr__(self, "funding_unit", _require_unit(self.funding_unit, "funding_unit", expected=HISTORICAL_FUTURES_MARKET_COST_FUNDING_UNIT))
        object.__setattr__(self, "settlement_currency", _require_str(self.settlement_currency, "settlement_currency").upper())
        object.__setattr__(self, "rounding_rule", _require_str(self.rounding_rule, "rounding_rule"))
        object.__setattr__(self, "premise_methodology", _require_str(self.premise_methodology, "premise_methodology"))
        object.__setattr__(self, "premise_methodology_version", _require_str(self.premise_methodology_version, "premise_methodology_version"))
        object.__setattr__(self, "funding_required", _require_bool(self.funding_required, "funding_required"))
        if self.scenario_name not in {HISTORICAL_FUTURES_MARKET_COST_SCENARIO_BASE, HISTORICAL_FUTURES_MARKET_COST_SCENARIO_PESSIMISTIC}:
            raise HistoricalFuturesMarketContractValidationError("scenario_name must be base or pessimistic.")
        if self.settlement_currency != HISTORICAL_FUTURES_MARKET_SETTLEMENT_CURRENCY:
            raise HistoricalFuturesMarketContractValidationError("settlement_currency must remain USDT for USD?-M Futures.")
        if self.rounding_rule != HISTORICAL_FUTURES_MARKET_COST_ROUNDING_RULE:
            raise HistoricalFuturesMarketContractValidationError("rounding_rule diverges from the trusted cost premise.")
        if self.premise_methodology != HISTORICAL_FUTURES_MARKET_COST_PREMISE_METHOD:
            raise HistoricalFuturesMarketContractValidationError("premise_methodology diverges from the trusted cost premise.")
        if self.premise_methodology_version != HISTORICAL_FUTURES_MARKET_COST_PREMISE_VERSION:
            raise HistoricalFuturesMarketContractValidationError("premise_methodology_version diverges from the trusted cost premise.")
        if not self.funding_required and self.funding != 0:
            raise HistoricalFuturesMarketContractValidationError("funding must be zero when funding is not required.")
        if self.funding_required and self.funding <= 0:
            raise HistoricalFuturesMarketContractValidationError("funding must be greater than zero when funding is required.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.scenario_hash:
            if self.scenario_hash != expected:
                raise HistoricalFuturesMarketContractValidationError("cost scenario hash mismatch.")
        else:
            object.__setattr__(self, "scenario_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "scenario_name": self.scenario_name,
            "entry_fee_rate": self.entry_fee_rate,
            "entry_fee_unit": self.entry_fee_unit,
            "exit_fee_rate": self.exit_fee_rate,
            "exit_fee_unit": self.exit_fee_unit,
            "spread": self.spread,
            "spread_unit": self.spread_unit,
            "slippage": self.slippage,
            "slippage_unit": self.slippage_unit,
            "funding": self.funding,
            "funding_unit": self.funding_unit,
            "settlement_currency": self.settlement_currency,
            "rounding_rule": self.rounding_rule,
            "premise_methodology": self.premise_methodology,
            "premise_methodology_version": self.premise_methodology_version,
            "funding_required": self.funding_required,
        }
        if include_hash:
            payload["scenario_hash"] = self.scenario_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketCostScenario":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketContractValidationError("cost scenario must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "scenario_name",
                "entry_fee_rate",
                "entry_fee_unit",
                "exit_fee_rate",
                "exit_fee_unit",
                "spread",
                "spread_unit",
                "slippage",
                "slippage_unit",
                "funding",
                "funding_unit",
                "settlement_currency",
                "rounding_rule",
                "premise_methodology",
                "premise_methodology_version",
                "funding_required",
                "scenario_hash",
            },
            name="cost scenario",
        )
        try:
            return cls(
                scenario_name=mapping["scenario_name"],
                entry_fee_rate=mapping["entry_fee_rate"],
                entry_fee_unit=mapping["entry_fee_unit"],
                exit_fee_rate=mapping["exit_fee_rate"],
                exit_fee_unit=mapping["exit_fee_unit"],
                spread=mapping["spread"],
                spread_unit=mapping["spread_unit"],
                slippage=mapping["slippage"],
                slippage_unit=mapping["slippage_unit"],
                funding=mapping["funding"],
                funding_unit=mapping["funding_unit"],
                settlement_currency=mapping["settlement_currency"],
                rounding_rule=mapping["rounding_rule"],
                premise_methodology=mapping["premise_methodology"],
                premise_methodology_version=mapping["premise_methodology_version"],
                funding_required=mapping["funding_required"],
                scenario_hash=mapping.get("scenario_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketContractValidationError("cost scenario is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketCostProtocol:
    schema_version: int = HISTORICAL_FUTURES_MARKET_COST_PROTOCOL_SCHEMA_VERSION
    funding_method: HistoricalFuturesMarketFundingMethod = field(default_factory=HistoricalFuturesMarketFundingMethod)
    base: HistoricalFuturesMarketCostScenario = field(default_factory=HistoricalFuturesMarketCostScenario)
    pessimistic: HistoricalFuturesMarketCostScenario = field(
        default_factory=lambda: HistoricalFuturesMarketCostScenario(
            scenario_name=HISTORICAL_FUTURES_MARKET_COST_SCENARIO_PESSIMISTIC,
            entry_fee_rate=Decimal("0.0005"),
            exit_fee_rate=Decimal("0.0005"),
            spread=Decimal("10"),
            slippage=Decimal("10"),
        )
    )
    protocol_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.funding_method, HistoricalFuturesMarketFundingMethod):
            raise HistoricalFuturesMarketContractValidationError("funding_method must be a HistoricalFuturesMarketFundingMethod instance.")
        if not isinstance(self.base, HistoricalFuturesMarketCostScenario):
            raise HistoricalFuturesMarketContractValidationError("base must be a HistoricalFuturesMarketCostScenario instance.")
        if not isinstance(self.pessimistic, HistoricalFuturesMarketCostScenario):
            raise HistoricalFuturesMarketContractValidationError("pessimistic must be a HistoricalFuturesMarketCostScenario instance.")
        if self.schema_version != HISTORICAL_FUTURES_MARKET_COST_PROTOCOL_SCHEMA_VERSION:
            raise HistoricalFuturesMarketContractValidationError("schema_version must be 1.")
        if self.base.scenario_name != HISTORICAL_FUTURES_MARKET_COST_SCENARIO_BASE:
            raise HistoricalFuturesMarketContractValidationError("base scenario must keep the base name.")
        if self.pessimistic.scenario_name != HISTORICAL_FUTURES_MARKET_COST_SCENARIO_PESSIMISTIC:
            raise HistoricalFuturesMarketContractValidationError("pessimistic scenario must keep the pessimistic name.")
        if self.base.settlement_currency != HISTORICAL_FUTURES_MARKET_SETTLEMENT_CURRENCY:
            raise HistoricalFuturesMarketContractValidationError("base settlement_currency must remain USDT.")
        if self.pessimistic.settlement_currency != HISTORICAL_FUTURES_MARKET_SETTLEMENT_CURRENCY:
            raise HistoricalFuturesMarketContractValidationError("pessimistic settlement_currency must remain USDT.")
        if self.base.premise_methodology != self.pessimistic.premise_methodology:
            raise HistoricalFuturesMarketContractValidationError("pessimistic premise methodology must match the base scenario.")
        if self.base.premise_methodology_version != self.pessimistic.premise_methodology_version:
            raise HistoricalFuturesMarketContractValidationError("pessimistic premise version must match the base scenario.")
        if self.pessimistic.entry_fee_rate < self.base.entry_fee_rate:
            raise HistoricalFuturesMarketContractValidationError("pessimistic entry_fee_rate cannot be more favorable than base.")
        if self.pessimistic.exit_fee_rate < self.base.exit_fee_rate:
            raise HistoricalFuturesMarketContractValidationError("pessimistic exit_fee_rate cannot be more favorable than base.")
        if self.pessimistic.spread < self.base.spread:
            raise HistoricalFuturesMarketContractValidationError("pessimistic spread cannot be more favorable than base.")
        if self.pessimistic.slippage < self.base.slippage:
            raise HistoricalFuturesMarketContractValidationError("pessimistic slippage cannot be more favorable than base.")
        if self.pessimistic.funding < self.base.funding:
            raise HistoricalFuturesMarketContractValidationError("pessimistic funding cannot be more favorable than base.")
        if self.base.funding_required and not self.pessimistic.funding_required:
            raise HistoricalFuturesMarketContractValidationError("pessimistic funding_required cannot be false when base funding is required.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.protocol_hash:
            if self.protocol_hash != expected:
                raise HistoricalFuturesMarketContractValidationError("cost protocol hash mismatch.")
        else:
            object.__setattr__(self, "protocol_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "funding_method": self.funding_method.as_dict(),
            "base": self.base.as_dict(),
            "pessimistic": self.pessimistic.as_dict(),
        }
        if include_hash:
            payload["protocol_hash"] = self.protocol_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketCostProtocol":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketContractValidationError("cost protocol must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={"schema_version", "funding_method", "base", "pessimistic", "protocol_hash"},
            name="cost protocol",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                funding_method=HistoricalFuturesMarketFundingMethod.from_dict(mapping["funding_method"]),
                base=HistoricalFuturesMarketCostScenario.from_dict(mapping["base"]),
                pessimistic=HistoricalFuturesMarketCostScenario.from_dict(mapping["pessimistic"]),
                protocol_hash=mapping.get("protocol_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketContractValidationError("cost protocol is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketExecutionPolicy:
    schema_version: int = HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_SCHEMA_VERSION
    policy_name: str = HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_NAME
    policy_version: str = HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_VERSION
    compatible_timeframes: tuple[str, ...] = HISTORICAL_FUTURES_MARKET_TIMEFRAMES
    hypothesis_13b_reference_hash: str = ""
    evaluation_13c_reference_hash: str = ""
    analysis_13d_reference_hash: str = ""
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    event_precedence: tuple[str, ...] = HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_EVENT_PRECEDENCE
    policy_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_name", _require_str(self.policy_name, "policy_name"))
        object.__setattr__(self, "policy_version", _require_str(self.policy_version, "policy_version"))
        if not isinstance(self.compatible_timeframes, tuple):
            object.__setattr__(self, "compatible_timeframes", tuple(self.compatible_timeframes))
        object.__setattr__(self, "compatible_timeframes", tuple(_require_str(item, "compatible_timeframe") for item in self.compatible_timeframes))
        object.__setattr__(self, "hypothesis_13b_reference_hash", _require_hash(self.hypothesis_13b_reference_hash, "hypothesis_13b_reference_hash"))
        object.__setattr__(self, "evaluation_13c_reference_hash", _require_hash(self.evaluation_13c_reference_hash, "evaluation_13c_reference_hash"))
        object.__setattr__(self, "analysis_13d_reference_hash", _require_hash(self.analysis_13d_reference_hash, "analysis_13d_reference_hash"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_SCHEMA_VERSION:
            raise HistoricalFuturesMarketContractValidationError("execution policy schema_version must be 1.")
        if self.policy_name != HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_NAME:
            raise HistoricalFuturesMarketContractValidationError("execution policy name diverges from the trusted contract.")
        if self.policy_version != HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_VERSION:
            raise HistoricalFuturesMarketContractValidationError("execution policy version diverges from the trusted contract.")
        if self.compatible_timeframes != HISTORICAL_FUTURES_MARKET_TIMEFRAMES:
            raise HistoricalFuturesMarketContractValidationError("execution policy timeframes diverge from the trusted contract.")
        if self.event_precedence != HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_EVENT_PRECEDENCE:
            raise HistoricalFuturesMarketContractValidationError("execution policy event precedence diverges from the trusted contract.")
        _research_only_flags(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.policy_hash:
            if self.policy_hash != expected:
                raise HistoricalFuturesMarketContractValidationError("execution policy hash mismatch.")
        else:
            object.__setattr__(self, "policy_hash", expected)

    def validate_timeline(self, *, timeframe: str, candle_open_utc: Any, candle_close_utc: Any, signal_utc: Any, execution_utc: Any, candle_present: bool = True, candle_valid: bool = True, candle_duplicate: bool = False, candle_in_order: bool = True, future_data_used: bool = False) -> None:
        if _require_str(timeframe, "timeframe") not in self.compatible_timeframes:
            raise HistoricalFuturesMarketContractValidationError("timeframe is incompatible with the frozen execution policy.")
        _require_utc_datetime(candle_open_utc, "candle_open_utc")
        close_utc = _require_utc_datetime(candle_close_utc, "candle_close_utc")
        signal_utc = _require_utc_datetime(signal_utc, "signal_utc")
        execution_utc = _require_utc_datetime(execution_utc, "execution_utc")
        if not candle_present:
            raise HistoricalFuturesMarketContractValidationError("candle is absent.")
        if not candle_valid:
            raise HistoricalFuturesMarketContractValidationError("candle is invalid.")
        if candle_duplicate:
            raise HistoricalFuturesMarketContractValidationError("candle is duplicated.")
        if not candle_in_order:
            raise HistoricalFuturesMarketContractValidationError("candle is out of order.")
        if future_data_used:
            raise HistoricalFuturesMarketContractValidationError("future data is prohibited.")
        if signal_utc <= close_utc:
            raise HistoricalFuturesMarketContractValidationError("signal must occur strictly after the candle close.")
        if execution_utc <= signal_utc:
            raise HistoricalFuturesMarketContractValidationError("execution must occur strictly after the signal.")

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "compatible_timeframes": list(self.compatible_timeframes),
            "hypothesis_13b_reference_hash": self.hypothesis_13b_reference_hash,
            "evaluation_13c_reference_hash": self.evaluation_13c_reference_hash,
            "analysis_13d_reference_hash": self.analysis_13d_reference_hash,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "event_precedence": list(self.event_precedence),
        }
        if include_hash:
            payload["policy_hash"] = self.policy_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketExecutionPolicy":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketContractValidationError("execution policy must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(mapping, allowed={"schema_version", "policy_name", "policy_version", "compatible_timeframes", "hypothesis_13b_reference_hash", "evaluation_13c_reference_hash", "analysis_13d_reference_hash", "historical_research_only", "operational_evidence", "paper_promotion_eligible", "event_precedence", "policy_hash"}, name="execution policy")
        try:
            return cls(schema_version=mapping["schema_version"], policy_name=mapping["policy_name"], policy_version=mapping["policy_version"], compatible_timeframes=tuple(mapping["compatible_timeframes"]), hypothesis_13b_reference_hash=mapping["hypothesis_13b_reference_hash"], evaluation_13c_reference_hash=mapping["evaluation_13c_reference_hash"], analysis_13d_reference_hash=mapping["analysis_13d_reference_hash"], historical_research_only=mapping.get("historical_research_only", True), operational_evidence=mapping.get("operational_evidence", False), paper_promotion_eligible=mapping.get("paper_promotion_eligible", False), event_precedence=tuple(mapping["event_precedence"]), policy_hash=mapping.get("policy_hash", ""))
        except KeyError as exc:
            raise HistoricalFuturesMarketContractValidationError("execution policy is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketAmbiguousCandlePolicy:
    schema_version: int = HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_SCHEMA_VERSION
    policy_name: str = HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_NAME
    policy_version: str = HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_VERSION
    compatible_timeframes: tuple[str, ...] = HISTORICAL_FUTURES_MARKET_TIMEFRAMES
    hypothesis_13b_reference_hash: str = ""
    evaluation_13c_reference_hash: str = ""
    analysis_13d_reference_hash: str = ""
    allow_intrabar_path_inference: bool = False
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    event_precedence: tuple[str, ...] = HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_EVENT_PRECEDENCE
    policy_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_name", _require_str(self.policy_name, "policy_name"))
        object.__setattr__(self, "policy_version", _require_str(self.policy_version, "policy_version"))
        if not isinstance(self.compatible_timeframes, tuple):
            object.__setattr__(self, "compatible_timeframes", tuple(self.compatible_timeframes))
        object.__setattr__(self, "compatible_timeframes", tuple(_require_str(item, "compatible_timeframe") for item in self.compatible_timeframes))
        object.__setattr__(self, "hypothesis_13b_reference_hash", _require_hash(self.hypothesis_13b_reference_hash, "hypothesis_13b_reference_hash"))
        object.__setattr__(self, "evaluation_13c_reference_hash", _require_hash(self.evaluation_13c_reference_hash, "evaluation_13c_reference_hash"))
        object.__setattr__(self, "analysis_13d_reference_hash", _require_hash(self.analysis_13d_reference_hash, "analysis_13d_reference_hash"))
        object.__setattr__(self, "allow_intrabar_path_inference", _require_bool(self.allow_intrabar_path_inference, "allow_intrabar_path_inference"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_SCHEMA_VERSION:
            raise HistoricalFuturesMarketContractValidationError("ambiguous candle policy schema_version must be 1.")
        if self.policy_name != HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_NAME:
            raise HistoricalFuturesMarketContractValidationError("ambiguous candle policy name diverges from the trusted contract.")
        if self.policy_version != HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_VERSION:
            raise HistoricalFuturesMarketContractValidationError("ambiguous candle policy version diverges from the trusted contract.")
        if self.compatible_timeframes != HISTORICAL_FUTURES_MARKET_TIMEFRAMES:
            raise HistoricalFuturesMarketContractValidationError("ambiguous candle policy timeframes diverge from the trusted contract.")
        if self.allow_intrabar_path_inference is not False:
            raise HistoricalFuturesMarketContractValidationError("intrabar path inference must remain disabled.")
        if self.event_precedence != HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_EVENT_PRECEDENCE:
            raise HistoricalFuturesMarketContractValidationError("ambiguous candle policy event precedence diverges from the trusted contract.")
        _research_only_flags(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.policy_hash:
            if self.policy_hash != expected:
                raise HistoricalFuturesMarketContractValidationError("ambiguous candle policy hash mismatch.")
        else:
            object.__setattr__(self, "policy_hash", expected)

    def validate_ambiguity(self, *, timeframe: str, candle_present: bool = True, candle_valid: bool = True, candle_duplicate: bool = False, candle_in_order: bool = True, future_data_used: bool = False, same_candle_conflict: bool = False, path_resolvable: bool = True) -> None:
        if _require_str(timeframe, "timeframe") not in self.compatible_timeframes:
            raise HistoricalFuturesMarketContractValidationError("timeframe is incompatible with the frozen ambiguous candle policy.")
        if not candle_present:
            raise HistoricalFuturesMarketContractValidationError("candle is absent.")
        if not candle_valid:
            raise HistoricalFuturesMarketContractValidationError("candle is invalid.")
        if candle_duplicate:
            raise HistoricalFuturesMarketContractValidationError("candle is duplicated.")
        if not candle_in_order:
            raise HistoricalFuturesMarketContractValidationError("candle is out of order.")
        if future_data_used:
            raise HistoricalFuturesMarketContractValidationError("future data is prohibited.")
        if same_candle_conflict:
            raise HistoricalFuturesMarketContractValidationError("same-candle conflicts are non-evaluable under the frozen policy.")
        if not path_resolvable:
            raise HistoricalFuturesMarketContractValidationError("intrabar path cannot be inferred under the frozen policy.")

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "compatible_timeframes": list(self.compatible_timeframes),
            "hypothesis_13b_reference_hash": self.hypothesis_13b_reference_hash,
            "evaluation_13c_reference_hash": self.evaluation_13c_reference_hash,
            "analysis_13d_reference_hash": self.analysis_13d_reference_hash,
            "allow_intrabar_path_inference": self.allow_intrabar_path_inference,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "event_precedence": list(self.event_precedence),
        }
        if include_hash:
            payload["policy_hash"] = self.policy_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketAmbiguousCandlePolicy":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketContractValidationError("ambiguous candle policy must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(mapping, allowed={"schema_version", "policy_name", "policy_version", "compatible_timeframes", "hypothesis_13b_reference_hash", "evaluation_13c_reference_hash", "analysis_13d_reference_hash", "allow_intrabar_path_inference", "historical_research_only", "operational_evidence", "paper_promotion_eligible", "event_precedence", "policy_hash"}, name="ambiguous candle policy")
        try:
            return cls(schema_version=mapping["schema_version"], policy_name=mapping["policy_name"], policy_version=mapping["policy_version"], compatible_timeframes=tuple(mapping["compatible_timeframes"]), hypothesis_13b_reference_hash=mapping["hypothesis_13b_reference_hash"], evaluation_13c_reference_hash=mapping["evaluation_13c_reference_hash"], analysis_13d_reference_hash=mapping["analysis_13d_reference_hash"], allow_intrabar_path_inference=mapping["allow_intrabar_path_inference"], historical_research_only=mapping.get("historical_research_only", True), operational_evidence=mapping.get("operational_evidence", False), paper_promotion_eligible=mapping.get("paper_promotion_eligible", False), event_precedence=tuple(mapping["event_precedence"]), policy_hash=mapping.get("policy_hash", ""))
        except KeyError as exc:
            raise HistoricalFuturesMarketContractValidationError("ambiguous candle policy is incomplete.") from exc


def build_historical_futures_market_execution_policy(hypothesis_13b: HistoricalFuturesMarketHypothesisReference13B, evaluation_13c: HistoricalFuturesMarketEvaluationReference13C, analysis_13d: HistoricalFuturesMarketAnalysisReference13D) -> HistoricalFuturesMarketExecutionPolicy:
    return HistoricalFuturesMarketExecutionPolicy(hypothesis_13b_reference_hash=hypothesis_13b.reference_hash, evaluation_13c_reference_hash=evaluation_13c.reference_hash, analysis_13d_reference_hash=analysis_13d.reference_hash)


def build_historical_futures_market_ambiguous_candle_policy(hypothesis_13b: HistoricalFuturesMarketHypothesisReference13B, evaluation_13c: HistoricalFuturesMarketEvaluationReference13C, analysis_13d: HistoricalFuturesMarketAnalysisReference13D) -> HistoricalFuturesMarketAmbiguousCandlePolicy:
    return HistoricalFuturesMarketAmbiguousCandlePolicy(hypothesis_13b_reference_hash=hypothesis_13b.reference_hash, evaluation_13c_reference_hash=evaluation_13c.reference_hash, analysis_13d_reference_hash=analysis_13d.reference_hash)

@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketContract:
    identity: HistoricalFuturesMarketIdentity
    hypothesis_13b: HistoricalFuturesMarketHypothesisReference13B
    evaluation_13c: HistoricalFuturesMarketEvaluationReference13C
    analysis_13d: HistoricalFuturesMarketAnalysisReference13D
    cost_protocol: HistoricalFuturesMarketCostProtocol | None = None
    execution_policy: HistoricalFuturesMarketExecutionPolicy | None = None
    ambiguous_candle_policy: HistoricalFuturesMarketAmbiguousCandlePolicy | None = None
    temporal_split_protocol: HistoricalFuturesMarketTemporalSplitProtocol | None = None
    schema_version: int = HISTORICAL_FUTURES_MARKET_CONTRACT_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    contract_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.identity, HistoricalFuturesMarketIdentity):
            raise HistoricalFuturesMarketContractValidationError("identity must be a HistoricalFuturesMarketIdentity instance.")
        if not isinstance(self.hypothesis_13b, HistoricalFuturesMarketHypothesisReference13B):
            raise HistoricalFuturesMarketContractValidationError("hypothesis_13b must be a 13B reference.")
        if not isinstance(self.evaluation_13c, HistoricalFuturesMarketEvaluationReference13C):
            raise HistoricalFuturesMarketContractValidationError("evaluation_13c must be a 13C reference.")
        if not isinstance(self.analysis_13d, HistoricalFuturesMarketAnalysisReference13D):
            raise HistoricalFuturesMarketContractValidationError("analysis_13d must be a 13D reference.")
        if self.cost_protocol is not None and not isinstance(self.cost_protocol, HistoricalFuturesMarketCostProtocol):
            raise HistoricalFuturesMarketContractValidationError("cost_protocol must be a HistoricalFuturesMarketCostProtocol instance.")
        if self.execution_policy is None:
            object.__setattr__(self, "execution_policy", build_historical_futures_market_execution_policy(self.hypothesis_13b, self.evaluation_13c, self.analysis_13d))
        if self.ambiguous_candle_policy is None:
            object.__setattr__(self, "ambiguous_candle_policy", build_historical_futures_market_ambiguous_candle_policy(self.hypothesis_13b, self.evaluation_13c, self.analysis_13d))
        if self.temporal_split_protocol is None:
            object.__setattr__(self, "temporal_split_protocol", build_historical_futures_market_temporal_split_protocol(self.hypothesis_13b, self.evaluation_13c, self.analysis_13d))
        if not isinstance(self.execution_policy, HistoricalFuturesMarketExecutionPolicy):
            raise HistoricalFuturesMarketContractValidationError("execution_policy must be a HistoricalFuturesMarketExecutionPolicy instance.")
        if not isinstance(self.ambiguous_candle_policy, HistoricalFuturesMarketAmbiguousCandlePolicy):
            raise HistoricalFuturesMarketContractValidationError("ambiguous_candle_policy must be a HistoricalFuturesMarketAmbiguousCandlePolicy instance.")
        if not isinstance(self.temporal_split_protocol, HistoricalFuturesMarketTemporalSplitProtocol):
            raise HistoricalFuturesMarketContractValidationError("temporal_split_protocol must be a HistoricalFuturesMarketTemporalSplitProtocol instance.")
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_CONTRACT_SCHEMA_VERSION:
            raise HistoricalFuturesMarketContractValidationError("schema_version must be 1.")
        if self.identity.symbol != self.hypothesis_13b.symbol:
            raise HistoricalFuturesMarketContractValidationError("identity symbol diverges from the 13B hypothesis reference.")
        _require_supported_symbol_and_timeframes(
            self.identity.symbol,
            (self.identity.timeframes[0], self.identity.timeframes[1], self.identity.timeframes[2]),
        )
        if self.identity.timeframes != HISTORICAL_FUTURES_MARKET_TIMEFRAMES:
            raise HistoricalFuturesMarketContractValidationError("identity timeframes diverge from the trusted contract.")
        if self.hypothesis_13b.strategy_report_hash != self.evaluation_13c.strategy_report_hash:
            raise HistoricalFuturesMarketContractValidationError("13C strategy_report_hash diverges from the 13B hypothesis reference.")
        if self.hypothesis_13b.strategy_config_hash != self.evaluation_13c.strategy_config_hash:
            raise HistoricalFuturesMarketContractValidationError("13C strategy_config_hash diverges from the 13B hypothesis reference.")
        if self.hypothesis_13b.strategy_factory_hash != self.evaluation_13c.strategy_factory_hash:
            raise HistoricalFuturesMarketContractValidationError("13C strategy_factory_hash diverges from the 13B hypothesis reference.")
        if self.evaluation_13c.strategy_hypothesis_version != self.hypothesis_13b.hypothesis_version:
            raise HistoricalFuturesMarketContractValidationError("13C strategy_hypothesis_version diverges from the 13B hypothesis reference.")
        if self.evaluation_13c.evaluation_protocol_hash != self.analysis_13d.evaluation_protocol_hash:
            raise HistoricalFuturesMarketContractValidationError("13D evaluation_protocol_hash diverges from the 13C evaluation reference.")
        if self.hypothesis_13b.strategy_report_hash != self.analysis_13d.strategy_report_hash:
            raise HistoricalFuturesMarketContractValidationError("13D strategy_report_hash diverges from the 13B hypothesis reference.")
        if self.hypothesis_13b.strategy_config_hash != self.analysis_13d.strategy_config_hash:
            raise HistoricalFuturesMarketContractValidationError("13D strategy_config_hash diverges from the 13B hypothesis reference.")
        if self.hypothesis_13b.strategy_factory_hash != self.analysis_13d.strategy_factory_hash:
            raise HistoricalFuturesMarketContractValidationError("13D strategy_factory_hash diverges from the 13B hypothesis reference.")
        if self.analysis_13d.strategy_hypothesis_version != self.hypothesis_13b.hypothesis_version:
            raise HistoricalFuturesMarketContractValidationError("13D strategy_hypothesis_version diverges from the 13B hypothesis reference.")
        if self.evaluation_13c.evaluation_hash != self.analysis_13d.evaluation_hash:
            raise HistoricalFuturesMarketContractValidationError("13D evaluation_hash diverges from the 13C evaluation reference.")
        if self.analysis_13d.symbol != self.identity.symbol:
            raise HistoricalFuturesMarketContractValidationError("13D symbol diverges from the market identity.")
        if (self.analysis_13d.base_interval, self.analysis_13d.one_hour_interval, self.analysis_13d.four_hour_interval) != self.identity.timeframes:
            raise HistoricalFuturesMarketContractValidationError("13D timeframes diverge from the market identity.")
        _research_only_flags(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        if self.cost_protocol is not None and self.cost_protocol.base.settlement_currency != self.identity.settlement_asset:
            raise HistoricalFuturesMarketContractValidationError("cost_protocol settlement currency diverges from the market identity.")
        if self.execution_policy.hypothesis_13b_reference_hash != self.hypothesis_13b.reference_hash:
            raise HistoricalFuturesMarketContractValidationError("execution policy 13B reference hash diverges from the market contract.")
        if self.execution_policy.evaluation_13c_reference_hash != self.evaluation_13c.reference_hash:
            raise HistoricalFuturesMarketContractValidationError("execution policy 13C reference hash diverges from the market contract.")
        if self.execution_policy.analysis_13d_reference_hash != self.analysis_13d.reference_hash:
            raise HistoricalFuturesMarketContractValidationError("execution policy 13D reference hash diverges from the market contract.")
        if self.execution_policy.compatible_timeframes != self.identity.timeframes:
            raise HistoricalFuturesMarketContractValidationError("execution policy timeframes diverge from the market identity.")
        if self.ambiguous_candle_policy.hypothesis_13b_reference_hash != self.hypothesis_13b.reference_hash:
            raise HistoricalFuturesMarketContractValidationError("ambiguous candle policy 13B reference hash diverges from the market contract.")
        if self.ambiguous_candle_policy.evaluation_13c_reference_hash != self.evaluation_13c.reference_hash:
            raise HistoricalFuturesMarketContractValidationError("ambiguous candle policy 13C reference hash diverges from the market contract.")
        if self.ambiguous_candle_policy.analysis_13d_reference_hash != self.analysis_13d.reference_hash:
            raise HistoricalFuturesMarketContractValidationError("ambiguous candle policy 13D reference hash diverges from the market contract.")
        if self.ambiguous_candle_policy.compatible_timeframes != self.identity.timeframes:
            raise HistoricalFuturesMarketContractValidationError("ambiguous candle policy timeframes diverge from the market identity.")
        if self.temporal_split_protocol.hypothesis_13b_reference_hash != self.hypothesis_13b.reference_hash:
            raise HistoricalFuturesMarketContractValidationError("temporal split protocol 13B reference hash diverges from the market contract.")
        if self.temporal_split_protocol.evaluation_13c_reference_hash != self.evaluation_13c.reference_hash:
            raise HistoricalFuturesMarketContractValidationError("temporal split protocol 13C reference hash diverges from the market contract.")
        if self.temporal_split_protocol.analysis_13d_reference_hash != self.analysis_13d.reference_hash:
            raise HistoricalFuturesMarketContractValidationError("temporal split protocol 13D reference hash diverges from the market contract.")
        if self.temporal_split_protocol.provenance_hash != self.analysis_13d.source_hash:
            raise HistoricalFuturesMarketContractValidationError("temporal split protocol provenance diverges from the 13D source hash.")
        if self.temporal_split_protocol.coverage_start_utc != self.analysis_13d.period_start_utc:
            raise HistoricalFuturesMarketContractValidationError("temporal split coverage_start_utc diverges from the 13D coverage.")
        if self.temporal_split_protocol.coverage_end_utc != self.analysis_13d.period_end_utc:
            raise HistoricalFuturesMarketContractValidationError("temporal split coverage_end_utc diverges from the 13D coverage.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.contract_hash:
            if self.contract_hash != expected:
                raise HistoricalFuturesMarketContractValidationError("contract hash mismatch.")
        else:
            object.__setattr__(self, "contract_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "identity": self.identity.as_dict(),
            "hypothesis_13b": self.hypothesis_13b.as_dict(),
            "evaluation_13c": self.evaluation_13c.as_dict(),
            "analysis_13d": self.analysis_13d.as_dict(),
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "cost_protocol": self.cost_protocol.as_dict() if self.cost_protocol is not None else None,
            "execution_policy": self.execution_policy.as_dict(),
            "ambiguous_candle_policy": self.ambiguous_candle_policy.as_dict(),
            "temporal_split_protocol": self.temporal_split_protocol.as_dict(),
        }
        if include_hash:
            payload["contract_hash"] = self.contract_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketContract":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketContractValidationError("market contract must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "identity",
                "hypothesis_13b",
                "evaluation_13c",
                "analysis_13d",
                "cost_protocol",
                "execution_policy",
                "ambiguous_candle_policy",
                "temporal_split_protocol",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "contract_hash",
            },
            name="market contract",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                identity=HistoricalFuturesMarketIdentity.from_dict(mapping["identity"]),
                hypothesis_13b=HistoricalFuturesMarketHypothesisReference13B.from_dict(mapping["hypothesis_13b"]),
                evaluation_13c=HistoricalFuturesMarketEvaluationReference13C.from_dict(mapping["evaluation_13c"]),
                analysis_13d=HistoricalFuturesMarketAnalysisReference13D.from_dict(mapping["analysis_13d"]),
                cost_protocol=HistoricalFuturesMarketCostProtocol.from_dict(mapping["cost_protocol"]) if mapping.get("cost_protocol") is not None else None,
                execution_policy=HistoricalFuturesMarketExecutionPolicy.from_dict(mapping["execution_policy"]) if mapping.get("execution_policy") is not None else None,
                ambiguous_candle_policy=HistoricalFuturesMarketAmbiguousCandlePolicy.from_dict(mapping["ambiguous_candle_policy"]) if mapping.get("ambiguous_candle_policy") is not None else None,
                temporal_split_protocol=HistoricalFuturesMarketTemporalSplitProtocol.from_dict(mapping["temporal_split_protocol"]) if mapping.get("temporal_split_protocol") is not None else None,
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                contract_hash=mapping.get("contract_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketContractValidationError("market contract is incomplete.") from exc
        except (
            HistoricalFuturesMarketContractValidationError,
            HistoricalMultiTimeframeFirstStrategyValidationError,
            HistoricalMultiTimeframeFirstStrategyEvaluationValidationError,
            HistoricalMultiTimeframeStrategyAnalysisValidationError,
        ) as exc:
            raise HistoricalFuturesMarketContractIntegrityError(str(exc)) from exc




def build_historical_futures_market_cost_protocol() -> HistoricalFuturesMarketCostProtocol:
    return HistoricalFuturesMarketCostProtocol()
def build_historical_futures_market_contract(
    strategy_report: HistoricalMultiTimeframeFirstStrategyReport,
    evaluation_report: HistoricalMultiTimeframeFirstStrategyEvaluationReport,
    analysis_report: HistoricalMultiTimeframeStrategyAnalysisReport,
    *,
    cost_protocol: HistoricalFuturesMarketCostProtocol | None = None,
    execution_policy: HistoricalFuturesMarketExecutionPolicy | None = None,
    ambiguous_candle_policy: HistoricalFuturesMarketAmbiguousCandlePolicy | None = None,
    temporal_split_protocol: HistoricalFuturesMarketTemporalSplitProtocol | None = None,
) -> HistoricalFuturesMarketContract:
    if not isinstance(strategy_report, HistoricalMultiTimeframeFirstStrategyReport):
        raise HistoricalFuturesMarketContractValidationError("strategy_report must be a HistoricalMultiTimeframeFirstStrategyReport instance.")
    if not isinstance(evaluation_report, HistoricalMultiTimeframeFirstStrategyEvaluationReport):
        raise HistoricalFuturesMarketContractValidationError("evaluation_report must be a HistoricalMultiTimeframeFirstStrategyEvaluationReport instance.")
    if not isinstance(analysis_report, HistoricalMultiTimeframeStrategyAnalysisReport):
        raise HistoricalFuturesMarketContractValidationError("analysis_report must be a HistoricalMultiTimeframeStrategyAnalysisReport instance.")

    hypothesis_13b = HistoricalFuturesMarketHypothesisReference13B.from_strategy_report(strategy_report)
    evaluation_13c = HistoricalFuturesMarketEvaluationReference13C.from_evaluation_report(evaluation_report)
    analysis_13d = HistoricalFuturesMarketAnalysisReference13D.from_analysis_report(analysis_report)
    identity = HistoricalFuturesMarketIdentity(
        symbol=hypothesis_13b.symbol,
        base_asset=_split_btcusdt_symbol(hypothesis_13b.symbol)[0],
        margin_asset=_split_btcusdt_symbol(hypothesis_13b.symbol)[1],
        settlement_asset=_split_btcusdt_symbol(hypothesis_13b.symbol)[2],
        timeframes=(hypothesis_13b.base_interval, hypothesis_13b.one_hour_interval, hypothesis_13b.four_hour_interval),
    )
    if execution_policy is None:
        execution_policy = build_historical_futures_market_execution_policy(hypothesis_13b, evaluation_13c, analysis_13d)
    if ambiguous_candle_policy is None:
        ambiguous_candle_policy = build_historical_futures_market_ambiguous_candle_policy(hypothesis_13b, evaluation_13c, analysis_13d)
    if temporal_split_protocol is None:
        temporal_split_protocol = build_historical_futures_market_temporal_split_protocol(hypothesis_13b, evaluation_13c, analysis_13d)
    return HistoricalFuturesMarketContract(
        identity=identity,
        hypothesis_13b=hypothesis_13b,
        evaluation_13c=evaluation_13c,
        analysis_13d=analysis_13d,
        cost_protocol=cost_protocol,
        execution_policy=execution_policy,
        ambiguous_candle_policy=ambiguous_candle_policy,
        temporal_split_protocol=temporal_split_protocol,
    )


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketTemporalWindow:
    window_name: str
    start_utc: datetime
    end_utc: datetime
    definition_methodology: str = HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_METHOD
    definition_version: str = "v1"
    provenance_hash: str = ""
    compatible_timeframes: tuple[str, ...] = HISTORICAL_FUTURES_MARKET_TIMEFRAMES
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    window_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_name", _require_str(self.window_name, "window_name").lower())
        object.__setattr__(self, "start_utc", _require_future_bound_utc(self.start_utc, "start_utc"))
        object.__setattr__(self, "end_utc", _require_future_bound_utc(self.end_utc, "end_utc"))
        object.__setattr__(self, "definition_methodology", _require_str(self.definition_methodology, "definition_methodology"))
        object.__setattr__(self, "definition_version", _require_str(self.definition_version, "definition_version"))
        object.__setattr__(self, "provenance_hash", _require_hash(self.provenance_hash, "provenance_hash"))
        if not isinstance(self.compatible_timeframes, tuple):
            object.__setattr__(self, "compatible_timeframes", tuple(self.compatible_timeframes))
        object.__setattr__(self, "compatible_timeframes", tuple(_require_str(item, "compatible_timeframe") for item in self.compatible_timeframes))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.window_name not in {HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE, HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION, HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST}:
            raise HistoricalFuturesMarketContractValidationError("window_name must be reference, validation, or test.")
        if self.definition_methodology != HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_METHOD:
            raise HistoricalFuturesMarketContractValidationError("window definition methodology diverges from the trusted contract.")
        if self.definition_version != "v1":
            raise HistoricalFuturesMarketContractValidationError("window definition version diverges from the trusted contract.")
        if self.compatible_timeframes != HISTORICAL_FUTURES_MARKET_TIMEFRAMES:
            raise HistoricalFuturesMarketContractValidationError("window timeframes diverge from the trusted contract.")
        if self.end_utc <= self.start_utc:
            raise HistoricalFuturesMarketContractValidationError("window end must be after window start.")
        _research_only_flags(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.window_hash:
            if self.window_hash != expected:
                raise HistoricalFuturesMarketContractValidationError("temporal window hash mismatch.")
        else:
            object.__setattr__(self, "window_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "window_name": self.window_name,
            "start_utc": _utc_iso(self.start_utc),
            "end_utc": _utc_iso(self.end_utc),
            "definition_methodology": self.definition_methodology,
            "definition_version": self.definition_version,
            "provenance_hash": self.provenance_hash,
            "compatible_timeframes": list(self.compatible_timeframes),
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }
        if include_hash:
            payload["window_hash"] = self.window_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketTemporalWindow":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketContractValidationError("temporal window must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(mapping, allowed={"window_name", "start_utc", "end_utc", "definition_methodology", "definition_version", "provenance_hash", "compatible_timeframes", "historical_research_only", "operational_evidence", "paper_promotion_eligible", "window_hash"}, name="temporal window")
        try:
            return cls(window_name=mapping["window_name"], start_utc=mapping["start_utc"], end_utc=mapping["end_utc"], definition_methodology=mapping.get("definition_methodology", HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_METHOD), definition_version=mapping.get("definition_version", "v1"), provenance_hash=mapping["provenance_hash"], compatible_timeframes=tuple(mapping.get("compatible_timeframes", HISTORICAL_FUTURES_MARKET_TIMEFRAMES)), historical_research_only=mapping.get("historical_research_only", True), operational_evidence=mapping.get("operational_evidence", False), paper_promotion_eligible=mapping.get("paper_promotion_eligible", False), window_hash=mapping.get("window_hash", ""))
        except KeyError as exc:
            raise HistoricalFuturesMarketContractValidationError("temporal window is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketTemporalSplitProtocol:
    schema_version: int = HISTORICAL_FUTURES_MARKET_TEMPORAL_SPLIT_SCHEMA_VERSION
    protocol_name: str = HISTORICAL_FUTURES_MARKET_TEMPORAL_SPLIT_METHOD
    protocol_version: str = "v1"
    selection_basis: str = HISTORICAL_FUTURES_MARKET_TEMPORAL_SPLIT_METHOD
    coverage_start_utc: datetime = datetime.now(timezone.utc)
    coverage_end_utc: datetime = datetime.now(timezone.utc)
    hypothesis_13b_reference_hash: str = ""
    evaluation_13c_reference_hash: str = ""
    analysis_13d_reference_hash: str = ""
    provenance_hash: str = ""
    reference_window: HistoricalFuturesMarketTemporalWindow = field(default_factory=lambda: HistoricalFuturesMarketTemporalWindow(window_name=HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE, start_utc=datetime.now(timezone.utc), end_utc=datetime.now(timezone.utc), provenance_hash="0" * 64))
    validation_window: HistoricalFuturesMarketTemporalWindow = field(default_factory=lambda: HistoricalFuturesMarketTemporalWindow(window_name=HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION, start_utc=datetime.now(timezone.utc), end_utc=datetime.now(timezone.utc), provenance_hash="0" * 64))
    test_window: HistoricalFuturesMarketTemporalWindow = field(default_factory=lambda: HistoricalFuturesMarketTemporalWindow(window_name=HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST, start_utc=datetime.now(timezone.utc), end_utc=datetime.now(timezone.utc), provenance_hash="0" * 64))
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    protocol_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol_name", _require_str(self.protocol_name, "protocol_name"))
        object.__setattr__(self, "protocol_version", _require_str(self.protocol_version, "protocol_version"))
        object.__setattr__(self, "selection_basis", _require_temporal_selection_basis(self.selection_basis, "selection_basis"))
        object.__setattr__(self, "coverage_start_utc", _require_future_bound_utc(self.coverage_start_utc, "coverage_start_utc"))
        object.__setattr__(self, "coverage_end_utc", _require_future_bound_utc(self.coverage_end_utc, "coverage_end_utc"))
        object.__setattr__(self, "hypothesis_13b_reference_hash", _require_hash(self.hypothesis_13b_reference_hash, "hypothesis_13b_reference_hash"))
        object.__setattr__(self, "evaluation_13c_reference_hash", _require_hash(self.evaluation_13c_reference_hash, "evaluation_13c_reference_hash"))
        object.__setattr__(self, "analysis_13d_reference_hash", _require_hash(self.analysis_13d_reference_hash, "analysis_13d_reference_hash"))
        object.__setattr__(self, "provenance_hash", _require_hash(self.provenance_hash, "provenance_hash"))
        if not isinstance(self.reference_window, HistoricalFuturesMarketTemporalWindow):
            raise HistoricalFuturesMarketContractValidationError("reference_window must be a HistoricalFuturesMarketTemporalWindow instance.")
        if not isinstance(self.validation_window, HistoricalFuturesMarketTemporalWindow):
            raise HistoricalFuturesMarketContractValidationError("validation_window must be a HistoricalFuturesMarketTemporalWindow instance.")
        if not isinstance(self.test_window, HistoricalFuturesMarketTemporalWindow):
            raise HistoricalFuturesMarketContractValidationError("test_window must be a HistoricalFuturesMarketTemporalWindow instance.")
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_TEMPORAL_SPLIT_SCHEMA_VERSION:
            raise HistoricalFuturesMarketContractValidationError("temporal split schema_version must be 1.")
        if self.protocol_name != HISTORICAL_FUTURES_MARKET_TEMPORAL_SPLIT_METHOD:
            raise HistoricalFuturesMarketContractValidationError("temporal split protocol name diverges from the trusted contract.")
        if self.protocol_version != "v1":
            raise HistoricalFuturesMarketContractValidationError("temporal split protocol version diverges from the trusted contract.")
        if self.coverage_end_utc <= self.coverage_start_utc:
            raise HistoricalFuturesMarketContractValidationError("coverage_end_utc must be after coverage_start_utc.")
        if self.reference_window.window_name != HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE:
            raise HistoricalFuturesMarketContractValidationError("reference window must be named reference.")
        if self.validation_window.window_name != HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION:
            raise HistoricalFuturesMarketContractValidationError("validation window must be named validation.")
        if self.test_window.window_name != HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST:
            raise HistoricalFuturesMarketContractValidationError("test window must be named test.")
        if self.reference_window.provenance_hash != self.provenance_hash or self.validation_window.provenance_hash != self.provenance_hash or self.test_window.provenance_hash != self.provenance_hash:
            raise HistoricalFuturesMarketContractValidationError("temporal window provenance diverges from the trusted contract.")
        if self.reference_window.compatible_timeframes != HISTORICAL_FUTURES_MARKET_TIMEFRAMES or self.validation_window.compatible_timeframes != HISTORICAL_FUTURES_MARKET_TIMEFRAMES or self.test_window.compatible_timeframes != HISTORICAL_FUTURES_MARKET_TIMEFRAMES:
            raise HistoricalFuturesMarketContractValidationError("temporal windows diverge from the trusted Futures timeframes.")
        if self.reference_window.end_utc >= self.validation_window.start_utc:
            raise HistoricalFuturesMarketContractValidationError("reference window overlaps validation window.")
        if self.validation_window.end_utc >= self.test_window.start_utc:
            raise HistoricalFuturesMarketContractValidationError("validation window overlaps test window.")
        if not (
            self.coverage_start_utc <= self.reference_window.start_utc < self.reference_window.end_utc <= self.validation_window.start_utc < self.validation_window.end_utc <= self.test_window.start_utc < self.test_window.end_utc <= self.coverage_end_utc
        ):
            raise HistoricalFuturesMarketContractValidationError("temporal windows diverge from the declared coverage.")
        for window in (self.reference_window, self.validation_window, self.test_window):
            if window.start_utc > datetime.now(timezone.utc) or window.end_utc > datetime.now(timezone.utc):
                raise HistoricalFuturesMarketContractValidationError("temporal windows cannot extend into the future.")
        _research_only_flags(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.protocol_hash:
            if self.protocol_hash != expected:
                raise HistoricalFuturesMarketContractValidationError("temporal split protocol hash mismatch.")
        else:
            object.__setattr__(self, "protocol_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "protocol_name": self.protocol_name,
            "protocol_version": self.protocol_version,
            "selection_basis": self.selection_basis,
            "coverage_start_utc": _utc_iso(self.coverage_start_utc),
            "coverage_end_utc": _utc_iso(self.coverage_end_utc),
            "hypothesis_13b_reference_hash": self.hypothesis_13b_reference_hash,
            "evaluation_13c_reference_hash": self.evaluation_13c_reference_hash,
            "analysis_13d_reference_hash": self.analysis_13d_reference_hash,
            "provenance_hash": self.provenance_hash,
            "reference_window": self.reference_window.as_dict(),
            "validation_window": self.validation_window.as_dict(),
            "test_window": self.test_window.as_dict(),
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketTemporalSplitProtocol":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketContractValidationError("temporal split protocol must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(mapping, allowed={"schema_version", "protocol_name", "protocol_version", "selection_basis", "coverage_start_utc", "coverage_end_utc", "hypothesis_13b_reference_hash", "evaluation_13c_reference_hash", "analysis_13d_reference_hash", "provenance_hash", "reference_window", "validation_window", "test_window", "historical_research_only", "operational_evidence", "paper_promotion_eligible", "protocol_hash"}, name="temporal split protocol")
        try:
            return cls(schema_version=mapping["schema_version"], protocol_name=mapping["protocol_name"], protocol_version=mapping["protocol_version"], selection_basis=mapping["selection_basis"], coverage_start_utc=mapping["coverage_start_utc"], coverage_end_utc=mapping["coverage_end_utc"], hypothesis_13b_reference_hash=mapping["hypothesis_13b_reference_hash"], evaluation_13c_reference_hash=mapping["evaluation_13c_reference_hash"], analysis_13d_reference_hash=mapping["analysis_13d_reference_hash"], provenance_hash=mapping["provenance_hash"], reference_window=HistoricalFuturesMarketTemporalWindow.from_dict(mapping["reference_window"]), validation_window=HistoricalFuturesMarketTemporalWindow.from_dict(mapping["validation_window"]), test_window=HistoricalFuturesMarketTemporalWindow.from_dict(mapping["test_window"]), historical_research_only=mapping.get("historical_research_only", True), operational_evidence=mapping.get("operational_evidence", False), paper_promotion_eligible=mapping.get("paper_promotion_eligible", False), protocol_hash=mapping.get("protocol_hash", ""))
        except KeyError as exc:
            raise HistoricalFuturesMarketContractValidationError("temporal split protocol is incomplete.") from exc


def build_historical_futures_market_temporal_split_protocol(hypothesis_13b: HistoricalFuturesMarketHypothesisReference13B, evaluation_13c: HistoricalFuturesMarketEvaluationReference13C, analysis_13d: HistoricalFuturesMarketAnalysisReference13D) -> HistoricalFuturesMarketTemporalSplitProtocol:
    coverage_start = analysis_13d.period_start_utc
    coverage_end = analysis_13d.period_end_utc
    gap = timedelta(microseconds=1)
    usable_span = coverage_end - coverage_start - (gap * 2)
    if usable_span <= timedelta(0):
        raise HistoricalFuturesMarketContractValidationError("analysis coverage is too short for a temporal split.")
    third = usable_span / 3
    reference_end = coverage_start + third
    validation_start = reference_end + gap
    validation_end = validation_start + third
    test_start = validation_end + gap
    return HistoricalFuturesMarketTemporalSplitProtocol(
        coverage_start_utc=coverage_start,
        coverage_end_utc=coverage_end,
        hypothesis_13b_reference_hash=hypothesis_13b.reference_hash,
        evaluation_13c_reference_hash=evaluation_13c.reference_hash,
        analysis_13d_reference_hash=analysis_13d.reference_hash,
        provenance_hash=analysis_13d.source_hash,
        reference_window=HistoricalFuturesMarketTemporalWindow(
            window_name=HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE,
            start_utc=coverage_start,
            end_utc=reference_end,
            provenance_hash=analysis_13d.source_hash,
        ),
        validation_window=HistoricalFuturesMarketTemporalWindow(
            window_name=HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION,
            start_utc=validation_start,
            end_utc=validation_end,
            provenance_hash=analysis_13d.source_hash,
        ),
        test_window=HistoricalFuturesMarketTemporalWindow(
            window_name=HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST,
            start_utc=test_start,
            end_utc=coverage_end,
            provenance_hash=analysis_13d.source_hash,
        ),
    )


__all__ = [
    "HISTORICAL_FUTURES_MARKET_CONTRACT_SCHEMA_VERSION",
    "HISTORICAL_FUTURES_MARKET_CONTRACT_TYPE",
    "HISTORICAL_FUTURES_MARKET_COST_ENTRY_EXIT_UNIT",
    "HISTORICAL_FUTURES_MARKET_COST_FUNDING_UNIT",
    "HISTORICAL_FUTURES_MARKET_COST_PREMISE_METHOD",
    "HISTORICAL_FUTURES_MARKET_COST_PREMISE_VERSION",
    "HISTORICAL_FUTURES_MARKET_COST_PROTOCOL_SCHEMA_VERSION",
    "HISTORICAL_FUTURES_MARKET_COST_ROUNDING_RULE",
    "HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_EVENT_PRECEDENCE",
    "HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_NAME",
    "HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_SCHEMA_VERSION",
    "HISTORICAL_FUTURES_MARKET_EXECUTION_POLICY_VERSION",
    "HISTORICAL_FUTURES_MARKET_TEMPORAL_SPLIT_METHOD",
    "HISTORICAL_FUTURES_MARKET_TEMPORAL_SPLIT_PROHIBITED_CRITERIA",
    "HISTORICAL_FUTURES_MARKET_TEMPORAL_SPLIT_SCHEMA_VERSION",
    "HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_METHOD",
    "HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE",
    "HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST",
    "HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION",
    "HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_EVENT_PRECEDENCE",
    "HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_NAME",
    "HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_RESOLUTION",
    "HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_SCHEMA_VERSION",
    "HISTORICAL_FUTURES_MARKET_AMBIGUOUS_CANDLE_POLICY_VERSION",
    "HISTORICAL_FUTURES_MARKET_COST_SCENARIO_BASE",
    "HISTORICAL_FUTURES_MARKET_COST_SCENARIO_PESSIMISTIC",
    "HISTORICAL_FUTURES_MARKET_COST_SPREAD_SLIPPAGE_UNIT",
    "HISTORICAL_FUTURES_MARKET_EXCHANGE",
    "HISTORICAL_FUTURES_MARKET_FUNDING_METHOD_NAME",
    "HISTORICAL_FUTURES_MARKET_FUNDING_METHOD_REFERENCE",
    "HISTORICAL_FUTURES_MARKET_FUNDING_METHOD_VERSION",
    "HISTORICAL_FUTURES_MARKET_SETTLEMENT_CURRENCY",
    "HISTORICAL_FUTURES_MARKET_TIMEFRAMES",
    "HISTORICAL_FUTURES_MARKET_TYPE",
    "HistoricalFuturesMarketAnalysisReference13D",
    "HistoricalFuturesMarketAmbiguousCandlePolicy",
    "HistoricalFuturesMarketContract",
    "HistoricalFuturesMarketContractError",
    "HistoricalFuturesMarketContractIntegrityError",
    "HistoricalFuturesMarketContractValidationError",
    "HistoricalFuturesMarketCostFundingMethod",
    "HistoricalFuturesMarketCostProtocol",
    "HistoricalFuturesMarketCostScenario",
    "HistoricalFuturesMarketExecutionPolicy",
    "HistoricalFuturesMarketEvaluationReference13C",
    "HistoricalFuturesMarketHypothesisReference13B",
    "HistoricalFuturesMarketIdentity",
    "HistoricalFuturesMarketTemporalSplitProtocol",
    "HistoricalFuturesMarketTemporalWindow",
    "build_historical_futures_market_ambiguous_candle_policy",
    "build_historical_futures_market_cost_protocol",
    "build_historical_futures_market_contract",
    "build_historical_futures_market_execution_policy",
    "build_historical_futures_market_temporal_split_protocol",
]
