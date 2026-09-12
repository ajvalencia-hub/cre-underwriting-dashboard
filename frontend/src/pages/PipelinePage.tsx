import { useEffect, useMemo, useState } from 'react'
import { exportBatchDeck, fetchDeals, unarchiveDeal } from '../lib/api'
import { upcomingDeadlines } from '../lib/criticalDates'
import { safeStorage } from '../lib/safeStorage'
import { toastError } from '../lib/toast'
import {
  ALL_STAGES,
  bulkStageOptions,
  dealTypeOf,
  STAGE_LABELS,
  STAGE_STYLES,
  stageOptionsForDeal,
  stagesFor,
  type DealType,
} from '../lib/dealStages'
import { relativeAge, stalenessBadge } from '../lib/staleness'
import { allTags, dealTags, normalizeTag, toggleTag } from '../lib/tags'
import {
  DEFAULT_SORT_DIR,
  DEFAULT_VIEW_STATE,
  STALENESS_LABELS,
  STALENESS_LEVELS,
  applyPipelineView,
  dealMarket,
  deleteView,
  loadViews,
  pipelineToCsv,
  saveView,
  toggleSort,
  type PipelineSortKey,
  type PipelineView,
  type PipelineViewState,
  type SortDir,
  type StalenessLevel,
} from '../lib/pipelineViews'
import type { Deal, DealStatus } from '../types/deal'

interface PipelinePageProps {
  deals: Deal[]
  activeDealId: string | null
  onOpenDeal: (dealId: string) => void
  onStatusChange: (dealId: string, status: DealStatus) => void
  onBulkStatus: (dealIds: string[], status: DealStatus) => Promise<void>
  /** Wave 2: bulk add/remove tags on the selection. */
  onBulkTags: (dealIds: string[], add: string[], remove: string[]) => Promise<void>
  /** Typed creation — every new deal knows its dealflow from birth. */
  onNewDeal: (type: DealType) => void
  /** J10: opens the OM-to-deal wizard. */
  onNewDealFromDocuments: () => void
  /** Assign a type to an untyped (legacy) deal. */
  onSetDealType: (dealId: string, type: DealType) => void
  /** F2: an unarchive changed the server-side list — refetch it. */
  onDealsChanged: () => void
}

const BOARD_META: Record<DealType, { title: string; accent: string }> = {
  acquisition: { title: 'Acquisitions', accent: 'text-sky-700' },
  development: { title: 'Developments', accent: 'text-orange-700' },
}

const SORT_COLUMNS: { key: PipelineSortKey; label: string; className?: string }[] = [
  { key: 'name', label: 'Deal' },
  { key: 'market', label: 'Market' },
  { key: 'stage', label: 'Stage' },
  { key: 'updated', label: 'Last touched' },
  { key: 'staleness', label: 'Staleness', className: 'w-24' },
]

/** Wave 2: sortable column header — aria-sort on the <th>, the click target
 *  is a real button so it is keyboard-reachable. */
function SortHeader({
  column,
  sortKey,
  sortDir,
  onSort,
}: {
  column: (typeof SORT_COLUMNS)[number]
  sortKey: PipelineSortKey
  sortDir: SortDir
  onSort: (key: PipelineSortKey) => void
}) {
  const active = sortKey === column.key
  return (
    <th
      scope="col"
      aria-sort={active ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
      className={`px-3 py-2 font-medium ${column.className ?? ''}`}
    >
      <button
        type="button"
        onClick={() => onSort(column.key)}
        className={`flex items-center gap-1 hover:text-slate-600 ${active ? 'text-slate-600' : ''}`}
      >
        {column.label}
        <span aria-hidden="true" className={active ? '' : 'opacity-30'}>
          {active ? (sortDir === 'asc' ? '▲' : '▼') : '▵'}
        </span>
      </button>
    </th>
  )
}

function TagChips({ tags }: { tags: string[] }) {
  if (tags.length === 0) return null
  return (
    <span className="ml-2 inline-flex flex-wrap gap-1 align-middle">
      {tags.map((tag) => (
        <span key={tag} className="rounded bg-slate-100 px-1 py-0.5 text-[10px] text-slate-500">
          {tag}
        </span>
      ))}
    </span>
  )
}

interface BoardProps {
  type: DealType
  deals: Deal[]
  /** F2: archived deals of this type — rendered dimmed, never counted or bulk-selected. */
  archivedDeals: Deal[]
  hiddenCount: number
  activeDealId: string | null
  selected: Set<string>
  sortKey: PipelineSortKey
  sortDir: SortDir
  onSort: (key: PipelineSortKey) => void
  onToggle: (dealId: string, checked: boolean) => void
  onSelectAll: (dealIds: string[], checked: boolean) => void
  onOpenDeal: (dealId: string) => void
  onStatusChange: (dealId: string, status: DealStatus) => void
  onNewDeal: (type: DealType) => void
  onUnarchive: (dealId: string) => void
}

/** One dealflow board: its own stage chips, counts, and stage dropdowns. */
function Board({
  type, deals, archivedDeals, hiddenCount, activeDealId, selected, sortKey, sortDir, onSort,
  onToggle, onSelectAll, onOpenDeal, onStatusChange, onNewDeal, onUnarchive,
}: BoardProps) {
  const stages = stagesFor(type)
  const counts = new Map<DealStatus, number>()
  for (const deal of deals) counts.set(deal.status, (counts.get(deal.status) ?? 0) + 1)
  const visibleSelected = deals.filter((d) => selected.has(d.id))

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className={`text-sm font-semibold ${BOARD_META[type].accent}`}>
            {BOARD_META[type].title}
          </h3>
          {stages.map((stage) => (
            <span
              key={stage}
              className={`rounded px-2 py-1 text-xs ${STAGE_STYLES[stage]} ${
                (counts.get(stage) ?? 0) === 0 ? 'opacity-40' : ''
              }`}
            >
              {STAGE_LABELS[stage]} · {counts.get(stage) ?? 0}
            </span>
          ))}
        </div>
        <button
          onClick={() => onNewDeal(type)}
          className="shrink-0 rounded bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-700"
        >
          New {type} deal
        </button>
      </div>

      <div className="mt-2 overflow-x-auto rounded border border-slate-200 bg-white">
        <table className="w-full min-w-[600px] text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-400">
              <th className="w-8 px-3 py-2">
                <input
                  type="checkbox"
                  aria-label={`Select all visible ${type} deals`}
                  checked={deals.length > 0 && visibleSelected.length === deals.length}
                  onChange={(e) => onSelectAll(deals.map((d) => d.id), e.target.checked)}
                />
              </th>
              {SORT_COLUMNS.map((column) => (
                <SortHeader
                  key={column.key}
                  column={column}
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onSort={onSort}
                />
              ))}
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {deals.map((deal) => {
              const badge = stalenessBadge(deal.status, deal.updatedAt)
              const options = stageOptionsForDeal(deal)
              return (
                <tr
                  key={deal.id}
                  className={`border-b border-slate-50 ${
                    deal.id === activeDealId ? 'bg-sky-50/50' : ''
                  }`}
                >
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label={`Select ${deal.name}`}
                      checked={selected.has(deal.id)}
                      onChange={(e) => onToggle(deal.id, e.target.checked)}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() => onOpenDeal(deal.id)}
                      className="font-medium text-slate-800 hover:text-sky-700 hover:underline"
                    >
                      {deal.name}
                    </button>
                    {deal.id === activeDealId && (
                      <span className="ml-2 text-[10px] text-sky-600">active</span>
                    )}
                    <TagChips tags={dealTags(deal)} />
                  </td>
                  <td className="px-3 py-2 text-slate-500">{dealMarket(deal) || '—'}</td>
                  <td className="px-3 py-2">
                    <select
                      value={deal.status}
                      aria-label={`Stage of ${deal.name}`}
                      onChange={(e) => onStatusChange(deal.id, e.target.value as DealStatus)}
                      className={`rounded border-0 px-2 py-1 text-xs ${STAGE_STYLES[deal.status]}`}
                    >
                      {options.map((stage) => (
                        <option key={stage} value={stage}>
                          {STAGE_LABELS[stage]}
                          {!stages.includes(stage) ? ' (legacy)' : ''}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-3 py-2 text-slate-500">{relativeAge(deal.updatedAt)}</td>
                  <td className="px-3 py-2 text-slate-500">
                    {badge ? (
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] ${
                          badge.tone === 'red'
                            ? 'bg-red-100 text-red-700'
                            : 'bg-amber-100 text-amber-700'
                        }`}
                      >
                        △ {badge.label}
                      </span>
                    ) : (
                      <span className="text-[10px] text-slate-300">fresh</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <a
                      href={`/api/deals/${deal.id}/share.html`}
                      target="_blank"
                      rel="noreferrer"
                      title="Self-contained read-only HTML snapshot"
                      className="mr-2 text-xs text-slate-400 hover:text-sky-700 hover:underline"
                    >
                      Share
                    </a>
                    <a
                      href={`/api/deals/${deal.id}/deck.pptx`}
                      title="One-page investment summary (PowerPoint)"
                      className="mr-2 text-xs text-slate-400 hover:text-sky-700 hover:underline"
                    >
                      Deck
                    </a>
                    <a
                      href={`/api/deals/${deal.id}/ic-deck.pptx`}
                      title="Full 8-slide IC deck (PowerPoint)"
                      className="mr-2 text-xs text-slate-400 hover:text-sky-700 hover:underline"
                    >
                      IC deck
                    </a>
                    <button
                      onClick={() => onOpenDeal(deal.id)}
                      className="rounded border border-slate-200 px-2 py-0.5 text-xs text-slate-500 hover:bg-slate-50"
                    >
                      Open
                    </button>
                  </td>
                </tr>
              )
            })}
            {deals.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-sm text-slate-400">
                  No {type} deals{hiddenCount > 0 ? ' in this view' : ' yet'}.
                </td>
              </tr>
            )}
            {archivedDeals.map((deal) => (
              <tr key={deal.id} className="border-b border-slate-50 opacity-50" aria-label={`${deal.name} (archived)`}>
                <td className="px-3 py-2" />
                <td className="px-3 py-2">
                  <span className="font-medium text-slate-600">{deal.name}</span>
                  <span className="ml-2 rounded bg-slate-200 px-1.5 py-0.5 text-[10px] text-slate-600">
                    archived
                  </span>
                  <TagChips tags={dealTags(deal)} />
                </td>
                <td className="px-3 py-2 text-slate-500">{dealMarket(deal) || '—'}</td>
                <td className="px-3 py-2 text-xs text-slate-500">{STAGE_LABELS[deal.status]}</td>
                <td className="px-3 py-2 text-slate-500">
                  {deal.archivedAt ? `archived ${relativeAge(deal.archivedAt)}` : relativeAge(deal.updatedAt)}
                </td>
                <td className="px-3 py-2" />
                <td className="px-3 py-2 text-right">
                  <button
                    onClick={() => onUnarchive(deal.id)}
                    className="rounded border border-slate-200 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-50"
                  >
                    Unarchive
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** Toggle-chip row for one filter dimension (stage / staleness / tag). */
function FilterChips<T extends string>({
  label,
  options,
  selected,
  onToggle,
  render = (v) => v,
  chipClass = () => 'bg-slate-100 text-slate-600',
}: {
  label: string
  options: T[]
  selected: T[]
  onToggle: (value: T) => void
  render?: (value: T) => string
  chipClass?: (value: T) => string
}) {
  if (options.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-1" role="group" aria-label={`Filter by ${label}`}>
      <span className="text-[10px] font-semibold tracking-wide text-slate-400">{label.toUpperCase()}</span>
      {options.map((value) => {
        const on = selected.includes(value)
        return (
          <button
            key={value}
            type="button"
            onClick={() => onToggle(value)}
            aria-pressed={on}
            className={`rounded border px-1.5 py-0.5 text-[11px] ${
              on ? `border-slate-400 ${chipClass(value)}` : 'border-slate-200 text-slate-400 hover:text-slate-600'
            }`}
          >
            {render(value)}
          </button>
        )
      })}
    </div>
  )
}

export default function PipelinePage({
  deals,
  activeDealId,
  onOpenDeal,
  onStatusChange,
  onBulkStatus,
  onBulkTags,
  onNewDeal,
  onNewDealFromDocuments,
  onSetDealType,
  onDealsChanged,
}: PipelinePageProps) {
  // Wave 2: every sort/filter knob lives in one state object so a saved view
  // captures all of it.
  const [view, setView] = useState<PipelineViewState>(DEFAULT_VIEW_STATE)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkStatusValue, setBulkStatusValue] = useState<DealStatus>('screening')
  const [bulkBusy, setBulkBusy] = useState(false)
  const [bulkTag, setBulkTag] = useState('')
  const [tagBusy, setTagBusy] = useState(false)
  // B13: saved views go through safeStorage (never throws).
  const [views, setViews] = useState<PipelineView[]>(() => loadViews(safeStorage))
  const [viewName, setViewName] = useState('')
  const [deckBusy, setDeckBusy] = useState(false)
  const [deckNote, setDeckNote] = useState<string | null>(null)
  // F2: archived deals are fetched on demand (includeArchived=true) and kept
  // apart from `deals` so counts, bulk actions and boards ignore them.
  const [showArchived, setShowArchived] = useState(false)
  const [archivedDeals, setArchivedDeals] = useState<Deal[]>([])

  useEffect(() => {
    if (!showArchived) {
      setArchivedDeals([])
      return
    }
    let cancelled = false
    fetchDeals({ includeArchived: true })
      .then((list) => {
        if (!cancelled) setArchivedDeals(list.filter((d) => Boolean(d.archivedAt)))
      })
      .catch((err) => {
        if (!cancelled) toastError(err, 'Could not load archived deals.')
      })
    return () => {
      cancelled = true
    }
  }, [showArchived, deals])

  async function handleUnarchive(dealId: string) {
    try {
      await unarchiveDeal(dealId)
      setArchivedDeals((prev) => prev.filter((d) => d.id !== dealId))
      onDealsChanged()
    } catch (err) {
      toastError(err, 'Could not unarchive the deal.')
    }
  }

  const sorted = useMemo(() => applyPipelineView(deals, view), [deals, view])
  const archivedByType = useMemo(
    () => ({
      acquisition: archivedDeals.filter((d) => dealTypeOf(d) === 'acquisition'),
      development: archivedDeals.filter((d) => dealTypeOf(d) === 'development'),
      untyped: archivedDeals.filter((d) => dealTypeOf(d) === null),
    }),
    [archivedDeals],
  )

  // The two dealflows, plus legacy deals that predate typed creation.
  const acquisitions = useMemo(
    () => sorted.filter((d) => dealTypeOf(d) === 'acquisition'),
    [sorted],
  )
  const developments = useMemo(
    () => sorted.filter((d) => dealTypeOf(d) === 'development'),
    [sorted],
  )
  const untyped = useMemo(() => sorted.filter((d) => dealTypeOf(d) === null), [sorted])
  const tagOptions = useMemo(() => allTags(deals).map((t) => t.tag), [deals])

  const hiddenCount = deals.length - sorted.length
  // Wave 2 (perf): memoised — a fresh array here used to defeat the
  // bulkOptions memo below on every render.
  const visibleSelected = useMemo(
    () => sorted.filter((d) => selected.has(d.id)),
    [sorted, selected],
  )
  // Bulk stage choices depend on WHAT is selected: one type -> its stages,
  // mixed -> only the shared stages.
  const bulkOptions = useMemo(() => bulkStageOptions(visibleSelected), [visibleSelected])
  const effectiveBulkValue = bulkOptions.includes(bulkStatusValue)
    ? bulkStatusValue
    : bulkOptions[0]

  function patchView(patch: Partial<PipelineViewState>) {
    setView((prev) => ({ ...prev, ...patch }))
  }

  function handleSort(key: PipelineSortKey) {
    setView((prev) => ({ ...prev, ...toggleSort(prev, key) }))
  }

  function toggle(dealId: string, checked: boolean) {
    const next = new Set(selected)
    if (checked) next.add(dealId)
    else next.delete(dealId)
    setSelected(next)
  }

  function selectAll(dealIds: string[], checked: boolean) {
    const next = new Set(selected)
    for (const id of dealIds) {
      if (checked) next.add(id)
      else next.delete(id)
    }
    setSelected(next)
  }

  async function handleBulk() {
    setBulkBusy(true)
    try {
      await onBulkStatus(
        visibleSelected.map((d) => d.id),
        effectiveBulkValue,
      )
      setSelected(new Set())
    } catch (err) {
      // B14: a failed bulk update used to reject silently.
      toastError(err, 'Bulk stage update failed.')
    } finally {
      setBulkBusy(false)
    }
  }

  async function handleBulkTag(mode: 'add' | 'remove') {
    const tag = normalizeTag(bulkTag)
    if (!tag) return
    setTagBusy(true)
    try {
      await onBulkTags(
        visibleSelected.map((d) => d.id),
        mode === 'add' ? [tag] : [],
        mode === 'remove' ? [tag] : [],
      )
      setBulkTag('')
    } catch (err) {
      toastError(err, `Bulk tag ${mode} failed.`)
    } finally {
      setTagBusy(false)
    }
  }

  async function handleExportDeck() {
    setDeckBusy(true)
    setDeckNote(null)
    try {
      // Ids in the pipeline's CURRENT sort so slide order matches the table.
      const { blob, skipped } = await exportBatchDeck(visibleSelected.map((d) => d.id))
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'screening-deck.pptx'
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      if (skipped.length > 0) {
        setDeckNote(`Skipped (no computable outputs): ${skipped.join(', ')}`)
      }
    } catch (err) {
      setDeckNote(err instanceof Error ? err.message : 'Deck export failed')
    } finally {
      setDeckBusy(false)
    }
  }

  function handleExportCsv() {
    const blob = new Blob([pipelineToCsv(sorted)], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'pipeline.csv'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  function handleApplyView(saved: PipelineView) {
    const { name: _name, ...rest } = saved
    setView(rest)
  }

  function handleSaveView() {
    if (!viewName.trim()) return
    setViews(saveView(safeStorage, { name: viewName.trim(), ...view }))
    setViewName('')
  }

  const filtersActive =
    view.stageFilter.length + view.stalenessFilter.length + view.tagFilter.length > 0

  return (
    <div className="max-w-4xl space-y-4">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <button
          onClick={onNewDealFromDocuments}
          className="shrink-0 rounded border border-slate-400 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
        >
          New deal from documents
        </button>
      </div>

      {/* J11: upcoming deadlines — overdue first (red), then the next 14 days. */}
      {(() => {
        const deadlines = upcomingDeadlines(deals, new Date())
        if (deadlines.length === 0) return null
        return (
          <div className="rounded border border-slate-200 bg-white px-3 py-2">
            <div className="text-[11px] font-semibold tracking-wide text-slate-400">
              UPCOMING DEADLINES (14 DAYS)
            </div>
            <div className="mt-1 flex flex-wrap gap-2">
              {deadlines.map((entry) => (
                <button
                  key={`${entry.dealId}-${entry.row.id}`}
                  onClick={() => onOpenDeal(entry.dealId)}
                  title={entry.row.notes || undefined}
                  className={`rounded px-2 py-1 text-xs ${
                    entry.status === 'overdue'
                      ? 'bg-red-100 text-red-700'
                      : 'bg-amber-50 text-amber-700'
                  }`}
                >
                  {entry.dealName}: {entry.row.label} {entry.row.date}
                  {entry.status === 'overdue'
                    ? ` (${-entry.days}d overdue)`
                    : entry.days === 0
                      ? ' (today)'
                      : ` (in ${entry.days}d)`}
                </button>
              ))}
            </div>
          </div>
        )
      })()}

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <input
          value={view.marketFilter}
          onChange={(e) => patchView({ marketFilter: e.target.value })}
          placeholder="Filter by market or name"
          aria-label="Filter by market or name"
          className="rounded border border-slate-200 px-2 py-1"
        />
        <label className="flex items-center gap-1 text-slate-500">
          Sort
          <select
            value={view.sortKey}
            onChange={(e) => {
              const key = e.target.value as PipelineSortKey
              patchView({ sortKey: key, sortDir: DEFAULT_SORT_DIR[key] })
            }}
            className="rounded border border-slate-200 px-1 py-1"
          >
            <option value="stage">Stage</option>
            <option value="updated">Recently touched</option>
            <option value="name">Name</option>
            <option value="market">Market</option>
            <option value="staleness">Staleness</option>
          </select>
          <button
            type="button"
            onClick={() => patchView({ sortDir: view.sortDir === 'asc' ? 'desc' : 'asc' })}
            aria-label={`Sort direction: ${view.sortDir === 'asc' ? 'ascending' : 'descending'} (click to flip)`}
            className="rounded border border-slate-200 px-1.5 py-1 text-slate-500 hover:text-slate-600"
          >
            {view.sortDir === 'asc' ? '▲' : '▼'}
          </button>
        </label>
        <button
          onClick={() => patchView({ showTerminal: !view.showTerminal })}
          className={`rounded border px-2 py-1 ${
            view.showTerminal
              ? 'border-slate-400 bg-slate-100 text-slate-600'
              : 'border-slate-200 text-slate-400 hover:text-slate-600'
          }`}
        >
          {view.showTerminal
            ? 'Hiding nothing'
            : `Closed/stabilized/dead hidden${hiddenCount ? ` (${hiddenCount})` : ''}`}
        </button>
        <button
          onClick={() => setShowArchived((v) => !v)}
          aria-pressed={showArchived}
          className={`rounded border px-2 py-1 ${
            showArchived
              ? 'border-slate-400 bg-slate-100 text-slate-600'
              : 'border-slate-200 text-slate-400 hover:text-slate-600'
          }`}
        >
          {showArchived ? `Showing archived (${archivedDeals.length})` : 'Show archived'}
        </button>
        <button
          onClick={handleExportCsv}
          className="rounded border border-slate-200 px-2 py-1 text-slate-500 hover:bg-slate-50"
        >
          Export CSV ({sorted.length})
        </button>
        <span className="mx-1 h-4 border-l border-slate-200" />
        {views.map((saved) => (
          <span key={saved.name} className="flex items-center rounded bg-sky-50 text-sky-700">
            <button onClick={() => handleApplyView(saved)} className="px-2 py-1 hover:underline">
              {saved.name}
            </button>
            <button
              onClick={() => setViews(deleteView(safeStorage, saved.name))}
              aria-label={`Delete saved view ${saved.name}`}
              className="pr-1.5 text-sky-400 hover:text-red-600"
            >
              ×
            </button>
          </span>
        ))}
        <input
          value={viewName}
          onChange={(e) => setViewName(e.target.value)}
          placeholder="Save view as…"
          aria-label="Name for the saved view"
          className="w-28 rounded border border-slate-200 px-2 py-1"
        />
        <button
          onClick={handleSaveView}
          disabled={!viewName.trim()}
          className="rounded border border-emerald-600 px-2 py-1 text-emerald-700 hover:bg-emerald-50 disabled:opacity-40"
        >
          Save
        </button>
      </div>

      {/* Wave 2: stage / staleness / tag filters (all AND-ed together). */}
      <div className="flex flex-wrap items-center gap-4 text-xs">
        <FilterChips
          label="Stage"
          options={ALL_STAGES}
          selected={view.stageFilter}
          onToggle={(stage) =>
            patchView({ stageFilter: toggleTag(view.stageFilter, stage) as DealStatus[] })
          }
          render={(stage) => STAGE_LABELS[stage]}
          chipClass={(stage) => STAGE_STYLES[stage]}
        />
        <FilterChips
          label="Staleness"
          options={STALENESS_LEVELS}
          selected={view.stalenessFilter}
          onToggle={(level) =>
            patchView({ stalenessFilter: toggleTag(view.stalenessFilter, level) as StalenessLevel[] })
          }
          render={(level) => STALENESS_LABELS[level]}
          chipClass={(level) =>
            level === 'critical'
              ? 'bg-red-100 text-red-700'
              : level === 'stale'
                ? 'bg-amber-100 text-amber-700'
                : 'bg-emerald-100 text-emerald-700'
          }
        />
        <FilterChips
          label="Tags"
          options={tagOptions}
          selected={view.tagFilter}
          onToggle={(tag) => patchView({ tagFilter: toggleTag(view.tagFilter, tag) })}
        />
        {filtersActive && (
          <button
            type="button"
            onClick={() => patchView({ stageFilter: [], stalenessFilter: [], tagFilter: [] })}
            className="text-slate-400 hover:text-slate-600"
          >
            Clear filters
          </button>
        )}
      </div>

      {visibleSelected.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded border border-sky-200 bg-sky-50 px-3 py-2 text-xs">
          <span className="text-sky-700">{visibleSelected.length} selected</span>
          <select
            value={effectiveBulkValue}
            aria-label="Stage to apply to the selection"
            onChange={(e) => setBulkStatusValue(e.target.value as DealStatus)}
            className="rounded border border-slate-200 px-1 py-1"
          >
            {bulkOptions.map((stage) => (
              <option key={stage} value={stage}>
                {STAGE_LABELS[stage]}
              </option>
            ))}
          </select>
          <button
            onClick={() => void handleBulk()}
            disabled={bulkBusy}
            className="rounded bg-sky-600 px-2 py-1 text-white hover:bg-sky-700 disabled:opacity-40"
          >
            {bulkBusy ? 'Updating…' : 'Set stage'}
          </button>
          <span className="mx-1 h-4 border-l border-sky-200" />
          <input
            value={bulkTag}
            onChange={(e) => setBulkTag(e.target.value)}
            placeholder="Tag…"
            aria-label="Tag to add to or remove from the selection"
            list="pipeline-tag-options"
            className="w-24 rounded border border-slate-200 px-2 py-1"
          />
          <datalist id="pipeline-tag-options">
            {tagOptions.map((tag) => (
              <option key={tag} value={tag} />
            ))}
          </datalist>
          <button
            onClick={() => void handleBulkTag('add')}
            disabled={tagBusy || !normalizeTag(bulkTag)}
            className="rounded border border-slate-400 px-2 py-1 text-slate-600 hover:bg-slate-100 disabled:opacity-40"
          >
            Add tag
          </button>
          <button
            onClick={() => void handleBulkTag('remove')}
            disabled={tagBusy || !normalizeTag(bulkTag)}
            className="rounded border border-slate-400 px-2 py-1 text-slate-600 hover:bg-slate-100 disabled:opacity-40"
          >
            Remove tag
          </button>
          <button
            onClick={() => void handleExportDeck()}
            disabled={deckBusy}
            className="rounded border border-slate-400 px-2 py-1 text-slate-600 hover:bg-slate-100 disabled:opacity-40"
          >
            {deckBusy ? 'Building deck…' : 'Export screening deck'}
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="text-slate-400 hover:text-slate-600"
          >
            Clear
          </button>
        </div>
      )}
      {deckNote && <div className="text-xs text-amber-600">{deckNote}</div>}

      <Board
        type="acquisition"
        deals={acquisitions}
        archivedDeals={archivedByType.acquisition}
        hiddenCount={hiddenCount}
        activeDealId={activeDealId}
        selected={selected}
        sortKey={view.sortKey}
        sortDir={view.sortDir}
        onSort={handleSort}
        onToggle={toggle}
        onSelectAll={selectAll}
        onOpenDeal={onOpenDeal}
        onStatusChange={onStatusChange}
        onNewDeal={onNewDeal}
        onUnarchive={(id) => void handleUnarchive(id)}
      />

      <Board
        type="development"
        deals={developments}
        archivedDeals={archivedByType.development}
        hiddenCount={hiddenCount}
        activeDealId={activeDealId}
        selected={selected}
        sortKey={view.sortKey}
        sortDir={view.sortDir}
        onSort={handleSort}
        onToggle={toggle}
        onSelectAll={selectAll}
        onOpenDeal={onOpenDeal}
        onStatusChange={onStatusChange}
        onNewDeal={onNewDeal}
        onUnarchive={(id) => void handleUnarchive(id)}
      />

      {archivedByType.untyped.length > 0 && (
        <div className="rounded border border-slate-200 bg-white p-3 opacity-60">
          <div className="text-xs font-semibold text-slate-500">ARCHIVED — UNTYPED</div>
          <ul className="mt-2 space-y-1">
            {archivedByType.untyped.map((deal) => (
              <li key={deal.id} className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-medium text-slate-600">{deal.name}</span>
                <button
                  onClick={() => void handleUnarchive(deal.id)}
                  className="rounded border border-slate-200 px-2 py-0.5 text-slate-600 hover:bg-slate-50"
                >
                  Unarchive
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {untyped.length > 0 && (
        <div className="rounded border border-amber-200 bg-amber-50 p-3">
          <div className="text-xs font-semibold text-amber-700">
            UNTYPED DEALS — assign a dealflow
          </div>
          <p className="mt-0.5 text-[11px] text-amber-600">
            These predate typed creation. Pick which pipeline each belongs to;
            nothing is assumed automatically.
          </p>
          <ul className="mt-2 space-y-1">
            {untyped.map((deal) => (
              <li key={deal.id} className="flex flex-wrap items-center gap-2 text-xs">
                <button
                  onClick={() => onOpenDeal(deal.id)}
                  className="font-medium text-slate-700 hover:underline"
                >
                  {deal.name}
                </button>
                <TagChips tags={dealTags(deal)} />
                <span className="text-slate-400">{relativeAge(deal.updatedAt)}</span>
                <button
                  onClick={() => onSetDealType(deal.id, 'acquisition')}
                  className="rounded border border-sky-400 px-2 py-0.5 text-sky-700 hover:bg-sky-50"
                >
                  Acquisition
                </button>
                <button
                  onClick={() => onSetDealType(deal.id, 'development')}
                  className="rounded border border-orange-400 px-2 py-0.5 text-orange-700 hover:bg-orange-50"
                >
                  Development
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
