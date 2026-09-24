import * as Dialog from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useState, type ReactNode } from 'react'

import { spring } from '@/lib/motion'

import { Button } from './ui'

/** Centred dialog: overlay fades, panel scales 0.95 -> 1 on a spring, focus trapped. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  danger = false,
  withNote = false,
  notePlaceholder = 'Optional note for the timeline',
  loading = false,
  onConfirm,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: ReactNode
  confirmLabel: string
  danger?: boolean
  withNote?: boolean
  notePlaceholder?: string
  loading?: boolean
  onConfirm: (note: string) => void
  children?: ReactNode
}) {
  const [note, setNote] = useState('')
  useEffect(() => {
    if (open) setNote('')
  }, [open])

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0, transition: { duration: 0.12 } }}
              />
            </Dialog.Overlay>
            <Dialog.Content
              forceMount
              className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center p-4"
            >
              <motion.form
                onSubmit={(e) => {
                  e.preventDefault()
                  onConfirm(note.trim())
                }}
                className="pointer-events-auto w-full max-w-md rounded-dialog border border-border bg-elevated p-5 shadow-[var(--shadow-elevated)]"
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1, transition: spring }}
                exit={{ opacity: 0, scale: 0.97, transition: { duration: 0.12 } }}
              >
                <Dialog.Title className="text-md font-medium">{title}</Dialog.Title>
                <Dialog.Description className="mt-1 text-sm text-fg-muted">
                  {description ?? ''}
                </Dialog.Description>
                {children}
                {withNote && (
                  <textarea
                    autoFocus
                    rows={3}
                    maxLength={1000}
                    value={note}
                    onChange={(e) => {
                      setNote(e.target.value)
                    }}
                    placeholder={notePlaceholder}
                    aria-label="Note"
                    className="mt-4 w-full resize-none rounded-control border border-border bg-canvas px-3 py-2 text-sm outline-none focus:border-accent"
                  />
                )}
                <div className="mt-5 flex justify-end gap-2">
                  <Dialog.Close asChild>
                    <Button>Cancel</Button>
                  </Dialog.Close>
                  <Button
                    type="submit"
                    variant="primary"
                    loading={loading}
                    className={danger ? '!bg-danger hover:!bg-danger/90' : ''}
                    autoFocus={!withNote}
                  >
                    {confirmLabel}
                  </Button>
                </div>
              </motion.form>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  )
}
