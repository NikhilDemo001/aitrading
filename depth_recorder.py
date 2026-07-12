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
