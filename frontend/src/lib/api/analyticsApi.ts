import { http } from './http'
import type { ChartCandle } from '../../types/api'

export const analyticsApi = {
  getReport: () => http.get<Record<string, unknown>>('/api/analytics/report'),
  getAnalytics: () => http.get<{ metrics: Record<string, unknown>; by_strategy: Record<string, unknown> }>('/api/analytics'),
  getEquityCurve: (days = 30) => http.get<{ equity_curve: Array<Record<string, unknown>>; total_realized_pnl: number; unrealized_pnl: number; total_trades: number }>(`/api/equity_curve?days=${days}`),
  getChart: (symbol: string) => http.get<ChartCandle[]>(`/api/chart/${symbol}?_t=${Date.now()}`),
  getTradeChart: (symbol: string, date: string) =>
    http.get<ChartCandle[]>(`/api/trade-chart/${symbol}?date=${date}`),
  runBacktest: (body: { symbol: string; strategy: string; from_date: string; to_date: string; interval?: string }) =>
    http.post('/api/backtest/run', body),
  getBacktest: (symbol: string, days = 30, slippagePct = 0.0005) =>
    http.get(`/api/backtest/${symbol}?days=${days}&slippage_pct=${slippagePct}`),
}
