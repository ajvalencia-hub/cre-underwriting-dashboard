import { useState } from 'react'

interface SecretFieldProps {
  isSet: boolean
  last4: string | null | undefined
  onSave: (value: string) => Promise<void>
  onRevert: () => Promise<void>
  disabled?: boolean
}

/** M4: no existing masked-secret-input pattern anywhere in this frontend
 * (confirmed by an exhaustive grep before building this) — designed fresh.
 * Never pre-fills the actual secret; save is explicit (a button, never
 * on-blur/on-change) so a half-typed key can't get persisted by accident. */
export default function SecretField({ isSet, last4, onSave, onRevert, disabled }: SecretFieldProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  if (!editing) {
    return (
      <div className="flex items-center gap-2">
        <span className="font-mono text-sm text-slate-600">
          {isSet ? `••••${last4 ?? ''}` : 'Not set'}
        </span>
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            setDraft('')
            setEditing(true)
          }}
          className="text-xs text-slate-500 underline hover:text-slate-700 disabled:opacity-50"
        >
          {isSet ? 'Edit' : 'Set'}
        </button>
        {isSet && (
          <button
            type="button"
            disabled={disabled || busy}
            onClick={async () => {
              setBusy(true)
              try {
                await onRevert()
              } finally {
                setBusy(false)
              }
            }}
            className="text-xs text-slate-400 underline hover:text-slate-600 disabled:opacity-50"
          >
            Clear
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2">
      <input
        type="password"
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="Enter new value"
        className="rounded border border-slate-300 px-2 py-1 text-sm"
      />
      <button
        type="button"
        disabled={!draft || busy}
        onClick={async () => {
          setBusy(true)
          try {
            await onSave(draft)
            setEditing(false)
            setDraft('')
          } finally {
            setBusy(false)
          }
        }}
        className="rounded bg-slate-900 px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
      >
        Save
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          setEditing(false)
          setDraft('')
        }}
        className="text-xs text-slate-500 underline hover:text-slate-700"
      >
        Cancel
      </button>
    </div>
  )
}
