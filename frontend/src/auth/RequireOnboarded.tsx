import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { useAuth } from './useAuth'

/** First sign-in: send new accounts to the "create your team?" page until it is answered. */
export function RequireOnboarded({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  if (user && !user.onboarded) return <Navigate to="/get-started" replace />
  return <>{children}</>
}
