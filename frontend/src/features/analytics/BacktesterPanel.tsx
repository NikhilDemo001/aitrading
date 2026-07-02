import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Panel } from '../../design-system/Panel'
import { Button } from '../../design-system/Button'
import { analyticsApi } from '../../lib/api/analyticsApi'
import { useBotStore, EMPTY_WATCHLIST } from '../../lib/stores/useBotStore'
import './BacktesterPanel.css'

interface BacktestResult {
  symbol: string
  period: string
  total_trades: number
  win_rate: number
  profit_factor: number
  max_drawdown: number
  sharpe_ratio: number
  avg_rr: number
  total_pnl: number
  gross_pnl: number
  total_costs: number
  rejected: number
  candles: number
  error?: string
}

export function BacktesterPanel() {
  const watchlist = useBotStore((s) => s.status?.watchlist ?? EMPTY_WATCHLIST)
  const [symbol, setSymbol] = useState('')
  const [days, setDays] = useState(30)
  const [slippagePct, setSlippagePct] = useState(0.0005)

  const mutation = useMutation({
    mutationFn: () => analyticsApi.getBacktest(symbol, days, slippagePct) as Promise<BacktestResult>,
  })
  const result = mutation.data

  return (
    <Panel title="Backtester">
      <div className="mq-bt-controls">
        <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
          <option value="" disabled>Symbol</option>
          {watchlist.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <label>Days<input type="number" min={5} max={365} value={days} onChange={(e) => setDays(Number(e.target.value))} /></label>
        <label>Slippage %<input type="number" step={0.0001} value={slippagePct} onChange={(e) => setSlippagePct(Number(e.target.value))} /></label>
        <Button variant="primary" disabled={!symbol || mutation.isPending} onClick={() => mutation.mutate()}>
          {mutation.isPending ? 'Running…' : 'Run Backtest'}
        </Button>
      </div>
      {result?.error && <div className="mq-bt-error">{result.error}</div>}
      {result && !result.error && (
        <div className="mq-bt-results">
          <div><span className="text-faint">Period</span> {result.period}</div>
          <div><span className="text-faint">Trades</span> {result.total_trades} ({result.rejected} rejected)</div>
          <div><span className="text-faint">Win Rate</span> {result.win_rate.toFixed(1)}%</div>
          <div><span className="text-faint">Profit Factor</span> {result.profit_factor.toFixed(2)}</div>
          <div><span className="text-faint">Sharpe</span> {result.sharpe_ratio.toFixed(2)}</div>
          <div><span className="text-faint">Avg R:R</span> {result.avg_rr.toFixed(2)}</div>
          <div className={(result.total_pnl ?? 0) >= 0 ? 'text-profit' : 'text-loss'}>
            <span className="text-faint">Total P&amp;L</span> ₹{result.total_pnl.toFixed(2)}
          </div>
        </div>
      )}
    </Panel>
  )
}
