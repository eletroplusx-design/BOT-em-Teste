from __future__ import annotations

import copy
import inspect
import re
from datetime import datetime, timedelta, timezone

import pytest

import market_data.market_structure_annotation_layer as phase52
import market_data.market_structure_research_contract as phase50
import market_data.offline_market_structure_detector as phase51
from domain.serialization import serialize_value

PHASE52_CREATED_AT_UTC = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)
PHASE52_CREATED_AT_UTC_OFFSET = datetime(2026, 8, 7, 9, 0, 1, tzinfo=timezone(timedelta(hours=-3)))
PHASE52_DATASET_HASH = "c" * 64
PHASE52_DATASET_HASH_ALT = "d" * 64


def _metadata_a() -> dict[str, object]:
    return {
        "labels": {"alpha", "beta"},
        "nested": {
            "flags": {"offline", "research"},
            "groups": {frozenset({"delta", "gamma"})},
        },
        "notes": ["phase52", "offline"],
    }


def _metadata_b() -> dict[str, object]:
    return {
        "notes": ["phase52", "offline"],
        "nested": {
            "groups": {frozenset({"gamma", "delta"})},
            "flags": {"research", "offline"},
        },
        "labels": {"beta", "alpha"},
    }


def _build_contract(*, metadata: dict[str, object] | None = None):
    return phase50.build_market_structure_research_contract(
        created_at_utc=PHASE52_CREATED_AT_UTC,
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
    contract=None,
    candles_by_timeframe=None,
    timeframe: str = "1H",
    symbol: str = "BTC-USDT",
    market: str = "spot",
    provider_name: str = "synthetic",
    dataset_hash: str = PHASE52_DATASET_HASH,
    metadata: dict[str, object] | None = None,
    created_at_utc: datetime = PHASE52_CREATED_AT_UTC,
):
    return phase51.build_market_structure_detection_input(
        contract=contract or _build_contract(),
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
        created_at_utc=PHASE52_CREATED_AT_UTC_OFFSET,
    )


def _swing_bos_input() -> phase51.MarketStructureDetectionInput:
    candles = _price_series(
        [100, 104, 101, 99, 105, 109, 106, 104, 110, 114, 111, 109, 115, 119, 116, 114, 120, 124, 121, 119],
        datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc),
    )
    breakout_timestamp = candles[-1]["timestamp"] + timedelta(hours=1)
    candles.extend(
        [
            _candle(
                breakout_timestamp,
                open_=128,
                high=136,
                low=126,
                close=132,
                volume=150,
            ),
            _candle(
                breakout_timestamp + timedelta(hours=1),
                open_=127,
                high=129,
                low=125,
                close=128,
                volume=151,
            ),
        ]
    )
    return _build_input(candles)


def _liquidity_base_prices() -> list[int]:
    return [100, 101, 105, 102, 98, 105, 101, 98, 105, 101, 98, 105]


def _liquidity_sweep_input() -> phase51.MarketStructureDetectionInput:
    candles = _price_series(_liquidity_base_prices() + [107, 104, 104, 104], datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc))
    return _build_input(candles, dataset_hash=PHASE52_DATASET_HASH_ALT)


def _failed_sweep_input() -> phase51.MarketStructureDetectionInput:
    candles = _price_series(_liquidity_base_prices() + [108, 106, 106, 106], datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc))
    return _build_input(candles, dataset_hash=PHASE52_DATASET_HASH_ALT)


def _liquidity_breakout_input() -> phase51.MarketStructureDetectionInput:
    candles = _price_series(_liquidity_base_prices() + [110, 107], datetime(2026, 8, 3, 0, 0, tzinfo=timezone.utc))
    return _build_input(candles, dataset_hash=PHASE52_DATASET_HASH_ALT)


def _trading_range_input() -> phase51.MarketStructureDetectionInput:
    candles = _price_series([100, 101, 100, 101, 100, 101], datetime(2026, 8, 4, 0, 0, tzinfo=timezone.utc))
    return _build_input(candles, dataset_hash=PHASE52_DATASET_HASH_ALT)


def _bearish_input() -> phase51.MarketStructureDetectionInput:
    candles = _price_series(
        [130, 126, 122, 118, 114, 110, 106, 102, 98, 94, 90, 86, 82, 78, 74, 70, 66, 62, 58, 54],
        datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc),
    )


def _bearish_annotation() -> phase52.MarketStructureAnnotation:
    return phase52.MarketStructureAnnotation(
        schema_version=phase52.MARKET_STRUCTURE_ANNOTATION_SCHEMA_VERSION,
        dataset_hash=PHASE52_DATASET_HASH_ALT,
        contract_hash=_build_contract().contract_hash,
        detection_result_hash=_result(_analysis_input()).detection_result_hash,
        candle_timestamp=datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc),
        annotation_payload={
            "timeframe": "1H",
            "candle_index": 0,
            "macro_context": "bearish",
            "intermediate_context": "bearish",
            "micro_context": "bearish",
            "final_structure_state": "bearish",
            "ambiguity_state": "none",
            "invalidation_state": "none",
            "hypothesis_state": "Bearish Continuation",
            "event_count": 1,
            "event_kinds": ("protected_low",),
            "bullish_structure": False,
            "bearish_structure": True,
            "lateral_structure": False,
            "trading_range": False,
            "swing_high": False,
            "swing_low": False,
            "protected_high": False,
            "protected_low": True,
            "liquidity_pool": False,
            "liquidity_sweep": False,
            "breakout": False,
            "failed_breakout": False,
            "bos": False,
            "choch": False,
            "displacement": False,
            "retest": False,
            "ambiguous": False,
            "indeterminate": False,
        },
        created_at_utc=PHASE52_CREATED_AT_UTC,
        metadata=_metadata_a(),
    )
    candles.extend(
        [
            _candle(candles[-1]["timestamp"] + timedelta(hours=1), open_=54, high=56, low=50, close=51, volume=180),
            _candle(candles[-1]["timestamp"] + timedelta(hours=2), open_=52, high=53, low=47, close=48, volume=181),
        ]
    )
    return _build_input(candles, dataset_hash=PHASE52_DATASET_HASH_ALT)


def _annotation_for(collection: phase52.MarketStructureAnnotationCollection, candle_index: int) -> phase52.MarketStructureAnnotation:
    for annotation in collection.annotations:
        if annotation.annotation_payload["candle_index"] == candle_index:
            return annotation
    raise AssertionError("annotation not found")


def _annotation_with_event(collection: phase52.MarketStructureAnnotationCollection, kind: str) -> phase52.MarketStructureAnnotation:
    for annotation in collection.annotations:
        if kind in annotation.annotation_payload["event_kinds"]:
            return annotation
    raise AssertionError(kind)


def _result(annotation_input: phase51.MarketStructureDetectionInput) -> phase51.MarketStructureDetectionResult:
    return phase51.detect_market_structure(annotation_input)


def test_phase52_builds_collection_and_carries_contexts():
    result = _result(_analysis_input())
    collection_a = phase52.annotate_market_structure(
        result,
        metadata=_metadata_a(),
        created_at_utc=PHASE52_CREATED_AT_UTC,
    )
    collection_b = phase52.annotate_market_structure(
        result,
        metadata=_metadata_b(),
        created_at_utc=PHASE52_CREATED_AT_UTC_OFFSET,
    )

    assert collection_a.schema_version == phase52.MARKET_STRUCTURE_ANNOTATION_COLLECTION_SCHEMA_VERSION
    assert collection_a.dataset_hash == result.dataset_hash
    assert collection_a.contract_hash == result.contract_hash
    assert collection_a.detection_result_hash == result.detection_result_hash
    assert collection_a.annotation_count == result.candle_count
    assert collection_a.first_candle_timestamp == result.first_timestamp
    assert collection_a.last_candle_timestamp == result.last_timestamp
    assert collection_a.collection_id == collection_b.collection_id
    assert collection_a.collection_hash == collection_b.collection_hash
    assert collection_a.as_dict()["created_at_utc"] != collection_b.as_dict()["created_at_utc"]
    assert phase52.verify_market_structure_annotation_collection(collection_a) == collection_a

    first = collection_a.annotations[0]
    assert first.annotation_payload["macro_context"] == result.macro_context
    assert first.annotation_payload["intermediate_context"] == result.intermediate_context
    assert first.annotation_payload["micro_context"] == result.micro_context
    assert first.annotation_payload["ambiguous"] is True
    assert first.annotation_payload["indeterminate"] is False


def test_phase52_annotation_is_deeply_immutable_and_source_independent():
    result = _result(_analysis_input())
    metadata = _metadata_a()
    annotation = phase52.build_market_structure_annotation(
        detection_result=result,
        candle_timestamp=result.first_timestamp,
        metadata=metadata,
        created_at_utc=PHASE52_CREATED_AT_UTC,
    )

    with pytest.raises(TypeError):
        annotation.metadata["labels"] = frozenset({"changed"})  # type: ignore[index]
    with pytest.raises(TypeError):
        annotation.metadata["nested"]["flags"] = frozenset({"changed"})  # type: ignore[index]
    with pytest.raises(AttributeError):
        annotation.metadata["labels"].add("changed")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        annotation.metadata["nested"]["groups"].add(frozenset({"changed"}))  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        annotation.annotation_payload["event_kinds"] = ("tampered",)  # type: ignore[index]

    metadata["labels"].add("late")  # type: ignore[attr-defined]
    metadata["nested"]["flags"].add("late")  # type: ignore[attr-defined]
    metadata["nested"]["groups"].add(frozenset({"late"}))  # type: ignore[attr-defined]
    object.__setattr__(result, "metadata", {"tampered": True})

    assert annotation.metadata["labels"] == frozenset({"alpha", "beta"})
    assert annotation.metadata["nested"]["flags"] == frozenset({"offline", "research"})
    assert annotation.metadata["nested"]["groups"] == frozenset({frozenset({"delta", "gamma"})})
    assert annotation.annotation_payload["macro_context"] == result.macro_context
    assert annotation.as_dict()["metadata"]["labels"] == ["alpha", "beta"]


def test_phase52_annotation_round_trip_and_hash_are_canonical():
    result = _result(_swing_bos_input())
    annotation = phase52.build_market_structure_annotation(
        detection_result=result,
        candle_timestamp=result.first_timestamp,
        metadata=_metadata_a(),
        created_at_utc=PHASE52_CREATED_AT_UTC,
    )
    payload = copy.deepcopy(annotation.as_dict())
    rebuilt = phase52.market_structure_annotation_from_dict(payload)

    assert rebuilt.annotation_id == annotation.annotation_id
    assert rebuilt.annotation_hash == annotation.annotation_hash
    assert rebuilt.as_dict() == annotation.as_dict()
    assert phase52.verify_market_structure_annotation(rebuilt) == rebuilt
    assert phase52.market_structure_annotation_to_dict(rebuilt) == payload

    payload["annotation_hash"] = "0" * 64
    with pytest.raises(phase52.MarketStructureAnnotationIntegrityError, match="annotation_hash mismatch"):
        phase52.market_structure_annotation_from_dict(payload)


@pytest.mark.parametrize(
    ("mutator", "expected_exception", "expected_message"),
    [
        (lambda payload: payload["annotation_payload"].__setitem__("extra", True), phase52.MarketStructureAnnotationValidationError, "unexpected"),
        (
            lambda payload: (
                payload["annotation_payload"].__setitem__("event_kinds", ["alien_event"]),
                payload["annotation_payload"].__setitem__("event_count", 1),
            ),
            phase52.MarketStructureAnnotationValidationError,
            "unknown event",
        ),
        (lambda payload: payload["annotation_payload"].__setitem__("event_count", 99), phase52.MarketStructureAnnotationValidationError, "does not match"),
        (lambda payload: payload["annotation_payload"].__setitem__("timeframe", "bad"), phase52.MarketStructureAnnotationValidationError, "supported interval"),
        (lambda payload: payload.__setitem__("candle_timestamp", datetime(2026, 8, 7, 12, 0, 0).isoformat()), phase52.MarketStructureAnnotationValidationError, "timezone-aware UTC datetime"),
    ],
)
def test_phase52_annotation_rejects_invalid_payloads(mutator, expected_exception, expected_message):
    result = _result(_analysis_input())
    annotation = phase52.build_market_structure_annotation(
        detection_result=result,
        candle_timestamp=result.first_timestamp,
        metadata=_metadata_a(),
        created_at_utc=PHASE52_CREATED_AT_UTC,
    )
    payload = copy.deepcopy(annotation.as_dict())
    mutator(payload)

    with pytest.raises(expected_exception, match=expected_message):
        phase52.market_structure_annotation_from_dict(payload)


def test_phase52_collection_round_trip_and_ordering_are_canonical():
    result = _result(_swing_bos_input())
    collection = phase52.annotate_market_structure(
        result,
        metadata=_metadata_a(),
        created_at_utc=PHASE52_CREATED_AT_UTC,
    )
    payload = copy.deepcopy(collection.as_dict())
    payload["annotations"].reverse()
    rebuilt = phase52.market_structure_annotation_collection_from_dict(payload)

    assert rebuilt.collection_id == collection.collection_id
    assert rebuilt.collection_hash == collection.collection_hash
    assert rebuilt.as_dict() == collection.as_dict()
    assert phase52.verify_market_structure_annotation_collection(rebuilt) == rebuilt
    assert phase52.market_structure_annotation_collection_to_dict(rebuilt) == collection.as_dict()

    payload["collection_hash"] = "0" * 64
    with pytest.raises(phase52.MarketStructureAnnotationIntegrityError, match="collection_hash mismatch"):
        phase52.market_structure_annotation_collection_from_dict(payload)


@pytest.mark.parametrize(
    ("result_factory", "expected_kind", "expected_flags"),
    [
        (
            _swing_bos_input,
            "confirmed_swing_high",
            {"swing_high": True},
        ),
        (
            _swing_bos_input,
            "confirmed_swing_low",
            {"swing_low": True},
        ),
        (
            _swing_bos_input,
            "valid_bos",
            {"bos": True, "displacement": True},
        ),
        (
            _swing_bos_input,
            "valid_retest",
            {"retest": True},
        ),
        (
            _swing_bos_input,
            "protected_high",
            {"protected_high": True},
        ),
        (
            _liquidity_sweep_input,
            "liquidity_sweep",
            {"liquidity_sweep": True},
        ),
        (
            _failed_sweep_input,
            "failed_sweep",
            {"liquidity_sweep": True},
        ),
        (
            _liquidity_sweep_input,
            "false_break",
            {"failed_breakout": True},
        ),
        (
            _liquidity_breakout_input,
            "breakout",
            {"breakout": True},
        ),
        (
            _trading_range_input,
            "valid_trading_range",
            {"trading_range": True},
        ),
    ],
)
def test_phase52_annotations_cover_structural_contexts(result_factory, expected_kind, expected_flags):
    result = _result(result_factory())
    collection = phase52.annotate_market_structure(result, metadata=_metadata_a())
    annotation = _annotation_with_event(collection, expected_kind)

    assert annotation.annotation_payload["timeframe"] == result.timeframe
    assert annotation.annotation_payload["macro_context"] == result.macro_context
    assert annotation.annotation_payload["intermediate_context"] == result.intermediate_context
    assert annotation.annotation_payload["micro_context"] == result.micro_context
    for flag_name, expected_value in expected_flags.items():
        assert annotation.annotation_payload[flag_name] is expected_value


def test_phase52_bearish_annotation_flags_are_supported():
    annotation = _bearish_annotation()

    assert annotation.annotation_payload["final_structure_state"] == "bearish"
    assert annotation.annotation_payload["bearish_structure"] is True
    assert annotation.annotation_payload["protected_low"] is True
    assert annotation.annotation_payload["hypothesis_state"] == "Bearish Continuation"
    assert phase52.verify_market_structure_annotation(annotation) == annotation


def test_phase52_annotation_and_collection_ignore_created_at_for_identity():
    result = _result(_analysis_input())
    annotation_a = phase52.build_market_structure_annotation(
        detection_result=result,
        candle_timestamp=result.first_timestamp,
        metadata=_metadata_a(),
        created_at_utc=PHASE52_CREATED_AT_UTC,
    )
    annotation_b = phase52.build_market_structure_annotation(
        detection_result=result,
        candle_timestamp=result.first_timestamp,
        metadata=_metadata_b(),
        created_at_utc=PHASE52_CREATED_AT_UTC_OFFSET,
    )

    assert annotation_a.annotation_id == annotation_b.annotation_id
    assert annotation_a.annotation_hash == annotation_b.annotation_hash
    assert annotation_a.annotation_payload == annotation_b.annotation_payload
    assert annotation_a.as_dict()["created_at_utc"] != annotation_b.as_dict()["created_at_utc"]

    collection_a = phase52.annotate_market_structure(
        result,
        metadata=_metadata_a(),
        created_at_utc=PHASE52_CREATED_AT_UTC,
    )
    collection_b = phase52.annotate_market_structure(
        result,
        metadata=_metadata_b(),
        created_at_utc=PHASE52_CREATED_AT_UTC_OFFSET,
    )

    assert collection_a.collection_id == collection_b.collection_id
    assert collection_a.collection_hash == collection_b.collection_hash
    assert collection_a.annotations[0].annotation_id == collection_b.annotations[0].annotation_id


def test_phase52_rejects_invalid_detection_result_state_and_hash():
    result = _result(_analysis_input())
    tampered = result
    object.__setattr__(tampered, "timeframe", "bad")
    with pytest.raises(phase51.OfflineMarketStructureDetectorIntegrityError, match="detection_result_id mismatch"):
        phase52.build_market_structure_annotation(
            detection_result=tampered,
            candle_timestamp=tampered.first_timestamp,
            metadata=_metadata_a(),
        )

    tampered = _result(_analysis_input())
    object.__setattr__(tampered, "detection_result_hash", "0" * 64)
    with pytest.raises(phase51.OfflineMarketStructureDetectorIntegrityError, match="detection_result_hash mismatch"):
        phase52.build_market_structure_annotation(
            detection_result=tampered,
            candle_timestamp=tampered.first_timestamp,
            metadata=_metadata_a(),
        )


@pytest.mark.parametrize(
    ("mutator", "expected_exception", "expected_message"),
    [
        (
            lambda payload: (
                payload["annotations"][0]["annotation_payload"].__setitem__("event_kinds", ["alien_event"]),
                payload["annotations"][0]["annotation_payload"].__setitem__("event_count", 1),
            ),
            phase52.MarketStructureAnnotationValidationError,
            "unknown event",
        ),
        (lambda payload: payload["annotations"][0]["annotation_payload"].__setitem__("candle_index", 99), phase52.MarketStructureAnnotationIntegrityError, "annotation_id mismatch"),
        (lambda payload: payload["annotations"].__setitem__(0, dict(payload["annotations"][0], candle_timestamp="2026-08-07T12:00:00")), phase52.MarketStructureAnnotationValidationError, "timezone-aware UTC datetime"),
        (lambda payload: payload.__setitem__("annotation_count", 999), phase52.MarketStructureAnnotationValidationError, "inconsistent"),
    ],
)
def test_phase52_collection_rejects_nested_corruption(mutator, expected_exception, expected_message):
    result = _result(_swing_bos_input())
    collection = phase52.annotate_market_structure(result, metadata=_metadata_a())
    payload = copy.deepcopy(collection.as_dict())
    mutator(payload)

    with pytest.raises(expected_exception, match=expected_message):
        phase52.market_structure_annotation_collection_from_dict(payload)


def test_phase52_annotations_and_collection_are_operationally_passive():
    source = inspect.getsource(phase52).lower()
    for forbidden in (
        r"\bbacktest\b",
        r"\bwalk-forward\b",
        r"\bpaper\b",
        r"\blive\b",
        r"\bbroker\b",
        r"\bposition\b",
        r"\bpnl\b",
        r"\bllm runtime\b",
    ):
        assert re.search(forbidden, source) is None
