from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

import market_data.market_structure_annotation_layer as phase52
import market_data.market_structure_hypothesis_evaluation as phase53
import market_data.market_structure_research_contract as phase50
import market_data.offline_market_structure_detector as phase51
from domain.serialization import serialize_value

PHASE53_CREATED_AT_UTC = datetime(2026, 8, 7, 15, 0, 0, tzinfo=timezone.utc)
PHASE53_CREATED_AT_UTC_OFFSET = datetime(2026, 8, 7, 12, 0, 1, tzinfo=timezone(timedelta(hours=-3)))


def _metadata_a() -> dict[str, object]:
    return {
        "labels": {"alpha", "beta"},
        "nested": {
            "flags": {"offline", "research"},
            "groups": {frozenset({"delta", "gamma"})},
        },
        "notes": ["phase53", "offline"],
    }


def _metadata_b() -> dict[str, object]:
    return {
        "notes": ["phase53", "offline"],
        "nested": {
            "groups": {frozenset({"gamma", "delta"})},
            "flags": {"research", "offline"},
        },
        "labels": {"beta", "alpha"},
    }


def _metadata_c() -> dict[str, object]:
    metadata = _metadata_a()
    metadata["labels"].add("omega")  # type: ignore[attr-defined]
    metadata["notes"].append("material")
    return metadata


def _build_contract(*, metadata: dict[str, object] | None = None):
    return phase50.build_market_structure_research_contract(
        created_at_utc=PHASE53_CREATED_AT_UTC,
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
    dataset_hash: str = "c" * 64,
    metadata: dict[str, object] | None = None,
    created_at_utc: datetime = PHASE53_CREATED_AT_UTC,
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
        created_at_utc=PHASE53_CREATED_AT_UTC,
    )


def _analysis_result() -> phase51.MarketStructureDetectionResult:
    return phase51.detect_market_structure(_analysis_input())


def _analysis_collection(*, metadata: dict[str, object] | None = None) -> phase52.MarketStructureAnnotationCollection:
    result = _analysis_result()
    return phase52.annotate_market_structure(
        result,
        metadata=metadata or _metadata_a(),
        created_at_utc=PHASE53_CREATED_AT_UTC,
    )


def _annotation_with_state(
    collection: phase52.MarketStructureAnnotationCollection,
    hypothesis_state: str,
) -> phase52.MarketStructureAnnotation:
    for annotation in collection.annotations:
        if annotation.annotation_payload["hypothesis_state"] == hypothesis_state:
            return annotation
    raise AssertionError(hypothesis_state)


def _rebased_annotation(
    annotation: phase52.MarketStructureAnnotation,
    *,
    candle_index: int,
    candle_timestamp: datetime,
    metadata: dict[str, object],
) -> phase52.MarketStructureAnnotation:
    return phase52.MarketStructureAnnotation(
        schema_version=annotation.schema_version,
        dataset_hash=annotation.dataset_hash,
        contract_hash=annotation.contract_hash,
        detection_result_hash=annotation.detection_result_hash,
        candle_timestamp=candle_timestamp,
        annotation_payload={
            **annotation.annotation_payload,
            "candle_index": candle_index,
        },
        created_at_utc=PHASE53_CREATED_AT_UTC,
        metadata=metadata,
    )


def _unknown_annotation(
    template: phase52.MarketStructureAnnotation,
    *,
    candle_index: int,
    candle_timestamp: datetime,
    metadata: dict[str, object],
) -> phase52.MarketStructureAnnotation:
    return phase52.MarketStructureAnnotation(
        schema_version=template.schema_version,
        dataset_hash=template.dataset_hash,
        contract_hash=template.contract_hash,
        detection_result_hash=template.detection_result_hash,
        candle_timestamp=candle_timestamp,
        annotation_payload={
            "timeframe": template.annotation_payload["timeframe"],
            "candle_index": candle_index,
            "macro_context": template.annotation_payload["macro_context"],
            "intermediate_context": template.annotation_payload["intermediate_context"],
            "micro_context": template.annotation_payload["micro_context"],
            "final_structure_state": "indeterminate",
            "ambiguity_state": "indeterminate",
            "invalidation_state": "indeterminate",
            "hypothesis_state": "Unknown",
            "event_count": 0,
            "event_kinds": (),
            "bullish_structure": False,
            "bearish_structure": False,
            "lateral_structure": False,
            "trading_range": False,
            "swing_high": False,
            "swing_low": False,
            "protected_high": False,
            "protected_low": False,
            "liquidity_pool": False,
            "liquidity_sweep": False,
            "breakout": False,
            "failed_breakout": False,
            "bos": False,
            "choch": False,
            "displacement": False,
            "retest": False,
            "ambiguous": False,
            "indeterminate": True,
        },
        created_at_utc=PHASE53_CREATED_AT_UTC,
        metadata=metadata,
    )


def _single_annotation_collection(
    *,
    metadata: dict[str, object],
) -> phase52.MarketStructureAnnotationCollection:
    result = _analysis_result()
    base_collection = phase52.annotate_market_structure(
        result,
        metadata=metadata,
        created_at_utc=PHASE53_CREATED_AT_UTC,
    )
    template = _annotation_with_state(base_collection, "Distribution Candidate")
    candidate = _rebased_annotation(
        template,
        candle_index=0,
        candle_timestamp=result.first_timestamp,
        metadata=metadata,
    )
    return phase52.MarketStructureAnnotationCollection(
        schema_version=phase52.MARKET_STRUCTURE_ANNOTATION_COLLECTION_SCHEMA_VERSION,
        dataset_hash=candidate.dataset_hash,
        contract_hash=candidate.contract_hash,
        detection_result_hash=candidate.detection_result_hash,
        annotation_count=1,
        first_candle_timestamp=candidate.candle_timestamp,
        last_candle_timestamp=candidate.candle_timestamp,
        annotations=(candidate,),
        created_at_utc=PHASE53_CREATED_AT_UTC,
        metadata=metadata,
    )


def _double_annotation_collection(
    *,
    metadata: dict[str, object],
) -> phase52.MarketStructureAnnotationCollection:
    result = _analysis_result()
    base_collection = phase52.annotate_market_structure(
        result,
        metadata=metadata,
        created_at_utc=PHASE53_CREATED_AT_UTC,
    )
    template = _annotation_with_state(base_collection, "Distribution Candidate")
    candidate = _rebased_annotation(
        template,
        candle_index=0,
        candle_timestamp=result.first_timestamp,
        metadata=metadata,
    )
    unknown = _unknown_annotation(
        template,
        candle_index=1,
        candle_timestamp=result.first_timestamp + timedelta(hours=1),
        metadata=metadata,
    )
    return phase52.MarketStructureAnnotationCollection(
        schema_version=phase52.MARKET_STRUCTURE_ANNOTATION_COLLECTION_SCHEMA_VERSION,
        dataset_hash=candidate.dataset_hash,
        contract_hash=candidate.contract_hash,
        detection_result_hash=candidate.detection_result_hash,
        annotation_count=2,
        first_candle_timestamp=candidate.candle_timestamp,
        last_candle_timestamp=unknown.candle_timestamp,
        annotations=(candidate, unknown),
        created_at_utc=PHASE53_CREATED_AT_UTC,
        metadata=metadata,
    )


def _semantic_hypothesis_payload(hypothesis: phase53.MarketStructureHypothesis) -> dict[str, object]:
    payload = copy.deepcopy(
        hypothesis.canonical_payload(include_hypothesis_id=False, include_hypothesis_hash=False)
    )
    payload.pop("annotation_collection_hash", None)
    return payload


def test_phase53_hypothesis_round_trip_and_metadata_are_deeply_immutable():
    metadata_a = _metadata_a()
    metadata_b = _metadata_b()
    metadata_c = _metadata_c()
    collection = _analysis_collection(metadata=metadata_a)
    template = _annotation_with_state(collection, "Distribution Candidate")

    hypothesis_a = phase53.build_market_structure_hypothesis(
        annotation=template,
        hypothesis_type="Distribution Candidate",
        metadata=metadata_a,
        created_at_utc=PHASE53_CREATED_AT_UTC,
        annotation_collection_hash=collection.collection_hash,
    )
    hypothesis_b = phase53.build_market_structure_hypothesis(
        annotation=template,
        hypothesis_type="Distribution Candidate",
        metadata=metadata_b,
        created_at_utc=PHASE53_CREATED_AT_UTC,
        annotation_collection_hash=collection.collection_hash,
    )
    hypothesis_c = phase53.build_market_structure_hypothesis(
        annotation=template,
        hypothesis_type="Distribution Candidate",
        metadata=metadata_c,
        created_at_utc=PHASE53_CREATED_AT_UTC,
        annotation_collection_hash=collection.collection_hash,
    )
    hypothesis_d = phase53.build_market_structure_hypothesis(
        annotation=template,
        hypothesis_type="Distribution Candidate",
        metadata=_metadata_a(),
        created_at_utc=PHASE53_CREATED_AT_UTC_OFFSET,
        annotation_collection_hash=collection.collection_hash,
    )

    assert hypothesis_a.hypothesis_id == hypothesis_b.hypothesis_id == hypothesis_c.hypothesis_id == hypothesis_d.hypothesis_id
    assert hypothesis_a.hypothesis_hash == hypothesis_b.hypothesis_hash == hypothesis_c.hypothesis_hash == hypothesis_d.hypothesis_hash
    assert hypothesis_a.as_dict() == hypothesis_b.as_dict()
    assert hypothesis_a.as_dict()["metadata"]["labels"] == ["alpha", "beta"]
    assert hypothesis_c.as_dict()["metadata"]["labels"] == ["alpha", "beta", "omega"]
    assert hypothesis_a.as_dict()["created_at_utc"] != hypothesis_d.as_dict()["created_at_utc"]
    assert hypothesis_a.status == "weakened"
    assert hypothesis_a.annotation_collection_hash == collection.collection_hash
    assert hypothesis_a.as_dict()["annotation_collection_hash"] == collection.collection_hash

    with pytest.raises(TypeError):
        hypothesis_a.metadata["labels"] = frozenset({"changed"})  # type: ignore[index]
    with pytest.raises(TypeError):
        hypothesis_a.metadata["nested"]["flags"] = frozenset({"changed"})  # type: ignore[index]
    with pytest.raises(AttributeError):
        hypothesis_a.metadata["labels"].add("changed")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        hypothesis_a.metadata["nested"]["groups"].add(frozenset({"changed"}))  # type: ignore[attr-defined]

    metadata_a["labels"].add("late")  # type: ignore[attr-defined]
    metadata_a["nested"]["flags"].add("late")  # type: ignore[attr-defined]
    metadata_a["nested"]["groups"].add(frozenset({"late"}))  # type: ignore[attr-defined]
    metadata_a["notes"].append("late")

    assert hypothesis_a.metadata["labels"] == frozenset({"alpha", "beta"})
    assert hypothesis_a.metadata["nested"]["flags"] == frozenset({"offline", "research"})
    assert hypothesis_a.metadata["nested"]["groups"] == frozenset({frozenset({"delta", "gamma"})})
    assert hypothesis_a.metadata["notes"] == ("phase53", "offline")
    assert json.dumps(serialize_value(hypothesis_a.as_dict()), sort_keys=True, separators=(",", ":"))

    payload = copy.deepcopy(hypothesis_a.as_dict())
    rebuilt = phase53.market_structure_hypothesis_from_dict(payload)

    assert rebuilt.hypothesis_id == hypothesis_a.hypothesis_id
    assert rebuilt.hypothesis_hash == hypothesis_a.hypothesis_hash
    assert rebuilt.as_dict() == hypothesis_a.as_dict()
    assert phase53.verify_market_structure_hypothesis(rebuilt) == rebuilt
    assert phase53.market_structure_hypothesis_to_dict(rebuilt) == payload


def test_phase53_invalidated_hypothesis_uses_invalidation_reasons():
    collection = _analysis_collection(metadata=_metadata_a())
    template = _annotation_with_state(collection, "Distribution Candidate")
    invalid_annotation = phase52.MarketStructureAnnotation(
        schema_version=phase52.MARKET_STRUCTURE_ANNOTATION_SCHEMA_VERSION,
        dataset_hash=template.dataset_hash,
        contract_hash=template.contract_hash,
        detection_result_hash=template.detection_result_hash,
        candle_timestamp=template.candle_timestamp,
        annotation_payload={
            "timeframe": template.annotation_payload["timeframe"],
            "candle_index": template.annotation_payload["candle_index"],
            "macro_context": template.annotation_payload["macro_context"],
            "intermediate_context": template.annotation_payload["intermediate_context"],
            "micro_context": template.annotation_payload["micro_context"],
            "final_structure_state": "indeterminate",
            "ambiguity_state": "indeterminate",
            "invalidation_state": "invalidated",
            "hypothesis_state": "Unknown",
            "event_count": 1,
            "event_kinds": ("failed_bos",),
            "bullish_structure": False,
            "bearish_structure": False,
            "lateral_structure": False,
            "trading_range": False,
            "swing_high": False,
            "swing_low": False,
            "protected_high": False,
            "protected_low": False,
            "liquidity_pool": False,
            "liquidity_sweep": False,
            "breakout": False,
            "failed_breakout": False,
            "bos": True,
            "choch": False,
            "displacement": False,
            "retest": False,
            "ambiguous": False,
            "indeterminate": True,
        },
        created_at_utc=PHASE53_CREATED_AT_UTC,
        metadata=_metadata_a(),
    )

    hypothesis = phase53.build_market_structure_hypothesis(
        annotation=invalid_annotation,
        hypothesis_type="Bullish Continuation",
        metadata=_metadata_a(),
        created_at_utc=PHASE53_CREATED_AT_UTC,
        annotation_collection_hash=collection.collection_hash,
    )

    assert hypothesis.status == "invalidated"
    assert hypothesis.invalidation_reasons == ("invalidation:failed_bos",)
    assert hypothesis.supporting_event_ids == ()
    assert phase53.verify_market_structure_hypothesis(hypothesis) == hypothesis


def test_phase53_evaluation_round_trip_and_unknown_is_preserved():
    metadata_a = _metadata_a()
    metadata_b = _metadata_b()
    collection = _double_annotation_collection(metadata=metadata_a)
    evaluation_a = phase53.evaluate_market_structure_hypotheses(
        collection,
        metadata=metadata_a,
        created_at_utc=PHASE53_CREATED_AT_UTC,
    )
    evaluation_b = phase53.evaluate_market_structure_hypotheses(
        collection,
        metadata=metadata_b,
        created_at_utc=PHASE53_CREATED_AT_UTC,
    )

    assert evaluation_a.evaluation_id == evaluation_b.evaluation_id
    assert evaluation_a.evaluation_hash == evaluation_b.evaluation_hash
    assert evaluation_a.annotation_collection_hash == collection.collection_hash
    assert [hypothesis.hypothesis_type for hypothesis in evaluation_a.hypotheses] == [
        "Bullish Continuation",
        "Distribution Candidate",
        "Unknown",
    ]
    assert [hypothesis.status for hypothesis in evaluation_a.hypotheses] == [
        "weakened",
        "weakened",
        "indeterminate",
    ]
    assert all(
        hypothesis.annotation_collection_hash == evaluation_a.annotation_collection_hash
        for hypothesis in evaluation_a.hypotheses
    )
    assert evaluation_a.as_dict()["created_at_utc"] == evaluation_b.as_dict()["created_at_utc"]
    assert json.dumps(serialize_value(evaluation_a.as_dict()), sort_keys=True, separators=(",", ":"))

    metadata_a["labels"].add("late")  # type: ignore[attr-defined]
    metadata_a["nested"]["flags"].add("late")  # type: ignore[attr-defined]
    metadata_a["nested"]["groups"].add(frozenset({"late"}))  # type: ignore[attr-defined]
    assert evaluation_a.metadata["labels"] == frozenset({"alpha", "beta"})
    assert evaluation_a.metadata["nested"]["flags"] == frozenset({"offline", "research"})
    assert evaluation_a.hypotheses[0].metadata["labels"] == frozenset({"alpha", "beta"})

    with pytest.raises(TypeError):
        evaluation_a.metadata["labels"] = frozenset({"changed"})  # type: ignore[index]
    with pytest.raises(AttributeError):
        evaluation_a.metadata["nested"]["groups"].add(frozenset({"changed"}))  # type: ignore[attr-defined]

    payload = copy.deepcopy(evaluation_a.as_dict())
    rebuilt = phase53.market_structure_hypothesis_evaluation_from_dict(payload)

    assert rebuilt.evaluation_id == evaluation_a.evaluation_id
    assert rebuilt.evaluation_hash == evaluation_a.evaluation_hash
    assert rebuilt.as_dict() == evaluation_a.as_dict()
    assert phase53.verify_market_structure_hypothesis_evaluation(rebuilt) == rebuilt
    assert phase53.market_structure_hypothesis_evaluation_to_dict(rebuilt) == payload


def test_phase53_evaluation_lookahead_is_stable_and_tampering_is_fail_closed():
    metadata = _metadata_a()
    single_collection = _single_annotation_collection(metadata=metadata)
    double_collection = _double_annotation_collection(metadata=_metadata_b())

    single_evaluation = phase53.evaluate_market_structure_hypotheses(
        single_collection,
        metadata=_metadata_a(),
        created_at_utc=PHASE53_CREATED_AT_UTC,
    )
    double_evaluation = phase53.evaluate_market_structure_hypotheses(
        double_collection,
        metadata=_metadata_a(),
        created_at_utc=PHASE53_CREATED_AT_UTC,
    )

    single_candidate = next(
        hypothesis for hypothesis in single_evaluation.hypotheses if hypothesis.hypothesis_type == "Distribution Candidate"
    )
    double_candidate = next(
        hypothesis for hypothesis in double_evaluation.hypotheses if hypothesis.hypothesis_type == "Distribution Candidate"
    )

    assert _semantic_hypothesis_payload(single_candidate) == _semantic_hypothesis_payload(double_candidate)

    payload = copy.deepcopy(double_evaluation.as_dict())
    payload["hypotheses"][0]["annotation_collection_hash"] = "0" * 64
    with pytest.raises(phase53.MarketStructureHypothesisIntegrityError, match="hypothesis_id mismatch"):
        phase53.market_structure_hypothesis_evaluation_from_dict(payload)

    payload = copy.deepcopy(double_evaluation.as_dict())
    payload["evaluation_hash"] = "0" * 64
    with pytest.raises(phase53.MarketStructureHypothesisIntegrityError, match="evaluation_hash mismatch"):
        phase53.market_structure_hypothesis_evaluation_from_dict(payload)
