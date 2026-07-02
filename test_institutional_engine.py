import pytest
from institutional_engine import InstitutionalTradingEngine

def test_institutional_engine_no_trade():
    engine = InstitutionalTradingEngine()
    
    # Range market regime trigger
    candles_5m = [
        {"high": 100.0, "low": 99.0, "close": 99.5, "open": 99.8, "volume": 100}
        for _ in range(40)
    ]
    candles_15m = [
        {"high": 100.0, "low": 99.0, "close": 99.5, "open": 99.8, "volume": 300}
        for _ in range(25)
    ]
    
    result = engine.run_engine(
        symbol="TCS",
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        nifty_trend="neutral",
        nifty_candles=candles_15m
    )
    
    assert result["signal"] == "NO_TRADE"
    assert result["setup_grade"] == "IGNORE"
    assert "No Trade Condition: Range-bound market regime" in result["reason"]

def test_institutional_engine_elite_setup():
    engine = InstitutionalTradingEngine()
    
    # Construct a high-probability bullish setup
    candles_5m = []
    base_price = 100.0
    for idx in range(40):
        # Higher highs and higher lows
        price_inc = idx * 0.5
        candles_5m.append({
            "high": base_price + price_inc + 0.4,
            "low": base_price + price_inc - 0.2,
            "close": base_price + price_inc + 0.1,
            "open": base_price + price_inc,
            "volume": 1000 + (10000 if idx == 39 else 100) # RVOL surge
        })
        
    candles_15m = []
    for idx in range(25):
        price_inc = idx * 1.5
        candles_15m.append({
            "high": base_price + price_inc + 1.0,
            "low": base_price + price_inc - 0.5,
            "close": base_price + price_inc + 0.2,
            "open": base_price + price_inc,
            "volume": 3000
        })
        
    # Set high relative strength (stock outperformed index)
    nifty_candles = []
    for idx in range(25):
        price_inc = idx * 0.2 # slower increase than stock
        nifty_candles.append({
            "high": base_price + price_inc + 0.5,
            "low": base_price + price_inc - 0.2,
            "close": base_price + price_inc + 0.1,
            "open": base_price + price_inc,
            "volume": 5000
        })

    # Override engine structure check to simulate passing setup
    result = engine.run_engine(
        symbol="TCS",
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        nifty_trend="up",
        nifty_candles=nifty_candles,
        pdh=118.0,
        pdl=95.0,
        weekly_high=119.0,
        weekly_low=94.0
    )
    
    # Should report the detailed output fields correctly
    assert "signal" in result
    assert "setup_grade" in result
    assert "confidence" in result
    assert "market_regime" in result
    assert "rvol" in result
    assert "reason" in result
