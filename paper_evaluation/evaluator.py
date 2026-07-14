from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from validation import WalkForwardResult, aggregate_run_statistics

from .artifacts import paper_evaluation_hash
from .errors import PaperEvaluationDecisionError
from .metrics import aggregate_paper_session_metrics, compute_paper_session_metrics
from .models import (
    PaperEvaluationDecision,
    PaperEvaluationManifest,
    PaperEvaluationPolicy,
    PaperEvaluationReport,
    PaperEvaluationStatus,
    PaperSessionEvidence,
    PaperSessionMetrics,
    PaperSessionRejection,
)
from .policy import default_paper_evaluation_policy


def _ensure_policy(policy: PaperEvaluationPolicy | None) -> PaperEvaluationPolicy:
    return policy or default_paper_evaluation_policy()


def _ensure_walk_forward_reference(reference: WalkForwardResult | None) -> tuple[dict[str, Any], str | None]:
    if reference is None:
        return {}, None
    if not isinstance(reference, WalkForwardResult):
        raise PaperEvaluationDecisionError("walk-forward reference must be a trusted WalkForwardResult.")
    payload = reference.as_dict()
    manifest = payload.get("manifest")
    summary = payload.get("summary")
    windows = payload.get("windows")
    if not isinstance(manifest, Mapping) or not isinstance(summary, Mapping) or not isinstance(windows, Sequence):
        raise PaperEvaluationDecisionError("walk-forward reference payload is invalid.")
    if manifest.get("runner_trusted") is not True or summary.get("runner_trusted") is not True:
        raise PaperEvaluationDecisionError("walk-forward reference must be runner_trusted.")
    if summary.get("manifest_hash") != manifest.get("manifest_hash"):
        raise PaperEvaluationDecisionError("walk-forward summary hash mismatch.")
    manifest_payload = dict(manifest)
    manifest_hash_value = manifest_payload.pop("manifest_hash", None)
    if not manifest_hash_value or paper_evaluation_hash(manifest_payload) != manifest_hash_value:
        raise PaperEvaluationDecisionError("walk-forward manifest hash mismatch.")
    for window in windows:
        if not isinstance(window, Mapping):
            raise PaperEvaluationDecisionError("walk-forward window payload is invalid.")
        if window.get("approved") is True:
            frozen_selection = window.get("frozen_selection")
            selected_candidate = window.get("selected_candidate")
            if not isinstance(frozen_selection, Mapping) or not isinstance(selected_candidate, Mapping):
                raise PaperEvaluationDecisionError("trusted walk-forward windows require frozen selections.")
            if frozen_selection.get("candidate") != selected_candidate:
                raise PaperEvaluationDecisionError("walk-forward candidate mismatch.")
            if frozen_selection.get("manifest_hash") != window.get("manifest_hash"):
                raise PaperEvaluationDecisionError("walk-forward window hash mismatch.")
    return payload, paper_evaluation_hash(payload)


def _compare_against_walk_forward(actual: PaperSessionMetrics, reference: dict[str, Any]) -> dict[str, Any]:
    if not reference:
        return {}
    summary = reference.get("summary") if isinstance(reference.get("summary"), Mapping) else reference
    comparison = {
        "reference_net_return_percent": summary.get("net_return_percent"),
        "reference_drawdown_max_percent": summary.get("drawdown_max_percent"),
        "reference_expectancy": summary.get("expectancy"),
        "reference_profit_factor": summary.get("profit_factor"),
        "reference_total_trades": summary.get("total_trades"),
        "actual_net_return_percent": actual.net_return_percent,
        "actual_drawdown_max_percent": actual.drawdown_max_percent,
        "actual_expectancy": actual.expectancy,
        "actual_profit_factor": actual.profit_factor,
        "actual_total_trades": actual.total_trades,
    }
    if comparison["reference_net_return_percent"] is not None:
        comparison["delta_net_return_percent"] = Decimal(str(actual.net_return_percent)) - Decimal(str(comparison["reference_net_return_percent"]))
    if comparison["reference_drawdown_max_percent"] is not None:
        comparison["delta_drawdown_max_percent"] = Decimal(str(actual.drawdown_max_percent)) - Decimal(str(comparison["reference_drawdown_max_percent"]))
    if comparison["reference_expectancy"] is not None:
        comparison["delta_expectancy"] = Decimal(str(actual.expectancy)) - Decimal(str(comparison["reference_expectancy"]))
    if comparison["reference_profit_factor"] is not None and actual.profit_factor is not None:
        comparison["delta_profit_factor"] = Decimal(str(actual.profit_factor)) - Decimal(str(comparison["reference_profit_factor"]))
    if comparison["reference_total_trades"] is not None:
        comparison["delta_total_trades"] = int(actual.total_trades) - int(comparison["reference_total_trades"])
    return comparison


def _session_is_completed(evidence: PaperSessionEvidence) -> bool:
    return evidence.session_state == "COMPLETED"


def _collect_reasons(
    policy: PaperEvaluationPolicy,
    aggregate_metrics: PaperSessionMetrics,
    evidence: Sequence[PaperSessionEvidence],
) -> list[str]:
    reasons: list[str] = []
    if not evidence:
        reasons.append("no paper sessions found.")
        return reasons
    if len(evidence) < policy.min_sessions_completed:
        reasons.append("insufficient completed sessions.")
    distinct_days = {
        snapshot.timestamp_utc.astimezone(timezone.utc).date()
        for session in evidence
        for snapshot in session.snapshots
    }
    if len(distinct_days) < policy.min_distinct_days:
        reasons.append("insufficient distinct trading days.")
    if aggregate_metrics.total_trades < policy.min_trades:
        reasons.append("insufficient trades.")
    if aggregate_metrics.duration_hours < policy.min_duration_hours:
        reasons.append("insufficient session duration.")
    if aggregate_metrics.drawdown_max_percent > policy.max_drawdown_percent:
        reasons.append("drawdown above maximum.")
    if policy.min_profit_factor is not None:
        if aggregate_metrics.profit_factor is None:
            if policy.min_profit_factor > 0:
                reasons.append("profit factor below minimum.")
        elif aggregate_metrics.profit_factor < policy.min_profit_factor:
            reasons.append("profit factor below minimum.")
    if aggregate_metrics.expectancy < policy.min_expectancy:
        reasons.append("expectancy below minimum.")
    if aggregate_metrics.net_return_percent < policy.min_net_return_percent:
        reasons.append("net return below minimum.")
    total_cost_percent = (
        aggregate_metrics.total_costs / aggregate_metrics.capital_initial * Decimal("100")
        if aggregate_metrics.capital_initial > 0
        else Decimal("0")
    )
    if policy.max_total_costs_percent >= 0 and total_cost_percent > policy.max_total_costs_percent:
        reasons.append("costs above maximum.")
    suspended_sessions = sum(1 for session in evidence if session.session_state == "SUSPENDED")
    if suspended_sessions > policy.max_suspended_sessions:
        reasons.append("suspended sessions above maximum.")
    if policy.require_zero_live_attempts and any(session.attempted_live_count > 0 for session in evidence):
        reasons.append("live attempts are not allowed.")
    if policy.require_audit_chain and any(not session.audit_chain_valid for session in evidence):
        reasons.append("audit chain invalid.")
    if policy.require_fresh_data and any(session.expired_data_cycles > 0 for session in evidence):
        reasons.append("stale data detected.")
    coverage = {regime for session in evidence for regime in session.regime_coverage}
    if policy.min_regime_coverage and len(coverage) < policy.min_regime_coverage:
        reasons.append("insufficient regime coverage.")
    if policy.required_regimes and not set(policy.required_regimes).issubset(coverage):
        reasons.append("missing required market regimes.")
    return reasons


def _status_from_reasons(reasons: Sequence[str], *, evidence: Sequence[PaperSessionEvidence]) -> PaperEvaluationStatus:
    if not evidence or any("no paper sessions found" in reason for reason in reasons):
        return PaperEvaluationStatus.INSUFFICIENT_EVIDENCE
    if any(
        token in reason
        for reason in reasons
        for token in (
            "audit chain invalid",
            "live attempts are not allowed",
            "stale data detected",
            "session state is invalid",
        )
    ):
        return PaperEvaluationStatus.REJECTED
    if any(session.session_state in {"SUSPENDED", "FAILED"} for session in evidence):
        return PaperEvaluationStatus.REJECTED
    if reasons:
        return PaperEvaluationStatus.INSUFFICIENT_EVIDENCE if any("insufficient" in reason for reason in reasons) else PaperEvaluationStatus.REJECTED
    return PaperEvaluationStatus.APPROVED_FOR_EXTENDED_PAPER


def evaluate_paper_sessions(
    evidences: Sequence[PaperSessionEvidence],
    *,
    policy: PaperEvaluationPolicy | None = None,
    reference_walk_forward: WalkForwardResult | None = None,
    evaluation_id: str | None = None,
    inclusion_rule: str = "explicit_session_ids",
    synthetic_test_data: bool = False,
    operational_evidence: bool = False,
    expected_session_ids: Sequence[str] | None = None,
    load_rejections: Sequence[PaperSessionRejection] | None = None,
) -> PaperEvaluationReport:
    policy = _ensure_policy(policy)
    reference_payload, reference_hash = _ensure_walk_forward_reference(reference_walk_forward)
    ordered_evidence = tuple(sorted(evidences, key=lambda item: (item.session_started_utc, item.session_id)))
    if len({item.session_id for item in ordered_evidence}) != len(ordered_evidence):
        raise PaperEvaluationDecisionError("duplicate session_id detected.")
    if expected_session_ids is not None:
        expected_ids = tuple(str(session_id).strip() for session_id in expected_session_ids if str(session_id).strip())
        loaded_ids = tuple(sorted(session.session_id for session in ordered_evidence))
        rejected_ids = {rejection.session_id for rejection in (load_rejections or ())}
        seen_ids = set(loaded_ids) | rejected_ids
        if not expected_ids or seen_ids != set(expected_ids):
            raise PaperEvaluationDecisionError("expected session ids diverge from loaded evidence.")
    accepted = tuple(session for session in ordered_evidence if _session_is_completed(session))
    rejected = tuple(load_rejections or ()) + tuple(PaperSessionRejection(session_id=session.session_id, reason=f"session state {session.session_state} not eligible") for session in ordered_evidence if not _session_is_completed(session))
    session_metrics = tuple(compute_paper_session_metrics(session) for session in ordered_evidence)
    accepted_metrics = tuple(compute_paper_session_metrics(session) for session in accepted)
    if accepted_metrics:
        aggregate_metrics = aggregate_paper_session_metrics(accepted_metrics)
    else:
        aggregate_metrics = PaperSessionMetrics(
            session_id="EMPTY",
            capital_initial=Decimal("0"),
            capital_final=Decimal("0"),
            gross_pnl=Decimal("0"),
            gross_profit=Decimal("0"),
            gross_loss=Decimal("0"),
            total_costs=Decimal("0"),
            net_pnl=Decimal("0"),
            net_return_percent=Decimal("0"),
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            breakeven_trades=0,
            win_rate=Decimal("0"),
            expectancy=Decimal("0"),
            profit_factor=None,
            payoff=None,
            drawdown_max_percent=Decimal("0"),
            exposure_percent=Decimal("0"),
            duration_hours=Decimal("0"),
            max_simultaneous_positions=0,
            max_loss_streak=0,
            max_risk_per_trade_percent=Decimal("0"),
            capital_paper_max_used=Decimal("0"),
            spread_deviation_bps=Decimal("0"),
            slippage_deviation_bps=Decimal("0"),
            fee_deviation_percent=Decimal("0"),
            snapshot_count=0,
            expired_data_cycles=0,
            suspension_count=0,
            suspension_reasons=tuple(),
            attempted_live_count=0,
            internal_error_count=0,
            regime_coverage=tuple(),
            trade_ids=tuple(),
            fill_count=0,
        )
    reasons = _collect_reasons(policy, aggregate_metrics, accepted)
    if load_rejections:
        reasons.extend(f"evidence rejected: {rejection.reason}" for rejection in load_rejections)
    status = _status_from_reasons(reasons, evidence=ordered_evidence)
    if load_rejections:
        status = PaperEvaluationStatus.REJECTED
    if status is PaperEvaluationStatus.APPROVED_FOR_EXTENDED_PAPER and (synthetic_test_data or not operational_evidence):
        reasons = tuple((*reasons, "operational evidence required."))
        status = PaperEvaluationStatus.INSUFFICIENT_EVIDENCE
    now = datetime.now(timezone.utc)
    evaluated_at_utc = accepted[-1].session_updated_utc if accepted else ordered_evidence[-1].session_updated_utc if ordered_evidence else now
    evaluation_identity = evaluation_id or paper_evaluation_hash(
        {
            "policy_hash": policy.policy_hash,
            "session_ids": [session.session_id for session in ordered_evidence],
            "session_hashes": [session.session_hash for session in ordered_evidence],
            "period_start_utc": ordered_evidence[0].session_started_utc if ordered_evidence else now,
            "period_end_utc": ordered_evidence[-1].session_updated_utc if ordered_evidence else now,
            "strategy_version": ordered_evidence[0].strategy_version if ordered_evidence else "v8_paper_evaluation",
        }
    )
    manifest = PaperEvaluationManifest(
        evaluation_id=evaluation_identity,
        period_start_utc=accepted[0].session_started_utc if accepted else ordered_evidence[0].session_started_utc if ordered_evidence else now,
        period_end_utc=accepted[-1].session_updated_utc if accepted else ordered_evidence[-1].session_updated_utc if ordered_evidence else now,
        inclusion_rule=inclusion_rule,
        synthetic_test_data=synthetic_test_data,
        operational_evidence=operational_evidence,
        session_ids=tuple(session.session_id for session in ordered_evidence),
        session_hashes=tuple((session.session_id, session.session_hash) for session in ordered_evidence),
        rejected_sessions=rejected,
        policy_hash=policy.policy_hash,
        strategy_version=accepted[0].strategy_version if accepted else ordered_evidence[0].strategy_version if ordered_evidence else "v8_paper_evaluation",
        evaluator_version=policy.evaluator_version,
        walk_forward_hash=reference_hash,
        session_count=len(ordered_evidence),
    )
    walk_forward_comparison = _compare_against_walk_forward(aggregate_metrics, reference_payload) if reference_payload else {}
    if reference_payload:
        manifest_hash = None
        if isinstance(reference_payload.get("manifest"), Mapping):
            manifest_hash = reference_payload["manifest"].get("manifest_hash")
        walk_forward_comparison["reference_manifest_hash"] = manifest_hash or reference_hash
    decision = PaperEvaluationDecision(
        status=status,
        policy_hash=policy.policy_hash,
        evidence_hash=paper_evaluation_hash({"sessions": [session.session_hash for session in ordered_evidence], "policy_hash": policy.policy_hash}),
        manifest_hash=manifest.manifest_hash,
        reasons=tuple(reasons),
        evaluated_at_utc=evaluated_at_utc,
        evaluator_version=policy.evaluator_version,
    )
    residual_risks = tuple(sorted(set(reasons)))
    return PaperEvaluationReport(
        manifest=manifest,
        policy=policy,
        decision=decision,
        evaluation_id=evaluation_identity,
        inclusion_rule=inclusion_rule,
        synthetic_test_data=synthetic_test_data,
        operational_evidence=operational_evidence,
        accepted_sessions=accepted,
        rejected_sessions=rejected,
        session_metrics=session_metrics,
        aggregate_metrics=aggregate_metrics,
        walk_forward_comparison=walk_forward_comparison,
        residual_risks=residual_risks,
        created_at_utc=now,
    )
