import { motion } from 'framer-motion'
import { useId, type ReactNode } from 'react'

/** On/off switch with a spring thumb. */
export function Switch({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => {
        onChange(!checked)
      }}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-fast disabled:cursor-not-allowed disabled:opacity-50 ${
        checked ? 'bg-accent' : 'bg-fg-muted/30'
      }`}
    >
      <motion.span
        layout
        transition={{ type: 'spring', stiffness: 600, damping: 35 }}
        className={`size-4 rounded-full bg-white shadow ${checked ? 'ml-[18px]' : 'ml-0.5'}`}
      />
    </button>
  )
}

/** Radio group styled as a segmented control; the highlight slides between options. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  size = 'md',
}: {
  value: T
  onChange: (next: T) => void
  options: { value: T; label: string; icon?: ReactNode }[]
  label: string
  size?: 'sm' | 'md'
}) {
  const id = useId()
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex rounded-control border border-border bg-canvas p-0.5"
      onKeyDown={(e) => {
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
        e.preventDefault()
        const i = options.findIndex((o) => o.value === value)
        const step = e.key === 'ArrowRight' ? 1 : -1
        const next = options[(i + step + options.length) % options.length]
        if (next) onChange(next.value)
      }}
    >
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => {
              onChange(o.value)
            }}
            className={`relative inline-flex items-center gap-1.5 rounded-[5px] font-medium transition-colors ${
              size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-8 px-3 text-sm'
            } ${active ? 'text-fg' : 'text-fg-muted hover:text-fg'}`}
          >
            {active && (
              <motion.span
                layoutId={`seg-${id}`}
                className="absolute inset-0 rounded-[5px] bg-elevated shadow-sm ring-1 ring-[color:var(--border)]"
                transition={{ type: 'spring', stiffness: 500, damping: 38 }}
              />
            )}
            <span className="relative flex items-center gap-1.5">
              {o.icon}
              {o.label}
            </span>
          </button>
        )
      })}
    </div>
  )
}
