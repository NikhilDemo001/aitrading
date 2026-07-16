"""
Symbol Memory — Persistent Per-Symbol Trading Intelligence
==========================================================
Learns from past trades per symbol:
- Best time-of-day to trade
- Best market regime for each symbol
- Win rate trend (improving / declining)
- Typical holding period
- Symbol-level bias score (-10 to +10)
"""

import sqlite3

MEMORY_DB = "symbol_memory.db"


def get_db_connection():
    """Returns a connection to the symbol memory database."""
    conn = sqlite3.connect(MEMORY_DB, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        pass
    conn.row_factory = sqlite3.Row
    return conn


def init_memory_db():
    """Initialize the symbol memory database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS symbol_stats (
        symbol TEXT PRIMARY KEY,
        total_trades INTEGER DEFAULT 0,
        total_wins INTEGER DEFAULT 0,
        total_losses INTEGER DEFAULT 0,
        win_rate REAL DEFAULT 0.0,
        avg_pnl REAL DEFAULT 0.0,
        best_hour TEXT DEFAULT '',
        best_regime TEXT DEFAULT '',
        avg_holding_mins REAL DEFAULT 0.0,
        bias_score REAL DEFAULT 0.0,
        last_updated TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS symbol_trade_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        strategy TEXT,
        direction TEXT,
        pnl REAL,
        regime TEXT,
        entry_hour TEXT,
        holding_minutes REAL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    conn.commit()
    conn.close()


def record_trade(symbol, strategy, direction, pnl, regime, entry_time, holding_minutes):
    """Record a completed trade for symbol learning."""
    init_memory_db()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Extract hour of entry
        # ISO format: YYYY-MM-DDTHH:MM:SS
        entry_hour = "10"
        if entry_time and len(entry_time) >= 16:
            entry_hour = entry_time[11:13]
            
        cursor.execute("""
        INSERT INTO symbol_trade_log (symbol, strategy, direction, pnl, regime, entry_hour, holding_minutes)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (symbol, strategy, direction, pnl, regime, entry_hour, holding_minutes))
        
        conn.commit()
    except Exception as e:
        print(f"[Symbol Memory] Error logging trade: {e}")
    finally:
        conn.close()
        
    update_symbol_stats(symbol)


def update_symbol_stats(symbol):
    """Recalculate and update aggregated stats for a symbol."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM symbol_trade_log WHERE symbol = ?;", (symbol,))
        trades = cursor.fetchall()
        if not trades:
            return
            
        total = len(trades)
        wins = sum(1 for t in trades if t['pnl'] > 0)
        losses = sum(1 for t in trades if t['pnl'] < 0)
        win_rate = (wins / total * 100.0) if total > 0 else 0.0
        avg_pnl = sum(t['pnl'] for t in trades) / total
        avg_holding = sum(t['holding_minutes'] or 0.0 for t in trades) / total
        
        # Calculate best hour
        hour_counts = {}
        hour_pnl = {}
        for t in trades:
            hr = t['entry_hour']
            hour_counts[hr] = hour_counts.get(hr, 0) + 1
            hour_pnl[hr] = hour_pnl.get(hr, 0.0) + t['pnl']
        best_hour = max(hour_pnl, key=hour_pnl.get) if hour_pnl else ''
        
        # Calculate best regime
        regime_pnl = {}
        for t in trades:
            reg = t['regime']
            regime_pnl[reg] = regime_pnl.get(reg, 0.0) + t['pnl']
        best_regime = max(regime_pnl, key=regime_pnl.get) if regime_pnl else ''
        
        # Calculate bias score (-10 to +10)
        # Sells a basic calculation: win rate ratio scaled, plus net profitability ratio.
        # Requires at least 5 trades to gain high confidence.
        bias_score = 0.0
        if total >= 5:
            # Base score from win rate: e.g. 50% = 0, 75% = +5, 25% = -5
            bias_score += (win_rate - 50.0) / 5.0
            # Add average pnl scaling (cap at +/- 5 points)
            pnl_points = avg_pnl / 100.0
            pnl_points = min(max(pnl_points, -5.0), 5.0)
            bias_score += pnl_points
            bias_score = round(min(max(bias_score, -10.0), 10.0), 2)
            
        cursor.execute("""
        INSERT INTO symbol_stats (symbol, total_trades, total_wins, total_losses, win_rate, avg_pnl, best_hour, best_regime, avg_holding_mins, bias_score, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(symbol) DO UPDATE SET
            total_trades=excluded.total_trades,
            total_wins=excluded.total_wins,
            total_losses=excluded.total_losses,
            win_rate=excluded.win_rate,
            avg_pnl=excluded.avg_pnl,
            best_hour=excluded.best_hour,
            best_regime=excluded.best_regime,
            avg_holding_mins=excluded.avg_holding_mins,
            bias_score=excluded.bias_score,
            last_updated=CURRENT_TIMESTAMP;
        """, (symbol, total, wins, losses, win_rate, avg_pnl, best_hour, best_regime, avg_holding, bias_score))
        
        conn.commit()
    except Exception as e:
        print(f"[Symbol Memory] Error updating stats: {e}")
    finally:
        conn.close()


def get_symbol_bias(symbol):
    """
    Returns bias score for the symbol (-10 to +10).
    Positive = bot has historically done well here.
    Negative = bot has historically lost here.
    Returns 0.0 if insufficient data (< 5 trades).
    """
    init_memory_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    score = 0.0
    try:
        cursor.execute("SELECT bias_score FROM symbol_stats WHERE symbol = ?;", (symbol,))
        row = cursor.fetchone()
        if row:
            score = row['bias_score']
    except Exception:
        pass
    finally:
        conn.close()
    return score


def get_best_time_for_symbol(symbol):
    """Returns best trading hour (e.g. '10', '14') or None."""
    init_memory_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    hr = None
    try:
        cursor.execute("SELECT best_hour FROM symbol_stats WHERE symbol = ?;", (symbol,))
        row = cursor.fetchone()
        if row and row[0]:
            hr = row[0]
    except Exception:
        pass
    finally:
        conn.close()
    return hr


def get_symbol_summary(symbol):
    """
    Returns dict with symbol stats summary.
    """
    init_memory_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    summary = {
        'win_rate': 0.0,
        'total_trades': 0,
        'avg_pnl': 0.0,
        'best_hour': '',
        'best_regime': '',
        'bias_score': 0.0,
        'recommendation': 'NEUTRAL'
    }
    try:
        cursor.execute("SELECT * FROM symbol_stats WHERE symbol = ?;", (symbol,))
        row = cursor.fetchone()
        if row:
            summary = {
                'win_rate': row['win_rate'],
                'total_trades': row['total_trades'],
                'avg_pnl': row['avg_pnl'],
                'best_hour': row['best_hour'],
                'best_regime': row['best_regime'],
                'bias_score': row['bias_score'],
                'recommendation': 'FAVORABLE' if row['bias_score'] >= 2.0 else 'AVOID' if row['bias_score'] <= -2.0 else 'NEUTRAL'
            }
    except Exception:
        pass
    finally:
        conn.close()
    return summary


def bulk_import_from_trade_history(trade_history):
    """
    Import all past trades from the bot's trade_history list into symbol memory.
    Called once on startup to backfill historical data.
    """
    if not trade_history:
        return
        
    init_memory_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    symbols_to_update = set()
    try:
        for t in trade_history:
            symbol = t.get("symbol")
            if not symbol:
                continue
            strategy = t.get("strategy", "")
            direction = t.get("direction", "")
            pnl = t.get("pnl", 0.0)
            regime = t.get("regime", "unknown")
            entry_time = t.get("entry_time", "")
            holding_minutes = t.get("holding_minutes", 0.0)
            
            entry_hour = "10"
            if entry_time and len(entry_time) >= 16:
                entry_hour = entry_time[11:13]
                
            cursor.execute("""
            INSERT INTO symbol_trade_log (symbol, strategy, direction, pnl, regime, entry_hour, holding_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (symbol, strategy, direction, pnl, regime, entry_hour, holding_minutes))
            symbols_to_update.add(symbol)
            
        conn.commit()
    except Exception as e:
        print(f"[Symbol Memory] Error bulk importing trades: {e}")
    finally:
        conn.close()
        
    for symbol in symbols_to_update:
        update_symbol_stats(symbol)
