import { create } from 'zustand'
import type { ScannerState } from '../../types/api'

interface ScannerStoreState {
  scanner: ScannerState
  checkingSymbol: { symbol: string; name?: string; status: 'checking' | 'done' } | null
  setScanner: (scanner: ScannerState) => void
  setCheckingProgress: (p: { symbol: string; name?: string; status: 'checking' | 'done' }) => void
}

export const useScannerStore = create<ScannerStoreState>((set) => ({
  scanner: { matrix: [] },
  checkingSymbol: null,
  setScanner: (scanner) => set({ scanner }),
  setCheckingProgress: (checkingSymbol) => set({ checkingSymbol }),
}))
