import { AnimatePresence, motion } from 'framer-motion'
import { Lock, MessageSquare, MoreHorizontal, Pencil, Trash2 } from 'lucide-react'
import { useRef, useState } from 'react'

import type { Comment, Incident } from '@/api/client'
import {
  useAddComment,
  useComments,
  useDeleteComment,
  useEditComment,
  useUsers,
} from '@/api/queries'
import { Kbd } from '@/components/incident-ui'
import { Markdown } from '@/components/Markdown'
import { Menu, MenuContent, MenuItem, MenuTrigger } from '@/components/menu'
import { Avatar, Button } from '@/components/ui'
import { formatDateTime, timeAgo } from '@/lib/time'
import { toastError } from '@/lib/toast'

import { useMentions } from './mentions'

function Editor({
  value,
  onChange,
  onSubmit,
  placeholder,
  autoFocus = false,
}: {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  placeholder: string
  autoFocus?: boolean
}) {
  const [preview, setPreview] = useState(false)
  const ref = useRef<HTMLTextAreaElement>(null)
  const { data: users } = useUsers()
  const mentions = useMentions({ value, onChange, users, textarea: ref })
  return (
    <div className="relative rounded-control border border-border bg-canvas focus-within:border-accent">
      <div className="flex gap-1 border-b border-border px-2 pt-1.5 text-xs">
        {(['Write', 'Preview'] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => {
              setPreview(tab === 'Preview')
            }}
            className={`rounded-t px-2 pb-1.5 ${preview === (tab === 'Preview') ? 'text-fg shadow-[inset_0_-2px_0_rgb(var(--accent))]' : 'text-fg-muted hover:text-fg'}`}
          >
            {tab}
          </button>
        ))}
      </div>
      {preview ? (
        <div className="min-h-24 p-3">
          {value.trim() ? (
            <Markdown>{value}</Markdown>
          ) : (
            <p className="text-sm text-fg-muted">Nothing to preview.</p>
          )}
        </div>
      ) : (
        <textarea
          ref={ref}
          {...mentions.inputProps}
          autoFocus={autoFocus}
          rows={3}
          maxLength={5000}
          value={value}
          onChange={(e) => {
            onChange(e.target.value)
            mentions.sync(e.target)
          }}
          onClick={(e) => {
            mentions.sync(e.currentTarget)
          }}
          onKeyUp={(e) => {
            if (e.key.startsWith('Arrow') && !mentions.open) mentions.sync(e.currentTarget)
          }}
          onBlur={() => {
            window.setTimeout(() => {
              mentions.close()
            }, 100)
          }}
          onKeyDown={(e) => {
            if (mentions.onKeyDown(e)) return
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
              e.preventDefault()
              onSubmit()
            }
          }}
          placeholder={placeholder}
          aria-label="Comment"
          className="block w-full resize-y bg-transparent px-3 py-2 text-sm outline-none placeholder:text-fg-muted/60"
        />
      )}
      {!preview && mentions.menu}
    </div>
  )
}

function CommentItem({ comment, incidentKey }: { comment: Comment; incidentKey: string }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(comment.body)
  const edit = useEditComment(incidentKey)
  const remove = useDeleteComment(incidentKey)

  const save = () => {
    const body = draft.trim()
    if (!body) return
    edit.mutate(
      { id: comment.id, body },
      {
        onSuccess: () => {
          setEditing(false)
        },
        onError: (err) => {
          toastError(err, 'Could not save the comment')
        },
      },
    )
  }

  return (
    <motion.li
      layout="position"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, height: 0, transition: { duration: 0.15 } }}
      transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
      className="flex gap-3"
    >
      <Avatar user={comment.author} size={28} />
      <div
        className={`min-w-0 flex-1 rounded-card border px-4 py-3 ${
          comment.is_internal
            ? 'border-priority-medium/30 bg-priority-medium/[0.06]'
            : 'border-border bg-surface'
        }`}
      >
        <div className="mb-1.5 flex items-center gap-2 text-sm">
          <span className="font-medium">{comment.author.name}</span>
          <time
            dateTime={comment.created_at}
            title={formatDateTime(comment.created_at)}
            className="text-xs text-fg-muted"
          >
            {timeAgo(comment.created_at)}
          </time>
          {comment.edited_at && <span className="text-xs text-fg-muted">· edited</span>}
          {comment.is_internal && (
            <span className="inline-flex items-center gap-1 rounded-full bg-priority-medium/15 px-1.5 text-[11px] text-priority-medium">
              <Lock aria-hidden className="size-3" /> Internal
            </span>
          )}
          {comment.can_modify && !editing && (
            <Menu>
              <MenuTrigger asChild>
                <button
                  type="button"
                  aria-label="Comment actions"
                  className="ml-auto rounded p-0.5 text-fg-muted hover:bg-elevated hover:text-fg"
                >
                  <MoreHorizontal className="size-4" />
                </button>
              </MenuTrigger>
              <MenuContent align="end">
                <MenuItem
                  onSelect={() => {
                    setDraft(comment.body)
                    setEditing(true)
                  }}
                >
                  <Pencil className="size-4" /> Edit
                </MenuItem>
                <MenuItem
                  danger
                  onSelect={() => {
                    remove.mutate(comment.id, {
                      onError: (err) => {
                        toastError(err, 'Could not delete the comment')
                      },
                    })
                  }}
                >
                  <Trash2 className="size-4" /> Delete
                </MenuItem>
              </MenuContent>
            </Menu>
          )}
        </div>
        {editing ? (
          <div className="space-y-2">
            <Editor
              value={draft}
              onChange={setDraft}
              onSubmit={save}
              placeholder="Edit comment"
              autoFocus
            />
            <div className="flex justify-end gap-2">
              <Button
                onClick={() => {
                  setEditing(false)
                }}
              >
                Cancel
              </Button>
              <Button variant="primary" loading={edit.isPending} onClick={save}>
                Save
              </Button>
            </div>
          </div>
        ) : (
          <Markdown>{comment.body}</Markdown>
        )}
      </div>
    </motion.li>
  )
}

export function Conversation({ incident }: { incident: Incident }) {
  const { data: comments, isPending } = useComments(incident.key)
  const add = useAddComment(incident.key)
  const [draft, setDraft] = useState('')
  const [internal, setInternal] = useState(false)
  const thread = useRef<HTMLUListElement>(null)

  const send = () => {
    const body = draft.trim()
    if (!body || add.isPending) return
    add.mutate(
      { body, is_internal: internal },
      {
        onSuccess: () => {
          setDraft('')
          setInternal(false)
          // Bring the new comment into view once it has rendered (spec 12.3).
          window.setTimeout(() => {
            thread.current?.lastElementChild?.scrollIntoView({
              behavior: document.documentElement.dataset.motion === 'reduce' ? 'auto' : 'smooth',
              block: 'nearest',
            })
          }, 60)
        },
        onError: (err) => {
          toastError(err, 'Could not post the comment')
        },
      },
    )
  }

  return (
    <div className="space-y-4">
      {isPending ? (
        <div className="space-y-3" aria-busy="true">
          {[0, 1].map((i) => (
            <div key={i} className="shimmer h-20 rounded-card" />
          ))}
        </div>
      ) : comments && comments.length > 0 ? (
        <ul ref={thread} className="space-y-4">
          <AnimatePresence initial={false}>
            {comments.map((c) => (
              <CommentItem key={c.id} comment={c} incidentKey={incident.key} />
            ))}
          </AnimatePresence>
        </ul>
      ) : (
        <p className="flex items-center gap-2 py-4 text-sm text-fg-muted">
          <MessageSquare aria-hidden className="size-4" /> No comments yet.
          {incident.permissions.can_comment && ' Start the conversation below.'}
        </p>
      )}

      {incident.permissions.can_comment && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            send()
          }}
          className="space-y-2"
        >
          <Editor
            value={draft}
            onChange={setDraft}
            onSubmit={send}
            placeholder="Add an update… Markdown supported, @ to mention"
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-fg-muted">
              <input
                type="checkbox"
                checked={internal}
                onChange={(e) => {
                  setInternal(e.target.checked)
                }}
                className="size-4 accent-[rgb(var(--priority-medium))]"
              />
              <Lock aria-hidden className="size-3.5" /> Internal note (hidden from viewers)
            </label>
            <div className="flex items-center gap-3">
              <span className="hidden items-center gap-1 text-xs text-fg-muted sm:flex">
                <Kbd>Ctrl</Kbd>
                <Kbd>Enter</Kbd>
              </span>
              <Button
                type="submit"
                variant="primary"
                loading={add.isPending}
                disabled={!draft.trim()}
              >
                {internal ? 'Add note' : 'Comment'}
              </Button>
            </div>
          </div>
        </form>
      )}
    </div>
  )
}
