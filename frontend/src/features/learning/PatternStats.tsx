import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { historyApi } from '../../lib/api/historyApi'
import type { DateRangeState } from './useDateRange'
import './LearningTables.css'

export function PatternStats({ range }: { range: DateRangeState }) {
  const { data } = useQuery({
    queryKey: ['history', 'patterns', range.start, range.end],
    queryFn: () => historyApi.getPatterns(range.start, range.end),
  })
  const rows = data ?? []

  return (
    <Panel title="Candlestick Pattern Learning" padded={false}>
      {rows.length === 0 ? (
        <div className="text-faint" style={{ padding: 16, fontSize: '0.72rem' }}>No candlestick patterns recorded on trades in this range.</div>
      ) : (
        <table className="mq-pattern-table">
          <thead><tr><th>Pattern</th><th>Date</th><th>Occurrences</th><th>Win %</th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>{r.pattern}</td>
                <td className="text-faint">{r.snapshot_date}</td>
                <td className="num">{r.occurrences}</td>
                <td className="num">{r.win_rate.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  )
}
