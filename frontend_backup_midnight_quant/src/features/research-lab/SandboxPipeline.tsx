import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Badge } from '../../design-system/Badge'
import { StatCard } from '../../design-system/StatCard'
import { researchApi } from '../../lib/api/researchApi'
import './SandboxPipeline.css'

function statusTone(status: string): 'profit' | 'loss' | 'accent' | 'neutral' {
  if (/approved|paper trading|live/i.test(status)) return 'profit'
  if (/rejected|retired/i.test(status)) return 'loss'
  if (/backtesting|validation|walkforward/i.test(status)) return 'accent'
  return 'neutral'
}

export function SandboxPipeline() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState('')

  const { data: summary } = useQuery({ queryKey: ['research', 'summary'], queryFn: researchApi.getSummary, refetchInterval: 20000 })
  const { data: strategies } = useQuery({ queryKey: ['research', 'strategies'], queryFn: researchApi.getStrategies, refetchInterval: 20000 })
  const { data: leaderboard } = useQuery({ queryKey: ['research', 'leaderboard'], queryFn: researchApi.getLeaderboard, refetchInterval: 30000 })
  const { data: detail } = useQuery({
    queryKey: ['research', 'strategy', selectedId],
    queryFn: () => researchApi.getStrategy(selectedId!),
    enabled: !!selectedId,
  })

  const filtered = (strategies ?? []).filter((s) => !statusFilter || s.status === statusFilter)
  const statuses = [...new Set((strategies ?? []).map((s) => s.status))]

  return (
    <div className="mq-sandbox">
      <div className="mq-sandbox-stats mq-stagger">
        <StatCard label="Under Research" value={summary?.under_research ?? 0} />
        <StatCard label="Backtesting" value={summary?.backtesting ?? 0} tone="accent" />
        <StatCard label="Paper Trading" value={summary?.papertrading ?? 0} tone="accent" />
        <StatCard label="Live Candidates" value={summary?.live_candidates ?? 0} tone="profit" />
        <StatCard label="Approved" value={summary?.approved ?? 0} tone="profit" />
        <StatCard label="Rejected" value={summary?.rejected ?? 0} tone="loss" />
      </div>

      <div className="mq-sandbox-main">
        <Panel
          title={`Strategies · ${filtered.length}`}
          padded={false}
          className="mq-sandbox-list-panel"
          actions={
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All statuses</option>
              {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          }
        >
          <div className="mq-sandbox-list">
            {filtered.map((s) => (
              <button key={s.id} className={`mq-sandbox-row ${selectedId === s.id ? 'active' : ''}`} onClick={() => setSelectedId(s.id)}>
                <span className="mq-sandbox-name">{s.name}</span>
                <Badge tone={statusTone(s.status)}>{s.status}</Badge>
                <span className="num text-faint">{s.current_score.toFixed(1)}</span>
              </button>
            ))}
          </div>
        </Panel>

        <Panel title={detail?.name ?? 'Select a strategy'} className="mq-sandbox-detail">
          {!detail ? (
            <p className="text-faint">Click a strategy on the left to see its rules, backtest, and hypothesis.</p>
          ) : (
            <div className="mq-detail-body">
              <div className="mq-detail-badges">
                <Badge tone={statusTone(detail.status)}>{detail.status}</Badge>
                <Badge tone="neutral">Score {detail.current_score.toFixed(1)}</Badge>
                {detail.active_version && <Badge tone="neutral">v{detail.active_version.version}</Badge>}
              </div>
              {detail.active_version && (
                <>
                  <section className="mq-detail-section">
                    <h4>Rules</h4>
                    <dl>
                      <dt>Entry</dt><dd>{detail.active_version.entry_rules}</dd>
                      <dt>Exit</dt><dd>{detail.active_version.exit_rules}</dd>
                      <dt>Stop Loss</dt><dd>{detail.active_version.stop_loss_rules}</dd>
                      <dt>Target</dt><dd>{detail.active_version.target_rules}</dd>
                      <dt>Sizing</dt><dd>{detail.active_version.sizing_rules}</dd>
                    </dl>
                  </section>
                  {detail.active_version.backtest && (
                    <section className="mq-detail-section">
                      <h4>Backtest</h4>
                      <div className="mq-detail-metrics">
                        <span>Trades {detail.active_version.backtest.total_trades}</span>
                        <span>Win Rate {detail.active_version.backtest.win_rate.toFixed(1)}%</span>
                        <span>PF {detail.active_version.backtest.profit_factor.toFixed(2)}</span>
                        <span>Sharpe {detail.active_version.backtest.sharpe_ratio.toFixed(2)}</span>
                      </div>
                    </section>
                  )}
                  {detail.active_version.hypothesis && (
                    <section className="mq-detail-section">
                      <h4>Hypothesis</h4>
                      <p>{detail.active_version.hypothesis.pattern_description}</p>
                      <p className="text-faint">{detail.active_version.hypothesis.reasoning}</p>
                    </section>
                  )}
                </>
              )}
            </div>
          )}
        </Panel>
      </div>

      <Panel title="Strategy Leaderboard" padded={false}>
        <table className="mq-leaderboard-table">
          <thead>
            <tr><th>#</th><th>Strategy</th><th>PF</th><th>Sharpe</th><th>Consistency</th><th>Status</th></tr>
          </thead>
          <tbody>
            {(leaderboard ?? []).slice(0, 15).map((row) => (
              <tr key={row.id}>
                <td className="text-faint">{row.rank}</td>
                <td className="mq-sandbox-name">{row.name}</td>
                <td className="num">{row.profit_factor.toFixed(2)}</td>
                <td className="num">{row.sharpe_ratio.toFixed(2)}</td>
                <td className="num">{row.consistency.toFixed(1)}</td>
                <td><Badge tone={statusTone(row.status)}>{row.status}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  )
}
