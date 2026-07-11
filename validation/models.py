from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from .errors import ValidationSelectionError, ValidationSplitError


def _freeze_value(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((str(key), _freeze_value(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze_value(item) for item in value))
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValidationSelectionError("datetime values must be timezone-aware.")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value


def _to_decimal(value: Any, field_name: str, *, allow_none: bool = False) -> Decimal | None:
    if value is None:
        if allow_none:
            return None
        raise ValidationSelectionError(f"{field_name} is required.")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception as exc:  # pragma: no cover - safe coercion guard
        raise ValidationSelectionError(f"{field_name} must be numeric.") from exc


def _strict_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise ValidationSplitError(f"{field_name} must be an integer.")
    if not allow_zero and value <= 0:
        raise ValidationSplitError(f"{field_name} must be greater than zero.")
    if allow_zero and value < 0:
        raise ValidationSplitError(f"{field_name} cannot be negative.")
    return int(value)


@dataclass(frozen=True, slots=True)
class ValidationSplitConfig:
    mode: str = "rolling"
    train_bars: int = 120
    validation_bars: int = 40
    test_bars: int = 40
    step_bars: int | None = None
    warmup_bars: int = 20
    purge_bars: int = 5
    embargo_bars: int = 5
    min_total_trades: int = 5
    min_net_return: Decimal = Decimal("0")
    max_drawdown_percent: Decimal = Decimal("25")
    min_expectancy: Decimal = Decimal("0")
    require_defined_profit_factor: bool = True
    min_profit_factor: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        mode = str(self.mode).strip().lower()
        if mode not in {"rolling", "expanding"}:
            raise ValidationSplitError("mode must be rolling or expanding.")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "train_bars", _strict_int(self.train_bars, "train_bars"))
        object.__setattr__(self, "validation_bars", _strict_int(self.validation_bars, "validation_bars"))
        object.__setattr__(self, "test_bars", _strict_int(self.test_bars, "test_bars"))
        if self.step_bars is not None:
            object.__setattr__(self, "step_bars", _strict_int(self.step_bars, "step_bars"))
        object.__setattr__(self, "warmup_bars", _strict_int(self.warmup_bars, "warmup_bars", allow_zero=True))
        object.__setattr__(self, "purge_bars", _strict_int(self.purge_bars, "purge_bars", allow_zero=True))
        object.__setattr__(self, "embargo_bars", _strict_int(self.embargo_bars, "embargo_bars", allow_zero=True))
        object.__setattr__(self, "min_total_trades", _strict_int(self.min_total_trades, "min_total_trades", allow_zero=True))
        object.__setattr__(self, "min_net_return", _to_decimal(self.min_net_return, "min_net_return"))
        object.__setattr__(self, "max_drawdown_percent", _to_decimal(self.max_drawdown_percent, "max_drawdown_percent"))
        object.__setattr__(self, "min_expectancy", _to_decimal(self.min_expectancy, "min_expectancy"))
        object.__setattr__(self, "min_profit_factor", _to_decimal(self.min_profit_factor, "min_profit_factor"))

    @property
    def effective_step_bars(self) -> int:
        return int(self.step_bars) if self.step_bars is not None else int(self.test_bars)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "train_bars": int(self.train_bars),
            "validation_bars": int(self.validation_bars),
            "test_bars": int(self.test_bars),
            "step_bars": int(self.step_bars) if self.step_bars is not None else None,
            "warmup_bars": int(self.warmup_bars),
            "purge_bars": int(self.purge_bars),
            "embargo_bars": int(self.embargo_bars),
            "min_total_trades": int(self.min_total_trades),
            "min_net_return": self.min_net_return,
            "max_drawdown_percent": self.max_drawdown_percent,
            "min_expectancy": self.min_expectancy,
            "require_defined_profit_factor": self.require_defined_profit_factor,
            "min_profit_factor": self.min_profit_factor,
        }


@dataclass(frozen=True, slots=True)
class SelectionCriteria:
    min_total_trades: int = 5
    min_net_return: Decimal = Decimal("0")
    max_drawdown_percent: Decimal = Decimal("25")
    min_expectancy: Decimal = Decimal("0")
    require_defined_profit_factor: bool = True
    min_profit_factor: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        object.__setattr__(self, "min_total_trades", _strict_int(self.min_total_trades, "min_total_trades", allow_zero=True))
        object.__setattr__(self, "min_net_return", _to_decimal(self.min_net_return, "min_net_return"))
        object.__setattr__(self, "max_drawdown_percent", _to_decimal(self.max_drawdown_percent, "max_drawdown_percent"))
        object.__setattr__(self, "min_expectancy", _to_decimal(self.min_expectancy, "min_expectancy"))
        object.__setattr__(self, "min_profit_factor", _to_decimal(self.min_profit_factor, "min_profit_factor"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_total_trades": int(self.min_total_trades),
            "min_net_return": self.min_net_return,
            "max_drawdown_percent": self.max_drawdown_percent,
            "min_expectancy": self.min_expectancy,
            "require_defined_profit_factor": self.require_defined_profit_factor,
            "min_profit_factor": self.min_profit_factor,
        }


@dataclass(frozen=True, slots=True)
class WindowBounds:
    warmup_start: int
    train_start: int
    train_end: int
    validation_start: int
    validation_end: int
    test_start: int
    test_end: int
    mode: str = "rolling"

    def __post_init__(self) -> None:
        numbers = [
            self.warmup_start,
            self.train_start,
            self.train_end,
            self.validation_start,
            self.validation_end,
            self.test_start,
            self.test_end,
        ]
        if any(int(number) < 0 for number in numbers):
            raise ValidationSplitError("window bounds cannot be negative.")
        if not (self.warmup_start <= self.train_start <= self.train_end <= self.validation_start <= self.validation_end <= self.test_start <= self.test_end):
            raise ValidationSplitError("window bounds must be chronological and non-overlapping.")
        object.__setattr__(self, "mode", str(self.mode).strip().lower())

    def as_dict(self) -> dict[str, int | str]:
        return {
            "warmup_start": self.warmup_start,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "validation_start": self.validation_start,
            "validation_end": self.validation_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "mode": self.mode,
        }


@dataclass(frozen=True, slots=True)
class SegmentView:
    name: str
    frame: Any
    warmup_start: int
    segment_start: int
    segment_end: int
    trade_start_index: int
    warmup_rows: int
    segment_rows: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "warmup_start": self.warmup_start,
            "segment_start": self.segment_start,
            "segment_end": self.segment_end,
            "trade_start_index": self.trade_start_index,
            "warmup_rows": self.warmup_rows,
            "segment_rows": self.segment_rows,
        }


@dataclass(frozen=True, slots=True)
class CandidateConfig:
    name: str
    parameters: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        normalized = tuple(sorted((str(key), _freeze_value(value)) for key, value in self.parameters))
        object.__setattr__(self, "name", str(self.name).strip())
        object.__setattr__(self, "parameters", normalized)
        if not self.name:
            raise ValidationSelectionError("candidate name is required.")

    @classmethod
    def from_mapping(cls, name: str, parameters: Mapping[str, Any]) -> "CandidateConfig":
        return cls(name=name, parameters=tuple(parameters.items()))

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "parameters": {key: value for key, value in self.parameters}}

    @property
    def digest_source(self) -> dict[str, Any]:
        return self.as_dict()


@dataclass(frozen=True, slots=True)
class SegmentMetrics:
    capital_initial: Decimal
    capital_final: Decimal
    net_pnl: Decimal
    net_return_percent: Decimal
    gross_pnl: Decimal
    gross_profit: Decimal
    gross_loss: Decimal
    total_costs: Decimal
    total_fees: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    drawdown_max_percent: Decimal
    expectancy: Decimal
    profit_factor: Decimal | None
    payoff: Decimal | None
    win_rate: Decimal
    total_trades: int
    winning_trades: int = 0
    losing_trades: int = 0
    average_gain: Decimal | None = None
    average_loss: Decimal | None = None
    sequencia_maxima_perdas: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "capital_initial": self.capital_initial,
            "capital_final": self.capital_final,
            "net_pnl": self.net_pnl,
            "net_return_percent": self.net_return_percent,
            "gross_pnl": self.gross_pnl,
            "gross_profit": self.gross_profit,
            "gross_loss": self.gross_loss,
            "total_costs": self.total_costs,
            "total_fees": self.total_fees,
            "spread_cost": self.spread_cost,
            "slippage_cost": self.slippage_cost,
            "drawdown_max_percent": self.drawdown_max_percent,
            "expectancy": self.expectancy,
            "profit_factor": self.profit_factor,
            "payoff": self.payoff,
            "win_rate": self.win_rate,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "average_gain": self.average_gain,
            "average_loss": self.average_loss,
            "sequencia_maxima_perdas": self.sequencia_maxima_perdas,
        }

    @classmethod
    def from_summary(cls, summary: Mapping[str, Any]) -> "SegmentMetrics":
        if not summary:
            raise ValidationSelectionError("summary is required.")
        return cls(
            capital_initial=_to_decimal(summary.get("capital_initial", 0), "capital_initial") or Decimal("0"),
            capital_final=_to_decimal(summary.get("capital_final", 0), "capital_final") or Decimal("0"),
            net_pnl=_to_decimal(summary.get("net_pnl", 0), "net_pnl") or Decimal("0"),
            net_return_percent=_to_decimal(summary.get("return_net_percent", summary.get("lucro_total_percent", 0)), "net_return_percent") or Decimal("0"),
            gross_pnl=_to_decimal(summary.get("gross_pnl", 0), "gross_pnl") or Decimal("0"),
            gross_profit=_to_decimal(summary.get("gross_profit", 0), "gross_profit") or Decimal("0"),
            gross_loss=_to_decimal(summary.get("gross_loss", 0), "gross_loss") or Decimal("0"),
            total_costs=_to_decimal(summary.get("total_costs", summary.get("total_fees", 0)), "total_costs") or Decimal("0"),
            total_fees=_to_decimal(summary.get("total_fees", 0), "total_fees") or Decimal("0"),
            spread_cost=_to_decimal(summary.get("spread_cost", 0), "spread_cost") or Decimal("0"),
            slippage_cost=_to_decimal(summary.get("slippage_cost", 0), "slippage_cost") or Decimal("0"),
            drawdown_max_percent=_to_decimal(summary.get("drawdown_max_percent", 0), "drawdown_max_percent") or Decimal("0"),
            expectancy=_to_decimal(summary.get("expectancy", summary.get("expectativa_matematica_percentual", 0)), "expectancy") or Decimal("0"),
            profit_factor=_to_decimal(summary["profit_factor"], "profit_factor", allow_none=True) if "profit_factor" in summary else None,
            payoff=_to_decimal(summary.get("payoff"), "payoff", allow_none=True) if summary.get("payoff") is not None else None,
            win_rate=_to_decimal(summary.get("win_rate", 0), "win_rate") or Decimal("0"),
            total_trades=int(summary.get("total_trades", 0) or 0),
            winning_trades=int(summary.get("winning_trades", 0) or 0),
            losing_trades=int(summary.get("losing_trades", 0) or 0),
            average_gain=_to_decimal(summary.get("average_gain"), "average_gain", allow_none=True) if summary.get("average_gain") is not None else None,
            average_loss=_to_decimal(summary.get("average_loss"), "average_loss", allow_none=True) if summary.get("average_loss") is not None else None,
            sequencia_maxima_perdas=int(summary.get("sequencia_maxima_perdas", 0) or 0),
        )


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    candidate: CandidateConfig
    train_metrics: SegmentMetrics
    validation_metrics: SegmentMetrics
    stability_score: Decimal = Decimal("0")
    rejection_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.as_dict(),
            "train_metrics": self.train_metrics.as_dict(),
            "validation_metrics": self.validation_metrics.as_dict(),
            "stability_score": self.stability_score,
            "rejection_reason": self.rejection_reason,
        }


@dataclass(frozen=True, slots=True)
class FrozenSelection:
    candidate: CandidateConfig
    strategy_version: str
    costs: tuple[tuple[str, Any], ...]
    symbol: str
    interval: str
    frozen_at: datetime
    manifest_hash: str
    window_id: str

    def __post_init__(self) -> None:
        if self.frozen_at.tzinfo is None or self.frozen_at.utcoffset() is None:
            raise ValidationSelectionError("frozen_at must be timezone-aware.")
        object.__setattr__(self, "strategy_version", str(self.strategy_version).strip())
        object.__setattr__(self, "symbol", str(self.symbol).strip())
        object.__setattr__(self, "interval", str(self.interval).strip())
        object.__setattr__(self, "costs", tuple(sorted((str(key), _freeze_value(value)) for key, value in self.costs)))
        if not self.manifest_hash:
            raise ValidationSelectionError("manifest_hash is required.")
        if not self.window_id:
            raise ValidationSelectionError("window_id is required.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.as_dict(),
            "strategy_version": self.strategy_version,
            "costs": {key: value for key, value in self.costs},
            "symbol": self.symbol,
            "interval": self.interval,
            "frozen_at": self.frozen_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "manifest_hash": self.manifest_hash,
            "window_id": self.window_id,
        }


@dataclass(frozen=True, slots=True)
class WalkForwardWindowResult:
    bounds: WindowBounds
    candidate_evaluations: tuple[CandidateEvaluation, ...]
    selected_candidate: CandidateConfig | None
    frozen_selection: FrozenSelection | None
    test_metrics: SegmentMetrics | None
    manifest_hash: str
    approved: bool = False
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "bounds": self.bounds.as_dict(),
            "candidate_evaluations": [evaluation.as_dict() for evaluation in self.candidate_evaluations],
            "selected_candidate": self.selected_candidate.as_dict() if self.selected_candidate else None,
            "frozen_selection": self.frozen_selection.as_dict() if self.frozen_selection else None,
            "test_metrics": self.test_metrics.as_dict() if self.test_metrics else None,
            "manifest_hash": self.manifest_hash,
            "approved": self.approved,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    windows: tuple[WalkForwardWindowResult, ...]
    summary: dict[str, Any]
    manifest: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "windows": [window.as_dict() for window in self.windows],
            "summary": self.summary,
            "manifest": self.manifest,
        }


ValidationRunResult = WalkForwardResult
