import { StatCard } from '../../design-system/StatCard'
import { ProgressRing } from '../../design-system/ProgressRing'
import { Sparkline } from '../../design-system/Sparkline'
import { useBotStore } from '../../lib/stores/useBotStore'
import { usePositionsStore } from '../../lib/stores/usePositionsStore'
import { useScannerStore } from '../../lib/stores/useScannerStore'
import { usePnlHistoryStore } from '../../lib/stores/usePnlHistoryStore'
import { useCountUp } from '../../lib/useCountUp'
import { formatINR } from '../../lib/tradeMath'
import './EngineStatusStrip.css'

export function EngineStatusStrip() {
  const status = useBotStore((s) => s.status)
  const positions = usePositionsStore((s) => s.positions)
  const scannerContext = useScannerStore((s) => s.scanner.context) as Record<string, unknown> | undefined
  const pnlPoints = usePnlHistoryStore((s) => s.points)

  const dailyPnl = status?.daily_pnl ?? 0
  const animatedPnl = useCountUp(dailyPnl)
  const pnlTone = dailyPnl >= 0 ? 'profit' : 'loss'
  const maxLoss = status?.max_daily_loss ?? 0
  const lossBudgetUsed = maxLoss ? Math.min(100, Math.max(0, (-dailyPnl / maxLoss) * 100)) : 0
  const isPaper = status?.paper_trading ?? true
  const budgetText = isPaper
    ? 'Unlimited (Paper Trading)'
    : `Loss budget used ${lossBudgetUsed.toFixed(0)}% of ₹${maxLoss}`

  // Capital protection, made visible: worst case if every stop hits right now,
  // and how much notional the open book is holding.
  const openRisk = positions.reduce(
    (sum, p) => sum + Math.abs((p.entry_price ?? 0) - (p.stop_loss ?? p.entry_price ?? 0)) * (p.quantity ?? 0),
    0,
  )
  const deployed = positions.reduce((sum, p) => sum + (p.entry_price ?? 0) * (p.quantity ?? 0), 0)

  const sparkValues = pnlPoints.map((p) => p.v)

  return (
    <div className="mq-status-strip mq-stagger">
      <StatCard
        label="Daily P&L"
        tone={pnlTone}
        value={formatINR(animatedPnl, { sign: true })}
        sub={
          sparkValues.length >= 2 ? (
            <span className="mq-pnl-spark">
              <Sparkline values={sparkValues} width={132} height={30} />
              <span>{budgetText}</span>
            </span>
          ) : (
            budgetText
          )
        }
        right={
          isPaper ? (
            <ProgressRing pct={0} tone="profit" label="∞" sub="Paper" />
          ) : (
            <ProgressRing
              pct={lossBudgetUsed}
              tone={lossBudgetUsed >= 80 ? 'loss' : lossBudgetUsed >= 50 ? 'warn' : 'profit'}
              label={`${lossBudgetUsed.toFixed(0)}%`}
              sub="Loss used"
            />
          )
        }
      />
      <StatCard
        label="Open Risk"
        tone={openRisk > 0 ? 'loss' : 'neutral'}
        value={positions.length > 0 ? formatINR(openRisk, { decimals: 0 }) : '₹0'}
        sub={
          positions.length > 0
            ? `if every stop hits · ${formatINR(deployed, { decimals: 0 })} deployed`
            : 'no capital at risk'
        }
      />
      <StatCard
        label="Broker Link"
        tone={status?.authenticated ? 'accent' : 'neutral'}
        value={status?.authenticated ? 'Connected' : 'Offline'}
      />
      <StatCard
        label="Mode"
        value={status?.paper_trading ? 'Paper' : 'Live'}
        tone={status?.paper_trading ? 'accent' : 'loss'}
      />
      <StatCard
        label="Positions"
        value={`${positions.length} / ${status?.max_open_positions ?? '—'}`}
      />
      <StatCard
        label="Scanner"
        value={status?.bot_running ? 'Active' : 'Idle'}
        sub={scannerContext ? undefined : 'no data'}
      />
    </div>
  )
}
