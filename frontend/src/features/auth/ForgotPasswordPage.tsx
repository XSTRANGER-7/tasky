import { MailCheck } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { api, unwrap } from '@/api/client'
import { Button, TextField } from '@/components/ui'

import { AuthLayout, FormError } from './AuthLayout'
import { fieldErrors } from './fieldErrors'

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      // 202 with an empty body: read it as text so no JSON parse can fail.
      await unwrap(api.POST('/api/v1/auth/forgot-password', { body: { email }, parseAs: 'text' }))
      setSentTo(email)
    } catch (err) {
      setError(err)
    } finally {
      setSubmitting(false)
    }
  }

  const back = (
    <Link to="/login" className="font-medium text-accent hover:underline">
      Back to sign in
    </Link>
  )

  if (sentTo) {
    return (
      <AuthLayout title="Check your email" subtitle="A reset link is on its way" footer={back}>
        <div className="flex gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent">
            <MailCheck aria-hidden className="size-5" />
          </span>
          <div className="space-y-2 text-sm">
            <p>
              If an account exists for <span className="font-medium">{sentTo}</span>, we sent it a
              link to choose a new password.
            </p>
            <p className="text-fg-muted">
              The link works once and expires in 30 minutes. Nothing arrived? Check spam, or{' '}
              <button
                type="button"
                className="text-accent hover:underline"
                onClick={() => {
                  setSentTo(null)
                }}
              >
                try again
              </button>
              .
            </p>
          </div>
        </div>
      </AuthLayout>
    )
  }

  const errors = fieldErrors(error)
  return (
    <AuthLayout
      title="Forgot your password?"
      subtitle="Enter your email and we will send you a reset link."
      footer={back}
    >
      <form onSubmit={(e) => void onSubmit(e)} className="space-y-4" noValidate>
        <TextField
          label="Email"
          type="email"
          autoComplete="email"
          required
          autoFocus
          value={email}
          onChange={(e) => {
            setEmail(e.target.value)
          }}
          error={errors.email}
        />
        {Object.keys(errors).length === 0 && <FormError error={error} />}
        <Button
          type="submit"
          variant="primary"
          loading={submitting}
          className="btn-glow h-11 w-full rounded-[14px]"
        >
          Send reset link
        </Button>
      </form>
    </AuthLayout>
  )
}
