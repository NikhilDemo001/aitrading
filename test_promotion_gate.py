"""
Tests for promotion_gate.py — Section 5 Promotion Gate + proposals.jsonl lifecycle (DoD #5).
Isolated to a tmp data dir. The gate function itself is pure and tested independently.
"""

import os
import shutil

import pytest

import jsonl_logger
import promotion_gate as pg


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(jsonl_logger, "DATA_DIR", str(data_dir))
    os.makedirs(data_dir, exist_ok=True)
    yield
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)


CONFIG = {"min_backtest_expectancy": 0.1, "min_paper_trades": 30, "require_human_approval": True}


# ── pure gate function ──────────────────────────────────────────────────────────────────

def test_gate_fails_with_no_evidence():
    d = pg.gate_decision(None, None, CONFIG)
    assert d["passes"] is False
    assert any("backtest" in r for r in d["reasons"])


def test_gate_fails_on_weak_backtest():
    d = pg.gate_decision({"expectancy": 0.05, "trades": 200}, {"trades": 40, "expectancy": 20}, CONFIG)
    assert d["passes"] is False
    assert any("backtest expectancy" in r for r in d["reasons"])


def test_gate_fails_on_insufficient_paper():
    d = pg.gate_decision({"expectancy": 0.5, "trades": 200}, {"trades": 10, "expectancy": 20}, CONFIG)
    assert d["passes"] is False
    assert any("paper trades" in r for r in d["reasons"])


def test_gate_passes_when_all_thresholds_met():
    d = pg.gate_decision({"expectancy": 0.5, "trades": 200}, {"trades": 40, "expectancy": 25}, CONFIG)
    assert d["passes"] is True
    assert d["require_approval"] is True


def test_gate_respects_drawdown_cap_when_provided():
    cfg = {**CONFIG, "max_backtest_drawdown": 500}
    d = pg.gate_decision({"expectancy": 0.5, "trades": 200, "max_drawdown": -900},
                         {"trades": 40, "expectancy": 25}, cfg)
    assert d["passes"] is False
    assert any("drawdown" in r for r in d["reasons"])


# ── lifecycle over the store ────────────────────────────────────────────────────────────

def test_add_proposal_is_inactive():
    p = pg.add_proposal({"title": "T", "strategy": "ORB", "source": "heuristic"})
    assert p["status"] == pg.PROPOSED
    assert pg.get_proposal(p["id"])["status"] == pg.PROPOSED


def test_weak_backtest_gets_rejected():
    p = pg.add_proposal({"title": "T", "strategy": "ORB"})
    pg.record_backtest(p["id"], {"expectancy": 0.0, "trades": 100})
    pg.evaluate(p["id"], CONFIG)
    assert pg.get_proposal(p["id"])["status"] == pg.REJECTED


def test_good_backtest_insufficient_paper_stays_validating():
    p = pg.add_proposal({"title": "T", "strategy": "ORB"})
    pg.record_backtest(p["id"], {"expectancy": 0.5, "trades": 200})
    pg.record_paper_progress(p["id"], trades=5, expectancy=10)
    pg.evaluate(p["id"], CONFIG)
    assert pg.get_proposal(p["id"])["status"] == pg.VALIDATING


def test_full_pass_awaits_human_approval_then_promotes():
    p = pg.add_proposal({"title": "T", "strategy": "ORB"})
    pg.record_backtest(p["id"], {"expectancy": 0.5, "trades": 200})
    pg.record_paper_progress(p["id"], trades=40, expectancy=25)
    pg.evaluate(p["id"], CONFIG)
    assert pg.get_proposal(p["id"])["status"] == pg.AWAITING_APPROVAL
    pg.approve(p["id"], approver="nikhil")
    prom = pg.get_proposal(p["id"])
    assert prom["status"] == pg.PROMOTED and prom["approver"] == "nikhil"


def test_full_pass_auto_promotes_when_approval_not_required():
    cfg = {**CONFIG, "require_human_approval": False}
    p = pg.add_proposal({"title": "T", "strategy": "ORB"})
    pg.record_backtest(p["id"], {"expectancy": 0.5, "trades": 200})
    pg.record_paper_progress(p["id"], trades=40, expectancy=25)
    pg.evaluate(p["id"], cfg)
    assert pg.get_proposal(p["id"])["status"] == pg.PROMOTED


def test_reject_is_terminal():
    p = pg.add_proposal({"title": "T", "strategy": "ORB"})
    pg.reject(p["id"], approver="nikhil", reason="not convinced")
    assert pg.get_proposal(p["id"])["status"] == pg.REJECTED
    # A later approve must not resurrect it.
    pg.approve(p["id"])
    assert pg.get_proposal(p["id"])["status"] == pg.REJECTED


def test_lifecycle_trail_accumulates():
    p = pg.add_proposal({"title": "T", "strategy": "ORB"})
    pg.record_backtest(p["id"], {"expectancy": 0.5, "trades": 200})
    pg.record_paper_progress(p["id"], trades=40, expectancy=25)
    pg.evaluate(p["id"], CONFIG)
    pg.approve(p["id"], approver="nikhil")
    trail = pg.get_proposal(p["id"])["lifecycle"]
    statuses = [e["status"] for e in trail]
    assert statuses[0] == pg.PROPOSED and statuses[-1] == pg.PROMOTED
    assert pg.AWAITING_APPROVAL in statuses


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
