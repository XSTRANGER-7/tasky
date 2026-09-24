import { motion } from 'framer-motion'
import { CheckCircle2, CircleSlash, Cpu, GitCommit, Mail, Server, Timer } from 'lucide-react'
import type { ReactNode } from 'react'

import { useAdminSettings, useAiStats } from '@/api/admin'
import { PriorityBadge } from '@/components/incident-ui'
import { priorityColor } from '@/lib/incident'
import { formatDuration, timeAgo } from '@/lib/time'

import { AdminOnly } from './AdminOnly'

function Card({
  title,
  subtitle,
  children,
  index,
}: {
  title: string
  subtitle?: string
  children: ReactNode
  index: number
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, delay: index * 0.05, ease: [0.16, 1, 0.3, 1] }}
      className="rounded-card border border-border bg-surface p-5 shadow-[var(--shadow-elevated)]"
    >
      <h2 className="text-md font-medium">{title}</h2>
      {subtitle && <p className="mb-4 text-xs text-fg-muted">{subtitle}</p>}
      {children}
    </motion.section>
  )
}

const minutes = (m: number) => formatDuration(m * 60_000)

const FEATURE_LABELS: Record<string, string> = {
  triage: 'Triage',
  summary: 'Task summary',
  postmortem: 'Postmortem draft',
  nl_search: 'Plain-language search',
}

function AiUsage() {
  const { data } = useAiStats()
  const rows = Object.entries(data ?? {})
  return (
    <Card
      index={3}
      title="AI assistance"
      subtitle="Every suggestion is stored; accepting is how we learn whether it helps."
    >
      {rows.length === 0 ? (
        <p className="text-sm text-fg-muted">No AI suggestions yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-sm">
            <caption className="sr-only">AI usage by feature</caption>
            <thead>
              <tr className="text-left text-xs text-fg-muted">
                <th className="pb-2 font-normal">Feature</th>
                <th className="pb-2 text-right font-normal">Suggestions</th>
                <th className="pb-2 text-right font-normal">Accept rate</th>
                <th className="pb-2 text-right font-normal">Model / rules</th>
                <th className="pb-2 text-right font-normal">Avg latency</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([kind, r]) => (
                <tr key={kind} className="border-t border-border">
                  <td className="py-2">{FEATURE_LABELS[kind] ?? kind}</td>
                  <td className="py-2 text-right tabular-nums">{r.total}</td>
                  <td className="py-2 text-right tabular-nums">
                    {r.accept_rate === null ? '—' : `${Math.round(r.accept_rate * 100)}%`}
                    <span className="ml-1 text-xs text-fg-muted">
                      ({r.accepted}/{r.accepted + r.rejected})
                    </span>
                  </td>
                  <td className="py-2 text-right tabular-nums">
                    {r.llm} / {r.rules}
                  </td>
                  <td className="py-2 text-right tabular-nums">{r.avg_latency_ms} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

function Configuration() {
  const { data, isPending, isError } = useAdminSettings()

  if (isPending)
    return (
      <div className="grid gap-5 lg:grid-cols-2" aria-busy="true" aria-label="Loading settings">
        {[0, 1, 2].map((i) => (
          <div key={i} className="shimmer h-56 rounded-card" />
        ))}
      </div>
    )
  if (isError) return <p className="text-sm text-danger">Could not load the configuration.</p>

  const longest = Math.max(...data.sla.map((s) => s.resolution_minutes))

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <div className="lg:col-span-2">
        <Card
          index={0}
          title="SLA targets"
          subtitle="Clocks start when a task is created; a priority change recomputes them."
        >
          <ul className="space-y-4">
            {data.sla.map((s, i) => (
              <li key={s.priority} className="grid items-center gap-2 sm:grid-cols-[7rem_1fr_9rem]">
                <PriorityBadge priority={s.priority} />
                <div
                  className="relative h-6 rounded-control bg-canvas"
                  role="img"
                  aria-label={`${s.priority}: first response within ${minutes(s.response_minutes)}, resolution within ${minutes(s.resolution_minutes)}`}
                >
                  <motion.span
                    className="absolute inset-y-0 left-0 rounded-control opacity-25"
                    style={{ background: priorityColor[s.priority] }}
                    initial={{ width: 0 }}
                    animate={{ width: `${(s.resolution_minutes / longest) * 100}%` }}
                    transition={{ duration: 0.7, delay: 0.1 + i * 0.04, ease: [0.16, 1, 0.3, 1] }}
                  />
                  <motion.span
                    className="absolute inset-y-1 left-0 rounded-[4px]"
                    style={{ background: priorityColor[s.priority] }}
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.max(1.5, (s.response_minutes / longest) * 100)}%` }}
                    transition={{ duration: 0.7, delay: 0.2 + i * 0.04, ease: [0.16, 1, 0.3, 1] }}
                  />
                </div>
                <p className="text-xs text-fg-muted sm:text-right">
                  <span className="text-fg">{minutes(s.response_minutes)}</span> respond ·{' '}
                  <span className="text-fg">{minutes(s.resolution_minutes)}</span> resolve
                </p>
              </li>
            ))}
          </ul>
          <p className="mt-4 flex items-center gap-4 text-xs text-fg-muted">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-4 rounded-sm bg-fg-muted" /> First response
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-4 rounded-sm bg-fg-muted/30" /> Resolution
            </span>
          </p>
        </Card>
      </div>

      <Card index={1} title="Features" subtitle="Turned on or off by environment variables.">
        <ul className="divide-y divide-[color:var(--border)]">
          {data.flags.map((f) => (
            <li key={f.key} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
              {f.enabled ? (
                <CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0 text-status-resolved" />
              ) : (
                <CircleSlash aria-hidden className="mt-0.5 size-4 shrink-0 text-fg-muted" />
              )}
              <div className="min-w-0 flex-1">
                <p className="text-sm">{f.label}</p>
                <p className="text-xs text-fg-muted">{f.detail}</p>
              </div>
              <span
                className={`rounded-full px-2 text-xs ${f.enabled ? 'bg-status-resolved/10 text-status-resolved' : 'bg-canvas text-fg-muted'}`}
              >
                {f.enabled ? 'On' : 'Off'}
              </span>
            </li>
          ))}
        </ul>
      </Card>

      <Card index={2} title="Runtime" subtitle="What this deployment is running.">
        <dl className="space-y-3 text-sm">
          {[
            { icon: Server, label: 'Environment', value: data.environment },
            { icon: GitCommit, label: 'Version', value: `${data.version} (${data.git_sha})` },
            { icon: Mail, label: 'Email', value: `${data.email_provider} · ${data.email_from}` },
            {
              icon: Timer,
              label: 'SLA checker',
              value: `every ${formatDuration(data.sla_check_seconds * 1000)}`,
            },
            {
              icon: Cpu,
              label: 'Worker',
              value:
                data.worker.status === 'ok'
                  ? `running, heartbeat ${data.worker.last_beat_at ? timeAgo(data.worker.last_beat_at) : ''}`
                  : data.worker.status === 'stale'
                    ? 'not responding'
                    : 'never started',
            },
          ].map((row) => (
            <div key={row.label} className="grid grid-cols-[1.25rem_6.5rem_1fr] items-start gap-2">
              <row.icon aria-hidden className="mt-0.5 size-4 text-fg-muted" />
              <dt className="text-fg-muted">{row.label}</dt>
              <dd className="min-w-0 break-words font-mono text-xs leading-5">{row.value}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 rounded-control border border-border bg-canvas px-3 py-2 text-xs text-fg-muted">
          Settings are read-only here on purpose: changing one is a deploy, so every process agrees
          and the change is in version control.
        </p>
      </Card>

      <div className="lg:col-span-2">
        <AiUsage />
      </div>
    </div>
  )
}

export function ConfigurationPage() {
  return (
    <AdminOnly what="The configuration">
      <div className="space-y-5">
        <header>
          <h1 className="text-xl font-medium">Configuration</h1>
          <p className="text-sm text-fg-muted">SLA targets, features and runtime, as deployed.</p>
        </header>
        <Configuration />
      </div>
    </AdminOnly>
  )
}
