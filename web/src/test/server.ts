import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { createHandlers } from '@/mocks/handlers'

/** MSW node server with the fixture library; call inside a test file. */
export function setupMockServer() {
  const server = setupServer(...createHandlers('full'))
  beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
  afterEach(() => server.resetHandlers())
  afterAll(() => server.close())
  return server
}
