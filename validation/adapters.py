from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pandas as pd

from backtesting import dataframe_to_candles
from backtesting.models import BacktestConfig, GapPolicy, IntrabarPolicy

from .errors import ValidationEvaluationError
from .models import CandidateConfig, SegmentView


def adapt_legacy_report(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "legacy": True,
        "source": report.get("source", "legacy"),
        "summary": report.get("summary", {}),
        "manifest": report.get("manifest", {}),
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "total_trades": 0,
        "net_return_percent": 0.0,
        "drawdown_max_percent": 0.0,
        "expectancy": 0.0,
        "profit_factor": None,
        "payoff": None,
        "win_rate": 0.0,
        "trade_win_rate": 0.0,
        "capital_initial": 0.0,
        "capital_final": 0.0,
        "net_pnl": 0.0,
        "gross_pnl": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "total_costs": 0.0,
        "total_fees": 0.0,
        "spread_cost": 0.0,
        "slippage_cost": 0.0,
        "winning_trades": 0,
        "losing_trades": 0,
        "sequencia_maxima_perdas": 0,
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
            return {"summary": _empty_summary()}
        return self.legacy_runner(df, strategy_callback, segment=segment, context=context or {}, frozen_selection=frozen_selection)


@dataclass(frozen=True, slots=True)
class TrustedLeakFreeBacktestRunner:
    engine_factory: Callable[[], Any]
    strategy_factory: Callable[[CandidateConfig], Callable[[Any, Any], object | None]]
    symbol: str
    interval: str

    @staticmethod
    def _normalize_value(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (IntrabarPolicy, GapPolicy)):
            return value.value
        return value

    def execution_contract(self) -> dict[str, Any]:
        engine = self.engine_factory()
        config = getattr(engine, "config", None)
        if not isinstance(config, BacktestConfig):
            raise ValidationEvaluationError("engine config must be BacktestConfig.")
        return {
            "entry_fee_rate": self._normalize_value(config.entry_fee_rate),
            "exit_fee_rate": self._normalize_value(config.exit_fee_rate),
            "spread_bps": self._normalize_value(config.spread_bps),
            "slippage_bps": self._normalize_value(config.slippage_bps),
            "leverage": self._normalize_value(config.leverage),
            "intrabar_policy": self._normalize_value(config.intrabar_policy),
            "gap_policy": self._normalize_value(config.gap_policy),
            "paper_only": config.paper_only,
            "symbol": config.symbol,
            "interval": config.interval,
            "strategy_version": config.strategy_version,
        }

    def normalized_warmup_summary(self, summary: Mapping[str, Any], *, segment_view: SegmentView) -> dict[str, Any]:
        normalized = dict(summary)
        normalized["total_bars"] = segment_view.segment_rows
        normalized["exposure_bars"] = int(normalized.get("exposure_bars", 0) or 0)
        total_bars = segment_view.segment_rows
        exposure_bars = normalized["exposure_bars"]
        normalized["exposure_time_percent"] = float(round((Decimal(exposure_bars) / Decimal(total_bars) * Decimal("100")) if total_bars > 0 else Decimal("0"), 2))
        return normalized

    def __call__(
        self,
        df: pd.DataFrame,
        candidate: CandidateConfig,
        *,
        segment: str,
        context: Mapping[str, Any] | None = None,
        frozen_selection=None,
    ) -> Mapping[str, Any]:
        context = context or {}
        segment_view = context.get("segment_view")
        if not isinstance(segment_view, SegmentView):
            raise ValidationEvaluationError("segment_view is required for trusted runner execution.")
        strategy_callback = self.strategy_factory(candidate)
        if strategy_callback is None:
            return {"summary": _empty_summary()}

        def guarded_strategy(history, snapshot):
            idx = len(history) - 1
            if idx < segment_view.trade_start_index:
                return None
            return strategy_callback(history, snapshot)

        candles = dataframe_to_candles(df, symbol=self.symbol, interval=self.interval)
        engine = self.engine_factory()
        actual_contract = self.execution_contract()
        if actual_contract["symbol"] != self.symbol or actual_contract["interval"] != self.interval:
            raise ValidationEvaluationError("engine symbol or interval diverges from trusted runner contract.")
        if actual_contract["paper_only"] is not True:
            raise ValidationEvaluationError("engine must remain paper_only.")
        result = engine.run(candles, guarded_strategy)
        if any(trade.entry_index < segment_view.trade_start_index for trade in result.trades):
            raise ValidationEvaluationError("warm-up trade leakage detected.")
        return {"summary": self.normalized_warmup_summary(result.summary, segment_view=segment_view), "execution_contract": actual_contract}
