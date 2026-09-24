import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { SystemStatus } from './SystemStatus'

const healthy = {
  status: 'ok',
  db: 'ok',
  version: '0.1.0',
  git_sha: '0123456789abcdef',
  env: 'development',
}

const REQUEST_ID = 'req_01J8TEST000000000000000000'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', 'x-request-id': REQUEST_ID },
  })
}

describe('SystemStatus', () => {
  it('shows healthy API and database details', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(healthy))

    render(<SystemStatus />)

    expect(await screen.findByText('All systems operational')).toBeInTheDocument()
    expect(screen.getByText('0.1.0')).toBeInTheDocument()
    expect(screen.getByText('0123456789ab')).toBeInTheDocument()
    expect(screen.getByText(REQUEST_ID)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/health', expect.anything())
  })

  it('reports degraded when the API answers 503', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ ...healthy, status: 'degraded', db: 'unreachable' }, 503),
    )

    render(<SystemStatus />)

    expect(await screen.findByText('API up, database unreachable')).toBeInTheDocument()
    expect(screen.getByText('unreachable')).toBeInTheDocument()
  })

  it('reports unreachable on a network error', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))

    render(<SystemStatus />)

    expect(await screen.findByText('API unreachable')).toBeInTheDocument()
    expect(screen.getByText(/Network error/)).toBeInTheDocument()
  })

  it('reports unreachable when a proxy returns a non-health body', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('<html>Bad gateway</html>', { status: 502 }),
    )

    render(<SystemStatus />)

    expect(await screen.findByText('Unexpected response (HTTP 502)')).toBeInTheDocument()
  })

  it('re-checks on demand', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValue(jsonResponse(healthy))

    render(<SystemStatus />)
    await screen.findByText('API unreachable')

    await userEvent.click(screen.getByRole('button', { name: 'Check again' }))

    await waitFor(() => {
      expect(screen.getByText('All systems operational')).toBeInTheDocument()
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
