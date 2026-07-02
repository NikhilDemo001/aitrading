import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { positionsApi } from '../../lib/api/statusApi'
import './TimeOfDayPanel.css'

// Derived client-side from real trade timestamps (the backend has no dedicated
// time-of-day endpoint) — groups every historical trade by entry hour and computes a
// real win rate per hour, rather than displaying invented figures.
export function TimeOfDayPanel() {
  const { data: trades } = useQuery({
    queryKey: ['trades', 'all'],
    queryFn: positionsApi.getTradesAll,
    staleTime: 60000,
  })

  const buckets = useMemo(() => {
    const byHour = new Map<number, { wins: number; total: number }>()
    for (const t of trades ?? []) {
      const entryTime = t.entry_time
      if (!entryTime) continue
      const hour = new Date(entryTime).getHours()
      if (Number.isNaN(hour)) continue
      const bucket = byHour.get(hour) ?? { wins: 0, total: 0 }
      bucket.total += 1
      if ((t.pnl ?? 0) > 0) bucket.wins += 1
      byHour.set(hour, bucket)
    }
    return [...byHour.entries()]
      .map(([hour, b]) => ({ hour, winRate: (b.wins / b.total) * 100, total: b.total }))
      .sort((a, b) => a.hour - b.hour)
  }, [trades])

  const best = buckets.length ? buckets.reduce((a, b) => (b.winRate > a.winRate ? b : a)) : null
  const worst = buckets.length ? buckets.reduce((a, b) => (b.winRate < a.winRate ? b : a)) : null

  return (
    <Panel title="Time of Day">
      {buckets.length === 0 ? (
        <div className="text-faint mq-tod-empty">Not enough trade history yet to break down by hour.</div>
      ) : (
        <div className="mq-tod-bars">
          {buckets.map((b) => (
            <div key={b.hour} className="mq-tod-row">
              <span className="mq-tod-hour num">{String(b.hour).padStart(2, '0')}:00</span>
              <div className="mq-tod-track">
                <div
                  className={`mq-tod-fill ${b.winRate >= 50 ? 'mq-tod-fill-profit' : 'mq-tod-fill-loss'}`}
                  style={{ width: `${b.winRate}%` }}
                />
              </div>
              <span className="mq-tod-pct num">{b.winRate.toFixed(0)}%</span>
            </div>
          ))}
          {best && worst && (
            <div className="mq-tod-summary text-faint">
              Best {String(best.hour).padStart(2, '0')}:00 ({best.winRate.toFixed(0)}%) · Worst {String(worst.hour).padStart(2, '0')}:00 ({worst.winRate.toFixed(0)}%)
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}
