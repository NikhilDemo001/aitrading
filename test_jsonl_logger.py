"""Unit tests for jsonl_logger — schema construction, wins/losses split, decisions log."""

import json
import os
import shutil

import pytest

import jsonl_logger


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path, monkeypatch):
    """Redirect all file writes to a temp dir so tests never touch the real data/ directory."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(jsonl_logger, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(jsonl_logger, "WINS_FILE", str(data_dir / "wins.jsonl"))
    monkeypatch.setattr(jsonl_logger, "LOSSES_FILE", str(data_dir / "losses.jsonl"))
    monkeypatch.setattr(jsonl_logger, "DECISIONS_FILE", str(data_dir / "decisions.log"))
    yield
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)


def sample_win_record(**overrides):
    record = {
        "symbol": "RELIANCE",
        "strategy": "ORB-Buy",
        "direction": "LONG",
        "quantity": 20,
        "entry_price": 2950.5,
        "entry_time": "2026-07-01T09:22:00",
        "exit_price": 2968.0,
        "exit_time": "2026-07-01T09:41:00",
        "pnl": 350.0,
        "reason": "TARGET-2 HIT",
        "regime": "trending_up",
        "atr_at_entry": 9.4,
        "market_context": {"vwap": 2948.2, "rsi": 61, "atr": 9.4, "volume_ratio": 1.7, "ema_20": 2945.0},
        "holding_minutes": 19.0,
        "mae": 2.0,
        "mfe": 18.0,
        "confluence_score": 5,
        "is_shadow_trade": False,
    }
    record.update(overrides)
    return record


def test_log_trade_writes_win_to_wins_file():
    full = jsonl_logger.log_trade(sample_win_record(), mode="paper")
    assert os.path.exists(jsonl_logger.WINS_FILE)
    assert not os.path.exists(jsonl_logger.LOSSES_FILE)
    rows = jsonl_logger.read_jsonl(jsonl_logger.WINS_FILE)
    assert len(rows) == 1
    assert rows[0]["trade_id"] == full["trade_id"]


def test_log_trade_writes_loss_to_losses_file():
    jsonl_logger.log_trade(sample_win_record(pnl=-120.0, reason="STOP LOSS", exit_price=2938.0), mode="paper")
    assert os.path.exists(jsonl_logger.LOSSES_FILE)
    assert not os.path.exists(jsonl_logger.WINS_FILE)
    rows = jsonl_logger.read_jsonl(jsonl_logger.LOSSES_FILE)
    assert rows[0]["pnl"] == -120.0
    assert rows[0]["exit_reason"] == "stoploss"


def test_schema_has_all_spec_fields():
    full = jsonl_logger.build_trade_record(sample_win_record(), mode="paper")
    required = {
        "trade_id", "mode", "symbol", "strategy", "direction", "timestamp_entry",
        "timestamp_exit", "entry_price", "exit_price", "quantity", "pnl", "pnl_pct",
        "r_multiple", "exit_reason", "market_regime", "candlestick_patterns",
        "time_of_day_bucket", "indicators_at_entry", "lesson", "tags",
    }
    assert required.issubset(full.keys())
    assert full["mode"] == "paper"
    assert full["symbol"] == "NSE:RELIANCE"
    assert full["direction"] == "long"


def test_r_multiple_uses_atr_as_risk_proxy():
    # per-share pnl = 2968.0 - 2950.5 = 17.5; atr_at_entry = 9.4 -> r_multiple = 17.5/9.4
    full = jsonl_logger.build_trade_record(sample_win_record(), mode="paper")
    assert full["r_multiple"] == pytest.approx(17.5 / 9.4, abs=1e-3)


def test_exit_reason_normalization():
    cases = [
        ("TARGET-2 HIT", "target"),
        ("STOP LOSS", "stoploss"),
        ("TRAIL/B-E STOP", "stoploss"),
        ("AUTO SQUARE-OFF", "eod_squareoff"),
        ("MOMENTUM EXIT (9EMA/VWAP CROSS)", "signal_reverse"),
        ("STALE_STARTUP_SQUAREOFF", "eod_squareoff"),
        ("SOMETHING WEIRD", "other"),
    ]
    for raw, expected in cases:
        assert jsonl_logger._normalize_exit_reason(raw) == expected


def test_time_of_day_bucket_format():
    from datetime import datetime
    bucket = jsonl_logger.time_of_day_bucket(datetime(2026, 7, 1, 9, 22, 0))
    assert bucket == "0915_1000"
    bucket2 = jsonl_logger.time_of_day_bucket(datetime(2026, 7, 1, 10, 5, 0))
    assert bucket2 == "1000_1045"


def test_log_decision_appends_jsonl_lines():
    jsonl_logger.log_decision("skip", "TCS", "Daily loss limit hit")
    jsonl_logger.log_decision("pick", "RELIANCE", "Best regime-weighted expectancy")
    rows = jsonl_logger.read_jsonl(jsonl_logger.DECISIONS_FILE)
    assert len(rows) == 2
    assert rows[0]["type"] == "skip"
    assert rows[1]["type"] == "pick"


def test_backfill_lessons_updates_matching_trade_id_only():
    full = jsonl_logger.log_trade(sample_win_record(), mode="paper")
    updated = jsonl_logger.backfill_lessons({full["trade_id"]: "Entry aligned with VWAP reclaim."})
    assert updated == 1
    rows = jsonl_logger.read_jsonl(jsonl_logger.WINS_FILE)
    assert rows[0]["lesson"] == "Entry aligned with VWAP reclaim."

    # Re-running with the same lesson map must not double-count (lesson already set).
    updated_again = jsonl_logger.backfill_lessons({full["trade_id"]: "Different lesson."})
    assert updated_again == 0


def test_read_jsonl_tolerates_malformed_trailing_line(tmp_path):
    path = str(tmp_path / "custom.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"a": 1}) + "\n")
        f.write("{not valid json\n")
        f.write(json.dumps({"a": 2}) + "\n")
    rows = jsonl_logger.read_jsonl(path)
    assert rows == [{"a": 1}, {"a": 2}]


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
