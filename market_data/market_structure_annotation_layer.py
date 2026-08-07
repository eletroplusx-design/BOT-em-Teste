from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value

from . import offline_market_structure_detector as phase51
from .errors import HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError

MARKET_STRUCTURE_ANNOTATION_SCHEMA_VERSION = 1
MARKET_STRUCTURE_ANNOTATION_ID = "market_structure_annotation"
MARKET_STRUCTURE_ANNOTATION_VERSION = "phase52_market_structure_annotation_layer_v1"
MARKET_STRUCTURE_ANNOTATION_COLLECTION_SCHEMA_VERSION = 1
MARKET_STRUCTURE_ANNOTATION_COLLECTION_ID = "market_structure_annotation_collection"
MARKET_STRUCTURE_ANNOTATION_COLLECTION_VERSION = "phase52_market_structure_annotation_collection_v1"

MARKET_STRUCTURE_ANNOTATION_ALLOWED_STRUCTURE_STATES = (
    "bullish",
    "bearish",
    "lateral",
    "ambiguous",
    "indeterminate",
)
MARKET_STRUCTURE_ANNOTATION_ALLOWED_ANNOTATION_STATES = (
    "none",
    "ambiguous",
    "indeterminate",
)
MARKET_STRUCTURE_ANNOTATION_ALLOWED_INVALIDATION_STATES = (
    "none",
    "invalidated",
    "indeterminate",
)
MARKET_STRUCTURE_ANNOTATION_ALLOWED_HYPOTHESIS_STATES = (
    "Bullish Continuation",
    "Bearish Continuation",
    "Accumulation Candidate",
    "Distribution Candidate",
    "Reaccumulation Candidate",
    "Redistribution Candidate",
    "Unknown",
)
MARKET_STRUCTURE_ANNOTATION_ALLOWED_EVENT_KINDS = {
    "confirmed_swing_high",
    "confirmed_swing_low",
    "candidate_swing_high",
    "candidate_swing_low",
    "ambiguous_swing_high",
    "ambiguous_swing_low",
    "bullish_structure",
    "bearish_structure",
    "lateral_structure",
    "ambiguous_structure",
    "indeterminate_structure",
    "equal_highs",
    "equal_lows",
    "internal_liquidity",
    "external_liquidity",
    "protected_high",
    "protected_low",
    "liquidity_sweep",
    "false_break",
    "breakout",
    "valid_bos",
    "failed_bos",
    "valid_choch",
    "failed_choch",
    "valid_retest",
    "failed_retest",
    "valid_displacement",
    "insufficient_displacement",
    "valid_trading_range",
    "unclassified_range",
    "candidate_accumulation",
    "candidate_distribution",
    "candidate_reaccumulation",
    "candidate_redistribution",
}
MARKET_STRUCTURE_ANNOTATION_PAYLOAD_KEYS = {
    "timeframe",
    "candle_index",
    "macro_context",
    "intermediate_context",
    "micro_context",
    "final_structure_state",
    "ambiguity_state",
    "invalidation_state",
    "hypothesis_state",
    "event_count",
    "event_kinds",
    "bullish_structure",
    "bearish_structure",
    "lateral_structure",
    "trading_range",
    "swing_high",
    "swing_low",
    "protected_high",
    "protected_low",
    "liquidity_pool",
    "liquidity_sweep",
    "breakout",
    "failed_breakout",
    "bos",
    "choch",
    "displacement",
    "retest",
    "ambiguous",
    "indeterminate",
}


class MarketStructureAnnotationError(HistoricalDataError):
    pass


class MarketStructureAnnotationValidationError(
    MarketStructureAnnotationError,
    HistoricalDataValidationError,
):
    pass


class MarketStructureAnnotationIntegrityError(
    MarketStructureAnnotationError,
    HistoricalDataIntegrityError,
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        serialize_value(_thaw_read_only_value(payload)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash_payload(payload: Any) -> str:
    try:
        return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    except (TypeError, ValueError) as exc:
        raise MarketStructureAnnotationValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketStructureAnnotationValidationError(f"{field_name} is required.")
    return value.strip()


def _require_exact_keys(mapping: Mapping[str, Any], field_name: str, expected_keys: set[str]) -> None:
    extra = sorted(set(mapping) - expected_keys)
    missing = sorted(expected_keys - set(mapping))
    if extra or missing:
        parts: list[str] = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected {', '.join(extra)}")
        raise MarketStructureAnnotationValidationError(
            f"{field_name} has invalid fields: {'; '.join(parts)}."
        )


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise MarketStructureAnnotationValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise MarketStructureAnnotationValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise MarketStructureAnnotationValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise MarketStructureAnnotationValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise MarketStructureAnnotationValidationError(f"{field_name} must be a 64-character hex digest.")
    return digest


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise MarketStructureAnnotationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise MarketStructureAnnotationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise MarketStructureAnnotationValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketStructureAnnotationValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _freeze_read_only_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_read_only_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_read_only_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_read_only_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_read_only_value(item) for item in value)
    if isinstance(value, frozenset):
        return frozenset(_freeze_read_only_value(item) for item in value)
    return value


def _thaw_read_only_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_read_only_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_thaw_read_only_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_thaw_read_only_value(item) for item in value)
    if isinstance(value, set) or isinstance(value, frozenset):
        thawed_items = [_thaw_read_only_value(item) for item in value]
        return tuple(sorted(thawed_items, key=_canonical_json))
    return value


def _parse_timeframe_delta(timeframe: str) -> timedelta:
    normalized = _require_str(timeframe, "timeframe").upper()
    match = re.fullmatch(r"(?P<count>\d+)(?P<unit>[MHDW])", normalized)
    if not match:
        raise MarketStructureAnnotationValidationError("timeframe must use a supported interval like 1H or 1D.")
    count = int(match.group("count"))
    unit = match.group("unit")
    if unit == "M":
        return timedelta(minutes=count)
    if unit == "H":
        return timedelta(hours=count)
    if unit == "D":
        return timedelta(days=count)
    return timedelta(weeks=count)


def _derive_candle_timestamps(
    detection_result: phase51.MarketStructureDetectionResult,
) -> tuple[datetime, ...]:
    if detection_result.candle_count <= 0:
        raise MarketStructureAnnotationValidationError("detection_result must contain at least one candle.")
    step = _parse_timeframe_delta(detection_result.timeframe)
    timestamps = tuple(detection_result.first_timestamp + index * step for index in range(detection_result.candle_count))
    if timestamps[-1] != detection_result.last_timestamp:
        raise MarketStructureAnnotationValidationError(
            "detection_result timestamps are inconsistent with the declared timeframe."
        )
    return timestamps


def _annotation_event_kinds(
    detection_result: phase51.MarketStructureDetectionResult,
    *,
    candle_index: int,
    candle_timestamp: datetime,
    candle_timestamps: tuple[datetime, ...],
) -> tuple[str, ...]:
    if candle_index < 0 or candle_index >= len(candle_timestamps):
        raise MarketStructureAnnotationValidationError("candle_index is out of range.")
    if candle_timestamps[candle_index] != candle_timestamp:
        raise MarketStructureAnnotationValidationError("candle_timestamp does not match the detected candle index.")

    event_kinds: list[str] = []
    for event in detection_result.events:
        if event.candle_index < 0 or event.candle_index >= len(candle_timestamps):
            raise MarketStructureAnnotationValidationError("event candle index is out of range.")
        if event.timestamp != candle_timestamps[event.candle_index]:
            raise MarketStructureAnnotationValidationError("event timestamp is inconsistent with the detected series.")
        if event.candle_index == candle_index:
            event_kinds.append(event.kind)
    return tuple(event_kinds)


def _annotation_hypothesis_state(result: phase51.MarketStructureDetectionResult, event_kinds: Sequence[str]) -> str:
    if "candidate_distribution" in event_kinds:
        return "Distribution Candidate"
    if "candidate_accumulation" in event_kinds:
        return "Accumulation Candidate"
    if "candidate_reaccumulation" in event_kinds:
        return "Reaccumulation Candidate"
    if "candidate_redistribution" in event_kinds:
        return "Redistribution Candidate"
    if result.final_structure_state == "bullish":
        return "Bullish Continuation"
    if result.final_structure_state == "bearish":
        return "Bearish Continuation"
    return "Unknown"


def _annotation_payload_from_result(
    result: phase51.MarketStructureDetectionResult,
    *,
    candle_index: int,
    candle_timestamp: datetime,
    event_kinds: Sequence[str],
) -> Mapping[str, Any]:
    event_kind_set = set(event_kinds)
    annotation_payload = {
        "timeframe": result.timeframe,
        "candle_index": candle_index,
        "macro_context": result.macro_context,
        "intermediate_context": result.intermediate_context,
        "micro_context": result.micro_context,
        "final_structure_state": result.final_structure_state,
        "ambiguity_state": result.ambiguity_state,
        "invalidation_state": result.invalidation_state,
        "hypothesis_state": _annotation_hypothesis_state(result, event_kinds),
        "event_count": len(event_kinds),
        "event_kinds": tuple(event_kinds),
        "bullish_structure": result.final_structure_state == "bullish",
        "bearish_structure": result.final_structure_state == "bearish",
        "lateral_structure": result.final_structure_state == "lateral",
        "trading_range": any(
            kind in {
                "valid_trading_range",
                "unclassified_range",
                "candidate_accumulation",
                "candidate_distribution",
                "candidate_reaccumulation",
                "candidate_redistribution",
            }
            for kind in event_kinds
        ),
        "swing_high": any(kind.endswith("swing_high") for kind in event_kinds),
        "swing_low": any(kind.endswith("swing_low") for kind in event_kinds),
        "protected_high": "protected_high" in event_kind_set,
        "protected_low": "protected_low" in event_kind_set,
        "liquidity_pool": any(
            kind in {"equal_highs", "equal_lows", "internal_liquidity", "external_liquidity"}
            for kind in event_kinds
        ),
        "liquidity_sweep": "liquidity_sweep" in event_kind_set,
        "breakout": "breakout" in event_kind_set,
        "failed_breakout": "false_break" in event_kind_set,
        "bos": any(kind in {"valid_bos", "failed_bos"} for kind in event_kinds),
        "choch": any(kind in {"valid_choch", "failed_choch"} for kind in event_kinds),
        "displacement": any(kind in {"valid_displacement", "insufficient_displacement"} for kind in event_kinds),
        "retest": any(kind in {"valid_retest", "failed_retest"} for kind in event_kinds),
        "ambiguous": result.ambiguity_state == "ambiguous" or any("ambiguous" in kind for kind in event_kinds),
        "indeterminate": result.final_structure_state == "indeterminate"
        or result.ambiguity_state == "indeterminate"
        or any(kind.startswith("unclassified_") for kind in event_kinds),
    }
    return _validate_annotation_payload(annotation_payload, field_name="annotation_payload")


def _require_str_sequence(value: Any, field_name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise MarketStructureAnnotationValidationError(f"{field_name} must be a sequence of strings.")
    normalized = tuple(_require_str(item, field_name) for item in value)
    if not allow_empty and not normalized:
        raise MarketStructureAnnotationValidationError(f"{field_name} must not be empty.")
    return normalized


def _validate_annotation_payload(
    payload: Mapping[str, Any],
    *,
    field_name: str,
) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise MarketStructureAnnotationValidationError(f"{field_name} must be a mapping.")
    _require_exact_keys(payload, field_name, MARKET_STRUCTURE_ANNOTATION_PAYLOAD_KEYS)
    timeframe = _require_str(payload["timeframe"], f"{field_name}.timeframe").upper()
    _parse_timeframe_delta(timeframe)
    candle_index = _require_int(payload["candle_index"], f"{field_name}.candle_index", allow_zero=True)
    macro_context = _require_str(payload["macro_context"], f"{field_name}.macro_context").lower()
    intermediate_context = _require_str(payload["intermediate_context"], f"{field_name}.intermediate_context").lower()
    micro_context = _require_str(payload["micro_context"], f"{field_name}.micro_context").lower()
    final_structure_state = _require_str(payload["final_structure_state"], f"{field_name}.final_structure_state").lower()
    ambiguity_state = _require_str(payload["ambiguity_state"], f"{field_name}.ambiguity_state").lower()
    invalidation_state = _require_str(payload["invalidation_state"], f"{field_name}.invalidation_state").lower()
    hypothesis_state = _require_str(payload["hypothesis_state"], f"{field_name}.hypothesis_state")
    event_count = _require_int(payload["event_count"], f"{field_name}.event_count", allow_zero=True)
    event_kinds = _require_str_sequence(payload["event_kinds"], f"{field_name}.event_kinds", allow_empty=True)

    if final_structure_state not in MARKET_STRUCTURE_ANNOTATION_ALLOWED_STRUCTURE_STATES:
        raise MarketStructureAnnotationValidationError(f"{field_name}.final_structure_state is invalid.")
    for context_name, context_value in (
        ("macro_context", macro_context),
        ("intermediate_context", intermediate_context),
        ("micro_context", micro_context),
    ):
        if context_value not in MARKET_STRUCTURE_ANNOTATION_ALLOWED_STRUCTURE_STATES:
            raise MarketStructureAnnotationValidationError(f"{field_name}.{context_name} is invalid.")
    if ambiguity_state not in MARKET_STRUCTURE_ANNOTATION_ALLOWED_ANNOTATION_STATES:
        raise MarketStructureAnnotationValidationError(f"{field_name}.ambiguity_state is invalid.")
    if invalidation_state not in MARKET_STRUCTURE_ANNOTATION_ALLOWED_INVALIDATION_STATES:
        raise MarketStructureAnnotationValidationError(f"{field_name}.invalidation_state is invalid.")
    if hypothesis_state not in MARKET_STRUCTURE_ANNOTATION_ALLOWED_HYPOTHESIS_STATES:
        raise MarketStructureAnnotationValidationError(f"{field_name}.hypothesis_state is invalid.")
    if event_count != len(event_kinds):
        raise MarketStructureAnnotationValidationError(f"{field_name}.event_count does not match event_kinds.")
    unknown_events = sorted(set(event_kinds) - MARKET_STRUCTURE_ANNOTATION_ALLOWED_EVENT_KINDS)
    if unknown_events:
        raise MarketStructureAnnotationValidationError(
            f"{field_name}.event_kinds contains unknown event(s): {', '.join(unknown_events)}."
        )

    derived_flags = {
        "bullish_structure": final_structure_state == "bullish",
        "bearish_structure": final_structure_state == "bearish",
        "lateral_structure": final_structure_state == "lateral",
        "trading_range": any(
            kind in {
                "valid_trading_range",
                "unclassified_range",
                "candidate_accumulation",
                "candidate_distribution",
                "candidate_reaccumulation",
                "candidate_redistribution",
            }
            for kind in event_kinds
        ),
        "swing_high": any(kind.endswith("swing_high") for kind in event_kinds),
        "swing_low": any(kind.endswith("swing_low") for kind in event_kinds),
        "protected_high": "protected_high" in event_kinds,
        "protected_low": "protected_low" in event_kinds,
        "liquidity_pool": any(
            kind in {"equal_highs", "equal_lows", "internal_liquidity", "external_liquidity"}
            for kind in event_kinds
        ),
        "liquidity_sweep": "liquidity_sweep" in event_kinds,
        "breakout": "breakout" in event_kinds,
        "failed_breakout": "false_break" in event_kinds,
        "bos": any(kind in {"valid_bos", "failed_bos"} for kind in event_kinds),
        "choch": any(kind in {"valid_choch", "failed_choch"} for kind in event_kinds),
        "displacement": any(kind in {"valid_displacement", "insufficient_displacement"} for kind in event_kinds),
        "retest": any(kind in {"valid_retest", "failed_retest"} for kind in event_kinds),
        "ambiguous": ambiguity_state == "ambiguous" or any("ambiguous" in kind for kind in event_kinds),
        "indeterminate": final_structure_state == "indeterminate"
        or ambiguity_state == "indeterminate"
        or any(kind.startswith("unclassified_") for kind in event_kinds),
    }
    for flag_name, expected in derived_flags.items():
        if _require_bool(payload[flag_name], f"{field_name}.{flag_name}") is not expected:
            raise MarketStructureAnnotationValidationError(f"{field_name}.{flag_name} is inconsistent.")

    normalized = {
        "timeframe": timeframe,
        "candle_index": candle_index,
        "macro_context": macro_context,
        "intermediate_context": intermediate_context,
        "micro_context": micro_context,
        "final_structure_state": final_structure_state,
        "ambiguity_state": ambiguity_state,
        "invalidation_state": invalidation_state,
        "hypothesis_state": hypothesis_state,
        "event_count": event_count,
        "event_kinds": tuple(event_kinds),
        **derived_flags,
    }
    return _freeze_read_only_value(normalized)


def _derive_collection_order(
    annotations: Sequence["MarketStructureAnnotation"],
) -> tuple["MarketStructureAnnotation", ...]:
    ordered = tuple(sorted(annotations, key=lambda annotation: (_utc_iso(annotation.candle_timestamp), annotation.annotation_id)))
    candle_indices = [annotation.annotation_payload["candle_index"] for annotation in ordered]
    if candle_indices != list(range(len(ordered))):
        raise MarketStructureAnnotationValidationError(
            "annotations must be a contiguous zero-based sequence matching candle order."
        )
    timestamps = [annotation.candle_timestamp for annotation in ordered]
    if len(set(timestamps)) != len(timestamps):
        raise MarketStructureAnnotationValidationError("annotations must not contain duplicate candle timestamps.")
    timeframes = {annotation.annotation_payload["timeframe"] for annotation in ordered}
    if len(timeframes) != 1:
        raise MarketStructureAnnotationValidationError("annotations must share the same timeframe.")
    step = _parse_timeframe_delta(next(iter(timeframes)))
    for index, annotation in enumerate(ordered):
        expected_timestamp = ordered[0].candle_timestamp + index * step
        if annotation.candle_timestamp != expected_timestamp:
            raise MarketStructureAnnotationValidationError(
                "annotations must follow a contiguous candle timeline."
            )
    return ordered


def _build_collection_payload(
    collection: "MarketStructureAnnotationCollection",
    *,
    include_collection_id: bool = True,
    include_collection_hash: bool = True,
) -> dict[str, Any]:
    payload = {
        "schema_version": collection.schema_version,
        "dataset_hash": collection.dataset_hash,
        "contract_hash": collection.contract_hash,
        "detection_result_hash": collection.detection_result_hash,
        "first_candle_timestamp": _utc_iso(collection.first_candle_timestamp),
        "last_candle_timestamp": _utc_iso(collection.last_candle_timestamp),
        "annotation_count": len(collection.annotations),
        "annotations": [annotation.canonical_payload() for annotation in collection.annotations],
        "created_at_utc": _utc_iso(collection.created_at_utc),
        "metadata": _thaw_read_only_value(collection.metadata),
    }
    if include_collection_id:
        payload["collection_id"] = collection.collection_id
    if include_collection_hash:
        payload["collection_hash"] = collection.collection_hash
    return payload


@dataclass(frozen=True, slots=True)
class MarketStructureAnnotation:
    schema_version: int
    annotation_id: str = ""
    annotation_hash: str = ""
    dataset_hash: str = ""
    contract_hash: str = ""
    detection_result_hash: str = ""
    candle_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    annotation_payload: Mapping[str, Any] = field(default_factory=dict, repr=False)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "annotation_id", _require_hex_digest(self.annotation_id, "annotation_id") if self.annotation_id else "")
        object.__setattr__(self, "annotation_hash", _require_hex_digest(self.annotation_hash, "annotation_hash") if self.annotation_hash else "")
        object.__setattr__(self, "dataset_hash", _require_hex_digest(self.dataset_hash, "dataset_hash"))
        object.__setattr__(self, "contract_hash", _require_hex_digest(self.contract_hash, "contract_hash"))
        object.__setattr__(self, "detection_result_hash", _require_hex_digest(self.detection_result_hash, "detection_result_hash"))
        object.__setattr__(self, "candle_timestamp", _require_utc_datetime(self.candle_timestamp, "candle_timestamp"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        if not isinstance(self.metadata, Mapping):
            raise MarketStructureAnnotationValidationError("metadata must be a mapping.")
        if not isinstance(self.annotation_payload, Mapping):
            raise MarketStructureAnnotationValidationError("annotation_payload must be a mapping.")
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))
        object.__setattr__(
            self,
            "annotation_payload",
            _validate_annotation_payload(self.annotation_payload, field_name="annotation_payload"),
        )

        expected_id = _hash_payload(self._annotation_id_payload())
        if self.annotation_id:
            if self.annotation_id != expected_id:
                raise MarketStructureAnnotationIntegrityError("annotation_id mismatch.")
        else:
            object.__setattr__(self, "annotation_id", expected_id)

        expected_hash = _hash_payload(self._annotation_hash_payload())
        if self.annotation_hash:
            if self.annotation_hash != expected_hash:
                raise MarketStructureAnnotationIntegrityError("annotation_hash mismatch.")
        else:
            object.__setattr__(self, "annotation_hash", expected_hash)

    def _annotation_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dataset_hash": self.dataset_hash,
            "contract_hash": self.contract_hash,
            "detection_result_hash": self.detection_result_hash,
            "candle_timestamp": _utc_iso(self.candle_timestamp),
            "annotation_payload": _thaw_read_only_value(self.annotation_payload),
            "metadata": _thaw_read_only_value(self.metadata),
        }

    def _annotation_hash_payload(self) -> dict[str, Any]:
        payload = self._annotation_id_payload()
        payload["annotation_id"] = self.annotation_id
        return payload

    def canonical_payload(
        self,
        *,
        include_annotation_id: bool = True,
        include_annotation_hash: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "dataset_hash": self.dataset_hash,
            "contract_hash": self.contract_hash,
            "detection_result_hash": self.detection_result_hash,
            "candle_timestamp": _utc_iso(self.candle_timestamp),
            "annotation_payload": _thaw_read_only_value(self.annotation_payload),
            "created_at_utc": _utc_iso(self.created_at_utc),
            "metadata": _thaw_read_only_value(self.metadata),
        }
        if include_annotation_id:
            payload["annotation_id"] = self.annotation_id
        if include_annotation_hash:
            payload["annotation_hash"] = self.annotation_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_annotation_id=True, include_annotation_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureAnnotation":
        if not isinstance(data, Mapping):
            raise MarketStructureAnnotationValidationError("market structure annotation must be a mapping.")
        _require_exact_keys(
            data,
            "market structure annotation",
            {
                "schema_version",
                "annotation_id",
                "annotation_hash",
                "dataset_hash",
                "contract_hash",
                "detection_result_hash",
                "candle_timestamp",
                "annotation_payload",
                "created_at_utc",
                "metadata",
            },
        )
        try:
            return cls(
                schema_version=data["schema_version"],
                annotation_id=data.get("annotation_id", ""),
                annotation_hash=data.get("annotation_hash", ""),
                dataset_hash=data["dataset_hash"],
                contract_hash=data["contract_hash"],
                detection_result_hash=data["detection_result_hash"],
                candle_timestamp=data["candle_timestamp"],
                annotation_payload=data["annotation_payload"],
                created_at_utc=data["created_at_utc"],
                metadata=data.get("metadata", {}),
            )
        except KeyError as exc:
            raise MarketStructureAnnotationValidationError("market structure annotation is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class MarketStructureAnnotationCollection:
    schema_version: int
    collection_id: str = ""
    collection_hash: str = ""
    dataset_hash: str = ""
    contract_hash: str = ""
    detection_result_hash: str = ""
    annotation_count: int = 0
    first_candle_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_candle_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    annotations: tuple[MarketStructureAnnotation, ...] = field(default_factory=tuple, repr=False)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "collection_id", _require_hex_digest(self.collection_id, "collection_id") if self.collection_id else "")
        object.__setattr__(self, "collection_hash", _require_hex_digest(self.collection_hash, "collection_hash") if self.collection_hash else "")
        object.__setattr__(self, "dataset_hash", _require_hex_digest(self.dataset_hash, "dataset_hash"))
        object.__setattr__(self, "contract_hash", _require_hex_digest(self.contract_hash, "contract_hash"))
        object.__setattr__(self, "detection_result_hash", _require_hex_digest(self.detection_result_hash, "detection_result_hash"))
        object.__setattr__(self, "annotation_count", _require_int(self.annotation_count, "annotation_count", allow_zero=True))
        object.__setattr__(self, "first_candle_timestamp", _require_utc_datetime(self.first_candle_timestamp, "first_candle_timestamp"))
        object.__setattr__(self, "last_candle_timestamp", _require_utc_datetime(self.last_candle_timestamp, "last_candle_timestamp"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        if not isinstance(self.metadata, Mapping):
            raise MarketStructureAnnotationValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))

        normalized_annotations: list[MarketStructureAnnotation] = []
        for annotation in self.annotations:
            if isinstance(annotation, MarketStructureAnnotation):
                normalized_annotations.append(annotation)
            elif isinstance(annotation, Mapping):
                normalized_annotations.append(MarketStructureAnnotation.from_dict(annotation))
            else:
                raise MarketStructureAnnotationValidationError("annotations must contain market structure annotations.")
        if not normalized_annotations:
            raise MarketStructureAnnotationValidationError("annotations must not be empty.")
        ordered_annotations = _derive_collection_order(tuple(normalized_annotations))
        object.__setattr__(self, "annotations", ordered_annotations)
        if self.annotation_count not in (0, len(ordered_annotations)):
            raise MarketStructureAnnotationValidationError("annotation_count is inconsistent with annotations.")
        object.__setattr__(self, "annotation_count", len(ordered_annotations))

        if ordered_annotations[0].candle_timestamp != self.first_candle_timestamp:
            raise MarketStructureAnnotationValidationError("first_candle_timestamp is inconsistent with annotations.")
        if ordered_annotations[-1].candle_timestamp != self.last_candle_timestamp:
            raise MarketStructureAnnotationValidationError("last_candle_timestamp is inconsistent with annotations.")
        for annotation in ordered_annotations:
            if annotation.dataset_hash != self.dataset_hash:
                raise MarketStructureAnnotationValidationError("annotation dataset_hash mismatch.")
            if annotation.contract_hash != self.contract_hash:
                raise MarketStructureAnnotationValidationError("annotation contract_hash mismatch.")
            if annotation.detection_result_hash != self.detection_result_hash:
                raise MarketStructureAnnotationValidationError("annotation detection_result_hash mismatch.")

        expected_id = _hash_payload(self._collection_id_payload())
        if self.collection_id:
            if self.collection_id != expected_id:
                raise MarketStructureAnnotationIntegrityError("collection_id mismatch.")
        else:
            object.__setattr__(self, "collection_id", expected_id)

        expected_hash = _hash_payload(self._collection_hash_payload())
        if self.collection_hash:
            if self.collection_hash != expected_hash:
                raise MarketStructureAnnotationIntegrityError("collection_hash mismatch.")
        else:
            object.__setattr__(self, "collection_hash", expected_hash)

    def _collection_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dataset_hash": self.dataset_hash,
            "contract_hash": self.contract_hash,
            "detection_result_hash": self.detection_result_hash,
            "first_candle_timestamp": _utc_iso(self.first_candle_timestamp),
            "last_candle_timestamp": _utc_iso(self.last_candle_timestamp),
            "annotation_count": self.annotation_count,
            "annotations": [annotation._annotation_hash_payload() for annotation in self.annotations],
            "metadata": _thaw_read_only_value(self.metadata),
        }

    def _collection_hash_payload(self) -> dict[str, Any]:
        payload = self._collection_id_payload()
        payload["collection_id"] = self.collection_id
        return payload

    def canonical_payload(
        self,
        *,
        include_collection_id: bool = True,
        include_collection_hash: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "dataset_hash": self.dataset_hash,
            "contract_hash": self.contract_hash,
            "detection_result_hash": self.detection_result_hash,
            "first_candle_timestamp": _utc_iso(self.first_candle_timestamp),
            "last_candle_timestamp": _utc_iso(self.last_candle_timestamp),
            "annotation_count": self.annotation_count,
            "annotations": [annotation.canonical_payload() for annotation in self.annotations],
            "created_at_utc": _utc_iso(self.created_at_utc),
            "metadata": _thaw_read_only_value(self.metadata),
        }
        if include_collection_id:
            payload["collection_id"] = self.collection_id
        if include_collection_hash:
            payload["collection_hash"] = self.collection_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_collection_id=True, include_collection_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureAnnotationCollection":
        if not isinstance(data, Mapping):
            raise MarketStructureAnnotationValidationError("market structure annotation collection must be a mapping.")
        _require_exact_keys(
            data,
            "market structure annotation collection",
            {
                "schema_version",
                "collection_id",
                "collection_hash",
                "dataset_hash",
                "contract_hash",
                "detection_result_hash",
                "first_candle_timestamp",
                "last_candle_timestamp",
                "annotation_count",
                "annotations",
                "created_at_utc",
                "metadata",
            },
        )
        try:
            return cls(
                schema_version=data["schema_version"],
                collection_id=data.get("collection_id", ""),
                collection_hash=data.get("collection_hash", ""),
                dataset_hash=data["dataset_hash"],
                contract_hash=data["contract_hash"],
                detection_result_hash=data["detection_result_hash"],
                annotation_count=data["annotation_count"],
                first_candle_timestamp=data["first_candle_timestamp"],
                last_candle_timestamp=data["last_candle_timestamp"],
                annotations=data["annotations"],
                created_at_utc=data["created_at_utc"],
                metadata=data.get("metadata", {}),
            )
        except KeyError as exc:
            raise MarketStructureAnnotationValidationError(
                "market structure annotation collection is incomplete."
            ) from exc


def build_market_structure_annotation(
    *,
    detection_result: phase51.MarketStructureDetectionResult,
    candle_timestamp: datetime,
    metadata: Mapping[str, Any] | None = None,
    created_at_utc: datetime | None = None,
) -> MarketStructureAnnotation:
    verified_result = verify_market_structure_detection_result(detection_result)
    candle_timestamp = _require_utc_datetime(candle_timestamp, "candle_timestamp")
    created_at_utc = created_at_utc or datetime.now(timezone.utc)

    candle_timestamps = _derive_candle_timestamps(verified_result)
    try:
        candle_index = candle_timestamps.index(candle_timestamp)
    except ValueError as exc:
        raise MarketStructureAnnotationValidationError("candle_timestamp is not part of the detection result.") from exc

    event_kinds = _annotation_event_kinds(
        verified_result,
        candle_index=candle_index,
        candle_timestamp=candle_timestamp,
        candle_timestamps=candle_timestamps,
    )
    annotation_payload = _annotation_payload_from_result(
        verified_result,
        candle_index=candle_index,
        candle_timestamp=candle_timestamp,
        event_kinds=event_kinds,
    )
    return MarketStructureAnnotation(
        schema_version=MARKET_STRUCTURE_ANNOTATION_SCHEMA_VERSION,
        dataset_hash=verified_result.dataset_hash,
        contract_hash=verified_result.contract_hash,
        detection_result_hash=verified_result.detection_result_hash,
        candle_timestamp=candle_timestamp,
        annotation_payload=annotation_payload,
        created_at_utc=created_at_utc,
        metadata=metadata or {},
    )


def verify_market_structure_annotation(
    annotation: MarketStructureAnnotation,
) -> MarketStructureAnnotation:
    if not isinstance(annotation, MarketStructureAnnotation):
        raise MarketStructureAnnotationValidationError("market structure annotation is required.")
    expected_id = _hash_payload(annotation._annotation_id_payload())
    if annotation.annotation_id != expected_id:
        raise MarketStructureAnnotationIntegrityError("annotation_id mismatch.")
    expected_hash = _hash_payload(annotation._annotation_hash_payload())
    if annotation.annotation_hash != expected_hash:
        raise MarketStructureAnnotationIntegrityError("annotation_hash mismatch.")
    return annotation


def annotate_market_structure(
    detection_result: phase51.MarketStructureDetectionResult,
    *,
    metadata: Mapping[str, Any] | None = None,
    created_at_utc: datetime | None = None,
) -> MarketStructureAnnotationCollection:
    verified_result = verify_market_structure_detection_result(detection_result)
    candle_timestamps = _derive_candle_timestamps(verified_result)
    annotations = tuple(
        build_market_structure_annotation(
            detection_result=verified_result,
            candle_timestamp=candle_timestamp,
            metadata=metadata,
            created_at_utc=created_at_utc,
        )
        for candle_timestamp in candle_timestamps
    )
    collection = MarketStructureAnnotationCollection(
        schema_version=MARKET_STRUCTURE_ANNOTATION_COLLECTION_SCHEMA_VERSION,
        dataset_hash=verified_result.dataset_hash,
        contract_hash=verified_result.contract_hash,
        detection_result_hash=verified_result.detection_result_hash,
        annotation_count=len(annotations),
        first_candle_timestamp=annotations[0].candle_timestamp,
        last_candle_timestamp=annotations[-1].candle_timestamp,
        annotations=annotations,
        created_at_utc=created_at_utc or datetime.now(timezone.utc),
        metadata=metadata or {},
    )
    return verify_market_structure_annotation_collection(collection)


def verify_market_structure_annotation_collection(
    annotation_collection: MarketStructureAnnotationCollection,
) -> MarketStructureAnnotationCollection:
    if not isinstance(annotation_collection, MarketStructureAnnotationCollection):
        raise MarketStructureAnnotationValidationError("market structure annotation collection is required.")
    for annotation in annotation_collection.annotations:
        verify_market_structure_annotation(annotation)
    expected_id = _hash_payload(annotation_collection._collection_id_payload())
    if annotation_collection.collection_id != expected_id:
        raise MarketStructureAnnotationIntegrityError("collection_id mismatch.")
    expected_hash = _hash_payload(annotation_collection._collection_hash_payload())
    if annotation_collection.collection_hash != expected_hash:
        raise MarketStructureAnnotationIntegrityError("collection_hash mismatch.")
    return annotation_collection


def market_structure_annotation_to_dict(annotation: MarketStructureAnnotation) -> dict[str, Any]:
    if not isinstance(annotation, MarketStructureAnnotation):
        raise MarketStructureAnnotationValidationError("market structure annotation is required.")
    return annotation.as_dict()


def market_structure_annotation_from_dict(data: Mapping[str, Any]) -> MarketStructureAnnotation:
    return MarketStructureAnnotation.from_dict(data)


def market_structure_annotation_collection_to_dict(
    annotation_collection: MarketStructureAnnotationCollection,
) -> dict[str, Any]:
    if not isinstance(annotation_collection, MarketStructureAnnotationCollection):
        raise MarketStructureAnnotationValidationError("market structure annotation collection is required.")
    return annotation_collection.as_dict()


def market_structure_annotation_collection_from_dict(
    data: Mapping[str, Any],
) -> MarketStructureAnnotationCollection:
    return MarketStructureAnnotationCollection.from_dict(data)


def verify_market_structure_detection_result(
    detection_result: phase51.MarketStructureDetectionResult,
) -> phase51.MarketStructureDetectionResult:
    return phase51.verify_market_structure_detection_result(detection_result)


__all__ = [
    "MARKET_STRUCTURE_ANNOTATION_ALLOWED_ANNOTATION_STATES",
    "MARKET_STRUCTURE_ANNOTATION_ALLOWED_EVENT_KINDS",
    "MARKET_STRUCTURE_ANNOTATION_ALLOWED_HYPOTHESIS_STATES",
    "MARKET_STRUCTURE_ANNOTATION_ALLOWED_INVALIDATION_STATES",
    "MARKET_STRUCTURE_ANNOTATION_ALLOWED_STRUCTURE_STATES",
    "MARKET_STRUCTURE_ANNOTATION_COLLECTION_ID",
    "MARKET_STRUCTURE_ANNOTATION_COLLECTION_SCHEMA_VERSION",
    "MARKET_STRUCTURE_ANNOTATION_COLLECTION_VERSION",
    "MARKET_STRUCTURE_ANNOTATION_ID",
    "MARKET_STRUCTURE_ANNOTATION_PAYLOAD_KEYS",
    "MARKET_STRUCTURE_ANNOTATION_SCHEMA_VERSION",
    "MARKET_STRUCTURE_ANNOTATION_VERSION",
    "MarketStructureAnnotation",
    "MarketStructureAnnotationCollection",
    "MarketStructureAnnotationError",
    "MarketStructureAnnotationIntegrityError",
    "MarketStructureAnnotationValidationError",
    "annotate_market_structure",
    "build_market_structure_annotation",
    "market_structure_annotation_collection_from_dict",
    "market_structure_annotation_collection_to_dict",
    "market_structure_annotation_from_dict",
    "market_structure_annotation_to_dict",
    "verify_market_structure_annotation",
    "verify_market_structure_annotation_collection",
    "verify_market_structure_detection_result",
]
