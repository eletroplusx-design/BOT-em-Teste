from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from domain import Candle, DataSource, Direction, Fill, PaperOrder, Position

from .costs import CostBreakdown, CostModel


@dataclass(frozen=True, slots=True)
class ExecutionDecision:
    base_price: Decimal
    fill_price: Decimal
    reason: str
    timestamp: datetime
    fee: Decimal
    spread_cost: Decimal
    slippage_cost: Decimal
    gap_handled: bool = False


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware.")
    return value.astimezone(timezone.utc)


def resolve_entry_execution(order: PaperOrder, candle: Candle, costs: CostModel) -> ExecutionDecision:
    breakdown = costs.build_entry(candle.open, order.quantity, order.direction)
    return ExecutionDecision(
        base_price=breakdown.base_price,
        fill_price=breakdown.fill_price,
        reason="ENTRY",
        timestamp=_coerce_utc(candle.open_time),
        fee=breakdown.fee,
        spread_cost=breakdown.spread_cost,
        slippage_cost=breakdown.slippage_cost,
    )


def _gap_base_price(position: Position, candle: Candle) -> tuple[Decimal, str]:
    if position.direction == Direction.COMPRA:
        if candle.open <= position.stop_loss:
            return candle.open, "GAP_STOP"
        if candle.open >= position.take_profit:
            return candle.open, "GAP_TAKE"
    else:
        if candle.open >= position.stop_loss:
            return candle.open, "GAP_STOP"
        if candle.open <= position.take_profit:
            return candle.open, "GAP_TAKE"
    return candle.close, "FINAL_CLOSE"


def resolve_exit_execution(position: Position, candle: Candle, *, costs: CostModel, intrabar_policy) -> ExecutionDecision | None:
    if position.direction == Direction.COMPRA:
        if candle.open <= position.stop_loss:
            return resolve_gap_exit_execution(position, candle, costs=costs)
        if candle.open >= position.take_profit:
            return resolve_gap_exit_execution(position, candle, costs=costs)
    else:
        if candle.open >= position.stop_loss:
            return resolve_gap_exit_execution(position, candle, costs=costs)
        if candle.open <= position.take_profit:
            return resolve_gap_exit_execution(position, candle, costs=costs)

    stop_hit = False
    take_hit = False
    if position.direction == Direction.COMPRA:
        stop_hit = candle.low <= position.stop_loss
        take_hit = candle.high >= position.take_profit
    else:
        stop_hit = candle.high >= position.stop_loss
        take_hit = candle.low <= position.take_profit

    if not (stop_hit or take_hit):
        return None

    if stop_hit and take_hit:
        if intrabar_policy.value == "TAKE_FIRST":
            reason = "TAKE_PROFIT"
            base_price = position.take_profit
        else:
            reason = "STOP_LOSS"
            base_price = position.stop_loss
    elif stop_hit:
        reason = "STOP_LOSS"
        base_price = position.stop_loss
    else:
        reason = "TAKE_PROFIT"
        base_price = position.take_profit

    breakdown = costs.build_exit(base_price, position.quantity, position.direction)
    return ExecutionDecision(
        base_price=breakdown.base_price,
        fill_price=breakdown.fill_price,
        reason=reason,
        timestamp=_coerce_utc(candle.close_time),
        fee=breakdown.fee,
        spread_cost=breakdown.spread_cost,
        slippage_cost=breakdown.slippage_cost,
    )


def resolve_gap_exit_execution(position: Position, candle: Candle, *, costs: CostModel) -> ExecutionDecision:
    base_price, reason = _gap_base_price(position, candle)
    breakdown = costs.build_exit(base_price, position.quantity, position.direction)
    return ExecutionDecision(
        base_price=breakdown.base_price,
        fill_price=breakdown.fill_price,
        reason=reason,
        timestamp=_coerce_utc(candle.open_time),
        fee=breakdown.fee,
        spread_cost=breakdown.spread_cost,
        slippage_cost=breakdown.slippage_cost,
        gap_handled=True,
    )


def build_entry_fill(order: PaperOrder, execution: ExecutionDecision) -> Fill:
    return Fill(
        price=execution.fill_price,
        quantity=order.quantity,
        filled_at=execution.timestamp,
        fee=execution.fee,
        source=DataSource.PAPER,
        is_real=False,
        order_id=order.order_id,
    )


def build_exit_fill(position: Position, execution: ExecutionDecision) -> Fill:
    return Fill(
        price=execution.fill_price,
        quantity=position.quantity,
        filled_at=execution.timestamp,
        fee=execution.fee,
        source=DataSource.PAPER,
        is_real=False,
        order_id=None,
    )
