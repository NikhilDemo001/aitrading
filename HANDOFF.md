# HANDOFF — LATEST SESSION 2026-07-15 → 07-16 (READ THIS FIRST)

Resuming tomorrow. Bot is in **PAPER mode**, running under the watchdog. This block is the current
state; the older 2026-07-04 handoff (deeper architecture/context) follows below.

## ▶️ RESUME TOMORROW — do these first
1. **Re-login for the daily Upstox token** — it dies ~3:30 AM IST. Open <https://127.0.0.1:5000/login>,
   click through the self-signed cert warning, log in (creds + OTP). **No market data flows until you do.**
   (The bot's "Token auto-refreshed successfully" log is misleading — it does NOT mint a valid token.)
2. **Bot should already be running** under the watchdog scheduled task ("UpstoxBot Watchdog"; auto-restarts,
   now with AC-never-sleep + 5-min self-heal). Check <https://127.0.0.1:5000>. If down:
   `Start-ScheduledTask -TaskName "UpstoxBot Watchdog"`.
3. **Commit the pending UI tweaks** (uncommitted — see "Uncommitted" below).
4. **Rotate the Anthropic API key** — it was pasted in chat (exposed). Regenerate at console.anthropic.com,
   update `.env` `ANTHROPIC_API_KEY`.

## ✅ WHAT WE BUILT TODAY (2026-07-15/16)
- **Assistant tab (2026-07-16)** — read-only Claude Q&A over the bot's own data. `assistant_engine.py`
  (pure snapshot + answer), `routers/assistant.py` (`POST /api/assistant/ask`), `AssistantTab.tsx`.
  Separate `assistant_max_daily_calls` (100) budget so chat never starves the trading gate;
  `assistant_max_tokens=4000` — claude-sonnet-5 emits a thinking block, so a smaller budget gets
  eaten by thinking and returns an EMPTY answer. `llm_engine.build_client()` added (budget-independent).
- **UI (2026-07-16):** new **Trades tab** (`features/trades/`) holds Closed/Historical/**Shadow**
  tables + a Real-vs-Shadow strip — Cockpit is now live-operation only and gained a
  **Why-no-trades gate breakdown** (`GateBreakdown.tsx`, aggregates `/api/decisions` skips).
  Active Positions moved out of the centre column → full width. Learning panels (Drilldown, KPI
  trend, Pattern) got per-panel date dropdowns (`usePanelRange` + `PanelRangeSelect`).
  Status strip no longer claims "Unlimited (Paper Trading)" — the daily-loss halt fires in paper too.
- **Fixes (2026-07-16):** leaderboard 500 (GET no longer runs generate_daily_journal write);
  `/api/fundamentals` competitors needs the FULL instrument key (NSE_EQ|ISIN), not bare ISIN;
  **reconcile-vs-fill race** — a just-filled live position no longer gets orphaned + its SL cancelled
  (`broker_reconcile_settle_seconds=15` grace window); live orders now record the **actual broker
  fill price** (`_await_fill_price`), not the limit price.
- **Proxy fixed** — old account was suspended (407). New **proxy-seller.com** account (same IP
  175.111.136.31), creds in `.env` `PROXY_URL`. Verified.
- **Real-time WebSocket feed** — `market_feed_mode: ws` (was `rest`); real-time LTP **~50–90 ms**. Connects
  DIRECT, bypassing the proxy (works on the home IP — the authorize step returns a pre-signed wss URL Upstox
  doesn't IP-check). Interval 0.5s. Feed change needs a bot restart.
- **Token-verification fix** (committed `b218781`) — added `verify_token_live()`; honest `try_refresh_token`
  (was fabricating a mock token in paper mode → bot ran blind all day). Now fail-closed + honest re-login prompt.
- **`min_net_rr = 1.1`** (was 1.0; briefly 1.3 but that blocked EVERY normal VWAP-Pullback T1 setup — the gate
  is net-of-cost on the NEAREST target). Do NOT push it back up without re-checking live T1 R:R.
- **Watchdog hardened** — `powercfg standby-timeout-ac 0` (never sleep on AC), task re-fires every 5 min for 8h
  (self-heals after sleep/crash via the :5000 single-instance guard), RestartCount 3. (Bot had died 11:46 from
  machine sleep.)
- **LLM entry-confirmation gate** (committed `d35607a`) — `llm_engine.confirm_entry()` sends candidate + news +
  technicals → `{proceed, confidence, reason}`. Hooked into `execute_entry` AFTER all deterministic gates,
  real (non-shadow) entries only. **FAIL-CLOSED.** Config: `enable_llm_entry_gate: true`,
  `llm_entry_gate_min_confidence: 60`, `llm_entry_gate_fail_open: false`.
- **Claude wired + working** — `llm_provider: anthropic`, `llm_model: claude-sonnet-5`, key in `.env`,
  **$5 credits added**. VERIFIED: "chase the +10% KSOLVES spike" → proceed:false; clean VWAP pullback →
  proceed:true. (llama-8b had wrongly said proceed on the chase — that's why we upgraded.)
- **News** — `get_news()`, `/api/news/{symbol}`, wired into the gate context (5-min per-symbol cache).
- **Fundamentals** — 8 client methods (profile, balance sheet, cash flow, income, shareholding, key ratios,
  corporate actions, competitors) + `/api/fundamentals/{symbol}` (parallel fetch, ~2s).
- **Two new dashboard tabs** — **News** (6th) + **Fundamentals** (7th), both with a searchable SymbolSearch
  (type-to-search + 50-symbol autocomplete).
- **Cockpit tidied** — removed Manual Trade + the small NewsPanel; swapped Scanner ↔ Active Positions.

## 📊 CURRENT STATE
- Mode: **PAPER** (`paper_trading: true`, `max_open_positions: 8`). Gate enabled but only bites REAL entries.
- Commits on `self-improve`: `b218781` (token fix), `d35607a` (news + gate + fundamentals + tabs). Not pushed.
- `config.json` is gitignored (holds the token). `config.template.json` has the feature flags but is
  UNCOMMITTED (entangled with pre-existing WIP).

## ⚠️ HONEST STATUS — the real gap is EDGE, not data
Data/parameters are now COMPLETE (a pro's full toolkit + news + fundamentals). But paper stats are weak
(win rate ~31%, profit factor <1, negative Sharpe — small sample). That's an **edge** problem, not a data
problem — no new feed fixes it. **Next real work:** run in paper for weeks and MEASURE per-strategy
expectancy + whether the LLM gate/news actually lift win rate. (Offered to build an "edge report" from the
logs.) **Do NOT go live until the numbers are positive.**

## 🗂️ UNCOMMITTED (working tree)
- **Today's UI tweaks (commit these):** `frontend/.../CockpitTab.tsx`, `NewsTab.tsx`, `FundamentalsTab.tsx`,
  new `design-system/SymbolSearch.tsx/.css`, deleted `cockpit/NewsPanel.*`, rebuilt `static/`.
- **Pre-existing WIP (predates today, left untouched):** `config.template.json`, `options_map.json` (321k
  lines), `event_calendar.py`, `safety_guards.py`, `symbol_memory.py`, `research_lab.py`, etc.

---

# HANDOFF — Session of 2026-07-04 (earlier session — deeper architecture/context below)

**Who:** Nikhil (nikhilnannajkar123@gmail.com), working with Claude Code.
**Repo:** `D:\coarse\upstox_Redign` (branch `self-improve`) → GitHub `https://github.com/NikhilDemo001/aitrading.git` (`main` + `self-improve`, both at same tip).
**Plan on resume:** do the "THREE BLOCKERS" below first, then start the 3-week paper-trading clock.

---

## 1. WHAT THIS PROJECT IS (the aim)

A fully automated **intraday trading bot for NSE (India) via Upstox**, that also **improves itself
from its own results**. Three founding pillars (README.md): rule-based scanning (no human bias),
instant execution, capital protection (stops, daily-loss limits, kill switch). Intraday only —
no overnight positions, IST market hours (9:15–15:30). On top: the self-improving layer:

- **Lane A (deterministic learning):** every closed trade logged with full context
  (Section-6 schema → `data/wins.jsonl`/`losses.jsonl`); nightly leaderboard rebuild, pattern
  reliability stats, per-symbol memory, Q-learning position sizing, daily history snapshots.
- **Lane B (LLM lessons/proposals):** reviews trades, writes lessons + one daily improvement
  proposal. NOTHING self-modifies into live — proposals pass promotion_gate (backtest → paper
  validation → HUMAN approval required).
- **AI Research Lab (`research_lab.py`):** autonomously invents/backtests/evolves candidate
  strategies in `ai_research.db`. Currently self-contained — its output does NOT trade.

**The aim is an OUTCOME** (profitable + self-improving + capital-protected), not just code.
Honest status: the code now matches the design well; the *evidence* is still one losing paper
day. See §5.

## 2. ARCHITECTURE MAP (flat files at repo root)

- `main.py` (~3500 lines) — FastAPI app, WebSocket `/ws`, scan loop + monitor loop, order flow,
  EOD learning block. Routers wired at the bottom (`routers/` package: research, history, lane_b
  — extracted 2026-07-04, audit item P3-14).
- `upstox_client.py` — broker adapter (OAuth, instruments, candles, quotes, orders,
  **NEW: `get_positions()`** portfolio API). Paper trading branches inside each method.
- `strategies.py` — indicators + 5 strategies + regime detection; 3 more in
  `strategy_vwap_trend_pullback.py`, `strategy_support_resistance.py`,
  `strategy_candlestick_confluence.py` (8 total). `candlestick_patterns.py` — pattern detectors.
- `signal_quality.py` (gating + Kelly sizing), `risk_manager.py` (unified risk gate),
  `execution.py`/`broker_base.py`/`mock_broker.py` (paper==live path),
  `jsonl_logger.py` (Section-6 schema), `leaderboard.py`, `history.py` (daily snapshots),
  `learning_engine.py` (Q-learning), `llm_engine.py` (Lane B), `promotion_gate.py`,
  `lane_b.py` (EOD orchestration), `research_lab.py`, `orchestrator.py` (standalone loop),
  `market_feed.py` (REST-poll / WS feed), `institutional_engine.py` (12-layer scorer, used in scan).
- Frontend: `frontend/` = React+TS+R3F source ("Midnight Quant" cockpit, rebuilt 2026-07-02);
  `static/` = build output. Backend serves it.
- Persistence: `active_positions.json`, `trade_history.json` (both gitignored),
  `data/*.jsonl` + `data/history/*` (gitignored), `ai_research.db` (48MB), `symbol_memory.db`,
  `rl_policy.json`. Config: `config.json` (GITIGNORED — holds live Upstox JWT), `.env`
  (GITIGNORED — all API keys).
- Run: `python main.py` (HTTPS on 127.0.0.1:5000, self-signed certs; `BOT_DEV=1` for reload).
- Tests: `python -m pytest -q` → **209 passed** (2026-07-04). Lint: `python -m ruff check .` →
  clean (config in `pyproject.toml`; requirements-dev.txt pins ruff). Python 3.14.3, Windows 11.

## 3. EVERYTHING DONE THIS SESSION (2026-07-04, chronological)

1. **Recovered main.py** — found as 167,306 NUL bytes (crash mid-write). Restored from HEAD;
   if main.py ever shows "binary" in git diff, suspect NUL corruption.
2. **Router extraction (P3-14):** research/history/lane-b endpoints → `routers/` package with
   `configure(get_now/get_config)` injection. 33-route parity verified via OpenAPI.
3. **Ruff lint baseline:** pyproject.toml (E4/E7/E9, F, UP, B, RUF013; py314; line 120;
   E701/E702/E741/B904 ignored as house style; per-file E402 for main.py + strategies.py).
   290 findings → 0. Real finds: duplicate `get_all_hypotheses` in research_lab (deleted),
   SQLite connection leaks in routers (fixed), misplaced import in signal_quality (moved).
4. **Wired in 3 unenforced strategy checks** (all stricter, never looser):
   - Morning/Evening Star: third candle body must be ≥ 0.5× first candle's body.
   - ORB: skip if 15-min opening range < 0.1% of price (noise).
   - Walk-forward gate: also requires in-sample PF ≥ 1.0 (extracted to pure
     `research_lab.walkforward_gate()` + `_profit_factor()`).
5. **Lane B LIVE at ₹0 cost:** `llm_engine.py` now provider-aware. `llm_provider` =
   `"anthropic"` | `"openai_compat"`; `OpenAICompatClient` (plain requests, non-streaming,
   `llm_timeout_seconds` default 180) works with NVIDIA build.nvidia.com / Ollama / LM Studio.
   ACTIVE CONFIG (in gitignored config.json): provider=openai_compat,
   base_url=https://integrate.api.nvidia.com/v1, **model=meta/llama-3.1-8b-instruct**,
   llm_enabled=true, cap 50 calls/day. Key in `.env` as `NVIDIA_API_KEY`.
   - User's preferred `meta/llama-3.3-70b-instruct` is VALID on the account but its free queue
     hung (>120s read-timeouts) on 07-04 while 8b answered in 0.5s. Retry 70b later — one-line
     `llm_model` swap; history stays attributable (every llm_calls.jsonl row carries
     model+source). NVIDIA free tier ≈ 1000 trial credits, 40 RPM.
   - Smoke-tested end-to-end: real lesson, `source=openai_compat`.
6. **Broker-position reconciliation (pre-live safety, user-requested):** closing a bot trade
   from the Upstox app previously left a ghost position → next bot action could OPEN a reverse
   position. Now: `upstox_client.get_positions()` (None = UNKNOWN ≠ flat);
   `main.reconcile_broker_positions()` each monitor cycle (live only, 20s throttle) records
   vanished positions as "CLOSED EXTERNALLY (BROKER RECONCILE)", cancels leftover SL order,
   places NO order; `execute_exit()` re-verifies broker holdings before any live closing order.
   Limits: external-close price = last known mark (not actual fill); manually-opened broker
   positions are NOT adopted. `test_broker_reconcile.py` (11 tests).
7. **Pushed to GitHub.** Before first push: found Bright Data proxy username+password in
   `proxy_setup_notes.md` → redacted AND scrubbed from ALL history via git-filter-repo
   (all commit hashes changed; pre-scrub bundle was in session scratchpad). Remote `main` was
   force-pushed over GitHub's init commit.
8. **Deployment question answered:** Vercel is WRONG for this bot (serverless = no persistent
   loops/WS/filesystem; Upstox needs a registered static IP). Right options: keep on PC (paper),
   later a small Mumbai VM (Lightsail/DO/Hetzner ~₹300-500/mo) or Oracle Always-Free; dashboard
   remote access via Tailscale/Cloudflare Tunnel. NOTE: backend API has NO auth — never expose
   it publicly as-is.

## 4. SECURITY / HOUSEKEEPING (tell Nikhil if not done)

- **Rotate the Bright Data proxy password** (was in git history + still in non-git Desktop
  copies: `C:\Users\nikhi\Desktop\upstox_Redign\`, `...\upstox_intraday_helper - working\` —
  NEVER publish those copies).
- **Revoke/rotate both NVIDIA keys pasted into chat** (first one unused: nvapi-9LU...; second
  is the active one in .env — after rotating, update `.env`).
- Check GitHub repo visibility — recommend PRIVATE (strategy edge is public otherwise).
- `.env`, `config.json` (live JWT!), `*.pem`, `*.db`, `data/`, trade files are all gitignored —
  keep it that way.

## 5. HONEST STATUS vs THE AIM (as of 2026-07-04)

- **Track record:** ONE real paper day (2026-07-02): 19 trades, 36.8% win rate, PF 0.497,
  net **−₹2,069** on ₹1,00,000 paper capital. Total stored: 22 trades (7W/15L, net −₹2,280).
  No evidence of edge yet — and none possible without daily runtime. (That day also ran with
  the looser pre-fix rules.)
- **Zero live trades ever.** paper_trading=true. Live needs: real key in config, llm of
  LIVE_TRADING_CONFIRMED env var (Section 0 rule 1), registered static IP.
- **Learning loop starving** (see blockers below).
- **Research Lab: mechanically fine, scientifically broken** (see §7).

## 6. ★ NEXT SESSION: THE THREE BLOCKERS (do these FIRST) ★

Agreed sequence: fix these → start the 3-week paper clock → 1-week plumbing check → 3-week
verdict on the aim.

1. **Paper mode bypasses the daily-loss halt** — `risk_manager.py` ~line 64-66: paper returns
   `RiskDecision(True)` before the max_daily_loss check (config says 500; the real day lost
   2,069 without halting). Decision (recommended): make paper honor the halt so paper
   faithfully rehearses live and learning data isn't contaminated by post-halt trades.
2. **`data/history/pattern_stats.jsonl` is 0 bytes** — candlestick pattern-reliability learning
   has NEVER recorded a row. Find why the feed never writes (likely trades carry no
   `candlestick_patterns` values on the scan path, or history.write_all's pattern section gets
   empty input) and fix.
3. **`rl_policy.json` stale since 2026-06-18** despite trades on 07-01/02 — the Q-learning EOD
   update path isn't firing. Note: exit-time RL update is gated on
   `config enable_rl_sizing=False` by design; check whether EOD-side update is also gated/broken
   and decide what "RL learning active" should mean.

Then: **run the bot every market day** (PC on 9:15–15:30 IST). Week-1 check: snapshots, lessons,
pattern stats, RL updates all accumulating. Week-3: expectancy/PF level AND trend.

## 7. QUEUED AFTER THE CLOCK STARTS: Research Lab overhaul

DB inspection findings (2026-07-04, ai_research.db: 34 strategies, 18 Paper Trading,
3 Approved):

- `simulate_paper_trades_daily()` produces FANTASY equity: ₹1,00,000 → ₹35,99,440 (36×),
  5,240 trades — not driven by real market data. Rebuild on real quotes / mock-broker path.
- Score saturation: every Paper Trading strategy scores exactly 100.0 — rescale formula.
- Duplicate discovery: "EMA Cloud Confluence #680" exists 5× as separate strategies — add
  dedup (name/param hash) in discover_strategies.
- 10 backtest_results rows have total_trades=0 but recorded PF=1.0/Sharpe=1.0 — treat
  zero-trade runs as failures/insufficient-data, not neutral results.
- Validation universe is RELIANCE-only, 30 days, hardcoded in backtest_strategy — use the
  config watchlist.
- Reassurance: lab output does NOT reach live trading; it's dashboard-only today.

## 8. OTHER OPEN THREADS / QUIRKS

- Lane B: consider swapping back to llama-3.3-70b when NVIDIA's free queue clears; Ollama is
  the free-forever fallback (OpenAICompatClient already supports it — just change
  llm_base_url to localhost, no key).
- Live-market backtest comparison of the new strategy thresholds (stars/ORB/WF gate) still
  pending — needs authenticated candle data.
- `/api/positions` returns only the bot's book; a broker-side view in the dashboard is a
  possible enhancement (reconciliation backend exists now).
- Deployment package (Dockerfile + service + VM guide) not yet built — user deferred.
- instrument_map.json / options_map.json get modified at runtime (instrument refresh) —
  commit them as "data refresh" or leave, either is fine.
- Multiple non-git copies of this repo exist on disk; if pytest tracebacks show Desktop paths,
  clear `__pycache__` — see memory note duplicate-repo-copies.
- User preferences: plain clear language; free-of-cost options first; ALWAYS ask before paid
  API spend; user says "go"/"yes" to approve proposed next steps.

## 9. VERIFICATION SNAPSHOT (2026-07-04)

- `python -m pytest -q` → 209 passed, ~2 min.
- `python -m ruff check .` → clean.
- Lane B smoke: real NVIDIA lesson logged (`data/llm_calls.jsonl`, source=openai_compat).
- GitHub: main == self-improve == local tip (f70d239 at push time; hashes changed by the
  history scrub — old hashes in chat logs are invalid).
