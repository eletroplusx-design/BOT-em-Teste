from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from math import isfinite
from statistics import pstdev
from typing import Any

from .models import CandidateEvaluation, SegmentMetrics, WalkForwardWindowResult


def sanitize_metric_value(value: Any, default: Decimal | float | int | None = 0) -> Any:
    if value is None:
        return default
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return default
        return value
    if isinstance(value, float):
        if not isfinite(value):
            return default
        return value
    return value


def aggregate_segment_metrics(metrics: Iterable[SegmentMetrics]) -> dict[str, Any]:
    itens = list(metrics)
    if not itens:
        return {
            "total_trades": 0,
            "net_pnl": 0.0,
            "net_return_percent": 0.0,
            "drawdown_max_percent": 0.0,
            "expectancy": 0.0,
            "profit_factor": None,
            "payoff": None,
            "win_rate": 0.0,
            "dispersion": 0.0,
            "worst_window": None,
            "proportion_lucrative": 0.0,
            "degradation_validation_test": 0.0,
        }

    total_trades = sum(item.total_trades for item in itens)
    net_pnl = sum((item.net_pnl for item in itens), Decimal("0"))
    gross_pnl = sum((item.gross_pnl for item in itens), Decimal("0"))
    total_costs = sum((item.total_costs for item in itens), Decimal("0"))
    total_fees = sum((item.total_fees for item in itens), Decimal("0"))
    spread_cost = sum((item.spread_cost for item in itens), Decimal("0"))
    slippage_cost = sum((item.slippage_cost for item in itens), Decimal("0"))
    capital_initial = itens[0].capital_initial
    capital_final = capital_initial + net_pnl
    gross_profit = sum((item.net_pnl for item in itens if item.net_pnl > 0), Decimal("0"))
    gross_loss = abs(sum((item.net_pnl for item in itens if item.net_pnl < 0), Decimal("0")))
    profit_factor = None
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = None
    payoff = None
    winning = [item for item in itens if item.net_pnl > 0]
    losing = [item for item in itens if item.net_pnl < 0]
    average_gain = (sum((item.net_pnl for item in winning), Decimal("0")) / Decimal(len(winning))) if winning else None
    average_loss = (
        abs(sum((item.net_pnl for item in losing), Decimal("0")) / Decimal(len(losing)))
        if losing
        else None
    )
    win_rate = (Decimal(len(winning)) / Decimal(len(itens)) * Decimal("100")) if itens else Decimal("0")
    if average_gain is not None and average_loss not in (None, Decimal("0")):
        payoff = average_gain / average_loss
    expectancy = Decimal("0")
    if average_gain is not None and average_loss is not None:
        win_ratio = win_rate / Decimal("100")
        expectancy = win_ratio * average_gain - (Decimal("1") - win_ratio) * average_loss
    return {
        "total_trades": total_trades,
        "net_pnl": float(round(net_pnl, 6)),
        "gross_pnl": float(round(gross_pnl, 6)),
        "total_costs": float(round(total_costs, 6)),
        "total_fees": float(round(total_fees, 6)),
        "spread_cost": float(round(spread_cost, 6)),
        "slippage_cost": float(round(slippage_cost, 6)),
        "capital_initial": float(round(capital_initial, 2)),
        "capital_final": float(round(capital_final, 2)),
        "net_return_percent": float(round((net_pnl / capital_initial) * Decimal("100"), 4)) if capital_initial else 0.0,
        "drawdown_max_percent": float(round(max((item.drawdown_max_percent for item in itens), default=Decimal("0")), 4)),
        "expectancy": float(round(expectancy, 6)),
        "profit_factor": float(round(profit_factor, 6)) if profit_factor is not None else None,
        "payoff": float(round(payoff, 6)) if payoff is not None else None,
        "win_rate": float(round(win_rate, 4)),
        "dispersion": float(round(Decimal(str(pstdev([float(item.net_return_percent) for item in itens]))) if len(itens) > 1 else Decimal("0"), 6)),
    }


def compute_candidate_stability(train_metrics: SegmentMetrics, validation_metrics: SegmentMetrics) -> Decimal:
    delta_return = abs(validation_metrics.net_return_percent - train_metrics.net_return_percent)
    delta_drawdown = abs(validation_metrics.drawdown_max_percent - train_metrics.drawdown_max_percent)
    delta_expectancy = abs(validation_metrics.expectancy - train_metrics.expectancy)
    return delta_return + delta_drawdown + delta_expectancy


def compute_dispersion(window_results: Iterable[WalkForwardWindowResult]) -> dict[str, Any]:
    windows = list(window_results)
    if not windows:
        return {"dispersion": 0.0, "worst_window": None, "proportion_lucrative": 0.0}

    test_metrics = [window.test_metrics for window in windows if window.test_metrics is not None]
    if not test_metrics:
        return {"dispersion": 0.0, "worst_window": None, "proportion_lucrative": 0.0}
    net_returns = [float(item.net_return_percent) for item in test_metrics]
    worst = min(windows, key=lambda window: float(window.test_metrics.net_return_percent) if window.test_metrics else float("inf"))
    profitable = sum(1 for item in test_metrics if item.net_return_percent > 0)
    dispersion = pstdev(net_returns) if len(net_returns) > 1 else 0.0
    return {
        "dispersion": float(round(Decimal(str(dispersion)), 6)),
        "worst_window": worst.bounds.as_dict(),
        "proportion_lucrative": float(round(Decimal(profitable) / Decimal(len(test_metrics)) * Decimal("100"), 4)),
    }


def aggregate_run_statistics(window_results: Iterable[WalkForwardWindowResult]) -> dict[str, Any]:
    windows = list(window_results)
    test_metrics = [window.test_metrics for window in windows if window.test_metrics is not None]
    validation_metrics = []
    for window in windows:
        for evaluation in window.candidate_evaluations:
            validation_metrics.append(evaluation.validation_metrics)

    aggregate_tests = aggregate_segment_metrics(test_metrics)
    aggregate_validation = aggregate_segment_metrics(validation_metrics)
    dispersion = compute_dispersion(windows)

    degradation = 0.0
    if validation_metrics and test_metrics:
        degradation = float(round((Decimal(str(aggregate_validation["net_return_percent"])) - Decimal(str(aggregate_tests["net_return_percent"]))), 6))

    summary = {
        "total_windows": len(windows),
        "selected_windows": sum(1 for window in windows if window.approved),
        "total_trades": aggregate_tests["total_trades"],
        "net_return_percent": aggregate_tests["net_return_percent"],
        "net_pnl": aggregate_tests["net_pnl"],
        "drawdown_max_percent": aggregate_tests["drawdown_max_percent"],
        "expectancy": aggregate_tests["expectancy"],
        "profit_factor": aggregate_tests["profit_factor"],
        "payoff": aggregate_tests["payoff"],
        "win_rate": aggregate_tests["win_rate"],
        "dispersion": dispersion["dispersion"],
        "worst_window": dispersion["worst_window"],
        "proportion_lucrative_windows": dispersion["proportion_lucrative"],
        "degradation_validation_test": degradation,
    }
    return {key: sanitize_metric_value(value, default=0.0) for key, value in summary.items()}
