/**
 * Live updates over Server-Sent Events (spec 9.9).
 *
 * `fetch-event-source` rather than `EventSource` because the stream needs an
 * `Authorization` header (the access token is in memory only, never in a cookie or URL).
 *
 *  - 401 on connect, or a `reauth` event when the token expires: refresh the
 *    session once and reconnect with the new token.
 *  - Network drops: reconnect with capped exponential backoff; the connection state is
 *    exposed so the shell can show an "offline" banner.
 *  - `incident.*` events invalidate incident lists, details and the dashboard, debounced
 *    so a burst of changes costs one refetch.
 *  - `notification.new` is only ever sent to its recipient; it refreshes the bell.
 */
import { fetchEventSource, type EventSourceMessage } from '@microsoft/fetch-event-source'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useSyncExternalStore } from 'react'

import { apiUrl, getAccessToken, refreshSession } from '@/api/client'

export type LiveState = 'connecting' | 'open' | 'offline'

export interface LiveMessage {
  type: string
  incident?: string
  user?: string
}

// ---------------------------------------------------------------- tiny store

interface Snapshot {
  state: LiveState
  /** Bumped on every notification.new so the bell can play its swing. */
  notificationPulse: number
}

let snapshot: Snapshot = { state: 'connecting', notificationPulse: 0 }
const subscribers = new Set<() => void>()

function set(patch: Partial<Snapshot>): void {
  snapshot = { ...snapshot, ...patch }
  subscribers.forEach((s) => {
    s()
  })
}

function subscribe(cb: () => void): () => void {
  subscribers.add(cb)
  return () => subscribers.delete(cb)
}

export function useLiveState(): Snapshot {
  return useSyncExternalStore(subscribe, () => snapshot)
}

/** Exposed for tests. */
export function resetLiveState(): void {
  snapshot = { state: 'connecting', notificationPulse: 0 }
}

// ---------------------------------------------------------------- connection

const STREAM_URL = import.meta.env.VITE_STREAM_URL ?? apiUrl('/api/v1/events/stream')

class Unauthorized extends Error {}
class Reauth extends Error {}

// A function, not a property read: TS narrows `signal.aborted` to false inside the loop,
// but it can flip while we await.
const isAborted = (signal: AbortSignal): boolean => signal.aborted

export function backoffMs(attempt: number): number {
  return Math.min(30_000, 1_000 * 2 ** Math.max(0, attempt - 1))
}

export interface LiveHandlers {
  onMessage: (message: LiveMessage) => void
  /** Called when a dropped stream comes back: anything sent meanwhile was missed. */
  onReconnect?: () => void
}

/** Run the stream until `signal` aborts. Resolves only on abort. */
export async function runLiveStream(
  { onMessage, onReconnect }: LiveHandlers,
  signal: AbortSignal,
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms)),
): Promise<void> {
  let failures = 0
  let connectedBefore = false
  while (!signal.aborted) {
    const token = getAccessToken()
    if (!token) {
      // Signed out (or the refresh cookie is gone): nothing to stream.
      set({ state: 'offline' })
      return
    }
    const attempt = new AbortController()
    const abort = () => {
      attempt.abort()
    }
    signal.addEventListener('abort', abort, { once: true })
    try {
      await fetchEventSource(STREAM_URL, {
        headers: { Authorization: `Bearer ${token}` },
        signal: attempt.signal,
        openWhenHidden: true, // a backgrounded tab still gets its notifications
        onopen: (res) => {
          if (res.status === 401) throw new Unauthorized()
          const type = res.headers.get('content-type') ?? ''
          if (!res.ok || !type.startsWith('text/event-stream')) {
            throw new Error(`stream failed (HTTP ${res.status})`)
          }
          failures = 0
          if (connectedBefore) onReconnect?.()
          connectedBefore = true
          set({ state: 'open' })
          return Promise.resolve()
        },
        onmessage: (msg: EventSourceMessage) => {
          if (msg.event === 'reauth') throw new Reauth()
          if (!msg.data || msg.event === 'ready' || msg.event === 'ping') return
          try {
            onMessage(JSON.parse(msg.data) as LiveMessage)
          } catch {
            // A malformed frame must not tear down the stream.
          }
        },
        onclose: () => {
          throw new Error('stream closed by server')
        },
        onerror: (err: unknown) => {
          throw err // we own the retry loop (it needs a fresh token each time)
        },
      })
    } catch (err) {
      if (isAborted(signal)) break
      if (err instanceof Unauthorized || err instanceof Reauth) {
        const refreshed = await refreshSession()
        if (refreshed) continue
        if (!getAccessToken()) {
          set({ state: 'offline' })
          return // the session is over; the shell is about to unmount
        }
        // Refresh hit a network error: fall through to the backoff below.
      }
      failures += 1
      set({ state: failures > 1 ? 'offline' : 'connecting' })
      await sleep(backoffMs(failures))
    } finally {
      signal.removeEventListener('abort', abort)
    }
  }
}

// ---------------------------------------------------------------- React hook

function debounce(fn: () => void, ms: number) {
  let id: ReturnType<typeof setTimeout> | undefined
  const run = () => {
    clearTimeout(id)
    id = setTimeout(fn, ms)
  }
  run.cancel = () => {
    clearTimeout(id)
  }
  return run
}

export function handleLiveMessage(
  qc: QueryClient,
  message: LiveMessage,
  refreshIncidents: () => void,
  onNotification: (message: LiveMessage) => void,
): void {
  if (message.type.startsWith('incident.')) {
    refreshIncidents()
  } else if (message.type === 'notification.new') {
    void qc.invalidateQueries({ queryKey: ['notifications'] })
    set({ notificationPulse: snapshot.notificationPulse + 1 })
    onNotification(message)
  }
}

/** Keep one stream open for the signed-in user; mount once, in the app shell. */
export function useLiveEvents(
  userId: string | undefined,
  onNotification: (m: LiveMessage) => void,
): void {
  const qc = useQueryClient()
  const notify = useRef(onNotification)
  notify.current = onNotification
  useEffect(() => {
    if (!userId) return
    const controller = new AbortController()
    const refreshIncidents = debounce(() => {
      void qc.invalidateQueries({ queryKey: ['incidents'] })
      void qc.invalidateQueries({ queryKey: ['dashboard'] })
    }, 400)
    set({ state: 'connecting' })
    void runLiveStream(
      {
        onMessage: (m) => {
          handleLiveMessage(qc, m, refreshIncidents, (n) => {
            notify.current(n)
          })
        },
        onReconnect: () => {
          refreshIncidents()
          void qc.invalidateQueries({ queryKey: ['notifications'] })
        },
      },
      controller.signal,
    )
    return () => {
      controller.abort()
      refreshIncidents.cancel()
    }
  }, [userId, qc])
}
