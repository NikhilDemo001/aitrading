"""Unit tests for upstox_client.py — credentials-free (paper-mode paths only)."""

import json
import os

from upstox_client import UpstoxClient


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
