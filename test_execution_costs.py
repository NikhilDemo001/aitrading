"""Unit tests for execution_costs — realistic paper fills + NSE intraday-equity charges.
Values hand-computed so the model is pinned, not just self-consistent."""

import pytest

from execution_costs import apply_fill_slippage, intraday_equity_charges, net_risk_reward


def _no_charges():
    return {"brokerage_per_order": 0.0, "stt_pct": 0.0, "exchange_txn_pct": 0.0,
            "gst_pct": 0.0, "sebi_per_crore": 0.0, "stamp_pct": 0.0}


# ── fill slippage ──────────────────────────────────────────────────────────────────────
def test_slippage_buy_lifts_sell_drops_clean():
    # spread_bps=10, slippage_bps=0 => adj = 5bps = 0.0005; on 200 => +/-0.1
    assert apply_fill_slippage(200.0, "BUY", spread_bps=10, slippage_bps=0) == pytest.approx(200.10)
    assert apply_fill_slippage(200.0, "SELL", spread_bps=10, slippage_bps=0) == pytest.approx(199.90)


def test_slippage_direction_with_defaults():
    buy = apply_fill_slippage(100.0, "BUY")
    sell = apply_fill_slippage(100.0, "SELL")
    assert buy > 100.0 > sell


def test_slippage_safe_on_bad_price():
    assert apply_fill_slippage(0.0, "BUY") == 0.0
    assert apply_fill_slippage(None, "SELL") is None


def test_slippage_uses_real_spread_when_provided():
    # real_spread_bps=100 (half=50bps) overrides config spread_bps=3; slippage 0 => +0.5%
    assert apply_fill_slippage(100.0, "BUY", spread_bps=3, slippage_bps=0,
                               real_spread_bps=100) == pytest.approx(100.5)
    # None/<=0 real spread falls back to config spread (10bps => half 5bps => +0.05%)
    assert apply_fill_slippage(100.0, "BUY", spread_bps=10, slippage_bps=0,
                               real_spread_bps=None) == pytest.approx(100.05)


# ── transaction charges ────────────────────────────────────────────────────────────────
def test_charges_50k_round_trip():
    ch = intraday_equity_charges(50000.0, 50000.0)
    # brokerage 20+20=40; stt 12.5; exchange 2.97; gst 0.18*(40+2.97)=7.73; sebi 0.1; stamp 1.5
    assert ch["brokerage"] == pytest.approx(40.0)
    assert ch["stt"] == pytest.approx(12.5)
    assert ch["stamp"] == pytest.approx(1.5)
    assert ch["total"] == pytest.approx(64.80, abs=0.05)


def test_charges_small_trade_brokerage_dominates():
    # ₹5k/leg: 0.025*5000=125 > 20, so flat ₹20/leg dominates
    ch = intraday_equity_charges(5000.0, 5000.0)
    assert ch["brokerage"] == pytest.approx(40.0)
    assert ch["total"] == pytest.approx(48.96, abs=0.05)
    # cost is ~1% of turnover — kills small-move trades
    assert ch["total"] / 10000.0 > 0.004


def test_charges_percentage_brokerage_cap_on_tiny_leg():
    # ₹400/leg: 0.025*400=10 < 20, so 2.5% applies => 10/leg
    ch = intraday_equity_charges(400.0, 400.0)
    assert ch["brokerage"] == pytest.approx(20.0)  # 10 + 10


def test_charges_zero_safe():
    ch = intraday_equity_charges(0.0, 0.0)
    assert ch["total"] == 0.0


# ── cost-adjusted risk:reward ────────────────────────────────────────────────────────────
def test_net_rr_equals_gross_when_costless():
    # entry 100, stop 99 (risk 1), target 103 (reward 3) => gross 3:1; zero costs => 3.0
    rr = net_risk_reward(100.0, 99.0, 103.0, 100, spread_bps=0, slippage_bps=0, charges=_no_charges())
    assert rr == pytest.approx(3.0)


def test_net_rr_below_gross_with_default_costs():
    rr = net_risk_reward(100.0, 99.0, 103.0, 100)   # default slippage + charges
    assert 0 < rr < 3.0


def test_net_rr_zero_when_no_risk_and_no_costs():
    rr = net_risk_reward(100.0, 100.0, 103.0, 100, spread_bps=0, slippage_bps=0, charges=_no_charges())
    assert rr == 0.0


def test_net_rr_costs_flip_marginal_small_trade_below_one():
    # gross 2.5:1 (reward 0.5, risk 0.2) but tiny ₹1000 leg — ₹40 round-trip brokerage
    # dwarfs the ₹5 edge, so net R:R collapses below 1.
    gross = abs(100.5 - 100.0) / abs(100.0 - 99.8)
    rr = net_risk_reward(100.0, 99.8, 100.5, 10)
    assert gross > 2.0 and rr < 1.0


def test_net_rr_safe_on_bad_input():
    assert net_risk_reward(0.0, 0.0, 0.0, 0) == 0.0
    assert net_risk_reward(100.0, 99.0, 103.0, 0) == 0.0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
