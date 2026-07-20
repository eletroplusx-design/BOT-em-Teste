from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import market_data.historical as historical
import paper_operations as paper_ops
from domain import Candle
from market_data import (
    BinancePublicKlinesProvider,
    HistoricalDataConflictError,
    HistoricalDataIntegrityError,
    HistoricalDataValidationError,
    HistoricalProviderQualification,
    MarketDataHTTPError,
    MarketDataJSONError,
    MarketDataNetworkError,
    MarketDataRateLimitError,
    historical_content_hash,
    load_historical_dataset_file,
    prepare_historical_dataset,
    status_historical_dataset,
    verify_historical_dataset_file,
)
from market_data.historical_manifest import historical_manifest_hash


BASE_START = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)


class SequenceProvider:
    provider_identity = "binance.public.klines"
    base_url = BinancePublicKlinesProvider.base_url
    trusted_market_data_provider = True

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def historical_qualification(self, symbol="BTCUSDT", interval="1h"):
        return HistoricalProviderQualification.binance_public_spot(symbol=symbol, interval=interval)

    def fetch_klines(self, symbol, interval, limit=500, *, start_time=None, end_time=None):
        self.calls.append(
            {
                "symbol": symbol,
                "interval": interval,
                "limit": limit,
                "start_time": start_time,
                "end_time": end_time,
            }
        )
        if not self.responses:
            raise AssertionError("unexpected extra historical fetch")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _kline_row(open_time: datetime, *, close_delta: timedelta = ONE_HOUR - ONE_MS, base: int = 100):
    close_time = open_time + close_delta
    return [
        int(open_time.timestamp() * 1000),
        str(base),
        str(base + 5),
        str(base - 2),
        str(base + 1),
        str(1000 + base),
        int(close_time.timestamp() * 1000),
        0,
        0,
        0,
        0,
        0,
    ]


def _page(start: datetime, count: int, *, close_delta: timedelta = ONE_HOUR - ONE_MS, base: int = 100):
    return [_kline_row(start + idx * ONE_HOUR, close_delta=close_delta, base=base + idx) for idx in range(count)]


def _request_end(start: datetime, count: int) -> datetime:
    return start + (count - 1) * ONE_HOUR + ONE_HOUR - ONE_MS


def _build_output(tmp_path: Path, name: str = "historical-dataset.json") -> Path:
    return tmp_path / name


def _recompute_dataset_hashes(payload: dict) -> None:
    candles = [Candle.from_dict(item) for item in payload["candles"]]
    payload["manifest"]["candle_count"] = len(candles)
    payload["manifest"]["content_hash"] = historical_content_hash(candles)
    payload["manifest"]["dataset_id"] = payload["manifest"]["content_hash"]
    payload["manifest"]["manifest_hash"] = historical_manifest_hash(payload["manifest"])


def test_historical_prepare_one_page_round_trip_and_verify(tmp_path):
    output = _build_output(tmp_path)
    page = _page(BASE_START, 1000)
    provider = SequenceProvider([page])
    frozen_now = _request_end(BASE_START, 1000) + timedelta(days=1)
    call_count = {"count": 0}

    def _frozen_now():
        call_count["count"] += 1
        return frozen_now

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(historical, "_utcnow", _frozen_now)

    try:
        result = prepare_historical_dataset(
            output_file=output,
            provider=provider,
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=_request_end(BASE_START, 1000),
            page_size=1000,
            max_pages=4,
        )

        assert result["reused"] is False
        assert output.exists()
        assert result["candle_count"] == 1000
        assert result["page_count"] == 1
        assert result["page_size"] == 1000
        assert provider.calls[0]["start_time"] == int(BASE_START.timestamp() * 1000)

        dataset = load_historical_dataset_file(output)
        assert len(dataset.candles) == 1000
        assert dataset.manifest.content_hash == historical_content_hash(dataset.candles)
        assert dataset.manifest.created_at_utc == frozen_now
        assert call_count["count"] == 1
        snapshots = dataset.replay_snapshots()
        assert len(snapshots) == 1000
        assert snapshots[0].symbol == "BTCUSDT"
        assert snapshots[-1].timestamp == dataset.candles[-1].close_time

        status = status_historical_dataset(input_file=output)
        assert status["exists"] is True
        assert status["manifest_hash"] == dataset.manifest.manifest_hash

        verify = verify_historical_dataset_file(input_file=output)
        assert verify["verified"] is True
        assert verify["content_hash"] == dataset.manifest.content_hash
    finally:
        monkeypatch.undo()


def test_historical_prepare_1001_records_two_pages_and_advances_deterministically(tmp_path):
    output = _build_output(tmp_path)
    first_page = _page(BASE_START, 1000)
    second_start = BASE_START + 1000 * ONE_HOUR
    second_page = _page(second_start, 1, base=2000)
    provider = SequenceProvider([first_page, second_page])

    result = prepare_historical_dataset(
        output_file=output,
        provider=provider,
        symbol="BTCUSDT",
        interval="1h",
        requested_start_utc=BASE_START,
        requested_end_utc=_request_end(BASE_START, 1001),
        page_size=1000,
        max_pages=4,
    )

    assert result["page_count"] == 2
    assert result["candle_count"] == 1001
    assert len(provider.calls) == 2
    assert provider.calls[0]["start_time"] == int(BASE_START.timestamp() * 1000)
    assert provider.calls[1]["start_time"] == int((BASE_START + 1000 * ONE_HOUR).timestamp() * 1000)


def test_historical_prepare_2501_uses_three_pages_and_partial_last_page(tmp_path):
    output = _build_output(tmp_path)
    pages = [
        _page(BASE_START, 1000),
        _page(BASE_START + 1000 * ONE_HOUR, 1000, base=2000),
        _page(BASE_START + 2000 * ONE_HOUR, 501, base=3000),
    ]
    provider = SequenceProvider(pages)

    result = prepare_historical_dataset(
        output_file=output,
        provider=provider,
        symbol="BTCUSDT",
        interval="1h",
        requested_start_utc=BASE_START,
        requested_end_utc=_request_end(BASE_START, 2501),
        page_size=1000,
        max_pages=6,
    )

    assert result["page_count"] == 3
    assert result["candle_count"] == 2501
    assert len(provider.calls) == 3
    assert output.exists()


def test_historical_prepare_rejects_duplicate_page_no_progress(tmp_path):
    output = _build_output(tmp_path)
    page = _page(BASE_START, 1000)
    provider = SequenceProvider([page, page])

    with pytest.raises(HistoricalDataValidationError, match="Duplicate candle detected between pages|no progress"):
        prepare_historical_dataset(
            output_file=output,
            provider=provider,
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=_request_end(BASE_START, 1001),
            page_size=1000,
            max_pages=4,
        )


def test_historical_prepare_rejects_gap_between_pages(tmp_path):
    output = _build_output(tmp_path)
    first_page = _page(BASE_START, 1000)
    gap_page = _page(BASE_START + (1000 + 2) * ONE_HOUR, 1, base=4000)
    provider = SequenceProvider([first_page, gap_page])

    with pytest.raises(HistoricalDataValidationError, match="Gap detected between pages"):
        prepare_historical_dataset(
            output_file=output,
            provider=provider,
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=_request_end(BASE_START, 1003),
            page_size=1000,
            max_pages=4,
        )


def test_historical_prepare_rejects_open_candle(tmp_path, monkeypatch):
    output = _build_output(tmp_path, "open.json")
    open_only = [_kline_row(BASE_START, close_delta=ONE_HOUR - ONE_MS)]
    provider = SequenceProvider([open_only])
    frozen_now = BASE_START + timedelta(minutes=30)
    monkeypatch.setattr(historical, "_utcnow", lambda: frozen_now)
    with pytest.raises(HistoricalDataValidationError, match="No closed candles available"):
        prepare_historical_dataset(
            output_file=output,
            provider=provider,
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=frozen_now,
            page_size=1000,
            max_pages=2,
        )


def test_historical_prepare_rejects_future_end_before_provider(tmp_path, monkeypatch):
    output = _build_output(tmp_path, "future-end.json")
    provider = SequenceProvider([_page(BASE_START, 1)])
    frozen_now = _request_end(BASE_START, 1)
    call_count = {"count": 0}

    def _frozen_now():
        call_count["count"] += 1
        return frozen_now

    monkeypatch.setattr(historical, "_utcnow", _frozen_now)

    with pytest.raises(HistoricalDataValidationError, match="requested_end_utc must not be in the future"):
        historical.fetch_historical_public_klines(
            provider=provider,
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=frozen_now + ONE_HOUR,
            page_size=1000,
            max_pages=2,
        )
    assert call_count["count"] == 1
    assert provider.calls == []


def test_historical_prepare_rejects_future_candle_from_provider(tmp_path, monkeypatch):
    output = _build_output(tmp_path, "future-candle.json")
    future_open = _request_end(BASE_START, 1) + ONE_MS
    provider = SequenceProvider([[ _kline_row(future_open, base=5000) ]])
    frozen_now = _request_end(BASE_START, 1)
    monkeypatch.setattr(historical, "_utcnow", lambda: frozen_now)

    with pytest.raises(HistoricalDataValidationError, match="Future candle detected"):
        prepare_historical_dataset(
            output_file=output,
            provider=provider,
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=frozen_now,
            page_size=1000,
            max_pages=2,
        )
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    "start_offset,label",
    [(-ONE_HOUR, "early"), (ONE_HOUR, "late")],
)
def test_historical_prepare_rejects_misaligned_start(tmp_path, start_offset, label):
    output = _build_output(tmp_path, f"start-{label}.json")
    page_start = BASE_START + start_offset
    provider = SequenceProvider([_page(page_start, 1, base=1500)])

    with pytest.raises(HistoricalDataValidationError, match="Historical page must start at requested_start_utc"):
        prepare_historical_dataset(
            output_file=output,
            provider=provider,
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=_request_end(BASE_START, 2),
            page_size=1000,
            max_pages=2,
        )


def test_historical_prepare_rejects_missing_last_candle(tmp_path):
    output = _build_output(tmp_path, "missing-last.json")
    provider = SequenceProvider([_page(BASE_START, 1), []])

    with pytest.raises(HistoricalDataValidationError, match="Empty or malformed response payload"):
        prepare_historical_dataset(
            output_file=output,
            provider=provider,
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=_request_end(BASE_START, 2),
            page_size=1000,
            max_pages=2,
        )
    assert len(provider.calls) == 2


def test_historical_prepare_accepts_single_closed_page(tmp_path):
    output = _build_output(tmp_path, "single.json")
    provider = SequenceProvider([[_kline_row(BASE_START, base=100)]])
    result = prepare_historical_dataset(
        output_file=output,
        provider=provider,
        symbol="BTCUSDT",
        interval="1h",
        requested_start_utc=BASE_START,
        requested_end_utc=_request_end(BASE_START, 1),
        page_size=1000,
        max_pages=2,
    )
    assert result["candle_count"] == 1


def test_historical_prepare_rejects_invalid_rows(tmp_path):
    output = _build_output(tmp_path, "invalid.json")
    provider = SequenceProvider([[["bad"]]])
    with pytest.raises(HistoricalDataValidationError, match="Kline payload is partial"):
        prepare_historical_dataset(
            output_file=output,
            provider=provider,
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=_request_end(BASE_START, 1),
            page_size=1000,
            max_pages=2,
        )


@pytest.mark.parametrize(
    "payload,exc_type",
    [
        ([_kline_row(BASE_START, close_delta=timedelta(hours=2), base=100)], HistoricalDataValidationError),
        ([[
            "invalid",
            "100",
            "105",
            "98",
            "101",
            "1000",
            "invalid",
            0,
            0,
            0,
            0,
            0,
        ]], HistoricalDataValidationError),
        ([[
            int(BASE_START.timestamp() * 1000),
            "100",
            "90",
            "95",
            "101",
            "1000",
            int((_request_end(BASE_START, 1)).timestamp() * 1000),
            0,
            0,
            0,
            0,
            0,
        ]], HistoricalDataValidationError),
        ([[
            int(BASE_START.timestamp() * 1000),
            "NaN",
            "105",
            "98",
            "101",
            "1000",
            int((_request_end(BASE_START, 1)).timestamp() * 1000),
            0,
            0,
            0,
            0,
            0,
        ]], HistoricalDataValidationError),
    ],
)
def test_historical_prepare_rejects_bad_payloads(payload, exc_type, tmp_path):
    output = _build_output(tmp_path, "bad.json")
    provider = SequenceProvider([payload])
    if payload[0][0] == int(BASE_START.timestamp() * 1000) and payload[0][1] == "100" and payload[0][2] == "90":
        with pytest.raises(exc_type, match="high must be greater than or equal to low|open must be within candle range|close must be within candle range"):
            prepare_historical_dataset(
                output_file=output,
                provider=provider,
                symbol="BTCUSDT",
                interval="1h",
                requested_start_utc=BASE_START,
                requested_end_utc=_request_end(BASE_START, 1),
                page_size=1000,
                max_pages=2,
            )
        return
    with pytest.raises(exc_type):
        prepare_historical_dataset(
            output_file=output,
            provider=provider,
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=_request_end(BASE_START, 1),
            page_size=1000,
            max_pages=2,
        )


def test_historical_prepare_preserves_io_failure_no_partial_file(tmp_path, monkeypatch):
    output = _build_output(tmp_path, "atomic.json")
    provider = SequenceProvider([_page(BASE_START, 1)])
    from market_data import historical_store

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(historical_store.os, "replace", boom)
    with pytest.raises(HistoricalDataValidationError, match="Failed to write historical dataset atomically"):
        prepare_historical_dataset(
            output_file=output,
            provider=provider,
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=_request_end(BASE_START, 1),
            page_size=1000,
            max_pages=2,
        )
    assert not output.exists()
    assert not any(output.parent.glob(f".{output.name}.*.tmp"))


def test_historical_prepare_is_write_once_idempotent_and_rejects_divergence(tmp_path):
    output = _build_output(tmp_path, "idempotent.json")
    provider = SequenceProvider([_page(BASE_START, 2)])
    first = prepare_historical_dataset(
        output_file=output,
        provider=provider,
        symbol="BTCUSDT",
        interval="1h",
        requested_start_utc=BASE_START,
        requested_end_utc=_request_end(BASE_START, 2),
        page_size=1000,
        max_pages=2,
    )
    assert first["reused"] is False
    second = prepare_historical_dataset(
        output_file=output,
        provider=provider,
        symbol="BTCUSDT",
        interval="1h",
        requested_start_utc=BASE_START,
        requested_end_utc=_request_end(BASE_START, 2),
        page_size=1000,
        max_pages=2,
    )
    assert second["reused"] is True
    assert len(provider.calls) == 1

    with pytest.raises(HistoricalDataValidationError, match="binance public spot provider only supports BTCUSDT 1h."):
        prepare_historical_dataset(
            output_file=output,
            provider=provider,
            symbol="ETHUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=_request_end(BASE_START, 2),
            page_size=1000,
            max_pages=2,
        )


def test_historical_dataset_tamper_detection_and_replay_without_network(tmp_path):
    output = _build_output(tmp_path, "tamper.json")
    provider = SequenceProvider([_page(BASE_START, 3)])
    prepare_historical_dataset(
        output_file=output,
        provider=provider,
        symbol="BTCUSDT",
        interval="1h",
        requested_start_utc=BASE_START,
        requested_end_utc=_request_end(BASE_START, 3),
        page_size=1000,
        max_pages=2,
    )
    loaded = load_historical_dataset_file(output)
    assert len(loaded.replay_snapshots()) == 3

    payload = output.read_text(encoding="utf-8")
    assert loaded.manifest.manifest_hash in payload

    tampered = load_historical_dataset_file(output).as_dict()
    tampered["candles"][0]["close"] = "999999"
    output.write_text(json.dumps(tampered, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    with pytest.raises(HistoricalDataIntegrityError):
        load_historical_dataset_file(output)


def test_historical_dataset_manifest_tamper_detection(tmp_path):
    output = _build_output(tmp_path, "manifest.json")
    provider = SequenceProvider([_page(BASE_START, 2)])
    prepare_historical_dataset(
        output_file=output,
        provider=provider,
        symbol="BTCUSDT",
        interval="1h",
        requested_start_utc=BASE_START,
        requested_end_utc=_request_end(BASE_START, 2),
        page_size=1000,
        max_pages=2,
    )
    tampered = load_historical_dataset_file(output).as_dict()
    tampered["manifest"]["page_count"] = 99
    output.write_text(json.dumps(tampered, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    with pytest.raises(HistoricalDataIntegrityError):
        load_historical_dataset_file(output)


def test_historical_prepare_cli_and_status_verify(tmp_path, monkeypatch):
    output = _build_output(tmp_path, "cli.json")
    provider = SequenceProvider([_page(BASE_START, 2)])
    monkeypatch.setattr(paper_ops.trusted_market_data_service, "provider", provider)

    exit_code = paper_ops.main(
        [
            "history",
            "prepare",
            "--symbol",
            "BTCUSDT",
            "--interval",
            "1h",
            "--start-utc",
            BASE_START.isoformat().replace("+00:00", "Z"),
            "--end-utc",
            _request_end(BASE_START, 2).isoformat().replace("+00:00", "Z"),
            "--output",
            str(output),
        ]
    )
    assert exit_code == 0
    assert output.exists()

    status_exit = paper_ops.main(["history", "status", "--input", str(output)])
    verify_exit = paper_ops.main(["history", "verify", "--input", str(output)])
    assert status_exit == 0
    assert verify_exit == 0


def test_historical_prepare_honors_max_pages_and_provider_errors(tmp_path):
    output = _build_output(tmp_path, "errors.json")
    provider = SequenceProvider([_page(BASE_START, 1), _page(BASE_START + ONE_HOUR, 1), _page(BASE_START + 2 * ONE_HOUR, 1)])

    with pytest.raises(HistoricalDataValidationError, match="Maximum historical page count exceeded"):
        prepare_historical_dataset(
            output_file=output,
            provider=provider,
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=_request_end(BASE_START, 3),
            page_size=1,
            max_pages=2,
        )

    for error in (MarketDataNetworkError("boom"), MarketDataRateLimitError("rate"), MarketDataHTTPError("http"), MarketDataJSONError("json")):
        output_error = _build_output(tmp_path, f"{error.__class__.__name__}.json")
        provider_error = SequenceProvider([_page(BASE_START, 1), error])
        with pytest.raises(error.__class__):
            prepare_historical_dataset(
                output_file=output_error,
                provider=provider_error,
                symbol="BTCUSDT",
                interval="1h",
                requested_start_utc=BASE_START,
                requested_end_utc=_request_end(BASE_START, 2),
                page_size=1,
                max_pages=2,
            )


@pytest.mark.parametrize(
    "invalid_max_pages",
    [False, True, 0, -1, 1001, 1.5, "3"],
)
def test_historical_prepare_rejects_invalid_max_pages_strict(tmp_path, invalid_max_pages):
    output = _build_output(tmp_path, f"max-pages-{invalid_max_pages}.json")
    provider = SequenceProvider([_page(BASE_START, 1)])

    with pytest.raises(HistoricalDataValidationError):
        prepare_historical_dataset(
            output_file=output,
            provider=provider,
            symbol="BTCUSDT",
            interval="1h",
            requested_start_utc=BASE_START,
            requested_end_utc=_request_end(BASE_START, 1),
            page_size=1000,
            max_pages=invalid_max_pages,
        )
    assert provider.calls == []


def test_historical_prepare_reuses_single_default_provider_instance(tmp_path, monkeypatch):
    output = _build_output(tmp_path, "default-provider.json")

    class CountingProvider:
        provider_identity = "binance.public.klines"
        base_url = BinancePublicKlinesProvider.base_url
        trusted_market_data_provider = True
        instances = 0

        def __init__(self):
            type(self).instances += 1
            self.calls = []

        def historical_qualification(self, symbol="BTCUSDT", interval="1h"):
            return HistoricalProviderQualification.binance_public_spot(symbol=symbol, interval=interval)

        def fetch_klines(self, symbol, interval, limit=500, *, start_time=None, end_time=None):
            self.calls.append(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "limit": limit,
                    "start_time": start_time,
                    "end_time": end_time,
                }
            )
            return [_kline_row(BASE_START, base=100)]

    monkeypatch.setattr(historical, "BinancePublicKlinesProvider", CountingProvider)

    result = prepare_historical_dataset(
        output_file=output,
        provider=None,
        symbol="BTCUSDT",
        interval="1h",
        requested_start_utc=BASE_START,
        requested_end_utc=_request_end(BASE_START, 1),
        page_size=1000,
        max_pages=2,
    )

    assert result["candle_count"] == 1
    assert CountingProvider.instances == 1


def test_historical_dataset_loader_rejects_recomputed_tampering(tmp_path):
    output = _build_output(tmp_path, "tamper-recomputed.json")
    provider = SequenceProvider([_page(BASE_START, 3)])
    prepare_historical_dataset(
        output_file=output,
        provider=provider,
        symbol="BTCUSDT",
        interval="1h",
        requested_start_utc=BASE_START,
        requested_end_utc=_request_end(BASE_START, 3),
        page_size=1000,
        max_pages=2,
    )

    cases = []

    gap_payload = load_historical_dataset_file(output).as_dict()
    del gap_payload["candles"][1]
    _recompute_dataset_hashes(gap_payload)
    cases.append((gap_payload, "Historical dataset candles are invalid."))

    symbol_payload = load_historical_dataset_file(output).as_dict()
    symbol_payload["candles"][0]["symbol"] = "ETHUSDT"
    _recompute_dataset_hashes(symbol_payload)
    cases.append((symbol_payload, "Historical dataset candle symbol mismatch."))

    duration_payload = load_historical_dataset_file(output).as_dict()
    duration_payload["candles"][0]["close_time"] = (
        BASE_START + timedelta(minutes=30) - ONE_MS
    ).isoformat().replace("+00:00", "Z")
    _recompute_dataset_hashes(duration_payload)
    cases.append((duration_payload, "Historical dataset candles are invalid."))

    permissive_payload = load_historical_dataset_file(output).as_dict()
    permissive_payload["manifest"]["closed_candles_only"] = False
    _recompute_dataset_hashes(permissive_payload)
    cases.append((permissive_payload, "closed_candles_only must be true."))

    for payload, match in cases:
        rewritten = output.parent / "tampered.json"
        rewritten.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        with pytest.raises(HistoricalDataIntegrityError, match=match):
            load_historical_dataset_file(rewritten)
        rewritten.unlink()


def test_history_prepare_help_omits_provider_option(capsys):
    with pytest.raises(SystemExit):
        paper_ops.main(["history", "prepare", "--help"])
    out = capsys.readouterr().out
    assert "--provider" not in out
