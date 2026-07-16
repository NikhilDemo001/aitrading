import type { ReactNode } from 'react'
import './StatCard.css'

export function StatCard({
  label,
  value,
  sub,
  icon,
  tone = 'neutral',
  right,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  icon?: ReactNode
  tone?: 'neutral' | 'profit' | 'loss' | 'accent'
  right?: ReactNode
}) {
  return (
    <div className="mq-statcard">
      {icon && <div className={`mq-statcard-icon mq-statcard-icon-${tone}`}>{icon}</div>}
      <div className="mq-statcard-body">
        <div className="mq-statcard-label">{label}</div>
        <div className={`mq-statcard-value mq-statcard-value-${tone} num`}>{value}</div>
        {sub && <div className="mq-statcard-sub">{sub}</div>}
      </div>
      {right && <div className="mq-statcard-right">{right}</div>}
    </div>
  )
}
