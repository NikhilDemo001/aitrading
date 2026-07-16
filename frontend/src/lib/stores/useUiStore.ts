import { create } from 'zustand'

export type TabId =
  | 'cockpit' | 'trades' | 'analytics' | 'config' | 'learning' | 'news' | 'fundamentals' | 'assistant'

interface UiStoreState {
  activeTab: TabId
  effectsEnabled: boolean
  setActiveTab: (tab: TabId) => void
  setEffectsEnabled: (on: boolean) => void
}

const STORAGE_KEY = 'mq_effects_enabled'

export const useUiStore = create<UiStoreState>((set) => ({
  activeTab: 'cockpit',
  effectsEnabled: localStorage.getItem(STORAGE_KEY) !== 'false',
  setActiveTab: (activeTab) => set({ activeTab }),
  setEffectsEnabled: (effectsEnabled) => {
    localStorage.setItem(STORAGE_KEY, String(effectsEnabled))
    set({ effectsEnabled })
  },
}))
