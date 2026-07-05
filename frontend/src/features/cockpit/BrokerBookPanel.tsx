import { useQuery } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Badge } from '../../design-system/Badge'
import { positionsApi } from '../../lib/api/statusApi'
import { useBotStore } from '../../lib/stores/useBotStore'
import { usePositionsStore } from '../../lib/stores/usePositionsStore'
import { formatINR } from '../../lib/tradeMath'
import './BrokerBookPanel.css'

// The broker's real book beside the bot's book — the dashboard face of the
// reconciliation safety net. Live mode only: paper positions exist purely inside
// the bot, so in paper mode this panel renders nothing at all.
//
// Field names follow Upstox GET /v2/portfolio/short-term-positions, with fallbacks
// for the trading-symbol key variants seen across API versions.

function sym(row: Record<string, unknown>): string {
  return String(row.trading_symbol ?? row.tradingsymbol ?? row.symbol ?? '—')
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

export function BrokerBookPanel() {
  const status = useBotStore((s) => s.status)
  const botPositions = usePositionsStore((s) => s.positions)
  const isPaper = status?.paper_trading ?? true

  const { data } = useQuery({
    queryKey: ['broker-book'],
    queryFn: positionsApi.getBrokerBook,
    enabled: !isPaper,
    refetchInterval: 30000,
    retry: 0,
  })

  if (isPaper) return null

  const botKeys = new Set(botPositions.map((p) => String(p.instrument_key ?? '')))
  const botSymbols = new Set(botPositions.map((p) => p.symbol))
  const rows = (data?.positions ?? []).filter((r) => num(r.quantity) !== 0)
  const brokerSymbols = new Set(rows.map(sym))
  const ghosts = botPositions.filter((p) => !brokerSymbols.has(p.symbol))

  return (
    <Panel title={`Broker Book · ${data?.available ? rows.length : '—'}`} padded={false}>
      {!data ? (
        <div className="mq-broker-empty text-faint">Fetching the broker book…</div>
      ) : !data.available ? (
        <div className="mq-broker-empty text-warn">
          Broker book unreachable — reconciliation is flying blind. Check the Upstox session.
        </div>
      ) : rows.length === 0 && ghosts.length === 0 ? (
        <div className="mq-broker-empty text-faint">Broker confirms flat — no open positions on the account.</div>
      ) : (
        <>
          {rows.length > 0 && (
            <table className="mq-broker-table">
              <thead>
                <tr>
                  <th>Symbol</th><th>Net Qty</th><th>Avg Price</th><th>Last</th><th>P&L</th><th>Product</th><th>Bot?</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const pnl = num(r.pnl)
                  const inBot = botKeys.has(String(r.instrument_token ?? r.instrument_key ?? '')) || botSymbols.has(sym(r))
                  return (
                    <tr key={i}>
                      <td className="mq-broker-sym">{sym(r)}</td>
                      <td className="num">{num(r.quantity) ?? '—'}</td>
                      <td className="num">{num(r.average_price)?.toFixed(2) ?? '—'}</td>
                      <td className="num">{num(r.last_price)?.toFixed(2) ?? '—'}</td>
                      <td className={`num ${pnl != null && pnl < 0 ? 'text-loss' : 'text-profit'}`}>
                        {pnl != null ? formatINR(pnl, { sign: true }) : '—'}
                      </td>
                      <td className="text-faint">{String(r.product ?? '—')}</td>
                      <td>
                        {inBot ? (
                          <Badge tone="profit">MANAGED</Badge>
                        ) : (
                          <Badge tone="warn">NOT BOT</Badge>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
          {ghosts.length > 0 && (
            <div className="mq-broker-ghosts">
              {ghosts.map((p) => (
                <span key={p.symbol} className="mq-broker-ghost text-loss">
                  ⚠ {p.symbol}: in the bot's book but NOT at the broker — reconcile will record it as closed externally.
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </Panel>
  )
}
