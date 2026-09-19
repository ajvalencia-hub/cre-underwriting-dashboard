import { useState } from 'react'
import type { ExternalToolsStatus, IntegrationStatus } from '../lib/api'
import { desktopApi, openExternal, type DesktopSettings } from '../lib/platform'
import { toastError } from '../lib/toast'

const LIBREOFFICE_DOWNLOAD = 'https://www.libreoffice.org/download/download-libreoffice/'
const TESSERACT_INFO = 'https://tesseract-ocr.github.io/tessdoc/Installation.html'

export function RestartBanner({ settings }: { settings: DesktopSettings | null }) {
  if (!settings?.restartNeeded) return null
  return (
    <div className="flex items-center justify-between rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
      <span>Changes take effect after the app restarts. Your deals are saved.</span>
      <button
        onClick={() => void desktopApi()?.restart()}
        className="rounded border border-amber-400 px-2 py-0.5 font-medium hover:bg-amber-100"
      >
        Restart now
      </button>
    </div>
  )
}

/** One integration row with a Keychain-backed key field (desktop app). */
export function KeychainKeyRow({
  item,
  stored,
  onSettings,
}: {
  item: IntegrationStatus
  stored: boolean
  onSettings: (s: DesktopSettings) => void
}) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  async function save(value: string) {
    const api = desktopApi()
    if (!api) return
    setBusy(true)
    try {
      const result = await api.set_api_key(item.envVar, value)
      if ('error' in result) toastError(`Couldn't update ${item.label}`, result.error)
      else {
        onSettings(result)
        setDraft('')
      }
    } finally {
      setBusy(false)
    }
  }

  // "configured" = active in the running backend; "stored" = in the Keychain
  // (which is what the next launch will use).
  const status = stored
    ? item.configured
      ? { text: 'saved in Keychain', cls: 'text-emerald-600' }
      : { text: 'saved — restart to apply', cls: 'text-amber-600' }
    : item.configured
      ? { text: 'removed — restart to apply', cls: 'text-amber-600' }
      : { text: 'not set', cls: 'text-slate-400' }

  return (
    <li className="text-xs">
      <div className="flex items-start gap-2">
        <span
          aria-hidden
          className={`mt-0.5 inline-block h-2 w-2 shrink-0 rounded-full ${stored ? 'bg-emerald-500' : 'bg-slate-300'}`}
        />
        <div className="min-w-0 flex-1">
          <span className="font-medium text-slate-700">{item.label}</span>{' '}
          <span className={status.cls}>{status.text}</span>
          <div className="text-slate-500">{item.purpose}</div>
          <form
            className="mt-1 flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (draft.trim()) void save(draft)
            }}
          >
            <label className="sr-only" htmlFor={`key-${item.envVar}`}>
              {item.label} key
            </label>
            <input
              id={`key-${item.envVar}`}
              type="password"
              autoComplete="off"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={stored ? 'Enter a new key to replace it' : 'Paste key'}
              className="w-72 rounded border border-slate-300 px-2 py-0.5"
            />
            <button
              type="submit"
              disabled={busy || !draft.trim()}
              className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50 disabled:opacity-40"
            >
              Save
            </button>
            {stored && (
              <button
                type="button"
                disabled={busy}
                onClick={() => void save('')}
                className="rounded border border-slate-300 px-2 py-0.5 text-red-600 hover:bg-red-50 disabled:opacity-40"
              >
                Remove
              </button>
            )}
          </form>
        </div>
      </div>
    </li>
  )
}

/** LibreOffice / OCR status — shown in the browser too, since both setups need them. */
export function ExternalToolsPanel({
  tools,
  settings,
  onSettings,
}: {
  tools: ExternalToolsStatus | null
  settings: DesktopSettings | null
  onSettings: (s: DesktopSettings) => void
}) {
  const api = desktopApi()
  if (tools === null) return <div className="text-xs text-slate-400">Status unavailable.</div>

  return (
    <div className="space-y-3 text-xs">
      <ToolRow
        name="LibreOffice"
        available={tools.libreoffice.available}
        detail={tools.libreoffice.available ? tools.libreoffice.path : null}
        enables={tools.libreoffice.enables}
        missingNote="Without it, generated workbooks are still correct when opened in Excel, but the app can't show your template's own results. The built-in engine is unaffected."
        installLabel="Download LibreOffice (free)"
        installUrl={LIBREOFFICE_DOWNLOAD}
      />
      <ToolRow
        name="OCR (Tesseract + Poppler)"
        available={tools.ocr.available}
        detail={null}
        enables={tools.ocr.enables}
        missingNote="Text-based PDFs, Excel and CSV documents work without it."
        installLabel="Installation guide"
        installUrl={TESSERACT_INFO}
      />
      {api && settings && (
        <div className="border-t border-slate-100 pt-2 text-slate-500">
          Installed somewhere unusual?{' '}
          {settings.extraToolDir ? (
            <>
              Also searching <span className="font-mono">{settings.extraToolDir}</span>{' '}
              <button
                className="text-sky-600 hover:underline"
                onClick={() => void api.clear_tool_folder().then(onSettings)}
              >
                Clear
              </button>
            </>
          ) : (
            <button
              className="text-sky-600 hover:underline"
              onClick={() => void api.choose_tool_folder().then(onSettings)}
            >
              Choose the application or folder…
            </button>
          )}
        </div>
      )}
    </div>
  )
}

function ToolRow({
  name,
  available,
  detail,
  enables,
  missingNote,
  installLabel,
  installUrl,
}: {
  name: string
  available: boolean
  detail: string | null
  enables: string[]
  missingNote: string
  installLabel: string
  installUrl: string
}) {
  return (
    <div className="flex items-start gap-2">
      <span
        aria-hidden
        className={`mt-0.5 inline-block h-2 w-2 shrink-0 rounded-full ${available ? 'bg-emerald-500' : 'bg-amber-500'}`}
      />
      <div>
        <span className="font-medium text-slate-700">{name}</span>{' '}
        <span className={available ? 'text-emerald-600' : 'text-amber-600'}>
          {available ? 'installed' : 'not installed (optional)'}
        </span>
        {detail && <span className="ml-1 font-mono text-[10px] text-slate-400">{detail}</span>}
        <div className="text-slate-500">Needed for: {enables.join('; ')}.</div>
        {!available && (
          <div className="mt-0.5 text-slate-500">
            {missingNote}{' '}
            <button className="text-sky-600 hover:underline" onClick={() => openExternal(installUrl)}>
              {installLabel}
            </button>
            , then restart this app.
          </div>
        )}
      </div>
    </div>
  )
}
