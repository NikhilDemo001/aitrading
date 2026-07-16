import { KpiCards } from './KpiCards'
import { EquityCurveChart } from './EquityCurveChart'
import { StrategyBreakdown } from './StrategyBreakdown'
import { MaeMfeScatter } from './MaeMfeScatter'
import { BacktesterPanel } from './BacktesterPanel'
import { RecommendationsPanel } from './RecommendationsPanel'
import { TimeOfDayPanel } from './TimeOfDayPanel'
import './AnalyticsTab.css'

export function AnalyticsTab() {
  return (
    <div className="mq-analytics">
      <KpiCards />
      <div className="mq-analytics-row">
        <EquityCurveChart />
      </div>
      <div className="mq-analytics-row">
        <StrategyBreakdown />
      </div>
      <div className="mq-analytics-row mq-analytics-row-3col">
        <TimeOfDayPanel />
        <MaeMfeScatter />
        <RecommendationsPanel />
      </div>
      <BacktesterPanel />
    </div>
  )
}
