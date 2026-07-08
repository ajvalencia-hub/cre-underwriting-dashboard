import { useState } from 'react'
import type { SettingEntry } from '../../types/settings'
import SecretField from './SecretField'

interface SettingRowProps {
  entry: SettingEntry
  onSave: (key: string, value: string) => Promise<void>
  onRevert: (key: string) => Promise<void>
  helperText?: string
}

const SOURCE_LABEL: Record<SettingEntry['source'], string> = {
  db: 'custom',
  env: 'from .env',
  default: 'default',
}

/** Non-secret fields: a plain text input, explicit Save button (never
 * on-blur) to match SecretField's "nothing persists until you say so"
 * convention. Secret fields delegate to SecretField entirely. */
export default function SettingRow({ entry, onSave, onRevert, helperText }: SettingRowProps) {
  const [draft, setDraft] = useState(entry.value ?? '')
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 py-2 last:border-b-0">
      <div>
        <div className="text-sm text-slate-700">{entry.label}</div>
        {helperText && <div className="text-xs text-slate-400">{helperText}</div>}
      </div>
      <div className="flex items-center gap-2">
        {entry.isSecret ? (
          <SecretField
            isSet={entry.isSet ?? false}
            last4={entry.last4}
            onSave={(value) => onSave(entry.key, value)}
            onRevert={() => onRevert(entry.key)}
          />
        ) : (
          <>
            <input
              type="text"
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value)
                setDirty(true)
              }}
              className="rounded border border-slate-300 px-2 py-1 text-sm"
            />
            <span className="text-xs text-slate-400">{SOURCE_LABEL[entry.source]}</span>
            <button
              type="button"
              disabled={!dirty || busy}
              onClick={async () => {
                setBusy(true)
                try {
                  await onSave(entry.key, draft)
                  setDirty(false)
                } finally {
                  setBusy(false)
                }
              }}
              className="rounded bg-slate-900 px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
            >
              Save
            </button>
            {entry.source === 'db' && (
              <button
                type="button"
                disabled={busy}
                onClick={async () => {
                  setBusy(true)
                  try {
                    await onRevert(entry.key)
                    setDirty(false)
                  } finally {
                    setBusy(false)
                  }
                }}
                className="text-xs text-slate-400 underline hover:text-slate-600 disabled:opacity-50"
              >
                Revert
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
