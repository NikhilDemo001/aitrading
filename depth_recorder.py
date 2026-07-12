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
