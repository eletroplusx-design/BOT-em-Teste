"""Hash-anchored, research-only multi-timeframe historical experiments.

This module deliberately has no dependency on paper or promotion workflows.  It
is an opt-in wrapper around the trusted 15m/1h/4h alignment contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from domain.serialization import serialize_value
from historical_experiments import HistoricalStrategyFingerprint
from market_data import (
    HISTORICAL_MULTITIMEFRAME_ALIGNMENT_RULE,
    HISTORICAL_MULTITIMEFRAME_SCHEMA_VERSION,
    HistoricalDataValidationError,
    HistoricalMultiTimeframeBundle,
    HistoricalMultiTimeframeSnapshot,
    align_historical_multitimeframe_series,
)


HISTORICAL_MULTITIMEFRAME_EXPERIMENT_SCHEMA_VERSION = 1


class HistoricalMultiTimeframeExperimentError(Exception):
    pass


class HistoricalMultiTimeframeExperimentValidationError(HistoricalMultiTimeframeExperimentError):
    pass


class HistoricalMultiTimeframeExperimentIntegrityError(HistoricalMultiTimeframeExperimentValidationError):
    pass


class HistoricalMultiTimeframeExperimentConflictError(HistoricalMultiTimeframeExperimentIntegrityError):
    pass


class HistoricalMultiTimeframeExperimentPromotionError(HistoricalMultiTimeframeExperimentValidationError):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _required_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalMultiTimeframeExperimentValidationError(f"{name} is required.")
    return value.strip()


def _utc(value: Any, name: str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise HistoricalMultiTimeframeExperimentValidationError(f"{name} must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value, "datetime").isoformat().replace("+00:00", "Z")


def _research_only(classification: str, operational_evidence: bool, paper_promotion_eligible: bool) -> None:
    if classification != "historical_research_only":
        raise HistoricalMultiTimeframeExperimentValidationError("classification must be historical_research_only.")
    if operational_evidence is not False:
        raise HistoricalMultiTimeframeExperimentValidationError("operational_evidence must be false.")
    if paper_promotion_eligible is not False:
        raise HistoricalMultiTimeframeExperimentValidationError("paper_promotion_eligible must be false.")


def _bundle_from_dict(payload: Mapping[str, Any]) -> HistoricalMultiTimeframeBundle:
    try:
        return HistoricalMultiTimeframeBundle.from_dict(payload)
    except HistoricalDataValidationError as exc:
        raise HistoricalMultiTimeframeExperimentIntegrityError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeReplayProvenance:
    bundle_hash: str
    alignment_rule: str
    alignment_policy_hash: str
    schema_version: int = HISTORICAL_MULTITIMEFRAME_EXPERIMENT_SCHEMA_VERSION
    classification: str = "historical_research_only"
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False

    @classmethod
    def from_bundle(cls, bundle: HistoricalMultiTimeframeBundle) -> "HistoricalMultiTimeframeReplayProvenance":
        return cls(
            bundle_hash=bundle.bundle_hash,
            alignment_rule=bundle.alignment_rule,
            alignment_policy_hash=_hash({"schema_version": HISTORICAL_MULTITIMEFRAME_SCHEMA_VERSION, "alignment_rule": bundle.alignment_rule}),
        )

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_hash", _required_str(self.bundle_hash, "bundle_hash"))
        object.__setattr__(self, "alignment_rule", _required_str(self.alignment_rule, "alignment_rule"))
        object.__setattr__(self, "alignment_policy_hash", _required_str(self.alignment_policy_hash, "alignment_policy_hash"))
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_EXPERIMENT_SCHEMA_VERSION:
            raise HistoricalMultiTimeframeExperimentValidationError("multi-timeframe experiment schema_version must be 1.")
        if self.alignment_rule != HISTORICAL_MULTITIMEFRAME_ALIGNMENT_RULE:
            raise HistoricalMultiTimeframeExperimentValidationError("alignment rule is not the trusted close-time policy.")
        expected = _hash({"schema_version": HISTORICAL_MULTITIMEFRAME_SCHEMA_VERSION, "alignment_rule": self.alignment_rule})
        if self.alignment_policy_hash != expected:
            raise HistoricalMultiTimeframeExperimentValidationError("alignment policy hash mismatch.")
        _research_only(self.classification, self.operational_evidence, self.paper_promotion_eligible)

    def as_dict(self) -> dict[str, Any]:
        return {"bundle_hash": self.bundle_hash, "alignment_rule": self.alignment_rule, "alignment_policy_hash": self.alignment_policy_hash, "schema_version": self.schema_version, "classification": self.classification, "operational_evidence": self.operational_evidence, "paper_promotion_eligible": self.paper_promotion_eligible}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeReplayProvenance":
        return cls(**dict(data))


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeReplay:
    bundle: HistoricalMultiTimeframeBundle
    snapshots: tuple[HistoricalMultiTimeframeSnapshot, ...]
    provenance: HistoricalMultiTimeframeReplayProvenance
    replay_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.bundle, HistoricalMultiTimeframeBundle):
            raise HistoricalMultiTimeframeExperimentValidationError("bundle must be a HistoricalMultiTimeframeBundle instance.")
        if not isinstance(self.snapshots, tuple):
            object.__setattr__(self, "snapshots", tuple(self.snapshots))
        if not self.snapshots:
            raise HistoricalMultiTimeframeExperimentValidationError("aligned snapshots are required.")
        if not isinstance(self.provenance, HistoricalMultiTimeframeReplayProvenance):
            raise HistoricalMultiTimeframeExperimentValidationError("provenance must be multi-timeframe provenance.")
        if self.provenance != HistoricalMultiTimeframeReplayProvenance.from_bundle(self.bundle):
            raise HistoricalMultiTimeframeExperimentValidationError("replay provenance diverges from bundle.")
        expected_snapshots = align_historical_multitimeframe_series(self.bundle)
        if self.snapshots != expected_snapshots:
            raise HistoricalMultiTimeframeExperimentValidationError("snapshots diverge from trusted alignment.")
        if any(snapshot.bundle_hash != self.bundle.bundle_hash for snapshot in self.snapshots):
            raise HistoricalMultiTimeframeExperimentValidationError("snapshot bundle hash diverges.")
        expected = _hash(self.as_hash_payload(include_hash=False))
        if self.replay_hash and self.replay_hash != expected:
            raise HistoricalMultiTimeframeExperimentValidationError("replay hash mismatch.")
        object.__setattr__(self, "replay_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {"schema_version": HISTORICAL_MULTITIMEFRAME_EXPERIMENT_SCHEMA_VERSION, "bundle": self.bundle.as_dict(), "provenance": self.provenance.as_dict(), "snapshots": [snapshot.as_dict() for snapshot in self.snapshots]}
        if include_hash:
            value["replay_hash"] = self.replay_hash
        return value

    def as_dict(self) -> dict[str, Any]:
        return self.as_hash_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeReplay":
        value = dict(data)
        if value.get("schema_version") != HISTORICAL_MULTITIMEFRAME_EXPERIMENT_SCHEMA_VERSION:
            raise HistoricalMultiTimeframeExperimentIntegrityError("multi-timeframe replay schema_version mismatch.")
        return cls(bundle=_bundle_from_dict(value["bundle"]), snapshots=tuple(HistoricalMultiTimeframeSnapshot.from_dict(item) for item in value["snapshots"]), provenance=HistoricalMultiTimeframeReplayProvenance.from_dict(value["provenance"]), replay_hash=value.get("replay_hash", ""))


def build_historical_multitimeframe_replay(bundle: HistoricalMultiTimeframeBundle) -> HistoricalMultiTimeframeReplay:
    if not isinstance(bundle, HistoricalMultiTimeframeBundle):
        raise HistoricalMultiTimeframeExperimentValidationError("bundle must be a HistoricalMultiTimeframeBundle instance.")
    return HistoricalMultiTimeframeReplay(bundle=bundle, snapshots=align_historical_multitimeframe_series(bundle), provenance=HistoricalMultiTimeframeReplayProvenance.from_bundle(bundle))


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeExperimentPlan:
    replay: HistoricalMultiTimeframeReplay
    runner_factory_fingerprint: HistoricalStrategyFingerprint
    seed: int | None = None
    execution_config: Mapping[str, Any] = field(default_factory=dict)
    classification: str = "historical_research_only"
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    plan_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.replay, HistoricalMultiTimeframeReplay) or not isinstance(self.runner_factory_fingerprint, HistoricalStrategyFingerprint):
            raise HistoricalMultiTimeframeExperimentValidationError("plan requires replay and inspectable runner factory fingerprint.")
        if self.seed is not None and (type(self.seed) is bool or not isinstance(self.seed, int)):
            raise HistoricalMultiTimeframeExperimentValidationError("seed must be an integer or null.")
        if not isinstance(self.execution_config, Mapping):
            raise HistoricalMultiTimeframeExperimentValidationError("execution_config must be a mapping.")
        object.__setattr__(self, "execution_config", dict(self.execution_config))
        _research_only(self.classification, self.operational_evidence, self.paper_promotion_eligible)
        expected = _hash(self.as_hash_payload(include_hash=False))
        if self.plan_hash and self.plan_hash != expected:
            raise HistoricalMultiTimeframeExperimentValidationError("plan hash mismatch.")
        object.__setattr__(self, "plan_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {"replay_hash": self.replay.replay_hash, "runner_factory_fingerprint": self.runner_factory_fingerprint.as_dict(), "seed": self.seed, "execution_config": dict(self.execution_config), "classification": self.classification, "operational_evidence": self.operational_evidence, "paper_promotion_eligible": self.paper_promotion_eligible}
        if include_hash: value["plan_hash"] = self.plan_hash
        return value

    def as_dict(self) -> dict[str, Any]: return self.as_hash_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], replay: HistoricalMultiTimeframeReplay) -> "HistoricalMultiTimeframeExperimentPlan":
        value = dict(data); value.pop("replay_hash", None)
        return cls(replay=replay, runner_factory_fingerprint=HistoricalStrategyFingerprint.from_dict(value.pop("runner_factory_fingerprint")), **value)


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeExperimentReport:
    plan: HistoricalMultiTimeframeExperimentPlan
    replay: HistoricalMultiTimeframeReplay
    results: tuple[Any, ...]
    created_at_utc: datetime
    report_hash: str = ""
    classification: str = "historical_research_only"
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.plan.replay.replay_hash != self.replay.replay_hash:
            raise HistoricalMultiTimeframeExperimentValidationError("report replay diverges from plan.")
        if len(self.results) != len(self.replay.snapshots):
            raise HistoricalMultiTimeframeExperimentValidationError("result count must equal aligned snapshot count.")
        object.__setattr__(self, "results", tuple(self.results))
        object.__setattr__(self, "created_at_utc", _utc(self.created_at_utc, "created_at_utc"))
        _research_only(self.classification, self.operational_evidence, self.paper_promotion_eligible)
        expected = _hash(self.as_hash_payload(include_hash=False))
        if self.report_hash and self.report_hash != expected:
            raise HistoricalMultiTimeframeExperimentValidationError("report hash mismatch.")
        object.__setattr__(self, "report_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {"plan_hash": self.plan.plan_hash, "replay_hash": self.replay.replay_hash, "results": serialize_value(self.results), "classification": self.classification, "operational_evidence": self.operational_evidence, "paper_promotion_eligible": self.paper_promotion_eligible}
        if include_hash: value["report_hash"] = self.report_hash
        return value

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": HISTORICAL_MULTITIMEFRAME_EXPERIMENT_SCHEMA_VERSION, "plan": self.plan.as_dict(), "replay": self.replay.as_dict(), "results": serialize_value(self.results), "created_at_utc": _iso(self.created_at_utc), "report_hash": self.report_hash, "classification": self.classification, "operational_evidence": self.operational_evidence, "paper_promotion_eligible": self.paper_promotion_eligible}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeExperimentReport":
        value = dict(data)
        if value.pop("schema_version", None) != HISTORICAL_MULTITIMEFRAME_EXPERIMENT_SCHEMA_VERSION:
            raise HistoricalMultiTimeframeExperimentIntegrityError("multi-timeframe report schema_version mismatch.")
        replay = HistoricalMultiTimeframeReplay.from_dict(value.pop("replay"))
        plan = HistoricalMultiTimeframeExperimentPlan.from_dict(value.pop("plan"), replay)
        return cls(plan=plan, replay=replay, **value)


def build_historical_multitimeframe_experiment_plan(replay: HistoricalMultiTimeframeReplay, *, runner_factory: Callable[[], Callable[[HistoricalMultiTimeframeSnapshot], Any]], seed: int | None = None, execution_config: Mapping[str, Any] | None = None) -> HistoricalMultiTimeframeExperimentPlan:
    return HistoricalMultiTimeframeExperimentPlan(replay=replay, runner_factory_fingerprint=HistoricalStrategyFingerprint.from_callable(runner_factory), seed=seed, execution_config=dict(execution_config or {}))


def run_historical_multitimeframe_experiment(replay: HistoricalMultiTimeframeReplay, *, runner_factory: Callable[[], Callable[[HistoricalMultiTimeframeSnapshot], Any]], seed: int | None = None, execution_config: Mapping[str, Any] | None = None, plan: HistoricalMultiTimeframeExperimentPlan | None = None, output_file: str | Path | None = None) -> HistoricalMultiTimeframeExperimentReport:
    current_fingerprint = HistoricalStrategyFingerprint.from_callable(runner_factory)
    if plan is None:
        plan = HistoricalMultiTimeframeExperimentPlan(replay=replay, runner_factory_fingerprint=current_fingerprint, seed=seed, execution_config=dict(execution_config or {}))
    elif plan.replay.replay_hash != replay.replay_hash or plan.runner_factory_fingerprint != current_fingerprint:
        raise HistoricalMultiTimeframeExperimentValidationError("fingerprinted runner factory diverges from the factory being executed.")
    # This exact callable is fingerprinted above and is the only factory invoked.
    runner = runner_factory()
    if not callable(runner):
        raise HistoricalMultiTimeframeExperimentValidationError("runner_factory must return a callable runner.")
    results = tuple(runner(snapshot) for snapshot in replay.snapshots)
    report = HistoricalMultiTimeframeExperimentReport(plan=plan, replay=replay, results=results, created_at_utc=datetime.now(timezone.utc))
    if output_file is not None: save_historical_multitimeframe_experiment_report(output_file, report)
    return report


def _read(path: Path) -> Mapping[str, Any]:
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc: raise HistoricalMultiTimeframeExperimentValidationError("multi-timeframe report not found.") from exc
    except Exception as exc: raise HistoricalMultiTimeframeExperimentIntegrityError("multi-timeframe report is invalid JSON.") from exc
    if not isinstance(value, Mapping): raise HistoricalMultiTimeframeExperimentIntegrityError("multi-timeframe report must be a JSON object.")
    return value


def load_historical_multitimeframe_experiment_report(path: str | Path) -> HistoricalMultiTimeframeExperimentReport:
    payload = _read(Path(path))
    try: report = HistoricalMultiTimeframeExperimentReport.from_dict(payload)
    except (KeyError, TypeError, HistoricalMultiTimeframeExperimentValidationError, HistoricalDataValidationError) as exc: raise HistoricalMultiTimeframeExperimentIntegrityError(str(exc)) from exc
    if report.as_dict() != payload: raise HistoricalMultiTimeframeExperimentIntegrityError("multi-timeframe report payload mismatch.")
    return report


def save_historical_multitimeframe_experiment_report(path: str | Path, report: HistoricalMultiTimeframeExperimentReport) -> HistoricalMultiTimeframeExperimentReport:
    file_path, payload = Path(path), report.as_dict()
    if file_path.exists():
        existing = load_historical_multitimeframe_experiment_report(file_path)
        if existing.as_dict() != payload: raise HistoricalMultiTimeframeExperimentConflictError("multi-timeframe report already exists and differs.")
        return existing
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_name(f".{file_path.name}.{os.getpid()}.{id(report)}.tmp")
    try:
        tmp.write_text(_canonical_json(payload), encoding="utf-8"); os.replace(tmp, file_path)
    except Exception as exc:
        tmp.unlink(missing_ok=True); raise HistoricalMultiTimeframeExperimentValidationError("failed to write multi-timeframe report atomically.") from exc
    return report


def verify_historical_multitimeframe_experiment_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_multitimeframe_experiment_report(path)
    return {"verified": True, "report_hash": report.report_hash, "plan_hash": report.plan.plan_hash, "replay_hash": report.replay.replay_hash, "classification": report.classification}


def status_historical_multitimeframe_experiment_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_multitimeframe_experiment_report(path)
    return {"exists": True, "report_hash": report.report_hash, "plan_hash": report.plan.plan_hash, "replay_hash": report.replay.replay_hash, "symbol": report.replay.bundle.base_dataset.manifest.symbol, "base_interval": "15m", "classification": report.classification}


def reject_historical_multitimeframe_promotion(_: HistoricalMultiTimeframeExperimentReport | HistoricalMultiTimeframeReplay) -> None:
    raise HistoricalMultiTimeframeExperimentPromotionError("multi-timeframe historical research is not promotion evidence.")
