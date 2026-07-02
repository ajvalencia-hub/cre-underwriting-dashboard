import type { InputField } from '../../types/schema'
import ScalarInput from './ScalarInput'

type Row = Record<string, unknown>

interface TableFieldProps {
  field: InputField
  value: Row[]
  onChange: (rows: Row[]) => void
}

export default function TableField({ field, value, onChange }: TableFieldProps) {
  const columns = field.columns ?? []
  const rows = value ?? []

  function updateCell(rowIdx: number, colId: string, cellValue: unknown) {
    onChange(rows.map((r, i) => (i === rowIdx ? { ...r, [colId]: cellValue } : r)))
  }

  function addRow() {
    if (field.maxRows && rows.length >= field.maxRows) return
    onChange([...rows, {}])
  }

  function removeRow(idx: number) {
    if (field.minRows && rows.length <= field.minRows) return
    onChange(rows.filter((_, i) => i !== idx))
  }

  return (
    <div className="overflow-x-auto rounded border border-slate-200">
      <table className="w-full text-xs">
        <thead className="bg-slate-50">
          <tr>
            {columns.map((c) => (
              <th key={c.id} className="whitespace-nowrap px-2 py-1 text-left font-medium">
                {c.label}
              </th>
            ))}
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rIdx) => (
            <tr key={rIdx} className="border-t border-slate-100">
              {columns.map((c) => (
                <td key={c.id} className="min-w-[7rem] px-2 py-1">
                  <ScalarInput
                    type={c.type}
                    value={row[c.id]}
                    options={c.options}
                    onChange={(v) => updateCell(rIdx, c.id, v)}
                  />
                </td>
              ))}
              <td className="px-2 py-1">
                <button
                  type="button"
                  onClick={() => removeRow(rIdx)}
                  className="text-slate-400 hover:text-red-500"
                  aria-label="Remove row"
                >
                  ✕
                </button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length + 1} className="px-2 py-2 text-slate-400">
                No rows yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <button
        type="button"
        onClick={addRow}
        className="w-full border-t border-slate-200 py-1 text-xs text-slate-500 hover:bg-slate-50"
      >
        + Add row
      </button>
    </div>
  )
}
