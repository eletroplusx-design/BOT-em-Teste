from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from domain import Direction
from domain.validation import parse_decimal


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    base_price: Decimal
    fill_price: Decimal
    fee: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal


@dataclass(frozen=True, slots=True)
class CostModel:
    entry_fee_rate: Decimal = Decimal("0.0004")
    exit_fee_rate: Decimal = Decimal("0.0004")
    spread_bps: Decimal = Decimal("5")
    slippage_bps: Decimal = Decimal("5")

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_fee_rate", parse_decimal(self.entry_fee_rate, "entry_fee_rate", allow_zero=True))
        object.__setattr__(self, "exit_fee_rate", parse_decimal(self.exit_fee_rate, "exit_fee_rate", allow_zero=True))
        object.__setattr__(self, "spread_bps", parse_decimal(self.spread_bps, "spread_bps", allow_zero=True))
        object.__setattr__(self, "slippage_bps", parse_decimal(self.slippage_bps, "slippage_bps", allow_zero=True))

    def _spread_side_rate(self) -> Decimal:
        return self.spread_bps / Decimal("20000")

    def _slippage_side_rate(self) -> Decimal:
        return self.slippage_bps / Decimal("10000")

    def _side_adjustment(self) -> Decimal:
        return self._spread_side_rate() + self._slippage_side_rate()

    def _fill_price(self, price: Decimal, direction: Direction, side: str) -> Decimal:
        price = parse_decimal(price, "price")
        adjustment = self._side_adjustment()
        if side == "entry":
            if direction == Direction.COMPRA:
                return price * (Decimal("1") + adjustment)
            return price * (Decimal("1") - adjustment)
        if direction == Direction.COMPRA:
            return price * (Decimal("1") - adjustment)
        return price * (Decimal("1") + adjustment)

    def build_entry(self, base_price: Decimal, quantity: Decimal, direction: Direction) -> CostBreakdown:
        base_price = parse_decimal(base_price, "base_price")
        quantity = parse_decimal(quantity, "quantity")
        fill_price = self._fill_price(base_price, direction, "entry")
        fee = abs(fill_price * quantity) * self.entry_fee_rate
        spread_cost = abs(base_price * quantity) * self._spread_side_rate()
        slippage_cost = abs(base_price * quantity) * self._slippage_side_rate()
        return CostBreakdown(base_price=base_price, fill_price=fill_price, fee=fee, spread_cost=spread_cost, slippage_cost=slippage_cost)

    def build_exit(self, base_price: Decimal, quantity: Decimal, direction: Direction) -> CostBreakdown:
        base_price = parse_decimal(base_price, "base_price")
        quantity = parse_decimal(quantity, "quantity")
        fill_price = self._fill_price(base_price, direction, "exit")
        fee = abs(fill_price * quantity) * self.exit_fee_rate
        spread_cost = abs(base_price * quantity) * self._spread_side_rate()
        slippage_cost = abs(base_price * quantity) * self._slippage_side_rate()
        return CostBreakdown(base_price=base_price, fill_price=fill_price, fee=fee, spread_cost=spread_cost, slippage_cost=slippage_cost)
