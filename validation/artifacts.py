from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pandas as pd

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


def _normalize_content_scalar(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return str(value)
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def build_data_signature(df: pd.DataFrame, *, symbol: str, interval: str) -> dict[str, Any]:
    if df is None or df.empty:
        return {
            "symbol": symbol,
            "interval": interval,
            "rows": 0,
            "first_open_time": None,
            "last_open_time": None,
            "content_hash": hashlib.sha256(b"").hexdigest(),
        }

    columns = [column for column in ("open_time", "open", "high", "low", "close", "volume") if column in df.columns]
    payload_rows = []
    for _, row in df[columns].iterrows():
        payload_rows.append({column: _normalize_content_scalar(row[column]) for column in columns})
    serialized = json.dumps(
        {
            "symbol": symbol,
            "interval": interval,
            "rows": payload_rows,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    first_open = _normalize_content_scalar(df.iloc[0]["open_time"]) if "open_time" in df.columns else None
    last_open = _normalize_content_scalar(df.iloc[-1]["open_time"]) if "open_time" in df.columns else None
    return {
        "symbol": symbol,
        "interval": interval,
        "rows": len(df),
        "first_open_time": first_open,
        "last_open_time": last_open,
        "content_hash": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    }


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
    selection_criteria: Mapping[str, Any] | None = None,
    execution_contract: Mapping[str, Any] | None = None,
    window_signatures: Mapping[str, Any] | None = None,
    runner_trusted: bool = False,
    seed: int | None = None,
) -> dict[str, Any]:
    manifest = {
        "symbol": symbol,
        "interval": interval,
        "strategy_version": strategy_version,
        "costs": dict(costs),
        "selection_criteria": dict(selection_criteria or {}),
        "execution_contract": dict(execution_contract or {}),
        "window_signatures": dict(window_signatures or {}),
        "runner_trusted": runner_trusted,
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
    execution_contract: Mapping[str, Any],
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
        execution_contract=tuple(execution_contract.items()),
        symbol=symbol,
        interval=interval,
        frozen_at=frozen_at,
        manifest_hash=manifest_hash_value,
        window_id=window_id,
    )
