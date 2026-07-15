"""Tests for the forward-looking LLM entry-confirmation gate (llm_engine.confirm_entry).

The gate is a LIVE-money safety layer, so the critical behaviors are: it honors a real verdict,
it FAILS CLOSED (does not trade) when the LLM can't run or replies with junk, it can be flipped
to fail-open by explicit opt-in, and it NEVER raises into the entry path."""

from llm_engine import confirm_entry, MockLLMClient

_CTX = {
    "symbol": "KSOLVES", "strategy": "TrendFollow-Buy", "direction": "LONG",
    "entry_price": 325.0, "stop_loss": 318.0, "target_1": 335.0, "target_2": 345.0,
    "regime": "trending_up",
}


def test_confirm_entry_proceed_true():
    client = MockLLMClient(scripted=['{"proceed": true, "confidence": 78, "reason": "clean VWAP reclaim, RVOL strong"}'])
    v = confirm_entry(_CTX, config={}, client=client)
    assert v["proceed"] is True
    assert v["confidence"] == 78
    assert "VWAP" in v["reason"]


def test_confirm_entry_skip_false():
    client = MockLLMClient(scripted=['{"proceed": false, "confidence": 25, "reason": "chasing +10% extended move into resistance"}'])
    v = confirm_entry(_CTX, config={}, client=client)
    assert v["proceed"] is False
    assert v["confidence"] == 25


def test_confirm_entry_unavailable_is_fail_closed():
    # An empty MockLLMClient == engine not really enabled/keyed/in-budget: must NOT proceed by default.
    v = confirm_entry(_CTX, config={}, client=MockLLMClient())
    assert v["proceed"] is False
    assert v["source"] == "unavailable"


def test_confirm_entry_unavailable_fail_open_is_opt_in():
    v = confirm_entry(_CTX, config={"llm_entry_gate_fail_open": True}, client=MockLLMClient())
    assert v["proceed"] is True
    assert v["source"] == "unavailable"


def test_confirm_entry_unparseable_is_fail_closed():
    client = MockLLMClient(scripted=["the model rambled without any json at all"])
    v = confirm_entry(_CTX, config={}, client=client)
    assert v["proceed"] is False
    assert v["source"] == "parse_error"


def test_confirm_entry_never_raises_on_client_error():
    class _Boom:
        model = "boom"
        source = "claude"
        def complete(self, system, prompt):
            raise RuntimeError("network down")

    v = confirm_entry(_CTX, config={}, client=_Boom())
    assert v["proceed"] is False        # fail-closed on error
    assert v["source"] == "error"
