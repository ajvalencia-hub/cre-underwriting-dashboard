import { useMemo, useState } from 'react'
import { fetchHoldSweep, type HoldSweepResponse } from '../lib/api'
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
  /** Current deal-input values — the hold sweep re-evaluates them per exit year. */
  values: Record<string, unknown>
  onGoToCompute: () => void
}

const pct = (v: number | null | undefined) => (v == null ? '—' : `${(v * 100).toFixed(2)}%`)
const mult = (v: number | null | undefined) => (v == null ? '—' : `${v.toFixed(2)}x`)
const money = (v: number | null | undefined) =>
  v == null ? '—' : `$${Math.round(v).toLocaleString()}`

function HoldSweepChart({ response }: { response: HoldSweepResponse }) {
  const rows = response.sweep.rows
  if (rows.length === 0) return null
  const width = 560
  const height = 180
  const pad = { left: 46, right: 46, top: 10, bottom: 22 }
  const plotW = width - pad.left - pad.right
  const plotH = height - pad.top - pad.bottom

  const years = rows.map((r) => r.holdYear)
  const xFor = (year: number) =>
    pad.left +
    (years.length === 1 ? plotW / 2 : ((year - years[0]) / (years[years.length - 1] - years[0])) * plotW)

  const irrValues = rows.flatMap((r) =>
    [r.leveredIrr, r.unleveredIrr].filter((v): v is number => v != null),
  )
  const emValues = rows.map((r) => r.equityMultiple).filter((v): v is number => v != null)
  const irrMin = Math.min(...irrValues, 0)
  const irrMax = Math.max(...irrValues, 0.01)
  const emMin = Math.min(...emValues, 1)
  const emMax = Math.max(...emValues, 1.01)
  const yIrr = (v: number) => pad.top + plotH - ((v - irrMin) / (irrMax - irrMin)) * plotH
  const yEm = (v: number) => pad.top + plotH - ((v - emMin) / (emMax - emMin)) * plotH

  const path = (values: (number | null)[], y: (v: number) => number) =>
    rows
      .map((r, i) => {
        const v = values[i]
        return v == null ? null : `${i === 0 || values[i - 1] == null ? 'M' : 'L'}${xFor(r.holdYear)},${y(v)}`
      })
      .filter(Boolean)
      .join(' ')

  const modeled = response.sweep.modeledHoldYears
  return (
    <svg width={width} height={height} role="img" aria-label="Hold sweep chart">
      {/* modeled hold marker */}
      {modeled >= years[0] && modeled <= years[years.length - 1] && (
        <line
          x1={xFor(modeled)}
          y1={pad.top}
          x2={xFor(modeled)}
          y2={pad.top + plotH}
          stroke="#f59e0b"
          strokeDasharray="4 3"
        />
      )}
      <path d={path(rows.map((r) => r.leveredIrr), yIrr)} fill="none" stroke="#0284c7" strokeWidth={2} />
      <path d={path(rows.map((r) => r.unleveredIrr), yIrr)} fill="none" stroke="#94a3b8" strokeWidth={1.5} />
      <path d={path(rows.map((r) => r.equityMultiple), yEm)} fill="none" stroke="#059669" strokeWidth={1.5} strokeDasharray="5 3" />
      {rows.map((r) => (
        <g key={r.holdYear}>
          {r.leveredIrr != null && <circle cx={xFor(r.holdYear)} cy={yIrr(r.leveredIrr)} r={2.5} fill="#0284c7" />}
          <text x={xFor(r.holdYear)} y={height - 6} fontSize={10} fill="#64748b" textAnchor="middle">
            Y{r.holdYear}
          </text>
        </g>
      ))}
      <text x={2} y={pad.top + 8} fontSize={9} fill="#0284c7">
        IRR {pct(irrMax)}
      </text>
      <text x={2} y={pad.top + plotH} fontSize={9} fill="#0284c7">
        {pct(irrMin)}
      </text>
      <text x={width - 2} y={pad.top + 8} fontSize={9} fill="#059669" textAnchor="end">
        {mult(emMax)}
      </text>
      <text x={width - 2} y={pad.top + plotH} fontSize={9} fill="#059669" textAnchor="end">
        {mult(emMin)}
      </text>
    </svg>
  )
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

export default function CashFlowTab({ statement, values, onGoToCompute }: CashFlowTabProps) {
  const [expandedYears, setExpandedYears] = useState<Set<number>>(new Set())
  const [holdSweep, setHoldSweep] = useState<HoldSweepResponse | null>(null)
  const [holdBusy, setHoldBusy] = useState(false)
  const [holdError, setHoldError] = useState<string | null>(null)

  async function handleRunHoldSweep() {
    setHoldBusy(true)
    setHoldError(null)
    try {
      setHoldSweep(await fetchHoldSweep(values))
    } catch (err) {
      setHoldError(err instanceof Error ? err.message : 'Hold sweep failed')
    } finally {
      setHoldBusy(false)
    }
  }

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

      {statement.leases && (
        <div className="mt-4 rounded border border-slate-200 bg-white p-3">
          <div className="text-sm font-semibold text-slate-600">Lease expirations</div>
          <div className="mt-1 text-xs text-slate-500">
            WALT {statement.leases.walt.toFixed(1)} yrs ·{' '}
            {Math.round(statement.leases.totalSf).toLocaleString()} SF · year-1 occupancy{' '}
            {(statement.leases.occupancyYear1 * 100).toFixed(1)}% · stabilized{' '}
            {(statement.leases.occupancyStabilized * 100).toFixed(1)}%
          </div>
          {statement.leases.expirationSchedule.length > 0 && (
            <div className="mt-2 flex items-end gap-4">
              <svg
                width={Math.max(160, statement.leases.expirationSchedule.length * 56)}
                height={110}
                role="img"
                aria-label="Lease expiration schedule"
              >
                {statement.leases.expirationSchedule.map((row, i) => {
                  const barHeight = Math.max(2, row.pctOfRent * 80)
                  return (
                    <g key={row.year}>
                      <rect
                        x={i * 56 + 8}
                        y={88 - barHeight}
                        width={36}
                        height={barHeight}
                        rx={2}
                        fill="#7dd3fc"
                        stroke="#0284c7"
                        strokeWidth={0.5}
                      />
                      <text x={i * 56 + 26} y={84 - barHeight} fontSize={9} fill="#475569" textAnchor="middle">
                        {Math.round(row.pctOfRent * 100)}%
                      </text>
                      <text x={i * 56 + 26} y={102} fontSize={10} fill="#64748b" textAnchor="middle">
                        {row.year}
                      </text>
                    </g>
                  )
                })}
              </svg>
              <table className="text-xs">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    <th className="px-2 py-1 font-medium">Year</th>
                    <th className="px-2 py-1 font-medium">SF expiring</th>
                    <th className="px-2 py-1 font-medium">% of SF</th>
                    <th className="px-2 py-1 font-medium">% of rent</th>
                  </tr>
                </thead>
                <tbody>
                  {statement.leases.expirationSchedule.map((row) => (
                    <tr key={row.year} className="border-b border-slate-50">
                      <td className="px-2 py-1">{row.year}</td>
                      <td className="px-2 py-1 tabular-nums">{Math.round(row.sfExpiring).toLocaleString()}</td>
                      <td className="px-2 py-1 tabular-nums">{(row.pctOfSf * 100).toFixed(1)}%</td>
                      <td className="px-2 py-1 tabular-nums">{(row.pctOfRent * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      <details className="mt-4 rounded border border-slate-200 bg-white p-3">
        <summary className="cursor-pointer select-none text-sm font-semibold text-slate-600">
          Hold-period &amp; refi analysis
        </summary>
        <p className="mt-1 text-xs text-slate-400">
          Re-evaluates the deal at every whole exit year after stabilization (modeled hold marked),
          and compares selling at stabilization vs refinancing and holding.
        </p>
        <button
          onClick={() => void handleRunHoldSweep()}
          disabled={holdBusy}
          className="mt-2 rounded bg-slate-900 px-3 py-1 text-xs text-white hover:bg-slate-700 disabled:opacity-40"
        >
          {holdBusy ? 'Running…' : holdSweep ? 'Re-run' : 'Run hold sweep'}
        </button>
        {holdError && <div className="mt-2 text-sm text-red-600">{holdError}</div>}
        {holdSweep && (
          <div className="mt-3 space-y-3">
            {[...holdSweep.sweep.warnings, ...holdSweep.refiVsSale.warnings].map((w, i) => (
              <div key={i} className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-700">
                {w}
              </div>
            ))}
            {holdSweep.sweep.rows.length > 0 && (
              <>
                <HoldSweepChart response={holdSweep} />
                <table className="text-xs">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-slate-500">
                      <th className="px-2 py-1 font-medium">Exit year</th>
                      <th className="px-2 py-1 font-medium">Unlevered IRR</th>
                      <th className="px-2 py-1 font-medium">Levered IRR</th>
                      <th className="px-2 py-1 font-medium">Equity multiple</th>
                      <th className="px-2 py-1 font-medium">Net proceeds</th>
                    </tr>
                  </thead>
                  <tbody>
                    {holdSweep.sweep.rows.map((row) => (
                      <tr
                        key={row.holdYear}
                        className={`border-b border-slate-50 ${
                          row.holdYear === holdSweep.sweep.modeledHoldYears ? 'bg-amber-50 font-medium' : ''
                        }`}
                      >
                        <td className="px-2 py-1">
                          Year {row.holdYear}
                          {row.holdYear === holdSweep.sweep.modeledHoldYears && (
                            <span className="ml-1 text-[10px] text-amber-600">modeled</span>
                          )}
                        </td>
                        <td className="px-2 py-1 tabular-nums">{pct(row.unleveredIrr)}</td>
                        <td className="px-2 py-1 tabular-nums">{pct(row.leveredIrr)}</td>
                        <td className="px-2 py-1 tabular-nums">{mult(row.equityMultiple)}</td>
                        <td className="px-2 py-1 tabular-nums">{money(row.netProceeds)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
            {(holdSweep.refiVsSale.saleAtStabilization || holdSweep.refiVsSale.holdThroughRefi) && (
              <div>
                <div className="text-xs font-semibold tracking-wide text-slate-500">
                  REFI VS SALE AT STABILIZATION
                </div>
                <table className="mt-1 text-xs">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-slate-500">
                      <th className="px-2 py-1 font-medium">Path</th>
                      <th className="px-2 py-1 font-medium">Hold (yrs)</th>
                      <th className="px-2 py-1 font-medium">Levered IRR</th>
                      <th className="px-2 py-1 font-medium">Equity multiple</th>
                      <th className="px-2 py-1 font-medium">Proceeds detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {holdSweep.refiVsSale.saleAtStabilization && (
                      <tr className="border-b border-slate-50">
                        <td className="px-2 py-1">Sell at stabilization</td>
                        <td className="px-2 py-1 tabular-nums">
                          {holdSweep.refiVsSale.saleAtStabilization.holdYears}
                        </td>
                        <td className="px-2 py-1 tabular-nums">
                          {pct(holdSweep.refiVsSale.saleAtStabilization.leveredIrr)}
                        </td>
                        <td className="px-2 py-1 tabular-nums">
                          {mult(holdSweep.refiVsSale.saleAtStabilization.equityMultiple)}
                        </td>
                        <td className="px-2 py-1 tabular-nums">
                          Net sale {money(holdSweep.refiVsSale.saleAtStabilization.netProceeds)}
                        </td>
                      </tr>
                    )}
                    {holdSweep.refiVsSale.holdThroughRefi && (
                      <tr>
                        <td className="px-2 py-1">Refi &amp; hold to exit</td>
                        <td className="px-2 py-1 tabular-nums">
                          {holdSweep.refiVsSale.holdThroughRefi.holdYears}
                        </td>
                        <td className="px-2 py-1 tabular-nums">
                          {pct(holdSweep.refiVsSale.holdThroughRefi.leveredIrr)}
                        </td>
                        <td className="px-2 py-1 tabular-nums">
                          {mult(holdSweep.refiVsSale.holdThroughRefi.equityMultiple)}
                        </td>
                        <td className="px-2 py-1 tabular-nums">
                          Refi loan {money(holdSweep.refiVsSale.holdThroughRefi.refiLoan)} (
                          {holdSweep.refiVsSale.holdThroughRefi.governingConstraint}) · cash-out{' '}
                          {money(holdSweep.refiVsSale.holdThroughRefi.cashOutProceeds)} · costs{' '}
                          {money(holdSweep.refiVsSale.holdThroughRefi.refiCosts)}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </details>
    </div>
  )
}
