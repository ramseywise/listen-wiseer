import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { applyTheme, useUi } from './lib/uiStore'

applyTheme(useUi.getState().theme)

async function enableMocks(): Promise<void> {
  if (import.meta.env.MODE !== 'mock') return
  const { startMockWorker } = await import('./mocks/browser')
  await startMockWorker()
}

void enableMocks().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
