import * as Popover from '@radix-ui/react-popover'
import { Bell, CheckCheck } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { useMarkAllRead, useMarkRead, useNotifications } from '@/api/notifications'
import { useLiveState } from '@/lib/live'
import { toastError } from '@/lib/toast'

import { notificationHref } from './kinds'
import { NotificationItem } from './NotificationItem'

const PREVIEW = 8

export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const { data, isPending } = useNotifications()
  const markRead = useMarkRead()
  const markAll = useMarkAllRead()
  const unread = data?.unread_count ?? 0

  // Replay the swing on every new notification (keyed remount restarts the CSS animation).
  const { notificationPulse } = useLiveState()
  const firstPulse = useRef(notificationPulse)
  const swinging = notificationPulse !== firstPulse.current

  const label = unread ? `Notifications, ${unread} unread` : 'Notifications'

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          aria-label={label}
          title={label}
          className="relative inline-flex size-9 items-center justify-center rounded-control text-fg-muted transition-colors hover:bg-elevated hover:text-fg data-[state=open]:bg-elevated data-[state=open]:text-fg"
        >
          <Bell
            key={notificationPulse}
            aria-hidden
            className={`size-4 ${swinging ? 'bell-swing' : ''}`}
          />
          {unread > 0 && (
            <span
              aria-hidden
              className="absolute right-1 top-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-semibold leading-none text-white ring-2 ring-canvas"
            >
              {unread > 99 ? '99+' : unread}
            </span>
          )}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          collisionPadding={12}
          aria-label="Notifications"
          className="popover-content z-50 flex max-h-[min(560px,80vh)] w-[min(400px,calc(100vw-24px))] flex-col overflow-hidden rounded-card border border-border bg-elevated shadow-[var(--shadow-elevated)]"
        >
          <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border px-3">
            <h2 className="text-sm font-medium">Notifications</h2>
            {unread > 0 && (
              <span className="rounded-full bg-accent/10 px-1.5 text-xs text-accent">
                {unread} new
              </span>
            )}
            <button
              type="button"
              disabled={!unread || markAll.isPending}
              onClick={() => {
                markAll.mutate(undefined, {
                  onError: (err) => {
                    toastError(err, 'Could not mark notifications as read')
                  },
                })
              }}
              className="ml-auto inline-flex items-center gap-1 rounded-control px-2 py-1 text-xs text-fg-muted hover:bg-canvas hover:text-fg disabled:pointer-events-none disabled:opacity-40"
            >
              <CheckCheck aria-hidden className="size-3.5" /> Mark all read
            </button>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto p-1">
            {isPending ? (
              <div className="space-y-1 p-1" aria-busy="true">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="shimmer h-14 rounded-control" />
                ))}
              </div>
            ) : data?.items.length ? (
              <ul>
                {data.items.slice(0, PREVIEW).map((n) => (
                  <NotificationItem
                    key={n.id}
                    notification={n}
                    compact
                    onOpen={() => {
                      if (!n.read_at) markRead.mutate(n.id)
                      setOpen(false)
                      navigate(notificationHref(n))
                    }}
                  />
                ))}
              </ul>
            ) : (
              <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
                <span className="flex size-10 items-center justify-center rounded-full bg-canvas">
                  <Bell aria-hidden className="size-5 text-fg-muted" />
                </span>
                <p className="text-sm font-medium">You are all caught up</p>
                <p className="text-xs text-fg-muted">
                  Assignments, mentions and SLA breaches will show up here.
                </p>
              </div>
            )}
          </div>

          <footer className="shrink-0 border-t border-border p-1">
            <Link
              to="/notifications"
              onClick={() => {
                setOpen(false)
              }}
              className="flex h-8 items-center justify-center rounded-control text-xs text-fg-muted hover:bg-canvas hover:text-fg"
            >
              View all notifications
            </Link>
          </footer>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
