import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Badge } from '../../design-system/Badge'
import { StatCard } from '../../design-system/StatCard'
import { systemApi } from '../../lib/api/systemApi'
import './LaneBPanel.css'

// Exposes Lane B (the Claude-powered self-improvement lane): the LLM engine's live budget,
// its reasoning-call log, and the promotion-gate proposal lifecycle — all previously
// invisible in the UI.
export function LaneBPanel() {
  const { data: llm } = useQuery({ queryKey: ['llm-status'], queryFn: systemApi.getLlmStatus, refetchInterval: 30000 })
  const { data: proposals } = useQuery({ queryKey: ['proposals'], queryFn: systemApi.getProposals, refetchInterval: 30000 })
  const { data: calls } = useQuery({ queryKey: ['llm-calls'], queryFn: () => systemApi.getLlmCalls(50), refetchInterval: 30000 })

  return (
    <div className="mq-laneb">
      <div className="mq-laneb-stats mq-stagger">
        <StatCard label="LLM Engine" value={llm?.enabled ? 'Enabled' : 'Disabled'} tone={llm?.enabled ? 'profit' : 'neutral'} />
        <StatCard label="API Key" value={llm?.key_available ? 'Available' : 'Missing'} tone={llm?.key_available ? 'profit' : 'loss'} />
        <StatCard label="Model" value={llm?.model ?? '—'} />
        <StatCard label="Budget" value={llm ? `${llm.budget_remaining} / ${llm.daily_cap}` : '—'} sub={`${llm?.calls_today ?? 0} calls today`} tone="accent" />
      </div>

      <Panel title={`Promotion Proposals · ${proposals?.length ?? 0}`} padded={false}>
        {(proposals?.length ?? 0) === 0 ? (
          <div className="mq-laneb-empty text-faint">No proposals in the pipeline. Lane B parks candidate strategy changes here for human approval.</div>
        ) : (
          <table className="mq-laneb-table">
            <thead><tr><th>ID</th><th>Strategy</th><th>Status</th><th>Created</th></tr></thead>
            <tbody>
              {proposals!.map((p, i) => (
                <tr key={p.id ?? i}>
                  <td className="text-faint">{p.id ?? '—'}</td>
                  <td>{p.strategy ?? '—'}</td>
                  <td><Badge tone="accent">{p.status ?? '—'}</Badge></td>
                  <td className="text-faint">{p.created_at ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title={`Claude Reasoning Log · ${calls?.length ?? 0}`} padded={false}>
        {(calls?.length ?? 0) === 0 ? (
          <div className="mq-laneb-empty text-faint">No Claude calls logged. The engine is off by default (no spend) — every call would appear here with token counts.</div>
        ) : (
          <table className="mq-laneb-table">
            <thead><tr><th>Time</th><th>Kind</th><th>Model</th><th>Source</th><th>Tokens</th></tr></thead>
            <tbody>
              {calls!.map((c, i) => (
                <tr key={i}>
                  <td className="text-faint">{(c.time ?? c.timestamp ?? '').slice(0, 19)}</td>
                  <td>{c.kind ?? '—'}</td>
                  <td>{c.model ?? '—'}</td>
                  <td className="text-faint">{c.source ?? '—'}</td>
                  <td className="num">{(c.prompt_tokens ?? 0) + (c.completion_tokens ?? 0) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  )
}
