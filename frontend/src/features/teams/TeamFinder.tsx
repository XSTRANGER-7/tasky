import { AnimatePresence, motion } from 'framer-motion'
import { Clock, Plus, Search, UserPlus, Users, X } from 'lucide-react'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { ApiError, type JoinRequest, type Team } from '@/api/client'
import { useCancelRequest, useCreateTeam, useDiscoverTeams, useRequestToJoin } from '@/api/teams'
import { useAuth } from '@/auth/useAuth'
import { Modal } from '@/components/Modal'
import { Button, TextField } from '@/components/ui'
import { FormError } from '@/features/auth/AuthLayout'
import { useTeam } from '@/team/useTeam'

import { TeamMark } from './TeamMark'
import { TeamRoleBadge } from './TeamRoleBadge'

/**
 * Create a team or ask to join one: the main page for someone in no team, and a dialog
 * ("Create or join a team") for everyone else. `onOpen` runs with a team that was just
 * created, once it is in "my teams".
 */
export function TeamFinder({
  onOpen,
  inDialog = false,
}: {
  onOpen: (team: Team) => void
  /** Inside a dialog: two flat columns split by a rule, no card-in-card frames. */
  inDialog?: boolean
}) {
  const { requests, refresh } = useTeam()
  const pending = requests.filter((r) => r.status === 'pending')
  const create = (
    <CreateTeamCard
      flat={inDialog}
      onCreated={(team) => {
        // The new team must be in "my teams" before the workspace opens it.
        void refresh().then(() => {
          onOpen(team)
        })
      }}
    />
  )
  return (
    <div className="space-y-5">
      {pending.length > 0 && <PendingRequests requests={pending} />}
      {inDialog ? (
        <div className="grid grid-cols-1 gap-8 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] md:gap-0">
          <div className="min-w-0 md:border-r md:border-border md:pr-7">{create}</div>
          <div className="min-w-0 border-t border-border pt-6 md:border-t-0 md:pl-7 md:pt-0">
            <JoinTeamCard flat />
          </div>
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[1fr_1.25fr]">
          {create}
          <JoinTeamCard />
        </div>
      )}
    </div>
  )
}

/** The workspace for someone who belongs to no team yet (skipped, left, or removed). */
export function NoTeamHome() {
  const { user } = useAuth()
  const { switchTeam } = useTeam()
  const first = user?.name.split(' ')[0] ?? 'there'
  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-xl font-semibold tracking-tight">You are not in a team yet, {first}</h1>
      <p className="mb-6 mt-1 text-fg-muted">
        Tasks live inside teams. Start your own, or ask to join an existing one.
      </p>
      <TeamFinder
        onOpen={(team) => {
          switchTeam(team.id)
        }}
      />
    </div>
  )
}

/** "Create or join a team" from the menus, for people who already have a team. */
export function TeamFinderDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { switchTeam } = useTeam()
  const navigate = useNavigate()
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Create or join a team"
      description="Start a new team, or ask to join one. Its admins approve who joins."
      size="xl"
    >
      <TeamFinder
        inDialog
        onOpen={(team) => {
          onOpenChange(false)
          switchTeam(team.id)
          navigate('/')
        }}
      />
    </Modal>
  )
}

function Card({
  icon: Icon,
  title,
  subtitle,
  flat = false,
  children,
}: {
  icon: typeof Users
  title: string
  subtitle: string
  flat?: boolean
  children: ReactNode
}) {
  return (
    <section
      className={
        flat
          ? 'flex h-full flex-col'
          : 'rounded-card border border-border bg-surface/85 p-5 shadow-[var(--shadow-elevated)] backdrop-blur-xl'
      }
    >
      <div className="mb-4 flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-control bg-accent/10 text-accent">
          <Icon aria-hidden className="size-[18px]" />
        </span>
        <div>
          <h2 className="font-medium">{title}</h2>
          <p className="text-sm text-fg-muted">{subtitle}</p>
        </div>
      </div>
      {children}
    </section>
  )
}

function CreateTeamCard({
  onCreated,
  flat = false,
}: {
  onCreated: (team: Team) => void
  flat?: boolean
}) {
  const create = useCreateTeam()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    try {
      const team = await create.mutateAsync({ name, description })
      toast.success(`${team.name} is ready`, { description: 'You are its admin.' })
      onCreated(team)
    } catch {
      // shown below
    }
  }

  return (
    <Card
      icon={Plus}
      title="Create a team"
      subtitle="You become its admin and approve who joins."
      flat={flat}
    >
      <form onSubmit={(e) => void onSubmit(e)} className="space-y-4">
        <TextField
          label="Team name"
          autoFocus={flat}
          required
          minLength={2}
          maxLength={80}
          placeholder="e.g. Payments On-call"
          value={name}
          onChange={(e) => {
            setName(e.target.value)
          }}
        />
        <div>
          <label htmlFor="team-description" className="mb-1 block text-sm text-fg-muted">
            What does this team look after? <span className="text-fg-muted/70">(optional)</span>
          </label>
          <textarea
            id="team-description"
            rows={3}
            maxLength={500}
            value={description}
            onChange={(e) => {
              setDescription(e.target.value)
            }}
            className="w-full resize-none rounded-control border border-border bg-canvas px-3 py-2 text-sm outline-none focus:border-accent"
          />
        </div>
        <FormError error={create.error} />
        <Button
          type="submit"
          variant="primary"
          className="w-full"
          loading={create.isPending}
          disabled={name.trim().length < 2}
        >
          Create team
        </Button>
      </form>
    </Card>
  )
}

function JoinTeamCard({ flat = false }: { flat?: boolean }) {
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebounced(query.trim())
    }, 250)
    return () => {
      window.clearTimeout(t)
    }
  }, [query])
  const results = useDiscoverTeams(debounced)

  return (
    <Card
      icon={UserPlus}
      title="Join a team"
      subtitle="Ask to join. Its admins get an email and approve or decline."

      flat={flat}
    >
      <label className="relative block">
        <span className="sr-only">Search teams</span>
        <Search
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-fg-muted"
        />
        <input
          type="search"
          placeholder="Search teams by name"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
          }}
          className="h-9 w-full rounded-control border border-border bg-canvas pl-9 pr-3 text-sm outline-none focus:border-accent"
        />
      </label>
      <ul
        className={`mt-3 space-y-2 overflow-y-auto ${flat ? 'max-h-[min(360px,40vh)] min-h-[120px] pr-1' : 'max-h-[340px]'}`}
        aria-busy={results.isFetching}
      >
        {results.isLoading && <li className="shimmer h-14 rounded-control" />}
        {results.data?.length === 0 && (
          <li className="rounded-control border border-dashed border-border px-3 py-6 text-center text-sm text-fg-muted">
            {debounced
              ? `No team matches "${debounced}".`
              : 'No teams exist yet. Create the first one.'}
          </li>
        )}
        {results.data?.map((team) => (
          <DiscoverRow key={team.id} team={team} />
        ))}
      </ul>
    </Card>
  )
}

function DiscoverRow({ team }: { team: Team }) {
  const request = useRequestToJoin()
  const cancel = useCancelRequest()
  const { refresh } = useTeam()
  const [asking, setAsking] = useState(false)
  const [message, setMessage] = useState('')

  async function send() {
    try {
      await request.mutateAsync({ teamId: team.id, message })
      toast.success(`Request sent to ${team.name}`, {
        description: 'Its admins were emailed. You will be notified when they decide.',
      })
      setAsking(false)
      void refresh()
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Could not send the request')
    }
  }

  return (
    <li className="rounded-control border border-border bg-canvas/60 px-3 py-2.5">
      <div className="flex items-center gap-3">
        <TeamMark name={team.name} size={32} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{team.name}</p>
          <p className="truncate text-xs text-fg-muted">
            {team.description ||
              `${team.member_count} ${team.member_count === 1 ? 'member' : 'members'}`}
          </p>
        </div>
        {team.my_role ? (
          <TeamRoleBadge role={team.my_role} />
        ) : team.pending_request_id ? (
          <span className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 text-xs text-priority-medium">
              <Clock className="size-3.5" /> Pending
            </span>
            <Button
              variant="ghost"
              className="h-7 px-2 text-xs"
              loading={cancel.isPending}
              onClick={() => {
                void cancel.mutateAsync(team.pending_request_id ?? '').then(() => refresh())
              }}
            >
              Withdraw
            </Button>
          </span>
        ) : (
          <Button
            variant={asking ? 'ghost' : 'secondary'}
            className="h-8 text-xs"
            onClick={() => {
              setAsking((v) => !v)
            }}
            aria-expanded={asking}
          >
            {asking ? <X className="size-3.5" /> : <UserPlus className="size-3.5" />}
            {asking ? 'Cancel' : 'Ask to join'}
          </Button>
        )}
      </div>
      <AnimatePresence initial={false}>
        {asking && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="mt-3 space-y-2">
              <label htmlFor={`msg-${team.id}`} className="block text-xs text-fg-muted">
                A note for the admins (optional)
              </label>
              <textarea
                id={`msg-${team.id}`}
                rows={2}
                maxLength={500}
                placeholder="Who you are and why you need access"
                value={message}
                onChange={(e) => {
                  setMessage(e.target.value)
                }}
                className="w-full resize-none rounded-control border border-border bg-canvas px-3 py-2 text-sm outline-none focus:border-accent"
              />
              <Button
                variant="primary"
                className="h-8 w-full text-xs"
                loading={request.isPending}
                onClick={() => {
                  void send()
                }}
              >
                Send request
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  )
}

function PendingRequests({ requests }: { requests: JoinRequest[] }) {
  const cancel = useCancelRequest()
  const { refresh } = useTeam()
  return (
    <section aria-labelledby="pending-requests">
      <h2 id="pending-requests" className="mb-3 text-sm font-medium text-fg-muted">
        Waiting for approval
      </h2>
      <ul className="space-y-2">
        {requests.map((r) => (
          <li
            key={r.id}
            className="flex items-center gap-3 rounded-card border border-priority-medium/30 bg-priority-medium/5 px-4 py-3"
          >
            <Clock aria-hidden className="size-4 text-priority-medium" />
            <p className="min-w-0 flex-1 text-sm">
              You asked to join <span className="font-medium">{r.team.name}</span>. Its admins have
              been emailed; you will get an email and a notification when they decide.
            </p>
            <Button
              variant="ghost"
              className="h-8 text-xs"
              loading={cancel.isPending}
              onClick={() => {
                void cancel.mutateAsync(r.id).then(() => refresh())
              }}
            >
              Withdraw
            </Button>
          </li>
        ))}
      </ul>
    </section>
  )
}
