import { CloudOff, Cpu, Sparkles } from 'lucide-react'

/** Which engine answered: the model, the rule engine, or the rules after a failure. */
export function EngineChip({
  source,
  model,
  fallback,
}: {
  source: 'llm' | 'rules'
  model: string
  fallback: string | null
}) {
  if (fallback) {
    return (
      <span
        title={`${fallback}; showing the rule-based suggestion`}
        className="ml-auto inline-flex items-center gap-1 rounded-full bg-priority-medium/10 px-2 py-0.5 text-[11px] text-priority-medium"
      >
        <CloudOff aria-hidden className="size-3" /> {fallback}
      </span>
    )
  }
  return (
    <span
      title={source === 'llm' ? `Model: ${model}` : 'Rule-based engine, no data leaves the server'}
      className="ml-auto inline-flex items-center gap-1 rounded-full bg-canvas px-2 py-0.5 text-[11px] text-fg-muted"
    >
      {source === 'llm' ? (
        <Sparkles aria-hidden className="size-3" />
      ) : (
        <Cpu aria-hidden className="size-3" />
      )}
      {source === 'llm' ? model : 'Rules'}
    </span>
  )
}
