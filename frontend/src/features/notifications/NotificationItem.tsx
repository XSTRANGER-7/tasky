import type { AppNotification } from '@/api/notifications'
import { Avatar } from '@/components/ui'
import { formatDateTime, timeAgo } from '@/lib/time'
import { useNow } from '@/lib/useNow'

import { kindMeta } from './kinds'

export function NotificationItem({
  notification: n,
  onOpen,
  compact = false,
}: {
  notification: AppNotification
  onOpen: () => void
  compact?: boolean
}) {
  const now = useNow()
  const meta = kindMeta[n.kind]
  const Icon = meta.icon
  const unread = !n.read_at

  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className={`group relative flex w-full gap-3 rounded-control text-left transition-colors hover:bg-canvas focus-visible:bg-canvas ${
          compact ? 'px-2.5 py-2.5' : 'px-4 py-3.5'
        }`}
      >
        <span className="relative mt-0.5 shrink-0">
          {n.actor ? (
            <Avatar user={n.actor} size={compact ? 28 : 32} />
          ) : (
            <span
              className={`flex items-center justify-center rounded-full ${meta.tone} ${compact ? 'size-7' : 'size-8'}`}
            >
              <Icon aria-hidden className="size-4" />
            </span>
          )}
          {n.actor && (
            <span
              className={`absolute -bottom-1 -right-1 flex size-4 items-center justify-center rounded-full ring-2 ring-elevated ${meta.tone}`}
            >
              <Icon aria-hidden className="size-2.5" />
            </span>
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span
              className={`min-w-0 flex-1 truncate text-sm ${unread ? 'font-medium text-fg' : 'text-fg-muted'}`}
            >
              {n.title}
            </span>
            <time
              dateTime={n.created_at}
              title={formatDateTime(n.created_at)}
              className="shrink-0 text-xs text-fg-muted"
            >
              {timeAgo(n.created_at, now)}
            </time>
          </span>
          {n.body && (
            <span
              className={`mt-0.5 block text-xs text-fg-muted ${compact ? 'line-clamp-2' : 'line-clamp-3'}`}
            >
              {n.body}
            </span>
          )}
          <span className="mt-1 flex items-center gap-2 text-[11px] text-fg-muted">
            {n.incident_key && (
              <>
                <span className="font-mono">{n.incident_key}</span>
                <span aria-hidden>·</span>
              </>
            )}
            <span>{meta.label}</span>
          </span>
        </span>
        {unread && (
          <span className="mt-2 size-2 shrink-0 rounded-full bg-accent">
            <span className="sr-only">Unread</span>
          </span>
        )}
      </button>
    </li>
  )
}
