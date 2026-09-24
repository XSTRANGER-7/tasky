import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { setSession } from '@/api/client'
import { dashboard, incident, team } from '@/test/fixtures'
import { apiError, json, mockApi, tokenOut, type Handler } from '@/test/mockApi'
import { renderApp } from '@/test/render'

afterEach(() => {
  setSession(null, null)
})

function api(extra: Record<string, Handler> = {}) {
  return mockApi({
    'POST /api/v1/auth/refresh': () => json(tokenOut()),
    'GET /api/v1/users': () => json(team),
    'GET /api/v1/dashboard/summary': () => json(dashboard()),
    'GET /api/v1/health': () =>
      json({ status: 'ok', db: 'ok', version: '1', git_sha: 'x', env: 't' }),
    'GET /api/v1/incidents/INC-8': () => json(incident({ key: 'INC-8', title: 'Disk full' })),
    'GET /api/v1/incidents/INC-8/comments': () => json([]),
    ...extra,
  })
}

async function openDrawer() {
  await screen.findByRole('heading', { name: 'Dashboard' })
  fireEvent.keyDown(window, { key: 'c' })
  return screen.findByRole('dialog', { name: 'New task' })
}

describe('create task drawer', () => {
  it('opens with C, validates the title client-side', async () => {
    const { count } = api()
    renderApp('/')

    await openDrawer()
    await userEvent.type(screen.getByLabelText('Title'), 'ab')
    await userEvent.click(screen.getByRole('button', { name: 'Create task' }))

    expect(await screen.findByText('At least 3 characters')).toBeInTheDocument()
    expect(count('POST /api/v1/incidents')).toBe(0)
  })

  it('creates with an Idempotency-Key and lands on the new task', async () => {
    const { calls } = api({
      'POST /api/v1/incidents': () => json(incident({ key: 'INC-8', title: 'Disk full' }), 201),
    })
    renderApp('/')

    await openDrawer()
    await userEvent.type(screen.getByLabelText('Title'), 'Disk full')
    await userEvent.click(screen.getByRole('radio', { name: 'Critical' }))
    await userEvent.type(screen.getByLabelText('Category'), 'infra')
    await userEvent.type(screen.getByLabelText('Tags'), 'prod{Enter}')
    await userEvent.click(screen.getByRole('button', { name: 'Create task' }))

    // Regression: the drawer must really unmount. It once lingered, invisible and still
    // modal, after a priority had been picked -- hiding the page from everyone.
    await waitFor(() => {
      expect(screen.queryByRole('dialog', { name: 'New task' })).not.toBeInTheDocument()
    })
    expect(await screen.findByRole('heading', { name: 'Disk full' })).toBeInTheDocument()
    const req = calls.find((r) => r.url.endsWith('/api/v1/incidents') && r.method === 'POST')
    expect(req?.headers.get('idempotency-key')).toMatch(/^[0-9a-f-]{36}$/)
    expect(await req?.json()).toEqual({
      title: 'Disk full',
      description: '',
      priority: 'critical',
      assignee_id: null,
      category: 'infra',
      tags: ['prod'],
    })
  })

  it('maps server validation errors onto fields', async () => {
    api({
      'POST /api/v1/incidents': () =>
        apiError(422, 'validation_error', 'Request validation failed', {
          fields: [
            { loc: ['body', 'category'], message: 'String should have at most 50 characters' },
          ],
        }),
    })
    renderApp('/')

    await openDrawer()
    await userEvent.type(screen.getByLabelText('Title'), 'Valid title')
    await userEvent.click(screen.getByRole('button', { name: 'Create task' }))

    await waitFor(() => {
      expect(screen.getByText('String should have at most 50 characters')).toBeInTheDocument()
    })
  })

  it('is not offered to viewers', async () => {
    api({
      'POST /api/v1/auth/refresh': () =>
        json(tokenOut('t', { ...tokenOut().user, role: 'viewer' as never })),
    })
    renderApp('/')

    await screen.findByRole('heading', { name: 'Dashboard' })
    fireEvent.keyDown(window, { key: 'c' })
    expect(screen.queryByRole('button', { name: /New task/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
