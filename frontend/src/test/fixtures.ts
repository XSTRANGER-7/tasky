import type { DashboardSummary, Incident, TeamPerson } from '@/api/client'

import { demoUser, TEST_TEAM_ID } from './mockApi'

// People in the test team, as the team directory lists them (with their team role).
export const ada: TeamPerson = {
  id: demoUser.id,
  name: 'Ada Admin',
  email: 'admin@demo.io',
  role: 'admin',
  avatar_color: '#4DD0E1',
}
export const jonas: TeamPerson = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Jonas Weber',
  email: 'jonas@demo.io',
  role: 'member',
  avatar_color: '#3DDC97',
}
export const team = [ada, jonas]

const HOUR = 3_600_000

export function incident(overrides: Partial<Incident> = {}): Incident {
  const now = Date.now()
  const merged: Omit<Incident, 'assignees'> & Partial<Pick<Incident, 'assignees'>> = {
    id: '22222222-2222-4222-8222-222222222222',
    key: 'INC-7',
    number: 7,
    team_id: TEST_TEAM_ID,
    title: 'Checkout API returning 502',
    description: 'Since the **14:02** deploy',
    status: 'open',
    priority: 'high',
    category: 'payments',
    tags: ['prod'],
    reporter: ada,
    assignee: jonas,
    response_due_at: new Date(now + HOUR).toISOString(),
    resolution_due_at: new Date(now + 6 * HOUR).toISOString(),
    first_response_at: null,
    resolved_at: null,
    closed_at: null,
    created_at: new Date(now - HOUR).toISOString(),
    updated_at: new Date(now - HOUR).toISOString(),
    is_deleted: false,
    comment_count: 0,
    sla: { response_breached: false, resolution_breached: false, at_risk: false, paused: false },
    allowed_transitions: ['in_progress', 'resolved'],
    permissions: { can_edit: true, can_assign: true, can_comment: true, can_delete: true },
    watching: false,
    watchers: [],
    ...overrides,
  }
  // Everyone assigned: the lead alone unless a test sets the list itself.
  return {
    ...merged,
    assignees: overrides.assignees ?? (merged.assignee ? [merged.assignee] : []),
  }
}

export function page(items: Incident[], next_cursor: string | null = null) {
  return { items, next_cursor, total: items.length }
}

export function dashboard(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  const today = new Date()
  return {
    counts: { open: 5, in_progress: 3, resolved: 10, closed: 7 },
    by_priority: { critical: 1, high: 2, medium: 1, low: 4 },
    open_by_assignee: [
      { user: jonas, count: 2 },
      { user: null, count: 4 },
    ],
    sla: { breached: 6, at_risk_next_hour: 1 },
    mttr_hours: { last_7d: 5.8, last_30d: 8.9 },
    trend_14d: Array.from({ length: 14 }, (_, i) => ({
      date: new Date(today.getTime() - (13 - i) * 24 * HOUR).toISOString().slice(0, 10),
      created: i % 3,
      resolved: (i + 1) % 2,
    })),
    recent_activity: [
      {
        id: '33333333-3333-4333-8333-333333333333',
        event_type: 'status_changed',
        actor: jonas,
        incident_id: '22222222-2222-4222-8222-222222222222',
        incident_key: 'INC-7',
        incident_title: 'Checkout API returning 502',
        field: 'status',
        old_value: 'open',
        new_value: 'in_progress',
        created_at: new Date().toISOString(),
      },
    ],
    generated_at: new Date().toISOString(),
    ...overrides,
  }
}
