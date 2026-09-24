import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchHealth, type HealthResult } from '@/api/health'

export const HEALTH_POLL_MS = 15_000

export interface HealthState {
  result: HealthResult | null
  checkedAt: Date | null
  checking: boolean
  refresh: () => void
}

/** Polls /health and exposes the latest result. Aborts in-flight requests on unmount. */
export function useHealth(pollMs: number = HEALTH_POLL_MS): HealthState {
  const [result, setResult] = useState<HealthResult | null>(null)
  const [checkedAt, setCheckedAt] = useState<Date | null>(null)
  const [checking, setChecking] = useState(false)
  const controller = useRef<AbortController | null>(null)

  const refresh = useCallback(() => {
    controller.current?.abort()
    const ctrl = new AbortController()
    controller.current = ctrl
    setChecking(true)
    fetchHealth(ctrl.signal)
      .then((r) => {
        setResult(r)
        setCheckedAt(new Date())
      })
      .catch((err: unknown) => {
        if (!(err instanceof DOMException && err.name === 'AbortError')) throw err
      })
      .finally(() => {
        if (controller.current === ctrl) setChecking(false)
      })
  }, [])

  useEffect(() => {
    refresh()
    const id = window.setInterval(refresh, pollMs)
    return () => {
      window.clearInterval(id)
      controller.current?.abort()
    }
  }, [refresh, pollMs])

  return { result, checkedAt, checking, refresh }
}
