from __future__ import annotations

from copy import deepcopy

import pytest

from historical_futures_market_operational_qualification import (
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_NAME,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ACCESS_TYPE,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_PATH,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_URL,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_INTERVALS,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_MARKET_TYPE,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_ID,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SOURCE_NAME,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SYMBOL,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_TIME_SEMANTICS,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_ENDPOINT_BEHAVIOR_STATEMENT,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT,
    HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS,
    HistoricalFuturesMarketOperationalQualificationConflictError,
    HistoricalFuturesMarketOperationalQualificationIntegrityError,
    HistoricalFuturesMarketOperationalQualificationPromotionError,
    HistoricalFuturesMarketOperationalQualificationReport,
    HistoricalFuturesMarketOperationalQualificationValidationError,
    build_historical_futures_market_operational_qualification_report,
    load_historical_futures_market_operational_qualification_report,
    reject_historical_futures_market_operational_qualification_promotion,
    run_historical_futures_market_operational_qualification,
    save_historical_futures_market_operational_qualification_report,
    status_historical_futures_market_operational_qualification_report,
    verify_historical_futures_market_operational_qualification_report,
)


@pytest.fixture(scope="module")
def operational_qualification_artifacts():
    report = build_historical_futures_market_operational_qualification_report()
    return report


def _payload(report: HistoricalFuturesMarketOperationalQualificationReport) -> dict:
    return report.as_dict()


def test_operational_qualification_round_trip_and_hash_stability(operational_qualification_artifacts):
    report = operational_qualification_artifacts
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


def test_operational_qualification_is_deterministic(operational_qualification_artifacts):
    report_a = operational_qualification_artifacts
    report_b = run_historical_futures_market_operational_qualification()

    assert report_a.report_hash == report_b.report_hash
    assert report_a.protocol == report_b.protocol
    assert report_a.summary == report_b.summary
    assert report_a.interval_observations == report_b.interval_observations
    assert report_a.frozen_windows == report_b.frozen_windows


def test_operational_qualification_covers_three_windows_and_three_intervals(operational_qualification_artifacts):
    report = operational_qualification_artifacts

    assert tuple(window.window_name for window in report.frozen_windows) == (
        "reference",
        "validation",
        "test",
    )
    assert tuple(observation.provider_qualification.interval for observation in report.interval_observations) == (
        "15m",
        "1h",
        "4h",
    )
    assert report.protocol.candidate_source_name == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SOURCE_NAME
    assert report.protocol.candidate_provider_id == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_ID
    assert report.protocol.candidate_market_type == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_MARKET_TYPE
    assert report.protocol.candidate_symbol == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SYMBOL
    assert report.protocol.candidate_external_symbol == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL
    assert report.protocol.candidate_time_semantics == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_TIME_SEMANTICS
    assert report.protocol.candidate_access_type == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ACCESS_TYPE
    assert report.protocol.candidate_endpoint_url == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_URL
    assert report.protocol.candidate_endpoint_path == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_ENDPOINT_PATH
    assert report.protocol.endpoint_behavior_statement == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_ENDPOINT_BEHAVIOR_STATEMENT
    assert report.protocol.candidate_provider_id != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID
    assert report.protocol.candidate_source_name != HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANONICAL_SOURCE_NAME
    assert report.protocol.window_count == 3
    assert report.protocol.interval_count == 3
    assert report.summary.window_count == 3
    assert report.summary.interval_count == 3
    assert report.summary.candle_count == 105
    assert report.summary.duplicate_count == 0
    assert report.summary.gap_count == 0
    assert report.summary.page_count == 3
    assert report.summary.all_confirm_closed is True
    assert report.summary.incomplete_candle_confirm_observed is True
    assert report.protocol.operational_qualification_status == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS
    assert report.summary.operational_qualification_status == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS
    assert report.protocol.coverage_scope_statement == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT
    assert report.protocol.non_ingestion_scope_statement == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT
    assert report.summary.coverage_scope_statement == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT
    assert report.summary.non_ingestion_scope_statement == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT


def test_operational_qualification_records_interval_evidence(operational_qualification_artifacts):
    report = operational_qualification_artifacts
    by_interval = {observation.provider_qualification.interval: observation for observation in report.interval_observations}

    assert by_interval["15m"].candle_count == 80
    assert by_interval["15m"].first_candle_open_utc.isoformat() == "2025-01-04T08:00:00+00:00"
    assert by_interval["15m"].last_candle_open_utc.isoformat() == "2025-01-05T03:45:00+00:00"
    assert by_interval["15m"].duplicate_count == 0
    assert by_interval["15m"].gap_count == 0
    assert by_interval["15m"].page_count == 1
    assert by_interval["15m"].pagination_limit == 100
    assert by_interval["15m"].all_confirm_closed is True
    assert by_interval["15m"].incomplete_candle_confirm_observed is True

    assert by_interval["1h"].candle_count == 20
    assert by_interval["1h"].first_candle_open_utc.isoformat() == "2025-01-04T08:00:00+00:00"
    assert by_interval["1h"].last_candle_open_utc.isoformat() == "2025-01-05T03:00:00+00:00"
    assert by_interval["1h"].duplicate_count == 0
    assert by_interval["1h"].gap_count == 0
    assert by_interval["1h"].page_count == 1
    assert by_interval["1h"].pagination_limit == 100
    assert by_interval["1h"].all_confirm_closed is True
    assert by_interval["1h"].incomplete_candle_confirm_observed is True

    assert by_interval["4h"].candle_count == 5
    assert by_interval["4h"].first_candle_open_utc.isoformat() == "2025-01-04T08:00:00+00:00"
    assert by_interval["4h"].last_candle_open_utc.isoformat() == "2025-01-05T00:00:00+00:00"
    assert by_interval["4h"].duplicate_count == 0
    assert by_interval["4h"].gap_count == 0
    assert by_interval["4h"].page_count == 1
    assert by_interval["4h"].pagination_limit == 100
    assert by_interval["4h"].all_confirm_closed is True
    assert by_interval["4h"].incomplete_candle_confirm_observed is True


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.__setitem__("historical_research_only", False),
        lambda payload: payload.__setitem__("operational_evidence", True),
        lambda payload: payload.__setitem__("paper_promotion_eligible", True),
        lambda payload: payload.__setitem__("manifest_hash", "0" * 64),
        lambda payload: payload["protocol"].__setitem__("candidate_provider_id", "kucoin.public.klines"),
        lambda payload: payload["protocol"].__setitem__("candidate_market_type", "futures"),
        lambda payload: payload["protocol"].__setitem__("candidate_symbol", "ETHUSDT"),
        lambda payload: payload["protocol"].__setitem__("candidate_external_symbol", "ETH-USDT"),
        lambda payload: payload["protocol"].__setitem__("candidate_endpoint_url", "https://example.invalid"),
        lambda payload: payload["protocol"].__setitem__("candidate_documentation_url", "https://example.invalid"),
        lambda payload: payload["protocol"].__setitem__("candidate_endpoint_path", "/api/v5/market/candles"),
        lambda payload: payload["protocol"].__setitem__("operational_qualification_status", "dataset_ready"),
        lambda payload: payload["protocol"].__setitem__("coverage_scope_statement", "tampered"),
        lambda payload: payload["protocol"].__setitem__("non_ingestion_scope_statement", "tampered"),
        lambda payload: payload["protocol"]["frozen_window_names"].__setitem__(0, "walk_forward"),
        lambda payload: payload["protocol"]["interval_names"].__setitem__(0, "30m"),
        lambda payload: payload["protocol"]["frozen_window_hashes"].__setitem__(0, "0" * 64),
        lambda payload: payload["protocol"]["interval_observation_hashes"].__setitem__(0, "0" * 64),
        lambda payload: payload["frozen_windows"][0].__setitem__("start_utc", "2025-01-04T08:15:00+00:00"),
        lambda payload: payload["frozen_windows"][1].__setitem__("window_name", "walk_forward"),
        lambda payload: payload["interval_observations"][0].__setitem__("candle_count", 79),
        lambda payload: payload["interval_observations"][0].__setitem__("first_candle_open_utc", "2025-01-04T08:15:00+00:00"),
        lambda payload: payload["interval_observations"][0].__setitem__("last_candle_open_utc", "2025-01-05T03:30:00+00:00"),
        lambda payload: payload["interval_observations"][0].__setitem__("duplicate_count", 1),
        lambda payload: payload["interval_observations"][0].__setitem__("gap_count", 1),
        lambda payload: payload["interval_observations"][0].__setitem__("page_count", 2),
        lambda payload: payload["interval_observations"][0].__setitem__("pagination_limit", 50),
        lambda payload: payload["interval_observations"][0].__setitem__("all_confirm_closed", False),
        lambda payload: payload["interval_observations"][0].__setitem__("incomplete_candle_confirm_observed", False),
        lambda payload: payload["summary"].__setitem__("candle_count", 106),
        lambda payload: payload["summary"].__setitem__("duplicate_count", 1),
        lambda payload: payload["summary"].__setitem__("gap_count", 1),
        lambda payload: payload["summary"].__setitem__("page_count", 2),
        lambda payload: payload["summary"].__setitem__("all_confirm_closed", False),
        lambda payload: payload["summary"].__setitem__("incomplete_candle_confirm_observed", False),
    ],
)
def test_operational_qualification_rejects_tampering(operational_qualification_artifacts, mutator):
    report = operational_qualification_artifacts
    payload = deepcopy(_payload(report))
    mutator(payload)

    with pytest.raises(HistoricalFuturesMarketOperationalQualificationIntegrityError):
        HistoricalFuturesMarketOperationalQualificationReport.from_dict(payload)


def test_operational_qualification_rejects_unknown_fields(operational_qualification_artifacts):
    report = operational_qualification_artifacts
    payload = deepcopy(_payload(report))
    payload["content_hash"] = "0" * 64

    with pytest.raises(HistoricalFuturesMarketOperationalQualificationIntegrityError):
        HistoricalFuturesMarketOperationalQualificationReport.from_dict(payload)


def test_operational_qualification_rejects_missing_interval(operational_qualification_artifacts):
    report = operational_qualification_artifacts
    payload = deepcopy(_payload(report))
    payload["interval_observations"] = payload["interval_observations"][:2]

    with pytest.raises(HistoricalFuturesMarketOperationalQualificationIntegrityError):
        HistoricalFuturesMarketOperationalQualificationReport.from_dict(payload)


def test_operational_qualification_preserves_research_only_flags(operational_qualification_artifacts):
    report = operational_qualification_artifacts

    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.protocol.historical_research_only is True
    assert report.protocol.operational_evidence is False
    assert report.protocol.paper_promotion_eligible is False
    assert report.summary.operational_qualification_status == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS


def test_operational_qualification_persistence_helpers(operational_qualification_artifacts, tmp_path):
    report = operational_qualification_artifacts
    path = tmp_path / "operational-qualification.json"

    saved = save_historical_futures_market_operational_qualification_report(path, report)
    loaded = load_historical_futures_market_operational_qualification_report(path)
    verified = verify_historical_futures_market_operational_qualification_report(path)
    status = status_historical_futures_market_operational_qualification_report(path)

    assert saved == report
    assert loaded == report
    assert verified["verified"] is True
    assert verified["report_hash"] == report.report_hash
    assert verified["protocol_hash"] == report.protocol.protocol_hash
    assert verified["summary_hash"] == report.summary.summary_hash
    assert verified["classification"] == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS
    assert verified["operational_qualification_status"] == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS
    assert verified["window_count"] == 3
    assert verified["interval_count"] == 3
    assert verified["candle_count"] == 105
    assert verified["all_confirm_closed"] is True
    assert status["exists"] is True
    assert status["report_hash"] == report.report_hash
    assert status["protocol_hash"] == report.protocol.protocol_hash
    assert status["summary_hash"] == report.summary.summary_hash
    assert status["window_count"] == 3
    assert status["interval_count"] == 3
    assert status["candle_count"] == 105
    assert status["duplicate_count"] == 0
    assert status["gap_count"] == 0
    assert status["page_count"] == 3
    assert status["all_confirm_closed"] is True
    assert status["incomplete_candle_confirm_observed"] is True
    assert status["operational_qualification_status"] == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS
    assert status["candidate_source_name"] == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SOURCE_NAME
    assert status["candidate_provider_id"] == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_PROVIDER_ID
    assert status["candidate_symbol"] == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_CANDIDATE_SYMBOL
    assert status["classification"] == HISTORICAL_FUTURES_MARKET_OPERATIONAL_QUALIFICATION_STATUS


def test_operational_qualification_rejects_non_promotion(operational_qualification_artifacts):
    report = operational_qualification_artifacts
    rebuild = build_historical_futures_market_operational_qualification_report()

    assert rebuild == report
    with pytest.raises(HistoricalFuturesMarketOperationalQualificationPromotionError):
        reject_historical_futures_market_operational_qualification_promotion(report)
