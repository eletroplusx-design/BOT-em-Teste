from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from domain.serialization import serialize_value

from .errors import HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError
from .offline_research_backtest import (
    OkxOfflineResearchArtifactReference,
    OfflineResearchBacktestValidationError,
    resolve_okx_offline_research_artifact_reference,
)
from .research_artifact_registry import (
    OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT,
    OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256,
    OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH,
    OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256,
    OKX_RESEARCH_ARTIFACT_INSTRUMENT,
    OKX_RESEARCH_ARTIFACT_MARKET_TYPE,
    OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION,
    OKX_RESEARCH_ARTIFACT_PROVIDER_NAME,
    OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC,
    OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC,
    OKX_RESEARCH_ARTIFACT_SYMBOL,
)
from strategies.baseline_a_okx_btc_usdt_research import (
    BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_ALLOWED_USE_CASES,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_SCHEMA_VERSION,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_NON_OPERATIONAL_DECLARATION,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_PROHIBITED_USE_CASES,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_ID,
    BaselineAOkxBtcUsdtResearchContract,
)

OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_SCHEMA_VERSION = 1
OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_ID = "baseline_a_okx_btc_usdt_1h_offline_experiment_contract"
OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_VERSION = "phase40_offline_experiment_contract_v1"
OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_PURPOSE = "offline_historical_research"
OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_ALLOWED_USE_CASES: tuple[str, ...] = (
    OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_PURPOSE,
)
OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_PROHIBITED_USE_CASES: tuple[str, ...] = (
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
OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_NON_OPERATIONAL_DECLARATION = (
    "This experiment contract is research-only and does not authorize replay, backtest, walk-forward, "
    "performance, ranking, paper trading, live trading, execution, or order submission."
)


class OfflineResearchExperimentContractError(HistoricalDataError):
    pass


class OfflineResearchExperimentContractValidationError(
    OfflineResearchExperimentContractError, HistoricalDataValidationError
):
    pass


class OfflineResearchExperimentContractIntegrityError(
    OfflineResearchExperimentContractError, HistoricalDataIntegrityError
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineResearchExperimentContractValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchExperimentContractValidationError(f"{field_name} must be a 64-character hex digest.")
    return digest


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineResearchExperimentContractValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineResearchExperimentContractValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineResearchExperimentContractValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise OfflineResearchExperimentContractValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise OfflineResearchExperimentContractValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineResearchExperimentContractValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _freeze_read_only_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_read_only_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_read_only_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_read_only_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_read_only_value(item) for item in value)
    return value


def _thaw_read_only_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_read_only_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_thaw_read_only_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_thaw_read_only_value(item) for item in value)
    if isinstance(value, frozenset):
        thawed_items = [_thaw_read_only_value(item) for item in value]
        return tuple(
            item
            for _, item in sorted(
                (
                    (
                        _canonical_json(_thaw_read_only_value(item)),
                        _thaw_read_only_value(item),
                    )
                    for item in thawed_items
                ),
                key=lambda pair: pair[0],
            )
        )
    return value


def _require_decimal(value: Any, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:  # pragma: no cover - defensive guard
        raise OfflineResearchExperimentContractValidationError(f"{field_name} must be numeric.") from exc


def _artifact_reference_payload(reference: OkxOfflineResearchArtifactReference) -> dict[str, Any]:
    if not isinstance(reference, OkxOfflineResearchArtifactReference):
        raise OfflineResearchExperimentContractValidationError(
            "a verified offline research artifact reference is required."
        )
    registry_report = reference.registry_report
    dataset_report = reference.dataset_report
    return {
        "artifact_id": registry_report.artifact_id,
        "provider_name": registry_report.provider_name,
        "market_type": registry_report.market_type,
        "instrument": registry_report.instrument,
        "symbol": registry_report.symbol,
        "interval": registry_report.interval,
        "requested_start_inclusive_utc": _utc_iso(registry_report.requested_start_inclusive_utc),
        "requested_end_exclusive_utc": _utc_iso(registry_report.requested_end_exclusive_utc),
        "expected_candle_count": registry_report.expected_candle_count,
        "dataset_sha256": registry_report.dataset_sha256,
        "manifest_sha256": registry_report.manifest_sha256,
        "manifest_hash": registry_report.manifest_hash,
        "audit_status": registry_report.audit_status,
        "historical_research_only": registry_report.historical_research_only,
        "operational_evidence": registry_report.operational_evidence,
        "paper_promotion_eligible": registry_report.paper_promotion_eligible,
        "registry_verification_hash": registry_report.verification_hash,
        "dataset_hash": dataset_report["dataset_hash"],
        "dataset_contract_hash": dataset_report["contract_hash"],
        "dataset_historical_research_only": dataset_report["historical_research_only"],
        "dataset_operational_evidence": dataset_report["operational_evidence"],
        "dataset_paper_promotion_eligible": dataset_report["paper_promotion_eligible"],
    }


def _strategy_contract_payload(strategy_contract: BaselineAOkxBtcUsdtResearchContract) -> dict[str, Any]:
    if not isinstance(strategy_contract, BaselineAOkxBtcUsdtResearchContract):
        raise OfflineResearchExperimentContractValidationError(
            "a verified baseline A strategy contract is required."
        )
    if strategy_contract.strategy_id != BASELINE_A_OKX_BTC_USDT_RESEARCH_STRATEGY_ID:
        raise OfflineResearchExperimentContractValidationError("strategy_id must remain baseline_a_okx_btc_usdt_1h_research.")
    return strategy_contract.as_dict()


@dataclass(frozen=True, slots=True)
class OfflineResearchExperimentContract:
    schema_version: int
    experiment_id: str
    experiment_version: str
    created_at_utc: datetime
    artifact_reference: Mapping[str, Any] = field(repr=False)
    strategy_contract: Mapping[str, Any] = field(repr=False)
    purpose: str = OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_PURPOSE
    window_start_utc: datetime = field(default_factory=lambda: OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC)
    window_end_utc: datetime = field(default_factory=lambda: OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC)
    symbol: str = OKX_RESEARCH_ARTIFACT_INSTRUMENT
    interval: str = "1H"
    entry_fee_rate: Decimal = Decimal("0.0004")
    exit_fee_rate: Decimal = Decimal("0.0004")
    spread_bps: Decimal = Decimal("5")
    slippage_bps: Decimal = Decimal("5")
    leverage: Decimal = Decimal("1")
    initial_capital: Decimal = Decimal("10000")
    risk_percent: Decimal = Decimal("1")
    extra_parameters: Mapping[str, Any] = field(default_factory=dict, repr=False)
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    paper_trading_enabled: bool = False
    live_trading_enabled: bool = False
    execution_enabled: bool = False
    order_submission_enabled: bool = False
    credentials_required: bool = False
    exchange_api_enabled: bool = False
    download_enabled: bool = False
    ingestion_enabled: bool = False
    allowed_use_cases: tuple[str, ...] = field(
        default_factory=lambda: OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_ALLOWED_USE_CASES
    )
    prohibited_use_cases: tuple[str, ...] = field(
        default_factory=lambda: OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_PROHIBITED_USE_CASES
    )
    non_operational_declaration: str = OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_NON_OPERATIONAL_DECLARATION
    contract_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "experiment_id", _require_str(self.experiment_id, "experiment_id"))
        object.__setattr__(self, "experiment_version", _require_str(self.experiment_version, "experiment_version"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "purpose", _require_str(self.purpose, "purpose"))
        object.__setattr__(self, "artifact_reference", _freeze_read_only_value(dict(_artifact_reference_payload(self.artifact_reference))))
        object.__setattr__(self, "strategy_contract", _freeze_read_only_value(dict(_strategy_contract_payload(self.strategy_contract))))
        object.__setattr__(self, "window_start_utc", _require_utc_datetime(self.window_start_utc, "window_start_utc"))
        object.__setattr__(self, "window_end_utc", _require_utc_datetime(self.window_end_utc, "window_end_utc"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "entry_fee_rate", _require_decimal(self.entry_fee_rate, "entry_fee_rate"))
        object.__setattr__(self, "exit_fee_rate", _require_decimal(self.exit_fee_rate, "exit_fee_rate"))
        object.__setattr__(self, "spread_bps", _require_decimal(self.spread_bps, "spread_bps"))
        object.__setattr__(self, "slippage_bps", _require_decimal(self.slippage_bps, "slippage_bps"))
        object.__setattr__(self, "leverage", _require_decimal(self.leverage, "leverage"))
        object.__setattr__(self, "initial_capital", _require_decimal(self.initial_capital, "initial_capital"))
        object.__setattr__(self, "risk_percent", _require_decimal(self.risk_percent, "risk_percent"))
        object.__setattr__(self, "extra_parameters", _freeze_read_only_value(dict(self.extra_parameters)))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "paper_trading_enabled", _require_bool(self.paper_trading_enabled, "paper_trading_enabled"))
        object.__setattr__(self, "live_trading_enabled", _require_bool(self.live_trading_enabled, "live_trading_enabled"))
        object.__setattr__(self, "execution_enabled", _require_bool(self.execution_enabled, "execution_enabled"))
        object.__setattr__(self, "order_submission_enabled", _require_bool(self.order_submission_enabled, "order_submission_enabled"))
        object.__setattr__(self, "credentials_required", _require_bool(self.credentials_required, "credentials_required"))
        object.__setattr__(self, "exchange_api_enabled", _require_bool(self.exchange_api_enabled, "exchange_api_enabled"))
        object.__setattr__(self, "download_enabled", _require_bool(self.download_enabled, "download_enabled"))
        object.__setattr__(self, "ingestion_enabled", _require_bool(self.ingestion_enabled, "ingestion_enabled"))
        object.__setattr__(self, "allowed_use_cases", tuple(dict.fromkeys(_require_str(item, "allowed_use_case").lower() for item in self.allowed_use_cases)))
        object.__setattr__(self, "prohibited_use_cases", tuple(dict.fromkeys(_require_str(item, "prohibited_use_case").lower() for item in self.prohibited_use_cases)))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))

        if self.schema_version != OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_SCHEMA_VERSION:
            raise OfflineResearchExperimentContractValidationError("schema_version must be 1.")
        if self.experiment_id != OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_ID:
            raise OfflineResearchExperimentContractValidationError(
                "experiment_id must remain baseline_a_okx_btc_usdt_1h_offline_experiment_contract."
            )
        if self.experiment_version != OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_VERSION:
            raise OfflineResearchExperimentContractValidationError(
                "experiment_version must remain phase40_offline_experiment_contract_v1."
            )
        if self.purpose != OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_PURPOSE:
            raise OfflineResearchExperimentContractValidationError("purpose must be offline_historical_research.")
        if self.window_end_utc <= self.window_start_utc:
            raise OfflineResearchExperimentContractValidationError(
                "window_end_utc must be after window_start_utc."
            )
        if self.window_start_utc < OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
            raise OfflineResearchExperimentContractIntegrityError(
                "window_start_utc must not precede the OKX research artifact start."
            )
        if self.window_end_utc > OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
            raise OfflineResearchExperimentContractIntegrityError(
                "window_end_utc must not exceed the OKX research artifact end."
            )
        if self.symbol != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
            raise OfflineResearchExperimentContractValidationError("symbol must be BTC-USDT.")
        if self.interval != "1H":
            raise OfflineResearchExperimentContractValidationError("interval must be 1H.")
        if self.entry_fee_rate < 0:
            raise OfflineResearchExperimentContractValidationError("entry_fee_rate must be non-negative.")
        if self.exit_fee_rate < 0:
            raise OfflineResearchExperimentContractValidationError("exit_fee_rate must be non-negative.")
        if self.spread_bps < 0:
            raise OfflineResearchExperimentContractValidationError("spread_bps must be non-negative.")
        if self.slippage_bps < 0:
            raise OfflineResearchExperimentContractValidationError("slippage_bps must be non-negative.")
        if self.leverage <= 0:
            raise OfflineResearchExperimentContractValidationError("leverage must be greater than zero.")
        if self.initial_capital <= 0:
            raise OfflineResearchExperimentContractValidationError("initial_capital must be greater than zero.")
        if self.risk_percent <= 0:
            raise OfflineResearchExperimentContractValidationError("risk_percent must be greater than zero.")
        if self.historical_research_only is not True:
            raise OfflineResearchExperimentContractValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchExperimentContractValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchExperimentContractValidationError("paper_promotion_eligible must be false.")
        if self.paper_trading_enabled is not False:
            raise OfflineResearchExperimentContractValidationError("paper_trading_enabled must be false.")
        if self.live_trading_enabled is not False:
            raise OfflineResearchExperimentContractValidationError("live_trading_enabled must be false.")
        if self.execution_enabled is not False:
            raise OfflineResearchExperimentContractValidationError("execution_enabled must be false.")
        if self.order_submission_enabled is not False:
            raise OfflineResearchExperimentContractValidationError("order_submission_enabled must be false.")
        if self.credentials_required is not False:
            raise OfflineResearchExperimentContractValidationError("credentials_required must be false.")
        if self.exchange_api_enabled is not False:
            raise OfflineResearchExperimentContractValidationError("exchange_api_enabled must be false.")
        if self.download_enabled is not False:
            raise OfflineResearchExperimentContractValidationError("download_enabled must be false.")
        if self.ingestion_enabled is not False:
            raise OfflineResearchExperimentContractValidationError("ingestion_enabled must be false.")
        if self.allowed_use_cases != OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_ALLOWED_USE_CASES:
            raise OfflineResearchExperimentContractValidationError("allowed_use_cases must remain offline_historical_research.")
        if self.prohibited_use_cases != OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_PROHIBITED_USE_CASES:
            raise OfflineResearchExperimentContractValidationError("prohibited_use_cases must block operational use cases.")
        if self.non_operational_declaration != OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchExperimentContractValidationError(
                "non_operational_declaration diverges from the research-only contract."
            )

        expected_hash = _hash_payload(self.canonical_payload(include_contract_hash=False))
        if self.contract_hash:
            if self.contract_hash != expected_hash:
                raise OfflineResearchExperimentContractIntegrityError("contract_hash mismatch.")
        else:
            object.__setattr__(self, "contract_hash", expected_hash)

    def canonical_payload(self, *, include_contract_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "experiment_version": self.experiment_version,
            "purpose": self.purpose,
            "artifact_reference": _thaw_read_only_value(self.artifact_reference),
            "strategy_contract": _thaw_read_only_value(self.strategy_contract),
            "window_start_utc": _utc_iso(self.window_start_utc),
            "window_end_utc": _utc_iso(self.window_end_utc),
            "symbol": self.symbol,
            "interval": self.interval,
            "entry_fee_rate": str(self.entry_fee_rate),
            "exit_fee_rate": str(self.exit_fee_rate),
            "spread_bps": str(self.spread_bps),
            "slippage_bps": str(self.slippage_bps),
            "leverage": str(self.leverage),
            "initial_capital": str(self.initial_capital),
            "risk_percent": str(self.risk_percent),
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "paper_trading_enabled": self.paper_trading_enabled,
            "live_trading_enabled": self.live_trading_enabled,
            "execution_enabled": self.execution_enabled,
            "order_submission_enabled": self.order_submission_enabled,
            "credentials_required": self.credentials_required,
            "exchange_api_enabled": self.exchange_api_enabled,
            "download_enabled": self.download_enabled,
            "ingestion_enabled": self.ingestion_enabled,
            "allowed_use_cases": self.allowed_use_cases,
            "prohibited_use_cases": self.prohibited_use_cases,
            "non_operational_declaration": self.non_operational_declaration,
            "extra_parameters": _thaw_read_only_value(self.extra_parameters),
        }
        if include_contract_hash:
            payload["contract_hash"] = self.contract_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_contract_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfflineResearchExperimentContract":
        if not isinstance(data, Mapping):
            raise OfflineResearchExperimentContractValidationError("experiment contract must be a mapping.")
        mapping = dict(data)
        allowed = {
            "schema_version",
            "experiment_id",
            "experiment_version",
            "created_at_utc",
            "purpose",
            "artifact_reference",
            "strategy_contract",
            "window_start_utc",
            "window_end_utc",
            "symbol",
            "interval",
            "entry_fee_rate",
            "exit_fee_rate",
            "spread_bps",
            "slippage_bps",
            "leverage",
            "initial_capital",
            "risk_percent",
            "extra_parameters",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "paper_trading_enabled",
            "live_trading_enabled",
            "execution_enabled",
            "order_submission_enabled",
            "credentials_required",
            "exchange_api_enabled",
            "download_enabled",
            "ingestion_enabled",
            "allowed_use_cases",
            "prohibited_use_cases",
            "non_operational_declaration",
            "contract_hash",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise OfflineResearchExperimentContractValidationError(
                f"unexpected experiment contract fields: {', '.join(extra)}."
            )
        try:
            return cls(
                schema_version=mapping.get("schema_version", OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_SCHEMA_VERSION),
                experiment_id=mapping["experiment_id"],
                experiment_version=mapping.get("experiment_version", OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_VERSION),
                created_at_utc=mapping.get("created_at_utc", datetime.now(timezone.utc)),
                purpose=mapping.get("purpose", OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_PURPOSE),
                artifact_reference=mapping["artifact_reference"],
                strategy_contract=mapping["strategy_contract"],
                window_start_utc=mapping["window_start_utc"],
                window_end_utc=mapping["window_end_utc"],
                symbol=mapping["symbol"],
                interval=mapping["interval"],
                entry_fee_rate=mapping["entry_fee_rate"],
                exit_fee_rate=mapping["exit_fee_rate"],
                spread_bps=mapping["spread_bps"],
                slippage_bps=mapping["slippage_bps"],
                leverage=mapping["leverage"],
                initial_capital=mapping["initial_capital"],
                risk_percent=mapping["risk_percent"],
                extra_parameters=mapping.get("extra_parameters", {}),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                paper_trading_enabled=mapping.get("paper_trading_enabled", False),
                live_trading_enabled=mapping.get("live_trading_enabled", False),
                execution_enabled=mapping.get("execution_enabled", False),
                order_submission_enabled=mapping.get("order_submission_enabled", False),
                credentials_required=mapping.get("credentials_required", False),
                exchange_api_enabled=mapping.get("exchange_api_enabled", False),
                download_enabled=mapping.get("download_enabled", False),
                ingestion_enabled=mapping.get("ingestion_enabled", False),
                allowed_use_cases=mapping.get("allowed_use_cases", OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_ALLOWED_USE_CASES),
                prohibited_use_cases=mapping.get(
                    "prohibited_use_cases", OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_PROHIBITED_USE_CASES
                ),
                non_operational_declaration=mapping.get(
                    "non_operational_declaration",
                    OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_NON_OPERATIONAL_DECLARATION,
                ),
                contract_hash=mapping.get("contract_hash", ""),
            )
        except KeyError as exc:
            raise OfflineResearchExperimentContractValidationError("experiment contract is incomplete.") from exc


def build_offline_research_experiment_contract(
    *,
    artifact_reference: OkxOfflineResearchArtifactReference | None = None,
    registry_file: str | Path | None = None,
    dataset_file: str | Path | None = None,
    manifest_file: str | Path | None = None,
    strategy_contract: BaselineAOkxBtcUsdtResearchContract,
    experiment_id: str = OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_ID,
    experiment_version: str = OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_VERSION,
    created_at_utc: datetime | None = None,
    purpose: str = OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_PURPOSE,
    window_start_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC,
    window_end_utc: datetime = OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC,
    symbol: str = OKX_RESEARCH_ARTIFACT_INSTRUMENT,
    interval: str = "1H",
    entry_fee_rate: Decimal | str = Decimal("0.0004"),
    exit_fee_rate: Decimal | str = Decimal("0.0004"),
    spread_bps: Decimal | str = Decimal("5"),
    slippage_bps: Decimal | str = Decimal("5"),
    leverage: Decimal | str = Decimal("1"),
    initial_capital: Decimal | str = Decimal("10000"),
    risk_percent: Decimal | str = Decimal("1"),
    extra_parameters: Mapping[str, Any] | None = None,
    historical_research_only: bool = True,
    operational_evidence: bool = False,
    paper_promotion_eligible: bool = False,
    paper_trading_enabled: bool = False,
    live_trading_enabled: bool = False,
    execution_enabled: bool = False,
    order_submission_enabled: bool = False,
    credentials_required: bool = False,
    exchange_api_enabled: bool = False,
    download_enabled: bool = False,
    ingestion_enabled: bool = False,
    allowed_use_cases: tuple[str, ...] | None = None,
    prohibited_use_cases: tuple[str, ...] | None = None,
    non_operational_declaration: str = OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_NON_OPERATIONAL_DECLARATION,
) -> OfflineResearchExperimentContract:
    if artifact_reference is not None and any(
        value is not None for value in (registry_file, dataset_file, manifest_file)
    ):
        raise OfflineResearchExperimentContractValidationError(
            "provide either a qualified artifact reference or explicit artifact paths, not both."
        )
    if artifact_reference is None:
        if registry_file is None or dataset_file is None or manifest_file is None:
            raise OfflineResearchExperimentContractValidationError(
                "registry_file, dataset_file and manifest_file are required when artifact_reference is not provided."
            )
        artifact_reference = resolve_okx_offline_research_artifact_reference(
            registry_file=registry_file,
            dataset_file=dataset_file,
            manifest_file=manifest_file,
        )
    if not isinstance(strategy_contract, BaselineAOkxBtcUsdtResearchContract):
        raise OfflineResearchExperimentContractValidationError(
            "a verified baseline A strategy contract is required."
        )

    contract = OfflineResearchExperimentContract(
        schema_version=OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_SCHEMA_VERSION,
        experiment_id=experiment_id,
        experiment_version=experiment_version,
        created_at_utc=created_at_utc or datetime.now(timezone.utc),
        purpose=purpose,
        artifact_reference=artifact_reference,
        strategy_contract=strategy_contract,
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
        symbol=symbol,
        interval=interval,
        entry_fee_rate=entry_fee_rate,
        exit_fee_rate=exit_fee_rate,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        leverage=leverage,
        initial_capital=initial_capital,
        risk_percent=risk_percent,
        extra_parameters=extra_parameters or {},
        historical_research_only=historical_research_only,
        operational_evidence=operational_evidence,
        paper_promotion_eligible=paper_promotion_eligible,
        paper_trading_enabled=paper_trading_enabled,
        live_trading_enabled=live_trading_enabled,
        execution_enabled=execution_enabled,
        order_submission_enabled=order_submission_enabled,
        credentials_required=credentials_required,
        exchange_api_enabled=exchange_api_enabled,
        download_enabled=download_enabled,
        ingestion_enabled=ingestion_enabled,
        allowed_use_cases=(
            OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_ALLOWED_USE_CASES
            if allowed_use_cases is None
            else allowed_use_cases
        ),
        prohibited_use_cases=(
            OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_PROHIBITED_USE_CASES
            if prohibited_use_cases is None
            else prohibited_use_cases
        ),
        non_operational_declaration=non_operational_declaration,
    )
    if contract.as_dict() != serialize_value(contract.canonical_payload(include_contract_hash=True)):
        raise OfflineResearchExperimentContractIntegrityError("experiment contract payload mismatch.")
    return contract


__all__ = [
    "OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_ALLOWED_USE_CASES",
    "OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_ID",
    "OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_NON_OPERATIONAL_DECLARATION",
    "OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_PROHIBITED_USE_CASES",
    "OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_PURPOSE",
    "OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_SCHEMA_VERSION",
    "OFFLINE_RESEARCH_EXPERIMENT_CONTRACT_VERSION",
    "OfflineResearchExperimentContract",
    "OfflineResearchExperimentContractError",
    "OfflineResearchExperimentContractIntegrityError",
    "OfflineResearchExperimentContractValidationError",
    "build_offline_research_experiment_contract",
]
