import assistant_engine
import llm_engine

STATUS = {"paper_trading": True, "bot_running": True, "open_positions_count": 1,
          "daily_pnl": 517.78, "scanner_last_summary": "40 checked, 1 signals, 1 filtered",
          "scanner_last_loop": "12:55", "watchlist": ["RELIANCE", "INFY"]}
POSITIONS = [{"symbol": "INFY", "direction": "LONG", "entry_price": 100.0, "current_price": 101.0,
              "stop_loss": 98.0, "target": 104.0, "pnl": 10.0, "strategy": "ORB-Buy"}]
TRADES = [{"symbol": "RELIANCE", "strategy": "VWAP-Pullback-Buy", "direction": "LONG",
           "entry_price": 50.0, "exit_price": 51.0, "pnl": 25.0, "reason": "TARGET-2 HIT",
           "entry_time": "2026-07-16T10:00:00", "exit_time": "2026-07-16T10:05:00"}]
DECISIONS = [{"time": "2026-07-16T10:15:00", "type": "skip", "symbol": "RELIANCE",
              "reason": "liquidity: thin book"}]
LEADERBOARD = [{"rank": 1, "name": "EMA Cloud", "id": "AI-EMA-1", "profit_factor": 1.7}]


def test_build_context_has_all_domains():
    snap = assistant_engine.build_context("how did today go?", status=STATUS, positions=POSITIONS,
        today_trades=TRADES, decisions=DECISIONS, leaderboard=LEADERBOARD, journal=None)
    for key in ("status", "open_positions", "today_trades", "today_pnl", "recent_decisions", "leaderboard"):
        assert key in snap
    assert snap["today_pnl"] == 25.0


def test_build_context_excludes_shadow_trades_from_today_pnl():
    """Shadow trades are simulated learning-only fills; today_pnl must count REAL trades only so
    it reconciles with status.daily_pnl. Summing both made the model report a false discrepancy."""
    trades = [
        {"symbol": "A", "pnl": 25.0},                             # real
        {"symbol": "B", "pnl": -500.0, "is_shadow_trade": True},  # shadow
    ]
    snap = assistant_engine.build_context("today?", status=STATUS, positions=[],
        today_trades=trades, decisions=[], leaderboard=[], journal=None)
    assert snap["today_pnl"] == 25.0
    assert snap["shadow_pnl"] == -500.0
    assert snap["real_trade_count"] == 1
    assert snap["shadow_trade_count"] == 1


def test_build_context_symbol_filter_surfaces_named_symbol():
    snap = assistant_engine.build_context("why did you skip RELIANCE?", status=STATUS,
        positions=POSITIONS, today_trades=TRADES, decisions=DECISIONS, leaderboard=LEADERBOARD,
        journal=None, known_symbols=["RELIANCE", "INFY"])
    assert "RELIANCE" in snap["focus_symbols"]
    assert any(d["symbol"] == "RELIANCE" for d in snap["symbol_decisions"])


def test_answer_returns_scripted_text():
    client = llm_engine.MockLLMClient(scripted=["Today closed +Rs 25 on one winner."])
    out = assistant_engine.answer("how did today go?", [], {"today_pnl": 25.0},
                                  {"llm_enabled": True}, client=client)
    assert out["answer"] == "Today closed +Rs 25 on one winner."
    assert out["source"] == "heuristic"


def test_answer_unavailable_when_over_budget(monkeypatch):
    monkeypatch.setattr(assistant_engine, "assistant_budget_remaining", lambda cfg: 0)
    out = assistant_engine.answer("q", [], {}, {"llm_enabled": True})
    assert out["source"] == "unavailable"
    assert "unavailable" in out["answer"].lower()


def test_answer_never_raises_on_client_error():
    class _Boom:
        source = "claude"
        def complete(self, system, prompt):
            raise RuntimeError("network down")
    out = assistant_engine.answer("q", [], {}, {"llm_enabled": True}, client=_Boom())
    assert out["source"] == "error"
