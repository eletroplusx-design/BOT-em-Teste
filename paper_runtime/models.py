from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4

from domain.serialization import serialize_value
from promotion import PaperMonitoringSessionContract
from promotion.errors import PromotionPolicyError

from .audit import sha256_hex
from .errors import PaperRuntimePolicyError, PaperRuntimeSessionError


def _require_timezone_aware(dt: datetime, field_name: str) -> datetime:
    if not isinstance(dt, datetime):
        raise PaperRuntimePolicyError(f"{field_name} must be a datetime.")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise PaperRuntimePolicyError(f"{field_name} must be timezone-aware.")
    return dt.astimezone(timezone.utc)


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise PaperRuntimePolicyError(f"{field_name} must be a boolean.")
    return bool(value)


def _require_int(value: Any, field_name: str, *, allow_zero: bool = True) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise PaperRuntimePolicyError(f"{field_name} must be an integer.")
    if allow_zero and value < 0:
        raise PaperRuntimePolicyError(f"{field_name} cannot be negative.")
    if not allow_zero and value <= 0:
        raise PaperRuntimePolicyError(f"{field_name} must be greater than zero.")
    return int(value)


def _require_decimal(value: Any, field_name: str, *, allow_zero: bool = True) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    else:
        try:
            result = Decimal(str(value))
        except Exception as exc:
            raise PaperRuntimePolicyError(f"{field_name} must be numeric.") from exc
    if not result.is_finite():
        raise PaperRuntimePolicyError(f"{field_name} must be finite.")
    if allow_zero:
        if result < 0:
            raise PaperRuntimePolicyError(f"{field_name} cannot be negative.")
    elif result <= 0:
        raise PaperRuntimePolicyError(f"{field_name} must be greater than zero.")
    return result


def _require_str(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise PaperRuntimePolicyError(f"{field_name} must be a string.")
    result = value.strip()
    if not result and not allow_empty:
        raise PaperRuntimePolicyError(f"{field_name} must be a non-empty string.")
    return result


class PaperRuntimeState(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PaperRuntimeEventType(str, Enum):
    SESSION_CREATED = "SESSION_CREATED"
    SESSION_STARTED = "SESSION_STARTED"
    SNAPSHOT_RECORDED = "SNAPSHOT_RECORDED"
    SESSION_SUSPENDED = "SESSION_SUSPENDED"
    SESSION_COMPLETED = "SESSION_COMPLETED"
    SESSION_FAILED = "SESSION_FAILED"
    ORDER_BLOCKED = "ORDER_BLOCKED"
    TRADE_RECORDED = "TRADE_RECORDED"
    FILL = "FILL"


@dataclass(frozen=True, slots=True)
class PaperRuntimeContract:
    session_id: str
    session_started_utc: datetime
    decision_hash: str
    evidence_hash: str
    paper_limits_hash: str
    paper_limits: Mapping[str, Any]
    configuration: Mapping[str, Any]
    strategy_version: str
    symbol: str
    interval: str
    execution_contract: Mapping[str, Any]
    paper_only: bool = True
    contract_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _require_str(self.session_id, "session_id"))
        object.__setattr__(self, "session_started_utc", _require_timezone_aware(self.session_started_utc, "session_started_utc"))
        object.__setattr__(self, "decision_hash", _require_str(self.decision_hash, "decision_hash"))
        object.__setattr__(self, "evidence_hash", _require_str(self.evidence_hash, "evidence_hash"))
        object.__setattr__(self, "paper_limits_hash", _require_str(self.paper_limits_hash, "paper_limits_hash"))
        object.__setattr__(self, "strategy_version", _require_str(self.strategy_version, "strategy_version"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol"))
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "paper_only", _require_bool(self.paper_only, "paper_only"))
        object.__setattr__(self, "paper_limits", dict(self.paper_limits))
        object.__setattr__(self, "configuration", dict(self.configuration))
        object.__setattr__(self, "execution_contract", dict(self.execution_contract))
        object.__setattr__(self, "contract_hash", sha256_hex(self.as_hash_payload()))

    def as_hash_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_started_utc": self.session_started_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "decision_hash": self.decision_hash,
            "evidence_hash": self.evidence_hash,
            "paper_limits_hash": self.paper_limits_hash,
            "paper_limits": self.paper_limits,
            "configuration": self.configuration,
            "strategy_version": self.strategy_version,
            "symbol": self.symbol,
            "interval": self.interval,
            "execution_contract": self.execution_contract,
            "paper_only": self.paper_only,
        }

    def as_dict(self) -> dict[str, Any]:
        payload = dict(self.as_hash_payload())
        payload["paper_limits"] = serialize_value(payload["paper_limits"])
        payload["configuration"] = serialize_value(payload["configuration"])
        payload["execution_contract"] = serialize_value(payload["execution_contract"])
        payload["contract_hash"] = self.contract_hash
        return payload

    def to_promotion_contract(self) -> PaperMonitoringSessionContract:
        return PaperMonitoringSessionContract(
            session_id=self.session_id,
            session_started_utc=self.session_started_utc,
        )


@dataclass(frozen=True, slots=True)
class PaperRuntimeSessionRecord:
    session_id: str
    state: PaperRuntimeState
    version: int
    contract_hash: str
    decision_json: str
    decision_hash: str
    evidence_hash: str
    paper_limits_hash: str
    strategy_version: str
    symbol: str
    interval: str
    configuration_hash: str
    paper_limits_json: str
    configuration_json: str
    execution_contract_json: str
    execution_contract_hash: str
    paper_only: bool
    created_at_utc: datetime
    updated_at_utc: datetime
    session_started_utc: datetime
    last_snapshot_hash: str | None = None
    last_event_hash: str | None = None
    suspended_reason: str | None = None
    completed_reason: str | None = None
    failed_reason: str | None = None
    active: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _require_str(self.session_id, "session_id"))
        object.__setattr__(self, "state", PaperRuntimeState(self.state))
        object.__setattr__(self, "version", _require_int(self.version, "version"))
        object.__setattr__(self, "contract_hash", _require_str(self.contract_hash, "contract_hash"))
        object.__setattr__(self, "decision_json", _require_str(self.decision_json, "decision_json"))
        object.__setattr__(self, "decision_hash", _require_str(self.decision_hash, "decision_hash"))
        object.__setattr__(self, "evidence_hash", _require_str(self.evidence_hash, "evidence_hash"))
        object.__setattr__(self, "paper_limits_hash", _require_str(self.paper_limits_hash, "paper_limits_hash"))
        object.__setattr__(self, "strategy_version", _require_str(self.strategy_version, "strategy_version"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol"))
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "configuration_hash", _require_str(self.configuration_hash, "configuration_hash"))
        object.__setattr__(self, "paper_limits_json", _require_str(self.paper_limits_json, "paper_limits_json"))
        object.__setattr__(self, "configuration_json", _require_str(self.configuration_json, "configuration_json"))
        object.__setattr__(self, "execution_contract_json", _require_str(self.execution_contract_json, "execution_contract_json"))
        object.__setattr__(self, "execution_contract_hash", _require_str(self.execution_contract_hash, "execution_contract_hash"))
        object.__setattr__(self, "paper_only", _require_bool(self.paper_only, "paper_only"))
        object.__setattr__(self, "created_at_utc", _require_timezone_aware(self.created_at_utc, "created_at_utc"))
        object.__setattr__(self, "updated_at_utc", _require_timezone_aware(self.updated_at_utc, "updated_at_utc"))
        object.__setattr__(self, "session_started_utc", _require_timezone_aware(self.session_started_utc, "session_started_utc"))
        object.__setattr__(self, "active", _require_bool(self.active, "active"))


@dataclass(frozen=True, slots=True)
class PaperRuntimeEvent:
    event_id: str
    session_id: str
    sequence: int
    event_type: PaperRuntimeEventType
    timestamp_utc: datetime
    previous_hash: str
    content_hash: str
    decision_hash: str
    evidence_hash: str
    result: str
    payload: Mapping[str, Any]
    event_hash: str = field(default="")

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _require_str(self.event_id, "event_id"))
        object.__setattr__(self, "session_id", _require_str(self.session_id, "session_id"))
        object.__setattr__(self, "sequence", _require_int(self.sequence, "sequence"))
        object.__setattr__(self, "event_type", PaperRuntimeEventType(self.event_type))
        object.__setattr__(self, "timestamp_utc", _require_timezone_aware(self.timestamp_utc, "timestamp_utc"))
        object.__setattr__(self, "previous_hash", _require_str(self.previous_hash, "previous_hash", allow_empty=True))
        object.__setattr__(self, "content_hash", _require_str(self.content_hash, "content_hash"))
        object.__setattr__(self, "decision_hash", _require_str(self.decision_hash, "decision_hash"))
        object.__setattr__(self, "evidence_hash", _require_str(self.evidence_hash, "evidence_hash"))
        object.__setattr__(self, "result", _require_str(self.result, "result"))
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "event_hash", _require_str(self.event_hash or self._build_hash(), "event_hash"))

    def _build_hash(self) -> str:
        return sha256_hex(
            {
                "event_id": self.event_id,
                "session_id": self.session_id,
                "sequence": self.sequence,
                "event_type": self.event_type.value,
                "timestamp_utc": self.timestamp_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "previous_hash": self.previous_hash,
                "content_hash": self.content_hash,
                "decision_hash": self.decision_hash,
                "evidence_hash": self.evidence_hash,
                "result": self.result,
                "payload": self.payload,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "timestamp_utc": self.timestamp_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "previous_hash": self.previous_hash,
            "content_hash": self.content_hash,
            "decision_hash": self.decision_hash,
            "evidence_hash": self.evidence_hash,
            "result": self.result,
            "payload": serialize_value(self.payload),
            "event_hash": self.event_hash,
        }


def new_session_id() -> str:
    return str(uuid4())
