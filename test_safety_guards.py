"""Unit tests for safety_guards — the real-time in-bot safety reactions (spec 2026-07-08).
Pure functions + OrderRateBreaker; each must be defensive (fail-open) and never block
legitimate trading on its own error."""

from safety_guards import (
    guard_quote, should_send_sl_modify,
    position_loss_anomalous, cycle_loss_spike, scanner_stalled,
    OrderRateBreaker,
)


# ── Tier 1: quote guard ────────────────────────────────────────────────────────────────
def test_guard_quote_accepts_normal_tick():
    assert guard_quote(101.0, 100.0, 1.0)[0] is True


def test_guard_quote_rejects_nonpositive():
    assert guard_quote(0.0, 100.0, 1.0)[0] is False
    assert guard_quote(-5.0, 100.0, 1.0)[0] is False
    assert guard_quote(None, 100.0, 1.0)[0] is False


def test_guard_quote_rejects_stale():
    ok, reason = guard_quote(100.5, 100.0, 45.0, stale_seconds=30.0)
    assert ok is False and "stale" in reason


def test_guard_quote_rejects_implausible_jump():
    ok, reason = guard_quote(130.0, 100.0, 1.0, jump_reject_pct=20.0)  # +30%
    assert ok is False and "jump" in reason


def test_guard_quote_allows_first_tick_no_last_good():
    assert guard_quote(100.0, None, None)[0] is True


def test_guard_quote_allows_normal_volatility_below_threshold():
    assert guard_quote(119.0, 100.0, 1.0, jump_reject_pct=20.0)[0] is True  # +19%


def test_should_send_sl_modify_true_when_changed_or_first():
    assert should_send_sl_modify(None, 100.0, 99.5) is True
    assert should_send_sl_modify((100.0, 99.5), 100.5, 100.0) is True


def test_should_send_sl_modify_false_when_identical():
    assert should_send_sl_modify((100.0, 99.5), 100.0, 99.5) is False


# ── Tier 2/3 predicates ────────────────────────────────────────────────────────────────
def test_position_loss_anomalous_long():
    # risk = |100-98|*10 = 20; k=3 => trips when loss > 60 => current < 94
    assert position_loss_anomalous(100, 98, 10, 93.9, "LONG", k=3.0) is True
    assert position_loss_anomalous(100, 98, 10, 94.5, "LONG", k=3.0) is False


def test_position_loss_anomalous_short():
    assert position_loss_anomalous(100, 102, 10, 106.1, "SHORT", k=3.0) is True
    assert position_loss_anomalous(100, 102, 10, 105.0, "SHORT", k=3.0) is False


def test_position_loss_anomalous_zero_risk_safe():
    assert position_loss_anomalous(100, 100, 10, 50, "LONG", k=3.0) is False


def test_cycle_loss_spike():
    assert cycle_loss_spike(-500.0, -5000.0, 4000.0) is True   # dropped 4500 > 4000
    assert cycle_loss_spike(-500.0, -1000.0, 4000.0) is False  # dropped 500
    assert cycle_loss_spike(None, -9999.0, 4000.0) is False    # no prior


def test_scanner_stalled():
    assert scanner_stalled(1000.0, 1000.0 + 9 * 60, True, stall_minutes=8.0) is True
    assert scanner_stalled(1000.0, 1000.0 + 5 * 60, True, stall_minutes=8.0) is False
    assert scanner_stalled(1000.0, 1000.0 + 9 * 60, False, stall_minutes=8.0) is False
    assert scanner_stalled(None, 9999.0, True) is False


# ── OrderRateBreaker ───────────────────────────────────────────────────────────────────
def test_order_rate_breaker_trips_over_limit():
    t = [0.0]
    b = OrderRateBreaker(max_orders=3, window_seconds=10.0, time_fn=lambda: t[0])
    assert b.record_and_check() is False  # 1
    assert b.record_and_check() is False  # 2
    assert b.record_and_check() is False  # 3
    assert b.record_and_check() is True   # 4 > 3 within window


def test_order_rate_breaker_window_expiry():
    t = [0.0]
    b = OrderRateBreaker(max_orders=2, window_seconds=10.0, time_fn=lambda: t[0])
    b.record_and_check()
    b.record_and_check()
    t[0] = 11.0  # old events fall out of the window
    assert b.record_and_check() is False


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
