from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Mapping

from domain import Candle, DataSource
from domain.serialization import serialize_value

from .errors import HistoricalDataValidationError
from .historical_alignment import (
    HISTORICAL_MULTITIMEFRAME_ALIGNMENT_RULE,
    HISTORICAL_MULTITIMEFRAME_BASE_INTERVAL,
    HISTORICAL_MULTITIMEFRAME_SCHEMA_VERSION,
    HISTORICAL_MULTITIMEFRAME_SUPPORTING_INTERVALS,
    HistoricalMultiTimeframeBundle,
    HistoricalMultiTimeframeSnapshot,
    align_historical_multitimeframe_series,
    align_historical_multitimeframe_snapshot,
)
from .historical_models import HistoricalDataset, HistoricalDatasetManifest
from .provider_qualification import HistoricalProviderQualification, KUCOIN_PUBLIC_SPOT_INTERVAL_SECONDS


HISTORICAL_MULTITIMEFRAME_CONTEXT_SCHEMA_VERSION = 1
HISTORICAL_MULTITIMEFRAME_CONTEXT_RULE = "15m decision candle -> closed 1h/4h historical context only"


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        serialize_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalDataValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalDataValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalDataValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalDataValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalDataValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.") from exc
    if not isinstance(value, datetime):
        raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _expected_source_for_exchange(exchange: str) -> DataSource:
    normalized = _require_str(exchange, "exchange").lower()
    if normalized == "binance":
        return DataSource.BINANCE
    if normalized == "kucoin":
        return DataSource.KUCOIN
    raise HistoricalDataValidationError(f"unsupported exchange for historical context: {exchange!r}")


def _alignment_policy_hash() -> str:
    return _hash_payload(
        {
            "schema_version": HISTORICAL_MULTITIMEFRAME_CONTEXT_SCHEMA_VERSION,
            "alignment_rule": HISTORICAL_MULTITIMEFRAME_ALIGNMENT_RULE,
            "base_interval": HISTORICAL_MULTITIMEFRAME_BASE_INTERVAL,
            "supporting_intervals": HISTORICAL_MULTITIMEFRAME_SUPPORTING_INTERVALS,
        }
    )


def _dataset_window_candles(dataset: HistoricalDataset, decision_time_utc: datetime) -> tuple[Candle, ...]:
    candles = tuple(dataset.candles)
    close_times = [candle.close_time for candle in candles]
    index = bisect_right(close_times, decision_time_utc)
    window = candles[:index]
    if not window:
        raise HistoricalDataValidationError("historical context requires closed candles at the decision time.")
    if window[-1].close_time > decision_time_utc:
        raise HistoricalDataValidationError("historical context cannot include future candles.")
    return window


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeDecisionContextPolicy:
    schema_version: int = HISTORICAL_MULTITIMEFRAME_CONTEXT_SCHEMA_VERSION
    alignment_rule: str = HISTORICAL_MULTITIMEFRAME_ALIGNMENT_RULE
    alignment_policy_hash: str = ""
    minimum_base_candles: int = 1
    minimum_one_hour_candles: int = 1
    minimum_four_hour_candles: int = 1
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    context_rule: str = HISTORICAL_MULTITIMEFRAME_CONTEXT_RULE
    context_policy_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "alignment_rule", _require_str(self.alignment_rule, "alignment_rule"))
        object.__setattr__(self, "alignment_policy_hash", _require_str(self.alignment_policy_hash, "alignment_policy_hash") if self.alignment_policy_hash else _alignment_policy_hash())
        object.__setattr__(self, "minimum_base_candles", _require_int(self.minimum_base_candles, "minimum_base_candles"))
        object.__setattr__(self, "minimum_one_hour_candles", _require_int(self.minimum_one_hour_candles, "minimum_one_hour_candles"))
        object.__setattr__(self, "minimum_four_hour_candles", _require_int(self.minimum_four_hour_candles, "minimum_four_hour_candles"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "context_rule", _require_str(self.context_rule, "context_rule"))
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_CONTEXT_SCHEMA_VERSION:
            raise HistoricalDataValidationError("context schema_version must be 1.")
        if self.alignment_rule != HISTORICAL_MULTITIMEFRAME_ALIGNMENT_RULE:
            raise HistoricalDataValidationError("alignment rule diverges from the trusted multi-timeframe policy.")
        if self.alignment_policy_hash != _alignment_policy_hash():
            raise HistoricalDataValidationError("alignment policy hash mismatch.")
        if self.minimum_base_candles <= 0 or self.minimum_one_hour_candles <= 0 or self.minimum_four_hour_candles <= 0:
            raise HistoricalDataValidationError("minimum warm-up must be greater than zero.")
        if self.historical_research_only is not True:
            raise HistoricalDataValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise HistoricalDataValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise HistoricalDataValidationError("paper_promotion_eligible must be false.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.context_policy_hash:
            if self.context_policy_hash != expected:
                raise HistoricalDataValidationError("context policy hash mismatch.")
        else:
            object.__setattr__(self, "context_policy_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "alignment_rule": self.alignment_rule,
            "alignment_policy_hash": self.alignment_policy_hash,
            "minimum_base_candles": self.minimum_base_candles,
            "minimum_one_hour_candles": self.minimum_one_hour_candles,
            "minimum_four_hour_candles": self.minimum_four_hour_candles,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "context_rule": self.context_rule,
        }
        if include_hash:
            payload["context_policy_hash"] = self.context_policy_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeDecisionContextPolicy":
        if not isinstance(data, Mapping):
            raise HistoricalDataValidationError("historical context policy must be a mapping.")
        mapping = dict(data)
        try:
            return cls(
                schema_version=mapping["schema_version"],
                alignment_rule=mapping["alignment_rule"],
                alignment_policy_hash=mapping.get("alignment_policy_hash", ""),
                minimum_base_candles=mapping["minimum_base_candles"],
                minimum_one_hour_candles=mapping["minimum_one_hour_candles"],
                minimum_four_hour_candles=mapping["minimum_four_hour_candles"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                context_rule=mapping["context_rule"],
                context_policy_hash=mapping.get("context_policy_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalDataValidationError("historical context policy is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeDecisionWindow:
    interval: str
    dataset_manifest: HistoricalDatasetManifest
    candles: tuple[Candle, ...]
    schema_version: int = HISTORICAL_MULTITIMEFRAME_CONTEXT_SCHEMA_VERSION
    window_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        if self.interval not in (HISTORICAL_MULTITIMEFRAME_BASE_INTERVAL, *HISTORICAL_MULTITIMEFRAME_SUPPORTING_INTERVALS):
            raise HistoricalDataValidationError("historical context only supports 15m, 1h, and 4h intervals.")
        if not isinstance(self.dataset_manifest, HistoricalDatasetManifest):
            raise HistoricalDataValidationError("dataset_manifest must be a HistoricalDatasetManifest instance.")
        if not isinstance(self.candles, tuple):
            object.__setattr__(self, "candles", tuple(self.candles))
        if not self.candles:
            raise HistoricalDataValidationError("historical context window must contain candles.")
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_CONTEXT_SCHEMA_VERSION:
            raise HistoricalDataValidationError("context window schema_version must be 1.")
        if self.dataset_manifest.interval != self.interval:
            raise HistoricalDataValidationError("historical context window interval diverges from dataset manifest.")
        qualification = self.dataset_manifest.provider_qualification
        if not isinstance(qualification, HistoricalProviderQualification):
            raise HistoricalDataValidationError("historical context window provider qualification is required.")
        expected_source = _expected_source_for_exchange(qualification.exchange)
        expected_symbol = _require_str(self.dataset_manifest.symbol, "dataset_manifest.symbol").upper()
        for candle in self.candles:
            if not isinstance(candle, Candle):
                raise HistoricalDataValidationError("historical context window candles must be Candle instances.")
            if candle.interval != self.interval:
                raise HistoricalDataValidationError("historical context window candle interval diverges.")
            if candle.symbol != expected_symbol:
                raise HistoricalDataValidationError("historical context window candle symbol diverges.")
            if candle.source != expected_source:
                raise HistoricalDataValidationError("historical context window candle source diverges.")
        interval_seconds = KUCOIN_PUBLIC_SPOT_INTERVAL_SECONDS[self.interval]
        expected_duration = timedelta(seconds=interval_seconds)
        for previous, current in zip(self.candles, self.candles[1:]):
            if current.open_time != previous.open_time + expected_duration:
                raise HistoricalDataValidationError("historical context window candles must be contiguous.")
        for candle in self.candles:
            if candle.close_time != candle.open_time + expected_duration - timedelta(milliseconds=1):
                raise HistoricalDataValidationError("historical context window candle close_time rule diverges.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.window_hash:
            if self.window_hash != expected:
                raise HistoricalDataValidationError("historical context window hash mismatch.")
        else:
            object.__setattr__(self, "window_hash", expected)

    @property
    def window_start_utc(self) -> datetime:
        return self.candles[0].open_time.astimezone(timezone.utc)

    @property
    def window_end_utc(self) -> datetime:
        return self.candles[-1].close_time.astimezone(timezone.utc)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "interval": self.interval,
            "dataset_manifest": self.dataset_manifest.as_dict(),
            "window_start_utc": _utc_iso(self.window_start_utc),
            "window_end_utc": _utc_iso(self.window_end_utc),
            "candle_count": len(self.candles),
            "candles": [candle.to_dict() for candle in self.candles],
        }
        if include_hash:
            payload["window_hash"] = self.window_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeDecisionWindow":
        if not isinstance(data, Mapping):
            raise HistoricalDataValidationError("historical context window must be a mapping.")
        mapping = dict(data)
        try:
            return cls(
                interval=mapping["interval"],
                dataset_manifest=HistoricalDatasetManifest.from_dict(mapping["dataset_manifest"]),
                candles=tuple(Candle.from_dict(item) for item in mapping["candles"]),
                schema_version=mapping["schema_version"],
                window_hash=mapping.get("window_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalDataValidationError("historical context window is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeDecisionContext:
    snapshot: HistoricalMultiTimeframeSnapshot
    policy: HistoricalMultiTimeframeDecisionContextPolicy
    base_window: HistoricalMultiTimeframeDecisionWindow
    supporting_windows: tuple[HistoricalMultiTimeframeDecisionWindow, ...]
    schema_version: int = HISTORICAL_MULTITIMEFRAME_CONTEXT_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    context_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, HistoricalMultiTimeframeSnapshot):
            raise HistoricalDataValidationError("snapshot must be a HistoricalMultiTimeframeSnapshot instance.")
        if not isinstance(self.policy, HistoricalMultiTimeframeDecisionContextPolicy):
            raise HistoricalDataValidationError("policy must be a HistoricalMultiTimeframeDecisionContextPolicy instance.")
        if not isinstance(self.base_window, HistoricalMultiTimeframeDecisionWindow):
            raise HistoricalDataValidationError("base_window must be a HistoricalMultiTimeframeDecisionWindow instance.")
        if not isinstance(self.supporting_windows, tuple):
            object.__setattr__(self, "supporting_windows", tuple(self.supporting_windows))
        if len(self.supporting_windows) != len(HISTORICAL_MULTITIMEFRAME_SUPPORTING_INTERVALS):
            raise HistoricalDataValidationError("supporting_windows must contain 1h and 4h windows.")
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_CONTEXT_SCHEMA_VERSION:
            raise HistoricalDataValidationError("historical context schema_version must be 1.")
        if self.historical_research_only is not True:
            raise HistoricalDataValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise HistoricalDataValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise HistoricalDataValidationError("paper_promotion_eligible must be false.")
        if self.snapshot.base_point.interval != HISTORICAL_MULTITIMEFRAME_BASE_INTERVAL:
            raise HistoricalDataValidationError("snapshot must use the trusted 15m base interval.")
        if self.snapshot.base_point.candle.close_time != self.base_window.window_end_utc:
            raise HistoricalDataValidationError("base window must end at the base snapshot close time.")
        if self.base_window.interval != HISTORICAL_MULTITIMEFRAME_BASE_INTERVAL:
            raise HistoricalDataValidationError("base window must use the 15m interval.")
        if self.base_window.candles[-1].close_time != self.snapshot.base_point.candle.close_time:
            raise HistoricalDataValidationError("base window must end on the base candle.")
        support_by_interval = {window.interval: window for window in self.supporting_windows}
        if set(support_by_interval) != set(HISTORICAL_MULTITIMEFRAME_SUPPORTING_INTERVALS):
            raise HistoricalDataValidationError("supporting windows must contain 1h and 4h intervals.")
        canonical_supporting = tuple(support_by_interval[interval] for interval in HISTORICAL_MULTITIMEFRAME_SUPPORTING_INTERVALS)
        object.__setattr__(self, "supporting_windows", canonical_supporting)
        for snapshot_point, window in zip(self.snapshot.supporting_points, canonical_supporting):
            if window.interval != snapshot_point.interval:
                raise HistoricalDataValidationError("supporting window interval diverges from aligned snapshot.")
            if window.candles[-1].close_time != snapshot_point.candle.close_time:
                raise HistoricalDataValidationError("supporting window must end at the aligned candle.")
        if len(self.base_window.candles) < self.policy.minimum_base_candles:
            raise HistoricalDataValidationError("historical context warm-up is insufficient.")
        if len(canonical_supporting[0].candles) < self.policy.minimum_one_hour_candles:
            raise HistoricalDataValidationError("historical context warm-up is insufficient.")
        if len(canonical_supporting[1].candles) < self.policy.minimum_four_hour_candles:
            raise HistoricalDataValidationError("historical context warm-up is insufficient.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.context_hash:
            if self.context_hash != expected:
                raise HistoricalDataValidationError("historical context hash mismatch.")
        else:
            object.__setattr__(self, "context_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "snapshot": self.snapshot.as_dict(),
            "policy": self.policy.as_dict(),
            "base_window": self.base_window.as_dict(),
            "supporting_windows": [window.as_dict() for window in self.supporting_windows],
        }
        if include_hash:
            payload["context_hash"] = self.context_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeDecisionContext":
        if not isinstance(data, Mapping):
            raise HistoricalDataValidationError("historical context must be a mapping.")
        mapping = dict(data)
        try:
            return cls(
                snapshot=HistoricalMultiTimeframeSnapshot.from_dict(mapping["snapshot"]),
                policy=HistoricalMultiTimeframeDecisionContextPolicy.from_dict(mapping["policy"]),
                base_window=HistoricalMultiTimeframeDecisionWindow.from_dict(mapping["base_window"]),
                supporting_windows=tuple(HistoricalMultiTimeframeDecisionWindow.from_dict(item) for item in mapping["supporting_windows"]),
                schema_version=mapping["schema_version"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                context_hash=mapping.get("context_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalDataValidationError("historical context is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeDecisionContextSeries:
    bundle: HistoricalMultiTimeframeBundle
    policy: HistoricalMultiTimeframeDecisionContextPolicy
    contexts: tuple[HistoricalMultiTimeframeDecisionContext, ...]
    schema_version: int = HISTORICAL_MULTITIMEFRAME_CONTEXT_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    series_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.bundle, HistoricalMultiTimeframeBundle):
            raise HistoricalDataValidationError("bundle must be a HistoricalMultiTimeframeBundle instance.")
        if not isinstance(self.policy, HistoricalMultiTimeframeDecisionContextPolicy):
            raise HistoricalDataValidationError("policy must be a HistoricalMultiTimeframeDecisionContextPolicy instance.")
        if not isinstance(self.contexts, tuple):
            object.__setattr__(self, "contexts", tuple(self.contexts))
        if not self.contexts:
            raise HistoricalDataValidationError("historical context series requires contexts.")
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_CONTEXT_SCHEMA_VERSION:
            raise HistoricalDataValidationError("historical context series schema_version must be 1.")
        if self.historical_research_only is not True:
            raise HistoricalDataValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise HistoricalDataValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise HistoricalDataValidationError("paper_promotion_eligible must be false.")
        expected_contexts = tuple(
            build_historical_multitimeframe_decision_context(
                self.bundle,
                base_candle=snapshot.base_point.candle,
                policy=self.policy,
                snapshot=snapshot,
            )
            for snapshot in align_historical_multitimeframe_series(self.bundle)
        )
        if self.contexts != expected_contexts:
            raise HistoricalDataValidationError("historical context series diverges from trusted alignment.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.series_hash:
            if self.series_hash != expected:
                raise HistoricalDataValidationError("historical context series hash mismatch.")
        else:
            object.__setattr__(self, "series_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "bundle_hash": self.bundle.bundle_hash,
            "policy": self.policy.as_dict(),
            "contexts": [context.as_dict() for context in self.contexts],
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }
        if include_hash:
            payload["series_hash"] = self.series_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], bundle: HistoricalMultiTimeframeBundle) -> "HistoricalMultiTimeframeDecisionContextSeries":
        if not isinstance(data, Mapping):
            raise HistoricalDataValidationError("historical context series must be a mapping.")
        mapping = dict(data)
        try:
            return cls(
                bundle=bundle,
                policy=HistoricalMultiTimeframeDecisionContextPolicy.from_dict(mapping["policy"]),
                contexts=tuple(HistoricalMultiTimeframeDecisionContext.from_dict(item) for item in mapping["contexts"]),
                schema_version=mapping["schema_version"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                series_hash=mapping.get("series_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalDataValidationError("historical context series is incomplete.") from exc


def build_historical_multitimeframe_decision_context_policy(
    *,
    minimum_base_candles: int = 1,
    minimum_one_hour_candles: int = 1,
    minimum_four_hour_candles: int = 1,
) -> HistoricalMultiTimeframeDecisionContextPolicy:
    return HistoricalMultiTimeframeDecisionContextPolicy(
        alignment_policy_hash=_alignment_policy_hash(),
        minimum_base_candles=minimum_base_candles,
        minimum_one_hour_candles=minimum_one_hour_candles,
        minimum_four_hour_candles=minimum_four_hour_candles,
    )


def _window_from_dataset(dataset: HistoricalDataset, decision_time_utc: datetime, *, interval: str) -> HistoricalMultiTimeframeDecisionWindow:
    if interval != dataset.manifest.interval:
        raise HistoricalDataValidationError("historical context window interval diverges from dataset interval.")
    candles = _dataset_window_candles(dataset, decision_time_utc)
    return HistoricalMultiTimeframeDecisionWindow(
        interval=interval,
        dataset_manifest=dataset.manifest,
        candles=candles,
    )


def build_historical_multitimeframe_decision_context(
    bundle: HistoricalMultiTimeframeBundle,
    *,
    base_candle: Candle,
    policy: HistoricalMultiTimeframeDecisionContextPolicy | None = None,
    snapshot: HistoricalMultiTimeframeSnapshot | None = None,
) -> HistoricalMultiTimeframeDecisionContext:
    if not isinstance(bundle, HistoricalMultiTimeframeBundle):
        raise HistoricalDataValidationError("bundle must be a HistoricalMultiTimeframeBundle instance.")
    if policy is None:
        policy = build_historical_multitimeframe_decision_context_policy()
    if snapshot is None:
        snapshot = align_historical_multitimeframe_snapshot(bundle, base_candle=base_candle)
    elif snapshot.base_point.candle != base_candle:
        raise HistoricalDataValidationError("snapshot and base_candle diverge.")
    decision_time_utc = snapshot.decision_time_utc
    base_window = _window_from_dataset(bundle.base_dataset, decision_time_utc, interval=HISTORICAL_MULTITIMEFRAME_BASE_INTERVAL)
    supporting_windows = tuple(
        _window_from_dataset(dataset, decision_time_utc, interval=dataset.manifest.interval)
        for dataset in bundle.supporting_datasets
    )
    return HistoricalMultiTimeframeDecisionContext(
        snapshot=snapshot,
        policy=policy,
        base_window=base_window,
        supporting_windows=supporting_windows,
    )


def build_historical_multitimeframe_decision_context_series(
    bundle: HistoricalMultiTimeframeBundle,
    *,
    policy: HistoricalMultiTimeframeDecisionContextPolicy | None = None,
) -> HistoricalMultiTimeframeDecisionContextSeries:
    if not isinstance(bundle, HistoricalMultiTimeframeBundle):
        raise HistoricalDataValidationError("bundle must be a HistoricalMultiTimeframeBundle instance.")
    if policy is None:
        policy = build_historical_multitimeframe_decision_context_policy()
    snapshots = align_historical_multitimeframe_series(bundle)
    contexts = tuple(
        build_historical_multitimeframe_decision_context(
            bundle,
            base_candle=snapshot.base_point.candle,
            policy=policy,
            snapshot=snapshot,
        )
        for snapshot in snapshots
    )
    return HistoricalMultiTimeframeDecisionContextSeries(bundle=bundle, policy=policy, contexts=contexts)


__all__ = [
    "HISTORICAL_MULTITIMEFRAME_CONTEXT_RULE",
    "HISTORICAL_MULTITIMEFRAME_CONTEXT_SCHEMA_VERSION",
    "HistoricalMultiTimeframeDecisionContextPolicy",
    "HistoricalMultiTimeframeDecisionWindow",
    "HistoricalMultiTimeframeDecisionContext",
    "HistoricalMultiTimeframeDecisionContextSeries",
    "build_historical_multitimeframe_decision_context_policy",
    "build_historical_multitimeframe_decision_context",
    "build_historical_multitimeframe_decision_context_series",
]
