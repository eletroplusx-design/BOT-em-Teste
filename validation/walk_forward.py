from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import pandas as pd

from .artifacts import build_data_signature, build_manifest, freeze_selection
from .adapters import TrustedLeakFreeBacktestRunner
from .errors import ValidationFreezeError
from .evaluation import evaluate_frozen_selection, evaluate_segment
from .models import CandidateConfig, CandidateEvaluation, FrozenSelection, SegmentView, SelectionCriteria, ValidationSplitConfig, WalkForwardResult, WalkForwardWindowResult
from .selection import SelectionOutcome, select_configuration
from .splits import build_window_segment_views, build_windows
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
    require_trusted_runner: bool = True
    _session_consumed: bool = field(default=False, init=False, repr=False)

    def _window_manifest(
        self,
        window,
        candidates,
        data_signature: dict[str, Any],
        *,
        execution_contract: dict[str, Any],
        window_signatures: dict[str, Any],
        runner_trusted: bool,
    ) -> dict[str, Any]:
        return build_manifest(
            symbol=self.symbol,
            interval=self.interval,
            strategy_version=self.strategy_version,
            costs=self.costs,
            selection_criteria=self.selection_criteria.as_dict(),
            execution_contract=execution_contract,
            window_signatures=window_signatures,
            runner_trusted=runner_trusted,
            split_config=self.split_config,
            candidate_grid=candidates,
            windows=[window],
            data_signature=data_signature,
            seed=self.seed,
        )

    def _select_window(self, candidate_evaluations: Sequence[CandidateEvaluation]) -> SelectionOutcome:
        return select_configuration(candidate_evaluations, self.selection_criteria)

    def select_window(self, candidate_evaluations: Sequence[CandidateEvaluation]) -> SelectionOutcome:
        if self._session_consumed:
            raise ValidationFreezeError("validator session already consumed; reselection is blocked.")
        return self._select_window(candidate_evaluations)

    def freeze_window(self, candidate: CandidateConfig, *, window_id: str, frozen_at: datetime, manifest_hash_value: str, execution_contract: dict[str, Any]) -> FrozenSelection:
        return freeze_selection(
            candidate,
            strategy_version=self.strategy_version,
            costs=self.costs,
            execution_contract=execution_contract,
            symbol=self.symbol,
            interval=self.interval,
            frozen_at=frozen_at,
            manifest_hash_value=manifest_hash_value,
            window_id=window_id,
        )

    @staticmethod
    def _normalize_contract_value(value: Any) -> Any:
        if hasattr(value, "value"):
            return value.value
        return str(value) if isinstance(value, (int, float, Decimal)) else value

    def _expected_execution_contract(self) -> dict[str, Any]:
        costs = dict(self.costs or {})
        entry_fee_rate = costs.get("entry_fee_rate", costs.get("commission_rate", Decimal("0")))
        exit_fee_rate = costs.get("exit_fee_rate", costs.get("commission_rate", entry_fee_rate))
        return {
            "engine_class": "LeakFreeBacktestEngine",
            "entry_fee_rate": self._normalize_contract_value(entry_fee_rate),
            "exit_fee_rate": self._normalize_contract_value(exit_fee_rate),
            "spread_bps": self._normalize_contract_value(costs.get("spread_bps", Decimal("0"))),
            "slippage_bps": self._normalize_contract_value(costs.get("slippage_bps", Decimal("0"))),
            "leverage": self._normalize_contract_value(costs.get("leverage", Decimal("1"))),
            "intrabar_policy": self._normalize_contract_value(costs.get("intrabar_policy", "STOP_FIRST")),
            "gap_policy": self._normalize_contract_value(costs.get("gap_policy", "OPEN_PRICE")),
            "paper_only": True,
            "symbol": self.symbol,
            "interval": self.interval,
            "strategy_version": self.strategy_version,
        }

    def _runner_execution_contract(self, runner) -> dict[str, Any] | None:
        if not isinstance(runner, TrustedLeakFreeBacktestRunner):
            return None
        contract_fn = getattr(runner, "execution_contract", None)
        if contract_fn is None:
            return None
        contract = contract_fn() if callable(contract_fn) else contract_fn
        if not isinstance(contract, dict):
            raise ValidationFreezeError("runner execution contract must be a mapping.")
        return contract

    def _validate_execution_contract(self, runner_contract: dict[str, Any] | None) -> dict[str, Any]:
        if runner_contract is None:
            return {}
        expected = self._expected_execution_contract()
        comparable_keys = (
            "engine_class",
            "entry_fee_rate",
            "exit_fee_rate",
            "spread_bps",
            "slippage_bps",
            "leverage",
            "intrabar_policy",
            "gap_policy",
            "paper_only",
            "symbol",
            "interval",
            "strategy_version",
        )
        for key in comparable_keys:
            if runner_contract.get(key) != expected.get(key):
                raise ValidationFreezeError(f"runner execution contract mismatch for {key}.")
        return expected

    def _window_signatures(self, segment_views: dict[str, SegmentView]) -> dict[str, Any]:
        signatures: dict[str, Any] = {}
        for name, view in segment_views.items():
            frame = view.frame
            warmup_rows = int(view.warmup_rows)
            segment_rows = int(view.segment_rows)
            signatures[f"warmup_{name}"] = build_data_signature(frame.iloc[:warmup_rows].copy(), symbol=self.symbol, interval=self.interval)
            signatures[name] = build_data_signature(frame.iloc[warmup_rows:warmup_rows + segment_rows].copy(), symbol=self.symbol, interval=self.interval)
        return signatures

    def _segment_signature(self, segment_view: SegmentView) -> dict[str, Any]:
        return build_data_signature(segment_view.frame, symbol=self.symbol, interval=self.interval)

    def _segment_context(self, segment_view: SegmentView, *, phase: str, frozen_selection: FrozenSelection | None = None) -> dict[str, Any]:
        context: dict[str, Any] = {
            "segment": segment_view.as_dict(),
            "segment_view": segment_view,
            "phase": phase,
            "trade_start_index": segment_view.trade_start_index,
            "segment_signature": self._segment_signature(segment_view),
        }
        if frozen_selection is not None:
            context["frozen_selection"] = frozen_selection.as_dict()
        return context

    def _evaluate_window_selection(
        self,
        df: pd.DataFrame,
        window,
        candidate_grid: Sequence[CandidateConfig],
        *,
        runner,
        execution_contract: dict[str, Any] | None = None,
        window_signatures: dict[str, Any] | None = None,
        runner_trusted: bool = False,
    ) -> WalkForwardWindowResult:
        segment_views = build_window_segment_views(df, window, self.split_config.warmup_bars)
        signatures = window_signatures or self._window_signatures(segment_views)
        candidate_evaluations: list[CandidateEvaluation] = []
        for candidate in candidate_grid:
            train_view = segment_views["train"]
            validation_view = segment_views["validation"]
            train_metrics = evaluate_segment(
                train_view.frame,
                candidate,
                segment="train",
                runner=runner,
                context=self._segment_context(train_view, phase="train"),
            )
            validation_metrics = evaluate_segment(
                validation_view.frame,
                candidate,
                segment="validation",
                runner=runner,
                context=self._segment_context(validation_view, phase="validation"),
            )
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
        manifest = self._window_manifest(
            window,
            candidate_grid,
            signatures["test"],
            execution_contract=execution_contract or {},
            window_signatures=signatures,
            runner_trusted=runner_trusted,
        )
        if not outcome.approved or outcome.candidate is None:
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

        frozen = self.freeze_window(
            outcome.candidate,
            window_id=f"{window.train_start}:{window.validation_start}:{window.test_start}",
            frozen_at=pd.to_datetime(df.iloc[window.test_start]["open_time"], utc=True).to_pydatetime(),
            manifest_hash_value=manifest["manifest_hash"],
            execution_contract=execution_contract or {},
        )
        return WalkForwardWindowResult(
            bounds=window,
            candidate_evaluations=tuple(candidate_evaluations),
            selected_candidate=outcome.candidate,
            frozen_selection=frozen,
            test_metrics=None,
            manifest_hash=manifest["manifest_hash"],
            approved=True,
            reason=outcome.reason,
        )

    def _evaluate_window_test(
        self,
        df: pd.DataFrame,
        window_result: WalkForwardWindowResult,
        *,
        runner,
        execution_contract: dict[str, Any] | None = None,
        window_signatures: dict[str, Any] | None = None,
        runner_trusted: bool = False,
    ) -> WalkForwardWindowResult:
        if not window_result.approved or window_result.selected_candidate is None or window_result.frozen_selection is None:
            return window_result

        test_view = build_window_segment_views(df, window_result.bounds, self.split_config.warmup_bars)["test"]
        test_metrics = evaluate_frozen_selection(
            test_view.frame,
            window_result.selected_candidate,
            window_result.frozen_selection,
            segment="test",
            runner=runner,
            context=self._segment_context(test_view, phase="test", frozen_selection=window_result.frozen_selection),
        )
        return WalkForwardWindowResult(
            bounds=window_result.bounds,
            candidate_evaluations=window_result.candidate_evaluations,
            selected_candidate=window_result.selected_candidate,
            frozen_selection=window_result.frozen_selection,
            test_metrics=test_metrics,
            manifest_hash=window_result.manifest_hash,
            approved=window_result.approved,
            reason=window_result.reason,
        )

    def _window_contract(self, runner) -> tuple[dict[str, Any], bool]:
        contract = self._runner_execution_contract(runner)
        if contract is None:
            if self.require_trusted_runner:
                raise ValidationFreezeError("trusted runner is required for this validation workflow.")
            return {}, False
        runner_trusted = True
        validated_contract = self._validate_execution_contract(contract)
        return validated_contract, runner_trusted

    def evaluate_window(
        self,
        df: pd.DataFrame,
        window,
        candidate_grid: Sequence[CandidateConfig],
        *,
        runner,
    ) -> WalkForwardWindowResult:
        contract, runner_trusted = self._window_contract(runner)
        segment_views = build_window_segment_views(df, window, self.split_config.warmup_bars)
        window_signatures = self._window_signatures(segment_views)
        selection_result = self._evaluate_window_selection(
            df,
            window,
            candidate_grid,
            runner=runner,
            execution_contract=contract,
            window_signatures=window_signatures,
            runner_trusted=runner_trusted,
        )
        return self._evaluate_window_test(
            df,
            selection_result,
            runner=runner,
            execution_contract=contract,
            window_signatures=window_signatures,
            runner_trusted=runner_trusted,
        )

    def run(self, df: pd.DataFrame, candidate_grid: Sequence[CandidateConfig], *, runner) -> WalkForwardResult:
        if self._session_consumed:
            raise ValidationFreezeError("validator session already consumed; create a new instance to rerun.")
        windows = build_windows(df, self.split_config)
        contract, runner_trusted = self._window_contract(runner)
        window_signatures_list = []
        for window in windows:
            segment_views = build_window_segment_views(df, window, self.split_config.warmup_bars)
            window_signatures_list.append(self._window_signatures(segment_views))
        selection_results = [
            self._evaluate_window_selection(
                df,
                window,
                candidate_grid,
                runner=runner,
                execution_contract=contract,
                window_signatures=window_signatures,
                runner_trusted=runner_trusted,
            )
            for window, window_signatures in zip(windows, window_signatures_list)
        ]
        results = [
            self._evaluate_window_test(
                df,
                window_result,
                runner=runner,
                execution_contract=contract,
                window_signatures=window_signatures,
                runner_trusted=runner_trusted,
            )
            for window_result, window_signatures in zip(selection_results, window_signatures_list)
        ]
        data_signature = build_data_signature(df, symbol=self.symbol, interval=self.interval)
        manifest = build_manifest(
            symbol=self.symbol,
            interval=self.interval,
            strategy_version=self.strategy_version,
            costs=self.costs,
            selection_criteria=self.selection_criteria.as_dict(),
            execution_contract=contract,
            window_signatures={"windows": window_signatures_list},
            runner_trusted=runner_trusted,
            split_config=self.split_config,
            candidate_grid=candidate_grid,
            windows=windows,
            data_signature=data_signature,
            seed=self.seed,
        )
        summary = aggregate_run_statistics(results)
        summary["manifest_hash"] = manifest["manifest_hash"]
        summary["strategy_version"] = self.strategy_version
        summary["symbol"] = self.symbol
        summary["interval"] = self.interval
        summary["mode"] = self.split_config.mode
        summary["runner_trusted"] = runner_trusted
        if any(window.test_metrics is not None for window in results):
            self._session_consumed = True
        return WalkForwardResult(windows=tuple(results), summary=summary, manifest=manifest)


def run_walk_forward_validation(df: pd.DataFrame, candidate_grid: Sequence[CandidateConfig], *, runner, split_config: ValidationSplitConfig | None = None, selection_criteria: SelectionCriteria | None = None, strategy_version: str = "v4_walk_forward", symbol: str = "BTCUSDT", interval: str = "1h", costs: dict[str, Any] | None = None, seed: int | None = None, require_trusted_runner: bool = True) -> WalkForwardResult:
    validator = WalkForwardValidator(
        split_config=split_config or ValidationSplitConfig(),
        selection_criteria=selection_criteria or SelectionCriteria(),
        strategy_version=strategy_version,
        costs=costs or {},
        symbol=symbol,
        interval=interval,
        seed=seed,
        require_trusted_runner=require_trusted_runner,
    )
    return validator.run(df, candidate_grid, runner=runner)
