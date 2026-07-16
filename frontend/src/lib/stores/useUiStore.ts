import { create } from 'zustand'

export type TabId =
  | 'cockpit' | 'trades' | 'analytics' | 'config' | 'learning' | 'news' | 'fundamentals'
  | 'assistant' | 'ai-usage'

interface UiStoreState {
  activeTab: TabId
  setActiveTab: (tab: TabId) => void
}

export const useUiStore = create<UiStoreState>((set) => ({
  activeTab: 'cockpit',
  setActiveTab: (activeTab) => set({ activeTab }),
}))
