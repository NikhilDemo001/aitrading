"""
Integration test for orchestrator.py — proves DoD #1/#2: the full continuous loop runs in
paper mode against MockBroker with zero live credentials, and produces trades in
data/wins.jsonl / data/losses.jsonl with the full Section-6 schema.
"""

import os
import shutil
from datetime import datetime

import pytest

import jsonl_logger
from mock_broker import MockBroker
from orchestrator import Orchestrator

# A fixed timestamp inside the trading window (09:15–15:15 IST). The orchestrator's
# run_tick_for_all_symbols() defaults to datetime.now(), so passing an explicit in-session
# time keeps these session tests deterministic regardless of the wall-clock hour they run at
# (otherwise they silently pass/fail depending on whether the machine clock is past square-off).
IN_SESSION = datetime(2026, 7, 1, 11, 0)


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(jsonl_logger, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(jsonl_logger, "WINS_FILE", str(data_dir / "wins.jsonl"))
    monkeypatch.setattr(jsonl_logger, "LOSSES_FILE", str(data_dir / "losses.jsonl"))
    monkeypatch.setattr(jsonl_logger, "DECISIONS_FILE", str(data_dir / "decisions.log"))
    yield
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)


def test_orchestrator_constructs_with_zero_live_credentials():
    """No UpstoxClient, no .env, no network — MockBroker only."""
    orch = Orchestrator(broker=MockBroker(seed=1))
    assert orch.broker is not None
    assert orch.open_positions == {}
    assert orch.trade_history == []


def test_simulated_session_produces_trades_with_full_jsonl_schema():
    orch = Orchestrator(broker=MockBroker(seed=3))
    for _ in range(60):
        orch.run_tick_for_all_symbols(now=IN_SESSION)

    assert len(orch.trade_history) > 0, "expected at least one closed trade over 60 ticks"

    all_rows = jsonl_logger.read_jsonl(jsonl_logger.WINS_FILE) + jsonl_logger.read_jsonl(jsonl_logger.LOSSES_FILE)
    assert len(all_rows) == len(orch.trade_history)

    required_fields = {
        "trade_id", "mode", "symbol", "strategy", "direction", "timestamp_entry",
        "timestamp_exit", "entry_price", "exit_price", "quantity", "pnl", "pnl_pct",
        "r_multiple", "exit_reason", "market_regime", "candlestick_patterns",
        "time_of_day_bucket", "indicators_at_entry", "lesson", "tags",
    }
    for row in all_rows:
        assert required_fields.issubset(row.keys())
        assert row["mode"] == "paper"
        assert row["symbol"].startswith("NSE:")


def test_wins_and_losses_are_split_correctly_by_pnl_sign():
    orch = Orchestrator(broker=MockBroker(seed=5))
    for _ in range(80):
        orch.run_tick_for_all_symbols(now=IN_SESSION)

    wins = jsonl_logger.read_jsonl(jsonl_logger.WINS_FILE)
    losses = jsonl_logger.read_jsonl(jsonl_logger.LOSSES_FILE)
    for row in wins:
        assert row["pnl"] >= 0
    for row in losses:
        assert row["pnl"] < 0


def test_decisions_log_records_skip_pick_and_trade_entries():
    orch = Orchestrator(broker=MockBroker(seed=2))
    for _ in range(40):
        orch.run_tick_for_all_symbols(now=IN_SESSION)

    decisions = jsonl_logger.read_jsonl(jsonl_logger.DECISIONS_FILE)
    assert len(decisions) > 0
    types_seen = {d["type"] for d in decisions}
    # Over 40 ticks across 2 symbols we should see at least skips and/or picks logged.
    assert types_seen & {"skip", "pick", "trade"}


def test_daily_loss_kill_switch_halts_and_flattens():
    """Section 0 rule 2, live mode: once total daily P&L breaches -max_daily_loss, the next
    tick must force-flatten every open position via the freeze path — not wait for the
    position's own stop-loss. mode='live' because paper mode intentionally has no daily-loss
    limit (the dashboard shows 'Unlimited (Paper Trading)'); MockBroker still means zero real
    credentials or network. The position is seeded deep underwater with a stop so wide the
    normal stop-loss exit can never fire — only the kill-switch flatten can close it, so this
    proves the freeze wiring itself, deterministically (no seed luck)."""
    orch = Orchestrator(broker=MockBroker(seed=9), config={"max_daily_loss": 500.0, "mode": "live"})
    orch.open_positions["RELIANCE"] = {
        "symbol": "RELIANCE", "instrument_key": "RELIANCE", "strategy": "ORB-Buy",
        "direction": "LONG", "quantity": 10, "entry_price": 1000.0,
        "entry_time": datetime(2026, 7, 1, 10, 0).isoformat(),
        "stop_loss": 1.0, "target": 100000.0, "target_2": 100000.0,
        "current_price": 940.0, "pnl": -600.0, "atr_at_entry": 5.0,
        "regime": "trending_up", "htf_trend": "neutral", "market_context": {},
    }
    orch.run_tick_for_all_symbols(now=IN_SESSION)
    assert orch.open_positions == {}, "kill switch must force-flatten all open positions"
    assert any("kill-switch" in t["reason"].lower() for t in orch.trade_history)
    # The freeze must persist: no new entries for the rest of the session.
    for _ in range(10):
        orch.run_tick_for_all_symbols(now=IN_SESSION)
    assert orch.open_positions == {}, "frozen session must not open new positions"


def test_run_end_of_day_writes_history_snapshots(tmp_path, monkeypatch):
    """DoD #9: after a session, run_end_of_day freezes the daily leaderboard/pattern/feature/KPI
    snapshots the date-range & as-of UI reads from."""
    import leaderboard
    import history
    monkeypatch.setattr(leaderboard, "STATS_FILE", str(tmp_path / "data" / "strategy_stats.json"))

    orch = Orchestrator(broker=MockBroker(seed=3))
    for _ in range(60):
        orch.run_tick_for_all_symbols(now=IN_SESSION)
    snap = orch.run_end_of_day(now=IN_SESSION)

    date_str = IN_SESSION.strftime("%Y-%m-%d")
    assert snap["date"] == date_str
    assert os.path.exists(history.leaderboard_path(date_str))
    assert len(history.load_kpi_daily()) == 1
    # As-of reconstruction resolves this exact day.
    assert history.load_leaderboard_asof(date_str) is not None


def test_square_off_time_flattens_positions():
    orch = Orchestrator(broker=MockBroker(seed=11))
    # Manually open a position, then tick at a time past square_off_time.
    orch.open_positions["RELIANCE"] = {
        "symbol": "RELIANCE", "instrument_key": "RELIANCE", "strategy": "ORB-Buy",
        "direction": "LONG", "quantity": 10, "entry_price": 1000.0,
        "entry_time": datetime(2026, 7, 1, 10, 0).isoformat(),
        "stop_loss": 990.0, "target": 1010.0, "target_2": 1010.0,
        "current_price": 1000.0, "pnl": 0.0, "atr_at_entry": 5.0,
        "regime": "trending_up", "htf_trend": "neutral", "market_context": {},
    }
    orch.run_tick_for_all_symbols(now=datetime(2026, 7, 1, 15, 20))
    assert "RELIANCE" not in orch.open_positions
    assert any("square-off" in t["reason"].lower() for t in orch.trade_history)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
