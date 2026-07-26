from __future__ import annotations

from copy import deepcopy
import urllib.request

import pytest

from historical_futures_market_extended_operational_qualification import (
    HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_BAR_ALIASES,
    HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT,
    HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_INTERVAL_NAMES,
    HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT,
    HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT,
    HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_RISK_NOTES,
    HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_STATUS,
    HistoricalFuturesMarketExtendedOperationalQualificationConflictError,
    HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError,
    HistoricalFuturesMarketExtendedOperationalQualificationPromotionError,
    HistoricalFuturesMarketExtendedOperationalQualificationReport,
    HistoricalFuturesMarketExtendedOperationalQualificationValidationError,
    build_historical_futures_market_extended_operational_qualification_report,
    load_historical_futures_market_extended_operational_qualification_report,
    reject_historical_futures_market_extended_operational_qualification_promotion,
    run_historical_futures_market_extended_operational_qualification,
    save_historical_futures_market_extended_operational_qualification_report,
    status_historical_futures_market_extended_operational_qualification_report,
    verify_historical_futures_market_extended_operational_qualification_report,
)


@pytest.fixture(scope="module")
def extended_operational_qualification_artifacts():
    report = build_historical_futures_market_extended_operational_qualification_report()
    return report


def _payload(report: HistoricalFuturesMarketExtendedOperationalQualificationReport) -> dict:
    return report.as_dict()


def test_extended_operational_qualification_round_trip_and_hash_stability(
    extended_operational_qualification_artifacts,
):
    report = extended_operational_qualification_artifacts
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
    assert report.summary.operational_evidence_status == HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_STATUS


def test_extended_operational_qualification_is_deterministic(extended_operational_qualification_artifacts):
    report_a = extended_operational_qualification_artifacts
    report_b = run_historical_futures_market_extended_operational_qualification()

    assert report_a.report_hash == report_b.report_hash
    assert report_a.protocol == report_b.protocol
    assert report_a.summary == report_b.summary
    assert report_a.interval_observations == report_b.interval_observations
    assert report_a.frozen_windows == report_b.frozen_windows


def test_extended_operational_qualification_covers_three_windows_and_three_intervals(
    extended_operational_qualification_artifacts,
):
    report = extended_operational_qualification_artifacts

    assert tuple(window.window_name for window in report.frozen_windows) == (
        "reference",
        "validation",
        "test",
    )
    assert tuple(window.start_utc.isoformat() for window in report.frozen_windows) == (
        "2025-01-04T08:14:59.999000+00:00",
        "2025-01-04T14:49:59.999000+00:00",
        "2025-01-04T21:24:59.999000+00:00",
    )
    assert tuple(window.end_utc.isoformat() for window in report.frozen_windows) == (
        "2025-01-04T14:49:59.998999+00:00",
        "2025-01-04T21:24:59.998999+00:00",
        "2025-01-05T03:59:59.999000+00:00",
    )
    assert tuple(observation.interval_name for observation in report.interval_observations) == (
        "15m",
        "1h",
        "4h",
    )
    assert tuple(observation.bar_alias for observation in report.interval_observations) == (
        "15m",
        "1H",
        "4H",
    )
    assert tuple(observation.provider_qualification.interval for observation in report.interval_observations) == (
        "15m",
        "1H",
        "4H",
    )
    assert report.protocol.canonical_source_name == "KuCoin spot"
    assert report.protocol.canonical_source_provider_id == "kucoin.public.klines"
    assert report.protocol.candidate_source_name == "OKX spot"
    assert report.protocol.candidate_provider_id == "okx.public.klines"
    assert report.protocol.candidate_market_type == "spot"
    assert report.protocol.candidate_symbol == "BTCUSDT"
    assert report.protocol.candidate_external_symbol == "BTC-USDT"
    assert report.protocol.candidate_time_semantics == "utc"
    assert report.protocol.candidate_access_type == "public_no_auth"
    assert report.protocol.candidate_provider_exchange == "okx"
    assert report.protocol.candidate_endpoint_url == "https://www.okx.com/api/v5/market/history-candles"
    assert report.protocol.candidate_documentation_url == "https://www.okx.com/docs-v5/en/"
    assert report.protocol.candidate_endpoint_path == "/api/v5/market/history-candles"
    assert report.protocol.operational_evidence_status == HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_STATUS
    assert report.protocol.coverage_scope_statement == HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT
    assert report.protocol.non_ingestion_scope_statement == HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT
    assert report.protocol.pagination_behavior_statement == HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT
    assert report.protocol.window_count == 3
    assert report.protocol.interval_count == 3
    assert report.protocol.provider_qualification_count == 3
    assert report.protocol.page_count == 10
    assert report.protocol.candle_count == 105
    assert report.protocol.duplicate_count == 0
    assert report.protocol.gap_count == 0
    assert report.summary.window_count == 3
    assert report.summary.interval_count == 3
    assert report.summary.provider_qualification_count == 3
    assert report.summary.page_count == 10
    assert report.summary.candle_count == 105
    assert report.summary.duplicate_count == 0
    assert report.summary.gap_count == 0
    assert report.summary.all_confirm_closed is True
    assert report.summary.incomplete_candle_confirm_observed is True
    assert report.protocol.coverage_start_utc.isoformat() == "2025-01-04T08:14:59.999000+00:00"
    assert report.protocol.coverage_end_utc.isoformat() == "2025-01-05T03:45:00+00:00"


def test_extended_operational_qualification_records_interval_evidence(extended_operational_qualification_artifacts):
    report = extended_operational_qualification_artifacts
    by_interval = {observation.interval_name: observation for observation in report.interval_observations}

    assert by_interval["15m"].candle_count == 80
    assert by_interval["15m"].first_candle_open_utc.isoformat() == "2025-01-04T08:00:00+00:00"
    assert by_interval["15m"].last_candle_open_utc.isoformat() == "2025-01-05T03:45:00+00:00"
    assert by_interval["15m"].duplicate_count == 0
    assert by_interval["15m"].gap_count == 0
    assert by_interval["15m"].page_count == 4
    assert by_interval["15m"].pagination_limit == 100
    assert by_interval["15m"].all_confirm_closed is True
    assert by_interval["15m"].incomplete_candle_confirm_observed is True
    assert by_interval["15m"].before_returns_newer_candles is True
    assert by_interval["15m"].after_observed_as_pagination_mechanism is True
    assert by_interval["15m"].utc_time_semantics == "utc"

    assert by_interval["1h"].candle_count == 20
    assert by_interval["1h"].first_candle_open_utc.isoformat() == "2025-01-04T08:00:00+00:00"
    assert by_interval["1h"].last_candle_open_utc.isoformat() == "2025-01-05T03:00:00+00:00"
    assert by_interval["1h"].duplicate_count == 0
    assert by_interval["1h"].gap_count == 0
    assert by_interval["1h"].page_count == 3
    assert by_interval["1h"].pagination_limit == 100
    assert by_interval["1h"].all_confirm_closed is True
    assert by_interval["1h"].incomplete_candle_confirm_observed is True
    assert by_interval["1h"].before_returns_newer_candles is True
    assert by_interval["1h"].after_observed_as_pagination_mechanism is True
    assert by_interval["1h"].utc_time_semantics == "utc"

    assert by_interval["4h"].candle_count == 5
    assert by_interval["4h"].first_candle_open_utc.isoformat() == "2025-01-04T08:00:00+00:00"
    assert by_interval["4h"].last_candle_open_utc.isoformat() == "2025-01-05T00:00:00+00:00"
    assert by_interval["4h"].duplicate_count == 0
    assert by_interval["4h"].gap_count == 0
    assert by_interval["4h"].page_count == 3
    assert by_interval["4h"].pagination_limit == 100
    assert by_interval["4h"].all_confirm_closed is True
    assert by_interval["4h"].incomplete_candle_confirm_observed is True
    assert by_interval["4h"].before_returns_newer_candles is True
    assert by_interval["4h"].after_observed_as_pagination_mechanism is True
    assert by_interval["4h"].utc_time_semantics == "utc"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.__setitem__("historical_research_only", False),
        lambda payload: payload.__setitem__("operational_evidence", True),
        lambda payload: payload.__setitem__("paper_promotion_eligible", True),
        lambda payload: payload["protocol"].__setitem__("candidate_provider_id", "kucoin.public.klines"),
        lambda payload: payload["protocol"].__setitem__("canonical_source_provider_id", "okx.public.klines"),
        lambda payload: payload["protocol"].__setitem__("candidate_source_name", "KuCoin spot"),
        lambda payload: payload["protocol"].__setitem__("candidate_market_type", "futures"),
        lambda payload: payload["protocol"].__setitem__("candidate_symbol", "ETHUSDT"),
        lambda payload: payload["protocol"].__setitem__("candidate_external_symbol", "ETH-USDT"),
        lambda payload: payload["protocol"].__setitem__("candidate_provider_version", "v2"),
        lambda payload: payload["protocol"].__setitem__("candidate_provider_exchange", "binance"),
        lambda payload: payload["protocol"].__setitem__("candidate_endpoint_url", "https://example.invalid"),
        lambda payload: payload["protocol"].__setitem__("candidate_documentation_url", "https://example.invalid"),
        lambda payload: payload["protocol"].__setitem__("candidate_endpoint_path", "/api/v5/market/candles"),
        lambda payload: payload["protocol"].__setitem__("operational_evidence_status", "dataset_ready"),
        lambda payload: payload["protocol"].__setitem__("coverage_scope_statement", "coverage 2021-2025"),
        lambda payload: payload["protocol"].__setitem__("non_ingestion_scope_statement", "tampered"),
        lambda payload: payload["protocol"].__setitem__("pagination_behavior_statement", "tampered"),
        lambda payload: payload["protocol"]["risk_notes"].__setitem__(0, "tampered"),
        lambda payload: payload["protocol"]["frozen_window_names"].__setitem__(0, "walk_forward"),
        lambda payload: payload["protocol"]["interval_names"].__setitem__(0, "30m"),
        lambda payload: payload["protocol"]["bar_aliases"].__setitem__(1, "1h"),
        lambda payload: payload["protocol"]["bar_aliases"].__setitem__(2, "4h"),
        lambda payload: payload["protocol"]["provider_qualification_hashes"].__setitem__(0, "0" * 64),
        lambda payload: payload["protocol"]["interval_observation_hashes"].__setitem__(0, "0" * 64),
        lambda payload: payload["protocol"].__setitem__("page_count", 9),
        lambda payload: payload["protocol"].__setitem__("candle_count", 104),
        lambda payload: payload["protocol"].__setitem__("duplicate_count", 1),
        lambda payload: payload["protocol"].__setitem__("gap_count", 1),
        lambda payload: payload["frozen_windows"][0].__setitem__("start_utc", "2025-01-04T08:15:00+00:00"),
        lambda payload: payload["frozen_windows"][1].__setitem__("window_name", "walk_forward"),
        lambda payload: payload["interval_observations"][0].__setitem__("interval_name", "30m"),
        lambda payload: payload["interval_observations"][0].__setitem__("bar_alias", "1h"),
        lambda payload: payload["interval_observations"][0].__setitem__("candle_count", 79),
        lambda payload: payload["interval_observations"][0].__setitem__("first_candle_open_utc", "2025-01-04T08:15:00+00:00"),
        lambda payload: payload["interval_observations"][0].__setitem__("last_candle_open_utc", "2025-01-05T03:30:00+00:00"),
        lambda payload: payload["interval_observations"][0].__setitem__("duplicate_count", 1),
        lambda payload: payload["interval_observations"][0].__setitem__("gap_count", 1),
        lambda payload: payload["interval_observations"][0].__setitem__("page_count", 2),
        lambda payload: payload["interval_observations"][0].__setitem__("pagination_limit", 50),
        lambda payload: payload["interval_observations"][0].__setitem__("all_confirm_closed", False),
        lambda payload: payload["interval_observations"][0].__setitem__("incomplete_candle_confirm_observed", False),
        lambda payload: payload["interval_observations"][0].__setitem__("before_returns_newer_candles", False),
        lambda payload: payload["interval_observations"][0].__setitem__("after_observed_as_pagination_mechanism", False),
        lambda payload: payload["interval_observations"][0].__setitem__("utc_time_semantics", "local"),
        lambda payload: payload["summary"].__setitem__("candle_count", 106),
        lambda payload: payload["summary"].__setitem__("duplicate_count", 1),
        lambda payload: payload["summary"].__setitem__("gap_count", 1),
        lambda payload: payload["summary"].__setitem__("page_count", 11),
        lambda payload: payload["summary"].__setitem__("all_confirm_closed", False),
        lambda payload: payload["summary"].__setitem__("incomplete_candle_confirm_observed", False),
        lambda payload: payload["summary"].__setitem__("operational_evidence_status", "dataset_ready"),
        lambda payload: payload["summary"].__setitem__("coverage_scope_statement", "tampered"),
        lambda payload: payload["summary"].__setitem__("risk_notes", ["tampered"]),
    ],
)
def test_extended_operational_qualification_rejects_tampering(
    extended_operational_qualification_artifacts,
    mutator,
):
    report = extended_operational_qualification_artifacts
    payload = deepcopy(_payload(report))
    mutator(payload)

    with pytest.raises(HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError):
        HistoricalFuturesMarketExtendedOperationalQualificationReport.from_dict(payload)


def test_extended_operational_qualification_rejects_unknown_fields(extended_operational_qualification_artifacts):
    report = extended_operational_qualification_artifacts
    payload = deepcopy(_payload(report))
    payload["manifest_hash"] = "0" * 64

    with pytest.raises(HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError):
        HistoricalFuturesMarketExtendedOperationalQualificationReport.from_dict(payload)


def test_extended_operational_qualification_rejects_missing_interval(extended_operational_qualification_artifacts):
    report = extended_operational_qualification_artifacts
    payload = deepcopy(_payload(report))
    payload["interval_observations"] = payload["interval_observations"][:2]

    with pytest.raises(HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError):
        HistoricalFuturesMarketExtendedOperationalQualificationReport.from_dict(payload)


def test_extended_operational_qualification_rejects_wrong_bar_aliases(extended_operational_qualification_artifacts):
    report = extended_operational_qualification_artifacts
    payload = deepcopy(_payload(report))
    payload["interval_observations"][1]["bar_alias"] = "1h"

    with pytest.raises(HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError):
        HistoricalFuturesMarketExtendedOperationalQualificationReport.from_dict(payload)

    payload = deepcopy(_payload(report))
    payload["interval_observations"][2]["bar_alias"] = "4h"

    with pytest.raises(HistoricalFuturesMarketExtendedOperationalQualificationIntegrityError):
        HistoricalFuturesMarketExtendedOperationalQualificationReport.from_dict(payload)


def test_extended_operational_qualification_preserves_research_only_flags(extended_operational_qualification_artifacts):
    report = extended_operational_qualification_artifacts

    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.protocol.historical_research_only is True
    assert report.protocol.operational_evidence is False
    assert report.protocol.paper_promotion_eligible is False
    assert report.summary.operational_evidence_status == HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_STATUS


def test_extended_operational_qualification_persistence_helpers(extended_operational_qualification_artifacts, tmp_path):
    report = extended_operational_qualification_artifacts
    path = tmp_path / "extended-operational-qualification.json"

    saved = save_historical_futures_market_extended_operational_qualification_report(path, report)
    loaded = load_historical_futures_market_extended_operational_qualification_report(path)
    verified = verify_historical_futures_market_extended_operational_qualification_report(path)
    status = status_historical_futures_market_extended_operational_qualification_report(path)

    assert saved == report
    assert loaded == report
    assert verified["verified"] is True
    assert verified["report_hash"] == report.report_hash
    assert verified["protocol_hash"] == report.protocol.protocol_hash
    assert verified["summary_hash"] == report.summary.summary_hash
    assert verified["classification"] == HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_STATUS
    assert verified["operational_evidence_status"] == HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_STATUS
    assert verified["window_count"] == 3
    assert verified["interval_count"] == 3
    assert verified["provider_qualification_count"] == 3
    assert verified["page_count"] == 10
    assert verified["candle_count"] == 105
    assert verified["all_confirm_closed"] is True
    assert status["exists"] is True
    assert status["report_hash"] == report.report_hash
    assert status["protocol_hash"] == report.protocol.protocol_hash
    assert status["summary_hash"] == report.summary.summary_hash
    assert status["window_count"] == 3
    assert status["interval_count"] == 3
    assert status["provider_qualification_count"] == 3
    assert status["page_count"] == 10
    assert status["candle_count"] == 105
    assert status["coverage_scope_statement"] == HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_COVERAGE_SCOPE_STATEMENT
    assert status["non_ingestion_scope_statement"] == HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_NON_INGESTION_SCOPE_STATEMENT
    assert status["pagination_behavior_statement"] == HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_PAGINATION_BEHAVIOR_STATEMENT


def test_extended_operational_qualification_rejects_non_candidate_or_promotion(extended_operational_qualification_artifacts):
    report = extended_operational_qualification_artifacts
    rebuild = build_historical_futures_market_extended_operational_qualification_report()

    assert rebuild == report
    with pytest.raises(HistoricalFuturesMarketExtendedOperationalQualificationPromotionError):
        reject_historical_futures_market_extended_operational_qualification_promotion(report)


def test_extended_operational_qualification_rejects_conflicting_save(extended_operational_qualification_artifacts, tmp_path):
    report = extended_operational_qualification_artifacts
    path = tmp_path / "extended-operational-qualification-conflict.json"
    save_historical_futures_market_extended_operational_qualification_report(path, report)

    conflicting = _payload(report)
    conflicting["summary"]["risk_notes"][0] = (
        "Official OKX spot documentation and public candles endpoint remain distinct from the canonical KuCoin spot chain."
    )

    class _ConflictingReport:
        def as_dict(self) -> dict:
            return conflicting

    with pytest.raises(HistoricalFuturesMarketExtendedOperationalQualificationConflictError):
        save_historical_futures_market_extended_operational_qualification_report(path, _ConflictingReport())


def test_extended_operational_qualification_builds_without_network(monkeypatch):
    def fail(*args, **kwargs):  # pragma: no cover - the test should never reach this
        raise AssertionError("network access is forbidden in this phase")

    monkeypatch.setattr(urllib.request, "urlopen", fail)

    report = build_historical_futures_market_extended_operational_qualification_report()

    assert report.summary.candle_count == 105
    assert report.protocol.operational_evidence_status == HISTORICAL_FUTURES_MARKET_EXTENDED_OPERATIONAL_QUALIFICATION_STATUS
