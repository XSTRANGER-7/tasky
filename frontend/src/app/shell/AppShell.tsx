import * as Dialog from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Activity,
  Bell,
  ChevronRight,
  Keyboard,
  LayoutDashboard,
  ListTodo,
  LogOut,
  Menu as MenuIcon,
  Moon,
  Plus,
  Search,
  Settings,
  Mail,
  SlidersHorizontal,
  Sun,
  UserRound,
  Users,
  WifiOff,
  type LucideIcon,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { fetchNotifications, useNotifications } from '@/api/notifications'
import { useTeamRequests } from '@/api/teams'
import { useHealth } from '@/app/useHealth'
import { useAuth } from '@/auth/useAuth'
import { Kbd } from '@/components/incident-ui'
import {
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
} from '@/components/menu'
import { Avatar, Button } from '@/components/ui'
import { CommandPalette } from '@/features/command/CommandPalette'
import { CreateIncidentDrawer } from '@/features/incidents/CreateIncidentDrawer'
import { NotificationBell } from '@/features/notifications/NotificationBell'
import { NoTeamHome, TeamFinderDialog } from '@/features/teams/TeamFinder'
import { useLiveEvents, useLiveState } from '@/lib/live'
import { useTheme } from '@/lib/theme'
import { PHONE, useMediaQuery } from '@/lib/useMediaQuery'
import { useTeam } from '@/team/useTeam'

import { PageTransition } from './PageTransition'
import { isTyping, ShellContext } from './ShellContext'
import { ShortcutsDialog } from './ShortcutsDialog'
import { TeamSwitcher } from './TeamSwitcher'

// ---------------------------------------------------------------- navigation model

interface NavEntry {
  to: string
  label: string
  icon: LucideIcon
  /** `?view=` value this entry stands for; list views share one path. */
  view?: string
  end?: boolean
  badge?: 'unread' | 'requests'
}

const MAIN: NavEntry[] = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/tasks', label: 'Tasks', icon: ListTodo },
  { to: '/tasks?view=mine', label: 'My work', icon: UserRound, view: 'mine' },
  { to: '/notifications', label: 'Notifications', icon: Bell, badge: 'unread' },
  { to: '/team', label: 'Team', icon: Users, badge: 'requests' },
]

// A team's admins also look after its email and see the settings it runs on.
const ADMIN: NavEntry[] = [
  { to: '/admin/outbox', label: 'Email outbox', icon: Mail },
  { to: '/admin/settings', label: 'Configuration', icon: SlidersHorizontal },
]

/** Without a team only these make sense: "home" (create or join one) and notifications. */
const NO_TEAM: NavEntry[] = [
  { to: '/', label: 'Home', icon: LayoutDashboard, end: true },
  { to: '/notifications', label: 'Notifications', icon: Bell, badge: 'unread' },
]
/** Pages that work without a team; every other page shows "create or join a team". */
const TEAMLESS_PATHS = ['/notifications', '/settings', '/status']

/** On phones the bottom bar holds these; everything else lives in "More". */
const BOTTOM = ['/', '/tasks', '/notifications']

const TITLES: [RegExp, string][] = [
  [/^\/$/, 'Dashboard'],
  [/^\/tasks$/, 'Tasks'],
  [/^\/notifications$/, 'Notifications'],
  [/^\/settings$/, 'Settings'],
  [/^\/status$/, 'System status'],
  [/^\/team(\/.*)?$/, 'Team'],
  [/^\/admin\/outbox$/, 'Email outbox'],
  [/^\/admin\/settings$/, 'Configuration'],
]

function useIsActive() {
  const location = useLocation()
  const view = new URLSearchParams(location.search).get('view')
  return (item: NavEntry) => {
    const path = item.to.split('?')[0] ?? item.to
    if (item.end) return location.pathname === path
    if (item.view !== undefined) return location.pathname === path && view === item.view
    if (path === '/tasks')
      return (
        (location.pathname === path && view !== 'mine') || location.pathname.startsWith('/tasks/')
      )
    return location.pathname === path || location.pathname.startsWith(`${path}/`)
  }
}

function usePendingRequests(enabled: boolean): number {
  const { active, canManage } = useTeam()
  const requests = useTeamRequests(active?.id ?? null, enabled && canManage)
  return requests.data?.filter((r) => r.status === 'pending').length ?? 0
}

function NavItem({ item, compact = false }: { item: NavEntry; compact?: boolean }) {
  const isActive = useIsActive()
  const unread = useNotifications().data?.unread_count ?? 0
  const pending = usePendingRequests(item.badge === 'requests')
  const active = isActive(item)
  const Icon = item.icon
  const count = item.badge === 'unread' ? unread : item.badge === 'requests' ? pending : 0
  return (
    <Link
      to={item.to}
      title={item.label}
      aria-current={active ? 'page' : undefined}
      className={`group relative flex items-center rounded-control text-sm transition-colors duration-instant ${
        compact
          ? 'mx-1 my-1.5 h-11 min-w-0 flex-1 justify-center'
          : 'h-9 gap-3 px-2.5 md:justify-center lg:justify-start'
      } ${active ? 'text-fg' : 'text-fg-muted hover:bg-elevated hover:text-fg'}`}
    >
      {active && (
        <motion.span
          layoutId={compact ? 'nav-active-mobile' : 'nav-active'}
          className="absolute inset-0 rounded-control bg-accent/10"
          transition={{ type: 'spring', stiffness: 500, damping: 40 }}
        />
      )}
      <span className="relative">
        <Icon aria-hidden className={`${compact ? 'size-5' : 'size-4'} shrink-0`} />
        {count > 0 && (
          <span className="absolute -right-1.5 -top-1 size-2 rounded-full bg-danger ring-2 ring-surface lg:hidden" />
        )}
      </span>
      {/* Phones: icons only; the name stays for screen readers and as a tooltip. */}
      <span className={compact ? 'sr-only' : 'relative hidden lg:inline'}>{item.label}</span>
      {count > 0 && !compact && (
        <span className="relative ml-auto hidden rounded-full bg-accent/15 px-1.5 text-[11px] tabular-nums text-accent lg:inline">
          {count > 99 ? '99+' : count}
        </span>
      )}
    </Link>
  )
}

function ApiStatusDot() {
  const { result } = useHealth(60_000)
  const { state: live } = useLiveState()
  const state = result?.state ?? 'idle'
  const paused = state === 'ok' && live === 'offline'
  const tone =
    state === 'ok'
      ? paused
        ? 'bg-priority-medium'
        : 'bg-status-resolved'
      : state === 'degraded'
        ? 'bg-priority-medium'
        : state === 'idle'
          ? 'bg-fg-muted'
          : 'bg-danger'
  const label =
    state === 'ok'
      ? paused
        ? 'Live updates paused'
        : 'All systems operational'
      : state === 'idle'
        ? 'Checking…'
        : 'API problem'
  return (
    <NavLink
      to="/status"
      title={label}
      className="flex h-9 items-center gap-3 rounded-control px-2.5 text-xs text-fg-muted hover:bg-elevated hover:text-fg md:justify-center lg:justify-start"
    >
      <span className="relative flex size-4 items-center justify-center">
        {state === 'ok' && live === 'open' && (
          <span
            aria-hidden
            className="absolute size-2 animate-ping rounded-full bg-status-resolved/50 [animation-duration:2.5s]"
          />
        )}
        <span aria-hidden className={`relative size-2 rounded-full ${tone}`} />
      </span>
      <span className="hidden lg:inline">{label}</span>
    </NavLink>
  )
}

/** Sun/moon that rotates 180° on switch (spec 12.3). */
function ThemeButton({ withLabel = false }: { withLabel?: boolean }) {
  const [theme, toggle] = useTheme()
  const label = `Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      title={`${label} (Ctrl+/)`}
      className={`flex items-center gap-3 rounded-control text-fg-muted transition-colors hover:bg-elevated hover:text-fg ${
        withLabel
          ? 'h-9 w-full px-2.5 text-xs md:justify-center lg:justify-start'
          : 'size-9 justify-center'
      }`}
    >
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={theme}
          initial={{ rotate: -180, opacity: 0 }}
          animate={{ rotate: 0, opacity: 1 }}
          exit={{ rotate: 180, opacity: 0 }}
          transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          className="flex"
        >
          {theme === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </motion.span>
      </AnimatePresence>
      {withLabel && (
        <span className="hidden lg:inline">{theme === 'dark' ? 'Light theme' : 'Dark theme'}</span>
      )}
    </button>
  )
}

function Breadcrumb() {
  const location = useLocation()
  const view = new URLSearchParams(location.search).get('view')
  let title = TITLES.find(([re]) => re.test(location.pathname))?.[1] ?? ''
  if (location.pathname === '/tasks' && view === 'mine') title = 'My work'
  if (location.pathname === '/tasks' && view === 'watching') title = 'Watching'
  const key = /^\/tasks\/([^/]+)$/.exec(location.pathname)?.[1]
  const current = key ? decodeURIComponent(key).toUpperCase() : title
  return (
    <nav aria-label="Breadcrumb" className="hidden min-w-0 items-center gap-1.5 text-sm lg:flex">
      {key && (
        <>
          <Link to="/tasks" className="text-fg-muted hover:text-fg">
            Tasks
          </Link>
          <ChevronRight aria-hidden className="size-3.5 text-fg-muted/60" />
        </>
      )}
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={current}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4, transition: { duration: 0.1 } }}
          transition={{ duration: 0.18 }}
          aria-current="page"
          className={`truncate font-medium ${key ? 'font-mono' : ''}`}
        >
          {current}
        </motion.span>
      </AnimatePresence>
    </nav>
  )
}

/** Shown while the live stream is down; data still loads, it just is not pushed. */
function OfflineBanner() {
  const { state } = useLiveState()
  return (
    <AnimatePresence>
      {state === 'offline' && (
        <motion.div
          role="status"
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          className="border-b border-priority-medium/30 bg-priority-medium/10"
        >
          <p className="flex items-center justify-center gap-2 px-4 py-1.5 text-xs text-priority-medium">
            <WifiOff aria-hidden className="size-3.5" />
            Live updates paused, reconnecting… Your changes still save.
          </p>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/** Phone "More" menu: a bottom sheet that slides up and can be dragged away (spec 11.3). */
function MoreSheet({
  open,
  onOpenChange,
  isAdmin,
  main,
  onShortcuts,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  isAdmin: boolean
  main: NavEntry[]
  onShortcuts: () => void
}) {
  const items: NavEntry[] = [
    ...main.filter((i) => !BOTTOM.includes(i.to)),
    { to: '/settings', label: 'Settings', icon: Settings },
    { to: '/status', label: 'System status', icon: Activity },
    ...(isAdmin ? ADMIN : []),
  ]
  const tile =
    'flex h-20 w-full flex-col items-center justify-center gap-1.5 rounded-card border border-border bg-surface text-xs text-fg-muted transition-transform active:scale-95'
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-40 bg-black/40"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              />
            </Dialog.Overlay>
            <Dialog.Content forceMount aria-describedby={undefined} asChild>
              <motion.div
                className="fixed inset-x-0 bottom-0 z-50 rounded-t-dialog border-t border-border bg-elevated px-3 pb-[max(1rem,env(safe-area-inset-bottom))] pt-2"
                initial={{ y: '100%' }}
                animate={{ y: 0 }}
                exit={{ y: '100%', transition: { duration: 0.16 } }}
                transition={{ type: 'spring', stiffness: 380, damping: 36 }}
                drag="y"
                dragConstraints={{ top: 0, bottom: 0 }}
                dragElastic={{ top: 0, bottom: 0.6 }}
                onDragEnd={(_, info) => {
                  if (info.offset.y > 80) onOpenChange(false)
                }}
              >
                <div aria-hidden className="mx-auto mb-3 h-1 w-10 rounded-full bg-fg-muted/30" />
                <Dialog.Title className="px-2 pb-2 text-sm font-medium">More</Dialog.Title>
                <div className="grid grid-cols-3 gap-2">
                  {items.map((item, i) => {
                    const Icon = item.icon
                    return (
                      <motion.div
                        key={item.to}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.03 * i }}
                      >
                        <Link
                          to={item.to}
                          className={tile}
                          onClick={() => {
                            onOpenChange(false)
                          }}
                        >
                          <Icon aria-hidden className="size-5 text-fg" />
                          {item.label}
                        </Link>
                      </motion.div>
                    )
                  })}
                  <button
                    type="button"
                    onClick={() => {
                      onOpenChange(false)
                      onShortcuts()
                    }}
                    className={tile}
                  >
                    <Keyboard aria-hidden className="size-5 text-fg" />
                    Shortcuts
                  </button>
                </div>
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  )
}

// ---------------------------------------------------------------- shell

/** `G` then a letter (spec 11.1: every primary action has a shortcut). */
const GO: Record<string, string> = {
  d: '/',
  t: '/tasks',
  i: '/tasks', // the old "G I" (incidents), kept for muscle memory
  m: '/tasks?view=mine',
  w: '/tasks?view=watching',
  n: '/notifications',
  s: '/settings',
}

export function AppShell({ children }: { children?: ReactNode }) {
  const { user, logout } = useAuth()
  const { canWork, canManage, active, role, refresh: refreshTeams } = useTeam()
  const navigate = useNavigate()
  const isActive = useIsActive()
  const [theme, toggleTheme] = useTheme()
  const phone = useMediaQuery(PHONE)
  const unread = useNotifications().data?.unread_count ?? 0
  const [createOpen, setCreateOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const [findOpen, setFindOpen] = useState(false)
  const openFind = useCallback(() => {
    setFindOpen(true)
  }, [])
  const location = useLocation()
  const [params, setParams] = useSearchParams()

  // Email links ("find another team") arrive as /?find=team: open the finder once.
  const findParam = params.get('find')
  useEffect(() => {
    if (findParam !== 'team') return
    if (active) setFindOpen(true) // without a team the page itself is the finder
    params.delete('find')
    setParams(params, { replace: true })
  }, [findParam, active, params, setParams])

  const openCreate = useCallback(() => {
    setCreateOpen(true)
  }, [])
  const openPalette = useCallback(() => {
    setPaletteOpen(true)
  }, [])
  const actions = useMemo(() => ({ openCreate, openPalette }), [openCreate, openPalette])

  const onNotification = useCallback(() => {
    // The stream only says "something arrived"; the list has the title to show.
    void fetchNotifications(true).then(
      (list) => {
        const latest = list.items[0]
        if (!latest) return
        const target = latest.incident_key
          ? `/tasks/${latest.incident_key}`
          : (latest.link ?? '/notifications')
        toast(latest.title, {
          description: latest.body || latest.incident_key,
          action: {
            label: 'Open',
            onClick: () => {
              navigate(target)
            },
          },
        })
        // Join decisions change which teams I belong to.
        if (latest.kind.startsWith('team_')) void refreshTeams()
      },
      () => undefined,
    )
  }, [navigate, refreshTeams])
  useLiveEvents(user?.id, onNotification)

  // Global keys: Ctrl+K palette, Ctrl+/ theme, C create, ? shortcuts, G then a letter.
  const pendingG = useRef<number | null>(null)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((open) => !open)
        return
      }
      if ((e.metaKey || e.ctrlKey) && e.key === '/') {
        e.preventDefault()
        toggleTheme()
        return
      }
      if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return
      if (document.querySelector('[role="dialog"]')) return // a drawer or dialog owns the keys
      const key = e.key.toLowerCase()
      if (pendingG.current !== null) {
        window.clearTimeout(pendingG.current)
        pendingG.current = null
        const to = GO[key]
        if (to) {
          e.preventDefault()
          navigate(to)
        }
        return
      }
      if (key === 'g') {
        pendingG.current = window.setTimeout(() => {
          pendingG.current = null
        }, 1000)
      } else if (e.key === '?') {
        e.preventDefault()
        setShortcutsOpen(true)
      } else if (key === 'c' && canWork) {
        e.preventDefault()
        setCreateOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
    }
  }, [canWork, toggleTheme, navigate])

  if (!user) return null
  const canCreate = canWork
  const isAdmin = canManage
  const main = active ? MAIN : NO_TEAM
  const moreActive = [...main, ...ADMIN].some((i) => !BOTTOM.includes(i.to) && isActive(i))
  const needsTeam = !active && !TEAMLESS_PATHS.includes(location.pathname)

  return (
    <ShellContext.Provider value={actions}>
      <div className="app-wallpaper flex min-h-dvh">
        {/* Sidebar: 240 px, 56 px icon rail below 1024 px; bottom bar below 768 px. */}
        <motion.aside
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.22 }}
          className="sticky top-0 hidden h-dvh w-14 shrink-0 flex-col border-r border-border bg-surface md:flex lg:w-60"
        >
          <Link
            to="/"
            aria-label="Tasky home"
            className="flex h-14 items-center gap-2.5 px-3.5 md:justify-center lg:justify-start"
          >
            <img src="/favicon.svg" alt="" className="size-7" />
            <span className="hidden font-medium lg:inline">Tasky</span>
          </Link>
          <div className="px-2 pb-1">
            <TeamSwitcher onFindTeam={openFind} />
          </div>
          <nav aria-label="Main" className="flex flex-1 flex-col gap-0.5 overflow-y-auto p-2">
            {main.map((item) => (
              <NavItem key={item.to} item={item} />
            ))}
            {isAdmin && (
              <div className="mt-3 flex flex-col gap-0.5 border-t border-border pt-3 lg:mt-4 lg:border-0 lg:pt-0">
                <p className="mb-1 hidden px-2.5 text-[11px] font-medium uppercase tracking-wide text-fg-muted/70 lg:block">
                  Team admin
                </p>
                {ADMIN.map((item) => (
                  <NavItem key={item.to} item={item} />
                ))}
              </div>
            )}
          </nav>
          <div className="space-y-0.5 border-t border-border p-2">
            <NavItem item={{ to: '/settings', label: 'Settings', icon: Settings }} />
            <ThemeButton withLabel />
            <ApiStatusDot />
          </div>
        </motion.aside>

        <div className="flex min-w-0 flex-1 flex-col pb-24 md:pb-0">
          <motion.header
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.22 }}
            className="glass-bar sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border px-4"
          >
            <Link to="/" className="shrink-0 md:hidden" aria-label="Tasky home">
              <img src="/favicon.svg" alt="" className="size-7" />
            </Link>
            <Breadcrumb />
            <button
              type="button"
              onClick={openPalette}
              aria-label="Search or jump to"
              className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-full border border-border bg-surface px-3 text-sm text-fg-muted transition-colors hover:border-fg-muted/40 hover:text-fg md:rounded-control lg:ml-4 lg:max-w-sm"
            >
              <Search aria-hidden className="size-4 shrink-0" />
              <span className="min-w-0 flex-1 truncate text-left">
                <span className="md:hidden">Search tasks…</span>
                <span className="hidden md:inline">Search or jump to…</span>
              </span>
              <span className="hidden gap-1 sm:flex">
                <Kbd>Ctrl</Kbd>
                <Kbd>K</Kbd>
              </span>
            </button>
            <div className="flex shrink-0 items-center gap-1 md:ml-auto">
              {/* Phones: New task sits in the bottom bar; the bell and theme live in the
                  profile menu, so the top bar is just logo, search and avatar. */}
              {canCreate && (
                <Button
                  variant="primary"
                  onClick={openCreate}
                  title="New task (C)"
                  className="hidden md:inline-flex"
                >
                  <Plus aria-hidden className="size-4" />
                  New task
                </Button>
              )}
              <span className="hidden md:block">
                <NotificationBell />
              </span>
              <Menu>
                <MenuTrigger asChild>
                  <button
                    type="button"
                    aria-label="Account menu"
                    className="ml-1 rounded-full outline-offset-2 transition-transform active:scale-95"
                  >
                    <Avatar user={user} size={30} />
                  </button>
                </MenuTrigger>
                <MenuContent align="end">
                  <MenuLabel>
                    <span className="block text-sm text-fg">{user.name}</span>
                    <span className="block">{user.email}</span>
                    {active && (
                      <span className="block">
                        <span className="capitalize">{role}</span> in {active.name}
                      </span>
                    )}
                  </MenuLabel>
                  <MenuSeparator />
                  {phone && (
                    <>
                      <MenuItem
                        onSelect={() => {
                          navigate('/notifications')
                        }}
                      >
                        <Bell className="size-4" /> Notifications
                        {unread > 0 && (
                          <span className="ml-auto rounded-full bg-danger px-1.5 text-[11px] font-medium tabular-nums text-white">
                            {unread > 99 ? '99+' : unread}
                          </span>
                        )}
                      </MenuItem>
                      <MenuItem onSelect={toggleTheme}>
                        {theme === 'dark' ? (
                          <Sun className="size-4" />
                        ) : (
                          <Moon className="size-4" />
                        )}
                        {theme === 'dark' ? 'Light theme' : 'Dark theme'}
                      </MenuItem>
                      <MenuSeparator />
                    </>
                  )}
                  <MenuItem
                    onSelect={() => {
                      navigate('/settings')
                    }}
                  >
                    <Settings className="size-4" /> Settings
                  </MenuItem>
                  <MenuItem
                    onSelect={() => {
                      setShortcutsOpen(true)
                    }}
                  >
                    <Keyboard className="size-4" /> Keyboard shortcuts
                    <span className="ml-auto">
                      <Kbd>?</Kbd>
                    </span>
                  </MenuItem>
                  <MenuItem
                    onSelect={() => {
                      navigate('/status')
                    }}
                  >
                    <Activity className="size-4" /> System status
                  </MenuItem>
                  <MenuSeparator />
                  <MenuItem
                    onSelect={() => {
                      if (active) openFind()
                      else navigate('/')
                    }}
                  >
                    <Users className="size-4" /> Create or join a team
                  </MenuItem>
                  <MenuSeparator />
                  <MenuItem onSelect={() => void logout()}>
                    <LogOut className="size-4" /> Sign out
                  </MenuItem>
                </MenuContent>
              </Menu>
            </div>
          </motion.header>

          <OfflineBanner />
          <main className="mx-auto w-full max-w-[1280px] flex-1 px-4 py-6 sm:px-6">
            {needsTeam ? <NoTeamHome /> : (children ?? <PageTransition />)}
          </main>
        </div>

        {/* Phone bottom bar. The "+" sits low in a round notch cut out of the bar (only its
            top third rises above the edge), so the bar never covers the button. The glass is three pieces (flat, notched
            middle, flat) and the border line follows the notch. */}
        <nav aria-label="Main (mobile)" className="fixed inset-x-0 bottom-0 z-30 md:hidden">
          <div aria-hidden className="pointer-events-none absolute inset-0 flex">
            <div className="tabbar-glass flex-1 border-t border-border" />
            {canCreate && (
              <div className="relative w-[128px] shrink-0">
                {/* The notch reads as a clean ring in the page colour, so text scrolling
                    underneath never shows around the button. */}
                <div className="absolute left-[33px] top-[-23px] size-[62px] rounded-full bg-canvas" />
                <div className="tabbar-glass tabbar-notch absolute inset-0" />
                <svg
                  className="absolute left-0 top-0 h-[40px] w-[128px] overflow-visible"
                  viewBox="0 0 128 40"
                >
                  {/* Fill the whole notch (shoulders included) in the page colour. */}
                  <path
                    className="fill-canvas"
                    d="M25 0 A 8 8 0 0 1 33 8 A 31 31 0 0 0 95 8 A 8 8 0 0 1 103 0 Z"
                  />
                  <path
                    d="M0 0.5 H 25 A 7.5 7.5 0 0 1 32.5 8 A 31.5 31.5 0 0 0 95.5 8 A 7.5 7.5 0 0 1 103 0.5 H 128"
                    fill="none"
                    stroke="var(--border)"
                    strokeWidth="1"
                  />
                </svg>
              </div>
            )}
            <div className="tabbar-glass flex-1 border-t border-border" />
          </div>

          <div className="relative flex items-center px-1 pb-[env(safe-area-inset-bottom)]">
            {main
              .filter((i) => BOTTOM.includes(i.to))
              .slice(0, 2)
              .map((item) => (
                <NavItem key={item.to} item={item} compact />
              ))}
            {canCreate && (
              <div className="relative h-14 w-[128px] shrink-0">
                <motion.button
                  type="button"
                  onClick={openCreate}
                  aria-label="New task"
                  title="New task"
                  whileTap={{ scale: 0.9 }}
                  className="btn-glow absolute left-[40px] top-[-16px] flex size-12 items-center justify-center rounded-full text-white"
                >
                  <Plus aria-hidden className="size-[22px]" />
                </motion.button>
              </div>
            )}
            {main
              .filter((i) => BOTTOM.includes(i.to))
              .slice(2)
              .map((item) => (
                <NavItem key={item.to} item={item} compact />
              ))}
            <button
              type="button"
              onClick={() => {
                setMoreOpen(true)
              }}
              title="More"
              className={`relative mx-1 my-1.5 flex h-11 flex-1 items-center justify-center rounded-control ${moreActive ? 'text-fg' : 'text-fg-muted'}`}
            >
              {moreActive && <span className="absolute inset-0 rounded-control bg-accent/10" />}
              <MenuIcon aria-hidden className="relative size-5" />
              <span className="sr-only">More</span>
            </button>
          </div>
        </nav>
      </div>

      <MoreSheet
        open={moreOpen}
        onOpenChange={setMoreOpen}
        isAdmin={isAdmin}
        main={main}
        onShortcuts={() => {
          setShortcutsOpen(true)
        }}
      />
      <ShortcutsDialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
      <TeamFinderDialog open={findOpen} onOpenChange={setFindOpen} />
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        onCreate={openCreate}
        canCreate={canCreate}
        isAdmin={isAdmin}
        toggleTheme={toggleTheme}
      />
      {canCreate && <CreateIncidentDrawer open={createOpen} onOpenChange={setCreateOpen} />}
    </ShellContext.Provider>
  )
}
