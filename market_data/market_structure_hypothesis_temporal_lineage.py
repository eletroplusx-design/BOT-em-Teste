from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value

from .errors import HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError
from . import market_structure_hypothesis_evaluation as phase53

MARKET_STRUCTURE_HYPOTHESIS_TEMPORAL_LINEAGE_SCHEMA_VERSION = 1
MARKET_STRUCTURE_HYPOTHESIS_TEMPORAL_LINEAGE_ID = "market_structure_hypothesis_temporal_lineage"
MARKET_STRUCTURE_HYPOTHESIS_TEMPORAL_LINEAGE_VERSION = "phase59_hypothesis_temporal_lineage_v1"
MARKET_STRUCTURE_HYPOTHESIS_TEMPORAL_LINEAGE_NON_OPERATIONAL_DECLARATION = (
    "This hypothesis temporal lineage is research-only and does not authorize replay, backtest, walk-forward, "
    "performance evaluation, ranking, scoring, paper trading, live trading, exchange connectivity, execution, "
    "or order submission."
)


class MarketStructureHypothesisTemporalLineageError(HistoricalDataError):
    pass


class MarketStructureHypothesisTemporalLineageValidationError(
    MarketStructureHypothesisTemporalLineageError,
    HistoricalDataValidationError,
):
    pass


class MarketStructureHypothesisTemporalLineageIntegrityError(
    MarketStructureHypothesisTemporalLineageError,
    HistoricalDataIntegrityError,
):
    pass


class MarketStructureHypothesisTemporalLineageConflictError(
    MarketStructureHypothesisTemporalLineageError,
    HistoricalDataValidationError,
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
        raise MarketStructureHypothesisTemporalLineageValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketStructureHypothesisTemporalLineageValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise MarketStructureHypothesisTemporalLineageValidationError(
            f"{field_name} must be a 64-character hex digest."
        )
    return digest


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise MarketStructureHypothesisTemporalLineageValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise MarketStructureHypothesisTemporalLineageValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise MarketStructureHypothesisTemporalLineageValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise MarketStructureHypothesisTemporalLineageValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketStructureHypothesisTemporalLineageValidationError(
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


def _normalize_hypothesis(value: Any) -> phase53.MarketStructureHypothesis:
    if isinstance(value, Mapping):
        return phase53.market_structure_hypothesis_from_dict(value)
    if not isinstance(value, phase53.MarketStructureHypothesis):
        raise MarketStructureHypothesisTemporalLineageValidationError(
            "hypotheses must contain market structure hypotheses."
        )
    return value


def _normalize_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set, frozenset)):
        raise MarketStructureHypothesisTemporalLineageValidationError(f"{field_name} must be a sequence of strings.")
    normalized = tuple(_require_str(item, field_name) for item in value)
    if len(set(normalized)) != len(normalized):
        raise MarketStructureHypothesisTemporalLineageValidationError(f"{field_name} must not contain duplicates.")
    return tuple(sorted(normalized))


def _event_kinds_from_references(references: Sequence[str]) -> tuple[str, ...]:
    kinds = []
    for reference in references:
        if "::" not in reference:
            continue
        kinds.append(reference.rsplit("::", 1)[-1])
    return tuple(sorted(dict.fromkeys(kinds)))


def _semantic_key_payload(entry: "MarketStructureHypothesisTemporalLineageEntry") -> dict[str, Any]:
    return {
        "schema_version": MARKET_STRUCTURE_HYPOTHESIS_TEMPORAL_LINEAGE_SCHEMA_VERSION,
        "dataset_hash": entry.dataset_hash,
        "contract_hash": entry.contract_hash,
        "hypothesis_type": entry.hypothesis_type,
        "timeframe_context": _thaw_read_only_value(entry.timeframe_context),
        "supporting_event_kinds": entry.supporting_event_kinds,
        "contradicting_event_kinds": entry.contradicting_event_kinds,
    }


def _entry_identity_payload(entry: "MarketStructureHypothesisTemporalLineageEntry") -> dict[str, Any]:
    return {
        "schema_version": entry.schema_version,
        "sequence_number": entry.sequence_number,
        "previous_hypothesis_id": entry.previous_hypothesis_id,
        "previous_hypothesis_hash": entry.previous_hypothesis_hash,
        "hypothesis_id": entry.hypothesis_id,
        "hypothesis_hash": entry.hypothesis_hash,
        "hypothesis_type": entry.hypothesis_type,
        "status": entry.status,
        "dataset_hash": entry.dataset_hash,
        "contract_hash": entry.contract_hash,
        "detection_result_hash": entry.detection_result_hash,
        "annotation_collection_hash": entry.annotation_collection_hash,
        "timeframe_context": _thaw_read_only_value(entry.timeframe_context),
        "observed_at": _utc_iso(entry.observed_at),
        "effective_at": _utc_iso(entry.effective_at),
        "supporting_event_ids": entry.supporting_event_ids,
        "supporting_annotation_ids": entry.supporting_annotation_ids,
        "contradicting_event_ids": entry.contradicting_event_ids,
        "contradicting_annotation_ids": entry.contradicting_annotation_ids,
        "invalidation_reasons": entry.invalidation_reasons,
        "ambiguity_reasons": entry.ambiguity_reasons,
        "supporting_event_kinds": entry.supporting_event_kinds,
        "contradicting_event_kinds": entry.contradicting_event_kinds,
    }


def _entry_hash_payload(entry: "MarketStructureHypothesisTemporalLineageEntry") -> dict[str, Any]:
    return _entry_identity_payload(entry)


def _lineage_entries_payload(entries: Sequence["MarketStructureHypothesisTemporalLineageEntry"]) -> list[dict[str, Any]]:
    return [_entry_hash_payload(entry) for entry in entries]


def _normalize_entry(value: Any) -> "MarketStructureHypothesisTemporalLineageEntry":
    if isinstance(value, Mapping):
        return market_structure_hypothesis_temporal_lineage_entry_from_dict(value)
    if not isinstance(value, MarketStructureHypothesisTemporalLineageEntry):
        raise MarketStructureHypothesisTemporalLineageValidationError(
            "entries must contain market structure hypothesis temporal lineage entries."
        )
    return value


def _normalize_entries(value: Any, field_name: str = "entries") -> tuple["MarketStructureHypothesisTemporalLineageEntry", ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise MarketStructureHypothesisTemporalLineageValidationError(f"{field_name} must be a sequence of entries.")
    return tuple(_normalize_entry(item) for item in value)


@dataclass(frozen=True, slots=True)
class MarketStructureHypothesisTemporalLineageEntry:
    schema_version: int
    sequence_number: int
    previous_hypothesis_id: str = ""
    previous_hypothesis_hash: str = ""
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
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    supporting_event_kinds: tuple[str, ...] = field(default_factory=tuple, repr=False)
    contradicting_event_kinds: tuple[str, ...] = field(default_factory=tuple, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        if self.schema_version != MARKET_STRUCTURE_HYPOTHESIS_TEMPORAL_LINEAGE_SCHEMA_VERSION:
            raise MarketStructureHypothesisTemporalLineageValidationError("schema_version must be 1.")
        object.__setattr__(self, "sequence_number", _require_int(self.sequence_number, "sequence_number"))
        if self.sequence_number <= 0:
            raise MarketStructureHypothesisTemporalLineageValidationError("sequence_number must be greater than zero.")
        object.__setattr__(
            self,
            "previous_hypothesis_id",
            _require_hex_digest(self.previous_hypothesis_id, "previous_hypothesis_id")
            if self.previous_hypothesis_id
            else "",
        )
        object.__setattr__(
            self,
            "previous_hypothesis_hash",
            _require_hex_digest(self.previous_hypothesis_hash, "previous_hypothesis_hash")
            if self.previous_hypothesis_hash
            else "",
        )
        object.__setattr__(self, "hypothesis_id", _require_hex_digest(self.hypothesis_id, "hypothesis_id"))
        object.__setattr__(self, "hypothesis_hash", _require_hex_digest(self.hypothesis_hash, "hypothesis_hash"))
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
            _require_hex_digest(self.annotation_collection_hash, "annotation_collection_hash"),
        )
        if not isinstance(self.timeframe_context, Mapping):
            raise MarketStructureHypothesisTemporalLineageValidationError("timeframe_context must be a mapping.")
        object.__setattr__(self, "timeframe_context", _freeze_read_only_value(dict(self.timeframe_context)))
        object.__setattr__(self, "observed_at", _require_utc_datetime(self.observed_at, "observed_at"))
        object.__setattr__(self, "effective_at", _require_utc_datetime(self.effective_at, "effective_at"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "supporting_event_ids", _normalize_sequence(self.supporting_event_ids, "supporting_event_ids"))
        object.__setattr__(
            self,
            "supporting_annotation_ids",
            _normalize_sequence(self.supporting_annotation_ids, "supporting_annotation_ids"),
        )
        object.__setattr__(
            self,
            "contradicting_event_ids",
            _normalize_sequence(self.contradicting_event_ids, "contradicting_event_ids"),
        )
        object.__setattr__(
            self,
            "contradicting_annotation_ids",
            _normalize_sequence(self.contradicting_annotation_ids, "contradicting_annotation_ids"),
        )
        object.__setattr__(self, "invalidation_reasons", _normalize_sequence(self.invalidation_reasons, "invalidation_reasons"))
        object.__setattr__(self, "ambiguity_reasons", _normalize_sequence(self.ambiguity_reasons, "ambiguity_reasons"))
        object.__setattr__(self, "supporting_event_kinds", _normalize_sequence(self.supporting_event_kinds, "supporting_event_kinds"))
        object.__setattr__(
            self,
            "contradicting_event_kinds",
            _normalize_sequence(self.contradicting_event_kinds, "contradicting_event_kinds"),
        )
        if self.effective_at < self.observed_at:
            raise MarketStructureHypothesisTemporalLineageValidationError("effective_at cannot precede observed_at.")

    def canonical_payload(self) -> dict[str, Any]:
        payload = _entry_identity_payload(self)
        payload["created_at_utc"] = _utc_iso(self.created_at_utc)
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureHypothesisTemporalLineageEntry":
        if not isinstance(data, Mapping):
            raise MarketStructureHypothesisTemporalLineageValidationError(
                "market structure hypothesis temporal lineage entry must be a mapping."
            )
        _require_exact_keys(
            data,
            "market structure hypothesis temporal lineage entry",
            {
                "schema_version",
                "sequence_number",
                "previous_hypothesis_id",
                "previous_hypothesis_hash",
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
                "created_at_utc",
                "supporting_event_kinds",
                "contradicting_event_kinds",
            },
        )
        try:
            return cls(
                schema_version=data["schema_version"],
                sequence_number=data["sequence_number"],
                previous_hypothesis_id=data.get("previous_hypothesis_id", ""),
                previous_hypothesis_hash=data.get("previous_hypothesis_hash", ""),
                hypothesis_id=data["hypothesis_id"],
                hypothesis_hash=data["hypothesis_hash"],
                hypothesis_type=data["hypothesis_type"],
                status=data["status"],
                dataset_hash=data["dataset_hash"],
                contract_hash=data["contract_hash"],
                detection_result_hash=data["detection_result_hash"],
                annotation_collection_hash=data["annotation_collection_hash"],
                timeframe_context=data["timeframe_context"],
                observed_at=data["observed_at"],
                effective_at=data["effective_at"],
                supporting_event_ids=data["supporting_event_ids"],
                supporting_annotation_ids=data["supporting_annotation_ids"],
                contradicting_event_ids=data["contradicting_event_ids"],
                contradicting_annotation_ids=data["contradicting_annotation_ids"],
                invalidation_reasons=data["invalidation_reasons"],
                ambiguity_reasons=data["ambiguity_reasons"],
                created_at_utc=data["created_at_utc"],
                supporting_event_kinds=data["supporting_event_kinds"],
                contradicting_event_kinds=data["contradicting_event_kinds"],
            )
        except KeyError as exc:
            raise MarketStructureHypothesisTemporalLineageValidationError(
                "market structure hypothesis temporal lineage entry is incomplete."
            ) from exc


@dataclass(frozen=True, slots=True)
class MarketStructureHypothesisTemporalLineage:
    schema_version: int
    lineage_id: str = ""
    lineage_hash: str = ""
    semantic_key: Mapping[str, Any] = field(default_factory=dict, repr=False)
    entries: tuple[MarketStructureHypothesisTemporalLineageEntry, ...] = field(default_factory=tuple, repr=False)
    entry_count: int = 0
    first_entry_id: str | None = None
    first_entry_hash: str | None = None
    last_entry_id: str | None = None
    last_entry_hash: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        if self.schema_version != MARKET_STRUCTURE_HYPOTHESIS_TEMPORAL_LINEAGE_SCHEMA_VERSION:
            raise MarketStructureHypothesisTemporalLineageValidationError("schema_version must be 1.")
        object.__setattr__(
            self,
            "lineage_id",
            _require_hex_digest(self.lineage_id, "lineage_id") if self.lineage_id else "",
        )
        object.__setattr__(
            self,
            "lineage_hash",
            _require_hex_digest(self.lineage_hash, "lineage_hash") if self.lineage_hash else "",
        )
        if not isinstance(self.semantic_key, Mapping):
            raise MarketStructureHypothesisTemporalLineageValidationError("semantic_key must be a mapping.")
        object.__setattr__(self, "semantic_key", _freeze_read_only_value(dict(self.semantic_key)))
        if not isinstance(self.metadata, Mapping):
            raise MarketStructureHypothesisTemporalLineageValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        provided_entry_count = _require_int(self.entry_count, "entry_count")

        normalized_entries = []
        for entry in self.entries:
            if isinstance(entry, MarketStructureHypothesisTemporalLineageEntry):
                normalized_entries.append(entry)
            elif isinstance(entry, Mapping):
                normalized_entries.append(MarketStructureHypothesisTemporalLineageEntry.from_dict(entry))
            else:
                raise MarketStructureHypothesisTemporalLineageValidationError(
                    "entries must contain market structure hypothesis temporal lineage entries."
                )
        ordered_entries = tuple(normalized_entries)
        object.__setattr__(self, "entries", ordered_entries)
        if provided_entry_count != len(ordered_entries):
            raise MarketStructureHypothesisTemporalLineageValidationError("entry_count is inconsistent.")
        object.__setattr__(self, "entry_count", len(ordered_entries))

        if ordered_entries:
            first = ordered_entries[0]
            if self.semantic_key:
                expected_key = _semantic_key_payload(first)
                if _thaw_read_only_value(self.semantic_key) != expected_key:
                    raise MarketStructureHypothesisTemporalLineageIntegrityError("semantic_key mismatch.")
            else:
                object.__setattr__(self, "semantic_key", _freeze_read_only_value(_semantic_key_payload(first)))

        expected_lineage_id = _hash_payload(_thaw_read_only_value(self.semantic_key))
        if self.lineage_id:
            if self.lineage_id != expected_lineage_id:
                raise MarketStructureHypothesisTemporalLineageIntegrityError("lineage_id mismatch.")
        else:
            object.__setattr__(self, "lineage_id", expected_lineage_id)

        self._validate_entries()
        expected_lineage_hash = _hash_payload(
            {
                "schema_version": self.schema_version,
                "lineage_id": self.lineage_id,
                "semantic_key": _thaw_read_only_value(self.semantic_key),
                "entry_count": self.entry_count,
                "first_entry_id": self.first_entry_id,
                "first_entry_hash": self.first_entry_hash,
                "last_entry_id": self.last_entry_id,
                "last_entry_hash": self.last_entry_hash,
                "entries": _lineage_entries_payload(self.entries),
                "metadata": _thaw_read_only_value(self.metadata),
            }
        )
        if self.lineage_hash:
            if self.lineage_hash != expected_lineage_hash:
                raise MarketStructureHypothesisTemporalLineageIntegrityError("lineage_hash mismatch.")
        else:
            object.__setattr__(self, "lineage_hash", expected_lineage_hash)

    def _validate_entries(self) -> None:
        seen_entry_ids: set[str] = set()
        seen_entry_hashes: set[str] = set()
        first_entry_id: str | None = None
        first_entry_hash: str | None = None
        last_entry_id: str | None = None
        last_entry_hash: str | None = None
        previous_entry: MarketStructureHypothesisTemporalLineageEntry | None = None
        expected_sequence = 1
        expected_key = _thaw_read_only_value(self.semantic_key)

        for entry in self.entries:
            if entry.sequence_number != expected_sequence:
                raise MarketStructureHypothesisTemporalLineageValidationError("sequence gap or reorder is not allowed.")
            expected_sequence += 1
            if entry.hypothesis_id in seen_entry_ids:
                raise MarketStructureHypothesisTemporalLineageConflictError("duplicate hypothesis_id already registered.")
            if entry.hypothesis_hash in seen_entry_hashes:
                raise MarketStructureHypothesisTemporalLineageConflictError("duplicate hypothesis_hash already registered.")
            seen_entry_ids.add(entry.hypothesis_id)
            seen_entry_hashes.add(entry.hypothesis_hash)
            entry_key = _semantic_key_payload(entry)
            if entry_key != expected_key:
                raise MarketStructureHypothesisTemporalLineageConflictError("ambiguous lineage continuation.")
            if previous_entry is None:
                if entry.previous_hypothesis_id or entry.previous_hypothesis_hash:
                    raise MarketStructureHypothesisTemporalLineageValidationError(
                        "first entry must not reference a previous hypothesis."
                    )
                first_entry_id = entry.hypothesis_id
                first_entry_hash = entry.hypothesis_hash
            else:
                if entry.previous_hypothesis_id != previous_entry.hypothesis_id:
                    raise MarketStructureHypothesisTemporalLineageConflictError("chain break or fork is not allowed.")
                if entry.previous_hypothesis_hash != previous_entry.hypothesis_hash:
                    raise MarketStructureHypothesisTemporalLineageConflictError("chain break or merge is not allowed.")
                if entry.effective_at <= previous_entry.effective_at:
                    raise MarketStructureHypothesisTemporalLineageValidationError(
                        "same timestamp or temporal regression is not allowed."
                    )
                if previous_entry.status == "invalidated" and entry.status != "invalidated":
                    raise MarketStructureHypothesisTemporalLineageValidationError(
                        "invalidated hypothesis instances cannot silently resurrect."
                    )
            previous_entry = entry
            last_entry_id = entry.hypothesis_id
            last_entry_hash = entry.hypothesis_hash

        object.__setattr__(self, "first_entry_id", first_entry_id)
        object.__setattr__(self, "first_entry_hash", first_entry_hash)
        object.__setattr__(self, "last_entry_id", last_entry_id)
        object.__setattr__(self, "last_entry_hash", last_entry_hash)

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "lineage_id": self.lineage_id,
            "lineage_hash": self.lineage_hash,
            "semantic_key": _thaw_read_only_value(self.semantic_key),
            "entry_count": self.entry_count,
            "first_entry_id": self.first_entry_id,
            "first_entry_hash": self.first_entry_hash,
            "last_entry_id": self.last_entry_id,
            "last_entry_hash": self.last_entry_hash,
            "entries": [entry.canonical_payload() for entry in self.entries],
            "metadata": _thaw_read_only_value(self.metadata),
            "created_at_utc": _utc_iso(self.created_at_utc),
        }

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureHypothesisTemporalLineage":
        if not isinstance(data, Mapping):
            raise MarketStructureHypothesisTemporalLineageValidationError(
                "market structure hypothesis temporal lineage must be a mapping."
            )
        _require_exact_keys(
            data,
            "market structure hypothesis temporal lineage",
            {
                "schema_version",
                "lineage_id",
                "lineage_hash",
                "semantic_key",
                "entries",
                "entry_count",
                "first_entry_id",
                "first_entry_hash",
                "last_entry_id",
                "last_entry_hash",
                "metadata",
                "created_at_utc",
            },
        )
        try:
            return cls(
                schema_version=data["schema_version"],
                lineage_id=data.get("lineage_id", ""),
                lineage_hash=data.get("lineage_hash", ""),
                semantic_key=data["semantic_key"],
                entries=data["entries"],
                entry_count=data["entry_count"],
                first_entry_id=data.get("first_entry_id"),
                first_entry_hash=data.get("first_entry_hash"),
                last_entry_id=data.get("last_entry_id"),
                last_entry_hash=data.get("last_entry_hash"),
                metadata=data.get("metadata", {}),
                created_at_utc=data["created_at_utc"],
            )
        except KeyError as exc:
            raise MarketStructureHypothesisTemporalLineageValidationError(
                "market structure hypothesis temporal lineage is incomplete."
            ) from exc


def _require_exact_keys(mapping: Mapping[str, Any], field_name: str, expected_keys: set[str]) -> None:
    extra = sorted(set(mapping) - expected_keys)
    missing = sorted(expected_keys - set(mapping))
    if extra or missing:
        parts: list[str] = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected {', '.join(extra)}")
        raise MarketStructureHypothesisTemporalLineageValidationError(
            f"{field_name} has invalid fields: {'; '.join(parts)}."
        )


def build_market_structure_hypothesis_temporal_lineage_entry(
    hypothesis: phase53.MarketStructureHypothesis | Mapping[str, Any],
    *,
    sequence_number: int,
    previous_hypothesis_id: str = "",
    previous_hypothesis_hash: str = "",
    created_at_utc: datetime | None = None,
) -> MarketStructureHypothesisTemporalLineageEntry:
    normalized_hypothesis = _normalize_hypothesis(hypothesis)
    verified_hypothesis = phase53.verify_market_structure_hypothesis(normalized_hypothesis)
    created_at_utc = created_at_utc or verified_hypothesis.created_at_utc
    return MarketStructureHypothesisTemporalLineageEntry(
        schema_version=MARKET_STRUCTURE_HYPOTHESIS_TEMPORAL_LINEAGE_SCHEMA_VERSION,
        sequence_number=sequence_number,
        previous_hypothesis_id=previous_hypothesis_id,
        previous_hypothesis_hash=previous_hypothesis_hash,
        hypothesis_id=verified_hypothesis.hypothesis_id,
        hypothesis_hash=verified_hypothesis.hypothesis_hash,
        hypothesis_type=verified_hypothesis.hypothesis_type,
        status=verified_hypothesis.status,
        dataset_hash=verified_hypothesis.dataset_hash,
        contract_hash=verified_hypothesis.contract_hash,
        detection_result_hash=verified_hypothesis.detection_result_hash,
        annotation_collection_hash=verified_hypothesis.annotation_collection_hash,
        timeframe_context=verified_hypothesis.timeframe_context,
        observed_at=verified_hypothesis.observed_at,
        effective_at=verified_hypothesis.effective_at,
        supporting_event_ids=verified_hypothesis.supporting_event_ids,
        supporting_annotation_ids=verified_hypothesis.supporting_annotation_ids,
        contradicting_event_ids=verified_hypothesis.contradicting_event_ids,
        contradicting_annotation_ids=verified_hypothesis.contradicting_annotation_ids,
        invalidation_reasons=verified_hypothesis.invalidation_reasons,
        ambiguity_reasons=verified_hypothesis.ambiguity_reasons,
        created_at_utc=created_at_utc,
        supporting_event_kinds=_event_kinds_from_references(verified_hypothesis.supporting_event_ids),
        contradicting_event_kinds=_event_kinds_from_references(verified_hypothesis.contradicting_event_ids),
    )


def build_market_structure_hypothesis_temporal_lineage(
    entries: Sequence[MarketStructureHypothesisTemporalLineageEntry | phase53.MarketStructureHypothesis | Mapping[str, Any]] = (),
    *,
    semantic_key: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    created_at_utc: datetime | None = None,
) -> MarketStructureHypothesisTemporalLineage:
    normalized_entries: list[MarketStructureHypothesisTemporalLineageEntry] = []
    previous_entry: MarketStructureHypothesisTemporalLineageEntry | None = None
    for index, item in enumerate(entries, 1):
        if isinstance(item, MarketStructureHypothesisTemporalLineageEntry):
            entry = item
        else:
            entry = build_market_structure_hypothesis_temporal_lineage_entry(
                item,
                sequence_number=index,
                previous_hypothesis_id=previous_entry.hypothesis_id if previous_entry else "",
                previous_hypothesis_hash=previous_entry.hypothesis_hash if previous_entry else "",
                created_at_utc=created_at_utc,
            )
        if entry.sequence_number != index:
            raise MarketStructureHypothesisTemporalLineageValidationError("sequence gap or reorder is not allowed.")
        if previous_entry is not None:
            if entry.previous_hypothesis_id != previous_entry.hypothesis_id:
                raise MarketStructureHypothesisTemporalLineageConflictError("chain break or fork is not allowed.")
            if entry.previous_hypothesis_hash != previous_entry.hypothesis_hash:
                raise MarketStructureHypothesisTemporalLineageConflictError("chain break or merge is not allowed.")
        normalized_entries.append(entry)
        previous_entry = entry
    created_at_utc = created_at_utc or (
        normalized_entries[-1].created_at_utc if normalized_entries else datetime.now(timezone.utc)
    )
    if semantic_key is None and normalized_entries:
        semantic_key = _semantic_key_payload(normalized_entries[0])
    if semantic_key is None:
        semantic_key = {}
    lineage = MarketStructureHypothesisTemporalLineage(
        schema_version=MARKET_STRUCTURE_HYPOTHESIS_TEMPORAL_LINEAGE_SCHEMA_VERSION,
        semantic_key=semantic_key,
        entries=tuple(normalized_entries),
        entry_count=len(normalized_entries),
        metadata=metadata or {},
        created_at_utc=created_at_utc,
    )
    return verify_market_structure_hypothesis_temporal_lineage(lineage)


def append_market_structure_hypothesis_temporal_lineage(
    lineage: MarketStructureHypothesisTemporalLineage | Mapping[str, Any],
    hypothesis: phase53.MarketStructureHypothesis | Mapping[str, Any] | Sequence[phase53.MarketStructureHypothesis | Mapping[str, Any]],
    *,
    created_at_utc: datetime | None = None,
) -> MarketStructureHypothesisTemporalLineage:
    if isinstance(lineage, Mapping):
        lineage = market_structure_hypothesis_temporal_lineage_from_dict(lineage)
    if not isinstance(lineage, MarketStructureHypothesisTemporalLineage):
        raise MarketStructureHypothesisTemporalLineageValidationError(
            "market structure hypothesis temporal lineage is required."
        )
    if isinstance(hypothesis, Sequence) and not isinstance(hypothesis, (str, bytes, Mapping)):
        candidates = tuple(_normalize_hypothesis(item) for item in hypothesis)
        matching_candidates = tuple(
            candidate
            for candidate in candidates
            if _semantic_key_payload(
                build_market_structure_hypothesis_temporal_lineage_entry(
                    candidate,
                    sequence_number=max(1, lineage.entry_count + 1),
                    previous_hypothesis_id=lineage.last_entry_id or "",
                    previous_hypothesis_hash=lineage.last_entry_hash or "",
                    created_at_utc=created_at_utc,
                )
            )
            == _thaw_read_only_value(lineage.semantic_key)
        )
        if not matching_candidates:
            raise MarketStructureHypothesisTemporalLineageValidationError("no matching lineage continuation.")
        if len(matching_candidates) > 1:
            raise MarketStructureHypothesisTemporalLineageConflictError("ambiguous lineage continuation.")
        hypothesis = matching_candidates[0]
    normalized_hypothesis = _normalize_hypothesis(hypothesis)
    verified_hypothesis = phase53.verify_market_structure_hypothesis(normalized_hypothesis)
    expected_key = _thaw_read_only_value(lineage.semantic_key)
    candidate_entry = build_market_structure_hypothesis_temporal_lineage_entry(
        verified_hypothesis,
        sequence_number=lineage.entry_count + 1,
        previous_hypothesis_id=lineage.last_entry_id or "",
        previous_hypothesis_hash=lineage.last_entry_hash or "",
        created_at_utc=created_at_utc,
    )
    if _semantic_key_payload(candidate_entry) != expected_key:
        raise MarketStructureHypothesisTemporalLineageConflictError("ambiguous lineage continuation.")
    return build_market_structure_hypothesis_temporal_lineage(
        tuple(lineage.entries) + (candidate_entry,),
        semantic_key=lineage.semantic_key,
        metadata=_thaw_read_only_value(lineage.metadata),
        created_at_utc=created_at_utc or candidate_entry.created_at_utc,
    )


def verify_market_structure_hypothesis_temporal_lineage(
    lineage: MarketStructureHypothesisTemporalLineage,
) -> MarketStructureHypothesisTemporalLineage:
    if not isinstance(lineage, MarketStructureHypothesisTemporalLineage):
        raise MarketStructureHypothesisTemporalLineageValidationError(
            "market structure hypothesis temporal lineage is required."
        )
    normalized_entries = _normalize_entries(lineage.entries)
    if tuple(normalized_entries) != lineage.entries:
        raise MarketStructureHypothesisTemporalLineageIntegrityError("entries mismatch.")
    semantic_key = _thaw_read_only_value(lineage.semantic_key)
    if not semantic_key and normalized_entries:
        raise MarketStructureHypothesisTemporalLineageValidationError("semantic_key is required.")
    expected_lineage_id = _hash_payload(semantic_key)
    if lineage.lineage_id != expected_lineage_id:
        raise MarketStructureHypothesisTemporalLineageIntegrityError("lineage_id mismatch.")
    expected_hash = _hash_payload(
        {
            "schema_version": lineage.schema_version,
            "lineage_id": lineage.lineage_id,
            "semantic_key": semantic_key,
            "entry_count": lineage.entry_count,
            "first_entry_id": lineage.first_entry_id,
            "first_entry_hash": lineage.first_entry_hash,
            "last_entry_id": lineage.last_entry_id,
            "last_entry_hash": lineage.last_entry_hash,
                "entries": _lineage_entries_payload(normalized_entries),
                "metadata": _thaw_read_only_value(lineage.metadata),
            }
        )
    if lineage.lineage_hash != expected_hash:
        raise MarketStructureHypothesisTemporalLineageIntegrityError("lineage_hash mismatch.")
    return lineage


def market_structure_hypothesis_temporal_lineage_to_dict(
    lineage: MarketStructureHypothesisTemporalLineage,
) -> dict[str, Any]:
    if not isinstance(lineage, MarketStructureHypothesisTemporalLineage):
        raise MarketStructureHypothesisTemporalLineageValidationError(
            "market structure hypothesis temporal lineage is required."
        )
    return lineage.as_dict()


def market_structure_hypothesis_temporal_lineage_from_dict(
    data: Mapping[str, Any],
) -> MarketStructureHypothesisTemporalLineage:
    return MarketStructureHypothesisTemporalLineage.from_dict(data)


__all__ = [
    "MARKET_STRUCTURE_HYPOTHESIS_TEMPORAL_LINEAGE_ID",
    "MARKET_STRUCTURE_HYPOTHESIS_TEMPORAL_LINEAGE_NON_OPERATIONAL_DECLARATION",
    "MARKET_STRUCTURE_HYPOTHESIS_TEMPORAL_LINEAGE_SCHEMA_VERSION",
    "MARKET_STRUCTURE_HYPOTHESIS_TEMPORAL_LINEAGE_VERSION",
    "MarketStructureHypothesisTemporalLineage",
    "MarketStructureHypothesisTemporalLineageConflictError",
    "MarketStructureHypothesisTemporalLineageEntry",
    "MarketStructureHypothesisTemporalLineageError",
    "MarketStructureHypothesisTemporalLineageIntegrityError",
    "MarketStructureHypothesisTemporalLineageValidationError",
    "append_market_structure_hypothesis_temporal_lineage",
    "build_market_structure_hypothesis_temporal_lineage",
    "build_market_structure_hypothesis_temporal_lineage_entry",
    "market_structure_hypothesis_temporal_lineage_from_dict",
    "market_structure_hypothesis_temporal_lineage_to_dict",
    "verify_market_structure_hypothesis_temporal_lineage",
]
