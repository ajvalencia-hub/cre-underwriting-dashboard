import { useEffect, useMemo, useState } from 'react'
import {
  bulkUpdateDealTags,
  exportBatchDeck,
  fetchDealMetrics,
  fetchDeals,
  fetchIcStates,
  unarchiveDeal,
  type DealMetrics,
  type IcState,
} from '../lib/api'
import { IC_STATE_LABELS, IC_STATE_STYLES } from '../lib/icWorkflow'
import { formatMoneyCompact } from '../lib/money'
import { upcomingDeadlines } from '../lib/criticalDates'
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
import {
  DEFAULT_SORT_DIR,
  DEFAULT_VIEW_STATE,
  STALENESS_LABELS,
  STALENESS_LEVELS,
  applyPipelineView,
  dealMarket,
  deleteView,
  filterDeals,
  loadViews,
  pipelineToCsv,
  saveView,
  toggleSort,
  type MetricSortKey,
  type PipelineSortKey,
  type PipelineView,
  type PipelineViewState,
  type SortDir,
  type StalenessLevel,
} from '../lib/pipelineViews'
import { safeStorage } from '../lib/safeStorage'
import { allTags, dealTags, parseTagInput, toggleTag } from '../lib/tags'
import type { Deal, DealStatus } from '../types/deal'
import ServerFileLink from '../components/ServerFileLink'
import { saveOutput, textBlob } from '../lib/saveOutput'
import { toastError } from '../lib/toast'

interface PipelinePageProps {
  deals: Deal[]
  activeDealId: string | null
  onOpenDeal: (dealId: string) => void
  onStatusChange: (dealId: string, status: DealStatus) => void
  onBulkStatus: (dealIds: string[], status: DealStatus) => Promise<void>
  /** Typed creation — every new deal knows its dealflow from birth. */
  onNewDeal: (type: DealType) => void
  /** J10: opens the OM-to-deal wizard. */
  onNewDealFromDocuments: () => void
  /** Assign a type to an untyped (legacy) deal. */
  onSetDealType: (dealId: string, type: DealType) => void
  /** The tab is showing — refresh the per-deal numbers. */
  active: boolean
  /** Deals this page changed server-side (bulk tags, unarchive — the reply's
   *  copies). App upserts them into its list by id (an unarchived deal
   *  rejoins it). Until App catches up the page overlays its own copies. */
  onDealsChanged?: (deals: Deal[]) => void
}

// Optional numeric columns (roadmap #18), remembered per browser.
const METRIC_COLUMNS: { id: MetricSortKey; label: string }[] = [
  { id: 'totalCost', label: 'Total cost' },
  { id: 'equity', label: 'Equity' },
  { id: 'leveredIrr', label: 'Levered IRR' },
  { id: 'equityMultiple', label: 'Equity multiple' },
  { id: 'yield', label: 'Going-in cap / YoC' },
]
type MetricColumn = MetricSortKey
const COLUMNS_KEY = 'cre.pipelineColumns'
const DEFAULT_COLUMNS: MetricColumn[] = ['totalCost', 'equity', 'leveredIrr', 'yield']

function validColumns(raw: unknown): MetricColumn[] | null {
  if (!Array.isArray(raw)) return null
  // Canonical order, known ids only.
  return METRIC_COLUMNS.map((c) => c.id).filter((id) => raw.includes(id))
}

function loadColumns(): MetricColumn[] {
  try {
    return validColumns(JSON.parse(safeStorage.get(COLUMNS_KEY) ?? 'null')) ?? DEFAULT_COLUMNS
  } catch {
    return DEFAULT_COLUMNS
  }
}

function metricNumber(column: MetricColumn, type: DealType, m: DealMetrics | undefined): number | null {
  if (!m || m.status !== 'ok') return null
  switch (column) {
    case 'totalCost':
      return m.totalCost
    case 'equity':
      return m.equity
    case 'leveredIrr':
      return m.leveredIrr
    case 'equityMultiple':
      return m.equityMultiple
    case 'yield':
      return type === 'development' ? m.yieldOnCost : m.goingInCapRate
  }
}

function metricCell(column: MetricColumn, type: DealType, m: DealMetrics | undefined): string {
  const v = metricNumber(column, type, m)
  if (v == null) return '—'
  switch (column) {
    case 'totalCost':
    case 'equity':
      return formatMoneyCompact(v)
    case 'equityMultiple':
      return `${v.toFixed(2)}x`
    case 'leveredIrr':
    case 'yield':
      return `${(v * 100).toFixed(2)}%`
  }
}

function metricHeader(column: MetricColumn, type: DealType): string {
  if (column === 'yield') return type === 'development' ? 'Yield on cost' : 'Going-in cap'
  return METRIC_COLUMNS.find((m) => m.id === column)?.label ?? column
}

const SORT_LABELS: Record<PipelineSortKey, string> = {
  stage: 'Stage',
  updated: 'Recently touched',
  name: 'Name',
  market: 'Market',
  staleness: 'Staleness',
  totalCost: 'Total cost',
  equity: 'Equity',
  leveredIrr: 'Levered IRR',
  equityMultiple: 'Equity multiple',
  yield: 'Going-in cap / YoC',
}

const BOARD_META: Record<DealType, { title: string; accent: string }> = {
  acquisition: { title: 'Acquisitions', accent: 'text-sky-700' },
  development: { title: 'Developments', accent: 'text-orange-700' },
}

/** Sortable column header: aria-sort on the <th>, the click target a real
 *  button so it is keyboard-reachable. */
function SortHeader({
  sortKey: key,
  label,
  current,
  onSort,
  align = 'left',
}: {
  sortKey: PipelineSortKey
  label: string
  current: { sortKey: PipelineSortKey; sortDir: SortDir }
  onSort: (key: PipelineSortKey) => void
  align?: 'left' | 'right'
}) {
  const active = current.sortKey === key
  return (
    <th
      scope="col"
      aria-sort={active ? (current.sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
      className={`px-3 py-2 font-medium ${align === 'right' ? 'text-right' : ''}`}
    >
      <button
        type="button"
        onClick={() => onSort(key)}
        className={`inline-flex items-center gap-1 hover:text-slate-600 ${active ? 'text-slate-600' : ''}`}
      >
        {label}
        <span aria-hidden="true" className={active ? '' : 'opacity-30'}>
          {active ? (current.sortDir === 'asc' ? '▲' : '▼') : '▵'}
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
        <span key={tag} className="rounded bg-slate-100 px-1 py-0.5 text-[10px] text-slate-600">
          {tag}
        </span>
      ))}
    </span>
  )
}

function StalenessCell({ deal }: { deal: Deal }) {
  const badge = stalenessBadge(deal.status, deal.updatedAt)
  if (!badge) return null
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] ${
        badge.tone === 'red' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
      }`}
    >
      △ {badge.label}
    </span>
  )
}

interface BoardProps {
  type: DealType
  deals: Deal[]
  /** Archived deals of this type (only while "Show archived" is on):
   *  dimmed, never counted, never selectable. */
  archivedDeals: Deal[]
  hiddenCount: number
  activeDealId: string | null
  selected: Set<string>
  sort: { sortKey: PipelineSortKey; sortDir: SortDir }
  onSort: (key: PipelineSortKey) => void
  onToggle: (dealId: string, checked: boolean) => void
  onSelectAll: (dealIds: string[], checked: boolean) => void
  onOpenDeal: (dealId: string) => void
  onStatusChange: (dealId: string, status: DealStatus) => void
  onNewDeal: (type: DealType) => void
  onUnarchive: (dealId: string) => void
  metrics: Record<string, DealMetrics> | null
  /** Investment-committee state of deals past draft. */
  icStates: Record<string, IcState>
  columns: MetricColumn[]
}

/** One dealflow board: its own stage chips, counts, and stage dropdowns. */
function Board({
  type, deals, archivedDeals, hiddenCount, activeDealId, selected, sort, onSort,
  onToggle, onSelectAll, onOpenDeal, onStatusChange, onNewDeal, onUnarchive, metrics, icStates, columns,
}: BoardProps) {
  const stages = stagesFor(type)
  const counts = new Map<DealStatus, number>()
  for (const deal of deals) counts.set(deal.status, (counts.get(deal.status) ?? 0) + 1)
  const visibleSelected = deals.filter((d) => selected.has(d.id))
  const colCount = 7 + columns.length

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
        <table className="w-full min-w-[600px] text-sm" aria-label={BOARD_META[type].title}>
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
              <th className="w-8 px-3 py-2">
                <input
                  type="checkbox"
                  aria-label={`Select all visible ${type} deals`}
                  checked={deals.length > 0 && visibleSelected.length === deals.length}
                  onChange={(e) => onSelectAll(deals.map((d) => d.id), e.target.checked)}
                />
              </th>
              <SortHeader sortKey="name" label="Deal" current={sort} onSort={onSort} />
              <SortHeader sortKey="market" label="Market" current={sort} onSort={onSort} />
              <SortHeader sortKey="stage" label="Stage" current={sort} onSort={onSort} />
              <SortHeader sortKey="updated" label="Last touched" current={sort} onSort={onSort} />
              <SortHeader sortKey="staleness" label="Staleness" current={sort} onSort={onSort} />
              {columns.map((c) => (
                <SortHeader
                  key={c}
                  sortKey={c}
                  label={metricHeader(c, type)}
                  current={sort}
                  onSort={onSort}
                  align="right"
                />
              ))}
              <th className="px-3 py-2">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {deals.map((deal) => {
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
                    {icStates[deal.id] && (
                      <span className={`ml-2 rounded px-1 py-0.5 text-[10px] font-semibold ${IC_STATE_STYLES[icStates[deal.id]]}`}>
                        {IC_STATE_LABELS[icStates[deal.id]]}
                      </span>
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
                  <td className="px-3 py-2">
                    <StalenessCell deal={deal} />
                  </td>
                  {columns.map((c) => {
                    const m = metrics?.[deal.id]
                    return (
                      <td
                        key={c}
                        className="px-3 py-2 text-right tabular-nums text-slate-700"
                        title={m?.status === 'incomplete' ? `Can't compute yet — missing: ${m.missing.join(', ')}` : undefined}
                      >
                        {m?.status === 'incomplete' ? <span className="text-xs text-slate-500">incomplete</span> : metricCell(c, type, m)}
                      </td>
                    )
                  })}
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <ServerFileLink
                      href={`/api/deals/${deal.id}/share.html`}
                      filename={`${deal.name}.html`}
                      newTab
                      title="Self-contained read-only HTML snapshot"
                      className="mr-2 text-xs text-slate-500 hover:text-sky-700 hover:underline"
                    >
                      Share
                    </ServerFileLink>
                    <ServerFileLink
                      href={`/api/deals/${deal.id}/deck.pptx`}
                      filename={`${deal.name} deck.pptx`}
                      title="One-page investment summary (PowerPoint)"
                      className="mr-2 text-xs text-slate-500 hover:text-sky-700 hover:underline"
                    >
                      Deck
                    </ServerFileLink>
                    <ServerFileLink
                      href={`/api/deals/${deal.id}/ic-deck.pptx`}
                      filename={`${deal.name} IC deck.pptx`}
                      title="Full 8-slide IC deck (PowerPoint)"
                      className="mr-2 text-xs text-slate-500 hover:text-sky-700 hover:underline"
                    >
                      IC deck
                    </ServerFileLink>
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
                <td colSpan={colCount} className="px-3 py-6 text-center text-sm text-slate-500">
                  No {type} deals{hiddenCount > 0 ? ' in this view' : ' yet'}.
                </td>
              </tr>
            )}
            {archivedDeals.map((deal) => (
              <ArchivedRow key={deal.id} deal={deal} columns={columns.length} onUnarchive={onUnarchive} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ArchivedRow({ deal, columns, onUnarchive }: { deal: Deal; columns: number; onUnarchive: (id: string) => void }) {
  return (
    <tr className="border-b border-slate-50 opacity-60" data-archived="true">
      <td className="px-3 py-2" />
      <td className="px-3 py-2">
        <span className="font-medium text-slate-600">{deal.name}</span>
        <span className="ml-2 rounded bg-slate-200 px-1.5 py-0.5 text-[10px] text-slate-600">archived</span>
        <TagChips tags={dealTags(deal)} />
      </td>
      <td className="px-3 py-2 text-slate-500">{dealMarket(deal) || '—'}</td>
      <td className="px-3 py-2 text-xs text-slate-500">{STAGE_LABELS[deal.status]}</td>
      <td className="px-3 py-2 text-slate-500">
        {deal.archivedAt ? `archived ${relativeAge(deal.archivedAt)}` : relativeAge(deal.updatedAt)}
      </td>
      <td className="px-3 py-2" />
      {Array.from({ length: columns }, (_, i) => (
        <td key={i} className="px-3 py-2" />
      ))}
      <td className="px-3 py-2 text-right">
        <button
          type="button"
          onClick={() => onUnarchive(deal.id)}
          aria-label={`Unarchive ${deal.name}`}
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-50"
        >
          Unarchive
        </button>
      </td>
    </tr>
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
  options: readonly T[]
  selected: readonly T[]
  onToggle: (value: T) => void
  render?: (value: T) => string
  chipClass?: (value: T) => string
}) {
  if (options.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-1" role="group" aria-label={`Filter by ${label}`}>
      <span className="text-[10px] font-semibold tracking-wide text-slate-500">{label.toUpperCase()}</span>
      {options.map((value) => {
        const on = selected.some((s) => s.toLowerCase() === value.toLowerCase())
        return (
          <button
            key={value}
            type="button"
            onClick={() => onToggle(value)}
            aria-pressed={on}
            className={`rounded border px-1.5 py-0.5 text-[11px] ${
              on ? `border-slate-400 ${chipClass(value)}` : 'border-slate-200 text-slate-500 hover:text-slate-700'
            }`}
          >
            {render(value)}
          </button>
        )
      })}
    </div>
  )
}

/** App's list with this page's newer server copies laid over it (bulk tags,
 *  unarchive) — until App's own list catches up. */
function overlayDeals(deals: Deal[], overrides: Map<string, Deal>): Deal[] {
  if (overrides.size === 0) return deals
  const seen = new Set<string>()
  const merged = deals.map((d) => {
    seen.add(d.id)
    const o = overrides.get(d.id)
    return o && Date.parse(o.updatedAt) >= Date.parse(d.updatedAt) ? o : d
  })
  const rejoined = [...overrides.values()].filter((o) => !seen.has(o.id) && !o.archivedAt)
  return rejoined.length ? [...rejoined, ...merged] : merged
}

export default function PipelinePage({
  deals: appDeals,
  activeDealId,
  onOpenDeal,
  onStatusChange,
  onBulkStatus,
  onNewDeal,
  onNewDealFromDocuments,
  onSetDealType,
  active,
  onDealsChanged,
}: PipelinePageProps) {
  const [overrides, setOverrides] = useState<Map<string, Deal>>(() => new Map())
  const deals = useMemo(() => overlayDeals(appDeals.filter((d) => !d.archivedAt), overrides), [appDeals, overrides])
  const [metrics, setMetrics] = useState<Record<string, DealMetrics> | null>(null)
  const [icStates, setIcStates] = useState<Record<string, IcState>>({})
  const [columns, setColumns] = useState<MetricColumn[]>(loadColumns)
  const dealsKey = deals.map((d) => `${d.id}:${d.updatedAt}`).join('|')
  useEffect(() => {
    if (!active) return
    fetchDealMetrics().then(setMetrics).catch(() => setMetrics(null))
    fetchIcStates().then(setIcStates).catch(() => setIcStates({}))
  }, [active, dealsKey])

  function applyColumns(next: MetricColumn[]) {
    setColumns(next)
    // storage unavailable — the choice just isn't remembered
    safeStorage.set(COLUMNS_KEY, JSON.stringify(next))
  }
  function toggleColumn(id: MetricColumn, on: boolean) {
    applyColumns(METRIC_COLUMNS.map((c) => c.id).filter((c) => (c === id ? on : columns.includes(c))))
  }

  const [view, setView] = useState<Omit<PipelineViewState, 'columns'>>(DEFAULT_VIEW_STATE)
  function patchView(patch: Partial<Omit<PipelineViewState, 'columns'>>) {
    setView((prev) => ({ ...prev, ...patch }))
  }
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkStatusValue, setBulkStatusValue] = useState<DealStatus>('screening')
  const [bulkBusy, setBulkBusy] = useState(false)
  const [bulkTag, setBulkTag] = useState('')
  const [tagBusy, setTagBusy] = useState(false)
  const [views, setViews] = useState<PipelineView[]>(() => loadViews(safeStorage))
  const [viewName, setViewName] = useState('')
  const [deckBusy, setDeckBusy] = useState(false)
  const [deckNote, setDeckNote] = useState<string | null>(null)

  // Archived deals are fetched on demand (includeArchived) and refetched
  // when the working list changes (an archive in the header, an unarchive
  // here).
  const [showArchived, setShowArchived] = useState(false)
  const [archivedDeals, setArchivedDeals] = useState<Deal[]>([])
  const appKey = appDeals.map((d) => `${d.id}:${d.updatedAt}`).join('|')
  useEffect(() => {
    if (!showArchived) return
    let current = true
    fetchDeals({ includeArchived: true })
      .then((list) => {
        if (current) setArchivedDeals(list.filter((d) => Boolean(d.archivedAt)))
      })
      .catch((err) => {
        if (current) toastError("Couldn't load the archived deals", err)
      })
    return () => {
      current = false
    }
  }, [showArchived, appKey])

  const metricOf = useMemo(
    () => (deal: Deal, key: MetricSortKey) => metricNumber(key, dealTypeOf(deal) ?? 'acquisition', metrics?.[deal.id]),
    [metrics],
  )
  const sorted = useMemo(() => applyPipelineView(deals, view, Date.now(), metricOf), [deals, view, metricOf])
  const archivedShown = useMemo(
    () =>
      showArchived
        ? filterDeals(
            // A deal unarchived here stays hidden until the refetch lands.
            archivedDeals.filter((d) => !overrides.get(d.id) || overrides.get(d.id)!.archivedAt),
            { ...view, showTerminal: true },
          )
        : [],
    [showArchived, archivedDeals, overrides, view],
  )

  // The two dealflows, plus legacy deals that predate typed creation.
  const acquisitions = useMemo(() => sorted.filter((d) => dealTypeOf(d) === 'acquisition'), [sorted])
  const developments = useMemo(() => sorted.filter((d) => dealTypeOf(d) === 'development'), [sorted])
  const untyped = useMemo(() => sorted.filter((d) => dealTypeOf(d) === null), [sorted])
  const archivedByType = useMemo(
    () => ({
      acquisition: archivedShown.filter((d) => dealTypeOf(d) === 'acquisition'),
      development: archivedShown.filter((d) => dealTypeOf(d) === 'development'),
      untyped: archivedShown.filter((d) => dealTypeOf(d) === null),
    }),
    [archivedShown],
  )
  const tagOptions = useMemo(
    () => allTags(showArchived ? [...deals, ...archivedDeals] : deals).map((t) => t.tag),
    [deals, archivedDeals, showArchived],
  )

  const hiddenCount = deals.length - sorted.length
  const visibleSelected = useMemo(() => sorted.filter((d) => selected.has(d.id)), [sorted, selected])
  // Bulk stage choices depend on WHAT is selected: one type -> its stages,
  // mixed -> only the shared stages.
  const bulkOptions = useMemo(() => bulkStageOptions(visibleSelected), [visibleSelected])
  const effectiveBulkValue = bulkOptions.includes(bulkStatusValue)
    ? bulkStatusValue
    : bulkOptions[0]

  function adopt(updated: Deal[]) {
    if (updated.length === 0) return
    setOverrides((prev) => {
      const next = new Map(prev)
      for (const d of updated) next.set(d.id, d)
      return next
    })
    onDealsChanged?.(updated)
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
    } finally {
      setBulkBusy(false)
    }
  }

  async function handleBulkTag(mode: 'add' | 'remove') {
    const tags = parseTagInput(bulkTag)
    if (tags.length === 0 || visibleSelected.length === 0) return
    setTagBusy(true)
    try {
      const { updated } = await bulkUpdateDealTags(
        visibleSelected.map((d) => d.id),
        mode === 'add' ? tags : [],
        mode === 'remove' ? tags : [],
      )
      adopt(updated)
      setBulkTag('')
    } catch (err) {
      toastError(
        mode === 'add'
          ? `Couldn't tag ${visibleSelected.length} deal(s) — none were changed`
          : `Couldn't untag ${visibleSelected.length} deal(s) — none were changed`,
        err,
      )
    } finally {
      setTagBusy(false)
    }
  }

  async function handleUnarchive(dealId: string) {
    try {
      const deal = await unarchiveDeal(dealId)
      setArchivedDeals((prev) => prev.filter((d) => d.id !== dealId))
      adopt([deal])
    } catch (err) {
      toastError("Couldn't unarchive the deal", err)
    }
  }

  async function handleExportDeck() {
    setDeckBusy(true)
    setDeckNote(null)
    try {
      // Ids in the pipeline's CURRENT sort so slide order matches the table.
      const { blob, skipped } = await exportBatchDeck(visibleSelected.map((d) => d.id))
      await saveOutput(blob, 'screening-deck.pptx')
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
    saveOutput(textBlob(pipelineToCsv(sorted), 'text/csv'), 'pipeline.csv').catch((err) =>
      toastError('Could not save pipeline.csv', err),
    )
  }

  function handleApplyView(saved: PipelineView) {
    const { name: _name, columns: savedColumns, ...rest } = saved
    setView(rest)
    const cols = validColumns(savedColumns)
    if (cols) applyColumns(cols)
  }

  function handleSaveView() {
    if (!viewName.trim()) return
    setViews(saveView(safeStorage, { name: viewName.trim(), ...view, columns }))
    setViewName('')
  }

  const sortState = { sortKey: view.sortKey, sortDir: view.sortDir }
  const onSort = (key: PipelineSortKey) => patchView(toggleSort(sortState, key))
  const filtersActive = view.stageFilter.length + view.stalenessFilter.length + view.tagFilter.length > 0
  const tagInputValid = parseTagInput(bulkTag).length > 0

  const boardProps = {
    hiddenCount,
    activeDealId,
    selected,
    sort: sortState,
    onSort,
    onToggle: toggle,
    onSelectAll: selectAll,
    onOpenDeal,
    onStatusChange,
    onNewDeal,
    onUnarchive: (id: string) => void handleUnarchive(id),
    metrics,
    icStates,
    columns,
  }

  return (
    <div className="max-w-5xl space-y-4">
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
            <div className="text-[11px] font-semibold tracking-wide text-slate-500">
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
            {(Object.keys(SORT_LABELS) as PipelineSortKey[]).map((key) => (
              <option key={key} value={key}>
                {SORT_LABELS[key]}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => patchView({ sortDir: view.sortDir === 'asc' ? 'desc' : 'asc' })}
          aria-label={`Sort direction: ${view.sortDir === 'asc' ? 'ascending' : 'descending'} (click to flip)`}
          className="rounded border border-slate-200 px-1.5 py-1 text-slate-500 hover:text-slate-700"
        >
          {view.sortDir === 'asc' ? '▲' : '▼'}
        </button>
        <details className="relative">
          <summary className="cursor-pointer rounded border border-slate-200 px-2 py-1 text-slate-600 hover:bg-slate-50">
            Columns
          </summary>
          <div className="absolute z-10 mt-1 w-48 rounded border border-slate-200 bg-white p-2 shadow-sm">
            {METRIC_COLUMNS.map((c) => (
              <label key={c.id} className="flex items-center gap-2 py-0.5 text-slate-700">
                <input type="checkbox" checked={columns.includes(c.id)} onChange={(e) => toggleColumn(c.id, e.target.checked)} />
                {c.label}
              </label>
            ))}
          </div>
        </details>
        <button
          onClick={() => patchView({ showTerminal: !view.showTerminal })}
          className={`rounded border px-2 py-1 ${
            view.showTerminal
              ? 'border-slate-400 bg-slate-100 text-slate-600'
              : 'border-slate-200 text-slate-500 hover:text-slate-700'
          }`}
        >
          {view.showTerminal
            ? 'Hiding nothing'
            : `Closed/stabilized/dead hidden${hiddenCount ? ` (${hiddenCount})` : ''}`}
        </button>
        <button
          type="button"
          onClick={() => setShowArchived((v) => !v)}
          aria-pressed={showArchived}
          className={`rounded border px-2 py-1 ${
            showArchived
              ? 'border-slate-400 bg-slate-100 text-slate-600'
              : 'border-slate-200 text-slate-500 hover:text-slate-700'
          }`}
        >
          {showArchived ? `Show archived (${archivedShown.length})` : 'Show archived'}
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

      {/* Stage / staleness / tag filters (all AND-ed together; a deal must
          carry every selected tag). */}
      <div className="flex flex-wrap items-center gap-4 text-xs">
        <FilterChips
          label="Stage"
          options={ALL_STAGES}
          selected={view.stageFilter}
          onToggle={(stage) => patchView({ stageFilter: toggleTag(view.stageFilter, stage) as DealStatus[] })}
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
            className="text-slate-500 hover:text-slate-700"
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
            onChange={(e) => setBulkStatusValue(e.target.value as DealStatus)}
            aria-label="Stage to apply to the selection"
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
            onKeyDown={(e) => {
              if (e.key === 'Enter' && tagInputValid && !tagBusy) void handleBulkTag('add')
            }}
            placeholder="Tag…"
            aria-label="Tag to add to or remove from the selection"
            list="pipeline-tag-options"
            className="w-28 rounded border border-slate-200 px-2 py-1"
          />
          <datalist id="pipeline-tag-options">
            {tagOptions.map((tag) => (
              <option key={tag} value={tag} />
            ))}
          </datalist>
          <button
            type="button"
            onClick={() => void handleBulkTag('add')}
            disabled={tagBusy || !tagInputValid}
            className="rounded border border-slate-400 px-2 py-1 text-slate-600 hover:bg-slate-100 disabled:opacity-40"
          >
            Add tag
          </button>
          <button
            type="button"
            onClick={() => void handleBulkTag('remove')}
            disabled={tagBusy || !tagInputValid}
            className="rounded border border-slate-400 px-2 py-1 text-slate-600 hover:bg-slate-100 disabled:opacity-40"
          >
            Remove tag
          </button>
          <span className="mx-1 h-4 border-l border-sky-200" />
          <button
            onClick={() => void handleExportDeck()}
            disabled={deckBusy}
            className="rounded border border-slate-400 px-2 py-1 text-slate-600 hover:bg-slate-100 disabled:opacity-40"
          >
            {deckBusy ? 'Building deck…' : 'Export screening deck'}
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="text-slate-500 hover:text-slate-700"
          >
            Clear
          </button>
        </div>
      )}
      {deckNote && <div className="text-xs text-amber-600">{deckNote}</div>}

      <Board type="acquisition" deals={acquisitions} archivedDeals={archivedByType.acquisition} {...boardProps} />

      <Board type="development" deals={developments} archivedDeals={archivedByType.development} {...boardProps} />

      {(untyped.length > 0 || archivedByType.untyped.length > 0) && (
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
                <span className="text-slate-500">{relativeAge(deal.updatedAt)}</span>
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
            {archivedByType.untyped.map((deal) => (
              <li key={deal.id} className="flex flex-wrap items-center gap-2 text-xs opacity-60" data-archived="true">
                <span className="font-medium text-slate-600">{deal.name}</span>
                <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] text-slate-600">archived</span>
                <button
                  type="button"
                  onClick={() => void handleUnarchive(deal.id)}
                  aria-label={`Unarchive ${deal.name}`}
                  className="rounded border border-slate-300 px-2 py-0.5 text-slate-600 hover:bg-slate-50"
                >
                  Unarchive
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
