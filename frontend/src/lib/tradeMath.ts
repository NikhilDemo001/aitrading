// Shared trade arithmetic + formatting. The backend writes direction as "LONG"/"SHORT"
// on the scan path and "BUY"/"SELL" on the manual path — every consumer must go through
// isLongDirection() instead of comparing against a single literal.

import type { Trade } from '../types/api'

export function isLongDirection(direction: string | undefined): boolean {
  const d = (direction ?? '').toUpperCase()
  return d === 'BUY' || d === 'LONG'
}

/** Signed P&L per unit of risk taken (entry→stop distance). Null when inputs are missing. */
export function rMultiple(t: {
  entry_price?: number
  exit_price?: number
  stop_loss?: number
  direction?: string
}): number | null {
  const { entry_price: entry, exit_price: exit, stop_loss: stop, direction } = t
  if (entry == null || exit == null || stop == null) return null
  const risk = Math.abs(entry - stop)
  if (risk === 0) return null
  const raw = isLongDirection(direction) ? exit - entry : entry - exit
  return raw / risk
}

/** P&L as % of invested notional. Uses the stored pnl_pct when present, else computes. */
export function pnlPct(t: Trade): number | null {
  if (t.pnl_pct != null) return t.pnl_pct
  const inv = invested(t)
  if (t.pnl == null || inv == null || inv === 0) return null
  return (t.pnl / inv) * 100
}

/** Notional deployed at entry (entry × qty). For F&O this is contract notional, not margin. */
export function invested(t: { entry_price?: number; quantity?: number }): number | null {
  if (t.entry_price == null || t.quantity == null) return null
  return t.entry_price * t.quantity
}

export function exitReason(t: Trade): string | null {
  return t.exit_reason ?? t.reason ?? null
}

export function formatINR(v: number, opts: { sign?: boolean; decimals?: number } = {}): string {
  const { sign = false, decimals = 2 } = opts
  const s = Math.abs(v).toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
  const prefix = v < 0 ? '−' : sign ? '+' : ''
  return `${prefix}₹${s}`
}

export function formatDateTime(iso: string | undefined | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString('en-IN', {
    day: '2-digit', month: 'short',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  })
}

export function formatTime(iso: string | undefined | null): string {
  if (!iso) return '—'
  // ISO timestamps from the backend are IST wall-clock — slice avoids TZ surprises.
  const m = String(iso).match(/T(\d{2}:\d{2}:\d{2})/)
  return m ? m[1] : String(iso)
}

export function formatDuration(minutes: number | null | undefined): string {
  if (minutes == null || !Number.isFinite(minutes)) return '—'
  const m = Math.max(0, Math.round(minutes))
  if (m < 60) return `${m}m`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

/** Minutes between an ISO entry time and now (for live holding duration). */
export function minutesSince(iso: string | undefined | null): number | null {
  if (!iso) return null
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return null
  return (Date.now() - t) / 60000
}
