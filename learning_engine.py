"""
Reinforcement Learning Engine for Trading Intelligence
======================================================
1. Discretizes market context into state keys.
2. Manages Q-Table policy loading, saving, and lookup.
3. Implements contextual Q-learning updates based on trade outcomes (PnL vs Risk).
4. Handles counterfactual rewards for shadow trades (skipped entries).
5. Upgraded to DQN-style neural network generalizer for unseen states (pure Python MLP).
"""

import os
import json
import math
import random

POLICY_FILE = "rl_policy.json"


class SimpleMLP:
    """A self-contained Multi-Layer Perceptron neural network in pure Python."""
    def __init__(self, input_dim=16, hidden_dim=32, output_dim=4, lr=0.03):
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.output_dim = output_dim
        self.lr = lr
        
        # Seed random for test reproducibility
        random.seed(42)
        
        # Initialize weights (Xavier/He initialization approximation) and biases
        scale_ih = math.sqrt(2.0 / input_dim)
        self.w_ih = [[random.gauss(0, 1) * scale_ih for _ in range(input_dim)] for _ in range(hidden_dim)]
        self.b_h = [0.0 for _ in range(hidden_dim)]
        
        # Initialize w_ho weights to 0.0 to break symmetry through w_ih random activations.
        # b_o holds 4 initial bias values (one per action: Skip, Half, Normal, Double).
        # These priors guide the expanded 16-input / 32-hidden network toward the same
        # default action priorities as the legacy 8/16 network, ensuring smooth retraining
        # after the architecture upgrade (M3). SGD updates will quickly adapt from here.
        self.w_ho = [[0.0 for _ in range(hidden_dim)] for _ in range(output_dim)]
        self.b_o = [-0.1, 0.1, 0.2, 0.0]  # [Skip, Half, Normal, Double] default priors

    def forward(self, x):
        # Hidden layer inputs and activations (ReLU)
        h_in = []
        h_out = []
        for i in range(self.hidden_dim):
            val = sum(x[j] * self.w_ih[i][j] for j in range(self.input_dim)) + self.b_h[i]
            h_in.append(val)
            h_out.append(max(0.0, val))  # ReLU activation
            
        # Output layer inputs and activations (Linear)
        out = []
        for i in range(self.output_dim):
            val = sum(h_out[j] * self.w_ho[i][j] for j in range(self.hidden_dim)) + self.b_o[i]
            out.append(val)
            
        return h_in, h_out, out

    def backward(self, x, h_in, h_out, out, action, target):
        # Calculate output error and delta
        # dLoss/dout = -(target - out[action]) for action, 0 for others
        d_out = [0.0] * self.output_dim
        d_out[action] = -(target - out[action])
        
        # Backpropagate to hidden layer
        d_hidden = [0.0] * self.hidden_dim
        for j in range(self.hidden_dim):
            if h_in[j] > 0:  # Derivative of ReLU is 1 if h_in > 0 else 0
                error_sum = sum(d_out[i] * self.w_ho[i][j] for i in range(self.output_dim))
                d_hidden[j] = error_sum
                
        # Update weights and biases w_ho
        for i in range(self.output_dim):
            for j in range(self.hidden_dim):
                self.w_ho[i][j] -= self.lr * d_out[i] * h_out[j]
            self.b_o[i] -= self.lr * d_out[i]
            
        # Update weights and biases w_ih
        for i in range(self.hidden_dim):
            for j in range(self.input_dim):
                self.w_ih[i][j] -= self.lr * d_hidden[i] * x[j]
            self.b_h[i] -= self.lr * d_hidden[i]


class QLearningAgent:
    def __init__(self, policy_path=POLICY_FILE):
        self.policy_path = policy_path
        self.q_table = {}  # state_key -> list of 4 Q-values (actions: 0=Skip, 1=Half, 2=Normal, 3=Double)
        self.alpha = 0.15  # Learning rate
        self.network = SimpleMLP(input_dim=16, hidden_dim=32, output_dim=4, lr=0.03)  # M3: expanded network
        self.load_policy()

    def load_policy(self):
        """Loads Q-table and network weights from policy file if it exists."""
        if os.path.exists(self.policy_path):
            try:
                with open(self.policy_path) as f:
                    data = json.load(f)
                
                # Support dictionary with dual elements (network weights + Q-table)
                if isinstance(data, dict) and ("q_table" in data or "w_ih" in data):
                    self.q_table = data.get("q_table", {})
                    if 'w_ih' in data:
                        loaded_w_ih = data['w_ih']
                        # Backward-compatibility guard: verify saved network dimensions
                        # match current architecture (M3 expanded to 32x16 from 16x8).
                        # If they differ, discard stale weights and retrain from scratch.
                        if (len(loaded_w_ih) == self.network.hidden_dim
                                and len(loaded_w_ih[0]) == self.network.input_dim):
                            self.network.w_ih = loaded_w_ih
                            self.network.b_h = data['b_h']
                            self.network.w_ho = data['w_ho']
                            self.network.b_o = data['b_o']
                        else:
                            print(
                                f'[RL Engine] Network dimensions changed '
                                f'({len(loaded_w_ih)}x{len(loaded_w_ih[0])} -> '
                                f'{self.network.hidden_dim}x{self.network.input_dim}). '
                                f'Reinitializing network weights.'
                            )
                            # Keep q_table but reset network weights so it retrains cleanly
                else:
                    # Legacy structure where file was just the q_table itself
                    self.q_table = data
                
                print(f"[RL Engine] Loaded policy with {len(self.q_table)} states.")
            except Exception as e:
                print(f"[RL Engine] Error loading policy: {e}")
                self.q_table = {}
        else:
            self.q_table = {}

    def save_policy(self, temp_path=None):
        """Saves Q-table and network weights to policy file atomically."""
        path = temp_path or self.policy_path
        try:
            # Save atomically using temporary file
            dir_name = os.path.dirname(os.path.abspath(path))
            import tempfile
            fd, tmp = tempfile.mkstemp(dir=dir_name, prefix="policy_", suffix=".tmp")
            
            data_to_save = {
                "q_table": self.q_table,
                "w_ih": self.network.w_ih,
                "b_h": self.network.b_h,
                "w_ho": self.network.w_ho,
                "b_o": self.network.b_o
            }
            
            with os.fdopen(fd, "w") as f:
                json.dump(data_to_save, f, indent=2)
            os.replace(tmp, path)
            return True
        except Exception as e:
            print(f"[RL Engine] Error saving policy to {path}: {e}")
            return False

    def discretize_state(self, context):
        """
        Converts trade market context variables into a discrete string key.
        context keys: regime, atr_pct, volume_ratio, vwap_aligned, htf_aligned, time
        """
        # 1. Regime (5 states)
        regime = context.get("regime", "unknown")
        if regime not in ("trending_up", "trending_down", "ranging", "choppy"):
            regime = "unknown"
            
        # 2. Volatility ATR % of Price (3 states)
        atr_pct = context.get("atr_pct", 0.008)
        if atr_pct < 0.004:
            vol = "low"
        elif atr_pct <= 0.015:
            vol = "normal"
        else:
            vol = "high"
            
        # 3. Volume strength ratio (3 states)
        vol_ratio = context.get("volume_ratio", 1.0)
        if vol_ratio < 1.2:
            vol_str = "weak"
        elif vol_ratio <= 1.8:
            vol_str = "normal"
        else:
            vol_str = "strong"
            
        # 4. VWAP alignment (2 states)
        vwap = "yes" if context.get("vwap_aligned", False) else "no"
        
        # 5. HTF Trend alignment (2 states)
        htf = "yes" if context.get("htf_aligned", False) else "no"
        
        # 6. Time of day buckets (3 states)
        time_str = context.get("time", "10:00")
        try:
            h = int(time_str.split(":")[0])
            m = int(time_str.split(":")[1])
            t_val = h * 60 + m
            if t_val < 11 * 60 + 30:  # before 11:30 AM
                tod = "morning"
            elif t_val < 13 * 60 + 30: # 11:30 AM - 01:30 PM
                tod = "midday"
            else:
                tod = "afternoon"
        except Exception:
            tod = "morning"
            
        # 7. RSI (3 states: oversold < 30, overbought > 70, neutral)
        rsi_val = context.get("rsi")
        rsi_str = ""
        if rsi_val is not None:
            if rsi_val < 30:
                rsi_str = "_oversold"
            elif rsi_val > 70:
                rsi_str = "_overbought"
            else:
                rsi_str = "_neutral"

        # 8. ADX (3 states: weak < 15, normal 15-25, strong > 25)
        adx_val = context.get("adx")
        adx_str = ""
        if adx_val is not None:
            if adx_val < 15:
                adx_str = "_weak"
            elif adx_val <= 25:
                adx_str = "_normal"
            else:
                adx_str = "_strong"

        # 9. Day of week (5 states: mon/tue/wed/thu/fri)
        # Adds temporal context so the agent learns weekday-specific patterns
        # (e.g., Monday gaps, Thursday F&O expiry volatility).
        try:
            from datetime import datetime as _dt
            _dow = _dt.now().weekday()  # 0=Mon, 4=Fri
            dow_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri'}
            dow_str = f"_{dow_map.get(_dow, 'mon')}"
        except Exception:
            dow_str = '_mon'

        # 10. Expiry week flag (appends '_expiry' during F&O expiry week)
        # Allows the agent to learn that expiry weeks have different risk/reward dynamics.
        try:
            from event_calendar import is_fno_expiry_week
            expiry_str = '_expiry' if is_fno_expiry_week() else ''
        except Exception:
            expiry_str = ''

        return f"{regime}_{vol}_{vol_str}_{vwap}_{htf}_{tod}{rsi_str}{adx_str}{dow_str}{expiry_str}"

    def state_key_to_features(self, state_key):
        """Converts string state_key back into normalized float features for Neural Network.
        Extended to 16 features for the expanded MLP (M3 upgrade).
        
        Feature layout:
          [0]  Regime              (trending=1.0, ranging=0.0, choppy=0.5, unknown=0.2)
          [1]  Volatility          (low=-1, normal=0, high=1)
          [2]  Volume strength     (weak=-1, normal=0, strong=1)
          [3]  VWAP aligned        (yes=1, no=0)
          [4]  HTF aligned         (yes=1, no=0)
          [5]  Time of day         (morning=0.1, midday=0.5, afternoon=0.9)
          [6]  RSI zone            (oversold=0.15, neutral=0.5, overbought=0.85)
          [7]  ADX strength        (weak=0.1, normal=0.4, strong=0.8)
          [8]  Day of week         (mon=0.0, tue=0.25, wed=0.5, thu=0.75, fri=1.0)
          [9]  Expiry week flag    (expiry=1.0, else=0.0)
          [10-15] Reserved zeros  (for future expansion)
        """
        parts = state_key.split('_')
        features = [0.0] * 16  # Extended to 16 features

        # Features 0-7: same as before
        regime_map = {'trending': 1.0, 'ranging': 0.0, 'choppy': 0.5, 'unknown': 0.2}
        features[0] = regime_map.get(parts[0] if parts else 'unknown', 0.2)

        vol_map = {'low': -1.0, 'normal': 0.0, 'high': 1.0}
        if len(parts) > 1: features[1] = vol_map.get(parts[1], 0.0)

        vol_str_map = {'weak': -1.0, 'normal': 0.0, 'strong': 1.0}
        if len(parts) > 2: features[2] = vol_str_map.get(parts[2], 0.0)

        if len(parts) > 3: features[3] = 1.0 if parts[3] == 'yes' else 0.0
        if len(parts) > 4: features[4] = 1.0 if parts[4] == 'yes' else 0.0

        tod_map = {'morning': 0.1, 'midday': 0.5, 'afternoon': 0.9}
        if len(parts) > 5: features[5] = tod_map.get(parts[5], 0.1)

        rsi_map = {'oversold': 0.15, 'neutral': 0.5, 'overbought': 0.85}
        if len(parts) > 6: features[6] = rsi_map.get(parts[6], 0.5)

        adx_map = {'weak': 0.1, 'normal': 0.4, 'strong': 0.8}
        if len(parts) > 7: features[7] = adx_map.get(parts[7], 0.4)

        # Features 8-15: Extended features (M3 additions)

        # Feature 8: Day of week (normalised 0.0=Mon .. 1.0=Fri)
        dow_map = {'mon': 0.0, 'tue': 0.25, 'wed': 0.5, 'thu': 0.75, 'fri': 1.0}
        if len(parts) > 8: features[8] = dow_map.get(parts[8], 0.0)

        # Feature 9: F&O expiry week flag (1.0 if key contains 'expiry', else 0.0)
        if len(parts) > 9: features[9] = 1.0 if parts[9] == 'expiry' else 0.0

        # Features 10-15: Reserved (zero) for future expansion
        return features

    def get_action(self, state_key, mode="live"):
        """
        Queries policy for the best sizing action.
        Uses Neural Network generalization to initialize unseen states.
        Returns (action_id, multiplier).
        """
        if state_key not in self.q_table:
            # Unseen state: Generalize initial values using SimpleMLP forward pass
            features = self.state_key_to_features(state_key)
            _, _, predicted_q = self.network.forward(features)
            self.q_table[state_key] = [round(max(-2.0, min(2.0, q)), 4) for q in predicted_q]
            
        q_vals = self.q_table[state_key]
        
        # Greedy action selection
        best_action = 2  # default fallback
        best_val = -9999.0
        for action_id, q_val in enumerate(q_vals):
            if q_val > best_val:
                best_val = q_val
                best_action = action_id
                
        multipliers = {0: 0.0, 1: 0.5, 2: 1.0, 3: 1.5}
        return best_action, multipliers[best_action]

    def update_q_value(self, state_key, action, reward):
        """Updates Q-value for a state-action pair using TD updates and trains the Neural Network."""
        if state_key not in self.q_table:
            features = self.state_key_to_features(state_key)
            _, _, predicted_q = self.network.forward(features)
            self.q_table[state_key] = [round(max(-2.0, min(2.0, q)), 4) for q in predicted_q]
            
        q_vals = self.q_table[state_key]
        old_val = q_vals[action]
        # 1. Update tabular value
        q_vals[action] = round(old_val + self.alpha * (reward - old_val), 4)

        # 2. Train the MLP generalizer (DQN target fit)
        features = self.state_key_to_features(state_key)
        h_in, h_out, out = self.network.forward(features)
        self.network.backward(features, h_in, h_out, out, action, q_vals[action])

    def calculate_reward(self, pnl, risk, is_win, holding_mins=None):
        """Calculates normalized reward signal from trade metrics."""
        if risk <= 0:
            risk = 1.0
            
        pnl_ratio = pnl / risk
        
        if is_win:
            reward = pnl_ratio + 0.1
        else:
            reward = pnl_ratio - 0.25
            
        return round(reward, 4)

    def calculate_counterfactual_reward(self, would_win):
        """Calculates reward for skipped trades (Shadow Trades)."""
        return -0.5 if would_win else 0.5

    def batch_train_from_db(self, db_path="ai_research.db"):
        """
        Loads all completed trades from the SQLite live_trades database and 
        performs offline batch reinforcement learning (experience replay) to 
        train the Q-table and SimpleMLP neural network weights.
        """
        if not os.path.exists(db_path):
            print(f"[RL Batch Train] Database file {db_path} not found.")
            return 0
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Select all trades
            cursor.execute("SELECT * FROM live_trades")
            rows = cursor.fetchall()
            conn.close()
            
            if not rows:
                print("[RL Batch Train] No historical trades found in live_trades table.")
                return 0
                
            updated_count = 0
            for row in rows:
                trade = dict(row)
                market_context_str = trade.get("market_context")
                if not market_context_str:
                    continue
                try:
                    context = json.loads(market_context_str) if isinstance(market_context_str, str) else market_context_str
                except Exception:
                    continue
                
                # Reconstruct state key
                state_key = self.discretize_state(context)
                
                # Sizing action ID (Actions mapping: 0=Skip, 1=Half, 2=Normal, 3=Double)
                is_shadow = trade.get("is_shadow_trade", 0) == 1
                if is_shadow:
                    action_id = 0
                else:
                    action_id = 2  # standard default normal size
                    
                pnl = float(trade.get("pnl", 0.0))
                is_win = pnl >= 0
                
                if is_shadow:
                    reward = self.calculate_counterfactual_reward(is_win)
                else:
                    qty = float(trade.get("quantity", 1.0))
                    # Estimate risk_amount using atr_at_entry or entry/stop gap
                    atr = float(trade.get("atr_at_entry") or 0.0)
                    risk_amount = atr * qty if atr > 0 else abs(pnl) or 1.0
                    reward = self.calculate_reward(pnl, risk_amount, is_win)
                
                self.update_q_value(state_key, action_id, reward)
                updated_count += 1
                
            if updated_count > 0:
                self.save_policy()
                print(f"[RL Batch Train] Successfully trained on {updated_count} historical trades.")
                
            return updated_count
        except Exception as e:
            print(f"[RL Batch Train] Error during batch training: {e}")
            return 0

