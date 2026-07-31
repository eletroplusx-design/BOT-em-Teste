from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from backtesting import BacktestConfig, BacktestResult, LeakFreeBacktestEngine
from backtesting.costs import CostModel
from backtesting.models import IntrabarPolicy, GapPolicy
from domain import Candle, DataSource, Direction, MarketSnapshot, Signal
from domain.serialization import serialize_value

from .errors import HistoricalDataIntegrityError, HistoricalDataValidationError
from .okx_historical import (
    OKX_HISTORICAL_CANDLE_INTERVAL,
    OKX_HISTORICAL_CONFIRM_REQUIRED_VALUE,
    OKX_HISTORICAL_DATASET_CANDLES_FILENAME,
    OKX_HISTORICAL_EXPECTED_CANDLE_COUNT,
    OKX_HISTORICAL_INSTRUMENT,
    OKX_HISTORICAL_MARKET_TYPE,
    OKX_HISTORICAL_MANIFEST_FILENAME,
    OKX_HISTORICAL_PROVIDER_ID,
    OKX_HISTORICAL_PROVIDER_VERSION,
    OKX_HISTORICAL_REQUESTED_END_EXCLUSIVE_UTC,
    OKX_HISTORICAL_REQUESTED_START_INCLUSIVE_UTC,
    OKX_HISTORICAL_SOURCE_NAME,
    OKX_HISTORICAL_SYMBOL,
    OkxHistoricalDataset,
    load_okx_historical_dataset,
    verify_okx_historical_dataset,
)
from .research_artifact_registry_verification import (
    ResearchArtifactRegistryVerificationReport,
    ResearchArtifactRegistryVerificationIntegrityError,
    ResearchArtifactRegistryVerificationValidationError,
    verify_okx_research_artifact_registry,
)
from .offline_research_experiment_authorization import (
    OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_ALLOWED_USE_CASES,
    OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_NON_OPERATIONAL_DECLARATION,
    OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PROHIBITED_USE_CASES,
    OfflineResearchExperimentAuthorization,
)
from .offline_research_strategy_compatibility import (
    OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES,
    OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION,
    OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES,
    OfflineResearchStrategyCompatibilityDecision,
)
from .research_artifact_registry import (
    OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT,
    OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256,
    OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH,
    OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256,
    OKX_RESEARCH_ARTIFACT_INSTRUMENT,
    OKX_RESEARCH_ARTIFACT_MARKET_TYPE,
    OKX_RESEARCH_ARTIFACT_PROVIDER_NAME,
    OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC,
    OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC,
    OKX_RESEARCH_ARTIFACT_SYMBOL,
)
from .research_artifact_registry_verification import (
    ResearchArtifactRegistryVerificationReport,
    verify_okx_research_artifact_registry,
)
from strategies.baseline_a_okx_btc_usdt_research import (
    BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_ALLOWED_USE_CASES,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_LONG_SETUP_DETECTED,
    BASELINE_A_OKX_BTC_USDT_RESEARCH_NON_OPERATIONAL_DECLARATION,
    BaselineAOkxBtcUsdtResearchContract,
    BaselineAOkxBtcUsdtResearchValidationError,
    build_baseline_a_okx_btc_usdt_research_contract,
    evaluate_baseline_a_okx_btc_usdt_research,
)

OFFLINE_RESEARCH_BACKTEST_SCHEMA_VERSION = 1
OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_ID = "phase22b_first_offline_okx_backtest"
OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_PURPOSE = "offline_historical_research"
OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_NON_OPERATIONAL_DECLARATION = (
    "Resultado exclusivamente para pesquisa hist\u00f3rica offline. N\u00e3o constitui evid\u00eancia operacional e n\u00e3o autoriza paper ou live."
)
OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_ALLOWED_USE_CASES: tuple[str, ...] = (
    "offline_historical_research",
)
OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_PROHIBITED_USE_CASES: tuple[str, ...] = (
    "replay",
    "backtest",
    "walk_forward",
    "performance",
    "ranking",
    "paper",
    "live",
    "execution",
    "order_submission",
)
OFFLINE_RESEARCH_BACKTEST_DEFAULT_ENTRY_FEE_RATE = Decimal("0.0004")
OFFLINE_RESEARCH_BACKTEST_DEFAULT_EXIT_FEE_RATE = Decimal("0.0004")
OFFLINE_RESEARCH_BACKTEST_DEFAULT_SPREAD_BPS = Decimal("5")
OFFLINE_RESEARCH_BACKTEST_DEFAULT_SLIPPAGE_BPS = Decimal("5")
OFFLINE_RESEARCH_BACKTEST_DEFAULT_LEVERAGE = Decimal("1")
OFFLINE_RESEARCH_BACKTEST_DEFAULT_INITIAL_CAPITAL = Decimal("10000")
OFFLINE_RESEARCH_BACKTEST_DEFAULT_RISK_PERCENT = Decimal("1")
OFFLINE_RESEARCH_BACKTEST_DEFAULT_INTRABAR_POLICY = IntrabarPolicy.STOP_FIRST
OFFLINE_RESEARCH_BACKTEST_DEFAULT_GAP_POLICY = GapPolicy.OPEN_PRICE


class OfflineResearchBacktestError(Exception):
    pass


class OfflineResearchBacktestValidationError(OfflineResearchBacktestError):
    pass


class OfflineResearchBacktestIntegrityError(OfflineResearchBacktestError):
    pass


def _canonical_json(payload: Any) -> str:
    return json.dumps(serialize_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineResearchBacktestValidationError(f"{field_name} is required.")
    return value.strip()


def _require_hex_digest(value: Any, field_name: str) -> str:
    digest = _require_str(value, field_name).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise OfflineResearchBacktestValidationError(f"{field_name} must be a 64-character hex digest.")
    return digest


def _require_bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise OfflineResearchBacktestValidationError(f"{field_name} must be a boolean.")
    return value


def _require_int(value: Any, field_name: str) -> int:
    if type(value) is bool or not isinstance(value, int):
        raise OfflineResearchBacktestValidationError(f"{field_name} must be an integer.")
    return int(value)


def _require_utc_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise OfflineResearchBacktestValidationError(f"{field_name} must be timezone-aware UTC datetime.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except Exception as exc:  # pragma: no cover - defensive parsing guard
            raise OfflineResearchBacktestValidationError(f"{field_name} must be timezone-aware UTC datetime.") from exc
    if not isinstance(value, datetime):
        raise OfflineResearchBacktestValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfflineResearchBacktestValidationError(f"{field_name} must be timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _require_utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")


def _workspace_tmp_dir(name: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp" / name
    root.mkdir(parents=True, exist_ok=True)
    return root

def _is_temporary_pytest_path(path: Path) -> bool:
    return any(part == ".pytest_tmp" for part in path.parts)

def _ensure_persistent_okx_artifact_path(path: str | Path, *, field_name: str) -> Path:
    artifact_path = Path(path)
    if _is_temporary_pytest_path(artifact_path):
        raise OfflineResearchBacktestValidationError(f"{field_name} must not point to .pytest_tmp.")
    return artifact_path

def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()

def _canonical_external_artifact_ref(value: str | Path) -> str:
    if isinstance(value, Path):
        ref = str(value)
    else:
        ref = _require_str(value, "external_artifact_ref")
    if "://" in ref:
        return ref
    return Path(ref).expanduser().resolve(strict=False).as_posix()


@dataclass(frozen=True, slots=True)
class OkxPersistentResearchArtifactResolution:
    registry_file: Path
    dataset_file: Path
    manifest_file: Path
    registry_report: ResearchArtifactRegistryVerificationReport
    dataset_report: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "registry_file", _ensure_persistent_okx_artifact_path(self.registry_file, field_name="registry_file"))
        object.__setattr__(self, "dataset_file", _ensure_persistent_okx_artifact_path(self.dataset_file, field_name="dataset_file"))
        object.__setattr__(self, "manifest_file", _ensure_persistent_okx_artifact_path(self.manifest_file, field_name="manifest_file"))
        if not isinstance(self.registry_report, ResearchArtifactRegistryVerificationReport):
            raise OfflineResearchBacktestValidationError("registry_report must be a verified research artifact registry report.")
        if not isinstance(self.dataset_report, dict):
            raise OfflineResearchBacktestValidationError("dataset_report must be a mapping.")
        if self.registry_report.historical_research_only is not True:
            raise OfflineResearchBacktestValidationError("historical_research_only must be true.")
        if self.registry_report.operational_evidence is not False:
            raise OfflineResearchBacktestValidationError("operational_evidence must be false.")
        if self.registry_report.paper_promotion_eligible is not False:
            raise OfflineResearchBacktestValidationError("paper_promotion_eligible must be false.")

    @property
    def artifact_root(self) -> Path:
        return self.dataset_file.parent


def resolve_okx_persistent_artifact(
    *,
    registry_file: str | Path,
    dataset_file: str | Path,
    manifest_file: str | Path,
    expected_external_artifact_ref: str | Path | None = None,
) -> OkxPersistentResearchArtifactResolution:
    registry_path = _ensure_persistent_okx_artifact_path(registry_file, field_name="registry_file")
    dataset_path = _ensure_persistent_okx_artifact_path(dataset_file, field_name="dataset_file")
    manifest_path = _ensure_persistent_okx_artifact_path(manifest_file, field_name="manifest_file")

    if not registry_path.exists():
        raise OfflineResearchBacktestValidationError("research artifact registry is missing.")
    if not dataset_path.exists():
        raise OfflineResearchBacktestValidationError("dataset file is missing.")
    if not manifest_path.exists():
        raise OfflineResearchBacktestValidationError("manifest file is missing.")
    if dataset_path.parent != manifest_path.parent:
        raise OfflineResearchBacktestValidationError("dataset and manifest must share the same artifact directory.")

    expected_artifact_ref = _canonical_external_artifact_ref(expected_external_artifact_ref or dataset_path.parent)
    try:
        registry_report = verify_okx_research_artifact_registry(
            registry_path,
            expected_external_artifact_ref=expected_artifact_ref,
        )
    except ResearchArtifactRegistryVerificationIntegrityError as exc:
        raise OfflineResearchBacktestIntegrityError(str(exc)) from exc
    except ResearchArtifactRegistryVerificationValidationError as exc:
        raise OfflineResearchBacktestValidationError(str(exc)) from exc

    artifact_ref = _canonical_external_artifact_ref(registry_report.external_artifact_ref)
    if _is_temporary_pytest_path(Path(artifact_ref)):
        raise OfflineResearchBacktestValidationError("external_artifact_ref must not point to .pytest_tmp.")
    if not Path(artifact_ref).exists():
        raise OfflineResearchBacktestValidationError("external_artifact_ref does not exist.")
    if artifact_ref != _canonical_external_artifact_ref(dataset_path.parent):
        raise OfflineResearchBacktestValidationError("external_artifact_ref must match the dataset artifact directory.")

    try:
        dataset_report = verify_okx_historical_dataset(dataset_file=dataset_path, manifest_file=manifest_path)
    except HistoricalDataIntegrityError as exc:
        raise OfflineResearchBacktestIntegrityError(str(exc)) from exc
    except HistoricalDataValidationError as exc:
        raise OfflineResearchBacktestValidationError(str(exc)) from exc
    if dataset_report["dataset_hash"] != registry_report.dataset_sha256:
        raise OfflineResearchBacktestIntegrityError("dataset_hash must match the verified registry.")
    if dataset_report["manifest_hash"] != registry_report.manifest_hash:
        raise OfflineResearchBacktestIntegrityError("manifest_hash must match the verified registry.")
    if _file_sha256(dataset_path) != registry_report.dataset_sha256:
        raise OfflineResearchBacktestIntegrityError("dataset file hash must match the verified registry.")
    if _file_sha256(manifest_path) != registry_report.manifest_sha256:
        raise OfflineResearchBacktestIntegrityError("manifest file hash must match the verified registry.")
    return OkxPersistentResearchArtifactResolution(
        registry_file=registry_path,
        dataset_file=dataset_path,
        manifest_file=manifest_path,
        registry_report=registry_report,
        dataset_report=dict(dataset_report),
    )


def discover_okx_persistent_artifact_paths(root: str | Path | None = None) -> tuple[Path, Path]:
    search_root = Path(root) if root is not None else Path.home() / ".codex" / "artifacts" / "BOT-em-Teste"
    if _is_temporary_pytest_path(search_root):
        raise OfflineResearchBacktestValidationError("persistent artifact search root must not be .pytest_tmp.")
    if not search_root.exists():
        raise OfflineResearchBacktestValidationError("persistent artifact search root does not exist.")
    registry_candidates = sorted(
        candidate
        for candidate in search_root.rglob("okx-research-artifact-registry.json")
        if not _is_temporary_pytest_path(candidate)
    )
    if not registry_candidates:
        raise OfflineResearchBacktestValidationError("OKX persistent research artifact registry was not found.")
    for registry_file in registry_candidates:
        registry_report = verify_okx_research_artifact_registry(registry_file)
        artifact_dir = Path(registry_report.external_artifact_ref)
        if _is_temporary_pytest_path(artifact_dir):
            raise OfflineResearchBacktestValidationError("persistent artifact directory must not be .pytest_tmp.")
        dataset_file = artifact_dir / OKX_HISTORICAL_DATASET_CANDLES_FILENAME
        manifest_file = artifact_dir / OKX_HISTORICAL_MANIFEST_FILENAME
        if not dataset_file.exists() or not manifest_file.exists():
            continue
        try:
            resolve_okx_persistent_artifact(
                registry_file=registry_file,
                dataset_file=dataset_file,
                manifest_file=manifest_file,
                expected_external_artifact_ref=artifact_dir,
            )
        except OfflineResearchBacktestError:
            continue
        return dataset_file, manifest_file
    raise OfflineResearchBacktestValidationError("OKX persistent research artifact files were not found locally.")


def discover_okx_phase19a_artifact_paths(root: str | Path | None = None) -> tuple[Path, Path]:
    search_root = Path(root) if root is not None else Path(__file__).resolve().parents[1] / ".pytest_tmp"
    candidates: list[tuple[Path, Path]] = []
    for dataset_file in search_root.rglob(OKX_HISTORICAL_DATASET_CANDLES_FILENAME):
        manifest_file = dataset_file.with_name(OKX_HISTORICAL_MANIFEST_FILENAME)
        if manifest_file.exists():
            candidates.append((dataset_file, manifest_file))
    if not candidates:
        raise OfflineResearchBacktestValidationError("OKX Phase 19A artifact files were not found locally.")
    candidates.sort(key=lambda item: (str(item[0]), str(item[1])))
    return candidates[0]


def _require_verified_authorization(authorization: Any) -> OfflineResearchExperimentAuthorization:
    if not isinstance(authorization, OfflineResearchExperimentAuthorization):
        raise OfflineResearchBacktestValidationError("a verified offline research experiment authorization is required.")
    if authorization.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchBacktestValidationError("authorization provider_name must be OKX.")
    if authorization.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchBacktestValidationError("authorization market_type must be spot.")
    if authorization.instrument != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchBacktestValidationError("authorization instrument must be BTC-USDT.")
    if authorization.symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchBacktestValidationError("authorization symbol must be BTCUSDT.")
    if authorization.interval != OKX_HISTORICAL_CANDLE_INTERVAL:
        raise OfflineResearchBacktestValidationError("authorization interval must remain 1H.")
    if authorization.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchBacktestIntegrityError("authorization requested_start_inclusive_utc diverges from the OKX research artifact.")
    if authorization.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise OfflineResearchBacktestIntegrityError("authorization requested_end_exclusive_utc diverges from the OKX research artifact.")
    if authorization.candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchBacktestIntegrityError("authorization candle_count must be 42816.")
    if authorization.dataset_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256:
        raise OfflineResearchBacktestIntegrityError("authorization dataset_sha256 must match the OKX research artifact.")
    if authorization.manifest_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256:
        raise OfflineResearchBacktestIntegrityError("authorization manifest_sha256 must match the OKX research artifact.")
    if authorization.manifest_hash != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH:
        raise OfflineResearchBacktestIntegrityError("authorization manifest_hash must match the OKX research artifact.")
    if authorization.historical_research_only is not True:
        raise OfflineResearchBacktestValidationError("historical_research_only must be true.")
    if authorization.operational_evidence is not False:
        raise OfflineResearchBacktestValidationError("operational_evidence must be false.")
    if authorization.paper_promotion_eligible is not False:
        raise OfflineResearchBacktestValidationError("paper_promotion_eligible must be false.")
    if authorization.allowed_use_cases not in ((), OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_ALLOWED_USE_CASES):
        raise OfflineResearchBacktestValidationError("authorization allowed_use_cases diverges from the research-only contract.")
    if authorization.prohibited_use_cases != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_PROHIBITED_USE_CASES:
        raise OfflineResearchBacktestValidationError("authorization prohibited_use_cases diverge from the research-only contract.")
    if authorization.non_operational_declaration != OFFLINE_RESEARCH_EXPERIMENT_AUTHORIZATION_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchBacktestValidationError("authorization non_operational_declaration diverges from the research-only contract.")
    if not authorization.authorization_hash:
        raise OfflineResearchBacktestIntegrityError("authorization_hash is required.")
    return authorization


def _require_verified_compatibility(
    compatibility_decision: Any,
) -> OfflineResearchStrategyCompatibilityDecision:
    if not isinstance(compatibility_decision, OfflineResearchStrategyCompatibilityDecision):
        raise OfflineResearchBacktestValidationError("a verified offline research compatibility decision is required.")
    if compatibility_decision.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchBacktestValidationError("compatibility provider_name must be OKX.")
    if compatibility_decision.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchBacktestValidationError("compatibility market_type must be spot.")
    if compatibility_decision.symbol != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchBacktestValidationError("compatibility symbol must be BTC-USDT.")
    if compatibility_decision.canonical_symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchBacktestValidationError("compatibility canonical_symbol must be BTCUSDT.")
    if compatibility_decision.interval != "1H":
        raise OfflineResearchBacktestValidationError("compatibility interval must be 1H.")
    if compatibility_decision.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchBacktestIntegrityError("compatibility requested_start_inclusive_utc diverges from the OKX research artifact.")
    if compatibility_decision.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise OfflineResearchBacktestIntegrityError("compatibility requested_end_exclusive_utc diverges from the OKX research artifact.")
    if compatibility_decision.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchBacktestIntegrityError("compatibility expected_candle_count must be 42816.")
    if compatibility_decision.required_dataset_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256:
        raise OfflineResearchBacktestIntegrityError("compatibility required_dataset_sha256 must match the OKX research artifact.")
    if compatibility_decision.required_manifest_sha256 != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256:
        raise OfflineResearchBacktestIntegrityError("compatibility required_manifest_sha256 must match the OKX research artifact.")
    if compatibility_decision.required_manifest_hash != OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH:
        raise OfflineResearchBacktestIntegrityError("compatibility required_manifest_hash must match the OKX research artifact.")
    if compatibility_decision.historical_research_only is not True:
        raise OfflineResearchBacktestValidationError("historical_research_only must be true.")
    if compatibility_decision.operational_evidence is not False:
        raise OfflineResearchBacktestValidationError("operational_evidence must be false.")
    if compatibility_decision.paper_promotion_eligible is not False:
        raise OfflineResearchBacktestValidationError("paper_promotion_eligible must be false.")
    if compatibility_decision.allowed_use_cases not in ((), OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_ALLOWED_USE_CASES):
        raise OfflineResearchBacktestValidationError("compatibility allowed_use_cases diverges from the research-only contract.")
    if compatibility_decision.prohibited_use_cases != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_PROHIBITED_USE_CASES:
        raise OfflineResearchBacktestValidationError("compatibility prohibited_use_cases diverge from the research-only contract.")
    if compatibility_decision.non_operational_declaration != OFFLINE_RESEARCH_STRATEGY_COMPATIBILITY_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchBacktestValidationError("compatibility non_operational_declaration diverges from the research-only contract.")
    if not compatibility_decision.compatibility_hash:
        raise OfflineResearchBacktestIntegrityError("compatibility_hash is required.")
    return compatibility_decision


def _require_strategy_contract(
    strategy_contract: Any,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
) -> BaselineAOkxBtcUsdtResearchContract:
    if not isinstance(strategy_contract, BaselineAOkxBtcUsdtResearchContract):
        raise OfflineResearchBacktestValidationError("baseline A strategy contract is required.")
    if strategy_contract.strategy_id != "baseline_a_okx_btc_usdt_1h_research":
        raise OfflineResearchBacktestValidationError("strategy_id must be baseline_a_okx_btc_usdt_1h_research.")
    if strategy_contract.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchBacktestValidationError("strategy provider_name must be OKX.")
    if strategy_contract.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchBacktestValidationError("strategy market_type must be spot.")
    if strategy_contract.symbol != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchBacktestValidationError("strategy symbol must be BTC-USDT.")
    if strategy_contract.canonical_symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchBacktestValidationError("strategy canonical_symbol must be BTCUSDT.")
    if strategy_contract.interval != "1H":
        raise OfflineResearchBacktestValidationError("strategy interval must be 1H.")
    if strategy_contract.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchBacktestIntegrityError("strategy requested_start_inclusive_utc diverges from the OKX research artifact.")
    if strategy_contract.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
        raise OfflineResearchBacktestIntegrityError("strategy requested_end_exclusive_utc diverges from the OKX research artifact.")
    if strategy_contract.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchBacktestIntegrityError("strategy expected_candle_count must be 42816.")
    if strategy_contract.required_authorization_hash != authorization.authorization_hash:
        raise OfflineResearchBacktestIntegrityError("strategy required_authorization_hash diverges from the verified authorization.")
    if strategy_contract.required_compatibility_hash != compatibility_decision.compatibility_hash:
        raise OfflineResearchBacktestIntegrityError("strategy required_compatibility_hash diverges from the verified compatibility decision.")
    if strategy_contract.historical_research_only is not True:
        raise OfflineResearchBacktestValidationError("historical_research_only must be true.")
    if strategy_contract.operational_evidence is not False:
        raise OfflineResearchBacktestValidationError("operational_evidence must be false.")
    if strategy_contract.paper_promotion_eligible is not False:
        raise OfflineResearchBacktestValidationError("paper_promotion_eligible must be false.")
    if strategy_contract.allowed_use_cases != BASELINE_A_OKX_BTC_USDT_RESEARCH_CONTRACT_ALLOWED_USE_CASES:
        raise OfflineResearchBacktestValidationError("strategy allowed_use_cases diverge from the research-only contract.")
    if strategy_contract.prohibited_use_cases != OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_PROHIBITED_USE_CASES:
        raise OfflineResearchBacktestValidationError("strategy prohibited_use_cases diverge from the research-only contract.")
    if strategy_contract.non_operational_declaration != BASELINE_A_OKX_BTC_USDT_RESEARCH_NON_OPERATIONAL_DECLARATION:
        raise OfflineResearchBacktestValidationError("strategy non_operational_declaration diverges from the research-only contract.")
    if not strategy_contract.contract_hash:
        raise OfflineResearchBacktestIntegrityError("strategy contract_hash is required.")
    return strategy_contract


def _project_candle_to_research_surface(candle: Candle, *, symbol: str) -> Candle:
    return Candle.from_dict(
        {
            "open_time": candle.open_time,
            "close_time": candle.close_time,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
            "symbol": symbol,
            "interval": candle.interval,
            "source": DataSource.PAPER,
        }
    )


def _project_dataset_to_research_surface(dataset: OkxHistoricalDataset, *, symbol: str) -> tuple[Candle, ...]:
    return tuple(_project_candle_to_research_surface(candle, symbol=symbol) for candle in dataset.candles)


def _load_okx_dataset(dataset_file: str | Path, manifest_file: str | Path) -> OkxHistoricalDataset:
    try:
        return load_okx_historical_dataset(dataset_file=dataset_file, manifest_file=manifest_file)
    except (HistoricalDataValidationError, HistoricalDataIntegrityError) as exc:
        raise OfflineResearchBacktestValidationError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class OfflineResearchBacktestExperimentCosts:
    entry_fee_rate: Decimal = OFFLINE_RESEARCH_BACKTEST_DEFAULT_ENTRY_FEE_RATE
    exit_fee_rate: Decimal = OFFLINE_RESEARCH_BACKTEST_DEFAULT_EXIT_FEE_RATE
    spread_bps: Decimal = OFFLINE_RESEARCH_BACKTEST_DEFAULT_SPREAD_BPS
    slippage_bps: Decimal = OFFLINE_RESEARCH_BACKTEST_DEFAULT_SLIPPAGE_BPS
    leverage: Decimal = OFFLINE_RESEARCH_BACKTEST_DEFAULT_LEVERAGE
    initial_capital: Decimal = OFFLINE_RESEARCH_BACKTEST_DEFAULT_INITIAL_CAPITAL
    risk_percent: Decimal = OFFLINE_RESEARCH_BACKTEST_DEFAULT_RISK_PERCENT
    paper_only: bool = True
    allow_short: bool = False
    intrabar_policy: IntrabarPolicy = OFFLINE_RESEARCH_BACKTEST_DEFAULT_INTRABAR_POLICY
    gap_policy: GapPolicy = OFFLINE_RESEARCH_BACKTEST_DEFAULT_GAP_POLICY

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_fee_rate", Decimal(str(self.entry_fee_rate)))
        object.__setattr__(self, "exit_fee_rate", Decimal(str(self.exit_fee_rate)))
        object.__setattr__(self, "spread_bps", Decimal(str(self.spread_bps)))
        object.__setattr__(self, "slippage_bps", Decimal(str(self.slippage_bps)))
        object.__setattr__(self, "leverage", Decimal(str(self.leverage)))
        object.__setattr__(self, "initial_capital", Decimal(str(self.initial_capital)))
        object.__setattr__(self, "risk_percent", Decimal(str(self.risk_percent)))
        _require_bool(self.paper_only, "paper_only")
        _require_bool(self.allow_short, "allow_short")
        if self.paper_only is not True:
            raise OfflineResearchBacktestValidationError("paper_only must be true.")
        if self.allow_short is not False:
            raise OfflineResearchBacktestValidationError("allow_short must be false.")
        if self.leverage <= 0:
            raise OfflineResearchBacktestValidationError("leverage must be greater than zero.")
        if self.risk_percent <= 0:
            raise OfflineResearchBacktestValidationError("risk_percent must be greater than zero.")
        if not isinstance(self.intrabar_policy, IntrabarPolicy):
            raise OfflineResearchBacktestValidationError("intrabar_policy is invalid.")
        if not isinstance(self.gap_policy, GapPolicy):
            raise OfflineResearchBacktestValidationError("gap_policy is invalid.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_fee_rate": str(self.entry_fee_rate),
            "exit_fee_rate": str(self.exit_fee_rate),
            "spread_bps": str(self.spread_bps),
            "slippage_bps": str(self.slippage_bps),
            "leverage": str(self.leverage),
            "initial_capital": str(self.initial_capital),
            "risk_percent": str(self.risk_percent),
            "paper_only": self.paper_only,
            "allow_short": self.allow_short,
            "intrabar_policy": self.intrabar_policy.value,
            "gap_policy": self.gap_policy.value,
        }


@dataclass(frozen=True, slots=True)
class OfflineResearchBacktestExperimentContract:
    schema_version: int
    experiment_id: str
    experiment_version: str
    executed_at_utc: datetime
    strategy_id: str
    strategy_version: str
    provider_name: str
    market_type: str
    symbol: str
    canonical_symbol: str
    interval: str
    requested_start_inclusive_utc: datetime
    requested_end_exclusive_utc: datetime
    expected_candle_count: int
    authorization_hash: str
    compatibility_hash: str
    strategy_contract_hash: str
    dataset_contract_hash: str
    dataset_hash: str
    manifest_hash: str
    historical_research_only: bool
    operational_evidence: bool
    paper_promotion_eligible: bool
    allowed_use_cases: tuple[str, ...]
    prohibited_use_cases: tuple[str, ...]
    non_operational_declaration: str
    costs: OfflineResearchBacktestExperimentCosts
    experiment_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _require_int(self.schema_version, "schema_version"))
        object.__setattr__(self, "experiment_id", _require_str(self.experiment_id, "experiment_id"))
        object.__setattr__(self, "experiment_version", _require_str(self.experiment_version, "experiment_version"))
        object.__setattr__(self, "executed_at_utc", _require_utc_datetime(self.executed_at_utc, "executed_at_utc"))
        object.__setattr__(self, "strategy_id", _require_str(self.strategy_id, "strategy_id"))
        object.__setattr__(self, "strategy_version", _require_str(self.strategy_version, "strategy_version"))
        object.__setattr__(self, "provider_name", _require_str(self.provider_name, "provider_name").upper())
        object.__setattr__(self, "market_type", _require_str(self.market_type, "market_type").lower())
        object.__setattr__(self, "symbol", _require_str(self.symbol, "symbol").upper())
        object.__setattr__(self, "canonical_symbol", _require_str(self.canonical_symbol, "canonical_symbol").upper())
        object.__setattr__(self, "interval", _require_str(self.interval, "interval"))
        object.__setattr__(self, "requested_start_inclusive_utc", _require_utc_datetime(self.requested_start_inclusive_utc, "requested_start_inclusive_utc"))
        object.__setattr__(self, "requested_end_exclusive_utc", _require_utc_datetime(self.requested_end_exclusive_utc, "requested_end_exclusive_utc"))
        object.__setattr__(self, "expected_candle_count", _require_int(self.expected_candle_count, "expected_candle_count"))
        object.__setattr__(self, "authorization_hash", _require_hex_digest(self.authorization_hash, "authorization_hash"))
        object.__setattr__(self, "compatibility_hash", _require_hex_digest(self.compatibility_hash, "compatibility_hash"))
        object.__setattr__(self, "strategy_contract_hash", _require_hex_digest(self.strategy_contract_hash, "strategy_contract_hash"))
        object.__setattr__(self, "dataset_contract_hash", _require_hex_digest(self.dataset_contract_hash, "dataset_contract_hash"))
        object.__setattr__(self, "dataset_hash", _require_hex_digest(self.dataset_hash, "dataset_hash"))
        object.__setattr__(self, "manifest_hash", _require_hex_digest(self.manifest_hash, "manifest_hash"))
        object.__setattr__(self, "historical_research_only", _require_bool(self.historical_research_only, "historical_research_only"))
        object.__setattr__(self, "operational_evidence", _require_bool(self.operational_evidence, "operational_evidence"))
        object.__setattr__(self, "paper_promotion_eligible", _require_bool(self.paper_promotion_eligible, "paper_promotion_eligible"))
        object.__setattr__(self, "allowed_use_cases", tuple(dict.fromkeys(_require_str(item, "allowed_use_case").lower() for item in self.allowed_use_cases)))
        object.__setattr__(self, "prohibited_use_cases", tuple(dict.fromkeys(_require_str(item, "prohibited_use_case").lower() for item in self.prohibited_use_cases)))
        object.__setattr__(self, "non_operational_declaration", _require_str(self.non_operational_declaration, "non_operational_declaration"))
        if self.schema_version != OFFLINE_RESEARCH_BACKTEST_SCHEMA_VERSION:
            raise OfflineResearchBacktestValidationError("schema_version must be 1.")
        if self.experiment_id != OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_ID:
            raise OfflineResearchBacktestValidationError("experiment_id must remain phase22b_first_offline_okx_backtest.")
        if self.provider_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
            raise OfflineResearchBacktestValidationError("provider_name must be OKX.")
        if self.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
            raise OfflineResearchBacktestValidationError("market_type must be spot.")
        if self.symbol != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
            raise OfflineResearchBacktestValidationError("symbol must be BTC-USDT.")
        if self.canonical_symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
            raise OfflineResearchBacktestValidationError("canonical_symbol must be BTCUSDT.")
        if self.interval != OKX_HISTORICAL_CANDLE_INTERVAL:
            raise OfflineResearchBacktestValidationError("interval must be 1H.")
        if self.requested_start_inclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
            raise OfflineResearchBacktestIntegrityError("requested_start_inclusive_utc diverges from the OKX research artifact.")
        if self.requested_end_exclusive_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC:
            raise OfflineResearchBacktestIntegrityError("requested_end_exclusive_utc diverges from the OKX research artifact.")
        if self.expected_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
            raise OfflineResearchBacktestIntegrityError("expected_candle_count must be 42816.")
        if self.historical_research_only is not True:
            raise OfflineResearchBacktestValidationError("historical_research_only must be true.")
        if self.operational_evidence is not False:
            raise OfflineResearchBacktestValidationError("operational_evidence must be false.")
        if self.paper_promotion_eligible is not False:
            raise OfflineResearchBacktestValidationError("paper_promotion_eligible must be false.")
        if self.allowed_use_cases != OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_ALLOWED_USE_CASES:
            raise OfflineResearchBacktestValidationError("allowed_use_cases must remain offline_historical_research only.")
        if self.prohibited_use_cases != OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_PROHIBITED_USE_CASES:
            raise OfflineResearchBacktestValidationError("prohibited_use_cases must remain locked to operational use cases.")
        if self.non_operational_declaration != OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchBacktestValidationError("non_operational_declaration diverges from the research-only contract.")
        expected_hash = _hash_payload(self.canonical_payload(include_experiment_hash=False))
        if self.experiment_hash:
            if self.experiment_hash != expected_hash:
                raise OfflineResearchBacktestIntegrityError("experiment_hash mismatch.")
        else:
            object.__setattr__(self, "experiment_hash", expected_hash)

    def canonical_payload(self, *, include_experiment_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "experiment_version": self.experiment_version,
            "executed_at_utc": _utc_iso(self.executed_at_utc),
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "provider_name": self.provider_name,
            "market_type": self.market_type,
            "symbol": self.symbol,
            "canonical_symbol": self.canonical_symbol,
            "interval": self.interval,
            "requested_start_inclusive_utc": _utc_iso(self.requested_start_inclusive_utc),
            "requested_end_exclusive_utc": _utc_iso(self.requested_end_exclusive_utc),
            "expected_candle_count": self.expected_candle_count,
            "authorization_hash": self.authorization_hash,
            "compatibility_hash": self.compatibility_hash,
            "strategy_contract_hash": self.strategy_contract_hash,
            "dataset_contract_hash": self.dataset_contract_hash,
            "dataset_hash": self.dataset_hash,
            "manifest_hash": self.manifest_hash,
            "historical_research_only": self.historical_research_only,
            "operational_evidence": self.operational_evidence,
            "paper_promotion_eligible": self.paper_promotion_eligible,
            "allowed_use_cases": self.allowed_use_cases,
            "prohibited_use_cases": self.prohibited_use_cases,
            "non_operational_declaration": self.non_operational_declaration,
            "costs": self.costs.as_dict(),
        }
        if include_experiment_hash:
            payload["experiment_hash"] = self.experiment_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_experiment_hash=True))


@dataclass(frozen=True, slots=True)
class OfflineResearchBacktestExperimentReport:
    experiment: OfflineResearchBacktestExperimentContract
    dataset_file: str
    manifest_file: str
    analysis_start_utc: datetime
    analysis_end_utc: datetime
    projected_symbol: str
    projected_source: str
    result: BacktestResult
    report_notice: str = OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_NON_OPERATIONAL_DECLARATION
    report_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_file", _require_str(self.dataset_file, "dataset_file"))
        object.__setattr__(self, "manifest_file", _require_str(self.manifest_file, "manifest_file"))
        object.__setattr__(self, "analysis_start_utc", _require_utc_datetime(self.analysis_start_utc, "analysis_start_utc"))
        object.__setattr__(self, "analysis_end_utc", _require_utc_datetime(self.analysis_end_utc, "analysis_end_utc"))
        object.__setattr__(self, "projected_symbol", _require_str(self.projected_symbol, "projected_symbol").upper())
        object.__setattr__(self, "projected_source", _require_str(self.projected_source, "projected_source"))
        if self.report_notice != OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_NON_OPERATIONAL_DECLARATION:
            raise OfflineResearchBacktestValidationError("report_notice must remain research-only.")
        expected_hash = _hash_payload(self.canonical_payload(include_report_hash=False))
        if self.report_hash:
            if self.report_hash != expected_hash:
                raise OfflineResearchBacktestIntegrityError("report_hash mismatch.")
        else:
            object.__setattr__(self, "report_hash", expected_hash)

    @property
    def metrics(self) -> Mapping[str, Any]:
        return self.result.summary

    def canonical_payload(self, *, include_report_hash: bool = True) -> dict[str, Any]:
        payload = {
            "experiment": self.experiment.as_dict(),
            "dataset_file": self.dataset_file,
            "manifest_file": self.manifest_file,
            "analysis_start_utc": _utc_iso(self.analysis_start_utc),
            "analysis_end_utc": _utc_iso(self.analysis_end_utc),
            "projected_symbol": self.projected_symbol,
            "projected_source": self.projected_source,
            "result": self.result.to_dict(),
            "report_notice": self.report_notice,
        }
        if include_report_hash:
            payload["report_hash"] = self.report_hash
        return payload

    def as_dict(self) -> dict[str, Any]:
        return serialize_value(self.canonical_payload(include_report_hash=True))


class OfflineResearchBacktestRunner:
    def __init__(self, *, config: BacktestConfig | None = None, cost_model: CostModel | None = None):
        self.config = config or BacktestConfig(
            initial_capital=OFFLINE_RESEARCH_BACKTEST_DEFAULT_INITIAL_CAPITAL,
            risk_percent=OFFLINE_RESEARCH_BACKTEST_DEFAULT_RISK_PERCENT,
            entry_fee_rate=OFFLINE_RESEARCH_BACKTEST_DEFAULT_ENTRY_FEE_RATE,
            exit_fee_rate=OFFLINE_RESEARCH_BACKTEST_DEFAULT_EXIT_FEE_RATE,
            spread_bps=OFFLINE_RESEARCH_BACKTEST_DEFAULT_SPREAD_BPS,
            slippage_bps=OFFLINE_RESEARCH_BACKTEST_DEFAULT_SLIPPAGE_BPS,
            leverage=OFFLINE_RESEARCH_BACKTEST_DEFAULT_LEVERAGE,
            symbol=OKX_RESEARCH_ARTIFACT_INSTRUMENT,
            interval=OKX_HISTORICAL_CANDLE_INTERVAL,
            paper_only=True,
            allow_short=False,
            intrabar_policy=OFFLINE_RESEARCH_BACKTEST_DEFAULT_INTRABAR_POLICY,
            gap_policy=OFFLINE_RESEARCH_BACKTEST_DEFAULT_GAP_POLICY,
            close_open_positions_at_end=True,
            strategy_version="baseline_a_okx_btc_usdt_1h_research_v1",
        )
        self.cost_model = cost_model or CostModel(
            entry_fee_rate=self.config.entry_fee_rate,
            exit_fee_rate=self.config.exit_fee_rate,
            spread_bps=self.config.spread_bps,
            slippage_bps=self.config.slippage_bps,
        )
        self.engine = LeakFreeBacktestEngine(config=self.config, cost_model=self.cost_model)

    def run(
        self,
        candles: Sequence[Candle],
        strategy_callable: Callable[[Sequence[Candle], object], Signal | None],
    ) -> BacktestResult:
        if self.config.paper_only is not True:
            raise OfflineResearchBacktestValidationError("paper_only must remain true.")
        if self.config.allow_short is not False:
            raise OfflineResearchBacktestValidationError("allow_short must remain false.")
        return self.engine.run(candles, strategy_callable)


def build_offline_research_backtest_experiment_contract(
    *,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    strategy_contract: BaselineAOkxBtcUsdtResearchContract,
    dataset: OkxHistoricalDataset,
    costs: OfflineResearchBacktestExperimentCosts | None = None,
    executed_at_utc: datetime | None = None,
) -> OfflineResearchBacktestExperimentContract:
    authorization = _require_verified_authorization(authorization)
    compatibility_decision = _require_verified_compatibility(compatibility_decision)
    strategy_contract = _require_strategy_contract(strategy_contract, authorization, compatibility_decision)
    if not isinstance(dataset, OkxHistoricalDataset):
        raise OfflineResearchBacktestValidationError("OKX historical dataset is required.")

    manifest = dataset.manifest
    contract = manifest.contract
    if contract.source_name != OKX_RESEARCH_ARTIFACT_PROVIDER_NAME:
        raise OfflineResearchBacktestValidationError("dataset provider must be OKX.")
    if contract.provider_id != OKX_HISTORICAL_PROVIDER_ID:
        raise OfflineResearchBacktestValidationError("dataset provider_id must be okx.public.klines.")
    if contract.provider_version != OKX_HISTORICAL_PROVIDER_VERSION:
        raise OfflineResearchBacktestValidationError("dataset provider_version must be v1.")
    if contract.market_type != OKX_RESEARCH_ARTIFACT_MARKET_TYPE:
        raise OfflineResearchBacktestValidationError("dataset market_type must be spot.")
    if contract.instrument != OKX_RESEARCH_ARTIFACT_INSTRUMENT:
        raise OfflineResearchBacktestValidationError("dataset instrument must be BTC-USDT.")
    if contract.symbol != OKX_RESEARCH_ARTIFACT_SYMBOL:
        raise OfflineResearchBacktestValidationError("dataset symbol must be BTCUSDT.")
    if contract.interval != OKX_HISTORICAL_CANDLE_INTERVAL:
        raise OfflineResearchBacktestValidationError("dataset interval must be 1H.")
    if contract.confirm_required_value != OKX_HISTORICAL_CONFIRM_REQUIRED_VALUE:
        raise OfflineResearchBacktestValidationError("dataset confirm_required_value must be 1.")
    if contract.historical_research_only is not True:
        raise OfflineResearchBacktestValidationError("dataset historical_research_only must be true.")
    if contract.operational_evidence is not False:
        raise OfflineResearchBacktestValidationError("dataset operational_evidence must be false.")
    if contract.paper_promotion_eligible is not False:
        raise OfflineResearchBacktestValidationError("dataset paper_promotion_eligible must be false.")
    if manifest.found_candle_count != OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchBacktestIntegrityError("dataset found_candle_count must be 42816.")
    if manifest.first_candle_open_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchBacktestIntegrityError("dataset first_candle_open_utc diverges from the OKX research artifact.")
    if manifest.last_candle_close_utc != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC - timedelta(milliseconds=1):
        raise OfflineResearchBacktestIntegrityError("dataset last_candle_close_utc diverges from the OKX research artifact.")
    if not dataset.candles:
        raise OfflineResearchBacktestValidationError("dataset must contain candles.")
    if len(dataset.candles) != OKX_HISTORICAL_EXPECTED_CANDLE_COUNT:
        raise OfflineResearchBacktestIntegrityError("dataset must contain 42816 candles.")
    if dataset.candles[0].open_time != OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC:
        raise OfflineResearchBacktestIntegrityError("dataset start time diverges from the OKX research artifact.")
    if dataset.candles[-1].close_time != OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC - timedelta(milliseconds=1):
        raise OfflineResearchBacktestIntegrityError("dataset end time diverges from the OKX research artifact.")
    if costs is None:
        costs = OfflineResearchBacktestExperimentCosts()
    if executed_at_utc is None:
        executed_at_utc = compatibility_decision.decision_at_utc
    return OfflineResearchBacktestExperimentContract(
        schema_version=OFFLINE_RESEARCH_BACKTEST_SCHEMA_VERSION,
        experiment_id=OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_ID,
        experiment_version="phase22b_first_offline_okx_backtest_v1",
        executed_at_utc=executed_at_utc,
        strategy_id=strategy_contract.strategy_id,
        strategy_version=strategy_contract.strategy_version,
        provider_name=contract.source_name,
        market_type=contract.market_type,
        symbol=strategy_contract.symbol,
        canonical_symbol=strategy_contract.canonical_symbol,
        interval=strategy_contract.interval,
        requested_start_inclusive_utc=manifest.first_candle_open_utc,
        requested_end_exclusive_utc=manifest.last_candle_close_utc + timedelta(milliseconds=1),
        expected_candle_count=manifest.found_candle_count,
        authorization_hash=authorization.authorization_hash,
        compatibility_hash=compatibility_decision.compatibility_hash,
        strategy_contract_hash=strategy_contract.contract_hash,
        dataset_contract_hash=contract.contract_hash,
        dataset_hash=manifest.dataset_hash,
        manifest_hash=manifest.manifest_hash,
        historical_research_only=True,
        operational_evidence=False,
        paper_promotion_eligible=False,
        allowed_use_cases=OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_ALLOWED_USE_CASES,
        prohibited_use_cases=OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_PROHIBITED_USE_CASES,
        non_operational_declaration=OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_NON_OPERATIONAL_DECLARATION,
        costs=costs,
    )


def _build_strategy_callable(
    *,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    strategy_contract: BaselineAOkxBtcUsdtResearchContract,
) -> Callable[[Sequence[Candle], object], Signal | None]:
    closes: list[Decimal] = []
    true_ranges: list[Decimal] = []
    ema20: Decimal | None = None
    ema50: Decimal | None = None
    ema200: Decimal | None = None
    prev_ema50: Decimal | None = None
    atr14: Decimal | None = None
    previous_candle: Candle | None = None
    recent_pullbacks: deque[bool] = deque(maxlen=strategy_contract.pullback_lookback)

    def _seed_average(values: Sequence[Decimal]) -> Decimal:
        return sum(values, Decimal("0")) / Decimal(len(values))

    def _strategy(history: Sequence[Candle], snapshot: object) -> Signal | None:
        nonlocal ema20, ema50, ema200, prev_ema50, atr14, previous_candle
        if len(history) != len(closes) + 1:
            raise OfflineResearchBacktestValidationError("history must advance one candle at a time.")
        last_candle = history[-1]
        closes.append(last_candle.close)
        if previous_candle is None:
            true_range = last_candle.high - last_candle.low
        else:
            true_range = max(
                last_candle.high - last_candle.low,
                abs(last_candle.high - previous_candle.close),
                abs(last_candle.low - previous_candle.close),
            )
        true_ranges.append(true_range)

        fast_period = strategy_contract.trend_fast_ema_period
        mid_period = strategy_contract.trend_mid_ema_period
        slow_period = strategy_contract.trend_slow_ema_period
        atr_period = strategy_contract.atr_period
        fast_alpha = Decimal("2") / Decimal(fast_period + 1)
        mid_alpha = Decimal("2") / Decimal(mid_period + 1)
        slow_alpha = Decimal("2") / Decimal(slow_period + 1)
        fast_complement = Decimal("1") - fast_alpha
        mid_complement = Decimal("1") - mid_alpha
        slow_complement = Decimal("1") - slow_alpha

        if len(closes) == fast_period:
            ema20 = _seed_average(closes[:fast_period])
        elif len(closes) > fast_period and ema20 is not None:
            ema20 = (last_candle.close * fast_alpha) + (ema20 * fast_complement)

        if len(closes) == mid_period:
            prev_ema50 = ema50
            ema50 = _seed_average(closes[:mid_period])
        elif len(closes) > mid_period and ema50 is not None:
            prev_ema50 = ema50
            ema50 = (last_candle.close * mid_alpha) + (ema50 * mid_complement)
        else:
            prev_ema50 = ema50

        if len(closes) == slow_period:
            ema200 = _seed_average(closes[:slow_period])
        elif len(closes) > slow_period and ema200 is not None:
            ema200 = (last_candle.close * slow_alpha) + (ema200 * slow_complement)

        if len(true_ranges) == atr_period:
            atr14 = _seed_average(true_ranges[:atr_period])
        elif len(true_ranges) > atr_period and atr14 is not None:
            atr14 = ((atr14 * Decimal(atr_period - 1)) + true_range) / Decimal(atr_period)

        recent_pullbacks.append(bool(ema20 is not None and last_candle.low <= ema20))
        previous_candle = last_candle

        if (
            len(closes) < strategy_contract.minimum_candles_required
            or ema20 is None
            or ema50 is None
            or ema200 is None
            or prev_ema50 is None
            or atr14 is None
            or len(recent_pullbacks) < strategy_contract.pullback_lookback
        ):
            return None

        if ema50 <= ema200:
            return None
        if last_candle.close <= ema200:
            return None
        if ema50 <= prev_ema50:
            return None
        if last_candle.close <= ema20:
            return None
        if len(history) < 2 or last_candle.close <= history[-2].high:
            return None
        if not any(recent_pullbacks):
            return None

        stop_loss = last_candle.close - (strategy_contract.stop_atr_multiplier * atr14)
        take_profit = last_candle.close + ((last_candle.close - stop_loss) * strategy_contract.reward_multiplier)
        if stop_loss >= last_candle.close or take_profit <= last_candle.close:
            raise OfflineResearchBacktestValidationError("risk targets are invalid.")

        return Signal(
            symbol=last_candle.symbol,
            direction=Direction.COMPRA,
            entry=last_candle.close,
            stop_loss=stop_loss,
            take_profit=take_profit,
            rr=strategy_contract.reward_multiplier,
            timestamp=last_candle.close_time,
            source=DataSource.PAPER,
            score=Decimal("1"),
            regime=None,
            volume_status="NAO_FILTRADO",
            reason=BASELINE_A_OKX_BTC_USDT_RESEARCH_DECISION_LONG_SETUP_DETECTED,
            strategy_version=strategy_contract.strategy_version,
        )

    return _strategy


def run_first_offline_okx_backtest_experiment(
    *,
    dataset_file: str | Path,
    manifest_file: str | Path,
    authorization: OfflineResearchExperimentAuthorization,
    compatibility_decision: OfflineResearchStrategyCompatibilityDecision,
    strategy_contract: BaselineAOkxBtcUsdtResearchContract | None = None,
    output_file: str | Path | None = None,
    costs: OfflineResearchBacktestExperimentCosts | None = None,
    executed_at_utc: datetime | None = None,
) -> OfflineResearchBacktestExperimentReport:
    dataset = _load_okx_dataset(dataset_file, manifest_file)
    if strategy_contract is None:
        strategy_contract = build_baseline_a_okx_btc_usdt_research_contract(authorization, compatibility_decision)
    experiment_contract = build_offline_research_backtest_experiment_contract(
        authorization=authorization,
        compatibility_decision=compatibility_decision,
        strategy_contract=strategy_contract,
        dataset=dataset,
        costs=costs,
        executed_at_utc=executed_at_utc,
    )
    projected_candles = _project_dataset_to_research_surface(dataset, symbol=strategy_contract.symbol)
    runner = OfflineResearchBacktestRunner(
        config=BacktestConfig(
            initial_capital=experiment_contract.costs.initial_capital,
            risk_percent=experiment_contract.costs.risk_percent,
            entry_fee_rate=experiment_contract.costs.entry_fee_rate,
            exit_fee_rate=experiment_contract.costs.exit_fee_rate,
            spread_bps=experiment_contract.costs.spread_bps,
            slippage_bps=experiment_contract.costs.slippage_bps,
            leverage=experiment_contract.costs.leverage,
            symbol=strategy_contract.symbol,
            interval=strategy_contract.interval,
            paper_only=True,
            allow_short=False,
            intrabar_policy=experiment_contract.costs.intrabar_policy,
            gap_policy=experiment_contract.costs.gap_policy,
            strategy_version=strategy_contract.strategy_version,
            close_open_positions_at_end=True,
        ),
        cost_model=CostModel(
            entry_fee_rate=experiment_contract.costs.entry_fee_rate,
            exit_fee_rate=experiment_contract.costs.exit_fee_rate,
            spread_bps=experiment_contract.costs.spread_bps,
            slippage_bps=experiment_contract.costs.slippage_bps,
        ),
    )
    strategy_callable = _build_strategy_callable(
        authorization=authorization,
        compatibility_decision=compatibility_decision,
        strategy_contract=strategy_contract,
    )
    result = runner.run(projected_candles, strategy_callable)
    report = OfflineResearchBacktestExperimentReport(
        experiment=experiment_contract,
        dataset_file=str(dataset_file),
        manifest_file=str(manifest_file),
        analysis_start_utc=dataset.manifest.first_candle_open_utc,
        analysis_end_utc=dataset.manifest.last_candle_close_utc,
        projected_symbol=strategy_contract.symbol,
        projected_source=DataSource.PAPER.value,
        result=result,
    )
    if output_file is not None:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_canonical_json(report.as_dict()), encoding="utf-8")
    return report


__all__ = [
    "OFFLINE_RESEARCH_BACKTEST_DEFAULT_ENTRY_FEE_RATE",
    "OFFLINE_RESEARCH_BACKTEST_DEFAULT_EXIT_FEE_RATE",
    "OFFLINE_RESEARCH_BACKTEST_DEFAULT_GAP_POLICY",
    "OFFLINE_RESEARCH_BACKTEST_DEFAULT_INITIAL_CAPITAL",
    "OFFLINE_RESEARCH_BACKTEST_DEFAULT_INTRABAR_POLICY",
    "OFFLINE_RESEARCH_BACKTEST_DEFAULT_LEVERAGE",
    "OFFLINE_RESEARCH_BACKTEST_DEFAULT_RISK_PERCENT",
    "OFFLINE_RESEARCH_BACKTEST_DEFAULT_SLIPPAGE_BPS",
    "OFFLINE_RESEARCH_BACKTEST_DEFAULT_SPREAD_BPS",
    "OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_ALLOWED_USE_CASES",
    "OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_ID",
    "OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_NON_OPERATIONAL_DECLARATION",
    "OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_PROHIBITED_USE_CASES",
    "OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_PURPOSE",
    "OFFLINE_RESEARCH_BACKTEST_SCHEMA_VERSION",
    "OfflineResearchBacktestError",
    "OfflineResearchBacktestExperimentContract",
    "OfflineResearchBacktestExperimentCosts",
    "OfflineResearchBacktestExperimentReport",
    "OfflineResearchBacktestIntegrityError",
    "OfflineResearchBacktestRunner",
    "OfflineResearchBacktestValidationError",
    "build_offline_research_backtest_experiment_contract",
    "discover_okx_phase19a_artifact_paths",
    "discover_okx_persistent_artifact_paths",
    "OkxPersistentResearchArtifactResolution",
    "resolve_okx_persistent_artifact",
    "run_first_offline_okx_backtest_experiment",
]
