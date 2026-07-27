from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest
import requests

import market_data.okx_artifact_audit as audit
import market_data.okx_historical as okx
from domain import Candle, DataSource
from domain.serialization import serialize_value
from market_data.errors import HistoricalDataIntegrityError, HistoricalDataValidationError

ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)
START_UTC = okx.OKX_HISTORICAL_REQUESTED_START_INCLUSIVE_UTC
END_EXCLUSIVE_UTC = okx.OKX_HISTORICAL_REQUESTED_END_EXCLUSIVE_UTC
TOTAL_CANDLES = okx.OKX_HISTORICAL_EXPECTED_CANDLE_COUNT
PAGE_SIZE = okx.OKX_HISTORICAL_REQUEST_LIMIT
PAGE_COUNT = TOTAL_CANDLES // PAGE_SIZE + (1 if TOTAL_CANDLES % PAGE_SIZE else 0)


def _workspace_tmp_dir(name: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp" / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _canonical_hash(payload):
    return sha256(json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _candle(open_time: datetime, *, base: int) -> Candle:
    return Candle.from_dict(
        {
            "open_time": open_time,
            "close_time": open_time + ONE_HOUR - ONE_MS,
            "open": str(base),
            "high": str(base + 5),
            "low": str(base - 2),
            "close": str(base + 1),
            "volume": str(1000 + base),
            "symbol": okx.OKX_HISTORICAL_SYMBOL,
            "interval": okx.OKX_HISTORICAL_CANDLE_INTERVAL,
            "source": DataSource.OKX,
        }
    )


def _candles(count: int = TOTAL_CANDLES) -> tuple[Candle, ...]:
    return tuple(_candle(START_UTC + idx * ONE_HOUR, base=10_000 + idx) for idx in range(count))


def _dataset_payload(candles: tuple[Candle, ...], *, confirm: int = 1) -> list[dict[str, object]]:
    payload = []
    for candle in candles:
        item = candle.to_dict()
        item["confirm"] = confirm
        payload.append(item)
    return payload


def _contract_payload() -> dict[str, object]:
    return okx.OkxHistoricalIngestionContract().as_dict()


def _manifest_payload(candles: tuple[Candle, ...]) -> dict[str, object]:
    contract = okx.OkxHistoricalIngestionContract()
    manifest = okx.OkxHistoricalIngestionManifest(
        schema_version=1,
        contract=contract,
        expected_candle_count=len(candles),
        found_candle_count=len(candles),
        page_count=PAGE_COUNT,
        first_candle_open_utc=candles[0].open_time,
        first_candle_close_utc=candles[0].close_time,
        last_candle_open_utc=candles[-1].open_time,
        last_candle_close_utc=candles[-1].close_time,
        trimmed_before_start_count=84,
        gap_count=0,
        duplicate_count=0,
        overlap_count=0,
        cursor_no_progress_count=0,
        http_error_count=0,
        timeout_count=0,
        malformed_response_count=0,
        dataset_hash=audit._hash_payload([candle.to_dict() for candle in candles]),
    )
    return manifest.as_dict()


def _refresh_hashes(dataset_payload: list[dict[str, object]], manifest_payload: dict[str, object]) -> None:
    normalized_dataset = [{k: v for k, v in item.items() if k != "confirm"} for item in dataset_payload]
    contract_payload = manifest_payload["contract"]
    contract_payload["contract_hash"] = _canonical_hash({k: v for k, v in contract_payload.items() if k != "contract_hash"})
    manifest_payload["dataset_hash"] = _canonical_hash(normalized_dataset)
    manifest_payload["manifest_hash"] = _canonical_hash({k: v for k, v in manifest_payload.items() if k != "manifest_hash"})


def _refresh_for_dataset_hash_mismatch(dataset_payload: list[dict[str, object]], manifest_payload: dict[str, object]) -> None:
    contract_payload = manifest_payload["contract"]
    contract_payload["contract_hash"] = _canonical_hash({k: v for k, v in contract_payload.items() if k != "contract_hash"})
    manifest_payload["manifest_hash"] = _canonical_hash({k: v for k, v in manifest_payload.items() if k != "manifest_hash"})


def _refresh_for_manifest_hash_mismatch(dataset_payload: list[dict[str, object]], manifest_payload: dict[str, object]) -> None:
    normalized_dataset = [{k: v for k, v in item.items() if k != "confirm"} for item in dataset_payload]
    contract_payload = manifest_payload["contract"]
    contract_payload["contract_hash"] = _canonical_hash({k: v for k, v in contract_payload.items() if k != "contract_hash"})
    manifest_payload["dataset_hash"] = _canonical_hash(normalized_dataset)


def _write_artifacts(root: Path, dataset_payload: list[dict[str, object]], manifest_payload: dict[str, object], *, suffix: str) -> tuple[Path, Path]:
    dataset_file = root / f"{suffix}.candles.json"
    manifest_file = root / f"{suffix}.manifest.json"
    dataset_file.write_text(json.dumps(dataset_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    manifest_file.write_text(json.dumps(manifest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return dataset_file, manifest_file


@pytest.fixture(scope="module")
def okx_audit_artifacts():
    root = _workspace_tmp_dir(f"okx-phase19b-audit-{Path(__file__).stem}")
    candles = _candles()
    dataset_payload = _dataset_payload(candles, confirm=1)
    manifest_payload = _manifest_payload(candles)
    dataset_file, manifest_file = _write_artifacts(root, dataset_payload, manifest_payload, suffix="okx-phase19b")
    report = audit.audit_okx_historical_artifacts(dataset_file=dataset_file, manifest_file=manifest_file)
    return {
        "root": root,
        "candles": candles,
        "dataset_payload": dataset_payload,
        "manifest_payload": manifest_payload,
        "dataset_file": dataset_file,
        "manifest_file": manifest_file,
        "report": report,
    }


def test_okx_artifact_audit_is_offline_and_reports_expected_contract(okx_audit_artifacts, monkeypatch):
    def _fail_network(*args, **kwargs):
        raise AssertionError("network must not be reached")

    monkeypatch.setattr(requests.sessions.Session, "get", _fail_network, raising=True)
    monkeypatch.setattr(okx.OkxPublicSpotHistoryCandlesProvider, "fetch_klines", _fail_network, raising=True)

    report = audit.audit_okx_historical_artifacts(
        dataset_file=okx_audit_artifacts["dataset_file"],
        manifest_file=okx_audit_artifacts["manifest_file"],
    )

    assert report.candle_count == TOTAL_CANDLES
    assert report.expected_candle_count == TOTAL_CANDLES
    assert report.first_candle_open_utc == START_UTC
    assert report.first_candle_close_utc == START_UTC + ONE_HOUR - ONE_MS
    assert report.last_candle_open_utc == END_EXCLUSIVE_UTC - ONE_HOUR
    assert report.last_candle_close_utc == END_EXCLUSIVE_UTC - ONE_MS
    assert report.dataset_hash == report.manifest.dataset_hash
    assert report.manifest_hash == report.manifest.manifest_hash
    assert report.contract_hash == report.contract.contract_hash
    assert report.aligned_candle_count == TOTAL_CANDLES
    assert report.gap_count == 0
    assert report.duplicate_count == 0
    assert report.confirm_required_value == 1
    assert report.contract.source_name == "OKX"
    assert report.contract.provider_id == "okx.public.klines"
    assert report.contract.market_type == "spot"
    assert report.contract.instrument == "BTC-USDT"
    assert report.contract.symbol == "BTCUSDT"
    assert report.contract.interval == "1H"
    assert report.contract.request_params == {"instId": "BTC-USDT", "bar": "1H", "limit": 100}
    assert report.contract.historical_research_only is True
    assert report.contract.operational_evidence is False
    assert report.contract.paper_promotion_eligible is False
    assert report.manifest.non_ingestion_scope_statement == okx.OKX_HISTORICAL_NON_INGESTION_SCOPE_STATEMENT
    assert okx_audit_artifacts["report"].as_dict()["dataset_file"].endswith(".candles.json")


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (
            lambda dataset, manifest: (
                dataset.pop(101),
                manifest.__setitem__("expected_candle_count", len(dataset)),
                manifest.__setitem__("found_candle_count", len(dataset)),
            ),
            "expected_candle_count diverges from the OKX contract",
        ),
        (
            lambda dataset, manifest: dataset.__setitem__(
                101,
                {
                    **dataset[101],
                    "open_time": (
                        datetime.fromisoformat(dataset[101]["open_time"].replace("Z", "+00:00")) + ONE_HOUR
                    ).isoformat().replace("+00:00", "Z"),
                    "close_time": (
                        datetime.fromisoformat(dataset[101]["open_time"].replace("Z", "+00:00")) + (ONE_HOUR * 2) - ONE_MS
                    ).isoformat().replace("+00:00", "Z"),
                },
            ),
            "not contiguous",
        ),
        (
            lambda dataset, manifest: dataset.__setitem__(101, dict(dataset[100])),
            "not contiguous",
        ),
        (lambda dataset, manifest: dataset.__setitem__(100, {**dataset[100], "confirm": 0}), "OKX dataset candles are invalid"),
        (lambda dataset, manifest: manifest.__setitem__("dataset_hash", "0" * 64), "dataset_hash mismatch"),
        (lambda dataset, manifest: manifest.__setitem__("manifest_hash", "0" * 64), "manifest_hash mismatch"),
    ],
)
def test_okx_artifact_audit_rejects_tampered_dataset_or_hashes(okx_audit_artifacts, mutator, expected):
    dataset_payload = json.loads(json.dumps(okx_audit_artifacts["dataset_payload"]))
    manifest_payload = json.loads(json.dumps(okx_audit_artifacts["manifest_payload"]))
    mutator(dataset_payload, manifest_payload)
    if expected == "dataset_hash mismatch":
        _refresh_for_dataset_hash_mismatch(dataset_payload, manifest_payload)
    elif expected == "manifest_hash mismatch":
        _refresh_for_manifest_hash_mismatch(dataset_payload, manifest_payload)
    else:
        _refresh_hashes(dataset_payload, manifest_payload)
    root = _workspace_tmp_dir(f"okx-phase19b-tamper-{expected.replace(' ', '_')}")
    dataset_file, manifest_file = _write_artifacts(root, dataset_payload, manifest_payload, suffix="tampered")
    with pytest.raises((HistoricalDataIntegrityError, HistoricalDataValidationError), match=expected):
        audit.audit_okx_historical_artifacts(dataset_file=dataset_file, manifest_file=manifest_file)


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda dataset, manifest: manifest["contract"].__setitem__("provider_id", "kucoin.public.klines"), "provider_id must be okx.public.klines"),
        (lambda dataset, manifest: manifest["contract"].__setitem__("market_type", "futures"), "market_type must be spot"),
        (lambda dataset, manifest: manifest["contract"].__setitem__("instrument", "BTCUSDT"), "instrument must be BTC-USDT"),
        (lambda dataset, manifest: manifest["contract"].__setitem__("request_params", {"instId": "BTCUSDT", "bar": "1H", "limit": 100}), "request_params diverge"),
        (lambda dataset, manifest: manifest["contract"].__setitem__("requested_end_exclusive_utc", (END_EXCLUSIVE_UTC + ONE_HOUR).isoformat().replace("+00:00", "Z")), "requested_end_exclusive_utc diverges"),
        (lambda dataset, manifest: manifest["contract"].__setitem__("historical_research_only", False), "historical_research_only must be true"),
        (lambda dataset, manifest: manifest["contract"].__setitem__("operational_evidence", True), "operational_evidence must be false"),
        (lambda dataset, manifest: manifest["contract"].__setitem__("paper_promotion_eligible", True), "paper_promotion_eligible must be false"),
        (lambda dataset, manifest: manifest.__setitem__("non_ingestion_scope_statement", "Replay and paper are authorized."), "non_ingestion_scope_statement diverges"),
    ],
)
def test_okx_artifact_audit_rejects_contract_divergence(okx_audit_artifacts, mutator, expected):
    dataset_payload = json.loads(json.dumps(okx_audit_artifacts["dataset_payload"]))
    manifest_payload = json.loads(json.dumps(okx_audit_artifacts["manifest_payload"]))
    mutator(dataset_payload, manifest_payload)
    _refresh_hashes(dataset_payload, manifest_payload)
    root = _workspace_tmp_dir(f"okx-phase19b-contract-{expected.replace(' ', '_')}")
    dataset_file, manifest_file = _write_artifacts(root, dataset_payload, manifest_payload, suffix="contract")
    with pytest.raises((HistoricalDataIntegrityError, HistoricalDataValidationError), match=expected):
        audit.audit_okx_historical_artifacts(dataset_file=dataset_file, manifest_file=manifest_file)


def test_okx_artifact_audit_rejects_manifest_claiming_more_candles_than_file(okx_audit_artifacts):
    dataset_payload = json.loads(json.dumps(okx_audit_artifacts["dataset_payload"]))
    manifest_payload = json.loads(json.dumps(okx_audit_artifacts["manifest_payload"]))
    manifest_payload["found_candle_count"] = len(dataset_payload) + 1
    _refresh_hashes(dataset_payload, manifest_payload)
    root = _workspace_tmp_dir("okx-phase19b-manifest-count")
    dataset_file, manifest_file = _write_artifacts(root, dataset_payload, manifest_payload, suffix="manifest-count")
    with pytest.raises(HistoricalDataIntegrityError, match="manifest found_candle_count does not match candles"):
        audit.audit_okx_historical_artifacts(dataset_file=dataset_file, manifest_file=manifest_file)
