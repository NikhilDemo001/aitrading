import { create } from 'zustand'
import type { Position, Trade } from '../../types/api'

interface PositionsStoreState {
  positions: Position[]
  trades: Trade[]
  totalDailyPnl: number | null
  quotes: Record<string, number>
  setPositions: (positions: Position[]) => void
  setTrades: (trades: Trade[]) => void
  applyRealtimeUpdate: (positions: Position[], totalDailyPnl?: number, quotes?: Record<string, number>) => void
}

export const usePositionsStore = create<PositionsStoreState>((set) => ({
  positions: [],
  trades: [],
  totalDailyPnl: null,
  quotes: {},
  setPositions: (positions) => set({ positions }),
  setTrades: (trades) => set({ trades }),
  applyRealtimeUpdate: (positions, totalDailyPnl, quotes) =>
    set((s) => ({
      positions,
      totalDailyPnl: totalDailyPnl ?? s.totalDailyPnl,
      quotes: quotes ?? s.quotes,
    })),
}))
