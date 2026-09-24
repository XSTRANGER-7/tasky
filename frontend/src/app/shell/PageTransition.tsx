import { motion } from 'framer-motion'
import { useLocation, useOutlet } from 'react-router-dom'

import { ErrorBoundary } from '@/components/ErrorBoundary'

/**
 * Route change (spec 12.3): the new page fades in and rises 6 px. Keyed by pathname only,
 * so changing filters in the query string never re-animates the page.
 *
 * Enter-only on purpose: an exit phase (AnimatePresence mode="wait") could stall with lazy
 * routes, leaving the old page at opacity 0 and the new one never mounted: a blank tab.
 */
export function PageTransition() {
  const location = useLocation()
  const outlet = useOutlet()
  return (
    <motion.div
      key={location.pathname}
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0, transition: { duration: 0.22, ease: [0.16, 1, 0.3, 1] } }}
    >
      <ErrorBoundary resetKey={location.pathname}>{outlet}</ErrorBoundary>
    </motion.div>
  )
}
