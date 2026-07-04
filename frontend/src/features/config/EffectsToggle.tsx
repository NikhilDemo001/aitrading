import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { useUiStore } from '../../lib/stores/useUiStore'

export function EffectsToggle() {
  const effectsEnabled = useUiStore((s) => s.effectsEnabled)
  const setEffectsEnabled = useUiStore((s) => s.setEffectsEnabled)

  return (
    <Panel title="3D & Motion Effects">
      <p className="text-faint" style={{ marginTop: 0, fontSize: '0.74rem' }}>
        Toggles the Three.js scenes (Analytics tab), the ambient glow backdrop, and the
        cursor-tilt on cards. Disabling saves GPU/CPU on slower devices.
      </p>
      <Button variant={effectsEnabled ? 'primary' : 'ghost'} onClick={() => setEffectsEnabled(!effectsEnabled)}>
        {effectsEnabled ? 'Effects: On' : 'Effects: Off'}
      </Button>
    </Panel>
  )
}
