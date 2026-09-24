import { motion } from 'framer-motion'
import { Fragment } from 'react'

import type { Incident } from '@/api/client'
import { useEvents } from '@/api/queries'
import { describeEvent, eventIcon } from '@/lib/events'
import { formatDateTime, timeAgo } from '@/lib/time'

/** Audit timeline: events fade in while the connector line draws top-to-bottom. */
/** "Today", "Yesterday", or a short date: the heading for a group of events. */
function dayLabel(iso: string, now = new Date()): string {
  const d = new Date(iso)
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const days = Math.round((start(now) - start(d)) / 86_400_000)
  if (days === 0) return 'Today'
  if (days === 1) return 'Yesterday'
  return d.toLocaleDateString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    ...(d.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }),
  })
}

export function Timeline({ incident }: { incident: Incident }) {
  const { data: events, isPending } = useEvents(incident.key)

  if (isPending) {
    return (
      <div className="space-y-3" aria-busy="true">
        {[0, 1, 2].map((i) => (
          <div key={i} className="shimmer h-10 rounded-control" />
        ))}
      </div>
    )
  }
  if (!events?.length) return <p className="py-4 text-sm text-fg-muted">No activity recorded.</p>

  return (
    <ol className="relative">
      <motion.span
        aria-hidden
        className="absolute bottom-3 left-[11px] top-3 w-px origin-top bg-[color:var(--border)]"
        initial={{ scaleY: 0 }}
        animate={{ scaleY: 1 }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      />
      {events.map((event, i) => {
        const Icon = eventIcon[event.event_type]
        const day = dayLabel(event.created_at)
        const newDay = i === 0 || dayLabel(events[i - 1]?.created_at ?? '') !== day
        const important = event.event_type === 'status_changed' || event.event_type === 'created'
        return (
          <Fragment key={event.id}>
            {newDay && (
              <motion.li
                aria-hidden
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: Math.min(i, 12) * 0.03 }}
                className="relative pb-3 pl-9 text-[11px] font-medium uppercase tracking-wide text-fg-muted/80"
              >
                {day}
              </motion.li>
            )}
            <motion.li
              className="relative flex gap-3 pb-4 last:pb-0"
              initial={{ opacity: 0, x: -4 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: Math.min(i, 12) * 0.03, duration: 0.2 }}
            >
              <span
                className={`relative z-10 flex size-6 shrink-0 items-center justify-center rounded-full border ${
                  important ? 'border-accent/40 bg-accent/10' : 'border-border bg-canvas'
                }`}
              >
                <Icon
                  aria-hidden
                  className={`size-3 ${important ? 'text-accent' : 'text-fg-muted'}`}
                />
              </span>
              <div className="min-w-0 pt-0.5 text-sm">
                <p>
                  <span className="font-medium">{event.actor?.name ?? 'System'}</span>{' '}
                  <span className="text-fg-muted">{describeEvent(event)}</span>{' '}
                  <time
                    dateTime={event.created_at}
                    title={formatDateTime(event.created_at)}
                    className="whitespace-nowrap text-xs text-fg-muted"
                  >
                    · {timeAgo(event.created_at)}
                  </time>
                </p>
                {event.note && (
                  <p className="mt-1 rounded-control border border-border bg-canvas px-2.5 py-1.5 text-sm text-fg">
                    {event.note}
                  </p>
                )}
                {event.event_type === 'updated' && event.field === 'title' && (
                  <p className="mt-0.5 truncate text-xs text-fg-muted">
                    <del>{String(event.old_value)}</del> → {String(event.new_value)}
                  </p>
                )}
                {event.event_type === 'commented' && (
                  <p className="mt-0.5 truncate text-xs text-fg-muted">
                    “{(event.new_value as { preview?: string } | null)?.preview ?? ''}”
                  </p>
                )}
              </div>
            </motion.li>
          </Fragment>
        )
      })}
    </ol>
  )
}
