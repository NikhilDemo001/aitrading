import { useEffect, useRef } from 'react'
import type { TradeEventMessage, WsMessage } from '../../types/api'
import { useBotStore } from '../stores/useBotStore'
import { usePositionsStore } from '../stores/usePositionsStore'
import { useScannerStore } from '../stores/useScannerStore'
import { useLogsStore } from '../stores/useLogsStore'
import { useResearchStore } from '../stores/useResearchStore'
import { usePnlHistoryStore } from '../stores/usePnlHistoryStore'
import { useToastStore } from '../stores/useToastStore'
import { isLongDirection, formatINR } from '../tradeMath'
import { statusApi, positionsApi, scannerApi } from '../api/statusApi'
import { analyticsApi } from '../api/analyticsApi'

const POLL_INTERVAL_MS = 4000
const RECONNECT_DELAY_MS = 10000

// Turn a broadcast trade event into a toast. Entries are informational (cyan);
// exits carry their P&L verdict (green/red) and the exit reason.
function toastTradeEvent(msg: TradeEventMessage) {
  const side = isLongDirection(msg.direction) ? 'LONG' : 'SHORT'
  if (msg.event === 'entry') {
    useToastStore.getState().push({
      tone: 'accent',
      title: `ENTRY · ${msg.symbol} ${side}`,
      body: `${msg.quantity ?? '—'} @ ${msg.entry_price != null ? formatINR(msg.entry_price) : '—'} · SL ${
        msg.stop_loss != null ? formatINR(msg.stop_loss) : '—'
      } · T1 ${msg.target != null ? formatINR(msg.target) : '—'}${msg.strategy ? ` · ${msg.strategy}` : ''}`,
      shadow: !!msg.is_shadow,
    })
  } else {
    const pnl = msg.pnl ?? 0
    useToastStore.getState().push({
      tone: pnl >= 0 ? 'profit' : 'loss',
      title: `EXIT · ${msg.symbol} ${formatINR(pnl, { sign: true })}`,
      body: `${msg.quantity ?? '—'} @ ${msg.exit_price != null ? formatINR(msg.exit_price) : '—'}${
        msg.reason ? ` · ${msg.reason}` : ''
      }`,
      shadow: !!msg.is_shadow,
    })
  }
}

function applyMessage(msg: WsMessage) {
  switch (msg.type) {
    case 'init':
      useBotStore.getState().setStatus(msg.status)
      usePositionsStore.getState().setPositions(msg.positions)
      usePositionsStore.getState().setTrades(msg.trades)
      useLogsStore.getState().setLogs(msg.logs)
      useScannerStore.getState().setScanner(msg.scanner)
      if (msg.research_status) useResearchStore.getState().setStatus(msg.research_status)
      if (typeof msg.status?.daily_pnl === 'number') usePnlHistoryStore.getState().push(msg.status.daily_pnl)
      break
    case 'state_update':
      useBotStore.getState().setStatus(msg.status)
      usePositionsStore.getState().setPositions(msg.positions)
      usePositionsStore.getState().setTrades(msg.trades)
      if (msg.logs) useLogsStore.getState().setLogs(msg.logs)
      if (msg.research_status) useResearchStore.getState().setStatus(msg.research_status)
      if (typeof msg.status?.daily_pnl === 'number') usePnlHistoryStore.getState().push(msg.status.daily_pnl)
      break
    case 'logs':
      useLogsStore.getState().appendLogs(msg.logs)
      break
    case 'scanner':
      useScannerStore.getState().setScanner(msg.scanner)
      break
    case 'checking_progress':
      useScannerStore.getState().setCheckingProgress({ symbol: msg.symbol, name: msg.name, status: msg.status })
      break
    case 'realtime_update': {
      const pnl = msg.total_daily_pnl ?? msg.daily_pnl
      usePositionsStore.getState().applyRealtimeUpdate(msg.positions, pnl, msg.quotes)
      if (typeof pnl === 'number') usePnlHistoryStore.getState().push(pnl)
      break
    }
    case 'research_progress':
      useResearchStore.getState().setProgress(msg)
      break
    case 'trade_event':
      // State stores already reflect the resulting position/trade change via the
      // accompanying state_update; this is purely the notification layer.
      toastTradeEvent(msg)
      break
  }
}

async function pollOnce() {
  const results = await Promise.allSettled([
    statusApi.getStatus(),
    positionsApi.getPositions(),
    positionsApi.getTradesToday(),
    analyticsApi.getReport(),
    scannerApi.getLogs(),
    scannerApi.getScanner(),
  ])
  const [status, positions, trades, , logs, scanner] = results
  if (status.status === 'fulfilled') {
    useBotStore.getState().setStatus(status.value)
    if (typeof status.value.daily_pnl === 'number') usePnlHistoryStore.getState().push(status.value.daily_pnl)
  }
  if (positions.status === 'fulfilled') usePositionsStore.getState().setPositions(positions.value)
  if (trades.status === 'fulfilled') usePositionsStore.getState().setTrades(trades.value)
  if (logs.status === 'fulfilled') useLogsStore.getState().setLogs(logs.value)
  if (scanner.status === 'fulfilled') useScannerStore.getState().setScanner(scanner.value)
}

// Mirrors static/app.js's initWebSocket()/poll(): WS is the primary transport; if it
// closes or errors, fall back to a 4s REST poll and keep retrying the WS every 10s.
export function useLiveConnection() {
  const pollTimerRef = useRef<number | null>(null)
  const reconnectTimerRef = useRef<number | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const stoppedRef = useRef(false)

  useEffect(() => {
    stoppedRef.current = false

    const startPolling = () => {
      if (pollTimerRef.current !== null) return
      pollOnce()
      pollTimerRef.current = window.setInterval(pollOnce, POLL_INTERVAL_MS)
    }

    const stopPolling = () => {
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }

    const connect = () => {
      if (stoppedRef.current) return
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const socket = new WebSocket(`${proto}//${window.location.host}/ws`)
      socketRef.current = socket

      // Guards against two stale-closure hazards: (1) the hook unmounting/cleaning up
      // while this socket's close/error event is still in flight, and (2) this socket
      // having already been superseded by a newer one from a later connect() call
      // (e.g. React StrictMode's dev-only double-invoke of the effect). Without these,
      // an old socket's onclose could resurrect polling/reconnect timers after the real
      // connection already took over, or after the component unmounted entirely.
      const isCurrent = () => !stoppedRef.current && socketRef.current === socket

      socket.onopen = () => {
        if (!isCurrent()) return
        useBotStore.getState().setConnected(true)
        stopPolling()
      }
      socket.onmessage = (event) => {
        if (!isCurrent()) return
        try {
          applyMessage(JSON.parse(event.data) as WsMessage)
        } catch (e) {
          console.error('Error handling WebSocket message:', e)
        }
      }
      socket.onclose = () => {
        if (!isCurrent()) return
        useBotStore.getState().setConnected(false)
        startPolling()
        reconnectTimerRef.current = window.setTimeout(connect, RECONNECT_DELAY_MS)
      }
      socket.onerror = () => {
        socket.close()
      }
    }

    connect()

    return () => {
      stoppedRef.current = true
      stopPolling()
      if (reconnectTimerRef.current !== null) window.clearTimeout(reconnectTimerRef.current)
      socketRef.current?.close()
    }
  }, [])
}
