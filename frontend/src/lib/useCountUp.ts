import { useEffect, useRef, useState } from 'react'

// Tween a displayed number toward its target so P&L changes read as movement,
// not teleportation. Respects prefers-reduced-motion (jumps instantly).

export function useCountUp(target: number, durationMs = 600): number {
  const [display, setDisplay] = useState(target)
  const fromRef = useRef(target)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      fromRef.current = target
      setDisplay(target)
      return
    }
    const from = fromRef.current
    if (from === target) return
    const t0 = performance.now()
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / durationMs)
      const eased = 1 - (1 - k) ** 3 // easeOutCubic
      const value = from + (target - from) * eased
      setDisplay(value)
      if (k < 1) {
        rafRef.current = requestAnimationFrame(step)
      } else {
        fromRef.current = target
      }
    }
    rafRef.current = requestAnimationFrame(step)
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
      fromRef.current = target
    }
  }, [target, durationMs])

  return display
}
