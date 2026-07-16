"""On-demand, read-only Claude analyst over the bot's own data. No trading/order/config writes.

build_context() assembles a compact JSON snapshot across four domains (live status + positions,
today's trades + P&L, recent decisions, strategy leaderboard + journal). answer() calls Claude
once (budget-gated by the SEPARATE assistant cap) and returns grounded prose. Never raises."""

import json
import llm_engine

MAX_DECISIONS = 40
MAX_TRADES = 60
MAX_HISTORY_TURNS = 6

SYSTEM = (
    "You are the analyst for an operator's OWN intraday trading bot. Answer questions ONLY from "
    "the JSON snapshot of the bot's real data provided below. Rules: (1) Use only the given data; "
    "if it isn't there, say you don't have that data. (2) Never invent numbers. (3) You are "
    "READ-ONLY — you cannot place trades or change settings; if asked to, explain you can only "
    "analyse. (4) Do NOT give buy/sell predictions or financial advice; analyse what the bot did "
    "and why. Be concise, concrete, and cite the numbers from the snapshot. All monetary "
    "amounts are Indian Rupees (₹) — never use $ or other currencies."
)


def assistant_calls_today():
    from datetime import datetime
    rows = llm_engine.jsonl_logger.read_jsonl(llm_engine.llm_calls_path())
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(1 for r in rows if str(r.get("time", "")).startswith(today) and r.get("kind") == "assistant")


def assistant_budget_remaining(config):
    cap = int((config or {}).get("assistant_max_daily_calls", 100))
    return max(0, cap - assistant_calls_today())


def _mentioned_symbols(question, known_symbols):
    q = (question or "").upper()
    return [s for s in (known_symbols or []) if s and s.upper() in q]


def build_context(question, *, status, positions, today_trades, decisions,
                  strategy_stats=None, known_symbols=None):
    trades = list(today_trades or [])[-MAX_TRADES:]
    # Shadow trades are simulated learning-only fills; the bot's status daily_pnl counts ONLY
    # real ones. Summing both into one number made the model report a false discrepancy, so
    # keep them separate and label them.
    real_trades = [t for t in trades if not t.get("is_shadow_trade")]
    shadow_trades = [t for t in trades if t.get("is_shadow_trade")]
    today_pnl = round(sum(float(t.get("pnl") or 0) for t in real_trades), 2)
    shadow_pnl = round(sum(float(t.get("pnl") or 0) for t in shadow_trades), 2)
    focus = _mentioned_symbols(question, known_symbols)
    snap = {
        "status": {k: (status or {}).get(k) for k in
                   ("paper_trading", "bot_running", "open_positions_count", "daily_pnl",
                    "scanner_last_summary", "scanner_last_loop")},
        "open_positions": positions or [],
        "today_trades": trades,
        "today_pnl": today_pnl,
        "today_pnl_note": ("today_pnl is REAL trades only and should reconcile with "
                           "status.daily_pnl; shadow trades are simulated and excluded."),
        "real_trade_count": len(real_trades),
        "shadow_trade_count": len(shadow_trades),
        "shadow_pnl": shadow_pnl,
        "recent_decisions": list(decisions or [])[-MAX_DECISIONS:],
        # Lane-A stats, built from REAL closed trades (regime/time-bucket -> strategy record).
        "strategy_stats": strategy_stats or {},
        "focus_symbols": focus,
    }
    if focus:
        snap["symbol_decisions"] = [d for d in (decisions or []) if d.get("symbol") in focus]
        snap["symbol_trades"] = [t for t in (today_trades or []) if t.get("symbol") in focus]
    return snap


def _prompt(question, history, snapshot):
    turns = ""
    for m in list(history or [])[-MAX_HISTORY_TURNS:]:
        role = "You" if m.get("role") == "assistant" else "Operator"
        turns += f"{role}: {m.get('content', '')}\n"
    convo = ("CONVERSATION SO FAR:\n" + turns + "\n") if turns else ""
    return (f"BOT DATA SNAPSHOT (JSON):\n{json.dumps(snapshot, default=str)}\n\n"
            f"{convo}OPERATOR QUESTION: {question}")


def answer(question, history, snapshot, config, client=None):
    config = config or {}
    if assistant_budget_remaining(config) <= 0:
        return {"answer": "Assistant unavailable: daily question budget reached. It resets tomorrow.",
                "source": "unavailable"}
    if client is None:
        model = config.get("assistant_model") or config.get("llm_model")
        # 4000 leaves room for claude-sonnet-5's thinking block PLUS a full answer; a smaller
        # budget got fully consumed by thinking on large snapshots, yielding an empty reply.
        client = llm_engine.build_client(config, model=model,
                                         max_tokens=int(config.get("assistant_max_tokens", 4000)))
    if client is None:
        return {"answer": "Assistant unavailable: Claude is disabled or no API key is configured.",
                "source": "unavailable"}
    prompt = _prompt(question, history, snapshot)
    summary = f"assistant: {(question or '')[:80]}"
    try:
        raw = client.complete(SYSTEM, prompt)
        if not (raw or "").strip():
            raw = client.complete(SYSTEM, prompt)   # the API occasionally returns empty — retry once
        text = (raw or "").strip() or "I couldn't produce an answer just now — please ask again."
        llm_engine.log_call("assistant", summary, text, getattr(client, "model", "?"),
                            getattr(client, "source", "claude"), ok=True,
                            usage=getattr(client, "last_usage", None))
        return {"answer": text, "source": getattr(client, "source", "claude")}
    except Exception as e:
        llm_engine.log_call("assistant", summary, "", getattr(client, "model", "?"),
                            "error", ok=False, error=str(e))
        return {"answer": f"Assistant error: {e}", "source": "error"}
