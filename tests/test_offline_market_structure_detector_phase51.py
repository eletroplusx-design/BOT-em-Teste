from __future__ import annotations

import copy
import inspect
from datetime import datetime, timedelta, timezone

import pytest

import market_data.market_structure_research_contract as phase50
import market_data.offline_market_structure_detector as phase51
from domain.serialization import serialize_value


PHASE51_CREATED_AT_UTC = datetime(2026, 8, 6, 12, 0, 0, tzinfo=timezone.utc)
PHASE51_CREATED_AT_UTC_OFFSET = datetime(2026, 8, 6, 9, 0, 0, tzinfo=timezone(timedelta(hours=-3)))
PHASE51_DATASET_HASH = "a" * 64
PHASE51_DATASET_HASH_ALT = "b" * 64


def _metadata_a() -> dict[str, object]:
    return {
        "labels": {"alpha", "beta"},
        "nested": {
            "flags": {"offline", "research"},
            "groups": {frozenset({"delta", "gamma"})},
        },
        "notes": ["phase51", "offline"],
    }


def _metadata_b() -> dict[str, object]:
    return {
        "notes": ["phase51", "offline"],
        "nested": {
            "groups": {frozenset({"gamma", "delta"})},
            "flags": {"research", "offline"},
        },
        "labels": {"beta", "alpha"},
    }


def _build_contract(*, metadata: dict[str, object] | None = None):
    return phase50.build_market_structure_research_contract(
        created_at_utc=PHASE51_CREATED_AT_UTC,
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
    dataset_hash: str = PHASE51_DATASET_HASH,
    metadata: dict[str, object] | None = None,
    created_at_utc: datetime = PHASE51_CREATED_AT_UTC,
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
        created_at_utc=PHASE51_CREATED_AT_UTC_OFFSET,
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
    return _build_input(candles, dataset_hash=PHASE51_DATASET_HASH_ALT)


def _liquidity_breakout_input() -> phase51.MarketStructureDetectionInput:
    candles = _price_series(_liquidity_base_prices() + [110, 107], datetime(2026, 8, 3, 0, 0, tzinfo=timezone.utc))
    return _build_input(candles, dataset_hash=PHASE51_DATASET_HASH_ALT)


def _trading_range_input() -> phase51.MarketStructureDetectionInput:
    candles = _price_series([100, 101, 100, 101, 100, 101], datetime(2026, 8, 4, 0, 0, tzinfo=timezone.utc))
    return _build_input(candles, dataset_hash=PHASE51_DATASET_HASH_ALT)


def test_phase51_builds_deterministic_result_and_contexts():
    detection_input_a = _analysis_input()
    detection_input_b = _build_input(
        detection_input_a.candles,
        candles_by_timeframe={
            "4H": detection_input_a.candles_by_timeframe["4H"],
            "1H": detection_input_a.candles_by_timeframe["1H"],
            "1D": detection_input_a.candles_by_timeframe["1D"],
        },
        created_at_utc=PHASE51_CREATED_AT_UTC,
        metadata=_metadata_b(),
    )

    result_a = phase51.detect_market_structure(detection_input_a)
    result_b = phase51.detect_market_structure(detection_input_b)

    assert result_a.schema_version == phase51.OFFLINE_MARKET_STRUCTURE_DETECTOR_SCHEMA_VERSION
    assert result_a.contract_id == detection_input_a.contract.contract_id
    assert result_a.contract_hash == detection_input_a.contract.contract_hash
    assert result_a.dataset_hash == PHASE51_DATASET_HASH
    assert result_a.final_structure_state == "bullish"
    assert result_a.macro_context == "bullish"
    assert result_a.intermediate_context == "indeterminate"
    assert result_a.micro_context == "bullish"
    assert result_a.ambiguity_state == "ambiguous"
    assert result_a.invalidation_state in {"none", "invalidated"}
    assert result_a.detection_result_id == result_b.detection_result_id
    assert result_a.detection_result_hash == result_b.detection_result_hash
    assert result_a.as_dict() == result_b.as_dict()
    assert phase51.verify_market_structure_detection_result(result_a) == result_a


def test_phase51_detects_swings_bos_retest_and_displacement():
    result = phase51.detect_market_structure(_swing_bos_input())
    event_kinds = [event.kind for event in result.events]

    assert "confirmed_swing_high" in event_kinds
    assert "confirmed_swing_low" in event_kinds
    assert "bullish_structure" in event_kinds
    assert "valid_bos" in event_kinds
    assert "valid_retest" in event_kinds
    assert "valid_displacement" in event_kinds
    assert result.final_structure_state == "bullish"
    assert result.macro_context == "bullish"
    assert result.micro_context == "bullish"
    assert result.ambiguity_state == "none"


@pytest.mark.parametrize(
    ("builder", "expected_kinds"),
    [
        (_liquidity_sweep_input, {"equal_highs", "equal_lows", "liquidity_sweep", "false_break"}),
        (_liquidity_breakout_input, {"equal_highs", "equal_lows", "breakout"}),
    ],
)
def test_phase51_detects_liquidity_sweeps_and_breakouts(builder, expected_kinds):
    result = phase51.detect_market_structure(builder())
    event_kinds = {event.kind for event in result.events}

    assert {"equal_highs", "equal_lows"}.issubset(event_kinds)
    assert expected_kinds.issubset(event_kinds)


def test_phase51_detects_trading_range_and_candidate_regime():
    result = phase51.detect_market_structure(_trading_range_input())
    event_kinds = [event.kind for event in result.events]

    assert "valid_trading_range" in event_kinds
    assert "candidate_reaccumulation" in event_kinds
    assert result.final_structure_state in {"indeterminate", "lateral"}


@pytest.mark.parametrize(
    ("payload_mutator", "expected"),
    [
        (lambda payload: payload[0].update({"close": float("nan")}), "finite"),
        (lambda payload: payload[1].__setitem__("timestamp", payload[0]["timestamp"]), "strictly ascending"),
        (lambda payload: payload[1].__setitem__("timestamp", payload[1]["timestamp"] - timedelta(hours=1)), "strictly ascending"),
        (lambda payload: payload[0].update({"high": 90, "low": 95}), "high must be greater"),
        (lambda payload: payload[0].update({"complete": False}), "incomplete candle"),
        (lambda payload: payload[0].update({"open": True}), "numeric"),
        (lambda payload: None, "64-character hex digest"),
    ],
)
def test_phase51_rejects_invalid_inputs_and_contract_mismatches(payload_mutator, expected):
    candles = _price_series([100, 104, 101, 99, 110, 103], datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc))
    contract = _build_contract()
    if expected == "64-character hex digest":
        object.__setattr__(contract, "contract_hash", "0" * 64)

    if payload_mutator is not None:
        payload_mutator(candles)

    if expected == "64-character hex digest":
        with pytest.raises(phase50.MarketStructureResearchContractIntegrityError, match="contract_hash mismatch"):
            _build_input(candles, contract=contract)
    else:
        with pytest.raises(phase51.OfflineMarketStructureDetectorValidationError, match=expected):
            _build_input(candles, contract=contract)


def test_phase51_is_deeply_immutable_and_source_independent():
    metadata = _metadata_a()
    candles = _price_series([100, 104, 101, 99, 110, 103, 98, 105, 115, 107, 102, 109, 120, 112, 106, 114, 125, 118, 119, 130, 126], datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc))
    candles_by_timeframe = {
        "1H": candles,
        "4H": _price_series([150, 150, 151, 150, 151, 150, 151, 150], datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc), hours=4),
    }
    detection_input = _build_input(candles, candles_by_timeframe=candles_by_timeframe, metadata=metadata)

    with pytest.raises(TypeError):
        detection_input.metadata["labels"] = frozenset({"changed"})  # type: ignore[index]
    with pytest.raises(TypeError):
        detection_input.metadata["nested"]["flags"] = frozenset({"changed"})  # type: ignore[index]
    with pytest.raises(AttributeError):
        detection_input.metadata["labels"].add("changed")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        detection_input.metadata["nested"]["groups"].add(frozenset({"changed"}))  # type: ignore[attr-defined]

    metadata["labels"].add("late")  # type: ignore[attr-defined]
    metadata["nested"]["flags"].add("late")  # type: ignore[attr-defined]
    metadata["nested"]["groups"].add(frozenset({"late"}))  # type: ignore[attr-defined]

    result = phase51.detect_market_structure(detection_input)
    snapshot = result.as_dict()
    snapshot["metadata"]["labels"] = ["mutated"]
    snapshot["events"][0]["details"] = {"tampered": True}

    assert detection_input.metadata["labels"] == frozenset({"alpha", "beta"})
    assert detection_input.metadata["nested"]["flags"] == frozenset({"offline", "research"})
    assert detection_input.metadata["nested"]["groups"] == frozenset({frozenset({"delta", "gamma"})})
    assert result.metadata["labels"] == frozenset({"alpha", "beta"})
    assert result.as_dict()["metadata"]["labels"] == ["alpha", "beta"]
    assert result.as_dict()["events"][0]["details"] != {"tampered": True}


def test_phase51_round_trip_and_operational_surface_stay_research_only():
    result = phase51.detect_market_structure(_swing_bos_input())
    payload = copy.deepcopy(result.as_dict())
    rebuilt = phase51.market_structure_detection_result_from_dict(payload)

    assert rebuilt.detection_result_id == result.detection_result_id
    assert rebuilt.detection_result_hash == result.detection_result_hash
    assert rebuilt.as_dict() == result.as_dict()
    assert phase51.market_structure_detection_result_to_dict(rebuilt) == payload

    payload["detection_result_hash"] = "0" * 64
    with pytest.raises(phase51.OfflineMarketStructureDetectorIntegrityError, match="detection_result_hash mismatch"):
        phase51.market_structure_detection_result_from_dict(payload)

    source = inspect.getsource(phase51).lower()
    for forbidden in (
        "backtest",
        "walk-forward",
        "paper",
        "live",
        "broker",
        "subprocess",
        "thread",
        "scheduler",
        "websocket",
    ):
        assert forbidden not in source
