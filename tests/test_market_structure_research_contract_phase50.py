from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

import market_data.market_structure_research_contract as phase50
import market_data.offline_execution_audit_record as phase48
import market_data.offline_execution_audit_registry as phase49
import market_data.offline_research_backtest as backtest
import strategies.baseline_a_okx_btc_usdt_research as baseline_module
from domain.serialization import serialize_value

PHASE50_CREATED_AT_UTC = datetime(2026, 8, 5, 18, 0, 0, tzinfo=timezone.utc)
PHASE50_CREATED_AT_UTC_OFFSET = datetime(2026, 8, 5, 15, 0, 0, tzinfo=timezone(timedelta(hours=-3)))


def _metadata_a() -> dict[str, object]:
    return {
        "labels": {"beta", "alpha"},
        "nested": {
            "groups": {frozenset({"gamma", "delta"})},
            "flags": {"research", "offline"},
        },
        "notes": ["offline", "research-only"],
    }


def _metadata_b() -> dict[str, object]:
    return {
        "notes": ["offline", "research-only"],
        "nested": {
            "flags": {"offline", "research"},
            "groups": {frozenset({"delta", "gamma"})},
        },
        "labels": {"alpha", "beta"},
    }


def _build_contract(*, metadata: dict[str, object] | None = None, created_at_utc: datetime | None = None):
    return phase50.build_market_structure_research_contract(
        created_at_utc=created_at_utc or PHASE50_CREATED_AT_UTC,
        metadata=metadata or _metadata_a(),
    )


def _forbidden(*args, **kwargs):
    raise AssertionError("unexpected operational or legacy call")


def test_phase50_builds_canonical_contract_and_is_stable(monkeypatch):
    monkeypatch.setattr(backtest, "run_first_offline_okx_backtest_experiment", _forbidden, raising=True)
    monkeypatch.setattr(backtest.OfflineResearchBacktestRunner, "run", _forbidden, raising=True)
    monkeypatch.setattr(backtest.LeakFreeBacktestEngine, "run", _forbidden, raising=True)
    monkeypatch.setattr(phase49, "register_offline_execution_audit_record", _forbidden, raising=True)
    monkeypatch.setattr(phase48, "build_offline_execution_audit_record", _forbidden, raising=True)
    monkeypatch.setattr(
        baseline_module,
        "build_baseline_a_okx_btc_usdt_research_contract",
        _forbidden,
        raising=True,
    )

    contract_one = _build_contract(created_at_utc=PHASE50_CREATED_AT_UTC)
    contract_two = _build_contract(created_at_utc=PHASE50_CREATED_AT_UTC_OFFSET)

    assert contract_one.schema_version == phase50.MARKET_STRUCTURE_RESEARCH_CONTRACT_SCHEMA_VERSION
    assert contract_one.contract_name == phase50.MARKET_STRUCTURE_RESEARCH_CONTRACT_NAME
    assert contract_one.market_domain == phase50.MARKET_STRUCTURE_RESEARCH_CONTRACT_MARKET_DOMAIN
    assert contract_one.supported_timeframes == phase50.MARKET_STRUCTURE_RESEARCH_CONTRACT_SUPPORTED_TIMEFRAMES
    assert contract_one.allowed_states == phase50.MARKET_STRUCTURE_RESEARCH_CONTRACT_ALLOWED_STATES
    assert contract_one.contract_id == contract_two.contract_id
    assert contract_one.contract_hash == contract_two.contract_hash
    assert contract_one.contract_id != contract_one.contract_hash
    assert contract_one.as_dict()["contract_id"] == contract_one.contract_id
    assert contract_one.as_dict()["contract_hash"] == contract_one.contract_hash
    assert contract_one.timeframe_context_definition.parameters["macro_timeframe"] == "1D"
    assert contract_one.timeframe_context_definition.parameters["intermediate_timeframe"] == "4H"
    assert contract_one.timeframe_context_definition.parameters["micro_timeframe"] == "1H"
    assert contract_one.swing_definition.states == (
        "confirmed_swing_high",
        "confirmed_swing_low",
        "candidate_swing_high",
        "candidate_swing_low",
        "indeterminate",
    )
    assert contract_one.ambiguity_definition.states == ("determinate", "indeterminate", "ambiguous", "invalid")


def test_phase50_is_deeply_immutable_and_source_independent():
    metadata = _metadata_a()
    contract = _build_contract(metadata=metadata)

    with pytest.raises(TypeError):
        contract.metadata["labels"] = frozenset({"gamma"})  # type: ignore[index]
    with pytest.raises(TypeError):
        contract.metadata["nested"]["flags"] = frozenset({"changed"})  # type: ignore[index]
    with pytest.raises(AttributeError):
        contract.metadata["labels"].add("gamma")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        contract.metadata["nested"]["groups"].add(frozenset({"epsilon"}))  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        contract.swing_definition.parameters["left_window"] = 99  # type: ignore[index]
    with pytest.raises(TypeError):
        contract.invalidation_rules["swing_definition"] = ("tampered",)  # type: ignore[index]

    metadata["labels"].add("late")  # type: ignore[attr-defined]
    metadata["nested"]["flags"].add("late")  # type: ignore[attr-defined]
    metadata["nested"]["groups"].add(frozenset({"late"}))  # type: ignore[attr-defined]
    metadata["notes"].append("mutated")

    assert contract.metadata["labels"] == frozenset({"alpha", "beta"})
    assert contract.metadata["nested"]["flags"] == frozenset({"offline", "research"})
    assert contract.metadata["nested"]["groups"] == frozenset({frozenset({"delta", "gamma"})})
    assert contract.metadata["notes"] == ("offline", "research-only")

    snapshot = contract.as_dict()
    snapshot["metadata"]["labels"] = ["changed"]
    snapshot["swing_definition"]["parameters"]["left_window"] = 999
    assert contract.as_dict()["metadata"]["labels"] == ["alpha", "beta"]
    assert contract.swing_definition.parameters["left_window"] == 2


def test_phase50_supports_nested_sets_deterministically():
    contract_a = _build_contract(metadata=_metadata_a(), created_at_utc=PHASE50_CREATED_AT_UTC)
    contract_b = _build_contract(metadata=_metadata_b(), created_at_utc=PHASE50_CREATED_AT_UTC_OFFSET)

    assert contract_a.contract_id == contract_b.contract_id
    assert contract_a.contract_hash == contract_b.contract_hash
    assert contract_a.as_dict() == contract_b.as_dict()
    assert contract_a.metadata["labels"] == frozenset({"alpha", "beta"})
    assert contract_a.metadata["nested"]["groups"] == frozenset({frozenset({"delta", "gamma"})})
    assert json.dumps(contract_a.as_dict(), sort_keys=True, separators=(",", ":"))

    snapshot = contract_a.as_dict()
    snapshot["metadata"]["labels"] = ["changed"]
    assert contract_a.as_dict()["metadata"]["labels"] == ["alpha", "beta"]

    mutated_metadata = _metadata_a()
    mutated_metadata["labels"].add("delta")  # type: ignore[attr-defined]
    assert _build_contract(metadata=mutated_metadata).contract_hash != contract_a.contract_hash


def test_phase50_round_trip_and_verification_are_canonical():
    contract = _build_contract(metadata=_metadata_a())
    payload = contract.as_dict()
    rebuilt = phase50.market_structure_research_contract_from_dict(copy.deepcopy(payload))

    assert rebuilt.contract_id == contract.contract_id
    assert rebuilt.contract_hash == contract.contract_hash
    assert rebuilt.as_dict() == contract.as_dict()
    assert phase50.verify_market_structure_research_contract(rebuilt) == rebuilt
    assert phase50.market_structure_research_contract_to_dict(rebuilt) == payload


@pytest.mark.parametrize(
    ("path_key", "replacement", "expected"),
    [
        ("left_window", True, "must be an integer"),
        ("right_window", -1, "must be greater than zero"),
        ("equality_tolerance_value", -1, "cannot be negative"),
        ("minimum_swing_count", 0, "must be greater than zero"),
        ("wick_allowed", "yes", "must be a boolean"),
        ("minimum_break_distance", -1, "cannot be negative"),
        ("minimum_test_count", 0, "must be greater than zero"),
        ("minimum_penetration", -1, "cannot be negative"),
        ("minimum_width", -1, "cannot be negative"),
        ("minimum_duration", 0, "must be greater than zero"),
    ],
)
def test_phase50_rejects_invalid_parameter_types_and_ranges(path_key, replacement, expected):
    payload = _build_contract().as_dict()
    location_map = {
        "left_window": ("swing_definition", "parameters"),
        "right_window": ("swing_definition", "parameters"),
        "equality_tolerance_value": ("swing_definition", "parameters"),
        "minimum_swing_count": ("trend_structure_definition", "parameters"),
        "wick_allowed": ("bos_definition", "parameters"),
        "minimum_break_distance": ("bos_definition", "parameters"),
        "minimum_test_count": ("liquidity_definition", "parameters"),
        "minimum_penetration": ("liquidity_sweep_definition", "parameters"),
        "minimum_width": ("trading_range_definition", "parameters"),
        "minimum_duration": ("trading_range_definition", "parameters"),
    }
    block_name, params_key = location_map[path_key]
    payload[block_name][params_key][path_key] = replacement
    with pytest.raises(phase50.MarketStructureResearchContractValidationError, match=expected):
        phase50.market_structure_research_contract_from_dict(payload)


def test_phase50_rejects_unknown_policies_timeframes_and_ambiguous_payloads():
    payload = _build_contract().as_dict()

    payload["allowed_states"] = ["determinate", "indeterminate", "ambiguous", "unknown"]
    with pytest.raises(phase50.MarketStructureResearchContractValidationError, match="allowed_states"):
        phase50.market_structure_research_contract_from_dict(payload)

    payload = _build_contract().as_dict()
    payload["supported_timeframes"] = ["1H", "4H", "1D"]
    with pytest.raises(phase50.MarketStructureResearchContractValidationError, match="supported_timeframes"):
        phase50.market_structure_research_contract_from_dict(payload)

    payload = _build_contract().as_dict()
    payload["supported_timeframes"] = ["1D", "1D", "1H"]
    with pytest.raises(phase50.MarketStructureResearchContractValidationError, match="duplicates"):
        phase50.market_structure_research_contract_from_dict(payload)

    payload = _build_contract().as_dict()
    payload["timeframe_context_definition"]["parameters"]["missing_timeframe_policy"] = "ignore"
    with pytest.raises(phase50.MarketStructureResearchContractValidationError, match="timeframe_context_definition"):
        phase50.market_structure_research_contract_from_dict(payload)


def test_phase50_rejects_nan_infinity_and_timezoneless_datetimes():
    payload = _build_contract().as_dict()
    payload["metadata"]["scores"] = float("nan")
    with pytest.raises(phase50.MarketStructureResearchContractValidationError, match="serializable"):
        phase50.market_structure_research_contract_from_dict(payload)

    payload = _build_contract().as_dict()
    payload["metadata"]["scores"] = float("inf")
    with pytest.raises(phase50.MarketStructureResearchContractValidationError, match="serializable"):
        phase50.market_structure_research_contract_from_dict(payload)

    payload = _build_contract().as_dict()
    payload["created_at_utc"] = datetime(2026, 8, 5, 18, 0, 0).isoformat()
    with pytest.raises(phase50.MarketStructureResearchContractValidationError, match="timezone-aware UTC datetime"):
        phase50.market_structure_research_contract_from_dict(payload)


def test_phase50_rejects_divergent_contract_and_concept_payloads():
    payload = _build_contract().as_dict()
    payload["contract_name"] = "Different"
    with pytest.raises(phase50.MarketStructureResearchContractValidationError, match="contract_name"):
        phase50.market_structure_research_contract_from_dict(payload)

    payload = _build_contract().as_dict()
    payload["swing_definition"]["kind"] = "wrong_kind"
    with pytest.raises(phase50.MarketStructureResearchContractValidationError, match="unknown concept definition kind"):
        phase50.market_structure_research_contract_from_dict(payload)

    payload = _build_contract().as_dict()
    payload["trading_range_definition"]["parameters"]["maximum_width"] = 1
    with pytest.raises(phase50.MarketStructureResearchContractValidationError, match="maximum_width"):
        phase50.market_structure_research_contract_from_dict(payload)


def test_phase50_hash_changes_for_material_mutations():
    contract = _build_contract(metadata=_metadata_a())
    baseline_payload = copy.deepcopy(serialize_value(contract.canonical_payload(include_contract_id=False, include_contract_hash=False)))

    mutated_metadata = copy.deepcopy(baseline_payload)
    mutated_metadata["metadata"]["labels"] = ["alpha", "beta", "gamma"]
    assert phase50._hash_payload(mutated_metadata) != contract.contract_id

    mutated_timeframes = copy.deepcopy(baseline_payload)
    mutated_timeframes["supported_timeframes"] = ["1H", "4H", "1D"]
    assert phase50._hash_payload(mutated_timeframes) != contract.contract_id

    mutated_allowed_states = copy.deepcopy(baseline_payload)
    mutated_allowed_states["allowed_states"] = ["ambiguous", "determinate", "indeterminate", "invalid"]
    assert phase50._hash_payload(mutated_allowed_states) != contract.contract_id
