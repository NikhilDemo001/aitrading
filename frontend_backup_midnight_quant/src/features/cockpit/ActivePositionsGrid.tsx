import { Panel } from '../../design-system/Panel'
import { Badge } from '../../design-system/Badge'
import { Button } from '../../design-system/Button'
import { usePositionsStore } from '../../lib/stores/usePositionsStore'
import { statusApi } from '../../lib/api/statusApi'
import './ActivePositionsGrid.css'

export function ActivePositionsGrid() {
  const positions = usePositionsStore((s) => s.positions)

  return (
    <Panel title={`Active Positions · ${positions.length}`} padded={false}>
      {positions.length === 0 ? (
        <div className="mq-positions-empty text-faint">No open positions.</div>
      ) : (
        <div className="mq-positions-grid">
          {positions.map((p) => {
            const pnl = p.pnl ?? 0
            const tone = pnl >= 0 ? 'profit' : 'loss'
            return (
              <div key={p.symbol} className="mq-position-card">
                <div className="mq-position-hdr">
                  <span className="mq-position-sym">{p.symbol}</span>
                  <Badge tone={p.direction === 'BUY' ? 'profit' : 'loss'}>{p.direction}</Badge>
                  {p.strategy && <Badge tone="accent">{p.strategy}</Badge>}
                </div>
                <div className={`mq-position-pnl num text-${tone}`}>
                  {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(2)}
                </div>
                <div className="mq-position-meta">
                  <span>Entry {p.entry_price?.toFixed(2)}</span>
                  <span>SL {p.stop_loss?.toFixed(2)}</span>
                  {p.target != null && <span>Tgt {p.target.toFixed(2)}</span>}
                  {p.confluence_score != null && <span>Conf {p.confluence_score}</span>}
                </div>
                {(p.mae != null || p.mfe != null) && (
                  <div className="mq-position-meta">
                    {p.mae != null && <span>MAE {p.mae.toFixed(2)}</span>}
                    {p.mfe != null && <span>MFE {p.mfe.toFixed(2)}</span>}
                  </div>
                )}
                <Button
                  variant="ghost"
                  onClick={() => statusApi.closePosition(p.symbol).catch(console.error)}
                >
                  Close
                </Button>
              </div>
            )
          })}
        </div>
      )}
    </Panel>
  )
}
