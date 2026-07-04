"""
Credentials-free broker simulator (Section 10: "A mock broker is required so the whole
system runs and is testable without live credentials"). Used by orchestrator.py when run
standalone (`python orchestrator.py`) and by tests that need a full paper-mode session
without hitting Upstox or requiring an access token.

Not the same as UpstoxClient's own paper-trading branches (which still call Upstox's REST
API for realistic quotes/candles, just skip the real order placement). MockBroker never
makes a network call at all — prices are a seeded random walk, so runs are repeatable.
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timedelta
from typing import Any

from broker_base import BrokerAdapter


class MockBroker(BrokerAdapter):
    def __init__(self, seed: int = 42, starting_capital: float = 100000.0):
        self._rng = random.Random(seed)
        self._prices: dict[str, float] = {}
        self._order_counter = 0
        self._orders: dict[str, dict] = {}
        self.starting_capital = starting_capital

    def _price_for(self, instrument_key: str, base: float = 1000.0) -> float:
        if instrument_key not in self._prices:
            self._prices[instrument_key] = base * (1 + self._rng.uniform(-0.05, 0.05))
        drift = self._rng.uniform(-0.004, 0.004)
        self._prices[instrument_key] = max(0.05, self._prices[instrument_key] * (1 + drift))
        return round(self._prices[instrument_key], 2)

    def place_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        order_type: str,
        price: float,
        tag: str = "",
        instrument_key: str | None = None,
    ) -> dict:
        self._order_counter += 1
        order_id = f"MOCK-{self._order_counter}-{int(time.time() * 1000)}"
        key = instrument_key or symbol
        fill_price = price if (order_type == "LIMIT" and price) else self._price_for(key)
        order = {
            "order_id": order_id,
            "price": round(fill_price, 2),
            "status": "FILLED",
            "symbol": symbol,
            "quantity": quantity,
            "transaction_type": action,
        }
        self._orders[order_id] = order
        return order

    def cancel_order(self, order_id: str) -> dict:
        self._orders.pop(order_id, None)
        return {"order_id": order_id, "status": "cancelled"}

    def modify_order(self, order_id: str, **kwargs: Any) -> dict:
        order = self._orders.get(order_id, {"order_id": order_id})
        order.update(kwargs)
        return order

    def get_order_status(self, order_id: str) -> dict:
        return self._orders.get(order_id, {"order_id": order_id, "status": "unknown"})

    def get_market_quote(self, instrument_key: str) -> dict | None:
        return {
            "ltp": self._price_for(instrument_key),
            "volume": self._rng.randint(50000, 500000),
            "net_change": round(self._rng.uniform(-10, 10), 2),
        }

    def get_market_quotes(self, instrument_keys: list) -> dict:
        return {k: self.get_market_quote(k) for k in instrument_keys}

    def get_intraday_candles(self, instrument_key: str, interval: str = "5minute") -> list | None:
        base = self._price_for(instrument_key)
        candles = []
        price = base * 0.98
        now = datetime.now()
        n = 40
        for i in range(n):
            o = price
            drift = self._rng.uniform(-0.005, 0.005)
            c = max(0.05, o * (1 + drift))
            h = max(o, c) * (1 + abs(self._rng.uniform(0, 0.003)))
            l = min(o, c) * (1 - abs(self._rng.uniform(0, 0.003)))
            vol = self._rng.randint(1000, 20000)
            ts = (now - timedelta(minutes=(n - i) * 5)).strftime("%Y-%m-%d %H:%M:%S")
            candles.append({
                "timestamp": ts, "open": round(o, 2), "high": round(h, 2),
                "low": round(l, 2), "close": round(c, 2), "volume": vol,
            })
            price = c
        return candles

    def get_funds_and_margin(self) -> dict | None:
        return {
            "status": "success",
            "data": {"equity": {"available_margin": self.starting_capital, "used_margin": 0.0}},
        }
