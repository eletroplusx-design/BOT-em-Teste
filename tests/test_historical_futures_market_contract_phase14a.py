from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from dataclasses import replace

import pytest

from domain import Candle, DataSource
from historical_futures_market_contract import (
    HISTORICAL_FUTURES_MARKET_CONTRACT_TYPE,
    HISTORICAL_FUTURES_MARKET_EXCHANGE,
    HISTORICAL_FUTURES_MARKET_TIMEFRAMES,
    HISTORICAL_FUTURES_MARKET_TYPE,
    HistoricalFuturesMarketAnalysisReference13D,
    HistoricalFuturesMarketContract,
    HistoricalFuturesMarketContractIntegrityError,
    HistoricalFuturesMarketContractValidationError,
    HistoricalFuturesMarketCostProtocol,
    HistoricalFuturesMarketCostScenario,
    HistoricalFuturesMarketFundingMethod,
    HistoricalFuturesMarketExecutionPolicy,
    HistoricalFuturesMarketAmbiguousCandlePolicy,
    HistoricalFuturesMarketTemporalSplitProtocol,
    HistoricalFuturesMarketTemporalWindow,
    build_historical_futures_market_temporal_split_protocol,
    HistoricalFuturesMarketEvaluationReference13C,
    HistoricalFuturesMarketHypothesisReference13B,
    HistoricalFuturesMarketIdentity,
    build_historical_futures_market_contract,
    build_historical_futures_market_cost_protocol,
    build_historical_futures_market_execution_policy,
    build_historical_futures_market_ambiguous_candle_policy,
)
from historical_multitimeframe_analysis import (
    build_historical_multitimeframe_strategy_analysis_protocol,
    run_historical_multitimeframe_strategy_analysis,
)
from historical_multitimeframe_evaluation import run_historical_multitimeframe_first_strategy_evaluation
from historical_multitimeframe_evaluation import HistoricalMultiTimeframeFirstStrategyEvaluationValidationError
from historical_multitimeframe_experiments import build_historical_multitimeframe_replay
from historical_multitimeframe_strategy import (
    build_historical_multitimeframe_first_strategy_config,
    build_historical_multitimeframe_first_strategy_factory,
    run_historical_multitimeframe_first_strategy,
)
from market_data import (
    HistoricalDataset,
    HistoricalDatasetRequest,
    HistoricalProviderQualification,
    build_historical_manifest,
    build_historical_multitimeframe_bundle,
    historical_content_hash,
)
from market_data.historical_store import save_historical_dataset


ONE_MS = timedelta(milliseconds=1)
BASE_15M_START = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
KUCOIN_ENDPOINT = "https://api.kucoin.com/api/v1/market/candles"


def _interval_delta(interval: str) -> timedelta:
    return {"15m": timedelta(minutes=15), "1h": timedelta(hours=1), "4h": timedelta(hours=4)}[interval]


def _trend_dataset(
    tmp_path,
    *,
    interval: str,
    start: datetime,
    count: int,
    direction: str = "up",
    symbol: str = "BTCUSDT",
    trigger_spike: bool = False,
) -> tuple[HistoricalDataset, Path]:
    qualification = HistoricalProviderQualification.kucoin_public_spot(symbol=symbol, interval=interval)
    step = _interval_delta(interval)
    candles: list[Candle] = []
    for idx in range(count):
        if direction == "down":
            open_value = 500 - (idx * 2)
            close_value = 499 - (idx * 2)
        else:
            open_value = 100 + (idx * 2)
            close_value = 101 + (idx * 2)
        high_value = max(open_value, close_value) + 1
        low_value = min(open_value, close_value) - 1
        if idx == count - 1:
            if trigger_spike:
                close_value = 1000
                high_value = 1100
                low_value = min(low_value, close_value - 2)
            else:
                close_value = open_value
                high_value = max(open_value, close_value) + 1
                low_value = min(low_value, close_value - 1)
        candles.append(
            Candle.from_dict(
                {
                    "open_time": start + (idx * step),
                    "close_time": start + (idx * step) + step - ONE_MS,
                    "open": str(open_value),
                    "high": str(high_value),
                    "low": str(low_value),
                    "close": str(close_value),
                    "volume": str(1000 + idx),
                    "symbol": symbol,
                    "interval": interval,
                    "source": DataSource.KUCOIN,
                }
            )
        )
    request = HistoricalDatasetRequest(
        provider=qualification.provider_id,
        provider_qualification=qualification,
        endpoint=KUCOIN_ENDPOINT,
        symbol=symbol,
        interval=interval,
        requested_start_utc=candles[0].open_time,
        requested_end_utc=candles[-1].close_time,
        page_size=1500,
        closed_candles_only=True,
    )
    manifest = build_historical_manifest(
        request=request,
        effective_start_utc=candles[0].open_time,
        effective_end_utc=candles[-1].close_time,
        created_at_utc=candles[-1].close_time + timedelta(days=1),
        candle_count=len(candles),
        page_count=1,
        gap_count=0,
        duplicate_count=0,
        content_hash=historical_content_hash(candles),
    )
    dataset = HistoricalDataset(manifest=manifest, candles=tuple(candles))
    path = tmp_path / f"kucoin-{interval}-{symbol}-{count}.json"
    save_historical_dataset(path, dataset)
    return dataset, path


def _build_artifacts(tmp_path):
    base, _ = _trend_dataset(tmp_path, interval="15m", start=BASE_15M_START, count=400, trigger_spike=True)
    one_hour, _ = _trend_dataset(tmp_path, interval="1h", start=BASE_15M_START - timedelta(hours=24), count=120)
    four_hour, _ = _trend_dataset(tmp_path, interval="4h", start=BASE_15M_START - timedelta(days=20), count=60)
    sliced_base_candles = base.candles[320:]
    sliced_hash = historical_content_hash(sliced_base_candles)
    base_manifest = replace(
        base.manifest,
        dataset_id=sliced_hash,
        candle_count=len(sliced_base_candles),
        content_hash=sliced_hash,
        requested_start_utc=sliced_base_candles[0].open_time,
        requested_end_utc=sliced_base_candles[-1].close_time,
        effective_start_utc=sliced_base_candles[0].open_time,
        effective_end_utc=sliced_base_candles[-1].close_time,
        created_at_utc=sliced_base_candles[-1].close_time + timedelta(days=1),
        manifest_hash="",
    )
    base_manifest = type(base_manifest).from_dict(base_manifest.as_dict())
    base_dataset = HistoricalDataset(manifest=base_manifest, candles=sliced_base_candles)
    bundle = build_historical_multitimeframe_bundle(base_dataset, one_hour, four_hour)
    replay = build_historical_multitimeframe_replay(bundle)
    config = build_historical_multitimeframe_first_strategy_config()
    factory = build_historical_multitimeframe_first_strategy_factory(config)
    strategy_report = run_historical_multitimeframe_first_strategy(replay, factory=factory)
    evaluation_report = run_historical_multitimeframe_first_strategy_evaluation(strategy_report, exit_horizon_15m_candles=4)
    analysis_protocol = build_historical_multitimeframe_strategy_analysis_protocol(evaluation_report)
    analysis_report = run_historical_multitimeframe_strategy_analysis(evaluation_report, protocol=analysis_protocol)
    return strategy_report, evaluation_report, analysis_report


def test_valid_futures_contract_round_trips_and_is_canonical(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    contract = build_historical_futures_market_contract(strategy_report, evaluation_report, analysis_report)
    round_tripped = type(contract).from_dict(contract.as_dict())

    assert contract == round_tripped
    assert contract.contract_hash == round_tripped.contract_hash
    assert contract.as_dict() == round_tripped.as_dict()
    assert contract.identity.exchange == HISTORICAL_FUTURES_MARKET_EXCHANGE
    assert contract.identity.market_type == HISTORICAL_FUTURES_MARKET_TYPE
    assert contract.identity.contract_type == HISTORICAL_FUTURES_MARKET_CONTRACT_TYPE
    assert contract.identity.timeframes == HISTORICAL_FUTURES_MARKET_TIMEFRAMES
    assert contract.historical_research_only is True
    assert contract.operational_evidence is False
    assert contract.paper_promotion_eligible is False


def test_spot_or_mixed_market_identity_is_rejected():
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketIdentity(
            exchange="Binance",
            market_type="spot",
            contract_type="perpetual",
            symbol="BTCUSDT",
            base_asset="BTC",
            margin_asset="USDT",
            settlement_asset="USDT",
            timeframes=HISTORICAL_FUTURES_MARKET_TIMEFRAMES,
        )

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketIdentity(
            exchange="Binance",
            market_type=HISTORICAL_FUTURES_MARKET_TYPE,
            contract_type="spot",
            symbol="BTCUSDT",
            base_asset="BTC",
            margin_asset="USDT",
            settlement_asset="USDT",
            timeframes=HISTORICAL_FUTURES_MARKET_TIMEFRAMES,
        )


def test_tampering_hash_or_provenance_is_detected(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    contract = build_historical_futures_market_contract(strategy_report, evaluation_report, analysis_report)

    tampered = contract.as_dict()
    tampered["hypothesis_13b"]["bundle_hash"] = "0" * 64
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        type(contract).from_dict(tampered)

    tampered = contract.as_dict()
    tampered["analysis_13d"]["source_hash"] = "0" * 64
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        type(contract).from_dict(tampered)


def test_research_only_flags_are_immutable(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    contract = build_historical_futures_market_contract(strategy_report, evaluation_report, analysis_report)

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        replace(contract, historical_research_only=False)

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        replace(contract, operational_evidence=True)

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        replace(contract, paper_promotion_eligible=True)


def test_incompatible_13b_13c_13d_references_are_rejected(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)

    hypothesis_13b = HistoricalFuturesMarketHypothesisReference13B.from_strategy_report(strategy_report)
    evaluation_13c = HistoricalFuturesMarketEvaluationReference13C.from_evaluation_report(evaluation_report)
    analysis_13d = HistoricalFuturesMarketAnalysisReference13D.from_analysis_report(analysis_report)
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketIdentity(
            exchange="Binance",
            market_type=HISTORICAL_FUTURES_MARKET_TYPE,
            contract_type=HISTORICAL_FUTURES_MARKET_CONTRACT_TYPE,
            symbol="ETHUSDT",
            base_asset="ETH",
            margin_asset="USDT",
            settlement_asset="USDT",
            timeframes=("15m", "1h", "4h"),
        )

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketContract(
            identity=HistoricalFuturesMarketIdentity(),
            hypothesis_13b=hypothesis_13b,
            evaluation_13c=replace(evaluation_13c, strategy_hypothesis_version="tampered"),
            analysis_13d=analysis_13d,
        )

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketContract(
            identity=HistoricalFuturesMarketIdentity(),
            hypothesis_13b=hypothesis_13b,
            evaluation_13c=evaluation_13c,
            analysis_13d=replace(analysis_13d, evaluation_protocol_hash="0" * 64),
        )

    tampered_hypothesis = hypothesis_13b.as_dict()
    tampered_hypothesis["symbol"] = "ETHUSDT"
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketHypothesisReference13B.from_dict(tampered_hypothesis)

    tampered_evaluation_reference = evaluation_13c.as_dict()
    tampered_evaluation_reference["strategy_hypothesis_version"] = "tampered"
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketEvaluationReference13C.from_dict(tampered_evaluation_reference)

    tampered_analysis_reference = analysis_13d.as_dict()
    tampered_analysis_reference["timeframes"] = ["5m", "1h", "4h"]
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketAnalysisReference13D.from_dict(tampered_analysis_reference)

    tampered_evaluation = evaluation_report.as_dict()
    tampered_evaluation["protocol"]["strategy_report_hash"] = "0" * 64
    with pytest.raises(HistoricalMultiTimeframeFirstStrategyEvaluationValidationError):
        type(evaluation_report).from_dict(tampered_evaluation)


def test_cost_protocol_round_trips_and_integrates_with_contract(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    cost_protocol = build_historical_futures_market_cost_protocol()
    contract = build_historical_futures_market_contract(strategy_report, evaluation_report, analysis_report, cost_protocol=cost_protocol)
    round_tripped = type(contract).from_dict(contract.as_dict())

    assert contract == round_tripped
    assert contract.contract_hash == round_tripped.contract_hash
    assert contract.cost_protocol is not None
    assert round_tripped.cost_protocol is not None
    assert contract.execution_policy is not None
    assert contract.ambiguous_candle_policy is not None
    assert contract.cost_protocol.protocol_hash == round_tripped.cost_protocol.protocol_hash
    assert contract.execution_policy.policy_hash == round_tripped.execution_policy.policy_hash
    assert contract.ambiguous_candle_policy.policy_hash == round_tripped.ambiguous_candle_policy.policy_hash
    assert contract.cost_protocol.base.funding == Decimal("0")
    assert contract.cost_protocol.pessimistic.funding == Decimal("0")


def test_execution_policy_round_trips_and_is_canonical(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    hypothesis_13b = HistoricalFuturesMarketHypothesisReference13B.from_strategy_report(strategy_report)
    evaluation_13c = HistoricalFuturesMarketEvaluationReference13C.from_evaluation_report(evaluation_report)
    analysis_13d = HistoricalFuturesMarketAnalysisReference13D.from_analysis_report(analysis_report)
    policy = build_historical_futures_market_execution_policy(hypothesis_13b, evaluation_13c, analysis_13d)
    round_tripped = HistoricalFuturesMarketExecutionPolicy.from_dict(policy.as_dict())

    assert policy == round_tripped
    assert policy.policy_hash == round_tripped.policy_hash
    assert policy.event_precedence[-1] == "reject_non_evaluable"


def test_ambiguous_candle_policy_round_trips_and_is_conservative(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    hypothesis_13b = HistoricalFuturesMarketHypothesisReference13B.from_strategy_report(strategy_report)
    evaluation_13c = HistoricalFuturesMarketEvaluationReference13C.from_evaluation_report(evaluation_report)
    analysis_13d = HistoricalFuturesMarketAnalysisReference13D.from_analysis_report(analysis_report)
    policy = build_historical_futures_market_ambiguous_candle_policy(hypothesis_13b, evaluation_13c, analysis_13d)
    round_tripped = HistoricalFuturesMarketAmbiguousCandlePolicy.from_dict(policy.as_dict())

    assert policy == round_tripped
    assert policy.policy_hash == round_tripped.policy_hash
    assert policy.allow_intrabar_path_inference is False
    assert policy.event_precedence[-1] == "reject_non_evaluable"


def test_execution_policy_rejects_open_candle_signal(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    policy = build_historical_futures_market_execution_policy(
        HistoricalFuturesMarketHypothesisReference13B.from_strategy_report(strategy_report),
        HistoricalFuturesMarketEvaluationReference13C.from_evaluation_report(evaluation_report),
        HistoricalFuturesMarketAnalysisReference13D.from_analysis_report(analysis_report),
    )
    close_utc = datetime(2025, 1, 1, 0, 15, tzinfo=timezone.utc)
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        policy.validate_timeline(timeframe="15m", candle_open_utc=close_utc - timedelta(minutes=15), candle_close_utc=close_utc, signal_utc=close_utc, execution_utc=close_utc + ONE_MS)


def test_execution_policy_rejects_bad_execution_order(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    policy = build_historical_futures_market_execution_policy(
        HistoricalFuturesMarketHypothesisReference13B.from_strategy_report(strategy_report),
        HistoricalFuturesMarketEvaluationReference13C.from_evaluation_report(evaluation_report),
        HistoricalFuturesMarketAnalysisReference13D.from_analysis_report(analysis_report),
    )
    close_utc = datetime(2025, 1, 1, 0, 15, tzinfo=timezone.utc)
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        policy.validate_timeline(timeframe="15m", candle_open_utc=close_utc - timedelta(minutes=15), candle_close_utc=close_utc, signal_utc=close_utc + ONE_MS, execution_utc=close_utc + ONE_MS)
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        policy.validate_timeline(timeframe="15m", candle_open_utc=close_utc - timedelta(minutes=15), candle_close_utc=close_utc, signal_utc=close_utc + ONE_MS, execution_utc=close_utc)


def test_execution_policy_rejects_future_data_and_bad_candles(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    policy = build_historical_futures_market_execution_policy(
        HistoricalFuturesMarketHypothesisReference13B.from_strategy_report(strategy_report),
        HistoricalFuturesMarketEvaluationReference13C.from_evaluation_report(evaluation_report),
        HistoricalFuturesMarketAnalysisReference13D.from_analysis_report(analysis_report),
    )
    close_utc = datetime(2025, 1, 1, 0, 15, tzinfo=timezone.utc)
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        policy.validate_timeline(timeframe="5m", candle_open_utc=close_utc - timedelta(minutes=15), candle_close_utc=close_utc, signal_utc=close_utc + timedelta(seconds=1), execution_utc=close_utc + timedelta(seconds=2))
    for kwargs in (
        dict(candle_present=False),
        dict(candle_valid=False),
        dict(candle_duplicate=True),
        dict(candle_in_order=False),
        dict(future_data_used=True),
    ):
        with pytest.raises(HistoricalFuturesMarketContractValidationError):
            policy.validate_timeline(timeframe="15m", candle_open_utc=close_utc - timedelta(minutes=15), candle_close_utc=close_utc, signal_utc=close_utc + timedelta(seconds=1), execution_utc=close_utc + timedelta(seconds=2), **kwargs)


def test_ambiguous_policy_rejects_ambiguous_or_incomplete_observations(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    policy = build_historical_futures_market_ambiguous_candle_policy(
        HistoricalFuturesMarketHypothesisReference13B.from_strategy_report(strategy_report),
        HistoricalFuturesMarketEvaluationReference13C.from_evaluation_report(evaluation_report),
        HistoricalFuturesMarketAnalysisReference13D.from_analysis_report(analysis_report),
    )
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        policy.validate_ambiguity(timeframe="15m", same_candle_conflict=True)
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        policy.validate_ambiguity(timeframe="15m", path_resolvable=False)
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        policy.validate_ambiguity(timeframe="1m")


def test_policy_tampering_is_detected(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    exec_policy = build_historical_futures_market_execution_policy(
        HistoricalFuturesMarketHypothesisReference13B.from_strategy_report(strategy_report),
        HistoricalFuturesMarketEvaluationReference13C.from_evaluation_report(evaluation_report),
        HistoricalFuturesMarketAnalysisReference13D.from_analysis_report(analysis_report),
    )
    tampered = exec_policy.as_dict()
    tampered["event_precedence"] = ["future_data"]
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketExecutionPolicy.from_dict(tampered)
    tampered = exec_policy.as_dict()
    tampered["policy_hash"] = "0" * 64
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketExecutionPolicy.from_dict(tampered)

    amb_policy = build_historical_futures_market_ambiguous_candle_policy(
        HistoricalFuturesMarketHypothesisReference13B.from_strategy_report(strategy_report),
        HistoricalFuturesMarketEvaluationReference13C.from_evaluation_report(evaluation_report),
        HistoricalFuturesMarketAnalysisReference13D.from_analysis_report(analysis_report),
    )
    tampered = amb_policy.as_dict()
    tampered["allow_intrabar_path_inference"] = True
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketAmbiguousCandlePolicy.from_dict(tampered)


def test_cost_protocol_canonical_serialization_and_deterministic_hash():
    protocol = build_historical_futures_market_cost_protocol()
    round_tripped = HistoricalFuturesMarketCostProtocol.from_dict(protocol.as_dict())
    rebuilt = build_historical_futures_market_cost_protocol()

    assert protocol == round_tripped
    assert protocol.protocol_hash == round_tripped.protocol_hash
    assert protocol.protocol_hash == rebuilt.protocol_hash
    assert protocol.as_dict() == round_tripped.as_dict()


def test_cost_protocol_tampering_is_detected():
    protocol = build_historical_futures_market_cost_protocol()

    tampered = protocol.as_dict()
    tampered["base"]["spread"] = "11"
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketCostProtocol.from_dict(tampered)

    tampered = protocol.as_dict()
    tampered["protocol_hash"] = "0" * 64
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketCostProtocol.from_dict(tampered)


def test_invalid_cost_inputs_are_rejected():
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketCostScenario(entry_fee_rate=Decimal("-0.0001"))

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketCostScenario(slippage=Decimal("NaN"))


def test_invalid_currency_or_unit_is_rejected():
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketCostScenario(settlement_currency="USD")

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketCostScenario(spread_unit="fraction")


def test_pessimistic_scenario_cannot_be_more_favorable_than_base():
    base = HistoricalFuturesMarketCostScenario(
        entry_fee_rate=Decimal("0.0004"),
        exit_fee_rate=Decimal("0.0004"),
        spread=Decimal("5"),
        slippage=Decimal("5"),
        funding=Decimal("0"),
        funding_required=False,
    )
    pessimistic = replace(
        base,
        scenario_name="pessimistic",
        spread=Decimal("4"),
        scenario_hash="",
    )

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketCostProtocol(
            funding_method=HistoricalFuturesMarketFundingMethod(),
            base=base,
            pessimistic=pessimistic,
        )


def test_funding_method_without_verifiable_reference_is_rejected():
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketFundingMethod(funding_method_reference="")


def test_optional_zero_funding_is_explicit_and_does_not_enable_calculation():
    protocol = build_historical_futures_market_cost_protocol()

    assert protocol.base.funding_required is False
    assert protocol.base.funding == Decimal("0")
    assert protocol.pessimistic.funding_required is False
    assert protocol.pessimistic.funding == Decimal("0")
    assert protocol.funding_method.funding_method_reference.startswith("https://")



def test_existing_multitimeframe_artifacts_still_round_trip(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)

    assert type(strategy_report).from_dict(strategy_report.as_dict()).report_hash == strategy_report.report_hash
    assert type(evaluation_report).from_dict(evaluation_report.as_dict()).evaluation_hash == evaluation_report.evaluation_hash
    assert type(analysis_report).from_dict(analysis_report.as_dict()).report_hash == analysis_report.report_hash



def test_temporal_split_protocol_round_trips_and_is_canonical(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    hypothesis_13b = HistoricalFuturesMarketHypothesisReference13B.from_strategy_report(strategy_report)
    evaluation_13c = HistoricalFuturesMarketEvaluationReference13C.from_evaluation_report(evaluation_report)
    analysis_13d = HistoricalFuturesMarketAnalysisReference13D.from_analysis_report(analysis_report)

    protocol = build_historical_futures_market_temporal_split_protocol(hypothesis_13b, evaluation_13c, analysis_13d)
    round_tripped = HistoricalFuturesMarketTemporalSplitProtocol.from_dict(protocol.as_dict())

    assert protocol == round_tripped
    assert protocol.protocol_hash == round_tripped.protocol_hash
    assert protocol.as_dict() == round_tripped.as_dict()
    assert protocol.selection_basis == "historical_reference_validation_test_split_v1"
    assert protocol.reference_window.window_name == "reference"
    assert protocol.validation_window.window_name == "validation"
    assert protocol.test_window.window_name == "test"
    assert protocol.reference_window.end_utc < protocol.validation_window.start_utc
    assert protocol.validation_window.end_utc < protocol.test_window.start_utc


def test_full_contract_round_trips_with_temporal_split_protocol(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    contract = build_historical_futures_market_contract(strategy_report, evaluation_report, analysis_report)
    round_tripped = type(contract).from_dict(contract.as_dict())

    assert contract == round_tripped
    assert contract.contract_hash == round_tripped.contract_hash
    assert contract.temporal_split_protocol == round_tripped.temporal_split_protocol
    assert contract.as_dict() == round_tripped.as_dict()
    assert contract.temporal_split_protocol is not None
    assert contract.execution_policy is not None
    assert contract.ambiguous_candle_policy is not None


def test_temporal_split_rejects_overlap_and_wrong_order(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    protocol = build_historical_futures_market_temporal_split_protocol(
        HistoricalFuturesMarketHypothesisReference13B.from_strategy_report(strategy_report),
        HistoricalFuturesMarketEvaluationReference13C.from_evaluation_report(evaluation_report),
        HistoricalFuturesMarketAnalysisReference13D.from_analysis_report(analysis_report),
    )

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        replace(
            protocol,
            reference_window=replace(
                protocol.reference_window,
                end_utc=protocol.validation_window.start_utc + ONE_MS,
                window_hash="",
            ),
        )

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        replace(
            protocol,
            validation_window=replace(
                protocol.validation_window,
                start_utc=protocol.test_window.end_utc + ONE_MS,
                end_utc=protocol.test_window.end_utc + timedelta(hours=1),
                window_hash="",
            ),
        )


def test_temporal_split_rejects_inverted_zero_length_and_future_windows():
    now = datetime.now(timezone.utc)

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketTemporalWindow(
            window_name="reference",
            start_utc=now,
            end_utc=now,
            provenance_hash="0" * 64,
        )

    naive_start = datetime(2025, 1, 1, 0, 0)
    aware_end = datetime(2025, 1, 1, 1, 0, tzinfo=timezone.utc)
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketTemporalWindow(
            window_name="validation",
            start_utc=naive_start,
            end_utc=aware_end,
            provenance_hash="0" * 64,
        )

    non_utc_tz = timezone(timedelta(hours=-3))
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketTemporalWindow(
            window_name="test",
            start_utc=datetime(2025, 1, 1, 0, 0, tzinfo=non_utc_tz),
            end_utc=datetime(2025, 1, 1, 1, 0, tzinfo=non_utc_tz),
            provenance_hash="0" * 64,
        )

    future_start = now + timedelta(days=1)
    future_end = future_start + timedelta(hours=1)
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketTemporalWindow(
            window_name="test",
            start_utc=future_start,
            end_utc=future_end,
            provenance_hash="0" * 64,
        )


def test_temporal_split_rejects_windows_outside_coverage_or_provenance(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    protocol = build_historical_futures_market_temporal_split_protocol(
        HistoricalFuturesMarketHypothesisReference13B.from_strategy_report(strategy_report),
        HistoricalFuturesMarketEvaluationReference13C.from_evaluation_report(evaluation_report),
        HistoricalFuturesMarketAnalysisReference13D.from_analysis_report(analysis_report),
    )

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        replace(
            protocol,
            reference_window=replace(
                protocol.reference_window,
                start_utc=protocol.coverage_start_utc - timedelta(days=1),
                window_hash="",
            ),
        )

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        replace(protocol, provenance_hash="0" * 64)


def test_temporal_split_rejects_performance_based_selection_basis(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    hypothesis_13b = HistoricalFuturesMarketHypothesisReference13B.from_strategy_report(strategy_report)
    evaluation_13c = HistoricalFuturesMarketEvaluationReference13C.from_evaluation_report(evaluation_report)
    analysis_13d = HistoricalFuturesMarketAnalysisReference13D.from_analysis_report(analysis_report)
    protocol = build_historical_futures_market_temporal_split_protocol(hypothesis_13b, evaluation_13c, analysis_13d)

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        replace(protocol, selection_basis="pnl")


def test_temporal_split_tampering_is_detected(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    protocol = build_historical_futures_market_temporal_split_protocol(
        HistoricalFuturesMarketHypothesisReference13B.from_strategy_report(strategy_report),
        HistoricalFuturesMarketEvaluationReference13C.from_evaluation_report(evaluation_report),
        HistoricalFuturesMarketAnalysisReference13D.from_analysis_report(analysis_report),
    )

    tampered = protocol.as_dict()
    tampered["protocol_hash"] = "0" * 64
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketTemporalSplitProtocol.from_dict(tampered)

    tampered = protocol.as_dict()
    tampered["provenance_hash"] = "0" * 64
    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        HistoricalFuturesMarketTemporalSplitProtocol.from_dict(tampered)

    with pytest.raises(HistoricalFuturesMarketContractValidationError):
        replace(protocol, coverage_end_utc=protocol.coverage_end_utc + timedelta(days=1))


def test_temporal_split_preserves_existing_part_1_to_3_anchors(tmp_path):
    strategy_report, evaluation_report, analysis_report = _build_artifacts(tmp_path)
    contract = build_historical_futures_market_contract(strategy_report, evaluation_report, analysis_report)

    assert contract.hypothesis_13b.reference_hash == contract.execution_policy.hypothesis_13b_reference_hash == contract.ambiguous_candle_policy.hypothesis_13b_reference_hash == contract.temporal_split_protocol.hypothesis_13b_reference_hash
    assert contract.evaluation_13c.reference_hash == contract.execution_policy.evaluation_13c_reference_hash == contract.ambiguous_candle_policy.evaluation_13c_reference_hash == contract.temporal_split_protocol.evaluation_13c_reference_hash
    assert contract.analysis_13d.reference_hash == contract.execution_policy.analysis_13d_reference_hash == contract.ambiguous_candle_policy.analysis_13d_reference_hash == contract.temporal_split_protocol.analysis_13d_reference_hash
    assert contract.temporal_split_protocol.provenance_hash == contract.analysis_13d.source_hash
