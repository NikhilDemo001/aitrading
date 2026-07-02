import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { historyApi } from '../../lib/api/historyApi'
import type { DateRangeState } from './useDateRange'
import './LearningTables.css'

const DIMENSIONS = ['rsi', 'volume_ratio', 'atr_pct', 'time_of_day', 'regime', 'symbol']

export function FeatureAnalytics({ range }: { range: DateRangeState }) {
  const [dimension, setDimension] = useState('rsi')
  const { data } = useQuery({
    queryKey: ['history', 'features', range.start, range.end, dimension],
    queryFn: () => historyApi.getFeatures(range.start, range.end, dimension),
  })
  const rows = data ?? []

  return (
    <Panel
      title="Feature / Condition Analytics"
      padded={false}
      actions={
        <select value={dimension} onChange={(e) => setDimension(e.target.value)}>
          {DIMENSIONS.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
      }
    >
      {rows.length === 0 ? (
        <div className="text-faint" style={{ padding: 16, fontSize: '0.72rem' }}>No feature/condition data for this range yet.</div>
      ) : (
        <table className="mq-feature-table">
          <thead><tr><th>Bucket</th><th>Trades</th><th>Win %</th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>{r.bucket}</td>
                <td className="num">{r.trades}</td>
                <td className="num">{r.win_rate.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  )
}
