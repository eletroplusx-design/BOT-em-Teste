from __future__ import annotations

from copy import deepcopy

from decimal import Decimal

import pytest

from historical_futures_market_temporal_consistency import (
    HistoricalFuturesMarketTemporalConsistencyIntegrityError,
    HistoricalFuturesMarketTemporalConsistencyValidationError,
    build_historical_futures_market_temporal_consistency_report,
    load_historical_futures_market_temporal_consistency_report,
    reject_historical_futures_market_temporal_consistency_promotion,
    run_historical_futures_market_temporal_consistency,
    save_historical_futures_market_temporal_consistency_report,
    status_historical_futures_market_temporal_consistency_report,
    verify_historical_futures_market_temporal_consistency_report,
)
from tests.test_historical_futures_market_validation_phase14b import _build_validation_artifacts


def _build_temporal_consistency_artifacts(tmp_path):
    contract, analysis_report, validation_report = _build_validation_artifacts(tmp_path)
    report = run_historical_futures_market_temporal_consistency(validation_report)
    return contract, analysis_report, validation_report, report


def test_temporal_consistency_round_trip_and_hash_stability(tmp_path):
    contract, analysis_report, validation_report, report = _build_temporal_consistency_artifacts(tmp_path)
    rebuilt = type(report).from_dict(report.as_dict())

    assert report == rebuilt
    assert report.report_hash == rebuilt.report_hash
    assert report.as_dict() == rebuilt.as_dict()
    assert report.validation_report == validation_report
    assert report.validation_report.contract == contract
    assert report.validation_report.analysis_report == analysis_report
    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False


def test_temporal_consistency_is_deterministic(tmp_path):
    _, _, _, report_a = _build_temporal_consistency_artifacts(tmp_path)
    _, _, _, report_b = _build_temporal_consistency_artifacts(tmp_path)

    assert report_a.report_hash == report_b.report_hash
    assert report_a.cells == report_b.cells
    assert report_a.window_summaries == report_b.window_summaries
    assert report_a.summary == report_b.summary


def test_temporal_consistency_covers_reference_validation_and_test(tmp_path):
    _, _, _, report = _build_temporal_consistency_artifacts(tmp_path)

    assert tuple(item.window_name for item in report.window_summaries) == (
        "reference",
        "validation",
        "test",
    )
    assert report.protocol.window_count == 3
    assert report.summary.window_count == 3
    assert report.summary.regime_count == len(report.validation_report.analysis_report.groups)
    assert report.summary.cell_count == report.summary.regime_count * 3
    assert report.summary.decision_count == sum(item.decision_count for item in report.cells)
    assert report.summary.signal_count == sum(item.signal_count for item in report.cells)
    assert report.summary.evaluated_operations == sum(item.evaluated_operations for item in report.cells)
    assert report.summary.no_signal_decisions == sum(item.no_signal_decisions for item in report.cells)
    assert report.summary.not_evaluable_entries == sum(item.not_evaluable_entries for item in report.cells)


def test_temporal_consistency_distinguishes_absent_and_insufficient_cells(tmp_path):
    _, _, _, report = _build_temporal_consistency_artifacts(tmp_path)

    statuses = {cell.status for cell in report.cells}
    assert "absent" in statuses
    assert "insufficient_sample" in statuses
    assert "observed" in statuses

    absent_cells = [cell for cell in report.cells if cell.status == "absent"]
    insufficient_cells = [cell for cell in report.cells if cell.status == "insufficient_sample"]
    observed_cells = [cell for cell in report.cells if cell.status == "observed"]

    assert all(cell.decision_count == 0 for cell in absent_cells)
    assert all(cell.sample_warning is not None for cell in absent_cells)
    assert all(cell.decision_count > 0 for cell in insufficient_cells)
    assert all(cell.sample_warning is not None for cell in insufficient_cells)
    assert all(cell.sample_warning is None for cell in observed_cells)


@pytest.mark.parametrize(
    "mutator, error_type",
    [
        (lambda payload: payload.__setitem__("validation_report", {**payload["validation_report"], "report_hash": "0" * 64}), HistoricalFuturesMarketTemporalConsistencyIntegrityError),
        (
            lambda payload: payload["validation_report"]["contract"]["temporal_split_protocol"].__setitem__(
                "reference_window",
                {
                    **payload["validation_report"]["contract"]["temporal_split_protocol"]["reference_window"],
                    "window_hash": "0" * 64,
                },
            ),
            HistoricalFuturesMarketTemporalConsistencyIntegrityError,
        ),
        (
            lambda payload: payload["validation_report"]["analysis_report"].__setitem__("report_hash", "0" * 64),
            HistoricalFuturesMarketTemporalConsistencyIntegrityError,
        ),
        (
            lambda payload: payload["cells"][0].__setitem__("sample_warning", "tampered"),
            HistoricalFuturesMarketTemporalConsistencyIntegrityError,
        ),
    ],
)
def test_temporal_consistency_rejects_tampering(tmp_path, mutator, error_type):
    _, _, _, report = _build_temporal_consistency_artifacts(tmp_path)
    payload = report.as_dict()
    mutator(payload)

    with pytest.raises(error_type):
        type(report).from_dict(payload)


def test_temporal_consistency_rejects_unknown_window(tmp_path):
    _, _, _, report = _build_temporal_consistency_artifacts(tmp_path)
    payload = report.as_dict()
    payload["cells"][0]["window_name"] = "walk_forward"

    with pytest.raises(HistoricalFuturesMarketTemporalConsistencyValidationError):
        type(report).from_dict(payload)


def test_temporal_consistency_preserves_research_only_flags(tmp_path):
    _, _, _, report = _build_temporal_consistency_artifacts(tmp_path)

    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.validation_report.historical_research_only is True
    assert report.validation_report.operational_evidence is False
    assert report.validation_report.paper_promotion_eligible is False
    assert report.validation_report.contract.historical_research_only is True
    assert report.validation_report.contract.operational_evidence is False
    assert report.validation_report.contract.paper_promotion_eligible is False
    assert report.validation_report.analysis_report.historical_research_only is True
    assert report.validation_report.analysis_report.operational_evidence is False
    assert report.validation_report.analysis_report.paper_promotion_eligible is False


def test_temporal_consistency_persistence_helpers(tmp_path):
    _, analysis_report, validation_report, report = _build_temporal_consistency_artifacts(tmp_path)
    path = tmp_path / "temporal-consistency" / "phase14c.json"

    saved = save_historical_futures_market_temporal_consistency_report(path, report)
    assert saved.report_hash == report.report_hash

    saved_again = save_historical_futures_market_temporal_consistency_report(path, report)
    assert saved_again.report_hash == report.report_hash

    loaded = load_historical_futures_market_temporal_consistency_report(path)
    assert loaded == report

    verified = verify_historical_futures_market_temporal_consistency_report(path)
    assert verified["verified"] is True
    assert verified["report_hash"] == report.report_hash
    assert verified["classification"] == "historical_research_only"

    status = status_historical_futures_market_temporal_consistency_report(path)
    assert status["exists"] is True
    assert status["report_hash"] == report.report_hash
    assert status["validation_report_hash"] == validation_report.report_hash
    assert status["analysis_report_hash"] == analysis_report.report_hash
    assert status["classification"] == "historical_research_only"

    with pytest.raises(HistoricalFuturesMarketTemporalConsistencyValidationError):
        reject_historical_futures_market_temporal_consistency_promotion(report)
