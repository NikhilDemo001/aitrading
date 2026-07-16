"""SQLite persistence for the bot's REAL trading state.

This is the source of truth: active_positions.json / trade_history.json are mirrors that
self-heal from these tables (the test suite overwrites the JSON files, the DB survives).

Previously these two tables lived inside research_lab.py's init_db() alongside 16 tables of
synthetic "AI research" data. The research lab is gone; only the real state remains, which is
all main.py ever persisted here.

Schema note: live_positions historically also carried rl_state_key / rl_action_id columns for
the Q-learning sizing experiment. That machinery is removed, so new databases don't create them.
CREATE TABLE IF NOT EXISTS leaves existing databases untouched — the stale columns simply sit
unused and nullable, and nothing reads or writes them.
"""

import sqlite3

DB_FILE = "ai_research.db"


def get_db_connection():
    """Connection to the state database. WAL so the scanner, the position manager and the API
    can read while one writer commits; 30s busy timeout so a concurrent write waits instead of
    raising 'database is locked'."""
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        pass
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the real-state tables if they don't exist. Safe to call on every startup."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS live_positions (
        symbol TEXT NOT NULL,
        instrument_key TEXT PRIMARY KEY,
        is_fno INTEGER,
        lot_size INTEGER,
        contract TEXT,
        strategy TEXT,
        direction TEXT,
        quantity INTEGER,
        entry_price REAL,
        entry_time TEXT,
        stop_loss REAL,
        target REAL,
        target_2 REAL,
        t1_hit INTEGER,
        order_id TEXT,
        current_price REAL,
        pnl REAL,
        atr_at_entry REAL,
        trailing_high REAL,
        trailing_low REAL,
        market_context TEXT,
        regime TEXT,
        htf_trend TEXT,
        mae REAL,
        mfe REAL,
        confluence_score INTEGER,
        trigger_level_source TEXT,
        trigger_level_price REAL,
        trigger_level_score REAL
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS live_trades (
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

    conn.commit()
    conn.close()
    print("[State DB] SQLite state database initialized.")
