"""
JSONL trade logging (Section 6 data files) — additive alongside the existing trade_history.json/
SQLite persistence, not a replacement. Every closed trade already flows through main.py's
execute_exit(); this module takes that same record and (a) enriches it with the fields the spec's
schema requires but the existing record doesn't carry yet (trade_id, mode, r_multiple,
time_of_day_bucket, pnl_pct), and (b) appends it to data/wins.jsonl or data/losses.jsonl.

Also provides log_decision() for data/decisions.log — every skip/pick/trade decision with its
reason, so the UI can show why the bot did or didn't act (Section 0 rule 7: nothing silent).
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from typing import Optional

DATA_DIR = "data"
WINS_FILE = os.path.join(DATA_DIR, "wins.jsonl")
LOSSES_FILE = os.path.join(DATA_DIR, "losses.jsonl")
DECISIONS_FILE = os.path.join(DATA_DIR, "decisions.log")

_EXIT_REASON_MAP = (
    ("TARGET", "target"),
    ("STOP", "stoploss"),
    ("SQUARE", "eod_squareoff"),
    ("SQUAREOFF", "eod_squareoff"),
    ("MOMENTUM", "signal_reverse"),
    ("CROSS", "signal_reverse"),
    ("TIME STOP", "time_stop"),
)


def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _normalize_exit_reason(raw_reason: str) -> str:
    r = (raw_reason or "").upper()
    for needle, mapped in _EXIT_REASON_MAP:
        if needle in r:
            return mapped
    return "other"


def time_of_day_bucket(dt: datetime, market_open: str = "09:15", session_end: str = "15:15", bucket_minutes: int = 45) -> str:
    """Buckets a timestamp into fixed-width windows from market open, e.g. '0915_1000'."""
    open_h, open_m = (int(x) for x in market_open.split(":"))
    open_dt = dt.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    elapsed_min = max(0, (dt - open_dt).total_seconds() / 60.0)
    bucket_index = int(elapsed_min // bucket_minutes)
    bucket_start = open_dt.timestamp() + bucket_index * bucket_minutes * 60
    bucket_end = bucket_start + bucket_minutes * 60
    start_dt = datetime.fromtimestamp(bucket_start)
    end_dt = datetime.fromtimestamp(bucket_end)
    return f"{start_dt.strftime('%H%M')}_{end_dt.strftime('%H%M')}"


def build_trade_record(record: dict, mode: str, capital: Optional[float] = None) -> dict:
    """Converts an existing execute_exit()-style trade_history record into the full Section-6
    schema. Additive: every field already in `record` is preserved; only the schema's missing
    fields are derived/defaulted.

    r_multiple is approximated as pnl-per-share / atr_at_entry, since the existing trade_history
    record does not carry the position's actual stop-loss distance at close time — every
    strategy already sizes its stop as an ATR multiple (Section 4), so this is a reasonable
    proxy rather than a change to execute_exit's record construction.
    """
    direction_raw = str(record.get("direction", "")).upper()
    direction = "long" if direction_raw == "LONG" else ("short" if direction_raw == "SHORT" else direction_raw.lower())

    entry_price = record.get("entry_price") or 0.0
    exit_price = record.get("exit_price") or 0.0
    quantity = record.get("quantity") or 0
    pnl = record.get("pnl", 0.0)

    notional = abs(entry_price * quantity)
    pnl_pct = round((pnl / notional) * 100, 4) if notional else 0.0

    atr_at_entry = record.get("atr_at_entry")
    per_share_pnl = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
    r_multiple = round(per_share_pnl / atr_at_entry, 3) if atr_at_entry else None

    try:
        entry_dt = datetime.fromisoformat(record.get("entry_time", ""))
        bucket = time_of_day_bucket(entry_dt)
    except Exception:
        bucket = None

    patterns = record.get("candlestick_patterns")
    if patterns is None:
        single = record.get("pattern")
        patterns = [single] if single else []

    symbol = record.get("symbol", "")
    exchange_symbol = symbol if ":" in symbol else f"NSE:{symbol}"

    return {
        "trade_id": record.get("trade_id") or str(uuid.uuid4()),
        "mode": mode,
        "symbol": exchange_symbol,
        "strategy": record.get("strategy"),
        "direction": direction,
        "timestamp_entry": record.get("entry_time"),
        "timestamp_exit": record.get("exit_time"),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": quantity,
        "pnl": round(pnl, 2),
        "pnl_pct": pnl_pct,
        "r_multiple": r_multiple,
        "exit_reason": _normalize_exit_reason(record.get("reason", "")),
        "market_regime": record.get("regime", "unknown"),
        "candlestick_patterns": patterns,
        "time_of_day_bucket": bucket,
        "indicators_at_entry": record.get("market_context", {}),
        "lesson": record.get("lesson", ""),
        "tags": record.get("tags", []),
        # Fields kept for backward-compat with the existing dashboard/analytics that already
        # read trade_history.json's shape — harmless extras alongside the spec schema above.
        "holding_minutes": record.get("holding_minutes"),
        "mae": record.get("mae"),
        "mfe": record.get("mfe"),
        "confluence_score": record.get("confluence_score"),
        "is_shadow_trade": record.get("is_shadow_trade", False),
    }


def log_trade(record: dict, mode: str, capital: Optional[float] = None) -> dict:
    """Appends one line to data/wins.jsonl or data/losses.jsonl depending on pnl sign.
    Returns the full enriched record that was written."""
    _ensure_data_dir()
    full_record = build_trade_record(record, mode, capital)
    target_file = WINS_FILE if full_record["pnl"] >= 0 else LOSSES_FILE
    with open(target_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(full_record) + "\n")
    return full_record


def log_decision(decision_type: str, symbol: str, reason: str, extra: Optional[dict] = None) -> None:
    """Appends one line to data/decisions.log. decision_type: 'skip' | 'pick' | 'trade'."""
    _ensure_data_dir()
    entry = {
        "time": datetime.now().isoformat(),
        "type": decision_type,
        "symbol": symbol,
        "reason": reason,
    }
    if extra:
        entry.update(extra)
    with open(DECISIONS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_jsonl(path: str, limit: Optional[int] = None) -> list:
    """Reads a JSONL file into a list of dicts, tolerating malformed trailing lines (e.g. from
    a crash mid-write) rather than failing the whole read."""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if limit is not None:
        rows = rows[-limit:]
    return rows


def backfill_lessons(trade_id_to_lesson: dict) -> int:
    """Rewrites matching lines in wins.jsonl/losses.jsonl with a lesson filled in (used by the
    Claude lesson-extraction job, which runs after trades close rather than blocking the live
    loop on a network call per trade). Returns how many lines were updated."""
    updated = 0
    for path in (WINS_FILE, LOSSES_FILE):
        rows = read_jsonl(path)
        if not rows:
            continue
        changed = False
        for row in rows:
            lesson = trade_id_to_lesson.get(row.get("trade_id"))
            if lesson and not row.get("lesson"):
                row["lesson"] = lesson
                changed = True
                updated += 1
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row) + "\n")
    return updated
