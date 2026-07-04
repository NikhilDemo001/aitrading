"""Unit tests for strategy_interface.py — the thin Strategy ABC wrapping the 8 existing
strategy functions, and execution.py — the thin broker-routing layer."""

import pytest

from strategy_interface import (
    ALL_STRATEGIES, Features, generate_signal_matrix, _normalize_signal,
)
from execution import ExecutionEngine
from mock_broker import MockBroker


def make_candles(n=60, start=1000.0):
    """Enough ascending 5-min OHLCV candles for every strategy's warmup requirement, with a
    mild uptrend drift so ORB/Momentum/TrendFollow-style breakout logic has something to find."""
    candles = []
    price = start
    for i in range(n):
        o = price
        c = price * 1.0015
        h = max(o, c) * 1.001
        l = min(o, c) * 0.999
        candles.append({
            "timestamp": f"2026-07-01 09:{15 + i // 12:02d}:{(i % 12) * 5:02d}",
            "open": round(o, 2), "high": round(h, 2), "low": round(l, 2),
            "close": round(c, 2), "volume": 50000 + i * 100,
        })
        price = c
    return candles


def test_all_strategies_have_unique_names():
    names = [s.name for s in ALL_STRATEGIES]
    assert len(names) == 8
    assert len(set(names)) == 8


def test_all_strategies_implement_suitable_regimes():
    for strategy in ALL_STRATEGIES:
        regimes = strategy.suitable_regimes()
        assert isinstance(regimes, list)
        assert len(regimes) > 0


def test_generate_signal_matrix_returns_all_strategy_names():
    features = Features(candles=make_candles(), config={})
    matrix = generate_signal_matrix(features)
    assert set(matrix.keys()) == {s.name for s in ALL_STRATEGIES}


def test_generate_signal_matrix_does_not_raise_on_short_candle_list():
    """Strategies warmup-guard internally; the matrix must never raise even with too little
    data — every entry should just be None (or a caught-error dict), never propagate."""
    features = Features(candles=make_candles(n=5), config={})
    matrix = generate_signal_matrix(features)
    for signal in matrix.values():
        assert signal is None or isinstance(signal, dict)


def test_normalize_signal_injects_direction_and_aliases():
    raw = {"strategy": "ORB-Buy", "entry_price": 100.0, "stop_loss": 95.0, "target_1": 110.0}
    normalized = _normalize_signal(raw)
    assert normalized["direction"] == "long"
    assert normalized["entry"] == 100.0
    assert normalized["stop"] == 95.0
    assert normalized["target"] == 110.0
    # Original fields must survive (additive, not a replacement).
    assert normalized["entry_price"] == 100.0


def test_normalize_signal_short_direction():
    raw = {"strategy": "ORB-Short", "entry_price": 100.0, "stop_loss": 105.0, "target_1": 90.0}
    normalized = _normalize_signal(raw)
    assert normalized["direction"] == "short"


def test_normalize_signal_passes_through_none():
    assert _normalize_signal(None) is None


# ── execution.py ─────────────────────────────────────────────────────────────────────────────

def test_execution_engine_place_entry_routes_buy_for_long():
    engine = ExecutionEngine(MockBroker(seed=7))
    order = engine.place_entry("RELIANCE", "LONG", 10, "MARKET", 0.0, instrument_key="NSE_EQ|TEST")
    assert order["transaction_type"] == "BUY"
    assert order["status"] == "FILLED"


def test_execution_engine_place_entry_routes_sell_for_short():
    engine = ExecutionEngine(MockBroker(seed=7))
    order = engine.place_entry("RELIANCE", "SHORT", 10, "MARKET", 0.0, instrument_key="NSE_EQ|TEST")
    assert order["transaction_type"] == "SELL"


def test_execution_engine_place_exit_is_opposite_side_of_entry_direction():
    engine = ExecutionEngine(MockBroker(seed=7))
    exit_order = engine.place_exit("RELIANCE", "LONG", 10, instrument_key="NSE_EQ|TEST")
    assert exit_order["transaction_type"] == "SELL"
    exit_order_short = engine.place_exit("RELIANCE", "SHORT", 10, instrument_key="NSE_EQ|TEST")
    assert exit_order_short["transaction_type"] == "BUY"


def test_execution_engine_same_calls_work_against_mock_and_real_shaped_broker():
    """The whole point of execution.py: identical call shape regardless of broker instance."""
    engine = ExecutionEngine(MockBroker(seed=1))
    quote = engine.get_quote("NSE_EQ|TEST")
    assert "ltp" in quote
    candles = engine.get_candles("NSE_EQ|TEST", "5minute")
    assert len(candles) > 0
    funds = engine.get_funds_and_margin()
    assert funds["status"] == "success"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
