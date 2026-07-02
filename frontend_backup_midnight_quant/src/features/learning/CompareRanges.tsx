import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { historyApi } from '../../lib/api/historyApi'
import './CompareRanges.css'

const METRIC_LABELS: Record<string, string> = {
  trades: 'Trades', win_rate: 'Win Rate %', expectancy: 'Expectancy ₹', net_pnl: 'Net P&L ₹', max_drawdown: 'Max Drawdown ₹', avg_r: 'Avg R',
}

export function CompareRanges() {
  const [aStart, setAStart] = useState('')
  const [aEnd, setAEnd] = useState('')
  const [bStart, setBStart] = useState('')
  const [bEnd, setBEnd] = useState('')

  const mutation = useMutation({
    mutationFn: () => historyApi.compare(aStart, aEnd, bStart, bEnd),
  })

  return (
    <Panel title="Compare two ranges">
      <div className="mq-compare-ranges-inputs">
        <span>A</span>
        <input type="date" value={aStart} onChange={(e) => setAStart(e.target.value)} />
        <span>–</span>
        <input type="date" value={aEnd} onChange={(e) => setAEnd(e.target.value)} />
        <span>B</span>
        <input type="date" value={bStart} onChange={(e) => setBStart(e.target.value)} />
        <span>–</span>
        <input type="date" value={bEnd} onChange={(e) => setBEnd(e.target.value)} />
        <Button variant="primary" disabled={!aStart || !aEnd || !bStart || !bEnd || mutation.isPending} onClick={() => mutation.mutate()}>
          Compare
        </Button>
      </div>
      {mutation.data && (
        <table className="mq-compare-ranges-table">
          <thead><tr><th>Metric</th><th>A</th><th>B</th><th>Δ</th></tr></thead>
          <tbody>
            {Object.entries(METRIC_LABELS).map(([key, label]) => {
              const av = (mutation.data!.a.metrics as unknown as Record<string, unknown>)[key]
              const bv = (mutation.data!.b.metrics as unknown as Record<string, unknown>)[key]
              const delta = mutation.data!.delta[key]
              return (
                <tr key={key}>
                  <td className="text-faint">{label}</td>
                  <td className="num">{typeof av === 'number' ? av.toFixed(2) : '—'}</td>
                  <td className="num">{typeof bv === 'number' ? bv.toFixed(2) : '—'}</td>
                  <td className={`num ${delta > 0 ? 'text-profit' : delta < 0 ? 'text-loss' : ''}`}>
                    {delta != null ? (delta > 0 ? '+' : '') + delta.toFixed(2) : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </Panel>
  )
}
