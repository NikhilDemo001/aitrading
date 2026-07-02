"""Unit tests for leaderboard.py — Lane A's recency-weighted, regime/time-bucket-keyed
strategy stats, the minimum-sample fallback rule, and the selector-reasoning explainer."""

import shutil

import pytest

import jsonl_logger
import leaderboard


@pytest.fixture(autouse=True)
def isolate_files(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(jsonl_logger, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(jsonl_logger, "WINS_FILE", str(data_dir / "wins.jsonl"))
    monkeypatch.setattr(jsonl_logger, "LOSSES_FILE", str(data_dir / "losses.jsonl"))
    monkeypatch.setattr(leaderboard, "STATS_FILE", str(data_dir / "strategy_stats.json"))
    yield
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)


def make_trade(strategy, regime, bucket, pnl, exit_time, r_multiple=1.0, holding=20.0):
    return {
        "strategy": strategy, "market_regime": regime, "time_of_day_bucket": bucket,
        "pnl": pnl, "r_multiple": r_multiple, "timestamp_exit": exit_time,
        "holding_minutes": holding,
    }


def test_base_strategy_name_normalizes_directional_variants():
    assert leaderboard.base_strategy_name("ORB-Buy") == "ORB"
    assert leaderboard.base_strategy_name("ORB-Short") == "ORB"
    assert leaderboard.base_strategy_name("CandlestickConfluence-Buy") == "CandlestickConfluence"
    assert leaderboard.base_strategy_name("SupportResistance-Breakout-Buy") == "SupportResistance"
    assert leaderboard.base_strategy_name("Unknown-Weird") == "Unknown-Weird"


def test_compute_stats_groups_by_strategy_regime_bucket():
    trades = [
        make_trade("ORB-Buy", "trending_up", "0915_1000", 100.0, "2026-07-01T09:30:00"),
        make_trade("ORB-Short", "trending_up", "0915_1000", -50.0, "2026-07-01T09:45:00"),
        make_trade("TrendFollow-Buy", "choppy", "1000_1045", 30.0, "2026-07-01T10:15:00"),
    ]
    stats = leaderboard.compute_stats(trades)
    assert "ORB|trending_up|0915_1000" in stats
    assert "TrendFollow|choppy|1000_1045" in stats
    orb_combo = stats["ORB|trending_up|0915_1000"]
    assert orb_combo["trades"] == 2
    assert orb_combo["win_rate"] == 0.5


def test_recency_weighting_favors_recent_trades():
    """Two combos with identical raw average P&L, but one has its win recent and the other has
    its win old — the recency-weighted score must differ, proving recency actually matters."""
    old_win_recent_loss = [
        make_trade("ORB-Buy", "trending_up", "0915_1000", 100.0, "2026-06-01T09:30:00"),
        make_trade("ORB-Buy", "trending_up", "0915_1000", -100.0, "2026-07-01T09:30:00"),
    ]
    recent_win_old_loss = [
        make_trade("VWAP-Pullback-Buy", "trending_up", "0915_1000", -100.0, "2026-06-01T09:30:00"),
        make_trade("VWAP-Pullback-Buy", "trending_up", "0915_1000", 100.0, "2026-07-01T09:30:00"),
    ]
    stats = leaderboard.compute_stats(old_win_recent_loss + recent_win_old_loss, halflife=10)
    orb_score = stats["ORB|trending_up|0915_1000"]["recency_weighted_score"]
    vwap_score = stats["VWAP-Pullback|trending_up|0915_1000"]["recency_weighted_score"]
    # Both have raw average pnl of 0, but VWAP's win is more recent -> higher weighted score.
    assert vwap_score > orb_score


def test_rebuild_reads_jsonl_and_writes_stats_file():
    jsonl_logger.log_trade({
        "symbol": "RELIANCE", "strategy": "ORB-Buy", "direction": "LONG", "quantity": 10,
        "entry_price": 100.0, "entry_time": "2026-07-01T09:20:00", "exit_price": 102.0,
        "exit_time": "2026-07-01T09:30:00", "pnl": 20.0, "reason": "TARGET-2 HIT",
        "regime": "trending_up", "atr_at_entry": 1.0,
    }, mode="paper")

    stats = leaderboard.rebuild(halflife=40)
    assert len(stats) == 1
    reloaded = leaderboard.load_stats()
    assert reloaded == stats


def test_min_samples_fallback_rule():
    trades = [make_trade("ORB-Buy", "trending_up", "0915_1000", 10.0, f"2026-07-01T09:{i:02d}:00") for i in range(5)]
    stats = leaderboard.compute_stats(trades)

    # Only 5 trades -> below min_samples=15 -> no combo qualifies -> None (fall back to default).
    order = leaderboard.get_strategy_order_for("trending_up", "0915_1000", min_samples=15, stats=stats)
    assert order is None

    # Lower the bar and it qualifies.
    order2 = leaderboard.get_strategy_order_for("trending_up", "0915_1000", min_samples=5, stats=stats)
    assert order2 == ["ORB"]


def test_get_strategy_order_ranks_by_recency_weighted_score_descending():
    trades = (
        [make_trade("ORB-Buy", "choppy", "1000_1045", 50.0, f"2026-07-01T10:{i:02d}:00") for i in range(20)]
        + [make_trade("MeanReversion-Buy", "choppy", "1000_1045", 10.0, f"2026-07-01T10:{i:02d}:30") for i in range(20)]
    )
    stats = leaderboard.compute_stats(trades)
    order = leaderboard.get_strategy_order_for("choppy", "1000_1045", min_samples=15, stats=stats)
    assert order[0] == "ORB"  # higher avg pnl -> higher score -> ranked first


def test_explain_pick_reports_insufficient_samples():
    stats = {}
    reason = leaderboard.explain_pick("trending_up", "0915_1000", "ORB-Buy", min_samples=15, stats=stats)
    assert "insufficient samples" in reason.lower()


def test_explain_pick_reports_stats_when_qualified():
    trades = [make_trade("ORB-Buy", "trending_up", "0915_1000", 50.0, f"2026-07-01T09:{i:02d}:00") for i in range(20)]
    stats = leaderboard.compute_stats(trades)
    reason = leaderboard.explain_pick("trending_up", "0915_1000", "ORB-Buy", min_samples=15, stats=stats)
    assert "recency-weighted score" in reason.lower()
    assert "20 trades" in reason


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
