import { Check, ChevronsUpDown, Plus, Settings2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import {
  Menu,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
} from '@/components/menu'
import { TeamRoleBadge } from '@/features/teams/TeamRoleBadge'
import { TeamMark } from '@/features/teams/TeamMark'
import { useTeam } from '@/team/useTeam'

/** Which team the workspace shows. Switching drops the old team's cached data. */
export function TeamSwitcher({ onFindTeam }: { onFindTeam: () => void }) {
  const { teams, active, role, switchTeam } = useTeam()
  const navigate = useNavigate()
  if (!active) {
    return (
      <button
        type="button"
        onClick={() => {
          navigate('/')
        }}
        title="Create or join a team"
        className="flex w-full items-center gap-2.5 rounded-control border border-dashed border-border p-1.5 text-left text-sm text-fg-muted transition-colors hover:border-accent/50 hover:text-fg md:justify-center lg:justify-start"
      >
        <span className="flex size-7 shrink-0 items-center justify-center rounded-control bg-accent/10 text-accent">
          <Plus aria-hidden className="size-4" />
        </span>
        <span className="hidden lg:inline">No team yet</span>
      </button>
    )
  }

  return (
    <Menu>
      <MenuTrigger asChild>
        <button
          type="button"
          aria-label={`Team: ${active.name}. Switch team`}
          className="flex w-full items-center gap-2.5 rounded-control border border-transparent p-1.5 text-left transition-colors hover:border-border hover:bg-elevated md:justify-center lg:justify-start"
        >
          <TeamMark name={active.name} size={28} />
          <span className="hidden min-w-0 flex-1 lg:block">
            <span className="block truncate text-sm font-medium">{active.name}</span>
            <span className="block truncate text-[11px] capitalize text-fg-muted">{role}</span>
          </span>
          <ChevronsUpDown aria-hidden className="hidden size-4 text-fg-muted lg:block" />
        </button>
      </MenuTrigger>
      <MenuContent align="start" className="w-64">
        <MenuLabel>Your teams</MenuLabel>
        {teams.map((t) => (
          <MenuItem
            key={t.id}
            onSelect={() => {
              if (t.id === active.id) return
              switchTeam(t.id)
              navigate('/')
            }}
          >
            <TeamMark name={t.name} size={22} />
            <span className="min-w-0 flex-1 truncate">{t.name}</span>
            {t.id === active.id ? (
              <Check aria-label="Current team" className="size-4 text-accent" />
            ) : (
              t.my_role && <TeamRoleBadge role={t.my_role} />
            )}
          </MenuItem>
        ))}
        <MenuSeparator />
        <MenuItem
          onSelect={() => {
            navigate('/team')
          }}
        >
          <Settings2 className="size-4" /> Team members and settings
        </MenuItem>
        <MenuItem onSelect={onFindTeam}>
          <Plus className="size-4" /> Create or join a team
        </MenuItem>
      </MenuContent>
    </Menu>
  )
}
