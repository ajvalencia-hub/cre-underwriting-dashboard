import { useMemo, useState } from 'react'
import { exportBatchDeck } from '../lib/api'
import { upcomingDeadlines } from '../lib/criticalDates'
import {
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
  applyView,
  deleteView,
  loadViews,
  pipelineToCsv,
  saveView,
  type PipelineSortKey,
  type PipelineView,
} from '../lib/pipelineViews'
import type { Deal, DealStatus } from '../types/deal'

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
}

const BOARD_META: Record<DealType, { title: string; accent: string }> = {
  acquisition: { title: 'Acquisitions', accent: 'text-sky-700' },
  development: { title: 'Developments', accent: 'text-orange-700' },
}

function dealMarket(deal: Deal): string {
  const market = deal.inputs?.market
  return typeof market === 'string' ? market : ''
}

interface BoardProps {
  type: DealType
  deals: Deal[]
  hiddenCount: number
  activeDealId: string | null
  selected: Set<string>
  onToggle: (dealId: string, checked: boolean) => void
  onSelectAll: (dealIds: string[], checked: boolean) => void
  onOpenDeal: (dealId: string) => void
  onStatusChange: (dealId: string, status: DealStatus) => void
  onNewDeal: (type: DealType) => void
}

/** One dealflow board: its own stage chips, counts, and stage dropdowns. */
function Board({
  type, deals, hiddenCount, activeDealId, selected,
  onToggle, onSelectAll, onOpenDeal, onStatusChange, onNewDeal,
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
              <th className="px-3 py-2 font-medium">Deal</th>
              <th className="px-3 py-2 font-medium">Market</th>
              <th className="px-3 py-2 font-medium">Stage</th>
              <th className="px-3 py-2 font-medium">Last touched</th>
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
                  </td>
                  <td className="px-3 py-2 text-slate-500">{dealMarket(deal) || '—'}</td>
                  <td className="px-3 py-2">
                    <select
                      value={deal.status}
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
                  <td className="px-3 py-2 text-slate-500">
                    {relativeAge(deal.updatedAt)}
                    {badge && (
                      <span
                        className={`ml-2 rounded px-1.5 py-0.5 text-[10px] ${
                          badge.tone === 'red'
                            ? 'bg-red-100 text-red-700'
                            : 'bg-amber-100 text-amber-700'
                        }`}
                      >
                        △ {badge.label}
                      </span>
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
                <td colSpan={6} className="px-3 py-6 text-center text-sm text-slate-400">
                  No {type} deals{hiddenCount > 0 ? ' in this view' : ' yet'}.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function PipelinePage({
  deals,
  activeDealId,
  onOpenDeal,
  onStatusChange,
  onBulkStatus,
  onNewDeal,
  onNewDealFromDocuments,
  onSetDealType,
}: PipelinePageProps) {
  const [showTerminal, setShowTerminal] = useState(false)
  const [marketFilter, setMarketFilter] = useState('')
  const [sortKey, setSortKey] = useState<PipelineSortKey>('stage')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkStatusValue, setBulkStatusValue] = useState<DealStatus>('screening')
  const [bulkBusy, setBulkBusy] = useState(false)
  const [views, setViews] = useState<PipelineView[]>(() => loadViews(window.localStorage))
  const [viewName, setViewName] = useState('')
  const [deckBusy, setDeckBusy] = useState(false)
  const [deckNote, setDeckNote] = useState<string | null>(null)

  const sorted = useMemo(
    () => applyView(deals, marketFilter, sortKey, showTerminal),
    [deals, marketFilter, sortKey, showTerminal],
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

  const hiddenCount = deals.length - sorted.length
  const visibleSelected = sorted.filter((d) => selected.has(d.id))
  // Bulk stage choices depend on WHAT is selected: one type -> its stages,
  // mixed -> only the shared stages.
  const bulkOptions = useMemo(() => bulkStageOptions(visibleSelected), [visibleSelected])
  const effectiveBulkValue = bulkOptions.includes(bulkStatusValue)
    ? bulkStatusValue
    : bulkOptions[0]

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

  function handleApplyView(view: PipelineView) {
    setMarketFilter(view.marketFilter)
    setSortKey(view.sortKey)
    setShowTerminal(view.showTerminal)
  }

  function handleSaveView() {
    if (!viewName.trim()) return
    setViews(
      saveView(window.localStorage, {
        name: viewName.trim(),
        marketFilter,
        sortKey,
        showTerminal,
      }),
    )
    setViewName('')
  }

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
          value={marketFilter}
          onChange={(e) => setMarketFilter(e.target.value)}
          placeholder="Filter by market or name"
          className="rounded border border-slate-200 px-2 py-1"
        />
        <label className="flex items-center gap-1 text-slate-500">
          Sort
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as PipelineSortKey)}
            className="rounded border border-slate-200 px-1 py-1"
          >
            <option value="stage">Stage</option>
            <option value="updated">Recently touched</option>
            <option value="name">Name</option>
          </select>
        </label>
        <button
          onClick={() => setShowTerminal(!showTerminal)}
          className={`rounded border px-2 py-1 ${
            showTerminal
              ? 'border-slate-400 bg-slate-100 text-slate-600'
              : 'border-slate-200 text-slate-400 hover:text-slate-600'
          }`}
        >
          {showTerminal
            ? 'Hiding nothing'
            : `Closed/stabilized/dead hidden${hiddenCount ? ` (${hiddenCount})` : ''}`}
        </button>
        <button
          onClick={handleExportCsv}
          className="rounded border border-slate-200 px-2 py-1 text-slate-500 hover:bg-slate-50"
        >
          Export CSV ({sorted.length})
        </button>
        <span className="mx-1 h-4 border-l border-slate-200" />
        {views.map((view) => (
          <span key={view.name} className="flex items-center rounded bg-sky-50 text-sky-700">
            <button onClick={() => handleApplyView(view)} className="px-2 py-1 hover:underline">
              {view.name}
            </button>
            <button
              onClick={() => setViews(deleteView(window.localStorage, view.name))}
              aria-label={`Delete saved view ${view.name}`}
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

      {visibleSelected.length > 0 && (
        <div className="flex items-center gap-2 rounded border border-sky-200 bg-sky-50 px-3 py-2 text-xs">
          <span className="text-sky-700">{visibleSelected.length} selected</span>
          <select
            value={effectiveBulkValue}
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
        hiddenCount={hiddenCount}
        activeDealId={activeDealId}
        selected={selected}
        onToggle={toggle}
        onSelectAll={selectAll}
        onOpenDeal={onOpenDeal}
        onStatusChange={onStatusChange}
        onNewDeal={onNewDeal}
      />

      <Board
        type="development"
        deals={developments}
        hiddenCount={hiddenCount}
        activeDealId={activeDealId}
        selected={selected}
        onToggle={toggle}
        onSelectAll={selectAll}
        onOpenDeal={onOpenDeal}
        onStatusChange={onStatusChange}
        onNewDeal={onNewDeal}
      />

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
