"""Unit tests for Level-Aware Target Adjustment."""

import unittest
from strategies import adjust_targets_with_levels

class MockClient:
    def __init__(self):
        self.config = {
            "enable_level_aware_targets": True
        }
        self.pdh = 104.0
        self.pdl = 95.0
        self.pdc = 97.0
        
    def get_historical_candles(self, instrument_key, interval, from_date, to_date):
        if interval == "day":
            # Mock historical daily candle for previous day: High=104, Low=95, Close=101
            return [{
                "timestamp": "2026-06-29T18:30:00+05:30",
                "open": 100.0,
                "high": self.pdh,
                "low": self.pdl,
                "close": self.pdc,
                "volume": 500000
            }]
        return []

def _candle(open_val, high, low, close, volume=100000):
    return {
        "open": float(open_val),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": int(volume),
        "timestamp": "2026-06-30T09:30:00+05:30"
    }

class TestLevelAwareTargets(unittest.TestCase):
    def setUp(self):
        self.client = MockClient()
        self.config = {
            "_client": self.client,
            "_symbol": "RELIANCE",
            "_instrument_key": "NSE_EQ|INE002A01018",
            "enable_level_aware_targets": True
        }
        self.candles = [_candle(100.0, 100.5, 99.5, 100.0) for _ in range(25)]

    def test_target_cap_before_resistance(self):
        """Test that Target 1 is capped just below a resistance level (PDH = 104.0)."""
        # Long signal: Entry = 100.0, SL = 98.0 (Risk = 2.0).
        # Original T1 = 100.0 + 1.5 * 2.0 = 103.0 (fine, no resistance in way).
        # Original T2 = 100.0 + 2.5 * 2.0 = 105.0 (obstructed by PDH = 104.0).
        signal = {
            "strategy": "ORB-Buy",
            "entry_price": 100.0,
            "stop_loss": 98.0,
            "target_1": 103.0,
            "target_2": 105.0,
            "atr": 1.0
        }
        
        adjusted = adjust_targets_with_levels(signal, self.candles, self.config)
        
        # Buffer is atr_val * 0.15 = 1.0 * 0.15 = 0.15
        # Target 2 should be adjusted to PDH - buffer = 104.0 - 0.15 = 103.85
        self.assertEqual(adjusted["target_1"], 103.0) # untouched
        self.assertEqual(adjusted["target_2"], 103.85) # capped before PDH
        self.assertEqual(adjusted["t2_adjusted_by"], "PDH")
        self.assertFalse(adjusted.get("is_shadow_trade", False))

    def test_low_risk_reward_downgrades_to_shadow(self):
        """Test that trade is flagged as shadow if the adjusted target yields RR < 1.0x."""
        # Long signal: Entry = 103.0, SL = 101.0 (Risk = 2.0).
        # Original T1 = 103.0 + 1.5 * 2.0 = 106.0 (obstructed by PDH = 104.0).
        # Capped T1 = PDH - buffer = 104.0 - 0.15 = 103.85.
        # Adjusted Reward = 103.85 - 103.0 = 0.85.
        # Risk is 2.0. Adjusted Reward (0.85) < Risk (2.0), so RR < 1.0x.
        # Verify it is flagged as shadow trade.
        signal = {
            "strategy": "ORB-Buy",
            "entry_price": 103.0,
            "stop_loss": 101.0,
            "target_1": 106.0,
            "target_2": 108.0,
            "atr": 1.0
        }
        
        adjusted = adjust_targets_with_levels(signal, self.candles, self.config)
        
        self.assertEqual(adjusted["target_1"], 103.85)
        self.assertTrue(adjusted.get("is_shadow_trade", False))
        self.assertIn("Low RR after level adjustment", adjusted.get("shadow_reason", ""))

    def test_disabled_adjuster_does_nothing(self):
        """Test that target adjuster does nothing when disabled in config."""
        self.config["enable_level_aware_targets"] = False
        signal = {
            "strategy": "ORB-Buy",
            "entry_price": 100.0,
            "stop_loss": 98.0,
            "target_1": 103.0,
            "target_2": 105.0,
            "atr": 1.0
        }
        adjusted = adjust_targets_with_levels(signal, self.candles, self.config)
        self.assertEqual(adjusted["target_2"], 105.0) # untouched

    def test_trailing_stop_activation(self):
        """Test that trailing stop only activates after price moves in favor by 0.5x trail_gap."""
        from main import _update_trailing_stop
        
        pos = {
            "direction": "LONG",
            "entry_price": 100.0,
            "stop_loss": 98.0,
            "atr_at_entry": 1.0,
            "quantity": 10
        }
        
        # Trailing multiplier = 1.5, so trail_gap = 1.5.
        # Activation price = 100.0 + 0.5 * 1.5 = 100.75.
        
        # 1. Price moves slightly in favor to 100.5 (below activation).
        # Trailing stop should NOT activate and SL should remain 98.0.
        res = _update_trailing_stop(pos, 100.5, 1.5)
        self.assertFalse(res.sl_changed)
        self.assertEqual(pos["stop_loss"], 98.0)
        self.assertFalse(pos.get("trailing_active", False))
        
        # 2. Price hits 100.8 (above activation).
        # Trailing stop should activate and SL should update to 100.8 - 1.5 = 99.3.
        res2 = _update_trailing_stop(pos, 100.8, 1.5)
        self.assertTrue(res2.sl_changed)
        self.assertEqual(pos["stop_loss"], 99.3)
        self.assertTrue(pos.get("trailing_active", False))

if __name__ == "__main__":
    unittest.main()
