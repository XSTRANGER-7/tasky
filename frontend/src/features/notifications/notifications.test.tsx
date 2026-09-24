import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { setSession } from '@/api/client'
import type { AppNotification, OutboxPage } from '@/api/notifications'
import { resetLiveState } from '@/lib/live'
import { incident, jonas, team } from '@/test/fixtures'
import { demoUser, json, mockApi, sseChannel, tokenOut, type Handler } from '@/test/mockApi'
import { renderApp } from '@/test/render'

afterEach(() => {
  setSession(null, null)
  resetLiveState()
})

function notification(overrides: Partial<AppNotification> = {}): AppNotification {
  return {
    id: 'n-1',
    kind: 'incident_assigned',
    title: 'INC-7 was assigned to you',
    body: 'Checkout API returning 502',
    incident_id: '22222222-2222-4222-8222-222222222222',
    incident_key: 'INC-7',
    actor: jonas,
    read_at: null,
    created_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    ...overrides,
  }
}

const inbox = [
  notification(),
  notification({
    id: 'n-2',
    kind: 'sla_breached',
    title: 'INC-3 breached its SLA',
    body: '',
    incident_key: 'INC-3',
    actor: null,
  }),
  notification({ id: 'n-3', title: 'Old news', read_at: new Date().toISOString() }),
]

function api(extra: Record<string, Handler> = {}, user = demoUser) {
  // Stateful, so a refetch after a mutation sees what the server would.
  let items = inbox.map((n) => ({ ...n }))
  const list = () => json({ items, unread_count: items.filter((n) => !n.read_at).length })
  const read = (id?: string) => {
    items = items.map((n) => (!id || n.id === id ? { ...n, read_at: n.read_at ?? 'now' } : n))
    return new Response(null, { status: 204 })
  }
  return mockApi({
    'POST /api/v1/auth/refresh': () => json(tokenOut('access-1', user)),
    'GET /api/v1/users': () => json(team),
    'GET /api/v1/health': () =>
      json({ status: 'ok', db: 'ok', version: '1', git_sha: 'x', env: 't' }),
    'GET /api/v1/notifications': list,
    'POST /api/v1/notifications/read-all': () => read(),
    'POST /api/v1/notifications/n-1/read': () => read('n-1'),
    'GET /api/v1/notifications/emails': () => json([]),
    ...extra,
  })
}

describe('notification bell', () => {
  it('shows the unread count and lists recent notifications', async () => {
    api()
    renderApp('/notifications')

    const bell = await screen.findByRole('button', { name: 'Notifications, 2 unread' })
    await userEvent.click(bell)

    const panel = await screen.findByRole('dialog', { name: 'Notifications' })
    expect(within(panel).getByText('INC-7 was assigned to you')).toBeInTheDocument()
    expect(within(panel).getByText('INC-3 breached its SLA')).toBeInTheDocument()
    expect(within(panel).getAllByText('Unread')).toHaveLength(2)
  })

  it('marks everything read optimistically', async () => {
    const { count } = api()
    renderApp('/notifications')

    await userEvent.click(await screen.findByRole('button', { name: /Notifications, 2 unread/ }))
    const panel = await screen.findByRole('dialog', { name: 'Notifications' })
    await userEvent.click(within(panel).getByRole('button', { name: /Mark all read/ }))

    expect(await screen.findByRole('button', { name: 'Notifications' })).toBeInTheDocument()
    expect(count('POST /api/v1/notifications/read-all')).toBe(1)
  })

  it('opening a notification marks it read and goes to the task', async () => {
    const { count } = api({
      'GET /api/v1/incidents/INC-7': () => json(incident()),
      'GET /api/v1/incidents/INC-7/comments': () => json([]),
      'GET /api/v1/incidents/INC-7/events': () => json([]),
    })
    renderApp('/notifications')

    await userEvent.click(await screen.findByRole('button', { name: /Notifications, 2 unread/ }))
    const panel = await screen.findByRole('dialog', { name: 'Notifications' })
    await userEvent.click(within(panel).getByText('INC-7 was assigned to you'))

    await waitFor(() => {
      expect(count('POST /api/v1/notifications/n-1/read')).toBe(1)
    })
    expect(
      await screen.findByRole('heading', { name: 'Checkout API returning 502' }),
    ).toBeInTheDocument()
    expect(
      await screen.findByRole('button', { name: 'Notifications, 1 unread' }),
    ).toBeInTheDocument()
  })

  it('a pushed notification refreshes the bell and shows a toast', async () => {
    let unread = 0
    const stream = sseChannel()
    api({
      'GET /api/v1/notifications': () =>
        json(
          unread
            ? { items: [notification({ title: 'Mira mentioned you on INC-7' })], unread_count: 1 }
            : { items: [], unread_count: 0 },
        ),
      'GET /api/v1/events/stream': stream.response,
    })
    renderApp('/status')
    await screen.findByRole('button', { name: 'Notifications' })
    await waitFor(() => {
      expect(stream.connected()).toBe(true)
    })

    unread = 1
    stream.send('notification.new', { type: 'notification.new', incident: 'INC-7' })

    expect(
      await screen.findByRole('button', { name: 'Notifications, 1 unread' }),
    ).toBeInTheDocument()
    // The toast names the notification and offers a way to it.
    expect(await screen.findByText('Mira mentioned you on INC-7')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open' })).toBeInTheDocument()
  })
})

describe('notifications page', () => {
  it('toggles the email preference', async () => {
    const { calls } = api({
      'PATCH /api/v1/users/4ea7f71a-bd93-4894-98ee-41e81a4a48c9': () =>
        json({ ...demoUser, notify_email: false }),
    })
    renderApp('/notifications')

    const toggle = await screen.findByRole('switch', { name: 'Email notifications' })
    expect(toggle).toHaveAttribute('aria-checked', 'true')
    await userEvent.click(toggle)

    await waitFor(() => {
      expect(toggle).toHaveAttribute('aria-checked', 'false')
    })
    const patch = calls.find((r) => r.method === 'PATCH')
    expect(await patch?.json()).toEqual({ notify_email: false })
    expect(screen.getByText(/you will still see everything here/)).toBeInTheDocument()
  })

  it('filters to unread and shows the email log', async () => {
    const { calls } = api({
      'GET /api/v1/notifications/emails': () =>
        json([
          {
            id: 'e-1',
            kind: 'incident_assigned',
            subject: '[INC-7] Assigned to you: Checkout API returning 502',
            incident_key: 'INC-7',
            status: 'sent',
            attempts: 1,
            created_at: new Date().toISOString(),
            sent_at: new Date().toISOString(),
          },
          {
            id: 'e-2',
            kind: 'sla_breached',
            subject: '[INC-3] SLA breached',
            incident_key: 'INC-3',
            status: 'pending',
            attempts: 2,
            created_at: new Date().toISOString(),
            sent_at: null,
          },
        ]),
    })
    renderApp('/notifications')

    await userEvent.click(await screen.findByRole('button', { name: /^Unread/ }))
    await waitFor(() => {
      expect(calls.some((r) => new URL(r.url).searchParams.get('unread') === 'true')).toBe(true)
    })

    await userEvent.click(screen.getByRole('tab', { name: 'Email log' }))
    const table = await screen.findByRole('table', { name: 'Email log' })
    expect(within(table).getByText('Sent')).toBeInTheDocument()
    expect(within(table).getByText('Retrying (2)')).toBeInTheDocument()
  })
})

function outbox(overrides: Partial<OutboxPage> = {}): OutboxPage {
  const now = new Date().toISOString()
  return {
    counts: { pending: 1, sent: 12, failed: 1 },
    worker: { status: 'ok', last_beat_at: now, seconds_since_beat: 3 },
    items: [
      {
        id: 'o-1',
        kind: 'mentioned',
        subject: '[INC-7] Mira mentioned you',
        incident_key: 'INC-7',
        status: 'failed',
        attempts: 5,
        created_at: now,
        sent_at: null,
        recipient_email: 'jonas@demo.io',
        recipient: jonas,
        last_error: 'smtp: connection refused',
        next_attempt_at: now,
      },
    ],
    ...overrides,
  }
}

describe('admin outbox', () => {
  it('shows counts, worker health and retries a failed email', async () => {
    const { count } = api({
      'GET /api/v1/admin/outbox': () => json(outbox()),
      'POST /api/v1/admin/outbox/o-1/retry': () => new Response(null, { status: 204 }),
    })
    renderApp('/admin/outbox')

    expect(await screen.findByText('Worker: Running')).toBeInTheDocument()
    expect(screen.getByText('smtp: connection refused')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Retry/ }))

    await waitFor(() => {
      expect(count('POST /api/v1/admin/outbox/o-1/retry')).toBe(1)
    })
    expect(await screen.findByText('Queued again for Jonas Weber')).toBeInTheDocument()
  })

  it('warns when the worker is not responding and filters by status', async () => {
    const { calls } = api({
      'GET /api/v1/admin/outbox': () =>
        json(
          outbox({
            worker: { status: 'stale', last_beat_at: null, seconds_since_beat: null },
            items: [],
          }),
        ),
    })
    renderApp('/admin/outbox')

    expect(await screen.findByText('Worker: Not responding')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Failed', pressed: false }))
    await waitFor(() => {
      expect(calls.some((r) => new URL(r.url).searchParams.get('status') === 'failed')).toBe(true)
    })
    expect(await screen.findByText('No failed emails.')).toBeInTheDocument()
  })

  it('is for the team admins only', async () => {
    const { count } = api({}, { ...demoUser, role: 'member' as never })
    renderApp('/admin/outbox')

    expect(await screen.findByRole('heading', { name: 'Team admins only' })).toBeInTheDocument()
    expect(count('GET /api/v1/admin/outbox')).toBe(0)
    expect(screen.queryByRole('link', { name: 'Email outbox' })).not.toBeInTheDocument()
  })
})
