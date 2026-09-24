import { toast } from 'sonner'

import { ApiError } from '@/api/client'

/** Error toast with the server's message and request ID, so a bug report is one copy away. */
export function toastError(err: unknown, fallback = 'Something went wrong'): void {
  if (err instanceof ApiError) {
    const requestId = err.requestId
    toast.error(err.message || fallback, {
      description: requestId ? `Request ${requestId}` : undefined,
      action: requestId
        ? { label: 'Copy ID', onClick: () => void navigator.clipboard.writeText(requestId) }
        : undefined,
    })
    return
  }
  toast.error(fallback, { description: 'Check your connection and try again.' })
}
