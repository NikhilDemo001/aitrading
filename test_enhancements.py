import time
import asyncio
from datetime import datetime, timedelta
import unittest
from unittest.mock import MagicMock, AsyncMock, call, patch

from upstox_client import RateLimiter
from backtester import run_backtest
import main

class TestBotEnhancements(unittest.TestCase):
    def setUp(self):
        import research_lab
        research_lab.init_db()

    def test_rate_limiter(self):
        """Verify that RateLimiter limits requests and spaces them correctly."""
        limiter = RateLimiter(max_calls=5, period=0.2)
        start = time.time()
        for _ in range(7):
            limiter.wait()
        end = time.time()
        elapsed = end - start
        # 5 calls execute immediately, 6th and 7th wait for sliding window (0.2s)
        self.assertGreaterEqual(elapsed, 0.2)

    def test_backtester_slippage(self):
        """Verify that slippage reduces long trade returns and increases short trade losses."""
        # Mock strategy that fires a single buy signal
        def dummy_strategy(window, config=None, htf_trend="neutral"):
            if len(window) == 2:
                return {
                    "strategy": "Dummy-Buy",
                    "entry_price": 100.0,
                    "stop_loss": 90.0,
                    "target_1": 110.0,
                    "target_2": 120.0,
                    "trigger_time": "10:00"
                }
            return None

        # Two candles: one to trigger signal, one to hit stop loss
        candles = [
            {"timestamp": "2024-01-01 10:00", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"timestamp": "2024-01-01 10:05", "open": 98, "high": 99, "low": 85, "close": 90, "volume": 1000}
        ]

        # Costs are zeroed here so this test isolates SLIPPAGE (its stated purpose). run_backtest
        # now applies a transaction-cost model by default (flat brokerage + statutory charges) —
        # covered separately — which would otherwise add ~₹40.95/round-trip on top of these numbers.
        # Run without slippage
        trades_no_slip, _ = run_backtest(dummy_strategy, candles, max_risk=100, warmup=1, slippage_pct=0.0, brokerage_flat=0.0, charge_pct=0.0)
        # Run with 1% slippage
        trades_slip, _ = run_backtest(dummy_strategy, candles, max_risk=100, warmup=1, slippage_pct=0.01, brokerage_flat=0.0, charge_pct=0.0)

        self.assertEqual(len(trades_no_slip), 1)
        self.assertEqual(len(trades_slip), 1)

        # Without slippage: entry=100, exit=pos.stop=90. Risk=10. Qty=100/10=10. P&L = (90 - 100) * 10 = -100
        # With slippage:
        # entry = 100 * 1.01 = 101.
        # exit = 90 * 0.99 = 89.1.
        # P&L = (89.1 - 101) * 10 = -119
        self.assertEqual(trades_no_slip[0]["pnl"], -100.0)
        self.assertEqual(trades_slip[0]["pnl"], -119.0)
        self.assertEqual(trades_slip[0]["entry"], 101.0)
        self.assertEqual(trades_slip[0]["exit"], 89.1)

    def test_time_stop_exit(self):
        """Verify that time-stop exits trigger when a position is open past the limit."""
        # Save old state
        old_active = main.active_positions.copy()
        old_config = main.client.config.copy()
        old_execute_exit = main.execute_exit
        
        try:
            # Enable time stop in config
            main.client.config["enable_time_stop"] = True
            main.client.config["time_stop_minutes"] = 15
            
            # Setup a position opened 20 minutes ago
            entry_time = (main.get_ist_now() - timedelta(minutes=20)).isoformat()
            main.active_positions = {
                "RELIANCE": {
                    "symbol": "RELIANCE",
                    "instrument_key": "NSE_EQ|INE002A01018",
                    "is_fno": False,
                    "strategy": "VWAP-Pullback-Buy",
                    "direction": "LONG",
                    "quantity": 10,
                    "entry_price": 2400.0,
                    "entry_time": entry_time,
                    "stop_loss": 2350.0,
                    "target": 2450.0,
                    "target_2": 2500.0,
                    "t1_hit": False,
                    "current_price": 2400.0,
                    "pnl": 0.0,
                    "trailing_high": 2400.0,
                    "mfe": 0.0,
                    "mae": 0.0,
                    "order_id": "MOCK-1"
                }
            }
            
            # Mock execute_exit and client.get_market_quotes
            main.execute_exit = AsyncMock()
            
            quotes = {
                "NSE_EQ|INE002A01018": {"ltp": 2405.0}
            }
            
            # Run position manager
            asyncio.run(main.manage_existing_positions(paper_trading=True, trailing_enabled=False, trailing_mult=1.5, quotes=quotes))
            
            # Verify that exit was triggered with TIME STOP
            main.execute_exit.assert_called_once()
            args = main.execute_exit.call_args[0]
            self.assertEqual(args[0], "RELIANCE") # symbol
            self.assertEqual(args[3], "TIME STOP") # reason
            
            # Verify position was removed
            self.assertNotIn("RELIANCE", main.active_positions)
            
        finally:
            # Restore state
            main.active_positions = old_active
            main.client.config = old_config
            main.execute_exit = old_execute_exit

    def test_vix_filter_active(self):
        """Verify that when VIX is elevated, target distances are scaled down by 20% and confluence gate is incremented."""
        # Mock client's get_market_quote for VIX to return > 22.0
        old_get_market_quote = main.client.get_market_quote
        old_get_intraday_candles = main.client.get_intraday_candles
        old_select_best_strategy = main.select_best_strategy
        old_evaluate_signal = main.evaluate_signal
        old_execute_entry = main.execute_entry
        old_config = main.client.config.copy()
        
        try:
            # get_market_quote now serves two callers in the scan path: the India VIX read AND the
            # M4 slippage guard's fresh price for the scanned stock. Return the elevated VIX only
            # for the VIX key, and the signal's price (100) for the stock so the slippage guard
            # (>0.3% drift) doesn't spuriously reject a signal that hasn't actually moved.
            def _quote(key, *a, **k):
                return {"ltp": 25.0} if "India VIX" in str(key) else {"ltp": 100.0}
            main.client.get_market_quote = MagicMock(side_effect=_quote)  # Elevated VIX, stable stock price
            # Full OHLCV candles (newer scan/indicator code reads high/low/open, not just close).
            mock_candles = [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000,
                             "timestamp": f"2026-06-15 10:{i:02d}"} for i in range(40)]
            main.client.get_intraday_candles = MagicMock(return_value=mock_candles)
            
            signal = {
                "strategy": "ORB-Buy",
                "entry_price": 100.0,
                "stop_loss": 95.0,
                "target_1": 110.0,
                "target_2": 120.0,
                "confidence": 85
            }
            main.select_best_strategy = MagicMock(return_value=signal)
            main.evaluate_signal = MagicMock(return_value=(True, "ok", {"confluence_score": 5}))
            main.execute_entry = AsyncMock()
            main.active_positions = {}  # Clear active positions to ensure RELIANCE is scanned
            main.client.config["enable_full_market_scan"] = False  # Disable full market scan to isolate the test
            main.client.config["enable_fno"] = False
            main.client.config["enable_time_filter"] = False
            main.client.config["watchlist"] = ["RELIANCE"]
            main.client.config["min_confluence_score"] = 4
            
            # Run scan_for_entries
            asyncio.run(main.scan_for_entries(watchlist=["RELIANCE"], max_positions=3, paper_trading=True))
            
            # Verify that VIX target scaling was applied:
            # target_1: 100 + (110 - 100)*0.8 = 108
            # target_2: 100 + (120 - 100)*0.8 = 116
            main.execute_entry.assert_called_once()
            called_signal = main.execute_entry.call_args[0][2]
            self.assertEqual(called_signal["target_1"], 108.0)
            self.assertEqual(called_signal["target_2"], 116.0)
            
            # Verify that evaluate_signal was called with min_confluence_score of 5 (4 + 1)
            main.evaluate_signal.assert_called_once()
            called_cfg = main.evaluate_signal.call_args[0][5]
            self.assertEqual(called_cfg["min_confluence_score"], 5)
            
        finally:
            main.client.get_market_quote = old_get_market_quote
            main.client.get_intraday_candles = old_get_intraday_candles
            main.select_best_strategy = old_select_best_strategy
            main.evaluate_signal = old_evaluate_signal
            main.execute_entry = old_execute_entry
            main.client.config = old_config

    def test_limit_order_entry(self):
        """Verify that execute_entry places a LIMIT order with 0.1x ATR buffer."""
        old_place_order = main.client.place_order
        old_config = main.client.config.copy()
        
        try:
            import research_lab
            old_allocations = research_lab.calculate_capital_allocations
            research_lab.calculate_capital_allocations = MagicMock(return_value=[])
            
            main.client.config["paper_trading"] = False  # To trigger the place_order call branch
            main.client.config["enable_fno"] = False
            main.client.config["enable_kelly_sizing"] = False
            main.client.config["enable_one_percent_risk"] = False
            main.client.config["max_risk_per_trade"] = 500.0
            
            main.client.place_order = MagicMock(return_value={"order_id": "TEST-LIMIT-1", "price": 100.5})
            
            signal = {
                "strategy": "ORB-Buy",
                "entry_price": 100.0,
                "stop_loss": 95.0,
                "target_1": 110.0,
                "target_2": 120.0,
                "atr": 5.0
            }
            
            # Run execute_entry for a Buy order. Patch get_ist_now into the trading window so the
            # mandatory RiskManager gate (which enforces the no-new-trade-after window) doesn't
            # reject the order when this unit test happens to run outside market hours.
            candles = [{"timestamp": "2024-01-01 10:00", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1000}]
            with patch.object(main, "get_ist_now", lambda: datetime(2026, 6, 15, 10, 0, 0)):
                asyncio.run(main.execute_entry("RELIANCE", "NSE_EQ|INE002A01018", signal, candles=candles, paper_trading=False))
            
            # Buy limit price should be entry_price + 0.1 * ATR = 100.0 + 0.1 * 5.0 = 100.5
            self.assertEqual(
                main.client.place_order.call_args_list[0],
                call("RELIANCE", "BUY", 100, "LIMIT", 100.5, tag="autobot", instrument_key=None)
            )
            
        finally:
            main.client.place_order = old_place_order
            main.client.config = old_config
            research_lab.calculate_capital_allocations = old_allocations

    def test_adaptive_trailing_stop_multiplier(self):
        """Verify that India VIX changes scale trailing ATR stop multiplier appropriately."""
        old_vix = main.vix_value
        old_get_ist_now = main.get_ist_now
        try:
            # Morning: scale only by VIX
            main.get_ist_now = lambda: datetime(2026, 6, 15, 10, 0, 0)
            
            pos = {
                "entry_price": 100.0,
                "target": 115.0,
                "target_2": 130.0,
                "t1_hit": False,
                "rvol": 1.0,
                "entry_time": "2026-06-15T09:50:00"  # 10 minutes elapsed (no time decay)
            }
            # High VIX (> 22.0): trailing stop is widened by 1.467x (e.g. 1.5 -> 2.2)
            main.vix_value = 25.0
            self.assertEqual(main.get_adaptive_trailing_multiplier(1.5, pos, 105.0), 2.2)
            
            # Low VIX (< 14.0): trailing stop is tightened by 0.8x (e.g. 1.5 -> 1.2)
            main.vix_value = 12.0
            self.assertEqual(main.get_adaptive_trailing_multiplier(1.5, pos, 105.0), 1.2)
            
            # Normal VIX (between 14.0 and 22.0): no scaling (returns base multiplier)
            main.vix_value = 16.0
            self.assertEqual(main.get_adaptive_trailing_multiplier(1.5, pos, 105.0), 1.5)
            
            # Afternoon: scale by VIX and then multiply by 0.6
            main.get_ist_now = lambda: datetime(2026, 6, 15, 14, 30, 0)
            pos["entry_time"] = "2026-06-15T14:20:00"  # 10 minutes elapsed (no time decay, only afternoon 0.6x)
            
            # Normal VIX in afternoon: should tighten by 0.6x (1.5 * 0.6 = 0.9)
            main.vix_value = 16.0
            self.assertEqual(main.get_adaptive_trailing_multiplier(1.5, pos, 105.0), 0.9)
        finally:
            main.vix_value = old_vix
            main.get_ist_now = old_get_ist_now

    def test_sector_concentration_filter(self):
        """Verify that open positions cap concurrent entries from the same industry sector."""
        old_active = main.active_positions.copy()
        old_config = main.client.config.copy()
        old_get_market_quote = main.client.get_market_quote
        old_get_intraday_candles = main.client.get_intraday_candles
        old_select_best_strategy = main.select_best_strategy
        old_evaluate_signal = main.evaluate_signal
        old_execute_entry = main.execute_entry
        old_get_instrument_info = main.client.get_instrument_info
        
        try:
            main.client.config["enable_full_market_scan"] = False
            main.client.config["enable_nifty_filter"] = False
            main.client.config["enable_sector_filter"] = True
            main.client.config["enable_time_filter"] = False
            main.client.config["max_open_positions_per_sector"] = 1
            main.client.config["watchlist"] = ["INFY", "RELIANCE"]
            
            # 1. Place a TCS position which is in "IT" sector
            main.active_positions = {
                "TCS": {
                    "symbol": "TCS",
                    "instrument_key": "NSE_EQ|INE467B01029",
                    "is_fno": False,
                    "strategy": "ORB-Buy",
                    "direction": "LONG",
                    "quantity": 10,
                    "entry_price": 3000.0,
                    "entry_time": main.get_ist_now().isoformat(),
                    "stop_loss": 2950.0,
                    "target": 3050.0,
                    "t1_hit": False,
                    "current_price": 3000.0,
                    "pnl": 0.0,
                    "trailing_high": 3000.0,
                    "mfe": 0.0,
                    "mae": 0.0,
                    "order_id": "MOCK-IT-1"
                }
            }
            
            # Mock scanner and signal evaluation to simulate normal positive entry signals
            main.client.get_market_quote = MagicMock(return_value={"ltp": 100.0})
            # Full OHLCV candles (newer scan/indicator code reads high/low/open, not just close).
            mock_candles = [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000,
                             "timestamp": f"2026-06-15 10:{i:02d}"} for i in range(40)]
            main.client.get_intraday_candles = MagicMock(return_value=mock_candles)
            main.client.get_instrument_info = MagicMock(return_value={
                "instrument_key": "NSE_EQ|MOCK",
                "lot_size": 1,
                "tick_size": 0.05
            })
            
            signal = {
                "strategy": "ORB-Buy",
                "entry_price": 100.0,
                "stop_loss": 95.0,
                "target_1": 110.0,
                "target_2": 120.0,
                "confidence": 85,
                "atr": 5.0
            }
            main.select_best_strategy = MagicMock(return_value=signal)
            main.evaluate_signal = MagicMock(return_value=(True, "ok", {"confluence_score": 5}))
            main.execute_entry = AsyncMock()
            
            # Scan for entry on INFY (IT sector, same as TCS) -> Should be blocked by sector limit!
            asyncio.run(main.scan_for_entries(watchlist=["INFY"], max_positions=3, paper_trading=True))
            main.execute_entry.assert_not_called()
            
            # Scan for entry on RELIANCE (OIL_GAS sector, different from TCS) -> Should NOT be blocked!
            asyncio.run(main.scan_for_entries(watchlist=["RELIANCE"], max_positions=3, paper_trading=True))
            main.execute_entry.assert_called_once()

            # Reset mocks
            main.execute_entry.reset_mock()

            # Place a DENORA position (unmapped, defaults to "OTHER" sector)
            main.active_positions["DENORA"] = {
                "symbol": "DENORA",
                "instrument_key": "NSE_EQ|MOCK_DENORA",
                "is_fno": False,
                "strategy": "ORB-Buy",
                "direction": "LONG",
                "quantity": 10,
                "entry_price": 100.0,
                "entry_time": main.get_ist_now().isoformat(),
                "stop_loss": 95.0,
                "target": 105.0,
                "t1_hit": False,
                "current_price": 100.0,
                "pnl": 0.0,
                "trailing_high": 100.0,
                "mfe": 0.0,
                "mae": 0.0,
                "order_id": "MOCK-OTHER-1"
            }

            # Scan for entry on SPAL (also unmapped, defaults to "OTHER" sector) -> Should NOT be blocked!
            asyncio.run(main.scan_for_entries(watchlist=["SPAL"], max_positions=3, paper_trading=True))
            main.execute_entry.assert_called_once()
            
        finally:
            main.active_positions = old_active
            main.client.config = old_config
            main.client.get_market_quote = old_get_market_quote
            main.client.get_intraday_candles = old_get_intraday_candles
            main.select_best_strategy = old_select_best_strategy
            main.evaluate_signal = old_evaluate_signal
            main.execute_entry = old_execute_entry
            main.client.get_instrument_info = old_get_instrument_info

    def test_fno_mode_entry(self):
        """Verify that F&O mode executes entry orders correctly on futures contracts and scales SL/targets."""
        old_get_future_for = main.client.get_future_for
        old_place_order = main.client.place_order
        old_get_market_quote = main.client.get_market_quote
        old_config = main.client.config.copy()
        
        try:
            import research_lab
            old_allocations = research_lab.calculate_capital_allocations
            research_lab.calculate_capital_allocations = MagicMock(return_value=[])
            
            # 1. Enable F&O mode and configure risk parameters
            main.client.config["enable_fno"] = True
            main.client.config["paper_trading"] = False  # trigger live order path
            main.client.config["enable_kelly_sizing"] = False
            main.client.config["enable_one_percent_risk"] = False
            main.client.config["fno_max_risk_per_trade"] = 2000.0
            main.client.config["fno_max_lots"] = 1
            
            # Mock get_future_for to return a mock contract with lot_size 100
            main.client.get_future_for = MagicMock(return_value={
                "instrument_key": "NSE_FO|12345",
                "lot_size": 100,
                "trading_symbol": "RELIANCE26JUNFUT",
                "expiry_date": "2026-06-26"
            })
            
            # Mock get_market_quote for the futures contract to return a premium price of 1015.0 (spot is 1000.0)
            # This simulates a spread premium of 15.0 Rs
            def mock_get_market_quote(instrument_key):
                if instrument_key == "NSE_FO|12345":
                    return {"ltp": 1015.0}
                return {"ltp": 1000.0}
            main.client.get_market_quote = MagicMock(side_effect=mock_get_market_quote)
            
            # Mock place_order to return the filled order details at the premium price
            main.client.place_order = MagicMock(return_value={
                "order_id": "TEST-FNO-LIMIT-1",
                "price": 1015.2, # filled price with a slight 0.2 slippage
                "status": "FILLED"
            })
            
            signal = {
                "strategy": "ORB-Buy",
                "entry_price": 1000.0, # spot entry price
                "stop_loss": 980.0,    # spot stop loss (20 Rs risk)
                "target_1": 1040.0,
                "target_2": 1060.0,
                "atr": 10.0
            }
            
            candles = [{"timestamp": "2024-01-01 10:00", "open": 1000.0, "high": 1000.0, "low": 1000.0, "close": 1000.0, "volume": 1000}]
            
            main.active_positions = {}
            # Run execute_entry for a Buy order (in trading window so the RiskManager gate allows it)
            with patch.object(main, "get_ist_now", lambda: datetime(2026, 6, 15, 10, 0, 0)):
                asyncio.run(main.execute_entry("RELIANCE", "NSE_EQ|INE002A01018", signal, candles=candles, paper_trading=False))
            
            # 2. Assert that place_order was called on the futures contract key, with quantity = lot_size (1 lot = 100 qty)
            # Limit price should be futures_ltp + 0.1 * ATR = 1015.0 + 0.1 * 10 = 1016.0
            self.assertEqual(
                main.client.place_order.call_args_list[0],
                call("RELIANCE", "BUY", 100, "LIMIT", 1016.0, tag="autobot", instrument_key="NSE_FO|12345")
            )
            
            # 3. Assert that the active position has been saved, and stop loss / targets shifted by basis offset
            # Basis offset = fill_price (1015.2) - spot_entry (1000.0) = 15.2
            # New stop loss = 980.0 + 15.2 = 995.2
            # New target_1 = 1040.0 + 15.2 = 1055.2
            # New target_2 = 1060.0 + 15.2 = 1075.2
            self.assertIn("RELIANCE", main.active_positions)
            pos = main.active_positions["RELIANCE"]
            self.assertEqual(pos["instrument_key"], "NSE_FO|12345")
            self.assertTrue(pos["is_fno"])
            self.assertEqual(pos["entry_price"], 1015.2)
            self.assertEqual(pos["stop_loss"], 995.2)
            self.assertEqual(pos["target"], 1055.2)
            self.assertEqual(pos["target_2"], 1075.2)
            
        finally:
            main.client.get_future_for = old_get_future_for
            main.client.place_order = old_place_order
            main.client.get_market_quote = old_get_market_quote
            main.client.config = old_config
            main.active_positions = {}
            research_lab.calculate_capital_allocations = old_allocations

    def test_momentum_exit(self):
        """Verify that momentum exit triggers when close goes below both 9 EMA and VWAP for LONG position."""
        old_config = main.client.config.copy()
        old_active = main.active_positions.copy()
        old_execute_exit = main.execute_exit
        
        try:
            main.client.config["enable_momentum_exit"] = True
            
            # Setup a LONG position with ema_9 and vwap indicators
            main.active_positions = {
                "RELIANCE": {
                    "symbol": "RELIANCE",
                    "instrument_key": "NSE_EQ|INE002A01018",
                    "is_fno": False,
                    "direction": "LONG",
                    "quantity": 10,
                    "entry_price": 2500.0,
                    "stop_loss": 2480.0,
                    "target": 2530.0,
                    "target_2": 2560.0,
                    "t1_hit": False,
                    "ema_9": 2510.0,
                    "vwap": 2505.0
                }
            }
            
            # LTP above both indicators -> Should NOT exit
            quotes = {"NSE_EQ|INE002A01018": {"ltp": 2512.0}}
            main.execute_exit = AsyncMock()
            asyncio.run(main.manage_existing_positions(paper_trading=True, trailing_enabled=False, trailing_mult=1.5, quotes=quotes))
            main.execute_exit.assert_not_called()
            
            # LTP below both indicators -> Should exit
            quotes = {"NSE_EQ|INE002A01018": {"ltp": 2502.0}}
            asyncio.run(main.manage_existing_positions(paper_trading=True, trailing_enabled=False, trailing_mult=1.5, quotes=quotes))
            main.execute_exit.assert_called_once()
            self.assertEqual(main.execute_exit.call_args[0][3], "MOMENTUM EXIT (9EMA/VWAP CROSS)")
            
        finally:
            main.client.config = old_config
            main.active_positions = old_active
            main.execute_exit = old_execute_exit

    def test_breakeven_buffer(self):
        """Verify that breakeven buffer moves stop loss to entry_price + buffer on Target 1 hit."""
        old_config = main.client.config.copy()
        old_active = main.active_positions.copy()
        old_place_order = main.client.place_order
        
        try:
            main.client.config["enable_partial_exit_t1"] = True
            main.client.config["breakeven_buffer_pct"] = 0.001 # 0.1% buffer
            main.client.config["partial_exit_t1_pct"] = 0.50
            
            # Setup a LONG position
            main.active_positions = {
                "RELIANCE": {
                    "symbol": "RELIANCE",
                    "instrument_key": "NSE_EQ|INE002A01018",
                    "is_fno": False,
                    "direction": "LONG",
                    "quantity": 10,
                    "entry_price": 2000.0,
                    "stop_loss": 1950.0,
                    "target": 2050.0,
                    "target_2": 2100.0,
                    "t1_hit": False,
                    "lot_size": 1
                }
            }
            
            main.client.place_order = MagicMock(return_value={"price": 2050.0, "status": "filled"})
            
            # Hit Target 1 (LTP 2050.0) -> Moves SL to Break-even (2000) + 0.1% buffer (2) = 2002.0
            quotes = {"NSE_EQ|INE002A01018": {"ltp": 2050.0}}
            asyncio.run(main.manage_existing_positions(paper_trading=True, trailing_enabled=False, trailing_mult=1.5, quotes=quotes))
            
            pos = main.active_positions["RELIANCE"]
            self.assertTrue(pos["t1_hit"])
            self.assertEqual(pos["stop_loss"], 2002.0)
            
        finally:
            main.client.config = old_config
            main.active_positions = old_active
            main.client.place_order = old_place_order

    def test_options_mode_entry(self):
        """Verify that F&O Options mode executes entry orders correctly on CE/PE contracts."""
        old_get_option_for = main.client.get_option_for
        old_place_order = main.client.place_order
        old_get_market_quote = main.client.get_market_quote
        old_config = main.client.config.copy()
        
        try:
            import research_lab
            old_allocations = research_lab.calculate_capital_allocations
            research_lab.calculate_capital_allocations = MagicMock(return_value=[])
            
            # Enable F&O options mode
            main.client.config["enable_fno"] = True
            main.client.config["fno_type"] = "OPT"
            main.client.config["option_delta"] = 0.50
            main.client.config["paper_trading"] = False
            main.client.config["enable_kelly_sizing"] = False
            main.client.config["enable_one_percent_risk"] = False
            main.client.config["fno_max_risk_per_trade"] = 1000.0
            main.client.config["fno_max_lots"] = 1
            
            # Mock get_option_for
            main.client.get_option_for = MagicMock(return_value={
                "instrument_key": "NSE_FO|98913",
                "lot_size": 100,
                "trading_symbol": "RELIANCE 1000 CE 26 JUN 26",
                "expiry_date": "2026-06-26",
                "strike_price": 1000.0,
                "option_type": "CE"
            })
            
            # Mock get_market_quote for option contract
            main.client.get_market_quote = MagicMock(return_value={"ltp": 50.0})
            
            # Mock place_order
            main.client.place_order = MagicMock(return_value={
                "order_id": "TEST-OPT-1",
                "price": 50.0,
                "status": "FILLED"
            })
            
            signal = {
                "strategy": "ORB-Buy",
                "entry_price": 1000.0, # spot
                "stop_loss": 980.0,    # spot (20 Rs risk)
                "target_1": 1040.0,
                "target_2": 1060.0,
                "atr": 10.0
            }
            
            candles = [{"timestamp": "2024-01-01 10:00", "open": 1000.0, "high": 1000.0, "low": 1000.0, "close": 1000.0, "volume": 1000}]
            main.active_positions = {}

            with patch.object(main, "get_ist_now", lambda: datetime(2026, 6, 15, 10, 0, 0)):
                asyncio.run(main.execute_entry("RELIANCE", "NSE_EQ|INE002A01018", signal, candles=candles, paper_trading=False))
            
            # Expected option levels:
            # Option SL = 50.0 - 0.50 * (1000.0 - 980.0) = 40.0
            # Option Target = 50.0 + 0.50 * (1040.0 - 1000.0) = 70.0
            # Option Target 2 = 50.0 + 0.50 * (1060.0 - 1000.0) = 80.0
            
            self.assertIn("RELIANCE", main.active_positions)
            pos = main.active_positions["RELIANCE"]
            self.assertEqual(pos["instrument_key"], "NSE_FO|98913")
            self.assertTrue(pos["is_fno"])
            self.assertEqual(pos["entry_price"], 50.0)
            self.assertEqual(pos["stop_loss"], 40.0)
            self.assertEqual(pos["target"], 70.0)
            self.assertEqual(pos["target_2"], 80.0)
            self.assertEqual(pos["direction"], "LONG")
            
        finally:
            main.client.get_option_for = old_get_option_for
            main.client.place_order = old_place_order
            main.client.get_market_quote = old_get_market_quote
            main.client.config = old_config
            main.active_positions = {}
            research_lab.calculate_capital_allocations = old_allocations

    def test_get_option_for_lookup(self):
        """Verify that get_option_for correctly returns the closest strike ATM option contract."""
        # get_option_for filters out expired contracts (expiry_date > today), so use expiries
        # relative to the run date rather than hardcoded dates that eventually fall into the past
        # (which is what made this test brittle). near = next week's expiry, far = a month later.
        from datetime import date, timedelta
        near = (date.today() + timedelta(days=7)).isoformat()
        far = (date.today() + timedelta(days=37)).isoformat()
        main.client.options_map = {
            "RELIANCE": [
                {"instrument_key": "NSE_FO|1", "trading_symbol": "RELIANCE 990 CE", "expiry_date": near, "strike_price": 990.0, "option_type": "CE"},
                {"instrument_key": "NSE_FO|2", "trading_symbol": "RELIANCE 1000 CE", "expiry_date": near, "strike_price": 1000.0, "option_type": "CE"},
                {"instrument_key": "NSE_FO|3", "trading_symbol": "RELIANCE 1010 CE", "expiry_date": near, "strike_price": 1010.0, "option_type": "CE"},
                {"instrument_key": "NSE_FO|4", "trading_symbol": "RELIANCE 1000 PE", "expiry_date": near, "strike_price": 1000.0, "option_type": "PE"},
                {"instrument_key": "NSE_FO|5", "trading_symbol": "RELIANCE 1000 CE", "expiry_date": far, "strike_price": 1000.0, "option_type": "CE"},
            ]
        }
        
        # Spot price 998, should return CE closest strike 1000 for nearest expiry 2026-06-25
        opt = main.client.get_option_for("RELIANCE", "CE", 998.0)
        self.assertIsNotNone(opt)
        self.assertEqual(opt["instrument_key"], "NSE_FO|2")
        self.assertEqual(opt["strike_price"], 1000.0)
        
        # Spot price 998, PE option type should return PE closest strike 1000 for nearest expiry
        opt_pe = main.client.get_option_for("RELIANCE", "PE", 998.0)
        self.assertIsNotNone(opt_pe)
        self.assertEqual(opt_pe["instrument_key"], "NSE_FO|4")

    def test_max_capacity_position_sizing(self):
        """Verify that enable_max_capacity calculates quantities correctly using leverage and buffer."""
        # leverage_multiplier set explicitly so this test is deterministic regardless of the
        # code's default (which was intentionally lowered from 5x to 4x for cash MIS safety).
        config = {
            "enable_max_capacity": True,
            "capacity_buffer_pct": 0.05,
            "leverage_multiplier": 5.0
        }

        # 1. Cash Equities (5x leverage, 5% buffer):
        # Margin: 10000, Leverage: 5x, Buffer: 5% -> Buying Power: 10000 * 5.0 * 0.95 = 47500
        # Price: 1000 -> qty = 47500 / 1000 = 47 shares
        qty_cash = main._calc_quantity(1000.0, 980.0, config, available_margin=10000.0, is_fno=False, is_options=False)
        self.assertEqual(qty_cash, 47)
        
        # 2. Options (1x leverage, 5% buffer, rounded to lot_size=100):
        # Margin: 10000, Leverage: 1x, Buffer: 5% -> Buying Power: 10000 * 1.0 * 0.95 = 9500
        # Premium: 50 -> qty = 9500 / 50 = 190. Rounded down to lot size 100 = 100 shares
        qty_opt = main._calc_quantity(50.0, 40.0, config, available_margin=10000.0, is_fno=True, is_options=True, lot_size=100)
        self.assertEqual(qty_opt, 100)
        
        # 3. Futures (5x leverage, 5% buffer, rounded to lot_size=100):
        # Margin: 10000, Leverage: 5x, Buffer: 5% -> Buying Power: 10000 * 5.0 * 0.95 = 47500
        # Price: 1000 -> qty = 47500 / 1000 = 47. Rounded down to lot size 100 = 100 (floored to lot_size)
        qty_fut = main._calc_quantity(1000.0, 980.0, config, available_margin=10000.0, is_fno=True, is_options=False, lot_size=100)
        self.assertEqual(qty_fut, 100)

if __name__ == "__main__":
    unittest.main()
