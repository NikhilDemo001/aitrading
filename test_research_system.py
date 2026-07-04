"""
Unit and System Tests for the AI Research Lab Module
====================================================
1. Verifies SQLite database schema initialization.
2. Tests strategy discovery (Stage 0: Idea Generated).
3. Tests strategy backtesting (Stage 1: Backtesting).
4. Tests out-of-sample validation (Stage 2 & 3: Promotion or Rejection).
5. Tests daily paper trading ticks (Stage 4: Cost friction & metrics).
6. Tests strategy evolution (V1 -> V2 parameter mutations).
7. Tests Battle Arena tournaments (Round matching and bracket winners).
8. Recalibrates leaderboards and logs research journals.
"""

import os
import sqlite3
import unittest
import research_lab

TEST_DB = "test_ai_research.db"

class TestAIResearchLab(unittest.TestCase):
    def setUp(self):
        # Override the database filename in the module to isolate tests
        research_lab.DB_FILE = TEST_DB
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        research_lab.init_db()

    def tearDown(self):
        # Clean up database after test execution
        if os.path.exists(TEST_DB):
            try:
                os.remove(TEST_DB)
            except Exception:
                pass

    def test_database_initialization(self):
        """Verify that SQLite table structures exist and contain required columns."""
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.cursor()
        
        tables = [
            "strategies", "strategy_versions", "strategy_parameters", 
            "strategy_hypotheses", "backtest_results", "walkforward_results", 
            "validation_results", "paper_trade_results", "paper_trade_logs", 
            "live_trade_results", "research_journal", "learning_events", 
            "ai_improvements", "strategy_comparisons", "market_regimes", 
            "leaderboard"
        ]
        
        for table in tables:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}';")
            row = cursor.fetchone()
            self.assertIsNotNone(row, f"Table '{table}' was not created in the database.")
            
        conn.close()

    def test_strategy_discovery_engine(self):
        """Verify that candidate strategies are successfully generated and versioned."""
        ids = research_lab.discover_strategies(count=3)
        self.assertEqual(len(ids), 3, "Should generate exactly 3 strategies.")
        
        # Verify strategy fields
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, status FROM strategies WHERE id = ?;", (ids[0],))
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[2], "Idea Generated", "Discovered strategies must default to 'Idea Generated' status.")
        
        # Verify version 1 exists
        cursor.execute("SELECT version FROM strategy_versions WHERE strategy_id = ?;", (ids[0],))
        v_row = cursor.fetchone()
        self.assertIsNotNone(v_row)
        self.assertEqual(v_row[0], 1)
        
        # Verify parameters exist
        cursor.execute("""
            SELECT count(*) FROM strategy_parameters sp
            JOIN strategy_versions sv ON sv.id = sp.version_id
            WHERE sv.strategy_id = ?;
        """, (ids[0],))
        param_cnt = cursor.fetchone()[0]
        self.assertGreater(param_cnt, 0, "Parameters should be created for the strategy.")
        
        # Verify hypothesis exists
        cursor.execute("SELECT pattern_description FROM strategy_hypotheses WHERE strategy_id = ?;", (ids[0],))
        h_row = cursor.fetchone()
        self.assertIsNotNone(h_row)
        
        conn.close()

    def test_backtesting_and_validation(self):
        """Test strategy execution sandbox from backtesting through walk-forward validation."""
        ids = research_lab.discover_strategies(count=2)
        strat_id = ids[0]
        
        # Backtest (Stage 1)
        v_id = research_lab.backtest_strategy(strat_id, version=1)
        self.assertIsNotNone(v_id)
        
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.cursor()
        
        # Check backtest results saved
        cursor.execute("SELECT profit_factor, sharpe_ratio FROM backtest_results WHERE version_id = ?;", (v_id,))
        bt_row = cursor.fetchone()
        self.assertIsNotNone(bt_row)
        self.assertGreater(bt_row[0], 0.0)
        
        # Check strategy status changed to Backtesting
        cursor.execute("SELECT status FROM strategies WHERE id = ?;", (strat_id,))
        self.assertEqual(cursor.fetchone()[0], "Backtesting")
        
        # Validate (Stage 2 & 3)
        passed = research_lab.validate_strategy(strat_id, version=1)
        
        # Check validation tables filled
        cursor.execute("SELECT score FROM validation_results WHERE version_id = ?;", (v_id,))
        val_row = cursor.fetchone()
        self.assertIsNotNone(val_row)
        
        # Check final status
        cursor.execute("SELECT status FROM strategies WHERE id = ?;", (strat_id,))
        expected_status = "Paper Trading" if passed else "Rejected"
        self.assertEqual(cursor.fetchone()[0], expected_status)
        
        conn.close()

    def test_paper_trading_simulator(self):
        """Verify that active paper trading strategies update metrics and log transactions."""
        ids = research_lab.discover_strategies(count=1)
        strat_id = ids[0]
        
        # Bootstrap strategy to pass validation and enter Paper Trading status
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.cursor()
        
        # Manually set status to Paper Trading and add initial results
        cursor.execute("UPDATE strategies SET status = 'Paper Trading' WHERE id = ?;", (strat_id,))
        cursor.execute("INSERT INTO paper_trade_results (strategy_id, version, allocated_capital, current_equity) VALUES (?, 1, 100000.0, 100000.0);", (strat_id,))
        cursor.execute("INSERT INTO strategy_versions (strategy_id, version, entry_rules, exit_rules, stop_loss_rules, target_rules, sizing_rules) VALUES (?, 1, '{}', '{}', '{}', '{}', '{}');", (strat_id,))
        v_id = cursor.lastrowid
        cursor.execute("INSERT INTO backtest_results (version_id, start_date, end_date, total_trades, win_rate, profit_factor, sharpe_ratio, max_drawdown, expectancy, equity_curve, drawdown_curve) VALUES (?, '2026-01-01', '2026-03-01', 50, 60.0, 1.5, 1.5, 2000.0, 200.0, '[]', '[]');", (v_id,))
        conn.commit()
        
        # Trigger paper trade ticks
        research_lab.simulate_paper_trades_daily()
        
        # Verify logs were populated
        cursor.execute("SELECT count(*) FROM paper_trade_logs WHERE strategy_id = ?;", (strat_id,))
        log_cnt = cursor.fetchone()[0]
        self.assertGreater(log_cnt, 0, "Paper trade logs should be recorded.")
        
        # Verify results equity changed
        cursor.execute("SELECT current_equity, total_trades FROM paper_trade_results WHERE strategy_id = ?;", (strat_id,))
        res = cursor.fetchone()
        self.assertIsNotNone(res)
        self.assertNotEqual(res[0], 100000.0, "Equity curve should update on transactions.")
        self.assertEqual(res[1], log_cnt)
        
        conn.close()

    def test_evolution_engine(self):
        """Test strategy mutation parameter updates and version increments."""
        ids = research_lab.discover_strategies(count=1)
        strat_id = ids[0]
        
        # Evolve V1 -> V2
        new_version = research_lab.evolve_strategy(strat_id)
        self.assertEqual(new_version, 2, "Evolution should increment version to V2.")
        
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.cursor()
        
        # Check new version row created
        cursor.execute("SELECT count(*) FROM strategy_versions WHERE strategy_id = ?;", (strat_id,))
        self.assertEqual(cursor.fetchone()[0], 2)
        
        # Check status reset to Backtesting
        cursor.execute("SELECT status FROM strategies WHERE id = ?;", (strat_id,))
        self.assertEqual(cursor.fetchone()[0], "Backtesting")
        
        # Check improvements logs
        cursor.execute("SELECT observation, improvement FROM ai_improvements WHERE strategy_id = ?;", (strat_id,))
        imp_row = cursor.fetchone()
        self.assertIsNotNone(imp_row)
        self.assertIn("whipsaws", imp_row[0])
        
        conn.close()

    def test_battle_arena_and_rankings(self):
        """Test tournament matches, leaderboard rankings, and research journals."""
        ids = research_lab.discover_strategies(count=4)
        
        # Simulate backtests so they have scores for ranking
        for sid in ids:
            research_lab.backtest_strategy(sid, version=1)
            
        # Run battle arena tournament (Bracket: 4 -> 2 -> 1)
        winner = research_lab.run_battle_arena(tournament_id="test_tournament", strategy_ids=ids)
        self.assertIn(winner, ids, "Winner must be one of the contenders.")
        
        conn = sqlite3.connect(TEST_DB)
        cursor = conn.cursor()
        
        # Verify comparisons logged
        cursor.execute("SELECT count(*) FROM strategy_comparisons WHERE tournament_id = ?;", ("test_tournament",))
        self.assertEqual(cursor.fetchone()[0], 3, "4-strategy tournament should produce exactly 3 comparison matches.")
        
        # Recalculate leaderboard
        research_lab.generate_daily_journal()
        
        # Verify leaderboard rows exist
        cursor.execute("SELECT count(*) FROM leaderboard;")
        self.assertEqual(cursor.fetchone()[0], 4, "Leaderboard should rank all strategies.")
        
        # Verify journal logged
        cursor.execute("SELECT count(*) FROM research_journal;")
        self.assertGreater(cursor.fetchone()[0], 0)
        
        conn.close()


class TestWalkforwardGate(unittest.TestCase):
    """Pure-function tests for the walk-forward promotion gate (no DB, no candles)."""

    def test_profit_factor(self):
        self.assertEqual(research_lab._profit_factor([]), 1.0)
        self.assertEqual(research_lab._profit_factor([{"pnl": 300.0}]), 300.0)  # no losses -> gross profit
        self.assertAlmostEqual(research_lab._profit_factor([{"pnl": 300.0}, {"pnl": -150.0}]), 2.0)

    def test_gate_passes_healthy_walkforward(self):
        self.assertTrue(research_lab.walkforward_gate(5, 3, 4000.0, is_pf=1.6, oos_pf=1.3))

    def test_gate_rejects_insample_loser(self):
        # Out-of-sample looks great, but the strategy lost money in-sample: luck, not edge.
        self.assertFalse(research_lab.walkforward_gate(5, 3, 4000.0, is_pf=0.7, oos_pf=1.5))

    def test_gate_rejects_thin_or_unprofitable_oos(self):
        self.assertFalse(research_lab.walkforward_gate(2, 3, 4000.0, is_pf=1.5, oos_pf=1.5))   # thin IS
        self.assertFalse(research_lab.walkforward_gate(5, 1, 4000.0, is_pf=1.5, oos_pf=1.5))   # thin OOS
        self.assertFalse(research_lab.walkforward_gate(5, 3, -500.0, is_pf=1.5, oos_pf=1.5))   # OOS loss
        self.assertFalse(research_lab.walkforward_gate(5, 3, 4000.0, is_pf=1.5, oos_pf=1.05))  # weak OOS PF


if __name__ == "__main__":
    unittest.main()
