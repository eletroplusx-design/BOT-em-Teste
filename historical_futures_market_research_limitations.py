"""Research-only limitations dossier for the Phase 16 historical futures pipeline.

This module consumes the immutable Phase 15 robustness dossier as the canonical
source of the frozen evidence chain. It consolidates only limitations that are
already expressed by the research artifacts and keeps the output strictly
descriptive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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
from historical_futures_market_robustness_dossier import (
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_CONSISTENT_OBSERVATION,
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION,
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE,
    HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE,
    HistoricalFuturesMarketRobustnessDossierConflictError,
    HistoricalFuturesMarketRobustnessDossierIntegrityError,
    HistoricalFuturesMarketRobustnessDossierPromotionError,
    HistoricalFuturesMarketRobustnessDossierReport,
    HistoricalFuturesMarketRobustnessDossierValidationError,
    HistoricalFuturesMarketRobustnessCell,
)
from historical_futures_market_temporal_consistency import (
    HistoricalFuturesMarketTemporalConsistencyIntegrityError,
    HistoricalFuturesMarketTemporalConsistencyReport,
    HistoricalFuturesMarketTemporalConsistencyValidationError,
)
from historical_futures_market_validation import (
    HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES,
    HistoricalFuturesMarketValidationError,
    HistoricalFuturesMarketValidationIntegrityError,
    HistoricalFuturesMarketValidationValidationError,
)
from historical_multitimeframe_analysis import (
    HistoricalMultiTimeframeStrategyAnalysisGroup,
    HistoricalMultiTimeframeStrategyAnalysisReport,
    HistoricalMultiTimeframeStrategyAnalysisValidationError,
)
from market_data import HistoricalDataValidationError

HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_SCHEMA_VERSION = 1
HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_PROTOCOL_NAME = (
    "historical_futures_market_research_limitations"
)
HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_PROTOCOL_VERSION = "v1"


class HistoricalFuturesMarketResearchLimitationsError(Exception):
    pass


class HistoricalFuturesMarketResearchLimitationsValidationError(
    HistoricalFuturesMarketResearchLimitationsError
):
    pass


class HistoricalFuturesMarketResearchLimitationsIntegrityError(
    HistoricalFuturesMarketResearchLimitationsValidationError
):
    pass


class HistoricalFuturesMarketResearchLimitationsConflictError(
    HistoricalFuturesMarketResearchLimitationsIntegrityError
):
    pass


class HistoricalFuturesMarketResearchLimitationsPromotionError(
    HistoricalFuturesMarketResearchLimitationsValidationError
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalFuturesMarketResearchLimitationsValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalFuturesMarketResearchLimitationsValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalFuturesMarketResearchLimitationsValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalFuturesMarketResearchLimitationsValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalFuturesMarketResearchLimitationsValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            )
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                f"{field_name} must be timezone-aware UTC datetime."
            ) from exc
    if not isinstance(value, datetime):
        raise HistoricalFuturesMarketResearchLimitationsValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise HistoricalFuturesMarketResearchLimitationsValidationError(
            f"{field_name} must be timezone-aware UTC datetime."
        )
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _validate_exact_keys(mapping: Mapping[str, Any], *, allowed: set[str], name: str) -> None:
    extra = set(mapping) - allowed
    if extra:
        raise HistoricalFuturesMarketResearchLimitationsValidationError(
            f"{name} contains unknown fields: {sorted(extra)!r}."
        )


def _research_only(historical_research_only: bool, operational_evidence: bool, paper_promotion_eligible: bool) -> None:
    if historical_research_only is not True:
        raise HistoricalFuturesMarketResearchLimitationsValidationError("historical_research_only must be true.")
    if operational_evidence is not False:
        raise HistoricalFuturesMarketResearchLimitationsValidationError("operational_evidence must be false.")
    if paper_promotion_eligible is not False:
        raise HistoricalFuturesMarketResearchLimitationsValidationError("paper_promotion_eligible must be false.")


def _limitation_note(status: str) -> str | None:
    if status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE:
        return "at least one frozen window is absent."
    if status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE:
        return "at least one frozen window has insufficient sample."
    if status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION:
        return "directional signatures differ across the frozen windows."
    return None


def _known_statuses() -> tuple[str, ...]:
    return (
        HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE,
        HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE,
        HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_CONSISTENT_OBSERVATION,
        HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION,
    )


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketResearchLimitation:
    robustness_cell: HistoricalFuturesMarketRobustnessCell
    status: str
    limitation_note: str | None = None
    schema_version: int = HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_SCHEMA_VERSION
    limitation_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.robustness_cell, HistoricalFuturesMarketRobustnessCell):
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "robustness_cell must be a HistoricalFuturesMarketRobustnessCell instance."
            )
        object.__setattr__(self, "status", _require_str(self.status, "status").lower())
        if self.limitation_note is not None:
            object.__setattr__(self, "limitation_note", _require_str(self.limitation_note, "limitation_note"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_SCHEMA_VERSION:
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "research limitation schema_version must be 1."
            )
        if self.status not in _known_statuses():
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "status must be missing_evidence, insufficient_evidence, consistent_observation, or divergent_observation."
            )
        if self.status != self.robustness_cell.status:
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "status diverges from the frozen robustness cell."
            )
        expected_note = _limitation_note(self.status)
        if self.limitation_note != expected_note:
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "limitation_note diverges from the frozen robustness cell."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.limitation_hash:
            if self.limitation_hash != expected:
                raise HistoricalFuturesMarketResearchLimitationsValidationError(
                    "research limitation hash mismatch."
                )
        else:
            object.__setattr__(self, "limitation_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "robustness_cell": self.robustness_cell.as_dict(),
            "status": self.status,
            "limitation_note": self.limitation_note,
        }
        if include_hash:
            payload["limitation_hash"] = self.limitation_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketResearchLimitation":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketResearchLimitationsValidationError("research limitation must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={"schema_version", "robustness_cell", "status", "limitation_note", "limitation_hash"},
            name="research limitation",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                robustness_cell=HistoricalFuturesMarketRobustnessCell.from_dict(mapping["robustness_cell"]),
                status=mapping["status"],
                limitation_note=mapping.get("limitation_note"),
                limitation_hash=mapping.get("limitation_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketResearchLimitationsValidationError("research limitation is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketResearchLimitationsProtocol:
    robustness_dossier_report_hash: str
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
    schema_version: int = HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_SCHEMA_VERSION
    protocol_name: str = HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_PROTOCOL_NAME
    protocol_version: str = HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_PROTOCOL_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    protocol_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "robustness_dossier_report_hash", _require_str(self.robustness_dossier_report_hash, "robustness_dossier_report_hash"))
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
        object.__setattr__(self, "protocol_name", _require_str(self.protocol_name, "protocol_name"))
        object.__setattr__(self, "protocol_version", _require_str(self.protocol_version, "protocol_version"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_SCHEMA_VERSION:
            raise HistoricalFuturesMarketResearchLimitationsValidationError("research limitations schema_version must be 1.")
        if self.protocol_name != HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_PROTOCOL_NAME:
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "protocol_name diverges from the trusted research limitations contract."
            )
        if self.protocol_version != HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_PROTOCOL_VERSION:
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "protocol_version diverges from the trusted research limitations contract."
            )
        if self.window_count != len(HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES):
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "research limitations must cover three frozen windows."
            )
        if len({self.reference_window_hash, self.validation_window_hash, self.test_window_hash}) != 3:
            raise HistoricalFuturesMarketResearchLimitationsValidationError("window hashes must remain distinct.")
        if self.regime_count != len(self.source_group_hashes):
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "regime_count must equal the number of source groups."
            )
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.protocol_hash:
            if self.protocol_hash != expected:
                raise HistoricalFuturesMarketResearchLimitationsValidationError(
                    "research limitations protocol hash mismatch."
                )
        else:
            object.__setattr__(self, "protocol_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "protocol_name": self.protocol_name,
            "protocol_version": self.protocol_version,
            "robustness_dossier_report_hash": self.robustness_dossier_report_hash,
            "validation_report_hash": self.validation_report_hash,
            "contract_hash": self.contract_hash,
            "contract_temporal_split_hash": self.contract_temporal_split_hash,
            "analysis_report_hash": self.analysis_report_hash,
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
            payload["protocol_hash"] = self.protocol_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketResearchLimitationsProtocol":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "research limitations protocol must be a mapping."
            )
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "protocol_name",
                "protocol_version",
                "robustness_dossier_report_hash",
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
            name="research limitations protocol",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                protocol_name=mapping["protocol_name"],
                protocol_version=mapping["protocol_version"],
                robustness_dossier_report_hash=mapping["robustness_dossier_report_hash"],
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
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "research limitations protocol is incomplete."
            ) from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketResearchLimitationsSummary:
    window_count: int
    regime_count: int
    limitation_count: int
    consistent_observation_regime_count: int
    divergent_observation_regime_count: int
    insufficient_evidence_regime_count: int
    missing_evidence_regime_count: int
    noted_regime_count: int
    schema_version: int = HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_SCHEMA_VERSION
    summary_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "window_count", _require_int(self.window_count, "window_count"))
        object.__setattr__(self, "regime_count", _require_int(self.regime_count, "regime_count"))
        object.__setattr__(self, "limitation_count", _require_int(self.limitation_count, "limitation_count", allow_zero=True))
        object.__setattr__(self, "consistent_observation_regime_count", _require_int(self.consistent_observation_regime_count, "consistent_observation_regime_count", allow_zero=True))
        object.__setattr__(self, "divergent_observation_regime_count", _require_int(self.divergent_observation_regime_count, "divergent_observation_regime_count", allow_zero=True))
        object.__setattr__(self, "insufficient_evidence_regime_count", _require_int(self.insufficient_evidence_regime_count, "insufficient_evidence_regime_count", allow_zero=True))
        object.__setattr__(self, "missing_evidence_regime_count", _require_int(self.missing_evidence_regime_count, "missing_evidence_regime_count", allow_zero=True))
        object.__setattr__(self, "noted_regime_count", _require_int(self.noted_regime_count, "noted_regime_count", allow_zero=True))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_SCHEMA_VERSION:
            raise HistoricalFuturesMarketResearchLimitationsValidationError("research limitations summary schema_version must be 1.")
        if self.window_count != len(HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES):
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "research limitations summary must cover three windows."
            )
        if self.regime_count != self.limitation_count:
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "limitation_count must match regime_count."
            )
        if self.regime_count != (
            self.consistent_observation_regime_count
            + self.divergent_observation_regime_count
            + self.insufficient_evidence_regime_count
            + self.missing_evidence_regime_count
        ):
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "research limitations summary regime counts do not reconcile."
            )
        if self.noted_regime_count != (
            self.divergent_observation_regime_count
            + self.insufficient_evidence_regime_count
            + self.missing_evidence_regime_count
        ):
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "research limitations summary note counts do not reconcile."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.summary_hash:
            if self.summary_hash != expected:
                raise HistoricalFuturesMarketResearchLimitationsValidationError(
                    "research limitations summary hash mismatch."
                )
        else:
            object.__setattr__(self, "summary_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "window_count": self.window_count,
            "regime_count": self.regime_count,
            "limitation_count": self.limitation_count,
            "consistent_observation_regime_count": self.consistent_observation_regime_count,
            "divergent_observation_regime_count": self.divergent_observation_regime_count,
            "insufficient_evidence_regime_count": self.insufficient_evidence_regime_count,
            "missing_evidence_regime_count": self.missing_evidence_regime_count,
            "noted_regime_count": self.noted_regime_count,
        }
        if include_hash:
            payload["summary_hash"] = self.summary_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketResearchLimitationsSummary":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketResearchLimitationsValidationError("research limitations summary must be a mapping.")
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "window_count",
                "regime_count",
                "limitation_count",
                "consistent_observation_regime_count",
                "divergent_observation_regime_count",
                "insufficient_evidence_regime_count",
                "missing_evidence_regime_count",
                "noted_regime_count",
                "summary_hash",
            },
            name="research limitations summary",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                window_count=mapping["window_count"],
                regime_count=mapping["regime_count"],
                limitation_count=mapping["limitation_count"],
                consistent_observation_regime_count=mapping["consistent_observation_regime_count"],
                divergent_observation_regime_count=mapping["divergent_observation_regime_count"],
                insufficient_evidence_regime_count=mapping["insufficient_evidence_regime_count"],
                missing_evidence_regime_count=mapping["missing_evidence_regime_count"],
                noted_regime_count=mapping["noted_regime_count"],
                summary_hash=mapping.get("summary_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketResearchLimitationsValidationError("research limitations summary is incomplete.") from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketResearchLimitationsReport:
    robustness_dossier_report: HistoricalFuturesMarketRobustnessDossierReport
    protocol: HistoricalFuturesMarketResearchLimitationsProtocol
    limitations: tuple[HistoricalFuturesMarketResearchLimitation, ...]
    summary: HistoricalFuturesMarketResearchLimitationsSummary
    schema_version: int = HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    report_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.robustness_dossier_report, HistoricalFuturesMarketRobustnessDossierReport):
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "robustness_dossier_report must be a HistoricalFuturesMarketRobustnessDossierReport instance."
            )
        if not isinstance(self.protocol, HistoricalFuturesMarketResearchLimitationsProtocol):
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "protocol must be a research limitations protocol instance."
            )
        if not isinstance(self.limitations, tuple):
            object.__setattr__(self, "limitations", tuple(self.limitations))
        if not isinstance(self.summary, HistoricalFuturesMarketResearchLimitationsSummary):
            raise HistoricalFuturesMarketResearchLimitationsValidationError("summary must be a research limitations summary instance.")
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_SCHEMA_VERSION:
            raise HistoricalFuturesMarketResearchLimitationsValidationError("research limitations report schema_version must be 1.")
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        if (
            self.robustness_dossier_report.historical_research_only is not True
            or self.robustness_dossier_report.operational_evidence is not False
            or self.robustness_dossier_report.paper_promotion_eligible is not False
        ):
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "robustness dossier report must remain research-only."
            )
        expected_protocol = _build_protocol(self.robustness_dossier_report)
        if self.protocol != expected_protocol:
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "research limitations protocol diverges from the frozen robustness dossier."
            )
        expected_limitations = _build_limitations(self.robustness_dossier_report)
        if self.limitations != expected_limitations:
            raise HistoricalFuturesMarketResearchLimitationsIntegrityError(
                "research limitations diverge from the frozen robustness dossier."
            )
        expected_summary = _build_summary(self.robustness_dossier_report, self.limitations)
        if self.summary != expected_summary:
            raise HistoricalFuturesMarketResearchLimitationsIntegrityError(
                "research limitations summary diverges from the frozen evidence."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.report_hash:
            if self.report_hash != expected:
                raise HistoricalFuturesMarketResearchLimitationsValidationError(
                    "research limitations report hash mismatch."
                )
        else:
            object.__setattr__(self, "report_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "robustness_dossier_report": self.robustness_dossier_report.as_dict(),
            "protocol": self.protocol.as_hash_payload(include_hash=False),
            "limitations": [limitation.as_dict() for limitation in self.limitations],
            "summary": self.summary.as_dict(),
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
        }
        if include_hash:
            payload["report_hash"] = self.report_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketResearchLimitationsReport":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "research limitations report must be a mapping."
            )
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "robustness_dossier_report",
                "protocol",
                "limitations",
                "summary",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "report_hash",
            },
            name="research limitations report",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                robustness_dossier_report=HistoricalFuturesMarketRobustnessDossierReport.from_dict(
                    mapping["robustness_dossier_report"]
                ),
                protocol=HistoricalFuturesMarketResearchLimitationsProtocol.from_dict(mapping["protocol"]),
                limitations=tuple(
                    HistoricalFuturesMarketResearchLimitation.from_dict(item) for item in mapping["limitations"]
                ),
                summary=HistoricalFuturesMarketResearchLimitationsSummary.from_dict(mapping["summary"]),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                report_hash=mapping.get("report_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "research limitations report is incomplete."
            ) from exc
        except (
            HistoricalFuturesMarketResearchLimitationsValidationError,
            HistoricalFuturesMarketResearchLimitationsIntegrityError,
            HistoricalFuturesMarketResearchLimitationsError,
            HistoricalFuturesMarketRobustnessDossierValidationError,
            HistoricalFuturesMarketRobustnessDossierIntegrityError,
            HistoricalFuturesMarketValidationValidationError,
            HistoricalFuturesMarketValidationIntegrityError,
            HistoricalFuturesMarketValidationError,
            HistoricalFuturesMarketContractValidationError,
            HistoricalFuturesMarketTemporalConsistencyValidationError,
            HistoricalFuturesMarketTemporalConsistencyIntegrityError,
            HistoricalMultiTimeframeStrategyAnalysisValidationError,
            HistoricalDataValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise HistoricalFuturesMarketResearchLimitationsIntegrityError(str(exc)) from exc


def _build_protocol(
    robustness_dossier_report: HistoricalFuturesMarketRobustnessDossierReport,
) -> HistoricalFuturesMarketResearchLimitationsProtocol:
    temporal_consistency_report = robustness_dossier_report.temporal_consistency_report
    validation_report = temporal_consistency_report.validation_report
    contract = validation_report.contract
    temporal_split = contract.temporal_split_protocol
    analysis_report = validation_report.analysis_report
    source = analysis_report.protocol.source
    source_group_hashes = tuple(group.group_hash for group in analysis_report.groups)
    return HistoricalFuturesMarketResearchLimitationsProtocol(
        robustness_dossier_report_hash=robustness_dossier_report.report_hash,
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


def _build_limitations(
    robustness_dossier_report: HistoricalFuturesMarketRobustnessDossierReport,
) -> tuple[HistoricalFuturesMarketResearchLimitation, ...]:
    analysis_report = robustness_dossier_report.temporal_consistency_report.validation_report.analysis_report
    source_group_hashes = tuple(group.group_hash for group in analysis_report.groups)
    if len(robustness_dossier_report.cells) != len(analysis_report.groups):
        raise HistoricalFuturesMarketResearchLimitationsValidationError(
            "robustness dossier must provide one cell per source group."
        )
    cells_by_group: dict[str, HistoricalFuturesMarketRobustnessCell] = {}
    for cell in robustness_dossier_report.cells:
        group_hash = cell.source_group.group_hash
        if group_hash in cells_by_group:
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "robustness dossier contains duplicate source groups."
            )
        cells_by_group[group_hash] = cell
    if set(cells_by_group) != set(source_group_hashes):
        raise HistoricalFuturesMarketResearchLimitationsValidationError(
            "robustness dossier must preserve the frozen source groups."
        )
    limitations: list[HistoricalFuturesMarketResearchLimitation] = []
    for source_group in analysis_report.groups:
        cell = cells_by_group[source_group.group_hash]
        if cell.source_group.group_hash != source_group.group_hash:
            raise HistoricalFuturesMarketResearchLimitationsValidationError(
                "source group diverges from the frozen robustness cell."
            )
        limitations.append(
            HistoricalFuturesMarketResearchLimitation(
                robustness_cell=cell,
                status=cell.status,
                limitation_note=cell.limitation_note,
            )
        )
    return tuple(limitations)


def _build_summary(
    robustness_dossier_report: HistoricalFuturesMarketRobustnessDossierReport,
    limitations: Sequence[HistoricalFuturesMarketResearchLimitation],
) -> HistoricalFuturesMarketResearchLimitationsSummary:
    _ = robustness_dossier_report
    return HistoricalFuturesMarketResearchLimitationsSummary(
        window_count=len(HISTORICAL_FUTURES_MARKET_VALIDATION_WINDOW_NAMES),
        regime_count=len(limitations),
        limitation_count=len(limitations),
        consistent_observation_regime_count=sum(
            1
            for item in limitations
            if item.status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_CONSISTENT_OBSERVATION
        ),
        divergent_observation_regime_count=sum(
            1
            for item in limitations
            if item.status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_DIVERGENT_OBSERVATION
        ),
        insufficient_evidence_regime_count=sum(
            1
            for item in limitations
            if item.status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_INSUFFICIENT_EVIDENCE
        ),
        missing_evidence_regime_count=sum(
            1
            for item in limitations
            if item.status == HISTORICAL_FUTURES_MARKET_ROBUSTNESS_DOSSIER_STATUS_MISSING_EVIDENCE
        ),
        noted_regime_count=sum(1 for item in limitations if item.limitation_note is not None),
    )


def build_historical_futures_market_research_limitations_protocol(
    robustness_dossier_report: HistoricalFuturesMarketRobustnessDossierReport,
) -> HistoricalFuturesMarketResearchLimitationsProtocol:
    if not isinstance(robustness_dossier_report, HistoricalFuturesMarketRobustnessDossierReport):
        raise HistoricalFuturesMarketResearchLimitationsValidationError(
            "robustness_dossier_report must be a HistoricalFuturesMarketRobustnessDossierReport instance."
        )
    return _build_protocol(robustness_dossier_report)


def build_historical_futures_market_research_limitations_report(
    robustness_dossier_report: HistoricalFuturesMarketRobustnessDossierReport,
) -> HistoricalFuturesMarketResearchLimitationsReport:
    if not isinstance(robustness_dossier_report, HistoricalFuturesMarketRobustnessDossierReport):
        raise HistoricalFuturesMarketResearchLimitationsValidationError(
            "robustness_dossier_report must be a HistoricalFuturesMarketRobustnessDossierReport instance."
        )
    protocol = _build_protocol(robustness_dossier_report)
    limitations = _build_limitations(robustness_dossier_report)
    summary = _build_summary(robustness_dossier_report, limitations)
    return HistoricalFuturesMarketResearchLimitationsReport(
        robustness_dossier_report=robustness_dossier_report,
        protocol=protocol,
        limitations=limitations,
        summary=summary,
    )


def run_historical_futures_market_research_limitations(
    robustness_dossier_report: HistoricalFuturesMarketRobustnessDossierReport,
    *,
    output_file: str | Path | None = None,
) -> HistoricalFuturesMarketResearchLimitationsReport:
    report = build_historical_futures_market_research_limitations_report(robustness_dossier_report)
    if output_file is not None:
        save_historical_futures_market_research_limitations_report(output_file, report)
    return report


def _read(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HistoricalFuturesMarketResearchLimitationsValidationError(
            "research limitations report not found."
        ) from exc
    except Exception as exc:
        raise HistoricalFuturesMarketResearchLimitationsIntegrityError(
            "research limitations report is invalid JSON."
        ) from exc
    if not isinstance(value, Mapping):
        raise HistoricalFuturesMarketResearchLimitationsIntegrityError(
            "research limitations report must be a JSON object."
        )
    return value


def load_historical_futures_market_research_limitations_report(
    path: str | Path,
) -> HistoricalFuturesMarketResearchLimitationsReport:
    payload = _read(Path(path))
    try:
        report = HistoricalFuturesMarketResearchLimitationsReport.from_dict(payload)
    except (
        KeyError,
        TypeError,
        ValueError,
        HistoricalFuturesMarketResearchLimitationsValidationError,
        HistoricalFuturesMarketResearchLimitationsIntegrityError,
        HistoricalFuturesMarketRobustnessDossierValidationError,
        HistoricalFuturesMarketRobustnessDossierIntegrityError,
        HistoricalFuturesMarketValidationValidationError,
        HistoricalFuturesMarketValidationIntegrityError,
        HistoricalFuturesMarketContractValidationError,
        HistoricalFuturesMarketTemporalConsistencyValidationError,
        HistoricalFuturesMarketTemporalConsistencyIntegrityError,
        HistoricalMultiTimeframeStrategyAnalysisValidationError,
        HistoricalDataValidationError,
    ) as exc:
        raise HistoricalFuturesMarketResearchLimitationsIntegrityError(str(exc)) from exc
    if report.as_dict() != payload:
        raise HistoricalFuturesMarketResearchLimitationsIntegrityError(
            "research limitations report payload mismatch."
        )
    return report


def save_historical_futures_market_research_limitations_report(
    path: str | Path,
    report: HistoricalFuturesMarketResearchLimitationsReport,
) -> HistoricalFuturesMarketResearchLimitationsReport:
    file_path = Path(path)
    payload = report.as_dict()
    if file_path.exists():
        existing = load_historical_futures_market_research_limitations_report(file_path)
        if existing.as_dict() != payload:
            raise HistoricalFuturesMarketResearchLimitationsConflictError(
                "research limitations report already exists and differs."
            )
        return existing
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_name(f".{file_path.name}.{os.getpid()}.{id(report)}.tmp")
    try:
        tmp.write_text(_canonical_json(payload), encoding="utf-8")
        try:
            os.link(tmp, file_path)
        except FileExistsError:
            existing = load_historical_futures_market_research_limitations_report(file_path)
            if existing.as_dict() != payload:
                raise HistoricalFuturesMarketResearchLimitationsConflictError(
                    "research limitations report already exists and differs."
                )
            return existing
    except Exception as exc:
        if isinstance(exc, HistoricalFuturesMarketResearchLimitationsConflictError):
            raise
        raise HistoricalFuturesMarketResearchLimitationsValidationError(
            "failed to write research limitations report atomically."
        ) from exc
    finally:
        tmp.unlink(missing_ok=True)
    return report


def verify_historical_futures_market_research_limitations_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_research_limitations_report(path)
    return {
        "verified": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "validation_report_hash": report.robustness_dossier_report.report_hash,
        "classification": "historical_research_only",
    }


def status_historical_futures_market_research_limitations_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_research_limitations_report(path)
    summary = report.summary
    return {
        "exists": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "validation_report_hash": report.robustness_dossier_report.report_hash,
        "contract_hash": report.protocol.contract_hash,
        "analysis_report_hash": report.protocol.analysis_report_hash,
        "window_count": summary.window_count,
        "regime_count": summary.regime_count,
        "limitation_count": summary.limitation_count,
        "consistent_observation_regime_count": summary.consistent_observation_regime_count,
        "divergent_observation_regime_count": summary.divergent_observation_regime_count,
        "insufficient_evidence_regime_count": summary.insufficient_evidence_regime_count,
        "missing_evidence_regime_count": summary.missing_evidence_regime_count,
        "noted_regime_count": summary.noted_regime_count,
        "classification": "historical_research_only",
    }


def reject_historical_futures_market_research_limitations_promotion(
    _: HistoricalFuturesMarketResearchLimitationsReport,
) -> None:
    raise HistoricalFuturesMarketResearchLimitationsPromotionError(
        "historical futures research limitations are not promotion evidence."
    )


__all__ = [
    "HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_PROTOCOL_NAME",
    "HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_PROTOCOL_VERSION",
    "HISTORICAL_FUTURES_MARKET_RESEARCH_LIMITATIONS_SCHEMA_VERSION",
    "HistoricalFuturesMarketResearchLimitationsConflictError",
    "HistoricalFuturesMarketResearchLimitationsError",
    "HistoricalFuturesMarketResearchLimitationsIntegrityError",
    "HistoricalFuturesMarketResearchLimitationsProtocol",
    "HistoricalFuturesMarketResearchLimitationsPromotionError",
    "HistoricalFuturesMarketResearchLimitationsReport",
    "HistoricalFuturesMarketResearchLimitationsSummary",
    "HistoricalFuturesMarketResearchLimitationsValidationError",
    "HistoricalFuturesMarketResearchLimitation",
    "build_historical_futures_market_research_limitations_protocol",
    "build_historical_futures_market_research_limitations_report",
    "load_historical_futures_market_research_limitations_report",
    "reject_historical_futures_market_research_limitations_promotion",
    "run_historical_futures_market_research_limitations",
    "save_historical_futures_market_research_limitations_report",
    "status_historical_futures_market_research_limitations_report",
    "verify_historical_futures_market_research_limitations_report",
]
