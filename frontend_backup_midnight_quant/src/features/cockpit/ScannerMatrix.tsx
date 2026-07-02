import { useState } from 'react'
import { Panel } from '../../design-system/Panel'
import { Badge } from '../../design-system/Badge'
import { Button } from '../../design-system/Button'
import { useScannerStore } from '../../lib/stores/useScannerStore'
import './ScannerMatrix.css'

function decisionTone(decision?: string): 'profit' | 'loss' | 'neutral' {
  if (!decision) return 'neutral'
  if (/buy|long|sell|short|trade/i.test(decision)) return 'profit'
  if (/reject|skip|no/i.test(decision)) return 'loss'
  return 'neutral'
}

export function ScannerMatrix() {
  const matrix = useScannerStore((s) => s.scanner.matrix)
  const checking = useScannerStore((s) => s.checkingSymbol)
  const [view, setView] = useState<'table' | 'heat'>('table')

  return (
    <Panel
      title="Scanner Matrix"
      padded={false}
      actions={
        <>
          {checking?.status === 'checking' && <Badge tone="accent">Scanning {checking.symbol}</Badge>}
          <Button variant={view === 'table' ? 'primary' : 'ghost'} onClick={() => setView('table')}>Table</Button>
          <Button variant={view === 'heat' ? 'primary' : 'ghost'} onClick={() => setView('heat')}>Heat Grid</Button>
        </>
      }
    >
      {matrix.length === 0 ? (
        <div className="mq-scanner-empty text-faint">No scan data yet.</div>
      ) : view === 'table' ? (
        <table className="mq-scanner-table">
          <thead>
            <tr>
              <th>Symbol</th><th>LTP</th><th>ATR%</th><th>RSI</th><th>Regime</th><th>Strategy</th><th>Decision</th><th>At</th>
            </tr>
          </thead>
          <tbody>
            {matrix.map((row) => (
              <tr key={row.symbol}>
                <td className="mq-scanner-sym">{row.symbol}</td>
                <td className="num">{row.ltp?.toFixed(2) ?? '—'}</td>
                <td className="num">{row.atr_pct?.toFixed(2) ?? '—'}</td>
                <td className="num">{row.rsi?.toFixed(1) ?? '—'}</td>
                <td>{row.regime ?? '—'}</td>
                <td>{row.strategy ?? '—'}</td>
                <td><Badge tone={decisionTone(row.decision)}>{row.decision ?? '—'}</Badge></td>
                <td className="text-faint">{row.at ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="mq-scanner-heat">
          {matrix.map((row) => (
            <div key={row.symbol} className={`mq-heat-tile mq-heat-${decisionTone(row.decision)}`}>
              <span className="mq-heat-sym">{row.symbol}</span>
              <span className="mq-heat-atr num">{row.atr_pct?.toFixed(1) ?? '—'}%</span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}
