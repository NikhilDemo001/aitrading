import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  createChart,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type UTCTimestamp,
} from 'lightweight-charts'
import { analyticsApi } from '../../lib/api/analyticsApi'
import type { Trade } from '../../types/api'
import { isLongDirection } from '../../lib/tradeMath'
import { toIstChartTime } from '../../lib/marketSession'
import './TradeChart.css'

// Replay a closed trade on the 5-minute candles of its own day: entry/exit markers,
// SL/T1/T2 level lines. Candle data comes from /api/trade-chart (live Upstox history),
// so it needs an authenticated broker session and a date within Upstox's retention.

function tradeDate(trade: Trade): string | null {
  const iso = trade.entry_time ?? trade.exit_time
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(iso ?? '')
  return m ? m[1] : null
}

function toEpochSeconds(iso: string | undefined): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  return Number.isNaN(t) ? null : Math.floor(t / 1000)
}

/** Markers must sit on an existing bar — snap a timestamp to the nearest candle time. */
function snapToCandle(times: number[], target: number | null): number | null {
  if (target == null || times.length === 0) return null
  let best = times[0]
  for (const t of times) {
    if (Math.abs(t - target) < Math.abs(best - target)) best = t
  }
  return best
}

export function TradeChart({ trade }: { trade: Trade }) {
  const date = tradeDate(trade)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)

  const { data: candles, isLoading, isError } = useQuery({
    queryKey: ['trade-chart', trade.symbol, date],
    queryFn: () => analyticsApi.getTradeChart(trade.symbol, date!),
    enabled: date != null,
    staleTime: Infinity, // a finished day's candles never change
    retry: 0,
  })

  useEffect(() => {
    const el = containerRef.current
    if (!el || !candles || candles.length === 0) return

    const chart = createChart(el, {
      layout: { background: { color: 'transparent' }, textColor: '#A8AAB8', fontFamily: 'JetBrains Mono' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.08)', timeVisible: true, secondsVisible: false },
      autoSize: true,
      handleScroll: false,
      handleScale: false,
    })
    chartRef.current = chart

    const series = chart.addCandlestickSeries({
      upColor: '#00E676',
      downColor: '#FF2D55',
      borderUpColor: '#00E676',
      borderDownColor: '#FF2D55',
      wickUpColor: '#00E676',
      wickDownColor: '#FF2D55',
    })
    seriesRef.current = series
    series.setData(
      candles.map((c) => ({
        time: toIstChartTime(c.time) as UTCTimestamp,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    )

    const levels: Array<[number | undefined | null, string, string]> = [
      [trade.entry_price, '#F4F5F7', 'ENTRY'],
      [trade.stop_loss, '#FF2D55', 'SL'],
      [trade.target_1, '#00E676', 'T1'],
      [trade.target_2, 'rgba(0,230,118,0.6)', 'T2'],
    ]
    for (const [price, color, title] of levels) {
      if (price == null) continue
      series.createPriceLine({ price, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title })
    }

    const times = candles.map((c) => toIstChartTime(c.time))
    const long = isLongDirection(trade.direction)
    const entry = toEpochSeconds(trade.entry_time)
    const exit = toEpochSeconds(trade.exit_time)
    const entryTime = snapToCandle(times, entry != null ? toIstChartTime(entry) : null)
    const exitTime = snapToCandle(times, exit != null ? toIstChartTime(exit) : null)
    const markers: SeriesMarker<UTCTimestamp>[] = []
    if (entryTime != null) {
      markers.push({
        time: entryTime as UTCTimestamp,
        position: long ? 'belowBar' : 'aboveBar',
        shape: long ? 'arrowUp' : 'arrowDown',
        color: '#00F0FF',
        text: 'IN',
      })
    }
    if (exitTime != null) {
      markers.push({
        time: exitTime as UTCTimestamp,
        position: long ? 'aboveBar' : 'belowBar',
        shape: 'circle',
        color: (trade.pnl ?? 0) >= 0 ? '#00E676' : '#FF2D55',
        text: 'OUT',
      })
    }
    markers.sort((a, b) => (a.time as number) - (b.time as number))
    series.setMarkers(markers)
    chart.timeScale().fitContent()

    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [candles, trade])

  if (date == null) return null

  return (
    <div className="mq-trade-chart">
      {isLoading ? (
        <div className="mq-trade-chart-note text-faint">Loading the day's candles…</div>
      ) : isError ? (
        <div className="mq-trade-chart-note text-faint">
          Candle data unavailable — the broker session may be expired, or {date} is beyond Upstox retention.
        </div>
      ) : !candles || candles.length === 0 ? (
        <div className="mq-trade-chart-note text-faint">No candles returned for {date}.</div>
      ) : (
        <div ref={containerRef} className="mq-trade-chart-canvas" />
      )}
    </div>
  )
}
