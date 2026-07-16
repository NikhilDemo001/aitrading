"""Broker-position reconciliation (live-mode safety).

If the operator closes a bot-held trade from another device (Upstox app/web), the bot must
record it as CLOSED EXTERNALLY — cancelling the leftover SL order and never placing a new
order (which would OPEN a reverse position on a flat book). None from get_positions() means
"broker state unknown" and must change nothing.
"""

import asyncio
import types
from datetime import timedelta

import pytest

import main
from upstox_client import UpstoxClient


# ── pure helpers ─────────────────────────────────────────────────────────────────────────

def test_net_positions_by_key_sums_rows():
    rows = [
        {"instrument_token": "K1", "quantity": 5},
        {"instrument_token": "K1", "quantity": 5},
        {"instrument_key": "K2", "quantity": -7},
        {"quantity": 99},  # no key -> ignored
    ]
    assert main._net_positions_by_key(rows) == {"K1": 10, "K2": -7}
    assert main._net_positions_by_key(None) == {}


def test_position_still_held_logic():
    long_pos = {"instrument_key": "K", "direction": "LONG", "quantity": 10}
    short_pos = {"instrument_key": "K", "direction": "SHORT", "quantity": 10}
    assert main._position_still_held(long_pos, {"K": 10}) is True
    assert main._position_still_held(long_pos, {"K": 15}) is True
    assert main._position_still_held(long_pos, {"K": 5}) is False   # partially closed outside
    assert main._position_still_held(long_pos, {}) is False         # fully closed outside
    assert main._position_still_held(short_pos, {"K": -10}) is True
    assert main._position_still_held(short_pos, {"K": -5}) is False
    assert main._position_still_held(short_pos, {"K": 0}) is False


# ── UpstoxClient.get_positions ───────────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, code, payload):
        self.status_code = code
        self._payload = payload

    def json(self):
        return self._payload


def test_client_get_positions_paper_returns_none():
    stub = types.SimpleNamespace(paper_trading=True)
    assert UpstoxClient.get_positions(stub) is None


def test_client_get_positions_parses_success():
    class _Sess:
        def get(self, url, headers=None, timeout=None):
            assert url.endswith("/portfolio/short-term-positions")
            return _FakeResp(200, {"status": "success",
                                   "data": [{"instrument_token": "NSE_EQ|X", "quantity": 5}]})

    stub = types.SimpleNamespace(paper_trading=False, session=_Sess(), get_headers=lambda: {})
    assert UpstoxClient.get_positions(stub) == [{"instrument_token": "NSE_EQ|X", "quantity": 5}]


def test_client_get_positions_error_returns_none_not_empty():
    class _Sess:
        def get(self, url, headers=None, timeout=None):
            return _FakeResp(500, {})

    stub = types.SimpleNamespace(paper_trading=False, session=_Sess(), get_headers=lambda: {})
    assert UpstoxClient.get_positions(stub) is None  # unknown, NOT "flat"


# ── reconcile_broker_positions ───────────────────────────────────────────────────────────

class _StubOrderQueue:
    def __init__(self):
        self.submitted = []

    async def submit(self, fn, *args, **kwargs):
        self.submitted.append((getattr(fn, "__name__", str(fn)), args))
        return {"status": "ok"}


def _pos(symbol="RELIANCE", direction="LONG", qty=10, key="NSE_EQ|INE002A01018", sl="SL-1"):
    return {"symbol": symbol, "direction": direction, "quantity": qty, "instrument_key": key,
            "entry_price": 100.0, "current_price": 101.5, "sl_order_id": sl,
            "entry_time": "2026-07-04T10:00:00", "strategy": "ORB-Buy", "stop_loss": 99.0}


@pytest.fixture()
def wired(monkeypatch):
    """Wire main's globals to no-network stubs; the returned namespace records what happened."""
    ns = types.SimpleNamespace(exits=[], broker_rows=[])

    async def fake_execute_exit(symbol, pos, exit_price, reason, paper_trading,
                                is_shadow=False, is_broker_hit=False):
        ns.exits.append({"symbol": symbol, "reason": reason,
                         "is_broker_hit": is_broker_hit, "price": exit_price})
        return True

    ns.oq = _StubOrderQueue()
    ns.client = types.SimpleNamespace(get_positions=lambda: ns.broker_rows,
                                      cancel_order=lambda oid: None, config={})
    monkeypatch.setattr(main, "execute_exit", fake_execute_exit)
    monkeypatch.setattr(main, "order_queue", ns.oq)
    monkeypatch.setattr(main, "client", ns.client)
    monkeypatch.setattr(main, "save_state", lambda: None)
    monkeypatch.setattr(main, "_last_broker_reconcile", 0.0)
    monkeypatch.setattr(main, "active_positions", {})
    return ns


def test_paper_mode_skips_reconcile(wired):
    main.active_positions["RELIANCE"] = _pos()
    assert asyncio.run(main.reconcile_broker_positions(paper_trading=True)) == []
    assert wired.exits == []


def test_unknown_broker_state_changes_nothing(wired):
    main.active_positions["RELIANCE"] = _pos()
    wired.broker_rows = None  # API failed / unknown — must NOT be read as "flat"
    assert asyncio.run(main.reconcile_broker_positions(paper_trading=False)) == []
    assert "RELIANCE" in main.active_positions
    assert wired.exits == []


def test_externally_closed_long_is_reconciled(wired):
    main.active_positions["RELIANCE"] = _pos()
    wired.broker_rows = []  # broker confirmed flat
    assert asyncio.run(main.reconcile_broker_positions(paper_trading=False)) == ["RELIANCE"]
    assert "RELIANCE" not in main.active_positions
    assert len(wired.exits) == 1
    exit_rec = wired.exits[0]
    assert exit_rec["is_broker_hit"] is True                 # no order was placed
    assert "CLOSED EXTERNALLY" in exit_rec["reason"]
    assert exit_rec["price"] == 101.5                        # last known mark
    # the leftover SL order was cancelled so it can't fire on a flat book
    assert wired.oq.submitted and wired.oq.submitted[0][1] == ("SL-1",)


def test_still_held_position_untouched(wired):
    main.active_positions["RELIANCE"] = _pos()
    wired.broker_rows = [{"instrument_token": "NSE_EQ|INE002A01018", "quantity": 10}]
    assert asyncio.run(main.reconcile_broker_positions(paper_trading=False)) == []
    assert "RELIANCE" in main.active_positions
    assert wired.exits == []


def test_short_position_covered_externally(wired):
    main.active_positions["TCS"] = _pos(symbol="TCS", direction="SHORT", key="NSE_EQ|TCS", sl=None)
    wired.broker_rows = [{"instrument_token": "NSE_EQ|TCS", "quantity": -10}]
    assert asyncio.run(main.reconcile_broker_positions(paper_trading=False)) == []
    main._last_broker_reconcile = 0.0  # reset throttle for the second pass
    wired.broker_rows = []             # operator covered the short from another device
    assert asyncio.run(main.reconcile_broker_positions(paper_trading=False)) == ["TCS"]


def test_fresh_fill_not_reconciled_during_settle_window(wired):
    """Regression (ITDC, 2026-07-16): a just-filled position missing from the broker's
    positions feed (propagation lag) must NOT be treated as CLOSED EXTERNALLY within the
    settling window — that orphaned a live short and cancelled its stop-loss 1s after entry,
    leaving a naked, unmanaged real-money position."""
    fresh = _pos(sl="SL-9")
    fresh["entry_time"] = main.get_ist_now().isoformat()   # opened just now
    main.active_positions["RELIANCE"] = fresh
    wired.broker_rows = []                                   # feed hasn't caught up to the fill
    assert asyncio.run(main.reconcile_broker_positions(paper_trading=False)) == []
    assert "RELIANCE" in main.active_positions               # still under management
    assert wired.exits == []                                 # not exited
    assert wired.oq.submitted == []                          # SL NOT cancelled
    assert main.active_positions["RELIANCE"].get("sl_order_id") == "SL-9"   # stop retained


def test_position_reconciled_after_settle_window(wired):
    """The grace period only DELAYS, never disables: once the fill is older than the settling
    window, a genuinely flat broker book still reconciles the position away."""
    aged = _pos(sl="SL-2")
    aged["entry_time"] = (main.get_ist_now() - timedelta(seconds=60)).isoformat()
    main.active_positions["RELIANCE"] = aged
    wired.broker_rows = []
    assert asyncio.run(main.reconcile_broker_positions(paper_trading=False)) == ["RELIANCE"]
    assert "RELIANCE" not in main.active_positions
    assert len(wired.exits) == 1


def test_throttle_limits_api_calls(wired):
    calls = {"n": 0}

    def counting_get_positions():
        calls["n"] += 1
        return []

    wired.client.get_positions = counting_get_positions
    main.active_positions["RELIANCE"] = _pos(sl=None)
    asyncio.run(main.reconcile_broker_positions(paper_trading=False))
    main.active_positions["RELIANCE"] = _pos(sl=None)  # re-add within the throttle window
    asyncio.run(main.reconcile_broker_positions(paper_trading=False))
    assert calls["n"] == 1  # second cycle was throttled


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
