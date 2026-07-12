"""Real-time in-bot safety guards (spec: docs/superpowers/specs/2026-07-08-realtime-safety-guards-design.md).

Pure functions + OrderRateBreaker, wired into main.py's loops. Tiered posture: Tier-1 blocks the
bad action, Tier-2 halts only on a true catastrophe, Tier-3 alerts. Each guard is defensive: an
internal error must never itself halt or block legitimate trading (fail-open for Tier-1/3; Tier-2
halts only on an explicit positive detection)."""

from __future__ import annotations

import time
from collections import deque


# ── Tier 1: block the bad action, keep trading ─────────────────────────────────────────────

def guard_quote(new_ltp, last_good_ltp, seconds_since_update, *,
                stale_seconds=30.0, jump_reject_pct=20.0):
    """(ok, reason). ok=False => do NOT act on new_ltp; keep using last_good_ltp.
    Rejects a provably-broken tick only: non-positive, stale, or implausible single-step jump.
    Fails open (ok=True) on any internal error so a guard bug never blocks trading."""
    try:
        if new_ltp is None or new_ltp <= 0:
            return False, "non-positive/absent price"
        if seconds_since_update is not None and seconds_since_update > stale_seconds:
            return False, f"stale quote ({seconds_since_update:.0f}s > {stale_seconds:.0f}s)"
        if last_good_ltp and last_good_ltp > 0:
            jump = abs(new_ltp - last_good_ltp) / last_good_ltp * 100.0
            if jump > jump_reject_pct:
                return False, f"implausible jump {jump:.1f}% (> {jump_reject_pct:.0f}%)"
        return True, "ok"
    except Exception:
        return True, "ok (guard error, fail-open)"


def circuit_proximity_ok(price, upper=None, lower=None, *, buffer_pct=0.02):
    """(ok, reason). ok=False => entry price is within buffer_pct of the day's upper/lower
    circuit limit, where fills are unreliable and you can get stuck unable to exit. Fails
    open (ok=True) when limits are absent/zero or on any internal error, so a missing field
    never blocks a legitimate trade."""
    try:
        if price is None or price <= 0:
            return True, "no price (allow)"
        if upper and upper > 0 and price >= upper * (1.0 - buffer_pct):
            return False, f"within {buffer_pct:.0%} of upper circuit ₹{upper}"
        if lower and lower > 0 and price <= lower * (1.0 + buffer_pct):
            return False, f"within {buffer_pct:.0%} of lower circuit ₹{lower}"
        return True, "ok"
    except Exception:
        return True, "ok (guard error, fail-open)"


def should_send_sl_modify(last_sent, new_trigger, new_limit):
    """last_sent: (trigger, limit) tuple or None. True to send the modify (changed / first),
    False to skip a redundant identical re-send."""
    return last_sent != (new_trigger, new_limit)


# ── Tier 2: halt / force-exit on catastrophe ───────────────────────────────────────────────

def position_loss_anomalous(entry_price, stop_loss, quantity, current_price, direction, *, k=3.0):
    """True if unrealized loss exceeds k x intended risk (|entry-stop|*qty) — the stop should
    have fired, so this signals a gap/data/broker glitch. Caller force-exits that position."""
    try:
        risk = abs(entry_price - stop_loss) * quantity
        if risk <= 0:
            return False
        loss = (entry_price - current_price) * quantity if direction == "LONG" \
            else (current_price - entry_price) * quantity
        return loss > k * risk
    except Exception:
        return False


def cycle_loss_spike(prev_total_pnl, cur_total_pnl, max_daily_loss):
    """True if total daily P&L dropped by more than the whole daily-loss limit within one ~1s
    cycle — impossible in normal trading, so treat as a data glitch and halt."""
    try:
        if prev_total_pnl is None or max_daily_loss <= 0:
            return False
        return (prev_total_pnl - cur_total_pnl) > max_daily_loss
    except Exception:
        return False


# ── Tier 3: self-heal / alert ──────────────────────────────────────────────────────────────

def scanner_stalled(last_scan_epoch, now_epoch, within_trade_window, *, stall_minutes=8.0):
    """True if, during the trade window, no scan has completed in > stall_minutes."""
    try:
        if not within_trade_window or last_scan_epoch is None:
            return False
        return (now_epoch - last_scan_epoch) > stall_minutes * 60.0
    except Exception:
        return False


class OrderRateBreaker:
    """Trips when more than max_orders submissions occur within window_seconds (runaway loop)."""

    def __init__(self, max_orders=20, window_seconds=10.0, time_fn=time.monotonic):
        self.max_orders = max_orders
        self.window_seconds = window_seconds
        self._time = time_fn
        self._events = deque()
        self.tripped = False

    def record_and_check(self):
        now = self._time()
        self._events.append(now)
        while self._events and now - self._events[0] > self.window_seconds:
            self._events.popleft()
        if len(self._events) > self.max_orders:
            self.tripped = True
        return self.tripped
