# Design: "Talk to Your Bot" — On-Demand Claude Analyst

**Date:** 2026-07-16
**Status:** Approved (design)
**Branch:** self-improve

## Purpose

A dashboard chat where the operator asks natural-language questions and Claude answers,
grounded **only** in the bot's own real data. It makes the system legible ("why did you skip
RELIANCE?", "how did today go?", "what keeps losing?") without touching the trading path.

Covers four question domains (all selected by the operator):
1. **Why it traded / skipped** — decision log + gate reasons.
2. **Performance & P&L** — trade history.
3. **Live status now** — open positions + scanner state.
4. **Strategy & learning** — leaderboard + recent lessons/journal.

## Hard Rules (safety)

1. **Read-only.** The assistant can read data and produce text. It has **no** capability —
   architecturally, not just by prompt — to place/modify/cancel orders, change config, or
   mutate any state. It can never trade.
2. **No fabrication, no advice.** The system prompt forces Claude to answer only from the
   supplied data, say "I don't have that data" when it is absent, never invent numbers, and
   never give buy/sell predictions or financial advice. It analyses the bot's own activity.
3. **Fail-soft.** If Claude is disabled / over-budget / errors, the endpoint returns a clear
   message, never a 500 or crash. (Unlike the entry gate, which is fail-closed — here failing
   soft is correct because nothing trades.)

## Architecture

Three isolated units plus config:

### 1. `assistant_engine.py` (new — pure, testable, no FastAPI/network coupling)
- `build_context(question, *, status, positions, today_trades, decisions, leaderboard, journal)`
  → a compact JSON snapshot across all four domains. If the question names watchlist/known
  symbols, it also includes that symbol's specific recent decisions + trades. Sizes are
  bounded (e.g. last ~40 decisions, today's trades, top ~15 leaderboard rows, latest journal).
- `answer(question, history, snapshot, config, client=None)` → builds the prompt
  (system + snapshot + last few turns + question), calls Claude once via
  `llm_engine.get_client`, logs the call, returns `{answer, source, ok}`. Never raises.
- Budget: honored via a dedicated counter (see Config) so chat never starves the trading gate.

### 2. `routers/assistant.py` (new) — `POST /api/assistant/ask`
- Request: `{ "question": str, "history": [{role, content}, ...] }` (history optional, bounded).
- Gathers existing data (active positions, today's trade_history, `/api/decisions` source,
  `research_lab.get_leaderboard()`, latest research journal, status snapshot), calls
  `assistant_engine.answer`, returns `{ "answer": str, "source": str }`.
- Adds nothing to the scanner / order path. Read-only over in-memory + SQLite data.

### 3. `AssistantTab.tsx` (new frontend, Midnight Quant style)
- Chat panel: scrollable message list + input box + send. Shows a "thinking" state during the
  call. Keeps the last ~6 turns client-side and sends them as `history` for follow-ups.
- Registered as a new tab in the dashboard nav; `assistantApi.ask()` in the api layer.

## Data Flow

```
User types question in Assistant tab
  → POST /api/assistant/ask {question, history}
  → gather data (positions, today's trades, recent decisions, leaderboard, journal, status)
  → assistant_engine.build_context(...) → compact snapshot (+ symbol filter if named)
  → assistant_engine.answer(...) → one Claude call (claude-sonnet-5)
  → {answer, source}
  → rendered in the chat
```

## Config (new keys; code defaults so config edits are optional)

- `assistant_enabled` (default `true`)
- `assistant_max_daily_calls` (default `100`) — separate from `llm_max_daily_calls` (50, trading)
- `assistant_model` (default = `llm_model`, i.e. `claude-sonnet-5`)

Calls logged via `llm_engine.log_call(kind="assistant", ...)`; the daily counter reads
`data/llm_calls.jsonl` filtered to `kind == "assistant"`.

## Error Handling

- Claude unavailable / over budget → `{answer: "Assistant unavailable: <reason>", source: "unavailable"}`.
- Unparseable / empty model output → returned as-is (it's prose, not JSON) with a soft note.
- Missing data domain (e.g. no trades today) → snapshot marks it empty; Claude says so.
- Endpoint never raises to the client; internal exceptions become a soft assistant message.

## Testing

- `assistant_engine.build_context`: returns all four domain keys; respects the size bounds;
  symbol-filtering includes a named symbol's rows and excludes others; empty inputs are safe.
- `assistant_engine.answer`: with a scripted `MockLLMClient` returns that text; over-budget →
  the friendly unavailable message; never raises on a client error.
- Endpoint: mocked engine → returns `{answer}`; malformed request → 422 (FastAPI validation).
- Final: one real smoke call with the live key confirming a grounded answer.

## Out of Scope (v1 — YAGNI)

Free-form tool-use / agentic retrieval, streaming responses, server-side long-term chat
memory, voice, and any write/trade capability. All are clean later additions.
