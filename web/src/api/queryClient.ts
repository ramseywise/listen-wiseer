import { QueryClient } from '@tanstack/react-query'
import { shouldRetry } from './hooks'

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetry, staleTime: 30_000, refetchOnWindowFocus: false },
    },
  })
}
