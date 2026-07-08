# Real-time Safety Guards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add six autonomous in-bot safety reactions (stale/bad-quote guard, trailing-SL dedup, position-anomaly force-exit, cycle-loss spike halt, order-rate breaker, scanner-stall alert) that run in the bot's own loops.

**Architecture:** New `safety_guards.py` module of pure, unit-tested functions + one `OrderRateBreaker` class, wired into existing `main.py` seams. Tiered posture: Tier-1 blocks the bad action, Tier-2 halts only on catastrophe, Tier-3 alerts.

**Tech Stack:** Python 3.14, pytest, ruff. No new dependencies.

## Global Constraints
- Paper==live: guards run on the same code path in both modes.
- Every guard config-toggleable; all thresholds read from `config.json` with defaults.
- Fail-open: a guard's internal exception must never halt/block legitimate trading (Tier-1/3 allow; Tier-2 halts only on explicit positive detection).
- Full `python -m pytest -q` and `python -m ruff check .` must stay green.
- Commit after each task. End commit messages with the Co-Authored-By line.

---

### Task 1: safety_guards.py — Tier-1 pure functions (quote guard + SL dedup)

**Files:**
- Create: `safety_guards.py`
- Test: `test_safety_guards.py`

**Interfaces:**
- Produces: `guard_quote(new_ltp, last_good_ltp, seconds_since_update, *, stale_seconds=30.0, jump_reject_pct=20.0) -> (bool, str)`; `should_send_sl_modify(last_sent, new_trigger, new_limit) -> bool`

- [ ] **Step 1: Write failing tests**
```python
# test_safety_guards.py
from safety_guards import guard_quote, should_send_sl_modify


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
```

- [ ] **Step 2: Run to verify fail** — `python -m pytest test_safety_guards.py -q` → FAIL (ImportError).

- [ ] **Step 3: Implement**
```python
# safety_guards.py
"""Real-time in-bot safety guards (spec: docs/superpowers/specs/2026-07-08-realtime-safety-guards-design.md).
Pure functions + OrderRateBreaker, wired into main.py's loops. Each guard is defensive: an internal
error must never itself halt or block legitimate trading."""

from __future__ import annotations

import time
from collections import deque


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


def should_send_sl_modify(last_sent, new_trigger, new_limit):
    """last_sent: (trigger, limit) tuple or None. True to send the modify (changed / first),
    False to skip a redundant identical re-send."""
    return last_sent != (new_trigger, new_limit)
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest test_safety_guards.py -q` → PASS.

- [ ] **Step 5: Commit** — `git add safety_guards.py test_safety_guards.py && git commit` ("feat: safety_guards Tier-1 pure guards (quote + SL dedup)").

---

### Task 2: Tier-2/3 pure predicates (anomaly, cycle spike, scanner stall)

**Files:** Modify `safety_guards.py`; Test `test_safety_guards.py`

**Interfaces:**
- Produces: `position_loss_anomalous(entry_price, stop_loss, quantity, current_price, direction, *, k=3.0) -> bool`; `cycle_loss_spike(prev_total_pnl, cur_total_pnl, max_daily_loss) -> bool`; `scanner_stalled(last_scan_epoch, now_epoch, within_trade_window, *, stall_minutes=8.0) -> bool`

- [ ] **Step 1: Write failing tests** (append to test_safety_guards.py)
```python
from safety_guards import position_loss_anomalous, cycle_loss_spike, scanner_stalled

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
    assert scanner_stalled(1000.0, 1000.0 + 9*60, True, stall_minutes=8.0) is True
    assert scanner_stalled(1000.0, 1000.0 + 5*60, True, stall_minutes=8.0) is False
    assert scanner_stalled(1000.0, 1000.0 + 9*60, False, stall_minutes=8.0) is False  # outside window
    assert scanner_stalled(None, 9999.0, True) is False
```

- [ ] **Step 2: Run to verify fail** — FAIL (ImportError for new names).

- [ ] **Step 3: Implement** (append to safety_guards.py)
```python
def position_loss_anomalous(entry_price, stop_loss, quantity, current_price, direction, *, k=3.0):
    """True if unrealized loss exceeds k x intended risk (|entry-stop|*qty) — the stop should
    have fired, so this signals a gap/data/broker glitch. Force-exit that position."""
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


def scanner_stalled(last_scan_epoch, now_epoch, within_trade_window, *, stall_minutes=8.0):
    """True if, during the trade window, no scan has completed in > stall_minutes."""
    try:
        if not within_trade_window or last_scan_epoch is None:
            return False
        return (now_epoch - last_scan_epoch) > stall_minutes * 60.0
    except Exception:
        return False
```

- [ ] **Step 4: Run to verify pass** — PASS.
- [ ] **Step 5: Commit** — ("feat: safety_guards Tier-2/3 predicates").

---

### Task 3: OrderRateBreaker

**Files:** Modify `safety_guards.py`; Test `test_safety_guards.py`

**Interfaces:**
- Produces: `OrderRateBreaker(max_orders=20, window_seconds=10.0, time_fn=time.monotonic)` with `.record_and_check() -> bool` and `.tripped: bool`.

- [ ] **Step 1: Write failing tests**
```python
from safety_guards import OrderRateBreaker

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
    b.record_and_check(); b.record_and_check()
    t[0] = 11.0  # old events fall out of the window
    assert b.record_and_check() is False
```

- [ ] **Step 2: Run to verify fail** — FAIL.

- [ ] **Step 3: Implement** (append)
```python
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
```

- [ ] **Step 4: Run to verify pass** — PASS.
- [ ] **Step 5: Commit** — ("feat: OrderRateBreaker").

---

### Task 4: Wire trailing-SL dedup into main.py

**Files:** Modify `main.py` (~2248-2252, the trailing modify).

- [ ] **Step 1:** Add import near other local imports at top of main.py: `import safety_guards`.
- [ ] **Step 2:** At the trailing SL modify (main.py:2249-2252), wrap the `client.modify_order` call:
```python
                                if safety_guards.should_send_sl_modify(
                                        pos.get("last_sl_sent"), sl_trigger, sl_price):
                                    await loop.run_in_executor(
                                        None, client.modify_order, sl_order_id, pos["quantity"], "SL", sl_price, sl_trigger
                                    )
                                    pos["last_sl_sent"] = (sl_trigger, sl_price)
                                    log_scan(symbol, f"Trailing SL order modified on broker: Trigger ₹{sl_trigger} | Limit ₹{sl_price}", "info")
```
- [ ] **Step 3: Verify** — `python -m pytest test_enhancements.py -q` (trailing tests) → PASS; `python -m ruff check main.py` → clean.
- [ ] **Step 4: Commit** — ("feat: dedup identical trailing-SL modifies").

---

### Task 5: Wire stale/bad-quote guard into position_manager_loop

**Files:** Modify `main.py` (~2612-2621, where `pos["current_price"]` is updated from quote ltp).

- [ ] **Step 1:** Replace the in-memory price-update block so a rejected tick keeps the last good price:
```python
                        for pos in active_positions.values():
                            quote = quotes.get(pos["instrument_key"])
                            if quote:
                                ltp = quote["ltp"]
                                import time as _t
                                now_ts = _t.monotonic()
                                secs = now_ts - pos.get("_last_px_ts", now_ts)
                                ok, why = safety_guards.guard_quote(
                                    ltp, pos.get("current_price"), secs,
                                    stale_seconds=float(client.config.get("quote_stale_seconds", 30)),
                                    jump_reject_pct=float(client.config.get("quote_jump_reject_pct", 20)))
                                if not client.config.get("enable_safety_guards", True) or ok:
                                    pos["current_price"] = ltp
                                    pos["_last_px_ts"] = now_ts
                                    if pos["direction"] == "LONG":
                                        pos["pnl"] = (ltp - pos["entry_price"]) * pos["quantity"]
                                    else:
                                        pos["pnl"] = (pos["entry_price"] - ltp) * pos["quantity"]
                                elif not pos.get("_quote_warned"):
                                    log_scan(pos["symbol"], f"Bad tick rejected ({why}) — holding last price ₹{pos.get('current_price')}", "warning")
                                    pos["_quote_warned"] = True
```
(Apply the same guard to the analogous `bot_running` price-update block if present.)
- [ ] **Step 2: Verify** — full `python -m pytest -q` green; ruff clean.
- [ ] **Step 3: Commit** — ("feat: reject broken quote ticks in position monitor").

---

### Task 6: Wire position-anomaly force-exit + cycle-loss spike halt

**Files:** Modify `main.py` (position_manager_loop, near the fast daily-loss check ~2628).

- [ ] **Step 1:** Add a module-global near other globals: `_prev_total_pnl = None`.
- [ ] **Step 2:** In the fast-halt block, before/after the existing daily-loss check, add:
```python
                    if client.config.get("enable_safety_guards", True) and bot_running and active_positions:
                        # Position-anomaly force-exit (stop failed to fire)
                        k = float(client.config.get("position_anomaly_k", 3.0))
                        for _sym, _pos in list(active_positions.items()):
                            if safety_guards.position_loss_anomalous(
                                    _pos["entry_price"], _pos["stop_loss"], _pos["quantity"],
                                    _pos.get("current_price", _pos["entry_price"]), _pos["direction"], k=k):
                                log_scan(_sym, f"ANOMALY: loss > {k}x risk — stop failed to fire; force-exiting.", "danger")
                                if await execute_exit(_sym, _pos, _pos.get("current_price", _pos["entry_price"]),
                                                      "SAFETY ANOMALY FORCE-EXIT", client.config.get("paper_trading", True)):
                                    _remove_position(_sym)
                        # Cycle-loss spike halt (data glitch)
                        global _prev_total_pnl
                        cur_total = get_total_daily_pnl()
                        if safety_guards.cycle_loss_spike(_prev_total_pnl, cur_total,
                                                          float(client.config.get("max_daily_loss", 4000))):
                            log_scan("SYSTEM", f"ANOMALY: daily P&L dropped >1 limit in one cycle ({_prev_total_pnl}→{cur_total}) — halting.", "danger")
                            bot_running = False
                            await square_off_all("SAFETY CYCLE-LOSS SPIKE")
                        _prev_total_pnl = cur_total
```
- [ ] **Step 2b:** Declare `global _prev_total_pnl` at the top of `position_manager_loop` alongside other globals.
- [ ] **Step 3: Verify** — full pytest green; ruff clean.
- [ ] **Step 4: Commit** — ("feat: position-anomaly force-exit + cycle-loss spike halt").

---

### Task 7: Wire order-rate breaker into OrderQueue

**Files:** Modify `main.py` (`OrderQueue` ~78-130 and its construction in `lifespan`).

- [ ] **Step 1:** In `OrderQueue.__init__`, add:
```python
        from safety_guards import OrderRateBreaker
        self.breaker = OrderRateBreaker(
            max_orders=int(client.config.get("order_rate_max", 20)),
            window_seconds=float(client.config.get("order_rate_window_s", 10)))
        self.on_runaway = None
```
- [ ] **Step 2:** At the top of `OrderQueue.submit`, before enqueuing:
```python
        if client.config.get("enable_safety_guards", True) and self.breaker.record_and_check():
            print("[OrderRateBreaker] Runaway order rate — refusing new orders.")
            if self.on_runaway:
                self.on_runaway()
            raise RuntimeError("order-rate breaker tripped")
```
- [ ] **Step 3:** In `lifespan`, after `order_queue = OrderQueue(...)`, set the callback:
```python
    def _runaway_halt():
        global bot_running
        bot_running = False
        log_scan("SYSTEM", "Order-rate breaker tripped — bot halted. Investigate a runaway loop.", "danger")
    order_queue.on_runaway = _runaway_halt
```
- [ ] **Step 4: Verify** — full pytest green (existing OrderQueue-dependent tests still pass); ruff clean.
- [ ] **Step 5: Commit** — ("feat: order-rate circuit breaker in OrderQueue").

---

### Task 8: Wire scanner-stall alert into scanner_loop

**Files:** Modify `main.py` (`scanner_state` def ~470; scanner_loop top ~1052; scan-complete ~1616).

- [ ] **Step 1:** Add `"last_scan_epoch": None,` to the `scanner_state` dict.
- [ ] **Step 2:** At scan completion (~1616, alongside `scanner_state["last_scan"] = ...`), add: `scanner_state["last_scan_epoch"] = time.monotonic()` (import time at top if not present).
- [ ] **Step 3:** At the top of the scanner loop body (~1052), add a throttled alert:
```python
        if client.config.get("enable_safety_guards", True):
            in_window = is_within_window(cfg.get("trade_start_time", "09:30"), cfg.get("trade_end_time", "14:30")) \
                if False else True  # stall check applies during running hours
            if safety_guards.scanner_stalled(scanner_state.get("last_scan_epoch"), time.monotonic(),
                                             bot_running, stall_minutes=float(cfg.get("scanner_stall_minutes", 8))):
                if get_ist_now().second < 15:  # throttle to ~once/min
                    log_scan("SYSTEM", "Scanner stalled — no completed scan in >8 min. Investigate feed/API.", "danger")
```
(`cfg` is loaded at the loop top already.)
- [ ] **Step 4: Verify** — full pytest green; ruff clean.
- [ ] **Step 5: Commit** — ("feat: scanner-stall alert").

---

### Task 9: Config defaults, full verification, deploy

**Files:** Modify `config.json` (gitignored — runtime only), `config.template.json` if present.

- [ ] **Step 1:** Add to config (via /api/settings or direct edit): `enable_safety_guards=true`, `quote_stale_seconds=30`, `quote_jump_reject_pct=20`, `position_anomaly_k=3.0`, `order_rate_max=20`, `order_rate_window_s=10`, `scanner_stall_minutes=8`. If `config.template.json` exists, add the same keys there and commit that file.
- [ ] **Step 2:** Add these keys to the `allowed_keys` list in `update_settings` (main.py ~2998) so they're dashboard-tunable. Commit.
- [ ] **Step 3: Full verification** — `python -m pytest -q` → all green; `python -m ruff check .` → clean.
- [ ] **Step 4: Deploy** — kill the bot PID so the watchdog reloads with new code; verify: bot up, positions resumed, no spurious halts over ~5 min, and the trailing-SL "modified" log lines are no longer repeating identically.
- [ ] **Step 5: Commit** — ("feat: safety-guard config keys + dashboard toggles").

---

## Self-Review
- **Spec coverage:** all six guards (quote, SL-dedup, anomaly, cycle-spike, order-rate, scanner-stall) each have a task; config + fail-open + paper==live covered in Tasks 5-9 and Global Constraints. ✓
- **Placeholders:** none — every code step has real code. ✓
- **Type consistency:** `should_send_sl_modify`/`guard_quote`/`position_loss_anomalous`/`cycle_loss_spike`/`scanner_stalled`/`OrderRateBreaker.record_and_check` names identical across definition (Tasks 1-3) and wiring (Tasks 4-8). ✓
