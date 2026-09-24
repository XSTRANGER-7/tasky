import { AnimatePresence, motion } from 'framer-motion'
import { FileText, HelpCircle, MessageSquareText, Send, Sparkles, ThumbsUp, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  decide,
  useAiEnabled,
  usePostPostmortem,
  useSummary,
  type SummarySuggestion,
} from '@/api/ai'
import type { Incident } from '@/api/client'
import { Markdown } from '@/components/Markdown'
import { Button } from '@/components/ui'
import { toastError } from '@/lib/toast'

import { EngineChip } from './EngineChip'

const SUMMARY_THRESHOLD = 5 // spec 10.2: most useful once the thread has more than five comments

function SummaryView({ s, onClose }: { s: SummarySuggestion; onClose: () => void }) {
  const sm = s.summary
  if (!sm) return null
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="overflow-hidden"
    >
      <div className="mt-3 space-y-2 rounded-control border border-border bg-canvas p-3 text-sm">
        <div className="flex items-center gap-2">
          <MessageSquareText aria-hidden className="size-4 text-accent" />
          <span className="font-medium">Task summary</span>
          <EngineChip source={s.source} model={s.model} fallback={s.fallback_reason ?? null} />
        </div>
        <p>{sm.summary}</p>
        <p className="text-xs text-fg-muted">{sm.current_status}</p>
        {(sm.open_questions ?? []).length > 0 && (
          <div>
            <p className="mb-1 flex items-center gap-1 text-xs font-medium text-fg-muted">
              <HelpCircle aria-hidden className="size-3.5" /> Open questions
            </p>
            <ul className="list-disc space-y-0.5 pl-5 text-xs">
              {(sm.open_questions ?? []).map((q) => (
                <li key={q}>{q}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="flex justify-end gap-1 pt-1">
          <button
            type="button"
            onClick={() => {
              void decide(s.suggestion_id, 'accept').catch(() => undefined)
              toast.success('Thanks, noted as helpful')
              onClose()
            }}
            className="inline-flex h-7 items-center gap-1 rounded-control px-2 text-xs text-fg-muted hover:bg-elevated hover:text-fg"
          >
            <ThumbsUp className="size-3.5" /> Helpful
          </button>
          <button
            type="button"
            onClick={() => {
              void decide(s.suggestion_id, 'reject').catch(() => undefined)
              onClose()
            }}
            className="inline-flex h-7 items-center gap-1 rounded-control px-2 text-xs text-fg-muted hover:bg-elevated hover:text-fg"
          >
            <X className="size-3.5" /> Dismiss
          </button>
        </div>
      </div>
    </motion.div>
  )
}

function PostmortemEditor({
  s,
  incident,
  onClose,
}: {
  s: SummarySuggestion
  incident: Incident
  onClose: () => void
}) {
  const [markdown, setMarkdown] = useState(s.markdown ?? '')
  const [preview, setPreview] = useState(true)
  const post = usePostPostmortem(incident.key)
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="overflow-hidden"
    >
      <div
        role="region"
        aria-label="Postmortem draft"
        className="mt-3 rounded-control border border-border bg-canvas"
      >
        <div className="flex items-center gap-2 border-b border-border px-3 py-2">
          <FileText aria-hidden className="size-4 text-accent" />
          <span className="text-sm font-medium">Postmortem draft</span>
          <EngineChip source={s.source} model={s.model} fallback={s.fallback_reason ?? null} />
        </div>
        <div className="flex gap-1 px-2 pt-1.5 text-xs">
          {(['Preview', 'Edit'] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => {
                setPreview(tab === 'Preview')
              }}
              className={`rounded px-2 pb-1 ${preview === (tab === 'Preview') ? 'text-fg shadow-[inset_0_-2px_0_rgb(var(--accent))]' : 'text-fg-muted hover:text-fg'}`}
            >
              {tab}
            </button>
          ))}
        </div>
        {preview ? (
          <div className="max-h-80 overflow-y-auto p-3 text-sm">
            <Markdown>{markdown}</Markdown>
          </div>
        ) : (
          <textarea
            aria-label="Postmortem Markdown"
            value={markdown}
            onChange={(e) => {
              setMarkdown(e.target.value)
            }}
            rows={12}
            className="block w-full resize-y bg-transparent p-3 font-mono text-xs outline-none"
          />
        )}
        <div className="flex items-center justify-end gap-2 border-t border-border p-2">
          <Button
            variant="ghost"
            className="h-8 text-xs"
            onClick={() => {
              void decide(s.suggestion_id, 'reject').catch(() => undefined)
              onClose()
            }}
          >
            Discard
          </Button>
          {incident.permissions.can_comment && (
            <Button
              variant="primary"
              className="h-8 text-xs"
              loading={post.isPending}
              disabled={!markdown.trim()}
              onClick={() => {
                post.mutate(
                  { id: s.suggestion_id, markdown },
                  {
                    onSuccess: () => {
                      toast.success('Postmortem posted as an internal note')
                      onClose()
                    },
                    onError: (err) => {
                      toastError(err, 'Could not post the postmortem')
                    },
                  },
                )
              }}
            >
              <Send className="size-3.5" /> Post as internal note
            </Button>
          )}
        </div>
      </div>
    </motion.div>
  )
}

/**
 * The AI assistant banner at the top of a task: one click for a summary of the task and
 * its conversation, and a postmortem draft once it is resolved. Results open inside the
 * banner. Suggestions only; absent when AI is off.
 */
export function AiPanel({ incident }: { incident: Incident }) {
  const enabled = useAiEnabled()
  const run = useSummary(incident.key)
  const [result, setResult] = useState<SummarySuggestion | null>(null)
  if (!enabled || incident.is_deleted) return null

  const resolved = incident.status === 'resolved' || incident.status === 'closed'
  const long = incident.comment_count > SUMMARY_THRESHOLD

  const ask = (kind: 'summary' | 'postmortem') => {
    run.mutate(kind, {
      onSuccess: setResult,
      onError: (err) => {
        toastError(err, 'AI is unavailable right now')
      },
    })
  }

  return (
    <motion.section
      aria-labelledby="ai-heading"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1], delay: 0.05 }}
      className="ai-banner relative overflow-hidden rounded-card border border-accent/25 bg-surface p-4 shadow-[var(--shadow-elevated)] sm:px-5"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-[12px] bg-gradient-to-br from-[#6E8BFF] via-[#8B5CF6] to-[#EC4899] text-white shadow-[0_8px_20px_-6px_rgba(139,92,246,0.6)]">
            <Sparkles aria-hidden className="size-5" />
          </span>
          <div className="min-w-0">
            <h2 id="ai-heading" className="text-sm font-semibold">
              AI assistant
            </h2>
            <p className="text-xs text-fg-muted">
              {long
                ? `${incident.comment_count} comments so far. Catch up in seconds.`
                : 'Get a quick summary of this task and its conversation.'}{' '}
              <span className="hidden md:inline">
                Suggestions only: nothing changes until you act.
              </span>
            </p>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button
            variant="primary"
            className="btn-glow h-9 rounded-full px-4 text-xs"
            loading={run.isPending && run.variables === 'summary'}
            onClick={() => {
              ask('summary')
            }}
          >
            <MessageSquareText className="size-3.5" /> Summarize
          </Button>
          {resolved && (
            <Button
              variant="secondary"
              className="h-9 rounded-full px-4 text-xs"
              loading={run.isPending && run.variables === 'postmortem'}
              onClick={() => {
                ask('postmortem')
              }}
            >
              <FileText className="size-3.5" /> Draft postmortem
            </Button>
          )}
        </div>
      </div>
      {run.isPending && (
        <div className="mt-3 space-y-2" aria-busy="true" aria-label="Thinking">
          {[90, 70, 80].map((w) => (
            <div key={w} className="shimmer h-3.5 rounded" style={{ width: `${w}%` }} />
          ))}
        </div>
      )}
      <AnimatePresence mode="wait">
        {result?.kind === 'summary' && !run.isPending && (
          <SummaryView
            key={result.suggestion_id}
            s={result}
            onClose={() => {
              setResult(null)
            }}
          />
        )}
        {result?.kind === 'postmortem' && !run.isPending && (
          <PostmortemEditor
            key={result.suggestion_id}
            s={result}
            incident={incident}
            onClose={() => {
              setResult(null)
            }}
          />
        )}
      </AnimatePresence>
    </motion.section>
  )
}
