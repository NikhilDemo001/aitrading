"""ORB opening-range sanity: a noise-level (sub-0.1%-of-price) opening range must not
produce breakout signals — its levels carry no information (see check_orb_strategy)."""

from strategies import check_orb_strategy


def candle(o, h, l, c, v=1000):
    return {"timestamp": "2026-07-04T10:00:00", "open": o, "high": h, "low": l, "close": c, "volume": v}


def orb_candles(range_high, range_low, n_quiet=18):
    """3 range candles, quiet drift inside, then a decisive high-volume breakout candle."""
    mid = (range_high + range_low) / 2
    out = [candle(mid, range_high, range_low, mid) for _ in range(3)]
    out += [candle(mid, mid + 0.2, mid - 0.2, mid) for _ in range(n_quiet)]
    out.append(candle(mid, mid + 1.7, mid - 0.1, mid + 1.5, v=5000))
    return out


def test_orb_fires_on_meaningful_range():
    sig = check_orb_strategy(orb_candles(100.5, 99.5), htf_trend="up")
    assert sig is not None and sig["strategy"] == "ORB-Buy"


def test_orb_skips_noise_level_range():
    # Identical breakout mechanics, but the 15-min range is 0.04 (~0.04% of price): skip.
    assert check_orb_strategy(orb_candles(100.02, 99.98), htf_trend="up") is None
