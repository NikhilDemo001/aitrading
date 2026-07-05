import { useEffect, useRef, useState } from 'react'
import {
  createChart,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type IPriceLine,
  type UTCTimestamp,
} from 'lightweight-charts'
import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { analyticsApi } from '../../lib/api/analyticsApi'
import { usePositionsStore } from '../../lib/stores/usePositionsStore'
import { toIstChartTime } from '../../lib/marketSession'
import type { ChartCandle } from '../../types/api'
import './MainChart.css'

const CHART_TICK_MS = 1000

export function MainChart({ symbol }: { symbol: string | null }) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const emaSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const vwapSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const priceLinesRef = useRef<IPriceLine[]>([])
  const [showEma, setShowEma] = useState(true)
  const [showVwap, setShowVwap] = useState(true)
  const positions = usePositionsStore((s) => s.positions)
  const position = symbol ? positions.find((p) => p.symbol === symbol) : undefined

  // Chart lifecycle: create once per mount.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const chart = createChart(el, {
      layout: { background: { color: 'transparent' }, textColor: '#A8AAB8', fontFamily: 'JetBrains Mono' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.08)', timeVisible: true, secondsVisible: false },
      autoSize: true,
    })
    chartRef.current = chart

    candleSeriesRef.current = chart.addCandlestickSeries({
      upColor: '#00E676',
      downColor: '#FF2D55',
      borderUpColor: '#00E676',
      borderDownColor: '#FF2D55',
      wickUpColor: '#00E676',
      wickDownColor: '#FF2D55',
    })
    emaSeriesRef.current = chart.addLineSeries({ color: '#00F0FF', lineWidth: 1, title: 'EMA20' })
    vwapSeriesRef.current = chart.addLineSeries({ color: '#FBBF24', lineWidth: 1, title: 'VWAP' })

    return () => {
      chart.remove()
      chartRef.current = null
      candleSeriesRef.current = null
      emaSeriesRef.current = null
      vwapSeriesRef.current = null
      priceLinesRef.current = []
    }
  }, [])

  useEffect(() => {
    emaSeriesRef.current?.applyOptions({ visible: showEma })
  }, [showEma])
  useEffect(() => {
    vwapSeriesRef.current?.applyOptions({ visible: showVwap })
  }, [showVwap])

  // Data refresh: mirrors legacy cockpitTick() — poll the chart endpoint every 1s while
  // this symbol is active, scoped to this component so the interval is torn down on
  // unmount/symbol change automatically.
  useEffect(() => {
    if (!symbol) return
    let cancelled = false

    const applyCandles = (candles: ChartCandle[]) => {
      if (cancelled || !candleSeriesRef.current) return
      // Times shifted so the UTC-rendered axis reads IST wall-clock (NSE hours).
      candleSeriesRef.current.setData(
        candles.map((c) => ({
          time: toIstChartTime(c.time) as UTCTimestamp,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        })),
      )
      emaSeriesRef.current?.setData(
        candles.filter((c) => c.ema20 != null).map((c) => ({ time: toIstChartTime(c.time) as UTCTimestamp, value: c.ema20! })),
      )
      vwapSeriesRef.current?.setData(
        candles.filter((c) => c.vwap != null).map((c) => ({ time: toIstChartTime(c.time) as UTCTimestamp, value: c.vwap! })),
      )
      chartRef.current?.timeScale().fitContent()
    }

    const tick = () => {
      analyticsApi.getChart(symbol).then(applyCandles).catch(console.error)
    }

    tick()
    const timer = window.setInterval(tick, CHART_TICK_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [symbol])

  // Entry/SL/target price lines for the active position on this symbol.
  useEffect(() => {
    const series = candleSeriesRef.current
    if (!series) return
    priceLinesRef.current.forEach((line) => series.removePriceLine(line))
    priceLinesRef.current = []
    if (!position) return

    const lines: Array<[number | undefined, string, string]> = [
      [position.entry_price, '#F4F5F7', 'ENTRY'],
      [position.stop_loss, '#FF2D55', 'SL'],
      [position.target, '#00E676', 'T1'],
    ]
    for (const [price, color, title] of lines) {
      if (price == null) continue
      priceLinesRef.current.push(
        series.createPriceLine({ price, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title }),
      )
    }
  }, [position])

  return (
    <Panel
      title={symbol ?? 'Chart'}
      className="mq-chart-panel"
      padded={false}
      actions={
        symbol && (
          <>
            <Button variant={showEma ? 'primary' : 'ghost'} onClick={() => setShowEma((v) => !v)}>EMA20</Button>
            <Button variant={showVwap ? 'primary' : 'ghost'} onClick={() => setShowVwap((v) => !v)}>VWAP</Button>
          </>
        )
      }
    >
      {/* Kept mounted unconditionally: the chart-creation effect below only fires once
          on mount, so if this div only rendered once `symbol` resolved, the effect would
          already have run (and bailed on a null ref) before the div ever existed. */}
      <div ref={containerRef} className="mq-chart-canvas" />
      {!symbol && <div className="mq-chart-empty text-faint">Select a symbol from the watchlist.</div>}
    </Panel>
  )
}
