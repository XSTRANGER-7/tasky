import { ApiError } from '@/api/client'

/** Map a 422 envelope's field errors ({loc: ["body", "email"], message}) to a record. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.status !== 422) return {}
  const fields = error.details.fields
  if (!Array.isArray(fields)) return {}
  const out: Record<string, string> = {}
  for (const f of fields as { loc?: unknown[]; message?: string }[]) {
    const name = f.loc?.[f.loc.length - 1]
    if (typeof name === 'string' && f.message) out[name] = f.message.replace(/^Value error, /, '')
  }
  return out
}
