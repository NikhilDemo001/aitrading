# Real-time in-bot safety guards — design (2026-07-08)

## Goal
Add instant, autonomous safety reactions that run inside the bot's own loops (per ~1s monitor
cycle / per scan), covering **reliability and data-glitch** failures the existing risk gates
don't catch. They must protect against disasters without throwing away days of the 3-week paper
experiment. No discretionary trading; paper==live path; every guard config-toggleable and
threshold-tunable.

## Non-goals (YAGNI)
- No generic/config rules engine.
- No predictive or discretionary trade signals; guards never open a trade or pick direction.
- Not replacing existing halts (daily-loss ₹4,000, consecutive-loss, EOD square-off, startup
  square-off, exit-race guard) — these guards are additive and cover different failures.

## Posture: TIERED (user decision 2026-07-08)
Reliability/data problems self-heal or block just the bad action and keep the day running for
data; only a true catastrophe triggers a full halt + square-off.

## Architecture
New module **`safety_guards.py`** of small, pure, individually unit-tested functions (mirrors
`risk_manager.py` / `signal_quality.py`). Wired into existing `main.py` seams:
- `OrderQueue.submit` (main.py:110) — order-rate breaker choke point.
- `position_manager_loop` / `manage_existing_positions` — stale-quote guard, position-anomaly
  force-exit, cycle-loss spike, trailing-SL dedup (modify at main.py:2249-2252).
- `scanner_loop` — scanner-stall detector (uses `scanner_state["last_scan"]`).
All thresholds live in `config.json`; each guard has an `enable_*` flag (default on).

## The guards

### Tier 1 — block the bad action, keep trading
1. **Stale/bad-quote guard** `guard_quote(last_good, tick, now, ...)`
   - Reject a tick when: price ≤ 0, or no fresh update in > `quote_stale_seconds` (default 30),
     or single-step move > `quote_jump_reject_pct` (default 20%).
   - Action: do NOT act on the rejected tick; keep using last-good `current_price`; log once.
   - **Conservative rule (highest risk of harm): must NOT suppress a legitimate stop.** A
     rejected tick only prevents *acting on that tick's price*; if the last-good price already
     breaches the stop, the normal stop path still fires. Reject only provably-broken ticks.
2. **Trailing-SL dedup** `should_send_sl_modify(pos, new_trigger, new_limit)`
   - Skip `client.modify_order` when `(trigger, limit)` equals the last values sent for this
     position (store `last_sl_sent` on the position). Removes the every-1–2s re-send spam.

### Tier 2 — halt + square-off (catastrophe only)
3. **Position-anomaly force-exit** `position_loss_anomalous(pos, k=3)`
   - If a position's unrealized loss > `k` × intended risk (|entry−stop|×qty), the stop failed to
     fire (gap/data/broker glitch) → force-exit THAT position at market now, log loudly.
     Default `position_anomaly_k = 3.0`.
4. **Cycle-loss spike halt** `cycle_loss_spike(prev_total, cur_total, limit)`
   - If total daily P&L drops by more than the whole `max_daily_loss` within a single ~1s cycle
     (impossible in normal trading) → treat as data glitch → halt bot_running + square_off_all.
5. **Order-rate breaker** (in `OrderQueue`) `OrderRateBreaker`
   - If > `order_rate_max` orders submitted within `order_rate_window_s` (defaults 20 / 10s) →
     stop accepting new submits + set bot_running False + loud log. Guards a runaway loop.
     Note: the SL-dedup (#2) removes benign order volume so this threshold stays clean.

### Tier 3 — self-heal / alert (never halts)
6. **Scanner-stall detector** `scanner_stalled(last_scan_dt, now, within_window)`
   - During the trade window, if no scan has COMPLETED in > `scanner_stall_minutes` (default 8;
     safely above the observed ~6-min cold-start) → loud warning + nudge the scan cycle. Never
     stops trading; persistent stalls surface for the watchdog.

## Error handling
Each guard is defensive: any internal exception is swallowed and treated as "no action / allow"
so a guard bug can never itself halt or block legitimate trading (fail-open for Tier 1/3;
Tier 2 halts only on an explicit positive detection).

## Testing (TDD)
`test_safety_guards.py` — pure unit tests per function: bad/stale/jumpy ticks vs good ticks
(incl. the "legitimate stop still fires" case), SL-dedup identical vs changed, anomaly at/below/
above k×risk, cycle-spike at threshold boundary, order-rate at/over limit within/outside window,
scanner-stall before/after threshold and outside market hours. Full suite must stay green; ruff
clean.

## Rollout
Land behind config flags (all default on), unit-tested; deploy by the watchdog reload; verify
live that normal trading is unaffected (no spurious halts) and the SL spam is gone.
