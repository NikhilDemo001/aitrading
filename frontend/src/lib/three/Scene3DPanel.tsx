import type { ReactNode } from 'react'
import { Canvas } from '@react-three/fiber'
import { Panel } from '../../design-system/Panel'
import { useUiStore } from '../stores/useUiStore'
import { useCanvasVisibility } from './useCanvasVisibility'
import './Scene3DPanel.css'

export function Scene3DPanel({
  title,
  children,
}: {
  title: string
  children: (props: { isVisible: boolean }) => ReactNode
}) {
  const effectsEnabled = useUiStore((s) => s.effectsEnabled)
  const { ref, isVisible } = useCanvasVisibility<HTMLDivElement>()

  return (
    <Panel title={title} padded={false} className="mq-scene-panel">
      <div ref={ref} className="mq-scene-canvas">
        {effectsEnabled ? (
          <Canvas dpr={[1, 2]} camera={{ position: [0, 0, 6], fov: 45 }}>
            {children({ isVisible })}
          </Canvas>
        ) : (
          <div className="mq-scene-disabled text-faint">3D effects disabled in Config.</div>
        )}
      </div>
    </Panel>
  )
}
