# Depth-Snapshot Recorder — Design

**Date:** 2026-07-13
**Status:** Approved (design), pending implementation plan
**Branch:** self-improve

## Problem

The Upstox `market-quote/quotes` endpoint returns full 5-level order-book depth plus
`total_buy_quantity` / `total_sell_quantity` (TBQ/TSQ), `oi`, and `average_price` (ATP)
on every quote. The bot currently **discards** almost all of it: `get_market_quotes`
collapses depth to top-of-book via `microstructure.normalize_depth` and drops TBQ/TSQ/OI/ATP.

Critically, **Upstox provides no historical order-book depth** — depth is live-only. The
existing microstructure/liquidity gate (`microstructure.py`) and the fill/slippage model
(`execution_costs.py`) therefore:

1. Can never be **backtested** — there is no historical depth to replay.
2. Run on **guessed constants** (`spread_bps: 3.0`, `slippage_bps: 2.0` in config) that
   have never been validated against real observed spreads.

The only fix is to **record live depth to disk going forward** and build our own
backtestable microstructure dataset. Every market day not recorded is data that can
never be recovered.

## Goal

A self-contained background recorder that captures full-fidelity order-book snapshots for
the watchlist during market hours and appends them to disk. Reliable, isolated, and
incapable of affecting the trading path.

**In scope:** capture and store raw depth snapshots.
**Out of scope (YAGNI):** computing imbalance signals, changing any strategy, or altering
the fill model. Consuming the recorded data is a separate later project.

## Approach

A **dedicated daemon thread** that fetches all watchlist quotes on a fixed cadence,
gates on market hours, and appends rows. Chosen over piggybacking on the scan loop
because it produces a **regularly-sampled** time series (better for later
backtesting/learning) and stays fully isolated from the hot quote path.

Honest cost note: this is **not** zero extra API calls — it issues ~1 batched call/sec
(one call covers all ~50 watchlist symbols), roughly 10% of the 10 calls/sec rate limit.
Negligible, and it works regardless of whether the market feed or scan loop is running.

## Architecture

### New module: `depth_recorder.py`

`DepthRecorder(client, config)` — one daemon thread, one responsibility (fetch → gate →
serialize → append). No coupling to `market_feed` or the scan loop.

Loop:
```
while running:
    if not market_hours_now(now(), config):
        sleep(check_interval); continue
    keys = watchlist instrument_keys
    raw  = client.fetch_raw_quotes(keys)          # new client method
    rows = [build_row(key, q, ts) for key, q in raw.items()]
    writer.append(rows)                            # gzip JSONL, daily-rotated
    sleep(interval)
```

Lifecycle: `start()` spawns the daemon thread; `stop()` sets the flag and lets it drain.
Every network/parse error inside the loop is caught and logged; the loop continues.

### New client method: `UpstoxClient.fetch_raw_quotes(keys)`

Returns the **raw per-instrument-key Upstox quote dict** (all 5 depth levels + every
field), reusing the existing batch request and `instrument_token` matching logic from
`get_market_quotes`. Returns `{}` on failure. `get_market_quotes` is left untouched so
existing consumers are unaffected.

### Pure functions (testable core, in `depth_recorder.py`)

- `market_hours_now(now, config) -> bool`
  True only on weekdays within the **full NSE session**, using recorder-specific bounds
  `depth_recorder_start` (default `"09:15"`) and `depth_recorder_end` (default `"15:30"`).
  These are intentionally **independent of the bot's trade window** (`trade_start_time`
  `09:30` / `square_off_time` `15:10`) — the volatile open and the post-square-off close
  are exactly the microstructure we want to capture. Times are IST; `now` is passed in
  for testability.

- `build_row(instrument_key, raw_quote, ts) -> dict`
  Flattens one quote to a single JSON-serializable row:
  ```
  {
    "ts": <iso8601>,
    "key": <instrument_key>,
    "ltp": float, "atp": float|None, "volume": int,
    "oi": float|None, "tbq": int|None, "tsq": int|None,
    "bid": [{"p":float,"q":int,"o":int}, ... up to 5],
    "ask": [{"p":float,"q":int,"o":int}, ... up to 5]
  }
  ```
  Missing/partial/crossed depth still yields a row (with empty lists / nulls) — the
  recorder never crashes on bad data.

### Storage: `DepthWriter`

Append-only **gzip JSONL**, one file per calendar day:
`data/depth/YYYY-MM-DD.jsonl.gz`. One row per symbol per snapshot. Rotates when the
date changes (reopens a new gzip handle). `data/depth/` is gitignored.

### Wiring in `main.py`

In the startup block alongside the market-feed init (~line 178): if
`enable_depth_recorder` is set, construct `DepthRecorder(client, config)` and `.start()`
it; `.stop()` on app shutdown. Fully guarded in try/except so a recorder failure can
never affect app startup or trading.

## Config (new keys)

| Key | Default (template) | Notes |
|-----|--------------------|-------|
| `enable_depth_recorder` | `false` | Set `true` in the live `config.json` |
| `depth_recorder_interval` | `1.0` | Seconds between snapshots |
| `depth_recorder_symbols` | `"watchlist"` | Symbol source (only "watchlist" supported now) |
| `depth_recorder_start` | `"09:15"` | Session start (IST), full NSE open |
| `depth_recorder_end` | `"15:30"` | Session end (IST), full NSE close |

## Error handling & safety

- Recorder is a strictly passive observer: no order path, no shared mutable state with
  the bot, no writes outside `data/depth/`.
- All exceptions in the loop are caught and logged; the thread survives transient API
  failures and resumes on the next tick.
- Recorder construction/start is wrapped so it can never break app startup.

## Testing (`test_depth_recorder.py`)

Unit tests on the pure core, no live API:

- `market_hours_now`: inside hours, before open, after close, weekend.
- `build_row`: full 5-level depth; missing depth; crossed/empty book; missing
  TBQ/TSQ/OI/ATP fields.
- `DepthWriter`: appends rows to today's gzip file; rotates to a new file on date change;
  written lines round-trip through `json.loads`.
- `DepthRecorder` loop (one tick) against a fake client returning canned raw quotes:
  verifies rows are written when in-hours and skipped when out-of-hours.

## Storage sizing

~50 symbols × 5-level depth ≈ a few hundred bytes/row. At 1 snapshot/sec over a 6.25h
session ≈ ~1.1M rows/day, ~50–80 MB/day gzipped, ~1–1.5 GB per trading month. Trivial.
