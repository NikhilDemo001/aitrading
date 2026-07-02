import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Badge } from '../../design-system/Badge'
import { Button } from '../../design-system/Button'
import { researchApi } from '../../lib/api/researchApi'
import './Marketplace.css'

function statusTone(status: string): 'profit' | 'loss' | 'accent' | 'neutral' {
  if (/approved|paper trading|live/i.test(status)) return 'profit'
  if (/rejected|retired/i.test(status)) return 'loss'
  if (/backtesting|validation|walkforward/i.test(status)) return 'accent'
  return 'neutral'
}

export function Marketplace() {
  const [count, setCount] = useState(5)
  const queryClient = useQueryClient()
  const { data: strategies } = useQuery({ queryKey: ['research', 'strategies'], queryFn: researchApi.getStrategies })

  const discoverMutation = useMutation({
    mutationFn: () => researchApi.discover(count),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['research', 'strategies'] }),
  })

  const sorted = [...(strategies ?? [])].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))

  return (
    <Panel
      title={`Discovered Strategies · ${sorted.length}`}
      padded={false}
      actions={
        <>
          <input type="number" min={1} max={20} value={count} onChange={(e) => setCount(Number(e.target.value))} className="mq-mkt-count" />
          <Button variant="primary" disabled={discoverMutation.isPending} onClick={() => discoverMutation.mutate()}>
            {discoverMutation.isPending ? 'Discovering…' : 'Discover New'}
          </Button>
        </>
      }
    >
      <div className="mq-mkt-grid">
        {sorted.map((s) => (
          <div key={s.id} className="mq-mkt-card">
            <div className="mq-mkt-card-hdr">
              <span className="mq-mkt-name">{s.name}</span>
              <Badge tone={statusTone(s.status)}>{s.status}</Badge>
            </div>
            <div className="mq-mkt-meta">
              <span>Score {s.current_score.toFixed(1)}</span>
              <span>v{s.version}</span>
              <span className="text-faint">{s.created_at}</span>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  )
}
