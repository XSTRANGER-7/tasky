/**
 * Typed API client (openapi-fetch over types generated from the backend's OpenAPI).
 *
 * Auth model:
 *  - The access token lives only in memory (never localStorage), so XSS cannot lift a
 *    long-lived credential.
 *  - The refresh token is an HttpOnly cookie scoped to /api/v1/auth; JS never sees it.
 *  - On a 401 the client refreshes once (single-flight, shared by concurrent requests)
 *    and replays the original request. If refresh fails the session is over.
 *
 * Team model: every request carries `X-Team-Id` for the active team (set by the
 * TeamProvider), so the server scopes incidents, people and the dashboard to it.
 */
import createClient from 'openapi-fetch'

import { API_URL } from '@/lib/config'

import type { components, paths } from './schema'

export type User = components['schemas']['UserOut']
export type UserPublic = components['schemas']['UserPublic']
/** Someone in the active team, with their role in it (the team directory). */
export type TeamPerson = components['schemas']['TeamPerson']
export type Role = TeamPerson['role']
export type TokenOut = components['schemas']['TokenOut']
export type Incident = components['schemas']['IncidentOut']
export type IncidentCreate = components['schemas']['IncidentCreate']
export type IncidentUpdate = components['schemas']['IncidentUpdate']
export type Comment = components['schemas']['CommentOut']
export type IncidentEvent = components['schemas']['EventOut']
export type DashboardSummary = components['schemas']['DashboardSummary']
export type ActivityItem = components['schemas']['ActivityItem']
export type Status = Incident['status']
export type Priority = Incident['priority']
export type Team = components['schemas']['TeamOut']
export type TeamRole = NonNullable<Team['my_role']>
export type TeamMember = components['schemas']['MemberOut']
export type JoinRequest = components['schemas']['JoinRequestOut']
export type AuthConfig = components['schemas']['AuthConfig']

/**
 * Absolute prefix for the generated paths (which already include `/api/v1`). Resolved
 * against the page origin so `VITE_API_URL=/api/v1` (same origin via the dev proxy or
 * Vercel rewrite) and a full URL both work, and `new Request()` always gets an
 * absolute URL.
 */
const BASE_URL = new URL(API_URL, window.location.origin).href.replace(/\/api\/v1\/?$/, '')

/** Absolute URL for an API path such as `/api/v1/events/stream`. */
export function apiUrl(path: string): string {
  return `${BASE_URL}${path}`
}

export interface ErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown>; request_id?: string }
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string | null,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'ApiError'
  }

  /**
   * Build from a failed response. Pass `body` when the caller already parsed it
   * (openapi-fetch consumes the body to fill `error`, so it cannot be read again).
   */
  static fromResponse(res: Response, body?: unknown): ApiError {
    const requestId = res.headers.get('x-request-id')
    const envelope = (body ?? {}) as Partial<ErrorBody>
    if (envelope.error && typeof envelope.error.code === 'string') {
      return new ApiError(
        res.status,
        envelope.error.code,
        envelope.error.message,
        envelope.error.request_id ?? requestId,
        envelope.error.details ?? {},
      )
    }
    return new ApiError(res.status, 'http_error', `Request failed (HTTP ${res.status})`, requestId)
  }
}

// ---------------------------------------------------------------- session state

type Listener = (token: string | null, user: User | null) => void

let accessToken: string | null = null
let currentUser: User | null = null
let refreshing: Promise<TokenOut | null> | null = null
const listeners = new Set<Listener>()

export function setSession(token: string | null, user: User | null): void {
  accessToken = token
  currentUser = user
  listeners.forEach((l) => {
    l(token, user)
  })
}

export function onSessionChange(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function getAccessToken(): string | null {
  return accessToken
}

export function getCurrentUser(): User | null {
  return currentUser
}

// ---------------------------------------------------------------- active team

const TEAM_STORAGE_KEY = 'incident-desk.team'
let activeTeamId: string | null = readStoredTeam()

function readStoredTeam(): string | null {
  try {
    return window.localStorage.getItem(TEAM_STORAGE_KEY)
  } catch {
    return null
  }
}

/** The team every request acts in (sent as `X-Team-Id`); remembered per browser. */
export function setActiveTeam(teamId: string | null): void {
  activeTeamId = teamId
  try {
    if (teamId) window.localStorage.setItem(TEAM_STORAGE_KEY, teamId)
    else window.localStorage.removeItem(TEAM_STORAGE_KEY)
  } catch {
    // storage blocked (private mode): the choice just is not remembered
  }
}

export function getActiveTeam(): string | null {
  return activeTeamId
}

/**
 * Exchange the refresh cookie for a new access token. Concurrent callers share one
 * request: two parallel refreshes would rotate the token twice, and the second would
 * look like token reuse to the server and end every session.
 */
export function refreshSession(): Promise<TokenOut | null> {
  refreshing ??= (async () => {
    try {
      const res = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
        method: 'POST',
        credentials: 'same-origin',
      })
      if (!res.ok) {
        setSession(null, null)
        return null
      }
      const body = (await res.json()) as TokenOut
      setSession(body.access_token, body.user)
      return body
    } catch {
      return null // network error: keep whatever state we had
    } finally {
      refreshing = null
    }
  })()
  return refreshing
}

const NO_REFRESH = ['/api/v1/auth/login', '/api/v1/auth/refresh', '/api/v1/auth/logout']

async function authFetch(request: Request): Promise<Response> {
  const replay = request.clone() // bodies are single-use; keep a copy for the retry
  const send = (req: Request) => {
    if (accessToken) req.headers.set('Authorization', `Bearer ${accessToken}`)
    if (activeTeamId && !req.headers.has('X-Team-Id')) req.headers.set('X-Team-Id', activeTeamId)
    return fetch(req)
  }

  const res = await send(request)
  const path = new URL(request.url, window.location.origin).pathname
  if (res.status !== 401 || NO_REFRESH.includes(path)) return res

  const refreshed = await refreshSession()
  return refreshed ? send(replay) : res
}

export const api = createClient<paths>({
  baseUrl: BASE_URL,
  credentials: 'same-origin',
  fetch: authFetch,
})

/** Unwrap an openapi-fetch result: return data or throw a typed ApiError. */
export async function unwrap<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await promise
  if (!response.ok) throw ApiError.fromResponse(response, error)
  return data as T
}
