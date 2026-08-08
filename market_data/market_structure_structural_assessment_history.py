from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value

from .errors import HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError
from . import market_structure_temporal_validation as phase56

MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_SCHEMA_VERSION = 1
MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_ID = "market_structure_structural_assessment_history"
MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_VERSION = "phase57_structural_assessment_history_v1"
MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_NON_OPERATIONAL_DECLARATION = (
    "This structural assessment history is research-only and does not authorize replay, backtest, walk-forward, "
    "performance evaluation, ranking, scoring, paper trading, live trading, exchange connectivity, execution, "
    "or order submission."
)


class MarketStructureStructuralAssessmentHistoryError(HistoricalDataError):
    pass


class MarketStructureStructuralAssessmentHistoryValidationError(
    MarketStructureStructuralAssessmentHistoryError,
    HistoricalDataValidationError,
):
    pass


class MarketStructureStructuralAssessmentHistoryIntegrityError(
    MarketStructureStructuralAssessmentHistoryError,
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
        raise MarketStructureStructuralAssessmentHistoryValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketStructureStructuralAssessmentHistoryValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise MarketStructureStructuralAssessmentHistoryValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise MarketStructureStructuralAssessmentHistoryValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise MarketStructureStructuralAssessmentHistoryValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise MarketStructureStructuralAssessmentHistoryValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise MarketStructureStructuralAssessmentHistoryValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketStructureStructuralAssessmentHistoryValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
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


def _normalize_transition(value: Any, field_name: str) -> phase56.MarketStructureStructuralAssessmentTransition:
    if isinstance(value, Mapping):
        return phase56.market_structure_structural_assessment_transition_from_dict(value)
    if not isinstance(value, phase56.MarketStructureStructuralAssessmentTransition):
        raise MarketStructureStructuralAssessmentHistoryValidationError(
            f"{field_name} must contain market structure structural assessment transitions."
        )
    return value


def _normalize_transitions(
    value: Any,
    field_name: str = "transitions",
) -> tuple[phase56.MarketStructureStructuralAssessmentTransition, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise MarketStructureStructuralAssessmentHistoryValidationError(
            f"{field_name} must be a sequence of transitions."
        )
    normalized = tuple(_normalize_transition(item, field_name) for item in value)
    return normalized


def _transition_identity_payload(
    transition: phase56.MarketStructureStructuralAssessmentTransition,
) -> dict[str, Any]:
    payload = transition.canonical_payload(include_transition_id=True, include_transition_hash=True)
    payload.pop("created_at_utc", None)
    return payload


def _history_sequence_payload(
    transitions: Sequence[phase56.MarketStructureStructuralAssessmentTransition],
) -> list[dict[str, Any]]:
    return [_transition_identity_payload(transition) for transition in transitions]


def _normalize_metadata(value: Any, field_name: str = "metadata") -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MarketStructureStructuralAssessmentHistoryValidationError(f"{field_name} must be a mapping.")
    return _freeze_read_only_value(dict(value))


def _validate_transitions(
    transitions: tuple[phase56.MarketStructureStructuralAssessmentTransition, ...],
    *,
    hypothesis_id: str,
    hypothesis_hash: str,
) -> tuple[
    str,
    str,
    int,
    str | None,
    str | None,
    str | None,
    str | None,
]:
    if not transitions:
        if not hypothesis_id or not hypothesis_hash:
            raise MarketStructureStructuralAssessmentHistoryValidationError(
                "hypothesis_id and hypothesis_hash are required for an empty history."
            )
        return hypothesis_id, hypothesis_hash, 0, None, None, None, None

    first_transition = transitions[0]
    resolved_hypothesis_id = hypothesis_id or first_transition.hypothesis_id
    resolved_hypothesis_hash = hypothesis_hash or first_transition.hypothesis_hash
    if not resolved_hypothesis_id or not resolved_hypothesis_hash:
        raise MarketStructureStructuralAssessmentHistoryValidationError(
            "hypothesis_id and hypothesis_hash are required."
        )

    seen_transition_ids: set[str] = set()
    seen_transition_hashes: set[str] = set()
    seen_assessment_ids: set[str] = set()
    seen_assessment_hashes: set[str] = set()
    previous_current_assessment_id: str | None = None
    previous_current_assessment_hash: str | None = None
    first_transition_id: str | None = None
    first_transition_hash: str | None = None
    last_transition_id: str | None = None
    last_transition_hash: str | None = None

    for index, transition in enumerate(transitions):
        verified_transition = phase56.verify_market_structure_structural_assessment_transition(transition)
        if verified_transition.hypothesis_id != resolved_hypothesis_id:
            raise MarketStructureStructuralAssessmentHistoryValidationError("cross-hypothesis transitions are not allowed.")
        if verified_transition.hypothesis_hash != resolved_hypothesis_hash:
            raise MarketStructureStructuralAssessmentHistoryValidationError("cross-hypothesis transitions are not allowed.")
        if index == 0:
            pass
        else:
            assert previous_current_assessment_id is not None
            assert previous_current_assessment_hash is not None
            if verified_transition.previous_assessment_id != previous_current_assessment_id:
                raise MarketStructureStructuralAssessmentHistoryValidationError("chain break detected.")
            if verified_transition.previous_assessment_hash != previous_current_assessment_hash:
                raise MarketStructureStructuralAssessmentHistoryValidationError("chain break detected.")

        previous_assessment_id = verified_transition.previous_assessment_id
        previous_assessment_hash = verified_transition.previous_assessment_hash
        if previous_assessment_id not in seen_assessment_ids:
            seen_assessment_ids.add(previous_assessment_id)
        if previous_assessment_hash not in seen_assessment_hashes:
            seen_assessment_hashes.add(previous_assessment_hash)

        if verified_transition.transition_id in seen_transition_ids:
            raise MarketStructureStructuralAssessmentHistoryValidationError("duplicate transition detected.")
        if verified_transition.transition_hash in seen_transition_hashes:
            raise MarketStructureStructuralAssessmentHistoryValidationError("duplicate transition detected.")

        current_assessment_id = verified_transition.current_assessment_id
        current_assessment_hash = verified_transition.current_assessment_hash
        if current_assessment_id in seen_assessment_ids and current_assessment_id != previous_assessment_id:
            raise MarketStructureStructuralAssessmentHistoryValidationError("cycle detected.")
        if current_assessment_hash in seen_assessment_hashes and current_assessment_hash != previous_assessment_hash:
            raise MarketStructureStructuralAssessmentHistoryValidationError("cycle detected.")

        seen_transition_ids.add(verified_transition.transition_id)
        seen_transition_hashes.add(verified_transition.transition_hash)
        seen_assessment_ids.add(current_assessment_id)
        seen_assessment_hashes.add(current_assessment_hash)
        previous_current_assessment_id = current_assessment_id
        previous_current_assessment_hash = current_assessment_hash
        if first_transition_id is None:
            first_transition_id = verified_transition.transition_id
            first_transition_hash = verified_transition.transition_hash
        last_transition_id = verified_transition.transition_id
        last_transition_hash = verified_transition.transition_hash

    return (
        resolved_hypothesis_id,
        resolved_hypothesis_hash,
        len(transitions),
        first_transition_id,
        first_transition_hash,
        last_transition_id,
        last_transition_hash,
    )


@dataclass(frozen=True, slots=True)
class MarketStructureStructuralAssessmentHistory:
    schema_version: int = MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_SCHEMA_VERSION
    history_id: str = ""
    history_hash: str = ""
    hypothesis_id: str = ""
    hypothesis_hash: str = ""
    transition_count: int = 0
    first_transition_id: str | None = None
    first_transition_hash: str | None = None
    last_transition_id: str | None = None
    last_transition_hash: str | None = None
    transitions: tuple[phase56.MarketStructureStructuralAssessmentTransition, ...] = field(default_factory=tuple, repr=False)
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "history_id", _require_hex_digest(self.history_id, "history_id") if self.history_id else "")
        object.__setattr__(self, "history_hash", _require_hex_digest(self.history_hash, "history_hash") if self.history_hash else "")
        object.__setattr__(self, "hypothesis_id", _require_hex_digest(self.hypothesis_id, "hypothesis_id") if self.hypothesis_id else "")
        object.__setattr__(self, "hypothesis_hash", _require_hex_digest(self.hypothesis_hash, "hypothesis_hash") if self.hypothesis_hash else "")
        object.__setattr__(self, "transition_count", _require_int(self.transition_count, "transition_count"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "metadata", _normalize_metadata(self.metadata))
        transitions = _normalize_transitions(self.transitions)
        object.__setattr__(self, "transitions", transitions)

        if self.schema_version != MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_SCHEMA_VERSION:
            raise MarketStructureStructuralAssessmentHistoryValidationError("schema_version must be 1.")

        (
            resolved_hypothesis_id,
            resolved_hypothesis_hash,
            derived_transition_count,
            first_transition_id,
            first_transition_hash,
            last_transition_id,
            last_transition_hash,
        ) = _validate_transitions(
            transitions,
            hypothesis_id=self.hypothesis_id,
            hypothesis_hash=self.hypothesis_hash,
        )
        object.__setattr__(self, "hypothesis_id", resolved_hypothesis_id)
        object.__setattr__(self, "hypothesis_hash", resolved_hypothesis_hash)

        if self.transition_count and self.transition_count != derived_transition_count:
            raise MarketStructureStructuralAssessmentHistoryValidationError("transition_count mismatch.")
        object.__setattr__(self, "transition_count", derived_transition_count)

        if self.first_transition_id is None:
            object.__setattr__(self, "first_transition_id", first_transition_id)
        elif self.first_transition_id != first_transition_id:
            raise MarketStructureStructuralAssessmentHistoryIntegrityError("first_transition_id mismatch.")
        if self.first_transition_hash is None:
            object.__setattr__(self, "first_transition_hash", first_transition_hash)
        elif self.first_transition_hash != first_transition_hash:
            raise MarketStructureStructuralAssessmentHistoryIntegrityError("first_transition_hash mismatch.")
        if self.last_transition_id is None:
            object.__setattr__(self, "last_transition_id", last_transition_id)
        elif self.last_transition_id != last_transition_id:
            raise MarketStructureStructuralAssessmentHistoryIntegrityError("last_transition_id mismatch.")
        if self.last_transition_hash is None:
            object.__setattr__(self, "last_transition_hash", last_transition_hash)
        elif self.last_transition_hash != last_transition_hash:
            raise MarketStructureStructuralAssessmentHistoryIntegrityError("last_transition_hash mismatch.")

        if transitions:
            if self.first_transition_id != transitions[0].transition_id:
                raise MarketStructureStructuralAssessmentHistoryIntegrityError("first transition mismatch.")
            if self.first_transition_hash != transitions[0].transition_hash:
                raise MarketStructureStructuralAssessmentHistoryIntegrityError("first transition hash mismatch.")
            if self.last_transition_id != transitions[-1].transition_id:
                raise MarketStructureStructuralAssessmentHistoryIntegrityError("last transition mismatch.")
            if self.last_transition_hash != transitions[-1].transition_hash:
                raise MarketStructureStructuralAssessmentHistoryIntegrityError("last transition hash mismatch.")
        else:
            if self.first_transition_id is not None or self.first_transition_hash is not None:
                raise MarketStructureStructuralAssessmentHistoryValidationError("empty history must not define first transition.")
            if self.last_transition_id is not None or self.last_transition_hash is not None:
                raise MarketStructureStructuralAssessmentHistoryValidationError("empty history must not define last transition.")

        expected_history_id = _hash_payload(self._history_id_payload())
        if self.history_id:
            if self.history_id != expected_history_id:
                raise MarketStructureStructuralAssessmentHistoryIntegrityError("history_id mismatch.")
        else:
            object.__setattr__(self, "history_id", expected_history_id)

        expected_history_hash = _hash_payload(self._history_hash_payload())
        if self.history_hash:
            if self.history_hash != expected_history_hash:
                raise MarketStructureStructuralAssessmentHistoryIntegrityError("history_hash mismatch.")
        else:
            object.__setattr__(self, "history_hash", expected_history_hash)

    def _history_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_hash": self.hypothesis_hash,
            "transition_count": self.transition_count,
            "first_transition_id": self.first_transition_id,
            "first_transition_hash": self.first_transition_hash,
            "last_transition_id": self.last_transition_id,
            "last_transition_hash": self.last_transition_hash,
            "transitions": _history_sequence_payload(self.transitions),
            "metadata": _thaw_read_only_value(self.metadata),
        }

    def _history_hash_payload(self) -> dict[str, Any]:
        payload = self._history_id_payload()
        payload["history_id"] = self.history_id
        return payload

    def canonical_payload(self, *, include_history_id: bool = True, include_history_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "hypothesis_id": self.hypothesis_id,
            "hypothesis_hash": self.hypothesis_hash,
            "transition_count": self.transition_count,
            "first_transition_id": self.first_transition_id,
            "first_transition_hash": self.first_transition_hash,
            "last_transition_id": self.last_transition_id,
            "last_transition_hash": self.last_transition_hash,
            "transitions": [transition.as_dict() for transition in self.transitions],
            "metadata": _thaw_read_only_value(self.metadata),
            "created_at_utc": _utc_iso(self.created_at_utc),
        }
        if include_history_id:
            payload["history_id"] = self.history_id
        if include_history_hash:
            payload["history_hash"] = self.history_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_history_id=True, include_history_hash=True))


def build_market_structure_structural_assessment_history(
    transitions: Sequence[phase56.MarketStructureStructuralAssessmentTransition | Mapping[str, Any]] = (),
    *,
    hypothesis_id: str = "",
    hypothesis_hash: str = "",
    created_at_utc: datetime | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> MarketStructureStructuralAssessmentHistory:
    normalized_transitions = tuple(
        _normalize_transition(transition, "transitions") for transition in transitions
    )
    history = MarketStructureStructuralAssessmentHistory(
        schema_version=MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_SCHEMA_VERSION,
        hypothesis_id=hypothesis_id,
        hypothesis_hash=hypothesis_hash,
        transition_count=len(normalized_transitions),
        first_transition_id=None,
        first_transition_hash=None,
        last_transition_id=None,
        last_transition_hash=None,
        transitions=normalized_transitions,
        metadata=metadata or {},
        created_at_utc=created_at_utc or (
            normalized_transitions[-1].created_at_utc if normalized_transitions else datetime.now(timezone.utc)
        ),
    )
    return verify_market_structure_structural_assessment_history(history)


def verify_market_structure_structural_assessment_history(
    history: MarketStructureStructuralAssessmentHistory,
) -> MarketStructureStructuralAssessmentHistory:
    if not isinstance(history, MarketStructureStructuralAssessmentHistory):
        raise MarketStructureStructuralAssessmentHistoryValidationError(
            "market structure structural assessment history is required."
        )
    normalized_transitions = _normalize_transitions(history.transitions)
    for transition in normalized_transitions:
        phase56.verify_market_structure_structural_assessment_transition(transition)
    expected_id = _hash_payload(
        {
            "schema_version": history.schema_version,
            "hypothesis_id": history.hypothesis_id,
            "hypothesis_hash": history.hypothesis_hash,
            "transition_count": history.transition_count,
            "first_transition_id": history.first_transition_id,
            "first_transition_hash": history.first_transition_hash,
            "last_transition_id": history.last_transition_id,
            "last_transition_hash": history.last_transition_hash,
            "transitions": _history_sequence_payload(normalized_transitions),
            "metadata": _thaw_read_only_value(history.metadata),
        }
    )
    if history.history_id != expected_id:
        raise MarketStructureStructuralAssessmentHistoryIntegrityError("history_id mismatch.")
    expected_hash = _hash_payload(
        {
            "schema_version": history.schema_version,
            "hypothesis_id": history.hypothesis_id,
            "hypothesis_hash": history.hypothesis_hash,
            "transition_count": history.transition_count,
            "first_transition_id": history.first_transition_id,
            "first_transition_hash": history.first_transition_hash,
            "last_transition_id": history.last_transition_id,
            "last_transition_hash": history.last_transition_hash,
            "transitions": _history_sequence_payload(normalized_transitions),
            "metadata": _thaw_read_only_value(history.metadata),
            "history_id": history.history_id,
        }
    )
    if history.history_hash != expected_hash:
        raise MarketStructureStructuralAssessmentHistoryIntegrityError("history_hash mismatch.")
    return history


def append_market_structure_structural_assessment_transition(
    history: MarketStructureStructuralAssessmentHistory | Mapping[str, Any],
    transition: phase56.MarketStructureStructuralAssessmentTransition | Mapping[str, Any],
    *,
    created_at_utc: datetime | None = None,
) -> MarketStructureStructuralAssessmentHistory:
    if isinstance(history, Mapping):
        history = market_structure_structural_assessment_history_from_dict(history)
    if not isinstance(history, MarketStructureStructuralAssessmentHistory):
        raise MarketStructureStructuralAssessmentHistoryValidationError(
            "market structure structural assessment history is required."
        )
    normalized_transition = _normalize_transition(transition, "transition")
    candidate_transitions = history.transitions + (normalized_transition,)
    return build_market_structure_structural_assessment_history(
        candidate_transitions,
        hypothesis_id=history.hypothesis_id,
        hypothesis_hash=history.hypothesis_hash,
        created_at_utc=created_at_utc or normalized_transition.created_at_utc,
        metadata=_thaw_read_only_value(history.metadata),
    )


def market_structure_structural_assessment_history_to_dict(
    history: MarketStructureStructuralAssessmentHistory,
) -> dict[str, Any]:
    if not isinstance(history, MarketStructureStructuralAssessmentHistory):
        raise MarketStructureStructuralAssessmentHistoryValidationError(
            "market structure structural assessment history is required."
        )
    return history.as_dict()


def market_structure_structural_assessment_history_from_dict(
    data: Mapping[str, Any],
) -> MarketStructureStructuralAssessmentHistory:
    if not isinstance(data, Mapping):
        raise MarketStructureStructuralAssessmentHistoryValidationError(
            "market structure structural assessment history must be a mapping."
        )
    allowed = {
        "schema_version",
        "history_id",
        "history_hash",
        "hypothesis_id",
        "hypothesis_hash",
        "transition_count",
        "first_transition_id",
        "first_transition_hash",
        "last_transition_id",
        "last_transition_hash",
        "transitions",
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
        raise MarketStructureStructuralAssessmentHistoryValidationError(
            f"market structure structural assessment history has invalid fields: {'; '.join(parts)}."
        )
    try:
        transitions = tuple(
            phase56.market_structure_structural_assessment_transition_from_dict(transition)
            for transition in data["transitions"]
        )
        return MarketStructureStructuralAssessmentHistory(
            schema_version=data["schema_version"],
            history_id=data.get("history_id", ""),
            history_hash=data.get("history_hash", ""),
            hypothesis_id=data.get("hypothesis_id", ""),
            hypothesis_hash=data.get("hypothesis_hash", ""),
            transition_count=data.get("transition_count", 0),
            first_transition_id=data.get("first_transition_id"),
            first_transition_hash=data.get("first_transition_hash"),
            last_transition_id=data.get("last_transition_id"),
            last_transition_hash=data.get("last_transition_hash"),
            transitions=transitions,
            metadata=data.get("metadata", {}),
            created_at_utc=data["created_at_utc"],
        )
    except KeyError as exc:
        raise MarketStructureStructuralAssessmentHistoryValidationError(
            "market structure structural assessment history is incomplete."
        ) from exc


__all__ = [
    "MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_ID",
    "MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_NON_OPERATIONAL_DECLARATION",
    "MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_SCHEMA_VERSION",
    "MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_VERSION",
    "MarketStructureStructuralAssessmentHistory",
    "MarketStructureStructuralAssessmentHistoryError",
    "MarketStructureStructuralAssessmentHistoryIntegrityError",
    "MarketStructureStructuralAssessmentHistoryValidationError",
    "append_market_structure_structural_assessment_transition",
    "build_market_structure_structural_assessment_history",
    "market_structure_structural_assessment_history_from_dict",
    "market_structure_structural_assessment_history_to_dict",
    "verify_market_structure_structural_assessment_history",
]
