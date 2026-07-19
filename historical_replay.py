from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from backtesting import BacktestResult, LeakFreeBacktestEngine
from backtesting.models import BacktestConfig
from domain import Candle
from domain.serialization import serialize_value
from validation import CandidateConfig, SelectionCriteria, TrustedLeakFreeBacktestRunner, ValidationSplitConfig, WalkForwardResult, WalkForwardValidator

from market_data import HistoricalDataset, HistoricalDataIntegrityError, HistoricalDataValidationError, load_historical_dataset_file


class HistoricalReplayError(Exception):
    pass


class HistoricalReplayValidationError(HistoricalReplayError):
    pass


class HistoricalReplayIntegrityError(HistoricalReplayValidationError):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalReplayValidationError(f"{field_name} is required.")
    return value.strip()


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalReplayValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalReplayValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalReplayValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalReplayValidationError(f"{field_name} must be a boolean.")
    return value


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalReplayValidationError(f"{field_name} must be timezone-aware UTC datetime.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalReplayValidationError(f"{field_name} must be timezone-aware UTC datetime.") from exc
    if not isinstance(value, datetime):
        raise HistoricalReplayValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoricalReplayValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _normalize_contract_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    return value


def _engine_execution_contract(engine: LeakFreeBacktestEngine) -> dict[str, Any]:
    config = getattr(engine, "config", None)
    if not isinstance(config, BacktestConfig):
        raise HistoricalReplayValidationError("engine config must be BacktestConfig.")
    return {
        "engine_class": engine.__class__.__name__,
        "entry_fee_rate": _normalize_contract_value(config.entry_fee_rate),
        "exit_fee_rate": _normalize_contract_value(config.exit_fee_rate),
        "spread_bps": _normalize_contract_value(config.spread_bps),
        "slippage_bps": _normalize_contract_value(config.slippage_bps),
        "leverage": _normalize_contract_value(config.leverage),
        "intrabar_policy": _normalize_contract_value(config.intrabar_policy),
        "gap_policy": _normalize_contract_value(config.gap_policy),
        "paper_only": config.paper_only,
        "symbol": config.symbol,
        "interval": config.interval,
        "strategy_version": config.strategy_version,
    }


def _coerce_dataset(source: str | Path | HistoricalDataset) -> HistoricalDataset:
    if isinstance(source, HistoricalDataset):
        return source
    if isinstance(source, (str, Path)):
        try:
            return load_historical_dataset_file(source)
        except (HistoricalDataValidationError, HistoricalDataIntegrityError) as exc:
            raise HistoricalReplayIntegrityError(str(exc)) from exc
    raise HistoricalReplayValidationError("historical replay requires a HistoricalDataset or path.")


@dataclass(frozen=True, slots=True)
class HistoricalReplayProvenance:
    dataset_id: str
    content_hash: str
    manifest_hash: str
    provider: str
    endpoint: str
    symbol: str
    interval: str
    effective_start_utc: datetime
    effective_end_utc: datetime
    candle_count: int
    schema_version: int = 1
    classification: str = "historical_research_only"
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_id", _require_str(self.dataset_id, "dataset_id"))
        object.__setattr__(self, "content_hash", _require_str(self.content_hash, "content_hash"))
        object.__setattr__(self, "manifest_hash", _require_str(self.manifest_hash, "manifest_hash"))
        object.__setattr__(self, "provider", _require_str(self.provider, "provider"))
        object.__setattr__(self, "endpoint", _require_str(self.endpoint, "endpoint"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "effective_start_utc", _require_utc_datetime(self.effective_start_utc, "effective_start_utc"))
        object.__setattr__(self, "effective_end_utc", _require_utc_datetime(self.effective_end_utc, "effective_end_utc"))
        object.__setattr__(self, "candle_count", _require_int(self.candle_count, "candle_count"))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "classification", _require_str(self.classification, "classification"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.classification != "historical_research_only":
            raise HistoricalReplayValidationError("classification must be historical_research_only.")
        if self.operational_evidence is not False:
            raise HistoricalReplayValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise HistoricalReplayValidationError("paper_promotion_eligible must be false.")

    @classmethod
    def from_dataset(cls, dataset: HistoricalDataset) -> "HistoricalReplayProvenance":
        manifest = dataset.manifest
        return cls(
            dataset_id=manifest.dataset_id,
            content_hash=manifest.content_hash,
            manifest_hash=manifest.manifest_hash,
            provider=manifest.provider,
            endpoint=manifest.endpoint,
            symbol=manifest.symbol,
            interval=manifest.interval,
            effective_start_utc=manifest.effective_start_utc,
            effective_end_utc=manifest.effective_end_utc,
            candle_count=manifest.candle_count,
            schema_version=1,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "content_hash": self.content_hash,
            "manifest_hash": self.manifest_hash,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "symbol": self.symbol,
            "interval": self.interval,
            "effective_start_utc": self.effective_start_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "effective_end_utc": self.effective_end_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "candle_count": self.candle_count,
            "schema_version": self.schema_version,
            "classification": self.classification,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }


@dataclass(frozen=True, slots=True)
class HistoricalBacktestReplay:
    result: BacktestResult
    provenance: HistoricalReplayProvenance
    execution_contract: dict[str, Any]
    replay_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "result": serialize_value(self.result.to_dict()),
            "provenance": self.provenance.as_dict(),
            "execution_contract": serialize_value(self.execution_contract),
            "replay_hash": self.replay_hash,
        }


@dataclass(frozen=True, slots=True)
class HistoricalWalkForwardReplay:
    result: WalkForwardResult
    provenance: HistoricalReplayProvenance
    execution_contract: dict[str, Any]
    replay_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "result": serialize_value(self.result.as_dict()),
            "provenance": self.provenance.as_dict(),
            "execution_contract": serialize_value(self.execution_contract),
            "replay_hash": self.replay_hash,
        }


def load_historical_replay_dataset(source: str | Path | HistoricalDataset) -> HistoricalDataset:
    return _coerce_dataset(source)


def historical_dataset_to_dataframe(source: str | Path | HistoricalDataset) -> pd.DataFrame:
    dataset = _coerce_dataset(source)
    rows = [
        {
            "open_time": candle.open_time,
            "close_time": candle.close_time,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
            "symbol": candle.symbol,
            "interval": candle.interval,
            "source": candle.source,
        }
        for candle in dataset.candles
    ]
    frame = pd.DataFrame(rows, columns=["open_time", "close_time", "open", "high", "low", "close", "volume", "symbol", "interval", "source"])
    if len(frame) != len(dataset.candles):
        raise HistoricalReplayIntegrityError("historical replay frame length mismatch.")
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    frame["close_time"] = pd.to_datetime(frame["close_time"], utc=True)
    frame.attrs["historical_dataset_id"] = dataset.manifest.dataset_id
    frame.attrs["historical_content_hash"] = dataset.manifest.content_hash
    frame.attrs["historical_manifest_hash"] = dataset.manifest.manifest_hash
    frame.attrs["historical_schema_version"] = dataset.manifest.schema_version
    frame.attrs["historical_classification"] = "historical_research_only"
    return frame


def replay_historical_backtest(
    source: str | Path | HistoricalDataset,
    *,
    engine: LeakFreeBacktestEngine,
    strategy_callback,
) -> HistoricalBacktestReplay:
    dataset = _coerce_dataset(source)
    provenance = HistoricalReplayProvenance.from_dataset(dataset)
    if not isinstance(engine, LeakFreeBacktestEngine):
        raise HistoricalReplayValidationError("historical backtest requires LeakFreeBacktestEngine.")
    if not callable(strategy_callback):
        raise HistoricalReplayValidationError("strategy_callback must be callable.")
    config = getattr(engine, "config", None)
    if not isinstance(config, BacktestConfig):
        raise HistoricalReplayValidationError("engine config must be BacktestConfig.")
    if config.paper_only is not True:
        raise HistoricalReplayValidationError("historical backtest engine must remain paper_only.")
    if config.symbol != dataset.manifest.symbol or config.interval != dataset.manifest.interval:
        raise HistoricalReplayValidationError("engine symbol or interval diverges from historical dataset.")
    result = engine.run(dataset.candles, strategy_callback)
    if not isinstance(result, BacktestResult):
        raise HistoricalReplayValidationError("historical backtest must return BacktestResult.")
    if result.config != config:
        raise HistoricalReplayValidationError("backtest result config must match engine config.")
    if result.config.paper_only is not True:
        raise HistoricalReplayValidationError("historical backtest result must remain paper_only.")
    execution_contract = _engine_execution_contract(engine)
    replay_hash = _hash_payload(
        {
            "dataset": dataset.as_dict(),
            "provenance": provenance.as_dict(),
            "execution_contract": execution_contract,
            "result": result.to_dict(),
        }
    )
    return HistoricalBacktestReplay(
        result=result,
        provenance=provenance,
        execution_contract=execution_contract,
        replay_hash=replay_hash,
    )


def replay_historical_walk_forward(
    source: str | Path | HistoricalDataset,
    *,
    runner: TrustedLeakFreeBacktestRunner,
    candidate_grid: Sequence[CandidateConfig],
    split_config: ValidationSplitConfig | None = None,
    selection_criteria: SelectionCriteria | None = None,
    strategy_version: str = "v4_walk_forward",
    costs: Mapping[str, Any] | None = None,
    seed: int | None = None,
) -> HistoricalWalkForwardReplay:
    dataset = _coerce_dataset(source)
    provenance = HistoricalReplayProvenance.from_dataset(dataset)
    if not isinstance(runner, TrustedLeakFreeBacktestRunner):
        raise HistoricalReplayValidationError("historical walk-forward requires TrustedLeakFreeBacktestRunner.")
    frame = historical_dataset_to_dataframe(dataset)
    validator = WalkForwardValidator(
        split_config=split_config or ValidationSplitConfig(),
        selection_criteria=selection_criteria or SelectionCriteria(),
        strategy_version=strategy_version,
        costs=dict(costs or {}),
        symbol=dataset.manifest.symbol,
        interval=dataset.manifest.interval,
        seed=seed,
        require_trusted_runner=True,
    )
    result = validator.run(frame, candidate_grid, runner=runner, historical_provenance=provenance.as_dict())
    if not isinstance(result, WalkForwardResult):
        raise HistoricalReplayValidationError("historical walk-forward must return WalkForwardResult.")
    historical_manifest = result.manifest.get("historical_provenance")
    if historical_manifest != provenance.as_dict():
        raise HistoricalReplayIntegrityError("historical provenance mismatch in walk-forward manifest.")
    replay_hash = _hash_payload(
        {
            "dataset": dataset.as_dict(),
            "provenance": provenance.as_dict(),
            "result": result.as_dict(),
        }
    )
    execution_contract = dict(result.manifest.get("execution_contract") or {})
    return HistoricalWalkForwardReplay(
        result=result,
        provenance=provenance,
        execution_contract=execution_contract,
        replay_hash=replay_hash,
    )
