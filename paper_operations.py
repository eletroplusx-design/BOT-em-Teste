from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
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
from validation import WalkForwardResult

import storage


APP_NAME = "paper_operations"
DEFAULT_REFERENCE_FILE = "reference.json"
DEFAULT_DECISION_FILE = "promotion_decision.json"
DEFAULT_POLICY_FILE = "policy.json"
DEFAULT_BACKUP_RETENTION = 7


class PaperOperationsError(Exception):
    pass


def _data_dir(raw: str | Path | None = None) -> Path:
    return resolve_paper_data_dir(raw, allow_temporary=raw is not None)


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


def _load_walk_forward_reference(path: str | Path) -> WalkForwardResult:
    payload = _load_json_file(path, label="walk-forward reference")
    result = _walk_forward_from_payload(payload)
    if result.summary.get("runner_trusted") is not True or result.manifest.get("runner_trusted") is not True:
        raise PaperOperationsError("walk-forward reference must be trusted.")
    execution_contract = result.manifest.get("execution_contract", {})
    if not isinstance(execution_contract, Mapping) or execution_contract.get("paper_only") is not True:
        raise PaperOperationsError("walk-forward reference must remain paper-only.")
    return result


def _load_promotion_decision(path: str | Path) -> PromotionDecision:
    payload = _load_json_file(path, label="promotion decision")
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
    return PromotionDecision(
        status=payload.get("status", PromotionStatus.APPROVED_FOR_MONITORED_PAPER.value),
        frozen_selection=frozen,
        strategy_version=payload.get("strategy_version", frozen.strategy_version),
        symbol=payload.get("symbol", frozen.symbol),
        interval=payload.get("interval", frozen.interval),
        phase5_manifest=dict(payload.get("phase5_manifest", {}) or {}),
        evidence_hash=payload.get("evidence_hash", ""),
        policy_hash=payload.get("policy_hash", ""),
        decision_hash=payload.get("decision_hash", ""),
        criteria_evaluated=criteria,
        reasons=tuple(payload.get("reasons", []) or []),
        recalculated_metrics=dict(payload.get("recalculated_metrics", {}) or {}),
        paper_limits=dict(payload.get("paper_limits", {}) or {}),
        timestamp_utc=datetime.fromisoformat(str(payload.get("timestamp_utc", "")).replace("Z", "+00:00")),
        paper_limits_hash=payload.get("paper_limits_hash", ""),
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
    issues: list[str] = []
    root = paths["root"]
    if live_trading_permitted():
        issues.append("operacao real habilitada em configuracao.")
    ok, config_issues = validate_component_config("telegram")
    if not ok:
        issues.extend(f"telegram: {issue}" for issue in config_issues)
    if not root.exists():
        issues.append("PAPER_DATA_DIR inexistente.")
    elif not root.is_dir():
        issues.append("PAPER_DATA_DIR nao e diretorio.")
    else:
        try:
            test_file = root / ".doctor_write_test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
        except Exception:
            issues.append("PAPER_DATA_DIR nao e gravavel.")
    try:
        usage = shutil.disk_usage(root if root.exists() else Path.cwd())
        if usage.free < 50 * 1024 * 1024:
            issues.append("espaco em disco insuficiente.")
    except Exception:
        issues.append("nao foi possivel verificar espaco em disco.")
    try:
        now_utc = datetime.now(timezone.utc)
        if now_utc.tzinfo is None or now_utc.utcoffset() is None:
            issues.append("relógio UTC indisponível.")
    except Exception:
        issues.append("nao foi possivel verificar o relogio UTC.")

    for label, db_path, tables in (
        ("trades", paths["trades_db"], {"trades", "decision_logs", "paper_trade_outbox"}),
        ("runtime", paths["runtime_db"], {"paper_runtime_meta", "paper_runtime_sessions"}),
        ("campaign", paths["campaign_db"], {"paper_evaluation_campaign_contracts", "paper_evaluation_campaign_reports"}),
    ):
        if db_path.exists():
            try:
                if not _sqlite_integrity_ok(db_path):
                    issues.append(f"{label} database integrity failed.")
                if not _sqlite_schema_ok(db_path, tables):
                    issues.append(f"{label} schema is incomplete.")
            except Exception:
                issues.append(f"{label} database inaccessible.")
    try:
        store = PaperRuntimeStore(paths["runtime_db"])
        active_sessions = store.list_active_sessions() if paths["runtime_db"].exists() else []
        for session in active_sessions[:3]:
            try:
                store.assert_audit_chain(session.session_id)
            except Exception:
                issues.append("audit chain invalid.")
                break
    except Exception:
        issues.append("runtime store unavailable.")
    try:
        load_latest_operational_cohort_contract(paths["runtime_db"])
    except Exception:
        issues.append("operational cohort unavailable.")
    try:
        load_operational_paper_campaign_contract(paths["campaign_db"])
    except Exception:
        issues.append("operational campaign unavailable.")
    ready = not issues
    return {"status": "READY" if ready else "NOT_READY", "issues": tuple(issues), "paths": {k: _sanitize_path(v, root) for k, v in paths.items()}}


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
    _write_json(output, result.as_dict())
    return {"output": str(output), "manifest_hash": result.manifest.get("manifest_hash"), "runner_trusted": result.manifest.get("runner_trusted")}


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
    store = _runtime_store_for(data_dir, runtime_db)
    try:
        session = get_monitored_session(session_id=session_id, store=store)
        if session is not None:
            return session
        if session_id is not None:
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
    try:
        session = create_monitored_session(
            decision,
            session_id=session_id,
            session_started_utc=datetime.now(timezone.utc),
            store=_runtime_store_for(data_dir),
        )
    except Exception:
        session = _load_runtime_session(data_dir=data_dir)
        if session is None:
            raise
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


def backup_create(*, data_dir: str | Path | None = None, backup_name: str | None = None) -> dict[str, Any]:
    paths = _paths(data_dir)
    backup_root = paths["backups_dir"]
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_dir = backup_root / (backup_name or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    backup_dir.mkdir(parents=False, exist_ok=False)
    db_files = [paths["trades_db"], paths["runtime_db"], paths["campaign_db"]]
    copied: list[Path] = []
    for db_file in db_files:
        if not db_file.exists():
            continue
        target = backup_dir / db_file.name
        with sqlite3.connect(db_file) as source_conn, sqlite3.connect(target) as target_conn:
            source_conn.backup(target_conn)
        copied.append(target)
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data_dir": str(paths["root"]),
        "campaign_id": _latest_campaign_id(paths["campaign_db"]),
        "files": {item.name: {"sha256": _hash_file(item)} for item in copied},
        "schema_version": 1,
    }
    _write_json(backup_dir / "manifest.json", manifest)
    return {"backup_dir": str(backup_dir), "files": sorted(item.name for item in copied), "manifest_hash": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest()}


def _latest_campaign_id(campaign_db: Path) -> str | None:
    try:
        snapshot = load_operational_paper_campaign_contract(campaign_db)
        return snapshot.campaign_id
    except Exception:
        return None


def backup_list(*, data_dir: str | Path | None = None) -> dict[str, Any]:
    backup_root = _paths(data_dir)["backups_dir"]
    if not backup_root.exists():
        return {"backups": []}
    backups = []
    for entry in sorted(backup_root.iterdir()):
        if entry.is_dir() and (entry / "manifest.json").exists():
            backups.append(entry.name)
    return {"backups": backups}


def backup_verify(*, backup_dir: str | Path) -> dict[str, Any]:
    backup_path = Path(backup_dir)
    manifest = _load_json_file(backup_path / "manifest.json", label="backup manifest")
    files = manifest.get("files", {})
    if not isinstance(files, Mapping):
        raise PaperOperationsError("backup manifest invalid.")
    for name, expected in files.items():
        db_file = backup_path / name
        if not db_file.exists():
            raise PaperOperationsError("backup file missing.")
        if _hash_file(db_file) != expected.get("sha256"):
            raise PaperOperationsError("backup file hash mismatch.")
        if not _sqlite_integrity_ok(db_file):
            raise PaperOperationsError("backup integrity check failed.")
    return {"backup_dir": str(backup_path), "verified": True}


def restore_verify(*, backup_dir: str | Path) -> dict[str, Any]:
    backup_path = Path(backup_dir)
    backup_verify(backup_dir=backup_path)
    temp_dir = Path(tempfile.mkdtemp(prefix="paper_restore_verify_"))
    try:
        for file_name in ("trades.db", "paper_runtime.db", "paper_evaluation_campaign.db"):
            src = backup_path / file_name
            if src.exists():
                shutil.copy2(src, temp_dir / file_name)
                if not _sqlite_integrity_ok(temp_dir / file_name):
                    raise PaperOperationsError("restore verification integrity failed.")
        return {"restored_to": str(temp_dir), "verified": True}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def report(*, data_dir: str | Path | None = None, campaign_id: str | None = None, session_id: str | None = None) -> dict[str, Any]:
    paths = _paths(data_dir)
    doctor_report = doctor(data_dir=data_dir)
    campaign_snapshot = None
    campaign_error = None
    if campaign_id:
        try:
            campaign_snapshot = campaign_status(campaign_id=campaign_id, campaign_db=paths["campaign_db"])
        except Exception as exc:
            campaign_error = str(exc)
    session_snapshot = None
    session_error = None
    if session_id:
        try:
            session_snapshot = session_status(session_id=session_id, data_dir=data_dir)
        except Exception as exc:
            session_error = str(exc)
    return {
        "doctor": doctor_report,
        "campaign": campaign_snapshot,
        "campaign_error": campaign_error,
        "session": session_snapshot,
        "session_error": session_error,
        "paths": {k: _sanitize_path(v, paths["root"]) for k, v in paths.items()},
        "last_backup": (backup_list(data_dir=data_dir).get("backups") or [None])[-1],
    }


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
