import { useEffect, useState } from 'react'
import { dismissToast, subscribeToasts, type Toast } from '../lib/toast'

const KIND_CLASS: Record<Toast['kind'], string> = {
  success: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  error: 'border-red-200 bg-red-50 text-red-700',
  info: 'border-sky-200 bg-sky-50 text-sky-700',
}

/** Bottom-right stack of notices raised via lib/toast. z-[60] sits above the
 *  z-50 modal layer so a failure inside a modal flow is still visible. */
export default function Toaster() {
  const [toasts, setToasts] = useState<Toast[]>([])
  useEffect(() => subscribeToasts(setToasts), [])

  if (toasts.length === 0) return null
  return (
    <div className="fixed right-4 bottom-4 z-[60] flex w-96 flex-col gap-2" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`rounded-md border px-3 py-2 text-sm shadow-sm ${KIND_CLASS[t.kind]}`}>
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="font-medium">{t.message}</div>
              {t.detail && <div className="mt-0.5 text-xs break-words opacity-90">{t.detail}</div>}
            </div>
            <button
              onClick={() => dismissToast(t.id)}
              className="shrink-0 text-xs opacity-70 hover:opacity-100"
              aria-label="Dismiss"
            >
              ✕
            </button>
          </div>
          {t.actions && t.actions.length > 0 && (
            <div className="mt-1.5 flex gap-3 text-xs">
              {t.actions.map((a) => (
                <button
                  key={a.label}
                  onClick={() => {
                    a.run()
                    dismissToast(t.id)
                  }}
                  className="font-medium underline"
                >
                  {a.label}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
