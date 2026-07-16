"""Assistant API route. The lazy `import main` (main imports this router back) keeps startup
free of circular imports."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.post("/ask")
def assistant_ask(req: dict):
    import main
    import jsonl_logger
    import assistant_engine

    question = str((req or {}).get("question", "")).strip()
    history = (req or {}).get("history") or []
    if not question:
        return {"answer": "Ask me something about the bot — e.g. 'how did today go?'", "source": "unavailable"}

    try:
        status = main.get_status()
    except Exception:
        status = {}
    positions = list(main.active_positions.values())
    today = main.get_ist_now().date().isoformat()
    today_trades = [t for t in main.trade_history
                    if str(t.get("exit_time", "")).startswith(today)
                    or str(t.get("entry_time", "")).startswith(today)]
    try:
        decisions = jsonl_logger.read_jsonl(jsonl_logger.DECISIONS_FILE, limit=120)
    except Exception:
        decisions = []
    # Strategy stats come from the Lane-A leaderboard, which is built from REAL closed trades.
    # (The old research-lab leaderboard/journal were generated with random.uniform(), and the
    # assistant kept faithfully reporting those invented numbers.)
    try:
        import leaderboard as lane_a
        strategy_stats = lane_a.load_stats()
    except Exception:
        strategy_stats = {}
    known_symbols = list(status.get("watchlist") or []) + [p.get("symbol") for p in positions]

    snapshot = assistant_engine.build_context(
        question, status=status, positions=positions, today_trades=today_trades,
        decisions=decisions, strategy_stats=strategy_stats, known_symbols=known_symbols)
    return assistant_engine.answer(question, history, snapshot, main.client.config)
