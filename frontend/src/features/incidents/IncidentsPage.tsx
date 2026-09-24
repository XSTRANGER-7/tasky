import { AnimatePresence, motion } from 'framer-motion'
import {
  ArrowDownUp,
  ChevronDown,
  CircleDot,
  Eye,
  EyeOff,
  Inbox,
  Loader2,
  MessageSquare,
  Plus,
  Search,
  Sparkles,
  UserPlus,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import type { Incident, Priority, Status, UserPublic } from '@/api/client'
import { filtersToSearch, nlSearch, useAiEnabled } from '@/api/ai'
import { useWatch } from '@/api/notifications'
import { assigneesOf, type IncidentFilters, useAssign, useIncidents, useUsers } from '@/api/queries'
import { isTyping, useShell } from '@/app/shell/ShellContext'
import { useAuth } from '@/auth/useAuth'
import { useTeam } from '@/team/useTeam'
import { Kbd, PriorityBadge, SlaTimer, StatusPill } from '@/components/incident-ui'
import { useNow } from '@/lib/useNow'
import {
  Menu,
  MenuCheckItem,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
} from '@/components/menu'
import { Button } from '@/components/ui'
import { PRIORITIES, priorityLabel, priorityTone, STATUSES, statusLabel } from '@/lib/incident'
import { timeAgo } from '@/lib/time'
import { toastError } from '@/lib/toast'

import { AssigneeStack, PeoplePicker } from './PeoplePicker'
import { StatusControl } from './StatusControl'

// ---------------------------------------------------------------- URL <-> filters

const VIEWS = [
  { id: 'all', label: 'All' },
  { id: 'mine', label: 'My work' },
  { id: 'watching', label: 'Watching' },
  { id: 'unassigned', label: 'Not assigned' },
  { id: 'breached', label: 'SLA breached' },
] as const
type View = (typeof VIEWS)[number]['id']

const SORTS = [
  { value: '-created_at', label: 'Newest first' },
  { value: 'created_at', label: 'Oldest first' },
  { value: '-updated_at', label: 'Recently updated' },
  { value: '-priority,-created_at', label: 'Priority' },
  { value: 'resolution_due_at', label: 'SLA due soonest' },
] as const

function useUrlFilters() {
  const [params, setParams] = useSearchParams()
  const view = (params.get('view') ?? 'all') as View
  const status = params.getAll('status') as Status[]
  const priority = params.getAll('priority') as Priority[]
  const assignee = params.getAll('assignee')
  const q = params.get('q') ?? ''
  const sort = params.get('sort') ?? ''
  const slaParam = params.get('sla')
  const sla =
    slaParam === 'breached' || slaParam === 'at_risk' || slaParam === 'on_track'
      ? slaParam
      : undefined

  const filters: IncidentFilters = useMemo(() => {
    const f: IncidentFilters = { status, priority, assignee, q, sort, ...(sla ? { sla } : {}) }
    if (view === 'mine') {
      f.assignee = ['me']
      if (!status.length) f.status = ['open', 'in_progress']
    } else if (view === 'unassigned') {
      f.assignee = ['none']
      if (!status.length) f.status = ['open', 'in_progress']
    } else if (view === 'breached') {
      f.sla = 'breached'
    } else if (view === 'watching') {
      f.watching = true
    }
    return f
    // eslint-disable-next-line react-hooks/exhaustive-deps -- params identity is the dependency
  }, [params.toString()])

  const update = (patch: Record<string, string | string[] | null>) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [key, value] of Object.entries(patch)) {
          next.delete(key)
          if (Array.isArray(value))
            value.forEach((v) => {
              next.append(key, v)
            })
          else if (value) next.set(key, value)
        }
        return next
      },
      { replace: true },
    )
  }

  return { view, status, priority, assignee, q, sort, sla, filters, update }
}

// ---------------------------------------------------------------- filter bar

function Chip({ active, children }: { active: boolean; children: ReactNode }) {
  return (
    <span
      className={`inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-sm transition-colors ${
        active
          ? 'border-accent/50 bg-accent/10 text-fg'
          : 'border-border text-fg-muted hover:border-fg-muted/40 hover:text-fg'
      }`}
    >
      {children}
      <ChevronDown aria-hidden className="size-3.5 opacity-70" />
    </span>
  )
}

function MultiFilter<T extends string>({
  label,
  options,
  selected,
  render,
  onChange,
}: {
  label: string
  options: T[]
  selected: T[]
  render: (v: T) => string
  onChange: (next: T[]) => void
}) {
  const summary =
    selected.length === 0
      ? label
      : selected.length === 1
        ? `${label}: ${render(selected[0] as T)}`
        : `${label}: ${selected.length}`
  return (
    <Menu>
      <MenuTrigger asChild>
        <button type="button" aria-label={`Filter by ${label.toLowerCase()}`}>
          <Chip active={selected.length > 0}>{summary}</Chip>
        </button>
      </MenuTrigger>
      <MenuContent>
        <MenuLabel>{label}</MenuLabel>
        {options.map((opt) => (
          <MenuCheckItem
            key={opt}
            checked={selected.includes(opt)}
            onCheckedChange={(on) => {
              onChange(on ? [...selected, opt] : selected.filter((s) => s !== opt))
            }}
          >
            {render(opt)}
          </MenuCheckItem>
        ))}
        {selected.length > 0 && (
          <>
            <MenuSeparator />
            <MenuItem
              onSelect={() => {
                onChange([])
              }}
            >
              Clear
            </MenuItem>
          </>
        )}
      </MenuContent>
    </Menu>
  )
}

function useDebouncedCallback(fn: (value: string) => void, ms: number) {
  const timer = useRef<number | undefined>(undefined)
  const latest = useRef(fn)
  latest.current = fn
  return (value: string) => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      latest.current(value)
    }, ms)
  }
}

// ---------------------------------------------------------------- table

type QuickMenu = 'assign' | 'status' | null

interface AiSearchState {
  query: string
  explanation: string
  source: 'llm' | 'rules'
}

const quickButton =
  'flex size-7 items-center justify-center rounded-control text-fg-muted transition-colors hover:bg-canvas hover:text-fg data-[state=open]:bg-canvas data-[state=open]:text-fg'

/**
 * Hover (or keyboard-select) quick actions: assign, change status, watch (spec 11.4).
 * They sit beside the row link rather than inside it, so no button is nested in a link.
 */
function RowActions({
  incident,
  users,
  menu,
  setMenu,
}: {
  incident: Incident
  users: UserPublic[]
  menu: QuickMenu
  setMenu: (menu: QuickMenu) => void
}) {
  const assign = useAssign(incident.key, users)
  const watch = useWatch(incident.key)
  const { permissions, allowed_transitions: moves } = incident
  if (incident.is_deleted) return null
  return (
    <div
      data-open={menu ? '' : undefined}
      className="absolute right-2 top-1/2 z-10 hidden -translate-y-1/2 translate-x-1 items-center gap-0.5 rounded-control border border-border bg-elevated p-0.5 opacity-0 shadow-[var(--shadow-elevated)] transition duration-instant group-focus-within:translate-x-0 group-focus-within:opacity-100 group-hover:translate-x-0 group-hover:opacity-100 data-[open]:translate-x-0 data-[open]:opacity-100 group-data-[kbd]:translate-x-0 group-data-[kbd]:opacity-100 md:flex"
    >
      {permissions.can_assign && (
        <PeoplePicker
          value={incident.assignee}
          open={menu === 'assign'}
          onOpenChange={(open) => {
            setMenu(open ? 'assign' : null)
          }}
          onChange={(user) => {
            assign.mutate(
              { assignee_id: user?.id ?? null },
              {
                onSuccess: (inc) => {
                  toast.success(
                    inc.assignee
                      ? `${inc.key} assigned to ${inc.assignee.name}`
                      : `${inc.key} unassigned`,
                  )
                },
                onError: (err) => {
                  toastError(err, 'Could not change who this is assigned to')
                },
              },
            )
          }}
          trigger={
            <button
              type="button"
              aria-label="Assign (A)"
              title="Assign (A)"
              className={quickButton}
            >
              <UserPlus className="size-4" />
            </button>
          }
        />
      )}
      {moves.length > 0 && (
        <StatusControl
          incident={incident}
          open={menu === 'status'}
          onOpenChange={(open) => {
            setMenu(open ? 'status' : null)
          }}
          trigger={
            <button
              type="button"
              aria-label="Change status (S)"
              title="Change status (S)"
              className={quickButton}
            >
              <CircleDot className="size-4" />
            </button>
          }
        />
      )}
      <button
        type="button"
        aria-label={incident.watching ? 'Stop watching' : 'Watch'}
        title={incident.watching ? 'Stop watching' : 'Watch'}
        aria-pressed={incident.watching}
        className={`${quickButton} ${incident.watching ? 'text-accent' : ''}`}
        onClick={() => {
          watch.mutate(!incident.watching, {
            onSuccess: (inc) => {
              toast.success(inc.watching ? `Watching ${inc.key}` : `Stopped watching ${inc.key}`)
            },
            onError: (err) => {
              toastError(err, 'Could not update watching')
            },
          })
        }}
      >
        {incident.watching ? <Eye className="size-4" /> : <EyeOff className="size-4" />}
      </button>
    </div>
  )
}

function Row({
  incident,
  selected,
  now,
  onHover,
  fresh,
  delay,
  users,
  menu,
  setMenu,
  keyboard,
}: {
  incident: Incident
  selected: boolean
  /** The selection came from J/K, so show its quick actions. */
  keyboard: boolean
  now: number
  onHover: () => void
  /** Arrived after the list was shown (e.g. via SSE): tint it briefly. */
  fresh: boolean
  delay: number
  users: UserPublic[]
  menu: QuickMenu
  setMenu: (menu: QuickMenu) => void
}) {
  const tone = priorityTone[incident.priority]
  return (
    <motion.li
      layout="position"
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, transition: { duration: 0.12 } }}
      transition={{
        duration: 0.22,
        delay,
        ease: [0.16, 1, 0.3, 1],
        layout: { type: 'spring', stiffness: 380, damping: 32 },
      }}
      onMouseEnter={onHover}
      data-kbd={(selected && keyboard) || undefined}
      className={`group relative ${fresh ? 'animate-fresh-row' : ''}`}
    >
      <RowActions incident={incident} users={users} menu={menu} setMenu={setMenu} />
      <Link
        to={`/tasks/${incident.key}`}
        data-selected={selected || undefined}
        aria-current={selected || undefined}
        className={`grid grid-cols-[4.5rem_1fr_auto] items-center gap-x-3 border-b border-l-2 border-b-[color:var(--border)] px-3 py-2.5 transition-colors duration-instant hover:bg-elevated data-[selected]:bg-accent/[0.07] md:grid-cols-[4.5rem_1fr_7.5rem_6.5rem_8rem_6rem] ${tone.border} ${
          incident.sla.resolution_breached && !incident.sla.paused ? 'bg-danger/[0.05]' : ''
        }`}
      >
        <span className="font-mono text-xs text-fg-muted">{incident.key}</span>
        <span className="min-w-0">
          <span className="block truncate text-sm">{incident.title}</span>
          <span className="flex items-center gap-2 whitespace-nowrap text-xs text-fg-muted md:hidden">
            <PriorityBadge priority={incident.priority} /> · {statusLabel[incident.status]}
          </span>
          {(incident.tags.length > 0 || incident.comment_count > 0) && (
            <span className="mt-0.5 hidden items-center gap-1.5 md:flex">
              {incident.tags.slice(0, 3).map((t) => (
                <span key={t} className="rounded-full bg-canvas px-1.5 text-[11px] text-fg-muted">
                  {t}
                </span>
              ))}
              {incident.comment_count > 0 && (
                <span className="inline-flex items-center gap-0.5 text-[11px] text-fg-muted">
                  <MessageSquare aria-hidden className="size-3" />
                  {incident.comment_count}
                </span>
              )}
            </span>
          )}
        </span>
        <span className="hidden md:block">
          <StatusPill status={incident.status} />
        </span>
        <span className="hidden md:block">
          <PriorityBadge priority={incident.priority} />
        </span>
        <span className="hidden min-w-0 items-center gap-2 md:flex">
          {assigneesOf(incident).length ? (
            <span className="min-w-0 truncate text-sm text-fg-muted">
              <AssigneeStack people={assigneesOf(incident)} />
            </span>
          ) : (
            <span className="text-sm text-fg-muted/70">Not assigned</span>
          )}
        </span>
        <span className="flex flex-col items-end gap-0.5 text-right">
          <SlaTimer incident={incident} now={now} />
          <span className="hidden text-[11px] text-fg-muted md:block">
            {timeAgo(incident.updated_at, now)}
          </span>
        </span>
      </Link>
    </motion.li>
  )
}

function EmptyState({
  filtered,
  onClear,
  canCreate,
  onCreate,
  view,
}: {
  view: View
  filtered: boolean
  onClear: () => void
  canCreate: boolean
  onCreate: () => void
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="flex flex-col items-center gap-3 px-6 py-16 text-center"
    >
      <span className="flex size-12 items-center justify-center rounded-full border border-border bg-canvas">
        <Inbox aria-hidden className="size-5 text-fg-muted" />
      </span>
      <div>
        <p className="font-medium">
          {view === 'watching'
            ? 'You are not watching anything yet'
            : view === 'mine'
              ? 'Nothing on your plate'
              : filtered
                ? 'No tasks match these filters'
                : 'No tasks yet'}
        </p>
        <p className="text-sm text-fg-muted">
          {view === 'watching'
            ? 'Press Watch on a task to follow every comment and its resolution.'
            : view === 'mine'
              ? 'Open work assigned to you shows up here.'
              : filtered
                ? 'Try widening the search or clearing a filter.'
                : 'Create the first task and it shows up here.'}
        </p>
      </div>
      <motion.div
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.12 }}
      >
        {filtered ? (
          <Button onClick={onClear}>Clear filters</Button>
        ) : canCreate ? (
          <Button variant="primary" onClick={onCreate}>
            <Plus className="size-4" /> Create a task
          </Button>
        ) : null}
      </motion.div>
    </motion.div>
  )
}

// ---------------------------------------------------------------- page

export function IncidentsPage() {
  const { user } = useAuth()
  const { canWork } = useTeam()
  const { openCreate } = useShell()
  const navigate = useNavigate()
  const location = useLocation()
  const aiEnabled = useAiEnabled()
  const [asking, setAsking] = useState(false)
  // How the AI read a plain-language search; cleared as soon as the filters change by hand.
  const aiSearch = (location.state as { aiSearch?: AiSearchState } | null)?.aiSearch ?? null
  const askAi = (text: string) => {
    if (text.length < 2) return
    setAsking(true)
    nlSearch(text)
      .then((res) => {
        setSearch(res.filters.q ?? '')
        navigate(`/tasks?${filtersToSearch(res.filters)}`, {
          replace: true,
          state: { aiSearch: { query: text, explanation: res.explanation, source: res.source } },
        })
      })
      .catch((err: unknown) => {
        toastError(err, 'AI search is unavailable; try a plain search')
      })
      .finally(() => {
        setAsking(false)
      })
  }
  const url = useUrlFilters()
  const { data: users = [] } = useUsers()
  const query = useIncidents(url.filters)
  const now = useNow()
  const [selected, setSelected] = useState(0)
  const [keyboard, setKeyboard] = useState(false)
  const [search, setSearch] = useState(url.q)
  const searchRef = useRef<HTMLInputElement>(null)
  const sentinel = useRef<HTMLDivElement>(null)
  const pushSearch = useDebouncedCallback((value) => {
    url.update({ q: value || null })
  }, 250)

  const items = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data])
  const total = query.data?.pages[0]?.total ?? 0
  const filtered =
    url.status.length + url.priority.length + url.assignee.length > 0 ||
    !!url.q ||
    !!url.sla ||
    url.view !== 'all'

  // Infinite scroll: load the next cursor page when the sentinel scrolls into view.
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query
  useEffect(() => {
    const el = sentinel.current
    if (!el) return
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting && hasNextPage && !isFetchingNextPage) void fetchNextPage()
      },
      { rootMargin: '300px' },
    )
    io.observe(el)
    return () => {
      io.disconnect()
    }
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  useEffect(() => {
    setSelected(0)
  }, [url.filters])

  // Quick menu opened from the keyboard (A / S) for the selected row.
  const [quick, setQuick] = useState<{ id: string; menu: QuickMenu } | null>(null)

  // Rows that appear after the first paint of a given filter set are "fresh" (a live
  // arrival); the first page itself staggers in instead (spec 12.3).
  const seen = useRef<{ filters: IncidentFilters; ids: Set<string> } | null>(null)
  const [fresh, setFresh] = useState<Set<string>>(new Set())
  const firstPaint = seen.current?.filters !== url.filters
  useEffect(() => {
    if (query.isPending || query.isPlaceholderData) return
    const ids = new Set(items.map((i) => i.id))
    const prev = seen.current
    seen.current = { filters: url.filters, ids }
    if (!prev || prev.filters !== url.filters) return
    const arrived = items.filter((i) => !prev.ids.has(i.id)).map((i) => i.id)
    if (!arrived.length) return
    setFresh(new Set(arrived))
    const t = window.setTimeout(() => {
      setFresh(new Set())
    }, 1600)
    return () => {
      window.clearTimeout(t)
    }
  }, [items, url.filters, query.isPending, query.isPlaceholderData])

  // J/K to move, Enter to open, "/" to search (spec 11.4).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === '/' && !isTyping(e)) {
        e.preventDefault()
        searchRef.current?.focus()
        return
      }
      if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey || items.length === 0) return
      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault()
        setKeyboard(true)
        setSelected((i) => Math.min(items.length - 1, i + 1))
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault()
        setKeyboard(true)
        setSelected((i) => Math.max(0, i - 1))
      } else if (e.key === 'Enter') {
        const incident = items[selected]
        if (incident) navigate(`/tasks/${incident.key}`)
      } else if (e.key === 'a' || e.key === 's') {
        const incident = items[selected]
        if (!incident || incident.is_deleted) return
        const allowed =
          e.key === 'a' ? incident.permissions.can_assign : incident.allowed_transitions.length > 0
        if (!allowed) return
        e.preventDefault()
        setKeyboard(true)
        setQuick({ id: incident.id, menu: e.key === 'a' ? 'assign' : 'status' })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
    }
  }, [items, selected, navigate])

  useEffect(() => {
    document.querySelector('[aria-current="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [selected])

  const assigneeLabel = (id: string) =>
    id === 'me'
      ? 'Me'
      : id === 'none'
        ? 'Not assigned'
        : (users.find((u) => u.id === id)?.name ?? 'Someone')
  const sortLabel = SORTS.find((s) => s.value === url.sort)?.label ?? 'Newest first'
  const clearAll = () => {
    setSearch('')
    url.update({
      status: null,
      priority: null,
      assignee: null,
      q: null,
      view: null,
      sort: null,
      sla: null,
    })
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-medium">Tasks</h1>
          <p className="tabular text-sm text-fg-muted" aria-live="polite">
            {query.isPending ? 'Loading…' : `${total} ${total === 1 ? 'task' : 'tasks'}`}
          </p>
        </div>
        <div className="hidden items-center gap-1.5 text-xs text-fg-muted lg:flex">
          <Kbd>J</Kbd>
          <Kbd>K</Kbd> move · <Kbd>Enter</Kbd> open · <Kbd>A</Kbd> assign · <Kbd>S</Kbd> status ·{' '}
          <Kbd>?</Kbd> all shortcuts
        </div>
      </header>

      {/* Saved views */}
      <nav
        aria-label="Views"
        className="no-scrollbar -mx-4 flex gap-1 overflow-x-auto border-b border-border px-4 sm:mx-0 sm:px-0"
      >
        {VIEWS.map((v) => {
          const active = url.view === v.id
          return (
            <button
              key={v.id}
              type="button"
              onClick={() => {
                url.update({ view: v.id === 'all' ? null : v.id })
              }}
              className={`relative shrink-0 whitespace-nowrap px-3 pb-2.5 pt-1 text-sm transition-colors ${active ? 'text-fg' : 'text-fg-muted hover:text-fg'}`}
            >
              {v.label}
              {active && (
                <motion.span
                  layoutId="view-underline"
                  className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent"
                />
              )}
            </button>
          )
        })}
      </nav>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative flex h-8 min-w-56 flex-1 items-center sm:max-w-xs">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 size-4 text-fg-muted"
          />
          <span className="sr-only">Search tasks</span>
          <input
            ref={searchRef}
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              // '?' means a plain-language request, sent on Enter instead of as you type.
              if (!(aiEnabled && e.target.value.startsWith('?'))) pushSearch(e.target.value)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && aiEnabled && search.trim().startsWith('?')) {
                e.preventDefault()
                askAi(search.trim().slice(1).trim())
                return
              }
              if (e.key === 'Escape') {
                setSearch('')
                url.update({ q: null })
                e.currentTarget.blur()
              }
            }}
            placeholder={
              aiEnabled
                ? 'Search, or ? to ask in plain words'
                : 'Search title, description, TASK-12…'
            }
            className="h-8 w-full rounded-full border border-border bg-surface pl-8 pr-8 text-sm outline-none transition-colors placeholder:text-fg-muted/70 focus:border-accent"
          />
          {search && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => {
                setSearch('')
                url.update({ q: null })
              }}
              className="absolute right-2 text-fg-muted hover:text-fg"
            >
              <X className="size-4" />
            </button>
          )}
        </label>

        <MultiFilter
          label="Status"
          options={STATUSES}
          selected={url.status}
          render={(s) => statusLabel[s]}
          onChange={(v) => {
            url.update({ status: v })
          }}
        />
        <MultiFilter
          label="Priority"
          options={PRIORITIES}
          selected={url.priority}
          render={(p) => priorityLabel[p]}
          onChange={(v) => {
            url.update({ priority: v })
          }}
        />
        {url.view !== 'mine' && url.view !== 'unassigned' && (
          <MultiFilter
            label="Assigned to"
            options={[
              'me',
              'none',
              ...users.filter((u) => u.role !== 'viewer' && u.id !== user?.id).map((u) => u.id),
            ]}
            selected={url.assignee}
            render={assigneeLabel}
            onChange={(v) => {
              url.update({ assignee: v })
            }}
          />
        )}

        <Menu>
          <MenuTrigger asChild>
            <button type="button" aria-label="Sort">
              <span className="inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-sm text-fg-muted hover:text-fg">
                <ArrowDownUp aria-hidden className="size-3.5" /> {sortLabel}
              </span>
            </button>
          </MenuTrigger>
          <MenuContent align="end">
            <MenuLabel>Sort by</MenuLabel>
            {SORTS.map((s) => (
              <MenuCheckItem
                key={s.value}
                checked={(url.sort || '-created_at') === s.value}
                onCheckedChange={() => {
                  url.update({ sort: s.value === '-created_at' ? null : s.value })
                }}
              >
                {s.label}
              </MenuCheckItem>
            ))}
          </MenuContent>
        </Menu>

        {filtered && (
          <button
            type="button"
            onClick={clearAll}
            className="text-sm text-fg-muted underline-offset-2 hover:text-fg hover:underline"
          >
            Reset
          </button>
        )}
      </div>

      <AnimatePresence>
        {(aiSearch ?? asking) && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            role="status"
            className="flex items-center gap-2 rounded-card border border-accent/25 bg-accent/[0.05] px-3 py-2 text-sm"
          >
            {asking ? (
              <Loader2 aria-hidden className="size-4 animate-spin text-accent" />
            ) : (
              <Sparkles aria-hidden className="size-4 text-accent" />
            )}
            <span className="min-w-0 flex-1">
              {asking || !aiSearch ? (
                'Reading your request…'
              ) : (
                <>
                  <span className="text-fg-muted">“{aiSearch.query}” → </span>
                  {aiSearch.explanation}
                </>
              )}
            </span>
            {aiSearch && !asking && (
              <button
                type="button"
                onClick={() => {
                  setSearch('')
                  navigate('/tasks', { replace: true })
                }}
                className="shrink-0 text-xs text-fg-muted hover:text-fg"
              >
                Clear
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Table */}
      <section
        aria-label="Task list"
        className="overflow-hidden rounded-card border border-border bg-surface shadow-[var(--shadow-elevated)]"
      >
        <div
          className="hidden grid-cols-[4.5rem_1fr_7.5rem_6.5rem_8rem_6rem] gap-x-3 border-b border-border px-3 py-2 text-xs text-fg-muted md:grid"
          aria-hidden
        >
          <span className="pl-0.5">Key</span>
          <span>Title</span>
          <span>Status</span>
          <span>Priority</span>
          <span>Assigned to</span>
          <span className="text-right">SLA · updated</span>
        </div>

        {query.isPending ? (
          <ul aria-busy="true">
            {Array.from({ length: 8 }, (_, i) => (
              <li key={i} className="border-b border-border px-3 py-3">
                <div
                  className="shimmer h-5 rounded"
                  style={{ width: `${60 + ((i * 17) % 35)}%` }}
                />
              </li>
            ))}
          </ul>
        ) : query.isError ? (
          <div className="p-6 text-sm text-danger">
            Could not load tasks.{' '}
            <button type="button" className="underline" onClick={() => void query.refetch()}>
              Retry
            </button>
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            view={url.view}
            filtered={filtered}
            onClear={clearAll}
            canCreate={canWork}
            onCreate={openCreate}
          />
        ) : (
          <ul
            className={
              query.isPlaceholderData ? 'opacity-60 transition-opacity' : 'transition-opacity'
            }
          >
            <AnimatePresence initial={false}>
              {items.map((incident, i) => (
                <Row
                  key={incident.id}
                  incident={incident}
                  selected={i === selected}
                  now={now}
                  onHover={() => {
                    setSelected(i)
                    setKeyboard(false)
                  }}
                  keyboard={keyboard}
                  fresh={fresh.has(incident.id)}
                  // Stagger only the first screenful, and only on first paint.
                  delay={firstPaint && i < 12 ? i * 0.03 : 0}
                  users={users}
                  menu={quick?.id === incident.id ? quick.menu : null}
                  setMenu={(menu) => {
                    setQuick(menu ? { id: incident.id, menu } : null)
                  }}
                />
              ))}
            </AnimatePresence>
          </ul>
        )}
        <div ref={sentinel} className="h-1" />
        {isFetchingNextPage && (
          <p className="py-3 text-center text-xs text-fg-muted">Loading more…</p>
        )}
        {!hasNextPage && items.length > 25 && (
          <p className="py-3 text-center text-xs text-fg-muted">That is everything.</p>
        )}
      </section>
    </div>
  )
}
