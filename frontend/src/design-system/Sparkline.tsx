// Minimal SVG sparkline with a zero baseline — built for the day-P&L stream but
// generic over any numeric series. Colors by the sign of the latest value.

export function Sparkline({
  values,
  width = 120,
  height = 34,
}: {
  values: number[]
  width?: number
  height?: number
}) {
  if (values.length < 2) return null
  const min = Math.min(0, ...values)
  const max = Math.max(0, ...values)
  const span = max - min || 1
  const pad = 2
  const x = (i: number) => pad + (i / (values.length - 1)) * (width - 2 * pad)
  const y = (v: number) => pad + (1 - (v - min) / span) * (height - 2 * pad)

  const line = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const zeroY = y(0)
  const last = values[values.length - 1]
  const color = last >= 0 ? 'var(--profit)' : 'var(--loss)'
  const fillId = `spark-${last >= 0 ? 'p' : 'l'}`

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="mq-sparkline"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <line x1={pad} x2={width - pad} y1={zeroY} y2={zeroY} stroke="rgba(255,255,255,0.14)" strokeDasharray="2 3" />
      <polygon
        points={`${x(0).toFixed(1)},${zeroY} ${line} ${x(values.length - 1).toFixed(1)},${zeroY}`}
        fill={`url(#${fillId})`}
      />
      <polyline points={line} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx={x(values.length - 1)} cy={y(last)} r="2.2" fill={color} />
    </svg>
  )
}
