# Trade Detail UI — Closed-Trade Modal + Full-Detail Position Cards

**Date:** 2026-07-05 · **Approved by:** Nikhil (option selections via question flow)

## Goal

The backend records ~25 fields per trade/position; the cockpit shows ~8. Surface *everything*:

1. **Closed Trades:** click any row → centered modal with every recorded field (approved over
   expandable row / slide-in drawer).
2. **Active Positions:** cards show every field — T1/T2/SL, entry vs live price, invested vs
   current value, live P&L ₹+%, holding time, context — with BUY/long green, SELL/short red.
3. **Selected extras:** SL→T1→T2 price bar on cards, live tick flash, sort+filter on the
   closed-trades table, R-multiple column, CSV export. (Broker-positions panel: not selected.)

## Bugs fixed as part of this work

- Frontend reads `t.exit_reason`; backend trade records store `reason`
  (`main.py` `execute_exit` record) → Reason column always "—". Fix: read `exit_reason ?? reason`.
- `ActivePositionsGrid` colors direction by `=== 'BUY'` but backend sends `LONG`/`SHORT` →
  every badge rendered red. Fix: long-ness helper accepting BUY/LONG vs SELL/SHORT.
- Backend CSV export (`/api/trades/export`) also reads `exit_reason` → blank column.
  One-line fix: fall back to `reason`.
- `pnl_pct` is never stored → computed client-side from `pnl / (entry_price × quantity)`.

## Design

### Design system: `Modal.tsx` (+ CSS)

Portal to `document.body`; dark blurred backdrop; centered `mq-panel`-styled dialog.
`role="dialog"` `aria-modal`, Esc + backdrop-click close, focus moves in on open and returns on
close. No new dependencies (no Tailwind/Radix — shadcn used as anatomy reference only, since
this design system is hand-rolled).

### `TradeDetailModal.tsx` (features/cockpit)

Takes a `Trade`, renders sections; every value falls back to "—" when absent:

- **Header:** symbol, direction badge (green/red), strategy, F&O contract, SHADOW badge.
- **Hero:** net P&L ₹ (large, colored), P&L %, R-multiple, invested (entry×qty),
  returned (exit×qty).
- **Execution:** entry/exit price & time, quantity, holding duration, exit reason, order tags.
- **Risk:** stop loss, ATR at entry, MAE, MFE, risk per share, total risked.
- **Signal context:** regime, HTF trend, confluence score, trigger level source/price/score.
- **Market context:** all keys of `market_context` rendered generically.
- **Raw fields:** every remaining key on the trade object not shown above, rendered
  key→value. Guarantees future backend fields can never be hidden.

Shared math (`lib/tradeMath.ts`): `isLongDirection`, `rMultiple`, `pnlPct`, `invested`,
duration/date formatters. `HistoricalTradesTable`'s local `rMultiple` moves here.

### `ClosedTradesTable` rework

Sortable headers (same pattern/classes as `HistoricalTradesTable`), search filter,
columns: Symbol · Strategy · Dir (colored) · Qty · Entry · Exit · P&L · P&L% · R · Exit time ·
Reason. Rows clickable → `TradeDetailModal`. CSV export button: client-side blob built from the
union of all keys across today's trade objects (complete, unlike the visible columns).
`HistoricalTradesTable` rows also open the modal; its reason/pnl% reads get the fallbacks.

### `ActivePositionsGrid` rework

Card layout (top → bottom):
- Header: symbol, direction badge (profit/loss tone), strategy badge; card border tinted by side.
- Live P&L ₹ (large) + P&L % — flash green/red on tick up/down (state keyed on
  `current_price` changes, ~600 ms CSS animation, disabled under `prefers-reduced-motion`).
- Price bar: linear scale over [SL, entry, T1, T2, live]; entry tick, SL/T1/T2 markers,
  live-price thumb; red span toward SL, green toward targets (mirrored for shorts).
- Stat grid: Entry / Live / Qty / Invested (entry×qty) / Current value (live×qty) / SL / T1
  (+ "T1 ✓" once `t1_hit`) / T2 / trailing high-low / ATR / MAE / MFE / confluence / regime /
  HTF trend / entry time + holding duration.
- Existing Close button + tilt kept.

### Types (`types/api.ts`)

`direction` widened to `string` (backend sends LONG/SHORT; manual path may send BUY/SELL).
Add explicit optional fields observed in `main.py`: Position `target_2, t1_hit, entry_time,
atr_at_entry, trailing_high, trailing_low, order_id, is_fno, contract, lot_size, market_context,
is_shadow`; Trade `reason, holding_minutes, mae, mfe, confluence_score, regime, htf_trend,
market_context, is_fno, contract, atr_at_entry, trigger_level_*, is_shadow_trade`.

## Not in scope

Broker-side positions panel, trade-event toasts, win/loss row tinting (not selected);
any trading-logic change; backend changes beyond the one-line CSV fallback.

## Testing / verification

`npm run build` (tsc + vite → `static/`), `oxlint`, `python -m pytest -q` (backend line
touched), then live check: run `python main.py`, open dashboard, load Historical trades,
click a real trade → modal shows all fields.
