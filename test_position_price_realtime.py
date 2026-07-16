"""Regression tests for the active-position live-price freeze (2026-07-13).

Root cause: manage_existing_positions passed guard_quote the time since the *last
accepted tick* as `seconds_since_update`. During a REST fetch gap (e.g. Upstox
rate-limiting) that value balloons past `quote_stale_seconds`, so the first fresh
quote after the gap was rejected as "stale" — and because the reject branch never
advanced the timestamp, EVERY subsequent quote stayed rejected and current_price
froze until process restart.

The fix moves the per-tick decision into safety_guards.evaluate_live_tick(), which
does NOT re-check staleness (quotes reaching the position manager are always fresh:
a live REST fetch, or a cache entry already bounded to a few seconds). A genuinely
frozen feed is still caught upstream by the missing-quote path. Non-positive and
implausible-jump ticks are still rejected.
"""

from safety_guards import evaluate_live_tick


def _apply(pos, ltp, *, jump_reject_pct=20.0):
    """Mirror of the position-manager per-tick block, post-fix."""
    price, ok, _why = evaluate_live_tick(ltp, pos.get("current_price"),
                                         jump_reject_pct=jump_reject_pct)
    pos["current_price"] = price
    return ok


def test_fresh_tick_after_long_gap_is_accepted():
    # This is the exact scenario that used to lock up: a valid last price, then a
    # brand-new quote arriving long after the previous accepted one.
    pos = {"current_price": 100.0}
    assert _apply(pos, 100.5) is True
    assert pos["current_price"] == 100.5
    # Simulate a >30s fetch gap, then a fresh quote — must be accepted, not frozen.
    assert _apply(pos, 101.0) is True
    assert pos["current_price"] == 101.0
    # And it keeps updating on every subsequent tick (no permanent lockout).
    assert _apply(pos, 101.5) is True
    assert pos["current_price"] == 101.5


def test_nonpositive_tick_rejected_keeps_last_price():
    pos = {"current_price": 100.0}
    assert _apply(pos, 0.0) is False
    assert pos["current_price"] == 100.0
    assert _apply(pos, -5.0) is False
    assert pos["current_price"] == 100.0


def test_implausible_jump_rejected_keeps_last_price():
    pos = {"current_price": 100.0}
    assert _apply(pos, 200.0) is False  # +100% single-step jump
    assert pos["current_price"] == 100.0
    # Normal volatility passes through.
    assert _apply(pos, 103.0) is True
    assert pos["current_price"] == 103.0


def test_first_tick_with_no_prior_price_is_accepted():
    pos = {}
    assert _apply(pos, 250.0) is True
    assert pos["current_price"] == 250.0
