import type { TeamRole } from '@/api/client'

const styles: Record<TeamRole, string> = {
  admin: 'border-accent/50 bg-accent/10 text-accent',
  member: 'border-border text-fg',
  viewer: 'border-border text-fg-muted',
}

export function TeamRoleBadge({ role }: { role: TeamRole }) {
  return (
    <span
      className={`inline-flex h-5 items-center rounded-full border px-2 text-xs capitalize ${styles[role]}`}
    >
      {role}
    </span>
  )
}
