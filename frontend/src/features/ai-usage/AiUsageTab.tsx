import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { StatCard } from '../../design-system/StatCard'
import { Badge } from '../../design-system/Badge'
import { ProgressRing } from '../../design-system/ProgressRing'
import { llmApi, type Budget } from '../../lib/api/llmApi'
import { systemApi } from '../../lib/api/systemApi'
import './AiUsageTab.css'

const KIND_LABEL: Record<string, string> = {
  confirm: 'Entry gate',
  lesson: 'Trade lessons',
  proposal: 'EOD proposals',
  assistant: 'Assistant chat',
}

const num = (n: number) => n.toLocaleString('en-IN')

// The trading budget is not a cost dial: the entry gate is fail-closed, so hitting the cap
// stops the bot taking trades. Warn well before it bites.
function BudgetPanel({ title, budget, note }: { title: string; budget: Budget; note: string }) {
  const pct = budget.cap > 0 ? Math.min(100, (budget.used / budget.cap) * 100) : 0
  const tone = pct >= 90 ? 'loss' : pct >= 70 ? 'warn' : 'profit'
  return (
    <StatCard
      label={title}
      value={`${num(budget.used)} / ${num(budget.cap)}`}
      tone={pct >= 90 ? 'loss' : undefined}
      sub={`${num(budget.remaining)} calls left · ${note}`}
      right={<ProgressRing pct={pct} tone={tone} label={`${pct.toFixed(0)}%`} sub="used" />}
    />
  )
}

export function AiUsageTab() {
  const { data: u, isLoading } = useQuery({
    queryKey: ['llm', 'usage'],
    queryFn: llmApi.getUsage,
    refetchInterval: 15000,
  })
  const { data: calls } = useQuery({
    queryKey: ['llm', 'calls'],
    queryFn: () => systemApi.getLlmCalls(40),
    refetchInterval: 15000,
  })

  if (isLoading || !u) {
    return <Panel title="AI Usage"><div className="text-faint">Loading usage…</div></Panel>
  }

  const kinds = Object.entries(u.by_kind).sort((a, b) => b[1].calls - a[1].calls)

  return (
    <div className="mq-aiu">
      <div className="mq-aiu-cards">
        <BudgetPanel title="Trading budget · calls today" budget={u.budgets.trading}
          note="entry gate, lessons, proposals" />
        <BudgetPanel title="Assistant budget · calls today" budget={u.budgets.assistant}
          note="your chat only" />
        <StatCard label="Tokens today" value={num(u.total_tokens)}
          sub={`${num(u.input_tokens)} in · ${num(u.output_tokens)} out`} />
        <StatCard
          label="Estimated cost today"
          value={u.cost.priced ? `$${(u.cost.usd ?? 0).toFixed(4)}` : '—'}
          sub={
            u.cost.priced
              ? (u.cost.inr != null ? `≈ ₹${u.cost.inr.toFixed(2)} at your configured rate` : 'set usd_inr_rate for ₹')
              : 'set llm_price_input/output_per_mtok in config'
          }
        />
      </div>

      {u.calls_missing_tokens > 0 && (
        <Panel title="Token history">
          <p className="mq-aiu-note text-faint">
            {num(u.calls_missing_tokens)} of today's {num(u.calls_total)} calls were made before token
            logging existed, so their tokens aren't counted above. Every call from now on records the
            provider's real numbers — expect today's totals to read low.
          </p>
        </Panel>
      )}

      <Panel title="Engine">
        <div className="mq-aiu-engine">
          <span>Status <Badge tone={u.enabled ? 'profit' : 'loss'}>{u.enabled ? 'Live' : 'Disabled'}</Badge></span>
          <span className="text-faint">Provider <b>{u.provider}</b></span>
          <span className="text-faint">Model <b>{u.model}</b></span>
          <span className="text-faint">Date <b>{u.date}</b></span>
        </div>
      </Panel>

      <Panel title="Where the calls went" padded={false}>
        {kinds.length === 0 ? (
          <div className="mq-aiu-empty text-faint">No LLM calls today.</div>
        ) : (
          <table className="mq-aiu-table">
            <thead>
              <tr>
                <th>Purpose</th><th>Calls</th><th>OK</th><th>Failed</th>
                <th>Input</th><th>Output</th><th>Thinking</th>
              </tr>
            </thead>
            <tbody>
              {kinds.map(([kind, k]) => (
                <tr key={kind}>
                  <td>{KIND_LABEL[kind] ?? kind}</td>
                  <td className="num">{num(k.calls)}</td>
                  <td className="num text-profit">{num(k.ok)}</td>
                  <td className={`num ${k.failed > 0 ? 'text-loss' : 'text-faint'}`}>{num(k.failed)}</td>
                  <td className="num">{num(k.input_tokens)}</td>
                  <td className="num">{num(k.output_tokens)}</td>
                  <td className="num text-faint">{num(k.thinking_tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title={`Recent calls · ${(calls ?? []).length}`} padded={false}>
        {(calls ?? []).length === 0 ? (
          <div className="mq-aiu-empty text-faint">No calls logged yet.</div>
        ) : (
          <div className="mq-aiu-calls">
            {(calls ?? []).slice(0, 40).map((c, i) => {
              const t = String(c.time ?? c.timestamp ?? '')
              const inTok = c.input_tokens as number | undefined
              const outTok = c.output_tokens as number | undefined
              return (
                <div key={i} className="mq-aiu-call">
                  <span className="mq-aiu-call-time num text-faint">{t.slice(11, 19)}</span>
                  <Badge tone={c.ok === false ? 'loss' : 'accent'}>{String(c.kind ?? '?')}</Badge>
                  <span className="text-faint">{String(c.source ?? '')}</span>
                  <span className="mq-aiu-call-sum">{String(c.prompt_summary ?? '')}</span>
                  <span className="mq-aiu-call-tok num text-faint">
                    {inTok != null ? `${num(inTok)}→${num(outTok ?? 0)}` : '—'}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </Panel>
    </div>
  )
}
