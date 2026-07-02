"""
Signal Quality Engine — multi-layer filters that only let high-conviction
setups through. Each layer eliminates a category of losing trades.
"""

from datetime import datetime, timezone, timedelta

# Returns timezone-naive datetime representing IST (India Standard Time, UTC +5:30)
def get_ist_now():
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=5, minutes=30)
from strategies import (
    calculate_ema, calculate_vwap, calculate_atr, calculate_rsi, calculate_adx
)

# ─────────────────────────────────────────────────────────────────────────────
# Optional event-calendar integration (H4)
# If event_calendar.py is present in the project, Layer 0 will activate
# automatically. If not, it is silently skipped and all other layers run as
# normal — no change to existing behaviour.
# ─────────────────────────────────────────────────────────────────────────────
try:
    from event_calendar import get_event_risk
    _EVENT_CALENDAR_AVAILABLE = True
except ImportError:
    _EVENT_CALENDAR_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1: Time-of-Day Filter
# ─────────────────────────────────────────────────────────────────────────────
#
# Market microstructure research shows:
#   09:15-09:30  — Extreme opening volatility, largely random.  AVOID.
#   09:30-11:30  — Best trending/breakout window.  ALL strategies.
#   11:30-12:00  — Pre-lunch drift.  Selective: trend/pullback only.
#   12:00-13:00  — Lunch hour thin liquidity, reversals common.  Mean reversion only.
#   13:00-14:30  — Post-lunch trending resumes.  ALL strategies.
#   14:30+       — Late session: exits only, no new entries.  NONE.

_TIME_WINDOWS = [
    #  (start,   end,     allowed_strategy_bases_or_None)
    ("09:15", "09:30", []),                                              # Opening noise
    ("09:30", "11:30", None),                                            # Prime time
    ("11:30", "12:00", ["ORB", "VWAP-Pullback", "TrendFollow"]),        # Pre-lunch selective
    ("12:00", "13:00", ["MeanReversion", "VWAP-Pullback"]),             # Lunch reversion only
    ("13:00", "14:30", None),                                            # Post-lunch
    ("14:30", "23:59", []),                                              # Late: exits only
]


def get_allowed_strategies(now=None):
    """
    Returns: None  = all strategies allowed
             []    = no new entries
             [..] = whitelist of allowed strategy base names
    """
    now = now or get_ist_now().time()
    for s_str, e_str, allowed in _TIME_WINDOWS:
        s = datetime.strptime(s_str, "%H:%M").time()
        e = datetime.strptime(e_str, "%H:%M").time()
        if s <= now <= e:
            return allowed
    return None


def is_tradeable_time(now=None):
    """Returns (ok: bool, reason: str)."""
    allowed = get_allowed_strategies(now)
    now_val = now or get_ist_now().time()
    now_str = now_val.strftime("%H:%M")
    if allowed == []:
        return False, f"Time gate: no new entries at {now_str}"
    return True, "ok"


# ─────────────────────────────────────────────────────────────────────────────
# Layer 0: Event Risk Filter  (H4)
# ─────────────────────────────────────────────────────────────────────────────

def check_event_risk(cfg=None):
    """
    Layer 0: Event Risk Filter.

    On high-impact calendar events (RBI MPC meetings, Union Budget, NSE/BSE
    F&O expiry days, market holidays) the normal confluence thresholds are
    tightened or trading is suspended entirely.

    Requires ``event_calendar.py`` to be present in the project.  If the
    module is absent ``_EVENT_CALENDAR_AVAILABLE`` will be False and this
    function is never called — all other layers run unchanged.

    Expected return shape from ``get_event_risk()``:
        {
            'level': 'LOW' | 'HIGH' | 'VERY_HIGH' | 'HOLIDAY',
            'events': ['RBI MPC', ...],
            'recommended_action': 'NORMAL' | 'REDUCE' | 'AVOID',
        }

    Returns:
        (ok: bool, reason: str, risk_level: str)
        ok=False  → block the trade outright (e.g. holiday)
        ok=True   → allow, but caller may tighten thresholds
    """
    if not _EVENT_CALENDAR_AVAILABLE:
        # Module not installed — behave as if risk is LOW, allow everything.
        return True, "ok", "LOW"

    try:
        risk_info = get_event_risk()
        level  = risk_info.get('level', 'LOW')
        events = risk_info.get('events', [])
        # action is informational; threshold adjustment is done in evaluate_signal
        action = risk_info.get('recommended_action', 'NORMAL')  # noqa: F841

        if level == 'HOLIDAY':
            # NSE is closed — no trading at all.
            return False, f"NSE Holiday — no trading today: {', '.join(events)}", level

        elif level == 'VERY_HIGH':
            # e.g. RBI MPC day or Budget — allow but flag for size reduction.
            return True, (
                f"VERY HIGH risk day ({', '.join(events)}) "
                f"— size halved, confluence +2"
            ), level

        elif level == 'HIGH':
            # e.g. F&O expiry — allow but flag for extra confluence.
            return True, (
                f"HIGH risk day ({', '.join(events)}) "
                f"— confluence +1 required"
            ), level

        # LOW / MEDIUM — no restrictions.
        return True, "ok", level

    except Exception:
        # Defensive: never let a broken calendar module block real trades.
        return True, "ok", "LOW"


def is_strategy_allowed_now(strategy_name, now=None):
    """Check if a specific strategy base is permitted at the current time."""
    allowed = get_allowed_strategies(now)
    if allowed is None:
        return True
    if allowed == []:
        return False
    return any(strategy_name.startswith(base) for base in allowed)


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2: Volatility Filter
# ─────────────────────────────────────────────────────────────────────────────
#
# ATR expressed as % of price.
# Sweet spot: 0.4% – 2.5%
#   Below 0.4%: spread/slippage eats the edge, market too quiet to break.
#   Above 2.5%: stops blow out, risk calculation becomes unreliable.

def is_volatility_acceptable(candles, min_pct=0.004, max_pct=0.025):
    """Returns (ok: bool, reason: str)."""
    if not candles or len(candles) < 15:
        return True, "no data"

    atr_vals = calculate_atr(candles, 14)
    atr      = atr_vals[-1]
    price    = candles[-1]["close"]

    if atr is None or price <= 0:
        return True, "no atr"

    pct = atr / price
    if pct < min_pct:
        return False, f"ATR {pct:.2%} too low — market too quiet"
    if pct > max_pct:
        return False, f"ATR {pct:.2%} too high — excessive volatility"
    return True, f"ATR {pct:.2%} acceptable"


# ─────────────────────────────────────────────────────────────────────────────
# Layer 3: Multi-Factor Confluence Score
# ─────────────────────────────────────────────────────────────────────────────
#
# Seven independent checks. Each is a separate reason to be in the trade.
# Require >= min_score (default 4) to enter.
#
# Scores are additive, not multiplicative — one miss is forgivable.
# Seven passes = maximum conviction.

def calculate_confluence_score(signal, candles, htf_candles=None):
    """
    Returns (score: int, max_score: int, details: list[str]).
    Caller decides threshold; recommended minimum is 4.
    """
    if not signal or not candles or len(candles) < 20:
        return 0, 7, ["insufficient candle data"]

    is_long      = "Buy" in signal.get("strategy", "")
    close_prices = [c["close"] for c in candles]
    curr         = candles[-1]
    score        = 0
    details      = []

    # 1 — EMA20 direction
    ema20 = calculate_ema(close_prices, 20)
    if ema20[-1] is not None:
        aligned = (is_long and curr["close"] > ema20[-1]) or \
                  (not is_long and curr["close"] < ema20[-1])
        if aligned:
            score += 1; details.append("✓ Price vs EMA20")
        else:
            details.append("✗ EMA20 wrong side")

    # 2 — VWAP direction
    vwap = calculate_vwap(candles)
    if vwap and vwap[-1] is not None:
        aligned = (is_long and curr["close"] > vwap[-1]) or \
                  (not is_long and curr["close"] < vwap[-1])
        if aligned:
            score += 1; details.append("✓ Price vs VWAP")
        else:
            details.append("✗ VWAP wrong side")

    # 3 — RSI momentum & range
    rsi = calculate_rsi(close_prices, 14)
    if rsi[-1] is not None and rsi[-2] is not None:
        rising = rsi[-1] > rsi[-2]
        r      = rsi[-1]
        ok = (is_long  and rising and 35 < r < 72) or \
             (not is_long and not rising and 28 < r < 65)
        if ok:
            score += 1; details.append(f"✓ RSI {r:.0f} momentum")
        else:
            details.append(f"✗ RSI {r:.0f} not aligned")

    # 4 — Volume surge (> 1.2× 20-bar avg)
    if len(candles) >= 22:
        avg_vol = sum(c["volume"] for c in candles[-21:-1]) / 20
        if avg_vol > 0 and curr["volume"] >= avg_vol * 1.2:
            score += 1; details.append(f"✓ Volume {curr['volume']/avg_vol:.1f}× avg")
        else:
            details.append("✗ Volume weak")

    # 5 — HTF trend alignment
    htf = signal.get("htf_trend", "neutral")
    if htf == "neutral":
        score += 1; details.append("~ HTF neutral (pass)")
    elif (is_long and htf == "up") or (not is_long and htf == "down"):
        score += 1; details.append(f"✓ HTF {htf}")
    else:
        details.append(f"✗ HTF counter-trend ({htf})")

    # 6 — Risk:Reward >= 1.5:1
    entry = signal.get("entry_price", 0)
    sl    = signal.get("stop_loss", 0)
    t2    = signal.get("target_2", signal.get("target_1", 0))
    if entry and sl and t2 and abs(entry - sl) > 0:
        rr = abs(t2 - entry) / abs(entry - sl)
        if rr >= 1.5:
            score += 1; details.append(f"✓ R:R {rr:.1f}:1")
        else:
            details.append(f"✗ R:R {rr:.1f}:1 (min 1.5)")

    # 7 — Regime-strategy compatibility
    regime   = signal.get("regime", "unknown")
    strat    = signal.get("strategy", "")
    trend_strats = ("ORB", "Momentum", "TrendFollow")
    range_strats = ("MeanReversion", "VWAP")
    regime_ok = (
        (regime in ("trending_up", "trending_down") and any(s in strat for s in trend_strats)) or
        (regime == "ranging" and any(s in strat for s in range_strats)) or
        (regime not in ("choppy",))
    )
    if regime_ok:
        score += 1; details.append(f"✓ Regime {regime}")
    else:
        details.append(f"✗ Choppy market for {strat.split('-')[0]}")

    return score, 7, details


# ─────────────────────────────────────────────────────────────────────────────
# Layer 4: Consecutive Loss Circuit Breaker
# ─────────────────────────────────────────────────────────────────────────────
#
# After N consecutive losses, pause new entries for halt_minutes.
# This forces a cooldown after a string of bad trades, preventing "tilt"
# entries where emotion overrides discipline.

def check_consecutive_loss_halt(trade_history, max_consecutive=3, halt_minutes=30, paper_trading=False):
    """Returns (halted: bool, reason: str)."""
    # M11: Bypass consecutive loss halt in paper trading mode
    if paper_trading:
        return False, "ok (paper trading bypass)"
        
    today      = get_ist_now().date().isoformat()
    today_trades = [
        t for t in trade_history
        if t.get("exit_time", "").startswith(today)
    ]

    if len(today_trades) < max_consecutive:
        return False, "ok"

    recent = today_trades[-max_consecutive:]
    if not all(t.get("pnl", 0) < 0 for t in recent):
        return False, "ok"

    # All N most recent are losses — check if cooldown still active
    last_exit = recent[-1].get("exit_time", "")
    if not last_exit:
        return False, "ok"

    try:
        elapsed = (get_ist_now() - datetime.fromisoformat(last_exit)).total_seconds() / 60
        if elapsed < halt_minutes:
            remaining = int(halt_minutes - elapsed)
            return True, f"{max_consecutive} consecutive losses — cooling down {remaining} min"
    except Exception:
        pass

    return False, "ok"


# ─────────────────────────────────────────────────────────────────────────────
# Layer 5: Kelly Criterion Position Sizing
# ─────────────────────────────────────────────────────────────────────────────
#
# Full Kelly: f* = (win_rate × R/R  −  loss_rate) / (R/R)
# Quarter-Kelly is used (25% of f*) for practical safety margin.
#
# When edge is strong (PF > 2, WR > 60%): size UP slightly.
# When edge is weak  (PF < 1.2, WR < 45%): size DOWN significantly.
# No historical data (<10 trades): use default risk.

def calculate_kelly_risk(trade_history, base_risk, lookback=30, strategy_name=None):
    """
    Returns an adjusted risk-per-trade amount (≥ 25% and ≤ 150% of base_risk).
    """
    if strategy_name:
        base_strat = strategy_name.split("-")[0]
        recent = [t for t in trade_history if t.get("pnl") is not None and t.get("strategy", "").startswith(base_strat)]
        recent = recent[-lookback:]
    else:
        recent = [t for t in trade_history[-lookback:] if t.get("pnl") is not None]

    if len(recent) < 10:
        global_recent = [t for t in trade_history[-lookback:] if t.get("pnl") is not None]
        if len(global_recent) >= 10:
            recent = global_recent
        else:
            return base_risk   # insufficient history, use base

    wins   = [t["pnl"] for t in recent if t["pnl"] > 0]
    losses = [abs(t["pnl"]) for t in recent if t["pnl"] < 0]

    if not wins or not losses:
        return base_risk

    win_rate  = len(wins)   / len(recent)
    loss_rate = len(losses) / len(recent)
    avg_win   = sum(wins)   / len(wins)
    avg_loss  = sum(losses) / len(losses)
    rr        = avg_win / avg_loss if avg_loss > 0 else 1.0

    # Full Kelly formula
    full_kelly = (win_rate * rr - loss_rate) / rr

    if full_kelly <= 0:
        # Negative edge: use minimum sizing — protect capital
        return round(max(base_risk * 0.25, 50.0), 2)

    # Using Quarter-Kelly (25% of Full Kelly) — standard institutional practice.
    # This significantly reduces variance while preserving positive expected value.
    # Quarter-Kelly caps losses at ~13% of bankroll vs Full Kelly's ~50%.
    fraction = min(full_kelly * 0.25, 1.0)   # Quarter-Kelly, cap at 100% of base
    fraction = max(fraction, 0.25)             # floor at 25% of base

    return round(base_risk * fraction, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Layer 6: Nifty 50 Broad Market Filter
# ─────────────────────────────────────────────────────────────────────────────
#
# Individual stocks move with the market 70-80% of the time.
# Ignoring the index trend is ignoring the tide direction.

def check_nifty_alignment(signal_direction, nifty_trend):
    """
    signal_direction: 'long' or 'short'
    nifty_trend:      'up', 'down', or 'neutral'
    Returns (ok: bool, reason: str).
    """
    if nifty_trend == "neutral":
        return True, "Nifty neutral — no filter applied"
    if signal_direction == "long" and nifty_trend == "down":
        return False, "Nifty trending DOWN — long entries suppressed"
    if signal_direction == "short" and nifty_trend == "up":
        return False, "Nifty trending UP — short entries suppressed"
    return True, f"Nifty {nifty_trend} aligns with {signal_direction}"


# ─────────────────────────────────────────────────────────────────────────────
# Composite quality gate (convenience wrapper)
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_signal(signal, candles, htf_candles, nifty_trend, trade_history, cfg):
    """
    Runs all quality layers in sequence.
    Returns (approved: bool, reason: str, details: dict).
    Fail-fast: returns on the first blocking layer.

    Layer ordering:
        0 — Event Risk (H4)          — block holidays; tighten on high-risk days
        1 — Time of Day              — no entries outside permitted windows
        2 — Volatility (ATR)         — skip when market is too quiet or too wild
        3 — Consecutive Loss Halt    — cooldown after a streak of losses
        4 — Nifty Alignment          — trade with the broad-market tide
        5 — Confluence Score         — multi-factor minimum threshold
    """
    details = {}

    # ── Layer 0: Event Risk (H4) ──────────────────────────────────────────────
    # Only active when event_calendar.py is present in the project.
    # On HOLIDAY days:    block the trade outright.
    # On VERY_HIGH days:  allow, but tighten min_confluence_score by +2.
    # On HIGH days:       allow, but tighten min_confluence_score by +1.
    if _EVENT_CALENDAR_AVAILABLE:
        event_ok, event_reason, event_level = check_event_risk(cfg)
        if not event_ok:
            # Hard block — e.g. NSE holiday.
            return False, event_reason, details

        # On elevated-risk days, bump the confluence requirement before we
        # reach Layer 5.  We shadow `cfg` with a shallow copy so the caller's
        # dict is never mutated.
        if event_level in ('VERY_HIGH', 'HIGH') and 'min_confluence_score' not in details:
            orig_min = int(cfg.get('min_confluence_score', 4))
            extra    = 2 if event_level == 'VERY_HIGH' else 1
            cfg      = dict(cfg)                          # shallow copy — do NOT mutate caller
            cfg['min_confluence_score'] = orig_min + extra
            if event_reason != 'ok':
                details['event_risk'] = event_reason     # surface reason in trade log

    # ── Layer 1: Time ─────────────────────────────────────────────────────────
    if cfg.get("enable_time_filter", True):
        ok, reason = is_tradeable_time()
        if not ok:
            return False, reason, details
        ok2 = is_strategy_allowed_now(signal.get("strategy", ""))
        if not ok2:
            return False, f"Strategy not permitted at current time", details

    # Layer 2: Volatility
    if cfg.get("enable_volatility_filter", True):
        ok, reason = is_volatility_acceptable(
            candles,
            min_pct=float(cfg.get("volatility_min_atr_pct", 0.001)),
            max_pct=float(cfg.get("volatility_max_atr_pct", 0.025)),
        )
        if not ok:
            return False, reason, details

    # Layer 3: Consecutive loss halt
    if cfg.get("enable_loss_halt", True):
        halted, reason = check_consecutive_loss_halt(
            trade_history,
            max_consecutive=int(cfg.get("max_consecutive_losses", 3)),
            halt_minutes=int(cfg.get("loss_halt_minutes", 30)),
            paper_trading=bool(cfg.get("paper_trading", False))
        )
        if halted:
            return False, reason, details

    # Layer 4: Nifty alignment
    if cfg.get("enable_nifty_filter", True):
        direction = "long" if "Buy" in signal.get("strategy", "") else "short"
        ok, reason = check_nifty_alignment(direction, nifty_trend)
        if not ok:
            return False, reason, details

    # Layer 5: Confluence scoring
    # VWAPTrendPullback carries its own confidence score — bypass generic confluence
    if signal.get("confidence") is not None:
        details["confluence_score"] = signal["confidence"]
        return True, f"All gates passed — strategy confidence {signal['confidence']}/100", details

    min_score = int(cfg.get("min_confluence_score", 4))
    score, max_score, conf_details = calculate_confluence_score(signal, candles, htf_candles)
    details["confluence"] = {"score": score, "max": max_score, "checks": conf_details}
    if cfg.get("enable_confluence_filter", True) and score < min_score:
        return False, f"Confluence {score}/{max_score} (need {min_score}): {conf_details[-1]}", details

    details["confluence_score"] = score
    return True, f"All gates passed — confluence {score}/{max_score}", details


SECTOR_MAP = {
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT", "LTIM": "IT",
    "HDFCBANK": "BANK", "ICICIBANK": "BANK", "SBIN": "BANK", "AXISBANK": "BANK", "KOTAKBANK": "BANK", "INDUSINDBK": "BANK",
    "RELIANCE": "OIL_GAS", "ONGC": "OIL_GAS", "BPCL": "OIL_GAS", "IOC": "OIL_GAS", "GAIL": "OIL_GAS",
    "TATASTEEL": "METALS", "JINDALSTEEL": "METALS", "HINDALCO": "METALS", "JSWSTEEL": "METALS", "COALINDIA": "METALS",
    "MARUTI": "AUTO", "TATAMOTORS": "AUTO", "M&M": "AUTO", "BAJAJ-AUTO": "AUTO", "HEROMOTOCO": "AUTO", "EICHERMOT": "AUTO",
    "BHARTIARTL": "TELECOM",
    "ITC": "FMCG", "HINDUNILVR": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG", "TATACONSUM": "FMCG",
    "SUNPHARMA": "PHARMA", "CIPLA": "PHARMA", "DRREDDY": "PHARMA", "DIVISLAB": "PHARMA", "APOLLOHOSP": "PHARMA",
    "L&T": "CONSTRUCTION", "ULTRACEMCO": "CONSTRUCTION", "GRASIM": "CONSTRUCTION",
    "ADANIENT": "CONGLOMERATE", "ADANIPORTS": "CONGLOMERATE",
    "POWERGRID": "POWER", "NTPC": "POWER",
    "TITAN": "CONSUMER_DURABLES", "ASIANPAINT": "CONSUMER_DURABLES", "BERGERPAINT": "CONSUMER_DURABLES",
    "HDFCLIFE": "FINANCIAL", "SBILIFE": "FINANCIAL", "BAJFINANCE": "FINANCIAL", "BAJAJFINSV": "FINANCIAL",
}


# ─────────────────────────────────────────────────────────────────────────────
# Sector Rotation Intelligence  (M2)
# ─────────────────────────────────────────────────────────────────────────────
#
# Philosophy:
#   Money rotates through sectors intraday.  When IT stocks are printing
#   green all morning, new IT longs have a sector tailwind; when they are
#   all red, fight the sector only with extra conviction.
#
# How to use:
#   1. Call ``update_sector_performance(trade_history)`` once per scan cycle
#      (e.g. in your main scanner loop) to keep the cache fresh.
#   2. In your signal-generation / position-sizing code, call
#      ``get_sector_bias(symbol)`` and adjust confluence or size accordingly:
#
#           bias = get_sector_bias(symbol)
#           effective_min_score = min_confluence_score - bias
#
#      This makes longs easier in a leading sector and harder in a lagging one.
# ─────────────────────────────────────────────────────────────────────────────

# In-memory sector performance cache — updated each scan cycle.
# Keyed by sector name (string); values are floats / ints.
_sector_daily_pnl: dict = {}    # sector -> today's total realised PnL (₹)
_sector_trade_counts: dict = {} # sector -> number of completed trades today


def update_sector_performance(trade_history):
    """
    Rebuild the sector PnL cache from today's completed trades.

    Should be called **once per scan cycle** (not on every signal) so that
    the in-memory dictionaries stay current without repeated iteration.

    Args:
        trade_history (list[dict]): Full list of trade records.  Each record
            must have at minimum:
                'symbol'    : str   — e.g. 'INFY'
                'exit_time' : str   — ISO-8601 datetime of trade close
                'pnl'       : float — realised PnL in rupees
            Records with no 'exit_time' or whose exit_time does not start
            with today's date (IST) are ignored.
    """
    global _sector_daily_pnl, _sector_trade_counts

    today   = get_ist_now().date().isoformat()   # e.g. '2026-06-29'
    pnl_map   = {}
    count_map = {}

    for t in trade_history:
        # Only count trades that were closed today.
        if not t.get('exit_time', '').startswith(today):
            continue

        symbol = t.get('symbol', '')
        sector = SECTOR_MAP.get(symbol, 'OTHER')

        pnl_map[sector]   = pnl_map.get(sector, 0.0)   + float(t.get('pnl', 0.0))
        count_map[sector] = count_map.get(sector, 0)    + 1

    # Atomically replace both caches so get_sector_bias never sees a partial state.
    _sector_daily_pnl        = pnl_map
    _sector_trade_counts     = count_map


def get_sector_bias(symbol):
    """
    Return a confluence-score adjustment based on today's sector performance.

    The adjustment is intentionally coarse — one point up or down — so that
    sector rotation is a *nudge*, not the primary decision driver.

    Thresholds (per-trade averages, in ₹):
        avg_pnl > +200  → sector is leading today  → bias = +1
        avg_pnl < -150  → sector is lagging today  → bias = -1
        otherwise       → neutral                  → bias =  0

    Args:
        symbol (str): NSE symbol, e.g. 'INFY'.

    Returns:
        int:
            +1  sector is leading  (relax confluence threshold by 1)
             0  neutral            (no change)
            -1  sector is lagging  (tighten confluence threshold by 1)
    """
    sector = SECTOR_MAP.get(symbol, 'OTHER')

    # Unknown / unmapped sector — no reliable data, stay neutral.
    if sector == 'OTHER' or sector not in _sector_daily_pnl:
        return 0

    pnl   = _sector_daily_pnl.get(sector, 0.0)
    count = _sector_trade_counts.get(sector, 0)

    # Require at least 2 completed trades to avoid single-trade noise.
    if count < 2:
        return 0

    avg_pnl = pnl / count

    if avg_pnl > 200:    # sector is winning well today → provide tailwind
        return +1
    elif avg_pnl < -150: # sector is losing today → require extra conviction
        return -1

    return 0  # neutral zone — no adjustment

