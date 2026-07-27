from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from domain import Candle, DataSource
from domain.serialization import serialize_value

from .errors import HistoricalDataIntegrityError, HistoricalDataValidationError
from .okx_historical import (
    OKX_HISTORICAL_CANDLE_INTERVAL,
    OKX_HISTORICAL_CONFIRM_REQUIRED_VALUE,
    OKX_HISTORICAL_COLLECTION_DIRECTION,
)

# NOTE: The imports above are intentionally strict and do not pull in any
# provider, fetch, or preparation path. The audit layer is offline-only.
from .okx_historical import (
    OKX_HISTORICAL_CURSOR_NAME,
    OKX_HISTORICAL_CURSOR_EXCLUSIVE,
    OKX_HISTORICAL_DATASET_CANDLES_FILENAME,
    OKX_HISTORICAL_ENDPOINT_METHOD,
    OKX_HISTORICAL_ENDPOINT_PATH,
    OKX_HISTORICAL_ENDPOINT_URL,
    OKX_HISTORICAL_EXPECTED_CANDLE_COUNT,
    OKX_HISTORICAL_INSTRUMENT,
    OKX_HISTORICAL_MARKET_TYPE,
    OKX_HISTORICAL_NON_INGESTION_SCOPE_STATEMENT,
    OKX_HISTORICAL_PROVIDER_ID,
    OKX_HISTORICAL_PROVIDER_VERSION,
    OKX_HISTORICAL_REQUEST_LIMIT,
    OKX_HISTORICAL_REQUESTED_END_EXCLUSIVE_UTC,
    OKX_HISTORICAL_REQUESTED_START_INCLUSIVE_UTC,
    OKX_HISTORICAL_SOURCE_NAME,
    OkxHistoricalIngestionContract,
    OkxHistoricalIngestionManifest,
)

OKX_HISTORICAL_ARTIFACT_AUDIT_SCHEMA_VERSION = 1


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalDataValidationError(f"{field_name} is required.")
    return value.strip()


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalDataValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalDataValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalDataValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalDataValidationError(f"{field_name} must be a boolean.")
    return value


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.") from exc
    if not isinstance(value, datetime):
        raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoricalDataValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _hour_delta() -> timedelta:
    return timedelta(hours=1)


def _load_json(path: Path) -> Any:
    if not path.exists():
        raise HistoricalDataValidationError(f"{path.name} is missing.")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise HistoricalDataValidationError(f"{path.name} is empty.")
    try:
        return json.loads(text)
    except Exception as exc:
        raise HistoricalDataValidationError(f"{path.name} is invalid JSON.") from exc


def _strip_confirm(item: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    confirm = payload.pop("confirm", None)
    if confirm is not None and confirm != OKX_HISTORICAL_CONFIRM_REQUIRED_VALUE:
        raise HistoricalDataIntegrityError("confirm=1 is required for OKX historical candles.")
    return payload


def _load_candles(dataset_payload: Any) -> tuple[Candle, ...]:
    if not isinstance(dataset_payload, list) or not dataset_payload:
        raise HistoricalDataIntegrityError("OKX dataset payload must be a JSON array.")
    candles: list[Candle] = []
    for item in dataset_payload:
        if not isinstance(item, Mapping):
            raise HistoricalDataIntegrityError("OKX dataset candles must be mappings.")
        try:
            candle = Candle.from_dict(_strip_confirm(item))
        except Exception as exc:
            raise HistoricalDataIntegrityError("OKX dataset candles are invalid.") from exc
        candles.append(candle)
    return tuple(candles)


def _candle_hash(candles: Sequence[Candle]) -> str:
    return _hash_payload([candle.to_dict() for candle in candles])


def _assert_contract(contract: OkxHistoricalIngestionContract) -> None:
    if contract.schema_version != 1:
        raise HistoricalDataValidationError("schema_version must be 1.")
    if contract.source_name != OKX_HISTORICAL_SOURCE_NAME:
        raise HistoricalDataValidationError("source_name must be OKX.")
    if contract.provider_id != OKX_HISTORICAL_PROVIDER_ID:
        raise HistoricalDataValidationError("provider_id must be okx.public.klines.")
    if contract.provider_version != OKX_HISTORICAL_PROVIDER_VERSION:
        raise HistoricalDataValidationError("provider_version must be v1.")
    if contract.market_type != OKX_HISTORICAL_MARKET_TYPE:
        raise HistoricalDataValidationError("market_type must be spot.")
    if contract.instrument != OKX_HISTORICAL_INSTRUMENT:
        raise HistoricalDataValidationError("instrument must be BTC-USDT.")
    if contract.symbol != "BTCUSDT":
        raise HistoricalDataValidationError("symbol must be BTCUSDT.")
    if contract.interval != OKX_HISTORICAL_CANDLE_INTERVAL:
        raise HistoricalDataValidationError("interval must be 1H.")
    if contract.endpoint_method != OKX_HISTORICAL_ENDPOINT_METHOD:
        raise HistoricalDataValidationError("endpoint_method must be GET.")
    if contract.endpoint_url != OKX_HISTORICAL_ENDPOINT_URL:
        raise HistoricalDataValidationError("endpoint_url must be the official OKX history-candles endpoint.")
    if contract.endpoint_path != OKX_HISTORICAL_ENDPOINT_PATH:
        raise HistoricalDataValidationError("endpoint_path must be /api/v5/market/history-candles.")
    if contract.cursor_name != OKX_HISTORICAL_CURSOR_NAME:
        raise HistoricalDataValidationError("cursor_name must be after.")
    if contract.cursor_exclusive is not OKX_HISTORICAL_CURSOR_EXCLUSIVE:
        raise HistoricalDataValidationError("cursor_exclusive must be true.")
    if contract.collection_direction != OKX_HISTORICAL_COLLECTION_DIRECTION:
        raise HistoricalDataValidationError("collection_direction must be reverse_chronological.")
    if contract.request_limit != OKX_HISTORICAL_REQUEST_LIMIT:
        raise HistoricalDataValidationError("request_limit must be 100.")
    if contract.confirm_required_value != OKX_HISTORICAL_CONFIRM_REQUIRED_VALUE:
        raise HistoricalDataValidationError("confirm_required_value must be 1.")
    if contract.requested_start_inclusive_utc != OKX_HISTORICAL_REQUESTED_START_INCLUSIVE_UTC:
        raise HistoricalDataValidationError("requested_start_inclusive_utc diverges from the Fase 19A contract.")
    if contract.requested_end_exclusive_utc != OKX_HISTORICAL_REQUESTED_END_EXCLUSIVE_UTC:
        raise HistoricalDataValidationError("requested_end_exclusive_utc diverges from the Fase 19A contract.")
    if contract.request_params != {"instId": OKX_HISTORICAL_INSTRUMENT, "bar": OKX_HISTORICAL_CANDLE_INTERVAL, "limit": OKX_HISTORICAL_REQUEST_LIMIT}:
        raise HistoricalDataValidationError("request_params diverge from the Fase 19A contract.")
    if contract.historical_research_only is not True:
        raise HistoricalDataValidationError("historical_research_only must be true.")
    if contract.operational_evidence is not False:
        raise HistoricalDataValidationError("operational_evidence must be false.")
    if contract.paper_promotion_eligible is not False:
        raise HistoricalDataValidationError("paper_promotion_eligible must be false.")


def _validate_candles(candles: Sequence[Candle], contract: OkxHistoricalIngestionContract) -> tuple[int, int, int]:
    if len(candles) != OKX_HISTORICAL_EXPECTED_CANDLE_COUNT:
        raise HistoricalDataIntegrityError("OKX dataset candle count diverges from the Fase 19A contract.")
    if candles[0].open_time != contract.requested_start_inclusive_utc:
        raise HistoricalDataIntegrityError("requested_start_inclusive_utc does not match candles.")
    if candles[-1].close_time != contract.requested_end_exclusive_utc - timedelta(milliseconds=1):
        raise HistoricalDataIntegrityError("requested_end_exclusive_utc does not match candles.")
    if any(candle.source != DataSource.OKX for candle in candles):
        raise HistoricalDataIntegrityError("OKX dataset candle source mismatch.")
    if any(candle.symbol != contract.symbol for candle in candles):
        raise HistoricalDataIntegrityError("OKX dataset candle symbol mismatch.")
    if any(candle.interval != contract.interval for candle in candles):
        raise HistoricalDataIntegrityError("OKX dataset candle interval mismatch.")
    aligned_candle_count = 0
    for previous, current in zip(candles, candles[1:]):
        if current.open_time != previous.open_time + _hour_delta():
            raise HistoricalDataIntegrityError("OKX dataset candles are not contiguous.")
    for candle in candles:
        if candle.open_time.minute != 0 or candle.open_time.second != 0 or candle.open_time.microsecond != 0:
            raise HistoricalDataIntegrityError("OKX candle timestamp must be aligned to the UTC hour.")
        if candle.close_time != candle.open_time + _hour_delta() - timedelta(milliseconds=1):
            raise HistoricalDataIntegrityError("OKX dataset candle close_time diverges.")
        aligned_candle_count += 1
    return aligned_candle_count, 0, 0


@dataclass(frozen=True, slots=True)
class OkxHistoricalArtifactAuditReport:
    dataset_file: Path
    manifest_file: Path
    contract: OkxHistoricalIngestionContract
    manifest: OkxHistoricalIngestionManifest
    candle_count: int
    expected_candle_count: int
    first_candle_open_utc: datetime
    first_candle_close_utc: datetime
    last_candle_open_utc: datetime
    last_candle_close_utc: datetime
    dataset_hash: str
    manifest_hash: str
    contract_hash: str
    aligned_candle_count: int
    gap_count: int
    duplicate_count: int
    confirm_required_value: int
    historical_research_only: bool
    operational_evidence: bool
    paper_promotion_eligible: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_file": str(self.dataset_file),
            "manifest_file": str(self.manifest_file),
            "contract": self.contract.as_dict(),
            "manifest": self.manifest.as_dict(),
            "candle_count": self.candle_count,
            "expected_candle_count": self.expected_candle_count,
            "first_candle_open_utc": _utc_iso(self.first_candle_open_utc),
            "first_candle_close_utc": _utc_iso(self.first_candle_close_utc),
            "last_candle_open_utc": _utc_iso(self.last_candle_open_utc),
            "last_candle_close_utc": _utc_iso(self.last_candle_close_utc),
            "dataset_hash": self.dataset_hash,
            "manifest_hash": self.manifest_hash,
            "contract_hash": self.contract_hash,
            "aligned_candle_count": self.aligned_candle_count,
            "gap_count": self.gap_count,
            "duplicate_count": self.duplicate_count,
            "confirm_required_value": self.confirm_required_value,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }


def audit_okx_historical_artifacts(*, dataset_file: str | Path, manifest_file: str | Path) -> OkxHistoricalArtifactAuditReport:
    dataset_path = Path(dataset_file)
    manifest_path = Path(manifest_file)
    dataset_payload = _load_json(dataset_path)
    manifest_payload = _load_json(manifest_path)
    if not isinstance(manifest_payload, Mapping):
        raise HistoricalDataIntegrityError("OKX manifest payload must be a JSON object.")
    if "manifest_hash" not in manifest_payload or not str(manifest_payload.get("manifest_hash", "")).strip():
        raise HistoricalDataValidationError("manifest_hash is required.")
    if "contract" not in manifest_payload or not isinstance(manifest_payload["contract"], Mapping):
        raise HistoricalDataValidationError("contract is required.")
    if "contract_hash" not in manifest_payload["contract"] or not str(manifest_payload["contract"].get("contract_hash", "")).strip():
        raise HistoricalDataValidationError("contract_hash is required.")
    manifest = OkxHistoricalIngestionManifest.from_dict(manifest_payload)
    _assert_contract(manifest.contract)
    if manifest.non_ingestion_scope_statement != OKX_HISTORICAL_NON_INGESTION_SCOPE_STATEMENT:
        raise HistoricalDataValidationError("non_ingestion_scope_statement diverges from the Fase 19A contract.")
    candles = _load_candles(dataset_payload)
    if manifest.expected_candle_count != len(candles):
        raise HistoricalDataIntegrityError("manifest expected_candle_count does not match candles.")
    if manifest.found_candle_count != len(candles):
        raise HistoricalDataIntegrityError("manifest found_candle_count does not match candles.")
    if manifest.contract.expected_candle_count != len(candles):
        raise HistoricalDataIntegrityError("contract expected candle count mismatch.")
    aligned_candle_count, gap_count, duplicate_count = _validate_candles(candles, manifest.contract)
    dataset_hash = _candle_hash(candles)
    if manifest.dataset_hash != dataset_hash:
        raise HistoricalDataIntegrityError("dataset_hash mismatch.")
    if manifest.contract.contract_hash != _hash_payload(manifest.contract.canonical_payload()):
        raise HistoricalDataIntegrityError("contract_hash mismatch.")
    if manifest.manifest_hash != _hash_payload(manifest.canonical_payload()):
        raise HistoricalDataIntegrityError("manifest_hash mismatch.")
    if manifest.contract.historical_research_only is not True:
        raise HistoricalDataValidationError("historical_research_only must be true.")
    if manifest.contract.operational_evidence is not False:
        raise HistoricalDataValidationError("operational_evidence must be false.")
    if manifest.contract.paper_promotion_eligible is not False:
        raise HistoricalDataValidationError("paper_promotion_eligible must be false.")
    return OkxHistoricalArtifactAuditReport(
        dataset_file=dataset_path,
        manifest_file=manifest_path,
        contract=manifest.contract,
        manifest=manifest,
        candle_count=len(candles),
        expected_candle_count=manifest.expected_candle_count,
        first_candle_open_utc=candles[0].open_time,
        first_candle_close_utc=candles[0].close_time,
        last_candle_open_utc=candles[-1].open_time,
        last_candle_close_utc=candles[-1].close_time,
        dataset_hash=dataset_hash,
        manifest_hash=manifest.manifest_hash,
        contract_hash=manifest.contract.contract_hash,
        aligned_candle_count=aligned_candle_count,
        gap_count=gap_count,
        duplicate_count=duplicate_count,
        confirm_required_value=manifest.contract.confirm_required_value,
        historical_research_only=manifest.contract.historical_research_only,
        operational_evidence=manifest.contract.operational_evidence,
        paper_promotion_eligible=manifest.contract.paper_promotion_eligible,
    )
