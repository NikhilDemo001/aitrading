"""Assistant API route. Lazy imports of main/research_lab (they import back into this app) keep
startup free of circular imports, matching routers/research.py."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


def _latest_journal():
    try:
        import research_lab
        conn = research_lab.get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT findings, mistakes, opportunities, strengths, weaknesses, created_at "
                        "FROM research_journal ORDER BY id DESC LIMIT 1;")
            row = cur.fetchone()
        finally:
            conn.close()
        return dict(row) if row else None
    except Exception:
        return None


@router.post("/ask")
def assistant_ask(req: dict):
    import main
    import research_lab
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
    try:
        leaderboard = research_lab.get_leaderboard()[:15]
    except Exception:
        leaderboard = []
    known_symbols = list(status.get("watchlist") or []) + [p.get("symbol") for p in positions]

    snapshot = assistant_engine.build_context(
        question, status=status, positions=positions, today_trades=today_trades,
        decisions=decisions, leaderboard=leaderboard, journal=_latest_journal(),
        known_symbols=known_symbols)
    return assistant_engine.answer(question, history, snapshot, main.client.config)
