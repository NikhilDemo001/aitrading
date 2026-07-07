"""Duplicate-exit race (2026-07-06 incident).

Two square-off paths ran concurrently (EMERGENCY KILL SWITCH + MANUAL SQUARE-OFF). The
kill switch closed MAZDA and _remove_position() cleared the _exiting_symbols claim; the
manual path — still holding a pre-removal `pos` reference from its own snapshot — then
re-entered execute_exit, passed the guard, and recorded the same close twice.

The guard must also reject any exit whose `pos` is no longer the object tracked in
active_positions (closed or replaced meanwhile). Entry-abort paths that legitimately
exit an untracked position declare it with pos_already_removed=True.
"""

import asyncio
import time
import types
import functools  # noqa: F401  (mirrors main's quote-fetch pattern)

import pytest

import main
import symbol_memory


def _pos(symbol="MAZDA", qty=133, entry=275.38):
    return {
        "symbol": symbol, "instrument_key": f"NSE_EQ|{symbol}", "is_fno": False,
        "contract": "", "strategy": "SupportResistance-Breakout-Buy", "direction": "LONG",
        "quantity": qty, "entry_price": entry, "entry_time": "2026-07-06T14:25:39",
        "stop_loss": 272.0, "target": 280.0, "target_2": 283.0, "t1_hit": False,
        "order_id": "MOCK-1", "current_price": 274.03, "pnl": 0.0,
        "atr_at_entry": 1.5, "trailing_high": 275.38, "trailing_low": None,
        "market_context": {}, "regime": "trending_up", "htf_trend": "up",
        "mae": 0.0, "mfe": 0.0, "confluence_score": 5,
        "trigger_level_source": None, "trigger_level_price": None,
        "trigger_level_score": None, "sl_order_id": None,
    }


@pytest.fixture()
def wired(monkeypatch):
    """Run the REAL execute_exit with all I/O stubbed out."""
    ns = types.SimpleNamespace(scan_logs=[], jsonl=[], orders=[])

    class _OQ:
        async def submit(self, fn, *args, **kwargs):
            ns.orders.append((getattr(fn, "__name__", str(fn)), args))
            return {"price": 274.03, "status": "ok"}

    async def _noop_broadcast(_msg):
        return None

    ns.client = types.SimpleNamespace(
        config={"paper_trading": True, "enable_rl_sizing": False},
        place_order=lambda *a, **k: None,
        cancel_order=lambda oid: None,
        get_market_quote=lambda key: {"ltp": 274.03},
    )
    monkeypatch.setattr(main, "client", ns.client)
    monkeypatch.setattr(main, "order_queue", _OQ())
    monkeypatch.setattr(main, "save_state", lambda: None)
    monkeypatch.setattr(main, "jsonl_logger", types.SimpleNamespace(
        log_trade=lambda record, mode=None: ns.jsonl.append(record)))
    monkeypatch.setattr(main, "manager", types.SimpleNamespace(broadcast=_noop_broadcast))
    monkeypatch.setattr(main, "log_scan",
                        lambda sym, msg, cat="info": ns.scan_logs.append((sym, msg, cat)))
    monkeypatch.setattr(main, "trade_history", [])
    monkeypatch.setattr(main, "daily_pnl", 0.0)
    monkeypatch.setattr(main, "active_positions", {})
    monkeypatch.setattr(main, "_exiting_symbols", set())
    monkeypatch.setattr(symbol_memory, "record_trade", lambda **k: None)
    return ns


def test_stale_pos_reference_cannot_double_close(wired):
    """Exact incident replay: exit completes + position removed, then a second exit path
    arrives holding the stale pos reference. It must be rejected, not re-recorded."""
    pos = _pos()
    main.active_positions["MAZDA"] = pos

    ok = asyncio.run(main.execute_exit("MAZDA", pos, 274.03,
                                       "EMERGENCY KILL SWITCH", paper_trading=True))
    assert ok is True
    main._remove_position("MAZDA")          # what square_off_all does after a True return

    dup = asyncio.run(main.execute_exit("MAZDA", pos, 274.03,
                                        "MANUAL SQUARE-OFF", paper_trading=True))
    assert dup is False, "stale exit must be rejected once the position is gone"
    assert len(main.trade_history) == 1, "the same close must never be recorded twice"
    assert len(wired.jsonl) == 1


def test_replaced_position_not_closed_by_stale_reference(wired):
    """If the symbol re-entered meanwhile (max 2 trades/symbol/day), a stale reference to
    the OLD position must not close the NEW one."""
    old_pos = _pos()
    main.active_positions["MAZDA"] = _pos()  # different object: the re-entered position

    ok = asyncio.run(main.execute_exit("MAZDA", old_pos, 274.03,
                                       "MANUAL SQUARE-OFF", paper_trading=True))
    assert ok is False
    assert main.trade_history == []
    assert "MAZDA" in main.active_positions


def test_untracked_pos_exit_allowed_when_flagged(wired):
    """Entry-abort paths (slippage anomaly / SL placement failure) exit a position that was
    never (or no longer) tracked — they must still work via pos_already_removed=True."""
    pos = _pos()
    ok = asyncio.run(main.execute_exit("MAZDA", pos, 274.03,
                                       "ENTRY SL FAILED - SAFETY EXIT", paper_trading=True,
                                       pos_already_removed=True))
    assert ok is True
    assert len(main.trade_history) == 1


def test_concurrent_square_off_all_closes_each_position_once(wired):
    """Production scenario: kill switch and manual square-off running concurrently must
    produce exactly one close per position regardless of interleaving."""
    pos = _pos()
    main.active_positions["MAZDA"] = pos

    delays = iter([0.01, 0.08])  # first caller wins, second arrives after removal

    def slow_quote(_key):
        time.sleep(next(delays, 0.08))
        return {"ltp": 274.03}

    wired.client.get_market_quote = slow_quote

    async def both():
        await asyncio.gather(main.square_off_all("EMERGENCY KILL SWITCH"),
                             main.square_off_all("MANUAL SQUARE-OFF"))

    asyncio.run(both())
    assert len(main.trade_history) == 1, "concurrent square-offs must close a position once"
    assert "MAZDA" not in main.active_positions


def test_realized_daily_pnl_excludes_shadow_and_stale():
    """2026-07-07 incident: a +7,672 SHADOW (counterfactual) trade inflated daily_pnl on a
    mid-day restart, which in live mode would delay the daily-loss kill switch by that amount.
    The recompute must count only real closed trades for the given day."""
    trades = [
        {"exit_time": "2026-07-07T10:00:00", "pnl": -500.0},                            # real loss
        {"exit_time": "2026-07-07T11:00:00", "pnl": 200.0, "is_shadow_trade": False},   # real win
        {"exit_time": "2026-07-07T12:00:00", "pnl": 7672.5, "is_shadow_trade": True},   # shadow — excluded
        {"exit_time": "2026-07-07T09:20:00", "pnl": -50.0,
         "reason": "STALE_STARTUP_SQUAREOFF"},                                          # stale — excluded
        {"exit_time": "2026-07-06T14:00:00", "pnl": 999.0},                             # other day — excluded
        {"pnl": 123.0},                                                                 # no exit_time — excluded
    ]
    assert main._realized_daily_pnl(trades, "2026-07-07") == -300.0
    assert main._realized_daily_pnl([], "2026-07-07") == 0.0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
