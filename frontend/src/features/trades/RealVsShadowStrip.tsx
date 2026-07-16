import { useMemo } from 'react'
import { Panel } from '../../design-system/Panel'
import { StatCard } from '../../design-system/StatCard'
import { usePositionsStore } from '../../lib/stores/usePositionsStore'
import { formatINR } from '../../lib/tradeMath'
import type { Trade } from '../../types/api'
import './RealVsShadowStrip.css'

function summarise(trades: Trade[]) {
  const net = trades.reduce((s, t) => s + (t.pnl ?? 0), 0)
  const wins = trades.filter((t) => (t.pnl ?? 0) >= 0).length
  const winRate = trades.length > 0 ? (wins / trades.length) * 100 : 0
  return { net, count: trades.length, winRate }
}

// Reads the day's two books side by side. The gap between them is the clearest signal the bot
// gives about whether its entry gates are earning their keep.
function verdict(real: ReturnType<typeof summarise>, shadow: ReturnType<typeof summarise>) {
  if (real.count === 0 && shadow.count === 0) return 'No trades on either book yet today.'
  if (shadow.count === 0) return 'No shadow trades today — nothing to compare against.'
  if (real.count === 0) return 'No real trades today, so only the simulated book has a result.'
  if (real.net >= 0 && shadow.net < 0) {
    return 'Real is green while shadow is red — the entry gates are keeping losers out. Loosening them would likely cost money.'
  }
  if (real.net < 0 && shadow.net > 0) {
    return 'Shadow is beating real — the gates may be filtering out winners. Worth reviewing which gate blocked the shadow winners.'
  }
  if (real.net >= 0 && shadow.net >= 0) return 'Both books are green today.'
  return 'Both books are red today — the setups themselves are struggling, not just the filters.'
}

export function RealVsShadowStrip() {
  const trades = usePositionsStore((s) => s.trades)
  const { real, shadow } = useMemo(() => ({
    real: summarise(trades.filter((t) => !t.is_shadow_trade)),
    shadow: summarise(trades.filter((t) => t.is_shadow_trade)),
  }), [trades])

  return (
    <Panel title="Real vs Shadow — today">
      <div className="mq-rvs">
        <StatCard
          label="Real · capital engaged"
          tone={real.net >= 0 ? 'profit' : 'loss'}
          value={formatINR(real.net, { sign: true, decimals: 0 })}
          sub={real.count > 0 ? `${real.count} trades · ${real.winRate.toFixed(0)}% win` : 'no real trades'}
        />
        <StatCard
          label="Shadow · simulated"
          tone={shadow.net >= 0 ? 'profit' : 'loss'}
          value={formatINR(shadow.net, { sign: true, decimals: 0 })}
          sub={shadow.count > 0 ? `${shadow.count} trades · ${shadow.winRate.toFixed(0)}% win` : 'no shadow trades'}
        />
      </div>
      <p className="mq-rvs-note text-faint">{verdict(real, shadow)}</p>
    </Panel>
  )
}
