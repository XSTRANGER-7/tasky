import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { Toaster } from 'sonner'

import { AppRoutes } from '@/app/App'
import { AuthProvider } from '@/auth/AuthProvider'

/** The whole app (routes, auth, query cache) at ``path``, with a fresh cache per test. */
export function renderApp(path = '/') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </AuthProvider>
      <Toaster />
    </QueryClientProvider>,
  )
}

/** A single component with a query cache and router, for focused tests. */
export function renderWithQuery(ui: ReactElement, path = '/') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="*" element={ui} />
        </Routes>
      </MemoryRouter>
      <Toaster />
    </QueryClientProvider>,
  )
}
