import { createContext, useContext } from 'react'

export interface ShellActions {
  openCreate: () => void
  openPalette: () => void
}

export const ShellContext = createContext<ShellActions | null>(null)

export function useShell(): ShellActions {
  const ctx = useContext(ShellContext)
  if (!ctx) throw new Error('useShell must be used inside <AppShell>')
  return ctx
}

/** True when the keyboard event comes from a text field (shortcuts must not fire). */
export function isTyping(event: KeyboardEvent): boolean {
  const el = event.target as HTMLElement | null
  if (!el) return false
  return el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
}
