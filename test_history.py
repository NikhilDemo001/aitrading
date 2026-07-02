"""
Tests for history.py — the daily learning-history snapshots that power the date-range /
as-of-date / compare UI (Section 6 + DoD #9). Fully isolated: monkeypatches jsonl_logger.DATA_DIR
to a tmp dir so no real data/ files are touched.
"""

import json
import os
import shutil

import pytest

import jsonl_logger
import history


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


def _trade(pnl, date="2026-07-01", exit_hhmm="10:00", **kw):
    base = {
        "trade_id": kw.get("trade_id", os.urandom(4).hex()),
        "mode": "paper",
        "symbol": kw.get("symbol", "NSE:RELIANCE"),
        "strategy": kw.get("strategy", "ORB-Buy"),
        "direction": "long",
        "timestamp_entry": f"{date}T09:30:00",
        "timestamp_exit": f"{date}T{exit_hhmm}:00",
        "pnl": pnl,
        "r_multiple": kw.get("r_multiple", 1.5 if pnl >= 0 else -1.0),
        "market_regime": kw.get("regime", "trending_up"),
        "candlestick_patterns": kw.get("patterns", ["bullish_engulfing"]),
        "time_of_day_bucket": kw.get("bucket", "0945_1030"),
        "indicators_at_entry": kw.get("indicators", {"rsi": 62, "volume_ratio": 1.7, "atr": 9.4, "ema_20": 2945.0}),
        "holding_minutes": kw.get("holding_minutes", 18),
    }
    return base


def _seed(trades):
    jsonl_logger._ensure_data_dir()
    for t in trades:
        target = jsonl_logger.WINS_FILE if t["pnl"] >= 0 else jsonl_logger.LOSSES_FILE
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(t) + "\n")


def test_write_all_creates_all_four_artifacts():
    _seed([_trade(350), _trade(-120), _trade(200, exit_hhmm="11:00", bucket="1030_1115")])
    result = history.write_all("2026-07-01", capital_start=100000)

    assert os.path.exists(history.leaderboard_path("2026-07-01"))
    assert os.path.exists(history._path(history.PATTERN_STATS_FILE))
    assert os.path.exists(history._path(history.FEATURE_STATS_FILE))
    assert os.path.exists(history._path(history.KPI_DAILY_FILE))
    assert result["trades_counted"] == 3


def test_kpi_daily_metrics_are_correct():
    _seed([_trade(300), _trade(-100), _trade(200)])
    history.write_all("2026-07-01", capital_start=100000)
    rows = history.load_kpi_daily()
    assert len(rows) == 1
    row = rows[0]
    assert row["trades"] == 3
    assert row["wins"] == 2 and row["losses"] == 1
    assert row["win_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert row["net_pnl"] == 400.0
    assert row["equity"] == 100400.0
    assert row["best_trade"] == 300.0 and row["worst_trade"] == -100.0
    # profit factor = gross profit 500 / gross loss 100
    assert row["profit_factor"] == 5.0


def test_profit_factor_none_when_no_losses():
    _seed([_trade(300), _trade(200)])
    history.write_all("2026-07-01", capital_start=100000)
    assert history.load_kpi_daily()[0]["profit_factor"] is None


def test_pattern_stats_group_by_pattern():
    _seed([
        _trade(300, patterns=["bullish_engulfing"]),
        _trade(-100, patterns=["bullish_engulfing"]),
        _trade(150, patterns=["hammer"]),
    ])
    history.write_all("2026-07-01")
    rows = {r["pattern"]: r for r in history.load_pattern_stats()}
    assert rows["bullish_engulfing"]["occurrences"] == 2
    assert rows["bullish_engulfing"]["win_rate"] == 0.5
    assert rows["hammer"]["occurrences"] == 1
    assert rows["hammer"]["win_rate"] == 1.0


def test_feature_stats_bucket_by_rsi_and_regime():
    _seed([
        _trade(300, indicators={"rsi": 62, "volume_ratio": 1.7, "atr": 9.4, "ema_20": 2945.0}),
        _trade(-50, indicators={"rsi": 25, "volume_ratio": 0.8, "atr": 5.0, "ema_20": 1000.0}),
    ])
    history.write_all("2026-07-01")
    feats = history.load_feature_stats()
    rsi_buckets = {r["bucket"] for r in feats if r["dimension"] == "rsi"}
    assert "60-70" in rsi_buckets and "<30" in rsi_buckets
    assert any(r["dimension"] == "regime" for r in feats)
    assert any(r["dimension"] == "symbol" for r in feats)


def test_writers_are_idempotent_per_date():
    _seed([_trade(300), _trade(-100)])
    history.write_all("2026-07-01", capital_start=100000)
    history.write_all("2026-07-01", capital_start=100000)  # re-run same date
    # Exactly one KPI row for the date, not two.
    assert len(history.load_kpi_daily("2026-07-01", "2026-07-01")) == 1


def test_two_days_coexist_in_jsonl():
    _seed([_trade(300, date="2026-07-01"), _trade(-100, date="2026-07-02")])
    history.write_all("2026-07-01", capital_start=100000)
    history.write_all("2026-07-02", capital_start=100300)
    kpis = history.load_kpi_daily()
    assert [k["snapshot_date"] for k in kpis] == ["2026-07-01", "2026-07-02"]
    assert kpis[0]["net_pnl"] == 300.0
    assert kpis[1]["net_pnl"] == -100.0


def test_leaderboard_asof_falls_back_to_prior_snapshot():
    _seed([_trade(300)])
    history.snapshot_leaderboard("2026-07-01", stats={"ORB|trending_up|0945_1030": {"trades": 5}})
    # No snapshot on the 3rd — as-of should resolve to the 1st.
    asof = history.load_leaderboard_asof("2026-07-03")
    assert asof is not None
    assert asof["snapshot_date"] == "2026-07-01"
    assert history.load_leaderboard_asof("2026-06-30") is None  # nothing on/before


def test_date_range_filtering():
    for d, pnl in [("2026-07-01", 100), ("2026-07-02", 200), ("2026-07-03", -50)]:
        _seed([_trade(pnl, date=d)])
        history.write_all(d)
    mid = history.load_kpi_daily("2026-07-02", "2026-07-02")
    assert len(mid) == 1 and mid[0]["snapshot_date"] == "2026-07-02"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
