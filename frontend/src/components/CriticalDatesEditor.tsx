import { useRef, useState } from 'react'
import { useModalFocus } from '../lib/useModalFocus'
import {
  PRESETS_BY_TYPE,
  readCriticalDates,
  sortByDate,
  type CriticalDate,
} from '../lib/criticalDates'

interface CriticalDatesEditorProps {
  values: Record<string, unknown>
  /** Writes through the normal input-change path (autosave + history). */
  onChange: (rows: CriticalDate[]) => void
  onClose: () => void
}

/** J11: per-deal key dates CRUD. */
export default function CriticalDatesEditor({ values, onChange, onClose }: CriticalDatesEditorProps) {
  const [rows, setRows] = useState<CriticalDate[]>(() => sortByDate(readCriticalDates(values)))

  const dialogRef = useRef<HTMLDivElement>(null)
  useModalFocus(dialogRef, onClose)

  function commit(next: CriticalDate[]) {
    setRows(next)
    onChange(next)
  }

  function addRow(label: string) {
    commit([
      ...rows,
      { id: Math.random().toString(36).slice(2, 10), label, date: '', notes: '' },
    ])
  }

  function update(id: string, patch: Partial<CriticalDate>) {
    commit(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)))
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-6" onClick={onClose}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Critical dates"
        className="w-full max-w-2xl rounded-lg bg-white p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700">Critical dates</h2>
          <button onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-slate-600">✕</button>
        </div>
        <div className="flex flex-wrap gap-1 text-xs">
          {(values.dealType === 'development'
            ? PRESETS_BY_TYPE.development
            : PRESETS_BY_TYPE.acquisition
          ).map((label) => (
            <button
              key={label}
              onClick={() => addRow(label)}
              className="rounded border border-slate-300 px-2 py-0.5 text-slate-600 hover:bg-slate-50"
            >
              + {label}
            </button>
          ))}
          <button
            onClick={() => addRow('')}
            className="rounded border border-slate-300 px-2 py-0.5 text-slate-600 hover:bg-slate-50"
          >
            + custom
          </button>
        </div>
        {rows.length === 0 && (
          <p className="mt-3 text-xs text-slate-400">No dates yet — add one above.</p>
        )}
        {rows.map((row) => (
          <div key={row.id} className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            <input
              value={row.label}
              onChange={(e) => update(row.id, { label: e.target.value })}
              placeholder="label"
              className="w-44 rounded border border-slate-300 px-2 py-1"
            />
            <input
              type="date"
              value={row.date}
              onChange={(e) => update(row.id, { date: e.target.value })}
              className="rounded border border-slate-300 px-2 py-1"
            />
            <input
              value={row.notes ?? ''}
              onChange={(e) => update(row.id, { notes: e.target.value })}
              placeholder="notes"
              className="min-w-40 flex-1 rounded border border-slate-300 px-2 py-1"
            />
            <button
              onClick={() => commit(rows.filter((r) => r.id !== row.id))}
              className="text-slate-400 hover:text-red-500"
            >
              remove
            </button>
          </div>
        ))}
        <p className="mt-3 text-[11px] text-slate-400">
          Dates save with the deal (autosave + history) and appear on the pipeline
          deadline strip, the deal header, exports, and the HTML share.
        </p>
      </div>
    </div>
  )
}
