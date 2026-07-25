"""Research-only robustness dossier for the Phase 15 historical futures pipeline.

This module consumes the immutable Phase 14C temporal consistency report as the
canonical source of the frozen reference, validation, and test windows, and then
classifies each historical sub-regime by comparing the directional signatures of
the already-derived evidence across those windows.

The dossier is descriptive only. It does not approve, reject, optimize, or
promote anything operational.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value
from historical_futures_market_contract import (
    HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE,
    HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST,
    HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION,
    HistoricalFuturesMarketContract,
    HistoricalFuturesMarketContractValidationError,
)
from historical_futures_market_temporal_consistency import (
    HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT,
    HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE,
    HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED,
    HistoricalFuturesMarketTemporalConsistencyCell as HistoricalFuturesMarketTemporalConsistencyWindowCell,
    HistoricalFuturesMarketTemporalConsistencyIntegrityError,
    HistoricalFuturesMarketTemporalConsistencyReport,
    HistoricalFuturesMarketTemporalConsistencyValidationError,
)
from historical_futures_market_validation import (
    HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES,
    HistoricalFuturesMarketValidationIntegrityError,
    HistoricalFuturesMarketValidationValidationError,
)
from historical_multitimeframe_analysis import (
    HistoricalMultiTimeframeStrategyAnalysisGroup,
    HistoricalMultiTimeframeStrategyAnalysisReasonCount,
    HistoricalMultiTimeframeStrategyAnalysisReport,
    HistoricalMultiTimeframeStrategyAnalysisValidationError,
)
from market_data import HistoricalDataValidationError

HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_SCHEMA_VERSION = 1
HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_PROTOCOL_NAME = (
    "historical_futures_market_robustness_dossier"
)
HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_PROTOCOL_VERSION = "v1"
HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE = "missing_evidence"
HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_CONSISTENT_OBSERVATION = "consistent_observation"
HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION = "divergent_observation"
HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUSES: tuple[str, ...] = (
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_CONSISTENT_OBSERVATION,
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION,
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE,
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE,
)


class HistoricalFuturesMarketRobustnessDossierError(Exception):
    pass


class HistoricalFuturesMarketRobustnessDossierValidationError(
    HistoricalFuturesMarketRobustnessDossierError
):
    pass


class HistoricalFuturesMarketRobustnessDossierIntegrityError(
    HistoricalFuturesMarketRobustnessDossierValidationError
):
    pass


class HistoricalFuturesMarketRobustnessDossierConflictError(
    HistoricalFuturesMarketRobustnessDossierIntegrityError
):
    pass


class HistoricalFuturesMarketRobustnessDossierPromotionError(
    HistoricalFuturesMarketRobustnessDossierValidationError
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalFuturesMarketRobustnessDossierValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalFuturesMarketRobustnessDossierValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalFuturesMarketRobustnessDossierValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalFuturesMarketRobustnessDossierValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalFuturesMarketRobustnessDossierValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if type(value) is bool:
        raise HistoricalFuturesMarketRobustnessDossierValidationError(f"{field_name} must be numeric.")
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise HistoricalFuturesMarketRobustnessDossierValidationError(f"{field_name} must be numeric.") from exc


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalFuturesMarketRobustnessDossierValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalFuturesMarketRobustnessDossierValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise HistoricalFuturesMarketRobustnessDossierValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise HistoricalFuturesMarketRobustnessDossierValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _validate_exact_keys(mapping: Mapping[str, Any], *, allowed: set[str], name: str) -> None:
    extra = set(mapping) - allowed
    if extra:
        raise HistoricalFuturesMarketRobustnessDossierValidationError(f"{name} contains unknown fields: {sorted(extra)!r}.")


def _research_only(historical_research_only: bool, operational_evidence: bool, paper_promotion_eligible: bool) -> None:
    if historical_research_only is not True:
        raise HistoricalFuturesMarketRobustnessDossierValidationError("historical_research_only must be true.")
    if operational_evidence is not False:
        raise HistoricalFuturesMarketRobustnessDossierValidationError("operational_evidence must be false.")
    if paper_promotion_eligible is not False:
        raise HistoricalFuturesMarketRobustnessDossierValidationError("paper_promotion_eligible must be false.")


def _directional_sign(value: Decimal) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _directional_signature(
    window_cell: HistoricalFuturesMarketTemporalConsistencyWindowCell,
) -> tuple[int, int, int]:
    return (
        _directional_sign(window_cell.mean_gross_return_percent_without_costs),
        _directional_sign(window_cell.median_gross_return_percent_without_costs),
        _directional_sign(window_cell.cumulative_simple_return_percent_without_costs),
    )


def _window_cells_ordered(
    cells: Sequence[HistoricalFuturesMarketTemporalConsistencyWindowCell],
) -> tuple[HistoricalFuturesMarketTemporalConsistencyWindowCell, ...]:
    expected = HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES
    if len(cells) != len(expected):
        raise HistoricalFuturesMarketRobustnessDossierValidationError("each robustness cell must cover three frozen windows.")
    ordered: list[HistoricalFuturesMarketTemporalConsistencyWindowCell] = []
    for index, expected_name in enumerate(expected):
        window_cell = cells[index]
        if window_cell.window_name != expected_name:
            raise HistoricalFuturesMarketRobustnessDossierValidationError(
                "window cells must follow the frozen reference, validation, test order."
            )
        ordered.append(window_cell)
    return tuple(ordered)


def _cell_limitation_note(status: str) -> str | None:
    if status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE:
        return "at least one frozen window is absent."
    if status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE:
        return "at least one frozen window has insufficient sample."
    if status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION:
        return "directional signatures differ across the frozen windows."
    return None


def _classify_cell(
    window_cells: Sequence[HistoricalFuturesMarketTemporalConsistencyWindowCell],
    window_signatures: Sequence[Sequence[int]],
) -> str:
    statuses = [cell.status for cell in window_cells]
    if HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT in statuses:
        return HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE
    if HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE in statuses:
        return HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE
    signature_set = {tuple(signature) for signature in window_signatures}
    if len(signature_set) == 1:
        return HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_CONSISTENT_OBSERVATION
    return HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION


def _require_directional_signature(value: Any) -> tuple[int, int, int]:
    if not isinstance(value, Sequence):
        raise HistoricalFuturesMarketRobustnessDossierValidationError("directional signature must be a sequence.")
    items = tuple(value)
    if len(items) != 3:
        raise HistoricalFuturesMarketRobustnessDossierValidationError("directional signature must contain three values.")
    signature: list[int] = []
    for item in items:
        if type(item) is bool or not isinstance(item, int):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("directional signature values must be integers.")
        if item not in (-1, 0, 1):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("directional signature values must be -1, 0, or 1.")
        signature.append(int(item))
    return tuple(signature)


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketRobustnessDossierProtocol:
    validation_report_hash: str
    contract_hash: str
    contract_temporal_split_hash: str
    analysis_report_hash: str
    analysis_protocol_hash: str
    evaluation_hash: str
    strategy_report_hash: str
    replay_hash: str
    bundle_hash: str
    source_hash: str
    reference_window_hash: str
    validation_window_hash: str
    test_window_hash: str
    source_group_hashes: tuple[str, ...]
    window_count: int = 3
    regime_count: int = 0
    schema_version: int = HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_SCHEMA_VERSION
    protocol_name: str = HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_PROTOCOL_NAME
    protocol_version: str = HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_PROTOCOL_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    protocol_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "validation_report_hash", _require_str(self.validation_report_hash, "validation_report_hash"))
        object.__setattr__(self, "contract_hash", _require_str(self.contract_hash, "contract_hash"))
        object.__setattr__(self, "contract_temporal_split_hash", _require_str(self.contract_temporal_split_hash, "contract_temporal_split_hash"))
        object.__setattr__(self, "analysis_report_hash", _require_str(self.analysis_report_hash, "analysis_report_hash"))
        object.__setattr__(self, "analysis_protocol_hash", _require_str(self.analysis_protocol_hash, "analysis_protocol_hash"))
        object.__setattr__(self, "evaluation_hash", _require_str(self.evaluation_hash, "evaluation_hash"))
        object.__setattr__(self, "strategy_report_hash", _require_str(self.strategy_report_hash, "strategy_report_hash"))
        object.__setattr__(self, "replay_hash", _require_str(self.replay_hash, "replay_hash"))
        object.__setattr__(self, "bundle_hash", _require_str(self.bundle_hash, "bundle_hash"))
        object.__setattr__(self, "source_hash", _require_str(self.source_hash, "source_hash"))
        object.__setattr__(self, "reference_window_hash", _require_str(self.reference_window_hash, "reference_window_hash"))
        object.__setattr__(self, "validation_window_hash", _require_str(self.validation_window_hash, "validation_window_hash"))
        object.__setattr__(self, "test_window_hash", _require_str(self.test_window_hash, "test_window_hash"))
        if not isinstance(self.source_group_hashes, tuple):
            object.__setattr__(self, "source_group_hashes", tuple(self.source_group_hashes))
        object.__setattr__(self, "source_group_hashes", tuple(_require_str(item, "source_group_hash") for item in self.source_group_hashes))
        object.__setattr__(self, "window_count", _require_int(self.window_count, "window_count"))
        object.__setattr__(self, "regime_count", _require_int(self.regime_count, "regime_count"))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "protocol_name", _require_str(self.protocol_name, "protocol_name"))
        object.__setattr__(self, "protocol_version", _require_str(self.protocol_version, "protocol_version"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_SCHEMA_VERSION:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness dossier schema_version must be 1.")
        if self.protocol_name != HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_PROTOCOL_NAME:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("protocol_name diverges from the trusted dossier.")
        if self.protocol_version != HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_PROTOCOL_VERSION:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("protocol_version diverges from the trusted dossier.")
        if self.window_count != len(HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness dossier must cover three windows.")
        if len({self.reference_window_hash, self.validation_window_hash, self.test_window_hash}) != 3:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("window hashes must remain distinct.")
        if self.regime_count != len(self.source_group_hashes):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("regime_count must equal the number of source groups.")
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.protocol_hash:
            if self.protocol_hash != expected:
                raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness dossier protocol hash mismatch.")
        else:
            object.__setattr__(self, "protocol_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "protocol_name": self.protocol_name,
            "protocol_version": self.protocol_version,
            "validation_report_hash": self.validation_report_hash,
            "analysis_protocol_hash": self.analysis_protocol_hash,
            "evaluation_hash": self.evaluation_hash,
            "strategy_report_hash": self.strategy_report_hash,
            "replay_hash": self.replay_hash,
            "bundle_hash": self.bundle_hash,
            "source_hash": self.source_hash,
            "reference_window_hash": self.reference_window_hash,
            "validation_window_hash": self.validation_window_hash,
            "test_window_hash": self.test_window_hash,
            "source_group_hashes": list(self.source_group_hashes),
            "window_count": self.window_count,
            "regime_count": self.regime_count,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }
        if include_hash:
            payload["contract_hash"] = self.contract_hash
            payload["contract_temporal_split_hash"] = self.contract_temporal_split_hash
            payload["analysis_report_hash"] = self.analysis_report_hash
            payload["protocol_hash"] = self.protocol_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketRobustnessDossierProtocol":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness dossier protocol must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "protocol_name",
                "protocol_version",
                "validation_report_hash",
                "contract_hash",
                "contract_temporal_split_hash",
                "analysis_report_hash",
                "analysis_protocol_hash",
                "evaluation_hash",
                "strategy_report_hash",
                "replay_hash",
                "bundle_hash",
                "source_hash",
                "reference_window_hash",
                "validation_window_hash",
                "test_window_hash",
                "source_group_hashes",
                "window_count",
                "regime_count",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "protocol_hash",
            },
            name="robustness dossier protocol",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                protocol_name=mapping["protocol_name"],
                protocol_version=mapping["protocol_version"],
                validation_report_hash=mapping["validation_report_hash"],
                contract_hash=mapping["contract_hash"],
                contract_temporal_split_hash=mapping["contract_temporal_split_hash"],
                analysis_report_hash=mapping["analysis_report_hash"],
                analysis_protocol_hash=mapping["analysis_protocol_hash"],
                evaluation_hash=mapping["evaluation_hash"],
                strategy_report_hash=mapping["strategy_report_hash"],
                replay_hash=mapping["replay_hash"],
                bundle_hash=mapping["bundle_hash"],
                source_hash=mapping["source_hash"],
                reference_window_hash=mapping["reference_window_hash"],
                validation_window_hash=mapping["validation_window_hash"],
                test_window_hash=mapping["test_window_hash"],
                source_group_hashes=tuple(mapping["source_group_hashes"]),
                window_count=mapping["window_count"],
                regime_count=mapping["regime_count"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                protocol_hash=mapping.get("protocol_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness dossier protocol is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketRobustnessCell:
    source_group: HistoricalMultiTimeframeStrategyAnalysisGroup
    window_cells: tuple[
        HistoricalFuturesMarketTemporalConsistencyWindowCell,
        HistoricalFuturesMarketTemporalConsistencyWindowCell,
        HistoricalFuturesMarketTemporalConsistencyWindowCell,
    ]
    window_directional_signatures: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]
    observed_window_count: int
    insufficient_sample_window_count: int
    absent_window_count: int
    status: str
    limitation_note: str | None = None
    schema_version: int = HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_SCHEMA_VERSION
    cell_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.source_group, HistoricalMultiTimeframeStrategyAnalysisGroup):
            raise HistoricalFuturesMarketRobustnessDossierValidationError(
                "source_group must be a HistoricalMultiTimeframeStrategyAnalysisGroup instance."
            )
        if not isinstance(self.window_cells, tuple):
            object.__setattr__(self, "window_cells", tuple(self.window_cells))
        if len(self.window_cells) != len(HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness cell must carry three window cells.")
        if any(not isinstance(item, HistoricalFuturesMarketTemporalConsistencyWindowCell) for item in self.window_cells):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("window_cells must contain temporal consistency cells.")
        if not isinstance(self.window_directional_signatures, tuple):
            object.__setattr__(self, "window_directional_signatures", tuple(self.window_directional_signatures))
        signatures = tuple(_require_directional_signature(signature) for signature in self.window_directional_signatures)
        if len(signatures) != len(HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness cell must carry three directional signatures.")
        object.__setattr__(self, "window_directional_signatures", signatures)
        for index, expected_name in enumerate(HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES):
            if self.window_cells[index].window_name != expected_name:
                raise HistoricalFuturesMarketRobustnessDossierValidationError(
                    "window cells must follow the frozen reference, validation, test order."
                )
        shared_group_hashes = {cell.source_group.group_hash for cell in self.window_cells}
        if len(shared_group_hashes) != 1:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("window cells must share the same source group.")
        if self.source_group.group_hash not in shared_group_hashes:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("source_group diverges from the frozen window cells.")
        object.__setattr__(self, "observed_window_count", _require_int(self.observed_window_count, "observed_window_count", allow_zero=True))
        object.__setattr__(self, "insufficient_sample_window_count", _require_int(self.insufficient_sample_window_count, "insufficient_sample_window_count", allow_zero=True))
        object.__setattr__(self, "absent_window_count", _require_int(self.absent_window_count, "absent_window_count", allow_zero=True))
        object.__setattr__(self, "status", _require_str(self.status, "status").lower())
        if self.limitation_note is not None:
            object.__setattr__(self, "limitation_note", _require_str(self.limitation_note, "limitation_note"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_SCHEMA_VERSION:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness cell schema_version must be 1.")
        derived_observed = sum(1 for cell in self.window_cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED)
        derived_insufficient = sum(1 for cell in self.window_cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE)
        derived_absent = sum(1 for cell in self.window_cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT)
        if self.observed_window_count != derived_observed:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("observed_window_count does not reconcile.")
        if self.insufficient_sample_window_count != derived_insufficient:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("insufficient_sample_window_count does not reconcile.")
        if self.absent_window_count != derived_absent:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("absent_window_count does not reconcile.")
        derived_status = _classify_cell(self.window_cells, self.window_directional_signatures)
        if self.status != derived_status:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness cell status diverges from the frozen evidence.")
        expected_note = _cell_limitation_note(derived_status)
        if self.limitation_note != expected_note:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness cell limitation note diverges from the frozen evidence.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.cell_hash:
            if self.cell_hash != expected:
                raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness cell hash mismatch.")
        else:
            object.__setattr__(self, "cell_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "source_group": self.source_group.as_dict(),
            "window_cells": [cell.as_dict() for cell in self.window_cells],
            "window_directional_signatures": [list(signature) for signature in self.window_directional_signatures],
            "observed_window_count": self.observed_window_count,
            "insufficient_sample_window_count": self.insufficient_sample_window_count,
            "absent_window_count": self.absent_window_count,
            "status": self.status,
            "limitation_note": self.limitation_note,
        }
        if include_hash:
            payload["cell_hash"] = self.cell_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketRobustnessCell":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness cell must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "source_group",
                "window_cells",
                "window_directional_signatures",
                "observed_window_count",
                "insufficient_sample_window_count",
                "absent_window_count",
                "status",
                "limitation_note",
                "cell_hash",
            },
            name="robustness cell",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                source_group=HistoricalMultiTimeframeStrategyAnalysisGroup.from_dict(mapping["source_group"]),
                window_cells=tuple(
                    HistoricalFuturesMarketTemporalConsistencyWindowCell.from_dict(item) for item in mapping["window_cells"]
                ),
                window_directional_signatures=tuple(
                    _require_directional_signature(signature) for signature in mapping["window_directional_signatures"]
                ),
                observed_window_count=mapping["observed_window_count"],
                insufficient_sample_window_count=mapping["insufficient_sample_window_count"],
                absent_window_count=mapping["absent_window_count"],
                status=mapping["status"],
                limitation_note=mapping.get("limitation_note"),
                cell_hash=mapping.get("cell_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness cell is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketRobustnessWindowSummary:
    window_name: str
    window_start_utc: datetime
    window_end_utc: datetime
    window_hash: str
    window_cell_count: int
    observed_window_cell_count: int
    insufficient_sample_window_cell_count: int
    absent_window_cell_count: int
    decision_count: int
    signal_count: int
    evaluated_operations: int
    no_signal_decisions: int
    not_evaluable_entries: int
    schema_version: int = HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_SCHEMA_VERSION
    summary_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_name", _require_str(self.window_name, "window_name").lower())
        object.__setattr__(self, "window_start_utc", _require_utc_datetime(self.window_start_utc, "window_start_utc"))
        object.__setattr__(self, "window_end_utc", _require_utc_datetime(self.window_end_utc, "window_end_utc"))
        object.__setattr__(self, "window_hash", _require_str(self.window_hash, "window_hash"))
        object.__setattr__(self, "window_cell_count", _require_int(self.window_cell_count, "window_cell_count", allow_zero=True))
        object.__setattr__(self, "observed_window_cell_count", _require_int(self.observed_window_cell_count, "observed_window_cell_count", allow_zero=True))
        object.__setattr__(self, "insufficient_sample_window_cell_count", _require_int(self.insufficient_sample_window_cell_count, "insufficient_sample_window_cell_count", allow_zero=True))
        object.__setattr__(self, "absent_window_cell_count", _require_int(self.absent_window_cell_count, "absent_window_cell_count", allow_zero=True))
        object.__setattr__(self, "decision_count", _require_int(self.decision_count, "decision_count", allow_zero=True))
        object.__setattr__(self, "signal_count", _require_int(self.signal_count, "signal_count", allow_zero=True))
        object.__setattr__(self, "evaluated_operations", _require_int(self.evaluated_operations, "evaluated_operations", allow_zero=True))
        object.__setattr__(self, "no_signal_decisions", _require_int(self.no_signal_decisions, "no_signal_decisions", allow_zero=True))
        object.__setattr__(self, "not_evaluable_entries", _require_int(self.not_evaluable_entries, "not_evaluable_entries", allow_zero=True))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_SCHEMA_VERSION:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("window summary schema_version must be 1.")
        if self.window_name not in HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("window_name must be reference, validation, or test.")
        if self.window_end_utc < self.window_start_utc:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("window end must be after or equal to window start.")
        if self.window_cell_count != self.observed_window_cell_count + self.insufficient_sample_window_cell_count + self.absent_window_cell_count:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("window summary cell counts do not reconcile.")
        if self.decision_count != self.signal_count + self.no_signal_decisions:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("window summary decision_count does not reconcile.")
        if self.signal_count != self.evaluated_operations + self.not_evaluable_entries:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("window summary signal_count does not reconcile.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.summary_hash:
            if self.summary_hash != expected:
                raise HistoricalFuturesMarketRobustnessDossierValidationError("window summary hash mismatch.")
        else:
            object.__setattr__(self, "summary_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "window_name": self.window_name,
            "window_start_utc": _utc_iso(self.window_start_utc),
            "window_end_utc": _utc_iso(self.window_end_utc),
            "window_hash": self.window_hash,
            "window_cell_count": self.window_cell_count,
            "observed_window_cell_count": self.observed_window_cell_count,
            "insufficient_sample_window_cell_count": self.insufficient_sample_window_cell_count,
            "absent_window_cell_count": self.absent_window_cell_count,
            "decision_count": self.decision_count,
            "signal_count": self.signal_count,
            "evaluated_operations": self.evaluated_operations,
            "no_signal_decisions": self.no_signal_decisions,
            "not_evaluable_entries": self.not_evaluable_entries,
        }
        if include_hash:
            payload["summary_hash"] = self.summary_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketRobustnessWindowSummary":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("window summary must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "window_name",
                "window_start_utc",
                "window_end_utc",
                "window_hash",
                "window_cell_count",
                "observed_window_cell_count",
                "insufficient_sample_window_cell_count",
                "absent_window_cell_count",
                "decision_count",
                "signal_count",
                "evaluated_operations",
                "no_signal_decisions",
                "not_evaluable_entries",
                "summary_hash",
            },
            name="window summary",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                window_name=mapping["window_name"],
                window_start_utc=mapping["window_start_utc"],
                window_end_utc=mapping["window_end_utc"],
                window_hash=mapping["window_hash"],
                window_cell_count=mapping["window_cell_count"],
                observed_window_cell_count=mapping["observed_window_cell_count"],
                insufficient_sample_window_cell_count=mapping["insufficient_sample_window_cell_count"],
                absent_window_cell_count=mapping["absent_window_cell_count"],
                decision_count=mapping["decision_count"],
                signal_count=mapping["signal_count"],
                evaluated_operations=mapping["evaluated_operations"],
                no_signal_decisions=mapping["no_signal_decisions"],
                not_evaluable_entries=mapping["not_evaluable_entries"],
                summary_hash=mapping.get("summary_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("window summary is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketRobustnessSummary:
    window_count: int
    regime_count: int
    matrix_cell_count: int
    observed_matrix_cell_count: int
    insufficient_sample_matrix_cell_count: int
    absent_matrix_cell_count: int
    consistent_observation_regime_count: int
    divergent_observation_regime_count: int
    insufficient_evidence_regime_count: int
    missing_evidence_regime_count: int
    comparable_regime_count: int
    decision_count: int
    signal_count: int
    evaluated_operations: int
    no_signal_decisions: int
    not_evaluable_entries: int
    schema_version: int = HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_SCHEMA_VERSION
    summary_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_count", _require_int(self.window_count, "window_count"))
        object.__setattr__(self, "regime_count", _require_int(self.regime_count, "regime_count"))
        object.__setattr__(self, "matrix_cell_count", _require_int(self.matrix_cell_count, "matrix_cell_count", allow_zero=True))
        object.__setattr__(self, "observed_matrix_cell_count", _require_int(self.observed_matrix_cell_count, "observed_matrix_cell_count", allow_zero=True))
        object.__setattr__(self, "insufficient_sample_matrix_cell_count", _require_int(self.insufficient_sample_matrix_cell_count, "insufficient_sample_matrix_cell_count", allow_zero=True))
        object.__setattr__(self, "absent_matrix_cell_count", _require_int(self.absent_matrix_cell_count, "absent_matrix_cell_count", allow_zero=True))
        object.__setattr__(self, "consistent_observation_regime_count", _require_int(self.consistent_observation_regime_count, "consistent_observation_regime_count", allow_zero=True))
        object.__setattr__(self, "divergent_observation_regime_count", _require_int(self.divergent_observation_regime_count, "divergent_observation_regime_count", allow_zero=True))
        object.__setattr__(self, "insufficient_evidence_regime_count", _require_int(self.insufficient_evidence_regime_count, "insufficient_evidence_regime_count", allow_zero=True))
        object.__setattr__(self, "missing_evidence_regime_count", _require_int(self.missing_evidence_regime_count, "missing_evidence_regime_count", allow_zero=True))
        object.__setattr__(self, "comparable_regime_count", _require_int(self.comparable_regime_count, "comparable_regime_count", allow_zero=True))
        object.__setattr__(self, "decision_count", _require_int(self.decision_count, "decision_count", allow_zero=True))
        object.__setattr__(self, "signal_count", _require_int(self.signal_count, "signal_count", allow_zero=True))
        object.__setattr__(self, "evaluated_operations", _require_int(self.evaluated_operations, "evaluated_operations", allow_zero=True))
        object.__setattr__(self, "no_signal_decisions", _require_int(self.no_signal_decisions, "no_signal_decisions", allow_zero=True))
        object.__setattr__(self, "not_evaluable_entries", _require_int(self.not_evaluable_entries, "not_evaluable_entries", allow_zero=True))
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_SCHEMA_VERSION:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness summary schema_version must be 1.")
        if self.window_count != len(HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness summary must cover three windows.")
        if self.matrix_cell_count != self.window_count * self.regime_count:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("matrix_cell_count does not reconcile.")
        if self.decision_count != self.signal_count + self.no_signal_decisions:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("summary decision_count does not reconcile.")
        if self.signal_count != self.evaluated_operations + self.not_evaluable_entries:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("summary signal_count does not reconcile.")
        if self.regime_count != (
            self.consistent_observation_regime_count
            + self.divergent_observation_regime_count
            + self.insufficient_evidence_regime_count
            + self.missing_evidence_regime_count
        ):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("summary regime counts do not reconcile.")
        if self.matrix_cell_count != (
            self.observed_matrix_cell_count
            + self.insufficient_sample_matrix_cell_count
            + self.absent_matrix_cell_count
        ):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("summary matrix cell counts do not reconcile.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.summary_hash:
            if self.summary_hash != expected:
                raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness summary hash mismatch.")
        else:
            object.__setattr__(self, "summary_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "window_count": self.window_count,
            "regime_count": self.regime_count,
            "matrix_cell_count": self.matrix_cell_count,
            "observed_matrix_cell_count": self.observed_matrix_cell_count,
            "insufficient_sample_matrix_cell_count": self.insufficient_sample_matrix_cell_count,
            "absent_matrix_cell_count": self.absent_matrix_cell_count,
            "consistent_observation_regime_count": self.consistent_observation_regime_count,
            "divergent_observation_regime_count": self.divergent_observation_regime_count,
            "insufficient_evidence_regime_count": self.insufficient_evidence_regime_count,
            "missing_evidence_regime_count": self.missing_evidence_regime_count,
            "comparable_regime_count": self.comparable_regime_count,
            "decision_count": self.decision_count,
            "signal_count": self.signal_count,
            "evaluated_operations": self.evaluated_operations,
            "no_signal_decisions": self.no_signal_decisions,
            "not_evaluable_entries": self.not_evaluable_entries,
        }
        if include_hash:
            payload["summary_hash"] = self.summary_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketRobustnessSummary":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness summary must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "window_count",
                "regime_count",
                "matrix_cell_count",
                "observed_matrix_cell_count",
                "insufficient_sample_matrix_cell_count",
                "absent_matrix_cell_count",
                "consistent_observation_regime_count",
                "divergent_observation_regime_count",
                "insufficient_evidence_regime_count",
                "missing_evidence_regime_count",
                "comparable_regime_count",
                "decision_count",
                "signal_count",
                "evaluated_operations",
                "no_signal_decisions",
                "not_evaluable_entries",
                "summary_hash",
            },
            name="robustness summary",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                window_count=mapping["window_count"],
                regime_count=mapping["regime_count"],
                matrix_cell_count=mapping["matrix_cell_count"],
                observed_matrix_cell_count=mapping["observed_matrix_cell_count"],
                insufficient_sample_matrix_cell_count=mapping["insufficient_sample_matrix_cell_count"],
                absent_matrix_cell_count=mapping["absent_matrix_cell_count"],
                consistent_observation_regime_count=mapping["consistent_observation_regime_count"],
                divergent_observation_regime_count=mapping["divergent_observation_regime_count"],
                insufficient_evidence_regime_count=mapping["insufficient_evidence_regime_count"],
                missing_evidence_regime_count=mapping["missing_evidence_regime_count"],
                comparable_regime_count=mapping["comparable_regime_count"],
                decision_count=mapping["decision_count"],
                signal_count=mapping["signal_count"],
                evaluated_operations=mapping["evaluated_operations"],
                no_signal_decisions=mapping["no_signal_decisions"],
                not_evaluable_entries=mapping["not_evaluable_entries"],
                summary_hash=mapping.get("summary_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness summary is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketRobustnessDossierReport:
    temporal_consistency_report: HistoricalFuturesMarketTemporalConsistencyReport
    protocol: HistoricalFuturesMarketRobustnessDossierProtocol
    cells: tuple[HistoricalFuturesMarketRobustnessCell, ...]
    window_summaries: tuple[HistoricalFuturesMarketRobustnessWindowSummary, ...]
    summary: HistoricalFuturesMarketRobustnessSummary
    schema_version: int = HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    report_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.temporal_consistency_report, HistoricalFuturesMarketTemporalConsistencyReport):
            raise HistoricalFuturesMarketRobustnessDossierValidationError(
                "temporal_consistency_report must be a historical temporal consistency report instance."
            )
        if not isinstance(self.protocol, HistoricalFuturesMarketRobustnessDossierProtocol):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("protocol must be a robustness dossier protocol instance.")
        if not isinstance(self.cells, tuple):
            object.__setattr__(self, "cells", tuple(self.cells))
        if not isinstance(self.window_summaries, tuple):
            object.__setattr__(self, "window_summaries", tuple(self.window_summaries))
        if not isinstance(self.summary, HistoricalFuturesMarketRobustnessSummary):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("summary must be a robustness summary instance.")
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_SCHEMA_VERSION:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness dossier report schema_version must be 1.")
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        if (
            self.temporal_consistency_report.historical_research_only is not True
            or self.temporal_consistency_report.operational_evidence is not False
            or self.temporal_consistency_report.paper_promotion_eligible is not False
        ):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("temporal consistency report must remain research-only.")
        if self.protocol.validation_report_hash != self.temporal_consistency_report.report_hash:
            raise HistoricalFuturesMarketRobustnessDossierValidationError(
                "robustness protocol diverges from the frozen temporal consistency report."
            )
        expected_cells = _build_cells(self.temporal_consistency_report)
        if self.cells != expected_cells:
            raise HistoricalFuturesMarketRobustnessDossierIntegrityError("robustness cells diverge from the frozen evidence.")
        expected_window_summaries = _build_window_summaries(self.temporal_consistency_report, self.cells)
        if self.window_summaries != expected_window_summaries:
            raise HistoricalFuturesMarketRobustnessDossierIntegrityError(
                "robustness window summaries diverge from the frozen evidence."
            )
        expected_summary = _build_summary(self.temporal_consistency_report, self.cells, self.window_summaries)
        if self.summary != expected_summary:
            raise HistoricalFuturesMarketRobustnessDossierIntegrityError("robustness summary diverges from the frozen evidence.")
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.report_hash:
            if self.report_hash != expected:
                raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness dossier report hash mismatch.")
        else:
            object.__setattr__(self, "report_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "validation_report_hash": self.temporal_consistency_report.report_hash,
            "protocol": self.protocol.as_hash_payload(include_hash=False),
            "cells": [cell.as_dict() for cell in self.cells],
            "window_summaries": [item.as_dict() for item in self.window_summaries],
            "summary": self.summary.as_dict(),
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }
        if include_hash:
            payload["report_hash"] = self.report_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "temporal_consistency_report": self.temporal_consistency_report.as_dict(),
            "protocol": self.protocol.as_dict(),
            "cells": [cell.as_dict() for cell in self.cells],
            "window_summaries": [item.as_dict() for item in self.window_summaries],
            "summary": self.summary.as_dict(),
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "report_hash": self.report_hash,
        }
        return serialize_value(payload)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketRobustnessDossierReport":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness dossier report must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "temporal_consistency_report",
                "protocol",
                "cells",
                "window_summaries",
                "summary",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "report_hash",
            },
            name="robustness dossier report",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                temporal_consistency_report=HistoricalFuturesMarketTemporalConsistencyReport.from_dict(
                    mapping["temporal_consistency_report"]
                ),
                protocol=HistoricalFuturesMarketRobustnessDossierProtocol.from_dict(mapping["protocol"]),
                cells=tuple(HistoricalFuturesMarketRobustnessCell.from_dict(item) for item in mapping["cells"]),
                window_summaries=tuple(
                    HistoricalFuturesMarketRobustnessWindowSummary.from_dict(item)
                    for item in mapping["window_summaries"]
                ),
                summary=HistoricalFuturesMarketRobustnessSummary.from_dict(mapping["summary"]),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                report_hash=mapping.get("report_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness dossier report is incomplete.") from exc
        except (
            HistoricalFuturesMarketRobustnessDossierValidationError,
            HistoricalFuturesMarketRobustnessDossierIntegrityError,
            HistoricalFuturesMarketTemporalConsistencyValidationError,
            HistoricalFuturesMarketContractValidationError,
            HistoricalMultiTimeframeStrategyAnalysisValidationError,
            HistoricalDataValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise HistoricalFuturesMarketRobustnessDossierIntegrityError(str(exc)) from exc


def _build_protocol(
    temporal_consistency_report: HistoricalFuturesMarketTemporalConsistencyReport,
) -> HistoricalFuturesMarketRobustnessDossierProtocol:
    validation_report = temporal_consistency_report.validation_report
    contract = validation_report.contract
    temporal_split = contract.temporal_split_protocol
    analysis_report = validation_report.analysis_report
    source = analysis_report.protocol.source
    source_group_hashes = tuple(group.group_hash for group in analysis_report.groups)
    return HistoricalFuturesMarketRobustnessDossierProtocol(
        validation_report_hash=temporal_consistency_report.report_hash,
        contract_hash=contract.contract_hash,
        contract_temporal_split_hash=temporal_split.protocol_hash,
        analysis_report_hash=analysis_report.report_hash,
        analysis_protocol_hash=analysis_report.protocol.protocol_hash,
        evaluation_hash=source.evaluation_hash,
        strategy_report_hash=source.strategy_report_hash,
        replay_hash=source.replay_hash,
        bundle_hash=source.bundle_hash,
        source_hash=source.source_hash,
        reference_window_hash=temporal_split.reference_window.window_hash,
        validation_window_hash=temporal_split.validation_window.window_hash,
        test_window_hash=temporal_split.test_window.window_hash,
        source_group_hashes=source_group_hashes,
        window_count=len(HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES),
        regime_count=len(source_group_hashes),
    )


def _build_cells(
    temporal_consistency_report: HistoricalFuturesMarketTemporalConsistencyReport,
) -> tuple[HistoricalFuturesMarketRobustnessCell, ...]:
    analysis_report = temporal_consistency_report.validation_report.analysis_report
    windows = HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES
    cells_by_group: dict[str, dict[str, HistoricalFuturesMarketTemporalConsistencyWindowCell]] = {}
    for cell in temporal_consistency_report.cells:
        group_hash = cell.source_group.group_hash
        if cell.window_name not in windows:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("temporal consistency report contains an unknown window.")
        cells_by_group.setdefault(group_hash, {})
        if cell.window_name in cells_by_group[group_hash]:
            raise HistoricalFuturesMarketRobustnessDossierValidationError("temporal consistency report contains duplicate window evidence.")
        cells_by_group[group_hash][cell.window_name] = cell

    result: list[HistoricalFuturesMarketRobustnessCell] = []
    for source_group in analysis_report.groups:
        group_map = cells_by_group.get(source_group.group_hash)
        if group_map is None or set(group_map) != set(windows):
            raise HistoricalFuturesMarketRobustnessDossierValidationError(
                "temporal consistency report must provide evidence for each frozen window and source group."
            )
        ordered_window_cells = tuple(group_map[name] for name in windows)
        window_signatures = tuple(_directional_signature(cell) for cell in ordered_window_cells)
        observed_window_count = sum(1 for cell in ordered_window_cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED)
        insufficient_sample_window_count = sum(
            1 for cell in ordered_window_cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE
        )
        absent_window_count = sum(
            1 for cell in ordered_window_cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT
        )
        status = _classify_cell(ordered_window_cells, window_signatures)
        result.append(
            HistoricalFuturesMarketRobustnessCell(
                source_group=source_group,
                window_cells=ordered_window_cells,
                window_directional_signatures=window_signatures,
                observed_window_count=observed_window_count,
                insufficient_sample_window_count=insufficient_sample_window_count,
                absent_window_count=absent_window_count,
                status=status,
                limitation_note=_cell_limitation_note(status),
            )
        )
    return tuple(result)


def _build_window_summaries(
    temporal_consistency_report: HistoricalFuturesMarketTemporalConsistencyReport,
    cells: Sequence[HistoricalFuturesMarketRobustnessCell],
) -> tuple[HistoricalFuturesMarketRobustnessWindowSummary, ...]:
    windows = {
        item.window_name: item for item in temporal_consistency_report.window_summaries
    }
    summaries: list[HistoricalFuturesMarketRobustnessWindowSummary] = []
    for index, window_name in enumerate(HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES):
        window = windows[window_name]
        window_cells = [cell.window_cells[index] for cell in cells]
        summaries.append(
            HistoricalFuturesMarketRobustnessWindowSummary(
                window_name=window.window_name,
                window_start_utc=window.window_start_utc,
                window_end_utc=window.window_end_utc,
                window_hash=window.window_hash,
                window_cell_count=len(window_cells),
                observed_window_cell_count=sum(
                    1 for cell in window_cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED
                ),
                insufficient_sample_window_cell_count=sum(
                    1 for cell in window_cells
                    if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE
                ),
                absent_window_cell_count=sum(
                    1 for cell in window_cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT
                ),
                decision_count=sum(cell.decision_count for cell in window_cells),
                signal_count=sum(cell.signal_count for cell in window_cells),
                evaluated_operations=sum(cell.evaluated_operations for cell in window_cells),
                no_signal_decisions=sum(cell.no_signal_decisions for cell in window_cells),
                not_evaluable_entries=sum(cell.not_evaluable_entries for cell in window_cells),
            )
        )
    return tuple(summaries)


def _build_summary(
    temporal_consistency_report: HistoricalFuturesMarketTemporalConsistencyReport,
    cells: Sequence[HistoricalFuturesMarketRobustnessCell],
    window_summaries: Sequence[HistoricalFuturesMarketRobustnessWindowSummary],
) -> HistoricalFuturesMarketRobustnessSummary:
    matrix_cells = [window_cell for cell in cells for window_cell in cell.window_cells]
    consistent_count = sum(1 for cell in cells if cell.status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_CONSISTENT_OBSERVATION)
    divergent_count = sum(1 for cell in cells if cell.status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION)
    insufficient_count = sum(1 for cell in cells if cell.status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE)
    missing_count = sum(1 for cell in cells if cell.status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE)
    decision_count = sum(cell.decision_count for cell in matrix_cells)
    signal_count = sum(cell.signal_count for cell in matrix_cells)
    evaluated_operations = sum(cell.evaluated_operations for cell in matrix_cells)
    no_signal_decisions = sum(cell.no_signal_decisions for cell in matrix_cells)
    not_evaluable_entries = sum(cell.not_evaluable_entries for cell in matrix_cells)
    return HistoricalFuturesMarketRobustnessSummary(
        window_count=len(window_summaries),
        regime_count=len(cells),
        matrix_cell_count=len(matrix_cells),
        observed_matrix_cell_count=sum(
            1 for cell in matrix_cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_OBSERVED
        ),
        insufficient_sample_matrix_cell_count=sum(
            1 for cell in matrix_cells
            if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_INSUFFICIENT_SAMPLE
        ),
        absent_matrix_cell_count=sum(
            1 for cell in matrix_cells if cell.status == HISTORICAL_FUTURES_MARKET_TEMPORAL_CONSISTENCY_CELL_STATUS_ABSENT
        ),
        consistent_observation_regime_count=consistent_count,
        divergent_observation_regime_count=divergent_count,
        insufficient_evidence_regime_count=insufficient_count,
        missing_evidence_regime_count=missing_count,
        comparable_regime_count=consistent_count + divergent_count,
        decision_count=decision_count,
        signal_count=signal_count,
        evaluated_operations=evaluated_operations,
        no_signal_decisions=no_signal_decisions,
        not_evaluable_entries=not_evaluable_entries,
    )


def build_historical_futures_market_robustness_dossier_protocol(
    temporal_consistency_report: HistoricalFuturesMarketTemporalConsistencyReport,
) -> HistoricalFuturesMarketRobustnessDossierProtocol:
    if not isinstance(temporal_consistency_report, HistoricalFuturesMarketTemporalConsistencyReport):
        raise HistoricalFuturesMarketRobustnessDossierValidationError(
            "temporal_consistency_report must be a HistoricalFuturesMarketTemporalConsistencyReport instance."
        )
    return _build_protocol(temporal_consistency_report)


def build_historical_futures_market_robustness_dossier_report(
    temporal_consistency_report: HistoricalFuturesMarketTemporalConsistencyReport,
) -> HistoricalFuturesMarketRobustnessDossierReport:
    if not isinstance(temporal_consistency_report, HistoricalFuturesMarketTemporalConsistencyReport):
        raise HistoricalFuturesMarketRobustnessDossierValidationError(
            "temporal_consistency_report must be a HistoricalFuturesMarketTemporalConsistencyReport instance."
        )
    protocol = _build_protocol(temporal_consistency_report)
    cells = _build_cells(temporal_consistency_report)
    window_summaries = _build_window_summaries(temporal_consistency_report, cells)
    summary = _build_summary(temporal_consistency_report, cells, window_summaries)
    return HistoricalFuturesMarketRobustnessDossierReport(
        temporal_consistency_report=temporal_consistency_report,
        protocol=protocol,
        cells=cells,
        window_summaries=window_summaries,
        summary=summary,
    )


def run_historical_futures_market_robustness_dossier(
    temporal_consistency_report: HistoricalFuturesMarketTemporalConsistencyReport,
    *,
    output_file: str | Path | None = None,
) -> HistoricalFuturesMarketRobustnessDossierReport:
    report = build_historical_futures_market_robustness_dossier_report(temporal_consistency_report)
    if output_file is not None:
        save_historical_futures_market_robustness_dossier_report(output_file, report)
    return report


def _read(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HistoricalFuturesMarketRobustnessDossierValidationError("robustness dossier report not found.") from exc
    except Exception as exc:
        raise HistoricalFuturesMarketRobustnessDossierIntegrityError("robustness dossier report is invalid JSON.") from exc
    if not isinstance(value, Mapping):
        raise HistoricalFuturesMarketRobustnessDossierIntegrityError("robustness dossier report must be a JSON object.")
    return value


def load_historical_futures_market_robustness_dossier_report(
    path: str | Path,
) -> HistoricalFuturesMarketRobustnessDossierReport:
    payload = _read(Path(path))
    try:
        report = HistoricalFuturesMarketRobustnessDossierReport.from_dict(payload)
    except (
        KeyError,
        TypeError,
        ValueError,
        HistoricalFuturesMarketRobustnessDossierValidationError,
        HistoricalFuturesMarketRobustnessDossierIntegrityError,
        HistoricalFuturesMarketTemporalConsistencyValidationError,
        HistoricalFuturesMarketTemporalConsistencyIntegrityError,
        HistoricalFuturesMarketValidationValidationError,
        HistoricalFuturesMarketValidationIntegrityError,
        HistoricalFuturesMarketContractValidationError,
        HistoricalMultiTimeframeStrategyAnalysisValidationError,
        HistoricalDataValidationError,
    ) as exc:
        raise HistoricalFuturesMarketRobustnessDossierIntegrityError(str(exc)) from exc
    if report.as_dict() != payload:
        raise HistoricalFuturesMarketRobustnessDossierIntegrityError("robustness dossier report payload mismatch.")
    return report


def save_historical_futures_market_robustness_dossier_report(
    path: str | Path,
    report: HistoricalFuturesMarketRobustnessDossierReport,
) -> HistoricalFuturesMarketRobustnessDossierReport:
    file_path = Path(path)
    payload = report.as_dict()
    if file_path.exists():
        existing = load_historical_futures_market_robustness_dossier_report(file_path)
        if existing.as_dict() != payload:
            raise HistoricalFuturesMarketRobustnessDossierConflictError(
                "robustness dossier report already exists and differs."
            )
        return existing
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_name(f".{file_path.name}.{os.getpid()}.{id(report)}.tmp")
    try:
        tmp.write_text(_canonical_json(payload), encoding="utf-8")
        try:
            os.link(tmp, file_path)
        except FileExistsError:
            existing = load_historical_futures_market_robustness_dossier_report(file_path)
            if existing.as_dict() != payload:
                raise HistoricalFuturesMarketRobustnessDossierConflictError(
                    "robustness dossier report already exists and differs."
                )
            return existing
    except Exception as exc:
        if isinstance(exc, HistoricalFuturesMarketRobustnessDossierConflictError):
            raise
        raise HistoricalFuturesMarketRobustnessDossierValidationError(
            "failed to write robustness dossier report atomically."
        ) from exc
    finally:
        tmp.unlink(missing_ok=True)
    return report


def verify_historical_futures_market_robustness_dossier_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_robustness_dossier_report(path)
    return {
        "verified": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "validation_report_hash": report.temporal_consistency_report.report_hash,
        "contract_hash": report.temporal_consistency_report.validation_report.contract.contract_hash,
        "analysis_report_hash": report.temporal_consistency_report.validation_report.analysis_report.report_hash,
        "classification": "historical_research_only",
    }


def status_historical_futures_market_robustness_dossier_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_robustness_dossier_report(path)
    summary = report.summary
    window_map = {item.window_name: item for item in report.window_summaries}
    return {
        "exists": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "validation_report_hash": report.temporal_consistency_report.report_hash,
        "contract_hash": report.temporal_consistency_report.validation_report.contract.contract_hash,
        "analysis_report_hash": report.temporal_consistency_report.validation_report.analysis_report.report_hash,
        "reference_window_hash": report.protocol.reference_window_hash,
        "validation_window_hash": report.protocol.validation_window_hash,
        "test_window_hash": report.protocol.test_window_hash,
        "reference_window_cell_count": window_map[HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_REFERENCE].window_cell_count,
        "validation_window_cell_count": window_map[HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_VALIDATION].window_cell_count,
        "test_window_cell_count": window_map[HISTORICAL_FUTURES_MARKET_TEMPORAL_WINDOW_NAME_TEST].window_cell_count,
        "matrix_cell_count": summary.matrix_cell_count,
        "consistent_observation_regime_count": summary.consistent_observation_regime_count,
        "divergent_observation_regime_count": summary.divergent_observation_regime_count,
        "insufficient_evidence_regime_count": summary.insufficient_evidence_regime_count,
        "missing_evidence_regime_count": summary.missing_evidence_regime_count,
        "comparable_regime_count": summary.comparable_regime_count,
        "classification": "historical_research_only",
    }


def reject_historical_futures_market_robustness_dossier_promotion(
    _: HistoricalFuturesMarketRobustnessDossierReport,
) -> None:
    raise HistoricalFuturesMarketRobustnessDossierPromotionError(
        "historical futures robustness dossier is not promotion evidence."
    )


__all__ = [
    "HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_PROTOCOL_NAME",
    "HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_PROTOCOL_VERSION",
    "HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_SCHEMA_VERSION",
    "HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_CONSISTENT_OBSERVATION",
    "HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION",
    "HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE",
    "HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE",
    "HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUSES",
    "HistoricalFuturesMarketRobustnessDossierConflictError",
    "HistoricalFuturesMarketRobustnessDossierError",
    "HistoricalFuturesMarketRobustnessDossierIntegrityError",
    "HistoricalFuturesMarketRobustnessDossierPromotionError",
    "HistoricalFuturesMarketRobustnessDossierProtocol",
    "HistoricalFuturesMarketRobustnessDossierReport",
    "HistoricalFuturesMarketRobustnessSummary",
    "HistoricalFuturesMarketRobustnessDossierValidationError",
    "HistoricalFuturesMarketRobustnessCell",
    "HistoricalFuturesMarketRobustnessWindowSummary",
    "build_historical_futures_market_robustness_dossier_protocol",
    "build_historical_futures_market_robustness_dossier_report",
    "load_historical_futures_market_robustness_dossier_report",
    "reject_historical_futures_market_robustness_dossier_promotion",
    "run_historical_futures_market_robustness_dossier",
    "save_historical_futures_market_robustness_dossier_report",
    "status_historical_futures_market_robustness_dossier_report",
    "verify_historical_futures_market_robustness_dossier_report",
]
