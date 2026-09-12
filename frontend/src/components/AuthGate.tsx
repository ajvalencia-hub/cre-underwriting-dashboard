import { useState } from 'react'
import { login } from '../lib/api'

interface AuthGateProps {
  /** Called once the session cookie is set — the caller re-runs boot. */
  onAuthenticated: () => void
}

/** F1: minimal full-page token prompt shown when the backend requires an
 *  API token and the browser has no session. POST /api/auth/login sets an
 *  HttpOnly cookie, so nothing is stored client-side. */
export default function AuthGate({ onAuthenticated }: AuthGateProps) {
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!token.trim() || busy) return
    setBusy(true)
    setError(null)
    try {
      await login(token.trim())
      setToken('')
      onAuthenticated()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-8">
      <form
        onSubmit={(e) => void handleSubmit(e)}
        className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      >
        <div className="text-sm font-semibold tracking-wide text-slate-500">CRE UNDERWRITING</div>
        <h1 className="mt-2 text-lg font-semibold text-slate-800">API token required</h1>
        <p className="mt-1 text-xs text-slate-500">
          This backend is protected. Enter the API token configured on the server to start a
          session in this browser.
        </p>
        <label htmlFor="api-token" className="mt-4 block text-xs font-medium text-slate-600">
          API token
        </label>
        <input
          id="api-token"
          type="password"
          autoComplete="off"
          autoFocus
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
        />
        {error && (
          <div role="alert" className="mt-2 text-xs text-red-600">
            {error}
          </div>
        )}
        <button
          type="submit"
          disabled={busy || !token.trim()}
          className="mt-4 w-full rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700 disabled:opacity-40"
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
