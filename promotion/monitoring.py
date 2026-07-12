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
class MonitoredPaperLimits:
    paper_capital_max: Decimal = Decimal("10000")
    risk_per_trade_max_percent: Decimal = Decimal("1")
    max_positions: int = 1
    session_drawdown_max_percent: Decimal = Decimal("10")
    max_loss_streak: int = 3
    max_duration_hours: int = 8
    min_trades: int = 1
    max_trades: int = 100
    expired_data_policy: str = "BLOCK_AND_SUSPEND"
    suspension_policy: str = "AUTO_SUSPEND"
    kill_switch_required: bool = True
    live_trading_permanently_disabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "paper_capital_max", _to_decimal(self.paper_capital_max, "paper_capital_max"))
        object.__setattr__(self, "risk_per_trade_max_percent", _to_decimal(self.risk_per_trade_max_percent, "risk_per_trade_max_percent"))
        object.__setattr__(self, "max_positions", _strict_int(self.max_positions, "max_positions"))
        object.__setattr__(self, "session_drawdown_max_percent", _to_decimal(self.session_drawdown_max_percent, "session_drawdown_max_percent"))
        object.__setattr__(self, "max_loss_streak", _strict_int(self.max_loss_streak, "max_loss_streak"))
        object.__setattr__(self, "max_duration_hours", _strict_int(self.max_duration_hours, "max_duration_hours"))
        object.__setattr__(self, "min_trades", _strict_int(self.min_trades, "min_trades"))
        object.__setattr__(self, "max_trades", _strict_int(self.max_trades, "max_trades"))
        object.__setattr__(self, "expired_data_policy", str(self.expired_data_policy).strip().upper())
        object.__setattr__(self, "suspension_policy", str(self.suspension_policy).strip().upper())
        if self.kill_switch_required is not True:
            raise PromotionPolicyError("kill_switch_required must be True.")
        if self.live_trading_permanently_disabled is not True:
            raise PromotionPolicyError("live_trading_permanently_disabled must be True.")
        if self.max_trades < self.min_trades:
            raise PromotionPolicyError("max_trades must be greater than or equal to min_trades.")
        if self.expired_data_policy not in {"BLOCK", "SUSPEND", "BLOCK_AND_SUSPEND"}:
            raise PromotionPolicyError("expired_data_policy is invalid.")
        if self.suspension_policy not in {"AUTO_SUSPEND", "BLOCK_ONLY", "SUSPEND"}:
            raise PromotionPolicyError("suspension_policy is invalid.")

    @property
    def live_trading_allowed(self) -> bool:
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "paper_capital_max": self.paper_capital_max,
            "risk_per_trade_max_percent": self.risk_per_trade_max_percent,
            "max_positions": self.max_positions,
            "session_drawdown_max_percent": self.session_drawdown_max_percent,
            "max_loss_streak": self.max_loss_streak,
            "max_duration_hours": self.max_duration_hours,
            "min_trades": self.min_trades,
            "max_trades": self.max_trades,
            "expired_data_policy": self.expired_data_policy,
            "suspension_policy": self.suspension_policy,
            "kill_switch_required": self.kill_switch_required,
            "live_trading_permanently_disabled": self.live_trading_permanently_disabled,
        }
