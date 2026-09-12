import { useEffect, useSyncExternalStore } from 'react'
import { toastStore, type Toast } from '../lib/toast'

const AUTO_DISMISS_MS = 6000

const KIND_CLASS: Record<Toast['kind'], string> = {
  error: 'border-red-200 bg-red-50 text-red-700',
  info: 'border-slate-200 bg-white text-slate-700',
  success: 'border-emerald-200 bg-emerald-50 text-emerald-700',
}

function ToastItem({ toast }: { toast: Toast }) {
  useEffect(() => {
    const handle = setTimeout(() => toastStore.dismiss(toast.id), AUTO_DISMISS_MS)
    return () => clearTimeout(handle)
  }, [toast.id])
  return (
    <div
      role={toast.kind === 'error' ? 'alert' : 'status'}
      className={`pointer-events-auto flex items-start gap-2 rounded border px-3 py-2 text-xs shadow-md ${KIND_CLASS[toast.kind]}`}
    >
      <span className="flex-1">{toast.message}</span>
      <button
        onClick={() => toastStore.dismiss(toast.id)}
        aria-label="Dismiss notification"
        className="opacity-60 hover:opacity-100"
      >
        ✕
      </button>
    </div>
  )
}

/** B14: single toast host, rendered once in App. */
export default function Toasts() {
  const toasts = useSyncExternalStore(toastStore.subscribe, toastStore.getToasts, toastStore.getToasts)
  if (toasts.length === 0) return null
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 max-w-[90vw] flex-col gap-2"
    >
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} />
      ))}
    </div>
  )
}
