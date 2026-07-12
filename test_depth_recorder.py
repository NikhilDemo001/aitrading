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
