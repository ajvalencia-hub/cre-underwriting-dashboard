import { useMemo, useState } from 'react'
import {
  cellValue,
  groupIntoYears,
  monthColumns,
  rowTotal,
  statementRows,
  statementToCsv,
  type PeriodColumn,
  type Statement,
} from '../lib/cashflowStatement'

interface CashFlowTabProps {
  statement: Statement | null
  onGoToCompute: () => void
}

const PHASE_STYLE: Record<string, string> = {
  close: 'bg-slate-200 text-slate-600',
  construction: 'bg-amber-100 text-amber-700',
  lease_up: 'bg-sky-100 text-sky-700',
  stabilized: 'bg-emerald-100 text-emerald-700',
}

const PHASE_LABEL: Record<string, string> = {
  close: 'Close',
  construction: 'Construction',
  lease_up: 'Lease-up',
  stabilized: 'Stabilized',
}

function fmt(value: number): string {
  if (Math.abs(value) < 0.005) return '—'
  const rounded = Math.round(value)
  return rounded < 0 ? `(${Math.abs(rounded).toLocaleString()})` : rounded.toLocaleString()
}

function download(filename: string, text: string) {
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export default function CashFlowTab({ statement, onGoToCompute }: CashFlowTabProps) {
  const [expandedYears, setExpandedYears] = useState<Set<number>>(new Set())

  const columns = useMemo(() => {
    if (!statement) return []
    const result: PeriodColumn[] = []
    for (const yearColumn of groupIntoYears(statement)) {
      result.push(yearColumn)
      if (yearColumn.year !== null && expandedYears.has(yearColumn.year)) {
        result.push(...monthColumns(statement, yearColumn.year))
      }
    }
    return result
  }, [statement, expandedYears])

  if (!statement) {
    return (
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold">Cash Flow</h1>
        <p className="mt-2 text-sm text-slate-500">
          The period-level pro forma appears here after a native compute.
        </p>
        <button
          onClick={onGoToCompute}
          className="mt-3 rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700"
        >
          Go to Deal Inputs → Compute (native)
        </button>
      </div>
    )
  }

  const rows = statementRows(statement)

  function toggleYear(year: number | null) {
    if (year === null) return
    setExpandedYears((prev) => {
      const next = new Set(prev)
      if (next.has(year)) next.delete(year)
      else next.add(year)
      return next
    })
  }

  return (
    <div>
      <div className="mb-3 flex items-center gap-3">
        <h1 className="text-2xl font-semibold">Cash Flow</h1>
        <span className="text-xs text-slate-400">
          Click a year header to expand its months.
        </span>
        <div className="ml-auto flex gap-2">
          <button
            onClick={() => download('cashflow-annual.csv', statementToCsv(statement, 'annual'))}
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
          >
            Export annual CSV
          </button>
          <button
            onClick={() => download('cashflow-monthly.csv', statementToCsv(statement, 'monthly'))}
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
          >
            Export monthly CSV
          </button>
        </div>
      </div>

      <div className="overflow-x-auto rounded border border-slate-200 bg-white">
        <table className="text-xs" style={{ borderCollapse: 'separate', borderSpacing: 0 }}>
          <thead>
            {/* Phase band */}
            <tr>
              <th className="sticky left-0 z-10 border-b border-slate-200 bg-white px-3 py-1 text-left font-medium text-slate-400">
                Phase
              </th>
              {columns.map((column, i) => (
                <th
                  key={`phase-${i}`}
                  className={`border-b border-slate-200 px-2 py-1 text-center text-[10px] font-medium ${
                    PHASE_STYLE[column.phase] ?? ''
                  }`}
                >
                  {PHASE_LABEL[column.phase] ?? column.phase}
                </th>
              ))}
              <th className="border-b border-slate-200 px-2 py-1" />
            </tr>
            <tr>
              <th className="sticky left-0 z-10 border-b border-slate-300 bg-white px-3 py-1.5 text-left font-semibold text-slate-600">
                Line item
              </th>
              {columns.map((column, i) => (
                <th
                  key={`hdr-${i}`}
                  onClick={() => toggleYear(column.year)}
                  className={`whitespace-nowrap border-b border-slate-300 px-2 py-1.5 text-right font-semibold text-slate-600 ${
                    column.year !== null && column.indices.length > 1
                      ? 'cursor-pointer hover:bg-slate-50'
                      : ''
                  }`}
                  title={
                    column.year !== null && column.indices.length > 1
                      ? 'Toggle months'
                      : undefined
                  }
                >
                  {column.label}
                  {column.year !== null && column.indices.length > 1 && (
                    <span className="ml-1 text-slate-300">
                      {expandedYears.has(column.year) ? '▾' : '▸'}
                    </span>
                  )}
                </th>
              ))}
              <th className="whitespace-nowrap border-b border-slate-300 px-2 py-1.5 text-right font-semibold text-slate-600">
                Total
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const total = rowTotal(row, statement)
              const emphasize = ['egi', 'noi', 'levered', 'opexTotal'].includes(row.key)
              return (
                <tr key={row.key} className={emphasize ? 'bg-slate-50 font-medium' : ''}>
                  <td
                    className={`sticky left-0 z-10 whitespace-nowrap border-b border-slate-100 px-3 py-1 text-slate-600 ${
                      emphasize ? 'bg-slate-50' : 'bg-white'
                    } ${row.indent ? 'pl-6' : ''}`}
                  >
                    {row.label}
                  </td>
                  {columns.map((column, i) => (
                    <td
                      key={i}
                      className="whitespace-nowrap border-b border-slate-100 px-2 py-1 text-right tabular-nums text-slate-700"
                    >
                      {fmt(cellValue(row, statement, column))}
                    </td>
                  ))}
                  <td className="whitespace-nowrap border-b border-slate-100 px-2 py-1 text-right font-medium tabular-nums text-slate-800">
                    {total === null ? '—' : fmt(total)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
