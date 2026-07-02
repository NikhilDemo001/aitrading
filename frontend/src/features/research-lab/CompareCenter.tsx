import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { researchApi } from '../../lib/api/researchApi'
import './CompareCenter.css'

function StrategyPicker({ label, strategies, value, onChange }: {
  label: string
  strategies: Array<{ id: string; name: string }>
  value: string
  onChange: (v: string) => void
}) {
  return (
    <label className="mq-compare-picker">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Select strategy</option>
        {strategies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select>
    </label>
  )
}

const METRIC_ROWS: Array<[string, (bt?: { win_rate: number; profit_factor: number; sharpe_ratio: number; max_drawdown: number; expectancy: number }) => string]> = [
  ['Win Rate', (bt) => bt ? `${bt.win_rate.toFixed(1)}%` : '—'],
  ['Profit Factor', (bt) => bt ? bt.profit_factor.toFixed(2) : '—'],
  ['Sharpe', (bt) => bt ? bt.sharpe_ratio.toFixed(2) : '—'],
  ['Max Drawdown', (bt) => bt ? `₹${bt.max_drawdown.toFixed(2)}` : '—'],
  ['Expectancy', (bt) => bt ? `₹${bt.expectancy.toFixed(2)}` : '—'],
]

export function CompareCenter() {
  const [idA, setIdA] = useState('')
  const [idB, setIdB] = useState('')
  const { data: strategies } = useQuery({ queryKey: ['research', 'strategies'], queryFn: researchApi.getStrategies })
  const { data: detailA } = useQuery({ queryKey: ['research', 'strategy', idA], queryFn: () => researchApi.getStrategy(idA), enabled: !!idA })
  const { data: detailB } = useQuery({ queryKey: ['research', 'strategy', idB], queryFn: () => researchApi.getStrategy(idB), enabled: !!idB })

  return (
    <Panel title="Compare Center">
      <div className="mq-compare-pickers">
        <StrategyPicker label="Strategy A" strategies={strategies ?? []} value={idA} onChange={setIdA} />
        <StrategyPicker label="Strategy B" strategies={strategies ?? []} value={idB} onChange={setIdB} />
      </div>
      {(idA || idB) && (
        <table className="mq-compare-table">
          <thead>
            <tr><th>Metric</th><th>{detailA?.name ?? 'A'}</th><th>{detailB?.name ?? 'B'}</th></tr>
          </thead>
          <tbody>
            {METRIC_ROWS.map(([label, fmt]) => (
              <tr key={label}>
                <td className="text-faint">{label}</td>
                <td className="num">{fmt(detailA?.active_version?.backtest)}</td>
                <td className="num">{fmt(detailB?.active_version?.backtest)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  )
}
