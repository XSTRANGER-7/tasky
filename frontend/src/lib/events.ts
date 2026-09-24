import {
  AlertTriangle,
  Eye,
  Paperclip,
  Sparkles,
  EyeOff,
  TimerOff,
  CircleDot,
  MessageSquare,
  Pencil,
  Plus,
  RotateCcw,
  Trash2,
  UserPlus,
  UserX,
  type LucideIcon,
} from 'lucide-react'

import type { IncidentEvent } from '@/api/client'

import { priorityLabel, statusLabel } from './incident'
import { formatDuration } from './time'

type EventLike = Pick<IncidentEvent, 'event_type' | 'field' | 'old_value' | 'new_value'>

export const eventIcon: Record<IncidentEvent['event_type'], LucideIcon> = {
  created: Plus,
  updated: Pencil,
  assigned: UserPlus,
  unassigned: UserX,
  status_changed: CircleDot,
  priority_changed: AlertTriangle,
  commented: MessageSquare,
  comment_edited: MessageSquare,
  comment_deleted: Trash2,
  deleted: Trash2,
  restored: RotateCcw,
  watcher_added: Eye,
  watcher_removed: EyeOff,
  sla_breached: TimerOff,
  attachment_added: Paperclip,
  attachment_deleted: Paperclip,
  ai_applied: Sparkles,
}

function fileName(value: unknown): string {
  return value && typeof value === 'object' && 'filename' in value
    ? String(value.filename)
    : 'a file'
}

function name(value: unknown): string {
  return value && typeof value === 'object' && 'name' in value ? String(value.name) : 'someone'
}

function label<T extends string>(map: Record<T, string>, value: unknown): string {
  return typeof value === 'string' && value in map ? map[value as T] : String(value)
}

/** Human sentence for an audit event, e.g. "moved to Resolved". */
export function describeEvent(e: EventLike): string {
  const nv: unknown = e.new_value
  const ov: unknown = e.old_value
  switch (e.event_type) {
    case 'created':
      return 'created the task'
    case 'assigned':
      return ov ? `reassigned from ${name(ov)} to ${name(nv)}` : `assigned ${name(nv)}`
    case 'unassigned':
      return `unassigned ${name(ov)}`
    case 'status_changed':
      return `moved ${label(statusLabel, ov)} → ${label(statusLabel, nv)}`
    case 'priority_changed':
      return `changed priority ${label(priorityLabel, (ov as { priority?: string } | null)?.priority)} → ${label(priorityLabel, (nv as { priority?: string } | null)?.priority)}`
    case 'updated':
      return `edited the ${e.field ?? 'task'}`
    case 'commented':
      return (nv as { internal?: boolean } | null)?.internal
        ? 'added an internal note'
        : 'commented'
    case 'comment_edited':
      return 'edited a comment'
    case 'comment_deleted':
      return 'deleted a comment'
    case 'deleted':
      return 'deleted the task'
    case 'restored':
      return 'restored the task'
    case 'watcher_added':
      return 'started watching'
    case 'watcher_removed':
      return 'stopped watching'
    case 'sla_breached': {
      const minutes = (nv as { overdue_minutes?: number } | null)?.overdue_minutes
      return minutes
        ? `breached the resolution SLA (${formatDuration(minutes * 60_000)} over)`
        : 'breached the resolution SLA'
    }
    case 'attachment_added':
      return `attached ${fileName(nv)}`
    case 'attachment_deleted':
      return `removed ${fileName(ov)}`
    case 'ai_applied':
      return 'applied an AI triage suggestion'
  }
}
