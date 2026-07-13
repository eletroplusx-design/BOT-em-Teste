from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from math import isfinite
from typing import Any, Mapping

from domain.serialization import serialize_value
from validation.artifacts import build_manifest, manifest_hash
from validation.models import CandidateConfig, FrozenSelection, SegmentMetrics, WalkForwardResult, WalkForwardWindowResult, WindowBounds
from validation.statistics import aggregate_run_statistics

from .artifacts import promotion_hash
from .errors import PromotionEvidenceError, PromotionValidationError


def _has_only_finite_values(value: Any) -> bool:
    if isinstance(value, Decimal):
        return value.is_finite()
    if isinstance(value, float):
        return isfinite(value)
    if isinstance(value, dict):
        return all(_has_only_finite_values(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return all(_has_only_finite_values(item) for item in value)
    return True


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PromotionEvidenceError(message)


def _normalize_str(value: Any) -> str:
    return str(value).strip()


@dataclass(frozen=True, slots=True)
class PromotionWindowEvidence:
    bounds: WindowBounds
    manifest_hash: str
    selected_candidate: CandidateConfig
    frozen_selection: FrozenSelection
    validation_metrics: SegmentMetrics
    test_metrics: SegmentMetrics
    candidate_evaluations: tuple[CandidateEvaluation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest_hash", _normalize_str(self.manifest_hash))
        object.__setattr__(self, "candidate_evaluations", tuple(self.candidate_evaluations))

    def as_dict(self) -> dict[str, Any]:
        return {
            "bounds": serialize_value(self.bounds),
            "manifest_hash": self.manifest_hash,
            "selected_candidate": serialize_value(self.selected_candidate),
            "frozen_selection": serialize_value(self.frozen_selection),
            "validation_metrics": serialize_value(self.validation_metrics),
            "test_metrics": serialize_value(self.test_metrics),
            "candidate_evaluations": serialize_value(self.candidate_evaluations),
        }


@dataclass(frozen=True, slots=True)
class PromotionEvidence:
    manifest: dict[str, Any]
    manifest_hash: str
    summary: dict[str, Any]
    windows: tuple[PromotionWindowEvidence, ...]
    recalculated_metrics: dict[str, Any]
    symbol: str
    interval: str
    strategy_version: str
    runner_trusted: bool
    paper_only: bool
    engine_class: str
    execution_contract: dict[str, Any]
    window_count_expected: int
    window_count_received: int
    builder_signature: str = field(default="", compare=False, init=False, repr=False)
    evidence_hash: str = field(default="", compare=False)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc), compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest", dict(self.manifest))
        object.__setattr__(self, "manifest_hash", _normalize_str(self.manifest_hash))
        object.__setattr__(self, "summary", dict(self.summary))
        object.__setattr__(self, "windows", tuple(self.windows))
        object.__setattr__(self, "recalculated_metrics", dict(self.recalculated_metrics))
        object.__setattr__(self, "symbol", _normalize_str(self.symbol).upper())
        object.__setattr__(self, "interval", _normalize_str(self.interval))
        object.__setattr__(self, "strategy_version", _normalize_str(self.strategy_version))
        object.__setattr__(self, "engine_class", _normalize_str(self.engine_class))
        object.__setattr__(self, "execution_contract", dict(self.execution_contract))
        object.__setattr__(self, "created_at_utc", self.created_at_utc.astimezone(timezone.utc))
        if not self.evidence_hash:
            payload = self.as_hash_payload()
            object.__setattr__(self, "evidence_hash", promotion_hash(payload))

    def as_hash_payload(self) -> dict[str, Any]:
        return {
            "manifest_hash": self.manifest_hash,
            "summary": self.summary,
            "windows": [window.as_dict() for window in self.windows],
            "recalculated_metrics": self.recalculated_metrics,
            "symbol": self.symbol,
            "interval": self.interval,
            "strategy_version": self.strategy_version,
            "runner_trusted": self.runner_trusted,
            "paper_only": self.paper_only,
            "engine_class": self.engine_class,
            "execution_contract": self.execution_contract,
            "window_count_expected": self.window_count_expected,
            "window_count_received": self.window_count_received,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest": serialize_value(self.manifest),
            "manifest_hash": self.manifest_hash,
            "summary": serialize_value(self.summary),
            "windows": [window.as_dict() for window in self.windows],
            "recalculated_metrics": serialize_value(self.recalculated_metrics),
            "symbol": self.symbol,
            "interval": self.interval,
            "strategy_version": self.strategy_version,
            "runner_trusted": self.runner_trusted,
            "paper_only": self.paper_only,
            "engine_class": self.engine_class,
            "execution_contract": serialize_value(self.execution_contract),
            "window_count_expected": self.window_count_expected,
            "window_count_received": self.window_count_received,
            "evidence_hash": self.evidence_hash,
            "created_at_utc": self.created_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }


def _window_from_result(window: WalkForwardWindowResult) -> PromotionWindowEvidence:
    if not window.approved:
        raise PromotionEvidenceError("window must be approved.")
    if window.selected_candidate is None or window.frozen_selection is None or window.test_metrics is None:
        raise PromotionEvidenceError("window must include selected candidate, frozen selection and test metrics.")
    validation_metrics = next(
        (evaluation.validation_metrics for evaluation in window.candidate_evaluations if evaluation.candidate == window.selected_candidate),
        None,
    )
    if validation_metrics is None:
        raise PromotionEvidenceError("selected candidate validation metrics are missing.")
    if window.selected_candidate != window.frozen_selection.candidate:
        raise PromotionEvidenceError("selected candidate diverges from frozen selection candidate.")
    if window.frozen_selection.manifest_hash != window.manifest_hash:
        raise PromotionEvidenceError("frozen selection manifest hash diverges from window manifest.")
    if sum(1 for evaluation in window.candidate_evaluations if evaluation.candidate == window.selected_candidate) != 1:
        raise PromotionEvidenceError("selected candidate must have exactly one matching evaluation.")
    return PromotionWindowEvidence(
        bounds=window.bounds,
        manifest_hash=window.manifest_hash,
        selected_candidate=window.selected_candidate,
        frozen_selection=window.frozen_selection,
        validation_metrics=validation_metrics,
        test_metrics=window.test_metrics,
        candidate_evaluations=tuple(window.candidate_evaluations),
    )


def build_promotion_evidence(result: WalkForwardResult) -> PromotionEvidence:
    if result is None:
        raise PromotionEvidenceError("walk forward result is required.")
    manifest = dict(result.manifest or {})
    summary = dict(result.summary or {})
    manifest_hash_value = _normalize_str(manifest.get("manifest_hash", ""))
    if not manifest_hash_value:
        raise PromotionEvidenceError("manifest hash is required.")
    manifest_payload = dict(manifest)
    manifest_payload.pop("manifest_hash", None)
    if manifest_hash(manifest_payload) != manifest_hash_value:
        raise PromotionEvidenceError("manifest hash mismatch.")
    execution_contract = dict(manifest.get("execution_contract") or {})
    runner_trusted = bool(manifest.get("runner_trusted"))
    paper_only = bool(execution_contract.get("paper_only"))
    engine_class = _normalize_str(execution_contract.get("engine_class", ""))
    symbol = _normalize_str(manifest.get("symbol", ""))
    interval = _normalize_str(manifest.get("interval", ""))
    strategy_version = _normalize_str(manifest.get("strategy_version", ""))
    _require(runner_trusted is True, "runner must be trusted.")
    _require(paper_only is True, "execution must remain paper-only.")
    _require(engine_class == "LeakFreeBacktestEngine", "engine class must be LeakFreeBacktestEngine.")
    _require(bool(symbol), "symbol is required.")
    _require(bool(interval), "interval is required.")
    _require(bool(strategy_version), "strategy version is required.")
    _require(isinstance(manifest.get("windows"), list), "manifest windows are required.")
    _require(isinstance(manifest.get("window_signatures"), dict), "window signatures are required.")
    _require(isinstance(manifest["window_signatures"].get("windows"), list), "window signatures must include windows.")
    _require(result.windows, "at least one window is required.")
    windows = tuple(_window_from_result(window) for window in result.windows)
    recalculated_metrics = aggregate_run_statistics(result.windows)
    if not _has_only_finite_values(summary) or not _has_only_finite_values(recalculated_metrics):
        raise PromotionEvidenceError("summary contains non-finite values.")
    expected_windows = len(manifest["windows"])
    received_windows = len(result.windows)
    if expected_windows != received_windows:
        raise PromotionEvidenceError("window count mismatch.")
    if len(manifest["window_signatures"]["windows"]) != received_windows:
        raise PromotionEvidenceError("window signatures count mismatch.")
    candidate_grid = [CandidateConfig.from_mapping(candidate["name"], candidate.get("parameters", {})) for candidate in manifest.get("candidate_grid", [])]
    if not candidate_grid:
        raise PromotionEvidenceError("candidate grid is required.")
    split_config = manifest.get("split_config")
    if split_config is None:
        raise PromotionEvidenceError("split config is required.")
    candidate_grid_dicts = [candidate.as_dict() for candidate in candidate_grid]
    for window_result, window_manifest_data, window_signature in zip(result.windows, manifest["windows"], manifest["window_signatures"]["windows"]):
        selected_candidate_dict = window_result.selected_candidate.as_dict()
        if selected_candidate_dict not in candidate_grid_dicts:
            raise PromotionEvidenceError("selected candidate must appear in the candidate grid.")
        if window_result.frozen_selection.candidate.as_dict() != selected_candidate_dict:
            raise PromotionEvidenceError("selected candidate diverges from frozen selection candidate.")
        rebuilt_window_manifest = build_manifest(
            symbol=symbol,
            interval=interval,
            strategy_version=strategy_version,
            costs=manifest.get("costs", {}),
            selection_criteria=manifest.get("selection_criteria", {}),
            execution_contract=execution_contract,
            window_signatures=window_signature,
            runner_trusted=runner_trusted,
            split_config=split_config,
            candidate_grid=candidate_grid,
            windows=[WindowBounds(**window_manifest_data)],
            data_signature=window_signature.get("test", {}),
            seed=manifest.get("seed"),
        )
        if window_result.manifest_hash != rebuilt_window_manifest["manifest_hash"]:
            raise PromotionEvidenceError("window manifest hash mismatch.")
    if manifest.get("symbol") != symbol or manifest.get("interval") != interval or manifest.get("strategy_version") != strategy_version:
        raise PromotionEvidenceError("manifest contract diverges from result contract.")
    if manifest.get("execution_contract", {}).get("engine_class") != "LeakFreeBacktestEngine":
        raise PromotionEvidenceError("execution contract must include LeakFreeBacktestEngine.")
    if summary.get("manifest_hash") not in (None, manifest_hash_value):
        raise PromotionEvidenceError("summary manifest hash diverges.")
    evidence = PromotionEvidence(
        manifest=manifest,
        manifest_hash=manifest_hash_value,
        summary=summary,
        windows=windows,
        recalculated_metrics=recalculated_metrics,
        symbol=symbol,
        interval=interval,
        strategy_version=strategy_version,
        runner_trusted=runner_trusted,
        paper_only=paper_only,
        engine_class=engine_class,
        execution_contract=execution_contract,
        window_count_expected=expected_windows,
        window_count_received=received_windows,
    )
    object.__setattr__(evidence, "builder_signature", promotion_hash(evidence.as_hash_payload()))
    return evidence


def validate_promotion_evidence(evidence: PromotionEvidence) -> None:
    if evidence is None:
        raise PromotionEvidenceError("promotion evidence is required.")
    if not isinstance(evidence, PromotionEvidence):
        raise PromotionEvidenceError("promotion evidence has invalid type.")
    if not evidence.runner_trusted:
        raise PromotionEvidenceError("runner must be trusted.")
    if not evidence.paper_only:
        raise PromotionEvidenceError("execution must remain paper-only.")
    if not evidence.builder_signature:
        raise PromotionEvidenceError("promotion evidence must originate from the trusted builder.")
    if evidence.builder_signature != promotion_hash(evidence.as_hash_payload()):
        raise PromotionEvidenceError("promotion evidence hash mismatch.")
    for window in evidence.windows:
        if not isinstance(window.bounds, WindowBounds):
            raise PromotionEvidenceError("window bounds must be typed.")
        if not isinstance(window.selected_candidate, CandidateConfig):
            raise PromotionEvidenceError("window candidate must be typed.")
        if not isinstance(window.frozen_selection, FrozenSelection):
            raise PromotionEvidenceError("frozen selection must be typed.")
        if not isinstance(window.validation_metrics, SegmentMetrics):
            raise PromotionEvidenceError("validation metrics must be typed.")
        if not isinstance(window.test_metrics, SegmentMetrics):
            raise PromotionEvidenceError("test metrics must be typed.")
