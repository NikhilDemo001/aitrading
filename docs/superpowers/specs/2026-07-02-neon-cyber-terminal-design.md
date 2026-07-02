# Neon Cyber-Terminal — Frontend Re-theme + Gap-Fill

**Date:** 2026-07-02
**Scope:** Frontend only (`frontend/src/`). Backend (`main.py`, 46 REST endpoints + `/ws`) is **not modified**.
**Approach:** Re-theme the existing "Midnight Quant" React 19 + TS + Vite + R3F app in place to a
"Neon Cyber-Terminal" identity, and fill the six interactive features that are genuinely missing.
Not a rebuild — the app already implements ~all of the functional spec and every referenced
endpoint is already wired.

---

## 1. Context (what already exists)

The dashboard was rebuilt earlier today as a complete, token-driven React app. All color flows
through CSS custom properties in `src/design-system/tokens.css`; feature components consume those
tokens via `mq-*` classes and shared design-system primitives (`Panel`, `StatCard`, `Badge`,
`Button`). Consequently a palette change in one file cascades to every component.

Every backend endpoint the original spec references already exists and is reachable:
`/api/kill-switch` (main.py:3024), `/api/close-position/{symbol}` (3181), `/api/trades/all`,
`/api/trades/export`, `/api/logs`, `/api/decisions`, `/api/proposals/{id}/approve|reject`, and the
full `/api/research/*` suite. **No backend work is required.**

Build/run unchanged: `cd frontend && npm run dev` (Vite :5173, proxies to `https://127.0.0.1:5000`);
`npm run build` → outputs to `../static_new/` (never directly into the live `static/`).

**Repo is not under git** — the design doc is written to disk but not committed. `git init` is a
possible separate step, out of scope here.

---

## 2. Visual system — "Neon Cyber-Terminal"

Single source of truth: `src/design-system/tokens.css`. This is the largest single lever.

### 2.1 Palette (token swap)

| Token | Old (Midnight Quant) | New (Neon Cyber-Terminal) |
|-------|----------------------|---------------------------|
| `--bg` | `#0A0B0F` | `#07090E` |
| `--panel` | `#12141C` | `rgba(15, 23, 42, 0.6)` (glass) |
| `--accent` | `#7C6CFF` (indigo) | `#00F0FF` (neon cyan) |
| `--profit` | `#34D399` | `#00E676` (cyber green) |
| `--loss` | `#F43F5E` | `#FF2D55` (neon magenta) |
| `--warn` | `#FBBF24` | `#FFB300` (golden amber) |
| `--live` *(new)* | — | `#FF3B30` (live/real-capital crimson) |
| `--paper` *(new)* | — | `#00F0FF` (paper/simulated cyan/teal) |

Glass panels: `background: rgba(15,23,42,0.6)` + `backdrop-filter: blur(16px)` + thin
`--border` (`rgba(255,255,255,0.08)`). Accent-driven derived tokens (`--accent-dim`,
`--accent-glow`), scrollbar colors, `::selection`, and focus ring update to cyan automatically since
they reference `--accent`.

### 2.2 New glow / LED / pulse utilities (added to `tokens.css`)

- `--glow-cyan`, `--glow-green`, `--glow-magenta`, `--glow-amber`, `--glow-crimson` — reusable
  `box-shadow`/`filter` glow tokens per signal color.
- `.led` + `@keyframes led-pulse` — pulsing status-light primitive (steady vs pulsing via a
  modifier class / prop).
- `.neon-text` — text-glow helper for headers and key values.
- Live-mode surfaces animate a crimson pulse (`@keyframes live-pulse`); paper-mode uses a steady
  cyan glow (no pulse).
- All new animations sit under the existing `@media (prefers-reduced-motion: reduce)` block so they
  are disabled for reduced-motion users.

### 2.3 Typography

- Add dependency `@fontsource/outfit`; import in `main.tsx` alongside existing Inter + JetBrains Mono.
- New token `--font-head: 'Outfit', ...`; apply to the wordmark, `Panel` titles, and section
  headers. `--font-ui` (Inter) stays for body/data; `--font-mono` (JetBrains Mono) stays for
  numeric values (`.num`).

---

## 3. Shared design-system upgrades

Small edits that cascade to all ~30 feature components:

- **`Badge` / `StatusDot`** — add configurable glow per tone and an optional `pulse` (already has a
  `pulse` prop; extend visual to neon LED glow).
- **`Button`** — `danger` and `success` variants gain neon glow; add an `emphasis`/`kill` treatment
  for the emergency button (stronger crimson glow + pulse).
- **`Panel`** — glass background (`blur(16px)`), thin border, header uses `--font-head`.
- **`StatCard`** — value text gains tone-driven neon glow.

---

## 4. Rebrand

- Wordmark: `MIDNIGHT · QUANT` → **`CIPHER · TERMINAL`**; 2-letter mark `MQ` → `CT` with cyan glow;
  keep sub-line `UPSTOX INTRADAY AUTOPILOT`.
- Files: `src/app/TopNav.tsx` (`mq-brand-*`), `src/app/StatusBar.tsx` (brand string
  `MIDNIGHT·QUANT · NSE INTRADAY · UPSTOX V3` → `CIPHER·TERMINAL · NSE INTRADAY · UPSTOX V3`).
- The `mq-` CSS class prefix stays as-is (internal; renaming it is churn with no user-visible value).

---

## 5. Feature gap-fill

Six features are genuinely missing or incomplete. Everything else in the original spec (active
positions live LTP/PnL + per-position square-off, strategy leaderboard, proposals approve/reject,
equity curve, KPI cards, time-of-day panel, watchlist sparklines) already exists and only receives
the theme cascade.

### 5.1 Emergency Kill Switch
- **Gap:** TopNav has Start/Stop (`/api/toggle`) and Square Off (`/api/squareoff`) but no kill switch.
- **Work:** add `systemApi.killSwitch()` → `POST /api/kill-switch`; add a prominent red glowing
  button in `TopNav.tsx` with a confirm dialog ("Halt bot and square off all open positions?").
  Uses the new `Button` kill treatment.

### 5.2 Daily-loss progress ring
- **Gap:** loss-budget logic exists in `EngineStatusStrip.tsx` but is rendered as StatCard sub-text,
  not a ring.
- **Work:** add an SVG progress-ring component showing `daily_pnl` vs `max_daily_loss`
  (% of loss budget consumed, amber→crimson as it fills). Preserve the existing
  "Unlimited (Paper Trading)" branch when `paper_trading` is true.

### 5.3 Connection telemetry LEDs
- **Gap:** `TopNav` shows SRV/API/PAPER/BOT LEDs; no scanner-loop cadence or WS ping.
- **Work:** add LEDs/readouts for `scanner_last_loop` and `scanner_last_checked` (from
  `BotStatus`/scanner context) and a WS ping/liveness indicator, using the new pulsing `.led`.
  Wire in `TopNav.tsx` (or `StatusBar.tsx` for the cadence readout).

### 5.4 Scanner confluence cells + "Why It Skipped" tooltips
- **Gap:** `ScannerMatrix.tsx` shows LTP/ATR%/RSI/regime/strategy/decision only.
- **Work:**
  - Extend the `ScannerRow` type (`src/types/api.ts`) with the fields the `/api/scanner` payload
    carries: EMA9/EMA20/VWAP touch-or-cross status, ORB 15-min high/low boundaries, ATR, VIX filter
    status, Nifty confluence score (`n/7`). **Exact field names/availability to be confirmed from a
    live `/api/scanner` response during implementation**; render each cell conditionally so unknown
    fields degrade gracefully to `—`.
  - Render these as columns (table view) and as heat-tile detail (heat view), with confluence score
    driving tile intensity.
  - "Why It Skipped" tooltip: on hover of a skipped/rejected row, show the blocking risk gate by
    reading `decision`/`gate`/`reason` from `/api/decisions` (already typed as `DecisionEntry` with
    `gate?`). Match decision entries to scanner rows by symbol; fall back to the row's own
    `decision` text if no matching decision entry exists.

### 5.5 Historical trades table
- **Gap:** `ClosedTradesTable.tsx` shows only *today's* WS-pushed trades; no search/sort/export,
  no PnL%/R-multiple columns.
- **Work:** add a historical table sourced from `/api/trades/all` (TanStack Query, click-to-fetch):
  - Searchable (symbol/strategy/exit-reason) + sortable columns.
  - Columns: Symbol, Strategy, Direction, Exit Reason (target/stoploss/eod_squareoff), PnL, PnL%
    (`pnl_pct`), **R-multiple** (computed: `R = (exit-entry)/(entry-stop)` signed by direction, when
    `stop_loss` present in the `/api/trades/all` payload; else `—`).
  - CSV download button → `/api/trades/export`.
  - Currency rendered with `₹`, tabular-nums, profit/loss neon coloring.
  - Keep the existing today's-trades WS table as the live view; the historical table is an addition
    (co-located in the Cockpit or a "History" section — placement decided in the plan). No overlap
    with the existing `Learning` tab's history views, which are date-bucketed KPI analytics, not a
    per-trade ledger.

### 5.6 RL Agent State Visualizer
- **Gap:** not present.
- **Work:** a card in the Research Lab (`src/features/research-lab/`) showing reinforcement-learning
  policy state: `paper_trade_logs` count, `learning_events` count, and out-of-sample validator
  approval status. Source from existing research/status endpoints
  (`/api/research/status`, `/api/research/summary`, `/api/llm-status`); **exact field mapping
  confirmed against live responses during implementation**, with graceful `—` fallbacks.

---

## 6. File-change map

**Edit:**
- `src/design-system/tokens.css` — palette, glass, glow/LED/pulse utilities, `--font-head`.
- `src/design-system/{Badge,Button,Panel,StatCard}.{tsx,css}` — neon glow/pulse treatments.
- `src/main.tsx` — import Outfit font.
- `src/app/TopNav.{tsx,css}` — rebrand, kill switch, telemetry LEDs.
- `src/app/StatusBar.tsx` — rebrand string, scanner cadence readout.
- `src/features/cockpit/EngineStatusStrip.{tsx,css}` — daily-loss ring.
- `src/features/cockpit/ScannerMatrix.{tsx,css}` — confluence cells + why-skipped tooltips.
- `src/lib/api/systemApi.ts` — `killSwitch()`, `getAllTrades()` (if not present in another api module).
- `src/types/api.ts` — extend `ScannerRow`; add trades-all row type if needed.
- `package.json` — add `@fontsource/outfit`.

**Add:**
- `src/design-system/ProgressRing.{tsx,css}` (or under cockpit) — reusable SVG ring.
- `src/features/cockpit/HistoricalTradesTable.{tsx,css}` — search/sort/export table.
- `src/features/research-lab/RlAgentState.{tsx,css}` — RL visualizer card.

---

## 7. Non-goals / YAGNI

- No backend changes.
- No renaming of the internal `mq-` CSS prefix.
- No rewrite of components that already satisfy the spec (positions grid, leaderboard, proposals,
  equity curve, KPI cards, time-of-day, watchlist) — they receive only the theme cascade.
- No new charting library — `lightweight-charts@4.2.3` stays.
- No git init / commit as part of this work.

---

## 8. Verification

1. `cd frontend && npm run build` (tsc -b + vite build) passes with zero type errors.
2. Run `npm run dev` against the backend; visually confirm:
   - Neon palette, glass blur, glow/LED/pulse render; live-mode crimson pulse vs paper-mode cyan glow.
   - Each gap-fill feature renders and wires: kill switch POSTs, ring reflects `daily_pnl`,
     telemetry LEDs update, scanner confluence cells + why-skipped tooltips populate, historical
     table searches/sorts/exports, RL card shows counts.
3. Confirm reduced-motion disables pulses.
4. Confirm build output lands in `../static_new/`, not the live `static/`.
