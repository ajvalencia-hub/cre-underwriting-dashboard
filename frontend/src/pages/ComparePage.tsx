// Compare deals side by side. App mounts it (tab divs stay mounted):
//
//   <ComparePage schema={schema} deals={deals} active={tab === 'compare'} onOpenDeal={…} />
//
// - deals:      App's working deal list (non-archived, full rows WITH
//               inputs), so no refetch is needed: each selected deal is
//               computed from its saved inputs, and recomputed when its
//               `updatedAt` moves (autosave keeps App's list current).
// - active:     compute lazily, only while the tab is showing.
// - onOpenDeal: switch to a deal (App saves the current one first).
//
// Compare is in MULTI_DEAL_TABS (no one-deal summary panel beside it).
import { useEffect, useMemo, useRef, useState } from 'react'
import { computeNative } from '../lib/api'
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
  type CompareRow,
} from '../lib/compareMath'
import { dealTypeOf } from '../lib/dealStages'
import { friendlyEngineError } from '../lib/engineErrors'
import { formatOutputValue } from '../lib/formatValue'
import { safeStorage } from '../lib/safeStorage'
import { saveOutput, textBlob } from '../lib/saveOutput'
import { defaultValuesFor } from '../lib/schemaFields'
import { toastError } from '../lib/toast'
import type { Deal } from '../types/deal'
import type { InputSchema } from '../types/schema'

export interface ComparePageProps {
  schema: InputSchema
  deals: Deal[]
  active: boolean
  onOpenDeal: (dealId: string) => Promise<void>
}

/** One computed column, cached by deal id + the saved version it came from. */
interface CacheEntry {
  version: string
  column: CompareColumn | null // null = computing
}

const versionOf = (deal: Deal) => `${deal.updatedAt}`

export default function ComparePage({ schema, deals, active, onOpenDeal }: ComparePageProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>(() => loadCompareIds(safeStorage))
  const [cache, setCache] = useState<Record<string, CacheEntry>>({})
  // Latest-wins: every compute carries the generation current when it
  // started; Recompute advances it so results for the cleared cache are
  // dropped. (A ref, not a guard advanced in a state initializer — StrictMode
  // runs initializers twice.)
  const generationRef = useRef(0)
  const [generation, setGeneration] = useState(0)

  const liveDeals = useMemo(() => deals.filter((d) => !d.archivedAt), [deals])
  const byId = useMemo(() => new Map(liveDeals.map((d) => [d.id, d])), [liveDeals])
  // Selections of deleted / archived deals simply drop out of view (the
  // stored list is rewritten on the next toggle).
  const liveIds = useMemo(() => pruneCompareIds(selectedIds, liveDeals), [selectedIds, liveDeals])
  const defaults = useMemo(() => defaultValuesFor(schema), [schema])

  useEffect(() => {
    if (!active) return
    const stale = liveIds
      .map((id) => byId.get(id)!)
      .filter((deal) => cache[deal.id]?.version !== versionOf(deal))
    if (stale.length === 0) return
    setCache((prev) => {
      const next = { ...prev }
      for (const deal of stale) next[deal.id] = { version: versionOf(deal), column: null }
      return next
    })
    for (const deal of stale) {
      const version = versionOf(deal)
      void computeColumn(deal, defaults).then((column) => {
        if (generationRef.current !== generation) return
        setCache((prev) =>
          // A newer save of this deal started its own compute: drop this one.
          prev[deal.id]?.version === version ? { ...prev, [deal.id]: { version, column } } : prev,
        )
      })
    }
    // `cache` is the store this effect fills; depending on it would re-run
    // on every fill (harmless but wasteful) — versions gate the work.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, liveIds, byId, defaults, generation])

  function toggle(id: string) {
    setSelectedIds((prev) => {
      const next = toggleCompareId(pruneCompareIds(prev, liveDeals), id)
      saveCompareIds(safeStorage, next)
      return next
    })
  }

  function handleRecompute() {
    generationRef.current += 1
    setCache({})
    setGeneration(generationRef.current)
  }

  const columnsInOrder = liveIds.map((id) => cache[id]?.column ?? null)
  const readyColumns = useMemo(
    () => columnsInOrder.filter((c): c is CompareColumn => c !== null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cache, liveIds],
  )
  const computingCount = columnsInOrder.filter((c) => c === null).length
  const rows = useMemo(() => buildCompareRows(schema.outputs, readyColumns), [schema.outputs, readyColumns])
  const groups = useMemo(() => Array.from(new Set(rows.map((r) => r.metric.group ?? 'Metrics'))), [rows])
  const enough = liveIds.length >= MIN_COMPARE_DEALS

  async function handleExport() {
    try {
      await saveOutput(
        textBlob(compareToCsv(rows, readyColumns, formatOutputValue), 'text/csv;charset=utf-8'),
        'deal-comparison.csv',
      )
    } catch (err) {
      toastError("Couldn't export the comparison", err)
    }
  }

  return (
    <div className="max-w-5xl space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Compare deals</h1>
        <p className="mt-1 text-slate-500">
          Pick {MIN_COMPARE_DEALS}–{MAX_COMPARE_DEALS} deals. Each is computed from its saved inputs; the best value
          per metric is highlighted where "better" is unambiguous.
        </p>
      </div>

      <fieldset className="rounded border border-slate-200 bg-white p-3">
        <legend className="px-1 text-[11px] font-semibold tracking-wide text-slate-500">
          DEALS ({liveIds.length} of {MAX_COMPARE_DEALS} selected)
        </legend>
        {liveDeals.length === 0 ? (
          <div className="text-sm text-slate-500">No deals yet.</div>
        ) : (
          <ul className="flex flex-wrap gap-x-4 gap-y-1">
            {liveDeals.map((deal) => {
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
      </fieldset>

      {!enough && <div className="text-sm text-slate-500">Select at least {MIN_COMPARE_DEALS} deals to compare.</div>}

      {enough && (
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
            <button
              type="button"
              onClick={handleRecompute}
              className="rounded border border-slate-300 px-2 py-1 text-slate-600 hover:bg-slate-50"
            >
              Recompute
            </button>
            <button
              type="button"
              onClick={() => void handleExport()}
              disabled={readyColumns.length === 0 || computingCount > 0}
              className="rounded border border-slate-300 px-2 py-1 text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            >
              Export CSV
            </button>
            {computingCount > 0 && <span className="text-slate-500">Computing {computingCount}…</span>}
          </div>

          <div className="overflow-x-auto rounded border border-slate-200 bg-white">
            <table className="w-full text-sm" aria-label="Deal comparison">
              <thead>
                <tr className="border-b border-slate-200 text-left">
                  <th scope="col" className="px-3 py-2 font-medium text-slate-500">
                    Metric
                  </th>
                  {liveIds.map((id, i) => {
                    const column = columnsInOrder[i]
                    const deal = byId.get(id)
                    return (
                      <th key={id} scope="col" className="px-3 py-2 font-medium text-slate-700">
                        <button
                          type="button"
                          onClick={() => void onOpenDeal(id)}
                          className="text-left hover:underline"
                          title="Open this deal"
                        >
                          {deal?.name ?? id}
                        </button>
                        {column === null && (
                          <span className="ml-1 text-[10px] font-normal text-slate-500">computing…</span>
                        )}
                        {column && !column.outputs && (
                          <span
                            title={column.note}
                            className="ml-1 rounded bg-amber-100 px-1 py-0.5 text-[10px] font-normal text-amber-700"
                          >
                            not computable
                          </span>
                        )}
                        {column && !column.outputs && column.note && (
                          <div className="mt-0.5 max-w-[14rem] text-[11px] font-normal text-amber-700">{column.note}</div>
                        )}
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody>
                {readyColumns.length === 0 && (
                  <tr>
                    <td colSpan={liveIds.length + 1} className="px-3 py-4 text-slate-500">
                      Computing…
                    </td>
                  </tr>
                )}
                {readyColumns.length > 0 &&
                  groups.map((group) => (
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
          <p className="mt-1 text-[11px] text-slate-500">
            "n/a" = the metric doesn't apply to that dealflow; "—" = the engine returned no value.
          </p>
        </div>
      )}
    </div>
  )
}

async function computeColumn(deal: Deal, defaults: Record<string, unknown>): Promise<CompareColumn> {
  const dealType = dealTypeOf(deal)
  const base = { dealId: deal.id, name: deal.name, dealType }
  if (!dealType) {
    return { ...base, outputs: null, note: 'Untyped deal — set Acquisition or Development first.' }
  }
  try {
    const result = await computeNative(dealFormValues(deal.inputs, defaults))
    return { ...base, outputs: result.outputs }
  } catch (err) {
    return { ...base, outputs: null, note: friendlyEngineError(err, 'Not computable') }
  }
}

function GroupRows({
  group,
  rows,
  columnIds,
  readyColumns,
}: {
  group: string
  rows: CompareRow[]
  columnIds: string[]
  readyColumns: CompareColumn[]
}) {
  // Rows are built over the READY columns only; map them back onto the
  // full selection so a still-computing column renders a placeholder.
  const readyIndex = new Map(readyColumns.map((c, i) => [c.dealId, i]))
  return (
    <>
      <tr className="bg-slate-50">
        <th
          scope="colgroup"
          colSpan={columnIds.length + 1}
          className="px-3 py-1 text-left text-[10px] font-semibold tracking-wide text-slate-500"
        >
          {group.toUpperCase()}
        </th>
      </tr>
      {rows.map((row) => (
        <tr key={row.metric.id} className="border-b border-slate-50">
          <th scope="row" className="px-3 py-1.5 text-left font-normal text-slate-500">
            {row.metric.label}
          </th>
          {columnIds.map((id) => {
            const i = readyIndex.get(id)
            if (i === undefined)
              return (
                <td key={id} className="px-3 py-1.5 text-slate-400">
                  …
                </td>
              )
            const value = row.values[i]
            const applicable = row.applicable[i]
            const best = row.best === i
            return (
              <td
                key={id}
                className={`px-3 py-1.5 tabular-nums ${best ? 'bg-emerald-50 font-semibold text-emerald-700' : ''} ${
                  !applicable ? 'text-slate-400' : ''
                }`}
                aria-label={best ? `${formatOutputValue(row.metric, value)} (best)` : undefined}
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
