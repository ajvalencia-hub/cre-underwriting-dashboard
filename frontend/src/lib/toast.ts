// App-wide transient notices (saved files, failed actions). A tiny pub/sub
// so any module can raise one without prop-drilling; <Toaster/> renders them.

import { fileBrowserLabel, type SaveResult } from './platform'

export type ToastKind = 'success' | 'error' | 'info'

export interface ToastAction {
  label: string
  run: () => void
}

export interface Toast {
  id: number
  kind: ToastKind
  message: string
  detail?: string
  actions?: ToastAction[]
}

type Listener = (toasts: Toast[]) => void

let nextId = 1
let current: Toast[] = []
const listeners = new Set<Listener>()

function emit() {
  for (const l of listeners) l(current)
}

export function subscribeToasts(listener: Listener): () => void {
  listeners.add(listener)
  listener(current)
  return () => {
    listeners.delete(listener)
  }
}

export function dismissToast(id: number): void {
  current = current.filter((t) => t.id !== id)
  emit()
}

/** Errors stay until dismissed; everything else fades after `ms`. */
export function showToast(toast: Omit<Toast, 'id'>, ms = 6000): number {
  const id = nextId++
  current = [...current.slice(-3), { ...toast, id }]
  emit()
  if (toast.kind !== 'error') setTimeout(() => dismissToast(id), ms)
  return id
}

export function toastError(message: string, err?: unknown): number {
  const detail = err instanceof Error ? err.message : err === undefined ? undefined : String(err)
  return showToast({ kind: 'error', message, detail })
}

/** Standard confirmation after saveFile(): where the file went + actions. */
export function toastSaved(
  result: SaveResult,
  actions: { reveal: (path: string) => void; open: (path: string) => void },
): void {
  if (result.status === 'saved') {
    const name = result.path.split(/[\/]/).pop() ?? result.path
    showToast(
      {
        kind: 'success',
        message: `Saved ${name}`,
        detail: result.path,
        actions: [
          { label: 'Open', run: () => actions.open(result.path) },
          { label: `Show in ${fileBrowserLabel()}`, run: () => actions.reveal(result.path) },
        ],
      },
      10000,
    )
  }
}
