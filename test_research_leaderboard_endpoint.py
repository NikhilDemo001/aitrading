"""Regression test for GET /api/research/leaderboard.

The endpoint used to call research_lab.generate_daily_journal() on every request — a
DELETE + bulk-INSERT write that (a) collided with the paper-trader's concurrent SQLite
writes causing intermittent 'database is locked' → HTTP 500, and (b) inserted a
near-duplicate research_journal row on every dashboard poll. It must be a pure read; the
journal/leaderboard rebuild belongs to the autonomous research cycle / EOD rebuild.
"""

import research_lab
from routers import research as research_router


def test_leaderboard_endpoint_is_read_only(monkeypatch):
    called = {"journal": False}
    monkeypatch.setattr(research_lab, "get_leaderboard", lambda: [{"rank": 1, "name": "X"}])
    monkeypatch.setattr(
        research_lab, "generate_daily_journal",
        lambda: called.__setitem__("journal", True))

    result = research_router.get_leaderboard_endpoint()

    assert result == [{"rank": 1, "name": "X"}]
    assert called["journal"] is False, \
        "GET /api/research/leaderboard must not trigger the journal/leaderboard rebuild write"
