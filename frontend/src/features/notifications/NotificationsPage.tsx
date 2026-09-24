import { motion } from 'framer-motion'
import { Bell, CheckCheck, Mail, MailX } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import {
  useEmailLog,
  useMarkAllRead,
  useMarkRead,
  useNotifications,
  useUpdateMe,
  type EmailLogItem,
} from '@/api/notifications'
import { useAuth } from '@/auth/useAuth'
import { Switch } from '@/components/controls'
import { Button } from '@/components/ui'
import { formatDateTime, timeAgo } from '@/lib/time'
import { toastError } from '@/lib/toast'
import { useNow } from '@/lib/useNow'

import { DeliveryBadge } from './DeliveryBadge'
import { kindMeta, notificationHref } from './kinds'
import { NotificationItem } from './NotificationItem'

type Tab = 'inbox' | 'emails'

const TABS = [
  ['inbox', 'Inbox'],
  ['emails', 'Email log'],
] as const

export function EmailPreference() {
  const { user } = useAuth()
  const update = useUpdateMe()
  if (!user) return null
  const on = user.notify_email
  return (
    <section className="flex items-start gap-3 rounded-card border border-border bg-surface p-4 shadow-[var(--shadow-elevated)]">
      <span
        className={`flex size-9 shrink-0 items-center justify-center rounded-full ${on ? 'bg-accent/10 text-accent' : 'bg-canvas text-fg-muted'}`}
      >
        {on ? <Mail aria-hidden className="size-4" /> : <MailX aria-hidden className="size-4" />}
      </span>
      <div className="min-w-0 flex-1">
        <h2 className="text-sm font-medium">Email notifications</h2>
        <p className="mt-0.5 text-xs text-fg-muted">
          {on
            ? `Sent to ${user.email} for assignments, resolutions, comments, mentions and SLA breaches.`
            : 'Off: you will still see everything here, in the app.'}
        </p>
      </div>
      <Switch
        checked={on}
        label="Email notifications"
        disabled={update.isPending}
        onChange={(next) => {
          update.mutate(
            { notify_email: next },
            {
              onSuccess: () => {
                toast.success(next ? 'Email notifications on' : 'Email notifications off')
              },
              onError: (err) => {
                toastError(err, 'Could not update your preference')
              },
            },
          )
        }}
      />
    </section>
  )
}

function Inbox() {
  const [params, setParams] = useSearchParams()
  const unreadOnly = params.get('unread') === '1'
  const navigate = useNavigate()
  const { data, isPending, isError, refetch } = useNotifications(unreadOnly)
  const markRead = useMarkRead()
  const markAll = useMarkAllRead()
  const unread = data?.unread_count ?? 0

  return (
    <section className="rounded-card border border-border bg-surface shadow-[var(--shadow-elevated)]">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
        <div
          className="flex rounded-control bg-canvas p-0.5 text-xs"
          role="group"
          aria-label="Filter"
        >
          {(
            [
              [false, 'All'],
              [true, 'Unread'],
            ] as const
          ).map(([value, label]) => (
            <button
              key={label}
              type="button"
              aria-pressed={unreadOnly === value}
              onClick={() => {
                setParams(
                  (p) => {
                    if (value) p.set('unread', '1')
                    else p.delete('unread')
                    return p
                  },
                  { replace: true },
                )
              }}
              className={`rounded-[5px] px-2.5 py-1 transition-colors ${
                unreadOnly === value
                  ? 'bg-elevated text-fg shadow-sm'
                  : 'text-fg-muted hover:text-fg'
              }`}
            >
              {label}
              {value && unread > 0 && <span className="ml-1 text-accent">{unread}</span>}
            </button>
          ))}
        </div>
        <Button
          variant="ghost"
          className="ml-auto h-8 text-xs"
          disabled={!unread || markAll.isPending}
          onClick={() => {
            markAll.mutate(undefined, {
              onSuccess: () => {
                toast.success('All caught up')
              },
              onError: (err) => {
                toastError(err, 'Could not mark notifications as read')
              },
            })
          }}
        >
          <CheckCheck aria-hidden className="size-4" /> Mark all read
        </Button>
      </div>

      {isPending ? (
        <div className="space-y-2 p-3" aria-busy="true" aria-label="Loading notifications">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="shimmer h-16 rounded-control" />
          ))}
        </div>
      ) : isError ? (
        <div className="p-8 text-center text-sm">
          <p className="text-danger">Could not load notifications.</p>
          <Button variant="ghost" className="mt-2" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : data.items.length ? (
        <ul className="divide-y divide-[color:var(--border)] p-1">
          {data.items.map((n) => (
            <NotificationItem
              key={n.id}
              notification={n}
              onOpen={() => {
                if (!n.read_at) markRead.mutate(n.id)
                navigate(notificationHref(n))
              }}
            />
          ))}
        </ul>
      ) : (
        <div className="flex flex-col items-center gap-2 px-6 py-14 text-center">
          <span className="flex size-12 items-center justify-center rounded-full bg-canvas">
            <Bell aria-hidden className="size-5 text-fg-muted" />
          </span>
          <p className="font-medium">{unreadOnly ? 'No unread notifications' : 'Nothing yet'}</p>
          <p className="max-w-sm text-sm text-fg-muted">
            {unreadOnly
              ? 'You have read everything. Nice.'
              : 'Watch a task or get @mentioned in a comment and updates will land here.'}
          </p>
        </div>
      )}
    </section>
  )
}

function EmailRow({ email, now }: { email: EmailLogItem; now: number }) {
  const meta = kindMeta[email.kind]
  const Icon = meta.icon
  return (
    <tr className="border-t border-border">
      <td className="py-2.5 pl-4 pr-2">
        <span className={`flex size-7 items-center justify-center rounded-full ${meta.tone}`}>
          <Icon aria-hidden className="size-3.5" />
        </span>
      </td>
      <td className="max-w-0 py-2.5 pr-3">
        {email.incident_key ? (
          <Link
            to={`/tasks/${email.incident_key}`}
            className="block truncate text-sm hover:underline"
            title={email.subject}
          >
            {email.subject}
          </Link>
        ) : (
          <span className="block truncate text-sm" title={email.subject}>
            {email.subject}
          </span>
        )}
      </td>
      <td className="whitespace-nowrap py-2.5 pr-3">
        <DeliveryBadge status={email.status} attempts={email.attempts} />
      </td>
      <td
        className="whitespace-nowrap py-2.5 pr-4 text-right text-xs text-fg-muted"
        title={formatDateTime(email.sent_at ?? email.created_at)}
      >
        {timeAgo(email.sent_at ?? email.created_at, now)}
      </td>
    </tr>
  )
}

function EmailLog() {
  const { user } = useAuth()
  const now = useNow()
  const { data, isPending, isError } = useEmailLog()

  return (
    <section className="overflow-hidden rounded-card border border-border bg-surface shadow-[var(--shadow-elevated)]">
      <p className="px-4 py-3 text-xs text-fg-muted">
        Emails sent to <span className="text-fg">{user?.email}</span>. Delivery is retried with
        backoff; a failed email never blocks the in-app notification.
      </p>
      {isPending ? (
        <div className="space-y-2 p-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="shimmer h-10 rounded-control" />
          ))}
        </div>
      ) : isError ? (
        <p className="p-8 text-center text-sm text-danger">Could not load the email log.</p>
      ) : data.length ? (
        <table className="w-full table-fixed">
          <caption className="sr-only">Email log</caption>
          <colgroup>
            <col className="w-12" />
            <col />
            <col className="w-28" />
            <col className="w-24" />
          </colgroup>
          <thead className="sr-only">
            <tr>
              <th>Type</th>
              <th>Subject</th>
              <th>Status</th>
              <th>When</th>
            </tr>
          </thead>
          <tbody>
            {data.map((e) => (
              <EmailRow key={e.id} email={e} now={now} />
            ))}
          </tbody>
        </table>
      ) : (
        <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
          <Mail aria-hidden className="size-6 text-fg-muted" />
          <p className="text-sm text-fg-muted">No emails have been sent to you yet.</p>
        </div>
      )}
    </section>
  )
}

export function NotificationsPage() {
  const [params, setParams] = useSearchParams()
  const tab: Tab = params.get('tab') === 'emails' ? 'emails' : 'inbox'

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <header>
        <h1 className="text-xl font-medium">Notifications</h1>
        <p className="text-sm text-fg-muted">
          Updates on tasks assigned to you, created by you, or that you follow.
        </p>
      </header>

      <EmailPreference />

      <div role="tablist" aria-label="Notifications" className="flex gap-1 border-b border-border">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={tab === id}
            onClick={() => {
              setParams(id === 'inbox' ? {} : { tab: id }, { replace: true })
            }}
            className={`relative px-3 pb-2.5 text-sm ${tab === id ? 'text-fg' : 'text-fg-muted hover:text-fg'}`}
          >
            {label}
            {tab === id && (
              <motion.span
                layoutId="notifications-tab"
                className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent"
              />
            )}
          </button>
        ))}
      </div>

      <div role="tabpanel">{tab === 'inbox' ? <Inbox /> : <EmailLog />}</div>
    </div>
  )
}
