import { Panel } from '../../design-system/Panel'
import { usePositionsStore } from '../../lib/stores/usePositionsStore'
import './MaeMfeScatter.css'

// The backend only exposes mae/mfe on *live* positions (not in the closed-trade export —
// confirmed against the /api/trades/export CSV column list), so this shows real-time
// excursion for currently open positions rather than a fabricated historical scatter.
export function MaeMfeScatter() {
  const positions = usePositionsStore((s) => s.positions).filter((p) => p.mae != null || p.mfe != null)

  return (
    <Panel title="MAE / MFE · open positions">
      {positions.length === 0 ? (
        <div className="mq-mae-empty text-faint">No open positions with excursion data.</div>
      ) : (
        <div className="mq-mae-list">
          {positions.map((p) => (
            <div key={p.symbol} className="mq-mae-row">
              <span className="mq-mae-sym">{p.symbol}</span>
              <span className="mq-mae-label text-loss">MAE {p.mae?.toFixed(2) ?? '—'}</span>
              <span className="mq-mae-label text-profit">MFE {p.mfe?.toFixed(2) ?? '—'}</span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}
