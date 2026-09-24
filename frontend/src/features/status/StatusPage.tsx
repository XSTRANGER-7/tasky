import { useEffect, useState } from 'react'

import { api, unwrap, type TeamPerson, type User } from '@/api/client'
import { SystemStatus } from '@/components/SystemStatus'
import { Avatar, RoleBadge } from '@/components/ui'

type TeamMember = TeamPerson & Partial<Pick<User, 'is_active'>>

function useTeam() {
  const [team, setTeam] = useState<TeamMember[] | null>(null)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    let active = true
    unwrap(api.GET('/api/v1/users'))
      .then((users) => {
        if (active) setTeam(users)
      })
      .catch((err: unknown) => {
        if (active) setError(err)
      })
    return () => {
      active = false
    }
  }, [])

  return { team, error }
}

function TeamCard() {
  const { team, error } = useTeam()

  return (
    <section
      aria-labelledby="team-heading"
      className="rounded-card border border-border bg-surface p-5 shadow-[var(--shadow-elevated)]"
    >
      <h2 id="team-heading" className="text-md font-medium">
        Team
      </h2>
      {error ? (
        <p className="mt-3 text-sm text-danger">Could not load the team.</p>
      ) : !team ? (
        <ul className="mt-3 space-y-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <li key={i} className="h-7 animate-pulse rounded-control bg-elevated" />
          ))}
        </ul>
      ) : (
        <ul className="mt-3 divide-y divide-[color:var(--border)]">
          {team.map((member) => (
            <li key={member.id} className="flex items-center gap-3 py-2">
              <Avatar user={member} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">
                  {member.name}
                  {member.is_active === false && (
                    <span className="ml-2 text-xs text-fg-muted">(deactivated)</span>
                  )}
                </p>
                <p className="truncate text-xs text-fg-muted">{member.email}</p>
              </div>
              <RoleBadge role={member.role} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function StatusPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-medium">System status</h1>
        <p className="text-sm text-fg-muted">API health, version and who is on the team.</p>
      </header>
      <div className="grid gap-6 md:grid-cols-2">
        <SystemStatus />
        <TeamCard />
      </div>
    </div>
  )
}
