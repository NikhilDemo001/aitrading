// Types mirror the backend's actual JSON shapes (main.py). Kept intentionally loose
// (many optional/unknown fields) since the backend is not typed and evolves independently
// of this frontend — over-narrowing here would just cause spurious TS errors on fields
// the backend adds/removes.

export interface BotStatus {
  bot_running: boolean
  authenticated: boolean
  paper_trading: boolean
  daily_pnl: number
  open_positions_count: number
  max_open_positions: number
  max_daily_loss: number
  watchlist: string[]
  enable_fno?: boolean
  scanner_last_loop?: string | null
  scanner_last_checked?: string | null
  trade_start_time?: string
  trade_end_time?: string
  square_off_time?: string
  [key: string]: unknown
}

// direction is a plain string: the scan path writes "LONG"/"SHORT", the manual path "BUY"/"SELL".
// Use isLongDirection() from lib/tradeMath to branch on it.
export interface Position {
  symbol: string
  direction: string
  quantity: number
  entry_price: number
  entry_time?: string
  stop_loss: number
  target?: number
  target_2?: number
  t1_hit?: boolean
  current_price?: number
  pnl?: number
  strategy?: string
  confluence_score?: number
  regime?: string
  htf_trend?: string
  mae?: number
  mfe?: number
  atr_at_entry?: number
  trailing_high?: number | null
  trailing_low?: number | null
  order_id?: string
  is_fno?: boolean
  contract?: string
  lot_size?: number
  market_context?: Record<string, unknown>
  is_shadow?: boolean
  [key: string]: unknown
}

export interface Trade {
  symbol: string
  direction: string
  strategy?: string
  entry_price: number
  entry_time: string
  exit_price?: number
  exit_time?: string
  pnl?: number
  pnl_pct?: number
  quantity: number
  /** Backend stores the exit reason as `reason`; some older paths used `exit_reason`. */
  reason?: string
  exit_reason?: string
  stop_loss?: number
  target_1?: number
  target_2?: number
  t1_hit?: boolean | number
  holding_minutes?: number | null
  mae?: number
  mfe?: number
  confluence_score?: number
  regime?: string
  htf_trend?: string
  atr_at_entry?: number
  is_fno?: boolean
  contract?: string
  lot_size?: number
  order_id?: string
  market_context?: Record<string, unknown>
  trigger_level_source?: string | null
  trigger_level_price?: number | null
  trigger_level_score?: number | null
  is_shadow_trade?: boolean
  [key: string]: unknown
}

export interface ScannerRow {
  symbol: string
  name?: string
  ltp?: number
  atr_pct?: number
  rsi?: number
  regime?: string
  strategy?: string
  decision?: string
  at?: string
  time?: string
  status?: string
  ema_9?: number
  ema_20?: number
  vwap?: number
  orb_high?: number
  orb_low?: number
  [key: string]: unknown
}

export interface ScannerState {
  context?: Record<string, unknown>
  matrix: ScannerRow[]
}

export interface ChartCandle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
  ema20?: number
  vwap?: number
  rsi?: number
  atr?: number
}

export interface LogEntry {
  time?: string
  message?: string
  tag?: string
  level?: string
  [key: string]: unknown
}

// ── WebSocket message envelope ──────────────────────────────────────────────
export type WsMessage =
  | { type: 'init'; status: BotStatus; positions: Position[]; trades: Trade[]; logs: LogEntry[]; scanner: ScannerState }
  | { type: 'state_update'; status: BotStatus; positions: Position[]; trades: Trade[]; logs?: LogEntry[] }
  | { type: 'logs'; logs: LogEntry[] }
  | { type: 'scanner'; scanner: ScannerState }
  | { type: 'checking_progress'; symbol: string; name?: string; status: 'checking' | 'done'; time?: string }
  | { type: 'realtime_update'; positions: Position[]; total_daily_pnl?: number; daily_pnl?: number; quotes?: Record<string, number> }
  | TradeEventMessage

export interface TradeEventMessage {
  type: 'trade_event'
  event: 'entry' | 'exit'
  symbol: string
  direction?: string
  quantity?: number
  strategy?: string
  entry_price?: number
  stop_loss?: number
  target?: number
  exit_price?: number
  pnl?: number
  reason?: string
  is_shadow?: boolean
  [key: string]: unknown
}
