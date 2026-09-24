import type { Priority, Status } from '@/api/client'

export const STATUSES: Status[] = ['open', 'in_progress', 'resolved', 'closed']
export const PRIORITIES: Priority[] = ['critical', 'high', 'medium', 'low']

export const statusLabel: Record<Status, string> = {
  open: 'Open',
  in_progress: 'In progress',
  resolved: 'Resolved',
  closed: 'Closed',
}

/** Verb for the button that moves an incident *to* a status, given where it is now. */
export function transitionLabel(from: Status, to: Status): string {
  if (to === 'in_progress') return 'Start work'
  if (to === 'resolved') return 'Resolve'
  if (to === 'closed') return 'Close'
  return from === 'in_progress' ? 'Pause' : 'Reopen'
}

export const priorityLabel: Record<Priority, string> = {
  critical: 'Critical',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
}

/** Tailwind classes per status / priority. Only these carry colour (spec 11.1). */
export const statusTone: Record<Status, { dot: string; text: string; ring: string }> = {
  open: { dot: 'bg-status-open', text: 'text-status-open', ring: 'border-status-open/40' },
  in_progress: {
    dot: 'bg-status-progress',
    text: 'text-status-progress',
    ring: 'border-status-progress/40',
  },
  resolved: {
    dot: 'bg-status-resolved',
    text: 'text-status-resolved',
    ring: 'border-status-resolved/40',
  },
  closed: { dot: 'bg-status-closed', text: 'text-fg-muted', ring: 'border-border' },
}

export const priorityTone: Record<Priority, { text: string; border: string; bg: string }> = {
  critical: {
    text: 'text-priority-critical',
    border: 'border-l-priority-critical',
    bg: 'bg-priority-critical',
  },
  high: { text: 'text-priority-high', border: 'border-l-priority-high', bg: 'bg-priority-high' },
  medium: {
    text: 'text-priority-medium',
    border: 'border-l-priority-medium',
    bg: 'bg-priority-medium',
  },
  low: { text: 'text-priority-low', border: 'border-l-priority-low', bg: 'bg-priority-low' },
}

/** CSS colour values for charts (Recharts needs real colours, not classes). */
export const priorityColor: Record<Priority, string> = {
  critical: 'rgb(var(--priority-critical))',
  high: 'rgb(var(--priority-high))',
  medium: 'rgb(var(--priority-medium))',
  low: 'rgb(var(--priority-low))',
}
