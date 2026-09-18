import { useState } from 'react'
import { isDesktop } from '../lib/platform'
import type { AcquisitionQuickScreenInputs, QuickScreenInputs } from '../lib/quickScreenMath'
import { buildShareLink, parseShareLink, shareParams, type ScreenMode, type SharedScreen } from '../lib/shareLink'
import { showToast, toastError } from '../lib/toast'

interface QuickScreenShareProps {
  development: QuickScreenInputs
  acquisition: AcquisitionQuickScreenInputs
  mode: ScreenMode
  onOpenShared: (shared: SharedScreen) => void
}

/** "Copy share link" + "Open shared link…" for the Quick Screen napkins. */
export default function QuickScreenShare({ development, acquisition, mode, onOpenShared }: QuickScreenShareProps) {
  const [pasting, setPasting] = useState(false)
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function copy() {
    const params = shareParams(development, acquisition, mode)
    const link = buildShareLink(params, isDesktop() ? null : `${window.location.origin}${window.location.pathname}`)
    try {
      await navigator.clipboard.writeText(link)
      showToast({
        kind: 'success',
        message: 'Share link copied',
        detail: isDesktop()
          ? 'Your colleague opens it with Quick Screen → Open shared link… in their copy of the app.'
          : 'Anyone with access to this dashboard can open it in a browser.',
      })
    } catch (err) {
      toastError('Could not copy to the clipboard — select and copy the link manually', `${link} (${String(err)})`)
    }
  }

  function open() {
    const shared = parseShareLink(text)
    if (shared === null) {
      setError("That doesn't look like a Quick Screen share link.")
      return
    }
    const sure = window.confirm(
      "Replace this deal's Quick Screen inputs with the shared ones? Your current napkin values will be overwritten.",
    )
    if (!sure) return
    onOpenShared(shared)
    setPasting(false)
    setText('')
    setError(null)
  }

  return (
    <div className="text-sm">
      <div className="flex items-center gap-2">
        <button
          onClick={() => void copy()}
          className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          Copy share link
        </button>
        <button
          onClick={() => setPasting((v) => !v)}
          aria-expanded={pasting}
          className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          Open shared link…
        </button>
      </div>
      {pasting && (
        <form
          className="mt-2 flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            open()
          }}
        >
          <label className="sr-only" htmlFor="qs-shared-link">
            Shared link
          </label>
          <input
            id="qs-shared-link"
            autoFocus
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              setError(null)
            }}
            placeholder="Paste a Quick Screen link"
            className="w-96 rounded border border-slate-300 px-2 py-1 text-xs"
          />
          <button
            type="submit"
            disabled={!text.trim()}
            className="rounded bg-slate-900 px-2 py-1 text-xs text-white hover:bg-slate-700 disabled:opacity-40"
          >
            Open
          </button>
          {error && <span className="text-xs text-red-600">{error}</span>}
        </form>
      )}
    </div>
  )
}
