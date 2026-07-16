"""Unit tests for upstox_client.py — credentials-free (paper-mode paths only)."""

import base64
import json
import os
import types
from datetime import datetime

from upstox_client import UpstoxClient


def _jwt_with_exp(ts):
    """Build a minimal JWT whose `exp` claim decodes the same way _token_expired() reads it."""
    header = base64.b64encode(b'{"typ":"JWT","alg":"HS256"}').decode().rstrip("=")
    body = base64.b64encode(json.dumps({"sub": "X", "exp": int(ts)}).encode()).decode().rstrip("=")
    return f"{header}.{body}.sig"


class _FakeResp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._p = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._p


def test_get_market_quote_surfaces_circuit_limits():
    """The circuit-proximity guard needs the day's upper/lower circuit limits, so
    get_market_quote must surface them (they were previously dropped from the parse)."""
    c = UpstoxClient.__new__(UpstoxClient)      # bypass __init__ (no config/network)
    c.access_token = "tok"
    payload = {"status": "success", "data": {"NSE_EQ:RELIANCE": {
        "instrument_token": "NSE_EQ|INE002A01018",
        "last_price": 100.0,
        "ohlc": {"open": 99, "high": 101, "low": 98, "close": 99},
        "volume": 1000,
        "upper_circuit_limit": 110.0,
        "lower_circuit_limit": 90.0,
        "depth": {"buy": [{"price": 99.9, "quantity": 10, "orders": 1}],
                  "sell": [{"price": 100.1, "quantity": 12, "orders": 1}]},
    }}}
    c.session = types.SimpleNamespace(get=lambda *a, **k: _FakeResp(payload))
    q = c.get_market_quote("NSE_EQ|INE002A01018")
    assert q["upper_circuit"] == 110.0
    assert q["lower_circuit"] == 90.0


def test_get_news_returns_recent_items_newest_first():
    c = UpstoxClient.__new__(UpstoxClient)
    c.access_token = "tok"
    c.get_headers = lambda: {}
    payload = {"status": "success", "data": {"NSE_EQ|INE002A01018": [
        {"heading": "older", "summary": "s1", "published_time": 100},
        {"heading": "newest", "summary": "s2", "published_time": 200},
    ]}}
    c.session = types.SimpleNamespace(get=lambda *a, **k: _FakeResp(payload))
    items = c.get_news("NSE_EQ|INE002A01018", page_size=5)
    assert len(items) == 2
    assert items[0]["heading"] == "newest"      # sorted newest-first
    assert items[0]["published"] == 200


def test_get_news_empty_when_no_articles():
    c = UpstoxClient.__new__(UpstoxClient)
    c.access_token = "tok"
    c.get_headers = lambda: {}
    c.session = types.SimpleNamespace(get=lambda *a, **k: _FakeResp({"status": "success", "data": {}}))
    assert c.get_news("NSE_EQ|INE002A01018") == []


def test_get_news_never_raises_on_error():
    c = UpstoxClient.__new__(UpstoxClient)
    c.access_token = "tok"
    c.get_headers = lambda: {}
    def _boom(*a, **k):
        raise RuntimeError("network down")
    c.session = types.SimpleNamespace(get=_boom)
    assert c.get_news("NSE_EQ|INE002A01018") == []


def test_get_competitors_uses_full_encoded_instrument_key():
    """Regression: the competitors endpoint uniquely requires the FULL instrument key
    (NSE_EQ|ISIN), URL-encoded — the bare ISIN returns 400 UDAPI100011 'Invalid Instrument
    key'. Assert the request path carries NSE_EQ%7CINE... (pipe encoded) + /competitors."""
    c = UpstoxClient.__new__(UpstoxClient)
    c.access_token = "tok"
    c.get_headers = lambda: {}
    captured = {}
    def _get(url, *a, **k):
        captured["url"] = url
        return _FakeResp({"status": "success", "data": [{"name": "RivalCo"}]})
    c.session = types.SimpleNamespace(get=_get)
    out = c.get_competitors("NSE_EQ|INE423A01024")
    assert out == [{"name": "RivalCo"}]
    assert "NSE_EQ%7CINE423A01024/competitors" in captured["url"]
    assert "INE423A01024/competitors" not in captured["url"].replace("%7C", "|").replace("|INE", "@")


def test_fundamentals_bare_isin_path_unchanged():
    """The other fundamentals endpoints pass a bare (alphanumeric) ISIN — encoding must be a
    no-op so those still hit /fundamentals/<ISIN>/<path>."""
    c = UpstoxClient.__new__(UpstoxClient)
    c.access_token = "tok"
    c.get_headers = lambda: {}
    captured = {}
    c.session = types.SimpleNamespace(
        get=lambda url, *a, **k: (captured.__setitem__("url", url),
                                  _FakeResp({"status": "success", "data": {"x": 1}}))[1])
    c.get_company_profile("INE002A01018")
    assert captured["url"].endswith("/fundamentals/INE002A01018/profile")


def test_await_fill_price_finds_completed_average():
    """_await_fill_price returns the broker's executed average price once the order is
    'complete', scanning all history records regardless of order."""
    c = UpstoxClient.__new__(UpstoxClient)
    c.access_token = "tok"
    c.get_headers = lambda: {}
    c.session = types.SimpleNamespace(get=lambda *a, **k: _FakeResp({"status": "success", "data": [
        {"status": "open", "average_price": 0},
        {"status": "complete", "average_price": 250.75}]}))
    assert c._await_fill_price("OID", tries=1) == 250.75


def test_place_order_live_records_actual_fill_not_limit():
    """Regression: a live entry must record the broker's ACTUAL average fill (250.75), not the
    limit price we sent (100.5) — otherwise the bot's entry never matches the Upstox app."""
    c = UpstoxClient.__new__(UpstoxClient)
    c.paper_trading = False
    c.access_token = "tok"
    c.get_headers = lambda: {}
    c._delivery_symbols = set()

    class _Sess:
        def post(self, url, headers=None, json=None, timeout=None):
            return _FakeResp({"status": "success", "data": {"order_id": "OID1"}})

        def get(self, url, headers=None, timeout=None):
            return _FakeResp({"status": "success", "data": [{"status": "complete", "average_price": 250.75}]})

    c.session = _Sess()
    order = c.place_order("RELIANCE", "BUY", 10, "LIMIT", price=100.5, instrument_key="NSE_EQ|X")
    assert order["order_id"] == "OID1"
    assert order["price"] == 250.75          # actual fill, NOT the 100.5 limit


def test_place_order_sl_skips_fill_lookup():
    """A pending SL order never 'completes' at placement — placing it must NOT poll order
    history (wasted latency); it keeps the SL limit price we sent."""
    c = UpstoxClient.__new__(UpstoxClient)
    c.paper_trading = False
    c.access_token = "tok"
    c.get_headers = lambda: {}
    c._delivery_symbols = set()
    calls = {"get": 0}

    class _Sess:
        def post(self, url, headers=None, json=None, timeout=None):
            return _FakeResp({"status": "success", "data": {"order_id": "SL1"}})

        def get(self, url, headers=None, timeout=None):
            calls["get"] += 1
            return _FakeResp({"status": "success", "data": []})

    c.session = _Sess()
    order = c.place_order("RELIANCE", "SELL", 10, "SL", price=99.0, trigger_price=99.5, instrument_key="NSE_EQ|X")
    assert order["price"] == 99.0            # SL limit retained
    assert calls["get"] == 0                 # no fill-history polling for a pending SL


def _paper_client(tmp_path) -> UpstoxClient:
    """A client over a throwaway config file so tests can never touch the real config.json
    (which holds live credentials)."""
    cfg = {"paper_trading": True, "api_key": "", "api_secret": "", "access_token": ""}
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg))
    return UpstoxClient(config_path=str(p))


def test_paper_token_refresh_does_not_fabricate_token():
    """Regression: paper mode must NOT mint a mock token when the daily token lapses.
    Paper trading still consumes REAL market data, so a fabricated token (future exp but
    rejected by Upstox with UDAPI100050) only masks a dead feed while the bot logs
    'auto-refreshed successfully' and runs blind all day. With no valid token loadable,
    try_refresh_token must return False so the scanner loop halts and prompts a real
    /login re-auth."""
    c = UpstoxClient.__new__(UpstoxClient)        # bypass __init__ (no config/network)
    c.paper_trading = True
    c.access_token = ""                           # stale/absent, as at ~3:30am daily expiry
    c.load_config = lambda: None                  # no re-login happened; nothing fresh arrives
    assert c.try_refresh_token() is False
    assert not c.access_token, "must not fabricate a working-looking token"


def test_token_refresh_true_after_relogin_and_verify():
    """Happy path: the user re-logged in via /login, so load_config now surfaces a fresh,
    unexpired token AND a live quote confirms Upstox accepts it — only then does refresh
    report success."""
    c = UpstoxClient.__new__(UpstoxClient)
    c.paper_trading = True
    c.access_token = ""
    fresh = _jwt_with_exp(datetime.now().timestamp() + 86400)
    c.load_config = lambda: setattr(c, "access_token", fresh)
    c.verify_token_live = lambda *a, **k: True    # Upstox accepts it
    assert c.try_refresh_token() is True


def test_verify_token_live_false_when_upstox_rejects_token():
    """verify_token_live must return False when Upstox rejects the token (auth error →
    get_market_quote returns None), so a stale/revoked token can't masquerade as valid."""
    c = UpstoxClient.__new__(UpstoxClient)
    c.access_token = "stale-token"
    c.get_headers = lambda: {}
    c.session = types.SimpleNamespace(
        get=lambda *a, **k: _FakeResp({"status": "error",
                                       "errors": [{"errorCode": "UDAPI100050"}]}, status=401))
    assert c.verify_token_live() is False


def test_verify_token_live_true_when_quote_succeeds():
    """A working token returns a real quote → verify_token_live True."""
    c = UpstoxClient.__new__(UpstoxClient)
    c.access_token = "good-token"
    c.get_headers = lambda: {}
    payload = {"status": "success", "data": {"NSE_INDEX|Nifty 50": {
        "instrument_token": "NSE_INDEX|Nifty 50", "last_price": 25000.0,
        "ohlc": {"open": 24900, "high": 25100, "low": 24800, "close": 24950}, "volume": 0,
        "depth": {"buy": [{"price": 24999.0, "quantity": 1, "orders": 1}],
                  "sell": [{"price": 25001.0, "quantity": 1, "orders": 1}]}}}}
    c.session = types.SimpleNamespace(get=lambda *a, **k: _FakeResp(payload))
    assert c.verify_token_live() is True
