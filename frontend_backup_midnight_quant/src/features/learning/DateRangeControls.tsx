import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { historyApi } from '../../lib/api/historyApi'
import type { DateRangeState, DateRangePreset } from './useDateRange'
import './DateRangeControls.css'

const PRESETS: Array<[string, DateRangePreset]> = [
  ['Today', 'today'], ['Yesterday', 'yesterday'], ['Last 5', 'last5'],
  ['This week', 'week'], ['This month', 'month'], ['Last 30', 'last30'], ['All time', 'all'],
]

export function DateRangeControls({
  range,
  setRange,
  applyPreset,
}: {
  range: DateRangeState
  setRange: (partial: Partial<DateRangeState>) => void
  applyPreset: (preset: DateRangePreset) => void
}) {
  const { data: datesData } = useQuery({ queryKey: ['history', 'dates'], queryFn: historyApi.getDates })

  return (
    <Panel title="Date Range">
      <div className="mq-daterange-presets">
        {PRESETS.map(([label, preset]) => (
          <Button key={label} variant="ghost" onClick={() => applyPreset(preset)}>{label}</Button>
        ))}
      </div>
      <div className="mq-daterange-fields">
        <label>From<input type="date" value={range.start} onChange={(e) => setRange({ start: e.target.value })} /></label>
        <label>To<input type="date" value={range.end} onChange={(e) => setRange({ end: e.target.value })} /></label>
        <label className="mq-daterange-checkbox">
          <input type="checkbox" checked={range.singleDay} onChange={(e) => setRange({ singleDay: e.target.checked })} />
          Single day
        </label>
        <label>
          As-of
          <select value={range.asOf} onChange={(e) => setRange({ asOf: e.target.value })}>
            <option value="">Live</option>
            {(datesData?.dates ?? []).map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
      </div>
      <div className="mq-daterange-summary text-faint">
        {range.start} → {range.end}{range.asOf && ` · as-of ${range.asOf}`}
      </div>
    </Panel>
  )
}
