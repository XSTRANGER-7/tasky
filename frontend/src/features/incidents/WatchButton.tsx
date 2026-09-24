import { AnimatePresence, motion } from 'framer-motion'
import { Eye, EyeOff, UserPlus, X } from 'lucide-react'
import { toast } from 'sonner'

import type { Incident } from '@/api/client'
import { usePeopleOnIncident, useWatch } from '@/api/notifications'
import { useUsers } from '@/api/queries'
import { useAuth } from '@/auth/useAuth'
import {
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
} from '@/components/menu'
import { Avatar, Button } from '@/components/ui'
import { toastError } from '@/lib/toast'
import { useTeam } from '@/team/useTeam'

/** Watch / unwatch toggle for the page header. */
export function WatchButton({ incident }: { incident: Incident }) {
  const watch = useWatch(incident.key)
  const watching = incident.watching
  if (incident.is_deleted) return null
  return (
    <Button
      variant="ghost"
      aria-pressed={watching}
      title={
        watching
          ? 'You get notified about every change. Click to stop.'
          : 'Get notified about comments and resolution'
      }
      disabled={watch.isPending}
      onClick={() => {
        watch.mutate(!watching, {
          onSuccess: (inc) => {
            toast.success(inc.watching ? `Watching ${inc.key}` : `Stopped watching ${inc.key}`)
          },
          onError: (err) => {
            toastError(err, 'Could not update watching')
          },
        })
      }}
      className={watching ? 'text-accent' : 'text-fg-muted'}
    >
      {watching ? (
        <Eye aria-hidden className="size-4" />
      ) : (
        <EyeOff aria-hidden className="size-4" />
      )}
      <span className="hidden sm:inline">{watching ? 'Watching' : 'Watch'}</span>
    </Button>
  )
}

const SHOWN = 5

/** Overlapping avatars of everyone watching, for the properties panel. */
export function Watchers({ incident }: { incident: Incident }) {
  const { watchers } = incident
  if (!watchers.length) return <span className="text-fg-muted">Nobody yet</span>
  const extra = watchers.length - SHOWN
  return (
    <span
      className="flex items-center"
      aria-label={`Watched by ${watchers.map((w) => w.name).join(', ')}`}
    >
      <AnimatePresence initial={false}>
        {watchers.slice(0, SHOWN).map((w, i) => (
          <motion.span
            key={w.id}
            title={w.name}
            initial={{ opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.6 }}
            className={`rounded-full ring-2 ring-surface ${i ? '-ml-1.5' : ''}`}
          >
            <Avatar user={w} size={22} />
          </motion.span>
        ))}
      </AnimatePresence>
      {extra > 0 && <span className="ml-1.5 text-xs text-fg-muted">+{extra}</span>}
    </span>
  )
}

/**
 * Everyone following the task, and (for the team's admins) "Add people": the teammate
 * added is emailed and hears about every update from then on. Admins can also take people
 * off; everyone else follows or leaves with the Watch button.
 */
export function PeopleOnIncident({ incident }: { incident: Incident }) {
  const { user } = useAuth()
  const { canManage } = useTeam()
  const { data: team = [] } = useUsers()
  const { add, remove } = usePeopleOnIncident(incident.key)
  const following = new Set(incident.watchers.map((w) => w.id))
  const candidates = team.filter((u) => !following.has(u.id))
  // Only the team's admins add or remove other people; anyone may leave themself.
  const canRemove = (id: string) => canManage || id === user?.id

  if (incident.is_deleted || !canManage) return <Watchers incident={incident} />

  return (
    <span className="flex items-center gap-2">
      <Watchers incident={incident} />
      <Menu>
        <MenuTrigger asChild>
          <button
            type="button"
            aria-label="Add people"
            title="Add people"
            className="inline-flex size-6 items-center justify-center rounded-full border border-dashed border-border text-fg-muted transition-colors hover:border-accent hover:text-accent"
          >
            <UserPlus aria-hidden className="size-3.5" />
          </button>
        </MenuTrigger>
        <MenuContent align="end" className="w-64">
          {incident.watchers.length > 0 && (
            <>
              <MenuLabel>Following</MenuLabel>
              {incident.watchers.map((w) => (
                <MenuItem
                  key={w.id}
                  disabled={!canRemove(w.id) || remove.isPending}
                  onSelect={() => {
                    remove.mutate(w.id, {
                      onSuccess: () => {
                        toast.success(
                          w.id === user?.id ? 'You stopped following this' : `Removed ${w.name}`,
                        )
                      },
                      onError: (err) => {
                        toastError(err, 'Could not remove them')
                      },
                    })
                  }}
                >
                  <Avatar user={w} size={20} />
                  <span className="min-w-0 flex-1 truncate">{w.name}</span>
                  {canRemove(w.id) && (
                    <X aria-label={`Remove ${w.name}`} className="size-3.5 text-fg-muted" />
                  )}
                </MenuItem>
              ))}
              <MenuSeparator />
            </>
          )}
          <MenuLabel>Add a teammate</MenuLabel>
          {candidates.length === 0 ? (
            <p className="px-2.5 py-2 text-xs text-fg-muted">
              Everyone in the team is already here.
            </p>
          ) : (
            candidates.map((u) => (
              <MenuItem
                key={u.id}
                disabled={add.isPending}
                onSelect={() => {
                  add.mutate(u.id, {
                    onSuccess: () => {
                      toast.success(
                        u.id === user?.id ? `Following ${incident.key}` : `Added ${u.name}`,
                        u.id === user?.id ? {} : { description: 'They were emailed about it.' },
                      )
                    },
                    onError: (err) => {
                      toastError(err, 'Could not add them')
                    },
                  })
                }}
              >
                <Avatar user={u} size={20} />
                <span className="min-w-0 flex-1 truncate">{u.name}</span>
                <span className="text-[11px] capitalize text-fg-muted">{u.role}</span>
              </MenuItem>
            ))
          )}
        </MenuContent>
      </Menu>
    </span>
  )
}
