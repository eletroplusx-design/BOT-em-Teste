from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value

from . import market_structure_annotation_layer as phase52
from .errors import HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError

MARKET_STRUCTURE_HYPOTHESIS_SCHEMA_VERSION = 1
MARKET_STRUCTURE_HYPOTHESIS_ID = "market_structure_hypothesis"
MARKET_STRUCTURE_HYPOTHESIS_VERSION = "phase53_market_structure_hypothesis_v1"
MARKET_STRUCTURE_HYPOTHESIS_EVALUATION_SCHEMA_VERSION = 1
MARKET_STRUCTURE_HYPOTHESIS_EVALUATION_ID = "market_structure_hypothesis_evaluation"
MARKET_STRUCTURE_HYPOTHESIS_EVALUATION_VERSION = "phase53_market_structure_hypothesis_evaluation_v1"

MARKET_STRUCTURE_HYPOTHESIS_ALLOWED_TYPES = (
    "Bullish Continuation",
    "Bearish Continuation",
    "Accumulation Candidate",
    "Distribution Candidate",
    "Reaccumulation Candidate",
    "Redistribution Candidate",
    "Unknown",
)
MARKET_STRUCTURE_HYPOTHESIS_ALLOWED_STATUSES = (
    "candidate",
    "supported",
    "weakened",
    "invalidated",
    "ambiguous",
    "indeterminate",
)
MARKET_STRUCTURE_HYPOTHESIS_ALLOWED_ALIGNMENT_STATES = (
    "aligned",
    "conflicted",
    "neutral",
    "indeterminate",
)
MARKET_STRUCTURE_HYPOTHESIS_TIMEFRAME_CONTEXT_KEYS = {
    "timeframe",
    "macro_context",
    "intermediate_context",
    "micro_context",
    "alignment_state",
}


class MarketStructureHypothesisError(HistoricalDataError):
    pass


class MarketStructureHypothesisValidationError(
    MarketStructureHypothesisError,
    HistoricalDataValidationError,
):
    pass


class MarketStructureHypothesisIntegrityError(
    MarketStructureHypothesisError,
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
        raise MarketStructureHypothesisValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketStructureHypothesisValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise MarketStructureHypothesisValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise MarketStructureHypothesisValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise MarketStructureHypothesisValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise MarketStructureHypothesisValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise MarketStructureHypothesisValidationError(f"{field_name} must be a 64-character hex digest.")
    return digest


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise MarketStructureHypothesisValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise MarketStructureHypothesisValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise MarketStructureHypothesisValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketStructureHypothesisValidationError(f"{field_name} must be timezone-aware UTC datetime.")
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


def _require_str_sequence(value: Any, field_name: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise MarketStructureHypothesisValidationError(f"{field_name} must be a sequence of strings.")
    normalized = tuple(_require_str(item, field_name) for item in value)
    if not allow_empty and not normalized:
        raise MarketStructureHypothesisValidationError(f"{field_name} must not be empty.")
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
        raise MarketStructureHypothesisValidationError(
            f"{field_name} has invalid fields: {'; '.join(parts)}."
        )


def _timeframe_alignment_state(macro_context: str, intermediate_context: str, micro_context: str) -> str:
    contexts = (macro_context, intermediate_context, micro_context)
    if all(context == "indeterminate" for context in contexts):
        return "indeterminate"
    if all(context == "lateral" or context == "indeterminate" for context in contexts):
        return "neutral"
    if len({context for context in contexts if context in {"bullish", "bearish"}}) == 1 and all(
        context in {"bullish", "bearish", "indeterminate"} for context in contexts
    ):
        return "aligned"
    return "conflicted"


def _normalize_timeframe_context(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MarketStructureHypothesisValidationError(f"{field_name} must be a mapping.")
    _require_exact_keys(value, field_name, MARKET_STRUCTURE_HYPOTHESIS_TIMEFRAME_CONTEXT_KEYS)
    timeframe = _require_str(value["timeframe"], f"{field_name}.timeframe").upper()
    macro_context = _require_str(value["macro_context"], f"{field_name}.macro_context").lower()
    intermediate_context = _require_str(value["intermediate_context"], f"{field_name}.intermediate_context").lower()
    micro_context = _require_str(value["micro_context"], f"{field_name}.micro_context").lower()
    alignment_state = _require_str(value["alignment_state"], f"{field_name}.alignment_state").lower()
    if alignment_state not in MARKET_STRUCTURE_HYPOTHESIS_ALLOWED_ALIGNMENT_STATES:
        raise MarketStructureHypothesisValidationError(f"{field_name}.alignment_state is invalid.")
    for context_name, context_value in (
        ("macro_context", macro_context),
        ("intermediate_context", intermediate_context),
        ("micro_context", micro_context),
    ):
        if context_value not in phase52.MARKET_STRUCTURE_ANNOTATION_ALLOWED_STRUCTURE_STATES:
            raise MarketStructureHypothesisValidationError(f"{field_name}.{context_name} is invalid.")
    expected_alignment_state = _timeframe_alignment_state(macro_context, intermediate_context, micro_context)
    if alignment_state != expected_alignment_state:
        raise MarketStructureHypothesisValidationError(f"{field_name}.alignment_state is inconsistent.")
    return _freeze_read_only_value(
        {
            "timeframe": timeframe,
            "macro_context": macro_context,
            "intermediate_context": intermediate_context,
            "micro_context": micro_context,
            "alignment_state": alignment_state,
        }
    )


def _annotation_timeframe_context(annotation: phase52.MarketStructureAnnotation) -> Mapping[str, Any]:
    payload = annotation.annotation_payload
    return _normalize_timeframe_context(
        {
            "timeframe": payload["timeframe"],
            "macro_context": payload["macro_context"],
            "intermediate_context": payload["intermediate_context"],
            "micro_context": payload["micro_context"],
            "alignment_state": _timeframe_alignment_state(
                payload["macro_context"],
                payload["intermediate_context"],
                payload["micro_context"],
            ),
        },
        field_name="timeframe_context",
    )


def _event_reference(annotation_id: str, event_kind: str) -> str:
    return f"{annotation_id}::{event_kind}"


def _unique_sorted(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(_require_str(item, "value") for item in values)
    if len(set(normalized)) != len(normalized):
        raise MarketStructureHypothesisValidationError("evidence references must not contain duplicates.")
    return tuple(sorted(normalized))


def _canonical_hypothesis_type_order(hypothesis_type: str) -> int:
    order = {
        "Bullish Continuation": 0,
        "Bearish Continuation": 1,
        "Accumulation Candidate": 2,
        "Distribution Candidate": 3,
        "Reaccumulation Candidate": 4,
        "Redistribution Candidate": 5,
        "Unknown": 6,
    }
    return order.get(hypothesis_type, 99)


def _supporting_event_kinds(hypothesis_type: str) -> tuple[str, ...]:
    if hypothesis_type == "Bullish Continuation":
        return (
            "bullish_structure",
            "valid_bos",
            "valid_choch",
            "valid_displacement",
            "valid_retest",
            "breakout",
        )
    if hypothesis_type == "Bearish Continuation":
        return (
            "bearish_structure",
            "valid_bos",
            "valid_choch",
            "valid_displacement",
            "valid_retest",
            "breakout",
        )
    if hypothesis_type == "Accumulation Candidate":
        return ("candidate_accumulation", "valid_trading_range")
    if hypothesis_type == "Distribution Candidate":
        return ("candidate_distribution", "valid_trading_range")
    if hypothesis_type == "Reaccumulation Candidate":
        return ("candidate_reaccumulation", "valid_trading_range")
    if hypothesis_type == "Redistribution Candidate":
        return ("candidate_redistribution", "valid_trading_range")
    return ()


def _contradicting_event_kinds(hypothesis_type: str) -> tuple[str, ...]:
    if hypothesis_type == "Bullish Continuation":
        return (
            "bearish_structure",
            "failed_bos",
            "failed_choch",
            "failed_retest",
            "false_break",
            "candidate_distribution",
            "candidate_redistribution",
        )
    if hypothesis_type == "Bearish Continuation":
        return (
            "bullish_structure",
            "failed_bos",
            "failed_choch",
            "failed_retest",
            "false_break",
            "candidate_accumulation",
            "candidate_reaccumulation",
        )
    if hypothesis_type == "Accumulation Candidate":
        return (
            "bearish_structure",
            "candidate_distribution",
            "candidate_redistribution",
            "failed_bos",
            "failed_retest",
        )
    if hypothesis_type == "Distribution Candidate":
        return (
            "bullish_structure",
            "candidate_accumulation",
            "candidate_reaccumulation",
            "failed_choch",
            "failed_retest",
        )
    if hypothesis_type == "Reaccumulation Candidate":
        return (
            "bearish_structure",
            "candidate_distribution",
            "candidate_redistribution",
            "failed_bos",
            "failed_retest",
        )
    if hypothesis_type == "Redistribution Candidate":
        return (
            "bullish_structure",
            "candidate_accumulation",
            "candidate_reaccumulation",
            "failed_choch",
            "failed_retest",
        )
    return ()


def _hypothesis_types_for_annotation(annotation: phase52.MarketStructureAnnotation) -> tuple[str, ...]:
    payload = annotation.annotation_payload
    types: list[str] = []
    if "candidate_accumulation" in payload["event_kinds"]:
        types.append("Accumulation Candidate")
    if "candidate_distribution" in payload["event_kinds"]:
        types.append("Distribution Candidate")
    if "candidate_reaccumulation" in payload["event_kinds"]:
        types.append("Reaccumulation Candidate")
    if "candidate_redistribution" in payload["event_kinds"]:
        types.append("Redistribution Candidate")
    if payload["final_structure_state"] == "bullish" or payload["bullish_structure"]:
        types.append("Bullish Continuation")
    if payload["final_structure_state"] == "bearish" or payload["bearish_structure"]:
        types.append("Bearish Continuation")
    if not types:
        types.append("Unknown")
    deduplicated: list[str] = []
    for hypothesis_type in types:
        if hypothesis_type not in deduplicated:
            deduplicated.append(hypothesis_type)
    return tuple(sorted(deduplicated, key=_canonical_hypothesis_type_order))


def _derive_hypothesis_status(
    *,
    hypothesis_type: str,
    support_event_ids: tuple[str, ...],
    contradicting_event_ids: tuple[str, ...],
    alignment_state: str,
    ambiguity_reasons: tuple[str, ...],
    invalidation_reasons: tuple[str, ...],
) -> str:
    if hypothesis_type == "Unknown":
        return "indeterminate"
    if invalidation_reasons:
        return "invalidated"
    if not support_event_ids:
        if alignment_state == "indeterminate":
            return "indeterminate"
        if alignment_state == "neutral":
            return "candidate"
        return "ambiguous"
    if contradicting_event_ids:
        return "weakened" if alignment_state != "indeterminate" else "ambiguous"
    if hypothesis_type.endswith("Candidate"):
        return "candidate"
    return "supported"


def _derive_invalidation_reasons(
    *,
    hypothesis_type: str,
    annotation: phase52.MarketStructureAnnotation,
    support_event_kinds: tuple[str, ...],
) -> tuple[str, ...]:
    kinds = set(annotation.annotation_payload["event_kinds"])
    reasons: list[str] = []
    if hypothesis_type == "Bullish Continuation":
        for event_kind in ("failed_bos", "failed_choch", "failed_retest", "false_break"):
            if event_kind in kinds:
                reasons.append(f"invalidation:{event_kind}")
    elif hypothesis_type == "Bearish Continuation":
        for event_kind in ("failed_bos", "failed_choch", "failed_retest", "false_break"):
            if event_kind in kinds:
                reasons.append(f"invalidation:{event_kind}")
    else:
        for event_kind in ("failed_bos", "failed_choch", "failed_retest", "false_break"):
            if event_kind in kinds and event_kind not in support_event_kinds:
                reasons.append(f"invalidation:{event_kind}")
    return tuple(sorted(dict.fromkeys(reasons)))


def _derive_ambiguity_reasons(
    *,
    hypothesis_type: str,
    support_event_ids: tuple[str, ...],
    contradicting_event_ids: tuple[str, ...],
    alignment_state: str,
    annotation: phase52.MarketStructureAnnotation,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if alignment_state == "conflicted":
        reasons.append("timeframe_context_conflicted")
    elif alignment_state == "neutral":
        reasons.append("timeframe_context_neutral")
    elif alignment_state == "indeterminate":
        reasons.append("timeframe_context_indeterminate")
    if not support_event_ids and hypothesis_type != "Unknown":
        reasons.append("insufficient_evidence")
    if contradicting_event_ids:
        reasons.append("contradicting_evidence")
    if annotation.annotation_payload["ambiguity_state"] == "ambiguous":
        reasons.append("annotation_ambiguous")
    if annotation.annotation_payload["invalidation_state"] == "invalidated":
        reasons.append("annotation_invalidated")
    return tuple(sorted(dict.fromkeys(reasons)))


def _build_hypothesis_payload(
    *,
    annotation: phase52.MarketStructureAnnotation,
    hypothesis_type: str,
    created_at_utc: datetime,
    metadata: Mapping[str, Any] | None,
    annotation_collection_hash: str = "",
) -> dict[str, Any]:
    verified_annotation = phase52.verify_market_structure_annotation(annotation)
    if hypothesis_type not in MARKET_STRUCTURE_HYPOTHESIS_ALLOWED_TYPES:
        raise MarketStructureHypothesisValidationError("hypothesis_type is invalid.")

    context = _annotation_timeframe_context(verified_annotation)
    event_kinds = tuple(verified_annotation.annotation_payload["event_kinds"])
    support_kinds = tuple(kind for kind in _supporting_event_kinds(hypothesis_type) if kind in event_kinds)
    contradicting_kinds = tuple(kind for kind in _contradicting_event_kinds(hypothesis_type) if kind in event_kinds)
    support_event_ids = _unique_sorted(_event_reference(verified_annotation.annotation_id, kind) for kind in support_kinds)
    contradicting_event_ids = _unique_sorted(
        _event_reference(verified_annotation.annotation_id, kind) for kind in contradicting_kinds
    )
    support_annotation_ids = (verified_annotation.annotation_id,)
    contradicting_annotation_ids: tuple[str, ...] = ()
    invalidation_reasons = _derive_invalidation_reasons(
        hypothesis_type=hypothesis_type,
        annotation=verified_annotation,
        support_event_kinds=support_kinds,
    )
    ambiguity_reasons = _derive_ambiguity_reasons(
        hypothesis_type=hypothesis_type,
        support_event_ids=support_event_ids,
        contradicting_event_ids=contradicting_event_ids,
        alignment_state=context["alignment_state"],
        annotation=verified_annotation,
    )
    status = _derive_hypothesis_status(
        hypothesis_type=hypothesis_type,
        support_event_ids=support_event_ids,
        contradicting_event_ids=contradicting_event_ids,
        alignment_state=context["alignment_state"],
        ambiguity_reasons=ambiguity_reasons,
        invalidation_reasons=invalidation_reasons,
    )
    observed_at = verified_annotation.candle_timestamp
    effective_at = observed_at
    payload = {
        "schema_version": MARKET_STRUCTURE_HYPOTHESIS_SCHEMA_VERSION,
        "hypothesis_type": hypothesis_type,
        "status": status,
        "dataset_hash": verified_annotation.dataset_hash,
        "contract_hash": verified_annotation.contract_hash,
        "detection_result_hash": verified_annotation.detection_result_hash,
        "annotation_collection_hash": annotation_collection_hash,
        "timeframe_context": context,
        "observed_at": _utc_iso(observed_at),
        "effective_at": _utc_iso(effective_at),
        "supporting_event_ids": support_event_ids,
        "supporting_annotation_ids": support_annotation_ids,
        "contradicting_event_ids": contradicting_event_ids,
        "contradicting_annotation_ids": contradicting_annotation_ids,
        "invalidation_reasons": invalidation_reasons,
        "ambiguity_reasons": ambiguity_reasons,
        "metadata": metadata or {},
        "created_at_utc": created_at_utc,
    }
    return payload


def _validate_hypothesis_payload(payload: Mapping[str, Any], *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise MarketStructureHypothesisValidationError(f"{field_name} must be a mapping.")
    _require_exact_keys(
        payload,
        field_name,
        {
            "schema_version",
            "hypothesis_id",
            "hypothesis_hash",
            "hypothesis_type",
            "status",
            "dataset_hash",
            "contract_hash",
            "detection_result_hash",
            "annotation_collection_hash",
            "timeframe_context",
            "observed_at",
            "effective_at",
            "supporting_event_ids",
            "supporting_annotation_ids",
            "contradicting_event_ids",
            "contradicting_annotation_ids",
            "invalidation_reasons",
            "ambiguity_reasons",
            "metadata",
            "created_at_utc",
        },
    )
    schema_version = _require_int(payload["schema_version"], f"{field_name}.schema_version")
    if schema_version != MARKET_STRUCTURE_HYPOTHESIS_SCHEMA_VERSION:
        raise MarketStructureHypothesisValidationError(f"{field_name}.schema_version must be 1.")
    hypothesis_type = _require_str(payload["hypothesis_type"], f"{field_name}.hypothesis_type")
    if hypothesis_type not in MARKET_STRUCTURE_HYPOTHESIS_ALLOWED_TYPES:
        raise MarketStructureHypothesisValidationError(f"{field_name}.hypothesis_type is invalid.")
    status = _require_str(payload["status"], f"{field_name}.status")
    if status not in MARKET_STRUCTURE_HYPOTHESIS_ALLOWED_STATUSES:
        raise MarketStructureHypothesisValidationError(f"{field_name}.status is invalid.")
    dataset_hash = _require_hex_digest(payload["dataset_hash"], f"{field_name}.dataset_hash")
    contract_hash = _require_hex_digest(payload["contract_hash"], f"{field_name}.contract_hash")
    detection_result_hash = _require_hex_digest(payload["detection_result_hash"], f"{field_name}.detection_result_hash")
    annotation_collection_hash = (
        _require_hex_digest(payload["annotation_collection_hash"], f"{field_name}.annotation_collection_hash")
        if payload["annotation_collection_hash"]
        else ""
    )
    timeframe_context = _normalize_timeframe_context(
        payload["timeframe_context"], field_name=f"{field_name}.timeframe_context"
    )
    observed_at = _require_utc_datetime(payload["observed_at"], f"{field_name}.observed_at")
    effective_at = _require_utc_datetime(payload["effective_at"], f"{field_name}.effective_at")
    if effective_at < observed_at:
        raise MarketStructureHypothesisValidationError(f"{field_name}.effective_at cannot precede observed_at.")
    supporting_event_ids = _unique_sorted(_require_str_sequence(payload["supporting_event_ids"], f"{field_name}.supporting_event_ids", allow_empty=True))
    supporting_annotation_ids = _unique_sorted(
        _require_str_sequence(payload["supporting_annotation_ids"], f"{field_name}.supporting_annotation_ids", allow_empty=True)
    )
    contradicting_event_ids = _unique_sorted(
        _require_str_sequence(payload["contradicting_event_ids"], f"{field_name}.contradicting_event_ids", allow_empty=True)
    )
    contradicting_annotation_ids = _unique_sorted(
        _require_str_sequence(
            payload["contradicting_annotation_ids"],
            f"{field_name}.contradicting_annotation_ids",
            allow_empty=True,
        )
    )
    invalidation_reasons = _unique_sorted(
        _require_str_sequence(payload["invalidation_reasons"], f"{field_name}.invalidation_reasons", allow_empty=True)
    )
    ambiguity_reasons = _unique_sorted(
        _require_str_sequence(payload["ambiguity_reasons"], f"{field_name}.ambiguity_reasons", allow_empty=True)
    )
    if not isinstance(payload["metadata"], Mapping):
        raise MarketStructureHypothesisValidationError(f"{field_name}.metadata must be a mapping.")
    if not isinstance(payload["created_at_utc"], datetime) and not isinstance(payload["created_at_utc"], str):
        raise MarketStructureHypothesisValidationError(f"{field_name}.created_at_utc must be timezone-aware UTC datetime.")
    created_at_utc = _require_utc_datetime(payload["created_at_utc"], f"{field_name}.created_at_utc")
    normalized = {
        "schema_version": schema_version,
        "hypothesis_type": hypothesis_type,
        "status": status,
        "dataset_hash": dataset_hash,
        "contract_hash": contract_hash,
        "detection_result_hash": detection_result_hash,
        "annotation_collection_hash": annotation_collection_hash,
        "timeframe_context": timeframe_context,
        "observed_at": observed_at,
        "effective_at": effective_at,
        "supporting_event_ids": supporting_event_ids,
        "supporting_annotation_ids": supporting_annotation_ids,
        "contradicting_event_ids": contradicting_event_ids,
        "contradicting_annotation_ids": contradicting_annotation_ids,
        "invalidation_reasons": invalidation_reasons,
        "ambiguity_reasons": ambiguity_reasons,
        "metadata": _freeze_read_only_value(dict(payload["metadata"])),
        "created_at_utc": created_at_utc,
    }
    return _freeze_read_only_value(normalized)


@dataclass(frozen=True, slots=True)
class MarketStructureHypothesis:
    schema_version: int
    hypothesis_id: str = ""
    hypothesis_hash: str = ""
    hypothesis_type: str = ""
    status: str = "indeterminate"
    dataset_hash: str = ""
    contract_hash: str = ""
    detection_result_hash: str = ""
    annotation_collection_hash: str = ""
    timeframe_context: Mapping[str, Any] = field(default_factory=dict, repr=False)
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    effective_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    supporting_event_ids: tuple[str, ...] = field(default_factory=tuple, repr=False)
    supporting_annotation_ids: tuple[str, ...] = field(default_factory=tuple, repr=False)
    contradicting_event_ids: tuple[str, ...] = field(default_factory=tuple, repr=False)
    contradicting_annotation_ids: tuple[str, ...] = field(default_factory=tuple, repr=False)
    invalidation_reasons: tuple[str, ...] = field(default_factory=tuple, repr=False)
    ambiguity_reasons: tuple[str, ...] = field(default_factory=tuple, repr=False)
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(
            self,
            "hypothesis_id",
            _require_hex_digest(self.hypothesis_id, "hypothesis_id") if self.hypothesis_id else "",
        )
        object.__setattr__(
            self,
            "hypothesis_hash",
            _require_hex_digest(self.hypothesis_hash, "hypothesis_hash") if self.hypothesis_hash else "",
        )
        object.__setattr__(self, "hypothesis_type", _require_str(self.hypothesis_type, "hypothesis_type"))
        object.__setattr__(self, "status", _require_str(self.status, "status"))
        object.__setattr__(self, "dataset_hash", _require_hex_digest(self.dataset_hash, "dataset_hash"))
        object.__setattr__(self, "contract_hash", _require_hex_digest(self.contract_hash, "contract_hash"))
        object.__setattr__(
            self,
            "detection_result_hash",
            _require_hex_digest(self.detection_result_hash, "detection_result_hash"),
        )
        object.__setattr__(
            self,
            "annotation_collection_hash",
            _require_hex_digest(self.annotation_collection_hash, "annotation_collection_hash")
            if self.annotation_collection_hash
            else "",
        )
        object.__setattr__(self, "timeframe_context", _normalize_timeframe_context(self.timeframe_context, field_name="timeframe_context"))
        object.__setattr__(self, "observed_at", _require_utc_datetime(self.observed_at, "observed_at"))
        object.__setattr__(self, "effective_at", _require_utc_datetime(self.effective_at, "effective_at"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        if self.effective_at < self.observed_at:
            raise MarketStructureHypothesisValidationError("effective_at cannot precede observed_at.")
        if self.status not in MARKET_STRUCTURE_HYPOTHESIS_ALLOWED_STATUSES:
            raise MarketStructureHypothesisValidationError("status is invalid.")
        if self.hypothesis_type not in MARKET_STRUCTURE_HYPOTHESIS_ALLOWED_TYPES:
            raise MarketStructureHypothesisValidationError("hypothesis_type is invalid.")
        if not isinstance(self.metadata, Mapping):
            raise MarketStructureHypothesisValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))

        for field_name in (
            "supporting_event_ids",
            "supporting_annotation_ids",
            "contradicting_event_ids",
            "contradicting_annotation_ids",
            "invalidation_reasons",
            "ambiguity_reasons",
        ):
            value = getattr(self, field_name)
            if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set, frozenset)):
                raise MarketStructureHypothesisValidationError(f"{field_name} must be a sequence of strings.")
            normalized = _unique_sorted(tuple(_require_str(item, field_name) for item in value))
            object.__setattr__(self, field_name, normalized)

        if self.status not in MARKET_STRUCTURE_HYPOTHESIS_ALLOWED_STATUSES:
            raise MarketStructureHypothesisValidationError("status is invalid.")

        expected_id = _hash_payload(self._hypothesis_id_payload())
        if self.hypothesis_id:
            if self.hypothesis_id != expected_id:
                raise MarketStructureHypothesisIntegrityError("hypothesis_id mismatch.")
        else:
            object.__setattr__(self, "hypothesis_id", expected_id)

        expected_hash = _hash_payload(self._hypothesis_hash_payload())
        if self.hypothesis_hash:
            if self.hypothesis_hash != expected_hash:
                raise MarketStructureHypothesisIntegrityError("hypothesis_hash mismatch.")
        else:
            object.__setattr__(self, "hypothesis_hash", expected_hash)

    def _hypothesis_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "hypothesis_type": self.hypothesis_type,
            "status": self.status,
            "dataset_hash": self.dataset_hash,
            "contract_hash": self.contract_hash,
            "detection_result_hash": self.detection_result_hash,
            "annotation_collection_hash": self.annotation_collection_hash,
            "timeframe_context": _thaw_read_only_value(self.timeframe_context),
            "observed_at": _utc_iso(self.observed_at),
            "effective_at": _utc_iso(self.effective_at),
            "supporting_event_ids": self.supporting_event_ids,
            "supporting_annotation_ids": self.supporting_annotation_ids,
            "contradicting_event_ids": self.contradicting_event_ids,
            "contradicting_annotation_ids": self.contradicting_annotation_ids,
            "invalidation_reasons": self.invalidation_reasons,
            "ambiguity_reasons": self.ambiguity_reasons,
        }

    def _hypothesis_hash_payload(self) -> dict[str, Any]:
        payload = self._hypothesis_id_payload()
        payload["hypothesis_id"] = self.hypothesis_id
        return payload

    def canonical_payload(
        self,
        *,
        include_hypothesis_id: bool = True,
        include_hypothesis_hash: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "hypothesis_type": self.hypothesis_type,
            "status": self.status,
            "dataset_hash": self.dataset_hash,
            "contract_hash": self.contract_hash,
            "detection_result_hash": self.detection_result_hash,
            "annotation_collection_hash": self.annotation_collection_hash,
            "timeframe_context": _thaw_read_only_value(self.timeframe_context),
            "observed_at": _utc_iso(self.observed_at),
            "effective_at": _utc_iso(self.effective_at),
            "supporting_event_ids": self.supporting_event_ids,
            "supporting_annotation_ids": self.supporting_annotation_ids,
            "contradicting_event_ids": self.contradicting_event_ids,
            "contradicting_annotation_ids": self.contradicting_annotation_ids,
            "invalidation_reasons": self.invalidation_reasons,
            "ambiguity_reasons": self.ambiguity_reasons,
            "metadata": _thaw_read_only_value(self.metadata),
            "created_at_utc": _utc_iso(self.created_at_utc),
        }
        if include_hypothesis_id:
            payload["hypothesis_id"] = self.hypothesis_id
        if include_hypothesis_hash:
            payload["hypothesis_hash"] = self.hypothesis_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_hypothesis_id=True, include_hypothesis_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureHypothesis":
        if not isinstance(data, Mapping):
            raise MarketStructureHypothesisValidationError("market structure hypothesis must be a mapping.")
        _require_exact_keys(
            data,
            "market structure hypothesis",
            {
                "schema_version",
                "hypothesis_id",
                "hypothesis_hash",
                "hypothesis_type",
                "status",
                "dataset_hash",
                "contract_hash",
                "detection_result_hash",
                "annotation_collection_hash",
                "timeframe_context",
                "observed_at",
                "effective_at",
                "supporting_event_ids",
                "supporting_annotation_ids",
                "contradicting_event_ids",
                "contradicting_annotation_ids",
                "invalidation_reasons",
                "ambiguity_reasons",
                "metadata",
                "created_at_utc",
            },
        )
        try:
            return cls(
                schema_version=data["schema_version"],
                hypothesis_id=data.get("hypothesis_id", ""),
                hypothesis_hash=data.get("hypothesis_hash", ""),
                hypothesis_type=data["hypothesis_type"],
                status=data["status"],
                dataset_hash=data["dataset_hash"],
                contract_hash=data["contract_hash"],
                detection_result_hash=data["detection_result_hash"],
                annotation_collection_hash=data.get("annotation_collection_hash", ""),
                timeframe_context=data["timeframe_context"],
                observed_at=data["observed_at"],
                effective_at=data["effective_at"],
                supporting_event_ids=data["supporting_event_ids"],
                supporting_annotation_ids=data["supporting_annotation_ids"],
                contradicting_event_ids=data["contradicting_event_ids"],
                contradicting_annotation_ids=data["contradicting_annotation_ids"],
                invalidation_reasons=data["invalidation_reasons"],
                ambiguity_reasons=data["ambiguity_reasons"],
                metadata=data.get("metadata", {}),
                created_at_utc=data["created_at_utc"],
            )
        except KeyError as exc:
            raise MarketStructureHypothesisValidationError("market structure hypothesis is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class MarketStructureHypothesisEvaluation:
    schema_version: int
    evaluation_id: str = ""
    evaluation_hash: str = ""
    dataset_hash: str = ""
    contract_hash: str = ""
    detection_result_hash: str = ""
    annotation_collection_hash: str = ""
    hypotheses: tuple[MarketStructureHypothesis, ...] = field(default_factory=tuple, repr=False)
    ambiguity_state: str = "indeterminate"
    timeframe_context: Mapping[str, Any] = field(default_factory=dict, repr=False)
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(
            self,
            "evaluation_id",
            _require_hex_digest(self.evaluation_id, "evaluation_id") if self.evaluation_id else "",
        )
        object.__setattr__(
            self,
            "evaluation_hash",
            _require_hex_digest(self.evaluation_hash, "evaluation_hash") if self.evaluation_hash else "",
        )
        object.__setattr__(self, "dataset_hash", _require_hex_digest(self.dataset_hash, "dataset_hash"))
        object.__setattr__(self, "contract_hash", _require_hex_digest(self.contract_hash, "contract_hash"))
        object.__setattr__(
            self,
            "detection_result_hash",
            _require_hex_digest(self.detection_result_hash, "detection_result_hash"),
        )
        object.__setattr__(
            self,
            "annotation_collection_hash",
            _require_hex_digest(self.annotation_collection_hash, "annotation_collection_hash"),
        )
        object.__setattr__(self, "ambiguity_state", _require_str(self.ambiguity_state, "ambiguity_state").lower())
        if self.ambiguity_state not in MARKET_STRUCTURE_HYPOTHESIS_ALLOWED_ALIGNMENT_STATES:
            raise MarketStructureHypothesisValidationError("ambiguity_state is invalid.")
        object.__setattr__(self, "timeframe_context", _normalize_timeframe_context(self.timeframe_context, field_name="timeframe_context"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        if not isinstance(self.metadata, Mapping):
            raise MarketStructureHypothesisValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))

        normalized_hypotheses: list[MarketStructureHypothesis] = []
        for hypothesis in self.hypotheses:
            if isinstance(hypothesis, MarketStructureHypothesis):
                normalized_hypotheses.append(hypothesis)
            elif isinstance(hypothesis, Mapping):
                normalized_hypotheses.append(MarketStructureHypothesis.from_dict(hypothesis))
            else:
                raise MarketStructureHypothesisValidationError("hypotheses must contain market structure hypotheses.")
        if not normalized_hypotheses:
            raise MarketStructureHypothesisValidationError("hypotheses must not be empty.")
        ordered_hypotheses = tuple(
            sorted(
                normalized_hypotheses,
                key=lambda hypothesis: (
                    _canonical_hypothesis_type_order(hypothesis.hypothesis_type),
                    _utc_iso(hypothesis.observed_at),
                    hypothesis.hypothesis_id,
                ),
            )
        )
        object.__setattr__(self, "hypotheses", ordered_hypotheses)

        for hypothesis in ordered_hypotheses:
            if hypothesis.annotation_collection_hash != self.annotation_collection_hash:
                raise MarketStructureHypothesisValidationError(
                    "hypotheses annotation_collection_hash mismatch."
                )

        expected_id = _hash_payload(self._evaluation_id_payload())
        if self.evaluation_id:
            if self.evaluation_id != expected_id:
                raise MarketStructureHypothesisIntegrityError("evaluation_id mismatch.")
        else:
            object.__setattr__(self, "evaluation_id", expected_id)

        expected_hash = _hash_payload(self._evaluation_hash_payload())
        if self.evaluation_hash:
            if self.evaluation_hash != expected_hash:
                raise MarketStructureHypothesisIntegrityError("evaluation_hash mismatch.")
        else:
            object.__setattr__(self, "evaluation_hash", expected_hash)

    def _evaluation_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dataset_hash": self.dataset_hash,
            "contract_hash": self.contract_hash,
            "detection_result_hash": self.detection_result_hash,
            "annotation_collection_hash": self.annotation_collection_hash,
            "hypotheses": [hypothesis._hypothesis_hash_payload() for hypothesis in self.hypotheses],
            "ambiguity_state": self.ambiguity_state,
            "timeframe_context": _thaw_read_only_value(self.timeframe_context),
        }

    def _evaluation_hash_payload(self) -> dict[str, Any]:
        payload = self._evaluation_id_payload()
        payload["evaluation_id"] = self.evaluation_id
        return payload

    def canonical_payload(
        self,
        *,
        include_evaluation_id: bool = True,
        include_evaluation_hash: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "dataset_hash": self.dataset_hash,
            "contract_hash": self.contract_hash,
            "detection_result_hash": self.detection_result_hash,
            "annotation_collection_hash": self.annotation_collection_hash,
            "hypotheses": [hypothesis.canonical_payload() for hypothesis in self.hypotheses],
            "ambiguity_state": self.ambiguity_state,
            "timeframe_context": _thaw_read_only_value(self.timeframe_context),
            "metadata": _thaw_read_only_value(self.metadata),
            "created_at_utc": _utc_iso(self.created_at_utc),
        }
        if include_evaluation_id:
            payload["evaluation_id"] = self.evaluation_id
        if include_evaluation_hash:
            payload["evaluation_hash"] = self.evaluation_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_evaluation_id=True, include_evaluation_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureHypothesisEvaluation":
        if not isinstance(data, Mapping):
            raise MarketStructureHypothesisValidationError("market structure hypothesis evaluation must be a mapping.")
        _require_exact_keys(
            data,
            "market structure hypothesis evaluation",
            {
                "schema_version",
                "evaluation_id",
                "evaluation_hash",
                "dataset_hash",
                "contract_hash",
                "detection_result_hash",
                "annotation_collection_hash",
                "hypotheses",
                "ambiguity_state",
                "timeframe_context",
                "metadata",
                "created_at_utc",
            },
        )
        try:
            return cls(
                schema_version=data["schema_version"],
                evaluation_id=data.get("evaluation_id", ""),
                evaluation_hash=data.get("evaluation_hash", ""),
                dataset_hash=data["dataset_hash"],
                contract_hash=data["contract_hash"],
                detection_result_hash=data["detection_result_hash"],
                annotation_collection_hash=data["annotation_collection_hash"],
                hypotheses=data["hypotheses"],
                ambiguity_state=data["ambiguity_state"],
                timeframe_context=data["timeframe_context"],
                metadata=data.get("metadata", {}),
                created_at_utc=data["created_at_utc"],
            )
        except KeyError as exc:
            raise MarketStructureHypothesisValidationError(
                "market structure hypothesis evaluation is incomplete."
            ) from exc


def build_market_structure_hypothesis(
    *,
    annotation: phase52.MarketStructureAnnotation,
    hypothesis_type: str,
    metadata: Mapping[str, Any] | None = None,
    created_at_utc: datetime | None = None,
    annotation_collection_hash: str = "",
) -> MarketStructureHypothesis:
    created_at_utc = created_at_utc or datetime.now(timezone.utc)
    payload = _build_hypothesis_payload(
        annotation=annotation,
        hypothesis_type=hypothesis_type,
        created_at_utc=created_at_utc,
        metadata=metadata or {},
        annotation_collection_hash=annotation_collection_hash,
    )
    return MarketStructureHypothesis(
        schema_version=MARKET_STRUCTURE_HYPOTHESIS_SCHEMA_VERSION,
        hypothesis_type=hypothesis_type,
        status=payload["status"],
        dataset_hash=payload["dataset_hash"],
        contract_hash=payload["contract_hash"],
        detection_result_hash=payload["detection_result_hash"],
        annotation_collection_hash=payload["annotation_collection_hash"],
        timeframe_context=payload["timeframe_context"],
        observed_at=payload["observed_at"],
        effective_at=payload["effective_at"],
        supporting_event_ids=payload["supporting_event_ids"],
        supporting_annotation_ids=payload["supporting_annotation_ids"],
        contradicting_event_ids=payload["contradicting_event_ids"],
        contradicting_annotation_ids=payload["contradicting_annotation_ids"],
        invalidation_reasons=payload["invalidation_reasons"],
        ambiguity_reasons=payload["ambiguity_reasons"],
        metadata=payload["metadata"],
        created_at_utc=payload["created_at_utc"],
    )


def verify_market_structure_hypothesis(
    hypothesis: MarketStructureHypothesis,
) -> MarketStructureHypothesis:
    if not isinstance(hypothesis, MarketStructureHypothesis):
        raise MarketStructureHypothesisValidationError("market structure hypothesis is required.")
    expected_id = _hash_payload(hypothesis._hypothesis_id_payload())
    if hypothesis.hypothesis_id != expected_id:
        raise MarketStructureHypothesisIntegrityError("hypothesis_id mismatch.")
    expected_hash = _hash_payload(hypothesis._hypothesis_hash_payload())
    if hypothesis.hypothesis_hash != expected_hash:
        raise MarketStructureHypothesisIntegrityError("hypothesis_hash mismatch.")
    return hypothesis


def _evaluate_hypotheses_for_annotation(
    annotation: phase52.MarketStructureAnnotation,
    *,
    annotation_collection_hash: str,
    metadata: Mapping[str, Any] | None = None,
    created_at_utc: datetime | None = None,
) -> tuple[MarketStructureHypothesis, ...]:
    hypothesis_types = _hypothesis_types_for_annotation(annotation)
    hypotheses = tuple(
        build_market_structure_hypothesis(
            annotation=annotation,
            hypothesis_type=hypothesis_type,
            metadata=metadata or {},
            created_at_utc=created_at_utc,
            annotation_collection_hash=annotation_collection_hash,
        )
        for hypothesis_type in hypothesis_types
    )
    return hypotheses


def _unknown_hypothesis_semantic_payload(hypothesis: MarketStructureHypothesis) -> dict[str, Any]:
    payload = hypothesis.canonical_payload(include_hypothesis_id=False, include_hypothesis_hash=False)
    return {
        "schema_version": payload["schema_version"],
        "hypothesis_type": payload["hypothesis_type"],
        "status": payload["status"],
        "dataset_hash": payload["dataset_hash"],
        "contract_hash": payload["contract_hash"],
        "detection_result_hash": payload["detection_result_hash"],
        "annotation_collection_hash": payload["annotation_collection_hash"],
        "timeframe_context": payload["timeframe_context"],
        "supporting_event_ids": payload["supporting_event_ids"],
        "contradicting_event_ids": payload["contradicting_event_ids"],
        "invalidation_reasons": payload["invalidation_reasons"],
        "ambiguity_reasons": payload["ambiguity_reasons"],
    }

def _canonicalize_unknown_hypotheses(
    hypotheses: Sequence[MarketStructureHypothesis],
) -> tuple[MarketStructureHypothesis, ...]:
    grouped: dict[str, list[MarketStructureHypothesis]] = {}
    canonical_hypotheses: list[MarketStructureHypothesis] = []

    for hypothesis in hypotheses:
        if hypothesis.hypothesis_type != "Unknown":
            canonical_hypotheses.append(hypothesis)
            continue
        semantic_key = _canonical_json(_unknown_hypothesis_semantic_payload(hypothesis))
        grouped.setdefault(semantic_key, []).append(hypothesis)

    for semantic_key in sorted(grouped):
        grouped_hypotheses = grouped[semantic_key]
        if len(grouped_hypotheses) == 1:
            canonical_hypotheses.append(grouped_hypotheses[0])
            continue

        ordered_group = sorted(
            grouped_hypotheses,
            key=lambda item: (
                _utc_iso(item.observed_at),
                _utc_iso(item.effective_at),
                item.hypothesis_id,
                item.hypothesis_hash,
            ),
        )
        representative = ordered_group[0]
        canonical_hypotheses.append(
            replace(
                representative,
                observed_at=ordered_group[0].observed_at,
                effective_at=ordered_group[0].effective_at,
                created_at_utc=ordered_group[0].created_at_utc,
                supporting_event_ids=tuple(
                    sorted({event_id for item in grouped_hypotheses for event_id in item.supporting_event_ids})
                ),
                supporting_annotation_ids=tuple(
                    sorted({annotation_id for item in grouped_hypotheses for annotation_id in item.supporting_annotation_ids})
                ),
                contradicting_event_ids=tuple(
                    sorted({event_id for item in grouped_hypotheses for event_id in item.contradicting_event_ids})
                ),
                contradicting_annotation_ids=tuple(
                    sorted({annotation_id for item in grouped_hypotheses for annotation_id in item.contradicting_annotation_ids})
                ),
                invalidation_reasons=tuple(
                    sorted({reason for item in grouped_hypotheses for reason in item.invalidation_reasons})
                ),
                ambiguity_reasons=tuple(
                    sorted({reason for item in grouped_hypotheses for reason in item.ambiguity_reasons})
                ),
                hypothesis_id="",
                hypothesis_hash="",
            )
        )

    return tuple(canonical_hypotheses)

def evaluate_market_structure_hypotheses(
    annotation_collection: phase52.MarketStructureAnnotationCollection,
    *,
    metadata: Mapping[str, Any] | None = None,
    created_at_utc: datetime | None = None,
) -> MarketStructureHypothesisEvaluation:
    verified_collection = phase52.verify_market_structure_annotation_collection(annotation_collection)
    created_at_utc = created_at_utc or datetime.now(timezone.utc)

    hypotheses: list[MarketStructureHypothesis] = []
    for annotation in verified_collection.annotations:
        hypotheses.extend(
            _evaluate_hypotheses_for_annotation(
                annotation,
                annotation_collection_hash=verified_collection.collection_hash,
                metadata=metadata,
                created_at_utc=created_at_utc,
            )
        )
    hypotheses = list(_canonicalize_unknown_hypotheses(hypotheses))
    if not hypotheses:
        raise MarketStructureHypothesisValidationError("hypotheses must not be empty.")

    evaluation_context = _annotation_timeframe_context(verified_collection.annotations[0])
    if any(
        _annotation_timeframe_context(annotation) != evaluation_context
        for annotation in verified_collection.annotations[1:]
    ):
        raise MarketStructureHypothesisValidationError("annotations must share the same timeframe context.")

    evaluation = MarketStructureHypothesisEvaluation(
        schema_version=MARKET_STRUCTURE_HYPOTHESIS_EVALUATION_SCHEMA_VERSION,
        dataset_hash=verified_collection.dataset_hash,
        contract_hash=verified_collection.contract_hash,
        detection_result_hash=verified_collection.detection_result_hash,
        annotation_collection_hash=verified_collection.collection_hash,
        hypotheses=tuple(hypotheses),
        ambiguity_state=evaluation_context["alignment_state"],
        timeframe_context=evaluation_context,
        metadata=metadata or {},
        created_at_utc=created_at_utc,
    )
    return verify_market_structure_hypothesis_evaluation(evaluation)


def verify_market_structure_hypothesis_evaluation(
    evaluation: MarketStructureHypothesisEvaluation,
) -> MarketStructureHypothesisEvaluation:
    if not isinstance(evaluation, MarketStructureHypothesisEvaluation):
        raise MarketStructureHypothesisValidationError("market structure hypothesis evaluation is required.")
    for hypothesis in evaluation.hypotheses:
        verify_market_structure_hypothesis(hypothesis)
        if hypothesis.dataset_hash != evaluation.dataset_hash:
            raise MarketStructureHypothesisValidationError("hypothesis dataset_hash mismatch.")
        if hypothesis.contract_hash != evaluation.contract_hash:
            raise MarketStructureHypothesisValidationError("hypothesis contract_hash mismatch.")
        if hypothesis.detection_result_hash != evaluation.detection_result_hash:
            raise MarketStructureHypothesisValidationError("hypothesis detection_result_hash mismatch.")
        if hypothesis.annotation_collection_hash != evaluation.annotation_collection_hash:
            raise MarketStructureHypothesisValidationError("hypothesis annotation_collection_hash mismatch.")
        if hypothesis.timeframe_context != evaluation.timeframe_context:
            raise MarketStructureHypothesisValidationError("hypothesis timeframe_context mismatch.")
    expected_id = _hash_payload(evaluation._evaluation_id_payload())
    if evaluation.evaluation_id != expected_id:
        raise MarketStructureHypothesisIntegrityError("evaluation_id mismatch.")
    expected_hash = _hash_payload(evaluation._evaluation_hash_payload())
    if evaluation.evaluation_hash != expected_hash:
        raise MarketStructureHypothesisIntegrityError("evaluation_hash mismatch.")
    return evaluation


def market_structure_hypothesis_to_dict(hypothesis: MarketStructureHypothesis) -> dict[str, Any]:
    if not isinstance(hypothesis, MarketStructureHypothesis):
        raise MarketStructureHypothesisValidationError("market structure hypothesis is required.")
    return hypothesis.as_dict()


def market_structure_hypothesis_from_dict(data: Mapping[str, Any]) -> MarketStructureHypothesis:
    return MarketStructureHypothesis.from_dict(data)


def market_structure_hypothesis_evaluation_to_dict(
    evaluation: MarketStructureHypothesisEvaluation,
) -> dict[str, Any]:
    if not isinstance(evaluation, MarketStructureHypothesisEvaluation):
        raise MarketStructureHypothesisValidationError("market structure hypothesis evaluation is required.")
    return evaluation.as_dict()


def market_structure_hypothesis_evaluation_from_dict(
    data: Mapping[str, Any],
) -> MarketStructureHypothesisEvaluation:
    return MarketStructureHypothesisEvaluation.from_dict(data)


__all__ = [
    "MARKET_STRUCTURE_HYPOTHESIS_ALLOWED_ALIGNMENT_STATES",
    "MARKET_STRUCTURE_HYPOTHESIS_ALLOWED_STATUSES",
    "MARKET_STRUCTURE_HYPOTHESIS_ALLOWED_TYPES",
    "MARKET_STRUCTURE_HYPOTHESIS_EVALUATION_ID",
    "MARKET_STRUCTURE_HYPOTHESIS_EVALUATION_SCHEMA_VERSION",
    "MARKET_STRUCTURE_HYPOTHESIS_EVALUATION_VERSION",
    "MARKET_STRUCTURE_HYPOTHESIS_ID",
    "MARKET_STRUCTURE_HYPOTHESIS_SCHEMA_VERSION",
    "MARKET_STRUCTURE_HYPOTHESIS_VERSION",
    "MarketStructureHypothesis",
    "MarketStructureHypothesisError",
    "MarketStructureHypothesisEvaluation",
    "MarketStructureHypothesisIntegrityError",
    "MarketStructureHypothesisValidationError",
    "build_market_structure_hypothesis",
    "evaluate_market_structure_hypotheses",
    "market_structure_hypothesis_evaluation_from_dict",
    "market_structure_hypothesis_evaluation_to_dict",
    "market_structure_hypothesis_from_dict",
    "market_structure_hypothesis_to_dict",
    "verify_market_structure_hypothesis",
    "verify_market_structure_hypothesis_evaluation",
]
