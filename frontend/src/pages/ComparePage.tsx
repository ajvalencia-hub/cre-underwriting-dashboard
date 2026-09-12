import { useEffect, useMemo, useRef, useState } from 'react'
import { computeNative, fetchDeal } from '../lib/api'
import {
  MAX_COMPARE_DEALS,
  MIN_COMPARE_DEALS,
  buildCompareRows,
  compareToCsv,
  dealFormValues,
  loadCompareIds,
  pruneCompareIds,
  saveCompareIds,
  toggleCompareId,
  type CompareColumn,
} from '../lib/compareMath'
import { dealTypeOf } from '../lib/dealStages'
import { friendlyEngineError } from '../lib/engineErrors'
import { formatOutputValue } from '../lib/formatValue'
import { createLatestGuard } from '../lib/latest'
import { safeStorage } from '../lib/safeStorage'
import type { Deal } from '../types/deal'
import type { InputSchema } from '../types/schema'

interface ComparePageProps {
  schema: InputSchema
  /** The working (non-archived) list from App. */
  deals: Deal[]
  active: boolean
}

type ColumnState = { status: 'loading' } | { status: 'ready'; column: CompareColumn }

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

/** Wave 2: pick 2–4 deals, fetch + compute each through the native engine,
 *  and lay the type-visible outputs side by side with the same
 *  direction-aware best-value highlight the Scenarios comparison uses. */
export default function ComparePage({ schema, deals, active }: ComparePageProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>(() => loadCompareIds(safeStorage))
  const [columns, setColumns] = useState<Record<string, ColumnState>>({})
  // B5-style latest-wins: every in-flight compute carries the token that was
  // current when it started; Recompute advances it so stale results are
  // dropped instead of landing on the cleared cache.
  const guard = useRef(createLatestGuard())
  // Lazily: `useRef(guard.current.next())` would advance the counter on
  // EVERY render (the initializer expression still runs), so no compute
  // would ever be "current".
  const tokenRef = useRef<number | null>(null)
  if (tokenRef.current === null) tokenRef.current = guard.current.next()
  // Bumped by "Recompute" so the fill effect reruns for the cleared cache.
  const [generation, setGeneration] = useState(0)

  // Drop selections that no longer exist (deleted / archived).
  const liveIds = useMemo(() => pruneCompareIds(selectedIds, deals), [selectedIds, deals])
  useEffect(() => {
    if (liveIds.length !== selectedIds.length) setSelectedIds(liveIds)
  }, [liveIds, selectedIds.length])

  useEffect(() => {
    saveCompareIds(safeStorage, selectedIds)
  }, [selectedIds])

  useEffect(() => {
    if (!active) return
    const missing = liveIds.filter((id) => !columns[id])
    if (missing.length === 0) return
    const token = tokenRef.current ?? guard.current.next()
    setColumns((prev) => {
      const next = { ...prev }
      for (const id of missing) next[id] = { status: 'loading' }
      return next
    })
    for (const id of missing) {
      void (async () => {
        let column: CompareColumn
        try {
          const deal = await fetchDeal(id)
          const dealType = dealTypeOf(deal)
          if (!dealType) {
            column = { dealId: id, name: deal.name, dealType, outputs: null, note: 'Untyped deal — set a dealflow first.' }
          } else {
            try {
              const result = await computeNative(dealFormValues(deal.inputs))
              column = { dealId: id, name: deal.name, dealType, outputs: result.outputs }
            } catch (err) {
              column = {
                dealId: id,
                name: deal.name,
                dealType,
                outputs: null,
                note: friendlyEngineError(err instanceof Error ? err.message : 'Not computable'),
              }
            }
          }
        } catch (err) {
          const fallback = deals.find((d) => d.id === id)
          column = {
            dealId: id,
            name: fallback?.name ?? id,
            dealType: fallback ? dealTypeOf(fallback) : null,
            outputs: null,
            note: err instanceof Error ? err.message : 'Could not load the deal.',
          }
        }
        if (!guard.current.isCurrent(token)) return
        setColumns((prev) => ({ ...prev, [id]: { status: 'ready', column } }))
      })()
    }
    // `columns` is intentionally not a dependency: it is the cache this
    // effect fills, and re-running on every fill would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, liveIds, generation])

  function toggle(id: string) {
    setSelectedIds((prev) => toggleCompareId(prev, id))
  }

  function handleRecompute() {
    tokenRef.current = guard.current.next()
    setColumns({})
    setGeneration((g) => g + 1)
  }

  const readyColumns = useMemo(
    () =>
      liveIds
        .map((id) => columns[id])
        .filter((c): c is { status: 'ready'; column: CompareColumn } => c?.status === 'ready')
        .map((c) => c.column),
    [liveIds, columns],
  )
  const loadingCount = liveIds.filter((id) => columns[id]?.status === 'loading').length
  const rows = useMemo(() => buildCompareRows(schema.outputs, readyColumns), [schema.outputs, readyColumns])
  const groups = useMemo(
    () => Array.from(new Set(rows.map((r) => r.metric.group ?? 'Metrics'))),
    [rows],
  )
  const enough = liveIds.length >= MIN_COMPARE_DEALS

  return (
    <div className="max-w-5xl space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Compare deals</h1>
        <p className="mt-1 text-slate-500">
          Pick {MIN_COMPARE_DEALS}–{MAX_COMPARE_DEALS} deals. Each is computed through the native
          engine from its saved inputs; the best value per metric is highlighted where the
          direction is unambiguous.
        </p>
      </div>

      <div className="rounded border border-slate-200 bg-white p-3">
        <div className="text-[11px] font-semibold tracking-wide text-slate-400">
          DEALS ({liveIds.length} of {MAX_COMPARE_DEALS} selected)
        </div>
        {deals.length === 0 ? (
          <div className="mt-2 text-sm text-slate-400">No deals yet.</div>
        ) : (
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {deals.map((deal) => {
              const checked = liveIds.includes(deal.id)
              const type = dealTypeOf(deal)
              return (
                <li key={deal.id}>
                  <label className="flex items-center gap-1.5 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={!checked && liveIds.length >= MAX_COMPARE_DEALS}
                      onChange={() => toggle(deal.id)}
                    />
                    {deal.name}
                    <span
                      className={`rounded px-1 py-0.5 text-[9px] font-semibold ${
                        type === 'development'
                          ? 'bg-orange-100 text-orange-700'
                          : type === 'acquisition'
                            ? 'bg-sky-100 text-sky-700'
                            : 'bg-amber-100 text-amber-700'
                      }`}
                    >
                      {type === 'development' ? 'DEV' : type === 'acquisition' ? 'ACQ' : 'UNTYPED'}
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {!enough && (
        <div className="text-sm text-slate-400">
          Select at least {MIN_COMPARE_DEALS} deals to compare.
        </div>
      )}

      {enough && (
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
            <button
              onClick={handleRecompute}
              className="rounded border border-slate-300 px-2 py-1 text-slate-600 hover:bg-slate-50"
            >
              Recompute
            </button>
            <button
              onClick={() =>
                download('deal-comparison.csv', compareToCsv(rows, readyColumns, formatOutputValue))
              }
              disabled={readyColumns.length === 0}
              className="rounded border border-slate-300 px-2 py-1 text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            >
              Export CSV
            </button>
            {loadingCount > 0 && <span className="text-slate-400">Computing {loadingCount}…</span>}
          </div>

          <div className="overflow-x-auto rounded border border-slate-200 bg-white">
            <table className="w-full text-sm" aria-label="Deal comparison">
              <thead>
                <tr className="border-b border-slate-200 text-left">
                  <th scope="col" className="px-3 py-2 font-medium text-slate-500">
                    Metric
                  </th>
                  {liveIds.map((id) => {
                    const state = columns[id]
                    const fallback = deals.find((d) => d.id === id)
                    const column = state?.status === 'ready' ? state.column : null
                    return (
                      <th key={id} scope="col" className="px-3 py-2 font-medium text-slate-700">
                        {column?.name ?? fallback?.name ?? id}
                        {state?.status === 'loading' && (
                          <span className="ml-1 text-[10px] font-normal text-slate-400">computing…</span>
                        )}
                        {column && !column.outputs && (
                          <span
                            title={column.note}
                            className="ml-1 rounded bg-amber-100 px-1 py-0.5 text-[10px] font-normal text-amber-700"
                          >
                            not computable
                          </span>
                        )}
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody>
                {readyColumns.length === 0 && (
                  <tr>
                    <td colSpan={liveIds.length + 1} className="px-3 py-4 text-slate-400">
                      Computing…
                    </td>
                  </tr>
                )}
                {groups.map((group) => (
                  <GroupRows
                    key={group}
                    group={group}
                    rows={rows.filter((r) => (r.metric.group ?? 'Metrics') === group)}
                    columnIds={liveIds}
                    readyColumns={readyColumns}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-1 text-[11px] text-slate-400">
            "n/a" = the metric does not apply to that dealflow; "—" = the engine returned no value.
            Deals edited since opening this tab need Recompute.
          </p>
        </div>
      )}
    </div>
  )
}

function GroupRows({
  group,
  rows,
  columnIds,
  readyColumns,
}: {
  group: string
  rows: ReturnType<typeof buildCompareRows>
  columnIds: string[]
  readyColumns: CompareColumn[]
}) {
  // Rows are built over the READY columns only; map them back onto the
  // full selection so a still-computing column renders a blank cell.
  const readyIndex = new Map(readyColumns.map((c, i) => [c.dealId, i]))
  return (
    <>
      <tr className="bg-slate-50">
        <td
          colSpan={columnIds.length + 1}
          className="px-3 py-1 text-[10px] font-semibold tracking-wide text-slate-400"
        >
          {group.toUpperCase()}
        </td>
      </tr>
      {rows.map((row) => (
        <tr key={row.metric.id} className="border-b border-slate-50">
          <td className="px-3 py-1.5 text-slate-500">{row.metric.label}</td>
          {columnIds.map((id) => {
            const i = readyIndex.get(id)
            if (i === undefined) return <td key={id} className="px-3 py-1.5 text-slate-300">…</td>
            const value = row.values[i]
            const applicable = row.applicable[i]
            const best = row.best === i
            return (
              <td
                key={id}
                className={`px-3 py-1.5 tabular-nums ${
                  best ? 'bg-emerald-50 font-semibold text-emerald-700' : ''
                } ${!applicable ? 'text-slate-300' : ''}`}
              >
                {!applicable ? 'n/a' : value === null ? '—' : formatOutputValue(row.metric, value)}
              </td>
            )
          })}
        </tr>
      ))}
    </>
  )
}
