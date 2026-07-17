"""Max-capacity sizing must fail SAFE when the funds call fails.

Regression (2026-07-17, live): the funds/margin fetch failed on a transient proxy error, so
avail_margin was None. With enable_max_capacity=True the code fell through to the Kelly/risk
branch, which sizes off max_risk_per_trade alone and knows nothing about margin. On an account
with Rs 1,678 available it sized ~Rs 19k orders (qty 144 = int(500/3.5)); the broker rejected
every one ("You need to add Rs 19,152.37"), and the follow-up stop-loss was then rejected with
"This stock is not available in your holdings" because the entry never filled.

A failed funds check must skip the entry, never silently size bigger.
"""

import asyncio
import types

import pytest

import main


@pytest.fixture()
def wired(monkeypatch):
    ns = types.SimpleNamespace(orders=[], skips=[])

    async def fake_submit(fn, *a, **k):
        ns.orders.append((getattr(fn, "__name__", str(fn)), a))
        return {"order_id": "X", "price": 100.0}

    monkeypatch.setattr(main, "order_queue", types.SimpleNamespace(submit=fake_submit))
    monkeypatch.setattr(main, "log_scan", lambda *a, **k: None)
    monkeypatch.setattr(main.jsonl_logger, "log_decision",
                        lambda t, s, r, e=None: ns.skips.append((t, s, r)))
    monkeypatch.setattr(main, "active_positions", {})
    monkeypatch.setattr(main, "_build_market_context", lambda c: {})
    return ns


def _signal():
    return {"entry_price": 133.0, "stop_loss": 129.5, "target_1": 140.0, "target_2": 145.0,
            "strategy": "VWAP-Pullback-Buy", "atr": 3.5}


def test_entry_skipped_when_funds_unavailable_under_max_capacity(wired, monkeypatch):
    """avail_margin None + enable_max_capacity -> skip, and place NO order."""
    cfg = {"enable_max_capacity": True, "enable_kelly_sizing": True, "max_risk_per_trade": 500.0,
           "max_position_value": 27000.0, "paper_trading": False, "enable_fno": False}
    client = types.SimpleNamespace(
        config=cfg,
        get_funds_and_margin=lambda: None,          # the failure this guards against
        get_instrument_info=lambda s: {"instrument_key": "NSE_EQ|X"},
    )
    monkeypatch.setattr(main, "client", client)

    asyncio.run(main.execute_entry("SHAREINDIA", "NSE_EQ|X", _signal(), [], paper_trading=False))

    assert wired.orders == [], "no order may be placed when margin is unknown"
    assert any("funds unavailable" in r for _, _, r in wired.skips), \
        f"expected a funds-unavailable skip decision, got {wired.skips}"
