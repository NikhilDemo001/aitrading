"""
Automated Test Script for Support & Resistance Strategy
======================================================
Tests breakout detection, rejection detection, volume filters, fake breakout protection,
and HTF trend alignment.
"""

import datetime
from strategy_support_resistance import check_support_resistance_strategy

class MockClient:
    def __init__(self, daily_candles=None):
        self.daily_candles = daily_candles or []
        self.paper_trading = True
        self.config = {"paper_capital": 100000.0}

    def get_historical_candles(self, instrument_key, interval, from_date, to_date):
        return self.daily_candles

    def get_funds_and_margin(self):
        return {
            "status": "success",
            "data": {
                "equity": {
                    "available_margin": 100000.0
                }
            }
        }

def create_base_candles(n=30, base_price=100.0, volume=1000):
    """Generates a base list of candles with flat price."""
    candles = []
    start_time = datetime.datetime(2026, 6, 12, 9, 15)
    for i in range(n):
        ts = (start_time + datetime.timedelta(minutes=5 * i)).strftime("%Y-%m-%dT%H:%M:00+05:30")

        candles.append({
            "timestamp": ts,
            "open": base_price,
            "high": base_price,
            "low": base_price,
            "close": base_price,
            "volume": volume
        })
    return candles

def test_long_breakout():
    print("Testing Long Breakout...")
    client = MockClient(daily_candles=[
        {"timestamp": "2026-06-11T00:00:00+05:30", "open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "volume": 10000}
    ])
    
    # 22 candles: index 0 to 21
    candles = create_base_candles(22, base_price=101.0, volume=1000)
    
    # Add a resistance touch in the past to build level score
    # Level is PDH = 105.0 (Daily level base weight is 3.0, touch count will increase it)
    # Let's say candle at index 10 touched high 105.0 with average volume
    candles[10]["high"] = 105.0
    candles[10]["volume"] = 1000
    
    # Candle 20 (prev) is just below resistance
    candles[20] = {
        "timestamp": "2026-06-12T11:00:00+05:30",
        "open": 104.0, "high": 104.8, "low": 103.5, "close": 104.5, "volume": 1000
    }
    # Candle 21 (curr) breaks out above 105.0 (PDH) with high volume and strong body
    candles[21] = {
        "timestamp": "2026-06-12T11:05:00+05:30",
        "open": 104.6, "high": 106.2, "low": 104.4, "close": 106.0, "volume": 3000  # 3x average
    }
    
    config = {
        "_client": client,
        "_instrument_key": "NSE_EQ|INE002A01018",
        "_symbol": "RELIANCE",
        "_trade_history": []
    }
    
    signal = check_support_resistance_strategy(candles, None, config, htf_trend="up")
    assert signal is not None, "Long breakout signal should not be None"
    assert "Breakout-Buy" in signal["strategy"], f"Expected Breakout-Buy, got {signal['strategy']}"
    assert signal["entry_price"] == 106.0, f"Expected entry price 106.0, got {signal['entry_price']}"
    assert signal["trigger_level_source"] == "PDH", f"Expected level PDH, got {signal['trigger_level_source']}"
    print("[OK] Long Breakout Test Passed!")

def test_fake_breakout_low_volume():
    print("Testing Fake Breakout (Low Volume)...")
    client = MockClient(daily_candles=[
        {"timestamp": "2026-06-11T00:00:00+05:30", "open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "volume": 10000}
    ])
    candles = create_base_candles(22, base_price=101.0, volume=1000)
    candles[10]["high"] = 105.0
    
    # Candle 21 (curr) breaks out above 105.0 but volume is low (1000, which is equal to average)
    candles[20] = {
        "timestamp": "2026-06-12T11:00:00+05:30",
        "open": 104.0, "high": 104.8, "low": 103.5, "close": 104.5, "volume": 1000
    }
    candles[21] = {
        "timestamp": "2026-06-12T11:05:00+05:30",
        "open": 104.6, "high": 106.2, "low": 104.4, "close": 106.0, "volume": 1000  # Equal to average
    }
    config = {
        "_client": client,
        "_instrument_key": "NSE_EQ|INE002A01018",
        "_symbol": "RELIANCE",
        "_trade_history": []
    }
    signal = check_support_resistance_strategy(candles, None, config, htf_trend="up")
    assert signal is None, "Should reject low volume breakout"
    print("[OK] Fake Breakout (Low Volume) Test Passed!")

def test_long_rejection():
    print("Testing Long Rejection...")
    # PDL is 98.0 (Support Level)
    client = MockClient(daily_candles=[
        {"timestamp": "2026-06-11T00:00:00+05:30", "open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "volume": 10000}
    ])
    
    # We need 23 candles to look back: prev_2, prev, curr
    candles = create_base_candles(23, base_price=102.0, volume=1000)
    
    # Add support touches in the past to build score
    candles[5]["low"] = 98.0
    candles[12]["low"] = 98.0
    
    # Candle 20 (prev_2) is just high
    candles[20] = {
        "timestamp": "2026-06-12T11:00:00+05:30",
        "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.2, "volume": 1000
    }
    
    # Candle 21 (prev) is a Bullish Rejection wick touching 98.0 (PDL)
    # Range is 100.0 - 97.8 = 2.2.
    # Close is 99.8, Open is 99.6. Body is 0.2.
    # Lower wick is min(open, close) - low = 99.6 - 97.8 = 1.8.
    # 1.8 / 2.2 = 81.8% lower wick. This is a clear pin bar!
    # Closes above support 98.0.
    candles[21] = {
        "timestamp": "2026-06-12T11:05:00+05:30",
        "open": 99.6, "high": 100.0, "low": 97.8, "close": 99.8, "volume": 1200
    }
    
    # Candle 22 (curr) is the confirmation candle: closes bullish and higher than prev close
    candles[22] = {
        "timestamp": "2026-06-12T11:10:00+05:30",
        "open": 99.9, "high": 101.5, "low": 99.8, "close": 101.2, "volume": 1500
    }
    
    config = {
        "_client": client,
        "_instrument_key": "NSE_EQ|INE002A01018",
        "_symbol": "RELIANCE",
        "_trade_history": []
    }
    
    signal = check_support_resistance_strategy(candles, None, config, htf_trend="up")
    assert signal is not None, "Long rejection signal should not be None"
    assert "Rejection-Buy" in signal["strategy"], f"Expected Rejection-Buy, got {signal['strategy']}"
    assert signal["entry_price"] == 101.2, f"Expected entry price 101.2, got {signal['entry_price']}"
    assert signal["trigger_level_source"] == "PDL", f"Expected level PDL, got {signal['trigger_level_source']}"
    print("[OK] Long Rejection Test Passed!")

def test_trailing_stop_loss():
    print("Testing Trailing Stop Loss...")
    from main import _update_trailing_stop
    
    # 1. Test LONG position trailing stop
    pos_long = {
        "direction": "LONG",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "atr_at_entry": 5.0,
        "trailing_high": 100.0
    }
    
    # Price moves down: trailing stop should NOT move down
    changed = _update_trailing_stop(pos_long, 98.0, 1.0) # Gap = 5.0 * 1.0 = 5.0
    assert not changed, "Stop loss should not change when price moves against us"
    assert pos_long["stop_loss"] == 95.0, f"Expected SL 95.0, got {pos_long['stop_loss']}"
    
    # Price moves up to 104.0: trailing high becomes 104.0, new SL candidate = 104.0 - 5.0 = 99.0
    # Since 99.0 > 95.0, the stop loss should move to 99.0
    changed = _update_trailing_stop(pos_long, 104.0, 1.0)
    assert changed, "Stop loss should update when price moves in our favor"
    assert pos_long["trailing_high"] == 104.0, f"Expected trailing high 104.0, got {pos_long['trailing_high']}"
    assert pos_long["stop_loss"] == 99.0, f"Expected SL 99.0, got {pos_long['stop_loss']}"
    
    # Price moves down to 102.0: trailing stop should stay at 99.0
    changed = _update_trailing_stop(pos_long, 102.0, 1.0)
    assert not changed, "Stop loss should not change when price drops from high"
    assert pos_long["trailing_high"] == 104.0, f"Expected trailing high 104.0, got {pos_long['trailing_high']}"
    assert pos_long["stop_loss"] == 99.0, f"Expected SL 99.0, got {pos_long['stop_loss']}"
    
    # Price moves up to 110.0: new SL = 110.0 - 5.0 = 105.0
    changed = _update_trailing_stop(pos_long, 110.0, 1.0)
    assert changed, "Stop loss should update on new high"
    assert pos_long["trailing_high"] == 110.0
    assert pos_long["stop_loss"] == 105.0
    
    # 2. Test SHORT position trailing stop
    pos_short = {
        "direction": "SHORT",
        "entry_price": 100.0,
        "stop_loss": 105.0,
        "atr_at_entry": 5.0,
        "trailing_low": 100.0
    }
    
    # Price moves up: SL should not change
    changed = _update_trailing_stop(pos_short, 102.0, 1.0)
    assert not changed
    assert pos_short["stop_loss"] == 105.0
    
    # Price moves down to 94.0: trailing low becomes 94.0, new SL = 94.0 + 5.0 = 99.0
    # Since 99.0 < 105.0, the stop loss should move down to 99.0
    changed = _update_trailing_stop(pos_short, 94.0, 1.0)
    assert changed
    assert pos_short["trailing_low"] == 94.0
    assert pos_short["stop_loss"] == 99.0
    
    # Price moves up to 96.0: SL stays at 99.0
    changed = _update_trailing_stop(pos_short, 96.0, 1.0)
    assert not changed
    assert pos_short["stop_loss"] == 99.0
    
    print("[OK] Trailing Stop Loss Test Passed!")

if __name__ == "__main__":
    test_long_breakout()
    test_fake_breakout_low_volume()
    test_long_rejection()
    test_trailing_stop_loss()
    print("All strategy and trailing stop tests completed successfully!")

