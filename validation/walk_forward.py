from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pandas as pd

from .artifacts import build_manifest, freeze_selection, manifest_hash
from .errors import ValidationFreezeError, ValidationSelectionError
from .evaluation import evaluate_frozen_selection, evaluate_segment
from .models import CandidateConfig, CandidateEvaluation, FrozenSelection, SelectionCriteria, ValidationRunResult, ValidationSplitConfig, WalkForwardResult, WalkForwardWindowResult
from .selection import SelectionOutcome, select_configuration
from .splits import build_windows, slice_window_frames
from .statistics import aggregate_run_statistics, compute_candidate_stability


@dataclass
class WalkForwardValidator:
    split_config: ValidationSplitConfig = field(default_factory=ValidationSplitConfig)
    selection_criteria: SelectionCriteria = field(default_factory=SelectionCriteria)
    strategy_version: str = "v4_walk_forward"
    costs: dict[str, Any] = field(default_factory=dict)
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    seed: int | None = None
    _test_viewed: bool = field(default=False, init=False, repr=False)

    def _window_manifest(self, window, candidates, df: pd.DataFrame) -> dict[str, Any]:
        signature = {
            "rows": len(df),
            "first_open_time": str(df.iloc[0]["open_time"]) if "open_time" in df.columns and not df.empty else None,
            "last_open_time": str(df.iloc[-1]["open_time"]) if "open_time" in df.columns and not df.empty else None,
        }
        return build_manifest(
            symbol=self.symbol,
            interval=self.interval,
            strategy_version=self.strategy_version,
            costs=self.costs,
            split_config=self.split_config,
            candidate_grid=candidates,
            windows=[window],
            data_signature=signature,
            seed=self.seed,
        )

    def _select_window(self, candidate_evaluations: Sequence[CandidateEvaluation]) -> SelectionOutcome:
        return select_configuration(candidate_evaluations, self.selection_criteria)

    def select_window(self, candidate_evaluations: Sequence[CandidateEvaluation]) -> SelectionOutcome:
        if self._test_viewed:
            raise ValidationFreezeError("test metrics already viewed; reselection is blocked.")
        return self._select_window(candidate_evaluations)

    def freeze_window(self, candidate: CandidateConfig, *, window_id: str, frozen_at: datetime, manifest_hash_value: str) -> FrozenSelection:
        return freeze_selection(
            candidate,
            strategy_version=self.strategy_version,
            costs=self.costs,
            symbol=self.symbol,
            interval=self.interval,
            frozen_at=frozen_at,
            manifest_hash_value=manifest_hash_value,
            window_id=window_id,
        )

    def evaluate_window(
        self,
        df: pd.DataFrame,
        window,
        candidate_grid: Sequence[CandidateConfig],
        *,
        runner,
    ) -> WalkForwardWindowResult:
        slices = slice_window_frames(df, window)
        candidate_evaluations: list[CandidateEvaluation] = []
        for candidate in candidate_grid:
            train_metrics = evaluate_segment(slices["train"], candidate, segment="train", runner=runner, context={"window": window.as_dict(), "slices": slices})
            validation_metrics = evaluate_segment(slices["validation"], candidate, segment="validation", runner=runner, context={"window": window.as_dict(), "slices": slices})
            stability = compute_candidate_stability(train_metrics, validation_metrics)
            candidate_evaluations.append(
                CandidateEvaluation(
                    candidate=candidate,
                    train_metrics=train_metrics,
                    validation_metrics=validation_metrics,
                    stability_score=stability,
                )
            )

        outcome = self._select_window(candidate_evaluations)
        if not outcome.approved or outcome.candidate is None:
            manifest = self._window_manifest(window, candidate_grid, df)
            return WalkForwardWindowResult(
                bounds=window,
                candidate_evaluations=tuple(candidate_evaluations),
                selected_candidate=None,
                frozen_selection=None,
                test_metrics=None,
                manifest_hash=manifest["manifest_hash"],
                approved=False,
                reason=outcome.reason,
            )

        manifest = self._window_manifest(window, candidate_grid, df)
        frozen = self.freeze_window(
            outcome.candidate,
            window_id=f"{window.train_start}:{window.validation_start}:{window.test_start}",
            frozen_at=pd.to_datetime(df.iloc[window.test_start]["open_time"], utc=True).to_pydatetime(),
            manifest_hash_value=manifest["manifest_hash"],
        )
        self._test_viewed = True
        test_metrics = evaluate_frozen_selection(
            slices["test"],
            outcome.candidate,
            frozen,
            segment="test",
            runner=runner,
            context={"window": window.as_dict(), "slices": slices},
        )
        return WalkForwardWindowResult(
            bounds=window,
            candidate_evaluations=tuple(candidate_evaluations),
            selected_candidate=outcome.candidate,
            frozen_selection=frozen,
            test_metrics=test_metrics,
            manifest_hash=manifest["manifest_hash"],
            approved=True,
            reason=outcome.reason,
        )

    def run(self, df: pd.DataFrame, candidate_grid: Sequence[CandidateConfig], *, runner) -> WalkForwardResult:
        self._test_viewed = False
        windows = build_windows(df, self.split_config)
        results = [self.evaluate_window(df, window, candidate_grid, runner=runner) for window in windows]
        manifest = build_manifest(
            symbol=self.symbol,
            interval=self.interval,
            strategy_version=self.strategy_version,
            costs=self.costs,
            split_config=self.split_config,
            candidate_grid=candidate_grid,
            windows=windows,
            data_signature={
                "rows": len(df),
                "first_open_time": str(df.iloc[0]["open_time"]) if "open_time" in df.columns and not df.empty else None,
                "last_open_time": str(df.iloc[-1]["open_time"]) if "open_time" in df.columns and not df.empty else None,
            },
            seed=self.seed,
        )
        summary = aggregate_run_statistics(results)
        summary["manifest_hash"] = manifest["manifest_hash"]
        summary["strategy_version"] = self.strategy_version
        summary["symbol"] = self.symbol
        summary["interval"] = self.interval
        summary["mode"] = self.split_config.mode
        return WalkForwardResult(windows=tuple(results), summary=summary, manifest=manifest)


def run_walk_forward_validation(df: pd.DataFrame, candidate_grid: Sequence[CandidateConfig], *, runner, split_config: ValidationSplitConfig | None = None, selection_criteria: SelectionCriteria | None = None, strategy_version: str = "v4_walk_forward", symbol: str = "BTCUSDT", interval: str = "1h", costs: dict[str, Any] | None = None, seed: int | None = None) -> WalkForwardResult:
    validator = WalkForwardValidator(
        split_config=split_config or ValidationSplitConfig(),
        selection_criteria=selection_criteria or SelectionCriteria(),
        strategy_version=strategy_version,
        costs=costs or {},
        symbol=symbol,
        interval=interval,
        seed=seed,
    )
    return validator.run(df, candidate_grid, runner=runner)
