from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from domain import Candle, DataSource, MarketSnapshot

from .errors import (
    HistoricalDataConflictError,
    HistoricalDataError,
    HistoricalDataIntegrityError,
    HistoricalDataValidationError,
    MarketDataError,
    MarketDataExpiredError,
    MarketDataValidationError,
)
from .provider import BinancePublicKlinesProvider
from .kucoin_provider import KuCoinPublicSpotKlinesProvider
from .historical_manifest import build_historical_dataset, build_historical_manifest, historical_content_hash
from .historical_models import HistoricalDataset, HistoricalDatasetRequest
from .provider_qualification import HistoricalProviderQualification
from .historical_store import historical_dataset_status, load_historical_dataset, save_historical_dataset, verify_historical_dataset
from .validation import MAX_BINANCE_LIMIT, validate_klines_payload, validate_limit, validate_symbol_interval


HISTORICAL_ENDPOINT = BinancePublicKlinesProvider.base_url
HISTORICAL_SCHEMA_VERSION = 2
HISTORICAL_MAX_PAGES = 1000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_utc(value: datetime | str, field_name: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalDataValidationError(f"{field_name} is required.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.") from exc
    else:
        raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return dt.astimezone(timezone.utc)


def _next_open_time(candle: Candle) -> datetime:
    return candle.close_time + timedelta(milliseconds=1)


def _build_request(
    *,
    symbol: str,
    interval: str,
    requested_start_utc: datetime | str,
    requested_end_utc: datetime | str,
    page_size: int,
    provider_qualification: HistoricalProviderQualification,
    endpoint: str,
) -> HistoricalDatasetRequest:
    symbol, interval = validate_symbol_interval(symbol, interval)
    page_limit = provider_qualification.pagination_limit or MAX_BINANCE_LIMIT
    page_size = validate_limit(page_size, maximum=page_limit)
    return HistoricalDatasetRequest(
        provider=provider_qualification.provider_id,
        provider_qualification=provider_qualification,
        endpoint=endpoint,
        symbol=symbol,
        interval=interval,
        requested_start_utc=_require_utc(requested_start_utc, "requested_start_utc"),
        requested_end_utc=_require_utc(requested_end_utc, "requested_end_utc"),
        page_size=page_size,
        closed_candles_only=True,
    )


def _require_max_pages(value: Any) -> int:
    if type(value) is not int:
        raise HistoricalDataValidationError("max_pages must be an integer.")
    if value <= 0:
        raise HistoricalDataValidationError("max_pages must be greater than zero.")
    if value > HISTORICAL_MAX_PAGES:
        raise HistoricalDataValidationError(f"max_pages must be <= {HISTORICAL_MAX_PAGES}.")
    return value


def _request_matches_dataset(request: HistoricalDatasetRequest, dataset: HistoricalDataset) -> bool:
    manifest = dataset.manifest
    return manifest.matches_request(request)


def _finalize_dataset(
    *,
    request: HistoricalDatasetRequest,
    candles: list[Candle],
    created_at_utc: datetime | None = None,
    page_count: int,
    gap_count: int = 0,
    duplicate_count: int = 0,
) -> HistoricalDataset:
    if not candles:
        raise HistoricalDataValidationError("Historical dataset has no closed candles.")
    content_hash = historical_content_hash(candles)
    manifest = build_historical_manifest(
        request=request,
        effective_start_utc=candles[0].open_time,
        effective_end_utc=candles[-1].close_time,
        created_at_utc=created_at_utc or _utcnow(),
        candle_count=len(candles),
        page_count=page_count,
        gap_count=gap_count,
        duplicate_count=duplicate_count,
        content_hash=content_hash,
    )
    dataset = build_historical_dataset(manifest, candles)
    return dataset


def _validate_page_candles(*, payload: Any, symbol: str, interval: str, now: datetime, source: DataSource = DataSource.BINANCE) -> list[Candle]:
    try:
        return validate_klines_payload(payload, symbol=symbol, interval=interval, now=now, source=source)
    except MarketDataValidationError as exc:
        raise HistoricalDataValidationError(str(exc)) from exc


def fetch_historical_public_klines(
    *,
    provider: BinancePublicKlinesProvider | None = None,
    provider_qualification: HistoricalProviderQualification | None = None,
    symbol: str,
    interval: str,
    requested_start_utc: datetime | str,
    requested_end_utc: datetime | str,
    page_size: int = MAX_BINANCE_LIMIT,
    max_pages: int = HISTORICAL_MAX_PAGES,
) -> HistoricalDataset:
    provider = provider or BinancePublicKlinesProvider()
    max_pages = _require_max_pages(max_pages)
    provider_qualification = provider_qualification or provider.historical_qualification(symbol=symbol, interval=interval)
    request = _build_request(
        symbol=symbol,
        interval=interval,
        requested_start_utc=requested_start_utc,
        requested_end_utc=requested_end_utc,
        page_size=page_size,
        provider_qualification=provider_qualification,
        endpoint=getattr(provider, "base_url", HISTORICAL_ENDPOINT),
    )
    operation_now = _utcnow()
    if request.requested_end_utc > operation_now:
        raise HistoricalDataValidationError("requested_end_utc must not be in the future.")

    current_start = request.requested_start_utc
    current_start_ms = int(current_start.timestamp() * 1000)
    end_ms = int(request.requested_end_utc.timestamp() * 1000)
    candles: list[Candle] = []
    page_count = 0
    last_open_time: datetime | None = None

    while True:
        if page_count >= max_pages:
            raise HistoricalDataValidationError("Maximum historical page count exceeded.")
        payload = provider.fetch_klines(
            request.symbol,
            request.interval,
            request.page_size,
            start_time=current_start_ms,
            end_time=end_ms,
        )
        page_candles = _validate_page_candles(
            payload=payload,
            symbol=request.symbol,
            interval=request.interval,
            now=operation_now,
            source=getattr(provider, "historical_source", DataSource.BINANCE),
        )
        if not page_candles:
            raise HistoricalDataValidationError("Historical page did not return closed candles.")
        if page_count == 0:
            if page_candles[0].open_time != request.requested_start_utc:
                raise HistoricalDataValidationError("Historical page must start at requested_start_utc.")
        else:
            expected_open = _next_open_time(candles[-1])
            if page_candles[0].open_time < expected_open:
                raise HistoricalDataValidationError("Duplicate candle detected between pages.")
            if page_candles[0].open_time > expected_open:
                raise HistoricalDataValidationError("Gap detected between pages.")
            if last_open_time is not None and page_candles[0].open_time <= last_open_time:
                raise HistoricalDataValidationError("Historical page made no progress.")
        if page_candles[-1].close_time > request.requested_end_utc:
            raise HistoricalDataValidationError("Historical page exceeds requested_end_utc.")
        candles.extend(page_candles)
        page_count += 1
        last_open_time = candles[-1].open_time
        if candles[-1].close_time < request.requested_end_utc:
            current_start_ms = int((_next_open_time(candles[-1])).timestamp() * 1000)
            continue
        if candles[-1].close_time != request.requested_end_utc:
            raise HistoricalDataValidationError("Historical dataset does not end at requested_end_utc.")
        if len(page_candles) < request.page_size:
            break
        break

    final_candles = _validate_page_candles(
        payload=[
            [
                int(candle.open_time.timestamp() * 1000),
                str(candle.open),
                str(candle.high),
                str(candle.low),
                str(candle.close),
                str(candle.volume),
                int(candle.close_time.timestamp() * 1000),
                0,
                0,
                0,
                0,
                0,
            ]
            for candle in candles
        ],
        symbol=request.symbol,
        interval=request.interval,
        now=operation_now,
        source=getattr(provider, "historical_source", DataSource.BINANCE),
    )
    return _finalize_dataset(request=request, candles=final_candles, created_at_utc=operation_now, page_count=page_count)


def prepare_historical_dataset(
    *,
    output_file: str | Path,
    provider: BinancePublicKlinesProvider | None = None,
    symbol: str,
    interval: str,
    requested_start_utc: datetime | str,
    requested_end_utc: datetime | str,
    page_size: int = MAX_BINANCE_LIMIT,
    max_pages: int = HISTORICAL_MAX_PAGES,
) -> dict[str, Any]:
    resolved_provider = provider or BinancePublicKlinesProvider()
    output_path = Path(output_file)
    provider_qualification = resolved_provider.historical_qualification(symbol=symbol, interval=interval)
    page_limit = provider_qualification.pagination_limit or MAX_BINANCE_LIMIT
    page_size_checked = validate_limit(page_size, maximum=page_limit)
    requested_start = _require_utc(requested_start_utc, "requested_start_utc")
    requested_end = _require_utc(requested_end_utc, "requested_end_utc")
    symbol_checked, interval_checked = validate_symbol_interval(symbol, interval)
    if output_path.exists():
        existing = load_historical_dataset(output_path)
        if (
            existing.manifest.provider != resolved_provider.provider_identity
            or existing.manifest.provider_qualification != provider_qualification
            or existing.manifest.endpoint != getattr(resolved_provider, "base_url", HISTORICAL_ENDPOINT)
            or existing.manifest.symbol != symbol_checked
            or existing.manifest.interval != interval_checked
            or existing.manifest.requested_start_utc != requested_start
            or existing.manifest.requested_end_utc != requested_end
            or existing.manifest.page_size != page_size_checked
            or existing.manifest.closed_candles_only is not True
        ):
            raise HistoricalDataConflictError("Historical dataset already exists and differs.")
        return {
            "output": str(output_path),
            "dataset_id": existing.manifest.dataset_id,
            "manifest_hash": existing.manifest.manifest_hash,
            "content_hash": existing.manifest.content_hash,
            "candle_count": existing.manifest.candle_count,
            "page_count": existing.manifest.page_count,
            "page_size": existing.manifest.page_size,
            "reused": True,
        }

    dataset = fetch_historical_public_klines(
        provider=resolved_provider,
        provider_qualification=provider_qualification,
        symbol=symbol,
        interval=interval,
        requested_start_utc=requested_start_utc,
        requested_end_utc=requested_end_utc,
        page_size=page_size,
        max_pages=max_pages,
    )
    saved = save_historical_dataset(output_path, dataset)
    return {
        "output": str(output_path),
        "dataset_id": saved.manifest.dataset_id,
        "manifest_hash": saved.manifest.manifest_hash,
        "content_hash": saved.manifest.content_hash,
        "candle_count": saved.manifest.candle_count,
        "page_count": saved.manifest.page_count,
        "page_size": saved.manifest.page_size,
        "reused": False,
    }


def prepare_historical_dataset_kucoin(
    *,
    output_file: str | Path,
    symbol: str,
    interval: str,
    requested_start_utc: datetime | str,
    requested_end_utc: datetime | str,
    page_size: int = KuCoinPublicSpotKlinesProvider.historical_pagination_limit,
    max_pages: int = HISTORICAL_MAX_PAGES,
) -> dict[str, Any]:
    return prepare_historical_dataset(
        output_file=output_file,
        provider=KuCoinPublicSpotKlinesProvider(),
        symbol=symbol,
        interval=interval,
        requested_start_utc=requested_start_utc,
        requested_end_utc=requested_end_utc,
        page_size=page_size,
        max_pages=max_pages,
    )


def status_historical_dataset(*, input_file: str | Path) -> dict[str, Any]:
    return historical_dataset_status(input_file)


def verify_historical_dataset_file(*, input_file: str | Path) -> dict[str, Any]:
    return verify_historical_dataset(input_file)


def load_historical_dataset_file(input_file: str | Path) -> HistoricalDataset:
    return load_historical_dataset(input_file)
