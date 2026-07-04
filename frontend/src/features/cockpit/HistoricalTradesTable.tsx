import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { positionsApi } from '../../lib/api/statusApi'
import type { Trade } from '../../types/api'
import './HistoricalTradesTable.css'

type SortKey = 'symbol' | 'strategy' | 'exit_reason' | 'pnl' | 'pnl_pct' | 'r'
type SortDir = 'asc' | 'desc'

function rMultiple(t: Trade): number | null {
  const { entry_price: entry, exit_price: exit, stop_loss: stop, direction } = t
  if (entry == null || exit == null || stop == null) return null
  const risk = Math.abs(entry - stop)
  if (risk === 0) return null
  const dir = (direction ?? '').toUpperCase()
  const raw = dir === 'SELL' || dir === 'SHORT' ? entry - exit : exit - entry
  return raw / risk
}

export function HistoricalTradesTable() {
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['trades-all'],
    queryFn: positionsApi.getTradesAll,
    enabled: false, // click-to-fetch
  })
  const [q, setQ] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('pnl')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const rows = useMemo(() => {
    let out = (data ?? []).map((t) => ({ ...t, _r: rMultiple(t) }))
    const needle = q.trim().toLowerCase()
    if (needle) {
      out = out.filter((t) =>
        [t.symbol, t.strategy, t.exit_reason].some((v) => (v ?? '').toLowerCase().includes(needle)),
      )
    }
    out.sort((a, b) => {
      const av = sortKey === 'r' ? (a._r ?? -Infinity) : (a[sortKey] as number | string | undefined)
      const bv = sortKey === 'r' ? (b._r ?? -Infinity) : (b[sortKey] as number | string | undefined)
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
              {sortableTh('exit_reason', 'Exit Reason')}
              {sortableTh('pnl', 'P&L')}
              {sortableTh('pnl_pct', 'P&L %')}
              {sortableTh('r', 'R')}
            </tr>
          </thead>
          <tbody>
            {rows.map((t, i) => {
              const pnl = t.pnl ?? 0
              return (
                <tr key={i}>
                  <td className="mq-hist-sym">{t.symbol}</td>
                  <td>{t.strategy ?? '—'}</td>
                  <td className="text-dim">{t.exit_reason ?? '—'}</td>
                  <td className={`num ${pnl >= 0 ? 'text-profit' : 'text-loss'}`}>{pnl >= 0 ? '+' : ''}₹{pnl.toFixed(2)}</td>
                  <td className={`num ${(t.pnl_pct ?? 0) >= 0 ? 'text-profit' : 'text-loss'}`}>{t.pnl_pct != null ? `${t.pnl_pct.toFixed(2)}%` : '—'}</td>
                  <td className={`num ${(t._r ?? 0) >= 0 ? 'text-profit' : 'text-loss'}`}>{t._r != null ? `${t._r.toFixed(2)}R` : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </Panel>
  )
}
