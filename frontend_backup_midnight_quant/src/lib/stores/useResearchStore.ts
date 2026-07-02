import { create } from 'zustand'

interface ResearchStoreState {
  status: unknown
  progress: unknown
  setStatus: (status: unknown) => void
  setProgress: (progress: unknown) => void
}

export const useResearchStore = create<ResearchStoreState>((set) => ({
  status: null,
  progress: null,
  setStatus: (status) => set({ status }),
  setProgress: (progress) => set({ progress }),
}))
