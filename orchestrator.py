"""
orchestrator.py — Section 3's continuous loop, runnable fully standalone with zero live
credentials (DoD #1: `python orchestrator.py` runs the full loop in paper mode using the mock
broker, end to end).

Scope note (deviation from the original build plan, recorded here rather than silently): the
plan called for *extracting* main.py's scanner_loop/position_manager_loop into this module.
Once in the code, those two functions turned out to be ~1500 lines of already-proven, tightly
coupled production logic — F&O contract resolution, VIX-adaptive trailing stops, sector/symbol
memory, research-lab EOD hooks — built directly against ~15 of main.py's module-level globals
(active_positions, shadow_positions, order_queue, the WebSocket manager, etc.). Mechanically
splitting that apart mid-session risked reintroducing subtle bugs across a feature surface this
large, well beyond what could be re-validated as thoroughly as its current working form already
has been. main.py keeps running its own loop for the live dashboard (already routed through
RiskManager/jsonl_logger/the new candlestick patterns from this same session). This module is
instead a clean-room implementation of the Section 3 loop, built on the same new architecture
(RiskManager, the Strategy interface, execution.py, jsonl_logger) — the standalone, testable
reference the Definition of Done asks for, and what future work (backtest replay, CI smoke
tests) should target instead of main.py's dashboard-coupled loop.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from broker_base import BrokerAdapter
from mock_broker import MockBroker
from execution import ExecutionEngine
from risk_manager import RiskManager
from strategy_interface import Features
from strategies import detect_market_regime, get_htf_trend, select_best_strategy
import jsonl_logger
import leaderboard
import history
import lane_b

DEFAULT_CONFIG = {
    "mode": "paper",
    "capital": 100000.0,
    "symbols": ["RELIANCE", "HDFCBANK"],
    "timeframe": "5minute",
    "risk_per_trade_pct": 0.5,
    "max_daily_loss": 2000.0,
    "max_weekly_loss_pct": 0.1,
    "max_weekly_loss_abs": 100000.0,
    "max_consecutive_losses": 4,
    "loss_halt_minutes": 30,
    "max_open_positions": 2,
    "trade_start_time": "09:15",
    "no_new_trade_time": "15:00",
    "square_off_time": "15:15",
    "enable_loss_halt": True,
    "enable_sector_filter": False,
    "min_scan_volume": 0,  # MockBroker's synthetic volume is arbitrary; don't gate on it
}


class Orchestrator:
    def __init__(self, broker: Optional[BrokerAdapter] = None, config: Optional[dict] = None):
        self.broker = broker or MockBroker()
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.execution = ExecutionEngine(self.broker)
        self.risk = RiskManager(self.config)
        self.open_positions: dict = {}
        self.trade_history: list = []
        self.daily_pnl: float = 0.0

    def _capital(self) -> float:
        funds = self.execution.get_funds_and_margin()
        if funds and funds.get("status") == "success":
            eq = funds["data"]["equity"]
            return float(eq.get("available_margin", 0)) + float(eq.get("used_margin", 0))
        return self.config["capital"]

    def _total_daily_pnl(self) -> float:
        unrealized = sum(p.get("pnl", 0.0) for p in self.open_positions.values())
        return self.daily_pnl + unrealized

    def tick(self, symbol: str, instrument_key: str, now: datetime) -> None:
        """One symbol's worth of the per-tick loop body (Section 3 pseudocode)."""
        candles = self.execution.get_candles(instrument_key, self.config["timeframe"])
        if not candles or len(candles) < 30:
            return

        if symbol in self.open_positions:
            self._manage_position(symbol, now)
            return

        regime = detect_market_regime(candles)
        htf_trend = get_htf_trend(candles)  # standalone mode has no separate HTF series
        time_bucket = jsonl_logger.time_of_day_bucket(now)

        # Lane A (Section 5A): bias strategy priority toward whichever base strategy has the
        # best recency-weighted expectancy for this exact (regime, time_bucket) combo, once
        # enough samples exist — falls back to select_best_strategy's static regime-priority
        # order (strategy_order=None) otherwise. This only changes WHICH validated strategy
        # runs, never strategy code (Section 0 rule 5).
        min_samples = self.config.get("min_samples_per_combo", 15)
        strategy_order = leaderboard.get_strategy_order_for(regime, time_bucket, min_samples=min_samples)

        signal = select_best_strategy(candles, htf_candles=None, strategy_order=strategy_order, config=self.config)
        if not signal:
            jsonl_logger.log_decision("skip", symbol, "No strategy fired", {"regime": regime, "time_bucket": time_bucket})
            return
        reason = leaderboard.explain_pick(regime, time_bucket, signal.get("strategy", ""), min_samples=min_samples)
        jsonl_logger.log_decision("pick", symbol, reason, {"regime": regime, "time_bucket": time_bucket, "strategy": signal.get("strategy")})

        decision = self.risk.size_and_check(
            symbol=symbol,
            entry_price=signal["entry_price"],
            stop_loss=signal["stop_loss"],
            capital=self._capital(),
            total_pnl_today=self._total_daily_pnl(),
            weekly_pnl=0.0,
            open_positions=self.open_positions,
            trade_history=self.trade_history,
            now=now,
            paper_trading=(self.config.get("mode", "paper") != "live"),
        )
        if not decision.allowed:
            jsonl_logger.log_decision("skip", symbol, decision.reason, {"strategy": signal.get("strategy")})
            return

        direction = "LONG" if "Buy" in signal["strategy"] else "SHORT"
        order = self.execution.place_entry(symbol, direction, decision.qty, "MARKET", 0.0, instrument_key=instrument_key)
        self.open_positions[symbol] = {
            "symbol": symbol, "instrument_key": instrument_key, "strategy": signal["strategy"],
            "direction": direction, "quantity": decision.qty, "entry_price": order["price"],
            "entry_time": now.isoformat(), "stop_loss": signal["stop_loss"],
            "target": signal["target_1"], "target_2": signal.get("target_2", signal["target_1"]),
            "current_price": order["price"], "pnl": 0.0, "atr_at_entry": signal.get("atr"),
            "regime": regime, "htf_trend": htf_trend, "market_context": signal.get("market_context", {}),
        }
        jsonl_logger.log_decision("trade", symbol, "Entered", {"strategy": signal["strategy"], "quantity": decision.qty})

    def _manage_position(self, symbol: str, now: datetime) -> None:
        pos = self.open_positions[symbol]
        quote = self.execution.get_quote(pos["instrument_key"])
        if not quote:
            return
        ltp = quote["ltp"]
        pos["current_price"] = ltp
        pos["pnl"] = (
            (ltp - pos["entry_price"]) * pos["quantity"] if pos["direction"] == "LONG"
            else (pos["entry_price"] - ltp) * pos["quantity"]
        )

        exit_reason = None
        if self.risk.is_past_square_off(now):
            exit_reason = "AUTO SQUARE-OFF"
        elif pos["direction"] == "LONG":
            if ltp >= pos["target"]:
                exit_reason = "TARGET-2 HIT"
            elif ltp <= pos["stop_loss"]:
                exit_reason = "STOP LOSS"
        else:
            if ltp <= pos["target"]:
                exit_reason = "TARGET-2 HIT"
            elif ltp >= pos["stop_loss"]:
                exit_reason = "STOP LOSS"

        if exit_reason:
            self._close_position(symbol, ltp, exit_reason, now)

    def _close_position(self, symbol: str, exit_price: float, reason: str, now: datetime) -> None:
        pos = self.open_positions.pop(symbol)
        self.execution.place_exit(symbol, pos["direction"], pos["quantity"], instrument_key=pos["instrument_key"])
        pnl = (
            (exit_price - pos["entry_price"]) * pos["quantity"] if pos["direction"] == "LONG"
            else (pos["entry_price"] - exit_price) * pos["quantity"]
        )
        self.daily_pnl += pnl
        record = {
            "symbol": symbol, "strategy": pos["strategy"], "direction": pos["direction"],
            "quantity": pos["quantity"], "entry_price": pos["entry_price"], "entry_time": pos["entry_time"],
            "exit_price": exit_price, "exit_time": now.isoformat(), "pnl": round(pnl, 2), "reason": reason,
            "regime": pos.get("regime", "unknown"), "atr_at_entry": pos.get("atr_at_entry"),
            "market_context": pos.get("market_context", {}),
        }
        self.trade_history.append(record)
        jsonl_logger.log_trade(record, mode=("paper" if self.config.get("mode", "paper") != "live" else "live"))
        jsonl_logger.log_decision("trade", symbol, f"Closed ({reason})", {"pnl": round(pnl, 2)})

    def ensure_flat(self, now: datetime) -> None:
        reason = self.risk.ensure_flat_reason(now)
        for symbol in list(self.open_positions.keys()):
            pos = self.open_positions[symbol]
            self._close_position(symbol, pos.get("current_price", pos["entry_price"]), reason, now)

    def run_end_of_day(self, now: Optional[datetime] = None) -> dict:
        """Section 3's run_end_of_day: rebuild the Lane-A leaderboard from the day's closed
        trades and freeze the Section-6 daily history snapshots (leaderboard / pattern / feature
        / KPI) so the date-range and as-of-date views can reconstruct this day exactly (DoD #9)."""
        now = now or datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        stats = leaderboard.rebuild(config=self.config)
        snap = history.write_all(date_str, capital_start=self.config.get("capital"), stats=stats)
        # Lane B (gated inside llm_engine — heuristic/no-spend unless llm_enabled): lessons +
        # one parked proposal + Promotion-Gate evaluation. Never trades or self-modifies live.
        day_trades = history.trades_in_range(history.load_all_trades(), date_str, date_str)
        snap["lane_b"] = lane_b.run_eod(date_str, day_trades, self.config)
        return snap

    def run_tick_for_all_symbols(self, now: Optional[datetime] = None) -> None:
        now = now or datetime.now()
        # RiskManager's daily-loss gate keys off `paper_trading` (paper = intentionally
        # unlimited, matching the dashboard's "Unlimited (Paper Trading)"), but this config
        # speaks `mode` — translate explicitly, exactly like the size_and_check call in
        # tick() does, or the kill switch silently never fires (found via the freeze-path
        # regression test below in test_orchestrator.py).
        is_paper = self.config.get("mode", "paper") != "live"
        frozen, reason = self.risk.is_frozen(self._total_daily_pnl(), paper_trading=is_paper)
        if frozen:
            if self.open_positions:
                jsonl_logger.log_decision("skip", "ALL", reason, {"gate": "kill_switch"})
            self.ensure_flat(now)
            return
        if self.risk.is_past_square_off(now):
            self.ensure_flat(now)
            return
        for symbol in self.config["symbols"]:
            self.tick(symbol, instrument_key=symbol, now=now)
        # Marks were just refreshed by the per-symbol pass — re-evaluate the kill switch so a
        # breach discovered THIS tick flattens now rather than one full tick later (position
        # P&L is only updated inside _manage_position, so the top-of-tick check always sees
        # last tick's marks).
        frozen, reason = self.risk.is_frozen(self._total_daily_pnl(), paper_trading=is_paper)
        if frozen and self.open_positions:
            jsonl_logger.log_decision("skip", "ALL", reason, {"gate": "kill_switch"})
            self.ensure_flat(now)


def run(iterations: int = 50, sleep_sec: float = 0.0) -> Orchestrator:
    """Standalone entry point (`python orchestrator.py`): runs the loop in paper mode against
    MockBroker with zero live credentials, satisfying DoD #1/#2 end to end."""
    orch = Orchestrator()
    session_now = datetime.now().replace(hour=11, minute=0, second=0, microsecond=0)
    for _ in range(iterations):
        orch.run_tick_for_all_symbols(now=session_now)
        if sleep_sec:
            time.sleep(sleep_sec)
    snap = orch.run_end_of_day(now=session_now)
    print(
        f"Orchestrator standalone run complete: {len(orch.trade_history)} trades closed, "
        f"daily P&L Rs.{orch.daily_pnl:.2f}; history snapshot written for {snap['date']} "
        f"({snap['trades_counted']} trades)."
    )
    return orch


if __name__ == "__main__":
    run()
