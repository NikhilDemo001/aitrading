import llm_engine


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
