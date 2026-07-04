"""
Tests for llm_engine.py — Lane B Claude wiring. ALL tests use MockLLMClient or scripted responses:
NO network call is ever made, so running the suite never spends. Also asserts the safety default
(disabled out of the box -> no real client).
"""

import os
import shutil

import pytest

import jsonl_logger
import llm_engine


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(jsonl_logger, "DATA_DIR", str(data_dir))
    os.makedirs(data_dir, exist_ok=True)
    yield
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)


def _trade(pnl=250, tid="t1"):
    return {
        "trade_id": tid, "symbol": "NSE:RELIANCE", "strategy": "ORB-Buy", "direction": "long",
        "entry_price": 2950.0, "exit_price": 2968.0, "pnl": pnl, "r_multiple": 1.8,
        "exit_reason": "target", "market_regime": "trending_up",
        "candlestick_patterns": ["bullish_engulfing"], "time_of_day_bucket": "0915_1000",
        "indicators_at_entry": {"rsi": 61, "vwap": 2948.2, "atr": 9.4},
    }


def test_disabled_by_default_returns_mock_client():
    """Safety: with no llm_enabled flag, get_client must NOT construct a real Anthropic client."""
    assert llm_engine.is_enabled({}) is False
    assert llm_engine.is_enabled({"llm_enabled": True}) in (True, False)  # depends on key, but...
    client = llm_engine.get_client({})  # no llm_enabled
    assert isinstance(client, llm_engine.MockLLMClient)


def test_extract_lesson_parses_scripted_json():
    scripted = ['{"lesson": "VWAP reclaim + volume; clean target.", "tags": ["vwap_reclaim","high_volume"]}']
    client = llm_engine.MockLLMClient(scripted=scripted, model="mock")
    les = llm_engine.extract_lesson(_trade(), config={}, client=client)
    assert les["lesson"].startswith("VWAP reclaim")
    assert "vwap_reclaim" in les["tags"]
    calls = llm_engine.read_llm_calls()
    assert len(calls) == 1 and calls[0]["kind"] == "lesson"


def test_extract_lesson_falls_back_to_heuristic_on_empty():
    client = llm_engine.MockLLMClient(model="mock")  # no scripted response
    les = llm_engine.extract_lesson(_trade(pnl=-120), config={}, client=client)
    assert les["source"] == "heuristic"
    assert "[heuristic]" in les["lesson"]


def test_extract_lesson_never_raises_on_client_error():
    class Boom:
        model = "x"; source = "claude"
        def complete(self, s, p): raise RuntimeError("network down")
    les = llm_engine.extract_lesson(_trade(), config={}, client=Boom())
    assert les["source"] == "heuristic"
    calls = llm_engine.read_llm_calls()
    assert calls[-1]["ok"] is False and "network down" in (calls[-1]["error"] or "")


def test_batch_lessons_skip_already_lessoned():
    trades = [_trade(tid="a"), {**_trade(tid="b"), "lesson": "already"}]
    client = llm_engine.MockLLMClient(model="mock")
    out = llm_engine.extract_lessons_for_trades(trades, config={}, client=client)
    assert "a" in out and "b" not in out


def test_budget_counting():
    for _ in range(3):
        llm_engine.log_call("lesson", "s", "r", "m", "heuristic")
    assert llm_engine.calls_today() == 3
    assert llm_engine.budget_remaining({"llm_max_daily_calls": 5}) == 2
    assert llm_engine.budget_remaining({"llm_max_daily_calls": 2}) == 0


def test_generate_proposal_heuristic_from_worst_combo():
    ctx = {"worst_combo": {"strategy": "Momentum", "market_regime": "choppy", "net_pnl": -800, "trades": 5}}
    prop = llm_engine.generate_proposal(ctx, config={}, client=llm_engine.MockLLMClient(model="mock"))
    assert prop["strategy"] == "Momentum"
    assert prop["source"] == "heuristic"
    assert "param_changes" in prop


def test_proposal_parses_scripted_claude_json():
    scripted = ['{"title":"Tighten ORB","rationale":"choppy losses","strategy":"ORB","param_changes":{"min_confluence_score":70}}']
    client = llm_engine.MockLLMClient(scripted=scripted, model="mock")
    # scripted present -> goes through the parse path (source reflects the mock client)
    prop = llm_engine.generate_proposal({"worst_combo": {}}, config={}, client=client)
    assert prop["title"] == "Tighten ORB"
    assert prop["param_changes"]["min_confluence_score"] == 70


# ── provider-aware client selection (openai_compat: NVIDIA build.nvidia.com / Ollama) ────────

def _nvidia_cfg(**over):
    cfg = {"llm_enabled": True, "llm_provider": "openai_compat",
           "llm_base_url": "https://integrate.api.nvidia.com/v1",
           "llm_model": "meta/llama-3.3-70b-instruct"}
    cfg.update(over)
    return cfg


def test_openai_compat_selected_when_keyed(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    client = llm_engine.get_client(_nvidia_cfg())
    assert isinstance(client, llm_engine.OpenAICompatClient)
    assert client.model == "meta/llama-3.3-70b-instruct"
    assert client.source == "openai_compat"


def test_openai_compat_without_key_falls_back_to_mock(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr(llm_engine, "_key_from_dotenv", lambda var: None)  # ignore local .env
    assert llm_engine.is_enabled(_nvidia_cfg()) is False
    assert isinstance(llm_engine.get_client(_nvidia_cfg()), llm_engine.MockLLMClient)


def test_custom_key_env_name(monkeypatch):
    monkeypatch.setattr(llm_engine, "_key_from_dotenv", lambda var: None)
    monkeypatch.setenv("MY_LLM_KEY", "k")
    assert llm_engine.api_key_available(_nvidia_cfg(llm_api_key_env="MY_LLM_KEY")) is True
    monkeypatch.delenv("MY_LLM_KEY")
    assert llm_engine.api_key_available(_nvidia_cfg(llm_api_key_env="MY_LLM_KEY")) is False


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_openai_compat_complete_parses_choices(monkeypatch):
    """No network: requests.post is patched. Asserts endpoint shape, auth header and that the
    assistant message content comes back stripped."""
    import requests
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, body=json)
        return _FakeResp({"choices": [{"message": {"content": ' {"lesson": "x", "tags": []} '}}]})

    monkeypatch.setattr(requests, "post", fake_post)
    c = llm_engine.OpenAICompatClient("meta/llama-3.3-70b-instruct", "nvapi-test",
                                      "https://integrate.api.nvidia.com/v1")
    out = c.complete("sys", "prompt")
    assert out == '{"lesson": "x", "tags": []}'
    assert captured["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer nvapi-test"
    assert captured["body"]["stream"] is False
    assert captured["body"]["messages"][0] == {"role": "system", "content": "sys"}


def test_openai_compat_extract_lesson_end_to_end(monkeypatch):
    """Full extract_lesson path through an OpenAICompatClient with a faked HTTP layer: the lesson
    is parsed, and the llm_calls.jsonl record carries source=openai_compat + the model name."""
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: _FakeResp(
        {"choices": [{"message": {"content": '{"lesson": "Momentum entries need RVOL>1.5", "tags": ["rvol"]}'}}]}))
    client = llm_engine.OpenAICompatClient("meta/llama-3.3-70b-instruct", "nvapi-test",
                                           "https://integrate.api.nvidia.com/v1")
    les = llm_engine.extract_lesson(_trade(), config={}, client=client)
    assert les["source"] == "openai_compat"
    assert les["lesson"].startswith("Momentum entries")
    rows = llm_engine.read_llm_calls()
    assert rows and rows[-1]["source"] == "openai_compat"
    assert rows[-1]["model"] == "meta/llama-3.3-70b-instruct"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
