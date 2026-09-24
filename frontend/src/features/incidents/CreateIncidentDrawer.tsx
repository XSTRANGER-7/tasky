import * as Dialog from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'framer-motion'
import { X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { ApiError, type Priority, type UserPublic } from '@/api/client'
import { useCreateIncident } from '@/api/queries'
import { Kbd, PriorityBadge } from '@/components/incident-ui'
import { Markdown } from '@/components/Markdown'
import { Button, TextField } from '@/components/ui'
import { fieldErrors } from '@/features/auth/fieldErrors'
import { PRIORITIES } from '@/lib/incident'
import { spring } from '@/lib/motion'

import { TriageCard, type TriageValues } from '@/features/ai/TriageCard'

import { AssigneesPicker } from './PeoplePicker'

const TAG = /^[\w\-.]{1,30}$/

function TagInput({ tags, onChange }: { tags: string[]; onChange: (tags: string[]) => void }) {
  const [draft, setDraft] = useState('')
  const commit = () => {
    const tag = draft.trim().toLowerCase().replace(/^#/, '')
    if (tag && TAG.test(tag) && !tags.includes(tag) && tags.length < 10) onChange([...tags, tag])
    setDraft('')
  }
  return (
    <div>
      <label htmlFor="new-incident-tags" className="mb-1 block text-sm text-fg-muted">
        Tags
      </label>
      <div className="flex min-h-9 flex-wrap items-center gap-1.5 rounded-control border border-border bg-canvas px-2 py-1.5 focus-within:border-accent">
        {tags.map((tag) => (
          <span
            key={tag}
            className="inline-flex h-6 items-center gap-1 rounded-full bg-elevated px-2 text-xs"
          >
            {tag}
            <button
              type="button"
              aria-label={`Remove tag ${tag}`}
              onClick={() => {
                onChange(tags.filter((t) => t !== tag))
              }}
              className="text-fg-muted hover:text-fg"
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          id="new-incident-tags"
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value)
          }}
          onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault()
              commit()
            } else if (e.key === 'Backspace' && !draft && tags.length) {
              onChange(tags.slice(0, -1))
            }
          }}
          onBlur={commit}
          placeholder={tags.length ? '' : 'prod, database…'}
          className="min-w-24 flex-1 bg-transparent text-sm outline-none placeholder:text-fg-muted/60"
        />
      </div>
    </div>
  )
}

function PrioritySegments({
  value,
  onChange,
}: {
  value: Priority
  onChange: (p: Priority) => void
}) {
  return (
    <fieldset>
      <legend className="mb-1 block text-sm text-fg-muted">Priority</legend>
      <div
        role="radiogroup"
        className="relative grid grid-cols-4 rounded-control border border-border bg-canvas p-0.5"
      >
        {/* One highlight that slides by index. A shared layoutId here stalled the
            drawer exit animation and left an invisible modal mounted. */}
        <motion.span
          aria-hidden
          className="absolute inset-y-0.5 left-0.5 w-[calc(25%-1px)] rounded-[5px] bg-elevated shadow-[var(--shadow-elevated)] ring-1 ring-[color:var(--border)]"
          initial={false}
          animate={{ x: `${PRIORITIES.indexOf(value) * 100}%` }}
          transition={spring}
        />
        {PRIORITIES.map((p) => (
          <button
            key={p}
            type="button"
            role="radio"
            aria-checked={value === p}
            onClick={() => {
              onChange(p)
            }}
            className="relative flex h-8 items-center justify-center rounded-[5px] text-xs"
          >
            <span className="relative">
              <PriorityBadge priority={p} />
            </span>
          </button>
        ))}
      </div>
    </fieldset>
  )
}

export function CreateIncidentDrawer({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const navigate = useNavigate()
  const create = useCreateIncident()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [preview, setPreview] = useState(false)
  const [priority, setPriority] = useState<Priority>('medium')
  const [assignees, setAssignees] = useState<UserPublic[]>([])
  const [category, setCategory] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [error, setError] = useState<unknown>(null)
  // Fields just filled by an accepted AI suggestion flash once (spec 12.3).
  const [flash, setFlash] = useState<{ fields: string[]; n: number }>({ fields: [], n: 0 })
  const flashing = (field: string) =>
    flash.fields.includes(field) ? 'ai-flash rounded-control' : ''
  function applyTriage(v: TriageValues) {
    setPriority(v.priority)
    if (v.category) setCategory(v.category)
    if (v.assignee) setAssignees([v.assignee])
    setFlash((f) => ({
      fields: [
        'priority',
        ...(v.category ? ['category'] : []),
        ...(v.assignee ? ['assignee'] : []),
      ],
      n: f.n + 1,
    }))
  }
  const idempotencyKey = useRef('')
  const titleRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      // One key per drawer opening: a double submit or network retry cannot duplicate.
      idempotencyKey.current = crypto.randomUUID()
      setError(null)
    }
  }, [open])

  function reset() {
    setTitle('')
    setDescription('')
    setPreview(false)
    setPriority('medium')
    setAssignees([])
    setCategory('')
    setTags([])
    setError(null)
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault()
    if (title.trim().length < 3) {
      setError(
        new ApiError(422, 'validation_error', 'Title needs at least 3 characters', null, {
          fields: [{ loc: ['body', 'title'], message: 'At least 3 characters' }],
        }),
      )
      titleRef.current?.focus()
      return
    }
    try {
      const incident = await create.mutateAsync({
        idempotencyKey: idempotencyKey.current,
        body: {
          title: title.trim(),
          description,
          priority,
          assignee_id: assignees[0]?.id ?? null,
          ...(assignees.length > 1 ? { assignee_ids: assignees.map((a) => a.id) } : {}),
          category: category.trim() || null,
          tags,
        },
      })
      onOpenChange(false)
      reset()
      toast.success(`${incident.key} created`, {
        description: incident.title,
        action: {
          label: 'Open',
          onClick: () => {
            navigate(`/tasks/${incident.key}`)
          },
        },
      })
      navigate(`/tasks/${incident.key}`)
    } catch (err) {
      setError(err)
    }
  }

  const errors = fieldErrors(error)
  const general = error && Object.keys(errors).length === 0 ? error : null

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-40 bg-black/40"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0, transition: { duration: 0.15 } }}
              />
            </Dialog.Overlay>
            <Dialog.Content
              asChild
              forceMount
              onOpenAutoFocus={(e) => {
                e.preventDefault()
                titleRef.current?.focus()
              }}
            >
              <motion.div
                className="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col border-l border-border bg-surface shadow-[var(--shadow-elevated)]"
                initial={{ x: '100%' }}
                animate={{ x: 0, transition: spring }}
                exit={{ x: '100%', transition: { duration: 0.16, ease: [0.7, 0, 0.84, 0] } }}
              >
                <form
                  onSubmit={(e) => void submit(e)}
                  onKeyDown={(e) => {
                    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') void submit()
                  }}
                  className="flex h-full flex-col"
                  noValidate
                >
                  <header className="flex h-14 items-center justify-between border-b border-border px-5">
                    <Dialog.Title className="text-md font-medium">New task</Dialog.Title>
                    <Dialog.Close asChild>
                      <Button variant="ghost" className="w-9 px-0" aria-label="Close">
                        <X className="size-4" />
                      </Button>
                    </Dialog.Close>
                  </header>
                  <Dialog.Description className="sr-only">
                    Create a new task. It will show you as its creator.
                  </Dialog.Description>

                  <motion.div
                    className="flex-1 space-y-5 overflow-y-auto p-5"
                    initial="hidden"
                    animate="show"
                    variants={{
                      show: { transition: { staggerChildren: 0.04, delayChildren: 0.08 } },
                    }}
                  >
                    {[
                      <TextField
                        key="title"
                        ref={titleRef}
                        label="Title"
                        placeholder="What is broken, for whom?"
                        maxLength={200}
                        value={title}
                        onChange={(e) => {
                          setTitle(e.target.value)
                        }}
                        error={errors.title}
                      />,
                      <div key="description">
                        <div className="mb-1 flex items-center justify-between">
                          <label
                            htmlFor="new-incident-description"
                            className="text-sm text-fg-muted"
                          >
                            Description
                          </label>
                          <div className="flex rounded-control border border-border p-0.5 text-xs">
                            {(['Write', 'Preview'] as const).map((tab) => (
                              <button
                                key={tab}
                                type="button"
                                onClick={() => {
                                  setPreview(tab === 'Preview')
                                }}
                                className={`rounded-[4px] px-2 py-0.5 ${preview === (tab === 'Preview') ? 'bg-elevated text-fg' : 'text-fg-muted'}`}
                              >
                                {tab}
                              </button>
                            ))}
                          </div>
                        </div>
                        {preview ? (
                          <div className="min-h-36 rounded-control border border-border bg-canvas p-3">
                            {description.trim() ? (
                              <Markdown>{description}</Markdown>
                            ) : (
                              <p className="text-sm text-fg-muted">Nothing to preview yet.</p>
                            )}
                          </div>
                        ) : (
                          <textarea
                            id="new-incident-description"
                            rows={7}
                            maxLength={20000}
                            value={description}
                            onChange={(e) => {
                              setDescription(e.target.value)
                            }}
                            placeholder={
                              'Impact, first seen, steps to reproduce…\n\nMarkdown supported.'
                            }
                            className="w-full resize-y rounded-control border border-border bg-canvas px-3 py-2 text-sm outline-none transition-colors placeholder:text-fg-muted/60 focus:border-accent"
                          />
                        )}
                      </div>,
                      <div key={`priority-${flash.n}`} className={flashing('priority')}>
                        <PrioritySegments value={priority} onChange={setPriority} />
                      </div>,
                      <div key={`assignee-${flash.n}`} className={flashing('assignee')}>
                        <span className="mb-1 block text-sm text-fg-muted">
                          Assign to{' '}
                          <span className="text-fg-muted/70">(one or more, optional)</span>
                        </span>
                        <AssigneesPicker value={assignees} onChange={setAssignees} />
                        {errors.assignee_id && (
                          <p className="mt-1 text-xs text-danger">{errors.assignee_id}</p>
                        )}
                      </div>,
                      <div key={`category-${flash.n}`} className={flashing('category')}>
                        <TextField
                          label="Category"
                          placeholder="database, auth, network…"
                          maxLength={50}
                          value={category}
                          onChange={(e) => {
                            setCategory(e.target.value)
                          }}
                          error={errors.category}
                        />
                      </div>,
                      <TagInput key="tags" tags={tags} onChange={setTags} />,
                    ].map((field, i) => (
                      <motion.div
                        key={i}
                        variants={{ hidden: { opacity: 0, y: 6 }, show: { opacity: 1, y: 0 } }}
                      >
                        {field}
                      </motion.div>
                    ))}

                    <TriageCard title={title} description={description} onApply={applyTriage} />

                    {general instanceof ApiError && (
                      <p
                        role="alert"
                        className="rounded-control border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
                      >
                        {general.message}
                      </p>
                    )}
                  </motion.div>

                  <footer className="flex items-center justify-between gap-3 border-t border-border px-5 py-3">
                    <span className="hidden items-center gap-1 text-xs text-fg-muted sm:flex">
                      <Kbd>Ctrl</Kbd>
                      <Kbd>Enter</Kbd> to create
                    </span>
                    <div className="ml-auto flex gap-2">
                      <Dialog.Close asChild>
                        <Button>Cancel</Button>
                      </Dialog.Close>
                      <Button type="submit" variant="primary" loading={create.isPending}>
                        Create task
                      </Button>
                    </div>
                  </footer>
                </form>
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  )
}
