from __future__ import annotations

from decimal import Decimal

from .models import PaperEvaluationPolicy


def default_paper_evaluation_policy() -> PaperEvaluationPolicy:
    return PaperEvaluationPolicy(
        min_sessions_completed=1,
        min_distinct_days=1,
        min_trades=1,
        min_duration_hours=Decimal("1"),
        max_drawdown_percent=Decimal("25"),
        min_profit_factor=Decimal("1"),
        min_expectancy=Decimal("0"),
        min_net_return_percent=Decimal("0"),
        max_total_costs_percent=Decimal("10"),
        max_suspended_sessions=0,
        require_zero_live_attempts=True,
        require_audit_chain=True,
        require_fresh_data=True,
        required_regimes=("BULL", "BEAR", "CHOP"),
        min_regime_coverage=3,
        evaluator_version="v8_paper_evaluation",
    )
