import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { historyApi } from '../../lib/api/historyApi'
import type { DateRangeState } from './useDateRange'
import { usePanelRange } from './usePanelRange'
import { PanelRangeSelect } from './PanelRangeSelect'
import './LearningTables.css'
import './TradeDrilldown.css'

export function TradeDrilldown({ range: globalRange }: { range: DateRangeState }) {
  const { range, override, setOverride } = usePanelRange(globalRange)
  const [mode, setMode] = useState('')
  const [symbol, setSymbol] = useState('')
  const [strategy, setStrategy] = useState('')

  const { data } = useQuery({
    queryKey: ['history', 'trades', range.start, range.end, mode, symbol, strategy],
    queryFn: () => historyApi.getTrades(range.start, range.end, mode || undefined, symbol || undefined, strategy || undefined),
  })
  const rows = data ?? []

  return (
    <Panel
      title={`Trade Drilldown · ${rows.length}`}
      padded={false}
      actions={
        <>
          <PanelRangeSelect value={override} onChange={setOverride} label="Date filter for Trade Drilldown" />
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="">All modes</option>
            <option value="paper">Paper</option>
            <option value="live">Live</option>
            <option value="combined">Combined</option>
          </select>
          <input placeholder="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} className="mq-drilldown-input" />
          <input placeholder="Strategy" value={strategy} onChange={(e) => setStrategy(e.target.value)} className="mq-drilldown-input" />
        </>
      }
    >
      {rows.length === 0 ? (
        <div className="text-faint" style={{ padding: 16, fontSize: '0.72rem' }}>No trades match this range/filter.</div>
      ) : (
        <table className="mq-trades-drilldown-table">
          <thead><tr><th>Symbol</th><th>Strategy</th><th>Dir</th><th>P&amp;L</th><th>R</th><th>Exit</th></tr></thead>
          <tbody>
            {rows.slice(0, 200).map((t, i) => (
              <tr key={i}>
                <td>{t.symbol}</td>
                <td className="text-faint">{t.strategy ?? '—'}</td>
                <td>{t.direction ?? '—'}</td>
                <td className={`num ${(t.pnl ?? 0) >= 0 ? 'text-profit' : 'text-loss'}`}>{t.pnl?.toFixed(2) ?? '—'}</td>
                <td className="num">{t.r_multiple?.toFixed(2) ?? '—'}</td>
                <td className="text-faint">{t.timestamp_exit ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  )
}
