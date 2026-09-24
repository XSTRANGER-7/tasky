/**
 * Attachments: the file is sent as the raw request body (the server sniffs its type), so
 * this uses fetch directly instead of the JSON client, with the same bearer token and a
 * single refresh-and-retry on 401.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  ApiError,
  api,
  apiUrl,
  getAccessToken,
  getActiveTeam,
  refreshSession,
  unwrap,
} from './client'
import { keys } from './queries'
import type { components } from './schema'

export type Attachment = components['schemas']['AttachmentOut']

export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024
export const ACCEPT =
  '.png,.jpg,.jpeg,.gif,.pdf,.txt,.log,.json,image/png,image/jpeg,image/gif,application/pdf,text/plain,application/json'

export const attachmentKeys = {
  list: (ident: string) => ['incidents', 'attachments', ident] as const,
}

export function useAttachments(ident: string) {
  return useQuery({
    queryKey: attachmentKeys.list(ident),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/incidents/{ident}/attachments', { params: { path: { ident } }, signal }),
      ),
  })
}

async function send(ident: string, file: File): Promise<Response> {
  const url = apiUrl(
    `/api/v1/incidents/${encodeURIComponent(ident)}/attachments?filename=${encodeURIComponent(file.name)}`,
  )
  const post = () =>
    fetch(url, {
      method: 'POST',
      body: file,
      credentials: 'same-origin',
      headers: {
        'content-type': 'application/octet-stream',
        ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken() ?? ''}` } : {}),
        ...(getActiveTeam() ? { 'X-Team-Id': getActiveTeam() ?? '' } : {}),
      },
    })
  const res = await post()
  if (res.status !== 401) return res
  return (await refreshSession()) ? post() : res
}

export async function uploadAttachment(ident: string, file: File): Promise<Attachment> {
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new ApiError(413, 'file_too_large', 'Files can be at most 10 MB', null)
  }
  const res = await send(ident, file)
  const body: unknown = await res.json().catch(() => ({}))
  if (!res.ok) throw ApiError.fromResponse(res, body)
  return body as Attachment
}

export function useUpload(ident: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => uploadAttachment(ident, file),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: attachmentKeys.list(ident) })
      void qc.invalidateQueries({ queryKey: keys.events(ident) })
    },
  })
}

export function useDeleteAttachment(ident: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE('/api/v1/attachments/{attachment_id}', {
          params: { path: { attachment_id: id } },
        }),
      ),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: attachmentKeys.list(ident) })
      const previous = qc.getQueryData<Attachment[]>(attachmentKeys.list(ident))
      qc.setQueryData<Attachment[]>(attachmentKeys.list(ident), (old) =>
        old?.filter((a) => a.id !== id),
      )
      return { previous }
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.previous) qc.setQueryData(attachmentKeys.list(ident), ctx.previous)
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: keys.events(ident) })
    },
  })
}

/** A short-lived signed URL (images can then load without a bearer token). */
export function downloadLink(id: string, inline = false): Promise<{ url: string }> {
  return unwrap(
    api.GET('/api/v1/attachments/{attachment_id}/download', {
      params: { path: { attachment_id: id }, query: { inline } },
      headers: { accept: 'application/json' },
    }),
  )
}

export function useDownloadLink(id: string, inline: boolean, enabled = true) {
  return useQuery({
    queryKey: ['attachments', 'link', id, inline],
    queryFn: () => downloadLink(id, inline),
    enabled,
    staleTime: 4 * 60_000, // links live 5 minutes
  })
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
