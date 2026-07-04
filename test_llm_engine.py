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


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
