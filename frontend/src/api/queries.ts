/**
 * Server state via TanStack Query. Keys are centralised so every mutation invalidates
 * exactly what it changed; status/priority/assignee changes are optimistic with rollback.
 */
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'

import {
  api,
  unwrap,
  type Comment,
  type Incident,
  type IncidentCreate,
  type IncidentUpdate,
  type Priority,
  type Status,
  type TeamPerson,
  type UserPublic,
} from './client'
import type { paths } from './schema'

export interface IncidentFilters {
  status?: Status[]
  priority?: Priority[]
  assignee?: string[]
  reporter?: string
  q?: string
  sla?: 'breached' | 'at_risk' | 'on_track'
  sort?: string
  deleted?: boolean
  watching?: boolean
}

export const keys = {
  incidents: ['incidents'] as const,
  list: (f: IncidentFilters) => ['incidents', 'list', f] as const,
  detail: (id: string) => ['incidents', 'detail', id] as const,
  comments: (id: string) => ['incidents', 'comments', id] as const,
  events: (id: string) => ['incidents', 'events', id] as const,
  users: ['users'] as const,
  dashboard: ['dashboard'] as const,
}

type ListQuery = NonNullable<paths['/api/v1/incidents']['get']['parameters']['query']>

/** Query params for GET /incidents, with empty values omitted entirely. */
function clean(f: IncidentFilters): ListQuery {
  const raw = {
    status: f.status?.length ? f.status : undefined,
    priority: f.priority?.length ? f.priority : undefined,
    assignee: f.assignee?.length ? f.assignee : undefined,
    reporter: f.reporter || undefined,
    q: f.q?.trim() || undefined,
    sla: f.sla,
    sort: f.sort || undefined,
    deleted: f.deleted || undefined,
    watching: f.watching || undefined,
  }
  return Object.fromEntries(Object.entries(raw).filter(([, v]) => v !== undefined))
}

// ---------------------------------------------------------------- reads

/** Public sign-in page options: demo accounts, self-registration. */
export function useAuthConfig() {
  return useQuery({
    queryKey: ['auth', 'config'],
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/auth/config', { signal })),
    staleTime: 10 * 60_000,
  })
}

export function useIncidents(filters: IncidentFilters, pageSize = 25) {
  return useInfiniteQuery({
    queryKey: keys.list(filters),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET('/api/v1/incidents', {
          params: {
            query: {
              ...clean(filters),
              limit: pageSize,
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
          signal,
        }),
      ),
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  })
}

export function useIncident(ident: string) {
  return useQuery({
    queryKey: keys.detail(ident),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/incidents/{ident}', { params: { path: { ident } }, signal })),
  })
}

export function useComments(ident: string) {
  return useQuery({
    queryKey: keys.comments(ident),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/incidents/{ident}/comments', { params: { path: { ident } }, signal }),
      ),
  })
}

export function useEvents(ident: string) {
  return useQuery({
    queryKey: keys.events(ident),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/incidents/{ident}/events', { params: { path: { ident } }, signal })),
  })
}

export function useUsers() {
  return useQuery({
    queryKey: keys.users,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/users', { signal })) as Promise<TeamPerson[]>,
    staleTime: 5 * 60_000,
  })
}

export function useDashboard() {
  return useQuery({
    queryKey: keys.dashboard,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/dashboard/summary', { signal })),
    refetchInterval: 30_000,
  })
}

// ---------------------------------------------------------------- writes

/** After any incident write: refresh lists, this incident's timeline and the dashboard. */
function afterWrite(qc: QueryClient, incident: Incident) {
  qc.setQueryData(keys.detail(incident.key), incident)
  void qc.invalidateQueries({ queryKey: ['incidents', 'list'] })
  void qc.invalidateQueries({ queryKey: keys.events(incident.key) })
  void qc.invalidateQueries({ queryKey: keys.dashboard })
}

export function useCreateIncident() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ body, idempotencyKey }: { body: IncidentCreate; idempotencyKey: string }) =>
      unwrap(
        api.POST('/api/v1/incidents', {
          body,
          params: { header: { 'Idempotency-Key': idempotencyKey } },
        }),
      ),
    onSuccess: (incident) => {
      afterWrite(qc, incident)
    },
  })
}

/** Optimistically patch the cached detail; roll back if the server says no. */
function useOptimisticIncident<V>(
  ident: string,
  mutate: (vars: V) => Promise<Incident>,
  apply: (incident: Incident, vars: V) => Incident,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: mutate,
    onMutate: async (vars) => {
      await qc.cancelQueries({ queryKey: keys.detail(ident) })
      const previous = qc.getQueryData<Incident>(keys.detail(ident))
      if (previous) qc.setQueryData(keys.detail(ident), apply(previous, vars))
      return { previous }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(keys.detail(ident), ctx.previous)
    },
    onSuccess: (incident) => {
      afterWrite(qc, incident)
    },
  })
}

export function useTransition(ident: string) {
  return useOptimisticIncident<{ status: Status; note?: string }>(
    ident,
    (body) =>
      unwrap(
        api.POST('/api/v1/incidents/{ident}/transition', { params: { path: { ident } }, body }),
      ),
    (inc, { status }) => ({ ...inc, status, allowed_transitions: [] }),
  )
}

export function useAssign(ident: string, users: UserPublic[] | undefined) {
  return useOptimisticIncident<{ assignee_id: string | null }>(
    ident,
    (body) =>
      unwrap(api.POST('/api/v1/incidents/{ident}/assign', { params: { path: { ident } }, body })),
    (inc, { assignee_id }) => {
      const person = users?.find((u) => u.id === assignee_id) ?? null
      return { ...inc, assignee: person, assignees: person ? [person] : [] }
    },
  )
}

/** Everyone assigned, in order (the first leads). Newly assigned people are emailed. */
export function useSetAssignees(ident: string, users: UserPublic[] | undefined) {
  return useOptimisticIncident<{ user_ids: string[] }>(
    ident,
    (body) =>
      unwrap(api.PUT('/api/v1/incidents/{ident}/assignees', { params: { path: { ident } }, body })),
    (inc, { user_ids }) => {
      const people = user_ids
        .map((id) => users?.find((u) => u.id === id))
        .filter((u): u is NonNullable<typeof u> => Boolean(u))
      return { ...inc, assignee: people[0] ?? null, assignees: people }
    },
  )
}

/**
 * Everyone assigned to a task, lead first. An API from before several assignees existed
 * (or an old cached response) has no `assignees` field: fall back to the single lead
 * rather than crash the page.
 */
export function assigneesOf(
  incident: Pick<Incident, 'assignee'> & { assignees?: UserPublic[] | null },
): UserPublic[] {
  if (incident.assignees && incident.assignees.length > 0) return incident.assignees
  return incident.assignee ? [incident.assignee] : []
}

export function useUpdateIncident(ident: string) {
  return useOptimisticIncident<IncidentUpdate>(
    ident,
    (body) => unwrap(api.PATCH('/api/v1/incidents/{ident}', { params: { path: { ident } }, body })),
    (inc, body) => ({ ...inc, ...(body as Partial<Incident>) }),
  )
}

export function useDeleteIncident(ident: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      unwrap(api.DELETE('/api/v1/incidents/{ident}', { params: { path: { ident } } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.incidents })
      void qc.invalidateQueries({ queryKey: keys.dashboard })
    },
  })
}

export function useRestoreIncident(ident: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      unwrap(api.POST('/api/v1/incidents/{ident}/restore', { params: { path: { ident } } })),
    onSuccess: (incident) => {
      afterWrite(qc, incident)
    },
  })
}

// ---------------------------------------------------------------- comments

function afterComment(qc: QueryClient, ident: string) {
  void qc.invalidateQueries({ queryKey: keys.comments(ident) })
  void qc.invalidateQueries({ queryKey: keys.events(ident) })
  void qc.invalidateQueries({ queryKey: keys.detail(ident) })
  void qc.invalidateQueries({ queryKey: keys.dashboard })
}

export function useAddComment(ident: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { body: string; is_internal: boolean }) =>
      unwrap(api.POST('/api/v1/incidents/{ident}/comments', { params: { path: { ident } }, body })),
    onSuccess: (comment) => {
      qc.setQueryData<Comment[]>(keys.comments(ident), (old) => [...(old ?? []), comment])
      afterComment(qc, ident)
    },
  })
}

export function useEditComment(ident: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: string }) =>
      unwrap(
        api.PATCH('/api/v1/comments/{comment_id}', {
          params: { path: { comment_id: id } },
          body: { body },
        }),
      ),
    onSuccess: () => {
      afterComment(qc, ident)
    },
  })
}

export function useDeleteComment(ident: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE('/api/v1/comments/{comment_id}', { params: { path: { comment_id: id } } })),
    onMutate: (id) => {
      qc.setQueryData<Comment[]>(keys.comments(ident), (old) => old?.filter((c) => c.id !== id))
    },
    onSettled: () => {
      afterComment(qc, ident)
    },
  })
}
