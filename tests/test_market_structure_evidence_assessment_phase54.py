from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

import market_data.market_structure_annotation_layer as phase52
import market_data.market_structure_evidence_assessment as phase54
import market_data.market_structure_hypothesis_evaluation as phase53
import market_data.market_structure_research_contract as phase50
import market_data.offline_market_structure_detector as phase51

PHASE54_CREATED_AT_UTC = datetime(2026, 8, 7, 18, 0, 0, tzinfo=timezone.utc)
PHASE54_CREATED_AT_UTC_OFFSET = datetime(2026, 8, 7, 15, 0, 1, tzinfo=timezone(timedelta(hours=-3)))


def _metadata_a() -> dict[str, object]:
    return {
        "labels": {"beta", "alpha"},
        "nested": {
            "flags": {"offline", "research"},
            "groups": {frozenset({"gamma", "delta"})},
        },
        "notes": ["phase54", "offline"],
    }


def _metadata_b() -> dict[str, object]:
    return {
        "notes": ["phase54", "offline"],
        "nested": {
            "groups": {frozenset({"delta", "gamma"})},
            "flags": {"research", "offline"},
        },
        "labels": {"alpha", "beta"},
    }


def _build_contract(*, metadata: dict[str, object] | None = None):
    return phase50.build_market_structure_research_contract(
        created_at_utc=PHASE54_CREATED_AT_UTC,
        metadata=metadata or _metadata_a(),
    )


def _ts(start: datetime, index: int, hours: int = 1) -> datetime:
    return start + timedelta(hours=index * hours)


def _candle(
    timestamp: datetime,
    *,
    open_: int,
    high: int,
    low: int,
    close: int,
    volume: int = 100,
    complete: bool = True,
) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "complete": complete,
    }


def _price_series(prices: list[int], start: datetime, hours: int = 1) -> list[dict[str, object]]:
    return [
        _candle(
            _ts(start, index, hours),
            open_=price - 1,
            high=price + 2,
            low=price - 2,
            close=price,
            volume=100 + index,
        )
        for index, price in enumerate(prices)
    ]


def _build_input(
    candles,
    *,
    candles_by_timeframe=None,
    timeframe: str = "1H",
    symbol: str = "BTC-USDT",
    market: str = "spot",
    provider_name: str = "synthetic",
    dataset_hash: str = "e" * 64,
    metadata: dict[str, object] | None = None,
    created_at_utc: datetime = PHASE54_CREATED_AT_UTC,
):
    return phase51.build_market_structure_detection_input(
        contract=_build_contract(metadata=metadata or _metadata_a()),
        candles=candles,
        candles_by_timeframe=candles_by_timeframe,
        timeframe=timeframe,
        symbol=symbol,
        market=market,
        provider_name=provider_name,
        dataset_hash=dataset_hash,
        created_at_utc=created_at_utc,
        metadata=metadata or _metadata_a(),
    )


def _analysis_input() -> phase51.MarketStructureDetectionInput:
    primary = _price_series(
        [100, 104, 101, 99, 105, 109, 106, 104, 110, 114, 111, 109, 115, 119, 116, 114, 120, 124, 121, 119, 128, 129],
        datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc),
    )
    macro = _price_series(
        [200, 204, 201, 199, 205, 209, 206, 204, 210, 214, 211, 209, 215, 219, 216, 214, 220, 224, 221, 219, 228, 227],
        datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc),
        hours=24,
    )
    intermediate = _price_series(
        [150, 150, 151, 150, 151, 150, 151, 150],
        datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc),
        hours=4,
    )
    candles_by_timeframe = {
        "1D": macro,
        "4H": intermediate,
        "1H": primary,
    }
    return _build_input(
        primary,
        candles_by_timeframe=candles_by_timeframe,
        created_at_utc=PHASE54_CREATED_AT_UTC,
    )


def _analysis_result() -> phase51.MarketStructureDetectionResult:
    return phase51.detect_market_structure(_analysis_input())


def _analysis_collection(*, metadata: dict[str, object] | None = None) -> phase52.MarketStructureAnnotationCollection:
    result = _analysis_result()
    return phase52.annotate_market_structure(
        result,
        metadata=metadata or _metadata_a(),
        created_at_utc=PHASE54_CREATED_AT_UTC,
    )


def _hypothesis_source() -> tuple[
    phase53.MarketStructureHypothesisEvaluation,
    phase53.MarketStructureHypothesis,
    phase53.MarketStructureHypothesis,
    phase53.MarketStructureHypothesis,
]:
    collection = _analysis_collection()
    bullish_annotation = next(
        annotation
        for annotation in collection.annotations
        if annotation.annotation_payload["hypothesis_state"] == "Bullish Continuation"
    )
    base = phase53.build_market_structure_hypothesis(
        annotation=bullish_annotation,
        hypothesis_type="Bullish Continuation",
        metadata=_metadata_a(),
        created_at_utc=PHASE54_CREATED_AT_UTC,
        annotation_collection_hash=collection.collection_hash,
    )
    duplicate = replace(base, hypothesis_id="", hypothesis_hash="")
    redundant = replace(
        base,
        hypothesis_id="",
        hypothesis_hash="",
        hypothesis_type="Accumulation Candidate",
        status="candidate",
    )
    invalidated = replace(
        base,
        hypothesis_id="",
        hypothesis_hash="",
        status="invalidated",
        invalidation_reasons=("manual_invalidation",),
    )
    evaluation = phase53.MarketStructureHypothesisEvaluation(
        schema_version=phase53.MARKET_STRUCTURE_HYPOTHESIS_EVALUATION_SCHEMA_VERSION,
        evaluation_id="",
        evaluation_hash="",
        dataset_hash=base.dataset_hash,
        contract_hash=base.contract_hash,
        detection_result_hash=base.detection_result_hash,
        annotation_collection_hash=base.annotation_collection_hash,
        hypotheses=(base, duplicate, redundant, invalidated),
        ambiguity_state=base.timeframe_context["alignment_state"],
        timeframe_context=base.timeframe_context,
        metadata=_metadata_a(),
        created_at_utc=PHASE54_CREATED_AT_UTC,
    )
    return evaluation, base, redundant, invalidated


def _assessment(
    *,
    created_at_utc: datetime = PHASE54_CREATED_AT_UTC,
    metadata: dict[str, object] | None = None,
):
    evaluation, _, _, _ = _hypothesis_source()
    return phase54.build_market_structure_evidence_assessment(
        evaluation,
        created_at_utc=created_at_utc,
        metadata=metadata or _metadata_a(),
    )


def test_phase54_assessment_is_deterministic_and_deeply_immutable():
    evaluation_a, _, _, _ = _hypothesis_source()
    evaluation_b, _, _, _ = _hypothesis_source()

    assessment_a = phase54.build_market_structure_evidence_assessment(
        evaluation_a,
        created_at_utc=PHASE54_CREATED_AT_UTC,
        metadata=_metadata_a(),
    )
    assessment_b = phase54.build_market_structure_evidence_assessment(
        evaluation_b,
        created_at_utc=PHASE54_CREATED_AT_UTC_OFFSET,
        metadata=_metadata_b(),
    )

    assert assessment_a.lineage_hash == evaluation_a.evaluation_hash
    assert assessment_a.lineage_hash == assessment_b.lineage_hash
    assert assessment_a.assessment_id == assessment_b.assessment_id
    assert assessment_a.assessment_hash == assessment_b.assessment_hash
    assert assessment_a.audit_record_hash == assessment_a.assessment_hash
    assert assessment_a.as_dict()["lineage_hash"] == evaluation_a.evaluation_hash
    assert json.dumps(assessment_a.as_dict(), sort_keys=True, separators=(",", ":"))

    with pytest.raises(TypeError):
        assessment_a.metadata["labels"] = frozenset({"gamma"})  # type: ignore[index]
    with pytest.raises(TypeError):
        assessment_a.metadata["nested"]["flags"] = frozenset({"changed"})  # type: ignore[index]
    with pytest.raises(AttributeError):
        assessment_a.metadata["labels"].add("gamma")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        assessment_a.metadata["nested"]["groups"].add(frozenset({"epsilon"}))  # type: ignore[attr-defined]

    source_metadata = _metadata_a()
    assessment = phase54.build_market_structure_evidence_assessment(
        evaluation_a,
        created_at_utc=PHASE54_CREATED_AT_UTC,
        metadata=source_metadata,
    )
    source_metadata["labels"].add("late")  # type: ignore[attr-defined]
    source_metadata["nested"]["flags"].add("late")  # type: ignore[attr-defined]
    assert assessment.metadata["labels"] == frozenset({"alpha", "beta"})
    assert assessment.metadata["nested"]["flags"] == frozenset({"offline", "research"})


def test_phase54_classifies_provenance_independence_and_family_matrix():
    assessment = _assessment()

    independence_states = {item.independence_state for item in assessment.evidence_items}
    assert {"duplicate", "redundant", "partially_redundant", "independent"}.issubset(independence_states)

    evidence_roles = {item.evidence_role for item in assessment.evidence_items}
    assert {"supporting", "contradicting", "ambiguous", "invalidation", "neutral"}.intersection(evidence_roles)

    observed_families = set(assessment.evidence_matrix)
    assert observed_families
    assert observed_families.issubset(set(phase54.MARKET_STRUCTURE_EVIDENCE_FAMILIES))
    assert all(summary.evidence_ids for summary in assessment.evidence_matrix.values())
    assert observed_families == {"trend", "range", "ambiguity", "timeframe", "invalidation"}
    if "invalidation" in assessment.evidence_matrix:
        assert assessment.evidence_matrix["invalidation"].family_state == "invalidated"

    provenance_states = {group.group_state for group in assessment.provenance_groups}
    assert {"duplicate", "redundant", "partially_redundant", "independent"}.intersection(provenance_states)
    assert all(group.provenance_hash for group in assessment.provenance_groups)

def test_phase54_builds_partial_evidence_matrix_without_empty_families():
    assessment = _assessment()
    single_item = next(iter(assessment.evidence_items))
    single_family = single_item.evidence_family

    partial_assessment = phase54.MarketStructureEvidenceAssessment(
        schema_version=assessment.schema_version,
        assessment_id="",
        assessment_hash="",
        lineage_hash=assessment.lineage_hash,
        hypothesis_evaluation=assessment.hypothesis_evaluation,
        evidence_items=(single_item,),
        provenance_groups=(),
        evidence_matrix={},
        created_at_utc=assessment.created_at_utc,
        historical_research_only=True,
        operational_evidence=False,
        paper_promotion_eligible=False,
        non_operational_declaration=phase54.MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_NON_OPERATIONAL_DECLARATION,
        metadata=assessment.metadata,
    )

    assert set(partial_assessment.evidence_matrix) == {single_family}
    assert partial_assessment.evidence_matrix[single_family].evidence_ids == (single_item.evidence_id,)
    assert all(summary.evidence_ids for summary in partial_assessment.evidence_matrix.values())

    rebuilt = phase54.market_structure_evidence_assessment_from_dict(copy.deepcopy(partial_assessment.as_dict()))
    assert rebuilt.as_dict() == partial_assessment.as_dict()


def test_phase54_allows_empty_evidence_matrix_when_no_evidence_is_available():
    assessment = _assessment()

    empty_assessment = phase54.MarketStructureEvidenceAssessment(
        schema_version=assessment.schema_version,
        assessment_id="",
        assessment_hash="",
        lineage_hash=assessment.lineage_hash,
        hypothesis_evaluation=assessment.hypothesis_evaluation,
        evidence_items=(),
        provenance_groups=(),
        evidence_matrix={},
        created_at_utc=assessment.created_at_utc,
        historical_research_only=True,
        operational_evidence=False,
        paper_promotion_eligible=False,
        non_operational_declaration=phase54.MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_NON_OPERATIONAL_DECLARATION,
        metadata=assessment.metadata,
    )

    assert empty_assessment.evidence_items == ()
    assert empty_assessment.provenance_groups == ()
    assert empty_assessment.evidence_matrix == {}
    assert empty_assessment.as_dict()["evidence_matrix"] == {}

    rebuilt = phase54.market_structure_evidence_assessment_from_dict(copy.deepcopy(empty_assessment.as_dict()))
    assert rebuilt.as_dict() == empty_assessment.as_dict()


def test_phase54_rejects_future_evidence_and_preserves_invalidation_precedence():
    evaluation, base, _, _ = _hypothesis_source()
    future_hypothesis = replace(
        base,
        hypothesis_id="",
        hypothesis_hash="",
        observed_at=PHASE54_CREATED_AT_UTC + timedelta(hours=2),
        effective_at=PHASE54_CREATED_AT_UTC + timedelta(hours=2),
    )
    future_evaluation = phase53.MarketStructureHypothesisEvaluation(
        schema_version=phase53.MARKET_STRUCTURE_HYPOTHESIS_EVALUATION_SCHEMA_VERSION,
        evaluation_id="",
        evaluation_hash="",
        dataset_hash=future_hypothesis.dataset_hash,
        contract_hash=future_hypothesis.contract_hash,
        detection_result_hash=future_hypothesis.detection_result_hash,
        annotation_collection_hash=future_hypothesis.annotation_collection_hash,
        hypotheses=(future_hypothesis,),
        ambiguity_state=future_hypothesis.timeframe_context["alignment_state"],
        timeframe_context=future_hypothesis.timeframe_context,
        metadata=_metadata_a(),
        created_at_utc=PHASE54_CREATED_AT_UTC,
    )

    with pytest.raises(phase54.MarketStructureEvidenceAssessmentValidationError, match="future evidence"):
        phase54.build_market_structure_evidence_assessment(future_evaluation)

    invalidated_hypothesis = replace(base, hypothesis_id="", hypothesis_hash="", status="invalidated", invalidation_reasons=("manual_invalidation",))
    invalidated_evaluation = phase53.MarketStructureHypothesisEvaluation(
        schema_version=phase53.MARKET_STRUCTURE_HYPOTHESIS_EVALUATION_SCHEMA_VERSION,
        evaluation_id="",
        evaluation_hash="",
        dataset_hash=invalidated_hypothesis.dataset_hash,
        contract_hash=invalidated_hypothesis.contract_hash,
        detection_result_hash=invalidated_hypothesis.detection_result_hash,
        annotation_collection_hash=invalidated_hypothesis.annotation_collection_hash,
        hypotheses=(invalidated_hypothesis, evaluation.hypotheses[1]),
        ambiguity_state=invalidated_hypothesis.timeframe_context["alignment_state"],
        timeframe_context=invalidated_hypothesis.timeframe_context,
        metadata=_metadata_a(),
        created_at_utc=PHASE54_CREATED_AT_UTC,
    )
    assessment = phase54.build_market_structure_evidence_assessment(invalidated_evaluation)
    assert assessment.evidence_matrix["invalidation"].family_state == "invalidated"
    assert assessment.evidence_matrix["invalidation"].invalidation_evidence_ids
    assert any(item.evidence_role == "supporting" for item in assessment.evidence_items)
    assert any(item.evidence_role == "invalidation" for item in assessment.evidence_items)


def test_phase54_round_trip_and_no_scoring_or_operation():
    assessment = _assessment()
    payload = copy.deepcopy(assessment.as_dict())
    rebuilt = phase54.market_structure_evidence_assessment_from_dict(payload)

    assert rebuilt.assessment_id == assessment.assessment_id
    assert rebuilt.assessment_hash == assessment.assessment_hash
    assert rebuilt.audit_record_hash == assessment.audit_record_hash
    assert rebuilt.lineage_hash == assessment.lineage_hash
    assert rebuilt.as_dict() == assessment.as_dict()
    assert rebuilt.historical_research_only is True
    assert rebuilt.operational_evidence is False
    assert rebuilt.paper_promotion_eligible is False
    assert rebuilt.non_operational_declaration == phase54.MARKET_STRUCTURE_EVIDENCE_ASSESSMENT_NON_OPERATIONAL_DECLARATION
    assert not hasattr(rebuilt, "score")
    assert not hasattr(rebuilt, "probability")
    assert not hasattr(rebuilt, "ranking")

    contract = _build_contract()
    assert contract.metadata["labels"] == frozenset({"alpha", "beta"})
