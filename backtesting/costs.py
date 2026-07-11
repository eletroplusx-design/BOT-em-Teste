from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from domain import Direction

from domain.validation import parse_decimal


@dataclass(frozen=True, slots=True)
class CostModel:
    commission_rate: Decimal = Decimal("0.0004")
    slippage_rate: Decimal = Decimal("0.0005")

    def __post_init__(self) -> None:
        object.__setattr__(self, "commission_rate", parse_decimal(self.commission_rate, "commission_rate", allow_zero=True))
        object.__setattr__(self, "slippage_rate", parse_decimal(self.slippage_rate, "slippage_rate", allow_zero=True))

    def fee(self, notional: Decimal) -> Decimal:
        notional = parse_decimal(notional, "notional", allow_zero=True, allow_negative=True)
        return abs(notional) * self.commission_rate

    def apply_entry_slippage(self, price: Decimal, direction: Direction) -> Decimal:
        price = parse_decimal(price, "price")
        if direction == Direction.COMPRA:
            return price * (Decimal("1") + self.slippage_rate)
        return price * (Decimal("1") - self.slippage_rate)

    def apply_exit_slippage(self, price: Decimal, direction: Direction) -> Decimal:
        price = parse_decimal(price, "price")
        if direction == Direction.COMPRA:
            return price * (Decimal("1") - self.slippage_rate)
        return price * (Decimal("1") + self.slippage_rate)
