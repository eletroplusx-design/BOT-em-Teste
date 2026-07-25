"""Research-only documentary qualification for an independent OKX historical source candidate.

This module consumes the immutable Phase 16 limitations report as the canonical
research provenance anchor and records only documentary, fail-closed evidence
for the OKX spot candidate. It does not download candles, build manifests,
perform replay, backtest, compare performance, or imply operational approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from domain.serialization import serialize_value
from historical_futures_market_research_limitations import (
    HistoricalFuturesMarketResearchLimitationsIntegrityError,
    HistoricalFuturesMarketResearchLimitationsReport,
    HistoricalFuturesMarketResearchLimitationsValidationError,
)
from historical_futures_market_validation import (
    HistoricalFuturesMarketValidationIntegrityError,
    HistoricalFuturesMarketValidationValidationError,
)
from historical_futures_market_temporal_consistency import (
    HistoricalFuturesMarketTemporalConsistencyIntegrityError,
    HistoricalFuturesMarketTemporalConsistencyValidationError,
)
from historical_futures_market_robustness_dossier import (
    HistoricalFuturesMarketRobustnessDossierIntegrityError,
    HistoricalFuturesMarketRobustnessDossierValidationError,
)
from historical_futures_market_contract import HistoricalFuturesMarketContractValidationError
from historical_multitimeframe_analysis import HistoricalMultiTimeframeStrategyAnalysisValidationError
from market_data import HistoricalDataValidationError
from market_data.provider_qualification import HistoricalProviderQualification

HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_SCHEMA_VERSION = 1
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_PROTOCOL_NAME = (
    "historical_futures_market_source_qualification"
)
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_PROTOCOL_VERSION = "v1"
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANONICAL_SOURCE_NAME = "KuCoin spot"
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID = "kucoin.public.klines"
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_NAME = "OKX spot"
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_PROVIDER_ID = "okx.public.klines"
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_ID = (
    HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_PROVIDER_ID
)
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_MARKET_TYPE = "spot"
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SYMBOL = "BTCUSDT"
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL = "BTC-USDT"
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_TIME_SEMANTICS = "utc"
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_ACCESS_TYPE = "public_no_auth"
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_VERSION = "v1"
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE = "okx"
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL = "https://www.okx.com/docs-v5/en/"
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_ENDPOINT_URL = (
    "https://www.okx.com/api/v5/market/history-candles"
)
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE = (
    "confirm=0 means incomplete; confirm=1 means completed"
)
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PAGINATION_LIMIT = 100
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_INTERVALS: tuple[str, ...] = (
    "15m",
    "1h",
    "4h",
)
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_DOCUMENTATION_STATUS_CANDIDATE_ONLY = (
    "documentation_candidate_only"
)
HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_COVERAGE_STATUS_UNVERIFIED = "unverified"


class HistoricalFuturesMarketSourceQualificationError(Exception):
    pass


class HistoricalFuturesMarketSourceQualificationValidationError(
    HistoricalFuturesMarketSourceQualificationError
):
    pass


class HistoricalFuturesMarketSourceQualificationIntegrityError(
    HistoricalFuturesMarketSourceQualificationValidationError
):
    pass


class HistoricalFuturesMarketSourceQualificationConflictError(
    HistoricalFuturesMarketSourceQualificationIntegrityError
):
    pass


class HistoricalFuturesMarketSourceQualificationPromotionError(
    HistoricalFuturesMarketSourceQualificationValidationError
):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalFuturesMarketSourceQualificationValidationError(f"{field_name} is required.")
    return value.strip()


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise HistoricalFuturesMarketSourceQualificationValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise HistoricalFuturesMarketSourceQualificationValidationError(f"{field_name} must be an integer.")
    if allow_zero:
        if value < 0:
            raise HistoricalFuturesMarketSourceQualificationValidationError(f"{field_name} cannot be negative.")
    elif value <= 0:
        raise HistoricalFuturesMarketSourceQualificationValidationError(f"{field_name} must be greater than zero.")
    return int(value)


def _validate_exact_keys(mapping: Mapping[str, Any], *, allowed: set[str], name: str) -> None:
    extra = set(mapping) - allowed
    if extra:
        raise HistoricalFuturesMarketSourceQualificationValidationError(
            f"{name} contains unknown fields: {sorted(extra)!r}."
        )


def _research_only(historical_research_only: bool, operational_evidence: bool, paper_promotion_eligible: bool) -> None:
    if historical_research_only is not True:
        raise HistoricalFuturesMarketSourceQualificationValidationError("historical_research_only must be true.")
    if operational_evidence is not False:
        raise HistoricalFuturesMarketSourceQualificationValidationError("operational_evidence must be false.")
    if paper_promotion_eligible is not False:
        raise HistoricalFuturesMarketSourceQualificationValidationError("paper_promotion_eligible must be false.")


def _require_phase16_report(
    report: HistoricalFuturesMarketResearchLimitationsReport | Mapping[str, Any],
) -> HistoricalFuturesMarketResearchLimitationsReport:
    if isinstance(report, HistoricalFuturesMarketResearchLimitationsReport):
        return report
    if isinstance(report, Mapping):
        return HistoricalFuturesMarketResearchLimitationsReport.from_dict(report)
    raise HistoricalFuturesMarketSourceQualificationValidationError(
        "research_limitations_report must be a HistoricalFuturesMarketResearchLimitationsReport instance."
    )


def _build_candidate_qualifications() -> tuple[HistoricalProviderQualification, ...]:
    qualifications = []
    for interval in HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_INTERVALS:
        qualifications.append(
            HistoricalProviderQualification(
                provider_id=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_PROVIDER_ID,
                provider_version=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_VERSION,
                market_type=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_MARKET_TYPE,
                exchange=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE,
                symbol=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SYMBOL,
                interval=interval,
                time_semantics=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_TIME_SEMANTICS,
                access_type=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_ACCESS_TYPE,
                data_contract_version=2,
                external_symbol=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL,
                endpoint_url=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_ENDPOINT_URL,
                documentation_url=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL,
                pagination_limit=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PAGINATION_LIMIT,
                close_time_rule=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE,
            )
        )
    return tuple(qualifications)


def _phase16_protocol(report: HistoricalFuturesMarketResearchLimitationsReport) -> Any:
    return report.protocol


def _phase16_validation_report_hash(report: HistoricalFuturesMarketResearchLimitationsReport) -> str:
    return report.protocol.validation_report_hash


def _phase16_contract_hash(report: HistoricalFuturesMarketResearchLimitationsReport) -> str:
    return report.protocol.contract_hash


def _phase16_contract_temporal_split_hash(report: HistoricalFuturesMarketResearchLimitationsReport) -> str:
    return report.protocol.contract_temporal_split_hash


def _phase16_analysis_report_hash(report: HistoricalFuturesMarketResearchLimitationsReport) -> str:
    return report.protocol.analysis_report_hash


def _phase16_analysis_protocol_hash(report: HistoricalFuturesMarketResearchLimitationsReport) -> str:
    return report.protocol.analysis_protocol_hash


def _phase16_evaluation_hash(report: HistoricalFuturesMarketResearchLimitationsReport) -> str:
    return report.protocol.evaluation_hash


def _phase16_strategy_report_hash(report: HistoricalFuturesMarketResearchLimitationsReport) -> str:
    return report.protocol.strategy_report_hash


def _phase16_replay_hash(report: HistoricalFuturesMarketResearchLimitationsReport) -> str:
    return report.protocol.replay_hash


def _phase16_bundle_hash(report: HistoricalFuturesMarketResearchLimitationsReport) -> str:
    return report.protocol.bundle_hash


def _phase16_source_hash(report: HistoricalFuturesMarketResearchLimitationsReport) -> str:
    return report.protocol.source_hash


def _phase16_reference_window_hash(report: HistoricalFuturesMarketResearchLimitationsReport) -> str:
    return report.protocol.reference_window_hash


def _phase16_validation_window_hash(report: HistoricalFuturesMarketResearchLimitationsReport) -> str:
    return report.protocol.validation_window_hash


def _phase16_test_window_hash(report: HistoricalFuturesMarketResearchLimitationsReport) -> str:
    return report.protocol.test_window_hash


def _phase16_source_group_hashes(report: HistoricalFuturesMarketResearchLimitationsReport) -> tuple[str, ...]:
    return tuple(report.protocol.source_group_hashes)


def _phase16_window_count(report: HistoricalFuturesMarketResearchLimitationsReport) -> int:
    return report.protocol.window_count


def _phase16_regime_count(report: HistoricalFuturesMarketResearchLimitationsReport) -> int:
    return report.protocol.regime_count


def _require_provider_qualifications(
    qualifications: Sequence[HistoricalProviderQualification],
) -> tuple[HistoricalProviderQualification, ...]:
    if not isinstance(qualifications, Sequence):
        raise HistoricalFuturesMarketSourceQualificationValidationError(
            "provider_qualifications must be a sequence."
        )
    items = tuple(qualifications)
    if len(items) != len(HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_INTERVALS):
        raise HistoricalFuturesMarketSourceQualificationValidationError(
            "provider_qualifications must contain three interval qualifications."
        )
    normalized: list[HistoricalProviderQualification] = []
    for index, expected_interval in enumerate(HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_INTERVALS):
        item = items[index]
        if not isinstance(item, HistoricalProviderQualification):
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider_qualifications must contain HistoricalProviderQualification instances."
            )
        if item.provider_id != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_PROVIDER_ID:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider qualification provider_id diverges from the OKX candidate."
            )
        if item.provider_version != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_VERSION:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider qualification provider_version diverges from the OKX candidate."
            )
        if item.market_type != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_MARKET_TYPE:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider qualification market_type must remain spot."
            )
        if item.exchange != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider qualification exchange must remain OKX."
            )
        if item.symbol != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SYMBOL:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider qualification symbol must remain BTCUSDT."
            )
        if item.external_symbol != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider qualification external_symbol must remain BTC-USDT."
            )
        if item.time_semantics != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_TIME_SEMANTICS:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider qualification time_semantics must remain utc."
            )
        if item.access_type != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_ACCESS_TYPE:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider qualification access_type must remain public_no_auth."
            )
        if item.interval != expected_interval:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider qualification intervals must remain 15m, 1h, and 4h."
            )
        if item.data_contract_version != 2:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider qualification data_contract_version must remain 2."
            )
        if item.endpoint_url != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_ENDPOINT_URL:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider qualification endpoint_url diverges from the OKX candidate."
            )
        if item.documentation_url != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider qualification documentation_url diverges from the OKX candidate."
            )
        if item.pagination_limit != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PAGINATION_LIMIT:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider qualification pagination_limit diverges from the OKX candidate."
            )
        if item.close_time_rule != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider qualification close_time_rule diverges from the OKX candidate."
            )
        normalized.append(item)
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketSourceQualificationProtocol:
    research_limitations_report_hash: str
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
    candidate_source_name: str
    candidate_provider_id: str
    candidate_market_type: str
    candidate_symbol: str
    candidate_external_symbol: str
    candidate_time_semantics: str
    candidate_access_type: str
    documentation_status: str
    coverage_status: str
    provider_qualification_hashes: tuple[str, ...]
    provider_qualification_count: int
    window_count: int
    regime_count: int
    schema_version: int = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_SCHEMA_VERSION
    protocol_name: str = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_PROTOCOL_NAME
    protocol_version: str = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_PROTOCOL_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    protocol_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "research_limitations_report_hash", _require_str(self.research_limitations_report_hash, "research_limitations_report_hash"))
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
        object.__setattr__(self, "candidate_source_name", _require_str(self.candidate_source_name, "candidate_source_name"))
        object.__setattr__(self, "candidate_provider_id", _require_str(self.candidate_provider_id, "candidate_provider_id"))
        object.__setattr__(self, "candidate_market_type", _require_str(self.candidate_market_type, "candidate_market_type"))
        object.__setattr__(self, "candidate_symbol", _require_str(self.candidate_symbol, "candidate_symbol"))
        object.__setattr__(self, "candidate_external_symbol", _require_str(self.candidate_external_symbol, "candidate_external_symbol"))
        object.__setattr__(self, "candidate_time_semantics", _require_str(self.candidate_time_semantics, "candidate_time_semantics"))
        object.__setattr__(self, "candidate_access_type", _require_str(self.candidate_access_type, "candidate_access_type"))
        object.__setattr__(self, "documentation_status", _require_str(self.documentation_status, "documentation_status"))
        object.__setattr__(self, "coverage_status", _require_str(self.coverage_status, "coverage_status"))
        if not isinstance(self.provider_qualification_hashes, tuple):
            object.__setattr__(self, "provider_qualification_hashes", tuple(self.provider_qualification_hashes))
        object.__setattr__(self, "provider_qualification_hashes", tuple(_require_str(item, "provider_qualification_hash") for item in self.provider_qualification_hashes))
        object.__setattr__(self, "provider_qualification_count", _require_int(self.provider_qualification_count, "provider_qualification_count"))
        object.__setattr__(self, "window_count", _require_int(self.window_count, "window_count"))
        object.__setattr__(self, "regime_count", _require_int(self.regime_count, "regime_count"))
        object.__setattr__(self, "protocol_name", _require_str(self.protocol_name, "protocol_name"))
        object.__setattr__(self, "protocol_version", _require_str(self.protocol_version, "protocol_version"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "source qualification schema_version must be 1."
            )
        if self.protocol_name != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_PROTOCOL_NAME:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "protocol_name diverges from the trusted source qualification contract."
            )
        if self.protocol_version != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_PROTOCOL_VERSION:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "protocol_version diverges from the trusted source qualification contract."
            )
        if self.candidate_source_name != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_NAME:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_source_name must remain OKX spot."
            )
        if self.candidate_provider_id != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_PROVIDER_ID:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_provider_id must remain the OKX candidate provider id."
            )
        if self.candidate_market_type != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_MARKET_TYPE:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_market_type must remain spot."
            )
        if self.candidate_symbol != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SYMBOL:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_symbol must remain BTCUSDT."
            )
        if self.candidate_external_symbol != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_external_symbol must remain BTC-USDT."
            )
        if self.candidate_time_semantics != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_TIME_SEMANTICS:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_time_semantics must remain utc."
            )
        if self.candidate_access_type != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_ACCESS_TYPE:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_access_type must remain public_no_auth."
            )
        if self.documentation_status != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_DOCUMENTATION_STATUS_CANDIDATE_ONLY:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "documentation_status must remain documentation_candidate_only."
            )
        if self.coverage_status != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_COVERAGE_STATUS_UNVERIFIED:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "coverage_status must remain unverified."
            )
        if self.candidate_source_name == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANONICAL_SOURCE_NAME:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_source_name must differ from the canonical KuCoin source."
            )
        if self.candidate_provider_id == HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_provider_id must differ from the canonical KuCoin provider."
            )
        if len(self.source_group_hashes) == 0:
            raise HistoricalFuturesMarketSourceQualificationValidationError("source_group_hashes cannot be empty.")
        if len(self.provider_qualification_hashes) != len(HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_INTERVALS):
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider_qualification_hashes must cover three intervals."
            )
        if self.provider_qualification_count != len(self.provider_qualification_hashes):
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider_qualification_count must match the number of interval qualifications."
            )
        if self.window_count != 3:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "window_count must preserve the frozen reference, validation, and test chain."
            )
        if self.regime_count != len(self.source_group_hashes):
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "regime_count must equal the number of source groups."
            )
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.protocol_hash:
            if self.protocol_hash != expected:
                raise HistoricalFuturesMarketSourceQualificationValidationError(
                    "source qualification protocol hash mismatch."
                )
        else:
            object.__setattr__(self, "protocol_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "protocol_name": self.protocol_name,
            "protocol_version": self.protocol_version,
            "research_limitations_report_hash": self.research_limitations_report_hash,
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
            "candidate_source_name": self.candidate_source_name,
            "candidate_provider_id": self.candidate_provider_id,
            "candidate_market_type": self.candidate_market_type,
            "candidate_symbol": self.candidate_symbol,
            "candidate_external_symbol": self.candidate_external_symbol,
            "candidate_time_semantics": self.candidate_time_semantics,
            "candidate_access_type": self.candidate_access_type,
            "documentation_status": self.documentation_status,
            "coverage_status": self.coverage_status,
            "provider_qualification_hashes": list(self.provider_qualification_hashes),
            "provider_qualification_count": self.provider_qualification_count,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketSourceQualificationProtocol":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "source qualification protocol must be a mapping."
            )
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "protocol_name",
                "protocol_version",
                "research_limitations_report_hash",
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
                "candidate_source_name",
                "candidate_provider_id",
                "candidate_market_type",
                "candidate_symbol",
                "candidate_external_symbol",
                "candidate_time_semantics",
                "candidate_access_type",
                "documentation_status",
                "coverage_status",
                "provider_qualification_hashes",
                "provider_qualification_count",
                "window_count",
                "regime_count",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "protocol_hash",
            },
            name="source qualification protocol",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                protocol_name=mapping["protocol_name"],
                protocol_version=mapping["protocol_version"],
                research_limitations_report_hash=mapping["research_limitations_report_hash"],
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
                candidate_source_name=mapping["candidate_source_name"],
                candidate_provider_id=mapping["candidate_provider_id"],
                candidate_market_type=mapping["candidate_market_type"],
                candidate_symbol=mapping["candidate_symbol"],
                candidate_external_symbol=mapping["candidate_external_symbol"],
                candidate_time_semantics=mapping["candidate_time_semantics"],
                candidate_access_type=mapping["candidate_access_type"],
                documentation_status=mapping["documentation_status"],
                coverage_status=mapping["coverage_status"],
                provider_qualification_hashes=tuple(mapping["provider_qualification_hashes"]),
                provider_qualification_count=mapping["provider_qualification_count"],
                window_count=mapping["window_count"],
                regime_count=mapping["regime_count"],
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                protocol_hash=mapping.get("protocol_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "source qualification protocol is incomplete."
            ) from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketSourceQualificationSummary:
    provider_qualification_count: int
    supported_interval_count: int
    documentation_status: str
    coverage_status: str
    schema_version: int = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_SCHEMA_VERSION
    summary_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_qualification_count", _require_int(self.provider_qualification_count, "provider_qualification_count"))
        object.__setattr__(self, "supported_interval_count", _require_int(self.supported_interval_count, "supported_interval_count"))
        object.__setattr__(self, "documentation_status", _require_str(self.documentation_status, "documentation_status"))
        object.__setattr__(self, "coverage_status", _require_str(self.coverage_status, "coverage_status"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "source qualification summary schema_version must be 1."
            )
        if self.documentation_status != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_DOCUMENTATION_STATUS_CANDIDATE_ONLY:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "documentation_status must remain documentation_candidate_only."
            )
        if self.coverage_status != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_COVERAGE_STATUS_UNVERIFIED:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "coverage_status must remain unverified."
            )
        if self.provider_qualification_count != 3:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider_qualification_count must be exactly three."
            )
        if self.supported_interval_count != 3:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "supported_interval_count must be exactly three."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.summary_hash:
            if self.summary_hash != expected:
                raise HistoricalFuturesMarketSourceQualificationValidationError(
                    "source qualification summary hash mismatch."
                )
        else:
            object.__setattr__(self, "summary_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "provider_qualification_count": self.provider_qualification_count,
            "supported_interval_count": self.supported_interval_count,
            "documentation_status": self.documentation_status,
            "coverage_status": self.coverage_status,
        }
        if include_hash:
            payload["summary_hash"] = self.summary_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload(include_hash=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketSourceQualificationSummary":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "source qualification summary must be a mapping."
            )
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "provider_qualification_count",
                "supported_interval_count",
                "documentation_status",
                "coverage_status",
                "summary_hash",
            },
            name="source qualification summary",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                provider_qualification_count=mapping["provider_qualification_count"],
                supported_interval_count=mapping["supported_interval_count"],
                documentation_status=mapping["documentation_status"],
                coverage_status=mapping["coverage_status"],
                summary_hash=mapping.get("summary_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "source qualification summary is incomplete."
            ) from exc


@dataclass(frozen=True, slots=True)
class HistoricalFuturesMarketSourceQualificationReport:
    research_limitations_report: HistoricalFuturesMarketResearchLimitationsReport
    protocol: HistoricalFuturesMarketSourceQualificationProtocol
    provider_qualifications: tuple[HistoricalProviderQualification, ...]
    canonical_source_name: str
    canonical_source_provider_id: str
    candidate_source_name: str
    candidate_provider_id: str
    candidate_market_type: str
    candidate_symbol: str
    candidate_external_symbol: str
    candidate_time_semantics: str
    candidate_access_type: str
    documentation_status: str
    coverage_status: str
    independence_evidence: str
    non_operational_scope_statement: str
    summary: HistoricalFuturesMarketSourceQualificationSummary
    schema_version: int = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_SCHEMA_VERSION
    historical_research_only: bool = True
    operational_evidence: bool = False
    paper_promotion_eligible: bool = False
    report_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.research_limitations_report, HistoricalFuturesMarketResearchLimitationsReport):
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "research_limitations_report must be a research limitations report instance."
            )
        if not isinstance(self.protocol, HistoricalFuturesMarketSourceQualificationProtocol):
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "protocol must be a source qualification protocol instance."
            )
        if not isinstance(self.provider_qualifications, tuple):
            object.__setattr__(self, "provider_qualifications", tuple(self.provider_qualifications))
        if not isinstance(self.summary, HistoricalFuturesMarketSourceQualificationSummary):
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "summary must be a source qualification summary instance."
            )
        object.__setattr__(self, "canonical_source_name", _require_str(self.canonical_source_name, "canonical_source_name"))
        object.__setattr__(self, "canonical_source_provider_id", _require_str(self.canonical_source_provider_id, "canonical_source_provider_id"))
        object.__setattr__(self, "candidate_source_name", _require_str(self.candidate_source_name, "candidate_source_name"))
        object.__setattr__(self, "candidate_provider_id", _require_str(self.candidate_provider_id, "candidate_provider_id"))
        object.__setattr__(self, "candidate_market_type", _require_str(self.candidate_market_type, "candidate_market_type"))
        object.__setattr__(self, "candidate_symbol", _require_str(self.candidate_symbol, "candidate_symbol"))
        object.__setattr__(self, "candidate_external_symbol", _require_str(self.candidate_external_symbol, "candidate_external_symbol"))
        object.__setattr__(self, "candidate_time_semantics", _require_str(self.candidate_time_semantics, "candidate_time_semantics"))
        object.__setattr__(self, "candidate_access_type", _require_str(self.candidate_access_type, "candidate_access_type"))
        object.__setattr__(self, "documentation_status", _require_str(self.documentation_status, "documentation_status"))
        object.__setattr__(self, "coverage_status", _require_str(self.coverage_status, "coverage_status"))
        object.__setattr__(self, "independence_evidence", _require_str(self.independence_evidence, "independence_evidence"))
        object.__setattr__(self, "non_operational_scope_statement", _require_str(self.non_operational_scope_statement, "non_operational_scope_statement"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        if self.schema_version != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_SCHEMA_VERSION:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "source qualification report schema_version must be 1."
            )
        _research_only(self.historical_research_only, self.operational_evidence, self.paper_promotion_eligible)
        if self.canonical_source_name != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANONICAL_SOURCE_NAME:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "canonical_source_name must remain KuCoin spot."
            )
        if self.canonical_source_provider_id != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "canonical_source_provider_id must remain the KuCoin provider id."
            )
        if self.candidate_source_name != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_NAME:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_source_name must remain OKX spot."
            )
        if self.candidate_provider_id != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_PROVIDER_ID:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_provider_id must remain the OKX provider id."
            )
        if self.candidate_market_type != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_MARKET_TYPE:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_market_type must remain spot."
            )
        if self.candidate_symbol != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SYMBOL:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_symbol must remain BTCUSDT."
            )
        if self.candidate_external_symbol != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_external_symbol must remain BTC-USDT."
            )
        if self.candidate_time_semantics != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_TIME_SEMANTICS:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_time_semantics must remain utc."
            )
        if self.candidate_access_type != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_ACCESS_TYPE:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_access_type must remain public_no_auth."
            )
        if self.documentation_status != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_DOCUMENTATION_STATUS_CANDIDATE_ONLY:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "documentation_status must remain documentation_candidate_only."
            )
        if self.coverage_status != HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_COVERAGE_STATUS_UNVERIFIED:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "coverage_status must remain unverified."
            )
        if self.canonical_source_provider_id == self.candidate_provider_id:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_provider_id must differ from the canonical KuCoin provider."
            )
        if self.canonical_source_name == self.candidate_source_name:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "candidate_source_name must differ from the canonical KuCoin source."
            )
        if "OKX" not in self.independence_evidence or "KuCoin" not in self.independence_evidence:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "independence_evidence must explicitly distinguish OKX from KuCoin."
            )
        if "dataset" not in self.non_operational_scope_statement.lower():
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "non_operational_scope_statement must state that no dataset was obtained."
            )
        if len(self.provider_qualifications) != len(HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_INTERVALS):
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider_qualifications must contain exactly three interval qualifications."
            )
        normalized = _require_provider_qualifications(self.provider_qualifications)
        if tuple(item.qualification_hash for item in normalized) != self.protocol.provider_qualification_hashes:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "provider qualification hashes diverge from the frozen protocol."
            )
        if self.protocol.candidate_source_name != self.candidate_source_name:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "protocol candidate_source_name diverges from the frozen report."
            )
        if self.protocol.candidate_provider_id != self.candidate_provider_id:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "protocol candidate_provider_id diverges from the frozen report."
            )
        if self.protocol.candidate_market_type != self.candidate_market_type:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "protocol candidate_market_type diverges from the frozen report."
            )
        if self.protocol.candidate_symbol != self.candidate_symbol:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "protocol candidate_symbol diverges from the frozen report."
            )
        if self.protocol.candidate_external_symbol != self.candidate_external_symbol:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "protocol candidate_external_symbol diverges from the frozen report."
            )
        if self.protocol.candidate_time_semantics != self.candidate_time_semantics:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "protocol candidate_time_semantics diverges from the frozen report."
            )
        if self.protocol.candidate_access_type != self.candidate_access_type:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "protocol candidate_access_type diverges from the frozen report."
            )
        if self.protocol.documentation_status != self.documentation_status:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "protocol documentation_status diverges from the frozen report."
            )
        if self.protocol.coverage_status != self.coverage_status:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "protocol coverage_status diverges from the frozen report."
            )
        expected_protocol = _build_protocol(self.research_limitations_report, normalized, self)
        if self.protocol != expected_protocol:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "source qualification protocol diverges from the frozen research limitations report."
            )
        expected_summary = _build_summary(self.research_limitations_report, normalized, self)
        if self.summary != expected_summary:
            raise HistoricalFuturesMarketSourceQualificationIntegrityError(
                "source qualification summary diverges from the frozen evidence."
            )
        expected = _hash_payload(self.as_hash_payload(include_hash=False))
        if self.report_hash:
            if self.report_hash != expected:
                raise HistoricalFuturesMarketSourceQualificationValidationError(
                    "source qualification report hash mismatch."
                )
        else:
            object.__setattr__(self, "report_hash", expected)

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "research_limitations_report": self.research_limitations_report.as_dict(),
            "protocol": self.protocol.as_hash_payload(include_hash=False),
            "provider_qualifications": [qualification.as_dict() for qualification in self.provider_qualifications],
            "canonical_source_name": self.canonical_source_name,
            "canonical_source_provider_id": self.canonical_source_provider_id,
            "candidate_source_name": self.candidate_source_name,
            "candidate_provider_id": self.candidate_provider_id,
            "candidate_market_type": self.candidate_market_type,
            "candidate_symbol": self.candidate_symbol,
            "candidate_external_symbol": self.candidate_external_symbol,
            "candidate_time_semantics": self.candidate_time_semantics,
            "candidate_access_type": self.candidate_access_type,
            "documentation_status": self.documentation_status,
            "coverage_status": self.coverage_status,
            "independence_evidence": self.independence_evidence,
            "non_operational_scope_statement": self.non_operational_scope_statement,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "HistoricalFuturesMarketSourceQualificationReport":
        if not isinstance(data, Mapping):
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "source qualification report must be a mapping."
            )
        mapping = dict(data)
        _validate_exact_keys(
            mapping,
            allowed={
                "schema_version",
                "research_limitations_report",
                "protocol",
                "provider_qualifications",
                "canonical_source_name",
                "canonical_source_provider_id",
                "candidate_source_name",
                "candidate_provider_id",
                "candidate_market_type",
                "candidate_symbol",
                "candidate_external_symbol",
                "candidate_time_semantics",
                "candidate_access_type",
                "documentation_status",
                "coverage_status",
                "independence_evidence",
                "non_operational_scope_statement",
                "summary",
                "historical_research_only",
                "operational_evidence",
                "paper_promotion_eligible",
                "report_hash",
            },
            name="source qualification report",
        )
        try:
            return cls(
                schema_version=mapping["schema_version"],
                research_limitations_report=_require_phase16_report(mapping["research_limitations_report"]),
                protocol=HistoricalFuturesMarketSourceQualificationProtocol.from_dict(mapping["protocol"]),
                provider_qualifications=tuple(
                    HistoricalProviderQualification.from_dict(item) for item in mapping["provider_qualifications"]
                ),
                canonical_source_name=mapping["canonical_source_name"],
                canonical_source_provider_id=mapping["canonical_source_provider_id"],
                candidate_source_name=mapping["candidate_source_name"],
                candidate_provider_id=mapping["candidate_provider_id"],
                candidate_market_type=mapping["candidate_market_type"],
                candidate_symbol=mapping["candidate_symbol"],
                candidate_external_symbol=mapping["candidate_external_symbol"],
                candidate_time_semantics=mapping["candidate_time_semantics"],
                candidate_access_type=mapping["candidate_access_type"],
                documentation_status=mapping["documentation_status"],
                coverage_status=mapping["coverage_status"],
                independence_evidence=mapping["independence_evidence"],
                non_operational_scope_statement=mapping["non_operational_scope_statement"],
                summary=HistoricalFuturesMarketSourceQualificationSummary.from_dict(mapping["summary"]),
                historical_research_only=mapping.get("historical_research_only", True),
                operational_evidence=mapping.get("operational_evidence", False),
                paper_promotion_eligible=mapping.get("paper_promotion_eligible", False),
                report_hash=mapping.get("report_hash", ""),
            )
        except KeyError as exc:
            raise HistoricalFuturesMarketSourceQualificationValidationError(
                "source qualification report is incomplete."
            ) from exc
        except (
            HistoricalFuturesMarketSourceQualificationValidationError,
            HistoricalFuturesMarketSourceQualificationIntegrityError,
            HistoricalFuturesMarketSourceQualificationError,
            HistoricalFuturesMarketResearchLimitationsValidationError,
            HistoricalFuturesMarketResearchLimitationsIntegrityError,
            HistoricalFuturesMarketRobustnessDossierValidationError,
            HistoricalFuturesMarketRobustnessDossierIntegrityError,
            HistoricalFuturesMarketValidationValidationError,
            HistoricalFuturesMarketValidationIntegrityError,
            HistoricalFuturesMarketTemporalConsistencyValidationError,
            HistoricalFuturesMarketTemporalConsistencyIntegrityError,
            HistoricalFuturesMarketContractValidationError,
            HistoricalMultiTimeframeStrategyAnalysisValidationError,
            HistoricalDataValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise HistoricalFuturesMarketSourceQualificationIntegrityError(str(exc)) from exc


def _build_protocol(
    research_limitations_report: HistoricalFuturesMarketResearchLimitationsReport,
    provider_qualifications: Sequence[HistoricalProviderQualification],
    report: HistoricalFuturesMarketSourceQualificationReport | None = None,
) -> HistoricalFuturesMarketSourceQualificationProtocol:
    limitations_protocol = _phase16_protocol(research_limitations_report)
    if report is None:
        candidate_source_name = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_NAME
        candidate_provider_id = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_PROVIDER_ID
        candidate_market_type = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_MARKET_TYPE
        candidate_symbol = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SYMBOL
        candidate_external_symbol = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL
        candidate_time_semantics = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_TIME_SEMANTICS
        candidate_access_type = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_ACCESS_TYPE
        documentation_status = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_DOCUMENTATION_STATUS_CANDIDATE_ONLY
        coverage_status = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_COVERAGE_STATUS_UNVERIFIED
    else:
        candidate_source_name = report.candidate_source_name
        candidate_provider_id = report.candidate_provider_id
        candidate_market_type = report.candidate_market_type
        candidate_symbol = report.candidate_symbol
        candidate_external_symbol = report.candidate_external_symbol
        candidate_time_semantics = report.candidate_time_semantics
        candidate_access_type = report.candidate_access_type
        documentation_status = report.documentation_status
        coverage_status = report.coverage_status
    provider_qualification_hashes = tuple(item.qualification_hash for item in provider_qualifications)
    return HistoricalFuturesMarketSourceQualificationProtocol(
        research_limitations_report_hash=research_limitations_report.report_hash,
        robustness_dossier_report_hash=limitations_protocol.robustness_dossier_report_hash,
        validation_report_hash=limitations_protocol.validation_report_hash,
        contract_hash=limitations_protocol.contract_hash,
        contract_temporal_split_hash=limitations_protocol.contract_temporal_split_hash,
        analysis_report_hash=limitations_protocol.analysis_report_hash,
        analysis_protocol_hash=limitations_protocol.analysis_protocol_hash,
        evaluation_hash=limitations_protocol.evaluation_hash,
        strategy_report_hash=limitations_protocol.strategy_report_hash,
        replay_hash=limitations_protocol.replay_hash,
        bundle_hash=limitations_protocol.bundle_hash,
        source_hash=limitations_protocol.source_hash,
        reference_window_hash=limitations_protocol.reference_window_hash,
        validation_window_hash=limitations_protocol.validation_window_hash,
        test_window_hash=limitations_protocol.test_window_hash,
        source_group_hashes=tuple(limitations_protocol.source_group_hashes),
        candidate_source_name=candidate_source_name,
        candidate_provider_id=candidate_provider_id,
        candidate_market_type=candidate_market_type,
        candidate_symbol=candidate_symbol,
        candidate_external_symbol=candidate_external_symbol,
        candidate_time_semantics=candidate_time_semantics,
        candidate_access_type=candidate_access_type,
        documentation_status=documentation_status,
        coverage_status=coverage_status,
        provider_qualification_hashes=provider_qualification_hashes,
        provider_qualification_count=len(provider_qualification_hashes),
        window_count=limitations_protocol.window_count,
        regime_count=limitations_protocol.regime_count,
    )


def _build_summary(
    research_limitations_report: HistoricalFuturesMarketResearchLimitationsReport,
    provider_qualifications: Sequence[HistoricalProviderQualification],
    report: HistoricalFuturesMarketSourceQualificationReport | None = None,
) -> HistoricalFuturesMarketSourceQualificationSummary:
    _ = research_limitations_report
    if report is None:
        documentation_status = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_DOCUMENTATION_STATUS_CANDIDATE_ONLY
        coverage_status = HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_COVERAGE_STATUS_UNVERIFIED
    else:
        documentation_status = report.documentation_status
        coverage_status = report.coverage_status
    return HistoricalFuturesMarketSourceQualificationSummary(
        provider_qualification_count=len(provider_qualifications),
        supported_interval_count=len(HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_INTERVALS),
        documentation_status=documentation_status,
        coverage_status=coverage_status,
    )


def build_historical_futures_market_source_qualification_report(
    research_limitations_report: HistoricalFuturesMarketResearchLimitationsReport | Mapping[str, Any],
) -> HistoricalFuturesMarketSourceQualificationReport:
    research_limitations_report = _require_phase16_report(research_limitations_report)
    provider_qualifications = _build_candidate_qualifications()
    protocol = _build_protocol(research_limitations_report, provider_qualifications)
    report = HistoricalFuturesMarketSourceQualificationReport(
        research_limitations_report=research_limitations_report,
        protocol=protocol,
        provider_qualifications=provider_qualifications,
        canonical_source_name=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANONICAL_SOURCE_NAME,
        canonical_source_provider_id=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID,
        candidate_source_name=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_NAME,
        candidate_provider_id=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_PROVIDER_ID,
        candidate_market_type=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_MARKET_TYPE,
        candidate_symbol=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SYMBOL,
        candidate_external_symbol=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL,
        candidate_time_semantics=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_TIME_SEMANTICS,
        candidate_access_type=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_ACCESS_TYPE,
        documentation_status=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_DOCUMENTATION_STATUS_CANDIDATE_ONLY,
        coverage_status=HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_COVERAGE_STATUS_UNVERIFIED,
        independence_evidence=(
            "Official OKX spot documentation and public candles endpoint are distinct from the canonical KuCoin spot chain."
        ),
        non_operational_scope_statement=(
            "No dataset, manifest_hash, content_hash, replay, backtest, or performance comparison was obtained or inferred."
        ),
        summary=_build_summary(research_limitations_report, provider_qualifications),
    )
    protocol = _build_protocol(research_limitations_report, provider_qualifications, report)
    return HistoricalFuturesMarketSourceQualificationReport(
        research_limitations_report=research_limitations_report,
        protocol=protocol,
        provider_qualifications=provider_qualifications,
        canonical_source_name=report.canonical_source_name,
        canonical_source_provider_id=report.canonical_source_provider_id,
        candidate_source_name=report.candidate_source_name,
        candidate_provider_id=report.candidate_provider_id,
        candidate_market_type=report.candidate_market_type,
        candidate_symbol=report.candidate_symbol,
        candidate_external_symbol=report.candidate_external_symbol,
        candidate_time_semantics=report.candidate_time_semantics,
        candidate_access_type=report.candidate_access_type,
        documentation_status=report.documentation_status,
        coverage_status=report.coverage_status,
        independence_evidence=report.independence_evidence,
        non_operational_scope_statement=report.non_operational_scope_statement,
        summary=report.summary,
    )


def run_historical_futures_market_source_qualification(
    research_limitations_report: HistoricalFuturesMarketResearchLimitationsReport | Mapping[str, Any],
    *,
    output_file: str | Path | None = None,
) -> HistoricalFuturesMarketSourceQualificationReport:
    report = build_historical_futures_market_source_qualification_report(research_limitations_report)
    if output_file is not None:
        save_historical_futures_market_source_qualification_report(output_file, report)
    return report


def _read(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HistoricalFuturesMarketSourceQualificationValidationError(
            "source qualification report not found."
        ) from exc
    except Exception as exc:
        raise HistoricalFuturesMarketSourceQualificationIntegrityError(
            "source qualification report is invalid JSON."
        ) from exc
    if not isinstance(value, Mapping):
        raise HistoricalFuturesMarketSourceQualificationIntegrityError(
            "source qualification report must be a JSON object."
        )
    return value


def load_historical_futures_market_source_qualification_report(
    path: str | Path,
) -> HistoricalFuturesMarketSourceQualificationReport:
    payload = _read(Path(path))
    try:
        report = HistoricalFuturesMarketSourceQualificationReport.from_dict(payload)
    except (
        KeyError,
        TypeError,
        ValueError,
        HistoricalFuturesMarketSourceQualificationValidationError,
        HistoricalFuturesMarketSourceQualificationIntegrityError,
        HistoricalFuturesMarketResearchLimitationsValidationError,
        HistoricalFuturesMarketResearchLimitationsIntegrityError,
        HistoricalFuturesMarketRobustnessDossierValidationError,
        HistoricalFuturesMarketRobustnessDossierIntegrityError,
        HistoricalFuturesMarketValidationValidationError,
        HistoricalFuturesMarketValidationIntegrityError,
        HistoricalFuturesMarketTemporalConsistencyValidationError,
        HistoricalFuturesMarketTemporalConsistencyIntegrityError,
        HistoricalFuturesMarketContractValidationError,
        HistoricalMultiTimeframeStrategyAnalysisValidationError,
        HistoricalDataValidationError,
    ) as exc:
        raise HistoricalFuturesMarketSourceQualificationIntegrityError(str(exc)) from exc
    if report.as_dict() != payload:
        raise HistoricalFuturesMarketSourceQualificationIntegrityError(
            "source qualification report payload mismatch."
        )
    return report


def save_historical_futures_market_source_qualification_report(
    path: str | Path,
    report: HistoricalFuturesMarketSourceQualificationReport,
) -> HistoricalFuturesMarketSourceQualificationReport:
    file_path = Path(path)
    payload = report.as_dict()
    if file_path.exists():
        existing = load_historical_futures_market_source_qualification_report(file_path)
        if existing.as_dict() != payload:
            raise HistoricalFuturesMarketSourceQualificationConflictError(
                "source qualification report already exists and differs."
            )
        return existing
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_name(f".{file_path.name}.{os.getpid()}.{id(report)}.tmp")
    try:
        tmp.write_text(_canonical_json(payload), encoding="utf-8")
        try:
            os.link(tmp, file_path)
        except FileExistsError:
            existing = load_historical_futures_market_source_qualification_report(file_path)
            if existing.as_dict() != payload:
                raise HistoricalFuturesMarketSourceQualificationConflictError(
                    "source qualification report already exists and differs."
                )
            return existing
    except Exception as exc:
        if isinstance(exc, HistoricalFuturesMarketSourceQualificationConflictError):
            raise
        raise HistoricalFuturesMarketSourceQualificationValidationError(
            "failed to write source qualification report atomically."
        ) from exc
    finally:
        tmp.unlink(missing_ok=True)
    return report


def verify_historical_futures_market_source_qualification_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_source_qualification_report(path)
    return {
        "verified": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "research_limitations_report_hash": report.research_limitations_report.report_hash,
        "classification": "historical_research_only",
        "documentation_status": report.documentation_status,
        "coverage_status": report.coverage_status,
    }


def status_historical_futures_market_source_qualification_report(path: str | Path) -> dict[str, Any]:
    report = load_historical_futures_market_source_qualification_report(path)
    summary = report.summary
    return {
        "exists": True,
        "report_hash": report.report_hash,
        "protocol_hash": report.protocol.protocol_hash,
        "research_limitations_report_hash": report.research_limitations_report.report_hash,
        "window_count": report.protocol.window_count,
        "regime_count": report.protocol.regime_count,
        "provider_qualification_count": summary.provider_qualification_count,
        "supported_interval_count": summary.supported_interval_count,
        "documentation_status": summary.documentation_status,
        "coverage_status": summary.coverage_status,
        "candidate_source_name": report.candidate_source_name,
        "candidate_provider_id": report.candidate_provider_id,
        "classification": "historical_research_only",
    }


def reject_historical_futures_market_source_qualification_promotion(
    _: HistoricalFuturesMarketSourceQualificationReport,
) -> None:
    raise HistoricalFuturesMarketSourceQualificationPromotionError(
        "historical futures source qualification is not promotion evidence."
    )


__all__ = [
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANONICAL_SOURCE_NAME",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANONICAL_SOURCE_PROVIDER_ID",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_ACCESS_TYPE",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_CLOSE_TIME_RULE",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_DOCUMENTATION_URL",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_ENDPOINT_URL",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_EXTERNAL_SYMBOL",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_INTERVALS",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_MARKET_TYPE",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_EXCHANGE",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_ID",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PROVIDER_VERSION",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SOURCE_NAME",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_SYMBOL",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_TIME_SEMANTICS",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_CANDIDATE_PAGINATION_LIMIT",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_COVERAGE_STATUS_UNVERIFIED",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_DOCUMENTATION_STATUS_CANDIDATE_ONLY",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_PROTOCOL_NAME",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_PROTOCOL_VERSION",
    "HISTORICAL_FUTURES_MARKET_SOURCE_QUALIFICATION_SCHEMA_VERSION",
    "HistoricalFuturesMarketSourceQualificationConflictError",
    "HistoricalFuturesMarketSourceQualificationError",
    "HistoricalFuturesMarketSourceQualificationIntegrityError",
    "HistoricalFuturesMarketSourceQualificationProtocol",
    "HistoricalFuturesMarketSourceQualificationPromotionError",
    "HistoricalFuturesMarketSourceQualificationReport",
    "HistoricalFuturesMarketSourceQualificationSummary",
    "HistoricalFuturesMarketSourceQualificationValidationError",
    "build_historical_futures_market_source_qualification_report",
    "load_historical_futures_market_source_qualification_report",
    "reject_historical_futures_market_source_qualification_promotion",
    "run_historical_futures_market_source_qualification",
    "save_historical_futures_market_source_qualification_report",
    "status_historical_futures_market_source_qualification_report",
    "verify_historical_futures_market_source_qualification_report",
]
