from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

from historical_futures_market_contract import (
    HistoricalFuturesMarketContractIntegrityError,
    HistoricalFuturesMarketContractValidationError,
    build_historical_futures_market_contract,
)
from historical_futures_market_validation import (
    HistoricalFuturesMarketValidationIntegrityError,
    HistoricalFuturesMarketValidationValidationError,
    HistoricalFuturesMarketValidationReport,
    build_historical_futures_market_validation_report,
    load_historical_futures_market_validation_report,
    reject_historical_futures_market_validation_promotion,
    run_historical_futures_market_validation,
    save_historical_futures_market_validation_report,
    status_historical_futures_market_validation_report,
    verify_historical_futures_market_validation_report,
)
from tests.test_historical_futures_market_contract_phase14a import _build_artifacts


def _build_validation_artifacts(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    contract = build_historical_futures_market_contract(strategy_report, evaluation_report, analysis_report)
    report = run_historical_futures_market_validation(contract, analysis_report)
    return contract, analysis_report, report


def test_validation_report_round_trip_and_hash_stability(tmp_path):
    contract, analysis_report, report = _build_validation_artifacts(tmp_path)
    rebuilt = type(report).from_dict(report.as_dict())

    assert report == rebuilt
    assert report.report_hash == rebuilt.report_hash
    assert report.as_dict() == rebuilt.as_dict()
    assert report.contract == contract
    assert report.analysis_report == analysis_report
    assert report.protocol.contract_hash == contract.contract_hash
    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False


def test_validation_report_is_deterministic(tmp_path):
    _, _, report_a = _build_validation_artifacts(tmp_path)
    _, _, report_b = _build_validation_artifacts(tmp_path)

    assert report_a.report_hash == report_b.report_hash
    assert report_a.window_summaries == report_b.window_summaries
    assert report_a.summary == report_b.summary


@pytest.mark.parametrize(
    "mutator, error_type",
    [
        (lambda payload: payload.__setitem__("contract", {**payload["contract"], "contract_hash": "0" * 64}), HistoricalFuturesMarketValidationIntegrityError),
        (
            lambda payload: payload["contract"]["temporal_split_protocol"].__setitem__(
                "reference_window",
                {**payload["contract"]["temporal_split_protocol"]["reference_window"], "window_hash": "0" * 64},
            ),
            HistoricalFuturesMarketValidationIntegrityError,
        ),
        (
            lambda payload: payload["contract"]["temporal_split_protocol"].__setitem__(
                "provenance_hash",
                "0" * 64,
            ),
            HistoricalFuturesMarketValidationIntegrityError,
        ),
    ],
)
def test_validation_rejects_tampering(tmp_path, mutator, error_type):
    _, _, report = _build_validation_artifacts(tmp_path)
    payload = report.as_dict()
    mutator(payload)

    with pytest.raises(error_type):
        type(report).from_dict(payload)


def test_validation_rejects_non_contiguous_or_overlapping_windows(tmp_path):
    _, _, report = _build_validation_artifacts(tmp_path)
    payload = report.as_dict()

    payload["contract"]["temporal_split_protocol"]["validation_window"]["start_utc"] = payload["contract"]["temporal_split_protocol"]["reference_window"]["end_utc"]
    with pytest.raises(HistoricalFuturesMarketValidationValidationError):
        type(report).from_dict(payload)

    payload = report.as_dict()
    payload["contract"]["temporal_split_protocol"]["test_window"]["start_utc"] = payload["contract"]["temporal_split_protocol"]["validation_window"]["end_utc"]
    with pytest.raises(HistoricalFuturesMarketValidationValidationError):
        type(report).from_dict(payload)


def test_validation_preserves_research_only_flags(tmp_path):
    _, _, report = _build_validation_artifacts(tmp_path)

    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.contract.historical_research_only is True
    assert report.contract.operational_evidence is False
    assert report.contract.paper_promotion_eligible is False
    assert report.analysis_report.historical_research_only is True
    assert report.analysis_report.operational_evidence is False
    assert report.analysis_report.paper_promotion_eligible is False


def test_validation_summary_covers_reference_validation_and_test(tmp_path):
    _, _, report = _build_validation_artifacts(tmp_path)

    assert tuple(item.window_name for item in report.window_summaries) == (
        "reference",
        "validation",
        "test",
    )
    assert report.summary.window_count == 3
    assert report.summary.decision_count == sum(item.decision_count for item in report.window_summaries)
    assert report.summary.signal_count == sum(item.signal_count for item in report.window_summaries)
    assert report.summary.evaluated_operations == sum(item.evaluated_operations for item in report.window_summaries)
    assert report.summary.no_signal_decisions == sum(item.no_signal_decisions for item in report.window_summaries)
    assert report.summary.not_evaluable_entries == sum(item.not_evaluable_entries for item in report.window_summaries)
    assert report.summary.window_mean_return_spread_percent >= Decimal("0")
    assert report.summary.window_win_rate_spread_percent >= Decimal("0")


def test_validation_persistence_helpers(tmp_path):
    _, analysis_report, report = _build_validation_artifacts(tmp_path)
    path = tmp_path / "validation" / "phase14b.json"

    saved = save_historical_futures_market_validation_report(path, report)
    assert saved.report_hash == report.report_hash

    saved_again = save_historical_futures_market_validation_report(path, report)
    assert saved_again.report_hash == report.report_hash

    loaded = load_historical_futures_market_validation_report(path)
    assert loaded == report

    verified = verify_historical_futures_market_validation_report(path)
    assert verified["verified"] is True
    assert verified["report_hash"] == report.report_hash
    assert verified["classification"] == "historical_research_only"

    status = status_historical_futures_market_validation_report(path)
    assert status["exists"] is True
    assert status["report_hash"] == report.report_hash
    assert status["analysis_report_hash"] == analysis_report.report_hash
    assert status["classification"] == "historical_research_only"

    with pytest.raises(HistoricalFuturesMarketValidationValidationError):
        reject_historical_futures_market_validation_promotion(report)
