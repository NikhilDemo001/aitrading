import { create } from 'zustand'
import type { BotStatus } from '../../types/api'

// Stable reference so selectors like `s.status?.watchlist ?? EMPTY_WATCHLIST` don't hand
// useSyncExternalStore a freshly-allocated array every render (which reads as "changed"
// on every render and causes an infinite update loop).
export const EMPTY_WATCHLIST: string[] = []

interface BotStoreState {
  status: BotStatus | null
  connected: boolean
  setStatus: (status: BotStatus) => void
  setConnected: (connected: boolean) => void
}

export const useBotStore = create<BotStoreState>((set) => ({
  status: null,
  connected: false,
  setStatus: (status) => set({ status }),
  setConnected: (connected) => set({ connected }),
}))
