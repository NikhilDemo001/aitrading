"""
Candlestick Pattern Recognition Module
======================================
Detects common bullish, bearish, and neutral candlestick patterns.
"""

def detect_hammer(candles) -> bool:
    """
    Hammer: Lower wick >= 2x body, upper wick < 0.3x body, real body in upper 1/3 of range.
    Can be green or red, but green is stronger.
    """
    if not candles:
        return False
    c = candles[-1]
    o, h, l, cl = c['open'], c['high'], c['low'], c['close']
    body = abs(cl - o)
    total_range = h - l
    if total_range <= 0:
        return False
    
    body_top = max(o, cl)
    body_bottom = min(o, cl)
    upper_wick = h - body_top
    lower_wick = body_bottom - l
    
    # Body in upper 1/3
    in_upper_third = (body_bottom - l) >= (total_range * 0.6)
    
    return lower_wick >= (2 * body) and upper_wick < (0.3 * body) and in_upper_third


def detect_shooting_star(candles) -> bool:
    """
    Shooting Star: Upper wick >= 2x body, lower wick < 0.3x body, real body in lower 1/3 of range.
    """
    if not candles:
        return False
    c = candles[-1]
    o, h, l, cl = c['open'], c['high'], c['low'], c['close']
    body = abs(cl - o)
    total_range = h - l
    if total_range <= 0:
        return False
    
    body_top = max(o, cl)
    body_bottom = min(o, cl)
    upper_wick = h - body_top
    lower_wick = body_bottom - l
    
    # Body in lower 1/3
    in_lower_third = (h - body_top) >= (total_range * 0.6)
    
    return upper_wick >= (2 * body) and lower_wick < (0.3 * body) and in_lower_third


def detect_bullish_engulfing(candles) -> bool:
    """
    Bullish Engulfing: Current green candle body completely engulfs previous red candle body.
    """
    if len(candles) < 2:
        return False
    prev, curr = candles[-2], candles[-1]
    
    # Prev must be red/neutral, curr must be green
    if prev['close'] > prev['open'] or curr['close'] <= curr['open']:
        return False
        
    prev_body_top = prev['open']
    prev_body_bottom = prev['close']
    curr_body_top = curr['close']
    curr_body_bottom = curr['open']
    
    return curr_body_top > prev_body_top and curr_body_bottom < prev_body_bottom


def detect_bearish_engulfing(candles) -> bool:
    """
    Bearish Engulfing: Current red candle body completely engulfs previous green candle body.
    """
    if len(candles) < 2:
        return False
    prev, curr = candles[-2], candles[-1]
    
    # Prev must be green/neutral, curr must be red
    if prev['close'] < prev['open'] or curr['close'] >= curr['open']:
        return False
        
    prev_body_top = prev['close']
    prev_body_bottom = prev['open']
    curr_body_top = curr['open']
    curr_body_bottom = curr['close']
    
    return curr_body_top > prev_body_top and curr_body_bottom < prev_body_bottom


def detect_doji(candles) -> str | None:
    """
    Doji: Body < 10% of total range.
    Returns: 'gravestone' | 'dragonfly' | 'standard' | None
    """
    if not candles:
        return None
    c = candles[-1]
    o, h, l, cl = c['open'], c['high'], c['low'], c['close']
    body = abs(cl - o)
    total_range = h - l
    if total_range <= 0:
        return None
        
    if body >= (total_range * 0.1):
        return None
        
    body_top = max(o, cl)
    body_bottom = min(o, cl)
    upper_wick = h - body_top
    lower_wick = body_bottom - l
    
    if upper_wick >= (total_range * 0.8) and lower_wick <= (total_range * 0.1):
        return 'gravestone'
    elif lower_wick >= (total_range * 0.8) and upper_wick <= (total_range * 0.1):
        return 'dragonfly'
    return 'standard'


def detect_pin_bar(candles, direction='long') -> bool:
    """
    Pin Bar: Wick is > 66% of total range, body < 33%.
    For 'long', lower wick is long. For 'short', upper wick is long.
    """
    if not candles:
        return False
    c = candles[-1]
    o, h, l, cl = c['open'], c['high'], c['low'], c['close']
    body = abs(cl - o)
    total_range = h - l
    if total_range <= 0:
        return False
        
    if body >= (total_range * 0.33):
        return False
        
    body_top = max(o, cl)
    body_bottom = min(o, cl)
    
    if direction == 'long':
        lower_wick = body_bottom - l
        return lower_wick >= (total_range * 0.66)
    else:
        upper_wick = h - body_top
        return upper_wick >= (total_range * 0.66)


def detect_morning_star(candles) -> bool:
    """
    Morning Star (3-candle):
    1. Large red candle
    2. Small body candle (gap down preferred)
    3. Large green candle closing above midpoint of 1st candle
    """
    if len(candles) < 3:
        return False
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    
    # 1. First must be red
    if c1['close'] >= c1['open']:
        return False
    # 3. Third must be green
    if c3['close'] <= c3['open']:
        return False
        
    c1_body = c1['open'] - c1['close']
    c2_body = abs(c2['close'] - c2['open'])
    c3_body = c3['close'] - c3['open']
    
    # 2. Second must be a star (small body)
    if c2_body >= (c1_body * 0.35):
        return False
        
    # 3. Third closes above midpoint of first
    c1_midpoint = c1['close'] + (c1_body / 2.0)
    return c3['close'] > c1_midpoint


def detect_evening_star(candles) -> bool:
    """
    Evening Star (3-candle):
    1. Large green candle
    2. Small body candle (gap up preferred)
    3. Large red candle closing below midpoint of 1st candle
    """
    if len(candles) < 3:
        return False
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    
    # 1. First must be green
    if c1['close'] <= c1['open']:
        return False
    # 3. Third must be red
    if c3['close'] >= c3['open']:
        return False
        
    c1_body = c1['close'] - c1['open']
    c2_body = abs(c2['close'] - c2['open'])
    c3_body = c1['open'] - c3['close']  # raw difference for comparison
    
    # 2. Second must be a star (small body)
    if c2_body >= (c1_body * 0.35):
        return False
        
    # 3. Third closes below midpoint of first
    c1_midpoint = c1['open'] + (c1_body / 2.0)
    return c3['close'] < c1_midpoint


def detect_marubozu(candles, direction='long') -> bool:
    """
    Marubozu: Body >= 90% of total range (almost no wicks).
    """
    if not candles:
        return False
    c = candles[-1]
    o, h, l, cl = c['open'], c['high'], c['low'], c['close']
    body = abs(cl - o)
    total_range = h - l
    if total_range <= 0:
        return False
        
    if body < (total_range * 0.9):
        return False
        
    if direction == 'long':
        return cl > o
    else:
        return cl < o


def detect_tweezer_bottoms(candles) -> bool:
    """
    Tweezer Bottoms: Two candles with almost identical lows (within 0.05% of price).
    First is red, second is green. Both should have lower wicks.
    """
    if len(candles) < 2:
        return False
    prev, curr = candles[-2], candles[-1]
    if prev['close'] >= prev['open'] or curr['close'] <= curr['open']:
        return False
    
    diff = abs(prev['low'] - curr['low'])
    threshold = prev['low'] * 0.0005
    
    prev_body_bottom = prev['close']
    curr_body_bottom = curr['open']
    has_wicks = (prev_body_bottom - prev['low'] > 0) and (curr_body_bottom - curr['low'] > 0)
    
    return diff <= threshold and has_wicks


def detect_tweezer_tops(candles) -> bool:
    """
    Tweezer Tops: Two candles with almost identical highs (within 0.05% of price).
    First is green, second is red. Both should have upper wicks.
    """
    if len(candles) < 2:
        return False
    prev, curr = candles[-2], candles[-1]
    if prev['close'] <= prev['open'] or curr['close'] >= curr['open']:
        return False
    
    diff = abs(prev['high'] - curr['high'])
    threshold = prev['high'] * 0.0005
    
    prev_body_top = prev['close']
    curr_body_top = curr['open']
    has_wicks = (prev['high'] - prev_body_top > 0) and (curr['high'] - curr_body_top > 0)
    
    return diff <= threshold and has_wicks


def detect_piercing_line(candles) -> bool:
    """
    Piercing Line: Large red candle followed by green candle that opens
    below red's close and closes above the 50% midpoint of the red body.
    """
    if len(candles) < 2:
        return False
    prev, curr = candles[-2], candles[-1]
    if prev['close'] >= prev['open'] or curr['close'] <= curr['open']:
        return False
    if curr['open'] >= prev['close']:
        return False
    
    prev_body = prev['open'] - prev['close']
    prev_midpoint = prev['close'] + (prev_body / 2.0)
    return curr['close'] > prev_midpoint and curr['close'] < prev['open']


def detect_dark_cloud_cover(candles) -> bool:
    """
    Dark Cloud Cover: Large green candle followed by red candle that opens
    above green's close and closes below the 50% midpoint of the green body.
    """
    if len(candles) < 2:
        return False
    prev, curr = candles[-2], candles[-1]
    if prev['close'] <= prev['open'] or curr['close'] >= curr['open']:
        return False
    if curr['open'] <= prev['close']:
        return False
    
    prev_body = prev['close'] - prev['open']
    prev_midpoint = prev['open'] + (prev_body / 2.0)
    return curr['close'] < prev_midpoint and curr['close'] > prev['open']


def detect_inside_bar(candles) -> bool:
    """
    Inside Bar: A candle whose high and low are completely inside the previous candle's range.
    """
    if len(candles) < 2:
        return False
    prev, curr = candles[-2], candles[-1]
    return curr['high'] <= prev['high'] and curr['low'] >= prev['low']


def detect_inverted_hammer(candles) -> bool:
    """
    Inverted Hammer: geometrically identical to Shooting Star (upper wick >= 2x body, lower
    wick < 0.3x body, body in lower 1/3 of range) — the two patterns differ only by the trend
    they appear in (bullish reversal after a decline vs bearish reversal after an advance), not
    by shape. As with detect_hammer/detect_shooting_star, this module tests geometry only; the
    caller (strategy/regime layer) supplies trend context.
    """
    return detect_shooting_star(candles)


def detect_hanging_man(candles) -> bool:
    """
    Hanging Man: geometrically identical to Hammer (lower wick >= 2x body, upper wick < 0.3x
    body, body in upper 1/3 of range) — bearish when it appears after an advance, same shape as
    a bullish Hammer after a decline. See detect_inverted_hammer's note on trend context.
    """
    return detect_hammer(candles)


def detect_spinning_top(candles) -> bool:
    """
    Spinning Top: small real body (10%-35% of range, bigger than a Doji but still indecisive)
    with both an upper AND lower wick present and roughly comparable in length — distinct from
    Hammer/Shooting Star/Pin Bar, where one wick dominates.
    """
    if not candles:
        return False
    c = candles[-1]
    o, h, l, cl = c['open'], c['high'], c['low'], c['close']
    body = abs(cl - o)
    total_range = h - l
    if total_range <= 0:
        return False

    if not (total_range * 0.1 <= body < total_range * 0.35):
        return False

    body_top = max(o, cl)
    body_bottom = min(o, cl)
    upper_wick = h - body_top
    lower_wick = body_bottom - l
    if upper_wick <= 0 or lower_wick <= 0:
        return False

    ratio = upper_wick / lower_wick
    return 0.4 <= ratio <= 2.5


def detect_three_white_soldiers(candles) -> bool:
    """
    Three White Soldiers (3-candle, bullish): three consecutive green candles each closing
    higher than the last, each opening inside the previous candle's real body, with small upper
    wicks — sustained buying pressure rather than a single gap-driven move.
    """
    if len(candles) < 3:
        return False
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    for c in (c1, c2, c3):
        if c['close'] <= c['open']:
            return False
    if not (c2['close'] > c1['close'] and c3['close'] > c2['close']):
        return False
    if not (c1['open'] <= c2['open'] <= c1['close']):
        return False
    if not (c2['open'] <= c3['open'] <= c2['close']):
        return False
    for c in (c1, c2, c3):
        body = c['close'] - c['open']
        upper_wick = c['high'] - c['close']
        if body <= 0 or upper_wick > body * 0.5:
            return False
    return True


def detect_three_black_crows(candles) -> bool:
    """
    Three Black Crows (3-candle, bearish): mirror of Three White Soldiers — three consecutive
    red candles each closing lower than the last, each opening inside the previous candle's
    real body, with small lower wicks.
    """
    if len(candles) < 3:
        return False
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    for c in (c1, c2, c3):
        if c['close'] >= c['open']:
            return False
    if not (c2['close'] < c1['close'] and c3['close'] < c2['close']):
        return False
    if not (c1['close'] <= c2['open'] <= c1['open']):
        return False
    if not (c2['close'] <= c3['open'] <= c2['open']):
        return False
    for c in (c1, c2, c3):
        body = c['open'] - c['close']
        lower_wick = c['close'] - c['low']
        if body <= 0 or lower_wick > body * 0.5:
            return False
    return True


def _clamp_strength(score: float) -> int:
    return int(max(0, min(100, round(score))))


def _wick_dominance_strength(candles, dominant_side: str) -> int:
    """Strength for wick-dominant single-candle patterns (Hammer/Hanging Man/Shooting
    Star/Inverted Hammer/Pin Bar): scales with how far the dominant wick exceeds the 2x-body
    qualifying threshold. Ratio 2.0 (bare minimum) -> ~40; ratio 6.0+ -> 100.
    """
    if not candles:
        return 0
    c = candles[-1]
    o, h, l, cl = c['open'], c['high'], c['low'], c['close']
    body = abs(cl - o) or 0.01
    body_top, body_bottom = max(o, cl), min(o, cl)
    wick = (h - body_top) if dominant_side == 'upper' else (body_bottom - l)
    ratio = wick / body
    return _clamp_strength(40 + (ratio - 2.0) * 15)


def _doji_strength(candles) -> int:
    if not candles:
        return 0
    c = candles[-1]
    o, h, l, cl = c['open'], c['high'], c['low'], c['close']
    total_range = h - l
    if total_range <= 0:
        return 0
    body_frac = abs(cl - o) / total_range
    return _clamp_strength((1 - body_frac / 0.1) * 100)


def _engulfing_strength(candles) -> int:
    if len(candles) < 2:
        return 0
    prev, curr = candles[-2], candles[-1]
    prev_body = abs(prev['close'] - prev['open']) or 0.01
    curr_body = abs(curr['close'] - curr['open'])
    ratio = curr_body / prev_body
    return _clamp_strength(40 + (ratio - 1.0) * 30)


def _star_strength(candles, kind: str) -> int:
    if len(candles) < 3:
        return 0
    c1, c3 = candles[-3], candles[-1]
    if kind == 'morning':
        c1_body = c1['open'] - c1['close']
        midpoint = c1['close'] + c1_body / 2.0
        beyond = c3['close'] - midpoint
    else:
        c1_body = c1['close'] - c1['open']
        midpoint = c1['open'] + c1_body / 2.0
        beyond = midpoint - c3['close']
    c1_body = c1_body or 0.01
    return _clamp_strength((beyond / c1_body) * 100)


def _tweezer_strength(candles, side: str) -> int:
    if len(candles) < 2:
        return 0
    prev, curr = candles[-2], candles[-1]
    key = 'low' if side == 'bottom' else 'high'
    diff = abs(prev[key] - curr[key])
    threshold = prev[key] * 0.0005 or 0.01
    return _clamp_strength((1 - diff / threshold) * 100)


def _piercing_dark_cloud_strength(candles, kind: str) -> int:
    if len(candles) < 2:
        return 0
    prev, curr = candles[-2], candles[-1]
    if kind == 'piercing':
        prev_body = (prev['open'] - prev['close']) or 0.01
        penetration = (curr['close'] - prev['close']) / prev_body
    else:
        prev_body = (prev['close'] - prev['open']) or 0.01
        penetration = (prev['close'] - curr['close']) / prev_body
    return _clamp_strength(((penetration - 0.5) / 0.5) * 100)


def _inside_bar_strength(candles) -> int:
    if len(candles) < 2:
        return 0
    prev, curr = candles[-2], candles[-1]
    prev_range = (prev['high'] - prev['low']) or 0.01
    curr_range = curr['high'] - curr['low']
    return _clamp_strength((1 - curr_range / prev_range) * 100)


def _spinning_top_strength(candles) -> int:
    if not candles:
        return 0
    c = candles[-1]
    o, h, l, cl = c['open'], c['high'], c['low'], c['close']
    body_top, body_bottom = max(o, cl), min(o, cl)
    upper_wick, lower_wick = h - body_top, body_bottom - l
    if upper_wick <= 0 or lower_wick <= 0:
        return 0
    balance = 1 - abs(upper_wick - lower_wick) / max(upper_wick, lower_wick)
    return _clamp_strength(balance * 70 + 30)


def _soldiers_crows_strength(candles, kind: str) -> int:
    if len(candles) < 3:
        return 0
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    scores = []
    for c in (c1, c2, c3):
        if kind == 'soldiers':
            body = (c['close'] - c['open']) or 0.01
            wick = c['high'] - c['close']
        else:
            body = (c['open'] - c['close']) or 0.01
            wick = c['close'] - c['low']
        scores.append(max(0.0, 1 - wick / body))
    return _clamp_strength((sum(scores) / len(scores)) * 100)


def _recent_trend(candles, lookback: int = 5) -> str:
    """Lightweight trend read used only by detect_all_patterns to disambiguate the two
    geometrically-identical pattern pairs (Hammer/Hanging Man, Shooting Star/Inverted Hammer),
    which differ only by whether they follow a decline or an advance."""
    if len(candles) < lookback + 2:
        return 'flat'
    ref_close = candles[-(lookback + 1)]['close']
    pre_close = candles[-2]['close']
    if ref_close <= 0:
        return 'flat'
    change_pct = (pre_close - ref_close) / ref_close
    if change_pct <= -0.003:
        return 'down'
    elif change_pct >= 0.003:
        return 'up'
    return 'flat'


def detect_all_patterns(candles) -> dict:
    """
    Master function to run all detectors. Returns bullish/bearish/neutral name lists (unchanged
    shape for backward compatibility with existing callers) plus an additive `strengths` dict
    (pattern name -> 0-100 score) so trades can carry a numeric confidence alongside the name.
    """
    bullish = []
    bearish = []
    neutral = []
    strengths = {}

    trend = _recent_trend(candles)

    # Hammer/Hanging Man and Shooting Star/Inverted Hammer are the same candle geometry —
    # which name applies (and whether it's bullish or bearish) depends on the preceding trend.
    if detect_hammer(candles):
        if trend == 'up':
            bearish.append("Hanging Man")
            strengths["Hanging Man"] = _wick_dominance_strength(candles, 'lower')
        else:
            bullish.append("Hammer")
            strengths["Hammer"] = _wick_dominance_strength(candles, 'lower')
    if detect_shooting_star(candles):
        if trend == 'down':
            bullish.append("Inverted Hammer")
            strengths["Inverted Hammer"] = _wick_dominance_strength(candles, 'upper')
        else:
            bearish.append("Shooting Star")
            strengths["Shooting Star"] = _wick_dominance_strength(candles, 'upper')

    if detect_spinning_top(candles):
        neutral.append("Spinning Top")
        strengths["Spinning Top"] = _spinning_top_strength(candles)
    if detect_three_white_soldiers(candles):
        bullish.append("Three White Soldiers")
        strengths["Three White Soldiers"] = _soldiers_crows_strength(candles, 'soldiers')
    if detect_three_black_crows(candles):
        bearish.append("Three Black Crows")
        strengths["Three Black Crows"] = _soldiers_crows_strength(candles, 'crows')

    if detect_bullish_engulfing(candles):
        bullish.append("Bullish Engulfing")
        strengths["Bullish Engulfing"] = _engulfing_strength(candles)
    if detect_bearish_engulfing(candles):
        bearish.append("Bearish Engulfing")
        strengths["Bearish Engulfing"] = _engulfing_strength(candles)
        
    doji_type = detect_doji(candles)
    if doji_type:
        doji_strength = _doji_strength(candles)
        if doji_type == 'gravestone':
            bearish.append("Gravestone Doji")
            strengths["Gravestone Doji"] = doji_strength
        elif doji_type == 'dragonfly':
            bullish.append("Dragonfly Doji")
            strengths["Dragonfly Doji"] = doji_strength
        else:
            neutral.append("Standard Doji")
            strengths["Standard Doji"] = doji_strength

    if detect_pin_bar(candles, 'long'):
        bullish.append("Bullish Pin Bar")
        strengths["Bullish Pin Bar"] = _wick_dominance_strength(candles, 'lower')
    if detect_pin_bar(candles, 'short'):
        bearish.append("Bearish Pin Bar")
        strengths["Bearish Pin Bar"] = _wick_dominance_strength(candles, 'upper')

    if detect_morning_star(candles):
        bullish.append("Morning Star")
        strengths["Morning Star"] = _star_strength(candles, 'morning')
    if detect_evening_star(candles):
        bearish.append("Evening Star")
        strengths["Evening Star"] = _star_strength(candles, 'evening')

    if detect_marubozu(candles, 'long'):
        bullish.append("Bullish Marubozu")
        strengths["Bullish Marubozu"] = _clamp_strength(60 + ((abs(candles[-1]['close'] - candles[-1]['open']) / (candles[-1]['high'] - candles[-1]['low'] or 0.01)) - 0.9) * 400)
    if detect_marubozu(candles, 'short'):
        bearish.append("Bearish Marubozu")
        strengths["Bearish Marubozu"] = _clamp_strength(60 + ((abs(candles[-1]['close'] - candles[-1]['open']) / (candles[-1]['high'] - candles[-1]['low'] or 0.01)) - 0.9) * 400)

    if detect_tweezer_bottoms(candles):
        bullish.append("Tweezer Bottoms")
        strengths["Tweezer Bottoms"] = _tweezer_strength(candles, 'bottom')
    if detect_tweezer_tops(candles):
        bearish.append("Tweezer Tops")
        strengths["Tweezer Tops"] = _tweezer_strength(candles, 'top')
    if detect_piercing_line(candles):
        bullish.append("Piercing Line")
        strengths["Piercing Line"] = _piercing_dark_cloud_strength(candles, 'piercing')
    if detect_dark_cloud_cover(candles):
        bearish.append("Dark Cloud Cover")
        strengths["Dark Cloud Cover"] = _piercing_dark_cloud_strength(candles, 'dark_cloud')
    if detect_inside_bar(candles):
        neutral.append("Inside Bar")
        strengths["Inside Bar"] = _inside_bar_strength(candles)

    return {
        'bullish': bullish,
        'bearish': bearish,
        'strengths': strengths,
        'neutral': neutral,
        'strongest_bullish': bullish[0] if bullish else None,
        'strongest_bearish': bearish[0] if bearish else None
    }
