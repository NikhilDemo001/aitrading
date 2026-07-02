"""
Unit and System Tests for the AI Self-Learning Trading Intelligence System
==========================================================================
1. Simulates a mock trading history of exactly 100 trades with mixed outcomes.
2. Verifies that the Q-learning agent discretizes states and updates Q-values correctly.
3. Tests counterfactual Q-learning updates for shadow trades.
4. Verifies the walk-forward validation gate (acceptance and rollback behavior).
5. Validates EOD report generation by the post-trade analysis engine.
"""

import os
import json
import shutil
import unittest
import datetime
from learning_engine import QLearningAgent
from model_validator import validate_model_update
from analysis_engine import analyze_trades_eod

class TestAISelfLearningSystem(unittest.TestCase):
    def setUp(self):
        # Create unique filenames for testing to avoid overwriting real policies
        self.test_policy_path = "test_rl_policy.json"
        self.test_backup_path = "test_rl_policy_backup.json"
        self.test_temp_path = "test_rl_policy_temp.json"
        
        # Clean up any leftover files from previous test runs
        for path in [self.test_policy_path, self.test_backup_path, self.test_temp_path, "daily_learning_report.md"]:
            if os.path.exists(path):
                os.remove(path)
                
        # Initialize an empty policy
        self.agent = QLearningAgent(policy_path=self.test_policy_path)

    def tearDown(self):
        # Clean up files after testing
        for path in [self.test_policy_path, self.test_backup_path, self.test_temp_path, "daily_learning_report.md"]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    def _assert_state_prefix(self, key, prefix):
        """discretize_state appends a run-day weekday bucket (_mon.._fri) and, during F&O expiry
        week, an _expiry flag (learning_engine.py features #9/#10). Those suffixes are wall-clock
        dependent, so assert the stable prefix and validate the suffix shape rather than pinning a
        brittle exact string."""
        self.assertTrue(key.startswith(prefix), f"{key!r} should start with {prefix!r}")
        suffix = key[len(prefix):]
        valid = {f"_{d}{e}" for d in ("mon", "tue", "wed", "thu", "fri") for e in ("", "_expiry")}
        self.assertIn(suffix, valid, f"unexpected weekday/expiry suffix {suffix!r}")

    def test_state_discretization(self):
        """Verify that market contexts are discretized into expected string keys."""
        context = {
            "regime": "trending_up",
            "atr_pct": 0.008,
            "volume_ratio": 1.5,
            "vwap_aligned": True,
            "htf_aligned": True,
            "time": "10:15"
        }
        state_key = self.agent.discretize_state(context)
        self._assert_state_prefix(state_key, "trending_up_normal_normal_yes_yes_morning")

        # Test edge case defaults and out-of-bounds inputs
        bad_context = {
            "regime": "unknown_regime",
            "atr_pct": 0.001,
            "volume_ratio": 0.5,
            "vwap_aligned": False,
            "htf_aligned": False,
            "time": "14:45"
        }
        state_key_bad = self.agent.discretize_state(bad_context)
        self._assert_state_prefix(state_key_bad, "unknown_low_weak_no_no_afternoon")

    def test_state_discretization_with_rsi_adx(self):
        """Verify that state discretization works properly when RSI and ADX are provided."""
        context = {
            "regime": "trending_up",
            "atr_pct": 0.008,
            "volume_ratio": 1.5,
            "vwap_aligned": True,
            "htf_aligned": True,
            "time": "10:15",
            "rsi": 25.0, # oversold
            "adx": 30.0  # strong
        }
        state_key = self.agent.discretize_state(context)
        self._assert_state_prefix(state_key, "trending_up_normal_normal_yes_yes_morning_oversold_strong")

        context_neutral = {
            "regime": "ranging",
            "atr_pct": 0.003,
            "volume_ratio": 1.0,
            "vwap_aligned": False,
            "htf_aligned": False,
            "time": "12:15",
            "rsi": 50.0, # neutral
            "adx": 10.0  # weak
        }
        state_key_neutral = self.agent.discretize_state(context_neutral)
        self._assert_state_prefix(state_key_neutral, "ranging_low_weak_no_no_midday_neutral_weak")

    def test_q_table_lookup_and_updates(self):
        """Test policy initialization, action selection, and TD updates."""
        state_key = "trending_up_normal_strong_yes_yes_morning"
        
        # Unseen state: should initialize defaults with Normal Size (action 2) as greedy choice
        act, mult = self.agent.get_action(state_key)
        self.assertEqual(act, 2)
        self.assertEqual(mult, 1.0)
        self.assertEqual(len(self.agent.q_table[state_key]), 4)
        
        # Test reward calculation
        win_reward = self.agent.calculate_reward(pnl=1500, risk=500, is_win=True)
        # 1500/500 = 3.0. For win: reward = 3.0 + 0.1 = 3.1
        self.assertEqual(win_reward, 3.1)
        
        loss_reward = self.agent.calculate_reward(pnl=-500, risk=500, is_win=False)
        # -500/500 = -1.0. For loss: reward = -1.0 - 0.25 = -1.25
        self.assertEqual(loss_reward, -1.25)
        
        # Update and check Q-value shift
        # initial Q-values: [-0.1, 0.1, 0.2, 0.0]
        # action 2 old value: 0.2
        # update: 0.2 + 0.15 * (3.1 - 0.2) = 0.2 + 0.15 * 2.9 = 0.2 + 0.435 = 0.635
        self.agent.update_q_value(state_key, action=2, reward=win_reward)
        self.assertEqual(self.agent.q_table[state_key][2], 0.635)
        
        # Save and reload policy
        success = self.agent.save_policy()
        self.assertTrue(success)
        self.assertTrue(os.path.exists(self.test_policy_path))
        
        new_agent = QLearningAgent(policy_path=self.test_policy_path)
        self.assertEqual(new_agent.q_table[state_key][2], 0.635)

    def test_shadow_trade_counterfactual_learning(self):
        """Verify that skipped/shadow trades update Q-values correctly using counterfactual rewards."""
        state_key = "ranging_normal_weak_no_no_midday"
        
        # Initial action for unseen state is Normal size (action 2)
        # If we skipped, action is 0 (Skip)
        self.agent.q_table[state_key] = [-0.1, 0.1, 0.2, 0.0]
        
        # Case 1: Skipped trade would have lost (saving capital -> positive reward)
        reward_good_skip = self.agent.calculate_counterfactual_reward(would_win=False)
        self.assertEqual(reward_good_skip, 0.5)
        self.agent.update_q_value(state_key, action=0, reward=reward_good_skip)
        # -0.1 + 0.15 * (0.5 - (-0.1)) = -0.1 + 0.15 * 0.6 = -0.1 + 0.09 = -0.01
        self.assertAlmostEqual(self.agent.q_table[state_key][0], -0.01, places=3)
        
        # Case 2: Skipped trade would have won (lost opportunity -> negative reward)
        reward_bad_skip = self.agent.calculate_counterfactual_reward(would_win=True)
        self.assertEqual(reward_bad_skip, -0.5)

    def test_simulation_100_trades(self):
        """Simulate exactly 100 trades to verify model convergence and walk-forward validation rules."""
        # 1. Generate 100 mock trades with consistent context and outcomes
        # We will define a favorable state (trending_up with strong volume) and an unfavorable state (choppy with low volume)
        fav_context = {
            "regime": "trending_up",
            "atr_pct": 0.008,
            "volume_ratio": 2.0,
            "vwap_aligned": True,
            "htf_aligned": True,
            "time": "10:00"
        }
        unfav_context = {
            "regime": "choppy",
            "atr_pct": 0.018,
            "volume_ratio": 0.8,
            "vwap_aligned": False,
            "htf_aligned": False,
            "time": "12:30"
        }
        
        fav_state_key = self.agent.discretize_state(fav_context)     # trending_up_normal_strong_yes_yes_morning
        unfav_state_key = self.agent.discretize_state(unfav_context) # choppy_high_weak_no_no_midday
        
        trade_history = []
        today_str = datetime.date.today().isoformat()
        
        # Create a mix of 100 trades: 70% In-Sample (training), 30% Out-of-Sample (testing)
        for i in range(100):
            is_fav = (i % 2 == 0) # alternate between favorable and unfavorable setups
            
            # Setup base trade fields
            symbol = "RELIANCE" if is_fav else "TCS"
            strategy = "MomentumBreakout" if is_fav else "MeanReversion"
            direction = "LONG" if is_fav else "SHORT"
            quantity = 100
            entry_price = 2500.0 if is_fav else 3500.0
            
            if is_fav:
                # Favorable state wins 80% of the time
                is_win = (i % 10 < 8)
                pnl = 1500.0 if is_win else -500.0
                risk = 500.0
                market_context = fav_context
                regime = "trending_up"
            else:
                # Unfavorable state loses 80% of the time
                is_win = (i % 10 < 2)
                pnl = 1000.0 if is_win else -1000.0
                risk = 1000.0
                market_context = unfav_context
                regime = "choppy"
                
            trade_history.append({
                "symbol": symbol,
                "strategy": strategy,
                "direction": direction,
                "quantity": quantity,
                "entry_price": entry_price,
                "exit_price": entry_price + (pnl / quantity),
                "entry_time": f"{today_str}T10:00:00",
                "exit_time": f"{today_str}T11:00:00",
                "pnl": pnl,
                "reason": "TARGET-2 HIT" if is_win else "STOP LOSS",
                "regime": regime,
                "htf_trend": "bullish" if is_fav else "bearish",
                "atr_at_entry": 5.0,
                "market_context": market_context,
                "holding_minutes": 60.0,
                "is_shadow_trade": False
            })

        # 2. Train Proposed Agent on the first 70 trades (In-Sample training)
        agent_proposed = QLearningAgent(policy_path=self.test_temp_path)
        for t in trade_history[:70]:
            state_key = agent_proposed.discretize_state(t["market_context"])
            # Get model action
            act_id, mult = agent_proposed.get_action(state_key)
            # Calculate reward
            is_win = t["pnl"] > 0
            risk_amount = abs(t["pnl"]) if not is_win else abs(t["pnl"]) / 3.0 # mock risk
            reward = agent_proposed.calculate_reward(t["pnl"], risk_amount, is_win)
            # Update proposed model
            agent_proposed.update_q_value(state_key, act_id, reward)
            
        agent_proposed.save_policy()

        # Create current base policy (before updates - untrained/default)
        agent_current = QLearningAgent(policy_path=self.test_policy_path)
        agent_current.save_policy()

        # 3. Test walk-forward validation (Out-of-Sample)
        # Because agent_proposed has learned that fav_state is highly profitable (will increase/maintain sizing)
        # and unfav_state is highly unprofitable (will reduce sizing to Skip/Half), it should outperform
        # the untrained current agent which defaults to Normal sizing.
        approved = validate_model_update(trade_history, self.test_temp_path, self.test_policy_path)
        
        # Verify validation output (should be approved because learning system improved outcomes)
        self.assertTrue(approved, "Proposed policy should be approved because it learns to reduce exposure on losing setups.")

        # Let's test a degenerate scenario where we check rejection
        # We will create a broken model that recommends skipping winning trades
        agent_bad = QLearningAgent(policy_path="test_rl_policy_bad.json")
        for state_key in list(agent_proposed.q_table.keys()):
            # Force Skip action (0) to have high Q-value, and Normal/Double to have negative values for favorable setups
            if "trending_up" in state_key:
                agent_bad.q_table[state_key] = [5.0, -10.0, -10.0, -10.0]
            else:
                agent_bad.q_table[state_key] = [0.0, 0.0, 0.0, 0.0]
        agent_bad.save_policy()

        # Validate updating from proposed (good) to bad policy: must be rejected!
        approved_bad = validate_model_update(trade_history, "test_rl_policy_bad.json", self.test_temp_path)
        self.assertFalse(approved_bad, "Model validator must reject a degraded policy.")
        
        if os.path.exists("test_rl_policy_bad.json"):
            os.remove("test_rl_policy_bad.json")

    def test_eod_analysis_report(self):
        """Verify that the EOD analysis runs and generates the markdown report correctly."""
        today_str = datetime.date.today().isoformat()
        
        mock_trades = [
            {
                "symbol": "RELIANCE",
                "strategy": "MomentumBreakout",
                "direction": "LONG",
                "quantity": 100,
                "entry_price": 2500.0,
                "exit_price": 2515.0,
                "entry_time": f"{today_str}T09:45:00",
                "exit_time": f"{today_str}T10:15:00",
                "pnl": 1500.0,
                "reason": "TARGET-2 HIT",
                "regime": "trending_up",
                "htf_trend": "bullish",
                "atr_at_entry": 10.0,
                "market_context": {"volume_ratio": 2.0, "atr_pct": 0.005, "regime": "trending_up"},
                "holding_minutes": 30.0
            },
            {
                "symbol": "TCS",
                "strategy": "MeanReversionBuy",
                "direction": "LONG",
                "quantity": 50,
                "entry_price": 3500.0,
                "exit_price": 3480.0,
                "entry_time": f"{today_str}T11:15:00",
                "exit_time": f"{today_str}T11:45:00",
                "pnl": -1000.0,
                "reason": "STOP LOSS",
                "regime": "choppy",
                "htf_trend": "neutral",
                "atr_at_entry": 12.0,
                "market_context": {"volume_ratio": 0.8, "atr_pct": 0.006, "regime": "choppy", "rsi": 75.0},
                "holding_minutes": 30.0
            }
        ]

        # Trigger analysis
        analyze_trades_eod(mock_trades, report_dir=".")
        
        # Verify file exists and has content
        report_path = "daily_learning_report.md"
        self.assertTrue(os.path.exists(report_path))
        
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Check for key sections
        self.assertIn("Daily AI Learning Report", content)
        self.assertIn("Session Performance", content)
        self.assertIn("Strengths Detected", content)
        self.assertIn("Mistakes & Patterns Identified", content)
        self.assertIn("Actionable Lessons Learned", content)
        
        # Check if rsi mistake was diagnosed (buy entry with overbought RSI)
        self.assertIn("Entered long with overbought RSI", content)

    def test_batch_train_from_db(self):
        """Verify that batch_train_from_db loads trades and updates Q-values."""
        import sqlite3
        test_db = "test_batch_train.db"
        if os.path.exists(test_db):
            os.remove(test_db)
            
        # Create test db and live_trades table
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE live_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                strategy TEXT,
                direction TEXT,
                quantity INTEGER,
                entry_price REAL,
                entry_time TEXT,
                exit_price REAL,
                exit_time TEXT,
                pnl REAL,
                reason TEXT,
                regime TEXT,
                htf_trend TEXT,
                is_fno INTEGER,
                contract TEXT,
                atr_at_entry REAL,
                market_context TEXT,
                holding_minutes REAL,
                mae REAL,
                mfe REAL,
                confluence_score INTEGER,
                trigger_level_source TEXT,
                trigger_level_price REAL,
                trigger_level_score REAL,
                is_shadow_trade INTEGER
            );
        """)
        
        # Insert mock trades
        context_1 = json.dumps({"regime": "trending_up", "atr_pct": 0.008, "volume_ratio": 1.5, "vwap_aligned": True, "htf_aligned": True, "time": "10:15"})
        context_2 = json.dumps({"regime": "ranging", "atr_pct": 0.003, "volume_ratio": 1.0, "vwap_aligned": False, "htf_aligned": False, "time": "12:15"})
        
        cursor.execute("""
            INSERT INTO live_trades (symbol, strategy, direction, quantity, entry_price, entry_time, pnl, market_context, is_shadow_trade)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, ("RELIANCE", "ORB-Buy", "LONG", 10, 2500.0, "2026-06-16T10:15:00", 500.0, context_1, 0))
        
        cursor.execute("""
            INSERT INTO live_trades (symbol, strategy, direction, quantity, entry_price, entry_time, pnl, market_context, is_shadow_trade)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, ("TCS", "VWAP-Short", "SHORT", 5, 3800.0, "2026-06-16T12:15:00", -200.0, context_2, 1))
        
        conn.commit()
        conn.close()
        
        try:
            # Run batch training
            count = self.agent.batch_train_from_db(db_path=test_db)
            self.assertEqual(count, 2, "Should train on exactly 2 trades.")
            
            # Verify Q-table has the states
            state_key_1 = self.agent.discretize_state(json.loads(context_1))
            state_key_2 = self.agent.discretize_state(json.loads(context_2))
            
            self.assertIn(state_key_1, self.agent.q_table)
            self.assertIn(state_key_2, self.agent.q_table)
        finally:
            if os.path.exists(test_db):
                os.remove(test_db)

if __name__ == "__main__":
    unittest.main()
