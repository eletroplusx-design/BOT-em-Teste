from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from historical_futures_market_research_limitations import (
    HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_PROTOCOL_NAME,
    HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_PROTOCOL_VERSION,
    HistoricalFuturesMarketResearchLimitationsConflictError,
    HistoricalFuturesMarketResearchLimitationsIntegrityError,
    HistoricalFuturesMarketResearchLimitationsPromotionError,
    HistoricalFuturesMarketResearchLimitationsReport,
    HistoricalFuturesMarketResearchLimitationsValidationError,
    HistoricalFuturesMarketResearchLimitation,
    build_historical_futures_market_research_limitations_protocol,
    build_historical_futures_market_research_limitations_report,
    load_historical_futures_market_research_limitations_report,
    reject_historical_futures_market_research_limitations_promotion,
    run_historical_futures_market_research_limitations,
    save_historical_futures_market_research_limitations_report,
    status_historical_futures_market_research_limitations_report,
    verify_historical_futures_market_research_limitations_report,
)
from historical_futures_market_robustness_dossier import (
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_CONSISTENT_OBSERVATION,
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION,
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE,
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE,
    HistoricalFuturesMarketRobustnessCell,
)
from historical_futures_market_temporal_consistency import (
    HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT,
    HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE,
    HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED,
)
from tests.test_historical_futures_market_robustness_dossier_phase15 import _build_robustness_artifacts


def _build_research_limitations_artifacts(tmp_path):
    contract, analysis_report, validation_report, temporal_consistency_report, robustness_report = _build_robustness_artifacts(
        tmp_path
    )
    report = run_historical_futures_market_research_limitations(robustness_report)
    return contract, analysis_report, validation_report, temporal_consistency_report, robustness_report, report


@pytest.fixture(scope="module")
def research_limitations_artifacts(tmp_path_factory):
    return _build_research_limitations_artifacts(tmp_path_factory.mktemp("phase16"))


def _window_templates(temporal_consistency_report):
    return {
        "reference": next(cell for cell in temporal_consistency_report.cells if cell.window_name == "reference"),
        "validation": next(cell for cell in temporal_consistency_report.cells if cell.window_name == "validation"),
        "test": next(cell for cell in temporal_consistency_report.cells if cell.window_name == "test"),
    }


def _synthetic_window_cell(template, *, source_group, status: str, mean: Decimal, median: Decimal, cumulative: Decimal):
    return replace(
        template,
        source_group=source_group,
        decision_count=0 if status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT else 1,
        signal_count=0 if status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT else 1,
        evaluated_operations=0 if status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT else 1,
        no_signal_decisions=0,
        not_evaluable_entries=0,
        no_signal_reason_counts=(),
        not_evaluable_reason_counts=(),
        win_rate_percent=Decimal("100") if status != HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT else Decimal("0"),
        mean_gross_return_percent_without_costs=mean,
        median_gross_return_percent_without_costs=median,
        cumulative_simple_return_percent_without_costs=cumulative,
        max_loss_streak=0,
        max_win_streak=1 if status != HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT else 0,
        status=status,
        sample_warning=None if status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED else "sample note",
        cell_hash="",
    )


def _synthetic_robustness_cell(template_cells, *, source_group, status: str, mean: Decimal, median: Decimal, cumulative: Decimal):
    if status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_CONSISTENT_OBSERVATION:
        note = None
        directional_signatures = ((1, 1, 1), (1, 1, 1), (1, 1, 1))
        window_statuses = (
            HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED,
            HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED,
            HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED,
        )
    elif status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION:
        note = "directional signatures differ across the frozen windows."
        directional_signatures = ((1, 1, 1), (-1, -1, -1), (0, 0, 0))
        window_statuses = (
            HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED,
            HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED,
            HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED,
        )
    elif status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE:
        note = "at least one frozen window is absent."
        directional_signatures = ((0, 0, 0), (1, 1, 1), (1, 1, 1))
        window_statuses = (
            HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT,
            HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED,
            HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED,
        )
    elif status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE:
        note = "at least one frozen window has insufficient sample."
        directional_signatures = ((0, 0, 0), (1, 1, 1), (1, 1, 1))
        window_statuses = (
            HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE,
            HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED,
            HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED,
        )
    else:
        raise AssertionError(status)

    window_cells = (
        _synthetic_window_cell(template_cells["reference"], source_group=source_group, status=window_statuses[0], mean=mean, median=median, cumulative=cumulative),
        _synthetic_window_cell(template_cells["validation"], source_group=source_group, status=window_statuses[1], mean=mean, median=median, cumulative=cumulative),
        _synthetic_window_cell(template_cells["test"], source_group=source_group, status=window_statuses[2], mean=mean, median=median, cumulative=cumulative),
    )

    return HistoricalFuturesMarketRobustnessCell(
        source_group=source_group,
        window_cells=window_cells,
        window_directional_signatures=directional_signatures,
        observed_window_count=sum(1 for item in window_cells if item.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED),
        insufficient_sample_window_count=sum(
            1 for item in window_cells if item.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE
        ),
        absent_window_count=sum(1 for item in window_cells if item.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT),
        status=status,
        limitation_note=note,
        cell_hash="",
    )


def test_research_limitations_round_trip_and_hash_stability(research_limitations_artifacts):
    contract, analysis_report, validation_report, temporal_consistency_report, robustness_report, report = research_limitations_artifacts
    rebuilt = type(report).from_dict(report.as_dict())

    assert report == rebuilt
    assert report.report_hash == rebuilt.report_hash
    assert report.as_dict() == rebuilt.as_dict()
    assert report.robustness_dossier_report == robustness_report
    assert report.robustness_dossier_report.temporal_consistency_report == temporal_consistency_report
    assert report.robustness_dossier_report.temporal_consistency_report.validation_report == validation_report
    assert report.robustness_dossier_report.temporal_consistency_report.validation_report.contract == contract
    assert report.robustness_dossier_report.temporal_consistency_report.validation_report.analysis_report == analysis_report
    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.protocol.robustness_dossier_report_hash == robustness_report.report_hash
    assert report.protocol.protocol_name == HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_PROTOCOL_NAME
    assert report.protocol.protocol_version == HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_PROTOCOL_VERSION


def test_research_limitations_is_deterministic(research_limitations_artifacts):
    _, _, _, _, robustness_report, report_a = research_limitations_artifacts
    report_b = run_historical_futures_market_research_limitations(robustness_report)

    assert report_a.report_hash == report_b.report_hash
    assert report_a.limitations == report_b.limitations
    assert report_a.summary == report_b.summary


def test_research_limitations_covers_reference_validation_and_test(research_limitations_artifacts):
    _, _, _, temporal_consistency_report, _, report = research_limitations_artifacts

    assert tuple(item.window_name for item in report.robustness_dossier_report.window_summaries) == (
        "reference",
        "validation",
        "test",
    )
    assert report.protocol.window_count == 3
    assert report.summary.window_count == 3
    assert report.summary.regime_count == len(report.limitations)
    assert report.summary.limitation_count == len(report.limitations)
    assert report.protocol.regime_count == len(report.limitations)
    assert report.protocol.source_group_hashes == tuple(group.group_hash for group in temporal_consistency_report.validation_report.analysis_report.groups)


def test_research_limitations_classifies_the_four_states(research_limitations_artifacts):
    _, _, _, temporal_consistency_report, _, _ = research_limitations_artifacts
    templates = _window_templates(temporal_consistency_report)
    shared_group = temporal_consistency_report.cells[0].source_group

    observed_cell = _synthetic_robustness_cell(
        templates,
        source_group=shared_group,
        status=HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_CONSISTENT_OBSERVATION,
        mean=Decimal("1"),
        median=Decimal("2"),
        cumulative=Decimal("3"),
    )
    observed_limitation = HistoricalFuturesMarketResearchLimitation(
        robustness_cell=observed_cell,
        status=HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_CONSISTENT_OBSERVATION,
        limitation_note=None,
    )
    assert observed_limitation.limitation_note is None

    divergent_cell = _synthetic_robustness_cell(
        templates,
        source_group=shared_group,
        status=HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION,
        mean=Decimal("1"),
        median=Decimal("2"),
        cumulative=Decimal("3"),
    )
    divergent_limitation = HistoricalFuturesMarketResearchLimitation(
        robustness_cell=divergent_cell,
        status=HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION,
        limitation_note="directional signatures differ across the frozen windows.",
    )
    assert divergent_limitation.limitation_note is not None

    missing_cell = _synthetic_robustness_cell(
        templates,
        source_group=shared_group,
        status=HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE,
        mean=Decimal("0"),
        median=Decimal("0"),
        cumulative=Decimal("0"),
    )
    missing_limitation = HistoricalFuturesMarketResearchLimitation(
        robustness_cell=missing_cell,
        status=HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE,
        limitation_note="at least one frozen window is absent.",
    )
    assert missing_limitation.limitation_note is not None

    insufficient_cell = _synthetic_robustness_cell(
        templates,
        source_group=shared_group,
        status=HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE,
        mean=Decimal("0"),
        median=Decimal("0"),
        cumulative=Decimal("0"),
    )
    insufficient_limitation = HistoricalFuturesMarketResearchLimitation(
        robustness_cell=insufficient_cell,
        status=HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE,
        limitation_note="at least one frozen window has insufficient sample.",
    )
    assert insufficient_limitation.limitation_note is not None


@pytest.mark.parametrize(
    "mutator, error_type",
    [
        (
            lambda payload: payload.__setitem__("robustness_dossier_report", {**payload["robustness_dossier_report"], "report_hash": "0" * 64}),
            HistoricalFuturesMarketResearchLimitationsIntegrityError,
        ),
        (
            lambda payload: payload["protocol"].__setitem__("robustness_dossier_report_hash", "0" * 64),
            HistoricalFuturesMarketResearchLimitationsIntegrityError,
        ),
        (
            lambda payload: payload["protocol"].__setitem__("contract_hash", "0" * 64),
            HistoricalFuturesMarketResearchLimitationsIntegrityError,
        ),
        (
            lambda payload: payload["limitations"][0].__setitem__("limitation_note", "tampered"),
            HistoricalFuturesMarketResearchLimitationsIntegrityError,
        ),
        (
            lambda payload: payload["summary"].__setitem__("noted_regime_count", 999),
            HistoricalFuturesMarketResearchLimitationsIntegrityError,
        ),
        (
            lambda payload: payload.__setitem__("historical_research_only", False),
            HistoricalFuturesMarketResearchLimitationsValidationError,
        ),
        (
            lambda payload: payload["protocol"].__setitem__("unexpected_field", "boom"),
            HistoricalFuturesMarketResearchLimitationsValidationError,
        ),
    ],
)
def test_research_limitations_rejects_tampering(research_limitations_artifacts, mutator, error_type):
    _, _, _, _, _, report = research_limitations_artifacts
    payload = report.as_dict()
    mutator(payload)

    with pytest.raises(error_type):
        type(report).from_dict(payload)


def test_research_limitations_rejects_global_analysis_substitute(research_limitations_artifacts):
    _, analysis_report, _, _, _, _ = research_limitations_artifacts

    with pytest.raises(HistoricalFuturesMarketResearchLimitationsValidationError):
        build_historical_futures_market_research_limitations_report(analysis_report)


def test_research_limitations_preserves_research_only_flags(research_limitations_artifacts):
    _, _, _, _, robustness_report, report = research_limitations_artifacts

    assert report.historical_research_only is True
    assert report.operational_evidence is False
    assert report.paper_promotion_eligible is False
    assert report.protocol.historical_research_only is True
    assert report.protocol.operational_evidence is False
    assert report.protocol.paper_promotion_eligible is False
    assert report.robustness_dossier_report.historical_research_only is True
    assert report.robustness_dossier_report.operational_evidence is False
    assert report.robustness_dossier_report.paper_promotion_eligible is False
    assert report.protocol.robustness_dossier_report_hash == robustness_report.report_hash


def test_research_limitations_persistence_helpers(research_limitations_artifacts, tmp_path):
    _, _, _, _, _, report = research_limitations_artifacts
    path = tmp_path / "research-limitations" / "phase16.json"

    saved = save_historical_futures_market_research_limitations_report(path, report)
    assert saved.report_hash == report.report_hash

    saved_again = save_historical_futures_market_research_limitations_report(path, report)
    assert saved_again.report_hash == report.report_hash

    loaded = load_historical_futures_market_research_limitations_report(path)
    assert loaded == report

    verified = verify_historical_futures_market_research_limitations_report(path)
    assert verified["verified"] is True
    assert verified["report_hash"] == report.report_hash
    assert verified["classification"] == "historical_research_only"

    status = status_historical_futures_market_research_limitations_report(path)
    assert status["exists"] is True
    assert status["report_hash"] == report.report_hash
    assert status["validation_report_hash"] == report.robustness_dossier_report.report_hash
    assert status["classification"] == "historical_research_only"

    with pytest.raises(HistoricalFuturesMarketResearchLimitationsPromotionError):
        reject_historical_futures_market_research_limitations_promotion(report)
