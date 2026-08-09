from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Mapping

from domain.serialization import serialize_value

from . import market_structure_structural_assessment_history as phase57
from . import offline_execution_audit_record as phase48
from .errors import HistoricalDataConflictError, HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError

PERSISTENT_MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_SCHEMA_VERSION = 1
PERSISTENT_MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_ID = (
    "persistent_market_structure_structural_assessment_history"
)
PERSISTENT_MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_VERSION = (
    "phase58_persistent_structural_assessment_history_v1"
)
PERSISTENT_MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_NON_OPERATIONAL_DECLARATION = (
    "This persistence layer is research-only and does not authorize replay, backtest, walk-forward, "
    "performance evaluation, ranking, scoring, paper trading, live trading, exchange connectivity, "
    "execution, or order submission."
)


class PersistentMarketStructureStructuralAssessmentHistoryError(HistoricalDataError):
    pass


class PersistentMarketStructureStructuralAssessmentHistoryValidationError(
    PersistentMarketStructureStructuralAssessmentHistoryError,
    HistoricalDataValidationError,
):
    pass


class PersistentMarketStructureStructuralAssessmentHistoryIntegrityError(
    PersistentMarketStructureStructuralAssessmentHistoryError,
    HistoricalDataIntegrityError,
):
    pass


class PersistentMarketStructureStructuralAssessmentHistoryConflictError(
    PersistentMarketStructureStructuralAssessmentHistoryError,
    HistoricalDataConflictError,
):
    pass


class PersistentMarketStructureStructuralAssessmentHistoryPersistenceError(
    PersistentMarketStructureStructuralAssessmentHistoryError,
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        serialize_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash_payload(payload: Any) -> str:
    try:
        return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    except (TypeError, ValueError) as exc:
        raise PersistentMarketStructureStructuralAssessmentHistoryValidationError(
            "payload is not serializable."
        ) from exc


def _require_history(value: Any) -> phase57.MarketStructureStructuralAssessmentHistory:
    if not isinstance(value, phase57.MarketStructureStructuralAssessmentHistory):
        raise PersistentMarketStructureStructuralAssessmentHistoryValidationError(
            "market structure structural assessment history is required."
        )
    try:
        return phase57.verify_market_structure_structural_assessment_history(value)
    except phase57.MarketStructureStructuralAssessmentHistoryValidationError as exc:
        raise PersistentMarketStructureStructuralAssessmentHistoryValidationError(str(exc)) from exc
    except phase57.MarketStructureStructuralAssessmentHistoryIntegrityError as exc:
        raise PersistentMarketStructureStructuralAssessmentHistoryIntegrityError(str(exc)) from exc


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise PersistentMarketStructureStructuralAssessmentHistoryValidationError(
            "market structure structural assessment history is missing."
        )
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise PersistentMarketStructureStructuralAssessmentHistoryValidationError(
            "market structure structural assessment history is empty."
        )
    try:
        return json.loads(text)
    except Exception as exc:
        raise PersistentMarketStructureStructuralAssessmentHistoryValidationError(
            "market structure structural assessment history is invalid JSON."
        ) from exc


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
        raise PersistentMarketStructureStructuralAssessmentHistoryPersistenceError(
            "failed to write market structure structural assessment history atomically."
        ) from exc


def resolve_market_structure_structural_assessment_history_path(
    history_file: str | Path,
    *,
    root_directory: str | Path | None = None,
) -> tuple[Path, Path]:
    try:
        return phase48._rooted_record_path(  # type: ignore[attr-defined]
            history_file,
            root_directory=root_directory,
            field_name="history_file",
        )
    except phase48.OfflineExecutionAuditRecordValidationError as exc:  # type: ignore[attr-defined]
        raise PersistentMarketStructureStructuralAssessmentHistoryValidationError(str(exc)) from exc


def load_market_structure_structural_assessment_history(
    *,
    history_file: str | Path,
    root_directory: str | Path | None = None,
) -> phase57.MarketStructureStructuralAssessmentHistory:
    _, path = resolve_market_structure_structural_assessment_history_path(
        history_file,
        root_directory=root_directory,
    )
    payload = _load_json(path)
    if not isinstance(payload, Mapping):
        raise PersistentMarketStructureStructuralAssessmentHistoryValidationError(
            "market structure structural assessment history must be a JSON object."
        )
    try:
        history = phase57.market_structure_structural_assessment_history_from_dict(payload)
    except phase57.MarketStructureStructuralAssessmentHistoryValidationError as exc:
        raise PersistentMarketStructureStructuralAssessmentHistoryValidationError(str(exc)) from exc
    except phase57.MarketStructureStructuralAssessmentHistoryIntegrityError as exc:
        raise PersistentMarketStructureStructuralAssessmentHistoryIntegrityError(str(exc)) from exc
    if _canonical_json(history.as_dict()) != _canonical_json(payload):
        raise PersistentMarketStructureStructuralAssessmentHistoryIntegrityError(
            "market structure structural assessment history payload mismatch."
        )
    return verify_persisted_market_structure_structural_assessment_history(history)


def save_market_structure_structural_assessment_history(
    *,
    history_file: str | Path,
    history: phase57.MarketStructureStructuralAssessmentHistory,
    root_directory: str | Path | None = None,
) -> phase57.MarketStructureStructuralAssessmentHistory:
    _, path = resolve_market_structure_structural_assessment_history_path(
        history_file,
        root_directory=root_directory,
    )
    verified_history = _require_history(history)
    payload = verified_history.as_dict()
    if path.exists():
        existing = load_market_structure_structural_assessment_history(
            history_file=history_file,
            root_directory=root_directory,
        )
        if existing.as_dict() == payload:
            return existing
        raise PersistentMarketStructureStructuralAssessmentHistoryConflictError(
            "market structure structural assessment history already exists and differs."
        )
    _write_json_atomic(path, payload)
    return verified_history


def verify_persisted_market_structure_structural_assessment_history(
    history: phase57.MarketStructureStructuralAssessmentHistory,
) -> phase57.MarketStructureStructuralAssessmentHistory:
    return _require_history(history)


__all__ = [
    "PERSISTENT_MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_ID",
    "PERSISTENT_MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_NON_OPERATIONAL_DECLARATION",
    "PERSISTENT_MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_SCHEMA_VERSION",
    "PERSISTENT_MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_HISTORY_VERSION",
    "PersistentMarketStructureStructuralAssessmentHistoryConflictError",
    "PersistentMarketStructureStructuralAssessmentHistoryError",
    "PersistentMarketStructureStructuralAssessmentHistoryIntegrityError",
    "PersistentMarketStructureStructuralAssessmentHistoryPersistenceError",
    "PersistentMarketStructureStructuralAssessmentHistoryValidationError",
    "load_market_structure_structural_assessment_history",
    "resolve_market_structure_structural_assessment_history_path",
    "save_market_structure_structural_assessment_history",
    "verify_persisted_market_structure_structural_assessment_history",
]
