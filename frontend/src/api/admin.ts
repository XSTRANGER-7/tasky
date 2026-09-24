/** Team-admin reads: the effective runtime settings and the team's own AI usage. There
 * is no platform-wide admin; these answer for the active team only. */
import { useQuery } from '@tanstack/react-query'

import { api, unwrap } from './client'
import type { components } from './schema'

export type AdminSettings = components['schemas']['AdminSettings']

export const adminKeys = {
  settings: ['admin', 'settings'] as const,
}

export function useAdminSettings(enabled = true) {
  return useQuery({
    queryKey: adminKeys.settings,
    enabled,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/admin/settings', { signal })),
    refetchInterval: 30_000,
  })
}

export interface AiFeatureStats {
  total: number
  accepted: number
  rejected: number
  llm: number
  rules: number
  avg_latency_ms: number
  accept_rate: number | null
}

/** Accept rate, engine split and latency per AI feature (spec 10.3: accept rate tracked). */
export function useAiStats(enabled = true) {
  return useQuery({
    queryKey: ['admin', 'ai'],
    enabled,
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/admin/ai', { signal })) as Promise<Record<string, AiFeatureStats>>,
  })
}
