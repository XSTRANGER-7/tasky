import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'

import { getActiveTeam, setActiveTeam, type TeamRole } from '@/api/client'
import { useMyTeams } from '@/api/teams'
import { useAuth } from '@/auth/useAuth'
import { AppSkeleton } from '@/components/Loading'

import { TeamContext, type EffectiveRole, type TeamContextValue } from './context'
import { useTeam } from './useTeam'

/** Query keys whose data belongs to one team: dropped whenever the active team changes.
 * `admin` covers the team admin pages (outbox, settings, AI usage). */
const TEAM_SCOPED = new Set([
  'incidents',
  'users',
  'dashboard',
  'ai',
  'attachments',
  'palette',
  'admin',
])

function toEffective(role: TeamRole | null): EffectiveRole {
  return role ?? 'viewer'
}

export function TeamProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const mine = useMyTeams(Boolean(user))
  const [activeId, setActiveId] = useState<string | null>(getActiveTeam)

  const teams = useMemo(() => mine.data?.teams ?? [], [mine.data])
  const requests = useMemo(() => mine.data?.requests ?? [], [mine.data])
  const active = useMemo(() => teams.find((t) => t.id === activeId) ?? null, [teams, activeId])

  const apply = useCallback(
    (next: string | null) => {
      if (next === getActiveTeam() && next === activeId) return
      setActiveTeam(next)
      setActiveId(next)
      qc.removeQueries({ predicate: (q) => TEAM_SCOPED.has(String(q.queryKey[0])) })
    },
    [activeId, qc],
  )

  // Pick the active team: a `?team=` link wins, then the last one used, then the first.
  // Only teams I belong to: there is no admin who can open someone else's team.
  const requested = params.get('team')
  useEffect(() => {
    // Wait for in-flight refetches: a team created or joined a moment ago is not in the
    // cached list yet, and must not be "corrected" back to another team.
    if (!mine.isSuccess || mine.isFetching) return
    const ids = new Set(teams.map((t) => t.id))
    const candidate = requested ?? activeId
    const next = candidate && ids.has(candidate) ? candidate : (teams[0]?.id ?? null)
    if (next !== activeId || next !== getActiveTeam()) apply(next)
    if (requested) {
      params.delete('team')
      setParams(params, { replace: true })
    }
  }, [mine.isSuccess, mine.isFetching, teams, requested, activeId, apply, params, setParams])

  const role = active?.my_role ?? null
  const effectiveRole = toEffective(role)
  // Loaded, but the active team is still being picked (or a new one is arriving).
  const settling = mine.isSuccess && !active && (mine.isFetching || teams.length > 0)

  const value = useMemo<TeamContextValue>(
    () => ({
      status: mine.isError ? 'error' : !mine.isSuccess || settling ? 'loading' : 'ready',
      teams,
      requests,
      active,
      role,
      effectiveRole,
      canWork: effectiveRole !== 'viewer',
      canManage: role === 'admin',
      switchTeam: apply,
      refresh: () => mine.refetch(),
    }),
    [mine, settling, teams, requests, active, role, effectiveRole, apply],
  )
  return <TeamContext.Provider value={value}>{children}</TeamContext.Provider>
}

/** Waits for "my teams" before the workspace renders. No redirect: someone in no team
 * gets the workspace too, whose pages then offer to create or join one. */
export function TeamGate({ children }: { children: ReactNode }) {
  const { status } = useTeam()
  if (status === 'error') {
    return (
      <div className="flex min-h-dvh items-center justify-center px-4 text-center">
        <p className="text-sm text-fg-muted">
          Could not load your teams. Check your connection and reload the page.
        </p>
      </div>
    )
  }
  if (status === 'loading') {
    return <AppSkeleton />
  }
  return <>{children}</>
}
