import { StatCard } from '../../design-system/StatCard'
import { useBotStore } from '../../lib/stores/useBotStore'
import { usePositionsStore } from '../../lib/stores/usePositionsStore'
import { useScannerStore } from '../../lib/stores/useScannerStore'
import './EngineStatusStrip.css'

export function EngineStatusStrip() {
  const status = useBotStore((s) => s.status)
  const positions = usePositionsStore((s) => s.positions)
  const scannerContext = useScannerStore((s) => s.scanner.context) as Record<string, unknown> | undefined

  const dailyPnl = status?.daily_pnl ?? 0
  const pnlTone = dailyPnl >= 0 ? 'profit' : 'loss'
  const maxLoss = status?.max_daily_loss ?? 0
  const lossBudgetUsed = maxLoss ? Math.min(100, Math.max(0, (-dailyPnl / maxLoss) * 100)) : 0
  const isPaper = status?.paper_trading ?? true
  const subText = isPaper 
    ? "Unlimited (Paper Trading)" 
    : `Loss budget used ${lossBudgetUsed.toFixed(0)}% of ₹${maxLoss}`

  return (
    <div className="mq-status-strip mq-stagger">
      <StatCard
        label="Daily P&L"
        tone={pnlTone}
        value={`${dailyPnl >= 0 ? '+' : ''}₹${dailyPnl.toFixed(2)}`}
        sub={subText}
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
