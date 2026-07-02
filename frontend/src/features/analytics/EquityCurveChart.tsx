import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from 'lightweight-charts'
import { Panel } from '../../design-system/Panel'
import { analyticsApi } from '../../lib/api/analyticsApi'
import './EquityCurveChart.css'

interface EquityPoint {
  date: string
  cumulative_pnl: number
}

export function EquityCurveChart() {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Area'> | null>(null)

  const { data } = useQuery({
    queryKey: ['analytics', 'equity_curve'],
    queryFn: () => analyticsApi.getEquityCurve(30),
    refetchInterval: 30000,
  })

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const chart = createChart(el, {
      layout: { background: { color: 'transparent' }, textColor: '#A8AAB8', fontFamily: 'JetBrains Mono' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.08)' },
      autoSize: true,
    })
    chartRef.current = chart
    seriesRef.current = chart.addAreaSeries({
      lineColor: '#00F0FF',
      topColor: 'rgba(0,240,255,0.35)',
      bottomColor: 'rgba(0,240,255,0.0)',
      lineWidth: 2,
    })
    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  useEffect(() => {
    const points = (data?.equity_curve as unknown as EquityPoint[] | undefined) ?? []
    if (!seriesRef.current) return
    seriesRef.current.setData(
      points.map((p) => ({ time: (new Date(p.date).getTime() / 1000) as UTCTimestamp, value: p.cumulative_pnl })),
    )
    chartRef.current?.timeScale().fitContent()
  }, [data])

  const hasData = (data?.equity_curve?.length ?? 0) > 0

  return (
    <Panel title="Equity Curve · 30D" padded={false} className="mq-equity-panel">
      <div ref={containerRef} className="mq-equity-canvas" />
      {!hasData && <div className="mq-equity-empty text-faint">No closed trades in this period yet.</div>}
    </Panel>
  )
}
