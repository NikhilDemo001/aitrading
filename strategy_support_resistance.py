"""
Advanced Support and Resistance (S/R) Trading Strategy
======================================================
1. Automatically detects PDH, PDL, PDC, Opening Range (09:15-09:30) High/Low, and Swing pivots.
2. Levels are scored based on touch counts, source/timeframe, volume weight, and feedback from past trades.
3. Breakout Strategy: entries on candle close beyond level + high volume + price vs VWAP + Nifty trend.
4. Rejection Strategy: entries on confirmation candle following engulfing or pin-bar rejection off levels.
5. Fake Breakout Protection: rejects low volume, weak body candle, and counter-HTF breakouts.
"""

import datetime
from datetime import timedelta

# Cache for Previous Day levels to avoid hitting rate limits.
# Key: instrument_key, Value: {"date": "YYYY-MM-DD", "pdh": float, "pdl": float, "pdc": float}
_DAILY_LEVELS_CACHE = {}

def get_ist_now():
    """Returns timezone-naive datetime representing IST (India Standard Time)."""
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None) + timedelta(hours=5, minutes=30)

class SRLevel:
    def __init__(self, price, source, timeframe, base_weight):
        self.price = round(float(price), 2)
        self.source = source        # "PDH" | "PDL" | "PDC" | "ORH" | "ORL" | "SwingHigh" | "SwingLow"
        self.timeframe = timeframe  # "1d" | "15m" | "5m"
        self.base_weight = base_weight
        self.score = 0.0

def _get_daily_levels(client, instrument_key, today_str):
    """Fetches and caches the previous day's daily levels."""
    global _DAILY_LEVELS_CACHE
    cached = _DAILY_LEVELS_CACHE.get(instrument_key)
    if cached and cached["date"] == today_str:
        return cached["pdh"], cached["pdl"], cached["pdc"]
    
    try:
        today_dt = datetime.datetime.strptime(today_str, "%Y-%m-%d")
        from_date = (today_dt - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
        to_date = today_str
        
        daily_candles = client.get_historical_candles(instrument_key, "day", from_date, to_date)
        if not daily_candles:
            return None, None, None
            
        # Filter for the last completed daily candle before today
        prev_day_candle = None
        for c in reversed(daily_candles):
            c_date = c["timestamp"][:10]
            if c_date < today_str:
                prev_day_candle = c
                break
                
        if prev_day_candle:
            pdh = prev_day_candle["high"]
            pdl = prev_day_candle["low"]
            pdc = prev_day_candle["close"]
            _DAILY_LEVELS_CACHE[instrument_key] = {
                "date": today_str,
                "pdh": pdh,
                "pdl": pdl,
                "pdc": pdc
            }
            return pdh, pdl, pdc
    except Exception as e:
        print(f"[SR Strategy] Error fetching daily levels for {instrument_key}: {e}")
        
    return None, None, None

def _get_opening_range(candles_5m, today_str):
    """Returns today's 15-minute Opening Range High and Low (09:15 - 09:30)."""
    or_candles = []
    for c in candles_5m:
        if c["timestamp"].startswith(today_str):
            time_part = c["timestamp"][11:16]
            if "09:15" <= time_part < "09:30":
                or_candles.append(c)
    if or_candles:
        or_high = max(c["high"] for c in or_candles)
        or_low = min(c["low"] for c in or_candles)
        return or_high, or_low
    return None, None

def _find_pivot_highs(candles, left=2, right=2):
    """Finds confirmed swing pivot highs."""
    result = []
    limit = len(candles) - right
    for i in range(left, limit):
        h = candles[i]["high"]
        if all(candles[i - j]["high"] < h for j in range(1, left + 1)) and \
           all(candles[i + j]["high"] < h for j in range(1, right + 1)):
            result.append(h)
    return result

def _find_pivot_lows(candles, left=2, right=2):
    """Finds confirmed swing pivot lows."""
    result = []
    limit = len(candles) - right
    for i in range(left, limit):
        lo = candles[i]["low"]
        if all(candles[i - j]["low"] > lo for j in range(1, left + 1)) and \
           all(candles[i + j]["low"] > lo for j in range(1, right + 1)):
            result.append(lo)
    return result

def get_optimized_level_multipliers(trade_history):
    """
    Continuous Optimization: Analyzes trade performance to calculate level multipliers.
    Boosts levels with high win rates; penalizes poor performing ones.
    """
    multipliers = {
        "PDH": 1.0, "PDL": 1.0, "PDC": 1.0,
        "ORH": 1.0, "ORL": 1.0,
        "SwingHigh": 1.0, "SwingLow": 1.0
    }
    sr_trades = [t for t in trade_history if "SupportResistance" in t.get("strategy", "")]
    if len(sr_trades) < 5:
        return multipliers
        
    by_source = {}
    for t in sr_trades:
        src = t.get("trigger_level_source")
        if src in multipliers:
            by_source.setdefault(src, []).append(t)
            
    for src, ts in by_source.items():
        if len(ts) >= 3:
            wins = sum(1 for t in ts if t.get("pnl", 0.0) > 0)
            win_rate = wins / len(ts)
            if win_rate >= 0.60:
                multipliers[src] = 1.3
            elif win_rate >= 0.50:
                multipliers[src] = 1.1
            elif win_rate <= 0.35:
                multipliers[src] = 0.7
            elif win_rate <= 0.45:
                multipliers[src] = 0.9
    return multipliers

def _score_levels(levels, candles_5m, atr_val, multipliers):
    """Calculates level strength score based on touches, volume, and performance."""
    avg_vol_20 = sum(c["volume"] for c in candles_5m[-21:-1]) / 20 if len(candles_5m) >= 22 else 1.0
    scored_levels = []
    
    for level in levels:
        price = level.price
        source = level.source
        
        # Adaptive tolerance: 10% of ATR or 0.1% of Price
        tolerance = max(0.001 * price, 0.1 * atr_val) if atr_val else 0.001 * price
        
        # Detect all touches in the last 100 5m candles
        touches = []
        for idx, c in enumerate(candles_5m[-100:]):
            if c["low"] <= price + tolerance and c["high"] >= price - tolerance:
                touches.append((idx, c["volume"]))
                
        # Cluster touches within 3 bars of each other to count as 1 touch event
        touch_events = []
        current_event = []
        for t in touches:
            if not current_event:
                current_event.append(t)
            elif t[0] - current_event[-1][0] <= 3:
                current_event.append(t)
            else:
                touch_events.append(current_event)
                current_event = [t]
        if current_event:
            touch_events.append(current_event)
            
        touch_count = len(touch_events)
        
        # Calculate volume bonus if any candle in a touch event had volume >= 1.5x average
        volume_bonus = 0.0
        for event in touch_events:
            max_event_vol = max(bar[1] for bar in event)
            if max_event_vol >= 1.5 * avg_vol_20:
                volume_bonus += 0.5
                
        # Apply optimizer multiplier
        mult = multipliers.get(source, 1.0)
        
        level.score = round(level.base_weight * (1.0 + touch_count * 0.4 + volume_bonus) * mult, 2)
        scored_levels.append(level)
        
    return scored_levels

def check_support_resistance_strategy(candles_5m, candles_15m=None, config=None, htf_trend="neutral"):
    """
    Evaluates support and resistance breakouts and rejections.
    Returns signal dict if triggered, otherwise None.
    """
    from strategies import calculate_atr, calculate_vwap
    
    if not candles_5m or len(candles_5m) < 22:
        return None
        
    config = config or {}
    client = config.get("_client")
    if not client:
        return None
        
    instrument_key = config.get("_instrument_key")
    if not instrument_key:
        return None
        
    today_str = get_ist_now().date().isoformat()
    trade_history = config.get("_trade_history", [])
    
    # 1. Fetch Daily Levels (PDH, PDL, PDC)
    pdh, pdl, pdc = _get_daily_levels(client, instrument_key, today_str)
    
    # 2. Fetch Opening Range Levels (ORH, ORL)
    orh, orl = _get_opening_range(candles_5m, today_str)
    
    # 3. Detect Swing pivots (5m & 15m)
    p_highs_5m = _find_pivot_highs(candles_5m, 2, 2)
    p_lows_5m = _find_pivot_lows(candles_5m, 2, 2)
    p_highs_15m = _find_pivot_highs(candles_15m, 2, 2) if candles_15m else []
    p_lows_15m = _find_pivot_lows(candles_15m, 2, 2) if candles_15m else []
    
    # 4. Construct S/R Levels List
    levels = []
    if pdh: levels.append(SRLevel(pdh, "PDH", "1d", 3.0))
    if pdl: levels.append(SRLevel(pdl, "PDL", "1d", 3.0))
    if pdc: levels.append(SRLevel(pdc, "PDC", "1d", 2.0))
    if orh: levels.append(SRLevel(orh, "ORH", "15m", 2.5))
    if orl: levels.append(SRLevel(orl, "ORL", "15m", 2.5))
    
    for ph in set(p_highs_5m[-10:]):
        levels.append(SRLevel(ph, "SwingHigh", "5m", 1.0))
    for pl in set(p_lows_5m[-10:]):
        levels.append(SRLevel(pl, "SwingLow", "5m", 1.0))
    for ph in set(p_highs_15m[-5:]):
        levels.append(SRLevel(ph, "SwingHigh", "15m", 1.5))
    for pl in set(p_lows_15m[-5:]):
        levels.append(SRLevel(pl, "SwingLow", "15m", 1.5))
        
    # Get indicators
    atr = calculate_atr(candles_5m, 14)
    vwap = calculate_vwap(candles_5m)
    atr_val = atr[-1]
    vwap_val = vwap[-1]
    
    if atr_val is None or vwap_val is None:
        return None
        
    # 5. Score S/R Levels
    multipliers = get_optimized_level_multipliers(trade_history)
    scored_levels = _score_levels(levels, candles_5m, atr_val, multipliers)
    
    # Filter for significant levels (score >= 3.0)
    sig_levels = [l for l in scored_levels if l.score >= 3.0]
    if not sig_levels:
        return None
        
    curr = candles_5m[-1]
    prev = candles_5m[-2]
    prev_2 = candles_5m[-3]
    avg_vol_20 = sum(c["volume"] for c in candles_5m[-21:-1]) / 20
    
    # Dynamically determine resistance vs support based on the previous close
    resistances = [l for l in sig_levels if l.price > prev["close"]]
    supports = [l for l in sig_levels if l.price < prev["close"]]
    
    tolerance = max(0.001 * curr["close"], 0.1 * atr_val)
    
    # ─────────────────────────────────────────────────────────────────────────
    # Breakout Strategy
    # ─────────────────────────────────────────────────────────────────────────
    
    # Long Breakout (Buy)
    for res in resistances:
        # Enter only after candle close above resistance
        breakout = curr["close"] > res.price and prev["close"] <= res.price
        if breakout:
            # Volume must be >= 1.5x average volume
            vol_ok = curr["volume"] >= 1.5 * avg_vol_20 and avg_vol_20 > 0
            # Price must be above VWAP
            vwap_ok = curr["close"] > vwap_val
            # Confirm trend with Higher Timeframe
            htf_ok = htf_trend != "down"
            # Reject weak candle body breakouts (Fake Breakout Protection)
            body_ok = (curr["close"] - curr["open"]) >= 0.5 * (curr["high"] - curr["low"])
            wick_ok = (curr["high"] - curr["close"]) <= 0.3 * (curr["high"] - curr["low"])
            
            if vol_ok and vwap_ok and htf_ok and body_ok and wick_ok:
                stop_loss = max(res.price - atr_val * 1.5, curr["low"] - atr_val * 0.3)
                risk = curr["close"] - stop_loss
                if risk > 0.05:
                    return {
                        "strategy": "SupportResistance-Breakout-Buy",
                        "trigger_time": curr["timestamp"],
                        "entry_price": round(curr["close"], 2),
                        "stop_loss": round(stop_loss, 2),
                        "target_1": round(curr["close"] + 1.5 * risk, 2),
                        "target_2": round(curr["close"] + 2.5 * risk, 2),
                        "trigger_level_source": res.source,
                        "trigger_level_price": res.price,
                        "trigger_level_score": res.score,
                        "atr": round(atr_val, 2),
                        "vwap": round(vwap_val, 2)
                    }
                    
    # Short Breakout (Sell)
    for sup in supports:
        # Enter only after candle close below support
        breakdown = curr["close"] < sup.price and prev["close"] >= sup.price
        if breakdown:
            vol_ok = curr["volume"] >= 1.5 * avg_vol_20 and avg_vol_20 > 0
            vwap_ok = curr["close"] < vwap_val
            htf_ok = htf_trend != "up"
            # Fake Breakout Protection
            body_ok = (curr["open"] - curr["close"]) >= 0.5 * (curr["high"] - curr["low"])
            wick_ok = (curr["close"] - curr["low"]) <= 0.3 * (curr["high"] - curr["low"])
            
            if vol_ok and vwap_ok and htf_ok and body_ok and wick_ok:
                stop_loss = min(sup.price + atr_val * 1.5, curr["high"] + atr_val * 0.3)
                risk = stop_loss - curr["close"]
                if risk > 0.05:
                    return {
                        "strategy": "SupportResistance-Breakout-Short",
                        "trigger_time": curr["timestamp"],
                        "entry_price": round(curr["close"], 2),
                        "stop_loss": round(stop_loss, 2),
                        "target_1": round(curr["close"] - 1.5 * risk, 2),
                        "target_2": round(curr["close"] - 2.5 * risk, 2),
                        "trigger_level_source": sup.source,
                        "trigger_level_price": sup.price,
                        "trigger_level_score": sup.score,
                        "atr": round(atr_val, 2),
                        "vwap": round(vwap_val, 2)
                    }
                    
    # ─────────────────────────────────────────────────────────────────────────
    # Rejection Strategy (evaluated on confirmation candle close)
    # ─────────────────────────────────────────────────────────────────────────
    
    # Long Rejection (Buy)
    for sup in supports:
        # We check the signal candle (prev = candles_5m[-2]) near level
        near_level = prev["low"] <= sup.price + tolerance
        
        # Bullish Rejection wick: lower wick is >= 60% of candle, body is <= 40%
        prev_range = max(prev["high"] - prev["low"], 0.01)
        prev_body = abs(prev["close"] - prev["open"])
        lower_wick = min(prev["open"], prev["close"]) - prev["low"]
        is_pinbar = lower_wick >= 0.6 * prev_range and prev_body <= 0.4 * prev_range and prev_range >= 0.5 * atr_val
        
        # Bullish Engulfing near support
        is_engulfing = prev_2["close"] < prev_2["open"] and prev["close"] > prev["open"] and \
                       prev["close"] >= prev_2["open"] and prev["open"] <= prev_2["close"] and \
                       min(prev_2["low"], prev["low"]) <= sup.price + tolerance
                       
        if near_level and (is_pinbar or is_engulfing):
            # Check confirmation candle (curr = candles_5m[-1])
            # Must close bullish and close higher than previous close
            confirm_ok = curr["close"] > curr["open"] and curr["close"] > prev["close"]
            htf_ok = htf_trend != "down"
            
            if confirm_ok and htf_ok:
                stop_loss = min(prev["low"], curr["low"]) - atr_val * 0.2
                risk = curr["close"] - stop_loss
                if risk > 0.05:
                    return {
                        "strategy": "SupportResistance-Rejection-Buy",
                        "trigger_time": curr["timestamp"],
                        "entry_price": round(curr["close"], 2),
                        "stop_loss": round(stop_loss, 2),
                        "target_1": round(curr["close"] + 1.5 * risk, 2),
                        "target_2": round(curr["close"] + 2.5 * risk, 2),
                        "trigger_level_source": sup.source,
                        "trigger_level_price": sup.price,
                        "trigger_level_score": sup.score,
                        "atr": round(atr_val, 2),
                        "vwap": round(vwap_val, 2)
                    }
                    
    # Short Rejection (Short)
    for res in resistances:
        near_level = prev["high"] >= res.price - tolerance
        
        # Bearish Rejection wick: upper wick is >= 60% of candle, body is <= 40%
        prev_range = max(prev["high"] - prev["low"], 0.01)
        prev_body = abs(prev["close"] - prev["open"])
        upper_wick = prev["high"] - max(prev["open"], prev["close"])
        is_pinbar = upper_wick >= 0.6 * prev_range and prev_body <= 0.4 * prev_range and prev_range >= 0.5 * atr_val
        
        # Bearish Engulfing near resistance
        is_engulfing = prev_2["close"] > prev_2["open"] and prev["close"] < prev["open"] and \
                       prev["close"] <= prev_2["open"] and prev["open"] >= prev_2["close"] and \
                       max(prev_2["high"], prev["high"]) >= res.price - tolerance
                       
        if near_level and (is_pinbar or is_engulfing):
            # Check confirmation candle (curr = candles_5m[-1])
            confirm_ok = curr["close"] < curr["open"] and curr["close"] < prev["close"]
            htf_ok = htf_trend != "up"
            
            if confirm_ok and htf_ok:
                stop_loss = max(prev["high"], curr["high"]) + atr_val * 0.2
                risk = stop_loss - curr["close"]
                if risk > 0.05:
                    return {
                        "strategy": "SupportResistance-Rejection-Short",
                        "trigger_time": curr["timestamp"],
                        "entry_price": round(curr["close"], 2),
                        "stop_loss": round(stop_loss, 2),
                        "target_1": round(curr["close"] - 1.5 * risk, 2),
                        "target_2": round(curr["close"] - 2.5 * risk, 2),
                        "trigger_level_source": res.source,
                        "trigger_level_price": res.price,
                        "trigger_level_score": res.score,
                        "atr": round(atr_val, 2),
                        "vwap": round(vwap_val, 2)
                    }
                    
    return None
