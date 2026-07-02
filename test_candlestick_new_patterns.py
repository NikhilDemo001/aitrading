"""Unit tests for the 5 candlestick patterns added to fill the gap vs the target spec list:
inverted hammer, hanging man, spinning top, three white soldiers, three black crows — plus the
new numeric strength scoring and detect_all_patterns' trend-based disambiguation."""

import pytest

from candlestick_patterns import (
    detect_inverted_hammer, detect_hanging_man, detect_spinning_top,
    detect_three_white_soldiers, detect_three_black_crows,
    detect_all_patterns, _recent_trend,
)


def candle(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


def uptrend_candles(n=6, start=100.0, step=1.0):
    out = []
    price = start
    for _ in range(n):
        out.append(candle(price, price + 0.5, price - 0.2, price + step * 0.8))
        price += step
    return out


def downtrend_candles(n=6, start=100.0, step=1.0):
    out = []
    price = start
    for _ in range(n):
        out.append(candle(price, price + 0.2, price - 0.5, price - step * 0.8))
        price -= step
    return out


# ── Inverted Hammer / Hanging Man (share Shooting Star / Hammer geometry) ───────────────────

def test_inverted_hammer_matches_shooting_star_shape():
    # body=2 (100->102), upper_wick=6 (108), lower_wick=0.4 (99.6): body/range=23.8%, clear of
    # the Doji threshold (<10%), so this exercises the Hammer/Shooting-Star path cleanly.
    candles = [candle(100.0, 108.0, 99.6, 102.0)]
    assert detect_inverted_hammer(candles) is True


def test_hanging_man_matches_hammer_shape():
    # body=2 (96->94), lower_wick=6 (88), upper_wick=0.4 (96.4): body/range=23.8%.
    candles = [candle(96.0, 96.4, 88.0, 94.0)]
    assert detect_hanging_man(candles) is True


def test_recent_trend_detects_down_and_up():
    assert _recent_trend(downtrend_candles(8)) == 'down'
    assert _recent_trend(uptrend_candles(8)) == 'up'
    assert _recent_trend([candle(100, 101, 99, 100.1) for _ in range(8)]) == 'flat'


def test_detect_all_patterns_labels_hammer_shape_by_trend():
    hammer_shape = candle(96.0, 96.4, 88.0, 94.0)

    # After a downtrend, the hammer-shaped candle is bullish "Hammer".
    down_then_hammer = downtrend_candles(8) + [hammer_shape]
    result_down = detect_all_patterns(down_then_hammer)
    assert "Hammer" in result_down["bullish"]
    assert "Hanging Man" not in result_down["bearish"]

    # After an uptrend, the SAME shape is bearish "Hanging Man".
    up_then_hammer = uptrend_candles(8) + [hammer_shape]
    result_up = detect_all_patterns(up_then_hammer)
    assert "Hanging Man" in result_up["bearish"]
    assert "Hammer" not in result_up["bullish"]


def test_detect_all_patterns_labels_shooting_star_shape_by_trend():
    star_shape = candle(100.0, 108.0, 99.6, 102.0)

    up_then_star = uptrend_candles(8) + [star_shape]
    result_up = detect_all_patterns(up_then_star)
    assert "Shooting Star" in result_up["bearish"]
    assert "Inverted Hammer" not in result_up["bullish"]

    down_then_star = downtrend_candles(8) + [star_shape]
    result_down = detect_all_patterns(down_then_star)
    assert "Inverted Hammer" in result_down["bullish"]
    assert "Shooting Star" not in result_down["bearish"]


# ── Spinning Top ─────────────────────────────────────────────────────────────────────────────

def test_spinning_top_detected_for_small_balanced_body():
    # body = 2 (100->102), range = 10 (95->105): body_frac=0.2, wicks: upper=3, lower=5 -> ratio~0.6
    candles = [candle(100.0, 105.0, 95.0, 102.0)]
    assert detect_spinning_top(candles) is True


def test_spinning_top_rejects_doji_sized_body():
    # body_frac too small (< 10%) -> not a spinning top (it's a doji)
    candles = [candle(100.0, 105.0, 95.0, 100.3)]
    assert detect_spinning_top(candles) is False


def test_spinning_top_rejects_dominant_wick_shapes():
    # Hammer shape: one wick totally dominates -> not a spinning top
    candles = [candle(96.0, 96.4, 88.0, 94.0)]
    assert detect_spinning_top(candles) is False


# ── Three White Soldiers / Three Black Crows ────────────────────────────────────────────────

def test_three_white_soldiers_detected():
    c1 = candle(100.0, 105.2, 99.8, 105.0)
    c2 = candle(102.0, 108.2, 101.8, 108.0)
    c3 = candle(105.0, 111.2, 104.8, 111.0)
    assert detect_three_white_soldiers([c1, c2, c3]) is True


def test_three_white_soldiers_rejects_if_any_candle_is_red():
    c1 = candle(100.0, 105.2, 99.8, 105.0)
    c2 = candle(102.0, 108.2, 101.8, 101.0)  # red candle breaks the pattern
    c3 = candle(105.0, 111.2, 104.8, 111.0)
    assert detect_three_white_soldiers([c1, c2, c3]) is False


def test_three_black_crows_detected():
    c1 = candle(105.0, 105.2, 99.8, 100.0)
    c2 = candle(103.0, 103.2, 97.8, 98.0)
    c3 = candle(101.0, 101.2, 94.8, 95.0)
    assert detect_three_black_crows([c1, c2, c3]) is True


def test_three_black_crows_rejects_if_any_candle_is_green():
    c1 = candle(105.0, 105.2, 99.8, 100.0)
    c2 = candle(103.0, 106.2, 97.8, 106.0)  # green candle breaks the pattern
    c3 = candle(101.0, 101.2, 94.8, 95.0)
    assert detect_three_black_crows([c1, c2, c3]) is False


# ── Strength scores ──────────────────────────────────────────────────────────────────────────

def test_detect_all_patterns_attaches_strength_scores():
    hammer_shape = candle(96.0, 96.4, 88.0, 94.0)
    result = detect_all_patterns(downtrend_candles(8) + [hammer_shape])
    assert "Hammer" in result["bullish"]
    assert "strengths" in result
    assert 0 <= result["strengths"]["Hammer"] <= 100


def test_strength_scores_are_all_ints_in_range():
    c1 = candle(100.0, 105.2, 99.8, 105.0)
    c2 = candle(102.0, 108.2, 101.8, 108.0)
    c3 = candle(105.0, 111.2, 104.8, 111.0)
    result = detect_all_patterns([c1, c2, c3])
    for name, score in result["strengths"].items():
        assert isinstance(score, int), f"{name} strength not an int"
        assert 0 <= score <= 100, f"{name} strength out of range: {score}"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
