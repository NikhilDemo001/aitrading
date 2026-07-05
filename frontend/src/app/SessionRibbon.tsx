import { useEffect, useState } from 'react'
import { useBotStore } from '../lib/stores/useBotStore'
import {
  getIstNow, getSessionState, toMinutes, formatCountdown,
  MARKET_PREOPEN, MARKET_OPEN, MARKET_CLOSE, type PhaseId,
} from '../lib/marketSession'
import './SessionRibbon.css'

// The signature element of the cockpit: the trading day rendered as a physical
// timeline. Everything this bot does happens between 09:15 and 15:30 IST — the
// ribbon keeps that window, the bot's own entry/manage/square-off zones, and a
// live now-marker in view on every tab.

const PHASE_LED: Record<PhaseId, string> = {
  closed: 'led-off',
  preopen: 'led-amber',
  warmup: 'led-cyan',
  entry: 'led-cyan led-pulse',
  manage: 'led-amber led-pulse',
  squareoff: 'led-crimson led-pulse',
}

const RIBBON_SPAN = MARKET_CLOSE - MARKET_PREOPEN

function pct(minutes: number): number {
  return ((minutes - MARKET_PREOPEN) / RIBBON_SPAN) * 100
}

export function SessionRibbon() {
  const status = useBotStore((s) => s.status)
  const [now, setNow] = useState(() => getIstNow())

  useEffect(() => {
    const id = window.setInterval(() => setNow(getIstNow()), 1000)
    return () => window.clearInterval(id)
  }, [])

  const times = {
    tradeStart: status?.trade_start_time ?? '09:30',
    tradeEnd: status?.trade_end_time ?? '14:30',
    squareOff: status?.square_off_time ?? '15:10',
  }
  const session = getSessionState(now, times)

  const start = toMinutes(times.tradeStart, 9 * 60 + 30)
  const end = toMinutes(times.tradeEnd, 14 * 60 + 30)
  const sqOff = toMinutes(times.squareOff, 15 * 60 + 10)

  const zones: Array<{ id: string; from: number; to: number; title: string }> = [
    { id: 'preopen', from: MARKET_PREOPEN, to: MARKET_OPEN, title: 'Pre-open 09:00–09:15' },
    { id: 'warmup', from: MARKET_OPEN, to: start, title: `Warm-up 09:15–${times.tradeStart}` },
    { id: 'entry', from: start, to: end, title: `Entry window ${times.tradeStart}–${times.tradeEnd}` },
    { id: 'manage', from: end, to: sqOff, title: `Manage only ${times.tradeEnd}–${times.squareOff}` },
    { id: 'squareoff', from: sqOff, to: MARKET_CLOSE, title: `Square-off ${times.squareOff}–15:30` },
  ]

  const clock = `${String(now.hh).padStart(2, '0')}:${String(now.mm).padStart(2, '0')}:${String(now.ss).padStart(2, '0')}`

  return (
    <div className={`mq-session mq-session-${session.phase}`} role="status" aria-label="Market session">
      <div className="mq-session-phase">
        <span className={`led ${PHASE_LED[session.phase]}`} />
        <span className="mq-session-label">{session.label}</span>
        <span className="mq-session-detail">{session.detail}</span>
      </div>

      <div className={`mq-session-track ${session.phase === 'closed' ? 'mq-session-track-closed' : ''}`} aria-hidden="true">
        {zones.map((z) => (
          <div
            key={z.id}
            className={`mq-session-zone mq-session-zone-${z.id} ${session.phase === z.id ? 'is-now' : ''}`}
            style={{ left: `${pct(z.from)}%`, width: `${pct(z.to) - pct(z.from)}%` }}
            title={z.title}
          />
        ))}
        {[MARKET_OPEN, start, end, sqOff].map((m) => (
          <div key={m} className="mq-session-tick" style={{ left: `${pct(m)}%` }} />
        ))}
        {session.ribbonPct != null && (
          <div className="mq-session-now" style={{ left: `${session.ribbonPct * 100}%` }} />
        )}
        <span className="mq-session-edge mq-session-edge-l">09:00</span>
        <span className="mq-session-edge mq-session-edge-r">15:30</span>
      </div>

      <div className="mq-session-right">
        <span className="mq-session-next">
          {session.nextLabel} in <strong className="num">{formatCountdown(session.minutesToNext)}</strong>
        </span>
        <span className="mq-session-clock num">{clock} IST</span>
      </div>
    </div>
  )
}
