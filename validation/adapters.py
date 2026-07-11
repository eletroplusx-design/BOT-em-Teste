from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd

from .models import CandidateConfig


def adapt_legacy_report(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "legacy": True,
        "source": report.get("source", "legacy"),
        "summary": report.get("summary", {}),
        "manifest": report.get("manifest", {}),
    }


class LegacyBacktesterAdapter:
    def __init__(self, legacy_runner: Callable[..., Mapping[str, Any]], *, strategy_callback_factory: Callable[[CandidateConfig], Callable] | None = None):
        self.legacy_runner = legacy_runner
        self.strategy_callback_factory = strategy_callback_factory or (lambda candidate: candidate.as_dict().get("strategy_callback"))

    def __call__(
        self,
        df: pd.DataFrame,
        candidate: CandidateConfig,
        *,
        segment: str,
        context: Mapping[str, Any] | None = None,
        frozen_selection=None,
    ) -> Mapping[str, Any]:
        strategy_callback = self.strategy_callback_factory(candidate)
        if strategy_callback is None:
            return {"summary": {"total_trades": 0, "net_return_percent": 0.0, "drawdown_max_percent": 0.0, "expectancy": 0.0, "profit_factor": None, "payoff": None, "win_rate": 0.0, "capital_initial": 0.0, "capital_final": 0.0, "net_pnl": 0.0, "gross_pnl": 0.0, "total_costs": 0.0, "total_fees": 0.0, "spread_cost": 0.0, "slippage_cost": 0.0, "sequencia_maxima_perdas": 0}}
        return self.legacy_runner(df, strategy_callback, segment=segment, context=context or {}, frozen_selection=frozen_selection)
