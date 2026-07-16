"""
llm_engine.py — Section 5 Lane B: genuine Claude reasoning for trade lessons + strategy proposals.

SAFETY / SPEND CONTROL (this is the whole point of the gating below):
  * Real LLM calls happen ONLY when ALL of these hold:
      - config["llm_enabled"] is True (default False — nothing spends out of the box),
      - the provider's API key is resolvable (env or .env): ANTHROPIC_API_KEY for the
        "anthropic" provider, NVIDIA_API_KEY (or config["llm_api_key_env"]) for "openai_compat",
      - the provider's client dependency is importable,
      - today's call count is under config["llm_max_daily_calls"] (hard per-day budget cap).
  * config["llm_provider"] selects the backend: "anthropic" (Claude SDK) or "openai_compat"
    (any /chat/completions endpoint — NVIDIA build.nvidia.com, Ollama, LM Studio — via
    config["llm_base_url"]). Every llm_calls.jsonl record carries model + source, so swapping
    providers/models later never corrupts history: old records keep their original attribution.
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

def _provider(config: dict | None) -> str:
    return (config or {}).get("llm_provider", "anthropic")


def _key_env_name(config: dict | None) -> str:
    explicit = (config or {}).get("llm_api_key_env")
    if explicit:
        return str(explicit)
    return "NVIDIA_API_KEY" if _provider(config) == "openai_compat" else "ANTHROPIC_API_KEY"


def _key_from_dotenv(var_name: str) -> str | None:
    """Read the key straight from .env (the app doesn't push it into os.environ), so enabling
    the engine doesn't require a separate export step. Value is never logged."""
    try:
        with open(".env", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == var_name:
                    return v.strip().strip('"').strip("'") or None
    except OSError:
        pass
    return None


def _resolve_key(config: dict | None = None) -> str | None:
    var = _key_env_name(config)
    return os.environ.get(var) or _key_from_dotenv(var)


def api_key_available(config: dict | None = None) -> bool:
    return bool(_resolve_key(config))


def _client_dep_available(config: dict | None) -> bool:
    if _provider(config) == "openai_compat":
        try:
            import requests  # noqa: F401
            return True
        except Exception:
            return False
    try:
        import anthropic  # noqa: F401
        return True
    except Exception:
        return False


def is_enabled(config: dict | None) -> bool:
    config = config or {}
    return bool(config.get("llm_enabled", False)) and api_key_available(config) and _client_dep_available(config)


# Kinds that draw on the TRADING budget. The assistant is operator-initiated chat with its own
# cap (assistant_max_daily_calls); counting it here let a chat session silently drain the entry
# gate's quota, and because the gate is fail-closed that HALTS trading for the rest of the day.
TRADING_KINDS = ("confirm", "lesson", "proposal")


def calls_today(kinds: tuple | None = TRADING_KINDS) -> int:
    """Calls made today. Defaults to the trading kinds only — pass kinds=None for every call."""
    rows = jsonl_logger.read_jsonl(llm_calls_path())
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(1 for r in rows
               if str(r.get("time", "")).startswith(today)
               and (kinds is None or r.get("kind") in kinds))


def budget_remaining(config: dict | None) -> int:
    """Remaining TRADING budget. Sized to cover a full session: when this hits zero the
    fail-closed entry gate blocks every remaining entry, so the cap must never be the thing
    that stops the bot trading."""
    cap = int((config or {}).get("llm_max_daily_calls", 250))
    return max(0, cap - calls_today())


# ── call logging (Section 6 data/llm_calls.jsonl) ──────────────────────────────────────

def log_call(kind: str, prompt_summary: str, response: str, model: str, source: str,
             ok: bool = True, error: str | None = None, usage: dict | None = None) -> None:
    """Append one call to data/llm_calls.jsonl. `usage` carries the provider's real token
    counts (input/output/thinking) when the call actually reached the API — that is the only
    place token spend is recorded, so the usage dashboard can only report calls made after
    this was wired in. Rows without it simply have no token fields."""
    os.makedirs(jsonl_logger.DATA_DIR, exist_ok=True)
    entry = {
        "time": datetime.now().isoformat(),
        "kind": kind,                    # confirm | lesson | proposal | assistant
        "source": source,                # claude | openai_compat | heuristic
        "model": model,
        "prompt_summary": prompt_summary[:600],
        "response": (response or "")[:2000],
        "ok": ok,
        "error": error,
    }
    if usage:
        entry["input_tokens"] = usage.get("input_tokens")
        entry["output_tokens"] = usage.get("output_tokens")
        entry["thinking_tokens"] = usage.get("thinking_tokens")
    with open(llm_calls_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def usage_summary(config: dict | None = None) -> dict:
    """Today's LLM spend, for the AI Usage tab. Read-only; costs nothing.

    Token counts are the provider's own numbers, recorded per call — but only for calls made
    since usage logging was added, so `calls_missing_tokens` reports how many of today's rows
    predate it rather than silently understating spend.

    Cost is an ESTIMATE at the rates in config (llm_price_input_per_mtok /
    llm_price_output_per_mtok, USD per million tokens). They default to 0 so this never invents
    a number: set them from your provider's pricing page and the estimate appears.
    """
    config = config or {}
    rows = jsonl_logger.read_jsonl(llm_calls_path())
    today = datetime.now().strftime("%Y-%m-%d")
    todays = [r for r in rows if str(r.get("time", "")).startswith(today)]

    def _int(v):
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    by_kind: dict = {}
    for r in todays:
        k = r.get("kind") or "unknown"
        b = by_kind.setdefault(k, {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                   "thinking_tokens": 0, "ok": 0, "failed": 0})
        b["calls"] += 1
        b["input_tokens"] += _int(r.get("input_tokens"))
        b["output_tokens"] += _int(r.get("output_tokens"))
        b["thinking_tokens"] += _int(r.get("thinking_tokens"))
        b["ok" if r.get("ok") else "failed"] += 1

    input_tokens = sum(b["input_tokens"] for b in by_kind.values())
    output_tokens = sum(b["output_tokens"] for b in by_kind.values())
    thinking_tokens = sum(b["thinking_tokens"] for b in by_kind.values())

    in_rate = float(config.get("llm_price_input_per_mtok", 0.0) or 0.0)
    out_rate = float(config.get("llm_price_output_per_mtok", 0.0) or 0.0)
    usd_inr = float(config.get("usd_inr_rate", 0.0) or 0.0)
    cost_usd = (input_tokens / 1_000_000.0) * in_rate + (output_tokens / 1_000_000.0) * out_rate
    priced = in_rate > 0 or out_rate > 0

    trading_cap = int(config.get("llm_max_daily_calls", 250))
    assistant_cap = int(config.get("assistant_max_daily_calls", 100))
    trading_used = calls_today()
    assistant_used = calls_today(kinds=("assistant",))

    return {
        "date": today,
        "model": config.get("llm_model") or DEFAULT_MODEL,
        "provider": _provider(config),
        "enabled": is_enabled(config),
        "calls_total": len(todays),
        "calls_missing_tokens": sum(1 for r in todays if r.get("input_tokens") is None),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thinking_tokens": thinking_tokens,
        "total_tokens": input_tokens + output_tokens,
        "by_kind": by_kind,
        "cost": {
            "priced": priced,
            "usd": round(cost_usd, 4) if priced else None,
            "inr": round(cost_usd * usd_inr, 2) if (priced and usd_inr > 0) else None,
            "input_rate_per_mtok_usd": in_rate,
            "output_rate_per_mtok_usd": out_rate,
            "usd_inr_rate": usd_inr,
        },
        "budgets": {
            "trading": {"used": trading_used, "cap": trading_cap,
                        "remaining": max(0, trading_cap - trading_used)},
            "assistant": {"used": assistant_used, "cap": assistant_cap,
                          "remaining": max(0, assistant_cap - assistant_used)},
        },
    }


# ── client abstraction (real Anthropic vs. injectable mock) ────────────────────────────

class MockLLMClient:
    """No network. Returns scripted responses (for tests) or a deterministic echo, so the parse/
    fallback paths can be exercised without spending. `source` is 'heuristic'."""
    source = "heuristic"

    def __init__(self, scripted: list | None = None, model: str = "mock"):
        self._scripted = list(scripted or [])
        self.model = model
        self.last_usage = None      # no network, no tokens spent

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
        self.last_usage = None

    def complete(self, system: str, prompt: str) -> str:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        # Real token spend, straight from the provider — the only trustworthy source for the
        # usage dashboard. thinking_tokens matter here: this model bills them as output.
        try:
            u = msg.usage
            details = getattr(u, "output_tokens_details", None)
            self.last_usage = {
                "input_tokens": getattr(u, "input_tokens", None),
                "output_tokens": getattr(u, "output_tokens", None),
                "thinking_tokens": getattr(details, "thinking_tokens", None) if details else None,
            }
        except Exception:
            self.last_usage = None
        parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
        return "\n".join(parts).strip()


class OpenAICompatClient:
    """Any OpenAI-compatible /chat/completions endpoint: NVIDIA build.nvidia.com, Ollama,
    LM Studio, vLLM. Plain `requests`, no extra SDK. Non-streaming on purpose — Lane B is an
    EOD batch job that wants one compact JSON blob back, not tokens."""
    source = "openai_compat"

    def __init__(self, model: str, api_key: str | None, base_url: str,
                 max_tokens: int = 512, timeout: int = 180):
        self.model = model
        self._api_key = api_key or ""
        self._base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self._timeout = timeout
        self.last_usage = None

    def complete(self, system: str, prompt: str) -> str:
        import requests
        headers = {"Content-Type": "application/json"}
        if self._api_key:  # local servers (Ollama/LM Studio) need no key
            headers["Authorization"] = f"Bearer {self._api_key}"
        resp = requests.post(
            f"{self._base_url}/chat/completions",
            headers=headers,
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": self.max_tokens,
                "temperature": 0.2,  # lessons/proposals must be stable, parseable JSON
                "stream": False,
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        try:
            u = body.get("usage") or {}
            self.last_usage = {
                "input_tokens": u.get("prompt_tokens"),
                "output_tokens": u.get("completion_tokens"),
                "thinking_tokens": None,
            }
        except Exception:
            self.last_usage = None
        content = body["choices"][0]["message"]["content"] or ""
        return content.strip()


DEFAULT_OPENAI_COMPAT_BASE_URL = "https://integrate.api.nvidia.com/v1"


def build_client(config: dict | None, model: str | None = None, max_tokens: int | None = None):
    """Construct the real provider client when the engine is enabled + keyed, WITHOUT the
    trading daily-budget gate. Returns None when the engine can't run. Callers that need budget
    enforcement (the trading gate via get_client, or the assistant) check their own budget.
    max_tokens lets callers (e.g. the assistant) request longer answers than the 512 default."""
    config = config or {}
    if not is_enabled(config):
        return None
    model = model or config.get("llm_model") or DEFAULT_MODEL
    mt = int(max_tokens) if max_tokens else 512
    if _provider(config) == "openai_compat":
        base_url = config.get("llm_base_url") or DEFAULT_OPENAI_COMPAT_BASE_URL
        # Free/shared endpoints (NVIDIA trial) queue under load — allow a generous timeout.
        timeout = int(config.get("llm_timeout_seconds", 180))
        return OpenAICompatClient(model, _resolve_key(config), base_url, max_tokens=mt, timeout=timeout)
    return AnthropicClient(model, _resolve_key(config), max_tokens=mt)


def get_client(config: dict | None):
    """Returns a real client when enabled + keyed + within the TRADING budget, else MockLLMClient."""
    config = config or {}
    model = config.get("llm_model") or DEFAULT_MODEL
    if budget_remaining(config) > 0:
        client = build_client(config, model=model)
        if client is not None:
            return client
    return MockLLMClient(model=model)


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

CONFIRM_SYSTEM = (
    "You are the final risk gate for a LIVE intraday NSE equity trade that has ALREADY passed the "
    "bot's technical filters (trend, VWAP, volume, R:R, liquidity). Your job is to catch bad-context "
    "entries the technicals miss. PROCEED only if the setup is sound; SKIP if it looks like chasing an "
    "over-extended move, buying into obvious resistance (or shorting into support), fighting the broader "
    "market, or entering just before a known event. If a 'news' field is present, weigh it heavily. Be "
    "conservative: when genuinely unsure, SKIP. Reply ONLY with compact JSON: "
    "{\"proceed\": true|false, \"confidence\": 0-100, \"reason\": \"<=160 chars\"}. No prose outside the JSON."
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
        log_call("lesson", summary, raw, client.model, getattr(client, "source", "heuristic"), ok=parsed is not None,
                 usage=getattr(client, "last_usage", None))
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
        if not isinstance(client, MockLLMClient) and budget_remaining(config) <= 0:
            client = MockLLMClient(model=client.model)  # switch to heuristic for the remainder
        les = extract_lesson(t, config=config, client=client)
        out[tid] = les["lesson"]
    return out


# ── public API: forward-looking entry confirmation (Section 5C) ─────────────────────────

def _confirm_prompt(context: dict) -> str:
    """Serialize the proposed-trade context the gate reasons over. `context` may carry a 'news'
    field once a news/corporate-actions feed is wired in — that's where the real edge lives."""
    return json.dumps(context, default=str)


def confirm_entry(context: dict, config: dict | None = None, client=None) -> dict:
    """Forward-looking LLM gate for ONE proposed entry.

    `context` is a JSON-serializable dict describing the setup (symbol, direction,
    entry/stop/targets, regime, technicals, and optionally 'news'). Returns
    {'proceed': bool, 'confidence': int, 'reason': str, 'source': str}.

    Fail-closed by default: if the LLM cannot actually run (disabled / no key / over budget) or
    returns something unparseable, proceed=False so a live entry is NOT taken on an un-vetted
    setup. Set config['llm_entry_gate_fail_open']=True to invert that. Never raises."""
    config = config or {}
    fail_open = bool(config.get("llm_entry_gate_fail_open", False))
    client = client or get_client(config)
    summary = f"confirm {context.get('symbol')} {context.get('strategy')} {context.get('direction')}"

    # Mock client with nothing scripted == the engine isn't really enabled/keyed/in-budget.
    if isinstance(client, MockLLMClient) and not client._scripted:
        log_call("confirm", summary, "", client.model, "unavailable", ok=False)
        return {"proceed": fail_open, "confidence": 0,
                "reason": "LLM entry gate enabled but LLM unavailable (disabled/no key/over budget)",
                "source": "unavailable"}
    try:
        raw = client.complete(CONFIRM_SYSTEM, _confirm_prompt(context))
        parsed = _extract_json(raw)
        ok = bool(parsed) and "proceed" in parsed
        log_call("confirm", summary, raw, client.model, getattr(client, "source", "heuristic"), ok=ok,
                 usage=getattr(client, "last_usage", None))
        if not ok:
            return {"proceed": fail_open, "confidence": 0,
                    "reason": "LLM returned an unparseable verdict", "source": "parse_error"}
        return {"proceed": bool(parsed["proceed"]),
                "confidence": int(parsed.get("confidence", 0) or 0),
                "reason": str(parsed.get("reason", ""))[:200],
                "source": getattr(client, "source", "llm")}
    except Exception as e:
        log_call("confirm", summary, "", getattr(client, "model", "?"), "error", ok=False, error=str(e))
        return {"proceed": fail_open, "confidence": 0,
                "reason": f"LLM error: {e}", "source": "error"}


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
        log_call("proposal", summary, raw, client.model, getattr(client, "source", "heuristic"),
                 ok=parsed is not None, usage=getattr(client, "last_usage", None))
        if not parsed or "title" not in parsed:
            return _heuristic_proposal(day_context)
        parsed["source"] = getattr(client, "source", "claude")
        return parsed
    except Exception as e:
        log_call("proposal", summary, "", getattr(client, "model", "?"), getattr(client, "source", "heuristic"), ok=False, error=str(e))
        return _heuristic_proposal(day_context)


def read_llm_calls(limit: int | None = None) -> list:
    return jsonl_logger.read_jsonl(llm_calls_path(), limit=limit)
