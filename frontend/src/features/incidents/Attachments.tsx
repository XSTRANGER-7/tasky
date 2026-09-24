import * as Dialog from '@radix-ui/react-dialog'
import { AnimatePresence, motion } from 'framer-motion'
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FileJson,
  FileText,
  ImageIcon,
  Loader2,
  Paperclip,
  Trash2,
  UploadCloud,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import { toast } from 'sonner'

import {
  ACCEPT,
  downloadLink,
  formatBytes,
  MAX_UPLOAD_BYTES,
  useAttachments,
  useDeleteAttachment,
  useDownloadLink,
  useUpload,
  type Attachment,
} from '@/api/attachments'
import type { Incident } from '@/api/client'
import { timeAgo } from '@/lib/time'
import { toastError } from '@/lib/toast'

function fileIcon(a: Attachment) {
  if (a.is_image) return ImageIcon
  if (a.content_type === 'application/json') return FileJson
  return FileText
}

function Thumb({ a, onOpen }: { a: Attachment; onOpen: () => void }) {
  const { data } = useDownloadLink(a.id, true, a.is_image)
  const [loaded, setLoaded] = useState(false)
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`Preview ${a.filename}`}
      className="relative size-10 shrink-0 overflow-hidden rounded-control border border-border bg-canvas"
    >
      {!loaded && <span className="shimmer absolute inset-0" />}
      {data && (
        <img
          src={data.url}
          alt=""
          onLoad={() => {
            setLoaded(true)
          }}
          className={`size-full object-cover transition-opacity duration-base ${loaded ? 'opacity-100' : 'opacity-0'}`}
        />
      )}
    </button>
  )
}

async function openDownload(a: Attachment) {
  try {
    const { url } = await downloadLink(a.id, false)
    window.open(url, '_blank', 'noopener')
  } catch (err) {
    toastError(err, 'Could not get a download link')
  }
}

function Lightbox({
  images,
  index,
  onIndex,
  onClose,
}: {
  images: Attachment[]
  index: number | null
  onIndex: (i: number) => void
  onClose: () => void
}) {
  const current = index === null ? null : images[index]
  const { data } = useDownloadLink(
    current?.id ?? '',
    true,
    current !== null && current !== undefined,
  )
  const step = useCallback(
    (d: number) => {
      if (index === null || images.length < 2) return
      onIndex((index + d + images.length) % images.length)
    },
    [index, images.length, onIndex],
  )

  return (
    <Dialog.Root
      open={index !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <AnimatePresence>
        {index !== null && current && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-40 bg-black/80 backdrop-blur-sm"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              />
            </Dialog.Overlay>
            <Dialog.Content
              forceMount
              aria-describedby={undefined}
              onKeyDown={(e) => {
                if (e.key === 'ArrowRight') step(1)
                if (e.key === 'ArrowLeft') step(-1)
              }}
              className="fixed inset-0 z-50 flex flex-col items-center justify-center p-4 sm:p-10"
            >
              <Dialog.Title className="sr-only">{current.filename}</Dialog.Title>
              <div className="mb-3 flex w-full max-w-5xl items-center gap-2 text-sm text-white/80">
                <span className="truncate">{current.filename}</span>
                <span className="text-white/50">{formatBytes(current.size_bytes)}</span>
                {images.length > 1 && (
                  <span className="text-white/50">
                    · {index + 1} / {images.length}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => void openDownload(current)}
                  className="ml-auto rounded-control p-2 hover:bg-white/10"
                  aria-label="Download"
                >
                  <Download className="size-4" />
                </button>
                <Dialog.Close className="rounded-control p-2 hover:bg-white/10" aria-label="Close">
                  <X className="size-4" />
                </Dialog.Close>
              </div>
              <div className="relative flex min-h-0 w-full max-w-5xl flex-1 items-center justify-center">
                <AnimatePresence mode="wait">
                  {data ? (
                    <motion.img
                      key={current.id}
                      src={data.url}
                      alt={current.filename}
                      initial={{ opacity: 0, scale: 0.96 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.12 } }}
                      transition={{ type: 'spring', stiffness: 380, damping: 32 }}
                      className="max-h-full max-w-full rounded-card object-contain shadow-2xl"
                    />
                  ) : (
                    <Loader2 className="size-6 animate-spin text-white/60" />
                  )}
                </AnimatePresence>
                {images.length > 1 && (
                  <>
                    <button
                      type="button"
                      aria-label="Previous image"
                      onClick={() => {
                        step(-1)
                      }}
                      className="absolute left-0 rounded-full bg-black/40 p-2 text-white hover:bg-black/60"
                    >
                      <ChevronLeft className="size-5" />
                    </button>
                    <button
                      type="button"
                      aria-label="Next image"
                      onClick={() => {
                        step(1)
                      }}
                      className="absolute right-0 rounded-full bg-black/40 p-2 text-white hover:bg-black/60"
                    >
                      <ChevronRight className="size-5" />
                    </button>
                  </>
                )}
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  )
}

/** Properties-panel section: list, drag-and-drop / click / paste upload, lightbox. */
export function Attachments({ incident }: { incident: Incident }) {
  const { data: items = [], isPending } = useAttachments(incident.key)
  const upload = useUpload(incident.key)
  const remove = useDeleteAttachment(incident.key)
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState<string[]>([])
  const [lightbox, setLightbox] = useState<number | null>(null)
  const canUpload = incident.permissions.can_comment && !incident.is_deleted
  const images = items.filter((a) => a.is_image)

  const handle = useCallback(
    (files: FileList | File[]) => {
      for (const file of Array.from(files)) {
        if (file.size > MAX_UPLOAD_BYTES) {
          toast.error(`${file.name} is larger than 10 MB`)
          continue
        }
        setUploading((u) => [...u, file.name])
        // One promise per file: mutate()'s own callbacks only fire for the latest call.
        upload
          .mutateAsync(file)
          .then((att) => {
            toast.success(`Attached ${att.filename}`)
          })
          .catch((err: unknown) => {
            toastError(err, `Could not attach ${file.name}`)
          })
          .finally(() => {
            setUploading((u) => {
              const i = u.indexOf(file.name)
              return i < 0 ? u : [...u.slice(0, i), ...u.slice(i + 1)]
            })
          })
      }
    },
    [upload],
  )

  // Paste a screenshot anywhere on the page (not while typing in a field).
  useEffect(() => {
    if (!canUpload) return
    const onPaste = (e: ClipboardEvent) => {
      const target = e.target as HTMLElement | null
      if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return
      const files = Array.from(e.clipboardData?.files ?? [])
      if (files.length) {
        e.preventDefault()
        handle(files)
      }
    }
    window.addEventListener('paste', onPaste)
    return () => {
      window.removeEventListener('paste', onPaste)
    }
  }, [canUpload, handle])

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (canUpload && e.dataTransfer.files.length) handle(e.dataTransfer.files)
  }

  return (
    <section
      aria-labelledby="attachments-heading"
      className="rounded-card border border-border bg-surface p-4 shadow-[var(--shadow-elevated)]"
      onDragOver={(e) => {
        if (!canUpload) return
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => {
        setDragging(false)
      }}
      onDrop={onDrop}
    >
      <div className="mb-3 flex items-center justify-between">
        <h2 id="attachments-heading" className="flex items-center gap-2 text-sm font-medium">
          <Paperclip aria-hidden className="size-4 text-fg-muted" /> Attachments
          {items.length > 0 && <span className="text-xs text-fg-muted">{items.length}</span>}
        </h2>
      </div>

      {isPending ? (
        <div className="shimmer h-10 rounded-control" />
      ) : (
        <ul className="space-y-1">
          <AnimatePresence initial={false}>
            {items.map((a) => {
              const Icon = fileIcon(a)
              return (
                <motion.li
                  key={a.id}
                  layout="position"
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, height: 0, transition: { duration: 0.15 } }}
                  className="group flex items-center gap-2.5 rounded-control p-1 hover:bg-canvas"
                >
                  {a.is_image ? (
                    <Thumb
                      a={a}
                      onOpen={() => {
                        setLightbox(images.findIndex((i) => i.id === a.id))
                      }}
                    />
                  ) : (
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-control border border-border bg-canvas">
                      <Icon aria-hidden className="size-4 text-fg-muted" />
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      if (a.is_image) setLightbox(images.findIndex((i) => i.id === a.id))
                      else void openDownload(a)
                    }}
                    className="min-w-0 flex-1 text-left"
                  >
                    <span className="block truncate text-sm hover:underline">{a.filename}</span>
                    <span className="block text-xs text-fg-muted">
                      {formatBytes(a.size_bytes)} · {a.uploader.name.split(' ')[0]} ·{' '}
                      {timeAgo(a.created_at)}
                    </span>
                  </button>
                  <span className="flex opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                    <button
                      type="button"
                      aria-label={`Download ${a.filename}`}
                      onClick={() => void openDownload(a)}
                      className="rounded-control p-1.5 text-fg-muted hover:bg-elevated hover:text-fg"
                    >
                      <Download className="size-3.5" />
                    </button>
                    {a.can_delete && (
                      <button
                        type="button"
                        aria-label={`Remove ${a.filename}`}
                        onClick={() => {
                          remove.mutate(a.id, {
                            onSuccess: () => toast.success(`Removed ${a.filename}`),
                            onError: (err) => {
                              toastError(err, 'Could not remove the file')
                            },
                          })
                        }}
                        className="rounded-control p-1.5 text-fg-muted hover:bg-elevated hover:text-danger"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    )}
                  </span>
                </motion.li>
              )
            })}
            {uploading.map((name, i) => (
              <motion.li
                key={`up-${name}-${i}`}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex items-center gap-2.5 p-1"
                aria-live="polite"
              >
                <span className="flex size-10 items-center justify-center rounded-control border border-dashed border-accent/40 bg-accent/5">
                  <Loader2 className="size-4 animate-spin text-accent" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">{name}</span>
                  <span className="mt-1 block h-1 overflow-hidden rounded-full bg-canvas">
                    <span className="block h-full w-1/3 animate-[indeterminate_1.1s_ease-in-out_infinite] rounded-full bg-accent" />
                  </span>
                </span>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}

      {canUpload ? (
        <button
          type="button"
          onClick={() => input.current?.click()}
          className={`mt-2 flex w-full flex-col items-center gap-1 rounded-control border border-dashed px-3 py-4 text-center text-xs transition-colors ${
            dragging
              ? 'border-accent bg-accent/10 text-fg'
              : 'border-border text-fg-muted hover:border-fg-muted/50 hover:text-fg'
          }`}
        >
          <motion.span animate={{ y: dragging ? -3 : 0 }} className="flex">
            <UploadCloud aria-hidden className="size-5" />
          </motion.span>
          <span>
            {dragging ? 'Drop to attach' : 'Drop files, paste a screenshot, or click to choose'}
          </span>
          <span className="text-[11px] text-fg-muted/80">
            PNG, JPG, GIF, PDF, TXT, LOG, JSON · up to 10 MB
          </span>
        </button>
      ) : (
        items.length === 0 && <p className="text-xs text-fg-muted">No attachments.</p>
      )}
      {canUpload && (
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          aria-label="Choose files to attach"
          onChange={(e) => {
            if (e.target.files) handle(e.target.files)
            e.target.value = ''
          }}
        />
      )}

      <Lightbox
        images={images}
        index={lightbox}
        onIndex={setLightbox}
        onClose={() => {
          setLightbox(null)
        }}
      />
    </section>
  )
}
