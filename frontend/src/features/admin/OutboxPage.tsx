import { motion } from 'framer-motion'
import {
  CheckCircle2,
  Clock,
  Cpu,
  Inbox,
  RotateCcw,
  ShieldAlert,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import {
  useOutbox,
  useRetryOutbox,
  type OutboxRow,
  type OutboxStatus,
  type WorkerStatus,
} from '@/api/notifications'
import { useTeam } from '@/team/useTeam'
import { AnimatedNumber } from '@/components/AnimatedNumber'
import { Avatar, Button } from '@/components/ui'
import { DeliveryBadge } from '@/features/notifications/DeliveryBadge'
import { kindMeta } from '@/features/notifications/kinds'
import { formatDateTime, formatDuration, timeAgo } from '@/lib/time'
import { toastError } from '@/lib/toast'
import { useNow } from '@/lib/useNow'

const FILTERS: { value: OutboxStatus | null; label: string }[] = [
  { value: null, label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'failed', label: 'Failed' },
  { value: 'sent', label: 'Sent' },
]

function Tile({
  label,
  value,
  icon: Icon,
  tone,
  active,
  onClick,
  index,
}: {
  label: string
  value: number
  icon: LucideIcon
  tone: string
  active: boolean
  onClick: () => void
  index: number
}) {
  return (
    <motion.button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, delay: index * 0.04, ease: [0.16, 1, 0.3, 1] }}
      className={`rounded-card border bg-surface p-4 text-left shadow-[var(--shadow-elevated)] transition-colors hover:border-fg-muted/40 ${
        active ? 'border-accent/60 ring-1 ring-accent/30' : 'border-border'
      }`}
    >
      <span className="flex items-center justify-between text-sm text-fg-muted">
        {label}
        <Icon aria-hidden className={`size-4 ${tone}`} />
      </span>
      <span className="mt-2 block text-xl font-medium">
        <AnimatedNumber value={value} />
      </span>
    </motion.button>
  )
}

function WorkerCard({ worker }: { worker: WorkerStatus }) {
  const ok = worker.status === 'ok'
  const text =
    worker.status === 'ok'
      ? 'Running'
      : worker.status === 'stale'
        ? 'Not responding'
        : 'Never started'
  return (
    <section
      className={`flex items-center gap-3 rounded-card border p-4 shadow-[var(--shadow-elevated)] ${
        ok ? 'border-border bg-surface' : 'border-danger/40 bg-danger/[0.06]'
      }`}
      aria-label="Notification worker"
    >
      <span
        className={`relative flex size-9 shrink-0 items-center justify-center rounded-full ${ok ? 'bg-status-resolved/10 text-status-resolved' : 'bg-danger/10 text-danger'}`}
      >
        <Cpu aria-hidden className="size-4" />
        {ok && (
          <span className="absolute right-0.5 top-0.5 size-2 animate-ping rounded-full bg-status-resolved/70" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">Worker: {text}</p>
        <p className="text-xs text-fg-muted">
          {worker.last_beat_at
            ? `Last heartbeat ${timeAgo(worker.last_beat_at)} (${formatDateTime(worker.last_beat_at)})`
            : 'No heartbeat recorded. Start it with `make worker`.'}
          {!ok && worker.status === 'stale' && ' - emails are queuing but not being sent.'}
        </p>
      </div>
    </section>
  )
}

function Row({ row, now }: { row: OutboxRow; now: number }) {
  const retry = useRetryOutbox()
  const meta = kindMeta[row.kind]
  const Icon = meta.icon
  const due = new Date(row.next_attempt_at).getTime() - now
  return (
    <tr className="border-t border-border align-top">
      <td className="py-3 pl-4 pr-3">
        <span className="flex items-center gap-2">
          <Avatar user={row.recipient} size={24} />
          <span className="min-w-0">
            <span className="block truncate text-sm">{row.recipient.name}</span>
            <span className="block truncate text-xs text-fg-muted">{row.recipient_email}</span>
          </span>
        </span>
      </td>
      <td className="max-w-0 py-3 pr-3">
        <span className="flex items-center gap-2">
          <span
            className={`flex size-6 shrink-0 items-center justify-center rounded-full ${meta.tone}`}
          >
            <Icon aria-hidden className="size-3" />
          </span>
          <Link
            to={`/tasks/${row.incident_key}`}
            className="truncate text-sm hover:underline"
            title={row.subject}
          >
            {row.subject}
          </Link>
        </span>
        {row.last_error && (
          <p
            className="mt-1 truncate pl-8 font-mono text-[11px] text-danger"
            title={row.last_error}
          >
            {row.last_error}
          </p>
        )}
      </td>
      <td className="whitespace-nowrap py-3 pr-3">
        <DeliveryBadge status={row.status} attempts={row.attempts} />
        {row.status === 'pending' && row.attempts > 0 && due > 0 && (
          <p className="mt-1 text-[11px] text-fg-muted">next in {formatDuration(due)}</p>
        )}
      </td>
      <td
        className="whitespace-nowrap py-3 pr-3 text-xs text-fg-muted"
        title={formatDateTime(row.sent_at ?? row.created_at)}
      >
        {timeAgo(row.sent_at ?? row.created_at, now)}
      </td>
      <td className="py-3 pr-4 text-right">
        {row.status === 'failed' && (
          <Button
            variant="ghost"
            className="h-7 px-2 text-xs"
            disabled={retry.isPending}
            onClick={() => {
              retry.mutate(row.id, {
                onSuccess: () => {
                  toast.success(`Queued again for ${row.recipient.name}`)
                },
                onError: (err) => {
                  toastError(err, 'Could not retry this email')
                },
              })
            }}
          >
            <RotateCcw aria-hidden className="size-3.5" /> Retry
          </Button>
        )}
      </td>
    </tr>
  )
}

export function OutboxPage() {
  const { canManage: isAdmin, active } = useTeam()
  const [params, setParams] = useSearchParams()
  const raw = params.get('status')
  const status = FILTERS.some((f) => f.value === raw) ? (raw as OutboxStatus) : null
  const now = useNow(15_000)
  const { data, isPending, isError } = useOutbox(status, isAdmin)

  if (!isAdmin) {
    return (
      <div className="mx-auto flex max-w-md flex-col items-center gap-2 py-20 text-center">
        <ShieldAlert aria-hidden className="size-8 text-fg-muted" />
        <h1 className="text-md font-medium">Team admins only</h1>
        <p className="text-sm text-fg-muted">
          The email outbox is visible to the admins of {active?.name ?? 'this team'}.
        </p>
      </div>
    )
  }

  const setStatus = (value: OutboxStatus | null) => {
    setParams(value ? { status: value } : {}, { replace: true })
  }
  const counts = data?.counts ?? {}
  const total = (counts.pending ?? 0) + (counts.sent ?? 0) + (counts.failed ?? 0)

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-medium">Email outbox</h1>
        <p className="text-sm text-fg-muted">
          Email about {active?.name ?? 'this team'}: written here in the same transaction as the
          change that caused it, then delivered by the worker with retries.
        </p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          label="All"
          value={total}
          icon={Inbox}
          tone=""
          active={!status}
          onClick={() => {
            setStatus(null)
          }}
          index={0}
        />
        <Tile
          label="Pending"
          value={counts.pending ?? 0}
          icon={Clock}
          tone="text-priority-medium"
          active={status === 'pending'}
          onClick={() => {
            setStatus('pending')
          }}
          index={1}
        />
        <Tile
          label="Failed"
          value={counts.failed ?? 0}
          icon={XCircle}
          tone="text-danger"
          active={status === 'failed'}
          onClick={() => {
            setStatus('failed')
          }}
          index={2}
        />
        <Tile
          label="Sent"
          value={counts.sent ?? 0}
          icon={CheckCircle2}
          tone="text-status-resolved"
          active={status === 'sent'}
          onClick={() => {
            setStatus('sent')
          }}
          index={3}
        />
      </div>

      {data && <WorkerCard worker={data.worker} />}

      <section className="overflow-hidden rounded-card border border-border bg-surface shadow-[var(--shadow-elevated)]">
        <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
          <div
            className="flex rounded-control bg-canvas p-0.5 text-xs"
            role="group"
            aria-label="Status"
          >
            {FILTERS.map((f) => (
              <button
                key={f.label}
                type="button"
                aria-pressed={status === f.value}
                onClick={() => {
                  setStatus(f.value)
                }}
                className={`rounded-[5px] px-2.5 py-1 transition-colors ${
                  status === f.value
                    ? 'bg-elevated text-fg shadow-sm'
                    : 'text-fg-muted hover:text-fg'
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
          <span className="ml-auto text-xs text-fg-muted">Refreshes every 10 s</span>
        </div>
        {isPending ? (
          <div className="space-y-2 p-3" aria-busy="true" aria-label="Loading outbox">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="shimmer h-12 rounded-control" />
            ))}
          </div>
        ) : isError ? (
          <p className="p-8 text-center text-sm text-danger">Could not load the outbox.</p>
        ) : data.items.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] table-fixed">
              <caption className="sr-only">Outbox</caption>
              <colgroup>
                <col className="w-56" />
                <col />
                <col className="w-32" />
                <col className="w-24" />
                <col className="w-24" />
              </colgroup>
              <thead>
                <tr className="text-left text-xs text-fg-muted">
                  <th className="py-2 pl-4 pr-3 font-normal">Recipient</th>
                  <th className="py-2 pr-3 font-normal">Subject</th>
                  <th className="py-2 pr-3 font-normal">Status</th>
                  <th className="py-2 pr-3 font-normal">When</th>
                  <th className="py-2 pr-4 font-normal">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <Row key={row.id} row={row} now={now} />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 px-6 py-14 text-center">
            <Inbox aria-hidden className="size-6 text-fg-muted" />
            <p className="text-sm text-fg-muted">
              {status ? `No ${status} emails.` : 'The outbox is empty.'}
            </p>
          </div>
        )}
      </section>
    </div>
  )
}
