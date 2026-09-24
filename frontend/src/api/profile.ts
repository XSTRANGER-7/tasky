/**
 * Profile photo: the cropped image goes up as the raw request body (the server sniffs its
 * type), like attachments, so this uses fetch directly with the same bearer token.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'

import {
  ApiError,
  api,
  apiUrl,
  getAccessToken,
  refreshSession,
  setSession,
  unwrap,
  type User,
} from './client'

export const MAX_AVATAR_BYTES = 2 * 1024 * 1024

async function put(photo: Blob): Promise<Response> {
  const send = () =>
    fetch(apiUrl('/api/v1/users/me/avatar'), {
      method: 'PUT',
      body: photo,
      credentials: 'same-origin',
      headers: {
        'content-type': 'application/octet-stream',
        ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken() ?? ''}` } : {}),
      },
    })
  const res = await send()
  if (res.status !== 401) return res
  return (await refreshSession()) ? send() : res
}

export async function uploadAvatar(photo: Blob): Promise<User> {
  if (photo.size > MAX_AVATAR_BYTES) {
    throw new ApiError(413, 'file_too_large', 'Photos can be at most 2 MB', null)
  }
  const res = await put(photo)
  const body: unknown = await res.json().catch(() => ({}))
  if (!res.ok) throw ApiError.fromResponse(res, body)
  return body as User
}

/** Set or remove my photo; every list that shows my avatar is refetched. */
export function useAvatar() {
  const qc = useQueryClient()
  const done = (me: User) => {
    setSession(getAccessToken(), me)
    void qc.invalidateQueries()
  }
  const upload = useMutation({ mutationFn: uploadAvatar, onSuccess: done })
  const remove = useMutation({
    mutationFn: () => unwrap(api.DELETE('/api/v1/users/me/avatar')),
    onSuccess: done,
  })
  return { upload, remove }
}
