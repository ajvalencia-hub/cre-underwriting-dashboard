import { useMemo, useState } from 'react'
import { relativeAge, stalenessBadge } from '../lib/staleness'
import type { Deal, DealStatus } from '../types/deal'

interface PipelinePageProps {
  deals: Deal[]
  activeDealId: string | null
  onOpenDeal: (dealId: string) => void
  onStatusChange: (dealId: string, status: DealStatus) => void
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
  onNewDeal,
}: PipelinePageProps) {
  const [showTerminal, setShowTerminal] = useState(false)

  const sorted = useMemo(() => {
    const filtered = showTerminal
      ? deals
      : deals.filter((d) => d.status !== 'closed' && d.status !== 'dead')
    return [...filtered].sort((a, b) => {
      const stage = STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status)
      return stage !== 0 ? stage : Date.parse(b.updatedAt) - Date.parse(a.updatedAt)
    })
  }, [deals, showTerminal])

  const counts = useMemo(() => {
    const map = new Map<DealStatus, number>()
    for (const deal of deals) map.set(deal.status, (map.get(deal.status) ?? 0) + 1)
    return map
  }, [deals])

  const hiddenCount = deals.length - sorted.length

  return (
    <div className="max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
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

      <div className="overflow-x-auto rounded border border-slate-200 bg-white">
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-400">
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
                <td colSpan={5} className="px-3 py-6 text-center text-sm text-slate-400">
                  No active deals — create one to get started.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {(hiddenCount > 0 || showTerminal) && (
        <button
          onClick={() => setShowTerminal(!showTerminal)}
          className="text-xs text-slate-400 hover:text-slate-600"
        >
          {showTerminal ? 'Hide closed & dead deals' : `Show ${hiddenCount} closed/dead deal(s)`}
        </button>
      )}
    </div>
  )
}
