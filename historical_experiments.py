from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from backtesting import BacktestConfig, BacktestResult, LeakFreeBacktestEngine
from domain.serialization import serialize_value
from historical_replay import (
    HistoricalBacktestReplay,
    HistoricalDataset,
    HistoricalReplayIntegrityError,
    HistoricalReplayProvenance,
    HistoricalReplayValidationError,
    HistoricalWalkForwardReplay,
    load_historical_replay_dataset,
    replay_historical_backtest,
    replay_historical_walk_forward,
)
from validation import CandidateConfig, SelectionCriteria, TrustedLeakFreeBacktestRunner, ValidationSplitConfig, WalkForwardResult


class HistoricalExperimentError(Exception):
    """Base error for historical experiment contracts."""


class HistoricalExperimentValidationError(HistoricalExperimentError):
    """Raised when a historical experiment contract is invalid."""


class HistoricalExperimentIntegrityError(HistoricalExperimentValidationError):
    """Raised when a persisted experiment artifact is inconsistent."""


class HistoricalExperimentConflictError(HistoricalExperimentIntegrityError):
    """Raised when a write-once experiment artifact already exists and differs."""


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalExperimentValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalExperimentValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalExperimentValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalExperimentValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalExperimentValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalExperimentValidationError(f"{field_name} must be timezone-aware UTC datetime.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalExperimentValidationError(f"{field_name} must be timezone-aware UTC datetime.") from exc
    if not isinstance(value, datetime):
        raise HistoricalExperimentValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoricalExperimentValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _normalize_contract_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    return value


def _mapping_or_dict(value: Mapping[str, Any] | dict[str, Any] | None, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise HistoricalExperimentValidationError(f"{field_name} must be a mapping.")
    return dict(value)


def _ensure_dataset(source: str | Path | HistoricalDataset) -> HistoricalDataset:
    try:
        return load_historical_replay_dataset(source)
    except (HistoricalReplayValidationError, HistoricalReplayIntegrityError) as exc:
        raise HistoricalExperimentValidationError(str(exc)) from exc


def _callable_identity(strategy: Callable[..., Any]) -> Callable[..., Any]:
    if not callable(strategy):
        raise HistoricalExperimentValidationError("strategy must be callable.")
    target = inspect.unwrap(strategy)
    if not (inspect.isfunction(target) or inspect.ismethod(target)):
        raise HistoricalExperimentValidationError("strategy must be a function or method with inspectable source.")
    module_name = getattr(target, "__module__", "")
    qualname = getattr(target, "__qualname__", "")
    if not module_name or not qualname:
        raise HistoricalExperimentValidationError("strategy must have a stable module and qualname.")
    if "<lambda>" in qualname or target.__name__ == "<lambda>":
        raise HistoricalExperimentValidationError("lambda strategies are not allowed.")
    if "<locals>" in qualname:
        raise HistoricalExperimentValidationError("nested or ambiguous strategy callables are not allowed.")
    closure = getattr(target, "__closure__", None)
    if closure:
        raise HistoricalExperimentValidationError("strategy closures are not allowed.")
    try:
        source = inspect.getsource(target)
    except Exception as exc:
        raise HistoricalExperimentValidationError("strategy source must be inspectable.") from exc
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    source_hash = sha256(source.encode("utf-8")).hexdigest()
    return target, module_name, qualname, source, source_hash


@dataclass(frozen=True, slots=True)
class HistoricalStrategyFingerprint:
    module: str
    qualname: str
    source: str
    source_hash: str
    identity: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "module", _require_str(self.module, "module"))
        object.__setattr__(self, "qualname", _require_str(self.qualname, "qualname"))
        if not isinstance(self.source, str) or not self.source.strip():
            raise HistoricalExperimentValidationError("source is required.")
        object.__setattr__(self, "source_hash", _require_str(self.source_hash, "source_hash"))
        if not self.identity:
            object.__setattr__(self, "identity", f"{self.module}:{self.qualname}")
        if self.source_hash != sha256(self.source.encode("utf-8")).hexdigest():
            raise HistoricalExperimentValidationError("strategy source hash mismatch.")

    @classmethod
    def from_callable(cls, strategy: Callable[..., Any]) -> "HistoricalStrategyFingerprint":
        _, module_name, qualname, source, source_hash = _callable_identity(strategy)
        return cls(module=module_name, qualname=qualname, source=source, source_hash=source_hash)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalStrategyFingerprint":
        mapping = dict(data)
        return cls(
            module=mapping["module"],
            qualname=mapping["qualname"],
            source=mapping["source"],
            source_hash=mapping["source_hash"],
            identity=mapping.get("identity", ""),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "qualname": self.qualname,
            "source": self.source,
            "source_hash": self.source_hash,
            "identity": self.identity,
        }


@dataclass(frozen=True, slots=True)
class HistoricalExperimentPlan:
    historical_provenance: HistoricalReplayProvenance
    mode: str
    strategy_version: str
    strategy_fingerprint: HistoricalStrategyFingerprint
    execution_contract: dict[str, Any]
    costs: dict[str, Any]
    symbol: str
    interval: str
    seed: int | None
    candidate_grid: tuple[CandidateConfig, ...] = ()
    selection_criteria: SelectionCriteria | None = None
    split_config: ValidationSplitConfig | None = None
    intrabar_policy: Any = None
    gap_policy: Any = None
    classification: str = "historical_research_only"
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    plan_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.historical_provenance, HistoricalReplayProvenance):
            raise HistoricalExperimentValidationError("historical_provenance must be a HistoricalReplayProvenance instance.")
        object.__setattr__(self, "mode", _require_str(self.mode, "mode").lower())
        if self.mode not in {"backtest", "walk_forward"}:
            raise HistoricalExperimentValidationError("mode must be backtest or walk_forward.")
        object.__setattr__(self, "strategy_version", _require_str(self.strategy_version, "strategy_version"))
        if not isinstance(self.strategy_fingerprint, HistoricalStrategyFingerprint):
            raise HistoricalExperimentValidationError("strategy_fingerprint must be a HistoricalStrategyFingerprint instance.")
        if not isinstance(self.execution_contract, Mapping):
            raise HistoricalExperimentValidationError("execution_contract must be a mapping.")
        if not isinstance(self.costs, Mapping):
            raise HistoricalExperimentValidationError("costs must be a mapping.")
        object.__setattr__(self, "execution_contract", dict(self.execution_contract))
        object.__setattr__(self, "costs", dict(self.costs))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        if self.seed is not None:
            object.__setattr__(self, "seed", _require_int(self.seed, "seed", allow_zero=True))
        object.__setattr__(self, "candidate_grid", tuple(self.candidate_grid))
        if any(not isinstance(candidate, CandidateConfig) for candidate in self.candidate_grid):
            raise HistoricalExperimentValidationError("candidate_grid must contain CandidateConfig entries.")
        if self.selection_criteria is not None and not isinstance(self.selection_criteria, SelectionCriteria):
            raise HistoricalExperimentValidationError("selection_criteria must be a SelectionCriteria instance.")
        if self.split_config is not None and not isinstance(self.split_config, ValidationSplitConfig):
            raise HistoricalExperimentValidationError("split_config must be a ValidationSplitConfig instance.")
        object.__setattr__(self, "classification", _require_str(self.classification, "classification"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.classification != "historical_research_only":
            raise HistoricalExperimentValidationError("classification must be historical_research_only.")
        if self.operational_evidence is not False:
            raise HistoricalExperimentValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise HistoricalExperimentValidationError("paper_promotion_eligible must be false.")
        if self.mode == "walk_forward":
            if not self.candidate_grid:
                raise HistoricalExperimentValidationError("candidate_grid is required for walk_forward experiments.")
            if self.selection_criteria is None:
                raise HistoricalExperimentValidationError("selection_criteria is required for walk_forward experiments.")
            if self.split_config is None:
                raise HistoricalExperimentValidationError("split_config is required for walk_forward experiments.")
        if self.execution_contract.get("symbol") not in (None, self.symbol):
            raise HistoricalExperimentValidationError("execution contract symbol diverges from experiment symbol.")
        if self.execution_contract.get("interval") not in (None, self.interval):
            raise HistoricalExperimentValidationError("execution contract interval diverges from experiment interval.")
        if self.execution_contract.get("paper_only") is not True:
            raise HistoricalExperimentValidationError("execution contract must remain paper-only.")
        if self.execution_contract.get("engine_class") != "LeakFreeBacktestEngine":
            raise HistoricalExperimentValidationError("execution contract engine class must be LeakFreeBacktestEngine.")
        if self.execution_contract.get("strategy_version") not in (None, self.strategy_version):
            raise HistoricalExperimentValidationError("execution contract strategy_version diverges from experiment strategy_version.")
        if self.intrabar_policy is None or self.gap_policy is None:
            raise HistoricalExperimentValidationError("intrabar_policy and gap_policy are required.")
        if not self.plan_hash:
            object.__setattr__(self, "plan_hash", _hash_payload(self.as_hash_payload(include_hash=False)))
        else:
            expected = _hash_payload(self.as_hash_payload(include_hash=False))
            if self.plan_hash != expected:
                raise HistoricalExperimentValidationError("experiment plan hash mismatch.")

    @property
    def provenance(self) -> HistoricalReplayProvenance:
        return self.historical_provenance

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "historical_provenance": self.historical_provenance.as_dict(),
            "mode": self.mode,
            "strategy_version": self.strategy_version,
            "strategy_fingerprint": self.strategy_fingerprint.as_dict(),
            "execution_contract": serialize_value(self.execution_contract),
            "costs": serialize_value(self.costs),
            "symbol": self.symbol,
            "interval": self.interval,
            "seed": self.seed,
            "candidate_grid": [candidate.as_dict() for candidate in self.candidate_grid],
            "selection_criteria": self.selection_criteria.as_dict() if self.selection_criteria is not None else None,
            "split_config": self.split_config.as_dict() if self.split_config is not None else None,
            "intrabar_policy": serialize_value(self.intrabar_policy),
            "gap_policy": serialize_value(self.gap_policy),
            "classification": self.classification,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }
        if include_hash:
            payload["plan_hash"] = self.plan_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalExperimentPlan":
        mapping = dict(data)
        provenance = HistoricalReplayProvenance(**mapping["historical_provenance"])
        strategy_fingerprint = HistoricalStrategyFingerprint.from_dict(mapping["strategy_fingerprint"])
        candidate_grid = tuple(
            CandidateConfig.from_mapping(candidate["name"], candidate.get("parameters", {}))
            for candidate in mapping.get("candidate_grid", [])
        )
        selection_criteria = None
        if mapping.get("selection_criteria") is not None:
            selection_criteria = SelectionCriteria(**dict(mapping["selection_criteria"]))
        split_config = None
        if mapping.get("split_config") is not None:
            split_config = ValidationSplitConfig(**dict(mapping["split_config"]))
        return cls(
            historical_provenance=provenance,
            mode=mapping["mode"],
            strategy_version=mapping["strategy_version"],
            strategy_fingerprint=strategy_fingerprint,
            execution_contract=_mapping_or_dict(mapping.get("execution_contract"), "execution_contract"),
            costs=_mapping_or_dict(mapping.get("costs"), "costs"),
            symbol=mapping["symbol"],
            interval=mapping["interval"],
            seed=mapping.get("seed"),
            candidate_grid=candidate_grid,
            selection_criteria=selection_criteria,
            split_config=split_config,
            intrabar_policy=mapping.get("intrabar_policy"),
            gap_policy=mapping.get("gap_policy"),
            classification=mapping.get("classification", "historical_research_only"),
            operational_evidence=mapping.get("operational_evidence", False),
            paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
            plan_hash=mapping.get("plan_hash", ""),
        )


@dataclass(frozen=True, slots=True)
class HistoricalExperimentReport:
    mode: str
    plan: HistoricalExperimentPlan
    historical_provenance: HistoricalReplayProvenance
    historical_dataset: Any
    replay: Any
    result: Any
    execution_contract: dict[str, Any]
    result_hash: str
    replay_hash: str
    classification: str = "historical_research_only"
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    report_hash: str = field(default="", compare=False)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc), compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.plan, HistoricalExperimentPlan):
            raise HistoricalExperimentValidationError("plan must be a HistoricalExperimentPlan instance.")
        if not isinstance(self.historical_provenance, HistoricalReplayProvenance):
            raise HistoricalExperimentValidationError("historical_provenance must be a HistoricalReplayProvenance instance.")
        if not isinstance(self.historical_dataset, Mapping) and not hasattr(self.historical_dataset, "as_dict"):
            raise HistoricalExperimentValidationError("historical_dataset must be a validated dataset or mapping.")
        object.__setattr__(self, "mode", _require_str(self.mode, "mode").lower())
        if self.mode not in {"backtest", "walk_forward"}:
            raise HistoricalExperimentValidationError("mode must be backtest or walk_forward.")
        if not isinstance(self.execution_contract, Mapping):
            raise HistoricalExperimentValidationError("execution_contract must be a mapping.")
        object.__setattr__(self, "execution_contract", dict(self.execution_contract))
        object.__setattr__(self, "result_hash", _require_str(self.result_hash, "result_hash"))
        object.__setattr__(self, "replay_hash", _require_str(self.replay_hash, "replay_hash"))
        object.__setattr__(self, "classification", _require_str(self.classification, "classification"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        if self.plan.historical_provenance != self.historical_provenance:
            raise HistoricalExperimentValidationError("report provenance diverges from plan provenance.")
        if self.plan.mode != self.mode:
            raise HistoricalExperimentValidationError("report mode diverges from plan mode.")
        if self.classification != "historical_research_only":
            raise HistoricalExperimentValidationError("classification must be historical_research_only.")
        if self.operational_evidence is not False:
            raise HistoricalExperimentValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise HistoricalExperimentValidationError("paper_promotion_eligible must be false.")
        if not self.report_hash:
            object.__setattr__(self, "report_hash", _hash_payload(self.as_hash_payload(include_hash=False)))
        else:
            expected = _hash_payload(self.as_hash_payload(include_hash=False))
            if self.report_hash != expected:
                raise HistoricalExperimentValidationError("historical experiment report hash mismatch.")
        dataset_payload = self.historical_dataset.as_dict() if hasattr(self.historical_dataset, "as_dict") else dict(self.historical_dataset)
        result_payload = self.result.to_dict() if hasattr(self.result, "to_dict") else self.result.as_dict() if hasattr(self.result, "as_dict") else self.result
        if self.mode == "backtest":
            expected_replay_hash = _hash_payload(
                {
                    "dataset": dataset_payload,
                    "provenance": self.historical_provenance.as_dict(),
                    "execution_contract": self.execution_contract,
                    "result": result_payload,
                }
            )
        else:
            expected_replay_hash = _hash_payload(
                {
                    "dataset": dataset_payload,
                    "provenance": self.historical_provenance.as_dict(),
                    "result": result_payload,
                }
            )
        if self.replay_hash != expected_replay_hash:
            raise HistoricalExperimentValidationError("historical experiment replay hash mismatch.")
        if self.result_hash != _hash_payload(result_payload):
            raise HistoricalExperimentValidationError("historical experiment result hash mismatch.")
        if self.execution_contract != self.plan.execution_contract:
            raise HistoricalExperimentValidationError("report execution contract diverges from plan execution contract.")

    @property
    def provenance(self) -> HistoricalReplayProvenance:
        return self.historical_provenance

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "mode": self.mode,
            "classification": self.classification,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "plan_hash": self.plan.plan_hash,
            "historical_provenance": self.historical_provenance.as_dict(),
            "historical_dataset": self.historical_dataset.as_dict() if hasattr(self.historical_dataset, "as_dict") else dict(self.historical_dataset),
            "execution_contract": serialize_value(self.execution_contract),
            "replay_hash": self.replay_hash,
            "result_hash": self.result_hash,
        }
        if include_hash:
            payload["report_hash"] = self.report_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "classification": self.classification,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "plan": self.plan.as_dict(),
            "historical_provenance": self.historical_provenance.as_dict(),
            "historical_dataset": serialize_value(self.historical_dataset.as_dict() if hasattr(self.historical_dataset, "as_dict") else self.historical_dataset),
            "execution_contract": serialize_value(self.execution_contract),
            "replay": serialize_value(self.replay.as_dict() if hasattr(self.replay, "as_dict") else self.replay),
            "result": serialize_value(self.result.to_dict() if hasattr(self.result, "to_dict") else self.result.as_dict() if hasattr(self.result, "as_dict") else self.result),
            "replay_hash": self.replay_hash,
            "result_hash": self.result_hash,
            "report_hash": self.report_hash,
            "created_at_utc": self.created_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalExperimentReport":
        mapping = dict(data)
        plan = HistoricalExperimentPlan.from_dict(mapping["plan"])
        provenance = HistoricalReplayProvenance(**mapping["historical_provenance"])
        historical_dataset = mapping["historical_dataset"]
        replay = mapping["replay"]
        result = mapping["result"]
        return cls(
            mode=mapping["mode"],
            plan=plan,
            historical_provenance=provenance,
            historical_dataset=historical_dataset,
            replay=replay,
            result=result,
            execution_contract=_mapping_or_dict(mapping.get("execution_contract"), "execution_contract"),
            result_hash=mapping["result_hash"],
            replay_hash=mapping["replay_hash"],
            classification=mapping.get("classification", "historical_research_only"),
            operational_evidence=mapping.get("operational_evidence", False),
            paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
            report_hash=mapping.get("report_hash", ""),
            created_at_utc=mapping["created_at_utc"],
        )

    @classmethod
    def from_backtest(
        cls,
        *,
        plan: HistoricalExperimentPlan,
        historical_dataset: HistoricalDataset | Mapping[str, Any],
        replay: HistoricalBacktestReplay,
    ) -> "HistoricalExperimentReport":
        result = replay.result
        result_hash = _hash_payload(result.to_dict())
        return cls(
            mode="backtest",
            plan=plan,
            historical_provenance=plan.historical_provenance,
            historical_dataset=historical_dataset,
            replay=replay,
            result=result,
            execution_contract=dict(replay.execution_contract),
            result_hash=result_hash,
            replay_hash=replay.replay_hash,
        )

    @classmethod
    def from_walk_forward(
        cls,
        *,
        plan: HistoricalExperimentPlan,
        historical_dataset: HistoricalDataset | Mapping[str, Any],
        replay: HistoricalWalkForwardReplay,
    ) -> "HistoricalExperimentReport":
        result = replay.result
        result_hash = _hash_payload(result.as_dict())
        return cls(
            mode="walk_forward",
            plan=plan,
            historical_provenance=plan.historical_provenance,
            historical_dataset=historical_dataset,
            replay=replay,
            result=result,
            execution_contract=dict(replay.execution_contract),
            result_hash=result_hash,
            replay_hash=replay.replay_hash,
        )


def build_historical_experiment_plan(
    source: str | Path | HistoricalDataset,
    *,
    mode: str,
    strategy_callable: Callable[..., Any],
    strategy_version: str,
    execution_contract: Mapping[str, Any],
    costs: Mapping[str, Any],
    symbol: str | None = None,
    interval: str | None = None,
    seed: int | None = None,
    candidate_grid: Sequence[CandidateConfig] = (),
    selection_criteria: SelectionCriteria | None = None,
    split_config: ValidationSplitConfig | None = None,
    intrabar_policy: Any = None,
    gap_policy: Any = None,
) -> HistoricalExperimentPlan:
    dataset = _ensure_dataset(source)
    provenance = HistoricalReplayProvenance.from_dataset(dataset)
    if symbol is not None and _require_str(symbol, "symbol").upper() != provenance.symbol:
        raise HistoricalExperimentValidationError("symbol diverges from historical dataset.")
    if interval is not None and _require_str(interval, "interval") != provenance.interval:
        raise HistoricalExperimentValidationError("interval diverges from historical dataset.")
    _callable_identity(strategy_callable)
    if intrabar_policy is None and "intrabar_policy" in execution_contract:
        intrabar_policy = execution_contract.get("intrabar_policy")
    if gap_policy is None and "gap_policy" in execution_contract:
        gap_policy = execution_contract.get("gap_policy")
    plan = HistoricalExperimentPlan(
        historical_provenance=provenance,
        mode=mode,
        strategy_version=strategy_version,
        strategy_fingerprint=HistoricalStrategyFingerprint.from_callable(strategy_callable),
        execution_contract=dict(execution_contract),
        costs=dict(costs),
        symbol=provenance.symbol,
        interval=provenance.interval,
        seed=seed,
        candidate_grid=tuple(candidate_grid),
        selection_criteria=selection_criteria,
        split_config=split_config,
        intrabar_policy=intrabar_policy,
        gap_policy=gap_policy,
    )
    return plan


def _engine_execution_contract(engine: LeakFreeBacktestEngine) -> dict[str, Any]:
    config = getattr(engine, "config", None)
    if not isinstance(config, BacktestConfig):
        raise HistoricalExperimentValidationError("engine config must be BacktestConfig.")
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


def _ensure_result_kind(replay: HistoricalBacktestReplay | HistoricalWalkForwardReplay, mode: str) -> None:
    if mode == "backtest" and not isinstance(replay, HistoricalBacktestReplay):
        raise HistoricalExperimentValidationError("backtest replay result is required.")
    if mode == "walk_forward" and not isinstance(replay, HistoricalWalkForwardReplay):
        raise HistoricalExperimentValidationError("walk-forward replay result is required.")


def run_historical_backtest_experiment(
    source: str | Path | HistoricalDataset,
    *,
    engine: LeakFreeBacktestEngine,
    strategy_callable: Callable[..., Any],
    output_file: str | Path | None = None,
) -> HistoricalExperimentReport:
    dataset = _ensure_dataset(source)
    execution_contract = _engine_execution_contract(engine)
    plan = build_historical_experiment_plan(
        dataset,
        mode="backtest",
        strategy_callable=strategy_callable,
        strategy_version=execution_contract["strategy_version"],
        execution_contract=execution_contract,
        costs={
            "entry_fee_rate": execution_contract["entry_fee_rate"],
            "exit_fee_rate": execution_contract["exit_fee_rate"],
            "spread_bps": execution_contract["spread_bps"],
            "slippage_bps": execution_contract["slippage_bps"],
            "leverage": execution_contract["leverage"],
            "intrabar_policy": execution_contract["intrabar_policy"],
            "gap_policy": execution_contract["gap_policy"],
        },
        intrabar_policy=execution_contract["intrabar_policy"],
        gap_policy=execution_contract["gap_policy"],
    )
    replay = replay_historical_backtest(dataset, engine=engine, strategy_callback=strategy_callable)
    _ensure_result_kind(replay, "backtest")
    report = HistoricalExperimentReport.from_backtest(plan=plan, historical_dataset=dataset, replay=replay)
    if output_file is not None:
        save_historical_experiment_report(output_file, report)
    return report


def run_historical_walk_forward_experiment(
    source: str | Path | HistoricalDataset,
    *,
    runner: TrustedLeakFreeBacktestRunner,
    candidate_grid: Sequence[CandidateConfig],
    split_config: ValidationSplitConfig | None = None,
    selection_criteria: SelectionCriteria | None = None,
    strategy_version: str = "v4_walk_forward",
    costs: Mapping[str, Any] | None = None,
    seed: int | None = None,
    output_file: str | Path | None = None,
) -> HistoricalExperimentReport:
    dataset = _ensure_dataset(source)
    if not isinstance(runner, TrustedLeakFreeBacktestRunner):
        raise HistoricalExperimentValidationError("historical walk-forward requires TrustedLeakFreeBacktestRunner.")
    runner_contract = runner.execution_contract()
    plan = build_historical_experiment_plan(
        dataset,
        mode="walk_forward",
        strategy_callable=runner.strategy_factory,
        strategy_version=strategy_version,
        execution_contract=runner_contract,
        costs=dict(costs or {}),
        candidate_grid=tuple(candidate_grid),
        selection_criteria=selection_criteria or SelectionCriteria(),
        split_config=split_config or ValidationSplitConfig(),
        seed=seed,
        intrabar_policy=runner_contract.get("intrabar_policy"),
        gap_policy=runner_contract.get("gap_policy"),
    )
    replay = replay_historical_walk_forward(
        dataset,
        runner=runner,
        candidate_grid=candidate_grid,
        split_config=split_config,
        selection_criteria=selection_criteria,
        strategy_version=strategy_version,
        costs=costs,
        seed=seed,
    )
    _ensure_result_kind(replay, "walk_forward")
    report = HistoricalExperimentReport.from_walk_forward(plan=plan, historical_dataset=dataset, replay=replay)
    if output_file is not None:
        save_historical_experiment_report(output_file, report)
    return report


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise HistoricalExperimentValidationError("Historical experiment report not found.")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise HistoricalExperimentValidationError("Historical experiment report is empty.")
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise HistoricalExperimentValidationError("Historical experiment report is invalid JSON.") from exc
    if not isinstance(payload, Mapping):
        raise HistoricalExperimentValidationError("Historical experiment report must be a JSON object.")
    return payload


def _write_atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    canonical = _canonical_json(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == canonical:
            return
        raise HistoricalExperimentConflictError("Historical experiment report already exists and differs.")
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{id(path)}.tmp")
    try:
        tmp_path.write_text(canonical, encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HistoricalExperimentValidationError("Failed to write historical experiment report atomically.") from exc


def load_historical_experiment_report(path: str | Path) -> HistoricalExperimentReport:
    file_path = Path(path)
    payload = _read_json(file_path)
    try:
        report = HistoricalExperimentReport.from_dict(payload)
    except HistoricalExperimentValidationError as exc:
        raise HistoricalExperimentIntegrityError(str(exc)) from exc
    if report.as_dict() != payload:
        raise HistoricalExperimentIntegrityError("Historical experiment report payload mismatch.")
    if report.report_hash != _hash_payload(report.as_hash_payload(include_hash=False)):
        raise HistoricalExperimentIntegrityError("Historical experiment report hash mismatch.")
    return report


def save_historical_experiment_report(path: str | Path, report: HistoricalExperimentReport) -> HistoricalExperimentReport:
    file_path = Path(path)
    payload = report.as_dict()
    if file_path.exists():
        existing = load_historical_experiment_report(file_path)
        if existing.as_dict() != payload:
            raise HistoricalExperimentConflictError("Historical experiment report already exists and differs.")
        return existing
    _write_atomic_json(file_path, payload)
    return report


def verify_historical_experiment_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_experiment_report(path)
    return {
        "verified": True,
        "mode": report.mode,
        "classification": report.classification,
        "report_hash": report.report_hash,
        "plan_hash": report.plan.plan_hash,
        "replay_hash": report.replay_hash,
        "result_hash": report.result_hash,
    }


def status_historical_experiment_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_experiment_report(path)
    return {
        "exists": True,
        "mode": report.mode,
        "classification": report.classification,
        "report_hash": report.report_hash,
        "plan_hash": report.plan.plan_hash,
        "replay_hash": report.replay_hash,
        "result_hash": report.result_hash,
        "plan_mode": report.plan.mode,
        "symbol": report.plan.symbol,
        "interval": report.plan.interval,
    }


__all__ = [
    "HistoricalExperimentConflictError",
    "HistoricalExperimentError",
    "HistoricalExperimentIntegrityError",
    "HistoricalExperimentPlan",
    "HistoricalExperimentReport",
    "HistoricalExperimentValidationError",
    "HistoricalStrategyFingerprint",
    "build_historical_experiment_plan",
    "fingerprint_strategy_callable",
    "load_historical_experiment_report",
    "run_historical_backtest_experiment",
    "run_historical_walk_forward_experiment",
    "save_historical_experiment_report",
    "status_historical_experiment_report",
    "verify_historical_experiment_report",
]


def fingerprint_strategy_callable(strategy: Callable[..., Any]) -> HistoricalStrategyFingerprint:
    return HistoricalStrategyFingerprint.from_callable(strategy)
