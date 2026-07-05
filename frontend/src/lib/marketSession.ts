// NSE intraday session math, computed in IST regardless of the viewer's clock.
// Boundaries come from the bot's own config via /api/status (trade_start_time,
// trade_end_time, square_off_time) with the backend's defaults as fallbacks.
// NSE exchange holidays are not modelled — on a holiday the ribbon shows a normal
// closed market once no ticks arrive; that trade-off keeps this dependency-free.

export type PhaseId = 'closed' | 'preopen' | 'warmup' | 'entry' | 'manage' | 'squareoff'

export interface SessionTimes {
  tradeStart: string // "09:30"
  tradeEnd: string // "14:30"
  squareOff: string // "15:10"
}

export interface IstNow {
  dow: number // 0=Sun … 6=Sat
  minutes: number // minutes since IST midnight, fractional seconds included
  hh: number
  mm: number
  ss: number
}

export const MARKET_PREOPEN = 9 * 60 // 09:00
export const MARKET_OPEN = 9 * 60 + 15 // 09:15
export const MARKET_CLOSE = 15 * 60 + 30 // 15:30

// lightweight-charts renders epoch timestamps on a UTC axis with no timezone
// option — shift epochs by IST's offset so the axis reads NSE wall-clock time.
export const IST_OFFSET_SECONDS = 5.5 * 3600

export function toIstChartTime(epochSeconds: number): number {
  return epochSeconds + IST_OFFSET_SECONDS
}

export function toMinutes(hhmm: string, fallback: number): number {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm ?? '')
  if (!m) return fallback
  return Number(m[1]) * 60 + Number(m[2])
}

export function getIstNow(date: Date = new Date()): IstNow {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(date)
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? ''
  const dow = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(get('weekday'))
  const hh = Number(get('hour')) % 24
  const mm = Number(get('minute'))
  const ss = Number(get('second'))
  return { dow, hh, mm, ss, minutes: hh * 60 + mm + ss / 60 }
}

export interface SessionState {
  phase: PhaseId
  label: string
  detail: string
  /** minutes until the next phase boundary (or next market open when closed) */
  minutesToNext: number
  nextLabel: string
  /** 0–1 position of "now" along the 09:00→15:30 ribbon; null when outside it */
  ribbonPct: number | null
  isTradingDay: boolean
}

const PHASE_LABELS: Record<PhaseId, string> = {
  closed: 'MARKET CLOSED',
  preopen: 'PRE-OPEN',
  warmup: 'WARM-UP',
  entry: 'ENTRY WINDOW',
  manage: 'MANAGE ONLY',
  squareoff: 'SQUARE-OFF',
}

/** Minutes from `now` (an IST snapshot) until the next weekday market open. */
function minutesToNextOpen(now: IstNow): number {
  for (let ahead = 0; ahead <= 7; ahead++) {
    const dow = (now.dow + ahead) % 7
    if (dow === 0 || dow === 6) continue // weekend
    const openAt = ahead * 24 * 60 + MARKET_OPEN
    const nowAt = now.minutes
    if (ahead === 0 && nowAt >= MARKET_OPEN) continue // today's open already passed
    return openAt - nowAt
  }
  return 0 // unreachable
}

export function getSessionState(now: IstNow, times: SessionTimes): SessionState {
  const start = toMinutes(times.tradeStart, 9 * 60 + 30)
  const end = toMinutes(times.tradeEnd, 14 * 60 + 30)
  const sqOff = toMinutes(times.squareOff, 15 * 60 + 10)
  const t = now.minutes
  const weekend = now.dow === 0 || now.dow === 6
  const inRibbon = !weekend && t >= MARKET_PREOPEN && t < MARKET_CLOSE
  const ribbonPct = inRibbon ? (t - MARKET_PREOPEN) / (MARKET_CLOSE - MARKET_PREOPEN) : null

  const mk = (phase: PhaseId, detail: string, minutesToNext: number, nextLabel: string): SessionState => ({
    phase,
    label: PHASE_LABELS[phase],
    detail,
    minutesToNext,
    nextLabel,
    ribbonPct,
    isTradingDay: !weekend,
  })

  if (weekend || t < MARKET_PREOPEN || t >= MARKET_CLOSE) {
    return mk('closed', 'NSE equities', minutesToNextOpen(now), 'market open')
  }
  if (t < MARKET_OPEN) return mk('preopen', 'auction + buffer', MARKET_OPEN - t, 'market open')
  if (t < start) return mk('warmup', 'market open · bot waits for range', start - t, 'entry window')
  if (t < end) return mk('entry', 'scanning for entries', end - t, 'entries close')
  if (t < sqOff) return mk('manage', 'no new entries · managing exits', sqOff - t, 'square-off')
  return mk('squareoff', 'force-flattening the book', MARKET_CLOSE - t, 'market close')
}

/** "1d 13h", "2h 48m", "48m 12s" — one unit pair, chosen by magnitude. */
export function formatCountdown(minutes: number): string {
  const totalSec = Math.max(0, Math.round(minutes * 60))
  const d = Math.floor(totalSec / 86400)
  const h = Math.floor((totalSec % 86400) / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m ${String(s).padStart(2, '0')}s`
}
