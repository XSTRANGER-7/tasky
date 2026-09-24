/**
 * Tiny fetch router for tests: `mockApi({ 'POST /api/v1/auth/login': () => json(...) })`.
 * Handles both call styles in the app: fetch(Request) (openapi-fetch) and fetch(url, init).
 */
import { vi } from 'vitest'

import { getCurrentUser } from '@/api/client'

export const TEST_TEAM_ID = '99999999-9999-4999-8999-999999999999'

export type Handler = (req: Request) => Response | Promise<Response>

export function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', 'x-request-id': 'req_TEST', ...headers },
  })
}

export function apiError(status: number, code: string, message: string, details = {}): Response {
  return json({ error: { code, message, details, request_id: 'req_ERR' } }, status)
}

/** An SSE response that sends `frames` and then stays open, like the real stream. */
export function sse(...frames: { event: string; data: unknown }[]): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const f of [{ event: 'ready', data: {} }, ...frames]) {
        controller.enqueue(encoder.encode(`event: ${f.event}\ndata: ${JSON.stringify(f.data)}\n\n`))
      }
    },
  })
  return new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } })
}

/** An open SSE stream the test pushes frames into whenever it likes. */
export function sseChannel() {
  const encoder = new TextEncoder()
  let push: ((chunk: string) => void) | null = null
  const response = () =>
    new Response(
      new ReadableStream<Uint8Array>({
        start(controller) {
          push = (chunk) => {
            controller.enqueue(encoder.encode(chunk))
          }
          push('event: ready\ndata: {}\n\n')
        },
      }),
      { status: 200, headers: { 'content-type': 'text/event-stream' } },
    )
  const send = (event: string, data: unknown) => {
    if (!push) throw new Error('stream not connected yet')
    push(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
  }
  return { response, send, connected: () => push !== null }
}

/** Endpoints every signed-in page touches; tests override them when they care. */
const DEFAULTS: Record<string, Handler> = {
  'GET /api/v1/events/stream': () => sse(),
  'GET /api/v1/notifications': () => json({ items: [], unread_count: 0 }),
  // Production-like by default: no demo accounts, self-registration open, no Google.
  'GET /api/v1/auth/config': () =>
    json({ allow_self_register: true, demo_mode: false, google_enabled: false }),
  // Like the backend fixtures: the signed-in user is in one team. Test users carry a `role`
  // field purely to say which role they hold in it (accounts have no global role).
  'GET /api/v1/teams/mine': () => json({ teams: [testTeam()], requests: [] }),
  'GET /api/v1/teams/{team}/join-requests': () => json([]),
}

export function testTeam(overrides: Record<string, unknown> = {}) {
  const role = (getCurrentUser() as { role?: string } | null)?.role ?? 'member'
  return {
    id: TEST_TEAM_ID,
    name: 'Test Team',
    slug: 'test-team',
    description: '',
    created_at: '2026-09-22T09:55:43Z',
    member_count: 4,
    my_role: role,
    pending_request_id: null,
    ...overrides,
  }
}

export function mockApi(routes: Record<string, Handler>) {
  const calls: Request[] = []
  const spy = vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      // Duck-typed: clones are native Requests, not the test-setup subclass.
      const isRequest = typeof input === 'object' && 'url' in input && 'method' in input
      const req = isRequest ? input : new Request(new URL(String(input), 'http://x'), init)
      calls.push(req.clone())
      const key = `${req.method} ${new URL(req.url).pathname}`
      const handler = routes[key] ?? DEFAULTS[key] ?? DEFAULTS[templated(key)]
      if (!handler) return apiError(404, 'not_found', `No mock for ${key}`)
      return handler(req)
    })
  return { spy, calls, count: (key: string) => calls.filter((r) => matches(r, key)).length }
}

/** `GET /api/v1/teams/<uuid>/join-requests` -> `GET /api/v1/teams/{team}/join-requests`. */
function templated(key: string): string {
  return key.replace(/\/teams\/[0-9a-f-]{36}\//, '/teams/{team}/')
}

function matches(req: Request, key: string): boolean {
  return `${req.method} ${new URL(req.url).pathname}` === key
}

export const demoUser = {
  id: '4ea7f71a-bd93-4894-98ee-41e81a4a48c9',
  name: 'Ada Admin',
  email: 'admin@demo.io',
  role: 'admin' as const,
  avatar_color: '#4DD0E1',
  is_active: true,
  notify_email: true,
  created_at: '2026-09-22T09:55:43Z',
  onboarded: true,
}

export function tokenOut(token = 'access-1', user = demoUser) {
  return { access_token: token, token_type: 'bearer', expires_in: 900, user }
}
