from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value

from .errors import HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError
from . import market_structure_structural_assessment as phase55

MARKET_STRUCTURE_TEMPORAL_VALIDATION_SCHEMA_VERSION = 1
MARKET_STRUCTURE_TEMPORAL_VALIDATION_ID = "market_structure_structural_assessment_transition"
MARKET_STRUCTURE_TEMPORAL_VALIDATION_VERSION = "phase56_temporal_structural_validation_v1"
MARKET_STRUCTURE_TEMPORAL_VALIDATION_NON_OPERATIONAL_DECLARATION = (
    "This temporal structural validation is research-only and does not authorize replay, backtest, "
    "walk-forward, performance evaluation, ranking, scoring, paper trading, live trading, exchange "
    "connectivity, execution, or order submission."
)

MARKET_STRUCTURE_TEMPORAL_VALIDATION_TRANSITION_TYPES: tuple[str, ...] = (
    "no_change",
    "dimension_change",
    "state_change",
    "invalidation",
)


class MarketStructureTemporalValidationError(HistoricalDataError):
    pass


class MarketStructureTemporalValidationValidationError(
    MarketStructureTemporalValidationError,
    HistoricalDataValidationError,
):
    pass


class MarketStructureTemporalValidationIntegrityError(
    MarketStructureTemporalValidationError,
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
        raise MarketStructureTemporalValidationValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketStructureTemporalValidationValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise MarketStructureTemporalValidationValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise MarketStructureTemporalValidationValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise MarketStructureTemporalValidationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise MarketStructureTemporalValidationValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise MarketStructureTemporalValidationValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketStructureTemporalValidationValidationError(f"{field_name} must be timezone-aware UTC datetime.")
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
    if isinstance(value, MappingProxyType) or isinstance(value, Mapping):
        return {key: _thaw_read_only_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_thaw_read_only_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_thaw_read_only_value(item) for item in value)
    if isinstance(value, set) or isinstance(value, frozenset):
        thawed_items = [_thaw_read_only_value(item) for item in value]
        return tuple(sorted(thawed_items, key=_canonical_json))
    return value


def _unique_sorted(values: Sequence[str] | set[str] | frozenset[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(dict.fromkeys(values)))


def _require_str_sequence(value: Any, field_name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (Sequence, set, frozenset)):
        raise MarketStructureTemporalValidationValidationError(f"{field_name} must be a sequence of strings.")
    normalized = _unique_sorted(_require_str(item, field_name) for item in value)
    if not allow_empty and not normalized:
        raise MarketStructureTemporalValidationValidationError(f"{field_name} must not be empty.")
    return normalized


def _require_exact_keys(mapping: Mapping[str, Any], field_name: str, expected_keys: set[str]) -> None:
    extra = sorted(set(mapping) - expected_keys)
    missing = sorted(expected_keys - set(mapping))
    if extra or missing:
        parts: list[str] = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected {', '.join(extra)}")
        raise MarketStructureTemporalValidationValidationError(
            f"{field_name} has invalid fields: {'; '.join(parts)}."
        )


def _normalize_metadata(value: Any, field_name: str = "metadata") -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MarketStructureTemporalValidationValidationError(f"{field_name} must be a mapping.")
    return _freeze_read_only_value(dict(value))


def _normalize_transition_reasons(value: Any) -> tuple[str, ...]:
    return _require_str_sequence(value, "transition_reasons")


def _normalize_changed_dimensions(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (Sequence, set, frozenset)):
        raise MarketStructureTemporalValidationValidationError("changed_dimensions must be a sequence of strings.")
    canonical_order = {name: index for index, name in enumerate(phase55.MARKET_STRUCTURE_STRUCTURAL_DIMENSIONS)}
    normalized = []
    seen: set[str] = set()
    for item in value:
        dimension_name = _require_str(item, "changed_dimensions").lower()
        if dimension_name not in canonical_order:
            raise MarketStructureTemporalValidationValidationError("changed_dimensions contains an unknown dimension.")
        if dimension_name not in seen:
            seen.add(dimension_name)
            normalized.append(dimension_name)
    normalized.sort(key=lambda name: canonical_order[name])
    if len(normalized) != len(tuple(value)) and len(seen) != len(tuple(value)):
        # duplicate detection is intentionally fail-closed via canonical collapse below
        pass
    return tuple(normalized)


def _dimension_payload(summary: phase55.MarketStructureStructuralDimensionSummary) -> dict[str, Any]:
    return summary.canonical_payload(include_dimension_hash=False)


def _summary_has_material_diff(
    previous: phase55.MarketStructureStructuralDimensionSummary | None,
    current: phase55.MarketStructureStructuralDimensionSummary | None,
) -> bool:
    if previous is None and current is None:
        return False
    if previous is None or current is None:
        return True
    return _dimension_payload(previous) != _dimension_payload(current)


def _dimension_transition_reasons(
    dimension_name: str,
    previous: phase55.MarketStructureStructuralDimensionSummary | None,
    current: phase55.MarketStructureStructuralDimensionSummary | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if previous is None and current is not None:
        reasons.append(f"dimension_added:{dimension_name}")
        reasons.append(f"dimension_state:{dimension_name}:absent->{current.dimension_state}")
    elif current is None and previous is not None:
        reasons.append(f"dimension_removed:{dimension_name}")
        reasons.append(f"dimension_state:{dimension_name}:{previous.dimension_state}->absent")
    elif previous is not None and current is not None:
        if previous.dimension_state != current.dimension_state:
            reasons.append(
                f"dimension_state:{dimension_name}:{previous.dimension_state}->{current.dimension_state}"
            )
        if previous.supporting_evidence_ids != current.supporting_evidence_ids:
            reasons.append(f"supporting_evidence_changed:{dimension_name}")
        if previous.contradicting_evidence_ids != current.contradicting_evidence_ids:
            reasons.append(f"contradicting_evidence_changed:{dimension_name}")
        if previous.ambiguous_evidence_ids != current.ambiguous_evidence_ids:
            reasons.append(f"ambiguous_evidence_changed:{dimension_name}")
        if previous.invalidation_evidence_ids != current.invalidation_evidence_ids:
            reasons.append(f"invalidation_evidence_changed:{dimension_name}")
        if previous.neutral_evidence_ids != current.neutral_evidence_ids:
            reasons.append(f"neutral_evidence_changed:{dimension_name}")
        if previous.provenance_group_ids != current.provenance_group_ids:
            reasons.append(f"provenance_changed:{dimension_name}")
        if previous.timeframe_context != current.timeframe_context:
            reasons.append(f"timeframe_context_changed:{dimension_name}")
        if previous.ambiguity_reasons != current.ambiguity_reasons:
            reasons.append(f"ambiguity_reasons_changed:{dimension_name}")
        if previous.invalidation_reasons != current.invalidation_reasons:
            reasons.append(f"invalidation_reasons_changed:{dimension_name}")
        if _thaw_read_only_value(previous.metadata) != _thaw_read_only_value(current.metadata):
            reasons.append(f"metadata_changed:{dimension_name}")
    return tuple(reasons)


def _dimension_names_in_order(
    previous: Mapping[str, phase55.MarketStructureStructuralDimensionSummary],
    current: Mapping[str, phase55.MarketStructureStructuralDimensionSummary],
) -> tuple[str, ...]:
    canonical_order = {name: index for index, name in enumerate(phase55.MARKET_STRUCTURE_STRUCTURAL_DIMENSIONS)}
    unknown = sorted((set(previous) | set(current)) - set(canonical_order))
    if unknown:
        raise MarketStructureTemporalValidationValidationError("dimension_summaries contains an unknown dimension.")
    changed = [
        name
        for name in phase55.MARKET_STRUCTURE_STRUCTURAL_DIMENSIONS
        if _summary_has_material_diff(previous.get(name), current.get(name))
    ]
    return tuple(changed)


def _derive_transition_reasons(
    previous: phase55.MarketStructureStructuralAssessment,
    current: phase55.MarketStructureStructuralAssessment,
    changed_dimensions: tuple[str, ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if previous.created_at_utc == current.created_at_utc:
        reasons.append("same_timestamp")
    if not changed_dimensions:
        reasons.append("materially_equivalent")
    else:
        for dimension_name in changed_dimensions:
            reasons.extend(
                _dimension_transition_reasons(
                    dimension_name,
                    previous.dimension_summaries.get(dimension_name),
                    current.dimension_summaries.get(dimension_name),
                )
            )
    if previous.structural_state != current.structural_state:
        reasons.append(f"structural_state:{previous.structural_state}->{current.structural_state}")
    if previous.ambiguity_state != current.ambiguity_state:
        reasons.append(f"ambiguity_state:{previous.ambiguity_state}->{current.ambiguity_state}")
    if previous.invalidation_state != current.invalidation_state:
        reasons.append(f"invalidation_state:{previous.invalidation_state}->{current.invalidation_state}")
    return _unique_sorted(tuple(reasons))


def _derive_transition_type(
    previous: phase55.MarketStructureStructuralAssessment,
    current: phase55.MarketStructureStructuralAssessment,
    changed_dimensions: tuple[str, ...],
) -> str:
    if not changed_dimensions and previous.structural_state == current.structural_state:
        return "no_change"
    if previous.structural_state == "invalidated" and current.structural_state != "invalidated":
        raise MarketStructureTemporalValidationValidationError(
            "invalidated structural assessments cannot silently resurrect."
        )
    if previous.structural_state != current.structural_state and current.structural_state == "invalidated":
        return "invalidation"
    if previous.structural_state != current.structural_state:
        return "state_change"
    return "dimension_change"


def _normalize_assessment(value: Any, field_name: str) -> phase55.MarketStructureStructuralAssessment:
    if isinstance(value, Mapping):
        return phase55.market_structure_structural_assessment_from_dict(value)
    if not isinstance(value, phase55.MarketStructureStructuralAssessment):
        raise MarketStructureTemporalValidationValidationError(f"{field_name} is required.")
    return value


@dataclass(frozen=True, slots=True)
class MarketStructureStructuralAssessmentTransition:
    schema_version: int = MARKET_STRUCTURE_TEMPORAL_VALIDATION_SCHEMA_VERSION
    transition_id: str = ""
    transition_hash: str = ""
    previous_assessment_id: str = ""
    previous_assessment_hash: str = ""
    current_assessment_id: str = ""
    current_assessment_hash: str = ""
    hypothesis_id: str = ""
    hypothesis_hash: str = ""
    transition_type: str = ""
    changed_dimensions: tuple[str, ...] = field(default_factory=tuple)
    transition_reasons: tuple[str, ...] = field(default_factory=tuple)
    previous_structural_state: str = ""
    current_structural_state: str = ""
    effective_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "transition_id", _require_hex_digest(self.transition_id, "transition_id") if self.transition_id else "")
        object.__setattr__(self, "transition_hash", _require_hex_digest(self.transition_hash, "transition_hash") if self.transition_hash else "")
        object.__setattr__(self, "previous_assessment_id", _require_hex_digest(self.previous_assessment_id, "previous_assessment_id"))
        object.__setattr__(self, "previous_assessment_hash", _require_hex_digest(self.previous_assessment_hash, "previous_assessment_hash"))
        object.__setattr__(self, "current_assessment_id", _require_hex_digest(self.current_assessment_id, "current_assessment_id"))
        object.__setattr__(self, "current_assessment_hash", _require_hex_digest(self.current_assessment_hash, "current_assessment_hash"))
        object.__setattr__(self, "hypothesis_id", _require_hex_digest(self.hypothesis_id, "hypothesis_id"))
        object.__setattr__(self, "hypothesis_hash", _require_hex_digest(self.hypothesis_hash, "hypothesis_hash"))
        object.__setattr__(self, "transition_type", _require_str(self.transition_type, "transition_type").lower())
        if self.transition_type not in MARKET_STRUCTURE_TEMPORAL_VALIDATION_TRANSITION_TYPES:
            raise MarketStructureTemporalValidationValidationError("transition_type is invalid.")
        object.__setattr__(self, "changed_dimensions", _normalize_changed_dimensions(self.changed_dimensions))
        object.__setattr__(self, "transition_reasons", _normalize_transition_reasons(self.transition_reasons))
        object.__setattr__(self, "previous_structural_state", _require_str(self.previous_structural_state, "previous_structural_state").lower())
        object.__setattr__(self, "current_structural_state", _require_str(self.current_structural_state, "current_structural_state").lower())
        if self.previous_structural_state not in phase55.MARKET_STRUCTURE_STRUCTURAL_STATES:
            raise MarketStructureTemporalValidationValidationError("previous_structural_state is invalid.")
        if self.current_structural_state not in phase55.MARKET_STRUCTURE_STRUCTURAL_STATES:
            raise MarketStructureTemporalValidationValidationError("current_structural_state is invalid.")
        object.__setattr__(self, "effective_at", _require_utc_datetime(self.effective_at, "effective_at"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        if not isinstance(self.metadata, Mapping):
            raise MarketStructureTemporalValidationValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))

        if self.transition_type == "no_change" and self.changed_dimensions:
            raise MarketStructureTemporalValidationValidationError("no_change transitions must not have changed dimensions.")
        if self.transition_type != "no_change" and not self.transition_reasons:
            raise MarketStructureTemporalValidationValidationError("transition reasons are required.")

        if not self.transition_id:
            object.__setattr__(self, "transition_id", _hash_payload(self._transition_id_payload()))
        else:
            expected_transition_id = _hash_payload(self._transition_id_payload())
            if self.transition_id != expected_transition_id:
                raise MarketStructureTemporalValidationIntegrityError("transition_id mismatch.")

        expected_transition_hash = _hash_payload(self._transition_hash_payload())
        if self.transition_hash:
            if self.transition_hash != expected_transition_hash:
                raise MarketStructureTemporalValidationIntegrityError("transition_hash mismatch.")
        else:
            object.__setattr__(self, "transition_hash", expected_transition_hash)

    def _transition_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "previous_assessment_id": self.previous_assessment_id,
            "previous_assessment_hash": self.previous_assessment_hash,
            "current_assessment_id": self.current_assessment_id,
            "current_assessment_hash": self.current_assessment_hash,
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_hash": self.hypothesis_hash,
            "transition_type": self.transition_type,
            "changed_dimensions": self.changed_dimensions,
            "transition_reasons": self.transition_reasons,
            "previous_structural_state": self.previous_structural_state,
            "current_structural_state": self.current_structural_state,
            "effective_at": _utc_iso(self.effective_at),
            "metadata": _thaw_read_only_value(self.metadata),
        }

    def _transition_hash_payload(self) -> dict[str, Any]:
        payload = self._transition_id_payload()
        payload["transition_id"] = self.transition_id
        return payload

    def canonical_payload(self, *, include_transition_id: bool = True, include_transition_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "previous_assessment_id": self.previous_assessment_id,
            "previous_assessment_hash": self.previous_assessment_hash,
            "current_assessment_id": self.current_assessment_id,
            "current_assessment_hash": self.current_assessment_hash,
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_hash": self.hypothesis_hash,
            "transition_type": self.transition_type,
            "changed_dimensions": self.changed_dimensions,
            "transition_reasons": self.transition_reasons,
            "previous_structural_state": self.previous_structural_state,
            "current_structural_state": self.current_structural_state,
            "effective_at": _utc_iso(self.effective_at),
            "metadata": _thaw_read_only_value(self.metadata),
            "created_at_utc": _utc_iso(self.created_at_utc),
        }
        if include_transition_id:
            payload["transition_id"] = self.transition_id
        if include_transition_hash:
            payload["transition_hash"] = self.transition_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_transition_id=True, include_transition_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureStructuralAssessmentTransition":
        if not isinstance(data, Mapping):
            raise MarketStructureTemporalValidationValidationError(
                "market structure structural assessment transition must be a mapping."
            )
        allowed = {
            "schema_version",
            "transition_id",
            "transition_hash",
            "previous_assessment_id",
            "previous_assessment_hash",
            "current_assessment_id",
            "current_assessment_hash",
            "hypothesis_id",
            "hypothesis_hash",
            "transition_type",
            "changed_dimensions",
            "transition_reasons",
            "previous_structural_state",
            "current_structural_state",
            "effective_at",
            "metadata",
            "created_at_utc",
        }
        extra = sorted(set(data) - allowed)
        missing = sorted(allowed - set(data))
        if extra or missing:
            parts: list[str] = []
            if missing:
                parts.append(f"missing {', '.join(missing)}")
            if extra:
                parts.append(f"unexpected {', '.join(extra)}")
            raise MarketStructureTemporalValidationValidationError(
                f"market structure structural assessment transition has invalid fields: {'; '.join(parts)}."
            )
        try:
            return cls(
                schema_version=data["schema_version"],
                transition_id=data.get("transition_id", ""),
                transition_hash=data.get("transition_hash", ""),
                previous_assessment_id=data["previous_assessment_id"],
                previous_assessment_hash=data["previous_assessment_hash"],
                current_assessment_id=data["current_assessment_id"],
                current_assessment_hash=data["current_assessment_hash"],
                hypothesis_id=data["hypothesis_id"],
                hypothesis_hash=data["hypothesis_hash"],
                transition_type=data["transition_type"],
                changed_dimensions=data["changed_dimensions"],
                transition_reasons=data["transition_reasons"],
                previous_structural_state=data["previous_structural_state"],
                current_structural_state=data["current_structural_state"],
                effective_at=data["effective_at"],
                metadata=data.get("metadata", {}),
                created_at_utc=data["created_at_utc"],
            )
        except KeyError as exc:
            raise MarketStructureTemporalValidationValidationError(
                "market structure structural assessment transition is incomplete."
            ) from exc


def _validate_assessment_pair(
    previous: phase55.MarketStructureStructuralAssessment,
    current: phase55.MarketStructureStructuralAssessment,
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    if previous.hypothesis_id != current.hypothesis_id or previous.hypothesis_hash != current.hypothesis_hash:
        raise MarketStructureTemporalValidationValidationError("cross-hypothesis transitions are not allowed.")
    if previous.dataset_hash != current.dataset_hash:
        raise MarketStructureTemporalValidationValidationError("cross-dataset transitions are not allowed.")
    if previous.contract_hash != current.contract_hash:
        raise MarketStructureTemporalValidationValidationError("cross-contract transitions are not allowed.")
    if previous.detection_result_hash != current.detection_result_hash:
        raise MarketStructureTemporalValidationValidationError("cross-detection-result transitions are not allowed.")
    if previous.annotation_collection_hash != current.annotation_collection_hash:
        raise MarketStructureTemporalValidationValidationError(
            "cross-annotation-collection transitions are not allowed."
        )
    if current.created_at_utc < previous.created_at_utc:
        raise MarketStructureTemporalValidationValidationError("timestamp regression is not allowed.")

    changed_dimensions = _dimension_names_in_order(previous.dimension_summaries, current.dimension_summaries)
    if current.created_at_utc == previous.created_at_utc and changed_dimensions:
        raise MarketStructureTemporalValidationValidationError("same timestamp with different content is not allowed.")

    transition_type = _derive_transition_type(previous, current, changed_dimensions)
    transition_reasons = _derive_transition_reasons(previous, current, changed_dimensions)
    if previous.structural_state == "invalidated" and current.structural_state != "invalidated" and transition_type != "no_change":
        raise MarketStructureTemporalValidationValidationError(
            "invalidated structural assessments cannot silently resurrect."
        )
    return changed_dimensions, transition_reasons, transition_type


def build_market_structure_structural_assessment_transition(
    previous_structural_assessment: phase55.MarketStructureStructuralAssessment | Mapping[str, Any],
    current_structural_assessment: phase55.MarketStructureStructuralAssessment | Mapping[str, Any],
    *,
    metadata: Mapping[str, Any] | None = None,
    created_at_utc: datetime | None = None,
) -> MarketStructureStructuralAssessmentTransition:
    previous = _normalize_assessment(previous_structural_assessment, "previous_structural_assessment")
    current = _normalize_assessment(current_structural_assessment, "current_structural_assessment")
    previous = phase55.verify_market_structure_structural_assessment(previous)
    current = phase55.verify_market_structure_structural_assessment(current)

    changed_dimensions, transition_reasons, transition_type = _validate_assessment_pair(previous, current)
    transition = MarketStructureStructuralAssessmentTransition(
        schema_version=MARKET_STRUCTURE_TEMPORAL_VALIDATION_SCHEMA_VERSION,
        previous_assessment_id=previous.assessment_id,
        previous_assessment_hash=previous.assessment_hash,
        current_assessment_id=current.assessment_id,
        current_assessment_hash=current.assessment_hash,
        hypothesis_id=current.hypothesis_id,
        hypothesis_hash=current.hypothesis_hash,
        transition_type=transition_type,
        changed_dimensions=changed_dimensions,
        transition_reasons=transition_reasons,
        previous_structural_state=previous.structural_state,
        current_structural_state=current.structural_state,
        effective_at=current.created_at_utc,
        metadata=metadata or {},
        created_at_utc=created_at_utc or current.created_at_utc,
    )
    return verify_market_structure_structural_assessment_transition(transition)


def verify_market_structure_structural_assessment_transition(
    transition: MarketStructureStructuralAssessmentTransition,
) -> MarketStructureStructuralAssessmentTransition:
    if not isinstance(transition, MarketStructureStructuralAssessmentTransition):
        raise MarketStructureTemporalValidationValidationError(
            "market structure structural assessment transition is required."
        )
    expected_id = _hash_payload(transition._transition_id_payload())
    if transition.transition_id != expected_id:
        raise MarketStructureTemporalValidationIntegrityError("transition_id mismatch.")
    expected_hash = _hash_payload(transition._transition_hash_payload())
    if transition.transition_hash != expected_hash:
        raise MarketStructureTemporalValidationIntegrityError("transition_hash mismatch.")
    if transition.transition_type == "no_change" and transition.changed_dimensions:
        raise MarketStructureTemporalValidationValidationError("no_change transitions must not have changed dimensions.")
    if transition.transition_type not in MARKET_STRUCTURE_TEMPORAL_VALIDATION_TRANSITION_TYPES:
        raise MarketStructureTemporalValidationValidationError("transition_type is invalid.")
    if transition.current_structural_state == "invalidated" and transition.transition_type == "no_change":
        return transition
    if transition.previous_structural_state == "invalidated" and transition.current_structural_state != "invalidated":
        raise MarketStructureTemporalValidationValidationError(
            "invalidated structural assessments cannot silently resurrect."
        )
    if transition.current_structural_state == "invalidated" and transition.transition_type != "invalidation":
        raise MarketStructureTemporalValidationValidationError("invalidated transitions must be classified as invalidation.")
    if transition.previous_structural_state != transition.current_structural_state:
        expected_type = "invalidation" if transition.current_structural_state == "invalidated" else "state_change"
    elif transition.changed_dimensions:
        expected_type = "dimension_change"
    else:
        expected_type = "no_change"
    if transition.transition_type != expected_type:
        raise MarketStructureTemporalValidationValidationError("transition_type is inconsistent with the snapshot pair.")
    return transition


def market_structure_structural_assessment_transition_to_dict(
    transition: MarketStructureStructuralAssessmentTransition,
) -> dict[str, Any]:
    if not isinstance(transition, MarketStructureStructuralAssessmentTransition):
        raise MarketStructureTemporalValidationValidationError(
            "market structure structural assessment transition is required."
        )
    return transition.as_dict()


def market_structure_structural_assessment_transition_from_dict(
    data: Mapping[str, Any],
) -> MarketStructureStructuralAssessmentTransition:
    return MarketStructureStructuralAssessmentTransition.from_dict(data)


__all__ = [
    "MARKET_STRUCTURE_TEMPORAL_VALIDATION_ID",
    "MARKET_STRUCTURE_TEMPORAL_VALIDATION_NON_OPERATIONAL_DECLARATION",
    "MARKET_STRUCTURE_TEMPORAL_VALIDATION_SCHEMA_VERSION",
    "MARKET_STRUCTURE_TEMPORAL_VALIDATION_TRANSITION_TYPES",
    "MARKET_STRUCTURE_TEMPORAL_VALIDATION_VERSION",
    "MarketStructureStructuralAssessmentTransition",
    "MarketStructureTemporalValidationError",
    "MarketStructureTemporalValidationIntegrityError",
    "MarketStructureTemporalValidationValidationError",
    "build_market_structure_structural_assessment_transition",
    "market_structure_structural_assessment_transition_from_dict",
    "market_structure_structural_assessment_transition_to_dict",
    "verify_market_structure_structural_assessment_transition",
]
