from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from backtesting import BacktestConfig, BacktestConfigurationError, CostModel, PortfolioSnapshot
from backtesting.adapters import strategy_output_to_order
from backtesting.execution import resolve_entry_execution, resolve_exit_execution, resolve_final_close_execution
from backtesting.portfolio import Portfolio
from domain import Candle, DataSource, PaperOrder, RiskDecision, Signal
from domain.serialization import serialize_value

from .offline_research_backtest import (
    OFFLINE_RESEARCH_BACKTEST_DEFAULT_ENTRY_FEE_RATE,
    OFFLINE_RESEARCH_BACKTEST_DEFAULT_EXIT_FEE_RATE,
    OFFLINE_RESEARCH_BACKTEST_DEFAULT_GAP_POLICY,
    OFFLINE_RESEARCH_BACKTEST_DEFAULT_INITIAL_CAPITAL,
    OFFLINE_RESEARCH_BACKTEST_DEFAULT_INTRABAR_POLICY,
    OFFLINE_RESEARCH_BACKTEST_DEFAULT_LEVERAGE,
    OFFLINE_RESEARCH_BACKTEST_DEFAULT_RISK_PERCENT,
    OFFLINE_RESEARCH_BACKTEST_DEFAULT_SLIPPAGE_BPS,
    OFFLINE_RESEARCH_BACKTEST_DEFAULT_SPREAD_BPS,
    discover_okx_phase19a_artifact_paths,
)
from .offline_research_experiment_authorization import (
    OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_ALLOWED_USE_CASES,
    OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_NON_OPERATIONAL_DECLARATION,
    OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PROHIBITED_USE_CASES,
    OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PURPOSE,
    OfflineResearchExperimentAuthorization,
)
from .offline_research_strategy_compatibility import (
    OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES,
    OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION,
    OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES,
    OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PURPOSE,
    OfflineResearchStrategyCompatibilityContract,
    OfflineResearchStrategyCompatibilityDecision,
)
from .okx_historical import OkxHistoricalDataset, load_okx_historical_dataset
from .research_artifact_registry import (
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
from strategies.baseline_a_okx_btc_usdt_research import (
    BASELINE_A_OKX_BTC_USDT_RESEARCH_ALLOWED_DECISIONS,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_ALLOWED_USE_CASES,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_LONG_SETUP_DETECTED,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_NON_OPERATIONAL_DECLARATION,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_PROHIBITED_USE_CASES,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_PURPOSE,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_ID,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_VERSION,
    BaselineAOkxBtcUsdtResearchContract,
    BaselineAOkxBtcUsdtResearchValidationError,
    build_baseline_a_okx_btc_usdt_research_contract,
)

BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_DIAGNOSTIC_SCHEMA_VERSION = 1
BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_DIAGNOSTIC_ID = (
    "baseline_a_okx_btc_usdt_1h_execution_gate_trace_research"
)
BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_DIAGNOSTIC_VERSION = (
    "baseline_a_okx_btc_usdt_1h_execution_gate_trace_research_v1"
)
BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_PURPOSE = "offline_historical_research"
BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_ALLOWED_USE_CASES: tuple[str, ...] = (
    BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_PURPOSE,
)
BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_PROHIBITED_USE_CASES: tuple[str, ...] = (
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
BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_NON_OPERATIONAL_DECLARATION = (
    "This execution-gate trace is research-only and does not authorize replay, backtest, walk-forward, "
    "performance, ranking, paper trading, live trading, execution, or order submission."
)
BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_ALLOWED_GATES: tuple[str, ...] = (
    "signal_emitted",
    "paper_order_created",
    "risk_rejected",
    "portfolio_cash_rejected",
    "position_opened",
    "position_closed",
    "not_reached",
    "active_position_blocked",
    "pending_order_blocked",
    "order_conversion_failed",
)


class OfflineResearchExecutionGateDiagnosticError(Exception):
    pass


class OfflineResearchExecutionGateDiagnosticValidationError(OfflineResearchExecutionGateDiagnosticError):
    pass


class OfflineResearchExecutionGateDiagnosticIntegrityError(OfflineResearchExecutionGateDiagnosticError):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineResearchExecutionGateDiagnosticValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineResearchExecutionGateDiagnosticValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineResearchExecutionGateDiagnosticValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineResearchExecutionGateDiagnosticValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise OfflineResearchExecutionGateDiagnosticValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _decimal_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _boolish_reason(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _calculate_required_cash(order: PaperOrder, *, leverage: Decimal, costs: CostModel, use_execution_price: Decimal | None = None) -> Decimal:
    base_price = use_execution_price if use_execution_price is not None else order.entry
    breakdown = costs.build_entry(base_price, order.quantity, order.direction)
    required_margin = (breakdown.fill_price * order.quantity) / leverage
    return required_margin + breakdown.fee + breakdown.spread_cost + breakdown.slippage_cost


def _default_risk_decision(snapshot: PortfolioSnapshot, order: PaperOrder, *, leverage: Decimal, risk_percent: Decimal) -> dict[str, Any]:
    capital = snapshot.equity
    quantity = order.quantity
    entry = order.entry
    exposure = Decimal("0")
    try:
        exposure = (Decimal(str(entry)) * Decimal(str(quantity))) / leverage if leverage > 0 else Decimal("0")
    except Exception:
        exposure = Decimal("0")
    allowed = capital > 0 and quantity > 0 and exposure <= capital
    reason = "Approved by default risk policy." if allowed else "Insufficient capital for default risk policy."
    return {
        "allowed": allowed,
        "reason": reason,
        "blocked_by": "N/A" if allowed else "RISK",
        "capital": capital,
        "risk_percent": risk_percent,
        "exposure": exposure,
        "exchange_info_ok": True,
    }


def _snapshot_for_candle(portfolio: Portfolio, candle: Candle) -> PortfolioSnapshot:
    return portfolio.snapshot(candle.close_time, {candle.symbol: candle.close})


def _project_candle_to_research_surface(candle: Candle, *, symbol: str) -> Candle:
    return Candle.from_dict(
        {
            "open_time": candle.open_time,
            "close_time": candle.close_time,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
            "symbol": symbol,
            "interval": candle.interval,
            "source": DataSource.PAPER,
        }
    )


def _project_dataset_to_research_surface(dataset: OkxHistoricalDataset, *, symbol: str) -> tuple[Candle, ...]:
    return tuple(_project_candle_to_research_surface(candle, symbol=symbol) for candle in dataset.candles)


def _require_authorization(authorization: Any) -> OfflineResearchExperimentAuthorization:
    if not isinstance(authorization, OfflineResearchExperimentAuthorization):
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "a verified offline research experiment authorization is required."
        )
    if authorization.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchExecutionGateDiagnosticValidationError("authorization provider_name must be OKX.")
    if authorization.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchExecutionGateDiagnosticValidationError("authorization market_type must be spot.")
    if authorization.instrument != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchExecutionGateDiagnosticValidationError("authorization instrument must be BTC-USDT.")
    if authorization.symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchExecutionGateDiagnosticValidationError("authorization symbol must be BTCUSDT.")
    if authorization.interval != "1H":
        raise OfflineResearchExecutionGateDiagnosticValidationError("authorization interval must be 1H.")
    if authorization.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError(
            "authorization requested_start_inclusive_utc diverges from the OKX research artifact."
        )
    if authorization.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError(
            "authorization requested_end_exclusive_utc diverges from the OKX research artifact."
        )
    if authorization.candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError("authorization candle_count must be 42816.")
    if authorization.dataset_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError(
            "authorization dataset_sha256 must match the OKX research artifact."
        )
    if authorization.manifest_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError(
            "authorization manifest_sha256 must match the OKX research artifact."
        )
    if authorization.manifest_hash != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError(
            "authorization manifest_hash must match the OKX research artifact."
        )
    if authorization.purpose != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PURPOSE:
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "authorization purpose must remain offline_historical_research."
        )
    if authorization.historical_research_only is not True:
        raise OfflineResearchExecutionGateDiagnosticValidationError("historical_research_only must be true.")
    if authorization.operational_evidence is not False:
        raise OfflineResearchExecutionGateDiagnosticValidationError("operational_evidence must be false.")
    if authorization.paper_promotion_eligible is not False:
        raise OfflineResearchExecutionGateDiagnosticValidationError("paper_promotion_eligible must be false.")
    if authorization.allowed_use_cases not in ((), OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_ALLOWED_USE_CASES):
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "authorization allowed_use_cases diverges from the research-only contract."
        )
    if authorization.prohibited_use_cases != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PROHIBITED_USE_CASES:
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "authorization prohibited_use_cases diverge from the research-only contract."
        )
    if authorization.non_operational_declaration != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "authorization non_operational_declaration diverges from the research-only contract."
        )
    if not authorization.authorization_hash:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError("authorization_hash is required.")
    return authorization


def _require_compatibility(compatibility_decision: Any) -> OfflineResearchStrategyCompatibilityDecision:
    if not isinstance(compatibility_decision, OfflineResearchStrategyCompatibilityDecision):
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "a verified offline research compatibility decision is required."
        )
    if compatibility_decision.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchExecutionGateDiagnosticValidationError("compatibility provider_name must be OKX.")
    if compatibility_decision.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchExecutionGateDiagnosticValidationError("compatibility market_type must be spot.")
    if compatibility_decision.symbol != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchExecutionGateDiagnosticValidationError("compatibility symbol must be BTC-USDT.")
    if compatibility_decision.canonical_symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchExecutionGateDiagnosticValidationError("compatibility canonical_symbol must be BTCUSDT.")
    if compatibility_decision.interval != "1H":
        raise OfflineResearchExecutionGateDiagnosticValidationError("compatibility interval must be 1H.")
    if compatibility_decision.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError(
            "compatibility requested_start_inclusive_utc diverges from the OKX research artifact."
        )
    if compatibility_decision.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError(
            "compatibility requested_end_exclusive_utc diverges from the OKX research artifact."
        )
    if compatibility_decision.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError("compatibility expected_candle_count must be 42816.")
    if compatibility_decision.required_dataset_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError(
            "compatibility required_dataset_sha256 must match the OKX research artifact."
        )
    if compatibility_decision.required_manifest_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError(
            "compatibility required_manifest_sha256 must match the OKX research artifact."
        )
    if compatibility_decision.required_manifest_hash != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError(
            "compatibility required_manifest_hash must match the OKX research artifact."
        )
    if compatibility_decision.purpose != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PURPOSE:
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "compatibility purpose must remain offline_historical_research."
        )
    if compatibility_decision.historical_research_only is not True:
        raise OfflineResearchExecutionGateDiagnosticValidationError("historical_research_only must be true.")
    if compatibility_decision.operational_evidence is not False:
        raise OfflineResearchExecutionGateDiagnosticValidationError("operational_evidence must be false.")
    if compatibility_decision.paper_promotion_eligible is not False:
        raise OfflineResearchExecutionGateDiagnosticValidationError("paper_promotion_eligible must be false.")
    if compatibility_decision.allowed_use_cases not in ((), OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES):
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "compatibility allowed_use_cases diverges from the research-only contract."
        )
    if compatibility_decision.prohibited_use_cases != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES:
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "compatibility prohibited_use_cases diverge from the research-only contract."
        )
    if compatibility_decision.non_operational_declaration != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "compatibility non_operational_declaration diverges from the research-only contract."
        )
    if not compatibility_decision.compatibility_hash:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError("compatibility_hash is required.")
    return compatibility_decision


def _require_strategy_contract(
    strategy_contract: Any,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
) -> BaselineAOkxBtcUsdtResearchContract:
    if not isinstance(strategy_contract, BaselineAOkxBtcUsdtResearchContract):
        raise OfflineResearchExecutionGateDiagnosticValidationError("baseline A strategy contract is required.")
    if strategy_contract.strategy_id != BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_ID:
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "strategy_id must be baseline_a_okx_btc_usdt_1h_research."
        )
    if strategy_contract.strategy_version != BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_VERSION:
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "strategy_version must remain baseline_a_okx_btc_usdt_1h_research_v1."
        )
    if strategy_contract.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchExecutionGateDiagnosticValidationError("strategy provider_name must be OKX.")
    if strategy_contract.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchExecutionGateDiagnosticValidationError("strategy market_type must be spot.")
    if strategy_contract.symbol != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchExecutionGateDiagnosticValidationError("strategy symbol must be BTC-USDT.")
    if strategy_contract.canonical_symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchExecutionGateDiagnosticValidationError("strategy canonical_symbol must be BTCUSDT.")
    if strategy_contract.interval != "1H":
        raise OfflineResearchExecutionGateDiagnosticValidationError("strategy interval must be 1H.")
    if strategy_contract.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError(
            "strategy requested_start_inclusive_utc diverges from the OKX research artifact."
        )
    if strategy_contract.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError(
            "strategy requested_end_exclusive_utc diverges from the OKX research artifact."
        )
    if strategy_contract.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError("strategy expected_candle_count must be 42816.")
    if strategy_contract.required_authorization_hash != authorization.authorization_hash:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError(
            "strategy required_authorization_hash diverges from the verified authorization."
        )
    if strategy_contract.required_compatibility_hash != compatibility_decision.compatibility_hash:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError(
            "strategy required_compatibility_hash diverges from the verified compatibility decision."
        )
    if strategy_contract.purpose != BASELINE_A_OKX_BTC_USDT_RESEARCH_PURPOSE:
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "strategy purpose must remain offline_historical_research."
        )
    if strategy_contract.historical_research_only is not True:
        raise OfflineResearchExecutionGateDiagnosticValidationError("historical_research_only must be true.")
    if strategy_contract.operational_evidence is not False:
        raise OfflineResearchExecutionGateDiagnosticValidationError("operational_evidence must be false.")
    if strategy_contract.paper_promotion_eligible is not False:
        raise OfflineResearchExecutionGateDiagnosticValidationError("paper_promotion_eligible must be false.")
    if strategy_contract.allowed_use_cases != BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_ALLOWED_USE_CASES:
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "strategy allowed_use_cases must remain offline_historical_research."
        )
    if strategy_contract.prohibited_use_cases != BASELINE_A_OKX_BTC_USDT_RESEARCH_PROHIBITED_USE_CASES:
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "strategy prohibited_use_cases must block operational use cases."
        )
    if strategy_contract.allowed_decisions != BASELINE_A_OKX_BTC_USDT_RESEARCH_ALLOWED_DECISIONS:
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "strategy allowed_decisions must remain long_setup_detected or no_setup."
        )
    if strategy_contract.non_operational_declaration != BASELINE_A_OKX_BTC_USDT_RESEARCH_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchExecutionGateDiagnosticValidationError(
            "strategy non_operational_declaration diverges from the research-only contract."
        )
    if not strategy_contract.contract_hash:
        raise OfflineResearchExecutionGateDiagnosticIntegrityError("strategy contract_hash is required.")
    return strategy_contract


@dataclass(frozen=True, slots=True)
class ExecutionGateTraceCosts:
    entry_fee_rate: Decimal = OFFLINE_RESEARCH_BACKTEST_DEFAULT_ENTRY_FEE_RATE
    exit_fee_rate: Decimal = OFFLINE_RESEARCH_BACKTEST_DEFAULT_EXIT_FEE_RATE
    spread_bps: Decimal = OFFLINE_RESEARCH_BACKTEST_DEFAULT_SPREAD_BPS
    slippage_bps: Decimal = OFFLINE_RESEARCH_BACKTEST_DEFAULT_SLIPPAGE_BPS
    leverage: Decimal = OFFLINE_RESEARCH_BACKTEST_DEFAULT_LEVERAGE
    initial_capital: Decimal = OFFLINE_RESEARCH_BACKTEST_DEFAULT_INITIAL_CAPITAL
    risk_percent: Decimal = OFFLINE_RESEARCH_BACKTEST_DEFAULT_RISK_PERCENT
    paper_only: bool = True
    allow_short: bool = False
    intrabar_policy: Any = OFFLINE_RESEARCH_BACKTEST_DEFAULT_INTRABAR_POLICY
    gap_policy: Any = OFFLINE_RESEARCH_BACKTEST_DEFAULT_GAP_POLICY
    close_open_positions_at_end: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_fee_rate", Decimal(str(self.entry_fee_rate)))
        object.__setattr__(self, "exit_fee_rate", Decimal(str(self.exit_fee_rate)))
        object.__setattr__(self, "spread_bps", Decimal(str(self.spread_bps)))
        object.__setattr__(self, "slippage_bps", Decimal(str(self.slippage_bps)))
        object.__setattr__(self, "leverage", Decimal(str(self.leverage)))
        object.__setattr__(self, "initial_capital", Decimal(str(self.initial_capital)))
        object.__setattr__(self, "risk_percent", Decimal(str(self.risk_percent)))
        _require_bool(self.paper_only, "paper_only")
        _require_bool(self.allow_short, "allow_short")
        _require_bool(self.close_open_positions_at_end, "close_open_positions_at_end")
        if self.paper_only is not True:
            raise OfflineResearchExecutionGateDiagnosticValidationError("paper_only must be true.")
        if self.allow_short is not False:
            raise OfflineResearchExecutionGateDiagnosticValidationError("allow_short must be false.")
        if self.close_open_positions_at_end is not True:
            raise OfflineResearchExecutionGateDiagnosticValidationError("close_open_positions_at_end must be true.")
        if self.leverage <= 0:
            raise OfflineResearchExecutionGateDiagnosticValidationError("leverage must be greater than zero.")
        if self.risk_percent <= 0:
            raise OfflineResearchExecutionGateDiagnosticValidationError("risk_percent must be greater than zero.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_fee_rate": str(self.entry_fee_rate),
            "exit_fee_rate": str(self.exit_fee_rate),
            "spread_bps": str(self.spread_bps),
            "slippage_bps": str(self.slippage_bps),
            "leverage": str(self.leverage),
            "initial_capital": str(self.initial_capital),
            "risk_percent": str(self.risk_percent),
            "paper_only": self.paper_only,
            "allow_short": self.allow_short,
            "intrabar_policy": getattr(self.intrabar_policy, "value", str(self.intrabar_policy)),
            "gap_policy": getattr(self.gap_policy, "value", str(self.gap_policy)),
            "close_open_positions_at_end": self.close_open_positions_at_end,
        }


@dataclass(slots=True)
class _ExecutionGateTraceRecordState:
    candle_index: int
    open_time: datetime
    close_time: datetime
    signal_side: str
    signal_timestamp: datetime
    signal_reason: str
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal | None
    quantity_proposed: Decimal
    exposure: Decimal
    capital_available: Decimal
    signal_emitted: bool = True
    paper_order_created: bool = False
    risk_allowed: bool | None = None
    risk_reason: str | None = None
    required_cash: Decimal | None = None
    open_attempt_result: str = "not_attempted"
    gate_terminal: str = "not_reached"
    normalized_rejection_reason: str | None = None
    position_opened: bool = False
    position_open_time: datetime | None = None
    position_closed: bool = False
    position_close_time: datetime | None = None
    close_reason: str | None = None

    def freeze(self) -> "ExecutionGateTraceRecord":
        return ExecutionGateTraceRecord(
            candle_index=self.candle_index,
            open_time=self.open_time,
            close_time=self.close_time,
            signal_side=self.signal_side,
            signal_timestamp=self.signal_timestamp,
            signal_reason=self.signal_reason,
            entry=self.entry,
            stop_loss=self.stop_loss,
            take_profit=self.take_profit,
            quantity_proposed=self.quantity_proposed,
            exposure=self.exposure,
            capital_available=self.capital_available,
            signal_emitted=self.signal_emitted,
            paper_order_created=self.paper_order_created,
            risk_allowed=self.risk_allowed,
            risk_reason=self.risk_reason,
            required_cash=self.required_cash,
            open_attempt_result=self.open_attempt_result,
            gate_terminal=self.gate_terminal,
            normalized_rejection_reason=self.normalized_rejection_reason,
            position_opened=self.position_opened,
            position_open_time=self.position_open_time,
            position_closed=self.position_closed,
            position_close_time=self.position_close_time,
            close_reason=self.close_reason,
        )


@dataclass(frozen=True, slots=True)
class ExecutionGateTraceRecord:
    candle_index: int
    open_time: datetime
    close_time: datetime
    signal_side: str
    signal_timestamp: datetime
    signal_reason: str
    entry: Decimal
    stop_loss: Decimal
    take_profit: Decimal | None
    quantity_proposed: Decimal
    exposure: Decimal
    capital_available: Decimal
    signal_emitted: bool = True
    paper_order_created: bool = False
    risk_allowed: bool | None = None
    risk_reason: str | None = None
    required_cash: Decimal | None = None
    open_attempt_result: str = "not_attempted"
    gate_terminal: str = "not_reached"
    normalized_rejection_reason: str | None = None
    position_opened: bool = False
    position_open_time: datetime | None = None
    position_closed: bool = False
    position_close_time: datetime | None = None
    close_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "candle_index": self.candle_index,
            "open_time": _utc_iso(self.open_time),
            "close_time": _utc_iso(self.close_time),
            "signal_side": self.signal_side,
            "signal_timestamp": _utc_iso(self.signal_timestamp),
            "signal_reason": self.signal_reason,
            "entry": str(self.entry),
            "stop_loss": str(self.stop_loss),
            "take_profit": _decimal_str(self.take_profit),
            "quantity_proposed": str(self.quantity_proposed),
            "exposure": str(self.exposure),
            "capital_available": str(self.capital_available),
            "signal_emitted": self.signal_emitted,
            "paper_order_created": self.paper_order_created,
            "risk_allowed": self.risk_allowed,
            "risk_reason": self.risk_reason,
            "required_cash": _decimal_str(self.required_cash),
            "open_attempt_result": self.open_attempt_result,
            "gate_terminal": self.gate_terminal,
            "normalized_rejection_reason": self.normalized_rejection_reason,
            "position_opened": self.position_opened,
            "position_open_time": _utc_iso(self.position_open_time) if self.position_open_time is not None else None,
            "position_closed": self.position_closed,
            "position_close_time": _utc_iso(self.position_close_time) if self.position_close_time is not None else None,
            "close_reason": self.close_reason,
        }


@dataclass(frozen=True, slots=True)
class ExecutionGateTraceContract:
    schema_version: int
    diagnostic_id: str
    diagnostic_version: str
    strategy_id: str
    strategy_version: str
    provider_name: str
    market_type: str
    symbol: str
    canonical_symbol: str
    interval: str
    requested_start_inclusive_utc: datetime
    requested_end_exclusive_utc: datetime
    expected_candle_count: int
    authorization_hash: str
    compatibility_hash: str
    strategy_contract_hash: str
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    allowed_use_cases: tuple[str, ...] = field(
        default_factory=lambda: BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_ALLOWED_USE_CASES
    )
    prohibited_use_cases: tuple[str, ...] = field(
        default_factory=lambda: BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_PROHIBITED_USE_CASES
    )
    non_operational_declaration: str = BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_NON_OPERATIONAL_DECLARATION
    costs: ExecutionGateTraceCosts = field(default_factory=ExecutionGateTraceCosts)
    contract_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "diagnostic_id", _require_str(self.diagnostic_id, "diagnostic_id"))
        object.__setattr__(self, "diagnostic_version", _require_str(self.diagnostic_version, "diagnostic_version"))
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
        object.__setattr__(self, "authorization_hash", _require_hex_digest(self.authorization_hash, "authorization_hash"))
        object.__setattr__(self, "compatibility_hash", _require_hex_digest(self.compatibility_hash, "compatibility_hash"))
        object.__setattr__(self, "strategy_contract_hash", _require_hex_digest(self.strategy_contract_hash, "strategy_contract_hash"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "allowed_use_cases", tuple(dict.fromkeys(_require_str(item, "allowed_use_case").lower() for item in self.allowed_use_cases)))
        object.__setattr__(self, "prohibited_use_cases", tuple(dict.fromkeys(_require_str(item, "prohibited_use_case").lower() for item in self.prohibited_use_cases)))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
            raise OfflineResearchExecutionGateDiagnosticValidationError("provider_name must be OKX.")
        if self.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
            raise OfflineResearchExecutionGateDiagnosticValidationError("market_type must be spot.")
        if self.symbol != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
            raise OfflineResearchExecutionGateDiagnosticValidationError("symbol must be BTC-USDT.")
        if self.canonical_symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
            raise OfflineResearchExecutionGateDiagnosticValidationError("canonical_symbol must be BTCUSDT.")
        if self.interval != "1H":
            raise OfflineResearchExecutionGateDiagnosticValidationError("interval must be 1H.")
        if self.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
            raise OfflineResearchExecutionGateDiagnosticIntegrityError(
                "requested_start_inclusive_utc diverges from the OKX research artifact."
            )
        if self.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
            raise OfflineResearchExecutionGateDiagnosticIntegrityError(
                "requested_end_exclusive_utc diverges from the OKX research artifact."
            )
        if self.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
            raise OfflineResearchExecutionGateDiagnosticIntegrityError("expected_candle_count must be 42816.")
        if self.historical_research_only is not True:
            raise OfflineResearchExecutionGateDiagnosticValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchExecutionGateDiagnosticValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchExecutionGateDiagnosticValidationError("paper_promotion_eligible must be false.")
        if self.allowed_use_cases != BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_ALLOWED_USE_CASES:
            raise OfflineResearchExecutionGateDiagnosticValidationError(
                "allowed_use_cases must remain offline_historical_research."
            )
        if self.prohibited_use_cases != BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_PROHIBITED_USE_CASES:
            raise OfflineResearchExecutionGateDiagnosticValidationError(
                "prohibited_use_cases must block operational use cases."
            )
        if self.non_operational_declaration != BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchExecutionGateDiagnosticValidationError(
                "non_operational_declaration diverges from the research-only contract."
            )
        if not isinstance(self.costs, ExecutionGateTraceCosts):
            raise OfflineResearchExecutionGateDiagnosticValidationError("costs must be ExecutionGateTraceCosts.")
        object.__setattr__(
            self,
            "costs",
            ExecutionGateTraceCosts(
                entry_fee_rate=self.costs.entry_fee_rate,
                exit_fee_rate=self.costs.exit_fee_rate,
                spread_bps=self.costs.spread_bps,
                slippage_bps=self.costs.slippage_bps,
                leverage=self.costs.leverage,
                initial_capital=self.costs.initial_capital,
                risk_percent=self.costs.risk_percent,
                paper_only=self.costs.paper_only,
                allow_short=self.costs.allow_short,
                intrabar_policy=self.costs.intrabar_policy,
                gap_policy=self.costs.gap_policy,
                close_open_positions_at_end=self.costs.close_open_positions_at_end,
            ),
        )
        expected_hash = _hash_payload(self.canonical_payload(include_contract_hash=False))
        if self.contract_hash:
            if self.contract_hash != expected_hash:
                raise OfflineResearchExecutionGateDiagnosticIntegrityError("contract_hash mismatch.")
        else:
            object.__setattr__(self, "contract_hash", expected_hash)

    def canonical_payload(self, *, include_contract_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "diagnostic_id": self.diagnostic_id,
            "diagnostic_version": self.diagnostic_version,
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
            "authorization_hash": self.authorization_hash,
            "compatibility_hash": self.compatibility_hash,
            "strategy_contract_hash": self.strategy_contract_hash,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "allowed_use_cases": self.allowed_use_cases,
            "prohibited_use_cases": self.prohibited_use_cases,
            "non_operational_declaration": self.non_operational_declaration,
            "costs": self.costs.as_dict(),
        }
        if include_contract_hash:
            payload["contract_hash"] = self.contract_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_contract_hash=True))


@dataclass(frozen=True, slots=True)
class ExecutionGateTraceReport:
    contract: ExecutionGateTraceContract
    analyzed_at_utc: datetime
    analysis_start_utc: datetime
    analysis_end_utc: datetime
    projected_symbol: str
    projected_source: str
    candles_total: int
    signals_emitted: int
    not_reached: int
    trace_counts: Mapping[str, int]
    first_occurrences: Mapping[str, Any]
    trace_records: tuple[ExecutionGateTraceRecord, ...]
    dataset_hash: str
    manifest_hash: str
    report_notice: str = BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_NON_OPERATIONAL_DECLARATION
    report_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "analyzed_at_utc", _require_utc_datetime(self.analyzed_at_utc, "analyzed_at_utc"))
        object.__setattr__(self, "analysis_start_utc", _require_utc_datetime(self.analysis_start_utc, "analysis_start_utc"))
        object.__setattr__(self, "analysis_end_utc", _require_utc_datetime(self.analysis_end_utc, "analysis_end_utc"))
        object.__setattr__(self, "projected_symbol", _require_str(self.projected_symbol, "projected_symbol").upper())
        object.__setattr__(self, "projected_source", _require_str(self.projected_source, "projected_source"))
        object.__setattr__(self, "candles_total", _require_int(self.candles_total, "candles_total"))
        object.__setattr__(self, "signals_emitted", _require_int(self.signals_emitted, "signals_emitted"))
        object.__setattr__(self, "not_reached", _require_int(self.not_reached, "not_reached"))
        object.__setattr__(self, "trace_counts", dict(self.trace_counts))
        object.__setattr__(self, "first_occurrences", dict(self.first_occurrences))
        object.__setattr__(self, "trace_records", tuple(self.trace_records))
        object.__setattr__(self, "dataset_hash", _require_hex_digest(self.dataset_hash, "dataset_hash"))
        object.__setattr__(self, "manifest_hash", _require_hex_digest(self.manifest_hash, "manifest_hash"))
        object.__setattr__(self, "report_notice", _require_str(self.report_notice, "report_notice"))
        if self.report_notice != BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchExecutionGateDiagnosticValidationError("report_notice must remain research-only.")
        expected_hash = _hash_payload(self.canonical_payload(include_report_hash=False))
        if self.report_hash:
            if self.report_hash != expected_hash:
                raise OfflineResearchExecutionGateDiagnosticIntegrityError("report_hash mismatch.")
        else:
            object.__setattr__(self, "report_hash", expected_hash)

    def canonical_payload(self, *, include_report_hash: bool = True) -> dict[str, Any]:
        payload = {
            "contract": self.contract.as_dict(),
            "analyzed_at_utc": _utc_iso(self.analyzed_at_utc),
            "analysis_start_utc": _utc_iso(self.analysis_start_utc),
            "analysis_end_utc": _utc_iso(self.analysis_end_utc),
            "projected_symbol": self.projected_symbol,
            "projected_source": self.projected_source,
            "candles_total": self.candles_total,
            "signals_emitted": self.signals_emitted,
            "not_reached": self.not_reached,
            "trace_counts": dict(sorted(self.trace_counts.items())),
            "first_occurrences": dict(sorted(self.first_occurrences.items())),
            "trace_records": [record.as_dict() for record in self.trace_records],
            "dataset_hash": self.dataset_hash,
            "manifest_hash": self.manifest_hash,
            "report_notice": self.report_notice,
        }
        if include_report_hash:
            payload["report_hash"] = self.report_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_report_hash=True))


def build_baseline_a_okx_btc_usdt_1h_execution_gate_trace_contract(
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    *,
    strategy_version: str = BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_VERSION,
    costs: ExecutionGateTraceCosts | None = None,
    contract_hash: str = "",
) -> ExecutionGateTraceContract:
    if costs is None:
        costs = ExecutionGateTraceCosts()
    strategy_contract = build_baseline_a_okx_btc_usdt_research_contract(
        authorization,
        compatibility_decision,
        strategy_version=strategy_version,
    )
    return ExecutionGateTraceContract(
        schema_version=BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_DIAGNOSTIC_SCHEMA_VERSION,
        diagnostic_id=BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_DIAGNOSTIC_ID,
        diagnostic_version=BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_DIAGNOSTIC_VERSION,
        strategy_id=strategy_contract.strategy_id,
        strategy_version=strategy_contract.strategy_version,
        provider_name=strategy_contract.provider_name,
        market_type=strategy_contract.market_type,
        symbol=strategy_contract.symbol,
        canonical_symbol=strategy_contract.canonical_symbol,
        interval=strategy_contract.interval,
        requested_start_inclusive_utc=strategy_contract.requested_start_inclusive_utc,
        requested_end_exclusive_utc=strategy_contract.requested_end_exclusive_utc,
        expected_candle_count=strategy_contract.expected_candle_count,
        authorization_hash=authorization.authorization_hash,
        compatibility_hash=compatibility_decision.compatibility_hash,
        strategy_contract_hash=strategy_contract.contract_hash,
        costs=costs,
        contract_hash=contract_hash,
    )


def _trace_record_payload(record: ExecutionGateTraceRecord) -> dict[str, Any]:
    return record.as_dict()


def _first_occurrence_payload(record: ExecutionGateTraceRecord) -> dict[str, Any]:
    payload = record.as_dict()
    return {
        "candle_index": payload["candle_index"],
        "open_time": payload["open_time"],
        "signal_side": payload["signal_side"],
        "gate_terminal": payload["gate_terminal"],
        "normalized_rejection_reason": payload["normalized_rejection_reason"],
        "signal_reason": payload["signal_reason"],
    }


def _build_trace_report(
    *,
    contract: ExecutionGateTraceContract,
    analyzed_at_utc: datetime,
    analysis_start_utc: datetime,
    analysis_end_utc: datetime,
    projected_symbol: str,
    projected_source: str,
    candles: Sequence[Candle],
    trace_records: Sequence[ExecutionGateTraceRecord],
    first_occurrences: Mapping[str, Any],
    dataset_hash: str,
    manifest_hash: str,
) -> ExecutionGateTraceReport:
    counts = Counter()
    for record in trace_records:
        counts["signal_emitted"] += 1
        if record.paper_order_created:
            counts["paper_order_created"] += 1
        if record.risk_allowed is False:
            counts["risk_rejected"] += 1
        if record.gate_terminal == "portfolio_cash_rejected":
            counts["portfolio_cash_rejected"] += 1
        if record.position_opened:
            counts["position_opened"] += 1
        if record.position_closed:
            counts["position_closed"] += 1
        if record.gate_terminal == "active_position_blocked":
            counts["active_position_blocked"] += 1
        if record.gate_terminal == "pending_order_blocked":
            counts["pending_order_blocked"] += 1
        if record.gate_terminal == "order_conversion_failed":
            counts["order_conversion_failed"] += 1
    counts["not_reached"] = len(candles) - len(trace_records)
    for gate in BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_ALLOWED_GATES:
        counts.setdefault(gate, 0)
    return ExecutionGateTraceReport(
        contract=contract,
        analyzed_at_utc=analyzed_at_utc,
        analysis_start_utc=analysis_start_utc,
        analysis_end_utc=analysis_end_utc,
        projected_symbol=projected_symbol,
        projected_source=projected_source,
        candles_total=len(candles),
        signals_emitted=len(trace_records),
        not_reached=counts["not_reached"],
        trace_counts=dict(sorted(counts.items())),
        first_occurrences=dict(sorted(first_occurrences.items())),
        trace_records=tuple(trace_records),
        dataset_hash=dataset_hash,
        manifest_hash=manifest_hash,
    )


def _simulate_execution_gate_trace(
    candles: Sequence[Candle],
    *,
    strategy_callable: Callable[[Sequence[Candle], PortfolioSnapshot], object | None],
    contract: ExecutionGateTraceContract,
    analyzed_at_utc: datetime,
    analysis_start_utc: datetime,
    analysis_end_utc: datetime,
    projected_symbol: str,
    projected_source: str,
    dataset_hash: str,
    manifest_hash: str,
) -> ExecutionGateTraceReport:
    if not isinstance(candles, Sequence):
        raise OfflineResearchExecutionGateDiagnosticValidationError("candles are required.")
    history = tuple(candles)
    if not history:
        raise OfflineResearchExecutionGateDiagnosticValidationError("candles must not be empty.")
    if not callable(strategy_callable):
        raise OfflineResearchExecutionGateDiagnosticValidationError("strategy_callable is required.")

    costs = contract.costs
    config = BacktestConfig(
        initial_capital=costs.initial_capital,
        risk_percent=costs.risk_percent,
        entry_fee_rate=costs.entry_fee_rate,
        exit_fee_rate=costs.exit_fee_rate,
        spread_bps=costs.spread_bps,
        slippage_bps=costs.slippage_bps,
        leverage=costs.leverage,
        symbol=contract.symbol,
        interval=contract.interval,
        paper_only=True,
        allow_short=False,
        intrabar_policy=costs.intrabar_policy,
        gap_policy=costs.gap_policy,
        strategy_version=contract.strategy_version,
        close_open_positions_at_end=costs.close_open_positions_at_end,
    )
    cost_model = CostModel(
        entry_fee_rate=costs.entry_fee_rate,
        exit_fee_rate=costs.exit_fee_rate,
        spread_bps=costs.spread_bps,
        slippage_bps=costs.slippage_bps,
    )
    portfolio = Portfolio(starting_capital=costs.initial_capital, config=config, cost_model=cost_model)
    trace_states: list[_ExecutionGateTraceRecordState] = []
    pending_order: PaperOrder | None = None
    pending_trace_index: int | None = None
    pending_risk_decision: dict[str, Any] | None = None
    open_trace_index: int | None = None
    first_occurrences: dict[str, Any] = {}

    def _remember(key: str, payload: Any) -> None:
        if key not in first_occurrences:
            first_occurrences[key] = payload

    for index, candle in enumerate(history):
        if pending_order is not None and pending_trace_index is not None:
            entry_execution = resolve_entry_execution(pending_order, candle, cost_model)
            trace_state = trace_states[pending_trace_index]
            actual_required_cash = _calculate_required_cash(
                pending_order,
                leverage=costs.leverage,
                costs=cost_model,
                use_execution_price=entry_execution.base_price,
            )
            trace_state.required_cash = actual_required_cash
            try:
                portfolio.open_position(
                    pending_order,
                    entry_execution,
                    entry_index=index,
                    risk_decision=RiskDecision(
                        allowed=bool(pending_risk_decision["allowed"]) if pending_risk_decision is not None else False,
                        reason=str(pending_risk_decision["reason"]) if pending_risk_decision is not None else "",
                        blocked_by=str(pending_risk_decision["blocked_by"]) if pending_risk_decision is not None else "RISK",
                        capital=pending_risk_decision["capital"] if pending_risk_decision is not None else Decimal("0"),
                        risk_percent=pending_risk_decision["risk_percent"] if pending_risk_decision is not None else Decimal("0"),
                        exposure=pending_risk_decision["exposure"] if pending_risk_decision is not None else Decimal("0"),
                        timestamp=candle.open_time,
                        strategy_version=contract.strategy_version,
                        exchange_info_ok=True,
                        notes="",
                    ),
                )
            except BacktestConfigurationError as exc:
                if "Insufficient capital for position." not in str(exc):
                    raise
                trace_state.position_opened = False
                trace_state.open_attempt_result = "rejected"
                trace_state.gate_terminal = "portfolio_cash_rejected"
                trace_state.normalized_rejection_reason = "required_cash_exceeds_available_cash"
                _remember("first_portfolio_cash_rejected", _trace_record_payload(trace_state.freeze()))
                _remember("first_rejection_reason_required_cash_exceeds_available_cash", _trace_record_payload(trace_state.freeze()))
                pending_order = None
                pending_trace_index = None
                pending_risk_decision = None
            else:
                trace_state.position_opened = True
                trace_state.position_open_time = candle.open_time
                trace_state.open_attempt_result = "opened"
                trace_state.gate_terminal = "position_opened"
                _remember("first_position_opened", _trace_record_payload(trace_state.freeze()))
                open_trace_index = pending_trace_index
                pending_order = None
                pending_trace_index = None
                pending_risk_decision = None

        for symbol in list(portfolio.open_positions.keys()):
            exit_decision = resolve_exit_execution(
                portfolio.open_positions[symbol].position,
                candle,
                costs=cost_model,
                intrabar_policy=config.intrabar_policy,
            )
            if exit_decision is None:
                continue
            portfolio.close_position(
                symbol,
                exit_decision,
                exit_reason=exit_decision.reason,
                exit_index=index,
                gap_handled=exit_decision.gap_handled,
            )
            if open_trace_index is not None:
                trace_state = trace_states[open_trace_index]
                trace_state.position_closed = True
                trace_state.position_close_time = exit_decision.timestamp
                trace_state.close_reason = exit_decision.reason
                trace_state.gate_terminal = "position_closed"
                trace_state.open_attempt_result = "closed"
                _remember("first_position_closed", _trace_record_payload(trace_state.freeze()))
                open_trace_index = None

        prices = {symbol: candle.close for symbol in portfolio.open_positions.keys()}
        prices[candle.symbol] = candle.close
        snapshot = portfolio.snapshot(candle.close_time, prices)

        if index >= len(history) - 1:
            continue

        strategy_output = strategy_callable(history[: index + 1], snapshot)
        order = strategy_output_to_order(
            strategy_output,
            capital=snapshot.equity,
            risk_percent=config.risk_percent,
        )
        if order is None:
            continue

        record = _ExecutionGateTraceRecordState(
            candle_index=index,
            open_time=candle.open_time,
            close_time=candle.close_time,
            signal_side=order.direction.value,
            signal_timestamp=order.opened_at if isinstance(order, PaperOrder) else candle.close_time,
            signal_reason=(strategy_output.reason if isinstance(strategy_output, Signal) else getattr(strategy_output, "reason", "")),
            entry=order.entry,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            quantity_proposed=order.quantity,
            exposure=(order.entry * order.quantity) / costs.leverage,
            capital_available=snapshot.equity,
            signal_emitted=True,
            paper_order_created=True,
            open_attempt_result="paper_order_created",
            gate_terminal="paper_order_created",
            required_cash=_calculate_required_cash(order, leverage=costs.leverage, costs=cost_model),
        )
        trace_states.append(record)
        _remember("first_signal_emitted", _trace_record_payload(record.freeze()))
        _remember("first_paper_order_created", _trace_record_payload(record.freeze()))

        if portfolio.open_positions:
            record.gate_terminal = "active_position_blocked"
            record.open_attempt_result = "blocked"
            record.normalized_rejection_reason = "open_position_already_exists"
            _remember("first_active_position_blocked", _trace_record_payload(record.freeze()))
            _remember("first_rejection_reason_open_position_already_exists", _trace_record_payload(record.freeze()))
            continue
        if pending_order is not None:
            record.gate_terminal = "pending_order_blocked"
            record.open_attempt_result = "blocked"
            record.normalized_rejection_reason = "pending_order_already_exists"
            _remember("first_pending_order_blocked", _trace_record_payload(record.freeze()))
            _remember("first_rejection_reason_pending_order_already_exists", _trace_record_payload(record.freeze()))
            continue
        if order.direction.value == "VENDA" and not config.allow_short:
            record.gate_terminal = "risk_rejected"
            record.open_attempt_result = "rejected"
            record.risk_allowed = False
            record.risk_reason = "short orders are blocked."
            record.normalized_rejection_reason = "short_disallowed"
            _remember("first_risk_rejected", _trace_record_payload(record.freeze()))
            _remember("first_rejection_reason_short_disallowed", _trace_record_payload(record.freeze()))
            continue

        risk_snapshot = _default_risk_decision(
            snapshot,
            order,
            leverage=costs.leverage,
            risk_percent=config.risk_percent,
        )
        record.risk_allowed = bool(risk_snapshot["allowed"])
        record.risk_reason = str(risk_snapshot["reason"])
        if not risk_snapshot["allowed"] or risk_snapshot["exchange_info_ok"] is False:
            record.gate_terminal = "risk_rejected"
            record.open_attempt_result = "rejected"
            record.normalized_rejection_reason = "risk_not_allowed"
            _remember("first_risk_rejected", _trace_record_payload(record.freeze()))
            _remember("first_rejection_reason_risk_not_allowed", _trace_record_payload(record.freeze()))
            continue

        pending_order = order
        pending_trace_index = len(trace_states) - 1
        pending_risk_decision = risk_snapshot

    if costs.close_open_positions_at_end and portfolio.open_positions:
        final_candle = history[-1]
        for symbol, state in list(portfolio.open_positions.items()):
            exit_decision = resolve_final_close_execution(state.position, final_candle, costs=cost_model)
            portfolio.close_position(
                symbol,
                exit_decision,
                exit_reason=exit_decision.reason,
                exit_index=len(history) - 1,
                gap_handled=False,
            )
            if open_trace_index is not None:
                trace_state = trace_states[open_trace_index]
                trace_state.position_closed = True
                trace_state.position_close_time = exit_decision.timestamp
                trace_state.close_reason = exit_decision.reason
                trace_state.gate_terminal = "position_closed"
                trace_state.open_attempt_result = "closed"
                _remember("first_position_closed", _trace_record_payload(trace_state.freeze()))
                open_trace_index = None

    frozen_records = tuple(state.freeze() for state in trace_states)
    not_reached = len(history) - len(frozen_records)
    if history and not trace_states:
        _remember(
            "first_not_reached",
            {
                "candle_index": 0,
                "open_time": _utc_iso(history[0].open_time),
                "close_time": _utc_iso(history[0].close_time),
                "reason": "signal_not_emitted",
            },
        )
    trace_counts = Counter()
    for record in frozen_records:
        trace_counts["signal_emitted"] += 1
        if record.paper_order_created:
            trace_counts["paper_order_created"] += 1
        if record.risk_allowed is False:
            trace_counts["risk_rejected"] += 1
        if record.gate_terminal == "portfolio_cash_rejected":
            trace_counts["portfolio_cash_rejected"] += 1
        if record.position_opened:
            trace_counts["position_opened"] += 1
        if record.position_closed:
            trace_counts["position_closed"] += 1
        if record.gate_terminal == "active_position_blocked":
            trace_counts["active_position_blocked"] += 1
        if record.gate_terminal == "pending_order_blocked":
            trace_counts["pending_order_blocked"] += 1
        if record.gate_terminal == "order_conversion_failed":
            trace_counts["order_conversion_failed"] += 1
    trace_counts["not_reached"] = not_reached
    for gate in BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_ALLOWED_GATES:
        trace_counts.setdefault(gate, 0)
    return ExecutionGateTraceReport(
        contract=contract,
        analyzed_at_utc=analyzed_at_utc,
        analysis_start_utc=analysis_start_utc,
        analysis_end_utc=analysis_end_utc,
        projected_symbol=projected_symbol,
        projected_source=projected_source,
        candles_total=len(history),
        signals_emitted=len(frozen_records),
        not_reached=not_reached,
        trace_counts=dict(sorted(trace_counts.items())),
        first_occurrences=dict(sorted(first_occurrences.items())),
        trace_records=frozen_records,
        dataset_hash=dataset_hash,
        manifest_hash=manifest_hash,
    )


def run_baseline_a_okx_btc_usdt_1h_execution_gate_trace_research(
    candles: Sequence[Candle],
    *,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    strategy_contract: BaselineAOkxBtcUsdtResearchContract | None = None,
    analyzed_at_utc: datetime | None = None,
    costs: ExecutionGateTraceCosts | None = None,
) -> ExecutionGateTraceReport:
    authorization = _require_authorization(authorization)
    compatibility_decision = _require_compatibility(compatibility_decision)
    if strategy_contract is None:
        strategy_contract = build_baseline_a_okx_btc_usdt_research_contract(authorization, compatibility_decision)
    strategy_contract = _require_strategy_contract(strategy_contract, authorization, compatibility_decision)
    history = tuple(candles)
    if not history:
        raise OfflineResearchExecutionGateDiagnosticValidationError("candles must not be empty.")
    if costs is None:
        costs = ExecutionGateTraceCosts()
    from market_data.offline_research_backtest import _build_strategy_callable  # local import to keep scope explicit

    strategy_callable = _build_strategy_callable(
        authorization=authorization,
        compatibility_decision=compatibility_decision,
        strategy_contract=strategy_contract,
    )
    analyzed_at = _require_utc_datetime(analyzed_at_utc or authorization.issued_at_utc, "analyzed_at_utc")
    dataset_hash = _hash_payload([candle.to_dict() for candle in history])
    manifest_hash = _hash_payload(
        {
            "dataset_hash": dataset_hash,
            "candle_count": len(history),
            "first_open_time": _utc_iso(history[0].open_time),
            "last_close_time": _utc_iso(history[-1].close_time),
        }
    )
    return _simulate_execution_gate_trace(
        history,
        strategy_callable=strategy_callable,
        contract=build_baseline_a_okx_btc_usdt_1h_execution_gate_trace_contract(
            authorization,
            compatibility_decision,
            strategy_version=strategy_contract.strategy_version,
            costs=costs,
        ),
        analyzed_at_utc=analyzed_at,
        analysis_start_utc=history[0].open_time,
        analysis_end_utc=history[-1].close_time,
        projected_symbol=strategy_contract.symbol,
        projected_source=DataSource.PAPER.value,
        dataset_hash=dataset_hash,
        manifest_hash=manifest_hash,
    )


def run_baseline_a_okx_btc_usdt_1h_execution_gate_trace_research_for_okx_artifact(
    *,
    dataset: OkxHistoricalDataset,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    strategy_contract: BaselineAOkxBtcUsdtResearchContract | None = None,
    analyzed_at_utc: datetime | None = None,
    costs: ExecutionGateTraceCosts | None = None,
) -> ExecutionGateTraceReport:
    authorization = _require_authorization(authorization)
    compatibility_decision = _require_compatibility(compatibility_decision)
    if strategy_contract is None:
        strategy_contract = build_baseline_a_okx_btc_usdt_research_contract(authorization, compatibility_decision)
    strategy_contract = _require_strategy_contract(strategy_contract, authorization, compatibility_decision)
    if not isinstance(dataset, OkxHistoricalDataset):
        raise OfflineResearchExecutionGateDiagnosticValidationError("OKX historical dataset is required.")
    projected = _project_dataset_to_research_surface(dataset, symbol=strategy_contract.symbol)
    dataset_hash = dataset.manifest.dataset_hash
    manifest_hash = dataset.manifest.manifest_hash
    analyzed_at = _require_utc_datetime(analyzed_at_utc or authorization.issued_at_utc, "analyzed_at_utc")
    if costs is None:
        costs = ExecutionGateTraceCosts()
    from market_data.offline_research_backtest import _build_strategy_callable  # local import to keep scope explicit

    strategy_callable = _build_strategy_callable(
        authorization=authorization,
        compatibility_decision=compatibility_decision,
        strategy_contract=strategy_contract,
    )
    return _simulate_execution_gate_trace(
        projected,
        strategy_callable=strategy_callable,
        contract=build_baseline_a_okx_btc_usdt_1h_execution_gate_trace_contract(
            authorization,
            compatibility_decision,
            strategy_version=strategy_contract.strategy_version,
            costs=costs,
        ),
        analyzed_at_utc=analyzed_at,
        analysis_start_utc=dataset.manifest.first_candle_open_utc,
        analysis_end_utc=dataset.manifest.last_candle_close_utc,
        projected_symbol=strategy_contract.symbol,
        projected_source=DataSource.PAPER.value,
        dataset_hash=dataset_hash,
        manifest_hash=manifest_hash,
    )


def discover_okx_phase24_artifact_paths(root: str | Path | None = None) -> tuple[Path, Path]:
    return discover_okx_phase19a_artifact_paths(root=root)


def load_okx_phase24_trace_dataset(
    *,
    dataset_file: str | Path,
    manifest_file: str | Path,
) -> OkxHistoricalDataset:
    return load_okx_historical_dataset(dataset_file=dataset_file, manifest_file=manifest_file)


__all__ = [
    "BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_ALLOWED_GATES",
    "BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_ALLOWED_USE_CASES",
    "BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_DIAGNOSTIC_ID",
    "BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_DIAGNOSTIC_SCHEMA_VERSION",
    "BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_DIAGNOSTIC_VERSION",
    "BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_NON_OPERATIONAL_DECLARATION",
    "BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_PROHIBITED_USE_CASES",
    "BASELINE_A_OKX_BTC_USDT_1H_EXECUTION_GATE_TRACE_RESEARCH_PURPOSE",
    "ExecutionGateTraceContract",
    "ExecutionGateTraceCosts",
    "ExecutionGateTraceReport",
    "ExecutionGateTraceRecord",
    "OfflineResearchExecutionGateDiagnosticError",
    "OfflineResearchExecutionGateDiagnosticIntegrityError",
    "OfflineResearchExecutionGateDiagnosticValidationError",
    "build_baseline_a_okx_btc_usdt_1h_execution_gate_trace_contract",
    "discover_okx_phase24_artifact_paths",
    "load_okx_phase24_trace_dataset",
    "run_baseline_a_okx_btc_usdt_1h_execution_gate_trace_research",
    "run_baseline_a_okx_btc_usdt_1h_execution_gate_trace_research_for_okx_artifact",
]
