"""
Phase-8 API tests: the history / learning-analytics endpoints in main.py that back the
date-range selector, as-of reconstruction and compare mode. Isolated to a tmp data dir so no
real data/ files are touched.
"""

import json
import os

import pytest

import jsonl_logger
import leaderboard
import history


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(jsonl_logger, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(jsonl_logger, "WINS_FILE", str(data_dir / "wins.jsonl"))
    monkeypatch.setattr(jsonl_logger, "LOSSES_FILE", str(data_dir / "losses.jsonl"))
    monkeypatch.setattr(jsonl_logger, "DECISIONS_FILE", str(data_dir / "decisions.log"))
    monkeypatch.setattr(leaderboard, "STATS_FILE", str(data_dir / "strategy_stats.json"))

    def _seed(pnl, date, **kw):
        rec = {
            "trade_id": os.urandom(4).hex(), "mode": kw.get("mode", "paper"),
            "symbol": kw.get("symbol", "NSE:RELIANCE"), "strategy": kw.get("strategy", "ORB-Buy"),
            "direction": "long", "timestamp_entry": f"{date}T09:30:00",
            "timestamp_exit": f"{date}T10:00:00", "pnl": pnl,
            "r_multiple": 1.5 if pnl >= 0 else -1.0, "market_regime": "trending_up",
            "candlestick_patterns": ["bullish_engulfing"], "time_of_day_bucket": "0945_1030",
            "indicators_at_entry": {"rsi": 62, "volume_ratio": 1.7, "atr": 9.4, "ema_20": 2945.0},
            "holding_minutes": 18,
        }
        target = jsonl_logger.WINS_FILE if pnl >= 0 else jsonl_logger.LOSSES_FILE
        os.makedirs(data_dir, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    _seed(300, "2026-06-30", mode="paper")
    _seed(-100, "2026-06-30", mode="live", symbol="NSE:HDFCBANK")
    _seed(250, "2026-07-01", mode="paper")
    history.write_all("2026-06-30", capital_start=100000)
    history.write_all("2026-07-01", capital_start=100200)

    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def test_history_dates(client):
    r = client.get("/api/history/dates")
    assert r.status_code == 200
    assert set(r.json()["dates"]) == {"2026-06-30", "2026-07-01"}


def test_history_kpi_range(client):
    r = client.get("/api/history/kpi", params={"start": "2026-06-30", "end": "2026-06-30"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1 and rows[0]["net_pnl"] == 200.0  # 300 - 100


def test_history_leaderboard_asof(client):
    # No snapshot on 07-05 → resolves to the latest prior (07-01).
    r = client.get("/api/history/leaderboard", params={"as_of": "2026-07-05"})
    assert r.status_code == 200
    assert r.json()["resolved_from"] == "2026-07-01"


def test_history_trades_mode_filter(client):
    r = client.get("/api/history/trades", params={"mode": "live"})
    rows = r.json()
    assert len(rows) == 1 and rows[0]["mode"] == "live"
    assert "HDFCBANK" in rows[0]["symbol"]


def test_history_trades_symbol_filter(client):
    r = client.get("/api/history/trades", params={"symbol": "RELIANCE"})
    rows = r.json()
    assert len(rows) == 2
    assert all("RELIANCE" in t["symbol"] for t in rows)


def test_history_summary_and_compare(client):
    r = client.get("/api/history/summary")
    s = r.json()
    assert s["trades"] == 3 and s["net_pnl"] == 450.0  # 300 -100 +250

    r2 = client.get("/api/history/compare", params={
        "a_start": "2026-06-30", "a_end": "2026-06-30",
        "b_start": "2026-07-01", "b_end": "2026-07-01",
    })
    body = r2.json()
    assert body["a"]["metrics"]["net_pnl"] == 200.0
    assert body["b"]["metrics"]["net_pnl"] == 250.0
    assert body["delta"]["net_pnl"] == 50.0


def test_history_patterns_and_features(client):
    p = client.get("/api/history/patterns").json()
    assert any(row["pattern"] == "bullish_engulfing" for row in p)
    f = client.get("/api/history/features", params={"dimension": "rsi"}).json()
    assert all(row["dimension"] == "rsi" for row in f)
    assert any(row["bucket"] == "60-70" for row in f)


def test_rebuild_endpoint_idempotent(client):
    r = client.post("/api/history/rebuild", json={"date": "2026-07-01"})
    assert r.status_code == 200 and r.json()["status"] == "success"
    # Still exactly one KPI row for that date after a re-run.
    assert len(history.load_kpi_daily("2026-07-01", "2026-07-01")) == 1


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
