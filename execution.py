"""
execution.py — thin order-routing layer (Section 2's execution.py role).

Same code path for paper and live: the only difference is which BrokerAdapter instance this is
constructed with (UpstoxClient — whose own paper_trading branches already give realistic paper
fills — or MockBroker for a fully credentials-free run). This does not duplicate main.py's
existing entry/exit logic (F&O contract resolution, slippage guards, position bookkeeping); it's
the single "place an order" choke point orchestrator.py and any future caller route through, so
that swapping paper<->live is exactly a broker-instance swap, nothing else.
"""

from __future__ import annotations


from broker_base import BrokerAdapter


class ExecutionEngine:
    def __init__(self, broker: BrokerAdapter):
        self.broker = broker

    def place_entry(
        self,
        symbol: str,
        direction: str,
        quantity: int,
        order_type: str,
        price: float,
        instrument_key: str | None = None,
        tag: str = "autobot",
    ) -> dict:
        action = "BUY" if direction.upper() in ("LONG", "BUY") else "SELL"
        return self.broker.place_order(symbol, action, quantity, order_type, price, tag=tag, instrument_key=instrument_key)

    def place_exit(
        self,
        symbol: str,
        direction: str,
        quantity: int,
        price: float = 0.0,
        instrument_key: str | None = None,
        tag: str = "autobot_exit",
    ) -> dict:
        """`direction` is the position's entry direction — the exit order is the opposite side."""
        action = "SELL" if direction.upper() in ("LONG", "BUY") else "BUY"
        return self.broker.place_order(symbol, action, quantity, "MARKET", price, tag=tag, instrument_key=instrument_key)

    def cancel(self, order_id: str) -> dict:
        return self.broker.cancel_order(order_id)

    def modify(self, order_id: str, **kwargs) -> dict:
        return self.broker.modify_order(order_id, **kwargs)

    def order_status(self, order_id: str) -> dict:
        return self.broker.get_order_status(order_id)

    def get_quote(self, instrument_key: str) -> dict | None:
        return self.broker.get_market_quote(instrument_key)

    def get_candles(self, instrument_key: str, interval: str) -> list | None:
        return self.broker.get_intraday_candles(instrument_key, interval)

    def get_funds_and_margin(self) -> dict | None:
        return self.broker.get_funds_and_margin()
