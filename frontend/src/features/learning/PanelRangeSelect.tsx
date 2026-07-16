import type { PanelPreset } from './usePanelRange'
import './PanelRangeSelect.css'

const OPTIONS: Array<[PanelPreset, string]> = [
  ['global', 'Global range'],
  ['today', 'Today'],
  ['yesterday', 'Yesterday'],
  ['last5', 'Last 5 days'],
  ['week', 'This week'],
  ['last30', 'Last 30 days'],
  ['all', 'All time'],
]

/** Date filter for a single panel. "Global range" follows the tab's Date Range control; any
 *  other choice pins just this panel and marks it so the divergence is never a surprise. */
export function PanelRangeSelect({
  value,
  onChange,
  label,
}: {
  value: PanelPreset
  onChange: (preset: PanelPreset) => void
  label: string
}) {
  const pinned = value !== 'global'
  return (
    <select
      className={`mq-panel-range ${pinned ? 'mq-panel-range-pinned' : ''}`}
      value={value}
      onChange={(e) => onChange(e.target.value as PanelPreset)}
      aria-label={label}
      title={pinned ? 'Pinned to its own dates — the tab range does not apply here' : 'Following the tab date range'}
    >
      {OPTIONS.map(([v, l]) => (
        <option key={v} value={v}>{l}</option>
      ))}
    </select>
  )
}
