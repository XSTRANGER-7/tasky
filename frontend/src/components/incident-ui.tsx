import { AlertTriangle, Clock, PauseCircle } from 'lucide-react'

import type { Incident, Priority, Status } from '@/api/client'
import { priorityLabel, priorityTone, statusLabel, statusTone } from '@/lib/incident'
import { formatDuration } from '@/lib/time'

export function StatusPill({ status, className = '' }: { status: Status; className?: string }) {
  const tone = statusTone[status]
  return (
    <span
      className={`inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-full border px-2 text-xs font-medium transition-colors duration-base ${tone.ring} ${tone.text} ${className}`}
    >
      <span
        aria-hidden
        className={`size-1.5 rounded-full ${tone.dot} ${status === 'in_progress' ? 'animate-pulse-soft' : ''}`}
      />
      {statusLabel[status]}
    </span>
  )
}

const bars: Record<Priority, number> = { critical: 4, high: 3, medium: 2, low: 1 }

export function PriorityBadge({
  priority,
  compact = false,
}: {
  priority: Priority
  compact?: boolean
}) {
  const tone = priorityTone[priority]
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${tone.text}`}>
      <span aria-hidden className="flex h-3 items-end gap-[2px]">
        {[1, 2, 3, 4].map((n) => (
          <span
            key={n}
            className={`w-[3px] rounded-sm ${n <= bars[priority] ? tone.bg : 'bg-fg-muted/25'}`}
            style={{ height: `${n * 3}px` }}
          />
        ))}
      </span>
      {!compact && priorityLabel[priority]}
      {compact && <span className="sr-only">{priorityLabel[priority]}</span>}
    </span>
  )
}

type SlaIncident = Pick<Incident, 'status' | 'resolution_due_at' | 'sla' | 'resolved_at'>

/**
 * Resolution-SLA countdown: neutral when on track, amber under an hour, red with a slow
 * pulse once breached (icon too, so colour is never the only signal).
 */
export function SlaTimer({ incident, now }: { incident: SlaIncident; now: number }) {
  const due = new Date(incident.resolution_due_at).getTime()
  if (incident.sla.paused) {
    const late = incident.sla.resolution_breached
    return (
      <span
        className={`inline-flex items-center gap-1 text-xs ${late ? 'text-danger/80' : 'text-fg-muted'}`}
        title={late ? 'Resolved after the SLA deadline' : 'Resolved within SLA'}
      >
        <PauseCircle aria-hidden className="size-3.5" />
        {late ? 'Missed' : 'Met'}
      </span>
    )
  }
  const remaining = due - now
  const breached = remaining <= 0
  const atRisk = !breached && remaining <= 3_600_000
  return (
    <span
      className={`tabular inline-flex items-center gap-1 text-xs font-medium ${
        breached ? 'text-danger' : atRisk ? 'text-priority-medium' : 'text-fg-muted'
      }`}
      title={`Resolution due ${new Date(due).toLocaleString()}`}
    >
      {breached ? (
        <AlertTriangle aria-hidden className="animate-pulse-slow size-3.5" />
      ) : (
        <Clock aria-hidden className="size-3.5" />
      )}
      {breached ? `${formatDuration(remaining)} over` : formatDuration(remaining)}
    </span>
  )
}

export function Kbd({ children }: { children: string }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-border bg-canvas px-1 font-mono text-[10px] text-fg-muted">
      {children}
    </kbd>
  )
}
