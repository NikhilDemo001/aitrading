import { useEffect, useRef } from 'react'
import { gsap } from 'gsap'
import { useUiStore } from './stores/useUiStore'

/**
 * Cursor-following 3D tilt ("antigravity" hover): the card leans toward the pointer with a
 * springy GSAP interpolation and lifts slightly, as if floating free of the page.
 *
 * Ownership note: while active, GSAP owns the element's inline transform (tilt + lift), so
 * CSS :hover transforms on the same element won't apply — keep hover shadows in CSS, motion
 * here. Inactive (effects off / reduced motion / touch), no inline transform is ever written
 * and the element's CSS hover behaviour applies untouched.
 *
 * Perf: transform-only (GPU-composited), quickTo tweens, will-change scoped to hover.
 */
export function useTilt<T extends HTMLElement>(maxDeg = 5, liftPx = 4) {
  const ref = useRef<T | null>(null)
  const effectsEnabled = useUiStore((s) => s.effectsEnabled)

  useEffect(() => {
    const el = ref.current
    if (!el || !effectsEnabled) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    if (window.matchMedia('(pointer: coarse)').matches) return // no cursor on touch

    // Explicit identity baseline: if GSAP instead parsed the computed transform here, it
    // could capture the mq-rise entrance animation mid-flight (e.g. scale 0.985) and bake
    // that into every subsequent tween, leaving the card permanently shrunken after hover.
    gsap.set(el, { transformPerspective: 700, x: 0, y: 0, scale: 1, rotationX: 0, rotationY: 0 })
    const rx = gsap.quickTo(el, 'rotationX', { duration: 0.45, ease: 'power2.out' })
    const ry = gsap.quickTo(el, 'rotationY', { duration: 0.45, ease: 'power2.out' })
    const ty = gsap.quickTo(el, 'y', { duration: 0.45, ease: 'power2.out' })

    const enter = () => {
      el.style.willChange = 'transform'
      ty(-liftPx)
    }
    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect()
      const px = (e.clientX - r.left) / r.width - 0.5 // -0.5 .. 0.5
      const py = (e.clientY - r.top) / r.height - 0.5
      ry(px * 2 * maxDeg)
      rx(-py * 2 * maxDeg)
    }
    const leave = () => {
      rx(0)
      ry(0)
      ty(0)
      el.style.willChange = ''
    }

    el.addEventListener('pointerenter', enter)
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerleave', leave)
    return () => {
      el.removeEventListener('pointerenter', enter)
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerleave', leave)
      gsap.killTweensOf(el)
      gsap.set(el, { clearProps: 'transform' })
      el.style.willChange = ''
    }
  }, [effectsEnabled, maxDeg, liftPx])

  return ref
}
