# Realistic Paper Fills + Intraday Transaction Costs — plan (2026-07-08)

**Goal:** Make paper P&L reflect reality, so the 3-week experiment (and any future backtester)
measures real edge instead of a cost-free fantasy. Two parts: (a) realistic fill prices
(spread + slippage) for paper orders, (b) round-trip NSE intraday-equity transaction charges
(brokerage + STT + exchange + GST + SEBI + stamp) deducted from every closed trade's P&L.

**Why first:** paper fills at exact LTP with zero charges (upstox_client.py:507; execute_exit
subtracts nothing). A ₹50k position carries ~₹65 round-trip; fixed ₹20/leg brokerage turns
small "winners" into losers. Without this, no result here can be trusted.

## Global Constraints
- New module `execution_costs.py` = pure, unit-tested functions. No new deps.
- Config-toggleable (`enable_realistic_costs`, default True) + tunable params.
- Charges apply in paper AND live (charges are real in both); fill slippage is paper-only
  simulation (live gets real fills).
- Full `pytest -q` + `ruff check .` stay green. Commit per task.

---

### Task 1: execution_costs.py (TDD)
**Files:** Create `execution_costs.py`, `test_execution_costs.py`.

**Interfaces:**
- `apply_fill_slippage(ltp, transaction_type, *, spread_bps=3.0, slippage_bps=2.0) -> float`
- `intraday_equity_charges(buy_value, sell_value, *, brokerage_per_order=20.0, stt_pct=0.00025, exchange_txn_pct=0.0000297, gst_pct=0.18, sebi_per_crore=10.0, stamp_pct=0.00003) -> dict` (keys: brokerage, stt, exchange, gst, sebi, stamp, total)

Tests: BUY lifts price / SELL drops it by (half-spread+slippage) bps; charges match hand-computed
values for a ₹50k round trip (~₹65) and show fixed-brokerage domination on a ₹5k trade; zero
values safe.

Model (NSE intraday equity):
- Brokerage per leg = min(brokerage_per_order, 0.025 * leg_value); round trip = buy leg + sell leg.
- STT = stt_pct * sell_value (sell side only).
- Exchange txn = exchange_txn_pct * (buy_value + sell_value).
- GST = gst_pct * (brokerage + exchange txn).
- SEBI = sebi_per_crore / 1e7 * (buy_value + sell_value).
- Stamp = stamp_pct * buy_value (buy side only).

### Task 2: wire slippage into UpstoxClient.place_order paper branch
After `fill_price = quote["ltp"] ...` (upstox_client.py:507), if `self.config.get("enable_realistic_costs", True)`
and not an SL order, `fill_price = execution_costs.apply_fill_slippage(fill_price, transaction_type, spread_bps=..., slippage_bps=...)`.

### Task 3: wire charges into execute_exit
After pnl computed (main.py:2846-2849), if `enable_realistic_costs`: derive buy/sell value from
direction, `ch = execution_costs.intraday_equity_charges(...); pnl -= ch["total"]`; add
`"charges": round(ch["total"], 2)` to the trade record. Log the charge on the close line.

### Task 4: config keys + verification + deploy
Add keys to config.json + `update_settings` allowed_keys: enable_realistic_costs, spread_bps,
slippage_bps, brokerage_per_order, stt_pct, exchange_txn_pct, gst_pct, sebi_per_crore, stamp_pct.
Full pytest + ruff green. Deploy via watchdog reload; verify a live paper close shows a non-zero
charge and a slipped fill.
