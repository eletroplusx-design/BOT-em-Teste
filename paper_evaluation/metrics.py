from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .errors import PaperEvaluationMetricsError
from .models import PaperSessionEvidence, PaperSessionMetrics, PaperSessionSnapshotEvidence, PaperSessionTradeEvidence


def _as_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _trade_cost(trade: PaperSessionTradeEvidence) -> Decimal:
    components = [
        trade.entry_fee,
        trade.exit_fee,
        trade.entry_spread_cost,
        trade.entry_slippage_cost,
        trade.exit_spread_cost,
        trade.exit_slippage_cost,
    ]
    total = Decimal("0")
    for component in components:
        if component is not None:
            total += _as_decimal(component)
    if trade.custos_totais is not None:
        return _as_decimal(trade.custos_totais)
    if trade.spread_cost is not None:
        total += _as_decimal(trade.spread_cost)
    if trade.slippage_cost is not None:
        total += _as_decimal(trade.slippage_cost)
    return total


def _close_time(trade: PaperSessionTradeEvidence) -> datetime:
    return trade.fechado_em or trade.aberto_em


def _equity_drawdown(capital_initial: Decimal, trades: Iterable[PaperSessionTradeEvidence]) -> Decimal:
    equity = capital_initial
    peak = capital_initial
    max_dd = Decimal("0")
    for trade in sorted(trades, key=lambda item: (_close_time(item), item.trade_id)):
        equity += _as_decimal(trade.lucro_reais)
        if equity > peak:
            peak = equity
        if peak > 0:
            drawdown = (peak - equity) / peak * Decimal("100")
            if drawdown > max_dd:
                max_dd = drawdown
    return max_dd


def _exposure_metrics(session: PaperSessionEvidence) -> tuple[int, Decimal, int]:
    if not session.snapshots:
        return 0, Decimal("0"), 0
    ordered = sorted(
        enumerate(session.snapshots),
        key=lambda item: (item[1].timestamp_utc, getattr(item[1], "sequence", item[0] + 1)),
    )
    start = session.session_started_utc
    end = ordered[-1][1].timestamp_utc
    if end <= start:
        return 0, Decimal("0"), 0
    active_bars = 0
    max_open = 0
    for _, snapshot in ordered:
        open_count = 0
        for trade in session.trades:
            close_time = trade.fechado_em or snapshot.timestamp_utc
            if trade.aberto_em <= snapshot.timestamp_utc and close_time >= snapshot.timestamp_utc:
                open_count += 1
        if open_count > 0:
            active_bars += 1
        if open_count > max_open:
            max_open = open_count
    exposure_percent = (Decimal(active_bars) / Decimal(len(ordered)) * Decimal("100")) if ordered else Decimal("0")
    return active_bars, exposure_percent, max_open


def compute_paper_session_metrics(session: PaperSessionEvidence) -> PaperSessionMetrics:
    if session is None:
        raise PaperEvaluationMetricsError("session evidence is required.")
    trades = list(session.trades)
    closed_trades = [trade for trade in trades if trade.status == "closed"]
    relevant_trades = closed_trades or trades
    if not relevant_trades:
        capital_initial = _as_decimal(session.paper_limits.get("paper_capital_max", 0), Decimal("0"))
        capital_final = capital_initial
        return PaperSessionMetrics(
            session_id=session.session_id,
            capital_initial=capital_initial,
            capital_final=capital_final,
            gross_pnl=Decimal("0"),
            total_costs=Decimal("0"),
            net_pnl=Decimal("0"),
            net_return_percent=Decimal("0"),
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            breakeven_trades=0,
            win_rate=Decimal("0"),
            expectancy=Decimal("0"),
            profit_factor=None,
            payoff=None,
            drawdown_max_percent=Decimal("0"),
            exposure_percent=Decimal("0"),
            duration_hours=Decimal("0"),
            max_simultaneous_positions=0,
            max_loss_streak=max((snapshot.current_loss_streak for snapshot in session.snapshots), default=0),
            max_risk_per_trade_percent=Decimal("0"),
            capital_paper_max_used=Decimal("0"),
            spread_deviation_bps=Decimal("0"),
            slippage_deviation_bps=Decimal("0"),
            fee_deviation_percent=Decimal("0"),
            snapshot_count=len(session.snapshots),
            expired_data_cycles=session.expired_data_cycles,
            suspension_count=len(session.suspension_reasons),
            suspension_reasons=session.suspension_reasons,
            attempted_live_count=session.attempted_live_count,
            internal_error_count=session.internal_error_count,
            regime_coverage=session.regime_coverage,
            trade_ids=tuple(),
            fill_count=len(session.fills),
        )

    capital_initial = _as_decimal(session.paper_limits.get("paper_capital_max", 0), Decimal("0"))
    gross_profit = Decimal("0")
    gross_loss = Decimal("0")
    net_pnl = Decimal("0")
    total_costs = Decimal("0")
    winning = losing = breakeven = 0
    trade_ids: list[int] = []
    max_risk = Decimal("0")
    capital_paper_used = Decimal("0")
    observed_entry_spread = Decimal("0")
    observed_entry_slippage = Decimal("0")
    observed_entry_fee = Decimal("0")
    observed_exit_spread = Decimal("0")
    observed_exit_slippage = Decimal("0")
    observed_exit_fee = Decimal("0")

    for trade in sorted(relevant_trades, key=lambda item: (_close_time(item), item.trade_id)):
        trade_ids.append(trade.trade_id)
        lucro = _as_decimal(trade.lucro_reais)
        costs = _trade_cost(trade)
        total_costs += costs
        net_pnl += lucro
        if lucro > 0:
            winning += 1
            gross_profit += lucro
        elif lucro < 0:
            losing += 1
            gross_loss += abs(lucro)
        else:
            breakeven += 1
        if capital_initial > 0:
            risk_pct = (_as_decimal(trade.valor_arriscado) / capital_initial) * Decimal("100")
            if risk_pct > max_risk:
                max_risk = risk_pct
        capital_paper_used = max(capital_paper_used, _as_decimal(trade.valor_arriscado))
        observed_entry_spread += _as_decimal(trade.entry_spread_cost)
        observed_entry_slippage += _as_decimal(trade.entry_slippage_cost)
        observed_entry_fee += _as_decimal(trade.entry_fee)
        observed_exit_spread += _as_decimal(trade.exit_spread_cost)
        observed_exit_slippage += _as_decimal(trade.exit_slippage_cost)
        observed_exit_fee += _as_decimal(trade.exit_fee)

    total_trades = len(relevant_trades)
    capital_final = capital_initial + net_pnl
    net_return_percent = ((net_pnl / capital_initial) * Decimal("100")) if capital_initial > 0 else Decimal("0")
    win_rate = (Decimal(winning) / Decimal(total_trades) * Decimal("100")) if total_trades else Decimal("0")
    expectancy = (net_pnl / Decimal(total_trades)) if total_trades else Decimal("0")
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
    payoff = (gross_profit / Decimal(winning) / (gross_loss / Decimal(losing))) if winning > 0 and losing > 0 else None
    drawdown = _equity_drawdown(capital_initial, relevant_trades)
    active_bars, exposure_percent, max_open_positions = _exposure_metrics(session)
    max_loss_streak = max((snapshot.current_loss_streak for snapshot in session.snapshots), default=0)
    duration = session.session_updated_utc - session.session_started_utc
    duration_hours = Decimal(str(round(duration.total_seconds() / 3600.0, 6)))
    fill_count = len(session.fills)
    spread_deviation = Decimal("0")
    slippage_deviation = Decimal("0")
    fee_deviation = Decimal("0")
    if session.observed_costs:
        spread_deviation = abs(_as_decimal(session.observed_costs.get("spread_bps", 0)) - Decimal("5"))
        slippage_deviation = abs(_as_decimal(session.observed_costs.get("slippage_bps", 0)) - Decimal("5"))
        fee_deviation = abs(_as_decimal(session.observed_costs.get("entry_fee_rate", 0)) - Decimal("0.0004"))

    return PaperSessionMetrics(
        session_id=session.session_id,
        capital_initial=capital_initial,
        capital_final=capital_final,
        gross_pnl=gross_profit - gross_loss,
        total_costs=total_costs,
        net_pnl=net_pnl,
        net_return_percent=net_return_percent,
        total_trades=total_trades,
        winning_trades=winning,
        losing_trades=losing,
        breakeven_trades=breakeven,
        win_rate=win_rate,
        expectancy=expectancy,
        profit_factor=profit_factor,
        payoff=payoff,
        drawdown_max_percent=drawdown,
        exposure_percent=exposure_percent,
        duration_hours=duration_hours,
        max_simultaneous_positions=max_open_positions,
        max_loss_streak=max_loss_streak,
        max_risk_per_trade_percent=max_risk,
        capital_paper_max_used=capital_paper_used,
        spread_deviation_bps=spread_deviation,
        slippage_deviation_bps=slippage_deviation,
        fee_deviation_percent=fee_deviation,
        snapshot_count=len(session.snapshots),
        expired_data_cycles=session.expired_data_cycles,
        suspension_count=len(session.suspension_reasons),
        suspension_reasons=session.suspension_reasons,
        attempted_live_count=session.attempted_live_count,
        internal_error_count=session.internal_error_count,
        regime_coverage=session.regime_coverage,
        trade_ids=tuple(trade_ids),
        fill_count=fill_count,
    )


def aggregate_paper_session_metrics(metrics: Iterable[PaperSessionMetrics]) -> PaperSessionMetrics:
    items = list(metrics)
    if not items:
        raise PaperEvaluationMetricsError("at least one session metric is required.")
    session_id = ",".join(sorted(item.session_id for item in items))
    capital_initial = sum((item.capital_initial for item in items), Decimal("0"))
    capital_final = sum((item.capital_final for item in items), Decimal("0"))
    gross_pnl = sum((item.gross_pnl for item in items), Decimal("0"))
    total_costs = sum((item.total_costs for item in items), Decimal("0"))
    net_pnl = sum((item.net_pnl for item in items), Decimal("0"))
    total_trades = sum(item.total_trades for item in items)
    winning = sum(item.winning_trades for item in items)
    losing = sum(item.losing_trades for item in items)
    breakeven = sum(item.breakeven_trades for item in items)
    win_rate = (Decimal(winning) / Decimal(total_trades) * Decimal("100")) if total_trades else Decimal("0")
    expectancy = (net_pnl / Decimal(total_trades)) if total_trades else Decimal("0")
    gross_profit = sum((item.gross_pnl for item in items if item.gross_pnl > 0), Decimal("0"))
    gross_loss = sum((abs(item.gross_pnl) for item in items if item.gross_pnl < 0), Decimal("0"))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
    drawdown = max((item.drawdown_max_percent for item in items), default=Decimal("0"))
    exposure_percent = max((item.exposure_percent for item in items), default=Decimal("0"))
    duration_hours = sum((item.duration_hours for item in items), Decimal("0"))
    max_positions = max((item.max_simultaneous_positions for item in items), default=0)
    max_loss_streak = max((item.max_loss_streak for item in items), default=0)
    max_risk = max((item.max_risk_per_trade_percent for item in items), default=Decimal("0"))
    capital_paper_max_used = max((item.capital_paper_max_used for item in items), default=Decimal("0"))
    spread_deviation = max((item.spread_deviation_bps for item in items), default=Decimal("0"))
    slippage_deviation = max((item.slippage_deviation_bps for item in items), default=Decimal("0"))
    fee_deviation = max((item.fee_deviation_percent for item in items), default=Decimal("0"))
    snapshot_count = sum(item.snapshot_count for item in items)
    expired_data_cycles = sum(item.expired_data_cycles for item in items)
    suspension_count = sum(item.suspension_count for item in items)
    attempted_live_count = sum(item.attempted_live_count for item in items)
    internal_error_count = sum(item.internal_error_count for item in items)
    trade_ids = tuple(sorted({trade_id for item in items for trade_id in item.trade_ids}))
    regime_coverage = tuple(sorted({regime for item in items for regime in item.regime_coverage}))
    fill_count = sum(item.fill_count for item in items)
    suspension_reasons = tuple(sorted({reason for item in items for reason in item.suspension_reasons}))
    return PaperSessionMetrics(
        session_id=session_id,
        capital_initial=capital_initial,
        capital_final=capital_final,
        gross_pnl=gross_pnl,
        total_costs=total_costs,
        net_pnl=net_pnl,
        net_return_percent=(net_pnl / capital_initial * Decimal("100")) if capital_initial > 0 else Decimal("0"),
        total_trades=total_trades,
        winning_trades=winning,
        losing_trades=losing,
        breakeven_trades=breakeven,
        win_rate=win_rate,
        expectancy=expectancy,
        profit_factor=profit_factor,
        payoff=None,
        drawdown_max_percent=drawdown,
        exposure_percent=exposure_percent,
        duration_hours=duration_hours,
        max_simultaneous_positions=max_positions,
        max_loss_streak=max_loss_streak,
        max_risk_per_trade_percent=max_risk,
        capital_paper_max_used=capital_paper_max_used,
        spread_deviation_bps=spread_deviation,
        slippage_deviation_bps=slippage_deviation,
        fee_deviation_percent=fee_deviation,
        snapshot_count=snapshot_count,
        expired_data_cycles=expired_data_cycles,
        suspension_count=suspension_count,
        suspension_reasons=suspension_reasons,
        attempted_live_count=attempted_live_count,
        internal_error_count=internal_error_count,
        regime_coverage=regime_coverage,
        trade_ids=trade_ids,
        fill_count=fill_count,
    )
