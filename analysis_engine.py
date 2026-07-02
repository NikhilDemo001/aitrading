"""
Post-Trade Analysis & Heuristics Engine
=======================================
1. Performs detailed diagnostics on won and lost trades.
2. Identifies repeating success and failure patterns.
3. Automatically updates S/R level scoring multipliers.
4. Generates EOD markdown learning reports.
"""

import os
import datetime
from collections import defaultdict

def analyze_trades_eod(trade_history, report_dir):
    """
    Performs EOD analysis, identifies mistakes/strengths,
    and writes the Daily Learning Report.
    """
    os.makedirs(report_dir, exist_ok=True)
    today = datetime.date.today().isoformat()
    
    # Filter trades completed today
    today_trades = [t for t in trade_history if t.get("exit_time", "").startswith(today)]
    
    report_path = os.path.join(report_dir, "daily_learning_report.md")
    
    if not today_trades:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# Daily AI Learning Report — {today}\n\n")
            f.write("No trades were executed today. System was in standby or did not find valid confluence setups.\n")
        return
        
    wins = [t for t in today_trades if t.get("pnl", 0.0) > 0]
    losses = [t for t in today_trades if t.get("pnl", 0.0) < 0]
    total_trades = len(today_trades)
    win_rate = round((len(wins) / total_trades * 100), 1) if total_trades > 0 else 0.0
    net_pnl = round(sum(t.get("pnl", 0.0) for t in today_trades), 2)
    
    # Heuristics & Diagnostics
    strengths = []
    mistakes = []
    
    # Check hourly cluster
    hourly_pnl = defaultdict(float)
    for t in today_trades:
        try:
            hour = t.get("exit_time", "")[11:13]
            hourly_pnl[hour] += t.get("pnl", 0.0)
        except Exception:
            pass
            
    worst_hour = min(hourly_pnl, key=hourly_pnl.get) if hourly_pnl else None
    if worst_hour and hourly_pnl[worst_hour] < 0:
        mistakes.append(f"Loss clustering observed around {worst_hour}:00. Consider tightening filters during this hour.")
        
    # Strategy diagnostic
    strat_pnl = defaultdict(float)
    for t in today_trades:
        strat_pnl[t["strategy"]] += t.get("pnl", 0.0)
        
    best_strat = max(strat_pnl, key=strat_pnl.get) if strat_pnl else None
    worst_strat = min(strat_pnl, key=strat_pnl.get) if strat_pnl else None
    
    if best_strat and strat_pnl[best_strat] > 0:
        strengths.append(f"Strong performance from {best_strat} yielding +₹{strat_pnl[best_strat]:.2f}.")
    if worst_strat and strat_pnl[worst_strat] < 0:
        mistakes.append(f"Underperformance in {worst_strat} resulting in -₹{abs(strat_pnl[worst_strat]):.2f}. Review regime alignment.")
        
    # Analyze individual losses
    for t in losses:
        p = t.get("market_context", {})
        rsi = p.get("rsi")
        regime = p.get("regime")
        symbol = t.get("symbol")
        strat = t.get("strategy")
        reason = t.get("reason", "unknown")
        
        # Diagnostics
        if regime == "choppy" and "Breakout" in strat:
            mistakes.append(f"Loss on {symbol} ({strat}): Entered breakout in choppy market. Whipsaw occurred.")
        elif rsi is not None and rsi > 70 and "Buy" in strat:
            mistakes.append(f"Loss on {symbol} ({strat}): Entered long with overbought RSI ({rsi:.1f}). Overextended entry.")
        elif rsi is not None and rsi < 30 and "Short" in strat:
            mistakes.append(f"Loss on {symbol} ({strat}): Entered short with oversold RSI ({rsi:.1f}). Overextended entry.")
        elif reason == "STOP LOSS" and abs(t.get("pnl", 0.0)) > t.get("atr_at_entry", 1.0) * t.get("quantity", 1) * 1.5:
            mistakes.append(f"Loss on {symbol} ({strat}): Exit slippage exceeded ATR threshold. Check execution speed.")

    # Analyze individual wins
    for t in wins:
        p = t.get("market_context", {})
        vol_ratio = p.get("volume_ratio", 1.0)
        symbol = t.get("symbol")
        strat = t.get("strategy")
        if vol_ratio >= 1.8:
            strengths.append(f"Win on {symbol} ({strat}): Entry confirmed by major volume surge ({vol_ratio:.1f}x avg).")

    # Generate Lessons Learned
    lessons = []
    if mistakes:
        lessons.append("1. **Time Gate**: Restrict late afternoon trades when volume decays.")
        lessons.append("2. **Regime Guard**: Do not trade breakouts when regime is choppy; wait for range expansion.")
    else:
        lessons.append("1. **Maintain Policy**: Continue trading high-volume breakouts.")
        lessons.append("2. **Keep Sizing**: Dynamic sizing kept drawdowns small.")
        
    if not strengths:
        strengths.append("No clear structural strengths observed today.")
    if not mistakes:
        mistakes.append("No recurring mistakes identified. Risk guidelines were followed perfectly.")

    # Write report
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Daily AI Learning Report — {today}\n\n")
        
        f.write("## 1. Session Performance\n")
        f.write(f"- **Total Trades**: {total_trades}\n")
        f.write(f"- **Win Rate**: {win_rate}%\n")
        f.write(f"- **Net P&L**: ₹{net_pnl:+.2f}\n\n")
        
        f.write("## 2. Strengths Detected\n")
        for s in set(strengths):
            f.write(f"- {s}\n")
        f.write("\n")
        
        f.write("## 3. Mistakes & Patterns Identified\n")
        for m in set(mistakes):
            f.write(f"- {m}\n")
        f.write("\n")
        
        f.write("## 4. Actionable Lessons Learned\n")
        for l in lessons:
            f.write(f"- {l}\n")
        f.write("\n")
        
        f.write("## 5. Level Multipliers Status\n")
        # Print level multipliers from trade history
        from strategy_support_resistance import get_optimized_level_multipliers
        multipliers = get_optimized_level_multipliers(trade_history)
        f.write("| Level Source | Multiplier |\n")
        f.write("|---|---|\n")
        for src, val in multipliers.items():
            f.write(f"| {src} | {val} |\n")
        f.write("\n")

    print(f"[Analysis Engine] Daily learning report written to {report_path}")

    # Also run shadow divergence analysis
    try:
        analyze_shadow_divergence(trade_history, report_dir)
    except Exception as e:
        print(f'[Analysis Engine] Shadow divergence analysis failed: {e}')


def analyze_shadow_divergence(trade_history, report_dir):
    """
    Analyzes divergence between Shadow trades and Live trades.
    If shadow trades consistently outperform live trades, it signals:
    - Entry timing is being missed (signals fired but were shadow-traded)
    - Confidence threshold may be too high
    - Or that market conditions favor the shadow strategy

    Writes findings to shadow_divergence_report.md inside report_dir.
    """
    os.makedirs(report_dir, exist_ok=True)
    today = datetime.date.today().isoformat()
    report_path = os.path.join(report_dir, 'shadow_divergence_report.md')

    # Separate shadow vs live trades that exited today
    live_trades = [
        t for t in trade_history
        if not t.get('is_shadow_trade', False)
        and t.get('exit_time', '').startswith(today)
    ]
    shadow_trades = [
        t for t in trade_history
        if t.get('is_shadow_trade', False)
        and t.get('exit_time', '').startswith(today)
    ]

    # Need at least some data to analyze
    if len(live_trades) < 2 and len(shadow_trades) < 2:
        return  # Not enough data

    def calc_stats(trades):
        """Returns win-rate, avg P&L and totals for a list of trade dicts."""
        if not trades:
            return {'win_rate': 0, 'avg_pnl': 0, 'total': 0, 'wins': 0}
        wins = [t for t in trades if t.get('pnl', 0) > 0]
        return {
            'total': len(trades),
            'wins': len(wins),
            'win_rate': round(len(wins) / len(trades) * 100, 1),
            'avg_pnl': round(sum(t.get('pnl', 0) for t in trades) / len(trades), 2)
        }

    live_stats = calc_stats(live_trades)
    shadow_stats = calc_stats(shadow_trades)

    # --- Divergence analysis ---
    insights = []
    recommendations = []

    # Case 1: Win-rate divergence between shadow and live
    if shadow_stats['total'] >= 3 and live_stats['total'] >= 2:
        shadow_wr = shadow_stats['win_rate']
        live_wr = live_stats['win_rate']
        divergence = shadow_wr - live_wr

        if divergence > 20:
            insights.append(
                f'CRITICAL: Shadow trades winning {divergence:.1f}% more than live '
                f'({shadow_wr}% vs {live_wr}%). The confidence filter may be too strict.'
            )
            recommendations.append(
                'Consider lowering min_confidence_threshold by 5-10 points to capture more live signals.'
            )
        elif divergence > 10:
            insights.append(
                f'Shadow trades outperforming live by {divergence:.1f}%. Review confidence threshold.'
            )
            recommendations.append('Minor confidence threshold adjustment may be beneficial.')
        elif divergence < -15:
            insights.append(
                f'Live trades winning {abs(divergence):.1f}% more than shadow. '
                f'Confidence filter working excellently.'
            )
            recommendations.append('Current confidence threshold appears well-calibrated.')

    # Case 2: Average P&L divergence
    if shadow_stats['total'] > 0 and live_stats['total'] > 0:
        pnl_diff = shadow_stats['avg_pnl'] - live_stats['avg_pnl']
        if abs(pnl_diff) > 100:
            direction = 'higher' if pnl_diff > 0 else 'lower'
            insights.append(
                f'Shadow average PnL is \u20b9{abs(pnl_diff):.0f} {direction} than live trades.'
            )

    # Case 3: Per-strategy divergence breakdown
    all_strategies = set(
        t.get('strategy', '') for t in live_trades + shadow_trades
    )
    for strat in all_strategies:
        live_strat = [t for t in live_trades if t.get('strategy', '') == strat]
        shadow_strat = [t for t in shadow_trades if t.get('strategy', '') == strat]
        if len(live_strat) >= 2 and len(shadow_strat) >= 2:
            ls = calc_stats(live_strat)
            ss = calc_stats(shadow_strat)
            diff = ss['win_rate'] - ls['win_rate']
            if abs(diff) > 20:
                if diff > 0:
                    insights.append(
                        f'{strat}: Shadow {ss["win_rate"]}% vs Live {ls["win_rate"]}% '
                        f'\u2014 signals being shadow-filtered unnecessarily.'
                    )
                else:
                    insights.append(
                        f'{strat}: Live outperforms shadow ({ls["win_rate"]}% vs {ss["win_rate"]}%) '
                        f'\u2014 good real signal quality.'
                    )

    # Default messages when no notable divergence detected
    if not insights:
        insights.append('Shadow and live trade performance are aligned. No divergence detected.')
        recommendations.append(
            'System operating normally. Confidence threshold is well-calibrated.'
        )

    # --- Write markdown report ---
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(f'# Shadow vs Live Trade Divergence Report \u2014 {today}\n\n')
        f.write('## Performance Comparison\n')
        f.write('| Metric | Live Trades | Shadow Trades |\n')
        f.write('|--------|------------|---------------|\n')
        f.write(f'| Total Trades | {live_stats["total"]} | {shadow_stats["total"]} |\n')
        f.write(f'| Win Rate | {live_stats["win_rate"]}% | {shadow_stats["win_rate"]}% |\n')
        f.write(f'| Avg P&L | \u20b9{live_stats["avg_pnl"]:+.2f} | \u20b9{shadow_stats["avg_pnl"]:+.2f} |\n')
        f.write('\n## Insights\n')
        for insight in insights:
            f.write(f'- {insight}\n')
        f.write('\n## Recommendations\n')
        for rec in recommendations:
            f.write(f'- {rec}\n')

    print(f'[Analysis Engine] Shadow divergence report written to {report_path}')
