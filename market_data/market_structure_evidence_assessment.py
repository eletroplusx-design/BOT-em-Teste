from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value

from .errors import HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError
from . import market_structure_hypothesis_evaluation as phase53

MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_SCHEMA_VERSION = 1
MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_ID = "market_structure_evidence_assessment"
MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_VERSION = "phase54_market_structure_evidence_assessment_v1"
MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_NON_OPERATIONAL_DECLARATION = (
    "This assessment is research-only and does not authorize replay, backtest, walk-forward, performance "
    "evaluation, ranking, paper trading, live trading, exchange connectivity, execution, or order submission."
)

MARKET_STRUCTURE_EVIDENCE_SOURCE_TYPES: tuple[str, ...] = ("event", "annotation", "derived_context")
MARKET_STRUCTURE_EVIDENCE_FAMILIES: tuple[str, ...] = (
    "trend",
    "structure",
    "liquidity",
    "range",
    "displacement",
    "retest",
    "timeframe",
    "ambiguity",
    "invalidation",
)
MARKET_STRUCTURE_EVIDENCE_ROLES: tuple[str, ...] = (
    "supporting",
    "contradicting",
    "ambiguous",
    "invalidation",
    "neutral",
)
MARKET_STRUCTURE_EVIDENCE_INDEPENDENCE_STATES: tuple[str, ...] = (
    "independent",
    "redundant",
    "partially_redundant",
    "duplicate",
    "unknown",
)
MARKET_STRUCTURE_EVIDENCE_TEMPORAL_VALIDITY_STATES: tuple[str, ...] = (
    "valid",
    "expired",
    "future",
    "indeterminate",
    "invalidated",
)
MARKET_STRUCTURE_EVIDENCE_AMBIGUITY_STATES: tuple[str, ...] = (
    "clear",
    "ambiguous",
    "conflicted",
    "unknown",
)


class MarketStructureEvidenceAssessmentError(HistoricalDataError):
    pass


class MarketStructureEvidenceAssessmentValidationError(
    MarketStructureEvidenceAssessmentError,
    HistoricalDataValidationError,
):
    pass


class MarketStructureEvidenceAssessmentIntegrityError(
    MarketStructureEvidenceAssessmentError,
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
        raise MarketStructureEvidenceAssessmentValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketStructureEvidenceAssessmentValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise MarketStructureEvidenceAssessmentValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise MarketStructureEvidenceAssessmentValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise MarketStructureEvidenceAssessmentValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise MarketStructureEvidenceAssessmentValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise MarketStructureEvidenceAssessmentValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise MarketStructureEvidenceAssessmentValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketStructureEvidenceAssessmentValidationError(f"{field_name} must be timezone-aware UTC datetime.")
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


def _require_str_sequence(value: Any, field_name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (Sequence, set, frozenset)):
        raise MarketStructureEvidenceAssessmentValidationError(f"{field_name} must be a sequence of strings.")
    normalized = tuple(_require_str(item, field_name) for item in value)
    if not allow_empty and not normalized:
        raise MarketStructureEvidenceAssessmentValidationError(f"{field_name} must not be empty.")
    return normalized


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MarketStructureEvidenceAssessmentValidationError(f"{field_name} must be a mapping.")
    return value


def _event_kind_from_reference(reference: str) -> tuple[str, str]:
    if "::" not in reference:
        raise MarketStructureEvidenceAssessmentValidationError("event reference must include its event kind.")
    annotation_id, event_kind = reference.rsplit("::", 1)
    if not annotation_id or not event_kind:
        raise MarketStructureEvidenceAssessmentValidationError("event reference is incomplete.")
    return annotation_id, event_kind


def _family_for_event_kind(event_kind: str) -> str:
    if event_kind in {
        "confirmed_swing_high",
        "confirmed_swing_low",
        "candidate_swing_high",
        "candidate_swing_low",
        "bullish_structure",
        "bearish_structure",
        "lateral_structure",
        "ambiguous_structure",
        "indeterminate_structure",
        "valid_bos",
        "failed_bos",
        "valid_choch",
        "failed_choch",
    }:
        return "structure"
    if event_kind in {
        "equal_highs",
        "equal_lows",
        "internal_liquidity",
        "external_liquidity",
        "protected_high",
        "protected_low",
        "liquidity_sweep",
        "failed_sweep",
        "false_break",
        "breakout",
    }:
        return "liquidity"
    if event_kind in {"valid_displacement", "insufficient_displacement"}:
        return "displacement"
    if event_kind in {"valid_retest", "failed_retest"}:
        return "retest"
    if event_kind in {
        "valid_trading_range",
        "unclassified_range",
        "candidate_accumulation",
        "candidate_distribution",
        "candidate_reaccumulation",
        "candidate_redistribution",
    }:
        return "range"
    raise MarketStructureEvidenceAssessmentValidationError(
        f"unsupported market structure event kind: {event_kind}."
    )


def _family_for_hypothesis_type(hypothesis_type: str) -> str:
    if hypothesis_type in {"Bullish Continuation", "Bearish Continuation"}:
        return "trend"
    if hypothesis_type in {
        "Accumulation Candidate",
        "Distribution Candidate",
        "Reaccumulation Candidate",
        "Redistribution Candidate",
    }:
        return "range"
    return "ambiguity"


def _role_for_alignment_state(alignment_state: str) -> str:
    mapping = {
        "aligned": "supporting",
        "conflicted": "contradicting",
        "neutral": "neutral",
        "indeterminate": "ambiguous",
    }
    if alignment_state not in mapping:
        raise MarketStructureEvidenceAssessmentValidationError("alignment_state is invalid.")
    return mapping[alignment_state]


def _state_for_evidence_role(
    *,
    evidence_role: str,
    hypothesis: phase53.MarketStructureHypothesis,
    alignment_state: str | None = None,
) -> str:
    if evidence_role == "invalidation" or hypothesis.status == "invalidated" or hypothesis.invalidation_reasons:
        return "invalidated"
    if alignment_state == "conflicted" or evidence_role == "contradicting":
        return "conflicted" if evidence_role == "contradicting" and hypothesis.ambiguity_reasons else "conflicted"
    if evidence_role == "ambiguous" or hypothesis.status == "ambiguous" or hypothesis.ambiguity_reasons:
        return "ambiguous"
    return "clear"


def _provenance_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    source_type = item["evidence_source_type"]
    payload: dict[str, Any] = {
        "evidence_source_type": source_type,
        "source_event_id": item["source_event_id"] if source_type == "event" else "",
        "source_annotation_id": item["source_annotation_id"] if source_type in {"event", "annotation"} else "",
        "dataset_hash": item["dataset_hash"],
        "contract_hash": item["contract_hash"],
        "detection_result_hash": item["detection_result_hash"],
        "annotation_collection_hash": item["annotation_collection_hash"],
        "evidence_family": item["evidence_family"] if source_type == "derived_context" else "",
    }
    if source_type == "derived_context":
        payload["source_hypothesis_id"] = item["source_hypothesis_id"]
        payload["evidence_role"] = item["evidence_role"]
    return payload


def _evidence_id_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "evidence_source_type": item["evidence_source_type"],
        "source_event_id": item["source_event_id"],
        "source_annotation_id": item["source_annotation_id"],
        "source_hypothesis_id": item["source_hypothesis_id"],
        "dataset_hash": item["dataset_hash"],
        "contract_hash": item["contract_hash"],
        "detection_result_hash": item["detection_result_hash"],
        "annotation_collection_hash": item["annotation_collection_hash"],
        "hypothesis_evaluation_hash": item["hypothesis_evaluation_hash"],
        "evidence_family": item["evidence_family"],
        "evidence_role": item["evidence_role"],
        "observed_at": item["observed_at"],
        "effective_at": item["effective_at"],
        "valid_from": item["valid_from"],
        "valid_until": item["valid_until"],
        "provenance_group_id": item["provenance_group_id"],
        "metadata": _thaw_read_only_value(item["metadata"]),
    }
    return payload


def _normalize_evidence_item_payload(payload: Mapping[str, Any], *, field_name: str) -> dict[str, Any]:
    _require_mapping(payload, field_name)
    required_keys = {
        "evidence_id",
        "evidence_source_type",
        "source_event_id",
        "source_annotation_id",
        "source_hypothesis_id",
        "dataset_hash",
        "contract_hash",
        "detection_result_hash",
        "annotation_collection_hash",
        "hypothesis_evaluation_hash",
        "evidence_family",
        "evidence_role",
        "observed_at",
        "effective_at",
        "valid_from",
        "valid_until",
        "provenance_group_id",
        "independence_state",
        "temporal_validity_state",
        "ambiguity_state",
        "metadata",
    }
    extra = sorted(set(payload) - required_keys)
    missing = sorted(required_keys - set(payload))
    if extra or missing:
        parts: list[str] = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected {', '.join(extra)}")
        raise MarketStructureEvidenceAssessmentValidationError(
            f"{field_name} has invalid fields: {'; '.join(parts)}."
        )
    return dict(payload)


def _normalize_provenance_payload(payload: Mapping[str, Any], *, field_name: str) -> dict[str, Any]:
    _require_mapping(payload, field_name)
    required_keys = {
        "provenance_group_id",
        "evidence_ids",
        "evidence_source_types",
        "source_event_ids",
        "source_annotation_ids",
        "source_hypothesis_ids",
        "evidence_families",
        "evidence_roles",
        "group_state",
        "metadata",
        "provenance_hash",
    }
    extra = sorted(set(payload) - required_keys)
    missing = sorted(required_keys - set(payload))
    if extra or missing:
        parts: list[str] = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected {', '.join(extra)}")
        raise MarketStructureEvidenceAssessmentValidationError(
            f"{field_name} has invalid fields: {'; '.join(parts)}."
        )
    return dict(payload)


def _normalize_family_summary_payload(payload: Mapping[str, Any], *, field_name: str) -> dict[str, Any]:
    _require_mapping(payload, field_name)
    required_keys = {
        "evidence_family",
        "evidence_ids",
        "supporting_evidence_ids",
        "contradicting_evidence_ids",
        "ambiguous_evidence_ids",
        "invalidation_evidence_ids",
        "neutral_evidence_ids",
        "family_state",
        "conflict_state",
        "metadata",
        "family_hash",
    }
    extra = sorted(set(payload) - required_keys)
    missing = sorted(required_keys - set(payload))
    if extra or missing:
        parts: list[str] = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected {', '.join(extra)}")
        raise MarketStructureEvidenceAssessmentValidationError(
            f"{field_name} has invalid fields: {'; '.join(parts)}."
        )
    return dict(payload)


@dataclass(frozen=True, slots=True)
class MarketStructureEvidenceItem:
    evidence_id: str = ""
    evidence_source_type: str = ""
    source_event_id: str = ""
    source_annotation_id: str = ""
    source_hypothesis_id: str = ""
    dataset_hash: str = ""
    contract_hash: str = ""
    detection_result_hash: str = ""
    annotation_collection_hash: str = ""
    hypothesis_evaluation_hash: str = ""
    evidence_family: str = ""
    evidence_role: str = "neutral"
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    effective_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    provenance_group_id: str = ""
    independence_state: str = "unknown"
    temporal_validity_state: str = "indeterminate"
    ambiguity_state: str = "unknown"
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_source_type", _require_str(self.evidence_source_type, "evidence_source_type").lower())
        if self.evidence_source_type not in MARKET_STRUCTURE_EVIDENCE_SOURCE_TYPES:
            raise MarketStructureEvidenceAssessmentValidationError("evidence_source_type is invalid.")
        object.__setattr__(self, "source_event_id", _require_str(self.source_event_id, "source_event_id") if self.source_event_id else "")
        object.__setattr__(self, "source_annotation_id", _require_str(self.source_annotation_id, "source_annotation_id") if self.source_annotation_id else "")
        object.__setattr__(self, "source_hypothesis_id", _require_str(self.source_hypothesis_id, "source_hypothesis_id"))
        if self.evidence_source_type == "event" and not self.source_event_id:
            raise MarketStructureEvidenceAssessmentValidationError("source_event_id is required for event evidence.")
        if self.evidence_source_type == "annotation" and not self.source_annotation_id:
            raise MarketStructureEvidenceAssessmentValidationError("source_annotation_id is required for annotation evidence.")
        if self.evidence_source_type == "derived_context" and not self.source_hypothesis_id:
            raise MarketStructureEvidenceAssessmentValidationError("source_hypothesis_id is required for derived context evidence.")
        object.__setattr__(self, "dataset_hash", _require_hex_digest(self.dataset_hash, "dataset_hash"))
        object.__setattr__(self, "contract_hash", _require_hex_digest(self.contract_hash, "contract_hash"))
        object.__setattr__(self, "detection_result_hash", _require_hex_digest(self.detection_result_hash, "detection_result_hash"))
        object.__setattr__(self, "annotation_collection_hash", _require_hex_digest(self.annotation_collection_hash, "annotation_collection_hash"))
        object.__setattr__(self, "hypothesis_evaluation_hash", _require_hex_digest(self.hypothesis_evaluation_hash, "hypothesis_evaluation_hash"))
        object.__setattr__(self, "evidence_family", _require_str(self.evidence_family, "evidence_family").lower())
        if self.evidence_family not in MARKET_STRUCTURE_EVIDENCE_FAMILIES:
            raise MarketStructureEvidenceAssessmentValidationError("evidence_family is invalid.")
        object.__setattr__(self, "evidence_role", _require_str(self.evidence_role, "evidence_role").lower())
        if self.evidence_role not in MARKET_STRUCTURE_EVIDENCE_ROLES:
            raise MarketStructureEvidenceAssessmentValidationError("evidence_role is invalid.")
        object.__setattr__(self, "observed_at", _require_utc_datetime(self.observed_at, "observed_at"))
        object.__setattr__(self, "effective_at", _require_utc_datetime(self.effective_at, "effective_at"))
        if self.valid_from is None:
            object.__setattr__(self, "valid_from", self.effective_at)
        else:
            object.__setattr__(self, "valid_from", _require_utc_datetime(self.valid_from, "valid_from"))
        if self.valid_until is not None:
            object.__setattr__(self, "valid_until", _require_utc_datetime(self.valid_until, "valid_until"))
        if self.valid_until is not None and self.valid_until < self.valid_from:
            raise MarketStructureEvidenceAssessmentValidationError("valid_until cannot precede valid_from.")
        object.__setattr__(self, "independence_state", _require_str(self.independence_state, "independence_state").lower())
        if self.independence_state not in MARKET_STRUCTURE_EVIDENCE_INDEPENDENCE_STATES:
            raise MarketStructureEvidenceAssessmentValidationError("independence_state is invalid.")
        object.__setattr__(self, "temporal_validity_state", _require_str(self.temporal_validity_state, "temporal_validity_state").lower())
        if self.temporal_validity_state not in MARKET_STRUCTURE_EVIDENCE_TEMPORAL_VALIDITY_STATES:
            raise MarketStructureEvidenceAssessmentValidationError("temporal_validity_state is invalid.")
        object.__setattr__(self, "ambiguity_state", _require_str(self.ambiguity_state, "ambiguity_state").lower())
        if self.ambiguity_state not in MARKET_STRUCTURE_EVIDENCE_AMBIGUITY_STATES:
            raise MarketStructureEvidenceAssessmentValidationError("ambiguity_state is invalid.")
        if not isinstance(self.metadata, Mapping):
            raise MarketStructureEvidenceAssessmentValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))

        if not self.provenance_group_id:
            object.__setattr__(self, "provenance_group_id", _hash_payload(_provenance_payload(self._base_payload())))
        else:
            expected_group_id = _hash_payload(_provenance_payload(self._base_payload()))
            if self.provenance_group_id != expected_group_id:
                raise MarketStructureEvidenceAssessmentIntegrityError("provenance_group_id mismatch.")

        if not self.evidence_id:
            object.__setattr__(self, "evidence_id", _hash_payload(self._evidence_id_payload()))
        else:
            expected_evidence_id = _hash_payload(self._evidence_id_payload())
            if self.evidence_id != expected_evidence_id:
                raise MarketStructureEvidenceAssessmentIntegrityError("evidence_id mismatch.")

    def _base_payload(self) -> dict[str, Any]:
        return {
            "evidence_source_type": self.evidence_source_type,
            "source_event_id": self.source_event_id,
            "source_annotation_id": self.source_annotation_id,
            "source_hypothesis_id": self.source_hypothesis_id,
            "dataset_hash": self.dataset_hash,
            "contract_hash": self.contract_hash,
            "detection_result_hash": self.detection_result_hash,
            "annotation_collection_hash": self.annotation_collection_hash,
            "hypothesis_evaluation_hash": self.hypothesis_evaluation_hash,
            "evidence_family": self.evidence_family,
            "evidence_role": self.evidence_role,
            "observed_at": _utc_iso(self.observed_at),
            "effective_at": _utc_iso(self.effective_at),
            "valid_from": _utc_iso(self.valid_from) if self.valid_from else None,
            "valid_until": _utc_iso(self.valid_until) if self.valid_until else None,
            "provenance_group_id": self.provenance_group_id,
            "metadata": _thaw_read_only_value(self.metadata),
        }

    def _evidence_id_payload(self) -> dict[str, Any]:
        payload = self._base_payload()
        payload["provenance_group_id"] = self.provenance_group_id
        return payload

    def canonical_payload(
        self,
        *,
        include_evidence_id: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "evidence_source_type": self.evidence_source_type,
            "source_event_id": self.source_event_id,
            "source_annotation_id": self.source_annotation_id,
            "source_hypothesis_id": self.source_hypothesis_id,
            "dataset_hash": self.dataset_hash,
            "contract_hash": self.contract_hash,
            "detection_result_hash": self.detection_result_hash,
            "annotation_collection_hash": self.annotation_collection_hash,
            "hypothesis_evaluation_hash": self.hypothesis_evaluation_hash,
            "evidence_family": self.evidence_family,
            "evidence_role": self.evidence_role,
            "observed_at": _utc_iso(self.observed_at),
            "effective_at": _utc_iso(self.effective_at),
            "valid_from": _utc_iso(self.valid_from) if self.valid_from else None,
            "valid_until": _utc_iso(self.valid_until) if self.valid_until else None,
            "provenance_group_id": self.provenance_group_id,
            "independence_state": self.independence_state,
            "temporal_validity_state": self.temporal_validity_state,
            "ambiguity_state": self.ambiguity_state,
            "metadata": _thaw_read_only_value(self.metadata),
        }
        if include_evidence_id:
            payload["evidence_id"] = self.evidence_id
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_evidence_id=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureEvidenceItem":
        mapping = _normalize_evidence_item_payload(data, field_name="market structure evidence item")
        try:
            return cls(
                evidence_id=mapping.get("evidence_id", ""),
                evidence_source_type=mapping["evidence_source_type"],
                source_event_id=mapping.get("source_event_id", ""),
                source_annotation_id=mapping.get("source_annotation_id", ""),
                source_hypothesis_id=mapping["source_hypothesis_id"],
                dataset_hash=mapping["dataset_hash"],
                contract_hash=mapping["contract_hash"],
                detection_result_hash=mapping["detection_result_hash"],
                annotation_collection_hash=mapping["annotation_collection_hash"],
                hypothesis_evaluation_hash=mapping["hypothesis_evaluation_hash"],
                evidence_family=mapping["evidence_family"],
                evidence_role=mapping["evidence_role"],
                observed_at=mapping["observed_at"],
                effective_at=mapping["effective_at"],
                valid_from=mapping.get("valid_from"),
                valid_until=mapping.get("valid_until"),
                provenance_group_id=mapping.get("provenance_group_id", ""),
                independence_state=mapping.get("independence_state", "unknown"),
                temporal_validity_state=mapping.get("temporal_validity_state", "indeterminate"),
                ambiguity_state=mapping.get("ambiguity_state", "unknown"),
                metadata=mapping.get("metadata", {}),
            )
        except KeyError as exc:
            raise MarketStructureEvidenceAssessmentValidationError("market structure evidence item is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class MarketStructureEvidenceProvenance:
    provenance_group_id: str = ""
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_source_types: tuple[str, ...] = field(default_factory=tuple)
    source_event_ids: tuple[str, ...] = field(default_factory=tuple)
    source_annotation_ids: tuple[str, ...] = field(default_factory=tuple)
    source_hypothesis_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_families: tuple[str, ...] = field(default_factory=tuple)
    evidence_roles: tuple[str, ...] = field(default_factory=tuple)
    group_state: str = "unknown"
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    provenance_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "provenance_group_id", _require_str(self.provenance_group_id, "provenance_group_id"))
        object.__setattr__(self, "evidence_ids", _require_str_sequence(self.evidence_ids, "evidence_ids"))
        object.__setattr__(self, "evidence_source_types", _require_str_sequence(self.evidence_source_types, "evidence_source_types"))
        object.__setattr__(self, "source_event_ids", _require_str_sequence(self.source_event_ids, "source_event_ids", allow_empty=True))
        object.__setattr__(self, "source_annotation_ids", _require_str_sequence(self.source_annotation_ids, "source_annotation_ids", allow_empty=True))
        object.__setattr__(self, "source_hypothesis_ids", _require_str_sequence(self.source_hypothesis_ids, "source_hypothesis_ids", allow_empty=True))
        object.__setattr__(self, "evidence_families", _require_str_sequence(self.evidence_families, "evidence_families"))
        object.__setattr__(self, "evidence_roles", _require_str_sequence(self.evidence_roles, "evidence_roles"))
        object.__setattr__(self, "group_state", _require_str(self.group_state, "group_state").lower())
        if self.group_state not in MARKET_STRUCTURE_EVIDENCE_INDEPENDENCE_STATES:
            raise MarketStructureEvidenceAssessmentValidationError("group_state is invalid.")
        if not isinstance(self.metadata, Mapping):
            raise MarketStructureEvidenceAssessmentValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))
        if not self.provenance_hash:
            object.__setattr__(self, "provenance_hash", _hash_payload(self.canonical_payload(include_provenance_hash=False)))
        else:
            expected_hash = _hash_payload(self.canonical_payload(include_provenance_hash=False))
            if self.provenance_hash != expected_hash:
                raise MarketStructureEvidenceAssessmentIntegrityError("provenance_hash mismatch.")

    def canonical_payload(self, *, include_provenance_hash: bool = True) -> dict[str, Any]:
        payload = {
            "provenance_group_id": self.provenance_group_id,
            "evidence_ids": self.evidence_ids,
            "evidence_source_types": self.evidence_source_types,
            "source_event_ids": self.source_event_ids,
            "source_annotation_ids": self.source_annotation_ids,
            "source_hypothesis_ids": self.source_hypothesis_ids,
            "evidence_families": self.evidence_families,
            "evidence_roles": self.evidence_roles,
            "group_state": self.group_state,
            "metadata": _thaw_read_only_value(self.metadata),
        }
        if include_provenance_hash:
            payload["provenance_hash"] = self.provenance_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_provenance_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureEvidenceProvenance":
        mapping = _normalize_provenance_payload(data, field_name="market structure evidence provenance")
        try:
            return cls(
                provenance_group_id=mapping["provenance_group_id"],
                evidence_ids=tuple(mapping["evidence_ids"]),
                evidence_source_types=tuple(mapping["evidence_source_types"]),
                source_event_ids=tuple(mapping["source_event_ids"]),
                source_annotation_ids=tuple(mapping["source_annotation_ids"]),
                source_hypothesis_ids=tuple(mapping["source_hypothesis_ids"]),
                evidence_families=tuple(mapping["evidence_families"]),
                evidence_roles=tuple(mapping["evidence_roles"]),
                group_state=mapping["group_state"],
                metadata=mapping.get("metadata", {}),
                provenance_hash=mapping.get("provenance_hash", ""),
            )
        except KeyError as exc:
            raise MarketStructureEvidenceAssessmentValidationError(
                "market structure evidence provenance is incomplete."
            ) from exc


@dataclass(frozen=True, slots=True)
class MarketStructureEvidenceFamilySummary:
    evidence_family: str
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    supporting_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    contradicting_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    ambiguous_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    invalidation_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    neutral_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    family_state: str = "unobserved"
    conflict_state: str = "none"
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    family_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_family", _require_str(self.evidence_family, "evidence_family").lower())
        if self.evidence_family not in MARKET_STRUCTURE_EVIDENCE_FAMILIES:
            raise MarketStructureEvidenceAssessmentValidationError("evidence_family is invalid.")
        object.__setattr__(self, "evidence_ids", _require_str_sequence(self.evidence_ids, "evidence_ids"))
        object.__setattr__(self, "supporting_evidence_ids", _require_str_sequence(self.supporting_evidence_ids, "supporting_evidence_ids", allow_empty=True))
        object.__setattr__(self, "contradicting_evidence_ids", _require_str_sequence(self.contradicting_evidence_ids, "contradicting_evidence_ids", allow_empty=True))
        object.__setattr__(self, "ambiguous_evidence_ids", _require_str_sequence(self.ambiguous_evidence_ids, "ambiguous_evidence_ids", allow_empty=True))
        object.__setattr__(self, "invalidation_evidence_ids", _require_str_sequence(self.invalidation_evidence_ids, "invalidation_evidence_ids", allow_empty=True))
        object.__setattr__(self, "neutral_evidence_ids", _require_str_sequence(self.neutral_evidence_ids, "neutral_evidence_ids", allow_empty=True))
        object.__setattr__(self, "family_state", _require_str(self.family_state, "family_state").lower())
        object.__setattr__(self, "conflict_state", _require_str(self.conflict_state, "conflict_state").lower())
        if self.conflict_state not in {"none", "present"}:
            raise MarketStructureEvidenceAssessmentValidationError("conflict_state is invalid.")
        if self.family_state not in {"supported", "contradicted", "conflicted", "ambiguous", "invalidated", "neutral", "unobserved"}:
            raise MarketStructureEvidenceAssessmentValidationError("family_state is invalid.")
        if not isinstance(self.metadata, Mapping):
            raise MarketStructureEvidenceAssessmentValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))
        if not self.family_hash:
            object.__setattr__(self, "family_hash", _hash_payload(self.canonical_payload(include_family_hash=False)))
        else:
            expected_hash = _hash_payload(self.canonical_payload(include_family_hash=False))
            if self.family_hash != expected_hash:
                raise MarketStructureEvidenceAssessmentIntegrityError("family_hash mismatch.")

    def canonical_payload(self, *, include_family_hash: bool = True) -> dict[str, Any]:
        payload = {
            "evidence_family": self.evidence_family,
            "evidence_ids": self.evidence_ids,
            "supporting_evidence_ids": self.supporting_evidence_ids,
            "contradicting_evidence_ids": self.contradicting_evidence_ids,
            "ambiguous_evidence_ids": self.ambiguous_evidence_ids,
            "invalidation_evidence_ids": self.invalidation_evidence_ids,
            "neutral_evidence_ids": self.neutral_evidence_ids,
            "family_state": self.family_state,
            "conflict_state": self.conflict_state,
            "metadata": _thaw_read_only_value(self.metadata),
        }
        if include_family_hash:
            payload["family_hash"] = self.family_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_family_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureEvidenceFamilySummary":
        mapping = _normalize_family_summary_payload(data, field_name="market structure evidence family summary")
        try:
            return cls(
                evidence_family=mapping["evidence_family"],
                evidence_ids=tuple(mapping["evidence_ids"]),
                supporting_evidence_ids=tuple(mapping["supporting_evidence_ids"]),
                contradicting_evidence_ids=tuple(mapping["contradicting_evidence_ids"]),
                ambiguous_evidence_ids=tuple(mapping["ambiguous_evidence_ids"]),
                invalidation_evidence_ids=tuple(mapping["invalidation_evidence_ids"]),
                neutral_evidence_ids=tuple(mapping["neutral_evidence_ids"]),
                family_state=mapping["family_state"],
                conflict_state=mapping["conflict_state"],
                metadata=mapping.get("metadata", {}),
                family_hash=mapping.get("family_hash", ""),
            )
        except KeyError as exc:
            raise MarketStructureEvidenceAssessmentValidationError(
                "market structure evidence family summary is incomplete."
            ) from exc


def _item_for_hypothesis(
    hypothesis: phase53.MarketStructureHypothesis,
    *,
    hypothesis_evaluation_hash: str,
    source_source_type: str,
    source_event_id: str = "",
    source_annotation_id: str = "",
    evidence_family: str,
    evidence_role: str,
    metadata: Mapping[str, Any] | None = None,
    observed_at: datetime | None = None,
    effective_at: datetime | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> MarketStructureEvidenceItem:
    if source_source_type not in MARKET_STRUCTURE_EVIDENCE_SOURCE_TYPES:
        raise MarketStructureEvidenceAssessmentValidationError("evidence_source_type is invalid.")
    if observed_at is None:
        observed_at = hypothesis.observed_at
    if effective_at is None:
        effective_at = hypothesis.effective_at
    if valid_from is None:
        valid_from = effective_at
    source_annotation_id = source_annotation_id or (source_event_id.rsplit("::", 1)[0] if source_event_id else "")
    item = MarketStructureEvidenceItem(
        evidence_source_type=source_source_type,
        source_event_id=source_event_id,
        source_annotation_id=source_annotation_id,
        source_hypothesis_id=hypothesis.hypothesis_id,
        dataset_hash=hypothesis.dataset_hash,
        contract_hash=hypothesis.contract_hash,
        detection_result_hash=hypothesis.detection_result_hash,
        annotation_collection_hash=hypothesis.annotation_collection_hash,
        hypothesis_evaluation_hash=hypothesis_evaluation_hash,
        evidence_family=evidence_family,
        evidence_role=evidence_role,
        observed_at=observed_at,
        effective_at=effective_at,
        valid_from=valid_from,
        valid_until=valid_until,
        provenance_group_id="",
        independence_state="unknown",
        temporal_validity_state="indeterminate",
        ambiguity_state="unknown",
        metadata=metadata or {},
    )
    return item


def _items_for_hypothesis(
    hypothesis: phase53.MarketStructureHypothesis,
    *,
    hypothesis_evaluation_hash: str,
) -> tuple[MarketStructureEvidenceItem, ...]:
    items: list[MarketStructureEvidenceItem] = []
    for event_reference in hypothesis.supporting_event_ids:
        annotation_id, event_kind = _event_kind_from_reference(event_reference)
        items.append(
            _item_for_hypothesis(
                hypothesis,
                hypothesis_evaluation_hash=hypothesis_evaluation_hash,
                source_source_type="event",
                source_event_id=event_reference,
                source_annotation_id=annotation_id,
                evidence_family=_family_for_event_kind(event_kind),
                evidence_role="supporting",
                metadata={"event_kind": event_kind, "hypothesis_type": hypothesis.hypothesis_type},
            )
        )
    for event_reference in hypothesis.contradicting_event_ids:
        annotation_id, event_kind = _event_kind_from_reference(event_reference)
        items.append(
            _item_for_hypothesis(
                hypothesis,
                hypothesis_evaluation_hash=hypothesis_evaluation_hash,
                source_source_type="event",
                source_event_id=event_reference,
                source_annotation_id=annotation_id,
                evidence_family=_family_for_event_kind(event_kind),
                evidence_role="contradicting",
                metadata={"event_kind": event_kind, "hypothesis_type": hypothesis.hypothesis_type},
            )
        )
    for annotation_id in hypothesis.supporting_annotation_ids:
        items.append(
            _item_for_hypothesis(
                hypothesis,
                hypothesis_evaluation_hash=hypothesis_evaluation_hash,
                source_source_type="annotation",
                source_annotation_id=annotation_id,
                evidence_family=_family_for_hypothesis_type(hypothesis.hypothesis_type),
                evidence_role="supporting",
                metadata={"hypothesis_type": hypothesis.hypothesis_type},
            )
        )
    for annotation_id in hypothesis.contradicting_annotation_ids:
        items.append(
            _item_for_hypothesis(
                hypothesis,
                hypothesis_evaluation_hash=hypothesis_evaluation_hash,
                source_source_type="annotation",
                source_annotation_id=annotation_id,
                evidence_family=_family_for_hypothesis_type(hypothesis.hypothesis_type),
                evidence_role="contradicting",
                metadata={"hypothesis_type": hypothesis.hypothesis_type},
            )
        )
    if hypothesis.timeframe_context:
        alignment_state = _require_str(hypothesis.timeframe_context["alignment_state"], "alignment_state").lower()
        items.append(
            _item_for_hypothesis(
                hypothesis,
                hypothesis_evaluation_hash=hypothesis_evaluation_hash,
                source_source_type="derived_context",
                evidence_family="timeframe",
                evidence_role=_role_for_alignment_state(alignment_state),
                metadata={"timeframe_context": hypothesis.timeframe_context},
            )
        )
    if hypothesis.ambiguity_reasons:
        items.append(
            _item_for_hypothesis(
                hypothesis,
                hypothesis_evaluation_hash=hypothesis_evaluation_hash,
                source_source_type="derived_context",
                evidence_family="ambiguity",
                evidence_role="ambiguous",
                metadata={"ambiguity_reasons": hypothesis.ambiguity_reasons},
            )
        )
    if hypothesis.invalidation_reasons:
        items.append(
            _item_for_hypothesis(
                hypothesis,
                hypothesis_evaluation_hash=hypothesis_evaluation_hash,
                source_source_type="derived_context",
                evidence_family="invalidation",
                evidence_role="invalidation",
                metadata={"invalidation_reasons": hypothesis.invalidation_reasons},
            )
        )
    if not items:
        items.append(
            _item_for_hypothesis(
                hypothesis,
                hypothesis_evaluation_hash=hypothesis_evaluation_hash,
                source_source_type="derived_context",
                evidence_family="ambiguity",
                evidence_role="neutral",
                metadata={"empty_evidence": True},
            )
        )
    return tuple(items)


def _temporal_state_for_item(item: MarketStructureEvidenceItem, *, evaluated_at_utc: datetime) -> str:
    if item.evidence_role == "invalidation" or item.evidence_family == "invalidation":
        return "invalidated"
    if item.observed_at > evaluated_at_utc or item.effective_at > evaluated_at_utc:
        return "future"
    if item.valid_from and item.valid_from > evaluated_at_utc:
        return "future"
    if item.valid_until is not None and item.valid_until < evaluated_at_utc:
        return "expired"
    return "valid"


def _ordered_items(items: Sequence[MarketStructureEvidenceItem]) -> tuple[MarketStructureEvidenceItem, ...]:
    return tuple(
        sorted(
            items,
            key=lambda item: (
                item.evidence_id,
                item.evidence_source_type,
                item.evidence_family,
                item.evidence_role,
            ),
        )
    )


def _build_provenance_groups(items: Sequence[MarketStructureEvidenceItem]) -> tuple[MarketStructureEvidenceProvenance, ...]:
    grouped: dict[str, list[MarketStructureEvidenceItem]] = {}
    for item in items:
        grouped.setdefault(item.provenance_group_id, []).append(item)
    provenance_groups: list[MarketStructureEvidenceProvenance] = []
    for provenance_group_id in sorted(grouped):
        group_items = tuple(sorted(grouped[provenance_group_id], key=lambda item: item.evidence_id))
        group_state = "independent"
        states = {item.independence_state for item in group_items}
        if "duplicate" in states:
            group_state = "duplicate"
        elif "redundant" in states:
            group_state = "redundant"
        elif "partially_redundant" in states:
            group_state = "partially_redundant"
        elif "unknown" in states and len(states) == 1:
            group_state = "unknown"
        provenance_groups.append(
            MarketStructureEvidenceProvenance(
                provenance_group_id=provenance_group_id,
                evidence_ids=tuple(item.evidence_id for item in group_items),
                evidence_source_types=tuple(item.evidence_source_type for item in group_items),
                source_event_ids=tuple(item.source_event_id for item in group_items if item.source_event_id),
                source_annotation_ids=tuple(item.source_annotation_id for item in group_items if item.source_annotation_id),
                source_hypothesis_ids=tuple(item.source_hypothesis_id for item in group_items if item.source_hypothesis_id),
                evidence_families=tuple(item.evidence_family for item in group_items),
                evidence_roles=tuple(item.evidence_role for item in group_items),
                group_state=group_state,
                metadata={},
            )
        )
    return tuple(provenance_groups)


def _family_state(items: Sequence[MarketStructureEvidenceItem]) -> tuple[str, str]:
    supporting = tuple(item.evidence_id for item in items if item.evidence_role == "supporting")
    contradicting = tuple(item.evidence_id for item in items if item.evidence_role == "contradicting")
    ambiguous = tuple(item.evidence_id for item in items if item.evidence_role == "ambiguous")
    invalidation = tuple(item.evidence_id for item in items if item.evidence_role == "invalidation")
    neutral = tuple(item.evidence_id for item in items if item.evidence_role == "neutral")
    if invalidation:
        return "invalidated", "present"
    if supporting and contradicting:
        return "conflicted", "present"
    if ambiguous and (supporting or contradicting):
        return "conflicted", "present"
    if supporting:
        return "supported", "none"
    if contradicting:
        return "contradicted", "none"
    if ambiguous:
        return "ambiguous", "none"
    if neutral:
        return "neutral", "none"
    return "unobserved", "none"


def _build_evidence_matrix(items: Sequence[MarketStructureEvidenceItem]) -> Mapping[str, MarketStructureEvidenceFamilySummary]:
    grouped: dict[str, list[MarketStructureEvidenceItem]] = {family: [] for family in MARKET_STRUCTURE_EVIDENCE_FAMILIES}
    for item in items:
        grouped[item.evidence_family].append(item)
    matrix: dict[str, MarketStructureEvidenceFamilySummary] = {}
    for family in MARKET_STRUCTURE_EVIDENCE_FAMILIES:
        family_items = tuple(sorted(grouped.get(family, ()), key=lambda item: item.evidence_id))
        if not family_items:
            continue
        family_state, conflict_state = _family_state(family_items)
        matrix[family] = MarketStructureEvidenceFamilySummary(
            evidence_family=family,
            evidence_ids=tuple(item.evidence_id for item in family_items),
            supporting_evidence_ids=tuple(item.evidence_id for item in family_items if item.evidence_role == "supporting"),
            contradicting_evidence_ids=tuple(item.evidence_id for item in family_items if item.evidence_role == "contradicting"),
            ambiguous_evidence_ids=tuple(item.evidence_id for item in family_items if item.evidence_role == "ambiguous"),
            invalidation_evidence_ids=tuple(item.evidence_id for item in family_items if item.evidence_role == "invalidation"),
            neutral_evidence_ids=tuple(item.evidence_id for item in family_items if item.evidence_role == "neutral"),
            family_state=family_state,
            conflict_state=conflict_state,
            metadata={},
        )
    return _freeze_read_only_value(matrix)


def _classify_independence(
    items: Sequence[MarketStructureEvidenceItem],
) -> tuple[MarketStructureEvidenceItem, ...]:
    sorted_items = _ordered_items(items)
    seen_evidence_ids: set[str] = set()
    seen_provenance_groups: set[str] = set()
    seen_origin_signatures: set[tuple[str, str]] = set()
    seen_source_hypothesis_ids: set[str] = set()
    enriched: list[MarketStructureEvidenceItem] = []
    for item in sorted_items:
        if item.evidence_id in seen_evidence_ids:
            state = "duplicate"
        elif item.provenance_group_id in seen_provenance_groups:
            state = "redundant"
        else:
            origin_signature = (
                item.evidence_source_type,
                item.source_event_id or item.source_annotation_id or item.source_hypothesis_id,
            )
            if origin_signature in seen_origin_signatures or item.source_hypothesis_id in seen_source_hypothesis_ids:
                state = "partially_redundant"
            else:
                state = "independent"
            seen_origin_signatures.add(origin_signature)
            seen_source_hypothesis_ids.add(item.source_hypothesis_id)
        seen_evidence_ids.add(item.evidence_id)
        seen_provenance_groups.add(item.provenance_group_id)
        enriched.append(replace(item, independence_state=state))
    return tuple(enriched)


def _classify_temporal_and_ambiguity(
    items: Sequence[MarketStructureEvidenceItem],
    *,
    hypothesis_evaluation: phase53.MarketStructureHypothesisEvaluation,
) -> tuple[MarketStructureEvidenceItem, ...]:
    enriched: list[MarketStructureEvidenceItem] = []
    for item in items:
        temporal_state = _temporal_state_for_item(item, evaluated_at_utc=hypothesis_evaluation.created_at_utc)
        if temporal_state == "future":
            raise MarketStructureEvidenceAssessmentValidationError("future evidence cannot be assessed.")
        ambiguity_state = item.ambiguity_state
        if item.evidence_role == "invalidation" or item.evidence_family == "invalidation":
            ambiguity_state = "unknown"
        elif item.evidence_role == "ambiguous" or item.evidence_family == "ambiguity":
            ambiguity_state = "ambiguous"
        elif item.evidence_role == "neutral":
            ambiguity_state = "unknown"
        enriched.append(
            replace(
                item,
                temporal_validity_state=temporal_state,
                ambiguity_state=ambiguity_state,
            )
        )
    return tuple(enriched)


@dataclass(frozen=True, slots=True)
class MarketStructureEvidenceAssessment:
    schema_version: int = MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_SCHEMA_VERSION
    assessment_id: str = ""
    assessment_hash: str = ""
    lineage_hash: str = ""
    hypothesis_evaluation: phase53.MarketStructureHypothesisEvaluation | None = None
    evidence_items: tuple[MarketStructureEvidenceItem, ...] = field(default_factory=tuple, repr=False)
    provenance_groups: tuple[MarketStructureEvidenceProvenance, ...] = field(default_factory=tuple, repr=False)
    evidence_matrix: Mapping[str, MarketStructureEvidenceFamilySummary] = field(default_factory=dict, repr=False)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    non_operational_declaration: str = MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_NON_OPERATIONAL_DECLARATION
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "assessment_id", _require_hex_digest(self.assessment_id, "assessment_id") if self.assessment_id else "")
        object.__setattr__(self, "assessment_hash", _require_hex_digest(self.assessment_hash, "assessment_hash") if self.assessment_hash else "")
        object.__setattr__(self, "lineage_hash", _require_hex_digest(self.lineage_hash, "lineage_hash"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if not isinstance(self.metadata, Mapping):
            raise MarketStructureEvidenceAssessmentValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))

        if self.historical_research_only is not True:
            raise MarketStructureEvidenceAssessmentValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise MarketStructureEvidenceAssessmentValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise MarketStructureEvidenceAssessmentValidationError("paper_promotion_eligible must be false.")
        if self.non_operational_declaration != MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_NON_OPERATIONAL_DECLARATION:
            raise MarketStructureEvidenceAssessmentValidationError(
                "non_operational_declaration diverges from the evidence assessment contract."
            )

        if self.hypothesis_evaluation is None:
            raise MarketStructureEvidenceAssessmentValidationError("hypothesis_evaluation is required.")
        verified_evaluation = phase53.verify_market_structure_hypothesis_evaluation(self.hypothesis_evaluation)
        object.__setattr__(self, "hypothesis_evaluation", verified_evaluation)
        if verified_evaluation.evaluation_hash != self.lineage_hash:
            raise MarketStructureEvidenceAssessmentIntegrityError("lineage_hash mismatch.")

        evidence_items = tuple(
            replace(item, hypothesis_evaluation_hash=self.lineage_hash)
            if item.hypothesis_evaluation_hash != self.lineage_hash
            else item
            for item in self.evidence_items
        )
        evidence_items = _classify_temporal_and_ambiguity(evidence_items, hypothesis_evaluation=verified_evaluation)
        evidence_items = _classify_independence(evidence_items)
        object.__setattr__(self, "evidence_items", evidence_items)
        object.__setattr__(self, "provenance_groups", _build_provenance_groups(evidence_items))
        object.__setattr__(self, "evidence_matrix", _build_evidence_matrix(evidence_items))

        if not self.assessment_id:
            object.__setattr__(self, "assessment_id", _hash_payload(self._assessment_id_payload()))
        else:
            expected_assessment_id = _hash_payload(self._assessment_id_payload())
            if self.assessment_id != expected_assessment_id:
                raise MarketStructureEvidenceAssessmentIntegrityError("assessment_id mismatch.")

        expected_hash = _hash_payload(self._assessment_hash_payload())
        if self.assessment_hash:
            if self.assessment_hash != expected_hash:
                raise MarketStructureEvidenceAssessmentIntegrityError("assessment_hash mismatch.")
        else:
            object.__setattr__(self, "assessment_hash", expected_hash)

    def _assessment_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "lineage_hash": self.lineage_hash,
            "evidence_items": [item.canonical_payload() for item in self.evidence_items],
            "provenance_groups": [group.canonical_payload() for group in self.provenance_groups],
            "evidence_matrix": {family: summary.canonical_payload() for family, summary in self.evidence_matrix.items()},
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
            "lineage_hash": self.lineage_hash,
            "hypothesis_evaluation": self.hypothesis_evaluation.as_dict(),
            "evidence_items": [item.as_dict() for item in self.evidence_items],
            "provenance_groups": [group.as_dict() for group in self.provenance_groups],
            "evidence_matrix": {family: summary.as_dict() for family, summary in self.evidence_matrix.items()},
            "created_at_utc": _utc_iso(self.created_at_utc),
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "non_operational_declaration": self.non_operational_declaration,
            "metadata": _thaw_read_only_value(self.metadata),
        }
        if include_assessment_id:
            payload["assessment_id"] = self.assessment_id
        if include_assessment_hash:
            payload["assessment_hash"] = self.assessment_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_assessment_id=True, include_assessment_hash=True))

    @property
    def hypothesis_evaluation_hash(self) -> str:
        return self.lineage_hash

    @property
    def audit_record_hash(self) -> str:
        return self.assessment_hash

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureEvidenceAssessment":
        if not isinstance(data, Mapping):
            raise MarketStructureEvidenceAssessmentValidationError("market structure evidence assessment must be a mapping.")
        allowed = {
            "schema_version",
            "assessment_id",
            "assessment_hash",
            "lineage_hash",
            "hypothesis_evaluation",
            "evidence_items",
            "provenance_groups",
            "evidence_matrix",
            "created_at_utc",
            "historical_research_only",
            "operational_evidence",
            "paper_promotion_eligible",
            "non_operational_declaration",
            "metadata",
        }
        extra = sorted(set(data) - allowed)
        missing = sorted(allowed - set(data))
        if extra or missing:
            parts: list[str] = []
            if missing:
                parts.append(f"missing {', '.join(missing)}")
            if extra:
                parts.append(f"unexpected {', '.join(extra)}")
            raise MarketStructureEvidenceAssessmentValidationError(
                f"market structure evidence assessment has invalid fields: {'; '.join(parts)}."
            )
        try:
            evidence_matrix = {
                family: MarketStructureEvidenceFamilySummary.from_dict(summary)
                for family, summary in data["evidence_matrix"].items()
            }
            provenance_groups = tuple(MarketStructureEvidenceProvenance.from_dict(group) for group in data["provenance_groups"])
            evidence_items = tuple(MarketStructureEvidenceItem.from_dict(item) for item in data["evidence_items"])
            hypothesis_evaluation = phase53.MarketStructureHypothesisEvaluation.from_dict(data["hypothesis_evaluation"])
            return cls(
                schema_version=data["schema_version"],
                assessment_id=data.get("assessment_id", ""),
                assessment_hash=data.get("assessment_hash", ""),
                lineage_hash=data["lineage_hash"],
                hypothesis_evaluation=hypothesis_evaluation,
                evidence_items=evidence_items,
                provenance_groups=provenance_groups,
                evidence_matrix=_freeze_read_only_value(evidence_matrix),
                created_at_utc=data["created_at_utc"],
                historical_research_only=data.get("historical_research_only", True),
                operational_evidence=data.get("operational_evidence", False),
                paper_promotion_eligible=data.get("paper_promotion_eligible", False),
                non_operational_declaration=data.get(
                    "non_operational_declaration",
                    MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_NON_OPERATIONAL_DECLARATION,
                ),
                metadata=data.get("metadata", {}),
            )
        except KeyError as exc:
            raise MarketStructureEvidenceAssessmentValidationError(
                "market structure evidence assessment is incomplete."
            ) from exc


def build_market_structure_evidence_assessment(
    hypothesis_evaluation: phase53.MarketStructureHypothesisEvaluation | Mapping[str, Any],
    *,
    created_at_utc: datetime | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> MarketStructureEvidenceAssessment:
    if isinstance(hypothesis_evaluation, Mapping):
        hypothesis_evaluation = phase53.MarketStructureHypothesisEvaluation.from_dict(hypothesis_evaluation)
    if not isinstance(hypothesis_evaluation, phase53.MarketStructureHypothesisEvaluation):
        raise MarketStructureEvidenceAssessmentValidationError(
            "market structure hypothesis evaluation is required."
        )
    verified_evaluation = phase53.verify_market_structure_hypothesis_evaluation(hypothesis_evaluation)
    evidence_items: list[MarketStructureEvidenceItem] = []
    for hypothesis in verified_evaluation.hypotheses:
        evidence_items.extend(_items_for_hypothesis(hypothesis, hypothesis_evaluation_hash=verified_evaluation.evaluation_hash))
    assessment = MarketStructureEvidenceAssessment(
        schema_version=MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_SCHEMA_VERSION,
        lineage_hash=verified_evaluation.evaluation_hash,
        hypothesis_evaluation=verified_evaluation,
        evidence_items=tuple(evidence_items),
        provenance_groups=tuple(),
        evidence_matrix=_freeze_read_only_value({}),
        created_at_utc=created_at_utc or verified_evaluation.created_at_utc,
        historical_research_only=True,
        operational_evidence=False,
        paper_promotion_eligible=False,
        non_operational_declaration=MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_NON_OPERATIONAL_DECLARATION,
        metadata=metadata or {},
    )
    return verify_market_structure_evidence_assessment(assessment)


def verify_market_structure_evidence_assessment(
    assessment: MarketStructureEvidenceAssessment,
) -> MarketStructureEvidenceAssessment:
    if not isinstance(assessment, MarketStructureEvidenceAssessment):
        raise MarketStructureEvidenceAssessmentValidationError("market structure evidence assessment is required.")
    expected_id = _hash_payload(assessment._assessment_id_payload())
    if assessment.assessment_id != expected_id:
        raise MarketStructureEvidenceAssessmentIntegrityError("assessment_id mismatch.")
    expected_hash = _hash_payload(assessment._assessment_hash_payload())
    if assessment.assessment_hash != expected_hash:
        raise MarketStructureEvidenceAssessmentIntegrityError("assessment_hash mismatch.")
    return assessment


def market_structure_evidence_assessment_to_dict(
    assessment: MarketStructureEvidenceAssessment,
) -> dict[str, Any]:
    if not isinstance(assessment, MarketStructureEvidenceAssessment):
        raise MarketStructureEvidenceAssessmentValidationError("market structure evidence assessment is required.")
    return assessment.as_dict()


def market_structure_evidence_assessment_from_dict(
    data: Mapping[str, Any],
) -> MarketStructureEvidenceAssessment:
    return MarketStructureEvidenceAssessment.from_dict(data)


__all__ = [
    "MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_ID",
    "MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_NON_OPERATIONAL_DECLARATION",
    "MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_SCHEMA_VERSION",
    "MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_VERSION",
    "MARKET_STRUCTURE_EVIDENCE_AMBIGUITY_STATES",
    "MARKET_STRUCTURE_EVIDENCE_FAMILIES",
    "MARKET_STRUCTURE_EVIDENCE_INDEPENDENCE_STATES",
    "MARKET_STRUCTURE_EVIDENCE_ROLES",
    "MARKET_STRUCTURE_EVIDENCE_SOURCE_TYPES",
    "MARKET_STRUCTURE_EVIDENCE_TEMPORAL_VALIDITY_STATES",
    "MarketStructureEvidenceAssessment",
    "MarketStructureEvidenceAssessmentError",
    "MarketStructureEvidenceAssessmentIntegrityError",
    "MarketStructureEvidenceAssessmentValidationError",
    "MarketStructureEvidenceFamilySummary",
    "MarketStructureEvidenceItem",
    "MarketStructureEvidenceProvenance",
    "build_market_structure_evidence_assessment",
    "market_structure_evidence_assessment_from_dict",
    "market_structure_evidence_assessment_to_dict",
    "verify_market_structure_evidence_assessment",
]
