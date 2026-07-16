import assistant_engine
from routers import assistant as assistant_router


def test_ask_delegates_to_engine(monkeypatch):
    import main, research_lab, jsonl_logger
    monkeypatch.setattr(main, "active_positions", {})
    monkeypatch.setattr(main, "trade_history", [])
    monkeypatch.setattr(main, "get_status", lambda: {"paper_trading": True, "watchlist": ["INFY"]})
    monkeypatch.setattr(main.client, "config", {"llm_enabled": True}, raising=False)
    monkeypatch.setattr(research_lab, "get_leaderboard", lambda: [])
    monkeypatch.setattr(jsonl_logger, "read_jsonl", lambda *a, **k: [])
    monkeypatch.setattr(assistant_engine, "answer",
                        lambda q, h, snap, cfg, client=None: {"answer": "hi", "source": "claude"})
    out = assistant_router.assistant_ask({"question": "how did today go?", "history": []})
    assert out == {"answer": "hi", "source": "claude"}


def test_ask_empty_question_is_rejected_softly():
    out = assistant_router.assistant_ask({"question": "  ", "history": []})
    assert out["source"] == "unavailable"
