import { useQuery } from '@tanstack/react-query'
import { StatCard } from '../../design-system/StatCard'
import { analyticsApi } from '../../lib/api/analyticsApi'
import './KpiCards.css'

interface Metrics {
  total_trades: number
  win_rate: number
  profit_factor: number
  sharpe_ratio: number
  max_drawdown: number
  expectancy: number
  risk_reward: number
}

export function KpiCards() {
  const { data } = useQuery({
    queryKey: ['analytics', 'report'],
    queryFn: analyticsApi.getReport,
    refetchInterval: 15000,
  })
  const metrics = (data as { metrics?: Metrics } | undefined)?.metrics

  return (
    <div className="mq-kpi-grid mq-stagger">
      <StatCard label="Win Rate" value={`${(metrics?.win_rate ?? 0).toFixed(1)}%`} />
      <StatCard label="Profit Factor" value={(metrics?.profit_factor ?? 0).toFixed(2)} tone={(metrics?.profit_factor ?? 0) >= 1 ? 'profit' : 'loss'} />
      <StatCard label="Sharpe Ratio" value={(metrics?.sharpe_ratio ?? 0).toFixed(2)} />
      <StatCard label="Expectancy" value={`₹${(metrics?.expectancy ?? 0).toFixed(2)}`} tone={(metrics?.expectancy ?? 0) >= 0 ? 'profit' : 'loss'} />
      <StatCard label="Max Drawdown" value={`₹${(metrics?.max_drawdown ?? 0).toFixed(2)}`} tone="loss" />
      <StatCard label="Risk : Reward" value={(metrics?.risk_reward ?? 0).toFixed(2)} />
    </div>
  )
}
