from .adapters import LegacyBacktesterAdapter, adapt_legacy_report
from .artifacts import build_manifest, freeze_selection, manifest_hash
from .errors import (
    ValidationError,
    ValidationEvaluationError,
    ValidationFreezeError,
    ValidationSelectionError,
    ValidationSplitError,
)
from .evaluation import evaluate_frozen_selection, evaluate_segment
from .models import (
    CandidateConfig,
    CandidateEvaluation,
    FrozenSelection,
    SegmentMetrics,
    SelectionCriteria,
    ValidationRunResult,
    ValidationSplitConfig,
    WalkForwardResult,
    WalkForwardWindowResult,
    WindowBounds,
)
from .selection import SelectionOutcome, select_configuration
from .splits import build_expanding_windows, build_rolling_windows, build_windows
from .statistics import (
    aggregate_run_statistics,
    aggregate_segment_metrics,
    compute_candidate_stability,
    compute_dispersion,
    sanitize_metric_value,
)
from .walk_forward import WalkForwardValidator, run_walk_forward_validation

__all__ = [
    "LegacyBacktesterAdapter",
    "adapt_legacy_report",
    "build_manifest",
    "freeze_selection",
    "manifest_hash",
    "ValidationError",
    "ValidationEvaluationError",
    "ValidationFreezeError",
    "ValidationSelectionError",
    "ValidationSplitError",
    "evaluate_frozen_selection",
    "evaluate_segment",
    "CandidateConfig",
    "CandidateEvaluation",
    "FrozenSelection",
    "SegmentMetrics",
    "SelectionCriteria",
    "ValidationRunResult",
    "ValidationSplitConfig",
    "WalkForwardResult",
    "WalkForwardWindowResult",
    "WindowBounds",
    "SelectionOutcome",
    "select_configuration",
    "build_expanding_windows",
    "build_rolling_windows",
    "build_windows",
    "aggregate_run_statistics",
    "aggregate_segment_metrics",
    "compute_candidate_stability",
    "compute_dispersion",
    "sanitize_metric_value",
    "WalkForwardValidator",
    "run_walk_forward_validation",
]
