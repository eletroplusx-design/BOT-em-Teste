from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from domain.serialization import serialize_value

from .errors import HistoricalDataError, HistoricalDataIntegrityError, HistoricalDataValidationError

MARKET_STRUCTURE_RESEARCH_CONTRACT_SCHEMA_VERSION = 1
MARKET_STRUCTURE_RESEARCH_CONTRACT_NAME = "MarketStructureResearchContract"
MARKET_STRUCTURE_RESEARCH_CONTRACT_MARKET_DOMAIN = "market_structure_research"
MARKET_STRUCTURE_RESEARCH_CONTRACT_SUPPORTED_TIMEFRAMES: tuple[str, ...] = ("1D", "4H", "1H")
MARKET_STRUCTURE_RESEARCH_CONTRACT_ALLOWED_STATES: tuple[str, ...] = (
    "determinate",
    "indeterminate",
    "ambiguous",
    "invalid",
)
MARKET_STRUCTURE_RESEARCH_CONTRACT_VERSION = "phase50_market_structure_research_contract_v1"

class MarketStructureResearchContractError(HistoricalDataError):
    pass


class MarketStructureResearchContractValidationError(
    MarketStructureResearchContractError,
    HistoricalDataValidationError,
):
    pass


class MarketStructureResearchContractIntegrityError(
    MarketStructureResearchContractError,
    HistoricalDataIntegrityError,
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        serialize_value(_thaw_read_only_value(payload)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash_payload(payload: Any) -> str:
    try:
        return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    except (TypeError, ValueError) as exc:
        raise MarketStructureResearchContractValidationError("payload is not serializable.") from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketStructureResearchContractValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise MarketStructureResearchContractValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise MarketStructureResearchContractValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise MarketStructureResearchContractValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise MarketStructureResearchContractValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise MarketStructureResearchContractValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise MarketStructureResearchContractValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise MarketStructureResearchContractValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketStructureResearchContractValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _freeze_read_only_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_read_only_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_read_only_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_read_only_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_read_only_value(item) for item in value)
    if isinstance(value, frozenset):
        return frozenset(_freeze_read_only_value(item) for item in value)
    return value


def _thaw_read_only_value(value: Any) -> Any:
    if isinstance(value, MappingProxyType) or isinstance(value, Mapping):
        return {key: _thaw_read_only_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_thaw_read_only_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_thaw_read_only_value(item) for item in value)
    if isinstance(value, set) or isinstance(value, frozenset):
        thawed_items = [_thaw_read_only_value(item) for item in value]
        return tuple(sorted(thawed_items, key=_canonical_json))
    return value


def _require_str_tuple(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool = False,
    exact_length: int | None = None,
    unique: bool = True,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise MarketStructureResearchContractValidationError(f"{field_name} must be a sequence of strings.")
    normalized = tuple(_require_str(item, field_name) for item in value)
    if exact_length is not None and len(normalized) != exact_length:
        raise MarketStructureResearchContractValidationError(
            f"{field_name} must contain exactly {exact_length} items."
        )
    if not allow_empty and not normalized:
        raise MarketStructureResearchContractValidationError(f"{field_name} must not be empty.")
    if unique and len(set(normalized)) != len(normalized):
        raise MarketStructureResearchContractValidationError(f"{field_name} must not contain duplicates.")
    return normalized


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MarketStructureResearchContractValidationError(f"{field_name} must be a mapping.")
    return value


def _require_exact_keys(mapping: Mapping[str, Any], field_name: str, expected_keys: set[str]) -> None:
    extra = sorted(set(mapping) - expected_keys)
    missing = sorted(expected_keys - set(mapping))
    if extra or missing:
        parts: list[str] = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected {', '.join(extra)}")
        raise MarketStructureResearchContractValidationError(
            f"{field_name} has invalid fields: {'; '.join(parts)}."
        )


def _validate_positive_int_field(parameters: Mapping[str, Any], field_name: str) -> int:
    return _require_int(parameters[field_name], field_name)


def _validate_non_negative_int_field(parameters: Mapping[str, Any], field_name: str) -> int:
    return _require_int(parameters[field_name], field_name, allow_zero=True)


def _validate_bool_field(parameters: Mapping[str, Any], field_name: str) -> bool:
    return _require_bool(parameters[field_name], field_name)


def _validate_text_field(parameters: Mapping[str, Any], field_name: str) -> str:
    return _require_str(parameters[field_name], field_name)


def _validate_concept_parameters(kind: str, parameters: Mapping[str, Any]) -> Mapping[str, Any]:
    if kind == "swing_definition":
        expected = {
            "left_window",
            "right_window",
            "equality_tolerance_mode",
            "equality_tolerance_value",
            "tie_break_policy",
            "incomplete_window_policy",
            "candle_completion_required",
        }
        _require_exact_keys(parameters, kind, expected)
        _validate_positive_int_field(parameters, "left_window")
        _validate_positive_int_field(parameters, "right_window")
        _validate_text_field(parameters, "equality_tolerance_mode")
        _validate_non_negative_int_field(parameters, "equality_tolerance_value")
        _validate_text_field(parameters, "tie_break_policy")
        _validate_text_field(parameters, "incomplete_window_policy")
        _validate_bool_field(parameters, "candle_completion_required")
        return parameters
    if kind == "trend_structure_definition":
        expected = {
            "minimum_swing_count",
            "high_progression_tolerance",
            "low_progression_tolerance",
            "lateral_range_tolerance",
            "confirmation_policy",
            "conflict_policy",
        }
        _require_exact_keys(parameters, kind, expected)
        _validate_positive_int_field(parameters, "minimum_swing_count")
        _validate_non_negative_int_field(parameters, "high_progression_tolerance")
        _validate_non_negative_int_field(parameters, "low_progression_tolerance")
        _validate_non_negative_int_field(parameters, "lateral_range_tolerance")
        _validate_text_field(parameters, "confirmation_policy")
        _validate_text_field(parameters, "conflict_policy")
        return parameters
    if kind == "bos_definition":
        expected = {
            "reference_swing_type",
            "break_confirmation_mode",
            "wick_allowed",
            "close_required",
            "minimum_break_distance",
            "distance_mode",
            "minimum_displacement",
            "volume_confirmation_mode",
            "false_break_return_window",
        }
        _require_exact_keys(parameters, kind, expected)
        _validate_text_field(parameters, "reference_swing_type")
        _validate_text_field(parameters, "break_confirmation_mode")
        _validate_bool_field(parameters, "wick_allowed")
        _validate_bool_field(parameters, "close_required")
        _validate_non_negative_int_field(parameters, "minimum_break_distance")
        _validate_text_field(parameters, "distance_mode")
        _validate_non_negative_int_field(parameters, "minimum_displacement")
        _validate_text_field(parameters, "volume_confirmation_mode")
        _validate_positive_int_field(parameters, "false_break_return_window")
        return parameters
    if kind == "choch_definition":
        expected = {
            "required_prior_trend",
            "opposite_swing_type",
            "confirmation_mode",
            "minimum_break_distance",
            "displacement_requirement",
            "range_behavior",
            "conflict_policy",
        }
        _require_exact_keys(parameters, kind, expected)
        _validate_text_field(parameters, "required_prior_trend")
        _validate_text_field(parameters, "opposite_swing_type")
        _validate_text_field(parameters, "confirmation_mode")
        _validate_non_negative_int_field(parameters, "minimum_break_distance")
        _validate_non_negative_int_field(parameters, "displacement_requirement")
        _validate_text_field(parameters, "range_behavior")
        _validate_text_field(parameters, "conflict_policy")
        return parameters
    if kind == "liquidity_definition":
        expected = {
            "minimum_test_count",
            "level_tolerance_mode",
            "level_tolerance_value",
            "minimum_spacing_between_tests",
            "internal_liquidity_policy",
            "external_liquidity_policy",
            "protected_high_policy",
            "protected_low_policy",
        }
        _require_exact_keys(parameters, kind, expected)
        _validate_positive_int_field(parameters, "minimum_test_count")
        _validate_text_field(parameters, "level_tolerance_mode")
        _validate_non_negative_int_field(parameters, "level_tolerance_value")
        _validate_non_negative_int_field(parameters, "minimum_spacing_between_tests")
        _validate_text_field(parameters, "internal_liquidity_policy")
        _validate_text_field(parameters, "external_liquidity_policy")
        _validate_text_field(parameters, "protected_high_policy")
        _validate_text_field(parameters, "protected_low_policy")
        return parameters
    if kind == "liquidity_sweep_definition":
        expected = {
            "penetration_mode",
            "minimum_penetration",
            "maximum_penetration",
            "close_back_inside_required",
            "return_window",
            "breakout_confirmation_threshold",
            "invalidation_policy",
        }
        _require_exact_keys(parameters, kind, expected)
        _validate_text_field(parameters, "penetration_mode")
        _validate_non_negative_int_field(parameters, "minimum_penetration")
        _validate_non_negative_int_field(parameters, "maximum_penetration")
        _validate_bool_field(parameters, "close_back_inside_required")
        _validate_positive_int_field(parameters, "return_window")
        _validate_positive_int_field(parameters, "breakout_confirmation_threshold")
        _validate_text_field(parameters, "invalidation_policy")
        if parameters["maximum_penetration"] < parameters["minimum_penetration"]:
            raise MarketStructureResearchContractValidationError(
                "liquidity_sweep_definition.maximum_penetration must be greater than or equal to minimum_penetration."
            )
        return parameters
    if kind == "displacement_definition":
        expected = {
            "amplitude_mode",
            "minimum_amplitude",
            "maximum_candle_count",
            "close_location_threshold",
            "range_average_lookback",
            "atr_multiplier",
            "imbalance_required",
            "volume_policy",
        }
        _require_exact_keys(parameters, kind, expected)
        _validate_text_field(parameters, "amplitude_mode")
        _validate_non_negative_int_field(parameters, "minimum_amplitude")
        _validate_positive_int_field(parameters, "maximum_candle_count")
        _validate_non_negative_int_field(parameters, "close_location_threshold")
        _validate_positive_int_field(parameters, "range_average_lookback")
        _validate_positive_int_field(parameters, "atr_multiplier")
        _validate_bool_field(parameters, "imbalance_required")
        _validate_text_field(parameters, "volume_policy")
        return parameters
    if kind == "retest_definition":
        expected = {
            "target_level_type",
            "zone_tolerance_mode",
            "zone_tolerance_value",
            "maximum_depth",
            "maximum_return_window",
            "confirmation_mode",
            "invalidation_policy",
        }
        _require_exact_keys(parameters, kind, expected)
        _validate_text_field(parameters, "target_level_type")
        _validate_text_field(parameters, "zone_tolerance_mode")
        _validate_non_negative_int_field(parameters, "zone_tolerance_value")
        _validate_non_negative_int_field(parameters, "maximum_depth")
        _validate_positive_int_field(parameters, "maximum_return_window")
        _validate_text_field(parameters, "confirmation_mode")
        _validate_text_field(parameters, "invalidation_policy")
        return parameters
    if kind == "trading_range_definition":
        expected = {
            "minimum_duration",
            "minimum_support_tests",
            "minimum_resistance_tests",
            "minimum_width",
            "maximum_width",
            "width_mode",
            "boundary_tolerance",
            "false_break_policy",
            "start_condition",
            "end_condition",
            "classification_policy",
        }
        _require_exact_keys(parameters, kind, expected)
        _validate_positive_int_field(parameters, "minimum_duration")
        _validate_positive_int_field(parameters, "minimum_support_tests")
        _validate_positive_int_field(parameters, "minimum_resistance_tests")
        _validate_non_negative_int_field(parameters, "minimum_width")
        _validate_non_negative_int_field(parameters, "maximum_width")
        _validate_text_field(parameters, "width_mode")
        _validate_non_negative_int_field(parameters, "boundary_tolerance")
        _validate_text_field(parameters, "false_break_policy")
        _validate_text_field(parameters, "start_condition")
        _validate_text_field(parameters, "end_condition")
        _validate_text_field(parameters, "classification_policy")
        if parameters["maximum_width"] < parameters["minimum_width"]:
            raise MarketStructureResearchContractValidationError(
                "trading_range_definition.maximum_width must be greater than or equal to minimum_width."
            )
        return parameters
    if kind == "timeframe_context_definition":
        expected = {
            "macro_timeframe",
            "intermediate_timeframe",
            "micro_timeframe",
            "priority_policy",
            "alignment_policy",
            "conflict_policy",
            "missing_timeframe_policy",
        }
        _require_exact_keys(parameters, kind, expected)
        _validate_text_field(parameters, "macro_timeframe")
        _validate_text_field(parameters, "intermediate_timeframe")
        _validate_text_field(parameters, "micro_timeframe")
        _validate_text_field(parameters, "priority_policy")
        _validate_text_field(parameters, "alignment_policy")
        _validate_text_field(parameters, "conflict_policy")
        _validate_text_field(parameters, "missing_timeframe_policy")
        if len({parameters["macro_timeframe"], parameters["intermediate_timeframe"], parameters["micro_timeframe"]}) != 3:
            raise MarketStructureResearchContractValidationError(
                "timeframe_context_definition timeframes must be distinct."
            )
        return parameters
    if kind == "ambiguity_definition":
        expected = {
            "insufficient_data_policy",
            "conflicting_structure_policy",
            "equal_priority_policy",
            "incomplete_window_policy",
            "multiple_valid_interpretations_policy",
        }
        _require_exact_keys(parameters, kind, expected)
        _validate_text_field(parameters, "insufficient_data_policy")
        _validate_text_field(parameters, "conflicting_structure_policy")
        _validate_text_field(parameters, "equal_priority_policy")
        _validate_text_field(parameters, "incomplete_window_policy")
        _validate_text_field(parameters, "multiple_valid_interpretations_policy")
        return parameters
    raise MarketStructureResearchContractValidationError(f"unknown concept definition kind: {kind}.")


@dataclass(frozen=True, slots=True)
class _ConceptDefinition:
    kind: str
    description: str
    hypothesis: str
    inputs: tuple[str, ...]
    parameters: Mapping[str, Any] = field(repr=False)
    minimum_condition: str
    confirmation_condition: str
    invalidation_condition: str
    ambiguities: tuple[str, ...]
    deterministic_output: tuple[str, ...]
    positive_examples: tuple[str, ...]
    negative_examples: tuple[str, ...]
    common_errors: tuple[str, ...]
    known_limits: tuple[str, ...]
    states: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _require_str(self.kind, "kind"))
        object.__setattr__(self, "description", _require_str(self.description, "description"))
        object.__setattr__(self, "hypothesis", _require_str(self.hypothesis, "hypothesis"))
        object.__setattr__(self, "inputs", _require_str_tuple(self.inputs, "inputs"))
        if not isinstance(self.parameters, Mapping):
            raise MarketStructureResearchContractValidationError("parameters must be a mapping.")
        frozen_parameters = _freeze_read_only_value(dict(self.parameters))
        if not isinstance(frozen_parameters, Mapping):
            raise MarketStructureResearchContractValidationError("parameters must be a mapping.")
        object.__setattr__(self, "parameters", frozen_parameters)
        object.__setattr__(self, "minimum_condition", _require_str(self.minimum_condition, "minimum_condition"))
        object.__setattr__(self, "confirmation_condition", _require_str(self.confirmation_condition, "confirmation_condition"))
        object.__setattr__(self, "invalidation_condition", _require_str(self.invalidation_condition, "invalidation_condition"))
        object.__setattr__(self, "ambiguities", _require_str_tuple(self.ambiguities, "ambiguities"))
        object.__setattr__(self, "deterministic_output", _require_str_tuple(self.deterministic_output, "deterministic_output"))
        object.__setattr__(self, "positive_examples", _require_str_tuple(self.positive_examples, "positive_examples"))
        object.__setattr__(self, "negative_examples", _require_str_tuple(self.negative_examples, "negative_examples"))
        object.__setattr__(self, "common_errors", _require_str_tuple(self.common_errors, "common_errors"))
        object.__setattr__(self, "known_limits", _require_str_tuple(self.known_limits, "known_limits"))
        object.__setattr__(self, "states", _require_str_tuple(self.states, "states"))
        _validate_concept_parameters(self.kind, self.parameters)
        if len(set(self.states)) != len(self.states):
            raise MarketStructureResearchContractValidationError("states must not contain duplicates.")

    def canonical_payload(self, *, include_kind: bool = True) -> dict[str, Any]:
        payload = {
            "description": self.description,
            "hypothesis": self.hypothesis,
            "inputs": self.inputs,
            "parameters": _thaw_read_only_value(self.parameters),
            "minimum_condition": self.minimum_condition,
            "confirmation_condition": self.confirmation_condition,
            "invalidation_condition": self.invalidation_condition,
            "ambiguities": self.ambiguities,
            "deterministic_output": self.deterministic_output,
            "positive_examples": self.positive_examples,
            "negative_examples": self.negative_examples,
            "common_errors": self.common_errors,
            "known_limits": self.known_limits,
            "states": self.states,
        }
        if include_kind:
            payload["kind"] = self.kind
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_kind=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "_ConceptDefinition":
        if not isinstance(data, Mapping):
            raise MarketStructureResearchContractValidationError("concept definition must be a mapping.")
        mapping = dict(data)
        allowed = {
            "kind",
            "description",
            "hypothesis",
            "inputs",
            "parameters",
            "minimum_condition",
            "confirmation_condition",
            "invalidation_condition",
            "ambiguities",
            "deterministic_output",
            "positive_examples",
            "negative_examples",
            "common_errors",
            "known_limits",
            "states",
        }
        _require_exact_keys(mapping, "concept definition", allowed)
        try:
            return cls(
                kind=mapping["kind"],
                description=mapping["description"],
                hypothesis=mapping["hypothesis"],
                inputs=tuple(mapping["inputs"]),
                parameters=mapping["parameters"],
                minimum_condition=mapping["minimum_condition"],
                confirmation_condition=mapping["confirmation_condition"],
                invalidation_condition=mapping["invalidation_condition"],
                ambiguities=tuple(mapping["ambiguities"]),
                deterministic_output=tuple(mapping["deterministic_output"]),
                positive_examples=tuple(mapping["positive_examples"]),
                negative_examples=tuple(mapping["negative_examples"]),
                common_errors=tuple(mapping["common_errors"]),
                known_limits=tuple(mapping["known_limits"]),
                states=tuple(mapping.get("states", ())),
            )
        except KeyError as exc:
            raise MarketStructureResearchContractValidationError("concept definition is incomplete.") from exc


def _default_swing_definition() -> _ConceptDefinition:
    return _ConceptDefinition(
        kind="swing_definition",
        description="A swing high or swing low is a locally confirmed pivot derived from bounded left/right observations.",
        hypothesis="A deterministic pivot window can formalize swing structure without interpreting market intent.",
        inputs=("candles", "price_highs", "price_lows"),
        parameters={
            "left_window": 2,
            "right_window": 2,
            "equality_tolerance_mode": "ticks",
            "equality_tolerance_value": 0,
            "tie_break_policy": "reject_tied_extrema",
            "incomplete_window_policy": "indeterminate",
            "candle_completion_required": True,
        },
        minimum_condition="A full left and right observation window must be available.",
        confirmation_condition="The candidate must remain the unique extremum after the confirmation window closes.",
        invalidation_condition="A stronger or tied extremum under the tie-break policy invalidates the candidate.",
        ambiguities=("equal_extrema", "incomplete_window", "late_confirmation"),
        deterministic_output=(
            "confirmed_swing_high",
            "confirmed_swing_low",
            "candidate_swing_high",
            "candidate_swing_low",
            "indeterminate",
        ),
        positive_examples=(
            "A candle remains the highest point after two candles confirm to the right.",
            "A candle remains the lowest point after two candles confirm to the right.",
        ),
        negative_examples=(
            "A pivot is claimed before the right window closes.",
            "A tied high is accepted without an explicit tie-break rule.",
        ),
        common_errors=(
            "Using an incomplete candle to confirm the swing.",
            "Treating equal highs as confirmed swings without policy.",
        ),
        known_limits=(
            "Short windows can overfit noise.",
            "Long windows confirm late and can miss fast regime changes.",
        ),
        states=(
            "confirmed_swing_high",
            "confirmed_swing_low",
            "candidate_swing_high",
            "candidate_swing_low",
            "indeterminate",
        ),
    )


def _default_trend_structure_definition() -> _ConceptDefinition:
    return _ConceptDefinition(
        kind="trend_structure_definition",
        description="Trend structure formalizes progression through higher highs/lows or lower lows/highs.",
        hypothesis="A bounded swing progression can classify directional structure without a detector.",
        inputs=("swings", "swing_sequence", "price_series"),
        parameters={
            "minimum_swing_count": 3,
            "high_progression_tolerance": 0,
            "low_progression_tolerance": 0,
            "lateral_range_tolerance": 1,
            "confirmation_policy": "close_and_follow_through",
            "conflict_policy": "indeterminate",
        },
        minimum_condition="At least three swings are available for directional evaluation.",
        confirmation_condition="The progression of highs and lows remains monotonic within tolerance.",
        invalidation_condition="A conflicting swing progression violates the trend policy.",
        ambiguities=("range_overlap", "mixed_progression", "insufficient_swings"),
        deterministic_output=("bullish", "bearish", "lateral", "indeterminate", "ambiguous"),
        positive_examples=(
            "Higher highs and higher lows repeat across the required swing count.",
            "Lower highs and lower lows repeat across the required swing count.",
        ),
        negative_examples=(
            "A single higher high appears without supporting higher lows.",
            "Conflicting swings prevent a directional classification.",
        ),
        common_errors=(
            "Confusing a temporary impulse with a sustained trend.",
            "Ignoring mixed swing evidence inside a narrow range.",
        ),
        known_limits=(
            "Thin ranges can oscillate without valid directional structure.",
            "Trend classification can lag after a reversal begins.",
        ),
        states=("bullish", "bearish", "lateral", "indeterminate", "ambiguous"),
    )


def _default_bos_definition() -> _ConceptDefinition:
    return _ConceptDefinition(
        kind="bos_definition",
        description="Break of structure formalizes a structural level break rather than a generic candle break.",
        hypothesis="A BOS can be defined from a structural swing, a confirmation mode, and a displacement threshold.",
        inputs=("price_series", "swings", "trend_context"),
        parameters={
            "reference_swing_type": "swing_high",
            "break_confirmation_mode": "close_beyond_level",
            "wick_allowed": True,
            "close_required": True,
            "minimum_break_distance": 1,
            "distance_mode": "ticks",
            "minimum_displacement": 1,
            "volume_confirmation_mode": "optional",
            "false_break_return_window": 3,
        },
        minimum_condition="A structural swing reference and a candidate break are both available.",
        confirmation_condition="Price closes beyond the structural level with minimum displacement.",
        invalidation_condition="Price returns inside the structure before the return window closes.",
        ambiguities=("wick_only_break", "close_without_displacement", "reclaim_before_window"),
        deterministic_output=("valid_bos", "failed_bos", "false_break", "indeterminate"),
        positive_examples=(
            "A close beyond the structural level is followed by the required displacement.",
            "A wick breach is accepted only when the close confirmation policy allows it.",
        ),
        negative_examples=(
            "A candle high exceeds the prior candle but the structural level remains intact.",
            "A wick poke reverses before the return window ends.",
        ),
        common_errors=(
            "Equating a candle engulf with a structural break.",
            "Ignoring the break confirmation mode.",
        ),
        known_limits=(
            "Breaks in thin liquidity can reclaim quickly.",
            "Confirmation lags when the return window is conservative.",
        ),
        states=("valid_bos", "failed_bos", "false_break", "indeterminate"),
    )


def _default_choch_definition() -> _ConceptDefinition:
    return _ConceptDefinition(
        kind="choch_definition",
        description="Change of character formalizes a directional regime change against the prior trend.",
        hypothesis="A trend-aware break of the opposite swing can distinguish CHoCH from continuation BOS.",
        inputs=("price_series", "swings", "trend_context"),
        parameters={
            "required_prior_trend": "bullish",
            "opposite_swing_type": "swing_low",
            "confirmation_mode": "close_beyond_level",
            "minimum_break_distance": 1,
            "displacement_requirement": 1,
            "range_behavior": "indeterminate",
            "conflict_policy": "ambiguous",
        },
        minimum_condition="A prior directional trend is available.",
        confirmation_condition="The opposite structural swing is broken with the required confirmation mode.",
        invalidation_condition="Range behavior or conflicting evidence prevents a safe regime change classification.",
        ambiguities=("range_context", "opposing_breaks", "late_confirmation"),
        deterministic_output=("valid_choch", "failed_choch", "indeterminate", "ambiguous"),
        positive_examples=(
            "A bullish sequence loses its structural low and closes through it.",
            "A bearish sequence loses its structural high and closes through it.",
        ),
        negative_examples=(
            "A continuation break is mislabeled as CHoCH.",
            "Range conditions are forced into a regime change label.",
        ),
        common_errors=(
            "Treating every BOS as a CHoCH.",
            "Ignoring prior trend context.",
        ),
        known_limits=(
            "Flat ranges can produce repeated false CHoCH candidates.",
            "The label is regime-sensitive and may lag on noisy transitions.",
        ),
        states=("valid_choch", "failed_choch", "indeterminate", "ambiguous"),
    )


def _default_liquidity_definition() -> _ConceptDefinition:
    return _ConceptDefinition(
        kind="liquidity_definition",
        description="Liquidity formalizes clusters of comparable highs or lows and protected levels.",
        hypothesis="Repeated tests around an observed level can define liquidity context without treating it as a signal.",
        inputs=("price_series", "swings", "level_clusters"),
        parameters={
            "minimum_test_count": 2,
            "level_tolerance_mode": "ticks",
            "level_tolerance_value": 1,
            "minimum_spacing_between_tests": 1,
            "internal_liquidity_policy": "context",
            "external_liquidity_policy": "context",
            "protected_high_policy": "track",
            "protected_low_policy": "track",
        },
        minimum_condition="At least one candidate level cluster is available.",
        confirmation_condition="Multiple tests occur within the tolerance and spacing policy.",
        invalidation_condition="The cluster loses observability or the tolerance window is exceeded.",
        ambiguities=("single_test_cluster", "wide_spacing", "multiple_nearby_levels"),
        deterministic_output=("liquidity_context", "protected_high", "protected_low", "indeterminate"),
        positive_examples=(
            "Equal highs form a liquidity pool under the configured tolerance.",
            "Equal lows form a liquidity pool under the configured tolerance.",
        ),
        negative_examples=(
            "A single isolated high is labeled as liquidity without repeated tests.",
            "A level is protected even though the spacing policy is violated.",
        ),
        common_errors=(
            "Using liquidity as a standalone entry signal.",
            "Ignoring the minimum test count.",
        ),
        known_limits=(
            "Liquidity clusters can overlap in congested ranges.",
            "Tolerance too wide collapses distinct levels.",
        ),
        states=("liquidity_context", "protected_high", "protected_low", "indeterminate"),
    )


def _default_liquidity_sweep_definition() -> _ConceptDefinition:
    return _ConceptDefinition(
        kind="liquidity_sweep_definition",
        description="Liquidity sweep formalizes a level penetration followed by a controlled return inside the range.",
        hypothesis="A sweep is distinguishable from breakout when penetration and reclaim conditions are explicit.",
        inputs=("price_series", "liquidity_context", "range_boundary"),
        parameters={
            "penetration_mode": "wick_and_close",
            "minimum_penetration": 1,
            "maximum_penetration": 3,
            "close_back_inside_required": True,
            "return_window": 3,
            "breakout_confirmation_threshold": 2,
            "invalidation_policy": "close_outside",
        },
        minimum_condition="A protected level exists and a penetration is observable.",
        confirmation_condition="The level is reclaimed inside the configured return window.",
        invalidation_condition="The price remains outside the level beyond the breakout confirmation threshold.",
        ambiguities=("weak_penetration", "slow_reclaim", "breakout_overlap"),
        deterministic_output=("valid_sweep", "failed_sweep", "breakout", "indeterminate"),
        positive_examples=(
            "Price wicks through a protected high and closes back inside the level.",
            "Price wicks below a protected low and closes back inside the level.",
        ),
        negative_examples=(
            "A penetration persists outside the range and is still called a sweep.",
            "A close outside the level is ignored.",
        ),
        common_errors=(
            "Confusing a clean breakout with a sweep.",
            "Ignoring the return window.",
        ),
        known_limits=(
            "Thin markets can both sweep and break in the same move.",
            "Long return windows can blur the distinction from breakout.",
        ),
        states=("valid_sweep", "failed_sweep", "breakout", "indeterminate"),
    )


def _default_displacement_definition() -> _ConceptDefinition:
    return _ConceptDefinition(
        kind="displacement_definition",
        description="Displacement formalizes directional expansion after a structural break or sweep.",
        hypothesis="A measurable expansion in range and close location can define displacement without subjective labels.",
        inputs=("price_series", "break_events", "range_context"),
        parameters={
            "amplitude_mode": "atr_multiple",
            "minimum_amplitude": 2,
            "maximum_candle_count": 3,
            "close_location_threshold": 75,
            "range_average_lookback": 20,
            "atr_multiplier": 2,
            "imbalance_required": True,
            "volume_policy": "optional",
        },
        minimum_condition="A break event or sweep context is present.",
        confirmation_condition="The move expands by the configured amplitude within the maximum candle count.",
        invalidation_condition="The move fails to expand or closes too far from the expected extremity.",
        ambiguities=("range_contraction", "insufficient_amplitude", "late_close"),
        deterministic_output=("valid_displacement", "insufficient_displacement", "indeterminate"),
        positive_examples=(
            "Price expands two ATRs within three candles after a structural break.",
            "A strong directional move closes near the candle extremity after reclaiming a level.",
        ),
        negative_examples=(
            "A candle is visually strong but fails the minimum amplitude.",
            "The move expands slowly beyond the maximum candle count.",
        ),
        common_errors=(
            "Calling any large candle a displacement without amplitude criteria.",
            "Ignoring the close location threshold.",
        ),
        known_limits=(
            "ATR expansion can lag in regime shifts.",
            "Amplitude thresholds can be asset-specific.",
        ),
        states=("valid_displacement", "insufficient_displacement", "indeterminate"),
    )


def _default_retest_definition() -> _ConceptDefinition:
    return _ConceptDefinition(
        kind="retest_definition",
        description="Retest formalizes a controlled revisit to a broken level or zone.",
        hypothesis="A retest can be separated from random return by tolerance, depth, and timing constraints.",
        inputs=("price_series", "level", "break_context"),
        parameters={
            "target_level_type": "swing",
            "zone_tolerance_mode": "ticks",
            "zone_tolerance_value": 1,
            "maximum_depth": 2,
            "maximum_return_window": 5,
            "confirmation_mode": "rejection",
            "invalidation_policy": "close_through_level",
        },
        minimum_condition="A prior level or zone has been identified.",
        confirmation_condition="Price returns to the zone within the permitted depth and timing and respects the confirmation mode.",
        invalidation_condition="Price closes through the level or exceeds the return window.",
        ambiguities=("random_return", "deep_penetration", "late_revisit"),
        deterministic_output=("valid_retest", "failed_retest", "random_return", "indeterminate"),
        positive_examples=(
            "Price revisits a broken swing and rejects from the zone.",
            "Price revisits a range boundary inside the return window and rejects cleanly.",
        ),
        negative_examples=(
            "A late revisit occurs outside the maximum return window.",
            "A deep penetration closes through the level but is still called a retest.",
        ),
        common_errors=(
            "Confusing a retest with a random drift back to a level.",
            "Ignoring the maximum depth constraint.",
        ),
        known_limits=(
            "Noisy markets can revisit zones repeatedly.",
            "Timing constraints may reject valid slow retests.",
        ),
        states=("valid_retest", "failed_retest", "random_return", "indeterminate"),
    )


def _default_trading_range_definition() -> _ConceptDefinition:
    return _ConceptDefinition(
        kind="trading_range_definition",
        description="Trading range formalizes a bounded market regime with repeated boundary interaction.",
        hypothesis="A range can be defined by duration, repeated support/resistance tests, and width constraints.",
        inputs=("price_series", "support_boundary", "resistance_boundary"),
        parameters={
            "minimum_duration": 6,
            "minimum_support_tests": 2,
            "minimum_resistance_tests": 2,
            "minimum_width": 2,
            "maximum_width": 20,
            "width_mode": "ticks",
            "boundary_tolerance": 1,
            "false_break_policy": "require_reclaim",
            "start_condition": "two_sided_test",
            "end_condition": "breakout",
            "classification_policy": "unclassified_only",
        },
        minimum_condition="Both boundaries and the minimum duration are available.",
        confirmation_condition="Support and resistance are tested repeatedly inside the width bounds.",
        invalidation_condition="The range breaks beyond tolerance or violates the width constraint.",
        ambiguities=("narrow_expansion", "late_breakout", "single_sided_test"),
        deterministic_output=(
            "valid_trading_range",
            "accumulation_candidate",
            "distribution_candidate",
            "reaccumulation_candidate",
            "redistribution_candidate",
            "unclassified_range",
            "indeterminate",
        ),
        positive_examples=(
            "Price rotates between boundaries for the minimum duration with repeated tests.",
            "Boundary tests stay within the configured tolerance and width.",
        ),
        negative_examples=(
            "A short pause is labeled a range without enough tests.",
            "A breakout is still treated as a range after the end condition fires.",
        ),
        common_errors=(
            "Labeling accumulation or distribution without confirmation.",
            "Ignoring the minimum duration.",
        ),
        known_limits=(
            "Ranges can later resolve into trend continuation or reversal.",
            "Width bounds are instrument-specific.",
        ),
        states=(
            "valid_trading_range",
            "accumulation_candidate",
            "distribution_candidate",
            "reaccumulation_candidate",
            "redistribution_candidate",
            "unclassified_range",
            "indeterminate",
        ),
    )


def _default_timeframe_context_definition() -> _ConceptDefinition:
    return _ConceptDefinition(
        kind="timeframe_context_definition",
        description="Timeframe context formalizes macro, intermediate and micro alignment without hidden overrides.",
        hypothesis="A deterministic timeframe hierarchy can expose alignment and conflict explicitly.",
        inputs=("macro_timeframe", "intermediate_timeframe", "micro_timeframe"),
        parameters={
            "macro_timeframe": MARKET_STRUCTURE_RESEARCH_CONTRACT_SUPPORTED_TIMEFRAMES[0],
            "intermediate_timeframe": MARKET_STRUCTURE_RESEARCH_CONTRACT_SUPPORTED_TIMEFRAMES[1],
            "micro_timeframe": MARKET_STRUCTURE_RESEARCH_CONTRACT_SUPPORTED_TIMEFRAMES[2],
            "priority_policy": "macro_over_micro",
            "alignment_policy": "aligned",
            "conflict_policy": "indeterminate",
            "missing_timeframe_policy": "reject",
        },
        minimum_condition="The three ordered timeframes are available.",
        confirmation_condition="Macro, intermediate and micro contexts align under the priority policy.",
        invalidation_condition="Any timeframe is missing or the hierarchy conflicts.",
        ambiguities=("missing_macro", "missing_micro", "conflicting_context"),
        deterministic_output=("aligned", "conflicted", "indeterminate", "ambiguous"),
        positive_examples=(
            "A bullish macro context is not silently overridden by a micro counter-move.",
            "The three timeframes agree under the configured priority policy.",
        ),
        negative_examples=(
            "Micro context is allowed to overwrite macro context silently.",
            "A missing timeframe is ignored.",
        ),
        common_errors=(
            "Using a single timeframe as if it represented the entire market.",
            "Ignoring conflicts between macro and micro structures.",
        ),
        known_limits=(
            "Timeframe alignment may differ across regimes.",
            "Higher timeframes can lag lower timeframe transitions.",
        ),
        states=("aligned", "conflicted", "indeterminate", "ambiguous"),
    )


def _default_ambiguity_definition() -> _ConceptDefinition:
    return _ConceptDefinition(
        kind="ambiguity_definition",
        description="Ambiguity formalizes situations where evidence is insufficient or multiple interpretations are equally valid.",
        hypothesis="Explicit ambiguity handling prevents the contract from pretending certainty where none exists.",
        inputs=("evidence_set", "conflict_context", "window_state"),
        parameters={
            "insufficient_data_policy": "indeterminate",
            "conflicting_structure_policy": "ambiguous",
            "equal_priority_policy": "ambiguous",
            "incomplete_window_policy": "indeterminate",
            "multiple_valid_interpretations_policy": "ambiguous",
        },
        minimum_condition="At least one ambiguous or incomplete observation is present.",
        confirmation_condition="The policy resolves the ambiguity into a deterministic non-operational state.",
        invalidation_condition="The contract pretends to know more than the evidence supports.",
        ambiguities=("insufficient_data", "conflicting_structure", "equal_priority", "incomplete_window"),
        deterministic_output=("determinate", "indeterminate", "ambiguous", "invalid"),
        positive_examples=(
            "Incomplete windows are marked indeterminate instead of forced into a trend label.",
            "Conflicting structures are marked ambiguous instead of arbitrarily resolved.",
        ),
        negative_examples=(
            "A missing candle is treated as a confirmed swing.",
            "Competing interpretations are forced into a single label without policy.",
        ),
        common_errors=(
            "Falling back to intuition when the evidence is insufficient.",
            "Using ambiguous evidence as if it were confirmed structure.",
        ),
        known_limits=(
            "Ambiguity will appear often in low-liquidity or thin-data regimes.",
            "The policy is intentionally conservative and may reject borderline cases.",
        ),
        states=("determinate", "indeterminate", "ambiguous", "invalid"),
    )


_EXPECTED_SWING_DEFINITION = _default_swing_definition()
_EXPECTED_TREND_STRUCTURE_DEFINITION = _default_trend_structure_definition()
_EXPECTED_BOS_DEFINITION = _default_bos_definition()
_EXPECTED_CHOCH_DEFINITION = _default_choch_definition()
_EXPECTED_LIQUIDITY_DEFINITION = _default_liquidity_definition()
_EXPECTED_LIQUIDITY_SWEEP_DEFINITION = _default_liquidity_sweep_definition()
_EXPECTED_DISPLACEMENT_DEFINITION = _default_displacement_definition()
_EXPECTED_RETEST_DEFINITION = _default_retest_definition()
_EXPECTED_TRADING_RANGE_DEFINITION = _default_trading_range_definition()
_EXPECTED_TIMEFRAME_CONTEXT_DEFINITION = _default_timeframe_context_definition()
_EXPECTED_AMBIGUITY_DEFINITION = _default_ambiguity_definition()
_EXPECTED_INVALIDATION_RULES = MappingProxyType(
    {
        "swing_definition": ("incomplete_window", "tie_without_policy"),
        "trend_structure_definition": ("conflicting_progression", "insufficient_swings"),
        "bos_definition": ("close_back_inside", "insufficient_displacement"),
        "choch_definition": ("prior_trend_missing", "range_conflict"),
        "liquidity_definition": ("single_test_cluster", "tolerance_violation"),
        "liquidity_sweep_definition": ("no_return_inside", "breakout_confirmation"),
        "displacement_definition": ("amplitude_shortfall", "late_completion"),
        "retest_definition": ("depth_exceeded", "window_expired"),
        "trading_range_definition": ("width_violation", "confirmation_missing"),
        "timeframe_context_definition": ("timeframe_missing", "cross_timeframe_conflict"),
        "ambiguity_definition": ("insufficient_information", "multiple_equal_interpretations"),
    }
)


@dataclass(frozen=True, slots=True)
class MarketStructureResearchContract:
    schema_version: int = MARKET_STRUCTURE_RESEARCH_CONTRACT_SCHEMA_VERSION
    contract_name: str = MARKET_STRUCTURE_RESEARCH_CONTRACT_NAME
    market_domain: str = MARKET_STRUCTURE_RESEARCH_CONTRACT_MARKET_DOMAIN
    supported_timeframes: tuple[str, ...] = MARKET_STRUCTURE_RESEARCH_CONTRACT_SUPPORTED_TIMEFRAMES
    swing_definition: _ConceptDefinition = field(default_factory=_default_swing_definition)
    trend_structure_definition: _ConceptDefinition = field(default_factory=_default_trend_structure_definition)
    bos_definition: _ConceptDefinition = field(default_factory=_default_bos_definition)
    choch_definition: _ConceptDefinition = field(default_factory=_default_choch_definition)
    liquidity_definition: _ConceptDefinition = field(default_factory=_default_liquidity_definition)
    liquidity_sweep_definition: _ConceptDefinition = field(default_factory=_default_liquidity_sweep_definition)
    displacement_definition: _ConceptDefinition = field(default_factory=_default_displacement_definition)
    retest_definition: _ConceptDefinition = field(default_factory=_default_retest_definition)
    trading_range_definition: _ConceptDefinition = field(default_factory=_default_trading_range_definition)
    timeframe_context_definition: _ConceptDefinition = field(default_factory=_default_timeframe_context_definition)
    ambiguity_definition: _ConceptDefinition = field(default_factory=_default_ambiguity_definition)
    invalidation_rules: Mapping[str, Any] = field(default_factory=lambda: _EXPECTED_INVALIDATION_RULES, repr=False)
    allowed_states: tuple[str, ...] = MARKET_STRUCTURE_RESEARCH_CONTRACT_ALLOWED_STATES
    created_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False)
    contract_id: str = ""
    contract_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "contract_name", _require_str(self.contract_name, "contract_name"))
        object.__setattr__(self, "market_domain", _require_str(self.market_domain, "market_domain"))
        object.__setattr__(
            self,
            "supported_timeframes",
            _require_str_tuple(self.supported_timeframes, "supported_timeframes", exact_length=3),
        )
        for field_name in (
            "swing_definition",
            "trend_structure_definition",
            "bos_definition",
            "choch_definition",
            "liquidity_definition",
            "liquidity_sweep_definition",
            "displacement_definition",
            "retest_definition",
            "trading_range_definition",
            "timeframe_context_definition",
            "ambiguity_definition",
        ):
            block = getattr(self, field_name)
            if not isinstance(block, _ConceptDefinition):
                raise MarketStructureResearchContractValidationError(
                    f"{field_name} must be a concept definition."
                )
        if not isinstance(self.invalidation_rules, Mapping):
            raise MarketStructureResearchContractValidationError("invalidation_rules must be a mapping.")
        object.__setattr__(self, "invalidation_rules", _freeze_read_only_value(dict(self.invalidation_rules)))
        object.__setattr__(self, "allowed_states", _require_str_tuple(self.allowed_states, "allowed_states"))
        object.__setattr__(self, "created_at_utc", _require_utc_datetime(self.created_at_utc, "created_at_utc"))
        if not isinstance(self.metadata, Mapping):
            raise MarketStructureResearchContractValidationError("metadata must be a mapping.")
        object.__setattr__(self, "metadata", _freeze_read_only_value(dict(self.metadata)))
        object.__setattr__(self, "contract_id", _require_str(self.contract_id, "contract_id") if self.contract_id else "")
        object.__setattr__(self, "contract_hash", _require_str(self.contract_hash, "contract_hash") if self.contract_hash else "")

        if self.schema_version != MARKET_STRUCTURE_RESEARCH_CONTRACT_SCHEMA_VERSION:
            raise MarketStructureResearchContractValidationError("schema_version must be 1.")
        if self.contract_name != MARKET_STRUCTURE_RESEARCH_CONTRACT_NAME:
            raise MarketStructureResearchContractValidationError(
                "contract_name must remain MarketStructureResearchContract."
            )
        if self.market_domain != MARKET_STRUCTURE_RESEARCH_CONTRACT_MARKET_DOMAIN:
            raise MarketStructureResearchContractValidationError(
                "market_domain must remain market_structure_research."
            )
        if self.supported_timeframes != MARKET_STRUCTURE_RESEARCH_CONTRACT_SUPPORTED_TIMEFRAMES:
            raise MarketStructureResearchContractValidationError(
                "supported_timeframes must remain the canonical macro/intermediate/micro tuple."
            )
        if self.timeframe_context_definition.parameters["macro_timeframe"] != self.supported_timeframes[0]:
            raise MarketStructureResearchContractIntegrityError(
                "timeframe_context_definition macro_timeframe mismatch."
            )
        if self.timeframe_context_definition.parameters["intermediate_timeframe"] != self.supported_timeframes[1]:
            raise MarketStructureResearchContractIntegrityError(
                "timeframe_context_definition intermediate_timeframe mismatch."
            )
        if self.timeframe_context_definition.parameters["micro_timeframe"] != self.supported_timeframes[2]:
            raise MarketStructureResearchContractIntegrityError(
                "timeframe_context_definition micro_timeframe mismatch."
            )
        if self.allowed_states != MARKET_STRUCTURE_RESEARCH_CONTRACT_ALLOWED_STATES:
            raise MarketStructureResearchContractValidationError(
                "allowed_states must remain determinate, indeterminate, ambiguous, invalid."
            )
        if self.invalidation_rules != _EXPECTED_INVALIDATION_RULES:
            raise MarketStructureResearchContractValidationError("invalidation_rules diverge from the canonical contract.")
        if self.swing_definition.as_dict() != _EXPECTED_SWING_DEFINITION.as_dict():
            raise MarketStructureResearchContractValidationError("swing_definition diverges from the canonical contract.")
        if self.trend_structure_definition.as_dict() != _EXPECTED_TREND_STRUCTURE_DEFINITION.as_dict():
            raise MarketStructureResearchContractValidationError(
                "trend_structure_definition diverges from the canonical contract."
            )
        if self.bos_definition.as_dict() != _EXPECTED_BOS_DEFINITION.as_dict():
            raise MarketStructureResearchContractValidationError("bos_definition diverges from the canonical contract.")
        if self.choch_definition.as_dict() != _EXPECTED_CHOCH_DEFINITION.as_dict():
            raise MarketStructureResearchContractValidationError("choch_definition diverges from the canonical contract.")
        if self.liquidity_definition.as_dict() != _EXPECTED_LIQUIDITY_DEFINITION.as_dict():
            raise MarketStructureResearchContractValidationError(
                "liquidity_definition diverges from the canonical contract."
            )
        if self.liquidity_sweep_definition.as_dict() != _EXPECTED_LIQUIDITY_SWEEP_DEFINITION.as_dict():
            raise MarketStructureResearchContractValidationError(
                "liquidity_sweep_definition diverges from the canonical contract."
            )
        if self.displacement_definition.as_dict() != _EXPECTED_DISPLACEMENT_DEFINITION.as_dict():
            raise MarketStructureResearchContractValidationError(
                "displacement_definition diverges from the canonical contract."
            )
        if self.retest_definition.as_dict() != _EXPECTED_RETEST_DEFINITION.as_dict():
            raise MarketStructureResearchContractValidationError("retest_definition diverges from the canonical contract.")
        if self.trading_range_definition.as_dict() != _EXPECTED_TRADING_RANGE_DEFINITION.as_dict():
            raise MarketStructureResearchContractValidationError(
                "trading_range_definition diverges from the canonical contract."
            )
        if self.timeframe_context_definition.as_dict() != _EXPECTED_TIMEFRAME_CONTEXT_DEFINITION.as_dict():
            raise MarketStructureResearchContractValidationError(
                "timeframe_context_definition diverges from the canonical contract."
            )
        if self.ambiguity_definition.as_dict() != _EXPECTED_AMBIGUITY_DEFINITION.as_dict():
            raise MarketStructureResearchContractValidationError(
                "ambiguity_definition diverges from the canonical contract."
            )

        expected_contract_id = _hash_payload(self._contract_id_payload())
        if self.contract_id:
            if self.contract_id != expected_contract_id:
                raise MarketStructureResearchContractIntegrityError("contract_id mismatch.")
        else:
            object.__setattr__(self, "contract_id", expected_contract_id)

        expected_contract_hash = _hash_payload(self._contract_hash_payload())
        if self.contract_hash:
            if self.contract_hash != expected_contract_hash:
                raise MarketStructureResearchContractIntegrityError("contract_hash mismatch.")
        else:
            object.__setattr__(self, "contract_hash", expected_contract_hash)

    def _contract_id_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_name": self.contract_name,
            "market_domain": self.market_domain,
            "supported_timeframes": self.supported_timeframes,
            "swing_definition": self.swing_definition.as_dict(),
            "trend_structure_definition": self.trend_structure_definition.as_dict(),
            "bos_definition": self.bos_definition.as_dict(),
            "choch_definition": self.choch_definition.as_dict(),
            "liquidity_definition": self.liquidity_definition.as_dict(),
            "liquidity_sweep_definition": self.liquidity_sweep_definition.as_dict(),
            "displacement_definition": self.displacement_definition.as_dict(),
            "retest_definition": self.retest_definition.as_dict(),
            "trading_range_definition": self.trading_range_definition.as_dict(),
            "timeframe_context_definition": self.timeframe_context_definition.as_dict(),
            "ambiguity_definition": self.ambiguity_definition.as_dict(),
            "invalidation_rules": _thaw_read_only_value(self.invalidation_rules),
            "allowed_states": self.allowed_states,
            "metadata": _thaw_read_only_value(self.metadata),
        }

    def _contract_hash_payload(self) -> dict[str, Any]:
        payload = self._contract_id_payload()
        payload["contract_id"] = self.contract_id
        return payload

    def canonical_payload(self, *, include_contract_id: bool = True, include_contract_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "contract_name": self.contract_name,
            "market_domain": self.market_domain,
            "supported_timeframes": self.supported_timeframes,
            "swing_definition": self.swing_definition.as_dict(),
            "trend_structure_definition": self.trend_structure_definition.as_dict(),
            "bos_definition": self.bos_definition.as_dict(),
            "choch_definition": self.choch_definition.as_dict(),
            "liquidity_definition": self.liquidity_definition.as_dict(),
            "liquidity_sweep_definition": self.liquidity_sweep_definition.as_dict(),
            "displacement_definition": self.displacement_definition.as_dict(),
            "retest_definition": self.retest_definition.as_dict(),
            "trading_range_definition": self.trading_range_definition.as_dict(),
            "timeframe_context_definition": self.timeframe_context_definition.as_dict(),
            "ambiguity_definition": self.ambiguity_definition.as_dict(),
            "invalidation_rules": _thaw_read_only_value(self.invalidation_rules),
            "allowed_states": self.allowed_states,
            "created_at_utc": _utc_iso(self.created_at_utc),
            "metadata": _thaw_read_only_value(self.metadata),
        }
        if include_contract_id:
            payload["contract_id"] = self.contract_id
        if include_contract_hash:
            payload["contract_hash"] = self.contract_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_contract_id=True, include_contract_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MarketStructureResearchContract":
        if not isinstance(data, Mapping):
            raise MarketStructureResearchContractValidationError("market structure research contract must be a mapping.")
        mapping = dict(data)
        allowed = {
            "schema_version",
            "contract_name",
            "market_domain",
            "supported_timeframes",
            "swing_definition",
            "trend_structure_definition",
            "bos_definition",
            "choch_definition",
            "liquidity_definition",
            "liquidity_sweep_definition",
            "displacement_definition",
            "retest_definition",
            "trading_range_definition",
            "timeframe_context_definition",
            "ambiguity_definition",
            "invalidation_rules",
            "allowed_states",
            "created_at_utc",
            "metadata",
            "contract_id",
            "contract_hash",
        }
        _require_exact_keys(mapping, "market structure research contract", allowed)
        try:
            return cls(
                schema_version=mapping["schema_version"],
                contract_name=mapping["contract_name"],
                market_domain=mapping["market_domain"],
                supported_timeframes=tuple(mapping["supported_timeframes"]),
                swing_definition=_ConceptDefinition.from_dict(mapping["swing_definition"]),
                trend_structure_definition=_ConceptDefinition.from_dict(mapping["trend_structure_definition"]),
                bos_definition=_ConceptDefinition.from_dict(mapping["bos_definition"]),
                choch_definition=_ConceptDefinition.from_dict(mapping["choch_definition"]),
                liquidity_definition=_ConceptDefinition.from_dict(mapping["liquidity_definition"]),
                liquidity_sweep_definition=_ConceptDefinition.from_dict(mapping["liquidity_sweep_definition"]),
                displacement_definition=_ConceptDefinition.from_dict(mapping["displacement_definition"]),
                retest_definition=_ConceptDefinition.from_dict(mapping["retest_definition"]),
                trading_range_definition=_ConceptDefinition.from_dict(mapping["trading_range_definition"]),
                timeframe_context_definition=_ConceptDefinition.from_dict(mapping["timeframe_context_definition"]),
                ambiguity_definition=_ConceptDefinition.from_dict(mapping["ambiguity_definition"]),
                invalidation_rules=mapping["invalidation_rules"],
                allowed_states=tuple(mapping["allowed_states"]),
                created_at_utc=mapping["created_at_utc"],
                metadata=mapping["metadata"],
                contract_id=mapping["contract_id"],
                contract_hash=mapping["contract_hash"],
            )
        except KeyError as exc:
            raise MarketStructureResearchContractValidationError(
                "market structure research contract is incomplete."
            ) from exc


def build_market_structure_research_contract(
    *,
    created_at_utc: datetime | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> MarketStructureResearchContract:
    contract = MarketStructureResearchContract(
        created_at_utc=created_at_utc or datetime.now(timezone.utc),
        metadata=metadata or {},
    )
    if contract.as_dict() != serialize_value(contract.canonical_payload(include_contract_id=True, include_contract_hash=True)):
        raise MarketStructureResearchContractIntegrityError("market structure research contract payload mismatch.")
    return contract


def verify_market_structure_research_contract(
    contract: MarketStructureResearchContract,
) -> MarketStructureResearchContract:
    if not isinstance(contract, MarketStructureResearchContract):
        raise MarketStructureResearchContractValidationError("market structure research contract is required.")
    expected_contract_id = _hash_payload(contract._contract_id_payload())
    if contract.contract_id != expected_contract_id:
        raise MarketStructureResearchContractIntegrityError("contract_id mismatch.")
    expected_contract_hash = _hash_payload(contract._contract_hash_payload())
    if contract.contract_hash != expected_contract_hash:
        raise MarketStructureResearchContractIntegrityError("contract_hash mismatch.")
    return contract


def market_structure_research_contract_from_dict(
    data: Mapping[str, Any],
) -> MarketStructureResearchContract:
    return MarketStructureResearchContract.from_dict(data)


def market_structure_research_contract_to_dict(
    contract: MarketStructureResearchContract,
) -> dict[str, Any]:
    if not isinstance(contract, MarketStructureResearchContract):
        raise MarketStructureResearchContractValidationError("market structure research contract is required.")
    return contract.as_dict()


__all__ = [
    "MARKET_STRUCTURE_RESEARCH_CONTRACT_ALLOWED_STATES",
    "MARKET_STRUCTURE_RESEARCH_CONTRACT_MARKET_DOMAIN",
    "MARKET_STRUCTURE_RESEARCH_CONTRACT_NAME",
    "MARKET_STRUCTURE_RESEARCH_CONTRACT_SCHEMA_VERSION",
    "MARKET_STRUCTURE_RESEARCH_CONTRACT_SUPPORTED_TIMEFRAMES",
    "MARKET_STRUCTURE_RESEARCH_CONTRACT_VERSION",
    "MarketStructureResearchContract",
    "MarketStructureResearchContractError",
    "MarketStructureResearchContractIntegrityError",
    "MarketStructureResearchContractValidationError",
    "build_market_structure_research_contract",
    "market_structure_research_contract_from_dict",
    "market_structure_research_contract_to_dict",
    "verify_market_structure_research_contract",
]
