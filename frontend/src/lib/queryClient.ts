import { QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api/client'

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: true,
        // 4xx will not fix itself on retry; network blips and 5xx get two more tries.
        retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
      },
    },
  })
}
