import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { analyticsApi } from '../../lib/api/analyticsApi'
import './StrategyBreakdown.css'

interface StrategyStats {
  trades?: number
  win_rate?: number
  total_pnl?: number
  profit_factor?: number
}

export function StrategyBreakdown() {
  const { data } = useQuery({
    queryKey: ['analytics', 'by_strategy'],
    queryFn: analyticsApi.getAnalytics,
    refetchInterval: 15000,
  })
  const byStrategy = (data?.by_strategy ?? {}) as Record<string, StrategyStats>
  const entries = Object.entries(byStrategy)

  return (
    <Panel title="Strategy Breakdown" padded={false}>
      {entries.length === 0 ? (
        <div className="mq-strategy-empty text-faint">No strategy data yet — trade activity will populate this.</div>
      ) : (
        <table className="mq-strategy-table">
          <thead>
            <tr><th>Strategy</th><th>Trades</th><th>Win %</th><th>P&amp;L</th><th>PF</th></tr>
          </thead>
          <tbody>
            {entries.map(([name, s]) => (
              <tr key={name}>
                <td className="mq-strategy-name">{name}</td>
                <td className="num">{s.trades ?? '—'}</td>
                <td className="num">{s.win_rate?.toFixed(1) ?? '—'}</td>
                <td className={`num ${(s.total_pnl ?? 0) >= 0 ? 'text-profit' : 'text-loss'}`}>{s.total_pnl?.toFixed(2) ?? '—'}</td>
                <td className="num">{s.profit_factor?.toFixed(2) ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  )
}
