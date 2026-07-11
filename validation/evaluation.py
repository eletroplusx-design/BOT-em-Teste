from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd

from .errors import ValidationEvaluationError
from .models import CandidateConfig, FrozenSelection, SegmentMetrics, WindowBounds
from .splits import slice_window_frames


Runner = Callable[[pd.DataFrame, CandidateConfig, str], Mapping[str, Any]]


def _to_metrics(result: Mapping[str, Any]) -> SegmentMetrics:
    summary = result.get("summary", result)
    if not isinstance(summary, Mapping):
        raise ValidationEvaluationError("runner must return a mapping with summary metrics.")
    return SegmentMetrics.from_summary(summary)


def evaluate_segment(
    df: pd.DataFrame,
    candidate: CandidateConfig,
    *,
    segment: str,
    runner: Runner,
    context: Mapping[str, Any] | None = None,
    frozen_selection: FrozenSelection | None = None,
) -> SegmentMetrics:
    try:
        result = runner(df, candidate, segment=segment, context=context or {}, frozen_selection=frozen_selection)
    except Exception as exc:  # pragma: no cover - runner failures are converted to typed errors
        raise ValidationEvaluationError(str(exc)) from exc
    return _to_metrics(result)


def evaluate_frozen_selection(
    df: pd.DataFrame,
    candidate: CandidateConfig,
    frozen_selection: FrozenSelection,
    *,
    segment: str,
    runner: Runner,
    context: Mapping[str, Any] | None = None,
) -> SegmentMetrics:
    if frozen_selection.candidate != candidate:
        raise ValidationEvaluationError("frozen selection candidate mismatch.")
    return evaluate_segment(df, candidate, segment=segment, runner=runner, context=context, frozen_selection=frozen_selection)
