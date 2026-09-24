import type { HealthResult } from '@/api/health'
import { useHealth } from '@/app/useHealth'

type Tone = 'ok' | 'warn' | 'bad' | 'idle'

const toneDot: Record<Tone, string> = {
  ok: 'bg-status-resolved',
  warn: 'bg-priority-medium',
  bad: 'bg-danger',
  idle: 'bg-fg-muted',
}

const headline: Record<HealthResult['state'], { tone: Tone; label: string }> = {
  ok: { tone: 'ok', label: 'All systems operational' },
  degraded: { tone: 'warn', label: 'API up, database unreachable' },
  unreachable: { tone: 'bad', label: 'API unreachable' },
}

const CHECKING = { tone: 'idle', label: 'Checking…' } as const

function Row({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2">
      <dt className="text-sm text-fg-muted">{label}</dt>
      <dd className={`truncate text-sm ${mono ? 'font-mono' : ''}`} title={value}>
        {value}
      </dd>
    </div>
  )
}

/** Live /health probe: API, database, version and the request ID of the last check. */
export function SystemStatus() {
  const { result, checkedAt, checking, refresh } = useHealth()
  const status = result ? headline[result.state] : CHECKING
  const payload = result && result.state !== 'unreachable' ? result.payload : null
  const apiState = result ? (result.state === 'unreachable' ? 'down' : 'up') : '—'

  return (
    <section
      aria-labelledby="status-heading"
      className="rounded-card border border-border bg-surface p-5 shadow-[var(--shadow-elevated)]"
    >
      <div className="flex items-center justify-between gap-4">
        <h2 id="status-heading" className="flex items-center gap-2 text-md font-medium">
          <span
            aria-hidden
            className={`inline-block size-2 shrink-0 rounded-full ${toneDot[status.tone]}`}
          />
          <span role="status" aria-live="polite">
            {status.label}
          </span>
        </h2>
        <button
          type="button"
          onClick={refresh}
          disabled={checking}
          className="rounded-control border border-border px-3 py-1 text-sm text-fg-muted transition-colors duration-instant hover:bg-elevated hover:text-fg active:scale-[0.98] disabled:opacity-50"
        >
          {checking ? 'Checking…' : 'Check again'}
        </button>
      </div>

      <dl className="mt-4 divide-y divide-[color:var(--border)] border-t border-border">
        <Row label="API" value={apiState} />
        <Row label="Database" value={payload?.db ?? '—'} />
        <Row label="Version" value={payload?.version ?? '—'} mono />
        <Row label="Commit" value={payload?.git_sha.slice(0, 12) ?? '—'} mono />
        <Row label="Environment" value={payload?.env ?? '—'} />
        <Row label="Request ID" value={result?.requestId ?? '—'} mono />
      </dl>

      {result?.state === 'unreachable' && (
        <p className="mt-4 text-sm text-danger">{result.error}</p>
      )}
      <p className="tabular mt-3 text-xs text-fg-muted">
        {checkedAt ? `Last checked ${checkedAt.toLocaleTimeString()}` : 'Not checked yet'}
      </p>
    </section>
  )
}
