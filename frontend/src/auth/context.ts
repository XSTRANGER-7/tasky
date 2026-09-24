import { createContext } from 'react'

import type { User } from '@/api/client'

export type AuthStatus = 'loading' | 'anonymous' | 'authenticated'

export interface AuthContextValue {
  status: AuthStatus
  user: User | null
  login: (email: string, password: string) => Promise<User>
  register: (name: string, email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  /** The first-sign-in page was answered (team created, or skipped): never shown again. */
  finishOnboarding: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)
