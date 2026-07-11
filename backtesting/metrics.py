from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from .models import EquityPoint, ExecutedTrade


def _as_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def max_drawdown(equity_curve: Sequence[EquityPoint]) -> Decimal:
    if not equity_curve:
        return Decimal("0")
    peak = _as_decimal(equity_curve[0].equity)
    max_dd = Decimal("0")
    for point in equity_curve:
        equity = _as_decimal(point.equity)
        if equity > peak:
            peak = equity
        if peak > 0:
            drawdown = (peak - equity) / peak * Decimal("100")
            if drawdown > max_dd:
                max_dd = drawdown
    return max_dd


def compute_metrics(
    trades: Sequence[ExecutedTrade],
    equity_curve: Sequence[EquityPoint],
    initial_capital: Decimal,
    *,
    total_bars: int = 0,
    exposure_bars: int = 0,
) -> dict[str, object]:
    initial_capital = _as_decimal(initial_capital)
    if not trades:
        return {
            "capital_initial": float(initial_capital),
            "capital_final": float(initial_capital),
            "return_net_percent": 0.0,
            "gross_pnl": 0.0,
            "net_pnl": 0.0,
            "total_fees": 0.0,
            "entry_fees": 0.0,
            "exit_fees": 0.0,
            "spread_cost": 0.0,
            "slippage_cost": 0.0,
            "total_trades": 0,
            "win_rate": 0.0,
            "average_gain": None,
            "average_loss": None,
            "payoff": None,
            "profit_factor": None,
            "profit_factor_state": "undefined_no_trades",
            "expectancy": 0.0,
            "drawdown_max_percent": float(max_drawdown(equity_curve)),
            "sequencia_maxima_perdas": 0,
            "exposure_time_percent": 0.0,
            "total_bars": total_bars,
            "exposure_bars": exposure_bars,
        }

    gross_pnl = sum((trade.gross_pnl for trade in trades), Decimal("0"))
    net_pnl = sum((trade.net_pnl for trade in trades), Decimal("0"))
    total_entry_fees = sum((trade.entry_fee for trade in trades), Decimal("0"))
    total_exit_fees = sum((trade.exit_fee for trade in trades), Decimal("0"))
    total_spread_cost = sum((trade.spread_cost for trade in trades), Decimal("0"))
    total_slippage_cost = sum((trade.slippage_cost for trade in trades), Decimal("0"))
    total_fees = total_entry_fees + total_exit_fees
    total_costs = total_fees + total_spread_cost + total_slippage_cost

    pnl_values = [trade.net_pnl for trade in trades]
    wins = [pnl for pnl in pnl_values if pnl > 0]
    losses = [pnl for pnl in pnl_values if pnl < 0]
    wins_count = len(wins)
    losses_count = len(losses)
    total_trades = len(trades)
    win_rate = (Decimal(wins_count) / Decimal(total_trades) * Decimal("100")) if total_trades else Decimal("0")
    average_gain = (sum(wins, Decimal("0")) / Decimal(wins_count)) if wins_count else None
    average_loss = (abs(sum(losses, Decimal("0")) / Decimal(losses_count))) if losses_count else None
    gross_profit = sum(wins, Decimal("0"))
    gross_loss = abs(sum(losses, Decimal("0")))
    profit_factor = None
    profit_factor_state = "undefined_no_losses"
    if wins_count and losses_count:
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
        profit_factor_state = "defined"
    elif wins_count == 0 and losses_count > 0:
        profit_factor = Decimal("0")
        profit_factor_state = "defined_zero_wins"

    payoff = None
    if average_gain is not None and average_loss not in (None, Decimal("0")):
        payoff = average_gain / average_loss

    expectancy = Decimal("0")
    if average_gain is not None and average_loss is not None:
        win_ratio = win_rate / Decimal("100")
        expectancy = win_ratio * average_gain - (Decimal("1") - win_ratio) * average_loss

    sequencia = 0
    max_seq = 0
    for pnl in pnl_values:
        if pnl < 0:
            sequencia += 1
            max_seq = max(max_seq, sequencia)
        else:
            sequencia = 0

    exposure_time_percent = (Decimal(exposure_bars) / Decimal(total_bars) * Decimal("100")) if total_bars > 0 else Decimal("0")
    final_capital = initial_capital + net_pnl

    return {
        "capital_initial": float(round(initial_capital, 2)),
        "capital_final": float(round(final_capital, 2)),
        "return_net_percent": float(round((net_pnl / initial_capital) * Decimal("100"), 2)) if initial_capital else 0.0,
        "gross_pnl": float(round(gross_pnl, 2)),
        "net_pnl": float(round(net_pnl, 2)),
        "gross_profit": float(round(gross_profit, 2)),
        "gross_loss": float(round(gross_loss, 2)),
        "total_fees": float(round(total_fees, 2)),
        "entry_fees": float(round(total_entry_fees, 2)),
        "exit_fees": float(round(total_exit_fees, 2)),
        "spread_cost": float(round(total_spread_cost, 2)),
        "slippage_cost": float(round(total_slippage_cost, 2)),
        "total_costs": float(round(total_costs, 2)),
        "total_trades": total_trades,
        "winning_trades": wins_count,
        "losing_trades": losses_count,
        "win_rate": float(round(win_rate, 2)),
        "average_gain": float(round(average_gain, 4)) if average_gain is not None else None,
        "average_loss": float(round(average_loss, 4)) if average_loss is not None else None,
        "payoff": float(round(payoff, 4)) if payoff is not None else None,
        "profit_factor": float(round(profit_factor, 4)) if isinstance(profit_factor, Decimal) else profit_factor,
        "profit_factor_state": profit_factor_state,
        "expectancy": float(round(expectancy, 4)),
        "drawdown_max_percent": float(round(max_drawdown(equity_curve), 2)),
        "sequencia_maxima_perdas": max_seq,
        "exposure_time_percent": float(round(exposure_time_percent, 2)),
        "total_bars": total_bars,
        "exposure_bars": exposure_bars,
    }
