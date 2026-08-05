from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value

from . import offline_execution_audit_record as phase48
from .errors import HistoricalDataConflictError, HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError

OFFLINE_EXECUTION_AUDIT_REGISTRY_SCHEMA_VERSION = 1
OFFLINE_EXECUTION_AUDIT_REGISTRY_ID = "offline_execution_audit_registry"
OFFLINE_EXECUTION_AUDIT_REGISTRY_VERSION = "phase49_offline_execution_audit_registry_v1"


class OfflineExecutionAuditRegistryError(HistoricalDataError):
    pass


class OfflineExecutionAuditRegistryValidationError(
    OfflineExecutionAuditRegistryError,
    HistoricalDataValidationError,
):
    pass


class OfflineExecutionAuditRegistryIntegrityError(
    OfflineExecutionAuditRegistryError,
    HistoricalDataIntegrityError,
):
    pass


class OfflineExecutionAuditRegistryConflictError(
    OfflineExecutionAuditRegistryError,
    HistoricalDataConflictError,
):
    pass


class OfflineExecutionAuditRegistryPersistenceError(OfflineExecutionAuditRegistryError):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        serialize_value(_thaw_read_only_value(payload)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash_payload(payload: Any) -> str:
    try:
        return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    except (TypeError, ValueError) as exc:
        raise OfflineExecutionAuditRegistryValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineExecutionAuditRegistryValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineExecutionAuditRegistryValidationError(f"{field_name} must be a 64-character hex digest.")
    return digest


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineExecutionAuditRegistryValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineExecutionAuditRegistryValidationError(f"{field_name} must be a boolean.")
    return value


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineExecutionAuditRegistryValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise OfflineExecutionAuditRegistryValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise OfflineExecutionAuditRegistryValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineExecutionAuditRegistryValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _freeze_read_only_value(value: Any) -> Any:
    return phase48._freeze_read_only_value(value)  # type: ignore[attr-defined]


def _thaw_read_only_value(value: Any) -> Any:
    return phase48._thaw_read_only_value(value)  # type: ignore[attr-defined]


def _rooted_registry_path(
    registry_file: str | Path,
    *,
    root_directory: str | Path | None,
    field_name: str,
) -> tuple[Path, Path]:
    try:
        return phase48._rooted_record_path(  # type: ignore[attr-defined]
            registry_file,
            root_directory=root_directory,
            field_name=field_name,
        )
    except phase48.OfflineExecutionAuditRecordValidationError as exc:  # type: ignore[attr-defined]
        raise OfflineExecutionAuditRegistryValidationError(str(exc)) from exc


def _write_json_atomic(path: Path, payload: Any) -> None:
    canonical = _canonical_json(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == canonical:
        return
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{id(payload)}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        try:
            dir_handle = os.open(path.parent, os.O_RDONLY)
        except Exception:
            return
        try:
            os.fsync(dir_handle)
        finally:
            os.close(dir_handle)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise OfflineExecutionAuditRegistryPersistenceError(
            "failed to write offline execution audit registry atomically."
        ) from exc


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise OfflineExecutionAuditRegistryValidationError("offline execution audit registry is missing.")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise OfflineExecutionAuditRegistryValidationError("offline execution audit registry is empty.")
    try:
        return json.loads(text)
    except Exception as exc:
        raise OfflineExecutionAuditRegistryValidationError(
            "offline execution audit registry is invalid JSON."
        ) from exc


def _metadata_snapshot(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    snapshot = _freeze_read_only_value(dict(metadata))
    if not isinstance(snapshot, Mapping):
        raise OfflineExecutionAuditRegistryValidationError("metadata must be a mapping.")
    return snapshot


def _audit_record_snapshot(audit_record: phase48.OfflineExecutionAuditRecord) -> Mapping[str, Any]:
    return audit_record.as_dict()


def _build_verified_audit_record(
    audit_record: phase48.OfflineExecutionAuditRecord | Mapping[str, Any],
) -> phase48.OfflineExecutionAuditRecord:
    if isinstance(audit_record, phase48.OfflineExecutionAuditRecord):
        return phase48.verify_offline_execution_audit_record(audit_record)
    if isinstance(audit_record, Mapping):
        return phase48.verify_offline_execution_audit_record(
            phase48.OfflineExecutionAuditRecord.from_dict(dict(audit_record))
        )
    raise OfflineExecutionAuditRegistryValidationError(
        "a verified offline execution audit record is required."
    )


def _registry_entry_identity_payload(entry: "OfflineExecutionAuditRegistryEntry") -> dict[str, Any]:
    return {
        "schema_version": entry.schema_version,
        "registry_id": entry.registry_id,
        "entry_number": entry.entry_number,
        "audit_record_id": entry.audit_record_id,
        "audit_record_hash": entry.audit_record_hash,
        "lineage_hash": entry.lineage_hash,
        "experiment_id": entry.experiment_id,
        "execution_attempt_id": entry.execution_attempt_id,
        "previous_entry_id": entry.previous_entry_id,
        "previous_entry_hash": entry.previous_entry_hash,
        "metadata": _thaw_read_only_value(entry.metadata),
    }


def _registry_entry_hash_payload(entry: "OfflineExecutionAuditRegistryEntry") -> dict[str, Any]:
    payload = _registry_entry_identity_payload(entry)
    payload["registry_entry_id"] = entry.registry_entry_id
    return payload


def _registry_hash_payload(registry: "OfflineExecutionAuditRegistry") -> dict[str, Any]:
    return {
        "schema_version": registry.schema_version,
        "registry_id": registry.registry_id,
        "entry_count": registry.entry_count,
        "first_entry_id": registry.first_entry_id,
        "last_entry_id": registry.last_entry_id,
        "metadata": _thaw_read_only_value(registry.metadata),
        "registry_entry_hashes": tuple(entry.registry_entry_hash for entry in registry.entries),
    }


def _entry_material_key(
    *,
    audit_record: phase48.OfflineExecutionAuditRecord,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "audit_record_id": audit_record.audit_record_id,
        "audit_record_hash": audit_record.audit_record_hash,
        "lineage_hash": audit_record.lineage_hash,
        "experiment_id": audit_record.experiment_id,
        "execution_attempt_id": audit_record.execution_attempt_id,
        "metadata": metadata,
    }


def _entry_matches_material(
    entry: "OfflineExecutionAuditRegistryEntry",
    *,
    audit_record: phase48.OfflineExecutionAuditRecord,
    metadata: Mapping[str, Any],
) -> bool:
    return (
        entry.audit_record_id == audit_record.audit_record_id
        and entry.audit_record_hash == audit_record.audit_record_hash
        and entry.lineage_hash == audit_record.lineage_hash
        and entry.experiment_id == audit_record.experiment_id
        and entry.execution_attempt_id == audit_record.execution_attempt_id
        and _canonical_json(entry.metadata) == _canonical_json(metadata)
    )


def _verify_entry_chain(entries: tuple["OfflineExecutionAuditRegistryEntry", ...]) -> None:
    if not entries:
        return
    previous = None
    seen_registry_entry_ids: set[str] = set()
    seen_registry_entry_hashes: set[str] = set()
    seen_audit_record_ids: set[str] = set()
    seen_audit_record_hashes: set[str] = set()
    seen_execution_attempt_ids: set[str] = set()
    seen_lineage_hashes: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if entry.entry_number != index:
            raise OfflineExecutionAuditRegistryValidationError("entry_number sequence is not contiguous.")
        if previous is None:
            if entry.previous_entry_id is not None or entry.previous_entry_hash is not None:
                raise OfflineExecutionAuditRegistryValidationError(
                    "the first entry must not reference a previous entry."
                )
        else:
            if entry.previous_entry_id != previous.registry_entry_id:
                raise OfflineExecutionAuditRegistryIntegrityError("previous_entry_id mismatch.")
            if entry.previous_entry_hash != previous.registry_entry_hash:
                raise OfflineExecutionAuditRegistryIntegrityError("previous_entry_hash mismatch.")
        if entry.registry_entry_id in seen_registry_entry_ids:
            raise OfflineExecutionAuditRegistryConflictError("registry_entry_id already registered.")
        if entry.registry_entry_hash in seen_registry_entry_hashes:
            raise OfflineExecutionAuditRegistryConflictError("registry_entry_hash already registered.")
        if entry.audit_record_id in seen_audit_record_ids:
            raise OfflineExecutionAuditRegistryConflictError("audit_record_id already registered.")
        if entry.audit_record_hash in seen_audit_record_hashes:
            raise OfflineExecutionAuditRegistryConflictError("audit_record_hash already registered.")
        if entry.execution_attempt_id in seen_execution_attempt_ids:
            raise OfflineExecutionAuditRegistryConflictError("execution_attempt_id already registered.")
        if entry.lineage_hash in seen_lineage_hashes:
            raise OfflineExecutionAuditRegistryConflictError("lineage_hash already registered.")
        seen_registry_entry_ids.add(entry.registry_entry_id)
        seen_registry_entry_hashes.add(entry.registry_entry_hash)
        seen_audit_record_ids.add(entry.audit_record_id)
        seen_audit_record_hashes.add(entry.audit_record_hash)
        seen_execution_attempt_ids.add(entry.execution_attempt_id)
        seen_lineage_hashes.add(entry.lineage_hash)
        previous = entry


@dataclass(frozen=True, slots=True)
class OfflineExecutionAuditRegistryEntry:
    schema_version: int = OFFLINE_EXECUTION_AUDIT_REGISTRY_SCHEMA_VERSION
    registry_entry_id: str = ""
    registry_entry_hash: str = ""
    registry_id: str = OFFLINE_EXECUTION_AUDIT_REGISTRY_ID
    audit_record_id: str = ""
    audit_record_hash: str = ""
    lineage_hash: str = ""
    experiment_id: str = ""
    execution_attempt_id: str = ""
    previous_entry_id: str | None = None
    previous_entry_hash: str | None = None
    entry_number: int = 0
    registered_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(
            self,
            "registry_entry_id",
            _require_hex_digest(self.registry_entry_id, "registry_entry_id") if self.registry_entry_id else "",
        )
        object.__setattr__(
            self,
            "registry_entry_hash",
            _require_hex_digest(self.registry_entry_hash, "registry_entry_hash") if self.registry_entry_hash else "",
        )
        object.__setattr__(self, "registry_id", _require_str(self.registry_id, "registry_id"))
        object.__setattr__(self, "audit_record_id", _require_hex_digest(self.audit_record_id, "audit_record_id"))
        object.__setattr__(self, "audit_record_hash", _require_hex_digest(self.audit_record_hash, "audit_record_hash"))
        object.__setattr__(self, "lineage_hash", _require_hex_digest(self.lineage_hash, "lineage_hash"))
        object.__setattr__(self, "experiment_id", _require_str(self.experiment_id, "experiment_id"))
        object.__setattr__(self, "execution_attempt_id", _require_str(self.execution_attempt_id, "execution_attempt_id"))
        object.__setattr__(self, "entry_number", _require_int(self.entry_number, "entry_number"))
        object.__setattr__(self, "registered_at_utc", _require_utc_datetime(self.registered_at_utc, "registered_at_utc"))
        if not isinstance(self.metadata, Mapping):
            raise OfflineExecutionAuditRegistryValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _metadata_snapshot(self.metadata))

        if self.schema_version != OFFLINE_EXECUTION_AUDIT_REGISTRY_SCHEMA_VERSION:
            raise OfflineExecutionAuditRegistryValidationError("schema_version must be 1.")
        if self.registry_id != OFFLINE_EXECUTION_AUDIT_REGISTRY_ID:
            raise OfflineExecutionAuditRegistryValidationError(
                "registry_id must remain offline_execution_audit_registry."
            )
        if self.entry_number <= 0:
            raise OfflineExecutionAuditRegistryValidationError("entry_number must be greater than zero.")
        if self.entry_number == 1:
            if self.previous_entry_id is not None:
                raise OfflineExecutionAuditRegistryIntegrityError("previous_entry_id mismatch.")
            if self.previous_entry_hash is not None:
                raise OfflineExecutionAuditRegistryIntegrityError("previous_entry_hash mismatch.")
        else:
            if self.previous_entry_id is None:
                raise OfflineExecutionAuditRegistryValidationError("previous_entry_id is required.")
            if self.previous_entry_hash is None:
                raise OfflineExecutionAuditRegistryValidationError("previous_entry_hash is required.")
            object.__setattr__(self, "previous_entry_id", _require_hex_digest(self.previous_entry_id, "previous_entry_id"))
            object.__setattr__(self, "previous_entry_hash", _require_hex_digest(self.previous_entry_hash, "previous_entry_hash"))

        expected_registry_entry_id = _hash_payload(self._registry_entry_id_payload())
        if self.registry_entry_id:
            if self.registry_entry_id != expected_registry_entry_id:
                raise OfflineExecutionAuditRegistryIntegrityError("registry_entry_id mismatch.")
        else:
            object.__setattr__(self, "registry_entry_id", expected_registry_entry_id)

        expected_registry_entry_hash = _hash_payload(self._registry_entry_hash_payload())
        if self.registry_entry_hash:
            if self.registry_entry_hash != expected_registry_entry_hash:
                raise OfflineExecutionAuditRegistryIntegrityError("registry_entry_hash mismatch.")
        else:
            object.__setattr__(self, "registry_entry_hash", expected_registry_entry_hash)

    def _registry_entry_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "registry_id": self.registry_id,
            "entry_number": self.entry_number,
            "audit_record_id": self.audit_record_id,
            "audit_record_hash": self.audit_record_hash,
            "lineage_hash": self.lineage_hash,
            "experiment_id": self.experiment_id,
            "execution_attempt_id": self.execution_attempt_id,
            "previous_entry_id": self.previous_entry_id,
            "previous_entry_hash": self.previous_entry_hash,
            "metadata": _thaw_read_only_value(self.metadata),
        }

    def _registry_entry_hash_payload(self) -> dict[str, Any]:
        payload = self._registry_entry_id_payload()
        payload["registry_entry_id"] = self.registry_entry_id
        return payload

    def canonical_payload(self, *, include_registry_entry_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "registry_entry_id": self.registry_entry_id,
            "registry_id": self.registry_id,
            "audit_record_id": self.audit_record_id,
            "audit_record_hash": self.audit_record_hash,
            "lineage_hash": self.lineage_hash,
            "experiment_id": self.experiment_id,
            "execution_attempt_id": self.execution_attempt_id,
            "previous_entry_id": self.previous_entry_id,
            "previous_entry_hash": self.previous_entry_hash,
            "entry_number": self.entry_number,
            "registered_at_utc": _utc_iso(self.registered_at_utc),
            "metadata": _thaw_read_only_value(self.metadata),
        }
        if include_registry_entry_hash:
            payload["registry_entry_hash"] = self.registry_entry_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_registry_entry_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfflineExecutionAuditRegistryEntry":
        if not isinstance(data, Mapping):
            raise OfflineExecutionAuditRegistryValidationError(
                "offline execution audit registry entry must be a mapping."
            )
        mapping = dict(data)
        allowed = {
            "schema_version",
            "registry_entry_id",
            "registry_entry_hash",
            "registry_id",
            "audit_record_id",
            "audit_record_hash",
            "lineage_hash",
            "experiment_id",
            "execution_attempt_id",
            "previous_entry_id",
            "previous_entry_hash",
            "entry_number",
            "registered_at_utc",
            "metadata",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise OfflineExecutionAuditRegistryValidationError(
                f"unexpected offline execution audit registry entry fields: {', '.join(extra)}."
            )
        required = allowed - {"previous_entry_id", "previous_entry_hash"}
        missing = sorted(field for field in required if field not in mapping)
        if missing:
            raise OfflineExecutionAuditRegistryValidationError(
                f"offline execution audit registry entry is incomplete: {', '.join(missing)}."
            )
        try:
            return cls(
                schema_version=mapping.get("schema_version", OFFLINE_EXECUTION_AUDIT_REGISTRY_SCHEMA_VERSION),
                registry_entry_id=mapping.get("registry_entry_id", ""),
                registry_entry_hash=mapping.get("registry_entry_hash", ""),
                registry_id=mapping.get("registry_id", OFFLINE_EXECUTION_AUDIT_REGISTRY_ID),
                audit_record_id=mapping["audit_record_id"],
                audit_record_hash=mapping["audit_record_hash"],
                lineage_hash=mapping["lineage_hash"],
                experiment_id=mapping["experiment_id"],
                execution_attempt_id=mapping["execution_attempt_id"],
                previous_entry_id=mapping.get("previous_entry_id"),
                previous_entry_hash=mapping.get("previous_entry_hash"),
                entry_number=mapping["entry_number"],
                registered_at_utc=mapping["registered_at_utc"],
                metadata=mapping.get("metadata", {}),
            )
        except KeyError as exc:
            raise OfflineExecutionAuditRegistryValidationError(
                "offline execution audit registry entry is incomplete."
            ) from exc


@dataclass(frozen=True, slots=True)
class OfflineExecutionAuditRegistry:
    schema_version: int = OFFLINE_EXECUTION_AUDIT_REGISTRY_SCHEMA_VERSION
    registry_id: str = OFFLINE_EXECUTION_AUDIT_REGISTRY_ID
    registry_hash: str = ""
    entries: tuple[OfflineExecutionAuditRegistryEntry, ...] = ()
    entry_count: int = 0
    first_entry_id: str | None = None
    last_entry_id: str | None = None
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "registry_id", _require_str(self.registry_id, "registry_id"))
        object.__setattr__(
            self,
            "registry_hash",
            _require_hex_digest(self.registry_hash, "registry_hash") if self.registry_hash else "",
        )
        if not isinstance(self.entries, Sequence):
            raise OfflineExecutionAuditRegistryValidationError("entries must be a sequence.")
        frozen_entries: tuple[OfflineExecutionAuditRegistryEntry, ...] = tuple(self.entries)
        for entry in frozen_entries:
            if not isinstance(entry, OfflineExecutionAuditRegistryEntry):
                raise OfflineExecutionAuditRegistryValidationError(
                    "entries must contain verified offline execution audit registry entries."
                )
        object.__setattr__(self, "entries", frozen_entries)
        object.__setattr__(self, "entry_count", _require_int(self.entry_count, "entry_count"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "updated_at_utc", _require_utc_datetime(self.updated_at_utc, "updated_at_utc"))
        if not isinstance(self.metadata, Mapping):
            raise OfflineExecutionAuditRegistryValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _metadata_snapshot(self.metadata))

        if self.schema_version != OFFLINE_EXECUTION_AUDIT_REGISTRY_SCHEMA_VERSION:
            raise OfflineExecutionAuditRegistryValidationError("schema_version must be 1.")
        if self.registry_id != OFFLINE_EXECUTION_AUDIT_REGISTRY_ID:
            raise OfflineExecutionAuditRegistryValidationError(
                "registry_id must remain offline_execution_audit_registry."
            )
        if self.entry_count != len(frozen_entries):
            raise OfflineExecutionAuditRegistryValidationError("entry_count does not match entries.")
        if frozen_entries:
            first_entry = frozen_entries[0]
            last_entry = frozen_entries[-1]
            if self.first_entry_id and self.first_entry_id != first_entry.registry_entry_id:
                raise OfflineExecutionAuditRegistryIntegrityError("first_entry_id mismatch.")
            if self.last_entry_id and self.last_entry_id != last_entry.registry_entry_id:
                raise OfflineExecutionAuditRegistryIntegrityError("last_entry_id mismatch.")
            object.__setattr__(self, "first_entry_id", first_entry.registry_entry_id)
            object.__setattr__(self, "last_entry_id", last_entry.registry_entry_id)
        else:
            if self.first_entry_id is not None or self.last_entry_id is not None:
                raise OfflineExecutionAuditRegistryValidationError("empty registry must not have entry ids.")
            object.__setattr__(self, "first_entry_id", None)
            object.__setattr__(self, "last_entry_id", None)

        for entry in frozen_entries:
            verify_offline_execution_audit_registry_entry(entry)
        _verify_entry_chain(frozen_entries)

        expected_registry_hash = _hash_payload(self._registry_hash_payload())
        if self.registry_hash:
            if self.registry_hash != expected_registry_hash:
                raise OfflineExecutionAuditRegistryIntegrityError("registry_hash mismatch.")
        else:
            object.__setattr__(self, "registry_hash", expected_registry_hash)

    @property
    def entry_count_value(self) -> int:
        return len(self.entries)

    def _registry_hash_payload(self) -> dict[str, Any]:
        return _registry_hash_payload(self)

    def canonical_payload(self, *, include_registry_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "registry_id": self.registry_id,
            "entries": [entry.canonical_payload(include_registry_entry_hash=True) for entry in self.entries],
            "entry_count": self.entry_count,
            "first_entry_id": self.first_entry_id,
            "last_entry_id": self.last_entry_id,
            "created_at_utc": _utc_iso(self.created_at_utc),
            "updated_at_utc": _utc_iso(self.updated_at_utc),
            "metadata": _thaw_read_only_value(self.metadata),
        }
        if include_registry_hash:
            payload["registry_hash"] = self.registry_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_registry_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfflineExecutionAuditRegistry":
        if not isinstance(data, Mapping):
            raise OfflineExecutionAuditRegistryValidationError("offline execution audit registry must be a mapping.")
        mapping = dict(data)
        allowed = {
            "schema_version",
            "registry_id",
            "registry_hash",
            "entries",
            "entry_count",
            "first_entry_id",
            "last_entry_id",
            "created_at_utc",
            "updated_at_utc",
            "metadata",
        }
        extra = sorted(set(mapping) - allowed)
        if extra:
            raise OfflineExecutionAuditRegistryValidationError(
                f"unexpected offline execution audit registry fields: {', '.join(extra)}."
            )
        required = allowed - {"first_entry_id", "last_entry_id"}
        missing = sorted(field for field in required if field not in mapping)
        if missing:
            raise OfflineExecutionAuditRegistryValidationError(
                f"offline execution audit registry is incomplete: {', '.join(missing)}."
            )
        try:
            entries = tuple(
                OfflineExecutionAuditRegistryEntry.from_dict(item)
                for item in mapping.get("entries", ())
            )
            return cls(
                schema_version=mapping.get("schema_version", OFFLINE_EXECUTION_AUDIT_REGISTRY_SCHEMA_VERSION),
                registry_id=mapping.get("registry_id", OFFLINE_EXECUTION_AUDIT_REGISTRY_ID),
                registry_hash=mapping.get("registry_hash", ""),
                entries=entries,
                entry_count=mapping["entry_count"],
                first_entry_id=mapping.get("first_entry_id"),
                last_entry_id=mapping.get("last_entry_id"),
                created_at_utc=mapping["created_at_utc"],
                updated_at_utc=mapping["updated_at_utc"],
                metadata=mapping.get("metadata", {}),
            )
        except KeyError as exc:
            raise OfflineExecutionAuditRegistryValidationError(
                "offline execution audit registry is incomplete."
            ) from exc

    def entry_by_registry_entry_id(self, registry_entry_id: str) -> OfflineExecutionAuditRegistryEntry:
        target = _require_hex_digest(registry_entry_id, "registry_entry_id")
        matches = tuple(entry for entry in self.entries if entry.registry_entry_id == target)
        if not matches:
            raise OfflineExecutionAuditRegistryValidationError("registry_entry_id was not found in the registry.")
        if len(matches) > 1:
            raise OfflineExecutionAuditRegistryConflictError("registry_entry_id already registered.")
        return matches[0]

    def entry_by_audit_record_id(self, audit_record_id: str) -> OfflineExecutionAuditRegistryEntry:
        target = _require_hex_digest(audit_record_id, "audit_record_id")
        matches = tuple(entry for entry in self.entries if entry.audit_record_id == target)
        if not matches:
            raise OfflineExecutionAuditRegistryValidationError("audit_record_id was not found in the registry.")
        if len(matches) > 1:
            raise OfflineExecutionAuditRegistryConflictError("audit_record_id already registered.")
        return matches[0]

    def entry_by_execution_attempt_id(self, execution_attempt_id: str) -> OfflineExecutionAuditRegistryEntry:
        target = _require_str(execution_attempt_id, "execution_attempt_id")
        matches = tuple(entry for entry in self.entries if entry.execution_attempt_id == target)
        if not matches:
            raise OfflineExecutionAuditRegistryValidationError(
                "execution_attempt_id was not found in the registry."
            )
        if len(matches) > 1:
            raise OfflineExecutionAuditRegistryConflictError("execution_attempt_id already registered.")
        return matches[0]

    def entry_by_audit_record_hash(self, audit_record_hash: str) -> OfflineExecutionAuditRegistryEntry:
        target = _require_hex_digest(audit_record_hash, "audit_record_hash")
        matches = tuple(entry for entry in self.entries if entry.audit_record_hash == target)
        if not matches:
            raise OfflineExecutionAuditRegistryValidationError("audit_record_hash was not found in the registry.")
        if len(matches) > 1:
            raise OfflineExecutionAuditRegistryConflictError("audit_record_hash already registered.")
        return matches[0]

    def entry_by_lineage_hash(self, lineage_hash: str) -> OfflineExecutionAuditRegistryEntry:
        target = _require_hex_digest(lineage_hash, "lineage_hash")
        matches = tuple(entry for entry in self.entries if entry.lineage_hash == target)
        if not matches:
            raise OfflineExecutionAuditRegistryValidationError("lineage_hash was not found in the registry.")
        if len(matches) > 1:
            raise OfflineExecutionAuditRegistryConflictError("lineage_hash already registered.")
        return matches[0]

    def with_entry(
        self,
        entry: OfflineExecutionAuditRegistryEntry,
        *,
        updated_at_utc: datetime | None = None,
    ) -> "OfflineExecutionAuditRegistry":
        entries = tuple(self.entries) + (entry,)
        return OfflineExecutionAuditRegistry(
            schema_version=self.schema_version,
            registry_id=self.registry_id,
            entries=entries,
            entry_count=len(entries),
            first_entry_id=entries[0].registry_entry_id if entries else None,
            last_entry_id=entries[-1].registry_entry_id if entries else None,
            created_at_utc=self.created_at_utc,
            updated_at_utc=updated_at_utc or datetime.now(timezone.utc),
            metadata=self.metadata,
        )


def verify_offline_execution_audit_registry_entry(
    entry: OfflineExecutionAuditRegistryEntry,
) -> OfflineExecutionAuditRegistryEntry:
    if not isinstance(entry, OfflineExecutionAuditRegistryEntry):
        raise OfflineExecutionAuditRegistryValidationError(
            "offline execution audit registry entry is required."
        )
    expected_registry_entry_id = _hash_payload(entry._registry_entry_id_payload())
    if entry.registry_entry_id != expected_registry_entry_id:
        raise OfflineExecutionAuditRegistryIntegrityError("registry_entry_id mismatch.")
    expected_registry_entry_hash = _hash_payload(entry._registry_entry_hash_payload())
    if entry.registry_entry_hash != expected_registry_entry_hash:
        raise OfflineExecutionAuditRegistryIntegrityError("registry_entry_hash mismatch.")
    return entry


def _verify_registry_material(
    registry: OfflineExecutionAuditRegistry,
) -> OfflineExecutionAuditRegistry:
    if not isinstance(registry, OfflineExecutionAuditRegistry):
        raise OfflineExecutionAuditRegistryValidationError("offline execution audit registry is required.")
    verify_offline_execution_audit_registry(registry)
    return registry


def verify_offline_execution_audit_registry(
    registry: OfflineExecutionAuditRegistry,
) -> OfflineExecutionAuditRegistry:
    if not isinstance(registry, OfflineExecutionAuditRegistry):
        raise OfflineExecutionAuditRegistryValidationError("offline execution audit registry is required.")
    if registry.schema_version != OFFLINE_EXECUTION_AUDIT_REGISTRY_SCHEMA_VERSION:
        raise OfflineExecutionAuditRegistryValidationError("schema_version must be 1.")
    if registry.registry_id != OFFLINE_EXECUTION_AUDIT_REGISTRY_ID:
        raise OfflineExecutionAuditRegistryValidationError(
            "registry_id must remain offline_execution_audit_registry."
        )
    if registry.entry_count != len(registry.entries):
        raise OfflineExecutionAuditRegistryValidationError("entry_count does not match entries.")
    if registry.entries:
        if registry.first_entry_id != registry.entries[0].registry_entry_id:
            raise OfflineExecutionAuditRegistryIntegrityError("first_entry_id mismatch.")
        if registry.last_entry_id != registry.entries[-1].registry_entry_id:
            raise OfflineExecutionAuditRegistryIntegrityError("last_entry_id mismatch.")
    else:
        if registry.first_entry_id is not None or registry.last_entry_id is not None:
            raise OfflineExecutionAuditRegistryValidationError("empty registry must not have entry ids.")
    for entry in registry.entries:
        verify_offline_execution_audit_registry_entry(entry)
    _verify_entry_chain(registry.entries)
    expected_registry_hash = _hash_payload(_registry_hash_payload(registry))
    if registry.registry_hash != expected_registry_hash:
        raise OfflineExecutionAuditRegistryIntegrityError("registry_hash mismatch.")
    return registry


def create_offline_execution_audit_registry(
    *,
    entries: Sequence[OfflineExecutionAuditRegistryEntry] | None = None,
    registry_id: str = OFFLINE_EXECUTION_AUDIT_REGISTRY_ID,
    created_at_utc: datetime | None = None,
    updated_at_utc: datetime | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> OfflineExecutionAuditRegistry:
    candidate_entries = tuple(entries or ())
    for entry in candidate_entries:
        verify_offline_execution_audit_registry_entry(entry)
    registry = OfflineExecutionAuditRegistry(
        registry_id=registry_id,
        entry_count=len(candidate_entries),
        first_entry_id=candidate_entries[0].registry_entry_id if candidate_entries else None,
        last_entry_id=candidate_entries[-1].registry_entry_id if candidate_entries else None,
        created_at_utc=created_at_utc or datetime.now(timezone.utc),
        updated_at_utc=updated_at_utc or datetime.now(timezone.utc),
        entries=candidate_entries,
        metadata=metadata or {},
    )
    return verify_offline_execution_audit_registry(registry)


def _registry_from_source(
    registry: OfflineExecutionAuditRegistry | Mapping[str, Any] | str | Path,
    *,
    root_directory: str | Path | None = None,
) -> OfflineExecutionAuditRegistry:
    if isinstance(registry, OfflineExecutionAuditRegistry):
        return verify_offline_execution_audit_registry(registry)
    if isinstance(registry, Mapping):
        return verify_offline_execution_audit_registry(OfflineExecutionAuditRegistry.from_dict(dict(registry)))
    return load_offline_execution_audit_registry(registry_file=registry, root_directory=root_directory)


def _existing_entry_for_audit_record(
    registry: OfflineExecutionAuditRegistry,
    audit_record: phase48.OfflineExecutionAuditRecord,
    metadata: Mapping[str, Any],
) -> OfflineExecutionAuditRegistryEntry | None:
    for entry in registry.entries:
        if _entry_matches_material(entry, audit_record=audit_record, metadata=metadata):
            return entry
    return None


def build_offline_execution_audit_registry_entry(
    *,
    audit_record: phase48.OfflineExecutionAuditRecord | Mapping[str, Any],
    entry_number: int,
    previous_entry_id: str | None = None,
    previous_entry_hash: str | None = None,
    registry_id: str = OFFLINE_EXECUTION_AUDIT_REGISTRY_ID,
    metadata: Mapping[str, Any] | None = None,
    registered_at_utc: datetime | None = None,
) -> OfflineExecutionAuditRegistryEntry:
    verified_audit_record = _build_verified_audit_record(audit_record)
    metadata_snapshot = _metadata_snapshot(metadata or {})
    entry = OfflineExecutionAuditRegistryEntry(
        registry_id=registry_id,
        audit_record_id=verified_audit_record.audit_record_id,
        audit_record_hash=verified_audit_record.audit_record_hash,
        lineage_hash=verified_audit_record.lineage_hash,
        experiment_id=verified_audit_record.experiment_id,
        execution_attempt_id=verified_audit_record.execution_attempt_id,
        previous_entry_id=previous_entry_id,
        previous_entry_hash=previous_entry_hash,
        entry_number=entry_number,
        registered_at_utc=registered_at_utc or datetime.now(timezone.utc),
        metadata=metadata_snapshot,
    )
    return verify_offline_execution_audit_registry_entry(entry)


def register_offline_execution_audit_record(
    *,
    registry_file: str | Path,
    audit_record: phase48.OfflineExecutionAuditRecord | Mapping[str, Any],
    root_directory: str | Path | None = None,
    registered_at_utc: datetime | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> OfflineExecutionAuditRegistryEntry:
    _, registry_path = _rooted_registry_path(
        registry_file,
        root_directory=root_directory,
        field_name="registry_file",
    )
    verified_audit_record = _build_verified_audit_record(audit_record)
    metadata_snapshot = _metadata_snapshot(metadata or {})
    registry = (
        load_offline_execution_audit_registry(registry_file=registry_file, root_directory=root_directory)
        if registry_path.exists()
        else create_offline_execution_audit_registry(
            created_at_utc=registered_at_utc or verified_audit_record.created_at_utc,
            updated_at_utc=registered_at_utc or verified_audit_record.created_at_utc,
            metadata=metadata_snapshot,
        )
    )
    existing = _existing_entry_for_audit_record(registry, verified_audit_record, metadata_snapshot)
    if existing is not None:
        return existing

    for entry in registry.entries:
        if entry.audit_record_id == verified_audit_record.audit_record_id:
            raise OfflineExecutionAuditRegistryConflictError("audit_record_id already registered and differs.")
        if entry.audit_record_hash == verified_audit_record.audit_record_hash:
            raise OfflineExecutionAuditRegistryConflictError("audit_record_hash already registered and differs.")
        if entry.execution_attempt_id == verified_audit_record.execution_attempt_id:
            raise OfflineExecutionAuditRegistryConflictError("execution_attempt_id already registered and differs.")
        if entry.lineage_hash == verified_audit_record.lineage_hash:
            raise OfflineExecutionAuditRegistryConflictError("lineage_hash already registered with incompatible context.")

    if registry.entries:
        previous_entry = registry.entries[-1]
        entry_number = previous_entry.entry_number + 1
        previous_entry_id = previous_entry.registry_entry_id
        previous_entry_hash = previous_entry.registry_entry_hash
    else:
        entry_number = 1
        previous_entry_id = None
        previous_entry_hash = None

    entry = build_offline_execution_audit_registry_entry(
        audit_record=verified_audit_record,
        entry_number=entry_number,
        previous_entry_id=previous_entry_id,
        previous_entry_hash=previous_entry_hash,
        registry_id=registry.registry_id,
        metadata=metadata_snapshot,
        registered_at_utc=registered_at_utc or verified_audit_record.created_at_utc,
    )
    updated_registry = registry.with_entry(entry, updated_at_utc=registered_at_utc or verified_audit_record.created_at_utc)
    save_offline_execution_audit_registry(
        registry_file=registry_file,
        registry=updated_registry,
        root_directory=root_directory,
    )
    return entry


def load_offline_execution_audit_registry(
    *,
    registry_file: str | Path,
    root_directory: str | Path | None = None,
) -> OfflineExecutionAuditRegistry:
    _, path = _rooted_registry_path(registry_file, root_directory=root_directory, field_name="registry_file")
    payload = _load_json(path)
    if not isinstance(payload, Mapping):
        raise OfflineExecutionAuditRegistryValidationError(
            "offline execution audit registry must be a JSON object."
        )
    registry = OfflineExecutionAuditRegistry.from_dict(payload)
    if _canonical_json(registry.as_dict()) != _canonical_json(payload):
        raise OfflineExecutionAuditRegistryIntegrityError("offline execution audit registry payload mismatch.")
    return verify_offline_execution_audit_registry(registry)


def save_offline_execution_audit_registry(
    *,
    registry_file: str | Path,
    registry: OfflineExecutionAuditRegistry,
    root_directory: str | Path | None = None,
) -> OfflineExecutionAuditRegistry:
    _, path = _rooted_registry_path(registry_file, root_directory=root_directory, field_name="registry_file")
    verified_registry = _verify_registry_material(registry)
    if path.exists():
        existing = load_offline_execution_audit_registry(registry_file=registry_file, root_directory=root_directory)
        if existing.as_dict() == verified_registry.as_dict():
            return existing
    _write_json_atomic(path, verified_registry.as_dict())
    return verified_registry


def list_registry_entries(
    registry: OfflineExecutionAuditRegistry | Mapping[str, Any] | str | Path,
    *,
    root_directory: str | Path | None = None,
) -> tuple[OfflineExecutionAuditRegistryEntry, ...]:
    return _registry_from_source(registry, root_directory=root_directory).entries


def find_entry_by_audit_record_id(
    registry: OfflineExecutionAuditRegistry | Mapping[str, Any] | str | Path,
    audit_record_id: str,
    *,
    root_directory: str | Path | None = None,
) -> OfflineExecutionAuditRegistryEntry | None:
    loaded = _registry_from_source(registry, root_directory=root_directory)
    matches = tuple(entry for entry in loaded.entries if entry.audit_record_id == _require_hex_digest(audit_record_id, "audit_record_id"))
    if not matches:
        return None
    if len(matches) > 1:
        raise OfflineExecutionAuditRegistryConflictError("audit_record_id already registered.")
    return matches[0]


def find_entry_by_execution_attempt_id(
    registry: OfflineExecutionAuditRegistry | Mapping[str, Any] | str | Path,
    execution_attempt_id: str,
    *,
    root_directory: str | Path | None = None,
) -> OfflineExecutionAuditRegistryEntry | None:
    loaded = _registry_from_source(registry, root_directory=root_directory)
    target = _require_str(execution_attempt_id, "execution_attempt_id")
    matches = tuple(entry for entry in loaded.entries if entry.execution_attempt_id == target)
    if not matches:
        return None
    if len(matches) > 1:
        raise OfflineExecutionAuditRegistryConflictError("execution_attempt_id already registered.")
    return matches[0]


def verify_offline_execution_audit_registry_integrity(
    registry: OfflineExecutionAuditRegistry,
) -> OfflineExecutionAuditRegistry:
    return verify_offline_execution_audit_registry(registry)


__all__ = [
    "OFFLINE_EXECUTION_AUDIT_REGISTRY_ID",
    "OFFLINE_EXECUTION_AUDIT_REGISTRY_SCHEMA_VERSION",
    "OFFLINE_EXECUTION_AUDIT_REGISTRY_VERSION",
    "OfflineExecutionAuditRegistry",
    "OfflineExecutionAuditRegistryConflictError",
    "OfflineExecutionAuditRegistryError",
    "OfflineExecutionAuditRegistryEntry",
    "OfflineExecutionAuditRegistryIntegrityError",
    "OfflineExecutionAuditRegistryValidationError",
    "build_offline_execution_audit_registry_entry",
    "create_offline_execution_audit_registry",
    "find_entry_by_audit_record_id",
    "find_entry_by_execution_attempt_id",
    "list_registry_entries",
    "load_offline_execution_audit_registry",
    "register_offline_execution_audit_record",
    "save_offline_execution_audit_registry",
    "verify_offline_execution_audit_registry",
    "verify_offline_execution_audit_registry_entry",
]
