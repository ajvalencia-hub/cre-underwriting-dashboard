import { memo, useMemo, useState } from 'react'
import {
  computeQuickScreenSensitivityGrid,
  type QuickScreenInputs,
  type SensitivityGridMetric,
} from '../lib/quickScreenMath'
import { formatPct } from '../lib/quickScreenFormat'

interface QuickScreenSensitivityGridProps {
  inputs: QuickScreenInputs
  onApplyCell: (rentDeltaPct: number, exitCapDeltaBps: number) => void
}

const TIER_CELL_CLASS: Record<string, string> = {
  strong: 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100',
  marginal: 'bg-amber-50 text-amber-700 hover:bg-amber-100',
  weak: 'bg-red-50 text-red-700 hover:bg-red-100',
}

/** Memoised (Run 6 wave 2 perf): re-renders only when its inputs change. */
export default memo(function QuickScreenSensitivityGrid({ inputs, onApplyCell }: QuickScreenSensitivityGridProps) {
  const [metric, setMetric] = useState<SensitivityGridMetric>('spread')
  const grid = useMemo(() => computeQuickScreenSensitivityGrid(inputs, metric), [inputs, metric])

  return (
    <div className="rounded-md border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold tracking-wide text-slate-500">
          SENSITIVITY PREVIEW — RENT &times; EXIT CAP
        </div>
        <div className="flex gap-1 text-xs">
          {(['spread', 'yieldOnCost'] as SensitivityGridMetric[]).map((m) => (
            <button
              key={m}
              onClick={() => setMetric(m)}
              aria-pressed={metric === m}
              className={`rounded px-2 py-0.5 ${
                metric === m ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
              }`}
            >
              {m === 'spread' ? 'Spread' : 'Yield on Cost'}
            </button>
          ))}
        </div>
      </div>

      <table className="mt-3 w-full table-fixed border-collapse text-center text-xs">
        <thead>
          <tr>
            <th className="w-16 border border-slate-100 p-1 text-slate-400">Rent \ Cap</th>
            {grid[0].map((cell) => (
              <th key={cell.exitCapDeltaBps} className="border border-slate-100 p-1 font-normal text-slate-500">
                {cell.exitCapDeltaBps >= 0 ? '+' : ''}
                {cell.exitCapDeltaBps} bps
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {grid.map((row) => (
            <tr key={row[0].rentDeltaPct}>
              <td className="border border-slate-100 p-1 text-slate-500">
                {row[0].rentDeltaPct >= 0 ? '+' : ''}
                {(row[0].rentDeltaPct * 100).toFixed(0)}%
              </td>
              {row.map((cell) => (
                <td
                  key={cell.exitCapDeltaBps}
                  className={`border p-0 font-medium ${TIER_CELL_CLASS[cell.tier]} ${
                    cell.isCenter ? 'border-2 border-slate-900' : 'border-slate-100'
                  }`}
                >
                  {/* A real button (Run 6 a11y) filling the cell, so the grid is
                      keyboard-operable without changing how it looks. */}
                  <button
                    type="button"
                    onClick={() => onApplyCell(cell.rentDeltaPct, cell.exitCapDeltaBps)}
                    title="Click to apply this rent / exit cap pair to the inputs"
                    aria-label={`Apply rent ${cell.rentDeltaPct >= 0 ? '+' : ''}${(cell.rentDeltaPct * 100).toFixed(0)}% and exit cap ${cell.exitCapDeltaBps >= 0 ? '+' : ''}${cell.exitCapDeltaBps} bps (${formatPct(cell.value, 1)})`}
                    className="block w-full cursor-pointer p-1.5 font-medium"
                  >
                    {formatPct(cell.value, 1)}
                  </button>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-slate-400">
        Center cell (boxed) is the current inputs — click any cell to apply that rent / exit cap pair.
        A preview of the full Sensitivity tab, which sweeps the actual mapped template.
      </p>
    </div>
  )
})
