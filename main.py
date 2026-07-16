import os
from dotenv import load_dotenv
load_dotenv()
import json
import asyncio
import functools
import time
import threading
from datetime import datetime, timedelta, time as datetime_time, UTC
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from upstox_client import UpstoxClient


def round_to_tick(price, tick_size=0.05):
    if price is None:
        return None
    return round(round(price / tick_size) * tick_size, 2)
from strategies import (
    calculate_ema, calculate_vwap, calculate_atr, calculate_rsi,
    detect_market_regime, get_htf_trend, select_best_strategy,
)
from analytics import calculate_metrics, analyze_by_strategy, generate_session_report, get_adaptive_strategy_order
from signal_quality import evaluate_signal, calculate_kelly_risk
from backtester import run_backtest, generate_backtest_report
from strategy_vwap_trend_pullback import check_vwap_trend_pullback as _check_vtp_direct
from generate_certs import generate_self_signed_cert
from market_feed import create_feed

vix_value = 15.0

def get_adaptive_trailing_multiplier(base_mult, pos, ltp):
    global vix_value
    mult = base_mult
    if vix_value and vix_value > 22.0:
        mult = mult * 1.467
    elif vix_value and vix_value < 14.0:
        mult = mult * 0.8
        
    # Time-of-day tightening (after 2:00 PM IST / 14:00)
    now_time = get_ist_now().time()
    if now_time >= datetime_time(14, 0):
        mult = mult * 0.6 # Tighten stop spacing by 40%

    # Volumetric RVOL check: Tighten stop spacing by 30% if volume is extreme (RVOL >= 2.0)
    rvol = pos.get("rvol", 1.0)
    if rvol >= 2.0:
        mult = mult * 0.7

    # Defensive Proximity Check: Tighten stop by 40% if we have T1 hit and are 80% close to Target 2
    if pos.get("t1_hit"):
        entry_p = pos["entry_price"]
        t2 = pos.get("target_2", pos["target"])
        total_dist = abs(t2 - entry_p)
        if total_dist > 0:
            progress = abs(ltp - entry_p) / total_dist
            if progress >= 0.8:
                mult = mult * 0.6

    # Time-Decay check: Tighten stop spacing by 5% for every 10 mins beyond 30 mins (max 50% reduction)
    try:
        from datetime import datetime
        entry_time_dt = datetime.fromisoformat(pos["entry_time"])
        elapsed_mins = (get_ist_now() - entry_time_dt).total_seconds() / 60.0
        if elapsed_mins > 30.0:
            overtime_intervals = int((elapsed_mins - 30.0) / 10.0)
            decay_factor = max(0.5, 1.0 - (overtime_intervals * 0.05))
            mult = mult * decay_factor
    except Exception:
        pass
        
    return round(mult, 2)

class OrderQueue:
    def __init__(self, client, limit_per_second=5):
        self.client = client
        self.delay = 1.0 / limit_per_second
        self.queue = asyncio.Queue()
        self.worker_task = None
        # Runaway-order circuit breaker (Tier-2 safety): trips if an abnormal burst of orders
        # is submitted (a code bug looping). Threshold sits well above a legitimate square-off
        # burst (~10-20 orders) and far below a runaway loop (hundreds). client may be None for
        # the module-level placeholder instance (reassigned with a real client in lifespan).
        # Local import: this class is instantiated at module-import time (the placeholder at
        # module level), before the bottom-of-file `import safety_guards` has run.
        import safety_guards
        _cfg = getattr(client, "config", {}) if client is not None else {}
        self.breaker = safety_guards.OrderRateBreaker(
            max_orders=int(_cfg.get("order_rate_max", 30)),
            window_seconds=float(_cfg.get("order_rate_window_s", 10)))
        self.on_runaway = None

    def start(self):
        self.worker_task = asyncio.create_task(self._worker())

    async def _worker(self):
        while True:
            try:
                task = await self.queue.get()
                func, args, kwargs, future = task
                loop = asyncio.get_running_loop()
                try:
                    res = await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))
                    if not future.done():
                        future.set_result(res)
                except Exception as e:
                    if not future.done():
                        future.set_exception(e)
                finally:
                    self.queue.task_done()
                await asyncio.sleep(self.delay)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Order Queue] Error in queue worker: {e}")
                await asyncio.sleep(1)

    async def submit(self, func, *args, **kwargs):
        if (getattr(self, "breaker", None) is not None and self.client is not None
                and self.client.config.get("enable_safety_guards", True)):
            if self.breaker.record_and_check():
                print("[OrderRateBreaker] Runaway order rate — refusing new orders.")
                if self.on_runaway:
                    try:
                        self.on_runaway()
                    except Exception:
                        pass
                raise RuntimeError("order-rate breaker tripped")
        if self.worker_task is None or self.worker_task.done():
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))
        future = asyncio.get_running_loop().create_future()
        await self.queue.put((func, args, kwargs, future))
        return await future


# Instantiate rate-limited order queue initially (falls back to direct executor if start() is not called)
order_queue = OrderQueue(None, limit_per_second=5)


# Nifty50 instrument key — used as market breadth filter
_NIFTY_KEY = "NSE_INDEX|Nifty 50"


def _quiet_connection_reset_handler(loop, context):
    """asyncio exception handler that swallows the benign Windows ConnectionResetError
    (WinError 10054) raised by the Proactor loop when a dashboard client forcibly closes
    its socket after a request already completed — only the socket teardown fails, so it's
    cosmetic log spam. Every other error is delegated to the default handler untouched, so
    real failures are never hidden."""
    exc = context.get("exception")
    if isinstance(exc, ConnectionResetError):
        return
    loop.default_exception_handler(context)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global order_queue, market_feed, bot_running, depth_recorder
    # Silence the harmless WinError 10054 teardown spam from client disconnects (dashboard
    # polling aborts connections constantly); real errors still surface via the default handler.
    try:
        asyncio.get_running_loop().set_exception_handler(_quiet_connection_reset_handler)
    except Exception:
        pass
    try:
        import state_db
        state_db.init_db()
    except Exception as e:
        print(f"Error initializing state database: {e}")
    load_state()

    # Auto-resume scanning after a crash/watchdog restart (2026-07-06: the process died
    # mid-session and trading stayed halted). Safe: the scanner loop re-derives every halt
    # condition (daily loss, weekly drawdown, token expiry) from persisted state each cycle,
    # so this cannot bypass a risk halt — it only removes the manual Start click.
    if client.config.get("auto_start_scanner", False):
        bot_running = True
        log_scan("SYSTEM", "auto_start_scanner: scanner started automatically.", "info")

    # Initialize and start rate-limited order execution queue
    order_queue = OrderQueue(client, limit_per_second=5)

    def _runaway_halt():
        global bot_running
        bot_running = False
        log_scan("SYSTEM", "Order-rate breaker tripped — bot halted. Investigate a runaway order loop.", "danger")
    order_queue.on_runaway = _runaway_halt
    order_queue.start()

    # Optional decoupled market-data feed (off by default — falls back to inline REST).
    if client.config.get("enable_market_feed", False):
        try:
            mode = client.config.get("market_feed_mode", "rest")
            interval = float(client.config.get("market_feed_interval", 1.0))
            market_feed = create_feed(client, mode=mode, interval=interval)
            market_feed.start()
            log_scan("SYSTEM", f"Market feed started (mode={mode}, interval={interval}s).", "info")
        except Exception as e:
            market_feed = None
            print(f"[startup] Failed to start market feed, using inline REST: {e}")

    # Optional depth-snapshot recorder (off by default). Passive observer that records
    # full 5-level order-book depth to data/depth/*.jsonl.gz for later microstructure
    # backtesting. Fully guarded — a recorder failure can never affect trading.
    if client.config.get("enable_depth_recorder", False):
        try:
            from depth_recorder import DepthRecorder
            depth_recorder = DepthRecorder(client, client.config)
            depth_recorder.start()
            log_scan("SYSTEM", f"Depth recorder started (interval={depth_recorder.interval}s).", "info")
        except Exception as e:
            depth_recorder = None
            print(f"[startup] Failed to start depth recorder: {e}")

    asyncio.create_task(scanner_loop())
    asyncio.create_task(position_manager_loop())
    yield
    try:
        if depth_recorder is not None:
            depth_recorder.stop()
    except Exception:
        pass


app = FastAPI(title="AutoTrade — Upstox Intraday Bot", lifespan=lifespan)

# M2: this bot moves real money and has no per-user login, so it must only trust requests
# coming from its own dashboard. The server runs at https://127.0.0.1:5000 (see __main__),
# so those are the only legitimate browser origins. Note: allow_origins=["*"] together with
# allow_credentials=True is also invalid per the CORS spec — browsers reject it — so locking
# this down is a correctness fix as well as a security one.
ALLOWED_ORIGINS = [
    "https://127.0.0.1:5000",
    "https://localhost:5000",
]
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _request_origin(request: Request):
    """Best-effort origin of a request: the Origin header, falling back to the Referer's
    scheme://host:port. Returns None for non-browser clients (curl, server-to-server),
    which are not CSRF vectors."""
    origin = request.headers.get("origin")
    if origin:
        return origin
    referer = request.headers.get("referer")
    if referer:
        from urllib.parse import urlparse
        p = urlparse(referer)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}"
    return None


@app.middleware("http")
async def csrf_origin_guard(request: Request, call_next):
    """CSRF defense: reject any state-changing request whose browser origin is not the
    dashboard. A malicious site you visit can make your browser POST to localhost, but it
    cannot forge the Origin header — so this blocks drive-by /api/squareoff, /api/toggle, etc.
    Requests with no Origin/Referer (curl, the bot itself) are allowed through."""
    if request.method not in SAFE_METHODS:
        origin = _request_origin(request)
        if origin is not None and origin not in ALLOWED_ORIGINS:
            return JSONResponse(
                status_code=403,
                content={"detail": f"Cross-origin {request.method} request blocked for safety."},
            )
    return await call_next(request)


@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ─── Timezone Helper ───────────────────────────────────────────────────────────
def get_ist_now():
    """Returns a timezone-naive datetime representing Indian Standard Time (IST)."""
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=5, minutes=30)


async def _off_loop(fn, *args, **kwargs):
    """Run blocking work (network I/O, backtests, RL training) in the default executor so
    the event loop — dashboard, WebSocket pushes, position exits — stays responsive.
    Any sync call that can take more than ~100ms must go through this inside async code;
    calling it directly on the loop freezes the entire server for its duration (observed
    live: 30s+ stalls from research-lab candle fetches through a slow proxy)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))

async def get_warmed_up_candles(instrument_key, interval="5minute"):
    """
    Fetches historical candles from past days and merges them with today's
    intraday candles to provide full indicator warmup (no morning blackout).
    
    H5 Improvement: For 5min/15min intervals, fetches 30 days of history to
    provide rich indicator warmup. For 1hour/day intervals used for HTF trend,
    fetches 90 days to capture meaningful multi-week structure.
    """
    loop = asyncio.get_running_loop()
    # 1. Fetch today's intraday candles (5min and 15min only)
    intra_candles = []
    if interval in ("5minute", "15minute", "1minute"):
        try:
            intra_candles = await loop.run_in_executor(
                None, functools.partial(client.get_intraday_candles, instrument_key, interval)
            )
        except Exception as e:
            print(f"Error fetching intraday candles for {instrument_key} ({interval}): {e}")
            intra_candles = []

    # 2. Determine lookback based on interval
    # H5: Extend history significantly for richer indicator context
    today_str = get_ist_now().date().isoformat()
    if interval in ("day", "1day"):
        lookback_days = 180  # 6 months of daily candles for macro trend
    elif interval in ("1hour", "60minute"):
        lookback_days = 90   # 3 months of hourly candles
    else:
        lookback_days = 30   # 30 days of 5min/15min for indicator warmup (was 5)
    
    from_date = (get_ist_now() - timedelta(days=lookback_days)).date().isoformat()
    
    try:
        hist_candles = await loop.run_in_executor(
            None, functools.partial(client.get_historical_candles, instrument_key, interval, from_date, today_str)
        )
    except Exception as e:
        print(f"Error fetching historical candles for {instrument_key} ({interval}): {e}")
        hist_candles = []

    if not hist_candles and not intra_candles:
        return []

    # 3. Merge by timestamp to ensure continuity and remove duplicates
    merged = {}
    for c in (hist_candles or []):
        merged[c["timestamp"]] = c
    for c in (intra_candles or []):
        merged[c["timestamp"]] = c

    sorted_timestamps = sorted(merged.keys())
    merged_list = [merged[ts] for ts in sorted_timestamps]
    
    # 4. Limit to last N candles based on interval
    # 5min: 300 candles = ~10 trading days, 1H: 120 candles = 3 months, day: 180 candles = 6 months
    limits = {"5minute": 300, "15minute": 200, "1hour": 180, "60minute": 180, "day": 180, "1day": 180}
    limit = limits.get(interval, 300)
    return merged_list[-limit:]


# ─── WebSocket Connection Manager ──────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

async def broadcast_research_status(status_payload: dict):
    """Broadcasts research lab status updates to all active WebSocket clients."""
    await manager.broadcast({
        "type": "research_progress",
        "status": status_payload["status"],
        "active_task": status_payload["active_task"],
        "progress": status_payload["progress"],
        "last_activity": status_payload["last_activity"],
        "last_active_time": status_payload["last_active_time"]
    })

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial data payload upon connection. Status comes from the same get_status()
        # that backs GET /api/status and the periodic state_update broadcast — one source of
        # truth. (This used to be a hand-maintained copy that had drifted ~16 fields behind
        # /api/status while also holding 3 fields /api/status lacked; the frontend's
        # SettingsForm still fetches /api/status directly as a belt-and-braces workaround,
        # which is now redundant but harmless.)
        status_payload = get_status()
        await websocket.send_json({
            "type": "init",
            "status": status_payload,
            "positions": list(active_positions.values()),
            "trades": [t for t in trade_history if t.get("exit_time", "").startswith(get_ist_now().date().isoformat())],
            "logs": scan_logs,
            "scanner": {"context": scan_context, "matrix": list(scan_matrix.values())},
        })
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

client = UpstoxClient()

from risk_manager import RiskManager
# The single mandatory risk gate — every order (paper or live) routes through this. See
# Section 0 of the build spec: "If RiskManager says no, the trade does not happen — no
# exceptions anywhere in the code." Config is passed as a callable so a live client.load_config()
# reload is always reflected without needing to re-instantiate this.
risk_manager = RiskManager(lambda: client.config)

import jsonl_logger  # data/wins.jsonl, losses.jsonl, decisions.log (Section 6)
import leaderboard   # data/strategy_stats.json — Lane A recency-weighted selector bias (Section 5A)
import history       # data/history/* daily learning snapshots — powers the date/as-of/compare UI (Section 6)
import lane_b        # Lane B EOD: Claude/heuristic lessons + parked proposals (gated, no spend by default)
import safety_guards  # real-time in-bot safety reactions (spec docs/superpowers/specs/2026-07-08-...)
import execution_costs  # realistic paper fills + NSE intraday transaction charges
import microstructure   # order-book depth: spread/liquidity gate + data-driven slippage

# ─── Global State ──────────────────────────────────────────────────────────────
bot_running = False
scan_logs = []
active_positions = {}   # symbol → position_dict
shadow_positions = {}   # symbol → position_dict (for simulated shadow trades)
trade_history = []
daily_pnl = 0.0

# Decoupled market-data feed (price cache + REST fallback). None until startup wires it
# when enable_market_feed is set; consumers fall back to direct REST when it's absent/stale.
market_feed = None

# Passive depth-snapshot recorder. None until startup wires it when enable_depth_recorder
# is set. Writes order-book snapshots to data/depth/*.jsonl.gz; never touches trading.
depth_recorder = None

# Symbols whose live exit is currently in-flight. A position is "claimed" the moment
# execute_exit() begins and stays claimed until the position is actually removed from
# active_positions (or un-claimed if the exit fails). Because all coroutines share one
# event loop, this synchronous flag — set before any await — prevents a second exit path
# (square_off_all, daily-loss halt, manual close) from firing a duplicate closing order.
# It is NOT persisted, so a crash mid-exit never blocks a later legitimate exit.
_exiting_symbols = set()

# Last cycle's total daily P&L — for the safety cycle-loss-spike guard in position_manager_loop.
_prev_total_pnl = None


def _remove_position(symbol):
    """Single choke point for removing a live position so the exit guard is always cleared."""
    active_positions.pop(symbol, None)
    _exiting_symbols.discard(symbol)


def _realized_daily_pnl(trades, today):
    """Sum of the day's REAL closed PnL. Excludes shadow (counterfactual) trades — no capital
    was engaged — and stale-startup reconciliation rows. Discovered 2026-07-07: a +7,672
    shadow trade inflated daily_pnl after a mid-day restart, which in live mode would have
    delayed the daily-loss kill switch by that amount."""
    return sum(
        t.get("pnl", 0.0) for t in trades
        if t.get("exit_time", "").startswith(today)
        and t.get("reason") != "STALE_STARTUP_SQUAREOFF"
        and not t.get("is_shadow_trade")
    )


def _position_is_stale_at_startup(pos, now, square_off_time_str="15:10"):
    """True if a position restored at startup must be force-closed instead of resumed:
    it came from a previous day, or the restart is happening at/after today's square-off
    time (the process died before square-off could run — 2026-07-06 incident). A missing
    entry_time only exempts the date check; past square-off the book must be flat."""
    entry_date = str(pos.get("entry_time", ""))[:10]
    if entry_date and entry_date != now.date().isoformat():
        return True
    try:
        h, m = square_off_time_str.split(":")
        sq = datetime_time(int(h), int(m))
    except Exception:
        return False
    return now.time() >= sq

def get_total_daily_pnl():
    """Returns the sum of realized P&L and unrealized P&L of open positions."""
    unrealized = sum(pos.get("pnl", 0.0) for pos in active_positions.values())
    return daily_pnl + unrealized


def get_capital_and_weekly_pnl():
    """Shared helper (used by scanner_loop, execute_entry, manual_trade) so every RiskManager
    call site computes weekly P&L and total equity/capital the same way — one formula, not
    three copies drifting apart over time."""
    today = get_ist_now().date().isoformat()
    seven_days_ago = (get_ist_now().date() - timedelta(days=7)).isoformat()
    weekly_pnl = sum(
        t.get("pnl", 0.0) for t in trade_history
        if t.get("exit_time", "").startswith(today) or t.get("exit_time", "") >= seven_days_ago
    )
    margin = 100000.0
    try:
        funds_res = client.get_funds_and_margin()
        if funds_res and funds_res.get("status") == "success":
            eq_data = funds_res.get("data", {}).get("equity", {})
            avail = float(eq_data.get("available_margin") or 0.0)
            used = float(eq_data.get("used_margin") or 0.0)
            margin = avail + used
            if margin <= 0:
                margin = 100000.0
    except Exception as ex:
        print(f"[get_capital_and_weekly_pnl] Error fetching funds and margin: {ex}")
    return margin, weekly_pnl

session_report = {}     # Populated at end-of-session
_last_reset_date = None # Tracks which calendar day daily_pnl was last zeroed
scanner_state = {       # Heartbeat info surfaced in /api/status for the dashboard
    "last_loop": None,          # last time the scanner loop ticked (even if bot stopped)
    "last_scan": None,          # last time a watchlist sweep completed
    "last_scan_epoch": None,    # monotonic ts of last completed scan (safety stall detector)
    "last_scan_checked": 0,
    "last_scan_summary": "",
}
scan_matrix = {}        # symbol → last per-symbol scan decision (served via /api/scanner)
scan_context = {}       # engine-level context of the last sweep (filters, sizing, timing)


def _matrix_set(symbol, decision, status, candles=None, strategy=None):
    """Records what the scanner decided for a symbol this sweep, with indicator
    snapshot when candles are available. status drives UI colour-coding."""
    inst = client.get_instrument_info(symbol)
    rec = {
        "symbol": symbol,
        "name": inst.get("name", symbol) if inst else symbol,
        "decision": decision,
        "status": status,   # entered | filtered | no_signal | skipped | no_data | in_position | error
        "time": get_ist_now().strftime("%H:%M:%S"),
        "ltp": None, "atr_pct": None, "rsi": None, "regime": None,
        "strategy": strategy,
    }
    if candles:
        try:
            close = [c["close"] for c in candles]
            rec["ltp"] = round(close[-1], 2)
            atr = calculate_atr(candles, 14)
            if atr and atr[-1]:
                rec["atr_pct"] = round(atr[-1] / close[-1] * 100, 2)
            rsi = calculate_rsi(close, 14)
            if rsi and rsi[-1]:
                rec["rsi"] = round(rsi[-1], 1)
            rec["regime"] = detect_market_regime(candles)
            # Indicator snapshot for the frontend confluence matrix (additive; safe if any fail).
            ema9 = calculate_ema(close, 9)
            if ema9 and ema9[-1] is not None:
                rec["ema_9"] = round(ema9[-1], 2)
            ema20 = calculate_ema(close, 20)
            if ema20 and ema20[-1] is not None:
                rec["ema_20"] = round(ema20[-1], 2)
            vwap = calculate_vwap(candles)
            if vwap and vwap[-1] is not None:
                rec["vwap"] = round(vwap[-1], 2)
            try:
                from strategy_support_resistance import _get_opening_range
                today_str = get_ist_now().date().isoformat()
                orh, orl = _get_opening_range(candles, today_str)
                if orh is not None:
                    rec["orb_high"] = round(orh, 2)
                if orl is not None:
                    rec["orb_low"] = round(orl, 2)
            except Exception:
                pass
        except Exception:
            pass
    scan_matrix[symbol] = rec

POSITIONS_FILE = "active_positions.json"
TRADES_FILE = "trade_history.json"


# ─── Persistence ───────────────────────────────────────────────────────────────

def save_positions_sql():
    try:
        import state_db
        conn = state_db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM live_positions")
        for pos in active_positions.values():
            p = dict(pos)
            if isinstance(p.get("market_context"), dict):
                p["market_context"] = json.dumps(p["market_context"])
            cursor.execute("""
                INSERT INTO live_positions (
                    symbol, instrument_key, is_fno, lot_size, contract, strategy, direction, quantity,
                    entry_price, entry_time, stop_loss, target, target_2, t1_hit, order_id, current_price,
                    pnl, atr_at_entry, trailing_high, trailing_low, market_context, regime, htf_trend,
                    mae, mfe, confluence_score, trigger_level_source, trigger_level_price, trigger_level_score
                ) VALUES (
                    :symbol, :instrument_key, :is_fno, :lot_size, :contract, :strategy, :direction, :quantity,
                    :entry_price, :entry_time, :stop_loss, :target, :target_2, :t1_hit, :order_id, :current_price,
                    :pnl, :atr_at_entry, :trailing_high, :trailing_low, :market_context, :regime, :htf_trend,
                    :mae, :mfe, :confluence_score, :trigger_level_source, :trigger_level_price, :trigger_level_score
                )
            """, p)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[SQL State] Error saving positions to SQLite: {e}")


def save_trades_sql():
    try:
        import state_db
        conn = state_db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM live_trades")
        for t in trade_history:
            trade = dict(t)
            if isinstance(trade.get("market_context"), dict):
                trade["market_context"] = json.dumps(trade["market_context"])
            cursor.execute("""
                INSERT INTO live_trades (
                    symbol, strategy, direction, quantity, entry_price, entry_time, exit_price, exit_time,
                    pnl, reason, regime, htf_trend, is_fno, contract, atr_at_entry, market_context,
                    holding_minutes, mae, mfe, confluence_score, trigger_level_source, trigger_level_price,
                    trigger_level_score, is_shadow_trade
                ) VALUES (
                    :symbol, :strategy, :direction, :quantity, :entry_price, :entry_time, :exit_price, :exit_time,
                    :pnl, :reason, :regime, :htf_trend, :is_fno, :contract, :atr_at_entry, :market_context,
                    :holding_minutes, :mae, :mfe, :confluence_score, :trigger_level_source, :trigger_level_price,
                    :trigger_level_score, :is_shadow_trade
                )
            """, trade)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[SQL State] Error saving trades to SQLite: {e}")


def load_state():
    global active_positions, trade_history, daily_pnl
    loaded_positions = {}
    loaded_trades = []
    
    try:
        import state_db
        conn = state_db.get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM live_positions")
        rows = cursor.fetchall()
        for r in rows:
            pos = dict(r)
            if pos.get("market_context"):
                try:
                    pos["market_context"] = json.loads(pos["market_context"])
                except Exception:
                    pass
            loaded_positions[pos["symbol"]] = pos
            
        cursor.execute("SELECT * FROM live_trades ORDER BY id ASC")
        rows = cursor.fetchall()
        for r in rows:
            t = dict(r)
            t.pop("id", None)
            if t.get("market_context"):
                try:
                    t["market_context"] = json.loads(t["market_context"])
                except Exception:
                    pass
            loaded_trades.append(t)
            
        conn.close()
    except Exception as e:
        print(f"[SQL State] Error loading state from SQLite: {e}")
        
    # 1. Resolve active positions (JSON is primary ground truth, SQLite is backup)
    loaded_from_json = False
    if os.path.exists(POSITIONS_FILE):
        try:
            with open(POSITIONS_FILE) as f:
                active_positions = json.load(f)
            loaded_from_json = True
            save_positions_sql()
        except Exception as e:
            if not loaded_positions:
                active_positions = {}
                log_scan("SYSTEM", f"active_positions.json unreadable ({e}) and no SQLite backup found — "
                                    f"starting with zero open positions. If a position was actually open, "
                                    f"reconcile manually against the broker.", "danger")
            else:
                active_positions = loaded_positions
                log_scan("SYSTEM", f"active_positions.json unreadable ({e}) — loaded backup positions from SQLite.", "warning")
    else:
        if loaded_positions:
            active_positions = loaded_positions
            # Sync to JSON
            try:
                with open(POSITIONS_FILE + ".tmp", "w") as f:
                    json.dump(active_positions, f, indent=2)
                os.replace(POSITIONS_FILE + ".tmp", POSITIONS_FILE)
            except Exception:
                pass
        else:
            active_positions = {}

    # 2. Resolve trade history (JSON is primary ground truth, SQLite is backup)
    loaded_trades_from_json = False
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE) as f:
                trade_history = json.load(f)
            loaded_trades_from_json = True
            save_trades_sql()
        except Exception as e:
            if not loaded_trades:
                trade_history = []
                log_scan("SYSTEM", f"trade_history.json unreadable ({e}) and no SQLite backup found — "
                                    f"starting with empty trade history.", "danger")
            else:
                trade_history = loaded_trades
                log_scan("SYSTEM", f"trade_history.json unreadable ({e}) — loaded backup trades from SQLite.", "warning")
    else:
        if loaded_trades:
            trade_history = loaded_trades
            # Sync to JSON
            try:
                with open(TRADES_FILE + ".tmp", "w") as f:
                    json.dump(trade_history, f, indent=2)
                os.replace(TRADES_FILE + ".tmp", TRADES_FILE)
            except Exception:
                pass
        else:
            trade_history = []

    # No-positions-past-square-off reconciliation (Section 0): a position restored from a
    # previous day OR restored after today's square-off time survived a crash/restart without
    # going through square-off. Force-close it now at its last known mark (no live quote needed
    # — these are stale by definition) rather than silently resuming it. Discovered twice on
    # this repo's real state: 6 positions dated 2026-06-30 in SQLite untouched, and on
    # 2026-07-06 three same-day positions resumed at a 20:50 restart (process died ~14:35,
    # before the 15:10 square-off) and sat unmanaged until a manual kill switch.
    _sq_off_str = client.config.get("square_off_time", "15:10")
    _reconciled_stale = False
    for _sym in list(active_positions.keys()):
        _pos = active_positions[_sym]
        _entry_date = str(_pos.get("entry_time", ""))[:10]
        if _position_is_stale_at_startup(_pos, get_ist_now(), _sq_off_str):
            _exit_price = _pos.get("current_price", _pos.get("entry_price"))
            if _pos.get("direction") == "LONG":
                _pnl = (_exit_price - _pos["entry_price"]) * _pos["quantity"]
            else:
                _pnl = (_pos["entry_price"] - _exit_price) * _pos["quantity"]
            trade_history.append({
                "symbol": _sym,
                "strategy": _pos.get("strategy"),
                "direction": _pos.get("direction"),
                "quantity": _pos.get("quantity"),
                "entry_price": _pos.get("entry_price"),
                "entry_time": _pos.get("entry_time"),
                "exit_price": _exit_price,
                "exit_time": get_ist_now().isoformat(),
                "pnl": round(_pnl, 2),
                "reason": "STALE_STARTUP_SQUAREOFF",
                "stop_loss": _pos.get("stop_loss"),
                "target_1": _pos.get("target"),
                "target_2": _pos.get("target_2"),
                "t1_hit": _pos.get("t1_hit", False),
                "regime": _pos.get("regime", "unknown"),
                "htf_trend": _pos.get("htf_trend", "neutral"),
                "is_fno": _pos.get("is_fno", False),
                "contract": _pos.get("contract", ""),
                "atr_at_entry": _pos.get("atr_at_entry"),
                "market_context": _pos.get("market_context", {}),
                "holding_minutes": None,
                "mae": round(_pos.get("mae", 0.0), 2),
                "mfe": round(_pos.get("mfe", 0.0), 2),
                "confluence_score": _pos.get("confluence_score", 0),
                "trigger_level_source": _pos.get("trigger_level_source"),
                "trigger_level_price": _pos.get("trigger_level_price"),
                "trigger_level_score": _pos.get("trigger_level_score"),
                "is_shadow_trade": False,
            })
            del active_positions[_sym]
            log_scan("SYSTEM", f"Stale position {_sym} ({_pos.get('direction')} "
                                f"{_pos.get('quantity')} from {_entry_date or 'unknown date'}) "
                                f"force-closed at last known price ₹{_exit_price} on startup — "
                                f"no position may survive past square-off (Section 0).", "danger")
            _reconciled_stale = True

    # Backfill symbol memory stats on startup
    try:
        from symbol_memory import init_memory_db, bulk_import_from_trade_history, get_db_connection
        init_memory_db()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM symbol_trade_log;")
        count = cursor.fetchone()[0]
        conn.close()
        if count == 0 and trade_history:
            log_scan("SYSTEM", f"Backfilling {len(trade_history)} historical trades to symbol memory...", "info")
            bulk_import_from_trade_history(trade_history)
    except Exception as e:
        print(f"Error backfilling symbol memory: {e}")
        
    # Clear the per-position bad-tick warning latch on startup (a fresh process should
    # re-warn if a feed problem recurs). Live-tick staleness is no longer tracked via a
    # monotonic timestamp — see safety_guards.evaluate_live_tick.
    for pos in active_positions.values():
        pos["_quote_warned"] = False

    today = get_ist_now().date().isoformat()
    daily_pnl = _realized_daily_pnl(trade_history, today)

    # Persist the reconciliation (JSON files + SQLite) so a corrupt/stale on-disk state doesn't
    # resurface on the next restart.
    if _reconciled_stale:
        save_state()


def save_state():
    import tempfile
    # M1: write the temp file in the SAME directory as the target so os.replace() is a true
    # atomic same-filesystem rename. Using the system temp dir breaks os.replace() across
    # drives (Windows WinError 17), which would make every persistence silently fail.
    temp_dir = os.path.dirname(os.path.abspath(POSITIONS_FILE)) or "."

    # Save positions atomically to JSON
    temp_path = None
    try:
        fd, temp_path = tempfile.mkstemp(dir=temp_dir, prefix="positions_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(active_positions, f, indent=2)
        os.replace(temp_path, POSITIONS_FILE)
    except Exception as e:
        print(f"Error saving positions JSON state: {e}")
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        
    # Save trades atomically to JSON
    temp_path = None
    try:
        fd, temp_path = tempfile.mkstemp(dir=temp_dir, prefix="trades_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(trade_history, f, indent=2)
        os.replace(temp_path, TRADES_FILE)
    except Exception as e:
        print(f"Error saving trades JSON state: {e}")
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

    # Mirror to SQLite database
    save_positions_sql()
    save_trades_sql()

    # Broadcast state change to WebSocket clients
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(manager.broadcast({
                "type": "state_update",
                "status": get_status(),
                "positions": list(active_positions.values()),
                "trades": get_trades()
            }))
    except Exception:
        pass


# ─── Logging ───────────────────────────────────────────────────────────────────

def log_scan(symbol, message, category="info"):
    entry = {
        "time": get_ist_now().strftime("%H:%M:%S"),
        "symbol": symbol,
        "message": message,
        "category": category,
    }
    scan_logs.insert(0, entry)
    if len(scan_logs) > 200:
        scan_logs.pop()
    try:
        print(f"[{entry['time']}] [{symbol}] {message}")
    except UnicodeEncodeError:
        safe_msg = message.replace("₹", "Rs.")
        try:
            print(f"[{entry['time']}] [{symbol}] {safe_msg}")
        except Exception:
            pass

    # Broadcast to WebSocket clients
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(manager.broadcast({
                "type": "logs",
                "logs": scan_logs
            }))
    except Exception:
        pass


# ─── Time Helpers ──────────────────────────────────────────────────────────────

def _parse_time(t_str):
    try:
        return datetime.strptime(t_str, "%H:%M").time()
    except Exception:
        return None


def is_within_window(start_str, end_str):
    now = get_ist_now().time()
    s, e = _parse_time(start_str), _parse_time(end_str)
    return s is not None and e is not None and s <= now <= e


def is_past(t_str):
    now = get_ist_now().time()
    t = _parse_time(t_str)
    return t is not None and now >= t


# ─── Market Index Trend ────────────────────────────────────────────────────────

async def _get_nifty_trend():
    """Returns Nifty50 15-min trend: 'up', 'down', or 'neutral'. Non-blocking."""
    try:
        candles = await get_warmed_up_candles(_NIFTY_KEY, "15minute")
        if candles and len(candles) >= 15:
            return get_htf_trend(candles)
    except Exception:
        pass
    return "neutral"



# ─── Position Sizing ───────────────────────────────────────────────────────────

def _calc_quantity(entry_price, stop_loss, config, override_risk=None, available_margin=None, is_fno=False, is_options=False, lot_size=1):
    """
    Sizes trades based on either Max Capacity (leverage) or Risk-based formula.
    """
    if config.get("enable_max_capacity", False) and available_margin is not None:
        buffer = float(config.get("capacity_buffer_pct", 0.05))
        # Cash-equity MIS leverage is configurable (default 4x of account balance). Note: the
        # ACTUAL intraday margin Upstox grants varies per stock and by SEBI peak-margin rules —
        # if a stock's real leverage is lower, Upstox will reject an oversized order, so treat
        # this as an upper bound, not a guarantee.
        cash_leverage = float(config.get("leverage_multiplier", 4.0))
        if is_options:
            leverage = 1.0  # 100% premium upfront
        elif is_fno:
            leverage = 5.0  # Futures ~20% SPAN margin
        else:
            leverage = cash_leverage  # Cash MIS leverage (default 4x)

        buying_power = available_margin * leverage * (1.0 - buffer)
        if entry_price > 0:
            qty = int(buying_power / entry_price)
            # R1: a configured "max position value" must NEVER be silently exceeded, even in
            # max-capacity mode — otherwise a single trade can consume the entire leveraged
            # buying power and the cap the user set does nothing. Set max_position_value to 0
            # to opt out and allow true uncapped max-capacity sizing.
            max_value = float(config.get("max_position_value", 50000.0))
            if max_value > 0:
                qty = min(qty, int(max_value / entry_price))
            if is_fno or is_options:
                qty = (qty // lot_size) * lot_size
            return max(lot_size, qty)
        return lot_size

    max_risk  = override_risk if override_risk is not None else float(config.get("max_risk_per_trade", 500.0))
    max_value = float(config.get("max_position_value", 50000.0))

    risk_per_share = abs(entry_price - stop_loss)
    if risk_per_share < 0.01:
        risk_per_share = 0.01

    qty = int(max_risk / risk_per_share)
    qty_by_value = int(max_value / entry_price) if entry_price > 0 else qty
    qty = max(1, min(qty, qty_by_value))
    return qty


# ─── Position Indicator Update ──────────────────────────────────────────────────

async def update_position_indicators(pos):
    """
    Fetches intraday candles and updates indicators for the position.
    """
    loop = asyncio.get_running_loop()
    try:
        candles = await loop.run_in_executor(
            None, functools.partial(client.get_intraday_candles, pos["instrument_key"], "5minute")
        )
        if candles and len(candles) >= 15:
            closes = [c["close"] for c in candles]
            from strategies import calculate_ema, calculate_vwap, calculate_atr, calculate_adx
            ema_9 = calculate_ema(closes, 9)
            vwap = calculate_vwap(candles)
            if ema_9 and len(ema_9) > 0 and ema_9[-1] is not None:
                pos["ema_9"] = round(ema_9[-1], 2)
            if vwap and len(vwap) > 0 and vwap[-1] is not None:
                pos["vwap"] = round(vwap[-1], 2)

            # Calculate RVOL
            if len(candles) >= 21:
                curr_vol = candles[-1]["volume"]
                avg_vol = sum(c["volume"] for c in candles[-21:-1]) / 20.0
                rvol = curr_vol / avg_vol if avg_vol > 0 else 1.0
                pos["rvol"] = round(rvol, 2)

            # Calculate dynamic market regime
            if len(candles) >= 30:
                from institutional_engine import InstitutionalTradingEngine
                engine = InstitutionalTradingEngine()
                adx_vals = calculate_adx(candles, 14)
                atr_vals = calculate_atr(candles, 14)
                ema20_vals = calculate_ema(closes, 20)
                ema50_vals = calculate_ema(closes, 50)

                adx_val = adx_vals[-1] if adx_vals else None
                atr_val = atr_vals[-1] if atr_vals else None
                ema20_val = ema20_vals[-1] if ema20_vals else None
                ema50_val = ema50_vals[-1] if ema50_vals else None

                new_regime = engine.detect_regime(candles, adx_val, atr_val, ema20_val, ema50_val)
                pos["regime"] = new_regime
    except Exception as e:
        print(f"Error updating indicators for {pos['symbol']}: {e}")



# ─── Trailing Stop ─────────────────────────────────────────────────────────────

class UpdateResult(int):
    """A backward-compatible result class that acts like a boolean (representing sl_changed)
    but can be unpacked as a tuple (state_changed, sl_changed)."""
    def __new__(cls, state_changed, sl_changed):
        obj = super().__new__(cls, 1 if sl_changed else 0)
        obj.state_changed = state_changed
        obj.sl_changed = sl_changed
        return obj
    def __iter__(self):
        yield self.state_changed
        yield self.sl_changed

def _update_trailing_stop(pos, ltp, trailing_atr_mult):
    """
    Ratchets the stop loss upward (for longs) / downward (for shorts) as price
    moves in our favour, at a distance of trailing_atr_mult × ATR from the new peak.
    Returns (state_changed, sl_changed) indicating if trailing high/low or stop_loss changed.
    """
    # Safe ATR fallback to avoid zero trail gap when stop loss is moved to break-even
    atr_val = pos.get("atr_at_entry") or pos.get("market_context", {}).get("atr") or (pos["entry_price"] * 0.01)
    trail_gap = atr_val * trailing_atr_mult
    state_changed = False
    sl_changed = False

    # Trailing activation trigger: only trail once price moves in our favour by at least 0.5x trail_gap,
    # or if trailing has already been activated, or if Target 1 has been hit.
    if not pos.get("trailing_active") and not pos.get("t1_hit"):
        if pos["direction"] == "LONG" and ltp >= pos["entry_price"] + (trail_gap * 0.5):
            pos["trailing_active"] = True
            state_changed = True
        elif pos["direction"] == "SHORT" and ltp <= pos["entry_price"] - (trail_gap * 0.5):
            pos["trailing_active"] = True
            state_changed = True
        else:
            return UpdateResult(False, False)

    if pos["direction"] == "LONG":
        curr_high = pos.get("trailing_high")
        if curr_high is None:
            curr_high = pos["entry_price"]
        if ltp > curr_high:
            pos["trailing_high"] = ltp
            state_changed = True
        new_sl = (pos.get("trailing_high") or curr_high) - trail_gap
        if new_sl > pos["stop_loss"]:
            pos["stop_loss"] = round(new_sl, 2)
            sl_changed = True
            state_changed = True
    else:
        curr_low = pos.get("trailing_low")
        if curr_low is None:
            curr_low = pos["entry_price"]
        if ltp < curr_low:
            pos["trailing_low"] = ltp
            state_changed = True
        new_sl = (pos.get("trailing_low") or curr_low) + trail_gap
        if new_sl < pos["stop_loss"]:
            pos["stop_loss"] = round(new_sl, 2)
            sl_changed = True
            state_changed = True

    return UpdateResult(state_changed, sl_changed)


# ─── Market Context Snapshot ───────────────────────────────────────────────────

def _build_market_context(candles):
    """Captures regime, RSI, ATR at the moment of signal."""
    if not candles:
        return {}
    close = [c["close"] for c in candles]
    ema_20 = calculate_ema(close, 20)
    vwap = calculate_vwap(candles)
    rsi = calculate_rsi(close, 14)
    atr = calculate_atr(candles, 14)
    return {
        "ema_20": round(ema_20[-1], 2) if ema_20[-1] else None,
        "vwap": round(vwap[-1], 2) if vwap else None,
        "rsi": round(rsi[-1], 1) if rsi[-1] else None,
        "atr": round(atr[-1], 2) if atr[-1] else None,
        "regime": detect_market_regime(candles),
    }


# ─── Core Trading Loop ─────────────────────────────────────────────────────────

async def scanner_loop():
    global bot_running, daily_pnl, session_report, _last_reset_date, shadow_positions
    log_scan("SYSTEM", "Background scanner started.", "info")
    session_ended = False

    while True:
        scanner_state["last_loop"] = get_ist_now().strftime("%H:%M:%S")

        client.load_config()
        cfg = client.config
        paper_trading = cfg.get("paper_trading", True)
        today = get_ist_now().date().isoformat()
        sq_off_time_str = cfg.get("square_off_time", "15:10")
        start_time_str = cfg.get("trade_start_time", "09:30")
        end_time_str = cfg.get("trade_end_time", "14:30")

        # Scanner-stall detector (Tier-3, alert only): if the bot is running but no scan has
        # completed in > scanner_stall_minutes, the loop is wedged (feed/API). Loud, throttled
        # alert (~once/min); never halts. The watchdog covers a hard process hang.
        if cfg.get("enable_safety_guards", True) and safety_guards.scanner_stalled(
                scanner_state.get("last_scan_epoch"), time.monotonic(), bot_running,
                stall_minutes=float(cfg.get("scanner_stall_minutes", 8))):
            if get_ist_now().second < 15:
                log_scan("SYSTEM", "SAFETY: scanner stalled — no completed scan in >"
                         f"{cfg.get('scanner_stall_minutes', 8)} min. Check data feed / API.", "danger")

        # ── Daily reset: zero PnL and session state at the start of each new day ──
        if _last_reset_date != today:
            daily_pnl = _realized_daily_pnl(trade_history, today)
            session_ended = False
            _last_reset_date = today
            log_scan("SYSTEM", f"New trading day {today}. Daily PnL reset to ₹{daily_pnl:.2f}.", "info")

            # Auto-refresh watchlist with current Nifty 50 constituents
            if cfg.get("auto_nifty50_watchlist", True):
                try:
                    loop = asyncio.get_running_loop()
                    n50 = await loop.run_in_executor(None, client.fetch_nifty50_symbols)
                    if n50:
                        valid = [s for s in n50 if client.get_instrument_info(s)] if client.instrument_map else n50
                        if valid:
                            client.config["watchlist"] = valid
                            client.save_config()
                            log_scan("SYSTEM", f"Watchlist auto-updated: {len(valid)} Nifty 50 stocks from NSE.", "info")
                    else:
                        log_scan("SYSTEM", "Nifty 50 list fetch failed — keeping existing watchlist.", "warning")
                except Exception as ex:
                    print(f"Error auto-refreshing watchlist: {ex}")

        # ── End-of-Day EOD Clock Task (Runs regardless of bot_running) ──
        if is_past(sq_off_time_str):
            # Square off positions if bot is running (safety)
            if bot_running:
                if active_positions:
                    log_scan("SYSTEM", f"Square-off time {sq_off_time_str} reached. Closing all positions.", "warning")
                    await square_off_all("AUTO SQUARE-OFF")
                if shadow_positions:
                    log_scan("SYSTEM", f"Square-off time {sq_off_time_str} reached. Closing all shadow positions.", "warning")
                    for symbol in list(shadow_positions.keys()):
                        pos = shadow_positions[symbol]
                        ep = pos.get("current_price", pos["entry_price"])
                        await execute_exit(symbol, pos, ep, "AUTO SQUARE-OFF", paper_trading=True, is_shadow=True)
                        shadow_positions.pop(symbol, None)
            
            # Generate end-of-session report & trigger AI EOD learning loop once
            if not session_ended:
                today_trades = [t for t in trade_history if t.get("exit_time", "").startswith(today)]
                session_report = generate_session_report(today_trades)
                _log_session_report(session_report)

                # Lane A EOD rebuild + Section-6 daily history snapshots. Runs unconditionally
                # (independent of RL config) so the date-range / as-of-date / compare UI always
                # has a frozen record of what the bot "knew" at each day's close (DoD #9).
                try:
                    stats = leaderboard.rebuild(config=client.config)
                    start_capital = client.config.get("capital", 100000)
                    snap = history.write_all(today, capital_start=start_capital, stats=stats)
                    log_scan("SYSTEM", f"Daily history snapshot written for {today} ({snap['trades_counted']} trades).", "success")
                except Exception as snap_err:
                    log_scan("SYSTEM", f"Error writing daily history snapshot: {snap_err}", "danger")

                # Lane B (Section 5): lessons + parked proposals + Promotion-Gate evaluation.
                # Gated inside llm_engine — with llm_enabled off (default) this runs the heuristic
                # path and makes ZERO API calls. It never trades or promotes to live silently.
                try:
                    day_trades = history.trades_in_range(history.load_all_trades(), today, today)
                    lb = lane_b.run_eod(today, day_trades, client.config)
                    log_scan("SYSTEM",
                             f"Lane B EOD: {lb['lessons_written']} lessons, proposal={lb['proposal_source']}, "
                             f"{lb['proposals_evaluated']} evaluated (llm_enabled={lb['llm_enabled']}).",
                             "success")
                except Exception as lb_err:
                    log_scan("SYSTEM", f"Error in Lane B EOD learning: {lb_err}", "danger")

                # AI Daily Learning Loop
                try:
                    from analysis_engine import analyze_trades_eod
                    # Brain directory path for the EOD report (dynamic fallback if hardcoded path doesn't exist)
                    report_dir = r"C:\Users\nikhi\.gemini\antigravity\brain\e901ce8d-1aeb-478f-a464-ff1906e9b92c"
                    if not os.path.exists(report_dir):
                        report_dir = os.path.abspath(os.path.join(os.getcwd(), 'reports'))
                    analyze_trades_eod(trade_history, report_dir)
                    
                except Exception as ex:
                    log_scan("SYSTEM", f"Error in daily learning loop: {ex}", "danger")
                    
                session_ended = True
            await asyncio.sleep(15)
            continue

        # Reset end-of-session flag for next day
        if not is_past(sq_off_time_str):
            session_ended = False

        # If bot is stopped, pause and loop again (bypassing trading tasks)
        if not bot_running:
            await asyncio.sleep(5)
            continue

        # Weekly drawdown limit check (past 5 trading days / last 7 calendar days)
        try:
            margin, weekly_pnl = get_capital_and_weekly_pnl()
            weekly_decision = risk_manager.check_weekly_drawdown(weekly_pnl, margin)
            if not weekly_decision.allowed:
                log_scan("SYSTEM", f"{weekly_decision.reason} Halting bot.", "danger")
                bot_running = False
                await square_off_all("WEEKLY DRAWDOWN HALT")
                continue
        except Exception as ex:
            print(f"[scanner_loop] Error checking weekly drawdown: {ex}")

        # ── Token expiry check + Auto-Reauth (L2) ───────────────────────────────
        if client.access_token and client._token_expired():
            # L2: Attempt automatic token refresh before halting bot
            log_scan("SYSTEM", "Access token has expired. Checking for a fresh login...", "warning")
            reauth_success = False
            try:
                if hasattr(client, 'try_refresh_token'):
                    reauth_success = client.try_refresh_token()
            except Exception as reauth_err:
                print(f"[Auto-Reauth] Refresh attempt failed: {reauth_err}")
            
            if reauth_success:
                log_scan("SYSTEM", "Fresh token detected and verified with Upstox. Bot continues.", "success")
            else:
                log_scan("SYSTEM", "Access token expired — no valid token found. Re-authenticate via the Login button (open /login).", "danger")
                client.config["access_token"] = ""
                client.access_token = ""
                client.save_config()
                bot_running = False
                await asyncio.sleep(5)
                continue
        watchlist = cfg.get("watchlist", [])
        max_positions = int(cfg.get("max_open_positions", 3))

        if not client.access_token:
            log_scan("SYSTEM", "Access token missing — please authenticate first.", "danger")
            bot_running = False
            await asyncio.sleep(5)
            continue

        # Daily loss circuit breaker — routed through RiskManager so it applies identically in
        # paper and live (Section 0 rule 2).
        total_pnl = get_total_daily_pnl()
        daily_decision = risk_manager.check_daily_loss(total_pnl)
        if not daily_decision.allowed:
            log_scan("SYSTEM", f"{daily_decision.reason} Squaring off.", "danger")
            bot_running = False
            await square_off_all("DAILY LOSS LIMIT")
            await asyncio.sleep(10)
            continue

        # Download instruments once
        if not client.instrument_map:
            log_scan("SYSTEM", "Downloading NSE instrument master list…", "info")
            client.download_instruments()

        # Position exits are managed in high frequency by position_manager_loop

        # New entries only within scan window
        if not is_within_window(start_time_str, end_time_str):
            await asyncio.sleep(5)
            continue

        if len(active_positions) < max_positions:
            await scan_for_entries(watchlist, max_positions, paper_trading)

        await asyncio.sleep(10)


async def scan_for_entries(watchlist, max_positions, paper_trading):
    cfg = client.config
    loop = asyncio.get_running_loop()
    sweep_start = get_ist_now()

    # Fetch India VIX index quote from Upstox
    global vix_value
    vix_val = None
    vix_active = False
    try:
        vix_quote = await loop.run_in_executor(
            None, functools.partial(client.get_market_quote, "NSE_INDEX|India VIX")
        )
        if vix_quote:
            vix_val = vix_quote.get("ltp")
            if vix_val:
                vix_value = vix_val
            if vix_val and vix_val > 22.0:
                vix_active = True
    except Exception as e:
        print(f"Error fetching India VIX: {e}")

    from signal_quality import is_tradeable_time, get_allowed_strategies

    def _set_context(**extra):
        allowed = get_allowed_strategies()
        scan_context.update({
            "updated": get_ist_now().strftime("%H:%M:%S"),
            "sweep_seconds": round((get_ist_now() - sweep_start).total_seconds(), 1),
            "allowed_strategies": "ALL" if allowed is None else (allowed or "NONE"),
            "kelly_risk": calculate_kelly_risk(trade_history, float(cfg.get("max_risk_per_trade", 500.0)))
                          if cfg.get("enable_kelly_sizing", True) else float(cfg.get("max_risk_per_trade", 500.0)),
            "open_positions": len(active_positions),
            "max_positions": max_positions,
            "india_vix": vix_val,
            "vix_filter_active": vix_active,
        })
        scan_context.update(extra)

    # ── Layer 1: Time gate (single check per scan cycle) ──────────────────
    if cfg.get("enable_time_filter", True):
        time_ok, time_reason = is_tradeable_time()
        if not time_ok:
            log_scan("SYSTEM", time_reason, "warning")
            _set_context(gate=time_reason, nifty_trend="—", halted=False,
                         checked=0, signals=0, filtered=0)
            return

    # ── Layer 4: Consecutive loss halt (once per cycle), via RiskManager ──
    loss_decision = risk_manager.check_consecutive_losses(trade_history, paper_trading)
    if not loss_decision.allowed:
        log_scan("SYSTEM", loss_decision.reason, "warning")
        jsonl_logger.log_decision("skip", "ALL", loss_decision.reason, {"gate": "consecutive_loss_halt"})
        _set_context(gate=loss_decision.reason, nifty_trend="—", halted=True,
                     checked=0, signals=0, filtered=0)
        return

    # ── Layer 6: Nifty broad market trend (once per cycle, non-blocking) ──
    nifty_trend = "neutral"
    if cfg.get("enable_nifty_filter", True):
        nifty_trend = await _get_nifty_trend()

    if vix_active:
        log_scan("SYSTEM", f"India VIX is elevated at {vix_val:.2f}. Tightening targets by 20% and incrementing confluence gate.", "warning")

    # Determine what symbols to scan (custom watchlist vs full NSE/BSE market scan)
    full_market = bool(cfg.get("enable_full_market_scan", False))
    if full_market:
        scan_nse = bool(cfg.get("scan_nse", True))
        scan_bse = bool(cfg.get("scan_bse", False))
        min_v = int(cfg.get("min_scan_volume", 50000))
        min_p = float(cfg.get("min_scan_price", 20.0))
        min_chg = float(cfg.get("min_scan_change_pct", 1.5))
        
        all_symbols = list(client.instrument_map.keys())
        symbols_to_query = []
        for s in all_symbols:
            inst = client.instrument_map[s]
            key = inst.get("instrument_key", "")
            if key.startswith("NSE_EQ") and scan_nse:
                symbols_to_query.append(s)
            elif key.startswith("BSE_EQ") and scan_bse:
                symbols_to_query.append(s)
                
        # Batch fetch quotes for all symbols to apply coarse filter (Upstox supports up to 500 keys per request)
        chunks = [symbols_to_query[i:i + 500] for i in range(0, len(symbols_to_query), 500)]
        all_quotes = {}
        for chunk in chunks:
            chunk_keys = [client.instrument_map[s]["instrument_key"] for s in chunk]
            try:
                res = await loop.run_in_executor(
                    None, functools.partial(client.get_market_quotes, chunk_keys)
                )
                if res:
                    all_quotes.update(res)
            except Exception as e:
                print(f"Error fetching batch quotes in coarse scanner: {e}")
            await asyncio.sleep(0.3) # Give API breathing room and respect rate limits
            
        # Filter symbols based on price, volume, and percentage change
        candidates = []
        for s in symbols_to_query:
            inst = client.instrument_map[s]
            key = inst["instrument_key"]
            quote = all_quotes.get(key)
            if not quote:
                continue
            ltp = quote.get("ltp", 0.0)
            volume = quote.get("volume", 0)
            net_change = quote.get("net_change", 0.0)
            prev_close = ltp - net_change
            
            if ltp < min_p or volume < min_v:
                continue
                
            change_pct = (net_change / prev_close * 100) if prev_close > 0 else 0.0
            
            if abs(change_pct) >= min_chg:
                candidates.append({
                    "symbol": s,
                    "ltp": ltp,
                    "volume": volume,
                    "change_pct": change_pct
                })
                
        # Sort candidates by change_pct absolute value
        candidates.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
        watchlist = [c["symbol"] for c in candidates[:40]]
        log_scan("SYSTEM", f"Full market scan: {len(symbols_to_query)} checked | {len(candidates)} filtered | scanning top {len(watchlist)} candidates.", "info")
    else:
        watchlist = list(watchlist)

    scanned = 0
    signals_found = 0
    signals_filtered = 0
    today = get_ist_now().date().isoformat()

    for symbol in watchlist:
        if not risk_manager.check_max_open_positions(len(active_positions)).allowed:
            break
        if symbol in active_positions:
            _matrix_set(symbol, "holding open position", "in_position")
            continue

        # Enforce Sector Concentration Filter (via RiskManager — only for mapped sectors)
        sector_decision = risk_manager.check_sector_cap(symbol, active_positions)
        if not sector_decision.allowed:
            _matrix_set(symbol, sector_decision.reason, "filtered")
            continue

        # Per-symbol daily trade limit (via RiskManager)
        symbol_cap_decision = risk_manager.check_symbol_daily_cap(symbol, trade_history, today)
        if not symbol_cap_decision.allowed:
            _matrix_set(symbol, symbol_cap_decision.reason, "skipped")
            continue

        # Per-symbol earnings/event blackout: never auto-open a position into a stock's
        # results/board-meeting day (dates from earnings_calendar.json). Fail-open — a symbol
        # not listed there is never blocked. Especially important on leveraged live money,
        # where a single earnings gap on a 4x position is outsized. Manual trades are exempt.
        if cfg.get("enable_earnings_blackout", True):
            try:
                from event_calendar import get_symbol_event_blackout
                _blk, _blk_reason = get_symbol_event_blackout(
                    symbol, get_ist_now(),
                    days_before=int(cfg.get("earnings_blackout_days_before", 1)),
                    days_after=int(cfg.get("earnings_blackout_days_after", 0)))
                if _blk:
                    log_scan(symbol, f"Filtered: {_blk_reason}", "info")
                    _matrix_set(symbol, f"filtered: {_blk_reason}", "filtered")
                    jsonl_logger.log_decision("skip", symbol, _blk_reason, {"gate": "earnings_blackout"})
                    continue
            except Exception as _blk_err:
                print(f"[earnings-blackout] non-fatal error for {symbol}: {_blk_err}")

        inst = client.get_instrument_info(symbol)
        if not inst:
            _matrix_set(symbol, "not in instrument map", "no_data")
            continue

        try:
            scanned += 1
            # Broadcast progress: currently checking
            try:
                name = inst.get("name", symbol)
                loop.create_task(manager.broadcast({
                    "type": "checking_progress",
                    "symbol": symbol,
                    "name": name,
                    "status": "checking",
                    "time": get_ist_now().strftime("%H:%M:%S")
                }))
            except Exception:
                pass

            # Rate-limiting throttle spacing to comply with 10 req/s limit:
            await asyncio.sleep(0.1)
            # Non-blocking warmed-up candle fetches (5min for signal, 15min+1H+daily for HTF context)
            candles_5m = await get_warmed_up_candles(inst["instrument_key"], "5minute")
            if not candles_5m or len(candles_5m) < 15:
                _matrix_set(symbol, f"insufficient candles ({len(candles_5m or [])}/15)", "no_data", candles_5m)
                continue
            candles_15m = await get_warmed_up_candles(inst["instrument_key"], "15minute")
            
            # H5: Fetch 1-hour and daily candles for macro trend analysis
            candles_1h = None
            candles_daily = None
            try:
                candles_1h = await get_warmed_up_candles(inst["instrument_key"], "1hour")
            except Exception as htf_err:
                print(f"[HTF] Error fetching 1H candles for {symbol}: {htf_err}")
            try:
                candles_daily = await get_warmed_up_candles(inst["instrument_key"], "day")
            except Exception as htf_err:
                print(f"[HTF] Error fetching daily candles for {symbol}: {htf_err}")
            
            # M7: Fetch PDH/PDL for institutional liquidity level detection
            pdh, pdl, pdc = None, None, None
            try:
                from strategy_support_resistance import _get_daily_levels as _get_sr_daily_levels
                pdh, pdl, pdc = _get_sr_daily_levels(client, inst["instrument_key"], today)
            except Exception:
                pass  # Non-critical: liquidity check will just skip PDH/PDL

            # H7: Run Institutional Engine for enhanced signal scoring
            inst_score = 0
            inst_details = []
            try:
                from institutional_engine import InstitutionalTradingEngine
                ie = InstitutionalTradingEngine()
                
                # Market Structure (BOS/CHOCH)
                structure, bos_bull, bos_bear = ie.check_market_structure(candles_5m)
                # Relative Volume
                rvol, rvol_grade = ie.check_rvol(candles_5m)
                # Liquidity sweeps using real PDH/PDL
                liquidity = ie.check_liquidity(candles_5m, pdh=pdh, pdl=pdl)
                # Relative Strength vs Nifty
                nifty_candles_5m = await get_warmed_up_candles(_NIFTY_KEY, "5minute")
                rel_strength = ie.check_relative_strength(candles_5m, nifty_candles_5m)
                
                # Score institutional factors
                if bos_bull:
                    inst_score += 2
                    inst_details.append("BOS Bullish")
                elif bos_bear:
                    inst_score -= 1
                    inst_details.append("BOS Bearish")
                if rvol_grade in ("Strong", "Very Strong"):
                    inst_score += 1
                    inst_details.append(f"RVOL {rvol:.1f}x ({rvol_grade})")
                if liquidity in ("PDL Sweep", "Weekly Low Sweep"):
                    inst_score += 1  # Bullish sweep
                    inst_details.append(f"Liquidity Sweep: {liquidity}")
                if rel_strength == "Strong":
                    inst_score += 1
                    inst_details.append("RS Strong vs Nifty")
                elif rel_strength == "Weak":
                    inst_score -= 1
                    inst_details.append("RS Weak vs Nifty")
            except Exception:
                pass  # Non-critical: institutional engine is additive

            # Lane A (Section 5A): prefer the leaderboard's recency-weighted, regime/time-bucket
            # -specific ordering once a combo has enough samples; otherwise fall back to the
            # existing regime-agnostic adaptive order. Either way this only re-prioritizes which
            # already-validated strategy select_best_strategy tries first — never changes code
            # (Section 0 rule 5).
            regime_for_leaderboard = detect_market_regime(candles_5m)
            time_bucket_for_leaderboard = jsonl_logger.time_of_day_bucket(get_ist_now())
            min_samples = int(cfg.get("min_samples_per_combo", 15))
            strategy_order = (
                leaderboard.get_strategy_order_for(regime_for_leaderboard, time_bucket_for_leaderboard, min_samples=min_samples)
                or get_adaptive_strategy_order(trade_history)
            )
            symbol_cfg = dict(cfg)
            symbol_cfg["_client"] = client
            symbol_cfg["_symbol"] = symbol
            symbol_cfg["_instrument_key"] = inst["instrument_key"]
            symbol_cfg["_htf_candles"] = candles_15m if candles_15m else None
            symbol_cfg["_htf_1h"] = candles_1h        # H5: 1H candles
            symbol_cfg["_htf_daily"] = candles_daily  # H5: Daily candles
            symbol_cfg["_trade_history"] = trade_history
            symbol_cfg["_institutional_score"] = inst_score
            signal = select_best_strategy(
                candles_5m, candles_15m if candles_15m else None,
                strategy_order=strategy_order,
                config=symbol_cfg,
            )

            if not signal:
                _matrix_set(symbol, "no setup", "no_signal", candles_5m)
                continue

            jsonl_logger.log_decision(
                "pick", symbol,
                leaderboard.explain_pick(regime_for_leaderboard, time_bucket_for_leaderboard, signal.get("strategy", ""), min_samples=min_samples),
                {"regime": regime_for_leaderboard, "time_bucket": time_bucket_for_leaderboard, "strategy": signal.get("strategy")},
            )
            
            # Embed institutional score into signal for downstream quality evaluation
            if inst_score > 0:
                signal["confidence_score"] = signal.get("confidence_score", 0) + inst_score
                signal["institutional_details"] = inst_details
                log_scan(symbol, f"Institutional Engine: +{inst_score} pts ({', '.join(inst_details)})", "info")

            signals_found += 1

            # ── Layers 2-6 evaluated together via quality gate ──────────
            eval_cfg = dict(cfg)
            if vix_active:
                eval_cfg["min_confluence_score"] = int(cfg.get("min_confluence_score", 4)) + 1

            approved, reason, quality_details = evaluate_signal(
                signal, candles_5m, candles_15m, nifty_trend, trade_history, eval_cfg
            )
            if not approved:
                log_scan(symbol, f"Filtered: {reason}", "info")
                _matrix_set(symbol, f"filtered: {reason}", "filtered", candles_5m, strategy=signal.get("strategy"))
                signals_filtered += 1
                continue

            # M4: Slippage Guard — verify signal is still fresh before entry
            # If price has moved > 0.3% from signal entry since signal was generated, skip (stale signal)
            if not signal.get("is_shadow_trade", False):
                try:
                    fresh_quote = await loop.run_in_executor(
                        None, functools.partial(client.get_market_quote, inst["instrument_key"])
                    )
                    if fresh_quote:
                        live_ltp = fresh_quote.get("ltp", signal["entry_price"])
                        signal_price = signal["entry_price"]
                        price_drift_pct = abs(live_ltp - signal_price) / signal_price if signal_price > 0 else 0
                        if price_drift_pct > 0.003:  # 0.3% drift threshold
                            log_scan(symbol, f"M4 Slippage Guard: Price drifted {price_drift_pct:.2%} from signal (₹{signal_price} → ₹{live_ltp}). Stale signal skipped.", "warning")
                            _matrix_set(symbol, f"stale signal: {price_drift_pct:.2%} drift", "filtered", candles_5m, strategy=signal.get("strategy"))
                            signals_filtered += 1
                            continue
                        # Liquidity/spread gate (order book): skip wide-spread / illiquid names
                        # where the bid-ask alone would eat any intraday edge. Fail-open if the
                        # feed omits depth (mock broker / API blip). Spread-only here (size-
                        # independent); order-size-vs-depth is enforced downstream once sized.
                        if client.config.get("enable_liquidity_gate", True):
                            _liq_ok, _liq_why = microstructure.liquidity_ok(
                                fresh_quote.get("depth"),
                                max_spread_bps=float(client.config.get("max_spread_bps", 50)),
                                min_depth_ratio=float(client.config.get("min_depth_ratio", 0.5)))
                            if not _liq_ok:
                                log_scan(symbol, f"Liquidity gate: {_liq_why} — skipped.", "warning")
                                _matrix_set(symbol, f"illiquid: {_liq_why}", "filtered", candles_5m, strategy=signal.get("strategy"))
                                signals_filtered += 1
                                continue
                except Exception:
                    pass  # Non-critical: proceed without slippage check if quote fetch fails

            # Scale targets if VIX is active
            if vix_active:
                signal = dict(signal)
                entry_p = signal["entry_price"]
                orig_t1 = signal["target_1"]
                orig_t2 = signal.get("target_2", orig_t1)
                
                signal["target_1"] = round(entry_p + (orig_t1 - entry_p) * 0.8, 2)
                signal["target_2"] = round(entry_p + (orig_t2 - entry_p) * 0.8, 2)
                log_scan(symbol, f"VIX elevated ({vix_val:.2f}): Tightened targets T1 ({orig_t1} -> {signal['target_1']}) and T2 ({orig_t2} -> {signal['target_2']})", "warning")

            # Attach quality metadata to signal for trade record
            signal["confluence_score"] = quality_details.get("confluence_score", 0)
            log_scan(symbol, reason, "info")

            if signal.get("is_shadow_trade", False):
                # Simulated shadow trade: log and track but bypass broker order execution
                _matrix_set(symbol, f"SHADOW — {signal.get('strategy', '?')}", "skipped", candles_5m, strategy=signal.get("strategy"))
                await execute_entry(symbol, inst["instrument_key"], signal, candles_5m, paper_trading=True, is_shadow=True)
            else:
                _matrix_set(symbol, f"ENTERED — {signal.get('strategy', '?')}", "entered", candles_5m, strategy=signal.get("strategy"))
                await execute_entry(symbol, inst["instrument_key"], signal, candles_5m, paper_trading)


        except Exception as e:
            log_scan(symbol, f"Scan error: {e}", "danger")
            _matrix_set(symbol, f"error: {e}", "error")

    _set_context(gate="open", nifty_trend=nifty_trend, halted=False,
                 checked=scanned, signals=signals_found, filtered=signals_filtered)

    # ── Heartbeat: always log scan summary so user knows the bot is alive ──
    scanner_state["last_scan"] = get_ist_now().strftime("%H:%M:%S")
    scanner_state["last_scan_epoch"] = time.monotonic()
    scanner_state["last_scan_checked"] = scanned
    scanner_state["last_scan_summary"] = (
        f"{scanned} checked, {signals_found} signals, {signals_filtered} filtered"
    )
    log_scan(
        "SYSTEM",
        f"Scan done — {scanned} checked | {signals_found} raw signals | "
        f"{signals_filtered} filtered | {len(active_positions)}/{max_positions} open",
        "info",
    )

    # Broadcast scanner updates
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(manager.broadcast({
                "type": "scanner",
                "scanner": {"context": scan_context, "matrix": list(scan_matrix.values())}
            }))
            loop.create_task(manager.broadcast({
                "type": "checking_progress",
                "symbol": "",
                "name": "",
                "status": "done",
                "time": get_ist_now().strftime("%H:%M:%S")
            }))
    except Exception:
        pass


_GATE_NEWS_CACHE = {}  # instrument_key -> (fetched_ts, [news]); short-TTL cache for the LLM entry gate


def _gate_news_cached(client, instrument_key, ttl=300):
    """Recent news for the entry gate, cached per instrument for `ttl` seconds so rapid re-scans
    of the same candidate don't re-hit the news API. Never raises — returns [] on any problem."""
    import time as _t
    try:
        hit = _GATE_NEWS_CACHE.get(instrument_key)
        if hit and (_t.time() - hit[0]) < ttl:
            return hit[1]
        news = client.get_news(instrument_key, page_size=5)
        _GATE_NEWS_CACHE[instrument_key] = (_t.time(), news)
        return news
    except Exception:
        return []


async def execute_entry(symbol, instrument_key, signal, candles, paper_trading, is_shadow=False):
    global active_positions, shadow_positions
    entry_price = signal["entry_price"]
    stop_loss = signal["stop_loss"]
    target_1 = signal["target_1"]
    target_2 = signal.get("target_2", signal["target_1"])
    strat_name = signal["strategy"]
    action = "BUY" if "Buy" in strat_name else "SELL"

    cfg = client.config
    fno_mode = bool(cfg.get("enable_fno", False))
    fno_type = cfg.get("fno_type", "FUT").upper()
    order_key = None        # None → equity order on the symbol itself
    lot_size = 1
    contract_label = ""

    if fno_mode:
        if fno_type == "OPT":
            option_type = "CE" if action == "BUY" else "PE"
            opt = client.get_option_for(symbol, option_type, entry_price)
            if not opt:
                log_scan(symbol, f"F&O Options mode: no ATM {option_type} contract found — trade skipped.", "warning")
                return
            order_key = opt["instrument_key"]
            lot_size = int(opt.get("lot_size") or 1)
            contract_label = opt.get("trading_symbol", "OPT")

            try:
                opt_quote = client.get_market_quote(order_key)
                if not opt_quote:
                    log_scan(symbol, f"F&O Options mode: failed to fetch quote for {contract_label} — trade skipped.", "warning")
                    return
                opt_ltp = opt_quote["ltp"]
            except Exception as quote_err:
                log_scan(symbol, f"F&O Options mode: error fetching quote for {contract_label}: {quote_err} — trade skipped.", "warning")
                return

            delta = float(cfg.get("option_delta", 0.50))
            if option_type == "CE":
                opt_sl = opt_ltp - delta * (entry_price - stop_loss)
                opt_t1 = opt_ltp + delta * (target_1 - entry_price)
                opt_t2 = opt_ltp + delta * (target_2 - entry_price)
            else:
                opt_sl = opt_ltp - delta * (stop_loss - entry_price)
                opt_t1 = opt_ltp + delta * (entry_price - target_1)
                opt_t2 = opt_ltp + delta * (entry_price - target_2)

            opt_sl = max(0.05, round(opt_sl, 2))
            opt_t1 = max(0.05, round(opt_t1, 2))
            opt_t2 = max(0.05, round(opt_t2, 2))

            entry_price = opt_ltp
            stop_loss = opt_sl
            target_1 = opt_t1
            target_2 = opt_t2
            action = "BUY"
        else:
            fut = client.get_future_for(symbol)
            if not fut:
                log_scan(symbol, "F&O mode: no futures contract for this stock — trade skipped.", "warning")
                return
            order_key = fut["instrument_key"]
            lot_size = int(fut.get("lot_size") or 1)
            contract_label = fut.get("trading_symbol", "FUT")

        # Lot-based sizing against the dedicated F&O risk budget
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit < 0.01:
            risk_per_unit = 0.01
        risk_per_lot = risk_per_unit * lot_size
        fno_budget = float(cfg.get("fno_max_risk_per_trade", 2000.0))
        max_lots = int(cfg.get("fno_max_lots", 1))
        lots = min(int(fno_budget // risk_per_lot), max_lots)
        if lots < 1:
            log_scan(
                symbol,
                f"F&O: 1 lot of {contract_label} risks ₹{risk_per_lot:.0f} > budget ₹{fno_budget:.0f} — trade skipped.",
                "warning",
            )
            return
        qty = lots * lot_size
    # Fetch account funds dynamically to check margin and calculate risk gates
    avail_margin = None
    margin = 100000.0
    try:
        funds_res = client.get_funds_and_margin()
        if funds_res and funds_res.get("status") == "success":
            eq_data = funds_res.get("data", {}).get("equity", {})
            avail_margin = float(eq_data.get("available_margin") or 0.0)
            used_margin = float(eq_data.get("used_margin") or 0.0)
            margin = avail_margin + used_margin
    except Exception as ex:
        print(f"[execute_entry] Error fetching funds and margin: {ex}")

    # Calculate 1% account risk dynamically if enabled
    base_risk = float(cfg.get("max_risk_per_trade", 500.0))
    # H2: default to False to match config.json — a missing key must NOT silently switch
    # sizing from the fixed ₹ risk budget to 1% of equity (a much larger position).
    if cfg.get("enable_one_percent_risk", False) and margin > 0:
        base_risk = round(0.01 * margin, 2)

    # Sizing is now: fixed ₹ risk budget (or 1% of equity) → Kelly/max-capacity → RiskManager's
    # hard ceiling. Two multipliers used to sit here and both are gone:
    #   - RL multiplier: the reward is size-invariant, so it could never learn sizing.
    #   - AI Research Lab capital allocations: those percentages were derived from metrics the
    #     lab generated with random.uniform(), i.e. a random number with a path to real position
    #     size. It measured 1.00x in practice, but "harmless today" is not a risk control.

    is_options_fno = (fno_mode and fno_type == "OPT")
    if fno_mode and not is_options_fno:
        # F&O Futures sizing is lot-based by default
        if cfg.get("enable_max_capacity", False) and avail_margin is not None:
            qty = _calc_quantity(entry_price, stop_loss, cfg, available_margin=avail_margin, is_fno=True, lot_size=lot_size)
        else:
            pass # use the lots * lot_size calculated above
    elif cfg.get("enable_max_capacity", False) and avail_margin is not None:
        qty = _calc_quantity(
            entry_price, stop_loss, cfg,
            available_margin=avail_margin,
            is_fno=fno_mode,
            is_options=is_options_fno,
            lot_size=lot_size
        )
    elif cfg.get("enable_kelly_sizing", True):
        kelly_risk = calculate_kelly_risk(trade_history, base_risk, strategy_name=strat_name)
        qty = _calc_quantity(entry_price, stop_loss, cfg, override_risk=kelly_risk)
    else:
        qty = _calc_quantity(entry_price, stop_loss, cfg, override_risk=base_risk)

    action = "BUY" if (fno_mode and fno_type == "OPT") else ("BUY" if "Buy" in strat_name else "SELL")
    atr_val = signal.get("atr", abs(entry_price - stop_loss))
    context = _build_market_context(candles)
    # Inject volume ratio if present in the signal context
    if "market_context" in signal:
        context["volume_ratio"] = signal["market_context"].get("volume_ratio", 1.0)
        context["atr_pct"] = signal["market_context"].get("atr_pct", 0.008)
        context["vwap_aligned"] = signal["market_context"].get("vwap_aligned", True)
        context["htf_aligned"] = signal["market_context"].get("htf_aligned", True)

    label_type = "SHADOW" if is_shadow else "LIVE"
    log_scan(
        symbol,
        f"[{strat_name}] {label_type} Signal fired | {'F&O ' + contract_label if fno_mode else 'EQ'} | Entry ₹{entry_price} | SL ₹{stop_loss} | T1 ₹{target_1} | Qty {qty} | Regime: {signal.get('regime', '?')}",
        "success",
    )

    if is_shadow:
        # Shadow simulation: bypass broker order placement
        shadow_positions[symbol] = {
            "symbol": symbol,
            "instrument_key": order_key if fno_mode else instrument_key,
            "is_fno": fno_mode,
            "lot_size": lot_size,
            "contract": contract_label,
            "strategy": strat_name,
            "direction": "LONG" if action == "BUY" else "SHORT",
            "quantity": qty,
            "entry_price": entry_price,
            "entry_time": get_ist_now().isoformat(),
            "stop_loss": stop_loss,
            "target": target_1,
            "target_2": target_2,
            "t1_hit": False,
            "order_id": f"MOCK-SHADOW-{int(datetime.now().timestamp() * 1000)}",
            "current_price": entry_price,
            "pnl": 0.0,
            "atr_at_entry": atr_val,
            "trailing_high": entry_price if action == "BUY" else None,
            "trailing_low": entry_price if action == "SELL" else None,
            "market_context": context,
            "regime": signal.get("regime", "unknown"),
            "htf_trend": signal.get("htf_trend", "neutral"),
            "mae": 0.0,
            "mfe": 0.0,
            "confluence_score": signal.get("confluence_score", 0),
            "trigger_level_source": signal.get("trigger_level_source"),
            "trigger_level_price": signal.get("trigger_level_price"),
            "trigger_level_score": signal.get("trigger_level_score"),
            "candlestick_patterns": signal.get("candlestick_patterns", []),
            "is_shadow": True
        }
        log_scan(symbol, f"Entered Shadow position {action} {qty} @ ₹{entry_price:.2f}", "success")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({
                "type": "trade_event",
                "event": "entry",
                "symbol": symbol,
                "direction": "LONG" if action == "BUY" else "SHORT",
                "quantity": qty,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "target": target_1,
                "strategy": strat_name,
                "is_shadow": True
            }))
        except Exception:
            pass
        return

    # ── Fresh quote on the ACTUAL traded instrument (option/future when F&O, else the
    # equity) — feeds the size-vs-depth, circuit and volume gates below with the book that
    # the order will really hit, not the underlying's. Best-effort; all gates fail-open. ──
    actual_key = order_key if (fno_mode and order_key) else instrument_key
    entry_volume = None
    entry_book = None
    entry_fresh = None
    try:
        entry_fresh = client.get_market_quote(actual_key)
        if entry_fresh:
            entry_volume = entry_fresh.get("volume")
            entry_book = entry_fresh.get("depth")
    except Exception as _q_err:
        print(f"[execute_entry] fresh quote fetch failed for {actual_key}: {_q_err}")

    # Circuit-limit proximity guard (fix #4): skip entries pinned near the daily band, where
    # fills are unreliable and you can get stuck unable to exit. Fail-open if limits absent.
    if entry_fresh and cfg.get("enable_circuit_guard", True):
        # Use the fresh LTP — the actual price we'll transact at, and consistent with the
        # circuit limits from the same quote (fall back to the signal price if LTP absent).
        _price_for_circuit = entry_fresh.get("ltp") or entry_price
        _cok, _cwhy = safety_guards.circuit_proximity_ok(
            _price_for_circuit,
            upper=entry_fresh.get("upper_circuit"),
            lower=entry_fresh.get("lower_circuit"),
            buffer_pct=float(cfg.get("circuit_buffer_pct", 0.02)))
        if not _cok:
            log_scan(symbol, f"Circuit guard: {_cwhy} — entry skipped.", "warning")
            jsonl_logger.log_decision("skip", symbol, f"circuit: {_cwhy}", {"strategy": strat_name})
            return

    # Cost-adjusted R:R gate (fix #2): reject when the nearest-target reward:risk collapses
    # below min_net_rr once round-trip slippage + statutory charges are subtracted. Equity
    # only — the charges model is NSE intraday equity; F&O has its own cost structure.
    if not fno_mode and cfg.get("enable_cost_adjusted_rr", True):
        _charges = {
            "brokerage_per_order": float(cfg.get("brokerage_per_order", 20.0)),
            "stt_pct": float(cfg.get("stt_pct", 0.00025)),
            "exchange_txn_pct": float(cfg.get("exchange_txn_pct", 0.0000297)),
            "gst_pct": float(cfg.get("gst_pct", 0.18)),
            "sebi_per_crore": float(cfg.get("sebi_per_crore", 10.0)),
            "stamp_pct": float(cfg.get("stamp_pct", 0.00003)),
        }
        _nrr = execution_costs.net_risk_reward(
            entry_price, stop_loss, target_1, qty,
            spread_bps=float(cfg.get("spread_bps", 3.0)),
            slippage_bps=float(cfg.get("slippage_bps", 2.0)),
            charges=_charges)
        _min_nrr = float(cfg.get("min_net_rr", 1.0))
        if _nrr < _min_nrr:
            log_scan(symbol, f"Cost-adjusted R:R {_nrr:.2f} < {_min_nrr:.2f} (net of costs) — entry skipped.", "warning")
            jsonl_logger.log_decision("skip", symbol, f"net_rr {_nrr:.2f} < {_min_nrr:.2f}", {"strategy": strat_name})
            return

    # ── Mandatory RiskManager gate (Section 0: "no exceptions anywhere in the code") ──
    # Re-validated here (not just upstream in scan_for_entries) so this is a true single
    # choke point every real order passes through, regardless of caller (scan loop, manual
    # trade, future callers). Never loosens qty below what upstream sizing (Kelly/max-capacity/
    # F&O lots, above) already computed — only ever caps it further or rejects outright.
    margin_for_risk, weekly_pnl_for_risk = get_capital_and_weekly_pnl()
    risk_decision = risk_manager.size_and_check(
        symbol=symbol,
        entry_price=entry_price,
        stop_loss=stop_loss,
        capital=margin_for_risk,
        total_pnl_today=get_total_daily_pnl(),
        weekly_pnl=weekly_pnl_for_risk,
        open_positions=active_positions,
        trade_history=trade_history,
        now=get_ist_now(),
        paper_trading=paper_trading,
        proposed_qty=qty,
        volume=entry_volume,   # fix #5: real volume now reaches check_liquidity
        book=entry_book,       # fix #1/#3: enforce sized order against the real book
        skip_size_cap=fno_mode or cfg.get("enable_max_capacity", False),  # F&O or Max Capacity sizes directly
    )
    if not risk_decision.allowed:
        log_scan(symbol, f"RiskManager blocked entry: {risk_decision.reason}", "warning")
        jsonl_logger.log_decision("skip", symbol, risk_decision.reason, {"strategy": strat_name})
        return
    qty = risk_decision.qty
    jsonl_logger.log_decision("trade", symbol, "RiskManager approved", {"strategy": strat_name, "quantity": qty})

    # ── LLM entry-confirmation gate (Section 5C) — optional, OFF by default. ──────────────
    # A forward-looking AI check layered on top of the deterministic gates above. Runs only for
    # real (non-shadow) entries and only when enable_llm_entry_gate is set. Fail-closed: if the
    # LLM can't confirm, the entry is skipped (set llm_entry_gate_fail_open to invert). Adds
    # ~seconds of latency, so it sits after every cheap gate has already passed.
    if cfg.get("enable_llm_entry_gate", False) and not is_shadow:
        try:
            import llm_engine
            _gate_ctx = {
                "symbol": symbol,
                "strategy": strat_name,
                "direction": "LONG" if action == "BUY" else "SHORT",
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "target_1": target_1,
                "target_2": target_2,
                "regime": signal.get("regime", "unknown"),
                "htf_trend": signal.get("htf_trend", "neutral"),
                "confidence_score": signal.get("confidence_score"),
                "institutional_details": signal.get("institutional_details"),
                "atr": atr_val,
                "news": (_gate_news_cached(client, instrument_key)
                         if cfg.get("llm_entry_gate_use_news", True) else None),
            }
            _verdict = llm_engine.confirm_entry(_gate_ctx, cfg)
            _min_conf = int(cfg.get("llm_entry_gate_min_confidence", 60))
            if (not _verdict["proceed"]) or _verdict["confidence"] < _min_conf:
                log_scan(symbol, f"LLM gate SKIP [{_verdict['source']}] conf={_verdict['confidence']}: {_verdict['reason']}", "warning")
                jsonl_logger.log_decision("skip", symbol, f"llm_gate: {_verdict['reason']}", {"strategy": strat_name})
                return
            log_scan(symbol, f"LLM gate PASS [{_verdict['source']}] conf={_verdict['confidence']}: {_verdict['reason']}", "success")
        except Exception as _gate_err:
            if not bool(cfg.get("llm_entry_gate_fail_open", False)):
                log_scan(symbol, f"LLM gate error — skipping entry (fail-closed): {_gate_err}", "danger")
                jsonl_logger.log_decision("skip", symbol, f"llm_gate_error: {_gate_err}", {"strategy": strat_name})
                return
            log_scan(symbol, f"LLM gate error — proceeding (fail-open): {_gate_err}", "warning")

    try:
        # Base limit price and slippage calculation on futures contract LTP if trading F&O,
        # since futures trade at a premium/discount basis to the underlying spot.
        base_entry_price = entry_price
        if fno_mode and order_key:
            try:
                quote = client.get_market_quote(order_key)
                if quote and "ltp" in quote:
                    base_entry_price = quote["ltp"]
            except Exception as e:
                print(f"[F&O Mode] Error fetching futures quote for limit price: {e}")

        raw_limit = (base_entry_price + 0.1 * atr_val) if action == "BUY" else (base_entry_price - 0.1 * atr_val)
        limit_price = round_to_tick(raw_limit)
        order = await order_queue.submit(
            client.place_order, symbol, action, qty, "LIMIT", limit_price, tag="autobot", instrument_key=order_key
        )
        fill_price = order["price"]

        # Anomaly Check: Entry Slippage (relative to the baseline instrument price we placed the order on)
        slippage = abs(fill_price - base_entry_price)
        if slippage > 1.5 * atr_val and atr_val > 0:
            log_scan(symbol, f"Excessive entry slippage (₹{slippage:.2f} > 1.5x ATR ₹{1.5*atr_val:.2f}). Force exit.", "danger")
            # Immediately close out the position
            pos_temp = {
                "symbol": symbol,
                "instrument_key": order_key if fno_mode else instrument_key,
                "is_fno": fno_mode,
                "lot_size": lot_size,
                "contract": contract_label,
                "strategy": strat_name,
                "direction": "LONG" if action == "BUY" else "SHORT",
                "quantity": qty,
                "entry_price": fill_price,
                "entry_time": get_ist_now().isoformat(),
                "stop_loss": stop_loss,
                "target": target_1,
                "target_2": target_2,
                "order_id": order["order_id"],
                "current_price": fill_price,
                "pnl": 0.0,
                "atr_at_entry": atr_val,
                "market_context": context,
                "regime": signal.get("regime", "unknown"),
                "htf_trend": signal.get("htf_trend", "neutral"),
                "trigger_level_source": signal.get("trigger_level_source"),
                "trigger_level_price": signal.get("trigger_level_price"),
                "trigger_level_score": signal.get("trigger_level_score"),
                "candlestick_patterns": signal.get("candlestick_patterns", [])
            }
            await execute_exit(symbol, pos_temp, fill_price, "SLIPPAGE ANOMALY EXIT", paper_trading,
                               pos_already_removed=True)
            _exiting_symbols.discard(symbol)   # entry aborted before the position was tracked
            return

        # Futures trade at a basis premium/discount to the equity price the
        # signal was computed on — shift SL/targets by the observed offset so
        # risk distances stay what the strategy intended.
        if fno_mode and fill_price:
            offset = round(fill_price - entry_price, 2)
            stop_loss = round(stop_loss + offset, 2)
            target_1 = round(target_1 + offset, 2)
            target_2 = round(target_2 + offset, 2)

        active_positions[symbol] = {
            "symbol": symbol,
            "instrument_key": order_key if fno_mode else instrument_key,
            "is_fno": fno_mode,
            "lot_size": lot_size,
            "contract": contract_label,
            "strategy": strat_name,
            "direction": "LONG" if action == "BUY" else "SHORT",
            "quantity": qty,
            "entry_price": fill_price,
            "entry_time": get_ist_now().isoformat(),
            "stop_loss": stop_loss,
            "target": target_1,
            "target_2": target_2,
            "t1_hit": False,
            "order_id": order["order_id"],
            "current_price": fill_price,
            "pnl": 0.0,
            "atr_at_entry": atr_val,
            "trailing_high": fill_price if action == "BUY" else None,
            "trailing_low": fill_price if action == "SELL" else None,
            "market_context": context,
            "regime": signal.get("regime", "unknown"),
            "htf_trend": signal.get("htf_trend", "neutral"),
            "mae": 0.0,
            "mfe": 0.0,
            "confluence_score": signal.get("confluence_score", 0),
            "trigger_level_source": signal.get("trigger_level_source"),
            "trigger_level_price": signal.get("trigger_level_price"),
            "trigger_level_score": signal.get("trigger_level_score"),
            "candlestick_patterns": signal.get("candlestick_patterns", [])
        }

        # Place broker-side stop loss order (real or mock)
        sl_order_id = None
        try:
            exit_action = "SELL" if action == "BUY" else "BUY"
            if exit_action == "SELL":
                sl_limit_price = round_to_tick(stop_loss - max(0.05, stop_loss * 0.002))
            else:
                sl_limit_price = round_to_tick(stop_loss + max(0.05, stop_loss * 0.002))
            
            stop_loss = round_to_tick(stop_loss)
            
            log_scan(symbol, f"Placing SL order: Trigger ₹{stop_loss} | Limit ₹{sl_limit_price}", "info")
            sl_order = await order_queue.submit(
                client.place_order, symbol, exit_action, qty, "SL", price=sl_limit_price, trigger_price=stop_loss, tag="autobot_sl", instrument_key=order_key
            )
            sl_order_id = sl_order["order_id"]
            log_scan(symbol, f"SL order placed successfully. Order ID: {sl_order_id}", "success")
        except Exception as sl_err:
            log_scan(symbol, f"SL order placement FAILED: {sl_err}. Bot will exit the entry position for safety.", "danger")
            pos_temp = active_positions.pop(symbol, None)
            if pos_temp:
                await execute_exit(symbol, pos_temp, fill_price, "ENTRY SL FAILED - SAFETY EXIT", paper_trading,
                                   pos_already_removed=True)
                _exiting_symbols.discard(symbol)   # position already popped; clear the exit claim
            return

        active_positions[symbol]["sl_order_id"] = sl_order_id
        save_state()
        log_scan(symbol, f"Entered {action} {qty} @ ₹{fill_price:.2f}", "success")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({
                "type": "trade_event",
                "event": "entry",
                "symbol": symbol,
                "direction": "LONG" if action == "BUY" else "SHORT",
                "quantity": qty,
                "entry_price": fill_price,
                "stop_loss": stop_loss,
                "target": target_1,
                "strategy": strat_name,
                "is_shadow": False
            }))
        except Exception:
            pass
    except Exception as e:
        log_scan(symbol, f"Entry order failed: {e}", "danger")



# ── Broker-position reconciliation (live mode only) ─────────────────────────────────────
# active_positions is the bot's own book; the real account can diverge the moment the
# operator closes a trade from the Upstox app/web on another device. Anything the broker no
# longer holds must be recorded as CLOSED EXTERNALLY — with its leftover SL order cancelled
# and WITHOUT placing any new order (a "closing" order on a flat book OPENS a reverse
# position). None from get_positions() means "state unknown": do nothing.

_BROKER_RECONCILE_INTERVAL_S = 20
_last_broker_reconcile = 0.0


def _net_positions_by_key(rows):
    """Broker position rows → {instrument_key: net signed quantity}."""
    net = {}
    for row in rows or []:
        key = row.get("instrument_token") or row.get("instrument_key")
        if key:
            net[key] = net.get(key, 0) + int(row.get("quantity") or 0)
    return net


def _position_still_held(pos, net_by_key):
    """True if the broker's net quantity still covers this bot position."""
    held = net_by_key.get(pos.get("instrument_key"), 0)
    needed = pos["quantity"] if pos["direction"] == "LONG" else -pos["quantity"]
    return held >= needed if needed > 0 else held <= needed


def _position_age_seconds(pos, now):
    """Seconds since this position was opened, per its entry_time. A missing/unparseable
    entry_time returns inf (treated as old) so it never blocks a genuine external-close
    reconcile."""
    et = pos.get("entry_time")
    if not et:
        return float("inf")
    try:
        return (now - datetime.fromisoformat(et)).total_seconds()
    except Exception:
        return float("inf")


async def reconcile_broker_positions(paper_trading):
    """Syncs the bot's book against the broker's real positions. Returns the list of symbols
    reconciled away as externally closed. Never raises; throttled to one API call per
    _BROKER_RECONCILE_INTERVAL_S."""
    global _last_broker_reconcile
    if paper_trading or not active_positions:
        return []
    now_mono = time.monotonic()
    if now_mono - _last_broker_reconcile < _BROKER_RECONCILE_INTERVAL_S:
        return []
    _last_broker_reconcile = now_mono

    loop = asyncio.get_running_loop()
    try:
        broker_rows = await loop.run_in_executor(None, client.get_positions)
    except Exception as e:
        print(f"[Reconcile] Error fetching broker positions: {e}")
        return []
    if broker_rows is None:
        return []  # unknown broker state — never treat as flat

    net_by_key = _net_positions_by_key(broker_rows)
    settle_s = float(client.config.get("broker_reconcile_settle_seconds", 15.0))
    now_ist = get_ist_now()
    removed = []
    for symbol, pos in list(active_positions.items()):
        if _position_still_held(pos, net_by_key):
            continue
        # Settling grace: a just-filled order can take a few seconds to appear in the broker's
        # positions feed. Treating that lag as an external close orphaned the live position and
        # cancelled its stop-loss (the ITDC incident, 2026-07-16) — a naked, unmanaged trade.
        # Give a fresh fill time to surface before concluding it was closed elsewhere.
        if _position_age_seconds(pos, now_ist) < settle_s:
            log_scan(symbol, f"Broker feed shows flat but this {pos['direction']} {pos['quantity']} "
                             f"fill is <{settle_s:.0f}s old — waiting for the positions feed to "
                             f"settle before reconciling.", "info")
            continue
        held = net_by_key.get(pos.get("instrument_key"), 0)
        log_scan(symbol, f"Broker holds {held} but bot book expects {pos['direction']} "
                         f"{pos['quantity']} — closed/changed outside the bot (other device?). "
                         f"Recording as CLOSED EXTERNALLY; no order will be placed.", "danger")
        # The bot's SL order survives an external square-off and would open a reverse
        # position if it later triggers on a flat book — cancel it first.
        sl_order_id = pos.pop("sl_order_id", None)
        if sl_order_id:
            try:
                await order_queue.submit(client.cancel_order, sl_order_id)
                log_scan(symbol, f"Leftover SL order {sl_order_id} cancelled after external close.", "warning")
            except Exception as cancel_err:
                log_scan(symbol, f"Could NOT cancel leftover SL order {sl_order_id}: {cancel_err} — "
                                 f"CHECK THE UPSTOX APP: while it stays pending it can open a "
                                 f"reverse position.", "danger")
        exit_price = pos.get("current_price", pos.get("entry_price"))
        # is_broker_hit=True records the trade at the given price WITHOUT placing an order.
        if await execute_exit(symbol, pos, exit_price, "CLOSED EXTERNALLY (BROKER RECONCILE)",
                              paper_trading, is_broker_hit=True):
            _remove_position(symbol)
            removed.append(symbol)
    if removed:
        save_state()
    return removed


async def manage_existing_positions(paper_trading, trailing_enabled, trailing_mult, quotes=None):
    global active_positions, daily_pnl, trade_history
    if not active_positions:
        return
    # Live-mode safety: sync the bot's book with the broker BEFORE acting on any position, so
    # a trade the operator closed from another device is never "managed" (= reverse-ordered).
    try:
        await reconcile_broker_positions(paper_trading)
    except Exception as reconcile_err:
        print(f"[Reconcile] Unexpected error: {reconcile_err}")
    if not active_positions:
        return
    to_remove = []
    cfg = client.config
    loop = asyncio.get_running_loop()
    state_changed = False

    if quotes is None:
        # Fetch quotes in a single batch request
        instrument_keys = [pos["instrument_key"] for pos in active_positions.values()]
        try:
            quotes = await loop.run_in_executor(
                None, functools.partial(client.get_market_quotes, instrument_keys)
            )
        except Exception as e:
            print(f"Error fetching batch quotes in position manager: {e}")
            return

    for symbol, pos in list(active_positions.items()):
        try:
            quote = quotes.get(pos["instrument_key"])
            if not quote:
                # H1: the batch feed dropped this symbol. Don't silently skip — a missed
                # quote means the stop-loss is not evaluated this cycle. Try a direct
                # single-quote fallback so the stop can still fire; escalate an alert if
                # the data feed is sustained-down for this position.
                try:
                    quote = await loop.run_in_executor(
                        None, functools.partial(client.get_market_quote, pos["instrument_key"])
                    )
                except Exception:
                    quote = None
                miss = pos.get("quote_miss_count", 0) + 1
                pos["quote_miss_count"] = miss
                if not quote:
                    if miss == 1 or miss % 10 == 0:
                        log_scan(symbol, f"No market quote for {miss} cycle(s) — stop-loss not evaluated. Check data feed.", "danger")
                    continue
            pos["quote_miss_count"] = 0
            ltp = quote["ltp"]
            # Bad-quote guard (Tier-1): ignore a provably-broken tick and evaluate this cycle
            # against the last good price. A real stop still fires — it's assessed on the last
            # good price, not suppressed. Only clearly-broken ticks (<=0 / absurd single-step
            # jump) are rejected; normal volatility passes through. Staleness is NOT re-checked
            # here: the quote in hand is always fresh (live REST, or a cache entry age-bounded
            # to a few seconds), and a genuinely absent/frozen feed is handled above by the
            # missing-quote path. (Checking staleness on our own processing cadence used to
            # freeze current_price permanently after any fetch gap — 2026-07-13 bug.)
            if client.config.get("enable_safety_guards", True):
                ltp, _ok, _why = safety_guards.evaluate_live_tick(
                    ltp, pos.get("current_price"),
                    jump_reject_pct=float(client.config.get("quote_jump_reject_pct", 20)))
                if _ok:
                    pos["_quote_warned"] = False
                elif not pos.get("_quote_warned"):
                    log_scan(symbol, f"Bad tick rejected ({_why}) — evaluating on last price ₹{pos.get('current_price')}", "warning")
                    pos["_quote_warned"] = True
            pos["current_price"] = ltp

            # Check broker-side Stop Loss status
            sl_order_id = pos.get("sl_order_id")
            if sl_order_id:
                try:
                    sl_status = await loop.run_in_executor(
                        None, client.get_order_status, sl_order_id
                    )
                    sl_status_lower = sl_status.lower() if sl_status else ""
                    if sl_status_lower == "filled":
                        log_scan(symbol, f"Broker-side SL order {sl_order_id} FILLED on exchange.", "warning")
                        await execute_exit(symbol, pos, pos["stop_loss"], "STOP LOSS (BROKER HIT)", paper_trading, is_broker_hit=True)
                        to_remove.append(symbol)
                        continue
                    elif sl_status_lower in ("cancelled", "rejected", "cancelled_after_market"):
                        log_scan(symbol, f"Broker-side SL order {sl_order_id} was {sl_status.upper()}. Exiting position for safety.", "danger")
                        await execute_exit(symbol, pos, ltp, f"SL ORDER {sl_status.upper()} - SAFETY EXIT", paper_trading)
                        to_remove.append(symbol)
                        continue
                except Exception as status_err:
                    print(f"[SL Check] Error polling SL order status: {status_err}")

            if pos["direction"] == "LONG":
                pos["pnl"] = (ltp - pos["entry_price"]) * pos["quantity"]
            else:
                pos["pnl"] = (pos["entry_price"] - ltp) * pos["quantity"]

            # Track peak favorable/adverse excursion for post-session analysis
            pos["mfe"] = max(pos.get("mfe", 0.0), pos["pnl"])
            pos["mae"] = min(pos.get("mae", 0.0), pos["pnl"])

            # Regime-Adaptive Target Expansion: Expand Target 2 by 1.5x in strong trend regimes
            if not pos.get("target_expanded_by_regime", False):
                regime = pos.get("regime", "unknown")
                if (pos["direction"] == "LONG" and regime in ("Strong Uptrend", "Uptrend")) or \
                   (pos["direction"] == "SHORT" and regime in ("Strong Downtrend", "Downtrend")):
                    ep = pos["entry_price"]
                    orig_t2 = pos.get("target_2", pos["target"])
                    dist = abs(orig_t2 - ep)
                    if pos["direction"] == "LONG":
                        pos["target_2"] = round(ep + (dist * 1.5), 2)
                    else:
                        pos["target_2"] = round(ep - (dist * 1.5), 2)
                    pos["target_expanded_by_regime"] = True
                    log_scan(symbol, f"Strong trend detected ({regime}). Dynamic Target 2 extended from ₹{orig_t2} to ₹{pos['target_2']}", "success")
                    state_changed = True

            # Trailing stop update
            if trailing_enabled:
                adaptive_mult = get_adaptive_trailing_multiplier(trailing_mult, pos, ltp)
                ts_changed, sl_changed = _update_trailing_stop(pos, ltp, adaptive_mult)
                if ts_changed:
                    state_changed = True
                    # Modify trailing SL on broker ONLY if the stop_loss price actually changed
                    if sl_changed:
                        sl_order_id = pos.get("sl_order_id")
                        if sl_order_id:
                            try:
                                sl_trigger = round_to_tick(pos["stop_loss"])
                                if pos["direction"] == "LONG":
                                    sl_price = round_to_tick(sl_trigger - max(0.05, sl_trigger * 0.002))
                                else:
                                    sl_price = round_to_tick(sl_trigger + max(0.05, sl_trigger * 0.002))
                                if safety_guards.should_send_sl_modify(
                                        pos.get("last_sl_sent"), sl_trigger, sl_price):
                                    await loop.run_in_executor(
                                        None, client.modify_order, sl_order_id, pos["quantity"], "SL", sl_price, sl_trigger
                                    )
                                    pos["last_sl_sent"] = (sl_trigger, sl_price)
                                    log_scan(symbol, f"Trailing SL order modified on broker: Trigger ₹{sl_trigger} | Limit ₹{sl_price}", "info")
                            except Exception as modify_err:
                                err_msg = str(modify_err)
                                if "UDAPI100041" in err_msg or "cancelled/rejected/completed" in err_msg:
                                    log_scan(symbol, f"Trailing SL order {sl_order_id} already closed/inactive on exchange. Resolving position...", "warning")
                                    try:
                                        curr_status = await loop.run_in_executor(None, client.get_order_status, sl_order_id)
                                    except Exception:
                                        curr_status = "UNKNOWN"
                                    
                                    curr_status_lower = curr_status.lower() if curr_status else ""
                                    reason = "STOP LOSS (BROKER HIT)"
                                    if curr_status_lower in ("cancelled", "rejected", "cancelled_after_market"):
                                        reason = f"SL ORDER {curr_status.upper()} - SAFETY EXIT"
                                    
                                    await execute_exit(symbol, pos, ltp if "SAFETY" in reason else pos["stop_loss"], reason, paper_trading, is_broker_hit=("SAFETY" not in reason))
                                    to_remove.append(symbol)
                                    continue
                                else:
                                    log_scan(symbol, f"Failed to modify trailing SL order: {modify_err}", "danger")

            # Partial profit: T1 hit → move stop to break-even, target T2
            if not pos["t1_hit"]:
                t1_hit = (pos["direction"] == "LONG" and ltp >= pos["target"]) or \
                         (pos["direction"] == "SHORT" and ltp <= pos["target"])
                if t1_hit:
                    pos["t1_hit"] = True
                    state_changed = True
                    ep = pos["entry_price"]

                    # Partial exit: sell configurable percentage at T1 to lock in profit
                    pos_lot = int(pos.get("lot_size") or 1)
                    t1_exit_pct = float(cfg.get("partial_exit_t1_pct", 0.50))
                    exit_qty = int(round((pos["quantity"] * t1_exit_pct) / pos_lot)) * pos_lot
                    if exit_qty < pos_lot:
                        exit_qty = pos_lot
                    if exit_qty > pos["quantity"] - pos_lot:
                        exit_qty = pos["quantity"] - pos_lot

                    if cfg.get("enable_partial_exit_t1", True) and exit_qty >= pos_lot and pos["quantity"] > exit_qty:
                        t1_action = "SELL" if pos["direction"] == "LONG" else "BUY"
                        try:
                            t1_order = await order_queue.submit(
                                client.place_order, symbol, t1_action, exit_qty, "MARKET", 0.0, tag="autobot_t1", instrument_key=pos.get("instrument_key")
                            )
                            pos["quantity"] -= exit_qty
                            state_changed = True
                            partial_pnl = round(
                                (t1_order["price"] - ep) * exit_qty if pos["direction"] == "LONG"
                                else (ep - t1_order["price"]) * exit_qty, 2
                            )
                            log_scan(symbol, f"T1 partial exit: {exit_qty} shares @ ₹{t1_order['price']:.2f} | +₹{partial_pnl:.2f} locked", "success")
                        except Exception as ex:
                            log_scan(symbol, f"T1 partial exit failed: {ex}", "danger")

                    # Move stop to break-even plus buffer only if trailing hasn't already passed it
                    buffer_pct = float(cfg.get("breakeven_buffer_pct", 0.0005))
                    buffer_amt = ep * buffer_pct
                    if pos["direction"] == "LONG":
                        be_stop = round(ep + buffer_amt, 2)
                        if pos["stop_loss"] < be_stop:
                            pos["stop_loss"] = be_stop
                            state_changed = True
                    elif pos["direction"] == "SHORT":
                        be_stop = round(ep - buffer_amt, 2)
                        if pos["stop_loss"] > be_stop:
                            pos["stop_loss"] = be_stop
                            state_changed = True
                    pos["target"] = pos["target_2"]
                    state_changed = True
                    log_scan(symbol, f"T1 hit @ ₹{ltp:.2f}. Stop → ₹{pos['stop_loss']:.2f}. Targeting T2 ₹{pos['target_2']:.2f}", "success")

                    # Modify broker-side SL order with new quantity and/or break-even stop loss
                    sl_order_id = pos.get("sl_order_id")
                    if sl_order_id:
                        try:
                            sl_trigger = round_to_tick(pos["stop_loss"])
                            if pos["direction"] == "LONG":
                                sl_price = round_to_tick(sl_trigger - max(0.05, sl_trigger * 0.002))
                            else:
                                sl_price = round_to_tick(sl_trigger + max(0.05, sl_trigger * 0.002))
                            await loop.run_in_executor(
                                None, client.modify_order, sl_order_id, pos["quantity"], "SL", sl_price, sl_trigger
                            )
                            log_scan(symbol, f"Broker-side SL order modified on T1 hit: Qty {pos['quantity']} | Trigger ₹{sl_trigger} | Limit ₹{sl_price}", "info")
                        except Exception as qty_err:
                            err_msg = str(qty_err)
                            if "UDAPI100041" in err_msg or "cancelled/rejected/completed" in err_msg:
                                log_scan(symbol, f"SL order {sl_order_id} already closed/inactive on exchange during T1 hit. Resolving position...", "warning")
                                try:
                                    curr_status = await loop.run_in_executor(None, client.get_order_status, sl_order_id)
                                except Exception:
                                    curr_status = "UNKNOWN"
                                
                                curr_status_lower = curr_status.lower() if curr_status else ""
                                reason = "STOP LOSS (BROKER HIT)"
                                if curr_status_lower in ("cancelled", "rejected", "cancelled_after_market"):
                                    reason = f"SL ORDER {curr_status.upper()} - SAFETY EXIT"
                                
                                await execute_exit(symbol, pos, ltp if "SAFETY" in reason else pos["stop_loss"], reason, paper_trading, is_broker_hit=("SAFETY" not in reason))
                                to_remove.append(symbol)
                                continue
                            else:
                                log_scan(symbol, f"Failed to modify SL order on T1 hit: {qty_err}", "danger")

            # Time Stop check
            time_stop_triggered = False
            if cfg.get("enable_time_stop", False):
                time_stop_mins = int(cfg.get("time_stop_minutes", 60))
                try:
                    entry_time_dt = datetime.fromisoformat(pos["entry_time"])
                    elapsed_mins = (get_ist_now() - entry_time_dt).total_seconds() / 60.0
                    if elapsed_mins >= time_stop_mins:
                        time_stop_triggered = True
                except Exception as ex:
                    log_scan(symbol, f"Time stop check error: {ex}", "danger")

            # Final exit check
            exit_triggered = False
            exit_reason = ""

            # Dynamic Indicator-based Exits (Momentum Exit)
            if cfg.get("enable_momentum_exit", True) and "ema_9" in pos and "vwap" in pos:
                ema_9_val = pos["ema_9"]
                vwap_val = pos["vwap"]
                if pos["direction"] == "LONG" and ltp < ema_9_val and ltp < vwap_val:
                    exit_triggered, exit_reason = True, "MOMENTUM EXIT (9EMA/VWAP CROSS)"
                elif pos["direction"] == "SHORT" and ltp > ema_9_val and ltp > vwap_val:
                    exit_triggered, exit_reason = True, "MOMENTUM EXIT (9EMA/VWAP CROSS)"

            if exit_triggered:
                pass  # already populated reason above
            elif time_stop_triggered:
                exit_triggered, exit_reason = True, "TIME STOP"
            elif pos["direction"] == "LONG":
                if pos["t1_hit"] and ltp >= pos["target"]:
                    exit_triggered, exit_reason = True, "TARGET-2 HIT"
                elif ltp <= pos["stop_loss"]:
                    # Bypass local SL trigger for live trades with an active broker-side SL order
                    if not (not paper_trading and pos.get("sl_order_id")):
                        exit_triggered, exit_reason = True, "STOP LOSS" if not pos["t1_hit"] else "TRAIL/B-E STOP"
            else:
                if pos["t1_hit"] and ltp <= pos["target"]:
                    exit_triggered, exit_reason = True, "TARGET-2 HIT"
                elif ltp >= pos["stop_loss"]:
                    # Bypass local SL trigger for live trades with an active broker-side SL order
                    if not (not paper_trading and pos.get("sl_order_id")):
                        exit_triggered, exit_reason = True, "STOP LOSS" if not pos["t1_hit"] else "TRAIL/B-E STOP"

            if exit_triggered:
                # C2: only retire the position if the exit actually completed. A failed
                # closing order returns False, so we keep the position under management and
                # retry it on the next cycle instead of orphaning an open live position.
                if await execute_exit(symbol, pos, ltp, exit_reason, paper_trading):
                    to_remove.append(symbol)

        except Exception as e:
            log_scan(symbol, f"Position management error: {e}", "danger")

    for sym in to_remove:
        _remove_position(sym)
        state_changed = True
    if state_changed:
        save_state()


async def manage_shadow_positions(quotes):
    global shadow_positions
    if not shadow_positions:
        return
    to_remove = []
    cfg = client.config
    trailing_enabled = cfg.get("enable_trailing_stop", True)
    trailing_mult = float(cfg.get("trailing_atr_multiplier", 1.5))

    for symbol, pos in list(shadow_positions.items()):
        try:
            quote = quotes.get(pos["instrument_key"])
            if not quote:
                continue
            ltp = quote["ltp"]
            pos["current_price"] = ltp

            if pos["direction"] == "LONG":
                pos["pnl"] = (ltp - pos["entry_price"]) * pos["quantity"]
            else:
                pos["pnl"] = (pos["entry_price"] - ltp) * pos["quantity"]

            # Track excursion
            pos["mfe"] = max(pos.get("mfe", 0.0), pos["pnl"])
            pos["mae"] = min(pos.get("mae", 0.0), pos["pnl"])

            # Regime-Adaptive Target Expansion: Expand Target 2 by 1.5x in strong trend regimes
            if not pos.get("target_expanded_by_regime", False):
                regime = pos.get("regime", "unknown")
                if (pos["direction"] == "LONG" and regime in ("Strong Uptrend", "Uptrend")) or \
                   (pos["direction"] == "SHORT" and regime in ("Strong Downtrend", "Downtrend")):
                    ep = pos["entry_price"]
                    orig_t2 = pos.get("target_2", pos["target"])
                    dist = abs(orig_t2 - ep)
                    if pos["direction"] == "LONG":
                        pos["target_2"] = round(ep + (dist * 1.5), 2)
                    else:
                        pos["target_2"] = round(ep - (dist * 1.5), 2)
                    pos["target_expanded_by_regime"] = True
                    log_scan(symbol, f"[Shadow] Strong trend detected ({regime}). Dynamic Target 2 extended from ₹{orig_t2} to ₹{pos['target_2']}", "success")

            # Trailing stop update
            if trailing_enabled:
                adaptive_mult = get_adaptive_trailing_multiplier(trailing_mult, pos, ltp)
                _, _ = _update_trailing_stop(pos, ltp, adaptive_mult)

            # Partial profit: T1 hit -> move stop to break-even, target T2
            if not pos["t1_hit"]:
                t1_hit = (pos["direction"] == "LONG" and ltp >= pos["target"]) or \
                         (pos["direction"] == "SHORT" and ltp <= pos["target"])
                if t1_hit:
                    pos["t1_hit"] = True
                    ep = pos["entry_price"]

                    # Partial exit simulation (mock configurable percentage reduction)
                    pos_lot = int(pos.get("lot_size") or 1)
                    t1_exit_pct = float(cfg.get("partial_exit_t1_pct", 0.50))
                    exit_qty = int(round((pos["quantity"] * t1_exit_pct) / pos_lot)) * pos_lot
                    if exit_qty < pos_lot:
                        exit_qty = pos_lot
                    if exit_qty > pos["quantity"] - pos_lot:
                        exit_qty = pos["quantity"] - pos_lot

                    if cfg.get("enable_partial_exit_t1", True) and exit_qty >= pos_lot and pos["quantity"] > exit_qty:
                        pos["quantity"] -= exit_qty
                        partial_pnl = round(
                            (ltp - ep) * exit_qty if pos["direction"] == "LONG"
                            else (ep - ltp) * exit_qty, 2
                        )
                        log_scan(symbol, f"[Shadow] T1 partial exit: {exit_qty} shares @ ₹{ltp:.2f} | +₹{partial_pnl:.2f} locked (simulated)", "success")

                    # Move stop to break-even plus buffer only if trailing hasn't already passed it
                    buffer_pct = float(cfg.get("breakeven_buffer_pct", 0.0005))
                    buffer_amt = ep * buffer_pct
                    if pos["direction"] == "LONG":
                        be_stop = round(ep + buffer_amt, 2)
                        if pos["stop_loss"] < be_stop:
                            pos["stop_loss"] = be_stop
                    elif pos["direction"] == "SHORT":
                        be_stop = round(ep - buffer_amt, 2)
                        if pos["stop_loss"] > be_stop:
                            pos["stop_loss"] = be_stop
                    pos["target"] = pos["target_2"]
                    log_scan(symbol, f"[Shadow] T1 hit @ ₹{ltp:.2f}. Stop -> ₹{pos['stop_loss']:.2f}. Targeting T2 ₹{pos['target_2']:.2f}", "success")

            # Time Stop check
            time_stop_triggered = False
            if cfg.get("enable_time_stop", False):
                time_stop_mins = int(cfg.get("time_stop_minutes", 60))
                try:
                    entry_time_dt = datetime.fromisoformat(pos["entry_time"])
                    elapsed_mins = (get_ist_now() - entry_time_dt).total_seconds() / 60.0
                    if elapsed_mins >= time_stop_mins:
                        time_stop_triggered = True
                except Exception as ex:
                    log_scan(symbol, f"Time stop check error: {ex}", "danger")

            # Final exit check
            exit_triggered = False
            exit_reason = ""

            # Dynamic Indicator-based Exits (Momentum Exit)
            if cfg.get("enable_momentum_exit", True) and "ema_9" in pos and "vwap" in pos:
                ema_9_val = pos["ema_9"]
                vwap_val = pos["vwap"]
                if pos["direction"] == "LONG" and ltp < ema_9_val and ltp < vwap_val:
                    exit_triggered, exit_reason = True, "MOMENTUM EXIT (9EMA/VWAP CROSS)"
                elif pos["direction"] == "SHORT" and ltp > ema_9_val and ltp > vwap_val:
                    exit_triggered, exit_reason = True, "MOMENTUM EXIT (9EMA/VWAP CROSS)"

            if exit_triggered:
                pass  # already populated reason above
            elif time_stop_triggered:
                exit_triggered, exit_reason = True, "TIME STOP"
            elif pos["direction"] == "LONG":
                if pos["t1_hit"] and ltp >= pos["target"]:
                    exit_triggered, exit_reason = True, "TARGET-2 HIT"
                elif ltp <= pos["stop_loss"]:
                    exit_triggered, exit_reason = True, "STOP LOSS" if not pos["t1_hit"] else "TRAIL/B-E STOP"
            else:
                if pos["t1_hit"] and ltp <= pos["target"]:
                    exit_triggered, exit_reason = True, "TARGET-2 HIT"
                elif ltp >= pos["stop_loss"]:
                    exit_triggered, exit_reason = True, "STOP LOSS" if not pos["t1_hit"] else "TRAIL/B-E STOP"

            if exit_triggered:
                await execute_exit(symbol, pos, ltp, exit_reason, paper_trading=True, is_shadow=True)
                to_remove.append(symbol)

        except Exception as e:
            log_scan(symbol, f"Shadow position management error: {e}", "danger")

    for sym in to_remove:
        shadow_positions.pop(sym, None)


async def position_manager_loop():
    global bot_running, active_positions, shadow_positions, _prev_total_pnl
    while True:
        try:
            watchlist = client.config.get("watchlist", [])
            if active_positions or shadow_positions or watchlist:
                # Gather instrument keys for OPEN positions only. The watchlist is
                # deliberately excluded here: this loop runs ~2x/sec and quoting the whole
                # watchlist every tick hammered the Upstox market-quote endpoint into
                # UDAPI10005 "Too Many Request Sent", starving the quotes the open positions
                # actually need. The UI's watchlist prices come from the scanner matrix
                # (scanner_loop), not from this broadcast, so nothing is lost.
                instrument_keys = []
                # 1. Active positions
                for pos in active_positions.values():
                    if pos["instrument_key"] not in instrument_keys:
                        instrument_keys.append(pos["instrument_key"])
                # 1b. Shadow positions
                for pos in shadow_positions.values():
                    if pos["instrument_key"] not in instrument_keys:
                        instrument_keys.append(pos["instrument_key"])

                # Fetch quotes. When the decoupled market feed is healthy, read the warm
                # cache (non-blocking) and only REST-fetch the keys it's missing/stale on;
                # otherwise fall back to a single inline REST batch (original behavior).
                loop = asyncio.get_running_loop()
                if market_feed is not None and market_feed.healthy():
                    market_feed.set_keys(instrument_keys)
                    quotes = market_feed.get_many(instrument_keys, max_age=5.0)
                    missing = [k for k in instrument_keys if k not in quotes]
                    if missing:
                        rest = await loop.run_in_executor(
                            None, functools.partial(client.get_market_quotes, missing)
                        )
                        if rest:
                            quotes.update(rest)
                else:
                    if market_feed is not None:
                        market_feed.set_keys(instrument_keys)   # warm it up for next ticks
                    quotes = await loop.run_in_executor(
                        None, functools.partial(client.get_market_quotes, instrument_keys)
                    )

                # Update indicators for active and shadow positions periodically (every 30 seconds)
                import time
                now_ts = time.time()
                for pos in list(active_positions.values()) + list(shadow_positions.values()):
                    if now_ts - pos.get("last_indicator_update", 0.0) >= 30.0:
                        await update_position_indicators(pos)
                        pos["last_indicator_update"] = now_ts
                
                # Manage positions if bot running and we have positions
                if active_positions:
                    if bot_running:
                        cfg = client.config
                        trailing_enabled = cfg.get("enable_trailing_stop", True)
                        trailing_mult = float(cfg.get("trailing_atr_multiplier", 1.5))
                        paper_trading = cfg.get("paper_trading", True)
                        
                        await manage_existing_positions(paper_trading, trailing_enabled, trailing_mult, quotes)
                    else:
                        # Just update positions prices in memory
                        for pos in active_positions.values():
                            quote = quotes.get(pos["instrument_key"])
                            if quote:
                                ltp = quote["ltp"]
                                pos["current_price"] = ltp
                                if pos["direction"] == "LONG":
                                    pos["pnl"] = (ltp - pos["entry_price"]) * pos["quantity"]
                                else:
                                    pos["pnl"] = (pos["entry_price"] - ltp) * pos["quantity"]

                    # R3: fast daily-loss circuit breaker (1s cadence). scanner_loop only
                    # re-checks every ~10s, which can let a sharp adverse move blow well past
                    # the limit before it halts. Re-evaluated here on freshly-marked P&L; the
                    # C1 exit guard makes squaring-off safe even mid-manage. Applies in both
                    # paper and live so paper mode exercises the same risk path (Section 0 rule 2).
                    if bot_running and active_positions:
                        live_pnl = get_total_daily_pnl()
                        fast_decision = risk_manager.check_daily_loss(live_pnl)
                        if not fast_decision.allowed:
                            log_scan("SYSTEM", f"{fast_decision.reason} Fast halt & square-off.", "danger")
                            bot_running = False
                            await square_off_all("DAILY LOSS LIMIT")

                    # Real-time safety guards (Tier-2): force-exit a position whose loss blew
                    # past where its stop should have fired, and halt on an impossible one-cycle
                    # P&L drop (data glitch). Additive to the daily-loss halt above.
                    if client.config.get("enable_safety_guards", True) and bot_running and active_positions:
                        _k = float(client.config.get("position_anomaly_k", 3.0))
                        _paper = client.config.get("paper_trading", True)
                        for _sym, _pos in list(active_positions.items()):
                            if safety_guards.position_loss_anomalous(
                                    _pos["entry_price"], _pos["stop_loss"], _pos["quantity"],
                                    _pos.get("current_price", _pos["entry_price"]), _pos["direction"], k=_k):
                                log_scan(_sym, f"SAFETY: loss exceeded {_k}x risk — stop failed to fire; force-exiting.", "danger")
                                if await execute_exit(_sym, _pos, _pos.get("current_price", _pos["entry_price"]),
                                                      "SAFETY ANOMALY FORCE-EXIT", _paper):
                                    _remove_position(_sym)
                        _cur_total = get_total_daily_pnl()
                        if safety_guards.cycle_loss_spike(_prev_total_pnl, _cur_total,
                                                          float(client.config.get("max_daily_loss", 4000))):
                            log_scan("SYSTEM", f"SAFETY: daily P&L dropped >1 limit in one cycle ({_prev_total_pnl}->{_cur_total}) — halting (data glitch).", "danger")
                            bot_running = False
                            await square_off_all("SAFETY CYCLE-LOSS SPIKE")
                        _prev_total_pnl = _cur_total

                # Manage shadow positions if bot running
                if shadow_positions:
                    if bot_running:
                        await manage_shadow_positions(quotes)
                    else:
                        # Just update shadow positions prices in memory
                        for pos in shadow_positions.values():
                            quote = quotes.get(pos["instrument_key"])
                            if quote:
                                ltp = quote["ltp"]
                                pos["current_price"] = ltp
                                if pos["direction"] == "LONG":
                                    pos["pnl"] = (ltp - pos["entry_price"]) * pos["quantity"]
                                else:
                                    pos["pnl"] = (pos["entry_price"] - ltp) * pos["quantity"]

                # Build symbol -> ltp quotes map for open positions (watchlist quotes are no
                # longer fetched here — see the instrument_keys note above; the UI sources
                # watchlist prices from the scanner matrix).
                quotes_by_symbol = {}
                for pos in active_positions.values():
                    quotes_by_symbol[pos["symbol"]] = pos["current_price"]
                
                # Broadcast the real-time update
                await manager.broadcast({
                    "type": "realtime_update",
                    "positions": list(active_positions.values()),
                    "total_daily_pnl": round(get_total_daily_pnl(), 2),
                    "daily_pnl": round(daily_pnl, 2),
                    "quotes": quotes_by_symbol
                })
        except Exception as e:
            print(f"Error in position_manager_loop: {e}")
        
        await asyncio.sleep(0.5)


async def execute_exit(symbol, pos, exit_price, reason, paper_trading, is_shadow=False, is_broker_hit=False,
                       pos_already_removed=False):
    """Closes a position. Returns True only if the exit completed (order placed / shadow /
    broker-hit recorded); returns False if it was a duplicate or the closing order failed —
    in which case the caller MUST keep the position in active_positions so it stays monitored.

    pos_already_removed=True is for entry-abort paths that intentionally exit a position not
    (or no longer) tracked in active_positions; every other caller must pass the live object."""
    global trade_history, daily_pnl

    # ── C1: duplicate-exit guard (synchronous, no await before it) ──
    # Shadow positions live in a separate dict and place no real orders, so they are exempt.
    if not is_shadow:
        if symbol in _exiting_symbols:
            log_scan(symbol, f"Exit already in progress — skipping duplicate ({reason}).", "info")
            return False
        # C1b: staleness check — the in-flight claim above only covers the window until
        # _remove_position() clears it. A concurrent square-off path that snapshotted the
        # book earlier can arrive here holding a reference to a position that has since been
        # closed (2026-07-06: MAZDA closed twice by KILL SWITCH + MANUAL SQUARE-OFF racing)
        # or replaced by a same-symbol re-entry. Identity check rejects both.
        if not pos_already_removed and active_positions.get(symbol) is not pos:
            log_scan(symbol, f"Position already closed/replaced — skipping stale exit ({reason}).", "info")
            return False
        _exiting_symbols.add(symbol)

    exit_action = "SELL" if pos["direction"] == "LONG" else "BUY"
    label = "Shadow" if is_shadow else "Live/Paper"
    log_scan(symbol, f"Exiting {label} {pos['direction']} @ ₹{exit_price:.2f} — {reason}", "warning")

    # Cancel pending broker-side stop loss order if we are exiting manually or via target
    sl_order_id = pos.get("sl_order_id")
    if sl_order_id and not is_shadow and not is_broker_hit:
        try:
            log_scan(symbol, f"Cancelling pending broker-side SL order {sl_order_id}...", "info")
            await order_queue.submit(client.cancel_order, sl_order_id)
            log_scan(symbol, f"SL order {sl_order_id} cancelled successfully.", "info")
        except Exception as cancel_err:
            log_scan(symbol, f"Failed to cancel pending SL order: {cancel_err}", "warning")

    try:
        skip_order = is_shadow or is_broker_hit
        if not skip_order and not paper_trading:
            # Live-mode guard: verify the broker still holds this quantity before sending a
            # closing order — if the operator squared off from another device moments ago, a
            # "closing" order would OPEN a reverse position. On verification failure (None)
            # proceed anyway: a stop-loss exit must never be blocked by an API blip.
            try:
                rows = await asyncio.get_running_loop().run_in_executor(None, client.get_positions)
            except Exception:
                rows = None
            if rows is not None and not _position_still_held(pos, _net_positions_by_key(rows)):
                log_scan(symbol, "Broker no longer holds this position — closed externally. "
                                 "Recording exit at last price WITHOUT placing an order.", "danger")
                reason = f"{reason} + CLOSED EXTERNALLY"
                skip_order = True

        if skip_order:
            final_price = exit_price
        else:
            order = await order_queue.submit(
                client.place_order, symbol, exit_action, pos["quantity"], "MARKET", 0.0, tag="autobot_exit", instrument_key=pos.get("instrument_key")
            )
            final_price = order["price"]

        if pos["direction"] == "LONG":
            pnl = (final_price - pos["entry_price"]) * pos["quantity"]
        else:
            pnl = (pos["entry_price"] - final_price) * pos["quantity"]

        # Realistic round-trip transaction charges (brokerage/STT/exchange/GST/SEBI/stamp).
        # Real in paper AND live — small intraday profits are eaten by these. Shadow trades are
        # counterfactual (no capital engaged), so they're excluded.
        charges = 0.0
        if not is_shadow and client.config.get("enable_realistic_costs", True):
            _qty = pos["quantity"]
            if pos["direction"] == "LONG":
                _buy_v, _sell_v = pos["entry_price"] * _qty, final_price * _qty
            else:
                _sell_v, _buy_v = pos["entry_price"] * _qty, final_price * _qty
            _ch = execution_costs.intraday_equity_charges(
                _buy_v, _sell_v,
                brokerage_per_order=float(client.config.get("brokerage_per_order", 20.0)),
                stt_pct=float(client.config.get("stt_pct", 0.00025)),
                exchange_txn_pct=float(client.config.get("exchange_txn_pct", 0.0000297)),
                gst_pct=float(client.config.get("gst_pct", 0.18)),
                sebi_per_crore=float(client.config.get("sebi_per_crore", 10.0)),
                stamp_pct=float(client.config.get("stamp_pct", 0.00003)))
            charges = _ch["total"]
            pnl -= charges

        # Anomaly Check: Extreme Slippage on Exit
        slippage_exit = abs(final_price - exit_price)
        # If exit slippage is extremely large (e.g. > 1.5x ATR), log a warning
        if not is_shadow and pos.get("atr_at_entry") and slippage_exit > 1.5 * pos["atr_at_entry"]:
            log_scan(symbol, f"Excessive exit slippage (₹{slippage_exit:.2f} > 1.5x ATR).", "warning")

        try:
            entry_dt = datetime.fromisoformat(pos["entry_time"])
            holding_minutes = round((get_ist_now() - entry_dt).total_seconds() / 60, 1)
        except Exception:
            holding_minutes = None

        record = {
            "symbol": symbol,
            "strategy": pos["strategy"],
            "direction": pos["direction"],
            "quantity": pos["quantity"],
            "entry_price": pos["entry_price"],
            "entry_time": pos["entry_time"],
            "exit_price": final_price,
            "exit_time": get_ist_now().isoformat(),
            "pnl": round(pnl, 2),
            "charges": round(charges, 2),
            "reason": reason,
            # Risk levels the position was managed with — without these the dashboard/CSV
            # can never reconstruct R-multiples for closed trades.
            "stop_loss": pos.get("stop_loss"),
            "target_1": pos.get("target"),
            "target_2": pos.get("target_2"),
            "t1_hit": pos.get("t1_hit", False),
            "regime": pos.get("regime", "unknown"),
            "htf_trend": pos.get("htf_trend", "neutral"),
            "is_fno": pos.get("is_fno", False),
            "contract": pos.get("contract", ""),
            "atr_at_entry": pos.get("atr_at_entry"),
            "market_context": pos.get("market_context", {}),
            "holding_minutes": holding_minutes,
            "mae": round(pos.get("mae", 0.0), 2),
            "mfe": round(pos.get("mfe", 0.0), 2),
            "confluence_score": pos.get("confluence_score", 0),
            "trigger_level_source": pos.get("trigger_level_source"),
            "trigger_level_price": pos.get("trigger_level_price"),
            "trigger_level_score": pos.get("trigger_level_score"),
            # Candlestick patterns detected at ENTRY — without these,
            # data/history/pattern_stats.jsonl has no input and stays 0 bytes (blocker #5).
            "candlestick_patterns": pos.get("candlestick_patterns", []),
            "is_shadow_trade": is_shadow
        }

        trade_history.append(record)
        if not is_shadow:
            daily_pnl += pnl

        # Section 6 JSONL logging (data/wins.jsonl / losses.jsonl) — additive alongside the
        # existing trade_history.json/SQLite persistence above. Shadow trades are counterfactual
        # simulations (no real capital/paper P&L engaged), not real trades, so they're excluded.
        if not is_shadow:
            try:
                jsonl_logger.log_trade(record, mode=("paper" if paper_trading else "live"))
            except Exception as jsonl_err:
                print(f"[jsonl_logger] Error logging trade: {jsonl_err}")

        # M5: Trade History Purge — keep only last 500 trades in memory
        # Older trades are safely persisted in SQLite; the in-memory list is for speed.
        _MAX_TRADE_HISTORY = 500
        if len(trade_history) > _MAX_TRADE_HISTORY:
            trade_history = trade_history[-_MAX_TRADE_HISTORY:]
        
        # M5b: Update symbol memory for per-symbol learning
        try:
            from symbol_memory import record_trade as _sm_record
            _sm_record(
                symbol=symbol,
                strategy=pos.get("strategy", ""),
                direction=pos.get("direction", ""),
                pnl=pnl,
                regime=pos.get("regime", "unknown"),
                entry_time=pos.get("entry_time", ""),
                holding_minutes=holding_minutes or 0
            )
        except Exception:
            pass  # Non-critical
        
        save_state()

        cat = "success" if pnl >= 0 else "danger"
        _chg_note = f" | charges ₹{charges:.2f}" if charges else ""
        log_scan(symbol, f"Closed ₹{pnl:+.2f} ({reason}){_chg_note} | Daily PnL ₹{daily_pnl:+.2f}", cat)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast({
                "type": "trade_event",
                "event": "exit",
                "symbol": symbol,
                "direction": pos["direction"],
                "quantity": pos["quantity"],
                "exit_price": final_price,
                "pnl": round(pnl, 2),
                "reason": reason,
                "is_shadow": is_shadow
            }))
        except Exception:
            pass

        return True

    except Exception as e:
        # C2: the closing order did not go through. Un-claim the guard so the position is
        # retried next cycle, and signal failure so the caller KEEPS it under management
        # rather than orphaning a live position with no stop-loss.
        log_scan(symbol, f"Exit order failed — position retained for monitoring/retry: {e}", "danger")
        if not is_shadow:
            _exiting_symbols.discard(symbol)
        return False


async def square_off_all(reason="MANUAL"):
    global active_positions
    paper_trading = client.config.get("paper_trading", True)
    loop = asyncio.get_running_loop()
    for symbol in list(active_positions.keys()):
        pos = active_positions[symbol]
        try:
            quote = await loop.run_in_executor(
                None, functools.partial(client.get_market_quote, pos["instrument_key"])
            )
            ep = quote["ltp"] if quote else pos["entry_price"]
            if await execute_exit(symbol, pos, ep, reason, paper_trading):
                _remove_position(symbol)
            else:
                log_scan(symbol, "Square-off could not close position — will retry next cycle.", "danger")
        except Exception as e:
            log_scan(symbol, f"Square-off error: {e}", "danger")
    save_state()


def _log_session_report(report):
    m = report.get("metrics", {})
    log_scan("SESSION", f"Trades: {m.get('total_trades',0)} | WR: {m.get('win_rate',0)}% | PF: {m.get('profit_factor',0)} | Sharpe: {m.get('sharpe_ratio',0)}", "info")
    log_scan("SESSION", f"Max DD: ₹{m.get('max_drawdown',0)} | Expectancy: ₹{m.get('expectancy',0)} | R:R {m.get('risk_reward',0)}", "info")
    for rec in report.get("insights", {}).get("recommendations", []):
        log_scan("SESSION", rec, "warning")


# ─── Startup / Shutdown ────────────────────────────────────────────────────────
# Lifespan managed via lifespan async context manager on app creation.


# ─── Static Files ──────────────────────────────────────────────────────────────

@app.get("/static/{file_path:path}")
def get_static(file_path: str):
    return FileResponse(os.path.join("static", file_path))


@app.get("/")
def dashboard():
    with open("static/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


# ─── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/login")
def login():
    client.load_config()
    return RedirectResponse(client.get_auth_url())


@app.get("/callback")
def oauth_callback(code: str):
    success = client.exchange_code(code)
    if success:
        threading.Thread(target=client.download_instruments).start()
        return HTMLResponse("""
            <html>
            <head>
                <meta http-equiv="refresh" content="2;url=/">
                <style>
                    body{margin:0;background:#0f172a;display:flex;align-items:center;
                         justify-content:center;height:100vh;font-family:sans-serif}
                    .box{text-align:center;color:#a1f0a1;padding:40px}
                    h2{font-size:1.6rem;margin-bottom:8px}
                    p{color:#94a3b8;font-size:.95rem}
                </style>
            </head>
            <body>
                <div class="box">
                    <h2>&#10003; Authenticated Successfully</h2>
                    <p>Redirecting to dashboard in 2 seconds…</p>
                </div>
            </body>
            </html>
        """)
    return HTMLResponse("Authentication failed. Check server logs.", status_code=400)


# ─── API Endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status():
    client.load_config()
    cfg = client.config
    return {
        "bot_running": bot_running,
        "authenticated": bool(client.access_token),
        "paper_trading": cfg.get("paper_trading", True),
        "max_open_positions": cfg.get("max_open_positions", 3),
        "max_daily_loss": cfg.get("max_daily_loss", 1000.0),
        "max_risk_per_trade": cfg.get("max_risk_per_trade", 500.0),
        "max_position_value": cfg.get("max_position_value", 50000.0),
        "trade_start_time": cfg.get("trade_start_time", "09:30"),
        "trade_end_time": cfg.get("trade_end_time", "14:30"),
        "square_off_time": cfg.get("square_off_time", "15:10"),
        "enable_trailing_stop": cfg.get("enable_trailing_stop", True),
        "trailing_atr_multiplier": cfg.get("trailing_atr_multiplier", 1.5),
        "watchlist": cfg.get("watchlist", []),
        "auto_nifty50_watchlist": cfg.get("auto_nifty50_watchlist", True),
        "enable_fno": cfg.get("enable_fno", False),
        "fno_type": cfg.get("fno_type", "FUT"),
        "option_delta": cfg.get("option_delta", 0.50),
        "fno_max_risk_per_trade": cfg.get("fno_max_risk_per_trade", 2000.0),
        "fno_max_lots": cfg.get("fno_max_lots", 1),
        "enable_max_capacity": cfg.get("enable_max_capacity", False),
        "capacity_buffer_pct": cfg.get("capacity_buffer_pct", 0.05),
        "daily_pnl": round(get_total_daily_pnl(), 2),
        "open_positions_count": len(active_positions),
        "scanner_last_loop": scanner_state["last_loop"],
        "scanner_last_scan": scanner_state["last_scan"],
        "scanner_last_checked": scanner_state["last_scan_checked"],
        "scanner_last_summary": scanner_state["last_scan_summary"],
        # Signal quality engine
        "enable_time_filter": cfg.get("enable_time_filter", True),
        "enable_volatility_filter": cfg.get("enable_volatility_filter", True),
        "enable_nifty_filter": cfg.get("enable_nifty_filter", True),
        "enable_confluence_filter": cfg.get("enable_confluence_filter", True),
        "min_confluence_score": cfg.get("min_confluence_score", 4),
        "enable_kelly_sizing": cfg.get("enable_kelly_sizing", True),
        "enable_loss_halt": cfg.get("enable_loss_halt", True),
        "max_consecutive_losses": cfg.get("max_consecutive_losses", 3),
        "loss_halt_minutes": cfg.get("loss_halt_minutes", 30),
        "enable_partial_exit_t1": cfg.get("enable_partial_exit_t1", True),
        "max_trades_per_symbol_per_day": cfg.get("max_trades_per_symbol_per_day", 2),
        "enable_vwap_trend_pullback": cfg.get("enable_vwap_trend_pullback", True),
        "vwap_tp_confidence_threshold": cfg.get("vwap_tp_confidence_threshold", 80),
        "enable_candlestick_confluence": cfg.get("enable_candlestick_confluence", True),
        "cpc_volume_multiplier": cfg.get("cpc_volume_multiplier", 1.5),
        "enable_level_aware_targets": cfg.get("enable_level_aware_targets", True),
        "enable_full_market_scan": cfg.get("enable_full_market_scan", True),
        "scan_nse": cfg.get("scan_nse", True),
        "scan_bse": cfg.get("scan_bse", False),
        "min_scan_volume": cfg.get("min_scan_volume", 50000),
        "min_scan_price": cfg.get("min_scan_price", 20.0),
        "min_scan_change_pct": cfg.get("min_scan_change_pct", 1.5),
        "enable_one_percent_risk": cfg.get("enable_one_percent_risk", False),
        "min_confidence_threshold": cfg.get("min_confidence_threshold", 60),
        "max_weekly_loss_pct": cfg.get("max_weekly_loss_pct", 0.05),
        "enable_time_stop": cfg.get("enable_time_stop", False),
        "time_stop_minutes": cfg.get("time_stop_minutes", 60),
        "backtest_slippage_pct": cfg.get("backtest_slippage_pct", 0.0005),
    }


@app.post("/api/settings")
def update_settings(settings: dict):
    client.load_config()
    allowed_keys = [
        "paper_trading", "max_open_positions", "max_daily_loss",
        "max_risk_per_trade", "max_position_value",
        "trade_start_time", "trade_end_time", "square_off_time",
        "enable_trailing_stop", "trailing_atr_multiplier", "watchlist",
        "auto_nifty50_watchlist",
        "enable_fno", "fno_type", "option_delta", "fno_max_risk_per_trade", "fno_max_lots",
        "enable_max_capacity", "capacity_buffer_pct",
        # Signal quality engine toggles
        "enable_time_filter", "enable_volatility_filter", "enable_nifty_filter",
        "enable_confluence_filter", "min_confluence_score",
        "enable_loss_halt", "max_consecutive_losses", "loss_halt_minutes",
        "enable_kelly_sizing",
        "enable_partial_exit_t1", "max_trades_per_symbol_per_day",
        "enable_vwap_trend_pullback", "vwap_tp_confidence_threshold",
        "enable_candlestick_confluence", "cpc_volume_multiplier",
        "enable_level_aware_targets",
        "enable_full_market_scan", "scan_nse", "scan_bse",
        "min_scan_volume", "min_scan_price", "min_scan_change_pct",
        "enable_one_percent_risk", "min_confidence_threshold", "max_weekly_loss_pct",
        "enable_time_stop", "time_stop_minutes", "backtest_slippage_pct",
        "auto_start_scanner",
        # Real-time safety guards (spec 2026-07-08)
        "enable_safety_guards", "quote_stale_seconds", "quote_jump_reject_pct",
        "position_anomaly_k", "order_rate_max", "order_rate_window_s", "scanner_stall_minutes",
        # Realistic fills + transaction costs (plan 2026-07-08)
        "enable_realistic_costs", "spread_bps", "slippage_bps", "brokerage_per_order",
        "stt_pct", "exchange_txn_pct", "gst_pct", "sebi_per_crore", "stamp_pct",
        # Market-depth / liquidity gate (plan 2026-07-08)
        "enable_liquidity_gate", "max_spread_bps", "min_depth_ratio",
        # Per-symbol earnings/event blackout (2026-07-13)
        "enable_earnings_blackout", "earnings_blackout_days_before", "earnings_blackout_days_after",
    ]

    for key in allowed_keys:
        if key in settings:
            client.config[key] = settings[key]
    client.save_config()
    return {"status": "success", "message": "Settings saved."}


@app.get("/api/scanner")
def get_scanner():
    """Live per-symbol scan decisions + engine context of the last sweep."""
    return {"context": scan_context, "matrix": list(scan_matrix.values())}


@app.get("/api/my-ip")
def get_my_ip():
    """Returns the public IP address of the bot session (verifies proxy)."""
    try:
        response = client.session.get("https://api.ipify.org?format=json", timeout=5)
        if response.status_code == 200:
            return response.json()
        return {"error": f"Status code {response.status_code}", "ip": "unknown"}
    except Exception as e:
        return {"error": str(e), "ip": "unknown"}


@app.get("/api/positions")
def get_positions():
    return list(active_positions.values())


@app.get("/api/trades")
def get_trades():
    today = get_ist_now().date().isoformat()
    return [t for t in trade_history if t.get("exit_time", "").startswith(today)]


@app.get("/api/trades/all")
def get_all_trades():
    return trade_history


@app.get("/api/trades/export")
def export_trades_csv():
    import csv
    import io
    from fastapi.responses import StreamingResponse
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    headers = [
        "symbol", "direction", "strategy", "entry_price", "entry_time",
        "exit_price", "exit_time", "pnl", "pnl_pct", "quantity",
        "stop_loss", "target_1", "target_2", "confluence_score",
        "regime", "vix_at_entry", "paper_trading", "is_shadow_trade",
        "exit_reason", "holding_time_mins"
    ]
    writer.writerow(headers)
    
    for t in trade_history:
        holding_time = ""
        try:
            if t.get("entry_time") and t.get("exit_time"):
                ent = datetime.fromisoformat(t["entry_time"])
                ext = datetime.fromisoformat(t["exit_time"])
                holding_time = round((ext - ent).total_seconds() / 60.0, 1)
        except Exception:
            pass
            
        writer.writerow([
            t.get("symbol", ""),
            t.get("direction", ""),
            t.get("strategy", ""),
            t.get("entry_price", ""),
            t.get("entry_time", ""),
            t.get("exit_price", ""),
            t.get("exit_time", ""),
            t.get("pnl", ""),
            t.get("pnl_pct", ""),
            t.get("quantity", ""),
            t.get("stop_loss", ""),
            t.get("target_1", ""),
            t.get("target_2", ""),
            t.get("confluence_score", ""),
            t.get("regime", ""),
            t.get("vix_at_entry", ""),
            t.get("paper_trading", ""),
            t.get("is_shadow_trade", ""),
            t.get("exit_reason", t.get("reason", "")),  # records store the exit reason as "reason"
            holding_time
        ])
        
    output.seek(0)
    filename = f"trades_export_{get_ist_now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        io.StringIO(output.getvalue()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/api/logs")
def get_logs():
    return scan_logs


@app.post("/api/kill-switch")
async def emergency_kill_switch():
    global bot_running
    bot_running = False
    log_scan("SYSTEM", "EMERGENCY KILL SWITCH TRIGGERED. Closing all positions.", "danger")
    await square_off_all("EMERGENCY KILL SWITCH")
    return {"status": "success", "message": "Bot halted and all positions closed."}


@app.post("/api/toggle")
def toggle_bot():
    global bot_running
    bot_running = not bot_running
    state = "STARTED" if bot_running else "STOPPED"
    log_scan("SYSTEM", f"Bot {state} manually.", "info")
    return {"bot_running": bot_running}



@app.post("/api/manual-trade")
async def manual_trade(trade_data: dict):
    symbol = trade_data.get("symbol", "").upper().strip()
    action = trade_data.get("action", "BUY").upper()
    qty = int(trade_data.get("quantity", 1))
    sl_input = trade_data.get("stop_loss")
    target_input = trade_data.get("target")

    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")
    
    inst = client.get_instrument_info(symbol)
    if not inst:
        raise HTTPException(status_code=400, detail=f"Symbol {symbol} not found in instrument map")

    loop = asyncio.get_running_loop()
    quote = await loop.run_in_executor(
        None, functools.partial(client.get_market_quote, inst["instrument_key"])
    )
    if not quote:
        raise HTTPException(status_code=400, detail=f"Failed to fetch market quote for {symbol}")

    entry_price = quote["ltp"]
    
    if sl_input is not None and sl_input != "":
        stop_loss = float(sl_input)
    else:
        stop_loss = round(entry_price * 0.99, 2) if action == "BUY" else round(entry_price * 1.01, 2)
        
    if target_input is not None and target_input != "":
        target_1 = float(target_input)
    else:
        target_1 = round(entry_price * 1.015, 2) if action == "BUY" else round(entry_price * 0.985, 2)

    paper_trading = client.config.get("paper_trading", True)

    if symbol in active_positions:
        raise HTTPException(status_code=400, detail=f"Position already open for {symbol}")

    if risk_manager.is_past_square_off(get_ist_now()):
        raise HTTPException(status_code=400, detail="Past square-off time — no new position may be opened (Section 0 rule 4).")

    # Manual trades are still trades — Section 0 rule: "no exceptions anywhere in the code".
    # The user-supplied quantity is treated as a proposed_qty ceiling that RiskManager can only
    # cap down further, never loosen.
    margin_for_risk, weekly_pnl_for_risk = get_capital_and_weekly_pnl()
    risk_decision = risk_manager.size_and_check(
        symbol=symbol,
        entry_price=entry_price,
        stop_loss=stop_loss,
        capital=margin_for_risk,
        total_pnl_today=get_total_daily_pnl(),
        weekly_pnl=weekly_pnl_for_risk,
        open_positions=active_positions,
        trade_history=trade_history,
        now=get_ist_now(),
        paper_trading=paper_trading,
        proposed_qty=qty,
        skip_window_check=True,  # manual override of the auto-entry window is an intentional feature
        skip_size_cap=client.config.get("enable_max_capacity", False),
    )
    if not risk_decision.allowed:
        jsonl_logger.log_decision("skip", symbol, risk_decision.reason, {"strategy": "Manual-Entry"})
        raise HTTPException(status_code=400, detail=f"RiskManager blocked manual trade: {risk_decision.reason}")
    qty = risk_decision.qty
    jsonl_logger.log_decision("trade", symbol, "RiskManager approved (manual)", {"strategy": "Manual-Entry", "quantity": qty})

    order_id = f"MOCK-MANUAL-{int(datetime.now().timestamp() * 1000)}"
    
    if paper_trading:
        order = {
            "order_id": order_id,
            "symbol": symbol,
            "instrument_key": inst["instrument_key"],
            "transaction_type": action,
            "quantity": qty,
            "price": entry_price,
            "status": "success"
        }
    else:
        try:
            order = await loop.run_in_executor(
                None, functools.partial(
                    client.place_order, symbol, action, qty, "MARKET", 0.0, tag="manual_bot", instrument_key=inst["instrument_key"]
                )
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Order placement failed: {str(e)}")

    fill_price = order.get("price", entry_price)
    
    context = {
        "ema_20": entry_price,
        "vwap": entry_price,
        "rsi": 50.0,
        "atr": abs(entry_price - stop_loss),
        "regime": "trending_up"
    }

    active_positions[symbol] = {
        "symbol": symbol,
        "instrument_key": inst["instrument_key"],
        "is_fno": False,
        "lot_size": 1,
        "contract": "",
        "strategy": "Manual-Entry",
        "direction": "LONG" if action == "BUY" else "SHORT",
        "quantity": qty,
        "entry_price": fill_price,
        "entry_time": get_ist_now().isoformat(),
        "stop_loss": stop_loss,
        "target": target_1,
        "target_2": target_1,
        "t1_hit": False,
        "order_id": order.get("order_id", order_id),
        "current_price": fill_price,
        "pnl": 0.0,
        "atr_at_entry": abs(fill_price - stop_loss),
        "trailing_high": fill_price if action == "BUY" else None,
        "trailing_low": fill_price if action == "SELL" else None,
        "market_context": context,
        "regime": "unknown",
        "htf_trend": "neutral",
        "mae": 0.0,
        "mfe": 0.0,
        "confluence_score": 5,
    }
    
    save_state()
    log_scan(symbol, f"Manually Entered {action} {qty} @ ₹{fill_price:.2f} (SL: ₹{stop_loss}, Target: ₹{target_1})", "success")
    return {"status": "success", "message": f"Manually entered trade for {symbol}", "position": active_positions[symbol]}


@app.post("/api/squareoff")
async def squareoff_endpoint():
    await square_off_all("MANUAL SQUARE-OFF")
    return {"status": "success", "message": "All positions squared off."}


@app.post("/api/close-position/{symbol}")
async def close_position_endpoint(symbol: str):
    global active_positions
    symbol = symbol.upper().strip()
    if symbol not in active_positions:
        raise HTTPException(status_code=404, detail=f"No active position found for {symbol}")
    
    pos = active_positions[symbol]
    paper_trading = client.config.get("paper_trading", True)
    loop = asyncio.get_running_loop()
    try:
        quote = await loop.run_in_executor(
            None, functools.partial(client.get_market_quote, pos["instrument_key"])
        )
        ep = quote["ltp"] if quote else pos["entry_price"]
        if not await execute_exit(symbol, pos, ep, "MANUAL INDIVIDUAL CLOSE", paper_trading):
            raise HTTPException(status_code=409, detail=f"Exit for {symbol} did not complete (duplicate or order failed); position retained.")
        _remove_position(symbol)
        save_state()
        return {"status": "success", "message": f"Position for {symbol} closed."}
    except HTTPException:
        raise
    except Exception as e:
        log_scan(symbol, f"Close position error: {e}", "danger")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analytics")
def get_analytics():
    """Performance metrics for today's trades."""
    today = get_ist_now().date().isoformat()
    today_trades = [t for t in trade_history if t.get("exit_time", "").startswith(today)]
    return {
        "metrics": calculate_metrics(today_trades),
        "by_strategy": analyze_by_strategy(today_trades),
    }


@app.get("/api/equity_curve")
def get_equity_curve(days: int = 30):
    """
    L3: Real-time equity curve endpoint.
    Returns daily P&L data points for charting the bot's performance over time.
    
    Query params:
      ?days=30  — how many calendar days to return (default 30, max 365)
    """
    days = min(max(days, 1), 365)
    cutoff = (get_ist_now() - timedelta(days=days)).date().isoformat()
    
    # Filter trades within the window
    relevant = [t for t in trade_history if t.get("exit_time", "") >= cutoff]
    
    # Build daily buckets
    daily_buckets: dict = {}
    for t in relevant:
        day = t.get("exit_time", "")[:10]
        if not day:
            continue
        if day not in daily_buckets:
            daily_buckets[day] = {"pnl": 0.0, "trades": 0, "wins": 0}
        daily_buckets[day]["pnl"] += t.get("pnl", 0.0)
        daily_buckets[day]["trades"] += 1
        if t.get("pnl", 0.0) > 0:
            daily_buckets[day]["wins"] += 1
    
    # Build cumulative equity curve
    curve = []
    cumulative_pnl = 0.0
    for day in sorted(daily_buckets.keys()):
        d = daily_buckets[day]
        cumulative_pnl += d["pnl"]
        curve.append({
            "date": day,
            "daily_pnl": round(d["pnl"], 2),
            "cumulative_pnl": round(cumulative_pnl, 2),
            "trades": d["trades"],
            "win_rate": round(d["wins"] / d["trades"] * 100, 1) if d["trades"] > 0 else 0.0
        })
    
    # Also include current open positions unrealized PnL
    unrealized = sum(p.get("pnl", 0.0) for p in active_positions.values())
    
    return {
        "equity_curve": curve,
        "total_realized_pnl": round(cumulative_pnl, 2),
        "unrealized_pnl": round(unrealized, 2),
        "total_trades": len(relevant),
        "period_days": days
    }


@app.post("/api/backtest/run")
async def run_custom_backtest(params: dict):
    """
    L4: User-facing real backtesting API.
    Accepts symbol, strategy, from_date, to_date and runs REAL backtesting
    using actual Upstox historical data (not random numbers).
    
    Body:
    {
      "symbol": "RELIANCE",
      "strategy": "VWAPTrendPullback",  // or ORB, Momentum, MeanReversion, TrendFollow, SupportResistance
      "from_date": "2025-01-01",
      "to_date": "2025-06-30",
      "interval": "5minute"  // optional, default 5minute
    }
    """
    symbol = params.get("symbol", "").upper().strip()
    strategy_name = params.get("strategy", "VWAPTrendPullback")
    from_date = params.get("from_date")
    to_date = params.get("to_date")
    interval = params.get("interval", "5minute")
    
    if not symbol:
        raise HTTPException(400, "symbol is required")
    if not from_date or not to_date:
        raise HTTPException(400, "from_date and to_date are required (YYYY-MM-DD format)")
    
    inst = client.get_instrument_info(symbol)
    if not inst:
        raise HTTPException(404, f"Symbol {symbol} not found in instrument map")
    
    try:
        loop = asyncio.get_running_loop()
        candles = await loop.run_in_executor(
            None, functools.partial(
                client.get_historical_candles, inst["instrument_key"], interval, from_date, to_date
            )
        )
        
        if not candles or len(candles) < 35:
            return {
                "error": "Not enough historical data for the requested period",
                "symbol": symbol,
                "candles_fetched": len(candles or []),
                "from_date": from_date,
                "to_date": to_date
            }
        
        cfg = client.config
        slippage_pct = float(cfg.get("backtest_slippage_pct", 0.0005))
        
        # Select the strategy checker function based on strategy name
        strategy_map = {
            "VWAPTrendPullback": _check_vtp_direct,
        }
        
        # For strategies not in the direct map, build a wrapper
        if strategy_name not in strategy_map:
            from strategies import (
                check_orb_strategy, check_vwap_pullback_strategy,
                check_momentum_breakout_strategy, check_mean_reversion_strategy,
                check_trend_following_strategy
            )
            strat_funcs = {
                "ORB": lambda c: check_orb_strategy(c),
                "VWAPPullback": lambda c: check_vwap_pullback_strategy(c),
                "Momentum": lambda c: check_momentum_breakout_strategy(c),
                "MeanReversion": lambda c: check_mean_reversion_strategy(c),
                "TrendFollow": lambda c: check_trend_following_strategy(c),
            }
            strat_fn = strat_funcs.get(strategy_name)
            if not strat_fn:
                raise HTTPException(400, f"Unknown strategy: {strategy_name}. Valid: {list(strat_funcs.keys()) + ['VWAPTrendPullback']}")
            checker = strat_fn
        else:
            checker = strategy_map[strategy_name]
        
        trades, rejected = run_backtest(
            checker, candles, config=cfg,
            max_risk=float(cfg.get("max_risk_per_trade", 500)),
            trailing_mult=float(cfg.get("trailing_atr_multiplier", 1.5)),
            slippage_pct=slippage_pct,
        )
        
        period = f"{from_date} to {to_date}"
        report = generate_backtest_report(trades, symbol, period)
        report["rejected_signals"] = len(rejected)
        report["candles_used"] = len(candles)
        report["strategy"] = strategy_name
        report["interval"] = interval
        report["note"] = "Real backtesting using actual Upstox historical market data"
        return report
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/analytics/report")
def get_session_report():
    """Full session report (also available after auto square-off)."""
    if session_report:
        return session_report
    today = get_ist_now().date().isoformat()
    today_trades = [t for t in trade_history if t.get("exit_time", "").startswith(today)]
    return generate_session_report(today_trades)


@app.get("/api/news/{symbol}")
def get_news_for_symbol(symbol: str):
    """Recent (7-day) news for a watchlist symbol — the same feed the LLM entry gate reasons over."""
    inst = client.get_instrument_info(symbol)
    if not inst:
        raise HTTPException(404, f"Symbol {symbol} not found")
    return client.get_news(inst["instrument_key"], page_size=10)


@app.get("/api/fundamentals/{symbol}")
def get_fundamentals(symbol: str):
    """Full fundamentals for a symbol (profile, ratios, financials, shareholding, corporate
    actions, competitors), fetched in parallel. Any section that fails comes back as null."""
    inst = client.get_instrument_info(symbol)
    if not inst:
        raise HTTPException(404, f"Symbol {symbol} not found")
    isin = str(inst["instrument_key"]).split("|")[-1]
    from concurrent.futures import ThreadPoolExecutor
    tasks = {
        "profile": lambda: client.get_company_profile(isin),
        "key_ratios": lambda: client.get_key_ratios(isin),
        "income_statement": lambda: client.get_income_statement(isin),
        "balance_sheet": lambda: client.get_balance_sheet(isin),
        "cash_flow": lambda: client.get_cash_flow(isin),
        "share_holdings": lambda: client.get_share_holdings(isin),
        "corporate_actions": lambda: client.get_corporate_actions(isin),
        "competitors": lambda: client.get_competitors(inst["instrument_key"]),
    }
    out = {"symbol": symbol, "isin": isin}
    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        futures = {k: ex.submit(fn) for k, fn in tasks.items()}
        for k, f in futures.items():
            try:
                out[k] = f.result(timeout=15)
            except Exception:
                out[k] = None
    return out


@app.get("/api/chart/{symbol}")
def get_chart(symbol: str):
    inst = client.get_instrument_info(symbol)
    if not inst:
        raise HTTPException(404, f"Symbol {symbol} not found")
    try:
        candles = client.get_intraday_candles(inst["instrument_key"], "5minute")
        if not candles:
            # Fallback to historical candles if intraday is empty (e.g. weekend or off-market hours)
            today_ist = get_ist_now()
            from_date = (today_ist - timedelta(days=6)).strftime("%Y-%m-%d")
            to_date = today_ist.strftime("%Y-%m-%d")
            candles = client.get_historical_candles(
                inst["instrument_key"], "5minute",
                from_date, to_date
            )
            if candles:
                # Filter to only keep candles from the most recent trading day
                latest_day = candles[-1]["timestamp"][:10]
                candles = [c for c in candles if c["timestamp"].startswith(latest_day)]
            else:
                return []
        close_prices = [c["close"] for c in candles]
        ema_20 = calculate_ema(close_prices, 20)
        vwap_list = calculate_vwap(candles)
        rsi_14 = calculate_rsi(close_prices, 14)
        atr_14 = calculate_atr(candles, 14)
        result = []
        for idx, c in enumerate(candles):
            dt = datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00"))
            result.append({
                "time": int(dt.timestamp()),
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c["volume"],
                "ema20": ema_20[idx],
                "vwap": vwap_list[idx],
                "rsi": rsi_14[idx],
                "atr": atr_14[idx],
            })
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/trade-chart/{symbol}")
def get_trade_chart(symbol: str, date: str):
    """5-minute candles for one symbol on one trading day — feeds the trade-detail
    modal's chart so a closed trade can be replayed on the candles it happened on."""
    inst = client.get_instrument_info(symbol)
    if not inst:
        raise HTTPException(404, f"Symbol {symbol} not found")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    try:
        if date == get_ist_now().strftime("%Y-%m-%d"):
            candles = client.get_intraday_candles(inst["instrument_key"], "5minute")
        else:
            candles = client.get_historical_candles(inst["instrument_key"], "5minute", date, date)
        return [
            {
                "time": int(datetime.fromisoformat(c["timestamp"].replace("Z", "+00:00")).timestamp()),
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c["volume"],
            }
            for c in candles
        ]
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/broker-positions")
def get_broker_positions():
    """The broker's own net-position book. Live mode only — paper positions exist purely
    inside the bot, so there is no broker-side book to show (available=False, reason=paper).
    None from the client means UNKNOWN (API failure), which is reported distinctly so the
    dashboard never renders an unreachable book as flat."""
    rows = client.get_positions()
    if rows is None:
        reason = "paper" if client.paper_trading else "unavailable"
        return {"available": False, "reason": reason, "positions": []}
    return {"available": True, "reason": None, "positions": rows}


@app.get("/api/backtest/{symbol}")
def backtest_symbol(symbol: str, days: int = 30, slippage_pct: float | None = None):
    """
    Runs VWAPTrendPullback backtest on historical 5-min candles.
    ?days=30  — look back this many calendar days (max 90).
    """
    inst = client.get_instrument_info(symbol)
    if not inst:
        raise HTTPException(404, f"Symbol {symbol} not found")

    days = min(max(days, 1), 90)
    try:
        from datetime import timedelta
        end_dt   = get_ist_now()
        start_dt = end_dt - timedelta(days=days)
        candles  = client.get_historical_candles(
            inst["instrument_key"], "5minute",
            start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"),
        )
        if not candles or len(candles) < 35:
            return {"error": "Not enough historical data", "symbol": symbol, "candles": len(candles or [])}

        cfg = client.config
        if slippage_pct is None:
            slippage_pct = float(cfg.get("backtest_slippage_pct", 0.0005))

        trades, rejected = run_backtest(
            _check_vtp_direct, candles, config=cfg,
            max_risk=float(cfg.get("max_risk_per_trade", 500)),
            trailing_mult=float(cfg.get("trailing_atr_multiplier", 1.5)),
            slippage_pct=slippage_pct,
        )
        period = f"{start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}"
        report = generate_backtest_report(trades, symbol, period)
        report["rejected"] = len(rejected)
        report["candles"]  = len(candles)
        return report
    except Exception as e:
        raise HTTPException(500, str(e))


# ─── API routers (extracted per docs/AUDIT-2026-07-04.md P3-14) ───────────────────────

from routers import history as history_router
from routers import lane_b as lane_b_router
from routers import assistant as assistant_router

history_router.configure(get_now=get_ist_now, get_config=lambda: client.config)
lane_b_router.configure(get_config=lambda: client.config)

app.include_router(history_router.router)
app.include_router(lane_b_router.router)
app.include_router(assistant_router.router)


if __name__ == "__main__":
    generate_self_signed_cert()
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=5000,
        ssl_keyfile="key.pem",
        ssl_certfile="cert.pem",
        # Auto-reload restarts the process on ANY file change — with open positions that
        # means a silent mid-session halt and in-memory state reset. Opt in for dev only:
        #   BOT_DEV=1 python main.py
        reload=os.environ.get("BOT_DEV") == "1",
    )
