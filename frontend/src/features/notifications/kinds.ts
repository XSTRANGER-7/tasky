import {
  AtSign,
  CheckCircle2,
  PencilLine,
  KeyRound,
  MessageSquare,
  TimerOff,
  ShieldCheck,
  UserCheck,
  UserMinus,
  UserPlus,
  UserX,
  Users,
  type LucideIcon,
} from 'lucide-react'

import type { AppNotification, NotificationKind } from '@/api/notifications'

export const kindMeta: Record<NotificationKind, { icon: LucideIcon; label: string; tone: string }> =
  {
    incident_assigned: { icon: UserPlus, label: 'Assigned', tone: 'text-accent bg-accent/10' },
    incident_resolved: {
      icon: CheckCircle2,
      label: 'Resolved',
      tone: 'text-status-resolved bg-status-resolved/10',
    },
    incident_updated: { icon: PencilLine, label: 'Updated', tone: 'text-accent bg-accent/10' },
    incident_added: { icon: UserPlus, label: 'Added you', tone: 'text-accent bg-accent/10' },
    incident_commented: {
      icon: MessageSquare,
      label: 'Comment',
      tone: 'text-fg-muted bg-canvas',
    },
    mentioned: { icon: AtSign, label: 'Mention', tone: 'text-priority-low bg-priority-low/10' },
    sla_breached: { icon: TimerOff, label: 'SLA breach', tone: 'text-danger bg-danger/10' },
    team_join_requested: { icon: Users, label: 'Join request', tone: 'text-accent bg-accent/10' },
    team_join_approved: {
      icon: UserCheck,
      label: 'Joined team',
      tone: 'text-status-resolved bg-status-resolved/10',
    },
    team_join_rejected: { icon: UserX, label: 'Request declined', tone: 'text-fg-muted bg-canvas' },
    team_member_added: {
      icon: UserCheck,
      label: 'Added to team',
      tone: 'text-status-resolved bg-status-resolved/10',
    },
    team_role_changed: { icon: ShieldCheck, label: 'Team role', tone: 'text-accent bg-accent/10' },
    team_member_removed: {
      icon: UserMinus,
      label: 'Removed from team',
      tone: 'text-fg-muted bg-canvas',
    },
    password_reset: { icon: KeyRound, label: 'Account', tone: 'text-fg-muted bg-canvas' },
  }

/** Where a notification opens: its incident, or the page it names (team requests...). */
export function notificationHref(n: Pick<AppNotification, 'incident_key' | 'link'>): string {
  if (n.incident_key) return `/tasks/${n.incident_key}`
  return n.link ?? '/notifications'
}
