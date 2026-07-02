# ARCHITECTURE.md — Current State (as of 2026-07-01)

This document describes what **already exists** in this repository, established by direct code
inspection (not assumption), so that the self-improving trading system build extends it in place
rather than duplicating it.

## 1. High-level shape

This is **not** the `/core /api /ui` layout described in a generic greenfield spec — it's a
single-process FastAPI app with feature-based flat files at the repo root:

```
main.py                      # FastAPI app: routes, WebSocket, both background loops, order flow
upstox_client.py             # Upstox broker adapter (concrete only, no base class)
market_feed.py                # Live feed abstraction: MarketFeed base -> RestPollFeed / UpstoxWsFeed
strategies.py                 # Indicators + 5 strategy functions + regime detection + selector
strategy_vwap_trend_pullback.py
strategy_support_resistance.py
strategy_candlestick_confluence.py   # 3 more strategy functions (8 total)
candlestick_patterns.py       # Pattern detection (13 of the ~18 patterns the target spec wants)
signal_quality.py             # Signal gating chain + Kelly position sizing
analytics.py                  # Session/strategy/symbol metrics, adaptive strategy ranking
backtester.py                 # Single-strategy walk-forward backtest engine
data_manager.py                # Historical OHLCV disk cache
event_calendar.py             # NSE holidays/expiry/earnings-season event-risk lookup
institutional_engine.py       # Separate 12-layer standalone signal scorer (not wired into main loop's strategy registry)
symbol_memory.py               # Per-symbol SQLite bias/stat tracker (symbol_memory.db)
learning_engine.py             # Q-learning position-sizing policy (rl_policy.json) + tiny hand-rolled MLP
model_validator.py             # Walk-forward gate for RL policy updates only
research_lab.py                # Autonomous strategy discovery/evolution/leaderboard engine (ai_research.db, 14 tables)
static/                        # Frontend: vanilla JS SPA, no framework, no build step
config.json                    # Bot config (flat key/value, no schema validation)
.env                            # Upstox credentials
```

Persistence is a mix of flat JSON files (`trade_history.json` as a JSON **array**,
`active_positions.json`) and SQLite (`ai_research.db`, `symbol_memory.db`). There is **no JSONL
anywhere** currently.

## 2. Broker integration

- `upstox_client.py`: single concrete `UpstoxClient` class, **no abstract broker interface**.
  OAuth login/exchange/refresh, instrument master download (`instrument_map.json`,
  `futures_map.json`, `options_map.json`), candles/quotes, order place/cancel/modify/status.
- Paper trading is **built directly into** each broker method (`place_order`, `cancel_order`,
  `modify_order`, `get_order_status`, `get_funds_and_margin`, `try_refresh_token`) via
  `if self.paper_trading: ... mock response ...` branches — not a separate simulator behind a
  shared interface. `place_order` in paper mode fetches a real quote for a realistic fill price
  and returns a `MOCK-{ts}` order id.
- `market_feed.py` **already has** a clean abstraction: `MarketFeed` base class +
  `RestPollFeed` (polling thread) + `UpstoxWsFeed` (Upstox V3 protobuf WebSocket), selected via
  `create_feed(client, mode="rest"|"ws")`. This is reusable as-is for `data_feed.py`'s role.

## 3. Strategies & signals

- 8 strategy functions total across `strategies.py` (5: ORB, VWAP-Pullback, Momentum,
  MeanReversion, TrendFollow) + 3 more in dedicated files (VWAPTrendPullback,
  SupportResistance, CandlestickConfluence). **No formal `Strategy` interface/class** — they're
  standalone functions with slightly different signatures, unified only by a lambda-wrapped
  dict registry (`strategies.py:657-666`).
- `detect_market_regime` already classifies `trending_up / trending_down / ranging / choppy /
  unknown` via ADX(14) + EMA20/EMA50 alignment + optional HTF bias — a finer-grained version of
  the target spec's 3-state regime.
- `select_best_strategy` already runs **every** strategy for the current regime-priority order,
  scores each fired signal with a 100-point confluence-style `calculate_signal_confidence`, and
  picks the highest score — genuinely regime-aware, but its "performance history" input
  (`_reorder_by_performance`) is optional/caller-supplied, not automatic, and there's no
  recency-weighted expectancy tracking per (strategy, regime, time-bucket) combination.
- `signal_quality.py` is a 5-layer gate chain (event risk, time-of-day, volatility band,
  consecutive-loss halt, Nifty-alignment + confluence score) run **after** a strategy fires —
  functionally close to part of the target spec's RiskManager, but it's a signal filter, not an
  order-level risk gate, and it lives outside `main.py`'s order-placement path checks.
- `candlestick_patterns.py` already detects: hammer, shooting star, bullish/bearish engulfing,
  3 doji variants, bullish/bearish pin bar, morning star, evening star, bullish/bearish marubozu,
  tweezer top/bottom, piercing line, dark cloud cover, inside bar. **Missing** vs. target list:
  inverted hammer, hanging man, spinning top, three white soldiers, three black crows. No pattern
  carries a numeric strength score today (bullish/bearish/neutral only).
- ATR-based stops + fixed R-multiple targets (1.5R/2.5R typical) are already standard across all
  8 strategies; `adjust_targets_with_levels` clips targets to S/R levels and can flag a trade
  `is_shadow_trade` if adjusted R:R drops below 1.0.
- Position **sizing** (converting risk into share quantity) lives in `main.py`'s `_calc_quantity`
  (main.py:733-776), with Kelly-fraction risk adjustment from `signal_quality.calculate_kelly_risk`
  — not colocated with the strategy/signal-quality code.

## 4. Risk management — the single biggest structural gap

There is **no unified `RiskManager` class**. Every check is a scattered inline `if` across
`main.py`:

| Rule | Where it lives today |
|---|---|
| Daily loss kill switch | `scanner_loop` (main.py:1102-1109) + a faster 1s recheck in `position_manager_loop` (2375-2381) |
| Weekly drawdown halt | `scanner_loop` (1040-1065) |
| Max open positions | Checked separately at 3 call sites (1123, 1273, 2929) |
| Consecutive-loss circuit breaker | `signal_quality.check_consecutive_loss_halt`, called from `scan_for_entries` (1178-1189) |
| Square-off time | `scanner_loop` (959-1029) |
| Per-trade sizing | `_calc_quantity` (733-776) + Kelly adjustment |
| Sector concentration | `scan_for_entries` (1280-1290) |
| Per-symbol daily trade cap | `scan_for_entries` (1292-1296) |

**Important safety bug found**: the daily-loss halt (1104) and weekly-drawdown halt (1061) are
both wrapped in `if not paper_trading:` — they are **skipped entirely in paper mode**. This
directly contradicts the "paper and live run the exact same risk path" design rule and the spec's
non-negotiable kill-switch rule. This needs fixing regardless of the rest of the build.

## 5. Data persistence — reliability gap found

`active_positions.json` is currently **8484 bytes of null bytes — not valid JSON**, alongside an
orphaned `trades_thc16kh0.tmp` (same timestamp), indicating an interrupted atomic write on
Windows even though `save_state()` (main.py:608-647) is designed to write via `tempfile.mkstemp` +
`os.replace`. `trade_history.json` itself parses fine (239 records, flat JSON array).
`save_state()` also mirrors both files into SQLite (`live_positions`/`live_trades` tables in
`ai_research.db`) as the actual primary store, with the JSON files as a migration
fallback/legacy artifact. This corruption should be fixed as part of the persistence-layer work.

Current trade record schema (from `trade_history.json`) already has: `symbol, strategy,
direction, quantity, entry_price, entry_time, exit_price, exit_time, pnl, reason, regime,
htf_trend, atr_at_entry, market_context {ema_20, vwap, rsi, atr, regime, volume_ratio, atr_pct,
vwap_aligned, htf_aligned}, holding_minutes, mae, mfe, confluence_score, trigger_level_source/
price/score, is_shadow_trade`. **Missing** vs. target schema: `trade_id` (uuid), `mode`
(paper/live — currently implicit), `r_multiple`, `candlestick_patterns` (list), `time_of_day_bucket`,
`lesson` (LLM-generated), `tags`.

## 6. Learning / self-improvement — substantial existing system, but no real LLM

This is the most surprising finding: there is already an elaborate autonomous research system in
`research_lab.py` (2394 lines, `ai_research.db` with 14 tables) that closely parallels the target
spec's two-lane design:

- **Leaderboard** (`leaderboard` table) rebuilt from scratch each EOD run, ranked by profit
  factor, preferring live paper-trading stats over backtest stats. No recency-weighting of
  individual trades within that calculation, though.
- **Strategy lifecycle / promotion gate already exists**: `Idea Generated → Backtesting →
  Paper Trading → (Rejected | Retired | promoted)`, gated by walk-forward backtest thresholds
  (`validate_strategy`, main.py:837-857: `oos_pnl > 0, oos_trades >= 2, oos_pf >= 1.1`) and
  paper-trading underperformance checks (retire if `trades>=5 and (win_rate<45% or pf<1.0)`).
  This is functionally close to the spec's Section 5 Promotion Gate — reuse it, don't rebuild it.
- **Strategy evolution**: `evolve_strategy` mines historical trades for the worst-losing
  hour/regime and appends a rule filter, versioning the strategy — an automated proposal
  mechanism, though mechanical rather than LLM-reasoned.
- A separate `model_validator.py` gates only the RL sizing policy (not strategies) via an
  out-of-sample PnL/drawdown comparison.
- **No Claude/Anthropic/OpenAI API integration exists anywhere in the repo** (verified via
  repo-wide grep — zero matches). The "AI CTO Chat", "CEO Executive Briefing", and journal
  `findings/mistakes/opportunities` text are **keyword-matched templates and hardcoded strings**,
  not model output (`interpret_chat_query` picks a random "persona" label and fills a string
  template; `generate_ceo_briefing` and hypothesis text work the same way).
  This is the single largest gap against the spec: **Section 5 Lane B calls for genuine Claude
  reasoning**, and today that lane is entirely simulated. Wiring in real Claude API calls (behind
  the existing lifecycle/gate plumbing, which is otherwise reusable) is the core of that phase.

## 7. Frontend — vanilla JS SPA, single app, reusable patterns already present

- No framework, no build step, no templating — `document.createElement`/`innerHTML` string
  interpolation throughout. Tabs are sibling `<section>` elements toggled by `data-tab`
  attributes (`initTabs()`, app.js:170-206), not client-side routing.
- **4 existing top-level tabs**: Cockpit (`#tab-dashboard`), Analytics, Config (`#tab-settings`),
  AI Research Lab (`#tab-ai-research`, which itself has 6 sub-tabs: Sandbox Pipeline, AI CTO
  Chat, Marketplace, Compare, Risk & Capital, Learning & Timeline).
- **Live data**: WebSocket-first (`/ws`, broadcasts `init/state_update/logs/scanner/
  realtime_update/trade_event/research_progress`) with automatic fallback to 4-second HTTP
  polling on socket close. This is already the "live channel" the target spec asks for — no new
  channel needed, just more message types to broadcast.
- Charting: `lightweight-charts@4.2.3` (CDN), already rendering candles + EMA + VWAP overlays +
  SL/target price lines + entry/exit markers. This is the one library to keep reusing for the new
  learning-over-time and equity-curve charts.
- State is module-level globals in `app.js`, not a store — acceptable given the existing app's
  scale; new views should follow the same pattern rather than introducing new state management.
- Rendering is bespoke `innerHTML` template building per feature — **no shared table/component
  helper exists**. New views (leaderboard table, pattern table, feature-bucket heatmap, proposals
  list) will each need their own render function following this existing pattern.
- **Meaningful head start on the target Section 8 tabs**:
  - Sandbox Pipeline's "AI Learning Journal" panel + date filter ≈ target Tab 6 (needs real
    Claude content + an LLM-call log viewer, which doesn't exist yet).
  - "Learning & Timeline" sub-tab (Hypothesis Tracker + Chronological Timeline) ≈ target Tab 6/7
    audit trail.
  - Strategy Pipeline (list/3D view + Approve/Reject/Retire buttons) ≈ target Tab 7 Promotion
    Gate UI — needs `require_human_approval` wired to actually gate promotion, which today runs
    fully automatically inside `run_autonomous_research_cycle()`.
  - Analytics tab's equity curve + strategy breakdown + MAE/MFE panel ≈ target Tab 8.
  - **Net-new, nothing to extend**: candlestick pattern-reliability-over-time view (Tab 4),
    feature/condition bucket analytics + time-of-day heatmap (Tab 5), and — most importantly —
    a **global date-range selector with as-of-date reconstruction and compare mode**. Today the
    only date filtering is 3 independent single-`<input type="date">` filters (journal, CEO
    chat, timeline), each calling its own `load*(date)` function with a `?date=` query param.
    That's the right pattern to generalize into one shared global control, but the history
    snapshots it would read from (`leaderboard_YYYY-MM-DD.json`, `pattern_stats.jsonl`,
    `feature_stats.jsonl`, `kpi_daily.jsonl`) **do not exist yet** — the leaderboard table is
    overwritten in place every EOD run, so no day-by-day evolution can currently be reconstructed.

## 8. Config

`config.json` is a flat key/value file (113 keys currently), loaded fresh via `.get(key, default)`
at each read site with no schema/type validation. Saved via `POST /api/settings`, which whitelists
allowed keys before writing. No config-change history is kept.

## 9. What this means for the build (see plan for the full phased breakdown)

The instruction to "extend in place, reuse what exists" is very achievable here because more of
the target spec is already built than a from-scratch read would suggest — especially Lane A
(leaderboard) and the promotion-gate lifecycle. The real work is: (1) consolidating scattered risk
checks into one `RiskManager` and fixing the paper-mode bypass bug, (2) replacing templated
pseudo-AI text with genuine Claude API calls behind the existing gate plumbing, (3) adding the
JSONL schema fields and daily history snapshots that don't exist yet (this is what unlocks the
whole date-range/as-of-date UI requirement), (4) filling in the 5 missing candlestick patterns,
(5) adding a thin `Strategy` interface wrapper around the existing 8 strategy functions without
rewriting their logic, and (6) building the genuinely new UI views (Tabs 4, 5, and the global
date-range selector) while extending the 4 existing tabs in place for everything else.
