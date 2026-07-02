"""Unit tests for Candlestick Pattern Confluence (CPC) Strategy."""

import unittest
import math
from strategy_candlestick_confluence import check_candlestick_confluence_strategy

class MockClient:
    def __init__(self):
        self.config = {
            "enable_candlestick_confluence": True,
            "cpc_volume_multiplier": 1.5
        }
    def get_historical_candles(self, instrument_key, interval, from_date, to_date):
        if interval == "day":
            # Mock historical daily candle for previous day: High=105, Low=95, Close=101
            return [{
                "timestamp": "2026-06-29T18:30:00+05:30",
                "open": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 101.0,
                "volume": 500000
            }]
        return []

def _candle(open_val, high, low, close, volume=100000, ts="2026-06-30T09:30:00+05:30"):
    return {
        "open": float(open_val),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": int(volume),
        "timestamp": ts
    }

def _build_base_candles(price=100.0, n=21):
    candles = []
    for i in range(n):
        ts = f"2026-06-30T09:{15 + i * 5:02d}:00+05:30"
        # Relatively flat candles
        candles.append(_candle(price, price + 0.5, price - 0.5, price, 100000, ts))
    return candles

class TestCandlestickConfluence(unittest.TestCase):
    def setUp(self):
        self.client = MockClient()
        self.config = {
            "_client": self.client,
            "_symbol": "RELIANCE",
            "_instrument_key": "NSE_EQ|INE002A01018",
            "cpc_volume_multiplier": 1.5,
            "enable_candlestick_confluence": True
        }

    def test_bullish_engulfing_at_pdl_level(self):
        """Test a bullish engulfing pattern touching the PDL level (95.0) with strong volume."""
        candles = _build_base_candles(price=100.0, n=20)
        
        # Inject red candle at index 20 (low of 95.0 touching PDL)
        c20 = _candle(97.0, 98.0, 95.0, 95.2, 100000, "2026-06-30T11:00:00+05:30")
        candles.append(c20)
        
        # Inject green engulfing candle at index 21 (opens below 95.2 and closes above 97.0)
        # Volume 300,000 (3x average of 100,000)
        c21 = _candle(94.8, 98.5, 94.8, 98.2, 300000, "2026-06-30T11:05:00+05:30")
        candles.append(c21)
        
        signal = check_candlestick_confluence_strategy(candles, None, self.config, "up")
        
        self.assertIsNotNone(signal)
        self.assertEqual(signal["strategy"], "CandlestickConfluence-Buy")
        self.assertEqual(signal["pattern"], "Bullish Engulfing")
        self.assertEqual(signal["level"], "PDL")
        self.assertEqual(signal["level_price"], 95.0)
        self.assertEqual(signal["entry_price"], 98.2)
        self.assertLess(signal["stop_loss"], 94.8) # Should have a small buffer below low (94.8)

    def test_hammer_near_ema20(self):
        """Test a Hammer pattern touching the EMA20 line with strong volume."""
        # EMA20 will be around 100.0
        candles = _build_base_candles(price=100.0, n=21)
        
        # Replace the last candle (index 21) with a Hammer touching EMA20 (100.0)
        # Body: open=100.0, close=100.5 (green)
        # Low: 98.0 (Wick = 2.0, body = 0.5; wick >= 2x body)
        # High: 100.6 (Upper wick = 0.1; upper wick < 0.3x body)
        # Volume: 300,000 (3x average)
        candles[20] = _candle(100.0, 100.6, 98.0, 100.5, 300000, "2026-06-30T11:00:00+05:30")
        
        signal = check_candlestick_confluence_strategy(candles, None, self.config, "up")
        
        self.assertIsNotNone(signal)
        self.assertEqual(signal["strategy"], "CandlestickConfluence-Buy")
        self.assertEqual(signal["pattern"], "Hammer")
        self.assertIn(signal["level"], ["EMA20", "VWAP"])
        self.assertEqual(signal["entry_price"], 100.5)

    def test_low_volume_ignored(self):
        """Test that a pattern is ignored if its volume is weak (below 1.5x average)."""
        candles = _build_base_candles(price=100.0, n=20)
        c20 = _candle(97.0, 98.0, 95.0, 95.2, 100000)
        candles.append(c20)
        # Engulfing pattern but only 100,000 volume (equal to average, not 1.5x)
        c21 = _candle(94.8, 98.5, 94.8, 98.2, 100000)
        candles.append(c21)
        
        signal = check_candlestick_confluence_strategy(candles, None, self.config, "up")
        self.assertIsNone(signal)

    def test_no_level_confluence_ignored(self):
        """Test that a pattern is ignored if it occurs in empty space (no key S/R level nearby)."""
        # Price is moved to 150.0 (far from 95, 101, 105 levels and EMA20)
        candles = _build_base_candles(price=150.0, n=20)
        c20 = _candle(147.0, 148.0, 145.0, 145.2, 100000)
        candles.append(c20)
        c21 = _candle(144.8, 148.5, 144.8, 148.2, 300000)
        candles.append(c21)
        
        signal = check_candlestick_confluence_strategy(candles, None, self.config, "up")
        self.assertIsNone(signal)

    def test_disabled_strategy_ignored(self):
        """Test that strategy returns None immediately if enable_candlestick_confluence is False."""
        self.config["enable_candlestick_confluence"] = False
        candles = _build_base_candles(price=100.0, n=20)
        c20 = _candle(97.0, 98.0, 95.0, 95.2, 100000)
        candles.append(c20)
        c21 = _candle(94.8, 98.5, 94.8, 98.2, 300000)
        candles.append(c21)
        
        signal = check_candlestick_confluence_strategy(candles, None, self.config, "up")
        self.assertIsNone(signal)

if __name__ == "__main__":
    unittest.main()
