import { motion } from 'framer-motion'
import { ShieldAlert } from 'lucide-react'
import type { ReactNode } from 'react'

import { useTeam } from '@/team/useTeam'

/** Team-admin pages render this for everyone else (the API refuses them anyway). There is
 * no platform-wide admin: these pages show the active team's admins their own team. */
export function AdminOnly({ children, what }: { children: ReactNode; what: string }) {
  const { canManage, active } = useTeam()
  if (canManage) return <>{children}</>
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="mx-auto flex max-w-md flex-col items-center gap-2 py-20 text-center"
    >
      <span className="flex size-14 items-center justify-center rounded-full border border-border bg-surface">
        <ShieldAlert aria-hidden className="size-6 text-fg-muted" />
      </span>
      <h1 className="text-md font-medium">Team admins only</h1>
      <p className="text-sm text-fg-muted">
        {what} is visible to the admins of {active?.name ?? 'this team'}.
      </p>
    </motion.div>
  )
}
