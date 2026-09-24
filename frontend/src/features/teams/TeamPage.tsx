import { AnimatePresence, motion } from 'framer-motion'
import { Check, Clock, LogOut, Pencil, Trash2, UserMinus, UserPlus, X } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { NavLink, useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { ApiError, type JoinRequest, type TeamMember, type TeamRole } from '@/api/client'
import {
  TEAM_ROLES,
  useAddMember,
  useChangeMemberRole,
  useDecide,
  useDeleteTeam,
  useRemoveMember,
  useTeamMembers,
  useTeamRequests,
  useUpdateTeam,
} from '@/api/teams'
import { useAuth } from '@/auth/useAuth'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { Modal } from '@/components/Modal'
import { Avatar, Button, TextField } from '@/components/ui'
import { FormError } from '@/features/auth/AuthLayout'
import { formatDateTime, timeAgo } from '@/lib/time'
import { useNow } from '@/lib/useNow'
import { useTeam } from '@/team/useTeam'

import { TeamRoleBadge } from './TeamRoleBadge'
import { TeamMark } from './TeamMark'

type Tab = 'members' | 'requests' | 'settings'

function errorText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

export function TeamPage() {
  const { tab = 'members' } = useParams<{ tab?: Tab }>()
  const { active, role, canManage } = useTeam()
  const requests = useTeamRequests(active?.id ?? null, canManage)
  const pendingCount = requests.data?.filter((r) => r.status === 'pending').length ?? 0
  const [editing, setEditing] = useState(false)

  if (!active) return null
  const tabs: { key: Tab; label: string; show: boolean; badge?: number }[] = [
    { key: 'members', label: 'Members', show: true },
    { key: 'requests', label: 'Join requests', show: canManage, badge: pendingCount },
    { key: 'settings', label: 'Settings', show: true },
  ]

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6 flex flex-wrap items-start gap-4">
        <TeamMark name={active.name} size={52} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-semibold">{active.name}</h1>
            {role && <TeamRoleBadge role={role} />}
          </div>
          <p className="mt-0.5 text-sm text-fg-muted">
            {active.description || 'No description yet.'} · {active.member_count}{' '}
            {active.member_count === 1 ? 'member' : 'members'}
          </p>
        </div>
        {canManage && (
          <Button
            variant="secondary"
            onClick={() => {
              setEditing(true)
            }}
          >
            <Pencil className="size-4" /> Edit
          </Button>
        )}
      </header>

      <nav aria-label="Team sections" className="mb-5 flex gap-1 border-b border-border">
        {tabs
          .filter((t) => t.show)
          .map((t) => (
            <NavLink
              key={t.key}
              to={`/team/${t.key}`}
              end
              className={({ isActive }) =>
                `relative -mb-px flex items-center gap-2 border-b-2 px-3 py-2 text-sm transition-colors ${
                  isActive || (tab === t.key && t.key === 'members')
                    ? 'border-accent text-fg'
                    : 'border-transparent text-fg-muted hover:text-fg'
                }`
              }
            >
              {t.label}
              {Boolean(t.badge) && (
                <span className="rounded-full bg-accent px-1.5 text-[11px] font-medium tabular-nums text-white">
                  {t.badge}
                </span>
              )}
            </NavLink>
          ))}
      </nav>

      <motion.div
        key={tab}
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.18 }}
      >
        {tab === 'requests' && canManage ? (
          <RequestsTab requests={requests.data ?? []} loading={requests.isLoading} />
        ) : tab === 'settings' ? (
          <SettingsTab />
        ) : (
          <MembersTab />
        )}
      </motion.div>

      <EditTeamDialog open={editing} onOpenChange={setEditing} />
    </div>
  )
}

// ---------------------------------------------------------------- members

function MembersTab() {
  const { user } = useAuth()
  const { active, canManage } = useTeam()
  const members = useTeamMembers(active?.id ?? null)
  const change = useChangeMemberRole()
  const remove = useRemoveMember()
  const [removing, setRemoving] = useState<TeamMember | null>(null)
  const now = useNow()
  if (!active) return null

  async function setRole(m: TeamMember, next: TeamRole) {
    try {
      await change.mutateAsync({ teamId: active?.id ?? '', userId: m.user.id, role: next })
      toast.success(`${m.user.name} is now ${next === 'admin' ? 'an' : 'a'} ${next}`, {
        description: `${m.user.name.split(' ')[0]} was emailed.`,
      })
    } catch (err) {
      toast.error(errorText(err, 'Could not change the role'))
    }
  }

  return (
    <div className="space-y-5">
      {canManage && <AddMemberForm teamId={active.id} />}
      <ul className="divide-y divide-border overflow-hidden rounded-card border border-border bg-surface">
        {members.isLoading &&
          [0, 1, 2].map((i) => <li key={i} className="shimmer m-3 h-10 rounded-control" />)}
        {members.data?.map((m) => {
          const self = m.user.id === user?.id
          // Admins manage everyone else (co-admins included); your own role is changed by
          // another admin, so a team can never lose its last admin by accident.
          const editable = canManage && !self
          return (
            <li key={m.user.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <Avatar user={m.user} size={34} />
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 truncate text-sm font-medium">
                  {m.user.name}
                  {self && <span className="text-xs font-normal text-fg-muted">(you)</span>}
                  {!m.is_active && (
                    <span className="rounded-full border border-danger/40 px-1.5 text-[11px] text-danger">
                      Deactivated
                    </span>
                  )}
                </p>
                <p className="truncate text-xs text-fg-muted">
                  {m.user.email} ·{' '}
                  <time dateTime={m.joined_at} title={formatDateTime(m.joined_at)}>
                    joined {timeAgo(m.joined_at, now)}
                  </time>
                </p>
              </div>
              {/* On phones the controls drop under the name, so names are never cut. */}
              <div
                className={`flex items-center gap-2 ${editable ? 'basis-full justify-end pl-[46px] sm:basis-auto sm:pl-0' : ''}`}
              >
                {editable ? (
                  <RoleSelect
                    value={m.role}
                    label={`Team role for ${m.user.name}`}
                    onChange={(next) => {
                      void setRole(m, next)
                    }}
                  />
                ) : (
                  <TeamRoleBadge role={m.role} />
                )}
                {editable && (
                  <Button
                    variant="ghost"
                    className="size-8 px-0"
                    aria-label={`Remove ${m.user.name}`}
                    title="Remove from team"
                    onClick={() => {
                      setRemoving(m)
                    }}
                  >
                    <UserMinus className="size-4" />
                  </Button>
                )}
              </div>
            </li>
          )
        })}
      </ul>
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null)
        }}
        title={`Remove ${removing?.user.name ?? ''}?`}
        description="They lose access to this team's tasks straight away and stop watching them. Their past comments and reports stay."
        confirmLabel="Remove"
        danger
        loading={remove.isPending}
        onConfirm={() => {
          if (!removing) return
          remove
            .mutateAsync({ teamId: active.id, userId: removing.user.id })
            .then(() => {
              toast.success(`${removing.user.name} was removed`)
              setRemoving(null)
            })
            .catch((err: unknown) => toast.error(errorText(err, 'Could not remove')))
        }}
      />
    </div>
  )
}

function RoleSelect({
  value,
  onChange,
  label,
}: {
  value: TeamRole
  onChange: (next: TeamRole) => void
  label: string
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => {
        onChange(e.target.value as TeamRole)
      }}
      className="h-8 rounded-control border border-border bg-canvas px-2 text-sm capitalize outline-none focus:border-accent"
    >
      {TEAM_ROLES.map((r) => (
        <option key={r.value} value={r.value} title={r.hint}>
          {r.label}
        </option>
      ))}
    </select>
  )
}

function AddMemberForm({ teamId }: { teamId: string }) {
  const add = useAddMember()
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<TeamRole>('member')

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    try {
      const member = await add.mutateAsync({ teamId, email, role })
      toast.success(`${member.user.name} added as ${role}`, {
        description: `${member.user.name.split(' ')[0]} was emailed.`,
      })
      setEmail('')
    } catch {
      // shown below
    }
  }

  return (
    <form
      onSubmit={(e) => void onSubmit(e)}
      className="rounded-card border border-border bg-surface p-4"
      aria-label="Add a member"
    >
      <p className="mb-3 flex items-center gap-2 text-sm font-medium">
        <UserPlus className="size-4 text-accent" /> Add someone who already has an account
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <TextField
          label="Email"
          type="email"
          required
          placeholder="teammate@company.com"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value)
          }}
          className="min-w-[220px] flex-1"
        />
        <RoleSelect value={role} onChange={setRole} label="Role" />
        <Button type="submit" variant="primary" loading={add.isPending} disabled={!email.trim()}>
          Add
        </Button>
      </div>
      <div className="mt-2">
        <FormError error={add.error} />
      </div>
      <p className="mt-2 text-xs text-fg-muted">
        No account yet? Ask them to sign up and then request to join; you will get an email.
      </p>
    </form>
  )
}

// ---------------------------------------------------------------- requests

function RequestsTab({ requests, loading }: { requests: JoinRequest[]; loading: boolean }) {
  const pending = requests.filter((r) => r.status === 'pending')
  const decided = requests.filter((r) => r.status !== 'pending')
  const now = useNow()
  return (
    <div className="space-y-6">
      <section aria-labelledby="pending-heading">
        <h2 id="pending-heading" className="mb-2 text-sm font-medium text-fg-muted">
          Waiting for a decision
        </h2>
        {loading && <div className="shimmer h-24 rounded-card" />}
        {!loading && pending.length === 0 && (
          <p className="rounded-card border border-dashed border-border px-4 py-8 text-center text-sm text-fg-muted">
            No one is waiting. New requests show up here, in your notifications, and by email.
          </p>
        )}
        <ul className="space-y-3">
          <AnimatePresence initial={false}>
            {pending.map((r) => (
              <motion.li
                key={r.id}
                layout
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: 24, transition: { duration: 0.15 } }}
              >
                <PendingRequest request={r} />
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      </section>

      {decided.length > 0 && (
        <section aria-labelledby="history-heading">
          <h2 id="history-heading" className="mb-2 text-sm font-medium text-fg-muted">
            History
          </h2>
          <ul className="divide-y divide-border rounded-card border border-border bg-surface">
            {decided.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-sm">
                <Avatar user={r.user} size={26} />
                <span className="min-w-0 flex-1 truncate">
                  <span className="font-medium">{r.user.name}</span>{' '}
                  <span className="text-fg-muted">
                    {r.status === 'approved'
                      ? `joined as ${r.granted_role ?? 'member'}`
                      : r.status === 'rejected'
                        ? 'was declined'
                        : 'withdrew the request'}
                    {r.decided_by && r.status !== 'cancelled' ? ` by ${r.decided_by.name}` : ''}
                  </span>
                </span>
                <time className="text-xs text-fg-muted" dateTime={r.decided_at ?? r.created_at}>
                  {timeAgo(r.decided_at ?? r.created_at, now)}
                </time>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function PendingRequest({ request: r }: { request: JoinRequest }) {
  const decide = useDecide()
  const [role, setRole] = useState<TeamRole>('member')
  const now = useNow()

  async function act(approve: boolean) {
    try {
      await decide.mutateAsync({ requestId: r.id, approve, role })
      toast.success(
        approve ? `${r.user.name} joined as ${role}` : `Declined ${r.user.name}'s request`,
        { description: `${r.user.name.split(' ')[0]} was emailed.` },
      )
    } catch (err) {
      toast.error(errorText(err, 'Could not save the decision'))
    }
  }

  return (
    <div className="rounded-card border border-border bg-surface p-4">
      <div className="flex flex-wrap items-start gap-3">
        <Avatar user={r.user} size={36} />
        <div className="min-w-0 flex-1">
          <p className="text-sm">
            <span className="font-medium">{r.user.name}</span>{' '}
            <span className="text-fg-muted">{r.user.email}</span>
          </p>
          <p className="mt-0.5 flex items-center gap-1 text-xs text-fg-muted">
            <Clock className="size-3" /> asked {timeAgo(r.created_at, now)}
          </p>
          {r.message && (
            <blockquote className="mt-2 border-l-2 border-border pl-3 text-sm text-fg-muted">
              {r.message}
            </blockquote>
          )}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
        <label className="mr-auto flex items-center gap-2 text-xs text-fg-muted">
          Join as
          <RoleSelect value={role} onChange={setRole} label={`Role for ${r.user.name}`} />
        </label>
        <Button
          variant="ghost"
          loading={decide.isPending && !decide.variables.approve}
          onClick={() => {
            void act(false)
          }}
        >
          <X className="size-4" /> Decline
        </Button>
        <Button
          variant="primary"
          loading={decide.isPending && decide.variables.approve}
          onClick={() => {
            void act(true)
          }}
        >
          <Check className="size-4" /> Approve
        </Button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- settings

function SettingsTab() {
  const { user } = useAuth()
  const { active, role, teams, switchTeam, refresh } = useTeam()
  const remove = useRemoveMember()
  const del = useDeleteTeam()
  const navigate = useNavigate()
  const [leaving, setLeaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmName, setConfirmName] = useState('')
  if (!active || !user) return null
  const canDelete = role === 'admin'

  async function afterExit() {
    await refresh()
    const next = teams.find((t) => t.id !== active?.id)
    if (next) switchTeam(next.id)
    navigate('/')
  }

  return (
    <div className="space-y-4">
      {role && (
        <section className="flex flex-wrap items-center gap-4 rounded-card border border-border bg-surface p-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-medium">Leave {active.name}</h2>
            <p className="text-sm text-fg-muted">
              You lose access to its tasks. To come back, you would need to ask again.
              {role === 'admin' && ' If you are the only admin, make someone else an admin first.'}
            </p>
          </div>
          <Button
            variant="secondary"
            onClick={() => {
              setLeaving(true)
            }}
          >
            <LogOut className="size-4" /> Leave team
          </Button>
        </section>
      )}
      {canDelete && (
        <section className="rounded-card border border-danger/40 bg-danger/5 p-4">
          <h2 className="text-sm font-medium text-danger">Delete this team</h2>
          <p className="mt-0.5 text-sm text-fg-muted">
            Permanently deletes the team with every task, comment, attachment and audit event in it.
            This cannot be undone.
          </p>
          <Button
            variant="danger"
            className="mt-3"
            onClick={() => {
              setConfirmName('')
              setDeleting(true)
            }}
          >
            <Trash2 className="size-4" /> Delete team…
          </Button>
        </section>
      )}

      <ConfirmDialog
        open={leaving}
        onOpenChange={setLeaving}
        title={`Leave ${active.name}?`}
        confirmLabel="Leave team"
        danger
        loading={remove.isPending}
        onConfirm={() => {
          remove
            .mutateAsync({ teamId: active.id, userId: user.id })
            .then(() => {
              toast.success(`You left ${active.name}`)
              setLeaving(false)
              return afterExit()
            })
            .catch((err: unknown) => toast.error(errorText(err, 'Could not leave the team')))
        }}
      />
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Delete ${active.name}?`}
        description="Type the team name to confirm. Everything in it is deleted for everyone."
        confirmLabel="Delete forever"
        danger
        loading={del.isPending}
        onConfirm={() => {
          if (confirmName.trim() !== active.name) {
            toast.error('The name does not match')
            return
          }
          del
            .mutateAsync(active.id)
            .then(() => {
              toast.success(`${active.name} was deleted`)
              setDeleting(false)
              return afterExit()
            })
            .catch((err: unknown) => toast.error(errorText(err, 'Could not delete the team')))
        }}
      >
        <TextField
          label={`Team name (${active.name})`}
          value={confirmName}
          onChange={(e) => {
            setConfirmName(e.target.value)
          }}
        />
      </ConfirmDialog>
    </div>
  )
}

function EditTeamDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { active, refresh } = useTeam()
  const update = useUpdateTeam()
  const [name, setName] = useState(active?.name ?? '')
  const [description, setDescription] = useState(active?.description ?? '')
  useEffect(() => {
    if (open && active) {
      setName(active.name)
      setDescription(active.description)
    }
  }, [open, active])

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!active) return
    try {
      await update.mutateAsync({ id: active.id, name, description })
      await refresh()
      toast.success('Team updated')
      onOpenChange(false)
    } catch {
      // shown below
    }
  }

  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Edit team">
      <form onSubmit={(e) => void onSubmit(e)} className="space-y-4">
        <TextField
          label="Team name"
          required
          minLength={2}
          maxLength={80}
          value={name}
          onChange={(e) => {
            setName(e.target.value)
          }}
        />
        <div>
          <label htmlFor="edit-team-description" className="mb-1 block text-sm text-fg-muted">
            Description
          </label>
          <textarea
            id="edit-team-description"
            rows={3}
            maxLength={500}
            value={description}
            onChange={(e) => {
              setDescription(e.target.value)
            }}
            className="w-full resize-none rounded-control border border-border bg-canvas px-3 py-2 text-sm outline-none focus:border-accent"
          />
        </div>
        <FormError error={update.error} />
        <div className="flex justify-end gap-2">
          <Button
            variant="ghost"
            onClick={() => {
              onOpenChange(false)
            }}
          >
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={update.isPending}>
            Save
          </Button>
        </div>
      </form>
    </Modal>
  )
}
