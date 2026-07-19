from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from domain import Candle

from .historical_models import (
    HistoricalDataset,
    HistoricalDatasetManifest,
    HistoricalDatasetRequest,
    candles_content_hash,
)


def historical_manifest_hash(manifest: Mapping[str, Any]) -> str:
    return HistoricalDatasetManifest.from_dict(manifest).as_dict()["manifest_hash"]


def historical_content_hash(candles: Sequence[Candle]) -> str:
    return candles_content_hash(tuple(candles))


def build_historical_manifest(
    *,
    request: HistoricalDatasetRequest,
    effective_start_utc: datetime,
    effective_end_utc: datetime,
    created_at_utc: datetime,
    candle_count: int,
    page_count: int,
    gap_count: int,
    duplicate_count: int,
    content_hash: str,
) -> HistoricalDatasetManifest:
    manifest = HistoricalDatasetManifest(
        schema_version=1,
        dataset_id=content_hash,
        provider=request.provider,
        endpoint=request.endpoint,
        symbol=request.symbol,
        interval=request.interval,
        requested_start_utc=request.requested_start_utc,
        requested_end_utc=request.requested_end_utc,
        effective_start_utc=effective_start_utc.astimezone(timezone.utc),
        effective_end_utc=effective_end_utc.astimezone(timezone.utc),
        created_at_utc=created_at_utc.astimezone(timezone.utc),
        candle_count=candle_count,
        page_count=page_count,
        page_size=request.page_size,
        closed_candles_only=request.closed_candles_only,
        gap_count=gap_count,
        duplicate_count=duplicate_count,
        content_hash=content_hash,
    )
    return HistoricalDatasetManifest.from_dict(manifest.as_dict())


def build_historical_dataset(manifest: HistoricalDatasetManifest, candles: Sequence[Candle]) -> HistoricalDataset:
    return HistoricalDataset(manifest=manifest, candles=tuple(candles))
