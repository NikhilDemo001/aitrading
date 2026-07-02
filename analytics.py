"""
Session analytics and performance metrics.
Called at end-of-day and via the /api/analytics endpoint.
"""


def calculate_metrics(trades):
    """
    Computes core performance metrics from a list of trade dicts.
    Each trade must have a 'pnl' key.
    """
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "total_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "expectancy": 0.0,
            "recovery_factor": 0.0,
            "risk_reward": 0.0,
        }

    pnls = [t.get("pnl", 0.0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    win_rate = len(wins) / len(pnls) * 100
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    expectancy = (win_rate / 100) * avg_win - (1 - win_rate / 100) * avg_loss
    risk_reward = avg_win / avg_loss if avg_loss > 0 else 0.0

    # Sharpe ratio (trade-level, annualised assuming ~250 trading days, ~20 trades/day)
    if len(pnls) > 1:
        avg = sum(pnls) / len(pnls)
        variance = sum((p - avg) ** 2 for p in pnls) / len(pnls)
        std = variance ** 0.5
        sharpe = (avg / std) * (5000 ** 0.5) if std > 0 else 0.0  # sqrt(250 days * 20 trades)
    else:
        sharpe = 0.0

    # Maximum drawdown (on cumulative PnL curve)
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for p in pnls:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_drawdown:
            max_drawdown = dd

    total_pnl = sum(pnls)
    recovery_factor = total_pnl / max_drawdown if max_drawdown > 0 else 0.0

    return {
        "total_trades": len(trades),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999.0,
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown": round(max_drawdown, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round(expectancy, 2),
        "recovery_factor": round(recovery_factor, 2),
        "risk_reward": round(risk_reward, 2),
    }


def analyze_by_strategy(trades):
    """Break down metrics per strategy."""
    groups = {}
    for t in trades:
        key = t.get("strategy", "Unknown")
        groups.setdefault(key, []).append(t)
    return {s: calculate_metrics(ts) for s, ts in groups.items()}


def analyze_by_symbol(trades):
    """Break down metrics per symbol."""
    groups = {}
    for t in trades:
        key = t.get("symbol", "Unknown")
        groups.setdefault(key, []).append(t)
    return {s: calculate_metrics(ts) for s, ts in groups.items()}


def _generate_recommendations(metrics, by_strategy, mae_mfe=None):
    recs = []

    if metrics["total_trades"] < 3:
        recs.append("Insufficient trades for statistical conclusions. Continue monitoring.")
        return recs

    if metrics["win_rate"] < 40:
        recs.append(
            f"Win rate {metrics['win_rate']}% is below 40%. "
            "Review entry filters — signals may be triggering too early or in choppy conditions."
        )

    if 0 < metrics["profit_factor"] < 1.0:
        recs.append(
            f"Profit factor {metrics['profit_factor']} is below 1.0 (losing money overall). "
            "Consider widening take-profit targets or tightening stop losses."
        )

    if metrics["max_drawdown"] > 0 and metrics["total_pnl"] > 0:
        if metrics["max_drawdown"] > metrics["total_pnl"] * 2:
            recs.append(
                "Drawdown is more than 2× net profit. Reduce position size or add a max-consecutive-loss halt."
            )

    if metrics["risk_reward"] > 0 and metrics["risk_reward"] < 1.0:
        recs.append(
            f"Average risk/reward {metrics['risk_reward']} is below 1:1. "
            "Targets are being hit less than stops — consider using tighter stops or wider targets."
        )

    for strategy, m in by_strategy.items():
        if m["total_trades"] >= 3 and m["win_rate"] < 30:
            recs.append(
                f"{strategy} has only {m['win_rate']}% win rate on {m['total_trades']} trades. "
                "Consider disabling it until market conditions change."
            )
        if m["total_trades"] >= 3 and m["profit_factor"] > 2.0 and m["win_rate"] > 55:
            recs.append(
                f"{strategy} is performing well (PF {m['profit_factor']}, WR {m['win_rate']}%). "
                "Consider increasing allocation weight for this strategy."
            )

    if mae_mfe:
        capture = mae_mfe.get("avg_mfe_capture_rate", 1.0)
        if 0 < capture < 0.5:
            recs.append(
                f"Winners are capturing only {capture:.0%} of their max favorable move. "
                "Reduce trailing_atr_multiplier to lock in gains earlier."
            )
        mae_ratio = mae_mfe.get("avg_mae_loss_ratio", 1.0)
        if mae_ratio < 0.8:
            recs.append(
                "Losing trades show small adverse excursion before reversing — stops are too tight. "
                "Consider widening stop loss placement by ~20%."
            )
        elif mae_ratio > 1.8:
            recs.append(
                "Losing trades travel far past the initial stop level — exits are being delayed. "
                "Verify stop loss orders are executing promptly."
            )

    if not recs:
        recs.append("Performance within acceptable parameters. Continue monitoring.")

    return recs


def get_adaptive_strategy_order(trade_history, lookback=50):
    """
    Returns strategy base names ranked by recent combined score (profit_factor × win_rate).
    Returns None when there is insufficient trade history to make a reliable ranking.
    Used by select_best_strategy to bias toward currently better-performing strategies.
    """
    _NAME_MAP = {
        "ORB-Buy": "ORB", "ORB-Short": "ORB",
        "VWAP-Pullback-Buy": "VWAP-Pullback", "VWAP-Pullback-Short": "VWAP-Pullback",
        "Momentum-Buy": "Momentum", "Momentum-Short": "Momentum",
        "MeanReversion-Buy": "MeanReversion", "MeanReversion-Short": "MeanReversion",
        "TrendFollow-Buy": "TrendFollow", "TrendFollow-Short": "TrendFollow",
        "VWAPTrendPullback-Buy": "VWAPTrendPullback",
        "VWAPTrendPullback-Short": "VWAPTrendPullback",
        "SupportResistance-Breakout-Buy": "SupportResistance",
        "SupportResistance-Breakout-Short": "SupportResistance",
        "SupportResistance-Rejection-Buy": "SupportResistance",
        "SupportResistance-Rejection-Short": "SupportResistance",
    }

    recent = trade_history[-lookback:] if len(trade_history) > lookback else trade_history
    if len(recent) < 10:
        return None

    perf = {}
    for t in recent:
        base = _NAME_MAP.get(t.get("strategy", ""))
        if not base:
            continue
        p = perf.setdefault(base, {"wins": 0, "losses": 0, "gross_profit": 0.0, "gross_loss": 0.0})
        pnl = t.get("pnl", 0.0)
        if pnl > 0:
            p["wins"] += 1
            p["gross_profit"] += pnl
        else:
            p["losses"] += 1
            p["gross_loss"] += abs(pnl)

    scores = {}
    for name, s in perf.items():
        total = s["wins"] + s["losses"]
        if total < 3:
            continue
        pf = s["gross_profit"] / s["gross_loss"] if s["gross_loss"] > 0 else (9.0 if s["gross_profit"] > 0 else 0.0)
        wr = s["wins"] / total
        scores[name] = pf * wr

    if len(scores) < 2:
        return None
    return sorted(scores, key=lambda k: scores[k], reverse=True)


def analyze_mae_mfe(trades):
    """
    Analyzes Maximum Adverse/Favorable Excursion to diagnose stop and target placement.
    Requires trades with 'mae' and 'mfe' keys (populated during live position management).
    """
    trades_with_data = [t for t in trades if "mae" in t and "mfe" in t]
    if not trades_with_data:
        return {}

    wins = [t for t in trades_with_data if t["pnl"] > 0]
    losses = [t for t in trades_with_data if t["pnl"] < 0]

    def _avg(lst, key):
        return round(sum(t[key] for t in lst) / len(lst), 2) if lst else 0.0

    result = {
        "sample_size": len(trades_with_data),
        "avg_mfe_winners": _avg(wins, "mfe"),
        "avg_mfe_losers": _avg(losses, "mfe"),
        "avg_mae_winners": _avg(wins, "mae"),
        "avg_mae_losers": _avg(losses, "mae"),
    }

    if wins:
        capture_rates = [t["pnl"] / t["mfe"] for t in wins if t.get("mfe", 0) > 0]
        result["avg_mfe_capture_rate"] = round(
            sum(capture_rates) / len(capture_rates), 2
        ) if capture_rates else 1.0

    if losses:
        ratios = [abs(t["mae"]) / abs(t["pnl"]) for t in losses if t.get("pnl", 0) != 0]
        result["avg_mae_loss_ratio"] = round(
            sum(ratios) / len(ratios), 2
        ) if ratios else 1.0

    return result


def generate_session_report(trades):
    """
    Full end-of-session analysis:
    - Overall metrics
    - Per-strategy breakdown
    - Per-symbol breakdown
    - Actionable recommendations
    - Loss clustering by hour
    """
    if not trades:
        return {
            "summary": "No trades executed this session.",
            "metrics": calculate_metrics([]),
            "by_strategy": {},
            "by_symbol": {},
            "insights": {"recommendations": ["No trades to analyse."]},
        }

    metrics = calculate_metrics(trades)
    by_strategy = analyze_by_strategy(trades)
    by_symbol = analyze_by_symbol(trades)
    mae_mfe = analyze_mae_mfe(trades)

    # Hour-of-day loss clustering
    loss_by_hour = {}
    win_by_hour = {}
    for t in trades:
        try:
            hour = t.get("exit_time", "")[:13].split("T")[-1].split(":")[0]
        except Exception:
            hour = "unknown"
        bucket = loss_by_hour if t.get("pnl", 0) < 0 else win_by_hour
        bucket[hour] = bucket.get(hour, 0) + 1

    worst_hour = max(loss_by_hour, key=loss_by_hour.get) if loss_by_hour else None
    best_hour = max(win_by_hour, key=win_by_hour.get) if win_by_hour else None

    best_strategy = max(by_strategy, key=lambda s: by_strategy[s]["total_pnl"]) if by_strategy else None
    worst_strategy = min(by_strategy, key=lambda s: by_strategy[s]["total_pnl"]) if by_strategy else None

    return {
        "metrics": metrics,
        "by_strategy": by_strategy,
        "by_symbol": by_symbol,
        "mae_mfe": mae_mfe,
        "insights": {
            "best_strategy": best_strategy,
            "worst_strategy": worst_strategy,
            "worst_loss_hour": worst_hour,
            "best_win_hour": best_hour,
            "recommendations": _generate_recommendations(metrics, by_strategy, mae_mfe),
        },
    }
