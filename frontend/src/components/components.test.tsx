import { render, screen } from '@testing-library/react'

import { dashboard } from '@/test/fixtures'
import { json, mockApi, tokenOut } from '@/test/mockApi'
import { renderApp } from '@/test/render'
import { setSession } from '@/api/client'
import { describeEvent } from '@/lib/events'
import { formatDuration, timeAgo } from '@/lib/time'

import { SlaTimer } from './incident-ui'
import { Markdown } from './Markdown'

const NOW = Date.parse('2026-09-22T12:00:00Z')
const at = (minutes: number) => new Date(NOW + minutes * 60_000).toISOString()
const sla = (over = {}) => ({
  response_breached: false,
  resolution_breached: false,
  at_risk: false,
  paused: false,
  ...over,
})

describe('SlaTimer', () => {
  it('is neutral when on track', () => {
    render(
      <SlaTimer
        now={NOW}
        incident={{ status: 'open', resolution_due_at: at(300), resolved_at: null, sla: sla() }}
      />,
    )
    const el = screen.getByText('5h')
    expect(el.closest('span')?.className).toContain('text-fg-muted')
  })

  it('turns amber under an hour', () => {
    render(
      <SlaTimer
        now={NOW}
        incident={{ status: 'open', resolution_due_at: at(45), resolved_at: null, sla: sla() }}
      />,
    )
    expect(screen.getByText('45m').closest('span')?.className).toContain('text-priority-medium')
  })

  it('turns red with an icon once breached', () => {
    const { container } = render(
      <SlaTimer
        now={NOW}
        incident={{
          status: 'open',
          resolution_due_at: at(-90),
          resolved_at: null,
          sla: sla({ resolution_breached: true }),
        }}
      />,
    )
    expect(screen.getByText('1h 30m over').closest('span')?.className).toContain('text-danger')
    expect(container.querySelector('svg')).not.toBeNull() // colour is never the only signal
  })

  it('shows the verdict once paused', () => {
    render(
      <SlaTimer
        now={NOW}
        incident={{
          status: 'resolved',
          resolution_due_at: at(60),
          resolved_at: at(0),
          sla: sla({ paused: true }),
        }}
      />,
    )
    expect(screen.getByText('Met')).toBeInTheDocument()
  })
})

describe('Markdown', () => {
  it('renders GitHub-flavoured markdown', async () => {
    render(<Markdown>{'**bold** and `code`\n\n- a\n- b'}</Markdown>)
    // First use loads the lazy renderer chunk; a cold import in jsdom takes a moment.
    expect((await screen.findByText('bold', {}, { timeout: 5000 })).tagName).toBe('STRONG')
    expect(screen.getByText('code').tagName).toBe('CODE')
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('strips raw HTML and javascript: links', async () => {
    const { container } = render(
      <Markdown>
        {'<img src=x onerror="alert(1)"><script>alert(1)</script>[click](javascript:alert(1))'}
      </Markdown>,
    )
    const link = (await screen.findByText('click', { selector: 'a' })).closest('a')
    expect(container.querySelector('script, img')).toBeNull()
    expect(link?.getAttribute('href') ?? '').not.toContain('javascript')
  })

  it('opens links safely in a new tab', async () => {
    render(<Markdown>{'[docs](https://example.com)'}</Markdown>)
    const link = await screen.findByRole('link', { name: 'docs' })
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer noopener')
  })
})

describe('formatters', () => {
  it.each([
    [30 * 60_000, '30m'],
    [3 * 3_600_000 + 20 * 60_000, '3h 20m'],
    [2 * 86_400_000 + 4 * 3_600_000, '2d 4h'],
  ])('formatDuration(%i) = %s', (ms, text) => {
    expect(formatDuration(ms)).toBe(text)
  })

  it('timeAgo', () => {
    expect(timeAgo(at(0), NOW + 10_000)).toBe('just now')
    expect(timeAgo(at(0), NOW + 5 * 60_000)).toBe('5m ago')
    expect(timeAgo(at(0), NOW + 3 * 3_600_000)).toBe('3h ago')
  })

  it('describeEvent', () => {
    expect(
      describeEvent({
        event_type: 'status_changed',
        field: 'status',
        old_value: 'open',
        new_value: 'resolved',
      }),
    ).toBe('moved Open → Resolved')
    expect(
      describeEvent({
        event_type: 'assigned',
        field: 'assignee',
        old_value: { name: 'Max' },
        new_value: { name: 'Mira' },
      }),
    ).toBe('reassigned from Max to Mira')
    expect(
      describeEvent({
        event_type: 'commented',
        field: null,
        old_value: null,
        new_value: { internal: true },
      }),
    ).toBe('added an internal note')
  })
})

describe('dashboard', () => {
  afterEach(() => {
    setSession(null, null)
  })

  it('shows KPIs, charts and activity from the summary', async () => {
    mockApi({
      'POST /api/v1/auth/refresh': () => json(tokenOut()),
      'GET /api/v1/dashboard/summary': () => json(dashboard()),
      'GET /api/v1/health': () =>
        json({ status: 'ok', db: 'ok', version: '1', git_sha: 'x', env: 't' }),
    })
    renderApp('/')

    // The page (and Recharts) is lazy-loaded; the first import in jsdom can be slow.
    expect(await screen.findByText('SLA breached', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText('1 more at risk within the hour')).toBeInTheDocument()
    expect(screen.getByText('Created vs resolved')).toBeInTheDocument()
    expect(screen.getByText('Open work by priority')).toBeInTheDocument()
    expect(screen.getByText('moved Open → In progress')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /SLA breached/ })).toHaveAttribute(
      'href',
      '/tasks?view=breached',
    )
  })
})
