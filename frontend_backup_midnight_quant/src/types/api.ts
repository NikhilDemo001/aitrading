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
  [key: string]: unknown
}

export interface Position {
  symbol: string
  direction: 'BUY' | 'SELL'
  quantity: number
  entry_price: number
  stop_loss: number
  target?: number
  current_price?: number
  pnl?: number
  strategy?: string
  confluence_score?: number
  regime?: string
  htf_trend?: string
  mae?: number
  mfe?: number
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
  exit_reason?: string
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
  | { type: 'init'; status: BotStatus; positions: Position[]; trades: Trade[]; logs: LogEntry[]; scanner: ScannerState; research_status?: unknown }
  | { type: 'state_update'; status: BotStatus; positions: Position[]; trades: Trade[]; logs?: LogEntry[]; research_status?: unknown }
  | { type: 'logs'; logs: LogEntry[] }
  | { type: 'scanner'; scanner: ScannerState }
  | { type: 'checking_progress'; symbol: string; name?: string; status: 'checking' | 'done'; time?: string }
  | { type: 'realtime_update'; positions: Position[]; total_daily_pnl?: number; daily_pnl?: number; quotes?: Record<string, number> }
  | { type: 'research_progress'; [key: string]: unknown }
  | { type: 'trade_event'; [key: string]: unknown }
