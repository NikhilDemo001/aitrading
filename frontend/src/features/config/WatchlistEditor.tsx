import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { useBotStore, EMPTY_WATCHLIST } from '../../lib/stores/useBotStore'
import { settingsApi } from '../../lib/api/settingsApi'
import './WatchlistEditor.css'

export function WatchlistEditor() {
  const watchlist = useBotStore((s) => s.status?.watchlist ?? EMPTY_WATCHLIST)
  const [newSymbol, setNewSymbol] = useState('')

  const mutation = useMutation({
    mutationFn: (next: string[]) => settingsApi.save({ watchlist: next }),
  })

  const addSymbol = () => {
    const symbol = newSymbol.trim().toUpperCase()
    if (!symbol || watchlist.includes(symbol)) return
    mutation.mutate([...watchlist, symbol])
    setNewSymbol('')
  }

  const removeSymbol = (symbol: string) => {
    mutation.mutate(watchlist.filter((s) => s !== symbol))
  }

  return (
    <Panel title={`Watchlist · ${watchlist.length}`}>
      <div className="mq-wle-add">
        <input
          placeholder="Add symbol (e.g. RELIANCE)"
          value={newSymbol}
          onChange={(e) => setNewSymbol(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && addSymbol()}
        />
        <Button variant="primary" onClick={addSymbol} disabled={!newSymbol.trim()}>Add</Button>
      </div>
      <div className="mq-wle-chips">
        {watchlist.map((symbol) => (
          <span key={symbol} className="mq-wle-chip">
            {symbol}
            <button onClick={() => removeSymbol(symbol)} aria-label={`Remove ${symbol}`}>×</button>
          </span>
        ))}
      </div>
    </Panel>
  )
}
