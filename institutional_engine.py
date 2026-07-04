"""
Institutional-Grade AI Intraday Trading Engine
==============================================
Implements 12 layers of filtering and checks to isolate only high-probability setups.
"""

from strategies import calculate_ema, calculate_vwap, calculate_atr, calculate_adx

class InstitutionalTradingEngine:
    def __init__(self):
        pass

    def detect_regime(self, candles, adx_val, atr_val, ema20_val, ema50_val):
        """Layer 1: Market Regime Detection"""
        if not candles or len(candles) < 30:
            return "Range"
            
        close = candles[-1]["close"]
        
        # Check strong trend
        if adx_val and adx_val >= 25:
            if ema50_val and close > ema50_val and ema20_val and close > ema20_val:
                return "Strong Uptrend"
            elif ema50_val and close < ema50_val and ema20_val and close < ema20_val:
                return "Strong Downtrend"
                
        # Check normal trend
        if adx_val and adx_val >= 18:
            if ema20_val and close > ema20_val:
                return "Uptrend"
            elif ema20_val and close < ema20_val:
                return "Downtrend"
                
        # Check Volatility Expansion / Compression
        atr_vals = calculate_atr(candles, 14)
        if len(atr_vals) >= 24:
            recent_atr = [a for a in atr_vals[-10:] if a is not None]
            if recent_atr:
                avg_atr = sum(recent_atr) / len(recent_atr)
                if atr_val > avg_atr * 1.05:
                    return "Volatility Expansion"
                elif atr_val < avg_atr * 0.95:
                    return "Volatility Compression"
                    
        return "Range"

    def find_pivots(self, candles, n=3):
        """Helper to find swing pivot highs and lows"""
        pivot_highs = []
        pivot_lows = []
        for i in range(n, len(candles) - n):
            is_high = True
            for j in range(i - n, i + n + 1):
                if j != i and candles[j]["high"] > candles[i]["high"]:
                    is_high = False
                    break
            if is_high:
                pivot_highs.append((i, candles[i]["high"]))
                
            is_low = True
            for j in range(i - n, i + n + 1):
                if j != i and candles[j]["low"] < candles[i]["low"]:
                    is_low = False
                    break
            if is_low:
                pivot_lows.append((i, candles[i]["low"]))
        return pivot_highs, pivot_lows

    def check_market_structure(self, candles):
        """Layer 2: Market Structure Engine (HH, HL, LH, LL, BOS, CHOCH)"""
        p_highs, p_lows = self.find_pivots(candles, n=2)
        if len(p_highs) < 2 or len(p_lows) < 2:
            return "Neutral", False, False
            
        ph1 = p_highs[-1][1]
        ph2 = p_highs[-2][1]
        pl1 = p_lows[-1][1]
        pl2 = p_lows[-2][1]
        
        close = candles[-1]["close"]
        structure = "Neutral"
        bos_bullish = False
        bos_bearish = False
        
        # Bullish: Higher High and Higher Low
        if ph1 > ph2 and pl1 > pl2:
            structure = "Bullish"
            if close > ph1:
                bos_bullish = True
        # Bearish: Lower High and Lower Low
        elif ph1 < ph2 and pl1 < pl2:
            structure = "Bearish"
            if close < pl1:
                bos_bearish = True
                
        return structure, bos_bullish, bos_bearish

    def check_vwap(self, candles):
        """Layer 3: VWAP Engine"""
        vwap_vals = calculate_vwap(candles)
        if not vwap_vals or len(vwap_vals) < 5:
            return False, False, 0.0
            
        curr_vwap = vwap_vals[-1]
        prev_vwap = vwap_vals[-5]
        slope = curr_vwap - prev_vwap
        close = candles[-1]["close"]
        
        bullish = close > curr_vwap and slope > 0
        bearish = close < curr_vwap and slope < 0
        return bullish, bearish, slope

    def check_rvol(self, candles):
        """Layer 4: Volume Engine"""
        if len(candles) < 21:
            return 1.0, "Weak"
            
        curr_vol = candles[-1]["volume"]
        avg_vol = sum(c["volume"] for c in candles[-21:-1]) / 20.0
        rvol = curr_vol / avg_vol if avg_vol > 0 else 1.0
        
        if rvol >= 2.0:
            grade = "Very Strong"
        elif rvol >= 1.5:
            grade = "Strong"
        elif rvol >= 1.2:
            grade = "Moderate"
        else:
            grade = "Weak"
        return rvol, grade

    def check_liquidity(self, candles, pdh=None, pdl=None, weekly_high=None, weekly_low=None):
        """Layer 5: Liquidity Engine (Sweeps, False Breakouts)"""
        curr = candles[-1]
        close = curr["close"]
        high = curr["high"]
        low = curr["low"]
        
        # Simple sweep: went past level but closed inside it
        if pdl and low < pdl and close > pdl:
            return "PDL Sweep"
        elif weekly_low and low < weekly_low and close > weekly_low:
            return "Weekly Low Sweep"
        elif pdh and high > pdh and close < pdh:
            return "PDH Sweep"
        elif weekly_high and high > weekly_high and close < weekly_high:
            return "Weekly High Sweep"
        return "None"

    def check_relative_strength(self, stock_candles, nifty_candles):
        """Layer 6: Relative Strength Engine"""
        if not stock_candles or not nifty_candles or len(stock_candles) < 10 or len(nifty_candles) < 10:
            return "Neutral"
            
        stock_change = (stock_candles[-1]["close"] - stock_candles[-10]["close"]) / stock_candles[-10]["close"]
        nifty_change = (nifty_candles[-1]["close"] - nifty_candles[-10]["close"]) / nifty_candles[-10]["close"]
        
        diff = stock_change - nifty_change
        if diff > 0.002:
            return "Strong"
        elif diff < -0.002:
            return "Weak"
        return "Neutral"

    def check_market_breadth(self, nifty_trend):
        """Layer 7: Market Breadth Engine"""
        # Exposes breadth based on index direction trend
        if nifty_trend == "up":
            return "Strong"
        elif nifty_trend == "down":
            return "Weak"
        return "Neutral"

    def check_volatility(self, candles):
        """Layer 8: Volatility Engine"""
        atr_vals = calculate_atr(candles, 14)
        if not atr_vals or len(atr_vals) < 15 or atr_vals[-1] is None:
            return False, 0.0
            
        curr_atr = atr_vals[-1]
        prev_atr = atr_vals[-5] if len(atr_vals) >= 5 and atr_vals[-5] is not None else curr_atr
        expansion = curr_atr > prev_atr * 1.02
        return expansion, curr_atr

    def check_mtf(self, candles_5m, candles_15m, is_long):
        """Layer 9: Multi Timeframe Confirmation"""
        if not candles_15m or len(candles_15m) < 20:
            return True
            
        close_15m = [c["close"] for c in candles_15m]
        ema_15m = calculate_ema(close_15m, 20)
        if not ema_15m or ema_15m[-1] is None:
            return True
            
        aligned = (is_long and close_15m[-1] > ema_15m[-1]) or (not is_long and close_15m[-1] < ema_15m[-1])
        return aligned

    def check_risk_management(self, entry_price, atr, is_long):
        """Layer 10: Risk Management"""
        sl_dist = 1.5 * atr
        if is_long:
            sl = entry_price - sl_dist
            tp = entry_price + (3.0 * atr)  # Preferred 1:3 RR target
        else:
            sl = entry_price + sl_dist
            tp = entry_price - (3.0 * atr)
            
        rr = abs(tp - entry_price) / abs(entry_price - sl) if abs(entry_price - sl) > 0 else 0.0
        return sl, tp, rr

    def run_engine(self, symbol, candles_5m, candles_15m, nifty_trend="neutral", nifty_candles=None, pdh=None, pdl=None, weekly_high=None, weekly_low=None):
        """
        Runs the 12-layer institutional trading system analysis.
        Returns the structured signal output.
        """
        reasons = []
        
        # Guard clause: insufficient candle data
        if not candles_5m or len(candles_5m) < 30:
            return {
                "signal": "NO_TRADE",
                "setup_grade": "IGNORE",
                "confidence": 0,
                "market_regime": "unknown",
                "market_structure": "unknown",
                "entry_price": 0,
                "stop_loss": 0,
                "take_profit": 0,
                "risk_reward": 0,
                "rvol": 0,
                "atr": 0,
                "relative_strength": "Neutral",
                "breadth": "Neutral",
                "liquidity_event": "None",
                "reason": ["Insufficient candle data"]
            }
            
        close = candles_5m[-1]["close"]
        
        # Calculate technical indicators
        close_prices = [c["close"] for c in candles_5m]
        ema20 = calculate_ema(close_prices, 20)[-1]
        ema50 = calculate_ema(close_prices, 50)[-1] if len(candles_5m) >= 50 else None
        adx = calculate_adx(candles_5m, 14)[-1]
        atr_vals = calculate_atr(candles_5m, 14)
        atr = atr_vals[-1] if atr_vals else None
        
        # 1. Market Regime
        regime = self.detect_regime(candles_5m, adx, atr, ema20, ema50)
        
        # 2. Market Structure
        structure, bos_bull, bos_bear = self.check_market_structure(candles_5m)
        
        # 3. VWAP
        vwap_bull, vwap_bear, vwap_slope = self.check_vwap(candles_5m)
        
        # 4. Volume RVOL
        rvol, rvol_grade = self.check_rvol(candles_5m)
        
        # 5. Liquidity
        liq_event = self.check_liquidity(candles_5m, pdh, pdl, weekly_high, weekly_low)
        
        # 6. Relative Strength
        rs = self.check_relative_strength(candles_5m, nifty_candles)
        
        # 7. Breadth
        breadth = self.check_market_breadth(nifty_trend)
        
        # 8. Volatility
        atr_expanding, atr_val = self.check_volatility(candles_5m)
        
        # Determine Trade Direction candidates
        is_long_candidate = close > (calculate_vwap(candles_5m)[-1] if calculate_vwap(candles_5m) else close) and structure == "Bullish" and bos_bull
        is_short_candidate = close < (calculate_vwap(candles_5m)[-1] if calculate_vwap(candles_5m) else close) and structure == "Bearish" and bos_bear
        
        # 9. Multi Timeframe Confirmation
        mtf_aligned = False
        if is_long_candidate:
            mtf_aligned = self.check_mtf(candles_5m, candles_15m, True)
        elif is_short_candidate:
            mtf_aligned = self.check_mtf(candles_5m, candles_15m, False)
            
        # 10. Risk Management levels
        sl, tp, rr = 0.0, 0.0, 0.0
        if atr:
            if is_long_candidate:
                sl, tp, rr = self.check_risk_management(close, atr, True)
            elif is_short_candidate:
                sl, tp, rr = self.check_risk_management(close, atr, False)
                
        # 12. Trade Quality Scoring
        score = 0
        
        # 12.1 Trend Alignment (15 pts)
        trend_aligned = (is_long_candidate and regime in ("Strong Uptrend", "Uptrend")) or (is_short_candidate and regime in ("Strong Downtrend", "Downtrend"))
        if trend_aligned:
            score += 15
        else:
            reasons.append("Trend alignment failed")
            
        # 12.2 VWAP Alignment (15 pts)
        vwap_aligned = (is_long_candidate and vwap_bull) or (is_short_candidate and vwap_bear)
        if vwap_aligned:
            score += 15
        else:
            reasons.append("VWAP slope or price relationship not aligned")
            
        # 12.3 Market Structure (20 pts)
        struct_aligned = (is_long_candidate and structure == "Bullish" and bos_bull) or (is_short_candidate and structure == "Bearish" and bos_bear)
        if struct_aligned:
            score += 20
        else:
            reasons.append("Market structure or break-of-structure (BOS) not aligned")
            
        # 12.4 RVOL (10 pts)
        rvol_aligned = rvol >= 1.5
        if rvol_aligned:
            score += 10
        else:
            reasons.append("Relative volume (RVOL) below 1.5 threshold")
            
        # 12.5 Liquidity Sweep (10 pts)
        sweep_aligned = liq_event != "None"
        if sweep_aligned:
            score += 10
            
        # 12.6 Relative Strength (10 pts)
        rs_aligned = (is_long_candidate and rs == "Strong") or (is_short_candidate and rs == "Weak")
        if rs_aligned:
            score += 10
        else:
            reasons.append("Relative strength benchmark index underperformance")
            
        # 12.7 Market Breadth (10 pts)
        breadth_aligned = (is_long_candidate and breadth == "Strong") or (is_short_candidate and breadth == "Weak")
        if breadth_aligned:
            score += 10
        else:
            reasons.append("Broad market breadth index trend not aligned")
            
        # 12.8 ATR Expansion (5 pts)
        if atr_expanding:
            score += 5
            
        # 12.9 MTF Alignment (5 pts)
        if mtf_aligned:
            score += 5
        else:
            reasons.append("HTF trend filter counter-alignment")
            
        # Classify Setup Grade
        grade = "IGNORE"
        if score >= 95:
            grade = "ELITE"
        elif score >= 90:
            grade = "A+"
        elif score >= 80:
            grade = "A"
        elif score >= 70:
            grade = "B"
            
        # Check no trade conditions
        no_trade = False
        if regime == "Range":
            no_trade = True
            reasons.append("No Trade Condition: Range-bound market regime")
        if rvol < 1.2:
            no_trade = True
            reasons.append("No Trade Condition: RVOL < 1.2 low volume")
        if atr and (atr / close < 0.003):
            no_trade = True
            reasons.append("No Trade Condition: ATR/Price < 0.3% low volatility")
        if rr < 2.0:
            no_trade = True
            reasons.append("No Trade Condition: Risk/Reward ratio < 1:2")
        if score < 80:
            no_trade = True
            reasons.append(f"No Trade Condition: Score {score} below required threshold (>=80)")
            
        signal = "NO_TRADE"
        if not no_trade:
            if is_long_candidate:
                signal = "BUY"
            elif is_short_candidate:
                signal = "SELL"
                
        if signal == "NO_TRADE":
            grade = "IGNORE"
            
        return {
            "signal": signal,
            "setup_grade": grade,
            "confidence": score,
            "market_regime": regime,
            "market_structure": f"{structure} (BOS: {bos_bull or bos_bear})",
            "entry_price": round(close, 2) if signal != "NO_TRADE" else 0.0,
            "stop_loss": round(sl, 2) if signal != "NO_TRADE" else 0.0,
            "take_profit": round(tp, 2) if signal != "NO_TRADE" else 0.0,
            "risk_reward": round(rr, 2) if signal != "NO_TRADE" else 0.0,
            "rvol": round(rvol, 2),
            "atr": round(atr, 4) if atr else 0.0,
            "relative_strength": rs,
            "breadth": breadth,
            "liquidity_event": liq_event,
            "reason": reasons if signal == "NO_TRADE" else ["Elite execution signals aligned"]
        }

if __name__ == "__main__":
    import json
    # Construct a high-probability Elite/A+ Setup mock dataset to verify the engine
    mock_candles_5m = []
    base_price = 2500.0
    for idx in range(40):
        # Create an uptrending price path
        price_inc = idx * 1.5
        mock_candles_5m.append({
            "high": base_price + price_inc + 2.0,
            "low": base_price + price_inc - 1.0,
            "close": base_price + price_inc + 0.5,
            "open": base_price + price_inc,
            "volume": 1000 + (1500 if idx == 39 else 100) # RVOL surge at execution trigger
        })
        
    mock_candles_15m = []
    for idx in range(25):
        price_inc = idx * 4.5
        mock_candles_15m.append({
            "high": base_price + price_inc + 5.0,
            "low": base_price + price_inc - 2.0,
            "close": base_price + price_inc + 1.0,
            "open": base_price + price_inc,
            "volume": 3000
        })

    engine = InstitutionalTradingEngine()
    result = engine.run_engine(
        symbol="RELIANCE",
        candles_5m=mock_candles_5m,
        candles_15m=mock_candles_15m,
        nifty_trend="up",
        nifty_candles=mock_candles_15m,
        pdh=2490.0,
        pdl=2450.0,
        weekly_high=2495.0,
        weekly_low=2440.0
    )
    print(json.dumps(result, indent=2))

