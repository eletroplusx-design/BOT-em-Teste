from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from domain.serialization import serialize_value

from .artifacts import paper_evaluation_hash
from .errors import PaperEvaluationEvidenceError, PaperEvaluationManifestError, PaperEvaluationReadError


class _OperationalBatchToken:
    __slots__ = ()


_OPERATIONAL_BATCH_TOKEN = _OperationalBatchToken()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_str(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise PaperEvaluationManifestError(f"{field_name} must be a string.")
    result = value.strip()
    if not result and not allow_empty:
        raise PaperEvaluationManifestError(f"{field_name} must be a non-empty string.")
    return result


def _require_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise PaperEvaluationManifestError(f"{field_name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise PaperEvaluationManifestError(f"{field_name} must be timezone-aware.")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class OperationalCohortContract:
    strategy_version: str
    symbol: str
    interval: str
    inclusion_rule: str
    period_start_utc: datetime
    period_end_utc: datetime
    created_at_utc: datetime
    cohort_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy_version", _require_str(self.strategy_version, "strategy_version"))
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol"))
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "inclusion_rule", _require_str(self.inclusion_rule, "inclusion_rule"))
        object.__setattr__(self, "period_start_utc", _require_datetime(self.period_start_utc, "period_start_utc"))
        object.__setattr__(self, "period_end_utc", _require_datetime(self.period_end_utc, "period_end_utc"))
        object.__setattr__(self, "created_at_utc", _require_datetime(self.created_at_utc, "created_at_utc"))
        if self.period_end_utc < self.period_start_utc:
            raise PaperEvaluationManifestError("period_end_utc cannot be earlier than period_start_utc.")
        if self.created_at_utc >= self.period_start_utc:
            raise PaperEvaluationManifestError("created_at_utc must be earlier than period_start_utc.")
        payload = self.as_hash_payload(include_hash=False)
        contract_hash = self.cohort_hash or paper_evaluation_hash(payload)
        object.__setattr__(self, "cohort_hash", _require_str(contract_hash, "cohort_hash"))
        if self.cohort_hash != paper_evaluation_hash(payload):
            raise PaperEvaluationManifestError("cohort hash mismatch.")

    def as_hash_payload(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "strategy_version": self.strategy_version,
            "symbol": self.symbol,
            "interval": self.interval,
            "inclusion_rule": self.inclusion_rule,
            "period_start_utc": self.period_start_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "period_end_utc": self.period_end_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "created_at_utc": self.created_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if include_hash:
            payload["cohort_hash"] = self.cohort_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.as_hash_payload())


_COHORT_REQUIRED_COLUMNS = {
    "cohort_hash",
    "strategy_version",
    "symbol",
    "interval",
    "inclusion_rule",
    "period_start_utc",
    "period_end_utc",
    "created_at_utc",
    "payload_json",
}


def _connect_rw(db_path: str | Path):
    return sqlite3.connect(Path(db_path), timeout=30, isolation_level=None)


@contextmanager
def _connect_ro(db_path: str | Path):
    path = Path(db_path)
    if not path.exists():
        raise PaperEvaluationReadError("operational cohort database not found.")
    conn = None
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        yield conn
    except sqlite3.DatabaseError as exc:
        raise PaperEvaluationReadError("operational cohort storage failed.") from exc
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def ensure_operational_cohort_schema(db_path: str | Path) -> None:
    with _connect_rw(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_evaluation_cohort_contracts (
                cohort_hash TEXT PRIMARY KEY,
                strategy_version TEXT NOT NULL,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                inclusion_rule TEXT NOT NULL,
                period_start_utc TEXT NOT NULL,
                period_end_utc TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_paper_evaluation_cohort_contracts_lookup ON paper_evaluation_cohort_contracts(strategy_version, symbol, interval, inclusion_rule, period_start_utc, period_end_utc, created_at_utc)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_evaluation_cohort_contracts_window_unique ON paper_evaluation_cohort_contracts(strategy_version, symbol, interval, inclusion_rule, period_start_utc, period_end_utc)"
        )
        conn.commit()


def persist_operational_cohort_contract(
    db_path: str | Path,
    *,
    strategy_version: str,
    symbol: str,
    interval: str,
    inclusion_rule: str,
    period_start_utc: datetime,
    period_end_utc: datetime,
) -> OperationalCohortContract:
    ensure_operational_cohort_schema(db_path)
    contract = OperationalCohortContract(
        strategy_version=strategy_version,
        symbol=symbol,
        interval=interval,
        inclusion_rule=inclusion_rule,
        period_start_utc=period_start_utc,
        period_end_utc=period_end_utc,
        created_at_utc=_utcnow(),
    )
    payload = json.dumps(contract.as_dict(), ensure_ascii=False, sort_keys=True)
    with _connect_rw(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            INSERT INTO paper_evaluation_cohort_contracts (
                cohort_hash, strategy_version, symbol, interval, inclusion_rule, period_start_utc, period_end_utc, created_at_utc, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contract.cohort_hash,
                contract.strategy_version,
                contract.symbol,
                contract.interval,
                contract.inclusion_rule,
                contract.period_start_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                contract.period_end_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                contract.created_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                payload,
            ),
        )
        conn.commit()
    return contract


def load_latest_operational_cohort_contract(
    db_path: str | Path,
    *,
    cohort_hash: str | None = None,
    strategy_version: str | None = None,
    symbol: str | None = None,
    interval: str | None = None,
    inclusion_rule: str | None = None,
) -> OperationalCohortContract:
    with _connect_ro(db_path) as conn:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "paper_evaluation_cohort_contracts" not in tables:
            raise PaperEvaluationReadError("operational cohort contract is missing.")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(paper_evaluation_cohort_contracts)")}
        missing = sorted(_COHORT_REQUIRED_COLUMNS - columns)
        if missing:
            raise PaperEvaluationReadError("operational cohort contract schema is incomplete.")
        filters = []
        params: list[Any] = []
        if strategy_version is not None:
            filters.append("strategy_version = ?")
            params.append(_require_str(strategy_version, "strategy_version"))
        if cohort_hash is not None:
            filters.append("cohort_hash = ?")
            params.append(_require_str(cohort_hash, "cohort_hash"))
        if symbol is not None:
            filters.append("symbol = ?")
            params.append(_require_str(symbol, "symbol"))
        if interval is not None:
            filters.append("interval = ?")
            params.append(_require_str(interval, "interval"))
        if inclusion_rule is not None:
            filters.append("inclusion_rule = ?")
            params.append(_require_str(inclusion_rule, "inclusion_rule"))
        query = "SELECT * FROM paper_evaluation_cohort_contracts"
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY created_at_utc DESC, cohort_hash DESC LIMIT 1"
        row = conn.execute(query, params).fetchone()
        if row is None:
            raise PaperEvaluationReadError("operational cohort contract not found.")
        contract = OperationalCohortContract(
            strategy_version=row["strategy_version"],
            symbol=row["symbol"],
            interval=row["interval"],
            inclusion_rule=row["inclusion_rule"],
            period_start_utc=datetime.fromisoformat(str(row["period_start_utc"]).replace("Z", "+00:00")),
            period_end_utc=datetime.fromisoformat(str(row["period_end_utc"]).replace("Z", "+00:00")),
            created_at_utc=datetime.fromisoformat(str(row["created_at_utc"]).replace("Z", "+00:00")),
            cohort_hash=row["cohort_hash"],
        )
        stored_payload = json.loads(row["payload_json"]) if row["payload_json"] else None
        expected_payload = contract.as_dict()
        if stored_payload != expected_payload:
            raise PaperEvaluationReadError("operational cohort contract payload mismatch.")
        if row["cohort_hash"] != contract.cohort_hash:
            raise PaperEvaluationReadError("operational cohort contract hash mismatch.")
        row_payload = {
            "strategy_version": row["strategy_version"],
            "symbol": row["symbol"],
            "interval": row["interval"],
            "inclusion_rule": row["inclusion_rule"],
            "period_start_utc": row["period_start_utc"],
            "period_end_utc": row["period_end_utc"],
            "created_at_utc": row["created_at_utc"],
            "cohort_hash": row["cohort_hash"],
        }
        expected_columns = {
            "strategy_version": expected_payload["strategy_version"],
            "symbol": expected_payload["symbol"],
            "interval": expected_payload["interval"],
            "inclusion_rule": expected_payload["inclusion_rule"],
            "period_start_utc": expected_payload["period_start_utc"],
            "period_end_utc": expected_payload["period_end_utc"],
            "created_at_utc": expected_payload["created_at_utc"],
            "cohort_hash": expected_payload["cohort_hash"],
        }
        if row_payload != expected_columns:
            raise PaperEvaluationReadError("operational cohort contract column mismatch.")
        return contract
