"""Phase 7: Lane B proposals + LLM reasoning (Section 5 / Tab 7 + Tab 6).

Moved from main.py. `configure(...)` injects the live client config (main owns it);
`import llm_engine` stays lazy as in the original.
"""

from collections.abc import Callable

from fastapi import APIRouter, HTTPException

import promotion_gate

router = APIRouter(tags=["lane-b"])

_get_config: Callable[[], dict] | None = None


def configure(get_config: Callable[[], dict]) -> None:
    global _get_config
    _get_config = get_config


@router.get("/api/proposals")
def get_proposals():
    """Full lifecycle per candidate (proposed → backtest → paper-validation → promoted/rejected)
    with timestamps + approver — the Promotion-Gate audit trail (Tab 7)."""
    try:
        return promotion_gate.load_proposals()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str, req: dict | None = None):
    """Human approval (respects require_human_approval). Promotes an awaiting-approval candidate."""
    try:
        approver = (req or {}).get("approver", "operator")
        p = promotion_gate.approve(proposal_id, approver=approver)
        if not p:
            raise HTTPException(404, "proposal not found")
        return {"status": "success", "proposal": p}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, req: dict | None = None):
    try:
        req = req or {}
        p = promotion_gate.reject(proposal_id, approver=req.get("approver", "operator"), reason=req.get("reason", ""))
        if not p:
            raise HTTPException(404, "proposal not found")
        return {"status": "success", "proposal": p}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/llm-status")
def llm_status():
    """Read-only (no spend): whether the Claude engine is enabled, keyed, and its remaining daily
    call budget — so the UI/operator can see Lane B's live state at a glance."""
    try:
        import llm_engine
        cfg = _get_config() if _get_config else {}
        return {
            "enabled": llm_engine.is_enabled(cfg),
            "configured_on": bool(cfg.get("llm_enabled", False)),
            "key_available": llm_engine.api_key_available(),
            "model": cfg.get("llm_model") or llm_engine.DEFAULT_MODEL,
            "calls_today": llm_engine.calls_today(),
            "daily_cap": int(cfg.get("llm_max_daily_calls", 50)),
            "budget_remaining": llm_engine.budget_remaining(cfg),
        }
    except Exception as e:
        raise HTTPException(500, str(e))
