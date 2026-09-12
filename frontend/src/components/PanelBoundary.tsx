import { Component, type ErrorInfo, type ReactNode } from 'react'
import { reportClientError } from '../lib/clientErrors'

interface PanelBoundaryProps {
  /** Human name of the workflow tab, for the card and the error report. */
  name: string
  children: ReactNode
}

interface PanelBoundaryState {
  error: Error | null
  /** Bumped by Retry so the subtree remounts from scratch. */
  attempt: number
}

/** Per-tab error boundary (wave 2): one panel crashing shows a retry card in
 *  its place while the header, sidebar and every other tab keep working.
 *  Reports through the same /api/client-errors path as the app boundary. */
export default class PanelBoundary extends Component<PanelBoundaryProps, PanelBoundaryState> {
  state: PanelBoundaryState = { error: null, attempt: 0 }

  static getDerivedStateFromError(error: Error): Partial<PanelBoundaryState> {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    reportClientError(error, info, this.props.name)
  }

  render() {
    if (this.state.error) {
      return (
        <div
          role="alert"
          className="max-w-lg rounded border border-red-200 bg-red-50 p-4 text-sm text-red-700"
        >
          <div className="font-semibold">The {this.props.name} panel hit an error.</div>
          <div className="mt-1 text-xs text-red-600">
            {this.state.error.message || 'Unknown error'} — it was reported automatically. The rest
            of the app keeps working; your inputs are saved on the server.
          </div>
          <button
            onClick={() => this.setState((s) => ({ error: null, attempt: s.attempt + 1 }))}
            className="mt-3 rounded bg-red-600 px-3 py-1 text-xs text-white hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      )
    }
    // Keying on the attempt remounts the children after a retry so any
    // state that caused the crash is discarded.
    return <div key={this.state.attempt}>{this.props.children}</div>
  }
}
