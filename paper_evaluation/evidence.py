from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

from config import resolve_paper_runtime_db_path, resolve_trades_db_path
from domain.serialization import serialize_value
from paper_runtime import PaperRuntimeEventType, PaperRuntimeSessionError, PaperRuntimeState
from paper_runtime.audit import chain_hash, event_content_hash
from paper_runtime.models import PaperRuntimeContract, PaperRuntimeEvent, PaperRuntimeSessionRecord
from promotion import (
    PaperMonitoringSnapshot,
    PromotionCriterionResult,
    PromotionDecision,
    PromotionStatus,
    promotion_hash,
)
from validation.models import CandidateConfig, FrozenSelection

from .errors import PaperEvaluationEvidenceError, PaperEvaluationReadError
from ._operational import (
    OperationalCohortContract,
    _OPERATIONAL_BATCH_TOKEN,
    load_latest_operational_cohort_contract,
    persist_operational_cohort_contract,
)
from .models import (
    _OperationalEvidenceBatch,
    PaperFillEvidence,
    PaperEvaluationCohort,
    PaperSessionEvidence,
    PaperSessionEventEvidence,
    PaperSessionRejection,
    PaperSessionSnapshotEvidence,
    PaperSessionTradeEvidence,
)


_RUNTIME_REQUIRED_TABLES = {
    "paper_runtime_meta",
    "paper_runtime_sessions",
    "paper_runtime_snapshots",
    "paper_runtime_events",
}

_TRADE_REQUIRED_COLUMNS = {
    "id",
    "timestamp",
    "tipo",
    "simbolo",
    "session_id",
    "status",
    "direcao",
    "resultado",
    "score",
    "lucro_percent",
    "rr_planejado",
    "entrada",
    "stop_loss",
    "take_profit",
    "quantidade",
    "valor_arriscado",
    "preco_base",
    "fill_price",
    "entry_fee",
    "exit_fee",
    "entry_spread_cost",
    "entry_slippage_cost",
    "exit_spread_cost",
    "exit_slippage_cost",
    "spread_cost",
    "slippage_cost",
    "pnl_bruto",
    "custos_totais",
    "pnl_liquido",
    "aberto_em",
    "fechado_em",
    "saida",
    "lucro_reais",
    "filtros_aplicados",
}


def _strict_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise PaperEvaluationEvidenceError(f"{field_name} must be boolean.")
    return value


def _normalize_regime(configuration: Mapping[str, Any]) -> str | None:
    top_level_present = "regime" in configuration
    top_level_value = configuration.get("regime")
    nested_mapping = configuration.get("execution_contract")
    nested_present = isinstance(nested_mapping, Mapping) and "regime" in nested_mapping
    nested_value = nested_mapping.get("regime") if nested_present else None

    def _strict_regime(value: Any, field_name: str) -> str:
        if type(value) is not str:
            raise PaperEvaluationEvidenceError(f"{field_name} must be a regime string.")
        regime = value.strip().upper()
        if regime not in {"BULL", "BEAR", "CHOP"}:
            raise PaperEvaluationEvidenceError(f"{field_name} must be BULL, BEAR or CHOP.")
        return regime

    if top_level_present:
        top_level_regime = _strict_regime(top_level_value, "configuration.regime")
        if nested_present:
            nested_regime = _strict_regime(nested_value, "configuration.execution_contract.regime")
            if top_level_regime != nested_regime:
                raise PaperEvaluationEvidenceError("regime divergence between configuration and execution contract.")
        return top_level_regime

    if nested_present:
        return _strict_regime(nested_value, "configuration.execution_contract.regime")
    return None


def _strict_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise PaperEvaluationEvidenceError(f"{field_name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise PaperEvaluationEvidenceError(f"{field_name} must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _strict_decimal(value: Any, field_name: str, *, allow_zero: bool = True) -> Decimal:
    try:
        decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception as exc:
        raise PaperEvaluationEvidenceError(f"{field_name} must be numeric.") from exc
    if not decimal.is_finite():
        raise PaperEvaluationEvidenceError(f"{field_name} must be finite.")
    if allow_zero and decimal < 0:
        raise PaperEvaluationEvidenceError(f"{field_name} cannot be negative.")
    if not allow_zero and decimal <= 0:
        raise PaperEvaluationEvidenceError(f"{field_name} must be greater than zero.")
    return decimal


def _strict_str(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise PaperEvaluationEvidenceError(f"{field_name} must be a string.")
    text = value.strip()
    if not text and not allow_empty:
        raise PaperEvaluationEvidenceError(f"{field_name} must be a non-empty string.")
    return text


def _strict_int(value: Any, field_name: str, *, allow_zero: bool = True) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise PaperEvaluationEvidenceError(f"{field_name} must be an integer.")
    if allow_zero and value < 0:
        raise PaperEvaluationEvidenceError(f"{field_name} cannot be negative.")
    if not allow_zero and value <= 0:
        raise PaperEvaluationEvidenceError(f"{field_name} must be greater than zero.")
    return int(value)


def _strict_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise PaperEvaluationEvidenceError(f"{field_name} must be boolean.")
    return value


def _validate_continuous_sequence(rows: list[sqlite3.Row], *, entity_name: str) -> None:
    previous_sequence: int | None = None
    for row in rows:
        sequence = _strict_int(row["sequence"], f"{entity_name}.sequence", allow_zero=False)
        if previous_sequence is not None and sequence != previous_sequence + 1:
            raise PaperEvaluationEvidenceError(f"{entity_name} sequence is not continuous.")
        previous_sequence = sequence


def _rehydrate_promotion_decision(decision_data: Mapping[str, Any], session_row: sqlite3.Row) -> PromotionDecision:
    frozen_selection_data = decision_data.get("frozen_selection") or {}
    candidate_data = frozen_selection_data.get("candidate") or {}
    candidate = CandidateConfig.from_mapping(
        candidate_data.get("name", "runtime"),
        candidate_data.get("parameters", {}),
    )
    frozen_selection = FrozenSelection(
        candidate=candidate,
        strategy_version=frozen_selection_data.get("strategy_version", session_row["strategy_version"]),
        costs=tuple(sorted((frozen_selection_data.get("costs", {}) or {}).items())),
        execution_contract=tuple(sorted((frozen_selection_data.get("execution_contract", {}) or {}).items())),
        symbol=frozen_selection_data.get("symbol", session_row["symbol"]),
        interval=frozen_selection_data.get("interval", session_row["interval"]),
        frozen_at=datetime.fromisoformat(str(frozen_selection_data.get("frozen_at", session_row["created_at_utc"])).replace("Z", "+00:00")),
        manifest_hash=frozen_selection_data.get("manifest_hash", session_row["contract_hash"]),
        window_id=frozen_selection_data.get("window_id", session_row["session_id"]),
    )
    criteria = tuple(
        PromotionCriterionResult(
            name=item.get("name", "criterion"),
            passed=_strict_bool(item.get("passed"), "criteria_evaluated.passed"),
            expected=item.get("expected"),
            actual=item.get("actual"),
            reason=item.get("reason", ""),
        )
        for item in decision_data.get("criteria_evaluated", [])
    )
    decision = PromotionDecision(
        status=PromotionStatus(decision_data.get("status", PromotionStatus.APPROVED_FOR_MONITORED_PAPER.value)),
        frozen_selection=frozen_selection,
        strategy_version=decision_data.get("strategy_version", session_row["strategy_version"]),
        symbol=decision_data.get("symbol", session_row["symbol"]),
        interval=decision_data.get("interval", session_row["interval"]),
        phase5_manifest=decision_data.get("phase5_manifest", {}),
        evidence_hash=decision_data.get("evidence_hash", session_row["evidence_hash"]),
        policy_hash=decision_data.get("policy_hash", session_row["contract_hash"]),
        decision_hash=decision_data.get("decision_hash", session_row["decision_hash"]),
        criteria_evaluated=criteria,
        reasons=tuple(decision_data.get("reasons", ())),
        recalculated_metrics=decision_data.get("recalculated_metrics", {}),
        paper_limits=decision_data.get("paper_limits", {}),
        timestamp_utc=datetime.fromisoformat(str(decision_data.get("timestamp_utc", session_row["updated_at_utc"])).replace("Z", "+00:00")),
        paper_limits_hash=decision_data.get("paper_limits_hash", session_row["paper_limits_hash"]),
    )
    if decision.status is not PromotionStatus.APPROVED_FOR_MONITORED_PAPER:
        raise PaperEvaluationEvidenceError("runtime decision must be approved for monitored paper.")
    return decision


@contextmanager
def _connect_readonly(db_path: str | Path):
    path = Path(db_path)
    if not path.exists():
        raise PaperEvaluationReadError("database not found.")
    uri = f"{path.resolve().as_uri()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        yield conn
    except sqlite3.DatabaseError as exc:
        raise PaperEvaluationReadError("strict sqlite read failed.") from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _require_table_columns(conn: sqlite3.Connection, table: str, required: set[str]) -> None:
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if table not in tables:
        raise PaperEvaluationReadError(f"missing table: {table}.")
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    missing = sorted(required - columns)
    if missing:
        raise PaperEvaluationReadError(f"missing columns for {table}: {', '.join(missing)}")


def _load_runtime_session_row(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM paper_runtime_sessions WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        raise PaperEvaluationEvidenceError("runtime session not found.")
    return row


def _load_runtime_session_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = conn.execute(
        "SELECT session_id, created_at_utc, session_started_utc, updated_at_utc, strategy_version, symbol, interval FROM paper_runtime_sessions ORDER BY session_started_utc ASC, session_id ASC",
    ).fetchall()
    if not rows:
        raise PaperEvaluationReadError("no paper sessions found.")
    return rows


def _load_operational_session_rows(conn: sqlite3.Connection, contract: OperationalCohortContract) -> list[sqlite3.Row]:
    if contract.inclusion_rule != "sqlite_all_sessions":
        raise PaperEvaluationReadError("unsupported operational inclusion rule.")
    rows = conn.execute(
        """
        SELECT session_id, created_at_utc, session_started_utc, updated_at_utc, strategy_version, symbol, interval
        FROM paper_runtime_sessions
        WHERE strategy_version = ?
          AND symbol = ?
          AND interval = ?
          AND datetime(created_at_utc) >= datetime(?)
          AND datetime(session_started_utc) >= datetime(?)
          AND datetime(session_started_utc) <= datetime(?)
        ORDER BY session_started_utc ASC, session_id ASC
        """,
        (
            contract.strategy_version,
            contract.symbol,
            contract.interval,
            contract.created_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            contract.period_start_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            contract.period_end_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        ),
    ).fetchall()
    if not rows:
        raise PaperEvaluationReadError("no paper sessions found.")
    return rows


def _load_runtime_snapshots(conn: sqlite3.Connection, session_id: str) -> list[PaperSessionSnapshotEvidence]:
    session_row = conn.execute(
        "SELECT last_snapshot_hash FROM paper_runtime_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    rows = conn.execute(
        "SELECT * FROM paper_runtime_snapshots WHERE session_id = ? ORDER BY sequence ASC",
        (session_id,),
    ).fetchall()
    _validate_continuous_sequence(rows, entity_name="runtime snapshot")
    snapshots: list[PaperSessionSnapshotEvidence] = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        snapshot = PaperMonitoringSnapshot(
            timestamp_utc=datetime.fromisoformat(str(payload["timestamp_utc"]).replace("Z", "+00:00")),
            decision_hash=payload["decision_hash"],
            evidence_hash=payload["evidence_hash"],
            strategy_version=payload["strategy_version"],
            configuration=dict(payload["configuration"]),
            trading_mode=payload["trading_mode"],
            session_id=payload["session_id"],
            session_started_utc=datetime.fromisoformat(str(payload["session_started_utc"]).replace("Z", "+00:00")),
            data_fresh=payload["data_fresh"],
            session_drawdown_percent=Decimal(str(payload["session_drawdown_percent"])),
            current_loss_streak=payload["current_loss_streak"],
            open_positions=payload["open_positions"],
            executed_trades=payload["executed_trades"],
            observed_costs=dict(payload["observed_costs"]),
            session_state=payload.get("session_state", "RUNNING"),
            paper_capital_used=Decimal(str(payload["paper_capital_used"])),
            risk_per_trade_percent=Decimal(str(payload["risk_per_trade_percent"])),
            internal_error=payload.get("internal_error"),
            attempted_live=payload["attempted_live"],
        )
        if row["snapshot_hash"] != snapshot.snapshot_hash:
            raise PaperEvaluationEvidenceError("runtime snapshot hash mismatch.")
        if row["decision_hash"] != snapshot.decision_hash or row["evidence_hash"] != snapshot.evidence_hash:
            raise PaperEvaluationEvidenceError("runtime snapshot hash divergence.")
        if row["timestamp_utc"] != snapshot.timestamp_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"):
            raise PaperEvaluationEvidenceError("runtime snapshot timestamp mismatch.")
        snapshots.append(
            PaperSessionSnapshotEvidence(
                snapshot_hash=row["snapshot_hash"],
                sequence=row["sequence"],
                timestamp_utc=snapshot.timestamp_utc,
                session_id=snapshot.session_id,
                session_started_utc=snapshot.session_started_utc,
                session_state=snapshot.session_state,
                data_fresh=snapshot.data_fresh,
                paper_capital_used=snapshot.paper_capital_used,
                risk_per_trade_percent=snapshot.risk_per_trade_percent,
                session_drawdown_percent=snapshot.session_drawdown_percent,
                current_loss_streak=snapshot.current_loss_streak,
                open_positions=snapshot.open_positions,
                executed_trades=snapshot.executed_trades,
                observed_costs=dict(snapshot.observed_costs),
                attempted_live=snapshot.attempted_live,
                internal_error=snapshot.internal_error,
                result_status=row["result_status"],
            )
        )
    if session_row is None:
        raise PaperEvaluationEvidenceError("runtime session not found while loading snapshots.")
    if rows:
        if session_row["last_snapshot_hash"] != rows[-1]["snapshot_hash"]:
            raise PaperEvaluationEvidenceError("runtime last snapshot hash mismatch.")
    elif session_row["last_snapshot_hash"] is not None:
        raise PaperEvaluationEvidenceError("runtime last snapshot hash mismatch.")
    return snapshots


def _load_runtime_events(conn: sqlite3.Connection, session_id: str) -> list[PaperSessionEventEvidence]:
    session_row = conn.execute(
        "SELECT last_event_hash FROM paper_runtime_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    rows = conn.execute(
        "SELECT * FROM paper_runtime_events WHERE session_id = ? ORDER BY sequence ASC",
        (session_id,),
    ).fetchall()
    _validate_continuous_sequence(rows, entity_name="runtime event")
    events: list[PaperSessionEventEvidence] = []
    previous_hash = ""
    for row in rows:
        payload = json.loads(row["payload_json"])
        content_hash = event_content_hash(
            {
                "event_type": row["event_type"],
                "payload": payload,
                "result": row["result"],
                "timestamp_utc": row["timestamp_utc"],
                "decision_hash": row["decision_hash"],
                "evidence_hash": row["evidence_hash"],
                "session_id": row["session_id"],
                "sequence": row["sequence"],
            }
        )
        expected_hash = chain_hash(
            previous_hash,
            content_hash,
            session_id=row["session_id"],
            sequence=row["sequence"],
            event_type=row["event_type"],
        )
        if row["content_hash"] != content_hash or row["previous_hash"] != previous_hash or row["event_hash"] != expected_hash:
            raise PaperEvaluationEvidenceError("audit chain diverged.")
        event = PaperRuntimeEvent(
            event_id=row["event_id"],
            session_id=row["session_id"],
            sequence=row["sequence"],
            event_type=PaperRuntimeEventType(row["event_type"]),
            timestamp_utc=datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00")),
            previous_hash=row["previous_hash"],
            content_hash=row["content_hash"],
            decision_hash=row["decision_hash"],
            evidence_hash=row["evidence_hash"],
            result=row["result"],
            payload=payload,
            event_hash=row["event_hash"],
        )
        events.append(
            PaperSessionEventEvidence(
                event_id=event.event_id,
                sequence=event.sequence,
                event_type=event.event_type.value,
                timestamp_utc=event.timestamp_utc,
                session_id=event.session_id,
                previous_hash=event.previous_hash,
                content_hash=event.content_hash,
                event_hash=event.event_hash,
                result=event.result,
                payload=event.payload,
            )
        )
        previous_hash = event.event_hash
    if session_row is None:
        raise PaperEvaluationEvidenceError("runtime session not found while loading events.")
    if rows:
        if session_row["last_event_hash"] != previous_hash:
            raise PaperEvaluationEvidenceError("runtime last event hash mismatch.")
    elif session_row["last_event_hash"] is not None:
        raise PaperEvaluationEvidenceError("runtime last event hash mismatch.")
    return events


def _trade_to_fills(trade: PaperSessionTradeEvidence) -> tuple[PaperFillEvidence, ...]:
    fills: list[PaperFillEvidence] = []
    entry_price = trade.fill_price or trade.preco_base or trade.entrada
    fills.append(
        PaperFillEvidence(
            trade_id=trade.trade_id,
            session_id=trade.session_id,
            fill_side="ENTRY",
            timestamp_utc=trade.aberto_em,
            price=entry_price,
            quantity=trade.quantidade,
            fee=trade.entry_fee or Decimal("0"),
            spread_cost=trade.entry_spread_cost or Decimal("0"),
            slippage_cost=trade.entry_slippage_cost or Decimal("0"),
            is_real=False,
        )
    )
    if trade.fechado_em is not None:
        fills.append(
            PaperFillEvidence(
                trade_id=trade.trade_id,
                session_id=trade.session_id,
                fill_side="EXIT",
                timestamp_utc=trade.fechado_em,
                price=trade.saida or trade.fill_price or trade.entrada,
                quantity=trade.quantidade,
                fee=trade.exit_fee or Decimal("0"),
                spread_cost=trade.exit_spread_cost or Decimal("0"),
                slippage_cost=trade.exit_slippage_cost or Decimal("0"),
                is_real=False,
            )
        )
    return tuple(fills)


def _trade_row_to_evidence(row: Mapping[str, Any]) -> PaperSessionTradeEvidence:
    return PaperSessionTradeEvidence(
        trade_id=row["id"],
        session_id=row["session_id"],
        symbol=row["simbolo"],
        tipo=row["tipo"],
        status=row["status"],
        direcao=row["direcao"],
        entrada=row["entrada"],
        stop_loss=row["stop_loss"],
        take_profit=row["take_profit"],
        quantidade=row["quantidade"],
        valor_arriscado=row["valor_arriscado"],
        preco_base=row["preco_base"],
        fill_price=row["fill_price"],
        entry_fee=row["entry_fee"],
        exit_fee=row["exit_fee"],
        entry_spread_cost=row["entry_spread_cost"],
        entry_slippage_cost=row["entry_slippage_cost"],
        exit_spread_cost=row["exit_spread_cost"],
        exit_slippage_cost=row["exit_slippage_cost"],
        spread_cost=row["spread_cost"],
        slippage_cost=row["slippage_cost"],
        pnl_bruto=row["pnl_bruto"],
        custos_totais=row["custos_totais"],
        pnl_liquido=row["pnl_liquido"],
        aberto_em=datetime.fromisoformat(str(row["aberto_em"]).replace("Z", "+00:00")),
        fechado_em=datetime.fromisoformat(str(row["fechado_em"]).replace("Z", "+00:00")) if row["fechado_em"] else None,
        saida=row["saida"],
        lucro_reais=row["lucro_reais"],
        lucro_percent=row["lucro_percent"],
        filtros_aplicados=bool(row["filtros_aplicados"]),
        idempotency_key=row["idempotency_key"],
        close_idempotency_key=row["close_idempotency_key"],
        close_idempotency_hash=row["close_idempotency_hash"],
        is_real=bool(row["tipo"] != "paper" and False),
    )


def _load_trades(conn: sqlite3.Connection, session_id: str) -> list[PaperSessionTradeEvidence]:
    rows = conn.execute(
        "SELECT * FROM trades WHERE session_id = ? AND tipo = 'paper' ORDER BY COALESCE(fechado_em, aberto_em, timestamp) ASC, id ASC",
        (session_id,),
    ).fetchall()
    return [_trade_row_to_evidence(row) for row in rows]


def _validate_trade_schema(conn: sqlite3.Connection) -> None:
    _require_table_columns(conn, "trades", _TRADE_REQUIRED_COLUMNS)


def _validate_runtime_schema(conn: sqlite3.Connection) -> None:
    _require_table_columns(conn, "paper_runtime_sessions", {
        "session_id",
        "state",
        "version",
        "contract_hash",
        "decision_json",
        "decision_hash",
        "evidence_hash",
        "paper_limits_hash",
        "strategy_version",
        "symbol",
        "interval",
        "configuration_hash",
        "paper_limits_json",
        "configuration_json",
        "execution_contract_json",
        "execution_contract_hash",
        "paper_only",
        "created_at_utc",
        "updated_at_utc",
        "session_started_utc",
        "last_snapshot_hash",
        "last_event_hash",
        "suspended_reason",
        "completed_reason",
        "failed_reason",
        "active",
    })
    _require_table_columns(conn, "paper_runtime_snapshots", {
        "session_id",
        "sequence",
        "snapshot_hash",
        "timestamp_utc",
        "payload_json",
        "decision_hash",
        "evidence_hash",
        "result_status",
        "created_at_utc",
    })
    _require_table_columns(conn, "paper_runtime_events", {
        "event_id",
        "session_id",
        "sequence",
        "event_type",
        "timestamp_utc",
        "previous_hash",
        "content_hash",
        "event_hash",
        "decision_hash",
        "evidence_hash",
        "result",
        "payload_json",
        "created_at_utc",
    })


def load_paper_session_evidence(
    session_id: str,
    *,
    runtime_db_path: str | Path = resolve_paper_runtime_db_path(),
    trades_db_path: str | Path = resolve_trades_db_path(),
) -> PaperSessionEvidence:
    session_id = _strict_str(session_id, "session_id")
    runtime_db_path = Path(runtime_db_path)
    trades_db_path = Path(trades_db_path)
    try:
        with _connect_readonly(runtime_db_path) as runtime_conn, _connect_readonly(trades_db_path) as trades_conn:
            _validate_runtime_schema(runtime_conn)
            _validate_trade_schema(trades_conn)
            session_row = _load_runtime_session_row(runtime_conn, session_id)
            decision_data = json.loads(session_row["decision_json"])
            decision = _rehydrate_promotion_decision(decision_data, session_row)
            snapshots = _load_runtime_snapshots(runtime_conn, session_id)
            events = _load_runtime_events(runtime_conn, session_id)
            trades = _load_trades(trades_conn, session_id)
            fills = []
            for trade in trades:
                fills.extend(_trade_to_fills(trade))

            session_state = str(session_row["state"]).strip().upper()
            session_started_utc = datetime.fromisoformat(str(session_row["session_started_utc"]).replace("Z", "+00:00"))
            session_updated_utc = datetime.fromisoformat(str(session_row["updated_at_utc"]).replace("Z", "+00:00"))
            session_finished_utc = None
            if session_row["state"] in {"SUSPENDED", "COMPLETED", "FAILED"} and session_row["updated_at_utc"]:
                session_finished_utc = session_updated_utc
            configuration = json.loads(session_row["configuration_json"])
            contract = PaperRuntimeContract(
                session_id=session_row["session_id"],
                session_started_utc=session_started_utc,
                decision_hash=decision.decision_hash,
                evidence_hash=decision.evidence_hash,
                paper_limits_hash=decision.paper_limits_hash,
                paper_limits=decision.paper_limits,
                configuration=decision.frozen_selection.as_dict(),
                strategy_version=decision.strategy_version,
                symbol=decision.symbol,
                interval=decision.interval,
                execution_contract=decision.phase5_manifest.get("execution_contract", {}),
                paper_only=True,
            )
            if contract.contract_hash != session_row["contract_hash"]:
                raise PaperEvaluationEvidenceError("runtime contract hash mismatch.")
            if session_row["configuration_hash"] != promotion_hash({"configuration": contract.configuration}):
                raise PaperEvaluationEvidenceError("runtime configuration hash mismatch.")
            if session_row["execution_contract_hash"] != promotion_hash({"execution_contract": contract.execution_contract}):
                raise PaperEvaluationEvidenceError("runtime execution contract hash mismatch.")
            if json.loads(session_row["paper_limits_json"]) != serialize_value(contract.paper_limits):
                raise PaperEvaluationEvidenceError("runtime paper limits divergence.")
            if json.loads(session_row["configuration_json"]) != serialize_value(contract.configuration):
                raise PaperEvaluationEvidenceError("runtime configuration divergence.")
            if json.loads(session_row["execution_contract_json"]) != serialize_value(contract.execution_contract):
                raise PaperEvaluationEvidenceError("runtime execution contract divergence.")
            if contract.paper_only is not True or contract.execution_contract.get("paper_only") is not True:
                raise PaperEvaluationEvidenceError("runtime must remain paper-only.")
            if decision.paper_limits_hash != session_row["paper_limits_hash"]:
                raise PaperEvaluationEvidenceError("decision paper limits hash mismatch.")
            if decision.decision_hash != session_row["decision_hash"] or decision.evidence_hash != session_row["evidence_hash"]:
                raise PaperEvaluationEvidenceError("decision hash mismatch.")
            if decision.strategy_version != session_row["strategy_version"] or decision.symbol != session_row["symbol"] or decision.interval != session_row["interval"]:
                raise PaperEvaluationEvidenceError("decision contract mismatch.")
            if not isinstance(decision.phase5_manifest.get("execution_contract"), Mapping):
                raise PaperEvaluationEvidenceError("decision execution contract is required.")
            observed_costs: dict[str, Decimal] = {}
            for snapshot in snapshots:
                for key, value in snapshot.observed_costs.items():
                    if key not in observed_costs:
                        observed_costs[key] = _strict_decimal(value, key)
            if not all(trade.is_real is False for trade in trades):
                raise PaperEvaluationEvidenceError("real trades are not allowed.")
            if not all(fill.is_real is False for fill in fills):
                raise PaperEvaluationEvidenceError("real fills are not allowed.")
            session_hash_payload = {
                "session_id": session_id,
                "session_state": session_state,
                "session_started_utc": session_started_utc,
                "session_updated_utc": session_updated_utc,
                "session_finished_utc": session_finished_utc,
                "decision_hash": session_row["decision_hash"],
                "evidence_hash": session_row["evidence_hash"],
                "paper_limits_hash": session_row["paper_limits_hash"],
                "strategy_version": session_row["strategy_version"],
                "symbol": session_row["symbol"],
                "interval": session_row["interval"],
                "paper_only": bool(session_row["paper_only"]),
                "contract_hash": session_row["contract_hash"],
                "paper_limits": contract.paper_limits,
                "configuration": contract.configuration,
                "execution_contract": contract.execution_contract,
                "snapshots": [snapshot.as_dict() for snapshot in snapshots],
                "events": [event.as_dict() for event in events],
                "trades": [trade.as_dict() for trade in trades],
                "fills": [fill.as_dict() for fill in fills],
                "audit_chain_valid": True,
                "attempted_live_count": sum(1 for snapshot in snapshots if snapshot.attempted_live),
                "internal_error_count": sum(1 for snapshot in snapshots if snapshot.internal_error),
                "expired_data_cycles": sum(1 for snapshot in snapshots if not snapshot.data_fresh),
                "suspension_reasons": tuple(sorted({snapshot.result_status or snapshot.session_state for snapshot in snapshots if snapshot.session_state == "SUSPENDED"})),
                "regime_coverage": tuple(sorted({regime for regime in (_normalize_regime(configuration) for _snapshot in snapshots) if regime})),
                "observed_costs": observed_costs,
            }
            return PaperSessionEvidence(
                session_id=session_id,
                session_state=session_state,
                session_started_utc=session_started_utc,
                session_updated_utc=session_updated_utc,
                session_finished_utc=session_finished_utc,
                decision_hash=session_row["decision_hash"],
                evidence_hash=session_row["evidence_hash"],
                paper_limits_hash=session_row["paper_limits_hash"],
                strategy_version=session_row["strategy_version"],
                symbol=session_row["symbol"],
                interval=session_row["interval"],
                paper_only=bool(session_row["paper_only"]),
                contract_hash=session_row["contract_hash"],
                paper_limits=contract.paper_limits,
                configuration=contract.configuration,
                execution_contract=contract.execution_contract,
                snapshots=tuple(snapshots),
                events=tuple(events),
                trades=tuple(trades),
                fills=tuple(fills),
                audit_chain_valid=True,
                attempted_live_count=sum(1 for snapshot in snapshots if snapshot.attempted_live),
                internal_error_count=sum(1 for snapshot in snapshots if snapshot.internal_error),
                expired_data_cycles=sum(1 for snapshot in snapshots if not snapshot.data_fresh),
                suspension_reasons=tuple(sorted({snapshot.result_status or snapshot.session_state for snapshot in snapshots if snapshot.session_state == "SUSPENDED"})),
                regime_coverage=tuple(sorted({regime for regime in (_normalize_regime(configuration) for _snapshot in snapshots) if regime})),
                observed_costs=observed_costs,
            )
    except PaperEvaluationEvidenceError:
        raise
    except Exception as exc:
        logging.warning("Paper evaluation evidence load failed: %s", exc.__class__.__name__)
        raise PaperEvaluationReadError("paper evaluation evidence load failed.") from exc


def load_operational_evidence_batch(
    *,
    runtime_db_path: str | Path = resolve_paper_runtime_db_path(),
    trades_db_path: str | Path = resolve_trades_db_path(),
) -> _OperationalEvidenceBatch:
    runtime_db_path = Path(runtime_db_path)
    trades_db_path = Path(trades_db_path)
    with _connect_readonly(runtime_db_path) as runtime_conn, _connect_readonly(trades_db_path) as trades_conn:
        _validate_runtime_schema(runtime_conn)
        _validate_trade_schema(trades_conn)
        contract = load_latest_operational_cohort_contract(runtime_db_path)
        session_rows = _load_operational_session_rows(runtime_conn, contract)
        session_ids = tuple(str(row["session_id"]).strip() for row in session_rows if str(row["session_id"]).strip())
        if not session_ids:
            raise PaperEvaluationReadError("no paper sessions found.")
        cohort = PaperEvaluationCohort(
            strategy_version=contract.strategy_version,
            period_start_utc=contract.period_start_utc,
            period_end_utc=contract.period_end_utc,
            inclusion_rule=contract.inclusion_rule,
            created_at_utc=contract.created_at_utc,
            session_ids=session_ids,
        )
        evidences: list[PaperSessionEvidence] = []
        rejections: list[PaperSessionRejection] = []
        for row in session_rows:
            session_id = str(row["session_id"]).strip()
            try:
                evidence = load_paper_session_evidence(session_id, runtime_db_path=runtime_db_path, trades_db_path=trades_db_path)
                evidences.append(evidence)
            except PaperEvaluationEvidenceError as exc:
                rejections.append(PaperSessionRejection(session_id=session_id, reason=str(exc)))
        return _OperationalEvidenceBatch(
            contract=contract,
            cohort=cohort,
            evidences=tuple(evidences),
            rejections=tuple(rejections),
            _token=_OPERATIONAL_BATCH_TOKEN,
        )


def load_paper_session_evidence_batch(
    *,
    runtime_db_path: str | Path = resolve_paper_runtime_db_path(),
    trades_db_path: str | Path = resolve_trades_db_path(),
    period_start_utc: datetime | None = None,
    period_end_utc: datetime | None = None,
    session_ids: Iterable[str] | None = None,
) -> tuple[list[PaperSessionEvidence], list[PaperSessionRejection]]:
    runtime_db_path = Path(runtime_db_path)
    trades_db_path = Path(trades_db_path)
    if session_ids is not None:
        normalized_ids = []
        for session_id in session_ids:
            normalized_ids.append(_strict_str(session_id, "session_id"))
        if not normalized_ids:
            raise PaperEvaluationReadError("explicit session selection is empty.")
        if len(set(normalized_ids)) != len(normalized_ids):
            raise PaperEvaluationReadError("duplicate session ids are not allowed.")
        ordered_ids = tuple(sorted(normalized_ids))
    else:
        ordered_ids = ()
    evidences: list[PaperSessionEvidence] = []
    rejections: list[PaperSessionRejection] = []
    try:
        with _connect_readonly(runtime_db_path) as conn:
            _validate_runtime_schema(conn)
            query = "SELECT session_id FROM paper_runtime_sessions"
            params: list[Any] = []
            filters: list[str] = []
            if period_start_utc is not None:
                filters.append("datetime(session_started_utc) >= datetime(?)")
                params.append(_strict_datetime(period_start_utc, "period_start_utc").isoformat().replace("+00:00", "Z"))
            if period_end_utc is not None:
                filters.append("datetime(session_started_utc) <= datetime(?)")
                params.append(_strict_datetime(period_end_utc, "period_end_utc").isoformat().replace("+00:00", "Z"))
            if ordered_ids:
                placeholders = ",".join("?" for _ in ordered_ids)
                filters.append(f"session_id IN ({placeholders})")
                params.extend(ordered_ids)
            if filters:
                query += " WHERE " + " AND ".join(filters)
            rows = conn.execute(query, params).fetchall()
            candidate_ids = [row["session_id"] for row in rows]
            if ordered_ids and set(candidate_ids) != set(ordered_ids):
                raise PaperEvaluationReadError("explicit session selection does not match runtime storage.")
    except Exception as exc:
        raise PaperEvaluationReadError("failed to enumerate paper sessions.") from exc

    for session_id in sorted(candidate_ids):
        try:
            evidence = load_paper_session_evidence(session_id, runtime_db_path=runtime_db_path, trades_db_path=trades_db_path)
            evidences.append(evidence)
        except PaperEvaluationEvidenceError as exc:
            rejections.append(PaperSessionRejection(session_id=session_id, reason=str(exc)))
        except PaperEvaluationReadError as exc:
            rejections.append(PaperSessionRejection(session_id=session_id, reason=str(exc)))
    return evidences, rejections
