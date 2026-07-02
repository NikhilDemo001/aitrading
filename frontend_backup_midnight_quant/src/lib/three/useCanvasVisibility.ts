import { useEffect, useRef, useState } from 'react'

// Mirrors static/v3d_core.js's shared-IntersectionObserver + document.hidden gating: one
// observer instance for the whole app (not one per scene), so N mounted 3D panels cost one
// observer, not N. Each scene reads isVisible inside its own useFrame and skips work when
// false — same behavior as the old v3dShouldRender() early-return, expressed idiomatically.
let sharedObserver: IntersectionObserver | null = null
const callbacks = new WeakMap<Element, (visible: boolean) => void>()

function getObserver() {
  if (!sharedObserver && 'IntersectionObserver' in window) {
    sharedObserver = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          callbacks.get(entry.target)?.(entry.isIntersecting)
        }
      },
      { threshold: 0 },
    )
  }
  return sharedObserver
}

export function useCanvasVisibility<T extends Element>() {
  const ref = useRef<T | null>(null)
  const [onScreen, setOnScreen] = useState(true)
  const [tabVisible, setTabVisible] = useState(!document.hidden)

  useEffect(() => {
    const el = ref.current
    const observer = getObserver()
    if (!el || !observer) return
    callbacks.set(el, setOnScreen)
    observer.observe(el)
    return () => {
      observer.unobserve(el)
      callbacks.delete(el)
    }
  }, [])

  useEffect(() => {
    const onVisibilityChange = () => setTabVisible(!document.hidden)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [])

  return { ref, isVisible: onScreen && tabVisible }
}
