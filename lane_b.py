"""
lane_b.py — the end-of-day Lane-B orchestration both the standalone orchestrator and main.py's
live loop call, so lesson extraction + proposal generation + Promotion-Gate evaluation live in one
place (not duplicated). Everything here is gated inside llm_engine: with llm_enabled off (default)
it runs the heuristic path and spends nothing; it only calls Claude once the operator enables it.

Nothing here trades or self-modifies live code — it writes lessons onto closed-trade records and
parks INACTIVE proposals that must still pass promotion_gate before ever going live.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

import jsonl_logger
import llm_engine
import promotion_gate


def _build_day_context(date_str: str, day_trades: list) -> dict:
    """Aggregate the day into a compact context for the proposal prompt, and surface the worst
    (strategy, regime) combo the heuristic proposer keys on."""
    by_combo = defaultdict(lambda: {"trades": 0, "net_pnl": 0.0})
    total = 0.0
    for t in day_trades:
        strat = t.get("strategy", "unknown")
        regime = t.get("market_regime", "unknown")
        c = by_combo[(strat, regime)]
        c["trades"] += 1
        c["net_pnl"] += t.get("pnl", 0.0)
        total += t.get("pnl", 0.0)
    combos = [
        {"strategy": s, "market_regime": r, "trades": v["trades"], "net_pnl": round(v["net_pnl"], 2)}
        for (s, r), v in by_combo.items()
    ]
    worst = min(combos, key=lambda c: c["net_pnl"], default=None)
    return {
        "date": date_str,
        "total_trades": len(day_trades),
        "net_pnl": round(total, 2),
        "combos": combos,
        "worst_combo": worst if (worst and worst["net_pnl"] < 0) else None,
    }


def run_eod(date_str: str, day_trades: list, config: Optional[dict], client=None) -> dict:
    """1) extract lessons for the day's closed trades and backfill them into wins/losses.jsonl,
    2) generate one INACTIVE proposal from the day's context, 3) re-evaluate every non-terminal
    proposal against the Promotion Gate. Returns a small summary for logging."""
    config = config or {}
    client = client or llm_engine.get_client(config)

    lessons = llm_engine.extract_lessons_for_trades(day_trades, config=config, client=client)
    backfilled = jsonl_logger.backfill_lessons(lessons) if lessons else 0

    ctx = _build_day_context(date_str, day_trades)
    proposal = llm_engine.generate_proposal(ctx, config=config, client=client)
    created = promotion_gate.add_proposal(proposal) if proposal else None

    # Advance the lifecycle of every candidate still in play (safe: without enough evidence they
    # simply stay 'validating'/'proposed'; nothing is promoted to live without passing the gate).
    evaluated = 0
    for p in promotion_gate.load_proposals():
        if p.get("status") not in promotion_gate.TERMINAL:
            promotion_gate.evaluate(p["id"], config)
            evaluated += 1

    return {
        "lessons_written": backfilled,
        "proposal_id": created["id"] if created else None,
        "proposal_source": (proposal or {}).get("source"),
        "proposals_evaluated": evaluated,
        "llm_enabled": llm_engine.is_enabled(config),
    }
