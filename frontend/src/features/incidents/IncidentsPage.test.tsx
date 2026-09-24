import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { setSession } from '@/api/client'
import { incident, page, team } from '@/test/fixtures'
import { json, mockApi, tokenOut, type Handler } from '@/test/mockApi'
import { renderApp } from '@/test/render'

const rows = [
  incident({ id: 'a', key: 'INC-3', number: 3, title: 'Checkout down', priority: 'critical' }),
  incident({ id: 'b', key: 'INC-2', number: 2, title: 'VPN flaps', status: 'in_progress' }),
  incident({
    id: 'c',
    key: 'INC-1',
    number: 1,
    title: 'Backup late',
    sla: { response_breached: true, resolution_breached: true, at_risk: false, paused: false },
    resolution_due_at: new Date(Date.now() - 3_600_000).toISOString(),
  }),
]

function api(extra: Record<string, Handler> = {}) {
  return mockApi({
    'POST /api/v1/auth/refresh': () => json(tokenOut()),
    'GET /api/v1/users': () => json(team),
    'GET /api/v1/incidents': () => json(page(rows)),
    'GET /api/v1/health': () =>
      json({ status: 'ok', db: 'ok', version: '1', git_sha: 'x', env: 't' }),
    ...extra,
  })
}

afterEach(() => {
  setSession(null, null)
})

function listQueries(calls: Request[]): URLSearchParams[] {
  return calls
    .filter((r) => new URL(r.url).pathname === '/api/v1/incidents')
    .map((r) => new URL(r.url).searchParams)
}

describe('task list', () => {
  it('renders rows with key, title, status and a breached SLA', async () => {
    api()
    renderApp('/tasks')

    const list = await screen.findByRole('region', { name: 'Task list' })
    expect(await within(list).findByText('Checkout down')).toBeInTheDocument()
    expect(within(list).getByText('INC-2')).toBeInTheDocument()
    expect(screen.getByText('3 tasks')).toBeInTheDocument()
    expect(within(list).getByText(/over$/)).toBeInTheDocument() // breached countdown
  })

  it('turns URL filters into API query params', async () => {
    const { calls } = api()
    renderApp(
      '/tasks?status=open&status=in_progress&priority=critical&q=db&sort=-priority,-created_at',
    )

    await screen.findByText('Checkout down')
    const params = listQueries(calls)[0]
    expect(params?.getAll('status')).toEqual(['open', 'in_progress'])
    expect(params?.get('priority')).toBe('critical')
    expect(params?.get('q')).toBe('db')
    expect(params?.get('sort')).toBe('-priority,-created_at')
    expect(params?.get('limit')).toBe('25')
  })

  it('"My work" means open work assigned to me', async () => {
    const { calls } = api()
    renderApp('/tasks?view=mine')

    await screen.findByText('Checkout down')
    const params = listQueries(calls)[0]
    expect(params?.get('assignee')).toBe('me')
    expect(params?.getAll('status')).toEqual(['open', 'in_progress'])
  })

  it('old /incidents links redirect to /tasks and keep the view', async () => {
    const { calls } = api()
    renderApp('/incidents?view=mine')

    await screen.findByText('Checkout down')
    expect(listQueries(calls)[0]?.get('assignee')).toBe('me')
    // "My work" is only the current tab on /tasks?view=mine.
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: 'My work' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(within(nav).getByRole('link', { name: 'Tasks' })).not.toHaveAttribute('aria-current')
  })

  it('the breached view asks the server for sla=breached', async () => {
    const { calls } = api()
    renderApp('/tasks')
    await screen.findByText('Checkout down')

    await userEvent.click(screen.getByRole('button', { name: 'SLA breached' }))

    await waitFor(() => {
      expect(listQueries(calls).some((p) => p.get('sla') === 'breached')).toBe(true)
    })
  })

  it('J/K move the selection and Enter opens the task', async () => {
    api({
      'GET /api/v1/incidents/INC-2': () => json(rows[1]),
      'GET /api/v1/incidents/INC-2/comments': () => json([]),
    })
    renderApp('/tasks')
    await screen.findByText('Checkout down')

    const current = () => document.querySelector('[aria-current="true"]')?.textContent ?? ''
    expect(current()).toContain('INC-3')
    fireEvent.keyDown(window, { key: 'j' })
    fireEvent.keyDown(window, { key: 'j' })
    expect(current()).toContain('INC-1')
    fireEvent.keyDown(window, { key: 'k' })
    expect(current()).toContain('INC-2')
    fireEvent.keyDown(window, { key: 'Enter' })

    expect(await screen.findByRole('heading', { name: 'VPN flaps' })).toBeInTheDocument()
  })

  it('shows an empty state that clears filters', async () => {
    api({ 'GET /api/v1/incidents': () => json(page([])) })
    renderApp('/tasks?priority=low')

    expect(await screen.findByText('No tasks match these filters')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(await screen.findByText('No tasks yet')).toBeInTheDocument()
  })
})
