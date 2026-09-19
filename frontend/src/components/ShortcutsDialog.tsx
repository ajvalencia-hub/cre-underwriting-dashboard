import { useRef } from 'react'
import { useModalFocus } from '../lib/useModalFocus'

interface ShortcutsDialogProps {
  onClose: () => void
}

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
const MOD = isMac ? '⌘' : 'Ctrl'

/** Every keyboard shortcut the app has — opened from the ⌘K palette's
 *  "Keyboard shortcuts" action. Keep in sync with App's keydown effect,
 *  CommandPalette and useModalFocus. */
const SHORTCUTS: { keys: string; what: string }[] = [
  { keys: `${MOD} K`, what: 'Open the command palette — actions, tabs, fields, recent deals, search' },
  { keys: `${MOD} ↩`, what: 'Compute with the inputs on screen' },
  { keys: '↑ ↓  ↩', what: 'In the palette: move and run the highlighted row' },
  { keys: 'Esc', what: 'Close the palette, a dialog or an open menu' },
  { keys: 'Tab / Shift Tab', what: 'Move between fields (stays inside an open dialog)' },
]

export default function ShortcutsDialog({ onClose }: ShortcutsDialogProps) {
  const ref = useRef<HTMLDivElement>(null)
  useModalFocus(ref, onClose)
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/40 pt-24" onClick={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 id="shortcuts-title" className="text-sm font-semibold text-slate-800">
            Keyboard shortcuts
          </h2>
          <button onClick={onClose} aria-label="Close" className="px-1 text-slate-400 hover:text-slate-700">
            ×
          </button>
        </div>
        <dl className="mt-3 space-y-2">
          {SHORTCUTS.map((s) => (
            <div key={s.keys} className="flex items-start gap-3 text-sm">
              <dt className="w-32 shrink-0">
                <kbd className="rounded border border-slate-200 px-1.5 py-0.5 text-[11px] text-slate-600">{s.keys}</kbd>
              </dt>
              <dd className="text-slate-600">{s.what}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}
