import { useRef, useState } from 'react'
import { EngineStatusStrip } from './EngineStatusStrip'
import { WatchlistRail } from './WatchlistRail'
import { MainChart } from './MainChart'
import { LiveFeedPanel } from './LiveFeedPanel'
import { ScannerMatrix } from './ScannerMatrix'
import { ActivePositionsGrid } from './ActivePositionsGrid'
import { BrokerBookPanel } from './BrokerBookPanel'
import { GateBreakdown } from './GateBreakdown'
import { DecisionStream } from './DecisionStream'
import { useBotStore, EMPTY_WATCHLIST } from '../../lib/stores/useBotStore'
import './CockpitTab.css'

export function CockpitTab() {
  const watchlist = useBotStore((s) => s.status?.watchlist ?? EMPTY_WATCHLIST)
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const activeSymbol = selectedSymbol ?? watchlist[0] ?? null
  const chartRef = useRef<HTMLDivElement>(null)

  // Both the watchlist and the position cards now sit below the chart, so choosing a symbol
  // has to bring the chart back into view — otherwise the click updates something off-screen.
  const showOnChart = (symbol: string) => {
    setSelectedSymbol(symbol)
    chartRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="mq-cockpit">
      <EngineStatusStrip />
      <div ref={chartRef}>
        <MainChart symbol={activeSymbol} />
      </div>
      {/* Open risk is the page's most urgent block, so it spans the full width directly under
          the chart. */}
      <ActivePositionsGrid selected={activeSymbol} onSelect={showOnChart} />
      <ScannerMatrix />
      <GateBreakdown />
      {/* Watchlist and Live Feed are both "browse / monitor" panels rather than decisions, so
          they share one row below the action blocks. */}
      <div className="mq-cockpit-halves">
        <WatchlistRail selected={activeSymbol} onSelect={showOnChart} />
        <LiveFeedPanel />
      </div>
      <BrokerBookPanel />
      <DecisionStream />
    </div>
  )
}
