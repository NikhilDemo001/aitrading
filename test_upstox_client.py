"""Unit tests for upstox_client.py — credentials-free (paper-mode paths only)."""

import json
import os
import types

from upstox_client import UpstoxClient


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


def _paper_client(tmp_path) -> UpstoxClient:
    """A client over a throwaway config file so tests can never touch the real config.json
    (which holds live credentials)."""
    cfg = {"paper_trading": True, "api_key": "", "api_secret": "", "access_token": ""}
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg))
    return UpstoxClient(config_path=str(p))


def test_paper_token_refresh_produces_unexpired_token(tmp_path):
    """L2 auto-reauth, paper mode: try_refresh_token must mint a mock token whose exp claim
    is in the future — this is what keeps an overnight paper session running when the real
    Upstox token lapses. Regression: the refresh path used `timedelta` without importing it,
    so every call raised NameError (swallowed by the caller in main.py's scanner loop, which
    then halted the bot — the feature had never worked)."""
    prev_env = os.environ.get("UPSTOX_ACCESS_TOKEN")
    try:
        client = _paper_client(tmp_path)
        client.access_token = ""  # a stale/absent token, as at ~3:30am daily expiry
        assert client.try_refresh_token() is True
        assert client.access_token, "refresh must install a token"
        assert not client._token_expired(), "refreshed token must not be expired"
    finally:
        # try_refresh_token writes os.environ directly; don't leak the mock token into
        # other tests (load_config prefers the env var over config.json).
        if prev_env is None:
            os.environ.pop("UPSTOX_ACCESS_TOKEN", None)
        else:
            os.environ["UPSTOX_ACCESS_TOKEN"] = prev_env
