# Talk-to-Your-Bot Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only, on-demand Claude "Assistant" tab that answers operator questions grounded only in the bot's real data (decisions, trades, positions, leaderboard).

**Architecture:** A pure `assistant_engine.py` builds a compact JSON snapshot of the bot and calls Claude once via the existing `llm_engine` client; a new `routers/assistant.py` (`POST /api/assistant/ask`) gathers live data and delegates to the engine; a new React `AssistantTab` provides the chat UI. No trading/order/config write path is ever touched.

**Tech Stack:** Python 3.14, FastAPI, `anthropic` SDK (via existing `llm_engine`), pytest; React + TypeScript + Vite (existing Midnight Quant frontend).

## Global Constraints

- Read-only: the assistant MUST NOT place/modify/cancel orders or mutate config/state. It only reads.
- Fail-soft: the endpoint never raises to the client; Claude unavailable/over-budget → a plain message.
- Budget: assistant calls use a SEPARATE daily cap `assistant_max_daily_calls` (default 100), independent of the trading gate's `llm_max_daily_calls` (50).
- Model: default `assistant_model` = `config["llm_model"]` (currently `claude-sonnet-5`).
- Follow existing patterns: routers use `from routers import X as X_router` + `app.include_router`; lazy `import main` / `import research_lab` inside handlers to avoid circular imports.
- No new dependencies.

---

### Task 1: `llm_engine.build_client` — a budget-independent client factory

**Files:**
- Modify: `llm_engine.py` (add `build_client`, refactor `get_client` to reuse it) — around lines 213-224
- Test: `test_llm_engine_build_client.py`

**Interfaces:**
- Produces: `llm_engine.build_client(config: dict | None, model: str | None = None) -> AnthropicClient | OpenAICompatClient | None` — a real client when `is_enabled(config)`, ignoring the trading daily budget; `None` otherwise.
- `get_client` behaviour is unchanged (real client when enabled + keyed + within the trading budget, else `MockLLMClient`).

- [ ] **Step 1: Write the failing test**

```python
# test_llm_engine_build_client.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_llm_engine_build_client.py -q`
Expected: FAIL with `AttributeError: module 'llm_engine' has no attribute 'build_client'`.

- [ ] **Step 3: Implement `build_client` and refactor `get_client`**

Replace the existing `get_client` function (llm_engine.py ~213-224) with:

```python
def build_client(config, model=None):
    """Construct the real provider client when the engine is enabled + keyed, WITHOUT the
    trading daily-budget gate. Returns None when the engine can't run. Callers that need
    budget enforcement (e.g. the trading gate, the assistant) check their own budget."""
    config = config or {}
    if not is_enabled(config):
        return None
    model = model or config.get("llm_model") or DEFAULT_MODEL
    if _provider(config) == "openai_compat":
        base_url = config.get("llm_base_url") or DEFAULT_OPENAI_COMPAT_BASE_URL
        timeout = int(config.get("llm_timeout_seconds", 180))
        return OpenAICompatClient(model, _resolve_key(config), base_url, timeout=timeout)
    return AnthropicClient(model, _resolve_key(config))


def get_client(config):
    """Returns a real client when enabled + keyed + within the TRADING budget, else MockLLMClient."""
    config = config or {}
    model = config.get("llm_model") or DEFAULT_MODEL
    if budget_remaining(config) > 0:
        client = build_client(config, model=model)
        if client is not None:
            return client
    return MockLLMClient(model=model)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest test_llm_engine_build_client.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the existing LLM/gate tests to confirm no regression**

Run: `python -m pytest test_llm_entry_gate.py -q`
Expected: PASS.

---

### Task 2: `assistant_engine.py` — snapshot builder + answer path

**Files:**
- Create: `assistant_engine.py`
- Test: `test_assistant_engine.py`
- Modify: `config.json` (add 3 keys after `"scanner_stall_minutes"`)

**Interfaces:**
- Consumes: `llm_engine.build_client`, `llm_engine.log_call`, `jsonl_logger.read_jsonl`, `jsonl_logger.llm_calls_path` (via `llm_engine`).
- Produces:
  - `build_context(question: str, *, status: dict, positions: list, today_trades: list, decisions: list, leaderboard: list, journal: dict | None, known_symbols: list | None = None) -> dict`
  - `assistant_calls_today() -> int`
  - `assistant_budget_remaining(config: dict) -> int`
  - `answer(question: str, history: list, snapshot: dict, config: dict, client=None) -> dict` returning `{"answer": str, "source": str}`.

- [ ] **Step 1: Write the failing tests**

```python
# test_assistant_engine.py
import types
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest test_assistant_engine.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'assistant_engine'`.

- [ ] **Step 3: Implement `assistant_engine.py`**

```python
"""On-demand, read-only Claude analyst over the bot's own data. No trading/order/config writes.

build_context() assembles a compact JSON snapshot across four domains (live status + positions,
today's trades + P&L, recent decisions, strategy leaderboard + journal). answer() calls Claude
once (budget-gated by the SEPARATE assistant cap) and returns grounded prose. Never raises."""

import json
import llm_engine

MAX_DECISIONS = 40
MAX_TRADES = 60
MAX_LEADERBOARD = 15
MAX_HISTORY_TURNS = 6

SYSTEM = (
    "You are the analyst for an operator's OWN intraday trading bot. Answer questions ONLY from "
    "the JSON snapshot of the bot's real data provided below. Rules: (1) Use only the given data; "
    "if it isn't there, say you don't have that data. (2) Never invent numbers. (3) You are "
    "READ-ONLY — you cannot place trades or change settings; if asked to, explain you can only "
    "analyse. (4) Do NOT give buy/sell predictions or financial advice; analyse what the bot did "
    "and why. Be concise, concrete, and cite the numbers from the snapshot."
)


def assistant_calls_today():
    from datetime import datetime
    rows = llm_engine.jsonl_logger.read_jsonl(llm_engine.llm_calls_path())
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(1 for r in rows if str(r.get("time", "")).startswith(today) and r.get("kind") == "assistant")


def assistant_budget_remaining(config):
    cap = int((config or {}).get("assistant_max_daily_calls", 100))
    return max(0, cap - assistant_calls_today())


def _mentioned_symbols(question, known_symbols):
    q = (question or "").upper()
    return [s for s in (known_symbols or []) if s and s.upper() in q]


def build_context(question, *, status, positions, today_trades, decisions, leaderboard,
                  journal, known_symbols=None):
    trades = list(today_trades or [])[-MAX_TRADES:]
    today_pnl = round(sum(float(t.get("pnl") or 0) for t in trades), 2)
    focus = _mentioned_symbols(question, known_symbols)
    snap = {
        "status": {k: (status or {}).get(k) for k in
                   ("paper_trading", "bot_running", "open_positions_count", "daily_pnl",
                    "scanner_last_summary", "scanner_last_loop")},
        "open_positions": positions or [],
        "today_trades": trades,
        "today_pnl": today_pnl,
        "recent_decisions": list(decisions or [])[-MAX_DECISIONS:],
        "leaderboard": list(leaderboard or [])[:MAX_LEADERBOARD],
        "journal": journal,
        "focus_symbols": focus,
    }
    if focus:
        snap["symbol_decisions"] = [d for d in (decisions or []) if d.get("symbol") in focus]
        snap["symbol_trades"] = [t for t in (today_trades or []) if t.get("symbol") in focus]
    return snap


def _prompt(question, history, snapshot):
    turns = ""
    for m in list(history or [])[-MAX_HISTORY_TURNS:]:
        role = "You" if m.get("role") == "assistant" else "Operator"
        turns += f"{role}: {m.get('content', '')}\n"
    return (f"BOT DATA SNAPSHOT (JSON):\n{json.dumps(snapshot, default=str)}\n\n"
            f"{('CONVERSATION SO FAR:\n' + turns + '\n') if turns else ''}"
            f"OPERATOR QUESTION: {question}")


def answer(question, history, snapshot, config, client=None):
    config = config or {}
    if assistant_budget_remaining(config) <= 0:
        return {"answer": "Assistant unavailable: daily question budget reached. It resets tomorrow.",
                "source": "unavailable"}
    if client is None:
        model = config.get("assistant_model") or config.get("llm_model")
        client = llm_engine.build_client(config, model=model)
    if client is None:
        return {"answer": "Assistant unavailable: Claude is disabled or no API key is configured.",
                "source": "unavailable"}
    prompt = _prompt(question, history, snapshot)
    summary = f"assistant: {(question or '')[:80]}"
    try:
        raw = client.complete(SYSTEM, prompt)
        text = (raw or "").strip() or "I couldn't produce an answer from the available data."
        llm_engine.log_call("assistant", summary, text, getattr(client, "model", "?"),
                            getattr(client, "source", "claude"), ok=True)
        return {"answer": text, "source": getattr(client, "source", "claude")}
    except Exception as e:
        llm_engine.log_call("assistant", summary, "", getattr(client, "model", "?"),
                            "error", ok=False, error=str(e))
        return {"answer": f"Assistant error: {e}", "source": "error"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest test_assistant_engine.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Add config keys**

In `config.json`, after the line `"scanner_stall_minutes": 8,` add:

```json
  "assistant_enabled": true,
  "assistant_max_daily_calls": 100,
```

(`assistant_model` is intentionally omitted so it defaults to `llm_model` in code.)

---

### Task 3: `routers/assistant.py` — the endpoint

**Files:**
- Create: `routers/assistant.py`
- Modify: `main.py` (register router near lines 4074-4083)
- Test: `test_assistant_router.py`

**Interfaces:**
- Consumes: `assistant_engine.build_context`, `assistant_engine.answer`; `main.active_positions`, `main.trade_history`, `main.get_ist_now`, `main.get_status`, `main.client.config`; `research_lab.get_leaderboard`, `research_lab.get_db_connection`; `jsonl_logger.read_jsonl`, `jsonl_logger.DECISIONS_FILE`.
- Produces: `POST /api/assistant/ask` → `{"answer": str, "source": str}`.

- [ ] **Step 1: Write the failing test**

```python
# test_assistant_router.py
import types
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test_assistant_router.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'routers.assistant'`.

- [ ] **Step 3: Implement `routers/assistant.py`**

```python
"""Assistant API route. Lazy imports of main/research_lab (they import back into this app) keep
startup free of circular imports, matching routers/research.py."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


def _latest_journal():
    try:
        import research_lab
        conn = research_lab.get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT findings, mistakes, opportunities, strengths, weaknesses, created_at "
                        "FROM research_journal ORDER BY id DESC LIMIT 1;")
            row = cur.fetchone()
        finally:
            conn.close()
        return dict(row) if row else None
    except Exception:
        return None


@router.post("/ask")
def assistant_ask(req: dict):
    import main
    import research_lab
    import jsonl_logger
    import assistant_engine

    question = str((req or {}).get("question", "")).strip()
    history = (req or {}).get("history") or []
    if not question:
        return {"answer": "Ask me something about the bot — e.g. 'how did today go?'", "source": "unavailable"}

    try:
        status = main.get_status()
    except Exception:
        status = {}
    positions = list(main.active_positions.values())
    today = main.get_ist_now().date().isoformat()
    today_trades = [t for t in main.trade_history
                    if str(t.get("exit_time", "")).startswith(today)
                    or str(t.get("entry_time", "")).startswith(today)]
    try:
        decisions = jsonl_logger.read_jsonl(jsonl_logger.DECISIONS_FILE, limit=120)
    except Exception:
        decisions = []
    try:
        leaderboard = research_lab.get_leaderboard()[:15]
    except Exception:
        leaderboard = []
    known_symbols = list(status.get("watchlist") or []) + [p.get("symbol") for p in positions]

    snapshot = assistant_engine.build_context(
        question, status=status, positions=positions, today_trades=today_trades,
        decisions=decisions, leaderboard=leaderboard, journal=_latest_journal(),
        known_symbols=known_symbols)
    return assistant_engine.answer(question, history, snapshot, main.client.config)
```

- [ ] **Step 4: Register the router in `main.py`**

After the line `from routers import research as research_router` (near line 4076) add:

```python
from routers import assistant as assistant_router
```

After `app.include_router(lane_b_router.router)` (near line 4083) add:

```python
app.include_router(assistant_router.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest test_assistant_router.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Confirm `read_jsonl` accepts a `limit` kwarg**

Run: `python -c "import jsonl_logger, inspect; print('limit' in inspect.signature(jsonl_logger.read_jsonl).parameters)"`
Expected: `True`. If `False`, change the router call to `jsonl_logger.read_jsonl(jsonl_logger.DECISIONS_FILE)[-120:]`.

---

### Task 4: Frontend — Assistant chat tab

**Files:**
- Create: `frontend/src/lib/api/assistantApi.ts`
- Create: `frontend/src/features/assistant/AssistantTab.tsx`
- Create: `frontend/src/features/assistant/AssistantTab.css`
- Modify: `frontend/src/lib/stores/useUiStore.ts:3` (add `'assistant'` to `TabId`)
- Modify: `frontend/src/app/TopNav.tsx:14` (add nav entry)
- Modify: `frontend/src/app/App.tsx` (import + render)

**Interfaces:**
- Consumes: `http.post` from `frontend/src/lib/api/http.ts`.
- Produces: `assistantApi.ask(question, history)`; `<AssistantTab />`; `TabId` includes `'assistant'`.

- [ ] **Step 1: Create `assistantApi.ts`**

```ts
import { http } from './http'

export interface AssistantTurn { role: 'user' | 'assistant'; content: string }
export interface AssistantReply { answer: string; source: string }

export const assistantApi = {
  ask: (question: string, history: AssistantTurn[]) =>
    http.post<AssistantReply>('/api/assistant/ask', { question, history }),
}
```

- [ ] **Step 2: Add `'assistant'` to `TabId`**

In `frontend/src/lib/stores/useUiStore.ts` line 3, change:

```ts
export type TabId = 'cockpit' | 'analytics' | 'config' | 'research-lab' | 'learning' | 'news' | 'fundamentals' | 'assistant'
```

- [ ] **Step 3: Add the nav entry**

In `frontend/src/app/TopNav.tsx`, append to the `TABS` array (after the `fundamentals` entry):

```ts
  { id: 'assistant', label: 'Assistant' },
```

- [ ] **Step 4: Create `AssistantTab.tsx`**

```tsx
import { useRef, useState } from 'react'
import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { assistantApi, type AssistantTurn } from '../../lib/api/assistantApi'
import './AssistantTab.css'

const SUGGESTIONS = [
  'How did today go?',
  'Why are there no trades today?',
  'Which strategy is losing money?',
  'What are my open positions doing?',
]

export function AssistantTab() {
  const [turns, setTurns] = useState<AssistantTurn[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  const send = async (q: string) => {
    const question = q.trim()
    if (!question || busy) return
    const history = turns.slice(-6)
    setTurns((t) => [...t, { role: 'user', content: question }])
    setInput('')
    setBusy(true)
    try {
      const reply = await assistantApi.ask(question, history)
      setTurns((t) => [...t, { role: 'assistant', content: reply.answer }])
    } catch (e) {
      setTurns((t) => [...t, { role: 'assistant', content: `Error: ${(e as Error).message}` }])
    } finally {
      setBusy(false)
      requestAnimationFrame(() => endRef.current?.scrollIntoView({ behavior: 'smooth' }))
    }
  }

  return (
    <Panel title="Assistant · ask your bot">
      <div className="mq-assist">
        {turns.length === 0 ? (
          <div className="mq-assist-empty text-faint">
            <p>Ask about your bot's decisions, performance, positions, or strategies. Read-only — I can't place trades.</p>
            <div className="mq-assist-suggest">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="mq-assist-chip" onClick={() => send(s)}>{s}</button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mq-assist-log">
            {turns.map((t, i) => (
              <div key={i} className={`mq-assist-msg mq-assist-${t.role}`}>
                <span className="mq-assist-role">{t.role === 'user' ? 'You' : 'Bot'}</span>
                <div className="mq-assist-text">{t.content}</div>
              </div>
            ))}
            {busy && <div className="mq-assist-msg mq-assist-assistant"><span className="mq-assist-role">Bot</span><div className="mq-assist-text text-faint">thinking…</div></div>}
            <div ref={endRef} />
          </div>
        )}
        <form className="mq-assist-input" onSubmit={(e) => { e.preventDefault(); send(input) }}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask your bot…"
            aria-label="Ask your bot"
            disabled={busy}
          />
          <Button variant="success" onClick={() => send(input)}>Send</Button>
        </form>
      </div>
    </Panel>
  )
}
```

- [ ] **Step 5: Create `AssistantTab.css`**

```css
.mq-assist { display: flex; flex-direction: column; gap: 12px; min-height: 60vh; }
.mq-assist-log { display: flex; flex-direction: column; gap: 12px; overflow-y: auto; max-height: 62vh; padding-right: 6px; }
.mq-assist-msg { display: flex; flex-direction: column; gap: 4px; }
.mq-assist-role { font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.6; }
.mq-assist-text { white-space: pre-wrap; line-height: 1.5; padding: 10px 12px; border-radius: 10px; max-width: 80ch; }
.mq-assist-user .mq-assist-text { align-self: flex-end; background: rgba(80, 200, 255, 0.10); }
.mq-assist-assistant .mq-assist-text { background: rgba(255, 255, 255, 0.04); }
.mq-assist-input { display: flex; gap: 8px; }
.mq-assist-input input { flex: 1; padding: 10px 12px; border-radius: 10px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); color: inherit; }
.mq-assist-suggest { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.mq-assist-chip { padding: 6px 12px; border-radius: 999px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.14); color: inherit; cursor: pointer; }
.mq-assist-chip:hover { background: rgba(80, 200, 255, 0.12); }
```

- [ ] **Step 6: Render the tab in `App.tsx`**

Add the import after line 15 (`import { FundamentalsTab } ...`):

```tsx
import { AssistantTab } from '../features/assistant/AssistantTab'
```

Add the render line after line 55 (`{activeTab === 'fundamentals' && <FundamentalsTab />}`):

```tsx
        {activeTab === 'assistant' && <AssistantTab />}
```

- [ ] **Step 7: Build the frontend**

Run: `cd frontend && npm run build`
Expected: build succeeds; `static/` is updated (the backend serves it). No TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add assistant_engine.py llm_engine.py routers/assistant.py main.py config.json test_llm_engine_build_client.py test_assistant_engine.py test_assistant_router.py frontend/ static/ docs/superpowers
git commit -m "feat: read-only Claude assistant tab (talk to your bot)"
```

---

### Task 5: Live smoke test + verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full new backend test set**

Run: `python -m pytest test_llm_engine_build_client.py test_assistant_engine.py test_assistant_router.py -q`
Expected: PASS (all).

- [ ] **Step 2: Real Claude smoke test (uses the live key, 1 call)**

Create `scratchpad/assist_smoke.py`:

```python
import json, assistant_engine
cfg = json.load(open("config.json", encoding="utf-8"))
snap = assistant_engine.build_context("how did today go?",
    status={"paper_trading": True, "daily_pnl": 517.78, "scanner_last_summary": "40 checked"},
    positions=[], today_trades=[{"symbol":"RELIANCE","pnl":25.0,"reason":"TARGET-2 HIT"}],
    decisions=[], leaderboard=[], journal=None)
print(assistant_engine.answer("how did today go?", [], snap, cfg))
```

Run: `PYTHONPATH=. python scratchpad/assist_smoke.py`
Expected: `source` is `claude` and the answer references the +25 / today's P&L (grounded, no fabrication).

- [ ] **Step 3: Verify in the running app**

Restart the bot (stop the `:5000` python; the watchdog restarts it), open the dashboard, click the **Assistant** tab, ask "how did today go?" and confirm a grounded answer renders. Confirm the bot is still in **paper** mode and trading is unaffected.

- [ ] **Step 4: Update HANDOFF.md**

Add a one-line note under the latest session block: "Assistant tab (read-only Claude Q&A over bot data) added — `assistant_engine.py`, `routers/assistant.py`, `AssistantTab.tsx`; separate `assistant_max_daily_calls` budget."
