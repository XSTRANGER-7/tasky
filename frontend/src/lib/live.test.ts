import { QueryClient } from '@tanstack/react-query'

import { getAccessToken, setSession } from '@/api/client'
import { apiError, demoUser, json, mockApi, sse, tokenOut } from '@/test/mockApi'

import {
  backoffMs,
  handleLiveMessage,
  resetLiveState,
  runLiveStream,
  type LiveMessage,
} from './live'

afterEach(() => {
  setSession(null, null)
  resetLiveState()
})

const STREAM = 'GET /api/v1/events/stream'

/** Run the stream until `done` resolves, then stop it. */
async function run(
  until: (messages: LiveMessage[]) => boolean,
  sleep: (ms: number) => Promise<void> = () => Promise.resolve(),
  onReconnect?: () => void,
) {
  const messages: LiveMessage[] = []
  const controller = new AbortController()
  const finished = runLiveStream(
    {
      onMessage: (m) => {
        messages.push(m)
        if (until(messages)) controller.abort()
      },
      ...(onReconnect ? { onReconnect } : {}),
    },
    controller.signal,
    sleep,
  )
  await vi.waitFor(() => {
    expect(until(messages)).toBe(true)
  })
  controller.abort()
  await finished
  return messages
}

describe('live stream', () => {
  it('sends the access token and delivers parsed events', async () => {
    setSession('tok-1', demoUser)
    const { calls } = mockApi({
      [STREAM]: () =>
        sse(
          { event: 'incident.updated', data: { type: 'incident.updated', incident: 'INC-4' } },
          { event: 'notification.new', data: { type: 'notification.new', incident: 'INC-4' } },
        ),
    })

    const messages = await run((m) => m.length === 2)

    expect(messages.map((m) => m.type)).toEqual(['incident.updated', 'notification.new'])
    expect(calls[0]?.headers.get('authorization')).toBe('Bearer tok-1')
  })

  it('refreshes the session on 401 and reconnects with the new token', async () => {
    setSession('expired', demoUser)
    let attempt = 0
    const { calls } = mockApi({
      [STREAM]: () => {
        attempt += 1
        return attempt === 1
          ? apiError(401, 'token_expired', 'expired')
          : sse({ event: 'incident.created', data: { type: 'incident.created' } })
      },
      'POST /api/v1/auth/refresh': () => json(tokenOut('fresh')),
    })

    await run((m) => m.length === 1)

    const streams = calls.filter((r) => new URL(r.url).pathname === '/api/v1/events/stream')
    expect(streams.map((r) => r.headers.get('authorization'))).toEqual([
      'Bearer expired',
      'Bearer fresh',
    ])
    expect(getAccessToken()).toBe('fresh')
  })

  it('reconnects on a reauth event before the token lapses', async () => {
    setSession('tok-1', demoUser)
    let attempt = 0
    mockApi({
      [STREAM]: () => {
        attempt += 1
        return attempt === 1
          ? sse({ event: 'reauth', data: {} })
          : sse({ event: 'incident.updated', data: { type: 'incident.updated' } })
      },
      'POST /api/v1/auth/refresh': () => json(tokenOut('tok-2')),
    })

    const reconnected = vi.fn()
    await run((m) => m.length === 1, undefined, reconnected)
    expect(getAccessToken()).toBe('tok-2')
    expect(reconnected).toHaveBeenCalledOnce() // so the app refetches what it missed
  })

  it('backs off after failures and stops when the session is gone', async () => {
    setSession('tok-1', demoUser)
    const waits: number[] = []
    let attempt = 0
    mockApi({
      [STREAM]: () => {
        attempt += 1
        if (attempt === 3) setSession(null, null) // e.g. signed out in another tab
        return apiError(503, 'unavailable', 'down')
      },
    })

    await runLiveStream({ onMessage: () => undefined }, new AbortController().signal, (ms) => {
      waits.push(ms)
      return Promise.resolve()
    })

    expect(waits).toEqual([1000, 2000, 4000])
  })

  it('caps the backoff at 30 seconds', () => {
    expect([1, 2, 3, 4, 5, 6, 10].map(backoffMs)).toEqual([
      1000, 2000, 4000, 8000, 16000, 30000, 30000,
    ])
  })
})

describe('handleLiveMessage', () => {
  it('routes incident events and notifications', () => {
    const qc = new QueryClient()
    const invalidate = vi.spyOn(qc, 'invalidateQueries')
    const refresh = vi.fn()
    const notify = vi.fn()

    handleLiveMessage(qc, { type: 'incident.updated', incident: 'INC-1' }, refresh, notify)
    expect(refresh).toHaveBeenCalledOnce()
    expect(notify).not.toHaveBeenCalled()

    handleLiveMessage(qc, { type: 'notification.new', incident: 'INC-1' }, refresh, notify)
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['notifications'] })
    expect(notify).toHaveBeenCalledOnce()

    handleLiveMessage(qc, { type: 'something.else' }, refresh, notify)
    expect(refresh).toHaveBeenCalledOnce()
  })
})
