import { create } from 'zustand'
import type { LogEntry } from '../../types/api'

interface LogsStoreState {
  logs: LogEntry[]
  setLogs: (logs: LogEntry[]) => void
  appendLogs: (logs: LogEntry[]) => void
}

const MAX_LOGS = 500

export const useLogsStore = create<LogsStoreState>((set) => ({
  logs: [],
  setLogs: (logs) => set({ logs }),
  appendLogs: (logs) =>
    set((s) => ({ logs: [...logs, ...s.logs].slice(0, MAX_LOGS) })),
}))
