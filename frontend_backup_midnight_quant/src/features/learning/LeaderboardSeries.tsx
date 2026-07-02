import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { historyApi } from '../../lib/api/historyApi'
import type { DateRangeState } from './useDateRange'

export function LeaderboardSeries({ range }: { range: DateRangeState }) {
  const { data } = useQuery({
    queryKey: ['history', 'leaderboard-series', range.start, range.end],
    queryFn: () => historyApi.getLeaderboardSeries(range.start, range.end),
  })

  const rows = (data ?? []).filter((d) => Object.keys(d.leaderboard).length > 0)

  return (
    <Panel title="Strategy Leaderboard — per-day snapshots">
      {rows.length === 0 ? (
        <p className="text-faint">No per-day leaderboard snapshots in this range yet.</p>
      ) : (
        <div className="mq-lbseries-list">
          {rows.map((d) => (
            <div key={d.date}>
              <strong>{d.date}</strong>
              <span className="text-faint"> — {Object.keys(d.leaderboard).length} strategies ranked</span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}
