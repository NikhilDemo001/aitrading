import './ProgressRing.css'

export function ProgressRing({
  pct,
  size = 96,
  tone = 'warn',
  label,
  sub,
}: {
  pct: number
  size?: number
  tone?: 'profit' | 'warn' | 'loss'
  label: string
  sub?: string
}) {
  const clamped = Math.min(100, Math.max(0, pct))
  const stroke = 8
  const r = (size - stroke) / 2
  const circ = 2 * Math.PI * r
  const offset = circ * (1 - clamped / 100)
  return (
    <div className={`mq-ring mq-ring-${tone}`} style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} className="mq-ring-track" strokeWidth={stroke} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          className="mq-ring-bar"
          strokeWidth={stroke}
          fill="none"
          strokeDasharray={circ}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <div className="mq-ring-center">
        <span className="mq-ring-label num">{label}</span>
        {sub && <span className="mq-ring-sub">{sub}</span>}
      </div>
    </div>
  )
}
