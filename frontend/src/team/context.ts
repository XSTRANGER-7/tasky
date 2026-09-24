import { createContext } from 'react'

import type { JoinRequest, Team, TeamRole } from '@/api/client'

/** What the UI may offer in the active team; the server still decides every action. */
export type EffectiveRole = 'admin' | 'member' | 'viewer'

export interface TeamContextValue {
  status: 'loading' | 'ready' | 'error'
  /** Teams I belong to. */
  teams: Team[]
  /** My join requests (any status), newest first. */
  requests: JoinRequest[]
  /** The team the workspace shows. */
  active: Team | null
  /** My role in the active team. */
  role: TeamRole | null
  effectiveRole: EffectiveRole
  /** Members and admins can report and work incidents; viewers only read. */
  canWork: boolean
  /** The team's admins manage its members, requests, email and settings. There is no
   * platform-wide admin: nobody manages a team they are not an admin of. */
  canManage: boolean
  switchTeam: (teamId: string) => void
  refresh: () => Promise<unknown>
}

export const TeamContext = createContext<TeamContextValue | null>(null)
