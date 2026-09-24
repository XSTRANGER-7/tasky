import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { ApiError, api, unwrap } from '@/api/client'
import { Button } from '@/components/ui'

import { AuthLayout, FormError, PasswordField } from './AuthLayout'
import { fieldErrors } from './fieldErrors'
import { PasswordStrength } from './PasswordStrength'

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)

  const footer = (
    <Link to="/login" className="font-medium text-accent hover:underline">
      Back to sign in
    </Link>
  )

  if (!token) {
    return (
      <AuthLayout
        title="This link is incomplete"
        subtitle="Open the link from your email"
        footer={footer}
      >
        <p className="text-sm text-fg-muted">
          The reset link is missing its code. Open it straight from the email, or{' '}
          <Link to="/forgot-password" className="text-accent hover:underline">
            ask for a new one
          </Link>
          .
        </p>
      </AuthLayout>
    )
  }

  const mismatch = confirm.length > 0 && confirm !== password

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (password !== confirm) {
      setError('The two passwords do not match.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await unwrap(api.POST('/api/v1/auth/reset-password', { body: { token, password } }))
      navigate('/login', {
        replace: true,
        state: { notice: 'Password changed. Sign in with your new password.' },
      })
    } catch (err) {
      setError(err)
    } finally {
      setSubmitting(false)
    }
  }

  const errors = fieldErrors(error)
  const expired = error instanceof ApiError && error.code === 'reset_invalid'

  return (
    <AuthLayout
      title="Choose a new password"
      subtitle="You will be signed out on every other device."
      footer={footer}
    >
      <form onSubmit={(e) => void onSubmit(e)} className="space-y-4" noValidate>
        <div>
          <PasswordField
            label="New password"
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
        <PasswordField
          label="Confirm new password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(e) => {
            setConfirm(e.target.value)
          }}
          error={mismatch ? 'Does not match' : undefined}
        />
        {Object.keys(errors).length === 0 && <FormError error={error} />}
        {expired && (
          <p className="text-sm">
            <Link to="/forgot-password" className="text-accent hover:underline">
              Send me a new link
            </Link>
          </p>
        )}
        <Button
          type="submit"
          variant="primary"
          loading={submitting}
          className="btn-glow h-11 w-full rounded-[14px]"
        >
          Save new password
        </Button>
      </form>
    </AuthLayout>
  )
}
