import { http } from './http'

export interface KpiDailyRow {
  snapshot_date: string
  trades: number
  wins: number
  losses: number
  win_rate: number
  expectancy: number
  profit_factor: number | null
  gross_pnl: number
  net_pnl: number
  max_drawdown: number
  avg_holding_minutes: number | null
  best_trade: number
  worst_trade: number
  capital_start: number
  equity: number
}

export interface HistorySummary {
  trades: number
  wins: number
  losses: number
  win_rate: number
  avg_r: number
  expectancy: number
  gross_pnl: number
  net_pnl: number
  profit_factor: number | null
  max_drawdown: number
  best_trade: number
  worst_trade: number
  avg_holding_minutes: number | null
}

export interface PatternStatRow {
  pattern: string
  snapshot_date: string
  occurrences: number
  win_rate: number
  [key: string]: unknown
}

export interface FeatureStatRow {
  dimension: string
  bucket: string
  trades: number
  win_rate: number
  [key: string]: unknown
}

export interface LeaderboardSnapshot {
  as_of: string | null
  leaderboard: Record<string, unknown>
  resolved_from: string | null
}

export interface LeaderboardSeriesPoint {
  date: string
  leaderboard: Record<string, unknown>
}

export interface HistoryTrade {
  symbol: string
  strategy?: string
  direction?: string
  pnl?: number
  r_multiple?: number
  timestamp_entry?: string
  timestamp_exit?: string
  paper_trading?: boolean
  lesson?: string
  tags?: string[]
  [key: string]: unknown
}

export interface CompareResult {
  a: { range: [string | null, string | null]; metrics: HistorySummary }
  b: { range: [string | null, string | null]; metrics: HistorySummary }
  delta: Record<string, number>
}

function qs(params: Record<string, string | undefined>) {
  const entries = Object.entries(params).filter(([, v]) => v != null && v !== '')
  if (entries.length === 0) return ''
  return '?' + new URLSearchParams(entries as [string, string][]).toString()
}

export const historyApi = {
  getDates: () => http.get<{ dates: string[] }>('/api/history/dates'),
  getKpi: (start?: string, end?: string) => http.get<KpiDailyRow[]>(`/api/history/kpi${qs({ start, end })}`),
  getPatterns: (start?: string, end?: string) => http.get<PatternStatRow[]>(`/api/history/patterns${qs({ start, end })}`),
  getFeatures: (start?: string, end?: string, dimension?: string) =>
    http.get<FeatureStatRow[]>(`/api/history/features${qs({ start, end, dimension })}`),
  getLeaderboard: (asOf?: string) => http.get<LeaderboardSnapshot>(`/api/history/leaderboard${qs({ as_of: asOf })}`),
  getLeaderboardSeries: (start?: string, end?: string) =>
    http.get<LeaderboardSeriesPoint[]>(`/api/history/leaderboard/series${qs({ start, end })}`),
  getTrades: (start?: string, end?: string, mode?: string, symbol?: string, strategy?: string) =>
    http.get<HistoryTrade[]>(`/api/history/trades${qs({ start, end, mode, symbol, strategy })}`),
  getSummary: (start?: string, end?: string, mode?: string, symbol?: string, strategy?: string) =>
    http.get<HistorySummary>(`/api/history/summary${qs({ start, end, mode, symbol, strategy })}`),
  compare: (aStart?: string, aEnd?: string, bStart?: string, bEnd?: string, mode?: string, symbol?: string, strategy?: string) =>
    http.get<CompareResult>(`/api/history/compare${qs({ a_start: aStart, a_end: aEnd, b_start: bStart, b_end: bEnd, mode, symbol, strategy })}`),
  rebuild: (date?: string) => http.post<{ status: string; date: string; trades_counted: number }>('/api/history/rebuild', date ? { date } : {}),
}
