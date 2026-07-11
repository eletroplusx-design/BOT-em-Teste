from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .models import CandidateConfig, FrozenSelection, ValidationSplitConfig, WindowBounds


def _normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, set):
        return [_normalize(item) for item in sorted(value, key=str)]
    if hasattr(value, "as_dict"):
        return _normalize(value.as_dict())
    return value


def manifest_hash(manifest: Mapping[str, Any]) -> str:
    payload = json.dumps(_normalize(dict(manifest)), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_manifest(
    *,
    symbol: str,
    interval: str,
    strategy_version: str,
    costs: Mapping[str, Any],
    split_config: ValidationSplitConfig,
    candidate_grid: Sequence[CandidateConfig],
    windows: Sequence[WindowBounds],
    data_signature: Mapping[str, Any],
    seed: int | None = None,
) -> dict[str, Any]:
    manifest = {
        "symbol": symbol,
        "interval": interval,
        "strategy_version": strategy_version,
        "costs": dict(costs),
        "split_config": split_config,
        "candidate_grid": [candidate.as_dict() for candidate in candidate_grid],
        "windows": [window.as_dict() for window in windows],
        "data_signature": dict(data_signature),
        "seed": seed,
    }
    manifest["manifest_hash"] = manifest_hash(manifest)
    return manifest


def freeze_selection(
    candidate: CandidateConfig,
    *,
    strategy_version: str,
    costs: Mapping[str, Any],
    symbol: str,
    interval: str,
    frozen_at: datetime,
    manifest_hash_value: str,
    window_id: str,
) -> FrozenSelection:
    return FrozenSelection(
        candidate=candidate,
        strategy_version=strategy_version,
        costs=tuple(costs.items()),
        symbol=symbol,
        interval=interval,
        frozen_at=frozen_at,
        manifest_hash=manifest_hash_value,
        window_id=window_id,
    )
