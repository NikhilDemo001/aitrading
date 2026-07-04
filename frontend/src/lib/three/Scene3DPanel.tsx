import { useMemo } from 'react'
import type { ReactNode } from 'react'
import { Canvas } from '@react-three/fiber'
import { Panel } from '../../design-system/Panel'
import { useUiStore } from '../stores/useUiStore'
import { useCanvasVisibility } from './useCanvasVisibility'
import './Scene3DPanel.css'

// Detected once per session: mounting a <Canvas> without WebGL support otherwise fails
// with a blank panel (or throws) instead of degrading gracefully.
let webglSupport: boolean | null = null
function supportsWebGL(): boolean {
  if (webglSupport !== null) return webglSupport
  try {
    const c = document.createElement('canvas')
    webglSupport = Boolean(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    webglSupport = false
  }
  return webglSupport
}

export function Scene3DPanel({
  title,
  children,
}: {
  title: string
  children: (props: { isVisible: boolean }) => ReactNode
}) {
  const effectsEnabled = useUiStore((s) => s.effectsEnabled)
  const { ref, isVisible } = useCanvasVisibility<HTMLDivElement>()
  const webgl = useMemo(supportsWebGL, [])
  // Skill-check "High DPR on mobile": cap render resolution on coarse-pointer devices.
  const isCoarse = useMemo(() => window.matchMedia('(pointer: coarse)').matches, [])

  return (
    <Panel title={title} padded={false} className="mq-scene-panel">
      <div ref={ref} className="mq-scene-canvas">
        {!webgl ? (
          <div className="mq-scene-disabled text-faint">3D unavailable (WebGL not supported on this device).</div>
        ) : effectsEnabled ? (
          <Canvas
            dpr={isCoarse ? 1 : [1, 2]}
            camera={{ position: [0, 0, 6], fov: 45 }}
            // The scenes' own useFrame guards only skip their animation math — the render
            // loop itself must stop when the panel is offscreen or the browser tab is
            // hidden, or the GPU redraws an identical frame at 60fps forever.
            frameloop={isVisible ? 'always' : 'never'}
            performance={{ min: 0.5 }}
          >
            {children({ isVisible })}
          </Canvas>
        ) : (
          <div className="mq-scene-disabled text-faint">3D effects disabled in Config.</div>
        )}
      </div>
    </Panel>
  )
}
