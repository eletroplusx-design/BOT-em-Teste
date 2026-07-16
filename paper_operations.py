from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from config import (
    PAPER_DATA_DIR,
    can_execute_sensitive_telegram_action,
    live_trading_permitted,
    resolve_paper_backup_dir,
    resolve_paper_campaign_db_path,
    resolve_paper_data_dir,
    resolve_paper_runtime_db_path,
    resolve_trades_db_path,
    validate_component_config,
)
from domain.serialization import serialize_value
from paper_runtime import PaperRuntimeSession, PaperRuntimeStore, create_monitored_session, get_monitored_session, load_active_runtime_session, new_session_id
from paper_runtime.errors import PaperRuntimeAuditError, PaperRuntimeSessionError, PaperRuntimeStoreError
from paper_runtime.models import PaperRuntimeState
from paper_evaluation import (
    PaperEvaluationPolicy,
    PaperEvaluationStatus,
    create_operational_paper_campaign,
    evaluate_operational_paper_campaign,
    get_operational_paper_campaign_status,
    load_operational_paper_campaign_contract,
    load_operational_paper_campaign_report,
    persist_operational_paper_campaign_contract,
    persist_operational_paper_campaign_report,
)
from paper_evaluation._operational import (
    OperationalCohortContract,
    ensure_operational_cohort_schema,
    load_latest_operational_cohort_contract,
    persist_operational_cohort_contract,
)
from paper_evaluation.campaign import _walk_forward_from_payload, ensure_operational_paper_campaign_schema
from paper_evaluation.errors import (
    PaperCampaignError,
    PaperCampaignManifestError,
    PaperCampaignPolicyError,
    PaperCampaignReadError,
)
from promotion import PromotionDecision, PromotionPolicy, PromotionStatus, adapt_walk_forward_result, evaluate_promotion
from promotion.errors import PromotionDecisionError, PromotionPolicyError
from validation.artifacts import manifest_hash as validation_manifest_hash
from validation import WalkForwardResult

import storage


APP_NAME = "paper_operations"
DEFAULT_REFERENCE_FILE = "reference.json"
DEFAULT_DECISION_FILE = "promotion_decision.json"
DEFAULT_POLICY_FILE = "policy.json"
DEFAULT_BACKUP_RETENTION = 7
_ALLOW_TEMPORARY_DATA_DIRS_FOR_TESTS = False
_REFERENCE_PROVENANCE_KEY = "operational_provenance"
_REFERENCE_PAYLOAD_KEY = "walk_forward"
_REFERENCE_PROVENANCE_VERSION = 1
_OPERATIONAL_LOCK_FILE = ".paper_operations.lock"
_RESTORE_REPORT_VERSION = 1
_RESTORE_REPORT_TTL_HOURS = 24
_OPERATIONAL_INSTANCE_ID = uuid.uuid4().hex


class PaperOperationsError(Exception):
    pass


def _data_dir(raw: str | Path | None = None) -> Path:
    return resolve_paper_data_dir(raw, allow_temporary=_ALLOW_TEMPORARY_DATA_DIRS_FOR_TESTS)


def _paths(data_dir: str | Path | None = None) -> dict[str, Path]:
    root = _data_dir(data_dir)
    return {
        "root": root,
        "trades_db": root / "trades.db",
        "runtime_db": root / "paper_runtime.db",
        "campaign_db": root / "paper_evaluation_campaign.db",
        "reference_file": root / DEFAULT_REFERENCE_FILE,
        "decision_file": root / DEFAULT_DECISION_FILE,
        "policy_file": root / DEFAULT_POLICY_FILE,
        "backups_dir": root / "backups",
    }


def _sanitize_path(path: Path, base: Path | None = None) -> str:
    try:
        path = path.resolve()
    except Exception:
        return path.name
    if base is not None:
        try:
            return str(path.relative_to(base.resolve()))
        except Exception:
            pass
    return path.name


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_json_file(path: str | Path, *, label: str) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        raise PaperOperationsError(f"{label} file not found.")
    content = file_path.read_text(encoding="utf-8")
    if not content.strip():
        raise PaperOperationsError(f"{label} file is empty.")
    try:
        payload = json.loads(content)
    except Exception as exc:
        raise PaperOperationsError(f"{label} file is invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise PaperOperationsError(f"{label} file must contain a JSON object.")
    return payload


def _require_reference_envelope(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise PaperOperationsError("walk-forward reference file is invalid.")
    provenance = payload.get(_REFERENCE_PROVENANCE_KEY)
    walk_forward_payload = payload.get(_REFERENCE_PAYLOAD_KEY)
    if not isinstance(provenance, Mapping) or not isinstance(walk_forward_payload, Mapping):
        raise PaperOperationsError("walk-forward reference must include operational provenance.")
    if provenance.get("synthetic_test_data") is not False:
        raise PaperOperationsError("walk-forward reference must be operational provenance, not synthetic test data.")
    if provenance.get("version") != _REFERENCE_PROVENANCE_VERSION:
        raise PaperOperationsError("walk-forward reference provenance version is invalid.")
    return provenance, walk_forward_payload


def _lock_file_path(root: Path, *, scope: str) -> Path:
    _ = scope
    return root / _OPERATIONAL_LOCK_FILE


def _sanitized_lock_payload(raw_payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_payload, Mapping):
        raise PaperOperationsError("operational lock requires administrative recovery.")
    required_fields = {"operation", "scope", "pid", "instance_id", "nonce", "created_at_utc"}
    if set(raw_payload) != required_fields:
        raise PaperOperationsError("operational lock requires administrative recovery.")
    operation = raw_payload.get("operation")
    scope = raw_payload.get("scope")
    instance_id = raw_payload.get("instance_id")
    nonce = raw_payload.get("nonce")
    created_at_utc = raw_payload.get("created_at_utc")
    pid = raw_payload.get("pid")
    if any(type(value) is not str or not value.strip() for value in (operation, scope, instance_id, nonce, created_at_utc)):
        raise PaperOperationsError("operational lock requires administrative recovery.")
    try:
        pid_value = int(pid)
    except Exception as exc:
        raise PaperOperationsError("operational lock requires administrative recovery.") from exc
    if pid_value <= 0:
        raise PaperOperationsError("operational lock requires administrative recovery.")
    _parse_utc(created_at_utc)
    return {
        "operation": operation.strip(),
        "scope": scope.strip(),
        "pid": pid_value,
        "instance_id": instance_id.strip(),
        "nonce": nonce.strip(),
        "created_at_utc": created_at_utc.strip(),
    }


def _read_operational_lock(lock_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PaperOperationsError("operational lock requires administrative recovery.") from exc
    return _sanitized_lock_payload(payload)


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return False
                return code.value == 259
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        os.kill(pid, 0)
        return True
    except Exception:
        return False


@contextmanager
def _acquire_operational_lock(root: Path, *, scope: str) -> Any:
    lock_path = _lock_file_path(root, scope=scope)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "operation": scope,
        "scope": scope,
        "pid": os.getpid(),
        "created_at_utc": _utcnow().isoformat().replace("+00:00", "Z"),
        "instance_id": _OPERATIONAL_INSTANCE_ID,
        "nonce": uuid.uuid4().hex,
    }
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        existing = _read_operational_lock(lock_path)
        if existing["pid"] == os.getpid() and existing["instance_id"] == _OPERATIONAL_INSTANCE_ID and existing["scope"] == scope:
            raise PaperOperationsError("operational lock is already held by this process.")
        if _process_is_alive(existing["pid"]):
            raise PaperOperationsError("operational lock is held by another live process.")
        raise PaperOperationsError("operational lock requires administrative recovery.")
    else:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, sort_keys=True)
    try:
        yield lock_path
    finally:
        try:
            if lock_path.exists():
                existing = _read_operational_lock(lock_path)
                if existing.get("pid") == os.getpid() and existing.get("instance_id") == _OPERATIONAL_INSTANCE_ID and existing.get("scope") == scope:
                    lock_path.unlink()
        except Exception:
            pass


def _inspect_operational_lock(root: Path) -> dict[str, Any]:
    lock_path = _lock_file_path(root, scope="global")
    if not lock_path.exists():
        raise PaperOperationsError("operational lock not found.")
    payload = _read_operational_lock(lock_path)
    payload["alive"] = _process_is_alive(payload["pid"])
    return payload


def _recover_operational_lock(root: Path, *, confirm: bool = False) -> dict[str, Any]:
    lock_path = _lock_file_path(root, scope="global")
    if not lock_path.exists():
        raise PaperOperationsError("operational lock not found.")
    try:
        payload = _read_operational_lock(lock_path)
    except PaperOperationsError:
        if not confirm:
            return {"status": "RECOVERY_REQUIRED", "lock": None, "reason": "malformed"}
        lock_path.unlink(missing_ok=True)
        return {"status": "RECOVERED", "lock": None, "reason": "malformed"}
    if payload["pid"] == os.getpid() and payload["instance_id"] == _OPERATIONAL_INSTANCE_ID:
        raise PaperOperationsError("operational lock is held by this process and cannot be recovered.")
    if _process_is_alive(payload["pid"]):
        raise PaperOperationsError("operational lock is still held by a live process.")
    if not confirm:
        return {"status": "RECOVERY_REQUIRED", "lock": payload}
    lock_path.unlink(missing_ok=True)
    return {"status": "RECOVERED", "lock": payload}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_integrity_ok(path: Path) -> bool:
    if not path.exists():
        return False
    with sqlite3.connect(path) as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return bool(row and str(row[0]).strip().upper() == "OK")


def _sqlite_schema_ok(path: Path, tables: set[str]) -> bool:
    if not path.exists():
        return False
    with sqlite3.connect(path) as conn:
        existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return tables.issubset(existing)


def _report_line(label: str, value: Any) -> str:
    return f"{label}: {value}"


def _sanitize_error(exc: Exception) -> str:
    return exc.__class__.__name__


def _load_walk_forward_reference(path: str | Path) -> WalkForwardResult:
    payload = _load_json_file(path, label="walk-forward reference")
    provenance, walk_forward_payload = _require_reference_envelope(payload)
    result = _walk_forward_from_payload(walk_forward_payload)
    if result.summary.get("runner_trusted") is not True or result.manifest.get("runner_trusted") is not True:
        raise PaperOperationsError("walk-forward reference must be trusted.")
    execution_contract = result.manifest.get("execution_contract", {})
    if not isinstance(execution_contract, Mapping) or execution_contract.get("paper_only") is not True:
        raise PaperOperationsError("walk-forward reference must remain paper-only.")
    if provenance.get("manifest_hash") != result.manifest.get("manifest_hash"):
        raise PaperOperationsError("walk-forward reference manifest hash mismatch.")
    if provenance.get("result_hash") != validation_manifest_hash(result.as_dict()):
        raise PaperOperationsError("walk-forward reference result hash mismatch.")
    if provenance.get("data_signature_hash") != result.manifest.get("data_signature", {}).get("content_hash"):
        raise PaperOperationsError("walk-forward reference data signature mismatch.")
    return result


def _load_promotion_decision(path: str | Path) -> PromotionDecision:
    payload = _load_json_file(path, label="promotion decision")
    required_keys = {
        "status",
        "frozen_selection",
        "strategy_version",
        "symbol",
        "interval",
        "phase5_manifest",
        "evidence_hash",
        "policy_hash",
        "decision_hash",
        "criteria_evaluated",
        "reasons",
        "recalculated_metrics",
        "paper_limits",
        "timestamp_utc",
        "paper_limits_hash",
    }
    missing = sorted(required_keys - set(payload))
    extra = sorted(set(payload) - required_keys)
    if missing or extra:
        problems = []
        if missing:
            problems.append(f"missing fields: {', '.join(missing)}")
        if extra:
            problems.append(f"unexpected fields: {', '.join(extra)}")
        raise PaperOperationsError("promotion decision file is invalid: " + "; ".join(problems))
    frozen_selection = payload.get("frozen_selection")
    if not isinstance(frozen_selection, Mapping):
        raise PaperOperationsError("promotion decision file is invalid.")
    from validation.models import CandidateConfig, FrozenSelection
    from promotion import PromotionCriterionResult

    candidate_payload = frozen_selection.get("candidate") or {}
    candidate = CandidateConfig.from_mapping(str(candidate_payload.get("name", "")).strip(), dict(candidate_payload.get("parameters", {}) or {}))
    frozen = FrozenSelection(
        candidate=candidate,
        strategy_version=frozen_selection.get("strategy_version", ""),
        costs=tuple((frozen_selection.get("costs", {}) or {}).items()),
        execution_contract=tuple((frozen_selection.get("execution_contract", {}) or {}).items()),
        symbol=frozen_selection.get("symbol", ""),
        interval=frozen_selection.get("interval", ""),
        frozen_at=datetime.fromisoformat(str(frozen_selection.get("frozen_at", "")).replace("Z", "+00:00")),
        manifest_hash=frozen_selection.get("manifest_hash", ""),
        window_id=frozen_selection.get("window_id", ""),
    )
    criteria = tuple(
        PromotionCriterionResult(
            name=str(item.get("name", "criterion")),
            passed=bool(item.get("passed", False)) if type(item.get("passed")) is bool else False,
            expected=item.get("expected"),
            actual=item.get("actual"),
            reason=str(item.get("reason", "")),
        )
        for item in payload.get("criteria_evaluated", []) or []
    )
    try:
        status = PromotionStatus(payload["status"])
    except Exception as exc:
        raise PaperOperationsError("promotion decision status is invalid.") from exc
    return PromotionDecision(
        status=status,
        frozen_selection=frozen,
        strategy_version=payload["strategy_version"],
        symbol=payload["symbol"],
        interval=payload["interval"],
        phase5_manifest=dict(payload["phase5_manifest"]),
        evidence_hash=payload["evidence_hash"],
        policy_hash=payload["policy_hash"],
        decision_hash=payload["decision_hash"],
        criteria_evaluated=criteria,
        reasons=tuple(payload["reasons"]),
        recalculated_metrics=dict(payload["recalculated_metrics"]),
        paper_limits=dict(payload["paper_limits"]),
        timestamp_utc=_parse_utc(payload["timestamp_utc"]),
        paper_limits_hash=payload["paper_limits_hash"],
    )


def _load_promotion_policy(path: str | Path) -> PromotionPolicy:
    payload = _load_json_file(path, label="policy")
    return PromotionPolicy(**payload)


def _load_campaign_policy(path: str | Path) -> PaperEvaluationPolicy:
    payload = _load_json_file(path, label="campaign policy")
    return PaperEvaluationPolicy(**payload)


def _db_paths(data_dir: str | Path | None = None) -> dict[str, Path]:
    paths = _paths(data_dir)
    return {
        "trades_db": paths["trades_db"],
        "runtime_db": paths["runtime_db"],
        "campaign_db": paths["campaign_db"],
    }


def _runtime_store_for(data_dir: str | Path | None = None, runtime_db: str | Path | None = None) -> PaperRuntimeStore:
    runtime_db_path = Path(runtime_db) if runtime_db is not None else _db_paths(data_dir)["runtime_db"]
    return PaperRuntimeStore(runtime_db_path)


def doctor(*, data_dir: str | Path | None = None) -> dict[str, Any]:
    paths = _paths(data_dir)
    local_issues: list[str] = []
    bot_runtime_issues: list[str] = []
    root = paths["root"]
    if live_trading_permitted():
        local_issues.append("operacao real habilitada em configuracao.")
    if not root.exists():
        local_issues.append("PAPER_DATA_DIR inexistente.")
    elif not root.is_dir():
        local_issues.append("PAPER_DATA_DIR nao e diretorio.")
    else:
        try:
            test_file = root / ".doctor_write_test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
        except Exception:
            local_issues.append("PAPER_DATA_DIR nao e gravavel.")
    try:
        usage = shutil.disk_usage(root if root.exists() else Path.cwd())
        if usage.free < 50 * 1024 * 1024:
            local_issues.append("espaco em disco insuficiente.")
    except Exception:
        local_issues.append("nao foi possivel verificar espaco em disco.")
    try:
        now_utc = datetime.now(timezone.utc)
        if now_utc.tzinfo is None or now_utc.utcoffset() is None:
            local_issues.append("relogio UTC indisponivel.")
    except Exception:
        local_issues.append("nao foi possivel verificar o relogio UTC.")

    for label, db_path, tables in (
        ("trades", paths["trades_db"], {"trades", "decision_logs", "paper_trade_outbox"}),
        ("runtime", paths["runtime_db"], {"paper_runtime_meta", "paper_runtime_sessions"}),
        ("campaign", paths["campaign_db"], {"paper_evaluation_campaign_contracts", "paper_evaluation_campaign_reports"}),
    ):
        if db_path.exists():
            try:
                if not _sqlite_integrity_ok(db_path):
                    local_issues.append(f"{label} database integrity failed.")
                if not _sqlite_schema_ok(db_path, tables):
                    local_issues.append(f"{label} schema is incomplete.")
            except Exception:
                local_issues.append(f"{label} database inaccessible.")
    try:
        store = PaperRuntimeStore(paths["runtime_db"])
        active_sessions = store.list_active_sessions() if paths["runtime_db"].exists() else []
        for session in active_sessions[:3]:
            try:
                store.assert_audit_chain(session.session_id)
            except Exception:
                local_issues.append("audit chain invalid.")
                break
    except Exception:
        local_issues.append("runtime store unavailable.")
    try:
        load_latest_operational_cohort_contract(paths["runtime_db"])
    except Exception:
        local_issues.append("operational cohort unavailable.")
    try:
        load_operational_paper_campaign_contract(paths["campaign_db"])
    except Exception:
        local_issues.append("operational campaign unavailable.")
    try:
        with _acquire_operational_lock(root, scope="doctor_probe"):
            pass
    except Exception:
        local_issues.append("operational lock unavailable.")
    try:
        ok, config_issues = validate_component_config("telegram")
        if not ok:
            bot_runtime_issues.extend(f"telegram: {issue}" for issue in config_issues)
    except Exception:
        bot_runtime_issues.append("telegram configuration unavailable.")
    backups = backup_list(data_dir=data_dir).get("backups") or []
    if not backups:
        local_issues.append("no valid backup available.")
    else:
        try:
            backup_verify(backup_dir=paths["backups_dir"] / backups[-1])
        except Exception:
            local_issues.append("latest backup verification failed.")
    restore_report = _load_last_restore_verify_report(paths["backups_dir"])
    if restore_report is None:
        local_issues.append("recent restore verification unavailable.")
    local_ready = not local_issues
    bot_runtime_ready = not bot_runtime_issues
    return {
        "status": "READY" if local_ready else "NOT_READY",
        "local_operations_ready": local_ready,
        "bot_runtime_ready": bot_runtime_ready,
        "issues": tuple(local_issues + bot_runtime_issues),
        "local_issues": tuple(local_issues),
        "bot_runtime_issues": tuple(bot_runtime_issues),
        "paths": {k: _sanitize_path(v, root) for k, v in paths.items()},
    }


def initialize(*, data_dir: str | Path | None = None, copy_existing_trades: str | Path | None = None) -> dict[str, Any]:
    paths = _paths(data_dir)
    root = paths["root"]
    root.mkdir(parents=True, exist_ok=True)
    paths["backups_dir"].mkdir(parents=True, exist_ok=True)
    if copy_existing_trades is not None:
        source = Path(copy_existing_trades)
        if not source.exists() or not source.is_file():
            raise PaperOperationsError("source trades db not found.")
        if paths["trades_db"].exists():
            raise PaperOperationsError("destination trades db already exists.")
        shutil.copy2(source, paths["trades_db"])
    storage.criar_tabelas(str(paths["trades_db"]))
    storage.inicializar_banco(str(paths["trades_db"]))
    runtime_store = PaperRuntimeStore(paths["runtime_db"])
    runtime_store.initialize()
    ensure_operational_cohort_schema(paths["runtime_db"])
    ensure_operational_paper_campaign_schema(paths["campaign_db"])
    return {"data_dir": str(root), "trades_db": _sanitize_path(paths["trades_db"], root), "runtime_db": _sanitize_path(paths["runtime_db"], root), "campaign_db": _sanitize_path(paths["campaign_db"], root)}


def phase5_reference(*, input_file: str | Path, output_file: str | Path | None = None) -> dict[str, Any]:
    result = _load_walk_forward_reference(input_file)
    output = Path(output_file) if output_file is not None else _paths()["reference_file"]
    envelope = {
        _REFERENCE_PROVENANCE_KEY: {
            "version": _REFERENCE_PROVENANCE_VERSION,
            "synthetic_test_data": False,
            "manifest_hash": result.manifest.get("manifest_hash"),
            "result_hash": validation_manifest_hash(result.as_dict()),
            "data_signature_hash": result.manifest.get("data_signature", {}).get("content_hash"),
        },
        _REFERENCE_PAYLOAD_KEY: result.as_dict(),
    }
    _write_json(output, envelope)
    return {
        "output": str(output),
        "manifest_hash": result.manifest.get("manifest_hash"),
        "runner_trusted": result.manifest.get("runner_trusted"),
        "synthetic_test_data": False,
    }


def promotion_decision(*, reference_file: str | Path, policy_file: str | Path, output_file: str | Path | None = None) -> dict[str, Any]:
    reference = _load_walk_forward_reference(reference_file)
    policy = _load_promotion_policy(policy_file)
    evidence = adapt_walk_forward_result(reference)
    decision = evaluate_promotion(evidence, policy)
    output = Path(output_file) if output_file is not None else _paths()["decision_file"]
    _write_json(output, decision.as_dict())
    return {"output": str(output), "status": decision.status.value, "decision_hash": decision.decision_hash, "paper_limits_hash": decision.paper_limits_hash}


def cohort_prepare(
    *,
    strategy_version: str,
    symbol: str,
    interval: str,
    inclusion_rule: str,
    period_start_utc: str,
    period_end_utc: str,
    runtime_db: str | Path | None = None,
) -> dict[str, Any]:
    runtime_db_path = Path(runtime_db) if runtime_db is not None else _db_paths()["runtime_db"]
    with _acquire_operational_lock(runtime_db_path.parent, scope=f"cohort_prepare:{strategy_version}:{symbol}:{interval}"):
        contract = persist_operational_cohort_contract(
            runtime_db_path,
            strategy_version=strategy_version,
            symbol=symbol,
            interval=interval,
            inclusion_rule=inclusion_rule,
            period_start_utc=_parse_utc(period_start_utc),
            period_end_utc=_parse_utc(period_end_utc),
        )
    return {"cohort_hash": contract.cohort_hash, "runtime_db": str(runtime_db_path)}


def cohort_status(*, runtime_db: str | Path | None = None, cohort_hash: str | None = None) -> dict[str, Any]:
    runtime_db_path = Path(runtime_db) if runtime_db is not None else _db_paths()["runtime_db"]
    contract = load_latest_operational_cohort_contract(runtime_db_path, cohort_hash=cohort_hash)
    return contract.as_dict()


def campaign_prepare(
    *,
    campaign_id: str,
    policy_file: str | Path,
    reference_file: str | Path,
    strategy_version: str,
    symbol: str,
    interval: str,
    inclusion_rule: str,
    period_start_utc: str,
    period_end_utc: str,
    cohort_hash: str | None = None,
    runtime_db: str | Path | None = None,
    campaign_db: str | Path | None = None,
) -> dict[str, Any]:
    policy = _load_campaign_policy(policy_file)
    reference = _load_walk_forward_reference(reference_file)
    runtime_db_path = Path(runtime_db) if runtime_db is not None else _db_paths()["runtime_db"]
    campaign_db_path = Path(campaign_db) if campaign_db is not None else _db_paths()["campaign_db"]
    with _acquire_operational_lock(campaign_db_path.parent, scope=f"campaign_prepare:{campaign_id}"):
        contract = create_operational_paper_campaign(
            campaign_id=campaign_id,
            cohort_hash=cohort_hash,
            strategy_version=strategy_version,
            symbol=symbol,
            interval=interval,
            inclusion_rule=inclusion_rule,
            period_start_utc=_parse_utc(period_start_utc),
            period_end_utc=_parse_utc(period_end_utc),
            policy=policy,
            reference_walk_forward=reference,
            runtime_db_path=runtime_db_path,
            campaign_db_path=campaign_db_path,
        )
    return {"campaign_hash": contract.campaign_hash, "campaign_id": contract.campaign_id}


def campaign_status(*, campaign_id: str, campaign_db: str | Path | None = None) -> dict[str, Any]:
    campaign_db_path = Path(campaign_db) if campaign_db is not None else _db_paths()["campaign_db"]
    snapshot = get_operational_paper_campaign_status(campaign_id=campaign_id, campaign_db_path=campaign_db_path)
    return snapshot.as_dict()


def _load_runtime_session(session_id: str | None = None, *, data_dir: str | Path | None = None, runtime_db: str | Path | None = None):
    if session_id is None:
        return None
    store = _runtime_store_for(data_dir, runtime_db)
    try:
        session = get_monitored_session(session_id=session_id, store=store)
        if session is not None:
            return session
        return PaperRuntimeSession.from_store(session_id, store=store)
    except Exception:
        return None


def session_start(
    *,
    campaign_id: str,
    decision_file: str | Path,
    campaign_db: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    campaign_db_path = Path(campaign_db) if campaign_db is not None else _db_paths(data_dir)["campaign_db"]
    contract = load_operational_paper_campaign_contract(campaign_db_path, campaign_id=campaign_id)
    if not contract.campaign_id:
        raise PaperOperationsError("campaign is invalid.")
    decision = _load_promotion_decision(decision_file)
    if decision.status is not PromotionStatus.APPROVED_FOR_MONITORED_PAPER:
        raise PaperOperationsError("promotion decision is not approved for monitored paper.")
    if decision.strategy_version != contract.strategy_version or decision.symbol != contract.symbol or decision.interval != contract.interval:
        raise PaperOperationsError("promotion decision diverges from campaign scope.")
    session_id = new_session_id()
    with _acquire_operational_lock(_paths(data_dir)["root"], scope=f"session_start:{campaign_id}"):
        session = create_monitored_session(
            decision,
            session_id=session_id,
            session_started_utc=datetime.now(timezone.utc),
            store=_runtime_store_for(data_dir),
        )
    return {"session_id": session.record.session_id if session is not None else session_id, "state": session.record.state.value if session is not None else "N/A"}


def session_status(*, session_id: str | None = None, data_dir: str | Path | None = None) -> dict[str, Any]:
    session = _load_runtime_session(session_id=session_id, data_dir=data_dir)
    if session is None:
        raise PaperOperationsError("runtime session not found.")
    record = session.record
    return {
        "session_id": record.session_id,
        "state": record.state.value,
        "version": record.version,
        "created_at_utc": record.created_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "updated_at_utc": record.updated_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "session_started_utc": record.session_started_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "contract_hash": record.contract_hash,
        "decision_hash": record.decision_hash,
    }


def session_complete(*, session_id: str, reason: str = "completed via paper_operations", data_dir: str | Path | None = None) -> dict[str, Any]:
    session = _load_runtime_session(session_id=session_id, data_dir=data_dir)
    if session is None:
        raise PaperOperationsError("runtime session not found.")
    record = session.complete(reason)
    return {"session_id": record.session_id, "state": record.state.value, "reason": reason}


def runtime_resume(*, session_id: str | None = None, data_dir: str | Path | None = None) -> dict[str, Any]:
    session = _load_runtime_session(session_id=session_id, data_dir=data_dir)
    if session is None:
        raise PaperOperationsError("runtime session not found.")
    session.require_running()
    return {"session_id": session.record.session_id, "state": session.record.state.value, "version": session.record.version}


def _backup_file_hashes(files: list[Path]) -> dict[str, str]:
    return {file.name: _hash_file(file) for file in files if file.exists()}


_BACKUP_REQUIRED_FILES = {"trades.db", "paper_runtime.db", "paper_evaluation_campaign.db"}


def _sanitize_backup_name(name: str | None) -> str:
    if name is None:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if type(name) is not str:
        raise PaperOperationsError("backup_name must be a string.")
    candidate = name.strip()
    if not candidate:
        raise PaperOperationsError("backup_name cannot be empty.")
    if candidate.startswith(("/", "\\")) or ":" in candidate or ".." in Path(candidate).parts:
        raise PaperOperationsError("backup_name must be a simple identifier.")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", candidate):
        raise PaperOperationsError("backup_name must be a simple identifier.")
    return candidate


def _validate_backup_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, Mapping) or not manifest:
        raise PaperOperationsError("backup manifest invalid.")
    required_keys = {"created_at_utc", "data_dir", "campaign_id", "files", "schema_version"}
    missing = sorted(required_keys - set(manifest))
    extra = sorted(set(manifest) - required_keys)
    if missing or extra:
        problems = []
        if missing:
            problems.append(f"missing fields: {', '.join(missing)}")
        if extra:
            problems.append(f"unexpected fields: {', '.join(extra)}")
        raise PaperOperationsError("backup manifest invalid: " + "; ".join(problems))
    created_at = _parse_utc(manifest["created_at_utc"])
    if not isinstance(manifest["data_dir"], str) or not manifest["data_dir"].strip():
        raise PaperOperationsError("backup manifest data_dir is invalid.")
    if any(sep in manifest["data_dir"] for sep in ("/", "\\")) or ":" in manifest["data_dir"]:
        raise PaperOperationsError("backup manifest data_dir must be sanitized.")
    files = manifest["files"]
    if not isinstance(files, Mapping) or not files:
        raise PaperOperationsError("backup manifest files are invalid.")
    if set(files) != _BACKUP_REQUIRED_FILES:
        raise PaperOperationsError("backup manifest must contain exactly the required database files.")
    for name, payload in files.items():
        if not isinstance(payload, Mapping):
            raise PaperOperationsError("backup manifest file entry is invalid.")
        if set(payload) != {"sha256"}:
            raise PaperOperationsError("backup manifest file entry is invalid.")
        sha256 = payload.get("sha256")
        if type(sha256) is not str or not sha256.strip():
            raise PaperOperationsError("backup manifest file hash is invalid.")
    schema_version = manifest["schema_version"]
    if type(schema_version) is not int or schema_version <= 0:
        raise PaperOperationsError("backup manifest schema_version is invalid.")
    campaign_id = manifest["campaign_id"]
    if campaign_id is not None and (type(campaign_id) is not str or not campaign_id.strip()):
        raise PaperOperationsError("backup manifest campaign_id is invalid.")
    return {
        "created_at_utc": created_at,
        "data_dir": manifest["data_dir"].strip(),
        "campaign_id": campaign_id.strip() if isinstance(campaign_id, str) else None,
        "files": dict(files),
        "schema_version": schema_version,
    }


def backup_create(*, data_dir: str | Path | None = None, backup_name: str | None = None) -> dict[str, Any]:
    paths = _paths(data_dir)
    backup_root = paths["backups_dir"]
    backup_root.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_backup_name(backup_name)
    if backup_name is None:
        safe_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final_backup_dir = backup_root / safe_name
    if final_backup_dir.exists():
        raise PaperOperationsError("backup directory already exists.")
    with _acquire_operational_lock(paths["root"], scope="backup_create"):
        db_files = [paths["trades_db"], paths["runtime_db"], paths["campaign_db"]]
        if not all(db_file.exists() for db_file in db_files):
            raise PaperOperationsError("all operational databases must exist before backup.")
        temp_backup_dir = Path(tempfile.mkdtemp(prefix=f".{safe_name}.", dir=backup_root))
        copied: list[Path] = []
        try:
            for db_file in db_files:
                target = temp_backup_dir / db_file.name
                source_conn = sqlite3.connect(db_file)
                target_conn = sqlite3.connect(target)
                try:
                    source_conn.backup(target_conn)
                    target_conn.commit()
                    integrity = target_conn.execute("PRAGMA integrity_check").fetchone()
                    if not integrity or str(integrity[0]).strip().upper() != "OK":
                        raise PaperOperationsError("backup integrity check failed.")
                finally:
                    try:
                        target_conn.close()
                    finally:
                        source_conn.close()
                copied.append(target)
            for sidecar in temp_backup_dir.iterdir():
                if sidecar.is_file() and sidecar.name.endswith(("-wal", "-shm", "-journal")):
                    try:
                        sidecar.unlink()
                    except Exception:
                        pass
            manifest = {
                "created_at_utc": _utcnow().isoformat().replace("+00:00", "Z"),
                "data_dir": paths["root"].name,
                "campaign_id": _latest_campaign_id(paths["campaign_db"]),
                "files": {item.name: {"sha256": _hash_file(item)} for item in copied},
                "schema_version": 1,
            }
            _validate_backup_manifest(manifest)
            manifest_path = temp_backup_dir / "manifest.json"
            _write_json(manifest_path, manifest)
            if hasattr(os, "fsync"):
                try:
                    with manifest_path.open("rb") as handle:
                        os.fsync(handle.fileno())
                except OSError:
                    pass
            shutil.move(str(temp_backup_dir), str(final_backup_dir))
            _apply_backup_retention(backup_root, keep=DEFAULT_BACKUP_RETENTION)
            return {
                "backup_dir": str(final_backup_dir),
                "files": sorted(item.name for item in copied),
                "manifest_hash": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest(),
            }
        except Exception:
            shutil.rmtree(temp_backup_dir, ignore_errors=True)
            raise


def _latest_campaign_id(campaign_db: Path) -> str | None:
    try:
        snapshot = load_operational_paper_campaign_contract(campaign_db)
        return snapshot.campaign_id
    except Exception:
        return None


def _apply_backup_retention(backup_root: Path, *, keep: int) -> None:
    if keep <= 0 or not backup_root.exists():
        return
    backups: list[tuple[datetime, Path]] = []
    for entry in backup_root.iterdir():
        if not entry.is_dir():
            continue
        manifest_path = entry / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = _validate_backup_manifest(_load_json_file(manifest_path, label="backup manifest"))
            for name in _BACKUP_REQUIRED_FILES:
                db_file = entry / name
                if not db_file.exists() or not _sqlite_integrity_ok(db_file):
                    raise PaperOperationsError("backup invalid during retention.")
            backups.append((manifest["created_at_utc"], entry))
        except Exception:
            continue
    backups.sort(key=lambda item: item[0])
    while len(backups) > keep:
        _, entry = backups.pop(0)
        if entry.exists():
            shutil.rmtree(entry, ignore_errors=True)


def backup_list(*, data_dir: str | Path | None = None) -> dict[str, Any]:
    backup_root = _paths(data_dir)["backups_dir"]
    if not backup_root.exists():
        return {"backups": []}
    backups = []
    for entry in sorted(backup_root.iterdir()):
        if entry.is_dir() and (entry / "manifest.json").exists():
            backups.append(entry.name)
    return {"backups": backups}


def _load_last_restore_verify_report(backup_root: Path) -> dict[str, Any] | None:
    report_path = backup_root / ".last_restore_verify.json"
    if not report_path.exists():
        return None
    try:
        report = _load_json_file(report_path, label="restore verification report")
    except Exception:
        return None
    required_keys = {
        "backup_dir",
        "backup_manifest_hash",
        "created_at_utc",
        "database_hashes",
        "expires_at_utc",
        "files",
        "result",
        "verified",
        "verification_version",
    }
    if set(report) != required_keys:
        return None
    if report.get("verified") is not True:
        return None
    if report.get("verification_version") != _RESTORE_REPORT_VERSION:
        return None
    try:
        created_at = _parse_utc(report["created_at_utc"])
        expires_at = _parse_utc(report["expires_at_utc"])
    except Exception:
        return None
    if expires_at <= created_at or _utcnow() > expires_at:
        return None
    backup_dir_name = report["backup_dir"]
    if type(backup_dir_name) is not str or not backup_dir_name.strip():
        return None
    backup_dir = backup_root / backup_dir_name
    if not backup_dir.exists():
        return None
    try:
        verification = backup_verify(backup_dir=backup_dir)
    except Exception:
        return None
    if verification["files"] != report["files"]:
        return None
    if report["backup_manifest_hash"] != _hash_file(backup_dir / "manifest.json"):
        return None
    return report


def _paper_activity_snapshot(paths: Mapping[str, Path]) -> dict[str, Any]:
    trades_db = str(paths["trades_db"])
    open_trades: list[dict[str, Any]] = []
    closed_trades: list[dict[str, Any]] = []
    decision_logs: list[dict[str, Any]] = []
    outbox_pending: list[dict[str, Any]] = []
    issues: list[str] = []
    try:
        open_trades = storage.obter_trades_paper_abertos(db_name=trades_db, strict=True)
    except Exception as exc:
        issues.append(f"open_trades: {exc.__class__.__name__}")
    try:
        closed_trades = storage.obter_ultimos_trades_paper(limite=1000, db_name=trades_db, strict=True)
    except Exception as exc:
        issues.append(f"closed_trades: {exc.__class__.__name__}")
    try:
        decision_logs = storage.buscar_ultimos_decision_logs(limite=1000, modos=("PAPER_SOL", "VIGIA_BTC"), db_name=trades_db, strict=True)
    except Exception as exc:
        issues.append(f"decision_logs: {_sanitize_error(exc)}")
    try:
        outbox_pending = storage.obter_outbox_paper_pendentes(db_name=trades_db, strict=True)
    except Exception as exc:
        issues.append(f"outbox: {_sanitize_error(exc)}")

    def _utc_date(value: Any) -> str | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None or dt.utcoffset() is None:
                return None
            return dt.astimezone(timezone.utc).date().isoformat()
        except Exception:
            return None

    closed_dates = sorted({date for date in (_utc_date(trade.get("fechado_em") or trade.get("timestamp")) for trade in closed_trades) if date})
    log_regimes = sorted({
        str(value).strip().upper()
        for item in decision_logs
        for value in [item.get("regime")]
        if type(value) is str and value.strip()
    })
    last_activity = None
    for source in (decision_logs, closed_trades, open_trades):
        if source:
            candidate = source[0].get("timestamp") or source[0].get("fechado_em") or source[0].get("created_at_utc")
            if candidate:
                last_activity = candidate
                break

    return {
        "open_positions": len(open_trades),
        "closed_trades": len(closed_trades),
        "distinct_days": len(closed_dates),
        "regimes": log_regimes,
        "outbox_pending": len(outbox_pending),
        "last_activity": last_activity,
        "issues": tuple(issues),
    }


def backup_verify(*, backup_dir: str | Path) -> dict[str, Any]:
    backup_path = Path(backup_dir)
    manifest = _validate_backup_manifest(_load_json_file(backup_path / "manifest.json", label="backup manifest"))
    sidecar_suffixes = ("-wal", "-shm", "-journal")
    actual_files = {
        entry.name
        for entry in backup_path.iterdir()
        if entry.is_file() and not entry.name.endswith(sidecar_suffixes)
    }
    allowed_files = set(manifest["files"]) | {"manifest.json"}
    extra_files = sorted(actual_files - allowed_files)
    if extra_files:
        raise PaperOperationsError("backup directory contains unexpected files.")
    for name, expected in manifest["files"].items():
        db_file = backup_path / name
        if not db_file.exists():
            raise PaperOperationsError("backup file missing.")
        if _hash_file(db_file) != expected.get("sha256"):
            raise PaperOperationsError("backup file hash mismatch.")
        if not _sqlite_integrity_ok(db_file):
            raise PaperOperationsError("backup integrity check failed.")
    return {
        "backup_dir": backup_path.name,
        "verified": True,
        "created_at_utc": manifest["created_at_utc"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "campaign_id": manifest["campaign_id"],
        "files": sorted(manifest["files"]),
    }


def restore_verify(*, backup_dir: str | Path) -> dict[str, Any]:
    backup_path = Path(backup_dir)
    verification = backup_verify(backup_dir=backup_path)
    temp_dir = Path(tempfile.mkdtemp(prefix="paper_restore_verify_"))
    try:
        restored_files = []
        restored_hashes: dict[str, str] = {}
        for file_name in _BACKUP_REQUIRED_FILES:
            src = backup_path / file_name
            if not src.exists():
                raise PaperOperationsError("restore verification file missing.")
            target = temp_dir / file_name
            shutil.copy2(src, target)
            if not _sqlite_integrity_ok(target):
                raise PaperOperationsError("restore verification integrity failed.")
            restored_files.append(file_name)
            restored_hashes[file_name] = _hash_file(target)
        verification_report = {
            "backup_dir": backup_path.name,
            "backup_manifest_hash": _hash_file(backup_path / "manifest.json"),
            "created_at_utc": _utcnow().isoformat().replace("+00:00", "Z"),
            "database_hashes": restored_hashes,
            "expires_at_utc": (_utcnow() + timedelta(hours=_RESTORE_REPORT_TTL_HOURS)).isoformat().replace("+00:00", "Z"),
            "files": sorted(restored_files),
            "result": verification,
            "verified": True,
            "verification_version": _RESTORE_REPORT_VERSION,
        }
        _write_json(backup_path.parent / ".last_restore_verify.json", verification_report)
        return verification_report
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _restore_sqlite_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(source)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
        integrity = target_conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity or str(integrity[0]).strip().upper() != "OK":
            raise PaperOperationsError("restore apply integrity failed.")
    finally:
        try:
            target_conn.close()
        finally:
            source_conn.close()


def _backup_current_state(paths: Mapping[str, Path], *, prefix: str) -> Path:
    snapshot_dir = Path(tempfile.mkdtemp(prefix=prefix, dir=paths["backups_dir"]))
    copied_files: list[Path] = []
    try:
        for file_name in _BACKUP_REQUIRED_FILES:
            src = paths["root"] / file_name
            if not src.exists():
                raise PaperOperationsError("current state file missing.")
            target = snapshot_dir / file_name
            source_conn = sqlite3.connect(src)
            target_conn = sqlite3.connect(target)
            try:
                source_conn.backup(target_conn)
                target_conn.commit()
                integrity = target_conn.execute("PRAGMA integrity_check").fetchone()
                if not integrity or str(integrity[0]).strip().upper() != "OK":
                    raise PaperOperationsError("current state backup integrity failed.")
            finally:
                try:
                    target_conn.close()
                finally:
                    source_conn.close()
            copied_files.append(target)
        for sidecar in snapshot_dir.iterdir():
            if sidecar.is_file() and sidecar.name.endswith(("-wal", "-shm", "-journal")):
                try:
                    sidecar.unlink()
                except Exception:
                    pass
        manifest = {
            "created_at_utc": _utcnow().isoformat().replace("+00:00", "Z"),
            "data_dir": paths["root"].name,
            "campaign_id": _latest_campaign_id(paths["campaign_db"]),
            "files": {item.name: {"sha256": _hash_file(item)} for item in copied_files},
            "schema_version": 1,
        }
        _validate_backup_manifest(manifest)
        _write_json(snapshot_dir / "manifest.json", manifest)
        return snapshot_dir
    except Exception:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise


def _restore_snapshot_into_paths(snapshot_dir: Path, paths: Mapping[str, Path]) -> None:
    for file_name in _BACKUP_REQUIRED_FILES:
        _restore_sqlite_file(snapshot_dir / file_name, paths["root"] / file_name)


def restore_apply(*, backup_dir: str | Path, data_dir: str | Path | None = None, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        raise PaperOperationsError("restore apply requires explicit confirmation.")
    backup_path = Path(backup_dir)
    backup_verify(backup_dir=backup_path)
    paths = _paths(data_dir)
    root = paths["root"]
    runtime_store = PaperRuntimeStore(paths["runtime_db"])
    try:
        active_sessions = runtime_store.list_active_sessions() if paths["runtime_db"].exists() else []
    except Exception as exc:
        raise PaperOperationsError("restore apply requires a confirmable inactive runtime.") from exc
    if active_sessions:
        raise PaperOperationsError("restore apply requires an inactive runtime.")
    with _acquire_operational_lock(root, scope="restore_apply"):
        pre_restore_snapshot = _backup_current_state(paths, prefix=".restore_prebackup.")
        staging_dir = Path(tempfile.mkdtemp(prefix=".restore_stage.", dir=paths["backups_dir"]))
        copied_files: list[str] = []
        try:
            for file_name in _BACKUP_REQUIRED_FILES:
                src = backup_path / file_name
                if not src.exists():
                    raise PaperOperationsError("restore source file missing.")
                shutil.copy2(src, staging_dir / file_name)
                if not _sqlite_integrity_ok(staging_dir / file_name):
                    raise PaperOperationsError("restore staging integrity failed.")
                copied_files.append(file_name)
            _restore_snapshot_into_paths(staging_dir, paths)
            result = {
                "restored_from": backup_path.name,
                "restored_files": sorted(copied_files),
                "restored_at_utc": _utcnow().isoformat().replace("+00:00", "Z"),
                "pre_restore_backup": pre_restore_snapshot.name,
            }
            _write_json(paths["backups_dir"] / ".last_restore_apply.json", result)
            return result
        except Exception:
            try:
                _restore_snapshot_into_paths(pre_restore_snapshot, paths)
            except Exception:
                pass
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(pre_restore_snapshot, ignore_errors=True)


def report(*, data_dir: str | Path | None = None, campaign_id: str | None = None, session_id: str | None = None) -> dict[str, Any]:
    paths = _paths(data_dir)
    doctor_report = doctor(data_dir=data_dir)
    activity = _paper_activity_snapshot(paths)
    campaign_snapshot = None
    campaign_error = None
    if campaign_id:
        try:
            campaign_snapshot = campaign_status(campaign_id=campaign_id, campaign_db=paths["campaign_db"])
        except Exception as exc:
            campaign_error = _sanitize_error(exc)
    session_snapshot = None
    session_error = None
    if session_id:
        try:
            session_snapshot = session_status(session_id=session_id, data_dir=data_dir)
        except Exception as exc:
            session_error = _sanitize_error(exc)
    report_payload = {
        "doctor": doctor_report,
        "campaign": campaign_snapshot,
        "campaign_error": campaign_error,
        "session": session_snapshot,
        "session_error": session_error,
        "activity": activity,
        "paths": {k: _sanitize_path(v, paths["root"]) for k, v in paths.items()},
        "last_backup": (backup_list(data_dir=data_dir).get("backups") or [None])[-1],
        "last_restore_verify": _load_last_restore_verify_report(paths["backups_dir"]),
    }
    report_payload["operational_summary"] = {
        "local_operations_ready": doctor_report["local_operations_ready"],
        "bot_runtime_ready": doctor_report["bot_runtime_ready"],
        "period_start": campaign_snapshot.get("period_start_utc") if isinstance(campaign_snapshot, dict) else None,
        "period_end": campaign_snapshot.get("period_end_utc") if isinstance(campaign_snapshot, dict) else None,
        "hours_required": campaign_snapshot.get("min_duration_hours") if isinstance(campaign_snapshot, dict) else None,
        "hours_observed": activity.get("distinct_days", 0) * 24,
        "sessions_observed": activity.get("closed_trades", 0),
        "trades_observed": activity.get("closed_trades", 0) + activity.get("open_positions", 0),
        "regimes_observed": activity.get("regimes", ()),
        "restore_verified": bool(report_payload["last_restore_verify"]),
        "audit_chain": "OK" if not activity.get("issues") else "ISSUES",
    }
    return report_payload


def _parse_utc(text: str) -> datetime:
    dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise PaperOperationsError("timestamp must be timezone-aware.")
    return dt.astimezone(timezone.utc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m paper_operations", description="Local administrative operations for monitored paper trading.")
    parser.add_argument("--data-dir", default=PAPER_DATA_DIR or None, help="Override PAPER_DATA_DIR for this command.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Validate the local operational environment.")

    lock = subparsers.add_parser("lock", help="Inspect or recover the global operational lock.")
    lock_sub = lock.add_subparsers(dest="lock_command", required=True)
    lock_inspect = lock_sub.add_parser("inspect", help="Inspect the current operational lock.")
    lock_inspect.add_argument("--data-dir", default=None)
    lock_recover = lock_sub.add_parser("recover", help="Recover a stale or malformed operational lock.")
    lock_recover.add_argument("--data-dir", default=None)
    lock_recover.add_argument("--confirm", action="store_true", help="Explicitly confirm lock recovery.")

    init_parser = subparsers.add_parser("initialize", help="Create the local operational directories and SQLite schemas.")
    init_parser.add_argument("--copy-existing-trades-db", default=None, help="Optional existing trades.db to copy into PAPER_DATA_DIR.")

    phase5 = subparsers.add_parser("phase5-reference", help="Validate and export a canonical WalkForwardResult reference.")
    phase5.add_argument("--input", required=True, help="Path to a canonical WalkForwardResult JSON file.")
    phase5.add_argument("--output", default=None, help="Output reference JSON path.")

    promotion = subparsers.add_parser("promotion-decision", help="Evaluate a real promotion decision from a trusted reference.")
    promotion.add_argument("--reference-file", required=True)
    promotion.add_argument("--policy-file", required=True)
    promotion.add_argument("--output", default=None)

    cohort = subparsers.add_parser("cohort", help="Manage the frozen operational cohort.")
    cohort_sub = cohort.add_subparsers(dest="cohort_command", required=True)
    cohort_prepare = cohort_sub.add_parser("prepare", help="Persist the operational cohort contract.")
    cohort_prepare.add_argument("--strategy-version", required=True)
    cohort_prepare.add_argument("--symbol", required=True)
    cohort_prepare.add_argument("--interval", required=True)
    cohort_prepare.add_argument("--inclusion-rule", required=True)
    cohort_prepare.add_argument("--period-start-utc", required=True)
    cohort_prepare.add_argument("--period-end-utc", required=True)
    cohort_prepare.add_argument("--runtime-db", default=None)
    cohort_status_parser = cohort_sub.add_parser("status", help="Show the latest operational cohort contract.")
    cohort_status_parser.add_argument("--runtime-db", default=None)
    cohort_status_parser.add_argument("--cohort-hash", default=None)

    campaign = subparsers.add_parser("campaign", help="Manage the operational paper campaign.")
    campaign_sub = campaign.add_subparsers(dest="campaign_command", required=True)
    campaign_prepare = campaign_sub.add_parser("prepare", help="Persist the campaign contract.")
    campaign_prepare.add_argument("--campaign-id", required=True)
    campaign_prepare.add_argument("--policy-file", required=True)
    campaign_prepare.add_argument("--reference-file", required=True)
    campaign_prepare.add_argument("--strategy-version", required=True)
    campaign_prepare.add_argument("--symbol", required=True)
    campaign_prepare.add_argument("--interval", required=True)
    campaign_prepare.add_argument("--inclusion-rule", required=True)
    campaign_prepare.add_argument("--period-start-utc", required=True)
    campaign_prepare.add_argument("--period-end-utc", required=True)
    campaign_prepare.add_argument("--cohort-hash", default=None)
    campaign_prepare.add_argument("--runtime-db", default=None)
    campaign_prepare.add_argument("--campaign-db", default=None)
    campaign_status_parser = campaign_sub.add_parser("status", help="Show the current campaign status.")
    campaign_status_parser.add_argument("--campaign-id", required=True)
    campaign_status_parser.add_argument("--campaign-db", default=None)
    campaign_evaluate = campaign_sub.add_parser("evaluate", help="Evaluate the operational paper campaign.")
    campaign_evaluate.add_argument("--campaign-id", required=True)
    campaign_evaluate.add_argument("--campaign-db", default=None)
    campaign_evaluate.add_argument("--runtime-db", default=None)
    campaign_evaluate.add_argument("--trades-db", default=None)

    session = subparsers.add_parser("session", help="Manage monitored paper runtime sessions.")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    session_start_parser = session_sub.add_parser("start", help="Start a monitored paper session from a decision file.")
    session_start_parser.add_argument("--campaign-id", required=True)
    session_start_parser.add_argument("--decision-file", required=True)
    session_start_parser.add_argument("--campaign-db", default=None)
    session_start_parser.add_argument("--data-dir", default=None)
    session_status_parser = session_sub.add_parser("status", help="Show the current runtime session status.")
    session_status_parser.add_argument("--session-id", default=None)
    session_status_parser.add_argument("--data-dir", default=None)
    session_complete_parser = session_sub.add_parser("complete", help="Complete a running session.")
    session_complete_parser.add_argument("--session-id", required=True)
    session_complete_parser.add_argument("--reason", default="completed via paper_operations")
    session_complete_parser.add_argument("--data-dir", default=None)

    runtime = subparsers.add_parser("runtime", help="Resume or inspect the monitored runtime.")
    runtime_sub = runtime.add_subparsers(dest="runtime_command", required=True)
    runtime_resume = runtime_sub.add_parser("resume", help="Resume a monitored runtime session.")
    runtime_resume.add_argument("--session-id", default=None)
    runtime_resume.add_argument("--data-dir", default=None)

    backup = subparsers.add_parser("backup", help="Create or inspect local backups.")
    backup_sub = backup.add_subparsers(dest="backup_command", required=True)
    backup_create_parser = backup_sub.add_parser("create", help="Create a consistent backup of the operational databases.")
    backup_create_parser.add_argument("--data-dir", default=None)
    backup_create_parser.add_argument("--backup-name", default=None)
    backup_list_parser = backup_sub.add_parser("list", help="List available backups.")
    backup_list_parser.add_argument("--data-dir", default=None)
    backup_verify_parser = backup_sub.add_parser("verify", help="Verify a backup copy.")
    backup_verify_parser.add_argument("--backup-dir", required=True)

    restore = subparsers.add_parser("restore", help="Verify a backup restore in isolation.")
    restore_sub = restore.add_subparsers(dest="restore_command", required=True)
    restore_verify_parser = restore_sub.add_parser("verify", help="Restore a backup into a temp directory and verify it.")
    restore_verify_parser.add_argument("--backup-dir", required=True)
    restore_apply_parser = restore_sub.add_parser("apply", help="Apply a verified backup to the local operational data directory.")
    restore_apply_parser.add_argument("--backup-dir", required=True)
    restore_apply_parser.add_argument("--data-dir", default=None)
    restore_apply_parser.add_argument("--confirm", action="store_true", help="Explicitly confirm restore application.")

    report_parser = subparsers.add_parser("report", help="Show the local paper operation report.")
    report_parser.add_argument("--data-dir", default=None)
    report_parser.add_argument("--campaign-id", default=None)
    report_parser.add_argument("--session-id", default=None)
    return parser


def _print_result(result: Any) -> None:
    print(json.dumps(serialize_value(result), ensure_ascii=False, sort_keys=True, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        data_dir = getattr(args, "data_dir", None)
        if args.command == "doctor":
            _print_result(doctor(data_dir=data_dir))
            return 0
        if args.command == "initialize":
            _print_result(initialize(data_dir=data_dir, copy_existing_trades=args.copy_existing_trades_db))
            return 0
        if args.command == "lock":
            root = _paths(data_dir)["root"]
            if args.lock_command == "inspect":
                _print_result(_inspect_operational_lock(root))
                return 0
            if args.lock_command == "recover":
                _print_result(_recover_operational_lock(root, confirm=args.confirm))
                return 0
        if args.command == "phase5-reference":
            _print_result(phase5_reference(input_file=args.input, output_file=args.output))
            return 0
        if args.command == "promotion-decision":
            _print_result(promotion_decision(reference_file=args.reference_file, policy_file=args.policy_file, output_file=args.output))
            return 0
        if args.command == "cohort":
            if args.cohort_command == "prepare":
                _print_result(cohort_prepare(
                    strategy_version=args.strategy_version,
                    symbol=args.symbol,
                    interval=args.interval,
                    inclusion_rule=args.inclusion_rule,
                    period_start_utc=args.period_start_utc,
                    period_end_utc=args.period_end_utc,
                    runtime_db=args.runtime_db,
                ))
                return 0
            if args.cohort_command == "status":
                _print_result(cohort_status(runtime_db=args.runtime_db, cohort_hash=args.cohort_hash))
                return 0
        if args.command == "campaign":
            if args.campaign_command == "prepare":
                _print_result(campaign_prepare(
                    campaign_id=args.campaign_id,
                    policy_file=args.policy_file,
                    reference_file=args.reference_file,
                    strategy_version=args.strategy_version,
                    symbol=args.symbol,
                    interval=args.interval,
                    inclusion_rule=args.inclusion_rule,
                    period_start_utc=args.period_start_utc,
                    period_end_utc=args.period_end_utc,
                    cohort_hash=args.cohort_hash,
                    runtime_db=args.runtime_db,
                    campaign_db=args.campaign_db,
                ))
                return 0
            if args.campaign_command == "status":
                _print_result(campaign_status(campaign_id=args.campaign_id, campaign_db=args.campaign_db))
                return 0
            if args.campaign_command == "evaluate":
                _print_result({
                    "report": evaluate_operational_paper_campaign(
                        campaign_id=args.campaign_id,
                        campaign_db_path=args.campaign_db or _db_paths(data_dir)["campaign_db"],
                        runtime_db_path=args.runtime_db or _db_paths(data_dir)["runtime_db"],
                        trades_db_path=args.trades_db or _db_paths(data_dir)["trades_db"],
                    ).as_dict()
                })
                return 0
        if args.command == "session":
            if args.session_command == "start":
                _print_result(session_start(
                    campaign_id=args.campaign_id,
                    decision_file=args.decision_file,
                    campaign_db=args.campaign_db,
                    data_dir=args.data_dir,
                ))
                return 0
            if args.session_command == "status":
                _print_result(session_status(session_id=args.session_id, data_dir=args.data_dir))
                return 0
            if args.session_command == "complete":
                _print_result(session_complete(session_id=args.session_id, reason=args.reason, data_dir=args.data_dir))
                return 0
        if args.command == "runtime":
            if args.runtime_command == "resume":
                _print_result(runtime_resume(session_id=args.session_id, data_dir=args.data_dir))
                return 0
        if args.command == "backup":
            if args.backup_command == "create":
                _print_result(backup_create(data_dir=args.data_dir, backup_name=args.backup_name))
                return 0
            if args.backup_command == "list":
                _print_result(backup_list(data_dir=args.data_dir))
                return 0
            if args.backup_command == "verify":
                _print_result(backup_verify(backup_dir=args.backup_dir))
                return 0
        if args.command == "restore" and args.restore_command == "verify":
            _print_result(restore_verify(backup_dir=args.backup_dir))
            return 0
        if args.command == "restore" and args.restore_command == "apply":
            _print_result(restore_apply(backup_dir=args.backup_dir, data_dir=args.data_dir, confirm=args.confirm))
            return 0
        if args.command == "report":
            _print_result(report(data_dir=args.data_dir, campaign_id=args.campaign_id, session_id=args.session_id))
            return 0
        raise PaperOperationsError("unknown command.")
    except (PaperOperationsError, PaperCampaignError, PaperRuntimeSessionError, PaperRuntimeStoreError, PaperRuntimeAuditError, PaperCampaignManifestError, PaperCampaignPolicyError, PaperCampaignReadError, PromotionDecisionError, PromotionPolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("error: paper operations command failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
