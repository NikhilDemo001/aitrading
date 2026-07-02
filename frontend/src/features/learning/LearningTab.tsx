import { useDateRange } from './useDateRange'
import { DateRangeControls } from './DateRangeControls'
import { KpiDashboard } from './KpiDashboard'
import { LeaderboardSeries } from './LeaderboardSeries'
import { PatternStats } from './PatternStats'
import { FeatureAnalytics } from './FeatureAnalytics'
import { TradeDrilldown } from './TradeDrilldown'
import { CompareRanges } from './CompareRanges'
import { RebuildEodControl } from './RebuildEodControl'
import './LearningTab.css'

export function LearningTab() {
  const { range, setRange, applyPreset } = useDateRange()

  return (
    <div className="mq-learning">
      <DateRangeControls range={range} setRange={setRange} applyPreset={applyPreset} />
      <KpiDashboard range={range} />
      <LeaderboardSeries range={range} />
      <div className="mq-learning-row">
        <PatternStats range={range} />
        <FeatureAnalytics range={range} />
      </div>
      <TradeDrilldown range={range} />
      <div className="mq-learning-row">
        <CompareRanges />
        <RebuildEodControl />
      </div>
    </div>
  )
}
