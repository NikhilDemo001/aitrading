"""
Abstract broker adapter interface (Section 2 /broker/base.py role).

`UpstoxClient` (upstox_client.py) already implements every method here with matching
signatures — it is registered as a virtual subclass below rather than rewritten, so its
internals (OAuth flow, instrument caching, paper-mode order mocking, etc.) stay untouched.
`MockBroker` (mock_broker.py) implements the same interface for credentials-free paper runs
(orchestrator.py standalone, tests).

Design rule (Section 2): paper and live must share the exact same strategy + risk + logging
code path — the only thing that changes is which BrokerAdapter instance execution.py is
constructed with.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class BrokerAdapter(ABC):
    """Every broker (real or mock) must implement this surface."""

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        order_type: str,
        price: float,
        tag: str = "",
        instrument_key: Optional[str] = None,
    ) -> dict:
        """Returns a dict with at least {order_id, price, status}."""
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def modify_order(self, order_id: str, **kwargs: Any) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_order_status(self, order_id: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def get_market_quote(self, instrument_key: str) -> Optional[dict]:
        """Returns a dict with at least {ltp}, or None if unavailable."""
        raise NotImplementedError

    @abstractmethod
    def get_intraday_candles(self, instrument_key: str, interval: str) -> Optional[list]:
        """Returns a list of OHLCV candle dicts (ascending by time), or None."""
        raise NotImplementedError

    @abstractmethod
    def get_funds_and_margin(self) -> Optional[dict]:
        """Returns a dict shaped like Upstox's funds/margin response, or None."""
        raise NotImplementedError


def _register_upstox_client() -> None:
    """UpstoxClient already implements every BrokerAdapter method (verified against
    upstox_client.py: place_order, cancel_order, modify_order, get_order_status,
    get_market_quote, get_intraday_candles, get_funds_and_margin all present with matching
    call signatures). Registering it as a virtual subclass makes `isinstance(client,
    BrokerAdapter)` true without touching upstox_client.py at all."""
    try:
        from upstox_client import UpstoxClient
        BrokerAdapter.register(UpstoxClient)
    except Exception:
        pass


_register_upstox_client()
