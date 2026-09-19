import { useId, useState, type ReactNode } from 'react'
import { useElementWidth } from './hooks'
import { Legend } from './Legend'
import type { ChartTable, LegendItem } from './types'

export interface ChartFrameProps {
  title: string
  subtitle?: ReactNode
  /** Pass only for ≥2 series (a single series is named by the title). */
  legend?: LegendItem[]
  /** The accessible table twin (always provide it). */
  table: ChartTable
  /** Render the quiet empty state instead of the chart. */
  empty?: boolean
  emptyMessage?: string
  className?: string
  /** Receives the measured content width (px). */
  children: (width: number) => ReactNode
}

/** Shared wrapper: title, subtitle, legend, the "Show table" toggle and the
 *  empty state. Place it on the card surface (bg-white) — marks' surface
 *  gaps/rings use --viz-surface. */
export function ChartFrame({
  title,
  subtitle,
  legend,
  table,
  empty = false,
  emptyMessage = 'Not enough data to chart.',
  className = '',
  children,
}: ChartFrameProps) {
  const [ref, width] = useElementWidth<HTMLDivElement>()
  const [showTable, setShowTable] = useState(false)
  const tableId = useId()
  return (
    <figure className={`m-0 min-w-0 ${className}`}>
      <figcaption>
        <div className="text-sm font-semibold text-viz-secondary">{title}</div>
        {subtitle && <div className="mt-0.5 text-xs text-viz-muted">{subtitle}</div>}
      </figcaption>
      {empty ? (
        <div className="mt-2 flex min-h-16 items-center text-xs text-viz-muted">{emptyMessage}</div>
      ) : (
        <>
          {legend && legend.length > 0 && <Legend items={legend} className="mt-2" />}
          <div ref={ref} className="mt-2 w-full min-w-0">
            {children(width)}
          </div>
          <button
            type="button"
            className="mt-1 text-xs text-viz-muted underline-offset-2 hover:underline"
            aria-expanded={showTable}
            aria-controls={tableId}
            onClick={() => setShowTable((v) => !v)}
          >
            {showTable ? 'Hide table' : 'Show table'}
          </button>
          <div id={tableId} hidden={!showTable} className="mt-1 max-h-72 overflow-auto">
            {showTable && <DataTable caption={title} table={table} />}
          </div>
        </>
      )}
    </figure>
  )
}

/** Plain accessible table: first column is the row header. */
export function DataTable({ caption, table }: { caption: string; table: ChartTable }) {
  return (
    <table className="w-full border-collapse text-xs">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr className="border-b border-slate-200 text-left">
          {table.columns.map((c, i) => (
            <th key={i} scope="col" className={`px-2 py-1 font-medium text-viz-muted ${i > 0 ? 'text-right' : ''}`}>
              {c}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {table.rows.map((row, r) => (
          <tr key={r} className="border-b border-slate-100">
            {row.map((cell, i) =>
              i === 0 ? (
                <th key={i} scope="row" className="px-2 py-1 text-left font-normal text-viz-secondary">
                  {cell}
                </th>
              ) : (
                <td key={i} className="viz-tabular px-2 py-1 text-right text-viz-primary">
                  {cell}
                </td>
              ),
            )}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
