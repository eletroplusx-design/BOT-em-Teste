from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
from typing import Any, Mapping

from domain import Candle
from domain.validation import DomainValidationError
from domain.serialization import serialize_value

from .errors import HistoricalDataConflictError, HistoricalDataIntegrityError, HistoricalDataValidationError
from .historical_models import HistoricalDataset, HistoricalDatasetManifest


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise HistoricalDataValidationError("Historical dataset not found.")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise HistoricalDataValidationError("Historical dataset is empty.")
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise HistoricalDataValidationError("Historical dataset is invalid JSON.") from exc
    if not isinstance(payload, Mapping):
        raise HistoricalDataValidationError("Historical dataset must be a JSON object.")
    return payload


def _write_atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    canonical = _canonical_json(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == canonical:
            return
        raise HistoricalDataConflictError("Historical dataset already exists and differs.")
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{id(path)}.tmp")
    try:
        tmp_path.write_text(canonical, encoding="utf-8")
        os.replace(tmp_path, path)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HistoricalDataValidationError("Failed to write historical dataset atomically.") from exc


def load_historical_dataset(path: str | Path) -> HistoricalDataset:
    file_path = Path(path)
    payload = _read_json(file_path)
    manifest_payload = payload.get("manifest")
    candles_payload = payload.get("candles")
    if not isinstance(manifest_payload, Mapping) or not isinstance(candles_payload, list):
        raise HistoricalDataIntegrityError("Historical dataset payload is incomplete.")
    manifest = HistoricalDatasetManifest.from_dict(manifest_payload)
    try:
        candles = tuple(Candle.from_dict(item) for item in candles_payload)
    except DomainValidationError as exc:
        raise HistoricalDataIntegrityError("Historical dataset candles are invalid.") from exc
    dataset = HistoricalDataset(manifest=manifest, candles=candles)
    if dataset.as_dict() != payload:
        raise HistoricalDataIntegrityError("Historical dataset payload mismatch.")
    return dataset


def verify_historical_dataset(path: str | Path) -> dict[str, Any]:
    dataset = load_historical_dataset(path)
    return {
        "verified": True,
        "dataset_id": dataset.manifest.dataset_id,
        "manifest_hash": dataset.manifest.manifest_hash,
        "content_hash": dataset.manifest.content_hash,
        "candle_count": dataset.manifest.candle_count,
        "page_count": dataset.manifest.page_count,
        "page_size": dataset.manifest.page_size,
    }


def historical_dataset_status(path: str | Path) -> dict[str, Any]:
    dataset = load_historical_dataset(path)
    return {
        "exists": True,
        "dataset_id": dataset.manifest.dataset_id,
        "provider": dataset.manifest.provider,
        "endpoint": dataset.manifest.endpoint,
        "symbol": dataset.manifest.symbol,
        "interval": dataset.manifest.interval,
        "requested_start_utc": dataset.manifest.as_dict()["requested_start_utc"],
        "requested_end_utc": dataset.manifest.as_dict()["requested_end_utc"],
        "effective_start_utc": dataset.manifest.as_dict()["effective_start_utc"],
        "effective_end_utc": dataset.manifest.as_dict()["effective_end_utc"],
        "created_at_utc": dataset.manifest.as_dict()["created_at_utc"],
        "candle_count": dataset.manifest.candle_count,
        "page_count": dataset.manifest.page_count,
        "page_size": dataset.manifest.page_size,
        "closed_candles_only": dataset.manifest.closed_candles_only,
        "gap_count": dataset.manifest.gap_count,
        "duplicate_count": dataset.manifest.duplicate_count,
        "content_hash": dataset.manifest.content_hash,
        "manifest_hash": dataset.manifest.manifest_hash,
    }


def save_historical_dataset(path: str | Path, dataset: HistoricalDataset) -> HistoricalDataset:
    file_path = Path(path)
    payload = dataset.as_dict()
    if file_path.exists():
        existing = load_historical_dataset(file_path)
        if existing.as_dict() != payload:
            raise HistoricalDataConflictError("Historical dataset already exists and differs.")
        return existing
    _write_atomic_json(file_path, payload)
    return dataset
