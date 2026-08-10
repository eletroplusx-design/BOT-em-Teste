from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

import market_data.market_structure_hypothesis_evaluation as phase53
import market_data.market_structure_hypothesis_temporal_lineage as phase59
from domain.serialization import serialize_value

PHASE59_CREATED_AT_UTC = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
PHASE59_CREATED_AT_UTC_OFFSET = datetime(2026, 8, 10, 9, 0, 1, tzinfo=timezone(timedelta(hours=-3)))

BASE_TIMEFRAME_CONTEXT = {
    "timeframe": "1H",
    "macro_context": "bullish",
    "intermediate_context": "bullish",
    "micro_context": "bullish",
    "alignment_state": "aligned",
}

DATASET_HASH_A = "1" * 64
DATASET_HASH_B = "2" * 64
CONTRACT_HASH_A = "3" * 64
CONTRACT_HASH_B = "4" * 64
DETECTION_RESULT_HASH_A = "5" * 64
DETECTION_RESULT_HASH_B = "6" * 64
ANNOTATION_COLLECTION_HASH_A = "7" * 64
ANNOTATION_COLLECTION_HASH_B = "8" * 64


def _metadata_a() -> dict[str, object]:
    return {
        "labels": {"alpha", "beta"},
        "nested": {
            "flags": {"offline", "research"},
            "groups": {frozenset({"delta", "gamma"})},
        },
        "notes": ["phase59", "offline"],
    }


def _metadata_b() -> dict[str, object]:
    return {
        "notes": ["phase59", "offline"],
        "nested": {
            "groups": {frozenset({"gamma", "delta"})},
            "flags": {"research", "offline"},
        },
        "labels": {"beta", "alpha"},
    }


def _hypothesis(
    *,
    hypothesis_type: str = "Bullish Continuation",
    status: str = "supported",
    dataset_hash: str = DATASET_HASH_A,
    contract_hash: str = CONTRACT_HASH_A,
    detection_result_hash: str = DETECTION_RESULT_HASH_A,
    annotation_collection_hash: str = ANNOTATION_COLLECTION_HASH_A,
    observed_at: datetime = PHASE59_CREATED_AT_UTC,
    effective_at: datetime = PHASE59_CREATED_AT_UTC,
    supporting_event_ids: tuple[str, ...] = ("annotation-a::bullish_structure", "annotation-a::valid_bos"),
    supporting_annotation_ids: tuple[str, ...] = ("annotation-a",),
    contradicting_event_ids: tuple[str, ...] = (),
    contradicting_annotation_ids: tuple[str, ...] = (),
    invalidation_reasons: tuple[str, ...] = (),
    ambiguity_reasons: tuple[str, ...] = (),
    metadata: dict[str, object] | None = None,
    created_at_utc: datetime = PHASE59_CREATED_AT_UTC,
) -> phase53.MarketStructureHypothesis:
    return phase53.MarketStructureHypothesis(
        schema_version=phase53.MARKET_STRUCTURE_HYPOTHESIS_SCHEMA_VERSION,
        hypothesis_id="",
        hypothesis_hash="",
        hypothesis_type=hypothesis_type,
        status=status,
        dataset_hash=dataset_hash,
        contract_hash=contract_hash,
        detection_result_hash=detection_result_hash,
        annotation_collection_hash=annotation_collection_hash,
        timeframe_context=BASE_TIMEFRAME_CONTEXT,
        observed_at=observed_at,
        effective_at=effective_at,
        supporting_event_ids=supporting_event_ids,
        supporting_annotation_ids=supporting_annotation_ids,
        contradicting_event_ids=contradicting_event_ids,
        contradicting_annotation_ids=contradicting_annotation_ids,
        invalidation_reasons=invalidation_reasons,
        ambiguity_reasons=ambiguity_reasons,
        metadata=metadata or _metadata_a(),
        created_at_utc=created_at_utc,
    )


def _entry(
    hypothesis: phase53.MarketStructureHypothesis,
    *,
    sequence_number: int,
    previous_hypothesis_id: str = "",
    previous_hypothesis_hash: str = "",
    created_at_utc: datetime | None = None,
) -> phase59.MarketStructureHypothesisTemporalLineageEntry:
    return phase59.build_market_structure_hypothesis_temporal_lineage_entry(
        hypothesis,
        sequence_number=sequence_number,
        previous_hypothesis_id=previous_hypothesis_id,
        previous_hypothesis_hash=previous_hypothesis_hash,
        created_at_utc=created_at_utc or hypothesis.created_at_utc,
    )


def _lineage_key_for(hypothesis: phase53.MarketStructureHypothesis) -> dict[str, object]:
    return serialize_value(
        {
            "schema_version": phase59.MARKET_STRUCTURE_HYPOTHESIS_TEMPORAL_LINEAGE_SCHEMA_VERSION,
            "dataset_hash": hypothesis.dataset_hash,
            "contract_hash": hypothesis.contract_hash,
            "hypothesis_type": hypothesis.hypothesis_type,
            "timeframe_context": hypothesis.timeframe_context,
            "supporting_event_kinds": ("bullish_structure", "valid_bos"),
            "contradicting_event_kinds": (),
        }
    )


def _build_lineage(
    *entries: phase59.MarketStructureHypothesisTemporalLineageEntry | phase53.MarketStructureHypothesis,
    semantic_key: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
    created_at_utc: datetime = PHASE59_CREATED_AT_UTC,
):
    return phase59.build_market_structure_hypothesis_temporal_lineage(
        entries,
        semantic_key=semantic_key,
        metadata=metadata or _metadata_a(),
        created_at_utc=created_at_utc,
    )


def test_phase59_empty_lineage_is_canonical_and_deeply_immutable():
    metadata = _metadata_a()
    lineage = phase59.build_market_structure_hypothesis_temporal_lineage(
        semantic_key={
            "schema_version": phase59.MARKET_STRUCTURE_HYPOTHESIS_TEMPORAL_LINEAGE_SCHEMA_VERSION,
            "dataset_hash": DATASET_HASH_A,
            "contract_hash": CONTRACT_HASH_A,
            "hypothesis_type": "Bullish Continuation",
            "timeframe_context": BASE_TIMEFRAME_CONTEXT,
            "supporting_event_kinds": ("bullish_structure", "valid_bos"),
            "contradicting_event_kinds": (),
        },
        metadata=metadata,
        created_at_utc=PHASE59_CREATED_AT_UTC,
    )

    metadata["labels"].add("late")  # type: ignore[attr-defined]
    metadata["nested"]["flags"].add("late")  # type: ignore[attr-defined]

    assert lineage.entry_count == 0
    assert lineage.first_entry_id is None
    assert lineage.first_entry_hash is None
    assert lineage.last_entry_id is None
    assert lineage.last_entry_hash is None
    assert lineage.entries == ()
    assert lineage.metadata["labels"] == frozenset({"alpha", "beta"})
    assert lineage.metadata["nested"]["flags"] == frozenset({"offline", "research"})
    assert json.dumps(lineage.as_dict(), sort_keys=True, separators=(",", ":"))

    round_tripped = phase59.market_structure_hypothesis_temporal_lineage_from_dict(lineage.as_dict())
    assert round_tripped.as_dict() == lineage.as_dict()
    assert round_tripped.lineage_id == lineage.lineage_id
    assert round_tripped.lineage_hash == lineage.lineage_hash
    assert phase59.verify_market_structure_hypothesis_temporal_lineage(round_tripped) is round_tripped

    with pytest.raises(TypeError):
        lineage.metadata["labels"] = frozenset({"gamma"})  # type: ignore[index]
    with pytest.raises(AttributeError):
        lineage.metadata["labels"].add("gamma")  # type: ignore[attr-defined]


def test_phase59_append_is_pure_and_keeps_lineage_id_stable():
    h1 = _hypothesis(
        observed_at=PHASE59_CREATED_AT_UTC,
        effective_at=PHASE59_CREATED_AT_UTC,
        created_at_utc=PHASE59_CREATED_AT_UTC,
    )
    h2 = _hypothesis(
        detection_result_hash=DETECTION_RESULT_HASH_B,
        annotation_collection_hash=ANNOTATION_COLLECTION_HASH_B,
        observed_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        effective_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        created_at_utc=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
    )
    h3 = _hypothesis(
        detection_result_hash="9" * 64,
        annotation_collection_hash="a" * 64,
        observed_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=10),
        effective_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=10),
        created_at_utc=PHASE59_CREATED_AT_UTC + timedelta(minutes=10),
    )

    lineage_1 = _build_lineage(_entry(h1, sequence_number=1), metadata=_metadata_a())
    lineage_2 = phase59.append_market_structure_hypothesis_temporal_lineage(lineage_1, h2)
    lineage_3 = phase59.append_market_structure_hypothesis_temporal_lineage(lineage_2, h3)

    assert lineage_1.lineage_id == lineage_2.lineage_id == lineage_3.lineage_id
    assert lineage_1.lineage_hash != lineage_2.lineage_hash
    assert lineage_2.lineage_hash != lineage_3.lineage_hash
    assert lineage_1.entry_count == 1
    assert lineage_2.entry_count == 2
    assert lineage_3.entry_count == 3
    assert lineage_3.first_entry_id == lineage_1.first_entry_id
    assert lineage_3.last_entry_id != lineage_1.last_entry_id
    assert phase59.verify_market_structure_hypothesis_temporal_lineage(lineage_3) is lineage_3


def test_phase59_created_at_utc_is_outside_the_identity_and_hash():
    h1 = _hypothesis(created_at_utc=PHASE59_CREATED_AT_UTC)
    entry = _entry(h1, sequence_number=1, created_at_utc=PHASE59_CREATED_AT_UTC)
    lineage_a = _build_lineage(entry, metadata=_metadata_a(), created_at_utc=PHASE59_CREATED_AT_UTC)
    lineage_b = _build_lineage(entry, metadata=_metadata_a(), created_at_utc=PHASE59_CREATED_AT_UTC_OFFSET)

    assert lineage_a.lineage_id == lineage_b.lineage_id
    assert lineage_a.lineage_hash == lineage_b.lineage_hash
    assert lineage_a.created_at_utc == PHASE59_CREATED_AT_UTC
    assert lineage_b.created_at_utc == PHASE59_CREATED_AT_UTC_OFFSET.astimezone(timezone.utc)


@pytest.mark.parametrize(
    ("field_name", "override", "match"),
    [
        ("dataset_hash", {"dataset_hash": DATASET_HASH_B}, "no matching lineage continuation"),
        ("contract_hash", {"contract_hash": CONTRACT_HASH_B}, "no matching lineage continuation"),
        ("hypothesis_type", {"hypothesis_type": "Bearish Continuation"}, "no matching lineage continuation"),
    ],
)
def test_phase59_rejects_non_matching_lineage_candidates(field_name, override, match):
    base = _hypothesis(
        observed_at=PHASE59_CREATED_AT_UTC,
        effective_at=PHASE59_CREATED_AT_UTC,
        created_at_utc=PHASE59_CREATED_AT_UTC,
    )
    lineage = _build_lineage(_entry(base, sequence_number=1), metadata=_metadata_a())
    candidate = _hypothesis(
        observed_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        effective_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        created_at_utc=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        **override,
    )

    with pytest.raises(phase59.MarketStructureHypothesisTemporalLineageValidationError, match=match):
        phase59.append_market_structure_hypothesis_temporal_lineage(lineage, [candidate])


def test_phase59_rejects_ambiguous_continuation():
    base = _hypothesis()
    lineage = _build_lineage(_entry(base, sequence_number=1))
    candidate_a = _hypothesis(
        detection_result_hash=DETECTION_RESULT_HASH_B,
        annotation_collection_hash=ANNOTATION_COLLECTION_HASH_B,
        observed_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        effective_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        created_at_utc=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
    )
    candidate_b = _hypothesis(
        detection_result_hash="9" * 64,
        annotation_collection_hash="a" * 64,
        observed_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=6),
        effective_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=6),
        created_at_utc=PHASE59_CREATED_AT_UTC + timedelta(minutes=6),
    )

    with pytest.raises(phase59.MarketStructureHypothesisTemporalLineageConflictError, match="ambiguous lineage continuation"):
        phase59.append_market_structure_hypothesis_temporal_lineage(lineage, [candidate_a, candidate_b])


def test_phase59_rejects_duplicate_and_conflicting_duplicates():
    h1 = _hypothesis()
    h2 = _hypothesis(
        detection_result_hash=DETECTION_RESULT_HASH_B,
        annotation_collection_hash=ANNOTATION_COLLECTION_HASH_B,
        observed_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        effective_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        created_at_utc=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
    )
    lineage = _build_lineage(_entry(h1, sequence_number=1))

    duplicate = phase59.append_market_structure_hypothesis_temporal_lineage(lineage, h2)
    with pytest.raises(phase59.MarketStructureHypothesisTemporalLineageConflictError, match="duplicate hypothesis_id"):
        phase59.append_market_structure_hypothesis_temporal_lineage(duplicate, h2)

    conflicting_duplicate = replace(
        duplicate.entries[-1],
        hypothesis_id=duplicate.entries[0].hypothesis_id,
        hypothesis_hash="f" * 64,
    )
    with pytest.raises(phase59.MarketStructureHypothesisTemporalLineageConflictError, match="duplicate hypothesis_id"):
        _build_lineage(duplicate.entries[0], conflicting_duplicate)


def test_phase59_rejects_temporal_regression_same_timestamp_and_resurrection():
    h1 = _hypothesis(
        status="invalidated",
        invalidation_reasons=("invalidation:failed_bos",),
    )
    h2 = _hypothesis(
        status="supported",
        detection_result_hash=DETECTION_RESULT_HASH_B,
        annotation_collection_hash=ANNOTATION_COLLECTION_HASH_B,
        observed_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        effective_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        created_at_utc=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
    )
    lineage = _build_lineage(_entry(h1, sequence_number=1))

    with pytest.raises(
        phase59.MarketStructureHypothesisTemporalLineageValidationError,
        match="invalidated hypothesis instances cannot silently resurrect",
    ):
        phase59.append_market_structure_hypothesis_temporal_lineage(lineage, h2)

    current_same_timestamp = _hypothesis(
        detection_result_hash=DETECTION_RESULT_HASH_B,
        annotation_collection_hash=ANNOTATION_COLLECTION_HASH_B,
        observed_at=PHASE59_CREATED_AT_UTC,
        effective_at=PHASE59_CREATED_AT_UTC,
        created_at_utc=PHASE59_CREATED_AT_UTC,
    )
    current_regression = _hypothesis(
        detection_result_hash="9" * 64,
        annotation_collection_hash="a" * 64,
        observed_at=PHASE59_CREATED_AT_UTC - timedelta(minutes=1),
        effective_at=PHASE59_CREATED_AT_UTC - timedelta(minutes=1),
        created_at_utc=PHASE59_CREATED_AT_UTC - timedelta(minutes=1),
    )
    base = _hypothesis()
    lineage = _build_lineage(_entry(base, sequence_number=1))
    with pytest.raises(phase59.MarketStructureHypothesisTemporalLineageValidationError, match="same timestamp or temporal regression"):
        phase59.append_market_structure_hypothesis_temporal_lineage(lineage, current_same_timestamp)
    with pytest.raises(phase59.MarketStructureHypothesisTemporalLineageValidationError, match="same timestamp or temporal regression"):
        phase59.append_market_structure_hypothesis_temporal_lineage(lineage, current_regression)


def test_phase59_rejects_gap_fork_merge_and_reorder():
    h1 = _hypothesis()
    h2 = _hypothesis(
        detection_result_hash=DETECTION_RESULT_HASH_B,
        annotation_collection_hash=ANNOTATION_COLLECTION_HASH_B,
        observed_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        effective_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        created_at_utc=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
    )
    h3 = _hypothesis(
        detection_result_hash="9" * 64,
        annotation_collection_hash="a" * 64,
        observed_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=10),
        effective_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=10),
        created_at_utc=PHASE59_CREATED_AT_UTC + timedelta(minutes=10),
    )

    entry1 = _entry(h1, sequence_number=1)
    entry2 = _entry(h2, sequence_number=2, previous_hypothesis_id=entry1.hypothesis_id, previous_hypothesis_hash=entry1.hypothesis_hash)
    entry3 = _entry(h3, sequence_number=3, previous_hypothesis_id=entry2.hypothesis_id, previous_hypothesis_hash=entry2.hypothesis_hash)

    with pytest.raises(phase59.MarketStructureHypothesisTemporalLineageValidationError, match="sequence gap or reorder"):
        _build_lineage(entry1, entry3)

    fork_entry = replace(entry2, previous_hypothesis_id="0" * 64)
    with pytest.raises(phase59.MarketStructureHypothesisTemporalLineageConflictError, match="fork"):
        _build_lineage(entry1, fork_entry)

    merge_entry = replace(entry2, previous_hypothesis_hash="f" * 64)
    with pytest.raises(phase59.MarketStructureHypothesisTemporalLineageConflictError, match="merge"):
        _build_lineage(entry1, merge_entry)

    with pytest.raises(phase59.MarketStructureHypothesisTemporalLineageValidationError, match="sequence gap or reorder"):
        _build_lineage(entry2, entry1)


def test_phase59_round_trip_preserves_identity_and_metadata():
    h1 = _hypothesis(created_at_utc=PHASE59_CREATED_AT_UTC)
    h2 = _hypothesis(
        detection_result_hash=DETECTION_RESULT_HASH_B,
        annotation_collection_hash=ANNOTATION_COLLECTION_HASH_B,
        observed_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        effective_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        created_at_utc=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
    )
    lineage = phase59.append_market_structure_hypothesis_temporal_lineage(
        _build_lineage(_entry(h1, sequence_number=1), metadata=_metadata_b()),
        h2,
    )

    payload = lineage.as_dict()
    round_tripped = phase59.market_structure_hypothesis_temporal_lineage_from_dict(copy.deepcopy(payload))

    assert round_tripped.as_dict() == payload
    assert round_tripped.lineage_id == lineage.lineage_id
    assert round_tripped.lineage_hash == lineage.lineage_hash
    assert round_tripped.entries[0].hypothesis_id == lineage.entries[0].hypothesis_id
    assert round_tripped.entries[-1].hypothesis_hash == lineage.entries[-1].hypothesis_hash
    assert phase59.verify_market_structure_hypothesis_temporal_lineage(round_tripped) is round_tripped
    assert json.dumps(serialize_value(round_tripped.as_dict()), sort_keys=True, separators=(",", ":"))


def test_phase59_detects_hash_id_and_schema_corruption():
    h1 = _hypothesis()
    h2 = _hypothesis(
        detection_result_hash=DETECTION_RESULT_HASH_B,
        annotation_collection_hash=ANNOTATION_COLLECTION_HASH_B,
        observed_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        effective_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        created_at_utc=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
    )
    lineage = phase59.append_market_structure_hypothesis_temporal_lineage(
        _build_lineage(_entry(h1, sequence_number=1)),
        h2,
    )

    payload = copy.deepcopy(lineage.as_dict())
    payload["lineage_hash"] = "0" * 64
    with pytest.raises(phase59.MarketStructureHypothesisTemporalLineageIntegrityError, match="lineage_hash mismatch"):
        phase59.market_structure_hypothesis_temporal_lineage_from_dict(payload)

    payload = copy.deepcopy(lineage.as_dict())
    payload["lineage_id"] = "1" * 64
    with pytest.raises(phase59.MarketStructureHypothesisTemporalLineageIntegrityError, match="lineage_id mismatch"):
        phase59.market_structure_hypothesis_temporal_lineage_from_dict(payload)

    payload = copy.deepcopy(lineage.as_dict())
    payload["schema_version"] = 2
    with pytest.raises(phase59.MarketStructureHypothesisTemporalLineageValidationError, match="schema_version must be 1"):
        phase59.market_structure_hypothesis_temporal_lineage_from_dict(payload)

    payload = copy.deepcopy(lineage.as_dict())
    payload["entries"][0]["schema_version"] = 2
    with pytest.raises(phase59.MarketStructureHypothesisTemporalLineageValidationError, match="schema_version must be 1"):
        phase59.market_structure_hypothesis_temporal_lineage_from_dict(payload)


def test_phase59_offline_integration_preserves_snapshot_identity_and_lineage_stability():
    snapshot_1 = _hypothesis(
        observed_at=PHASE59_CREATED_AT_UTC,
        effective_at=PHASE59_CREATED_AT_UTC,
        created_at_utc=PHASE59_CREATED_AT_UTC,
    )
    snapshot_2 = _hypothesis(
        detection_result_hash=DETECTION_RESULT_HASH_B,
        annotation_collection_hash=ANNOTATION_COLLECTION_HASH_B,
        observed_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        effective_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
        created_at_utc=PHASE59_CREATED_AT_UTC + timedelta(minutes=5),
    )
    snapshot_3 = _hypothesis(
        detection_result_hash="9" * 64,
        annotation_collection_hash="a" * 64,
        observed_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=10),
        effective_at=PHASE59_CREATED_AT_UTC + timedelta(minutes=10),
        created_at_utc=PHASE59_CREATED_AT_UTC + timedelta(minutes=10),
    )

    lineage_1 = _build_lineage(_entry(snapshot_1, sequence_number=1), metadata=_metadata_a())
    lineage_2 = phase59.append_market_structure_hypothesis_temporal_lineage(lineage_1, snapshot_2)
    lineage_3 = phase59.append_market_structure_hypothesis_temporal_lineage(lineage_2, snapshot_3)

    assert snapshot_1.hypothesis_id != snapshot_2.hypothesis_id != snapshot_3.hypothesis_id
    assert snapshot_1.hypothesis_hash != snapshot_2.hypothesis_hash != snapshot_3.hypothesis_hash
    assert lineage_1.lineage_id == lineage_2.lineage_id == lineage_3.lineage_id
    assert lineage_1.lineage_hash != lineage_2.lineage_hash != lineage_3.lineage_hash
    assert lineage_3.entry_count == 3
    assert lineage_3.entries[0].hypothesis_id == snapshot_1.hypothesis_id
    assert lineage_3.entries[1].hypothesis_id == snapshot_2.hypothesis_id
    assert lineage_3.entries[2].hypothesis_id == snapshot_3.hypothesis_id
