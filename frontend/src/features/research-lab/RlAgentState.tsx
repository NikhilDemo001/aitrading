import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { StatCard } from '../../design-system/StatCard'
import { Badge } from '../../design-system/Badge'
import { researchApi } from '../../lib/api/researchApi'
import { systemApi } from '../../lib/api/systemApi'
import './RlAgentState.css'

export function RlAgentState() {
  const { data: briefing } = useQuery({ queryKey: ['research-briefing'], queryFn: researchApi.getBriefing, refetchInterval: 10000 })
  const { data: summary } = useQuery({ queryKey: ['research-summary'], queryFn: researchApi.getSummary, refetchInterval: 10000 })
  const { data: llm } = useQuery({ queryKey: ['llm-status'], queryFn: systemApi.getLlmStatus, refetchInterval: 30000 })

  const paperTrades = briefing?.paper_trades
  const paperWr = briefing?.paper_win_rate
  const paperPnl = briefing?.paper_pnl
  const learningEvents = summary ? (summary.validation ?? 0) + (summary.papertrading ?? 0) : undefined
  const approved = summary?.approved ?? 0
  const liveCandidates = summary?.live_candidates ?? 0
  const validatorTone = approved > 0 ? 'profit' : liveCandidates > 0 ? 'warn' : 'neutral'
  const validatorText = approved > 0 ? `${approved} approved` : liveCandidates > 0 ? `${liveCandidates} pending` : 'none'

  return (
    <Panel title="RL Agent · Policy State" icon={<span className="led led-cyan led-pulse" />}>
      <div className="mq-rl-grid">
        <StatCard label="Paper Trade Logs" tone="accent" value={paperTrades != null ? paperTrades : '—'} sub={paperWr != null ? `${paperWr.toFixed(0)}% win rate` : undefined} />
        <StatCard label="Paper P&L" tone={(paperPnl ?? 0) >= 0 ? 'profit' : 'loss'} value={paperPnl != null ? `${paperPnl >= 0 ? '+' : ''}₹${paperPnl.toFixed(0)}` : '—'} />
        <StatCard label="Learning Events" tone="accent" value={learningEvents != null ? learningEvents : '—'} sub="validating + paper-trading" />
        <StatCard label="LLM Calls Today" value={llm ? `${llm.calls_today}/${llm.daily_cap}` : '—'} sub={llm?.enabled ? 'engine on' : 'engine off'} />
      </div>
      <div className="mq-rl-validator">
        <span className="mq-rl-validator-label">Out-of-sample validator</span>
        <Badge tone={validatorTone}>{validatorText}</Badge>
      </div>
    </Panel>
  )
}
