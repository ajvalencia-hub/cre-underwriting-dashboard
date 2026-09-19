import type { ErrorInfo } from 'react'

/** Fire-and-forget report to /api/client-errors so a render crash lands in
 *  the same log stream as backend requests. Reporting must never throw —
 *  the fallback UI depends on it. Shared by the app-level ErrorBoundary and
 *  the per-tab PanelBoundary (wave 2). */
export function reportClientError(error: Error, info: ErrorInfo, panel?: string): void {
  try {
    void fetch('/api/client-errors', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: `${panel ? `[${panel}] ` : ''}${String(error?.message ?? error)}`.slice(0, 4000),
        stack: String(error?.stack ?? '').slice(0, 4000),
        componentStack: String(info?.componentStack ?? '').slice(0, 4000),
        url: window.location.href,
      }),
    }).catch(() => {})
  } catch {
    // never let reporting crash the fallback
  }
}
