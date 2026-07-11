from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from domain import Candle, Direction, Fill, PaperOrder, Position, PositionStatus, DataSource, OrderStatus
from domain.validation import parse_decimal

from .costs import CostModel
from .models import GapPolicy, IntrabarPolicy


@dataclass(frozen=True, slots=True)
class ExecutionDecision:
    price: Decimal
    reason: str
    timestamp: datetime
    gap_handled: bool = False


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware.")
    return value.astimezone(timezone.utc)


def resolve_entry_fill(order: PaperOrder, candle: Candle, costs: CostModel) -> Fill:
    entry_price = costs.apply_entry_slippage(candle.open, order.direction)
    notional = entry_price * order.quantity
    fee = costs.fee(notional)
    return Fill(
        price=entry_price,
        quantity=order.quantity,
        filled_at=_coerce_utc(candle.open_time),
        fee=fee,
        source=DataSource.PAPER,
        is_real=False,
        order_id=order.order_id,
    )


def _gap_exit_price(position: Position, candle: Candle) -> ExecutionDecision | None:
    if position.direction == Direction.COMPRA:
        if candle.open <= position.stop_loss:
            return ExecutionDecision(price=candle.open, reason="GAP_STOP", timestamp=_coerce_utc(candle.open_time), gap_handled=True)
        if candle.open >= position.take_profit:
            return ExecutionDecision(price=candle.open, reason="GAP_TAKE", timestamp=_coerce_utc(candle.open_time), gap_handled=True)
    else:
        if candle.open >= position.stop_loss:
            return ExecutionDecision(price=candle.open, reason="GAP_STOP", timestamp=_coerce_utc(candle.open_time), gap_handled=True)
        if candle.open <= position.take_profit:
            return ExecutionDecision(price=candle.open, reason="GAP_TAKE", timestamp=_coerce_utc(candle.open_time), gap_handled=True)
    return None


def resolve_exit(position: Position, candle: Candle, *, costs: CostModel, intrabar_policy: IntrabarPolicy = IntrabarPolicy.STOP_FIRST) -> ExecutionDecision | None:
    gap_decision = _gap_exit_price(position, candle)
    if gap_decision is not None:
        return gap_decision

    stop_hit = False
    take_hit = False
    stop_price = position.stop_loss
    take_price = position.take_profit

    if position.direction == Direction.COMPRA:
        stop_hit = candle.low <= stop_price
        take_hit = candle.high >= take_price
    else:
        stop_hit = candle.high >= stop_price
        take_hit = candle.low <= take_price

    if stop_hit and take_hit:
        if intrabar_policy == IntrabarPolicy.TAKE_FIRST:
            price = take_price
            reason = "TAKE_PROFIT"
        else:
            price = stop_price
            reason = "STOP_LOSS"
    elif stop_hit:
        price = stop_price
        reason = "STOP_LOSS"
    elif take_hit:
        price = take_price
        reason = "TAKE_PROFIT"
    else:
        return None

    price = costs.apply_exit_slippage(price, position.direction)
    return ExecutionDecision(price=price, reason=reason, timestamp=_coerce_utc(candle.close_time))


def build_exit_fill(position: Position, decision: ExecutionDecision, costs: CostModel) -> Fill:
    notional = decision.price * position.quantity
    fee = costs.fee(notional)
    return Fill(
        price=decision.price,
        quantity=position.quantity,
        filled_at=decision.timestamp,
        fee=fee,
        source=DataSource.PAPER,
        is_real=False,
        order_id=None,
    )
