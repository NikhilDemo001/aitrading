"""AI Research Lab API routes (moved verbatim from main.py).

Note: `import research_lab` stays lazy inside each handler on purpose —
research_lab itself reaches back into main (broadcast_research_status), so a
module-level import here would create a circular import at app startup.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/research", tags=["research"])


@router.get("/summary")
def get_research_summary():
    try:
        import research_lab
        conn = research_lab.get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT status, COUNT(*) as cnt FROM strategies GROUP BY status;")
            rows = cursor.fetchall()
        finally:
            conn.close()

        counts = {
            "Idea Generated": 0,
            "Backtesting": 0,
            "Walk Forward Testing": 0,
            "Validation": 0,
            "Paper Trading": 0,
            "Live Candidate": 0,
            "Ready For Review": 0,
            "Approved": 0,
            "Retired": 0,
            "Rejected": 0
        }
        total = 0
        for r in rows:
            status = r["status"]
            cnt = r["cnt"]
            if status in counts:
                counts[status] = cnt
            total += cnt

        return {
            "total_strategies": total,
            "under_research": counts["Idea Generated"],
            "backtesting": counts["Backtesting"],
            "walkforward": counts["Walk Forward Testing"],
            "validation": counts["Validation"],
            "papertrading": counts["Paper Trading"],
            "live_candidates": counts["Live Candidate"],
            "approved": counts["Approved"],
            "retired": counts["Retired"],
            "rejected": counts["Rejected"]
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/strategies")
def get_research_strategies():
    try:
        import research_lab
        return research_lab.get_all_strategies()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/strategy/{strategy_id}")
def get_research_strategy(strategy_id: str):
    try:
        import research_lab
        details = research_lab.get_strategy_details(strategy_id)
        if not details:
            raise HTTPException(404, f"Strategy {strategy_id} not found")
        return details
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/discover")
async def discover_strategies_endpoint(count: int = 5):
    try:
        import research_lab
        discovered = research_lab.discover_strategies(count)
        return {"status": "success", "discovered": discovered}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/backtest")
async def backtest_strategy_endpoint(strategy_id: str, version: int = 1):
    try:
        import research_lab
        v_id = research_lab.backtest_strategy(strategy_id, version)
        if v_id is None:
            raise HTTPException(404, "Strategy/Version not found")
        return {"status": "success", "version_id": v_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/validate")
async def validate_strategy_endpoint(strategy_id: str, version: int = 1):
    try:
        import research_lab
        passed = research_lab.validate_strategy(strategy_id, version)
        return {"status": "success", "passed": passed}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/evolve")
async def evolve_strategy_endpoint(strategy_id: str):
    try:
        import research_lab
        new_version = research_lab.evolve_strategy(strategy_id)
        if new_version is None:
            raise HTTPException(404, "Strategy not found")
        return {"status": "success", "new_version": new_version}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/battle")
async def battle_arena_endpoint(req: dict):
    try:
        import research_lab
        tournament_name = req.get("tournament_name", "Battle-Royale")
        strategy_ids = req.get("strategy_ids", [])
        winner = research_lab.run_battle_arena(tournament_name, strategy_ids)
        return {"status": "success", "winner": winner}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/leaderboard")
def get_leaderboard_endpoint():
    """Pure read of the current leaderboard. The rankings + daily journal are rebuilt by the
    autonomous research cycle / manual EOD rebuild — NOT here. Calling generate_daily_journal()
    on every poll did a DELETE + bulk-INSERT write that collided with the paper-trader's
    concurrent SQLite writes (intermittent 'database is locked' → HTTP 500) and spammed
    research_journal with a near-duplicate row per dashboard poll."""
    try:
        import research_lab
        return research_lab.get_leaderboard()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/journal")
def get_research_journal(date: str | None = None):
    try:
        import research_lab
        conn = research_lab.get_db_connection()
        try:
            cursor = conn.cursor()
            if date:
                cursor.execute("SELECT * FROM research_journal WHERE date(created_at) = ? ORDER BY id DESC;", (date,))
            else:
                cursor.execute("SELECT * FROM research_journal ORDER BY id DESC LIMIT 20;")
            rows = cursor.fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/control")
async def update_strategy_control(req: dict):
    try:
        import research_lab
        strategy_id = req.get("strategy_id")
        status = req.get("status")
        research_lab.update_strategy_status(strategy_id, status)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/chat")
async def chat_cto_endpoint(req: dict):
    try:
        import research_lab
        query = req.get("query", "")
        return research_lab.interpret_chat_query(query)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/status")
def get_research_status_endpoint():
    try:
        import research_lab
        return research_lab.research_status
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/timeline")
def get_research_timeline_endpoint(date: str | None = None):
    try:
        import research_lab
        return research_lab.get_chronological_timeline(date)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/briefing")
def get_ceo_briefing_endpoint(date: str | None = None):
    try:
        import research_lab
        return research_lab.generate_ceo_briefing(date)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/allocation")
def get_capital_allocation_endpoint():
    try:
        import research_lab
        return research_lab.calculate_capital_allocations()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/hypotheses")
def get_hypotheses_endpoint():
    try:
        import research_lab
        return research_lab.get_all_hypotheses()
    except Exception as e:
        raise HTTPException(500, str(e))
