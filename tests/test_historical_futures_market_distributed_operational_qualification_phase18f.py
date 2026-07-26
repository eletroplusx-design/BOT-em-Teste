from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import urllib.request

import pytest

from historical_futures_market_distributed_operational_qualification import (
    HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_BAR_ALIASES,
    HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT,
    HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES,
    HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT,
    HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT,
    HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_RISK_NOTES,
    HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_STATUS,
    HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_YEARS,
    HistoricalFuturesMarketDistributedOperationalQualificationConflictError,
    HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError,
    HistoricalFuturesMarketDistributedOperationalQualificationPromotionError,
    HistoricalFuturesMarketDistributedOperationalQualificationReport,
    HistoricalFuturesMarketDistributedOperationalQualificationValidationError,
    build_historical_futures_market_distributed_operational_qualification_report,
    load_historical_futures_market_distributed_operational_qualification_report,
    reject_historical_futures_market_distributed_operational_qualification_promotion,
    run_historical_futures_market_distributed_operational_qualification,
    save_historical_futures_market_distributed_operational_qualification_report,
    status_historical_futures_market_distributed_operational_qualification_report,
    verify_historical_futures_market_distributed_operational_qualification_report,
)


EXPECTED_SAMPLE_ORDER = tuple(
    (interval_name, year)
    for interval_name in HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES
    for year in HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_YEARS
)
EXPECTED_INTERVAL_SPECS = {
    "15m": {
        "bar_alias": "15m",
        "span": timedelta(days=2),
        "window_candle_count": 192,
        "last_candle_open_utc": "23:45:00",
    },
    "1h": {
        "bar_alias": "1H",
        "span": timedelta(days=5),
        "window_candle_count": 120,
        "last_candle_open_utc": "23:00:00",
    },
    "4h": {
        "bar_alias": "4H",
        "span": timedelta(days=18),
        "window_candle_count": 108,
        "last_candle_open_utc": "20:00:00",
    },
}


@pytest.fixture(scope="module")
def distributed_operational_qualification_artifacts():
    return build_historical_futures_market_distributed_operational_qualification_report()


def _payload(report: HistoricalFuturesMarketDistributedOperationalQualificationReport) -> dict:
    return report.as_dict()


def _expected_window_start(year: int) -> str:
    return f"{year:04d}-01-01T00:00:00+00:00"


def _expected_window_end(year: int, interval_name: str) -> str:
    spec = EXPECTED_INTERVAL_SPECS[interval_name]
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = start + spec["span"]
    return end.isoformat()
def _expected_last_candle_iso(year: int, interval_name: str) -> str:
    if interval_name == "15m":
        return f"{year:04d}-01-02T23:45:00+00:00"
    if interval_name == "1h":
        return f"{year:04d}-01-05T23:00:00+00:00"
    return f"{year:04d}-01-18T20:00:00+00:00"


def _expected_sample_count(interval_name: str) -> int:
    return EXPECTED_INTERVAL_SPECS[interval_name]["window_candle_count"]


def test_distributed_operational_qualification_round_trip_and_hash_stability(
    distributed_operational_qualification_artifacts,
):
    report = distributed_operational_qualification_artifacts
    rebuilt = type(report).from_dict(report.as_dict())

    assert report == rebuilt
    assert report.report_hash == rebuilt.report_hash
    assert report.as_dict() == rebuilt.as_dict()
    assert report.protocol.protocol_hash == rebuilt.protocol.protocol_hash
    assert report.summary.summary_hash == rebuilt.summary.summary_hash
    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.protocol.historical_research_only is True
    assert report.protocol.operational_evidence is False
    assert report.protocol.paper_promotion_eligible is False
    assert report.summary.distributed_operational_evidence_status == HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_STATUS


def test_distributed_operational_qualification_is_deterministic(distributed_operational_qualification_artifacts):
    report_a = distributed_operational_qualification_artifacts
    report_b = run_historical_futures_market_distributed_operational_qualification()

    assert report_a.report_hash == report_b.report_hash
    assert report_a.protocol == report_b.protocol
    assert report_a.summary == report_b.summary
    assert report_a.distributed_samples == report_b.distributed_samples


def test_distributed_operational_qualification_covers_fifteen_distributed_samples(
    distributed_operational_qualification_artifacts,
):
    report = distributed_operational_qualification_artifacts

    assert tuple((sample.interval_name, sample.year) for sample in report.distributed_samples) == EXPECTED_SAMPLE_ORDER
    assert tuple(sample.bar_alias for sample in report.distributed_samples) == (
        "15m",
        "15m",
        "15m",
        "15m",
        "15m",
        "1H",
        "1H",
        "1H",
        "1H",
        "1H",
        "4H",
        "4H",
        "4H",
        "4H",
        "4H",
    )
    assert report.protocol.coverage_start_utc.isoformat() == "2021-01-01T00:00:00+00:00"
    assert report.protocol.coverage_end_utc.isoformat() == "2025-01-18T20:00:00+00:00"
    assert report.protocol.years == HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_YEARS
    assert report.protocol.interval_names == HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES
    assert report.protocol.bar_aliases == HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_BAR_ALIASES
    assert report.protocol.sample_count == 15
    assert report.protocol.year_count == 5
    assert report.protocol.interval_count == 3
    assert report.protocol.page_count == 30
    assert report.protocol.fetched_count == 3000
    assert report.protocol.window_candle_count == 2100
    assert report.protocol.duplicate_count == 0
    assert report.protocol.gap_count == 0
    assert report.protocol.distributed_samples_only is True
    assert report.protocol.continuous_history_coverage_claimed is False
    assert report.summary.sample_count == 15
    assert report.summary.year_count == 5
    assert report.summary.interval_count == 3
    assert report.summary.page_count == 30
    assert report.summary.fetched_count == 3000
    assert report.summary.window_candle_count == 2100
    assert report.summary.duplicate_count == 0
    assert report.summary.gap_count == 0
    assert report.summary.all_confirm_closed is True
    assert report.summary.incomplete_candle_confirm_observed is False
    assert report.summary.distributed_samples_only is True
    assert report.summary.continuous_history_coverage_claimed is False
    assert report.summary.coverage_scope_statement == HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT
    assert report.summary.non_ingestion_scope_statement == HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT
    assert report.summary.pagination_behavior_statement == HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT
    assert report.summary.risk_notes == HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_RISK_NOTES


@pytest.mark.parametrize("interval_name", HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES)
def test_distributed_operational_qualification_records_interval_evidence(
    distributed_operational_qualification_artifacts,
    interval_name,
):
    report = distributed_operational_qualification_artifacts
    samples = [sample for sample in report.distributed_samples if sample.interval_name == interval_name]
    spec = EXPECTED_INTERVAL_SPECS[interval_name]

    assert len(samples) == 5
    for sample in samples:
        assert sample.bar_alias == spec["bar_alias"]
        assert sample.page_count == 2
        assert sample.fetched_count == 200
        assert sample.window_candle_count == spec["window_candle_count"]
        assert sample.confirm_value == 1
        assert sample.all_confirm_closed is True
        assert sample.incomplete_candle_confirm_observed is False
        assert sample.duplicate_count == 0
        assert sample.gap_count == 0
        assert sample.second_page_contains_pre_window_candles is True
        assert sample.second_page_filtered_in_memory is True
        assert sample.before_returns_newer_candles is True
        assert sample.after_observed_as_pagination_mechanism is True
        assert sample.utc_time_semantics == "utc"
        assert sample.pagination_limit == 100
        assert sample.window_start_utc.isoformat() == _expected_window_start(sample.year)
        assert sample.window_end_utc.isoformat() == _expected_window_end(sample.year, interval_name)
        assert sample.first_candle_open_utc.isoformat() == _expected_window_start(sample.year)
        assert sample.last_candle_open_utc.isoformat() == _expected_last_candle_iso(sample.year, interval_name)
        assert sample.provider_qualification.provider_id == "okx.public.klines"
        assert sample.provider_qualification.provider_version == "v1"
        assert sample.provider_qualification.market_type == "spot"
        assert sample.provider_qualification.exchange == "okx"
        assert sample.provider_qualification.symbol == "BTCUSDT"
        assert sample.provider_qualification.interval == spec["bar_alias"]
        assert sample.provider_qualification.time_semantics == "utc"
        assert sample.provider_qualification.access_type == "public_no_auth"
        assert sample.provider_qualification.data_contract_version == 2
        assert sample.provider_qualification.external_symbol == "BTC-USDT"
        assert sample.provider_qualification.endpoint_url == "https://www.okx.com/api/v5/market/history-candles"
        assert sample.provider_qualification.documentation_url == "https://www.okx.com/docs-v5/en/"
        assert sample.provider_qualification.pagination_limit == 100
        assert sample.provider_qualification.close_time_rule == "confirm=0 means incomplete; confirm=1 means completed"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.__setitem__("historical_research_only", False),
        lambda payload: payload.__setitem__("operational_evidence", True),
        lambda payload: payload.__setitem__("paper_promotion_eligible", True),
        lambda payload: payload.__setitem__("manifest_hash", "0" * 64),
        lambda payload: payload["protocol"].__setitem__("canonical_source_provider_id", "okx.public.klines"),
        lambda payload: payload["protocol"].__setitem__("canonical_source_name", "OKX spot"),
        lambda payload: payload["protocol"].__setitem__("candidate_source_name", "KuCoin spot"),
        lambda payload: payload["protocol"].__setitem__("candidate_provider_id", "kucoin.public.klines"),
        lambda payload: payload["protocol"].__setitem__("candidate_market_type", "futures"),
        lambda payload: payload["protocol"].__setitem__("candidate_symbol", "ETHUSDT"),
        lambda payload: payload["protocol"].__setitem__("candidate_external_symbol", "ETH-USDT"),
        lambda payload: payload["protocol"].__setitem__("candidate_provider_version", "v2"),
        lambda payload: payload["protocol"].__setitem__("candidate_provider_exchange", "binance"),
        lambda payload: payload["protocol"].__setitem__("candidate_endpoint_url", "https://example.invalid"),
        lambda payload: payload["protocol"].__setitem__("candidate_documentation_url", "https://example.invalid"),
        lambda payload: payload["protocol"].__setitem__("candidate_endpoint_path", "/api/v5/market/candles"),
        lambda payload: payload["protocol"].__setitem__("distributed_operational_evidence_status", "dataset_ready"),
        lambda payload: payload["protocol"].__setitem__("coverage_scope_statement", "coverage 2021-2025"),
        lambda payload: payload["protocol"].__setitem__("non_ingestion_scope_statement", "tampered"),
        lambda payload: payload["protocol"].__setitem__("pagination_behavior_statement", "tampered"),
        lambda payload: payload["protocol"]["risk_notes"].__setitem__(0, "tampered"),
        lambda payload: payload["protocol"]["years"].__setitem__(0, 2020),
        lambda payload: payload["protocol"]["interval_names"].__setitem__(0, "30m"),
        lambda payload: payload["protocol"]["bar_aliases"].__setitem__(1, "1h"),
        lambda payload: payload["protocol"]["sample_hashes"].__setitem__(0, "0" * 64),
        lambda payload: payload["protocol"].__setitem__("sample_count", 14),
        lambda payload: payload["protocol"].__setitem__("year_count", 4),
        lambda payload: payload["protocol"].__setitem__("interval_count", 2),
        lambda payload: payload["protocol"].__setitem__("page_count", 29),
        lambda payload: payload["protocol"].__setitem__("fetched_count", 2999),
        lambda payload: payload["protocol"].__setitem__("window_candle_count", 2099),
        lambda payload: payload["protocol"].__setitem__("duplicate_count", 1),
        lambda payload: payload["protocol"].__setitem__("gap_count", 1),
        lambda payload: payload["protocol"].__setitem__("distributed_samples_only", False),
        lambda payload: payload["protocol"].__setitem__("continuous_history_coverage_claimed", True),
        lambda payload: payload["summary"].__setitem__("sample_count", 14),
        lambda payload: payload["summary"].__setitem__("year_count", 4),
        lambda payload: payload["summary"].__setitem__("interval_count", 2),
        lambda payload: payload["summary"].__setitem__("page_count", 29),
        lambda payload: payload["summary"].__setitem__("fetched_count", 2999),
        lambda payload: payload["summary"].__setitem__("window_candle_count", 2099),
        lambda payload: payload["summary"].__setitem__("duplicate_count", 1),
        lambda payload: payload["summary"].__setitem__("gap_count", 1),
        lambda payload: payload["summary"].__setitem__("all_confirm_closed", False),
        lambda payload: payload["summary"].__setitem__("incomplete_candle_confirm_observed", True),
        lambda payload: payload["summary"].__setitem__("distributed_samples_only", False),
        lambda payload: payload["summary"].__setitem__("continuous_history_coverage_claimed", True),
        lambda payload: payload["summary"].__setitem__("distributed_operational_evidence_status", "dataset_ready"),
        lambda payload: payload["summary"].__setitem__("coverage_scope_statement", "tampered"),
        lambda payload: payload["summary"].__setitem__("non_ingestion_scope_statement", "tampered"),
        lambda payload: payload["summary"].__setitem__("pagination_behavior_statement", "tampered"),
        lambda payload: payload["summary"].__setitem__("risk_notes", ["tampered"]),
        lambda payload: payload["distributed_samples"][0].__setitem__("year", 2020),
        lambda payload: payload["distributed_samples"][0].__setitem__("interval_name", "30m"),
        lambda payload: payload["distributed_samples"][0].__setitem__("bar_alias", "1h"),
        lambda payload: payload["distributed_samples"][0].__setitem__("window_start_utc", "2021-01-02T00:00:00+00:00"),
        lambda payload: payload["distributed_samples"][0].__setitem__("window_end_utc", "2021-01-03T00:15:00+00:00"),
        lambda payload: payload["distributed_samples"][0].__setitem__("page_count", 1),
        lambda payload: payload["distributed_samples"][0].__setitem__("fetched_count", 199),
        lambda payload: payload["distributed_samples"][0].__setitem__("window_candle_count", 191),
        lambda payload: payload["distributed_samples"][0].__setitem__("first_candle_open_utc", "2021-01-01T00:15:00+00:00"),
        lambda payload: payload["distributed_samples"][0].__setitem__("last_candle_open_utc", "2021-01-02T23:30:00+00:00"),
        lambda payload: payload["distributed_samples"][0].__setitem__("confirm_value", 0),
        lambda payload: payload["distributed_samples"][0].__setitem__("all_confirm_closed", False),
        lambda payload: payload["distributed_samples"][0].__setitem__("incomplete_candle_confirm_observed", True),
        lambda payload: payload["distributed_samples"][0].__setitem__("duplicate_count", 1),
        lambda payload: payload["distributed_samples"][0].__setitem__("gap_count", 1),
        lambda payload: payload["distributed_samples"][0].__setitem__("second_page_contains_pre_window_candles", False),
        lambda payload: payload["distributed_samples"][0].__setitem__("second_page_filtered_in_memory", False),
        lambda payload: payload["distributed_samples"][0].__setitem__("before_returns_newer_candles", False),
        lambda payload: payload["distributed_samples"][0].__setitem__("after_observed_as_pagination_mechanism", False),
        lambda payload: payload["distributed_samples"][0].__setitem__("utc_time_semantics", "local"),
        lambda payload: payload["distributed_samples"][0].__setitem__("pagination_limit", 50),
        lambda payload: payload["distributed_samples"][0]["provider_qualification"].__setitem__("provider_id", "kucoin.public.klines"),
        lambda payload: payload["distributed_samples"][0]["provider_qualification"].__setitem__("provider_version", "v2"),
        lambda payload: payload["distributed_samples"][0]["provider_qualification"].__setitem__("market_type", "futures"),
        lambda payload: payload["distributed_samples"][0]["provider_qualification"].__setitem__("exchange", "binance"),
        lambda payload: payload["distributed_samples"][0]["provider_qualification"].__setitem__("symbol", "ETHUSDT"),
        lambda payload: payload["distributed_samples"][0]["provider_qualification"].__setitem__("interval", "1h"),
        lambda payload: payload["distributed_samples"][0]["provider_qualification"].__setitem__("external_symbol", "ETH-USDT"),
        lambda payload: payload["distributed_samples"][0]["provider_qualification"].__setitem__("endpoint_url", "https://example.invalid"),
        lambda payload: payload["distributed_samples"][0]["provider_qualification"].__setitem__("documentation_url", "https://example.invalid"),
        lambda payload: payload["distributed_samples"][0]["provider_qualification"].__setitem__("pagination_limit", 50),
        lambda payload: payload["distributed_samples"][0]["provider_qualification"].__setitem__("close_time_rule", "tampered"),
        lambda payload: payload["distributed_samples"][0]["sample_hash"].__setitem__(slice(None), "0" * 64) if False else payload["distributed_samples"][0].__setitem__("sample_hash", "0" * 64),
        lambda payload: payload["distributed_samples"].__setitem__(0, deepcopy(payload["distributed_samples"][1])),
        lambda payload: payload["distributed_samples"].__setitem__(1, deepcopy(payload["distributed_samples"][0])),
        lambda payload: payload["distributed_samples"].append(deepcopy(payload["distributed_samples"][0])),
        lambda payload: payload["distributed_samples"].pop(),
    ],
)
def test_distributed_operational_qualification_rejects_tampering(
    distributed_operational_qualification_artifacts,
    mutator,
):
    report = distributed_operational_qualification_artifacts
    payload = deepcopy(_payload(report))
    mutator(payload)

    with pytest.raises(HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError):
        HistoricalFuturesMarketDistributedOperationalQualificationReport.from_dict(payload)


def test_distributed_operational_qualification_rejects_unknown_fields(distributed_operational_qualification_artifacts):
    report = distributed_operational_qualification_artifacts
    payload = deepcopy(_payload(report))
    payload["manifest_hash"] = "0" * 64

    with pytest.raises(HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError):
        HistoricalFuturesMarketDistributedOperationalQualificationReport.from_dict(payload)


def test_distributed_operational_qualification_rejects_lowercase_bar_aliases(
    distributed_operational_qualification_artifacts,
):
    report = distributed_operational_qualification_artifacts
    payload = deepcopy(_payload(report))
    payload["distributed_samples"][5]["bar_alias"] = "1h"

    with pytest.raises(HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError):
        HistoricalFuturesMarketDistributedOperationalQualificationReport.from_dict(payload)

    payload = deepcopy(_payload(report))
    payload["distributed_samples"][10]["bar_alias"] = "4h"

    with pytest.raises(HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError):
        HistoricalFuturesMarketDistributedOperationalQualificationReport.from_dict(payload)


def test_distributed_operational_qualification_rejects_missing_sample(distributed_operational_qualification_artifacts):
    report = distributed_operational_qualification_artifacts
    payload = deepcopy(_payload(report))
    payload["distributed_samples"] = payload["distributed_samples"][:-1]

    with pytest.raises(HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError):
        HistoricalFuturesMarketDistributedOperationalQualificationReport.from_dict(payload)


def test_distributed_operational_qualification_rejects_extra_sample(distributed_operational_qualification_artifacts):
    report = distributed_operational_qualification_artifacts
    payload = deepcopy(_payload(report))
    payload["distributed_samples"].append(deepcopy(payload["distributed_samples"][0]))

    with pytest.raises(HistoricalFuturesMarketDistributedOperationalQualificationIntegrityError):
        HistoricalFuturesMarketDistributedOperationalQualificationReport.from_dict(payload)


def test_distributed_operational_qualification_preserves_research_only_flags(distributed_operational_qualification_artifacts):
    report = distributed_operational_qualification_artifacts

    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.protocol.historical_research_only is True
    assert report.protocol.operational_evidence is False
    assert report.protocol.paper_promotion_eligible is False
    assert report.protocol.distributed_operational_evidence_status == HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_STATUS
    assert report.summary.distributed_operational_evidence_status == HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_STATUS


def test_distributed_operational_qualification_persistence_helpers(distributed_operational_qualification_artifacts):
    report = distributed_operational_qualification_artifacts

    with TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "distributed-operational-qualification.json"

        saved = save_historical_futures_market_distributed_operational_qualification_report(path, report)
        loaded = load_historical_futures_market_distributed_operational_qualification_report(path)
        verified = verify_historical_futures_market_distributed_operational_qualification_report(path)
        status = status_historical_futures_market_distributed_operational_qualification_report(path)

    assert saved == report
    assert loaded == report
    assert verified["verified"] is True
    assert verified["report_hash"] == report.report_hash
    assert verified["protocol_hash"] == report.protocol.protocol_hash
    assert verified["summary_hash"] == report.summary.summary_hash
    assert verified["classification"] == HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_STATUS
    assert verified["distributed_operational_evidence_status"] == HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_STATUS
    assert verified["sample_count"] == 15
    assert verified["year_count"] == 5
    assert verified["interval_count"] == 3
    assert verified["page_count"] == 30
    assert verified["fetched_count"] == 3000
    assert verified["window_candle_count"] == 2100
    assert verified["all_confirm_closed"] is True
    assert verified["incomplete_candle_confirm_observed"] is False
    assert verified["distributed_samples_only"] is True
    assert verified["continuous_history_coverage_claimed"] is False
    assert status["exists"] is True
    assert status["report_hash"] == report.report_hash
    assert status["protocol_hash"] == report.protocol.protocol_hash
    assert status["summary_hash"] == report.summary.summary_hash
    assert status["sample_count"] == 15
    assert status["year_count"] == 5
    assert status["interval_count"] == 3
    assert status["page_count"] == 30
    assert status["fetched_count"] == 3000
    assert status["window_candle_count"] == 2100
    assert status["duplicate_count"] == 0
    assert status["gap_count"] == 0
    assert status["all_confirm_closed"] is True
    assert status["incomplete_candle_confirm_observed"] is False
    assert status["distributed_samples_only"] is True
    assert status["continuous_history_coverage_claimed"] is False
    assert status["distributed_operational_evidence_status"] == HISTORICAL_FUTURES_MARKET_DISTRIBUTED_OPERATIONAL_QUALIFICATION_STATUS


def test_distributed_operational_qualification_rejects_non_promotion(distributed_operational_qualification_artifacts):
    report = distributed_operational_qualification_artifacts
    rebuild = build_historical_futures_market_distributed_operational_qualification_report()

    assert rebuild == report
    with pytest.raises(HistoricalFuturesMarketDistributedOperationalQualificationPromotionError):
        reject_historical_futures_market_distributed_operational_qualification_promotion(report)


def test_distributed_operational_qualification_does_not_poll_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(urllib.request, "urlopen", fail, raising=True)

    report = build_historical_futures_market_distributed_operational_qualification_report()
    rebuilt = run_historical_futures_market_distributed_operational_qualification()

    assert report == rebuilt
