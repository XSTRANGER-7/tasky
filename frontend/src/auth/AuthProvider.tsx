import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import {
  api,
  getAccessToken,
  onSessionChange,
  refreshSession,
  setSession,
  unwrap,
  type User,
} from '@/api/client'

import { AuthContext, type AuthStatus } from './context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [status, setStatus] = useState<AuthStatus>('loading')

  // Any session change (login, silent refresh, refresh failure) flows through here.
  useEffect(
    () =>
      onSessionChange((token, next) => {
        setUser(next)
        setStatus(token ? 'authenticated' : 'anonymous')
      }),
    [],
  )

  // On load, try to resume a session from the refresh cookie.
  useEffect(() => {
    let active = true
    void refreshSession().then((result) => {
      if (active && !result) setStatus('anonymous')
    })
    return () => {
      active = false
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const body = await unwrap(api.POST('/api/v1/auth/login', { body: { email, password } }))
    setSession(body.access_token, body.user)
    return body.user
  }, [])

  const register = useCallback(async (name: string, email: string, password: string) => {
    await unwrap(api.POST('/api/v1/auth/register', { body: { name, email, password } }))
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.POST('/api/v1/auth/logout')
    } finally {
      setSession(null, null)
    }
  }, [])

  const finishOnboarding = useCallback(async () => {
    const next = await unwrap(api.POST('/api/v1/auth/me/onboarded'))
    setSession(getAccessToken(), next)
  }, [])

  const value = useMemo(
    () => ({ status, user, login, register, logout, finishOnboarding }),
    [status, user, login, register, logout, finishOnboarding],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
