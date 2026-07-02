import { SettingsForm } from './SettingsForm'
import { WatchlistEditor } from './WatchlistEditor'
import { EffectsToggle } from './EffectsToggle'
import { HotkeyLegend } from './HotkeyLegend'
import './ConfigTab.css'

export function ConfigTab() {
  return (
    <div className="mq-config">
      <div className="mq-config-row">
        <WatchlistEditor />
        <EffectsToggle />
        <HotkeyLegend />
      </div>
      <SettingsForm />
    </div>
  )
}
