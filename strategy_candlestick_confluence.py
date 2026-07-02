"""
Candlestick Pattern Confluence (CPC) Strategy
==============================================
Identifies high-conviction 1-candle, 2-candle, and 3-candle patterns,
but only enters trades when they occur at key support/resistance levels
(dynamic like EMA/VWAP, or static like PDH/PDL) with high volume.
"""

import datetime
from datetime import timezone, timedelta
from strategies import calculate_ema, calculate_vwap, calculate_atr
from candlestick_patterns import (
    detect_hammer, detect_shooting_star, detect_bullish_engulfing,
    detect_bearish_engulfing, detect_morning_star, detect_evening_star,
    detect_tweezer_bottoms, detect_tweezer_tops, detect_piercing_line,
    detect_dark_cloud_cover
)

def get_ist_now():
    """Returns timezone-naive datetime representing IST."""
    return datetime.datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=5, minutes=30)

def check_candlestick_confluence_strategy(candles_5m, candles_15m=None, config=None, htf_trend="neutral"):
    """
    Checks for high-confluence candlestick patterns at key S/R levels.
    """
    if not candles_5m or len(candles_5m) < 21:
        return None

    config = config or {}
    if not config.get("enable_candlestick_confluence", True):
        return None
    client = config.get("_client")
    instrument_key = config.get("_instrument_key")
    
    if not client or not instrument_key:
        return None

    # Get indicator lists
    atr_list = calculate_atr(candles_5m, 14)
    vwap_list = calculate_vwap(candles_5m)
    close_prices = [c["close"] for c in candles_5m]
    ema20_list = calculate_ema(close_prices, 20)
    ema50_list = calculate_ema(close_prices, 50) if len(candles_5m) >= 50 else [None] * len(candles_5m)

    idx = len(candles_5m) - 1
    curr = candles_5m[idx]
    prev = candles_5m[idx - 1]

    atr_val = atr_list[-1]
    vwap_val = vwap_list[-1]
    ema20_val = ema20_list[-1]
    ema50_val = ema50_list[-1]

    if atr_val is None or vwap_val is None or ema20_val is None:
        return None

    # 1. Fetch static S/R levels from support/resistance module
    levels = []
    try:
        from strategy_support_resistance import _get_daily_levels, _get_opening_range, _find_pivot_highs, _find_pivot_lows
        today_str = get_ist_now().date().isoformat()
        
        pdh, pdl, pdc = _get_daily_levels(client, instrument_key, today_str)
        orh, orl = _get_opening_range(candles_5m, today_str)
        p_highs_5m = _find_pivot_highs(candles_5m, 2, 2)
        p_lows_5m = _find_pivot_lows(candles_5m, 2, 2)
        p_highs_15m = _find_pivot_highs(candles_15m, 2, 2) if candles_15m else []
        p_lows_15m = _find_pivot_lows(candles_15m, 2, 2) if candles_15m else []

        if pdh: levels.append(("PDH", pdh))
        if pdl: levels.append(("PDL", pdl))
        if pdc: levels.append(("PDC", pdc))
        if orh: levels.append(("ORH", orh))
        if orl: levels.append(("ORL", orl))
        
        for ph in set(p_highs_5m[-5:]):
            levels.append(("SwingHigh_5m", ph))
        for pl in set(p_lows_5m[-5:]):
            levels.append(("SwingLow_5m", pl))
        for ph in set(p_highs_15m[-3:]):
            levels.append(("SwingHigh_15m", ph))
        for pl in set(p_lows_15m[-3:]):
            levels.append(("SwingLow_15m", pl))
    except Exception as e:
        print(f"[CPC Strategy] Error loading support levels: {e}")

    # 2. Check Level Confluence (level is within [low - tolerance, high + tolerance])
    tolerance = atr_val * 0.15
    near_level = False
    level_name = ""
    level_price = 0.0

    # Dynamic levels priority
    if curr["low"] - tolerance <= vwap_val <= curr["high"] + tolerance:
        near_level = True
        level_name = "VWAP"
        level_price = vwap_val
    elif curr["low"] - tolerance <= ema20_val <= curr["high"] + tolerance:
        near_level = True
        level_name = "EMA20"
        level_price = ema20_val
    elif ema50_val is not None and (curr["low"] - tolerance <= ema50_val <= curr["high"] + tolerance):
        near_level = True
        level_name = "EMA50"
        level_price = ema50_val
    else:
        # Check static levels
        for name, price in levels:
            if curr["low"] - tolerance <= price <= curr["high"] + tolerance:
                near_level = True
                level_name = name
                level_price = price
                break

    if not near_level:
        return None

    # 3. Volume Confirmation Gate
    avg_vol = sum(c["volume"] for c in candles_5m[-21:-1]) / 20.0
    vol_multiplier = float(config.get("cpc_volume_multiplier", 1.5))
    if curr["volume"] < avg_vol * vol_multiplier:
        return None

    # 4. Pattern Recognition & Trade Signal Determination
    # We check active patterns on the current candle
    is_bullish = False
    is_bearish = False
    pattern_name = ""

    # Bullish pattern checks
    if detect_morning_star(candles_5m):
        is_bullish = True
        pattern_name = "Morning Star"
    elif detect_bullish_engulfing(candles_5m):
        is_bullish = True
        pattern_name = "Bullish Engulfing"
    elif detect_tweezer_bottoms(candles_5m):
        is_bullish = True
        pattern_name = "Tweezer Bottoms"
    elif detect_piercing_line(candles_5m):
        is_bullish = True
        pattern_name = "Piercing Line"
    elif detect_hammer(candles_5m):
        is_bullish = True
        pattern_name = "Hammer"

    # Bearish pattern checks
    if detect_evening_star(candles_5m):
        is_bearish = True
        pattern_name = "Evening Star"
    elif detect_bearish_engulfing(candles_5m):
        is_bearish = True
        pattern_name = "Bearish Engulfing"
    elif detect_tweezer_tops(candles_5m):
        is_bearish = True
        pattern_name = "Tweezer Tops"
    elif detect_dark_cloud_cover(candles_5m):
        is_bearish = True
        pattern_name = "Dark Cloud Cover"
    elif detect_shooting_star(candles_5m):
        is_bearish = True
        pattern_name = "Shooting Star"

    # If both trigger (rare) or neither triggers, skip
    if (is_bullish and is_bearish) or (not is_bullish and not is_bearish):
        return None

    # 5. Trend Gate Validation
    if is_bullish and htf_trend == "down":
        return None
    if is_bearish and htf_trend == "up":
        return None

    # 6. Risk-Reward Logic and Target Settings
    entry = curr["close"]
    if is_bullish:
        # Stop loss is pattern low - 10% ATR safety buffer
        pattern_low = min(curr["low"], prev["low"])
        if "Morning Star" in pattern_name and len(candles_5m) >= 3:
            pattern_low = min(pattern_low, candles_5m[-3]["low"])
        stop_loss = pattern_low - atr_val * 0.1
        risk = entry - stop_loss
        
        # Guard against zero or overly wide stop
        if risk <= 0 or risk > atr_val * 3:
            stop_loss = entry - atr_val * 1.5
            risk = entry - stop_loss

        return {
            "strategy": f"CandlestickConfluence-Buy",
            "trigger_time": curr["timestamp"],
            "entry_price": round(entry, 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(entry + 1.5 * risk, 2),
            "target_2": round(entry + 2.5 * risk, 2),
            "pattern": pattern_name,
            "level": level_name,
            "level_price": round(level_price, 2),
            "atr": round(atr_val, 2),
            "volume_ratio": round(curr["volume"] / avg_vol, 2) if avg_vol > 0 else 1.0
        }
    else:
        # Stop loss is pattern high + 10% ATR safety buffer
        pattern_high = max(curr["high"], prev["high"])
        if "Evening Star" in pattern_name and len(candles_5m) >= 3:
            pattern_high = max(pattern_high, candles_5m[-3]["high"])
        stop_loss = pattern_high + atr_val * 0.1
        risk = stop_loss - entry
        
        # Guard against zero or overly wide stop
        if risk <= 0 or risk > atr_val * 3:
            stop_loss = entry + atr_val * 1.5
            risk = stop_loss - entry

        return {
            "strategy": f"CandlestickConfluence-Short",
            "trigger_time": curr["timestamp"],
            "entry_price": round(entry, 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(entry - 1.5 * risk, 2),
            "target_2": round(entry - 2.5 * risk, 2),
            "pattern": pattern_name,
            "level": level_name,
            "level_price": round(level_price, 2),
            "atr": round(atr_val, 2),
            "volume_ratio": round(curr["volume"] / avg_vol, 2) if avg_vol > 0 else 1.0
        }
