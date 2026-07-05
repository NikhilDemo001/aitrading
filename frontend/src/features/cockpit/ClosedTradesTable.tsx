import { useMemo, useState } from 'react'
import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { usePositionsStore } from '../../lib/stores/usePositionsStore'
import { TradeDetailModal } from './TradeDetailModal'
import type { Trade } from '../../types/api'
import { isLongDirection, rMultiple, pnlPct, exitReason, formatTime, formatINR } from '../../lib/tradeMath'
import './ClosedTradesTable.css'

// The day's verdict in one strip. Shadow trades are counterfactual simulations —
// they never touch capital, so they are excluded from every stat here.
function DaySummary({ trades }: { trades: Trade[] }) {
  const real = trades.filter((t) => !t.is_shadow_trade)
  if (real.length === 0) return null
  const net = real.reduce((s, t) => s + (t.pnl ?? 0), 0)
  const wins = real.filter((t) => (t.pnl ?? 0) >= 0)
  const losses = real.filter((t) => (t.pnl ?? 0) < 0)
  const grossWin = wins.reduce((s, t) => s + (t.pnl ?? 0), 0)
  const grossLoss = Math.abs(losses.reduce((s, t) => s + (t.pnl ?? 0), 0))
  const pf = grossLoss > 0 ? grossWin / grossLoss : null
  const rs = real.map((t) => rMultiple(t)).filter((r): r is number => r != null)
  const avgR = rs.length > 0 ? rs.reduce((s, r) => s + r, 0) / rs.length : null
  const pnls = real.map((t) => t.pnl ?? 0)
  const best = Math.max(...pnls)
  const worst = Math.min(...pnls)

  const stat = (label: string, value: string, tone?: 'profit' | 'loss') => (
    <span className="mq-trades-day-stat">
      <span className="mq-trades-day-label">{label}</span>
      <span className={`num ${tone ? `text-${tone}` : ''}`}>{value}</span>
    </span>
  )

  return (
    <div className="mq-trades-day">
      {stat('Net', formatINR(net, { sign: true }), net >= 0 ? 'profit' : 'loss')}
      {stat('W–L', `${wins.length}–${losses.length}`)}
      {stat('Win rate', `${((wins.length / real.length) * 100).toFixed(0)}%`)}
      {stat('Profit factor', pf != null ? pf.toFixed(2) : grossWin > 0 ? '∞' : '—')}
      {stat('Avg R', avgR != null ? `${avgR.toFixed(2)}R` : '—')}
      {stat('Best', formatINR(best, { sign: true }), 'profit')}
      {stat('Worst', formatINR(worst, { sign: true }), worst < 0 ? 'loss' : 'profit')}
    </div>
  )
}

type SortKey = 'symbol' | 'strategy' | 'direction' | 'quantity' | 'entry_price' | 'exit_price' | 'pnl' | 'pct' | 'r' | 'exit_time' | 'reason'
type SortDir = 'asc' | 'desc'

// Field order for the CSV header; any keys not listed follow alphabetically. The export
// serializes the FULL trade objects (every backend field), not just the visible columns.
const CSV_PREFERRED_ORDER = [
  'symbol', 'direction', 'strategy', 'quantity', 'entry_price', 'entry_time',
  'exit_price', 'exit_time', 'pnl', 'reason', 'stop_loss', 'holding_minutes',
]

function csvCell(v: unknown): string {
  if (v == null) return ''
  const s = typeof v === 'object' ? JSON.stringify(v) : String(v)
  return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s
}

function downloadTodayCsv(trades: Trade[]) {
  const keys = new Set<string>()
  for (const t of trades) Object.keys(t).forEach((k) => keys.add(k))
  const ordered = [
    ...CSV_PREFERRED_ORDER.filter((k) => keys.has(k)),
    ...[...keys].filter((k) => !CSV_PREFERRED_ORDER.includes(k)).sort(),
  ]
  const lines = [
    ordered.join(','),
    ...trades.map((t) => ordered.map((k) => csvCell(t[k])).join(',')),
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `trades_today_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export function ClosedTradesTable() {
  const trades = usePositionsStore((s) => s.trades)
  const [selected, setSelected] = useState<Trade | null>(null)
  const [q, setQ] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('exit_time')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const rows = useMemo(() => {
    let out = trades.map((t) => ({ t, r: rMultiple(t), pct: pnlPct(t), reason: exitReason(t) }))
    const needle = q.trim().toLowerCase()
    if (needle) {
      out = out.filter(({ t, reason }) =>
        [t.symbol, t.strategy, t.direction, reason].some((v) => (v ?? '').toLowerCase().includes(needle)),
      )
    }
    const val = (row: (typeof out)[number]): number | string | undefined => {
      switch (sortKey) {
        case 'r': return row.r ?? undefined
        case 'pct': return row.pct ?? undefined
        case 'reason': return row.reason ?? undefined
        default: return row.t[sortKey] as number | string | undefined
      }
    }
    out.sort((a, b) => {
      const av = val(a)
      const bv = val(b)
      let cmp: number
      if (typeof av === 'number' || typeof bv === 'number') {
        cmp = ((av as number) ?? -Infinity) - ((bv as number) ?? -Infinity)
      } else {
        cmp = String(av ?? '').localeCompare(String(bv ?? ''))
      }
      return sortDir === 'asc' ? cmp : -cmp
    })
    return out
  }, [trades, q, sortKey, sortDir])

  const toggleSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(k); setSortDir('desc') }
  }
  const arrow = (k: SortKey) => (k === sortKey ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '')

  const sortableTh = (k: SortKey, label: string) => (
    <th aria-sort={k === sortKey ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" className="mq-trades-sort-btn" onClick={() => toggleSort(k)}>
        {label}
        {arrow(k)}
      </button>
    </th>
  )

  return (
    <Panel
      title={`Closed Trades — Today · ${trades.length}`}
      padded={false}
      actions={
        trades.length > 0 ? (
          <>
            <input
              className="mq-hist-search"
              placeholder="Filter symbol / strategy / reason"
              aria-label="Filter today's trades by symbol, strategy, direction or exit reason"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <Button variant="ghost" onClick={() => downloadTodayCsv(trades)}>Export CSV</Button>
          </>
        ) : undefined
      }
    >
      {trades.length === 0 ? (
        <div className="mq-trades-empty text-faint">
          No trades closed today. Fills appear here the moment the bot books them.
        </div>
      ) : rows.length === 0 ? (
        <div className="mq-trades-empty text-faint">No matching trades — clear the filter to see all of today's fills.</div>
      ) : (
        <table className="mq-trades-table">
          <thead>
            <tr>
              {sortableTh('symbol', 'Symbol')}
              {sortableTh('strategy', 'Strategy')}
              {sortableTh('direction', 'Dir')}
              {sortableTh('quantity', 'Qty')}
              {sortableTh('entry_price', 'Entry')}
              {sortableTh('exit_price', 'Exit')}
              {sortableTh('pnl', 'P&L')}
              {sortableTh('pct', 'P&L %')}
              {sortableTh('r', 'R')}
              {sortableTh('exit_time', 'Exit time')}
              {sortableTh('reason', 'Reason')}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ t, r, pct, reason }, i) => {
              const pnl = t.pnl ?? 0
              return (
                <tr
                  key={i}
                  className={`mq-trades-row ${pnl >= 0 ? 'mq-trades-row-win' : 'mq-trades-row-loss'} ${
                    t.is_shadow_trade ? 'mq-trades-row-shadow' : ''
                  }`}
                  tabIndex={0}
                  role="button"
                  aria-label={`Open details for ${t.symbol} trade`}
                  title={t.is_shadow_trade ? 'Shadow trade — simulated, no capital engaged' : undefined}
                  onClick={() => setSelected(t)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(t) } }}
                >
                  <td className="mq-trades-sym">{t.symbol}{t.is_shadow_trade ? <span className="mq-trades-shadow-tag">S</span> : null}</td>
                  <td>{t.strategy ?? '—'}</td>
                  <td className={isLongDirection(t.direction) ? 'text-profit' : 'text-loss'}>{t.direction}</td>
                  <td className="num">{t.quantity}</td>
                  <td className="num">{t.entry_price?.toFixed(2)}</td>
                  <td className="num">{t.exit_price?.toFixed(2) ?? '—'}</td>
                  <td className={`num ${pnl >= 0 ? 'text-profit' : 'text-loss'}`}>{pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}</td>
                  <td className={`num ${(pct ?? 0) >= 0 ? 'text-profit' : 'text-loss'}`}>{pct != null ? `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%` : '—'}</td>
                  <td className={`num ${(r ?? 0) >= 0 ? 'text-profit' : 'text-loss'}`}>{r != null ? `${r.toFixed(2)}R` : '—'}</td>
                  <td className="text-faint">{formatTime(t.exit_time)}</td>
                  <td className="text-faint">{reason ?? '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {trades.length > 0 && <DaySummary trades={trades} />}
      {selected && <TradeDetailModal trade={selected} onClose={() => setSelected(null)} />}
    </Panel>
  )
}
