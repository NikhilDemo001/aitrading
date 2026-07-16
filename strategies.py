# ─────────────────────────────────────────────────────────────────────────────
# Technical Indicators
# ─────────────────────────────────────────────────────────────────────────────

def calculate_ema(prices, period=20):
    """Exponential Moving Average."""
    if len(prices) < period:
        return [None] * len(prices)
    ema = [None] * len(prices)
    sma = sum(prices[:period]) / period
    ema[period - 1] = sma
    multiplier = 2.0 / (period + 1)
    for i in range(period, len(prices)):
        ema[i] = (prices[i] - ema[i - 1]) * multiplier + ema[i - 1]
    return ema


def calculate_sma(prices, period):
    """Simple Moving Average."""
    if len(prices) < period:
        return [None] * len(prices)
    sma = [None] * len(prices)
    for i in range(period - 1, len(prices)):
        sma[i] = sum(prices[i - period + 1 : i + 1]) / period
    return sma


def calculate_vwap(candles, intraday_only=True):
    """
    Volume Weighted Average Price.

    Args:
        candles: list of OHLCV dicts (ascending order)
        intraday_only: if True (default), only accumulates from today's 09:15 candle
                       onwards. This ensures VWAP resets each session as intended.
                       Pass False only for multi-day research backtests.

    Returns list of VWAP values aligned to candles list. Indices before today's
    session start are filled with None so callers must guard with ``is not None``.
    """
    if not candles:
        return []

    # ── Determine where today's session begins ────────────────────────────────
    today_start_idx = 0
    if intraday_only:
        # Derive today's date from the *last* candle's ISO timestamp (YYYY-MM-DD …)
        last_ts = candles[-1].get('timestamp', '')
        today_str = last_ts[:10] if last_ts else ''

        if today_str:
            # Walk forward to find the first candle of today at or after 09:15
            for i, c in enumerate(candles):
                ts = c.get('timestamp', '')
                if ts[:10] == today_str and ts[11:16] >= '09:15':
                    today_start_idx = i
                    break
            # If the loop completes without a break every candle pre-dates today;
            # default to 0 (accumulate from the start of the list)

    vwap = [None] * len(candles)
    cum_vp = 0.0
    cum_vol = 0.0

    for i in range(len(candles)):
        if i < today_start_idx:
            # Before today's session — VWAP is undefined; leave as None
            continue
        c = candles[i]
        tp = (c['high'] + c['low'] + c['close']) / 3.0
        cum_vp += tp * c['volume']
        cum_vol += c['volume']
        vwap[i] = cum_vp / cum_vol if cum_vol > 0 else tp

    return vwap


def calculate_atr(candles, period=14):
    """Average True Range — measures volatility for position sizing and stops."""
    if len(candles) < period + 1:
        return [None] * len(candles)
    tr_list = [None]
    for i in range(1, len(candles)):
        prev_close = candles[i - 1]["close"]
        c = candles[i]
        tr = max(c["high"] - c["low"], abs(c["high"] - prev_close), abs(c["low"] - prev_close))
        tr_list.append(tr)
    atr = [None] * len(candles)
    initial = [t for t in tr_list[1 : period + 1] if t is not None]
    if len(initial) < period:
        return atr
    atr[period] = sum(initial) / period
    for i in range(period + 1, len(candles)):
        if tr_list[i] is not None and atr[i - 1] is not None:
            atr[i] = atr[i - 1] + (tr_list[i] - atr[i - 1]) / period
    return atr


def calculate_rsi(prices, period=14):
    """Relative Strength Index using Wilder smoothing."""
    if len(prices) < period + 1:
        return [None] * len(prices)
    rsi = [None] * len(prices)
    gains = [max(prices[i] - prices[i - 1], 0) for i in range(1, period + 1)]
    losses = [max(prices[i - 1] - prices[i], 0) for i in range(1, period + 1)]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    rsi[period] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(prices)):
        gain = max(prices[i] - prices[i - 1], 0)
        loss = max(prices[i - 1] - prices[i], 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rsi[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return rsi


def calculate_bollinger_bands(prices, period=20, std_multiplier=2.0):
    """Returns (upper, middle, lower) band lists."""
    if len(prices) < period:
        nones = [None] * len(prices)
        return nones[:], nones[:], nones[:]
    upper = [None] * len(prices)
    middle = [None] * len(prices)
    lower = [None] * len(prices)
    for i in range(period - 1, len(prices)):
        window = prices[i - period + 1 : i + 1]
        sma = sum(window) / period
        std = (sum((p - sma) ** 2 for p in window) / period) ** 0.5
        upper[i] = sma + std_multiplier * std
        middle[i] = sma
        lower[i] = sma - std_multiplier * std
    return upper, middle, lower


def calculate_adx(candles, period=14):
    """
    Average Directional Index using Wilder smoothing.
    ADX > 25 = trending, 15-25 = weak trend, < 15 = ranging/choppy.
    """
    if len(candles) < period * 2 + 1:
        return [None] * len(candles)

    plus_dm_raw = [None]
    minus_dm_raw = [None]
    tr_raw = [None]

    for i in range(1, len(candles)):
        curr, prev = candles[i], candles[i - 1]
        up = curr["high"] - prev["high"]
        down = prev["low"] - curr["low"]
        plus_dm_raw.append(up if up > down and up > 0 else 0)
        minus_dm_raw.append(down if down > up and down > 0 else 0)
        tr_raw.append(max(
            curr["high"] - curr["low"],
            abs(curr["high"] - prev["close"]),
            abs(curr["low"] - prev["close"])
        ))

    def wilder(vals, p):
        out = [None] * len(vals)
        first = next((i for i, v in enumerate(vals) if v is not None), None)
        if first is None or first + p - 1 >= len(vals):
            return out
        valid_start = first
        out[valid_start + p - 1] = sum(vals[valid_start : valid_start + p])
        for i in range(valid_start + p, len(vals)):
            if vals[i] is not None and out[i - 1] is not None:
                out[i] = out[i - 1] - out[i - 1] / p + vals[i]
        return out

    s_tr = wilder(tr_raw, period)
    s_pdm = wilder(plus_dm_raw, period)
    s_mdm = wilder(minus_dm_raw, period)

    dx = [None] * len(candles)
    for i in range(len(candles)):
        if s_tr[i] and s_tr[i] > 0 and s_pdm[i] is not None and s_mdm[i] is not None:
            pdi = 100 * s_pdm[i] / s_tr[i]
            mdi = 100 * s_mdm[i] / s_tr[i]
            di_sum = pdi + mdi
            dx[i] = 100 * abs(pdi - mdi) / di_sum if di_sum > 0 else 0

    adx_sum = wilder(dx, period)
    return [v / period if v is not None else None for v in adx_sum]


# ─────────────────────────────────────────────────────────────────────────────
# Market Regime Detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_market_regime(candles, htf_candles=None):
    """
    Returns one of: 'trending_up', 'trending_down', 'ranging', 'choppy', 'unknown'.
    Uses ADX for strength, EMA alignment for direction.
    htf_candles (e.g. 15-min) optionally overrides direction bias.
    """
    if len(candles) < 30:
        return "unknown"

    close_prices = [c["close"] for c in candles]
    ema_20 = calculate_ema(close_prices, 20)
    ema_50 = calculate_ema(close_prices, 50) if len(candles) >= 52 else [None] * len(candles)
    adx = calculate_adx(candles, 14)

    latest_close = close_prices[-1]
    e20 = ema_20[-1]
    e50 = ema_50[-1]
    adx_val = adx[-1]

    # HTF trend bias
    htf_trend = "neutral"
    if htf_candles and len(htf_candles) >= 22:
        htf_close = [c["close"] for c in htf_candles]
        htf_ema = calculate_ema(htf_close, 20)
        if htf_ema[-1] is not None:
            htf_trend = "up" if htf_close[-1] > htf_ema[-1] * 1.001 else "down" if htf_close[-1] < htf_ema[-1] * 0.999 else "neutral"

    if adx_val is None:
        if e20 is not None:
            if latest_close > e20 * 1.002:
                return "trending_up" if htf_trend != "down" else "ranging"
            elif latest_close < e20 * 0.998:
                return "trending_down" if htf_trend != "up" else "ranging"
        return "ranging"

    if adx_val >= 25:
        bullish = (e20 is not None and latest_close > e20) or (e50 is not None and e20 is not None and e20 > e50)
        if htf_trend == "up" or (htf_trend == "neutral" and bullish):
            return "trending_up"
        elif htf_trend == "down" or (htf_trend == "neutral" and not bullish):
            return "trending_down"
        return "trending_up" if bullish else "trending_down"
    elif adx_val >= 15:
        return "ranging"
    else:
        return "choppy"


def get_htf_trend(htf_candles):
    """Quick trend direction from higher timeframe candles. Returns 'up', 'down', or 'neutral'."""
    if not htf_candles or len(htf_candles) < 10:
        return "neutral"
    close = [c["close"] for c in htf_candles]
    ema = calculate_ema(close, 9)
    if ema[-1] is None:
        return "neutral"
    if close[-1] > ema[-1] * 1.001:
        return "up"
    elif close[-1] < ema[-1] * 0.999:
        return "down"
    return "neutral"


# ─────────────────────────────────────────────────────────────────────────────
# Strategies
# ─────────────────────────────────────────────────────────────────────────────

def check_orb_strategy(candles, interval_minutes=5, range_duration_minutes=15, htf_trend="neutral"):
    """
    Opening Range Breakout.
    First 3 candles (15 min) define the range.
    Breakout above range_high = Buy; below range_low = Short.
    EMA20 confirms direction. ATR-based stops.
    """
    num_range_candles = range_duration_minutes // interval_minutes
    if len(candles) < num_range_candles + 3:
        return None

    range_high = max(c["high"] for c in candles[:num_range_candles])
    range_low = min(c["low"] for c in candles[:num_range_candles])

    # A noise-level opening range (< 0.1% of price) has no meaningful breakout levels —
    # and the ATR-based buffer below can be equally tiny in a flat open. Skip outright.
    if (range_high - range_low) < ((range_high + range_low) / 2) * 0.001:
        return None

    close_prices = [c["close"] for c in candles]
    ema_20 = calculate_ema(close_prices, 20)
    atr = calculate_atr(candles, 14)

    # Only evaluate the most recent candle — acting on a historical breakout is stale
    idx = len(candles) - 1
    if idx < num_range_candles:
        return None
    curr = candles[idx]
    prev = candles[idx - 1]
    ema_val = ema_20[idx]
    atr_val = atr[idx]
    if ema_val is None or atr_val is None:
        return None

    # Require above-average volume AND minimum breakout distance (0.15× ATR above range)
    avg_vol = sum(c["volume"] for c in candles[-21:-1]) / 20 if len(candles) >= 22 else 0
    min_volume = avg_vol * 1.3 if avg_vol > 0 else 1

    # Buy breakout
    if (htf_trend != "down" and
            prev["close"] <= range_high and
            curr["close"] > range_high + atr_val * 0.15 and   # decisive breakout, not a tick
            curr["close"] > ema_val and
            curr["volume"] >= min_volume):
        stop_loss = max(range_high - atr_val * 1.0, range_low)
        risk = curr["close"] - stop_loss
        if risk <= 0:
            stop_loss = curr["close"] - atr_val * 0.8
            risk = curr["close"] - stop_loss
        return {
            "strategy": "ORB-Buy",
            "trigger_time": curr["timestamp"],
            "entry_price": round(curr["close"], 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(curr["close"] + 1.5 * risk, 2),
            "target_2": round(curr["close"] + 2.5 * risk, 2),
            "range_high": round(range_high, 2),
            "range_low": round(range_low, 2),
            "atr": round(atr_val, 2),
        }

    # Short breakout
    if (htf_trend != "up" and
            prev["close"] >= range_low and
            curr["close"] < range_low - atr_val * 0.15 and    # decisive breakdown
            curr["close"] < ema_val and
            curr["volume"] >= min_volume):
        stop_loss = min(range_low + atr_val * 1.0, range_high)
        risk = stop_loss - curr["close"]
        if risk <= 0:
            stop_loss = curr["close"] + atr_val * 0.8
            risk = stop_loss - curr["close"]
        return {
            "strategy": "ORB-Short",
            "trigger_time": curr["timestamp"],
            "entry_price": round(curr["close"], 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(curr["close"] - 1.5 * risk, 2),
            "target_2": round(curr["close"] - 2.5 * risk, 2),
            "range_high": round(range_high, 2),
            "range_low": round(range_low, 2),
            "atr": round(atr_val, 2),
        }
    return None


def check_vwap_pullback_strategy(candles, htf_trend="neutral"):
    """
    VWAP + 9 EMA Pullback.
    Uptrend: price dips to 9 EMA (staying above VWAP), next candle reversal above EMA.
    Downtrend: mirror logic.
    """
    if len(candles) < 15:
        return None

    vwap_list = calculate_vwap(candles)
    close_prices = [c["close"] for c in candles]
    ema_9 = calculate_ema(close_prices, 9)
    atr = calculate_atr(candles, 14)

    # Only evaluate the most recent candle — historical pullback setups are stale
    i = len(candles) - 1
    if i < 11:
        return None
    curr, prev = candles[i], candles[i - 1]
    vc, vp = vwap_list[i], vwap_list[i - 1]
    ec, ep = ema_9[i], ema_9[i - 1]
    atr_val = atr[i]
    # Guard against None VWAP values (pre-session indices from intraday_only mode)
    if ec is None or ep is None or atr_val is None or vc is None or vp is None:
        return None

    # Long pullback
    if (htf_trend != "down" and
            prev["close"] > vp and
            prev["low"] <= ep and prev["low"] > vp and
            curr["close"] > curr["open"] and curr["close"] > ec and curr["close"] > vc):
        entry = curr["close"]
        stop_loss = min(prev["low"], vc) - atr_val * 0.3
        risk = entry - stop_loss
        if risk > 0:
            return {
                "strategy": "VWAP-Pullback-Buy",
                "trigger_time": curr["timestamp"],
                "entry_price": round(entry, 2),
                "stop_loss": round(stop_loss, 2),
                "target_1": round(entry + 1.5 * risk, 2),
                "target_2": round(entry + 2.5 * risk, 2),
                "vwap": round(vc, 2),
                "ema_9": round(ec, 2),
                "atr": round(atr_val, 2),
            }

    # Short pullback
    if (htf_trend != "up" and
            prev["close"] < vp and
            prev["high"] >= ep and prev["high"] < vp and
            curr["close"] < curr["open"] and curr["close"] < ec and curr["close"] < vc):
        entry = curr["close"]
        stop_loss = max(prev["high"], vc) + atr_val * 0.3
        risk = stop_loss - entry
        if risk > 0:
            return {
                "strategy": "VWAP-Pullback-Short",
                "trigger_time": curr["timestamp"],
                "entry_price": round(entry, 2),
                "stop_loss": round(stop_loss, 2),
                "target_1": round(entry - 1.5 * risk, 2),
                "target_2": round(entry - 2.5 * risk, 2),
                "vwap": round(vc, 2),
                "ema_9": round(ec, 2),
                "atr": round(atr_val, 2),
            }
    return None


def check_momentum_breakout_strategy(candles, htf_trend="neutral"):
    """
    Momentum Breakout: new 20-bar price high/low with volume surge (1.5×) and RSI momentum.
    Only fires when price and RSI agree with the breakout direction.
    """
    if len(candles) < 25:
        return None

    close_prices = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    ema_20 = calculate_ema(close_prices, 20)
    rsi_14 = calculate_rsi(close_prices, 14)
    vwap_list = calculate_vwap(candles)
    atr = calculate_atr(candles, 14)

    idx = len(candles) - 1
    curr, prev = candles[idx], candles[idx - 1]

    if ema_20[idx] is None or rsi_14[idx] is None or atr[idx] is None:
        return None

    lookback = candles[-22:-1]
    lookback_high = max(c["high"] for c in lookback)
    lookback_low = min(c["low"] for c in lookback)
    avg_vol = sum(volumes[-21:-1]) / 20
    atr_val = atr[idx]
    # Raised threshold to 2.0× — real momentum needs real volume
    vol_surge = curr["volume"] > avg_vol * 2.0 and avg_vol > 0

    # Long momentum — also require a valid (non-None) VWAP value for this bar
    if (htf_trend != "down" and
            curr["high"] > lookback_high and vol_surge and
            55 < rsi_14[idx] < 80 and
            curr["close"] > ema_20[idx] and
            vwap_list[idx] is not None and curr["close"] > vwap_list[idx]):
        entry = curr["close"]
        stop_loss = max(curr["low"] - atr_val * 0.5, prev["low"])
        risk = entry - stop_loss
        if risk <= 0:
            return None
        return {
            "strategy": "Momentum-Buy",
            "trigger_time": curr["timestamp"],
            "entry_price": round(entry, 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(entry + 2.0 * risk, 2),
            "target_2": round(entry + 3.0 * risk, 2),
            "rsi": round(rsi_14[idx], 1),
            "volume_ratio": round(curr["volume"] / avg_vol, 2) if avg_vol > 0 else 0,
            "atr": round(atr_val, 2),
        }

    # Short momentum — also require a valid (non-None) VWAP value for this bar
    if (htf_trend != "up" and
            curr["low"] < lookback_low and vol_surge and
            20 < rsi_14[idx] < 45 and
            curr["close"] < ema_20[idx] and
            vwap_list[idx] is not None and curr["close"] < vwap_list[idx]):
        entry = curr["close"]
        stop_loss = min(curr["high"] + atr_val * 0.5, prev["high"])
        risk = stop_loss - entry
        if risk <= 0:
            return None
        return {
            "strategy": "Momentum-Short",
            "trigger_time": curr["timestamp"],
            "entry_price": round(entry, 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(entry - 2.0 * risk, 2),
            "target_2": round(entry - 3.0 * risk, 2),
            "rsi": round(rsi_14[idx], 1),
            "volume_ratio": round(curr["volume"] / avg_vol, 2) if avg_vol > 0 else 0,
            "atr": round(atr_val, 2),
        }
    return None


def check_mean_reversion_strategy(candles):
    """
    Bollinger Band + RSI mean reversion.
    Works only in narrow BB (< 2.5% width) = ranging market.
    Entry when price bounces off BB extreme with RSI confirmation.
    """
    if len(candles) < 25:
        return None

    close_prices = [c["close"] for c in candles]
    upper_bb, mid_bb, lower_bb = calculate_bollinger_bands(close_prices, 20, 2.0)
    rsi_14 = calculate_rsi(close_prices, 14)
    atr = calculate_atr(candles, 14)

    idx = len(candles) - 1
    curr, prev = candles[idx], candles[idx - 1]

    if any(v is None for v in [upper_bb[idx], lower_bb[idx], mid_bb[idx], rsi_14[idx], atr[idx]]):
        return None
    if upper_bb[idx - 1] is None or lower_bb[idx - 1] is None or rsi_14[idx - 1] is None:
        return None

    bb_width_pct = (upper_bb[idx] - lower_bb[idx]) / mid_bb[idx] if mid_bb[idx] > 0 else 1.0
    if bb_width_pct > 0.025:  # Too wide — trending, skip mean reversion
        return None

    atr_val = atr[idx]

    # Long: previous candle touched lower BB with RSI truly oversold, current candle reversal
    # Tighter RSI threshold (30 not 35) = fewer but much higher-quality entries
    if (prev["low"] <= lower_bb[idx - 1] and
            rsi_14[idx - 1] < 30 and
            curr["close"] > curr["open"] and curr["close"] > prev["close"] and
            curr["close"] - curr["open"] > (curr["high"] - curr["low"]) * 0.5):  # strong reversal body
        entry = curr["close"]
        stop_loss = min(prev["low"], curr["low"]) - atr_val * 0.3
        risk = entry - stop_loss
        if risk <= 0 or risk > atr_val * 3:
            return None
        return {
            "strategy": "MeanReversion-Buy",
            "trigger_time": curr["timestamp"],
            "entry_price": round(entry, 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(mid_bb[idx], 2),
            "target_2": round(upper_bb[idx], 2),
            "rsi": round(rsi_14[idx - 1], 1),
            "lower_bb": round(lower_bb[idx], 2),
            "atr": round(atr_val, 2),
        }

    # Short: previous candle touched upper BB with RSI truly overbought, current candle reversal
    if (prev["high"] >= upper_bb[idx - 1] and
            rsi_14[idx - 1] > 70 and
            curr["close"] < curr["open"] and curr["close"] < prev["close"] and
            curr["open"] - curr["close"] > (curr["high"] - curr["low"]) * 0.5):  # strong reversal body
        entry = curr["close"]
        stop_loss = max(prev["high"], curr["high"]) + atr_val * 0.3
        risk = stop_loss - entry
        if risk <= 0 or risk > atr_val * 3:
            return None
        return {
            "strategy": "MeanReversion-Short",
            "trigger_time": curr["timestamp"],
            "entry_price": round(entry, 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(mid_bb[idx], 2),
            "target_2": round(lower_bb[idx], 2),
            "rsi": round(rsi_14[idx - 1], 1),
            "upper_bb": round(upper_bb[idx], 2),
            "atr": round(atr_val, 2),
        }
    return None


def check_trend_following_strategy(candles, htf_trend="neutral"):
    """
    EMA-stack Trend Following: EMA9 > EMA20 (bullish stack).
    Entry on pullback to EMA20 with reversal candle.
    ADX must confirm trend strength (> 20).
    Reduced from 55 to 25 candles — usable from ~11:30am onwards.
    """
    if len(candles) < 25:
        return None

    close_prices = [c["close"] for c in candles]
    ema_9 = calculate_ema(close_prices, 9)
    ema_20 = calculate_ema(close_prices, 20)
    adx = calculate_adx(candles, 14)
    vwap_list = calculate_vwap(candles)
    atr = calculate_atr(candles, 14)

    idx = len(candles) - 1
    curr, prev = candles[idx], candles[idx - 1]

    if any(v is None for v in [ema_9[idx], ema_20[idx], adx[idx], atr[idx]]):
        return None
    if ema_20[idx - 1] is None:
        return None
    if adx[idx] < 20:
        return None

    atr_val = atr[idx]

    # Bullish stack: EMA9 > EMA20, price pulls back to EMA20 then bounces
    # Guard None VWAP — intraday_only mode may leave pre-session bars as None
    if (htf_trend != "down" and
            ema_9[idx] > ema_20[idx] and
            abs(prev["low"] - ema_20[idx - 1]) < atr_val * 0.6 and
            curr["close"] > curr["open"] and
            curr["close"] > ema_9[idx] and
            vwap_list[idx] is not None and curr["close"] > vwap_list[idx]):
        entry = curr["close"]
        stop_loss = ema_20[idx] - atr_val * 0.5
        risk = entry - stop_loss
        if risk <= 0:
            return None
        return {
            "strategy": "TrendFollow-Buy",
            "trigger_time": curr["timestamp"],
            "entry_price": round(entry, 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(entry + 1.5 * risk, 2),
            "target_2": round(entry + 2.5 * risk, 2),
            "adx": round(adx[idx], 1),
            "ema_20": round(ema_20[idx], 2),
            "atr": round(atr_val, 2),
        }

    # Bearish stack: EMA9 < EMA20, price pulls back to EMA20 then drops
    # Guard None VWAP — intraday_only mode may leave pre-session bars as None
    if (htf_trend != "up" and
            ema_9[idx] < ema_20[idx] and
            abs(prev["high"] - ema_20[idx - 1]) < atr_val * 0.6 and
            curr["close"] < curr["open"] and
            curr["close"] < ema_9[idx] and
            vwap_list[idx] is not None and curr["close"] < vwap_list[idx]):
        entry = curr["close"]
        stop_loss = ema_20[idx] + atr_val * 0.5
        risk = stop_loss - entry
        if risk <= 0:
            return None
        return {
            "strategy": "TrendFollow-Short",
            "trigger_time": curr["timestamp"],
            "entry_price": round(entry, 2),
            "stop_loss": round(stop_loss, 2),
            "target_1": round(entry - 1.5 * risk, 2),
            "target_2": round(entry - 2.5 * risk, 2),
            "adx": round(adx[idx], 1),
            "ema_20": round(ema_20[idx], 2),
            "atr": round(atr_val, 2),
        }
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Strategy Registry and Adaptive Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

# Maps base strategy name → checker (candles, htf_trend, cfg=None) → signal | None
from strategy_vwap_trend_pullback import check_vwap_trend_pullback as _check_vtp
from strategy_support_resistance import check_support_resistance_strategy as _check_sr
from datetime import UTC

def _check_cpc(c, htf_trend, config):
    from strategy_candlestick_confluence import check_candlestick_confluence_strategy
    return check_candlestick_confluence_strategy(c, config.get("_htf_candles") if config else None, config or {}, htf_trend)

_REGISTRY = {
    "ORB":               lambda c, h, cfg=None: check_orb_strategy(c, 5, 15, h),
    "VWAP-Pullback":     lambda c, h, cfg=None: check_vwap_pullback_strategy(c, h),
    "Momentum":          lambda c, h, cfg=None: check_momentum_breakout_strategy(c, h),
    "MeanReversion":     lambda c, _h, cfg=None: check_mean_reversion_strategy(c),
    "TrendFollow":       lambda c, h, cfg=None: check_trend_following_strategy(c, h),
    "VWAPTrendPullback": lambda c, h, cfg=None: _check_vtp(c, None, cfg or {}, h),
    "SupportResistance": lambda c, h, cfg=None: _check_sr(c, cfg.get("_htf_candles") if cfg else None, cfg or {}, h),
    "CandlestickConfluence": lambda c, h, cfg=None: _check_cpc(c, h, cfg),
}

# Default per-regime priority (best-fit strategies first)
_REGIME_PRIORITY = {
    "trending_up":   ["SupportResistance", "CandlestickConfluence", "VWAPTrendPullback", "ORB", "Momentum", "TrendFollow", "VWAP-Pullback"],
    "trending_down": ["SupportResistance", "CandlestickConfluence", "VWAPTrendPullback", "ORB", "Momentum", "TrendFollow", "VWAP-Pullback"],
    "ranging":       ["SupportResistance", "CandlestickConfluence", "VWAP-Pullback", "MeanReversion", "ORB"],
    "choppy":        ["SupportResistance", "CandlestickConfluence", "ORB", "VWAP-Pullback", "Momentum", "MeanReversion", "TrendFollow"],
    "unknown":       ["SupportResistance", "CandlestickConfluence", "VWAPTrendPullback", "ORB", "VWAP-Pullback", "Momentum", "MeanReversion", "TrendFollow"],
}



def _reorder_by_performance(strategy_names, strategy_order):
    """Bubble higher-ranked strategies to the front while keeping regime-only ones."""
    rank = {s: i for i, s in enumerate(strategy_order)}
    ranked = sorted([s for s in strategy_names if s in rank], key=lambda s: rank[s])
    unranked = [s for s in strategy_names if s not in rank]
    return ranked + unranked


def calculate_signal_confidence(signal, candles, htf_candles=None):
    """Calculates a unified confidence score (0-100) for a strategy signal."""
    score = 0
    curr = candles[-1]
    is_long = "Buy" in signal.get("strategy", "")

    # 1. Trend Alignment (15 pts)
    close_prices = [c["close"] for c in candles]
    ema20 = calculate_ema(close_prices, 20)
    if ema20 and ema20[-1] is not None:
        aligned = (is_long and curr["close"] > ema20[-1]) or (not is_long and curr["close"] < ema20[-1])
        if aligned:
            score += 15

    # 2. Support/Resistance Quality (15 pts)
    sr_score = signal.get("trigger_level_score", 0.0)
    if sr_score > 0:
        score += min(int(sr_score * 3.0), 15)  # Scale level strength to max 15
    else:
        score += 10  # Baseline S/R compatibility

    # 3. Volume Strength (15 pts)
    if len(candles) >= 22:
        avg_vol = sum(c["volume"] for c in candles[-21:-1]) / 20
        vol_ratio = curr["volume"] / avg_vol if avg_vol > 0 else 1.0
        if vol_ratio >= 1.5:
            score += 15
        elif vol_ratio >= 1.2:
            score += 10

    # 4. VWAP Confirmation (15 pts)
    vwap = calculate_vwap(candles)
    # Use the most recent non-None VWAP value — intraday_only mode can leave
    # early indices as None, so walk backwards to find the first valid value.
    last_vwap = next((v for v in reversed(vwap) if v is not None), None)
    if last_vwap is not None:
        aligned = (is_long and curr["close"] > last_vwap) or (not is_long and curr["close"] < last_vwap)
        if aligned:
            score += 15

    # 5. Volatility Quality (10 pts)
    atr = calculate_atr(candles, 14)
    if atr and atr[-1] is not None:
        atr_pct = atr[-1] / curr["close"]
        if 0.004 <= atr_pct <= 0.015:
            score += 10
        elif atr_pct > 0.015:
            score += 5

    # 6. Market Regime Compatibility (15 pts)
    regime = signal.get("regime", "unknown")
    strat = signal.get("strategy", "")
    trend_strats = ("ORB", "Momentum", "TrendFollow", "Breakout")
    range_strats = ("MeanReversion", "Rejection")
    if regime in ("trending_up", "trending_down") and any(s in strat for s in trend_strats):
        score += 15
    elif regime == "ranging" and any(s in strat for s in range_strats):
        score += 15
    elif regime != "choppy":
        score += 10

    # 7. HTF Trend Confirmation (15 pts)
    htf = signal.get("htf_trend", "neutral")
    if (is_long and htf == "up") or (not is_long and htf == "down"):
        score += 15
    elif htf == "neutral":
        score += 10

    # 8. Candlestick Pattern Confluence (M1) — up to 15 pts boost / -10 pts penalty
    try:
        from candlestick_patterns import detect_all_patterns
        patterns = detect_all_patterns(candles)
        
        # Bullish patterns boost longs, bearish patterns boost shorts
        if is_long and patterns['bullish']:
            boost = len(patterns['bullish']) * 5
            score += min(boost, 15)
        elif not is_long and patterns['bearish']:
            boost = len(patterns['bearish']) * 5
            score += min(boost, 15)
            
        # Contrary patterns penalize confidence
        if is_long and patterns['bearish']:
            score -= 10
        elif not is_long and patterns['bullish']:
            score -= 10
    except Exception as cp_err:
        print(f"[Strategies] Candlestick pattern detection failed in confidence calculation: {cp_err}")

    # Clamp final score to [0, 100]
    return min(max(score, 0), 100)


def select_best_strategy(candles, htf_candles=None, strategy_order=None, config=None):
    """
    Detects market regime, selects strategy, and applies confidence/RL sizing policy.
    """
    regime = detect_market_regime(candles, htf_candles)
    htf_trend = get_htf_trend(htf_candles) if htf_candles else "neutral"
    config = config or {}

    priority = list(_REGIME_PRIORITY.get(regime, _REGIME_PRIORITY["unknown"]))
    if strategy_order:
        priority = _reorder_by_performance(priority, strategy_order)

    # ── Collect ALL valid signals across the entire priority list ────────────
    # Previously we returned on the first hit; now we score every candidate
    # and return the one with the highest confidence so the best opportunity
    # wins regardless of where it sits in the priority ordering.
    all_signals = []

    for name in priority:
        checker = _REGISTRY.get(name)
        if not checker:
            continue
        try:
            sig = checker(candles, htf_trend, config)
        except Exception:
            # Defensive: a buggy checker must not crash the orchestrator
            continue
        if not sig:
            continue

        sig['regime'] = regime
        sig['htf_trend'] = htf_trend

        # ── Build RL / market-context state ──────────────────────────────────
        atr_list = calculate_atr(candles, 14)
        atr_val = atr_list[-1] if atr_list and atr_list[-1] is not None else 0.5
        atr_pct = (atr_val / candles[-1]['close']) if candles[-1]['close'] > 0 else 0.008

        avg_vol_20 = 1.0
        if len(candles) >= 22:
            avg_vol_20 = sum(c['volume'] for c in candles[-21:-1]) / 20
        vol_ratio = (candles[-1]['volume'] / avg_vol_20) if avg_vol_20 > 0 else 1.0

        # Resolve VWAP — walk backwards to skip any None pre-session entries
        vwap_list = calculate_vwap(candles)
        vwap_val = next((v for v in reversed(vwap_list) if v is not None), candles[-1]['close'])
        vwap_aligned = (
            (candles[-1]['close'] > vwap_val) if 'Buy' in sig['strategy']
            else (candles[-1]['close'] < vwap_val)
        )

        closes = [c['close'] for c in candles]
        rsi_list = calculate_rsi(closes, 14)
        rsi_val = rsi_list[-1] if (rsi_list and rsi_list[-1] is not None) else 50.0

        adx_list = calculate_adx(candles, 14)
        adx_val = adx_list[-1] if (adx_list and adx_list[-1] is not None) else 20.0

        context = {
            'regime': regime,
            'atr_pct': atr_pct,
            'volume_ratio': vol_ratio,
            'vwap_aligned': vwap_aligned,
            'htf_aligned': (htf_trend == 'up' if 'Buy' in sig['strategy'] else htf_trend == 'down'),
            'time': candles[-1]['timestamp'][11:16],
            'rsi': rsi_val,
            'adx': adx_val
        }

        # ── Confidence score (0-100) ──────────────────────────────────────────
        conf_score = calculate_signal_confidence(sig, candles, htf_candles)
        sig['confidence_score'] = conf_score
        sig['market_context'] = context

        # Tag the candlestick patterns present at entry so they flow signal -> position ->
        # exit record -> pattern_stats.jsonl (blocker #5). Detection already happens inside
        # the confidence scorer; here we keep the names instead of discarding them.
        try:
            from candlestick_patterns import detected_pattern_names
            sig['candlestick_patterns'] = detected_pattern_names(candles)
        except Exception:
            sig['candlestick_patterns'] = []

        sig['is_shadow_trade'] = False
        all_signals.append(sig)

    # ── No strategy fired at all ──────────────────────────────────────────────
    if not all_signals:
        return None

    # ── Pick the signal with the highest confidence score ────────────────────
    best_signal = max(all_signals, key=lambda s: s.get('confidence_score', 0))

    # ── Level-Aware Target Adjuster ──
    best_signal = adjust_targets_with_levels(best_signal, candles, config)

    # ── Confidence threshold gates shadow/live ────────────────────────────────
    threshold = int(config.get('min_confidence_threshold', 60))
    if best_signal.get('confidence_score', 0) < threshold:
        # Flag as shadow trade — simulated in memory, not sent to broker
        best_signal['is_shadow_trade'] = True

    return best_signal


def adjust_targets_with_levels(signal, candles, config):
    """
    Adjusts target_1 and target_2 in the signal so they do not print directly
    on or past major support/resistance levels, capping them just before the level.
    """
    if not signal or not config:
        return signal

    if not config.get("enable_level_aware_targets", True):
        return signal

    # Only adjust for buying (long) and shorting (short)
    is_long = "Buy" in signal.get("strategy", "") or signal.get("direction", "LONG") == "LONG"
    entry = signal["entry_price"]
    t1 = signal["target_1"]
    t2 = signal.get("target_2", t1)
    
    client = config.get("_client")
    instrument_key = config.get("_instrument_key")
    if not client or not instrument_key:
        return signal

    # Fetch levels
    levels = []
    try:
        from strategy_support_resistance import _get_daily_levels, _get_opening_range, _find_pivot_highs, _find_pivot_lows
        from datetime import datetime, timedelta
        
        # Helper for IST
        now_ist = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=5, minutes=30)
        today_str = now_ist.date().isoformat()
        
        pdh, pdl, pdc = _get_daily_levels(client, instrument_key, today_str)
        orh, orl = _get_opening_range(candles, today_str)
        p_highs_5m = _find_pivot_highs(candles, 2, 2)
        p_lows_5m = _find_pivot_lows(candles, 2, 2)
        
        if pdh: levels.append(("PDH", pdh))
        if pdl: levels.append(("PDL", pdl))
        if pdc: levels.append(("PDC", pdc))
        if orh: levels.append(("ORH", orh))
        if orl: levels.append(("ORL", orl))
        for ph in p_highs_5m[-5:]:
            levels.append(("SwingHigh", ph))
        for pl in p_lows_5m[-5:]:
            levels.append(("SwingLow", pl))
    except Exception as e:
        print(f"[Target Adjuster] Error loading levels: {e}")
        return signal

    atr_val = signal.get("atr") or (calculate_atr(candles, 14)[-1] if len(candles) >= 15 else entry * 0.01)
    if atr_val is None or atr_val <= 0:
        atr_val = entry * 0.01
        
    buffer = atr_val * 0.15

    adjusted_t1 = t1
    adjusted_t2 = t2
    t1_adjusted_by = None
    t2_adjusted_by = None

    if is_long:
        # Find any resistance levels between entry and target_1
        for name, price in levels:
            if entry < price <= t1:
                new_t1 = price - buffer
                if new_t1 > entry + atr_val * 0.2 and new_t1 < adjusted_t1:
                    adjusted_t1 = new_t1
                    t1_adjusted_by = name
                    
        # Find resistance levels between entry and target_2
        for name, price in levels:
            if entry < price <= t2:
                new_t2 = price - buffer
                if new_t2 > adjusted_t1 + atr_val * 0.2 and new_t2 < adjusted_t2:
                    adjusted_t2 = new_t2
                    t2_adjusted_by = name
    else:
        # Short trade: find support levels below entry but above target_1
        for name, price in levels:
            if t1 <= price < entry:
                new_t1 = price + buffer
                if new_t1 < entry - atr_val * 0.2 and new_t1 > adjusted_t1:
                    adjusted_t1 = new_t1
                    t1_adjusted_by = name
                    
        for name, price in levels:
            if t2 <= price < entry:
                new_t2 = price + buffer
                if new_t2 < adjusted_t1 - atr_val * 0.2 and new_t2 > adjusted_t2:
                    adjusted_t2 = new_t2
                    t2_adjusted_by = name

    if adjusted_t1 != t1:
        signal["target_1"] = round(adjusted_t1, 2)
        signal["t1_adjusted_by"] = t1_adjusted_by
    if adjusted_t2 != t2:
        signal["target_2"] = round(adjusted_t2, 2)
        signal["t2_adjusted_by"] = t2_adjusted_by

    # Guard: if adjusted target 1 is less than 1.0x of the risk, downgrade the trade!
    risk = abs(entry - signal["stop_loss"])
    adjusted_reward = abs(signal["target_1"] - entry)
    if risk > 0 and adjusted_reward < risk * 1.0:
        signal["is_shadow_trade"] = True
        signal["shadow_reason"] = f"Low RR after level adjustment ({adjusted_reward / risk:.2f} < 1.0)"

    return signal


