"""
Walk-forward backtester for single-strategy evaluation.
Usage:
    from backtester import run_backtest, generate_backtest_report
    trades, rejected = run_backtest(check_vwap_trend_pullback, candles, config)
    report = generate_backtest_report(trades, "RELIANCE", "2024-01-01 to 2025-01-01")
"""

import math
from datetime import datetime


class _Position:
    """Simulates a live position with ATR trailing stop and T1/T2 partial exits."""

    def __init__(self, signal, max_risk, trailing_mult):
        self.direction      = "LONG" if signal["strategy"].endswith("-Buy") else "SHORT"
        self.entry          = signal["entry_price"]
        self.stop           = signal["stop_loss"]
        self.t1             = signal["target_1"]
        self.t2             = signal["target_2"]
        self.atr            = signal.get("atr", 1.0)
        self.confidence     = signal.get("confidence", 0)
        self.strategy       = signal["strategy"]
        self.trigger_time   = signal.get("trigger_time", "")
        self.trailing_mult  = trailing_mult
        self.risk           = abs(self.entry - self.stop)
        self.t1_hit         = False
        self.t2_hit         = False
        self.best_price     = self.entry
        self.trailing_high  = self.entry
        self.trailing_low   = self.entry

        # size by risk
        self.quantity = max(1, int(max_risk / self.risk)) if self.risk > 0 else 1

    def update(self, candle):
        """Feed next candle; returns 'open' | 't1' | 'stop' | 'target' | 't1_stop'."""
        hi, lo, cl = candle["high"], candle["low"], candle["close"]

        if self.direction == "LONG":
            # Stop check first (using the stop level carried over from the previous candle)
            if lo <= self.stop:
                return "t1_stop" if self.t1_hit else "stop"
            
            # T1 check
            if not self.t1_hit and hi >= self.t1:
                self.t1_hit = True
                if self.stop < self.entry:
                    self.stop = self.entry     # move to BE on T1 hit
                if hi > self.trailing_high:
                    self.trailing_high = hi
                new_trail = self.trailing_high - self.atr * self.trailing_mult
                if new_trail > self.stop:
                    self.stop = new_trail
                return "t1"
            
            # T2 / trailing target
            if self.t1_hit and hi >= self.t2:
                return "target"
            
            # Update peak tracking and trailing stop
            if hi > self.trailing_high:
                self.trailing_high = hi
            new_trail = self.trailing_high - self.atr * self.trailing_mult
            if new_trail > self.stop:
                self.stop = new_trail
        else:
            # Stop check first (using the stop level carried over from the previous candle)
            if hi >= self.stop:
                return "t1_stop" if self.t1_hit else "stop"
            
            # T1 check
            if not self.t1_hit and lo <= self.t1:
                self.t1_hit = True
                if self.stop > self.entry:
                    self.stop = self.entry     # move to BE on T1 hit
                if lo < self.trailing_low:
                    self.trailing_low = lo
                new_trail = self.trailing_low + self.atr * self.trailing_mult
                if new_trail < self.stop:
                    self.stop = new_trail
                return "t1"
            
            # T2 / trailing target
            if self.t1_hit and lo <= self.t2:
                return "target"
            
            # Update valley tracking and trailing stop
            if lo < self.trailing_low:
                self.trailing_low = lo
            new_trail = self.trailing_low + self.atr * self.trailing_mult
            if new_trail < self.stop:
                self.stop = new_trail

        return "open"


def run_backtest(strategy_func, candles, config=None, max_risk=500,
                 trailing_mult=1.5, warmup=30, slippage_pct=0.0,
                 brokerage_flat=None, charge_pct=None):
    """
    Walk-forward simulation.

    Parameters
    ----------
    strategy_func : callable — strategy's check function (candles, *, config, htf_trend)
    candles       : list of OHLCV dicts, ascending
    config        : bot config dict
    max_risk      : max ₹ risk per trade
    trailing_mult : ATR multiplier for trailing stop
    warmup        : minimum candles required before scanning starts
    slippage_pct  : percentage slippage to simulate (e.g. 0.0005 for 0.05%)

    Returns
    -------
    trades   : list of closed trade dicts
    rejected : list of signals that were filtered / skipped
    """
    if config is None:
        config = {}

    # Transaction costs — a backtest that ignores brokerage/taxes overstates edge, because
    # intraday round-trip costs (~₹40 + statutory charges) are a large fraction of a small
    # per-trade risk budget. Defaults mirror the live/paper friction model in research_lab.py.
    if brokerage_flat is None:
        brokerage_flat = float(config.get("backtest_brokerage_flat", 40.0))
    if charge_pct is None:
        charge_pct = float(config.get("backtest_charge_pct", 0.0005))

    trades   = []
    rejected = []
    pos      = None

    for i in range(warmup, len(candles)):
        window = candles[: i + 1]

        # manage open position first
        if pos is not None:
            outcome = pos.update(candles[i])
            if outcome != "open":
                if outcome == "t1":
                    # T1 hit: record 50% partial exit
                    half_qty = pos.quantity // 2
                    if half_qty >= 1:
                        # Record partial exit
                        trades.append(_close_trade(pos, candles[i], pos.t1, "t1_partial", qty=half_qty, slippage_pct=slippage_pct, brokerage_flat=brokerage_flat, charge_pct=charge_pct))
                        pos.quantity -= half_qty
                        # Do not set pos = None; keep it open for Target 2 or Trailing Stop
                    else:
                        # Cannot divide: exit entire position at T1
                        trades.append(_close_trade(pos, candles[i], pos.t1, "target", qty=pos.quantity, slippage_pct=slippage_pct, brokerage_flat=brokerage_flat, charge_pct=charge_pct))
                        pos = None
                else:
                    # Final exit (stop, t1_stop, target, or EOD)
                    exit_price = _exit_price(pos, candles[i], outcome)
                    trades.append(_close_trade(pos, candles[i], exit_price, outcome, qty=pos.quantity, slippage_pct=slippage_pct, brokerage_flat=brokerage_flat, charge_pct=charge_pct))
                    pos = None
            continue

        # scan for entry
        try:
            sig = strategy_func(window, config=config, htf_trend="neutral")
        except Exception:
            sig = None

        if sig is None:
            continue

        # basic validity
        risk = abs(sig["entry_price"] - sig["stop_loss"])
        if risk <= 0:
            rejected.append({**sig, "reject_reason": "zero_risk"})
            continue

        pos = _Position(sig, max_risk, trailing_mult)

    # close any open position at end of data
    if pos and candles:
        last = candles[-1]
        trades.append(_close_trade(pos, last, last["close"], "eod_close", qty=pos.quantity, slippage_pct=slippage_pct, brokerage_flat=brokerage_flat, charge_pct=charge_pct))

    return trades, rejected


def _exit_price(pos, candle, outcome):
    if outcome in ("stop", "t1_stop"):
        return pos.stop
    if outcome == "t1":
        return pos.t1
    if outcome == "target":
        return pos.t2
    return candle["close"]


def _close_trade(pos, candle, exit_price, outcome, qty=None, slippage_pct=0.0,
                 brokerage_flat=40.0, charge_pct=0.0005):
    direction_sign = 1 if pos.direction == "LONG" else -1
    q = qty if qty is not None else pos.quantity

    # Apply entry and exit slippage
    # LONG: entry is higher, exit is lower
    # SHORT: entry is lower, exit is higher
    actual_entry = pos.entry * (1 + slippage_pct) if pos.direction == "LONG" else pos.entry * (1 - slippage_pct)
    actual_exit = exit_price * (1 - slippage_pct) if pos.direction == "LONG" else exit_price * (1 + slippage_pct)

    gross_pnl = (actual_exit - actual_entry) * direction_sign * q

    # Transaction costs on this leg: flat brokerage (round-trip) + statutory charges on
    # turnover (STT/exchange/SEBI/stamp/GST proxy). Slightly conservative on partial-exit
    # legs (each leg bears the flat fee), which is the safe direction for a backtest.
    turnover = (actual_entry + actual_exit) * q
    costs = brokerage_flat + turnover * charge_pct
    net_pnl = gross_pnl - costs

    return {
        "strategy":    pos.strategy,
        "entry":       round(actual_entry, 2),
        "exit":        round(actual_exit, 2),
        "stop":        round(pos.stop, 2),
        "t1":          pos.t1,
        "t2":          pos.t2,
        "direction":   pos.direction,
        "quantity":    q,
        "pnl":         round(net_pnl, 2),
        "gross_pnl":   round(gross_pnl, 2),
        "costs":       round(costs, 2),
        "outcome":     outcome,
        "confidence":  pos.confidence,
        "entry_time":  pos.trigger_time,
        "exit_time":   candle.get("timestamp", ""),
    }


# ── Monthly breakdown ────────────────────────────────────────────────────────

def monthly_breakdown(trades):
    """Groups trades by 'YYYY-MM' and computes per-month stats."""
    months = {}
    for t in trades:
        key = str(t.get("exit_time", ""))[:7]   # 'YYYY-MM'
        if not key or key == "":
            key = "unknown"
        m = months.setdefault(key, {"trades": 0, "wins": 0, "pnl": 0.0})
        m["trades"] += 1
        m["pnl"]    += t["pnl"]
        if t["pnl"] > 0:
            m["wins"] += 1
    return dict(sorted(months.items()))


# ── Summary report ───────────────────────────────────────────────────────────

def generate_backtest_report(trades, symbol, period):
    """
    Computes key statistics and returns a structured report dict.

    Metrics:
      total_trades, win_rate, profit_factor, max_drawdown,
      sharpe_ratio, avg_rr, total_pnl, monthly_breakdown
    """
    if not trades:
        return {
            "symbol": symbol, "period": period,
            "total_trades": 0, "win_rate": 0, "profit_factor": 0,
            "max_drawdown": 0, "sharpe_ratio": 0, "avg_rr": 0,
            "total_pnl": 0, "monthly": {},
        }

    pnls  = [t["pnl"] for t in trades]
    wins  = [p for p in pnls if p > 0]
    losses= [p for p in pnls if p <= 0]

    win_rate = len(wins) / len(trades) * 100

    gross_profit = sum(wins)
    gross_loss   = abs(sum(losses)) if losses else 0
    # Avoid float('inf') — it is not valid JSON and breaks the /api/backtest response.
    pf           = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999.99 if gross_profit > 0 else 0)

    # max drawdown (equity curve peak-to-trough)
    equity  = 0
    peak    = 0
    max_dd  = 0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    # Sharpe (daily, assumes 252 trading days)
    n   = len(pnls)
    mu  = sum(pnls) / n
    var = sum((p - mu) ** 2 for p in pnls) / n
    sd  = math.sqrt(var) if var > 0 else 0
    sharpe = (mu / sd) * math.sqrt(252) if sd > 0 else 0

    # average R:R (reward / risk per trade)
    rr_vals = []
    for t in trades:
        risk = abs(t["entry"] - t["stop"])
        if risk > 0:
            rr_vals.append(abs(t["exit"] - t["entry"]) / risk)
    avg_rr = sum(rr_vals) / len(rr_vals) if rr_vals else 0

    total_costs = sum(t.get("costs", 0.0) for t in trades)
    total_gross = sum(t.get("gross_pnl", t["pnl"]) for t in trades)
    return {
        "symbol":          symbol,
        "period":          period,
        "total_trades":    len(trades),
        "win_rate":        round(win_rate, 1),
        "profit_factor":   pf,
        "max_drawdown":    round(max_dd, 2),
        "sharpe_ratio":    round(sharpe, 2),
        "avg_rr":          round(avg_rr, 2),
        "total_pnl":       round(sum(pnls), 2),   # net of costs
        "gross_pnl":       round(total_gross, 2),
        "total_costs":     round(total_costs, 2),
        "monthly":         monthly_breakdown(trades),
    }
