"""Phase 8: history / learning-analytics API (Section 6 data → Section 8 UI).

Moved from main.py. These expose the daily learning-history snapshots (history.py) plus the
Section-6 trade log to the frontend, so the global date-range selector, as-of-date
reconstruction and compare mode have a backend to read from. All range params are inclusive
ISO dates (YYYY-MM-DD); omit them for "all time". mode is paper | live | combined
(default combined).

main.py must call `configure(...)` before including this router: /api/history/rebuild needs
the IST clock and the live client config, which main owns.
"""

import os
from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, HTTPException

import history
import jsonl_logger
import leaderboard

router = APIRouter(tags=["history"])

_get_now: Callable[[], datetime] | None = None
_get_config: Callable[[], dict] | None = None


def configure(get_now: Callable[[], datetime], get_config: Callable[[], dict]) -> None:
    global _get_now, _get_config
    _get_now = get_now
    _get_config = get_config


def _filter_schema_trades(rows, mode=None, symbol=None, strategy=None):
    """Shared filter for Section-6 wins/losses rows: mode (paper/live/combined), symbol and
    strategy. symbol/strategy match either the exact stored value or a case-insensitive
    substring (so 'RELIANCE' matches 'NSE:RELIANCE', 'ORB' matches 'ORB-Buy')."""
    out = []
    for r in rows:
        if mode and mode != "combined" and r.get("mode") != mode:
            continue
        if symbol:
            s = str(r.get("symbol", "")).upper()
            if symbol.upper() not in s:
                continue
        if strategy:
            st = str(r.get("strategy", "")).upper()
            base = leaderboard.base_strategy_name(r.get("strategy", "")).upper()
            if strategy.upper() not in st and strategy.upper() not in base:
                continue
        out.append(r)
    return out


@router.get("/api/history/dates")
def history_dates():
    """Dates for which an end-of-day snapshot exists (drives the as-of date picker)."""
    return {"dates": history.list_snapshot_dates()}


@router.get("/api/history/kpi")
def history_kpi(start: str | None = None, end: str | None = None):
    """Per-day KPI rows in range — equity/trend charts + calendar heatmap (Tab 8)."""
    try:
        return history.load_kpi_daily(start, end)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/history/patterns")
def history_patterns(start: str | None = None, end: str | None = None):
    """Per-candlestick-pattern per-day reliability rows in range (Tab 4)."""
    try:
        return history.load_pattern_stats(start, end)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/history/features")
def history_features(start: str | None = None, end: str | None = None, dimension: str | None = None):
    """Feature/condition bucket rows in range (Tab 5); optionally filter to one dimension
    (rsi | volume_ratio | atr_pct | time_of_day | regime | symbol)."""
    try:
        rows = history.load_feature_stats(start, end)
        if dimension:
            rows = [r for r in rows if r.get("dimension") == dimension]
        return rows
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/history/leaderboard")
def history_leaderboard(as_of: str | None = None):
    """Strategy leaderboard. With as_of=YYYY-MM-DD, reconstructs it exactly as it stood at that
    day's close (or the latest prior snapshot). Without as_of, returns the current live stats."""
    try:
        if as_of:
            snap = history.load_leaderboard_asof(as_of)
            if snap is None:
                return {"as_of": as_of, "leaderboard": {}, "resolved_from": None}
            return {"as_of": as_of, "leaderboard": snap.get("leaderboard", {}), "resolved_from": snap.get("snapshot_date")}
        return {"as_of": None, "leaderboard": leaderboard.load_stats(), "resolved_from": "live"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/history/leaderboard/series")
def history_leaderboard_series(start: str | None = None, end: str | None = None):
    """Per-day leaderboard snapshots across a range — the 'watch it learn / rank over time'
    data source (Tab 3). One entry per snapshot date with that day's full leaderboard."""
    try:
        series = []
        for d in history.list_snapshot_dates():
            if (start and d < start) or (end and d > end):
                continue
            snap = history.load_leaderboard_asof(d)
            if snap:
                series.append({"date": d, "leaderboard": snap.get("leaderboard", {})})
        return series
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/history/trades")
def history_trades(start: str | None = None, end: str | None = None, mode: str | None = None, symbol: str | None = None, strategy: str | None = None):
    """Full Section-6 schema closed trades (wins + losses) in range, with mode/symbol/strategy
    filters — the drillable Trades tab source (Tab 2), carrying r_multiple, candlestick_patterns,
    indicators_at_entry, lesson, tags, etc."""
    try:
        rows = history.load_all_trades()
        rows = history.trades_in_range(rows, start, end)
        rows = _filter_schema_trades(rows, mode=mode, symbol=symbol, strategy=strategy)
        rows.sort(key=lambda t: t.get("timestamp_exit") or "", reverse=True)
        return rows
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/history/summary")
def history_summary(start: str | None = None, end: str | None = None, mode: str | None = None, symbol: str | None = None, strategy: str | None = None):
    """Aggregate KPI cards for a range + filter set (Tab 8 'KPI cards for the range')."""
    try:
        rows = history.load_all_trades()
        rows = history.trades_in_range(rows, start, end)
        rows = _filter_schema_trades(rows, mode=mode, symbol=symbol, strategy=strategy)
        return history.summarize(rows)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/history/compare")
def history_compare(a_start: str | None = None, a_end: str | None = None, b_start: str | None = None, b_end: str | None = None,
                    mode: str | None = None, symbol: str | None = None, strategy: str | None = None):
    """Compare mode: side-by-side aggregate metrics for two ranges + their deltas, so the UI can
    show how the bot improved between them."""
    try:
        all_rows = history.load_all_trades()

        def _agg(s, e):
            r = _filter_schema_trades(history.trades_in_range(all_rows, s, e), mode=mode, symbol=symbol, strategy=strategy)
            return history.summarize(r)

        a = _agg(a_start, a_end)
        b = _agg(b_start, b_end)
        numeric = ("trades", "win_rate", "expectancy", "net_pnl", "max_drawdown", "avg_r")
        delta = {}
        for k in numeric:
            av, bv = a.get(k), b.get(k)
            if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                delta[k] = round(bv - av, 4)
        return {"a": {"range": [a_start, a_end], "metrics": a},
                "b": {"range": [b_start, b_end], "metrics": b},
                "delta": delta}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/decisions")
def get_decisions(limit: int = 200):
    """Tail of data/decisions.log — the live pick/skip/trade decision stream (Tab 1) with reasons
    (Section 0 rule 7: nothing silent)."""
    try:
        rows = jsonl_logger.read_jsonl(jsonl_logger.DECISIONS_FILE, limit=limit)
        rows.reverse()  # newest first
        return rows
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/llm-calls")
def get_llm_calls(limit: int = 100):
    """Tail of data/llm_calls.jsonl — the Claude lesson/proposal reasoning log (Tab 6). Returns
    [] until Lane B (Phase 7) begins writing it."""
    try:
        path = os.path.join(jsonl_logger.DATA_DIR, "llm_calls.jsonl")
        rows = jsonl_logger.read_jsonl(path, limit=limit)
        rows.reverse()
        return rows
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/history/rebuild")
def history_rebuild(req: dict | None = None):
    """Tab-9 safe control: re-run end-of-day learning (leaderboard rebuild + history snapshots)
    for a chosen date (default: today). Idempotent per date. Does NOT trade or self-modify code."""
    try:
        req = req or {}
        cfg = _get_config() if _get_config else {}
        date_str = req.get("date") or (_get_now() if _get_now else datetime.now()).strftime("%Y-%m-%d")
        stats = leaderboard.rebuild(config=cfg)
        snap = history.write_all(date_str, capital_start=cfg.get("capital", 100000), stats=stats)
        return {"status": "success", "date": snap["date"], "trades_counted": snap["trades_counted"]}
    except Exception as e:
        raise HTTPException(500, str(e))
