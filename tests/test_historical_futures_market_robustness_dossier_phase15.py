from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from historical_futures_market_robustness_dossier import (
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_CONSISTENT_OBSERVATION,
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION,
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE,
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE,
    HistoricalFuturesMarketRobustnessCell,
    HistoricalFuturesMarketRobustnessDossierIntegrityError,
    HistoricalFuturesMarketRobustnessDossierValidationError,
    build_historical_futures_market_robustness_dossier_report,
    load_historical_futures_market_robustness_dossier_report,
    reject_historical_futures_market_robustness_dossier_promotion,
    run_historical_futures_market_robustness_dossier,
    save_historical_futures_market_robustness_dossier_report,
    status_historical_futures_market_robustness_dossier_report,
    verify_historical_futures_market_robustness_dossier_report,
)
from tests.test_historical_futures_market_temporal_consistency_phase14c import (
    _build_temporal_consistency_artifacts,
)


def _build_robustness_artifacts(tmp_path):
    contract, analysis_report, validation_report, temporal_consistency_report = _build_temporal_consistency_artifacts(tmp_path)
    report = run_historical_futures_market_robustness_dossier(temporal_consistency_report)
    return contract, analysis_report, validation_report, temporal_consistency_report, report


def _window_template_cells(temporal_consistency_report):
    templates = {}
    for window_name in ("reference", "validation", "test"):
        templates[window_name] = next(cell for cell in temporal_consistency_report.cells if cell.window_name == window_name)
    return templates


def _synthetic_observed_cell(template, *, source_group, mean: Decimal, median: Decimal, cumulative: Decimal):
    return replace(
        template,
        source_group=source_group,
        decision_count=1,
        signal_count=1,
        evaluated_operations=1,
        no_signal_decisions=0,
        not_evaluable_entries=0,
        no_signal_reason_counts=(),
        not_evaluable_reason_counts=(),
        win_rate_percent=Decimal("100"),
        mean_gross_return_percent_without_costs=mean,
        median_gross_return_percent_without_costs=median,
        cumulative_simple_return_percent_without_costs=cumulative,
        max_loss_streak=0,
        max_win_streak=1,
        status="observed",
        sample_warning=None,
        cell_hash="",
    )


def _synthetic_absent_cell(template, *, source_group):
    return replace(
        template,
        source_group=source_group,
        decision_count=0,
        signal_count=0,
        evaluated_operations=0,
        no_signal_decisions=0,
        not_evaluable_entries=0,
        no_signal_reason_counts=(),
        not_evaluable_reason_counts=(),
        win_rate_percent=Decimal("0"),
        mean_gross_return_percent_without_costs=Decimal("0"),
        median_gross_return_percent_without_costs=Decimal("0"),
        cumulative_simple_return_percent_without_costs=Decimal("0"),
        max_loss_streak=0,
        max_win_streak=0,
        status="absent",
        sample_warning="no observations matched this fixed analytical cut.",
        cell_hash="",
    )


def _synthetic_insufficient_cell(template, *, source_group):
    return replace(
        template,
        source_group=source_group,
        decision_count=1,
        signal_count=1,
        evaluated_operations=1,
        no_signal_decisions=0,
        not_evaluable_entries=0,
        no_signal_reason_counts=(),
        not_evaluable_reason_counts=(),
        win_rate_percent=Decimal("100"),
        mean_gross_return_percent_without_costs=Decimal("0"),
        median_gross_return_percent_without_costs=Decimal("0"),
        cumulative_simple_return_percent_without_costs=Decimal("0"),
        max_loss_streak=0,
        max_win_streak=0,
        status="insufficient_sample",
        sample_warning="sample size is small.",
        cell_hash="",
    )


def test_robustness_round_trip_and_hash_stability(tmp_path):
    contract, analysis_report, validation_report, temporal_consistency_report, report = _build_robustness_artifacts(tmp_path)
    rebuilt = type(report).from_dict(report.as_dict())

    assert report == rebuilt
    assert report.report_hash == rebuilt.report_hash
    assert report.as_dict() == rebuilt.as_dict()
    assert report.temporal_consistency_report == temporal_consistency_report
    assert report.temporal_consistency_report.validation_report == validation_report
    assert report.temporal_consistency_report.validation_report.contract == contract
    assert report.temporal_consistency_report.validation_report.analysis_report == analysis_report
    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.protocol.validation_report_hash == temporal_consistency_report.report_hash


def test_robustness_is_deterministic(tmp_path):
    _, _, _, _, report_a = _build_robustness_artifacts(tmp_path)
    _, _, _, _, report_b = _build_robustness_artifacts(tmp_path)

    assert report_a.report_hash == report_b.report_hash
    assert report_a.cells == report_b.cells
    assert report_a.window_summaries == report_b.window_summaries
    assert report_a.summary == report_b.summary


def test_robustness_covers_reference_validation_and_test(tmp_path):
    _, _, _, temporal_consistency_report, report = _build_robustness_artifacts(tmp_path)

    assert tuple(item.window_name for item in report.window_summaries) == ("reference", "validation", "test")
    assert report.protocol.window_count == 3
    assert report.summary.window_count == 3
    assert report.summary.regime_count == len(temporal_consistency_report.validation_report.analysis_report.groups)
    assert report.summary.matrix_cell_count == len(report.cells) * 3
    assert report.summary.decision_count == sum(item.decision_count for item in report.window_summaries)
    assert report.summary.signal_count == sum(item.signal_count for item in report.window_summaries)
    assert report.summary.evaluated_operations == sum(item.evaluated_operations for item in report.window_summaries)
    assert report.summary.no_signal_decisions == sum(item.no_signal_decisions for item in report.window_summaries)
    assert report.summary.not_evaluable_entries == sum(item.not_evaluable_entries for item in report.window_summaries)
    assert report.summary.comparable_regime_count == (
        report.summary.consistent_observation_regime_count + report.summary.divergent_observation_regime_count
    )


def test_robustness_classifies_the_four_states(tmp_path):
    _, _, _, temporal_consistency_report, _ = _build_robustness_artifacts(tmp_path)
    templates = _window_template_cells(temporal_consistency_report)
    shared_group = temporal_consistency_report.cells[0].source_group

    consistent_cell = HistoricalFuturesMarketRobustnessCell(
        source_group=shared_group,
        window_cells=(
            _synthetic_observed_cell(templates["reference"], source_group=shared_group, mean=Decimal("1"), median=Decimal("2"), cumulative=Decimal("3")),
            _synthetic_observed_cell(templates["validation"], source_group=shared_group, mean=Decimal("4"), median=Decimal("5"), cumulative=Decimal("6")),
            _synthetic_observed_cell(templates["test"], source_group=shared_group, mean=Decimal("7"), median=Decimal("8"), cumulative=Decimal("9")),
        ),
        window_directional_signatures=((1, 1, 1), (1, 1, 1), (1, 1, 1)),
        observed_window_count=3,
        insufficient_sample_window_count=0,
        absent_window_count=0,
        status=HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_CONSISTENT_OBSERVATION,
        limitation_note=None,
    )
    assert consistent_cell.status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_CONSISTENT_OBSERVATION
    assert consistent_cell.limitation_note is None

    divergent_cell = HistoricalFuturesMarketRobustnessCell(
        source_group=shared_group,
        window_cells=(
            _synthetic_observed_cell(templates["reference"], source_group=shared_group, mean=Decimal("1"), median=Decimal("2"), cumulative=Decimal("3")),
            _synthetic_observed_cell(templates["validation"], source_group=shared_group, mean=Decimal("-4"), median=Decimal("-5"), cumulative=Decimal("-6")),
            _synthetic_observed_cell(templates["test"], source_group=shared_group, mean=Decimal("0"), median=Decimal("0"), cumulative=Decimal("0")),
        ),
        window_directional_signatures=((1, 1, 1), (-1, -1, -1), (0, 0, 0)),
        observed_window_count=3,
        insufficient_sample_window_count=0,
        absent_window_count=0,
        status=HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION,
        limitation_note="directional signatures differ across the frozen windows.",
    )
    assert divergent_cell.status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION
    assert divergent_cell.limitation_note is not None

    missing_cells = (
        _synthetic_absent_cell(templates["reference"], source_group=shared_group),
        _synthetic_observed_cell(templates["validation"], source_group=shared_group, mean=Decimal("1"), median=Decimal("1"), cumulative=Decimal("1")),
        _synthetic_observed_cell(templates["test"], source_group=shared_group, mean=Decimal("1"), median=Decimal("1"), cumulative=Decimal("1")),
    )
    missing_row = HistoricalFuturesMarketRobustnessCell(
        source_group=missing_cells[0].source_group,
        window_cells=missing_cells,
        window_directional_signatures=tuple(
            tuple(
                0 if value == 0 else 1 if value > 0 else -1
                for value in (
                    cell.mean_gross_return_percent_without_costs,
                    cell.median_gross_return_percent_without_costs,
                    cell.cumulative_simple_return_percent_without_costs,
                )
            )
            for cell in missing_cells
        ),
        observed_window_count=sum(1 for cell in missing_cells if cell.status == "observed"),
        insufficient_sample_window_count=sum(1 for cell in missing_cells if cell.status == "insufficient_sample"),
        absent_window_count=sum(1 for cell in missing_cells if cell.status == "absent"),
        status=HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE,
        limitation_note="at least one frozen window is absent.",
    )
    assert missing_row.status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE

    insufficient_cells = (
        _synthetic_insufficient_cell(templates["reference"], source_group=shared_group),
        _synthetic_observed_cell(templates["validation"], source_group=shared_group, mean=Decimal("1"), median=Decimal("1"), cumulative=Decimal("1")),
        _synthetic_observed_cell(templates["test"], source_group=shared_group, mean=Decimal("1"), median=Decimal("1"), cumulative=Decimal("1")),
    )
    insufficient_row = HistoricalFuturesMarketRobustnessCell(
        source_group=insufficient_cells[0].source_group,
        window_cells=insufficient_cells,
        window_directional_signatures=tuple(
            tuple(
                0 if value == 0 else 1 if value > 0 else -1
                for value in (
                    cell.mean_gross_return_percent_without_costs,
                    cell.median_gross_return_percent_without_costs,
                    cell.cumulative_simple_return_percent_without_costs,
                )
            )
            for cell in insufficient_cells
        ),
        observed_window_count=sum(1 for cell in insufficient_cells if cell.status == "observed"),
        insufficient_sample_window_count=sum(1 for cell in insufficient_cells if cell.status == "insufficient_sample"),
        absent_window_count=sum(1 for cell in insufficient_cells if cell.status == "absent"),
        status=HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE,
        limitation_note="at least one frozen window has insufficient sample.",
    )
    assert insufficient_row.status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize(
    "mutator, error_type",
    [
        (
            lambda payload: payload.__setitem__("temporal_consistency_report", {**payload["temporal_consistency_report"], "report_hash": "0" * 64}),
            HistoricalFuturesMarketRobustnessDossierIntegrityError,
        ),
        (
            lambda payload: payload["protocol"].__setitem__("validation_report_hash", "0" * 64),
            HistoricalFuturesMarketRobustnessDossierIntegrityError,
        ),
        (
            lambda payload: payload["protocol"].__setitem__("source_group_hashes", list(payload["protocol"]["source_group_hashes"]) + ["0" * 64]),
            HistoricalFuturesMarketRobustnessDossierValidationError,
        ),
        (
            lambda payload: payload["cells"][0]["window_cells"][0].__setitem__("window_hash", "0" * 64),
            HistoricalFuturesMarketRobustnessDossierIntegrityError,
        ),
        (
            lambda payload: payload["cells"][0].__setitem__("window_directional_signatures", [[1, 1, 1], [1, 1, 1], [1, 1, 0]]),
            HistoricalFuturesMarketRobustnessDossierValidationError,
        ),
        (
            lambda payload: payload["summary"].__setitem__("matrix_cell_count", 999),
            HistoricalFuturesMarketRobustnessDossierIntegrityError,
        ),
        (
            lambda payload: payload["protocol"].__setitem__("unexpected_field", "boom"),
            HistoricalFuturesMarketRobustnessDossierValidationError,
        ),
    ],
)
def test_robustness_rejects_tampering(tmp_path, mutator, error_type):
    _, _, _, _, report = _build_robustness_artifacts(tmp_path)
    payload = report.as_dict()
    mutator(payload)

    with pytest.raises(error_type):
        type(report).from_dict(payload)


def test_robustness_rejects_unknown_window(tmp_path):
    _, _, _, _, report = _build_robustness_artifacts(tmp_path)
    payload = report.as_dict()
    payload["cells"][0]["window_cells"][0]["window_name"] = "walk_forward"

    with pytest.raises(HistoricalFuturesMarketRobustnessDossierValidationError):
        type(report).from_dict(payload)


def test_robustness_preserves_research_only_flags(tmp_path):
    _, _, _, temporal_consistency_report, report = _build_robustness_artifacts(tmp_path)

    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.protocol.historical_research_only is True
    assert report.protocol.operational_evidence is False
    assert report.protocol.paper_promotion_eligible is False
    assert report.temporal_consistency_report.historical_research_only is True
    assert report.temporal_consistency_report.operational_evidence is False
    assert report.temporal_consistency_report.paper_promotion_eligible is False
    assert report.protocol.validation_report_hash == temporal_consistency_report.report_hash


def test_robustness_persistence_helpers(tmp_path):
    _, analysis_report, validation_report, temporal_consistency_report, report = _build_robustness_artifacts(tmp_path)
    path = tmp_path / "robustness" / "phase15.json"

    saved = save_historical_futures_market_robustness_dossier_report(path, report)
    assert saved.report_hash == report.report_hash

    saved_again = save_historical_futures_market_robustness_dossier_report(path, report)
    assert saved_again.report_hash == report.report_hash

    loaded = load_historical_futures_market_robustness_dossier_report(path)
    assert loaded == report

    verified = verify_historical_futures_market_robustness_dossier_report(path)
    assert verified["verified"] is True
    assert verified["report_hash"] == report.report_hash
    assert verified["classification"] == "historical_research_only"

    status = status_historical_futures_market_robustness_dossier_report(path)
    assert status["exists"] is True
    assert status["report_hash"] == report.report_hash
    assert status["validation_report_hash"] == temporal_consistency_report.report_hash
    assert status["analysis_report_hash"] == analysis_report.report_hash
    assert status["classification"] == "historical_research_only"

    with pytest.raises(HistoricalFuturesMarketRobustnessDossierValidationError):
        reject_historical_futures_market_robustness_dossier_promotion(report)


def test_robustness_rejects_non_temporal_consistency_input(tmp_path):
    _, analysis_report, _, _, _ = _build_robustness_artifacts(tmp_path)

    with pytest.raises(HistoricalFuturesMarketRobustnessDossierValidationError):
        build_historical_futures_market_robustness_dossier_report(analysis_report)
