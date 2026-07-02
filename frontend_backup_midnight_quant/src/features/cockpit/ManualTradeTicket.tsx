import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { statusApi } from '../../lib/api/statusApi'
import { useBotStore, EMPTY_WATCHLIST } from '../../lib/stores/useBotStore'
import './ManualTradeTicket.css'

export function ManualTradeTicket({ symbol }: { symbol: string | null }) {
  const watchlist = useBotStore((s) => s.status?.watchlist ?? EMPTY_WATCHLIST)
  const [selected, setSelected] = useState(symbol ?? '')
  const [action, setAction] = useState<'BUY' | 'SELL'>('BUY')
  const [quantity, setQuantity] = useState(1)
  const [stopLoss, setStopLoss] = useState('')
  const [target, setTarget] = useState('')

  const mutation = useMutation({
    mutationFn: () =>
      statusApi.manualTrade({
        symbol: selected || symbol || '',
        action,
        quantity,
        stop_loss: stopLoss ? Number(stopLoss) : undefined,
        target: target ? Number(target) : undefined,
      }),
  })

  const effectiveSymbol = selected || symbol || ''

  return (
    <Panel title="Manual Trade" className="mq-ticket-panel">
      <div className="mq-ticket-row">
        <select value={effectiveSymbol} onChange={(e) => setSelected(e.target.value)}>
          <option value="" disabled>Select symbol</option>
          {watchlist.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      <div className="mq-ticket-row mq-ticket-actions">
        <Button variant={action === 'BUY' ? 'success' : 'ghost'} onClick={() => setAction('BUY')}>Buy</Button>
        <Button variant={action === 'SELL' ? 'danger' : 'ghost'} onClick={() => setAction('SELL')}>Sell</Button>
      </div>
      <div className="mq-ticket-row mq-ticket-fields">
        <label>Qty<input type="number" min={1} value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} /></label>
        <label>SL<input type="number" value={stopLoss} onChange={(e) => setStopLoss(e.target.value)} placeholder="opt" /></label>
        <label>Target<input type="number" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="opt" /></label>
      </div>
      <Button
        variant="primary"
        disabled={!effectiveSymbol || mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending ? 'Submitting…' : `${action} ${effectiveSymbol || '—'}`}
      </Button>
      {mutation.isError && <div className="mq-ticket-error">{(mutation.error as Error).message}</div>}
      {mutation.isSuccess && <div className="mq-ticket-success">Order submitted.</div>}
    </Panel>
  )
}
