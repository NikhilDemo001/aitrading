"""
history.py — Section 6's daily learning-history snapshots (the linchpin the whole date-range /
as-of-date / compare UI reads from).

A file that gets overwritten cannot show evolution, so every EOD we snapshot the state of the
bot's "learned brain" as it stood at the end of that day, append-only / date-stamped, so any
past day can be reconstructed exactly:

  data/history/leaderboard_YYYY-MM-DD.json  — full Lane-A leaderboard as it stood that EOD
  data/history/pattern_stats.jsonl          — per candlestick pattern per day
  data/history/feature_stats.jsonl          — outcome stats bucketed by indicator range /
                                              time-of-day / regime / symbol, per day
  data/history/kpi_daily.jsonl              — one KPI row per day (trends, calendar heatmap)

Writers are idempotent per snapshot_date: re-running EOD for a date (Tab 9's "re-run end-of-day
learning for a chosen date") replaces that date's rows rather than duplicating them.

Reads: date-range filters return rows whose snapshot_date is in [start, end]; as-of reads return
the latest snapshot on or before the requested date (weekends/holidays produce no snapshot).
"""

from __future__ import annotations

import glob
import json
import math
import os
from collections import defaultdict
from datetime import datetime
from typing import Optional

import jsonl_logger
import leaderboard

PATTERN_STATS_FILE = "pattern_stats.jsonl"
FEATURE_STATS_FILE = "feature_stats.jsonl"
KPI_DAILY_FILE = "kpi_daily.jsonl"


# ── paths (derived from jsonl_logger.DATA_DIR at call time so tests can monkeypatch it) ──

def history_dir() -> str:
    return os.path.join(jsonl_logger.DATA_DIR, "history")


def _ensure_dir() -> None:
    os.makedirs(history_dir(), exist_ok=True)


def _path(name: str) -> str:
    return os.path.join(history_dir(), name)


def leaderboard_path(date_str: str) -> str:
    return _path(f"leaderboard_{date_str}.json")


# ── helpers ──────────────────────────────────────────────────────────────────────────

def _exit_date(trade: dict) -> str:
    return str(trade.get("timestamp_exit") or trade.get("exit_time") or "")[:10]


def trades_for_date(trades: list, date_str: str) -> list:
    return [t for t in trades if _exit_date(t) == date_str]


def _all_closed_trades() -> list:
    return jsonl_logger.read_jsonl(jsonl_logger.WINS_FILE) + jsonl_logger.read_jsonl(jsonl_logger.LOSSES_FILE)


def _metrics(trades: list) -> dict:
    """Core outcome metrics for any group of Section-6 trade dicts."""
    n = len(trades)
    wins = [t for t in trades if t.get("pnl", 0.0) >= 0]
    losses = [t for t in trades if t.get("pnl", 0.0) < 0]
    win_rate = len(wins) / n if n else 0.0
    gross_profit = sum(t.get("pnl", 0.0) for t in wins)
    gross_loss = sum(t.get("pnl", 0.0) for t in losses)  # <= 0
    net_pnl = gross_profit + gross_loss
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
    # profit_factor: None when there are no losing trades (UI renders as ∞) rather than dividing
    # by zero or fabricating a misleading finite number.
    profit_factor = round(gross_profit / abs(gross_loss), 3) if gross_loss < 0 else None
    r_vals = [t.get("r_multiple") for t in trades if t.get("r_multiple") is not None]
    avg_r = round(sum(r_vals) / len(r_vals), 3) if r_vals else 0.0
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 4),
        "avg_r": avg_r,
        "expectancy": round(expectancy, 2),
        "gross_pnl": round(gross_profit + gross_loss, 2),
        "net_pnl": round(net_pnl, 2),
        "profit_factor": profit_factor,
    }


def _max_drawdown(trades: list) -> float:
    """Running peak-to-trough of cumulative P&L over the trade sequence (ordered by exit time)."""
    ordered = sorted(trades, key=lambda t: t.get("timestamp_exit") or t.get("exit_time") or "")
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for t in ordered:
        cum += t.get("pnl", 0.0)
        peak = max(peak, cum)
        max_dd = min(max_dd, cum - peak)
    return round(max_dd, 2)


def _band(value: Optional[float], edges: list, labels: list) -> Optional[str]:
    """Maps a numeric value into a labeled band. len(labels) must be len(edges)+1."""
    if value is None:
        return None
    for i, edge in enumerate(edges):
        if value < edge:
            return labels[i]
    return labels[-1]


def _rewrite_replacing_date(path: str, date_str: str, new_rows: list) -> None:
    """Idempotent append: drop any existing rows for this snapshot_date, then write new ones.
    Keeps the file append-only in spirit (one block per day) while making EOD re-runs safe."""
    _ensure_dir()
    existing = jsonl_logger.read_jsonl(path) if os.path.exists(path) else []
    kept = [r for r in existing if r.get("snapshot_date") != date_str]
    with open(path, "w", encoding="utf-8") as f:
        for r in kept + new_rows:
            f.write(json.dumps(r) + "\n")


# ── writers ──────────────────────────────────────────────────────────────────────────

def snapshot_leaderboard(date_str: str, stats: Optional[dict] = None) -> dict:
    """Freezes the full Lane-A leaderboard as it stood at the end of `date_str`. Overwriting the
    same date's file is naturally idempotent."""
    _ensure_dir()
    stats = stats if stats is not None else leaderboard.load_stats()
    payload = {
        "snapshot_date": date_str,
        "generated_at": datetime.now().isoformat(),
        "leaderboard": stats,
    }
    with open(leaderboard_path(date_str), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return payload


def snapshot_pattern_stats(date_str: str, day_trades: list) -> list:
    """Per candlestick pattern, for trades that closed on `date_str`: occurrences, win rate,
    avg R, expectancy — so the UI shows which patterns the bot learned to trust vs avoid."""
    by_pattern = defaultdict(list)
    for t in day_trades:
        for pat in (t.get("candlestick_patterns") or []):
            if pat:
                by_pattern[pat].append(t)
    rows = []
    for pattern, trades in sorted(by_pattern.items()):
        m = _metrics(trades)
        rows.append({
            "snapshot_date": date_str,
            "pattern": pattern,
            "occurrences": m["trades"],
            "wins": m["wins"],
            "win_rate": m["win_rate"],
            "avg_r": m["avg_r"],
            "expectancy": m["expectancy"],
            "net_pnl": m["net_pnl"],
        })
    _rewrite_replacing_date(_path(PATTERN_STATS_FILE), date_str, rows)
    return rows


# (dimension, extractor, edges, labels) for the indicator-range buckets.
_RSI_EDGES = [30, 40, 50, 60, 70]
_RSI_LABELS = ["<30", "30-40", "40-50", "50-60", "60-70", ">70"]
_VOL_EDGES = [1.0, 1.5, 2.0]
_VOL_LABELS = ["<1.0", "1.0-1.5", "1.5-2.0", ">2.0"]
_ATR_EDGES = [0.5, 1.0, 1.5]
_ATR_LABELS = ["<0.5%", "0.5-1%", "1-1.5%", ">1.5%"]


def _feature_bucket(trade: dict, dimension: str) -> Optional[str]:
    ind = trade.get("indicators_at_entry") or {}
    if dimension == "rsi":
        return _band(ind.get("rsi"), _RSI_EDGES, _RSI_LABELS)
    if dimension == "volume_ratio":
        return _band(ind.get("volume_ratio"), _VOL_EDGES, _VOL_LABELS)
    if dimension == "atr_pct":
        atr_pct = ind.get("atr_pct")
        if atr_pct is None and ind.get("atr") and ind.get("ema_20"):
            try:
                atr_pct = (ind["atr"] / ind["ema_20"]) * 100
            except (TypeError, ZeroDivisionError):
                atr_pct = None
        return _band(atr_pct, _ATR_EDGES, _ATR_LABELS)
    if dimension == "time_of_day":
        return trade.get("time_of_day_bucket")
    if dimension == "regime":
        return trade.get("market_regime")
    if dimension == "symbol":
        return trade.get("symbol")
    return None


FEATURE_DIMENSIONS = ["rsi", "volume_ratio", "atr_pct", "time_of_day", "regime", "symbol"]


def snapshot_feature_stats(date_str: str, day_trades: list) -> list:
    """Win rate & expectancy bucketed by RSI / volume-ratio / ATR% range, plus time-of-day,
    regime and symbol — for trades that closed on `date_str` (Section 8 Tab 5)."""
    rows = []
    for dimension in FEATURE_DIMENSIONS:
        by_bucket = defaultdict(list)
        for t in day_trades:
            bucket = _feature_bucket(t, dimension)
            if bucket is not None:
                by_bucket[bucket].append(t)
        for bucket, trades in by_bucket.items():
            m = _metrics(trades)
            rows.append({
                "snapshot_date": date_str,
                "dimension": dimension,
                "bucket": bucket,
                "trades": m["trades"],
                "win_rate": m["win_rate"],
                "avg_r": m["avg_r"],
                "expectancy": m["expectancy"],
                "net_pnl": m["net_pnl"],
            })
    _rewrite_replacing_date(_path(FEATURE_STATS_FILE), date_str, rows)
    return rows


def snapshot_kpi_daily(
    date_str: str,
    day_trades: list,
    capital_start: Optional[float] = None,
) -> dict:
    """One KPI row for `date_str`: trades, win rate, expectancy, profit factor, max drawdown,
    net P&L, equity — powering the cumulative/trend charts and the calendar heatmap (Tab 8)."""
    m = _metrics(day_trades)
    pnls = [t.get("pnl", 0.0) for t in day_trades]
    holds = [t.get("holding_minutes") for t in day_trades if t.get("holding_minutes") is not None]
    equity_end = round((capital_start or 0.0) + m["net_pnl"], 2) if capital_start is not None else None
    row = {
        "snapshot_date": date_str,
        "trades": m["trades"],
        "wins": m["wins"],
        "losses": m["losses"],
        "win_rate": m["win_rate"],
        "expectancy": m["expectancy"],
        "profit_factor": m["profit_factor"],
        "gross_pnl": m["gross_pnl"],
        "net_pnl": m["net_pnl"],
        "max_drawdown": _max_drawdown(day_trades),
        "avg_holding_minutes": round(sum(holds) / len(holds), 1) if holds else None,
        "best_trade": round(max(pnls), 2) if pnls else 0.0,
        "worst_trade": round(min(pnls), 2) if pnls else 0.0,
        "capital_start": capital_start,
        "equity": equity_end,
    }
    _rewrite_replacing_date(_path(KPI_DAILY_FILE), date_str, [row])
    return row


def write_all(
    date_str: Optional[str] = None,
    capital_start: Optional[float] = None,
    stats: Optional[dict] = None,
) -> dict:
    """EOD convenience: snapshot all four history artifacts for `date_str` (default: today).
    Reads closed trades from wins.jsonl/losses.jsonl and filters to the given date. Called from
    run_end_of_day (and re-runnable for any past date from Tab 9)."""
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    all_trades = _all_closed_trades()
    day_trades = trades_for_date(all_trades, date_str)
    return {
        "date": date_str,
        "leaderboard": snapshot_leaderboard(date_str, stats=stats),
        "pattern_stats": snapshot_pattern_stats(date_str, day_trades),
        "feature_stats": snapshot_feature_stats(date_str, day_trades),
        "kpi_daily": snapshot_kpi_daily(date_str, day_trades, capital_start=capital_start),
        "trades_counted": len(day_trades),
    }


# ── readers (for the Phase-8 API / date-range + as-of UI) ──────────────────────────────

def list_snapshot_dates() -> list:
    """Sorted list of dates for which a leaderboard snapshot exists."""
    prefix = _path("leaderboard_")
    dates = []
    for p in glob.glob(prefix + "*.json"):
        stem = os.path.basename(p)[len("leaderboard_"):-len(".json")]
        dates.append(stem)
    return sorted(dates)


def load_leaderboard_asof(date_str: str) -> Optional[dict]:
    """Leaderboard exactly as it stood at EOD on `date_str`, or the most recent prior snapshot
    if that exact date has none (weekend/holiday) — so 'as-of' always resolves to what the bot
    actually knew on or before that day."""
    exact = leaderboard_path(date_str)
    if os.path.exists(exact):
        with open(exact, encoding="utf-8") as f:
            return json.load(f)
    prior = [d for d in list_snapshot_dates() if d <= date_str]
    if not prior:
        return None
    with open(leaderboard_path(prior[-1]), encoding="utf-8") as f:
        return json.load(f)


def _load_range(filename: str, start: Optional[str], end: Optional[str]) -> list:
    rows = jsonl_logger.read_jsonl(_path(filename))
    if start is None and end is None:
        return rows
    out = []
    for r in rows:
        d = r.get("snapshot_date", "")
        if (start is None or d >= start) and (end is None or d <= end):
            out.append(r)
    return out


def load_pattern_stats(start: Optional[str] = None, end: Optional[str] = None) -> list:
    return _load_range(PATTERN_STATS_FILE, start, end)


def load_feature_stats(start: Optional[str] = None, end: Optional[str] = None) -> list:
    return _load_range(FEATURE_STATS_FILE, start, end)


def load_kpi_daily(start: Optional[str] = None, end: Optional[str] = None) -> list:
    return sorted(_load_range(KPI_DAILY_FILE, start, end), key=lambda r: r.get("snapshot_date", ""))


# ── range aggregation (for the Tab-8 range KPI cards and compare mode) ──────────────────

def load_all_trades() -> list:
    """All closed Section-6 trades (wins + losses)."""
    return _all_closed_trades()


def trades_in_range(trades: list, start: Optional[str] = None, end: Optional[str] = None) -> list:
    """Filter trades by exit-date inclusive [start, end]."""
    out = []
    for t in trades:
        d = _exit_date(t)
        if (start is None or d >= start) and (end is None or d <= end):
            out.append(t)
    return out


def summarize(trades: list) -> dict:
    """Aggregate KPI summary for an arbitrary set of trades (any date range / filter) — the same
    metric definitions used in the per-day KPI snapshots, so range cards and compare deltas stay
    consistent with the daily rows."""
    m = _metrics(trades)
    pnls = [t.get("pnl", 0.0) for t in trades]
    holds = [t.get("holding_minutes") for t in trades if t.get("holding_minutes") is not None]
    m["max_drawdown"] = _max_drawdown(trades)
    m["best_trade"] = round(max(pnls), 2) if pnls else 0.0
    m["worst_trade"] = round(min(pnls), 2) if pnls else 0.0
    m["avg_holding_minutes"] = round(sum(holds) / len(holds), 1) if holds else None
    return m
