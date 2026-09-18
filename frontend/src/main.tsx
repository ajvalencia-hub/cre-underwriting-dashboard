import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import ErrorBoundary from './components/ErrorBoundary.tsx'
import Toaster from './components/Toaster.tsx'
import { toastError } from './lib/toast.ts'
import { initTheme } from './lib/uiPrefs.ts'

// Apply the stored theme before first paint (no light flash on dark setups).
initTheme()

// Safety net: an action whose failure isn't handled where it happens still
// tells the user something didn't finish, instead of failing silently.
window.addEventListener('unhandledrejection', (event) => {
  const reason: unknown = event.reason
  if (reason instanceof DOMException && reason.name === 'AbortError') return
  toastError("Something didn't finish", reason)
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
    <Toaster />
  </StrictMode>,
)
