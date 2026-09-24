import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { ApiError } from '@/api/client'
import { useAuthConfig } from '@/api/queries'
import { useAuth } from '@/auth/useAuth'
import { Button, TextField } from '@/components/ui'

import { AuthLayout, Divider, FormError, GoogleButton, PasswordField } from './AuthLayout'
import { fieldErrors } from './fieldErrors'
import { PasswordStrength } from './PasswordStrength'

export function RegisterPage() {
  const { status, register, login } = useAuth()
  const { data: config } = useAuthConfig()
  const navigate = useNavigate()

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)
  const [shake, setShake] = useState(0)

  if (status === 'authenticated') return <Navigate to="/" replace />
  if (config && !config.allow_self_register) {
    return (
      <AuthLayout
        title="Registration is closed"
        subtitle="Accounts are created by an admin"
        footer={
          <Link to="/login" className="font-medium text-accent hover:underline">
            Back to sign in
          </Link>
        }
      >
        <p className="text-sm text-fg-muted">
          Ask an administrator to add you from the Admin Console, then sign in.
        </p>
      </AuthLayout>
    )
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await register(name, email, password)
      await login(email, password)
      // New accounts start without a team: onboarding offers to create or join one.
      navigate('/get-started', { replace: true })
    } catch (err) {
      setError(err)
      setShake((n) => n + 1)
    } finally {
      setSubmitting(false)
    }
  }

  const errors = fieldErrors(error)
  if (error instanceof ApiError && error.code === 'email_taken') errors.email = error.message
  const general = Object.keys(errors).length === 0 ? error : null

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Then create a team, or ask to join your team's workspace."
      shake={shake}
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" className="font-medium text-accent hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      {config?.google_enabled && (
        <>
          <GoogleButton next="/" label="Sign up with Google" />
          <Divider label="or with email" />
        </>
      )}
      <form onSubmit={(e) => void onSubmit(e)} className="space-y-4" noValidate>
        <TextField
          label="Name"
          autoComplete="name"
          required
          maxLength={100}
          value={name}
          onChange={(e) => {
            setName(e.target.value)
          }}
          error={errors.name}
        />
        <TextField
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => {
            setEmail(e.target.value)
          }}
          error={errors.email}
        />
        <div>
          <PasswordField
            label="Password"
            autoComplete="new-password"
            required
            minLength={8}
            maxLength={128}
            hint="At least 8 characters"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value)
            }}
            error={errors.password}
          />
          <PasswordStrength password={password} />
        </div>
        <FormError error={general} />
        <Button
          type="submit"
          variant="primary"
          loading={submitting}
          className="btn-glow h-11 w-full rounded-[14px]"
        >
          Create account
        </Button>
      </form>
    </AuthLayout>
  )
}
