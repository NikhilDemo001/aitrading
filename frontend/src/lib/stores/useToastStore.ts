import { create } from 'zustand'

// Trade-event notification queue. The backend broadcasts `trade_event` on every
// entry and exit; this store turns them into a small stack of glass toasts.

export type ToastTone = 'accent' | 'profit' | 'loss'

export interface Toast {
  id: number
  tone: ToastTone
  title: string
  body: string
  shadow: boolean
}

const MAX_VISIBLE = 4

interface ToastState {
  toasts: Toast[]
  push: (t: Omit<Toast, 'id'>) => void
  dismiss: (id: number) => void
}

let nextId = 1

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (t) =>
    set((s) => {
      const next = [...s.toasts, { ...t, id: nextId++ }]
      if (next.length > MAX_VISIBLE) next.splice(0, next.length - MAX_VISIBLE)
      return { toasts: next }
    }),
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))
