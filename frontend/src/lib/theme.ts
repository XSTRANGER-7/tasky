/**
 * Per-browser display preferences: theme and motion (spec 11.2, 12.4).
 *
 * Both default to "system" (prefers-color-scheme / prefers-reduced-motion) until the
 * user picks, then the choice is remembered in localStorage. One tiny external store,
 * so the shell toggle, the settings page and MotionConfig always agree.
 */
import { useCallback, useEffect, useSyncExternalStore } from 'react'

export type Theme = 'dark' | 'light'
export type ThemePref = Theme | 'system'
export type MotionPref = 'system' | 'reduce' | 'full'

const THEME_KEY = 'incident-desk.theme'
const MOTION_KEY = 'incident-desk.motion'

interface Prefs {
  theme: ThemePref
  motion: MotionPref
}

function read<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const value = localStorage.getItem(key)
    return value && (allowed as readonly string[]).includes(value) ? (value as T) : fallback
  } catch {
    return fallback // storage blocked (private mode): use the system preference
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // not persisted; still applied for this session
  }
}

let prefs: Prefs = {
  theme: read<ThemePref>(THEME_KEY, ['dark', 'light', 'system'], 'system'),
  motion: read<MotionPref>(MOTION_KEY, ['system', 'reduce', 'full'], 'system'),
}
const listeners = new Set<() => void>()

function update(patch: Partial<Prefs>): void {
  prefs = { ...prefs, ...patch }
  apply()
  listeners.forEach((l) => {
    l()
  })
}

function media(query: string): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia(query).matches
}

export function systemTheme(): Theme {
  return media('(prefers-color-scheme: light)') ? 'light' : 'dark'
}

export function resolvedTheme(p: ThemePref = prefs.theme): Theme {
  return p === 'system' ? systemTheme() : p
}

/** Whether animations should be reduced right now (user choice beats the OS). */
export function motionReduced(p: MotionPref = prefs.motion): boolean {
  return p === 'system' ? media('(prefers-reduced-motion: reduce)') : p === 'reduce'
}

let fadeTimer: ReturnType<typeof setTimeout> | undefined

function apply(): void {
  const root = document.documentElement
  const theme = resolvedTheme()
  if (root.dataset.theme && root.dataset.theme !== theme && !motionReduced()) {
    // Cross-fade colours for one theme switch only (spec 12.3), not on every hover.
    root.classList.add('theme-transition')
    clearTimeout(fadeTimer)
    fadeTimer = setTimeout(() => {
      root.classList.remove('theme-transition')
    }, 260)
  }
  root.dataset.theme = theme
  root.dataset.motion = motionReduced() ? 'reduce' : 'full'
}

/** Call before the first render so the saved theme is applied without a flash. */
export function initTheme(): void {
  apply()
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

export function usePreferences() {
  const current = useSyncExternalStore(subscribe, () => prefs)

  // Follow OS changes while the preference is "system".
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const queries = ['(prefers-color-scheme: light)', '(prefers-reduced-motion: reduce)'].map((q) =>
      window.matchMedia(q),
    )
    const onChange = () => {
      update({})
    }
    queries.forEach((q) => {
      q.addEventListener('change', onChange)
    })
    return () => {
      queries.forEach((q) => {
        q.removeEventListener('change', onChange)
      })
    }
  }, [])

  const setTheme = useCallback((theme: ThemePref) => {
    write(THEME_KEY, theme)
    update({ theme })
  }, [])
  const setMotion = useCallback((motion: MotionPref) => {
    write(MOTION_KEY, motion)
    update({ motion })
  }, [])

  return {
    theme: current.theme,
    motion: current.motion,
    resolvedTheme: resolvedTheme(current.theme),
    reduceMotion: motionReduced(current.motion),
    setTheme,
    setMotion,
  }
}

/** Dark by default, follows the OS until the user picks, then remembers the choice. */
export function useTheme(): [Theme, () => void] {
  const { resolvedTheme: theme, setTheme } = usePreferences()
  const toggle = useCallback(() => {
    setTheme(resolvedTheme() === 'dark' ? 'light' : 'dark')
  }, [setTheme])
  return [theme, toggle]
}
