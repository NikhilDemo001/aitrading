import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Badge } from '../../design-system/Badge'
import { researchApi } from '../../lib/api/researchApi'
import './RiskAndCapital.css'

export function RiskAndCapital() {
  const { data: allocation } = useQuery({ queryKey: ['research', 'allocation'], queryFn: researchApi.getAllocation, refetchInterval: 30000 })
  const { data: briefing } = useQuery({ queryKey: ['research', 'briefing'], queryFn: researchApi.getBriefing, refetchInterval: 30000 })

  return (
    <div className="mq-risk-grid">
      <Panel title="Capital Allocation" padded={false}>
        <div className="mq-alloc-list">
          {(allocation ?? []).map((row) => (
            <div key={row.strategy_id} className="mq-alloc-row">
              <div className="mq-alloc-hdr">
                <span className="mq-alloc-name">{row.name}</span>
                <span className="num">{row.percentage}%</span>
              </div>
              <div className="mq-alloc-track">
                <div className="mq-alloc-fill" style={{ width: `${row.percentage}%` }} />
              </div>
              <span className="mq-alloc-notes text-faint">{row.regime_notes}</span>
            </div>
          ))}
        </div>
      </Panel>

      <Panel title="Risk Alerts">
        {(briefing?.risk_alerts ?? []).length === 0 ? (
          <p className="text-faint">No active risk alerts.</p>
        ) : (
          <ul className="mq-risk-alerts">
            {briefing!.risk_alerts.map((a, i) => (
              <li key={i}><Badge tone="warn">Alert</Badge> {a}</li>
            ))}
          </ul>
        )}
        {briefing && (
          <div className="mq-risk-summary text-faint">
            Paper P&amp;L ₹{briefing.paper_pnl.toLocaleString()} · Win Rate {briefing.paper_win_rate.toFixed(1)}% · {briefing.paper_trades.toLocaleString()} trades
          </div>
        )}
      </Panel>
    </div>
  )
}
