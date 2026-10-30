import { setupWorker } from 'msw/browser'
import { createHandlers, type MockScenario } from './handlers'

const SCENARIOS: MockScenario[] = ['full', 'empty', 'offline']

function readScenario(): MockScenario {
  const fromUrl = new URLSearchParams(window.location.search).get('mock')
  if (fromUrl && (SCENARIOS as string[]).includes(fromUrl)) {
    try {
      sessionStorage.setItem('lw:mock', fromUrl)
    } catch {
      // storage unavailable — scenario just won't persist across reloads
    }
    return fromUrl as MockScenario
  }
  try {
    const stored = sessionStorage.getItem('lw:mock')
    if (stored && (SCENARIOS as string[]).includes(stored)) return stored as MockScenario
  } catch {
    // ignore
  }
  return 'full'
}

export async function startMockWorker(): Promise<void> {
  const scenario = readScenario()
  const worker = setupWorker(...createHandlers(scenario))
  await worker.start({ onUnhandledFrame: 'bypass', quiet: true })
  console.info(`[listen-wiseer] mock API active (scenario: ${scenario})`)
}
