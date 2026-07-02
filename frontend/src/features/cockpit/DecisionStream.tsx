import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Badge, type BadgeTone } from '../../design-system/Badge'
import { systemApi } from '../../lib/api/systemApi'
import './DecisionStream.css'

function decisionTone(type: string): BadgeTone {
  if (/pick|trade|entry|buy|long/i.test(type)) return 'profit'
  if (/skip|reject|halt/i.test(type)) return 'loss'
  return 'neutral'
}

// Surfaces the bot's real reasoning log (why it acted / skipped each cycle) — the
// `/api/decisions` gate stream that was previously invisible in the UI.
export function DecisionStream() {
  const { data } = useQuery({
    queryKey: ['decisions'],
    queryFn: () => systemApi.getDecisions(60),
    refetchInterval: 5000,
  })
  const rows = data ?? []

  return (
    <Panel title={`Decision Stream · ${rows.length}`} padded={false}>
      {rows.length === 0 ? (
        <div className="mq-ds-empty text-faint">No decisions logged yet.</div>
      ) : (
        <div className="mq-ds-list">
          {rows.map((d, i) => (
            <div key={i} className="mq-ds-row">
              <Badge tone={decisionTone(d.type)}>{d.type}</Badge>
              <span className="mq-ds-sym">{d.symbol}</span>
              <span className="mq-ds-reason">{d.reason}</span>
              {d.gate && <span className="mq-ds-gate text-faint">{d.gate}</span>}
              <span className="mq-ds-time num text-faint">{d.time?.slice(11, 19)}</span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}
