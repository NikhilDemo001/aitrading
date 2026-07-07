"""Startup staleness check (2026-07-06 incident, part 2).

The bot process died ~14:35 and was restarted at 20:50 — after square-off time. load_state()
already force-closed positions from PREVIOUS days, but same-day positions restored past
square-off resumed as live and sat on the book until a manual kill switch 5+ hours after
close. Section 0: no position may survive past square-off — regardless of entry date.
"""

from datetime import datetime

import main


SQ = "15:10"


def _pos(entry_time):
    return {"symbol": "MAZDA", "entry_time": entry_time, "direction": "LONG",
            "quantity": 133, "entry_price": 275.38, "current_price": 274.03}


def test_overnight_position_is_stale():
    now = datetime(2026, 7, 7, 9, 0, 0)
    assert main._position_is_stale_at_startup(_pos("2026-07-06T14:25:39"), now, SQ) is True


def test_same_day_position_before_square_off_is_kept():
    """Normal crash-recovery: restart at 11:05 must resume managing the position."""
    now = datetime(2026, 7, 6, 11, 5, 0)
    assert main._position_is_stale_at_startup(_pos("2026-07-06T10:30:00"), now, SQ) is False


def test_same_day_position_after_square_off_is_stale():
    """The actual incident: entry 14:25, restart 20:50 — must be force-closed."""
    now = datetime(2026, 7, 6, 20, 50, 24)
    assert main._position_is_stale_at_startup(_pos("2026-07-06T14:25:39"), now, SQ) is True


def test_exactly_at_square_off_time_is_stale():
    now = datetime(2026, 7, 6, 15, 10, 0)
    assert main._position_is_stale_at_startup(_pos("2026-07-06T14:25:39"), now, SQ) is True


def test_missing_entry_time_before_square_off_is_kept():
    now = datetime(2026, 7, 6, 11, 0, 0)
    assert main._position_is_stale_at_startup(_pos(""), now, SQ) is False


def test_missing_entry_time_after_square_off_is_stale():
    """A position with no entry_time is still a position on the book past square-off."""
    now = datetime(2026, 7, 6, 16, 0, 0)
    assert main._position_is_stale_at_startup(_pos(""), now, SQ) is True


def test_unparseable_square_off_falls_back_to_date_check_only():
    now = datetime(2026, 7, 6, 20, 0, 0)
    assert main._position_is_stale_at_startup(_pos("2026-07-06T14:25:39"), now, "bogus") is False
    assert main._position_is_stale_at_startup(_pos("2026-07-05T14:25:39"), now, "bogus") is True


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
