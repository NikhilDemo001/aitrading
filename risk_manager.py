"""
Unified risk management (Section 0 + Section 7 of the build spec).

Every order — paper or live — must pass through RiskManager.size_and_check() before being
placed; no other code path may size or gate a trade independently. Every check here is a plain
method taking explicit arguments (no module globals), so it's directly unit-testable and can be
called identically from main.py's existing scan/execute path and from orchestrator.py.

Design note: this does not replace strategy-specific sizing nuance already tuned in main.py
(Kelly-fraction risk, max-capacity/leverage sizing, F&O lot sizing, capital-allocation scaling
from research_lab). Those still compute a *candidate* quantity upstream. RiskManager applies the
spec's canonical risk_per_trade_pct-derived ceiling on top of that candidate and is the mandatory
final gate every path must call before an order is actually placed — the hard ceiling, not a
replacement for existing sizing logic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time as dtime

try:
    from signal_quality import check_consecutive_loss_halt, SECTOR_MAP
except Exception:
    check_consecutive_loss_halt = None
    SECTOR_MAP = {}


@dataclass
class RiskDecision:
    allowed: bool
    qty: int = 0
    reason: str = ""

    def __bool__(self) -> bool:
        return self.allowed


def _parse_hhmm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


class RiskManager:
    """Single consolidated gate for every order.

    Construct with a config dict, or a zero-arg callable returning the live config (so config
    reloads, e.g. `client.load_config()`, are picked up automatically): `RiskManager(lambda:
    client.config)`.
    """

    def __init__(self, config):
        self._config = config

    @property
    def config(self) -> dict:
        return self._config() if callable(self._config) else self._config

    # ── Individual gates (each independently unit-testable) ─────────────────────────

    def check_daily_loss(self, total_pnl_today: float, paper_trading: bool | None = None) -> RiskDecision:
        """Section 0 rule 2: hard daily loss kill switch.

        Enforced identically in paper and live (like check_consecutive_losses). Paper must
        faithfully rehearse live and must not keep logging trades after the halt — otherwise
        the learning data is contaminated by post-kill-switch trades (blocker #4, fixed
        2026-07-07; the day the halt bypassed paper, one paper day lost ₹2,069 without halting
        on a ₹500 limit). `paper_trading` is accepted for API symmetry but never loosens this.
        """
        max_loss = float(self.config.get("max_daily_loss", 1000.0))
        if total_pnl_today <= -max_loss:
            return RiskDecision(
                False, 0,
                f"Daily loss limit hit (₹{total_pnl_today:.2f} <= -₹{max_loss:.2f}) — "
                f"kill switch active for the rest of today."
            )
        return RiskDecision(True)

    def check_weekly_drawdown(self, weekly_pnl: float, margin: float) -> RiskDecision:
        max_weekly = max(
            float(self.config.get("max_weekly_loss_pct", 0.1)) * margin,
            float(self.config.get("max_weekly_loss_abs", 100000.0)),
        )
        if weekly_pnl <= -max_weekly:
            return RiskDecision(
                False, 0,
                f"Weekly drawdown limit hit (₹{weekly_pnl:.2f} <= -₹{max_weekly:.2f})."
            )
        return RiskDecision(True)

    def check_consecutive_losses(self, trade_history, paper_trading: bool = False) -> RiskDecision:
        """Section 0 rule 6: circuit breaker on N consecutive losses.

        Always enforced regardless of mode. The underlying signal_quality.check_consecutive_
        loss_halt has its own `if paper_trading: bypass` (added upstream so paper mode keeps
        generating data through a losing streak) — we deliberately do not use that bypass here,
        since the spec requires paper and live to share the exact same risk path. `paper_trading`
        is accepted for API symmetry/logging but never changes this gate's outcome.
        """
        if not self.config.get("enable_loss_halt", True):
            return RiskDecision(True)
        if check_consecutive_loss_halt is None:
            return RiskDecision(True)
        halted, reason = check_consecutive_loss_halt(
            trade_history,
            max_consecutive=int(self.config.get("max_consecutive_losses", 3)),
            halt_minutes=int(self.config.get("loss_halt_minutes", 30)),
            paper_trading=False,
        )
        return RiskDecision(not halted, 0, reason if halted else "")

    def check_trading_window(self, now: datetime) -> RiskDecision:
        start = _parse_hhmm(self.config.get("trade_start_time", "09:30"))
        end_str = self.config.get("no_new_trade_time") or self.config.get("trade_end_time", "14:30")
        end = _parse_hhmm(end_str)
        t = now.time()
        if not (start <= t <= end):
            return RiskDecision(False, 0, f"Outside trading window ({start}–{end}); current time {t}.")
        return RiskDecision(True)

    def is_past_square_off(self, now: datetime) -> bool:
        """Section 0 rule 4: no position may be held past square_off_time."""
        sq = _parse_hhmm(self.config.get("square_off_time", "15:15"))
        return now.time() >= sq

    def check_max_open_positions(self, open_count: int) -> RiskDecision:
        max_positions = int(self.config.get("max_open_positions", 3))
        if open_count >= max_positions:
            return RiskDecision(False, 0, f"Max open positions reached ({open_count}/{max_positions}).")
        return RiskDecision(True)

    def check_sector_cap(self, symbol: str, open_positions: dict) -> RiskDecision:
        if not self.config.get("enable_sector_filter", True):
            return RiskDecision(True)
        sector = SECTOR_MAP.get(symbol, "OTHER")
        if sector == "OTHER":
            return RiskDecision(True)
        max_per_sector = int(self.config.get("max_open_positions_per_sector", 1))
        open_in_sector = sum(
            1 for p in open_positions.values()
            if SECTOR_MAP.get(p.get("symbol"), "OTHER") == sector
        )
        if open_in_sector >= max_per_sector:
            return RiskDecision(False, 0, f"Sector cap reached for {sector} ({open_in_sector}/{max_per_sector}).")
        return RiskDecision(True)

    def check_symbol_daily_cap(self, symbol: str, trade_history, today: str) -> RiskDecision:
        max_per_symbol = int(self.config.get("max_trades_per_symbol_per_day", 2))
        count_today = sum(
            1 for t in trade_history
            if t.get("symbol") == symbol and str(t.get("exit_time", "")).startswith(today)
        )
        if count_today >= max_per_symbol:
            return RiskDecision(False, 0, f"Per-symbol daily trade cap reached for {symbol} ({count_today}/{max_per_symbol}).")
        return RiskDecision(True)

    def check_liquidity(self, volume: float | None, min_volume: float | None = None) -> RiskDecision:
        min_v = min_volume if min_volume is not None else float(self.config.get("min_scan_volume", 50000))
        if volume is not None and volume < min_v:
            return RiskDecision(False, 0, f"Liquidity too low (volume {volume} < {min_v}).")
        return RiskDecision(True)

    # ── Position sizing (Section 7) ────────────────────────────────────────────────

    def max_qty_by_risk_pct(self, capital: float, entry_price: float, stop_loss: float) -> int:
        """floor(capital * risk_per_trade_pct / stop_distance) — the spec's canonical formula.
        Position size is derived from stop-loss distance, never a fixed lot count."""
        risk_pct = float(self.config.get("risk_per_trade_pct", 0.5)) / 100.0
        risk_budget = capital * risk_pct
        stop_distance = abs(entry_price - stop_loss)
        if stop_distance < 0.01:
            stop_distance = 0.01
        return max(0, math.floor(risk_budget / stop_distance))

    def is_frozen(self, total_pnl_today: float, paper_trading: bool | None = None) -> tuple[bool, str]:
        """Pure/stateless by design: reflects today's realized+unrealized P&L against the
        kill-switch threshold, so it naturally clears at day rollover once daily P&L resets to
        zero — no persisted 'tripped' flag to manage."""
        d = self.check_daily_loss(total_pnl_today, paper_trading)
        if not d.allowed:
            return True, d.reason
        return False, ""

    def ensure_flat_reason(self, now: datetime) -> str:
        """Reason string the orchestrator logs when force-flattening all positions."""
        if self.is_past_square_off(now):
            return "EOD square-off (Section 0 rule 4)"
        return "Risk kill-switch (Section 0 rule 2/6)"

    # ── The mandatory single entry point ───────────────────────────────────────────

    def size_and_check(
        self,
        *,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        capital: float,
        total_pnl_today: float,
        weekly_pnl: float,
        open_positions: dict,
        trade_history: list,
        now: datetime,
        paper_trading: bool = True,
        proposed_qty: int | None = None,
        volume: float | None = None,
        max_qty_cap: int | None = None,
        skip_window_check: bool = False,
        skip_size_cap: bool = False,
    ) -> RiskDecision:
        """The one gate every order — paper or live — must pass through.

        Runs every applicable check in order; if all pass, returns an allowed decision capped at
        the smaller of the risk-pct-derived quantity and whatever quantity the caller's own
        sizing logic proposed (`proposed_qty` — Kelly / max-capacity all still apply upstream;
        this is the hard ceiling on top of them, never a looser number).

        `skip_size_cap`: set for F&O trades. F&O already has its own dedicated, lot-based risk
        budget (fno_max_risk_per_trade / fno_max_lots), which sizes in whole lots against a
        premium/futures price — not the equity-account risk_per_trade_pct-of-capital formula.
        Applying that formula on top would silently override an already-correct, differently-
        scoped sizing decision (and can round below 1 lot, killing valid F&O trades outright).
        All the other gates above still fully apply to F&O — only the size ceiling is skipped.
        """
        today = now.date().isoformat()

        for check in (
            self.check_daily_loss(total_pnl_today, paper_trading),
            self.check_weekly_drawdown(weekly_pnl, capital),
            self.check_consecutive_losses(trade_history, paper_trading),
            self.check_max_open_positions(len(open_positions)),
            self.check_sector_cap(symbol, open_positions),
            self.check_symbol_daily_cap(symbol, trade_history, today),
            self.check_liquidity(volume),
        ):
            if not check.allowed:
                return check

        if not skip_window_check:
            window = self.check_trading_window(now)
            if not window.allowed:
                return window

        if skip_size_cap:
            qty = int(proposed_qty) if proposed_qty is not None else 0
            if max_qty_cap is not None:
                qty = min(qty, max_qty_cap)
            if qty <= 0:
                return RiskDecision(False, 0, "Proposed quantity is zero.")
            return RiskDecision(True, qty, "ok (size cap skipped — F&O uses its own dedicated risk budget)")

        risk_qty = self.max_qty_by_risk_pct(capital, entry_price, stop_loss)
        if risk_qty <= 0:
            return RiskDecision(False, 0, "Computed position size is zero (stop too tight or capital too small for risk_per_trade_pct).")

        qty = risk_qty
        if proposed_qty is not None:
            qty = min(qty, proposed_qty)
        if max_qty_cap is not None:
            qty = min(qty, max_qty_cap)
        qty = max(0, int(qty))
        if qty <= 0:
            return RiskDecision(False, 0, "Final sized quantity is zero after applying all caps.")

        return RiskDecision(True, qty, "ok")
