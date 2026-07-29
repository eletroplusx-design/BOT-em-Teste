from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from domain import Candle, DataSource, Direction, Signal

import market_data.offline_research_backtest as backtest
import market_data.offline_research_execution_gate_diagnostic as diagnostic
import market_data.offline_research_experiment_authorization as authorization
import market_data.offline_research_strategy_compatibility as compatibility
import market_data.okx_historical as okx
import market_data.research_artifact_registry as registry
import market_data.research_artifact_registry_verification as verification
from strategies.baseline_a_okx_btc_usdt_research import build_baseline_a_okx_btc_usdt_research_contract

ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)


def _verified_authorization() -> authorization.OfflineResearchExperimentAuthorization:
    registry_entry = registry.ResearchArtifactRegistryEntry(
        registered_at_utc=datetime(2026, 7, 27, 16, 31, 31, tzinfo=timezone.utc),
        external_artifact_ref="artifact://okx/phase24/research-only",
        dataset_sha256=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256,
        manifest_sha256=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256,
        manifest_hash=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH,
    )
    report = verification.ResearchArtifactRegistryVerificationReport(
        registry_file=Path("synthetic/okx-research-artifact-registry.json"),
        verified_at_utc=datetime(2026, 7, 27, 16, 31, 32, tzinfo=timezone.utc),
        artifact_id=registry_entry.artifact_id,
        provider_name=registry.OKX_RESEARCH_ARTIFACT_PROVIDER_NAME,
        market_type=registry.OKX_RESEARCH_ARTIFACT_MARKET_TYPE,
        instrument=registry.OKX_RESEARCH_ARTIFACT_INSTRUMENT,
        symbol=registry.OKX_RESEARCH_ARTIFACT_SYMBOL,
        interval=registry.OKX_RESEARCH_ARTIFACT_INTERVAL,
        requested_start_inclusive_utc=registry.OKX_RESEARCH_ARTIFACT_REQUESTED_START_INCLUSIVE_UTC,
        requested_end_exclusive_utc=registry.OKX_RESEARCH_ARTIFACT_REQUESTED_END_EXCLUSIVE_UTC,
        expected_candle_count=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT,
        audited_candle_count=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT,
        dataset_sha256=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_DATASET_SHA256,
        manifest_sha256=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_SHA256,
        manifest_hash=registry.OKX_RESEARCH_ARTIFACT_EXPECTED_MANIFEST_HASH,
        audit_status=registry.OKX_RESEARCH_ARTIFACT_AUDIT_STATUS_PASSED,
        external_artifact_ref="artifact://okx/phase24/research-only",
        external_artifact_ref_is_opaque=True,
        external_artifact_ref_is_local=True,
        historical_research_only=True,
        operational_evidence=False,
        paper_promotion_eligible=False,
        non_operational_declaration=registry.OKX_RESEARCH_ARTIFACT_NON_OPERATIONAL_DECLARATION,
        verification_hash="",
    )
    return authorization.authorize_offline_research_experiment(
        report,
        issued_at_utc=datetime(2026, 7, 27, 16, 31, 33, tzinfo=timezone.utc),
    )


def _compatible_contract(
    auth: authorization.OfflineResearchExperimentAuthorization,
) -> compatibility.OfflineResearchStrategyCompatibilityContract:
    return compatibility.OfflineResearchStrategyCompatibilityContract(
        strategy_id="synthetic_okx_compatibility",
        strategy_version="phase24_compatibility_v1",
        provider_name=auth.provider_name,
        market_type=auth.market_type,
        symbol=auth.instrument,
        canonical_symbol=auth.symbol,
        interval=auth.interval,
        requested_start_inclusive_utc=auth.requested_start_inclusive_utc,
        requested_end_exclusive_utc=auth.requested_end_exclusive_utc,
        expected_candle_count=auth.candle_count,
        required_dataset_sha256=auth.dataset_sha256,
        required_manifest_sha256=auth.manifest_sha256,
        required_manifest_hash=auth.manifest_hash,
        required_verification_hash=auth.verification_result_hash,
        purpose=auth.purpose,
        historical_research_only=auth.historical_research_only,
        operational_evidence=auth.operational_evidence,
        paper_promotion_eligible=auth.paper_promotion_eligible,
        allowed_use_cases=auth.allowed_use_cases,
        prohibited_use_cases=auth.prohibited_use_cases,
    )


def _bundle(
    *,
    costs: diagnostic.ExecutionGateTraceCosts | None = None,
):
    auth = _verified_authorization()
    compat = _compatible_contract(auth)
    decision = compatibility.evaluate_offline_research_strategy_compatibility(
        auth,
        compat,
        decided_at_utc=datetime(2026, 7, 27, 16, 31, 34, tzinfo=timezone.utc),
    )
    strategy_contract = build_baseline_a_okx_btc_usdt_research_contract(auth, decision)
    trace_contract = diagnostic.build_baseline_a_okx_btc_usdt_1h_execution_gate_trace_contract(
        auth,
        decision,
        strategy_version=strategy_contract.strategy_version,
        costs=costs,
    )
    return auth, decision, strategy_contract, trace_contract


def _candle(
    open_time: datetime,
    *,
    base: int,
    close_offset: int = 1,
    high_offset: int = 2,
    low_offset: int = 1,
    symbol: str = registry.OKX_RESEARCH_ARTIFACT_INSTRUMENT,
    interval: str = registry.OKX_RESEARCH_ARTIFACT_INTERVAL,
) -> Candle:
    return Candle.from_dict(
        {
            "open_time": open_time,
            "close_time": open_time + ONE_HOUR - ONE_MS,
            "open": str(base),
            "high": str(base + high_offset),
            "low": str(base - low_offset),
            "close": str(base + close_offset),
            "volume": str(1000 + base),
            "symbol": symbol,
            "interval": interval,
            "source": DataSource.PAPER,
        }
    )


def _history(*, count: int = 3) -> tuple[Candle, ...]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return tuple(_candle(start + idx * ONE_HOUR, base=100 + idx, close_offset=1, high_offset=2, low_offset=1) for idx in range(count))


def _signal(
    candle: Candle,
    *,
    stop_loss: Decimal,
    take_profit: Decimal,
    reason: str = "phase24_signal",
) -> Signal:
    return Signal(
        symbol=registry.OKX_RESEARCH_ARTIFACT_INSTRUMENT,
        direction=Direction.COMPRA,
        entry=candle.close,
        stop_loss=stop_loss,
        take_profit=take_profit,
        rr=Decimal("2"),
        timestamp=candle.close_time,
        source=DataSource.PAPER,
        score=Decimal("1"),
        regime="BULL",
        volume_status="NAO_FILTRADO",
        reason=reason,
        strategy_version="phase24_test_signal_v1",
    )


def _trace_hash_payload(candles: tuple[Candle, ...]) -> tuple[str, str]:
    dataset_hash = diagnostic._hash_payload([candle.to_dict() for candle in candles])
    manifest_hash = diagnostic._hash_payload(
        {
            "dataset_hash": dataset_hash,
            "candle_count": len(candles),
            "first_open_time": candles[0].open_time,
            "last_close_time": candles[-1].close_time,
        }
    )
    return dataset_hash, manifest_hash


def test_trace_signal_to_order_position_open_and_close():
    auth, decision, strategy_contract, trace_contract = _bundle()
    candles = _history(count=3)
    dataset_hash, manifest_hash = _trace_hash_payload(candles)

    def _strategy(history, snapshot):
        if len(history) == 2:
            return _signal(history[-1], stop_loss=Decimal("90"), take_profit=Decimal("120"))
        return None

    report = diagnostic._simulate_execution_gate_trace(
        candles,
        strategy_callable=_strategy,
        contract=trace_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 35, tzinfo=timezone.utc),
        analysis_start_utc=candles[0].open_time,
        analysis_end_utc=candles[-1].close_time,
        projected_symbol=strategy_contract.symbol,
        projected_source=DataSource.PAPER.value,
        dataset_hash=dataset_hash,
        manifest_hash=manifest_hash,
    )

    assert report.trace_counts["signal_emitted"] == 1
    assert report.trace_counts["paper_order_created"] == 1
    assert report.trace_counts["position_opened"] == 1
    assert report.trace_counts["position_closed"] == 1
    assert report.trace_counts["not_reached"] == 2
    assert report.trace_records[0].gate_terminal == "position_closed"
    assert report.trace_records[0].position_opened is True
    assert report.trace_records[0].position_closed is True
    assert report.trace_records[0].risk_allowed is True
    assert report.trace_records[0].normalized_rejection_reason is None


def test_trace_rejects_exposure_above_capital():
    auth, decision, strategy_contract, trace_contract = _bundle()
    candles = _history(count=3)
    dataset_hash, manifest_hash = _trace_hash_payload(candles)

    def _strategy(history, snapshot):
        if len(history) == 2:
            return _signal(history[-1], stop_loss=Decimal("101.5"), take_profit=Decimal("120"))
        return None

    report = diagnostic._simulate_execution_gate_trace(
        candles,
        strategy_callable=_strategy,
        contract=trace_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 36, tzinfo=timezone.utc),
        analysis_start_utc=candles[0].open_time,
        analysis_end_utc=candles[-1].close_time,
        projected_symbol=strategy_contract.symbol,
        projected_source=DataSource.PAPER.value,
        dataset_hash=dataset_hash,
        manifest_hash=manifest_hash,
    )

    assert report.trace_counts["risk_rejected"] == 1
    assert report.trace_records[0].gate_terminal == "risk_rejected"
    assert report.trace_records[0].risk_allowed is False
    assert report.trace_records[0].normalized_rejection_reason == "risk_not_allowed"


def test_trace_rejects_portfolio_cash_when_required_cash_exceeds_available_cash():
    auth, decision, strategy_contract, trace_contract = _bundle()
    candles = _history(count=3)
    dataset_hash, manifest_hash = _trace_hash_payload(candles)

    def _strategy(history, snapshot):
        if len(history) == 2:
            return _signal(history[-1], stop_loss=Decimal("100.98"), take_profit=Decimal("120"))
        return None

    report = diagnostic._simulate_execution_gate_trace(
        candles,
        strategy_callable=_strategy,
        contract=trace_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 37, tzinfo=timezone.utc),
        analysis_start_utc=candles[0].open_time,
        analysis_end_utc=candles[-1].close_time,
        projected_symbol=strategy_contract.symbol,
        projected_source=DataSource.PAPER.value,
        dataset_hash=dataset_hash,
        manifest_hash=manifest_hash,
    )

    assert report.trace_counts["portfolio_cash_rejected"] == 1
    assert report.trace_records[0].gate_terminal == "portfolio_cash_rejected"
    assert report.trace_records[0].risk_allowed is True
    assert report.trace_records[0].required_cash is not None
    assert report.trace_records[0].required_cash > report.trace_records[0].capital_available


def test_trace_blocks_signals_while_position_is_open():
    auth, decision, strategy_contract, trace_contract = _bundle()
    candles = _history(count=3)
    dataset_hash, manifest_hash = _trace_hash_payload(candles)

    def _strategy(history, snapshot):
        if len(history) in (1, 2):
            return _signal(history[-1], stop_loss=Decimal("90"), take_profit=Decimal("120"), reason="phase24_dual_signal")
        return None

    report = diagnostic._simulate_execution_gate_trace(
        candles,
        strategy_callable=_strategy,
        contract=trace_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 38, tzinfo=timezone.utc),
        analysis_start_utc=candles[0].open_time,
        analysis_end_utc=candles[-1].close_time,
        projected_symbol=strategy_contract.symbol,
        projected_source=DataSource.PAPER.value,
        dataset_hash=dataset_hash,
        manifest_hash=manifest_hash,
    )

    assert report.trace_counts["position_opened"] == 1
    assert report.trace_counts["position_closed"] == 1
    assert report.trace_counts["active_position_blocked"] == 1
    assert report.trace_records[0].gate_terminal == "position_closed"
    assert report.trace_records[1].gate_terminal == "active_position_blocked"
    assert report.trace_records[1].normalized_rejection_reason == "open_position_already_exists"


def test_trace_is_reproducible_and_preserves_baseline_contract():
    auth, decision, strategy_contract, trace_contract = _bundle()
    candles = _history(count=3)
    dataset_hash, manifest_hash = _trace_hash_payload(candles)

    before = strategy_contract.as_dict()

    def _strategy(history, snapshot):
        if len(history) == 2:
            return _signal(history[-1], stop_loss=Decimal("90"), take_profit=Decimal("120"))
        return None

    first = diagnostic._simulate_execution_gate_trace(
        candles,
        strategy_callable=_strategy,
        contract=trace_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 39, tzinfo=timezone.utc),
        analysis_start_utc=candles[0].open_time,
        analysis_end_utc=candles[-1].close_time,
        projected_symbol=strategy_contract.symbol,
        projected_source=DataSource.PAPER.value,
        dataset_hash=dataset_hash,
        manifest_hash=manifest_hash,
    )
    second = diagnostic._simulate_execution_gate_trace(
        candles,
        strategy_callable=_strategy,
        contract=trace_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 39, tzinfo=timezone.utc),
        analysis_start_utc=candles[0].open_time,
        analysis_end_utc=candles[-1].close_time,
        projected_symbol=strategy_contract.symbol,
        projected_source=DataSource.PAPER.value,
        dataset_hash=dataset_hash,
        manifest_hash=manifest_hash,
    )

    assert strategy_contract.as_dict() == before
    assert first.as_dict() == second.as_dict()
    assert trace_contract.historical_research_only is True
    assert trace_contract.operational_evidence is False
    assert trace_contract.paper_promotion_eligible is False
    assert trace_contract.strategy_id == "baseline_a_okx_btc_usdt_1h_research"
    assert trace_contract.strategy_version == "baseline_a_okx_btc_usdt_1h_research_v1"


@pytest.mark.parametrize(
    ("mutator", "expected", "runner"),
    [
        (
            lambda auth, compat, contract, trace_contract: object.__setattr__(auth, "paper_promotion_eligible", True),
            "paper_promotion_eligible must be false.",
            lambda auth, compat, contract, trace_contract, candles: diagnostic.run_baseline_a_okx_btc_usdt_1h_execution_gate_trace_research(
                candles,
                authorization=auth,
                compatibility_decision=compat,
                strategy_contract=contract,
                analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 41, tzinfo=timezone.utc),
                costs=trace_contract.costs,
            ),
        ),
        (
            lambda auth, compat, contract, trace_contract: object.__setattr__(compat, "symbol", "BTCUSDT"),
            "compatibility symbol must be BTC-USDT.",
            lambda auth, compat, contract, trace_contract, candles: diagnostic.run_baseline_a_okx_btc_usdt_1h_execution_gate_trace_research(
                candles,
                authorization=auth,
                compatibility_decision=compat,
                strategy_contract=contract,
                analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 41, tzinfo=timezone.utc),
                costs=trace_contract.costs,
            ),
        ),
        (
            lambda auth, compat, contract, trace_contract: object.__setattr__(contract, "symbol", "BTCUSDT"),
            "strategy symbol must be BTC-USDT.",
            lambda auth, compat, contract, trace_contract, candles: diagnostic.run_baseline_a_okx_btc_usdt_1h_execution_gate_trace_research(
                candles,
                authorization=auth,
                compatibility_decision=compat,
                strategy_contract=contract,
                analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 41, tzinfo=timezone.utc),
                costs=trace_contract.costs,
            ),
        ),
        (
            lambda auth, compat, contract, trace_contract: object.__setattr__(contract, "prohibited_use_cases", ("replay", "paper")),
            "prohibited_use_cases must block operational use cases.",
            lambda auth, compat, contract, trace_contract, candles: diagnostic.run_baseline_a_okx_btc_usdt_1h_execution_gate_trace_research(
                candles,
                authorization=auth,
                compatibility_decision=compat,
                strategy_contract=contract,
                analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 41, tzinfo=timezone.utc),
                costs=trace_contract.costs,
            ),
        ),
        (
            lambda auth, compat, contract, trace_contract: object.__setattr__(trace_contract.costs, "allow_short", True),
            "allow_short must be false.",
            lambda auth, compat, contract, trace_contract, candles: diagnostic.run_baseline_a_okx_btc_usdt_1h_execution_gate_trace_research(
                candles,
                authorization=auth,
                compatibility_decision=compat,
                strategy_contract=contract,
                analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 41, tzinfo=timezone.utc),
                costs=trace_contract.costs,
            ),
        ),
    ],
)
def test_trace_rejects_operational_flags_kucoin_btcusdt_and_paper_live_use_cases(mutator, expected, runner):
    auth, decision, strategy_contract, trace_contract = _bundle()
    auth = copy.deepcopy(auth)
    decision = copy.deepcopy(decision)
    strategy_contract = copy.deepcopy(strategy_contract)
    trace_contract = copy.deepcopy(trace_contract)
    mutator(auth, decision, strategy_contract, trace_contract)

    with pytest.raises(diagnostic.OfflineResearchExecutionGateDiagnosticValidationError, match=expected):
        runner(auth, decision, strategy_contract, trace_contract, _history(count=3))


def test_trace_on_real_okx_artifact_is_reproducible_and_research_only():
    dataset_file, manifest_file = diagnostic.discover_okx_phase24_artifact_paths()
    dataset = diagnostic.load_okx_phase24_trace_dataset(dataset_file=dataset_file, manifest_file=manifest_file)
    auth, decision, strategy_contract, trace_contract = _bundle()

    first = diagnostic.run_baseline_a_okx_btc_usdt_1h_execution_gate_trace_research_for_okx_artifact(
        dataset=dataset,
        authorization=auth,
        compatibility_decision=decision,
        strategy_contract=strategy_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 40, tzinfo=timezone.utc),
    )
    second = diagnostic.run_baseline_a_okx_btc_usdt_1h_execution_gate_trace_research_for_okx_artifact(
        dataset=dataset,
        authorization=auth,
        compatibility_decision=decision,
        strategy_contract=strategy_contract,
        analyzed_at_utc=datetime(2026, 7, 27, 16, 31, 40, tzinfo=timezone.utc),
    )

    assert first.as_dict() == second.as_dict()
    assert first.contract.historical_research_only is True
    assert first.contract.operational_evidence is False
    assert first.contract.paper_promotion_eligible is False
    assert first.projected_symbol == "BTC-USDT"
    assert first.projected_source == DataSource.PAPER.value
    assert first.candles_total == registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT
    assert first.signals_emitted == 0
    assert first.trace_counts["signal_emitted"] == 0
    assert first.trace_counts["not_reached"] == registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT
    assert trace_contract.strategy_id == "baseline_a_okx_btc_usdt_1h_research"
