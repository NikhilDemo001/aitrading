import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { historyApi } from '../../lib/api/historyApi'
import './RebuildEodControl.css'

export function RebuildEodControl() {
  const [date, setDate] = useState('')
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: () => historyApi.rebuild(date || undefined),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['history'] }),
  })

  return (
    <Panel title="Rebuild EOD Learning">
      <p className="text-faint" style={{ marginTop: 0, fontSize: '0.72rem' }}>
        Idempotent — re-runs leaderboard rebuild + history snapshots for a chosen date (default today). Never trades or self-modifies code.
      </p>
      <div className="mq-rebuild-row">
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        <Button variant="primary" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
          {mutation.isPending ? 'Rebuilding…' : 'Re-run EOD'}
        </Button>
      </div>
      {mutation.data && <div className="text-profit" style={{ fontSize: '0.72rem', marginTop: 8 }}>Rebuilt {mutation.data.date} — {mutation.data.trades_counted} trades counted.</div>}
    </Panel>
  )
}
