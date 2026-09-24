import { useContext } from 'react'

import { TeamContext, type TeamContextValue } from './context'

export function useTeam(): TeamContextValue {
  const ctx = useContext(TeamContext)
  if (!ctx) throw new Error('useTeam must be used inside <TeamProvider>')
  return ctx
}
