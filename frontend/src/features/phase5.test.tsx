/** Phase 5 screens: settings, admin users + configuration, shortcuts, list quick actions. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { setSession } from '@/api/client'
import { ada, dashboard, incident, jonas, page, team } from '@/test/fixtures'
import { demoUser, json, mockApi, tokenOut, type Handler } from '@/test/mockApi'
import { renderApp } from '@/test/render'

afterEach(() => {
  setSession(null, null)
  localStorage.clear()
  document.documentElement.removeAttribute('data-motion')
})

const people = [
  { ...demoUser },
  {
    ...jonas,
    is_active: true,
    notify_email: false,
    created_at: '2026-09-01T10:00:00Z',
  },
  {
    id: '55555555-5555-4555-8555-555555555555',
    name: 'Old Timer',
    email: 'old@demo.io',
    role: 'member' as const,
    avatar_color: '#999999',
    is_active: false,
    notify_email: true,
    created_at: '2026-01-01T10:00:00Z',
  },
]

function api(extra: Record<string, Handler> = {}, user = demoUser) {
  return mockApi({
    'POST /api/v1/auth/refresh': () => json(tokenOut('access-1', user)),
    'GET /api/v1/users': () => json(user.role === 'admin' ? people : team),
    // The Admin Console lists every account with its teams and sign-in methods.
    'GET /api/v1/admin/users': () =>
      json(people.map((p) => ({ ...p, teams: [], has_password: true, google_linked: false }))),
    'GET /api/v1/health': () =>
      json({ status: 'ok', db: 'ok', version: '1', git_sha: 'x', env: 't' }),
    'GET /api/v1/dashboard/summary': () => json(dashboard()),
    ...extra,
  })
}

describe('settings', () => {
  it('switches theme and motion, and remembers both', async () => {
    api()
    renderApp('/settings')

    await userEvent.click(await screen.findByRole('radio', { name: /Light/ }))
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('incident-desk.theme')).toBe('light')

    await userEvent.click(screen.getByRole('radio', { name: /Reduced/ }))
    expect(document.documentElement.dataset.motion).toBe('reduce')
    expect(localStorage.getItem('incident-desk.motion')).toBe('reduce')
    expect(screen.getByText(/Animations are off/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('radio', { name: /Dark/ }))
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('saves the display name and validates it', async () => {
    const { calls } = api({
      'PATCH /api/v1/users/4ea7f71a-bd93-4894-98ee-41e81a4a48c9': () =>
        json({ ...demoUser, name: 'Ada Lovelace' }),
    })
    renderApp('/settings')

    const field = await screen.findByLabelText('Display name')
    const save = screen.getByRole('button', { name: 'Save profile' })
    expect(save).toBeDisabled()

    await userEvent.clear(field)
    await userEvent.type(field, 'A')
    await userEvent.click(save)
    expect(await screen.findByText('Use at least 2 characters')).toBeInTheDocument()

    await userEvent.type(field, 'da Lovelace')
    await userEvent.click(save)
    expect(await screen.findByText('Profile saved')).toBeInTheDocument()
    const patch = calls.find((r) => r.method === 'PATCH')
    expect(await patch?.json()).toEqual({ name: 'Ada Lovelace' })
  })
})

describe('admin configuration', () => {
  it('shows SLA targets, flags and runtime', async () => {
    api({
      'GET /api/v1/admin/settings': () =>
        json({
          version: '0.1.0',
          git_sha: 'abc123',
          environment: 'development',
          email_provider: 'console',
          email_from: 'Incident Desk <noreply@example.com>',
          sla_check_seconds: 300,
          worker: { status: 'ok', last_beat_at: new Date().toISOString(), seconds_since_beat: 2 },
          sla: [
            { priority: 'critical', response_minutes: 30, resolution_minutes: 240 },
            { priority: 'high', response_minutes: 120, resolution_minutes: 480 },
            { priority: 'medium', response_minutes: 480, resolution_minutes: 1440 },
            { priority: 'low', response_minutes: 1440, resolution_minutes: 4320 },
          ],
          flags: [
            { key: 'email', label: 'Email notifications', enabled: false, detail: 'console' },
            { key: 'metrics', label: 'Prometheus metrics', enabled: true, detail: '/metrics' },
          ],
        }),
    })
    renderApp('/admin/settings')

    expect(
      await screen.findByRole('img', {
        name: 'critical: first response within 30m, resolution within 4h',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('Prometheus metrics')).toBeInTheDocument()
    expect(screen.getByText('0.1.0 (abc123)')).toBeInTheDocument()
    expect(screen.getByText('every 5m')).toBeInTheDocument()
  })
})

describe('shell', () => {
  it('opens the shortcuts list with ? and navigates with G then a letter', async () => {
    api({
      'GET /api/v1/incidents': () => json(page([incident()])),
    })
    renderApp('/settings')
    await screen.findByRole('heading', { name: 'Settings' })

    await userEvent.keyboard('?')
    const dialog = await screen.findByRole('dialog', { name: 'Keyboard shortcuts' })
    expect(within(dialog).getByText('Go to tasks')).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    await userEvent.keyboard('gt')
    expect(await screen.findByRole('heading', { name: 'Tasks' })).toBeInTheDocument()
  })

  it('shows team admin navigation only to the team admins', async () => {
    api({}, { ...demoUser, role: 'member' as never })
    renderApp('/settings')
    await screen.findByRole('heading', { name: 'Settings' })
    expect(screen.queryByRole('link', { name: 'Email outbox' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'My work' }).length).toBeGreaterThan(0)
    expect(screen.queryByRole('link', { name: 'Watching' })).not.toBeInTheDocument()
  })

  it('gives a team admin their email outbox and configuration', async () => {
    api()
    renderApp('/settings')
    await screen.findByRole('heading', { name: 'Settings' })
    expect(screen.getAllByRole('link', { name: 'Email outbox' }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('link', { name: 'Configuration' }).length).toBeGreaterThan(0)
  })

  it('draws sparklines and the priority donut on the dashboard', async () => {
    api()
    renderApp('/')
    expect(
      await screen.findByRole('img', { name: 'Open backlog over the last 14 days' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: /open: Critical 1, High 2, Medium 1, Low 4/ }),
    ).toBeInTheDocument()
  })
})

describe('task list quick actions', () => {
  it('filters the Watching view on the server', async () => {
    const { calls } = api({ 'GET /api/v1/incidents': () => json(page([])) })
    renderApp('/tasks?view=watching')

    expect(await screen.findByText('You are not watching anything yet')).toBeInTheDocument()
    const list = calls.find((r) => new URL(r.url).pathname === '/api/v1/incidents')
    expect(new URL(list?.url ?? 'http://x').searchParams.get('watching')).toBe('true')
  })

  it('A opens the assign menu for the selected row; picking someone assigns', async () => {
    const { calls } = api({
      'GET /api/v1/incidents': () => json(page([incident({ assignee: null })])),
      'POST /api/v1/incidents/INC-7/assign': () => json(incident({ assignee: ada })),
    })
    renderApp('/tasks')
    await screen.findByText('Checkout API returning 502')

    await userEvent.keyboard('a')
    await userEvent.click(await screen.findByRole('menuitem', { name: /Ada Admin/ }))

    expect(await screen.findByText('INC-7 assigned to Ada Admin')).toBeInTheDocument()
    const body = await calls.find((r) => r.url.endsWith('/assign'))?.json()
    expect(body).toEqual({ assignee_id: ada.id })
  })

  it('S opens the status menu with the allowed moves', async () => {
    api({ 'GET /api/v1/incidents': () => json(page([incident()])) })
    renderApp('/tasks')
    await screen.findByText('Checkout API returning 502')

    await userEvent.keyboard('s')
    const items = await screen.findAllByRole('menuitem')
    expect(items.map((i) => i.textContent)).toEqual(['Start workIn progress', 'ResolveResolved'])
  })
})

describe('error boundary', () => {
  it('contains a page crash, shows the request id and recovers on retry', async () => {
    const { render } = await import('@testing-library/react')
    const { ErrorBoundary } = await import('@/components/ErrorBoundary')
    const { ApiError } = await import('@/api/client')
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    let fail = true
    function Page() {
      if (fail) throw new ApiError(500, 'internal_error', 'Boom', 'req_01TEST')
      return <p>Recovered</p>
    }
    render(
      <ErrorBoundary>
        <Page />
      </ErrorBoundary>,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('This page hit a problem')
    expect(screen.getByText('Request ID req_01TEST')).toBeInTheDocument()
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(screen.getByText('Recovered')).toBeInTheDocument()
  })
})

describe('sidebar highlight', () => {
  it('marks Tasks as the current tab on the Watching view', async () => {
    api({ 'GET /api/v1/incidents': () => json(page([])) })
    renderApp('/tasks?view=watching')
    await screen.findByText('You are not watching anything yet')
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: 'Tasks' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('link', { name: 'My work' })).not.toHaveAttribute('aria-current')
  })
})

describe('profile photo', () => {
  const withPhoto = { ...demoUser, avatar_url: '/api/v1/avatars/abc.png' } as typeof demoUser

  it('shows the photo instead of initials, and removes it', async () => {
    const { count } = api({ 'DELETE /api/v1/users/me/avatar': () => json(demoUser) }, withPhoto)
    renderApp('/settings')

    const change = await screen.findByRole('button', { name: 'Change profile photo' })
    expect(change.querySelector('img')?.getAttribute('src')).toMatch(
      /\/api\/v1\/avatars\/abc\.png$/,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))

    expect(await screen.findByText('Photo removed')).toBeInTheDocument()
    expect(count('DELETE /api/v1/users/me/avatar')).toBe(1)
    expect(await screen.findByRole('button', { name: 'Add a profile photo' })).toBeInTheDocument()
  })

  it('falls back to initials when the photo cannot load', async () => {
    api({}, withPhoto)
    renderApp('/settings')
    const img = (await screen.findByRole('button', { name: 'Change profile photo' })).querySelector(
      'img',
    )
    fireEvent.error(img as HTMLImageElement)
    expect(
      await within(screen.getByRole('button', { name: 'Change profile photo' })).findByText('AA'),
    ).toBeInTheDocument()
  })
})

describe('phone layout', () => {
  const realMatchMedia = window.matchMedia
  beforeEach(() => {
    // Every "max-width" query matches: the app thinks it is on a phone.
    window.matchMedia = (query: string) => ({
      matches: query.includes('max-width'),
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    })
  })
  afterEach(() => {
    window.matchMedia = realMatchMedia
  })

  it('puts notifications and the theme in the profile menu, and New task in the bottom bar', async () => {
    api({
      'GET /api/v1/notifications': () => json({ items: [], unread_count: 3, next_cursor: null }),
    })
    renderApp('/settings')
    await screen.findByRole('heading', { name: 'Settings' })

    const bar = screen.getByRole('navigation', { name: 'Main (mobile)' })
    expect(within(bar).getByRole('button', { name: 'New task' })).toBeInTheDocument()
    expect(within(bar).queryByRole('link', { name: 'My work' })).not.toBeInTheDocument()
    expect(within(bar).getByRole('link', { name: 'Notifications' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Account menu' }))
    expect(await screen.findByRole('menuitem', { name: /Notifications\s*3/ })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /theme/ })).toBeInTheDocument()
  })
})
