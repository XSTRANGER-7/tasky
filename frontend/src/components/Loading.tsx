import { motion } from 'framer-motion'

/*
 * Loading states that look like the app they are loading: a branded splash while we find
 * out who you are, then a skeleton of the workspace (sidebar, header, cards) while your
 * teams load, and a page skeleton while a page's code arrives. Each swaps to the real UI
 * in place, so nothing jumps. The shimmer and the ring stop under "reduce motion".
 */

/** First paint: is anyone signed in? The logo breathes inside a turning ring. */
export function BrandSplash({ label = 'Loading' }: { label?: string }) {
  return (
    <div
      className="aurora flex min-h-dvh flex-col items-center justify-center gap-5"
      role="status"
      aria-busy="true"
      aria-label={label}
    >
      <div className="relative flex size-24 items-center justify-center">
        <span aria-hidden className="loader-ring absolute inset-0 rounded-full" />
        <motion.img
          src="/logo.svg"
          alt=""
          className="size-12 drop-shadow-[0_10px_30px_rgba(110,139,255,0.55)]"
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: [1, 1.06, 1], opacity: 1 }}
          transition={{
            opacity: { duration: 0.3 },
            scale: { duration: 1.8, repeat: Infinity, ease: 'easeInOut' },
          }}
        />
      </div>
      <motion.p
        className="text-sm font-medium tracking-tight text-fg-muted"
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        Tasky
      </motion.p>
    </div>
  )
}

function Bone({ className = '' }: { className?: string }) {
  return <div aria-hidden className={`shimmer rounded-lg ${className}`} />
}

/** A glass card with placeholder lines, like the dashboard's. */
function CardBones({ lines = 2, className = '' }: { lines?: number; className?: string }) {
  return (
    <div
      className={`rounded-card border border-border bg-surface p-5 shadow-[var(--shadow-elevated)] ${className}`}
    >
      <Bone className="h-3 w-24" />
      <Bone className="mt-4 h-7 w-16" />
      {Array.from({ length: lines - 1 }, (_, i) => (
        <Bone key={i} className="mt-3 h-3 w-3/4" />
      ))}
    </div>
  )
}

/** The inside of a page while it loads: title, stat cards, two panels. */
export function PageSkeleton({
  label = 'Loading',
  announce = true,
}: {
  label?: string
  /** False inside another loader, which already announces itself. */
  announce?: boolean
}) {
  return (
    <motion.div
      className="space-y-6"
      {...(announce
        ? { role: 'status', 'aria-busy': true, 'aria-label': label }
        : { 'aria-hidden': true })}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.25, delay: 0.1 }}
    >
      <div>
        <Bone className="h-7 w-48" />
        <Bone className="mt-2 h-3.5 w-32" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <CardBones key={i} />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
        <div className="rounded-card border border-border bg-surface p-5 shadow-[var(--shadow-elevated)]">
          <Bone className="h-4 w-40" />
          <Bone className="mt-2 h-3 w-28" />
          <Bone className="mt-6 h-52 w-full rounded-xl" />
        </div>
        <div className="rounded-card border border-border bg-surface p-5 shadow-[var(--shadow-elevated)]">
          <Bone className="h-4 w-36" />
          <div className="mx-auto mt-6 size-36 rounded-full border-[14px] border-[rgb(var(--text-muted)/0.12)]" />
          {[0, 1, 2].map((i) => (
            <Bone key={i} className="mt-4 h-3 w-full" />
          ))}
        </div>
      </div>
    </motion.div>
  )
}

/** The whole workspace before your teams arrive: sidebar, header and a page skeleton. */
export function AppSkeleton() {
  return (
    <div
      className="app-wallpaper flex min-h-dvh"
      role="status"
      aria-busy="true"
      aria-label="Loading your workspace"
    >
      <aside className="sticky top-0 hidden h-dvh w-14 shrink-0 flex-col gap-2 border-r border-border bg-surface p-2 md:flex lg:w-60">
        <div className="flex h-12 items-center gap-2.5 px-1.5">
          <img src="/logo.svg" alt="" className="size-7" />
          <Bone className="hidden h-3.5 w-20 lg:block" />
        </div>
        <Bone className="h-10 w-full rounded-control" />
        <div className="mt-2 space-y-1.5">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="flex h-9 items-center gap-3 px-2.5">
              <Bone className="size-4 rounded" />
              <Bone className="hidden h-3 flex-1 lg:block" />
            </div>
          ))}
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="glass-bar sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border px-4">
          <Bone className="h-3.5 w-20" />
          <Bone className="h-9 max-w-sm flex-1 rounded-control" />
          <div className="ml-auto flex items-center gap-2">
            <Bone className="hidden h-9 w-28 rounded-control sm:block" />
            <Bone className="size-8 rounded-full" />
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1280px] flex-1 px-4 py-6 sm:px-6">
          <PageSkeleton announce={false} />
        </main>
      </div>
    </div>
  )
}
