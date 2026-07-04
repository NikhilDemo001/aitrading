import { useEffect, useRef } from 'react'
import { gsap } from 'gsap'
import { useUiStore } from '../lib/stores/useUiStore'
import './AmbientBackdrop.css'

/**
 * Ambient depth layer behind the whole app: two soft neon glow orbs that drift on slow CSS
 * keyframes and parallax gently against the pointer (background moves slower than content,
 * selling the spatial depth). Transform-only, pointer-events: none, sits under everything.
 * With effects off or prefers-reduced-motion, the orbs render static — depth without motion.
 */
export function AmbientBackdrop() {
  const effectsEnabled = useUiStore((s) => s.effectsEnabled)
  const layerRef = useRef<HTMLDivElement | null>(null)

  const reduced =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const animate = effectsEnabled && !reduced

  useEffect(() => {
    const layer = layerRef.current
    if (!layer || !animate) return
    if (window.matchMedia('(pointer: coarse)').matches) return

    const tx = gsap.quickTo(layer, 'x', { duration: 1.2, ease: 'power2.out' })
    const ty = gsap.quickTo(layer, 'y', { duration: 1.2, ease: 'power2.out' })
    const move = (e: PointerEvent) => {
      // Background drifts opposite the pointer at ~1.5% of viewport — slow-layer parallax.
      tx((0.5 - e.clientX / window.innerWidth) * 30)
      ty((0.5 - e.clientY / window.innerHeight) * 30)
    }
    window.addEventListener('pointermove', move, { passive: true })
    return () => {
      window.removeEventListener('pointermove', move)
      gsap.killTweensOf(layer)
      gsap.set(layer, { clearProps: 'transform' })
    }
  }, [animate])

  return (
    <div className="mq-ambient" aria-hidden="true">
      <div ref={layerRef} className="mq-ambient-layer" style={{ willChange: animate ? 'transform' : undefined }}>
        <div className={`mq-ambient-orb mq-ambient-orb-cyan ${animate ? 'mq-ambient-drift' : ''}`} />
        <div className={`mq-ambient-orb mq-ambient-orb-magenta ${animate ? 'mq-ambient-drift-alt' : ''}`} />
      </div>
    </div>
  )
}
