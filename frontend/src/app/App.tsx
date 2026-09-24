import { QueryClientProvider } from '@tanstack/react-query'
import { MotionConfig } from 'framer-motion'
import { lazy, Suspense, type ReactNode } from 'react'
import {
  BrowserRouter,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useParams,
} from 'react-router-dom'
import { Toaster } from 'sonner'

import { AuthProvider } from '@/auth/AuthProvider'
import { RequireAuth } from '@/auth/RequireAuth'
import { RequireOnboarded } from '@/auth/RequireOnboarded'
import { ForgotPasswordPage } from '@/features/auth/ForgotPasswordPage'
import { LoginPage } from '@/features/auth/LoginPage'
import { RegisterPage } from '@/features/auth/RegisterPage'
import { ResetPasswordPage } from '@/features/auth/ResetPasswordPage'
import { PageSkeleton } from '@/components/Loading'
import { makeQueryClient } from '@/lib/queryClient'
import { usePreferences } from '@/lib/theme'
import { TeamGate, TeamProvider } from '@/team/TeamProvider'

import { AppShell } from './shell/AppShell'

// Route-level code splitting: charts (Recharts) and Markdown load only where used.
const DashboardPage = lazy(() =>
  import('@/features/dashboard/DashboardPage').then((m) => ({ default: m.DashboardPage })),
)
const IncidentsPage = lazy(() =>
  import('@/features/incidents/IncidentsPage').then((m) => ({ default: m.IncidentsPage })),
)
const IncidentDetailPage = lazy(() =>
  import('@/features/incidents/IncidentDetailPage').then((m) => ({
    default: m.IncidentDetailPage,
  })),
)
const StatusPage = lazy(() =>
  import('@/features/status/StatusPage').then((m) => ({ default: m.StatusPage })),
)
const NotificationsPage = lazy(() =>
  import('@/features/notifications/NotificationsPage').then((m) => ({
    default: m.NotificationsPage,
  })),
)
const OutboxPage = lazy(() =>
  import('@/features/admin/OutboxPage').then((m) => ({ default: m.OutboxPage })),
)
const ConfigurationPage = lazy(() =>
  import('@/features/admin/ConfigurationPage').then((m) => ({ default: m.ConfigurationPage })),
)
const SettingsPage = lazy(() =>
  import('@/features/settings/SettingsPage').then((m) => ({ default: m.SettingsPage })),
)
const GetStartedPage = lazy(() =>
  import('@/features/teams/GetStartedPage').then((m) => ({ default: m.GetStartedPage })),
)
const TeamPage = lazy(() =>
  import('@/features/teams/TeamPage').then((m) => ({ default: m.TeamPage })),
)

function Page({ children }: { children: ReactNode }) {
  return <Suspense fallback={<PageFallback />}>{children}</Suspense>
}

function PageFallback() {
  return <PageSkeleton />
}

/**
 * Tasks used to be "incidents": old links and emails point at /incidents and
 * /incidents/:ident. Send them to the same place under /tasks, keeping ?view= and the rest.
 */
function LegacyTasksRedirect() {
  const { ident } = useParams()
  const { search, hash } = useLocation()
  const pathname = ident ? `/tasks/${encodeURIComponent(ident)}` : '/tasks'
  return <Navigate to={{ pathname, search, hash }} replace />
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/incidents" element={<LegacyTasksRedirect />} />
      <Route path="/incidents/:ident" element={<LegacyTasksRedirect />} />
      <Route
        element={
          <RequireAuth>
            <TeamProvider>
              <Outlet />
            </TeamProvider>
          </RequireAuth>
        }
      >
        {/* First sign-in: create a team, or continue without one. Shown once. */}
        <Route
          path="/get-started"
          element={
            <Page>
              <GetStartedPage />
            </Page>
          }
        />

        <Route
          element={
            <RequireOnboarded>
              <Outlet />
            </RequireOnboarded>
          }
        >
          {/* The team workspace: everything below acts in the active team. Without a team
              it offers to create or join one instead. */}
          <Route
            element={
              <TeamGate>
                <AppShell />
              </TeamGate>
            }
          >
            <Route
              index
              element={
                <Page>
                  <DashboardPage />
                </Page>
              }
            />
            <Route
              path="/tasks"
              element={
                <Page>
                  <IncidentsPage />
                </Page>
              }
            />
            <Route
              path="/tasks/:ident"
              element={
                <Page>
                  <IncidentDetailPage />
                </Page>
              }
            />
            <Route
              path="/team/:tab?"
              element={
                <Page>
                  <TeamPage />
                </Page>
              }
            />
            {/* The team's admins: its email and the settings it runs on. */}
            <Route
              path="/admin/outbox"
              element={
                <Page>
                  <OutboxPage />
                </Page>
              }
            />
            <Route
              path="/admin/settings"
              element={
                <Page>
                  <ConfigurationPage />
                </Page>
              }
            />
            <Route
              path="/notifications"
              element={
                <Page>
                  <NotificationsPage />
                </Page>
              }
            />
            <Route
              path="/settings"
              element={
                <Page>
                  <SettingsPage />
                </Page>
              }
            />
            <Route
              path="/status"
              element={
                <Page>
                  <StatusPage />
                </Page>
              }
            />
          </Route>
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

function Motion({ children }: { children: ReactNode }) {
  const { motion } = usePreferences()
  const reducedMotion = motion === 'system' ? 'user' : motion === 'reduce' ? 'always' : 'never'
  return <MotionConfig reducedMotion={reducedMotion}>{children}</MotionConfig>
}

const queryClient = makeQueryClient()

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      {/* Honour prefers-reduced-motion, or the manual switch in Settings (spec 12.4). */}
      <Motion>
        <AuthProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </AuthProvider>
        <Toaster
          position="bottom-right"
          theme="system"
          toastOptions={{
            className: '!rounded-card !border-[color:var(--border)] !bg-elevated !text-fg',
          }}
        />
      </Motion>
    </QueryClientProvider>
  )
}
