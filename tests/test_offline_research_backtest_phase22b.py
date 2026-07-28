from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import requests

from backtesting.costs import CostModel
from backtesting.models import BacktestConfig, GapPolicy, IntrabarPolicy
from domain import Candle, DataSource, Direction, MarketSnapshot, OrderStatus, PaperOrder, Signal, TradingMode

import market_data.offline_research_backtest as backtest
import market_data.offline_research_experiment_authorization as authorization
import market_data.offline_research_strategy_compatibility as compatibility
import market_data.okx_historical as okx
import market_data.research_artifact_registry as registry
import market_data.research_artifact_registry_verification as verification
from strategies.baseline_a_okx_btc_usdt_research import build_baseline_a_okx_btc_usdt_research_contract

ONE_HOUR = timedelta(hours=1)
ONE_MS = timedelta(milliseconds=1)


def _fail_network(*args, **kwargs):
    raise AssertionError("network must not be reached")


def _workspace_tmp_dir(name: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp" / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _verified_authorization() -> authorization.OfflineResearchExperimentAuthorization:
    registry_entry = registry.ResearchArtifactRegistryEntry(
        registered_at_utc=datetime(2026, 7, 27, 16, 31, 31, tzinfo=timezone.utc),
        external_artifact_ref="artifact://okx/phase22b/research-only",
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
        external_artifact_ref="artifact://okx/phase22b/research-only",
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
        strategy_version="phase21b_compatibility_v1",
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


def _real_phase19a_dataset():
    dataset_file, manifest_file = backtest.discover_okx_phase19a_artifact_paths()
    return okx.load_okx_historical_dataset(dataset_file=dataset_file, manifest_file=manifest_file)


def _strategy_contract():
    auth = _verified_authorization()
    compat = _compatible_contract(auth)
    decision = compatibility.evaluate_offline_research_strategy_compatibility(
        auth,
        compat,
        decided_at_utc=datetime(2026, 7, 27, 16, 31, 34, tzinfo=timezone.utc),
    )
    return build_baseline_a_okx_btc_usdt_research_contract(auth, decision)


def _candle(
    open_time: datetime,
    *,
    base: int,
    symbol: str = "BTC-USDT",
    interval: str = "1H",
    source: DataSource = DataSource.PAPER,
) -> Candle:
    return Candle.from_dict(
        {
            "open_time": open_time,
            "close_time": open_time + ONE_HOUR - ONE_MS,
            "open": str(base),
            "high": str(base + 5),
            "low": str(base - 5),
            "close": str(base + 1),
            "volume": str(1000 + base),
            "symbol": symbol,
            "interval": interval,
            "source": source,
        }
    )


def _history(*, count: int = 6, symbol: str = "BTC-USDT", interval: str = "1H") -> tuple[Candle, ...]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return tuple(_candle(start + idx * ONE_HOUR, base=100 + idx, symbol=symbol, interval=interval) for idx in range(count))


def _signal_strategy(trigger_index: int, *, order_symbol: str = "BTC-USDT", source: DataSource = DataSource.PAPER):
    def _strategy(history: tuple[Candle, ...], snapshot: MarketSnapshot):
        if len(history) != trigger_index + 1:
            return None
        candle = history[-1]
        return Signal(
            symbol=order_symbol,
            direction=Direction.COMPRA,
            entry=candle.close,
            stop_loss=candle.close - Decimal("10"),
            take_profit=candle.close + Decimal("20"),
            rr=Decimal("2"),
            timestamp=candle.close_time,
            source=source,
            score=Decimal("1"),
            regime="BULL",
            volume_status="NAO_FILTRADO",
            reason="phase22b_test_signal",
            strategy_version="phase22b_test_signal_v1",
        )

    return _strategy


def _paper_order_strategy(trigger_index: int, *, quantity: Decimal, entry: Decimal, stop_loss: Decimal, take_profit: Decimal):
    def _strategy(history: tuple[Candle, ...], snapshot: MarketSnapshot):
        if len(history) != trigger_index + 1:
            return None
        candle = history[-1]
        return PaperOrder(
            symbol=candle.symbol,
            direction=Direction.COMPRA,
            entry=entry,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            opened_at=candle.close_time,
            status=OrderStatus.OPEN,
            source=DataSource.PAPER,
            paper=True,
            trading_mode=TradingMode.PAPER,
        )

    return _strategy


def test_runner_is_prefix_only_and_deterministic(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, "get", _fail_network, raising=True)
    seen_histories: list[tuple[datetime, ...]] = []
    candles = _history(count=5)
    runner = backtest.OfflineResearchBacktestRunner(
        config=BacktestConfig(
            symbol="BTC-USDT",
            interval="1H",
            paper_only=True,
            allow_short=False,
            strategy_version="phase22b_test",
        ),
        cost_model=CostModel(entry_fee_rate=Decimal("0"), exit_fee_rate=Decimal("0"), spread_bps=Decimal("0"), slippage_bps=Decimal("0")),
    )

    def _strategy(history: tuple[Candle, ...], snapshot: MarketSnapshot):
        seen_histories.append(tuple(candle.open_time for candle in history))
        return None

    result = runner.run(candles, _strategy)
    assert result.trades == ()
    assert seen_histories == [tuple(candle.open_time for candle in candles[: idx + 1]) for idx in range(len(candles) - 1)]

    seen_histories.clear()
    repeat = runner.run(candles, _strategy)
    assert seen_histories == [tuple(candle.open_time for candle in candles[: idx + 1]) for idx in range(len(candles) - 1)]
    assert result.to_dict() == repeat.to_dict()


@pytest.mark.parametrize(
    ("policy", "expected_exit_reason", "expected_exit_base"),
    [
        (IntrabarPolicy.STOP_FIRST, "STOP_LOSS", Decimal("90")),
        (IntrabarPolicy.TAKE_FIRST, "TAKE_PROFIT", Decimal("120")),
    ],
)
def test_runner_enters_on_next_bar_and_handles_intrabar_stop_or_target(policy, expected_exit_reason, expected_exit_base):
    candles = (
        _candle(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), base=100),
        _candle(datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), base=101),
        _candle(datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc), base=102),
        Candle.from_dict(
            {
                "open_time": datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc),
                "close_time": datetime(2026, 1, 1, 3, 59, 59, 999000, tzinfo=timezone.utc),
                "open": "100",
                "high": "130",
                "low": "70",
                "close": "110",
                "volume": "1500",
                "symbol": "BTC-USDT",
                "interval": "1H",
                "source": DataSource.PAPER,
            }
        ),
        _candle(datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc), base=104),
    )
    costs = CostModel(entry_fee_rate=Decimal("0.001"), exit_fee_rate=Decimal("0.002"), spread_bps=Decimal("10"), slippage_bps=Decimal("20"))
    runner = backtest.OfflineResearchBacktestRunner(
        config=BacktestConfig(
            symbol="BTC-USDT",
            interval="1H",
            paper_only=True,
            allow_short=False,
            strategy_version="phase22b_test",
            intrabar_policy=policy,
            gap_policy=GapPolicy.OPEN_PRICE,
        ),
        cost_model=costs,
    )
    result = runner.run(
        candles,
        _paper_order_strategy(
            trigger_index=2,
            quantity=Decimal("2"),
            entry=Decimal("100"),
            stop_loss=Decimal("90"),
            take_profit=Decimal("120"),
        ),
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.trade.reason == expected_exit_reason
    assert trade.entry_index == 3
    assert trade.exit_index == 3
    assert trade.entry_fill.filled_at == candles[3].open_time
    assert trade.exit_fill.filled_at == candles[3].close_time
    assert trade.entry_fill.price == costs.build_entry(Decimal("100"), Decimal("2"), Direction.COMPRA).fill_price
    assert trade.exit_fill.price == costs.build_exit(expected_exit_base, Decimal("2"), Direction.COMPRA).fill_price
    assert trade.gross_pnl == (expected_exit_base - Decimal("100")) * Decimal("2")
    assert trade.total_costs == trade.entry_fee + trade.exit_fee + trade.spread_cost + trade.slippage_cost
    assert trade.net_pnl == trade.gross_pnl - trade.total_costs


def test_runner_marks_final_close_when_no_stop_or_target_is_hit():
    candles = (
        _candle(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), base=100),
        _candle(datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), base=101),
        _candle(datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc), base=102),
        Candle.from_dict(
            {
                "open_time": datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc),
                "close_time": datetime(2026, 1, 1, 3, 59, 59, 999000, tzinfo=timezone.utc),
                "open": "100",
                "high": "106",
                "low": "99",
                "close": "104",
                "volume": "1500",
                "symbol": "BTC-USDT",
                "interval": "1H",
                "source": DataSource.PAPER,
            }
        ),
        Candle.from_dict(
            {
                "open_time": datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc),
                "close_time": datetime(2026, 1, 1, 4, 59, 59, 999000, tzinfo=timezone.utc),
                "open": "104",
                "high": "107",
                "low": "103",
                "close": "106",
                "volume": "1600",
                "symbol": "BTC-USDT",
                "interval": "1H",
                "source": DataSource.PAPER,
            }
        ),
    )
    runner = backtest.OfflineResearchBacktestRunner(
        config=BacktestConfig(
            symbol="BTC-USDT",
            interval="1H",
            paper_only=True,
            allow_short=False,
            strategy_version="phase22b_test",
            intrabar_policy=IntrabarPolicy.STOP_FIRST,
            gap_policy=GapPolicy.OPEN_PRICE,
        ),
        cost_model=CostModel(entry_fee_rate=Decimal("0"), exit_fee_rate=Decimal("0"), spread_bps=Decimal("0"), slippage_bps=Decimal("0")),
    )
    result = runner.run(
        candles,
        _paper_order_strategy(
            trigger_index=2,
            quantity=Decimal("1"),
            entry=Decimal("100"),
            stop_loss=Decimal("90"),
            take_profit=Decimal("120"),
        ),
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.trade.reason == "FINAL_CLOSE"
    assert trade.exit_fill.filled_at == candles[-1].close_time
    assert result.summary["total_trades"] == 1
    assert result.summary["profit_factor_state"] == "undefined_no_losses"


def test_experiment_contract_builds_for_real_okx_artifact_and_projects_surface(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, "get", _fail_network, raising=True)
    auth = _verified_authorization()
    compat = _compatible_contract(auth)
    decision = compatibility.evaluate_offline_research_strategy_compatibility(
        auth,
        compat,
        decided_at_utc=datetime(2026, 7, 27, 16, 31, 34, tzinfo=timezone.utc),
    )
    strategy_contract = build_baseline_a_okx_btc_usdt_research_contract(auth, decision)
    dataset = _real_phase19a_dataset()
    experiment = backtest.build_offline_research_backtest_experiment_contract(
        authorization=auth,
        compatibility_decision=decision,
        strategy_contract=strategy_contract,
        dataset=dataset,
        executed_at_utc=datetime(2026, 7, 27, 16, 31, 35, tzinfo=timezone.utc),
    )
    projected = backtest._project_dataset_to_research_surface(dataset, symbol=strategy_contract.symbol)

    assert experiment.provider_name == "OKX"
    assert experiment.market_type == "spot"
    assert experiment.symbol == "BTC-USDT"
    assert experiment.canonical_symbol == "BTCUSDT"
    assert experiment.interval == "1H"
    assert experiment.historical_research_only is True
    assert experiment.operational_evidence is False
    assert experiment.paper_promotion_eligible is False
    assert experiment.allowed_use_cases == ("offline_historical_research",)
    assert experiment.prohibited_use_cases == backtest.OFFLINE_RESEARCH_BACKTEST_EXPERIMENT_PROHIBITED_USE_CASES
    assert experiment.strategy_contract_hash == strategy_contract.contract_hash
    assert experiment.authorization_hash == auth.authorization_hash
    assert experiment.compatibility_hash == decision.compatibility_hash
    assert dataset.manifest.found_candle_count == registry.OKX_RESEARCH_ARTIFACT_EXPECTED_CANDLE_COUNT
    assert projected[0].symbol == "BTC-USDT"
    assert projected[0].source == DataSource.PAPER
    assert projected[-1].symbol == "BTC-USDT"


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda auth, compat, contract, dataset: object.__setattr__(auth, "provider_name", "KuCoin"), "authorization provider_name must be OKX"),
        (lambda auth, compat, contract, dataset: object.__setattr__(compat, "symbol", "BTCUSDT"), "compatibility symbol must be BTC-USDT"),
        (lambda auth, compat, contract, dataset: object.__setattr__(contract, "symbol", "BTCUSDT"), "strategy symbol must be BTC-USDT"),
        (lambda auth, compat, contract, dataset: object.__setattr__(dataset.manifest.contract, "provider_id", "kucoin.public.klines"), "dataset provider_id must be okx.public.klines"),
        (lambda auth, compat, contract, dataset: object.__setattr__(auth, "paper_promotion_eligible", True), "paper_promotion_eligible must be false"),
    ],
)
def test_experiment_contract_rejects_kucoin_btcusdt_and_operational_flags(mutator, expected):
    auth = copy.deepcopy(_verified_authorization())
    compat = _compatible_contract(auth)
    decision = compatibility.evaluate_offline_research_strategy_compatibility(
        auth,
        compat,
        decided_at_utc=datetime(2026, 7, 27, 16, 31, 34, tzinfo=timezone.utc),
    )
    strategy_contract = build_baseline_a_okx_btc_usdt_research_contract(auth, decision)
    dataset = copy.deepcopy(_real_phase19a_dataset())
    mutator(auth, decision, strategy_contract, dataset)

    with pytest.raises(backtest.OfflineResearchBacktestValidationError, match=expected):
        backtest.build_offline_research_backtest_experiment_contract(
            authorization=auth,
            compatibility_decision=decision,
            strategy_contract=strategy_contract,
            dataset=dataset,
        )


def test_backtest_runner_result_is_reproducible_with_same_inputs():
    candles = _history(count=5)
    runner = backtest.OfflineResearchBacktestRunner(
        config=BacktestConfig(
            symbol="BTC-USDT",
            interval="1H",
            paper_only=True,
            allow_short=False,
            strategy_version="phase22b_test",
            intrabar_policy=IntrabarPolicy.STOP_FIRST,
            gap_policy=GapPolicy.OPEN_PRICE,
        ),
        cost_model=CostModel(entry_fee_rate=Decimal("0.0004"), exit_fee_rate=Decimal("0.0004"), spread_bps=Decimal("5"), slippage_bps=Decimal("5")),
    )
    strategy = _signal_strategy(2)
    first = runner.run(candles, strategy)
    second = runner.run(candles, strategy)

    assert first.to_dict() == second.to_dict()
    assert first.summary == second.summary
