from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from domain import Candle, DataSource
from domain.serialization import serialize_value

from strategies.baseline_a_okx_btc_usdt_research import (
    BASELINE_A_OKX_BTC_USDT_RESEARCH_ALLOWED_DECISIONS,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_ALLOWED_USE_CASES,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_LONG_SETUP_DETECTED,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_NON_OPERATIONAL_DECLARATION,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_PROHIBITED_USE_CASES,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_PURPOSE,
    BaselineAOkxBtcUsdtResearchContract,
    BaselineAOkxBtcUsdtResearchValidationError,
    build_baseline_a_okx_btc_usdt_research_contract,
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
    OfflineResearchStrategyCompatibilityDecision,
)
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
from .okx_historical import OkxHistoricalDataset

OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_SCHEMA_VERSION = 1
OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_ID = "phase22c_zero_trade_signal_diagnostic"
OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_VERSION = "phase22c_zero_trade_signal_diagnostic_v1"
OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_PURPOSE = "offline_historical_research"
OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_ALLOWED_USE_CASES: tuple[str, ...] = (
    "offline_historical_research",
)
OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_PROHIBITED_USE_CASES: tuple[str, ...] = (
    "replay",
    "walk_forward",
    "performance",
    "ranking",
    "paper",
    "live",
    "execution",
    "order_submission",
)
OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_NON_OPERATIONAL_DECLARATION = (
    "Diagnóstico exclusivo para pesquisa histórica offline. Não constitui evidência operacional, não altera a estratégia e não autoriza paper ou live."
)
OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_BULLISH_TREND_REJECTION = "ema50_must_be_above_ema200"
OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_BULLISH_CONTINUATION_REJECTION = "bullish_sequence_not_completed"
OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_BEARISH_TREND_REJECTION = "ema50_must_be_below_ema200"
OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_BEARISH_CONTINUATION_REJECTION = "bearish_sequence_not_completed"
ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)


class OfflineResearchSignalDiagnosticError(Exception):
    pass


class OfflineResearchSignalDiagnosticValidationError(OfflineResearchSignalDiagnosticError):
    pass


class OfflineResearchSignalDiagnosticIntegrityError(OfflineResearchSignalDiagnosticError):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineResearchSignalDiagnosticValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchSignalDiagnosticValidationError(f"{field_name} must be a 64-character hex digest.")
    return digest


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineResearchSignalDiagnosticValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineResearchSignalDiagnosticValidationError(f"{field_name} must be a boolean.")
    return value


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineResearchSignalDiagnosticValidationError(f"{field_name} must be timezone-aware UTC datetime.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise OfflineResearchSignalDiagnosticValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise OfflineResearchSignalDiagnosticValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineResearchSignalDiagnosticValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _require_candle_sequence(candles: Sequence[Candle], *, symbol: str, interval: str) -> tuple[Candle, ...]:
    if not isinstance(candles, Sequence):
        raise OfflineResearchSignalDiagnosticValidationError("candles are required.")
    items = tuple(candles)
    previous_open_time: datetime | None = None
    previous_candle: Candle | None = None
    for candle in items:
        if not isinstance(candle, Candle):
            raise OfflineResearchSignalDiagnosticValidationError("candles must contain Candle instances.")
        if candle.symbol != symbol:
            raise OfflineResearchSignalDiagnosticValidationError("candles must use BTC-USDT.")
        if candle.interval != interval:
            raise OfflineResearchSignalDiagnosticValidationError("candles must use 1H.")
        if candle.source != DataSource.PAPER:
            raise OfflineResearchSignalDiagnosticValidationError("candles must remain synthetic PAPER candles.")
        if candle.close_time - candle.open_time != ONE_HOUR - ONE_MS:
            raise OfflineResearchSignalDiagnosticValidationError("candles must span exactly one 1H bar.")
        if candle.high < candle.low:
            raise OfflineResearchSignalDiagnosticValidationError("candles must have high >= low.")
        if candle.high < candle.close or candle.high < candle.open:
            raise OfflineResearchSignalDiagnosticValidationError("candles must keep high above open and close.")
        if candle.low > candle.close or candle.low > candle.open:
            raise OfflineResearchSignalDiagnosticValidationError("candles must keep low below open and close.")
        if previous_open_time is not None:
            if candle.open_time - previous_open_time != ONE_HOUR:
                raise OfflineResearchSignalDiagnosticValidationError(
                    "candles must be contiguous 1H bars without gaps or duplicates."
                )
        previous_open_time = candle.open_time
        previous_candle = candle
    return items


def _normalize_use_cases(value: Sequence[str] | None, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_ALLOWED_USE_CASES
    return tuple(dict.fromkeys(_require_str(item, field_name).lower() for item in value))


def _snapshot_payload(
    *,
    candle_index: int,
    candle: Candle,
    ema20: Decimal | None,
    ema50: Decimal | None,
    ema200: Decimal | None,
    atr14: Decimal | None,
    previous_candle: Candle | None,
    reason: str,
) -> dict[str, Any]:
    return {
        "candle_index": candle_index,
        "open_time": _utc_iso(candle.open_time),
        "close_time": _utc_iso(candle.close_time),
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "ema20": str(ema20) if ema20 is not None else None,
        "ema50": str(ema50) if ema50 is not None else None,
        "ema200": str(ema200) if ema200 is not None else None,
        "atr14": str(atr14) if atr14 is not None else None,
        "previous_high": str(previous_candle.high) if previous_candle is not None else None,
        "previous_low": str(previous_candle.low) if previous_candle is not None else None,
        "reason": reason,
    }


@dataclass(frozen=True, slots=True)
class OfflineResearchSignalDiagnosticReport:
    schema_version: int
    diagnostic_id: str
    diagnostic_version: str
    analyzed_at_utc: datetime
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
    dataset_hash: str
    manifest_hash: str
    candles_total: int
    candles_structurally_invalid: int
    candles_insufficient: int
    bullish_trend_candles: int
    bearish_trend_candles: int
    bullish_pullback_candles: int
    bearish_pullback_candles: int
    bullish_confirmation_candles: int
    bearish_confirmation_candles: int
    long_setups: int
    short_setups: int
    long_rejection_counts: Mapping[str, int]
    short_rejection_counts: Mapping[str, int]
    first_occurrences: Mapping[str, Any]
    primary_rejection_reason: str
    primary_rejection_reason_count: int
    conclusion: str
    report_notice: str = OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_NON_OPERATIONAL_DECLARATION
    diagnostic_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "diagnostic_id", _require_str(self.diagnostic_id, "diagnostic_id"))
        object.__setattr__(self, "diagnostic_version", _require_str(self.diagnostic_version, "diagnostic_version"))
        object.__setattr__(self, "analyzed_at_utc", _require_utc_datetime(self.analyzed_at_utc, "analyzed_at_utc"))
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
        object.__setattr__(self, "dataset_hash", _require_hex_digest(self.dataset_hash, "dataset_hash"))
        object.__setattr__(self, "manifest_hash", _require_hex_digest(self.manifest_hash, "manifest_hash"))
        object.__setattr__(self, "candles_total", _require_int(self.candles_total, "candles_total"))
        object.__setattr__(self, "candles_structurally_invalid", _require_int(self.candles_structurally_invalid, "candles_structurally_invalid"))
        object.__setattr__(self, "candles_insufficient", _require_int(self.candles_insufficient, "candles_insufficient"))
        object.__setattr__(self, "bullish_trend_candles", _require_int(self.bullish_trend_candles, "bullish_trend_candles"))
        object.__setattr__(self, "bearish_trend_candles", _require_int(self.bearish_trend_candles, "bearish_trend_candles"))
        object.__setattr__(self, "bullish_pullback_candles", _require_int(self.bullish_pullback_candles, "bullish_pullback_candles"))
        object.__setattr__(self, "bearish_pullback_candles", _require_int(self.bearish_pullback_candles, "bearish_pullback_candles"))
        object.__setattr__(self, "bullish_confirmation_candles", _require_int(self.bullish_confirmation_candles, "bullish_confirmation_candles"))
        object.__setattr__(self, "bearish_confirmation_candles", _require_int(self.bearish_confirmation_candles, "bearish_confirmation_candles"))
        object.__setattr__(self, "long_setups", _require_int(self.long_setups, "long_setups"))
        object.__setattr__(self, "short_setups", _require_int(self.short_setups, "short_setups"))
        object.__setattr__(self, "long_rejection_counts", dict(self.long_rejection_counts))
        object.__setattr__(self, "short_rejection_counts", dict(self.short_rejection_counts))
        object.__setattr__(self, "first_occurrences", dict(self.first_occurrences))
        object.__setattr__(self, "primary_rejection_reason", _require_str(self.primary_rejection_reason, "primary_rejection_reason"))
        object.__setattr__(self, "primary_rejection_reason_count", _require_int(self.primary_rejection_reason_count, "primary_rejection_reason_count"))
        object.__setattr__(self, "conclusion", _require_str(self.conclusion, "conclusion"))
        object.__setattr__(self, "report_notice", _require_str(self.report_notice, "report_notice"))
        if self.schema_version != OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_SCHEMA_VERSION:
            raise OfflineResearchSignalDiagnosticValidationError("schema_version must be 1.")
        if self.diagnostic_id != OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_ID:
            raise OfflineResearchSignalDiagnosticValidationError("diagnostic_id must remain phase22c_zero_trade_signal_diagnostic.")
        if self.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
            raise OfflineResearchSignalDiagnosticValidationError("provider_name must be OKX.")
        if self.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
            raise OfflineResearchSignalDiagnosticValidationError("market_type must be spot.")
        if self.symbol != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
            raise OfflineResearchSignalDiagnosticValidationError("symbol must be BTC-USDT.")
        if self.canonical_symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
            raise OfflineResearchSignalDiagnosticValidationError("canonical_symbol must be BTCUSDT.")
        if self.interval != "1H":
            raise OfflineResearchSignalDiagnosticValidationError("interval must be 1H.")
        if self.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
            raise OfflineResearchSignalDiagnosticIntegrityError("requested_start_inclusive_utc diverges from the OKX research artifact.")
        if self.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
            raise OfflineResearchSignalDiagnosticIntegrityError("requested_end_exclusive_utc diverges from the OKX research artifact.")
        if self.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
            raise OfflineResearchSignalDiagnosticIntegrityError("expected_candle_count must be 42816.")
        if self.long_setups < 0 or self.short_setups < 0:
            raise OfflineResearchSignalDiagnosticValidationError("setup counts cannot be negative.")
        expected_hash = _hash_payload(self.canonical_payload(include_diagnostic_hash=False))
        if self.diagnostic_hash:
            if self.diagnostic_hash != expected_hash:
                raise OfflineResearchSignalDiagnosticIntegrityError("diagnostic_hash mismatch.")
        else:
            object.__setattr__(self, "diagnostic_hash", expected_hash)

    def canonical_payload(self, *, include_diagnostic_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "diagnostic_id": self.diagnostic_id,
            "diagnostic_version": self.diagnostic_version,
            "analyzed_at_utc": _utc_iso(self.analyzed_at_utc),
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
            "dataset_hash": self.dataset_hash,
            "manifest_hash": self.manifest_hash,
            "candles_total": self.candles_total,
            "candles_structurally_invalid": self.candles_structurally_invalid,
            "candles_insufficient": self.candles_insufficient,
            "bullish_trend_candles": self.bullish_trend_candles,
            "bearish_trend_candles": self.bearish_trend_candles,
            "bullish_pullback_candles": self.bullish_pullback_candles,
            "bearish_pullback_candles": self.bearish_pullback_candles,
            "bullish_confirmation_candles": self.bullish_confirmation_candles,
            "bearish_confirmation_candles": self.bearish_confirmation_candles,
            "long_setups": self.long_setups,
            "short_setups": self.short_setups,
            "long_rejection_counts": dict(sorted(self.long_rejection_counts.items())),
            "short_rejection_counts": dict(sorted(self.short_rejection_counts.items())),
            "first_occurrences": self.first_occurrences,
            "primary_rejection_reason": self.primary_rejection_reason,
            "primary_rejection_reason_count": self.primary_rejection_reason_count,
            "conclusion": self.conclusion,
            "report_notice": self.report_notice,
        }
        if include_diagnostic_hash:
            payload["diagnostic_hash"] = self.diagnostic_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_diagnostic_hash=True))


def _require_authorization(authorization: OfflineResearchExperimentAuthorization) -> OfflineResearchExperimentAuthorization:
    if not isinstance(authorization, OfflineResearchExperimentAuthorization):
        raise OfflineResearchSignalDiagnosticValidationError("a verified offline research experiment authorization is required.")
    if authorization.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchSignalDiagnosticValidationError("authorization provider_name must be OKX.")
    if authorization.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchSignalDiagnosticValidationError("authorization market_type must be spot.")
    if authorization.instrument != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchSignalDiagnosticValidationError("authorization instrument must be BTC-USDT.")
    if authorization.symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchSignalDiagnosticValidationError("authorization symbol must be BTCUSDT.")
    if authorization.interval != "1H":
        raise OfflineResearchSignalDiagnosticValidationError("authorization interval must be 1H.")
    if authorization.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchSignalDiagnosticIntegrityError(
            "authorization requested_start_inclusive_utc diverges from the OKX research artifact."
        )
    if authorization.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise OfflineResearchSignalDiagnosticIntegrityError(
            "authorization requested_end_exclusive_utc diverges from the OKX research artifact."
        )
    if authorization.candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchSignalDiagnosticIntegrityError("authorization candle_count must be 42816.")
    if authorization.dataset_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256:
        raise OfflineResearchSignalDiagnosticIntegrityError("authorization dataset_sha256 must match the OKX research artifact.")
    if authorization.manifest_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256:
        raise OfflineResearchSignalDiagnosticIntegrityError("authorization manifest_sha256 must match the OKX research artifact.")
    if authorization.manifest_hash != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH:
        raise OfflineResearchSignalDiagnosticIntegrityError("authorization manifest_hash must match the OKX research artifact.")
    if authorization.purpose != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PURPOSE:
        raise OfflineResearchSignalDiagnosticValidationError("authorization purpose must remain offline_historical_research.")
    if authorization.historical_research_only is not True:
        raise OfflineResearchSignalDiagnosticValidationError("historical_research_only must be true.")
    if authorization.operational_evidence is not False:
        raise OfflineResearchSignalDiagnosticValidationError("operational_evidence must be false.")
    if authorization.paper_promotion_eligible is not False:
        raise OfflineResearchSignalDiagnosticValidationError("paper_promotion_eligible must be false.")
    if authorization.allowed_use_cases not in ((), OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_ALLOWED_USE_CASES):
        raise OfflineResearchSignalDiagnosticValidationError("authorization allowed_use_cases diverges from the research-only contract.")
    if authorization.prohibited_use_cases != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PROHIBITED_USE_CASES:
        raise OfflineResearchSignalDiagnosticValidationError("authorization prohibited_use_cases diverge from the research-only contract.")
    if authorization.non_operational_declaration != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchSignalDiagnosticValidationError("authorization non_operational_declaration diverges from the research-only contract.")
    if not authorization.authorization_hash:
        raise OfflineResearchSignalDiagnosticIntegrityError("authorization_hash is required.")
    return authorization


def _require_compatibility(
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
) -> OfflineResearchStrategyCompatibilityDecision:
    if not isinstance(compatibility_decision, OfflineResearchStrategyCompatibilityDecision):
        raise OfflineResearchSignalDiagnosticValidationError("a verified offline research compatibility decision is required.")
    if compatibility_decision.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchSignalDiagnosticValidationError("compatibility provider_name must be OKX.")
    if compatibility_decision.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchSignalDiagnosticValidationError("compatibility market_type must be spot.")
    if compatibility_decision.symbol != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchSignalDiagnosticValidationError("compatibility symbol must be BTC-USDT.")
    if compatibility_decision.canonical_symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchSignalDiagnosticValidationError("compatibility canonical_symbol must be BTCUSDT.")
    if compatibility_decision.interval != "1H":
        raise OfflineResearchSignalDiagnosticValidationError("compatibility interval must be 1H.")
    if compatibility_decision.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchSignalDiagnosticIntegrityError(
            "compatibility requested_start_inclusive_utc diverges from the OKX research artifact."
        )
    if compatibility_decision.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise OfflineResearchSignalDiagnosticIntegrityError(
            "compatibility requested_end_exclusive_utc diverges from the OKX research artifact."
        )
    if compatibility_decision.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchSignalDiagnosticIntegrityError("compatibility expected_candle_count must be 42816.")
    if compatibility_decision.required_dataset_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256:
        raise OfflineResearchSignalDiagnosticIntegrityError("compatibility required_dataset_sha256 must match the OKX research artifact.")
    if compatibility_decision.required_manifest_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256:
        raise OfflineResearchSignalDiagnosticIntegrityError("compatibility required_manifest_sha256 must match the OKX research artifact.")
    if compatibility_decision.required_manifest_hash != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH:
        raise OfflineResearchSignalDiagnosticIntegrityError("compatibility required_manifest_hash must match the OKX research artifact.")
    if compatibility_decision.purpose != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PURPOSE:
        raise OfflineResearchSignalDiagnosticValidationError("compatibility purpose must remain offline_historical_research.")
    if compatibility_decision.historical_research_only is not True:
        raise OfflineResearchSignalDiagnosticValidationError("historical_research_only must be true.")
    if compatibility_decision.operational_evidence is not False:
        raise OfflineResearchSignalDiagnosticValidationError("operational_evidence must be false.")
    if compatibility_decision.paper_promotion_eligible is not False:
        raise OfflineResearchSignalDiagnosticValidationError("paper_promotion_eligible must be false.")
    if compatibility_decision.allowed_use_cases not in ((), OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES):
        raise OfflineResearchSignalDiagnosticValidationError("compatibility allowed_use_cases diverges from the research-only contract.")
    if compatibility_decision.prohibited_use_cases != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES:
        raise OfflineResearchSignalDiagnosticValidationError("compatibility prohibited_use_cases diverge from the research-only contract.")
    if compatibility_decision.non_operational_declaration != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchSignalDiagnosticValidationError("compatibility non_operational_declaration diverges from the research-only contract.")
    if not compatibility_decision.compatibility_hash:
        raise OfflineResearchSignalDiagnosticIntegrityError("compatibility_hash is required.")
    return compatibility_decision


def _require_strategy_contract(
    strategy_contract: BaselineAOkxBtcUsdtResearchContract,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
) -> BaselineAOkxBtcUsdtResearchContract:
    if not isinstance(strategy_contract, BaselineAOkxBtcUsdtResearchContract):
        raise OfflineResearchSignalDiagnosticValidationError("baseline A strategy contract is required.")
    if strategy_contract.strategy_id != "baseline_a_okx_btc_usdt_1h_research":
        raise OfflineResearchSignalDiagnosticValidationError("strategy_id must be baseline_a_okx_btc_usdt_1h_research.")
    if strategy_contract.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchSignalDiagnosticValidationError("strategy provider_name must be OKX.")
    if strategy_contract.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchSignalDiagnosticValidationError("strategy market_type must be spot.")
    if strategy_contract.symbol != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchSignalDiagnosticValidationError("strategy symbol must be BTC-USDT.")
    if strategy_contract.canonical_symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchSignalDiagnosticValidationError("strategy canonical_symbol must be BTCUSDT.")
    if strategy_contract.interval != "1H":
        raise OfflineResearchSignalDiagnosticValidationError("strategy interval must be 1H.")
    if strategy_contract.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchSignalDiagnosticIntegrityError("strategy requested_start_inclusive_utc diverges from the OKX research artifact.")
    if strategy_contract.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise OfflineResearchSignalDiagnosticIntegrityError("strategy requested_end_exclusive_utc diverges from the OKX research artifact.")
    if strategy_contract.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchSignalDiagnosticIntegrityError("strategy expected_candle_count must be 42816.")
    if strategy_contract.required_authorization_hash != authorization.authorization_hash:
        raise OfflineResearchSignalDiagnosticIntegrityError("strategy required_authorization_hash diverges from the verified authorization.")
    if strategy_contract.required_compatibility_hash != compatibility_decision.compatibility_hash:
        raise OfflineResearchSignalDiagnosticIntegrityError("strategy required_compatibility_hash diverges from the verified compatibility decision.")
    if strategy_contract.purpose != BASELINE_A_OKX_BTC_USDT_RESEARCH_PURPOSE:
        raise OfflineResearchSignalDiagnosticValidationError("strategy purpose must remain offline_historical_research.")
    if strategy_contract.historical_research_only is not True:
        raise OfflineResearchSignalDiagnosticValidationError("historical_research_only must be true.")
    if strategy_contract.operational_evidence is not False:
        raise OfflineResearchSignalDiagnosticValidationError("operational_evidence must be false.")
    if strategy_contract.paper_promotion_eligible is not False:
        raise OfflineResearchSignalDiagnosticValidationError("paper_promotion_eligible must be false.")
    if strategy_contract.allowed_use_cases != BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_ALLOWED_USE_CASES:
        raise OfflineResearchSignalDiagnosticValidationError("strategy allowed_use_cases must remain offline_historical_research.")
    if strategy_contract.prohibited_use_cases != BASELINE_A_OKX_BTC_USDT_RESEARCH_PROHIBITED_USE_CASES:
        raise OfflineResearchSignalDiagnosticValidationError("strategy prohibited_use_cases must block operational use cases.")
    if strategy_contract.allowed_decisions != BASELINE_A_OKX_BTC_USDT_RESEARCH_ALLOWED_DECISIONS:
        raise OfflineResearchSignalDiagnosticValidationError("strategy allowed_decisions must remain long_setup_detected or no_setup.")
    if strategy_contract.non_operational_declaration != BASELINE_A_OKX_BTC_USDT_RESEARCH_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchSignalDiagnosticValidationError("strategy non_operational_declaration diverges from the research-only contract.")
    if not strategy_contract.contract_hash:
        raise OfflineResearchSignalDiagnosticIntegrityError("strategy contract_hash is required.")
    return strategy_contract

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

def project_okx_research_candles(
    dataset: OkxHistoricalDataset,
    *,
    symbol: str,
) -> tuple[Candle, ...]:
    return _project_dataset_to_research_surface(dataset, symbol=symbol)


def _seed_average(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _build_conclusion(
    *,
    candles_insufficient: int,
    bullish_trend_candles: int,
    bullish_pullback_candles: int,
    bullish_confirmation_candles: int,
    long_setups: int,
) -> str:
    if candles_insufficient and candles_insufficient > 0 and bullish_trend_candles == 0 and long_setups == 0:
        return "candles are accepted, but every eligible candle is rejected at the bullish trend gate (ema50 must be above ema200)."
    if bullish_trend_candles == 0:
        return "the strategy never identifies a bullish trend."
    if bullish_pullback_candles == 0:
        return "a bullish trend exists, but the pullback never occurs."
    if bullish_confirmation_candles == 0:
        return "a bullish pullback exists, but the confirmation never occurs."
    if long_setups == 0:
        return "an additional criterion eliminates all long setups."
    return "at least one long setup is present."


def analyze_zero_trade_signal_funnel(
    candles: Sequence[Candle],
    *,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    strategy_contract: BaselineAOkxBtcUsdtResearchContract | None = None,
    analyzed_at_utc: datetime | None = None,
) -> OfflineResearchSignalDiagnosticReport:
    authorization = _require_authorization(authorization)
    compatibility_decision = _require_compatibility(compatibility_decision)
    if strategy_contract is None:
        strategy_contract = build_baseline_a_okx_btc_usdt_research_contract(authorization, compatibility_decision)
    strategy_contract = _require_strategy_contract(strategy_contract, authorization, compatibility_decision)
    history = _require_candle_sequence(candles, symbol=strategy_contract.symbol, interval=strategy_contract.interval)
    if not history:
        raise OfflineResearchSignalDiagnosticValidationError("candles must contain at least one item.")
    analyzed_at = _require_utc_datetime(analyzed_at_utc or authorization.issued_at_utc, "analyzed_at_utc")

    closes: list[Decimal] = []
    true_ranges: list[Decimal] = []
    ema20: Decimal | None = None
    ema50: Decimal | None = None
    ema200: Decimal | None = None
    prev_ema50: Decimal | None = None
    atr14: Decimal | None = None
    previous_candle: Candle | None = None
    recent_long_touches: deque[bool] = deque(maxlen=strategy_contract.pullback_lookback)
    recent_short_touches: deque[bool] = deque(maxlen=strategy_contract.pullback_lookback)
    long_rejection_counts: Counter[str] = Counter()
    short_rejection_counts: Counter[str] = Counter()
    first_occurrences: dict[str, dict[str, Any]] = {}
    bullish_trend_candles = 0
    bearish_trend_candles = 0
    bullish_pullback_candles = 0
    bearish_pullback_candles = 0
    bullish_confirmation_candles = 0
    bearish_confirmation_candles = 0
    long_setups = 0
    short_setups = 0
    insufficient_count = 0

    for index, candle in enumerate(history):
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

        if len(closes) == strategy_contract.trend_fast_ema_period:
            ema20 = _seed_average(closes[: strategy_contract.trend_fast_ema_period])
        elif len(closes) > strategy_contract.trend_fast_ema_period and ema20 is not None:
            alpha = Decimal("2") / Decimal(strategy_contract.trend_fast_ema_period + 1)
            ema20 = (candle.close * alpha) + (ema20 * (Decimal("1") - alpha))

        if len(closes) == strategy_contract.trend_mid_ema_period:
            prev_ema50 = ema50
            ema50 = _seed_average(closes[: strategy_contract.trend_mid_ema_period])
        elif len(closes) > strategy_contract.trend_mid_ema_period and ema50 is not None:
            prev_ema50 = ema50
            alpha = Decimal("2") / Decimal(strategy_contract.trend_mid_ema_period + 1)
            ema50 = (candle.close * alpha) + (ema50 * (Decimal("1") - alpha))
        else:
            prev_ema50 = ema50

        if len(closes) == strategy_contract.trend_slow_ema_period:
            ema200 = _seed_average(closes[: strategy_contract.trend_slow_ema_period])
        elif len(closes) > strategy_contract.trend_slow_ema_period and ema200 is not None:
            alpha = Decimal("2") / Decimal(strategy_contract.trend_slow_ema_period + 1)
            ema200 = (candle.close * alpha) + (ema200 * (Decimal("1") - alpha))

        if len(true_ranges) == strategy_contract.atr_period:
            atr14 = _seed_average(true_ranges[: strategy_contract.atr_period])
        elif len(true_ranges) > strategy_contract.atr_period and atr14 is not None:
            atr14 = ((atr14 * Decimal(strategy_contract.atr_period - 1)) + true_range) / Decimal(strategy_contract.atr_period)

        recent_long_touches.append(bool(ema20 is not None and candle.low <= ema20))
        recent_short_touches.append(bool(ema20 is not None and candle.high >= ema20))

        if (
            len(closes) < strategy_contract.minimum_candles_required
            or ema20 is None
            or ema50 is None
            or ema200 is None
            or prev_ema50 is None
            or atr14 is None
            or len(recent_long_touches) < strategy_contract.pullback_lookback
        ):
            insufficient_count += 1
            if "first_insufficient" not in first_occurrences:
                first_occurrences["first_insufficient"] = _snapshot_payload(
                    candle_index=index,
                    candle=candle,
                    ema20=ema20,
                    ema50=ema50,
                    ema200=ema200,
                    atr14=atr14,
                    previous_candle=previous_candle,
                    reason="insufficient_data_for_indicator_stack",
                )
            previous_candle = candle
            continue

        long_trend = ema50 > ema200
        short_trend = ema50 < ema200
        if long_trend:
            bullish_trend_candles += 1
        else:
            long_rejection_counts[OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_BULLISH_TREND_REJECTION] += 1
            if "first_long_rejection" not in first_occurrences:
                first_occurrences["first_long_rejection"] = _snapshot_payload(
                    candle_index=index,
                    candle=candle,
                    ema20=ema20,
                    ema50=ema50,
                    ema200=ema200,
                    atr14=atr14,
                    previous_candle=previous_candle,
                    reason=OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_BULLISH_TREND_REJECTION,
                )
        if short_trend:
            bearish_trend_candles += 1
        else:
            short_rejection_counts[OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_BEARISH_TREND_REJECTION] += 1

        long_price_above_ema200 = long_trend and candle.close > ema200
        short_price_below_ema200 = short_trend and candle.close < ema200
        if long_price_above_ema200:
            bullish_pullback_candles += 1
        elif long_trend:
            long_rejection_counts["close_must_be_above_ema200"] += 1

        if short_price_below_ema200:
            bearish_pullback_candles += 1
        elif short_trend:
            short_rejection_counts["close_must_be_below_ema200"] += 1

        long_rising_ema50 = long_price_above_ema200 and ema50 > prev_ema50
        short_falling_ema50 = short_price_below_ema200 and ema50 < prev_ema50
        if long_rising_ema50:
            bullish_confirmation_candles += 1
        elif long_price_above_ema200:
            long_rejection_counts["ema50_must_be_rising"] += 1

        if short_falling_ema50:
            bearish_confirmation_candles += 1
        elif short_price_below_ema200:
            short_rejection_counts["ema50_must_be_falling"] += 1

        long_reclaim_ema20 = long_rising_ema50 and candle.close > ema20
        short_reclaim_ema20 = short_falling_ema50 and candle.close < ema20
        if not long_reclaim_ema20 and long_rising_ema50:
            long_rejection_counts["close_must_reclaim_ema20"] += 1
        if not short_reclaim_ema20 and short_falling_ema50:
            short_rejection_counts["close_must_break_below_ema20"] += 1

        long_breakout = long_reclaim_ema20 and candle.close > previous_candle.high
        short_breakout = short_reclaim_ema20 and candle.close < previous_candle.low
        if not long_breakout and long_reclaim_ema20:
            long_rejection_counts["close_must_break_prior_high"] += 1
        if not short_breakout and short_reclaim_ema20:
            short_rejection_counts["close_must_break_prior_low"] += 1

        if long_breakout and any(recent_long_touches):
            long_setups += 1
            if "first_long_setup" not in first_occurrences:
                first_occurrences["first_long_setup"] = _snapshot_payload(
                    candle_index=index,
                    candle=candle,
                    ema20=ema20,
                    ema50=ema50,
                    ema200=ema200,
                    atr14=atr14,
                    previous_candle=previous_candle,
                    reason=BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_LONG_SETUP_DETECTED,
                )
        elif long_breakout:
            long_rejection_counts["no_recent_long_pullback_touch"] += 1

        if short_breakout and any(recent_short_touches):
            short_setups += 1
            if "first_short_setup" not in first_occurrences:
                first_occurrences["first_short_setup"] = _snapshot_payload(
                    candle_index=index,
                    candle=candle,
                    ema20=ema20,
                    ema50=ema50,
                    ema200=ema200,
                    atr14=atr14,
                    previous_candle=previous_candle,
                    reason="short_setup_detected",
                )
        elif short_breakout:
            short_rejection_counts["no_recent_short_pullback_touch"] += 1

        if long_trend and "first_bullish_trend" not in first_occurrences:
            first_occurrences["first_bullish_trend"] = _snapshot_payload(
                candle_index=index,
                candle=candle,
                ema20=ema20,
                ema50=ema50,
                ema200=ema200,
                atr14=atr14,
                previous_candle=previous_candle,
                reason="bullish_trend_identified",
            )
        if short_trend and "first_bearish_trend" not in first_occurrences:
            first_occurrences["first_bearish_trend"] = _snapshot_payload(
                candle_index=index,
                candle=candle,
                ema20=ema20,
                ema50=ema50,
                ema200=ema200,
                atr14=atr14,
                previous_candle=previous_candle,
                reason="bearish_trend_identified",
            )
        if short_price_below_ema200 and "first_bearish_pullback" not in first_occurrences:
            first_occurrences["first_bearish_pullback"] = _snapshot_payload(
                candle_index=index,
                candle=candle,
                ema20=ema20,
                ema50=ema50,
                ema200=ema200,
                atr14=atr14,
                previous_candle=previous_candle,
                reason="bearish_pullback_identified",
            )
        if short_falling_ema50 and "first_bearish_confirmation" not in first_occurrences:
            first_occurrences["first_bearish_confirmation"] = _snapshot_payload(
                candle_index=index,
                candle=candle,
                ema20=ema20,
                ema50=ema50,
                ema200=ema200,
                atr14=atr14,
                previous_candle=previous_candle,
                reason="bearish_confirmation_identified",
            )

        previous_candle = candle

    primary_reason = OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_BULLISH_TREND_REJECTION
    primary_reason_count = long_rejection_counts.get(primary_reason, 0)
    if long_rejection_counts:
        primary_reason, primary_reason_count = max(long_rejection_counts.items(), key=lambda item: (item[1], item[0]))
    conclusion = _build_conclusion(
        candles_insufficient=insufficient_count,
        bullish_trend_candles=bullish_trend_candles,
        bullish_pullback_candles=bullish_pullback_candles,
        bullish_confirmation_candles=bullish_confirmation_candles,
        long_setups=long_setups,
    )
    report = OfflineResearchSignalDiagnosticReport(
        schema_version=OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_SCHEMA_VERSION,
        diagnostic_id=OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_ID,
        diagnostic_version=OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_VERSION,
        analyzed_at_utc=analyzed_at,
        strategy_id=strategy_contract.strategy_id,
        strategy_version=strategy_contract.strategy_version,
        provider_name=authorization.provider_name,
        market_type=authorization.market_type,
        symbol=strategy_contract.symbol,
        canonical_symbol=strategy_contract.canonical_symbol,
        interval=strategy_contract.interval,
        requested_start_inclusive_utc=strategy_contract.requested_start_inclusive_utc,
        requested_end_exclusive_utc=strategy_contract.requested_end_exclusive_utc,
        expected_candle_count=strategy_contract.expected_candle_count,
        authorization_hash=authorization.authorization_hash,
        compatibility_hash=compatibility_decision.compatibility_hash,
        strategy_contract_hash=strategy_contract.contract_hash,
        dataset_hash=authorization.dataset_sha256,
        manifest_hash=authorization.manifest_sha256,
        candles_total=len(history),
        candles_structurally_invalid=0,
        candles_insufficient=insufficient_count,
        bullish_trend_candles=bullish_trend_candles,
        bearish_trend_candles=bearish_trend_candles,
        bullish_pullback_candles=bullish_pullback_candles,
        bearish_pullback_candles=bearish_pullback_candles,
        bullish_confirmation_candles=bullish_confirmation_candles,
        bearish_confirmation_candles=bearish_confirmation_candles,
        long_setups=long_setups,
        short_setups=short_setups,
        long_rejection_counts=long_rejection_counts,
        short_rejection_counts=short_rejection_counts,
        first_occurrences=first_occurrences,
        primary_rejection_reason=primary_reason,
        primary_rejection_reason_count=primary_reason_count,
        conclusion=conclusion,
    )
    if report.as_dict() != serialize_value(report.canonical_payload()):
        raise OfflineResearchSignalDiagnosticIntegrityError("diagnostic payload mismatch.")
    return report


def run_zero_trade_signal_diagnostic(
    candles: Sequence[Candle],
    *,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    strategy_contract: BaselineAOkxBtcUsdtResearchContract | None = None,
    analyzed_at_utc: datetime | None = None,
    output_file: str | Path | None = None,
) -> OfflineResearchSignalDiagnosticReport:
    report = analyze_zero_trade_signal_funnel(
        candles,
        authorization=authorization,
        compatibility_decision=compatibility_decision,
        strategy_contract=strategy_contract,
        analyzed_at_utc=analyzed_at_utc,
    )
    if output_file is not None:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_canonical_json(report.as_dict()), encoding="utf-8")
    return report

def run_zero_trade_signal_diagnostic_for_okx_artifact(
    *,
    dataset: OkxHistoricalDataset,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    strategy_contract: BaselineAOkxBtcUsdtResearchContract | None = None,
    analyzed_at_utc: datetime | None = None,
    output_file: str | Path | None = None,
) -> OfflineResearchSignalDiagnosticReport:
    if strategy_contract is None:
        strategy_contract = build_baseline_a_okx_btc_usdt_research_contract(authorization, compatibility_decision)
    projected_candles = project_okx_research_candles(
        dataset,
        symbol=strategy_contract.symbol,
    )
    return run_zero_trade_signal_diagnostic(
        projected_candles,
        authorization=authorization,
        compatibility_decision=compatibility_decision,
        strategy_contract=strategy_contract,
        analyzed_at_utc=analyzed_at_utc,
        output_file=output_file,
    )


__all__ = [
    "OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_ALLOWED_USE_CASES",
    "OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_ID",
    "OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_NON_OPERATIONAL_DECLARATION",
    "OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_PROHIBITED_USE_CASES",
    "OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_PURPOSE",
    "OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_SCHEMA_VERSION",
    "OFFLINE_RESEARCH_SIGNAL_DIAGNOSTIC_VERSION",
    "OfflineResearchSignalDiagnosticError",
    "OfflineResearchSignalDiagnosticIntegrityError",
    "OfflineResearchSignalDiagnosticReport",
    "OfflineResearchSignalDiagnosticValidationError",
    "analyze_zero_trade_signal_funnel",
    "project_okx_research_candles",
    "run_zero_trade_signal_diagnostic",
    "run_zero_trade_signal_diagnostic_for_okx_artifact",
]
