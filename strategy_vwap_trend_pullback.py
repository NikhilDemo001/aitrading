"""
VWAP Trend Pullback Strategy (VTP)
====================================
Entry Logic:
  Long  — Price > VWAP, HH+HL structure, EMA20 slope up, pullback to VWAP/EMA20
          with declining volume, strong bullish confirmation candle.
  Short — Mirror: Price < VWAP, LH+LL, EMA20 slope down, pullback up.

Confidence scoring 0-100 across 6 independent dimensions.
Only fires when score >= threshold (config: vwap_tp_confidence_threshold, default 80).

Indicators are imported lazily inside check_vwap_trend_pullback to avoid the circular
import that arises because strategies.py also imports this module.
"""


_LEFT  = 2    # bars left of pivot for confirmation
_RIGHT = 2    # bars right of pivot for confirmation
_PB_W  = 5    # pullback window (candles before current)
_IMP_W = 5    # impulse window (candles before pullback window)


# ── Swing pivot helpers ──────────────────────────────────────────────────────

def _find_pivot_highs(candles, left=_LEFT, right=_RIGHT):
    """Confirmed swing highs as list of (index, price). Requires strict inequality."""
    result = []
    limit  = len(candles) - right
    for i in range(left, limit):
        h = candles[i]["high"]
        if all(candles[i - j]["high"] < h for j in range(1, left + 1)) and \
           all(candles[i + j]["high"] < h for j in range(1, right + 1)):
            result.append((i, h))
    return result


def _find_pivot_lows(candles, left=_LEFT, right=_RIGHT):
    """Confirmed swing lows as list of (index, price). Requires strict inequality."""
    result = []
    limit  = len(candles) - right
    for i in range(left, limit):
        lo = candles[i]["low"]
        if all(candles[i - j]["low"] > lo for j in range(1, left + 1)) and \
           all(candles[i + j]["low"] > lo for j in range(1, right + 1)):
            result.append((i, lo))
    return result


# ── Market structure ─────────────────────────────────────────────────────────

def detect_market_structure(candles):
    """
    Determines trend structure from swing pivots.
    Returns (structure, last_swing_high, last_swing_low).
    structure: 'bullish' | 'bearish' | 'neutral'
    """
    ph = _find_pivot_highs(candles)
    pl = _find_pivot_lows(candles)

    last_sh = ph[-1][1] if ph else None
    last_sl = pl[-1][1] if pl else None

    if len(ph) >= 2 and len(pl) >= 2:
        hh = ph[-1][1] > ph[-2][1]
        hl = pl[-1][1] > pl[-2][1]
        lh = ph[-1][1] < ph[-2][1]
        ll = pl[-1][1] < pl[-2][1]
        if hh and hl:
            return "bullish", last_sh, last_sl
        if lh and ll:
            return "bearish", last_sh, last_sl

    return "neutral", last_sh, last_sl


# ── EMA slope ────────────────────────────────────────────────────────────────

def _ema_slope(ema_vals, lookback=5):
    """Returns 'up' | 'down' | 'flat' based on percentage change over lookback bars."""
    vals = [v for v in ema_vals[-lookback:] if v is not None]
    if len(vals) < 2:
        return "flat"
    pct = (vals[-1] - vals[0]) / vals[0] if vals[0] else 0
    if pct > 0.0003:
        return "up"
    if pct < -0.0003:
        return "down"
    return "flat"


# ── VWAP flat check ──────────────────────────────────────────────────────────

def _vwap_flat(vwap_vals, lookback=6, threshold=0.0003):
    """True when VWAP barely moves — indicates ranging/low-conviction market."""
    vals = [v for v in vwap_vals[-lookback:] if v is not None]
    if len(vals) < 2:
        return True
    change = abs(vals[-1] - vals[0]) / vals[0] if vals[0] else 0
    return change < threshold


# ── Pullback analysis ────────────────────────────────────────────────────────

def _pullback_data(candles, direction, vwap_val, ema20_val,
                   pb_window=_PB_W, imp_window=_IMP_W):
    """
    Analyses the candles immediately before the current bar to verify a valid
    low-volume pullback toward VWAP or EMA20 occurred.

    Returns dict with keys:
      valid, avg_pb_vol, avg_imp_vol, touched_vwap, touched_ema, pb_depth_pct
    """
    needed = pb_window + imp_window + 2
    if len(candles) < needed:
        return {"valid": False, "avg_pb_vol": 0, "avg_imp_vol": 0,
                "touched_vwap": False, "touched_ema": False, "pb_depth_pct": 0}

    pb_slice  = candles[-(pb_window + 1):-1]
    imp_slice = candles[-(pb_window + imp_window + 1):-(pb_window + 1)]

    avg_pb  = sum(c["volume"] for c in pb_slice)  / max(len(pb_slice),  1)
    avg_imp = sum(c["volume"] for c in imp_slice) / max(len(imp_slice), 1)

    pb_closes = [c["close"] for c in pb_slice]

    if direction == "long":
        moved_toward = pb_closes[-1] < pb_closes[0]          # price came down
        min_low      = min(c["low"] for c in pb_slice)
        touched_vwap = vwap_val  is not None and min_low <= vwap_val  * 1.005
        touched_ema  = ema20_val is not None and min_low <= ema20_val * 1.005

        imp_high = max(c["high"] for c in imp_slice)
        imp_low  = min(c["low"]  for c in imp_slice)
        imp_size = max(imp_high - imp_low, 0.001)
        retrace  = min((imp_high - min_low) / imp_size, 1.0)
    else:
        moved_toward = pb_closes[-1] > pb_closes[0]          # price came up
        max_high     = max(c["high"] for c in pb_slice)
        touched_vwap = vwap_val  is not None and max_high >= vwap_val  * 0.995
        touched_ema  = ema20_val is not None and max_high >= ema20_val * 0.995

        imp_high = max(c["high"] for c in imp_slice)
        imp_low  = min(c["low"]  for c in imp_slice)
        imp_size = max(imp_high - imp_low, 0.001)
        retrace  = min((max_high - imp_low) / imp_size, 1.0)

    near_support = touched_vwap or touched_ema
    valid = (
        moved_toward and
        near_support and
        avg_imp > 0 and
        avg_pb < avg_imp * 0.9    # pullback volume must be weaker than impulse
    )

    return {
        "valid":        valid,
        "avg_pb_vol":   avg_pb,
        "avg_imp_vol":  avg_imp,
        "touched_vwap": bool(touched_vwap),
        "touched_ema":  bool(touched_ema),
        "pb_depth_pct": round(retrace, 3),
    }


# ── Candle quality ───────────────────────────────────────────────────────────

def _candle_quality(candle, direction):
    """
    Returns (is_strong: bool, body_ratio: float, close_at_extreme: bool).
    strong = bullish/bearish body ≥ 50% of candle range.
    close_at_extreme = close within top/bottom 25% of range.
    """
    body = abs(candle["close"] - candle["open"])
    rng  = max(candle["high"] - candle["low"], 0.0001)
    ratio = body / rng

    if direction == "long":
        bullish      = candle["close"] > candle["open"]
        at_extreme   = (candle["high"] - candle["close"]) / rng < 0.25
        return bullish and ratio >= 0.5, ratio, at_extreme
    else:
        bearish    = candle["close"] < candle["open"]
        at_extreme = (candle["close"] - candle["low"]) / rng < 0.25
        return bearish and ratio >= 0.5, ratio, at_extreme


# ── Confidence scoring ───────────────────────────────────────────────────────

def calculate_confidence_score(d):
    """
    Computes a 0-100 confidence score from 6 independent dimensions.

    Input dict keys:
      vwap_dist_pct, pivot_count, imp_vol, pb_vol,
      touched_vwap, touched_ema, pb_depth_pct,
      body_ratio, close_at_extreme, atr_pct

    Returns (score: int, detail: dict)
    """
    score  = 0
    detail = {}

    # 1. VWAP distance (20 pts) — how decisively price is on the correct side
    vd  = abs(d.get("vwap_dist_pct", 0))
    pts = 20 if vd >= 0.005 else 12 if vd >= 0.002 else 6 if vd > 0 else 0
    score += pts; detail["vwap_alignment"] = pts

    # 2. Trend structure quality (20 pts) — more pivots = more confirmed trend
    pc  = d.get("pivot_count", 0)
    pts = 20 if pc >= 3 else 12 if pc == 2 else 5 if pc == 1 else 0
    score += pts; detail["trend_structure"] = pts

    # 3. Volume confirmation (20 pts) — impulse/pullback ratio
    iv  = d.get("imp_vol", 0)
    pv  = max(d.get("pb_vol", 1), 1)
    r   = iv / pv
    pts = 20 if r >= 2.0 else 12 if r >= 1.5 else 6 if r >= 1.1 else 0
    score += pts; detail["volume_ratio"] = pts

    # 4. Pullback quality (15 pts)
    if d.get("touched_vwap"):
        pts = 15
    elif d.get("touched_ema"):
        pts = 10
    else:
        pd  = d.get("pb_depth_pct", 0)
        pts = 8 if pd >= 0.4 else 4 if pd >= 0.2 else 0
    score += pts; detail["pullback_quality"] = pts

    # 5. Candle confirmation (15 pts)
    br  = d.get("body_ratio", 0)
    ext = d.get("close_at_extreme", False)
    pts = 15 if br >= 0.7 and ext else 10 if br >= 0.5 else 4 if br >= 0.3 else 0
    score += pts; detail["candle_quality"] = pts

    # 6. ATR in sweet-spot (10 pts)
    ap  = d.get("atr_pct", 0)
    pts = 10 if 0.004 <= ap <= 0.025 else 5 if 0.003 <= ap <= 0.030 else 0
    score += pts; detail["volatility"] = pts

    return min(score, 100), detail


# ── Main entry point ─────────────────────────────────────────────────────────

def check_vwap_trend_pullback(candles, htf_candles=None, config=None, htf_trend="neutral"):
    """
    VWAP Trend Pullback Strategy.

    Parameters
    ----------
    candles     : intraday 5-min candles (ascending, oldest first)
    htf_candles : 15-min candles for higher-timeframe bias (optional)
    config      : bot config dict — reads enable_vwap_trend_pullback,
                  vwap_tp_confidence_threshold
    htf_trend   : 'up' | 'down' | 'neutral'

    Returns signal dict or None.
    """
    if config is None:
        config = {}

    if not config.get("enable_vwap_trend_pullback", True):
        return None

    if len(candles) < 30:
        return None

    # Lazy import breaks the circular dependency with strategies.py
    from strategies import calculate_ema, calculate_vwap, calculate_atr

    closes = [c["close"] for c in candles]
    ema20  = calculate_ema(closes, 20)
    vwap   = calculate_vwap(candles)
    atr_   = calculate_atr(candles, 14)
    idx    = len(candles) - 1

    e20   = ema20[idx]
    vc    = vwap[idx]
    atr_v = atr_[idx]

    if e20 is None or vc is None or atr_v is None:
        return None

    # Avoid ranging markets
    if _vwap_flat(vwap):
        return None

    # EMA slope and market structure
    slope = _ema_slope(ema20)
    structure, last_sh, last_sl = detect_market_structure(candles)
    if structure == "neutral":
        return None

    curr    = candles[idx]
    atr_pct = atr_v / curr["close"] if curr["close"] > 0 else 0

    # Low-volume sanity filter
    avg_vol20 = (sum(c["volume"] for c in candles[-21:-1]) / 20
                 if len(candles) >= 22 else 0)
    if avg_vol20 > 0 and curr["volume"] < avg_vol20 * 0.3:
        return None

    ph = _find_pivot_highs(candles)
    pl = _find_pivot_lows(candles)
    threshold = int(config.get("vwap_tp_confidence_threshold", 80))

    # ── LONG setup ────────────────────────────────────────────────────────────
    if structure == "bullish" and slope != "down" and htf_trend != "down":
        if curr["close"] > vc:
            pb     = _pullback_data(candles, "long", vc, e20)
            strong, body_ratio, close_top = _candle_quality(curr, "long")
            vol_ok = curr["volume"] >= avg_vol20 * 1.2 if avg_vol20 > 0 else True

            if pb["valid"] and strong and vol_ok:
                score, detail = calculate_confidence_score({
                    "vwap_dist_pct":    (curr["close"] - vc) / vc,
                    "pivot_count":      len(ph),
                    "imp_vol":          pb["avg_imp_vol"],
                    "pb_vol":           pb["avg_pb_vol"],
                    "touched_vwap":     pb["touched_vwap"],
                    "touched_ema":      pb["touched_ema"],
                    "pb_depth_pct":     pb["pb_depth_pct"],
                    "body_ratio":       body_ratio,
                    "close_at_extreme": close_top,
                    "atr_pct":          atr_pct,
                })

                if score >= threshold:
                    sl   = (min(last_sl, curr["low"]) if last_sl else curr["low"]) - atr_v * 0.2
                    risk = curr["close"] - sl
                    if risk <= 0:
                        return None
                    return {
                        "strategy":          "VWAPTrendPullback-Buy",
                        "trigger_time":      curr["timestamp"],
                        "entry_price":       round(curr["close"], 2),
                        "stop_loss":         round(sl, 2),
                        "target_1":          round(curr["close"] + 2.0 * risk, 2),
                        "target_2":          round(curr["close"] + 3.5 * risk, 2),
                        "vwap":              round(vc, 2),
                        "ema_20":            round(e20, 2),
                        "atr":               round(atr_v, 2),
                        "confidence":        score,
                        "confidence_detail": detail,
                        "structure":         structure,
                        "ema_slope":         slope,
                    }

    # ── SHORT setup ───────────────────────────────────────────────────────────
    if structure == "bearish" and slope != "up" and htf_trend != "up":
        if curr["close"] < vc:
            pb     = _pullback_data(candles, "short", vc, e20)
            strong, body_ratio, close_bot = _candle_quality(curr, "short")
            vol_ok = curr["volume"] >= avg_vol20 * 1.2 if avg_vol20 > 0 else True

            if pb["valid"] and strong and vol_ok:
                score, detail = calculate_confidence_score({
                    "vwap_dist_pct":    (vc - curr["close"]) / vc,
                    "pivot_count":      len(pl),
                    "imp_vol":          pb["avg_imp_vol"],
                    "pb_vol":           pb["avg_pb_vol"],
                    "touched_vwap":     pb["touched_vwap"],
                    "touched_ema":      pb["touched_ema"],
                    "pb_depth_pct":     pb["pb_depth_pct"],
                    "body_ratio":       body_ratio,
                    "close_at_extreme": close_bot,
                    "atr_pct":          atr_pct,
                })

                if score >= threshold:
                    sl   = (max(last_sh, curr["high"]) if last_sh else curr["high"]) + atr_v * 0.2
                    risk = sl - curr["close"]
                    if risk <= 0:
                        return None
                    return {
                        "strategy":          "VWAPTrendPullback-Short",
                        "trigger_time":      curr["timestamp"],
                        "entry_price":       round(curr["close"], 2),
                        "stop_loss":         round(sl, 2),
                        "target_1":          round(curr["close"] - 2.0 * risk, 2),
                        "target_2":          round(curr["close"] - 3.5 * risk, 2),
                        "vwap":              round(vc, 2),
                        "ema_20":            round(e20, 2),
                        "atr":               round(atr_v, 2),
                        "confidence":        score,
                        "confidence_detail": detail,
                        "structure":         structure,
                        "ema_slope":         slope,
                    }

    return None
