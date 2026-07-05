# Session Ribbon + Live Cockpit — "The Trading Day, Alive"

**Date:** 2026-07-05 · **Brief:** "use all imagination — most attractive, engaging, informative,
interesting; do whatever you want" (Nikhil). Frontend-only; identity stays Neon Cyber Terminal
(tokens.css is untouched as the single source of truth).

## Design thesis

An intraday bot's whole existence happens inside one window: 09:15–15:30 IST. The signature
element renders that truth — everything else is quieter support that makes live change *felt*
(movement, notifications, session stats) without decorating.

## Signature: the Session Ribbon (`app/SessionRibbon.tsx`)

A slim strip under the top nav, visible on every tab: the trading day as a physical track
(09:00→15:30) with the bot's own zones drawn to scale from `/api/status` config —
pre-open (amber), warm-up, **entry window** (cyan), manage-only (amber), square-off (crimson) —
a glowing now-marker, the current phase pulsing with an LED, and a countdown to the next
boundary. Outside market hours: "MARKET CLOSED · market open in 1d 21h". Weekends handled;
NSE holidays deliberately not modelled (dependency-free; a holiday shows as a quiet open day).

Session math lives in pure `lib/marketSession.ts` (IST-computed via Intl regardless of the
viewer's clock). Boundary-verified: closed→preopen 09:00, warmup 09:15, entry at
`trade_start_time`, manage at `trade_end_time`, squareoff at `square_off_time`, closed 15:30,
weekend countdowns land on Monday 09:15.

## Supporting cast

- **Daily P&L card, alive** (`EngineStatusStrip`): count-up tween on change (`lib/useCountUp`,
  reduced-motion jumps instantly) + a session sparkline with zero baseline
  (`design-system/Sparkline`) fed by `lib/stores/usePnlHistoryStore` — every WS
  `realtime_update`/`state_update`/poll pushes the running P&L (dedup on value, cap 1200 pts,
  in-memory per session).
- **Open Risk card**: Σ|entry−SL|×qty ("if every stop hits") + deployed notional — the
  capital-protection pillar made glanceable.
- **Trade-event toasts** (`app/ToastLayer` + `lib/stores/useToastStore`): the fx layer the
  codebase reserved but never built. Entry = cyan ("ENTRY · SYMBOL LONG · qty @ price · SL · T1
  · strategy"), exit = green/red ("EXIT · SYMBOL +₹pnl · qty @ price · reason"). SHADOW events
  tagged and dimmed. Max 4 stacked, 7 s auto-dismiss, hover pauses, `aria-live="polite"`.
- **Closed-trades day summary** (`DaySummary` in `ClosedTradesTable`): Net · W–L · Win rate ·
  Profit factor · Avg R · Best · Worst — shadow trades excluded from every stat, dimmed in rows
  with an "S" tag; faint green/red row wash.
- **Empty states direct instead of shrug** ("The scanner is hunting — entries land here the
  moment a signal clears every gate.").

## Restraint

Cut during design: radar-sweep empty-state animation, sounds, command palette, new 3D scenes.
One bold element (the ribbon); the rest follows existing tokens/typography. All new animation
sits under `prefers-reduced-motion` guards.

## Verification

- `npm run build` + `oxlint` clean; no backend changes.
- Live against the running bot (Sunday): ribbon shows MARKET CLOSED with correct 23h54m
  countdown to Monday 09:15; strip renders new cards; empty states render.
- `marketSession` compiled standalone and boundary-tested across 12 cases (all correct).
- Not yet observable live (no market): toasts, sparkline movement, day summary with real fills —
  first real session will exercise them; logic is typed, lint-clean, and store-driven.
