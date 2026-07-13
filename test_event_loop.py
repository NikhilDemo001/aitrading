"""Event-loop responsiveness: heavy sync work (research-lab simulation, RL batch training,
EOD research cycle) must run in the executor, never directly on the loop.

Regression context: research_lab.simulate_paper_trades_daily() — sync network candle fetches
plus a full backtest — was called directly inside position_manager_loop every 10 seconds,
freezing the entire server (dashboard, WebSocket, position exits) for 3-30s at a time.
Diagnosed live via py-spy: MainThread blocked in ssl read under
get_intraday_candles ← simulate_paper_trades_daily ← position_manager_loop.
"""

import asyncio
import time

import main


def test_off_loop_keeps_event_loop_responsive():
    """While a 0.5s blocking call runs through main._off_loop, a 50ms heartbeat task must
    keep ticking. If the blocking call ran on the loop, beats would be 0."""

    async def scenario():
        beats = 0

        async def heartbeat():
            nonlocal beats
            while True:
                await asyncio.sleep(0.05)
                beats += 1

        hb = asyncio.create_task(heartbeat())
        await main._off_loop(time.sleep, 0.5)
        hb.cancel()
        return beats

    beats = asyncio.run(scenario())
    assert beats >= 5, f"event loop starved during blocking work (only {beats} heartbeats)"


def test_off_loop_returns_result_and_propagates_errors():
    async def ok():
        return await main._off_loop(lambda a, b: a + b, 2, 3)

    assert asyncio.run(ok()) == 5

    async def boom():
        def bad():
            raise ValueError("expected")
        await main._off_loop(bad)

    try:
        asyncio.run(boom())
        raise AssertionError("exception must propagate from executor")
    except ValueError:
        pass


class _FakeLoop:
    """Captures whatever the handler delegates to the default handler."""
    def __init__(self):
        self.delegated = []

    def default_exception_handler(self, context):
        self.delegated.append(context)


def test_quiet_handler_swallows_windows_connection_reset():
    """WinError 10054 on socket teardown (dashboard client closed the connection) is benign
    noise — the handler must swallow it and NOT delegate to the noisy default handler."""
    loop = _FakeLoop()
    main._quiet_connection_reset_handler(loop, {"exception": ConnectionResetError(10054, "reset")})
    assert loop.delegated == []


def test_quiet_handler_delegates_real_errors():
    """Any non-ConnectionResetError must still reach the default handler so real bugs are
    never silently hidden."""
    loop = _FakeLoop()
    ctx = {"exception": ValueError("a real bug")}
    main._quiet_connection_reset_handler(loop, ctx)
    assert loop.delegated == [ctx]


def test_quiet_handler_delegates_when_no_exception():
    loop = _FakeLoop()
    ctx = {"message": "some loop message with no exception"}
    main._quiet_connection_reset_handler(loop, ctx)
    assert loop.delegated == [ctx]
