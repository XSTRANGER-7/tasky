import { AlertOctagon, Check, Copy, RotateCcw } from 'lucide-react'
import { useState } from 'react'

import { ApiError } from '@/api/client'

import { Button } from './ui'

function details(error: Error): string {
  const lines = [
    `Error: ${error.message}`,
    `Page: ${window.location.pathname}${window.location.search}`,
    `Time: ${new Date().toISOString()}`,
    `Browser: ${navigator.userAgent}`,
  ]
  if (error instanceof ApiError) {
    lines.splice(1, 0, `Status: ${error.status} (${error.code})`)
    if (error.requestId) lines.splice(1, 0, `Request ID: ${error.requestId}`)
  }
  return lines.join('\n')
}

export function CrashCard({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const [copied, setCopied] = useState(false)
  const requestId = error instanceof ApiError ? error.requestId : null
  return (
    <div
      role="alert"
      className="mx-auto mt-10 max-w-lg rounded-card border border-danger/30 bg-surface p-6 shadow-[var(--shadow-elevated)]"
    >
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-danger/10 text-danger">
          <AlertOctagon aria-hidden className="size-5" />
        </span>
        <div className="min-w-0">
          <h1 className="text-md font-medium">This page hit a problem</h1>
          <p className="mt-1 text-sm text-fg-muted">
            The rest of the app still works. Try again, or copy the details for a bug report.
          </p>
          <p className="mt-3 break-words font-mono text-xs text-fg-muted">{error.message}</p>
          {requestId && (
            <p className="mt-1 font-mono text-xs text-fg-muted">Request ID {requestId}</p>
          )}
        </div>
      </div>
      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <Button
          variant="ghost"
          onClick={() => {
            void navigator.clipboard.writeText(details(error)).then(() => {
              setCopied(true)
            })
          }}
        >
          {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
          {copied ? 'Copied' : 'Copy details'}
        </Button>
        <Button variant="primary" onClick={onRetry}>
          <RotateCcw className="size-4" /> Try again
        </Button>
      </div>
    </div>
  )
}
