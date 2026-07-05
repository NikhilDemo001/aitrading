import type { ReactNode } from 'react'
import { Modal } from '../../design-system/Modal'
import { Badge } from '../../design-system/Badge'
import { TradeChart } from './TradeChart'
import type { Trade } from '../../types/api'
import {
  isLongDirection, rMultiple, pnlPct, invested, exitReason,
  formatINR, formatDateTime, formatDuration,
} from '../../lib/tradeMath'
import './TradeDetailModal.css'

// Every backend field rendered somewhere. Fields covered by the explicit sections below are
// listed here; anything NOT in this set (including fields the backend adds in the future)
// falls through to the "All other fields" section, so no detail can ever be hidden.
const EXPLICIT_FIELDS = new Set([
  'symbol', 'direction', 'strategy', 'contract', 'is_fno', 'is_shadow_trade', 'lot_size',
  'pnl', 'pnl_pct', 'quantity', 'entry_price', 'entry_time', 'exit_price', 'exit_time',
  'holding_minutes', 'reason', 'exit_reason', 'order_id',
  'stop_loss', 'target_1', 'target_2', 't1_hit', 'atr_at_entry', 'mae', 'mfe',
  'regime', 'htf_trend', 'confluence_score',
  'trigger_level_source', 'trigger_level_price', 'trigger_level_score',
  'market_context',
])

function fmtValue(v: unknown): string {
  if (v == null || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(4).replace(/0+$/, '').replace(/\.$/, '')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function Row({ label, value, tone }: { label: string; value: ReactNode; tone?: 'profit' | 'loss' }) {
  return (
    <div className="mq-tdm-row">
      <span className="mq-tdm-label">{label}</span>
      <span className={`mq-tdm-value num ${tone ? `text-${tone}` : ''}`}>{value ?? '—'}</span>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mq-tdm-section">
      <h4 className="mq-tdm-section-title">{title}</h4>
      <div className="mq-tdm-grid">{children}</div>
    </section>
  )
}

export function TradeDetailModal({ trade, onClose }: { trade: Trade; onClose: () => void }) {
  const long = isLongDirection(trade.direction)
  const pnl = trade.pnl ?? 0
  const pnlTone = pnl >= 0 ? 'profit' : 'loss'
  const pct = pnlPct(trade)
  const r = rMultiple(trade)
  const inv = invested(trade)
  const returned = inv != null && trade.pnl != null ? inv + trade.pnl : null
  const riskPerShare =
    trade.entry_price != null && trade.stop_loss != null ? Math.abs(trade.entry_price - trade.stop_loss) : null
  const totalRisked = riskPerShare != null && trade.quantity != null ? riskPerShare * trade.quantity : null
  const marketContext = (trade.market_context ?? {}) as Record<string, unknown>
  const extraFields = Object.entries(trade).filter(([k]) => !EXPLICIT_FIELDS.has(k))

  return (
    <Modal
      onClose={onClose}
      className="mq-tdm"
      title={
        <>
          <span className="mq-tdm-sym">{trade.symbol}</span>
          <Badge tone={long ? 'profit' : 'loss'}>{trade.direction}</Badge>
          {trade.strategy ? <Badge tone="accent">{trade.strategy}</Badge> : null}
          {trade.is_fno ? <Badge tone="warn">{trade.contract || 'F&O'}</Badge> : null}
          {trade.is_shadow_trade ? <Badge tone="info">SHADOW</Badge> : null}
        </>
      }
    >
      <div className={`mq-tdm-hero mq-tdm-hero-${pnlTone}`}>
        <div className={`mq-tdm-pnl num text-${pnlTone}`}>{formatINR(pnl, { sign: true })}</div>
        <div className="mq-tdm-hero-stats">
          <Row label="P&L %" tone={pct != null && pct < 0 ? 'loss' : 'profit'}
            value={pct != null ? `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%` : '—'} />
          <Row label="R-multiple" tone={r != null && r < 0 ? 'loss' : 'profit'}
            value={r != null ? `${r.toFixed(2)}R` : '—'} />
          <Row label="Invested" value={inv != null ? formatINR(inv) : '—'} />
          <Row label="Returned" value={returned != null ? formatINR(returned) : '—'} />
        </div>
      </div>

      <TradeChart trade={trade} />

      <Section title="Execution">
        <Row label="Entry price" value={trade.entry_price != null ? formatINR(trade.entry_price) : '—'} />
        <Row label="Entry time" value={formatDateTime(trade.entry_time)} />
        <Row label="Exit price" value={trade.exit_price != null ? formatINR(trade.exit_price) : '—'} />
        <Row label="Exit time" value={formatDateTime(trade.exit_time)} />
        <Row label="Quantity" value={trade.quantity ?? '—'} />
        <Row label="Holding time" value={formatDuration(trade.holding_minutes)} />
        <Row label="Exit reason" value={exitReason(trade) ?? '—'} />
        {trade.lot_size != null && <Row label="Lot size" value={trade.lot_size} />}
        {trade.order_id != null && <Row label="Order ID" value={String(trade.order_id)} />}
      </Section>

      <Section title="Risk">
        <Row label="Stop loss" value={trade.stop_loss != null ? formatINR(trade.stop_loss) : '—'} />
        <Row label="Target 1" value={trade.target_1 != null ? formatINR(trade.target_1) : '—'} />
        <Row label="Target 2" value={trade.target_2 != null ? formatINR(trade.target_2) : '—'} />
        <Row label="T1 hit" value={trade.t1_hit != null ? (trade.t1_hit ? 'Yes' : 'No') : '—'} />
        <Row label="Risk / share" value={riskPerShare != null ? formatINR(riskPerShare) : '—'} />
        <Row label="Total risked" value={totalRisked != null ? formatINR(totalRisked) : '—'} />
        <Row label="ATR at entry" value={trade.atr_at_entry != null ? formatINR(trade.atr_at_entry) : '—'} />
        <Row label="MAE (worst)" tone="loss" value={trade.mae != null ? formatINR(trade.mae) : '—'} />
        <Row label="MFE (best)" tone="profit" value={trade.mfe != null ? formatINR(trade.mfe) : '—'} />
      </Section>

      <Section title="Signal context">
        <Row label="Regime" value={trade.regime ?? '—'} />
        <Row label="HTF trend" value={trade.htf_trend ?? '—'} />
        <Row label="Confluence score" value={trade.confluence_score ?? '—'} />
        <Row label="Trigger source" value={trade.trigger_level_source ?? '—'} />
        <Row label="Trigger price" value={trade.trigger_level_price != null ? formatINR(trade.trigger_level_price) : '—'} />
        <Row label="Trigger score" value={trade.trigger_level_score ?? '—'} />
      </Section>

      {Object.keys(marketContext).length > 0 && (
        <Section title="Market context at entry">
          {Object.entries(marketContext).map(([k, v]) => (
            <Row key={k} label={k.replaceAll('_', ' ')} value={fmtValue(v)} />
          ))}
        </Section>
      )}

      {extraFields.length > 0 && (
        <Section title="All other fields">
          {extraFields.map(([k, v]) => (
            <Row key={k} label={k.replaceAll('_', ' ')} value={fmtValue(v)} />
          ))}
        </Section>
      )}
    </Modal>
  )
}
