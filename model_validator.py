"""
Model Validator for Out-of-Sample Walk-Forward Testing
======================================================
1. Splits historical trades into In-Sample and Out-of-Sample datasets.
2. Simulates trading on Out-of-Sample datasets using the updated vs current policies.
3. Rejects model updates that result in worse performance or increased drawdowns.
"""

from learning_engine import QLearningAgent

def validate_model_update(trade_history, temp_policy_path, current_policy_path):
    """
    Validates updated policy against current policy on out-of-sample trades.
    Returns True if approved, False if rejected.
    """
    # If not enough history, approve the update to bootstrap the model
    if len(trade_history) < 10:
        print(f"[Model Validator] Insufficient history ({len(trade_history)} trades). Bootstrapping approved.")
        return True

    # Split history: 70% In-Sample (training), 30% Out-of-Sample (testing)
    split_idx = int(len(trade_history) * 0.70)
    out_of_sample_trades = trade_history[split_idx:]
    
    # Load current and proposed policies
    agent_proposed = QLearningAgent(policy_path=temp_policy_path)
    agent_current = QLearningAgent(policy_path=current_policy_path)
    
    # Simulate both on Out-of-Sample trades
    proposed_pnl = 0.0
    current_pnl = 0.0
    
    proposed_drawdowns = 0
    current_drawdowns = 0
    
    for t in out_of_sample_trades:
        # Build state context
        context = t.get("market_context", {})
        if not context:
            # Reconstruct basic context if missing
            context = {
                "regime": t.get("regime", "unknown"),
                "atr_pct": 0.008,
                "volume_ratio": 1.2 if t.get("pnl", 0.0) != 0 else 1.0,
                "vwap_aligned": True,
                "htf_aligned": t.get("htf_trend", "neutral") != "neutral",
                "time": t.get("entry_time", "10:00")[11:16]
            }
            
        state_key = agent_current.discretize_state(context)
        
        # Proposed Action
        p_act, p_mult = agent_proposed.get_action(state_key)
        # Current Action
        c_act, c_mult = agent_current.get_action(state_key)
        
        pnl = t.get("pnl", 0.0)
        
        # Simulate returns
        p_pnl = pnl * p_mult
        c_pnl = pnl * c_mult
        
        proposed_pnl += p_pnl
        current_pnl += c_pnl
        
        if p_pnl < 0:
            proposed_drawdowns += 1
        if c_pnl < 0:
            current_drawdowns += 1

    # Validation criteria:
    # 1. Proposed policy out-of-sample PnL must be >= current policy out-of-sample PnL
    # 2. Proposed policy must not increase drawdowns by more than 10%
    approved = (proposed_pnl >= current_pnl) and (proposed_drawdowns <= current_drawdowns * 1.1)
    
    print("[Model Validator] Walk-forward results:")
    print(f"  Current Policy PnL: Rs. {current_pnl:.2f} | Drawdowns: {current_drawdowns}")
    print(f"  Proposed Policy PnL: Rs. {proposed_pnl:.2f} | Drawdowns: {proposed_drawdowns}")
    print(f"  Validation Outcome: {'APPROVED' if approved else 'REJECTED'}")
    
    return approved
