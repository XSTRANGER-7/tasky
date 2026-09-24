/** Phases 6 and 7: attachments and AI assistance (suggest, never act). */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { setSession } from '@/api/client'
import { ada, dashboard, incident, jonas, page, team } from '@/test/fixtures'
import { json, mockApi, tokenOut, type Handler } from '@/test/mockApi'
import { renderApp } from '@/test/render'

afterEach(() => {
  setSession(null, null)
})

const AI_ON = { enabled: true, provider: 'rules', model: 'rules-v1', features: ['triage'] }
const AI_OFF = { enabled: false, provider: 'none', model: null, features: [] }

function api(extra: Record<string, Handler> = {}, ai: unknown = AI_ON) {
  return mockApi({
    'POST /api/v1/auth/refresh': () => json(tokenOut()),
    'GET /api/v1/users': () => json(team),
    'GET /api/v1/health': () =>
      json({ status: 'ok', db: 'ok', version: '1', git_sha: 'x', env: 't' }),
    'GET /api/v1/dashboard/summary': () => json(dashboard()),
    'GET /api/v1/ai/status': () => json(ai),
    'GET /api/v1/incidents/INC-7': () => json(incident()),
    'GET /api/v1/incidents/INC-7/comments': () => json([]),
    'GET /api/v1/incidents/INC-7/events': () => json([]),
    'GET /api/v1/incidents/INC-7/attachments': () => json([]),
    ...extra,
  })
}

function attachment(overrides: Record<string, unknown> = {}) {
  return {
    id: 'a-1',
    incident_id: incident().id,
    comment_id: null,
    filename: 'error.log',
    content_type: 'text/plain',
    size_bytes: 2048,
    is_image: false,
    uploader: ada,
    created_at: new Date().toISOString(),
    can_delete: true,
    ...overrides,
  }
}

describe('attachments', () => {
  it('uploads the raw file with its name, lists it and removes it', async () => {
    let files: ReturnType<typeof attachment>[] = []
    const { calls } = api({
      'GET /api/v1/incidents/INC-7/attachments': () => json(files),
      'POST /api/v1/incidents/INC-7/attachments': () => {
        files = [attachment()]
        return json(files[0], 201)
      },
      'DELETE /api/v1/attachments/a-1': () => {
        files = []
        return new Response(null, { status: 204 })
      },
    })
    renderApp('/tasks/INC-7')

    const input = await screen.findByLabelText('Choose files to attach')
    await userEvent.upload(input, new File(['boom\n'], 'error.log', { type: 'text/plain' }))

    expect(await screen.findByText('Attached error.log')).toBeInTheDocument()
    const post = calls.find((r) => r.method === 'POST' && r.url.includes('/attachments'))
    expect(new URL(post?.url ?? 'http://x').searchParams.get('filename')).toBe('error.log')
    expect(post?.headers.get('content-type')).toBe('application/octet-stream')
    expect(post?.headers.get('authorization')).toBe('Bearer access-1')
    expect(await screen.findByText(/2\.0 KB/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Remove error.log' }))
    expect(await screen.findByText('Removed error.log')).toBeInTheDocument()
  })

  it('refuses files over 10 MB before uploading', async () => {
    const { count } = api()
    renderApp('/tasks/INC-7')
    const big = new File(['x'], 'huge.log')
    Object.defineProperty(big, 'size', { value: 11 * 1024 * 1024 })
    await userEvent.upload(await screen.findByLabelText('Choose files to attach'), big)

    expect(await screen.findByText('huge.log is larger than 10 MB')).toBeInTheDocument()
    expect(count('POST /api/v1/incidents/INC-7/attachments')).toBe(0)
  })

  it('previews images in a lightbox through a signed link', async () => {
    const image = attachment({
      id: 'img-1',
      filename: 'graph.png',
      content_type: 'image/png',
      is_image: true,
    })
    api({
      'GET /api/v1/incidents/INC-7/attachments': () => json([image]),
      'GET /api/v1/attachments/img-1/download': (req) => {
        expect(req.headers.get('accept')).toBe('application/json')
        return json({ url: '/api/v1/files?key=k&sig=s', expires_in: 300 })
      },
    })
    renderApp('/tasks/INC-7')

    await userEvent.click(await screen.findByRole('button', { name: 'Preview graph.png' }))
    const dialog = await screen.findByRole('dialog', { name: 'graph.png' })
    expect(await within(dialog).findByRole('img', { name: 'graph.png' })).toHaveAttribute(
      'src',
      '/api/v1/files?key=k&sig=s',
    )
  })

  it('viewers see attachments but cannot add any', async () => {
    api({
      'GET /api/v1/incidents/INC-7': () =>
        json(
          incident({
            permissions: {
              can_edit: false,
              can_assign: false,
              can_comment: false,
              can_delete: false,
            },
          }),
        ),
      'GET /api/v1/incidents/INC-7/attachments': () => json([attachment({ can_delete: false })]),
    })
    renderApp('/tasks/INC-7')
    expect(await screen.findByText('error.log')).toBeInTheDocument()
    expect(screen.queryByLabelText('Choose files to attach')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove error.log' })).not.toBeInTheDocument()
  })
})

const triage = {
  suggestion_id: 's-1',
  source: 'rules',
  model: 'rules-v1',
  priority: 'critical',
  category: 'payments',
  assignee: { user: jonas, open_count: 2 },
  confidence: 0.75,
  reasoning: 'priority critical because of "down for all".',
  similar: [],
  possible_duplicate_of: {
    id: 'd-1',
    key: 'INC-3',
    title: 'Checkout down for all users',
    status: 'open',
    priority: 'critical',
    score: 0.82,
  },
  fallback_reason: null,
}

describe('AI triage in the create drawer', () => {
  it('suggests after a pause, flags the duplicate, and applies to the form on accept', async () => {
    const { calls } = api({
      'POST /api/v1/ai/triage': () => json(triage),
      'POST /api/v1/ai/suggestions/s-1/accept': () =>
        json({
          id: 's-1',
          kind: 'triage',
          status: 'accepted',
          decided_at: new Date().toISOString(),
        }),
    })
    renderApp('/')
    await screen.findByRole('heading', { name: 'Dashboard' })
    await userEvent.keyboard('c')
    await userEvent.type(await screen.findByLabelText('Title'), 'Checkout down for all users')

    const card = await screen.findByRole('region', { name: 'AI triage suggestion' })
    expect(await within(card).findByText(/Possible duplicate of/)).toBeInTheDocument()
    expect(within(card).getByText('INC-3')).toHaveAttribute('href', '/tasks/INC-3')
    expect(within(card).getByText('payments')).toBeInTheDocument()
    expect(within(card).getByText('Jonas Weber')).toBeInTheDocument()
    const body = await calls.find((r) => r.url.endsWith('/ai/triage'))?.json()
    expect(body).toEqual({ title: 'Checkout down for all users', description: '' })

    await userEvent.click(within(card).getByRole('button', { name: /Apply to form/ }))
    expect(screen.getByLabelText('Category')).toHaveValue('payments')
    expect(screen.getByRole('button', { name: 'Assigned to: Jonas Weber' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Critical/ })).toHaveAttribute('aria-checked', 'true')
    await waitFor(() => {
      expect(calls.some((r) => r.url.endsWith('/ai/suggestions/s-1/accept'))).toBe(true)
    })
    expect(screen.queryByRole('region', { name: 'AI triage suggestion' })).not.toBeInTheDocument()
  })

  it('is absent when AI is off', async () => {
    const { count } = api({}, AI_OFF)
    renderApp('/')
    await screen.findByRole('heading', { name: 'Dashboard' })
    await userEvent.keyboard('c')
    await userEvent.type(await screen.findByLabelText('Title'), 'Checkout down for all users')
    await new Promise((r) => setTimeout(r, 800))
    expect(screen.queryByRole('region', { name: 'AI triage suggestion' })).not.toBeInTheDocument()
    expect(count('POST /api/v1/ai/triage')).toBe(0)
  })
})

describe('AI on the task page', () => {
  it('summarises the thread on request', async () => {
    api({
      'POST /api/v1/incidents/INC-7/ai/summary': () =>
        json({
          suggestion_id: 'sum-1',
          kind: 'summary',
          source: 'llm',
          model: 'llama-3.3-70b-versatile',
          summary: {
            summary: 'EU checkout failing since the deploy; rollback in progress.',
            current_status: 'In progress (assigned to Jonas).',
            open_questions: ['Mira: is checkout verified?'],
          },
          fallback_reason: null,
        }),
    })
    renderApp('/tasks/INC-7')
    // The assistant sits at the top of the task, above the description.
    const assistant = await screen.findByRole('heading', { name: 'AI assistant' })
    const description = screen.getByRole('heading', { name: 'Description' })
    expect(
      assistant.compareDocumentPosition(description) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    await userEvent.click(await screen.findByRole('button', { name: /Summarize/ }))
    expect(await screen.findByText(/rollback in progress/)).toBeInTheDocument()
    expect(screen.getByText('Mira: is checkout verified?')).toBeInTheDocument()
    expect(screen.getByText('llama-3.3-70b-versatile')).toBeInTheDocument()
  })

  it('drafts an editable postmortem for resolved tasks and posts it as an internal note', async () => {
    const { calls } = api({
      'GET /api/v1/incidents/INC-7': () =>
        json(incident({ status: 'resolved', allowed_transitions: [] })),
      'POST /api/v1/incidents/INC-7/ai/summary': () =>
        json({
          suggestion_id: 'pm-1',
          kind: 'postmortem',
          source: 'rules',
          model: 'rules-v1',
          postmortem: { timeline: [], probable_root_cause: 'x', impact: 'y', action_items: [] },
          markdown: '## Postmortem: INC-7\n\nDraft',
          fallback_reason: 'AI unavailable',
        }),
      'POST /api/v1/ai/suggestions/pm-1/accept': () =>
        json({ id: 'pm-1', kind: 'postmortem', status: 'accepted', decided_at: null }),
    })
    renderApp('/tasks/INC-7')

    await userEvent.click(await screen.findByRole('button', { name: /Draft postmortem/ }))
    expect(await screen.findByText('AI unavailable')).toBeInTheDocument() // fallback is visible
    const draft = screen.getByRole('region', { name: 'Postmortem draft' })
    await userEvent.click(within(draft).getByRole('button', { name: 'Edit' }))
    // "[[" is a literal "[" for userEvent.
    await userEvent.type(screen.getByLabelText('Postmortem Markdown'), '\n- [[ ] Add a probe')
    await userEvent.click(screen.getByRole('button', { name: /Post as internal note/ }))

    expect(await screen.findByText('Postmortem posted as an internal note')).toBeInTheDocument()
    const accept = calls.find((r) => r.url.endsWith('/ai/suggestions/pm-1/accept'))
    expect(await accept?.json()).toEqual({
      markdown: '## Postmortem: INC-7\n\nDraft\n- [ ] Add a probe',
    })
  })
})

describe('plain-language search', () => {
  it('turns "?" queries in the palette into list filters and explains them', async () => {
    const { calls } = api({
      'POST /api/v1/ai/search': () =>
        json({
          suggestion_id: 'q-1',
          source: 'rules',
          model: 'rules-v1',
          filters: {
            status: ['open'],
            priority: ['critical'],
            assignee: 'me',
            sla: null,
            q: 'database',
            sort: null,
          },
          explanation: 'Critical open tasks assigned to you matching "database"',
          fallback_reason: null,
        }),
      'GET /api/v1/incidents': () => json(page([incident()])),
    })
    renderApp('/')
    await screen.findByRole('heading', { name: 'Dashboard' })
    await userEvent.keyboard('{Control>}k{/Control}')
    await userEvent.type(await screen.findByRole('combobox'), '?my critical open database stuff')
    await userEvent.click(
      await screen.findByRole('option', { name: /Find: my critical open database stuff/ }),
    )

    expect(
      await screen.findByText('Critical open tasks assigned to you matching "database"'),
    ).toBeInTheDocument()
    await waitFor(() => {
      const list = calls.filter((r) => new URL(r.url).pathname === '/api/v1/incidents').at(-1)
      const params = new URL(list?.url ?? 'http://x').searchParams
      expect(params.getAll('status')).toEqual(['open'])
      expect(params.getAll('priority')).toEqual(['critical'])
      expect(params.getAll('assignee')).toEqual(['me'])
      expect(params.get('q')).toBe('database')
    })
  })
})
