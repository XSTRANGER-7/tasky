import { motion } from 'framer-motion'
import {
  Camera,
  Check,
  Laptop,
  LogOut,
  Moon,
  Sparkles,
  Sun,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { toast } from 'sonner'

import { useUpdateMe } from '@/api/notifications'
import { useAvatar } from '@/api/profile'
import { useAuth } from '@/auth/useAuth'
import { Segmented } from '@/components/controls'
import { Avatar, Button, TextField } from '@/components/ui'
import { EmailPreference } from '@/features/notifications/NotificationsPage'
import { TeamRoleBadge } from '@/features/teams/TeamRoleBadge'
import { usePreferences, type MotionPref, type ThemePref } from '@/lib/theme'
import { formatDateTime } from '@/lib/time'
import { toastError } from '@/lib/toast'
import { useTeam } from '@/team/useTeam'

import { AvatarCropDialog } from './AvatarCropDialog'

function Section({
  title,
  description,
  children,
  index,
}: {
  title: string
  description: string
  children: ReactNode
  index: number
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, delay: index * 0.04, ease: [0.16, 1, 0.3, 1] }}
      className="grid gap-4 border-b border-border py-6 last:border-0 md:grid-cols-[14rem_1fr] md:gap-8"
    >
      <div>
        <h2 className="text-sm font-medium">{title}</h2>
        <p className="mt-1 text-xs text-fg-muted">{description}</p>
      </div>
      <div className="min-w-0 space-y-4">{children}</div>
    </motion.section>
  )
}

const PHOTO_TYPES = 'image/png,image/jpeg,image/gif,image/webp'
const MAX_SOURCE_BYTES = 20 * 1024 * 1024 // before cropping; the saved photo is tiny

/** My photo, with upload (crop first), change and remove. */
function ProfilePhoto({ name }: { name: string }) {
  const { user } = useAuth()
  const { upload, remove } = useAvatar()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  if (!user) return null
  const hasPhoto = Boolean(user.avatar_url)

  function pick() {
    input.current?.click()
  }

  return (
    <div className="flex shrink-0 flex-col items-center gap-2">
      <button
        type="button"
        onClick={pick}
        aria-label={hasPhoto ? 'Change profile photo' : 'Add a profile photo'}
        className="group relative rounded-full outline-offset-4"
      >
        <motion.span
          key={`${user.avatar_url ?? ''}${name}`}
          initial={{ scale: 0.85, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 380, damping: 26 }}
          className="block"
        >
          <Avatar user={{ ...user, name }} size={72} />
        </motion.span>
        <span className="absolute inset-0 flex items-center justify-center rounded-full bg-black/45 text-white opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
          <Camera aria-hidden className="size-5" />
        </span>
        <span className="absolute -bottom-0.5 -right-0.5 flex size-6 items-center justify-center rounded-full border-2 border-surface bg-accent text-white">
          <Camera aria-hidden className="size-3" />
        </span>
      </button>
      <input
        ref={input}
        type="file"
        accept={PHOTO_TYPES}
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(e) => {
          const chosen = e.target.files?.[0] ?? null
          e.target.value = '' // picking the same file again still opens the cropper
          if (!chosen) return
          if (!chosen.type.startsWith('image/')) {
            toast.error('Choose an image: PNG, JPEG, GIF or WebP')
            return
          }
          if (chosen.size > MAX_SOURCE_BYTES) {
            toast.error('That image is over 20 MB. Choose a smaller one.')
            return
          }
          setFile(chosen)
        }}
      />
      <div className="flex items-center gap-1">
        <button type="button" onClick={pick} className="text-xs text-accent hover:underline">
          {hasPhoto ? 'Change' : 'Upload photo'}
        </button>
        {hasPhoto && (
          <>
            <span className="text-xs text-fg-muted">·</span>
            <button
              type="button"
              disabled={remove.isPending}
              onClick={() => {
                remove.mutate(undefined, {
                  onSuccess: () => {
                    toast.success('Photo removed')
                  },
                  onError: (err) => {
                    toastError(err, 'Could not remove your photo')
                  },
                })
              }}
              className="text-xs text-fg-muted hover:text-danger disabled:opacity-50"
            >
              Remove
            </button>
          </>
        )}
      </div>
      <AvatarCropDialog
        file={file}
        saving={upload.isPending}
        onCancel={() => {
          setFile(null)
        }}
        onSave={(photo) => {
          upload.mutate(photo, {
            onSuccess: () => {
              setFile(null)
              toast.success('Profile photo updated')
            },
            onError: (err) => {
              toastError(err, 'Could not save your photo')
            },
          })
        }}
      />
    </div>
  )
}

function Profile() {
  const { user } = useAuth()
  const { active, role } = useTeam()
  const update = useUpdateMe()
  const [name, setName] = useState(user?.name ?? '')
  const [error, setError] = useState<string | undefined>()
  useEffect(() => {
    setName(user?.name ?? '')
  }, [user?.name])
  if (!user) return null
  const dirty = name.trim() !== user.name

  const save = (e: FormEvent) => {
    e.preventDefault()
    const value = name.trim()
    if (value.length < 2) {
      setError('Use at least 2 characters')
      return
    }
    setError(undefined)
    update.mutate(
      { name: value },
      {
        onSuccess: () => {
          toast.success('Profile saved')
        },
        onError: (err) => {
          toastError(err, 'Could not save your profile')
        },
      },
    )
  }

  return (
    <form onSubmit={save} className="space-y-4">
      <div className="flex items-center gap-4">
        <ProfilePhoto name={name || user.name} />
        <div className="min-w-0">
          <p className="truncate font-medium">{user.name}</p>
          <p className="flex flex-wrap items-center gap-2 text-sm text-fg-muted">
            {user.email}
            {role && <TeamRoleBadge role={role} />}
            {active && <span className="text-xs">in {active.name}</span>}
          </p>
          <p className="mt-0.5 text-xs text-fg-muted">
            Member since {formatDateTime(user.created_at)}
          </p>
        </div>
      </div>
      <div className="max-w-sm">
        <TextField
          label="Display name"
          value={name}
          maxLength={100}
          onChange={(e) => {
            setName(e.target.value)
          }}
          error={error}
          hint="Shown on tasks, comments and notifications."
        />
      </div>
      <Button type="submit" variant="primary" disabled={!dirty} loading={update.isPending}>
        Save profile
      </Button>
    </form>
  )
}

const THEMES: { value: ThemePref; label: string; icon: LucideIcon }[] = [
  { value: 'system', label: 'System', icon: Laptop },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'light', label: 'Light', icon: Sun },
]

/** A tiny rendering of the app in each theme, so the choice is visual. */
function ThemeCard({
  value,
  label,
  icon: Icon,
  active,
  onSelect,
}: {
  value: ThemePref
  label: string
  icon: LucideIcon
  active: boolean
  onSelect: () => void
}) {
  const half = (theme: 'dark' | 'light') => (
    <span data-preview={theme} className="flex flex-1 flex-col gap-1 bg-canvas p-2">
      <span className="flex gap-1">
        <span className="h-10 w-3 rounded-sm bg-surface" />
        <span className="flex flex-1 flex-col gap-1">
          <span className="h-2 w-2/3 rounded-sm bg-fg-muted/40" />
          <span className="h-2 w-1/2 rounded-sm bg-accent" />
          <span className="h-4 rounded-sm border border-border bg-surface" />
        </span>
      </span>
    </span>
  )
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onSelect}
      className={`group relative w-full overflow-hidden rounded-card border text-left transition-colors sm:w-40 ${
        active ? 'border-accent ring-2 ring-accent/30' : 'border-border hover:border-fg-muted/40'
      }`}
    >
      <span className="flex h-16 overflow-hidden">
        {value === 'system' ? (
          <>
            {half('dark')}
            {half('light')}
          </>
        ) : (
          half(value)
        )}
      </span>
      <span className="flex items-center gap-2 border-t border-border bg-surface px-3 py-2 text-sm">
        <Icon aria-hidden className="size-4 text-fg-muted" />
        {label}
        {active && (
          <motion.span
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ type: 'spring', stiffness: 500, damping: 18 }}
            className="ml-auto flex size-4 items-center justify-center rounded-full bg-accent text-white"
          >
            <Check className="size-3" strokeWidth={3} />
          </motion.span>
        )}
      </span>
    </button>
  )
}

function Appearance() {
  const prefs = usePreferences()
  return (
    <>
      <div role="radiogroup" aria-label="Theme" className="flex flex-col gap-3 sm:flex-row">
        {THEMES.map((t) => (
          <ThemeCard
            key={t.value}
            {...t}
            active={prefs.theme === t.value}
            onSelect={() => {
              prefs.setTheme(t.value)
            }}
          />
        ))}
      </div>
      <div className="space-y-2">
        <p className="text-sm font-medium">Motion</p>
        <Segmented<MotionPref>
          label="Motion"
          value={prefs.motion}
          onChange={prefs.setMotion}
          options={[
            { value: 'system', label: 'System', icon: <Laptop className="size-3.5" /> },
            { value: 'full', label: 'Full', icon: <Sparkles className="size-3.5" /> },
            { value: 'reduce', label: 'Reduced', icon: <Zap className="size-3.5" /> },
          ]}
        />
        <p className="text-xs text-fg-muted">
          {prefs.reduceMotion
            ? 'Animations are off: every transition is an instant change and loops stop.'
            : 'Animations show what just changed and where it went.'}
          {prefs.motion === 'system' && ' Following your operating system setting.'}
        </p>
      </div>
    </>
  )
}

export function SettingsPage() {
  const { logout } = useAuth()
  return (
    <div className="mx-auto max-w-4xl">
      <header className="pb-2">
        <h1 className="text-xl font-medium">Settings</h1>
        <p className="text-sm text-fg-muted">Your profile and how Tasky looks and behaves.</p>
      </header>
      <Section
        index={0}
        title="Profile"
        description="Your photo and name are visible to your team."
      >
        <Profile />
      </Section>
      <Section
        index={1}
        title="Appearance"
        description="Saved in this browser. Dark is the default, tuned for long shifts."
      >
        <Appearance />
      </Section>
      <Section
        index={2}
        title="Notifications"
        description="In-app notifications are always on; email is up to you."
      >
        <EmailPreference />
      </Section>
      <Section
        index={3}
        title="Session"
        description="Signing out ends this session everywhere it is open in this browser."
      >
        <Button onClick={() => void logout()}>
          <LogOut className="size-4" /> Sign out
        </Button>
      </Section>
    </div>
  )
}
