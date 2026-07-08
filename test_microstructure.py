"""Unit tests for microstructure — order-book depth parsing + spread/liquidity gating."""

import pytest

from microstructure import normalize_depth, spread_bps, liquidity_ok


def _raw(bid, ask, bq=1000, aq=1000):
    return {"buy": [{"price": bid, "quantity": bq, "orders": 2}],
            "sell": [{"price": ask, "quantity": aq, "orders": 2}]}


# ── normalize_depth ────────────────────────────────────────────────────────────────────
def test_normalize_depth_basic():
    b = normalize_depth(_raw(668.5, 668.7, 300, 450))
    assert b["best_bid"] == 668.5 and b["best_ask"] == 668.7
    assert b["bid_qty"] == 300 and b["ask_qty"] == 450
    assert b["mid"] == pytest.approx(668.6)
    assert b["spread"] == pytest.approx(0.2)


def test_normalize_depth_missing_or_empty():
    assert normalize_depth(None) is None
    assert normalize_depth({}) is None
    assert normalize_depth({"buy": [], "sell": []}) is None


def test_normalize_depth_crossed_or_zero_is_none():
    assert normalize_depth(_raw(0, 100)) is None       # zero bid
    assert normalize_depth(_raw(101, 100)) is None      # crossed (ask < bid)


# ── spread_bps ─────────────────────────────────────────────────────────────────────────
def test_spread_bps():
    # mid 100, spread 0.1 => 10 bps
    assert spread_bps(99.95, 100.05) == pytest.approx(10.0, abs=0.01)
    assert spread_bps(0, 0) is None


# ── liquidity_ok ───────────────────────────────────────────────────────────────────────
def test_liquidity_ok_tight_spread_passes():
    ok, _ = liquidity_ok(normalize_depth(_raw(99.95, 100.05)), max_spread_bps=50)
    assert ok is True


def test_liquidity_ok_wide_spread_rejected():
    ok, why = liquidity_ok(normalize_depth(_raw(98.0, 100.0)), max_spread_bps=50)  # ~200 bps
    assert ok is False and "spread" in why


def test_liquidity_ok_no_depth_allows():
    ok, why = liquidity_ok(None, max_spread_bps=50)
    assert ok is True


def test_liquidity_ok_order_size_vs_depth():
    book = normalize_depth(_raw(99.99, 100.01, bq=100, aq=100))  # tight spread, thin book
    ok_small, _ = liquidity_ok(book, order_qty=100, min_depth_ratio=0.5)   # need 50, have 100
    assert ok_small is True
    ok_big, why = liquidity_ok(book, order_qty=1000, min_depth_ratio=0.5)  # need 500, have 100
    assert ok_big is False and "book" in why


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
