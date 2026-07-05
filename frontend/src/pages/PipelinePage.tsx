import { useMemo, useState } from 'react'
import { exportBatchDeck } from '../lib/api'
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
  onNewDeal: () => void
}

const STATUS_ORDER: DealStatus[] = [
  'screening',
  'underwriting',
  'loi',
  'under_contract',
  'closed',
  'dead',
]

const STATUS_LABELS: Record<DealStatus, string> = {
  screening: 'Screening',
  underwriting: 'Underwriting',
  loi: 'LOI',
  under_contract: 'Under Contract',
  closed: 'Closed',
  dead: 'Dead',
}

const STATUS_STYLES: Record<DealStatus, string> = {
  screening: 'bg-slate-100 text-slate-600',
  underwriting: 'bg-sky-100 text-sky-700',
  loi: 'bg-violet-100 text-violet-700',
  under_contract: 'bg-amber-100 text-amber-700',
  closed: 'bg-emerald-100 text-emerald-700',
  dead: 'bg-slate-200 text-slate-400',
}

function dealMarket(deal: Deal): string {
  const market = deal.inputs?.market
  return typeof market === 'string' ? market : ''
}

export default function PipelinePage({
  deals,
  activeDealId,
  onOpenDeal,
  onStatusChange,
  onBulkStatus,
  onNewDeal,
}: PipelinePageProps) {
  const [showTerminal, setShowTerminal] = useState(false)
  const [marketFilter, setMarketFilter] = useState('')
  const [sortKey, setSortKey] = useState<PipelineSortKey>('stage')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkStatusValue, setBulkStatusValue] = useState<DealStatus>('underwriting')
  const [bulkBusy, setBulkBusy] = useState(false)
  const [views, setViews] = useState<PipelineView[]>(() => loadViews(window.localStorage))
  const [viewName, setViewName] = useState('')
  const [deckBusy, setDeckBusy] = useState(false)
  const [deckNote, setDeckNote] = useState<string | null>(null)

  const sorted = useMemo(
    () => applyView(deals, marketFilter, sortKey, showTerminal),
    [deals, marketFilter, sortKey, showTerminal],
  )

  const counts = useMemo(() => {
    const map = new Map<DealStatus, number>()
    for (const deal of deals) map.set(deal.status, (map.get(deal.status) ?? 0) + 1)
    return map
  }, [deals])

  const hiddenCount = deals.length - sorted.length
  const visibleSelected = sorted.filter((d) => selected.has(d.id))

  function toggle(dealId: string, checked: boolean) {
    const next = new Set(selected)
    if (checked) next.add(dealId)
    else next.delete(dealId)
    setSelected(next)
  }

  async function handleBulk() {
    setBulkBusy(true)
    try {
      await onBulkStatus(
        visibleSelected.map((d) => d.id),
        bulkStatusValue,
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
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-2">
          {STATUS_ORDER.map((status) => (
            <span
              key={status}
              className={`rounded px-2 py-1 text-xs ${STATUS_STYLES[status]} ${
                (counts.get(status) ?? 0) === 0 ? 'opacity-40' : ''
              }`}
            >
              {STATUS_LABELS[status]} · {counts.get(status) ?? 0}
            </span>
          ))}
        </div>
        <button
          onClick={onNewDeal}
          className="shrink-0 rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700"
        >
          New deal
        </button>
      </div>

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
          {showTerminal ? 'Hiding nothing' : `Closed/dead hidden${hiddenCount ? ` (${hiddenCount})` : ''}`}
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
            value={bulkStatusValue}
            onChange={(e) => setBulkStatusValue(e.target.value as DealStatus)}
            className="rounded border border-slate-200 px-1 py-1"
          >
            {STATUS_ORDER.map((status) => (
              <option key={status} value={status}>
                {STATUS_LABELS[status]}
              </option>
            ))}
          </select>
          <button
            onClick={() => void handleBulk()}
            disabled={bulkBusy}
            className="rounded bg-sky-600 px-2 py-1 text-white hover:bg-sky-700 disabled:opacity-40"
          >
            {bulkBusy ? 'Updating…' : 'Set status'}
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

      <div className="overflow-x-auto rounded border border-slate-200 bg-white">
        <table className="w-full min-w-[600px] text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-400">
              <th className="w-8 px-3 py-2">
                <input
                  type="checkbox"
                  aria-label="Select all visible deals"
                  checked={sorted.length > 0 && visibleSelected.length === sorted.length}
                  onChange={(e) =>
                    setSelected(e.target.checked ? new Set(sorted.map((d) => d.id)) : new Set())
                  }
                />
              </th>
              <th className="px-3 py-2 font-medium">Deal</th>
              <th className="px-3 py-2 font-medium">Market</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Last touched</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((deal) => {
              const badge = stalenessBadge(deal.status, deal.updatedAt)
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
                      onChange={(e) => toggle(deal.id, e.target.checked)}
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
                      className={`rounded border-0 px-2 py-1 text-xs ${STATUS_STYLES[deal.status]}`}
                    >
                      {STATUS_ORDER.map((status) => (
                        <option key={status} value={status}>
                          {STATUS_LABELS[status]}
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
            {sorted.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-sm text-slate-400">
                  No deals match this view.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
