import { useCallback, useEffect, useRef } from 'react'
import { useToastStore, type Toast } from '../lib/stores/useToastStore'
import './ToastLayer.css'

const AUTO_DISMISS_MS = 7000

function ToastCard({ toast }: { toast: Toast }) {
  const dismiss = useToastStore((s) => s.dismiss)
  const timerRef = useRef<number | null>(null)

  const disarm = useCallback(() => {
    if (timerRef.current != null) window.clearTimeout(timerRef.current)
    timerRef.current = null
  }, [])
  const arm = useCallback(() => {
    disarm()
    timerRef.current = window.setTimeout(() => dismiss(toast.id), AUTO_DISMISS_MS)
  }, [disarm, dismiss, toast.id])

  // Auto-dismiss clock; hovering the toast pauses it.
  useEffect(() => {
    arm()
    return disarm
  }, [arm, disarm])

  return (
    <div
      className={`mq-toast mq-toast-${toast.tone} ${toast.shadow ? 'mq-toast-shadow' : ''}`}
      onMouseEnter={disarm}
      onMouseLeave={arm}
    >
      <span className={`led ${toast.tone === 'profit' ? 'led-green' : toast.tone === 'loss' ? 'led-magenta' : 'led-cyan'}`} />
      <div className="mq-toast-text">
        <div className="mq-toast-title">
          {toast.title}
          {toast.shadow && <span className="mq-toast-tag">SHADOW</span>}
        </div>
        <div className="mq-toast-body num">{toast.body}</div>
      </div>
      <button type="button" className="mq-toast-close" aria-label="Dismiss notification" onClick={() => dismiss(toast.id)}>
        ✕
      </button>
    </div>
  )
}

export function ToastLayer() {
  const toasts = useToastStore((s) => s.toasts)
  if (toasts.length === 0) return null
  return (
    <div className="mq-toast-layer" role="status" aria-live="polite">
      {toasts.map((t) => (
        <ToastCard key={t.id} toast={t} />
      ))}
    </div>
  )
}
