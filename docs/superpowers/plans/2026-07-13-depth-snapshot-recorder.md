# Depth-Snapshot Recorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record full 5-level order-book depth (+ TBQ/TSQ/OI/ATP) for the watchlist during the full NSE session to disk, building a backtestable microstructure dataset.

**Architecture:** A dedicated daemon thread (`DepthRecorder`) fetches all watchlist quotes on a fixed cadence via a new raw-quote client method, gates on market hours, flattens each quote to a row, and appends to a daily-rotated gzip JSONL file. Fully isolated from the trading path — a passive observer that can never affect orders.

**Tech Stack:** Python 3.14, `requests` (existing session), `gzip`/`json` stdlib, `threading`, pytest.

## Global Constraints

- Python 3.14, Windows 11. Tests run via `python -m pytest -q`.
- Test files live at repo root, named `test_*.py`, with a `if __name__ == "__main__": sys.exit(pytest.main([__file__, "-q"]))` runner block (match `test_microstructure.py`).
- Recorder is a **strictly passive observer**: no order path, no shared mutable state with the bot, no file writes outside `data/depth/`.
- `data/` is already gitignored — recorded files must NOT be committed.
- All loop-level exceptions are caught and logged; the recorder thread must survive transient API failures.
- Do NOT modify `get_market_quotes` — add a sibling method so existing consumers are untouched.

---

### Task 1: `fetch_raw_quotes` client method

Adds a raw batch-quote fetch that preserves full depth + all fields (unlike `get_market_quotes`, which normalizes depth to top-of-book and drops OI/TBQ/TSQ/ATP).

**Files:**
- Modify: `upstox_client.py` (add method after `get_market_quotes`, ~line 497)
- Test: `test_depth_recorder.py` (create)

**Interfaces:**
- Consumes: nothing new (reuses `self.session`, `self.access_token`, `self.get_headers`, `urllib.parse`).
- Produces: `UpstoxClient.fetch_raw_quotes(instrument_keys: list[str]) -> dict[str, dict]` — maps each instrument_key to its raw Upstox quote dict (full `depth`, `oi`, `total_buy_quantity`, `total_sell_quantity`, `average_price`, etc). Returns `{}` on failure/empty.

- [ ] **Step 1: Write the failing test**

Create `test_depth_recorder.py`:

```python
"""Unit tests for the depth-snapshot recorder + raw-quote client method."""

import json
import gzip
import types
import os
import time
from datetime import datetime


class _FakeResp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._p = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._p


def _client_with_response(payload, status=200):
    from upstox_client import UpstoxClient
    c = UpstoxClient.__new__(UpstoxClient)   # bypass __init__ (no config/network)
    c.access_token = "tok"
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        return _FakeResp(payload, status)

    c.session = types.SimpleNamespace(get=fake_get)
    return c


# ── fetch_raw_quotes ─────────────────────────────────────────────────────────────────────
def test_fetch_raw_quotes_matches_by_token_and_keeps_full_depth():
    payload = {"status": "success", "data": {
        "NSE_EQ:RELIANCE": {
            "instrument_token": "NSE_EQ|INE002A01018",
            "last_price": 1307.8,
            "average_price": 1306.0,
            "volume": 8412537,
            "oi": 0.0,
            "total_buy_quantity": 5000,
            "total_sell_quantity": 6000,
            "depth": {
                "buy": [{"price": 1307.8, "quantity": 100, "orders": 3},
                        {"price": 1307.7, "quantity": 200, "orders": 4}],
                "sell": [{"price": 1307.9, "quantity": 150, "orders": 2}],
            },
        }}}
    c = _client_with_response(payload)
    out = c.fetch_raw_quotes(["NSE_EQ|INE002A01018"])
    assert "NSE_EQ|INE002A01018" in out
    q = out["NSE_EQ|INE002A01018"]
    assert q["total_buy_quantity"] == 5000 and q["total_sell_quantity"] == 6000
    assert len(q["depth"]["buy"]) == 2                    # full depth retained
    assert q["depth"]["sell"][0]["quantity"] == 150


def test_fetch_raw_quotes_empty_on_no_token():
    from upstox_client import UpstoxClient
    c = UpstoxClient.__new__(UpstoxClient)
    c.access_token = None
    c.session = types.SimpleNamespace(get=lambda *a, **k: _FakeResp({}, 200))
    assert c.fetch_raw_quotes(["X"]) == {}
    assert c.fetch_raw_quotes([]) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_depth_recorder.py -v`
Expected: FAIL — `AttributeError: 'UpstoxClient' object has no attribute 'fetch_raw_quotes'`

- [ ] **Step 3: Write minimal implementation**

In `upstox_client.py`, immediately after the `get_market_quotes` method (before `place_order`, ~line 498), add:

```python
    def fetch_raw_quotes(self, instrument_keys):
        """Returns the RAW Upstox quote dict per instrument_key — full 5-level depth plus
        every field (oi, total_buy_quantity, total_sell_quantity, average_price). Unlike
        get_market_quotes, nothing is normalized or dropped. Returns {} on failure/empty.
        Used by the depth recorder to capture full-fidelity order-book snapshots."""
        if not self.access_token or not instrument_keys:
            return {}
        keys_str = ",".join(instrument_keys)
        url = f"https://api.upstox.com/v2/market-quote/quotes?instrument_key={urllib.parse.quote(keys_str)}"
        response = self.session.get(url, headers=self.get_headers(), timeout=10)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("status") == "success":
                data = res_json.get("data") or {}
                result = {}
                for key in instrument_keys:
                    quote = data.get(key)
                    if not quote:
                        for v in data.values():
                            if v.get("instrument_token") == key:
                                quote = v
                                break
                    if not quote and len(data) == 1:
                        quote = next(iter(data.values()))
                    if quote:
                        result[key] = quote
                return result
        print(f"Error fetching raw quotes: {response.text}")
        return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test_depth_recorder.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add upstox_client.py test_depth_recorder.py
git commit -m "feat: fetch_raw_quotes — full-fidelity batch quotes for depth recorder"
```

---

### Task 2: Pure functions — `market_hours_now` + `build_row`

The testable core of the recorder: session gating and row flattening. No I/O, no network.

**Files:**
- Create: `depth_recorder.py`
- Test: `test_depth_recorder.py` (append)

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces:
  - `market_hours_now(now: datetime, config: dict) -> bool` — True on weekdays within `[depth_recorder_start, depth_recorder_end]` (IST). `now` is naive local/IST, passed in for testability.
  - `build_row(instrument_key: str, raw_quote: dict | None, ts: str) -> dict` — flattens one raw quote to a JSON-serializable snapshot row with keys: `ts, key, ltp, atp, volume, oi, tbq, tsq, bid, ask` (bid/ask = lists of up to 5 `{p, q, o}` dicts). Never raises.

- [ ] **Step 1: Write the failing test**

Append to `test_depth_recorder.py`:

```python
# ── market_hours_now ─────────────────────────────────────────────────────────────────────
def _cfg(**over):
    base = {"depth_recorder_start": "09:15", "depth_recorder_end": "15:30",
            "watchlist": ["RELIANCE"]}
    base.update(over)
    return base


def test_market_hours_now_inside_session():
    from depth_recorder import market_hours_now
    # 2026-07-13 is a Monday
    assert market_hours_now(datetime(2026, 7, 13, 10, 30), _cfg()) is True


def test_market_hours_now_before_open_and_after_close():
    from depth_recorder import market_hours_now
    assert market_hours_now(datetime(2026, 7, 13, 9, 0), _cfg()) is False
    assert market_hours_now(datetime(2026, 7, 13, 15, 45), _cfg()) is False


def test_market_hours_now_weekend():
    from depth_recorder import market_hours_now
    # 2026-07-18 is a Saturday
    assert market_hours_now(datetime(2026, 7, 18, 11, 0), _cfg()) is False


# ── build_row ────────────────────────────────────────────────────────────────────────────
def test_build_row_full_depth():
    from depth_recorder import build_row
    q = {"last_price": 1307.8, "average_price": 1306.0, "volume": 500, "oi": 12.0,
         "total_buy_quantity": 5000, "total_sell_quantity": 6000,
         "depth": {"buy": [{"price": 1307.8, "quantity": 100, "orders": 3}],
                   "sell": [{"price": 1307.9, "quantity": 150, "orders": 2}]}}
    r = build_row("K", q, "2026-07-13T10:30:00")
    assert r["key"] == "K" and r["ltp"] == 1307.8 and r["atp"] == 1306.0
    assert r["tbq"] == 5000 and r["tsq"] == 6000 and r["oi"] == 12.0
    assert r["bid"] == [{"p": 1307.8, "q": 100, "o": 3}]
    assert r["ask"] == [{"p": 1307.9, "q": 150, "o": 2}]
    json.dumps(r)   # must be serializable


def test_build_row_missing_depth_and_fields():
    from depth_recorder import build_row
    r = build_row("K", {"last_price": 10.0}, "t")
    assert r["ltp"] == 10.0 and r["bid"] == [] and r["ask"] == []
    assert r["tbq"] is None and r["oi"] is None and r["atp"] is None
    r2 = build_row("K", None, "t")           # completely missing quote
    assert r2["key"] == "K" and r2["bid"] == [] and r2["ltp"] is None


def test_build_row_caps_at_five_levels():
    from depth_recorder import build_row
    buy = [{"price": i, "quantity": i, "orders": 1} for i in range(1, 9)]
    r = build_row("K", {"depth": {"buy": buy, "sell": []}}, "t")
    assert len(r["bid"]) == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_depth_recorder.py -k "market_hours or build_row" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'depth_recorder'`

- [ ] **Step 3: Write minimal implementation**

Create `depth_recorder.py`:

```python
"""depth_recorder.py — passive recorder of full 5-level order-book depth.

Captures the raw Upstox order book (+ TBQ/TSQ/OI/ATP) for the watchlist during the full
NSE session and appends it to daily-rotated gzip JSONL, building a backtestable
microstructure dataset. Upstox provides NO historical depth, so this is the only way to
get one. Strictly a passive observer — no order path, no shared state with the bot.

Design: docs/superpowers/specs/2026-07-13-depth-snapshot-recorder-design.md
"""

from __future__ import annotations

import os
import gzip
import json
import time
import threading
from datetime import datetime, time as dtime


def _parse_hhmm(value, default):
    try:
        hh, mm = str(value).split(":")
        return dtime(int(hh), int(mm))
    except Exception:
        h, m = default.split(":")
        return dtime(int(h), int(m))


def market_hours_now(now, config):
    """True on weekdays within [depth_recorder_start, depth_recorder_end] (IST).
    `now` is a naive datetime already in IST (passed in for testability)."""
    if now.weekday() >= 5:      # Saturday/Sunday
        return False
    start = _parse_hhmm(config.get("depth_recorder_start", "09:15"), "09:15")
    end = _parse_hhmm(config.get("depth_recorder_end", "15:30"), "15:30")
    return start <= now.time() <= end


def _levels(side):
    out = []
    for lvl in (side or [])[:5]:
        out.append({
            "p": float(lvl.get("price") or 0.0),
            "q": int(lvl.get("quantity") or 0),
            "o": int(lvl.get("orders") or 0),
        })
    return out


def build_row(instrument_key, raw_quote, ts):
    """Flatten one raw Upstox quote into a JSON-serializable snapshot row.
    Missing/partial fields degrade to nulls/empties — never raises."""
    q = raw_quote or {}
    depth = q.get("depth") or {}

    def _f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    def _i(x):
        try:
            return int(x)
        except (TypeError, ValueError):
            return None

    return {
        "ts": ts,
        "key": instrument_key,
        "ltp": _f(q.get("last_price")),
        "atp": _f(q.get("average_price")),
        "volume": _i(q.get("volume")) or 0,
        "oi": _f(q.get("oi")),
        "tbq": _i(q.get("total_buy_quantity")),
        "tsq": _i(q.get("total_sell_quantity")),
        "bid": _levels(depth.get("buy")),
        "ask": _levels(depth.get("sell")),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test_depth_recorder.py -k "market_hours or build_row" -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add depth_recorder.py test_depth_recorder.py
git commit -m "feat: depth_recorder pure core — market_hours_now + build_row"
```

---

### Task 3: `DepthWriter` — daily-rotated gzip JSONL

**Files:**
- Modify: `depth_recorder.py` (append class)
- Test: `test_depth_recorder.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `DepthWriter(base_dir="data/depth")` with `.append(rows: list[dict], day: str | None = None)` and `.close()`. Writes one JSON line per row to `<base_dir>/<day>.jsonl.gz`, reopening a new file when `day` changes. `day` defaults to today (`%Y-%m-%d`).

- [ ] **Step 1: Write the failing test**

Append to `test_depth_recorder.py`:

```python
# ── DepthWriter ──────────────────────────────────────────────────────────────────────────
def _read_gz_lines(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def test_depth_writer_appends_and_rotates(tmp_path):
    from depth_recorder import DepthWriter
    base = str(tmp_path / "depth")
    w = DepthWriter(base_dir=base)
    w.append([{"key": "A", "ltp": 1}, {"key": "B", "ltp": 2}], day="2026-07-13")
    w.append([{"key": "A", "ltp": 3}], day="2026-07-13")     # same day -> same file
    w.append([{"key": "A", "ltp": 4}], day="2026-07-14")     # new day -> new file
    w.close()

    d13 = _read_gz_lines(os.path.join(base, "2026-07-13.jsonl.gz"))
    d14 = _read_gz_lines(os.path.join(base, "2026-07-14.jsonl.gz"))
    assert [r["ltp"] for r in d13] == [1, 2, 3]
    assert [r["ltp"] for r in d14] == [4]


def test_depth_writer_empty_rows_noop(tmp_path):
    from depth_recorder import DepthWriter
    base = str(tmp_path / "depth")
    w = DepthWriter(base_dir=base)
    w.append([], day="2026-07-13")
    w.close()
    assert not os.path.exists(os.path.join(base, "2026-07-13.jsonl.gz"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_depth_recorder.py -k "depth_writer" -v`
Expected: FAIL — `ImportError: cannot import name 'DepthWriter'`

- [ ] **Step 3: Write minimal implementation**

Append to `depth_recorder.py`:

```python
class DepthWriter:
    """Append-only gzip JSONL writer, one file per calendar day:
    <base_dir>/YYYY-MM-DD.jsonl.gz. Reopens a new file when the day changes."""

    def __init__(self, base_dir="data/depth"):
        self.base_dir = base_dir
        self._date = None
        self._fh = None
        self._lock = threading.Lock()

    def _path_for(self, day):
        return os.path.join(self.base_dir, f"{day}.jsonl.gz")

    def _ensure_open(self, day):
        if self._date == day and self._fh is not None:
            return
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
        os.makedirs(self.base_dir, exist_ok=True)
        self._fh = gzip.open(self._path_for(day), "at", encoding="utf-8")
        self._date = day

    def append(self, rows, day=None):
        if not rows:
            return
        day = day or datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            self._ensure_open(day)
            for r in rows:
                self._fh.write(json.dumps(r, separators=(",", ":")) + "\n")
            self._fh.flush()

    def close(self):
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                finally:
                    self._fh = None
                    self._date = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test_depth_recorder.py -k "depth_writer" -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add depth_recorder.py test_depth_recorder.py
git commit -m "feat: DepthWriter — daily-rotated gzip JSONL sink"
```

---

### Task 4: `DepthRecorder` — the daemon-thread orchestrator

**Files:**
- Modify: `depth_recorder.py` (append class)
- Test: `test_depth_recorder.py` (append)

**Interfaces:**
- Consumes: `market_hours_now`, `build_row`, `DepthWriter` (Tasks 2-3); `client.get_instrument_info(sym)` and `client.fetch_raw_quotes(keys)` (Task 1).
- Produces: `DepthRecorder(client, config, writer=None, now_fn=None, sleep_fn=None)` with `.tick() -> int` (one capture cycle, returns rows written), `.start()`, `.stop()`. `.interval` attribute = float seconds.

- [ ] **Step 1: Write the failing test**

Append to `test_depth_recorder.py`:

```python
# ── DepthRecorder ────────────────────────────────────────────────────────────────────────
class _FakeClient:
    def __init__(self, keymap, quotes):
        self._keymap = keymap        # symbol -> instrument_key
        self._quotes = quotes        # instrument_key -> raw quote

    def get_instrument_info(self, sym):
        k = self._keymap.get(sym)
        return {"instrument_key": k} if k else None

    def fetch_raw_quotes(self, keys):
        return {k: self._quotes[k] for k in keys if k in self._quotes}


class _CapWriter:
    def __init__(self):
        self.rows = []

    def append(self, rows, day=None):
        self.rows.extend(rows)

    def close(self):
        pass


def test_recorder_tick_writes_rows_in_hours():
    from depth_recorder import DepthRecorder
    client = _FakeClient(
        {"RELIANCE": "NSE_EQ|R", "TCS": "NSE_EQ|T"},
        {"NSE_EQ|R": {"last_price": 1, "depth": {"buy": [{"price": 1, "quantity": 5, "orders": 1}], "sell": []}},
         "NSE_EQ|T": {"last_price": 2, "depth": {"buy": [], "sell": []}}},
    )
    w = _CapWriter()
    cfg = _cfg(watchlist=["RELIANCE", "TCS"])
    rec = DepthRecorder(client, cfg, writer=w, now_fn=lambda: datetime(2026, 7, 13, 10, 30))
    n = rec.tick()
    assert n == 2 and len(w.rows) == 2
    assert {r["key"] for r in w.rows} == {"NSE_EQ|R", "NSE_EQ|T"}


def test_recorder_tick_skips_out_of_hours():
    from depth_recorder import DepthRecorder
    client = _FakeClient({"RELIANCE": "NSE_EQ|R"}, {"NSE_EQ|R": {"last_price": 1}})
    w = _CapWriter()
    cfg = _cfg(watchlist=["RELIANCE"])
    rec = DepthRecorder(client, cfg, writer=w, now_fn=lambda: datetime(2026, 7, 13, 8, 0))
    assert rec.tick() == 0 and w.rows == []


def test_recorder_start_stop_lifecycle():
    from depth_recorder import DepthRecorder
    client = _FakeClient({"RELIANCE": "NSE_EQ|R"}, {"NSE_EQ|R": {"last_price": 1}})
    w = _CapWriter()
    cfg = _cfg(watchlist=["RELIANCE"], depth_recorder_interval=0.01)
    rec = DepthRecorder(client, cfg, writer=w, now_fn=lambda: datetime(2026, 7, 13, 10, 30))
    rec.start()
    time.sleep(0.05)
    rec.stop()
    assert len(w.rows) >= 1        # at least one tick fired while running
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_depth_recorder.py -k "recorder" -v`
Expected: FAIL — `ImportError: cannot import name 'DepthRecorder'`

- [ ] **Step 3: Write minimal implementation**

Append to `depth_recorder.py`:

```python
class DepthRecorder:
    """Dedicated daemon thread: fetch watchlist raw quotes -> gate market hours -> build
    rows -> append gzip JSONL. Passive observer; never touches the order path."""

    def __init__(self, client, config, writer=None, now_fn=None, sleep_fn=None):
        self.client = client
        self.config = config
        self.interval = max(0.2, float(config.get("depth_recorder_interval", 1.0)))
        self.writer = writer or DepthWriter(config.get("depth_recorder_dir", "data/depth"))
        self._now = now_fn or datetime.now
        self._sleep = sleep_fn or time.sleep
        self._running = False
        self._thread = None

    def _watchlist_keys(self):
        keys = []
        for sym in self.config.get("watchlist", []):
            info = self.client.get_instrument_info(sym)
            if info and info.get("instrument_key"):
                keys.append(info["instrument_key"])
        return keys

    def tick(self):
        """One capture cycle. Public for testing. Returns number of rows written
        (0 when out-of-hours or no data)."""
        now = self._now()
        if not market_hours_now(now, self.config):
            return 0
        keys = self._watchlist_keys()
        if not keys:
            return 0
        raw = self.client.fetch_raw_quotes(keys)
        ts = now.isoformat()
        rows = [build_row(k, raw.get(k), ts) for k in keys if raw.get(k) is not None]
        self.writer.append(rows, day=now.strftime("%Y-%m-%d"))
        return len(rows)

    def _run(self):
        while self._running:
            try:
                self.tick()
            except Exception as e:
                print(f"[DepthRecorder] tick error: {e}")
            self._sleep(self.interval)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="DepthRecorder", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        try:
            self.writer.close()
        except Exception:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test_depth_recorder.py -v`
Expected: PASS (all tests in file)

- [ ] **Step 5: Commit**

```bash
git add depth_recorder.py test_depth_recorder.py
git commit -m "feat: DepthRecorder daemon — fetch/gate/serialize/append loop"
```

---

### Task 5: Wire into `main.py` + config keys

Start the recorder at app startup (guarded), stop it at shutdown, and add config keys.

**Files:**
- Modify: `main.py` (lifespan globals ~line 151; startup ~after line 187; shutdown after `yield` ~line 191; module global near line 422)
- Modify: `config.template.json` (after `"market_feed_interval"` ~line 111)
- Modify: `config.json` (live — set `enable_depth_recorder: true`; NOT committed, gitignored)
- Test: manual smoke + full suite

**Interfaces:**
- Consumes: `DepthRecorder(client, client.config)` (Task 4).
- Produces: nothing consumed by later tasks (terminal task).

- [ ] **Step 1: Add config keys to the template**

In `config.template.json`, find (~line 111):

```json
  "enable_market_feed": false,
  "market_feed_mode": "rest",
  "market_feed_interval": 1.0,
```

Add immediately after `"market_feed_interval": 1.0,`:

```json
  "enable_depth_recorder": false,
  "depth_recorder_interval": 1.0,
  "depth_recorder_symbols": "watchlist",
  "depth_recorder_start": "09:15",
  "depth_recorder_end": "15:30",
```

- [ ] **Step 2: Declare the module global in `main.py`**

Find (~line 422):

```python
market_feed = None
```

Add on the next line:

```python
depth_recorder = None
```

Then find the lifespan global declaration (~line 151):

```python
    global order_queue, market_feed, bot_running
```

Replace with:

```python
    global order_queue, market_feed, bot_running, depth_recorder
```

- [ ] **Step 3: Add startup + shutdown wiring in the lifespan**

In `main.py`, find the end of the market-feed startup block (~line 185-187):

```python
        except Exception as e:
            market_feed = None
            print(f"[startup] Failed to start market feed, using inline REST: {e}")

    asyncio.create_task(scanner_loop())
```

Replace with:

```python
        except Exception as e:
            market_feed = None
            print(f"[startup] Failed to start market feed, using inline REST: {e}")

    # Optional depth-snapshot recorder (off by default). Passive observer that records
    # full 5-level order-book depth to data/depth/*.jsonl.gz for later microstructure
    # backtesting. Fully guarded — a recorder failure can never affect trading.
    if client.config.get("enable_depth_recorder", False):
        try:
            from depth_recorder import DepthRecorder
            depth_recorder = DepthRecorder(client, client.config)
            depth_recorder.start()
            log_scan("SYSTEM", f"Depth recorder started (interval={depth_recorder.interval}s).", "info")
        except Exception as e:
            depth_recorder = None
            print(f"[startup] Failed to start depth recorder: {e}")

    asyncio.create_task(scanner_loop())
```

Then find the `yield` that ends the lifespan startup (~line 191):

```python
    asyncio.create_task(scanner_loop())
    asyncio.create_task(position_manager_loop())
    yield
```

Replace with:

```python
    asyncio.create_task(scanner_loop())
    asyncio.create_task(position_manager_loop())
    yield
    try:
        if depth_recorder is not None:
            depth_recorder.stop()
    except Exception:
        pass
```

- [ ] **Step 4: Verify the module imports cleanly and the full suite passes**

Run: `python -c "import depth_recorder; import main; print('import ok')"`
Expected: prints `import ok` (no traceback).

Run: `python -m pytest -q`
Expected: all tests pass, including the new `test_depth_recorder.py` (previous baseline 209 + new tests).

Run: `python -m ruff check depth_recorder.py test_depth_recorder.py upstox_client.py main.py`
Expected: no errors.

- [ ] **Step 5: Enable in the live config**

Edit `config.json` (gitignored — live token file). Add the same five keys as Step 1 next to `"market_feed_interval"`, but with `"enable_depth_recorder": true`. This turns the recorder on for the next `python main.py` run.

- [ ] **Step 6: Commit (code + template only — never config.json)**

```bash
git add main.py config.template.json
git commit -m "feat: wire depth recorder into app lifespan + config keys"
```

---

## Post-Implementation Verification (not a commit step)

At the next market open (09:15 IST), start the bot (`python main.py`) and confirm:
- Log line: `Depth recorder started (interval=1.0s).`
- Within a minute, `data/depth/<today>.jsonl.gz` exists and grows.
- Spot-check: `python -c "import gzip,json; f=gzip.open('data/depth/<today>.jsonl.gz','rt'); print(json.loads(f.readline()))"` shows a row with populated `bid`/`ask` lists during market hours.
