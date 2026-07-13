from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from domain.serialization import serialize_value
from .artifacts import promotion_hash
from .errors import PromotionDecisionError, PromotionPolicyError
from .models import PromotionDecision, PromotionStatus


def _strict_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise PromotionPolicyError(f"{field_name} must be an integer.")
    if allow_zero and value < 0:
        raise PromotionPolicyError(f"{field_name} cannot be negative.")
    if not allow_zero and value <= 0:
        raise PromotionPolicyError(f"{field_name} must be greater than zero.")
    return int(value)


def _to_decimal(value: Any, field_name: str, *, allow_zero: bool = True) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    else:
        try:
            result = Decimal(str(value))
        except Exception as exc:
            raise PromotionPolicyError(f"{field_name} must be numeric.") from exc
    if not result.is_finite():
        raise PromotionPolicyError(f"{field_name} must be finite.")
    if allow_zero:
        if result < 0:
            raise PromotionPolicyError(f"{field_name} cannot be negative.")
    elif result <= 0:
        raise PromotionPolicyError(f"{field_name} must be greater than zero.")
    return result


def _require_timezone_aware(dt: datetime, field_name: str) -> datetime:
    if not isinstance(dt, datetime):
        raise PromotionPolicyError(f"{field_name} must be a datetime.")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise PromotionPolicyError(f"{field_name} must be timezone-aware.")
    return dt.astimezone(timezone.utc)


def _require_session_id(value: Any, field_name: str = "session_id") -> str:
    if type(value) is not str:
        raise PromotionPolicyError(f"{field_name} must be a string.")
    session_id = value.strip()
    if not session_id:
        raise PromotionPolicyError(f"{field_name} must be a non-empty string.")
    return session_id


def _require_bool_strict(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise PromotionPolicyError(f"{field_name} must be a boolean.")
    return value


@dataclass(frozen=True, slots=True)
class MonitoredPaperLimits:
    paper_capital_max: Decimal = Decimal("10000")
    risk_per_trade_max_percent: Decimal = Decimal("1")
    max_positions: int = 1
    session_drawdown_max_percent: Decimal = Decimal("10")
    max_loss_streak: int = 3
    max_duration_hours: int = 8
    min_trades: int = 1
    max_trades: int = 100
    expired_data_policy: str = "BLOCK_AND_SUSPEND"
    suspension_policy: str = "AUTO_SUSPEND"
    kill_switch_required: bool = True
    live_trading_permanently_disabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "paper_capital_max", _to_decimal(self.paper_capital_max, "paper_capital_max"))
        object.__setattr__(self, "risk_per_trade_max_percent", _to_decimal(self.risk_per_trade_max_percent, "risk_per_trade_max_percent"))
        object.__setattr__(self, "max_positions", _strict_int(self.max_positions, "max_positions"))
        object.__setattr__(self, "session_drawdown_max_percent", _to_decimal(self.session_drawdown_max_percent, "session_drawdown_max_percent"))
        object.__setattr__(self, "max_loss_streak", _strict_int(self.max_loss_streak, "max_loss_streak"))
        object.__setattr__(self, "max_duration_hours", _strict_int(self.max_duration_hours, "max_duration_hours"))
        object.__setattr__(self, "min_trades", _strict_int(self.min_trades, "min_trades"))
        object.__setattr__(self, "max_trades", _strict_int(self.max_trades, "max_trades"))
        object.__setattr__(self, "expired_data_policy", str(self.expired_data_policy).strip().upper())
        object.__setattr__(self, "suspension_policy", str(self.suspension_policy).strip().upper())
        if self.kill_switch_required is not True:
            raise PromotionPolicyError("kill_switch_required must be True.")
        if self.live_trading_permanently_disabled is not True:
            raise PromotionPolicyError("live_trading_permanently_disabled must be True.")
        if self.max_trades < self.min_trades:
            raise PromotionPolicyError("max_trades must be greater than or equal to min_trades.")
        if self.expired_data_policy not in {"BLOCK", "SUSPEND", "BLOCK_AND_SUSPEND"}:
            raise PromotionPolicyError("expired_data_policy is invalid.")
        if self.suspension_policy not in {"AUTO_SUSPEND", "BLOCK_ONLY", "SUSPEND"}:
            raise PromotionPolicyError("suspension_policy is invalid.")

    @property
    def live_trading_allowed(self) -> bool:
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "paper_capital_max": self.paper_capital_max,
            "risk_per_trade_max_percent": self.risk_per_trade_max_percent,
            "max_positions": self.max_positions,
            "session_drawdown_max_percent": self.session_drawdown_max_percent,
            "max_loss_streak": self.max_loss_streak,
            "max_duration_hours": self.max_duration_hours,
            "min_trades": self.min_trades,
            "max_trades": self.max_trades,
            "expired_data_policy": self.expired_data_policy,
            "suspension_policy": self.suspension_policy,
            "kill_switch_required": self.kill_switch_required,
            "live_trading_permanently_disabled": self.live_trading_permanently_disabled,
        }


@dataclass(frozen=True, slots=True)
class PaperMonitoringSnapshot:
    timestamp_utc: datetime
    decision_hash: str
    evidence_hash: str
    strategy_version: str
    configuration: dict[str, Any]
    trading_mode: str
    session_id: str
    session_started_utc: datetime
    data_fresh: bool
    session_drawdown_percent: Decimal
    current_loss_streak: int
    open_positions: int
    executed_trades: int
    observed_costs: dict[str, Any]
    session_state: str = "RUNNING"
    paper_capital_used: Decimal = Decimal("0")
    risk_per_trade_percent: Decimal = Decimal("0")
    internal_error: str | None = None
    attempted_live: bool = False
    snapshot_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp_utc", _require_timezone_aware(self.timestamp_utc, "timestamp_utc"))
        object.__setattr__(self, "session_id", _require_session_id(self.session_id))
        object.__setattr__(self, "session_started_utc", _require_timezone_aware(self.session_started_utc, "session_started_utc"))
        if self.session_started_utc > self.timestamp_utc:
            raise PromotionPolicyError("session_started_utc cannot be after timestamp_utc.")
        object.__setattr__(self, "session_state", str(self.session_state).strip().upper())
        if self.session_state not in {"RUNNING", "COMPLETED"}:
            raise PromotionPolicyError("session_state is invalid.")
        object.__setattr__(self, "data_fresh", _require_bool_strict(self.data_fresh, "data_fresh"))
        object.__setattr__(self, "session_drawdown_percent", _to_decimal(self.session_drawdown_percent, "session_drawdown_percent"))
        object.__setattr__(self, "paper_capital_used", _to_decimal(self.paper_capital_used, "paper_capital_used"))
        object.__setattr__(self, "risk_per_trade_percent", _to_decimal(self.risk_per_trade_percent, "risk_per_trade_percent"))
        object.__setattr__(self, "decision_hash", str(self.decision_hash).strip())
        object.__setattr__(self, "evidence_hash", str(self.evidence_hash).strip())
        object.__setattr__(self, "strategy_version", str(self.strategy_version).strip())
        object.__setattr__(self, "trading_mode", str(self.trading_mode).strip().upper())
        object.__setattr__(self, "configuration", dict(self.configuration))
        object.__setattr__(self, "observed_costs", dict(self.observed_costs))
        object.__setattr__(self, "current_loss_streak", _strict_int(self.current_loss_streak, "current_loss_streak", allow_zero=True))
        object.__setattr__(self, "open_positions", _strict_int(self.open_positions, "open_positions", allow_zero=True))
        object.__setattr__(self, "executed_trades", _strict_int(self.executed_trades, "executed_trades", allow_zero=True))
        object.__setattr__(self, "attempted_live", _require_bool_strict(self.attempted_live, "attempted_live"))
        object.__setattr__(self, "snapshot_hash", promotion_hash(self.as_hash_payload()))

    def as_hash_payload(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "decision_hash": self.decision_hash,
            "evidence_hash": self.evidence_hash,
            "strategy_version": self.strategy_version,
            "configuration": self.configuration,
            "trading_mode": self.trading_mode,
            "session_id": self.session_id,
            "session_state": self.session_state,
            "session_started_utc": self.session_started_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "data_fresh": self.data_fresh,
            "paper_capital_used": self.paper_capital_used,
            "risk_per_trade_percent": self.risk_per_trade_percent,
            "session_drawdown_percent": self.session_drawdown_percent,
            "current_loss_streak": self.current_loss_streak,
            "open_positions": self.open_positions,
            "executed_trades": self.executed_trades,
            "observed_costs": self.observed_costs,
            "internal_error": self.internal_error,
            "attempted_live": self.attempted_live,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "decision_hash": self.decision_hash,
            "evidence_hash": self.evidence_hash,
            "strategy_version": self.strategy_version,
            "configuration": serialize_value(self.configuration),
            "trading_mode": self.trading_mode,
            "session_id": self.session_id,
            "session_state": self.session_state,
            "session_started_utc": self.session_started_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "data_fresh": self.data_fresh,
            "paper_capital_used": self.paper_capital_used,
            "risk_per_trade_percent": self.risk_per_trade_percent,
            "session_drawdown_percent": self.session_drawdown_percent,
            "current_loss_streak": self.current_loss_streak,
            "open_positions": self.open_positions,
            "executed_trades": self.executed_trades,
            "observed_costs": serialize_value(self.observed_costs),
            "internal_error": self.internal_error,
            "attempted_live": self.attempted_live,
            "snapshot_hash": self.snapshot_hash,
        }


@dataclass(frozen=True, slots=True)
class PaperMonitoringSessionContract:
    session_id: str
    session_started_utc: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _require_session_id(self.session_id))
        object.__setattr__(self, "session_started_utc", _require_timezone_aware(self.session_started_utc, "session_started_utc"))

    def as_hash_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_started_utc": self.session_started_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    def as_dict(self) -> dict[str, Any]:
        return dict(self.as_hash_payload(), contract_hash=promotion_hash(self.as_hash_payload()))


@dataclass(frozen=True, slots=True)
class PaperMonitoringDecision:
    status: PromotionStatus
    decision_hash: str
    evidence_hash: str
    snapshot_hash: str
    paper_limits: dict[str, Any]
    reasons: tuple[str, ...]
    timestamp_utc: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", PromotionStatus(self.status))
        object.__setattr__(self, "decision_hash", str(self.decision_hash).strip())
        object.__setattr__(self, "evidence_hash", str(self.evidence_hash).strip())
        object.__setattr__(self, "snapshot_hash", str(self.snapshot_hash).strip())
        object.__setattr__(self, "paper_limits", dict(self.paper_limits))
        object.__setattr__(self, "reasons", tuple(str(reason) for reason in self.reasons))
        object.__setattr__(self, "timestamp_utc", self.timestamp_utc.astimezone(timezone.utc))
        if not self.decision_hash or not self.evidence_hash or not self.snapshot_hash:
            raise PromotionDecisionError("monitoring hashes are required.")
        if self.status == PromotionStatus.APPROVED_FOR_MONITORED_PAPER:
            if self.paper_limits.get("kill_switch_required") is not True:
                raise PromotionDecisionError("monitoring approval requires kill_switch_required.")
            if self.paper_limits.get("live_trading_permanently_disabled") is not True:
                raise PromotionDecisionError("monitoring approval requires live trading permanently disabled.")


def _monitoring_snapshot_hash(snapshot: PaperMonitoringSnapshot) -> str:
    return promotion_hash(snapshot.as_hash_payload())


def _suspend(reason: str, decision: PromotionDecision, snapshot: PaperMonitoringSnapshot, limits: MonitoredPaperLimits) -> PaperMonitoringDecision:
    return PaperMonitoringDecision(
        status=PromotionStatus.PAPER_SUSPENDED,
        decision_hash=decision.decision_hash,
        evidence_hash=decision.evidence_hash,
        snapshot_hash=_monitoring_snapshot_hash(snapshot),
        paper_limits=limits.as_dict(),
        reasons=(reason,),
        timestamp_utc=datetime.now(timezone.utc),
    )


def _coerce_limits(decision: PromotionDecision, limits: MonitoredPaperLimits | None) -> MonitoredPaperLimits:
    decision_limits = MonitoredPaperLimits(**decision.paper_limits)
    if limits is None:
        return decision_limits
    if limits.as_dict() != decision_limits.as_dict():
        raise PromotionDecisionError("provided limits must match the frozen decision limits exactly.")
    return decision_limits


def _coerce_session_contract(
    snapshot: PaperMonitoringSnapshot,
    session_contract: PaperMonitoringSessionContract | None,
) -> PaperMonitoringSessionContract:
    if session_contract is None:
        raise PromotionDecisionError("paper monitoring session contract is required.")
    if not isinstance(session_contract, PaperMonitoringSessionContract):
        raise PromotionDecisionError("paper monitoring session contract is required.")
    if session_contract.session_id != snapshot.session_id or session_contract.session_started_utc != snapshot.session_started_utc:
        raise PromotionDecisionError("session contract divergence.")
    return session_contract


def _validate_observed_costs(decision: PromotionDecision, snapshot: PaperMonitoringSnapshot) -> str | None:
    required_keys = {"entry_fee_rate", "exit_fee_rate", "spread_bps", "slippage_bps"}
    observed_keys = set(snapshot.observed_costs)
    if observed_keys != required_keys:
        missing = sorted(required_keys - observed_keys)
        unknown = sorted(observed_keys - required_keys)
        if missing:
            return f"missing observed cost keys: {', '.join(missing)}"
        if unknown:
            return f"unknown observed cost keys: {', '.join(unknown)}"
    contract = decision.phase5_manifest.get("execution_contract", {})
    for key in required_keys:
        expected = contract.get(key)
        if expected is None:
            return f"frozen cost contract missing key: {key}"
        observed = snapshot.observed_costs.get(key)
        try:
            observed_decimal = Decimal(str(observed))
            expected_decimal = Decimal(str(expected))
        except Exception as exc:
            return f"invalid observed cost value for {key}"
        if not observed_decimal.is_finite() or not expected_decimal.is_finite():
            return f"cost values must be finite: {key}"
        if observed_decimal < 0 or expected_decimal < 0:
            return f"cost values cannot be negative: {key}"
        if observed_decimal > expected_decimal:
            return f"observed cost above frozen contract: {key}"
    return None


def _validate_session_limits(snapshot: PaperMonitoringSnapshot, limits: MonitoredPaperLimits) -> str | None:
    if snapshot.paper_capital_used > limits.paper_capital_max:
        return "paper capital limit exceeded."
    if snapshot.risk_per_trade_percent > limits.risk_per_trade_max_percent:
        return "risk per trade limit exceeded."
    if snapshot.session_drawdown_percent > limits.session_drawdown_max_percent:
        return "session drawdown exceeded."
    if snapshot.current_loss_streak > limits.max_loss_streak:
        return "loss streak exceeded."
    if snapshot.open_positions > limits.max_positions:
        return "open positions exceeded."
    if snapshot.executed_trades > limits.max_trades:
        return "trade count above maximum."
    duration_hours = (snapshot.timestamp_utc - snapshot.session_started_utc).total_seconds() / 3600.0
    if duration_hours < 0:
        raise PromotionDecisionError("session duration cannot be negative.")
    if duration_hours > limits.max_duration_hours:
        return "session duration exceeded."
    if not snapshot.data_fresh and limits.expired_data_policy in {"BLOCK", "SUSPEND", "BLOCK_AND_SUSPEND"}:
        return "data are stale or expired."
    if snapshot.session_state == "COMPLETED" and snapshot.executed_trades < limits.min_trades:
        return "completed sessions must satisfy min_trades."
    if snapshot.session_state == "RUNNING":
        return None
    if snapshot.session_state != "COMPLETED":
        raise PromotionDecisionError("unknown session state.")
    return None


def evaluate_paper_monitoring(
    decision: PromotionDecision,
    snapshot: PaperMonitoringSnapshot,
    limits: MonitoredPaperLimits | None = None,
    session_contract: PaperMonitoringSessionContract | None = None,
) -> PaperMonitoringDecision:
    if not isinstance(decision, PromotionDecision):
        raise PromotionDecisionError("promotion decision is required.")
    if decision.status is not PromotionStatus.APPROVED_FOR_MONITORED_PAPER:
        raise PromotionDecisionError("only approved monitored paper decisions can be monitored.")
    if not isinstance(snapshot, PaperMonitoringSnapshot):
        raise PromotionDecisionError("paper monitoring snapshot is required.")
    if decision.paper_limits_hash != promotion_hash(decision.paper_limits):
        raise PromotionDecisionError("decision paper limits hash mismatch.")
    limits = _coerce_limits(decision, limits)
    session_contract = _coerce_session_contract(snapshot, session_contract)
    if snapshot.snapshot_hash != _monitoring_snapshot_hash(snapshot):
        raise PromotionDecisionError("snapshot hash mismatch.")
    if snapshot.decision_hash != decision.decision_hash or snapshot.evidence_hash != decision.evidence_hash:
        raise PromotionDecisionError("hash divergence.")
    expected_configuration = decision.frozen_selection.as_dict()
    if serialize_value(snapshot.configuration) != serialize_value(expected_configuration):
        raise PromotionDecisionError("configuration divergence.")
    if snapshot.strategy_version != decision.strategy_version or snapshot.trading_mode != "PAPER":
        raise PromotionDecisionError("strategy or mode divergence.")
    if snapshot.internal_error:
        return _suspend("internal error", decision, snapshot, limits)
    if snapshot.attempted_live:
        return _suspend("live trading attempt", decision, snapshot, limits)
    reason = _validate_observed_costs(decision, snapshot)
    if reason is not None:
        return _suspend(reason, decision, snapshot, limits)
    reason = _validate_session_limits(snapshot, limits)
    if reason is not None:
        return _suspend(reason, decision, snapshot, limits)
    return PaperMonitoringDecision(
        status=PromotionStatus.APPROVED_FOR_MONITORED_PAPER,
        decision_hash=decision.decision_hash,
        evidence_hash=decision.evidence_hash,
        snapshot_hash=snapshot.snapshot_hash,
        paper_limits=limits.as_dict(),
        reasons=(),
        timestamp_utc=datetime.now(timezone.utc),
    )
