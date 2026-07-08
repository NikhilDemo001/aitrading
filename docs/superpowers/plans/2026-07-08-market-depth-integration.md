# Market Depth / Order-Book Integration — plan (2026-07-08)

**Goal:** Use the 5-level order book (bid/ask depth) the bot already receives but discards, to
(1) gate out illiquid / wide-spread names before entry, and (2) drive the paper slippage model
from the *real* observed spread instead of a fixed guess. This is the #1 missing essential
intraday input (market microstructure).

**Feasibility (verified):** both `get_market_quote` and `get_market_quotes` hit Upstox v2
`market-quote/quotes` (the FULL quote), whose response already contains `depth: {buy:[...],
sell:[...]}`. The code parses only ltp/ohlc/volume (upstox_client.py:483). So depth is free —
zero new API calls.

## Global Constraints
- New module `microstructure.py` = pure, unit-tested functions. No new deps.
- Config-toggleable (`enable_liquidity_gate`, default True) + tunable (`max_spread_bps`,
  `min_depth_ratio`). Data-driven slippage reuses `enable_realistic_costs`.
- Fail-open: no depth (mock broker / API omit) → gate ALLOWS; slippage falls back to fixed bps.
- Full `pytest -q` + `ruff check .` stay green. Commit per task.

---

### Task 1: microstructure.py (TDD)
**Files:** Create `microstructure.py`, `test_microstructure.py`.
**Interfaces:**
- `normalize_depth(raw_depth) -> dict|None` (keys: best_bid, best_ask, bid_qty, ask_qty, mid, spread)
- `spread_bps(best_bid, best_ask) -> float|None`
- `liquidity_ok(book, order_qty=None, *, max_spread_bps=50.0, min_depth_ratio=0.5) -> (bool, str)`

Model: reject if `spread_bps > max_spread_bps`, or (when order_qty given) top-of-book
`min(bid_qty, ask_qty) < min_depth_ratio * order_qty`. `book=None` → allow (fail-open).
Tests: tight vs wide spread; missing/empty depth → None/allow; crossed/zero book → None;
order-size-vs-depth pass/fail.

### Task 2: parse depth in upstox_client
In both `get_market_quote` (line 448) and `get_market_quotes` (line 483) returned dicts, add
`"depth": microstructure.normalize_depth(quote.get("depth"))`. `import microstructure` at top.

### Task 3: entry liquidity/spread gate
At the M4 fresh-quote block (main.py:1616, inside `if fresh_quote:`), after the drift check add:
```python
if client.config.get("enable_liquidity_gate", True):
    ok, why = microstructure.liquidity_ok(
        fresh_quote.get("depth"),
        max_spread_bps=float(client.config.get("max_spread_bps", 50)),
        min_depth_ratio=float(client.config.get("min_depth_ratio", 0.5)))
    if not ok:
        log_scan(symbol, f"Liquidity gate: {why} — skipped.", "warning")
        _matrix_set(symbol, f"illiquid: {why}", "filtered", candles_5m, strategy=signal.get("strategy"))
        signals_filtered += 1
        continue
```

### Task 4: data-driven slippage
`execution_costs.apply_fill_slippage` gains `real_spread_bps=None`; when provided & >0 it
replaces the config `spread_bps`. In `upstox_client.place_order` paper branch, compute real
spread from the fetched quote's depth and pass it:
```python
_book = quote.get("depth") if quote else None
_rsb = microstructure.spread_bps(_book["best_bid"], _book["best_ask"]) if _book else None
fill_price = execution_costs.apply_fill_slippage(fill_price, transaction_type,
    spread_bps=..., slippage_bps=..., real_spread_bps=_rsb)
```

### Task 5: config + verify + deploy
Add `enable_liquidity_gate`, `max_spread_bps` (50), `min_depth_ratio` (0.5) to config.json +
`update_settings` allowed_keys. Full pytest + ruff green. Deploy via watchdog; verify a live
quote now carries depth (best_bid/best_ask) and the gate logs on a wide-spread name.
