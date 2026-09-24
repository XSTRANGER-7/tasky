import * as Dialog from '@radix-ui/react-dialog'
import { useQuery } from '@tanstack/react-query'
import { Command } from 'cmdk'
import { AnimatePresence, motion } from 'framer-motion'
import {
  AlertTriangle,
  ArrowRight,
  Bell,
  Loader2,
  Sparkles,
  CircleDot,
  LayoutDashboard,
  ListTodo,
  Mail,
  Moon,
  Plus,
  UserRound,
  UserX,
} from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { filtersToSearch, nlSearch, useAiEnabled } from '@/api/ai'
import { api, unwrap } from '@/api/client'
import { PriorityBadge, StatusPill } from '@/components/incident-ui'
import { spring } from '@/lib/motion'
import { toastError } from '@/lib/toast'

// A task key typed on its own: "42", "TASK-42", or the old "INC-42" (the server still
// accepts it, so old keys keep working). A bare number means TASK-.
const KEY = /^(?:(task|inc)-)?(\d{1,9})$/i

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = window.setTimeout(() => {
      setDebounced(value)
    }, ms)
    return () => {
      window.clearTimeout(id)
    }
  }, [value, ms])
  return debounced
}

function Item({
  children,
  onSelect,
  value,
  icon,
}: {
  children: ReactNode
  onSelect: () => void
  value: string
  icon?: ReactNode
}) {
  return (
    <Command.Item
      value={value}
      onSelect={onSelect}
      className="flex h-10 cursor-default items-center gap-3 rounded-control px-3 text-sm text-fg data-[selected=true]:bg-accent/10"
    >
      <span className="text-fg-muted">{icon}</span>
      {children}
    </Command.Item>
  )
}

export function CommandPalette({
  open,
  onOpenChange,
  onCreate,
  canCreate,
  isAdmin = false,
  toggleTheme,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreate: () => void
  canCreate: boolean
  isAdmin?: boolean
  toggleTheme: () => void
}) {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const q = useDebounced(search.trim(), 150)

  useEffect(() => {
    if (!open) setSearch('')
  }, [open])

  // "?" asks the AI to turn the request into filters (spec 10.2). Without AI it falls
  // through to plain full-text search on the rest of the text.
  const aiEnabled = useAiEnabled()
  const asking = q.startsWith('?')
  const text = asking ? q.slice(1).trim() : q
  const [askingNow, setAskingNow] = useState(false)

  const results = useQuery({
    queryKey: ['palette', text],
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/incidents', { params: { query: { q: text, limit: 6 } }, signal })),
    enabled: open && text.length >= 2 && !(asking && aiEnabled),
    staleTime: 10_000,
  })

  const ask = () => {
    setAskingNow(true)
    nlSearch(text)
      .then((s) => {
        onOpenChange(false)
        navigate(`/tasks?${filtersToSearch(s.filters)}`, {
          state: { aiSearch: { query: text, explanation: s.explanation, source: s.source } },
        })
      })
      .catch((err: unknown) => {
        toastError(err, 'AI search is unavailable; try a plain search')
      })
      .finally(() => {
        setAskingNow(false)
      })
  }

  const run = (action: () => void) => {
    onOpenChange(false)
    action()
  }
  const go = (to: string) => {
    run(() => {
      navigate(to)
    })
  }
  const match = KEY.exec(q)
  const jumpKey = match ? `${(match[1] ?? 'task').toUpperCase()}-${match[2] ?? ''}` : null

  // cmdk only auto-selects on its own filtering; results here arrive async, so keep
  // the highlight on the first row whenever they change (Enter must always do something).
  const firstId = results.data?.items[0]?.id
  const [selected, setSelected] = useState('')
  useEffect(() => {
    if (asking && aiEnabled && text.length >= 2) setSelected('ask')
    else if (jumpKey) setSelected(`jump-${jumpKey}`)
    else if (q.length >= 2 && firstId) setSelected(firstId)
    else if (q.length < 2) setSelected(canCreate ? 'create' : 'theme')
  }, [jumpKey, q, firstId, canCreate, asking, aiEnabled, text])

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0, transition: { duration: 0.12 } }}
              />
            </Dialog.Overlay>
            <Dialog.Content
              forceMount
              aria-describedby={undefined}
              className="pointer-events-none fixed inset-x-0 top-[12vh] z-50 flex justify-center px-4"
            >
              <motion.div
                className="pointer-events-auto w-full max-w-[640px]"
                initial={{ opacity: 0, scale: 0.96 }}
                animate={{ opacity: 1, scale: 1, transition: spring }}
                exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.12 } }}
              >
                <Dialog.Title className="sr-only">Command palette</Dialog.Title>
                <Command
                  shouldFilter={false}
                  loop
                  value={selected}
                  onValueChange={setSelected}
                  className="overflow-hidden rounded-dialog border border-border bg-elevated/95 shadow-[var(--shadow-elevated)] backdrop-blur-xl"
                >
                  <Command.Input
                    autoFocus
                    value={search}
                    onValueChange={setSearch}
                    placeholder={
                      aiEnabled
                        ? 'Search, TASK-42, a command, or ? to ask in plain words…'
                        : 'Search tasks, type TASK-42, or a command…'
                    }
                    className="h-14 w-full border-b border-border bg-transparent px-4 text-md outline-none placeholder:text-fg-muted"
                  />
                  <Command.List className="max-h-[60vh] overflow-y-auto p-2">
                    <Command.Empty className="px-3 py-6 text-center text-sm text-fg-muted">
                      {results.isFetching ? 'Searching…' : 'No matches'}
                    </Command.Empty>

                    {asking && aiEnabled && text.length >= 2 && (
                      <Command.Group heading="Ask AI" className="palette-group">
                        <Item
                          value="ask"
                          icon={
                            askingNow ? (
                              <Loader2 className="size-4 animate-spin" />
                            ) : (
                              <Sparkles className="size-4 text-accent" />
                            )
                          }
                          onSelect={ask}
                        >
                          <span className="flex-1 truncate">
                            Find: <span className="text-fg">{text}</span>
                          </span>
                          <span className="text-xs text-fg-muted">turns it into filters</span>
                        </Item>
                      </Command.Group>
                    )}

                    {jumpKey && (
                      <Command.Group heading="Jump to" className="palette-group">
                        <Item
                          value={`jump-${jumpKey}`}
                          icon={<ArrowRight className="size-4" />}
                          onSelect={() => {
                            go(`/tasks/${jumpKey}`)
                          }}
                        >
                          Open <span className="font-mono">{jumpKey}</span>
                        </Item>
                      </Command.Group>
                    )}

                    {(results.data?.items.length ?? 0) > 0 && (
                      <Command.Group heading="Tasks" className="palette-group">
                        {results.data?.items.map((incident) => (
                          <Item
                            key={incident.id}
                            value={incident.id}
                            icon={<PriorityBadge priority={incident.priority} compact />}
                            onSelect={() => {
                              go(`/tasks/${incident.key}`)
                            }}
                          >
                            <span className="w-16 shrink-0 font-mono text-xs text-fg-muted">
                              {incident.key}
                            </span>
                            <span className="flex-1 truncate">{incident.title}</span>
                            <StatusPill status={incident.status} />
                          </Item>
                        ))}
                      </Command.Group>
                    )}

                    {q.length < 2 && (
                      <>
                        <Command.Group heading="Actions" className="palette-group">
                          {canCreate && (
                            <Item
                              value="create"
                              icon={<Plus className="size-4" />}
                              onSelect={() => {
                                run(onCreate)
                              }}
                            >
                              New task
                            </Item>
                          )}
                          <Item
                            value="theme"
                            icon={<Moon className="size-4" />}
                            onSelect={() => {
                              run(toggleTheme)
                            }}
                          >
                            Toggle theme
                          </Item>
                        </Command.Group>
                        <Command.Group heading="Go to" className="palette-group">
                          <Item
                            value="dashboard"
                            icon={<LayoutDashboard className="size-4" />}
                            onSelect={() => {
                              go('/')
                            }}
                          >
                            Dashboard
                          </Item>
                          <Item
                            value="incidents"
                            icon={<ListTodo className="size-4" />}
                            onSelect={() => {
                              go('/tasks')
                            }}
                          >
                            All tasks
                          </Item>
                          <Item
                            value="mine"
                            icon={<UserRound className="size-4" />}
                            onSelect={() => {
                              go('/tasks?view=mine')
                            }}
                          >
                            My work
                          </Item>
                          <Item
                            value="open"
                            icon={<CircleDot className="size-4" />}
                            onSelect={() => {
                              go('/tasks?status=open&status=in_progress')
                            }}
                          >
                            Open work
                          </Item>
                          <Item
                            value="unassigned"
                            icon={<UserX className="size-4" />}
                            onSelect={() => {
                              go('/tasks?view=unassigned')
                            }}
                          >
                            Not assigned
                          </Item>
                          <Item
                            value="breached"
                            icon={<AlertTriangle className="size-4" />}
                            onSelect={() => {
                              go('/tasks?view=breached')
                            }}
                          >
                            SLA breached
                          </Item>
                          <Item
                            value="notifications"
                            icon={<Bell className="size-4" />}
                            onSelect={() => {
                              go('/notifications')
                            }}
                          >
                            Notifications
                          </Item>
                          {isAdmin && (
                            <Item
                              value="outbox"
                              icon={<Mail className="size-4" />}
                              onSelect={() => {
                                go('/admin/outbox')
                              }}
                            >
                              Email outbox
                            </Item>
                          )}
                        </Command.Group>
                      </>
                    )}
                  </Command.List>
                </Command>
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  )
}
