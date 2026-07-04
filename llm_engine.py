"""
llm_engine.py — Section 5 Lane B: genuine Claude reasoning for trade lessons + strategy proposals.

SAFETY / SPEND CONTROL (this is the whole point of the gating below):
  * Real Anthropic calls happen ONLY when ALL of these hold:
      - config["llm_enabled"] is True (default False — nothing spends out of the box),
      - an ANTHROPIC_API_KEY is resolvable (env or .env),
      - the anthropic SDK is importable,
      - today's call count is under config["llm_max_daily_calls"] (hard per-day budget cap).
  * When any of those is false, we fall back to a deterministic, clearly-labelled heuristic
    lesson/proposal (source="heuristic") so the whole Lane-B pipeline still runs, is testable,
    and is demonstrable WITHOUT spending — real Claude output (source="claude") only switches on
    once the operator explicitly enables it.
  * Every call (real or mock) is appended to data/llm_calls.jsonl (prompt summary + response) so
    the AI's actual reasoning is fully inspectable in the UI (Section 8 Tab 6).

This never places or modifies a trade. It only produces text lessons and INACTIVE proposals that
must still pass the Promotion Gate (promotion_gate.py) before anything becomes live.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

import jsonl_logger

# Cheap, high-volume-friendly default for per-trade lessons. Overridable via config["llm_model"].
# (config currently ships claude-opus-4-8, which is far pricier than needed for this task — the
# operator confirms the model when enabling.)
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def llm_calls_path() -> str:
    return os.path.join(jsonl_logger.DATA_DIR, "llm_calls.jsonl")


# ── key + availability resolution ──────────────────────────────────────────────────────

def _key_from_dotenv() -> str | None:
    """Read ANTHROPIC_API_KEY straight from .env (the app doesn't push it into os.environ), so
    enabling the engine doesn't require a separate export step. Value is never logged."""
    try:
        with open(".env", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == "ANTHROPIC_API_KEY":
                    return v.strip().strip('"').strip("'") or None
    except OSError:
        pass
    return None


def api_key_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or _key_from_dotenv())


def _resolve_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or _key_from_dotenv()


def _anthropic_available() -> bool:
    try:
        import anthropic  # noqa: F401
        return True
    except Exception:
        return False


def is_enabled(config: dict | None) -> bool:
    config = config or {}
    return bool(config.get("llm_enabled", False)) and api_key_available() and _anthropic_available()


def calls_today() -> int:
    rows = jsonl_logger.read_jsonl(llm_calls_path())
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(1 for r in rows if str(r.get("time", "")).startswith(today))


def budget_remaining(config: dict | None) -> int:
    cap = int((config or {}).get("llm_max_daily_calls", 50))
    return max(0, cap - calls_today())


# ── call logging (Section 6 data/llm_calls.jsonl) ──────────────────────────────────────

def log_call(kind: str, prompt_summary: str, response: str, model: str, source: str,
             ok: bool = True, error: str | None = None) -> None:
    os.makedirs(jsonl_logger.DATA_DIR, exist_ok=True)
    entry = {
        "time": datetime.now().isoformat(),
        "kind": kind,                    # lesson | proposal
        "source": source,                # claude | heuristic
        "model": model,
        "prompt_summary": prompt_summary[:600],
        "response": (response or "")[:2000],
        "ok": ok,
        "error": error,
    }
    with open(llm_calls_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ── client abstraction (real Anthropic vs. injectable mock) ────────────────────────────

class MockLLMClient:
    """No network. Returns scripted responses (for tests) or a deterministic echo, so the parse/
    fallback paths can be exercised without spending. `source` is 'heuristic'."""
    source = "heuristic"

    def __init__(self, scripted: list | None = None, model: str = "mock"):
        self._scripted = list(scripted or [])
        self.model = model

    def complete(self, system: str, prompt: str) -> str:
        if self._scripted:
            return self._scripted.pop(0)
        return ""  # triggers heuristic fallback in callers


class AnthropicClient:
    """Thin wrapper over the anthropic SDK. Constructed only when the engine is enabled + keyed."""
    source = "claude"

    def __init__(self, model: str, api_key: str, max_tokens: int = 512):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, system: str, prompt: str) -> str:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
        return "\n".join(parts).strip()


def get_client(config: dict | None):
    """Returns an AnthropicClient when enabled + within budget, else a MockLLMClient (no spend)."""
    config = config or {}
    if is_enabled(config) and budget_remaining(config) > 0:
        model = config.get("llm_model") or DEFAULT_MODEL
        return AnthropicClient(model, _resolve_key())
    return MockLLMClient(model=(config.get("llm_model") or DEFAULT_MODEL))


# ── prompts + parsing ──────────────────────────────────────────────────────────────────

LESSON_SYSTEM = (
    "You are a disciplined intraday trading coach reviewing a single closed NSE trade. "
    "Reply ONLY with compact JSON: {\"lesson\": \"<=200 chars, one concrete takeaway\", "
    "\"tags\": [\"snake_case\", ...]}. No prose outside the JSON."
)

PROPOSAL_SYSTEM = (
    "You are a quant researcher proposing ONE small, testable improvement to an intraday strategy "
    "set, based on the day's aggregate results. Reply ONLY with compact JSON: "
    "{\"title\": \"...\", \"rationale\": \"<=280 chars\", \"strategy\": \"<base strategy name>\", "
    "\"param_changes\": {\"<key>\": <value>}}. Propose nothing that increases per-trade risk."
)


def _lesson_prompt(trade: dict) -> str:
    ind = trade.get("indicators_at_entry", {})
    return json.dumps({
        "symbol": trade.get("symbol"), "strategy": trade.get("strategy"),
        "direction": trade.get("direction"), "entry": trade.get("entry_price"),
        "exit": trade.get("exit_price"), "pnl": trade.get("pnl"),
        "r_multiple": trade.get("r_multiple"), "exit_reason": trade.get("exit_reason"),
        "regime": trade.get("market_regime"), "patterns": trade.get("candlestick_patterns"),
        "time_bucket": trade.get("time_of_day_bucket"), "indicators": ind,
    }, default=str)


_JSON_RE = re.compile(r"\{.*\}", re.S)


def _extract_json(raw: str) -> dict | None:
    if not raw:
        return None
    m = _JSON_RE.search(raw)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _heuristic_lesson(trade: dict) -> dict:
    """Deterministic fallback when Claude is disabled/over-budget — clearly not AI-authored."""
    win = (trade.get("pnl", 0) or 0) >= 0
    reason = trade.get("exit_reason", "")
    pats = trade.get("candlestick_patterns") or []
    regime = trade.get("market_regime", "unknown")
    if win:
        text = f"[heuristic] {trade.get('strategy')} worked in {regime}; exit via {reason}."
    else:
        text = f"[heuristic] {trade.get('strategy')} lost in {regime}; review entry filter (exit {reason})."
    tags = [t for t in [regime, ("win" if win else "loss")] + list(pats) if t]
    return {"lesson": text, "tags": tags, "source": "heuristic"}


# ── public API: lesson extraction ──────────────────────────────────────────────────────

def extract_lesson(trade: dict, config: dict | None = None, client=None) -> dict:
    """Returns {'lesson': str, 'tags': [str], 'source': 'claude'|'heuristic'} for one closed trade.
    Never raises — on any error or when disabled/over-budget it returns a heuristic lesson."""
    config = config or {}
    client = client or get_client(config)
    prompt = _lesson_prompt(trade)
    summary = f"lesson for {trade.get('symbol')} {trade.get('strategy')} pnl={trade.get('pnl')}"
    if isinstance(client, MockLLMClient) and not client._scripted:
        # No scripted response and no real client -> heuristic without a wasted "call" log noise,
        # but still record it so the UI shows the fallback happened.
        les = _heuristic_lesson(trade)
        log_call("lesson", summary, les["lesson"], client.model, "heuristic", ok=True)
        return les
    try:
        raw = client.complete(LESSON_SYSTEM, prompt)
        parsed = _extract_json(raw)
        log_call("lesson", summary, raw, client.model, getattr(client, "source", "heuristic"), ok=parsed is not None)
        if not parsed or "lesson" not in parsed:
            return _heuristic_lesson(trade)
        return {"lesson": str(parsed["lesson"])[:300], "tags": parsed.get("tags", []),
                "source": getattr(client, "source", "claude")}
    except Exception as e:
        log_call("lesson", summary, "", getattr(client, "model", "?"), getattr(client, "source", "heuristic"), ok=False, error=str(e))
        return _heuristic_lesson(trade)


def extract_lessons_for_trades(trades: list, config: dict | None = None, client=None) -> dict:
    """Batch lessons for a day's closed trades, honoring the daily budget cap. Returns
    {trade_id: lesson_text} suitable for jsonl_logger.backfill_lessons()."""
    config = config or {}
    client = client or get_client(config)
    out = {}
    for t in trades:
        tid = t.get("trade_id")
        if not tid or t.get("lesson"):
            continue
        # Re-check budget between calls so a real client stops at the cap mid-batch.
        if isinstance(client, AnthropicClient) and budget_remaining(config) <= 0:
            client = MockLLMClient(model=client.model)  # switch to heuristic for the remainder
        les = extract_lesson(t, config=config, client=client)
        out[tid] = les["lesson"]
    return out


# ── public API: strategy proposal ──────────────────────────────────────────────────────

def _proposal_prompt(day_context: dict) -> str:
    return json.dumps(day_context, default=str)


def _heuristic_proposal(day_context: dict) -> dict | None:
    """Mechanical proposal from the day's worst (strategy, regime): tighten it. Clearly heuristic."""
    worst = day_context.get("worst_combo")
    if not worst:
        return None
    return {
        "title": f"Add a filter to {worst.get('strategy')} in {worst.get('market_regime')}",
        "rationale": f"[heuristic] {worst.get('strategy')} lost ₹{worst.get('net_pnl')} over "
                     f"{worst.get('trades')} trades in {worst.get('market_regime')} today; "
                     f"gate entries there on stronger confirmation.",
        "strategy": worst.get("strategy"),
        "param_changes": {"min_confluence_score": 65},
        "source": "heuristic",
    }


def generate_proposal(day_context: dict, config: dict | None = None, client=None) -> dict | None:
    """Returns ONE proposal dict (or None) — an INACTIVE candidate; it does not trade. Uses Claude
    when enabled, else a heuristic proposal so the Promotion-Gate pipeline is demonstrable."""
    config = config or {}
    client = client or get_client(config)
    summary = "proposal from day context"
    if isinstance(client, MockLLMClient) and not client._scripted:
        prop = _heuristic_proposal(day_context)
        if prop:
            log_call("proposal", summary, prop["rationale"], client.model, "heuristic", ok=True)
        return prop
    try:
        raw = client.complete(PROPOSAL_SYSTEM, _proposal_prompt(day_context))
        parsed = _extract_json(raw)
        log_call("proposal", summary, raw, client.model, getattr(client, "source", "heuristic"), ok=parsed is not None)
        if not parsed or "title" not in parsed:
            return _heuristic_proposal(day_context)
        parsed["source"] = getattr(client, "source", "claude")
        return parsed
    except Exception as e:
        log_call("proposal", summary, "", getattr(client, "model", "?"), getattr(client, "source", "heuristic"), ok=False, error=str(e))
        return _heuristic_proposal(day_context)


def read_llm_calls(limit: int | None = None) -> list:
    return jsonl_logger.read_jsonl(llm_calls_path(), limit=limit)
