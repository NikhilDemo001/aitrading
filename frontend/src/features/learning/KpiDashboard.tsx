import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { StatCard } from '../../design-system/StatCard'
import { historyApi } from '../../lib/api/historyApi'
import type { DateRangeState } from './useDateRange'
import { usePanelRange } from './usePanelRange'
import { PanelRangeSelect } from './PanelRangeSelect'
import './KpiDashboard.css'

export function KpiDashboard({ range: globalRange }: { range: DateRangeState }) {
  const { range, override, setOverride } = usePanelRange(globalRange)
  const effectiveStart = range.singleDay ? range.end : range.start
  const { data: summary } = useQuery({
    queryKey: ['history', 'summary', effectiveStart, range.end],
    queryFn: () => historyApi.getSummary(effectiveStart, range.end),
  })
  const { data: kpiRows } = useQuery({
    queryKey: ['history', 'kpi', effectiveStart, range.end],
    queryFn: () => historyApi.getKpi(effectiveStart, range.end),
  })

  return (
    <div className="mq-kpi-dash">
      <div className="mq-kpi-dash-cards mq-stagger">
        <StatCard label="Trades" value={summary?.trades ?? 0} />
        <StatCard label="Win Rate" value={`${(summary?.win_rate ?? 0).toFixed(1)}%`} />
        <StatCard label="Expectancy" value={`₹${(summary?.expectancy ?? 0).toFixed(2)}`} tone={(summary?.expectancy ?? 0) >= 0 ? 'profit' : 'loss'} />
        <StatCard label="Net P&L" value={`₹${(summary?.net_pnl ?? 0).toFixed(2)}`} tone={(summary?.net_pnl ?? 0) >= 0 ? 'profit' : 'loss'} />
        <StatCard label="Max Drawdown" value={`₹${(summary?.max_drawdown ?? 0).toFixed(2)}`} tone="loss" />
        <StatCard label="Avg R" value={(summary?.avg_r ?? 0).toFixed(2)} />
      </div>
      <Panel
        title="Learning over time — daily KPI trend"
        padded={false}
        actions={<PanelRangeSelect value={override} onChange={setOverride} label="Date filter for the KPI trend and stats above" />}
      >
        {(kpiRows ?? []).length === 0 ? (
          <div className="mq-kpi-empty text-faint">No daily snapshots in this range yet — snapshots are written at end-of-day.</div>
        ) : (
          <table className="mq-kpi-table">
            <thead>
              <tr><th>Date</th><th>Trades</th><th>Win %</th><th>Net P&amp;L</th><th>Equity</th></tr>
            </thead>
            <tbody>
              {kpiRows!.map((row) => (
                <tr key={row.snapshot_date}>
                  <td>{row.snapshot_date}</td>
                  <td className="num">{row.trades}</td>
                  <td className="num">{row.win_rate.toFixed(1)}</td>
                  <td className={`num ${row.net_pnl >= 0 ? 'text-profit' : 'text-loss'}`}>{row.net_pnl.toFixed(2)}</td>
                  <td className="num">{row.equity.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  )
}
