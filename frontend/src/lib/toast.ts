// Lightweight toast queue (B14). Pure store — the <Toasts/> component
// subscribes; every fire-and-forget promise that used to reject silently
// routes its failure here so the user gets feedback.

export type ToastKind = 'error' | 'info' | 'success'

export interface Toast {
  id: number
  kind: ToastKind
  message: string
}

export interface ToastStore {
  push(message: string, kind?: ToastKind): number
  dismiss(id: number): void
  clear(): void
  getToasts(): Toast[]
  subscribe(listener: (toasts: Toast[]) => void): () => void
}

export const TOAST_MAX_VISIBLE = 4

export function createToastStore(maxVisible = TOAST_MAX_VISIBLE): ToastStore {
  let toasts: Toast[] = []
  let nextId = 1
  const listeners = new Set<(toasts: Toast[]) => void>()

  function emit() {
    for (const listener of listeners) listener(toasts)
  }

  return {
    push(message, kind = 'error') {
      const id = nextId++
      // Identical back-to-back messages collapse instead of stacking.
      const last = toasts[toasts.length - 1]
      if (last && last.message === message && last.kind === kind) return last.id
      toasts = [...toasts, { id, kind, message }].slice(-maxVisible)
      emit()
      return id
    },
    dismiss(id) {
      if (!toasts.some((t) => t.id === id)) return
      toasts = toasts.filter((t) => t.id !== id)
      emit()
    },
    clear() {
      if (toasts.length === 0) return
      toasts = []
      emit()
    },
    getToasts: () => toasts,
    subscribe(listener) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
  }
}

export const toastStore: ToastStore = createToastStore()

export function errorMessage(err: unknown, fallback = 'Something went wrong.'): string {
  if (err instanceof Error && err.message) return err.message
  if (typeof err === 'string' && err) return err
  return fallback
}

export function toastError(err: unknown, fallback?: string): number {
  return toastStore.push(errorMessage(err, fallback), 'error')
}

export function toastInfo(message: string): number {
  return toastStore.push(message, 'info')
}

export function toastSuccess(message: string): number {
  return toastStore.push(message, 'success')
}
