import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Panel } from '../../design-system/Panel'
import { Badge } from '../../design-system/Badge'
import { Button } from '../../design-system/Button'
import { usePositionsStore } from '../../lib/stores/usePositionsStore'
import { statusApi } from '../../lib/api/statusApi'
import { useTilt } from '../../lib/useTilt'
import type { Position } from '../../types/api'
import { isLongDirection, formatINR, formatTime, formatDuration, minutesSince } from '../../lib/tradeMath'
import './ActivePositionsGrid.css'

// Flash direction for the last live-price tick. The key counter remounts the flashing
// elements so the CSS animation restarts even on consecutive same-direction ticks.
function usePriceFlash(price: number | undefined) {
  const prev = useRef(price)
  const [flash, setFlash] = useState<{ dir: 'up' | 'down'; key: number } | null>(null)
  useEffect(() => {
    if (price != null && prev.current != null && price !== prev.current) {
      const dir = price > prev.current ? 'up' : 'down'
      setFlash((f) => ({ dir, key: (f?.key ?? 0) + 1 }))
    }
    prev.current = price
  }, [price])
  return flash
}

function Stat({ label, value, tone, flash }: {
  label: string
  value: ReactNode
  tone?: 'profit' | 'loss'
  flash?: { dir: 'up' | 'down'; key: number } | null
}) {
  return (
    <div className="mq-pos-stat">
      <span className="mq-pos-stat-label">{label}</span>
      <span
        key={flash?.key}
        className={`mq-pos-stat-value num ${tone ? `text-${tone}` : ''} ${flash ? `mq-flash-${flash.dir}` : ''}`}
      >
        {value}
      </span>
    </div>
  )
}

// Horizontal map of the trade: where the live price sits between stop-loss, entry and
// targets. Linear scale over all defined levels; red span covers entry→SL, green entry→T2
// (works for shorts too since the scale just flips).
function PriceLevelBar({ p }: { p: Position }) {
  const live = p.current_price ?? p.entry_price
  const levels: Array<{ label: string; value: number }> = [
    { label: 'SL', value: p.stop_loss },
    { label: 'E', value: p.entry_price },
    ...(p.target != null ? [{ label: 'T1', value: p.target }] : []),
    ...(p.target_2 != null ? [{ label: 'T2', value: p.target_2 }] : []),
  ]
  const values = [...levels.map((l) => l.value), live]
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min
  if (!Number.isFinite(span) || span <= 0) return null
  const pad = span * 0.04
  const pos = (v: number) => ((v - (min - pad)) / (span + 2 * pad)) * 100

  const farTarget = p.target_2 ?? p.target
  return (
    <div className="mq-pos-bar" aria-hidden="true">
      <div className="mq-pos-bar-track">
        <div
          className="mq-pos-bar-zone mq-pos-bar-zone-loss"
          style={{
            left: `${Math.min(pos(p.entry_price), pos(p.stop_loss))}%`,
            width: `${Math.abs(pos(p.entry_price) - pos(p.stop_loss))}%`,
          }}
        />
        {farTarget != null && (
          <div
            className="mq-pos-bar-zone mq-pos-bar-zone-profit"
            style={{
              left: `${Math.min(pos(p.entry_price), pos(farTarget))}%`,
              width: `${Math.abs(pos(p.entry_price) - pos(farTarget))}%`,
            }}
          />
        )}
        {levels.map((l) => (
          <div key={l.label} className="mq-pos-bar-mark" style={{ left: `${pos(l.value)}%` }} />
        ))}
        <div className="mq-pos-bar-live" style={{ left: `${pos(live)}%` }} />
      </div>
      <div className="mq-pos-bar-labels">
        {levels.map((l) => (
          <span key={l.label} className="mq-pos-bar-label" style={{ left: `${pos(l.value)}%` }}>
            {l.label}
          </span>
        ))}
      </div>
    </div>
  )
}

function PositionCard({ p }: { p: Position }) {
  const tiltRef = useTilt<HTMLDivElement>(5, 4)
  const long = isLongDirection(p.direction)
  const pnl = p.pnl ?? 0
  const tone = pnl >= 0 ? 'profit' : 'loss'
  const live = p.current_price
  const flash = usePriceFlash(live)

  const invested = p.entry_price * p.quantity
  const currentValue = live != null ? live * p.quantity : null
  const pnlPctValue = invested !== 0 ? (pnl / invested) * 100 : null
  const holding = formatDuration(minutesSince(p.entry_time))

  return (
    <div ref={tiltRef} className={`mq-position-card mq-position-card-${long ? 'long' : 'short'}`}>
      <div className="mq-position-hdr">
        <span className="mq-position-sym">{p.symbol}</span>
        <Badge tone={long ? 'profit' : 'loss'}>{p.direction}</Badge>
        {p.strategy ? <Badge tone="accent">{p.strategy}</Badge> : null}
        {p.is_fno ? <Badge tone="warn">{p.contract || 'F&O'}</Badge> : null}
        {p.t1_hit ? <Badge tone="profit">T1 ✓</Badge> : null}
      </div>

      <div className="mq-position-pnl-row">
        <span key={flash ? `p${flash.key}` : 'p'} className={`mq-position-pnl num text-${tone} ${flash ? `mq-flash-${flash.dir}` : ''}`}>
          {formatINR(pnl, { sign: true })}
        </span>
        {pnlPctValue != null && (
          <span className={`mq-position-pnl-pct num text-${tone}`}>
            {pnlPctValue >= 0 ? '+' : ''}{pnlPctValue.toFixed(2)}%
          </span>
        )}
      </div>

      <PriceLevelBar p={p} />

      <div className="mq-pos-stats">
        <Stat label="Entry" value={p.entry_price?.toFixed(2)} />
        <Stat label="Live" value={live != null ? live.toFixed(2) : '—'} flash={flash} />
        <Stat label="Qty" value={p.quantity} />
        <Stat label="Invested" value={formatINR(invested, { decimals: 0 })} />
        <Stat label="Value now" value={currentValue != null ? formatINR(currentValue, { decimals: 0 }) : '—'}
          tone={currentValue != null ? tone : undefined} />
        <Stat label="Stop loss" value={p.stop_loss?.toFixed(2)} tone="loss" />
        <Stat label="Target 1" value={p.target != null ? p.target.toFixed(2) : '—'} tone="profit" />
        <Stat label="Target 2" value={p.target_2 != null ? p.target_2.toFixed(2) : '—'} tone="profit" />
        {p.trailing_high != null && <Stat label="Trail high" value={p.trailing_high.toFixed(2)} />}
        {p.trailing_low != null && <Stat label="Trail low" value={p.trailing_low.toFixed(2)} />}
        {p.atr_at_entry != null && <Stat label="ATR entry" value={p.atr_at_entry.toFixed(2)} />}
        {p.mae != null && <Stat label="MAE" value={formatINR(p.mae)} tone="loss" />}
        {p.mfe != null && <Stat label="MFE" value={formatINR(p.mfe)} tone="profit" />}
        {p.confluence_score != null && <Stat label="Confluence" value={p.confluence_score} />}
        {p.regime && <Stat label="Regime" value={p.regime} />}
        {p.htf_trend && <Stat label="HTF trend" value={p.htf_trend} />}
        <Stat label="Entered" value={formatTime(p.entry_time)} />
        <Stat label="Holding" value={holding} />
      </div>

      <Button
        variant="ghost"
        onClick={() => statusApi.closePosition(p.symbol).catch(console.error)}
      >
        Close
      </Button>
    </div>
  )
}

export function ActivePositionsGrid() {
  const positions = usePositionsStore((s) => s.positions)

  return (
    <Panel title={`Active Positions · ${positions.length}`} padded={false}>
      {positions.length === 0 ? (
        <div className="mq-positions-empty text-faint">No open positions.</div>
      ) : (
        <div className="mq-positions-grid">
          {positions.map((p) => (
            <PositionCard key={p.symbol} p={p} />
          ))}
        </div>
      )}
    </Panel>
  )
}
