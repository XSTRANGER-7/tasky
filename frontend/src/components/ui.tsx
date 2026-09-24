import {
  forwardRef,
  useId,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
} from 'react'

import { apiUrl, type Role, type UserPublic } from '@/api/client'
import { initials } from '@/lib/format'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'

const variants: Record<Variant, string> = {
  primary: 'bg-accent text-white hover:bg-accent/90 disabled:bg-accent/50',
  secondary: 'border border-border bg-surface text-fg hover:bg-elevated',
  ghost: 'text-fg-muted hover:bg-elevated hover:text-fg',
  danger: 'bg-danger text-white hover:bg-danger/90 disabled:bg-danger/50',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  loading?: boolean
}

export function Button({
  variant = 'secondary',
  loading = false,
  className = '',
  children,
  disabled,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled ?? loading}
      aria-busy={loading || undefined}
      className={`inline-flex h-9 items-center justify-center gap-2 rounded-control px-3 text-sm font-medium transition-colors duration-instant active:scale-[0.98] disabled:cursor-not-allowed ${variants[variant]} ${className}`}
      {...rest}
    >
      {loading && (
        <span
          aria-hidden
          className="size-3.5 animate-spin rounded-full border-2 border-current border-r-transparent"
        />
      )}
      {children}
    </button>
  )
}

export interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  error?: string | undefined
  hint?: string
}

export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, error, hint, className = '', ...rest },
  ref,
) {
  const id = useId()
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-sm text-fg-muted">
        {label}
      </label>
      <input
        ref={ref}
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={`h-9 w-full rounded-control border bg-canvas/60 px-3 text-sm text-fg outline-none transition-colors duration-fast placeholder:text-fg-muted/60 focus:border-accent ${error ? 'border-danger' : 'border-border'}`}
        {...rest}
      />
      {error ? (
        <p id={`${id}-error`} className="mt-1 text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1 text-xs text-fg-muted">
          {hint}
        </p>
      ) : null}
    </div>
  )
})

/** The profile photo when there is one (and it loads), else initials on the user's colour. */
export function Avatar({
  user,
  size = 28,
}: {
  user: Pick<UserPublic, 'name' | 'avatar_color' | 'avatar_url'>
  size?: number
}) {
  const [broken, setBroken] = useState<string | null>(null)
  const photo = user.avatar_url && user.avatar_url !== broken ? user.avatar_url : null
  if (photo) {
    return (
      <img
        src={apiUrl(photo)}
        alt=""
        aria-hidden
        draggable={false}
        onError={() => {
          setBroken(photo)
        }}
        className="shrink-0 select-none rounded-full bg-elevated object-cover"
        style={{ width: size, height: size }}
      />
    )
  }
  return (
    <span
      aria-hidden
      className="inline-flex shrink-0 select-none items-center justify-center rounded-full text-[11px] font-semibold text-white"
      style={{ width: size, height: size, backgroundColor: user.avatar_color }}
    >
      {initials(user.name)}
    </span>
  )
}

const roleStyles: Record<Role, string> = {
  admin: 'border-accent/40 text-accent',
  member: 'border-border text-fg',
  viewer: 'border-border text-fg-muted',
}

export function RoleBadge({ role }: { role: Role }) {
  return (
    <span
      className={`inline-flex h-5 items-center rounded-full border px-2 text-xs capitalize ${roleStyles[role]}`}
    >
      {role}
    </span>
  )
}
