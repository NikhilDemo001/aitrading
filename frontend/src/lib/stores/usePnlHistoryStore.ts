import { create } from 'zustand'

// Session-local history of the day's running P&L, fed by the live WS stream
// (realtime_update / state_update). In-memory only: a page reload starts the
// spark fresh, which is honest — the stream is what we actually observed.

export interface PnlPoint {
  t: number // epoch ms
  v: number // running daily P&L at that moment
}

const MAX_POINTS = 1200 // ~2 h at one point every 6 s; plenty for a session spark

interface PnlHistoryState {
  points: PnlPoint[]
  push: (v: number) => void
}

export const usePnlHistoryStore = create<PnlHistoryState>((set) => ({
  points: [],
  push: (v) =>
    set((s) => {
      const last = s.points[s.points.length - 1]
      if (last && last.v === v) return s // only record actual movement
      const next = [...s.points, { t: Date.now(), v }]
      if (next.length > MAX_POINTS) next.splice(0, next.length - MAX_POINTS)
      return { points: next }
    }),
}))
