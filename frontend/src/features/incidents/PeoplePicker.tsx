import { ChevronDown, UserX } from 'lucide-react'
import type { ReactNode } from 'react'

import type { UserPublic } from '@/api/client'
import { useDashboard, useUsers } from '@/api/queries'
import {
  Menu,
  MenuCheckItem,
  MenuContent,
  MenuItem,
  MenuLabel,
  MenuSeparator,
  MenuTrigger,
} from '@/components/menu'
import { Avatar } from '@/components/ui'

/** Assignee picker: active members and admins (viewers cannot be assigned). */
export function PeoplePicker({
  value,
  onChange,
  disabled = false,
  label = 'Assigned to',
  className = '',
  open,
  onOpenChange,
  trigger,
}: {
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** Replace the field-style button with a custom trigger (row quick action). */
  trigger?: ReactNode
  value: UserPublic | null
  onChange: (user: UserPublic | null) => void
  disabled?: boolean
  label?: string
  className?: string
}) {
  const { data: users = [] } = useUsers()
  const assignable = users.filter((u) => u.role !== 'viewer')
  // Workload next to each name (spec 11.5), from the cached dashboard summary.
  const { data: dashboard } = useDashboard()
  const load = new Map(dashboard?.open_by_assignee.map((r) => [r.user?.id ?? '', r.count]))

  return (
    <Menu {...(open !== undefined ? { open } : {})} {...(onOpenChange ? { onOpenChange } : {})}>
      <MenuTrigger asChild disabled={disabled}>
        {trigger ?? (
          <button
            type="button"
            aria-label={`${label}: ${value?.name ?? 'Not assigned'}`}
            className={`flex h-9 w-full items-center gap-2 rounded-control border border-border bg-canvas px-2.5 text-left text-sm transition-colors hover:border-fg-muted/40 disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
          >
            {value ? (
              <Avatar user={value} size={22} />
            ) : (
              <span className="flex size-[22px] items-center justify-center rounded-full border border-dashed border-fg-muted/50">
                <UserX aria-hidden className="size-3 text-fg-muted" />
              </span>
            )}
            <span className={`flex-1 truncate ${value ? '' : 'text-fg-muted'}`}>
              {value?.name ?? 'Not assigned'}
            </span>
            {!disabled && <ChevronDown aria-hidden className="size-4 text-fg-muted" />}
          </button>
        )}
      </MenuTrigger>
      <MenuContent className="max-h-80 w-64 overflow-y-auto">
        <MenuLabel>{label}</MenuLabel>
        {assignable.map((user) => (
          <MenuItem
            key={user.id}
            onSelect={() => {
              onChange(user)
            }}
          >
            <Avatar user={user} size={22} />
            <span className="flex-1 truncate">{user.name}</span>
            {user.id === value?.id ? (
              <span className="text-xs text-accent">current</span>
            ) : (
              <span
                className="text-xs tabular-nums text-fg-muted"
                title={`${load.get(user.id) ?? 0} open`}
              >
                {load.get(user.id) ?? 0}
              </span>
            )}
          </MenuItem>
        ))}
        <MenuSeparator />
        <MenuItem
          onSelect={() => {
            onChange(null)
          }}
          disabled={!value}
        >
          <UserX className="size-4" /> Remove assignment
        </MenuItem>
      </MenuContent>
    </Menu>
  )
}

/** Overlapping avatars for several people, then their names. */
export function AssigneeStack({
  people,
  size = 22,
  max = 3,
}: {
  people: UserPublic[]
  size?: number
  max?: number
}) {
  if (!people.length) return <span className="text-fg-muted">Not assigned yet</span>
  const shown = people.slice(0, max)
  const first = people.map((p) => p.name.split(' ')[0])
  const label =
    people.length === 1
      ? (people[0]?.name ?? '')
      : `${first.slice(0, 2).join(', ')}${people.length > 2 ? ` +${people.length - 2}` : ''}`
  return (
    <span className="flex min-w-0 items-center gap-2" title={people.map((p) => p.name).join(', ')}>
      <span className="flex shrink-0 items-center">
        {shown.map((p, i) => (
          <span key={p.id} className={`rounded-full ring-2 ring-surface ${i ? '-ml-1.5' : ''}`}>
            <Avatar user={p} size={size} />
          </span>
        ))}
      </span>
      <span className="truncate">{label}</span>
    </span>
  )
}

/**
 * Several assignees: tick people in or out (the menu stays open). The first chosen leads.
 * Each change is applied at once; the server emails the people newly ticked.
 */
export function AssigneesPicker({
  value,
  onChange,
  disabled = false,
  className = '',
}: {
  value: UserPublic[]
  onChange: (people: UserPublic[]) => void
  disabled?: boolean
  className?: string
}) {
  const { data: users = [] } = useUsers()
  const assignable = users.filter((u) => u.role !== 'viewer')
  const { data: dashboard } = useDashboard()
  const load = new Map(dashboard?.open_by_assignee.map((r) => [r.user?.id ?? '', r.count]))
  const chosen = new Set(value.map((p) => p.id))
  const names = value.map((p) => p.name).join(', ')

  return (
    <Menu>
      <MenuTrigger asChild disabled={disabled}>
        <button
          type="button"
          aria-label={`Assigned to: ${names || 'nobody yet'}`}
          className={`flex min-h-9 w-full items-center gap-2 rounded-control border border-border bg-canvas px-2.5 py-1 text-left text-sm transition-colors hover:border-fg-muted/40 disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
        >
          {value.length ? (
            <span className="min-w-0 flex-1">
              <AssigneeStack people={value} />
            </span>
          ) : (
            <>
              <span className="flex size-[22px] items-center justify-center rounded-full border border-dashed border-fg-muted/50">
                <UserX aria-hidden className="size-3 text-fg-muted" />
              </span>
              <span className="flex-1 truncate text-fg-muted">Choose who works on it</span>
            </>
          )}
          {!disabled && <ChevronDown aria-hidden className="size-4 shrink-0 text-fg-muted" />}
        </button>
      </MenuTrigger>
      <MenuContent className="max-h-80 w-64 overflow-y-auto">
        <MenuLabel>Assign to (one or more people)</MenuLabel>
        {assignable.map((user) => (
          <MenuCheckItem
            key={user.id}
            checked={chosen.has(user.id)}
            onCheckedChange={(on) => {
              onChange(on ? [...value, user] : value.filter((p) => p.id !== user.id))
            }}
          >
            <Avatar user={user} size={22} />
            <span className="flex-1 truncate">{user.name}</span>
            {value[0]?.id === user.id && value.length > 1 ? (
              <span className="text-xs text-accent">lead</span>
            ) : (
              <span
                className="text-xs tabular-nums text-fg-muted"
                title={`${load.get(user.id) ?? 0} open`}
              >
                {load.get(user.id) ?? 0}
              </span>
            )}
          </MenuCheckItem>
        ))}
        <MenuSeparator />
        <MenuItem
          onSelect={() => {
            onChange([])
          }}
          disabled={!value.length}
        >
          <UserX className="size-4" /> Remove everyone
        </MenuItem>
      </MenuContent>
    </Menu>
  )
}
