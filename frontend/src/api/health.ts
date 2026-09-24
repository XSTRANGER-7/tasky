import { API_URL } from '@/lib/config'

export interface HealthPayload {
  status: 'ok' | 'degraded'
  db: 'ok' | 'unreachable'
  version: string
  git_sha: string
  env: string
}

export type HealthResult =
  | { state: 'ok' | 'degraded'; payload: HealthPayload; requestId: string | null }
  | { state: 'unreachable'; error: string; requestId: string | null }

function isHealthPayload(value: unknown): value is HealthPayload {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  return (
    (v.status === 'ok' || v.status === 'degraded') &&
    (v.db === 'ok' || v.db === 'unreachable') &&
    typeof v.version === 'string' &&
    typeof v.git_sha === 'string' &&
    typeof v.env === 'string'
  )
}

/**
 * Probe the API. A 503 still carries a health body (API up, database down), so it is
 * reported as `degraded`; anything else that is not a valid body is `unreachable`.
 */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthResult> {
  let res: Response
  try {
    res = await fetch(`${API_URL}/health`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
      ...(signal ? { signal } : {}),
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    return { state: 'unreachable', error: 'Network error - is the API running?', requestId: null }
  }

  const requestId = res.headers.get('x-request-id')
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    // Non-JSON response, e.g. an HTML error page from a proxy.
  }

  if ((res.ok || res.status === 503) && isHealthPayload(body)) {
    return { state: body.status, payload: body, requestId }
  }
  return { state: 'unreachable', error: `Unexpected response (HTTP ${res.status})`, requestId }
}
