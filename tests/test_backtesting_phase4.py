from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
import pytest

import backtester
from backtesting import (
    BacktestConfig,
    BacktestGapError,
    BacktestConfigurationError,
    GapPolicy,
    IntrabarPolicy,
    LeakFreeBacktestEngine,
    dataframe_to_candles,
    max_drawdown,
    strategy_output_to_order,
    compute_metrics,
)
from backtesting.errors import BacktestDataError
from backtesting.models import ExecutedTrade
from backtesting.models import EquityPoint
from domain import Candle, DataSource, Direction, DomainValidationError, Fill, OrderStatus, PaperOrder, Position, PositionStatus, Signal, TradeResult, TradeResultStatus, TradingMode


def _candle(open_time: datetime, open_: str, high: str, low: str, close: str, volume: str, symbol: str = "BTCUSDT", interval: str = "1h") -> Candle:
    return Candle.from_dict(
        {
            "open_time": open_time,
            "close_time": open_time + timedelta(hours=1) - timedelta(milliseconds=1),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "symbol": symbol,
            "interval": interval,
            "source": DataSource.PAPER,
        }
    )


def _signal(timestamp: datetime, *, direction=Direction.COMPRA, symbol="BTCUSDT", entry=Decimal("100"), stop=Decimal("95"), take=Decimal("110")) -> Signal:
    return Signal(
        symbol=symbol,
        direction=direction,
        entry=entry,
        stop_loss=stop,
        take_profit=take,
        rr=Decimal("2"),
        timestamp=timestamp,
        source=DataSource.PAPER,
        score=Decimal("6"),
        regime="BULL" if direction == Direction.COMPRA else "BEAR",
        volume_status="ALTO",
        reason="teste",
        strategy_version="v3_leak_free",
    )


def _executed_trade(pnl_reais: str, realized_rr: str, *, symbol="BTCUSDT", direction=Direction.COMPRA) -> ExecutedTrade:
    opened_at = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    closed_at = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    entry = Decimal("100")
    stop = Decimal("95")
    take = Decimal("110")
    quantity = Decimal("1")
    pnl_reais_dec = Decimal(pnl_reais)
    trade = TradeResult(
        symbol=symbol,
        direction=direction,
        entry=entry,
        exit_price=Decimal("110" if pnl_reais_dec >= 0 else "90"),
        quantity=quantity,
        pnl_percent=(pnl_reais_dec / (entry * quantity)) * Decimal("100"),
        pnl_reais=pnl_reais_dec,
        status=TradeResultStatus.CLOSED,
        reason="TESTE",
        opened_at=opened_at,
        closed_at=closed_at,
        source=DataSource.PAPER,
        paper=True,
        trading_mode=TradingMode.PAPER,
        strategy_version="v3_leak_free",
    )
    order = PaperOrder(
        symbol=symbol,
        direction=direction,
        entry=entry,
        quantity=quantity,
        stop_loss=stop,
        take_profit=take,
        opened_at=opened_at,
        status=OrderStatus.CLOSED,
        source=DataSource.PAPER,
        paper=True,
        trading_mode=TradingMode.PAPER,
    )
    entry_fill = Fill(price=entry, quantity=quantity, filled_at=opened_at, fee=Decimal("0"), source=DataSource.PAPER, is_real=False)
    exit_fill = Fill(price=trade.exit_price, quantity=quantity, filled_at=closed_at, fee=Decimal("0"), source=DataSource.PAPER, is_real=False)
    return ExecutedTrade(
        order=order,
        entry_fill=entry_fill,
        exit_fill=exit_fill,
        trade=trade,
        realized_rr=Decimal(realized_rr),
        entry_index=0,
        exit_index=1,
    )


def test_dataframe_to_candles_e_strategy_output_to_order():
    df = pd.DataFrame(
        {
            "open_time": pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC"),
            "close_time": pd.date_range("2026-01-01 00:59:59.999", periods=2, freq="h", tz="UTC"),
            "open": [100, 101],
            "high": [105, 106],
            "low": [99, 100],
            "close": [104, 105],
            "volume": [1000, 1100],
        }
    )
    candles = dataframe_to_candles(df, symbol="BTCUSDT", interval="1h")
    assert len(candles) == 2
    assert candles[0].symbol == "BTCUSDT"
    assert candles[0].source == DataSource.PAPER

    signal = _signal(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc))
    order = strategy_output_to_order(signal, capital=Decimal("10000"), risk_percent=Decimal("1"))
    assert order.paper is True
    assert order.status == OrderStatus.OPEN
    assert order.quantity > 0


def test_dataframe_to_candles_rejeita_frame_invalido():
    df = pd.DataFrame({"open_time": [datetime(2026, 1, 1, tzinfo=timezone.utc)]})
    with pytest.raises(BacktestDataError):
        dataframe_to_candles(df, symbol="BTCUSDT", interval="1h")


def test_engine_rejeita_config_e_ordem_nao_paper():
    with pytest.raises(BacktestConfigurationError):
        BacktestConfig(paper_only=False)

    with pytest.raises(DomainValidationError):
        strategy_output_to_order(
            {
                "symbol": "BTCUSDT",
                "direction": Direction.COMPRA,
                "entry": Decimal("100"),
                "quantity": Decimal("1"),
                "stop_loss": Decimal("95"),
                "take_profit": Decimal("110"),
                "opened_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "status": OrderStatus.OPEN,
                "source": DataSource.PAPER,
                "paper": False,
                "trading_mode": TradingMode.PAPER,
            },
            capital=Decimal("10000"),
            risk_percent=Decimal("1"),
        )


def test_engine_no_lookahead_and_prefix_only():
    candles = tuple(
        _candle(datetime(2026, 1, 1, idx, 0, tzinfo=timezone.utc), str(100 + idx), str(105 + idx), str(95 + idx), str(102 + idx), str(1000 + idx))
        for idx in range(4)
    )
    seen = []

    def strategy(history, snapshot):
        seen.append((len(history), history[-1].open_time))
        return None

    engine = LeakFreeBacktestEngine(BacktestConfig(initial_capital=Decimal("10000"), risk_percent=Decimal("1")))
    result = engine.run(candles, strategy)

    assert [item[0] for item in seen] == [1, 2, 3]
    assert [item[1] for item in seen] == [c.open_time for c in candles[:3]]
    assert result.trades == ()
    assert result.final_capital == Decimal("10000")


def test_engine_intrabar_stop_first_e_gap_open():
    candles = (
        _candle(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), "100", "101", "99", "100", "1000"),
        _candle(datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), "100", "112", "94", "105", "1000"),
        _candle(datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc), "106", "108", "100", "107", "1000"),
    )
    calls = []

    def strategy(history, snapshot):
        calls.append(len(history))
        if len(history) == 1:
            return _signal(history[-1].close_time, entry=Decimal("100"), stop=Decimal("95"), take=Decimal("110"))
        return None

    engine = LeakFreeBacktestEngine(BacktestConfig(initial_capital=Decimal("10000"), risk_percent=Decimal("1"), slippage_rate=Decimal("0"), commission_rate=Decimal("0")))
    result = engine.run(candles, strategy)

    assert calls[0] == 1
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_index == 1
    assert trade.exit_index == 1
    assert trade.trade.reason == "STOP_LOSS"
    assert trade.trade.pnl_reais < 0
    assert trade.realized_rr < 0


def test_engine_intrabar_take_first_prioriza_take():
    candles = (
        _candle(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), "100", "101", "99", "100", "1000"),
        _candle(datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), "100", "112", "94", "105", "1000"),
    )

    def strategy(history, snapshot):
        if len(history) == 1:
            return _signal(history[-1].close_time, entry=Decimal("100"), stop=Decimal("95"), take=Decimal("110"))
        return None

    engine = LeakFreeBacktestEngine(
        BacktestConfig(
            initial_capital=Decimal("10000"),
            risk_percent=Decimal("1"),
            slippage_rate=Decimal("0"),
            commission_rate=Decimal("0"),
            intrabar_policy=IntrabarPolicy.TAKE_FIRST,
        )
    )
    result = engine.run(candles, strategy)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.trade.reason == "TAKE_PROFIT"
    assert trade.trade.pnl_reais > 0


def test_engine_gap_policy_open_price_and_strict_rejects_gap():
    gap_candles = (
        _candle(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), "100", "101", "99", "100", "1000"),
        _candle(datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc), "100", "105", "95", "104", "1000"),
    )

    engine = LeakFreeBacktestEngine(BacktestConfig(gap_policy=GapPolicy.STRICT))
    with pytest.raises(BacktestGapError):
        engine.run(gap_candles, lambda history, snapshot: None)

    def strategy(history, snapshot):
        if len(history) == 1:
            return _signal(history[-1].close_time, entry=Decimal("100"), stop=Decimal("95"), take=Decimal("110"))
        return None

    open_price_candles = (
        _candle(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), "100", "101", "99", "100", "1000"),
        _candle(datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), "100", "104", "98", "103", "1000"),
        _candle(datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc), "90", "111", "85", "95", "1000"),
    )
    engine = LeakFreeBacktestEngine(BacktestConfig(gap_policy=GapPolicy.OPEN_PRICE, slippage_rate=Decimal("0"), commission_rate=Decimal("0")))
    result = engine.run(open_price_candles, strategy)
    assert result.trades[0].trade.reason == "GAP_STOP"
    assert result.trades[0].exit_fill.price == Decimal("90")


def test_metrics_and_result_serialization():
    trades = (
        _executed_trade("10", "2"),
        _executed_trade("-5", "-1"),
    )
    curve = (
        EquityPoint(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), equity=Decimal("1000"), cash=Decimal("1000"), unrealized_pnl=Decimal("0")),
        EquityPoint(timestamp=datetime(2026, 1, 1, 1, tzinfo=timezone.utc), equity=Decimal("1010"), cash=Decimal("1010"), unrealized_pnl=Decimal("0")),
        EquityPoint(timestamp=datetime(2026, 1, 1, 2, tzinfo=timezone.utc), equity=Decimal("1005"), cash=Decimal("1005"), unrealized_pnl=Decimal("0")),
    )
    metrics = compute_metrics(trades, curve, Decimal("1000"))
    assert metrics["total_trades"] == 2
    assert metrics["profit_factor"] == 2.0
    assert metrics["sequencia_maxima_perdas"] == 1
    assert max_drawdown(curve) >= 0

    result = backtester.executar_backtest_leak_free(
        pd.DataFrame(
            {
                "open_time": pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC"),
                "close_time": pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC"),
                "open": [100, 101, 102],
                "high": [101, 102, 103],
                "low": [99, 100, 101],
                "close": [100, 101, 102],
                "volume": [1000, 1000, 1000],
            }
        ),
        lambda history, snapshot: None,
        symbol="BTCUSDT",
        interval="1h",
    )
    assert isinstance(result, dict)
    assert result["summary"]["total_trades"] == 0
    assert result["metadata"]["lookahead_free"] is True
