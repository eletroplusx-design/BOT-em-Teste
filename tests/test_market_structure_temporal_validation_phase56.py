from __future__ import annotations

import copy
import inspect
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

import market_data.market_structure_structural_assessment as phase55
import market_data.market_structure_temporal_validation as phase56

PHASE56_CREATED_AT_UTC = datetime(2026, 8, 7, 20, 0, 0, tzinfo=timezone.utc)
PHASE56_CREATED_AT_UTC_OFFSET = datetime(2026, 8, 7, 17, 0, 1, tzinfo=timezone(timedelta(hours=-3)))

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
HYPOTHESIS_ID = "5" * 64
HYPOTHESIS_HASH = "6" * 64
HYPOTHESIS_ID_ALT = "7" * 64
HYPOTHESIS_HASH_ALT = "8" * 64


def _transition_metadata_a() -> dict[str, object]:
    return {
        "labels": {"alpha", "beta"},
        "nested": {
            "flags": {"offline", "research"},
            "groups": {frozenset({"delta", "gamma"})},
        },
        "notes": ["phase56", "offline"],
    }


def _transition_metadata_b() -> dict[str, object]:
    return {
        "notes": ["phase56", "offline"],
        "nested": {
            "groups": {frozenset({"gamma", "delta"})},
            "flags": {"research", "offline"},
        },
        "labels": {"beta", "alpha"},
    }


def _transition_metadata_c() -> dict[str, object]:
    metadata = _transition_metadata_a()
    metadata["labels"].add("gamma")  # type: ignore[attr-defined]
    return metadata


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


def _dimension_metadata_c() -> dict[str, object]:
    metadata = _dimension_metadata_a()
    metadata["labels"].add("evidence")  # type: ignore[attr-defined]
    return metadata


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


def _assessment(
    *,
    structure_summary: dict[str, object],
    timeframe_summary: dict[str, object],
    hypothesis_id: str = HYPOTHESIS_ID,
    hypothesis_hash: str = HYPOTHESIS_HASH,
    dataset_hash: str = DATASET_HASH,
    contract_hash: str = CONTRACT_HASH,
    detection_result_hash: str = DETECTION_RESULT_HASH,
    annotation_collection_hash: str = ANNOTATION_COLLECTION_HASH,
    created_at_utc: datetime = PHASE56_CREATED_AT_UTC,
    metadata: dict[str, object] | None = None,
) -> phase55.MarketStructureStructuralAssessment:
    return phase55.MarketStructureStructuralAssessment(
        schema_version=phase55.MARKET_STRUCTURE_STRUCTURAL_ASSESSMENT_SCHEMA_VERSION,
        assessment_id="",
        assessment_hash="",
        hypothesis_id=hypothesis_id,
        hypothesis_hash=hypothesis_hash,
        hypothesis_evaluation_hash="7" * 64,
        evidence_assessment_id="8" * 64,
        evidence_assessment_hash="9" * 64,
        dataset_hash=dataset_hash,
        contract_hash=contract_hash,
        detection_result_hash=detection_result_hash,
        annotation_collection_hash=annotation_collection_hash,
        dimension_summaries={
            "structure": _dimension_summary("structure", **structure_summary),
            "timeframe": _dimension_summary("timeframe", **timeframe_summary),
        },
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


def _transition(
    previous: phase55.MarketStructureStructuralAssessment,
    current: phase55.MarketStructureStructuralAssessment,
    *,
    metadata: dict[str, object] | None = None,
    created_at_utc: datetime | None = None,
) -> phase56.MarketStructureStructuralAssessmentTransition:
    return phase56.build_market_structure_structural_assessment_transition(
        previous,
        current,
        metadata=metadata or _transition_metadata_a(),
        created_at_utc=created_at_utc,
    )


def _supported_assessment(
    *,
    created_at_utc: datetime = PHASE56_CREATED_AT_UTC,
    metadata: dict[str, object] | None = None,
    **overrides: object,
):
    params = {
        "structure_summary": {
            "dimension_state": "supporting",
            "supporting": ("structure-support-1",),
            "provenance": ("structure-group-1",),
            "metadata": _dimension_metadata_a(),
        },
        "timeframe_summary": {
            "dimension_state": "neutral",
            "neutral": ("timeframe-neutral-1",),
            "provenance": ("timeframe-group-1",),
            "metadata": _dimension_metadata_b(),
        },
        "created_at_utc": created_at_utc,
        "metadata": metadata or _transition_metadata_a(),
    }
    params.update(overrides)
    return _assessment(**params)


def _conflicted_assessment(*, created_at_utc: datetime = PHASE56_CREATED_AT_UTC, metadata: dict[str, object] | None = None):
    params = {
        "structure_summary": {
            "dimension_state": "conflicted",
            "supporting": ("structure-support-1",),
            "contradicting": ("structure-contradict-1",),
            "provenance": ("structure-group-1",),
            "metadata": _dimension_metadata_a(),
        },
        "timeframe_summary": {
            "dimension_state": "neutral",
            "neutral": ("timeframe-neutral-1",),
            "provenance": ("timeframe-group-1",),
            "metadata": _dimension_metadata_b(),
        },
        "created_at_utc": created_at_utc,
        "metadata": metadata or _transition_metadata_a(),
    }
    return _assessment(**params)


def _invalidated_assessment(
    *,
    created_at_utc: datetime = PHASE56_CREATED_AT_UTC,
    metadata: dict[str, object] | None = None,
):
    params = {
        "structure_summary": {
            "dimension_state": "invalidated",
            "invalidation": ("structure-invalid-1",),
            "provenance": ("structure-group-1",),
            "metadata": _dimension_metadata_a(),
        },
        "timeframe_summary": {
            "dimension_state": "neutral",
            "neutral": ("timeframe-neutral-1",),
            "provenance": ("timeframe-group-1",),
            "metadata": _dimension_metadata_b(),
        },
        "created_at_utc": created_at_utc,
        "metadata": metadata or _transition_metadata_a(),
    }
    return _assessment(**params)


def _ambiguous_assessment(*, created_at_utc: datetime = PHASE56_CREATED_AT_UTC, metadata: dict[str, object] | None = None):
    params = {
        "structure_summary": {
            "dimension_state": "ambiguous",
            "ambiguous": ("structure-ambiguous-1",),
            "provenance": ("structure-group-1",),
            "metadata": _dimension_metadata_a(),
        },
        "timeframe_summary": {
            "dimension_state": "neutral",
            "neutral": ("timeframe-neutral-1",),
            "provenance": ("timeframe-group-1",),
            "metadata": _dimension_metadata_b(),
        },
        "created_at_utc": created_at_utc,
        "metadata": metadata or _transition_metadata_a(),
    }
    return _assessment(**params)


def _indeterminate_assessment(
    *,
    created_at_utc: datetime = PHASE56_CREATED_AT_UTC,
    metadata: dict[str, object] | None = None,
):
    params = {
        "structure_summary": {
            "dimension_state": "indeterminate",
            "neutral": ("structure-neutral-1",),
            "provenance": ("structure-group-1",),
            "metadata": _dimension_metadata_a(),
        },
        "timeframe_summary": {
            "dimension_state": "neutral",
            "neutral": ("timeframe-neutral-1",),
            "provenance": ("timeframe-group-1",),
            "metadata": _dimension_metadata_b(),
        },
        "created_at_utc": created_at_utc,
        "metadata": metadata or _transition_metadata_a(),
    }
    return _assessment(**params)


def _assessment_with_timeframe_variant(
    *,
    created_at_utc: datetime = PHASE56_CREATED_AT_UTC,
    metadata: dict[str, object] | None = None,
) -> phase55.MarketStructureStructuralAssessment:
    return _assessment(
        structure_summary={
            "dimension_state": "supporting",
            "supporting": ("structure-support-1",),
            "provenance": ("structure-group-1",),
            "metadata": _dimension_metadata_c(),
        },
        timeframe_summary={
            "dimension_state": "neutral",
            "neutral": ("timeframe-neutral-2",),
            "provenance": ("timeframe-group-2",),
            "metadata": _dimension_metadata_a(),
        },
        created_at_utc=created_at_utc,
        metadata=metadata or _transition_metadata_b(),
    )


def test_phase56_transition_is_deterministic_and_deeply_immutable():
    previous_a = _supported_assessment(metadata=_transition_metadata_a())
    current_a = _supported_assessment(metadata=_transition_metadata_a())
    previous_b = _supported_assessment(metadata=_transition_metadata_b())
    current_b = _supported_assessment(metadata=_transition_metadata_b())

    transition_a = _transition(
        previous_a,
        current_a,
        metadata=_transition_metadata_a(),
        created_at_utc=PHASE56_CREATED_AT_UTC,
    )
    transition_b = _transition(
        previous_b,
        current_b,
        metadata=_transition_metadata_b(),
        created_at_utc=PHASE56_CREATED_AT_UTC_OFFSET,
    )

    assert transition_a.transition_id == transition_b.transition_id
    assert transition_a.transition_hash == transition_b.transition_hash
    assert transition_a.transition_type == "no_change"
    assert transition_a.changed_dimensions == ()
    assert transition_a.transition_reasons == ("materially_equivalent", "same_timestamp")
    assert transition_a.created_at_utc == PHASE56_CREATED_AT_UTC
    assert transition_b.created_at_utc == PHASE56_CREATED_AT_UTC_OFFSET.astimezone(timezone.utc)
    assert transition_a.as_dict()["transition_hash"] == transition_a.transition_hash
    assert transition_a.as_dict()["metadata"]["nested"]["groups"] == [["delta", "gamma"]]
    assert json.dumps(transition_a.as_dict(), sort_keys=True, separators=(",", ":"))

    round_tripped = phase56.market_structure_structural_assessment_transition_from_dict(transition_a.as_dict())
    assert round_tripped.as_dict() == transition_a.as_dict()
    assert round_tripped.transition_hash == transition_a.transition_hash
    assert phase56.verify_market_structure_structural_assessment_transition(round_tripped) is round_tripped

    with pytest.raises(TypeError):
        transition_a.metadata["labels"] = frozenset({"gamma"})  # type: ignore[index]
    with pytest.raises(TypeError):
        transition_a.metadata["nested"]["groups"] = frozenset({frozenset({"epsilon", "zeta"})})  # type: ignore[index]
    with pytest.raises(AttributeError):
        transition_a.metadata["labels"].add("gamma")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        transition_a.metadata["nested"]["groups"].add(frozenset({"epsilon", "zeta"}))  # type: ignore[attr-defined]

    source_metadata = _transition_metadata_a()
    transition = _transition(
        previous_a,
        current_a,
        metadata=source_metadata,
        created_at_utc=PHASE56_CREATED_AT_UTC,
    )
    source_metadata["labels"].add("late")  # type: ignore[attr-defined]
    source_metadata["nested"]["flags"].add("late")  # type: ignore[attr-defined]
    assert transition.metadata["labels"] == frozenset({"alpha", "beta"})
    assert transition.metadata["nested"]["flags"] == frozenset({"offline", "research"})
    assert phase56.MARKET_STRUCTURE_TEMPORAL_VALIDATION_NON_OPERATIONAL_DECLARATION.startswith(
        "This temporal structural validation is research-only"
    )
    assert "requests" not in phase56.__dict__
    assert "subprocess" not in phase56.__dict__
    assert "multiprocessing" not in phase56.__dict__
    assert "threading" not in phase56.__dict__
    assert "aiohttp" not in phase56.__dict__
    assert "websocket" not in phase56.__dict__


def test_phase56_created_at_utc_is_outside_the_identity_and_round_trips():
    previous = _supported_assessment()
    current = _supported_assessment(created_at_utc=PHASE56_CREATED_AT_UTC + timedelta(minutes=5))

    transition_a = _transition(
        previous,
        current,
        created_at_utc=PHASE56_CREATED_AT_UTC,
    )
    transition_b = _transition(
        previous,
        current,
        created_at_utc=PHASE56_CREATED_AT_UTC_OFFSET,
    )

    assert transition_a.transition_id == transition_b.transition_id
    assert transition_a.transition_hash == transition_b.transition_hash
    assert transition_a.created_at_utc != transition_b.created_at_utc
    assert transition_a.effective_at == current.created_at_utc
    assert transition_a.as_dict()["created_at_utc"] != transition_b.as_dict()["created_at_utc"]


@pytest.mark.parametrize(
    ("previous_factory", "current_factory", "expected_type"),
    [
        (_supported_assessment, _conflicted_assessment, "state_change"),
        (_conflicted_assessment, _supported_assessment, "state_change"),
        (_supported_assessment, _invalidated_assessment, "invalidation"),
        (_indeterminate_assessment, _supported_assessment, "state_change"),
        (_ambiguous_assessment, _supported_assessment, "state_change"),
        (_supported_assessment, _ambiguous_assessment, "state_change"),
    ],
)
def test_phase56_transition_classification_accepts_valid_state_transitions(
    previous_factory,
    current_factory,
    expected_type,
):
    previous = previous_factory()
    current = current_factory(created_at_utc=previous.created_at_utc + timedelta(minutes=1))

    transition = _transition(previous, current)

    assert transition.transition_type == expected_type
    assert transition.transition_hash == phase56.verify_market_structure_structural_assessment_transition(transition).transition_hash
    assert transition.previous_structural_state == previous.structural_state
    assert transition.current_structural_state == current.structural_state
    assert transition.as_dict()["transition_type"] == expected_type


def test_phase56_transition_detects_dimension_changes_in_canonical_order():
    previous = _supported_assessment(created_at_utc=PHASE56_CREATED_AT_UTC)
    current = _assessment_with_timeframe_variant(
        created_at_utc=PHASE56_CREATED_AT_UTC + timedelta(minutes=2),
    )

    transition = _transition(previous, current, metadata=_transition_metadata_b())

    assert transition.transition_type == "dimension_change"
    assert transition.changed_dimensions == ("structure", "timeframe")
    assert transition.transition_reasons == tuple(sorted(set(transition.transition_reasons)))
    assert "metadata_changed:structure" in transition.transition_reasons
    assert "neutral_evidence_changed:timeframe" in transition.transition_reasons
    assert "provenance_changed:timeframe" in transition.transition_reasons


def test_phase56_transition_rejects_timestamp_regression_and_same_timestamp_drift():
    previous = _supported_assessment(created_at_utc=PHASE56_CREATED_AT_UTC)

    with pytest.raises(phase56.MarketStructureTemporalValidationValidationError, match="timestamp regression"):
        _transition(
            previous,
            _supported_assessment(created_at_utc=PHASE56_CREATED_AT_UTC - timedelta(minutes=1)),
        )

    with pytest.raises(phase56.MarketStructureTemporalValidationValidationError, match="same timestamp"):
        _transition(
            previous,
            _assessment_with_timeframe_variant(created_at_utc=PHASE56_CREATED_AT_UTC),
        )


def test_phase56_transition_rejects_invalidated_resurrection():
    previous = _invalidated_assessment(created_at_utc=PHASE56_CREATED_AT_UTC)
    current = _supported_assessment(created_at_utc=PHASE56_CREATED_AT_UTC + timedelta(minutes=1))

    with pytest.raises(
        phase56.MarketStructureTemporalValidationValidationError,
        match="invalidated structural assessments cannot silently resurrect",
    ):
        _transition(previous, current)


@pytest.mark.parametrize(
    ("field_name", "previous_factory", "current_factory", "message"),
    [
        ("hypothesis_id", _supported_assessment, lambda **kwargs: _supported_assessment(hypothesis_id=HYPOTHESIS_ID_ALT, hypothesis_hash=HYPOTHESIS_HASH_ALT, **kwargs), "cross-hypothesis"),
        ("dataset_hash", _supported_assessment, lambda **kwargs: _supported_assessment(dataset_hash="a" * 64, **kwargs), "cross-dataset"),
        ("contract_hash", _supported_assessment, lambda **kwargs: _supported_assessment(contract_hash="b" * 64, **kwargs), "cross-contract"),
        ("detection_result_hash", _supported_assessment, lambda **kwargs: _supported_assessment(detection_result_hash="c" * 64, **kwargs), "cross-detection-result"),
        ("annotation_collection_hash", _supported_assessment, lambda **kwargs: _supported_assessment(annotation_collection_hash="d" * 64, **kwargs), "cross-annotation-collection"),
    ],
)
def test_phase56_transition_rejects_cross_domain_transitions(
    field_name,
    previous_factory,
    current_factory,
    message,
):
    previous = previous_factory()
    current = current_factory(created_at_utc=previous.created_at_utc + timedelta(minutes=1))

    with pytest.raises(phase56.MarketStructureTemporalValidationValidationError, match=message):
        _transition(previous, current)


def test_phase56_transition_rejects_corrupted_hashes():
    previous = _supported_assessment()
    current = _supported_assessment(created_at_utc=previous.created_at_utc + timedelta(minutes=1))
    transition = _transition(previous, current)

    with pytest.raises(phase56.MarketStructureTemporalValidationIntegrityError):
        mutated = replace(transition)
        object.__setattr__(mutated, "previous_assessment_hash", "0" * 64)
        phase56.verify_market_structure_structural_assessment_transition(mutated)

    with pytest.raises(phase56.MarketStructureTemporalValidationIntegrityError):
        mutated = replace(transition)
        object.__setattr__(mutated, "current_assessment_hash", "f" * 64)
        phase56.verify_market_structure_structural_assessment_transition(mutated)

    with pytest.raises(phase56.MarketStructureTemporalValidationIntegrityError, match="transition_hash mismatch"):
        mutated = replace(transition)
        object.__setattr__(mutated, "transition_hash", "e" * 64)
        object.__setattr__(mutated, "transition_id", phase56._hash_payload(mutated._transition_id_payload()))
        phase56.verify_market_structure_structural_assessment_transition(mutated)


def test_phase56_transition_does_not_enable_operational_behavior():
    previous = _supported_assessment()
    current = _supported_assessment(created_at_utc=previous.created_at_utc + timedelta(minutes=1))
    transition = _transition(previous, current)

    payload = transition.as_dict()
    forbidden_keys = {
        "score",
        "confidence",
        "probability",
        "ranking",
        "signal",
        "replay",
        "backtest",
        "paper",
        "live",
        "order",
    }

    assert forbidden_keys.isdisjoint(payload)
    assert "execution" not in payload["transition_reasons"]
    assert "strategy" not in payload["transition_reasons"]
    assert "broker" not in phase56.__dict__
    assert "socket" not in phase56.__dict__
