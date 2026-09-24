/**
 * @mention autocomplete for the comment editor. The handle is the email local part,
 * exactly what the backend's mention parser resolves (`@mira` -> mira@demo.io).
 */
import { useId, useMemo, useState, type KeyboardEvent, type RefObject } from 'react'

import type { UserPublic } from '@/api/client'
import { Avatar } from '@/components/ui'

/** An `@` at the start or after whitespace/punctuation, followed by the partial handle. */
const TRIGGER = /(?:^|[\s([{,;:!?])@([a-zA-Z0-9._-]{0,64})$/

export function handleOf(user: Pick<UserPublic, 'email'>): string {
  return (user.email.split('@')[0] ?? '').toLowerCase()
}

export interface MentionMatch {
  start: number // index of the `@`
  query: string
}

export function findMention(value: string, caret: number): MentionMatch | null {
  const m = TRIGGER.exec(value.slice(0, caret))
  if (!m) return null
  const query = m[1] ?? ''
  return { start: caret - query.length - 1, query }
}

export function rankUsers(users: UserPublic[], query: string, limit = 6): UserPublic[] {
  const q = query.toLowerCase()
  const score = (u: UserPublic) => {
    const handle = handleOf(u)
    const name = u.name.toLowerCase()
    if (handle.startsWith(q)) return 0
    if (name.split(/\s+/).some((part) => part.startsWith(q))) return 1
    if (handle.includes(q) || name.includes(q)) return 2
    return -1
  }
  return users
    .map((u) => [u, score(u)] as const)
    .filter(([, s]) => s >= 0)
    .sort((a, b) => a[1] - b[1] || a[0].name.localeCompare(b[0].name))
    .slice(0, limit)
    .map(([u]) => u)
}

export function useMentions({
  value,
  onChange,
  users,
  textarea,
}: {
  value: string
  onChange: (v: string) => void
  users: UserPublic[] | undefined
  textarea: RefObject<HTMLTextAreaElement | null>
}) {
  const listId = useId()
  const [match, setMatch] = useState<MentionMatch | null>(null)
  const [active, setActive] = useState(0)
  const [dismissedAt, setDismissedAt] = useState<number | null>(null)

  const options = useMemo(
    () => (match && users ? rankUsers(users, match.query) : []),
    [match, users],
  )
  const open = options.length > 0 && dismissedAt !== match?.start

  /** Re-read the caret; call after every change, click or caret move. */
  const sync = (el: HTMLTextAreaElement) => {
    const next = findMention(el.value, el.selectionStart)
    if (next?.start !== match?.start || next?.query !== match?.query) setActive(0)
    setMatch(next)
    if (!next) setDismissedAt(null)
  }

  const pick = (user: UserPublic) => {
    const el = textarea.current
    if (!match || !el) return
    const insert = `@${handleOf(user)} `
    const caret = el.selectionStart
    const next = value.slice(0, match.start) + insert + value.slice(caret)
    onChange(next)
    setMatch(null)
    const pos = match.start + insert.length
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(pos, pos)
    })
  }

  /** Returns true when the key was handled by the menu. */
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>): boolean => {
    if (!open) return false
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const step = e.key === 'ArrowDown' ? 1 : -1
      setActive((i) => (i + step + options.length) % options.length)
      return true
    }
    if ((e.key === 'Enter' && !e.metaKey && !e.ctrlKey) || e.key === 'Tab') {
      const user = options[active]
      if (!user) return false
      e.preventDefault()
      pick(user)
      return true
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation() // do not close a surrounding dialog
      setDismissedAt(match?.start ?? null)
      return true
    }
    return false
  }

  const activeId = open ? `${listId}-${active}` : undefined
  const inputProps = {
    role: 'combobox' as const,
    'aria-autocomplete': 'list' as const,
    'aria-expanded': open,
    'aria-controls': open ? listId : undefined,
    'aria-activedescendant': activeId,
  }

  const menu = open ? (
    <ul
      id={listId}
      role="listbox"
      aria-label="Mention someone"
      className="popover-content absolute left-2 top-full z-30 mt-1 w-64 overflow-hidden rounded-card border border-border bg-elevated p-1 shadow-[var(--shadow-elevated)]"
      data-state="open"
    >
      {options.map((u, i) => (
        <li
          key={u.id}
          id={`${listId}-${i}`}
          role="option"
          aria-selected={i === active}
          onMouseDown={(e) => {
            e.preventDefault() // keep focus in the textarea
            pick(u)
          }}
          onMouseEnter={() => {
            setActive(i)
          }}
          className={`flex cursor-default items-center gap-2 rounded-control px-2 py-1.5 text-sm ${
            i === active ? 'bg-accent/10' : ''
          }`}
        >
          <Avatar user={u} size={22} />
          <span className="min-w-0 flex-1 truncate">{u.name}</span>
          <span className="font-mono text-xs text-fg-muted">@{handleOf(u)}</span>
        </li>
      ))}
    </ul>
  ) : null

  const close = () => {
    setMatch(null)
  }

  return { sync, onKeyDown, inputProps, menu, open, close }
}
