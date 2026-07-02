import { useMemo, useState } from 'react'
import { Panel } from '../../design-system/Panel'
import { useBotStore, EMPTY_WATCHLIST } from '../../lib/stores/useBotStore'
import { useScannerStore } from '../../lib/stores/useScannerStore'
import './WatchlistRail.css'

export function WatchlistRail({
  selected,
  onSelect,
}: {
  selected: string | null
  onSelect: (symbol: string) => void
}) {
  const [query, setQuery] = useState('')
  const watchlist = useBotStore((s) => s.status?.watchlist ?? EMPTY_WATCHLIST)
  const matrix = useScannerStore((s) => s.scanner.matrix)

  const quoteBySymbol = useMemo(() => {
    const map = new Map<string, number | undefined>()
    for (const row of matrix) map.set(row.symbol, row.ltp)
    return map
  }, [matrix])

  const filtered = watchlist.filter((s) => s.toLowerCase().includes(query.toLowerCase()))

  return (
    <Panel title={`Watchlist · ${watchlist.length}`} padded={false} className="mq-watchlist-panel">
      <div className="mq-watchlist-search">
        <input
          placeholder="Filter watchlist..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="mq-watchlist-list">
        {filtered.length === 0 && <div className="mq-watchlist-empty text-faint">No symbols</div>}
        {filtered.map((symbol) => (
          <button
            key={symbol}
            className={`mq-watchlist-row ${selected === symbol ? 'active' : ''}`}
            onClick={() => onSelect(symbol)}
          >
            <span className="mq-wl-sym">{symbol}</span>
            <span className="mq-wl-price num">{quoteBySymbol.get(symbol) != null ? quoteBySymbol.get(symbol)!.toFixed(2) : '—'}</span>
          </button>
        ))}
      </div>
    </Panel>
  )
}
