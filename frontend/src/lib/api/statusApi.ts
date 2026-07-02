import { http, cacheBust } from './http'
import type { BotStatus, Position, Trade, ScannerState, LogEntry } from '../../types/api'

export const statusApi = {
  getStatus: () => http.get<BotStatus>(cacheBust('/api/status')),
  toggle: () => http.post<{ ok?: boolean }>('/api/toggle'),
  killSwitch: () => http.post<{ ok?: boolean }>('/api/kill-switch'),
  squareOff: () => http.post<{ ok?: boolean }>('/api/squareoff'),
  closePosition: (symbol: string) => http.post<{ ok?: boolean }>(`/api/close-position/${symbol}`),
  manualTrade: (body: { symbol: string; action: 'BUY' | 'SELL'; quantity: number; stop_loss?: number; target?: number }) =>
    http.post('/api/manual-trade', body),
}

export const positionsApi = {
  getPositions: () => http.get<Position[]>(cacheBust('/api/positions')),
  getTradesToday: () => http.get<Trade[]>(cacheBust('/api/trades')),
  getTradesAll: () => http.get<Trade[]>('/api/trades/all'),
}

export const scannerApi = {
  getScanner: () => http.get<ScannerState>(cacheBust('/api/scanner')),
  getLogs: () => http.get<LogEntry[]>(cacheBust('/api/logs')),
}
