import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { useAuthConfig } from '@/api/queries'
import { useAuth } from '@/auth/useAuth'
import { Button, TextField } from '@/components/ui'

import {
  AuthLayout,
  Divider,
  FormError,
  FormNotice,
  GoogleButton,
  PasswordField,
} from './AuthLayout'
import { fieldErrors } from './fieldErrors'
import { OAUTH_ERRORS } from './oauthErrors'

const DEMO_ACCOUNTS = [
  { label: 'Admin', email: 'admin@demo.io' },
  { label: 'Member', email: 'mira@demo.io' },
  { label: 'Viewer', email: 'sam@demo.io' },
] as const
const DEMO_PASSWORD = 'demo1234'

export function LoginPage() {
  const { status, login } = useAuth()
  // What this deployment offers: demo buttons only on demo installs (their password is
  // public), the register link only when self-registration is open, Google when set up.
  const { data: config } = useAuthConfig()
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()
  const state = location.state as { from?: string; notice?: string } | null
  const from = state?.from ?? '/'
  const oauthError = params.get('error')

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(
    oauthError ? (OAUTH_ERRORS[oauthError] ?? OAUTH_ERRORS.google_failed) : null,
  )
  const [submitting, setSubmitting] = useState(false)
  const [shake, setShake] = useState(0)

  if (status === 'authenticated') return <Navigate to={from} replace />

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await login(email, password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(err)
      setShake((n) => n + 1)
    } finally {
      setSubmitting(false)
    }
  }

  const errors = fieldErrors(error)

  return (
    <AuthLayout
      title="Sign in to Tasky"
      subtitle="Welcome back. Pick up where your team left off."
      shake={shake}
      footer={
        config?.allow_self_register && (
          <>
            New here?{' '}
            <Link to="/register" className="font-medium text-accent hover:underline">
              Create one
            </Link>
          </>
        )
      }
    >
      {config?.google_enabled && (
        <>
          <GoogleButton next={from} />
          <Divider label="or sign in with email" />
        </>
      )}

      <form onSubmit={(e) => void onSubmit(e)} className="space-y-4" noValidate>
        {state?.notice && !error && <FormNotice>{state.notice}</FormNotice>}
        <TextField
          label="Email"
          type="email"
          autoComplete="username"
          required
          autoFocus
          value={email}
          onChange={(e) => {
            setEmail(e.target.value)
          }}
          error={errors.email}
        />
        <div>
          <PasswordField
            label="Password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => {
              setPassword(e.target.value)
            }}
            error={errors.password}
          />
          <div className="mt-1.5 flex justify-end">
            <Link to="/forgot-password" className="text-xs text-accent hover:underline">
              Forgot password?
            </Link>
          </div>
        </div>
        {Object.keys(errors).length === 0 && <FormError error={error} />}
        <Button
          type="submit"
          variant="primary"
          loading={submitting}
          className="btn-glow h-11 w-full rounded-[14px]"
        >
          Sign in
        </Button>
      </form>

      {config?.demo_mode && (
        <div className="mt-5 border-t border-border pt-4">
          <p className="mb-2 text-xs text-fg-muted">Demo accounts (password {DEMO_PASSWORD})</p>
          <div className="grid grid-cols-3 gap-2">
            {DEMO_ACCOUNTS.map((demo) => (
              <Button
                key={demo.email}
                variant="secondary"
                className="h-8 text-xs"
                onClick={() => {
                  setEmail(demo.email)
                  setPassword(DEMO_PASSWORD)
                  setError(null)
                }}
              >
                {demo.label}
              </Button>
            ))}
          </div>
        </div>
      )}
    </AuthLayout>
  )
}
