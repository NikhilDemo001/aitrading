# Neon Cyber-Terminal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-theme the existing "Midnight Quant" React dashboard to a "Neon Cyber-Terminal" identity ("CIPHER · TERMINAL") and add the six interactive features that are genuinely missing, plus one surgical backend addition so the scanner confluence matrix is backed by real data.

**Architecture:** The frontend is fully token-driven — all color/shape/motion flows from CSS custom properties in `frontend/src/design-system/tokens.css`, consumed by ~30 feature components via shared primitives (`Panel`, `StatCard`, `Badge`, `Button`) and `mq-*` classes. Re-theming is therefore mostly a token swap in one file that cascades everywhere, plus targeted component edits. Live state arrives via a WS-first/poll-fallback hook into Zustand stores; click-to-fetch reads use TanStack Query. One additive backend change enriches the `/api/scanner` matrix rows with indicator snapshots.

**Tech Stack:** React 19, TypeScript, Vite 8, Zustand 5, TanStack Query 5, lightweight-charts 4.2.3, @fontsource, FastAPI (Python) backend.

## Global Constraints

- **No test runner exists** in `frontend/` (scripts: `dev`, `build`, `lint`, `preview`). The per-task verification cycle is: `cd frontend && npm run build` (runs `tsc -b` typecheck + `vite build`) must pass with **zero type errors**, followed by the described visual check via `npm run dev`. There are no frontend unit tests to write.
- **Repo is NOT under git.** "Commit" is replaced by a **checkpoint**: confirm `npm run build` passes before moving on. Do not run git commands.
- **Build output goes to `../static_new/`** (configured in `vite.config`). Never write into the live `static/` directory.
- **Backend edits are limited to the single additive change in Task 1.** `main.py` must remain importable and the existing pytest suite (179 tests) must still pass: `cd d:\coarse\upstox_Redign && python -m pytest -q`.
- **Preserve the internal `mq-` CSS class prefix** — do not rename it (pure churn).
- **Never fake data.** Fields not emitted by the backend render as `—`.
- **Currency** renders with `₹`, numeric values use the `.num` class (JetBrains Mono, tabular-nums). Profit = `--profit`, loss = `--loss`.
- **Exact palette:** `--bg: #07090E`, glass panels `rgba(15,23,42,0.6)` + `blur(16px)`, `--accent`/`--paper: #00F0FF` (cyan), `--profit: #00E676`, `--loss: #FF2D55`, `--warn: #FFB300`, `--live: #FF3B30`. Fonts: Outfit (headers), Inter (body), JetBrains Mono (numeric).

---

## File Structure

**Backend (1 file, additive):**
- `main.py` — `_matrix_set()` emits `ema_9`, `ema_20`, `vwap`, `orb_high`, `orb_low` per scanner row.

**Frontend — modify:**
- `frontend/src/design-system/tokens.css` — palette, glass, glow/LED/pulse utilities, `--font-head`.
- `frontend/src/design-system/{Badge.css,Button.tsx,Button.css,Panel.css,StatCard.css}` — neon treatments.
- `frontend/src/main.tsx` — import Outfit font.
- `frontend/src/app/TopNav.tsx` / `TopNav.css` — rebrand, kill switch, telemetry LEDs.
- `frontend/src/app/StatusBar.tsx` — rebrand string.
- `frontend/src/features/cockpit/EngineStatusStrip.tsx` / `.css` — daily-loss ring.
- `frontend/src/features/cockpit/ScannerMatrix.tsx` / `.css` — confluence cells + why-skipped tooltips.
- `frontend/src/features/cockpit/CockpitTab.tsx` — mount historical trades table.
- `frontend/src/features/research-lab/ResearchLabTab.tsx` — mount RL agent subtab.
- `frontend/src/types/api.ts` — extend `ScannerRow`, `Trade`, `BotStatus`.

**Frontend — create:**
- `frontend/src/design-system/ProgressRing.tsx` / `.css` — reusable SVG progress ring.
- `frontend/src/features/cockpit/HistoricalTradesTable.tsx` / `.css` — search/sort/export table.
- `frontend/src/features/research-lab/RlAgentState.tsx` / `.css` — RL visualizer card.

---

## Task 1: Backend — scanner indicator enrichment

**Files:**
- Modify: `main.py` — `_matrix_set()` at lines 472-498.

**Interfaces:**
- Produces: each `/api/scanner` matrix row and the WS `scanner` payload rows gain optional numeric fields `ema_9`, `ema_20`, `vwap`, `orb_high`, `orb_low` (present only when candles are available; otherwise absent).

- [ ] **Step 1: Add indicator snapshot to `_matrix_set`**

In `main.py`, inside `_matrix_set`, extend the existing `if candles:` block (currently lines 485-497). After the `rec["regime"] = detect_market_regime(candles)` line and before the `except Exception:` , add EMA/VWAP/ORB snapshots. The final block becomes:

```python
    if candles:
        try:
            close = [c["close"] for c in candles]
            rec["ltp"] = round(close[-1], 2)
            atr = calculate_atr(candles, 14)
            if atr and atr[-1]:
                rec["atr_pct"] = round(atr[-1] / close[-1] * 100, 2)
            rsi = calculate_rsi(close, 14)
            if rsi and rsi[-1]:
                rec["rsi"] = round(rsi[-1], 1)
            rec["regime"] = detect_market_regime(candles)
            # Indicator snapshot for the frontend confluence matrix (additive; safe if any fail).
            ema9 = calculate_ema(close, 9)
            if ema9 and ema9[-1] is not None:
                rec["ema_9"] = round(ema9[-1], 2)
            ema20 = calculate_ema(close, 20)
            if ema20 and ema20[-1] is not None:
                rec["ema_20"] = round(ema20[-1], 2)
            vwap = calculate_vwap(candles)
            if vwap and vwap[-1] is not None:
                rec["vwap"] = round(vwap[-1], 2)
            try:
                from strategy_support_resistance import _get_opening_range
                today_str = get_ist_now().date().isoformat()
                orh, orl = _get_opening_range(candles, today_str)
                if orh is not None:
                    rec["orb_high"] = round(orh, 2)
                if orl is not None:
                    rec["orb_low"] = round(orl, 2)
            except Exception:
                pass
        except Exception:
            pass
    scan_matrix[symbol] = rec
```

Note: `calculate_ema`, `calculate_vwap`, `calculate_atr`, `calculate_rsi` are already imported at the top of `main.py` (line 24). `_get_opening_range` is imported lazily inside the inner try to avoid touching module-level imports.

- [ ] **Step 2: Verify backend still imports and tests pass**

Run: `cd d:\coarse\upstox_Redign && python -m pytest -q`
Expected: same pass count as before the change (baseline 179 passed), 0 new failures. The change is additive and guarded by try/except.

- [ ] **Step 3: Verify the endpoint emits the new fields (manual, optional if server runnable)**

If the backend can be started, hit `GET /api/scanner` after a scan sweep and confirm rows that have candles include `ema_9`/`ema_20`/`vwap` (and `orb_high`/`orb_low` after 09:30 IST). If the server isn't running in this environment, rely on Step 2 — the frontend degrades gracefully to `—` for absent fields.

- [ ] **Step 4: Checkpoint** — pytest green.

---

## Task 2: Theme foundation — tokens, glow/LED utilities, Outfit font

**Files:**
- Modify: `frontend/src/design-system/tokens.css` (`:root` block lines 1-65; pulse utilities).
- Modify: `frontend/src/main.tsx` (font imports).
- Modify: `frontend/package.json` (add `@fontsource/outfit`).

**Interfaces:**
- Produces: CSS custom properties `--bg #07090E`, `--panel rgba(15,23,42,0.6)`, `--accent #00F0FF`, `--paper #00F0FF`, `--live #FF3B30`, `--profit #00E676`, `--loss #FF2D55`, `--warn #FFB300`, `--font-head`. New utility classes `.led`, `.led-pulse`, `.neon-text`, and glow tokens `--glow-cyan/-green/-magenta/-amber/-crimson`.

- [ ] **Step 1: Add the Outfit font dependency**

Run: `cd d:\coarse\upstox_Redign\frontend && npm install @fontsource/outfit`
Expected: `@fontsource/outfit` added to `package.json` dependencies.

- [ ] **Step 2: Import Outfit weights in `main.tsx`**

In `frontend/src/main.tsx`, add after the JetBrains Mono imports (after line 9):

```tsx
import '@fontsource/outfit/500.css'
import '@fontsource/outfit/600.css'
import '@fontsource/outfit/700.css'
```

- [ ] **Step 3: Swap the palette + add tokens in `tokens.css`**

In `frontend/src/design-system/tokens.css`, replace the `:root` variable definitions (lines 2-56, from `--bg` through `--ease-float`) with:

```css
  /* Neon Cyber-Terminal — base surfaces */
  --bg: #07090E;
  --bg-raised: #0C0F17;
  --panel: rgba(15, 23, 42, 0.6);
  --panel-solid: #0E1420;
  --border: rgba(255, 255, 255, 0.08);
  --border-strong: rgba(255, 255, 255, 0.16);

  /* Accent — neon cyan */
  --accent: #00F0FF;
  --accent-dim: rgba(0, 240, 255, 0.14);
  --accent-glow: rgba(0, 240, 255, 0.45);

  /* Trading-mode accents */
  --paper: #00F0FF;
  --paper-glow: rgba(0, 240, 255, 0.5);
  --live: #FF3B30;
  --live-glow: rgba(255, 59, 48, 0.55);

  /* Signal colors */
  --profit: #00E676;
  --profit-dim: rgba(0, 230, 118, 0.14);
  --loss: #FF2D55;
  --loss-dim: rgba(255, 45, 85, 0.14);
  --warn: #FFB300;
  --warn-dim: rgba(255, 179, 0, 0.14);
  --info: #38BDF8;

  /* Ink */
  --ink: #EAF6F8;
  --ink-dim: #9AA6B8;
  --ink-faint: #5E6675;

  /* Type */
  --font-head: 'Outfit', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-ui: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'JetBrains Mono', 'IBM Plex Mono', monospace;

  /* Shape */
  --r-sm: 6px;
  --r-md: 10px;
  --r-lg: 12px;
  --r-xl: 16px;

  /* Neon glow tokens (RGB triplets for rgba() interpolation) */
  --glow-cyan: 0, 240, 255;
  --glow-green: 0, 230, 118;
  --glow-magenta: 255, 45, 85;
  --glow-amber: 255, 179, 0;
  --glow-crimson: 255, 59, 48;

  /* Elevation / glass */
  --panel-shadow:
    0 1px 1px rgba(0, 0, 0, 0.40),
    0 6px 14px rgba(0, 0, 0, 0.44),
    0 18px 40px rgba(0, 0, 0, 0.50),
    inset 0 1px 0 rgba(255, 255, 255, 0.04);
  --panel-shadow-lift:
    0 2px 4px rgba(0, 0, 0, 0.42),
    0 12px 24px rgba(0, 0, 0, 0.50),
    0 30px 60px rgba(0, 0, 0, 0.56),
    0 0 0 1px rgba(0, 240, 255, 0.20),
    inset 0 1px 0 rgba(255, 255, 255, 0.06);
  --panel-glow-inset: inset 0 0 0 1px var(--border), inset 0 0 24px rgba(0, 240, 255, 0.05);
  --blur-glass: blur(16px);
  --ease-float: cubic-bezier(0.22, 1, 0.36, 1);
```

- [ ] **Step 4: Update the hardcoded indigo references in `tokens.css`**

In the same file, update the scrollbar and selection rules that reference the old indigo `rgba(124,108,255,...)`:
- `::selection` background stays `var(--accent-glow)` (already token-based — no change).
- Replace every `rgba(124, 108, 255, X)` / `rgba(124,108,255,X)` occurrence in the `scrollbar-color`, `*::-webkit-scrollbar-thumb`, and `.mq-stagger`/glow rules with `rgba(0, 240, 255, X)` (same alpha values).

- [ ] **Step 5: Append glow/LED/neon utilities to `tokens.css`**

Add at the end of `frontend/src/design-system/tokens.css`:

```css
/* ── Neon LED + glow utilities ─────────────────────────────────────────────── */
.led {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ink-faint);
  box-shadow: 0 0 6px 1px rgba(94, 102, 117, 0.6);
}
.led-cyan    { background: var(--accent); box-shadow: 0 0 8px 1px rgba(var(--glow-cyan), 0.7); }
.led-green   { background: var(--profit); box-shadow: 0 0 8px 1px rgba(var(--glow-green), 0.7); }
.led-magenta { background: var(--loss);   box-shadow: 0 0 8px 1px rgba(var(--glow-magenta), 0.7); }
.led-amber   { background: var(--warn);   box-shadow: 0 0 8px 1px rgba(var(--glow-amber), 0.7); }
.led-crimson { background: var(--live);   box-shadow: 0 0 8px 1px rgba(var(--glow-crimson), 0.7); }
.led-off     { background: var(--ink-faint); box-shadow: none; opacity: 0.5; }

.led-pulse { animation: led-pulse 1.6s ease-out infinite; }
@keyframes led-pulse {
  0%   { box-shadow: 0 0 0 0 rgba(var(--led-rgb, 0,240,255), 0.55), 0 0 8px 1px rgba(var(--led-rgb, 0,240,255), 0.7); }
  70%  { box-shadow: 0 0 0 8px rgba(var(--led-rgb, 0,240,255), 0),   0 0 8px 1px rgba(var(--led-rgb, 0,240,255), 0.7); }
  100% { box-shadow: 0 0 0 0 rgba(var(--led-rgb, 0,240,255), 0),     0 0 8px 1px rgba(var(--led-rgb, 0,240,255), 0.7); }
}
.led-cyan.led-pulse    { --led-rgb: var(--glow-cyan); }
.led-green.led-pulse   { --led-rgb: var(--glow-green); }
.led-magenta.led-pulse { --led-rgb: var(--glow-magenta); }
.led-amber.led-pulse   { --led-rgb: var(--glow-amber); }
.led-crimson.led-pulse { --led-rgb: var(--glow-crimson); }

.neon-text { text-shadow: 0 0 8px rgba(var(--glow-cyan), 0.55); }
.neon-text-live { text-shadow: 0 0 10px rgba(var(--glow-crimson), 0.7); }

/* Live-mode surface pulse (real capital); paper mode uses a steady cyan glow (no animation). */
@keyframes live-pulse {
  0%, 100% { box-shadow: 0 0 0 1px rgba(var(--glow-crimson), 0.5), 0 0 16px rgba(var(--glow-crimson), 0.35); }
  50%      { box-shadow: 0 0 0 1px rgba(var(--glow-crimson), 0.9), 0 0 26px rgba(var(--glow-crimson), 0.6); }
}
.surface-live  { animation: live-pulse 2s ease-in-out infinite; border-color: rgba(var(--glow-crimson), 0.6) !important; }
.surface-paper { box-shadow: 0 0 0 1px rgba(var(--glow-cyan), 0.4), 0 0 18px rgba(var(--glow-cyan), 0.28); border-color: rgba(var(--glow-cyan), 0.5) !important; }
```

- [ ] **Step 6: Extend the reduced-motion block**

In the existing `@media (prefers-reduced-motion: reduce)` block in `tokens.css`, add `.led-pulse` and `.surface-live` to the `animation: none !important;` selector list so the new pulses are disabled for reduced-motion users:

```css
  .mq-rise,
  .mq-stagger > *,
  .led-pulse,
  .surface-live {
    animation: none !important;
  }
```

- [ ] **Step 7: Build + visual checkpoint**

Run: `cd d:\coarse\upstox_Redign\frontend && npm run build`
Expected: PASS, zero type errors.
Then `npm run dev` and confirm: background is near-black slate, accents/scrollbars are cyan, profit green / loss magenta / warn amber, panels blur. Fonts load (Outfit visible on headers once Task 6 applies it; body already Inter).

---

## Task 3: Shared design-system neon treatments

**Files:**
- Modify: `frontend/src/design-system/Badge.css`, `Button.tsx`, `Button.css`, `Panel.css`, `StatCard.css`.

**Interfaces:**
- Consumes: tokens/utilities from Task 2.
- Produces: `Button` gains a new variant `'kill'` (crimson, glowing, pulsing) in its `Variant` union; `StatusDot` pulse renders per-tone neon rings.

- [ ] **Step 1: Per-tone neon pulse for `StatusDot` in `Badge.css`**

In `frontend/src/design-system/Badge.css`, replace the `.mq-dot-*` color rules and the pulse keyframe (lines 30-46) with:

```css
.mq-dot-neutral { background: var(--ink-faint); --dot-rgb: 94,102,117; }
.mq-dot-accent  { background: var(--accent); --dot-rgb: var(--glow-cyan); box-shadow: 0 0 6px 1px rgba(var(--glow-cyan),0.6); }
.mq-dot-profit  { background: var(--profit); --dot-rgb: var(--glow-green); box-shadow: 0 0 6px 1px rgba(var(--glow-green),0.6); }
.mq-dot-loss    { background: var(--loss); --dot-rgb: var(--glow-magenta); box-shadow: 0 0 6px 1px rgba(var(--glow-magenta),0.6); }
.mq-dot-warn    { background: var(--warn); --dot-rgb: var(--glow-amber); box-shadow: 0 0 6px 1px rgba(var(--glow-amber),0.6); }
.mq-dot-info    { background: var(--info); --dot-rgb: 56,189,248; box-shadow: 0 0 6px 1px rgba(56,189,248,0.6); }

.mq-dot-pulse { animation: mq-dot-pulse 1.6s ease-out infinite; }

@keyframes mq-dot-pulse {
  0%   { box-shadow: 0 0 0 0 rgba(var(--dot-rgb,0,240,255),0.55), 0 0 6px 1px rgba(var(--dot-rgb,0,240,255),0.6); }
  70%  { box-shadow: 0 0 0 7px rgba(var(--dot-rgb,0,240,255),0), 0 0 6px 1px rgba(var(--dot-rgb,0,240,255),0.6); }
  100% { box-shadow: 0 0 0 0 rgba(var(--dot-rgb,0,240,255),0), 0 0 6px 1px rgba(var(--dot-rgb,0,240,255),0.6); }
}
```

Also update the `.mq-badge-*` border colors (lines 16-19) to the new palette RGB: accent `rgba(0,240,255,0.3)`, profit `rgba(0,230,118,0.3)`, loss `rgba(255,45,85,0.3)`, warn `rgba(255,179,0,0.3)`.

- [ ] **Step 2: Add the `'kill'` variant to `Button.tsx`**

In `frontend/src/design-system/Button.tsx`, extend the `Variant` type (line 4):

```tsx
type Variant = 'primary' | 'ghost' | 'danger' | 'success' | 'kill'
```

(No other change — the class is emitted as `mq-btn-kill`.)

- [ ] **Step 3: Neon button treatments in `Button.css`**

In `frontend/src/design-system/Button.css`, replace the color of `mq-btn-primary`/`mq-btn-success` text-on-accent hardcoded hex with tokens, and add glow + the kill variant. Update lines 24-43 and append:

```css
.mq-btn-primary {
  background: var(--accent);
  color: var(--bg);
  border-color: var(--accent);
}
.mq-btn-primary:hover { box-shadow: 0 0 0 3px var(--accent-dim), 0 0 14px rgba(var(--glow-cyan),0.5); }

.mq-btn-success {
  background: var(--profit);
  color: #04140C;
  border-color: var(--profit);
}
.mq-btn-success:hover { box-shadow: 0 0 0 3px var(--profit-dim), 0 0 14px rgba(var(--glow-green),0.5); }

.mq-btn-danger {
  background: transparent;
  color: var(--loss);
  border-color: rgba(255,45,85,0.45);
}
.mq-btn-danger:hover { background: var(--loss-dim); box-shadow: 0 0 12px rgba(var(--glow-magenta),0.4); }

.mq-btn-kill {
  background: var(--live);
  color: #FFF;
  border-color: var(--live);
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  box-shadow: 0 0 14px rgba(var(--glow-crimson),0.55);
  animation: mq-kill-pulse 1.8s ease-in-out infinite;
}
.mq-btn-kill:hover { box-shadow: 0 0 22px rgba(var(--glow-crimson),0.85); }
@keyframes mq-kill-pulse {
  0%, 100% { box-shadow: 0 0 12px rgba(var(--glow-crimson),0.45); }
  50%      { box-shadow: 0 0 22px rgba(var(--glow-crimson),0.8); }
}
@media (prefers-reduced-motion: reduce) { .mq-btn-kill { animation: none !important; } }
```

- [ ] **Step 4: Glass + header font in `Panel.css`**

In `frontend/src/design-system/Panel.css`, ensure `.mq-panel` uses `background: var(--panel)` + `backdrop-filter: var(--blur-glass)` + `border: 1px solid var(--border)` + `box-shadow: var(--panel-shadow)` (update whatever the current background is to `var(--panel)`), and set the header title font to headers: add/replace the `.mq-panel-hdr h3` rule with `font-family: var(--font-head); font-weight: 600; letter-spacing: 0.01em;`.

- [ ] **Step 5: Value glow in `StatCard.css`**

In `frontend/src/design-system/StatCard.css`, add tone-driven neon glow to the value: for `.mq-statcard-value-profit` add `text-shadow: 0 0 10px rgba(var(--glow-green),0.5);`, for `.mq-statcard-value-loss` add `text-shadow: 0 0 10px rgba(var(--glow-magenta),0.5);`, for `.mq-statcard-value-accent` add `text-shadow: 0 0 10px rgba(var(--glow-cyan),0.5);`. Set `.mq-statcard-label { font-family: var(--font-head); }`.

- [ ] **Step 6: Build + visual checkpoint**

Run: `cd d:\coarse\upstox_Redign\frontend && npm run build` — Expected: PASS.
`npm run dev`: badges/dots glow per tone; buttons glow on hover; panels are glass-blurred; StatCard values glow.

---

## Task 4: Rebrand to CIPHER · TERMINAL

**Files:**
- Modify: `frontend/src/app/TopNav.tsx` (lines 34-40), `frontend/src/app/TopNav.css` (`.mq-brand-mark` lines 24-38, `.mq-brand-name`), `frontend/src/app/StatusBar.tsx` (line 41).

**Interfaces:** cosmetic only.

- [ ] **Step 1: Update the wordmark in `TopNav.tsx`**

In `frontend/src/app/TopNav.tsx`, replace the brand block (lines 34-40):

```tsx
        <div className="mq-brand">
          <div className="mq-brand-mark">CT</div>
          <div className="mq-brand-text">
            <span className="mq-brand-name neon-text">CIPHER · TERMINAL</span>
            <span className="mq-brand-sub">UPSTOX INTRADAY AUTOPILOT</span>
          </div>
        </div>
```

- [ ] **Step 2: Cyan mark + header font in `TopNav.css`**

In `frontend/src/app/TopNav.css`, update `.mq-brand-mark` (lines 24-38): change `background: linear-gradient(135deg, var(--accent), #4C3ED9);` to `background: linear-gradient(135deg, var(--accent), #0088A8);`, change `color: #0A0B0F;` to `color: var(--bg);`, and `box-shadow: 0 0 16px var(--accent-glow);` stays. Set `.mq-brand-name { font-family: var(--font-head); }` (add to the existing rule at lines 47-53). Update `.mq-tab-btn.active` (lines 119-122) already token-based (`--accent`/`--accent-dim`) — no change needed.

- [ ] **Step 3: Update the StatusBar brand string**

In `frontend/src/app/StatusBar.tsx` line 41, replace `MIDNIGHT·QUANT · NSE INTRADAY · UPSTOX V3` with `CIPHER·TERMINAL · NSE INTRADAY · UPSTOX V3`.

- [ ] **Step 4: Build + visual checkpoint**

Run: `npm run build` — PASS. `npm run dev`: header shows "CT" cyan-glow mark + "CIPHER · TERMINAL" in Outfit; footer brand string updated.

---

## Task 5: Emergency Kill Switch button

**Files:**
- Modify: `frontend/src/app/TopNav.tsx` (imports + `mq-nav-actions` block lines 49-61).

**Interfaces:**
- Consumes: `statusApi.killSwitch()` (already exists, `statusApi.ts:7`); `Button` `'kill'` variant (Task 3).

- [ ] **Step 1: Add a kill handler + button in `TopNav.tsx`**

In `frontend/src/app/TopNav.tsx`, add a handler alongside the existing `handleSquareOff` (after line 29):

```tsx
  const handleKill = () => {
    if (confirm('EMERGENCY KILL: halt the bot and square off ALL open positions immediately. Continue?')) {
      statusApi.killSwitch().catch(console.error)
    }
  }
```

Then in the `mq-nav-actions` div (lines 49-61), add as the last button (after Square Off):

```tsx
          <Button variant="kill" onClick={handleKill} title="Emergency stop — halt bot and square off all positions">
            <span className="mq-btn-full">Kill Switch</span>
            <span className="mq-btn-short">KILL</span>
          </Button>
```

- [ ] **Step 2: Build + visual checkpoint**

Run: `npm run build` — PASS. `npm run dev`: a pulsing crimson "Kill Switch" button appears in the header; clicking prompts a confirm; confirming POSTs to `/api/kill-switch` (verify in Network tab / backend log).

---

## Task 6: Connection telemetry LEDs (scanner cadence + WS ping)

**Files:**
- Modify: `frontend/src/types/api.ts` (`BotStatus` — add scanner cadence fields).
- Modify: `frontend/src/app/TopNav.tsx` (LED strip lines 42-47).

**Interfaces:**
- Consumes: `useBotStore` `status` (`scanner_last_loop`, `scanner_last_checked` from `/api/status`) and `connected`.
- Produces: `BotStatus` gains `scanner_last_loop?: string | null` and `scanner_last_checked?: string | null`.

- [ ] **Step 1: Type the cadence fields in `api.ts`**

In `frontend/src/types/api.ts`, inside `interface BotStatus` (before the index signature `[key: string]: unknown` at line 16), add:

```ts
  scanner_last_loop?: string | null
  scanner_last_checked?: string | null
```

- [ ] **Step 2: Add cadence + ping LEDs in `TopNav.tsx`**

In `frontend/src/app/TopNav.tsx`, read the fields near the other status reads (after line 25):

```tsx
  const scanLastLoop = (status?.scanner_last_loop as string | null) ?? null
  const scanLastChecked = (status?.scanner_last_checked as string | null) ?? null
```

Then inside the `mq-led-strip` div (lines 42-47), replace the existing `.mq-led` items with the LED-utility versions and append two cadence readouts. Use the new `.led` classes (per-tone + pulse) instead of `StatusDot` for the neon look:

```tsx
        <div className="mq-led-strip" role="status" aria-label="System status">
          <span className="mq-led" title="Server / live WebSocket connection">
            <span className={`led ${connected ? 'led-green led-pulse' : 'led-magenta'}`} /> <span className="mq-led-text">{connected ? 'WS' : 'POLL'}</span>
          </span>
          <span className="mq-led" title="Broker API">
            <span className={`led ${authenticated ? 'led-green' : 'led-off'}`} /> <span className="mq-led-text">API</span>
          </span>
          <span className="mq-led" title={paperTrading ? 'Paper trading (simulated)' : 'LIVE trading (real capital)'}>
            <span className={`led ${paperTrading ? 'led-cyan' : 'led-crimson led-pulse'}`} /> <span className="mq-led-text">{paperTrading ? 'PAPER' : 'LIVE'}</span>
          </span>
          <span className="mq-led" title="Bot engine">
            <span className={`led ${botRunning ? 'led-cyan led-pulse' : 'led-off'}`} /> <span className="mq-led-text">BOT</span>
          </span>
          <span className="mq-led" title="Last scanner sweep">
            <span className={`led ${scanLastLoop ? 'led-cyan' : 'led-off'}`} /> <span className="mq-led-text num">{scanLastLoop ?? '—'}</span>
          </span>
          <span className="mq-led" title="Last symbol checked">
            <span className="led led-amber" /> <span className="mq-led-text">{scanLastChecked ?? '—'}</span>
          </span>
        </div>
```

Remove the now-unused `StatusDot` import if no longer referenced in the file (check — `TopNav` no longer uses it after this change; delete the import on line 3).

- [ ] **Step 3: Build + visual checkpoint**

Run: `npm run build` — PASS (confirm no unused-import TS error for `StatusDot`). `npm run dev`: LED strip shows glowing per-status LEDs; PAPER shows steady cyan, LIVE shows pulsing crimson; last-loop timestamp + last-checked symbol render (or `—` when absent).

---

## Task 7: Daily-loss progress ring

**Files:**
- Create: `frontend/src/design-system/ProgressRing.tsx`, `frontend/src/design-system/ProgressRing.css`.
- Modify: `frontend/src/features/cockpit/EngineStatusStrip.tsx`.

**Interfaces:**
- Produces: `ProgressRing({ pct, size?, tone, label, sub })` — `pct` 0-100, `tone: 'profit'|'warn'|'loss'`, renders an SVG ring with centered label.

- [ ] **Step 1: Create `ProgressRing.tsx`**

```tsx
import './ProgressRing.css'

export function ProgressRing({
  pct,
  size = 96,
  tone = 'warn',
  label,
  sub,
}: {
  pct: number
  size?: number
  tone?: 'profit' | 'warn' | 'loss'
  label: string
  sub?: string
}) {
  const clamped = Math.min(100, Math.max(0, pct))
  const stroke = 8
  const r = (size - stroke) / 2
  const circ = 2 * Math.PI * r
  const offset = circ * (1 - clamped / 100)
  return (
    <div className={`mq-ring mq-ring-${tone}`} style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} className="mq-ring-track" strokeWidth={stroke} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          className="mq-ring-bar"
          strokeWidth={stroke}
          fill="none"
          strokeDasharray={circ}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <div className="mq-ring-center">
        <span className="mq-ring-label num">{label}</span>
        {sub && <span className="mq-ring-sub">{sub}</span>}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Create `ProgressRing.css`**

```css
.mq-ring { position: relative; display: inline-flex; align-items: center; justify-content: center; }
.mq-ring svg { display: block; }
.mq-ring-track { stroke: rgba(255,255,255,0.07); }
.mq-ring-bar { transition: stroke-dashoffset 0.6s var(--ease-float); }
.mq-ring-profit .mq-ring-bar { stroke: var(--profit); filter: drop-shadow(0 0 6px rgba(var(--glow-green),0.7)); }
.mq-ring-warn  .mq-ring-bar { stroke: var(--warn);   filter: drop-shadow(0 0 6px rgba(var(--glow-amber),0.7)); }
.mq-ring-loss  .mq-ring-bar { stroke: var(--loss);   filter: drop-shadow(0 0 6px rgba(var(--glow-magenta),0.7)); }
.mq-ring-center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
.mq-ring-label { font-family: var(--font-mono); font-size: 0.9rem; font-weight: 700; }
.mq-ring-sub { font-family: var(--font-head); font-size: 0.5rem; letter-spacing: 0.08em; color: var(--ink-faint); text-transform: uppercase; margin-top: 2px; }
```

- [ ] **Step 3: Wire the ring into `EngineStatusStrip.tsx`**

In `frontend/src/features/cockpit/EngineStatusStrip.tsx`, import the ring (`import { ProgressRing } from '../../design-system/ProgressRing'`). The existing loss-budget math (lines 12-19) stays. Replace the first `StatCard` (the Daily P&L one, lines 23-28) with a P&L card that carries the ring as its `right` slot:

```tsx
      <StatCard
        label="Daily P&L"
        tone={pnlTone}
        value={`${dailyPnl >= 0 ? '+' : ''}₹${dailyPnl.toFixed(2)}`}
        sub={subText}
        right={
          isPaper ? (
            <ProgressRing pct={0} tone="profit" label="∞" sub="Paper" />
          ) : (
            <ProgressRing
              pct={lossBudgetUsed}
              tone={lossBudgetUsed >= 80 ? 'loss' : lossBudgetUsed >= 50 ? 'warn' : 'profit'}
              label={`${lossBudgetUsed.toFixed(0)}%`}
              sub="Loss used"
            />
          )
        }
      />
```

- [ ] **Step 4: Build + visual checkpoint**

Run: `npm run build` — PASS. `npm run dev`: Daily P&L card shows a glowing ring; in paper mode it reads `∞ / Paper`; in live mode it fills amber→crimson with the loss-budget %.

---

## Task 8: Scanner confluence cells + "Why It Skipped" tooltips

**Files:**
- Modify: `frontend/src/types/api.ts` (`ScannerRow`).
- Modify: `frontend/src/features/cockpit/ScannerMatrix.tsx`, `frontend/src/features/cockpit/ScannerMatrix.css`.

**Interfaces:**
- Consumes: `useScannerStore` matrix rows (now with `ema_9/ema_20/vwap/orb_high/orb_low` from Task 1) + scanner `context`; `systemApi.getDecisions()` (already exists) for the `gate` reason; TanStack Query `useQuery`.
- Produces: helper `confluenceScore(row)` → `{ score: number; total: number; parts: {label:string; on:boolean}[] }`.

- [ ] **Step 1: Extend `ScannerRow` in `api.ts`**

In `frontend/src/types/api.ts`, inside `interface ScannerRow` (before the index signature line 62), add:

```ts
  status?: string
  ema_9?: number
  ema_20?: number
  vwap?: number
  orb_high?: number
  orb_low?: number
```

- [ ] **Step 2: Add confluence + tooltip logic and cells in `ScannerMatrix.tsx`**

Replace the full contents of `frontend/src/features/cockpit/ScannerMatrix.tsx` with:

```tsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Badge } from '../../design-system/Badge'
import { Button } from '../../design-system/Button'
import { useScannerStore } from '../../lib/stores/useScannerStore'
import { systemApi } from '../../lib/api/systemApi'
import type { ScannerRow } from '../../types/api'
import './ScannerMatrix.css'

function statusTone(status?: string, decision?: string): 'profit' | 'loss' | 'warn' | 'neutral' {
  const s = (status ?? '').toLowerCase()
  if (s === 'entered') return 'profit'
  if (s === 'filtered' || s === 'skipped') return 'loss'
  if (s === 'no_signal' || s === 'no_data' || s === 'error') return 'warn'
  if (s === 'in_position') return 'neutral'
  // fallback to decision text
  if (decision && /enter|buy|long|sell|short|trade/i.test(decision)) return 'profit'
  if (decision && /reject|skip|filter|no/i.test(decision)) return 'loss'
  return 'neutral'
}

// Frontend-derived confluence: how many real emitted indicators the LTP is on the bullish
// side of. All inputs are real (Task 1 backend snapshot); nothing is faked.
function confluenceScore(row: ScannerRow): { score: number; total: number; parts: { label: string; on: boolean | null }[] } {
  const ltp = row.ltp
  const parts: { label: string; on: boolean | null }[] = [
    { label: 'EMA9', on: ltp != null && row.ema_9 != null ? ltp >= row.ema_9 : null },
    { label: 'EMA20', on: ltp != null && row.ema_20 != null ? ltp >= row.ema_20 : null },
    { label: 'VWAP', on: ltp != null && row.vwap != null ? ltp >= row.vwap : null },
    { label: 'ORB', on: ltp != null && row.orb_high != null ? ltp >= row.orb_high : (ltp != null && row.orb_low != null ? ltp <= row.orb_low : null) },
  ]
  const known = parts.filter((p) => p.on !== null)
  const score = known.filter((p) => p.on === true).length
  return { score, total: known.length, parts }
}

export function ScannerMatrix() {
  const matrix = useScannerStore((s) => s.scanner.matrix)
  const context = useScannerStore((s) => s.scanner.context) as Record<string, unknown> | undefined
  const checking = useScannerStore((s) => s.checkingSymbol)
  const [view, setView] = useState<'table' | 'heat'>('table')

  const { data: decisions } = useQuery({
    queryKey: ['decisions', 'scanner'],
    queryFn: () => systemApi.getDecisions(200),
    refetchInterval: 5000,
  })
  // Latest decision gate keyed by symbol, for the "why it skipped" tooltip.
  const gateBySymbol = new Map<string, string>()
  for (const d of decisions ?? []) {
    if (d.symbol && !gateBySymbol.has(d.symbol)) gateBySymbol.set(d.symbol, d.gate || d.reason || '')
  }

  const vixActive = Boolean(context?.vix_filter_active)
  const vix = context?.india_vix as number | undefined

  const tooltipFor = (row: ScannerRow) => {
    const gate = gateBySymbol.get(row.symbol)
    return gate ? `${row.decision ?? ''}\nGate: ${gate}` : (row.decision ?? '')
  }

  return (
    <Panel
      title="Scanner · Confluence Matrix"
      padded={false}
      actions={
        <>
          <Badge tone={vixActive ? 'warn' : 'neutral'}>VIX {vix != null ? vix.toFixed(1) : '—'}{vixActive ? ' ⚠' : ''}</Badge>
          {checking?.status === 'checking' && <Badge tone="accent">Scanning {checking.symbol}</Badge>}
          <Button variant={view === 'table' ? 'primary' : 'ghost'} onClick={() => setView('table')}>Table</Button>
          <Button variant={view === 'heat' ? 'primary' : 'ghost'} onClick={() => setView('heat')}>Heat Grid</Button>
        </>
      }
    >
      {matrix.length === 0 ? (
        <div className="mq-scanner-empty text-faint">No scan data yet.</div>
      ) : view === 'table' ? (
        <table className="mq-scanner-table">
          <thead>
            <tr>
              <th>Symbol</th><th>LTP</th><th>EMA9</th><th>EMA20</th><th>VWAP</th><th>ORB</th><th>ATR%</th><th>Conf.</th><th>Decision</th><th>At</th>
            </tr>
          </thead>
          <tbody>
            {matrix.map((row) => {
              const c = confluenceScore(row)
              const cell = (v: number | undefined, on: boolean | null) =>
                v == null ? <span className="text-faint">—</span> : <span className={on ? 'text-profit' : 'text-loss'}>{v.toFixed(2)}</span>
              return (
                <tr key={row.symbol} title={tooltipFor(row)} className="mq-scanner-row">
                  <td className="mq-scanner-sym">{row.symbol}</td>
                  <td className="num">{row.ltp?.toFixed(2) ?? '—'}</td>
                  <td className="num">{cell(row.ema_9, row.ltp != null && row.ema_9 != null ? row.ltp >= row.ema_9 : null)}</td>
                  <td className="num">{cell(row.ema_20, row.ltp != null && row.ema_20 != null ? row.ltp >= row.ema_20 : null)}</td>
                  <td className="num">{cell(row.vwap, row.ltp != null && row.vwap != null ? row.ltp >= row.vwap : null)}</td>
                  <td className="num">{row.orb_high != null || row.orb_low != null ? `${row.orb_low?.toFixed(0) ?? '—'}/${row.orb_high?.toFixed(0) ?? '—'}` : '—'}</td>
                  <td className="num">{row.atr_pct?.toFixed(2) ?? '—'}</td>
                  <td><span className={`mq-conf mq-conf-${c.score >= 3 ? 'hi' : c.score >= 2 ? 'mid' : 'lo'}`}>{c.total ? `${c.score}/${c.total}` : '—'}</span></td>
                  <td><Badge tone={statusTone(row.status, row.decision)}>{row.decision ?? '—'}</Badge></td>
                  <td className="text-faint">{row.time ?? row.at ?? '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : (
        <div className="mq-scanner-heat">
          {matrix.map((row) => {
            const c = confluenceScore(row)
            const tone = statusTone(row.status, row.decision)
            return (
              <div key={row.symbol} className={`mq-heat-tile mq-heat-${tone}`} title={tooltipFor(row)} style={{ '--conf': c.total ? c.score / c.total : 0 } as React.CSSProperties}>
                <span className="mq-heat-sym">{row.symbol}</span>
                <span className="mq-heat-conf num">{c.total ? `${c.score}/${c.total}` : '—'}</span>
                <span className="mq-heat-atr num">{row.atr_pct?.toFixed(1) ?? '—'}%</span>
              </div>
            )
          })}
        </div>
      )}
    </Panel>
  )
}
```

Note: `useScannerStore` exposes `scanner.context` (confirmed used in `EngineStatusStrip.tsx:10`) and `checkingSymbol` (used in the original `ScannerMatrix`). `systemApi.getDecisions` returns `DecisionEntry[]` with `symbol`, `reason`, `gate?` (`systemApi.ts:43`, `types/api.ts DecisionEntry`).

- [ ] **Step 3: Add confluence/heat styles to `ScannerMatrix.css`**

Append to `frontend/src/features/cockpit/ScannerMatrix.css`:

```css
.mq-scanner-row { cursor: help; }
.mq-conf { font-family: var(--font-mono); font-weight: 700; font-size: 0.7rem; padding: 1px 6px; border-radius: var(--r-sm); }
.mq-conf-hi  { color: var(--profit); background: var(--profit-dim); text-shadow: 0 0 8px rgba(var(--glow-green),0.6); }
.mq-conf-mid { color: var(--warn); background: var(--warn-dim); }
.mq-conf-lo  { color: var(--loss); background: var(--loss-dim); }
.mq-heat-conf { font-weight: 700; color: var(--ink); }
.mq-heat-tile { position: relative; }
.mq-heat-tile::after {
  content: ''; position: absolute; inset: 0; border-radius: inherit; pointer-events: none;
  box-shadow: inset 0 0 calc(2px + var(--conf, 0) * 16px) rgba(var(--glow-cyan), calc(var(--conf, 0) * 0.6));
}
```

- [ ] **Step 4: Build + visual checkpoint**

Run: `npm run build` — PASS. `npm run dev`: scanner table shows EMA9/EMA20/VWAP (green when LTP above, magenta below, `—` if absent), ORB low/high, ATR%, and a confluence `n/N` chip; hovering a row shows the decision + gate tooltip; VIX badge in the header reflects `vix_filter_active`. Heat grid tiles glow proportionally to confluence.

---

## Task 9: Historical trades table (search / sort / R-multiple / CSV)

**Files:**
- Modify: `frontend/src/types/api.ts` (`Trade` — add `stop_loss?`).
- Create: `frontend/src/features/cockpit/HistoricalTradesTable.tsx`, `HistoricalTradesTable.css`.
- Modify: `frontend/src/features/cockpit/CockpitTab.tsx` (mount it after `ClosedTradesTable`).

**Interfaces:**
- Consumes: `positionsApi.getTradesAll()` (already exists, `statusApi.ts:17`), returns `Trade[]`.
- Produces: `HistoricalTradesTable` component (no props).

- [ ] **Step 1: Add `stop_loss` to `Trade` in `api.ts`**

In `frontend/src/types/api.ts`, inside `interface Trade` (before the index signature at line 49), add:

```ts
  stop_loss?: number
```

- [ ] **Step 2: Create `HistoricalTradesTable.tsx`**

```tsx
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { positionsApi } from '../../lib/api/statusApi'
import type { Trade } from '../../types/api'
import './HistoricalTradesTable.css'

type SortKey = 'symbol' | 'strategy' | 'exit_reason' | 'pnl' | 'pnl_pct' | 'r'
type SortDir = 'asc' | 'desc'

function rMultiple(t: Trade): number | null {
  const { entry_price: entry, exit_price: exit, stop_loss: stop, direction } = t
  if (entry == null || exit == null || stop == null) return null
  const risk = Math.abs(entry - stop)
  if (risk === 0) return null
  const dir = (direction ?? '').toUpperCase()
  const raw = dir === 'SELL' || dir === 'SHORT' ? entry - exit : exit - entry
  return raw / risk
}

export function HistoricalTradesTable() {
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['trades-all'],
    queryFn: positionsApi.getTradesAll,
    enabled: false, // click-to-fetch
  })
  const [q, setQ] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('pnl')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const rows = useMemo(() => {
    let out = (data ?? []).map((t) => ({ ...t, _r: rMultiple(t) }))
    const needle = q.trim().toLowerCase()
    if (needle) {
      out = out.filter((t) =>
        [t.symbol, t.strategy, t.exit_reason].some((v) => (v ?? '').toLowerCase().includes(needle)),
      )
    }
    out.sort((a, b) => {
      const av = sortKey === 'r' ? (a._r ?? -Infinity) : (a[sortKey] as number | string | undefined)
      const bv = sortKey === 'r' ? (b._r ?? -Infinity) : (b[sortKey] as number | string | undefined)
      let cmp: number
      if (typeof av === 'number' || typeof bv === 'number') cmp = ((av as number) ?? -Infinity) - ((bv as number) ?? -Infinity)
      else cmp = String(av ?? '').localeCompare(String(bv ?? ''))
      return sortDir === 'asc' ? cmp : -cmp
    })
    return out
  }, [data, q, sortKey, sortDir])

  const toggleSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(k); setSortDir('desc') }
  }
  const arrow = (k: SortKey) => (k === sortKey ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '')

  return (
    <Panel
      title="Historical Trades"
      padded={false}
      actions={
        <>
          <input className="mq-hist-search" placeholder="Search symbol / strategy / reason" value={q} onChange={(e) => setQ(e.target.value)} />
          <Button variant="primary" onClick={() => refetch()} disabled={isFetching}>{isFetching ? 'Loading…' : data ? 'Reload' : 'Load All'}</Button>
          <a className="mq-btn mq-btn-ghost" href="/api/trades/export" download>Export CSV</a>
        </>
      }
    >
      {isError ? (
        <div className="mq-hist-empty text-loss">Failed to load trades.</div>
      ) : isLoading ? (
        <div className="mq-hist-empty text-faint">Loading…</div>
      ) : !data ? (
        <div className="mq-hist-empty text-faint">Click “Load All” to fetch the full trade history.</div>
      ) : rows.length === 0 ? (
        <div className="mq-hist-empty text-faint">No matching trades.</div>
      ) : (
        <table className="mq-hist-table">
          <thead>
            <tr>
              <th onClick={() => toggleSort('symbol')}>Symbol{arrow('symbol')}</th>
              <th onClick={() => toggleSort('strategy')}>Strategy{arrow('strategy')}</th>
              <th onClick={() => toggleSort('exit_reason')}>Exit Reason{arrow('exit_reason')}</th>
              <th onClick={() => toggleSort('pnl')}>P&L{arrow('pnl')}</th>
              <th onClick={() => toggleSort('pnl_pct')}>P&L %{arrow('pnl_pct')}</th>
              <th onClick={() => toggleSort('r')}>R{arrow('r')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t, i) => {
              const pnl = t.pnl ?? 0
              return (
                <tr key={i}>
                  <td className="mq-hist-sym">{t.symbol}</td>
                  <td>{t.strategy ?? '—'}</td>
                  <td className="text-dim">{t.exit_reason ?? '—'}</td>
                  <td className={`num ${pnl >= 0 ? 'text-profit' : 'text-loss'}`}>{pnl >= 0 ? '+' : ''}₹{pnl.toFixed(2)}</td>
                  <td className={`num ${(t.pnl_pct ?? 0) >= 0 ? 'text-profit' : 'text-loss'}`}>{t.pnl_pct != null ? `${t.pnl_pct.toFixed(2)}%` : '—'}</td>
                  <td className={`num ${(t._r ?? 0) >= 0 ? 'text-profit' : 'text-loss'}`}>{t._r != null ? `${t._r.toFixed(2)}R` : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </Panel>
  )
}
```

- [ ] **Step 3: Create `HistoricalTradesTable.css`**

```css
.mq-hist-search {
  background: rgba(255,255,255,0.04); border: 1px solid var(--border); color: var(--ink);
  font-family: var(--font-ui); font-size: 0.74rem; padding: 6px 10px; border-radius: var(--r-md); min-width: 220px;
}
.mq-hist-search:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-dim); }
.mq-hist-empty { padding: var(--space-5); text-align: center; }
.mq-hist-table { width: 100%; border-collapse: collapse; font-size: 0.76rem; }
.mq-hist-table th { text-align: left; font-family: var(--font-head); font-weight: 600; color: var(--ink-dim); padding: 8px var(--space-3); border-bottom: 1px solid var(--border); cursor: pointer; white-space: nowrap; user-select: none; }
.mq-hist-table th:hover { color: var(--accent); }
.mq-hist-table td { padding: 7px var(--space-3); border-bottom: 1px solid rgba(255,255,255,0.04); }
.mq-hist-sym { font-family: var(--font-mono); font-weight: 600; }
```

- [ ] **Step 4: Mount in `CockpitTab.tsx`**

In `frontend/src/features/cockpit/CockpitTab.tsx`, add the import (after line 9): `import { HistoricalTradesTable } from './HistoricalTradesTable'`. Then add it after `<ClosedTradesTable />` (line 37):

```tsx
      <ClosedTradesTable />
      <HistoricalTradesTable />
```

- [ ] **Step 5: Build + visual checkpoint**

Run: `npm run build` — PASS. `npm run dev`: a "Historical Trades" panel appears below today's closed trades; "Load All" fetches `/api/trades/all`; search filters; column headers sort; PnL/PnL%/R render with neon coloring; "Export CSV" downloads `/api/trades/export`.

---

## Task 10: RL Agent State Visualizer

**Files:**
- Create: `frontend/src/features/research-lab/RlAgentState.tsx`, `RlAgentState.css`.
- Modify: `frontend/src/features/research-lab/ResearchLabTab.tsx` (add subtab).

**Interfaces:**
- Consumes: `researchApi.getBriefing()` (`paper_trades`, `paper_win_rate`, `paper_pnl`), `researchApi.getSummary()` (`papertrading`, `validation`, `approved`, `live_candidates`), `systemApi.getLlmStatus()` (`calls_today`). All already exist.

- [ ] **Step 1: Create `RlAgentState.tsx`**

The spec's `paper_trade_logs` maps to briefing `paper_trades`; `learning_events` maps to the research summary's in-flight counts (validation + papertrading) as the closest real signal; validator approval maps to summary `approved` / `live_candidates`. All fields real; absent → `—`.

```tsx
import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { StatCard } from '../../design-system/StatCard'
import { Badge } from '../../design-system/Badge'
import { researchApi } from '../../lib/api/researchApi'
import { systemApi } from '../../lib/api/systemApi'
import './RlAgentState.css'

export function RlAgentState() {
  const { data: briefing } = useQuery({ queryKey: ['research-briefing'], queryFn: researchApi.getBriefing, refetchInterval: 10000 })
  const { data: summary } = useQuery({ queryKey: ['research-summary'], queryFn: researchApi.getSummary, refetchInterval: 10000 })
  const { data: llm } = useQuery({ queryKey: ['llm-status'], queryFn: systemApi.getLlmStatus, refetchInterval: 30000 })

  const paperTrades = briefing?.paper_trades
  const paperWr = briefing?.paper_win_rate
  const paperPnl = briefing?.paper_pnl
  const learningEvents = summary ? (summary.validation ?? 0) + (summary.papertrading ?? 0) : undefined
  const approved = summary?.approved ?? 0
  const liveCandidates = summary?.live_candidates ?? 0
  const validatorTone = approved > 0 ? 'profit' : liveCandidates > 0 ? 'warn' : 'neutral'
  const validatorText = approved > 0 ? `${approved} approved` : liveCandidates > 0 ? `${liveCandidates} pending` : 'none'

  return (
    <Panel title="RL Agent · Policy State" icon={<span className="led led-cyan led-pulse" />}>
      <div className="mq-rl-grid">
        <StatCard label="Paper Trade Logs" tone="accent" value={paperTrades != null ? paperTrades : '—'} sub={paperWr != null ? `${paperWr.toFixed(0)}% win rate` : undefined} />
        <StatCard label="Paper P&L" tone={(paperPnl ?? 0) >= 0 ? 'profit' : 'loss'} value={paperPnl != null ? `${paperPnl >= 0 ? '+' : ''}₹${paperPnl.toFixed(0)}` : '—'} />
        <StatCard label="Learning Events" tone="accent" value={learningEvents != null ? learningEvents : '—'} sub="validating + paper-trading" />
        <StatCard label="LLM Calls Today" value={llm ? `${llm.calls_today}/${llm.daily_cap}` : '—'} sub={llm?.enabled ? 'engine on' : 'engine off'} />
      </div>
      <div className="mq-rl-validator">
        <span className="mq-rl-validator-label">Out-of-sample validator</span>
        <Badge tone={validatorTone}>{validatorText}</Badge>
      </div>
    </Panel>
  )
}
```

- [ ] **Step 2: Create `RlAgentState.css`**

```css
.mq-rl-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: var(--space-3); }
.mq-rl-validator { display: flex; align-items: center; gap: var(--space-3); margin-top: var(--space-4); padding-top: var(--space-3); border-top: 1px solid var(--border); }
.mq-rl-validator-label { font-family: var(--font-head); font-size: 0.72rem; color: var(--ink-dim); }
```

- [ ] **Step 3: Add the RL subtab to `ResearchLabTab.tsx`**

In `frontend/src/features/research-lab/ResearchLabTab.tsx`: import (`import { RlAgentState } from './RlAgentState'`); add `'rl'` to the `SubTab` union (line 11); add `{ id: 'rl', label: 'RL Agent State' }` to `SUB_TABS` (after the `laneb` entry, line 20); add the render branch after the laneb line (line 42): `{sub === 'rl' && <RlAgentState />}`.

- [ ] **Step 4: Build + visual checkpoint**

Run: `npm run build` — PASS. `npm run dev` → AI Research Lab tab → "RL Agent State" subtab: shows paper-trade-log count, paper P&L, learning-events count, LLM calls, and the validator approval badge (real values, `—` where absent).

---

## Task 11: Final full-app verification

**Files:** none (verification only).

- [ ] **Step 1: Clean production build**

Run: `cd d:\coarse\upstox_Redign\frontend && npm run build`
Expected: `tsc -b` + `vite build` succeed with zero errors; output written to `../static_new/`.

- [ ] **Step 2: Backend suite still green**

Run: `cd d:\coarse\upstox_Redign && python -m pytest -q`
Expected: baseline pass count (179), zero new failures.

- [ ] **Step 3: Visual walkthrough (`npm run dev`)**

Confirm end-to-end against the backend:
- Neon palette + glass everywhere; live-mode crimson pulse vs paper-mode cyan glow on mode indicators.
- Header: CIPHER · TERMINAL wordmark, telemetry LEDs (WS/API/mode/BOT/last-loop/last-checked), pulsing Kill Switch (POSTs `/api/kill-switch` on confirm).
- Cockpit: daily-loss ring (∞ in paper, % in live); scanner confluence matrix with EMA/VWAP/ORB cells + confluence chip + why-skipped tooltips + VIX badge; historical trades table load/search/sort/CSV.
- Research Lab: RL Agent State subtab populated.
- Toggle OS reduced-motion and confirm pulses/animations stop.

- [ ] **Step 4: Confirm no writes to live `static/`**

Verify the build landed in `../static_new/` and the live `static/` directory was not modified.

---

## Self-Review Notes

- **Spec coverage:** §2 visual system → Tasks 2-3; §2A header/controls (mode card, telemetry, loss ring, kill switch) → Tasks 4-7; §2B positions/history (active grid already exists; historical table) → Task 9; §2C scanner heatmap/confluence + why-skipped → Task 1 (data) + Task 8; §2D research lab (leaderboard/proposals already exist; RL visualizer) → Task 10; §2E analytics suite → already implemented, receives theme cascade (no task needed); §3 technical (structure, lightweight-charts, no placeholders, currency) → honored in Global Constraints.
- **Deviations from the design doc (corrections found during file reading):** `statusApi.killSwitch()` and `positionsApi.getTradesAll()` already exist — Tasks 5 and 9 are UI-only (no new API functions), superseding the design doc's §5.1/§6 "add systemApi.killSwitch()". Confluence `n/N` is frontend-derived from real indicators emitted by the Task 1 backend add (per the approved "surgical backend add" decision).
- **Placeholder scan:** none — every code step contains complete content.
- **Type consistency:** `confluenceScore`/`rMultiple`/`statusTone` defined where used; `ScannerRow`, `Trade`, `BotStatus` field additions in Task 6/8/9 match their consumers; `Button` `'kill'` variant added in Task 3 before use in Task 5.
