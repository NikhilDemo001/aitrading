import { useState } from 'react'
import { EngineStatusStrip } from './EngineStatusStrip'
import { WatchlistRail } from './WatchlistRail'
import { MainChart } from './MainChart'
import { LiveFeedPanel } from './LiveFeedPanel'
import { ScannerMatrix } from './ScannerMatrix'
import { ManualTradeTicket } from './ManualTradeTicket'
import { NewsPanel } from './NewsPanel'
import { ActivePositionsGrid } from './ActivePositionsGrid'
import { BrokerBookPanel } from './BrokerBookPanel'
import { ClosedTradesTable } from './ClosedTradesTable'
import { HistoricalTradesTable } from './HistoricalTradesTable'
import { DecisionStream } from './DecisionStream'
import { useBotStore, EMPTY_WATCHLIST } from '../../lib/stores/useBotStore'
import './CockpitTab.css'

export function CockpitTab() {
  const watchlist = useBotStore((s) => s.status?.watchlist ?? EMPTY_WATCHLIST)
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const activeSymbol = selectedSymbol ?? watchlist[0] ?? null

  return (
    <div className="mq-cockpit">
      <EngineStatusStrip />
      <div className="mq-cockpit-columns">
        <div className="mq-cockpit-col mq-cockpit-col-left">
          <WatchlistRail selected={activeSymbol} onSelect={setSelectedSymbol} />
        </div>
        <div className="mq-cockpit-col mq-cockpit-col-center">
          <MainChart symbol={activeSymbol} />
          <ScannerMatrix />
        </div>
        <div className="mq-cockpit-col mq-cockpit-col-right">
          <LiveFeedPanel />
          <ManualTradeTicket symbol={activeSymbol} />
          <NewsPanel symbol={activeSymbol} />
        </div>
      </div>
      <ActivePositionsGrid />
      <BrokerBookPanel />
      <DecisionStream />
      <ClosedTradesTable />
      <HistoricalTradesTable />
    </div>
  )
}
