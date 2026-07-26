from __future__ import annotations

import pytest

from historical_futures_market_source_qualification import (
    HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANONICAL_SOURCE_NAME,
    HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID,
    HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_ACCESS_TYPE,
    HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL,
    HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_INTERVALS,
    HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_MARKET_TYPE,
    HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_ID,
    HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_NAME,
    HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SYMBOL,
    HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_TIME_SEMANTICS,
    HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_COVERAGE_STATUS_UNVERIFIED,
    HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_DOCUMENTATION_STATUS_CANDIDATE_ONLY,
    HistoricalFuturesMarketSourceQualificationConflictError,
    HistoricalFuturesMarketSourceQualificationPromotionError,
    HistoricalFuturesMarketSourceQualificationReport,
    HistoricalFuturesMarketSourceQualificationValidationError,
    build_historical_futures_market_source_qualification_report,
    load_historical_futures_market_source_qualification_report,
    reject_historical_futures_market_source_qualification_promotion,
    run_historical_futures_market_source_qualification,
    save_historical_futures_market_source_qualification_report,
    status_historical_futures_market_source_qualification_report,
    verify_historical_futures_market_source_qualification_report,
)
from tests.test_historical_futures_market_research_limitations_phase16 import (
    _build_research_limitations_artifacts,
)


def _build_source_qualification_artifacts(tmp_path):
    *_, research_limitations_report = _build_research_limitations_artifacts(tmp_path)
    report = run_historical_futures_market_source_qualification(research_limitations_report)
    return research_limitations_report, report


@pytest.fixture(scope="module")
def source_qualification_artifacts(tmp_path_factory):
    return _build_source_qualification_artifacts(tmp_path_factory.mktemp("phase17"))


def _payload(report: HistoricalFuturesMarketSourceQualificationReport) -> dict:
    return report.as_dict()


def test_source_qualification_round_trip_and_hash_stability(source_qualification_artifacts):
    research_limitations_report, report = source_qualification_artifacts
    rebuilt = type(report).from_dict(report.as_dict())

    assert report == rebuilt
    assert report.report_hash == rebuilt.report_hash
    assert report.as_dict() == rebuilt.as_dict()
    assert report.research_limitations_report == research_limitations_report
    assert report.research_limitations_report.report_hash == research_limitations_report.report_hash
    assert report.protocol.research_limitations_report_hash == research_limitations_report.report_hash
    assert report.protocol.provider_qualification_hashes == tuple(
        qualification.qualification_hash for qualification in report.provider_qualifications
    )
    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.protocol.historical_research_only is True
    assert report.protocol.operational_evidence is False
    assert report.protocol.paper_promotion_eligible is False
    assert report.summary.documentation_status == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_DOCUMENTATION_STATUS_CANDIDATE_ONLY
    assert report.summary.coverage_status == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_COVERAGE_STATUS_UNVERIFIED


def test_source_qualification_is_deterministic(source_qualification_artifacts):
    research_limitations_report, report_a = source_qualification_artifacts
    report_b = run_historical_futures_market_source_qualification(research_limitations_report)

    assert report_a.report_hash == report_b.report_hash
    assert report_a.provider_qualifications == report_b.provider_qualifications
    assert report_a.summary == report_b.summary


def test_source_qualification_covers_three_intervals(source_qualification_artifacts):
    _, report = source_qualification_artifacts

    assert report.canonical_source_name == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANONICAL_SOURCE_NAME
    assert report.canonical_source_provider_id == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID
    assert report.candidate_source_name == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_NAME
    assert report.candidate_provider_id == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_ID
    assert report.candidate_market_type == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_MARKET_TYPE
    assert report.candidate_symbol == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SYMBOL
    assert report.candidate_external_symbol == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL
    assert report.candidate_time_semantics == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_TIME_SEMANTICS
    assert report.candidate_access_type == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_ACCESS_TYPE
    assert tuple(item.interval for item in report.provider_qualifications) == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_INTERVALS
    assert report.protocol.provider_qualification_count == 3
    assert report.summary.provider_qualification_count == 3
    assert report.summary.supported_interval_count == 3


@pytest.mark.parametrize(
    "mutator, error_type",
    [
        (lambda payload: payload.__setitem__("candidate_provider_id", "kucoin.public.klines"), HistoricalFuturesMarketSourceQualificationValidationError),
        (lambda payload: payload.__setitem__("candidate_source_name", "KuCoin spot"), HistoricalFuturesMarketSourceQualificationValidationError),
        (lambda payload: payload.__setitem__("candidate_market_type", "futures"), HistoricalFuturesMarketSourceQualificationValidationError),
        (lambda payload: payload.__setitem__("candidate_symbol", "ETHUSDT"), HistoricalFuturesMarketSourceQualificationValidationError),
        (lambda payload: payload.__setitem__("candidate_external_symbol", "ETH-USDT"), HistoricalFuturesMarketSourceQualificationValidationError),
        (lambda payload: payload.__setitem__("candidate_time_semantics", "local"), HistoricalFuturesMarketSourceQualificationValidationError),
        (lambda payload: payload.__setitem__("candidate_access_type", "private_auth"), HistoricalFuturesMarketSourceQualificationValidationError),
        (lambda payload: payload.__setitem__("documentation_status", "verified"), HistoricalFuturesMarketSourceQualificationValidationError),
        (lambda payload: payload.__setitem__("coverage_status", "verified"), HistoricalFuturesMarketSourceQualificationValidationError),
        (lambda payload: payload.__setitem__("independence_evidence", ""), HistoricalFuturesMarketSourceQualificationValidationError),
        (lambda payload: payload.__setitem__("non_operational_scope_statement", ""), HistoricalFuturesMarketSourceQualificationValidationError),
        (
            lambda payload: payload["provider_qualifications"][1].__setitem__("interval", "30m"),
            HistoricalFuturesMarketSourceQualificationValidationError,
        ),
        (
            lambda payload: payload["provider_qualifications"][0].__setitem__("provider_id", "kucoin.public.klines"),
            HistoricalFuturesMarketSourceQualificationValidationError,
        ),
        (
            lambda payload: payload["provider_qualifications"][2].__setitem__("documentation_url", ""),
            HistoricalFuturesMarketSourceQualificationValidationError,
        ),
        (
            lambda payload: payload["provider_qualifications"][0].__setitem__("endpoint_url", ""),
            HistoricalFuturesMarketSourceQualificationValidationError,
        ),
        (
            lambda payload: payload["provider_qualifications"][1].__setitem__("close_time_rule", ""),
            HistoricalFuturesMarketSourceQualificationValidationError,
        ),
        (
            lambda payload: payload["provider_qualifications"][2].__setitem__("pagination_limit", 0),
            HistoricalFuturesMarketSourceQualificationValidationError,
        ),
        (
            lambda payload: payload["research_limitations_report"].__setitem__("report_hash", "0" * 64),
            HistoricalFuturesMarketSourceQualificationValidationError,
        ),
        (
            lambda payload: payload["protocol"].__setitem__("protocol_hash", "0" * 64),
            HistoricalFuturesMarketSourceQualificationValidationError,
        ),
    ],
)
def test_source_qualification_rejects_documentary_tampering(source_qualification_artifacts, mutator, error_type):
    _, report = source_qualification_artifacts
    payload = _payload(report)
    mutator(payload)

    with pytest.raises(error_type):
        HistoricalFuturesMarketSourceQualificationReport.from_dict(payload)


def test_source_qualification_rejects_unknown_fields(source_qualification_artifacts):
    _, report = source_qualification_artifacts
    payload = _payload(report)
    payload["manifest_hash"] = "0" * 64

    with pytest.raises(HistoricalFuturesMarketSourceQualificationValidationError):
        HistoricalFuturesMarketSourceQualificationReport.from_dict(payload)


def test_source_qualification_preserves_research_only_flags(source_qualification_artifacts):
    _, report = source_qualification_artifacts

    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.protocol.historical_research_only is True
    assert report.protocol.operational_evidence is False
    assert report.protocol.paper_promotion_eligible is False
    assert report.research_limitations_report.historical_research_only is True
    assert report.research_limitations_report.operational_evidence is False
    assert report.research_limitations_report.paper_promotion_eligible is False


def test_source_qualification_persistence_helpers(source_qualification_artifacts, tmp_path):
    _, report = source_qualification_artifacts
    path = tmp_path / "source_qualification.json"

    saved = save_historical_futures_market_source_qualification_report(path, report)
    loaded = load_historical_futures_market_source_qualification_report(path)
    verified = verify_historical_futures_market_source_qualification_report(path)
    status = status_historical_futures_market_source_qualification_report(path)

    assert saved == report
    assert loaded == report
    assert verified["verified"] is True
    assert verified["report_hash"] == report.report_hash
    assert verified["protocol_hash"] == report.protocol.protocol_hash
    assert verified["research_limitations_report_hash"] == report.research_limitations_report.report_hash
    assert verified["classification"] == "historical_research_only"
    assert status["exists"] is True
    assert status["report_hash"] == report.report_hash
    assert status["protocol_hash"] == report.protocol.protocol_hash
    assert status["research_limitations_report_hash"] == report.research_limitations_report.report_hash
    assert status["provider_qualification_count"] == 3
    assert status["supported_interval_count"] == 3
    assert status["documentation_status"] == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_DOCUMENTATION_STATUS_CANDIDATE_ONLY
    assert status["coverage_status"] == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_COVERAGE_STATUS_UNVERIFIED
    assert status["candidate_source_name"] == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_NAME
    assert status["candidate_provider_id"] == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_ID
    assert status["classification"] == "historical_research_only"


def test_source_qualification_rejects_non_candidate_or_promotion(source_qualification_artifacts):
    _, report = source_qualification_artifacts
    rebuild = build_historical_futures_market_source_qualification_report(report.research_limitations_report)

    assert rebuild == report
    with pytest.raises(HistoricalFuturesMarketSourceQualificationPromotionError):
        reject_historical_futures_market_source_qualification_promotion(report)


def test_source_qualification_rejects_conflicting_save(source_qualification_artifacts, tmp_path):
    _, report = source_qualification_artifacts
    path = tmp_path / "source_qualification_conflict.json"
    save_historical_futures_market_source_qualification_report(path, report)

    conflicting = _payload(report)
    conflicting["independence_evidence"] = (
        "Official OKX spot documentation and public candles endpoint remain distinct from the canonical KuCoin spot chain."
    )
    conflicting["report_hash"] = ""

    with pytest.raises(HistoricalFuturesMarketSourceQualificationConflictError):
        save_historical_futures_market_source_qualification_report(
            path,
            HistoricalFuturesMarketSourceQualificationReport.from_dict(conflicting),
        )
