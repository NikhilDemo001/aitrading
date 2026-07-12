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
