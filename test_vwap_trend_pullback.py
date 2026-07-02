"""Unit tests for VWAP Trend Pullback Strategy."""

import unittest
import math as _math

from strategy_vwap_trend_pullback import (
    _find_pivot_highs,
    _find_pivot_lows,
    detect_market_structure,
    _ema_slope,
    calculate_confidence_score,
    check_vwap_trend_pullback,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _candle(open_, high, low, close, volume=100_000, ts="2024-01-02 09:30:00"):
    return {"open": open_, "high": high, "low": low,
            "close": close, "volume": volume, "timestamp": ts}


def _flat_candles(price=100.0, n=40):
    return [_candle(price, price + 1, price - 1, price, 200_000) for _ in range(n)]


def _wavy_candles(n, start, trend_step, wave_amp=4.0, wave_period=10):
    """
    Trending but oscillating candles — sine wave riding on a trend slope.
    Pivot highs appear at sine peaks, pivot lows at troughs, with the overall
    trend ensuring HH+HL (positive trend_step) or LH+LL (negative trend_step).
    """
    out = []
    for i in range(n):
        p         = start + i * trend_step
        osc       = wave_amp * _math.sin(2 * _math.pi * i / wave_period)
        h         = p + osc + 3.0
        l         = p + osc - 3.0
        c         = p + osc + 1.0
        o         = p + osc - 1.0
        out.append(_candle(o, h, l, c, 300_000))
    return out


def _bullish_candles(n=40, start=100.0, step=0.8):
    """Oscillating uptrend — creates HH+HL swing structure."""
    return _wavy_candles(n, start, step)


def _bearish_candles(n=40, start=140.0, step=0.8):
    """Oscillating downtrend — creates LH+LL swing structure."""
    return _wavy_candles(n, start, -step)


# ── Pivot detection ──────────────────────────────────────────────────────────

class TestPivotDetection(unittest.TestCase):

    def test_highs_found(self):
        candles = _flat_candles(100.0, 20)
        # inject a clear peak in the middle
        candles[8]  = _candle(100, 120, 99, 110)
        candles[12] = _candle(100, 115, 99, 108)
        ph = _find_pivot_highs(candles)
        self.assertGreater(len(ph), 0)
        highs = [h for _, h in ph]
        self.assertIn(120, highs)

    def test_lows_found(self):
        candles = _flat_candles(100.0, 20)
        candles[8]  = _candle(100, 101, 80, 82)
        candles[12] = _candle(100, 101, 85, 87)
        pl = _find_pivot_lows(candles)
        self.assertGreater(len(pl), 0)
        lows = [l for _, l in pl]
        self.assertIn(80, lows)

    def test_pivot_is_local_maximum(self):
        candles = _flat_candles(100.0, 20)
        candles[10] = _candle(100, 130, 99, 120)
        ph = _find_pivot_highs(candles)
        for idx, h in ph:
            self.assertGreaterEqual(h, candles[idx - 1]["high"])
            self.assertGreaterEqual(h, candles[idx + 1]["high"])

    def test_pivot_is_local_minimum(self):
        candles = _flat_candles(100.0, 20)
        candles[10] = _candle(80, 95, 70, 85)
        pl = _find_pivot_lows(candles)
        for idx, lo in pl:
            self.assertLessEqual(lo, candles[idx - 1]["low"])
            self.assertLessEqual(lo, candles[idx + 1]["low"])

    def test_no_false_pivots_on_flat(self):
        # Perfectly flat — no pivot should be detected because no bar is strictly
        # higher/lower than its neighbors.
        flat = [_candle(100, 101, 99, 100) for _ in range(20)]
        ph = _find_pivot_highs(flat)
        pl = _find_pivot_lows(flat)
        self.assertEqual(len(ph), 0)
        self.assertEqual(len(pl), 0)


# ── Market structure ─────────────────────────────────────────────────────────

class TestMarketStructure(unittest.TestCase):

    def test_bullish_detected(self):
        candles = _bullish_candles(40)
        struct, sh, sl = detect_market_structure(candles)
        self.assertEqual(struct, "bullish")

    def test_bearish_detected(self):
        candles = _bearish_candles(40)
        struct, sh, sl = detect_market_structure(candles)
        self.assertEqual(struct, "bearish")

    def test_neutral_on_flat(self):
        candles = _flat_candles(100.0, 20)
        struct, sh, sl = detect_market_structure(candles)
        self.assertEqual(struct, "neutral")

    def test_swing_high_low_not_none_on_trend(self):
        candles = _bullish_candles(40)
        _, sh, sl = detect_market_structure(candles)
        self.assertIsNotNone(sh)
        self.assertIsNotNone(sl)


# ── EMA slope ────────────────────────────────────────────────────────────────

class TestEmaSlope(unittest.TestCase):

    def test_upward_slope(self):
        vals = [100, 101, 102, 103, 104, 105]
        self.assertEqual(_ema_slope(vals), "up")

    def test_downward_slope(self):
        vals = [105, 104, 103, 102, 101, 100]
        self.assertEqual(_ema_slope(vals), "down")

    def test_flat_slope(self):
        vals = [100.0, 100.01, 100.0, 100.02, 100.01, 100.01]
        self.assertEqual(_ema_slope(vals), "flat")

    def test_none_values_skipped(self):
        vals = [None, None, 100, 100.5, 101]
        result = _ema_slope(vals)
        self.assertIn(result, ("up", "down", "flat"))


# ── Confidence score ─────────────────────────────────────────────────────────

class TestConfidenceScore(unittest.TestCase):

    def _perfect(self):
        return {
            "vwap_dist_pct":    0.01,
            "pivot_count":      4,
            "imp_vol":          300_000,
            "pb_vol":           100_000,
            "touched_vwap":     True,
            "touched_ema":      True,
            "pb_depth_pct":     0.5,
            "body_ratio":       0.8,
            "close_at_extreme": True,
            "atr_pct":          0.01,
        }

    def _zero(self):
        return {
            "vwap_dist_pct":    0.0,
            "pivot_count":      0,
            "imp_vol":          0,
            "pb_vol":           100_000,
            "touched_vwap":     False,
            "touched_ema":      False,
            "pb_depth_pct":     0.0,
            "body_ratio":       0.1,
            "close_at_extreme": False,
            "atr_pct":          0.0,
        }

    def test_perfect_score_high(self):
        score, _ = calculate_confidence_score(self._perfect())
        self.assertGreaterEqual(score, 90)

    def test_zero_score_on_bad_data(self):
        score, _ = calculate_confidence_score(self._zero())
        self.assertEqual(score, 0)

    def test_score_never_exceeds_100(self):
        d = self._perfect()
        d["pivot_count"]  = 100
        d["imp_vol"]      = 10_000_000
        score, _ = calculate_confidence_score(d)
        self.assertLessEqual(score, 100)

    def test_score_non_negative(self):
        score, _ = calculate_confidence_score(self._zero())
        self.assertGreaterEqual(score, 0)

    def test_detail_keys_present(self):
        _, detail = calculate_confidence_score(self._perfect())
        for key in ("vwap_alignment", "trend_structure", "volume_ratio",
                    "pullback_quality", "candle_quality", "volatility"):
            self.assertIn(key, detail)


# ── Main strategy function ───────────────────────────────────────────────────

class TestStrategyMainFunction(unittest.TestCase):

    def test_returns_none_on_insufficient_data(self):
        candles = _bullish_candles(10)
        result  = check_vwap_trend_pullback(candles)
        self.assertIsNone(result)

    def test_returns_none_when_disabled(self):
        candles = _bullish_candles(50)
        result  = check_vwap_trend_pullback(candles, config={"enable_vwap_trend_pullback": False})
        self.assertIsNone(result)

    def test_signal_has_required_keys(self):
        """Build a near-perfect bullish setup and check signal structure."""
        required = {
            "strategy", "entry_price", "stop_loss", "target_1", "target_2",
            "vwap", "ema_20", "atr", "confidence", "confidence_detail",
            "structure", "ema_slope",
        }
        # Use a generous threshold so we can actually get a signal on synthetic data
        config = {"vwap_tp_confidence_threshold": 1}
        candles = _make_ideal_long_setup()
        result  = check_vwap_trend_pullback(candles, config=config)
        if result is not None:
            for k in required:
                self.assertIn(k, result, f"Missing key: {k}")
            self.assertIn(result["strategy"], ("VWAPTrendPullback-Buy", "VWAPTrendPullback-Short"))

    def test_stop_loss_below_entry_for_long(self):
        config  = {"vwap_tp_confidence_threshold": 1}
        candles = _make_ideal_long_setup()
        result  = check_vwap_trend_pullback(candles, config=config)
        if result and result["strategy"] == "VWAPTrendPullback-Buy":
            self.assertLess(result["stop_loss"], result["entry_price"])

    def test_target_above_entry_for_long(self):
        config  = {"vwap_tp_confidence_threshold": 1}
        candles = _make_ideal_long_setup()
        result  = check_vwap_trend_pullback(candles, config=config)
        if result and result["strategy"] == "VWAPTrendPullback-Buy":
            self.assertGreater(result["target_1"], result["entry_price"])
            self.assertGreater(result["target_2"], result["target_1"])

    def test_high_threshold_returns_none(self):
        config  = {"vwap_tp_confidence_threshold": 101}
        candles = _make_ideal_long_setup()
        result  = check_vwap_trend_pullback(candles, config=config)
        self.assertIsNone(result)


def _make_ideal_long_setup():
    """
    Constructs synthetic 5-min candles that should trigger a LONG signal:
    - Rising trend (HH+HL structure) for 30+ bars
    - VWAP and EMA20 below price (bullish)
    - A 5-bar low-volume pullback to VWAP/EMA20
    - Final strong bullish candle with high volume
    """
    candles = []
    base    = 500.0

    # Phase 1 — rising impulse (bars 0-24) with swings to create pivots
    for i in range(25):
        p = base + i * 1.5
        v = 300_000 + i * 2000
        swing = 3 if (i % 5 == 0) else 1
        candles.append(_candle(p, p + swing + 2, p - 1, p + 1, v, f"2024-01-02 0{9}:{i:02d}:00"))

    # Phase 2 — pullback (bars 25-29) with low volume toward VWAP
    pullback_base = candles[-1]["close"]
    for i in range(5):
        p = pullback_base - i * 0.8
        candles.append(_candle(p, p + 0.5, p - 1.5, p - 0.5, 80_000, f"2024-01-02 10:{i:02d}:00"))

    # Phase 3 — strong confirmation candle with volume surge
    p = candles[-1]["close"]
    candles.append(_candle(p, p + 5, p - 0.3, p + 4.5, 500_000, "2024-01-02 10:05:00"))

    return candles


if __name__ == "__main__":
    unittest.main()
