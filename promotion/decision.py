from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .artifacts import promotion_hash
from .evidence import PromotionEvidence, validate_promotion_evidence
from .errors import PromotionDecisionError
from .models import PromotionCriterionResult, PromotionDecision, PromotionStatus
from .monitoring import MonitoredPaperLimits
from .policy import PromotionPolicy


def _as_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _criteria_name(name: str) -> str:
    return str(name).strip()


def _criterion(name: str, passed: bool, expected: Any, actual: Any, reason: str) -> PromotionCriterionResult:
    return PromotionCriterionResult(name=name, passed=passed, expected=expected, actual=actual, reason=reason)


def _policy_hash(policy: PromotionPolicy, monitoring: MonitoredPaperLimits) -> str:
    return promotion_hash({"policy": policy.as_dict(), "monitoring": monitoring.as_dict()})


def _decision_hash(
    *,
    status: PromotionStatus,
    evidence_hash: str,
    policy_hash: str,
    criteria_evaluated: tuple[PromotionCriterionResult, ...],
    reasons: tuple[str, ...],
    recalculated_metrics: dict[str, Any],
    paper_limits: dict[str, Any],
    frozen_selection: dict[str, Any],
    strategy_version: str,
    symbol: str,
    interval: str,
    ) -> str:
    return promotion_hash(
        {
            "status": status.value,
            "evidence_hash": evidence_hash,
            "policy_hash": policy_hash,
            "criteria_evaluated": [criterion.as_dict() for criterion in criteria_evaluated],
            "reasons": list(reasons),
            "recalculated_metrics": recalculated_metrics,
            "paper_limits": paper_limits,
            "frozen_selection": frozen_selection,
            "strategy_version": strategy_version,
            "symbol": symbol,
            "interval": interval,
        }
    )


def _classify_status(criteria: tuple[PromotionCriterionResult, ...]) -> PromotionStatus:
    failed = [criterion.name for criterion in criteria if not criterion.passed]
    if not failed:
        return PromotionStatus.APPROVED_FOR_MONITORED_PAPER
    if any(name in {"min_oos_windows", "min_oos_trades"} for name in failed):
        return PromotionStatus.INSUFFICIENT_EVIDENCE
    if any(name in {"max_drawdown"} for name in failed) or any(name.startswith("cost_") for name in failed):
        return PromotionStatus.PAPER_SUSPENDED
    if any(name in {"runner_trusted", "paper_only", "engine_class", "manifest_complete", "manifest_hash", "window_count", "single_candidate"} for name in failed):
        return PromotionStatus.REJECTED
    return PromotionStatus.REJECTED


def _monitoring_limits(policy: PromotionPolicy) -> MonitoredPaperLimits:
    return MonitoredPaperLimits(
        paper_capital_max=Decimal("10000"),
        risk_per_trade_max_percent=Decimal("1"),
        max_positions=1,
        session_drawdown_max_percent=policy.max_oos_drawdown_percent,
        max_loss_streak=3,
        max_duration_hours=8,
        min_trades=policy.min_oos_windows,
        max_trades=max(policy.min_oos_trades, 100),
        expired_data_policy="BLOCK_AND_SUSPEND",
        suspension_policy="AUTO_SUSPEND",
        kill_switch_required=True,
        live_trading_permanently_disabled=True,
    )


def evaluate_promotion(evidence: PromotionEvidence, policy: PromotionPolicy | None = None, monitoring: MonitoredPaperLimits | None = None) -> PromotionDecision:
    policy = policy or PromotionPolicy()
    monitoring = monitoring or _monitoring_limits(policy)
    reasons: list[str] = []
    criteria: list[PromotionCriterionResult] = []
    try:
        validate_promotion_evidence(evidence)
    except Exception as exc:
        reasons.append(str(exc))
        policy_hash_value = _policy_hash(policy, monitoring)
        return PromotionDecision(
            status=PromotionStatus.REJECTED,
            frozen_selection=evidence.windows[0].frozen_selection if evidence.windows else raise_missing_selection(),
            strategy_version=evidence.strategy_version,
            symbol=evidence.symbol,
            interval=evidence.interval,
            phase5_manifest=evidence.manifest,
            evidence_hash=evidence.evidence_hash,
            policy_hash=policy_hash_value,
            decision_hash=promotion_hash({"rejected": reasons, "evidence_hash": evidence.evidence_hash, "policy_hash": policy_hash_value}),
            criteria_evaluated=tuple(criteria),
            reasons=tuple(reasons),
            recalculated_metrics=evidence.recalculated_metrics,
            paper_limits=monitoring.as_dict(),
            timestamp_utc=datetime.now(timezone.utc),
        )

    recalculated = evidence.recalculated_metrics
    summary = evidence.summary
    window_metrics = [window.test_metrics for window in evidence.windows]
    profitable_windows = sum(1 for metrics in window_metrics if _as_decimal(metrics.get("net_return_percent", 0)) > 0)
    total_windows = len(window_metrics)
    total_trades = int(_as_decimal(recalculated.get("total_trades", 0)))
    net_return = _as_decimal(recalculated.get("net_return_percent", 0))
    expectancy = _as_decimal(recalculated.get("expectancy", 0))
    profit_factor = recalculated.get("profit_factor")
    drawdown = _as_decimal(recalculated.get("drawdown_max_percent", 0))
    degradation = _as_decimal(recalculated.get("degradation_validation_test", 0))
    selected_candidate_names = {window.selected_candidate.get("name") for window in evidence.windows}
    single_candidate = len(selected_candidate_names) == 1

    criteria.append(_criterion("runner_trusted", evidence.runner_trusted is True, True, evidence.runner_trusted, "runner_trusted must be true"))
    criteria.append(_criterion("paper_only", evidence.paper_only is True, True, evidence.paper_only, "paper_only must be true"))
    criteria.append(_criterion("engine_class", evidence.engine_class == "LeakFreeBacktestEngine", "LeakFreeBacktestEngine", evidence.engine_class, "engine_class must be LeakFreeBacktestEngine"))
    criteria.append(_criterion("manifest_complete", bool(evidence.manifest.get("windows")) and bool(evidence.manifest.get("window_signatures")), True, True, "manifest must include windows and signatures"))
    criteria.append(_criterion("single_candidate", single_candidate, True, single_candidate, "all windows must resolve to the same candidate"))
    criteria.append(_criterion("min_oos_windows", total_windows >= policy.min_oos_windows, policy.min_oos_windows, total_windows, "insufficient OOS windows"))
    criteria.append(_criterion("min_oos_trades", total_trades >= policy.min_oos_trades, policy.min_oos_trades, total_trades, "insufficient OOS trades"))
    criteria.append(_criterion("positive_net_return", net_return > policy.min_oos_net_return_percent, policy.min_oos_net_return_percent, net_return, "net return must be positive"))
    criteria.append(_criterion("positive_expectancy", expectancy > policy.min_oos_expectancy, policy.min_oos_expectancy, expectancy, "expectancy must be positive"))
    criteria.append(_criterion("profit_factor_defined", profit_factor is not None, "defined", profit_factor, "profit factor must be defined"))
    criteria.append(_criterion("profit_factor_min", profit_factor is not None and _as_decimal(profit_factor) >= policy.min_oos_profit_factor, policy.min_oos_profit_factor, profit_factor, "profit factor below minimum"))
    criteria.append(_criterion("max_drawdown", drawdown <= policy.max_oos_drawdown_percent, policy.max_oos_drawdown_percent, drawdown, "drawdown above maximum"))
    criteria.append(_criterion("profitable_window_ratio", total_windows > 0 and (Decimal(profitable_windows) / Decimal(total_windows) * Decimal("100")) >= policy.min_profitable_window_ratio_percent, policy.min_profitable_window_ratio_percent, profitable_windows if total_windows == 0 else float(Decimal(profitable_windows) / Decimal(total_windows) * Decimal("100")), "too few profitable windows"))
    criteria.append(_criterion("degradation_limit", degradation <= policy.max_validation_degradation_percent, policy.max_validation_degradation_percent, degradation, "validation->test degradation above maximum"))

    if policy.require_complete_manifest:
        criteria.append(_criterion("manifest_hash", evidence.manifest_hash == evidence.manifest.get("manifest_hash"), evidence.manifest.get("manifest_hash"), evidence.manifest_hash, "manifest hash mismatch"))
        criteria.append(_criterion("window_count", evidence.window_count_expected == evidence.window_count_received, evidence.window_count_expected, evidence.window_count_received, "window count mismatch"))
    if policy.require_nonzero_costs:
        costs = evidence.execution_contract
        cost_keys = ("entry_fee_rate", "exit_fee_rate", "spread_bps", "slippage_bps")
        for key in cost_keys:
            value = _as_decimal(costs.get(key, 0))
            criteria.append(_criterion(f"cost_{key}", value > 0, ">0", value, f"{key} must be positive"))
    else:
        costs = evidence.execution_contract
        for key in ("entry_fee_rate", "exit_fee_rate", "spread_bps", "slippage_bps"):
            value = _as_decimal(costs.get(key, 0))
            criteria.append(_criterion(f"cost_{key}", value >= 0, ">=0", value, f"{key} must be non-negative"))

    if any(not criterion.passed for criterion in criteria):
        for criterion in criteria:
            if not criterion.passed:
                reasons.append(f"{criterion.name}: {criterion.reason}")
    status = _classify_status(tuple(criteria))

    policy_hash_value = _policy_hash(policy, monitoring)
    decision_hash_value = _decision_hash(
        status=status,
        evidence_hash=evidence.evidence_hash,
        policy_hash=policy_hash_value,
        criteria_evaluated=tuple(criteria),
        reasons=tuple(reasons),
        recalculated_metrics=recalculated,
        paper_limits=monitoring.as_dict(),
        frozen_selection=evidence.windows[0].frozen_selection,
        strategy_version=evidence.strategy_version,
        symbol=evidence.symbol,
        interval=evidence.interval,
    )
    return PromotionDecision(
        status=status,
        frozen_selection=evidence.windows[0].frozen_selection,
        strategy_version=evidence.strategy_version,
        symbol=evidence.symbol,
        interval=evidence.interval,
        phase5_manifest=evidence.manifest,
        evidence_hash=evidence.evidence_hash,
        policy_hash=policy_hash_value,
        decision_hash=decision_hash_value,
        criteria_evaluated=tuple(criteria),
        reasons=tuple(reasons),
        recalculated_metrics=recalculated,
        paper_limits=monitoring.as_dict(),
        timestamp_utc=datetime.now(timezone.utc),
    )


def raise_missing_selection():
    raise PromotionDecisionError("promotion evidence must contain at least one approved window.")
