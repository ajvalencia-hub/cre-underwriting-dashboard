import { Component, type ErrorInfo, type ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
}

/** App-level error boundary (H13): a render crash shows a recoverable
 *  fallback instead of a white page, and the error is reported to
 *  /api/client-errors so it lands in the same log stream as backend
 *  requests (fire-and-forget — reporting must never crash the fallback). */
export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    void fetch('/api/client-errors', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: String(error?.message ?? error).slice(0, 4000),
        stack: String(error?.stack ?? '').slice(0, 4000),
        componentStack: String(info?.componentStack ?? '').slice(0, 4000),
        url: window.location.href,
      }),
    }).catch(() => {})
  }

  render() {
    if (this.state.error) {
      return (
        <div className="mx-auto mt-16 max-w-lg rounded border border-red-200 bg-red-50 p-6 text-center">
          <div className="text-sm font-semibold text-red-700">Something went wrong.</div>
          <div className="mt-1 text-xs text-red-600">
            The error was reported automatically. Your deal data is saved on the server —
            reloading is safe.
          </div>
          <button
            onClick={() => window.location.reload()}
            className="mt-4 rounded bg-red-600 px-4 py-1.5 text-sm text-white hover:bg-red-700"
          >
            Reload
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
