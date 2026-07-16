import { RealVsShadowStrip } from './RealVsShadowStrip'
import { ClosedTradesTable, ShadowTradesTable } from '../cockpit/ClosedTradesTable'
import { HistoricalTradesTable } from '../cockpit/HistoricalTradesTable'
import './TradesTab.css'

// The books live here rather than in the Cockpit: the Cockpit is for what the bot is doing
// right now, this tab is for what it already did.
export function TradesTab() {
  return (
    <div className="mq-trades-tab">
      <RealVsShadowStrip />
      <ClosedTradesTable />
      <HistoricalTradesTable />
      <ShadowTradesTable />
    </div>
  )
}
