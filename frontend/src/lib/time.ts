const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** "just now", "5m ago", "3h ago", "2d ago", then a short date. */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const diff = now - new Date(iso).getTime()
  if (diff < 45_000) return 'just now'
  if (diff < HOUR) return `${Math.max(1, Math.round(diff / MINUTE))}m ago`
  if (diff < DAY) return `${Math.round(diff / HOUR)}h ago`
  if (diff < 7 * DAY) return `${Math.round(diff / DAY)}d ago`
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

/** Compact duration for SLA timers: "45m", "3h 20m", "2d 4h". */
export function formatDuration(ms: number): string {
  const abs = Math.abs(ms)
  if (abs < HOUR) return `${Math.max(1, Math.floor(abs / MINUTE))}m`
  if (abs < DAY) {
    const h = Math.floor(abs / HOUR)
    const m = Math.floor((abs % HOUR) / MINUTE)
    return m ? `${h}h ${m}m` : `${h}h`
  }
  const d = Math.floor(abs / DAY)
  const h = Math.floor((abs % DAY) / HOUR)
  return h ? `${d}d ${h}h` : `${d}d`
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatHours(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return '—'
  if (hours < 1) return `${Math.round(hours * 60)}m`
  return `${hours.toFixed(1)}h`
}
