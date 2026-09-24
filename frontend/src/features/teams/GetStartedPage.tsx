import { AnimatePresence, motion } from 'framer-motion'
import { ArrowRight, LogOut, Users } from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { useCreateTeam } from '@/api/teams'
import { useAuth } from '@/auth/useAuth'
import { Button, TextField } from '@/components/ui'
import { FormError } from '@/features/auth/AuthLayout'
import { useTeam } from '@/team/useTeam'

import { TeamMark } from './TeamMark'

/**
 * First sign-in: one centred question, "create your team?". No team search and no team
 * list here on purpose; skipping leads on to the workspace (or the team finder when the
 * account has no team yet). Answered once: `user.onboarded` then keeps it away.
 */
export function GetStartedPage() {
  const { user, logout, finishOnboarding } = useAuth()
  const { refresh, switchTeam } = useTeam()
  const create = useCreateTeam()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [skipping, setSkipping] = useState(false)
  const [skipError, setSkipError] = useState<unknown>(null)
  const busy = useRef(false)

  if (!user) return null
  if (user.onboarded && !busy.current) return <Navigate to="/" replace />

  const trimmed = name.trim()
  const valid = trimmed.length >= 2

  async function onCreate(event: FormEvent) {
    event.preventDefault()
    if (!valid || create.isPending) return
    busy.current = true
    try {
      const team = await create.mutateAsync({ name: trimmed })
      await finishOnboarding()
      await refresh() // the new team must be in "my teams" before the workspace opens
      switchTeam(team.id)
      toast.success(`${team.name} is ready`, { description: 'You are its admin.' })
      navigate('/', { replace: true })
    } catch {
      busy.current = false // the error is shown under the form
    }
  }

  async function onSkip() {
    setSkipping(true)
    setSkipError(null)
    busy.current = true
    try {
      await finishOnboarding()
      navigate('/', { replace: true }) // no team yet: the workspace guard offers the finder
    } catch (error) {
      busy.current = false
      setSkipError(error)
      setSkipping(false)
    }
  }

  return (
    <div className="auth-backdrop flex min-h-dvh flex-col">
      <header className="flex h-16 items-center justify-between px-4 sm:px-6">
        <Link to="/" className="flex items-center gap-2.5" aria-label="Tasky home">
          <img src="/favicon.svg" alt="" className="size-8" />
          <span className="font-medium">Tasky</span>
        </Link>
        <Button
          variant="ghost"
          onClick={() => {
            void logout()
          }}
        >
          <LogOut className="size-4" /> Sign out
        </Button>
      </header>

      <main className="flex flex-1 items-center justify-center px-4 pb-20">
        <motion.section
          aria-labelledby="get-started-title"
          initial={{ opacity: 0, y: 14, scale: 0.985 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
          className="w-full max-w-[400px] rounded-[20px] border border-border bg-surface/85 p-8 text-center shadow-[var(--shadow-elevated)] backdrop-blur-xl"
        >
          {/* The badge fills in as the name is typed: a preview of the new team. */}
          <div className="mx-auto flex w-fit rounded-[14px] ring-4 ring-accent/10">
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.span
                key={trimmed.slice(0, 1).toUpperCase() || '?'}
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.8 }}
                transition={{ duration: 0.18 }}
              >
                {trimmed ? (
                  <TeamMark name={trimmed} size={56} />
                ) : (
                  <span className="flex size-14 items-center justify-center rounded-control bg-accent/15 text-accent">
                    <Users aria-hidden className="size-6" />
                  </span>
                )}
              </motion.span>
            </AnimatePresence>
          </div>

          <h1 id="get-started-title" className="mt-5 text-xl font-semibold tracking-tight">
            Create your team
          </h1>
          <p className="mt-1 text-sm text-fg-muted">You will be its admin.</p>

          <form onSubmit={(e) => void onCreate(e)} className="mt-6 space-y-3 text-left">
            <TextField
              label="Team name"
              autoFocus
              required
              minLength={2}
              maxLength={80}
              placeholder="e.g. Payments On-call"
              value={name}
              onChange={(e) => {
                setName(e.target.value)
              }}
            />
            <FormError error={create.error ?? skipError} />
            <Button
              type="submit"
              variant="primary"
              className="h-11 w-full"
              loading={create.isPending}
              disabled={!valid || skipping}
            >
              Create team <ArrowRight aria-hidden className="size-4" />
            </Button>
          </form>

          <button
            type="button"
            onClick={() => {
              void onSkip()
            }}
            disabled={skipping || create.isPending}
            className="mt-4 text-sm text-fg-muted transition-colors hover:text-fg disabled:opacity-50"
          >
            {skipping ? 'One moment…' : 'Skip for now'}
          </button>
        </motion.section>
      </main>
    </div>
  )
}
