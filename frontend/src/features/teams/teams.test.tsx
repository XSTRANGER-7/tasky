import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { setActiveTeam, setSession } from '@/api/client'
import { dashboard, page } from '@/test/fixtures'
import {
  TEST_TEAM_ID,
  apiError,
  demoUser,
  json,
  mockApi,
  testTeam,
  tokenOut,
  type Handler,
} from '@/test/mockApi'
import { renderApp } from '@/test/render'

const health = { status: 'ok', db: 'ok', version: '0.1.0', git_sha: 'abc', env: 'test' }
type TestUser = Omit<typeof demoUser, 'role'> & { role: 'admin' | 'member' | 'viewer' }
const member: TestUser = { ...demoUser, role: 'member', name: 'Mira Patel', email: 'mira@demo.io' }
const OTHER_TEAM = '88888888-8888-4888-8888-888888888888'

function signedIn(user: TestUser = member, extra: Record<string, Handler> = {}) {
  return mockApi({
    'POST /api/v1/auth/refresh': () => json(tokenOut('access-1', user as typeof demoUser)),
    'GET /api/v1/health': () => json(health),
    'GET /api/v1/dashboard/summary': () => json(dashboard()),
    'GET /api/v1/users': () => json([]),
    'GET /api/v1/incidents': () => json(page([])),
    ...extra,
  })
}

const request = (overrides: Record<string, unknown> = {}) => ({
  id: 'req-1',
  team: { id: OTHER_TEAM, name: 'Payments', slug: 'payments' },
  user: {
    id: 'u-max',
    name: 'Max Weber',
    email: 'max@demo.io',
    role: 'member',
    avatar_color: '#81C784',
  },
  message: 'On call for payouts',
  status: 'pending',
  granted_role: null,
  decided_by: null,
  decided_at: null,
  created_at: new Date().toISOString(),
  ...overrides,
})

afterEach(() => {
  setSession(null, null)
  setActiveTeam(null)
})

describe('team onboarding', () => {
  it('shows people without a team how to create or join one on the main page', async () => {
    signedIn(member, { 'GET /api/v1/teams/mine': () => json({ teams: [], requests: [] }) })
    renderApp('/')
    expect(
      await screen.findByRole('heading', { name: 'You are not in a team yet, Mira' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Create a team' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Join a team' })).toBeInTheDocument()
  })

  it('creates a team and opens its workspace as its admin', async () => {
    let created = false
    const payments = testTeam({
      id: OTHER_TEAM,
      name: 'Payments',
      my_role: 'admin',
      member_count: 1,
    })
    const { calls } = signedIn(member, {
      'GET /api/v1/teams/mine': () => json({ teams: created ? [payments] : [], requests: [] }),
      'GET /api/v1/teams/discover': () => json([]),
      'POST /api/v1/teams': () => {
        created = true
        return json(payments, 201)
      },
    })
    renderApp('/')

    await userEvent.type(await screen.findByLabelText('Team name'), 'Payments')
    await userEvent.click(screen.getByRole('button', { name: 'Create team' }))

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    const create = calls.find((r) => r.method === 'POST' && r.url.endsWith('/api/v1/teams'))
    expect(await create?.json()).toEqual({ name: 'Payments', description: '' })
    // From now on every request acts in the new team.
    await waitFor(() => {
      const dash = calls.filter((r) => new URL(r.url).pathname === '/api/v1/dashboard/summary')
      expect(dash.at(-1)?.headers.get('X-Team-Id')).toBe(OTHER_TEAM)
    })
  })

  it('asks to join a team and shows the request as pending', async () => {
    let asked = false
    const { calls } = signedIn(member, {
      'GET /api/v1/teams/mine': () =>
        json({ teams: [], requests: asked ? [request({ user: member })] : [] }),
      'GET /api/v1/teams/discover': () =>
        json([
          testTeam({
            id: OTHER_TEAM,
            name: 'Payments',
            my_role: null,
            pending_request_id: asked ? 'req-1' : null,
          }),
        ]),
      [`POST /api/v1/teams/${OTHER_TEAM}/join-requests`]: () => {
        asked = true
        return json(request({ user: member }), 201)
      },
    })
    renderApp('/')

    await userEvent.click(await screen.findByRole('button', { name: 'Ask to join' }))
    await userEvent.type(screen.getByLabelText('A note for the admins (optional)'), 'Hi!')
    await userEvent.click(screen.getByRole('button', { name: 'Send request' }))

    expect(await screen.findByText('Request sent to Payments')).toBeInTheDocument()
    expect(
      await calls.find((r) => r.url.endsWith(`/teams/${OTHER_TEAM}/join-requests`))?.json(),
    ).toEqual({ message: 'Hi!' })
    expect(await screen.findByText('Waiting for approval')).toBeInTheDocument()
  })
})

describe('team workspace', () => {
  it('sends the active team with every request', async () => {
    const { calls } = signedIn()
    renderApp('/')
    await screen.findByRole('heading', { name: 'Dashboard' })
    const dash = calls.find((r) => new URL(r.url).pathname === '/api/v1/dashboard/summary')
    expect(dash?.headers.get('X-Team-Id')).toBe(TEST_TEAM_ID)
  })

  it('hides "New task" from viewers of the team', async () => {
    signedIn({ ...member, role: 'viewer' })
    renderApp('/')
    await screen.findByRole('heading', { name: 'Dashboard' })
    expect(screen.queryByRole('button', { name: /New task/ })).not.toBeInTheDocument()
  })

  it('lets the team admin approve a join request with a chosen role', async () => {
    const { calls } = signedIn(demoUser, {
      [`GET /api/v1/teams/${TEST_TEAM_ID}/join-requests`]: () =>
        json([request({ team: { id: TEST_TEAM_ID, name: 'Test Team', slug: 'test-team' } })]),
      'POST /api/v1/teams/join-requests/req-1/approve': () =>
        json(request({ status: 'approved', granted_role: 'viewer' })),
    })
    renderApp('/team/requests')

    expect(await screen.findByText('On call for payouts')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Role for Max Weber'), 'viewer')
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }))

    expect(await screen.findByText('Max Weber joined as viewer')).toBeInTheDocument()
    expect(await calls.find((r) => r.url.endsWith('/approve'))?.json()).toEqual({ role: 'viewer' })
  })

  it('opens a join-request notification on the requests page', async () => {
    signedIn(demoUser, {
      'GET /api/v1/notifications': () =>
        json({
          items: [
            {
              id: 'n1',
              kind: 'team_join_requested',
              title: 'Max Weber asked to join Test Team',
              body: 'On call for payouts',
              incident_id: null,
              incident_key: null,
              team_id: TEST_TEAM_ID,
              link: `/team/requests?team=${TEST_TEAM_ID}`,
              actor: null,
              read_at: null,
              created_at: new Date().toISOString(),
            },
          ],
          unread_count: 1,
        }),
      'POST /api/v1/notifications/n1/read': () => new Response(null, { status: 204 }),
    })
    renderApp('/notifications')
    await userEvent.click(await screen.findByText('Max Weber asked to join Test Team'))
    expect(await screen.findByRole('navigation', { name: 'Team sections' })).toBeInTheDocument()
  })
})

describe('team admin pages', () => {
  it('there is no platform Admin Console', async () => {
    signedIn(demoUser)
    renderApp('/admin')
    // Unknown route: back to the team workspace.
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
  })

  it('keeps the email outbox for the team admins', async () => {
    const { count } = signedIn(member)
    renderApp('/admin/outbox')
    expect(await screen.findByRole('heading', { name: 'Team admins only' })).toBeInTheDocument()
    expect(count('GET /api/v1/admin/outbox')).toBe(0)
  })
})

describe('sign-in extras', () => {
  const signedOut: Record<string, Handler> = {
    'POST /api/v1/auth/refresh': () => apiError(401, 'refresh_missing', 'No refresh token'),
  }

  it('offers Google when the server has it set up', async () => {
    mockApi({
      ...signedOut,
      'GET /api/v1/auth/config': () =>
        json({ allow_self_register: true, demo_mode: false, google_enabled: true }),
    })
    renderApp('/login')
    const google = await screen.findByRole('link', { name: 'Continue with Google' })
    expect(google.getAttribute('href')).toMatch(/\/api\/v1\/auth\/google\/start\?next=%2F$/)
  })

  it('explains a failed Google sign-in', async () => {
    mockApi(signedOut)
    renderApp('/login?error=registration_closed')
    expect(await screen.findByRole('alert')).toHaveTextContent(/sign-ups are closed/)
  })

  it('sends a reset link without saying whether the account exists', async () => {
    const { calls } = mockApi({
      ...signedOut,
      'POST /api/v1/auth/forgot-password': () => new Response(null, { status: 202 }),
    })
    renderApp('/login')
    await userEvent.click(await screen.findByRole('link', { name: 'Forgot password?' }))
    await userEvent.type(await screen.findByLabelText('Email'), 'mira@demo.io')
    await userEvent.click(screen.getByRole('button', { name: 'Send reset link' }))
    expect(await screen.findByRole('heading', { name: 'Check your email' })).toBeInTheDocument()
    expect(screen.getByText(/If an account exists for/)).toBeInTheDocument()
    expect(
      await calls.find((r) => r.method === 'POST' && r.url.endsWith('/forgot-password'))?.json(),
    ).toEqual({
      email: 'mira@demo.io',
    })
  })

  it('sets a new password from the emailed link', async () => {
    const { calls } = mockApi({
      ...signedOut,
      'POST /api/v1/auth/reset-password': () => new Response(null, { status: 204 }),
    })
    renderApp('/reset-password?token=abcdefghijklmnopqrstuvwxyz')
    await userEvent.type(await screen.findByLabelText('New password'), 'correct-horse-9!')
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'correct-horse-9!')
    await userEvent.click(screen.getByRole('button', { name: 'Save new password' }))

    expect(
      await screen.findByText('Password changed. Sign in with your new password.'),
    ).toBeInTheDocument()
    expect(await calls.find((r) => r.url.endsWith('/reset-password'))?.json()).toEqual({
      token: 'abcdefghijklmnopqrstuvwxyz',
      password: 'correct-horse-9!',
    })
  })

  it('offers a fresh link when the reset link has expired', async () => {
    mockApi({
      ...signedOut,
      'POST /api/v1/auth/reset-password': () =>
        apiError(
          422,
          'reset_invalid',
          'This reset link is invalid or has expired. Ask for a new one.',
        ),
    })
    renderApp('/reset-password?token=abcdefghijklmnopqrstuvwxyz')
    await userEvent.type(await screen.findByLabelText('New password'), 'longenough1')
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'longenough1')
    await userEvent.click(screen.getByRole('button', { name: 'Save new password' }))
    expect(await screen.findByRole('link', { name: 'Send me a new link' })).toBeInTheDocument()
  })
})

describe('create or join another team', () => {
  it('opens as a dialog from the team switcher, and from ?find=team links', async () => {
    signedIn(member, {
      'GET /api/v1/teams/mine': () => json({ teams: [testTeam()], requests: [] }),
      'GET /api/v1/teams/discover': () => json([]),
    })
    renderApp('/?find=team')
    const dialog = await screen.findByRole('dialog', { name: 'Create or join a team' })
    expect(dialog).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Join a team' })).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /Switch team/ }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Create or join a team' }))
    expect(await screen.findByRole('dialog', { name: 'Create or join a team' })).toBeInTheDocument()
  })
})

describe('first sign-in', () => {
  const newcomer: TestUser = { ...member, onboarded: false }
  const onboarded = () => json({ ...newcomer, onboarded: true })

  it('asks a new account to create a team, with no join search or team list', async () => {
    signedIn(newcomer, { 'GET /api/v1/teams/mine': () => json({ teams: [], requests: [] }) })
    renderApp('/')
    expect(await screen.findByRole('heading', { name: 'Create your team' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Skip for now' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Join a team' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Ask to join' })).not.toBeInTheDocument()
  })

  it('creates the team, finishes onboarding and opens the workspace', async () => {
    let created = false
    const payments = testTeam({ id: OTHER_TEAM, name: 'Payments', my_role: 'admin' })
    const { count } = signedIn(newcomer, {
      'GET /api/v1/teams/mine': () => json({ teams: created ? [payments] : [], requests: [] }),
      'POST /api/v1/teams': () => {
        created = true
        return json(payments, 201)
      },
      'POST /api/v1/auth/me/onboarded': onboarded,
    })
    renderApp('/')

    await userEvent.type(await screen.findByLabelText('Team name'), 'Payments')
    expect(screen.getByText('P')).toBeInTheDocument() // the badge previews the team
    await userEvent.click(screen.getByRole('button', { name: /Create team/ }))

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(count('POST /api/v1/teams')).toBe(1)
    expect(count('POST /api/v1/auth/me/onboarded')).toBe(1)
  })

  it('can skip creating a team, which leads on to the team finder', async () => {
    const { count } = signedIn(newcomer, {
      'GET /api/v1/teams/mine': () => json({ teams: [], requests: [] }),
      'GET /api/v1/teams/discover': () => json([]),
      'POST /api/v1/auth/me/onboarded': onboarded,
    })
    renderApp('/')
    await userEvent.click(await screen.findByRole('button', { name: 'Skip for now' }))

    expect(
      await screen.findByRole('heading', { name: 'You are not in a team yet, Mira' }),
    ).toBeInTheDocument()
    expect(count('POST /api/v1/auth/me/onboarded')).toBe(1)
  })

  it('is not shown again once answered', async () => {
    signedIn(member, { 'GET /api/v1/teams/mine': () => json({ teams: [], requests: [] }) })
    renderApp('/get-started')
    expect(
      await screen.findByRole('heading', { name: 'You are not in a team yet, Mira' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Create your team' })).not.toBeInTheDocument()
  })
})

describe('loading', () => {
  it('shows a skeleton of the workspace while the teams load, then the real page', async () => {
    let release: () => void = () => undefined
    const teamsReady = new Promise<void>((resolve) => {
      release = resolve
    })
    signedIn(member, {
      'GET /api/v1/teams/mine': async () => {
        await teamsReady
        return json({ teams: [testTeam()], requests: [] })
      },
    })
    renderApp('/')

    expect(
      await screen.findByRole('status', { name: 'Loading your workspace' }),
    ).toBeInTheDocument()
    release()
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    expect(screen.queryByRole('status', { name: 'Loading your workspace' })).not.toBeInTheDocument()
  })
})
