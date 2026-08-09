from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import market_data.market_structure_structural_assessment as phase55
import market_data.market_structure_structural_assessment_history as phase57
import market_data.market_structure_temporal_validation as phase56
import market_data.persistent_market_structure_structural_assessment_history as phase58

PHASE58_CREATED_AT_UTC = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
PHASE58_CREATED_AT_UTC_OFFSET = datetime(2026, 8, 9, 9, 0, 1, tzinfo=timezone(timedelta(hours=-3)))

BASE_TIMEFRAME_CONTEXT = {
    "timeframe": "1H",
    "macro_context": "bullish",
    "intermediate_context": "bullish",
    "micro_context": "bullish",
    "alignment_state": "aligned",
}

HYPOTHESIS_ID = "5" * 64
HYPOTHESIS_HASH = "6" * 64
HYPOTHESIS_ID_ALT = "7" * 64
HYPOTHESIS_HASH_ALT = "8" * 64


def _history_metadata_a() -> dict[str, object]:
    return {
        "labels": {"alpha", "beta"},
        "nested": {
            "flags": {"offline", "research"},
            "groups": {frozenset({"gamma", "delta"})},
        },
        "notes": ["phase58", "offline"],
    }


def _history_metadata_b() -> dict[str, object]:
    return {
        "notes": ["phase58", "offline"],
        "nested": {
            "groups": {frozenset({"delta", "gamma"})},
            "flags": {"research", "offline"},
        },
        "labels": {"beta", "alpha"},
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
    created_at_utc: datetime = PHASE58_CREATED_AT_UTC,
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
        dataset_hash="1" * 64,
        contract_hash="2" * 64,
        detection_result_hash="3" * 64,
        annotation_collection_hash="4" * 64,
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
    created_at_utc: datetime = PHASE58_CREATED_AT_UTC,
    metadata: dict[str, object] | None = None,
    **overrides: object,
):
    params = {
        "structure_summary": {
            "dimension_state": "supporting",
            "supporting": ("structure-support-1",),
            "provenance": ("structure-group-1",),
            "metadata": {"labels": {"support", "structure"}, "nested": {"groups": {frozenset({"primary", "secondary"})}}},
        },
        "timeframe_summary": {
            "dimension_state": "neutral",
            "neutral": ("timeframe-neutral-1",),
            "provenance": ("timeframe-group-1",),
            "metadata": {"labels": {"support", "structure"}, "nested": {"groups": {frozenset({"secondary", "primary"})}}},
        },
        "created_at_utc": created_at_utc,
        "metadata": metadata or _history_metadata_a(),
    }
    params.update(overrides)
    return _assessment(**params)


def _conflicted_assessment(
    *,
    created_at_utc: datetime = PHASE58_CREATED_AT_UTC,
    metadata: dict[str, object] | None = None,
):
    return _assessment(
        structure_summary={
            "dimension_state": "conflicted",
            "supporting": ("structure-support-1",),
            "contradicting": ("structure-contradict-1",),
            "provenance": ("structure-group-1",),
            "metadata": {"labels": {"support", "structure"}, "nested": {"groups": {frozenset({"primary", "secondary"})}}},
        },
        timeframe_summary={
            "dimension_state": "neutral",
            "neutral": ("timeframe-neutral-1",),
            "provenance": ("timeframe-group-1",),
            "metadata": {"labels": {"support", "structure"}, "nested": {"groups": {frozenset({"secondary", "primary"})}}},
        },
        created_at_utc=created_at_utc,
        metadata=metadata or _history_metadata_a(),
    )


def _invalidated_assessment(
    *,
    created_at_utc: datetime = PHASE58_CREATED_AT_UTC,
    metadata: dict[str, object] | None = None,
):
    return _assessment(
        structure_summary={
            "dimension_state": "invalidated",
            "invalidation": ("structure-invalid-1",),
            "provenance": ("structure-group-1",),
            "metadata": {"labels": {"support", "structure"}, "nested": {"groups": {frozenset({"primary", "secondary"})}}},
        },
        timeframe_summary={
            "dimension_state": "neutral",
            "neutral": ("timeframe-neutral-1",),
            "provenance": ("timeframe-group-1",),
            "metadata": {"labels": {"support", "structure"}, "nested": {"groups": {frozenset({"secondary", "primary"})}}},
        },
        created_at_utc=created_at_utc,
        metadata=metadata or _history_metadata_a(),
    )


def _history(
    *transitions: phase56.MarketStructureStructuralAssessmentTransition,
    hypothesis_id: str = HYPOTHESIS_ID,
    hypothesis_hash: str = HYPOTHESIS_HASH,
    created_at_utc: datetime = PHASE58_CREATED_AT_UTC,
    metadata: dict[str, object] | None = None,
) -> phase57.MarketStructureStructuralAssessmentHistory:
    return phase57.build_market_structure_structural_assessment_history(
        transitions=transitions,
        hypothesis_id=hypothesis_id,
        hypothesis_hash=hypothesis_hash,
        created_at_utc=created_at_utc,
        metadata=metadata or _history_metadata_a(),
    )


def _history_payload(history: phase57.MarketStructureStructuralAssessmentHistory) -> str:
    return json.dumps(history.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_phase58_round_trip_empty_history_is_canonical_and_deeply_immutable(tmp_path):
    history = _history(
        hypothesis_id=HYPOTHESIS_ID,
        hypothesis_hash=HYPOTHESIS_HASH,
        metadata=_history_metadata_a(),
    )
    history_file = Path("histories") / "empty-history.json"

    saved = phase58.save_market_structure_structural_assessment_history(
        history_file=history_file,
        history=history,
        root_directory=tmp_path,
    )
    loaded = phase58.load_market_structure_structural_assessment_history(
        history_file=history_file,
        root_directory=tmp_path,
    )
    verified = phase58.verify_persisted_market_structure_structural_assessment_history(loaded)

    assert saved.as_dict() == history.as_dict()
    assert loaded.as_dict() == history.as_dict()
    assert verified.history_id == history.history_id
    assert verified.history_hash == history.history_hash
    assert verified.created_at_utc == history.created_at_utc
    assert set(verified.metadata["labels"]) == {"alpha", "beta"}
    assert set(verified.metadata["nested"]["flags"]) == {"offline", "research"}
    assert {frozenset(group) for group in verified.metadata["nested"]["groups"]} == {frozenset({"delta", "gamma"})}
    assert json.dumps(loaded.as_dict(), sort_keys=True, separators=(",", ":"))

    with pytest.raises(TypeError):
        loaded.metadata["labels"] = frozenset({"gamma"})  # type: ignore[index]
    with pytest.raises(AttributeError):
        loaded.metadata["labels"].add("gamma")  # type: ignore[attr-defined]

    source_metadata = _history_metadata_a()
    source_history = _history(
        hypothesis_id=HYPOTHESIS_ID,
        hypothesis_hash=HYPOTHESIS_HASH,
        metadata=source_metadata,
    )
    source_metadata["labels"].add("late")  # type: ignore[attr-defined]
    source_metadata["nested"]["flags"].add("late")  # type: ignore[attr-defined]
    assert source_history.metadata["labels"] == frozenset({"alpha", "beta"})
    assert source_history.metadata["nested"]["flags"] == frozenset({"offline", "research"})


def test_phase58_round_trip_single_and_multiple_transitions_preserve_identity_and_gaps(tmp_path):
    no_change_previous = _supported_assessment(created_at_utc=PHASE58_CREATED_AT_UTC)
    no_change_current = _supported_assessment(created_at_utc=PHASE58_CREATED_AT_UTC)
    t1 = _transition(
        no_change_previous,
        no_change_current,
        metadata=_history_metadata_a(),
        created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=1),
    )
    t2 = _transition(
        no_change_current,
        _invalidated_assessment(created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(days=3)),
        metadata=_history_metadata_a(),
        created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(days=3, minutes=1),
    )

    single = _history(t1, hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)
    multiple = _history(t1, t2, hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)
    single_file = Path("histories") / "single.json"
    multiple_file = Path("histories") / "multiple.json"

    saved_single = phase58.save_market_structure_structural_assessment_history(
        history_file=single_file,
        history=single,
        root_directory=tmp_path,
    )
    saved_multiple = phase58.save_market_structure_structural_assessment_history(
        history_file=multiple_file,
        history=multiple,
        root_directory=tmp_path,
    )
    loaded_single = phase58.load_market_structure_structural_assessment_history(
        history_file=single_file,
        root_directory=tmp_path,
    )
    loaded_multiple = phase58.load_market_structure_structural_assessment_history(
        history_file=multiple_file,
        root_directory=tmp_path,
    )

    assert saved_single.history_id == loaded_single.history_id == single.history_id
    assert saved_single.history_hash == loaded_single.history_hash == single.history_hash
    assert saved_multiple.history_id == loaded_multiple.history_id == multiple.history_id
    assert saved_multiple.history_hash == loaded_multiple.history_hash == multiple.history_hash
    assert loaded_single.transition_count == 1
    assert loaded_multiple.transition_count == 2
    assert loaded_multiple.transitions[0].transition_type == "no_change"
    assert loaded_multiple.transitions[1].current_structural_state == "invalidated"
    assert loaded_multiple.transitions[1].created_at_utc > loaded_multiple.transitions[0].created_at_utc
    assert loaded_multiple.as_dict()["transitions"][0]["transition_type"] == "no_change"
    assert "score" not in loaded_multiple.as_dict()
    assert "signal" not in loaded_multiple.as_dict()
    assert "replay" not in loaded_multiple.as_dict()
    assert "paper" not in loaded_multiple.as_dict()
    assert "live" not in loaded_multiple.as_dict()


def test_phase58_same_history_same_persisted_payload_and_idempotent_save(tmp_path):
    t1 = _transition(
        _supported_assessment(created_at_utc=PHASE58_CREATED_AT_UTC),
        _conflicted_assessment(created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=1)),
        metadata=_history_metadata_b(),
        created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=2),
    )
    history_a = _history(
        t1,
        hypothesis_id=HYPOTHESIS_ID,
        hypothesis_hash=HYPOTHESIS_HASH,
        created_at_utc=PHASE58_CREATED_AT_UTC,
        metadata=_history_metadata_a(),
    )
    history_b = _history(
        t1,
        hypothesis_id=HYPOTHESIS_ID,
        hypothesis_hash=HYPOTHESIS_HASH,
        created_at_utc=PHASE58_CREATED_AT_UTC,
        metadata=_history_metadata_b(),
    )
    history_file = Path("histories") / "idempotent.json"

    saved_a = phase58.save_market_structure_structural_assessment_history(
        history_file=history_file,
        history=history_a,
        root_directory=tmp_path,
    )
    payload_before = (tmp_path / history_file).read_text(encoding="utf-8")
    saved_b = phase58.save_market_structure_structural_assessment_history(
        history_file=history_file,
        history=history_b,
        root_directory=tmp_path,
    )
    payload_after = (tmp_path / history_file).read_text(encoding="utf-8")

    assert history_a.history_id == history_b.history_id
    assert history_a.history_hash == history_b.history_hash
    assert saved_a.history_id == saved_b.history_id
    assert saved_a.history_hash == saved_b.history_hash
    assert payload_before == payload_after
    assert _history_payload(history_a) == _history_payload(history_b)


def test_phase58_conflicting_overwrite_fails_closed_and_preserves_existing_file(tmp_path):
    t1 = _transition(
        _supported_assessment(created_at_utc=PHASE58_CREATED_AT_UTC),
        _conflicted_assessment(created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=1)),
        metadata=_history_metadata_a(),
        created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=2),
    )
    t2 = _transition(
        _conflicted_assessment(created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=1)),
        _invalidated_assessment(created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=3)),
        metadata=_history_metadata_a(),
        created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=4),
    )
    history_a = _history(t1, hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)
    history_b = _history(t1, t2, hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)
    history_file = Path("histories") / "conflict.json"

    phase58.save_market_structure_structural_assessment_history(
        history_file=history_file,
        history=history_a,
        root_directory=tmp_path,
    )
    original_text = (tmp_path / history_file).read_text(encoding="utf-8")

    with pytest.raises(phase58.PersistentMarketStructureStructuralAssessmentHistoryConflictError, match="already exists"):
        phase58.save_market_structure_structural_assessment_history(
            history_file=history_file,
            history=history_b,
            root_directory=tmp_path,
        )

    assert (tmp_path / history_file).read_text(encoding="utf-8") == original_text


@pytest.mark.parametrize(
    "history_file",
    [
        Path(r"C:\escape.json"),
        Path(r"C:\escape.json"),
        Path(r"D:\folder\file.json"),
        Path("//server/share/file.json"),
        Path(r"\\server\share\file.json"),
        Path("/tmp/file.json"),
        Path("../file.json"),
        Path("folder/../../file.json"),
        Path("~/file.json"),
    ],
)
def test_phase58_rejects_escape_paths_cross_platform(history_file, tmp_path):
    history = _history(hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)
    with pytest.raises(phase58.PersistentMarketStructureStructuralAssessmentHistoryValidationError):
        phase58.save_market_structure_structural_assessment_history(
            history_file=history_file,
            history=history,
            root_directory=tmp_path,
        )


@pytest.mark.parametrize(
    "history_file",
    [
        Path("histories/.pytest_tmp/history.json"),
        Path("histories/phase/.pytest_tmp/history.json"),
        Path(r"histories\.pytest_tmp\history.json"),
    ],
)
def test_phase58_rejects_pytest_tmp_segments(history_file, tmp_path):
    history = _history(hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)
    with pytest.raises(phase58.PersistentMarketStructureStructuralAssessmentHistoryValidationError, match=r"\.pytest_tmp"):
        phase58.save_market_structure_structural_assessment_history(
            history_file=history_file,
            history=history,
            root_directory=tmp_path,
        )


def test_phase58_rejects_symlink_escape(tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks are not supported in this environment.")

    root = tmp_path / "authorized-root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_target = outside / "history.json"
    outside_target.write_text("{}", encoding="utf-8")

    escape_link = root / "escape"
    try:
        escape_link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("symlink creation is not permitted in this environment.")

    history = _history(hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)
    with pytest.raises(phase58.PersistentMarketStructureStructuralAssessmentHistoryValidationError):
        phase58.save_market_structure_structural_assessment_history(
            history_file=Path("escape") / "history.json",
            history=history,
            root_directory=root,
        )


def test_phase58_atomic_failure_preserves_previous_file_and_cleans_temp(tmp_path, monkeypatch):
    history_file = tmp_path / "histories" / "atomic.json"
    history_a = _history(hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)
    history_b = _history(
        _transition(
            _supported_assessment(created_at_utc=PHASE58_CREATED_AT_UTC),
            _conflicted_assessment(created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=1)),
            metadata=_history_metadata_a(),
            created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=2),
        ),
        hypothesis_id=HYPOTHESIS_ID,
        hypothesis_hash=HYPOTHESIS_HASH,
    )
    payload_a = history_a.as_dict()
    payload_b = history_b.as_dict()
    history_file.parent.mkdir(parents=True, exist_ok=True)
    history_file.write_text(json.dumps(payload_a, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    original_text = history_file.read_text(encoding="utf-8")

    def _fail(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(phase58.os, "replace", _fail, raising=True)

    temp_candidates_before = set(history_file.parent.glob(f".{history_file.name}.*.tmp"))
    with pytest.raises(phase58.PersistentMarketStructureStructuralAssessmentHistoryPersistenceError, match="failed to write"):
        phase58._write_json_atomic(history_file, payload_b)
    temp_candidates_after = set(history_file.parent.glob(f".{history_file.name}.*.tmp"))

    assert history_file.read_text(encoding="utf-8") == original_text
    assert not temp_candidates_after - temp_candidates_before


def test_phase58_load_rejects_corrupted_payloads_and_invalid_schema(tmp_path):
    history = _history(
        _transition(
            _supported_assessment(created_at_utc=PHASE58_CREATED_AT_UTC),
            _conflicted_assessment(created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=1)),
            metadata=_history_metadata_a(),
            created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=2),
        ),
        hypothesis_id=HYPOTHESIS_ID,
        hypothesis_hash=HYPOTHESIS_HASH,
        metadata=_history_metadata_a(),
    )
    history_file = Path("histories") / "corrupted.json"
    phase58.save_market_structure_structural_assessment_history(
        history_file=history_file,
        history=history,
        root_directory=tmp_path,
    )
    history_path = tmp_path / history_file
    original_payload = json.loads(history_path.read_text(encoding="utf-8"))

    corrupted_cases = [
        ("schema_version", 2, phase58.PersistentMarketStructureStructuralAssessmentHistoryValidationError, "schema_version"),
        ("history_id", "0" * 64, phase58.PersistentMarketStructureStructuralAssessmentHistoryIntegrityError, "history_id"),
        ("history_hash", "0" * 64, phase58.PersistentMarketStructureStructuralAssessmentHistoryIntegrityError, "history_hash"),
        ("hypothesis_id", HYPOTHESIS_ID_ALT, phase58.PersistentMarketStructureStructuralAssessmentHistoryValidationError, "cross-hypothesis"),
        ("hypothesis_hash", HYPOTHESIS_HASH_ALT, phase58.PersistentMarketStructureStructuralAssessmentHistoryValidationError, "cross-hypothesis"),
        ("transition_count", 999, phase58.PersistentMarketStructureStructuralAssessmentHistoryValidationError, "transition_count"),
        ("first_transition_id", "0" * 64, phase58.PersistentMarketStructureStructuralAssessmentHistoryIntegrityError, "first_transition_id"),
        ("first_transition_hash", "0" * 64, phase58.PersistentMarketStructureStructuralAssessmentHistoryIntegrityError, "first_transition_hash"),
        ("last_transition_id", "0" * 64, phase58.PersistentMarketStructureStructuralAssessmentHistoryIntegrityError, "last_transition_id"),
        ("last_transition_hash", "0" * 64, phase58.PersistentMarketStructureStructuralAssessmentHistoryIntegrityError, "last_transition_hash"),
    ]
    for field_name, value, expected_exc, expected in corrupted_cases:
        payload = json.loads(json.dumps(original_payload))
        payload[field_name] = value
        history_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        with pytest.raises(expected_exc, match=expected):
            phase58.load_market_structure_structural_assessment_history(
                history_file=history_file,
                root_directory=tmp_path,
            )

    payload = json.loads(json.dumps(original_payload))
    payload["transitions"][0]["transition_id"] = "0" * 64
    history_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(phase56.MarketStructureTemporalValidationIntegrityError, match="transition_id"):
        phase58.load_market_structure_structural_assessment_history(
            history_file=history_file,
            root_directory=tmp_path,
        )

    payload = json.loads(json.dumps(original_payload))
    payload["transitions"][0]["previous_assessment_id"] = "0" * 64
    history_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(phase56.MarketStructureTemporalValidationIntegrityError, match="transition_id"):
        phase58.load_market_structure_structural_assessment_history(
            history_file=history_file,
            root_directory=tmp_path,
        )

    payload = json.loads(json.dumps(original_payload))
    payload["transitions"][0]["metadata"]["labels"][0] = "tampered"
    history_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(phase56.MarketStructureTemporalValidationIntegrityError, match="transition_id"):
        phase58.load_market_structure_structural_assessment_history(
            history_file=history_file,
            root_directory=tmp_path,
        )

    history_path.write_text("", encoding="utf-8")
    with pytest.raises(phase58.PersistentMarketStructureStructuralAssessmentHistoryValidationError, match="empty"):
        phase58.load_market_structure_structural_assessment_history(
            history_file=history_file,
            root_directory=tmp_path,
        )

    history_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(phase58.PersistentMarketStructureStructuralAssessmentHistoryValidationError, match="invalid JSON"):
        phase58.load_market_structure_structural_assessment_history(
            history_file=history_file,
            root_directory=tmp_path,
        )


def test_phase58_rejects_cross_hypothesis_and_invalidated_resurrection():
    previous = _supported_assessment(hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)
    current = _conflicted_assessment(created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=1))
    transition = _transition(previous, current, metadata=_history_metadata_a(), created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=2))

    with pytest.raises(phase57.MarketStructureStructuralAssessmentHistoryValidationError, match="cross-hypothesis"):
        _history(
            transition,
            hypothesis_id=HYPOTHESIS_ID_ALT,
            hypothesis_hash=HYPOTHESIS_HASH_ALT,
        )

    invalidated_previous = _invalidated_assessment(created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=3))
    invalidated_current = _invalidated_assessment(created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=4))
    invalidated_transition = _transition(
        invalidated_previous,
        invalidated_current,
        metadata=_history_metadata_a(),
        created_at_utc=PHASE58_CREATED_AT_UTC + timedelta(minutes=5),
    )
    object.__setattr__(invalidated_transition, "current_structural_state", "supported")
    object.__setattr__(invalidated_transition, "transition_type", "state_change")

    with pytest.raises(phase56.MarketStructureTemporalValidationIntegrityError):
        _history(invalidated_transition, hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)


def test_phase58_does_not_enable_registry_replay_scoring_or_operation():
    history = _history(hypothesis_id=HYPOTHESIS_ID, hypothesis_hash=HYPOTHESIS_HASH)
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
        "broker",
        "execution",
        "registry",
    }

    assert forbidden_keys.isdisjoint(payload)
    assert "requests" not in phase58.__dict__
    assert "subprocess" not in phase58.__dict__
    assert "multiprocessing" not in phase58.__dict__
    assert "threading" not in phase58.__dict__
    assert "socket" not in phase58.__dict__
