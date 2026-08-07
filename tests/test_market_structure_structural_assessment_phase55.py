from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import market_data.market_structure_evidence_assessment as phase54
import market_data.market_structure_hypothesis_evaluation as phase53
import market_data.market_structure_structural_assessment as phase55

PHASE55_CREATED_AT_UTC = datetime(2026, 8, 7, 19, 0, 0, tzinfo=timezone.utc)
PHASE55_OBSERVED_AT_UTC = datetime(2026, 8, 7, 18, 0, 0, tzinfo=timezone.utc)
PHASE55_EFFECTIVE_AT_UTC = datetime(2026, 8, 7, 18, 5, 0, tzinfo=timezone.utc)

BASE_TIMEFRAME_CONTEXT = {
    "timeframe": "1H",
    "macro_context": "bullish",
    "intermediate_context": "bullish",
    "micro_context": "bullish",
    "alignment_state": "aligned",
}

DATASET_HASH = "1" * 64
CONTRACT_HASH = "2" * 64
DETECTION_RESULT_HASH = "3" * 64
ANNOTATION_COLLECTION_HASH = "4" * 64


def _assessment_metadata_a() -> dict[str, object]:
    return {
        "labels": {"alpha", "beta"},
        "nested": {
            "groups": {frozenset({"delta", "gamma"})},
            "flags": {"offline", "research"},
        },
        "notes": ["phase55", "offline"],
    }


def _assessment_metadata_b() -> dict[str, object]:
    return {
        "notes": ["phase55", "offline"],
        "nested": {
            "flags": {"research", "offline"},
            "groups": {frozenset({"gamma", "delta"})},
        },
        "labels": {"beta", "alpha"},
    }


def _dimension_metadata_a() -> dict[str, object]:
    return {
        "labels": {"support", "structure"},
        "nested": {
            "groups": {frozenset({"primary", "secondary"})},
        },
    }


def _dimension_metadata_b() -> dict[str, object]:
    return {
        "nested": {
            "groups": {frozenset({"secondary", "primary"})},
        },
        "labels": {"structure", "support"},
    }


def _dimension_summary(
    dimension_name: str,
    dimension_state: str,
    *,
    supporting: tuple[str, ...] = (),
    contradicting: tuple[str, ...] = (),
    ambiguous: tuple[str, ...] = (),
    invalidation: tuple[str, ...] = (),
    neutral: tuple[str, ...] = (),
    provenance: tuple[str, ...] = (),
    metadata: dict[str, object] | None = None,
) -> phase55.MarketStructureStructuralDimensionSummary:
    return phase55.MarketStructureStructuralDimensionSummary(
        dimension_name=dimension_name,
        dimension_state=dimension_state,
        supporting_evidence_ids=supporting,
        contradicting_evidence_ids=contradicting,
        ambiguous_evidence_ids=ambiguous,
        invalidation_evidence_ids=invalidation,
        neutral_evidence_ids=neutral,
        provenance_group_ids=provenance,
        timeframe_context=BASE_TIMEFRAME_CONTEXT,
        ambiguity_reasons=(),
        invalidation_reasons=(),
        metadata=metadata or {},
    )


def _direct_assessment(
    dimension_summaries: dict[str, phase55.MarketStructureStructuralDimensionSummary],
    *,
    metadata: dict[str, object] | None = None,
    created_at_utc: datetime = PHASE55_CREATED_AT_UTC,
) -> phase55.MarketStructureStructuralAssessment:
    return phase55.MarketStructureStructuralAssessment(
        schema_version=phase55.MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_SCHEMA_VERSION,
        assessment_id="",
        assessment_hash="",
        hypothesis_id="5" * 64,
        hypothesis_hash="6" * 64,
        hypothesis_evaluation_hash="7" * 64,
        evidence_assessment_id="8" * 64,
        evidence_assessment_hash="9" * 64,
        dataset_hash=DATASET_HASH,
        contract_hash=CONTRACT_HASH,
        detection_result_hash=DETECTION_RESULT_HASH,
        annotation_collection_hash=ANNOTATION_COLLECTION_HASH,
        dimension_summaries=dimension_summaries,
        structural_state="",
        ambiguity_state="",
        invalidation_state="",
        timeframe_context=BASE_TIMEFRAME_CONTEXT,
        historical_research_only=True,
        operational_evidence=False,
        paper_promotion_eligible=False,
        non_operational_declaration=phase55.MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_NON_OPERATIONAL_DECLARATION,
        metadata=metadata or {},
        created_at_utc=created_at_utc,
    )


def _hypothesis(
    *,
    supporting_event_ids: tuple[str, ...] = ("structure-annotation::valid_bos",),
    contradicting_event_ids: tuple[str, ...] = ("structure-annotation::failed_bos",),
    invalidation_reasons: tuple[str, ...] = (),
    metadata: dict[str, object] | None = None,
    hypothesis_type: str = "Bullish Continuation",
    status: str = "supported",
) -> phase53.MarketStructureHypothesis:
    return phase53.MarketStructureHypothesis(
        schema_version=phase53.MARKET_STRUCTURE_HYPOTHESIS_SCHEMA_VERSION,
        hypothesis_id="",
        hypothesis_hash="",
        hypothesis_type=hypothesis_type,
        status=status,
        dataset_hash=DATASET_HASH,
        contract_hash=CONTRACT_HASH,
        detection_result_hash=DETECTION_RESULT_HASH,
        annotation_collection_hash=ANNOTATION_COLLECTION_HASH,
        timeframe_context=BASE_TIMEFRAME_CONTEXT,
        observed_at=PHASE55_OBSERVED_AT_UTC,
        effective_at=PHASE55_EFFECTIVE_AT_UTC,
        supporting_event_ids=supporting_event_ids,
        supporting_annotation_ids=(),
        contradicting_event_ids=contradicting_event_ids,
        contradicting_annotation_ids=(),
        invalidation_reasons=invalidation_reasons,
        ambiguity_reasons=(),
        metadata=metadata or {},
        created_at_utc=PHASE55_CREATED_AT_UTC,
    )


def _evaluation(
    hypothesis: phase53.MarketStructureHypothesis,
    *,
    metadata: dict[str, object] | None = None,
) -> phase53.MarketStructureHypothesisEvaluation:
    return phase53.MarketStructureHypothesisEvaluation(
        schema_version=phase53.MARKET_STRUCTURE_HYPOTHESIS_EVALUATION_SCHEMA_VERSION,
        evaluation_id="",
        evaluation_hash="",
        dataset_hash=hypothesis.dataset_hash,
        contract_hash=hypothesis.contract_hash,
        detection_result_hash=hypothesis.detection_result_hash,
        annotation_collection_hash=hypothesis.annotation_collection_hash,
        hypotheses=(hypothesis,),
        ambiguity_state=BASE_TIMEFRAME_CONTEXT["alignment_state"],
        timeframe_context=BASE_TIMEFRAME_CONTEXT,
        metadata=metadata or {},
        created_at_utc=PHASE55_CREATED_AT_UTC,
    )


def _pipeline_assessment(
    hypothesis: phase53.MarketStructureHypothesis,
    *,
    metadata: dict[str, object] | None = None,
) -> phase55.MarketStructureStructuralAssessment:
    evaluation = _evaluation(hypothesis, metadata=metadata or _assessment_metadata_a())
    evidence_assessment = phase54.build_market_structure_evidence_assessment(
        evaluation,
        created_at_utc=PHASE55_CREATED_AT_UTC,
        metadata=metadata or _assessment_metadata_a(),
    )
    return phase55.build_market_structure_structural_assessment(
        hypothesis,
        evidence_assessment,
        created_at_utc=PHASE55_CREATED_AT_UTC,
        metadata=metadata or _assessment_metadata_a(),
    )


def test_phase55_structural_assessment_is_deterministic_and_deeply_immutable():
    assessment_a = _direct_assessment(
        {
            "structure": _dimension_summary(
                "structure",
                "supporting",
                supporting=("structure-support-1",),
                provenance=("group-1",),
                metadata=_dimension_metadata_a(),
            ),
            "timeframe": _dimension_summary(
                "timeframe",
                "neutral",
                neutral=("timeframe-neutral-1",),
                provenance=("group-2",),
                metadata={"notes": ["timeframe", "neutral"]},
            ),
        },
        metadata=_assessment_metadata_a(),
    )
    assessment_b = _direct_assessment(
        {
            "timeframe": _dimension_summary(
                "timeframe",
                "neutral",
                neutral=("timeframe-neutral-1",),
                provenance=("group-2",),
                metadata={"notes": ["timeframe", "neutral"]},
            ),
            "structure": _dimension_summary(
                "structure",
                "supporting",
                supporting=("structure-support-1",),
                provenance=("group-1",),
                metadata=_dimension_metadata_b(),
            ),
        },
        metadata=_assessment_metadata_b(),
    )

    assert assessment_a.assessment_id == assessment_b.assessment_id
    assert assessment_a.assessment_hash == assessment_b.assessment_hash
    assert assessment_a.audit_record_hash == assessment_a.assessment_hash
    assert assessment_a.as_dict()["assessment_hash"] == assessment_a.assessment_hash
    assert json.dumps(assessment_a.as_dict(), sort_keys=True, separators=(",", ":"))

    round_tripped = phase55.market_structure_structural_assessment_from_dict(assessment_a.as_dict())
    assert round_tripped.as_dict() == assessment_a.as_dict()
    assert round_tripped.assessment_hash == assessment_a.assessment_hash

    with pytest.raises(TypeError):
        assessment_a.metadata["labels"] = frozenset({"gamma"})  # type: ignore[index]
    with pytest.raises(TypeError):
        assessment_a.dimension_summaries["structure"].metadata["nested"]["groups"] = frozenset({"epsilon"})  # type: ignore[index]
    with pytest.raises(AttributeError):
        assessment_a.metadata["labels"].add("gamma")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        assessment_a.dimension_summaries["structure"].metadata["nested"]["groups"].add(  # type: ignore[attr-defined]
            frozenset({"epsilon"})
        )

    source_metadata = _assessment_metadata_a()
    source_dimension_metadata = _dimension_metadata_a()
    assessment = _direct_assessment(
        {
            "structure": _dimension_summary(
                "structure",
                "supporting",
                supporting=("structure-support-1",),
                provenance=("group-1",),
                metadata=source_dimension_metadata,
            ),
            "timeframe": _dimension_summary(
                "timeframe",
                "neutral",
                neutral=("timeframe-neutral-1",),
                provenance=("group-2",),
            ),
        },
        metadata=source_metadata,
    )
    source_metadata["labels"].add("late")  # type: ignore[attr-defined]
    source_metadata["nested"]["flags"].add("late")  # type: ignore[attr-defined]
    source_dimension_metadata["labels"].add("late")  # type: ignore[attr-defined]
    assert assessment.metadata["labels"] == frozenset({"alpha", "beta"})
    assert assessment.metadata["nested"]["flags"] == frozenset({"offline", "research"})
    assert assessment.dimension_summaries["structure"].metadata["labels"] == frozenset({"support", "structure"})


def test_phase55_build_is_sparse_and_round_trips_through_the_pipeline():
    hypothesis = _hypothesis(
        supporting_event_ids=("structure-annotation::valid_bos",),
        contradicting_event_ids=("structure-annotation::failed_bos",),
    )

    assessment = _pipeline_assessment(hypothesis, metadata=_assessment_metadata_a())

    assert assessment.structural_state == "conflicted"
    assert assessment.dimension_summaries["structure"].dimension_state == "conflicted"
    assert set(assessment.dimension_summaries) == {"structure", "timeframe"}
    assert "range" not in assessment.dimension_summaries
    assert assessment.non_operational_declaration == phase55.MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_NON_OPERATIONAL_DECLARATION
    assert assessment.historical_research_only is True
    assert assessment.operational_evidence is False
    assert assessment.paper_promotion_eligible is False
    assert "score" not in assessment.as_dict()
    assert "confidence" not in assessment.as_dict()
    assert "probability" not in assessment.as_dict()
    assert "signal" not in assessment.as_dict()
    assert "ranking" not in assessment.as_dict()

    round_tripped = phase55.market_structure_structural_assessment_from_dict(assessment.as_dict())
    assert round_tripped.as_dict() == assessment.as_dict()
    assert round_tripped.assessment_hash == assessment.assessment_hash
    assert len(round_tripped.dimension_summaries["structure"].supporting_evidence_ids) == 1
    assert len(round_tripped.dimension_summaries["structure"].contradicting_evidence_ids) == 1
    assert round_tripped.dimension_summaries["structure"].supporting_evidence_ids != round_tripped.dimension_summaries["structure"].contradicting_evidence_ids


def test_phase55_invalidated_state_takes_precedence_over_other_dimension_states():
    hypothesis = _hypothesis(
        supporting_event_ids=("structure-annotation::valid_bos",),
        contradicting_event_ids=("structure-annotation::failed_bos",),
        invalidation_reasons=("manual_invalidation",),
        status="invalidated",
    )

    assessment = _pipeline_assessment(hypothesis, metadata=_assessment_metadata_a())

    assert assessment.structural_state == "invalidated"
    assert assessment.invalidation_state == "present"
    assert "invalidation" in assessment.dimension_summaries
    assert assessment.dimension_summaries["invalidation"].dimension_state == "invalidated"


def test_phase55_build_rejects_hypotheses_not_present_in_the_evidence_assessment():
    hypothesis = _hypothesis(
        supporting_event_ids=("structure-annotation::valid_bos",),
        contradicting_event_ids=(),
    )
    evidence_assessment = phase54.build_market_structure_evidence_assessment(
        _evaluation(hypothesis, metadata=_assessment_metadata_a()),
        created_at_utc=PHASE55_CREATED_AT_UTC,
        metadata=_assessment_metadata_a(),
    )
    other_hypothesis = _hypothesis(
        supporting_event_ids=("structure-annotation::valid_bos", "structure-annotation::breakout"),
        contradicting_event_ids=(),
    )

    with pytest.raises(phase55.MarketStructureStructuralAssessmentValidationError, match="hypothesis is not part of the evidence assessment"):
        phase55.build_market_structure_structural_assessment(
            other_hypothesis,
            evidence_assessment,
            created_at_utc=PHASE55_CREATED_AT_UTC,
            metadata=_assessment_metadata_a(),
        )


def test_phase55_from_dict_rejects_unexpected_fields_and_flag_drift():
    assessment = _direct_assessment(
        {
            "structure": _dimension_summary(
                "structure",
                "supporting",
                supporting=("structure-support-1",),
                provenance=("group-1",),
                metadata=_dimension_metadata_a(),
            ),
        },
        metadata=_assessment_metadata_a(),
    )
    payload = assessment.as_dict()
    payload["unexpected"] = "boom"

    with pytest.raises(phase55.MarketStructureStructuralAssessmentValidationError):
        phase55.market_structure_structural_assessment_from_dict(payload)

    with pytest.raises(phase55.MarketStructureStructuralAssessmentValidationError):
        phase55.MarketStructureStructuralAssessment(
            schema_version=phase55.MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_SCHEMA_VERSION,
            assessment_id="",
            assessment_hash="",
            hypothesis_id="5" * 64,
            hypothesis_hash="6" * 64,
            hypothesis_evaluation_hash="7" * 64,
            evidence_assessment_id="8" * 64,
            evidence_assessment_hash="9" * 64,
            dataset_hash=DATASET_HASH,
            contract_hash=CONTRACT_HASH,
            detection_result_hash=DETECTION_RESULT_HASH,
            annotation_collection_hash=ANNOTATION_COLLECTION_HASH,
            dimension_summaries={
                "structure": _dimension_summary(
                    "structure",
                    "supporting",
                    supporting=("structure-support-1",),
                    provenance=("group-1",),
                ),
            },
            structural_state="",
            ambiguity_state="",
            invalidation_state="",
            timeframe_context=BASE_TIMEFRAME_CONTEXT,
            historical_research_only=False,
            operational_evidence=False,
            paper_promotion_eligible=False,
            non_operational_declaration=phase55.MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_NON_OPERATIONAL_DECLARATION,
            metadata=_assessment_metadata_a(),
            created_at_utc=PHASE55_CREATED_AT_UTC,
        )
