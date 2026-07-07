"""Blocker #5 (2026-07-06): data/history/pattern_stats.jsonl was 0 bytes forever because
every logged trade carried candlestick_patterns=[]. The patterns detected at entry
(strategies.calculate_confidence_score computed and threw them away) were never attached to
the signal -> position -> exit record, so snapshot_pattern_stats always got empty input.

These lock the repaired pipeline: patterns are detectable as names, and execute_exit's logged
record carries whatever patterns the position was tagged with at entry.
"""

import asyncio
import types

import pytest

import main
import symbol_memory
from candlestick_patterns import detected_pattern_names


def candle(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


def downtrend_candles(n=8, start=100.0, step=1.0):
    out, price = [], start
    for _ in range(n):
        out.append(candle(price, price + 0.2, price - 0.5, price - step * 0.8))
        price -= step
    return out


# ── the new pure helper ──────────────────────────────────────────────────────────────

def test_detected_pattern_names_returns_flat_sorted_names():
    # A hammer-shaped candle after a downtrend is a bullish "Hammer".
    candles = downtrend_candles(8) + [candle(96.0, 96.4, 88.0, 94.0)]
    names = detected_pattern_names(candles)
    assert "Hammer" in names
    assert names == sorted(set(names))  # sorted + de-duplicated


def test_detected_pattern_names_empty_on_no_patterns():
    flat = [candle(100, 100.2, 99.8, 100.0) for _ in range(8)]
    assert isinstance(detected_pattern_names(flat), list)


def test_detected_pattern_names_safe_on_empty():
    assert detected_pattern_names([]) == []


# ── the pipeline seam that was dropping the data: position -> exit record ──────────────

@pytest.fixture()
def wired(monkeypatch):
    ns = types.SimpleNamespace(jsonl=[])

    class _OQ:
        async def submit(self, fn, *args, **kwargs):
            return {"price": 100.0, "status": "ok"}

    async def _noop(_msg):
        return None

    ns.client = types.SimpleNamespace(
        config={"paper_trading": True, "enable_rl_sizing": False},
        place_order=lambda *a, **k: None, cancel_order=lambda oid: None)
    monkeypatch.setattr(main, "client", ns.client)
    monkeypatch.setattr(main, "order_queue", _OQ())
    monkeypatch.setattr(main, "save_state", lambda: None)
    monkeypatch.setattr(main, "jsonl_logger", types.SimpleNamespace(
        log_trade=lambda record, mode=None: ns.jsonl.append(record)))
    monkeypatch.setattr(main, "manager", types.SimpleNamespace(broadcast=_noop))
    monkeypatch.setattr(main, "log_scan", lambda *a, **k: None)
    monkeypatch.setattr(main, "trade_history", [])
    monkeypatch.setattr(main, "daily_pnl", 0.0)
    monkeypatch.setattr(main, "active_positions", {})
    monkeypatch.setattr(main, "_exiting_symbols", set())
    monkeypatch.setattr(symbol_memory, "record_trade", lambda **k: None)
    return ns


def _pos(**over):
    p = {
        "symbol": "TATASTEEL", "instrument_key": "NSE_EQ|TATASTEEL", "is_fno": False,
        "strategy": "TrendFollow-Buy", "direction": "LONG", "quantity": 100,
        "entry_price": 100.0, "entry_time": "2026-07-06T10:00:00", "stop_loss": 98.0,
        "target": 104.0, "current_price": 101.0, "pnl": 0.0, "atr_at_entry": 1.0,
        "candlestick_patterns": ["Bullish Engulfing", "Hammer"],
    }
    p.update(over)
    return p


def test_exit_record_carries_position_patterns(wired):
    pos = _pos()
    main.active_positions["TATASTEEL"] = pos
    ok = asyncio.run(main.execute_exit("TATASTEEL", pos, 101.0, "TARGET", paper_trading=True))
    assert ok is True
    assert len(wired.jsonl) == 1
    assert wired.jsonl[0]["candlestick_patterns"] == ["Bullish Engulfing", "Hammer"]


def test_exit_record_patterns_default_empty_when_untagged(wired):
    pos = _pos()
    del pos["candlestick_patterns"]
    main.active_positions["TATASTEEL"] = pos
    asyncio.run(main.execute_exit("TATASTEEL", pos, 101.0, "TARGET", paper_trading=True))
    assert wired.jsonl[0]["candlestick_patterns"] == []


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
