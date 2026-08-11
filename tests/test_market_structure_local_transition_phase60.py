from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

import market_data.market_structure_local_transition as phase60
import market_data.market_structure_research_contract as phase50
import market_data.offline_market_structure_detector as phase51

PHASE60_CREATED_AT_UTC = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
PHASE60_DATASET_HASH = "a" * 64


def _metadata_a() -> dict[str, object]:
    return {
        "labels": {"alpha", "beta"},
        "nested": {
            "flags": {"offline", "research"},
            "groups": {frozenset({"delta", "gamma"})},
        },
        "notes": ["phase60", "offline"],
    }


def _metadata_b() -> dict[str, object]:
    return {
        "notes": ["phase60", "offline"],
        "nested": {
            "groups": {frozenset({"gamma", "delta"})},
            "flags": {"research", "offline"},
        },
        "labels": {"beta", "alpha"},
    }


def _build_contract(*, metadata: dict[str, object] | None = None):
    return phase50.build_market_structure_research_contract(
        created_at_utc=PHASE60_CREATED_AT_UTC,
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


def _mirror_prices(prices: list[int], *, pivot: int = 400) -> list[int]:
    return [pivot - price for price in prices]


def _build_input(
    candles,
    *,
    contract=None,
    detection_result=None,
    confirmed_swings=None,
    timeframe: str = "1H",
    symbol: str = "BTC-USDT",
    market: str = "spot",
    dataset_hash: str = PHASE60_DATASET_HASH,
    effective_at: datetime | None = None,
    created_at_utc: datetime | None = None,
    metadata: dict[str, object] | None = None,
):
    return phase60.detect_market_structure_local_transition(
        contract=contract or _build_contract(),
        candles=candles,
        detection_result=detection_result,
        confirmed_swings=confirmed_swings,
        timeframe=timeframe,
        symbol=symbol,
        market=market,
        dataset_hash=dataset_hash,
        effective_at=effective_at,
        created_at_utc=created_at_utc,
        metadata=metadata or _metadata_a(),
    )


def _phase51_result(candles, *, contract=None, timeframe: str = "1H", symbol: str = "BTC-USDT", market: str = "spot"):
    detection_input = phase51.build_market_structure_detection_input(
        contract=contract or _build_contract(),
        candles=candles,
        candles_by_timeframe={timeframe: candles},
        timeframe=timeframe,
        symbol=symbol,
        market=market,
        provider_name="synthetic",
        dataset_hash=PHASE60_DATASET_HASH,
        created_at_utc=PHASE60_CREATED_AT_UTC,
        metadata=_metadata_a(),
    )
    return phase51.detect_market_structure(detection_input)


def _bullish_bos_input():
    candles = _price_series(
        [100, 104, 101, 99, 105, 109, 106, 104, 110, 114, 111, 109, 115, 119, 116, 114, 120, 124, 121, 119, 128, 129],
        datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc),
    )
    candles.extend(
        [
            _candle(candles[-1]["timestamp"] + timedelta(hours=1), open_=128, high=136, low=126, close=132, volume=150),
            _candle(candles[-1]["timestamp"] + timedelta(hours=2), open_=127, high=129, low=125, close=128, volume=151),
        ]
    )
    return candles


def _bearish_bos_input():
    mirrored = _mirror_prices(
        [100, 104, 101, 99, 105, 109, 106, 104, 110, 114, 111, 109, 115, 119, 116, 114, 120, 124, 121, 119, 128, 129]
    )
    start = datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc)
    candles = _price_series(mirrored, start)
    candles.extend(
        [
            _candle(candles[-1]["timestamp"] + timedelta(hours=1), open_=270, high=272, low=264, close=266, volume=150),
            _candle(candles[-1]["timestamp"] + timedelta(hours=2), open_=268, high=270, low=260, close=262, volume=151),
        ]
    )
    return candles


def _bullish_to_bearish_choch_input():
    candles = _bullish_bos_input()
    candles.extend(
        [
            _candle(candles[-1]["timestamp"] + timedelta(hours=1), open_=125, high=126, low=112, close=113, volume=180),
            _candle(candles[-1]["timestamp"] + timedelta(hours=2), open_=113, high=114, low=108, close=109, volume=181),
        ]
    )
    return candles


def _bearish_to_bullish_choch_input():
    candles = _bearish_bos_input()
    candles.extend(
        [
            _candle(candles[-1]["timestamp"] + timedelta(hours=1), open_=280, high=290, low=278, close=284, volume=180),
            _candle(candles[-1]["timestamp"] + timedelta(hours=2), open_=284, high=340, low=280, close=336, volume=181),
        ]
    )
    return candles


def _mixed_global_local_bullish_input():
    candles = _price_series(
        [100, 104, 101, 99, 103, 100, 98, 101, 97, 95, 99, 96, 94, 100, 104, 101, 99, 105, 109, 106, 104, 111, 115],
        datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc),
    )
    return candles


def test_phase60_detects_bullish_bos_from_phase51_positive_control():
    candles = _bullish_bos_input()
    detection_result = _phase51_result(candles)

    transition = _build_input(
        candles,
        detection_result=detection_result,
        effective_at=candles[-1]["timestamp"],
    )

    assert transition.local_structure_before == "bullish"
    assert transition.transition_type == "bos"
    assert transition.direction == "bullish"
    assert transition.confirmation_state == "confirmed"
    assert transition.protected_pivot_kind == "confirmed_swing_high"
    assert transition.broken_level is not None
    assert transition.break_event_ids
    assert transition.displacement_event_ids
    assert phase60.verify_market_structure_local_transition(transition) == transition


def test_phase60_detects_bearish_bos_from_mirrored_positive_control():
    candles = _bearish_bos_input()
    detection_result = _phase51_result(candles)

    transition = _build_input(
        candles,
        detection_result=detection_result,
        effective_at=candles[-1]["timestamp"],
    )

    assert transition.local_structure_before == "bearish"
    assert transition.transition_type == "bos"
    assert transition.direction == "bearish"
    assert transition.confirmation_state == "confirmed"
    assert transition.protected_pivot_kind == "confirmed_swing_low"


def test_phase60_detects_bullish_choch_without_global_window_dependency():
    candles = _bullish_to_bearish_choch_input()
    detection_result = _phase51_result(candles)

    assert detection_result.final_structure_state in {"indeterminate", "ambiguous", "bullish"}

    transition = _build_input(
        candles,
        detection_result=detection_result,
        effective_at=candles[-1]["timestamp"],
    )

    assert transition.local_structure_before == "bullish"
    assert transition.transition_type == "choch"
    assert transition.direction == "bearish"
    assert transition.confirmation_state == "confirmed"
    assert transition.protected_pivot_kind == "confirmed_swing_low"


def test_phase60_detects_bearish_choch_without_global_window_dependency():
    candles = _bearish_to_bullish_choch_input()
    detection_result = _phase51_result(candles)

    assert detection_result.final_structure_state in {"indeterminate", "ambiguous", "bearish"}

    transition = _build_input(
        candles,
        detection_result=detection_result,
        effective_at=candles[-1]["timestamp"],
    )

    assert transition.local_structure_before == "bearish"
    assert transition.transition_type == "choch"
    assert transition.direction == "bullish"
    assert transition.confirmation_state == "confirmed"
    assert transition.protected_pivot_kind == "confirmed_swing_high"


def test_phase60_returns_none_for_range_wick_and_failed_break():
    candles = _price_series([100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101], datetime(2026, 8, 6, 0, 0, tzinfo=timezone.utc))
    detection_result = _phase51_result(candles)

    transition = _build_input(
        candles,
        detection_result=detection_result,
        effective_at=candles[-1]["timestamp"],
    )

    assert transition.transition_type in {"none", "indeterminate"}
    assert transition.direction == "none"
    assert transition.break_event_ids == ()
    assert transition.displacement_event_ids == ()


def test_phase60_returns_indeterminate_for_insufficient_local_swings():
    candles = _price_series([100, 104, 101, 99, 102], datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc))
    detection_result = _phase51_result(candles)

    transition = _build_input(
        candles,
        detection_result=detection_result,
        effective_at=candles[-1]["timestamp"],
    )

    assert transition.transition_type == "indeterminate"
    assert transition.local_structure_before == "indeterminate"
    assert transition.direction == "none"
    assert transition.confirmation_state == "indeterminate"


def test_phase60_respects_effective_at_no_lookahead_and_round_trips():
    candles = _bullish_bos_input()
    detection_result = _phase51_result(candles)
    early_effective_at = candles[-3]["timestamp"]

    no_transition = _build_input(
        candles,
        detection_result=detection_result,
        effective_at=early_effective_at,
    )
    confirmed = _build_input(
        candles,
        detection_result=detection_result,
        effective_at=candles[-1]["timestamp"],
    )

    assert no_transition.transition_type in {"none", "indeterminate"}
    assert confirmed.transition_type == "bos"
    assert confirmed.result_id != no_transition.result_id
    assert confirmed.result_hash != no_transition.result_hash

    payload = copy.deepcopy(confirmed.as_dict())
    rebuilt = phase60.market_structure_local_transition_from_dict(payload)
    assert rebuilt.as_dict() == confirmed.as_dict()
    assert rebuilt.result_id == confirmed.result_id
    assert rebuilt.result_hash == confirmed.result_hash
    assert phase60.market_structure_local_transition_to_dict(rebuilt) == payload

    payload["result_hash"] = "0" * 64
    with pytest.raises(phase60.MarketStructureLocalTransitionIntegrityError, match="result_hash mismatch"):
        phase60.market_structure_local_transition_from_dict(payload)


def test_phase60_created_at_is_outside_identity_and_metadata_is_immutable():
    candles = _bullish_bos_input()
    detection_result = _phase51_result(candles)
    transition_a = _build_input(
        candles,
        detection_result=detection_result,
        effective_at=candles[-1]["timestamp"],
        created_at_utc=PHASE60_CREATED_AT_UTC,
        metadata=_metadata_a(),
    )
    transition_b = _build_input(
        candles,
        detection_result=detection_result,
        effective_at=candles[-1]["timestamp"],
        created_at_utc=PHASE60_CREATED_AT_UTC + timedelta(minutes=13),
        metadata=_metadata_b(),
    )

    assert transition_a.result_id == transition_b.result_id
    assert transition_a.result_hash == transition_b.result_hash
    assert transition_a.created_at_utc == PHASE60_CREATED_AT_UTC
    assert transition_b.created_at_utc == PHASE60_CREATED_AT_UTC + timedelta(minutes=13)

    with pytest.raises(TypeError):
        transition_a.metadata["labels"] = frozenset({"tampered"})  # type: ignore[index]
    with pytest.raises(AttributeError):
        transition_a.metadata["labels"].add("tampered")  # type: ignore[attr-defined]

    assert json.dumps(transition_a.as_dict(), sort_keys=True, separators=(",", ":"))


def test_phase60_rejects_schema_and_semantic_tampering():
    candles = _bullish_bos_input()
    detection_result = _phase51_result(candles)
    transition = _build_input(
        candles,
        detection_result=detection_result,
        effective_at=candles[-1]["timestamp"],
    )
    payload = copy.deepcopy(transition.as_dict())

    payload["schema_version"] = 2
    with pytest.raises(phase60.MarketStructureLocalTransitionValidationError, match="schema_version must be 1"):
        phase60.market_structure_local_transition_from_dict(payload)

    payload = copy.deepcopy(transition.as_dict())
    payload["transition_type"] = "bos"
    payload["direction"] = "none"
    with pytest.raises(phase60.MarketStructureLocalTransitionValidationError, match="confirmed local transitions require a direction"):
        phase60.market_structure_local_transition_from_dict(payload)

    payload = copy.deepcopy(transition.as_dict())
    payload["broken_level"] = None
    with pytest.raises(phase60.MarketStructureLocalTransitionValidationError, match="break details"):
        phase60.market_structure_local_transition_from_dict(payload)


def test_phase60_preserves_global_indeterminate_local_transition_coexistence():
    candles = _mixed_global_local_bullish_input()
    detection_result = _phase51_result(candles)

    transition = _build_input(
        candles,
        detection_result=detection_result,
        effective_at=candles[-1]["timestamp"],
    )

    assert detection_result.final_structure_state in {"indeterminate", "ambiguous"}
    assert transition.local_structure_before in {"bullish", "indeterminate"}
    assert transition.transition_type in {"bos", "choch", "none", "indeterminate"}
