"""
Unit Tests for AI CTO Dashboard Functions
==========================================
Verifies:
1. Chat query interpretation (interpret_chat_query).
2. CEO Executive briefings compilation (generate_ceo_briefing).
3. Capital allocation calculations (calculate_capital_allocations).
4. Hypothesis lists retrieval (get_all_hypotheses).
"""

import os
import sqlite3
import unittest
import research_lab

TEST_DB = "test_cto_ai_research.db"

class TestAICTODashboard(unittest.TestCase):
    def setUp(self):
        # Isolate database
        research_lab.DB_FILE = TEST_DB
        if os.path.exists(TEST_DB):
            try:
                os.remove(TEST_DB)
            except Exception:
                pass
        research_lab.init_db()
        
        # Populate with mock data for testing
        self.populate_mock_data()

    def tearDown(self):
        if os.path.exists(TEST_DB):
            try:
                os.remove(TEST_DB)
            except Exception:
                pass

    def populate_mock_data(self):
        conn = sqlite3.connect(TEST_DB)
        try:
            cursor = conn.cursor()
            
            # 1. Insert strategies
            cursor.executemany("""
                INSERT INTO strategies (id, name, status, current_score)
                VALUES (?, ?, ?, ?);
            """, [
                ("AI-ORB-101", "Opening Range Breakout V1", "Live Candidate", 85.0),
                ("AI-VTP-202", "VWAP Pullback V1", "Paper Trading", 92.0),
                ("AI-MR-303", "Mean Reversion V1", "Rejected", 45.0),
                ("AI-TF-404", "Trend Following V1", "Approved", 78.0)
            ])
            
            # 2. Insert strategy versions
            cursor.executemany("""
                INSERT INTO strategy_versions (id, strategy_id, version, entry_rules, exit_rules, stop_loss_rules, target_rules, sizing_rules)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, [
                (1, "AI-ORB-101", 1, '"ORB Entry"', '"ORB Exit"', '"ORB SL"', '"ORB Target"', '"ORB Sizing"'),
                (2, "AI-VTP-202", 1, '"VTP Entry"', '"VTP Exit"', '"VTP SL"', '"VTP Target"', '"VTP Sizing"'),
                (3, "AI-MR-303", 1, '"MR Entry"', '"MR Exit"', '"MR SL"', '"MR Target"', '"MR Sizing"'),
                (4, "AI-TF-404", 1, '"TF Entry"', '"TF Exit"', '"TF SL"', '"TF Target"', '"TF Sizing"')
            ])
            
            # 3. Insert hypotheses
            cursor.executemany("""
                INSERT INTO strategy_hypotheses (strategy_id, version, pattern_description, assumed_regimes, evidence, reasoning, risks)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """, [
                ("AI-ORB-101", 1, "Breakout of first 15m range high", "trending_up", "Historical 62% win rate", "Local volume surge", "Choppy range whipsaws"),
                ("AI-VTP-202", 1, "Pullback to 20 EMA and VWAP", "trending_up, ranging", "High win consistency", "Mean reversion in local trend", "Sudden momentum reversal"),
                ("AI-MR-303", 1, "RSI overbought reversion", "ranging", "Weak edge observed", "Overbought mean reversion", "Strong trend expansion breakout"),
                ("AI-TF-404", 1, "Moving average crossover", "trending_up", "Solid trend capturing", "Momentum follow", "High decay in chop")
            ])
            
            # 4. Insert backtest results
            cursor.executemany("""
                INSERT INTO backtest_results (version_id, start_date, end_date, profit_factor, max_drawdown, win_rate, total_trades, sharpe_ratio, expectancy, equity_curve, drawdown_curve)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, [
                (1, "2026-05-01", "2026-06-01", 1.45, 1500.0, 60.0, 42, 1.8, 120.0, "[100000, 101200]", "[0, 0]"),
                (2, "2026-05-01", "2026-06-01", 1.82, 1200.0, 65.0, 35, 2.2, 180.0, "[100000, 102400]", "[0, 0]"),
                (3, "2026-05-01", "2026-06-01", 0.82, 4500.0, 40.0, 50, 0.4, -60.0, "[100000, 97000]", "[0, 0]"),
                (4, "2026-05-01", "2026-06-01", 1.25, 2000.0, 52.0, 30, 1.3, 80.0, "[100000, 100800]", "[0, 0]")
            ])
            
            # 5. Insert leaderboard stats
            cursor.executemany("""
                INSERT INTO leaderboard (strategy_id, profit_factor, drawdown, consistency, sharpe_ratio, expectancy, rank)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """, [
                ("AI-VTP-202", 1.82, 1200.0, 65.0, 2.2, 180.0, 1),
                ("AI-ORB-101", 1.45, 1500.0, 60.0, 1.8, 120.0, 2),
                ("AI-TF-404", 1.25, 2000.0, 52.0, 1.3, 80.0, 3)
            ])
            
            # 6. Insert validation results
            cursor.executemany("""
                INSERT INTO validation_results (version_id, score, passed, stability_score)
                VALUES (?, ?, ?, ?);
            """, [
                (1, 85.0, 1, 80.0),
                (2, 92.0, 1, 88.0),
                (3, 40.0, 0, 35.0),
                (4, 78.0, 1, 75.0)
            ])
            
            # 7. Insert paper trade results
            cursor.executemany("""
                INSERT INTO paper_trade_results (strategy_id, version, allocated_capital, current_equity, profit_factor, win_rate, total_trades, sharpe_ratio)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, [
                ("AI-ORB-101", 1, 100000.0, 102400.0, 1.5, 62.0, 15, 1.9),
                ("AI-VTP-202", 1, 100000.0, 104500.0, 1.9, 66.0, 12, 2.3)
            ])
            
            conn.commit()
        finally:
            conn.close()

    def test_interpret_chat_query_best_strategy(self):
        """Verify chat interpreter returns details of the top strategy."""
        reply = research_lab.interpret_chat_query("Show best strategy today")
        self.assertIn("AI-VTP-202", reply["text"])
        self.assertIn("1.82", reply["text"])  # Profit Factor
        self.assertIn("2.20", reply["text"])  # Sharpe

    def test_interpret_chat_query_rejected(self):
        """Verify chat interpreter returns rejected strategy details."""
        reply = research_lab.interpret_chat_query("Why was Strategy rejected?")
        self.assertIn("AI-MR-303", reply["text"])
        self.assertIn("40.0", reply["text"])  # Validation Score

    def test_interpret_chat_query_ready(self):
        """Verify chat interpreter lists ready candidates."""
        reply = research_lab.interpret_chat_query("Show strategies ready for live deployment")
        self.assertIn("AI-VTP-202", reply["text"])

    def test_interpret_chat_query_explain(self):
        """Verify explain query prints details of specific strategy."""
        reply = research_lab.interpret_chat_query("Explain Strategy AI-ORB-101")
        self.assertIn("Breakout of first 15m range high", reply["text"])
        self.assertIn("Choppy range whipsaws", reply["text"])

    def test_ceo_briefing(self):
        """Verify CEO briefing compiles correct summary data fields."""
        brief = research_lab.generate_ceo_briefing()
        self.assertEqual(brief["best_strategy_id"], "AI-VTP-202")
        self.assertEqual(brief["best_strategy_pf"], 1.82)
        self.assertEqual(brief["retire_strategy_id"], "AI-MR-303")
        self.assertEqual(brief["closest_strategy_id"], "AI-VTP-202")
        self.assertEqual(brief["highest_confidence_id"], "AI-VTP-202")
        self.assertIn("optimizing", brief["voice_of_ai"])

    def test_capital_allocations(self):
        """Verify capital allocation splits sum to 100%."""
        allocations = research_lab.calculate_capital_allocations()
        
        total_pct = sum(a["percentage"] for a in allocations)
        self.assertEqual(total_pct, 100, "Allocations must sum exactly to 100%.")
        
        # Cash segment must be present
        cash_segment = next((a for a in allocations if a["strategy_id"] == "CASH"), None)
        self.assertIsNotNone(cash_segment)

    def test_get_all_hypotheses(self):
        """Verify get_all_hypotheses fetches all hypothesis records."""
        hyps = research_lab.get_all_hypotheses()
        self.assertEqual(len(hyps), 4)
        self.assertEqual(hyps[0]["strat_id"], "AI-TF-404")

if __name__ == "__main__":
    unittest.main()
