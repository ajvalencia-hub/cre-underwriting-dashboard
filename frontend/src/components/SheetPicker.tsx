import { useEffect, useRef, useState } from 'react'
import { fetchSheetGrid } from '../lib/api'
import { formatCellValue } from '../lib/mappingCoverage'
import type { SheetGrid, SheetMeta } from '../types/template'

const WINDOW_ROWS = 60
const WINDOW_COLS = 30

interface SheetPickerProps {
  templateId: string
  sheets: SheetMeta[]
  /** Label of the field being mapped; null = browsing only. */
  pickingLabel: string | null
  /** "Sheet!A1" -> field label, for cells that are already mapped. */
  mappedCells: Map<string, string>
  /** Jump here when it changes (e.g. "show me where this field lands"). */
  focusRef: string | null
  onPick: (sheet: string, cellRef: string, isFormula: boolean) => void
  onCancel: () => void
  onClose: () => void
}

function splitRef(ref: string): { sheet: string | null; cell: string } {
  const bang = ref.lastIndexOf('!')
  return bang >= 0 ? { sheet: ref.slice(0, bang).replace(/^'|'$/g, ''), cell: ref.slice(bang + 1) } : { sheet: null, cell: ref }
}

function rowOf(cell: string): number | null {
  const m = cell.replace(/\$/g, '').match(/^[A-Za-z]{1,3}(\d+)$/)
  return m ? Number(m[1]) : null
}

/** A window onto one sheet of the template for picking a target cell. */
export default function SheetPicker({
  templateId,
  sheets,
  pickingLabel,
  mappedCells,
  focusRef,
  onPick,
  onCancel,
  onClose,
}: SheetPickerProps) {
  const [sheet, setSheet] = useState(sheets[0]?.name ?? '')
  const [startRow, setStartRow] = useState(1)
  const [grid, setGrid] = useState<SheetGrid | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [goTo, setGoTo] = useState('')
  const [target, setTarget] = useState<string | null>(null) // "Sheet!A1" to outline
  const requestId = useRef(0)

  useEffect(() => {
    if (!sheet) return
    const id = ++requestId.current
    setLoading(true)
    setError(null)
    fetchSheetGrid(templateId, sheet, WINDOW_ROWS, WINDOW_COLS, startRow)
      .then((g) => {
        if (id === requestId.current) setGrid(g)
      })
      .catch((err) => {
        if (id === requestId.current) setError(err instanceof Error ? err.message : 'Could not load the sheet')
      })
      .finally(() => {
        if (id === requestId.current) setLoading(false)
      })
  }, [templateId, sheet, startRow])

  function jumpTo(ref: string): boolean {
    const { sheet: refSheet, cell } = splitRef(ref.trim())
    const row = rowOf(cell)
    const nextSheet = refSheet ?? sheet
    if (row === null || !sheets.some((s) => s.name === nextSheet)) return false
    setSheet(nextSheet)
    setStartRow(Math.max(1, row - 5))
    setTarget(`${nextSheet}!${cell.replace(/\$/g, '').toUpperCase()}`)
    return true
  }

  useEffect(() => {
    if (focusRef) jumpTo(focusRef)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRef])

  const sheetMeta = sheets.find((s) => s.name === sheet)
  const totalRows = grid?.totalRows ?? sheetMeta?.maxRow ?? 0
  const firstRow = grid?.startRow ?? startRow
  const lastRow = grid ? firstRow + grid.rows.length - 1 : firstRow

  return (
    <div className="rounded-md border border-slate-300 bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-2 text-sm">
        {pickingLabel ? (
          <span className="rounded bg-indigo-100 px-2 py-0.5 text-indigo-700">
            Click the cell for <strong>{pickingLabel}</strong>
          </span>
        ) : (
          <span className="text-slate-500">Template preview</span>
        )}
        <label className="sr-only" htmlFor="picker-sheet">
          Sheet
        </label>
        <select
          id="picker-sheet"
          value={sheet}
          onChange={(e) => {
            setSheet(e.target.value)
            setStartRow(1)
            setTarget(null)
          }}
          className="rounded border border-slate-300 px-2 py-0.5 text-sm"
        >
          {sheets.map((s) => (
            <option key={s.name} value={s.name}>
              {s.name}
            </option>
          ))}
        </select>
        <form
          className="flex items-center gap-1"
          onSubmit={(e) => {
            e.preventDefault()
            if (jumpTo(goTo)) setGoTo('')
            else setError(`"${goTo}" isn't a cell reference like B12 or Assumptions!C7`)
          }}
        >
          <label className="sr-only" htmlFor="picker-goto">
            Go to cell
          </label>
          <input
            id="picker-goto"
            value={goTo}
            onChange={(e) => setGoTo(e.target.value)}
            placeholder="Go to cell, e.g. C120"
            className="w-40 rounded border border-slate-300 px-2 py-0.5 text-sm"
          />
        </form>
        <div className="ml-auto flex items-center gap-2 text-xs text-slate-500">
          <span>
            Rows {firstRow}–{lastRow} of {totalRows}
          </span>
          <button
            disabled={firstRow <= 1 || loading}
            onClick={() => setStartRow(Math.max(1, firstRow - WINDOW_ROWS))}
            className="rounded border border-slate-300 px-1.5 hover:bg-slate-50 disabled:opacity-40"
            aria-label="Previous rows"
          >
            ↑
          </button>
          <button
            disabled={lastRow >= totalRows || loading}
            onClick={() => setStartRow(firstRow + WINDOW_ROWS)}
            className="rounded border border-slate-300 px-1.5 hover:bg-slate-50 disabled:opacity-40"
            aria-label="Next rows"
          >
            ↓
          </button>
          {pickingLabel ? (
            <button onClick={onCancel} className="rounded border border-slate-300 px-2 hover:bg-slate-50">
              Cancel
            </button>
          ) : (
            <button onClick={onClose} className="rounded border border-slate-300 px-2 hover:bg-slate-50">
              Close
            </button>
          )}
        </div>
      </div>
      {error && <div className="px-3 py-1.5 text-xs text-red-600">{error}</div>}
      <div className="max-h-80 overflow-auto">
        {grid && (
          <table className="border-collapse text-xs">
            <thead className="sticky top-0 bg-slate-100">
              <tr>
                <th className="border border-slate-200 px-2 py-1"></th>
                {grid.columns.map((c) => (
                  <th key={c} className="border border-slate-200 px-2 py-1 font-medium">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className={loading ? 'opacity-50' : ''}>
              {grid.rows.map((row, rIdx) => (
                <tr key={firstRow + rIdx}>
                  <td className="border border-slate-200 bg-slate-50 px-2 py-1 font-medium text-slate-400">
                    {firstRow + rIdx}
                  </td>
                  {row.map((cell) => {
                    const fullRef = `${grid.sheet}!${cell.ref}`
                    const mappedTo = mappedCells.get(fullRef)
                    const isTarget = target === fullRef
                    return (
                      <td
                        key={cell.ref}
                        title={
                          `${cell.ref}` +
                          (cell.isFormula ? ` — formula ${String(cell.value)} (values can't be written here)` : '') +
                          (mappedTo ? ` — mapped: ${mappedTo}` : '')
                        }
                        onClick={() => pickingLabel && onPick(grid.sheet, cell.ref, cell.isFormula)}
                        className={`border border-slate-200 px-2 py-1 whitespace-nowrap ${
                          cell.isFormula ? 'bg-amber-50 text-amber-700' : ''
                        } ${mappedTo ? 'font-medium text-indigo-700 outline outline-1 outline-indigo-300' : ''} ${
                          isTarget ? 'outline outline-2 outline-indigo-500' : ''
                        } ${pickingLabel ? 'cursor-pointer hover:bg-indigo-100' : ''}`}
                      >
                        {cell.value === null
                          ? ''
                          : cell.isFormula
                            ? `ƒ ${String(cell.value).slice(0, 24)}`
                            : formatCellValue(cell.value, cell.numberFormat)}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {!grid && loading && <div className="px-3 py-6 text-center text-sm text-slate-400">Loading sheet…</div>}
      </div>
      <div className="border-t border-slate-200 bg-slate-50 px-3 py-1 text-[11px] text-slate-500">
        Amber ƒ cells are formulas (values are never written there) · outlined cells are already mapped · hover a
        cell for details
      </div>
    </div>
  )
}
