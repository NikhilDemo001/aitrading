import { Panel } from '../../design-system/Panel'
import { usePositionsStore } from '../../lib/stores/usePositionsStore'
import './ClosedTradesTable.css'

export function ClosedTradesTable() {
  const trades = usePositionsStore((s) => s.trades)

  return (
    <Panel title={`Closed Trades — Today · ${trades.length}`} padded={false}>
      {trades.length === 0 ? (
        <div className="mq-trades-empty text-faint">No trades closed today.</div>
      ) : (
        <table className="mq-trades-table">
          <thead>
            <tr>
              <th>Symbol</th><th>Strategy</th><th>Dir</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Exit time</th><th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => {
              const pnl = t.pnl ?? 0
              return (
                <tr key={i}>
                  <td className="mq-trades-sym">{t.symbol}</td>
                  <td>{t.strategy ?? '—'}</td>
                  <td>{t.direction}</td>
                  <td className="num">{t.entry_price?.toFixed(2)}</td>
                  <td className="num">{t.exit_price?.toFixed(2) ?? '—'}</td>
                  <td className={`num ${pnl >= 0 ? 'text-profit' : 'text-loss'}`}>{pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}</td>
                  <td className="text-faint">{t.exit_time?.slice(11, 19) ?? '—'}</td>
                  <td className="text-faint">{t.exit_reason ?? '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </Panel>
  )
}
