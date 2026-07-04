"""
leaderboard.py — Lane A (Section 5A): the safe, auto-applied strategy leaderboard.

Maintains data/strategy_stats.json: for each (strategy, market_regime, time_of_day_bucket)
combination, tracks sample count, win rate, avg R-multiple, expectancy, avg P&L, max drawdown,
avg holding time, and a recency-weighted score (recent trades count more — markets are
non-stationary). This only ever changes WHICH already-validated strategy the selector favors
for current conditions; it never changes strategy code, so it's safe to auto-apply every cycle
(Section 0 rule 5) — distinct from research_lab.py's own `leaderboard` SQL table, which ranks
*candidate/discovered* strategies through the Lane B promotion pipeline, not this per-regime/
time-bucket selection layer over the 8 production strategies.
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict

import jsonl_logger

STATS_FILE = os.path.join("data", "strategy_stats.json")

# Maps directional/variant strategy names (as stored on closed trades) to the base name the
# selector's registry (strategies.py `_REGISTRY`) actually keys on.
NAME_MAP = {
    "ORB-Buy": "ORB", "ORB-Short": "ORB",
    "VWAP-Pullback-Buy": "VWAP-Pullback", "VWAP-Pullback-Short": "VWAP-Pullback",
    "Momentum-Buy": "Momentum", "Momentum-Short": "Momentum",
    "MeanReversion-Buy": "MeanReversion", "MeanReversion-Short": "MeanReversion",
    "TrendFollow-Buy": "TrendFollow", "TrendFollow-Short": "TrendFollow",
    "VWAPTrendPullback-Buy": "VWAPTrendPullback", "VWAPTrendPullback-Short": "VWAPTrendPullback",
    "SupportResistance-Breakout-Buy": "SupportResistance",
    "SupportResistance-Breakout-Short": "SupportResistance",
    "SupportResistance-Rejection-Buy": "SupportResistance",
    "SupportResistance-Rejection-Short": "SupportResistance",
    "CandlestickConfluence-Buy": "CandlestickConfluence",
    "CandlestickConfluence-Short": "CandlestickConfluence",
}


def base_strategy_name(raw_name: str) -> str:
    return NAME_MAP.get(raw_name, raw_name)


def _recency_weight(index_from_end: int, halflife: int) -> float:
    """index_from_end=0 is the most recent trade. Exponential decay so recent trades count
    more than older ones — `halflife` trades back, the weight is 0.5."""
    if halflife <= 0:
        return 1.0
    return math.pow(0.5, index_from_end / halflife)


def compute_stats(trades: list, halflife: int = 40) -> dict:
    """`trades`: Section-6-schema trade dicts. Order doesn't need to be pre-sorted — this sorts
    by exit time itself so recency weighting is always correct regardless of input order.
    Returns {combo_key: stats_dict} where combo_key = "strategy|regime|time_bucket"."""
    ordered = sorted(trades, key=lambda t: t.get("timestamp_exit") or "")
    groups = defaultdict(list)
    for t in ordered:
        strategy = base_strategy_name(t.get("strategy", "unknown"))
        regime = t.get("market_regime", "unknown")
        bucket = t.get("time_of_day_bucket", "unknown")
        groups[f"{strategy}|{regime}|{bucket}"].append(t)

    stats = {}
    for key, group_trades in groups.items():
        n = len(group_trades)
        wins = [t for t in group_trades if t.get("pnl", 0) >= 0]
        losses = [t for t in group_trades if t.get("pnl", 0) < 0]
        win_rate = len(wins) / n if n else 0.0
        avg_r = sum((t.get("r_multiple") or 0.0) for t in group_trades) / n if n else 0.0
        avg_pnl = sum(t.get("pnl", 0.0) for t in group_trades) / n if n else 0.0
        avg_win = sum(t.get("pnl", 0.0) for t in wins) / len(wins) if wins else 0.0
        avg_loss = sum(t.get("pnl", 0.0) for t in losses) / len(losses) if losses else 0.0
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
        holding = [t.get("holding_minutes") for t in group_trades if t.get("holding_minutes") is not None]
        avg_holding = (sum(holding) / len(holding)) if holding else None

        # Simple running peak-to-trough max drawdown within this combo's own trade sequence.
        cum, peak, max_dd = 0.0, 0.0, 0.0
        for t in group_trades:
            cum += t.get("pnl", 0.0)
            peak = max(peak, cum)
            max_dd = min(max_dd, cum - peak)

        weighted_sum, weight_total = 0.0, 0.0
        for i, t in enumerate(reversed(group_trades)):
            w = _recency_weight(i, halflife)
            weighted_sum += w * t.get("pnl", 0.0)
            weight_total += w
        recency_weighted_score = (weighted_sum / weight_total) if weight_total else 0.0

        strategy, regime, bucket = key.split("|", 2)
        stats[key] = {
            "strategy": strategy,
            "market_regime": regime,
            "time_of_day_bucket": bucket,
            "trades": n,
            "win_rate": round(win_rate, 4),
            "avg_r_multiple": round(avg_r, 3),
            "expectancy": round(expectancy, 2),
            "avg_pnl": round(avg_pnl, 2),
            "max_drawdown": round(max_dd, 2),
            "avg_holding_minutes": round(avg_holding, 1) if avg_holding is not None else None,
            "recency_weighted_score": round(recency_weighted_score, 2),
        }
    return stats


def rebuild(halflife: int | None = None, config: dict | None = None) -> dict:
    """Reads wins.jsonl + losses.jsonl fresh and rewrites data/strategy_stats.json. Called both
    intraday (Section 3's time_for_intraday_learning()) and at EOD."""
    halflife = halflife if halflife is not None else (config or {}).get("recency_halflife_trades", 40)
    trades = jsonl_logger.read_jsonl(jsonl_logger.WINS_FILE) + jsonl_logger.read_jsonl(jsonl_logger.LOSSES_FILE)
    stats = compute_stats(trades, halflife=halflife)
    os.makedirs(os.path.dirname(STATS_FILE) or ".", exist_ok=True)
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    return stats


def load_stats() -> dict:
    if not os.path.exists(STATS_FILE):
        return {}
    with open(STATS_FILE, encoding="utf-8") as f:
        return json.load(f)


def get_strategy_order_for(
    regime: str,
    time_bucket: str,
    min_samples: int = 15,
    stats: dict | None = None,
) -> list | None:
    """Returns base strategy names ranked by recency-weighted expectancy for this (regime,
    time_bucket), restricted to combos with >= min_samples trades (Section 5A's minimum-sample
    fallback rule). Returns None if no combo yet qualifies — the caller should fall back to
    select_best_strategy's static regime-priority order in that case."""
    stats = stats if stats is not None else load_stats()
    candidates = [
        s for s in stats.values()
        if s["market_regime"] == regime and s["time_of_day_bucket"] == time_bucket and s["trades"] >= min_samples
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda s: s["recency_weighted_score"], reverse=True)
    return [c["strategy"] for c in candidates]


def explain_pick(
    regime: str,
    time_bucket: str,
    chosen_strategy: str,
    min_samples: int = 15,
    stats: dict | None = None,
) -> str:
    """Human-readable reasoning string for data/decisions.log and the UI's selector-reasoning
    panel (Section 8 Tab 1: 'the selector's reasoning and the compared scores it chose from')."""
    stats = stats if stats is not None else load_stats()
    base = base_strategy_name(chosen_strategy)
    combo = stats.get(f"{base}|{regime}|{time_bucket}")
    if combo and combo["trades"] >= min_samples:
        return (
            f"{base} picked for {regime}/{time_bucket}: recency-weighted score "
            f"{combo['recency_weighted_score']:.1f} over {combo['trades']} trades "
            f"(win rate {combo['win_rate'] * 100:.0f}%, expectancy Rs.{combo['expectancy']:.1f})."
        )
    return (
        f"{base} picked for {regime}/{time_bucket}: insufficient samples (<{min_samples}) "
        f"for this combo yet — falling back to the default regime-priority order."
    )
