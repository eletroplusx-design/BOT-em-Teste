from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import market_data.market_structure_structural_assessment as phase55
import market_data.market_structure_structural_assessment_history as phase57
import market_data.market_structure_temporal_validation as phase56

PHASE57_CREATED_AT_UTC = datetime(2026, 8, 7, 21, 0, 0, tzinfo=timezone.utc)
PHASE57_CREATED_AT_UTC_OFFSET = datetime(2026, 8, 7, 18, 0, 0, tzinfo=timezone(timedelta(hours=-3)))

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


def _history_metadata_a() -> dict[str, object]:
    return {
        "labels": {"alpha", "beta"},
        "nested": {
            "groups": {frozenset({"delta", "gamma"})},
            "flags": {"research", "offline"},
        },
        "notes": ["phase57", "offline"],
    }


def _history_metadata_b() -> dict[str, object]:
    return {
        "notes": ["phase57", "offline"],
        "nested": {
            "flags": {"offline", "research"},
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
    created_at_utc: datetime = PHASE57_CREATED_AT_UTC,
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
        metadata=metadata or _history_metadata_a(),
        created_at_utc=created_at_utc,
    )


def _supported_assessment(
    *,
    created_at_utc: datetime = PHASE57_CREATED_AT_UTC,
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
        "metadata": metadata or _history_metadata_a(),
    }
    params.update(overrides)
    return _assessment(**params)


def _conflicted_assessment(
    *,
    created_at_utc: datetime = PHASE57_CREATED_AT_UTC,
    metadata: dict[str, object] | None = None,
):
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
        "metadata": metadata or _history_metadata_a(),
    }
    return _assessment(**params)


def _invalidated_assessment(
    *,
    created_at_utc: datetime = PHASE57_CREATED_AT_UTC,
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
        "metadata": metadata or _history_metadata_a(),
    }
    return _assessment(**params)


def _history(
    *transitions: phase56.MarketStructureStructuralAssessmentTransition,
    hypothesis_id: str = HYPOTHESIS_ID,
    hypothesis_hash: str = HYPOTHESIS_HASH,
    created_at_utc: datetime = PHASE57_CREATED_AT_UTC,
    metadata: dict[str, object] | None = None,
) -> phase57.MarketStructureStructuralAssessmentHistory:
    return phase57.build_market_structure_structural_assessment_history(
        transitions=transitions,
        hypothesis_id=hypothesis_id,
        hypothesis_hash=hypothesis_hash,
        created_at_utc=created_at_utc,
        metadata=metadata or _history_metadata_a(),
    )


def test_phase57_empty_history_is_canonical_and_deeply_immutable():
    metadata = _history_metadata_a()
    history = _history(
        hypothesis_id=HYPOTHESIS_ID,
        hypothesis_hash=HYPOTHESIS_HASH,
        metadata=metadata,
    )

    metadata["labels"].add("late")  # type: ignore[attr-defined]
    metadata["nested"]["flags"].add("late")  # type: ignore[attr-defined]

    assert history.transition_count == 0
    assert history.first_transition_id is None
    assert history.first_transition_hash is None
    assert history.last_transition_id is None
    assert history.last_transition_hash is None
    assert history.transitions == ()
    assert history.hypothesis_id == HYPOTHESIS_ID
    assert history.hypothesis_hash == HYPOTHESIS_HASH
    assert history.metadata["labels"] == frozenset({"alpha", "beta"})
    assert history.metadata["nested"]["flags"] == frozenset({"offline", "research"})
    assert json.dumps(history.as_dict(), sort_keys=True, separators=(",", ":"))

    round_tripped = phase57.market_structure_structural_assessment_history_from_dict(history.as_dict())
    assert round_tripped.as_dict() == history.as_dict()
    assert round_tripped.history_id == history.history_id
    assert round_tripped.history_hash == history.history_hash
    assert phase57.verify_market_structure_structural_assessment_history(round_tripped) is round_tripped

    with pytest.raises(TypeError):
        history.metadata["labels"] = frozenset({"gamma"})  # type: ignore[index]
    with pytest.raises(AttributeError):
        history.metadata["labels"].add("gamma")  # type: ignore[attr-defined]


def test_phase57_history_is_deterministic_for_set_order_and_created_at_is_outside_identity():
    previous = _supported_assessment(metadata=_history_metadata_a())
    current = _conflicted_assessment(
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=7),
        metadata=_history_metadata_a(),
    )
    transition = _transition(previous, current, metadata=_history_metadata_a())

    history_a = _history(
        transition,
        hypothesis_id=HYPOTHESIS_ID,
        hypothesis_hash=HYPOTHESIS_HASH,
        created_at_utc=PHASE57_CREATED_AT_UTC,
        metadata=_history_metadata_a(),
    )
    history_b = _history(
        transition,
        hypothesis_id=HYPOTHESIS_ID,
        hypothesis_hash=HYPOTHESIS_HASH,
        created_at_utc=PHASE57_CREATED_AT_UTC_OFFSET,
        metadata=_history_metadata_b(),
    )

    assert history_a.history_id == history_b.history_id
    assert history_a.history_hash == history_b.history_hash
    assert history_a.transition_count == 1
    assert history_a.first_transition_id == transition.transition_id
    assert history_a.last_transition_hash == transition.transition_hash
    assert history_a.created_at_utc == PHASE57_CREATED_AT_UTC
    assert history_b.created_at_utc == PHASE57_CREATED_AT_UTC_OFFSET.astimezone(timezone.utc)
    assert history_a.as_dict()["history_hash"] == history_a.history_hash
    assert history_a.as_dict()["metadata"]["nested"]["groups"] == [["delta", "gamma"]]
    assert json.dumps(history_a.as_dict(), sort_keys=True, separators=(",", ":"))

    source_metadata = _history_metadata_a()
    mutable_history = _history(
        transition,
        hypothesis_id=HYPOTHESIS_ID,
        hypothesis_hash=HYPOTHESIS_HASH,
        metadata=source_metadata,
    )
    source_metadata["labels"].add("late")  # type: ignore[attr-defined]
    source_metadata["nested"]["flags"].add("late")  # type: ignore[attr-defined]
    assert mutable_history.metadata["labels"] == frozenset({"alpha", "beta"})
    assert mutable_history.metadata["nested"]["flags"] == frozenset({"offline", "research"})


def test_phase57_append_is_pure_and_preserves_prefix_integrity():
    t1 = _transition(
        _supported_assessment(created_at_utc=PHASE57_CREATED_AT_UTC),
        _conflicted_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=1)),
        metadata=_history_metadata_a(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=2),
    )
    t2 = _transition(
        _conflicted_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=1)),
        _invalidated_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=4)),
        metadata=_history_metadata_a(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=5),
    )
    t3 = _transition(
        _invalidated_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=4)),
        _invalidated_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=7)),
        metadata=_history_metadata_a(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=8),
    )

    history_2 = _history(t1, t2, hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)
    prefix_snapshot = history_2.as_dict()
    history_3 = phase57.append_market_structure_structural_assessment_transition(history_2, t3)

    assert history_2.transition_count == 2
    assert history_3.transition_count == 3
    assert history_2.as_dict() == prefix_snapshot
    assert history_2.history_id == _history(t1, t2, hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH).history_id
    assert history_2.history_hash == _history(t1, t2, hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH).history_hash
    assert tuple(item.as_dict() for item in history_3.transitions[:2]) == tuple(item.as_dict() for item in history_2.transitions)
    assert history_3.transitions[-1].transition_id == t3.transition_id
    assert history_3.transitions[-1].transition_hash == t3.transition_hash


def test_phase57_rejects_reorder_and_chain_break():
    t1 = _transition(
        _supported_assessment(),
        _conflicted_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=1)),
        metadata=_history_metadata_a(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=2),
    )
    t2 = _transition(
        _conflicted_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=1)),
        _invalidated_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=3)),
        metadata=_history_metadata_a(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=4),
    )

    with pytest.raises(phase57.MarketStructureStructuralAssessmentHistoryValidationError, match="chain break"):
        _history(t2, t1, hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)


def test_phase57_rejects_duplicate_transition_reuse():
    previous = _supported_assessment(created_at_utc=PHASE57_CREATED_AT_UTC)
    current = _supported_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=1))
    no_change = _transition(
        previous,
        current,
        metadata=_history_metadata_a(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=2),
    )

    with pytest.raises(phase57.MarketStructureStructuralAssessmentHistoryValidationError, match="duplicate"):
        _history(no_change, no_change, hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)


def test_phase57_rejects_fork_and_cycle():
    t1 = _transition(
        _supported_assessment(created_at_utc=PHASE57_CREATED_AT_UTC),
        _conflicted_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=1)),
        metadata=_history_metadata_a(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=2),
    )
    t2 = _transition(
        _conflicted_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=1)),
        _invalidated_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=3)),
        metadata=_history_metadata_a(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=4),
    )
    fork = _transition(
        _conflicted_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=1)),
        _supported_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=5)),
        metadata=_history_metadata_a(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=6),
    )

    with pytest.raises(phase57.MarketStructureStructuralAssessmentHistoryValidationError, match="chain break"):
        _history(t1, t2, fork, hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)

    cycle_a = _transition(
        _supported_assessment(created_at_utc=PHASE57_CREATED_AT_UTC),
        _conflicted_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=1)),
        metadata=_history_metadata_a(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=2),
    )
    cycle_b = _transition(
        _conflicted_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=1)),
        _supported_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=5)),
        metadata=_history_metadata_a(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=6),
    )

    with pytest.raises(phase57.MarketStructureStructuralAssessmentHistoryValidationError, match="cycle"):
        _history(cycle_a, cycle_b, hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)


def test_phase57_rejects_cross_hypothesis_and_invalidated_resurrection():
    previous = _supported_assessment(hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)
    current = _conflicted_assessment(
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=1),
        metadata=_history_metadata_a(),
    )
    cross_hypothesis_transition = _transition(
        previous,
        current,
        metadata=_history_metadata_a(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=2),
    )
    with pytest.raises(phase57.MarketStructureStructuralAssessmentHistoryValidationError, match="cross-hypothesis"):
        _history(
            cross_hypothesis_transition,
            hypothesis_id=HYPOTHESIS_ID_ALT,
            hypothesis_hash=HYPOTHESIS_HASH_ALT,
        )

    invalidated_previous = _invalidated_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=3))
    invalidated_current = _invalidated_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=4))
    invalidated_transition = _transition(
        invalidated_previous,
        invalidated_current,
        metadata=_history_metadata_a(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=5),
    )
    object.__setattr__(invalidated_transition, "current_structural_state", "supported")
    object.__setattr__(invalidated_transition, "transition_type", "state_change")

    with pytest.raises(phase56.MarketStructureTemporalValidationIntegrityError):
        _history(invalidated_transition, hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)


def test_phase57_preserves_no_change_and_allows_temporal_gaps():
    previous = _supported_assessment(created_at_utc=PHASE57_CREATED_AT_UTC)
    current = _supported_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(days=2))
    no_change = _transition(
        previous,
        current,
        metadata=_history_metadata_a(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(days=2, minutes=1),
    )
    later = _transition(
        current,
        _conflicted_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(days=7)),
        metadata=_history_metadata_a(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(days=7, minutes=1),
    )

    history = _history(no_change, later, hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)

    assert history.transitions[0].transition_type == "no_change"
    assert history.transitions[0].changed_dimensions == ()
    assert history.transitions[0].transition_reasons == ("materially_equivalent",)
    assert history.transitions[1].current_structural_state == "conflicted"
    assert history.transition_count == 2
    assert history.as_dict()["transitions"][0]["transition_type"] == "no_change"
    assert "score" not in history.as_dict()
    assert "signal" not in history.as_dict()
    assert "replay" not in history.as_dict()
    assert "paper" not in history.as_dict()
    assert "live" not in history.as_dict()


def test_phase57_round_trip_preserves_identity_and_metadata():
    t1 = _transition(
        _supported_assessment(created_at_utc=PHASE57_CREATED_AT_UTC),
        _conflicted_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=1)),
        metadata=_history_metadata_b(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=2),
    )
    t2 = _transition(
        _conflicted_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=1)),
        _invalidated_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=4)),
        metadata=_history_metadata_b(),
        created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=5),
    )
    history = _history(
        t1,
        t2,
        hypothesis_id=HYPOTHESIS_ID,
        hypothesis_hash=HYPOTHESIS_HASH,
        metadata=_history_metadata_b(),
    )

    payload = history.as_dict()
    round_tripped = phase57.market_structure_structural_assessment_history_from_dict(payload)

    assert round_tripped.as_dict() == payload
    assert round_tripped.history_id == history.history_id
    assert round_tripped.history_hash == history.history_hash
    assert round_tripped.transitions[0].transition_id == t1.transition_id
    assert round_tripped.transitions[-1].transition_hash == t2.transition_hash


def test_phase57_does_not_enable_operational_behavior():
    previous = _supported_assessment()
    current = _conflicted_assessment(created_at_utc=PHASE57_CREATED_AT_UTC + timedelta(minutes=1))
    transition = _transition(previous, current)
    history = _history(transition, hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)

    payload = history.as_dict()
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
    assert "execution" not in payload
    assert "strategy" not in payload
    assert "broker" not in phase57.__dict__
    assert "socket" not in phase57.__dict__
    assert "requests" not in phase57.__dict__
    assert "subprocess" not in phase57.__dict__
    assert "multiprocessing" not in phase57.__dict__
    assert "threading" not in phase57.__dict__
