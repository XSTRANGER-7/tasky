/**
 * Two hand-rolled SVG charts: a KPI sparkline and the priority donut. Both draw on
 * mount (spec 12.3: line left-to-right, donut clockwise) and collapse to their final
 * state under reduced motion via MotionConfig.
 */
import { motion } from 'framer-motion'
import { useId, useState } from 'react'

/** 14-point trend line with a soft area; the last point is marked. */
export function Sparkline({
  values,
  color,
  label,
}: {
  values: number[]
  color: string
  label: string
}) {
  const id = useId()
  const w = 96
  const h = 28
  if (values.length < 2) return null
  const max = Math.max(...values)
  const min = Math.min(...values)
  const span = max - min || 1
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w
    const y = h - 3 - ((v - min) / span) * (h - 6)
    return [x, y] as const
  })
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const area = `${line} L${w},${h} L0,${h} Z`
  const last = pts[pts.length - 1] ?? [w, h]
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
      className="h-7 w-24 min-w-0 shrink overflow-visible"
    >
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.25} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <motion.path
        d={area}
        fill={`url(#${id})`}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.7, delay: 0.3 }}
      />
      <motion.path
        d={line}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
      />
      <motion.circle
        cx={last[0]}
        cy={last[1]}
        r={3}
        fill={color}
        stroke="rgb(var(--bg-surface))"
        strokeWidth={1.5}
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ delay: 0.65, type: 'spring', stiffness: 500, damping: 18 }}
      />
    </svg>
  )
}

export interface Slice {
  key: string
  label: string
  value: number
  color: string
}

/** Donut with a 2 px surface gap between slices; hovering a slice (or its legend row
 *  elsewhere) highlights it and the centre shows its count. */
export function Donut({
  slices,
  size = 132,
  active,
  onActive,
  centerLabel,
}: {
  slices: Slice[]
  size?: number
  active: string | null
  onActive: (key: string | null) => void
  centerLabel: string
}) {
  const [hover, setHover] = useState<string | null>(null)
  const current = active ?? hover
  const total = slices.reduce((n, s) => n + s.value, 0)
  const stroke = 16
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const gap = total > 0 && slices.filter((s) => s.value > 0).length > 1 ? 2 : 0

  let offset = 0
  const arcs = slices.map((s, i) => {
    const frac = total ? s.value / total : 0
    const len = Math.max(0, frac * c - gap)
    const arc = { ...s, len, offset, i }
    offset += frac * c
    return arc
  })
  const focused = slices.find((s) => s.key === current)

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg
        viewBox={`0 0 ${size} ${size}`}
        width={size}
        height={size}
        role="img"
        aria-label={`${centerLabel}: ${slices.map((s) => `${s.label} ${s.value}`).join(', ')}`}
        className="-rotate-90"
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="rgb(var(--bg-canvas))"
          strokeWidth={stroke}
        />
        {arcs.map((a) =>
          a.len > 0 ? (
            <motion.circle
              key={a.key}
              cx={size / 2}
              cy={size / 2}
              r={r}
              fill="none"
              stroke={a.color}
              strokeWidth={current === a.key ? stroke + 4 : stroke}
              strokeDasharray={`${a.len} ${c}`}
              strokeDashoffset={-a.offset}
              initial={{ opacity: 0, strokeDasharray: `0 ${c}` }}
              animate={{
                opacity: current && current !== a.key ? 0.35 : 1,
                strokeDasharray: `${a.len} ${c}`,
              }}
              transition={{
                strokeDasharray: { duration: 0.7, delay: a.i * 0.08, ease: [0.16, 1, 0.3, 1] },
                opacity: { duration: 0.15 },
              }}
              onMouseEnter={() => {
                setHover(a.key)
                onActive(a.key)
              }}
              onMouseLeave={() => {
                setHover(null)
                onActive(null)
              }}
              className="cursor-pointer transition-[stroke-width] duration-fast"
            >
              <title>{`${a.label}: ${a.value}`}</title>
            </motion.circle>
          ) : null,
        )}
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <motion.span
          key={focused?.key ?? 'total'}
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.15 }}
          className="text-xl font-medium tabular-nums"
        >
          {focused ? focused.value : total}
        </motion.span>
        <span className="text-[11px] text-fg-muted">{focused ? focused.label : centerLabel}</span>
      </div>
    </div>
  )
}
