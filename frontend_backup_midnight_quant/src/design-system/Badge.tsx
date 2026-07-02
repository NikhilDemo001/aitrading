import type { ReactNode } from 'react'
import './Badge.css'

export type BadgeTone = 'neutral' | 'accent' | 'profit' | 'loss' | 'warn' | 'info'

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: BadgeTone }) {
  return <span className={`mq-badge mq-badge-${tone}`}>{children}</span>
}

export function StatusDot({ tone = 'neutral', pulse = false }: { tone?: BadgeTone; pulse?: boolean }) {
  return <span className={`mq-dot mq-dot-${tone} ${pulse ? 'mq-dot-pulse' : ''}`} />
}
