import { useEffect, useRef } from 'react'
import type { WsMessage } from '../../types/api'
import { useBotStore } from '../stores/useBotStore'
import { usePositionsStore } from '../stores/usePositionsStore'
import { useScannerStore } from '../stores/useScannerStore'
import { useLogsStore } from '../stores/useLogsStore'
import { useResearchStore } from '../stores/useResearchStore'
import { statusApi, positionsApi, scannerApi } from '../api/statusApi'
import { analyticsApi } from '../api/analyticsApi'

const POLL_INTERVAL_MS = 4000
const RECONNECT_DELAY_MS = 10000

function applyMessage(msg: WsMessage) {
  switch (msg.type) {
    case 'init':
      useBotStore.getState().setStatus(msg.status)
      usePositionsStore.getState().setPositions(msg.positions)
      usePositionsStore.getState().setTrades(msg.trades)
      useLogsStore.getState().setLogs(msg.logs)
      useScannerStore.getState().setScanner(msg.scanner)
      if (msg.research_status) useResearchStore.getState().setStatus(msg.research_status)
      break
    case 'state_update':
      useBotStore.getState().setStatus(msg.status)
      usePositionsStore.getState().setPositions(msg.positions)
      usePositionsStore.getState().setTrades(msg.trades)
      if (msg.logs) useLogsStore.getState().setLogs(msg.logs)
      if (msg.research_status) useResearchStore.getState().setStatus(msg.research_status)
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
    case 'realtime_update':
      usePositionsStore.getState().applyRealtimeUpdate(msg.positions, msg.total_daily_pnl ?? msg.daily_pnl, msg.quotes)
      break
    case 'research_progress':
      useResearchStore.getState().setProgress(msg)
      break
    case 'trade_event':
      // Consumed by fx/toast layer in a later phase; state stores already reflect the
      // resulting position/trade change via the state_update that accompanies it.
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
  if (status.status === 'fulfilled') useBotStore.getState().setStatus(status.value)
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
