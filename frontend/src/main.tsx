import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import ErrorBoundary from './components/ErrorBoundary.tsx'
import { initTheme } from './lib/uiPrefs.ts'

// Apply the stored theme before first paint (no light flash on dark setups).
// B13: this runs outside the ErrorBoundary — a storage/matchMedia failure
// must degrade to the default theme, never a blank page.
try {
  initTheme()
} catch {
  // default (light) theme
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
