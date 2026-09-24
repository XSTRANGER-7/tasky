/** AI suggestions (spec 10): status, triage, summaries/postmortems, NL search, decisions. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap } from './client'
import { keys } from './queries'
import type { components } from './schema'

export type AiStatus = components['schemas']['AiStatus']
export type TriageSuggestion = components['schemas']['TriageSuggestion']
export type SummarySuggestion = components['schemas']['SummarySuggestion']
export type SearchSuggestion = components['schemas']['SearchSuggestion']
export type SearchFilters = components['schemas']['SearchOutput']

export function useAiStatus() {
  return useQuery({
    queryKey: ['ai', 'status'],
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/ai/status', { signal })),
    staleTime: 10 * 60_000,
  })
}

/** True only when the server says AI is on; panels are simply absent otherwise. */
export function useAiEnabled(): boolean {
  return useAiStatus().data?.enabled ?? false
}

export function triage(
  body: { title: string; description: string },
  signal?: AbortSignal,
): Promise<TriageSuggestion> {
  return unwrap(api.POST('/api/v1/ai/triage', { body, ...(signal ? { signal } : {}) }))
}

export function nlSearch(query: string): Promise<SearchSuggestion> {
  return unwrap(api.POST('/api/v1/ai/search', { body: { query } }))
}

export function useSummary(ident: string) {
  return useMutation({
    mutationFn: (kind: 'summary' | 'postmortem') =>
      unwrap(
        api.POST('/api/v1/incidents/{ident}/ai/summary', {
          params: { path: { ident } },
          body: { kind },
        }),
      ),
  })
}

export function decide(
  id: string,
  decision: 'accept' | 'reject',
  body?: { incident?: string; markdown?: string; apply?: ('priority' | 'category' | 'assignee')[] },
) {
  return decision === 'accept'
    ? unwrap(
        api.POST('/api/v1/ai/suggestions/{suggestion_id}/accept', {
          params: { path: { suggestion_id: id } },
          body: body ?? {},
        }),
      )
    : unwrap(
        api.POST('/api/v1/ai/suggestions/{suggestion_id}/reject', {
          params: { path: { suggestion_id: id } },
        }),
      )
}

export function usePostPostmortem(ident: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, markdown }: { id: string; markdown: string }) =>
      decide(id, 'accept', { markdown }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.comments(ident) })
      void qc.invalidateQueries({ queryKey: keys.events(ident) })
      void qc.invalidateQueries({ queryKey: keys.detail(ident) })
    },
  })
}

/** Filters from NL search -> the list page's URL (the same params a human would click). */
export function filtersToSearch(f: SearchFilters): string {
  const p = new URLSearchParams()
  f.status?.forEach((s) => {
    p.append('status', s)
  })
  f.priority?.forEach((s) => {
    p.append('priority', s)
  })
  if (f.assignee) p.append('assignee', f.assignee) // me | none | user id, as the list expects
  if (f.sla) p.set('sla', f.sla)
  if (f.q) p.set('q', f.q)
  if (f.sort) p.set('sort', f.sort)
  return p.toString()
}
