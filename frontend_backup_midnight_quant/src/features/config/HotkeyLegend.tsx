import { Panel } from '../../design-system/Panel'
import './HotkeyLegend.css'

const HOTKEYS: Array<[string, string]> = [
  ['1 – 5', 'Switch tabs'],
  ['Esc', 'Panic square-off (with confirmation)'],
]

export function HotkeyLegend() {
  return (
    <Panel title="Hotkeys">
      <div className="mq-hotkey-list">
        {HOTKEYS.map(([key, desc]) => (
          <div key={key} className="mq-hotkey-row">
            <kbd>{key}</kbd>
            <span>{desc}</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}
