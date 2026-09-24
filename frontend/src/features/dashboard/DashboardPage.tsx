import { motion } from 'framer-motion'
import { AlertTriangle, CheckCircle2, CircleDot, Clock, UserX, type LucideIcon } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  Area,
  AreaChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { ActivityItem, DashboardSummary, Priority } from '@/api/client'
import { useDashboard } from '@/api/queries'
import { AnimatedNumber } from '@/components/AnimatedNumber'
import { PriorityBadge } from '@/components/incident-ui'
import { Avatar } from '@/components/ui'
import { describeEvent, eventIcon } from '@/lib/events'
import { PRIORITIES, priorityColor, priorityLabel } from '@/lib/incident'
import { formatHours, timeAgo } from '@/lib/time'

import { Donut, Sparkline } from './mini-charts'

const CREATED = 'rgb(var(--chart-created))'
const RESOLVED = 'rgb(var(--chart-resolved))'

function Card({
  title,
  subtitle,
  children,
  className = '',
  action,
}: {
  title: string
  subtitle?: string
  children: ReactNode
  className?: string
  action?: ReactNode
}) {
  return (
    <section
      className={`rounded-card border border-border bg-surface p-5 shadow-[var(--shadow-elevated)] ${className}`}
    >
      <header className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-md font-medium">{title}</h2>
          {subtitle && <p className="text-xs text-fg-muted">{subtitle}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  )
}

// ---------------------------------------------------------------- KPI tiles

function Kpi({
  label,
  value,
  format,
  icon: Icon,
  to,
  tone = 'neutral',
  hint,
  index,
  spark,
}: {
  label: string
  value: number
  format?: (n: number) => string
  icon: LucideIcon
  to: string
  tone?: 'neutral' | 'danger'
  hint?: string
  index: number
  /** 14-day series drawn as a sparkline (spec 11.4). */
  spark?: { values: number[]; color: string; label: string }
}) {
  const danger = tone === 'danger' && value > 0
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, delay: index * 0.04, ease: [0.16, 1, 0.3, 1] }}
    >
      <Link
        to={to}
        className={`group block rounded-card border bg-surface p-4 shadow-[var(--shadow-elevated)] transition-colors hover:border-fg-muted/40 ${
          danger ? 'border-danger/40 bg-danger/[0.06]' : 'border-border'
        }`}
      >
        <div className="flex items-center justify-between text-sm text-fg-muted">
          {label}
          <Icon aria-hidden className={`size-4 ${danger ? 'text-danger' : ''}`} />
        </div>
        <div className="mt-2 flex items-end justify-between gap-2">
          <span className="text-xl font-medium">
            <AnimatedNumber value={value} {...(format ? { format } : {})} />
          </span>
          {spark && (
            <span className="flex min-w-0 flex-1 justify-end pb-1">
              <Sparkline {...spark} />
            </span>
          )}
        </div>
        {hint && <p className="mt-0.5 text-xs text-fg-muted">{hint}</p>}
      </Link>
    </motion.div>
  )
}

// ---------------------------------------------------------------- trend chart

function TrendTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: { value: number; dataKey: string }[]
  label?: string
}) {
  if (!active || !payload?.length || !label) return null
  const get = (key: string) => payload.find((p) => p.dataKey === key)?.value ?? 0
  return (
    <div className="rounded-control border border-border bg-elevated px-3 py-2 text-xs shadow-[var(--shadow-elevated)]">
      <p className="mb-1 font-medium text-fg">
        {new Date(label).toLocaleDateString(undefined, {
          weekday: 'short',
          month: 'short',
          day: 'numeric',
        })}
      </p>
      <p className="flex items-center gap-2 text-fg-muted">
        <span className="size-2 rounded-full" style={{ background: CREATED }} /> Created
        <span className="tabular ml-auto pl-4 text-fg">{get('created')}</span>
      </p>
      <p className="flex items-center gap-2 text-fg-muted">
        <span className="size-2 rounded-full" style={{ background: RESOLVED }} /> Resolved
        <span className="tabular ml-auto pl-4 text-fg">{get('resolved')}</span>
      </p>
    </div>
  )
}

function EndLabel(props: {
  x?: number
  y?: number
  index?: number
  value?: number
  count: number
  name: string
  color: string
}) {
  if (props.index !== props.count - 1 || props.x === undefined || props.y === undefined) return null
  return (
    <g>
      <circle
        cx={props.x}
        cy={props.y}
        r={4}
        fill={props.color}
        stroke="rgb(var(--bg-surface))"
        strokeWidth={2}
      />
      <text
        x={props.x - 8}
        y={props.y - 10}
        textAnchor="end"
        className="fill-[rgb(var(--text-muted))] text-[11px]"
      >
        {props.name} {props.value}
      </text>
    </g>
  )
}

function TrendChart({ data }: { data: DashboardSummary['trend_14d'] }) {
  const total = data.reduce((acc, p) => ({ c: acc.c + p.created, r: acc.r + p.resolved }), {
    c: 0,
    r: 0,
  })
  return (
    <Card
      title="Created vs resolved"
      subtitle={`Last 14 days · ${total.c} created, ${total.r} resolved`}
      className="lg:col-span-2"
      action={
        <div className="flex items-center gap-3 text-xs text-fg-muted" aria-label="Legend">
          <span className="flex items-center gap-1.5">
            <span className="h-0.5 w-3 rounded" style={{ background: CREATED }} /> Created
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-0.5 w-3 rounded" style={{ background: RESOLVED }} /> Resolved
          </span>
        </div>
      }
    >
      <div
        className="h-56"
        role="img"
        aria-label={`Created versus resolved tasks per day for 14 days: ${total.c} created, ${total.r} resolved.`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 20, right: 12, bottom: 0, left: -24 }}>
            <defs>
              <linearGradient id="fill-created" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={CREATED} stopOpacity={0.25} />
                <stop offset="100%" stopColor={CREATED} stopOpacity={0} />
              </linearGradient>
              <linearGradient id="fill-resolved" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={RESOLVED} stopOpacity={0.2} />
                <stop offset="100%" stopColor={RESOLVED} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis
              dataKey="date"
              tickLine={false}
              axisLine={false}
              tick={{ fill: 'rgb(var(--text-muted))', fontSize: 11 }}
              tickFormatter={(d: string) =>
                new Date(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
              }
              interval="preserveStartEnd"
              minTickGap={24}
            />
            <YAxis
              allowDecimals={false}
              tickLine={false}
              axisLine={false}
              tick={{ fill: 'rgb(var(--text-muted))', fontSize: 11 }}
            />
            <Tooltip
              content={<TrendTooltip />}
              cursor={{ stroke: 'rgb(var(--text-muted) / 0.5)', strokeDasharray: '3 3' }}
            />
            <Area
              type="linear"
              dataKey="created"
              stroke={CREATED}
              strokeWidth={2}
              fill="url(#fill-created)"
              animationDuration={700}
              activeDot={{ r: 4, strokeWidth: 2, stroke: 'rgb(var(--bg-surface))' }}
            >
              <LabelList
                content={<EndLabel count={data.length} name="Created" color={CREATED} />}
              />
            </Area>
            <Area
              type="linear"
              dataKey="resolved"
              stroke={RESOLVED}
              strokeWidth={2}
              fill="url(#fill-resolved)"
              animationDuration={700}
              activeDot={{ r: 4, strokeWidth: 2, stroke: 'rgb(var(--bg-surface))' }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------- bars

function BarRow({
  label,
  value,
  max,
  color,
  to,
  children,
}: {
  label: string
  value: number
  max: number
  color: string
  to: string
  children?: ReactNode
}) {
  const pct = max > 0 ? (value / max) * 100 : 0
  return (
    <Link
      to={to}
      title={`${label}: ${value} open`}
      className="group grid grid-cols-[8rem_1fr_2rem] items-center gap-3 rounded-control px-1 py-1 hover:bg-elevated"
    >
      <span className="flex min-w-0 items-center gap-2 truncate text-sm">{children ?? label}</span>
      <span className="h-2 overflow-hidden rounded-full bg-canvas">
        <motion.span
          className="block h-full rounded-full"
          style={{ background: color }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        />
      </span>
      <span className="tabular text-right text-sm text-fg-muted group-hover:text-fg">{value}</span>
    </Link>
  )
}

function PriorityCard({ byPriority }: { byPriority: Record<string, number> }) {
  const [active, setActive] = useState<string | null>(null)
  const max = Math.max(1, ...PRIORITIES.map((p) => byPriority[p] ?? 0))
  const total = PRIORITIES.reduce((n, p) => n + (byPriority[p] ?? 0), 0)
  return (
    <Card title="Open work by priority" subtitle={`${total} open or in progress`}>
      <div className="flex justify-center pb-4">
        <Donut
          centerLabel="open"
          active={active}
          onActive={setActive}
          slices={PRIORITIES.map((p: Priority) => ({
            key: p,
            label: priorityLabel[p],
            value: byPriority[p] ?? 0,
            color: priorityColor[p],
          }))}
        />
      </div>
      <div className="space-y-1">
        {PRIORITIES.map((p: Priority) => (
          <div
            key={p}
            onMouseEnter={() => {
              setActive(p)
            }}
            onMouseLeave={() => {
              setActive(null)
            }}
            className={`rounded-control transition-opacity duration-fast ${active && active !== p ? 'opacity-50' : ''}`}
          >
            <BarRow
              label={priorityLabel[p]}
              value={byPriority[p] ?? 0}
              max={max}
              color={priorityColor[p]}
              to={`/tasks?priority=${p}&status=open&status=in_progress`}
            >
              <PriorityBadge priority={p} />
            </BarRow>
          </div>
        ))}
      </div>
    </Card>
  )
}

function AssigneeCard({ rows }: { rows: DashboardSummary['open_by_assignee'] }) {
  const max = Math.max(1, ...rows.map((r) => r.count))
  return (
    <Card title="Open work by person" subtitle="Who is assigned what right now">
      {rows.length === 0 ? (
        <p className="py-6 text-center text-sm text-fg-muted">No open work. Enjoy the quiet.</p>
      ) : (
        <div className="space-y-1">
          {rows.map((row) => (
            <BarRow
              key={row.user?.id ?? 'unassigned'}
              label={row.user?.name ?? 'Not assigned'}
              value={row.count}
              max={max}
              color={row.user ? 'rgb(var(--accent))' : 'rgb(var(--text-muted) / 0.6)'}
              to={`/tasks?status=open&status=in_progress&assignee=${row.user?.id ?? 'none'}`}
            >
              {row.user ? (
                <Avatar user={row.user} size={20} />
              ) : (
                <UserX aria-hidden className="size-4 text-fg-muted" />
              )}
              <span className="truncate">{row.user?.name ?? 'Not assigned'}</span>
            </BarRow>
          ))}
        </div>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------- activity

function ActivityCard({ items }: { items: ActivityItem[] }) {
  return (
    <Card title="Recent activity" subtitle="Every change is in the audit log">
      {items.length === 0 ? (
        <p className="py-6 text-center text-sm text-fg-muted">Nothing has happened yet.</p>
      ) : (
        <ol className="space-y-3">
          {items.map((item, i) => {
            const Icon = eventIcon[item.event_type]
            return (
              <motion.li
                key={item.id}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i, 10) * 0.03, duration: 0.2 }}
                className="flex gap-3"
              >
                <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border border-border bg-canvas">
                  <Icon aria-hidden className="size-3 text-fg-muted" />
                </span>
                <div className="min-w-0 text-sm">
                  <p className="truncate">
                    <span className="font-medium">{item.actor?.name ?? 'System'}</span>{' '}
                    <span className="text-fg-muted">{describeEvent(item)}</span>
                  </p>
                  <Link
                    to={`/tasks/${item.incident_key}`}
                    className="flex min-w-0 gap-2 text-xs text-fg-muted hover:text-fg"
                  >
                    <span className="font-mono">{item.incident_key}</span>
                    <span className="truncate">{item.incident_title}</span>
                    <span className="ml-auto shrink-0">{timeAgo(item.created_at)}</span>
                  </Link>
                </div>
              </motion.li>
            )
          })}
        </ol>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------- page

function Skeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading dashboard">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="shimmer h-24 rounded-card" />
        ))}
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="shimmer h-72 rounded-card lg:col-span-2" />
        <div className="shimmer h-72 rounded-card" />
      </div>
    </div>
  )
}

export function DashboardPage() {
  const { data, isPending, isError, refetch } = useDashboard()
  // Backlog trend: open work at the end of each day, walked back from today's count.
  const sparks = useMemo(() => {
    if (!data) return null
    const trend = data.trend_14d
    const openNow = (data.counts.open ?? 0) + (data.counts.in_progress ?? 0)
    const backlog: number[] = []
    let level = openNow
    for (let i = trend.length - 1; i >= 0; i--) {
      backlog.unshift(level)
      const p = trend[i]
      if (p) level = Math.max(0, level - p.created + p.resolved)
    }
    return {
      backlog,
      created: trend.map((p) => p.created),
      resolved: trend.map((p) => p.resolved),
    }
  }, [data])

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-medium">Dashboard</h1>
          <p className="text-sm text-fg-muted">
            {data ? `Updated ${timeAgo(data.generated_at)}` : 'The state of every task, live'}
          </p>
        </div>
      </header>

      {isPending ? (
        <Skeleton />
      ) : isError ? (
        <div className="rounded-card border border-danger/40 bg-danger/10 p-6 text-sm">
          Could not load the dashboard.{' '}
          <button type="button" className="text-accent underline" onClick={() => void refetch()}>
            Try again
          </button>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Kpi
              index={0}
              label="Open"
              value={data.counts.open ?? 0}
              icon={CircleDot}
              to="/tasks?status=open"
              {...(sparks
                ? {
                    spark: {
                      values: sparks.backlog,
                      color: 'rgb(var(--accent))',
                      label: 'Open backlog over the last 14 days',
                    },
                  }
                : {})}
            />
            <Kpi
              index={1}
              label="In progress"
              value={data.counts.in_progress ?? 0}
              icon={Clock}
              to="/tasks?status=in_progress"
              {...(sparks
                ? {
                    spark: {
                      values: sparks.created,
                      color: CREATED,
                      label: 'Tasks created per day, last 14 days',
                    },
                  }
                : {})}
            />
            <Kpi
              index={2}
              label="SLA breached"
              value={data.sla.breached}
              icon={AlertTriangle}
              tone="danger"
              to="/tasks?view=breached"
              hint={
                data.sla.at_risk_next_hour
                  ? `${data.sla.at_risk_next_hour} more at risk within the hour`
                  : 'Nothing else at risk this hour'
              }
            />
            <Kpi
              index={3}
              label="MTTR (7 days)"
              value={data.mttr_hours.last_7d ?? 0}
              format={(n) => (data.mttr_hours.last_7d === null ? '—' : formatHours(n))}
              icon={CheckCircle2}
              to="/tasks?status=resolved&status=closed"
              {...(sparks
                ? {
                    spark: {
                      values: sparks.resolved,
                      color: RESOLVED,
                      label: 'Tasks resolved per day, last 14 days',
                    },
                  }
                : {})}
              hint={`30-day: ${formatHours(data.mttr_hours.last_30d)}`}
            />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <TrendChart data={data.trend_14d} />
            <PriorityCard byPriority={data.by_priority} />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <AssigneeCard rows={data.open_by_assignee} />
            <ActivityCard items={data.recent_activity} />
          </div>
        </>
      )}
    </div>
  )
}
