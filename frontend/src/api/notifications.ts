/**
 * Notifications, the email log, the admin outbox, watching and the email preference.
 * Unread state is updated optimistically so the bell reacts before the round trip.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, getAccessToken, getCurrentUser, setSession, unwrap, type Incident } from './client'
import { keys as incidentKeys } from './queries'
import type { components } from './schema'

export type AppNotification = components['schemas']['InAppNotificationOut']
export type NotificationList = components['schemas']['NotificationList']
export type NotificationKind = components['schemas']['NotificationKind']
export type EmailLogItem = components['schemas']['EmailLogItem']
export type OutboxRow = components['schemas']['OutboxRow']
export type OutboxPage = components['schemas']['OutboxPage']
export type OutboxStatus = components['schemas']['OutboxStatus']
export type WorkerStatus = components['schemas']['WorkerStatus']

export const notificationKeys = {
  all: ['notifications'] as const,
  list: (unread: boolean) => ['notifications', 'list', { unread }] as const,
  emails: ['notifications', 'emails'] as const,
  outbox: (status: OutboxStatus | null) => ['admin', 'outbox', { status }] as const,
}

export function fetchNotifications(unread = false, signal?: AbortSignal) {
  return unwrap(
    api.GET('/api/v1/notifications', {
      params: { query: { unread, limit: 50 } },
      ...(signal ? { signal } : {}),
    }),
  )
}

export function useNotifications(unread = false) {
  return useQuery({
    queryKey: notificationKeys.list(unread),
    queryFn: ({ signal }) => fetchNotifications(unread, signal),
    // Live updates arrive over SSE; polling is only a safety net for a dropped stream.
    refetchInterval: 120_000,
    placeholderData: keepPreviousData,
  })
}

type ListUpdater = (list: NotificationList) => NotificationList

function useOptimisticNotifications<V>(
  mutate: (vars: V) => Promise<unknown>,
  apply: (vars: V) => ListUpdater,
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: mutate,
    onMutate: async (vars) => {
      await qc.cancelQueries({ queryKey: ['notifications', 'list'] })
      const previous = qc.getQueriesData<NotificationList>({ queryKey: ['notifications', 'list'] })
      const update = apply(vars)
      qc.setQueriesData<NotificationList>({ queryKey: ['notifications', 'list'] }, (old) =>
        old ? update(old) : old,
      )
      return { previous }
    },
    onError: (_err, _vars, ctx) => {
      ctx?.previous.forEach(([key, data]) => {
        qc.setQueryData(key, data)
      })
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ['notifications', 'list'] })
    },
  })
}

export function useMarkRead() {
  return useOptimisticNotifications(
    (id: string) =>
      unwrap(
        api.POST('/api/v1/notifications/{notification_id}/read', {
          params: { path: { notification_id: id } },
        }),
      ),
    (id) => (list) => {
      const target = list.items.find((n) => n.id === id)
      if (!target || target.read_at) return list
      return {
        items: list.items.map((n) =>
          n.id === id ? { ...n, read_at: new Date().toISOString() } : n,
        ),
        unread_count: Math.max(0, list.unread_count - 1),
      }
    },
  )
}

export function useMarkAllRead() {
  return useOptimisticNotifications(
    () => unwrap(api.POST('/api/v1/notifications/read-all')),
    () => (list) => {
      const now = new Date().toISOString()
      return {
        items: list.items.map((n) => ({ ...n, read_at: n.read_at ?? now })),
        unread_count: 0,
      }
    },
  )
}

export function useEmailLog() {
  return useQuery({
    queryKey: notificationKeys.emails,
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/notifications/emails', { params: { query: { limit: 100 } }, signal }),
      ),
  })
}

// ---------------------------------------------------------------- admin outbox

export function useOutbox(status: OutboxStatus | null, enabled = true) {
  return useQuery({
    enabled,
    queryKey: notificationKeys.outbox(status),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/admin/outbox', {
          params: { query: { limit: 100, ...(status ? { status } : {}) } },
          signal,
        }),
      ),
    refetchInterval: 10_000,
    placeholderData: keepPreviousData,
  })
}

export function useRetryOutbox() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST('/api/v1/admin/outbox/{outbox_id}/retry', { params: { path: { outbox_id: id } } }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin', 'outbox'] })
    },
  })
}

// ---------------------------------------------------------------- watching

export function useWatch(ident: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (watch: boolean) =>
      unwrap(
        watch
          ? api.POST('/api/v1/incidents/{ident}/watch', { params: { path: { ident } } })
          : api.DELETE('/api/v1/incidents/{ident}/watch', { params: { path: { ident } } }),
      ),
    onMutate: async (watch) => {
      await qc.cancelQueries({ queryKey: incidentKeys.detail(ident) })
      const previous = qc.getQueryData<Incident>(incidentKeys.detail(ident))
      if (previous) qc.setQueryData(incidentKeys.detail(ident), { ...previous, watching: watch })
      return { previous }
    },
    onError: (_err, _watch, ctx) => {
      if (ctx?.previous) qc.setQueryData(incidentKeys.detail(ident), ctx.previous)
    },
    onSuccess: (incident) => {
      qc.setQueryData(incidentKeys.detail(ident), incident)
      void qc.invalidateQueries({ queryKey: incidentKeys.events(ident) })
    },
  })
}

/** Add a teammate to an incident (they are emailed), or take someone off it. */
export function usePeopleOnIncident(ident: string) {
  const qc = useQueryClient()
  const done = (incident: Incident) => {
    qc.setQueryData(incidentKeys.detail(ident), incident)
    void qc.invalidateQueries({ queryKey: incidentKeys.events(ident) })
  }
  const add = useMutation({
    mutationFn: (userId: string) =>
      unwrap(
        api.POST('/api/v1/incidents/{ident}/watchers', {
          params: { path: { ident } },
          body: { user_id: userId },
        }),
      ),
    onSuccess: done,
  })
  const remove = useMutation({
    mutationFn: (userId: string) =>
      unwrap(
        api.DELETE('/api/v1/incidents/{ident}/watchers/{user_id}', {
          params: { path: { ident, user_id: userId } },
        }),
      ),
    onSuccess: done,
  })
  return { add, remove }
}

// ---------------------------------------------------------------- preferences

export function useUpdateMe() {
  return useMutation({
    mutationFn: (body: { notify_email?: boolean; name?: string }) => {
      const userId = getCurrentUser()?.id
      if (!userId) throw new Error('Not signed in')
      return unwrap(
        api.PATCH('/api/v1/users/{user_id}', { params: { path: { user_id: userId } }, body }),
      )
    },
    onSuccess: (updated) => {
      // Push the new profile through the session so every useAuth() consumer sees it.
      setSession(getAccessToken(), updated)
    },
  })
}
