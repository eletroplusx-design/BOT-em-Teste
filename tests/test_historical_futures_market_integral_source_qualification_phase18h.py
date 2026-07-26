from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
import socket
from pathlib import Path
from tempfile import TemporaryDirectory
import urllib.request

import pytest

import historical_futures_market_integral_source_qualification as integral
from historical_futures_market_integral_source_qualification import (
    HistoricalFuturesMarketIntegralSourceQualificationConflictError,
    HistoricalFuturesMarketIntegralSourceQualificationIntegrityError,
    HistoricalFuturesMarketIntegralSourceQualificationPromotionError,
    HistoricalFuturesMarketIntegralSourceQualificationReport,
    HistoricalFuturesMarketIntegralSourceQualificationValidationError,
    build_historical_futures_market_integral_source_qualification_protocol,
    build_historical_futures_market_integral_source_qualification_report,
    load_historical_futures_market_integral_source_qualification_report,
    reject_historical_futures_market_integral_source_qualification_promotion,
    run_historical_futures_market_integral_source_qualification,
    save_historical_futures_market_integral_source_qualification_report,
    status_historical_futures_market_integral_source_qualification_report,
    verify_historical_futures_market_integral_source_qualification_report,
)
from market_data import HistoricalDataValidationError


@pytest.fixture(scope="module")
def integral_source_qualification_report():
    return build_historical_futures_market_integral_source_qualification_report()


def _payload(report: HistoricalFuturesMarketIntegralSourceQualificationReport) -> dict:
    return deepcopy(report.as_dict())


def test_integral_source_qualification_round_trip_and_hash_stability(integral_source_qualification_report):
    report = integral_source_qualification_report
    rebuilt = type(report).from_dict(report.as_dict())

    assert report == rebuilt
    assert report.report_hash == rebuilt.report_hash
    assert report.as_dict() == rebuilt.as_dict()
    assert report.protocol == build_historical_futures_market_integral_source_qualification_protocol()
    assert report.protocol.provider_qualification_hash == report.provider_qualification.qualification_hash
    assert report.protocol.annual_result_hashes == tuple(item.annual_result_hash for item in report.annual_results)
    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.protocol.historical_research_only is True
    assert report.protocol.operational_evidence is False
    assert report.protocol.paper_promotion_eligible is False
    assert report.summary.integral_source_qualification_status == integral.HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS
    assert tuple(item.year for item in report.annual_results) == (2021, 2022, 2023, 2024, 2025)
    assert set(report.as_dict()) == {
        "schema_version",
        "provider_qualification",
        "annual_results",
        "protocol",
        "summary",
        "historical_research_only",
        "operational_evidence",
        "paper_promotion_eligible",
        "report_hash",
    }


def test_integral_source_qualification_is_deterministic(integral_source_qualification_report):
    report_a = integral_source_qualification_report
    report_b = run_historical_futures_market_integral_source_qualification()

    assert report_a.report_hash == report_b.report_hash
    assert report_a.protocol == report_b.protocol
    assert report_a.summary == report_b.summary
    assert report_a.annual_results == report_b.annual_results


def test_integral_source_qualification_records_the_audited_contract(integral_source_qualification_report):
    report = integral_source_qualification_report

    assert report.provider_qualification.provider_id == "okx.public.klines"
    assert report.provider_qualification.provider_version == "v1"
    assert report.provider_qualification.market_type == "spot"
    assert report.provider_qualification.exchange == "okx"
    assert report.provider_qualification.symbol == "BTCUSDT"
    assert report.provider_qualification.interval == "1H"
    assert report.provider_qualification.time_semantics == "utc"
    assert report.provider_qualification.access_type == "public_no_auth"
    assert report.provider_qualification.external_symbol == "BTC-USDT"
    assert report.provider_qualification.endpoint_url == "https://www.okx.com/api/v5/market/history-candles"
    assert report.provider_qualification.documentation_url == "https://www.okx.com/docs-v5/en/"
    assert report.provider_qualification.pagination_limit == 100
    assert report.provider_qualification.close_time_rule == "confirm=0 means incomplete; confirm=1 means completed"
    assert report.protocol.canonical_source_name == "KuCoin spot"
    assert report.protocol.canonical_source_provider_id == "kucoin.public.klines"
    assert report.protocol.canonical_market_type == "spot"
    assert report.protocol.canonical_symbol == "BTCUSDT"
    assert report.protocol.candidate_source_name == "OKX spot"
    assert report.protocol.candidate_provider_id == "okx.public.klines"
    assert report.protocol.candidate_market_type == "spot"
    assert report.protocol.candidate_symbol == "BTCUSDT"
    assert report.protocol.candidate_external_symbol == "BTC-USDT"
    assert report.protocol.candidate_provider_exchange == "okx"
    assert report.protocol.candidate_provider_version == "v1"
    assert report.protocol.candidate_access_type == "public_no_auth"
    assert report.protocol.candidate_time_semantics == "utc"
    assert report.protocol.candidate_endpoint_url == "https://www.okx.com/api/v5/market/history-candles"
    assert report.protocol.candidate_endpoint_path == "/api/v5/market/history-candles"
    assert report.protocol.candidate_documentation_url == "https://www.okx.com/docs-v5/en/"
    assert report.protocol.candidate_close_time_rule == "confirm=0 means incomplete; confirm=1 means completed"
    assert report.protocol.audited_interval_name == "1H"
    assert report.protocol.audited_period_start_utc.isoformat() == "2021-02-12T00:00:00+00:00"
    assert report.protocol.audited_period_end_exclusive_utc.isoformat() == "2026-01-01T00:00:00+00:00"
    assert report.protocol.first_candle_open_utc.isoformat() == "2021-02-12T00:00:00+00:00"
    assert report.protocol.last_candle_open_utc.isoformat() == "2025-12-31T23:00:00+00:00"
    assert report.protocol.expected_candle_count == 42816
    assert report.protocol.found_candle_count == 42816
    assert report.protocol.pages_observed == 429
    assert report.protocol.limit_used == 100
    assert report.protocol.cursor_name == "after"
    assert report.protocol.cursor_exclusive is True
    assert report.protocol.collect_direction == "reverse_chronological"
    assert report.protocol.confirm_value == 1
    assert report.protocol.all_confirm_closed is True
    assert report.protocol.utc_time_semantics == "utc"
    assert report.protocol.utc_alignment_valid is True
    assert report.protocol.duplicate_count == 0
    assert report.protocol.gap_count == 0
    assert report.protocol.overlap_count == 0
    assert report.protocol.cursor_no_progress_count == 0
    assert report.protocol.http_error_count == 0
    assert report.protocol.timeout_count == 0
    assert report.protocol.incomplete_candle_count == 0
    assert report.protocol.year_count == 5
    assert report.protocol.annual_result_count == 5
    assert report.protocol.interval_count == 1
    assert report.protocol.provider_qualification_count == 1
    assert report.protocol.scope == "single_candidate_single_market_single_instrument_single_interval_single_audited_period"
    assert report.protocol.coverage_scope_statement == (
        "Coverage is limited to the audited BTC-USDT spot 1H period from 2021-02-12T00:00:00Z to "
        "2026-01-01T00:00:00Z; coverage beyond that period remains unverified."
    )
    assert report.protocol.non_ingestion_scope_statement == (
        "No API polling, download, dataset, manifest, candle hash, replay, backtest, performance comparison, "
        "paper trading, or live trading is authorized."
    )
    assert report.protocol.pagination_behavior_statement == (
        "The OKX history-candles endpoint was observed with after as the exclusive cursor and limit=100, "
        "and pages can include candles before the requested start that must be filtered in memory."
    )
    assert report.summary.pages_observed == 429
    assert report.summary.expected_candle_count == 42816
    assert report.summary.found_candle_count == 42816
    assert report.summary.duplicate_count == 0
    assert report.summary.gap_count == 0
    assert report.summary.overlap_count == 0
    assert report.summary.cursor_no_progress_count == 0
    assert report.summary.http_error_count == 0
    assert report.summary.timeout_count == 0
    assert report.summary.incomplete_candle_count == 0
    assert report.summary.all_confirm_closed is True
    assert report.summary.utc_alignment_valid is True
    assert report.summary.integral_source_qualification_status == integral.HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS
    assert report.summary.risk_notes == integral.HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_RISK_NOTES
    assert tuple(item.result for item in report.annual_results) == ("pass", "pass", "pass", "pass", "pass")
    assert tuple(item.expected_candle_count for item in report.annual_results) == (7752, 8760, 8760, 8784, 8760)
    assert tuple(item.found_candle_count for item in report.annual_results) == (7752, 8760, 8760, 8784, 8760)
    assert tuple(item.duplicate_count for item in report.annual_results) == (0, 0, 0, 0, 0)
    assert tuple(item.gap_count for item in report.annual_results) == (0, 0, 0, 0, 0)
    assert tuple(item.first_timestamp_utc.isoformat() for item in report.annual_results) == (
        "2021-02-12T00:00:00+00:00",
        "2022-01-01T00:00:00+00:00",
        "2023-01-01T00:00:00+00:00",
        "2024-01-01T00:00:00+00:00",
        "2025-01-01T00:00:00+00:00",
    )
    assert tuple(item.last_timestamp_utc.isoformat() for item in report.annual_results) == (
        "2021-12-31T23:00:00+00:00",
        "2022-12-31T23:00:00+00:00",
        "2023-12-31T23:00:00+00:00",
        "2024-12-31T23:00:00+00:00",
        "2025-12-31T23:00:00+00:00",
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.__setitem__("historical_research_only", False),
        lambda payload: payload.__setitem__("operational_evidence", True),
        lambda payload: payload.__setitem__("paper_promotion_eligible", True),
        lambda payload: payload.__delitem__("summary"),
        lambda payload: payload.__setitem__("manifest_hash", "0" * 64),
        lambda payload: payload["provider_qualification"].__setitem__("interval", "1h"),
        lambda payload: payload["provider_qualification"].__setitem__("provider_id", "kucoin.public.klines"),
        lambda payload: payload["provider_qualification"].__setitem__("exchange", "binance"),
        lambda payload: payload["provider_qualification"].__setitem__("symbol", "ETHUSDT"),
        lambda payload: payload["provider_qualification"].__setitem__("external_symbol", "ETH-USDT"),
        lambda payload: payload["protocol"].__setitem__("candidate_source_name", "KuCoin spot"),
        lambda payload: payload["protocol"].__setitem__("candidate_provider_id", "kucoin.public.klines"),
        lambda payload: payload["protocol"].__setitem__("candidate_market_type", "futures"),
        lambda payload: payload["protocol"].__setitem__("candidate_symbol", "ETHUSDT"),
        lambda payload: payload["protocol"].__setitem__("candidate_external_symbol", "ETH-USDT"),
        lambda payload: payload["protocol"].__setitem__("candidate_provider_exchange", "binance"),
        lambda payload: payload["protocol"].__setitem__("candidate_endpoint_url", "https://example.invalid"),
        lambda payload: payload["protocol"].__setitem__("candidate_documentation_url", "https://example.invalid"),
        lambda payload: payload["protocol"].__setitem__("candidate_close_time_rule", "tampered"),
        lambda payload: payload["protocol"].__setitem__("audited_interval_name", "1h"),
        lambda payload: payload["protocol"].__setitem__("audited_period_start_utc", "2021-02-13T00:00:00+00:00"),
        lambda payload: payload["protocol"].__setitem__("audited_period_end_exclusive_utc", "2025-12-31T00:00:00+00:00"),
        lambda payload: payload["protocol"].__setitem__("first_candle_open_utc", "2021-02-13T00:00:00+00:00"),
        lambda payload: payload["protocol"].__setitem__("last_candle_open_utc", "2026-01-01T00:00:00+00:00"),
        lambda payload: payload["protocol"].__setitem__("expected_candle_count", 1),
        lambda payload: payload["protocol"].__setitem__("found_candle_count", 1),
        lambda payload: payload["protocol"].__setitem__("pages_observed", 1),
        lambda payload: payload["protocol"].__setitem__("limit_used", 300),
        lambda payload: payload["protocol"].__setitem__("cursor_name", "before"),
        lambda payload: payload["protocol"].__setitem__("cursor_exclusive", False),
        lambda payload: payload["protocol"].__setitem__("collect_direction", "chronological"),
        lambda payload: payload["protocol"].__setitem__("confirm_value", 0),
        lambda payload: payload["protocol"].__setitem__("all_confirm_closed", False),
        lambda payload: payload["protocol"].__setitem__("utc_time_semantics", "local"),
        lambda payload: payload["protocol"].__setitem__("utc_alignment_valid", False),
        lambda payload: payload["protocol"].__setitem__("duplicate_count", 1),
        lambda payload: payload["protocol"].__setitem__("gap_count", 1),
        lambda payload: payload["protocol"].__setitem__("year_count", 4),
        lambda payload: payload["protocol"].__setitem__("annual_result_count", 4),
        lambda payload: payload["protocol"].__setitem__("interval_count", 2),
        lambda payload: payload["protocol"].__setitem__("provider_qualification_count", 2),
        lambda payload: payload["protocol"].__setitem__("annual_result_hashes", ["0" * 64] * 5),
        lambda payload: payload["protocol"].__setitem__("coverage_scope_statement", "tampered"),
        lambda payload: payload["protocol"].__setitem__("non_ingestion_scope_statement", "tampered"),
        lambda payload: payload["protocol"].__setitem__("pagination_behavior_statement", "tampered"),
        lambda payload: payload["protocol"].__setitem__("risk_notes", ["tampered"]),
        lambda payload: payload["summary"].__setitem__("integral_source_qualification_status", "tampered"),
        lambda payload: payload["summary"].__setitem__("year_count", 4),
        lambda payload: payload["summary"].__setitem__("annual_result_count", 4),
        lambda payload: payload["summary"].__setitem__("pass_year_count", 4),
        lambda payload: payload["summary"].__setitem__("interval_count", 2),
        lambda payload: payload["summary"].__setitem__("provider_qualification_count", 2),
        lambda payload: payload["summary"].__setitem__("pages_observed", 1),
        lambda payload: payload["summary"].__setitem__("expected_candle_count", 1),
        lambda payload: payload["summary"].__setitem__("found_candle_count", 1),
        lambda payload: payload["summary"].__setitem__("duplicate_count", 1),
        lambda payload: payload["summary"].__setitem__("gap_count", 1),
        lambda payload: payload["summary"].__setitem__("all_confirm_closed", False),
        lambda payload: payload["summary"].__setitem__("utc_alignment_valid", False),
        lambda payload: payload["summary"].__setitem__("risk_notes", ["tampered"]),
        lambda payload: payload["annual_results"][0].__setitem__("year", 2020),
        lambda payload: payload["annual_results"][0].__setitem__("first_timestamp_utc", "2021-02-13T00:00:00+00:00"),
        lambda payload: payload["annual_results"][0].__setitem__("last_timestamp_utc", "2021-12-31T22:00:00+00:00"),
        lambda payload: payload["annual_results"][0].__setitem__("expected_candle_count", 1),
        lambda payload: payload["annual_results"][0].__setitem__("found_candle_count", 1),
        lambda payload: payload["annual_results"][0].__setitem__("duplicate_count", 1),
        lambda payload: payload["annual_results"][0].__setitem__("gap_count", 1),
        lambda payload: payload["annual_results"][0].__setitem__("result", "fail"),
        lambda payload: payload["annual_results"][0].__setitem__("annual_result_hash", "0" * 64),
        lambda payload: payload["annual_results"].pop(),
        lambda payload: payload["annual_results"].append(deepcopy(payload["annual_results"][0])),
        lambda payload: payload.__setitem__("report_hash", "0" * 64),
        lambda payload: payload["protocol"].__setitem__("protocol_hash", "0" * 64),
        lambda payload: payload["summary"].__setitem__("summary_hash", "0" * 64),
    ],
)
def test_integral_source_qualification_rejects_tampering(
    integral_source_qualification_report,
    mutator,
):
    report = integral_source_qualification_report
    payload = _payload(report)
    mutator(payload)

    with pytest.raises(
        (
            HistoricalFuturesMarketIntegralSourceQualificationValidationError,
            HistoricalDataValidationError,
        )
    ):
        HistoricalFuturesMarketIntegralSourceQualificationReport.from_dict(payload)


def test_integral_source_qualification_rejects_unknown_fields(integral_source_qualification_report):
    report = integral_source_qualification_report
    payload = _payload(report)
    payload["manifest_hash"] = "0" * 64

    with pytest.raises(HistoricalFuturesMarketIntegralSourceQualificationValidationError):
        HistoricalFuturesMarketIntegralSourceQualificationReport.from_dict(payload)


def test_integral_source_qualification_preserves_research_only_flags(integral_source_qualification_report):
    report = integral_source_qualification_report

    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.protocol.historical_research_only is True
    assert report.protocol.operational_evidence is False
    assert report.protocol.paper_promotion_eligible is False
    assert report.summary.integral_source_qualification_status == integral.HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS


def test_integral_source_qualification_persistence_helpers(integral_source_qualification_report):
    report = integral_source_qualification_report

    with TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "integral-source-qualification.json"

        saved = save_historical_futures_market_integral_source_qualification_report(path, report)
        loaded = load_historical_futures_market_integral_source_qualification_report(path)
        verified = verify_historical_futures_market_integral_source_qualification_report(path)
        status = status_historical_futures_market_integral_source_qualification_report(path)

    assert saved == report
    assert loaded == report
    assert verified["verified"] is True
    assert verified["report_hash"] == report.report_hash
    assert verified["protocol_hash"] == report.protocol.protocol_hash
    assert verified["summary_hash"] == report.summary.summary_hash
    assert verified["provider_qualification_hash"] == report.provider_qualification.qualification_hash
    assert verified["classification"] == integral.HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS
    assert verified["integral_source_qualification_status"] == integral.HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS
    assert verified["year_count"] == 5
    assert verified["annual_result_count"] == 5
    assert verified["pages_observed"] == 429
    assert verified["expected_candle_count"] == 42816
    assert verified["found_candle_count"] == 42816
    assert verified["all_confirm_closed"] is True
    assert verified["utc_alignment_valid"] is True
    assert status["exists"] is True
    assert status["report_hash"] == report.report_hash
    assert status["protocol_hash"] == report.protocol.protocol_hash
    assert status["summary_hash"] == report.summary.summary_hash
    assert status["provider_qualification_hash"] == report.provider_qualification.qualification_hash
    assert status["classification"] == integral.HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS
    assert status["integral_source_qualification_status"] == integral.HISTORICAL_FUTURES_MARKET_INTEGRAL_SOURCE_QUALIFICATION_STATUS
    assert status["canonical_source_name"] == "KuCoin spot"
    assert status["canonical_source_provider_id"] == "kucoin.public.klines"
    assert status["candidate_source_name"] == "OKX spot"
    assert status["candidate_provider_id"] == "okx.public.klines"
    assert status["candidate_market_type"] == "spot"
    assert status["candidate_symbol"] == "BTCUSDT"
    assert status["candidate_external_symbol"] == "BTC-USDT"
    assert status["audited_interval_name"] == "1H"
    assert status["expected_candle_count"] == 42816
    assert status["found_candle_count"] == 42816
    assert status["pages_observed"] == 429
    assert status["limit_used"] == 100
    assert status["duplicate_count"] == 0
    assert status["gap_count"] == 0
    assert status["overlap_count"] == 0
    assert status["cursor_no_progress_count"] == 0
    assert status["http_error_count"] == 0
    assert status["timeout_count"] == 0
    assert status["incomplete_candle_count"] == 0
    assert status["year_count"] == 5
    assert status["annual_result_count"] == 5
    assert status["provider_qualification_count"] == 1
    assert status["all_confirm_closed"] is True
    assert status["utc_alignment_valid"] is True


def test_integral_source_qualification_rejects_non_promotion(integral_source_qualification_report):
    report = integral_source_qualification_report
    rebuilt = build_historical_futures_market_integral_source_qualification_report()

    assert rebuilt == report
    with pytest.raises(HistoricalFuturesMarketIntegralSourceQualificationPromotionError):
        reject_historical_futures_market_integral_source_qualification_promotion(report)


def test_integral_source_qualification_rejects_conflicting_save(integral_source_qualification_report):
    report = integral_source_qualification_report
    with TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "integral-source-qualification-conflict.json"
        save_historical_futures_market_integral_source_qualification_report(path, report)

        conflicting = type(report).from_dict(report.as_dict())
        object.__setattr__(conflicting, "report_hash", "0" * 64)

        with pytest.raises(HistoricalFuturesMarketIntegralSourceQualificationConflictError):
            save_historical_futures_market_integral_source_qualification_report(path, conflicting)


def test_integral_source_qualification_does_not_poll_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("network access is not allowed")

    monkeypatch.setattr(urllib.request, "urlopen", fail, raising=True)
    monkeypatch.setattr(socket, "create_connection", fail, raising=True)

    report = build_historical_futures_market_integral_source_qualification_report()
    rebuilt = run_historical_futures_market_integral_source_qualification()

    assert report == rebuilt
