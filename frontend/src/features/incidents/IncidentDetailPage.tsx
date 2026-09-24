import { motion } from 'framer-motion'
import { ArrowLeft, Check, Copy, Pencil, RotateCcw, Trash2 } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { ApiError, type Incident, type Priority } from '@/api/client'
import {
  assigneesOf,
  useDeleteIncident,
  useIncident,
  useRestoreIncident,
  useSetAssignees,
  useUpdateIncident,
  useUsers,
} from '@/api/queries'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { PriorityBadge, SlaTimer } from '@/components/incident-ui'
import { useNow } from '@/lib/useNow'
import { Markdown } from '@/components/Markdown'
import { Menu, MenuCheckItem, MenuContent, MenuLabel, MenuTrigger } from '@/components/menu'
import { Avatar, Button } from '@/components/ui'
import { PRIORITIES, priorityLabel } from '@/lib/incident'
import { formatDateTime, formatDuration, timeAgo } from '@/lib/time'
import { toastError } from '@/lib/toast'
import { AiPanel } from '@/features/ai/AiPanel'

import { Conversation } from './Conversation'
import { AssigneeStack, AssigneesPicker } from './PeoplePicker'
import { StatusControl } from './StatusControl'
import { Timeline } from './Timeline'
import { PeopleOnIncident, WatchButton } from './WatchButton'
import { Attachments } from './Attachments'

// ---------------------------------------------------------------- title

function EditableTitle({ incident }: { incident: Incident }) {
  const update = useUpdateIncident(incident.key)
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(incident.title)
  useEffect(() => {
    if (!editing) setValue(incident.title)
  }, [incident.title, editing])

  const save = () => {
    const title = value.trim()
    setEditing(false)
    if (title === incident.title) return
    if (title.length < 3) {
      toast.error('Titles need at least 3 characters')
      return
    }
    update.mutate(
      { title },
      {
        onError: (err) => {
          toastError(err, 'Could not rename the task')
        },
      },
    )
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={value}
        maxLength={200}
        aria-label="Task title"
        onChange={(e) => {
          setValue(e.target.value)
        }}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === 'Enter') save()
          if (e.key === 'Escape') {
            setValue(incident.title)
            setEditing(false)
          }
        }}
        className="w-full rounded-control border border-accent bg-canvas px-2 py-1 text-xl font-medium outline-none"
      />
    )
  }
  return (
    <h1 className="group flex items-start gap-2 text-xl font-medium">
      <span className="min-w-0 break-words">{incident.title}</span>
      {incident.permissions.can_edit && (
        <button
          type="button"
          aria-label="Edit title"
          onClick={() => {
            setEditing(true)
          }}
          className="mt-1.5 rounded p-1 text-fg-muted opacity-0 transition-opacity hover:bg-elevated hover:text-fg focus:opacity-100 group-hover:opacity-100"
        >
          <Pencil className="size-4" />
        </button>
      )}
    </h1>
  )
}

// ---------------------------------------------------------------- description

function Description({ incident }: { incident: Incident }) {
  const update = useUpdateIncident(incident.key)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(incident.description)

  const save = () => {
    update.mutate(
      { description: draft },
      {
        onSuccess: () => {
          setEditing(false)
          toast.success('Description saved')
        },
        onError: (err) => {
          toastError(err, 'Could not save the description')
        },
      },
    )
  }

  return (
    <section className="rounded-card border border-border bg-surface p-5 shadow-[var(--shadow-elevated)]">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium text-fg-muted">Description</h2>
        {incident.permissions.can_edit && !editing && (
          <Button
            variant="ghost"
            className="h-7 text-xs"
            onClick={() => {
              setDraft(incident.description)
              setEditing(true)
            }}
          >
            <Pencil className="size-3.5" /> Edit
          </Button>
        )}
      </div>
      {editing ? (
        <div className="space-y-2">
          <textarea
            autoFocus
            rows={8}
            maxLength={20000}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value)
            }}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') save()
            }}
            aria-label="Description"
            className="w-full resize-y rounded-control border border-border bg-canvas px-3 py-2 font-mono text-[13px] outline-none focus:border-accent"
          />
          <div className="flex justify-end gap-2">
            <Button
              onClick={() => {
                setEditing(false)
              }}
            >
              Cancel
            </Button>
            <Button variant="primary" loading={update.isPending} onClick={save}>
              Save
            </Button>
          </div>
        </div>
      ) : incident.description.trim() ? (
        <Markdown>{incident.description}</Markdown>
      ) : (
        <p className="text-sm text-fg-muted">No description.</p>
      )}
    </section>
  )
}

// ---------------------------------------------------------------- properties

function Prop({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[6.5rem_1fr] items-center gap-2 py-2">
      <dt className="text-sm text-fg-muted">{label}</dt>
      <dd className="min-w-0 text-sm">{children}</dd>
    </div>
  )
}

function SlaBar({
  label,
  start,
  due,
  done,
  breached,
  now,
}: {
  label: string
  start: string
  due: string
  done: string | null
  breached: boolean
  now: number
}) {
  const s = new Date(start).getTime()
  const d = new Date(due).getTime()
  const end = done ? new Date(done).getTime() : now
  const pct = Math.min(100, Math.max(2, ((end - s) / Math.max(1, d - s)) * 100))
  const remaining = d - now
  const tone = breached
    ? 'bg-danger'
    : !done && remaining < 3_600_000
      ? 'bg-priority-medium'
      : done
        ? 'bg-status-resolved'
        : 'bg-accent'
  const text = done
    ? breached
      ? `Missed by ${formatDuration(end - d)}`
      : `Met with ${formatDuration(d - end)} to spare`
    : breached
      ? `${formatDuration(remaining)} overdue`
      : `${formatDuration(remaining)} left`
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-fg-muted">{label}</span>
        <span
          className={breached ? 'text-danger' : 'text-fg-muted'}
          title={`Due ${formatDateTime(due)}`}
        >
          {text}
        </span>
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-canvas"
        role="progressbar"
        aria-label={`${label} SLA`}
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <motion.div
          className={`h-full rounded-full ${tone}`}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        />
      </div>
    </div>
  )
}

function Properties({ incident }: { incident: Incident }) {
  const now = useNow()
  const { data: users } = useUsers()
  const setAssignees = useSetAssignees(incident.key, users)
  const assigned = assigneesOf(incident)
  const update = useUpdateIncident(incident.key)

  return (
    <aside className="space-y-4 lg:sticky lg:top-20">
      <section className="rounded-card border border-border bg-surface px-4 py-2 shadow-[var(--shadow-elevated)]">
        <dl className="divide-y divide-[color:var(--border)]">
          <Prop label="Assigned to">
            {incident.permissions.can_assign ? (
              <AssigneesPicker
                value={assigned}
                onChange={(people) => {
                  const before = new Set(assigned.map((p) => p.id))
                  const added = people.filter((p) => !before.has(p.id))
                  setAssignees.mutate(
                    { user_ids: people.map((p) => p.id) },
                    {
                      onSuccess: () => {
                        const first = added[0]
                        if (first) {
                          toast.success(`Assigned ${first.name}`, {
                            description: 'They were emailed about it.',
                          })
                        } else if (!people.length) {
                          toast.success('No one is assigned now')
                        }
                      },
                      onError: (err) => {
                        toastError(err, 'Could not change who this is assigned to')
                      },
                    },
                  )
                }}
              />
            ) : (
              <AssigneeStack people={assigned} />
            )}
            {incident.assigned_by && assigned.length > 0 && (
              <span className="mt-1 block text-xs text-fg-muted">
                Assigned by {incident.assigned_by.name}
              </span>
            )}
          </Prop>
          <Prop label="Priority">
            {incident.permissions.can_edit ? (
              <Menu>
                <MenuTrigger asChild>
                  <button
                    type="button"
                    className="rounded-control px-1.5 py-1 hover:bg-elevated"
                    aria-label={`Priority: ${priorityLabel[incident.priority]}. Change priority`}
                  >
                    <PriorityBadge priority={incident.priority} />
                  </button>
                </MenuTrigger>
                <MenuContent>
                  <MenuLabel>Priority (resets the SLA clock)</MenuLabel>
                  {PRIORITIES.map((p: Priority) => (
                    <MenuCheckItem
                      key={p}
                      checked={incident.priority === p}
                      onCheckedChange={() => {
                        if (p !== incident.priority)
                          update.mutate(
                            { priority: p },
                            {
                              onError: (err) => {
                                toastError(err, 'Could not change the priority')
                              },
                            },
                          )
                      }}
                    >
                      <PriorityBadge priority={p} />
                    </MenuCheckItem>
                  ))}
                </MenuContent>
              </Menu>
            ) : (
              <PriorityBadge priority={incident.priority} />
            )}
          </Prop>
          <Prop label="Created by">
            <span className="flex items-center gap-2">
              <Avatar user={incident.reporter} size={22} />{' '}
              <span className="truncate">{incident.reporter.name}</span>
            </span>
          </Prop>
          <Prop label="People">
            <PeopleOnIncident incident={incident} />
          </Prop>
          <Prop label="Category">
            {incident.category ?? <span className="text-fg-muted">—</span>}
          </Prop>
          <Prop label="Tags">
            {incident.tags.length ? (
              <span className="flex flex-wrap gap-1">
                {incident.tags.map((t) => (
                  <Link
                    key={t}
                    to={`/tasks?q=${encodeURIComponent(t)}`}
                    className="rounded-full bg-canvas px-2 text-xs text-fg-muted hover:text-fg"
                  >
                    {t}
                  </Link>
                ))}
              </span>
            ) : (
              <span className="text-fg-muted">—</span>
            )}
          </Prop>
          <Prop label="Created">
            <span title={formatDateTime(incident.created_at)}>
              {timeAgo(incident.created_at, now)}
            </span>
          </Prop>
          <Prop label="Updated">
            <span title={formatDateTime(incident.updated_at)}>
              {timeAgo(incident.updated_at, now)}
            </span>
          </Prop>
        </dl>
      </section>

      <section className="space-y-3 rounded-card border border-border bg-surface p-4 shadow-[var(--shadow-elevated)]">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium">SLA</h2>
          <SlaTimer incident={incident} now={now} />
        </div>
        <SlaBar
          label="First response"
          start={incident.created_at}
          due={incident.response_due_at}
          done={incident.first_response_at}
          breached={incident.sla.response_breached}
          now={now}
        />
        <SlaBar
          label="Resolution"
          start={incident.created_at}
          due={incident.resolution_due_at}
          done={incident.resolved_at}
          breached={incident.sla.resolution_breached}
          now={now}
        />
      </section>

      <Attachments incident={incident} />
    </aside>
  )
}

// ---------------------------------------------------------------- page

function CopyKey({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard.writeText(value).then(() => {
          setCopied(true)
          window.setTimeout(() => {
            setCopied(false)
          }, 1200)
        })
      }}
      className="inline-flex items-center gap-1 rounded px-1 font-mono text-sm text-fg-muted hover:bg-elevated hover:text-fg"
      aria-label={`Copy ${value}`}
    >
      {value}
      {copied ? (
        <Check className="size-3.5 text-status-resolved" />
      ) : (
        <Copy className="size-3.5 opacity-60" />
      )}
    </button>
  )
}

export function IncidentDetailPage() {
  const { ident = '' } = useParams()
  const navigate = useNavigate()
  const { data: incident, isPending, error } = useIncident(ident)
  const [tab, setTab] = useState<'conversation' | 'activity'>('conversation')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const remove = useDeleteIncident(ident)
  const restore = useRestoreIncident(ident)

  // Same component across incidents: start each one on its conversation.
  useEffect(() => {
    setTab('conversation')
  }, [ident])

  useEffect(() => {
    if (incident) document.title = `${incident.key} · ${incident.title} — Tasky`
    return () => {
      document.title = 'Tasky'
    }
  }, [incident])

  if (isPending) {
    return (
      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]" aria-busy="true">
        <div className="space-y-4">
          <div className="shimmer h-8 w-2/3 rounded" />
          <div className="shimmer h-40 rounded-card" />
        </div>
        <div className="shimmer h-80 rounded-card" />
      </div>
    )
  }
  if (error) {
    const notFound = error instanceof ApiError && error.status === 404
    return (
      <div className="flex flex-col items-center gap-3 py-20 text-center">
        <p className="text-lg font-medium">
          {notFound ? 'Task not found' : 'Could not load this task'}
        </p>
        <p className="text-sm text-fg-muted">
          {notFound ? `${ident} does not exist or was deleted.` : 'Try again in a moment.'}
        </p>
        <Button
          onClick={() => {
            navigate('/tasks')
          }}
        >
          Back to tasks
        </Button>
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      className="space-y-5"
    >
      <div className="flex items-center gap-2 text-sm text-fg-muted">
        <Link to="/tasks" className="inline-flex items-center gap-1 hover:text-fg">
          <ArrowLeft className="size-4" /> Tasks
        </Link>
        <span>/</span>
        <CopyKey value={incident.key} />
      </div>

      {incident.is_deleted && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-danger/40 bg-danger/10 px-4 py-3 text-sm">
          This task is in the recycle bin and read-only.
          <Button
            loading={restore.isPending}
            onClick={() => {
              restore.mutate(undefined, {
                onSuccess: () => toast.success(`${incident.key} restored`),
                onError: (e) => {
                  toastError(e)
                },
              })
            }}
          >
            <RotateCcw className="size-4" /> Restore
          </Button>
        </div>
      )}

      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1 space-y-2">
          <EditableTitle incident={incident} />
          <p className="text-sm text-fg-muted">
            Created by {incident.reporter.name} {timeAgo(incident.created_at)}
            {incident.category && <> · {incident.category}</>}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <WatchButton incident={incident} />
          <StatusControl incident={incident} />
          {incident.permissions.can_delete && !incident.is_deleted && (
            <Button
              variant="ghost"
              className="w-9 px-0 text-fg-muted hover:text-danger"
              aria-label="Delete task"
              onClick={() => {
                setConfirmDelete(true)
              }}
            >
              <Trash2 className="size-4" />
            </Button>
          )}
        </div>
      </header>

      {/* Up top, where people look first: summaries and postmortem drafts. */}
      <AiPanel incident={incident} />

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <div className="min-w-0 space-y-6">
          <Description incident={incident} />

          <section>
            <div
              role="tablist"
              aria-label="Task history"
              className="mb-4 flex gap-1 border-b border-border"
            >
              {(
                [
                  [
                    'conversation',
                    `Conversation${incident.comment_count ? ` (${incident.comment_count})` : ''}`,
                  ],
                  ['activity', 'Activity'],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  role="tab"
                  type="button"
                  aria-selected={tab === id}
                  onClick={() => {
                    setTab(id)
                  }}
                  className={`relative px-3 pb-2.5 text-sm ${tab === id ? 'text-fg' : 'text-fg-muted hover:text-fg'}`}
                >
                  {label}
                  {tab === id && (
                    <motion.span
                      layoutId="detail-tab"
                      className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent"
                    />
                  )}
                </button>
              ))}
            </div>
            <div role="tabpanel">
              {tab === 'conversation' ? (
                <Conversation incident={incident} />
              ) : (
                <Timeline incident={incident} />
              )}
            </div>
          </section>
        </div>

        <Properties incident={incident} />
      </div>

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title={`Delete ${incident.key}?`}
        description="It moves to the recycle bin: hidden from everyone, restorable by admins, and the audit trail is kept."
        confirmLabel="Delete"
        danger
        loading={remove.isPending}
        onConfirm={() => {
          remove.mutate(undefined, {
            onSuccess: () => {
              setConfirmDelete(false)
              toast.success(`${incident.key} deleted`)
              navigate('/tasks')
            },
            onError: (e) => {
              toastError(e)
            },
          })
        }}
      />
    </motion.div>
  )
}
