import { lazy, Suspense, useRef, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { BrandSplash } from '@/components/Loading'

import { useAuth } from './useAuth'

const LandingPage = lazy(() =>
  import('@/features/landing/LandingPage').then((m) => ({ default: m.LandingPage })),
)

/** Gate for signed-in routes. The server still enforces every permission. A signed-out
 * visitor to the home page gets the landing page; anywhere else (or right after signing
 * out), the sign-in page. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()
  // Signing out goes to the sign-in page, not the landing page.
  const wasSignedIn = useRef(false)
  if (status === 'authenticated') wasSignedIn.current = true

  if (status === 'loading') {
    return <BrandSplash />
  }
  if (status === 'anonymous') {
    if (location.pathname === '/' && !wasSignedIn.current) {
      return (
        <Suspense fallback={<BrandSplash />}>
          <LandingPage />
        </Suspense>
      )
    }
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <>{children}</>
}
