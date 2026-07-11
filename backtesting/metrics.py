from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Sequence

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


def compute_metrics(trades: Sequence[ExecutedTrade], equity_curve: Sequence[EquityPoint], initial_capital: Decimal) -> dict[str, object]:
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "lucro_total_valor": 0.0,
            "lucro_total_percent": 0.0,
            "drawdown_max_percent": float(max_drawdown(equity_curve)),
            "media_rr": 0.0,
            "expectativa_matematica": 0.0,
            "sequencia_maxima_perdas": 0,
        }

    pnl_values = [trade.pnl_reais for trade in trades]
    gross_profit = sum((pnl for pnl in pnl_values if pnl > 0), Decimal("0"))
    gross_loss = abs(sum((pnl for pnl in pnl_values if pnl < 0), Decimal("0")))
    total_pnl = sum(pnl_values, Decimal("0"))
    wins = sum(1 for pnl in pnl_values if pnl > 0)
    losses = sum(1 for pnl in pnl_values if pnl < 0)
    win_rate = (Decimal(wins) / Decimal(len(trades))) * Decimal("100")
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (Decimal("Infinity") if gross_profit > 0 else Decimal("0"))
    average_rr = sum((trade.realized_rr for trade in trades), Decimal("0")) / Decimal(len(trades))
    avg_gain = sum((pnl for pnl in pnl_values if pnl > 0), Decimal("0")) / Decimal(wins) if wins else Decimal("0")
    avg_loss = abs(sum((pnl for pnl in pnl_values if pnl < 0), Decimal("0")) / Decimal(losses)) if losses else Decimal("0")
    expectancy = (win_rate / Decimal("100")) * avg_gain - (Decimal("1") - (win_rate / Decimal("100"))) * avg_loss
    sequencia = 0
    max_seq = 0
    for pnl in pnl_values:
        if pnl < 0:
            sequencia += 1
            max_seq = max(max_seq, sequencia)
        else:
            sequencia = 0

    return {
        "total_trades": len(trades),
        "win_rate": float(round(win_rate, 2)),
        "profit_factor": "inf" if profit_factor == Decimal("Infinity") else float(round(profit_factor, 4)),
        "lucro_total_valor": float(round(total_pnl, 2)),
        "lucro_total_percent": float(round((total_pnl / initial_capital) * Decimal("100"), 2)) if initial_capital else 0.0,
        "drawdown_max_percent": float(round(max_drawdown(equity_curve), 2)),
        "media_rr": float(round(average_rr, 4)),
        "expectativa_matematica": float(round(expectancy, 4)),
        "sequencia_maxima_perdas": max_seq,
    }
