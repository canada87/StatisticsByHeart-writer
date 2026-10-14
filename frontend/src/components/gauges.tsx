import { useId } from 'react'

interface RingProps {
  /** 0..1 (clamped). */
  fraction: number
  size?: number
  stroke?: number
  color?: string
  /** Text alternative: the number is conveyed in words, the ring is decorative. */
  label: string
  children?: React.ReactNode
}

/** Radial gauge (SVG). The arc draws in with a transform-free dash-offset transition. */
export function Ring({ fraction, size = 148, stroke = 10, color = 'var(--accent-c)', label, children }: RingProps) {
  const id = useId()
  const f = Math.max(0, Math.min(1, fraction))
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
        <defs>
          <filter id={`${id}-glow`}>
            <feDropShadow dx="0" dy="0" stdDeviation="2.5" floodColor={color} floodOpacity="0.55" />
          </filter>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-border)" strokeWidth={stroke} />
        {/* tick marks every 10% */}
        {Array.from({ length: 10 }, (_, i) => {
          const a = (i / 10) * 2 * Math.PI - Math.PI / 2
          const r1 = r + stroke / 2 + 2
          const r2 = r1 + 3
          return (
            <line
              key={i}
              x1={size / 2 + r1 * Math.cos(a)}
              y1={size / 2 + r1 * Math.sin(a)}
              x2={size / 2 + r2 * Math.cos(a)}
              y2={size / 2 + r2 * Math.sin(a)}
              stroke="var(--color-border-control)"
              strokeWidth={1}
            />
          )
        })}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="butt"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - f)}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          filter={`url(#${id}-glow)`}
          style={{ transition: 'stroke-dashoffset 600ms var(--ease-hud)' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">{children}</div>
    </div>
  )
}

interface SparklineProps {
  values: (number | null)[]
  width?: number
  height?: number
  color?: string
}

/** Tiny trend line. Purely decorative (aria-hidden): the parent carries the text equivalent. */
export function Sparkline({ values, width = 120, height = 32, color = 'var(--accent-c)' }: SparklineProps) {
  const nums = values.filter((v): v is number => v !== null)
  if (nums.length < 2) return null
  const lo = Math.min(...nums)
  const hi = Math.max(...nums)
  const span = hi - lo || 1
  const step = width / (values.length - 1)
  let d = ''
  values.forEach((v, i) => {
    if (v === null) return
    const x = i * step
    const y = height - 3 - ((v - lo) / span) * (height - 6)
    d += `${d ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`
  })
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <path d={d} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  )
}
