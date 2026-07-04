"""
promotion_gate.py — Section 5 Lane B's GATED promotion pipeline + data/proposals.jsonl lifecycle.

A proposal (from llm_engine.generate_proposal — Claude or heuristic) is an INACTIVE candidate. It
becomes eligible for the leaderboard/live ONLY after passing the Promotion Gate, which requires
ALL of:
  * backtest on stored history with expectancy >= config["min_backtest_expectancy"]
    (and drawdown within config["max_backtest_drawdown"] if provided), AND
  * a minimum number of paper trades >= config["min_paper_trades"] with positive expectancy.
If config["require_human_approval"] is True, a passing proposal parks in 'awaiting_approval' until
someone clicks Approve in the UI — nothing self-modifies into live silently (Section 0 rule 5).

The full lifecycle (proposed -> backtesting -> validating -> awaiting_approval/promoted/rejected)
with timestamps + approver is retained per proposal so the UI can show the whole decision trail.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

import jsonl_logger

# lifecycle statuses
PROPOSED = "proposed"
BACKTESTING = "backtesting"
VALIDATING = "validating"          # passed backtest, accumulating paper trades
AWAITING_APPROVAL = "awaiting_approval"
PROMOTED = "promoted"
REJECTED = "rejected"

TERMINAL = {PROMOTED, REJECTED}


def proposals_path() -> str:
    return os.path.join(jsonl_logger.DATA_DIR, "proposals.jsonl")


def _now() -> str:
    return datetime.now().isoformat()


# ── store (append-only file, rewritten in place on status changes) ─────────────────────

def load_proposals() -> list:
    return jsonl_logger.read_jsonl(proposals_path())


def get_proposal(proposal_id: str) -> dict | None:
    for p in load_proposals():
        if p.get("id") == proposal_id:
            return p
    return None


def _save_all(proposals: list) -> None:
    os.makedirs(jsonl_logger.DATA_DIR, exist_ok=True)
    with open(proposals_path(), "w", encoding="utf-8") as f:
        for p in proposals:
            f.write(json.dumps(p) + "\n")


def _append(proposal: dict) -> None:
    os.makedirs(jsonl_logger.DATA_DIR, exist_ok=True)
    with open(proposals_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(proposal) + "\n")


def _update(proposal_id: str, mutate) -> dict | None:
    proposals = load_proposals()
    updated = None
    for p in proposals:
        if p.get("id") == proposal_id:
            mutate(p)
            updated = p
            break
    if updated is not None:
        _save_all(proposals)
    return updated


def _event(proposal: dict, status: str, note: str = "", extra: dict | None = None) -> None:
    proposal["status"] = status
    proposal.setdefault("lifecycle", []).append({
        "at": _now(), "status": status, "note": note, **(extra or {})
    })


# ── creation ────────────────────────────────────────────────────────────────────────

def add_proposal(proposal: dict) -> dict:
    """Register a new candidate as INACTIVE ('proposed'). Never trades."""
    record = {
        "id": str(uuid.uuid4()),
        "created_at": _now(),
        "title": proposal.get("title", "Untitled proposal"),
        "rationale": proposal.get("rationale", ""),
        "strategy": proposal.get("strategy"),
        "param_changes": proposal.get("param_changes", {}),
        "source": proposal.get("source", "heuristic"),
        "status": PROPOSED,
        "backtest": None,
        "paper": {"trades": 0, "expectancy": None},
        "approver": None,
        "lifecycle": [{"at": _now(), "status": PROPOSED, "note": "candidate registered (inactive)"}],
    }
    _append(record)
    return record


# ── evidence recording ────────────────────────────────────────────────────────────────

def record_backtest(proposal_id: str, result: dict) -> dict | None:
    """result: {'expectancy': float, 'trades': int, 'max_drawdown': float, ...}"""
    def m(p):
        p["backtest"] = result
        _event(p, BACKTESTING, "backtest recorded", {"result": result})
    return _update(proposal_id, m)


def record_paper_progress(proposal_id: str, trades: int, expectancy: float | None) -> dict | None:
    def m(p):
        p["paper"] = {"trades": int(trades), "expectancy": expectancy}
        _event(p, VALIDATING, "paper-validation progress", {"trades": trades, "expectancy": expectancy})
    return _update(proposal_id, m)


# ── the gate (pure, unit-testable — DoD #5) ────────────────────────────────────────────

def gate_decision(backtest: dict | None, paper: dict | None, config: dict | None) -> dict:
    """Pure evaluation of the Promotion Gate against thresholds. Returns
    {'passes': bool, 'require_approval': bool, 'reasons': [str]} — no I/O, no state."""
    config = config or {}
    min_bt_exp = float(config.get("min_backtest_expectancy", 0.1))
    max_bt_dd = config.get("max_backtest_drawdown")  # optional; None -> not enforced
    min_paper = int(config.get("min_paper_trades", 30))
    require_approval = bool(config.get("require_human_approval", True))

    reasons = []
    backtest = backtest or {}
    paper = paper or {}

    bt_exp = backtest.get("expectancy")
    if bt_exp is None:
        reasons.append("no backtest yet")
    elif bt_exp < min_bt_exp:
        reasons.append(f"backtest expectancy {bt_exp} < {min_bt_exp}")

    if max_bt_dd is not None and backtest.get("max_drawdown") is not None:
        if backtest["max_drawdown"] < -abs(float(max_bt_dd)):
            reasons.append(f"backtest drawdown {backtest['max_drawdown']} beyond {-abs(float(max_bt_dd))}")

    paper_trades = int(paper.get("trades", 0) or 0)
    paper_exp = paper.get("expectancy")
    if paper_trades < min_paper:
        reasons.append(f"paper trades {paper_trades} < {min_paper}")
    if paper_exp is None:
        reasons.append("no paper expectancy yet")
    elif paper_exp <= 0:
        reasons.append(f"paper expectancy {paper_exp} <= 0")

    passes = len(reasons) == 0
    return {"passes": passes, "require_approval": require_approval, "reasons": reasons}


def evaluate(proposal_id: str, config: dict | None) -> dict | None:
    """Run the gate on a stored proposal and advance its lifecycle accordingly:
      fail (with a backtest present, unfixable) -> rejected;
      fail (still gathering evidence)           -> validating;
      pass + require_human_approval             -> awaiting_approval;
      pass + no approval required               -> promoted.
    Terminal proposals are left unchanged."""
    p = get_proposal(proposal_id)
    if not p or p.get("status") in TERMINAL:
        return p
    decision = gate_decision(p.get("backtest"), p.get("paper"), config)

    def m(pp):
        if decision["passes"]:
            if decision["require_approval"]:
                _event(pp, AWAITING_APPROVAL, "passed gate; awaiting human approval", {"gate": decision})
            else:
                _event(pp, PROMOTED, "passed gate; auto-promoted (approval not required)", {"gate": decision})
        else:
            # Hard reject only if a backtest exists and it's the backtest that failed (won't improve
            # with more paper trades). Otherwise keep validating.
            bt = pp.get("backtest") or {}
            bt_failed = bt.get("expectancy") is not None and any("backtest" in r for r in decision["reasons"])
            if bt_failed:
                _event(pp, REJECTED, "failed backtest threshold", {"gate": decision})
            else:
                _event(pp, VALIDATING, "not yet eligible", {"gate": decision})

    return _update(proposal_id, m)


# ── human approval (Section 5 / Tab 7) ─────────────────────────────────────────────────

def approve(proposal_id: str, approver: str = "operator") -> dict | None:
    def m(p):
        if p.get("status") in TERMINAL:
            return
        p["approver"] = approver
        _event(p, PROMOTED, f"approved by {approver}", {"approver": approver})
    return _update(proposal_id, m)


def reject(proposal_id: str, approver: str = "operator", reason: str = "") -> dict | None:
    def m(p):
        if p.get("status") in TERMINAL:
            return
        p["approver"] = approver
        _event(p, REJECTED, f"rejected by {approver}: {reason}", {"approver": approver, "reason": reason})
    return _update(proposal_id, m)
