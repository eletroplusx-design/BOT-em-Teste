from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from domain import Candle, DataSource, Signal
from domain.serialization import serialize_value

from .offline_research_backtest import discover_okx_phase19a_artifact_paths
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
    BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_NO_SETUP,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_NON_OPERATIONAL_DECLARATION,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_PROHIBITED_USE_CASES,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_PURPOSE,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_ID,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_VERSION,
    BaselineAOkxBtcUsdtResearchContract,
    BaselineAOkxBtcUsdtResearchDecision,
    BaselineAOkxBtcUsdtResearchDecision,
    BaselineAOkxBtcUsdtResearchValidationError,
    build_baseline_a_okx_btc_usdt_research_contract,
    evaluate_baseline_a_okx_btc_usdt_research,
)

BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_SCHEMA_VERSION = 1
BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_ID = (
    "baseline_a_okx_btc_usdt_1h_signal_gap_diagnostic_research"
)
BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_VERSION = (
    "baseline_a_okx_btc_usdt_1h_signal_gap_diagnostic_research_v1"
)
BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_PURPOSE = "offline_historical_research"
BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_ALLOWED_USE_CASES: tuple[str, ...] = (
    BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_PURPOSE,
)
BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_PROHIBITED_USE_CASES: tuple[str, ...] = (
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
BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_NON_OPERATIONAL_DECLARATION = (
    "This signal-gap diagnostic is research-only and does not authorize replay, backtest, walk-forward, "
    "performance, ranking, paper trading, live trading, execution, or order submission."
)
BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_SETUP_GATES: tuple[str, ...] = (
    "warmup_complete",
    "bullish_trend",
    "bullish_pullback",
    "bullish_confirmation",
    "bullish_breakout",
    "recent_pullback_touch",
)
BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_REAL_GATES: tuple[str, ...] = (
    "contract_valid",
    "warmup_complete",
    "trend_alignment",
    "close_above_ema200",
    "ema50_rising",
    "close_above_ema20",
    "close_breaks_prior_high",
    "recent_pullback_touch",
    "atr_positive",
    "risk_targets_valid",
    "signal_emitted",
)


class OfflineResearchSignalGapDiagnosticError(Exception):
    pass


class OfflineResearchSignalGapDiagnosticValidationError(OfflineResearchSignalGapDiagnosticError):
    pass


class OfflineResearchSignalGapDiagnosticIntegrityError(OfflineResearchSignalGapDiagnosticError):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineResearchSignalGapDiagnosticValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineResearchSignalGapDiagnosticValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineResearchSignalGapDiagnosticValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchSignalGapDiagnosticValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineResearchSignalGapDiagnosticValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise OfflineResearchSignalGapDiagnosticValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise OfflineResearchSignalGapDiagnosticValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineResearchSignalGapDiagnosticValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _decimal_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


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
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "a verified offline research experiment authorization is required."
        )
    if authorization.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchSignalGapDiagnosticValidationError("authorization provider_name must be OKX.")
    if authorization.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchSignalGapDiagnosticValidationError("authorization market_type must be spot.")
    if authorization.instrument != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchSignalGapDiagnosticValidationError("authorization instrument must be BTC-USDT.")
    if authorization.symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchSignalGapDiagnosticValidationError("authorization symbol must be BTCUSDT.")
    if authorization.interval != "1H":
        raise OfflineResearchSignalGapDiagnosticValidationError("authorization interval must be 1H.")
    if authorization.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchSignalGapDiagnosticIntegrityError(
            "authorization requested_start_inclusive_utc diverges from the OKX research artifact."
        )
    if authorization.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise OfflineResearchSignalGapDiagnosticIntegrityError(
            "authorization requested_end_exclusive_utc diverges from the OKX research artifact."
        )
    if authorization.candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchSignalGapDiagnosticIntegrityError("authorization candle_count must be 42816.")
    if authorization.dataset_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256:
        raise OfflineResearchSignalGapDiagnosticIntegrityError(
            "authorization dataset_sha256 must match the OKX research artifact."
        )
    if authorization.manifest_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256:
        raise OfflineResearchSignalGapDiagnosticIntegrityError(
            "authorization manifest_sha256 must match the OKX research artifact."
        )
    if authorization.manifest_hash != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH:
        raise OfflineResearchSignalGapDiagnosticIntegrityError(
            "authorization manifest_hash must match the OKX research artifact."
        )
    if authorization.purpose != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PURPOSE:
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "authorization purpose must remain offline_historical_research."
        )
    if authorization.historical_research_only is not True:
        raise OfflineResearchSignalGapDiagnosticValidationError("historical_research_only must be true.")
    if authorization.operational_evidence is not False:
        raise OfflineResearchSignalGapDiagnosticValidationError("operational_evidence must be false.")
    if authorization.paper_promotion_eligible is not False:
        raise OfflineResearchSignalGapDiagnosticValidationError("paper_promotion_eligible must be false.")
    if authorization.allowed_use_cases not in ((), OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_ALLOWED_USE_CASES):
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "authorization allowed_use_cases diverges from the research-only contract."
        )
    if authorization.prohibited_use_cases != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PROHIBITED_USE_CASES:
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "authorization prohibited_use_cases diverge from the research-only contract."
        )
    if authorization.non_operational_declaration != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "authorization non_operational_declaration diverges from the research-only contract."
        )
    if not authorization.authorization_hash:
        raise OfflineResearchSignalGapDiagnosticIntegrityError("authorization_hash is required.")
    return authorization


def _require_compatibility(compatibility_decision: Any) -> OfflineResearchStrategyCompatibilityDecision:
    if not isinstance(compatibility_decision, OfflineResearchStrategyCompatibilityDecision):
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "a verified offline research compatibility decision is required."
        )
    if compatibility_decision.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchSignalGapDiagnosticValidationError("compatibility provider_name must be OKX.")
    if compatibility_decision.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchSignalGapDiagnosticValidationError("compatibility market_type must be spot.")
    if compatibility_decision.symbol != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchSignalGapDiagnosticValidationError("compatibility symbol must be BTC-USDT.")
    if compatibility_decision.canonical_symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchSignalGapDiagnosticValidationError("compatibility canonical_symbol must be BTCUSDT.")
    if compatibility_decision.interval != "1H":
        raise OfflineResearchSignalGapDiagnosticValidationError("compatibility interval must be 1H.")
    if compatibility_decision.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchSignalGapDiagnosticIntegrityError(
            "compatibility requested_start_inclusive_utc diverges from the OKX research artifact."
        )
    if compatibility_decision.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise OfflineResearchSignalGapDiagnosticIntegrityError(
            "compatibility requested_end_exclusive_utc diverges from the OKX research artifact."
        )
    if compatibility_decision.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchSignalGapDiagnosticIntegrityError("compatibility expected_candle_count must be 42816.")
    if compatibility_decision.required_dataset_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256:
        raise OfflineResearchSignalGapDiagnosticIntegrityError(
            "compatibility required_dataset_sha256 must match the OKX research artifact."
        )
    if compatibility_decision.required_manifest_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256:
        raise OfflineResearchSignalGapDiagnosticIntegrityError(
            "compatibility required_manifest_sha256 must match the OKX research artifact."
        )
    if compatibility_decision.required_manifest_hash != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH:
        raise OfflineResearchSignalGapDiagnosticIntegrityError(
            "compatibility required_manifest_hash must match the OKX research artifact."
        )
    if compatibility_decision.purpose != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PURPOSE:
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "compatibility purpose must remain offline_historical_research."
        )
    if compatibility_decision.historical_research_only is not True:
        raise OfflineResearchSignalGapDiagnosticValidationError("historical_research_only must be true.")
    if compatibility_decision.operational_evidence is not False:
        raise OfflineResearchSignalGapDiagnosticValidationError("operational_evidence must be false.")
    if compatibility_decision.paper_promotion_eligible is not False:
        raise OfflineResearchSignalGapDiagnosticValidationError("paper_promotion_eligible must be false.")
    if compatibility_decision.allowed_use_cases not in ((), OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES):
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "compatibility allowed_use_cases diverges from the research-only contract."
        )
    if compatibility_decision.prohibited_use_cases != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES:
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "compatibility prohibited_use_cases diverge from the research-only contract."
        )
    if compatibility_decision.non_operational_declaration != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "compatibility non_operational_declaration diverges from the research-only contract."
        )
    if not compatibility_decision.compatibility_hash:
        raise OfflineResearchSignalGapDiagnosticIntegrityError("compatibility_hash is required.")
    return compatibility_decision


def _require_strategy_contract(
    strategy_contract: Any,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
) -> BaselineAOkxBtcUsdtResearchContract:
    if not isinstance(strategy_contract, BaselineAOkxBtcUsdtResearchContract):
        raise OfflineResearchSignalGapDiagnosticValidationError("baseline A strategy contract is required.")
    if strategy_contract.strategy_id != BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_ID:
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "strategy_id must be baseline_a_okx_btc_usdt_1h_research."
        )
    if strategy_contract.strategy_version != BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_VERSION:
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "strategy_version must remain baseline_a_okx_btc_usdt_1h_research_v1."
        )
    if strategy_contract.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchSignalGapDiagnosticValidationError("strategy provider_name must be OKX.")
    if strategy_contract.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchSignalGapDiagnosticValidationError("strategy market_type must be spot.")
    if strategy_contract.symbol != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchSignalGapDiagnosticValidationError("strategy symbol must be BTC-USDT.")
    if strategy_contract.canonical_symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchSignalGapDiagnosticValidationError("strategy canonical_symbol must be BTCUSDT.")
    if strategy_contract.interval != "1H":
        raise OfflineResearchSignalGapDiagnosticValidationError("strategy interval must be 1H.")
    if strategy_contract.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchSignalGapDiagnosticIntegrityError(
            "strategy requested_start_inclusive_utc diverges from the OKX research artifact."
        )
    if strategy_contract.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise OfflineResearchSignalGapDiagnosticIntegrityError(
            "strategy requested_end_exclusive_utc diverges from the OKX research artifact."
        )
    if strategy_contract.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchSignalGapDiagnosticIntegrityError("strategy expected_candle_count must be 42816.")
    if strategy_contract.required_authorization_hash != authorization.authorization_hash:
        raise OfflineResearchSignalGapDiagnosticIntegrityError(
            "strategy required_authorization_hash diverges from the verified authorization."
        )
    if strategy_contract.required_compatibility_hash != compatibility_decision.compatibility_hash:
        raise OfflineResearchSignalGapDiagnosticIntegrityError(
            "strategy required_compatibility_hash diverges from the verified compatibility decision."
        )
    if strategy_contract.purpose != BASELINE_A_OKX_BTC_USDT_RESEARCH_PURPOSE:
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "strategy purpose must remain offline_historical_research."
        )
    if strategy_contract.historical_research_only is not True:
        raise OfflineResearchSignalGapDiagnosticValidationError("historical_research_only must be true.")
    if strategy_contract.operational_evidence is not False:
        raise OfflineResearchSignalGapDiagnosticValidationError("operational_evidence must be false.")
    if strategy_contract.paper_promotion_eligible is not False:
        raise OfflineResearchSignalGapDiagnosticValidationError("paper_promotion_eligible must be false.")
    if strategy_contract.allowed_use_cases != BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_ALLOWED_USE_CASES:
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "strategy allowed_use_cases must remain offline_historical_research."
        )
    if strategy_contract.prohibited_use_cases != BASELINE_A_OKX_BTC_USDT_RESEARCH_PROHIBITED_USE_CASES:
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "strategy prohibited_use_cases must block operational use cases."
        )
    if strategy_contract.allowed_decisions != BASELINE_A_OKX_BTC_USDT_RESEARCH_ALLOWED_DECISIONS:
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "strategy allowed_decisions must remain long_setup_detected or no_setup."
        )
    if strategy_contract.non_operational_declaration != BASELINE_A_OKX_BTC_USDT_RESEARCH_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "strategy non_operational_declaration diverges from the research-only contract."
        )
    if not strategy_contract.contract_hash:
        raise OfflineResearchSignalGapDiagnosticIntegrityError("strategy contract_hash is required.")
    return strategy_contract


def _seed_average(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _build_warmup_real_decision(
    *,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    strategy_contract: BaselineAOkxBtcUsdtResearchContract,
    analyzed_at_utc: datetime,
    candle_count: int,
) -> BaselineAOkxBtcUsdtResearchDecision:
    return BaselineAOkxBtcUsdtResearchDecision(
        strategy_id=strategy_contract.strategy_id,
        strategy_version=strategy_contract.strategy_version,
        decided_at_utc=analyzed_at_utc,
        decision=BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_NO_SETUP,
        authorization_hash=authorization.authorization_hash,
        compatibility_hash=compatibility_decision.compatibility_hash,
        contract_hash=strategy_contract.contract_hash,
        candle_count=candle_count,
        rejection_reason="candles are insufficient for the 1H trend contract.",
        historical_research_only=True,
        operational_evidence=False,
        paper_promotion_eligible=False,
    )


def _build_warmup_real_gate_results() -> dict[str, bool]:
    return {
        "contract_valid": True,
        "warmup_complete": False,
        "trend_alignment": True,
        "close_above_ema200": True,
        "ema50_rising": True,
        "close_above_ema20": True,
        "close_breaks_prior_high": True,
        "recent_pullback_touch": True,
        "atr_positive": True,
        "risk_targets_valid": True,
        "signal_emitted": False,
    }


@dataclass(frozen=True, slots=True)
class SignalGapDiagnosticContract:
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
        default_factory=lambda: BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_ALLOWED_USE_CASES
    )
    prohibited_use_cases: tuple[str, ...] = field(
        default_factory=lambda: BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_PROHIBITED_USE_CASES
    )
    non_operational_declaration: str = BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_NON_OPERATIONAL_DECLARATION
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
            raise OfflineResearchSignalGapDiagnosticValidationError("provider_name must be OKX.")
        if self.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
            raise OfflineResearchSignalGapDiagnosticValidationError("market_type must be spot.")
        if self.symbol != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
            raise OfflineResearchSignalGapDiagnosticValidationError("symbol must be BTC-USDT.")
        if self.canonical_symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
            raise OfflineResearchSignalGapDiagnosticValidationError("canonical_symbol must be BTCUSDT.")
        if self.interval != "1H":
            raise OfflineResearchSignalGapDiagnosticValidationError("interval must be 1H.")
        if self.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
            raise OfflineResearchSignalGapDiagnosticIntegrityError(
                "requested_start_inclusive_utc diverges from the OKX research artifact."
            )
        if self.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
            raise OfflineResearchSignalGapDiagnosticIntegrityError(
                "requested_end_exclusive_utc diverges from the OKX research artifact."
            )
        if self.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
            raise OfflineResearchSignalGapDiagnosticIntegrityError("expected_candle_count must be 42816.")
        if self.historical_research_only is not True:
            raise OfflineResearchSignalGapDiagnosticValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchSignalGapDiagnosticValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchSignalGapDiagnosticValidationError("paper_promotion_eligible must be false.")
        if self.allowed_use_cases != BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_ALLOWED_USE_CASES:
            raise OfflineResearchSignalGapDiagnosticValidationError("allowed_use_cases must remain offline_historical_research.")
        if self.prohibited_use_cases != BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_PROHIBITED_USE_CASES:
            raise OfflineResearchSignalGapDiagnosticValidationError("prohibited_use_cases must block operational use cases.")
        if self.non_operational_declaration != BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchSignalGapDiagnosticValidationError(
                "non_operational_declaration diverges from the research-only contract."
            )
        expected_hash = _hash_payload(self.canonical_payload(include_contract_hash=False))
        if self.contract_hash:
            if self.contract_hash != expected_hash:
                raise OfflineResearchSignalGapDiagnosticIntegrityError("contract_hash mismatch.")
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
        }
        if include_contract_hash:
            payload["contract_hash"] = self.contract_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_contract_hash=True))


@dataclass(frozen=True, slots=True)
class SignalGapDiagnosticRecord:
    candle_index: int
    open_time: datetime
    close_time: datetime
    close: Decimal
    high: Decimal
    low: Decimal
    previous_high: Decimal | None
    ema20: Decimal | None
    ema50: Decimal | None
    ema200: Decimal | None
    atr14: Decimal | None
    setup_gates: Mapping[str, bool]
    real_gates: Mapping[str, bool]
    setup_detected: bool
    signal_emitted: bool
    first_real_failed_gate: str | None
    failed_real_gates: tuple[str, ...]
    normalized_rejection_reason: str | None
    setup_reason: str | None
    signal_reason: str | None
    signal_side: str | None
    signal_entry: Decimal | None
    signal_stop_loss: Decimal | None
    signal_take_profit: Decimal | None
    signal_quantity: Decimal | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "candle_index": self.candle_index,
            "open_time": _utc_iso(self.open_time),
            "close_time": _utc_iso(self.close_time),
            "close": str(self.close),
            "high": str(self.high),
            "low": str(self.low),
            "previous_high": _decimal_str(self.previous_high),
            "ema20": _decimal_str(self.ema20),
            "ema50": _decimal_str(self.ema50),
            "ema200": _decimal_str(self.ema200),
            "atr14": _decimal_str(self.atr14),
            "setup_gates": dict(self.setup_gates),
            "real_gates": dict(self.real_gates),
            "setup_detected": self.setup_detected,
            "signal_emitted": self.signal_emitted,
            "first_real_failed_gate": self.first_real_failed_gate,
            "failed_real_gates": self.failed_real_gates,
            "normalized_rejection_reason": self.normalized_rejection_reason,
            "setup_reason": self.setup_reason,
            "signal_reason": self.signal_reason,
            "signal_side": self.signal_side,
            "signal_entry": _decimal_str(self.signal_entry),
            "signal_stop_loss": _decimal_str(self.signal_stop_loss),
            "signal_take_profit": _decimal_str(self.signal_take_profit),
            "signal_quantity": _decimal_str(self.signal_quantity),
        }


@dataclass(frozen=True, slots=True)
class SignalGapDiagnosticReport:
    contract: SignalGapDiagnosticContract
    analyzed_at_utc: datetime
    analysis_start_utc: datetime
    analysis_end_utc: datetime
    projected_symbol: str
    projected_source: str
    candles_total: int
    setup_candles: int
    signal_emitted_candles: int
    not_reached: int
    setup_gate_pass_counts: Mapping[str, int]
    setup_gate_fail_counts: Mapping[str, int]
    real_gate_pass_counts: Mapping[str, int]
    real_gate_fail_counts: Mapping[str, int]
    first_occurrences: Mapping[str, Any]
    primary_rejection_reason: str
    primary_rejection_reason_count: int
    conclusion: str
    signal_gap_records: tuple[SignalGapDiagnosticRecord, ...]
    dataset_hash: str
    manifest_hash: str
    report_notice: str = BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_NON_OPERATIONAL_DECLARATION
    report_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "analyzed_at_utc", _require_utc_datetime(self.analyzed_at_utc, "analyzed_at_utc"))
        object.__setattr__(self, "analysis_start_utc", _require_utc_datetime(self.analysis_start_utc, "analysis_start_utc"))
        object.__setattr__(self, "analysis_end_utc", _require_utc_datetime(self.analysis_end_utc, "analysis_end_utc"))
        object.__setattr__(self, "projected_symbol", _require_str(self.projected_symbol, "projected_symbol").upper())
        object.__setattr__(self, "projected_source", _require_str(self.projected_source, "projected_source"))
        object.__setattr__(self, "candles_total", _require_int(self.candles_total, "candles_total"))
        object.__setattr__(self, "setup_candles", _require_int(self.setup_candles, "setup_candles"))
        object.__setattr__(self, "signal_emitted_candles", _require_int(self.signal_emitted_candles, "signal_emitted_candles"))
        object.__setattr__(self, "not_reached", _require_int(self.not_reached, "not_reached"))
        object.__setattr__(self, "setup_gate_pass_counts", dict(self.setup_gate_pass_counts))
        object.__setattr__(self, "setup_gate_fail_counts", dict(self.setup_gate_fail_counts))
        object.__setattr__(self, "real_gate_pass_counts", dict(self.real_gate_pass_counts))
        object.__setattr__(self, "real_gate_fail_counts", dict(self.real_gate_fail_counts))
        object.__setattr__(self, "first_occurrences", dict(self.first_occurrences))
        object.__setattr__(self, "primary_rejection_reason", _require_str(self.primary_rejection_reason, "primary_rejection_reason"))
        object.__setattr__(self, "primary_rejection_reason_count", _require_int(self.primary_rejection_reason_count, "primary_rejection_reason_count"))
        object.__setattr__(self, "conclusion", _require_str(self.conclusion, "conclusion"))
        object.__setattr__(self, "signal_gap_records", tuple(self.signal_gap_records))
        object.__setattr__(self, "dataset_hash", _require_hex_digest(self.dataset_hash, "dataset_hash"))
        object.__setattr__(self, "manifest_hash", _require_hex_digest(self.manifest_hash, "manifest_hash"))
        object.__setattr__(self, "report_notice", _require_str(self.report_notice, "report_notice"))
        if self.report_notice != BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchSignalGapDiagnosticValidationError("report_notice must remain research-only.")
        expected_hash = _hash_payload(self.canonical_payload(include_report_hash=False))
        if self.report_hash:
            if self.report_hash != expected_hash:
                raise OfflineResearchSignalGapDiagnosticIntegrityError("report_hash mismatch.")
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
            "setup_candles": self.setup_candles,
            "signal_emitted_candles": self.signal_emitted_candles,
            "not_reached": self.not_reached,
            "setup_gate_pass_counts": dict(sorted(self.setup_gate_pass_counts.items())),
            "setup_gate_fail_counts": dict(sorted(self.setup_gate_fail_counts.items())),
            "real_gate_pass_counts": dict(sorted(self.real_gate_pass_counts.items())),
            "real_gate_fail_counts": dict(sorted(self.real_gate_fail_counts.items())),
            "first_occurrences": dict(sorted(self.first_occurrences.items())),
            "primary_rejection_reason": self.primary_rejection_reason,
            "primary_rejection_reason_count": self.primary_rejection_reason_count,
            "conclusion": self.conclusion,
            "signal_gap_records": [record.as_dict() for record in self.signal_gap_records],
            "dataset_hash": self.dataset_hash,
            "manifest_hash": self.manifest_hash,
            "report_notice": self.report_notice,
        }
        if include_report_hash:
            payload["report_hash"] = self.report_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_report_hash=True))


def build_baseline_a_okx_btc_usdt_1h_signal_gap_diagnostic_contract(
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    *,
    strategy_version: str = BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_VERSION,
    contract_hash: str = "",
) -> SignalGapDiagnosticContract:
    if not isinstance(authorization, OfflineResearchExperimentAuthorization):
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "authorization must be a verified offline research experiment authorization."
        )
    if not isinstance(compatibility_decision, OfflineResearchStrategyCompatibilityDecision):
        raise OfflineResearchSignalGapDiagnosticValidationError(
            "compatibility_decision must be a verified offline compatibility decision."
        )
    strategy_contract = build_baseline_a_okx_btc_usdt_research_contract(
        authorization,
        compatibility_decision,
        strategy_version=strategy_version,
    )
    return SignalGapDiagnosticContract(
        schema_version=BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_SCHEMA_VERSION,
        diagnostic_id=BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_ID,
        diagnostic_version=BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_VERSION,
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
        contract_hash=contract_hash,
    )


def _indicator_step(
    state: dict[str, Any],
    candle: Candle,
    *,
    pullback_lookback: int,
    fast_period: int,
    mid_period: int,
    slow_period: int,
    atr_period: int,
) -> dict[str, Any]:
    closes: list[Decimal] = state["closes"]
    true_ranges: list[Decimal] = state["true_ranges"]
    ema20 = state["ema20"]
    ema50 = state["ema50"]
    ema200 = state["ema200"]
    prev_ema50 = state["prev_ema50"]
    atr14 = state["atr14"]
    previous_candle: Candle | None = state["previous_candle"]
    recent_pullbacks: deque[bool] = state["recent_pullbacks"]

    closes.append(candle.close)
    if previous_candle is None:
        true_range = candle.high - candle.low
    else:
        true_range = max(
            candle.high - candle.low,
            abs(candle.high - previous_candle.close),
            abs(candle.low - previous_candle.close),
        )
    true_ranges.append(true_range)

    if len(closes) == fast_period:
        ema20 = _seed_average(closes[:fast_period])
    elif len(closes) > fast_period and ema20 is not None:
        alpha = Decimal("2") / Decimal(fast_period + 1)
        ema20 = (candle.close * alpha) + (ema20 * (Decimal("1") - alpha))

    if len(closes) == mid_period:
        prev_ema50 = ema50
        ema50 = _seed_average(closes[:mid_period])
    elif len(closes) > mid_period and ema50 is not None:
        prev_ema50 = ema50
        alpha = Decimal("2") / Decimal(mid_period + 1)
        ema50 = (candle.close * alpha) + (ema50 * (Decimal("1") - alpha))
    else:
        prev_ema50 = ema50

    if len(closes) == slow_period:
        ema200 = _seed_average(closes[:slow_period])
    elif len(closes) > slow_period and ema200 is not None:
        alpha = Decimal("2") / Decimal(slow_period + 1)
        ema200 = (candle.close * alpha) + (ema200 * (Decimal("1") - alpha))

    if len(true_ranges) == atr_period:
        atr14 = _seed_average(true_ranges[:atr_period])
    elif len(true_ranges) > atr_period and atr14 is not None:
        atr14 = ((atr14 * Decimal(atr_period - 1)) + true_range) / Decimal(atr_period)

    recent_pullbacks.append(bool(ema20 is not None and candle.low <= ema20))
    state["ema20"] = ema20
    state["ema50"] = ema50
    state["ema200"] = ema200
    state["prev_ema50"] = prev_ema50
    state["atr14"] = atr14
    state["previous_candle"] = candle
    return {
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "prev_ema50": prev_ema50,
        "atr14": atr14,
        "recent_pullback_touch": any(recent_pullbacks),
        "insufficient": (
            len(closes) < mid_period + 1
            or ema20 is None
            or ema50 is None
            or ema200 is None
            or prev_ema50 is None
            or atr14 is None
            or len(recent_pullbacks) < pullback_lookback
        ),
    }


def _build_setup_gate_results(
    *,
    candle: Candle,
    previous_candle: Candle | None,
    indicators: Mapping[str, Any],
) -> dict[str, bool]:
    ema20 = indicators["ema20"]
    ema50 = indicators["ema50"]
    ema200 = indicators["ema200"]
    prev_ema50 = indicators["prev_ema50"]
    atr14 = indicators["atr14"]
    recent_pullback_touch = bool(indicators["recent_pullback_touch"])
    warmup_complete = not bool(indicators["insufficient"])
    bullish_trend = bool(warmup_complete and ema50 is not None and ema200 is not None and ema50 > ema200)
    bullish_pullback = bool(bullish_trend and candle.close > ema200)
    bullish_confirmation = bool(bullish_pullback and prev_ema50 is not None and ema50 > prev_ema50)
    bullish_reclaim = bool(bullish_confirmation and ema20 is not None and candle.close > ema20)
    bullish_breakout = bool(
        bullish_reclaim and previous_candle is not None and candle.close > previous_candle.high
    )
    return {
        "warmup_complete": warmup_complete,
        "bullish_trend": bullish_trend,
        "bullish_pullback": bullish_pullback,
        "bullish_confirmation": bullish_confirmation,
        "bullish_breakout": bullish_breakout,
        "recent_pullback_touch": recent_pullback_touch,
    }


def _build_real_gate_results(
    *,
    candle: Candle,
    previous_candle: Candle | None,
    indicators: Mapping[str, Any],
) -> dict[str, bool]:
    ema20 = indicators["ema20"]
    ema50 = indicators["ema50"]
    ema200 = indicators["ema200"]
    prev_ema50 = indicators["prev_ema50"]
    atr14 = indicators["atr14"]
    recent_pullback_touch = bool(indicators["recent_pullback_touch"])
    warmup_complete = not bool(indicators["insufficient"])
    trend_alignment = bool(warmup_complete and ema50 is not None and ema200 is not None and ema50 > ema200)
    close_above_ema200 = bool(trend_alignment and candle.close > ema200)
    ema50_rising = bool(close_above_ema200 and prev_ema50 is not None and ema50 > prev_ema50)
    close_above_ema20 = bool(ema50_rising and ema20 is not None and candle.close > ema20)
    close_breaks_prior_high = bool(
        close_above_ema20 and previous_candle is not None and candle.close > previous_candle.high
    )
    atr_positive = bool(atr14 is not None and atr14 > 0)
    if not (close_breaks_prior_high and recent_pullback_touch and atr_positive):
        risk_targets_valid = False
    else:
        entry = candle.close
        stop_loss = entry - (Decimal("1.5") * atr14)
        take_profit = entry + ((entry - stop_loss) * Decimal("2"))
        risk_targets_valid = bool(stop_loss < entry and take_profit > entry)
    return {
        "contract_valid": True,
        "warmup_complete": warmup_complete,
        "trend_alignment": trend_alignment,
        "close_above_ema200": close_above_ema200,
        "ema50_rising": ema50_rising,
        "close_above_ema20": close_above_ema20,
        "close_breaks_prior_high": close_breaks_prior_high,
        "recent_pullback_touch": recent_pullback_touch,
        "atr_positive": atr_positive,
        "risk_targets_valid": risk_targets_valid,
        "signal_emitted": risk_targets_valid,
    }


def _gate_failures_in_order(gates: Mapping[str, bool], order: Sequence[str]) -> tuple[str, ...]:
    return tuple(name for name in order if not gates.get(name, False))


def _first_failure_reason(failures: Sequence[str]) -> str | None:
    if not failures:
        return None
    return failures[0]


def _normalized_failure_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    mapping = {
        "warmup_complete": "insufficient_history_for_signal_emission",
        "bullish_trend": "ema50_not_above_ema200",
        "bullish_pullback": "close_not_above_ema200",
        "bullish_confirmation": "ema50_not_rising",
        "bullish_breakout": "breakout_not_confirmed",
        "recent_pullback_touch": "no_recent_pullback_touch",
        "atr_positive": "atr_not_positive",
        "risk_targets_valid": "risk_targets_invalid",
        "signal_emitted": "signal_not_emitted",
    }
    return mapping.get(reason, reason)


def analyze_baseline_a_okx_btc_usdt_1h_signal_gap_research(
    candles: Sequence[Candle],
    *,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    strategy_contract: BaselineAOkxBtcUsdtResearchContract | None = None,
    analyzed_at_utc: datetime | None = None,
) -> SignalGapDiagnosticReport:
    authorization = _require_authorization(authorization)
    compatibility_decision = _require_compatibility(compatibility_decision)
    if strategy_contract is None:
        strategy_contract = build_baseline_a_okx_btc_usdt_research_contract(authorization, compatibility_decision)
    strategy_contract = _require_strategy_contract(strategy_contract, authorization, compatibility_decision)
    history = tuple(candles)
    if not history:
        raise OfflineResearchSignalGapDiagnosticValidationError("candles must not be empty.")
    analyzed_at = _require_utc_datetime(analyzed_at_utc or authorization.issued_at_utc, "analyzed_at_utc")

    state: dict[str, Any] = {
        "closes": [],
        "true_ranges": [],
        "ema20": None,
        "ema50": None,
        "ema200": None,
        "prev_ema50": None,
        "atr14": None,
        "previous_candle": None,
        "recent_pullbacks": deque(maxlen=strategy_contract.pullback_lookback),
    }
    setup_pass_counts: Counter[str] = Counter()
    setup_fail_counts: Counter[str] = Counter()
    real_pass_counts: Counter[str] = Counter()
    real_fail_counts: Counter[str] = Counter()
    first_occurrences: dict[str, Any] = {}
    signal_gap_records: list[SignalGapDiagnosticRecord] = []
    setup_candles = 0
    signal_emitted_candles = 0
    not_reached = 0
    first_gap_found = False
    real_failure_frequency: Counter[str] = Counter()

    for index, candle in enumerate(history):
        previous_candle = state["previous_candle"]
        indicators = _indicator_step(
            state,
            candle,
            pullback_lookback=strategy_contract.pullback_lookback,
            fast_period=strategy_contract.trend_fast_ema_period,
            mid_period=strategy_contract.trend_mid_ema_period,
            slow_period=strategy_contract.trend_slow_ema_period,
            atr_period=strategy_contract.atr_period,
        )
        setup_gates = _build_setup_gate_results(candle=candle, previous_candle=previous_candle, indicators=indicators)
        setup_detected = all(setup_gates.values())
        if index + 1 < strategy_contract.minimum_candles_required:
            real_gates = _build_warmup_real_gate_results()
        else:
            real_gates = _build_real_gate_results(
                candle=candle,
                previous_candle=previous_candle,
                indicators=indicators,
            )
        real_failures = _gate_failures_in_order(real_gates, BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_REAL_GATES)
        real_failure_reason = _first_failure_reason(real_failures)
        normalized_reason = _normalized_failure_reason(real_failure_reason)
        signal_emitted = bool(real_gates["signal_emitted"])
        if setup_detected:
            setup_candles += 1
        if signal_emitted:
            signal_emitted_candles += 1
        if not setup_detected and not signal_emitted and index < strategy_contract.minimum_candles_required:
            not_reached += 1

        for gate_name, passed in setup_gates.items():
            if passed:
                setup_pass_counts[gate_name] += 1
            else:
                setup_fail_counts[gate_name] += 1
        for gate_name, passed in real_gates.items():
            if passed:
                real_pass_counts[gate_name] += 1
            else:
                real_fail_counts[gate_name] += 1

        if real_failure_reason is not None:
            real_failure_frequency[normalized_reason or real_failure_reason] += 1

        if setup_detected and "first_setup_detected" not in first_occurrences:
            first_occurrences["first_setup_detected"] = {
                "candle_index": index,
                "open_time": _utc_iso(candle.open_time),
                "reason": BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_LONG_SETUP_DETECTED,
            }
        if signal_emitted and "first_signal_emitted" not in first_occurrences:
            first_occurrences["first_signal_emitted"] = {
                "candle_index": index,
                "open_time": _utc_iso(candle.open_time),
                "reason": BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_LONG_SETUP_DETECTED,
            }
        if setup_detected and not signal_emitted and not first_gap_found:
            first_occurrences["first_setup_without_signal"] = {
                "candle_index": index,
                "open_time": _utc_iso(candle.open_time),
                "setup_reason": BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_LONG_SETUP_DETECTED,
                "first_real_failed_gate": real_failure_reason,
                "normalized_rejection_reason": normalized_reason,
            }
            first_gap_found = True
        if real_failure_reason is not None and f"first_real_failure_{normalized_reason or real_failure_reason}" not in first_occurrences:
            first_occurrences[f"first_real_failure_{normalized_reason or real_failure_reason}"] = {
                "candle_index": index,
                "open_time": _utc_iso(candle.open_time),
                "reason": normalized_reason or real_failure_reason,
            }

        if index + 1 >= strategy_contract.minimum_candles_required or setup_detected or signal_emitted or first_gap_found:
            signal_gap_records.append(
                SignalGapDiagnosticRecord(
                    candle_index=index,
                    open_time=candle.open_time,
                    close_time=candle.close_time,
                    close=candle.close,
                    high=candle.high,
                    low=candle.low,
                    previous_high=previous_candle.high if previous_candle is not None else None,
                    ema20=indicators["ema20"],
                    ema50=indicators["ema50"],
                    ema200=indicators["ema200"],
                    atr14=indicators["atr14"],
                    setup_gates=dict(setup_gates),
                    real_gates=dict(real_gates),
                    setup_detected=setup_detected,
                    signal_emitted=signal_emitted,
                    first_real_failed_gate=real_failure_reason,
                    failed_real_gates=real_failures,
                    normalized_rejection_reason=normalized_reason,
                    setup_reason=BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_LONG_SETUP_DETECTED if setup_detected else None,
                    signal_reason=BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_LONG_SETUP_DETECTED if signal_emitted else None,
                    signal_side="LONG" if signal_emitted else None,
                    signal_entry=candle.close if signal_emitted else None,
                    signal_stop_loss=(candle.close - (Decimal("1.5") * indicators["atr14"])) if signal_emitted else None,
                    signal_take_profit=(
                        candle.close
                        + (
                            (Decimal("1.5") * indicators["atr14"]) * Decimal("2")
                        )
                    )
                    if signal_emitted
                    else None,
                    signal_quantity=None,
                )
            )

    if not signal_gap_records and history:
        not_reached = len(history)
        first_occurrences["first_not_reached"] = {
            "candle_index": 0,
            "open_time": _utc_iso(history[0].open_time),
            "reason": "signal_not_emitted",
        }

    primary_reason = "no_executable_signals"
    primary_reason_count = 0
    if signal_gap_records:
        primary_reason = signal_gap_records[0].first_real_failed_gate or primary_reason
        primary_reason_count = int(real_fail_counts.get(primary_reason, 0))
    conclusion = (
        "the first post-warm-up gate that blocks signal emission is trend_alignment "
        "(ema50 must be above ema200)."
        if primary_reason == "trend_alignment"
        else "the strategy does not produce an executable signal on the inspected artifact."
    )

    report = SignalGapDiagnosticReport(
        contract=build_baseline_a_okx_btc_usdt_1h_signal_gap_diagnostic_contract(
            authorization,
            compatibility_decision,
            strategy_version=strategy_contract.strategy_version,
        ),
        analyzed_at_utc=analyzed_at,
        analysis_start_utc=history[0].open_time,
        analysis_end_utc=history[-1].close_time,
        projected_symbol=strategy_contract.symbol,
        projected_source=DataSource.PAPER.value,
        candles_total=len(history),
        setup_candles=setup_candles,
        signal_emitted_candles=signal_emitted_candles,
        not_reached=not_reached,
        setup_gate_pass_counts=dict(sorted(setup_pass_counts.items())),
        setup_gate_fail_counts=dict(sorted(setup_fail_counts.items())),
        real_gate_pass_counts=dict(sorted(real_pass_counts.items())),
        real_gate_fail_counts=dict(sorted(real_fail_counts.items())),
        first_occurrences=dict(sorted(first_occurrences.items())),
        primary_rejection_reason=primary_reason,
        primary_rejection_reason_count=primary_reason_count,
        conclusion=conclusion,
        signal_gap_records=tuple(signal_gap_records),
        dataset_hash=authorization.dataset_sha256,
        manifest_hash=authorization.manifest_sha256,
    )
    if report.as_dict() != serialize_value(report.canonical_payload()):
        raise OfflineResearchSignalGapDiagnosticIntegrityError("diagnostic payload mismatch.")
    return report


def analyze_baseline_a_okx_btc_usdt_1h_signal_gap_research_for_okx_artifact(
    *,
    dataset: OkxHistoricalDataset,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    strategy_contract: BaselineAOkxBtcUsdtResearchContract | None = None,
    analyzed_at_utc: datetime | None = None,
) -> SignalGapDiagnosticReport:
    authorization = _require_authorization(authorization)
    compatibility_decision = _require_compatibility(compatibility_decision)
    if strategy_contract is None:
        strategy_contract = build_baseline_a_okx_btc_usdt_research_contract(authorization, compatibility_decision)
    strategy_contract = _require_strategy_contract(strategy_contract, authorization, compatibility_decision)
    if not isinstance(dataset, OkxHistoricalDataset):
        raise OfflineResearchSignalGapDiagnosticValidationError("OKX historical dataset is required.")
    projected = _project_dataset_to_research_surface(dataset, symbol=strategy_contract.symbol)
    return analyze_baseline_a_okx_btc_usdt_1h_signal_gap_research(
        projected,
        authorization=authorization,
        compatibility_decision=compatibility_decision,
        strategy_contract=strategy_contract,
        analyzed_at_utc=analyzed_at_utc,
    )


def discover_okx_phase26_artifact_paths(root: str | Path | None = None) -> tuple[Path, Path]:
    return discover_okx_phase19a_artifact_paths(root=root)


def load_okx_phase26_gap_dataset(
    *,
    dataset_file: str | Path,
    manifest_file: str | Path,
) -> OkxHistoricalDataset:
    return load_okx_historical_dataset(dataset_file=dataset_file, manifest_file=manifest_file)


__all__ = [
    "BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_ALLOWED_USE_CASES",
    "BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_ID",
    "BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_NON_OPERATIONAL_DECLARATION",
    "BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_PROHIBITED_USE_CASES",
    "BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_PURPOSE",
    "BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_REAL_GATES",
    "BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_SCHEMA_VERSION",
    "BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_SETUP_GATES",
    "BASELINE_A_OKX_BTC_USDT_1H_SIGNAL_GAP_DIAGNOSTIC_VERSION",
    "OfflineResearchSignalGapDiagnosticError",
    "OfflineResearchSignalGapDiagnosticIntegrityError",
    "OfflineResearchSignalGapDiagnosticValidationError",
    "SignalGapDiagnosticContract",
    "SignalGapDiagnosticRecord",
    "SignalGapDiagnosticReport",
    "analyze_baseline_a_okx_btc_usdt_1h_signal_gap_research",
    "analyze_baseline_a_okx_btc_usdt_1h_signal_gap_research_for_okx_artifact",
    "build_baseline_a_okx_btc_usdt_1h_signal_gap_diagnostic_contract",
    "discover_okx_phase26_artifact_paths",
    "load_okx_phase26_gap_dataset",
]
