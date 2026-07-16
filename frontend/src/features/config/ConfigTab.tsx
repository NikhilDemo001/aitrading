import { SettingsForm } from './SettingsForm'
import { WatchlistEditor } from './WatchlistEditor'
import { HotkeyLegend } from './HotkeyLegend'
import './ConfigTab.css'

export function ConfigTab() {
  return (
    <div className="mq-config">
      <div className="mq-config-row">
        <WatchlistEditor />
        <HotkeyLegend />
      </div>
      <SettingsForm />
    </div>
  )
}
