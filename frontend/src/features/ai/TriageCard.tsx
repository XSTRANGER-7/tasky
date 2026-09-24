import { useQuery } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, Check, CopyCheck, ExternalLink, Sparkles, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { decide, triage, useAiEnabled, type TriageSuggestion } from '@/api/ai'
import type { Priority, UserPublic } from '@/api/client'
import { PriorityBadge } from '@/components/incident-ui'
import { Avatar } from '@/components/ui'

import { EngineChip } from './EngineChip'

export interface TriageValues {
  priority: Priority
  category: string | null
  assignee: UserPublic | null
}

function useIdle<T>(value: T, ms: number): T {
  const [idle, setIdle] = useState(value)
  useEffect(() => {
    const id = window.setTimeout(() => {
      setIdle(value)
    }, ms)
    return () => {
      window.clearTimeout(id)
    }
  }, [value, ms])
  return idle
}

const row = {
  hidden: { opacity: 0, y: 4 },
  show: (i: number) => ({ opacity: 1, y: 0, transition: { delay: i * 0.06, duration: 0.2 } }),
}

function Shimmer() {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Thinking">
      {[70, 45, 85].map((w) => (
        <div key={w} className="shimmer h-4 rounded" style={{ width: `${w}%` }} />
      ))}
    </div>
  )
}

/** Triage suggestions for the draft in the create drawer (spec 10.2, 12.3). */
export function TriageCard({
  title,
  description,
  onApply,
}: {
  title: string
  description: string
  onApply: (values: TriageValues) => void
}) {
  const enabled = useAiEnabled()
  // Primitive values: an object literal would be new every render and never go idle.
  const idleTitle = useIdle(title.trim(), 600)
  const idleDescription = useIdle(description.trim(), 600)
  const draft = { title: idleTitle, description: idleDescription }
  const ready = enabled && draft.title.length >= 8
  const [handled, setHandled] = useState<string | null>(null)

  const query = useQuery({
    queryKey: ['ai', 'triage', draft.title, draft.description],
    queryFn: ({ signal }) => triage(draft, signal),
    enabled: ready,
    staleTime: Infinity,
    retry: false,
  })
  const s: TriageSuggestion | undefined = query.data
  const typing = title.trim() !== draft.title || description.trim() !== draft.description

  if (!enabled) return null
  const hidden = s && handled === s.suggestion_id

  return (
    <AnimatePresence>
      {(ready || typing) && !hidden && (
        <motion.section
          aria-label="AI triage suggestion"
          aria-live="polite"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, height: 0, marginTop: 0, transition: { duration: 0.2 } }}
          className="overflow-hidden rounded-card border border-accent/25 bg-accent/[0.04]"
        >
          <header className="flex items-center gap-2 border-b border-accent/15 px-3 py-2">
            <Sparkles aria-hidden className="size-4 text-accent" />
            <h3 className="text-sm font-medium">AI triage</h3>
            {s && (
              <EngineChip source={s.source} model={s.model} fallback={s.fallback_reason ?? null} />
            )}
          </header>

          <div className="p-3">
            {!ready ? (
              <p className="text-xs text-fg-muted">Keep typing: suggestions appear as you pause.</p>
            ) : query.isFetching || typing || !s ? (
              query.isError ? (
                <p className="text-xs text-fg-muted">
                  AI unavailable right now. Triage it yourself.
                </p>
              ) : (
                <Shimmer />
              )
            ) : (
              <motion.div
                initial="hidden"
                animate="show"
                className="space-y-3"
                key={s.suggestion_id}
              >
                {s.possible_duplicate_of && (
                  <motion.div
                    variants={row}
                    custom={0}
                    className="flex items-start gap-2 rounded-control border border-priority-medium/40 bg-priority-medium/10 px-2.5 py-2 text-xs"
                  >
                    <CopyCheck
                      aria-hidden
                      className="mt-0.5 size-3.5 shrink-0 text-priority-medium"
                    />
                    <span className="min-w-0 flex-1">
                      Possible duplicate of{' '}
                      <a
                        href={`/tasks/${s.possible_duplicate_of.key}`}
                        target="_blank"
                        rel="noreferrer"
                        className="font-mono underline"
                      >
                        {s.possible_duplicate_of.key}
                      </a>{' '}
                      “{s.possible_duplicate_of.title}” (
                      {Math.round(s.possible_duplicate_of.score * 100)}% similar,{' '}
                      {s.possible_duplicate_of.status.replace('_', ' ')})
                    </span>
                  </motion.div>
                )}

                <dl className="grid grid-cols-[5.5rem_1fr] items-center gap-x-3 gap-y-2 text-sm">
                  <motion.dt variants={row} custom={1} className="text-fg-muted">
                    Priority
                  </motion.dt>
                  <motion.dd variants={row} custom={1}>
                    <PriorityBadge priority={s.priority} />
                  </motion.dd>
                  <motion.dt variants={row} custom={2} className="text-fg-muted">
                    Category
                  </motion.dt>
                  <motion.dd variants={row} custom={2}>
                    {s.category ? (
                      <span className="rounded-full bg-canvas px-2 py-0.5 text-xs">
                        {s.category}
                      </span>
                    ) : (
                      <span className="text-fg-muted">—</span>
                    )}
                  </motion.dd>
                  <motion.dt variants={row} custom={3} className="text-fg-muted">
                    Assign to
                  </motion.dt>
                  <motion.dd variants={row} custom={3} className="flex items-center gap-2">
                    {s.assignee ? (
                      <>
                        <Avatar user={s.assignee.user} size={20} />
                        {s.assignee.user.name}
                        <span className="text-xs text-fg-muted">{s.assignee.open_count} open</span>
                      </>
                    ) : (
                      <span className="text-fg-muted">No suggestion</span>
                    )}
                  </motion.dd>
                  <motion.dt variants={row} custom={4} className="text-fg-muted">
                    Confidence
                  </motion.dt>
                  <motion.dd variants={row} custom={4} className="flex items-center gap-2">
                    <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-canvas">
                      <motion.span
                        className={`block h-full rounded-full ${s.confidence < 0.5 ? 'bg-priority-medium' : 'bg-accent'}`}
                        initial={{ width: 0 }}
                        animate={{ width: `${Math.round(s.confidence * 100)}%` }}
                        transition={{ duration: 0.7, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
                      />
                    </span>
                    <span className="text-xs tabular-nums text-fg-muted">
                      {Math.round(s.confidence * 100)}%
                    </span>
                    {s.confidence < 0.5 && (
                      <AlertTriangle
                        aria-label="Low confidence"
                        className="size-3.5 text-priority-medium"
                      />
                    )}
                  </motion.dd>
                </dl>

                <motion.p variants={row} custom={5} className="text-xs text-fg-muted">
                  {s.reasoning}
                </motion.p>

                {s.similar.length > 0 && !s.possible_duplicate_of && (
                  <motion.div variants={row} custom={6} className="text-xs">
                    <p className="mb-1 text-fg-muted">Similar past tasks</p>
                    <ul className="space-y-0.5">
                      {s.similar.slice(0, 3).map((x) => (
                        <li key={x.id}>
                          <a
                            href={`/tasks/${x.key}`}
                            target="_blank"
                            rel="noreferrer"
                            className="group inline-flex max-w-full items-center gap-1.5 hover:text-fg"
                          >
                            <span className="font-mono text-fg-muted">{x.key}</span>
                            <span className="truncate">{x.title}</span>
                            <ExternalLink
                              aria-hidden
                              className="size-3 shrink-0 opacity-0 group-hover:opacity-100"
                            />
                          </a>
                        </li>
                      ))}
                    </ul>
                  </motion.div>
                )}

                <motion.div variants={row} custom={7} className="flex justify-end gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => {
                      setHandled(s.suggestion_id)
                      void decide(s.suggestion_id, 'reject').catch(() => undefined)
                    }}
                    className="inline-flex h-7 items-center gap-1 rounded-control px-2 text-xs text-fg-muted hover:bg-canvas hover:text-fg"
                  >
                    <X className="size-3.5" /> Dismiss
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      onApply({
                        priority: s.priority,
                        category: s.category ?? null,
                        assignee: s.assignee?.user ?? null,
                      })
                      setHandled(s.suggestion_id)
                      void decide(s.suggestion_id, 'accept').catch(() => undefined)
                    }}
                    className="inline-flex h-7 items-center gap-1 rounded-control bg-accent px-2.5 text-xs font-medium text-white hover:bg-accent/90"
                  >
                    <Check className="size-3.5" /> Apply to form
                  </button>
                </motion.div>
              </motion.div>
            )}
          </div>
        </motion.section>
      )}
    </AnimatePresence>
  )
}
