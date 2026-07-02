interface KeyValueRow {
  key: string
  value: string
}

interface KeyValueFieldProps {
  value: KeyValueRow[]
  onChange: (rows: KeyValueRow[]) => void
}

export default function KeyValueField({ value, onChange }: KeyValueFieldProps) {
  const rows = value ?? []

  function updateRow(idx: number, patch: Partial<KeyValueRow>) {
    onChange(rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)))
  }

  function addRow() {
    onChange([...rows, { key: '', value: '' }])
  }

  function removeRow(idx: number) {
    onChange(rows.filter((_, i) => i !== idx))
  }

  return (
    <div className="rounded border border-slate-200">
      {rows.map((row, idx) => (
        <div key={idx} className="flex items-center gap-2 border-b border-slate-100 p-2 last:border-b-0">
          <input
            className="w-1/2 rounded border border-slate-300 px-2 py-1 text-sm"
            placeholder="Key"
            value={row.key}
            onChange={(e) => updateRow(idx, { key: e.target.value })}
          />
          <input
            className="w-1/2 rounded border border-slate-300 px-2 py-1 text-sm"
            placeholder="Value"
            value={row.value}
            onChange={(e) => updateRow(idx, { value: e.target.value })}
          />
          <button
            type="button"
            onClick={() => removeRow(idx)}
            className="text-slate-400 hover:text-red-500"
            aria-label="Remove row"
          >
            ✕
          </button>
        </div>
      ))}
      {rows.length === 0 && <div className="p-2 text-xs text-slate-400">No custom inputs yet.</div>}
      <button
        type="button"
        onClick={addRow}
        className="w-full border-t border-slate-200 py-1 text-xs text-slate-500 hover:bg-slate-50"
      >
        + Add key/value
      </button>
    </div>
  )
}
