import * as Dialog from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'framer-motion'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'

import { spring } from '@/lib/motion'

/** Centred dialog: overlay fades, panel scales 0.95 -> 1 on a spring, focus trapped. */
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  wide = false,
  size,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  children: ReactNode
  wide?: boolean
  /** md 448 px (default), lg 672 px (same as `wide`), xl 1000 px for two-column content. */
  size?: 'md' | 'lg' | 'xl'
}) {
  const width = { md: 'max-w-md p-5', lg: 'max-w-2xl p-5', xl: 'max-w-[1000px] p-6 sm:p-7' }[
    size ?? (wide ? 'lg' : 'md')
  ]
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
              {...(description ? {} : { 'aria-describedby': undefined })}
              className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center p-4"
            >
              <motion.div
                className={`pointer-events-auto max-h-[90vh] w-full overflow-y-auto rounded-dialog border border-border bg-elevated shadow-[var(--shadow-elevated)] ${width}`}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1, transition: spring }}
                exit={{ opacity: 0, scale: 0.97, transition: { duration: 0.12 } }}
              >
                <div
                  className={`flex items-start justify-between gap-3 ${size === 'xl' ? 'mb-6' : 'mb-4'}`}
                >
                  <div>
                    <Dialog.Title
                      className={
                        size === 'xl'
                          ? 'text-lg font-semibold tracking-tight'
                          : 'text-md font-medium'
                      }
                    >
                      {title}
                    </Dialog.Title>
                    {description && (
                      <Dialog.Description className="mt-0.5 text-sm text-fg-muted">
                        {description}
                      </Dialog.Description>
                    )}
                  </div>
                  <Dialog.Close
                    aria-label="Close"
                    className="rounded-control p-1 text-fg-muted hover:bg-canvas hover:text-fg"
                  >
                    <X className="size-4" />
                  </Dialog.Close>
                </div>
                {children}
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  )
}
