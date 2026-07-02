import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Badge } from '../../design-system/Badge'
import { Button } from '../../design-system/Button'
import { useScannerStore } from '../../lib/stores/useScannerStore'
import { systemApi } from '../../lib/api/systemApi'
import type { ScannerRow } from '../../types/api'
import './ScannerMatrix.css'

function statusTone(status?: string, decision?: string): 'profit' | 'loss' | 'warn' | 'neutral' {
  const s = (status ?? '').toLowerCase()
  if (s === 'entered') return 'profit'
  if (s === 'filtered' || s === 'skipped') return 'loss'
  if (s === 'no_signal' || s === 'no_data' || s === 'error') return 'warn'
  if (s === 'in_position') return 'neutral'
  // fallback to decision text
  if (decision && /enter|buy|long|sell|short|trade/i.test(decision)) return 'profit'
  if (decision && /reject|skip|filter|no/i.test(decision)) return 'loss'
  return 'neutral'
}

// Frontend-derived confluence: how many real emitted indicators the LTP is on the bullish
// side of. All inputs are real (Task 1 backend snapshot); nothing is faked.
function confluenceScore(row: ScannerRow): { score: number; total: number; parts: { label: string; on: boolean | null }[] } {
  const ltp = row.ltp
  const parts: { label: string; on: boolean | null }[] = [
    { label: 'EMA9', on: ltp != null && row.ema_9 != null ? ltp >= row.ema_9 : null },
    { label: 'EMA20', on: ltp != null && row.ema_20 != null ? ltp >= row.ema_20 : null },
    { label: 'VWAP', on: ltp != null && row.vwap != null ? ltp >= row.vwap : null },
    { label: 'ORB', on: ltp != null && row.orb_high != null ? ltp >= row.orb_high : (ltp != null && row.orb_low != null ? ltp <= row.orb_low : null) },
  ]
  const known = parts.filter((p) => p.on !== null)
  const score = known.filter((p) => p.on === true).length
  return { score, total: known.length, parts }
}

export function ScannerMatrix() {
  const matrix = useScannerStore((s) => s.scanner.matrix)
  const context = useScannerStore((s) => s.scanner.context) as Record<string, unknown> | undefined
  const checking = useScannerStore((s) => s.checkingSymbol)
  const [view, setView] = useState<'table' | 'heat'>('table')

  const { data: decisions } = useQuery({
    queryKey: ['decisions', 'scanner'],
    queryFn: () => systemApi.getDecisions(200),
    refetchInterval: 5000,
  })
  // Latest decision gate keyed by symbol, for the "why it skipped" tooltip.
  const gateBySymbol = new Map<string, string>()
  for (const d of decisions ?? []) {
    if (d.symbol && !gateBySymbol.has(d.symbol)) gateBySymbol.set(d.symbol, d.gate || d.reason || '')
  }

  const vixActive = Boolean(context?.vix_filter_active)
  const vix = context?.india_vix as number | undefined

  const tooltipFor = (row: ScannerRow) => {
    const gate = gateBySymbol.get(row.symbol)
    return gate ? `${row.decision ?? ''}\nGate: ${gate}` : (row.decision ?? '')
  }

  return (
    <Panel
      title="Scanner · Confluence Matrix"
      padded={false}
      actions={
        <>
          <Badge tone={vixActive ? 'warn' : 'neutral'}>VIX {vix != null ? vix.toFixed(1) : '—'}{vixActive ? ' ⚠' : ''}</Badge>
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
              <th>Symbol</th><th>LTP</th><th>EMA9</th><th>EMA20</th><th>VWAP</th><th>ORB</th><th>ATR%</th><th>Conf.</th><th>Decision</th><th>At</th>
            </tr>
          </thead>
          <tbody>
            {matrix.map((row) => {
              const c = confluenceScore(row)
              const cell = (v: number | undefined, on: boolean | null) =>
                v == null ? <span className="text-faint">—</span> : <span className={on ? 'text-profit' : 'text-loss'}>{v.toFixed(2)}</span>
              return (
                <tr key={row.symbol} title={tooltipFor(row)} className="mq-scanner-row">
                  <td className="mq-scanner-sym">{row.symbol}</td>
                  <td className="num">{row.ltp?.toFixed(2) ?? '—'}</td>
                  <td className="num">{cell(row.ema_9, row.ltp != null && row.ema_9 != null ? row.ltp >= row.ema_9 : null)}</td>
                  <td className="num">{cell(row.ema_20, row.ltp != null && row.ema_20 != null ? row.ltp >= row.ema_20 : null)}</td>
                  <td className="num">{cell(row.vwap, row.ltp != null && row.vwap != null ? row.ltp >= row.vwap : null)}</td>
                  <td className="num">{row.orb_high != null || row.orb_low != null ? `${row.orb_low?.toFixed(0) ?? '—'}/${row.orb_high?.toFixed(0) ?? '—'}` : '—'}</td>
                  <td className="num">{row.atr_pct?.toFixed(2) ?? '—'}</td>
                  <td><span className={`mq-conf mq-conf-${c.score >= 3 ? 'hi' : c.score >= 2 ? 'mid' : 'lo'}`}>{c.total ? `${c.score}/${c.total}` : '—'}</span></td>
                  <td><Badge tone={statusTone(row.status, row.decision)}>{row.decision ?? '—'}</Badge></td>
                  <td className="text-faint">{row.time ?? row.at ?? '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : (
        <div className="mq-scanner-heat">
          {matrix.map((row) => {
            const c = confluenceScore(row)
            const tone = statusTone(row.status, row.decision)
            return (
              <div key={row.symbol} className={`mq-heat-tile mq-heat-${tone}`} title={tooltipFor(row)} style={{ '--conf': c.total ? c.score / c.total : 0 } as React.CSSProperties}>
                <span className="mq-heat-sym">{row.symbol}</span>
                <span className="mq-heat-conf num">{c.total ? `${c.score}/${c.total}` : '—'}</span>
                <span className="mq-heat-atr num">{row.atr_pct?.toFixed(1) ?? '—'}%</span>
              </div>
            )
          })}
        </div>
      )}
    </Panel>
  )
}
