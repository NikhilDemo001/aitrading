import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { systemApi, type DecisionEntry } from '../../lib/api/systemApi'
import './GateBreakdown.css'

// Which gate actually stopped this entry. The explicit `gate` field wins when the backend set
// one; otherwise the reason's prefix identifies it ("liquidity: thin book", "net_rr 1.05 < 1.10").
function gateOf(d: DecisionEntry): string {
  if (d.gate) return d.gate.replaceAll('_', ' ')
  const r = (d.reason ?? '').toLowerCase()
  if (r.startsWith('liquidity')) return 'liquidity'
  if (r.startsWith('net_rr')) return 'net R:R'
  if (r.startsWith('llm_gate_error')) return 'LLM gate error'
  if (r.startsWith('llm_gate')) return 'LLM gate'
  if (r.startsWith('circuit')) return 'circuit'
  if (r.includes('confluence')) return 'confluence'
  if (r.includes('consecutive loss')) return 'loss halt'
  if (r.includes('risk') || r.includes('capacity') || r.includes('quantity')) return 'risk manager'
  const head = (d.reason ?? '').split(':')[0].trim()
  return head ? head.slice(0, 28) : 'other'
}

/** Answers the operator's most common question — "why isn't it trading?" — by aggregating the
 *  skip decisions into the handful of gates actually doing the blocking. */
export function GateBreakdown() {
  const { data } = useQuery({
    queryKey: ['decisions', 'gates'],
    queryFn: () => systemApi.getDecisions(200),
    refetchInterval: 10000,
  })

  const { rows, total } = useMemo(() => {
    const skips = (data ?? []).filter((d) => /skip|reject/i.test(d.type))
    const counts = new Map<string, number>()
    for (const d of skips) {
      const g = gateOf(d)
      counts.set(g, (counts.get(g) ?? 0) + 1)
    }
    const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1])
    return { rows: sorted, total: skips.length }
  }, [data])

  return (
    <Panel title={`Why no trades — blocks · ${total}`} padded={false}>
      {rows.length === 0 ? (
        <div className="mq-gate-empty text-faint">
          Nothing is blocking entries right now — no skips in the recent decision log.
        </div>
      ) : (
        <div className="mq-gate-list">
          {rows.map(([gate, count]) => {
            const pct = (count / total) * 100
            return (
              <div key={gate} className="mq-gate-row">
                <span className="mq-gate-name">{gate}</span>
                <span className="mq-gate-bar" aria-hidden="true">
                  <span className="mq-gate-fill" style={{ width: `${pct}%` }} />
                </span>
                <span className="mq-gate-count num text-faint">{count}</span>
                <span className="mq-gate-pct num">{pct.toFixed(0)}%</span>
              </div>
            )
          })}
        </div>
      )}
    </Panel>
  )
}
