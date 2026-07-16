"""Tests for the per-symbol earnings/event blackout gate (event_calendar).

The gate stops the automated scanner from opening a new position in a stock within a
configurable window around its known results/board-meeting date. It must FAIL OPEN: an
unlisted symbol, a missing/empty calendar, or any error must never block a trade.
"""

import datetime
import json

import event_calendar
from event_calendar import get_symbol_event_blackout


def _d(s):
    return datetime.datetime.fromisoformat(s)


def _load(monkeypatch, tmp_path, mapping):
    """Point the module at a temp calendar file and clear its cache."""
    f = tmp_path / "earnings_calendar.json"
    f.write_text(json.dumps(mapping))
    monkeypatch.setattr(event_calendar, "_EARNINGS_FILE", str(f))
    event_calendar._earnings_cache = None
    event_calendar._earnings_mtime = None


def test_blocks_on_event_day(monkeypatch, tmp_path):
    _load(monkeypatch, tmp_path, {"RELIANCE": ["2026-07-18"]})
    blocked, reason = get_symbol_event_blackout("RELIANCE", _d("2026-07-18T10:00:00"),
                                                days_before=1, days_after=0)
    assert blocked is True
    assert "2026-07-18" in reason


def test_blocks_within_days_before_window(monkeypatch, tmp_path):
    _load(monkeypatch, tmp_path, {"RELIANCE": ["2026-07-18"]})
    # One day before, with a 1-day pre-window -> blocked.
    blocked, _ = get_symbol_event_blackout("RELIANCE", _d("2026-07-17T10:00:00"),
                                           days_before=1, days_after=0)
    assert blocked is True


def test_allows_outside_window(monkeypatch, tmp_path):
    _load(monkeypatch, tmp_path, {"RELIANCE": ["2026-07-18"]})
    # Two days before, 1-day pre-window -> allowed.
    blocked, _ = get_symbol_event_blackout("RELIANCE", _d("2026-07-16T10:00:00"),
                                           days_before=1, days_after=0)
    assert blocked is False
    # Day after, with no post-window -> allowed.
    blocked2, _ = get_symbol_event_blackout("RELIANCE", _d("2026-07-19T10:00:00"),
                                            days_before=1, days_after=0)
    assert blocked2 is False


def test_days_after_window(monkeypatch, tmp_path):
    _load(monkeypatch, tmp_path, {"RELIANCE": ["2026-07-18"]})
    blocked, _ = get_symbol_event_blackout("RELIANCE", _d("2026-07-19T10:00:00"),
                                           days_before=0, days_after=1)
    assert blocked is True


def test_unlisted_symbol_fails_open(monkeypatch, tmp_path):
    _load(monkeypatch, tmp_path, {"RELIANCE": ["2026-07-18"]})
    blocked, _ = get_symbol_event_blackout("INFY", _d("2026-07-18T10:00:00"),
                                           days_before=1, days_after=0)
    assert blocked is False


def test_symbol_case_insensitive(monkeypatch, tmp_path):
    _load(monkeypatch, tmp_path, {"RELIANCE": ["2026-07-18"]})
    blocked, _ = get_symbol_event_blackout("reliance", _d("2026-07-18T10:00:00"),
                                           days_before=1, days_after=0)
    assert blocked is True


def test_comment_keys_ignored(monkeypatch, tmp_path):
    _load(monkeypatch, tmp_path, {"__comment__": "docs", "__example__": {"X": ["2026-07-18"]},
                                  "RELIANCE": []})
    # RELIANCE has no dates -> not blocked; the __example__ block must not leak in.
    blocked, _ = get_symbol_event_blackout("RELIANCE", _d("2026-07-18T10:00:00"))
    assert blocked is False
    blocked_x, _ = get_symbol_event_blackout("X", _d("2026-07-18T10:00:00"))
    assert blocked_x is False


def test_missing_file_fails_open(monkeypatch, tmp_path):
    monkeypatch.setattr(event_calendar, "_EARNINGS_FILE", str(tmp_path / "does_not_exist.json"))
    event_calendar._earnings_cache = None
    event_calendar._earnings_mtime = None
    blocked, _ = get_symbol_event_blackout("RELIANCE", _d("2026-07-18T10:00:00"))
    assert blocked is False


def test_bad_date_string_ignored(monkeypatch, tmp_path):
    _load(monkeypatch, tmp_path, {"RELIANCE": ["not-a-date", "2026-07-18"]})
    blocked, _ = get_symbol_event_blackout("RELIANCE", _d("2026-07-18T10:00:00"))
    assert blocked is True
