from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from domain.serialization import serialize_value

from .audit import chain_hash, event_content_hash, sanitize_payload, sha256_hex
from .errors import PaperRuntimeAuditError, PaperRuntimeSessionError, PaperRuntimeStoreError
from .models import (
    PaperRuntimeContract,
    PaperRuntimeEvent,
    PaperRuntimeEventType,
    PaperRuntimeSessionRecord,
    PaperRuntimeState,
)

SCHEMA_VERSION = 1


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_timezone_aware_text(value: str) -> str:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise PaperRuntimeAuditError("timestamp must be timezone-aware.")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class PaperRuntimeStore:
    def __init__(self, db_path: str | Path = "paper_runtime.db") -> None:
        self.db_path = Path(db_path)
        self._initialized = False

    @contextmanager
    def _connect(self, *, require_exists: bool = False):
        if require_exists and not self.db_path.exists():
            raise PaperRuntimeStoreError("runtime database not found.")
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            yield conn
        except sqlite3.DatabaseError as exc:
            raise PaperRuntimeStoreError("runtime storage error.") from exc
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_runtime_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_runtime_sessions (
                    session_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    contract_hash TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    decision_hash TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    paper_limits_hash TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    configuration_hash TEXT NOT NULL,
                    paper_limits_json TEXT NOT NULL,
                    configuration_json TEXT NOT NULL,
                    execution_contract_json TEXT NOT NULL,
                    execution_contract_hash TEXT NOT NULL,
                    paper_only INTEGER NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    session_started_utc TEXT NOT NULL,
                    last_snapshot_hash TEXT,
                    last_event_hash TEXT,
                    suspended_reason TEXT,
                    completed_reason TEXT,
                    failed_reason TEXT,
                    active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_runtime_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    decision_hash TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    result_status TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    UNIQUE(session_id, sequence),
                    UNIQUE(session_id, snapshot_hash),
                    FOREIGN KEY(session_id) REFERENCES paper_runtime_sessions(session_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_runtime_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    decision_hash TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    result TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    UNIQUE(session_id, sequence),
                    FOREIGN KEY(session_id) REFERENCES paper_runtime_sessions(session_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_runtime_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_active_decision_config ON paper_runtime_sessions(decision_hash, configuration_hash) WHERE active = 1"
            )
            current = conn.execute("SELECT value FROM paper_runtime_meta WHERE key = 'schema_version'").fetchone()
            if current is None:
                conn.execute(
                    "INSERT OR REPLACE INTO paper_runtime_meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            conn.execute("COMMIT")
        self._initialized = True

    def _ensure_initialized(self, *, require_exists: bool = False) -> None:
        if self._initialized:
            return
        if require_exists and not self.db_path.exists():
            raise PaperRuntimeStoreError("runtime database not found.")
        self.initialize()

    def _row_to_session(self, row: sqlite3.Row) -> PaperRuntimeSessionRecord:
        return PaperRuntimeSessionRecord(
            session_id=row["session_id"],
            state=PaperRuntimeState(row["state"]),
            version=row["version"],
            contract_hash=row["contract_hash"],
            decision_json=row["decision_json"],
            decision_hash=row["decision_hash"],
            evidence_hash=row["evidence_hash"],
            paper_limits_hash=row["paper_limits_hash"],
            strategy_version=row["strategy_version"],
            symbol=row["symbol"],
            interval=row["interval"],
            configuration_hash=row["configuration_hash"],
            paper_limits_json=row["paper_limits_json"],
            configuration_json=row["configuration_json"],
            execution_contract_json=row["execution_contract_json"],
            execution_contract_hash=row["execution_contract_hash"],
            paper_only=bool(row["paper_only"]),
            created_at_utc=datetime.fromisoformat(row["created_at_utc"].replace("Z", "+00:00")),
            updated_at_utc=datetime.fromisoformat(row["updated_at_utc"].replace("Z", "+00:00")),
            session_started_utc=datetime.fromisoformat(row["session_started_utc"].replace("Z", "+00:00")),
            last_snapshot_hash=row["last_snapshot_hash"],
            last_event_hash=row["last_event_hash"],
            suspended_reason=row["suspended_reason"],
            completed_reason=row["completed_reason"],
            failed_reason=row["failed_reason"],
            active=bool(row["active"]),
        )

    def _fetch_session_row(self, conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
        return conn.execute("SELECT * FROM paper_runtime_sessions WHERE session_id = ?", (session_id,)).fetchone()

    def load_session(self, session_id: str, *, require_exists: bool = True) -> PaperRuntimeSessionRecord | None:
        self._ensure_initialized(require_exists=require_exists)
        with self._connect(require_exists=require_exists) as conn:
            row = self._fetch_session_row(conn, session_id)
            if row is None:
                if require_exists:
                    raise PaperRuntimeStoreError("runtime session not found.")
                return None
            return self._row_to_session(row)

    def load_active_session(self, decision_hash: str | None = None, *, session_id: str | None = None) -> PaperRuntimeSessionRecord | None:
        self._ensure_initialized(require_exists=True)
        with self._connect(require_exists=True) as conn:
            if session_id is not None:
                row = self._fetch_session_row(conn, session_id)
                if row is None or not row["active"]:
                    return None
                return self._row_to_session(row)
            if decision_hash is None:
                row = conn.execute(
                    "SELECT * FROM paper_runtime_sessions WHERE active = 1 ORDER BY updated_at_utc DESC LIMIT 1"
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM paper_runtime_sessions WHERE active = 1 AND decision_hash = ? ORDER BY updated_at_utc DESC LIMIT 1",
                    (decision_hash,),
                ).fetchone()
            return self._row_to_session(row) if row else None

    def list_active_sessions(self) -> list[PaperRuntimeSessionRecord]:
        self._ensure_initialized(require_exists=True)
        with self._connect(require_exists=True) as conn:
            rows = conn.execute("SELECT * FROM paper_runtime_sessions WHERE active = 1 ORDER BY created_at_utc ASC").fetchall()
        return [self._row_to_session(row) for row in rows]

    def create_session(
        self,
        contract: PaperRuntimeContract,
        *,
        session_state: PaperRuntimeState = PaperRuntimeState.CREATED,
        decision_json: str | None = None,
    ) -> PaperRuntimeSessionRecord:
        self._ensure_initialized()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT session_id FROM paper_runtime_sessions
                WHERE active = 1 AND decision_hash = ? AND configuration_hash = ?
                """,
                (contract.decision_hash, sha256_hex({"configuration": contract.configuration})),
            ).fetchone()
            if existing is not None:
                raise PaperRuntimeSessionError("an active session for the same decision and configuration already exists.")
            now = _now_utc()
            session_row = {
                "session_id": contract.session_id,
                "state": session_state.value,
                "version": 1,
                "contract_hash": contract.contract_hash,
                "decision_json": decision_json
                or json.dumps(serialize_value(contract.as_dict()), ensure_ascii=False, sort_keys=True),
                "decision_hash": contract.decision_hash,
                "evidence_hash": contract.evidence_hash,
                "paper_limits_hash": contract.paper_limits_hash,
                "strategy_version": contract.strategy_version,
                "symbol": contract.symbol,
                "interval": contract.interval,
                "configuration_hash": sha256_hex({"configuration": contract.configuration}),
                "paper_limits_json": json.dumps(serialize_value(contract.paper_limits), ensure_ascii=False, sort_keys=True),
                "configuration_json": json.dumps(serialize_value(contract.configuration), ensure_ascii=False, sort_keys=True),
                "execution_contract_json": json.dumps(serialize_value(contract.execution_contract), ensure_ascii=False, sort_keys=True),
                "execution_contract_hash": sha256_hex({"execution_contract": contract.execution_contract}),
                "paper_only": 1 if contract.paper_only else 0,
                "created_at_utc": now,
                "updated_at_utc": now,
                "session_started_utc": contract.session_started_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "last_snapshot_hash": None,
                "last_event_hash": None,
                "suspended_reason": None,
                "completed_reason": None,
                "failed_reason": None,
                "active": 1,
            }
            conn.execute(
                """
                INSERT INTO paper_runtime_sessions (
                    session_id, state, version, contract_hash, decision_json, decision_hash, evidence_hash, paper_limits_hash,
                    strategy_version, symbol, interval, configuration_hash, paper_limits_json, configuration_json,
                    execution_contract_json, execution_contract_hash, paper_only,
                    created_at_utc, updated_at_utc, session_started_utc, last_snapshot_hash, last_event_hash,
                    suspended_reason, completed_reason, failed_reason, active
                ) VALUES (
                    :session_id, :state, :version, :contract_hash, :decision_json, :decision_hash, :evidence_hash, :paper_limits_hash,
                    :strategy_version, :symbol, :interval, :configuration_hash, :paper_limits_json, :configuration_json,
                    :execution_contract_json, :execution_contract_hash, :paper_only,
                    :created_at_utc, :updated_at_utc, :session_started_utc, :last_snapshot_hash, :last_event_hash,
                    :suspended_reason, :completed_reason, :failed_reason, :active
                )
                """,
                session_row,
            )
            self._append_event_locked(
                conn,
                session_id=contract.session_id,
                event_type=PaperRuntimeEventType.SESSION_CREATED,
                payload={"contract": contract.as_dict()},
                decision_hash=contract.decision_hash,
                evidence_hash=contract.evidence_hash,
                result=session_state.value,
                idempotency_key=f"start:{contract.session_id}",
            )
            conn.execute("COMMIT")
            return self.load_session(contract.session_id)

    def _append_event_locked(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        event_type: PaperRuntimeEventType,
        payload: Mapping[str, Any],
        decision_hash: str,
        evidence_hash: str,
        result: str,
        idempotency_key: str | None = None,
    ) -> PaperRuntimeEvent:
        if idempotency_key:
            row = conn.execute(
                "SELECT response_json FROM paper_runtime_idempotency WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is not None:
                data = json.loads(row["response_json"])
                return PaperRuntimeEvent(
                    event_id=data["event_id"],
                    session_id=data["session_id"],
                    sequence=data["sequence"],
                    event_type=PaperRuntimeEventType(data["event_type"]),
                    timestamp_utc=datetime.fromisoformat(data["timestamp_utc"].replace("Z", "+00:00")),
                    previous_hash=data["previous_hash"],
                    content_hash=data["content_hash"],
                    decision_hash=data["decision_hash"],
                    evidence_hash=data["evidence_hash"],
                    result=data["result"],
                    payload=data["payload"],
                    event_hash=data["event_hash"],
                )

        session_row = conn.execute(
            "SELECT version, last_event_hash FROM paper_runtime_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if session_row is None:
            raise PaperRuntimeStoreError("runtime session not found.")
        sequence = int(session_row["version"]) + 1
        previous_hash = str(session_row["last_event_hash"] or "")
        timestamp_utc = datetime.now(timezone.utc)
        payload_sanitized = sanitize_payload(dict(payload))
        content_hash = event_content_hash(
            {
                "event_type": event_type.value,
                "payload": payload_sanitized,
                "result": result,
                "timestamp_utc": timestamp_utc.isoformat().replace("+00:00", "Z"),
            }
        )
        event_hash = chain_hash(
            previous_hash,
            content_hash,
            session_id=session_id,
            sequence=sequence,
            event_type=event_type.value,
        )
        event = PaperRuntimeEvent(
            event_id=f"{session_id}:{sequence}",
            session_id=session_id,
            sequence=sequence,
            event_type=event_type,
            timestamp_utc=timestamp_utc,
            previous_hash=previous_hash,
            content_hash=content_hash,
            decision_hash=decision_hash,
            evidence_hash=evidence_hash,
            result=result,
            payload=payload_sanitized,
            event_hash=event_hash,
        )
        conn.execute(
            """
            INSERT INTO paper_runtime_events (
                event_id, session_id, sequence, event_type, timestamp_utc, previous_hash, content_hash, event_hash,
                decision_hash, evidence_hash, result, payload_json, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.session_id,
                event.sequence,
                event.event_type.value,
                event.timestamp_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                event.previous_hash,
                event.content_hash,
                event.event_hash,
                event.decision_hash,
                event.evidence_hash,
                event.result,
                json.dumps(event.payload, ensure_ascii=False, sort_keys=True),
                _now_utc(),
            ),
        )
        if idempotency_key:
            conn.execute(
                "INSERT OR REPLACE INTO paper_runtime_idempotency(idempotency_key, session_id, kind, response_json, created_at_utc) VALUES (?, ?, ?, ?, ?)",
                (idempotency_key, session_id, event_type.value, json.dumps(event.as_dict(), ensure_ascii=False, sort_keys=True), _now_utc()),
            )
        conn.execute(
            """
            UPDATE paper_runtime_sessions
               SET version = version + 1,
                   updated_at_utc = ?,
                   last_event_hash = ?
             WHERE session_id = ?
            """,
            (_now_utc(), event.event_hash, session_id),
        )
        return event

    def append_event(
        self,
        session_id: str,
        event_type: PaperRuntimeEventType,
        *,
        payload: Mapping[str, Any],
        decision_hash: str,
        evidence_hash: str,
        result: str,
        idempotency_key: str | None = None,
    ) -> PaperRuntimeEvent:
        self._ensure_initialized(require_exists=True)
        with self._connect(require_exists=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            event = self._append_event_locked(
                conn,
                session_id=session_id,
                event_type=event_type,
                payload=payload,
                decision_hash=decision_hash,
                evidence_hash=evidence_hash,
                result=result,
                idempotency_key=idempotency_key,
            )
            conn.execute("COMMIT")
            return event

    def append_snapshot(
        self,
        session_id: str,
        *,
        snapshot: Mapping[str, Any],
        decision_hash: str,
        evidence_hash: str,
        result_status: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_initialized(require_exists=True)
        payload = dict(snapshot)
        snapshot_hash = str(payload.get("snapshot_hash") or sha256_hex(payload))
        with self._connect(require_exists=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM paper_runtime_snapshots WHERE session_id = ? AND snapshot_hash = ?",
                (session_id, snapshot_hash),
            ).fetchone()
            if existing is not None:
                conn.execute("COMMIT")
                return dict(existing)
            session_row = conn.execute(
                "SELECT version, state FROM paper_runtime_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if session_row is None:
                raise PaperRuntimeStoreError("runtime session not found.")
            sequence = int(session_row["version"]) + 1
            conn.execute(
                """
                INSERT INTO paper_runtime_snapshots (
                    session_id, sequence, snapshot_hash, timestamp_utc, payload_json, decision_hash, evidence_hash,
                    result_status, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    sequence,
                    snapshot_hash,
                    _ensure_timezone_aware_text(str(payload["timestamp_utc"])),
                    json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True),
                    decision_hash,
                    evidence_hash,
                    result_status,
                    _now_utc(),
                ),
            )
            conn.execute(
                """
                UPDATE paper_runtime_sessions
                   SET version = version + 1,
                       updated_at_utc = ?,
                       last_snapshot_hash = ?,
                       state = CASE
                           WHEN ? = 'SUSPENDED' THEN 'SUSPENDED'
                           WHEN ? = 'COMPLETED' THEN 'COMPLETED'
                           ELSE state
                       END,
                       active = CASE
                           WHEN ? IN ('SUSPENDED', 'COMPLETED', 'FAILED') THEN 0
                           ELSE active
                       END
                 WHERE session_id = ?
                """,
                (_now_utc(), snapshot_hash, result_status, result_status, result_status, session_id),
            )
            conn.execute("COMMIT")
            return {
                "session_id": session_id,
                "sequence": sequence,
                "snapshot_hash": snapshot_hash,
                "result_status": result_status,
            }

    def transition_session(
        self,
        session_id: str,
        *,
        expected_version: int,
        next_state: PaperRuntimeState,
        reason: str | None = None,
    ) -> PaperRuntimeSessionRecord:
        self._ensure_initialized(require_exists=True)
        next_state = PaperRuntimeState(next_state)
        with self._connect(require_exists=True) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._fetch_session_row(conn, session_id)
            if row is None:
                raise PaperRuntimeStoreError("runtime session not found.")
            current = self._row_to_session(row)
            if current.version != expected_version:
                raise PaperRuntimeSessionError("session version mismatch.")
            if current.state in {PaperRuntimeState.SUSPENDED, PaperRuntimeState.COMPLETED, PaperRuntimeState.FAILED}:
                raise PaperRuntimeSessionError("terminal sessions cannot transition.")
            allowed = {
                PaperRuntimeState.CREATED: {PaperRuntimeState.RUNNING, PaperRuntimeState.FAILED},
                PaperRuntimeState.RUNNING: {
                    PaperRuntimeState.SUSPENDED,
                    PaperRuntimeState.COMPLETED,
                    PaperRuntimeState.FAILED,
                },
            }
            if next_state not in allowed.get(current.state, set()):
                raise PaperRuntimeSessionError("invalid session transition.")
            fields: dict[str, Any] = {
                "state": next_state.value,
                "version": current.version + 1,
                "updated_at_utc": _now_utc(),
            }
            if next_state == PaperRuntimeState.SUSPENDED:
                fields["suspended_reason"] = reason or current.suspended_reason
                fields["active"] = 0
            elif next_state == PaperRuntimeState.COMPLETED:
                fields["completed_reason"] = reason or current.completed_reason
                fields["active"] = 0
            elif next_state == PaperRuntimeState.FAILED:
                fields["failed_reason"] = reason or current.failed_reason
                fields["active"] = 0
            else:
                fields["active"] = 1
            assignments = ", ".join(f"{key} = :{key}" for key in fields)
            fields["session_id"] = session_id
            conn.execute(f"UPDATE paper_runtime_sessions SET {assignments} WHERE session_id = :session_id", fields)
            conn.execute("COMMIT")
            return self.load_session(session_id)

    def load_events(self, session_id: str) -> list[PaperRuntimeEvent]:
        self._ensure_initialized(require_exists=True)
        with self._connect(require_exists=True) as conn:
            rows = conn.execute(
                "SELECT * FROM paper_runtime_events WHERE session_id = ? ORDER BY sequence ASC",
                (session_id,),
            ).fetchall()
        events: list[PaperRuntimeEvent] = []
        previous_hash = ""
        for row in rows:
            payload = json.loads(row["payload_json"])
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
            expected_hash = chain_hash(
                previous_hash,
                event.content_hash,
                session_id=event.session_id,
                sequence=event.sequence,
                event_type=event.event_type.value,
            )
            if event.previous_hash != previous_hash or event.event_hash != expected_hash:
                raise PaperRuntimeAuditError("audit chain diverged.")
            previous_hash = event.event_hash
            events.append(event)
        return events

    def assert_audit_chain(self, session_id: str) -> None:
        self.load_events(session_id)


_DEFAULT_STORE: PaperRuntimeStore | None = None


def get_default_store() -> PaperRuntimeStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = PaperRuntimeStore()
    return _DEFAULT_STORE
