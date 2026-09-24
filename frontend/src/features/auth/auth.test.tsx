import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { setSession } from '@/api/client'
import { dashboard } from '@/test/fixtures'
import { apiError, demoUser, json, mockApi, tokenOut, type Handler } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const team = [
  {
    id: demoUser.id,
    name: 'Ada Admin',
    email: 'admin@demo.io',
    role: 'admin',
    avatar_color: '#4DD0E1',
  },
  { id: '2', name: 'Mira Patel', email: 'mira@demo.io', role: 'member', avatar_color: '#3DDC97' },
]
const health = { status: 'ok', db: 'ok', version: '0.1.0', git_sha: 'abc', env: 'test' }

const signedOut: Record<string, Handler> = {
  'POST /api/v1/auth/refresh': () => apiError(401, 'refresh_missing', 'No refresh token'),
  'GET /api/v1/users': () => json(team),
  'GET /api/v1/health': () => json(health),
  'GET /api/v1/dashboard/summary': () => json(dashboard()),
}

afterEach(() => {
  setSession(null, null)
})

describe('authentication flow', () => {
  it('shows no demo accounts or register link on a real deployment', async () => {
    mockApi({
      ...signedOut,
      'GET /api/v1/auth/config': () => json({ allow_self_register: false, demo_mode: false }),
    })
    renderApp('/login')
    await screen.findByRole('heading', { name: 'Sign in to Tasky' })
    await waitFor(() => {
      expect(screen.queryByText(/Demo accounts/)).not.toBeInTheDocument()
    })
    expect(screen.queryByText(/demo1234/)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Create one' })).not.toBeInTheDocument()
  })

  it('explains that registration is closed', async () => {
    mockApi({
      ...signedOut,
      'GET /api/v1/auth/config': () => json({ allow_self_register: false, demo_mode: false }),
    })
    renderApp('/register')
    expect(
      await screen.findByRole('heading', { name: 'Registration is closed' }),
    ).toBeInTheDocument()
  })

  it('shows signed-out visitors the landing page, with a way to log in', async () => {
    mockApi(signedOut)

    renderApp('/')

    expect(
      await screen.findByRole('heading', { name: /Plan it. Assign it. Get it done./ }),
    ).toBeInTheDocument()
    const logIns = screen.getAllByRole('link', { name: 'Log in' })
    expect(logIns[0]).toHaveAttribute('href', '/login')
    expect(screen.getAllByRole('link', { name: /Get started/ })[0]).toHaveAttribute(
      'href',
      '/register',
    )
  })

  it('sends signed-out visitors of any other page to the login page', async () => {
    mockApi(signedOut)

    renderApp('/tasks')

    const heading = await screen.findByRole('heading', { name: 'Sign in to Tasky' })
    await waitFor(() => {
      expect(heading).toBeVisible() // after the card's entrance fade
    })
  })

  it('resumes the session from the refresh cookie on load', async () => {
    mockApi({ ...signedOut, 'POST /api/v1/auth/refresh': () => json(tokenOut()) })

    renderApp('/')

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeVisible()
  })

  it('logs in with a demo account and lands on the dashboard', async () => {
    const { calls } = mockApi({
      ...signedOut,
      'GET /api/v1/auth/config': () => json({ allow_self_register: true, demo_mode: true }),
      'POST /api/v1/auth/login': () => json(tokenOut()),
    })
    renderApp('/login')
    await screen.findByRole('heading', { name: 'Sign in to Tasky' })

    await userEvent.click(screen.getByRole('button', { name: 'Admin' }))
    expect(screen.getByLabelText('Email')).toHaveValue('admin@demo.io')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeVisible()
    expect(await screen.findByText('SLA breached')).toBeVisible()
    const login = calls.find((r) => r.url.endsWith('/api/v1/auth/login'))
    expect(await login?.json()).toEqual({ email: 'admin@demo.io', password: 'demo1234' })
    const summary = calls.find((r) => r.url.endsWith('/api/v1/dashboard/summary'))
    expect(summary?.headers.get('authorization')).toBe('Bearer access-1')
  })

  it('shows the server message and request id on bad credentials', async () => {
    mockApi({
      ...signedOut,
      'POST /api/v1/auth/login': () =>
        apiError(401, 'invalid_credentials', 'Invalid email or password'),
    })
    renderApp('/login')

    await userEvent.type(await screen.findByLabelText('Email'), 'admin@demo.io')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Invalid email or password')
    expect(alert).toHaveTextContent('req_ERR')
  })

  it('signs out and returns to the login page', async () => {
    const { count } = mockApi({
      ...signedOut,
      'POST /api/v1/auth/refresh': () => json(tokenOut()),
      'POST /api/v1/auth/logout': () => new Response(null, { status: 204 }),
    })
    renderApp('/')
    await screen.findByRole('heading', { name: 'Dashboard' })

    await userEvent.click(screen.getByRole('button', { name: 'Account menu' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Sign out' }))

    const heading = await screen.findByRole('heading', { name: 'Sign in to Tasky' })
    await waitFor(() => {
      expect(heading).toBeVisible() // after the card's entrance fade
    })
    expect(count('POST /api/v1/auth/logout')).toBe(1)
  })

  it('maps 422 field errors and 409 email_taken onto the register form', async () => {
    let attempt = 0
    mockApi({
      ...signedOut,
      'POST /api/v1/auth/register': () =>
        ++attempt === 1
          ? apiError(422, 'validation_error', 'Request validation failed', {
              fields: [
                { loc: ['body', 'password'], message: 'String should have at least 8 characters' },
              ],
            })
          : apiError(409, 'email_taken', 'An account with this email already exists'),
    })
    renderApp('/register')

    await userEvent.type(await screen.findByLabelText('Name'), 'New Person')
    await userEvent.type(screen.getByLabelText('Email'), 'admin@demo.io')
    await userEvent.type(screen.getByLabelText('Password'), 'short')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText('String should have at least 8 characters')).toBeVisible()

    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    await waitFor(() => {
      expect(screen.getByText('An account with this email already exists')).toBeVisible()
    })
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true')
  })
})
