import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { positionsApi } from '../../lib/api/statusApi'
import { TradeDetailModal } from './TradeDetailModal'
import type { Trade } from '../../types/api'
import { rMultiple, pnlPct, exitReason } from '../../lib/tradeMath'
import './HistoricalTradesTable.css'

type SortKey = 'symbol' | 'strategy' | 'reason' | 'pnl' | 'pct' | 'r'
type SortDir = 'asc' | 'desc'

export function HistoricalTradesTable() {
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['trades-all'],
    queryFn: positionsApi.getTradesAll,
    enabled: false, // click-to-fetch
  })
  const [selected, setSelected] = useState<Trade | null>(null)
  const [q, setQ] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('pnl')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const rows = useMemo(() => {
    let out = (data ?? []).map((t) => ({ t, r: rMultiple(t), pct: pnlPct(t), reason: exitReason(t) }))
    const needle = q.trim().toLowerCase()
    if (needle) {
      out = out.filter(({ t, reason }) =>
        [t.symbol, t.strategy, reason].some((v) => (v ?? '').toLowerCase().includes(needle)),
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
      if (typeof av === 'number' || typeof bv === 'number') cmp = ((av as number) ?? -Infinity) - ((bv as number) ?? -Infinity)
      else cmp = String(av ?? '').localeCompare(String(bv ?? ''))
      return sortDir === 'asc' ? cmp : -cmp
    })
    return out
  }, [data, q, sortKey, sortDir])

  const toggleSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(k); setSortDir('desc') }
  }
  const arrow = (k: SortKey) => (k === sortKey ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '')

  // Sortable headers as real <button>s inside <th>: clickable <th> alone is invisible to
  // keyboard and screen-reader users. aria-sort announces the current order.
  const sortableTh = (k: SortKey, label: string) => (
    <th aria-sort={k === sortKey ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" className="mq-hist-sort-btn" onClick={() => toggleSort(k)}>
        {label}
        {arrow(k)}
      </button>
    </th>
  )

  return (
    <Panel
      title="Historical Trades"
      padded={false}
      actions={
        <>
          <input
            className="mq-hist-search"
            placeholder="Search symbol / strategy / reason"
            aria-label="Search trades by symbol, strategy or exit reason"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <Button variant="primary" onClick={() => refetch()} disabled={isFetching}>{isFetching ? 'Loading…' : data ? 'Reload' : 'Load All'}</Button>
          <a className="mq-btn mq-btn-ghost" href="/api/trades/export" download>Export CSV</a>
        </>
      }
    >
      {isError ? (
        <div className="mq-hist-empty text-loss">Failed to load trades.</div>
      ) : isLoading ? (
        <div className="mq-hist-empty text-faint">Loading…</div>
      ) : !data ? (
        <div className="mq-hist-empty text-faint">Click “Load All” to fetch the full trade history.</div>
      ) : rows.length === 0 ? (
        <div className="mq-hist-empty text-faint">No matching trades.</div>
      ) : (
        <table className="mq-hist-table">
          <thead>
            <tr>
              {sortableTh('symbol', 'Symbol')}
              {sortableTh('strategy', 'Strategy')}
              {sortableTh('reason', 'Exit Reason')}
              {sortableTh('pnl', 'P&L')}
              {sortableTh('pct', 'P&L %')}
              {sortableTh('r', 'R')}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ t, r, pct, reason }, i) => {
              const pnl = t.pnl ?? 0
              return (
                <tr
                  key={i}
                  className="mq-hist-row"
                  tabIndex={0}
                  role="button"
                  aria-label={`Open details for ${t.symbol} trade`}
                  onClick={() => setSelected(t)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(t) } }}
                >
                  <td className="mq-hist-sym">{t.symbol}</td>
                  <td>{t.strategy ?? '—'}</td>
                  <td className="text-dim">{reason ?? '—'}</td>
                  <td className={`num ${pnl >= 0 ? 'text-profit' : 'text-loss'}`}>{pnl >= 0 ? '+' : ''}₹{pnl.toFixed(2)}</td>
                  <td className={`num ${(pct ?? 0) >= 0 ? 'text-profit' : 'text-loss'}`}>{pct != null ? `${pct.toFixed(2)}%` : '—'}</td>
                  <td className={`num ${(r ?? 0) >= 0 ? 'text-profit' : 'text-loss'}`}>{r != null ? `${r.toFixed(2)}R` : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {selected && <TradeDetailModal trade={selected} onClose={() => setSelected(null)} />}
    </Panel>
  )
}
