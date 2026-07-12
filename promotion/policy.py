from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .errors import PromotionPolicyError


def _strict_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise PromotionPolicyError(f"{field_name} must be an integer.")
    if allow_zero and value < 0:
        raise PromotionPolicyError(f"{field_name} cannot be negative.")
    if not allow_zero and value <= 0:
        raise PromotionPolicyError(f"{field_name} must be greater than zero.")
    return int(value)


def _to_decimal(value: Any, field_name: str, *, allow_zero: bool = True) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    else:
        try:
            result = Decimal(str(value))
        except Exception as exc:
            raise PromotionPolicyError(f"{field_name} must be numeric.") from exc
    if not result.is_finite():
        raise PromotionPolicyError(f"{field_name} must be finite.")
    if allow_zero:
        if result < 0:
            raise PromotionPolicyError(f"{field_name} cannot be negative.")
    elif result <= 0:
        raise PromotionPolicyError(f"{field_name} must be greater than zero.")
    return result


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    min_oos_windows: int = 3
    min_oos_trades: int = 30
    min_oos_net_return_percent: Decimal = Decimal("0")
    min_oos_expectancy: Decimal = Decimal("0")
    min_oos_profit_factor: Decimal = Decimal("1.10")
    max_oos_drawdown_percent: Decimal = Decimal("15")
    min_profitable_window_ratio_percent: Decimal = Decimal("60")
    max_validation_degradation_percent: Decimal = Decimal("10")
    require_runner_trusted: bool = True
    require_paper_only: bool = True
    require_leak_free_engine: bool = True
    require_nonzero_costs: bool = True
    require_complete_manifest: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "min_oos_windows", _strict_int(self.min_oos_windows, "min_oos_windows"))
        object.__setattr__(self, "min_oos_trades", _strict_int(self.min_oos_trades, "min_oos_trades"))
        object.__setattr__(self, "min_oos_net_return_percent", _to_decimal(self.min_oos_net_return_percent, "min_oos_net_return_percent"))
        object.__setattr__(self, "min_oos_expectancy", _to_decimal(self.min_oos_expectancy, "min_oos_expectancy"))
        object.__setattr__(self, "min_oos_profit_factor", _to_decimal(self.min_oos_profit_factor, "min_oos_profit_factor", allow_zero=False))
        object.__setattr__(self, "max_oos_drawdown_percent", _to_decimal(self.max_oos_drawdown_percent, "max_oos_drawdown_percent"))
        object.__setattr__(self, "min_profitable_window_ratio_percent", _to_decimal(self.min_profitable_window_ratio_percent, "min_profitable_window_ratio_percent"))
        object.__setattr__(self, "max_validation_degradation_percent", _to_decimal(self.max_validation_degradation_percent, "max_validation_degradation_percent"))
        if self.min_profitable_window_ratio_percent > Decimal("100"):
            raise PromotionPolicyError("min_profitable_window_ratio_percent cannot exceed 100.")
        if self.max_oos_drawdown_percent < 0 or self.max_validation_degradation_percent < 0:
            raise PromotionPolicyError("percentage thresholds cannot be negative.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_oos_windows": self.min_oos_windows,
            "min_oos_trades": self.min_oos_trades,
            "min_oos_net_return_percent": self.min_oos_net_return_percent,
            "min_oos_expectancy": self.min_oos_expectancy,
            "min_oos_profit_factor": self.min_oos_profit_factor,
            "max_oos_drawdown_percent": self.max_oos_drawdown_percent,
            "min_profitable_window_ratio_percent": self.min_profitable_window_ratio_percent,
            "max_validation_degradation_percent": self.max_validation_degradation_percent,
            "require_runner_trusted": self.require_runner_trusted,
            "require_paper_only": self.require_paper_only,
            "require_leak_free_engine": self.require_leak_free_engine,
            "require_nonzero_costs": self.require_nonzero_costs,
            "require_complete_manifest": self.require_complete_manifest,
        }
