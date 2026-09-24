import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { setSession } from '@/api/client'
import { ada, incident, jonas, team } from '@/test/fixtures'
import {
  apiError,
  demoUser,
  json,
  mockApi,
  sseChannel,
  tokenOut,
  type Handler,
} from '@/test/mockApi'
import { renderApp } from '@/test/render'

afterEach(() => {
  setSession(null, null)
})

function api(extra: Record<string, Handler> = {}, base = incident()) {
  return mockApi({
    'POST /api/v1/auth/refresh': () => json(tokenOut()),
    'GET /api/v1/users': () => json(team),
    'GET /api/v1/health': () =>
      json({ status: 'ok', db: 'ok', version: '1', git_sha: 'x', env: 't' }),
    'GET /api/v1/incidents/INC-7': () => json(base),
    'GET /api/v1/incidents/INC-7/comments': () => json([]),
    'GET /api/v1/incidents/INC-7/events': () => json([]),
    ...extra,
  })
}

const statusButton = () => screen.findByRole('button', { name: /^Status: / })

describe('task detail', () => {
  it('offers exactly the transitions the server allows', async () => {
    api()
    renderApp('/tasks/INC-7')

    await userEvent.click(await statusButton())

    const items = await screen.findAllByRole('menuitem')
    expect(items.map((i) => i.textContent)).toEqual(['Start workIn progress', 'ResolveResolved'])
  })

  it('redirects an old /incidents/:key link to the task page', async () => {
    api()
    renderApp('/incidents/INC-7')

    await screen.findByRole('heading', { name: 'Checkout API returning 502' })
    // The Tasks tab is current only under /tasks/..., and the page links back to /tasks.
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: 'Tasks' })).toHaveAttribute('aria-current', 'page')
    expect(
      screen.getAllByRole('link', { name: 'Tasks' }).map((a) => a.getAttribute('href')),
    ).toContain('/tasks')
  })

  it('shows a read-only pill when no transition is allowed', async () => {
    api(
      {},
      incident({
        allowed_transitions: [],
        permissions: { can_edit: false, can_assign: false, can_comment: false, can_delete: false },
      }),
    )
    renderApp('/tasks/INC-7')

    await screen.findByRole('heading', { name: 'Checkout API returning 502' })
    expect(screen.queryByRole('button', { name: /^Status: / })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Comment' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete task' })).not.toBeInTheDocument()
  })

  it('changes status optimistically and keeps the server result', async () => {
    const { calls } = api({
      'POST /api/v1/incidents/INC-7/transition': () =>
        json(incident({ status: 'in_progress', allowed_transitions: ['open', 'resolved'] })),
    })
    renderApp('/tasks/INC-7')

    await userEvent.click(await statusButton())
    await userEvent.click(await screen.findByRole('menuitem', { name: /Start work/ }))

    expect(
      await screen.findByRole('button', { name: 'Status: In progress. Change status' }),
    ).toBeInTheDocument()
    const body = await calls.find((r) => r.url.endsWith('/transition'))?.json()
    expect(body).toEqual({ status: 'in_progress' })
  })

  it('rolls back and explains when the server refuses', async () => {
    api({
      'POST /api/v1/incidents/INC-7/transition': () =>
        apiError(409, 'invalid_transition', 'Cannot move from closed to open'),
    })
    renderApp('/tasks/INC-7')

    await userEvent.click(await statusButton())
    await userEvent.click(await screen.findByRole('menuitem', { name: /Start work/ }))

    expect(await screen.findByText('Cannot move from closed to open')).toBeInTheDocument()
    expect(
      await screen.findByRole('button', { name: 'Status: Open. Change status' }),
    ).toBeInTheDocument()
  })

  it('asks for a note when resolving and sends it', async () => {
    const { calls } = api({
      'POST /api/v1/incidents/INC-7/transition': () =>
        json(incident({ status: 'resolved', allowed_transitions: ['open'] })),
    })
    renderApp('/tasks/INC-7')

    await userEvent.click(await statusButton())
    await userEvent.click(await screen.findByRole('menuitem', { name: /Resolve/ }))
    await userEvent.type(await screen.findByRole('textbox', { name: 'Note' }), 'Rolled back v2.14')
    await userEvent.click(screen.getByRole('button', { name: 'Resolve' }))

    await waitFor(async () => {
      const req = calls.find((r) => r.url.endsWith('/transition'))
      expect(await req?.clone().json()).toEqual({ status: 'resolved', note: 'Rolled back v2.14' })
    })
  })

  it('posts a comment and renders it as sanitised markdown', async () => {
    const comment = {
      id: 'c1',
      incident_id: incident().id,
      author: jonas,
      body: 'Fixed **it** <script>alert(1)</script>',
      is_internal: false,
      created_at: new Date().toISOString(),
      edited_at: null,
      can_modify: true,
    }
    let thread: (typeof comment)[] = []
    const { calls } = api({
      'GET /api/v1/incidents/INC-7/comments': () => json(thread),
      'POST /api/v1/incidents/INC-7/comments': () => {
        thread = [comment]
        return json(comment, 201)
      },
    })
    renderApp('/tasks/INC-7')

    await userEvent.type(await screen.findByRole('combobox', { name: 'Comment' }), 'Fixed **it**')
    await userEvent.click(screen.getByRole('button', { name: 'Comment' }))

    const bold = await screen.findByText('it', { selector: 'strong' })
    expect(bold).toBeInTheDocument()
    expect(document.querySelector('script')).toBeNull()
    const body = await calls.find((r) => r.url.endsWith('/comments') && r.method === 'POST')?.json()
    expect(body).toEqual({ body: 'Fixed **it**', is_internal: false })
  })

  it('watches and unwatches, showing who is watching', async () => {
    let watching = false
    const { count } = api({
      'POST /api/v1/incidents/INC-7/watch': () => {
        watching = true
        return json(incident({ watching: true, watchers: [ada] }))
      },
      'DELETE /api/v1/incidents/INC-7/watch': () => {
        watching = false
        return json(incident({ watching: false, watchers: [] }))
      },
    })
    renderApp('/tasks/INC-7')

    expect(await screen.findByText('Nobody yet')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Watch', pressed: false }))

    expect(
      await screen.findByRole('button', { name: 'Watching', pressed: true }),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Watched by Ada Admin')).toBeInTheDocument()
    expect(watching).toBe(true)

    await userEvent.click(screen.getByRole('button', { name: 'Watching' }))
    expect(await screen.findByRole('button', { name: 'Watch', pressed: false })).toBeInTheDocument()
    expect(count('DELETE /api/v1/incidents/INC-7/watch')).toBe(1)
  })

  it('autocompletes @mentions with the email handle', async () => {
    api()
    renderApp('/tasks/INC-7')

    const box = await screen.findByRole('combobox', { name: 'Comment' })
    await userEvent.type(box, 'cc @jo')

    const options = await screen.findAllByRole('option')
    expect(options.map((o) => o.textContent)).toEqual(['JWJonas Weber@jonas'])
    await userEvent.keyboard('{Enter}')

    expect(box).toHaveValue('cc @jonas ')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()

    // Escape dismisses without inserting.
    await userEvent.type(box, 'and @ad')
    expect(await screen.findByRole('option', { name: /Ada Admin/ })).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(box).toHaveValue('cc @jonas and @ad')
  })

  it('refetches when the live stream says the task changed', async () => {
    const stream = sseChannel()
    let title = 'Checkout API returning 502'
    api({
      'GET /api/v1/incidents/INC-7': () => json(incident({ title })),
      'GET /api/v1/events/stream': stream.response,
    })
    renderApp('/tasks/INC-7')

    await screen.findByRole('heading', { name: title })
    await waitFor(() => {
      expect(stream.connected()).toBe(true)
    })
    title = 'Checkout API recovered'
    stream.send('incident.updated', { type: 'incident.updated', incident: 'INC-7' })

    expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument()
  })

  it('shows a not-found state for unknown tasks', async () => {
    api({ 'GET /api/v1/incidents/INC-404': () => apiError(404, 'not_found', 'Incident not found') })
    renderApp('/tasks/INC-404')

    expect(await screen.findByText('Task not found')).toBeInTheDocument()
  })
})

describe('people on a task', () => {
  it('adds a teammate, who is emailed about it', async () => {
    const { calls } = api({
      'POST /api/v1/incidents/INC-7/watchers': () => json(incident({ watchers: [jonas] })),
    })
    renderApp('/tasks/INC-7')

    await userEvent.click(await screen.findByRole('button', { name: 'Add people' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: /Jonas Weber/ }))

    expect(await screen.findByText('Added Jonas Weber')).toBeInTheDocument()
    expect(screen.getByText('They were emailed about it.')).toBeInTheDocument()
    const post = calls.find((r) => r.url.endsWith('/INC-7/watchers'))
    expect(await post?.json()).toEqual({ user_id: jonas.id })
  })
})

describe('several assignees', () => {
  it('ticks a second person in; both are sent, the first stays the lead', async () => {
    const { calls } = api({
      'PUT /api/v1/incidents/INC-7/assignees': () =>
        json(incident({ assignee: jonas, assignees: [jonas, ada] })),
    })
    renderApp('/tasks/INC-7')

    await userEvent.click(await screen.findByRole('button', { name: /^Assigned to: / }))
    await userEvent.click(await screen.findByRole('menuitemcheckbox', { name: /Ada Admin/ }))

    expect(await screen.findByText('Assigned Ada Admin')).toBeInTheDocument()
    const put = calls.find((r) => r.method === 'PUT' && r.url.endsWith('/INC-7/assignees'))
    expect(await put?.json()).toEqual({ user_ids: [jonas.id, ada.id] })
  })

  it('only team admins get the Add people button', async () => {
    mockApi({
      'POST /api/v1/auth/refresh': () =>
        json(tokenOut('access-1', { ...demoUser, role: 'member' as never })),
      'GET /api/v1/users': () => json(team),
      'GET /api/v1/health': () =>
        json({ status: 'ok', db: 'ok', version: '1', git_sha: 'x', env: 't' }),
      'GET /api/v1/incidents/INC-7': () => json(incident()),
      'GET /api/v1/incidents/INC-7/comments': () => json([]),
      'GET /api/v1/incidents/INC-7/events': () => json([]),
    })
    renderApp('/tasks/INC-7')
    await screen.findByRole('heading', { name: 'Checkout API returning 502' })
    expect(screen.queryByRole('button', { name: 'Add people' })).not.toBeInTheDocument()
  })
})

describe('older API responses', () => {
  it('renders a task that has no assignees list (API from before several assignees)', async () => {
    const legacy: Partial<ReturnType<typeof incident>> = incident()
    delete legacy.assignees
    api({}, legacy as ReturnType<typeof incident>)
    renderApp('/tasks/INC-7')

    expect(
      await screen.findByRole('heading', { name: 'Checkout API returning 502' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Assigned to: Jonas Weber' })).toBeInTheDocument()
    expect(screen.queryByText('This page hit a problem')).not.toBeInTheDocument()
  })
})

describe('who is who on a task', () => {
  it('labels the creator, the people assigned, and who assigned them', async () => {
    api({}, incident({ assignees: [jonas, ada], assigned_by: ada }))
    renderApp('/tasks/INC-7')

    expect(await screen.findByText(/^Created by Ada Admin/)).toBeInTheDocument()
    expect(screen.getByText('Created by', { selector: 'dt' })).toBeInTheDocument()
    expect(screen.getByText('Assigned to', { selector: 'dt' })).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Assigned to: Jonas Weber, Ada Admin' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Assigned by Ada Admin')).toBeInTheDocument()
  })
})
