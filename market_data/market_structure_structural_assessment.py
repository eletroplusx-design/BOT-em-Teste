from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value

from .errors import HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError
from . import market_structure_evidence_assessment as phase54
from . import market_structure_hypothesis_evaluation as phase53

MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_SCHEMA_VERSION = 1
MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_ID = "market_structure_structural_assessment"
MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_VERSION = "phase55_market_structure_structural_assessment_v1"
MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_NON_OPERATIONAL_DECLARATION = (
    "This structural assessment is research-only and does not authorize replay, backtest, walk-forward, "
    "performance evaluation, ranking, paper trading, live trading, exchange connectivity, execution, or "
    "order submission."
)

MARKET_STRUCTURE_STRUCTURAL_DIMENSIONS: tuple[str, ...] = phase54.MARKET_STRUCTURE_EVIDENCE_FAMILIES
MARKET_STRUCTURE_STRUCTURAL_DIMENSION_STATES: tuple[str, ...] = (
    "supporting",
    "contradicting",
    "conflicted",
    "ambiguous",
    "indeterminate",
    "absent",
    "invalidated",
    "neutral",
)
MARKET_STRUCTURE_STRUCTURAL_STATES: tuple[str, ...] = (
    "supported",
    "contradicted",
    "conflicted",
    "ambiguous",
    "indeterminate",
    "invalidated",
    "neutral",
    "empty",
)
MARKET_STRUCTURE_STRUCTURAL_INVALIDATION_STATES: tuple[str, ...] = ("none", "present")


class MarketStructureStructuralAssessmentError(HistoricalDataError):
    pass


class MarketStructureStructuralAssessmentValidationError(
    MarketStructureStructuralAssessmentError,
    HistoricalDataValidationError,
):
    pass


class MarketStructureStructuralAssessmentIntegrityError(
    MarketStructureStructuralAssessmentError,
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
        raise MarketStructureStructuralAssessmentValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketStructureStructuralAssessmentValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise MarketStructureStructuralAssessmentValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise MarketStructureStructuralAssessmentValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise MarketStructureStructuralAssessmentValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise MarketStructureStructuralAssessmentValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise MarketStructureStructuralAssessmentValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise MarketStructureStructuralAssessmentValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketStructureStructuralAssessmentValidationError(f"{field_name} must be timezone-aware UTC datetime.")
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


def _unique_sorted(values: Any) -> tuple[str, ...]:
    return tuple(sorted(dict.fromkeys(values)))


def _require_str_sequence(value: Any, field_name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (Sequence, set, frozenset)):
        raise MarketStructureStructuralAssessmentValidationError(f"{field_name} must be a sequence of strings.")
    normalized = _unique_sorted(_require_str(item, field_name) for item in value)
    if not allow_empty and not normalized:
        raise MarketStructureStructuralAssessmentValidationError(f"{field_name} must not be empty.")
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
        raise MarketStructureStructuralAssessmentValidationError(
            f"{field_name} has invalid fields: {'; '.join(parts)}."
        )


def _normalize_timeframe_context(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MarketStructureStructuralAssessmentValidationError(f"{field_name} must be a mapping.")
    _require_exact_keys(
        value,
        field_name,
        set(phase53.MARKET_STRUCTURE_HYPOTHESIS_TIMEFRAME_CONTEXT_KEYS),
    )
    return _freeze_read_only_value(dict(value))


def _normalize_dimension_summary_payload(payload: Mapping[str, Any], *, field_name: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise MarketStructureStructuralAssessmentValidationError(f"{field_name} must be a mapping.")
    required_keys = {
        "dimension_name",
        "dimension_state",
        "supporting_evidence_ids",
        "contradicting_evidence_ids",
        "ambiguous_evidence_ids",
        "invalidation_evidence_ids",
        "neutral_evidence_ids",
        "provenance_group_ids",
        "timeframe_context",
        "ambiguity_reasons",
        "invalidation_reasons",
        "metadata",
        "dimension_hash",
    }
    _require_exact_keys(payload, field_name, required_keys)
    return dict(payload)


@dataclass(frozen=True, slots=True)
class MarketStructureStructuralDimensionSummary:
    dimension_name: str
    dimension_state: str = "indeterminate"
    supporting_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    contradicting_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    ambiguous_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    invalidation_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    neutral_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    provenance_group_ids: tuple[str, ...] = field(default_factory=tuple)
    timeframe_context: Mapping[str, Any] = field(default_factory=dict, repr=False)
    ambiguity_reasons: tuple[str, ...] = field(default_factory=tuple)
    invalidation_reasons: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    dimension_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimension_name", _require_str(self.dimension_name, "dimension_name").lower())
        if self.dimension_name not in MARKET_STRUCTURE_STRUCTURAL_DIMENSIONS:
            raise MarketStructureStructuralAssessmentValidationError("dimension_name is invalid.")
        object.__setattr__(self, "dimension_state", _require_str(self.dimension_state, "dimension_state").lower())
        if self.dimension_state not in MARKET_STRUCTURE_STRUCTURAL_DIMENSION_STATES:
            raise MarketStructureStructuralAssessmentValidationError("dimension_state is invalid.")
        object.__setattr__(
            self,
            "supporting_evidence_ids",
            _require_str_sequence(self.supporting_evidence_ids, "supporting_evidence_ids", allow_empty=True),
        )
        object.__setattr__(
            self,
            "contradicting_evidence_ids",
            _require_str_sequence(self.contradicting_evidence_ids, "contradicting_evidence_ids", allow_empty=True),
        )
        object.__setattr__(
            self,
            "ambiguous_evidence_ids",
            _require_str_sequence(self.ambiguous_evidence_ids, "ambiguous_evidence_ids", allow_empty=True),
        )
        object.__setattr__(
            self,
            "invalidation_evidence_ids",
            _require_str_sequence(self.invalidation_evidence_ids, "invalidation_evidence_ids", allow_empty=True),
        )
        object.__setattr__(
            self,
            "neutral_evidence_ids",
            _require_str_sequence(self.neutral_evidence_ids, "neutral_evidence_ids", allow_empty=True),
        )
        object.__setattr__(
            self,
            "provenance_group_ids",
            _require_str_sequence(self.provenance_group_ids, "provenance_group_ids", allow_empty=True),
        )
        object.__setattr__(
            self,
            "ambiguity_reasons",
            _require_str_sequence(self.ambiguity_reasons, "ambiguity_reasons", allow_empty=True),
        )
        object.__setattr__(
            self,
            "invalidation_reasons",
            _require_str_sequence(self.invalidation_reasons, "invalidation_reasons", allow_empty=True),
        )
        object.__setattr__(self, "timeframe_context", _normalize_timeframe_context(self.timeframe_context, "timeframe_context"))
        if not isinstance(self.metadata, Mapping):
            raise MarketStructureStructuralAssessmentValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))

        if self.dimension_state == "absent":
            if any(
                (
                    self.supporting_evidence_ids,
                    self.contradicting_evidence_ids,
                    self.ambiguous_evidence_ids,
                    self.invalidation_evidence_ids,
                    self.neutral_evidence_ids,
                    self.provenance_group_ids,
                )
            ):
                raise MarketStructureStructuralAssessmentValidationError(
                    "absent dimension summary must not contain evidence references."
                )
        else:
            if not any(
                (
                    self.supporting_evidence_ids,
                    self.contradicting_evidence_ids,
                    self.ambiguous_evidence_ids,
                    self.invalidation_evidence_ids,
                    self.neutral_evidence_ids,
                )
            ):
                raise MarketStructureStructuralAssessmentValidationError(
                    "dimension summary must contain evidence references or be absent."
                )

        if not self.dimension_hash:
            object.__setattr__(self, "dimension_hash", _hash_payload(self.canonical_payload(include_dimension_hash=False)))
        else:
            expected_hash = _hash_payload(self.canonical_payload(include_dimension_hash=False))
            if self.dimension_hash != expected_hash:
                raise MarketStructureStructuralAssessmentIntegrityError("dimension_hash mismatch.")

    def canonical_payload(self, *, include_dimension_hash: bool = True) -> dict[str, Any]:
        payload = {
            "dimension_name": self.dimension_name,
            "dimension_state": self.dimension_state,
            "supporting_evidence_ids": self.supporting_evidence_ids,
            "contradicting_evidence_ids": self.contradicting_evidence_ids,
            "ambiguous_evidence_ids": self.ambiguous_evidence_ids,
            "invalidation_evidence_ids": self.invalidation_evidence_ids,
            "neutral_evidence_ids": self.neutral_evidence_ids,
            "provenance_group_ids": self.provenance_group_ids,
            "timeframe_context": _thaw_read_only_value(self.timeframe_context),
            "ambiguity_reasons": self.ambiguity_reasons,
            "invalidation_reasons": self.invalidation_reasons,
            "metadata": _thaw_read_only_value(self.metadata),
        }
        if include_dimension_hash:
            payload["dimension_hash"] = self.dimension_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_dimension_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureStructuralDimensionSummary":
        mapping = _normalize_dimension_summary_payload(data, field_name="market structure structural dimension summary")
        try:
            return cls(
                dimension_name=mapping["dimension_name"],
                dimension_state=mapping["dimension_state"],
                supporting_evidence_ids=tuple(mapping["supporting_evidence_ids"]),
                contradicting_evidence_ids=tuple(mapping["contradicting_evidence_ids"]),
                ambiguous_evidence_ids=tuple(mapping["ambiguous_evidence_ids"]),
                invalidation_evidence_ids=tuple(mapping["invalidation_evidence_ids"]),
                neutral_evidence_ids=tuple(mapping["neutral_evidence_ids"]),
                provenance_group_ids=tuple(mapping["provenance_group_ids"]),
                timeframe_context=mapping["timeframe_context"],
                ambiguity_reasons=tuple(mapping["ambiguity_reasons"]),
                invalidation_reasons=tuple(mapping["invalidation_reasons"]),
                metadata=mapping.get("metadata", {}),
                dimension_hash=mapping.get("dimension_hash", ""),
            )
        except KeyError as exc:
            raise MarketStructureStructuralAssessmentValidationError(
                "market structure structural dimension summary is incomplete."
            ) from exc


@dataclass(frozen=True, slots=True)
class MarketStructureStructuralAssessment:
    schema_version: int = MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_SCHEMA_VERSION
    assessment_id: str = ""
    assessment_hash: str = ""
    hypothesis_id: str = ""
    hypothesis_hash: str = ""
    hypothesis_evaluation_hash: str = ""
    evidence_assessment_id: str = ""
    evidence_assessment_hash: str = ""
    dataset_hash: str = ""
    contract_hash: str = ""
    detection_result_hash: str = ""
    annotation_collection_hash: str = ""
    dimension_summaries: Mapping[str, MarketStructureStructuralDimensionSummary] = field(default_factory=dict, repr=False)
    structural_state: str = ""
    ambiguity_state: str = ""
    invalidation_state: str = ""
    timeframe_context: Mapping[str, Any] = field(default_factory=dict, repr=False)
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_NON_OPERATIONAL_DECLARATION
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "assessment_id", _require_hex_digest(self.assessment_id, "assessment_id") if self.assessment_id else "")
        object.__setattr__(self, "assessment_hash", _require_hex_digest(self.assessment_hash, "assessment_hash") if self.assessment_hash else "")
        object.__setattr__(self, "hypothesis_id", _require_hex_digest(self.hypothesis_id, "hypothesis_id"))
        object.__setattr__(self, "hypothesis_hash", _require_hex_digest(self.hypothesis_hash, "hypothesis_hash"))
        object.__setattr__(self, "hypothesis_evaluation_hash", _require_hex_digest(self.hypothesis_evaluation_hash, "hypothesis_evaluation_hash"))
        object.__setattr__(self, "evidence_assessment_id", _require_hex_digest(self.evidence_assessment_id, "evidence_assessment_id"))
        object.__setattr__(self, "evidence_assessment_hash", _require_hex_digest(self.evidence_assessment_hash, "evidence_assessment_hash"))
        object.__setattr__(self, "dataset_hash", _require_hex_digest(self.dataset_hash, "dataset_hash"))
        object.__setattr__(self, "contract_hash", _require_hex_digest(self.contract_hash, "contract_hash"))
        object.__setattr__(self, "detection_result_hash", _require_hex_digest(self.detection_result_hash, "detection_result_hash"))
        object.__setattr__(self, "annotation_collection_hash", _require_hex_digest(self.annotation_collection_hash, "annotation_collection_hash"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if not isinstance(self.metadata, Mapping):
            raise MarketStructureStructuralAssessmentValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))
        object.__setattr__(self, "timeframe_context", _normalize_timeframe_context(self.timeframe_context, "timeframe_context"))

        if self.historical_research_only is not True:
            raise MarketStructureStructuralAssessmentValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise MarketStructureStructuralAssessmentValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise MarketStructureStructuralAssessmentValidationError("paper_promotion_eligible must be false.")
        if self.non_operational_declaration != MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_NON_OPERATIONAL_DECLARATION:
            raise MarketStructureStructuralAssessmentValidationError(
                "non_operational_declaration diverges from the structural assessment contract."
            )

        normalized_dimension_summaries: dict[str, MarketStructureStructuralDimensionSummary] = {}
        for dimension_name, summary in self.dimension_summaries.items():
            if isinstance(summary, MarketStructureStructuralDimensionSummary):
                normalized_summary = summary
            elif isinstance(summary, Mapping):
                normalized_summary = MarketStructureStructuralDimensionSummary.from_dict(summary)
            else:
                raise MarketStructureStructuralAssessmentValidationError(
                    "dimension_summaries must contain structural dimension summaries."
                )
            if normalized_summary.dimension_name != _require_str(dimension_name, "dimension_name").lower():
                raise MarketStructureStructuralAssessmentValidationError("dimension name mismatch.")
            if normalized_summary.dimension_name in normalized_dimension_summaries:
                raise MarketStructureStructuralAssessmentValidationError("duplicate dimension summary.")
            normalized_dimension_summaries[normalized_summary.dimension_name] = normalized_summary
        normalized_dimension_summaries = dict(sorted(normalized_dimension_summaries.items()))
        object.__setattr__(self, "dimension_summaries", _freeze_read_only_value(normalized_dimension_summaries))

        derived_structural_state = _derive_structural_state(normalized_dimension_summaries.values())
        if not self.structural_state:
            object.__setattr__(self, "structural_state", derived_structural_state)
        elif self.structural_state != derived_structural_state:
            raise MarketStructureStructuralAssessmentValidationError("structural_state is inconsistent with dimensions.")
        if self.structural_state not in MARKET_STRUCTURE_STRUCTURAL_STATES:
            raise MarketStructureStructuralAssessmentValidationError("structural_state is invalid.")

        if not self.ambiguity_state:
            object.__setattr__(self, "ambiguity_state", _require_str(self.timeframe_context["alignment_state"], "timeframe_context.alignment_state").lower())
        else:
            object.__setattr__(self, "ambiguity_state", _require_str(self.ambiguity_state, "ambiguity_state").lower())
        if self.ambiguity_state not in phase53.MARKET_STRUCTURE_HYPOTHESIS_ALLOWED_ALIGNMENT_STATES:
            raise MarketStructureStructuralAssessmentValidationError("ambiguity_state is invalid.")

        derived_invalidation_state = "present" if any(
            summary.dimension_state == "invalidated" for summary in normalized_dimension_summaries.values()
        ) else "none"
        if not self.invalidation_state:
            object.__setattr__(self, "invalidation_state", derived_invalidation_state)
        elif self.invalidation_state != derived_invalidation_state:
            raise MarketStructureStructuralAssessmentValidationError("invalidation_state is inconsistent with dimensions.")
        if self.invalidation_state not in MARKET_STRUCTURE_STRUCTURAL_INVALIDATION_STATES:
            raise MarketStructureStructuralAssessmentValidationError("invalidation_state is invalid.")

        if not self.assessment_id:
            object.__setattr__(self, "assessment_id", _hash_payload(self._assessment_id_payload()))
        else:
            expected_assessment_id = _hash_payload(self._assessment_id_payload())
            if self.assessment_id != expected_assessment_id:
                raise MarketStructureStructuralAssessmentIntegrityError("assessment_id mismatch.")

        expected_hash = _hash_payload(self._assessment_hash_payload())
        if self.assessment_hash:
            if self.assessment_hash != expected_hash:
                raise MarketStructureStructuralAssessmentIntegrityError("assessment_hash mismatch.")
        else:
            object.__setattr__(self, "assessment_hash", expected_hash)

    def _assessment_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_hash": self.hypothesis_hash,
            "hypothesis_evaluation_hash": self.hypothesis_evaluation_hash,
            "evidence_assessment_id": self.evidence_assessment_id,
            "evidence_assessment_hash": self.evidence_assessment_hash,
            "dataset_hash": self.dataset_hash,
            "contract_hash": self.contract_hash,
            "detection_result_hash": self.detection_result_hash,
            "annotation_collection_hash": self.annotation_collection_hash,
            "dimension_summaries": {
                dimension_name: summary.canonical_payload(include_dimension_hash=False)
                for dimension_name, summary in self.dimension_summaries.items()
            },
            "structural_state": self.structural_state,
            "ambiguity_state": self.ambiguity_state,
            "invalidation_state": self.invalidation_state,
            "timeframe_context": _thaw_read_only_value(self.timeframe_context),
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
            "metadata": _thaw_read_only_value(self.metadata),
        }

    def _assessment_hash_payload(self) -> dict[str, Any]:
        payload = self._assessment_id_payload()
        payload["assessment_id"] = self.assessment_id
        return payload

    def canonical_payload(self, *, include_assessment_id: bool = True, include_assessment_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_hash": self.hypothesis_hash,
            "hypothesis_evaluation_hash": self.hypothesis_evaluation_hash,
            "evidence_assessment_id": self.evidence_assessment_id,
            "evidence_assessment_hash": self.evidence_assessment_hash,
            "dataset_hash": self.dataset_hash,
            "contract_hash": self.contract_hash,
            "detection_result_hash": self.detection_result_hash,
            "annotation_collection_hash": self.annotation_collection_hash,
            "dimension_summaries": {
                dimension_name: summary.as_dict() for dimension_name, summary in self.dimension_summaries.items()
            },
            "structural_state": self.structural_state,
            "ambiguity_state": self.ambiguity_state,
            "invalidation_state": self.invalidation_state,
            "timeframe_context": _thaw_read_only_value(self.timeframe_context),
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
            "metadata": _thaw_read_only_value(self.metadata),
            "created_at_utc": _utc_iso(self.created_at_utc),
        }
        if include_assessment_id:
            payload["assessment_id"] = self.assessment_id
        if include_assessment_hash:
            payload["assessment_hash"] = self.assessment_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_assessment_id=True, include_assessment_hash=True))

    @property
    def audit_record_hash(self) -> str:
        return self.assessment_hash

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureStructuralAssessment":
        if not isinstance(data, Mapping):
            raise MarketStructureStructuralAssessmentValidationError(
                "market structure structural assessment must be a mapping."
            )
        allowed = {
            "schema_version",
            "assessment_id",
            "assessment_hash",
            "hypothesis_id",
            "hypothesis_hash",
            "hypothesis_evaluation_hash",
            "evidence_assessment_id",
            "evidence_assessment_hash",
            "dataset_hash",
            "contract_hash",
            "detection_result_hash",
            "annotation_collection_hash",
            "dimension_summaries",
            "structural_state",
            "ambiguity_state",
            "invalidation_state",
            "timeframe_context",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "non_operational_declaration",
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
            raise MarketStructureStructuralAssessmentValidationError(
                f"market structure structural assessment has invalid fields: {'; '.join(parts)}."
            )
        try:
            dimension_summaries = {
                dimension_name: MarketStructureStructuralDimensionSummary.from_dict(summary)
                for dimension_name, summary in data["dimension_summaries"].items()
            }
            return cls(
                schema_version=data["schema_version"],
                assessment_id=data.get("assessment_id", ""),
                assessment_hash=data.get("assessment_hash", ""),
                hypothesis_id=data["hypothesis_id"],
                hypothesis_hash=data["hypothesis_hash"],
                hypothesis_evaluation_hash=data["hypothesis_evaluation_hash"],
                evidence_assessment_id=data["evidence_assessment_id"],
                evidence_assessment_hash=data["evidence_assessment_hash"],
                dataset_hash=data["dataset_hash"],
                contract_hash=data["contract_hash"],
                detection_result_hash=data["detection_result_hash"],
                annotation_collection_hash=data["annotation_collection_hash"],
                dimension_summaries=dimension_summaries,
                structural_state=data.get("structural_state", ""),
                ambiguity_state=data.get("ambiguity_state", ""),
                invalidation_state=data.get("invalidation_state", ""),
                timeframe_context=data["timeframe_context"],
                historical_research_only=data.get("historical_research_only", True),
                operational_evidence=data.get("operational_evidence", False),
                paper_promotion_eligible=data.get("paper_promotion_eligible", False),
                non_operational_declaration=data.get(
                    "non_operational_declaration",
                    MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_NON_OPERATIONAL_DECLARATION,
                ),
                metadata=data.get("metadata", {}),
                created_at_utc=data["created_at_utc"],
            )
        except KeyError as exc:
            raise MarketStructureStructuralAssessmentValidationError(
                "market structure structural assessment is incomplete."
            ) from exc


def _collect_reason_values(items: Sequence[phase54.MarketStructureEvidenceItem], key: str) -> tuple[str, ...]:
    values: list[str] = []
    for item in items:
        payload = item.metadata.get(key, ())
        if isinstance(payload, str):
            values.append(payload)
        elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
            values.extend(
                _require_str(value, key)
                for value in payload
                if isinstance(value, str) and value.strip()
            )
    return _unique_sorted(values)


def _derive_dimension_state(items: Sequence[phase54.MarketStructureEvidenceItem]) -> str:
    supporting = tuple(item.evidence_id for item in items if item.evidence_role == "supporting")
    contradicting = tuple(item.evidence_id for item in items if item.evidence_role == "contradicting")
    ambiguous = tuple(item.evidence_id for item in items if item.evidence_role == "ambiguous")
    invalidation = tuple(item.evidence_id for item in items if item.evidence_role == "invalidation")
    neutral = tuple(item.evidence_id for item in items if item.evidence_role == "neutral")
    if invalidation:
        return "invalidated"
    if supporting and contradicting:
        return "conflicted"
    if ambiguous and (supporting or contradicting or neutral):
        return "ambiguous"
    if supporting:
        return "supporting"
    if contradicting:
        return "contradicting"
    if ambiguous:
        return "ambiguous"
    if neutral:
        return "neutral"
    return "indeterminate"


def _derive_structural_state(dimension_summaries: Sequence[MarketStructureStructuralDimensionSummary]) -> str:
    states = tuple(summary.dimension_state for summary in dimension_summaries)
    if not states:
        return "empty"
    if "invalidated" in states:
        return "invalidated"
    if "conflicted" in states or ("supporting" in states and "contradicting" in states):
        return "conflicted"
    if "ambiguous" in states:
        return "ambiguous"
    if "indeterminate" in states:
        return "indeterminate"
    if "supporting" in states:
        return "supported"
    if "contradicting" in states:
        return "contradicted"
    if "neutral" in states:
        return "neutral"
    return "empty"


def _build_dimension_summaries(
    items: Sequence[phase54.MarketStructureEvidenceItem],
    *,
    timeframe_context: Mapping[str, Any],
) -> Mapping[str, MarketStructureStructuralDimensionSummary]:
    grouped: dict[str, list[phase54.MarketStructureEvidenceItem]] = {}
    for item in items:
        grouped.setdefault(item.evidence_family, []).append(item)
    summaries: dict[str, MarketStructureStructuralDimensionSummary] = {}
    for dimension_name in MARKET_STRUCTURE_STRUCTURAL_DIMENSIONS:
        dimension_items = tuple(sorted(grouped.get(dimension_name, ()), key=lambda item: item.evidence_id))
        if not dimension_items:
            continue
        summaries[dimension_name] = MarketStructureStructuralDimensionSummary(
            dimension_name=dimension_name,
            dimension_state=_derive_dimension_state(dimension_items),
            supporting_evidence_ids=tuple(item.evidence_id for item in dimension_items if item.evidence_role == "supporting"),
            contradicting_evidence_ids=tuple(item.evidence_id for item in dimension_items if item.evidence_role == "contradicting"),
            ambiguous_evidence_ids=tuple(item.evidence_id for item in dimension_items if item.evidence_role == "ambiguous"),
            invalidation_evidence_ids=tuple(item.evidence_id for item in dimension_items if item.evidence_role == "invalidation"),
            neutral_evidence_ids=tuple(item.evidence_id for item in dimension_items if item.evidence_role == "neutral"),
            provenance_group_ids=tuple(item.provenance_group_id for item in dimension_items),
            timeframe_context=timeframe_context,
            ambiguity_reasons=_collect_reason_values(dimension_items, "ambiguity_reasons"),
            invalidation_reasons=_collect_reason_values(dimension_items, "invalidation_reasons"),
            metadata={},
        )
    return _freeze_read_only_value(dict(sorted(summaries.items())))


def build_market_structure_structural_assessment(
    hypothesis: phase53.MarketStructureHypothesis | Mapping[str, Any],
    evidence_assessment: phase54.MarketStructureEvidenceAssessment | Mapping[str, Any],
    *,
    created_at_utc: datetime | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> MarketStructureStructuralAssessment:
    if isinstance(hypothesis, Mapping):
        hypothesis = phase53.MarketStructureHypothesis.from_dict(hypothesis)
    if isinstance(evidence_assessment, Mapping):
        evidence_assessment = phase54.MarketStructureEvidenceAssessment.from_dict(evidence_assessment)
    if not isinstance(hypothesis, phase53.MarketStructureHypothesis):
        raise MarketStructureStructuralAssessmentValidationError("market structure hypothesis is required.")
    if not isinstance(evidence_assessment, phase54.MarketStructureEvidenceAssessment):
        raise MarketStructureStructuralAssessmentValidationError("market structure evidence assessment is required.")

    verified_hypothesis = phase53.verify_market_structure_hypothesis(hypothesis)
    verified_evidence_assessment = phase54.verify_market_structure_evidence_assessment(evidence_assessment)
    verified_evaluation = phase53.verify_market_structure_hypothesis_evaluation(
        verified_evidence_assessment.hypothesis_evaluation
    )

    matching_hypotheses = tuple(
        item for item in verified_evaluation.hypotheses if item.hypothesis_id == verified_hypothesis.hypothesis_id
    )
    if len(matching_hypotheses) != 1:
        raise MarketStructureStructuralAssessmentValidationError("hypothesis is not part of the evidence assessment.")
    if matching_hypotheses[0].hypothesis_hash != verified_hypothesis.hypothesis_hash:
        raise MarketStructureStructuralAssessmentValidationError("hypothesis hash mismatch.")

    relevant_items = tuple(
        item for item in verified_evidence_assessment.evidence_items if item.source_hypothesis_id == verified_hypothesis.hypothesis_id
    )
    dimension_summaries = _build_dimension_summaries(
        relevant_items,
        timeframe_context=verified_hypothesis.timeframe_context,
    )
    assessment = MarketStructureStructuralAssessment(
        schema_version=MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_SCHEMA_VERSION,
        hypothesis_id=verified_hypothesis.hypothesis_id,
        hypothesis_hash=verified_hypothesis.hypothesis_hash,
        hypothesis_evaluation_hash=verified_evaluation.evaluation_hash,
        evidence_assessment_id=verified_evidence_assessment.assessment_id,
        evidence_assessment_hash=verified_evidence_assessment.assessment_hash,
        dataset_hash=verified_evaluation.dataset_hash,
        contract_hash=verified_evaluation.contract_hash,
        detection_result_hash=verified_evaluation.detection_result_hash,
        annotation_collection_hash=verified_evaluation.annotation_collection_hash,
        dimension_summaries=dimension_summaries,
        structural_state="",
        ambiguity_state=verified_hypothesis.timeframe_context["alignment_state"],
        invalidation_state="",
        timeframe_context=verified_hypothesis.timeframe_context,
        historical_research_only=True,
        operational_evidence=False,
        paper_promotion_eligible=False,
        non_operational_declaration=MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_NON_OPERATIONAL_DECLARATION,
        metadata=metadata or {},
        created_at_utc=created_at_utc or verified_evidence_assessment.created_at_utc,
    )
    return verify_market_structure_structural_assessment(assessment)


def verify_market_structure_structural_assessment(
    assessment: MarketStructureStructuralAssessment,
) -> MarketStructureStructuralAssessment:
    if not isinstance(assessment, MarketStructureStructuralAssessment):
        raise MarketStructureStructuralAssessmentValidationError("market structure structural assessment is required.")
    expected_id = _hash_payload(assessment._assessment_id_payload())
    if assessment.assessment_id != expected_id:
        raise MarketStructureStructuralAssessmentIntegrityError("assessment_id mismatch.")
    expected_hash = _hash_payload(assessment._assessment_hash_payload())
    if assessment.assessment_hash != expected_hash:
        raise MarketStructureStructuralAssessmentIntegrityError("assessment_hash mismatch.")
    return assessment


def market_structure_structural_assessment_to_dict(
    assessment: MarketStructureStructuralAssessment,
) -> dict[str, Any]:
    if not isinstance(assessment, MarketStructureStructuralAssessment):
        raise MarketStructureStructuralAssessmentValidationError("market structure structural assessment is required.")
    return assessment.as_dict()


def market_structure_structural_assessment_from_dict(
    data: Mapping[str, Any],
) -> MarketStructureStructuralAssessment:
    return MarketStructureStructuralAssessment.from_dict(data)


__all__ = [
    "MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_ID",
    "MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_NON_OPERATIONAL_DECLARATION",
    "MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_SCHEMA_VERSION",
    "MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_VERSION",
    "MARKET_STRUCTURE_STRUCTURAL_DIMENSION_STATES",
    "MARKET_STRUCTURE_STRUCTURAL_DIMENSIONS",
    "MARKET_STRUCTURE_STRUCTURAL_INVALIDATION_STATES",
    "MARKET_STRUCTURE_STRUCTURAL_STATES",
    "MarketStructureStructuralAssessment",
    "MarketStructureStructuralAssessmentError",
    "MarketStructureStructuralAssessmentIntegrityError",
    "MarketStructureStructuralAssessmentValidationError",
    "MarketStructureStructuralDimensionSummary",
    "build_market_structure_structural_assessment",
    "market_structure_structural_assessment_from_dict",
    "market_structure_structural_assessment_to_dict",
    "verify_market_structure_structural_assessment",
]
