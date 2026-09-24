import { motion } from 'framer-motion'
import { Eye, EyeOff } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { ApiError, apiUrl } from '@/api/client'
import { TextField, type TextFieldProps } from '@/components/ui'

/**
 * Every auth page (sign in, register, forgot, reset): just the form, on one frosted-glass
 * card (iOS materials) over a slowly moving aurora. The product story lives on the landing
 * page; here nothing competes with the form.
 */
export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
  shake = 0,
}: {
  title: string
  subtitle: string
  children: ReactNode
  footer?: ReactNode
  /** Increment to replay the error shake once. */
  shake?: number
}) {
  return (
    <main className="aurora relative flex min-h-dvh flex-col">
      <Orbs />
      <header className="relative z-10 flex h-16 items-center justify-between px-4 sm:px-6">
        <Link to="/" className="flex items-center gap-2.5" aria-label="Tasky home">
          <img src="/logo.svg" alt="" className="size-8" />
          <span className="font-semibold tracking-tight">Tasky</span>
        </Link>
        <Link
          to="/"
          className="rounded-full px-3 py-1.5 text-sm text-fg-muted transition-colors hover:bg-surface hover:text-fg"
        >
          About Tasky
        </Link>
      </header>

      <section className="relative z-10 flex flex-1 items-center justify-center px-4 pb-16 pt-2">
        <motion.div
          className="w-full max-w-[420px]"
          initial={{ opacity: 0, y: 18, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        >
          <div
            key={shake}
            className={`glass-card rounded-[28px] p-6 sm:p-8 ${shake ? 'animate-shake' : ''}`}
          >
            <div className="mb-6 flex flex-col items-center text-center">
              <motion.img
                src="/logo.svg"
                alt=""
                className="size-14 drop-shadow-[0_8px_24px_rgba(110,139,255,0.45)]"
                initial={{ rotate: -12, scale: 0.7, opacity: 0 }}
                animate={{ rotate: 0, scale: 1, opacity: 1 }}
                transition={{ type: 'spring', stiffness: 260, damping: 16, delay: 0.1 }}
              />
              <h1 className="mt-4 text-xl font-semibold tracking-tight">{title}</h1>
              <p className="mt-1 text-sm text-fg-muted">{subtitle}</p>
            </div>
            {children}
            {footer && (
              <div className="mt-6 border-t border-border pt-5 text-center text-sm text-fg-muted">
                {footer}
              </div>
            )}
          </div>
        </motion.div>
      </section>
    </main>
  )
}

/** Soft colour orbs drifting behind the glass (paused by the reduce-motion setting). */
function Orbs() {
  const orbs = [
    {
      className: 'left-[8%] top-[12%] size-72 bg-[#6E8BFF]',
      x: [0, 40, -20, 0],
      y: [0, 30, 60, 0],
    },
    {
      className: 'right-[10%] top-[20%] size-80 bg-[#8B5CF6]',
      x: [0, -50, 10, 0],
      y: [0, 40, -20, 0],
    },
    {
      className: 'bottom-[8%] left-[30%] size-72 bg-[#EC4899]',
      x: [0, 30, -40, 0],
      y: [0, -30, 10, 0],
    },
  ]
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      {orbs.map((o, i) => (
        <motion.span
          key={i}
          className={`absolute rounded-full opacity-[0.28] blur-3xl dark:opacity-[0.22] ${o.className}`}
          animate={{ x: o.x, y: o.y }}
          transition={{ duration: 22 + i * 6, repeat: Infinity, ease: 'easeInOut' }}
        />
      ))}
    </div>
  )
}

export function FormError({ error }: { error: unknown }) {
  if (!error) return null
  const message =
    error instanceof ApiError
      ? error.message
      : typeof error === 'string'
        ? error
        : 'Could not reach the server. Check your connection and try again.'
  const requestId = error instanceof ApiError ? error.requestId : null
  return (
    <div role="alert" className="rounded-control border border-danger/40 bg-danger/10 px-3 py-2">
      <p className="text-sm text-danger">{message}</p>
      {requestId && <p className="mt-0.5 font-mono text-xs text-fg-muted">{requestId}</p>}
    </div>
  )
}

export function FormNotice({ children }: { children: ReactNode }) {
  return (
    <div
      role="status"
      className="rounded-control border border-status-resolved/40 bg-status-resolved/10 px-3 py-2 text-sm text-status-resolved"
    >
      {children}
    </div>
  )
}

/** A password input with a show/hide toggle. */
export function PasswordField(props: Omit<TextFieldProps, 'type'>) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="relative">
      <TextField {...props} type={visible ? 'text' : 'password'} className="[&_input]:pr-10" />
      <button
        type="button"
        onClick={() => {
          setVisible((v) => !v)
        }}
        aria-label={visible ? 'Hide password' : 'Show password'}
        aria-pressed={visible}
        className="absolute right-1.5 top-[26px] flex size-7 items-center justify-center rounded-control text-fg-muted hover:bg-elevated hover:text-fg"
      >
        {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  )
}

/** "Continue with Google": a full-page navigation into the server's OAuth flow. */
export function GoogleButton({
  next = '/',
  label = 'Continue with Google',
}: {
  next?: string
  label?: string
}) {
  const href = apiUrl(`/api/v1/auth/google/start?next=${encodeURIComponent(next)}`)
  return (
    <a
      href={href}
      className="inline-flex h-11 w-full items-center justify-center gap-3 rounded-[14px] border border-border bg-canvas/50 text-sm font-medium text-fg transition-colors hover:bg-canvas/80"
    >
      <GoogleLogo />
      {label}
    </a>
  )
}

export function Divider({ label = 'or' }: { label?: string }) {
  return (
    <div className="my-5 flex items-center gap-3 text-xs uppercase tracking-wide text-fg-muted/80">
      <span className="h-px flex-1 bg-border" />
      {label}
      <span className="h-px flex-1 bg-border" />
    </div>
  )
}

function GoogleLogo() {
  return (
    <svg aria-hidden viewBox="0 0 48 48" className="size-[18px]">
      <path
        fill="#FFC107"
        d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"
      />
      <path
        fill="#FF3D00"
        d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"
      />
      <path
        fill="#4CAF50"
        d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"
      />
      <path
        fill="#1976D2"
        d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"
      />
    </svg>
  )
}
