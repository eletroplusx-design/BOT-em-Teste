from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from domain import Candle
from domain.serialization import serialize_value

from .errors import HistoricalDataIntegrityError, HistoricalDataValidationError
from .historical_models import HistoricalDataset, HistoricalDatasetManifest
from .provider_qualification import HistoricalProviderQualification, KUCOIN_PUBLIC_SPOT_INTERVAL_SECONDS


HISTORICAL_MULTITIMEFRAME_SCHEMA_VERSION = 1
HISTORICAL_MULTITIMEFRAME_BASE_INTERVAL = "15m"
HISTORICAL_MULTITIMEFRAME_SUPPORTING_INTERVALS: tuple[str, ...] = ("1h", "4h")
HISTORICAL_MULTITIMEFRAME_ALIGNMENT_RULE = "base_close_time -> last_closed_supporting_candle_close_time <= base_close_time"


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalDataValidationError(f"{field_name} is required.")
    return value.strip()


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


def _dataset_from_dict(data: Mapping[str, Any]) -> HistoricalDataset:
    if not isinstance(data, Mapping):
        raise HistoricalDataValidationError("historical dataset payload must be a mapping.")
    mapping = dict(data)
    try:
        manifest = HistoricalDatasetManifest.from_dict(mapping["manifest"])
        candles = tuple(Candle.from_dict(item) for item in mapping["candles"])
    except KeyError as exc:
        raise HistoricalDataValidationError("historical dataset payload is incomplete.") from exc
    return HistoricalDataset(manifest=manifest, candles=candles)


def _dataset_family_signature(dataset: HistoricalDataset) -> dict[str, Any]:
    qualification = dataset.manifest.provider_qualification
    return {
        "provider": dataset.manifest.provider,
        "provider_id": qualification.provider_id,
        "provider_version": qualification.provider_version,
        "market_type": qualification.market_type,
        "exchange": qualification.exchange,
        "symbol": dataset.manifest.symbol,
        "time_semantics": qualification.time_semantics,
        "access_type": qualification.access_type,
        "external_symbol": qualification.external_symbol,
        "endpoint": dataset.manifest.endpoint,
        "documentation_url": qualification.documentation_url,
    }


def _dataset_descriptor(dataset: HistoricalDataset) -> dict[str, Any]:
    manifest = dataset.manifest
    qualification = manifest.provider_qualification
    return {
        "dataset": dataset.as_dict(),
        "family_signature": _dataset_family_signature(dataset),
        "manifest_hash": manifest.manifest_hash,
        "content_hash": manifest.content_hash,
        "provider_qualification_hash": qualification.qualification_hash,
    }


def _point_descriptor(point: "HistoricalMultiTimeframeAlignmentPoint") -> dict[str, Any]:
    return point.as_dict()


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeAlignmentPoint:
    interval: str
    candle: Candle
    dataset_id: str
    manifest_hash: str
    provider_qualification_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        if not isinstance(self.candle, Candle):
            raise HistoricalDataValidationError("candle must be a Candle instance.")
        object.__setattr__(self, "dataset_id", _require_str(self.dataset_id, "dataset_id"))
        object.__setattr__(self, "manifest_hash", _require_str(self.manifest_hash, "manifest_hash"))
        object.__setattr__(self, "provider_qualification_hash", _require_str(self.provider_qualification_hash, "provider_qualification_hash"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "interval": self.interval,
            "candle": self.candle.to_dict(),
            "dataset_id": self.dataset_id,
            "manifest_hash": self.manifest_hash,
            "provider_qualification_hash": self.provider_qualification_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeAlignmentPoint":
        if not isinstance(data, Mapping):
            raise HistoricalDataValidationError("alignment point must be a mapping.")
        mapping = dict(data)
        try:
            candle = Candle.from_dict(mapping["candle"])
            return cls(
                interval=mapping["interval"],
                candle=candle,
                dataset_id=mapping["dataset_id"],
                manifest_hash=mapping["manifest_hash"],
                provider_qualification_hash=mapping["provider_qualification_hash"],
            )
        except KeyError as exc:
            raise HistoricalDataValidationError("alignment point is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeBundle:
    base_dataset: HistoricalDataset
    supporting_datasets: tuple[HistoricalDataset, ...]
    alignment_rule: str = HISTORICAL_MULTITIMEFRAME_ALIGNMENT_RULE
    schema_version: int = HISTORICAL_MULTITIMEFRAME_SCHEMA_VERSION
    bundle_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.base_dataset, HistoricalDataset):
            raise HistoricalDataValidationError("base_dataset must be a HistoricalDataset instance.")
        if not isinstance(self.supporting_datasets, tuple):
            object.__setattr__(self, "supporting_datasets", tuple(self.supporting_datasets))
        if len(self.supporting_datasets) != len(HISTORICAL_MULTITIMEFRAME_SUPPORTING_INTERVALS):
            raise HistoricalDataValidationError("supporting_datasets must contain 1h and 4h datasets.")
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_SCHEMA_VERSION:
            raise HistoricalDataValidationError("schema_version must be 1.")
        object.__setattr__(self, "alignment_rule", _require_str(self.alignment_rule, "alignment_rule"))
        support_by_interval = {dataset.manifest.interval: dataset for dataset in self.supporting_datasets}
        expected_intervals = set(HISTORICAL_MULTITIMEFRAME_SUPPORTING_INTERVALS)
        if set(support_by_interval) != expected_intervals:
            raise HistoricalDataValidationError("supporting_datasets must contain 1h and 4h intervals.")
        if self.base_dataset.manifest.interval != HISTORICAL_MULTITIMEFRAME_BASE_INTERVAL:
            raise HistoricalDataValidationError("base_dataset must use 15m interval.")
        canonical_supporting = tuple(support_by_interval[interval] for interval in HISTORICAL_MULTITIMEFRAME_SUPPORTING_INTERVALS)
        object.__setattr__(self, "supporting_datasets", canonical_supporting)
        datasets = (self.base_dataset,) + canonical_supporting
        if any(dataset.manifest.symbol != self.base_dataset.manifest.symbol for dataset in datasets):
            raise HistoricalDataValidationError("multi-timeframe datasets must share the same symbol.")
        if any(dataset.manifest.provider != self.base_dataset.manifest.provider for dataset in datasets):
            raise HistoricalDataValidationError("multi-timeframe datasets must share the same provider.")
        if any(dataset.manifest.provider_qualification.provider_id != self.base_dataset.manifest.provider_qualification.provider_id for dataset in datasets):
            raise HistoricalDataValidationError("multi-timeframe datasets must share the same provider qualification identity.")
        if any(_dataset_family_signature(dataset) != _dataset_family_signature(self.base_dataset) for dataset in canonical_supporting):
            raise HistoricalDataValidationError("multi-timeframe datasets must share the same provider family provenance.")
        if any(dataset.manifest.provider_qualification.market_type != "spot" for dataset in datasets):
            raise HistoricalDataValidationError("multi-timeframe datasets must remain spot market datasets.")
        if any(dataset.manifest.provider_qualification.exchange != "kucoin" for dataset in datasets):
            raise HistoricalDataValidationError("multi-timeframe datasets must remain KuCoin datasets.")
        if self.bundle_hash:
            object.__setattr__(self, "bundle_hash", _require_str(self.bundle_hash, "bundle_hash"))
            if self.bundle_hash != _hash_payload(self.as_hash_payload(include_hash=False)):
                raise HistoricalDataValidationError("bundle_hash mismatch.")
        else:
            object.__setattr__(self, "bundle_hash", _hash_payload(self.as_hash_payload(include_hash=False)))

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "alignment_rule": self.alignment_rule,
            "base_dataset": _dataset_descriptor(self.base_dataset),
            "supporting_datasets": [_dataset_descriptor(dataset) for dataset in self.supporting_datasets],
        }
        if include_hash:
            payload["bundle_hash"] = self.bundle_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeBundle":
        if not isinstance(data, Mapping):
            raise HistoricalDataValidationError("historical multi-timeframe bundle must be a mapping.")
        mapping = dict(data)
        try:
            return cls(
                base_dataset=_dataset_from_dict(mapping["base_dataset"]["dataset"]),
                supporting_datasets=tuple(_dataset_from_dict(item["dataset"]) for item in mapping["supporting_datasets"]),
                alignment_rule=mapping["alignment_rule"],
                schema_version=mapping["schema_version"],
                bundle_hash=mapping.get("bundle_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalDataValidationError("historical multi-timeframe bundle is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalMultiTimeframeSnapshot:
    decision_time_utc: datetime
    base_point: HistoricalMultiTimeframeAlignmentPoint
    supporting_points: tuple[HistoricalMultiTimeframeAlignmentPoint, ...]
    bundle_hash: str
    schema_version: int = HISTORICAL_MULTITIMEFRAME_SCHEMA_VERSION
    alignment_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_time_utc", _require_utc_datetime(self.decision_time_utc, "decision_time_utc"))
        if not isinstance(self.base_point, HistoricalMultiTimeframeAlignmentPoint):
            raise HistoricalDataValidationError("base_point must be an alignment point.")
        if not isinstance(self.supporting_points, tuple):
            object.__setattr__(self, "supporting_points", tuple(self.supporting_points))
        if len(self.supporting_points) != len(HISTORICAL_MULTITIMEFRAME_SUPPORTING_INTERVALS):
            raise HistoricalDataValidationError("supporting_points must contain 1h and 4h points.")
        object.__setattr__(self, "bundle_hash", _require_str(self.bundle_hash, "bundle_hash"))
        if self.schema_version != HISTORICAL_MULTITIMEFRAME_SCHEMA_VERSION:
            raise HistoricalDataValidationError("schema_version must be 1.")
        if self.base_point.interval != HISTORICAL_MULTITIMEFRAME_BASE_INTERVAL:
            raise HistoricalDataValidationError("base_point must use the 15m interval.")
        support_by_interval = {point.interval: point for point in self.supporting_points}
        if set(support_by_interval) != set(HISTORICAL_MULTITIMEFRAME_SUPPORTING_INTERVALS):
            raise HistoricalDataValidationError("supporting_points must contain 1h and 4h points.")
        canonical_supporting = tuple(support_by_interval[interval] for interval in HISTORICAL_MULTITIMEFRAME_SUPPORTING_INTERVALS)
        object.__setattr__(self, "supporting_points", canonical_supporting)
        if self.base_point.candle.close_time != self.decision_time_utc:
            raise HistoricalDataValidationError("base point close time must match the decision time.")
        if any(point.candle.close_time > self.decision_time_utc for point in canonical_supporting):
            raise HistoricalDataValidationError("supporting points must already be closed at the decision time.")
        if self.alignment_hash:
            object.__setattr__(self, "alignment_hash", _require_str(self.alignment_hash, "alignment_hash"))
            if self.alignment_hash != _hash_payload(self.as_hash_payload(include_hash=False, include_bundle_hash=False)):
                raise HistoricalDataValidationError("alignment_hash mismatch.")
        else:
            object.__setattr__(self, "alignment_hash", _hash_payload(self.as_hash_payload(include_hash=False, include_bundle_hash=False)))

    def as_hash_payload(self, *, include_hash: bool = True, include_bundle_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "decision_time_utc": _utc_iso(self.decision_time_utc),
            "base_point": _point_descriptor(self.base_point),
            "supporting_points": [_point_descriptor(point) for point in self.supporting_points],
        }
        if include_bundle_hash:
            payload["bundle_hash"] = self.bundle_hash
        if include_hash:
            payload["alignment_hash"] = self.alignment_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalMultiTimeframeSnapshot":
        if not isinstance(data, Mapping):
            raise HistoricalDataValidationError("historical multi-timeframe snapshot must be a mapping.")
        mapping = dict(data)
        try:
            return cls(
                decision_time_utc=mapping["decision_time_utc"],
                base_point=HistoricalMultiTimeframeAlignmentPoint.from_dict(mapping["base_point"]),
                supporting_points=tuple(HistoricalMultiTimeframeAlignmentPoint.from_dict(item) for item in mapping["supporting_points"]),
                bundle_hash=mapping["bundle_hash"],
                schema_version=mapping["schema_version"],
                alignment_hash=mapping.get("alignment_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalDataValidationError("historical multi-timeframe snapshot is incomplete.") from exc


def build_historical_multitimeframe_bundle(
    base_dataset: HistoricalDataset,
    one_hour_dataset: HistoricalDataset,
    four_hour_dataset: HistoricalDataset,
) -> HistoricalMultiTimeframeBundle:
    return HistoricalMultiTimeframeBundle(
        base_dataset=base_dataset,
        supporting_datasets=(one_hour_dataset, four_hour_dataset),
    )


def _point_from_dataset_and_candle(dataset: HistoricalDataset, candle: Candle) -> HistoricalMultiTimeframeAlignmentPoint:
    return HistoricalMultiTimeframeAlignmentPoint(
        interval=dataset.manifest.interval,
        candle=candle,
        dataset_id=dataset.manifest.dataset_id,
        manifest_hash=dataset.manifest.manifest_hash,
        provider_qualification_hash=dataset.manifest.provider_qualification.qualification_hash,
    )


def _select_last_closed_candle(dataset: HistoricalDataset, decision_time_utc: datetime) -> Candle:
    close_times = [candle.close_time for candle in dataset.candles]
    index = bisect_right(close_times, decision_time_utc) - 1
    if index < 0:
        raise HistoricalDataValidationError("higher timeframe candle is not yet closed at the requested decision time.")
    candle = dataset.candles[index]
    if candle.close_time > decision_time_utc:
        raise HistoricalDataValidationError("higher timeframe candle must be closed before or at the decision time.")
    return candle


def align_historical_multitimeframe_snapshot(
    bundle: HistoricalMultiTimeframeBundle,
    *,
    base_candle: Candle,
) -> HistoricalMultiTimeframeSnapshot:
    if not isinstance(bundle, HistoricalMultiTimeframeBundle):
        raise HistoricalDataValidationError("bundle must be a HistoricalMultiTimeframeBundle instance.")
    if base_candle not in bundle.base_dataset.candles:
        raise HistoricalDataValidationError("base candle must belong to the base 15m dataset.")
    if base_candle.symbol != bundle.base_dataset.manifest.symbol:
        raise HistoricalDataValidationError("base candle symbol diverges from bundle symbol.")
    if base_candle.interval != bundle.base_dataset.manifest.interval:
        raise HistoricalDataValidationError("base candle interval diverges from bundle interval.")
    if base_candle.source != bundle.base_dataset.candles[0].source:
        raise HistoricalDataValidationError("base candle source diverges from bundle source.")

    decision_time_utc = base_candle.close_time.astimezone(timezone.utc)
    base_point = _point_from_dataset_and_candle(bundle.base_dataset, base_candle)
    supporting_points = tuple(
        _point_from_dataset_and_candle(dataset, _select_last_closed_candle(dataset, decision_time_utc))
        for dataset in bundle.supporting_datasets
    )
    return HistoricalMultiTimeframeSnapshot(
        decision_time_utc=decision_time_utc,
        base_point=base_point,
        supporting_points=supporting_points,
        bundle_hash=bundle.bundle_hash,
    )


def align_historical_multitimeframe_series(
    bundle: HistoricalMultiTimeframeBundle,
) -> tuple[HistoricalMultiTimeframeSnapshot, ...]:
    if not isinstance(bundle, HistoricalMultiTimeframeBundle):
        raise HistoricalDataValidationError("bundle must be a HistoricalMultiTimeframeBundle instance.")
    snapshots: list[HistoricalMultiTimeframeSnapshot] = []
    supporting_close_times = {
        dataset.manifest.interval: [candle.close_time for candle in dataset.candles]
        for dataset in bundle.supporting_datasets
    }
    supporting_indices = {dataset.manifest.interval: -1 for dataset in bundle.supporting_datasets}
    for base_candle in bundle.base_dataset.candles:
        decision_time_utc = base_candle.close_time.astimezone(timezone.utc)
        supporting_points: list[HistoricalMultiTimeframeAlignmentPoint] = []
        for dataset in bundle.supporting_datasets:
            interval = dataset.manifest.interval
            close_times = supporting_close_times[interval]
            index = supporting_indices[interval]
            while index + 1 < len(close_times) and close_times[index + 1] <= decision_time_utc:
                index += 1
            if index < 0:
                raise HistoricalDataValidationError("higher timeframe candle is not yet closed at the requested decision time.")
            supporting_indices[interval] = index
            supporting_points.append(_point_from_dataset_and_candle(dataset, dataset.candles[index]))
        snapshots.append(
            HistoricalMultiTimeframeSnapshot(
                decision_time_utc=decision_time_utc,
                base_point=_point_from_dataset_and_candle(bundle.base_dataset, base_candle),
                supporting_points=tuple(supporting_points),
                bundle_hash=bundle.bundle_hash,
            )
        )
    return tuple(snapshots)


__all__ = [
    "HISTORICAL_MULTITIMEFRAME_ALIGNMENT_RULE",
    "HISTORICAL_MULTITIMEFRAME_BASE_INTERVAL",
    "HISTORICAL_MULTITIMEFRAME_SCHEMA_VERSION",
    "HISTORICAL_MULTITIMEFRAME_SUPPORTING_INTERVALS",
    "HistoricalMultiTimeframeAlignmentPoint",
    "HistoricalMultiTimeframeBundle",
    "HistoricalMultiTimeframeSnapshot",
    "align_historical_multitimeframe_series",
    "align_historical_multitimeframe_snapshot",
    "build_historical_multitimeframe_bundle",
]
