"""Unit tests for risk_manager.RiskManager — proves the Section 0 / DoD #6 safety rules:
daily-loss kill switch, per-trade sizing, consecutive-loss breaker, forced square-off."""

from datetime import datetime

import pytest

from risk_manager import RiskManager


def make_config(**overrides):
    cfg = {
        "paper_trading": False,
        "max_daily_loss": 2000.0,
        "max_weekly_loss_pct": 0.1,
        "max_weekly_loss_abs": 100000.0,
        "max_consecutive_losses": 4,
        "loss_halt_minutes": 30,
        "enable_loss_halt": True,
        "max_open_positions": 2,
        "enable_sector_filter": True,
        "max_open_positions_per_sector": 1,
        "max_trades_per_symbol_per_day": 2,
        "risk_per_trade_pct": 0.5,
        "trade_start_time": "09:30",
        "no_new_trade_time": "15:00",
        "trade_end_time": "14:30",
        "square_off_time": "15:15",
        "min_scan_volume": 50000,
    }
    cfg.update(overrides)
    return cfg


# ── Daily loss kill switch (Section 0 rule 2) ───────────────────────────────────────

def test_daily_loss_kill_switch_trips_at_threshold():
    rm = RiskManager(make_config(max_daily_loss=2000.0))
    decision = rm.check_daily_loss(total_pnl_today=-2000.0)
    assert not decision.allowed
    assert "Daily loss limit" in decision.reason


def test_daily_loss_kill_switch_does_not_trip_above_threshold():
    rm = RiskManager(make_config(max_daily_loss=2000.0))
    decision = rm.check_daily_loss(total_pnl_today=-1999.99)
    assert decision.allowed


def test_is_frozen_reflects_daily_loss_and_clears_on_reset():
    rm = RiskManager(make_config(max_daily_loss=2000.0))
    frozen, reason = rm.is_frozen(total_pnl_today=-2500.0)
    assert frozen
    assert reason
    # Next trading day, daily_pnl resets to 0 upstream — is_frozen is pure, so it clears
    # automatically with no persisted "tripped" flag to manage.
    frozen, reason = rm.is_frozen(total_pnl_today=0.0)
    assert not frozen


def test_size_and_check_blocks_when_daily_loss_breached():
    rm = RiskManager(make_config())
    decision = rm.size_and_check(
        symbol="RELIANCE", entry_price=2950.0, stop_loss=2940.0, capital=100000.0,
        total_pnl_today=-2000.0, weekly_pnl=0.0, open_positions={}, trade_history=[],
        now=datetime(2026, 7, 1, 10, 0), paper_trading=False,
    )
    assert not decision.allowed
    assert decision.qty == 0


def test_daily_loss_kill_switch_trips_in_paper_mode_too():
    """Section 0 rule 2 applies identically in paper and live: paper must faithfully rehearse
    live and must not keep generating (contaminated) learning data after the halt. Changed
    2026-07-07 — the daily-loss halt previously bypassed paper (blocker #4)."""
    rm = RiskManager(make_config(max_daily_loss=1000.0))
    decision = rm.check_daily_loss(total_pnl_today=-1500.0, paper_trading=True)
    assert not decision.allowed
    assert "Daily loss limit" in decision.reason


def test_daily_loss_halt_applies_in_both_paper_and_live():
    """The full size_and_check gate blocks a breaching trade regardless of mode."""
    rm = RiskManager(make_config(max_daily_loss=1000.0))

    for paper in (False, True):
        decision = rm.size_and_check(
            symbol="TCS", entry_price=3500.0, stop_loss=3480.0, capital=100000.0,
            total_pnl_today=-1500.0, weekly_pnl=0.0, open_positions={}, trade_history=[],
            now=datetime(2026, 7, 1, 10, 0), paper_trading=paper,
        )
        assert not decision.allowed, f"daily-loss halt must block in paper={paper}"


# ── Weekly drawdown ──────────────────────────────────────────────────────────────────

def test_weekly_drawdown_halt():
    rm = RiskManager(make_config(max_weekly_loss_pct=0.1, max_weekly_loss_abs=5000.0))
    decision = rm.check_weekly_drawdown(weekly_pnl=-15000.0, margin=100000.0)
    assert not decision.allowed


def test_weekly_drawdown_uses_the_larger_of_pct_and_abs_floor():
    rm = RiskManager(make_config(max_weekly_loss_pct=0.1, max_weekly_loss_abs=100000.0))
    # 10% of 50000 margin = 5000, but abs floor is 100000 -> threshold is 100000
    decision = rm.check_weekly_drawdown(weekly_pnl=-6000.0, margin=50000.0)
    assert decision.allowed  # -6000 has not breached the 100000 floor


# ── Per-trade risk sizing (Section 7) ────────────────────────────────────────────────

def test_position_size_derived_from_stop_distance_not_fixed_lots():
    rm = RiskManager(make_config(risk_per_trade_pct=0.5))
    # capital=100000, risk_pct=0.5% -> risk budget = 500. stop distance = 10 -> qty = floor(500/10) = 50
    qty = rm.max_qty_by_risk_pct(capital=100000.0, entry_price=2950.0, stop_loss=2940.0)
    assert qty == 50

    # Wider stop -> smaller qty, same risk budget, proving sizing scales with stop distance.
    qty_wide_stop = rm.max_qty_by_risk_pct(capital=100000.0, entry_price=2950.0, stop_loss=2900.0)
    assert qty_wide_stop == 10
    assert qty_wide_stop < qty


def test_size_and_check_returns_the_risk_derived_quantity():
    rm = RiskManager(make_config(risk_per_trade_pct=0.5))
    decision = rm.size_and_check(
        symbol="INFY", entry_price=1500.0, stop_loss=1490.0, capital=100000.0,
        total_pnl_today=0.0, weekly_pnl=0.0, open_positions={}, trade_history=[],
        now=datetime(2026, 7, 1, 10, 0), paper_trading=True,
    )
    assert decision.allowed
    assert decision.qty == 50  # floor(100000*0.005 / 10)


def test_size_and_check_never_exceeds_caller_proposed_qty():
    """RiskManager is a ceiling on top of upstream sizing (Kelly/max-capacity/F&O), never a
    looser number than what the caller's own sizing already proposed."""
    rm = RiskManager(make_config(risk_per_trade_pct=0.5))
    decision = rm.size_and_check(
        symbol="INFY", entry_price=1500.0, stop_loss=1490.0, capital=100000.0,
        total_pnl_today=0.0, weekly_pnl=0.0, open_positions={}, trade_history=[],
        now=datetime(2026, 7, 1, 10, 0), paper_trading=True,
        proposed_qty=5,
    )
    assert decision.allowed
    assert decision.qty == 5  # capped by proposed_qty even though risk_pct math allows 50


def test_size_and_check_skip_size_cap_passes_through_fno_lot_qty():
    """F&O trades size against their own fno_max_risk_per_trade/lot budget upstream — the
    equity risk_per_trade_pct ceiling must not clobber an already-correct lot quantity."""
    rm = RiskManager(make_config(risk_per_trade_pct=0.5))
    decision = rm.size_and_check(
        symbol="RELIANCE", entry_price=1000.0, stop_loss=980.0, capital=100000.0,
        total_pnl_today=0.0, weekly_pnl=0.0, open_positions={}, trade_history=[],
        now=datetime(2026, 7, 1, 10, 0), paper_trading=True,
        proposed_qty=100,  # 1 lot of 100 — would otherwise be clamped to floor(500/20)=25
        skip_size_cap=True,
    )
    assert decision.allowed
    assert decision.qty == 100


def test_size_and_check_rejects_when_computed_size_is_zero():
    rm = RiskManager(make_config(risk_per_trade_pct=0.5))
    decision = rm.size_and_check(
        symbol="INFY", entry_price=1500.0, stop_loss=1490.0, capital=1.0,  # tiny capital
        total_pnl_today=0.0, weekly_pnl=0.0, open_positions={}, trade_history=[],
        now=datetime(2026, 7, 1, 10, 0), paper_trading=True,
    )
    assert not decision.allowed
    assert decision.qty == 0


# ── Consecutive-loss circuit breaker (Section 0 rule 6) ─────────────────────────────

def test_consecutive_loss_breaker_halts_after_threshold():
    from signal_quality import get_ist_now  # real wall-clock IST — the delegate is not injectable
    rm = RiskManager(make_config(max_consecutive_losses=3, loss_halt_minutes=30))
    now_iso = get_ist_now().isoformat()
    losing_trades = [
        {"pnl": -100.0, "exit_time": now_iso, "is_shadow_trade": False}
        for _ in range(3)
    ]
    decision = rm.check_consecutive_losses(losing_trades, paper_trading=False)
    assert not decision.allowed


def test_consecutive_loss_breaker_disabled_via_config():
    from signal_quality import get_ist_now
    rm = RiskManager(make_config(enable_loss_halt=False, max_consecutive_losses=1))
    now_iso = get_ist_now().isoformat()
    losing_trades = [{"pnl": -100.0, "exit_time": now_iso, "is_shadow_trade": False}]
    decision = rm.check_consecutive_losses(losing_trades, paper_trading=False)
    assert decision.allowed  # gate is switched off entirely


# ── Forced square-off (Section 0 rule 4) ────────────────────────────────────────────

def test_is_past_square_off():
    rm = RiskManager(make_config(square_off_time="15:15"))
    assert rm.is_past_square_off(datetime(2026, 7, 1, 15, 15))
    assert rm.is_past_square_off(datetime(2026, 7, 1, 15, 30))
    assert not rm.is_past_square_off(datetime(2026, 7, 1, 15, 14))


def test_trading_window_blocks_outside_hours():
    rm = RiskManager(make_config(trade_start_time="09:30", no_new_trade_time="15:00"))
    assert not rm.check_trading_window(datetime(2026, 7, 1, 9, 0)).allowed
    assert not rm.check_trading_window(datetime(2026, 7, 1, 15, 5)).allowed
    assert rm.check_trading_window(datetime(2026, 7, 1, 10, 0)).allowed


def test_size_and_check_blocks_after_square_off_window_via_trading_window_gate():
    rm = RiskManager(make_config(trade_start_time="09:30", no_new_trade_time="15:00"))
    decision = rm.size_and_check(
        symbol="RELIANCE", entry_price=2950.0, stop_loss=2940.0, capital=100000.0,
        total_pnl_today=0.0, weekly_pnl=0.0, open_positions={}, trade_history=[],
        now=datetime(2026, 7, 1, 15, 20), paper_trading=True,
    )
    assert not decision.allowed
    assert "trading window" in decision.reason.lower()


# ── Max open positions / sector cap / per-symbol cap ────────────────────────────────

def test_max_open_positions_blocks_new_entries():
    rm = RiskManager(make_config(max_open_positions=2))
    open_positions = {"RELIANCE": {}, "TCS": {}}
    decision = rm.check_max_open_positions(len(open_positions))
    assert not decision.allowed


def test_sector_cap_blocks_second_position_same_sector():
    rm = RiskManager(make_config(max_open_positions_per_sector=1))
    # HDFCBANK and ICICIBANK are both in signal_quality.SECTOR_MAP under the same sector.
    from signal_quality import SECTOR_MAP
    sector = SECTOR_MAP.get("HDFCBANK")
    if sector is None or sector == "OTHER":
        pytest.skip("SECTOR_MAP does not map HDFCBANK in this build")
    same_sector_symbol = next(
        (s for s, sec in SECTOR_MAP.items() if sec == sector and s != "HDFCBANK"), None
    )
    if same_sector_symbol is None:
        pytest.skip("No second symbol found in the same sector as HDFCBANK")
    open_positions = {"HDFCBANK": {"symbol": "HDFCBANK"}}
    decision = rm.check_sector_cap(same_sector_symbol, open_positions)
    assert not decision.allowed


def test_symbol_daily_cap_blocks_after_limit():
    rm = RiskManager(make_config(max_trades_per_symbol_per_day=2))
    today = "2026-07-01"
    trade_history = [
        {"symbol": "RELIANCE", "exit_time": f"{today}T10:00:00"},
        {"symbol": "RELIANCE", "exit_time": f"{today}T11:00:00"},
    ]
    decision = rm.check_symbol_daily_cap("RELIANCE", trade_history, today)
    assert not decision.allowed


def test_liquidity_gate():
    rm = RiskManager(make_config(min_scan_volume=50000))
    assert not rm.check_liquidity(volume=1000).allowed
    assert rm.check_liquidity(volume=100000).allowed
    assert rm.check_liquidity(volume=None).allowed  # no data -> don't block on missing info


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
