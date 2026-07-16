import llm_engine


def test_assistant_calls_do_not_drain_the_trading_budget(monkeypatch):
    """Regression: calls_today() counted EVERY kind, so operator chat drew down the entry
    gate's quota. The gate is fail-closed, so an exhausted budget blocked every remaining
    entry — a chat session could silently halt trading for the rest of the day."""
    rows = (
        [{"time": "2026-07-16T10:00:00", "kind": "assistant"}] * 40
        + [{"time": "2026-07-16T10:00:00", "kind": "confirm"}] * 3
    )
    monkeypatch.setattr(llm_engine.jsonl_logger, "read_jsonl", lambda *a, **k: rows)
    monkeypatch.setattr(llm_engine, "llm_calls_path", lambda: "x")
    import datetime as _dt

    class _D(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return _dt.datetime(2026, 7, 16, 12, 0, 0)

    monkeypatch.setattr(llm_engine, "datetime", _D)

    # trading budget sees only the 3 confirm calls, not the 40 assistant ones
    assert llm_engine.calls_today() == 3
    assert llm_engine.budget_remaining({"llm_max_daily_calls": 50}) == 47
    # ...and kinds=None still reports everything, for status displays
    assert llm_engine.calls_today(kinds=None) == 43


def test_build_client_none_when_disabled(monkeypatch):
    monkeypatch.setattr(llm_engine, "is_enabled", lambda cfg: False)
    assert llm_engine.build_client({"llm_model": "claude-sonnet-5"}) is None


def test_build_client_ignores_trading_budget(monkeypatch):
    # Even with the TRADING budget exhausted, build_client still returns a real client.
    monkeypatch.setattr(llm_engine, "is_enabled", lambda cfg: True)
    monkeypatch.setattr(llm_engine, "budget_remaining", lambda cfg: 0)
    monkeypatch.setattr(llm_engine, "_resolve_key", lambda cfg=None: "sk-test")
    monkeypatch.setattr(llm_engine.AnthropicClient, "__init__",
                        lambda self, model, api_key, max_tokens=512: setattr(self, "model", model))
    c = llm_engine.build_client({"llm_provider": "anthropic", "llm_model": "claude-sonnet-5"})
    assert isinstance(c, llm_engine.AnthropicClient)
    assert c.model == "claude-sonnet-5"


def test_get_client_still_mock_when_trading_budget_exhausted(monkeypatch):
    monkeypatch.setattr(llm_engine, "is_enabled", lambda cfg: True)
    monkeypatch.setattr(llm_engine, "budget_remaining", lambda cfg: 0)
    assert isinstance(llm_engine.get_client({"llm_model": "m"}), llm_engine.MockLLMClient)
