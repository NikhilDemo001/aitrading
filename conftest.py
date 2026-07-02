"""
Shared pytest fixtures / test-isolation guarantees.

Some production modules keep process-global caches for performance (they're correct in a real
run, where a given symbol resolves to one set of levels for the day). In the test suite, however,
different tests construct different MockClients for the SAME instrument_key, so a value cached by
one test would leak into another and make outcomes depend on test execution order.

`_reset_shared_state` clears those caches before every test so each test is hermetic, regardless
of order. This does not change any production behavior — it only affects the test process.
"""

import pytest


@pytest.fixture(autouse=True)
def _reset_shared_state():
    # Previous-day level cache (PDH/PDL/PDC), keyed by instrument_key+date. Poisoned across tests
    # that reuse an instrument_key with different mock daily candles.
    try:
        import strategy_support_resistance as sr
        sr._DAILY_LEVELS_CACHE.clear()
    except Exception:
        pass
    yield
