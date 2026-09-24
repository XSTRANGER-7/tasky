/** Teams: my teams and requests, discovery, join requests, members, and decisions. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, unwrap, type TeamRole } from './client'

export const teamKeys = {
  all: ['teams'] as const,
  mine: ['teams', 'mine'] as const,
  discover: (q: string) => ['teams', 'discover', q] as const,
  members: (id: string) => ['teams', 'members', id] as const,
  requests: (id: string) => ['teams', 'requests', id] as const,
  review: ['teams', 'review'] as const,
}

export function useMyTeams(enabled = true) {
  return useQuery({
    queryKey: teamKeys.mine,
    enabled,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/teams/mine', { signal })),
    staleTime: 30_000,
  })
}

export function useDiscoverTeams(q: string, enabled = true) {
  return useQuery({
    queryKey: teamKeys.discover(q),
    enabled,
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/teams/discover', { params: { query: q ? { q } : {} }, signal })),
    placeholderData: (previous) => previous,
  })
}

export function useTeamMembers(teamId: string | null) {
  return useQuery({
    queryKey: teamKeys.members(teamId ?? ''),
    enabled: Boolean(teamId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/teams/{team_id}/members', {
          params: { path: { team_id: teamId ?? '' } },
          signal,
        }),
      ),
  })
}

export function useTeamRequests(teamId: string | null, enabled = true) {
  return useQuery({
    queryKey: teamKeys.requests(teamId ?? ''),
    enabled: enabled && Boolean(teamId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/teams/{team_id}/join-requests', {
          params: { path: { team_id: teamId ?? '' } },
          signal,
        }),
      ),
  })
}

/** Pending requests for every team I own or administer (all teams for platform admins). */
export function useRequestsToReview(enabled = true) {
  return useQuery({
    queryKey: teamKeys.review,
    enabled,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/teams/join-requests/review', { signal })),
    refetchInterval: 60_000,
  })
}

function useTeamMutation<V, R>(fn: (vars: V) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: teamKeys.all })
      void qc.invalidateQueries({ queryKey: ['admin'] })
      void qc.invalidateQueries({ queryKey: ['users'] })
    },
  })
}

export function useCreateTeam() {
  return useTeamMutation((body: { name: string; description?: string }) =>
    unwrap(
      api.POST('/api/v1/teams', { body: { name: body.name, description: body.description ?? '' } }),
    ),
  )
}

export function useUpdateTeam() {
  return useTeamMutation(({ id, ...body }: { id: string; name?: string; description?: string }) =>
    unwrap(api.PATCH('/api/v1/teams/{team_id}', { params: { path: { team_id: id } }, body })),
  )
}

export function useDeleteTeam() {
  return useTeamMutation((id: string) =>
    unwrap(api.DELETE('/api/v1/teams/{team_id}', { params: { path: { team_id: id } } })),
  )
}

export function useRequestToJoin() {
  return useTeamMutation(({ teamId, message }: { teamId: string; message: string }) =>
    unwrap(
      api.POST('/api/v1/teams/{team_id}/join-requests', {
        params: { path: { team_id: teamId } },
        body: { message },
      }),
    ),
  )
}

export function useCancelRequest() {
  return useTeamMutation((requestId: string) =>
    unwrap(
      api.POST('/api/v1/teams/join-requests/{request_id}/cancel', {
        params: { path: { request_id: requestId } },
      }),
    ),
  )
}

export function useDecide() {
  return useTeamMutation(
    ({ requestId, approve, role }: { requestId: string; approve: boolean; role?: TeamRole }) =>
      approve
        ? unwrap(
            api.POST('/api/v1/teams/join-requests/{request_id}/approve', {
              params: { path: { request_id: requestId } },
              body: { role: role ?? 'member' },
            }),
          )
        : unwrap(
            api.POST('/api/v1/teams/join-requests/{request_id}/reject', {
              params: { path: { request_id: requestId } },
            }),
          ),
  )
}

export function useAddMember() {
  return useTeamMutation(
    ({ teamId, email, role }: { teamId: string; email: string; role: TeamRole }) =>
      unwrap(
        api.POST('/api/v1/teams/{team_id}/members', {
          params: { path: { team_id: teamId } },
          body: { email, role },
        }),
      ),
  )
}

export function useChangeMemberRole() {
  return useTeamMutation(
    ({ teamId, userId, role }: { teamId: string; userId: string; role: TeamRole }) =>
      unwrap(
        api.PATCH('/api/v1/teams/{team_id}/members/{user_id}', {
          params: { path: { team_id: teamId, user_id: userId } },
          body: { role },
        }),
      ),
  )
}

/** Remove someone, or leave the team (your own id). */
export function useRemoveMember() {
  return useTeamMutation(({ teamId, userId }: { teamId: string; userId: string }) =>
    unwrap(
      api.DELETE('/api/v1/teams/{team_id}/members/{user_id}', {
        params: { path: { team_id: teamId, user_id: userId } },
      }),
    ),
  )
}

export const TEAM_ROLES: { value: TeamRole; label: string; hint: string }[] = [
  { value: 'admin', label: 'Admin', hint: 'Runs the team: members, requests, settings' },
  { value: 'member', label: 'Member', hint: 'Creates, works on and comments on tasks' },
  { value: 'viewer', label: 'Viewer', hint: 'Read-only' },
]
