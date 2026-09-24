import { AnimatePresence, motion } from 'framer-motion'
import { Check, ChevronDown } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { toast } from 'sonner'

import type { Incident, Status } from '@/api/client'
import { useTransition } from '@/api/queries'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { StatusPill } from '@/components/incident-ui'
import { Menu, MenuContent, MenuItem, MenuLabel, MenuTrigger } from '@/components/menu'
import { statusLabel, statusTone, transitionLabel } from '@/lib/incident'
import { toastError } from '@/lib/toast'

/**
 * The status pill doubles as the lifecycle control. It offers exactly the server's
 * ``allowed_transitions`` for this viewer; the change is optimistic and rolls back
 * (with a toast) if the server refuses. Resolve and close ask for an optional note.
 */
export function StatusControl({
  incident,
  open,
  onOpenChange,
  trigger,
}: {
  incident: Incident
  /** Controlled menu state, e.g. opened by the S shortcut in the list. */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** Replace the pill with a custom trigger (row quick action). */
  trigger?: ReactNode
}) {
  const mutation = useTransition(incident.key)
  const [pending, setPending] = useState<Status | null>(null)
  const [done, setDone] = useState(0)
  useEffect(() => {
    if (!done) return
    const id = window.setTimeout(() => {
      setDone(0)
    }, 900)
    return () => {
      window.clearTimeout(id)
    }
  }, [done])
  const moves = incident.allowed_transitions

  function apply(to: Status, note?: string) {
    setPending(null)
    mutation.mutate(
      { status: to, ...(note ? { note } : {}) },
      {
        onSuccess: (updated) => {
          setDone((n) => n + 1)
          toast.success(`${updated.key} is now ${statusLabel[updated.status].toLowerCase()}`)
        },
        onError: (err) => {
          toastError(err, 'Could not change the status')
        },
      },
    )
  }

  if (moves.length === 0 && !trigger) {
    return <StatusPill status={incident.status} className="h-7 px-2.5 text-sm" />
  }

  return (
    <>
      <Menu {...(open !== undefined ? { open } : {})} {...(onOpenChange ? { onOpenChange } : {})}>
        <MenuTrigger asChild>
          {trigger ?? (
            <button
              type="button"
              aria-label={`Status: ${statusLabel[incident.status]}. Change status`}
              className="group relative inline-flex items-center rounded-full"
            >
              <motion.span
                key={incident.status}
                initial={{ opacity: 0.4, scale: 0.94 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ type: 'spring', stiffness: 380, damping: 32 }}
                className="inline-flex"
              >
                <StatusPill
                  status={incident.status}
                  className="h-7 px-2.5 text-sm group-hover:brightness-110"
                />
              </motion.span>
              <ChevronDown aria-hidden className="-ml-1 size-4 text-fg-muted" />
              <AnimatePresence>
                {done > 0 && (
                  <motion.span
                    key={done}
                    aria-hidden
                    initial={{ scale: 0, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    exit={{ opacity: 0, transition: { duration: 0.2 } }}
                    transition={{ type: 'spring', stiffness: 500, damping: 18 }}
                    className="absolute -right-2 -top-2 flex size-4 items-center justify-center rounded-full bg-status-resolved text-white"
                  >
                    <Check className="size-3" strokeWidth={3} />
                  </motion.span>
                )}
              </AnimatePresence>
            </button>
          )}
        </MenuTrigger>
        <MenuContent>
          <MenuLabel>{moves.length ? 'Move to' : 'No status change available'}</MenuLabel>
          {moves.map((to) => (
            <MenuItem
              key={to}
              onSelect={() => {
                if (to === 'resolved' || to === 'closed') setPending(to)
                else apply(to)
              }}
            >
              <span aria-hidden className={`size-2 rounded-full ${statusTone[to].dot}`} />
              <span className="flex-1">{transitionLabel(incident.status, to)}</span>
              <span className="text-xs text-fg-muted">{statusLabel[to]}</span>
            </MenuItem>
          ))}
        </MenuContent>
      </Menu>

      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) setPending(null)
        }}
        title={pending === 'closed' ? `Close ${incident.key}?` : `Resolve ${incident.key}`}
        description={
          pending === 'closed'
            ? 'Closed tasks are final and read-only.'
            : 'Describe the fix so the timeline tells the whole story.'
        }
        confirmLabel={pending === 'closed' ? 'Close task' : 'Resolve'}
        withNote
        notePlaceholder={
          pending === 'closed' ? 'Optional closing note' : 'What fixed it? (optional)'
        }
        onConfirm={(note) => {
          if (pending) apply(pending, note)
        }}
      />
    </>
  )
}
